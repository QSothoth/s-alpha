"""TF7 (notes/TF7_PREREG.md): W4 entry frozen, exits aligned with the signal horizon; A-shares, point-in-time pool.

    PY="env PYTHONUTF8=1 /opt/futu-opend/venv/bin/python"
    $PY -m studies.trend_breakout.run_tf7 dev        # X1-X3 on train + test (already seen), pick the winner
    $PY -m studies.trend_breakout.run_tf7 B X1       # the frozen winner on 2019-03 -> 2023-08, once

Writes reports/tf7_<mode>.json and trades to data/trend-breakout-v1-results/tf7_<mode>.json.
"""
from __future__ import annotations

import json
import sys

import numpy as np

from . import backtest, pit, run_tf1, run_tf6, signals
from .run_tf1 import DATA, REPORTS, TRADES

EXITS = {'X1': {'max_hold': 20, 'use_stop': False}, 'X2': {'max_hold': 20, 'use_stop': True},
         'X3': {'max_hold': 60, 'use_stop': True}}


def trade_criteria(d):
    return {'n>=50': d['n'] >= 50, 'mean_r>0': d['mean_r'] > 0, 'excess>0': d['mean_excess'] > 0,
            'ex_top5>0': d['mean_r_ex_top5'] > 0}


def run_exit(p, ind, pool, lo, hi, name):
    entry, line, ratchet = signals.evaluate(ind, 'W4', pool)
    limit = np.array([run_tf1.cn_limit(c) for c in p['codes']])
    tr, skipped = backtest.run(p, entry, line, ratchet, pool, ind['atr22'], lo, hi, run_tf1.MARKETS['cn']['cost'],
                               limit, **EXITS[name])
    d = run_tf1.summarize(tr, backtest.ew_benchmark(p, pool, tr), p['dates'])
    d['skipped'] = skipped
    d['criteria'] = trade_criteria(d) if d['n'] else {'n': False}
    trades = {**{k: v.tolist() for k, v in tr.items()}, 'code': [str(p['codes'][j]) for j in tr['stock']],
              'entry_date': [str(p['dates'][i]) for i in tr['entry']]}
    return d, trades


def load_dev():
    cands = set(json.loads((pit.CNX / 'progress.json').read_text())['done'])
    meta = [DATA / 'cn', pit.CNX]
    return pit.load([(DATA / 'cn', '2023-09-01', '2026-10-09', None),
                     (pit.HIST_CNX, '2023-09-01', '2026-10-09', cands)], meta,
                    keep=lambda q: np.nanmax(np.nan_to_num(q['mktcap']), axis=0) >= run_tf6.MIN_CAP)


def load_b():
    cands = set(json.loads((pit.CNX / 'progress.json').read_text())['done'])
    meta = [DATA / 'cn', pit.CNX]

    def keep(q):
        span = (q['dates'] >= run_tf6.B_SPAN[0]) & (q['dates'] <= run_tf6.B_SPAN[1])
        return np.nanmax(np.nan_to_num(q['mktcap'][span]), axis=0) >= run_tf6.MIN_CAP
    return pit.load([(pit.HIST, '2018-01-01', run_tf6.B_SPAN[1], None),
                     (pit.HIST_CNX, '2018-01-01', run_tf6.B_SPAN[1], cands)],
                    meta, keep=keep)


def main():
    np.seterr(invalid='ignore', divide='ignore')
    mode = sys.argv[1]
    out, trades = {}, {}
    if mode == 'dev':
        p = load_dev()
        pool, ind = run_tf6.pit_pool(p), signals.indicators(p)
        for split in ('train', 'test'):
            lo, hi = run_tf6.rows(p, *run_tf1.panel.SPLITS[split])
            for name in EXITS:
                out[f'{name}_{split}'], trades[f'{name}_{split}'] = run_exit(p, ind, pool, lo, hi, name)
                d = out[f'{name}_{split}']
                print(f"{name} {split}: n={d['n']} R={d['mean_r']:+.3f} win={d['win_rate']:.1%} payoff={d['payoff']:.2f} "
                      f"ext={d['mean_r_ex_top5']:+.3f} exc={d['mean_excess']:+.2%} hold={d['median_hold']:.0f} "
                      f"criteria={sum(d['criteria'].values())}/4", flush=True)
        ok = [n for n in EXITS if all(out[f'{n}_train']['criteria'].values()) and all(out[f'{n}_test']['criteria'].values())]
        out['winner'] = max(ok, key=lambda n: out[f'{n}_train']['mean_r'] + out[f'{n}_test']['mean_r']) if ok else None
        print('winner:', out['winner'])
    else:
        name = sys.argv[2]
        p = load_b()
        pool, ind = run_tf6.pit_pool(p), signals.indicators(p)
        lo, hi = run_tf6.rows(p, *run_tf6.B_SPAN)
        out[name], trades[name] = run_exit(p, ind, pool, lo, hi, name)
        d = out[name]
        out['verdict'] = all(d['criteria'].values())
        print(f"B {name}: n={d['n']} R={d['mean_r']:+.3f} ext={d['mean_r_ex_top5']:+.3f} verdict={out['verdict']}")
    TRADES.mkdir(parents=True, exist_ok=True)
    (TRADES / f'tf7_{mode}.json').write_text(json.dumps(trades, ensure_ascii=False) + '\n', encoding='utf-8')
    (REPORTS / f'tf7_{mode}.json').write_text(json.dumps(out, ensure_ascii=False, indent=1, default=float) + '\n',
                                              encoding='utf-8')


if __name__ == '__main__':
    main()
