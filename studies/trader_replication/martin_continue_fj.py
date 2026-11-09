"""FJ: matched initial-risk first-passage opportunities in fixed daily setups."""
from collections import Counter, defaultdict
import gc
import json
from pathlib import Path

import numpy as np
from studies import trader_data
from studies.trader_replication import martin_continue_du as du
from studies.trader_replication import martin_continue_fg as fg
from studies.trader_replication import panels
from studies.trader_replication.martin_continue_dq import sha
from studies.trader_replication.martin_strong_scan import longs

HORIZON, COST, BLOCK, DRAWS, SEED = 120, .0005, 21, 1000, 20261103


def first_passage(opening, high, low, close, entry, stop):
    """Return status, terminal reason and known target hits for a prior-stop order."""
    op = float(opening[entry])
    if not np.isfinite(op) or op <= 0 or not np.isfinite(stop) or stop <= 0:
        return 'unknown', 'missing_open_or_stop', (None, None)
    if np.float32(op) == np.float32(stop):
        return 'unknown', 'precision_unknown', (None, None)
    if op <= stop:
        return 'cancel', 'open_below_stop', (False, False)
    risk = op * (1 + COST) - stop * (1 - COST)
    if risk <= 0:
        return 'unknown', 'invalid_risk', (None, None)
    targets = [(op * (1 + COST) + n * risk) / (1 - COST) for n in (3, 5)]
    hits = [None, None]
    end = min(entry + HORIZON, len(opening))
    for i in range(entry, end):
        o, h, l, c = map(float, (opening[i], high[i], low[i], close[i]))
        if not (all(np.isfinite(v) and v > 0 for v in (o, h, l, c)) and
                l <= min(o, c) and h >= max(o, c)):
            return 'filled', 'invalid_bar', tuple(hits)
        if o <= stop:
            return 'filled', 'gap_stop', tuple(False if x is None else x for x in hits)
        for k, target in enumerate(targets):
            if hits[k] is None and o >= target:
                hits[k] = True
        if l <= stop:
            return 'filled', 'stop', tuple(False if x is None else x for x in hits)
        for k, target in enumerate(targets):
            if hits[k] is None and h >= target:
                hits[k] = True
        if all(x is True for x in hits):
            return 'filled', 'both_targets', tuple(hits)
    if end - entry == HORIZON:
        return 'filled', 'horizon', tuple(False if x is None else x for x in hits)
    return 'filled', 'end_unmatured', tuple(hits)


def adr_buckets(candidates, adr):
    values = np.array([adr[e[1]] for e in candidates], dtype=float)
    valid = np.isfinite(values) & (values > 0)
    result = [None] * len(values)
    if valid.any():
        boundaries = np.quantile(values[valid], [1 / 3, 2 / 3])
        for i in np.flatnonzero(valid):
            result[i] = int(np.searchsorted(boundaries, values[i], side='right'))
    return result


def group_summary(rows, conditional):
    out = {}
    for name, selected in (('top4', True), ('other', False)):
        sample = [r for r in rows if r['selected'] == selected]
        result = {'orders': len(sample), 'status': dict(Counter(r['status'] for r in sample)),
                  'terminal': dict(Counter(r['terminal'] for r in sample)),
                  'adr_unknown': sum(r['adr_bin'] is None for r in sample)}
        for metric in ('hit3', 'hit5'):
            eligible = [r for r in sample if not conditional or r['status'] == 'filled']
            valid = [r[metric] for r in eligible if r[metric] is not None]
            result[metric] = {'known': len(valid), 'unknown': len(eligible) - len(valid),
                              'excluded_not_filled': len(sample) - len(eligible),
                              'hits': sum(valid), 'rate': sum(valid) / len(valid) if valid else None}
        out[name] = result
    return out


def matched(rows, year_days, metric, conditional, rng):
    groups = defaultdict(lambda: [0, 0, 0, 0])
    for r in rows:
        if r['adr_bin'] is None or r[metric] is None or (conditional and r['status'] != 'filled'):
            continue
        q = groups[(r['day_index'], r['adr_bin'])]
        offset = 0 if r['selected'] else 2
        q[offset] += 1
        q[offset + 1] += int(r[metric])
    by_day = defaultdict(lambda: [0., 0])
    for (day, _), (n1, h1, n0, h0) in groups.items():
        if n1 and n0:
            by_day[day][0] += n1 * (h1 / n1 - h0 / n0)
            by_day[day][1] += n1
    blocks = []
    for start in range(0, len(year_days), BLOCK):
        block = year_days[start:start + BLOCK]
        blocks.append((sum(by_day[d][0] for d in block), sum(by_day[d][1] for d in block)))
    numerator = sum(x[0] for x in blocks)
    denominator = sum(x[1] for x in blocks)
    estimates = []
    for _ in range(DRAWS):
        picks = rng.integers(0, len(blocks), len(blocks))
        num = sum(blocks[k][0] for k in picks)
        den = sum(blocks[k][1] for k in picks)
        if den:
            estimates.append(num / den)
    interval = [float(x) for x in np.percentile(estimates, [2.5, 97.5])] if estimates else [None, None]
    return {'difference': numerator / denominator if denominator else None, 'interval': interval,
            'paired_days': sum(v[1] > 0 for v in by_day.values()), 'top4_weight': denominator,
            'blocks': len(blocks), 'bootstrap_known': len(estimates)}


def main():
    root = du.REPORTS
    reference = root / 'strong_continue_fg.json'
    ref = json.loads(reference.read_text())
    if ref['script_sha256'] != sha(Path(fg.__file__)):
        raise ValueError('FG source differs')
    dataset = trader_data.dataset('us', mode='frozen', version='trader-data-v1')
    if dataset.digest() != ref['dataset_digest']:
        raise ValueError('dataset differs')
    d = du.make_data(dataset)
    reg = [[((1.0,) + (e[0] if isinstance(e[0], tuple) else (e[0],)),) + tuple(e[1:6])
            for e in row] for row in longs(d.reg)]
    for name in ('fp', 'fwd', 'raw', 'o', 'h', 'l', 'c', 't', 'adr', 'to20', 'U', 'rk'):
        if hasattr(d, name):
            delattr(d, name)
    gc.collect()
    trace = {}
    cfg = {k: v for k, v in d.cfg.items() if k != 'short'}
    _, _, mask, pool = d.base.build(d.A, cfg, trace)
    del mask, pool
    checked = fg.candidate_rows(reg, trace['filtered'], trace['capped'], d.days)
    width = {'signal_days': len(checked), 'over_cap_days': sum(len(c) > n for _, c, n in checked),
             'all_fit_days': sum(len(c) == n for _, c, n in checked),
             'candidates': sum(len(c) for _, c, _ in checked), 'selected': sum(n for _, _, n in checked)}
    if width != ref['width']:
        raise AssertionError('FG candidate width differs')
    del checked
    A = d.A
    last = np.full(len(A['codes']), -10000, dtype=np.int32)
    rows = []
    for day, candidates in enumerate(trace['filtered'][:-1]):
        if not candidates:
            continue
        spaced = []
        for e in candidates:
            j = e[1]
            use = day - last[j] >= 21
            spaced.append(bool(use))
            if use:
                last[j] = day
        entry_day = day + 1
        if not panels.WINDOW[0] <= d.days[entry_day] <= panels.WINDOW[1]:
            continue
        if day == 0:
            bins = [None] * len(candidates)
        else:
            bins = adr_buckets(candidates, A['adr'][day - 1])
        selected = {e[1] for e in trace['capped'][day]}
        for e, bucket, spaced_ok in zip(candidates, bins, spaced):
            j, stop = int(e[1]), float(e[4])
            status, terminal, hits = first_passage(A['open'][:, j], A['high'][:, j], A['low'][:, j],
                                                   A['close'][:, j], entry_day, stop)
            rows.append({'day_index': day, 'signal_day': d.days[day], 'entry_day': d.days[entry_day],
                         'year': d.days[entry_day][:4], 'code': str(A['codes'][j]), 'selected': j in selected,
                         'adr_bin': bucket, 'spaced': spaced_ok, 'status': status, 'terminal': terminal,
                         'hit3': hits[0], 'hit5': hits[1], 'stop': stop})
    if len(rows) != width['candidates'] or sum(r['selected'] for r in rows) != width['selected']:
        raise AssertionError('candidate outcome counts differ')
    rng = np.random.default_rng(SEED)
    result = {}
    for year in ('2024', '2025', '2026'):
        year_days = [i for i in range(len(d.days) - 1) if panels.WINDOW[0] <= d.days[i + 1] <= panels.WINDOW[1]
                     and d.days[i + 1].startswith(year)]
        result[year] = {}
        for sample in ('all', 'spaced'):
            subset = [r for r in rows if r['year'] == year and (sample == 'all' or r['spaced'])]
            result[year][sample] = {}
            for mode, conditional in (('per_filled', True), ('per_preselected', False)):
                result[year][sample][mode] = {'groups': group_summary(subset, conditional),
                                               'matched': {m: matched(subset, year_days, m, conditional, rng)
                                                           for m in ('hit3', 'hit5')}}
    out = {'dataset_digest': ref['dataset_digest'], 'fg_sha256': sha(reference),
           'script_sha256': sha(Path(__file__)), 'seed': SEED, 'bootstrap_draws': DRAWS,
           'horizon': HORIZON, 'cost': COST, 'width': width, 'results': result, 'rows': rows}
    target = root / 'strong_continue_fj.json'
    with target.open('w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
        f.write('\n')
    print('wrote', target, 'rows', len(rows), flush=True)


if __name__ == '__main__':
    main()
