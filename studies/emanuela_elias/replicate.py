"""Emanuela Elias (The Trader Reset; USIC 2025 +259.9%, 2026 to September +190.3%) through skills/trader-replication:
a small list of liquid large caps, key levels, a failed break that is reclaimed ("buyers show up"), then a retest
of the level to define risk; calls or puts both ways, held a few sessions (notes/RULES_CN.md).

    PY="nice -n 19 env OPENBLAS_NUM_THREADS=1 PYTHONUTF8=1 /opt/futu-opend/venv/bin/python"
    $PY -m studies.emanuela_elias.replicate round R1
    $PY -m studies.emanuela_elias.replicate validate r1.json

Her public posts give the framework, not the numbers: the list size, the key level (here the 20-session low /
high), the reclaim window, the retest band and the exits are researcher values.  Stock signals are traded with
the shared engine; `options` replays the same trades with ~30-day at-the-money calls / puts priced on OpenD's IV
(studies/trader_options/pricing.py), her instrument.  No dated trades: fidelity is her years only.
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np

from studies.trader_replication import panels, study, system as Y
from studies.trader_screens import screens as S
from studies.trader_options.goal import GoalMixin

ROOT = Path(__file__).resolve().parents[2]
lag = S.lag

SELECT = ('2024-01-02', '2025-12-31')
VALIDATE = ('2026-01-02', '2026-10-16')
WINDOW = ('2024-01-02', '2026-10-16')

DRAFT = dict(
    top=15,                   # the list: the 15 names with the largest 20-day turnover (as of the day before)
    level=20,                 # key level: the low / high of the 20 sessions before the break
    reclaim=5,                # the reclaim (a close back above the broken low) within 5 sessions of the break
    band=.01,                 # the retest: a low within 1% above the level (or through it) and a close above it
    window=10,                # the retest within 10 sessions after the reclaim
    sides=['long', 'short'],
    target='hi20',            # out at the next key level: a close at / above the prior 20-session high (shorts: low)
    rule_opts=dict(risk=.02, max_position=.30, max_gross=1.5, max_open=6, trail='', trims=(), max_days=5,
                   short_max_days=5, borrow_rate=.03),
    max_new=3,
)


class Emanuela(GoalMixin, study.Study):
    id, name = 'emanuela_elias', 'Emanuela Elias'
    root = ROOT / 'studies' / 'emanuela_elias'
    ledger = None
    full = SELECT
    home = ('us',)
    his = {'2025': dict(ret=2.599)}
    his_behaviour = {}
    base = DRAFT
    periods = {'2024': ('2024-01-02', '2024-12-31', None), '2025': ('2025-01-02', '2025-12-31', 2.599),
               '2026-01..09 (used)': ('2026-01-02', '2026-09-30', 1.903)}
    goal_behaviour = {}
    starts = ('2024-01-02', '2024-02-01', '2024-03-01', '2024-04-01', '2024-07-01', '2025-01-02')

    def arrays(self, market, upto=None, mode=None):
        return panels.arrays(market, upto, mode)

    def ledger_sets(self, A):
        return [], []

    def listed(self, A, cfg):
        """The day's list (as of that close): the top-N names by 20-day turnover."""
        F = A['F']
        n = cfg.get('top', 15)

        def f():
            out = np.zeros(F.c.shape, bool)
            t = np.where(np.isfinite(F.to20) & (F.raw >= 5), F.to20, -1)
            for d in range(len(t)):
                k = np.argsort(-t[d])[:n]
                out[d, k[t[d, k] > 0]] = True
            return out
        return F.get(('top', n), f)

    def setups(self, A, cfg, side):
        """Day-t entries at the close: the level broken on some day b, reclaimed by a close back across it within
        `reclaim` sessions, then retested (the day's extreme within `band` of it or through it, the close back on
        the right side) within `window` sessions of the reclaim; the stop beyond the retest day's extreme."""
        F = A['F']
        n, rc, win, band = cfg['level'], cfg['reclaim'], cfg['window'], cfg['band']
        lst = lag(self.listed(A, cfg))
        c, h, l = F.c, F.h, F.l
        nd, nc = c.shape
        lvl_lo, lvl_hi = lag(F.lo(n)), lag(F.hi(n))                     # the prior n-session low / high
        m = np.zeros((nd, nc), bool)
        level_at = np.full((nd, nc), np.nan)
        # state per name: armed level and the session it was reclaimed
        armed = np.full(nc, np.nan)
        rec_day = np.full(nc, -10 ** 6)
        broke_lvl = np.full(nc, np.nan)
        broke_day = np.full(nc, -10 ** 6)
        for d in range(1, nd):
            with np.errstate(invalid='ignore'):
                if side > 0:
                    brk = l[d] < lvl_lo[d]                               # trades under the key low
                    newb = brk & ~(np.isfinite(broke_lvl) & (d - broke_day <= rc))
                    broke_lvl = np.where(newb, lvl_lo[d], broke_lvl)
                    broke_day = np.where(newb, d, broke_day)
                    recl = np.isfinite(broke_lvl) & (d - broke_day <= rc) & (c[d] > broke_lvl)
                    armed = np.where(recl, broke_lvl, armed)
                    rec_day = np.where(recl, d, rec_day)
                    broke_lvl = np.where(recl, np.nan, broke_lvl)
                    ok = (np.isfinite(armed) & (d - rec_day >= 1) & (d - rec_day <= win)
                          & (l[d] <= armed * (1 + band)) & (c[d] > armed))
                else:
                    brk = h[d] > lvl_hi[d]
                    newb = brk & ~(np.isfinite(broke_lvl) & (d - broke_day <= rc))
                    broke_lvl = np.where(newb, lvl_hi[d], broke_lvl)
                    broke_day = np.where(newb, d, broke_day)
                    recl = np.isfinite(broke_lvl) & (d - broke_day <= rc) & (c[d] < broke_lvl)
                    armed = np.where(recl, broke_lvl, armed)
                    rec_day = np.where(recl, d, rec_day)
                    broke_lvl = np.where(recl, np.nan, broke_lvl)
                    ok = (np.isfinite(armed) & (d - rec_day >= 1) & (d - rec_day <= win)
                          & (h[d] >= armed * (1 - band)) & (c[d] < armed))
                expired = np.isfinite(armed) & (d - rec_day > win)
                if cfg.get('at_reclaim'):                    # enter at the reclaim close itself ("buyers show up"),
                    ok = recl & (rec_day == d)               # not at a later retest
            ok &= lst[d]
            m[d] = ok
            level_at[d] = np.where(ok, armed, np.nan)
            armed = np.where(ok | expired, np.nan, armed)
        return m, level_at

    def retests(self, A, cfg, side):
        """Break and retest (her AAPL put, 2026-07-05): a close beyond the key level (longs: above the prior n-session
        high; shorts: below the low), then within `window` sessions a retest from the other side (the day's extreme
        within `band` of the level or through it) that closes back beyond it; entry at that close, the stop beyond the
        retest day's extreme."""
        F = A['F']
        n, win, band = cfg['level'], cfg['window'], cfg['band']
        lst = lag(self.listed(A, cfg))
        c, h, l = F.c, F.h, F.l
        nd, nc = c.shape
        lvl = lag(F.hi(n)) if side > 0 else lag(F.lo(n))
        m = np.zeros((nd, nc), bool)
        level_at = np.full((nd, nc), np.nan)
        armed = np.full(nc, np.nan)
        brk_day = np.full(nc, -10 ** 6)
        for d in range(1, nd):
            with np.errstate(invalid='ignore'):
                if side > 0:
                    ok = (np.isfinite(armed) & (d - brk_day >= 1) & (d - brk_day <= win)
                          & (l[d] <= armed * (1 + band)) & (c[d] > armed))
                    newb = c[d] > lvl[d]
                else:
                    ok = (np.isfinite(armed) & (d - brk_day >= 1) & (d - brk_day <= win)
                          & (h[d] >= armed * (1 - band)) & (c[d] < armed))
                    newb = c[d] < lvl[d]
                expired = np.isfinite(armed) & (d - brk_day > win)
            ok &= lst[d]
            m[d] = ok
            level_at[d] = np.where(ok, armed, np.nan)
            armed = np.where(ok | expired, np.nan, armed)
            fresh = newb & ~np.isfinite(armed)                    # a new break arms its own level
            armed = np.where(fresh, lvl[d], armed)
            brk_day = np.where(fresh, d, brk_day)
        return m, level_at

    def pool(self, A, cfg):
        return lag(self.listed(A, cfg))

    def weak(self, A, n):
        """Per day: the pool's equal-weight index (price >= 5, 20-day turnover >= 20M, as of the day before) closed
        under its n-day EMA the day before."""
        F = A['F']

        def f():
            prev = lag(F.c)
            with np.errstate(invalid='ignore', divide='ignore'):
                ok = lag((F.raw >= 5) & (F.to20 >= 20e6))
                r = np.where(ok & np.isfinite(prev) & np.isfinite(F.c), F.c / prev - 1, np.nan)
                idx = np.cumprod(1 + np.nan_to_num(np.nanmean(r, axis=1)))
            e = S.ema(idx[:, None], n)[:, 0]
            return lag((idx < e)[:, None])[:, 0]
        return F.get(('weak', n), f)

    def build(self, A, cfg, trace=None):
        F = A['F']
        c, h, l = F.c, F.h, F.l
        entries = [[] for _ in range(len(c))]
        mask = np.zeros(c.shape, bool)
        for side, nm in ((1, 'long'), (-1, 'short')):
            if nm not in cfg.get('sides', ['long', 'short']):
                continue
            mode = cfg.get('mode', 'reclaim')
            if mode == 'retest':
                m, lv = self.retests(A, cfg, side)
            elif mode == 'both':
                m, lv = self.setups(A, cfg, side)
                m2, lv2 = self.retests(A, cfg, side)
                lv = np.where(m, lv, lv2)
                m = m | m2
            else:
                m, lv = self.setups(A, cfg, side)
            if side < 0 and cfg.get('short_gate'):              # shorts only while the pool's index is under its
                m = m & self.weak(A, cfg['short_gate'])[:, None]  # n-day EMA (as of the prior close)
            if side > 0 and cfg.get('long_gate'):               # longs only while it is above (her AAPL put leaned
                m = m & ~self.weak(A, cfg['long_gate'])[:, None]  # on the market weakening at the same time)
            mask |= m
            for d, j in zip(*np.nonzero(m)):
                f = float(c[d, j])
                st = float(l[d, j]) * .999 if side > 0 else float(h[d, j]) * 1.001
                if cfg.get('stop_level'):                       # beyond the key level itself, not the retest bar
                    k = cfg['stop_level']
                    st = min(st, lv[d, j] * (1 - k)) if side > 0 else max(st, lv[d, j] * (1 + k))
                if side > 0:
                    st = min(st, f * .99)
                else:
                    st = max(st, f * 1.01)
                entries[d].append((-float(F.to20[d - 1, j]), int(j), side, f, st, 'kl' if side > 0 else 'ks'))
        ro = dict(cfg.get('rule_opts', {}))
        ro['trims'] = tuple(ro.get('trims', ()))
        tg = cfg.get('target', 'hi20')
        rules = Y.Rules(**ro, exit_signal=f'x_{tg}' if tg else '', short_exit_signal=f'xs_{tg}' if tg else '',
                        max_new_all=cfg.get('max_new', 3))
        A['kind_pools'] = None
        return entries, rules, mask, self.pool(A, cfg)

    def named(self, A, pool, name):
        F = A['F']
        with np.errstate(invalid='ignore'):
            if name.startswith('x_hi'):                 # a close at / above the prior n-session high
                return F.c >= lag(F.hi(int(name[4:])))
            if name.startswith('xs_hi'):                # shorts: a close at / below the prior n-session low
                return F.c <= lag(F.lo(int(name[5:])))
        raise KeyError(name)

    # ----- the option account (R3 on): her instrument, priced from the underlying and OpenD's daily IV -----
    def iv(self, A):
        from studies.trader_options import pricing as P
        if 'iv' not in A:
            A['iv'] = P.load_panel('iv', 'iv', A['days'], [str(x) for x in A['codes']], .01)
        return A['iv']

    def option_return(self, A, side, i0, i1, j, o, s1=None):
        """Return on premium of a call (side +1) / put (-1) bought at the close of session i0 and sold at the close
        of i1: `dte` calendar days to expiry, strike `mny` out of the money (fraction of the price), vol = the day's
        IV with the pricing module's skew, `spread` paid each way.  None when the IV or a price is missing."""
        from studies.trader_options import pricing as P
        F, iv, days = A['F'], self.iv(A), A['days']
        S0, S1, v0 = F.raw[i0, j], F.raw[i1, j], iv[i0, j]
        if s1 is not None and np.isfinite(s1):                # the stock's own exit price (a stop or target inside
            S1 = s1 * F.raw[i1, j] / F.c[i1, j]               # the day), in raw terms
        if not (np.isfinite(S0) and np.isfinite(S1) and np.isfinite(v0) and S0 > 0 and v0 > 0):
            return None
        v1 = iv[i1, j] if np.isfinite(iv[i1, j]) and iv[i1, j] > 0 else v0
        put = side < 0
        K = S0 * (1 - o.get('mny', 0.0)) if put else S0 * (1 + o.get('mny', 0.0))
        T0 = o.get('dte', 30) / 365
        T1 = max(T0 - P.years(days[i0], days[i1]), 0.0)
        p0 = P.bs(S0, K, T0, P.vol_for(S0, K, T0, v0, put), put) * (1 + o.get('spread', .03))
        p1 = P.bs(S1, K, T1, P.vol_for(S1, K, max(T1, 1e-6), v1, put), put) * (1 - o.get('spread', .03))
        if p0 <= 0:
            return None
        return p1 / p0 - 1

    def option_account(self, A, legs, seg, o):
        """Realised option account over seg: each leg (side, i0, i1, j) buys `frac` of the realised equity in
        premium at its entry close (skipped when open premium would pass `cap` of equity), sold at its exit close.
        Returns (curve over the segment's sessions, closed option trades)."""
        days = A['days'].astype(str)
        d0, d1 = int(np.searchsorted(days, seg[0])), int(np.searchsorted(days, seg[1], side='right'))
        frac, cap = o.get('frac', .10), o.get('cap', 1.0)
        by_day = {}
        for lg in legs:
            by_day.setdefault(lg[1], []).append(lg)
        eq, open_, curve, trades = 1.0, [], [], []
        for i in range(d0, d1):
            keep = []
            for (amt, side, i0, i1, j, r) in open_:
                if i1 == i:
                    eq += amt * r
                    trades.append(dict(entry=days[i0], exit=days[i], days=i - i0, ret=r, side=side))
                else:
                    keep.append((amt, side, i0, i1, j, r))
            open_ = keep
            for side, i0, i1, j, *px in by_day.get(i, []):
                if i1 >= d1 or i1 <= i0:
                    continue
                r = self.option_return(A, side, i0, i1, j, o, px[0] if px else None)
                if r is None:
                    continue
                amt = frac * eq
                if sum(x[0] for x in open_) + amt > cap * eq + 1e-12:
                    continue
                open_.append((amt, side, i0, i1, j, r))
            curve.append(eq)
        return np.array(curve), trades

    def option_stats(self, A, cfg, tr, seg, draws):
        """The option account of the stock trades `tr` and its same-list random-entry placebo (same entry day,
        side and holding, a random name of that day's list), as goal-ready stats."""
        from studies.trader_options import goal as G
        o = cfg['opt']
        days = A['days'].astype(str)
        di = {d: i for i, d in enumerate(days)}
        ci = {str(c): j for j, c in enumerate(A['codes'])}
        legs = [(t['side'], di[t['entry']], di[t['exit']], ci[t['code']], t['executions'][-1]['price']) for t in tr
                if t['entry'] in di and t['exit'] in di and t['why'] != 'end']
        curve, otr = self.option_account(A, legs, seg, o)
        sd = days[(days >= seg[0]) & (days <= seg[1])]
        lst = lag(self.listed(A, cfg))
        rng = np.random.default_rng(1)
        tots = []
        for _ in range(draws):
            pl = []
            for side, i0, i1, j, _ in legs:                   # the placebo sells at the close
                cand = np.flatnonzero(lst[i0])
                if len(cand):
                    pl.append((side, i0, i1, int(rng.choice(cand))))
            c, _ = self.option_account(A, pl, seg, o)
            tots.append(c[-1] - 1 if len(c) else 0.0)
        tots = np.array(tots) if tots else np.zeros(1)
        total = float(curve[-1] - 1) if len(curve) else 0.0
        by_year = {}
        for y in sorted({d[:4] for d in sd}):
            idx = np.flatnonzero(np.char.startswith(sd, y))
            base = curve[idx[0] - 1] if idx[0] > 0 else 1.0
            by_year[y] = float(curve[idx[-1]] / base - 1)
        peak = np.maximum.accumulate(curve) if len(curve) else np.ones(1)
        return dict(total=total, by_year=by_year, maxdd=float(np.max(1 - curve / peak)) if len(curve) else 0.0,
                    placebo=dict(median=float(np.median(tots)), rank=float(np.mean(tots < total))),
                    periods=G.period_returns(curve, sd, self.periods), goal_behaviour=G.behaviour_of(otr, len(sd)),
                    trades=len(otr))

    def evaluate(self, A, cfg, ls, lv, placebo=None):
        """The stock run (kept under 'stock'), then, with cfg['opt'], the option account replaces the totals,
        years, placebo and behaviour the goal and the gates read."""
        from studies.trader_options import goal as G
        st, tr = study.Study.evaluate(self, A, cfg, ls, lv, placebo)
        if cfg.get('opt'):
            st['stock'] = dict(total=st['total'], by_year=st['by_year'], placebo=st['placebo'],
                               periods=st.get('periods'), maxdd=st['maxdd'])
            draws = self.draws if placebo is None else placebo
            st.update(self.option_stats(A, cfg, tr, self.full, max(draws, 20)))
        pg = G.period_gaps(st.get('periods', {}), self.periods, self.full)
        dv = G.deviations(st.get('goal_behaviour', {}), self.goal_behaviour)
        st['goal'], st['goal_years'], st['goal_behav'] = G.goal_of(pg, dv)
        st['goal_parts'] = dict(periods=pg, behaviour=dv)
        st['meets'] = bool(st['goal'] >= -1 and st['total'] > st['placebo']['median'])
        return st, tr

    def options(self, report, key='chosen', dte=30, seg=WINDOW, frac=.10):
        """The same trades as ~dte-day ATM calls (longs) / puts (shorts) bought at the entry close and sold at the
        exit close, each `frac` of equity (premium), priced on OpenD's IV with a 2% half spread."""
        from studies.trader_options import pricing as P
        cfg = self.config(report, key)
        A = self.arrays('us')
        codes = [str(x) for x in A['codes']]
        iv = P.load_panel('iv', 'iv', A['days'], codes, .01)
        entries, rules, mask, pool = self.build(A, cfg)
        st, tr = self.run(A, entries, seg, pool, rules, placebo=0, audit=True)
        F, days = A['F'], A['days']
        di = {str(d): i for i, d in enumerate(days)}
        eq, curve_y = 1.0, {}
        rets = []
        for t in sorted(tr, key=lambda x: x['entry']):
            i0, i1 = di.get(t['entry']), di.get(t['exit'])
            j = codes.index(t['code']) if t['code'] in codes else None
            if i0 is None or i1 is None or j is None or not np.isfinite(iv[i0, j]):
                continue
            put = t['side'] < 0
            S0, S1 = float(F.raw[i0, j]), float(F.raw[i1, j])
            K = S0
            T0 = dte / 365
            T1 = max(T0 - (np.datetime64(t['exit']) - np.datetime64(t['entry'])).astype(int) / 365, 1 / 365)
            v0 = float(iv[i0, j])
            v1 = float(iv[i1, j]) if np.isfinite(iv[i1, j]) else v0
            p0 = P.bs(S0, K, T0, v0, put) * 1.02
            p1 = P.bs(S1, K, T1, v1, put) * .98
            r = p1 / p0 - 1
            rets.append(r)
            eq *= 1 + frac * r
            curve_y[t['exit'][:4]] = eq
        prev, by = 1.0, {}
        for y in sorted(curve_y):
            by[y] = curve_y[y] / prev - 1
            prev = curve_y[y]
        out = dict(trades=len(rets), win=float(np.mean([r > 0 for r in rets])) if rets else None,
                   avg=float(np.mean(rets)) if rets else None, total=eq - 1, by_year=by, frac=frac, dte=dte)
        print('OPTIONS', report, key, seg, out, flush=True)
        return out

    def validate(self, report, key='chosen'):
        cfg = self.config(report, key)
        A = self.arrays('us')
        entries, rules, mask, pool = self.build(A, cfg)
        out = {'report': report, 'config': cfg}
        for nm, seg in (('select', SELECT), ('validate', VALIDATE), ('window', WINDOW)):
            st, tr = self.run(A, entries, seg, pool, rules, audit=True)
            st.pop('_curve', None)
            st['ew_hold_pool'] = study.ew_hold(A, pool, seg, lagged=True)
            out[nm] = st
            print('VALIDATE', nm, f"total {st['total']:+.3f} dd {st['maxdd']:.2f} placebo median "
                  f"{st['placebo']['median']:+.3f} rank {st['placebo']['rank']:.2f} ew {st['ew_hold_pool']:+.3f}",
                  {a: round(b, 3) for a, b in st['by_year'].items()}, 'n', st['trades'], 'win', st['win'],
                  'avg', st.get('avg_win'), st.get('avg_loss'), flush=True)
        if cfg.get('opt'):                                    # the option account (R3 on), as the rounds score it
            for nm, seg in (('select', SELECT), ('validate', VALIDATE), ('window', WINDOW)):
                _, tr = self.run(A, entries, seg, pool, rules, placebo=0, audit=True)
                o = self.option_stats(A, cfg, tr, seg, 30)
                out['option_' + nm] = o
                print('OPTION', nm, f"total {o['total']:+.3f} dd {o['maxdd']:.2f} placebo median "
                      f"{o['placebo']['median']:+.3f} rank {o['placebo']['rank']:.2f}",
                      {a: round(b, 3) for a, b in o['by_year'].items()}, 'periods',
                      {a: (round(b, 3) if b is not None else None) for a, b in o['periods'].items()},
                      'n', o['trades'], 'behaviour',
                      {a: (round(b, 3) if b else b) for a, b in o['goal_behaviour'].items()}, flush=True)
        else:
            for nm, seg in (('select', SELECT), ('validate', VALIDATE)):
                out['options_' + nm] = self.options(report, key, seg=seg)
        self.out.mkdir(parents=True, exist_ok=True)
        (self.out / f'validate_{report.replace(".json", "")}_{key}.json').write_text(
            json.dumps(out, indent=1, default=float), encoding='utf-8')
        return out


STUDY = Emanuela()

if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == 'validate':
        STUDY.validate(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else 'chosen')
    elif len(sys.argv) > 1 and sys.argv[1] == 'options':
        STUDY.options(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else 'chosen')
    else:
        study.main(STUDY, sys.argv)
