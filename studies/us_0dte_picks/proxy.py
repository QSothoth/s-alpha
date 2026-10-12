"""Model-priced 0DTE option bars from real underlying 1m bars (SV2, notes/SV2_PREREG.md).

Every timing decision of the custody engines uses the underlying only, so a replay needs option
prices only to turn exits into money. This proxy prices each bar with Black-Scholes (rate 0) at the
underlying open/high/low/close, sigma = k x the previous day's 30-day IV, and widens the high/low by
w/2 each way. It is never a custody Release and never ACCEPT evidence.
"""
from __future__ import annotations

import math
from statistics import median

from custody.dataset import CaseData
from custody.marketdata import Bar

YEAR_MINUTES = 252 * 390
GRID = {'US.INTC': 0.5}


def _cdf(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def bs_price(spot, strike, variance, right):
    """Black-Scholes with zero rate; ``variance`` = sigma^2 x years left."""
    intrinsic = max(0.0, spot - strike) if right == 'CALL' else max(0.0, strike - spot)
    if variance <= 0 or spot <= 0:
        return intrinsic
    sd = math.sqrt(variance)
    d1 = (math.log(spot / strike) + variance / 2) / sd
    d2 = d1 - sd
    call = spot * _cdf(d1) - strike * _cdf(d2)
    return call if right == 'CALL' else call - spot + strike


def atm_strike(symbol, reference):
    step = GRID.get(symbol, 2.5)
    low = (reference // step) * step
    return round(min((low, low + step), key=lambda k: (abs(k - reference), k)), 3)


def option_bars(underlying, session, strike, right, iv, k=1.0, w=0.0, code='US.PROXY'):
    """One synthetic option bar per underlying bar. ``iv`` is annualized (0.25 = 25%)."""
    sigma2 = (k * iv) ** 2 / YEAR_MINUTES
    out = []
    for bar in underlying:
        left = (session.closes - bar.close_time).total_seconds() / 60
        start = [bs_price(bar.open, strike, sigma2 * (left + 1), right)]
        rest = [bs_price(p, strike, sigma2 * left, right) for p in (bar.high, bar.low, bar.close)]
        close = max(rest[-1], 0.01)  # a worthless 0DTE still prints at the minimum tick
        high = max(max(start + rest) * (1 + w / 2), close)
        low = min(max(0.01, min(start + rest) * (1 - w / 2)), close)
        out.append(Bar(code, bar.close_time, min(max(start[0], low), high), high, low, close, 1.0))
    return tuple(out)


def proxy_case(data: CaseData, iv, k, w):
    case = data.case
    right = 'CALL' if case.direction == 'LONG' else 'PUT'
    return CaseData(case, data.session, data.underlying,
                    option_bars(data.underlying, data.session, case.strike, right, iv, k, w, case.contract))


def measure_k_w(datas, ivs, first=16, last=300):
    """k and w on the calibration set (notes/SV2_PREREG.md step 1), from k=1, w=0 proxies."""
    ratios, widths = [], []
    for data, iv in zip(datas, ivs):
        if iv is None:
            continue
        model = {round((b.close_time - data.session.opens).total_seconds() / 60): b
                 for b in proxy_case(data, iv, 1.0, 0.0).option}
        r, wd = [], []
        for bar in data.option:
            minute = round((bar.close_time - data.session.opens).total_seconds() / 60)
            m = model.get(minute)
            if not (first <= minute <= last) or m is None or m.close <= 0.01 or bar.close <= 0:
                continue
            r.append(bar.close / m.close)
            wd.append((bar.high - bar.low) / bar.close - (m.high - m.low) / m.close)
        if r:
            ratios.append(median(r))
            widths.append(median(wd))
    return round(median(ratios), 2), round(max(0.0, median(widths)), 2), len(ratios)
