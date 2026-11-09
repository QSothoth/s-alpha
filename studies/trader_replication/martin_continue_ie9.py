"""IE9: fixed IE8 gates, causal trigger ranks and half-year selection."""
import argparse
from collections import defaultdict
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import resource
import sys

import numpy as np

from studies.trader_replication import martin_continue_ie8 as ie8

ie7, prior, old = ie8.ie7, ie8.prior, ie8.old
lib = old.lib
ROOT, REPORTS = ie8.ROOT, ie8.REPORTS
WORK = REPORTS / 'ie9_work'
PREFIX = 'strong_continue_ie9_'
PLAN = ROOT / 'studies/martin_luk/notes/PLAN_IE9_CN.md'
PREREG = ROOT / 'studies/martin_luk/notes/PREREG_IE9_CN.md'
YEARS, HALVES, TOPS = ie8.YEARS, ie8.HALVES, ie8.TOPS
SEED, RANDOM_SEED = 20261109, 2026110900
TRIGGERS = ('reclaim9', 'reclaim21', 'touch9', 'touch21', 'first_touch9', 'first_touch21',
    'cross9', 'cross21', 'nr4', 'nr7', 'inside', 'after_nr4', 'after_nr7', 'after_inside',
    'volume_rebound', 'dry_volume_rebound', 'break_high_close', 'nr4_breakout', 'nr7_breakout',
    'inside_breakout', 'pullback_2_10', 'pullback_turn', 'rs1', 'price_volume_turn',
    'fresh_gap', 'fresh_pot', 'tight_range_turn', 'close_break_strength')
CONTINUOUS = ('cross9', 'cross21', 'volume_rebound', 'rs1', 'price_volume_turn',
              'fresh_gap', 'fresh_pot', 'close_break_strength')
ANCHORS = ('offlow252', 'near_ema9')
NAMES = TRIGGERS + ANCHORS
CACHED = ('cross9', 'cross21', 'rs1', 'fresh_gap', 'fresh_pot') + ANCHORS
GATES = [dict(name=n, direction=1, cutoff=c) for n, c in
         (('h4_history', .6), ('adr20', .7), ('option_volume', .8), ('low20', .5))]


def read(name):
    return ie7.read(REPORTS / (PREFIX + name + '.json'))


def write(name, value):
    old.prior.write_json(REPORTS / (PREFIX + name + '.json'), value)


def event(condition, *inputs):
    valid = np.logical_and.reduce([np.isfinite(x) for x in inputs])
    return np.where(valid, condition, np.nan).astype(float)


def trigger_values(arrays):
    """One security's history only; cached trigger columns are reused separately."""
    c, h, l, v = (np.asarray(arrays[k], float) for k in ('c', 'h', 'l', 'v'))
    p, ph, pl = lib.lag(c), lib.lag(h), lib.lag(l)
    a = lib.divide(h, l) - 1
    adr = lib.lag(lib.roll(a, 20))
    gain = lib.divide(c, p) - 1
    cp = lib.divide(c - l, h - l)
    previous_volume = lib.lag(lib.roll(v, 3))
    vr = lib.divide(v, previous_volume)
    out = {}
    for n, window in ((9, 5), (21, 10)):
        ema = lib.smooth(c, n)
        touch = event((l <= ema) & (c > ema), l, c, ema)
        out['reclaim' + str(n)] = event((c > ema) & (p <= lib.lag(ema)), c, p, ema, lib.lag(ema))
        out['touch' + str(n)] = touch
        above = lib.lag(lib.roll(event(l > ema, l, ema), window, 'sum'))
        out['first_touch' + str(n)] = event((touch == 1) & (above == window), touch, above)
    for n in (4, 7):
        minimum = lib.roll(a, n, 'min')
        nr = event(a <= minimum, a, minimum)
        after = lib.lag(nr)
        out['nr' + str(n)] = nr
        out['after_nr' + str(n)] = after
        out['nr' + str(n) + '_breakout'] = event((after == 1) & (c > ph), after, c, ph)
    out['inside'] = event((h <= ph) & (l >= pl), h, l, ph, pl)
    out['after_inside'] = lib.lag(out['inside'])
    out['inside_breakout'] = event((out['after_inside'] == 1) & (c > ph), out['after_inside'], c, ph)
    out['volume_rebound'] = vr
    volume20 = lib.lag(lib.roll(v, 20))
    out['dry_volume_rebound'] = event((previous_volume < volume20) & (vr > 1) & (c > p),
                                     previous_volume, volume20, vr, c, p)
    out['break_high_close'] = event((cp >= .75) & (c > ph), cp, c, ph)
    age = np.full(len(c), np.nan)
    for t in range(19, len(c)):
        window = h[t - 19:t + 1]
        if np.isfinite(window).all():
            age[t] = np.argmax(window[::-1])
    out['pullback_2_10'] = event((age >= 2) & (age <= 10), age)
    out['pullback_turn'] = event((out['pullback_2_10'] == 1) & (c > p) & (cp >= .5),
                                 age, c, p, cp)
    out['price_volume_turn'] = lib.divide(gain, adr) * vr
    previous_range = lib.lag(lib.roll(a, 3))
    out['tight_range_turn'] = event((previous_range < adr) & (c > p) & (cp >= .5),
                                    previous_range, adr, c, p, cp)
    out['close_break_strength'] = lib.divide(lib.divide(c, ph) - 1, adr)
    return out


def rank_night(values, passed, names, factors):
    kept = np.flatnonzero(passed)
    score = np.zeros(len(kept), float)
    for factor in factors:
        score += np.nan_to_num(values[kept, names.index(factor)], nan=.5)
    if factors:
        score /= len(factors)
    order = kept[np.argsort(-score, kind='stable')]
    ranks = np.full(len(passed), old.prior.SENTINEL, np.int32)
    ranks[order] = np.arange(1, len(order) + 1)
    return order, ranks


def random_expectation(entries, query, passed, row_width):
    rows = []
    for e, qs in zip(entries, query):
        probabilities = [min(1., 5 / row_width[q]) for q in qs if q >= 0 and passed[q]]
        rows.append(dict(id=e['id'], entry_date=e['entry_date'], primary=e['target']['tier'] == 'primary',
            best_night=max(probabilities, default=0.), union=1 - float(np.prod(1 - np.array(probabilities)))))
    def summary(sample):
        return dict(n=len(sample), best_night=sum(r['best_night'] for r in sample),
                    union=sum(r['union'] for r in sample))
    primary = [r for r in rows if r['primary']]
    return dict(rows=rows, primary=summary(primary), all_entries=summary(rows),
        halfyear={h: summary([r for r in primary if ie7.half(r['entry_date']) == h]) for h in HALVES},
        annual={y: dict(primary=summary([r for r in primary if r['entry_date'].startswith(y)]),
                        all_entries=summary([r for r in rows if r['entry_date'].startswith(y)]))
                for y in (*YEARS, '2026')})


def score_key(result):
    return min(ie7.rate(result['coverage']['halfyear'][h]) for h in HALVES), -len(result['scheme']['factors'])


def qualify(coverage, expected, accounts):
    account_ok, failures = ie7.eligible(accounts)
    for h in HALVES:
        if coverage['halfyear'][h]['hits']['5'] <= expected['halfyear'][h]['best_night']:
            failures.append(h + ':not_above_random_expectation')
    return account_ok and not failures, failures


def winner(results):
    return max([r for r in results if r['eligible']] or results, key=score_key)


def stable_names(description):
    return [r['name'] for r in description['primary'] if r['stable'] and r['name'] in TRIGGERS]


def validate(scheme, allowed):
    factors = scheme['factors']
    if scheme['gates'] != GATES or scheme.get('rank_scope') != 'small':
        raise ValueError('IE9 gates and rank scope are immutable')
    if not 1 <= len(factors) <= 4 or len(set(factors)) != len(factors):
        raise ValueError('IE9 factor budget or duplicate')
    if not set(factors) <= set(allowed) | set(ANCHORS) or not set(factors) & set(allowed):
        raise ValueError('every scheme needs a stable, preregistered trigger')


class Data(ie7.Data):
    def __init__(self, full=False, shuffled=False):
        super().__init__(full=full)
        if ie8.read('frozen_gates')['final']['scheme']['gates'] != GATES:
            raise ValueError('IE8 gate provenance differs')
        self.base_names, self.base_raw = self.names, self.raw
        pct_path = ie7.WORK / ('full_pct.npy' if full else 'train_pct.npy')
        self.base_pct = np.load(pct_path, mmap_mode='r')
        self.passed = np.zeros(self.n, bool)
        self.row_width = np.zeros(self.n, np.int32)
        self.widths = {}
        for day, sl in self.slices.items():
            if day >= self.meta['first_signal']:
                self.passed[sl] = ie8.gate_mask(self.base_pct[sl], self.base_names, GATES)
                self.widths[day] = int(self.passed[sl].sum())
                self.row_width[sl] = self.widths[day]
        self.label = 'shuffle' if shuffled else 'true'
        if shuffled:
            rng = np.random.default_rng(SEED)
            mapping = np.arange(self.n)
            for sl in self.slices.values():
                kept = np.flatnonzero(self.passed[sl]) + sl.start
                mapping[kept] = rng.permutation(kept)
            self.query = [[int(mapping[q]) if q >= 0 else -1 for q in qs] for qs in self.query]
        self.expected = random_expectation(self.entries, self.query, self.passed, self.row_width)
        self.names = list(NAMES)

    def features(self):
        if hasattr(self, 'values'):
            return self.values
        label = 'full' if self.end > prior.TRAIN_END else 'train'
        marker = WORK / (label + '_features.json')
        path = WORK / (label + '_features.npy')
        if marker.exists():
            self.values = np.load(path, mmap_mode='r')
            return self.values
        dest = np.lib.format.open_memmap(path, mode='w+', dtype=np.float32, shape=(self.n, len(NAMES)))
        dest[:] = np.nan
        start = 0
        if label == 'full':
            trained = np.load(WORK / 'train_features.npy', mmap_mode='r')
            start = len(trained)
            for a in range(0, start, 4096):
                dest[a:min(a + 4096, start)] = trained[a:min(a + 4096, start)]
            del trained
        bycode = defaultdict(list)
        di = {day: t for t, day in enumerate(self.meta['days'])}
        stop = int(np.searchsorted(self.meta['days'], self.end, side='right'))
        for day, sl in self.slices.items():
            if sl.start < start:
                continue
            kept = np.flatnonzero(self.passed[sl])
            rows = kept + sl.start
            for name in CACHED:
                dest[rows, self.names.index(name)] = self.base_raw[rows, self.base_names.index(name)]
            for k in kept:
                bycode[self.meta['scope'][day][k]].append((di[day], sl.start + k))
        inputs = {}
        for count, (code, positions) in enumerate(bycode.items()):
            source = old.WORK / 'stocks' / (code + '.npz')
            inputs[str(source.relative_to(ROOT))] = prior.file_sha(source)
            with np.load(source) as z:
                arrays = {k: z[k][:stop] for k in ('c', 'h', 'l', 'v')}
            values = trigger_values(arrays)
            ts, rows = map(np.asarray, zip(*positions))
            for name, column in values.items():
                dest[rows, self.names.index(name)] = column[ts]
            if count % 200 == 0:
                print('trigger stock', count, '/', len(bycode), flush=True)
        for day, sl in self.slices.items():
            if sl.start < start:
                continue
            rows = np.flatnonzero(self.passed[sl]) + sl.start
            for name in CONTINUOUS + ANCHORS:
                j = self.names.index(name)
                dest[rows, j] = ie7.night_percentiles(dest[rows, j:j + 1])[:, 0]
        dest.flush()
        del dest
        old.prior.write_json(marker, dict(names=list(NAMES), rows=self.n, end=self.end, stocks=len(bycode),
            input_sha256=inputs, dataset_digest=self.meta['dataset_digest'],
            plan_sha256=prior.file_sha(PLAN), prereg_sha256=prior.file_sha(PREREG),
            source_sha256=prior.file_sha(Path(__file__)), feature_sha256=prior.file_sha(path)))
        self.values = np.load(path, mmap_mode='r')
        return self.values

    def select(self, scheme):
        values = self.features()
        ranks = np.full(self.n, old.prior.SENTINEL, np.int32)
        selected = {}
        for day, sl in self.slices.items():
            if day not in self.widths:
                continue
            order, ranks[sl] = rank_night(values[sl], self.passed[sl], self.names, scheme['factors'])
            selected[day] = [self.meta['scope'][day][k] for k in order[:5]]
        return selected, ie7.coverage(self.entries, self.query, ranks, self.passed)

    def evaluate(self, scheme):
        key = prior.digest(dict(scheme=scheme, end=self.end, label=self.label,
                                source=prior.file_sha(Path(__file__))))
        path = WORK / 'evaluations' / (key + '.json')
        if path.exists():
            return ie7.read(path)
        selected, coverage = self.select(scheme)
        account_key = prior.digest(dict(selected=selected, end=self.end))
        candidates = [WORK / 'accounts' / (account_key + '.json'),
                      ie8.WORK / 'accounts' / (account_key + '.json')]
        cached = next((p for p in candidates if p.exists()), None)
        accounts = ie7.read(cached) if cached else self.accounts(selected)
        if cached is None:
            old.prior.write_json(candidates[0], accounts)
        eligible, failures = qualify(coverage, self.expected, accounts)
        value = dict(scheme=scheme, coverage=coverage, accounts=accounts, eligible=eligible, failures=failures,
            expected=self.expected, selected=selected, selection_hash=account_key, nightly_widths=self.widths,
            width=ie8.width_summary(self.widths))
        value['score'], value['losses'] = list(score_key(value)), ie7.losses(value)
        old.prior.write_json(path, value)
        return value


def describe(d):
    values = d.features()
    def rows(primary):
        result = []
        for j, name in enumerate(NAMES):
            row = dict(name=name, kind='percentile' if name in CONTINUOUS + ANCHORS else 'event', halves={})
            for half in HALVES:
                target, other, differences = [], [], []
                outside = gated_out = missing = 0
                indices = [i for i, e in enumerate(d.entries)
                           if ie7.half(e['entry_date']) == half and (not primary or e['target']['tier'] == 'primary')]
                for i in indices:
                    own, controls = [], []
                    for signal, q in zip(d.entries[i]['systems']['h4'], d.query[i]):
                        if q < 0:
                            outside += 1
                            continue
                        if not d.passed[q]:
                            gated_out += 1
                            continue
                        sl = d.slices[signal['date']]
                        others = np.flatnonzero(d.passed[sl]) + sl.start
                        others = others[others != q]
                        finite = values[others, j]
                        finite = finite[np.isfinite(finite)]
                        if not np.isfinite(values[q, j]) or not len(finite):
                            missing += 1
                            continue
                        own.append(float(values[q, j]))
                        controls.append(float(np.mean(finite) if row['kind'] == 'event' else np.median(finite)))
                    if own:
                        aggregate = np.mean if row['kind'] == 'event' else np.median
                        target.append(float(aggregate(own)))
                        other.append(float(aggregate(controls)))
                        differences.append(target[-1] - other[-1])
                aggregate = np.mean if row['kind'] == 'event' else np.median
                a = float(aggregate(target)) if target else None
                b = float(aggregate(other)) if other else None
                difference = float(aggregate(differences)) if differences else None
                row['halves'][half] = dict(n=len(indices), valid_entries=len(target), target=a, other=b,
                    difference=difference, ratio=a / b if a is not None and b else None,
                    outside_nights=outside, gated_out_nights=gated_out, missing_nights=missing)
            row['stable'] = all(r['difference'] is not None and r['difference'] > 0 for r in row['halves'].values())
            result.append(row)
        return result
    result = dict(primary=rows(True), all_entries=rows(False), gates=GATES,
                  plan_sha256=prior.file_sha(PLAN), prereg_sha256=prior.file_sha(PREREG))
    result['stable_triggers'] = stable_names(result)
    return result


def registration(number):
    spec_path = WORK / f'round{number}.json'
    spec = ie7.read(spec_path)
    if not 1 <= number <= 2 or not 1 <= len(spec['schemes']) <= 5:
        raise ValueError('IE9 round budget exceeded')
    allowed = stable_names(read('description'))
    for scheme in spec['schemes']:
        validate(scheme, allowed)
    value = dict(spec=spec, spec_sha256=prior.file_sha(spec_path), prereg_sha256=prior.file_sha(PREREG),
        prereg_text=PREREG.read_text(encoding='utf-8'), plan_sha256=prior.file_sha(PLAN),
        utc=datetime.now(timezone.utc).isoformat())
    write(f'round{number}_registration', value)
    return value


def run_round(number):
    reg = registration(number)
    d, results = Data(), []
    for scheme in reg['spec']['schemes']:
        result = d.evaluate(scheme)
        results.append(result)
        print(scheme['id'], result['score'], result['eligible'], result['losses'], flush=True)
    best = winner(results)
    write(f'round{number}', dict(registration=reg, results=results, winner=best))


def ablate(d, start):
    current, rounds = start, []
    while True:
        trials, accepted = [], False
        for k, name in enumerate(current['scheme']['factors']):
            scheme = dict(current['scheme'], factors=current['scheme']['factors'][:k] + current['scheme']['factors'][k + 1:])
            scheme['id'] += '-drop' + str(k)
            after = d.evaluate(scheme)
            accept = after['score'][0] >= current['score'][0]
            if current['eligible']:
                accept &= after['eligible']
            else:
                account_failures = lambda r: {f for f in r['failures'] if ':not_above_random_expectation' not in f}
                accept &= not (account_failures(after) - account_failures(current))
            trials.append(dict(removed=name, result=after, accepted=bool(accept)))
            if accept:
                current, accepted = after, True
                break
        rounds.append(dict(trials=trials))
        if not accepted:
            return dict(initial=start, rounds=rounds, final=current)


def random_controls(d, actual):
    records = []
    for seed in range(RANDOM_SEED, RANDOM_SEED + 30):
        rng = np.random.default_rng(seed)
        ranks = np.full(d.n, old.prior.SENTINEL, np.int32)
        for sl in d.slices.values():
            kept = np.flatnonzero(d.passed[sl]) + sl.start
            order = rng.permutation(kept)
            ranks[order] = np.arange(1, len(order) + 1)
        coverage = ie7.coverage(d.entries, d.query, ranks, d.passed)
        records.append(dict(seed=seed, coverage=coverage,
                            score=min(ie7.rate(coverage['halfyear'][h]) for h in HALVES)))
    def placement(value, baseline):
        better, ties = sum(x > value for x in baseline), sum(x == value for x in baseline)
        return dict(actual=value, rank=1 + better, tied_random=ties, strictly_beats=sum(x < value for x in baseline),
                    trials=len(baseline), mean=float(np.mean(baseline)), minimum=min(baseline), maximum=max(baseline))
    return dict(records=records, seed=RANDOM_SEED,
        score_placement=placement(actual['score'][0], [r['score'] for r in records]),
        annual_placement={y: placement(actual['coverage']['annual'][y]['primary']['hits']['5'],
            [r['coverage']['annual'][y]['primary']['hits']['5'] for r in records]) for y in (*YEARS, '2026')},
        combined_placement=placement(actual['coverage']['primary']['hits']['5'],
            [r['coverage']['primary']['hits']['5'] for r in records]))


def shuffle_stage():
    d = Data(shuffled=True)
    description = describe(d)
    write('shuffle_description', description)
    real = stable_names(read('description'))
    shuffled = stable_names(description)
    results, unavailable = [], []
    for path in sorted(WORK.glob('round[12].json')):
        for scheme in ie7.read(path)['schemes']:
            needed = [real.index(n) for n in scheme['factors'] if n in real]
            if max(needed, default=-1) >= len(shuffled):
                unavailable.append(scheme['id'])
                continue
            factors = [shuffled[real.index(n)] if n in real else n for n in scheme['factors']]
            candidate = dict(scheme, factors=factors)
            validate(candidate, shuffled)
            results.append(d.evaluate(candidate))
    if results:
        ablation = ablate(d, winner(results))
        result = ablation['final']
    else:
        ablation = None
        result = d.evaluate(dict(id='shuffle_empty_tie_baseline', factors=[], gates=GATES, rank_scope='small'))
    write('shuffle', dict(seed=SEED, stable_triggers=shuffled, results=results, unavailable=unavailable,
        fallback=not bool(results), ablation=ablation, final=result,
        note='同晚小池内共享置换；同结构稳定筛选和消融；退化同分基线不算合格触发模型。'))


def freeze():
    result = read('ablation')['final']
    write('frozen_selection', dict(final=result, freeze_utc=datetime.now(timezone.utc).isoformat(),
        selection_years=list(YEARS), exam_used_for_selection=False, plan_sha256=prior.file_sha(PLAN),
        prereg_sha256=prior.file_sha(PREREG), source_sha256=prior.file_sha(Path(__file__))))


def final_stage():
    if (REPORTS / (PREFIX + 'final.json')).exists():
        raise ValueError('IE9 final already evaluated; reuse the saved artifact')
    frozen = read('frozen_selection')
    d = Data(full=True)
    result = d.evaluate(frozen['final']['scheme'])
    historical = {day: codes for day, codes in result['selected'].items() if day <= prior.TRAIN_END}
    if historical != frozen['final']['selected']:
        raise AssertionError('future rows changed frozen historical selections')
    result['note'] = '2026已看过四次，不是干净的考试；仅冻结后报告，不据此调参。'
    result['frozen_sha256'] = prior.file_sha(REPORTS / (PREFIX + 'frozen_selection.json'))
    write('final', result)
    write('random_final', random_controls(d, result))
    print('FINAL', result['coverage']['annual']['2026']['primary'], flush=True)


def guard():
    def allowed(path):
        p = Path(os.fsdecode(path)).resolve()
        return p.is_relative_to(WORK.resolve()) or (p.parent == REPORTS.resolve() and p.name.startswith(PREFIX))

    def audit(name, args):
        if name == 'open':
            path, _, flags = args
            if not isinstance(path, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND) and not allowed(path):
                raise PermissionError('IE9 output boundary: ' + os.fsdecode(path))
        if name in ('socket.connect', 'socket.bind', 'os.system', 'subprocess.Popen'):
            raise PermissionError('IE9 offline single process')
        if name in ('os.remove', 'os.rename', 'os.rmdir', 'os.mkdir'):
            paths = args[:2] if name == 'os.rename' else args[:1]
            if any(not allowed(p) for p in paths):
                raise PermissionError('IE9 output boundary')
    sys.addaudithook(audit)


def main(stage):
    WORK.mkdir(exist_ok=True)
    for name in ('evaluations', 'accounts', 'tmp'):
        (WORK / name).mkdir(exist_ok=True)
    os.environ['TMPDIR'] = str(WORK / 'tmp')
    import tempfile
    tempfile.tempdir = str(WORK / 'tmp')
    guard()
    if stage == 'describe':
        result = describe(Data())
        write('description', result)
        print('STABLE', result['stable_triggers'], flush=True)
    elif stage.startswith('round'):
        run_round(int(stage[-1]))
    elif stage == 'ablate':
        results = [r for p in sorted(REPORTS.glob(PREFIX + 'round[12].json')) for r in ie7.read(p)['results']]
        if not results:
            results = [Data().evaluate(dict(id='no_stable_trigger_tie_baseline', factors=[], gates=GATES, rank_scope='small'))]
        result = ablate(Data(), winner(results))
        write('ablation', result)
        print('ABLATION', result['final']['scheme'], result['final']['score'], flush=True)
    elif stage == 'random':
        write('random', random_controls(Data(), read('ablation')['final']))
    else:
        dict(shuffle=shuffle_stage, freeze=freeze, final=final_stage)[stage]()
    write('runtime_' + stage, dict(completed_utc=datetime.now(timezone.utc).isoformat(),
        plan_sha256=prior.file_sha(PLAN), prereg_sha256=prior.file_sha(PREREG),
        source_sha256=prior.file_sha(Path(__file__)), peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('stage', choices=('describe', 'round1', 'round2', 'ablate', 'random', 'shuffle', 'freeze', 'final'))
    main(parser.parse_args().stage)
