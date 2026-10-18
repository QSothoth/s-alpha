"""How far is the daily approximation of his EP entry from the real thing?  On the 5-minute sample
(data/martin-luk-cache/k5.npz, 87 names from 2023-05), every gap-up >= 10% day of a pool name is entered two ways:

  daily     the study's 'level' entry: fill at the open, stop at the day's final low, never stopped that day
  minutes   his rule: buy the first break of the first 5-minute bar's high, stop at the low of day so far;
            stopped the same day if a later bar trades through it

Both are then held with the same daily rule (out at the stop, else at the close 10 sessions later) so only the
entry differs.  Reported per trade and on average (R multiples and returns).

    nice -n 19 /opt/futu-opend/venv/bin/python -m studies.christian_flanders.checks.ep_minutes
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from studies.trader_replication import panels

ROOT = Path(__file__).resolve().parents[3]
HOLD = 10


def hold(A, d, j, fill, stop):
    """Daily management after the entry day: stop (gap -> open) or the close HOLD sessions later."""
    o, l, c = A['open'][:, j], A['low'][:, j], A['close'][:, j]
    for k in range(d + 1, min(d + 1 + HOLD, len(c))):
        if not np.isfinite(o[k]):
            continue
        if o[k] <= stop:
            return o[k]
        if l[k] <= stop:
            return stop
    k = min(d + HOLD, len(c) - 1)
    return c[k]


def main():
    A = panels.arrays('us')
    z = np.load(ROOT / 'data' / 'martin-luk-cache' / 'k5.npz', allow_pickle=False)
    days5, syms, arr = z['days'], z['syms'], z['arr']
    di = {str(d): i for i, d in enumerate(A['days'])}
    col = {str(c): j for j, c in enumerate(A['codes'])}
    F = A['F']
    rows = []
    for s, sym in enumerate(syms):
        j = col.get('US.' + str(sym))
        if j is None:
            continue
        for k5, day in enumerate(days5):
            d = di.get(str(day))
            if d is None or d == 0:
                continue
            pc, o = F.c[d - 1, j], F.o[d, j]
            if not (np.isfinite(pc) and np.isfinite(o)) or o / pc - 1 < .10:
                continue
            if not (F.to20[d - 1, j] >= 5e6 and F.raw[d - 1, j] >= 2):
                continue
            O, H, L, C = (arr[i, s, k5] for i in range(4))
            ok = np.isfinite(O)
            if ok.sum() < 10:
                continue
            k = A['close'][d, j] / C[ok][-1]                     # 5-minute prices -> the adjusted daily basis
            O, H, L, C = O * k, H * k, L * k, C * k
            # daily approximation
            fill_d, stop_d = o, min(F.l[d, j], o * .99)
            out_d = hold(A, d, j, fill_d, stop_d)
            close_d = F.c[d, j]
            out_p = stop_d if close_d < fill_d else out_d          # the pessimistic daily bound (level_pess)
            stop_c = min(F.l[d, j], close_d * .99)                  # buy the close, stop at the day's low (exact)
            out_c = hold(A, d, j, close_d, stop_c)
            held = bool(close_d >= o)
            # 5-minute opening-range high
            first = np.flatnonzero(ok)[0]
            orh, entry = H[first], None
            for b in range(first + 1, len(H)):
                if ok[b] and H[b] > orh:
                    entry = b
                    break
            if entry is None:
                continue
            fill_m = max(orh, O[entry])
            stop_m = min(np.nanmin(L[:entry + 1]), fill_m * .99)
            later = L[entry + 1:][np.isfinite(L[entry + 1:])]
            stopped = bool(len(later) and later.min() <= stop_m)
            out_m = stop_m if stopped else hold(A, d, j, fill_m, stop_m)
            rows.append(dict(sym=str(sym), day=str(day), gap=float(o / pc - 1),
                             daily_r=float((out_d - fill_d) / (fill_d - stop_d)), daily_ret=float(out_d / fill_d - 1),
                             daily_stop_pct=float(1 - stop_d / fill_d),
                             close_ret=float(out_c / close_d - 1), held=held,
                             pess_ret=float(out_p / fill_d - 1), pess_r=float((out_p - fill_d) / (fill_d - stop_d)),
                             min_r=float((out_m - fill_m) / (fill_m - stop_m)), min_ret=float(out_m / fill_m - 1),
                             min_stop_pct=float(1 - stop_m / fill_m), stopped_day0=stopped))
    n = len(rows)
    summ = dict(n=n, day0_stopped=float(np.mean([r['stopped_day0'] for r in rows])) if n else None,
                **{f'{k}_mean': float(np.mean([r[k] for r in rows])) for k in
                   ('daily_r', 'min_r', 'pess_r', 'daily_ret', 'min_ret', 'pess_ret', 'close_ret', 'daily_stop_pct', 'min_stop_pct')} if n else {},
                **{f'{k}_median': float(np.median([r[k] for r in rows])) for k in ('daily_r', 'min_r')} if n else {})
    hr = [r for r in rows if r['held']]
    summ['held_only'] = dict(n=len(hr), **{k: float(np.mean([r[k] for r in hr])) for k in
                                           ('daily_ret', 'min_ret', 'close_ret')}) if hr else {}
    print(json.dumps(summ, indent=1))
    out = ROOT / 'studies' / 'christian_flanders' / 'reports' / 'ep_minutes.json'
    out.write_text(json.dumps(dict(summary=summ, rows=rows), indent=1))


if __name__ == '__main__':
    main()
