"""Continuation BN: describe short-horizon retries after earlier list exits."""
from collections import defaultdict
import hashlib
import json
from pathlib import Path

import numpy as np

from . import panels, system
from .martin_continue_a import required_fields
from .martin_continue_ap import group
from .martin_continue_bm import describe
from .martin_strong import Data
from .martin_strong_scan import HOLD, active, f1_rules, hold_sim, name_score, u1_entries


def classify(trades, day_index):
    history = defaultdict(list)
    result = []
    for t in sorted((t for t in trades if t['kind'] == 'list'), key=lambda t: (t['entry'], t['code'])):
        prior = [p for p in history[t['code']] if p['why'] != 'end' and p['entry'] < t['entry'] and p['exit'] <= t['entry']]
        if not prior:
            category = 'other'
        else:
            previous = max(prior, key=lambda p: (p['exit'], p['entry']))
            age = day_index[t['entry']] - day_index[previous['exit']]
            if age == 0:
                category = 'same_day_exit'
            elif age <= 5:
                category = 'after_loss' if previous['ret'] <= 0 else 'after_win'
            else:
                category = 'other'
        result.append((category, t))
        history[t['code']].append(t)
    return result


def main():
    root = Path(__file__).resolve().parents[2]
    prior = json.loads((root / 'studies/trader_replication/reports/gap_review/strong_continue_bh.json').read_text())
    D = Data()
    if D.A['digest'] != prior['dataset_digest']:
        raise ValueError('frozen dataset differs from BH')
    F = required_fields(D)
    M = active(D, F)
    score = name_score(D, F, M, HOLD['H3'])
    H = hold_sim(score, 12, 36)
    entries = u1_entries(D, F, H, score)
    del F, M, score, H
    rules = f1_rules(D, 6, (1, 3))
    px, ema = D.base.px(D.A), D.base.ema_inputs(D.A, D.pool, rules)
    curve, dates, trades = system.simulate(px, ema, rules, entries, *panels.WINDOW)
    years = system.stats(curve, dates, trades)['by_year']
    if any(abs(years[y] - prior['results']['U1']['metrics']['by_year'][y]) > 1e-10 for y in years):
        raise AssertionError('U1 account path differs from BH')
    classified = classify(trades, D.di)
    cats = ('after_loss', 'after_win', 'other', 'same_day_exit')
    by_year = {}
    for year in ('2024', '2025', '2026'):
        by_year[year] = {}
        for category in cats:
            rows = [t for cat, t in classified if cat == category and t['entry'].startswith(year)]
            closed = [t for t in rows if t['why'] != 'end']
            by_year[year][category] = {'initial_basis': group(rows), 'invested_basis': describe(closed, 'ret_invested'),
                                       'initial_ret_at_least_30pct': int(sum(t['ret'] >= .3 for t in closed))}
    windows = []
    for d, j, ticker, _, date in D.big:
        peak = d + 1 + int(np.nanargmax(D.h[d + 1:d + 21, j]))
        end = min(d + 10, peak - 1)
        code = str(D.A['codes'][j])
        covered = {cat: any(t['code'] == code and D.di[t['entry']] <= end and D.di[t['exit']] >= d
                            for c, t in classified if c == cat) for cat in cats}
        windows.append({'date': date, 'ticker': ticker, 'covered': covered})
    coverage = {year: {cat: sum(w['covered'][cat] for w in windows if year == 'all' or w['date'].startswith(year))
                       for cat in cats} for year in ('2024', '2025', '2026', 'all')}
    paths = ('studies/trader_replication/martin_continue_a.py', 'studies/trader_replication/martin_continue_ap.py',
             'studies/trader_replication/martin_continue_bm.py', 'studies/trader_replication/martin_continue_bn.py',
             'studies/trader_replication/martin_strong_scan.py', 'studies/trader_replication/system.py',
             'studies/martin_luk/notes/trades.csv')
    out = dict(dataset_digest=D.A['digest'], window=list(panels.WINDOW), by_entry_year=by_year, coverage=coverage,
               windows=windows, code_sha256={p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in paths})
    target = root / 'studies/trader_replication/reports/gap_review/strong_continue_bn.json'
    target.write_text(json.dumps(out, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'by_entry_year': by_year, 'coverage': coverage}, ensure_ascii=False, indent=2), flush=True)


if __name__ == '__main__':
    main()
