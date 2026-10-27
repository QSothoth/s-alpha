"""Intraday signal confidence (I3, notes/INTRADAY_I3_PREREG_CN.md): one method for any time t of the session.

1. One full-day volume model with time as an input: z = log(full day / volume so far) - log(1 / f_m(tau)), from
   features known at t (relative volume, gap, liquidity, the last 30 minutes, ADR, price, the whole market),
   quantiles q10 / q50 / q90 (VG: grouped quantile curves; VQ: linear quantile regression).
2. Scenario reruns: today's provisional bar replaced by a few possible closes (V0 as it is; M: q50 volume; A / B:
   price +-0.5 u, u = ADR x sqrt(1 - tau), half the names up and half down, crossed; VL / VH: q10 / q90 volume);
   the seven systems run on each, and the scenarios a signal appears in measure how far it is from triggering.
3. One probability model (PL: logistic; PG: grouped frequency) of "still there at the close" from those features,
   the time, the kind, the trader and the pattern class; p >= p_hi -> order, p_lo <= p < p_hi -> watch.

decide_many() reruns the systems on several rows of today at once: the entries before today are built once on the
whole panel, and for each scenario only today's entries and exit lines are rebuilt on the last L sessions, spliced
in and the account replayed (equal to a whole rebuild, tests).  Only data known at t enters: the minute bars up to
t, the daily bars before today, today's open.
"""
from __future__ import annotations

import gc
import json
import zlib
from pathlib import Path

import numpy as np

SESSIONS = {'us': (('09:30', '16:00'),), 'hk': (('09:30', '12:00'), ('13:00', '16:00')),
            'cn': (('09:30', '11:30'), ('13:00', '15:00'))}
CUTS = {'us': ('10:00', '10:30', '11:00', '11:30', '12:00', '12:30', '13:00', '13:30', '14:00', '14:30', '15:00',
               '15:30', '15:45', '15:50'),
        'hk': ('10:00', '10:30', '11:00', '11:30', '12:00', '13:30', '14:00', '14:30', '15:00', '15:30', '15:45',
               '15:50'),
        'cn': ('10:00', '10:30', '11:00', '11:30', '13:30', '14:00', '14:30', '14:45', '14:50')}
EARLY = {'us': ('10:30', '12:30'), 'hk': ('10:30', '13:30'), 'cn': ('10:30', '14:00')}
MAIN = {'us': '15:50', 'hk': '15:50', 'cn': '14:50'}
STEP = .5                      # price scenarios move STEP x u
L_TRUNC = 300                  # sessions the scenario rebuild of today's entries looks back
SCEN = ('M', 'A', 'B', 'VL', 'VH')
VFEAT = ('rvol', 'gap', 'liq', 'trend', 'adr', 'ret', 'pos', 'mkt')
QS = (.1, .5, .9)
TRADERS = ('martin_luk', 'christian_flanders', 'clement_ang', 'qullamaggie', 'oliver_kell', 'mark_minervini',
           'marios_stamatoudis')
SELL_STOP = ('跌破止损', '跳空跌破止损', '当天止损', '当天止损回补', '涨破止损回补', '跳空涨破止损回补', '按 R 分批',
             '按 R 回补一部分', '到达目标线回补')
SELL_CLOSE = ('收盘跌破跟踪线', '收盘站上跟踪线回补', '信号离场', '信号分批', '没有延续', '没有延续回补')
MODEL_PATH = Path(__file__).resolve().parent / 'reports' / 'confidence_model.json'


# ----- time -----
def minutes(hhmm):
    h, m = map(int, hhmm.split(':'))
    return h * 60 + m


def total(market):
    return sum(minutes(b) - minutes(a) for a, b in SESSIONS[market])


def elapsed(market, hhmm):
    """Trading minutes from the open to hhmm (the lunch break not counted)."""
    t = minutes(hhmm)
    return sum(min(max(t - minutes(a), 0), minutes(b) - minutes(a)) for a, b in SESSIONS[market])


def tau(market, hhmm):
    return elapsed(market, hhmm) / total(market)


def clock(market, e):
    """The clock time after e trading minutes (the end of the morning for a time in the lunch break)."""
    for a, b in SESSIONS[market]:
        n = minutes(b) - minutes(a)
        if e <= n:
            t = minutes(a) + e
            return f'{t // 60:02d}:{t % 60:02d}'
        e -= n
    return SESSIONS[market][-1][1]


def back30(market, hhmm):
    """The clock time 30 trading minutes before hhmm, or None in the first 30 minutes."""
    e = elapsed(market, hhmm) - 30
    return clock(market, e) if e > 0 else None


def side_hash(code):
    """+1 / -1: the name's price direction in scenario A (B is the opposite), fixed by the code."""
    return 1 if zlib.crc32(str(code).encode()) % 2 == 0 else -1


# ----- 1. the full-day volume model -----
def market_curve(fm, market, t):
    """f_m(tau): the market's normal share of the day's volume by time t (fm: {cut: share}), linear in tau."""
    xs = sorted((tau(market, c), v) for c, v in fm.items())
    return float(np.interp(t, [x for x, _ in xs], [v for _, v in xs]))


def vol_features(t, fm_t, v, last30, op, prev, adv, to20, adr, hi, lo, cl):
    """Feature matrix (names x VFEAT) at time fraction t of one market and moment: arrays over names (cumulative
    volume v, the last 30 minutes' volume, today's open, the previous close, 20-day mean volume / turnover / range,
    the day's high / low / last price so far).  Liquidity is relative to the median of these names, mkt is the
    names' total volume so far over their normal level."""
    with np.errstate(divide='ignore', invalid='ignore'):
        base = adv * fm_t
        rvol = np.log(v / base)
        liq = np.log(to20)
        ok = np.isfinite(liq)
        liq = liq - (np.median(liq[ok]) if ok.any() else 0.0)
        trend = np.log(np.maximum(last30, 1e-3 * v) / v)
        good = np.isfinite(rvol) & (base > 0)
        mkt = float(np.log(v[good].sum() / base[good].sum())) if good.any() else 0.0
        pos = np.where(hi > lo, (cl - lo) / (hi - lo), .5)
        X = np.column_stack([rvol, np.abs(op / prev - 1), liq, trend, np.nan_to_num(adr), cl / prev - 1, pos,
                             np.full(len(v), mkt)])
    return X


class VolumeModel:
    """VG (grouped quantile curves by cut x rvol tercile x gap) or VQ (linear quantile regression on the features
    and the features x sqrt(1 - tau)); predicts z quantiles (QS) at any tau."""

    def __init__(self, kind):
        self.kind = kind

    # VG
    def _cells(self, X, z):
        q = np.quantile(X[:, 0], [1 / 3, 2 / 3])
        g = self._group(X, q)
        cells = {}
        for b in np.unique(g):
            m = g == b
            if m.sum() >= 30:
                cells[int(b)] = np.quantile(z[m], QS).tolist()
        r = np.searchsorted(q, X[:, 0])
        rcell = {int(b): np.quantile(z[r == b], QS).tolist() for b in np.unique(r) if (r == b).sum() >= 30}
        return dict(q=q.tolist(), cells=cells, rcell=rcell, all=np.quantile(z, QS).tolist())

    @staticmethod
    def _group(X, q):
        return np.searchsorted(np.asarray(q), X[:, 0]) * 3 + np.digitize(X[:, 1], [.02, .05])

    def _vg_at(self, c, X):
        r = np.searchsorted(np.asarray(c['q']), X[:, 0])
        g = r * 3 + np.digitize(X[:, 1], [.02, .05])
        out = np.empty((len(X), len(QS)))
        for i in range(len(X)):
            out[i] = c['cells'].get(int(g[i])) or c['rcell'].get(int(r[i])) or c['all']
        return out

    # VQ
    def _design(self, X, t):
        Z = (np.nan_to_num(X) - self.mu) / self.sd
        s = np.sqrt(np.clip(1 - np.asarray(t, float), 0, 1))[:, None] * np.ones((len(X), 1))
        return np.column_stack([np.ones(len(X)), Z, s, s * Z])

    def fit(self, X, t, z, cut_tau=None):
        """X: features, t: time fraction per row, z: target; cut_tau: (VG) the grid's tau per row."""
        ok = np.all(np.isfinite(X), axis=1) & np.isfinite(z)
        X, t, z = X[ok], np.asarray(t)[ok], z[ok]
        if self.kind == 'VG':
            grid = sorted(set(np.round(cut_tau[ok], 6).tolist()))
            self.grid = grid
            self.by = [self._cells(X[np.isclose(cut_tau[ok], g)], z[np.isclose(cut_tau[ok], g)]) for g in grid]
            return self
        self.mu, self.sd = X.mean(0), X.std(0) + 1e-9
        D = self._design(X, t)
        self.beta = []
        for q in QS:
            b = np.linalg.lstsq(D, z, rcond=None)[0]
            for _ in range(60):
                r = z - D @ b
                w = np.where(r >= 0, q, 1 - q) / np.maximum(np.abs(r), 1e-3)
                b = np.linalg.solve(D.T @ (D * w[:, None]) + 1e-6 * np.eye(D.shape[1]), D.T @ (w * z))
            self.beta.append(b)
        return self

    def predict(self, X, t):
        """(names x 3) z quantiles; t a scalar or per-row time fraction."""
        t = np.broadcast_to(np.asarray(t, float), (len(X),))
        if self.kind == 'VG':
            g = np.asarray(self.grid)
            out = np.empty((len(X), len(QS)))
            for tv in np.unique(t):
                m = t == tv
                k = int(np.clip(np.searchsorted(g, tv), 1, len(g) - 1)) if len(g) > 1 else 0
                lo_, hi_ = max(k - 1, 0), k
                w = 0.0 if hi_ == lo_ else float(np.clip((tv - g[lo_]) / (g[hi_] - g[lo_]), 0, 1))
                out[m] = (1 - w) * self._vg_at(self.by[lo_], X[m]) + w * self._vg_at(self.by[hi_], X[m])
            return np.sort(out, axis=1)
        D = self._design(X, t)
        return np.sort(np.column_stack([D @ b for b in self.beta]), axis=1)

    def to_json(self):
        if self.kind == 'VG':
            return dict(kind='VG', grid=self.grid, by=self.by)
        return dict(kind='VQ', mu=self.mu.tolist(), sd=self.sd.tolist(), beta=[b.tolist() for b in self.beta])

    @classmethod
    def from_json(cls, d):
        m = cls(d['kind'])
        if m.kind == 'VG':
            m.grid = d['grid']
            m.by = [dict(c, cells={int(k): v for k, v in c['cells'].items()},
                         rcell={int(k): v for k, v in c['rcell'].items()}) for c in d['by']]
        else:
            m.mu, m.sd, m.beta = np.array(d['mu']), np.array(d['sd']), [np.array(b) for b in d['beta']]
        return m


def pinball(zq, z):
    """Mean pinball loss over QS (rows with a finite target)."""
    ok = np.isfinite(z) & np.all(np.isfinite(zq), axis=1)
    out = []
    for i, q in enumerate(QS):
        r = z[ok] - zq[ok, i]
        out.append(np.mean(np.maximum(q * r, (q - 1) * r)))
    return float(np.mean(out))


# ----- 2. scenario rows -----
def scenario_rows(P, d, prov, yq, t, names=('V0',) + SCEN):
    """{name: today's row} (fields of the panel, arrays over codes).  prov: dict(j=column indices of the names with
    a provisional bar, high, low, close (panel units), volume, turnover (so far), adr (20-day mean range), k (panel
    / raw price factor)); yq: (names x 3) quantiles of y = log(full day / so far); t: time fraction.  Names outside
    prov keep the panel's row (the true bar on the local subset days of the study; nothing else in live use)."""
    fields = ('open', 'high', 'low', 'close', 'volume', 'turnover', 'raw_close')
    j = np.asarray(prov['j'], int)
    op = P['open'][d, j].astype(float)
    hi, lo, cl = (np.asarray(prov[k], float) for k in ('high', 'low', 'close'))
    v, to = np.asarray(prov['volume'], float), np.asarray(prov['turnover'], float)
    u = np.nan_to_num(np.asarray(prov['adr'], float)) * np.sqrt(max(1 - t, 0.0))
    sgn = np.array([side_hash(c) for c in np.asarray(P['codes'])[j]])
    yq = np.maximum(np.asarray(yq, float), 0.0)
    out = {}
    for name in names:
        row = {k: P[k][d].astype(float).copy() for k in fields}
        c, m = cl.copy(), np.ones(len(j))
        if name in ('M', 'A', 'B'):
            m = np.exp(yq[:, 1])
        elif name == 'VL':
            m = np.exp(yq[:, 0])
        elif name == 'VH':
            m = np.exp(yq[:, 2])
        if name == 'A':
            c = cl * (1 + STEP * u * sgn)
        elif name == 'B':
            c = cl * (1 - STEP * u * sgn)
        row['open'][j], row['close'][j] = op, c
        row['high'][j] = np.fmax(np.fmax(hi, c), op)
        row['low'][j] = np.fmin(np.fmin(lo, c), op)
        row['volume'][j], row['turnover'][j] = v * m, to * m
        row['raw_close'][j] = c / np.asarray(prov['k'], float)
        out[name] = row
    return out


# ----- the systems on several rows of today -----
def cut_at(P, d, row=None):
    q = {k: (v[:d + 1] if isinstance(v, np.ndarray) and v.ndim and k != 'codes' else v) for k, v in P.items()}
    for k, v in (row or {}).items():
        q[k] = q[k].copy()
        q[k][d] = v
    return q


def _window(P, d, row, L):
    lo = max(0, d - L + 1)
    q = {k: (v[lo:d + 1] if isinstance(v, np.ndarray) and v.ndim and k != 'codes' else v) for k, v in P.items()}
    for k, v in (row or {}).items():
        q[k] = q[k].copy()
        q[k][-1] = v
    return q


def _day(st, px, ema, rules, entries, codes, day):
    """The day's decisions of one replay (the parts of runner.run the board uses, for the last day only)."""
    from studies.trader_replication import system as Y, systems as SY
    from studies.trader_replication.runner import WHY, WHY_SHORT
    _, _, tr = Y.simulate(px, ema, rules, entries, SY.START, day, audit=True)
    buys, sells, opened = [], [], set()
    for t in tr:
        opened.add((t['code'], t['entry']))
        ex = t['executions']
        if t['entry'] == day:
            buys.append([t['code'], t['side'], False, t['fill'], t['stop'], t['kind']])
        for e in ex:
            if e['action'] in ('entry', 'end') or e['time'][:10] != day:
                continue
            if e['action'] == 'add':
                buys.append([t['code'], t['side'], True, e['price'], None, '加码'])
                continue
            why = (WHY if t['side'] > 0 else WHY_SHORT).get(e['action'], e['action'])
            sells.append([t['code'], t['side'], e['price'], why])
    sig = {(t[0], t[1], t[5]) for t in buys if not t[2]}
    for e in entries[-1]:
        sig.add((codes[e[1]], int(e[2]), e[5]))
    return dict(sig=[list(s) for s in sorted(sig)], buys=buys, sells=sells)


def decide_many(P, d, rows, market, L=L_TRUNC, systems=None):
    """{row name: {system id: dict(sig, buys, sells)}} of day d for each of rows (today's bar per name).  The first
    row is built on the whole panel (the entries before today do not depend on today's bar); every other row
    rebuilds only today's entries and exit lines on the last L sessions and is spliced in."""
    import warnings
    from studies.trader_replication import systems as SY
    from .intraday import shared
    warnings.simplefilter('ignore', RuntimeWarning)
    names = list(rows)
    out = {n: {} for n in names}
    day = str(P['days'][d])
    codes = [str(c) for c in P['codes']]
    with np.errstate(all='ignore'):
        for x in systems or SY.all_():
            st, cfg = x.study, x.config
            with shared(cut_at(P, d, rows[names[0]]), market):
                A = st.arrays(market, mode='live')
                entries, rules, mask, pool = st.build(A, cfg)
                ema = st.ema_inputs(A, pool, rules)
            del mask, pool
            px = st.px(A)
            del A                              # prices and engine inputs retain only the arrays still needed
            if str(px['dates'][-1]) != day:
                raise RuntimeError(f'{x.id}: ends {px["dates"][-1]}, expected {day}')
            out[names[0]][x.id] = _day(st, px, ema, rules, entries, codes, day)
            for n in names[1:]:
                with shared(_window(P, d, rows[n], L), market):
                    At = st.arrays(market, mode='live')
                    et, _, _, poolt = st.build(At, cfg)
                    emat = st.ema_inputs(At, poolt, rules)
                updates = [(At[k][-1].copy(), px[k]) for k in ('open', 'high', 'low', 'close')] + \
                          [(emat[k][-1].copy(), ema[k]) for k in ema]
                today_entries = et[-1]
                del At, et, poolt, emat
                saved = []
                try:
                    for src, dst in updates:
                        saved.append((dst, dst[-1].copy() if np.ndim(dst) > 1 else dst[-1]))
                        dst[-1] = src
                    out[n][x.id] = _day(st, px, ema, rules, entries[:-1] + [today_entries], codes, day)
                finally:
                    for dst, old in reversed(saved):
                        dst[-1] = old
                del updates, today_entries
            del entries, ema, px
            gc.collect()
    return out


# ----- 3. candidates and the probability model -----
def keys_of(dec, covered=None):
    """{key: info} of one scenario's decisions: ('buy', sid, code, side, add), ('sell', sid, code, side),
    ('sig', sid, code, side, setup); info: price, setup / reason."""
    out = {}
    for sid, x in dec.items():
        for b in x['buys']:
            if covered is None or b[0] in covered:
                out[('buy', sid, b[0], int(b[1]), bool(b[2]))] = dict(price=b[3], stop=b[4], setup=b[5])
        for s in x['sells']:
            if covered is None or s[0] in covered:
                out.setdefault(('sell', sid, s[0], int(s[1])), dict(price=s[2], setup=s[3]))
        for g in x['sig']:
            if covered is None or g[0] in covered:
                out[('sig', sid, g[0], int(g[1]), g[2])] = dict(setup=g[2])
    return out


def pclass(key, setup):
    """Pattern class: 'ep' / 'entry' / 'add' / 'stop' / 'close' / 'time'."""
    if key[0] == 'sell':
        return 'stop' if setup in SELL_STOP else 'close' if setup in SELL_CLOSE else 'time'
    if key[0] == 'buy' and key[4]:
        return 'add'
    return 'ep' if 'ep' in str(setup).lower() else 'entry'


def candidates(by_scen, t, covered=None):
    """Candidate rows from {scenario: decisions}: every key seen in any of SCEN, with the scenarios it appears in
    (A / B mapped to the name's own up / down move) and its info."""
    seen = {n: keys_of(by_scen[n], covered) for n in SCEN if n in by_scen}
    allk = set().union(*[set(v) for v in seen.values()]) if seen else set()
    rows = []
    for k in sorted(allk, key=str):
        info = next(seen[n][k] for n in SCEN if n in seen and k in seen[n])
        up = 'A' if side_hash(k[2]) > 0 else 'B'
        dn = 'B' if up == 'A' else 'A'
        bits = dict(M=k in seen.get('M', {}), up=k in seen.get(up, {}), dn=k in seen.get(dn, {}),
                    VL=k in seen.get('VL', {}), VH=k in seen.get('VH', {}))
        rows.append(dict(key=k, t=t, bits=bits, setup=info.get('setup'), price=info.get('price'),
                         stop=info.get('stop'), cls=pclass(k, info.get('setup'))))
    return rows


PFEAT = ('M', 'fav', 'unfav', 'VL', 'VH', 'n', 't', 'tM', 'add', 'sell', 'sig', 'short', 'ep', 'stop', 'close') + \
        TRADERS[1:]


def pfeatures(rows):
    """Feature matrix (rows x PFEAT) of candidate rows."""
    X = np.zeros((len(rows), len(PFEAT)))
    for i, r in enumerate(rows):
        k, b = r['key'], r['bits']
        eff = k[3] * (-1 if k[0] == 'sell' else 1)          # the price direction that helps the signal
        fav, unfav = (b['up'], b['dn']) if eff > 0 else (b['dn'], b['up'])
        n = sum(b.values())
        X[i] = [b['M'], fav, unfav, b['VL'], b['VH'], n, r['t'], r['t'] * b['M'], k[0] == 'buy' and k[4],
                k[0] == 'sell', k[0] == 'sig', k[3] < 0, r['cls'] == 'ep', r['cls'] == 'stop',
                r['cls'] == 'close'] + [k[1] == s for s in TRADERS[1:]]
    return X


def tbucket(t):
    return np.digitize(np.asarray(t, float), [1 / 3, 2 / 3, .95])


class ProbModel:
    """PL: L2 logistic regression (lambda 1, standardized features); PG: grouped frequency (in M x how many of the
    other four x time bucket, (hits + 1) / (n + 2), groups under 20 fall back to in M x time bucket)."""

    def __init__(self, kind):
        self.kind = kind

    @staticmethod
    def _groups(X):
        m = X[:, 0].astype(int)
        others = X[:, 5] - X[:, 0]
        o = np.digitize(others, [1, 3])
        tb = tbucket(X[:, 6])
        return m * 100 + o * 10 + tb, m * 100 + 90 + tb

    def fit(self, X, y):
        y = np.asarray(y, float)
        if self.kind == 'PG':
            g, g2 = self._groups(X)
            self.cell, self.cell2 = {}, {}
            for gg, store, need in ((g, self.cell, 20), (g2, self.cell2, 1)):
                for b in np.unique(gg):
                    s = gg == b
                    if s.sum() >= need:
                        store[int(b)] = float((y[s].sum() + 1) / (s.sum() + 2))
            self.prior = float((y.sum() + 1) / (len(y) + 2))
            return self
        self.mu, self.sd = X.mean(0), X.std(0) + 1e-9
        Z = np.column_stack([np.ones(len(X)), (X - self.mu) / self.sd])
        R = np.eye(Z.shape[1])
        R[0, 0] = 0
        b = np.zeros(Z.shape[1])
        for _ in range(50):
            p = 1 / (1 + np.exp(-np.clip(Z @ b, -30, 30)))
            w = np.maximum(p * (1 - p), 1e-6)
            step = np.linalg.solve(Z.T @ (Z * w[:, None]) + R, Z.T @ (y - p) - R @ b)
            b = b + step
            if np.max(np.abs(step)) < 1e-8:
                break
        self.beta = b
        return self

    def predict(self, X):
        if self.kind == 'PG':
            g, g2 = self._groups(X)
            return np.array([self.cell.get(int(a), self.cell2.get(int(c), self.prior)) for a, c in zip(g, g2)])
        Z = np.column_stack([np.ones(len(X)), (X - self.mu) / self.sd])
        return 1 / (1 + np.exp(-np.clip(Z @ self.beta, -30, 30)))

    def to_json(self):
        if self.kind == 'PG':
            return dict(kind='PG', cell=self.cell, cell2=self.cell2, prior=self.prior)
        return dict(kind='PL', mu=self.mu.tolist(), sd=self.sd.tolist(), beta=self.beta.tolist(), feat=PFEAT)

    @classmethod
    def from_json(cls, d):
        m = cls(d['kind'])
        if m.kind == 'PG':
            m.cell = {int(k): v for k, v in d['cell'].items()}
            m.cell2 = {int(k): v for k, v in d['cell2'].items()}
            m.prior = d['prior']
        else:
            if tuple(d['feat']) != PFEAT:
                raise ValueError('probability model features changed')
            m.mu, m.sd, m.beta = np.array(d['mu']), np.array(d['sd']), np.array(d['beta'])
        return m


def thresholds(p, y, is_order, target_prec=.8, target_recall=.9):
    """(p_hi, p_lo) on the 0.05 grid: the smallest p_hi whose order column precision >= target_prec; the largest
    p_lo (<= p_hi) keeping >= target_recall of the true order candidates in order + watch."""
    p, y = np.asarray(p)[is_order], np.asarray(y, bool)[is_order]
    grid = np.round(np.arange(.05, 1.0, .05), 2)
    hi = next((g for g in grid if (p >= g).any() and y[p >= g].mean() >= target_prec), 1.0)
    lo = max((g for g in grid if g <= hi and y.sum() and (y & (p >= g)).sum() / y.sum() >= target_recall),
             default=0.0)
    return float(hi), float(lo)


def distance(r, u, vq=None):
    """Words for how far a candidate is from triggering / failing (r: candidate row; u: the name's remaining move
    unit, a fraction; vq: q50 full-day volume over the 20-day mean)."""
    b, k = r['bits'], r['key']
    eff = k[3] * (-1 if k[0] == 'sell' else 1)
    fav_w, unfav_w = ('涨', '跌') if eff > 0 else ('跌', '涨')
    fav, unfav = (b['up'], b['dn']) if eff > 0 else (b['dn'], b['up'])
    step = f'{STEP * u:.1%}' if u and np.isfinite(u) else '半个剩余波动'
    out = []
    if b['M']:
        out.append(f'{unfav_w} {step} 会失效' if not unfav else f'{unfav_w} {step} 仍成立')
    elif fav:
        out.append(f'再{fav_w} {step} 内可触发')
    if b['M'] and not b['VL']:
        out.append('全天量偏低（q10）会失效')
    elif not b['M'] and b['VH']:
        out.append('全天量到 q90 可触发')
    if vq is not None and np.isfinite(vq) and r['cls'] == 'ep':
        out.append(f'全天量估 {vq:.1f} 倍均量')
    if not out:
        out.append('只在个别情形出现')
    return '；'.join(out)


def daily_inputs(P, d, j):
    """20-day mean volume, turnover and range over the 20 sessions before day d (>= 10 valid, else NaN), the
    previous close and the panel / raw price factor of day d - 1, for columns j."""
    lo = max(d - 20, 0)
    with np.errstate(invalid='ignore', divide='ignore'):
        rng = (P['high'][lo:d, j] - P['low'][lo:d, j]).astype(float) / P['close'][lo:d, j]
        out = {}
        for name, a in (('adv', P['volume'][lo:d, j].astype(float)), ('to20', P['turnover'][lo:d, j].astype(float)),
                        ('adr', rng)):
            n = np.isfinite(a).sum(0)
            out[name] = np.where(n >= 10, np.nansum(a, 0) / np.maximum(n, 1), np.nan) if d >= 20 else \
                np.full(len(j), np.nan)
        out['prev'] = P['close'][d - 1, j].astype(float)
        out['fac'] = (P['close'][d - 1, j] / P['raw_close'][d - 1, j]).astype(float)
    return out


def scenario_inputs(p, market, t, vm, fms, last30=None):
    """(d, prov, yq, daily inputs, ok) of a provisional panel p (today = its last row) at time fraction t: the
    names with a bar today, their provisional bar and the q10 / q50 / q90 of y = log(full day / so far)."""
    d = len(p['days']) - 1
    j = np.flatnonzero(np.isfinite(p['close'][d]) & (p['volume'][d] > 0))
    codes = [str(c) for c in np.asarray(p['codes'])[j]]
    di = daily_inputs(p, d, j)
    v = p['volume'][d, j].astype(float)
    if last30 is None:
        if vm.kind != 'VG':
            raise ValueError(f'{vm.kind} reads the last 30 minutes of volume: pass last30')
        l30 = v                                         # VG does not read the trend
    else:
        l30 = np.array([last30.get(c, np.nan) for c in codes], float)
    f = market_curve(fms[market], market, t)
    hi, lo, cl = (p[k][d, j].astype(float) for k in ('high', 'low', 'close'))
    op = p['open'][d, j].astype(float)
    X = vol_features(t, f, v, l30, op, di['prev'], di['adv'], di['to20'], di['adr'], hi, lo, cl)
    ok = np.all(np.isfinite(X), axis=1)
    yq = vm.predict(X[ok], t) + np.log(1 / f)
    k = j[ok]
    prov = dict(j=k, high=hi[ok], low=lo[ok], close=cl[ok], volume=v[ok],
                turnover=p['turnover'][d, k].astype(float), adr=di['adr'][ok], k=di['fac'][ok])
    return d, prov, yq, di, ok


def order_keys(dec):
    """{('buy', sid, code, side, add) | ('sell', sid, code, side)} of one run's decisions."""
    return {k for k in keys_of(dec) if k[0] in ('buy', 'sell')}


def robust_board(p, market, hhmm, run_board, only=None, systems=None, model=None):
    """Early in the session (the US board an hour after the open): the board on scenario M (today's price, the q50
    full-day volume), keeping only the buys and sells that stand in every scenario (M, price +-STEP u, volume q10 /
    q90): fewer orders, chosen by one rule for every trader.  run_board: scan.run.  The rest is listed in
    r['early']['dropped'] (not orders)."""
    vm, pm, fms, th, meta = model or load_model()
    first = CUTS[market][0]
    t = tau(market, hhmm)
    if t < tau(market, first):
        raise ValueError(f'{market}: before {first} the early board is not computed')
    t = min(t, tau(market, CUTS[market][-1]))
    d, prov, yq, di, ok = scenario_inputs(p, market, t, vm, fms)
    rows = scenario_rows(p, d, prov, yq, t, SCEN)
    q = {k: (v.copy() if isinstance(v, np.ndarray) and k in rows['M'] else v) for k, v in p.items()}
    for k, v in rows['M'].items():
        q[k][d] = v
    r = run_board(market, 'live', 1, only, panel=q)
    by = decide_many(p, d, rows, market, systems=systems)
    stand = set.intersection(*(order_keys(by[n]) for n in SCEN))
    kept, dropped = 0, []
    for tr in r['traders']:
        buys, sells = [], []
        for b in tr['buys']:
            key = ('buy', tr['id'], b['code'], int(b.get('side', 1)), b['setup'] == '加码')
            (buys if key in stand else dropped).append(b if key in stand else dict(b, trader=tr['id'], kind='buy'))
        for s in tr['sells']:
            key = ('sell', tr['id'], s['code'], int(s.get('side', 1)))
            (sells if key in stand else dropped).append(s if key in stand else dict(s, trader=tr['id'], kind='sell'))
        kept += len(buys) + len(sells)
        tr['buys'], tr['sells'] = buys, sells
    r['early'] = dict(hhmm=hhmm, t=t, rule='every scenario', step=STEP, scenarios=list(SCEN), kept=kept,
                      dropped=dropped, volume_model=meta.get('volume'))
    return r


def live(p, market, hhmm, model=None, last30=None, systems=None):
    """The confidence columns of a provisional panel p (today = its last row, from a snapshot at hhmm market time):
    dict(t, hhmm, thresholds, rows = every order candidate with p, its columns ('order' / 'watch' / None) and the
    distance words), or dict(skipped=reason).  last30: volume of the last 30 trading minutes per code (only a model
    that reads the trend needs it)."""
    vm, pm, fms, th, meta = model or load_model()
    first, last = CUTS[market][0], CUTS[market][-1]
    t = tau(market, hhmm)
    if t < tau(market, first):
        return dict(skipped=f'开盘后 {elapsed(market, first)} 分钟内不估计（模型从 {first} 起）', hhmm=hhmm)
    t = min(t, tau(market, last))
    d, prov, yq, di, ok = scenario_inputs(p, market, t, vm, fms, last30)
    k = prov['j']
    rows = scenario_rows(p, d, prov, yq, t, SCEN)
    by = decide_many(p, d, rows, market, systems=systems)
    cand = [r for r in candidates(by, t, set(np.asarray(p['codes'])[k].astype(str))) if r['key'][0] != 'sig']
    prob = pm.predict(pfeatures(cand)) if cand else np.zeros(0)
    pos = {str(c): i for i, c in enumerate(np.asarray(p['codes'])[k])}
    out = []
    for r, pi in zip(cand, prob):
        i = pos[r['key'][2]]
        u = float(np.nan_to_num(prov['adr'][i]) * np.sqrt(1 - t))
        vq = float(np.exp(yq[i, 1]) * prov['volume'][i] / di['adv'][ok][i]) if di['adv'][ok][i] > 0 else None
        col = 'order' if pi >= th['p_hi'] else 'watch' if pi >= th['p_lo'] else None
        out.append(dict(trader=r['key'][1], kind=r['key'][0], code=r['key'][2], side=r['key'][3],
                        add=bool(r['key'][4]) if r['key'][0] == 'buy' else False, setup=r['setup'],
                        price=float(prov['close'][i]), stop=r.get('stop'), p=float(pi), column=col,
                        distance=distance(r, u, vq), bits=r['bits']))
    out.sort(key=lambda x: -x['p'])
    return dict(t=t, hhmm=hhmm, thresholds=th, model=meta, rows=out)


def save_model(vol, prob, fm, th, meta):
    MODEL_PATH.write_text(json.dumps(dict(volume=vol.to_json(), prob=prob.to_json(), fm=fm, thresholds=th,
                                          meta=meta), ensure_ascii=False, indent=1), encoding='utf-8')


def load_model(path=MODEL_PATH):
    d = json.loads(Path(path).read_text(encoding='utf-8'))
    return VolumeModel.from_json(d['volume']), ProbModel.from_json(d['prob']), d['fm'], d['thresholds'], d['meta']
