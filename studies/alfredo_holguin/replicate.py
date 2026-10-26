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

import csv
import datetime as dt
import json
import math
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

    def eligible(self, A, cfg):
        F = A['F']
        with np.errstate(invalid='ignore'):
            m = ((F.to20 >= cfg['turnover']) & (F.raw >= cfg['price']) & (A['optvol20'] >= cfg['optvol'])
                 & np.isfinite(A['iv']) & (A['iv'] > 0) & (A['trend'] >= cfg['trend']) & np.isfinite(F.atr14))
            if cfg.get('trend_max') is not None:
                m &= A['trend'] <= cfg['trend_max']
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
            held = {p['j'] for p in pos}
            coll = sum(p['m'] * p['n'] for p in pos)
            cand = []
            for j in np.flatnonzero(elig[d]):
                if j in held or not np.isfinite(o[d, j]):
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
                atm = float(iv[d - 1, j])
                base = math.sqrt(max(atm * atm - ev / (30 / 365), (.5 * atm) ** 2)) if has_e else atm
                v = P.vol_for(S0, K, T, atm, True, cfg['skew'], earn_var=ev, base_atm=base)
                prem = P.bs(S0, K, T, v, True) * (1 - cfg['spread']) - P.COMMISSION / 100
                if prem <= .01:
                    continue
                pr = -prem / K if cfg['priority'] == 'yield' else -atm
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
                    trades.append(self.trade(A, p, d, pay, 'expiry'))
                    continue
                T = P.years(days[d], days[p['e']])
                ev = p['ev'] if any(d < i <= p['e'] for i in A['earn_idx'].get(j, [])) else 0.0
                atm = float(iv[d, j]) if np.isfinite(iv[d, j]) else p['base']
                v = P.vol_for(S_, p['K'], T, atm, True, cfg['skew'], earn_var=ev, base_atm=atm if not ev else p['base'])
                val = P.bs(S_, p['K'], T, v, True)
                if cfg.get('take') and val * (1 + cfg['spread']) + P.COMMISSION / 100 <= cfg['take'] * p['prem']:
                    pay = val * (1 + cfg['spread']) + P.COMMISSION / 100
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
        base = self.config(report, key)
        cfgs = {k: dict(base, **v) for k, v in spec['candidates'].items()}
        ref = spec['ref']
        cfgs[ref] = base
        res = {}
        for k, cfg in cfgs.items():
            st, _ = self.evaluate(cfg, SELECT, draws=spec.get('draws', 20))
            res[k] = st
            show(name, k, st)
        ok = [k for k in cfgs if k == ref or (res[k]['total'] > res[k]['placebo']['median']
                                               and res[k]['fidelity']['his_hit'] >= res[ref]['fidelity']['his_hit']
                                               * spec.get('hit_floor', 0.9))]
        target = spec.get('target', 1.002)            # his USIC 2025
        best = min(ok, key=lambda k: abs(math.log((1 + res[k]['total']) / (1 + target))))
        out = dict(name=name, base=spec['base'], configs=cfgs, full=res, chosen=best, chosen_config=cfgs[best],
                   gates=['placebo', f"his_hit >= {spec.get('hit_floor', 0.9)} x ref"], objective=f'closest to {target}')
        self.reports.mkdir(parents=True, exist_ok=True)
        (self.reports / f'{name.lower()}.json').write_text(json.dumps(out, indent=1, default=float), encoding='utf-8')
        print(name, 'chosen', best, flush=True)
        return out

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
