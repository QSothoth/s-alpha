"""Continuation M: prior-close potent/leader scanner coverage of the existing ledger."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np

from . import panels, watchlist as WL
from .martin_continue_a import required_fields
from .martin_strong import Data
from .martin_strong_scan import HOLD, active, hold_sim, name_score


def main():
    D = Data()
    F = required_fields(D)
    M = active(D, F)
    score = name_score(D, F, M, HOLD['H3'])
    H = hold_sim(score, 12, 36)
    vol5 = WL.roll_mean(D.h / D.l - 1, 5)
    pot, lead = np.zeros(D.c.shape, bool), np.zeros(D.c.shape, bool)
    for d in range(2, len(D.c)):
        v = (D.U[d] & (np.nan_to_num(D.to20[d-1]) >= 5e7) & (np.nan_to_num(vol5[d-1]) >= .035))
        with np.errstate(all='ignore'):
            r = D.c[d-1] / D.c[d-2] - 1
        for signal, x, n, minimum in ((pot, r, 50, 60), (lead, F['g21'][d-1], 100, 120)):
            ix = np.flatnonzero(v & np.isfinite(x))
            if len(ix) > minimum:
                signal[d, ix[np.argsort(-x[ix])[:n]]] = True
    union = pot | lead
    reg = [{e[1] for e in row if e[2] > 0} for row in D.reg]
    rows = []
    for d, j, ticker, setup, day in D.his:
        # Match L's fully-observed 20-bar label; it is used only to group the diagnostic outcome.
        trace = D.h[d + 1:d + 21, j]
        known = len(trace) == 20 and np.isfinite(trace).all() and np.isfinite(D.c[d, j]) and D.c[d, j] > 0
        big = bool(np.max(trace) / D.c[d, j] - 1 >= .5) if known else None
        first = 'H3_miss' if D.U[d, j] and M[d, j] and not H[d, j] else 'H3_in' if H[d, j] else 'other'
        rows.append(dict(day=day, ticker=ticker, group=first, big=big, potent=bool(pot[d, j]),
                         leader=bool(lead[d, j]), union=bool(union[d, j]), reg_close=j in reg[d]))
    result = {}
    for year in ('2024', '2025', '2026'):
        dates = [i for i, day in enumerate(D.days) if day.startswith(year) and panels.WINDOW[0] <= day <= panels.WINDOW[1]]
        widths = {}
        for k, mat in (('potent', pot), ('leader', lead), ('union', union)):
            widths[k] = dict(median_count=float(np.median(mat[dates].sum(1))),
                             mean_share=float(np.mean(mat[dates].sum(1) / np.maximum(D.U[dates].sum(1), 1))))
        groups = {}
        for g in ('H3_miss', 'H3_in'):
            for subset in ('all', 'big'):
                sample = [r for r in rows if r['day'].startswith(year) and r['group'] == g and (subset == 'all' or r['big'] is True)]
                actual = {k: sum(r[k] for r in sample) for k in ('potent', 'leader', 'union', 'reg_close')}
                expected = {}
                for k, mat in (('potent', pot), ('leader', lead), ('union', union)):
                    expected[k] = float(sum(mat[D.di[r['day']]].sum() / max(1, D.U[D.di[r['day']]].sum()) for r in sample))
                groups[g + '_' + subset] = dict(n=len(sample), actual=actual, same_width_random_expected=expected)
        result[year] = dict(widths=widths, groups=groups)
    root = Path(__file__).resolve().parents[2]
    paths = ('studies/trader_replication/martin_continue_a.py', 'studies/trader_replication/martin_continue_m.py',
             'studies/trader_replication/martin_strong_scan.py', 'studies/martin_luk/notes/trades.csv')
    out = dict(dataset_digest=D.A['digest'], window=list(panels.WINDOW), years=result, rows=rows,
               code_sha256={p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in paths})
    target = root / 'studies/trader_replication/reports/gap_review/strong_continue_m.json'
    target.write_text(json.dumps(out, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({k: v for k, v in out.items() if k != 'rows'}, ensure_ascii=False, indent=2), flush=True)


if __name__ == '__main__':
    main()
