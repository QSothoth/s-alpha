"""Read existing benchmark closes and exact-session option statistics; never refresh."""
from __future__ import annotations

import csv
import hashlib
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
BENCHMARKS = ROOT / 'data/martin-luk-benchmarks-v1'
OPTIONS = ROOT / 'data/trader-options-v1/us'
LIVE_OPTIONS = ROOT / 'data/trader-options-live/us'


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        while block := stream.read(1024 * 1024):
            h.update(block)
    return h.hexdigest()


def benchmark(code, days, mode='frozen'):
    """Require an observed close on each requested session; no stale-price substitution."""
    from . import resolve_mode
    resolve_mode(mode)
    path = BENCHMARKS / (code + '.csv')
    values = {}
    with path.open(encoding='utf-8') as stream:
        for row in csv.DictReader(stream):
            values[row['time_key'][:10]] = float(row['close'])
    out = np.array([values.get(str(d), np.nan) for d in days], float)
    return out, {str(path.relative_to(ROOT)): sha(path)}


def option_volume(codes, days, mode='frozen'):
    """Frozen rows take precedence over append-only live rows on duplicate dates."""
    from . import resolve_mode
    roots = (OPTIONS, LIVE_OPTIONS) if resolve_mode(mode) == 'live' else (OPTIONS,)
    out = np.full((len(days), len(codes)), np.nan, np.float32)
    di = {str(d): t for t, d in enumerate(days)}
    sources = {}
    for j, code in enumerate(codes):
        for root in roots:
            path = root / 'stat' / (str(code) + '.csv')
            if not path.exists():
                continue
            sources[str(path.relative_to(ROOT))] = sha(path)
            with path.open(encoding='utf-8') as stream:
                for row in csv.DictReader(stream):
                    t = di.get(row['time'][:10])
                    if t is None or (root != OPTIONS and np.isfinite(out[t, j])):
                        continue
                    try:
                        value = float(row['option_volume'])
                    except (ValueError, TypeError):
                        continue
                    if np.isfinite(value) and value >= 0:
                        out[t, j] = value
    return out, sources
