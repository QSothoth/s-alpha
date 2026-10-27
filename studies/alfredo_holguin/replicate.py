"""Alfredo Holguin through skills/trader-replication: weekly cash-secured puts on liquid large caps, strike a cushion
of daily ATRs under the price, held to the weekly expiry (holguintrades.com; his 1,417 published trades,
notes/trades_holguin.csv, and his weekly returns, notes/weeks_holguin.csv; USIC 2025 +100.2%).

    PY="nice -n 19 env OPENBLAS_NUM_THREADS=1 PYTHONUTF8=1 /opt/futu-opend/venv/bin/python"
    $PY -m studies.alfredo_holguin.replicate round R1
    $PY -m studies.alfredo_holguin.replicate validate r1.json

The ledger publishes each trade's strike, days to expiry, collateral share ("risk per trade"), the strike's distance
in ATR14 and the price's distance above its 200-day in ATR14 (his own screen fields), but not the premium: options
are priced by studies/trader_options/pricing.py on OpenD's daily IV (an approximation).  Selection segment: 2025
(his ledger starts 2024-12-23); validation: 2026-01-02 -> 2026-10-16 once (his weekly table runs to 2026-05-29).
"""
from __future__ import annotations

import collections
import csv
import datetime as dt
import json
import math
import re
import sys
from pathlib import Path

import numpy as np

from studies.trader_options import pricing as P
from studies.trader_replication import panels
from studies.trader_screens import screens as S

ROOT = Path(__file__).resolve().parents[2]
HERE = ROOT / 'studies' / 'alfredo_holguin'
lag = S.lag

SELECT = ('2025-01-02', '2025-12-31')
VALIDATE = ('2026-01-02', '2026-10-16')
WINDOW = ('2024-01-02', '2026-10-16')

DRAFT = dict(
    cushion=2.0,               # strike = open - 2 ATR14 (his median strike distance -2.0 ATR, margin of safety 2.0)
    trend=0.0,                 # (close - 200-day) / ATR14 at least this (his median +5.1, 25th pct +2.0)
    turnover=500e6,            # 20-day turnover (his median market cap 193B USD; no market caps in the data)
    optvol=20000,              # 20-day average option volume (contracts) at least this: liquid options only
    price=20.0,
    earnings=False,            # True: also sell when an earnings day falls before the expiry (108 of his 1,417 did)
    min_dte=2,                 # calendar days to the week's expiry at least this, else next week's (his DTE 2-8)
    frac=.05,                  # collateral per trade, of equity (his mean risk_per_trade 4.9%)
    cap=1.0,                   # total collateral at most this x equity
    max_new=4,                 # new puts a day (his ~19 a week)
    priority='yield',          # premium / strike, highest first ('iv': highest IV)
    skew=.10, spread=.05,
    take=0.0,                  # > 0: buy back when the put is worth at most this share of the premium received
)


def week_expiries(days):
    """For each session, the index of the last session of its ISO week (the weekly expiry)."""
    wk = [dt.date.fromisoformat(str(d)).isocalendar()[:2] for d in days]
    out = np.zeros(len(days), int)
    i = len(days) - 1
    last = i
    while i >= 0:
        if i == len(days) - 1 or wk[i] != wk[i + 1]:
            last = i
        out[i] = last
        i -= 1
    return out


def grid(S_):
    return .5 if S_ < 25 else 1.0 if S_ < 100 else 2.5 if S_ < 250 else 5.0


class Holguin:
    id, name = 'alfredo_holguin', 'Alfredo Holguin'
    reports = HERE / 'reports'
    rounds = HERE / 'notes' / 'rounds'

    def __init__(self):
        self._A = None

    def data(self):
        if self._A is None:
            A = panels.arrays('us')
            F = A['F']
            codes = [str(c) for c in A['codes']]
            A['iv'] = P.load_panel('iv', 'iv', A['days'], codes, .01)
            ov = P.load_panel('stat', 'option_volume', A['days'], codes)
            A['optvol20'] = S.rolling(np.where(np.isfinite(ov), ov, np.nan), 20, 'mean')
            A['earn'] = P.earnings(set(codes))
            A['expiry'] = week_expiries(A['days'])
            A['codes_s'] = codes
            ev = {}                                                  # session indexes of earnings reactions
            for j, c in enumerate(codes):
                for date, pub in A['earn'].get(c, []):
                    i = P.reaction_day(A['days'], date, pub)
                    if i is not None:
                        ev.setdefault(j, []).append(i)
            A['earn_idx'] = {j: sorted(v) for j, v in ev.items()}
            with np.errstate(invalid='ignore', divide='ignore'):
                A['trend'] = (F.c - F.sma(200)) / F.atr14
            self._A = A
        return self._A

    def earn_var(self, A, j, d, expiry):
        """Earnings variance for an option of name j opened on session d expiring at session `expiry`: e^2 when a
        reaction day falls in (d, expiry], e the median absolute reaction of its earlier earnings (6% if fewer than
        two known)."""
        idx = A['earn_idx'].get(j, [])
        if not any(d < i <= expiry for i in idx):
            return 0.0, False
        c = A['close']
        past = [abs(c[i, j] / c[i - 1, j] - 1) for i in idx if 1 <= i < d and np.isfinite(c[i, j])
                and np.isfinite(c[i - 1, j])]
        e = float(np.median(past)) if len(past) >= 2 else .06
        return e * e, True

    def v2_put(self, A, j, ivd, S, K, T, ie, pc):
        """v2 price of a put (studies/trader_options/notes/SIM_V2_PREREG_CN.md) on the IV of session ivd: the next
        report's variance read off the name's past IV drops, a smile k, expiring at session ie."""
        iv = float(A['iv'][ivd, j])
        if not (np.isfinite(iv) and iv > 0):
            return float('nan')
        rx = A['earn_idx'].get(j, [])
        c = A['close']
        past = [abs(c[i, j] / c[i - 1, j] - 1) for i in rx if 1 <= i <= ivd and np.isfinite(c[i, j])
                and np.isfinite(c[i - 1, j])]
        E = P.implied_event_var(A['iv'], j, rx, ivd + 1, float(np.median(past)) ** 2 if len(past) >= 2 else .06 ** 2)
        _, near, spans = P.event_context(A['days'], rx, ivd, ie)
        return P.bs(S, K, T, P.vol_v2(S, K, T, iv, True, E, near, spans, pc.get('k', .05), pc.get('strip', True)), True)

    def eligible(self, A, cfg):
        F = A['F']
        with np.errstate(invalid='ignore'):
            m = ((F.to20 >= cfg['turnover']) & (F.raw >= cfg['price']) & (A['optvol20'] >= cfg['optvol'])
                 & np.isfinite(A['iv']) & (A['iv'] > 0) & (A['trend'] >= cfg['trend']) & np.isfinite(F.atr14))
            if cfg.get('trend_max') is not None:
                m &= A['trend'] <= cfg['trend_max']
            if cfg.get('iv_min'):                                    # R6: his names' IV (median 0.54, 25% 0.41)
                m &= A['iv'] >= cfg['iv_min']
            if cfg.get('names'):                                     # ERR4 diagnosis only: his own names (lookahead)
                keep = set(cfg['names'])
                m &= np.array([str(c)[3:] in keep for c in A['codes']])[None, :]
        return lag(m)                                                # as of the prior close

    def simulate(self, cfg, start, end, placebo=None, audit=False):
        """(equity curve, dates, trades).  placebo: a numpy Generator; each day's new puts go to random eligible
        names instead (same count, same cushion rule)."""
        A = self.data()
        F = A['F']
        o, c, days = F.o, F.c, A['days']
        iv, atr = A['iv'], F.atr14
        elig = self.eligible(A, cfg)
        d0, d1 = int(np.searchsorted(days, start)), int(np.searchsorted(days, end, side='right'))
        cash, eq_prev = 1.0, 1.0
        pos, trades, curve = [], [], []
        exp = A['expiry']
        for d in range(d0, d1):
            # --- new puts at the open, sized on the prior close's equity ---
            held = collections.Counter(p['j'] for p in pos)      # per_name > 1 (ERR15-2): another put on a name
            today = {p['j'] for p in pos if p['d0'] == d}            # already held, on a later day of the week --
            coll = sum(p['m'] * p['n'] for p in pos)                 # 130 of his 147 repeat name-weeks in 2025
            cand = []
            for j in np.flatnonzero(elig[d]):
                if held[j] >= cfg.get('per_name', 1) or j in today or not np.isfinite(o[d, j]):
                    continue
                e_ = exp[d]
                if (dt.date.fromisoformat(str(days[e_])) - dt.date.fromisoformat(str(days[d]))).days < cfg['min_dte']:
                    if e_ + 1 >= len(days):
                        continue
                    e_ = exp[e_ + 1]
                ev, has_e = self.earn_var(A, j, d, e_)
                if has_e and not cfg.get('earnings'):
                    continue
                S0 = float(o[d, j])
                g = grid(S0)
                K = math.floor((S0 - cfg['cushion'] * atr[d - 1, j]) / g) * g
                if K <= 0:
                    continue
                T = P.years(days[d], days[e_])
                atm = self.model_vol(A, j, d, cfg)                   # as of the prior close
                base = math.sqrt(max(atm * atm - ev / (30 / 365), (.5 * atm) ** 2)) if has_e else atm
                v = P.vol_for(S0, K, T, atm, True, cfg['skew'], earn_var=ev, base_atm=base)
                prem = P.bs(S0, K, T, v, True) * (1 - cfg['spread']) - P.COMMISSION / 100
                if cfg.get('v2'):                                    # v2 pricing (SIM_V2_PREREG_CN.md)
                    q = self.v2_put(A, j, d - 1, S0, K, T, e_, cfg)
                    prem = q * (1 - P.half_spread(q) * cfg.get('spread_x', 1)) - P.COMMISSION / 100
                if not prem > .01:                                   # also a missing v2 IV
                    continue
                if cfg['priority'] == 'yield':
                    pr = -prem / K
                elif cfg['priority'] == 'yield_iv':           # rank on the IV-only premium (observable), whatever
                    iv0 = float(iv[d - 1, j])                 # vol the price itself uses
                    pr = -P.bs(S0, K, T, P.vol_for(S0, K, T, iv0, True, cfg['skew'], earn_var=ev,
                                                   base_atm=min(base, iv0)), True) / K
                elif cfg['priority'] == 'iv30':               # R6: OpenD's 30-day IV, highest first
                    pr = -float(iv[d - 1, j])
                elif cfg['priority'] == 'turnover':           # the biggest names first (his median cap 193B)
                    pr = -float(F.to20[d - 1, j])
                else:
                    pr = -atm
                cand.append((pr, j, K, e_, prem, base, ev, S0))
            if placebo is not None and cand:
                pick = placebo.permutation(len(cand))
                cand = [cand[k] for k in pick]
            else:
                cand.sort()
            new = 0
            for pr, j, K, e_, prem, base, ev, S0 in cand:
                if new >= cfg['max_new']:
                    break
                if cfg.get('margin') == 'regt':   # his "risk per trade" read as the Reg-T naked-put margin share:
                    m_ = max(.20 * S0 - max(S0 - K, 0.0) + prem, .10 * K + prem)   # per share
                else:                             # cash-secured: the strike
                    m_ = K
                n = cfg['frac'] * eq_prev / m_
                if coll + m_ * n > cfg['cap'] * eq_prev + 1e-12:
                    break
                cash += n * prem
                coll += m_ * n
                pos.append(dict(j=j, K=K, n=n, e=e_, prem=prem, base=base, ev=ev, d0=d, S0=S0, m=m_))
                new += 1
            # --- the close: expiries settle at intrinsic, take-profits, marks ---
            keep, liab = [], 0.0
            for p in pos:
                j = p['j']
                S_ = float(c[d, j]) if np.isfinite(c[d, j]) else p['S0']
                if d >= p['e']:
                    pay = max(p['K'] - S_, 0.0)
                    cash -= p['n'] * pay
                    if (pay > 0 and cfg.get('v2') and p.get('rolls', 0) < cfg.get('roll', 0)
                            and d + 1 < len(days)):          # R9: his rolls -- 97 of his 116 losers were followed
                        e2 = exp[d + 1]                      # by a new put on the name that day, strike ~97.3%: the
                        g = grid(S_)                         # loss settles, next week's put at roll_k x the strike
                        K2 = math.floor(p['K'] * cfg.get('roll_k', .975) / g) * g
                        T2 = P.years(days[d], days[e2])
                        q = self.v2_put(A, j, d, S_, K2, T2, e2, cfg)
                        if K2 > 0 and np.isfinite(q) and q > .01:
                            prem2 = q * (1 - P.half_spread(q) * cfg.get('spread_x', 1)) - P.COMMISSION / 100
                            m2 = (max(.20 * S_ - max(S_ - K2, 0.0) + prem2, .10 * K2 + prem2)
                                  if cfg.get('margin') == 'regt' else K2)
                            cash += p['n'] * prem2
                            trades.append(self.trade(A, p, d, pay, 'rolled'))
                            keep.append(dict(p, K=K2, e=e2, prem=prem2, d0=d, S0=S_, m=m2, ev=0.0,
                                             rolls=p.get('rolls', 0) + 1))
                            liab += p['n'] * q
                            continue
                    trades.append(self.trade(A, p, d, pay, 'expiry'))
                    continue
                T = P.years(days[d], days[p['e']])
                ev = p['ev'] if any(d < i <= p['e'] for i in A['earn_idx'].get(j, [])) else 0.0
                atm = self.model_vol(A, j, d + 1, cfg) if np.isfinite(iv[d, j]) else p['base']
                v = P.vol_for(S_, p['K'], T, atm, True, cfg['skew'], earn_var=ev, base_atm=atm if not ev else p['base'])
                val = P.bs(S_, p['K'], T, v, True)
                sp = cfg['spread']
                if cfg.get('v2'):
                    v2v = self.v2_put(A, j, d if np.isfinite(iv[d, j]) else d - 1, S_, p['K'], T, p['e'], cfg)
                    val = v2v if np.isfinite(v2v) else val
                    sp = P.half_spread(val) * cfg.get('spread_x', 1)
                if cfg.get('take') and val * (1 + sp) + P.COMMISSION / 100 <= cfg['take'] * p['prem']:
                    pay = val * (1 + sp) + P.COMMISSION / 100
                    cash -= p['n'] * pay
                    trades.append(self.trade(A, p, d, pay, 'take'))
                    continue
                liab += p['n'] * val
                keep.append(p)
            pos = keep
            eq = cash - liab
            curve.append(eq)
            eq_prev = eq
        for p in pos:
            trades.append(self.trade(A, p, d1 - 1, None, 'open'))
        return np.array(curve), days[d0:d1], trades

    def trade(self, A, p, d, pay, why):
        return dict(code=A['codes_s'][p['j']], entry=str(A['days'][p['d0']]), expiry=str(A['days'][p['e']]),
                    exit=str(A['days'][d]), K=p['K'], S0=p['S0'], prem=p['prem'], pay=pay, why=why,
                    ret=None if pay is None else (p['prem'] - pay) / p['K'], n=p['n'])

    # ----- his records -----
    @staticmethod
    def his_trades():
        out = []
        with (HERE / 'notes' / 'trades_holguin.csv').open(encoding='utf-8') as f:
            for r in csv.DictReader(f):
                out.append(r)
        return out

    @staticmethod
    def his_weeks():
        out = {}
        with (HERE / 'notes' / 'weeks_holguin.csv').open(encoding='utf-8') as f:
            for r in csv.DictReader(f):
                out[r['weekly_expiration'][:10]] = float(r['weekly_percent_gain'])
        return out

    def fidelity(self, A, trades, seg):
        """Overlap with his (name, expiry week) positions, our weekly returns against his, behaviour."""
        def wk(s):
            return dt.date.fromisoformat(s[:10]).isocalendar()[:2]
        his = [t for t in self.his_trades() if seg[0] <= t['date_entered'][:10] <= seg[1]]
        hs = {(t['symbol'].upper(), wk(t['weekly_expiration'])) for t in his}
        ours = {(t['code'][3:], wk(t['expiry'])) for t in trades if seg[0] <= t['entry'] <= seg[1]}
        his_names = {t['symbol'].upper() for t in his}
        our_names = {t['code'][3:] for t in trades if seg[0] <= t['entry'] <= seg[1]}
        closed = [t for t in trades if t['ret'] is not None and seg[0] <= t['entry'] <= seg[1]]
        dist = [(t['K'] - t['S0']) for t in closed]
        return dict(his_positions=len(hs), ours=len(ours), both=len(hs & ours),
                    his_hit=len(hs & ours) / max(len(hs), 1), our_hit=len(hs & ours) / max(len(ours), 1),
                    names_his=len(his_names), names_ours=len(our_names), names_both=len(his_names & our_names),
                    win=float(np.mean([t['ret'] > 0 for t in closed])) if closed else None,
                    his_win=float(np.mean([int(t['Trade_Success']) for t in his])) if his else None,
                    per_week=len(closed) / max(1, len({wk(t['expiry']) for t in closed})),
                    his_per_week=len(his) / max(1, len({wk(t['weekly_expiration']) for t in his})))

    def weekly(self, curve, dates):
        """Our weekly returns by the week's last session, against his weekly table (same weeks)."""
        out, prev, last = {}, 1.0, None
        wk = [dt.date.fromisoformat(str(d)).isocalendar()[:2] for d in dates]
        for i in range(len(dates)):
            if i == len(dates) - 1 or wk[i] != wk[i + 1]:
                out[str(dates[i])] = curve[i] / prev - 1
                prev = curve[i]
        his = self.his_weeks()
        pairs = []
        for d, r in out.items():
            hk = next((h for h in his if dt.date.fromisoformat(h).isocalendar()[:2] ==
                       dt.date.fromisoformat(d).isocalendar()[:2]), None)
            if hk is not None:
                pairs.append((r, his[hk]))
        if len(pairs) >= 5:
            a, b = np.array(pairs).T
            corr = float(np.corrcoef(a, b)[0, 1])
            ours_c, his_c = float(np.prod(1 + a) - 1), float(np.prod(1 + b) - 1)
        else:
            corr = ours_c = his_c = None
        return dict(weeks=len(pairs), corr=corr, ours_compound=ours_c, his_compound=his_c,
                    worst_week=float(min(out.values())) if out else None)

    # ----- layer 2 of the three-layer replay: his own trades priced by our model -----
    def hv(self, A, n):
        """n-session close-to-close volatility (annualised fraction) as of each close."""
        key = f'hv{n}'
        if key not in A:
            c = A['close']
            with np.errstate(invalid='ignore', divide='ignore'):
                lr = np.log(c / lag(c))
            m, m2 = S.rolling(lr, n, 'mean'), S.rolling(lr * lr, n, 'mean')
            A[key] = np.sqrt(np.maximum(m2 - m * m, 0) * n / max(n - 1, 1) * 252)
        return A[key]

    def model_vol(self, A, j, d, pc):
        """The vol our model gives an option of name j on session d (as of the prior close): pc['vol'] is 'iv'
        (OpenD's 30-day IV), 'max5' (the larger of IV and the 5-session HV), 'blend5' (root mean square of the
        two) or 'max10'."""
        iv = float(A['iv'][d - 1, j])
        k = pc.get('vol', 'iv')
        if k == 'iv':
            return iv
        h = float(self.hv(A, int(k[-2:]) if k[-2:].isdigit() else int(k[-1]))[d - 1, j])
        if not np.isfinite(h):
            return iv
        if k.startswith('max'):
            return max(iv, h)
        return math.sqrt(.5 * iv * iv + .5 * h * h)

    def replay(self, pc, seg=('2025-01-02', '2026-05-29')):
        """Each of his trades in seg priced by our model: sold at the entry day's open (close when entered after
        noon) at his strike and expiry, bought back at the close day's close when closed before the expiry, else
        settled at the expiry close; pc['assign'] (default on) settles an in-the-money put assigned at the expiry
        by selling the shares on his close day (its open when closed before noon, else its close).  The account
        effect is his collateral share x (premium - payout) / collateral per share, pc['margin'] 'cash' (the strike)
        or 'regt'.  Returns per-week sums by his expiry week against his weekly table."""
        A = self.data()
        F, days = A['F'], A['days'].astype(str)
        ci = {c: j for j, c in enumerate(A['codes_s'])}
        spread, skew = pc.get('spread', .05), pc.get('skew', .10)
        weeks, rows = {}, []
        trades = self.his_trades()
        week_keys = sorted(self.his_weeks())
        iso_key = {dt.date.fromisoformat(h).isocalendar()[:2]: h for h in week_keys}
        parts = {}                                 # one position closed in parts appears once per part, each row
        for t in trades:                            # with the position's full size: split the size across them
            k = (t['symbol'].upper(), t['date_entered'], t['OCC_option_symbol'])
            parts[k] = parts.get(k, 0) + 1
        rolls = {}                                  # a roll: a new put on the name entered on the close day with a
        for t in trades:                            # negative risk_per_trade (his table books trades net of rolls)
            if float(t['risk_per_trade']) < 0:
                rolls.setdefault((t['symbol'].upper(), t['date_entered'][:10]), t['weekly_expiration'][:10])
        for t in trades:
            de, dc = t['date_entered'][:10], t['date_closed'][:10]
            if not seg[0] <= de <= seg[1]:
                continue
            j = ci.get('US.' + t['symbol'].upper())
            mo = re.search(r'(\d{2})(\d{2})(\d{2})[CP]\d+$', t['OCC_option_symbol'])
            ex = f'20{mo.group(1)}-{mo.group(2)}-{mo.group(3)}' if mo else t['weekly_expiration'][:10]
            K = float(t['strike_option_contract'])
            i0 = int(np.searchsorted(days, de))
            ie = min(int(np.searchsorted(days, ex, side='right')) - 1, len(days) - 1)
            ic = min(int(np.searchsorted(days, dc)), len(days) - 1)
            if j is None or i0 >= len(days) or days[i0] != de or not np.isfinite(A['iv'][i0 - 1, j]):
                rows.append(dict(t=t, ok=False))
                continue
            noon = lambda s: int(s[11:13]) >= 12
            S0 = (F.o[i0, j] if not noon(t['date_entered']) else F.c[i0, j]) * F.raw[i0, j] / F.c[i0, j]
            T0 = P.years(days[i0], ex)
            v0 = self.model_vol(A, j, i0, pc)
            if pc.get('v2'):                                     # v2: as of the prior close, tick-floored spread
                q = self.v2_put(A, j, i0 - 1, S0, K, T0, ie, pc)
                prem = q * (1 - P.half_spread(q) * pc.get('spread_x', 1)) - P.COMMISSION / 100
            else:
                prem = P.bs(S0, K, T0, P.vol_for(S0, K, T0, v0, True, skew), True) * (1 - spread) - P.COMMISSION / 100
            raw = lambda i, px: px[i, j] * F.raw[i, j] / F.c[i, j]
            am = pc.get('intraday') and not noon(t['date_closed'])
            if dc < ex or (dc == ex and am):                        # bought back early: at that day's close, or
                S1 = raw(ic, F.o) if am else raw(ic, F.c)           # its open when closed in the morning
                T1 = P.years(dc, ex) + (5.5 / (365 * 24) if am else 0.0)
                v1 = self.model_vol(A, j, min(ic + 1, len(days) - 1), pc)     # as of that close
                v1 = v1 if np.isfinite(v1) and v1 > 0 else v0
                if pc.get('v2'):
                    q = self.v2_put(A, j, ic, S1, K, T1, ie, pc)
                    pay = q * (1 + P.half_spread(q) * pc.get('spread_x', 1)) + P.COMMISSION / 100
                else:
                    pay = P.bs(S1, K, T1, P.vol_for(S1, K, T1, v1, True, skew), True) * (1 + spread) + P.COMMISSION / 100
                how = 'early'
            else:
                Se = raw(ie, F.c)
                pay = max(K - Se, 0.0)
                how = 'expiry'
                if pay > 0 and pc.get('assign', True) and dc > ex:   # assigned: shares sold on his close day
                    Ss = raw(ic, F.o) if not noon(t['date_closed']) else raw(ic, F.c)
                    pay = K - Ss                                      # below zero when the shares recovered
                    how = 'assigned'
            mg = pc.get('margin', 'cash')
            if mg == 'cash':
                m = K
            elif mg.startswith('pm'):               # portfolio margin: the loss if the stock fell pm% (15 default),
                mv = int(mg[2:] or 15) / 100        # at least 2.5% of the strike
                m = max(K - (1 - mv) * S0, .025 * K)
            else:
                m = max(.20 * S0 - max(S0 - K, 0.0) + prem, .10 * K + prem)
            size = abs(float(t['risk_per_trade']))
            if pc.get('parts', True):
                size /= parts[(t['symbol'].upper(), t['date_entered'], t['OCC_option_symbol'])]
            if pc.get('oracle') and (prem - pay > 0) != (t['Trade_Success'] == '1'):
                pay = prem - pc['oracle'] * prem * (1 if t['Trade_Success'] == '1' else -1)  # diagnostic only: his
            pnl = size * (prem - pay) / m                                                   # label overrides ours
            wk = t['weekly_expiration'][:10]
            if pc.get('by_close'):                                  # booked in the week it was closed (assigned
                iso = dt.date.fromisoformat(dc).isocalendar()[:2]   # shares sold the next Monday land there)
                wk = next((h for h in week_keys if dt.date.fromisoformat(h).isocalendar()[:2] == iso), wk)
            if pc.get('roll') and prem - pay < 0 and (t['symbol'].upper(), dc) in rolls:
                wk = max(rolls[(t['symbol'].upper(), dc)], wk)       # the loss rides with the rolled put
            if pc.get('mtm'):                       # the account marked at each week's last close: a put opened in
                xi = ie if how == 'expiry' else ic  # an earlier week books its premium decay there, an assigned put
                last, owed = None, prem             # the Friday intrinsic in the expiry week, the sale the next
                for k in range(i0, xi):
                    if A['expiry'][k] != k:
                        continue
                    Sk = raw(k, F.c)
                    if k < ie:
                        Tk = P.years(days[k], ex)
                        vk = self.model_vol(A, j, min(k + 1, len(days) - 1), pc)
                        Vk = P.bs(Sk, K, Tk, P.vol_for(Sk, K, Tk, vk if np.isfinite(vk) and vk > 0 else v0, True, skew), True)
                    else:
                        Vk = max(K - Sk, 0.0) if how == 'expiry' else K - Sk
                    key = iso_key.get(dt.date.fromisoformat(days[k]).isocalendar()[:2])
                    if key:
                        weeks[key] = weeks.get(key, 0.0) + size * (owed - Vk) / m * (1 if last is None else 1)
                    owed, last = Vk, k
                key = iso_key.get(dt.date.fromisoformat(days[xi]).isocalendar()[:2], wk)
                weeks[key] = weeks.get(key, 0.0) + size * (owed - pay) / m
            else:
                weeks[wk] = weeks.get(wk, 0.0) + pnl
            rows.append(dict(t=t, ok=True, prem=prem, pay=pay, pnl=pnl, how=how, win=prem - pay > 0,
                             his_win=t['Trade_Success'] == '1', K=K, S0=S0))
        self.last_rows = rows                      # per-trade detail of the last replay
        his = self.his_weeks()
        pairs = [(weeks.get(w, 0.0), his[w]) for w in sorted(his) if seg[0] <= w <= seg[1]]
        a, b = np.array(pairs).T
        ok = [r for r in rows if r['ok']]
        return dict(weeks=len(pairs), corr=float(np.corrcoef(a, b)[0, 1]), ours_mean=float(a.mean()),
                    his_mean=float(b.mean()), ours_sum=float(a.sum()), his_sum=float(b.sum()),
                    slope=float(np.polyfit(b, a, 1)[0]), priced=len(ok), missing=len(rows) - len(ok),
                    agree=float(np.mean([r['win'] == r['his_win'] for r in ok])),
                    ours_win=float(np.mean([r['win'] for r in ok])), his_win=float(np.mean([r['his_win'] for r in ok])),
                    worst_ours=float(a.min()), worst_his=float(b.min()),
                    by_year={y: (float(np.prod([1 + x for x, w in zip(a, sorted(w for w in his if seg[0] <= w <= seg[1]))
                                               if w[:4] == y]) - 1),
                                 float(np.prod([1 + x for x, w in zip(b, sorted(w for w in his if seg[0] <= w <= seg[1]))
                                               if w[:4] == y]) - 1)) for y in ('2025', '2026')}), pairs

    def evaluate(self, cfg, seg, draws=0):
        A = self.data()
        curve, dates, tr = self.simulate(cfg, *seg)
        st = stats(curve, dates, tr)
        st['fidelity'] = self.fidelity(A, tr, seg)
        st['weekly'] = self.weekly(curve, dates)
        if draws:
            rng = np.random.default_rng(1)
            pl = np.array([self.simulate(cfg, *seg, placebo=rng)[0][-1] - 1 for _ in range(draws)])
            st['placebo'] = dict(median=float(np.median(pl)), rank=float((pl < st['total']).mean()), draws=draws)
        return st, tr

    def round(self, name):
        spec = json.loads((self.rounds / f'{name}.json').read_text(encoding='utf-8'))
        report, key = spec['base']
        base = dict(self.config(report, key), **spec.get('base_change', {}))   # a declared correction of the base
        cfgs = {k: dict(base, **v) for k, v in spec['candidates'].items()}
        ref = spec['ref']
        cfgs[ref] = base
        res = {}
        for k, cfg in cfgs.items():
            st, _ = self.evaluate(cfg, tuple(spec.get('select', SELECT)), draws=spec.get('draws', 20))   # R5: 2024-25
            if spec.get('objective') == 'goal':
                st.update(self.goal(st))
            res[k] = st
            show(name, k, st)
        if spec.get('objective') == 'goal':           # docs/prompts/new_styles_return_goal.md (R2 on)
            r = res[ref]
            ok = [k for k in cfgs if k == ref or (res[k]['total'] > res[k]['placebo']['median']
                  and res[k]['goal_years'] <= max(r['goal_years'], 1.0) + 1e-9
                  and res[k]['goal_behav'] <= max(r['goal_behav'], 1.0) + 1e-9)]
            best = max(ok, key=lambda k: res[k]['goal'])
            gates, objective = ['placebo', 'years', 'behav'], 'goal'
        else:
            ok = [k for k in cfgs if k == ref or (res[k]['total'] > res[k]['placebo']['median']
                                                   and res[k]['fidelity']['his_hit'] >= res[ref]['fidelity']['his_hit']
                                                   * spec.get('hit_floor', 0.9))]
            target = spec.get('target', 1.002)            # his USIC 2025
            best = min(ok, key=lambda k: abs(math.log((1 + res[k]['total']) / (1 + target))))
            gates, objective = ['placebo', f"his_hit >= {spec.get('hit_floor', 0.9)} x ref"], f'closest to {target}'
        out = dict(name=name, base=spec['base'], configs=cfgs, full=res, chosen=best, chosen_config=cfgs[best],
                   gates=gates, objective=objective)
        self.reports.mkdir(parents=True, exist_ok=True)
        (self.reports / f'{name.lower()}.json').write_text(json.dumps(out, indent=1, default=float), encoding='utf-8')
        print(name, 'chosen', best, flush=True)
        return out

    HIS_2025 = dict(ret=.5603, win=.8976, per_week=16.6)     # his weekly table compounded, his 2025 ledger

    def goal(self, st):
        """The goal on the 2025 selection segment: log gap to his weekly-table 2025, and win rate / trades a week
        within +-30% of his 2025 ledger; goal = -max(year gap / 0.3, worst behaviour deviation / 0.3)."""
        h, f = self.HIS_2025, st['fidelity']
        y = abs(math.log((1 + st['by_year'].get('2025', -.99)) / (1 + h['ret']))) / .3
        dv = {k: abs(f[k] / h[k] - 1) for k in ('win', 'per_week') if f.get(k)}
        b = max(dv.values()) / .3 if dv else 9.0
        return dict(goal=-max(y, b), goal_years=y, goal_behav=b, goal_parts=dict(year=y * .3, behaviour=dv),
                    meets=bool(max(y, b) <= 1 and st['total'] > st.get('placebo', {}).get('median', 9)))

    def config(self, report, key='chosen'):
        if not report:
            return dict(DRAFT)
        res = json.loads((self.reports / report).read_text(encoding='utf-8'))
        return res['chosen_config'] if key == 'chosen' else res['configs'][key]

    def validate(self, report, key='chosen'):
        cfg = self.config(report, key)
        out = {'report': report, 'config': cfg}
        for nm, seg in (('y2024', ('2024-01-02', '2024-12-31')), ('select', SELECT), ('validate', VALIDATE),
                        ('his_2026', ('2026-01-02', '2026-05-29')), ('window', WINDOW)):
            st, tr = self.evaluate(cfg, seg, draws=50)
            out[nm] = st
            show('VALIDATE', nm, st)
        (self.reports / f'validate_{report.replace(".json", "")}_{key}.json').write_text(
            json.dumps(out, indent=1, default=float), encoding='utf-8')
        return out


def stats(curve, dates, tr):
    curve = np.asarray(curve)
    peak = np.maximum.accumulate(np.concatenate([[1.0], curve]))[1:]
    by_year = {}
    prev = 1.0
    for y in sorted({str(d)[:4] for d in dates}):
        idx = [i for i, d in enumerate(dates) if str(d)[:4] == y]
        by_year[y] = float(curve[idx[-1]] / prev - 1)
        prev = curve[idx[-1]]
    closed = [t for t in tr if t['ret'] is not None]
    return dict(total=float(curve[-1] - 1), maxdd=float(np.max(1 - curve / peak)), by_year=by_year,
                trades=len(closed), win=float(np.mean([t['ret'] > 0 for t in closed])) if closed else None,
                worst_trade=float(min(t['ret'] for t in closed)) if closed else None)


def show(tag, k, st):
    f, w = st['fidelity'], st['weekly']
    pl = st.get('placebo', {})
    print(tag, k, f"total {st['total']:+.3f} dd {st['maxdd']:.2f}", {a: round(b, 3) for a, b in st['by_year'].items()},
          f"placebo {pl.get('median', float('nan')):+.3f} rank {pl.get('rank', float('nan')):.2f}",
          f"n {st['trades']} win {st['win'] if st['win'] is None else round(st['win'], 3)} (his {f['his_win']})",
          f"/wk {f['per_week']:.1f} (his {f['his_per_week']:.1f}) his_hit {f['his_hit']:.2f} names {f['names_both']}/{f['names_his']}",
          f"weekly corr {w['corr']} ours {w['ours_compound']} his {w['his_compound']} worst {w['worst_week']}", flush=True)


STUDY = Holguin()

if __name__ == '__main__':
    a = sys.argv[1]
    if a == 'round':
        STUDY.round(sys.argv[2])
    elif a == 'validate':
        STUDY.validate(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else 'chosen')
