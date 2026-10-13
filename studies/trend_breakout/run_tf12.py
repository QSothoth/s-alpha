"""TF12 (notes/TF12_PREREG.md): chase-the-breakout with a market filter and a failed-breakout exit, A-share PIT pool.

    PY="env PYTHONUTF8=1 /opt/futu-opend/venv/bin/python"
    $PY -m studies.trend_breakout.run_tf12 dev          # K1-K4 on 2019-03-01 -> 2022-06-30
    $PY -m studies.trend_breakout.run_tf12 holdout K?   # the dev winner on 2022-07-01 -> 2026-10-09, once
"""
from __future__ import annotations

import json
import sys

import numpy as np

from . import backtest, run_tf1, run_tf6, run_tf8, signals as S
from .run_tf1 import REPORTS, TRADES

SPANS = run_tf8.SPANS
RULES = {'K1': ('hh55_prev', True, False), 'K2': ('hh55_prev', False, True), 'K3': ('hh55_prev', True, True),
         'K4': ('hh252_prev', True, True)}  # breakout level, market filter, failed-breakout exit
FAIL_DAYS = 10


def indicators(p):
    valid = ~np.isnan(p['close'])
    c = {k: S.compact(p[k], valid)[0] for k in ('high', 'low', 'close')}
    order = S.compact(p['close'], valid)[1]
    cl = c['close']
    sma200 = S.sma(cl, 200)
    atr22 = S.atr(c['high'], c['low'], cl, 22)
    raw = {'ready': np.cumsum(~np.isnan(cl), axis=0) >= S.MIN_BARS, 'close': cl,
           'trend_ok': (cl > sma200) & (sma200 > S.shift(sma200, 20)),
           'hh252_prev': S.shift(S.rolling_max(c['high'], 252)), 'hh55_prev': S.shift(S.rolling_max(c['high'], 55)),
           'atr22': atr22, 'atr_trail': cl - 3 * atr22, 'above200': cl > sma200}
    return {k: S.scatter(x.astype(float), order, valid, np.nan if x.dtype != bool else 0.0) for k, x in raw.items()}


def run_one(p, ind, pool, up, lo, hi, rule, seeds=20):
    level, use_up, use_fail = RULES[rule]
    with np.errstate(invalid='ignore'):
        entry = S._bool(ind['ready']) & S._bool(ind['trend_ok']) & (ind['close'] > ind[level])
    if use_up:
        entry &= up[:, None]
    limit = np.array([run_tf1.cn_limit(x) for x in p['codes']])
    cost = run_tf1.MARKETS['cn']['cost']
    kw = {'fail_level': ind[level], 'fail_days': FAIL_DAYS} if use_fail else {}
    tr, skipped = backtest.run(p, entry, ind['atr_trail'], True, pool, ind['atr22'], lo, hi, cost, limit, **kw)
    d = run_tf1.summarize(tr, backtest.ew_benchmark(p, pool, tr), p['dates'])
    r = tr['r']
    d['p5R'] = float((r >= 5).mean()) if len(r) else float('nan')
    d['p10R'] = float((r >= 10).mean()) if len(r) else float('nan')
    years = {}
    for i, x in zip(tr['entry'], r):
        years.setdefault(str(p['dates'][i])[:4], []).append(x)
    d['years'] = {y: {'n': len(v), 'mean_r': float(np.mean(v))} for y, v in sorted(years.items())}
    rk = {'fail_level': ind['close'], 'fail_days': FAIL_DAYS} if use_fail else {}
    rnd = []
    for seed in range(seeds):
        re = backtest.random_entries(entry, pool, pool, np.random.default_rng(seed))
        t0, _ = backtest.run(p, re, ind['atr_trail'], True, pool, ind['atr22'], lo, hi, cost, limit, **rk)
        rnd.append((float(t0['r'].mean()), float((t0['r'] >= 5).mean())))
    rnd = np.array(rnd)
    d['random'] = {'mean_r': float(rnd[:, 0].mean()), 'mean_r_p95': float(np.percentile(rnd[:, 0], 95)),
                   'p5R': float(rnd[:, 1].mean()), 'p5R_p95': float(np.percentile(rnd[:, 1], 95))}
    d['skipped'] = skipped
    d['criteria'] = {'mean_r>0': d['mean_r'] > 0, 'beats_random_p95': d['mean_r'] > d['random']['mean_r_p95'],
                     'excess>0': d['mean_excess'] > 0, 'p5R>random_p95': d['p5R'] > d['random']['p5R_p95'],
                     'n>=200': d['n'] >= 200}
    trades = {**{k: v.tolist() for k, v in tr.items()}, 'code': [str(p['codes'][j]) for j in tr['stock']]}
    print(f"{rule}: n={d['n']} R={d['mean_r']:+.3f} win={d['win_rate']:.1%} payoff={d['payoff']:.2f} "
          f">=5R {d['p5R']:.2%} >=10R {d['p10R']:.2%} exc={d['mean_excess']:+.2%} hold={d['median_hold']:.0f} | "
          f"random R {d['random']['mean_r']:+.3f}/p95 {d['random']['mean_r_p95']:+.3f} >=5R {d['random']['p5R']:.2%}/p95 "
          f"{d['random']['p5R_p95']:.2%} | years { {y: round(v['mean_r'], 2) for y, v in d['years'].items()} } "
          f"| criteria {sum(d['criteria'].values())}/5", flush=True)
    return d, trades


def main():
    np.seterr(invalid='ignore', divide='ignore')
    mode = sys.argv[1]
    rules = tuple(RULES) if mode == 'dev' else (sys.argv[2],)
    if mode == 'holdout':
        dev = json.loads((REPORTS / 'tf12_dev.json').read_text(encoding='utf-8'))
        if dev['winner'] != rules[0]:
            raise SystemExit(f'holdout must use the dev winner {dev["winner"]}')
    p = run_tf8.load()
    pool = run_tf6.pit_pool(p)
    ind = indicators(p)
    up = S.market_up(p['close'], pool)
    lo, hi = run_tf6.rows(p, *SPANS[mode])
    out, trades = {'span': [str(p['dates'][lo]), str(p['dates'][hi])],
                   'market_up_share': float(up[lo:hi + 1].mean())}, {}
    for rule in rules:
        out[rule], trades[rule] = run_one(p, ind, pool, up, lo, hi, rule)
    if mode == 'dev':
        ok = [r for r in RULES if all(out[r]['criteria'].values())]
        out['winner'] = max(ok, key=lambda r: out[r]['mean_r']) if ok else None
        print('winner:', out['winner'])
    else:
        d = out[rules[0]]
        pos_years = sum(v['mean_r'] > 0 for v in d['years'].values())
        out['verdict'] = bool(all(d['criteria'].values()) and pos_years * 2 >= len(d['years']))
        print('positive years', pos_years, 'of', len(d['years']), 'verdict:', out['verdict'])
    TRADES.mkdir(parents=True, exist_ok=True)
    (TRADES / f'tf12_{mode}.json').write_text(json.dumps(trades, ensure_ascii=False) + '\n', encoding='utf-8')
    (REPORTS / f'tf12_{mode}.json').write_text(json.dumps(out, ensure_ascii=False, indent=1, default=float) + '\n',
                                               encoding='utf-8')


if __name__ == '__main__':
    main()
