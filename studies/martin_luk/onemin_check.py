"""Compare J4 (5-min touch) entry-day outcomes with a 1-minute reconstruction on names that have 1m data."""
import csv, numpy as np
from pathlib import Path
from studies.martin_luk import intraday as I
ROOT = Path('/opt/opend-us-options/data')
files = {f.stem: f for d in ('sv2-stock-raw/k1m', 'ux1-stock-raw/k1m') for f in (ROOT / d).glob('*.csv')}
P = I.prepare()
s, tr, cfg = I.evaluate(P, 'J4', 'full')
want = {}
for t in tr:
    if t['code'] in files and t['kind'] in ('bo', 'burst', 'ep') and t['entry'] <= '2026-08-14':
        want.setdefault(t['code'], []).append(t)
rows = []
for sym, ts in want.items():
    days = {t['entry'] for t in ts}
    bars = {}
    with open(files[sym]) as fh:
        rd = csv.reader(fh); next(rd)
        for tk, o, h, l, c, v in rd:
            if tk[:10] in days:
                bars.setdefault(tk[:10], []).append((tk[11:16], float(o), float(h), float(l), float(c)))
    for t in ts:
        b1 = bars.get(t['entry'])
        if not b1:
            continue
        trig_px = t['fill']
        # first 1m bar reaching the fill price at or after the 5m entry bar start
        start_min = 570 + 5 * t['bar']
        k = next((i for i, x in enumerate(b1) if int(x[0][:2]) * 60 + int(x[0][3:]) - 1 >= start_min and x[2] >= trig_px - 1e-9), None)
        if k is None:
            continue
        lod_at_entry = min([x[3] for x in b1[:k]] + [b1[k][1]])     # lows before + open of the entry minute
        stop5 = t['stop']
        after = b1[k + 1:]
        hit5 = any(x[3] <= stop5 for x in after)                   # 5m-model stop, checked with exact minutes
        rows.append(dict(sym=sym, day=t['entry'], fill=trig_px, stop5=stop5, lod1=lod_at_entry,
                         stop_tighter_1m=lod_at_entry > stop5 + 1e-9, hit_after_entry=hit5,
                         model_said_stop_day0=(t['why'] in ('stop', 'gap_stop') and t['exit'] == t['entry']), r=t['r']))
n = len(rows)
agree = sum(r['hit_after_entry'] == r['model_said_stop_day0'] for r in rows)
print('trades checked', n, '| 5m model and 1m path agree on same-day stop-out:', agree, f'({agree/n:.0%})')
miss = [r for r in rows if r['hit_after_entry'] and not r['model_said_stop_day0']]
extra = [r for r in rows if r['model_said_stop_day0'] and not r['hit_after_entry']]
print('1m shows a same-day stop the 5m model missed:', len(miss), 'sumR of those trades in model', round(sum(r['r'] for r in miss), 1))
print('5m model stopped but 1m shows no stop after entry:', len(extra))
print('LOD at the entry minute above the 5m stop (real stop would be tighter):', sum(r['stop_tighter_1m'] for r in rows))
