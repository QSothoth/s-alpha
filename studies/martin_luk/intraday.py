"""R2: replicate Martin Luk's long book on local 5-minute bars (notes/PREREG_R2.md).

    /opt/futu-opend/venv/bin/python -m studies.martin_luk.intraday select
    /opt/futu-opend/venv/bin/python -m studies.martin_luk.intraday validate I?

Bars are dense arrays (stock, day, 78 five-minute slots 09:35..16:00); daily OHLC is aggregated from them.
Signals use only the previous day's close and today's bars up to the decision bar.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass, field, replace
import json
import sys

import numpy as np

from . import luk

SOURCES = ['preopen-s20-k5-raw-a', 'preopen-s20-k5-raw-b', 'preopen-us-k5-raw', 'p3-k5-validation-raw']
ETFS = {'SPY', 'QQQ', 'IWM'}
FIRST_DAY = '2023-05-01'
NB = 78
SEGMENTS = {'select': ('2024-01-02', '2024-12-31'), 'validate': ('2025-01-02', '2026-09-24')}
OUT = luk.ROOT / 'studies' / 'martin_luk' / 'reports'


def files():
    best = {}
    for src in SOURCES:
        for f in sorted((luk.ROOT / 'data' / src / 'k5').glob('*.csv')):
            if f.stat().st_size and (f.stem not in best or f.stat().st_size > best[f.stem].stat().st_size):
                best[f.stem] = f
    return best


def load5():
    path = luk.CACHE / 'k5.npz'
    if not path.exists():
        src = files()
        days = set()
        for f in src.values():                       # pass 1: trading days only (keeps memory flat)
            with open(f, newline='') as fh:
                next(fh)
                days.update(line[:10] for line in fh if line[:10] >= FIRST_DAY)
        days = np.array(sorted(days))
        syms = np.array(sorted(src))
        di = {d: i for i, d in enumerate(days)}
        arr = np.full((6, len(syms), len(days), NB), np.nan, np.float32)
        for s, sym in enumerate(syms):               # pass 2: one file at a time
            dd, bb, vals = [], [], []
            with open(src[sym], newline='') as fh:
                rd = csv.reader(fh)
                next(rd)
                for t, *v in rd:
                    if t[:10] < FIRST_DAY:
                        continue
                    b = (int(t[11:13]) * 60 + int(t[14:16]) - 570) // 5 - 1
                    if 0 <= b < NB:
                        dd.append(di[t[:10]])
                        bb.append(b)
                        vals.append(v)
            if vals:
                arr[:, s, np.array(dd), np.array(bb)] = np.array(vals, np.float32).T
        np.savez_compressed(path, days=days, syms=syms, arr=arr)
    z = np.load(path)
    return z['days'], z['syms'], z['arr']


def daily(arr):
    """(D, S) daily open/high/low/close/turnover from (6, S, D, 78) bars."""
    o5, h5, l5, c5, _, t5 = arr
    with np.errstate(all='ignore'):
        valid = ~np.isnan(c5)
        first = np.argmax(valid, axis=2)
        last = NB - 1 - np.argmax(valid[:, :, ::-1], axis=2)
        any_ = valid.any(axis=2)
        take = lambda x, idx: np.take_along_axis(x, idx[..., None], axis=2)[..., 0]
        out = dict(open=take(o5, first), high=np.nanmax(h5, axis=2), low=np.nanmin(l5, axis=2),
                   close=take(c5, last), turnover=np.nansum(t5, axis=2))
    for k in out:
        out[k] = np.where(any_, out[k], np.nan).T.astype(float)
    return out


@dataclass(frozen=True)
class Cfg:
    breakout: bool = True
    pullback: bool = True
    ep: bool = True
    market_filter: bool = False
    dd_halving: bool = False
    risk: float = .005
    max_position: float = .35
    max_gross: float = 2.0
    margin_rate: float = .07
    cost: float = .001
    adr_min: float = 5.0
    mom: float = .30
    gap: float = .10
    stop_cap: float = .05
    trims: tuple = (3, 6, 9, 12)
    trim_frac: float = .15
    min_price: float = 5.0
    min_turnover: float = 20e6
    burst: bool = False            # J1 potent continuation
    ep_vol: float = 0.0            # J2: first-bar turnover >= ep_vol x 20d average daily turnover
    first_pullback: bool = False   # J3
    progressive: bool = False      # J5
    confirm_close: bool = False    # causal variant: buy the close of the first 5-min bar closing above the trigger
    short_bd: bool = False         # K1 breakdown below the prior low
    short_br: bool = False         # K2 failed bounce at a falling EMA21
    borrow_rate: float = .05
    ep_cap: float = 0.0            # R6: fixed stop cap for EP entries (0 = use min(stop_cap, 0.5 x ADR))
    min_stop: float = 0.0          # R8 sensitivity: skip entries whose stop is narrower than this fraction


CANDIDATES = {
    'I1': dict(pullback=False, ep=False),
    'I2': dict(breakout=False, ep=False),
    'I3': dict(breakout=False, pullback=False),
    'I4': dict(),
    'I5': dict(market_filter=True, dd_halving=True),
    'J1': dict(breakout=False, pullback=False, ep=False, burst=True),
    'J2': dict(breakout=False, pullback=False, ep_vol=.05),
    'J3': dict(breakout=False, pullback=False, ep=False, first_pullback=True),
    'J4': dict(pullback=False, ep_vol=.05, burst=True, first_pullback=True),
    'J5': dict(pullback=False, ep_vol=.05, burst=True, first_pullback=True, progressive=True),
}
SEGMENTS['full'] = ('2024-01-02', '2026-09-24')
_J4 = CANDIDATES['J4']
CANDIDATES.update({
    'K1': dict(breakout=False, pullback=False, ep=False, short_bd=True),
    'K2': dict(breakout=False, pullback=False, ep=False, short_br=True),
    'K3': dict(breakout=False, pullback=False, ep=False, short_bd=True, short_br=True),
    'K4': dict(_J4, short_bd=True, short_br=True),
    'K5': dict(_J4, short_bd=True, short_br=True, confirm_close=True),
    'L1': dict(_J4, ep_cap=.05),
    'L2': dict(_J4, adr_min=4.0),
    'L3': dict(_J4, ep_cap=.05, adr_min=4.0),
    'L4': dict(_J4, ep_cap=.05, adr_min=4.0, confirm_close=True),
    'L5': dict(_J4, ep_cap=.05, adr_min=4.0, risk=.01, max_gross=2.8),
})


def prepare():
    days, syms, arr = load5()
    stock = np.array([s not in ETFS for s in syms])
    dly = daily(arr)
    c = dly['close']
    e9, e21, e50 = luk.ema(c, 9), luk.ema(c, 21), luk.ema(c, 50)
    adr = luk.rolling_mean(dly['high'] / dly['low'] - 1, 20) * 100
    to20 = luk.rolling_mean(dly['turnover'], 20)
    with np.errstate(invalid='ignore', divide='ignore'):
        mom = np.fmax(np.fmax(c / luk.lag(c, 21), c / luk.lag(c, 63)), c / luk.lag(c, 126)) - 1
        r63 = c / luk.lag(c, 63) - 1
    qqq = int(np.flatnonzero(syms == 'QQQ')[0])
    qe = luk.ema(c[:, [qqq]], 21)[:, 0]
    return dict(days=days, syms=syms, arr=arr, stock=stock, d=dly, e9=e9, e21=e21, e50=e50, adr=adr,
                to20=to20, mom=mom, r63=r63, qqq_up=c[:, qqq] > qe)


def masks(P, cfg):
    d = P['d']
    with np.errstate(invalid='ignore'):
        tradeable = P['stock'][None, :] & (d['close'] >= cfg.min_price) & (P['to20'] >= cfg.min_turnover)
        leader = (tradeable & (P['adr'] >= cfg.adr_min) & (P['mom'] >= cfg.mom)
                  & (P['e9'] > P['e21']) & (P['e21'] > P['e50']))
        rng = d['high'] / d['low'] - 1
        inside = (d['high'] <= luk.lag(d['high'])) & (d['low'] >= luk.lag(d['low']))
        setup = leader & (inside | (rng * 100 <= .5 * P['adr'])) & (d['close'] >= P['e21'])
        r1 = d['close'] / luk.lag(d['close']) - 1
        pos_in_range = (d['close'] - d['low']) / (d['high'] - d['low'])
        burst = (tradeable & (P['adr'] >= cfg.adr_min) & (r1 >= np.fmax(.08, 1.5 * P['adr'] / 100))
                 & (pos_in_range >= .75) & (d['turnover'] >= 2 * luk.lag(P['to20'])))
        hh10 = np.full_like(d['high'], np.nan)
        for k in range(9, len(hh10)):
            hh10[k] = np.nanmax(d['high'][k - 9:k + 1], axis=0)
        fp = leader & (hh10 >= P['e21'] * (1 + 3 * P['adr'] / 100)) & (d['close'] > P['e21'])
        with np.errstate(invalid='ignore', divide='ignore'):
            c = d['close']
            mom_dn = P['mom_dn'] if 'mom_dn' in P else (
                np.fmin(np.fmin(c / luk.lag(c, 21), c / luk.lag(c, 63)), c / luk.lag(c, 126)) - 1)
        laggard = (tradeable & (P['adr'] >= cfg.adr_min) & (mom_dn <= -cfg.mom)
                   & (P['e9'] < P['e21']) & (P['e21'] < P['e50']))
        sbd = laggard & (inside | (rng * 100 <= .5 * P['adr'])) & (d['close'] <= P['e21'])
    if '_allow' in P:                       # R10: only names his scan selected (point-in-time, whole market)
        allow = P['_allow']
        tradeable, leader, setup, burst, fp = (x & allow for x in (tradeable, leader, setup, burst, fp))
    P['_burst'], P['_fp'], P['_lag'], P['_sbd'] = burst, fp, laggard, sbd
    return tradeable, leader, setup


def first_entry(bars, kind, prev, confirm_close=False):
    """(bar, fill, lod) of the first trigger today for one stock, or None. prev: dict of yesterday's levels."""
    o5, h5, l5, c5 = bars
    if np.isnan(o5[0]):
        return None
    if kind in ('bo', 'ep', 'burst'):
        if kind == 'ep' or o5[0] > prev['high']:
            trig, b0 = h5[0], 1
        else:
            trig, b0 = prev['high'], 0
        for b in range(b0, NB):
            if confirm_close:
                if not np.isnan(c5[b]) and c5[b] >= trig:
                    return b, c5[b], np.nanmin(l5[:b + 1])
            elif not np.isnan(h5[b]) and h5[b] >= trig:
                return b, max(trig, o5[b]), np.nanmin(l5[:b + 1])
        return None
    lod = np.inf
    pierced = np.zeros(len(prev['ema']), bool)
    for b in range(NB):
        if np.isnan(c5[b]):
            continue
        lod = min(lod, l5[b])
        pierced |= lod < prev['ema']
        if (pierced & (c5[b] > prev['ema'])).any():
            return b, c5[b], lod
    return None


def first_short(bars, kind, prev, confirm_close=False):
    """Short trigger on negated prices: (bar, fill, hod) or None. kind 'sbd' mirrors 'bo', 'sbr' mirrors 'pb'."""
    o5, h5, l5, c5 = bars
    neg = (-o5, -l5, -h5, -c5)
    if kind == 'sbd':
        e = first_entry(neg, 'bo', {'high': -prev['low']}, confirm_close)
    else:
        e = first_entry(neg, 'pb', {'ema': np.array([-prev['e21']])}, confirm_close)
    return None if e is None else (e[0], -e[1], -e[2])


@dataclass
class Pos:
    j: int
    kind: str
    d0: int
    b0: int
    fill: float
    stop: float
    shares0: float
    shares: float
    trims: int = 0
    above9: bool = False
    cash_in: float = 0.0
    cash_out: float = 0.0
    why: str = ''
    side: int = 1
    below9: bool = False


def simulate(P, cfg, start, end, placebo=None, keep=None):
    days, syms, (o5, h5, l5, c5, _, _) = P['days'], P['syms'], P['arr']
    C = P['d']['close']
    tradeable, leader, setup = masks(P, cfg)
    d0, d1 = int(np.searchsorted(days, start)), int(np.searchsorted(days, end, side='right'))
    cash, pos, trades, curve, peak = 1.0, {}, [], [], 1.0
    rng = placebo
    keep = np.ones(len(syms), bool) if keep is None else keep

    def close_px(j, d):
        k = d
        while k >= 0 and np.isnan(C[k, j]):
            k -= 1
        return C[k, j] if k >= 0 else 0.0

    def mark(d):
        return cash + sum(q.side * q.shares * close_px(q.j, d) for q in pos.values())

    def gross_at(d):
        return sum(q.shares * close_px(q.j, d) for q in pos.values())

    def sell(q, sh, px, d, why):
        """Reduce a position: sell longs, buy back shorts."""
        nonlocal cash
        sh = min(sh, q.shares)
        if q.side > 0:
            got = sh * px * (1 - cfg.cost)
            cash += got
            q.cash_out += got
        else:
            paid = sh * px * (1 + cfg.cost)
            cash -= paid
            q.cash_out += paid
        q.shares -= sh
        if q.shares <= 1e-12:
            pos.pop(q.j, None)
            R = q.shares0 * abs(q.fill - q.stop)
            pnl = (q.cash_out - q.cash_in) * q.side
            trades.append(dict(j=q.j, code=str(syms[q.j]), kind=q.kind, side=q.side, entry=str(days[q.d0]),
                               bar=q.b0, exit=str(days[d]), days=d - q.d0, fill=q.fill, stop=q.stop,
                               risk_pct=abs(q.fill - q.stop) / q.fill, pnl=pnl, r=pnl / R,
                               ret=pnl / (q.shares0 * q.fill), why=why))

    def manage(q, d, b_from):
        if q.side < 0:
            return manage_short(q, d, b_from)
        j = q.j
        R = q.fill - q.stop
        for b in range(b_from, NB):
            o, h, l = o5[j, d, b], h5[j, d, b], l5[j, d, b]
            if np.isnan(o):
                continue
            if o <= q.stop:
                sell(q, q.shares, o, d, 'gap_stop' if b == 0 else 'stop')
                return
            while q.trims < len(cfg.trims) and o >= q.fill + cfg.trims[q.trims] * R:
                sell(q, cfg.trim_frac * q.shares0, o, d, 'trim')
                q.trims += 1
            if l <= q.stop:
                sell(q, q.shares, q.stop, d, 'stop')
                return
            while q.trims < len(cfg.trims) and h >= q.fill + cfg.trims[q.trims] * R:
                sell(q, cfg.trim_frac * q.shares0, q.fill + cfg.trims[q.trims] * R, d, 'trim')
                q.trims += 1
            if q.j not in pos:
                return

    def manage_short(q, d, b_from):
        j = q.j
        R = q.stop - q.fill
        for b in range(b_from, NB):
            o, h, l = o5[j, d, b], h5[j, d, b], l5[j, d, b]
            if np.isnan(o):
                continue
            if o >= q.stop:
                sell(q, q.shares, o, d, 'gap_stop' if b == 0 else 'stop')
                return
            while q.trims < len(cfg.trims) and o <= q.fill - cfg.trims[q.trims] * R:
                sell(q, cfg.trim_frac * q.shares0, o, d, 'trim')
                q.trims += 1
            if h >= q.stop:
                sell(q, q.shares, q.stop, d, 'stop')
                return
            while q.trims < len(cfg.trims) and l <= q.fill - cfg.trims[q.trims] * R:
                sell(q, cfg.trim_frac * q.shares0, q.fill - cfg.trims[q.trims] * R, d, 'trim')
                q.trims += 1
            if q.j not in pos:
                return

    for d in range(d0, d1):
        equity = mark(d - 1)
        gross = gross_at(d - 1)
        frac = cfg.risk * (.5 if cfg.dd_halving and equity < .9 * peak else 1)
        if cfg.progressive:
            recent = sum(t['r'] for t in trades[-20:])
            frac = cfg.risk * (.5 if equity < .9 * peak else 2 if recent > 5 else 1)
        for q in list(pos.values()):
            manage(q, d, 0)
        events = []
        if not cfg.market_filter or P['qqq_up'][d - 1]:
            prio = np.nan_to_num(-P['r63'][d - 1], nan=0.0)
            kinds = [('bo', setup[d - 1]) if cfg.breakout else None, ('pb', leader[d - 1]) if cfg.pullback else None,
                     ('ep', tradeable[d - 1]) if (cfg.ep or cfg.ep_vol) else None,
                     ('burst', P['_burst'][d - 1]) if cfg.burst else None,
                     ('fp', P['_fp'][d - 1]) if cfg.first_pullback else None,
                     ('sbd', P['_sbd'][d - 1]) if cfg.short_bd else None,
                     ('sbr', P['_lag'][d - 1]) if cfg.short_br else None]
            for kind, ok in filter(None, kinds):
                for j in np.flatnonzero(ok & keep):
                    if kind == 'ep' and not (o5[j, d, 0] / C[d - 1, j] - 1 >= cfg.gap):
                        continue
                    if kind == 'ep' and cfg.ep_vol and not (P['arr'][5, j, d, 0] >= cfg.ep_vol * P['to20'][d - 1, j]):
                        continue
                    if kind in ('sbd', 'sbr'):
                        e = first_short((o5[j, d], h5[j, d], l5[j, d], c5[j, d]), kind,
                                        dict(low=P['d']['low'][d - 1, j], e21=P['e21'][d - 1, j]), cfg.confirm_close)
                        if e is None:
                            continue
                        b, fill, hod = e
                        cap = min(cfg.stop_cap, .005 * P['adr'][d - 1, j])
                        stop = hod if (hod - fill) / fill <= cap else h5[j, d, b]
                        if not (max(0, cfg.min_stop) < (stop - fill) / fill <= cap):
                            continue
                        events.append((b, -prio[j], j, float(fill), float(stop), kind))
                        continue
                    if kind == 'fp':
                        lv = np.array([P['e21'][d - 1, j]])
                    else:
                        lv = np.array([P['e9'][d - 1, j], P['e21'][d - 1, j], P['e50'][d - 1, j]])
                    prev = dict(high=P['d']['high'][d - 1, j], ema=lv)
                    e = first_entry((o5[j, d], h5[j, d], l5[j, d], c5[j, d]), 'pb' if kind == 'fp' else kind, prev,
                                    cfg.confirm_close)
                    if e is None:
                        continue
                    b, fill, lod = e
                    cap = min(cfg.stop_cap, .005 * P['adr'][d - 1, j])
                    if kind == 'ep' and cfg.ep_cap:
                        cap = cfg.ep_cap
                    stop = lod if (fill - lod) / fill <= cap else l5[j, d, b]
                    if not (max(0, cfg.min_stop) < (fill - stop) / fill <= cap):
                        continue
                    events.append((b, prio[j], j, float(fill), float(stop), kind))
        events.sort(key=lambda x: (x[0], x[1]))
        if rng is not None:
            events = _placebo(events, P, d, leader, tradeable, keep, rng)
        for b, _, j, fill, stop, kind in events:
            if j in pos:
                continue
            value = min(frac * equity / (abs(fill - stop) / fill), cfg.max_position * equity, cfg.max_gross * equity - gross)
            if value <= .001 * equity:
                continue
            side = -1 if kind in ('sbd', 'sbr') else 1
            flow = value * (1 + cfg.cost) if side > 0 else value * (1 - cfg.cost)
            cash -= side * flow
            gross += value
            q = Pos(j, kind, d, b, fill, stop, value / fill, value / fill, cash_in=flow, side=side)
            pos[j] = q
            manage(q, d, b + 1)
        for q in list(pos.values()):
            j = q.j
            if np.isnan(C[d, j]):
                continue
            if q.side < 0:
                if q.d0 == d and C[d, j] > q.fill:
                    sell(q, q.shares, C[d, j], d, 'nft')
                elif q.d0 != d and q.below9 and C[d, j] > P['e9'][d, j]:
                    sell(q, q.shares, C[d, j], d, 'ema9')
                else:
                    q.below9 = q.below9 or C[d, j] < P['e9'][d, j]
                continue
            if q.d0 == d:
                if C[d, j] < q.fill:
                    sell(q, q.shares, C[d, j], d, 'nft')
                    continue
            elif q.above9 and C[d, j] < P['e9'][d, j]:
                sell(q, q.shares, C[d, j], d, 'ema9')
                continue
            q.above9 = q.above9 or C[d, j] > P['e9'][d, j]
        longs = sum(q.shares * close_px(q.j, d) for q in pos.values() if q.side > 0)
        shorts = sum(q.shares * close_px(q.j, d) for q in pos.values() if q.side < 0)
        eq = mark(d)
        if longs > eq > 0:
            cash -= (longs - eq) * cfg.margin_rate / 252
        cash -= shorts * cfg.borrow_rate / 252
        eq = mark(d)
        peak = max(peak, eq)
        curve.append(eq)
    for q in list(pos.values()):
        sell(q, q.shares, close_px(q.j, d1 - 1), d1 - 1, 'end')
    return np.array(curve), days[d0:d1], trades


def _placebo(events, P, d, leader, tradeable, keep, rng):
    o5, c5 = P['arr'][0], P['arr'][3]
    out = []
    for b, prio, j, fill, stop, kind in events:
        base = (tradeable[d - 1] if kind in ('ep', 'burst') else P['_lag'][d - 1] if kind in ('sbd', 'sbr')
                else leader[d - 1])
        pool = np.flatnonzero(base & keep & ~np.isnan(c5[:, d, b]))
        if not len(pool):
            continue
        k = int(rng.choice(pool))
        px = float(c5[k, d, b])
        side = -1 if kind in ('sbd', 'sbr') else 1
        out.append((b, prio, k, px, px * (1 - side * abs(fill - stop) / fill), kind))
    return out


def benchmark(P, cfg, start, end, keep=None):
    tradeable, _, _ = masks(P, cfg)
    C = P['d']['close']
    days = P['days']
    keep = np.ones(len(P['syms']), bool) if keep is None else keep
    d0, d1 = int(np.searchsorted(days, start)), int(np.searchsorted(days, end, side='right'))
    with np.errstate(invalid='ignore'):
        r = C[d0:d1] / C[d0 - 1:d1 - 1] - 1
        m = tradeable[d0 - 1:d1 - 1] & keep & ~np.isnan(r)
        ew = np.where(m, r, 0).sum(1) / np.maximum(m.sum(1), 1)
    return float(np.prod(1 + ew) - 1)


def evaluate(P, cand, seg, **over):
    cfg = replace(Cfg(), **CANDIDATES[cand], **over)
    start, end = SEGMENTS[seg] if seg in SEGMENTS else seg
    curve, dates, trades = simulate(P, cfg, start, end)
    s = luk.stats(curve, dates, trades)
    s['bench'] = benchmark(P, cfg, start, end)
    s['calmar'] = s['cagr'] / s['maxdd'] if s['maxdd'] > 0 else np.nan
    return s, trades, cfg


def main(argv):
    P = prepare()
    seg = argv[0]
    cands = list(CANDIDATES) if seg == 'select' else [argv[1]]
    rows = {}
    for cand in cands:
        s, trades, _ = evaluate(P, cand, seg)
        rows[cand] = s
        from .r1 import fmt
        print(cand, fmt(s), 'by_year', {k: round(v, 3) for k, v in s['by_year'].items()}, flush=True)
    OUT.mkdir(exist_ok=True)
    (OUT / f'r2_{seg}.json').write_text(json.dumps(rows, indent=1, default=float))


if __name__ == '__main__' and sys.argv[1:2] != ['check']:
    main(sys.argv[1:])


def check(P, cand, seg, n=200, **over):
    """Pre-registered checks: bootstrap CI of per-trade R, benchmark, placebo percentile, top-10 removal."""
    s, trades, cfg = evaluate(P, cand, seg, **over)
    start, end = SEGMENTS[seg] if seg in SEGMENTS else seg
    r = np.array([t['r'] for t in trades])
    rng = np.random.default_rng(0)
    boots = rng.choice(r, (2000, len(r))).mean(axis=1)
    pr = np.random.default_rng(1)
    pl = np.array([simulate(P, cfg, start, end, placebo=pr)[0][-1] - 1 for _ in range(n)])
    return dict(total=float(s['total']), cagr=float(s['cagr']), maxdd=float(s['maxdd']), bench=float(s['bench']),
                trades=len(trades), win=float(s['win']), avg_win=float(s['avg_win']), avg_loss=float(s['avg_loss']),
                exp_r=float(r.mean()), ci=[float(np.percentile(boots, 2.5)), float(np.percentile(boots, 97.5))],
                median_r=float(np.median(r)), placebo_median=float(np.median(pl)), placebo_p90=float(np.percentile(pl, 90)),
                placebo_rank=float((pl < s['total']).mean()), pnl_ex_top10=float(sum(sorted(t['pnl'] for t in trades)[:-10])),
                by_year={k: float(v) for k, v in s['by_year'].items()})


if __name__ == '__main__' and sys.argv[1:2] == ['check']:
    out = check(prepare(), sys.argv[2], sys.argv[3])
    print(json.dumps(out, indent=1))
    (OUT / f'r2_check_{sys.argv[2]}_{sys.argv[3]}.json').write_text(json.dumps(out, indent=1))


HK1M = ['watch-hk1m-holdout-2025h2-v1', 'watch-hk1m-train-v1', 'watch-hk1m-valid-v1']


def _hk_slot(hhmm):
    """5-minute slot for an HK 1-minute bar end time (09:30 auction -> first bar, closing auction -> last)."""
    if hhmm <= 575:
        return 0
    if hhmm <= 720:
        return (hhmm - 571) // 5
    if hhmm < 781:
        return 30
    return min(30 + (hhmm - 781) // 5, 65)


def load_hk5(days):
    """(syms, arr) for the HK 1-minute files aggregated to 5 minutes on the given daily calendar."""
    path = luk.CACHE / 'hk5.npz'
    if not path.exists():
        import gzip
        di = {d: i for i, d in enumerate(days)}
        codes = set()
        for name in HK1M:
            with gzip.open(luk.ROOT / 'data' / name / 'bars_1m.csv.gz', 'rt') as fh:
                next(fh)
                codes.update(line.split(',', 1)[0] for line in fh)
        syms = np.array(sorted(codes))
        si = {s: i for i, s in enumerate(syms)}
        arr = np.full((6, len(syms), len(days), NB), np.nan, np.float32)
        for name in HK1M:
            with gzip.open(luk.ROOT / 'data' / name / 'bars_1m.csv.gz', 'rt') as fh:
                rd = csv.reader(fh)
                next(rd)
                for code, t, o, h, l, c, v, to, _ in rd:
                    d = di.get(t[:10])
                    if d is None:
                        continue
                    s, b = si[code], _hk_slot(int(t[11:13]) * 60 + int(t[14:16]))
                    o, h, l, c, v, to = float(o), float(h), float(l), float(c), float(v), float(to)
                    if np.isnan(arr[0, s, d, b]):
                        arr[:, s, d, b] = (o, h, l, c, v, to)
                    else:
                        cell = arr[:, s, d, b]
                        cell[1] = max(cell[1], h)
                        cell[2] = min(cell[2], l)
                        cell[3] = c
                        cell[4] += v
                        cell[5] += to
        np.savez_compressed(path, syms=syms, arr=arr)
    z = np.load(path)
    return z['syms'], z['arr']


def prepare_hk():
    """P like prepare(), but daily bars/indicators from the HK trend-scan panel and 5-minute bars from 1-minute files."""
    p = luk.load('hk')
    days = p['dates']
    syms, arr = load_hk5(days)
    have = np.isin(syms, p['codes'])
    syms, arr = syms[have], arr[:, have]
    idx = np.array([int(np.flatnonzero(p['codes'] == s)[0]) for s in syms])
    dly = {k: p[k][:, idx].astype(float) for k in ('open', 'high', 'low', 'close', 'turnover')}
    agg = daily(arr)                      # same price basis as the fills on days with intraday bars
    for k in ('open', 'high', 'low', 'close'):
        dly[k] = np.where(np.isnan(agg[k]), dly[k], agg[k])
    c = dly['close']
    with np.errstate(invalid='ignore', divide='ignore'):
        mom = np.fmax(np.fmax(c / luk.lag(c, 21), c / luk.lag(c, 63)), c / luk.lag(c, 126)) - 1
        r63 = c / luk.lag(c, 63) - 1
    return dict(days=days, syms=syms, arr=arr, stock=np.ones(len(syms), bool), d=dly,
                e9=luk.ema(c, 9), e21=luk.ema(c, 21), e50=luk.ema(c, 50),
                adr=luk.rolling_mean(dly['high'] / dly['low'] - 1, 20) * 100,
                to20=luk.rolling_mean(dly['turnover'], 20), mom=mom, r63=r63, qqq_up=np.ones(len(days), bool))


HK_CFG = dict(min_price=1.0, min_turnover=50e6, cost=.002)


K30 = luk.ROOT / 'data' / 'p5-k30-validation-raw' / 'k30'


def prepare_k30():
    """P for the 145 P5 names: daily history from the US trend-scan panel, 30-minute bars in slots 0..12 (R7)."""
    p = luk.load('us')
    days = p['dates']
    di = {d: i for i, d in enumerate(days)}
    syms, cols = [], []
    for f in sorted(K30.glob('*.json')):
        code = 'US.' + f.stem
        k = np.flatnonzero(p['codes'] == code)
        if len(k):
            syms.append(f.stem)
            cols.append(int(k[0]))
    arr = np.full((6, len(syms), len(days), NB), np.nan, np.float32)
    for s, sym in enumerate(syms):
        for row in json.loads((K30 / f'{sym}.json').read_text()):
            t = row['time_key']
            d = di.get(t[:10])
            if d is None:
                continue
            b = (int(t[11:13]) * 60 + int(t[14:16]) - 600) // 30          # 10:00 bar end -> slot 0
            if 0 <= b < 13:
                arr[:, s, d, b] = (row['open'], row['high'], row['low'], row['close'], row['volume'], row['turnover'])
    idx = np.array(cols)
    dly = {k: p[k][:, idx].astype(float) for k in ('open', 'high', 'low', 'close', 'turnover')}
    agg = daily(arr)
    for k in ('open', 'high', 'low', 'close'):
        dly[k] = np.where(np.isnan(agg[k]), dly[k], agg[k])
    c = dly['close']
    with np.errstate(invalid='ignore', divide='ignore'):
        mom = np.fmax(np.fmax(c / luk.lag(c, 21), c / luk.lag(c, 63)), c / luk.lag(c, 126)) - 1
        r63 = c / luk.lag(c, 63) - 1
    return dict(days=days, syms=np.array(syms), arr=arr, stock=np.ones(len(syms), bool), d=dly,
                e9=luk.ema(c, 9), e21=luk.ema(c, 21), e50=luk.ema(c, 50),
                adr=luk.rolling_mean(dly['high'] / dly['low'] - 1, 20) * 100,
                to20=luk.rolling_mean(dly['turnover'], 20), mom=mom, r63=r63, qqq_up=np.ones(len(days), bool))


_L3 = CANDIDATES['L3']
CANDIDATES.update({
    'M1': dict(_L3),
    'M2': dict(_L3, confirm_close=True),
    'M3': dict(CANDIDATES['K3']),
    'M4': dict(_L3, short_bd=True, short_br=True),
    'M5': dict(_L3, short_bd=True, short_br=True, confirm_close=True),
})
SEGMENTS['k30'] = ('2026-06-09', '2026-09-25')


R8_DIR = luk.ROOT / 'data' / 'martin-luk-k5-r8'
R8_DAILY = luk.ROOT / 'data' / 'martin-luk-universe-us' / 'us'
R8_FIRST = '2023-06-01'


def _daily_for(codes):
    """Ratio-adjusted daily panel for a few codes, streamed from the broad R8 daily file (memory stays small)."""
    from studies.trend_breakout import panel
    want, raw = set(codes), {}
    for code, day, values in panel.read_bars(R8_DAILY / 'bars_raw.csv.gz'):
        if code in want and day >= R8_FIRST:
            raw.setdefault(code, {})[day] = values
    return panel.build(raw, panel.read_actions(R8_DAILY / 'actions.csv.gz'))


def _k5_into(arr, s, path, di):
    import gzip
    opener = gzip.open if str(path).endswith('.gz') else open
    with opener(path, 'rt', newline='') as fh:
        rd = csv.reader(fh)
        next(rd)
        dd, bb, vals = [], [], []
        for t, *v in rd:
            d = di.get(t[:10])
            if d is None:
                continue
            b = (int(t[11:13]) * 60 + int(t[14:16]) - 570) // 5 - 1
            if 0 <= b < NB:
                dd.append(d)
                bb.append(b)
                vals.append(v[:6])
    if vals:
        arr[:, s, np.array(dd), np.array(bb)] = np.array(vals, np.float32).T


def prepare_r8(which):
    """R8 panels: 'new' = the 200 sampled names, 'all' = those plus the 84 earlier names (5-minute bars),
    daily indicators from the broad daily panel; days with bars use the 5-minute aggregate."""
    plan = json.loads((R8_DIR / 'sample.json').read_text())
    paths = {c: R8_DIR / f'{c[3:]}.csv.gz' for c in plan['picked'] if (R8_DIR / f'{c[3:]}.csv.gz').exists()}
    if which == 'all':
        paths.update({'US.' + s: f for s, f in files().items() if s not in ETFS})
    p = _daily_for(paths)
    codes = [str(c) for c in p['codes']]
    days = p['dates']
    di = {d: i for i, d in enumerate(days)}
    arr = np.full((6, len(codes), len(days), NB), np.nan, np.float32)
    for s, code in enumerate(codes):
        _k5_into(arr, s, paths[code], di)
    dly = {k: p[k].astype(float) for k in ('open', 'high', 'low', 'close', 'turnover')}
    agg = daily(arr)
    for k in ('open', 'high', 'low', 'close'):
        dly[k] = np.where(np.isnan(agg[k]), dly[k], agg[k])
    c = dly['close']
    with np.errstate(invalid='ignore', divide='ignore'):
        mom = np.fmax(np.fmax(c / luk.lag(c, 21), c / luk.lag(c, 63)), c / luk.lag(c, 126)) - 1
        r63 = c / luk.lag(c, 63) - 1
    return dict(days=days, syms=np.array([x[3:] for x in codes]), arr=arr, stock=np.ones(len(codes), bool), d=dly,
                e9=luk.ema(c, 9), e21=luk.ema(c, 21), e50=luk.ema(c, 50),
                adr=luk.rolling_mean(dly['high'] / dly['low'] - 1, 20) * 100,
                to20=luk.rolling_mean(dly['turnover'], 20), mom=mom, r63=r63, qqq_up=np.ones(len(days), bool))


SEGMENTS['r8'] = ('2024-01-02', '2026-10-16')
