"""IE10: cached numerical filters, fixed IE9 ranking and half-year selection."""
import argparse
from collections import defaultdict
from datetime import datetime, timezone
import csv
import gc
import json
import os
from pathlib import Path
import resource
import sys
from unittest.mock import patch

import numpy as np

from studies.trader_replication import martin_continue_ie9 as ie9

ie8, ie7, prior, old, lib = ie9.ie8, ie9.ie7, ie9.prior, ie9.old, ie9.lib
ROOT, REPORTS = ie9.ROOT, ie9.REPORTS
WORK = REPORTS / 'ie10_work'
PREFIX = 'strong_continue_ie10_'
PLAN = ROOT / 'studies/martin_luk/notes/PLAN_IE10_CN.md'
PREREG = ROOT / 'studies/martin_luk/notes/PREREG_IE10_CN.md'
YEARS, HALVES, TOPS = ie9.YEARS, ie9.HALVES, ie9.TOPS
SEED, RANDOM_SEED = 20261110, 2026111000
CUTOFFS = (.3, .5, .7, .8, .9)
FACTORS = ('after_inside', 'near_ema9')
EXTRA_RAW = ('peer_g5', 'peer_rank', 'earn_age', 'iv_hv', 'pcr')
DERIVED = ('call_surge5', 'call_surge20', 'iv_change1', 'iv_change5', 'pcr_change5',
           'oi_change5', 'call_share', 'option_turnover', 'post_earn5', 'post_earn20')
GROUPS = tuple((n, key) for n in (5, 20) for key in
               ('peer_return', 'peer_excess', 'peer_positive', 'peer_volume', 'peer_rank', 'peer_potent'))
CONTEXT = (tuple(('group', n, key) for n, key in GROUPS) +
           tuple(('avwap', n, key) for n in (14, 50) for key in ('high', 'low', 'breakout', 'earnings')) +
           (('chips', 100, 'cost'), ('chips', 100, 'concentration')) +
           tuple(('ibd_rs', n, 'weighted') for n in (63, 126, 252)) +
           (('statistics', 20, 't_score'), ('statistics', 20, 'r_squared')))
EXTERNAL = ('short_fraction', 'flow_fraction', 'main_flow_fraction')
EVENTS = (set(ie9.TRIGGERS) - set(ie9.CONTINUOUS)) | {'post_earn5', 'post_earn20'}


def read(name):
    return ie7.read(REPORTS / (PREFIX + name + '.json'))


def write(name, value):
    old.prior.write_json(REPORTS / (PREFIX + name + '.json'), value)


def delta_specs():
    inventory = {old.prior.factor_name(s, t): s for s, t in old.prior.factor_specs()}
    records = [r for p in sorted(prior.WORK.glob('delta_*.json')) for r in ie7.read(p)['columns']]
    return [(r['name'], inventory[r['name']]) for r in records]


def feature_names():
    stable = [r['name'] for r in ie8.stable_features()]
    return list(dict.fromkeys(stable + list(ie9.NAMES) + list(EXTRA_RAW) + list(DERIVED) +
        [f'{family}.{key}.{n}' for family, n, key in CONTEXT] +
        [name for name, _ in delta_specs()] + list(EXTERNAL)))


def derived_values(extras):
    """No forward filling: absent option observations stay absent."""
    iv, cv, pv, ov, oi = (extras[k] for k in
        ('iv', 'call_volume', 'put_volume', 'option_volume', 'option_open_interest'))
    pcr = lib.divide(pv, cv)
    age = extras['earn_days']
    return dict(call_surge5=lib.divide(cv, lib.lag(lib.roll(cv, 5))),
        call_surge20=lib.divide(cv, lib.lag(lib.roll(cv, 20))),
        iv_change1=lib.divide(iv, lib.lag(iv)) - 1,
        iv_change5=lib.divide(iv, lib.lag(iv, 5)) - 1,
        pcr_change5=pcr - lib.lag(pcr, 5), oi_change5=lib.divide(oi, lib.lag(oi, 5)) - 1,
        call_share=lib.divide(cv, ov), option_turnover=lib.divide(ov, oi),
        post_earn5=ie9.event((age >= 0) & (age <= 5), age),
        post_earn20=ie9.event((age >= 0) & (age <= 20), age))


def context_values(arrays, extras, days, qqq, specs):
    """Evaluate one security and a few indicator branches at a time."""
    stock = lib.Stock(arrays, days, qqq, extras)
    grouped = defaultdict(set)
    for family, n, metric in specs:
        grouped[family, n].add(metric)
    result = {}
    for (family, n), wanted in grouped.items():
        values = old.indicator_values(stock, family, n, wanted)
        for metric in wanted:
            result[f'{family}.{metric}.{n}'] = values[metric]
    stock.ema.cache_clear()
    stock.f_hilbert.cache_clear()
    return result


def external_files():
    result = []
    for directory, _, files in os.walk(ROOT / 'data'):
        if Path(directory).name in ('short_volume', 'capital_flow'):
            result.extend(Path(directory) / f for f in sorted(files) if f.endswith('.csv'))
    return sorted(result)


def external_values(code, days, arrays, sources):
    """Use the previous completed session for cash-flow/short-sale publication lag."""
    out = {n: np.full(len(days), np.nan) for n in EXTERNAL}
    di = {d: t for t, d in enumerate(days)}
    duplicates = conflicts = 0
    for source in sources:
        if source.stem not in (code, code.removeprefix('US.')):
            continue
        with source.open() as stream:
            for row in csv.DictReader(stream):
                day = row.get('date', row.get('timestamp_str', ''))[:10]
                if day not in di:
                    continue
                t = di[day]
                fields = ({'short_fraction': ('short_percent', 100.)} if source.parent.name == 'short_volume'
                          else {n: (f, arrays['t'][t]) for n, f in
                                (('flow_fraction', 'in_flow'), ('main_flow_fraction', 'main_in_flow'))})
                for name, (field, denominator) in fields.items():
                    try:
                        value = float(row[field]) / denominator if denominator > 0 else np.nan
                    except (ValueError, TypeError):
                        continue
                    if not np.isfinite(value):
                        continue
                    if np.isfinite(out[name][t]):
                        duplicates += 1
                        conflicts += not np.isclose(out[name][t], value, rtol=1e-6, atol=1e-9)
                    else:
                        out[name][t] = value
    return {n: lib.lag(a) for n, a in out.items()}, duplicates, conflicts


def filter_mask(values, condition):
    finite = np.isfinite(values)
    if condition['kind'] == 'event':
        return finite & (values == condition['value'])
    oriented = values if condition['direction'] > 0 else 1 - values
    return finite & (oriented + 1e-7 >= condition['cutoff'])


def rank_night(values, passed, names):
    """Keep the frozen equal-weight formula; rank EMA distance in the remaining pool."""
    kept = np.flatnonzero(passed)
    score = np.nan_to_num(values[kept, names.index('after_inside')], nan=.5)
    near = ie7.night_percentiles(values[kept, names.index('near_ema9'):names.index('near_ema9') + 1])[:, 0]
    score = (score + np.nan_to_num(near, nan=.5)) / 2
    order = kept[np.argsort(-score, kind='stable')]
    ranks = np.full(len(passed), old.prior.SENTINEL, np.int32)
    ranks[order] = np.arange(1, len(order) + 1)
    return order, ranks


def score_key(result):
    return (min(ie7.rate(result['coverage']['halfyear'][h]) for h in HALVES),
            -len(result['scheme']['filters']), ie7.rate(result['coverage']['all_entries']))


def winner(results):
    return max([r for r in results if r['eligible']] or results, key=score_key)


def qualify(coverage, expected, accounts):
    _, failures = ie7.eligible(accounts)
    for h in HALVES:
        if coverage['halfyear'][h]['hits']['5'] <= expected['halfyear'][h]['union'] + 1e-10:
            failures.append(h + ':not_above_union_expectation')
    return not failures, failures


class Data(ie9.Data):
    def __init__(self, full=False, shuffled=False):
        super().__init__(full=full)
        self.base_passed = self.passed.copy()
        self.base_widths = self.widths.copy()
        self.names = feature_names()
        self.label = 'shuffle' if shuffled else 'true'
        if shuffled:
            rng = np.random.default_rng(SEED)
            mapping = np.arange(self.n)
            for sl in self.slices.values():
                kept = np.flatnonzero(self.base_passed[sl]) + sl.start
                mapping[kept] = rng.permutation(kept)
            self.query = [[int(mapping[q]) if q >= 0 else -1 for q in qs] for qs in self.query]

    def features(self):
        if not hasattr(self, 'values'):
            self.values = np.load(WORK / 'features.npy', mmap_mode='r')[:self.n]
        return self.values

    def passed_for(self, conditions):
        passed = self.base_passed.copy()
        values = self.features()
        for condition in conditions:
            passed &= filter_mask(values[:, self.names.index(condition['name'])], condition)
        return passed

    def select(self, scheme):
        self.passed = self.passed_for(scheme['filters'])
        self.widths = {day: int(self.passed[sl].sum()) for day, sl in self.slices.items() if day in self.base_widths}
        for day, sl in self.slices.items():
            self.row_width[sl] = self.widths.get(day, 0)
        self.expected = ie9.random_expectation(self.entries, self.query, self.passed, self.row_width)
        ranks = np.full(self.n, old.prior.SENTINEL, np.int32)
        selected = {}
        for day, sl in self.slices.items():
            if day not in self.widths:
                continue
            order, ranks[sl] = rank_night(self.features()[sl], self.passed[sl], self.names)
            selected[day] = [self.meta['scope'][day][k] for k in order[:5]]
        coverage = ie7.coverage(self.entries, self.query, ranks, self.passed)
        base = ie7.coverage(self.entries, self.query, ranks, self.base_passed)
        for a, b in zip(coverage['rows'], base['rows']):
            a['ie8_retained'] = b['passed_gate']
        return selected, coverage

    def evaluate(self, scheme):
        key = prior.digest(dict(scheme=scheme, end=self.end, label=self.label,
            source=prior.file_sha(Path(__file__)), features=ie7.read(WORK / 'features.json')['feature_sha256']))
        path = WORK / 'evaluations' / (key + '.json')
        if path.exists():
            return ie7.read(path)
        selected, coverage = self.select(scheme)
        account_key = prior.digest(dict(selected=selected, end=self.end))
        candidates = [w / 'accounts' / (account_key + '.json') for w in (WORK, ie9.WORK, ie8.WORK, ie7.WORK)]
        cached = next((p for p in candidates if p.exists()), None)
        accounts = ie7.read(cached) if cached else self.accounts(selected)
        if cached is None:
            old.prior.write_json(candidates[0], accounts)
        eligible, failures = qualify(coverage, self.expected, accounts)
        groups = dict(combined=[r for r in coverage['rows'] if r['primary']])
        groups.update({h: [r for r in groups['combined'] if ie7.half(r['entry_date']) == h] for h in HALVES})
        groups.update({y: [r for r in groups['combined'] if r['entry_date'].startswith(y)] for y in (*YEARS, '2026')})
        funnel = {k: dict(n=len(rows), scope=sum(r['in_scope'] for r in rows),
            ie8=sum(r['ie8_retained'] for r in rows), filtered=sum(r['passed_gate'] for r in rows),
            top5=sum(r['best_rank'] <= 5 for r in rows)) for k, rows in groups.items()}
        f = funnel['combined']
        losses = dict(scope=f['n'] - f['scope'], ie8=f['scope'] - f['ie8'],
                      filters=f['ie8'] - f['filtered'], ranking=f['filtered'] - f['top5'])
        value = dict(scheme=scheme, coverage=coverage, accounts=accounts, eligible=eligible, failures=failures,
            expected=self.expected, selected=selected, selection_hash=account_key, nightly_widths=self.widths,
            width=width_summary(self.widths), funnel=funnel,
            losses=dict(counts=losses, largest=max(losses, key=losses.get)))
        value['score'] = list(score_key(value))
        old.prior.write_json(path, value)
        return value


def width_summary(widths):
    result = ie8.width_summary(widths)
    for year, summary in result.items():
        a = [v for day, v in widths.items() if day[:4] in YEARS] if year == 'combined' else [v for day, v in widths.items() if day.startswith(year)]
        summary.update(empty_fraction=summary['empty'] / summary['n'], q10=float(np.percentile(a, 10)),
                       q90=float(np.percentile(a, 90)), at_most5=sum(v <= 5 for v in a) / len(a))
    return result


def prepare_features():
    path = WORK / 'features.npy'
    if (WORK / 'features.json').exists():
        raise ValueError('inventory already prepared; read the saved artifacts')
    d = Data(full=True)
    names = d.names
    dest = np.lib.format.open_memmap(path, mode='w+', dtype=np.float32, shape=(d.n, len(names)))
    dest[:] = np.nan
    triggers = np.load(ie9.WORK / 'full_features.npy', mmap_mode='r')
    base_cols = set(names) & set(d.base_names)
    for day, sl in d.slices.items():
        rows = np.flatnonzero(d.base_passed[sl]) + sl.start
        for name in base_cols:
            dest[rows, names.index(name)] = d.base_raw[rows, d.base_names.index(name)]
        for name in set(ie9.NAMES) - base_cols:
            dest[rows, names.index(name)] = triggers[rows, list(ie9.NAMES).index(name)]
    di = {day: t for t, day in enumerate(d.meta['days'])}
    bycode, presence = defaultdict(list), defaultdict(set)
    for day, sl in d.slices.items():
        for k, code in enumerate(d.meta['scope'][day]):
            presence[code].add(di[day])
            if d.base_passed[sl.start + k]:
                bycode[code].append((di[day], sl.start + k))
    qqq = np.load(old.WORK / 'qqq.npy', mmap_mode='r')
    deltas = delta_specs()
    corrected = {name: np.load(prior.WORK / 'design' / (name + '.npy'), mmap_mode='r') for name, _ in deltas}
    specs = list(dict.fromkeys(list(CONTEXT) + [(s.family, s.parameter, s.metric) for _, s in deltas]))
    sources = external_files()
    input_hashes = {str(p.relative_to(ROOT)): prior.file_sha(p) for p in sources}
    duplicates = conflicts = 0
    for count, (code, positions) in enumerate(bycode.items()):
        source = old.WORK / 'stocks' / (code + '.npz')
        input_hashes[str(source.relative_to(ROOT))] = prior.file_sha(source)
        with np.load(source) as z:
            arrays = {k: z[k] for k in z.files if not k.startswith('extra_')}
            extras = {k[6:]: z[k] for k in z.files if k.startswith('extra_')}
        for n in {n for family, n, _ in specs if family == 'group'}:
            source = old.WORK / 'group' / (code + f'.{n}.npz')
            input_hashes[str(source.relative_to(ROOT))] = prior.file_sha(source)
            with np.load(source) as z:
                extras.update({f'group.{key}.{n}': z[key] for key in z.files})
        values = context_values(arrays, extras, d.meta['days'], qqq, [s for s in specs if s[0] != 'original53'])
        values.update(derived_values(extras))
        extra, dupe, conflict = external_values(code, d.meta['days'], arrays, sources)
        values.update(extra)
        duplicates += dupe
        conflicts += conflict
        ts, rows = map(np.asarray, zip(*positions))
        for name, column in values.items():
            if name in names:
                dest[rows, names.index(name)] = column[ts]
        prior_present = np.array([t - 5 in presence[code] for t in ts])
        for name, s in deltas:
            raw = extras[s.metric] if s.family == 'original53' else values[f'{s.family}.{s.metric}.{s.parameter}']
            valid = (ts >= 5) & prior_present & np.isfinite(raw[ts]) & np.isfinite(raw[np.maximum(ts - 5, 0)])
            dest[rows, names.index(name)] = np.where(valid, corrected[name][rows], np.nan)
        if count % 100 == 0:
            print('feature stock', count, '/', len(bycode), flush=True)
    dest.flush()
    inventory = []
    for j, name in enumerate(names):
        row = dict(name=name, kind='event' if name in EVENTS else 'percentile', annual={})
        for year in (*YEARS, '2026'):
            valid = total = nights = 0
            securities = set()
            for day, sl in d.slices.items():
                if not day.startswith(year) or day not in d.base_widths:
                    continue
                rows = np.flatnonzero(d.base_passed[sl]) + sl.start
                finite = np.isfinite(dest[rows, j])
                valid += int(finite.sum())
                total += len(rows)
                nights += bool(finite.any())
                securities.update(d.meta['scope'][day][q - sl.start] for q in rows[finite])
            row['annual'][year] = dict(valid=valid, total=total, fraction=valid / total if total else 0,
                valid_nights=nights, securities=len(securities))
        inventory.append(row)
    write('inventory', dict(rows=inventory, external_sources=[str(p.relative_to(ROOT)) for p in sources],
        external_duplicates=duplicates, external_conflicts=conflicts,
        denominator='IE8四条过滤条件后的股票×交易晚；2026只盘点可用性，不读标签作描述或选择。',
        delta_note='IE6校正列复用数值；逐股重算本晚/前五晚有限性及范围成员，恢复NaN，不能把中性0.5视为有数据。',
        nonhistorical='industry_us.json为当前行业快照，无历史版本，未作因子；同伙只是相关群组。',
        no_point_in_time_earnings_schedule=True))
    for day, sl in d.slices.items():
        rows = np.flatnonzero(d.base_passed[sl]) + sl.start
        for j, name in enumerate(names):
            if name not in EVENTS:
                dest[rows, j] = ie7.night_percentiles(dest[rows, j:j + 1])[:, 0]
    dest.flush()
    del dest
    gc.collect()
    old.prior.write_json(WORK / 'features.json', dict(names=names, rows=d.n, input_sha256=input_hashes,
        feature_sha256=prior.file_sha(path), plan_sha256=prior.file_sha(PLAN),
        dataset_digest=d.meta['dataset_digest'], source_sha256=prior.file_sha(Path(__file__))))


def candidates(names):
    result = []
    for name in names:
        variants = [dict(kind='event', value=v) for v in (1, 0)] if name in EVENTS else [
            dict(kind='percentile', direction=direction, cutoff=cutoff) for direction in (1, -1) for cutoff in CUTOFFS]
        for variant in variants:
            result.append(dict(id=len(result), name=name, **variant))
    return result


def describe(d):
    base = d.base_passed
    rows = []
    for condition in candidates(d.names):
        passed = base & filter_mask(d.features()[:, d.names.index(condition['name'])], condition)
        widths = {day: int(passed[sl].sum()) for day, sl in d.slices.items() if day in d.base_widths}
        halves = {}
        for h in HALVES:
            indices = [i for i, e in enumerate(d.entries) if e['target']['tier'] == 'primary' and ie7.half(e['entry_date']) == h]
            baseline = sum(any(q >= 0 and base[q] for q in d.query[i]) for i in indices)
            retained = sum(any(q >= 0 and passed[q] for q in d.query[i]) for i in indices)
            days = [day for day in widths if ie7.half(day) == h]
            ratios = [widths[day] / d.base_widths[day] for day in days if d.base_widths[day] > 0]
            ratio = float(np.median(ratios)) if ratios else 0.
            rate = retained / baseline if baseline else 0.
            halves[h] = dict(n=len(indices), ie8_retained=baseline, retained=retained, retention=rate,
                full_retention=retained / len(indices) if indices else 0., width_ratio=ratio,
                median_width=float(np.median([widths[day] for day in days])), advantage=rate - ratio)
        row = dict(condition=condition, halves=halves,
            stable=all(r['advantage'] > 1e-10 for r in halves.values()))
        row['min_advantage'] = min(r['advantage'] for r in halves.values())
        rows.append(row)
    return dict(rows=rows, stable=[r['condition'] for r in rows if r['stable']],
        selection_years=list(YEARS), seed=SEED if d.label == 'shuffle' else None,
        prereg_sha256=prior.file_sha(PREREG))


def validate(scheme, allowed):
    if scheme['base_filters'] != ie9.GATES or scheme['factors'] != list(FACTORS):
        raise ValueError('IE8 filters and IE9 ranking are frozen')
    conditions = scheme['filters']
    if len(conditions) > 4 or len({c['name'] for c in conditions}) != len(conditions):
        raise ValueError('new filter budget or duplicate numerical feature')
    if any(c not in allowed for c in conditions):
        raise ValueError('condition failed the four-half retention/width requirement')


def run_round(number):
    spec_path = WORK / f'round{number}.json'
    spec = ie7.read(spec_path)
    if not 1 <= number <= 4 or not 1 <= len(spec['schemes']) <= 5:
        raise ValueError('round budget exceeded')
    if number > 1 and spec['target_layer'] != read(f'round{number - 1}')['winner']['losses']['largest']:
        raise ValueError('next round must address the largest funnel loss')
    allowed = read('description')['stable']
    for scheme in spec['schemes']:
        validate(scheme, allowed)
    registration = dict(spec=spec, utc=datetime.now(timezone.utc).isoformat(),
        spec_sha256=prior.file_sha(spec_path), prereg_sha256=prior.file_sha(PREREG),
        prereg_text=PREREG.read_text(encoding='utf-8'), plan_sha256=prior.file_sha(PLAN))
    write(f'round{number}_registration', registration)
    d, results = Data(), []
    for scheme in spec['schemes']:
        result = d.evaluate(scheme)
        results.append(result)
        print(scheme['id'], result['score'], result['eligible'], result['failures'], result['funnel']['combined'], flush=True)
    write(f'round{number}', dict(registration=registration, results=results, winner=winner(results)))


def ablate(d, start):
    current, rounds = start, []
    while True:
        trials, accepted = [], False
        for k, condition in enumerate(current['scheme']['filters']):
            scheme = dict(current['scheme'], filters=current['scheme']['filters'][:k] + current['scheme']['filters'][k + 1:],
                          id=current['scheme']['id'] + '-drop' + str(k))
            after = d.evaluate(scheme)
            accept = after['score'][0] >= current['score'][0]
            trials.append(dict(removed=condition, result=after, accepted=bool(accept)))
            if accept:
                current, accepted = after, True
                break
        rounds.append(dict(trials=trials))
        if not accepted:
            return dict(initial=start, rounds=rounds, final=current)


def shuffle_stage():
    d = Data(shuffled=True)
    description = describe(d)
    write('shuffle_description', description)
    real, shuffled = read('description')['stable'], description['stable']
    results, unavailable = [], []
    for path in sorted(WORK.glob('round[1234].json')):
        for original in ie7.read(path)['schemes']:
            indices = [real.index(c) for c in original['filters']]
            if max(indices, default=-1) >= len(shuffled):
                unavailable.append(original['id'])
                continue
            candidate = dict(original, filters=[shuffled[i] for i in indices])
            if len({c['name'] for c in candidate['filters']}) != len(candidate['filters']):
                unavailable.append(original['id'])
                continue
            validate(candidate, shuffled)
            results.append(d.evaluate(candidate))
    if results:
        ablation = ablate(d, winner(results))
        final = ablation['final']
    else:
        ablation = None
        final = d.evaluate(dict(id='shuffle_unfiltered_reference', base_filters=ie9.GATES, factors=list(FACTORS), filters=[]))
    write('shuffle', dict(seed=SEED, results=results, unavailable=unavailable, stable=len(shuffled),
        final=final, ablation=ablation, fallback=not bool(results)))


def random_controls(d, actual):
    with patch.object(ie9, 'RANDOM_SEED', RANDOM_SEED):
        return ie9.random_controls(d, actual)


def freeze():
    final = read('ablation')['final']
    write('frozen_selection', dict(final=final, freeze_utc=datetime.now(timezone.utc).isoformat(),
        selection_years=list(YEARS), exam_used_for_selection=False, plan_sha256=prior.file_sha(PLAN),
        prereg_sha256=prior.file_sha(PREREG), source_sha256=prior.file_sha(Path(__file__)),
        feature_sha256=ie7.read(WORK / 'features.json')['feature_sha256']))


def final_stage():
    if (REPORTS / (PREFIX + 'final.json')).exists():
        raise ValueError('final already evaluated; reuse the saved result')
    frozen = read('frozen_selection')
    if prior.file_sha(Path(__file__)) != frozen['source_sha256']:
        raise ValueError('source changed after freeze')
    d = Data(full=True)
    final = d.evaluate(frozen['final']['scheme'])
    if {day: codes for day, codes in final['selected'].items() if day <= prior.TRAIN_END} != frozen['final']['selected']:
        raise AssertionError('historical selections changed')
    final['note'] = '2026已看过五次，不是干净考试；冻结后只报告一次。'
    write('final', final)
    d.select(final['scheme'])
    write('random_final', random_controls(d, final))
    print('FINAL', final['coverage']['annual']['2026']['primary'], flush=True)


def guard():
    def allowed(path):
        p = Path(os.fsdecode(path)).resolve()
        return p.is_relative_to(WORK.resolve()) or (p.parent == REPORTS.resolve() and p.name.startswith(PREFIX))
    def audit(event, args):
        if event == 'open':
            path, _, flags = args
            if not isinstance(path, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND) and not allowed(path):
                raise PermissionError('IE10 output boundary: ' + os.fsdecode(path))
        if event in ('socket.connect', 'socket.bind', 'os.system', 'subprocess.Popen'):
            raise PermissionError('IE10 offline single process')
        if event in ('os.remove', 'os.rename', 'os.rmdir', 'os.mkdir'):
            paths = args[:2] if event == 'os.rename' else args[:1]
            if any(not allowed(p) for p in paths):
                raise PermissionError('IE10 output boundary')
    sys.addaudithook(audit)


def main(stage):
    os.environ['TMPDIR'] = str(WORK / 'tmp')
    import tempfile
    tempfile.tempdir = str(WORK / 'tmp')
    guard()
    if stage == 'inventory':
        prepare_features()
    elif stage == 'describe':
        result = describe(Data())
        write('description', result)
        print('stable conditions', len(result['stable']), flush=True)
    elif stage.startswith('round'):
        run_round(int(stage[-1]))
    elif stage == 'ablate':
        results = [r for p in sorted(REPORTS.glob(PREFIX + 'round[1234].json')) for r in ie7.read(p)['results']]
        result = ablate(Data(), winner(results))
        write('ablation', result)
        print('ABLATION', result['final']['scheme'], result['final']['score'], flush=True)
    elif stage == 'random':
        d, actual = Data(), read('ablation')['final']
        d.select(actual['scheme'])
        write('random', random_controls(d, actual))
    else:
        dict(shuffle=shuffle_stage, freeze=freeze, final=final_stage)[stage]()
    write('runtime_' + stage, dict(utc=datetime.now(timezone.utc).isoformat(),
        source_sha256=prior.file_sha(Path(__file__)), plan_sha256=prior.file_sha(PLAN),
        prereg_sha256=prior.file_sha(PREREG) if PREREG.exists() else None,
        peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('stage', choices=('inventory', 'describe', 'round1', 'round2', 'round3', 'round4',
                                         'ablate', 'random', 'shuffle', 'freeze', 'final'))
    main(parser.parse_args().stage)
