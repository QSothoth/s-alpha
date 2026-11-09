"""IE22: causal setup queues over the unchanged IE9 filtered universe."""
import argparse
from collections import Counter, defaultdict
from copy import deepcopy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import resource
import sys

import numpy as np

from studies.trader_replication import martin_continue_ie9 as ie9

ie7, prior, old, lib = ie9.ie7, ie9.prior, ie9.old, ie9.lib
ROOT, REPORTS = ie9.ROOT, ie9.REPORTS
WORK = REPORTS / 'ie22_work'
PREFIX = 'strong_continue_ie22_'
PLAN = ROOT / 'studies/martin_luk/notes/PLAN_IE22_CN.md'
PREREG = ROOT / 'studies/martin_luk/notes/PREREG_IE22_CN.md'
KINDS = ('ep', 'breakout', 'pullback')
GROUPS = KINDS + ('other',)
HALVES = ie9.HALVES
SIX_HALVES = tuple(y + 'H' + str(h) for y in (*ie9.YEARS, '2026') for h in (1, 2))
NAMES = KINDS + ('ep_recency', 'ep_gap', 'near_high', 'tightness',
                 'near_ema9', 'near_ema21', 'after_inside')
DEFAULT = dict(ep=['ep_recency', 'near_high'], breakout=['tightness', 'near_high'],
               pullback=['after_inside', 'near_ema9'])
VARIANTS = dict(ep=[['ep_recency', 'near_high'], ['ep_gap', 'near_high'],
                   ['ep_recency', 'ep_gap'], ['ep_recency'], ['near_high']],
    breakout=[['tightness', 'near_high'], ['tightness'], ['near_high'],
              ['after_inside', 'near_high'], ['after_inside', 'tightness']],
    pullback=[['after_inside', 'near_ema9'], ['near_ema9'], ['after_inside'],
              ['after_inside', 'near_ema21'], ['near_ema21']])
SHUFFLE_SEEDS = tuple(range(2026112201, 2026112206))
RANDOM_SEEDS = tuple(range(2026112200, 2026112230))
SENTINEL = old.prior.SENTINEL


def read(name):
    return ie7.read(REPORTS / (PREFIX + name + '.json'))


def write(name, value):
    path = REPORTS / (PREFIX + name + '.json')
    if path.exists():
        raise FileExistsError(path.name + ': reuse the saved artifact')
    old.prior.write_json(path, value)


def stamp():
    return dict(utc=datetime.now(timezone.utc).isoformat(), plan_sha256=prior.file_sha(PLAN),
                prereg_sha256=prior.file_sha(PREREG), source_sha256=prior.file_sha(Path(__file__)))


def setup_values(arrays):
    """A single security, no labels, cross-security data or future observations."""
    o, h, l, c, v = (np.asarray(arrays[k], float) for k in ('o', 'h', 'l', 'c', 'v'))
    amplitude = lib.divide(h, l) - 1
    adr = lib.roll(amplitude, 20)
    e9, e21 = lib.smooth(c, 9), lib.smooth(c, 21)
    near9 = -lib.divide(abs(lib.divide(c, e9) - 1), adr)
    near21 = -lib.divide(abs(lib.divide(c, e21) - 1), adr)
    gap = lib.divide(o, lib.lag(c)) - 1
    volume20 = lib.lag(lib.roll(v, 20))
    ep_event = np.isfinite(gap) & np.isfinite(volume20) & (gap >= .1) & (v >= 2 * volume20)
    age, event_gap = np.full(len(c), np.nan), np.full(len(c), np.nan)
    last = None
    for t in range(len(c)):
        if ep_event[t]:
            last = t
        if last is not None:
            age[t], event_gap[t] = t - last, gap[last]
    high20, high50 = lib.roll(h, 20, 'max'), lib.roll(h, 50, 'max')
    near_high = -np.fmin(lib.divide(abs(lib.divide(c, high20) - 1), adr),
                         lib.divide(abs(lib.divide(c, high50) - 1), adr))
    previous_high = lib.lag(high20)
    new_high = np.isfinite(h) & np.isfinite(previous_high) & (h >= previous_high)
    recent_high = lib.roll(new_high.astype(float), 20, 'max') == 1
    inside = ie9.event((h <= lib.lag(h)) & (l >= lib.lag(l)), h, l, lib.lag(h), lib.lag(l))
    nr = ie9.event(amplitude <= lib.roll(amplitude, 7, 'min'), amplitude, lib.roll(amplitude, 7, 'min'))
    narrow = (inside == 1) | (nr == 1)
    valid = np.isfinite(c) & np.isfinite(h) & np.isfinite(l) & (c > 0) & (l > 0)
    return dict(ep=(valid & (age < 3)).astype(float),
        breakout=(valid & (narrow | (lib.lag(narrow.astype(float)) == 1)) & (near_high >= -1)).astype(float),
        pullback=(valid & (e9 > e21) & (np.fmax(near9, near21) >= -1) & recent_high).astype(float),
        ep_recency=-age, ep_gap=event_gap, near_high=near_high,
        tightness=-lib.divide(amplitude, adr), near_ema9=near9, near_ema21=near21,
        after_inside=lib.lag(inside))


def identity(scheme):
    return {k: v for k, v in scheme.items() if k != 'id'}


def baseline_scheme():
    return dict(id='IE9', classes={}, mode='quota', quota=[0, 0, 0, 5])


def factor_count(scheme):
    return 2 + sum(len(v) for v in scheme['classes'].values())


def validate(scheme):
    if not set(scheme['classes']) <= set(KINDS):
        raise ValueError('unknown setup')
    for factors in scheme['classes'].values():
        if len(factors) > 2 or len(factors) != len(set(factors)) or not set(factors) <= set(NAMES[3:]):
            raise ValueError('factor budget or unregistered factor')
    if scheme['mode'] not in ('quota', 'round_robin', 'proportional'):
        raise ValueError('unregistered allocation')
    if len(scheme['quota']) != 4 or sum(scheme['quota']) != 5 or any(type(n) is not int or n < 0 for n in scheme['quota']):
        raise ValueError('five nonnegative integer slots required')


def merge_queues(queues, fallback, mode, quota):
    """Deduplicate overlapping setup queues and transfer unfilled slots."""
    pointers = [0] * len(GROUPS)
    seen, order = set(), []
    if mode == 'round_robin':
        schedule = list(range(len(KINDS)))
    else:
        if mode == 'proportional':
            counts = np.array([len(q) if i < len(KINDS) else 0 for i, q in enumerate(queues)])
            if not counts.sum():
                return np.asarray(fallback, dtype=np.int32)
            fractions = 5 * counts / counts.sum()
            quota = np.floor(fractions).astype(int)
            for j in np.argsort(-(fractions - quota), kind='stable')[:5 - int(quota.sum())]:
                quota[j] += 1
        schedule = [j for j, n in enumerate(quota) for _ in range(n)]

    def take(j):
        while pointers[j] < len(queues[j]):
            item = int(queues[j][pointers[j]])
            pointers[j] += 1
            if item not in seen:
                seen.add(item)
                order.append(item)
                return True
        return False

    while len(order) < len(fallback):
        before = len(order)
        for j in schedule:
            if not take(j):
                for alternative in range(len(GROUPS)):
                    if take(alternative):
                        break
        if len(order) == before:
            order.extend(int(k) for k in fallback if int(k) not in seen)
            break
    return np.asarray(order, dtype=np.int32)


def rank_night(values, passed, base_values, scheme):
    base_order, _ = ie9.rank_night(base_values, passed, list(ie9.NAMES), ['after_inside', 'near_ema9'])
    if not scheme['classes']:
        order = base_order
    else:
        queues, classified = [], np.zeros(len(passed), bool)
        for kind in KINDS:
            members = passed & (values[:, NAMES.index(kind)] == 1) if kind in scheme['classes'] else np.zeros(len(passed), bool)
            classified |= members
            kept = np.flatnonzero(members)
            score = np.zeros(len(kept), float)
            for name in scheme['classes'].get(kind, []):
                column = values[kept, NAMES.index(name)]
                if name != 'after_inside':
                    column = ie7.night_percentiles(column[:, None])[:, 0]
                score += np.nan_to_num(column, nan=.5)
            queues.append(kept[np.argsort(-score, kind='stable')])
        queues.append(base_order[~classified[base_order]])
        order = merge_queues(queues, base_order, scheme['mode'], scheme['quota'])
    ranks = np.full(len(passed), SENTINEL, np.int32)
    ranks[order] = np.arange(1, len(order) + 1)
    return order, ranks


def coverage(entries, query, ranks, passed):
    result = ie7.coverage(entries, query, ranks, passed)
    main = [r for r in result['rows'] if r['primary']]
    result['halfyear'] = {h: ie7.summarize([r for r in main if ie7.half(r['entry_date']) == h]) for h in SIX_HALVES}
    return result


def expectation(entries, query, passed, widths):
    result = ie9.random_expectation(entries, query, passed, widths)
    result['halfyear'] = {h: dict(n=sum(r['primary'] and ie7.half(r['entry_date']) == h for r in result['rows']),
        union=sum(r['union'] for r in result['rows'] if r['primary'] and ie7.half(r['entry_date']) == h)) for h in SIX_HALVES}
    return result


def score_key(result, halves):
    rows = [r for r in result['coverage']['rows'] if ie7.half(r['entry_date']) in halves]
    return (min(ie7.rate(result['coverage']['halfyear'][h]) for h in halves),
            -factor_count(result['scheme']), sum(r['best_rank'] <= 5 for r in rows))


def coverage_failures(result, baseline, halves):
    failures = []
    for h in halves:
        hits = result['coverage']['halfyear'][h]['hits']['5']
        if hits < baseline['coverage']['halfyear'][h]['hits']['5']:
            failures.append(h + ':below_IE9')
        if hits <= result['expected']['halfyear'][h]['union'] + 1e-10:
            failures.append(h + ':not_above_union')
    return failures


class Data(ie9.Data):
    def __init__(self, full=False):
        super().__init__(full=full)
        self.label = 'full' if full else 'train'
        self.base_values = np.load(ie9.WORK / (self.label + '_features.npy'), mmap_mode='r')
        self.names = list(NAMES)

    def features(self):
        if not hasattr(self, 'values'):
            self.values = np.load(WORK / (self.label + '_features.npy'), mmap_mode='r')
        return self.values

    def predict(self, scheme):
        validate(scheme)
        key = prior.digest(dict(scheme=identity(scheme), end=self.end, source=prior.file_sha(Path(__file__))))
        path = WORK / 'predictions' / (key + '.json')
        if path.exists():
            result = ie7.read(path)
            return dict(result, scheme=scheme)
        ranks_path = path.with_suffix('.npy')
        ranks = np.lib.format.open_memmap(ranks_path, mode='w+', shape=(self.n,), dtype=np.int32)
        ranks[:] = SENTINEL
        selected, values = {}, self.features()
        for day, sl in self.slices.items():
            if day not in self.widths:
                continue
            order, ranks[sl] = rank_night(values[sl], self.passed[sl], self.base_values[sl], scheme)
            selected[day] = [self.meta['scope'][day][k] for k in order[:5]]
        ranks.flush()
        result = dict(scheme=scheme, selected=selected, ranks=str(ranks_path.relative_to(ROOT)), end=self.end,
                      selection_hash=prior.digest(dict(selected=selected, end=self.end)))
        old.prior.write_json(path, result)
        return result

    def result(self, scheme, query=None, halves=None):
        query = self.query if query is None else query
        prediction = self.predict(scheme)
        ranks = np.load(ROOT / prediction['ranks'], mmap_mode='r')
        included = [i for i, e in enumerate(self.entries) if halves is None or ie7.half(e['entry_date']) in halves]
        entries, queries = [self.entries[i] for i in included], [query[i] for i in included]
        c = coverage(entries, queries, ranks, self.passed)
        return dict(scheme=scheme, prediction=prediction['ranks'], selection_hash=prediction['selection_hash'],
                    coverage=c, expected=expectation(entries, queries, self.passed, self.row_width))

    def fixed_accounts(self, scheme, full=False):
        prediction = self.predict(scheme)
        end = self.end if full else prior.TRAIN_END
        selected = {day: codes for day, codes in prediction['selected'].items() if day <= end}
        key = prior.digest(dict(selected=selected, end=end))
        paths = [w / 'accounts' / (key + '.json') for w in (WORK, ie9.WORK, ie9.ie8.WORK, ie7.WORK)]
        for path in paths:
            if path.exists():
                return ie7.read(path)
        original_end = self.end
        try:
            self.end = end
            accounts = self.accounts(selected)
        finally:
            self.end = original_end
        old.prior.write_json(paths[0], accounts)
        return accounts


def prepare(full=False):
    d = Data(full=full)
    marker = WORK / (d.label + '_features.json')
    if marker.exists():
        raise FileExistsError('feature block already prepared')
    path = marker.with_suffix('.npy')
    dest = np.lib.format.open_memmap(path, mode='w+', dtype=np.float32, shape=(d.n, len(NAMES)))
    dest[:] = np.nan
    start = 0
    if full:
        train = np.load(WORK / 'train_features.npy', mmap_mode='r')
        start = len(train)
        for a in range(0, start, 4096):
            dest[a:a + min(4096, start - a)] = train[a:a + min(4096, start - a)]
        del train
    bycode = defaultdict(list)
    di = {day: t for t, day in enumerate(d.meta['days'])}
    for day, sl in d.slices.items():
        if sl.start >= start:
            for k, code in enumerate(d.meta['scope'][day]):
                bycode[code].append((di[day], sl.start + k))
    stop = int(np.searchsorted(d.meta['days'], d.end, side='right'))
    inputs = {}
    for count, (code, positions) in enumerate(bycode.items()):
        source = old.WORK / 'stocks' / (code + '.npz')
        inputs[str(source.relative_to(ROOT))] = prior.file_sha(source)
        with np.load(source) as z:
            arrays = {k: z[k][:stop] for k in ('o', 'h', 'l', 'c', 'v')}
        values = setup_values(arrays)
        ts, rows = map(np.asarray, zip(*positions))
        for j, name in enumerate(NAMES):
            dest[rows, j] = values[name][ts]
        if count % 300 == 0:
            print('setup stock', count, '/', len(bycode), flush=True)
    dest.flush()
    old.prior.write_json(marker, dict(**stamp(), names=list(NAMES), rows=d.n, end=d.end,
        input_sha256=inputs, feature_sha256=prior.file_sha(path), copied_training_rows=start,
        dataset_digest=d.meta['dataset_digest']))


def qualify(d, result, baseline, halves):
    failures = coverage_failures(result, baseline, halves)
    result = dict(result, score=list(score_key(result, halves)), failures=failures,
                  eligible=False, account_veto='not_evaluated_coverage_failed')
    if not failures:
        accounts = d.fixed_accounts(result['scheme'])
        ok, account_failures = ie7.eligible(accounts)
        result.update(accounts=accounts, eligible=ok, failures=account_failures, account_veto='evaluated')
    return result


def winner(results, halves):
    return max([r for r in results if r['eligible']] or results, key=lambda r: score_key(r, halves))


def funnel(d, result, query, halves):
    rows = [r for r in result['coverage']['rows'] if r['primary'] and ie7.half(r['entry_date']) in halves]
    lookup = {e['id']: qs for e, qs in zip(d.entries, query)}
    by_class, missed, classified, other_hits = Counter(), Counter(), 0, 0
    for row in rows:
        qs = [q for q in lookup[row['id']] if q >= 0 and d.passed[q]]
        kinds = [k for k in KINDS if any(d.features()[q, NAMES.index(k)] == 1 for q in qs)]
        classified += bool(kinds)
        for kind in kinds or ['other']:
            by_class[kind] += 1
        if row['passed_gate'] and row['best_rank'] > 5:
            missed[(kinds or ['other'])[0]] += 1
        if not kinds and row['best_rank'] <= 5:
            other_hits += 1
    n, scope, filtered = len(rows), sum(r['in_scope'] for r in rows), sum(r['passed_gate'] for r in rows)
    hits = sum(r['best_rank'] <= 5 for r in rows)
    losses = dict(scope=n - scope, filters=scope - filtered, ranking=filtered - hits)
    return dict(n=n, scope=scope, filtered=filtered, classified=classified, other=filtered - classified,
        by_class=dict(by_class), top5=hits, other_top5=other_hits, missed_by_class={k: missed[k] for k in GROUPS},
        losses=losses, largest=max(losses, key=losses.get),
        target=max(GROUPS, key=lambda k: missed[k]))


def allocations(target):
    if target == 'other':
        return [[1, 1, 2, 1], [1, 2, 1, 1], [2, 1, 1, 1], [1, 1, 1, 2], [0, 1, 2, 2]]
    j = KINDS.index(target)
    others = [k for k in range(3) if k != j]
    result = []
    for own, a, b, rest in ((3, 1, 1, 0), (2, 2, 1, 0), (2, 1, 2, 0), (2, 1, 1, 1), (3, 1, 0, 1)):
        quota = [0, 0, 0, rest]
        quota[j], quota[others[0]], quota[others[1]] = own, a, b
        result.append(quota)
    return result


def propose(number, anchor=None, target=None):
    base = dict(classes=deepcopy(DEFAULT), mode='quota', quota=[1, 2, 2]) if anchor is None else identity(deepcopy(anchor))
    candidates = []
    if number == 1:
        for mode, quota in (('quota', [1, 2, 2, 0]), ('quota', [2, 2, 1, 0]),
                            ('quota', [1, 1, 3, 0]), ('round_robin', [2, 2, 1, 0]),
                            ('proportional', [1, 2, 2, 0])):
            candidates.append(dict(base, mode=mode, quota=quota))
    elif number == 3 or target == 'other':
        candidates = [dict(base, mode='quota', quota=q) for q in allocations(target)]
    else:
        for factors in VARIANTS[target]:
            candidate = deepcopy(base)
            candidate['classes'][target] = factors.copy()
            candidates.append(candidate)
    return [dict(s, id=f'R{number}{chr(65 + i)}') for i, s in enumerate(candidates)]


def ablate(d, start, baseline, halves, query):
    current, rounds = start, []
    while True:
        candidates = []
        for kind in KINDS:
            for i, factor in enumerate(current['scheme']['classes'].get(kind, [])):
                scheme = deepcopy(current['scheme'])
                del scheme['classes'][kind][i]
                candidates.append((kind + ':' + factor, scheme))
        for kind in KINDS:
            if kind in current['scheme']['classes']:
                scheme = deepcopy(current['scheme'])
                del scheme['classes'][kind]
                candidates.append(('merge:' + kind, scheme))
        trials, accepted = [], False
        for removed, scheme in candidates:
            scheme['id'] = current['scheme']['id'] + '-drop-' + removed.replace(':', '-')
            after = qualify(d, d.result(scheme, query, halves=halves), baseline, halves)
            accept = (score_key(after, halves)[0] >= score_key(current, halves)[0] and
                      (not current['eligible'] or after['eligible']))
            trials.append(dict(removed=removed, result=after, accepted=bool(accept)))
            if accept:
                current, accepted = after, True
                break
        rounds.append(dict(trials=trials))
        if not accepted:
            return dict(initial=start, rounds=rounds, final=current)


def run_selection(d, halves=HALVES, query=None, save=False):
    query = d.query if query is None else query
    baseline = d.result(baseline_scheme(), query, halves=halves)
    baseline = qualify(d, baseline, baseline, halves)
    rounds, all_results, seen, anchor, target = [], [], set(), None, None
    for number in range(1, 5):
        spec = dict(round=number, target_layer='ranking', target_class=target,
                    reason='固定初始分类排名与五种名额' if number == 1 else '仅修改上一轮掉票最多类别的排名或名额',
                    schemes=[])
        for candidate in propose(number, anchor, target):
            key = prior.digest(identity(candidate))
            if key not in seen:
                seen.add(key)
                spec['schemes'].append(candidate)
        if not spec['schemes']:
            break
        reg = dict(spec=spec, prereg_text=PREREG.read_text(encoding='utf-8'), **stamp())
        if save:
            write(f'round{number}_registration', reg)
        results = []
        for scheme in spec['schemes']:
            result = qualify(d, d.result(scheme, query, halves=halves), baseline, halves)
            result['funnel'] = funnel(d, result, query, halves)
            results.append(result)
            if save:
                print(scheme['id'], result['score'], result['eligible'], result['funnel'], flush=True)
        best = winner(results, halves)
        rd = dict(registration=reg, results=results, winner=best)
        rounds.append(rd)
        all_results.extend(results)
        if save:
            write(f'round{number}', rd)
        anchor, target = best['scheme'], best['funnel']['target']
        if best['funnel']['largest'] != 'ranking':
            break
    allowed = [r for r in all_results if r['eligible']]
    chosen = winner(allowed, halves) if allowed else baseline
    ablation = ablate(d, chosen, baseline, halves, query)
    exploratory = None
    if not allowed and all_results:
        exploratory = ablate(d, winner(all_results, halves), baseline, halves, query)
    return dict(baseline=baseline, rounds=rounds, candidates=len(all_results),
                ablation=ablation, exploratory_ablation=exploratory, fallback=not bool(allowed), final=ablation['final'])


def describe(d):
    baseline = d.predict(baseline_scheme())
    base_ranks = np.load(ROOT / baseline['ranks'], mmap_mode='r')
    di = {day: i for i, day in enumerate(d.meta['days'])}
    rows, setup_counts, lost = [], defaultdict(Counter), Counter()
    stop = int(np.searchsorted(d.meta['days'], d.end, side='right'))
    for entry, qs in zip(d.entries, d.query):
        if entry['target']['tier'] != 'primary':
            continue
        source = old.WORK / 'stocks' / (entry['code'] + '.npz')
        with np.load(source) as z:
            own = setup_values({k: z[k][:stop] for k in ('o', 'h', 'l', 'c', 'v')})
        nights, union, filtered_union = [], set(), set()
        for signal, q in zip(entry['systems']['h4'], qs):
            day = signal['date']
            t = di[day]
            kinds = [k for k in KINDS if own[k][t] == 1]
            union.update(kinds)
            passed = q >= 0 and bool(d.passed[q])
            if passed:
                filtered_union.update(kinds)
            ranks = {}
            if passed:
                sl = d.slices[day]
                for kind in kinds:
                    members = np.flatnonzero(d.passed[sl] & (d.features()[sl, NAMES.index(kind)] == 1)) + sl.start
                    ranks[kind] = 1 + int(np.count_nonzero(base_ranks[members] < base_ranks[q]))
            nights.append(dict(date=day, classes=kinds or ['other'], in_scope=q >= 0, filtered=passed,
                ie9_rank=int(base_ranks[q]) if passed else None, within_class_ie9=ranks))
        valid = [q for q in qs if q >= 0 and d.passed[q]]
        best = min((int(base_ranks[q]) for q in valid), default=SENTINEL)
        missed = bool(valid) and best > 5
        group = next((k for k in KINDS if k in filtered_union), 'other')
        if missed:
            lost[group] += 1
        for kind in union or {'other'}:
            setup_counts[entry['setup']][kind] += 1
        rows.append(dict(id=entry['id'], code=entry['code'], entry_date=entry['entry_date'],
            setup=entry['setup'], classes=sorted(union) or ['other'], filtered_classes=sorted(filtered_union) or ['other'],
            prior_night=nights[-1]['classes'], nights=nights, best_ie9_rank=best,
            ranking_lost=missed, assigned_loss_class=group if missed else None))
    widths = {k: {} for k in GROUPS}
    for day, sl in d.slices.items():
        if day not in d.widths:
            continue
        flags = d.features()[sl, :len(KINDS)] == 1
        for j, kind in enumerate(KINDS):
            widths[kind][day] = int(np.count_nonzero(d.passed[sl] & flags[:, j]))
        widths['other'][day] = int(np.count_nonzero(d.passed[sl] & ~flags.any(axis=1)))
    def stats(values):
        return dict(n=len(values), minimum=min(values), median=float(np.median(values)),
                    q25=float(np.percentile(values, 25)), q75=float(np.percentile(values, 75)), maximum=max(values))
    summary = {kind: {h: stats([n for day, n in widths[kind].items() if ie7.half(day) == h]) for h in HALVES} for kind in GROUPS}
    mismatch = []
    for setup, counts in setup_counts.items():
        sample = [r for r in rows if r['setup'] == setup]
        other = sum(r['classes'] == ['other'] for r in sample)
        if other > len(sample) / 2:
            mismatch.append(dict(setup=setup, other=other, n=len(sample)))
    return dict(rows=rows, setup_cross={k: dict(v) for k, v in setup_counts.items()},
                nightly_widths=widths, width_summary=summary, ranking_lost_by_class=dict(lost),
                definition_problems=mismatch, **stamp())


def shuffled_query(d, seed):
    rng = np.random.default_rng(seed)
    mapping = np.arange(d.n, dtype=np.int32)
    for sl in d.slices.values():
        kept = np.flatnonzero(d.passed[sl]) + sl.start
        mapping[kept] = rng.permutation(kept)
    return [[int(mapping[q]) if q >= 0 else -1 for q in qs] for qs in d.query]


def shuffle_stage():
    actual = read('selection')['final']
    d, controls = Data(), []
    for seed in SHUFFLE_SEEDS:
        value = run_selection(d, query=shuffled_query(d, seed))
        value['seed'] = seed
        write('shuffle_' + str(seed), value)
        controls.append(dict(seed=seed, score=value['final']['score'],
            coverage=value['final']['coverage']['primary'], fallback=value['fallback']))
        print('shuffle', seed, value['final']['score'], flush=True)
    write('shuffle', dict(controls=controls, actual_score=actual['score'],
        passed=all(actual['score'][0] > r['score'][0] for r in controls), **stamp()))


def freeze():
    selection = read('selection')
    write('frozen_selection', dict(final=selection['final'], fallback=selection['fallback'],
        shuffle=read('shuffle'), selection_years=list(ie9.YEARS), exam_used_for_selection=False,
        feature_sha256=ie7.read(WORK / 'train_features.json')['feature_sha256'], **stamp()))


def random_controls(d, actual, baseline):
    records = []
    for seed in RANDOM_SEEDS:
        rng = np.random.default_rng(seed)
        ranks = np.full(d.n, SENTINEL, np.int32)
        for sl in d.slices.values():
            kept = np.flatnonzero(d.passed[sl]) + sl.start
            ranks[rng.permutation(kept)] = np.arange(1, len(kept) + 1)
        c = coverage(d.entries, d.query, ranks, d.passed)
        records.append(dict(seed=seed, coverage=c))
    def place(value, samples):
        return dict(actual=value, rank=1 + sum(n > value for n in samples),
                    ties=sum(n == value for n in samples), mean=float(np.mean(samples)),
                    minimum=min(samples), maximum=max(samples), trials=len(samples))
    placements = {}
    for label, r in (('ie22', actual), ('ie9', baseline)):
        placements[label] = {y: place(r['coverage']['annual'][y]['primary']['hits']['5'],
            [record['coverage']['annual'][y]['primary']['hits']['5'] for record in records]) for y in (*ie9.YEARS, '2026')}
        placements[label]['combined'] = place(sum(r['coverage']['annual'][y]['primary']['hits']['5'] for y in ie9.YEARS),
            [sum(record['coverage']['annual'][y]['primary']['hits']['5'] for y in ie9.YEARS) for record in records])
    return dict(records=records, placements=placements, seeds=list(RANDOM_SEEDS))


def final_stage():
    if (REPORTS / (PREFIX + 'final.json')).exists():
        raise FileExistsError('formal final already evaluated')
    frozen = read('frozen_selection')
    if frozen['source_sha256'] != prior.file_sha(Path(__file__)):
        raise ValueError('source changed after freeze')
    prepare(full=True)
    d = Data(full=True)
    scheme = frozen['final']['scheme']
    result, baseline = d.result(scheme), d.result(baseline_scheme())
    train_predictions = Data().predict(scheme)['selected']
    if {day: codes for day, codes in d.predict(scheme)['selected'].items() if day <= prior.TRAIN_END} != train_predictions:
        raise AssertionError('future data changed historical selections')
    result['accounts'] = d.fixed_accounts(scheme, full=True)
    result['funnel'] = {h: funnel(d, result, d.query, [h]) for h in SIX_HALVES}
    result['training'] = frozen['final']
    result['note'] = '2026反复看过，不是干净考试；冻结后只报告，不据此调参。'
    result['baseline'] = baseline
    result['baseline_accounts'] = d.fixed_accounts(baseline_scheme(), full=True)
    result['nightly_widths'] = d.widths
    result.update(stamp())
    write('final', result)
    write('random_final', random_controls(d, result, baseline))
    print('final', result['coverage']['primary'], flush=True)


def leave_one_out():
    if not (REPORTS / (PREFIX + 'final.json')).exists():
        raise ValueError('six-half diagnostic follows the frozen formal evaluation')
    d, records = Data(full=True), []
    baseline = d.result(baseline_scheme())
    for held in SIX_HALVES:
        halves = [h for h in SIX_HALVES if h != held]
        path = REPORTS / (PREFIX + 'loo_' + held + '.json')
        if path.exists():
            value = ie7.read(path)
        else:
            value = run_selection(d, halves=halves)
            held_result = d.result(value['final']['scheme'], halves=[held])
            value.update(held_out=held, training_halves=halves,
                held_result=held_result['coverage']['halfyear'][held],
                baseline_held=baseline['coverage']['halfyear'][held], **stamp())
            write('loo_' + held, value)
        records.append({k: value[k] for k in ('held_out', 'held_result', 'baseline_held', 'fallback')})
        records[-1]['scheme'] = value['final']['scheme']
        print('held', held, value['held_result'], value['fallback'], flush=True)
    hits = {str(k): sum(r['held_result']['hits'][str(k)] for r in records) for k in ie9.TOPS}
    base_hits = {str(k): sum(r['baseline_held']['hits'][str(k)] for r in records) for k in ie9.TOPS}
    write('loo', dict(records=records, hits=hits, baseline_hits=base_hits,
        n=sum(r['held_result']['n'] for r in records), passed=hits['5'] > base_hits['5'],
        note='冻结后的六半年留一诊断，包含已反复看过的部分2026；不反调主方案。', **stamp()))


def guard():
    def allowed(path):
        p = Path(os.fsdecode(path)).resolve()
        return p.is_relative_to(WORK.resolve()) or (p.parent == REPORTS.resolve() and p.name.startswith(PREFIX))

    def audit(name, args):
        if name == 'open':
            path, _, flags = args
            if not isinstance(path, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND) and not allowed(path):
                raise PermissionError('IE22 output boundary: ' + os.fsdecode(path))
        if name in ('socket.connect', 'socket.bind', 'os.system', 'subprocess.Popen'):
            raise PermissionError('IE22 offline single process')
        if name in ('os.remove', 'os.rename', 'os.rmdir', 'os.mkdir'):
            paths = args[:2] if name == 'os.rename' else args[:1]
            if any(not allowed(path) for path in paths):
                raise PermissionError('IE22 output boundary')
    sys.addaudithook(audit)


def main(stage):
    WORK.mkdir(exist_ok=True)
    for name in ('tmp', 'predictions', 'accounts'):
        (WORK / name).mkdir(exist_ok=True)
    os.environ['TMPDIR'] = str(WORK / 'tmp')
    import tempfile
    tempfile.tempdir = str(WORK / 'tmp')
    guard()
    if stage == 'prepare':
        prepare()
    elif stage == 'describe':
        result = describe(Data())
        write('description', result)
        print('description', result['ranking_lost_by_class'], result['definition_problems'], flush=True)
    elif stage == 'select':
        value = run_selection(Data(), save=True)
        write('selection', value)
        print('selection', value['final']['scheme'], value['final']['score'], 'fallback', value['fallback'], flush=True)
    else:
        dict(shuffle=shuffle_stage, freeze=freeze, final=final_stage, loo=leave_one_out)[stage]()
    write('runtime_' + stage, dict(**stamp(), peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('stage', choices=('prepare', 'describe', 'select', 'shuffle', 'freeze', 'final', 'loo'))
    main(parser.parse_args().stage)
