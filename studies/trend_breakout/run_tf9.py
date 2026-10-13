"""TF9 (notes/TF9_PREREG.md): trend following on A-share broad indices, long or cash, 2005-2026.

    PY="env PYTHONUTF8=1 /opt/futu-opend/venv/bin/python"
    $PY -m studies.trend_breakout.run_tf9 fetch          # once: data/index-cn-daily-v1/bars.csv.gz (Tencent static + Sina)
    $PY -m studies.trend_breakout.run_tf9 dev            # Z1-Z3 on 2005-2015, pick the winner
    $PY -m studies.trend_breakout.run_tf9 holdout Z?     # the dev winner on 2016-01-01 -> 2026-10-09, once
"""
from __future__ import annotations

import csv
import gzip
import json
import math
import sys

import numpy as np

from . import fetch, signals, sources
from .run_tf1 import REPORTS, ROOT

FOLDER = ROOT / 'data' / 'index-cn-daily-v1'  # Release index-cn-daily-v1 (see docs/DATA.md)
INDICES = {'SH.000001': '上证综指', 'SH.000300': '沪深300', 'SH.000905': '中证500', 'SZ.399006': '创业板指',
           'SH.000852': '中证1000'}
SPANS = {'dev': ('2005-01-01', '2015-12-31'), 'holdout': ('2016-01-01', '2026-10-09')}
COST = 0.001
RULES = ('Z1', 'Z2', 'Z3')


def do_fetch():
    FOLDER.mkdir(parents=True, exist_ok=True)
    src = sources.CnHttpSource()
    rows = []
    for code in INDICES:
        rows += src.history_tencent(code, '2005-01-01', '2026-10-09')
    with gzip.open(FOLDER / 'bars.csv.gz', 'wt', encoding='utf-8', newline='') as f:
        csv.writer(f).writerows([sources.COLUMNS] + rows)
    fetch.write_json(FOLDER / 'meta.json', {'source': 'Tencent static yearly files to 2022-10-24, Sina after',
                                           'indices': INDICES, 'fetched_utc': fetch.now(), 'rows': len(rows)})
    print(len(rows), 'rows')


def load(code):
    with gzip.open(FOLDER / 'bars.csv.gz', 'rt', encoding='utf-8', newline='') as f:
        rows = [r for r in csv.reader(f) if r[0] == code]
    d = np.array([r[1] for r in rows])
    o, h, l, c = (np.array([float(r[k]) for r in rows]) for k in (2, 3, 4, 5))
    return d, o, h, l, c


def target(rule, h, l, c):
    """Desired position at each close (1 = hold the index), known at that close; 0 before 252 bars."""
    x = c[:, None]
    pos = np.zeros(len(c))
    if rule == 'Z1':
        pos = (x > signals.sma(x, 200))[:, 0].astype(float)
    elif rule == 'Z2':
        pos = np.nan_to_num(x / signals.shift(x, 252) - 1 > 0)[:, 0].astype(float)
    else:
        hh = signals.shift(signals.rolling_max(h[:, None], 55))[:, 0]
        ll = signals.shift(signals.rolling_min(l[:, None], 20))[:, 0]
        state = 0.0
        for t in range(len(c)):
            if state == 0 and c[t] > hh[t]:
                state = 1.0
            elif state == 1 and c[t] < ll[t]:
                state = 0.0
            pos[t] = state
    pos[:252] = 0
    return pos


def simulate(d, o, c, pos, start, end):
    """Daily strategy and buy-and-hold returns over [start, end]: the overnight move belongs to yesterday's
    position, the move from today's open to close to the position taken at today's open; a switch costs COST."""
    idx = np.flatnonzero((d >= start) & (d <= end))
    strat, hold, trades, cur = [], [], [], None
    for t in idx:
        if t == 0:
            continue
        prev_pos, new_pos = pos[t - 2] if t >= 2 else 0.0, pos[t - 1]
        night = o[t] / c[t - 1] - 1
        day = c[t] / o[t] - 1
        r = (1 + prev_pos * night) * (1 + new_pos * day) - 1
        if new_pos != prev_pos:
            r -= COST
            if new_pos == 1:
                cur = o[t]
            elif cur is not None:
                trades.append(o[t] * (1 - COST) / (cur * (1 + COST)) - 1)
                cur = None
        strat.append(r)
        hold.append(c[t] / c[t - 1] - 1)
    if cur is not None:  # open at the end: mark to the last close
        trades.append(c[idx[-1]] * (1 - COST) / (cur * (1 + COST)) - 1)
    years = {}
    for t, r in zip(idx[idx > 0], strat):
        years.setdefault(d[t][:4], []).append(r)
    return np.array(strat), np.array(hold), np.array(trades), years, pos[idx - 1].mean()


def stats(r):
    if not len(r):
        return {}
    eq = np.cumprod(1 + r)
    dd = (eq / np.maximum.accumulate(eq) - 1).min()
    sd = r.std()
    return {'cagr': float(eq[-1] ** (252 / len(r)) - 1), 'vol': float(sd * math.sqrt(252)),
            'sharpe': float(r.mean() / sd * math.sqrt(252)) if sd > 0 else math.nan, 'max_dd': float(dd),
            'total': float(eq[-1] - 1)}


def evaluate(rule, span):
    out = {}
    for code, name in INDICES.items():
        d, o, h, l, c = load(code)
        if not len(d) or d[-1] < span[0]:
            continue
        pos = target(rule, h, l, c)
        r, b, tr, years, in_mkt = simulate(d, o, c, pos, *span)
        if len(r) < 252 * 3 and span == SPANS['dev']:
            continue  # fewer than 3 years in the development span
        s, bh = stats(r), stats(b)
        win, loss = tr[tr > 0], tr[tr <= 0]
        out[code] = {'name': name, 'days': len(r), 'strategy': s, 'buy_hold': bh, 'in_market': float(in_mkt),
                     'trades': int(len(tr)), 'win_rate': float(len(win) / len(tr)) if len(tr) else math.nan,
                     'payoff': float(win.mean() / -loss.mean()) if len(win) and len(loss) else math.nan,
                     'years': {y: float(np.prod(1 + np.array(v)) - 1) for y, v in years.items()},
                     'effective': bool(s['sharpe'] > bh['sharpe'] and s['max_dd'] > bh['max_dd'])}
    return out


def main():
    mode = sys.argv[1]
    if mode == 'fetch':
        return do_fetch()
    np.seterr(invalid='ignore', divide='ignore')
    rules = RULES if mode == 'dev' else (sys.argv[2],)
    if mode == 'holdout':
        dev = json.loads((REPORTS / 'tf9_dev.json').read_text(encoding='utf-8'))
        if dev['winner'] != rules[0]:
            raise SystemExit(f'holdout must use the dev winner {dev["winner"]}')
    res = {r: evaluate(r, SPANS[mode]) for r in rules}
    for r, per in res.items():
        for code, x in per.items():
            s, b = x['strategy'], x['buy_hold']
            print(f"{r} {x['name']}: sharpe {s['sharpe']:.2f} vs {b['sharpe']:.2f} | maxDD {s['max_dd']:.1%} vs {b['max_dd']:.1%} | "
                  f"cagr {s['cagr']:+.1%} vs {b['cagr']:+.1%} | in {x['in_market']:.0%} trades {x['trades']} "
                  f"win {x['win_rate']:.0%} payoff {x['payoff']:.2f} | effective {x['effective']}", flush=True)
    out = {'span': SPANS[mode], 'results': res}
    lift = {r: float(np.median([x['strategy']['sharpe'] - x['buy_hold']['sharpe'] for x in per.values()]))
            for r, per in res.items()}
    out['median_sharpe_lift'] = lift
    if mode == 'dev':
        eff = {r: sum(x['effective'] for x in per.values()) for r, per in res.items()}
        n = {r: len(per) for r, per in res.items()}
        ok = [r for r in RULES if eff[r] * 2 > n[r]]
        out['effective'] = eff
        out['winner'] = max(ok, key=lambda r: (eff[r], lift[r])) if ok else None
        print('effective', eff, 'lift', lift, 'winner:', out['winner'])
    else:
        per = res[rules[0]]
        out['effective'] = sum(x['effective'] for x in per.values())
        out['verdict'] = bool(out['effective'] >= 4 and lift[rules[0]] > 0)
        print('effective', out['effective'], 'of', len(per), 'lift', lift, 'verdict:', out['verdict'])
    (REPORTS / f'tf9_{mode}.json').write_text(json.dumps(out, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
