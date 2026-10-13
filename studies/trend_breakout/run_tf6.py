"""TF6 (notes/TF6_PREREG.md): W4 frozen, point-in-time A-share pool; A = bias correction on train/test,
B = out-of-time check on 2019-03-01 -> 2023-08-31 (the only verdict of this round).

    PYTHONUTF8=1 /opt/futu-opend/venv/bin/python -m studies.trend_breakout.run_tf6 A   # then: ... run_tf6 B

Each part is its own process (memory: the machine has ~2 GB free). Writes reports/tf6_<part>.json and the
trades to data/trend-breakout-v1-results/tf6_<part>.json.
"""
from __future__ import annotations

import json
import math

import numpy as np

from . import pit, run_tf1, signals
from .run_tf1 import DATA, REPORTS, TRADES

MIN_CAP = 1e10
B_SPAN = ('2019-03-01', '2023-08-31')


def pit_pool(p):
    """Point-in-time pool: cap >= 10bn CNY on the day, 20-day turnover >= 100m CNY, current ST names out."""
    cfg = run_tf1.MARKETS['cn']
    ok = signals.liquid(p, cfg['min_turnover']) & (np.nan_to_num(p['mktcap']) >= MIN_CAP)
    st = np.array([run_tf1.is_st(p['names'][c]) for c in p['codes']])
    return ok & ~st[None, :]


def month_t(p, entry, pool, lo, hi, h=20):
    """Equal-weight t statistic of monthly mean event excess, and the first-signal-per-h-days version."""
    o, c = p['open'], p['close']
    per_month, dedup, last_sig = {}, [], {}
    for t in range(max(lo - 1, 0), hi - h + 1):
        sig = entry[t] & pool[t]
        if not sig.any():
            continue
        ret = c[t + h] / o[t + 1] - 1
        base = ret[pool[t] & ~np.isnan(ret)]
        for j in np.flatnonzero(sig & ~np.isnan(ret)):
            x = ret[j] - base.mean()
            per_month.setdefault(p['dates'][t + 1][:7], []).append(x)
            if t - last_sig.get(j, -10 ** 9) >= h:
                dedup.append(x)
                last_sig[j] = t
    means = np.array([np.mean(v) for v in per_month.values()])
    t_stat = means.mean() / (means.std(ddof=1) / math.sqrt(len(means))) if len(means) > 1 else math.nan
    return {'months': len(means), 'month_mean': float(means.mean()) if len(means) else math.nan,
            't_month': float(t_stat), 'dedup_n': len(dedup), 'dedup_mean': float(np.mean(dedup)) if dedup else math.nan}


def by_year(p, trades, event_rows):
    years = {}
    for d, r in zip(trades['entry_date'], trades['r']):
        years.setdefault(d[:4], []).append(r)
    return {y: {'n': len(v), 'mean_r': float(np.mean(v))} for y, v in sorted(years.items())}


def evaluate(p, pool, lo, hi, label):
    ind = signals.indicators(p)
    limit = np.array([run_tf1.cn_limit(c) for c in p['codes']])
    cfg = run_tf1.MARKETS['cn']
    res, tr = run_tf1.run_rule(p, ind, 'W4', pool, lo, hi, cfg, limit)
    v1 = signals.evaluate(ind, 'V1', pool)[0]
    w4 = signals.evaluate(ind, 'W4', pool)[0]
    res['v1_event'] = run_tf1.event_study(p, v1, pool, lo, hi)
    res['tf5_criteria'] = run_tf1.gates(res, 'test', 'tf5')
    res['original7'] = run_tf1.gates(res, 'train', 'tf4')
    res['month_t'] = {'W4': month_t(p, w4, pool, lo, hi), 'V1': month_t(p, v1, pool, lo, hi)}
    trades = {**tr, 'code': [str(p['codes'][j]) for j in tr['stock']],
              'entry_date': [str(p['dates'][i]) for i in tr['entry']],
              'exit_date': [str(p['dates'][i]) for i in tr['exit']]}
    res['by_year'] = by_year(p, trades, None)
    res['span'] = [str(p['dates'][lo]), str(p['dates'][hi])]
    res['pool_per_day'] = float(pool[lo:hi + 1].sum(axis=1).mean())
    d = res['daily']
    print(f"{label}: n={d['n']} R={d['mean_r']:+.3f} ext={d['mean_r_ex_top5']:+.3f} "
          f"ev20={res['event'][20].get('mean_excess', float('nan')):+.4f} v1={res['v1_event'][20].get('mean_excess', float('nan')):+.4f} "
          f"tf5={sum(res['tf5_criteria'].values())}/{len(res['tf5_criteria'])}", flush=True)
    return res, trades


def rows(p, start, end):
    idx = np.flatnonzero((p['dates'] >= start) & (p['dates'] <= end))
    return int(idx[0]), int(idx[-1])


def main():
    import sys
    np.seterr(invalid='ignore', divide='ignore')
    which = sys.argv[1] if len(sys.argv) > 1 else 'A'
    cands = set(json.loads((pit.CNX / 'progress.json').read_text())['done'])
    meta = [DATA / 'cn', pit.CNX]
    out, trades = {}, {}
    if which == 'A':  # bias correction: same window as TF1-TF5 (2023-09 onwards), point-in-time pool
        pa = pit.load([(DATA / 'cn', '2023-09-01', '2026-10-09', None),
                       (pit.HIST_CNX, '2023-09-01', '2026-10-09', cands)], meta,
                      keep=lambda q: np.nanmax(np.nan_to_num(q['mktcap']), axis=0) >= MIN_CAP)
        pool = pit_pool(pa)
        for split in ('train', 'test'):
            lo, hi = rows(pa, *run_tf1.panel.SPLITS[split])
            out[f'A_{split}'], trades[f'A_{split}'] = evaluate(pa, pool, lo, hi, f'A {split}')
        out['coverage_A'] = {'stocks': len(pa['codes']), 'candidates': len(cands)}
    else:  # B: out-of-time; history from 2018 for indicators, verdict on 2019-03-01 -> 2023-08-31
        def keep(q):  # stocks never in the point-in-time cap range during B can never enter the pool
            span = (q['dates'] >= B_SPAN[0]) & (q['dates'] <= B_SPAN[1])
            return np.nanmax(np.nan_to_num(q['mktcap'][span]), axis=0) >= MIN_CAP
        pb = pit.load([(pit.HIST, '2018-01-01', B_SPAN[1], None),
                       (pit.HIST_CNX, '2018-01-01', B_SPAN[1], cands)], meta, keep=keep)
        pool = pit_pool(pb)
        lo, hi = rows(pb, *B_SPAN)
        out['B'], trades['B'] = evaluate(pb, pool, lo, hi, 'B out-of-time')
        out['B']['verdict'] = all(out['B']['tf5_criteria'].values())
        out['coverage_B'] = {'stocks': len(pb['codes']), 'candidates': len(cands)}
        print('B verdict:', out['B']['verdict'])
    TRADES.mkdir(parents=True, exist_ok=True)
    (TRADES / f'tf6_{which}.json').write_text(json.dumps(trades, ensure_ascii=False) + '\n', encoding='utf-8')
    (REPORTS / f'tf6_{which}.json').write_text(json.dumps(out, ensure_ascii=False, indent=1, default=float) + '\n',
                                               encoding='utf-8')


if __name__ == '__main__':
    main()
