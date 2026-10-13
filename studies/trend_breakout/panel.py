"""Load one market of the trend-breakout dataset into date x stock numpy panels, with the fixed splits.

    from studies.trend_breakout import panel
    p = panel.load('data/trend-breakout-v1/us')
    p['close'].shape            # (dates, stocks), ratio-adjusted, NaN where the stock did not trade
    p['raw_close']              # unadjusted (also raw_open/high/low), for price floors and A-share limits
    p['dates'][panel.mask(p['dates'], 'train')]

Prices are rebuilt from the unadjusted bars and ``actions.csv.gz`` (OpenD-style factors from every
source, see sources.py) into one multiplicative adjustment, so percentage moves are exact and the
strategy code never branches on the market or the source (the sources' own forward-adjusted bars
subtract dividends and are kept only for audit and for inferring A-share actions).
The split dates are pre-registered in notes/SPLITS.md and must not move after any result is seen.
"""
from __future__ import annotations

from collections import defaultdict
import csv
import gzip
import json
from pathlib import Path

import numpy as np

SPLITS = {  # inclusive ISO dates; warmup only feeds 52-week and 250-day indicators, never scores
    'warmup': ('2023-09-01', '2024-09-30'),
    'train': ('2024-10-01', '2025-09-30'),
    'test': ('2025-10-01', '2026-10-09'),
}
FIELDS = ('open', 'high', 'low', 'close', 'volume', 'turnover')


def read_bars(path):
    with gzip.open(path, 'rt', encoding='utf-8', newline='') as f:
        rows = csv.reader(f)
        header = next(rows)
        if tuple(header) != ('code', 'date') + FIELDS:
            raise ValueError(f'unexpected header in {path}: {header}')
        for row in rows:
            if row and row[0] != 'code':
                yield row[0], row[1], [float(x) for x in row[2:]]



def factors(raw_close, days, actions):
    """Multiplicative factor per day (latest day = 1) from OpenD-style actions (price -> a * price + b).

    An action whose ex-date falls inside the stock's data rescales every earlier day by
    (a * previous close + b) / previous close; one on a non-trading day applies on the next bar.
    """
    raw = np.asarray(raw_close, float)
    step = np.ones(len(raw))
    for ex_date, a, b in actions:
        t = int(np.searchsorted(days, ex_date))
        if 0 < t < len(raw):
            step[t] *= (a * raw[t - 1] + b) / raw[t - 1]
    return np.append(np.cumprod(step[::-1])[::-1][1:], 1.0) if len(raw) else step


def read_actions(path):
    out = defaultdict(list)
    with gzip.open(path, 'rt', encoding='utf-8', newline='') as f:
        rows = csv.reader(f)
        if tuple(next(rows)) != ('code', 'ex_date', 'factor_a', 'factor_b'):
            raise ValueError(f'unexpected header in {path}')
        for code, ex_date, a, b in rows:
            out[code].append((ex_date, float(a), float(b)))
    # a resumed fetch may append a code twice: the same action must count once
    return {code: sorted(set(acts)) for code, acts in out.items()}

def load(folder):
    """Return dates, codes and one (dates x codes) array per field; turnover and raw prices stay unadjusted."""
    folder = Path(folder)
    raw = defaultdict(dict)
    for code, day, values in read_bars(folder / 'bars_raw.csv.gz'):
        raw[code][day] = values
    actions = read_actions(folder / 'actions.csv.gz')
    listed = {s['code'] for s in json.loads((folder / 'universe.json').read_text(encoding='utf-8'))['stocks']}
    return build({code: rows for code, rows in raw.items() if code in listed}, actions)


def build(raw, actions):
    """Panels from {code: {date: [open, high, low, close, volume, turnover]}} unadjusted rows and actions."""
    dates = np.array(sorted({d for rows in raw.values() for d in rows}))
    codes = np.array(sorted(raw))
    di = {d: i for i, d in enumerate(dates)}
    out = {'dates': dates, 'codes': codes, 'events': {}}
    for name in FIELDS + ('raw_open', 'raw_high', 'raw_low', 'raw_close'):
        out[name] = np.full((len(dates), len(codes)), np.nan)
    for j, code in enumerate(codes):
        days = sorted(raw[code])
        r = np.array([raw[code][d] for d in days])
        f = factors(r[:, 3], np.array(days), actions.get(code, []))
        out['events'][code] = int(np.sum(np.abs(np.diff(f)) > 1e-12))
        rows = [di[d] for d in days]
        for k, name in enumerate(('open', 'high', 'low', 'close')):
            out[name][rows, j] = r[:, k] * f
        out['volume'][rows, j] = r[:, 4] / f
        out['turnover'][rows, j] = r[:, 5]
        out['raw_open'][rows, j] = r[:, 0]
        out['raw_high'][rows, j] = r[:, 1]
        out['raw_low'][rows, j] = r[:, 2]
        out['raw_close'][rows, j] = r[:, 3]
    return out


def mask(dates, split):
    lo, hi = SPLITS[split]
    return (dates >= lo) & (dates <= hi)
