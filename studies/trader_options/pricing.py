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
