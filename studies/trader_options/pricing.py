"""Option prices for the option traders' replications (Alfredo Holguin, Karl Domm, Emanuela Elias), from the data
the board may use: the daily bars of trader-data-v1 and OpenD's per-underlying daily IV (data/trader-options-v1).

There are no historical option quotes (expired contracts vanish after about four weeks, history klines are 60 a
week), so every option is priced with Black-Scholes on the underlying's IV that day.  That IV is one number per
underlying and day (OpenD's implied volatility of the underlying, roughly 30 days at the money); the researcher's
model on top of it, stated so the results are read as an approximation:

    skew      an out-of-the-money put / call's vol is the ATM vol x (1 + skew x |moneyness in ATM sds|) (puts) or
              x (1 + call_skew x ...) (calls); default 0.10 / 0.0 (researcher values, sensitivity reported)
    earnings  when an earnings day falls inside an option's life, its variance carries the earnings move: total
              variance = base^2 x T + e^2, with e the typical one-day earnings move (the median absolute earnings-day
              return of the name's past earnings, known before the day) and base^2 = max(IV^2 - e^2 / T30, floor)
              (the 30-day IV already holds the next earnings when it is inside 30 days)
    spread    selling receives the model price x (1 - spread), buying pays x (1 + spread); default 5%; plus
              commission 0.65 USD a contract (Schwab)
Rates: 4% a year, no dividends.
"""
from __future__ import annotations

import csv
import math
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / 'data' / 'trader-options-v1' / 'us'
R = .04
COMMISSION = .65


def _ncdf(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def bs(S, K, T, vol, put):
    """Black-Scholes price per share; T in years (expired: intrinsic)."""
    if T <= 1e-6 or vol <= 0:
        return max(K - S, 0.0) if put else max(S - K, 0.0)
    sq = vol * math.sqrt(T)
    d1 = (math.log(S / K) + (R + .5 * vol * vol) * T) / sq
    d2 = d1 - sq
    if put:
        return K * math.exp(-R * T) * _ncdf(-d2) - S * _ncdf(-d1)
    return S * _ncdf(d1) - K * math.exp(-R * T) * _ncdf(d2)


def vol_for(S, K, T, atm, put, skew=.10, call_skew=0.0, earn_var=0.0, base_atm=None):
    """The option's vol from the ATM IV (fractions), with skew and an earnings variance inside its life."""
    base = atm if base_atm is None else base_atm
    T = max(T, 1e-6)
    v = math.sqrt(max(base * base * T + earn_var, 1e-12) / T)
    m = abs(math.log(K / S)) / max(v * math.sqrt(T), 1e-6)
    return v * (1 + (skew if put else call_skew) * m)


def leverage(S, K, T, vol, put):
    """The option's leverage at entry: |delta| x S / price (how many times the stock's percentage move)."""
    p = bs(S, K, T, vol, put)
    if p <= 0 or T <= 1e-6 or vol <= 0:
        return float('nan')
    d1 = (math.log(S / K) + (R + .5 * vol * vol) * T) / (vol * math.sqrt(T))
    return abs(_ncdf(d1) - (1 if put else 0)) * S / p


def lever_return(stock_ret, lev, T0, T1, spread=0.0):
    """Estimated return on premium of a bought option: leverage x the stock's move in the option's direction
    (stock_ret already signed), less the time value an at-the-money option loses from T0 to T1 years to expiry
    (value ~ sqrt(T)) and the spread both ways; at most a total loss."""
    decay = 1 - math.sqrt(max(T1, 0.0) / T0) if T0 > 0 else 0.0
    return max(-1.0, lev * stock_ret - decay - 2 * spread)


# ----- v2 (notes/SIM_V2_PREREG_CN.md): the earnings premium read off the market, a smile, a tick-floored spread -----

def reactions(days, events):
    """Sorted session indexes of the earnings reactions of `events` [(date, pub)]."""
    return sorted({r for r in (reaction_day(days, d, pb) for d, pb in events) if r is not None})


def implied_event_var(iv, j, rx, d, fallback=None):
    """The variance the market gives one earnings report of name j, as of session d: the median over its reports
    before d of (IV the day before - IV of the reaction day)^2-difference x 30/365 (OpenD's IV is a 30-day number),
    at least 0; `fallback` (e.g. the historical move squared) with fewer than two."""
    out = []
    for r in rx:
        if r >= d or r < 1:
            continue
        a, b = iv[r - 1, j], iv[r, j]
        if np.isfinite(a) and np.isfinite(b):
            out.append(max(a * a - b * b, 0.0) * 30 / 365)
    return float(np.median(out)) if len(out) >= 2 else fallback


def event_context(days, rx, d, expiry):
    """(next report's reaction index or None, it is within 30 calendar days of d, it falls inside the option's
    life to `expiry` (an index))."""
    import datetime as dt
    r = next((x for x in rx if x > d), None)
    if r is None or r >= len(days):
        return None, False, False
    near = (dt.date.fromisoformat(str(days[r])[:10]) - dt.date.fromisoformat(str(days[d])[:10])).days <= 30
    return r, near, r <= expiry


def vol_v2(S, K, T, iv30, put, E=0.0, near=False, spans=False, k=.1, strip=True):
    """v2 vol of one option: the base (the 30-day IV without the next report's variance E when that report is within
    30 days), plus E spread over the option's life when the report falls inside it, times a smile
    min(1 + k x m^2, 3), m = |ln K/S| in the option's sds.  Calls and puts alike.  strip=False (v2.1): an option
    that does not span the report keeps the 30-day IV itself (Karl's near legs filled at 0.95 x it)."""
    T = max(T, 1e-6)
    cut = near and E and (strip or spans)
    base2 = max(iv30 * iv30 - E / (30 / 365), (.5 * iv30) ** 2) if cut else iv30 * iv30
    v = math.sqrt(base2 + (E / T if spans else 0.0))
    m = abs(math.log(K / S)) / max(v * math.sqrt(T), 1e-6)
    return v * min(1 + k * m * m, 3.0)


def half_spread(price, pct=.01, tick=.02):
    """v2 half spread as a fraction of the option's price: at least `tick` dollars, at most 50%."""
    return min(max(pct, tick / price if price > 0 else .5), .5)


def years(d0, d1):
    """Trading-day fraction of a year between ISO dates, counted as calendar days / 365 (options decay on calendar
    time); at least one hour."""
    import datetime as dt
    a, b = dt.date.fromisoformat(str(d0)[:10]), dt.date.fromisoformat(str(d1)[:10])
    return max((b - a).days, 0) / 365 + 1 / (365 * 24)


def load_panel(sub, col, days, codes, scale=1.0):
    """(days x codes) array of one column of data/trader-options-v1/us/<sub>/<code>.csv aligned to the panel (NaN
    where missing)."""
    out = np.full((len(days), len(codes)), np.nan)
    di = {str(d): i for i, d in enumerate(days)}
    for j, code in enumerate(codes):
        p = DATA / sub / f'{code}.csv'
        if not p.exists():
            continue
        with p.open(encoding='utf-8') as f:
            rd = csv.DictReader(f)
            if not rd.fieldnames or col not in rd.fieldnames:
                continue
            for r in rd:
                i = di.get(r['time'][:10])
                if i is not None and r[col] not in ('', None):
                    try:
                        out[i, j] = float(r[col]) * scale
                    except ValueError:
                        pass
    return out


def earnings(codes=None):
    """{code: sorted [(date, 'BEFORE' | 'AFTER' | ...)]} from the earnings calendar."""
    out = {}
    with (DATA / 'earnings.csv').open(encoding='utf-8') as f:
        for r in csv.DictReader(f):
            c = r['security']
            if codes is not None and c not in codes:
                continue
            out.setdefault(c, set()).add((r['earnings_date'][:10], r['pub_type']))
    return {c: sorted(v) for c, v in out.items()}


def reaction_day(days, date, pub):
    """Index of the first session that trades on the news: the day itself for BEFORE (pre-market), the next session
    for AFTER / unknown."""
    i = int(np.searchsorted(days, date))
    if i >= len(days):
        return None
    if str(days[i]) == date and pub == 'BEFORE':
        return i
    return i + 1 if str(days[i]) == date else i


def earnings_moves(days, close, j, events):
    """[(reaction index, absolute close-to-close move)] of the name's earnings (NaN-free ones only)."""
    out = []
    for date, pub in events:
        i = reaction_day(days, date, pub)
        if i is None or i < 1 or i >= len(days):
            continue
        a, b = close[i - 1, j], close[i, j]
        if np.isfinite(a) and np.isfinite(b) and a > 0:
            out.append((i, abs(b / a - 1)))
    return out
