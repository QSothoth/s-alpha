"""IE7: offline half-year stability, small equal-rank models and yearwise selection."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import resource
import sys

import numpy as np

from studies.trader_replication import martin_continue_ie6 as prior

old = prior.old
ROOT, REPORTS = old.ROOT, old.REPORTS
WORK = REPORTS / 'ie7_work'
PREFIX = 'strong_continue_ie7_'
PLAN = ROOT / 'studies/martin_luk/notes/PLAN_IE7_CN.md'
PREREG = ROOT / 'studies/martin_luk/notes/PREREG_IE7_CN.md'
YEARS = prior.YEARS
HALVES = tuple(f'{y}H{h}' for y in YEARS for h in (1, 2))
TOPS = (1, 3, 5, 10)
SEED = 20261107


def read(path):
    return prior.read(path)


def write(name, value):
    old.prior.write_json(REPORTS / (PREFIX + name + '.json'), value)


def half(day):
    return day[:4] + ('H1' if day[5:7] <= '06' else 'H2')


def night_percentiles(raw):
    out = old.prior.percentile(raw)
    out[~np.isfinite(raw)] = np.nan
    return out


def stability(medians):
    values = np.array([np.nan if x is None else x for x in medians])
    if np.all(values >= .65):
        return 'stable', 1
    if np.all(values <= .35):
        return 'stable', -1
    strong = int(np.count_nonzero(np.abs(values - .5) >= .15 - 1e-7))
    return ('unstable' if strong in (1, 2) else 'mixed_or_weak'), 0


def describe(pct, entries, query, names):
    """Only evaluation queries supply labels; the matrix has pre-gate nightly ranks."""
    rows = []
    for j, name in enumerate(names):
        row = dict(name=name, halves={})
        for h in HALVES:
            indices = [i for i, e in enumerate(entries) if half(e['entry_date']) == h]
            per_entry, pooled = [], []
            missing = outside = 0
            for i in indices:
                samples = []
                for q in query[i]:
                    if q < 0:
                        outside += 1
                    elif np.isfinite(pct[q, j]):
                        samples.append(float(pct[q, j]))
                    else:
                        missing += 1
                if samples:
                    per_entry.append(float(np.median(samples)))
                    pooled.extend(samples)
            row['halves'][h] = dict(n=len(indices), valid_entries=len(per_entry),
                valid_nights=len(pooled), missing_nights=missing, outside_nights=outside,
                median=float(np.median(per_entry)) if per_entry else None,
                pooled_median=float(np.median(pooled)) if pooled else None)
        medians = [row['halves'][h]['median'] for h in HALVES]
        row['status'], row['direction'] = stability(medians)
        row['allowed'] = name not in ('raw_price', 'observed_sessions')
        row['worst_half_distance'] = min(abs(x - .5) for x in medians) if all(x is not None for x in medians) else None
        rows.append(row)
    return rows


def stable_rows(description):
    return sorted((r for r in description if r['status'] == 'stable' and r['allowed']),
                  key=lambda r: (-r['worst_half_distance'], r['name']))


def summarize(rows):
    return dict(n=len(rows), hits={str(k): sum(r['best_rank'] <= k for r in rows) for k in TOPS},
        scope=sum(r['in_scope'] for r in rows), gated=sum(r['passed_gate'] for r in rows))


def coverage(entries, query, ranks, passed):
    rows = []
    for e, qs in zip(entries, query):
        valid = [q for q in qs if q >= 0]
        rows.append(dict(id=e['id'], code=e['code'], entry_date=e['entry_date'],
            primary=e['target']['tier'] == 'primary', in_scope=bool(valid),
            passed_gate=any(passed[q] for q in valid),
            best_rank=min((int(ranks[q]) for q in valid), default=old.prior.SENTINEL)))
    primary = [r for r in rows if r['primary']]
    return dict(primary=summarize(primary), all_entries=summarize(rows), rows=rows,
        annual={y: dict(primary=summarize([r for r in primary if r['entry_date'].startswith(y)]),
                         all_entries=summarize([r for r in rows if r['entry_date'].startswith(y)])) for y in (*YEARS, '2026')},
        halfyear={h: summarize([r for r in primary if half(r['entry_date']) == h]) for h in HALVES})


def rate(summary):
    return summary['hits']['5'] / summary['n'] if summary['n'] else 0.


def coverage_key(result):
    c = result['coverage']
    return (min(rate(c['annual'][y]['primary']) for y in YEARS),
            -len(result['scheme']['factors']), min(rate(c['halfyear'][h]) for h in HALVES))


def eligible(accounts):
    failures = []
    for label, account in accounts.items():
        for year in YEARS:
            row = account['annual'].get(year, {})
            if row.get('entries', 0) < 52:
                failures.append(label + ':' + year + ':entries<52')
            if row.get('win') is None or row['win'] > .35:
                failures.append(label + ':' + year + ':win>35% or undefined')
    return not failures, failures


def winner(results):
    allowed = [r for r in results if r['eligible']]
    return max(allowed or results, key=coverage_key)


def losses(result):
    c = result['coverage']['primary']
    counts = dict(scope=c['n'] - c['scope'], gate=c['scope'] - c['gated'], ranking=c['gated'] - c['hits']['5'])
    return dict(counts=counts, largest=max(counts, key=counts.get))


def validate_scheme(scheme, stable):
    directions = {r['name']: r['direction'] for r in stable}
    factors = scheme['factors']
    if not 1 <= len(factors) <= 5 or len(scheme['gates']) > 3:
        raise ValueError('scheme exceeds the task limits')
    if len({f['name'] for f in factors}) != len(factors):
        raise ValueError('duplicate ranking factor')
    for f in factors:
        if directions.get(f['name']) != f['direction']:
            raise ValueError('ranking factor is not stable in this direction')
    for g in scheme['gates']:
        if g['name'] not in directions or g['form'] not in ('raw', 'pct'):
            raise ValueError('gate is not a stable feature')


def rank_night(raw, pct, names, scheme):
    score = np.zeros(len(raw), np.float32)
    for f in scheme['factors']:
        p = pct[:, names.index(f['name'])]
        p = np.where(np.isfinite(p), p, .5)
        score += p if f['direction'] > 0 else 1 - p
    if scheme['factors']:
        score /= len(scheme['factors'])
    passed = np.ones(len(raw), bool)
    for g in scheme['gates']:
        j = names.index(g['name'])
        passed &= prior.condition_mask(raw[:, j] if g['form'] == 'raw' else pct[:, j], g, missing_pass=False)
    order = np.argsort(-score, kind='stable')
    order = order[passed[order]]
    ranks = np.full(len(raw), old.prior.SENTINEL, np.int32)
    ranks[order] = np.arange(1, len(order) + 1)
    return order, ranks, passed


class Data:
    def __init__(self, full=False, shuffled=False):
        self.meta = read(old.WORK / 'prepared.json')
        self.end = self.meta['prepared_last'] if full else prior.TRAIN_END
        self.names = read(old.FROZEN)['raw_feature_names']
        self.raw = np.load(old.WORK / 'raw.npy', mmap_mode='r')
        self.slices = {}
        offset = 0
        for day, codes in sorted(self.meta['scope'].items()):
            if day <= self.end:
                self.slices[day] = slice(offset, offset + len(codes))
            offset += len(codes)
        self.n = max(sl.stop for sl in self.slices.values())
        self.entries = [r for r in self.meta['entries'] if r['entry_date'] <= self.end]
        rng = np.random.default_rng(SEED)
        mapping = {day: rng.permutation(sl.stop - sl.start) for day, sl in self.slices.items()} if shuffled else {}
        self.query = []
        for entry in self.entries:
            qs = []
            for event in entry['systems']['h4']:
                day = event['date']
                codes = self.meta['scope'][day]
                k = codes.index(entry['code']) if entry['code'] in codes else -1
                if shuffled and k >= 0:
                    k = int(mapping[day][k])
                qs.append(self.slices[day].start + k if k >= 0 else -1)
            self.query.append(qs)
        if any(len(q) != 4 for q in self.query):
            raise ValueError('expected four prior signal nights')

    def percentiles(self):
        name = 'full_pct.npy' if self.end > prior.TRAIN_END else 'train_pct.npy'
        path = WORK / name
        if path.exists():
            return np.load(path, mmap_mode='r')
        temp = path.with_suffix('.tmp.npy')
        out = np.lib.format.open_memmap(temp, mode='w+', dtype=np.float32,
                                        shape=(self.n, len(self.names)))
        trained = np.load(WORK / 'train_pct.npy', mmap_mode='r') if name == 'full_pct.npy' else None
        for day, sl in self.slices.items():
            out[sl] = trained[sl] if trained is not None and day <= prior.TRAIN_END else night_percentiles(self.raw[sl])
        out.flush()
        del out
        temp.replace(path)
        return np.load(path, mmap_mode='r')

    def select(self, scheme):
        pct = self.percentiles()
        ranks = np.full(self.n, old.prior.SENTINEL, np.int32)
        passed = np.zeros(self.n, bool)
        selected, widths = {}, {}
        for day, sl in self.slices.items():
            if day < self.meta['first_signal']:
                continue
            order, ranks[sl], passed[sl] = rank_night(self.raw[sl], pct[sl], self.names, scheme)
            codes = self.meta['scope'][day]
            selected[day] = [codes[k] for k in order[:5]]
            widths[day] = len(order)
        return selected, widths, coverage(self.entries, self.query, ranks, passed)

    def accounts(self, selected):
        if not hasattr(self, 'inputs'):
            d, px, rules, ema = old.load_account_inputs()
            d.A = {name: np.asarray(a) for name, a in d.A.items()}
            px = {name: np.asarray(a) for name, a in px.items()}
            ema = {label: {name: np.asarray(a) for name, a in arrays.items()} for label, arrays in ema.items()}
            self.inputs = d, px, rules, ema
        d, px, rules, ema = self.inputs
        orders = old.selected_orders(d, selected, window=(old.panels.WINDOW[0], self.end))
        book, _, _ = old.hc.make_books(d, orders, old.hh.observations(d, orders), True)
        return {label: prior.account(d, px, ema[label], rule, book, self.meta, end=self.end)
                for label, rule in rules.items()}

    def evaluate(self, scheme, label='true'):
        key = prior.digest(dict(scheme=scheme, end=self.end, label=label))
        path = WORK / 'evaluations' / (key + '.json')
        if path.exists():
            return read(path)
        selected, widths, c = self.select(scheme)
        account_key = prior.digest(dict(selected=selected, end=self.end))
        cache = WORK / 'accounts' / (account_key + '.json')
        if cache.exists():
            accounts = read(cache)
        else:
            accounts = self.accounts(selected)
            old.prior.write_json(cache, accounts)
        ok, failures = eligible(accounts)
        value = dict(scheme=scheme, coverage=c, accounts=accounts, eligible=ok, failures=failures,
            selection_hash=account_key, selected=selected, nightly_widths=widths)
        value['score'] = list(coverage_key(value))
        value['losses'] = losses(value)
        old.prior.write_json(path, value)
        return value


def description_stage(shuffled=False):
    d = Data(shuffled=shuffled)
    pct = d.percentiles()
    main = [i for i, e in enumerate(d.entries) if e['target']['tier'] == 'primary']
    primary = describe(pct, [d.entries[i] for i in main], [d.query[i] for i in main], d.names)
    all_entries = describe(pct, d.entries, d.query, d.names)
    gates = read(REPORTS / (prior.PREFIX + 'candidate_pool.json'))['gates']
    label = 'shuffle' if shuffled else 'true'
    result = dict(primary=primary, all_entries=all_entries, stable_order=[r['name'] for r in stable_rows(primary)],
        candidate_mapping=[dict(id=g['id'], name=g['name'], form=g['form'], description_index=d.names.index(g['name'])) for g in gates],
        raw_values=len(d.names), candidate_conditions=len(gates),
        distinct_candidate_values=len({(g['name'], g['form']) for g in gates}),
        percentile_variant_note='同晚百分位本身即描述值，与原值的同晚百分位相同；保留全部候选映射。',
        years=list(YEARS), seed=SEED if shuffled else None)
    write(label + '_description', result)
    print(label, 'stable:', [(r['name'], r['direction'], round(r['worst_half_distance'], 3)) for r in stable_rows(primary)], flush=True)


def run_round(number):
    spec = read(WORK / f'round{number}.json')
    stable = stable_rows(read(REPORTS / (PREFIX + 'true_description.json'))['primary'])
    if not 1 <= len(spec['schemes']) <= 5:
        raise ValueError('invalid round size')
    if number > 1:
        previous = read(REPORTS / (PREFIX + f'round{number - 1}.json'))
        if spec['target_layer'] != previous['winner']['losses']['largest']:
            raise ValueError('next round must target the largest loss layer')
    registration = dict(spec=spec, spec_sha256=prior.file_sha(WORK / f'round{number}.json'),
        prereg_sha256=prior.file_sha(PREREG), plan_sha256=prior.file_sha(PLAN),
        utc=datetime.now(timezone.utc).isoformat())
    write(f'round{number}_registration', registration)
    d = Data()
    results = []
    for scheme in spec['schemes']:
        validate_scheme(scheme, stable)
        result = d.evaluate(scheme)
        results.append(result)
        print(scheme['id'], result['score'], 'eligible', result['eligible'], 'losses', result['losses'], flush=True)
    best = winner(results)
    write(f'round{number}', dict(registration=registration, results=results, winner=best))
    print('WINNER', best['scheme']['id'], best['score'], flush=True)


def ablate(d, start, label='true'):
    current, rounds = start, []
    while True:
        trials = []
        removed = None
        for field in ('factors', 'gates'):
            for k, item in enumerate(current['scheme'][field]):
                scheme = json.loads(json.dumps(current['scheme']))
                del scheme[field][k]
                scheme['id'] = current['scheme']['id'] + f'-{field}{k}'
                after = d.evaluate(scheme, label)
                accept = coverage_key(after)[0] >= coverage_key(current)[0]
                trials.append(dict(field=field, removed=item, result=after, accepted=accept))
                if accept:
                    removed, current = item, after
                    break
            if removed is not None:
                break
        rounds.append(dict(trials=trials))
        if removed is None:
            break
    return dict(initial=start, rounds=rounds, final=current)


def ablation_stage():
    rounds = [read(p) for p in sorted(REPORTS.glob(PREFIX + 'round[123].json'))]
    best = winner([r for rd in rounds for r in rd['results']])
    result = ablate(Data(), best)
    write('ablation', result)
    print('ABLATION', result['final']['scheme'], result['final']['score'], flush=True)


def shuffle_stage():
    description_stage(True)
    real = stable_rows(read(REPORTS / (PREFIX + 'true_description.json'))['primary'])
    shuffled = stable_rows(read(REPORTS / (PREFIX + 'shuffle_description.json'))['primary'])
    position = {r['name']: i for i, r in enumerate(real)}
    d = Data(shuffled=True)
    results, unavailable = [], []
    for path in sorted(WORK.glob('round[123].json')):
        spec = read(path)
        for original in spec['schemes']:
            scheme = json.loads(json.dumps(original))
            needed = [position[f['name']] for f in scheme['factors'] + scheme['gates']]
            if max(needed, default=-1) >= len(shuffled):
                unavailable.append(original['id'])
                continue
            for f in scheme['factors'] + scheme['gates']:
                index = position[f['name']]
                row = shuffled[index]
                if 'direction' not in f and row['direction'] != real[index]['direction']:
                    lower, upper = f['lower'], f['upper']
                    f['lower'] = None if upper is None else 1 - upper
                    f['upper'] = None if lower is None else 1 - lower
                f['name'] = row['name']
                if 'direction' in f:
                    f['direction'] = row['direction']
            # Gate structures use percentiles so their common thresholds transfer.
            validate_scheme(scheme, shuffled)
            results.append(d.evaluate(scheme, 'shuffle'))
    if results:
        result = ablate(d, winner(results), 'shuffle')
        write('shuffle', dict(seed=SEED, stable=len(shuffled), results=results, unavailable=unavailable, ablation=result,
                              final=result['final'], fallback=False))
    else:
        scheme = dict(id='no_stable_feature_tie_baseline', factors=[], gates=[])
        result = d.evaluate(scheme, 'shuffle')
        write('shuffle', dict(seed=SEED, stable=len(shuffled), results=[], unavailable=unavailable,
                              final=result, fallback=True, note='无可用的同结构稳定模型；只附零因子同分基线。'))
    print('SHUFFLE', len(shuffled), 'stable;', result.get('final', result)['score'], flush=True)


def freeze():
    final = read(REPORTS / (PREFIX + 'ablation.json'))['final']
    write('frozen_selection', dict(final=final, selection_years=list(YEARS),
        freeze_utc=datetime.now(timezone.utc).isoformat(), exam_used_for_selection=False,
        plan_sha256=prior.file_sha(PLAN), prereg_sha256=prior.file_sha(PREREG),
        description_sha256=prior.file_sha(REPORTS / (PREFIX + 'true_description.json')),
        shuffle_sha256=prior.file_sha(REPORTS / (PREFIX + 'shuffle.json'))))


def final_stage():
    path = REPORTS / (PREFIX + 'final.json')
    if path.exists():
        raise ValueError('final exam already reported; read the saved result')
    frozen = read(REPORTS / (PREFIX + 'frozen_selection.json'))
    result = Data(full=True).evaluate(frozen['final']['scheme'], 'final')
    result['note'] = '2026已看过两次，不是干净的考试；本次冻结后只报告一次。'
    result['frozen_sha256'] = prior.file_sha(REPORTS / (PREFIX + 'frozen_selection.json'))
    write('final', result)
    print('FINAL', result['coverage']['annual']['2026']['primary'], flush=True)


def guard():
    def allowed(path):
        p = Path(os.fsdecode(path)).resolve()
        return p.is_relative_to(WORK.resolve()) or (p.parent == REPORTS.resolve() and p.name.startswith(PREFIX))

    def audit(event, args):
        if event == 'open':
            path, _, flags = args
            if not isinstance(path, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND) and not allowed(path):
                raise PermissionError('IE7 output boundary: ' + os.fsdecode(path))
        if event in ('socket.connect', 'socket.bind', 'os.system', 'subprocess.Popen'):
            raise PermissionError('IE7 offline single process')
        if event in ('os.remove', 'os.rename', 'os.rmdir', 'os.mkdir'):
            paths = args[:2] if event == 'os.rename' else args[:1]
            if any(not allowed(p) for p in paths):
                raise PermissionError('IE7 output boundary')
    sys.addaudithook(audit)


def main(stage):
    WORK.mkdir(exist_ok=True)
    for name in ('evaluations', 'accounts'):
        (WORK / name).mkdir(exist_ok=True)
    guard()
    if stage == 'describe':
        description_stage()
    elif stage.startswith('round'):
        run_round(int(stage[-1]))
    elif stage == 'ablate':
        ablation_stage()
    elif stage == 'shuffle':
        shuffle_stage()
    elif stage == 'freeze':
        freeze()
    elif stage == 'final':
        final_stage()
    else:
        raise ValueError(stage)
    write('runtime_' + stage, dict(completed_utc=datetime.now(timezone.utc).isoformat(),
        plan_sha256=prior.file_sha(PLAN), prereg_sha256=prior.file_sha(PREREG),
        source_sha256=prior.file_sha(Path(__file__)), peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('stage', choices=('describe', 'round1', 'round2', 'round3', 'ablate', 'shuffle', 'freeze', 'final'))
    main(parser.parse_args().stage)
