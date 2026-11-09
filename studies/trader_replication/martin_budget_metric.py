"""New coverage yardstick (user-approved 2026-11-04), read-only:
- each night pick at most K new names from the IE9 filtered pool, by rank; a name picked in the
  previous HOLD nights is treated as held and not picked again;
- his entry is covered if we picked it on any night from entry-4 to entry+2 (buy next day);
- compare with 30 same-budget random draws; report all 51 primary and all 81 entries;
- precision: share of our picks whose 60-day max high after next-day open is >= +30%, vs pool base rate.
"""
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path('/opt/opend-us-options/.claude/worktrees/gap-review')
sys.path.insert(0, str(ROOT))
from studies.trader_replication import martin_continue_ie23 as m  # noqa: E402

GAP = ROOT / 'studies/trader_replication/reports/gap_review'
HALVES = ('2024H1', '2024H2', '2025H1', '2025H2', '2026H1', '2026H2')
K, HOLD, WINDOW = 3, 10, range(-4, 3)

cal = json.load(open(GAP / 'ie5_work/prepared.json'))['days']
cpos = {x: i for i, x in enumerate(cal)}
d = m.Data(matrix=False)
days = sorted(d.slices)
half = {day: m.ie7.half(day) for day in days}

prices = {}
def winner(code, day):
    if code not in prices:
        z = np.load(GAP / f'ie5_work/stocks/{code}.npz')
        prices[code] = (z['o'], z['h'])
    o, h = prices[code]
    i = cpos[day] + 1
    if i >= len(cal) - 1 or not np.isfinite(o[i]) or o[i] <= 0:
        return None
    return np.nanmax(h[i:min(len(cal), i + 60)]) / o[i] - 1 >= .3

def picks(ranks):
    out, recent = {}, []
    for day in days:
        sl = d.slices[day]
        codes = d.codes[sl]
        held = set().union(*recent[-HOLD:]) if recent else set()
        order = np.argsort(ranks[sl], kind='stable')
        chosen = [codes[k] for k in order if codes[k] not in held][:K]
        out[day] = set(chosen)
        recent.append(set(chosen))
    return out

def first(x):
    return next(i for i, y in enumerate(cal) if y >= x)

def coverage(sel):
    res = {'primary': 0, 'all': 0, 'half': {h: [0, 0] for h in HALVES}}
    for e, h, p in zip(d.entries, d.entry_half, d.primary):
        i0 = first(e['entry_date'])
        hit = any(e['code'] in sel.get(cal[j], ()) for j in (i0 + w for w in WINDOW) if 0 <= j < len(cal))
        res['all'] += hit
        if p:
            res['primary'] += hit
            res['half'][h][0] += hit
            res['half'][h][1] += 1
    return res

def precision(sel):
    flags = [winner(c, day) for day, cs in sel.items() for c in cs]
    flags = [f for f in flags if f is not None]
    return float(np.mean(flags)), len(flags)

def held_out(prefix):
    r = np.full(d.n, 99999, np.int32)
    for h in HALVES:
        a = np.load(GAP / f'strong_continue_ie25_real_{h}_{prefix}_ranks.npy')
        for day in days:
            if half[day] == h:
                sl = d.slices[day]
                r[sl] = a[sl]
    return r

base = [winner(c, day) for day, sl in d.slices.items() for c in d.codes[sl]]
base = [f for f in base if f is not None]
print(f'K={K}/night new names, hold {HOLD} nights, window -4..+2; pool base rate of +30% winners {np.mean(base):.1%}')

rng = np.random.default_rng(2026110401)
rand = []
for _ in range(30):
    r = np.empty(d.n, np.int32)
    for sl in d.slices.values():
        r[sl] = rng.permutation(sl.stop - sl.start) + 1
    sel = picks(r)
    c = coverage(sel)
    rand.append((c['primary'], c['all'], precision(sel)[0], [c['half'][h][0] for h in HALVES]))
rp = np.array([x[0] for x in rand])
print(f'random x30: primary mean {rp.mean():.1f}/51 (range {rp.min()}-{rp.max()}), all {np.mean([x[1] for x in rand]):.1f}/81, '
      f'precision {np.mean([x[2] for x in rand]):.1%}, by half mean {np.round(np.mean([x[3] for x in rand], axis=0), 1).tolist()}')

for name, r in (('IE9', d.baseline_ranks), ('IE25-E', held_out('E')), ('IE25-A', held_out('A')),
                ('IE25-B', held_out('B')), ('IE25-AB', held_out('AB'))):
    sel = picks(r)
    c = coverage(sel)
    pr, n = precision(sel)
    beat = int((rp < c['primary']).sum())
    print(f'{name:8s} primary {c["primary"]}/51  all {c["all"]}/81  beats {beat}/30 random  precision {pr:.1%} (n={n})  '
          f'by half {[f"{a}/{b}" for a, b in c["half"].values()]}')
