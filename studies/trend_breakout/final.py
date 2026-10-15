"""Final weekly schemes per market from the 2026-10 trend research (see reports/CONCLUSIONS_CN.md).

Self-contained: the earlier rounds' scripts are archived. Only local daily bars are read.

- cn: long trend. Weekly Chan 2nd/3rd buy, pool index above its 120-day line, buy only in the first week after
  it crosses up, 5 names sized by risk (10% / 5 at stop, cap 40%), ranked by 52-week return, exit on the
  structural stop or when the line breaks.
- us: long trend. Same buy points, first 13 weeks after the 120-day cross-up, 20 equal names, 26-week return.
- hk: swing. Same buy points within 20% of the 52-week high, ranked by closeness to it, no market line,
  5 equal names, exit when a weekly close breaks the highest weekly low since entry or after 8 weeks.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from . import backtest, chan, pit, portfolio, signals as S

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / 'data' / 'trend-breakout-v1'
MARKETS = {  # costs per side, liquidity floor; A-share price limits by board
    'us': {'cost': (0.0005, 0.0005), 'min_turnover': 50e6, 'min_price': 5.0},
    'hk': {'cost': (0.0016, 0.0016), 'min_turnover': 20e6, 'min_price': None},
    'cn': {'cost': (0.00076, 0.00126), 'min_turnover': 1e8, 'min_price': None},
}
SPANS = {'cn': ('2019-03-01', '2026-10-09'), 'us': ('2024-10-01', '2026-10-09'), 'hk': ('2024-10-01', '2026-10-09')}
SCHEMES = {
    'cn': dict(early=1, line=120, slots=5, sizing='RISK', rank='RS52', exit_on_line=True, max_hold=None,
               trail='STRUCT', near_high=None),
    'us': dict(early=13, line=120, slots=20, sizing='EQ', rank='RS26', exit_on_line=True, max_hold=None,
               trail='STRUCT', near_high=None),
    'hk': dict(early=None, line=None, slots=5, sizing='EQ', rank='NEAR52', exit_on_line=False, max_hold=8,
               trail='LOW', near_high=.20),
}
CN_MIN_CAP = 1e10


def cn_limit(code):
    return 0.2 if code.startswith(('SZ.300', 'SZ.301', 'SH.688', 'SH.689')) else 0.1


def is_st(name):
    return name.lstrip('*').upper().startswith('ST')


def rows(p, start, end):
    idx = np.flatnonzero((p['dates'] >= start) & (p['dates'] <= end))
    return int(idx[0]), int(idx[-1])


def load(market):
    """Daily panel: A-shares point-in-time (2018-01 on, cap ever >= 10bn), US/HK the 2023-09 snapshot list."""
    if market != 'cn':
        folder = DATA / market
        return pit.load([(folder, '2023-09-01', SPANS[market][1], None)], [folder])
    cands = set(json.loads((pit.CNX / 'progress.json').read_text())['done'])

    def keep(q):
        span = q['dates'] >= SPANS['cn'][0]
        return np.nanmax(np.nan_to_num(q['mktcap'][span]), axis=0) >= CN_MIN_CAP
    return pit.load([(pit.HIST, '2018-01-01', '2023-08-31', None), (DATA / 'cn', '2023-09-01', '2026-10-09', None),
                     (pit.HIST_CNX, '2018-01-01', '2026-10-09', cands)], [DATA / 'cn', pit.CNX], keep=keep)


def pool(p, market, block=256, cap=True):
    """Daily universe: 20-day turnover floor (and US price floor); A-shares also cap >= 10bn on the day (skipped
    with ``cap=False`` when the stock list itself is a current >= 10bn snapshot), no ST."""
    cfg = MARKETS[market]
    out = np.zeros(p['close'].shape, bool)
    for a in range(0, out.shape[1], block):
        q = {k: v[:, a:a + block] for k, v in p.items() if isinstance(v, np.ndarray) and v.ndim == 2}
        out[:, a:a + block] = S.liquid(q, cfg['min_turnover'], cfg['min_price'])
    if market == 'cn':
        if cap:
            out &= np.nan_to_num(p['mktcap']) >= CN_MIN_CAP
        out &= ~np.array([is_st(p['names'][c]) for c in p['codes']])[None, :]
    return out


def momentum(close, weeks):
    past = np.full_like(close, np.nan)
    past[weeks:] = close[:-weeks]
    return np.nan_to_num(close / past - 1, nan=-np.inf)


def rolling_high(high, weeks):
    out = np.full(high.shape, np.nan)
    for i in range(len(out)):
        block = high[max(0, i - weeks + 1):i + 1]
        seen = np.isfinite(block).any(axis=0)
        out[i] = np.where(seen, np.max(np.where(np.isfinite(block), block, -np.inf), axis=0), np.nan)
    return out


def weekly_atr(w, n=10):
    out = np.full(w['close'].shape, np.nan)
    for a in range(0, out.shape[1], 256):
        b = min(a + 256, out.shape[1])
        valid = np.isfinite(w['close'][:, a:b])
        c = {k: S.compact(w[k][:, a:b], valid)[0] for k in ('high', 'low', 'close')}
        order = S.compact(w['close'][:, a:b], valid)[1]
        out[:, a:b] = S.scatter(S.atr(c['high'], c['low'], c['close'], n), order, valid)
    return out


def pool_mean(x, member):
    ok = member & np.isfinite(x)
    n = ok.sum(axis=1)
    return np.where(n > 0, np.where(ok, x, 0.).sum(axis=1) / np.maximum(n, 1), 0.)


def alpha(curve, market):
    """Daily OLS of account returns on pool equal-weight returns: annualized intercept, beta, t value."""
    nav = np.array([1.] + [r['nav'] for r in curve])
    y = nav[1:] / nav[:-1] - 1
    x = np.column_stack([np.ones(len(y)), market])
    coef, *_ = np.linalg.lstsq(x, y, rcond=None)
    resid = y - x @ coef
    se = np.sqrt(resid @ resid / (len(y) - 2) * np.linalg.inv(x.T @ x)[0, 0])
    return {'alpha_annual': float(coef[0] * 252), 'beta': float(coef[1]), 't': float(coef[0] / se)}


class Book:
    """Everything a scheme needs for one market, computed once from the daily panel."""

    def __init__(self, market, p=None, span=None, cap=True):
        """``p``/``span`` default to the research data and period; the scanner passes a fresh panel."""
        self.market = market
        p = self.p = load(market) if p is None else p
        self.pool = pool(p, market, cap=cap)
        for key in ('volume', 'turnover', 'mktcap'):
            p.pop(key, None)
        w = self.w = chan.weekly(p)
        self.pw = {k: w[k] for k in chan.FIELDS + ('dates', 'codes')}
        self.first, self.last = w['first'], w['last']
        self.pool_w = self.pool[self.last]
        self.atr = weekly_atr(w)
        self.first_open = np.zeros(w['close'].shape, int)
        for i, (a, b) in enumerate(zip(self.first, self.last)):
            self.first_open[i] = a + np.isfinite(p['open'][a:b + 1]).argmax(axis=0)
        start_d, end_d = rows(p, *(span or SPANS[market]))
        self.lo = int(np.flatnonzero(self.first >= start_d)[0])
        self.hi = int(np.flatnonzero(self.last <= end_d)[-1])
        self.fee = MARKETS[market]['cost']
        self.limit = np.array([cn_limit(c) for c in p['codes']]) if market == 'cn' else None
        buy3, stop3, buy2, stop2, self.cap, self.support = chan.signals(w['high'], w['low'])
        self.signal, self.initial = buy2 | buy3, np.where(buy3, stop3, stop2)
        self.buy3 = buy3
        rs52 = momentum(w['close'], 52)
        self.drop52 = 1 - w['close'] / rolling_high(w['high'], 52)
        near = np.where(np.isfinite(self.drop52), -self.drop52 * 1e3, -np.inf)
        self.ranks = {'RS26': momentum(w['close'], 26), 'RS52': rs52,
                      'NEAR52': near + np.where(np.isfinite(rs52), np.clip(rs52, -9, 99) * 1e-3, 0)}
        close = p['close']
        self.filled = close.copy()
        for t in range(1, len(close)):
            gap = np.isnan(self.filled[t])
            self.filled[t, gap] = self.filled[t - 1, gap]
        ret = np.full_like(close, np.nan)
        ret[1:] = close[1:] / close[:-1] - 1
        member = np.zeros_like(self.pool)
        member[1:] = self.pool[:-1]
        self.market_ret = pool_mean(ret, member)

    def line(self, n):
        """(up, streak) per week: pool index above its n-day average at the week's close, consecutive weeks up."""
        if n is None:
            return np.ones(len(self.last), bool), None
        up = S.market_up(self.p['close'], self.pool, n=n)[self.last]
        streak = np.zeros(len(up), int)
        for i in range(len(up)):
            streak[i] = (streak[i - 1] + 1 if i else 1) if up[i] else 0
        return up, streak

    def entry(self, s):
        up, streak = self.line(s['line'])
        e = self.signal & up[:, None]
        if s['early'] is not None:
            e &= (streak <= s['early'])[:, None]
        if s['near_high'] is not None:
            e &= self.drop52 <= s['near_high']
        return e, up

    def nav(self, trades, a_d, b_d):
        n = b_d - a_d + 1
        cash, value = np.zeros(n), np.zeros(n)
        for tr in trades:
            j = tr['stock']
            a = self.first_open[tr['entry'], j] - a_d
            qty = tr['paid'] / (tr['buy'] * (1 + self.fee[0]))
            cash[a:] -= tr['paid']
            b = n if tr['at_end'] else self.first_open[tr['exit'], j] - a_d
            if not tr['at_end']:
                cash[b:] += qty * tr['sell'] * (1 - self.fee[1])
            value[a:b] += qty * self.filled[a_d + a:a_d + b, j]
        out = 1 + cash + value
        return [{'date': str(d), 'nav': float(v), 'cash': float(1 + c), 'exposure': float(x / v), 'positions': 0,
                 'largest_weight': 0., 'stale_positions': 0}
                for d, v, c, x in zip(self.p['dates'][a_d:b_d + 1], out, cash, value)]

    def run(self, s, rank=None):
        """Replay a scheme over the market's span; returns (metrics, account)."""
        e, up = self.entry(s)
        slots = s['slots']
        size = dict(weight=1 / slots) if s['sizing'] == 'EQ' else dict(weight=2 / slots, risk_fraction=.10 / slots)
        account = chan.PullbackAccount(self.pw, self.ranks[s['rank']] if rank is None else rank, self.fee, self.cap,
                                       slots=slots, **size)
        backtest.run(self.pw, e, self.support if s['trail'] == 'STRUCT' else self.w['low'], True, self.pool_w,
                     self.atr, self.lo, self.hi, self.fee, self.limit, account=account, initial_line=self.initial,
                     max_hold=s['max_hold'], exit_rows=~up if s['exit_on_line'] else None)
        a_d, b_d = int(self.first[self.lo]), int(self.last[self.hi])
        curve = self.nav(account.trades, a_d, b_d)
        summary = portfolio.nav_summary(curve, str(self.p['dates'][a_d - 1]))
        held = [t['exit'] - t['entry'] for t in account.trades if not t['at_end']]
        metrics = {'total_return': summary['total_return'], 'cagr': summary['cagr'],
                   'max_drawdown': summary['max_drawdown'], 'trades': len(account.trades),
                   'median_hold_weeks': float(np.median(held)) if held else None,
                   'mean_exposure': float(np.mean([r['exposure'] for r in curve])),
                   **alpha(curve, self.market_ret[a_d:b_d + 1])}
        return metrics, account

    def hold_pool(self):
        a_d, b_d = int(self.first[self.lo]), int(self.last[self.hi])
        nav = np.cumprod(1 + self.market_ret[a_d:b_d + 1])
        dd = nav / np.maximum.accumulate(nav) - 1
        return {'total_return': float(nav[-1] - 1), 'max_drawdown': float(dd.min())}

    def holdings(self, s, account):
        """Open positions and next-week candidates at the data end (rule state, not orders)."""
        hi, w, names = self.hi, self.w, self.p.get('names', {})
        e, up = self.entry(s)
        to_raw = w['raw_close'][hi] / w['close'][hi]
        positions = [{'code': t['code'], 'name': names.get(t['code'], ''),
                      'bought_week_of': str(self.p['dates'][self.first_open[t['entry'], t['stock']]]),
                      'buy_raw': float(w['raw_open'][t['entry'], t['stock']]),
                      'close_raw': float(w['raw_close'][hi, t['stock']]), 'gain': float(t['sell'] / t['buy'] - 1)}
                     for t in account.trades if t['at_end']]
        rank = self.ranks[s['rank']][hi]
        cands = sorted(np.flatnonzero(e[hi] & self.pool_w[hi]), key=lambda j: -rank[j])[:10]
        return {'data_end': str(self.p['dates'][int(self.last[hi])]), 'market_ok': bool(up[hi]),
                'positions': positions,
                'next_week_candidates': [{'code': str(self.p['codes'][j]), 'name': names.get(str(self.p['codes'][j]), ''),
                                          'close_raw': float(w['raw_close'][hi, j]),
                                          'stop_raw': float(self.initial[hi, j] * to_raw[j]),
                                          'skip_if_open_at_or_above': float(self.cap[hi, j] * to_raw[j])}
                                         for j in cands]}
