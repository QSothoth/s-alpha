"""Dense (days x codes) forward-adjusted panel of a Dataset: open, high, low, close, volume (on the adjusted basis),
turnover, raw_close, plus 'days', 'codes', 'digest' (what it was built from) and 'dataset' (its id).

Built once per dataset into data/trader-data/cache and rebuilt whenever the dataset's digest differs.  A source bar
that opens or closes outside its own high / low (some HK bars) gets its high / low widened to contain them.
"""
from __future__ import annotations

import hashlib
from itertools import groupby
import re
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / 'data' / 'trader-data' / 'cache'
VERSION = 2                           # 2: high / low widened to contain open and close
FIELDS = ('open', 'high', 'low', 'close', 'volume', 'turnover', 'raw_close')


def cache_path(ds):
    key = re.sub(r'[^A-Za-z0-9._-]+', '_', ds.id)[-60:]
    return CACHE / f'{key}_{hashlib.sha256(ds.id.encode()).hexdigest()[:10]}_v{VERSION}.npz'


def assemble(ds):
    from studies.trend_breakout import panel as P
    actions = ds.actions()
    codes = sorted({s['code'] for s in ds.stocks()})
    ci = {c: i for i, c in enumerate(codes)}
    days = np.array(sorted({day for code, day, _ in ds.rows() if code in ci}))
    di = {d: i for i, d in enumerate(days)}
    out = {k: np.full((len(days), len(codes)), np.nan, np.float32) for k in FIELDS}
    for code, records in groupby(ds.rows(), key=lambda row: row[0]):
        if code not in ci:
            continue
        dd, rows = [], []
        for _, day, values in records:
            if dd and day <= dd[-1]:
                raise ValueError(f'{ds.id}: {code} bars out of order or repeated at {day}')
            dd.append(day)
            rows.append(values)
        r = np.array(rows, float)
        f = P.factors(r[:, 3], np.array(dd), actions.get(code, []))
        idx = [di[d] for d in dd]
        j = ci[code]
        for k, n in (('open', 0), ('high', 1), ('low', 2), ('close', 3)):
            out[k][idx, j] = r[:, n] * f
        with np.errstate(invalid='ignore', divide='ignore'):
            out['volume'][idx, j] = r[:, 4] / f
        out['turnover'][idx, j] = r[:, 5]
        out['raw_close'][idx, j] = r[:, 3]
    with np.errstate(invalid='ignore'):
        out['high'] = np.fmax(out['high'], np.fmax(out['open'], out['close']))
        out['low'] = np.fmin(out['low'], np.fmin(out['open'], out['close']))
    return dict(days=days, codes=np.array(codes), **out)


def build(ds, upto=None, cache=True, write_cache=True):
    """The panel of `ds` (cached by digest); `upto` cuts it after that day. write_cache=False reads existing
    caches but builds a missing/stale one only in memory, for the read-only intraday path."""
    digest = ds.digest()
    path = cache_path(ds)
    p = None
    if cache and path.exists():
        with np.load(path) as z:
            if 'digest' in z.files and str(z['digest']) == digest:
                p = {k: z[k] for k in z.files}
    if p is None:
        p = assemble(ds)
        if cache and write_cache:
            CACHE.mkdir(parents=True, exist_ok=True)
            np.savez_compressed(path, digest=np.array(digest), **p)
    p['digest'], p['dataset'] = digest, ds.id
    if upto is not None:
        k = int(np.searchsorted(p['days'], upto, side='right'))
        p = {key: (v[:k] if isinstance(v, np.ndarray) and v.ndim and key != 'codes' else v) for key, v in p.items()}
    return p
