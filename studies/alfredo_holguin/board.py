"""Holguin on the trader-screens board: his weekly short puts replayed by his own engine (replicate.simulate) from
the registered start to the newest close, in the runner's result shape (runner.run) so scan / board render him with
the stock traders.  A put is a row with `option` (strike, expiry, premium); it takes no part in the overlaps.  He
sells at the open and holds to the weekly expiry, so the provisional (pre-close) board leaves him out.
"""
from __future__ import annotations

import numpy as np

from studies.trader_replication import runner, systems as SY


def run(system, market, mode=None, days=1, A=None):
    H, cfg = system.study, system.config
    H.mode = mode
    A = H.data()
    dates = A['days']
    T = len(dates) - 1
    curve, cdates, tr = H.simulate(cfg, SY.START, str(dates[T]))
    curve = np.asarray(curve)
    window = [str(d) for d in dates[max(T - days + 1, 0):T + 1]]
    di = {str(d): i for i, d in enumerate(cdates)}
    col = {str(c): j for j, c in enumerate(A['codes_s'])}

    def eq_before(day):
        k = di.get(day, 0)
        return float(curve[k - 1]) if k > 0 else 1.0

    def option(t):
        return dict(strike=t['K'], expiry=t['expiry'], premium=t['prem'], spot=t['S0'])

    buys, sells, holdings = [], [], []
    for t in tr:
        if t['entry'] in window:
            buys.append(dict(code=t['code'], day=t['entry'], setup='卖 Put', side=1, price=t['prem'], stop=None,
                             weight=t['m'] * t['n'] / eq_before(t['entry']), stage='open', option=option(t)))
        if t['why'] != 'open' and t['exit'] in window:
            assigned = bool(t['pay'])
            sells.append(dict(code=t['code'], day=t['exit'], side=1, stage='close', price=t['pay'] or 0.0,
                              why='到期被行权' if assigned else '到期作废', full=True, ret=t['ret'], option=option(t)))
    equity = float(curve[-1])
    for t in (t for t in tr if t['why'] == 'open'):
        j = col[t['code']]
        seen = np.flatnonzero(np.isfinite(A['close'][:T + 1, j]))
        close = float(A['close'][seen[-1], j]) if len(seen) else t['S0']
        holdings.append(dict(code=t['code'], entry_day=t['entry'], setup='卖 Put', side=1, fill=t['prem'], close=close,
                             close_day=str(dates[seen[-1]]) if len(seen) else t['entry'], ret=None,
                             tradable=bool(np.isfinite(A['close'][T, j])), weight=t['m'] * t['n'] / equity,
                             days=int(T - int(np.searchsorted(dates, t['entry']))), option=option(t)))
    closed = [t for t in tr if t['why'] != 'open']
    peak = np.maximum.accumulate(np.concatenate([[1.0], curve]))[1:]
    return dict(id=system.id, name=system.name, version=system.version, status=system.status, label=system.label,
                style=system.style, market=market, data=A.get('digest'), last_day=str(dates[T]), days=days,
                equity_history=runner.bounded_history(cdates, curve, str(dates[T])), strategy=system.strategy,
                buys=buys, sells=sells, wanted=[], holdings=holdings, gate_today=None,
                account=dict(since=SY.START, ret=equity - 1, maxdd=float(np.max(1 - curve / peak)), trades=len(closed),
                             win=float(np.mean([t['ret'] > 0 for t in closed])) if closed else None,
                             exposure=float(sum(h['weight'] for h in holdings)), short_exposure=0.0),
                freeze=system.freeze, registered=system.registered,
                forward=runner.forward(curve, cdates, tr, system.freeze), check=dict(ok=None, status='missing'))
