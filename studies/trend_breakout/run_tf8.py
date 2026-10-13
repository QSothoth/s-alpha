"""TF8 (notes/TF8_PREREG.md): A-share anti-speculation candidates Y1-Y4 on the point-in-time pool, 2019-2026.

    PY="env PYTHONUTF8=1 /opt/futu-opend/venv/bin/python"
    $PY -m studies.trend_breakout.run_tf8 dev           # Y1-Y4 on 2019-03-01 -> 2022-06-30, pick the winner
    $PY -m studies.trend_breakout.run_tf8 holdout Y?    # the dev winner on 2022-07-01 -> 2026-10-09, once

Writes reports/tf8_<mode>.json and trades to data/trend-breakout-v1-results/tf8_<mode>.json.
"""
from __future__ import annotations

import json
import sys

import numpy as np

from . import backtest, pit, run_tf1, run_tf6, signals
from .run_tf1 import DATA, REPORTS, TRADES

SPANS = {'dev': ('2019-03-01', '2022-06-30'), 'holdout': ('2022-07-01', '2026-10-09')}
RULES = ('Y1', 'Y2', 'Y3', 'Y4')


def load():
    cands = set(json.loads((pit.CNX / 'progress.json').read_text())['done'])
    meta = [DATA / 'cn', pit.CNX]

    def keep(q):
        span = q['dates'] >= SPANS['dev'][0]
        return np.nanmax(np.nan_to_num(q['mktcap'][span]), axis=0) >= run_tf6.MIN_CAP
    return pit.load([(pit.HIST, '2018-01-01', '2023-08-31', None),
                     (DATA / 'cn', '2023-09-01', '2026-10-09', None),
                     (pit.HIST_CNX, '2018-01-01', '2026-10-09', cands)],
                    meta, keep=keep)


def evaluate(p, ind, pool, lo, hi, rule):
    entry = signals.defensive_entry(ind, pool, rule)
    limit = np.array([run_tf1.cn_limit(c) for c in p['codes']])
    tr, skipped = backtest.run(p, entry, ind['atr_trail'], True, pool, ind['atr22'], lo, hi,
                               run_tf1.MARKETS['cn']['cost'], limit, max_hold=20, use_stop=False)
    d = run_tf1.summarize(tr, backtest.ew_benchmark(p, pool, tr), p['dates'])
    res = {'daily': d, 'skipped': skipped, 'event': run_tf1.event_study(p, entry, pool, lo, hi),
           'month_t': run_tf6.month_t(p, entry, pool, lo, hi)}
    rng = np.random.default_rng(0)  # 20 random-entry draws (same daily counts), same exit, as a reference
    r0 = []
    for _ in range(20):
        rnd = backtest.random_entries(entry, pool, pool, rng)
        t0, _ = backtest.run(p, rnd, ind['atr_trail'], True, pool, ind['atr22'], lo, hi,
                             run_tf1.MARKETS['cn']['cost'], limit, max_hold=20, use_stop=False)
        r0.append(float(t0['r'].mean()) if len(t0['r']) else float('nan'))
    res['R0_mean'] = float(np.nanmean(r0))
    years = {}
    for i, r in zip(tr['entry'], tr['r']):
        years.setdefault(str(p['dates'][i])[:4], []).append(r)
    res['by_year'] = {y: {'n': len(v), 'mean_r': float(np.mean(v))} for y, v in sorted(years.items())}
    e, m = res['event'][20], res['month_t']
    ev_ok = e.get('n', 0) > 0 and e['mean_excess'] > 0 and e['boot90'][0] > 0
    trade_ok = d.get('n', 0) >= 100 and d['mean_r'] > 0 and d['mean_excess'] > 0 and d['mean_r_ex_top5'] > 0
    res['criteria'] = {'event20': ev_ok, 'trade': trade_ok, 't_month': m['t_month']}
    trades = {**{k: v.tolist() for k, v in tr.items()}, 'code': [str(p['codes'][j]) for j in tr['stock']]}
    print(f"{rule}: n={d.get('n')} R={d.get('mean_r', 0):+.3f} win={d.get('win_rate', 0):.1%} "
          f"payoff={d.get('payoff', 0):.2f} ext={d.get('mean_r_ex_top5', 0):+.3f} exc={d.get('mean_excess', 0):+.2%} "
          f"ev20={e.get('mean_excess', float('nan')):+.4f} [{e.get('boot90', [0, 0])[0]:+.4f},{e.get('boot90', [0, 0])[1]:+.4f}] "
          f"t={m['t_month']:.2f} R0={res['R0_mean']:+.3f}", flush=True)
    return res, trades


def main():
    np.seterr(invalid='ignore', divide='ignore')
    mode = sys.argv[1]
    rules = RULES if mode == 'dev' else (sys.argv[2],)
    if mode == 'holdout':
        dev = json.loads((REPORTS / 'tf8_dev.json').read_text(encoding='utf-8'))
        if dev['winner'] != rules[0]:
            raise SystemExit(f'holdout must use the dev winner {dev["winner"]}')
    p = load()
    pool = run_tf6.pit_pool(p)
    ind = signals.defensive_indicators(p)
    lo, hi = run_tf6.rows(p, *SPANS[mode])
    out, trades = {'span': [str(p['dates'][lo]), str(p['dates'][hi])], 'stocks': len(p['codes']),
                   'pool_per_day': float(pool[lo:hi + 1].sum(axis=1).mean())}, {}
    for rule in rules:
        out[rule], trades[rule] = evaluate(p, ind, pool, lo, hi, rule)
    if mode == 'dev':
        ok = [r for r in RULES if out[r]['criteria']['event20'] and out[r]['criteria']['trade']
              and out[r]['criteria']['t_month'] >= 2]
        out['winner'] = max(ok, key=lambda r: out[r]['event'][20]['mean_excess']) if ok else None
        print('winner:', out['winner'])
    else:
        c = out[rules[0]]['criteria']
        out['verdict'] = bool(c['event20'] and c['trade'] and c['t_month'] >= 1.5)
        print('holdout verdict:', out['verdict'])
    TRADES.mkdir(parents=True, exist_ok=True)
    (TRADES / f'tf8_{mode}.json').write_text(json.dumps(trades, ensure_ascii=False) + '\n', encoding='utf-8')
    (REPORTS / f'tf8_{mode}.json').write_text(json.dumps(out, ensure_ascii=False, indent=1, default=float) + '\n',
                                              encoding='utf-8')


if __name__ == '__main__':
    main()
