"""Karl Domm (Real P&L, Earnings Edge) through skills/trader-replication: before an earnings report, short one
near-week strangle that expires before the report and buy two of the same strikes in the first weekly expiry after
it; out within days, before the report (his 2025 Schwab statements, notes/trades_karl.csv; 2025 account +321%,
USIC 2026 to September +46.2%).

    PY="nice -n 19 env OPENBLAS_NUM_THREADS=1 PYTHONUTF8=1 /opt/futu-opend/venv/bin/python"
    $PY -m studies.karl_domm.replicate calibrate
    $PY -m studies.karl_domm.replicate round R1
    $PY -m studies.karl_domm.replicate validate r1.json

Options are priced by studies/trader_options/pricing.py on OpenD's daily IV, with the earnings variance carried by
the far week (an approximation; `calibrate` compares it with his own fills).  Selection segment 2024-01-02 ->
2025-12-31 (his statements are 2025), validation 2026-01-02 -> 2026-10-16 once.
"""
from __future__ import annotations

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
HERE = ROOT / 'studies' / 'karl_domm'
lag = S.lag

SELECT = ('2024-01-02', '2025-12-31')
VALIDATE = ('2026-01-02', '2026-10-16')
WINDOW = ('2024-01-02', '2026-10-16')

DRAFT = dict(
    lead=12,                  # open this many sessions before the earnings reaction day (his 10-13)
    width=1.0,                # strikes at the price x (1 +- width x the far week's expected move: ATM vol x sqrt(T))
    ratio=2.0,                # long far / short near
    take=.25,                 # out once the position is worth (1 + take) x its debit ...
    stop=0.0,                 # ... or (stop > 0) at most (1 - stop) x it
    exit_lead=1,              # ... else at the close this many sessions before the near expiry
    turnover=1e9, optvol=50000, price=50.0,
    debit=.25,                # net debit of one position, of equity
    max_open=2,
    skew=.0, call_skew=.0, spread=.02,     # half the quoted spread of liquid weeklies (OpenD 2026-10-23: 4-5%)
    e_mode='implied',         # the report's move implied by the day's IV over the pre-report base ('hist': median past move)
)


_WEX = {}


def week_expiry_on_or_after(days, i):
    """Index of the last session of the ISO week of session i."""
    key = (len(days), str(days[0]))
    if key not in _WEX:
        from studies.alfredo_holguin.replicate import week_expiries
        _WEX[key] = week_expiries(days)
    return int(_WEX[key][i])


class Karl:
    id, name = 'karl_domm', 'Karl Domm'
    reports = HERE / 'reports'
    rounds = HERE / 'notes' / 'rounds'

    def __init__(self):
        self._A = None

    def data(self):
        if self._A is None:
            A = panels.arrays('us')
            F = A['F']
            codes = [str(c) for c in A['codes']]
            A['codes_s'] = codes
            A['iv'] = P.load_panel('iv', 'iv', A['days'], codes, .01)
            ov = P.load_panel('stat', 'option_volume', A['days'], codes)
            A['optvol20'] = S.rolling(ov, 20, 'mean')
            A['earn'] = P.earnings(set(codes))
            A['fac'] = F.raw / F.c                                   # raw / adjusted: strikes are raw prices
            self._A = A
        return self._A

    def events(self, A, cfg):
        """[(reaction index, code index, entry index, near expiry index, far expiry index, e)] -- e the median
        absolute move of the name's earlier earnings (6% with fewer than two)."""
        days, c = A['days'], A['close']
        out = []
        for j, code in enumerate(A['codes_s']):
            evs = A['earn'].get(code, [])
            moves = P.earnings_moves(days, c, j, evs)
            for date, pub in evs:
                r = P.reaction_day(days, date, pub)
                if r is None or r - cfg['lead'] < 1 or r >= len(days):
                    continue
                d = r - cfg['lead']
                # near: the last weekly expiry strictly before the report's own day (BEFORE: before the reaction
                # session; AFTER: on or before the report day)
                rep = r if pub == 'BEFORE' else r - 1
                fe = week_expiry_on_or_after(days, r)
                ne = week_expiry_on_or_after(days, rep)
                if ne >= (r if pub == 'BEFORE' else rep + 1) or ne == fe:     # the report's week: go back a week
                    k = ne
                    while k > 0 and week_expiry_on_or_after(days, k - 1) == ne:
                        k -= 1
                    ne = k - 1 if k > 0 else -1
                if ne <= d or ne < 0:
                    continue
                past = [m for i, m in moves if i < d]
                e = float(np.median(past)) if len(past) >= 2 else .06
                out.append((r, j, d, ne, fe, e))
        return sorted(out, key=lambda x: x[2])

    def base_vol(self, A, j, r, d):
        """The name's vol without the report: the median IV of sessions r-45 .. r-30 (the 30-day IV then does not
        hold this report), known on any day d >= r-30; NaN if missing."""
        lo, hi = max(r - 45, 0), min(r - 30, d)
        x = A['iv'][lo:hi + 1, j]
        x = x[np.isfinite(x)]
        return float(np.median(x)) if len(x) else float('nan')

    def implied_e(self, cfg, atm, base, e_hist):
        """The report's one-day move implied by the day's 30-day IV over the base vol (OpenD's IV is a 30-day
        number): e^2 = (IV^2 - base^2) x 30/365; at least half the historical median move."""
        if cfg.get('e_mode', 'implied') == 'hist' or not np.isfinite(base):
            return e_hist * cfg.get('e_mult', 1.0)          # the market's event move over the median one
        e2 = max(atm * atm - base * base, 0.0) * 30 / 365
        return max(math.sqrt(e2), .5 * e_hist)

    def price_legs(self, A, cfg, j, i, Kc, Kp, ne, fe, e, r, S_=None, atm=None, base=None):
        """Model prices per share of (near call, near put, far call, far put) at session i's close."""
        days = A['days']
        S_ = S_ if S_ is not None else float(A['F'].raw[i, j])
        atm = atm if atm is not None else float(A['iv'][i, j])
        if cfg.get('v2'):
            return self.v2_legs(A, cfg, j, i, Kc, Kp, ne, fe, e, r, S_, atm, base)
        if not np.isfinite(atm):
            atm = base if base is not None and np.isfinite(base) else .4
        if base is None or not np.isfinite(base) or cfg.get('e_mode', 'implied') == 'hist':
            ev_left = (e * cfg.get('e_mult', 1.0)) ** 2 if i < r else 0.0
            sv = (e * cfg.get('strip_mult', cfg.get('e_mult', 1.0))) ** 2 if i < r else 0.0   # R11: what the 30-day
            b = math.sqrt(max(atm * atm - sv / (30 / 365), (.5 * atm) ** 2)) if sv else atm   # IV loses to the report
        else:
            et = self.implied_e(cfg, atm, base, e) if i < r else 0.0
            ev_left, b = et * et, base
        out = []
        for k, (K, put) in enumerate(((Kc, False), (Kp, True), (Kc, False), (Kp, True))):
            exp = ne if k < 2 else fe
            T = P.years(days[i], days[exp])
            if i >= exp:
                out.append(max(K - S_, 0.0) if put else max(S_ - K, 0.0))
                continue
            ev = ev_left if (k >= 2 and i < r) else 0.0
            v = P.vol_for(S_, K, T, b, put, cfg['skew'], cfg['call_skew'], earn_var=ev, base_atm=b)
            out.append(P.bs(S_, K, T, v, put))
        return out

    def v2_legs(self, A, cfg, j, i, Kc, Kp, ne, fe, e, r, S_, atm, base):
        """v2 (studies/trader_options/notes/SIM_V2_PREREG_CN.md): the report's variance read off the name's past
        IV drops (the historical move squared with fewer than two), the 30-day IV without it as the base, a smile."""
        import datetime as dt_
        days = A['days']
        if not np.isfinite(atm):
            atm = base if base is not None and np.isfinite(base) else .4
        rx = A.setdefault('_rx', {}).get(j)
        if rx is None:
            rx = A['_rx'][j] = P.reactions(days, A['earn'].get(A['codes_s'][j], []))
        E = P.implied_event_var(A['iv'], j, rx, i, e * e)
        near = i < r and (dt_.date.fromisoformat(str(days[r])[:10]) - dt_.date.fromisoformat(str(days[i])[:10])).days <= 30
        out = []
        for k, (K, put) in enumerate(((Kc, False), (Kp, True), (Kc, False), (Kp, True))):
            exp = ne if k < 2 else fe
            if i >= exp:
                out.append(max(K - S_, 0.0) if put else max(S_ - K, 0.0))
                continue
            T = P.years(days[i], days[exp])
            v = P.vol_v2(S_, K, T, atm, put, E, near, i < r <= exp, cfg.get('k', .05))
            out.append(P.bs(S_, K, T, v, put))
        return out

    def leg_spread(self, cfg, legs):
        """The position's half spread: cfg['spread'], or under v2 each leg's tick-floored one weighted by its value."""
        if not cfg.get('v2'):
            return cfg['spread']
        w = [cfg['ratio'], cfg['ratio'], 1.0, 1.0]
        q = [legs[2], legs[3], legs[0], legs[1]]
        tot = sum(a * b for a, b in zip(w, q))
        if tot <= 0:
            return cfg['spread']
        return sum(a * b * P.half_spread(b, cfg['spread']) for a, b in zip(w, q)) / tot * cfg.get('spread_x', 1)

    def value(self, legs, ratio):
        nc, npt, fc, fp = legs
        return ratio * (fc + fp) - (nc + npt)

    def simulate(self, cfg, start, end, placebo=None, audit=False):
        A = self.data()
        F = A['F']
        days = A['days']
        raw, iv = F.raw, A['iv']
        d0, d1 = int(np.searchsorted(days, start)), int(np.searchsorted(days, end, side='right'))
        evs = [e for e in self.events(A, cfg) if d0 <= e[2] < d1]
        by_day = {}
        for e in evs:
            by_day.setdefault(e[2], []).append(e)
        with np.errstate(invalid='ignore'):
            ok = (F.to20 >= cfg['turnover']) & (F.raw >= cfg['price']) & (A['optvol20'] >= cfg['optvol'])
        ok = lag(ok)
        cash, pos, trades, curve = 1.0, [], [], []
        eq_prev = 1.0
        spr = cfg['spread']
        for d in range(d0, d1):
            # --- manage open positions at the close ---
            keep, mark = [], 0.0
            for p in pos:
                j = p['j']
                legs = self.price_legs(A, cfg, j, d, p['Kc'], p['Kp'], p['ne'], p['fe'], p['e'], p['r'], base=p['base'])
                v = self.value(legs, cfg['ratio'])
                exit_ = None
                if cfg.get('take_intraday') and d > p['d']:     # a resting take-profit order: the day's high / low
                    hit = None                                  # would have lifted the position to the target
                    for x in (F.h[d, j], F.l[d, j]):
                        xr = float(x) * float(A['fac'][d, j])
                        if not np.isfinite(xr):
                            continue
                        lx = self.price_legs(A, cfg, j, d, p['Kc'], p['Kp'], p['ne'], p['fe'], p['e'], p['r'],
                                             S_=xr, base=p['base'])
                        if self.value(lx, cfg['ratio']) >= (1 + cfg['take']) * p['debit']:
                            hit = lx
                            break
                    if hit is not None:
                        nc, npt, fc, fp = hit
                        gross = cfg['ratio'] * (fc + fp) + (nc + npt)
                        got = (1 + cfg['take']) * p['debit'] - p.get('spr', spr) * gross \
                            - 6 * P.COMMISSION / 100 * (cfg['ratio'] + 1) / 3
                        cash += p['n'] * got
                        trades.append(dict(code=A['codes_s'][j], entry=str(days[p['d']]), exit=str(days[d]),
                                           why='take', debit=p['debit_paid'], got=got, ret=got / p['debit_paid'] - 1,
                                           Kc=p['Kc'], Kp=p['Kp'], S0=p['S0'], near=str(days[p['ne']]),
                                           far=str(days[p['fe']]), report=str(days[p['r']])))
                        continue
                if v >= (1 + cfg['take']) * p['debit']:
                    exit_ = 'take'
                elif cfg.get('stop') and v <= (1 - cfg['stop']) * p['debit']:
                    exit_ = 'stop'
                elif d >= p['ne'] - cfg['exit_lead'] or d >= p['r'] - 1:
                    exit_ = 'time'
                if exit_:
                    nc, npt, fc, fp = legs
                    sp_ = p.get('spr', spr)
                    got = cfg['ratio'] * (fc + fp) * (1 - sp_) - (nc + npt) * (1 + sp_) \
                        - 6 * P.COMMISSION / 100 * (cfg['ratio'] + 1) / 3
                    cash += p['n'] * got
                    trades.append(dict(code=A['codes_s'][j], entry=str(days[p['d']]), exit=str(days[d]),
                                       why=exit_, debit=p['debit_paid'], got=got, ret=got / p['debit_paid'] - 1,
                                       Kc=p['Kc'], Kp=p['Kp'], S0=p['S0'], near=str(days[p['ne']]),
                                       far=str(days[p['fe']]), report=str(days[p['r']])))
                    continue
                mark += p['n'] * v
                keep.append(p)
            pos = keep
            # --- new positions at the close ---
            elig = [e for e in by_day.get(d, []) if ok[d, e[1]] and np.isfinite(iv[d, e[1]]) and np.isfinite(raw[d, e[1]])]

            def ratio_(e):                                    # the report priced cheap: the move the day's IV implies
                b = self.base_vol(A, e[1], e[0], d)           # over the base vol, against the name's median move
                a = float(iv[d, e[1]])
                if not (np.isfinite(b) and np.isfinite(a)) or e[5] <= 0:
                    return 9.0
                return math.sqrt(max(a * a - b * b, 0.0) * 30 / 365) / e[5]

            def select(es):
                es = sorted(es, key=lambda e: -A['optvol20'][d - 1, e[1]])
                if cfg.get('cheap'):
                    es = [e for e in es if ratio_(e) <= cfg['cheap']]
                    if cfg.get('rank_cheap'):
                        es.sort(key=ratio_)
                return es
            if placebo is not None and cfg.get('placebo_events'):    # R5 on: as many of the day's genuine,
                n_ = len(select(elig))                              # eligible earnings events, drawn at random
                cand = [elig[k] for k in placebo.permutation(len(elig))][:n_]
            elif placebo is not None:                 # the first rounds' placebo: a random name carrying this event
                pool = np.flatnonzero(ok[d] & np.isfinite(iv[d]) & np.isfinite(raw[d]))
                cand = [(e[0], int(placebo.choice(pool)), e[2], e[3], e[4], e[5]) for e in select(elig)] \
                    if len(pool) else []
            else:
                cand = select(elig)
            eq = cash + mark
            for r, j, dd, ne, fe, e in cand:
                if len(pos) >= cfg['max_open'] or any(p['j'] == j for p in pos):
                    continue
                S0, atm = float(raw[d, j]), float(iv[d, j])
                base = self.base_vol(A, j, r, d)
                T = P.years(days[d], days[fe])
                et = self.implied_e(cfg, atm, base, e)
                b = base if np.isfinite(base) and cfg.get('e_mode', 'implied') != 'hist' else atm
                far_vol = math.sqrt(max(b * b * T + et * et, 1e-9) / T)
                mv = far_vol * math.sqrt(T)
                g = 2.5 if S0 >= 100 else 1.0 if S0 >= 25 else .5
                Kc = math.ceil(S0 * (1 + cfg['width'] * mv) / g) * g
                Kp = math.floor(S0 * (1 - cfg['width'] * mv) / g) * g
                if Kp <= 0:
                    continue
                legs = self.price_legs(A, cfg, j, d, Kc, Kp, ne, fe, e, r, base=base)
                nc, npt, fc, fp = legs
                sp_ = self.leg_spread(cfg, legs)
                paid = cfg['ratio'] * (fc + fp) * (1 + sp_) - (nc + npt) * (1 - sp_) \
                    + 6 * P.COMMISSION / 100 * (cfg['ratio'] + 1) / 3
                if paid <= 0:
                    continue
                n = cfg['debit'] * eq / paid
                if n * paid > cash:                                   # no margin borrowing for debits
                    n = max(cash, 0) / paid
                if n <= 0:
                    continue
                cash -= n * paid
                v = self.value(legs, cfg['ratio'])
                mark += n * v
                pos.append(dict(j=j, d=d, r=r, ne=ne, fe=fe, e=e, Kc=Kc, Kp=Kp, n=n, debit=v, debit_paid=paid, S0=S0, base=base, spr=sp_))
            curve.append(cash + mark)
        for p in pos:
            trades.append(dict(code=A['codes_s'][p['j']], entry=str(days[p['d']]), exit='open', why='open',
                               debit=p['debit_paid'], got=None, ret=None))
        return np.array(curve), days[d0:d1], trades

    # ----- his statements -----
    LINE = re.compile(r'^\s*(?:(\d{1,2})[/.](\d{2}))?\s*(Sale|Purchase)\s+(Short Sale|Cover Short)?\s*([A-Z]{1,5})\s+'
                      r'(?:(\d{2})/(\d{2})/(\d{4}))?\s*(CALL|PUT)\s*(.*?)\s*\(?(\d+\.\d{4})\)?\s+'
                      r'(\d+\.\d{2,4})\s+(\d+\.\d{2})\s+\(?([\d,]+\.\d{2})\)?')
    PENDING = re.compile(r'^\s*(Sale|Purchase)\s+(Short Sale|Cover Short)?\s*([A-Z]{1,5})\s+(CALL|PUT)\s+[A-Z][A-Z .&]*?\s+'
                         r'([\d.,]+)\s+([\d.,]+)\s+(\d{2})/(\d{2})\s+([\d.,]+)')

    @staticmethod
    def _num(s):
        return float(s.replace(',', ''))

    @classmethod
    def parse_statement(cls, text, year=2025):
        """Option transactions of one Schwab statement's text (pdftotext or OCR): [{date, sym, action, cp, strike,
        exp ('' when the line has none), qty (signed contracts), px}].  A line without a date takes the previous
        line's.  The contract count is checked against the dollar amount and fee (an OCR misread such as 42 for 12
        is replaced by the count the amount implies).  The statement's dates are settlement dates ("Date column
        represents the Settlement/Process date"); options settle T+1, so `date` is the trading day before and
        `settle` keeps the printed one.  Month-end trades pending settlement are not read here: they reappear in the
        next statement's transactions."""
        out, last = [], None
        hol = ['2025-01-01', '2025-01-09', '2025-01-20', '2025-02-17', '2025-04-18', '2025-05-26', '2025-06-19',
               '2025-07-04', '2025-09-01', '2025-11-27', '2025-12-25', '2026-01-01']
        trade_day = lambda s: str(np.busday_offset(np.datetime64(s), -1, roll='backward', holidays=hol))
        acts = {('Sale', 'Short Sale'): 'open_short', ('Purchase', 'Cover Short'): 'cover',
                ('Purchase', None): 'buy', ('Sale', None): 'sell'}
        for line in text.splitlines():
            line = line.replace('—', '-')
            m = cls.LINE.match(line)
            if m:
                mo, dd, kind, tag, sym, em, ed, ey, cp, desc, q, px, fee, amt = m.groups()
                ks = re.search(r'\$\s?([\d.,]+)', desc)
                k = ks.group(1) if ks else '0'                       # an OCR line can lose the strike
                if mo:
                    last = f'{year}-{int(mo):02d}-{dd}'
                if last is None:
                    continue
                qty, p_, f_, a_ = cls._num(q), cls._num(px), cls._num(fee), cls._num(amt)
                if p_ > 0:
                    implied = (a_ + f_) / (p_ * 100) if kind == 'Sale' else (a_ - f_) / (p_ * 100)
                    if abs(implied - qty) > .5 and abs(implied - round(implied)) < .1:
                        qty = float(round(implied))
                action = acts[(kind, tag)]
                out.append(dict(date=trade_day(last), settle=last, sym=sym, action=action, cp=cp, strike=cls._num(k),
                                exp=f'{ey}-{em}-{ed}' if ey else '', qty=qty if action in ('buy', 'cover') else -qty,
                                px=p_))
        return out

    @staticmethod
    def positions(rows):
        """His ratio calendars from ledger rows: grouped by name and strikes, opened by the short near legs (or the
        first row), closed when every leg is flat.  Each: open / close day, net debit and proceeds in dollars,
        return on the debit."""
        out, book = [], {}
        rows = [dict(r) for r in rows]
        for r in rows:                              # a strike lost by OCR: the same leg's strike on another row of
            if not float(r['strike']):              # the position, else flagged for replay to infer
                same = [x for x in rows if x['sym'] == r['sym'] and x['cp'] == r['cp'] and float(x['strike'])
                        and abs((dt.date.fromisoformat(x['date']) - dt.date.fromisoformat(r['date'])).days) <= 25]
                if same:
                    r['strike'] = same[0]['strike']
                else:
                    r['strike_missing'] = True
        for r in sorted(rows, key=lambda x: x['date']):
            key = (r['sym'], tuple(sorted({float(x['strike']) for x in rows if x['sym'] == r['sym']
                                           and abs((dt.date.fromisoformat(x['date']) -
                                                    dt.date.fromisoformat(r['date'])).days) <= 25})))
            p = book.setdefault(key, dict(sym=r['sym'], open=r['date'], legs={}, debit=0.0, proceeds=0.0, rows=[]))
            cash = -float(r['qty']) * float(r['px']) * 100
            leg = (r['cp'], float(r['strike']), 'near' if r['action'] in ('open_short', 'cover') else 'far')
            p['legs'][leg] = p['legs'].get(leg, 0.0) + float(r['qty'])
            if r['action'] in ('open_short', 'buy'):
                p['debit'] -= cash
            else:
                p['proceeds'] += cash
            p['rows'].append(r)
            if all(abs(v) < 1e-9 for v in p['legs'].values()):
                p['close'] = r['date']
                p['ret'] = p['proceeds'] / p['debit'] - 1 if p['debit'] > 0 else None
                out.append(p)
                del book[key]
        return out, list(book.values())

    def his_replay(self, cfg, positions):
        """Layer 2: each of his positions priced by our model -- debit at his open day's close, value at his close
        day's close ('close') and at the better of that day's high / low ('best', a resting take-profit's bound),
        spread paid both ways.  Strikes and expiries are his; the report is the first earnings reaction after the
        open."""
        A = self.data()
        days = A['days'].astype(str)
        ci = {c[3:]: i for i, c in enumerate(A['codes_s'])}
        F, spr, ratio = A['F'], cfg['spread'], cfg['ratio']
        out = []
        for p in positions:
            j = ci.get(p['sym'])
            i0, i1 = int(np.searchsorted(days, p['open'])), int(np.searchsorted(days, p['close']))
            calls = sorted({k for (cp, k, _) in p['legs'] if cp == 'CALL' and k > 0})
            puts = sorted({k for (cp, k, _) in p['legs'] if cp == 'PUT' and k > 0})
            exps = {r['exp'] for r in p['rows'] if r['exp']}
            inferred = False
            if j is not None and days[i0] == p['open'] and (calls or puts) and not (calls and puts):
                S0_ = float(F.raw[i0, j])                     # a strike OCR lost: the other leg mirrored in logs
                calls, puts = calls or [round(S0_ * S0_ / puts[0], 1)], puts or [round(S0_ * S0_ / calls[0], 1)]
                inferred = True
            if j is None or not calls or not puts or days[i0] != p['open']:
                out.append(dict(sym=p['sym'], open=p['open'], his=p.get('ret'), ours=None))
                continue
            evs = [P.reaction_day(A['days'], d, pb) for d, pb in A['earn'].get('US.' + p['sym'], [])]
            r = next((x for x in sorted(e for e in evs if e is not None) if x > i0), None)
            r_inferred = r is None or r - i0 > 15             # a report the calendar misses (AMAT, HD in 2025-08):
            if r_inferred:                                    # his reports come 10-13 sessions after his entries
                r = min(i0 + 11, len(days) - 1)
            if len(exps) >= 2:
                ne, fe = (int(np.searchsorted(days, x, side='right')) - 1 for x in sorted(exps)[:2])
            else:
                fe = week_expiry_on_or_after(A['days'], r)
                ne = week_expiry_on_or_after(A['days'], max(fe - 5, i0))
                if ne >= r or ne == fe:
                    ne = week_expiry_on_or_after(A['days'], max(fe - 7, i0))
            moves = P.earnings_moves(A['days'], A['close'], j, A['earn'].get('US.' + p['sym'], []))
            past = [m for k, m in moves if k < i0]
            e = float(np.median(past)) if len(past) >= 2 else .06
            base = self.base_vol(A, j, r, i0)
            Kc, Kp = calls[0], puts[0]
            nc, npt, fc, fp = self.price_legs(A, cfg, j, i0, Kc, Kp, ne, fe, e, r, base=base)
            paid = ratio * (fc + fp) * (1 + spr) - (nc + npt) * (1 - spr)
            vals = {}
            for nm, Sx in (('close', None), ('high', F.h[i1, j] * A['fac'][i1, j]), ('low', F.l[i1, j] * A['fac'][i1, j])):
                lg = self.price_legs(A, cfg, j, i1, Kc, Kp, ne, fe, e, r, S_=None if Sx is None else float(Sx), base=base)
                vals[nm] = ratio * (lg[2] + lg[3]) * (1 - spr) - (lg[0] + lg[1]) * (1 + spr)
            path = None                                       # his window under a resting take-profit at `take`
            for i in range(i0 + 1, i1 + 1):
                for Sx in (F.h[i, j] * A['fac'][i, j], F.l[i, j] * A['fac'][i, j]):
                    lg = self.price_legs(A, cfg, j, i, Kc, Kp, ne, fe, e, r, S_=float(Sx), base=base)
                    if ratio * (lg[2] + lg[3]) * (1 - spr) - (lg[0] + lg[1]) * (1 + spr) >= (1 + cfg['take']) * paid:
                        path = cfg['take']
                        break
                if path is not None:
                    break
            out.append(dict(sym=p['sym'], open=p['open'], close=p['close'], his=p.get('ret'),
                            ours=vals['close'] / paid - 1, best=max(vals['high'], vals['low']) / paid - 1,
                            path=vals['close'] / paid - 1 if path is None else path, tp_hit=path is not None,
                            inferred=inferred or r_inferred, paid=paid, Kc=Kc, Kp=Kp, near=days[ne], far=days[fe],
                            report=days[r]))
        return out

    @staticmethod
    def his_trades():
        with (HERE / 'notes' / 'trades_karl.csv').open(encoding='utf-8') as f:
            return list(csv.DictReader(f))

    def calibrate(self):
        """Model prices of his legs at his fill days (the close of that day) against his fills."""
        A = self.data()
        days = A['days']
        ci = {c[3:]: i for i, c in enumerate(A['codes_s'])}
        rows = []
        for t in self.his_trades():
            j = ci.get(t['sym'])
            i = int(np.searchsorted(days, t['date']))
            if j is None or i >= len(days) or str(days[i]) != t['date'] or not t['exp']:
                continue
            S_ = float(A['F'].raw[i, j])
            atm = float(A['iv'][i, j])
            e_i = int(np.searchsorted(days, t['exp']))
            evs = [P.reaction_day(days, dd, pb) for dd, pb in A['earn'].get('US.' + t['sym'], [])]
            r = next((x for x in evs if x is not None and x > i), None)
            moves = P.earnings_moves(days, A['close'], j, A['earn'].get('US.' + t['sym'], []))
            past = [m for k, m in moves if k < i]
            e = float(np.median(past)) if len(past) >= 2 else .06
            K, put = float(t['strike']), t['cp'] == 'PUT'
            T = P.years(t['date'], t['exp'])
            spans = r is not None and r <= e_i
            ev = e * e if spans else 0.0
            base = math.sqrt(max(atm * atm - (e * e if r is not None and r - i <= 21 else 0) / (30 / 365),
                                 (.5 * atm) ** 2))
            v = P.vol_for(S_, K, T, atm, put, 0.0, 0.0, earn_var=ev, base_atm=base)
            m = P.bs(S_, K, T, v, put)
            rows.append(dict(sym=t['sym'], date=t['date'], cp=t['cp'], K=K, exp=t['exp'], S=S_, iv=atm, e=e,
                             spans=spans, fill=float(t['px']), model=m, ratio=float(t['px']) / m if m > 0 else None))
        for r_ in rows:
            print(r_['sym'], r_['date'], r_['cp'], r_['K'], r_['exp'], f"S {r_['S']:.2f} iv {r_['iv']:.3f} e {r_['e']:.3f}",
                  'far' if r_['spans'] else 'near', f"fill {r_['fill']:.2f} model {r_['model']:.2f} ratio {r_['ratio']}")
        rat = [r_['ratio'] for r_ in rows if r_['ratio']]
        print('median fill / model', np.median(rat) if rat else None, 'n', len(rat))
        self.reports.mkdir(parents=True, exist_ok=True)
        (self.reports / 'calibrate.json').write_text(json.dumps(rows, indent=1, default=float), encoding='utf-8')

    def evaluate(self, cfg, seg, draws=0):
        curve, dates, tr = self.simulate(cfg, *seg)
        st = stats(curve, dates, tr)
        if draws:
            rng = np.random.default_rng(1)
            pl = np.array([self.simulate(cfg, *seg, placebo=rng)[0][-1] - 1 for _ in range(draws)])
            st['placebo'] = dict(median=float(np.median(pl)), rank=float((pl < st['total']).mean()), draws=draws)
        his = {(t['sym'], t['date']) for t in self.his_trades() if t['action'] in ('open_short',)}
        ours = {(t['code'][3:], t['entry']) for t in tr}
        his_names = {s for s, _ in his}
        st['his_hit'] = dict(positions=len(his), same_name_within_5d=sum(
            any(s == a and abs((dt.date.fromisoformat(d) - dt.date.fromisoformat(b)).days) <= 7 for a, b in ours)
            for s, d in his), names=len(his_names))
        return st, tr

    def config(self, report, key='chosen'):
        if not report:
            return dict(DRAFT)
        res = json.loads((self.reports / report).read_text(encoding='utf-8'))
        return res['chosen_config'] if key == 'chosen' else res['configs'][key]

    HIS_2025 = dict(ret=3.2138, per_year=25, win=.84, hold=3.8)   # his statements: 25 closed positions in 2025

    def goal(self, st):
        """2025 log gap to his statements' +321.4%, and positions a year / win rate / days held within +-30% of his
        25 positions; goal = -max(year gap / 0.3, worst behaviour deviation / 0.3)."""
        h = self.HIS_2025
        y = abs(math.log(max(1 + st['by_year'].get('2025', -1), 1e-6) / (1 + h['ret']))) / .3
        ours = dict(per_year=st['trades'] / 2, win=st['win'], hold=st['hold'])
        dv = {k: (abs(ours[k] / h[k] - 1) if ours[k] else 1.0) for k in ('per_year', 'win', 'hold')}
        b = max(dv.values()) / .3
        return dict(goal=-max(y, b), goal_years=y, goal_behav=b, goal_parts=dict(year=y * .3, behaviour=dv),
                    meets=bool(max(y, b) <= 1 and st['total'] > st.get('placebo', {}).get('median', 9)))

    def round(self, name):
        spec = json.loads((self.rounds / f'{name}.json').read_text(encoding='utf-8'))
        report, key = spec['base']
        base = dict(self.config(report, key), **spec.get('base_change', {}))   # a declared correction of the base
        cfgs = {k: dict(base, **v) for k, v in spec['candidates'].items()}
        ref = spec['ref']
        cfgs[ref] = base
        res = {}
        for k, cfg in cfgs.items():
            st, _ = self.evaluate(cfg, SELECT, draws=spec.get('draws', 20))
            if spec.get('objective') == 'goal':
                st.update(self.goal(st))
            res[k] = st
            show(name, k, st)
        target = spec.get('target', 3.2138)          # his 2025 statements
        if spec.get('objective') == 'goal':           # docs/prompts/new_styles_return_goal.md (R3 on)
            r = res[ref]
            ok = [k for k in cfgs if k == ref or (res[k]['total'] > res[k]['placebo']['median']
                  and res[k]['goal_years'] <= max(r['goal_years'], 1.0) + 1e-9
                  and res[k]['goal_behav'] <= max(r['goal_behav'], 1.0) + 1e-9)]
            best = max(ok, key=lambda k: res[k]['goal'])
            gates, objective = ['placebo', 'years', 'behav'], 'goal'
        else:
            ok = [k for k in cfgs if k == ref or res[k]['total'] > res[k]['placebo']['median']]
            best = min(ok, key=lambda k: abs(math.log(max(1 + res[k]['by_year'].get('2025', -1), 1e-6) / (1 + target))))
            gates, objective = ['placebo'], f'2025 closest to {target}'
        out = dict(name=name, base=spec['base'], configs=cfgs, full=res, chosen=best, chosen_config=cfgs[best],
                   gates=gates, objective=objective)
        self.reports.mkdir(parents=True, exist_ok=True)
        (self.reports / f'{name.lower()}.json').write_text(json.dumps(out, indent=1, default=float), encoding='utf-8')
        print(name, 'chosen', best, flush=True)
        return out

    def validate(self, report, key='chosen', draws=50):
        cfg = self.config(report, key)
        out = {'report': report, 'config': cfg}
        for nm, seg in (('select', SELECT), ('validate', VALIDATE), ('window', WINDOW)):
            st, tr = self.evaluate(cfg, seg, draws=draws)
            out[nm] = st
            show('VALIDATE', nm, st)
        (self.reports / f'validate_{report.replace(".json", "")}_{key}.json').write_text(
            json.dumps(out, indent=1, default=float), encoding='utf-8')
        return out


def stats(curve, dates, tr):
    curve = np.asarray(curve)
    peak = np.maximum.accumulate(np.concatenate([[1.0], curve]))[1:]
    by_year, prev = {}, 1.0
    for y in sorted({str(d)[:4] for d in dates}):
        idx = [i for i, d in enumerate(dates) if str(d)[:4] == y]
        by_year[y] = float(curve[idx[-1]] / prev - 1)
        prev = curve[idx[-1]]
    closed = [t for t in tr if t['ret'] is not None]
    rets = [t['ret'] for t in closed]
    return dict(total=float(curve[-1] - 1), maxdd=float(np.max(1 - curve / peak)), by_year=by_year,
                trades=len(closed), win=float(np.mean([r > 0 for r in rets])) if rets else None,
                avg_ret=float(np.mean(rets)) if rets else None,
                hold=float(np.mean([np.busday_count(t['entry'], t['exit']) for t in closed])) if closed else None,
                why={w: sum(t['why'] == w for t in closed) for w in ('take', 'stop', 'time')})


def show(tag, k, st):
    pl = st.get('placebo', {})
    print(tag, k, f"total {st['total']:+.3f} dd {st['maxdd']:.2f}", {a: round(b, 3) for a, b in st['by_year'].items()},
          f"placebo {pl.get('median', float('nan')):+.3f} rank {pl.get('rank', float('nan')):.2f}",
          f"n {st['trades']} win {st['win']} avg {st['avg_ret']} hold {st['hold']} why {st['why']} his {st.get('his_hit')}",
          flush=True)


STUDY = Karl()

if __name__ == '__main__':
    a = sys.argv[1]
    if a == 'calibrate':
        STUDY.calibrate()
    elif a == 'round':
        STUDY.round(sys.argv[2])
    elif a == 'validate':
        STUDY.validate(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else 'chosen', int(sys.argv[4]) if len(sys.argv) > 4 else 50)
