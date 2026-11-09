"""A capital-flow book: no slots.  Every signal starts as a small probe, one formula sets each holding's weight from how
the market has treated it, and when the budget runs out money moves from the weak holdings to the strong ones.  Daily
bars only; every decision reads the close it trades at or earlier.

    $PY -m studies.trader_replication.flow cache            # /tmp/flow_cache.npz from the registered Flanders build
    $PY -m studies.trader_replication.flow <round>          # reports/gap_review/flow_<round>.json
"""
from __future__ import annotations

import math
import os
import pickle
import sys
from dataclasses import dataclass

import numpy as np

WHO = os.environ.get('FLOW_ID', 'christian_flanders')
_P = os.environ.get('FLOW_PICK', '')
CACHE = f'/tmp/flow_cache_{WHO}{_P}.pkl' if WHO != 'christian_flanders' or _P else '/tmp/flow_cache.pkl'
TODAY = f'/tmp/flow_today_{WHO}{_P}.npy' if WHO != 'christian_flanders' or _P else '/tmp/flow_today.npy'
HIS = {'christian_flanders': {'2024': 4.335, '2025': 1.675}, 'martin_luk': {'2024': 2.83, '2025': 9.698}, 'clement_ang': {'2024': .793, '2025': 1.404}}[WHO]
COST = .0005
MARGIN = .07 / 252


@dataclass(frozen=True)
class Flow:
    risk: float = .0025         # equity lost at the first stop on a probe
    a: float = .3               # weight grows by exp(a * R) in profit
    b: float = .3               # and shrinks by exp(b * R) below cost
    rmax: float = 8.0           # evidence stops counting here
    cap: float = .5             # of equity, per name
    budget: float = 2.0         # total weight
    tilt: float = 1.0           # > 1: over budget, weights ** tilt before scaling, so the strong keep more
    k: float = 3.0              # trail: highest close since entry less k daily ranges
    k_grow: float = 0.0         # the trail widens by this many ranges per R of evidence, up to k_max
    k_max: float = 6.0
    band: float = .25           # a weight is only traded once it is this far from target
    tighten: int = 0            # > 0: an unproven stop climbs to the fill over this many sessions
    arm: float = 1.0            # the trail starts at this many R
    memory: float = 0.0         # > 0: a name that paid lately gets a bigger probe: exp(memory * its recent R), floor at -1
    memory_days: int = 60
    breadth: float = 0.0        # > 0: the budget runs from (1 - breadth) to full with the share of the pool above its 21-day mean
    ep_top: int = 0             # > 0: a gap name must rank this high by the day's own dollar turnover (known at the close it is bought)
    lead: float = 0.0           # share of the breadth reading taken from the evening list instead of the whole pool
    conv: float = 0.0           # > 0: the probe grows by exp(conv * (1 - best rank / conv_n)) with its place on the evening or the day's money list
    conv_n: int = 50
    bp: float = 1.0             # the breadth reading is raised to this power before it sets the budget
    brake: float = 0.0          # > 0: budget x max(.25, 1 - account drawdown / brake)
    vol: float = 0.0            # > 0: budget x min(1, vol / the book's annualised 20-day volatility)
    k_read: float = 0.0         # > 0: the trail narrows to k x (1 - k_read x (1 - reading))
    probe_read: float = 0.0     # > 0: probe risk x (1 - probe_read x (1 - reading))
    new_day: int = 0            # > 0: at most this many new probes a day
    fb: float = 0.0             # > 0: probe risk moves with the book's feedback, exp(fb * mean R of the last fb_n closed)
    fb_n: int = 30
    fb_lo: float = .25
    fb_hi: float = 2.0


def run(D, cfg, entries=None, seed=None):
    o, h, l, c, rng, ema = D['open'], D['high'], D['low'], D['close'], D['range'], D['ema21']
    days = D['days']
    start, end = D['window']
    idx = np.flatnonzero((days >= start) & (days <= end))
    entries = D['entries'] if entries is None else entries
    r = np.random.default_rng(seed) if seed is not None else None
    cash, pos, closed, curve = 1.0, {}, [], []

    def equity(d):
        return cash + sum(q['sh'] * (c[d, j] if np.isfinite(c[d, j]) else q['last']) for j, q in pos.items())

    def close_out(j, price, d):
        nonlocal cash
        q = pos.pop(j)
        cash += q['sh'] * price * (1 - COST)
        pnl = q['cash'] + q['sh'] * price * (1 - COST)
        closed.append(dict(j=j, entry=str(days[q['d0']]), exit=str(days[d]), days=d - q['d0'], pnl=pnl, pnl_eq=pnl / q['eq0'],
                           ret=pnl / q['peak_cost'], r=pnl / (q['eq0'] * cfg.risk)))

    for d in idx:
        for j in list(pos):                      # stops work during the day; a gap fills at the open
            q = pos[j]
            if not np.isfinite(l[d, j]):
                continue
            q['last'] = c[d, j]
            if l[d, j] <= q['stop']:
                close_out(j, min(o[d, j], q['stop']), d)
        eq = equity(d)
        if cash < eq:
            cash -= (eq - cash) * 0 + max(0.0, -cash) * MARGIN
        for j in list(pos):                      # the evening's evidence moves the line
            q = pos[j]
            if not np.isfinite(c[d, j]):
                continue
            q['hi'] = max(q['hi'], c[d, j])
            R = (c[d, j] - q['fill']) / q['r0']
            q['R'] = R
            k = min(cfg.k_max, cfg.k + cfg.k_grow * max(0.0, R))
            if cfg.k_read:
                k *= 1 - cfg.k_read * (1 - ((1 - cfg.lead) * D['breadth'][d - 1] + cfg.lead * D['lead_breadth'][d - 1]))
            if np.isfinite(rng[d, j]) and (R >= cfg.arm or q['armed']):
                q['armed'] = True
                q['stop'] = max(q['stop'], q['hi'] - k * rng[d, j])
            elif cfg.tighten:
                q['stop'] = max(q['stop'], q['fill'] - q['r0'] * max(0.0, 1 - (d - q['d0']) / cfg.tighten))
            if c[d, j] <= q['stop']:
                close_out(j, c[d, j], d)
        eq = equity(d)
        lst = sorted(entries[d], key=lambda e: e[0]) if len(entries[d]) else []
        if cfg.ep_top:
            lst = [e for e in lst if e[4] != 'ep' or D['today'][d, e[1]] < cfg.ep_top]
        if cfg.new_day:
            lst = lst[:cfg.new_day]
        for e in lst:
            j, fill, stop = e[1], e[2], e[3]
            if r is not None:                    # the placebo: the same day and stop width on a random name of the pool
                cand = np.flatnonzero(D['pool'][d] & np.isfinite(c[d]))
                if not len(cand):
                    continue
                pct = 1 - stop / fill
                j = int(r.choice(cand))
                fill, stop = float(c[d, j]), float(c[d, j]) * (1 - pct)
            if j in pos or not (0 < fill - stop < fill):
                continue
            mult = 1.0
            if cfg.fb and closed:
                recent = np.mean(np.clip([t['r'] for t in closed[-cfg.fb_n:]], -2, 5))
                mult = min(cfg.fb_hi, max(cfg.fb_lo, math.exp(cfg.fb * recent)))
            if cfg.probe_read:
                mult *= 1 - cfg.probe_read * (1 - ((1 - cfg.lead) * D['breadth'][d - 1] + cfg.lead * D['lead_breadth'][d - 1]))
            if cfg.memory:
                seen = sum(t['r'] for t in reversed(closed[-400:]) if t['j'] == j and d - D['index'][t['exit']] <= cfg.memory_days)
                mult *= math.exp(cfg.memory * max(-1.0, min(seen, 8.0)))
            if cfg.conv and r is None:
                best = min(int(D['rank'][d, j]), int(D['today'][d, j]))
                mult *= math.exp(cfg.conv * max(0.0, 1 - best / cfg.conv_n))
            w0 = min(cfg.risk * mult * fill / (fill - stop), cfg.cap)
            pos[j] = dict(sh=0.0, fill=fill, stop=stop, r0=fill - stop, hi=fill, d0=d, w0=w0, R=0.0, cash=0.0, eq0=eq, peak_cost=1e-12, last=fill, new=True, armed=False)
        t = {}
        for j, q in pos.items():
            x = max(-1.0, min(cfg.rmax, q['R']))
            t[j] = min(cfg.cap, q['w0'] * math.exp((cfg.a if x > 0 else cfg.b) * x))
        total = sum(t.values())
        reading = (1 - cfg.lead) * D['breadth'][d - 1] + cfg.lead * D['lead_breadth'][d - 1]
        budget = cfg.budget * (1 - cfg.breadth * (1 - reading ** cfg.bp)) if cfg.breadth else cfg.budget
        if cfg.brake and curve:
            budget *= max(.25, 1 - (1 - curve[-1] / max(curve)) / cfg.brake)
        if cfg.vol and len(curve) > 21:
            rv = float(np.std(np.diff(np.log(curve[-21:])))) * 252 ** .5
            budget *= min(1.0, cfg.vol / max(rv, 1e-9))
        if total > budget and total > 0:
            p = {j: v ** cfg.tilt for j, v in t.items()}
            s = budget / sum(p.values())
            t = {j: min(cfg.cap, v * s) for j, v in p.items()}
        for j, w in t.items():
            q = pos[j]
            px = c[d, j]
            if not np.isfinite(px) or px <= 0:
                continue
            now = q['sh'] * px / eq
            if q['new'] or abs(w - now) > cfg.band * max(now, 1e-9):
                dv = (w - now) * eq
                cost = abs(dv) * COST
                cash -= dv + cost
                q['cash'] -= dv + cost
                q['sh'] += dv / px
                q['new'] = False
                q['peak_cost'] = max(q['peak_cost'], -q['cash'])
        for j in [j for j, q in pos.items() if q['sh'] <= 0]:
            pos.pop(j)
        curve.append(equity(d))
    last = idx[-1]
    for j in list(pos):
        close_out(j, c[last, j] if np.isfinite(c[last, j]) else pos[j]['last'], last)
    return np.array(curve), closed


def report(D, cfg, name, placebo=0):
    curve, tr = run(D, cfg)
    days = D['days'][(D['days'] >= D['window'][0]) & (D['days'] <= D['window'][1])]
    years, prev = {}, 1.0
    for y in ('2024', '2025', '2026'):
        m = [i for i, x in enumerate(days) if str(x)[:4] == y]
        years[y] = float(curve[m[-1]] / prev - 1)
        prev = curve[m[-1]]
    peak = np.maximum.accumulate(np.r_[1.0, curve])
    dd = float(1 - (np.r_[1.0, curve] / peak).min())
    ret = np.array([t['ret'] for t in tr])
    win = ret > 0
    span = len(days) / 252
    o = {(t['j'], t['entry']) for t in tr}
    got = [i for i, (j, a, z) in D['tickets'].items() if any((j, str(D['days'][x])) in o for x in range(a, z + 1))]
    bj = sorted(tr, key=lambda t: -t['pnl_eq'])[:5]
    gain = sum(t['pnl_eq'] for t in tr if t['pnl_eq'] > 0)
    out = dict(years=years, total=float(curve[-1] - 1), maxdd=dd, per_year=len(tr) / span, win=float(win.mean()), avg_win=float(ret[win].mean()), avg_loss=float(ret[~win].mean()),
               days_win=float(np.mean([t['days'] for t, w in zip(tr, win) if w])), bought=len(got), gap=float(np.mean([abs(math.log(max(1 + years[k], 1e-6) / (1 + v))) for k, v in HIS.items()])),
               top5=float(sum(t['pnl_eq'] for t in bj) / gain), top=[(str(D['codes'][t['j']]), t['entry'], round(t['pnl_eq'], 2)) for t in bj[:3]])
    if placebo:
        p = [float(run(D, cfg, seed=i)[0][-1] - 1) for i in range(placebo)]
        out['placebo_median'], out['rank'] = float(np.median(p)), float(np.mean(np.array(p) < out['total']))
    print(f"{name:7}", {k: round(v, 2) for k, v in years.items()}, f"tot {out['total']:+.2f} dd {dd:.2f} n/y {out['per_year']:.0f} win {out['win']:.3f} aw {out['avg_win']:+.3f} al {out['avg_loss']:+.3f} dw {out['days_win']:.0f} bought {out['bought']} gap {out['gap']:.3f} top5 {out['top5']:.2f}",
          out.get('rank', ''), out['top'][:2], flush=True)
    return out


def cache():
    from . import panels, systems as SY, ticket_flanders as F, ticket_t4 as T4, watchlist as WL
    W, cfg = SY.get(WHO).load()
    base = getattr(W, 'base', W)
    A = base.arrays('us')
    e, rules, mask, pool = W.build(A, {**cfg, **F.ALL} if WHO == 'christian_flanders' else {**cfg, 'max_new': 0})
    rk = T4.ranks(A, pool)
    pick = int(os.environ.get('FLOW_PICK', 0))
    if pick:
        from .pick_map import pick_rank
        rk0, rk = rk, pick_rank(A, rk, WHO)
        kept = F.keep(e, rk, pick, True)
    else:
        kept = F.keep(e, rk, 50, True)
    ent = []
    for d, lst in enumerate(kept):
        row = []
        for x in lst:
            if x[2] > 0:
                row.append((-2e7 if x[5] == 'ep' else float(rk[d, x[1]] - 10 ** 7), x[1], float(x[3]), float(x[4]), str(x[5])))
        ent.append(row)
    hi, lo, cl = (A[k].astype(np.float32) for k in ('high', 'low', 'close'))
    rng = WL.roll_mean((hi - lo).astype(float), 20).astype(np.float32)
    ema = WL.roll_mean(cl.astype(float), 21).astype(np.float32)
    his = [x for x in base.located(A, base.trades()) if '2024-01-02' <= x[0].entry_date <= '2025-12-31' and x[0].side == 'long']
    D = dict(open=A['open'].astype(np.float32), high=hi, low=lo, close=cl, range=rng, ema21=ema, days=A['days'].astype(str), codes=A['codes'].astype(str), pool=pool if getattr(pool, 'shape', None) == cl.shape else np.isfinite(cl),
             entries=ent, rank=rk.astype(np.int32), window=panels.WINDOW, tickets={t.id: (j, a, z) for t, j, a, z in his})
    pickle.dump(D, open(CACHE, 'wb'), protocol=4)
    to = np.where(D['pool'], A['turnover'].astype(float), -1.0)
    np.save(TODAY, np.argsort(np.argsort(-to, axis=1), axis=1).astype(np.int32))
    print('cached', cl.shape, sum(map(len, ent)), flush=True)


ROUNDS = {}


def main(name):
    from . import review as RV
    D = pickle.load(open(CACHE, 'rb'))
    D['index'] = {str(x): i for i, x in enumerate(D['days'])}
    with np.errstate(all='ignore'):
        up = np.where(D['pool'], D['close'] > D['ema21'], np.nan)
    D['breadth'] = np.nan_to_num(np.nanmean(up, axis=1), nan=.5)
    D['today'] = np.load(TODAY, mmap_mode='r')
    with np.errstate(all='ignore'):
        top = np.where(D['rank'] < 50, D['close'] > D['ema21'], np.nan)
    D['lead_breadth'] = np.nan_to_num(np.nanmean(top, axis=1), nan=.5)
    out = {}
    for k, c in ROUNDS[name].items():
        out[k] = report(D, c, k)
        RV.write(f'flow_{name}.json', out)


ROUNDS['F1'] = dict(base=Flow(), a2=Flow(a=.2), a5=Flow(a=.5), kg=Flow(k_grow=.5), tilt=Flow(tilt=1.5), r5=Flow(risk=.005))

ROUNDS['F2'] = dict(n2=Flow(a=.2, new_day=2), n3=Flow(a=.2, new_day=3), n2f=Flow(a=.2, new_day=2, fb=1.0, risk=.005), n3b=Flow(a=.2, b=1.0, new_day=3), n3f=Flow(a=.2, new_day=3, fb=1.0, risk=.005))

_b = dict(a=.2)
ROUNDS['F3'] = dict(t5=Flow(tighten=5, **_b), t10=Flow(tighten=10, **_b), t20=Flow(tighten=20, **_b), t5k4=Flow(tighten=5, k=4.0, **_b), t10k2=Flow(tighten=10, k=2.0, **_b), t10a=Flow(tighten=10, arm=.5, **_b))

_c = dict(a=.2, tighten=5, k=4.0)
ROUNDS['F4'] = dict(base=Flow(**_c), m3=Flow(memory=.3, **_c), m5=Flow(memory=.5, **_c), br=Flow(breadth=1.0, **_c), m3br=Flow(memory=.3, breadth=1.0, **_c), m5br=Flow(memory=.5, breadth=1.0, **_c))

_d = dict(a=.2, tighten=5, k=4.0, memory=.5, breadth=1.0)
ROUNDS['F5'] = dict(b3=Flow(budget=3.0, **_d), b4=Flow(budget=4.0, **_d), r5b3=Flow(budget=3.0, risk=.005, **_d), r5b3t=Flow(budget=3.0, risk=.005, tilt=1.5, **_d),
                    b3a3=Flow(budget=3.0, **{**_d, 'a': .3}))

_e = dict(a=.2, tighten=5, k=4.0, memory=.5, breadth=1.0, risk=.005)
ROUNDS['F6'] = dict(e30=Flow(budget=3.0, ep_top=30, **_e), e50=Flow(budget=3.0, ep_top=50, **_e), e100=Flow(budget=3.0, ep_top=100, **_e), e50b4=Flow(budget=4.0, ep_top=50, **_e),
                    e30b4=Flow(budget=4.0, ep_top=30, **_e))

_f = {**_e, 'budget': 3.0}
ROUNDS['F7'] = dict(e200=Flow(ep_top=200, **_f), e300=Flow(ep_top=300, **_f), e200k3=Flow(ep_top=200, **{**_f, 'k': 3.0}), e300k3=Flow(ep_top=300, **{**_f, 'k': 3.0}),
                    e200m1=Flow(ep_top=200, **{**_f, 'memory': 1.0}))

_g = {**_e, 'ep_top': 300}
ROUNDS['F8'] = dict(b4=Flow(budget=4.0, **_g), b5=Flow(budget=5.0, **_g), b4m1=Flow(budget=4.0, **{**_g, 'memory': 1.0}), b4a3=Flow(budget=4.0, **{**_g, 'a': .3}),
                    b4r75=Flow(budget=4.0, **{**_g, 'risk': .0075}))

_h = {**_g, 'budget': 4.0}
ROUNDS['F9'] = dict(lead1=Flow(lead=1.0, **_h), lead5=Flow(lead=.5, **_h), br7=Flow(**{**_h, 'breadth': .7}), lead1b3=Flow(lead=1.0, **{**_h, 'budget': 3.0}), lead1br7=Flow(lead=1.0, **{**_h, 'breadth': .7}))

_i = {**_h, 'lead': 1.0}
ROUNDS['F10'] = dict(c1=Flow(conv=1.0, **_i), c2=Flow(conv=2.0, **_i), c2n20=Flow(conv=2.0, conv_n=20, **_i), c3=Flow(conv=3.0, **_i), c2b3=Flow(conv=2.0, **{**_i, 'budget': 3.0}))

_j = {**_i, 'conv': 2.0, 'conv_n': 20}
ROUNDS['X1'] = dict(same=Flow(**_j))

_m = {**_j, 'budget': 2.8}
ROUNDS['X2'] = dict(k2=Flow(**{**_m, 'k': 2.0}), k2t3=Flow(**{**_m, 'k': 2.0, 'tighten': 3}), k15=Flow(**{**_m, 'k': 1.5, 'tighten': 3}), k2a5=Flow(**{**_m, 'k': 2.0, 'tighten': 3, 'arm': .5}),
                    k2r3=Flow(**{**_m, 'k': 2.0, 'tighten': 3, 'risk': .003}))

ROUNDS['D1'] = dict(bp2=Flow(bp=2.0, **_j), brake4=Flow(brake=.4, **_j), vol6=Flow(vol=.6, **_j), kr=Flow(k_read=.5, **_j), pr=Flow(probe_read=1.0, **_j))

ROUNDS['P1'] = dict(v4=Flow(vol=.4, **_j))
ROUNDS['D2'] = dict(v5=Flow(vol=.5, **_j), v4=Flow(vol=.4, **_j), v6k=Flow(vol=.6, k_read=.5, **_j), v5k=Flow(vol=.5, k_read=.5, **_j), v5b=Flow(vol=.5, bp=2.0, **_j))

if __name__ == '__main__':
    cache() if sys.argv[1] == 'cache' else main(sys.argv[1])
