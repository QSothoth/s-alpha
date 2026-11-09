"""Continuation BK: compare U1/BH holdings and previously blocked entries."""
from collections import Counter
from dataclasses import replace
import hashlib
import json
from pathlib import Path

from . import panels, system
from .martin_continue_a import required_fields
from .martin_strong import Data
from .martin_strong_scan import HOLD, active, f1_rules, hold_sim, name_score, u1_entries


def main():
    root = Path(__file__).resolve().parents[2]
    read = lambda name: json.loads((root / 'studies/trader_replication/reports/gap_review' / name).read_text())
    bh = read('strong_continue_bh.json')
    be = read('strong_continue_be.json')
    bf = read('strong_continue_bf.json')
    D = Data()
    if any(D.A['digest'] != x['dataset_digest'] for x in (bh, be, bf)):
        raise ValueError('frozen datasets differ')
    F = required_fields(D)
    M = active(D, F)
    score = name_score(D, F, M, HOLD['H3'])
    H = hold_sim(score, 12, 36)
    entries = u1_entries(D, F, H, score)
    del F, M, score, H
    rules = f1_rules(D, 6, (1, 3))
    px = D.base.px(D.A)
    trades = {}
    for name, ru in (('U1', rules), ('BH1', replace(rules, rotate_below=.02, rotate_min_days=3))):
        ema = D.base.ema_inputs(D.A, D.pool, ru)
        curve, dates, trades[name] = system.simulate(px, ema, ru, entries, *panels.WINDOW)
        years = system.stats(curve, dates, trades[name])['by_year']
        if any(abs(years[y] - bh['results'][name]['metrics']['by_year'][y]) > 1e-10 for y in years):
            raise AssertionError(f'{name} path differs from BH')
    locations = {(date, ticker): j for _, j, ticker, _, date in D.big}
    windows = []
    for w in be['windows']:
        code = str(D.A['codes'][locations[(w['date'], w['ticker'])]])
        first, last = D.di[w['date']], D.di[w['end']]
        held = {}
        for name, rows in trades.items():
            held[name] = any(t['code'] == code and t['side'] > 0 and D.di[t['entry']] <= last
                             and D.di[t['exit']] >= first for t in rows)
        category = 'both' if all(held.values()) else 'u1_only' if held['U1'] else 'bh_only' if held['BH1'] else 'neither'
        windows.append({'date': w['date'], 'ticker': w['ticker'], 'category': category})
    summary = {}
    for year in ('2024', '2025', '2026', 'all'):
        rows = [w for w in windows if year == 'all' or w['date'].startswith(year)]
        summary[year] = {'windows': len(rows), 'categories': dict(Counter(w['category'] for w in rows))}
    bh_entries = {(t['entry'], t['code']): t for t in trades['BH1'] if t['kind'] == 'list' and t['side'] > 0}
    matched = []
    for r in bf['records']:
        t = bh_entries.get((r['date'], r['code']))
        matched.append({'date': r['date'], 'code': r['code'], 'windows': r['windows'],
                        'opened': t is not None, 'open_at_end': t is not None and t['why'] == 'end'})
    covered = {tuple(w) for r in matched if r['opened'] for w in r['windows']}
    paths = ('studies/trader_replication/martin_continue_a.py', 'studies/trader_replication/martin_continue_bk.py',
             'studies/trader_replication/martin_strong_scan.py', 'studies/trader_replication/system.py')
    out = dict(dataset_digest=D.A['digest'], summary=summary, windows=windows, targets=matched,
               blocked_candidates=len(matched), bh_opened=sum(r['opened'] for r in matched),
               bh_open_at_end=sum(r['open_at_end'] for r in matched), bh_covered_windows=len(covered),
               code_sha256={p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in paths})
    target = root / 'studies/trader_replication/reports/gap_review/strong_continue_bk.json'
    target.write_text(json.dumps(out, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({k: out[k] for k in ('summary', 'blocked_candidates', 'bh_opened', 'bh_open_at_end', 'bh_covered_windows')}, ensure_ascii=False, indent=2), flush=True)


if __name__ == '__main__':
    main()
