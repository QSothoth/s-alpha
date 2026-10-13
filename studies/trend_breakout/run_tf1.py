"""Run a TF round (notes/TF1_PREREG.md ... TF4_PREREG.md) on one split and write the report data.

    PY="env PYTHONUTF8=1 /opt/futu-opend/venv/bin/python"
    $PY -m studies.trend_breakout.run_tf1 train                       # all five candidates, every market
    $PY -m studies.trend_breakout.run_tf1 test --rule us=T1 --rule hk=T2 --rule cn=T3   # once, winners only
    $PY -m studies.trend_breakout.run_tf1 train --round tf2           # U1-U5
    $PY -m studies.trend_breakout.run_tf1 test --round tf5            # W4 frozen, once (notes/TF5_PREREG.md)

Writes reports/<round>_<split>.json (every number in the report), the trades to
data/trend-breakout-v1-results/<round>_<split>.json (not in git), and prints a summary.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np

from . import backtest, panel, signals

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / 'data' / 'trend-breakout-v1'
REPORTS = Path(__file__).resolve().parent / 'reports'
TRADES = ROOT / 'data' / 'trend-breakout-v1-results'
SEEDS = 100

MARKETS = {  # only market rules: costs per side, liquidity floor, price limits, exclusions
    'us': {'cost': (0.0005, 0.0005), 'min_turnover': 50e6, 'min_price': 5.0},
    'hk': {'cost': (0.0016, 0.0016), 'min_turnover': 20e6, 'min_price': None},
    'cn': {'cost': (0.00076, 0.00126), 'min_turnover': 1e8, 'min_price': None},
}


def cn_limit(code):
    return 0.2 if code.startswith(('SH.688', 'SZ.300', 'SZ.301', 'SZ.302')) else 0.1


def is_st(name):
    """A-share risk-warning names: 'ST...' or '*ST...'."""
    return name.lstrip('*').upper().startswith('ST')


def load(market):
    p = panel.load(DATA / market)
    stocks = json.loads((DATA / market / 'universe.json').read_text(encoding='utf-8'))['stocks']
    names = {s['code']: s.get('name', '') for s in stocks}
    keep = np.array([not (market == 'cn' and is_st(names[c])) for c in p['codes']])  # prereg section 3
    for k, v in list(p.items()):
        if isinstance(v, np.ndarray) and v.ndim == 2:
            p[k] = v[:, keep]
    p['codes'] = p['codes'][keep]
    p['excluded'] = int((~keep).sum())
    return p


def summarize(tr, ew, dates):
    r = tr['r']
    n = len(r)
    if not n:
        return {'n': 0}
    win, loss = r[r > 0], r[r <= 0]
    months = np.array([dates[i][:7] for i in tr['entry']])
    quarters = np.array([m[:5] + 'Q%d' % ((int(m[5:]) - 1) // 3 + 1) for m in months])

    def share(values, labels):
        """Largest segment over the total (NaN when the total is not positive)."""
        segs = {k: float(values[labels == k].sum()) for k in sorted(set(labels))}
        return max(segs.values()) / values.sum() if values.sum() > 0 else math.nan, segs

    q_share, q_segs = share(r, quarters)
    m_share, m_segs = share(r, months)
    xr = (tr['ret'] - ew) * tr['buy'] / tr['risk']  # excess over the pool, in R (TF3 concentration)
    xq_share, xq_segs = share(xr, quarters)
    xm_share, xm_segs = share(xr, months)
    top = math.ceil(0.05 * n)
    rng = np.random.default_rng(0)
    uniq = sorted(set(months))
    by_month = [r[months == m] for m in uniq]
    boot = [np.concatenate([by_month[i] for i in rng.integers(0, len(uniq), len(uniq))]).mean()
            for _ in range(2000)]
    end = tr['at_end'].astype(bool)
    return {
        'n': n, 'mean_r': float(r.mean()), 'win_rate': float(len(win) / n),
        'payoff': float(win.mean() / -loss.mean()) if len(win) and len(loss) and loss.mean() < 0 else math.nan,
        'profit_factor': float(win.sum() / -loss.sum()) if loss.sum() < 0 else math.nan,
        'median_hold': float(np.median(tr['exit'] - tr['entry'])),
        'mean_ret': float(tr['ret'].mean()), 'mean_excess': float((tr['ret'] - ew).mean()),
        'mean_r_ex_top5': float(np.sort(r)[:n - top].mean()) if n > top else math.nan,
        'max_r': float(r.max()), 'min_r': float(r.min()),
        'quarter_max_share': q_share, 'month_max_share': m_share, 'quarters': q_segs, 'months': m_segs,
        'boot90': [float(np.percentile(boot, 5)), float(np.percentile(boot, 95))],
        'mean_xr': float(xr.mean()), 'xq_max_share': xq_share, 'xm_max_share': xm_share,
        'x_quarters': xq_segs, 'x_months': xm_segs,
        'open_at_end': int(end.sum()), 'mean_r_closed_only': float(r[~end].mean()) if (~end).any() else math.nan,
    }


def event_study(p, entry, eligible, lo, hi, horizons=(5, 10, 20)):
    """Descriptive: buy at T+1 open, hold h days to the close, minus the signal day's pool over the same window;
    every signal counts (no holding rule), and the whole window must lie inside rows lo..hi."""
    o, c = p['open'], p['close']
    out = {}
    rng = np.random.default_rng(0)
    for h in horizons:
        xs, months = [], []
        for t in range(max(lo - 1, 0), hi - h + 1):
            sig = entry[t] & eligible[t]
            if not sig.any():
                continue
            ret = c[t + h] / o[t + 1] - 1
            base = ret[eligible[t] & ~np.isnan(ret)]
            got = ret[sig & ~np.isnan(ret)]
            if len(got) and len(base):
                xs.extend(got - base.mean())
                months.extend([p['dates'][t + 1][:7]] * len(got))
        if not xs:
            out[h] = {'n': 0}
            continue
        xs, months = np.array(xs), np.array(months)
        uniq = sorted(set(months))
        by = [xs[months == m] for m in uniq]
        boot = [np.concatenate([by[i] for i in rng.integers(0, len(uniq), len(uniq))]).mean() for _ in range(2000)]
        out[h] = {'n': int(len(xs)), 'mean_excess': float(xs.mean()),
                  'boot90': [float(np.percentile(boot, 5)), float(np.percentile(boot, 95))]}
    return out


def run_rule(p, ind, rule, eligible, lo, hi, cfg, limit, controls=True):
    entry, line, ratchet = signals.evaluate(ind, rule, eligible)
    args = (line, ratchet)
    out = {}
    for universe, pool in (('daily', eligible), ('snapshot', ~np.isnan(p['close']))):
        entry_u = entry if universe == 'daily' else signals.evaluate(ind, rule, pool)[0]
        tr, skipped = backtest.run(p, entry_u, *args, pool, ind['atr22'], lo, hi, cfg['cost'], limit)
        out[universe] = summarize(tr, backtest.ew_benchmark(p, pool, tr), p['dates'])
        out[universe]['skipped'] = skipped
        if universe == 'daily':
            trades = {k: v.tolist() for k, v in tr.items()}
    out['event'] = event_study(p, entry, eligible, lo, hi)
    if controls:
        f_pool = eligible & signals.trend_filter(ind)
        for name, pool in (('R0', eligible), ('R0F', f_pool)):
            means = []
            for seed in range(SEEDS):
                rnd = backtest.random_entries(entry, eligible, pool, np.random.default_rng(seed))
                tr, _ = backtest.run(p, rnd, *args, eligible, ind['atr22'], lo, hi, cfg['cost'], limit)
                means.append(float(tr['r'].mean()) if len(tr['r']) else math.nan)
            out[name] = {'mean': float(np.nanmean(means)), 'p95': float(np.nanpercentile(means, 95)),
                         'runs': means}
    return out, trades


def gates(res, split, round_='tf1'):
    d = res['daily']
    if not d['n']:
        return {'n': False}
    if split == 'train' and round_ in ('tf3', 'tf4'):  # concentration on excess R (TF3_PREREG.md section 1)
        return {
            'n>=100': d['n'] >= 100, 'mean_r>0': d['mean_r'] > 0, 'beats_R0_p95': d['mean_r'] > res['R0']['p95'],
            'excess>0': d['mean_excess'] > 0, 'ex_top5>0': d['mean_r_ex_top5'] > 0,
            'x_quarter<=50%': d['xq_max_share'] <= 0.5, 'x_month<=50%': d['xm_max_share'] <= 0.5,
        }
    if split == 'train':
        return {
            'n>=100': d['n'] >= 100, 'mean_r>0': d['mean_r'] > 0, 'beats_R0_p95': d['mean_r'] > res['R0']['p95'],
            'excess>0': d['mean_excess'] > 0, 'ex_top5>0': d['mean_r_ex_top5'] > 0,
            'quarter<=50%': d['quarter_max_share'] <= 0.5, 'month<=50%': d['month_max_share'] <= 0.5,
        }
    if round_ == 'tf5':  # notes/TF5_PREREG.md section 3
        key = 20 if 20 in res['event'] else '20'  # int in memory, str after a JSON round trip
        ev, base = res['event'][key], res['v1_event'][key]
        return {'event20>0': ev.get('mean_excess', -1) > 0, 'event20_low>0': ev.get('boot90', [-1])[0] > 0,
                'beats_V1_event20': ev.get('mean_excess', -1) > base.get('mean_excess', math.inf),
                'n>=50': d['n'] >= 50, 'mean_r>0': d['mean_r'] > 0, 'excess>0': d['mean_excess'] > 0,
                'ex_top5>0': d['mean_r_ex_top5'] > 0}
    return {'n>=50': d['n'] >= 50, 'mean_r>0': d['mean_r'] > 0, 'beats_R0_mean': d['mean_r'] > res['R0']['mean'],
            'excess>0': d['mean_excess'] > 0, 'ex_top5>0': d['mean_r_ex_top5'] > 0}


def pick(results):
    passed = [(r, v['daily']['mean_r'], v['daily']['n']) for r, v in results.items() if all(v['gates'].values())]
    if not passed:
        return None
    best = max(m for _, m, _ in passed)
    close = [x for x in passed if best - x[1] <= 0.02]
    return max(close, key=lambda x: x[2])[0]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('split', choices=('train', 'test'))
    ap.add_argument('--round', default='tf1', choices=tuple(signals.ROUNDS))
    ap.add_argument('--markets', nargs='+', default=list(MARKETS))
    ap.add_argument('--rule', action='append', default=[], help='test only: market=rule, the registered winner')
    a = ap.parse_args()
    chosen = dict(x.split('=') for x in a.rule)
    if a.split == 'test' and a.round == 'tf5':
        chosen = {m: 'W4' for m in a.markets}
    if a.split == 'test' and (set(chosen) != set(a.markets) or
                              not set(chosen.values()) <= set(signals.ROUNDS[a.round])):
        raise SystemExit('test needs exactly one registered --rule of this round per market')
    np.seterr(invalid='ignore', divide='ignore')
    report = {'round': a.round, 'split': a.split, 'seeds': SEEDS, 'markets': {}}
    for market in a.markets:
        cfg = MARKETS[market]
        p = load(market)
        ind = signals.indicators(p)
        eligible = signals.liquid(p, cfg['min_turnover'], cfg['min_price'])
        rows = np.flatnonzero(panel.mask(p['dates'], a.split))
        lo, hi = int(rows[0]), int(rows[-1])
        limit = np.array([cn_limit(c) for c in p['codes']]) if market == 'cn' else None
        rules = [chosen[market]] if a.split == 'test' else list(signals.ROUNDS[a.round])
        results, trades = {}, {}
        for rule in rules:
            results[rule], trades[rule] = run_rule(p, ind, rule, eligible, lo, hi, cfg, limit)
            if a.round == 'tf5':  # the no-timing baseline for criterion 2
                v1 = signals.evaluate(ind, 'V1', eligible)[0]
                results[rule]['v1_event'] = event_study(p, v1, eligible, lo, hi)
            results[rule]['gates'] = gates(results[rule], a.split, a.round)
            d = results[rule]['daily']
            print(f"{market} {rule}: n={d['n']} R={d.get('mean_r', 0):+.3f} win={d.get('win_rate', 0):.1%} "
                  f"payoff={d.get('payoff', 0):.2f} R0p95={results[rule]['R0']['p95']:+.3f} "
                  f"gates={sum(results[rule]['gates'].values())}/{len(results[rule]['gates'])}", flush=True)
        report['markets'][market] = {
            'stocks': len(p['codes']), 'excluded_st': p['excluded'], 'span': [p['dates'][lo], p['dates'][hi]],
            'eligible_per_day': float(eligible[lo:hi + 1].sum(axis=1).mean()),
            'results': results, 'winner': pick(results) if a.split == 'train' else None,
            'trades': {r: {**t, 'code': [str(p['codes'][j]) for j in t['stock']],
                           'entry_date': [str(p['dates'][i]) for i in t['entry']],
                           'exit_date': [str(p['dates'][i]) for i in t['exit']]} for r, t in trades.items()},
        }
        print(market, 'winner:', report['markets'][market]['winner'], flush=True)
    name = '%s_%s%s.json' % (a.round, a.split, '' if a.markets == list(MARKETS) else '_' + '_'.join(a.markets))
    TRADES.mkdir(parents=True, exist_ok=True)  # every trade: local data, not in git
    (TRADES / name).write_text(json.dumps({m: v.pop('trades') for m, v in report['markets'].items()},
                                          ensure_ascii=False) + '\n', encoding='utf-8')
    REPORTS.mkdir(exist_ok=True)
    (REPORTS / name).write_text(json.dumps(report, ensure_ascii=False, indent=1, default=float) + '\n',
                                encoding='utf-8')


if __name__ == '__main__':
    main()
