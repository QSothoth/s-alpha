"""Why the registered systems trail what their traders published: where the account's money sits (weight on winners
against losers, the names he won on) and what buying the close costs against touching the prior-day high on his own
tickets (hourly bars settle the same-day order).  Diagnosis only, nothing here is chosen or carried.

    $PY -m studies.trader_replication.anatomy <id> ...        # reports/gap_review/anatomy_<id>.json
"""
from __future__ import annotations

import gc
import sys
from dataclasses import replace

import numpy as np

from studies import trader_data as TD

from . import panels, review as RV, systems as SY

WINDOW = panels.WINDOW
LO, HI = .01, .05                                # the stop band of the default his_entry


def _hourly():
    h = TD.load_hourly('us', mode='frozen')
    codes = {str(c): j for j, c in enumerate(h['codes'])}
    days = h['days'].astype(str)
    return h, codes, days


def touch_entry(A, d, j, code, H):
    """(tuple, facts) buying the first touch of the prior-day high: the open when it gaps above, stop at the prior-day
    low inside the 1%-5% band, known before the fill.  Hourly bars decide whether the stop went the same day; an hour
    holding both the touch and the stop counts as stopped.  None without hourly bars for that day."""
    h, codes, days = H
    k = codes.get(code)
    if k is None or d < 1:
        return None
    bars = np.flatnonzero(days == str(A['days'][d]))
    bars = bars[np.isfinite(h['high'][bars, k])]
    if not len(bars):
        return None
    c, o, ph, pl = A['close'][d, j], A['open'][d, j], A['high'][d - 1, j], A['low'][d - 1, j]
    if not all(np.isfinite([c, o, ph, pl])) or c <= 0:
        return None
    scale = c / h['close'][bars[-1], k]
    hi, lo = h['high'][bars, k] * scale, h['low'][bars, k] * scale
    hit = np.flatnonzero(hi >= ph)
    if not len(hit):
        return dict(touched=False)
    fill = max(o, ph)
    stop = min(max(pl, fill * (1 - HI)), fill * (1 - LO))
    stopped = bool((lo[hit[0]:] <= stop).any())
    e = (0.0, j, 1, float(fill), float(stop), 'his', float(stop) if stopped else None)
    return dict(touched=True, entry=e, stopped=stopped, fill=float(fill), stop=float(stop), close=float(c),
                low=float(A['low'][d, j]))


def side(tr):
    if not tr:
        return dict(n=0)
    ret = np.array([t['ret'] for t in tr], float)
    r = np.array([t['r'] for t in tr], float)
    w = ret > 0
    return dict(n=len(tr), win=float(w.mean()), avg_win=float(ret[w].mean()) if w.any() else None,
                avg_loss=float(ret[~w].mean()) if (~w).any() else None, mean_ret=float(ret.mean()),
                sum_r=float(r.sum()), sum_r_cut=float(np.clip(r, -1.5, 10).sum()),
                days_loss=float(np.mean([t['days'] for t, x in zip(tr, ret) if x <= 0])) if (~w).any() and 'days' in tr[0]
                else None)


def anatomy(id_, H):
    system = SY.get(id_)
    W, cfg = system.load()
    base = getattr(W, 'base', W)
    A = base.arrays('us')
    entries, rules, mask, pool = W.build(A, cfg)
    st, tr = base.run(A, entries, WINDOW, pool, rules, placebo=0, audit=True)
    curve = np.asarray(st.pop('_curve'))
    days = A['days'][(A['days'] >= WINDOW[0]) & (A['days'] <= WINDOW[1])]
    at = {str(d): float(curve[i]) for i, d in enumerate(days)}
    out = dict(id=id_, version=system.version, years={}, by_year=st['by_year'])
    lon = [t for t in tr if t['side'] > 0 and t['ret']]
    for y in ('2024', '2025', '2026'):
        t = [x for x in lon if x['entry'][:4] == y]
        ret = np.array([x['ret'] for x in t])
        wt = np.array([x['pnl'] / x['ret'] / at[x['entry']] for x in t])
        pnl = wt * ret
        top = np.argsort(-pnl)[:max(1, len(t) // 20)]
        names = {}
        for x, p in zip(t, pnl):
            names[x['code']] = names.get(x['code'], 0.0) + p
        s = sorted(names.values(), reverse=True)
        gain = sum(v for v in names.values() if v > 0)
        out['years'][y] = dict(n=len(t), w_win=float(wt[ret > 0].mean()), w_loss=float(wt[ret <= 0].mean()),
                               w_top5pct=float(wt[top].mean()), corr_w_ret=float(np.corrcoef(wt, np.clip(ret, -.2, 1))[0, 1]),
                               contrib=float(pnl.sum()), avg_w=float(wt.mean()), top1_share=float(s[0] / gain), top5_share=float(sum(s[:5]) / gain))
    # the names he says he won on, year by year
    led = base.trades()
    won = {}
    for t in led:
        if t.side == 'long' and t.outcome == 'win' and t.window_lo[:4] in ('2024', '2025', '2026'):
            won.setdefault(t.window_lo[:4], set()).add('US.' + t.ticker)
    out['his_winners'] = {}
    for y, names in won.items():
        ours = {}
        n = {}
        for x in lon:
            if x['entry'][:4] == y:
                c = x['code']
                ours[c] = ours.get(c, 0.0) + x['pnl'] / at[x['entry']]
                n[c] = n.get(c, 0) + 1
        hit = sorted(((c, round(ours[c], 3), n[c]) for c in names if c in ours), key=lambda v: -v[1])
        total = sum(ours.values())
        out['his_winners'][y] = dict(names=len(names), traded=len(hit), profitable=sum(v[1] > 0 for v in hit),
                                     contrib=float(sum(v[1] for v in hit)), total=float(total), top=hit[:6],
                                     missed=sorted(c[3:] for c in names if c not in ours)[:25])
    # his tickets: close against touch, same exits, every trade on its own
    alone = replace(rules, max_open=0, max_new_long=0, max_gross=1e9, max_position=1e9, feedback=0, risk_scale='', margin_rate=0.0)
    located = [x for x in base.located(A, led) if WINDOW[0] <= x[0].entry_date <= WINDOW[1] and x[0].side == 'long']
    di = {str(d): i for i, d in enumerate(A['days'])}
    close, touch, facts = [[] for _ in A['days']], [[] for _ in A['days']], []
    for t, j, a, b in located:
        d = di.get(t.entry_date)
        if d is None:
            continue
        f = touch_entry(A, d, j, str(A['codes'][j]), H)
        e = base.his_entry(A, d, j, cfg)
        if not f or e is None or not f['touched']:
            facts.append(dict(id=t.id, covered=bool(f), touched=False))
            continue
        close[d].append(e)
        te = f['entry']
        touch[d].append(te if te[6] is not None else te[:6])
        facts.append(dict(id=t.id, covered=True, touched=True, stopped=f['stopped'], stop_touch=1 - f['stop'] / f['fill'],
                          stop_close=1 - e[4] / e[3], chase=f['close'] / f['fill'] - 1, his_stop=t.stop_pct))
    _, a2 = base.run(A, close, WINDOW, pool, alone, placebo=0, audit=True)
    _, b2 = base.run(A, touch, WINDOW, pool, alone, placebo=0, audit=True)
    use = [f for f in facts if f['touched']]
    out['his_tickets'] = dict(located=len(located), no_hourly=sum(not f['covered'] for f in facts),
                              no_touch=sum(f['covered'] and not f['touched'] for f in facts), used=len(use),
                              same_day_stopped=sum(f['stopped'] for f in use),
                              chase_median=float(np.median([f['chase'] for f in use])) if use else None,
                              stop_close_median=float(np.median([f['stop_close'] for f in use])) if use else None,
                              stop_touch_median=float(np.median([f['stop_touch'] for f in use])) if use else None,
                              his_stop_median=float(np.median([f['his_stop'] for f in use if f['his_stop']])) if any(f['his_stop'] for f in use) else None,
                              close=side(a2), touch=side(b2))
    print(id_, {k: v for k, v in out.items() if k != 'version'}, flush=True)
    RV.write(f'anatomy_{id_}.json', out)
    del A
    gc.collect()


if __name__ == '__main__':
    H = _hourly()
    for x in sys.argv[1:]:
        anatomy(x, H)
