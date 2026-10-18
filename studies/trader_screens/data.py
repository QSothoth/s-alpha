"""Daily bars for skills/trader-screens: on-demand fetch, the newest dataset per market, a dense panel cache, and
OpenD industry names.

US uses its own broad list (price >= 1 USD, 20-day turnover >= 2M USD, the Martin Luk research filter) so the
replicated system ranks over the same kind of universe it was researched on; HK / A-shares use the trend scan's
lists (studies/trend_breakout/sources.py), and a trend-market-scan refresh of the same day is reused.
"""
from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
SCANS = ROOT / 'data' / 'trader-screens'
TREND = ROOT / 'data' / 'trend-scan'
CACHE = SCANS / 'cache'
US_FILTER = ('US', 1.0, 2e6)          # futu market, min price, min 20-day average turnover
DATA_START_DAYS = 3 * 366 + 60        # history fetched: the replicated system replays from 2024-01-02
NAMES = {'us': '美股', 'hk': '港股', 'cn': 'A 股'}


def latest_folder(market):
    """Newest dataset root holding <market>/universe.json: data/trader-screens/<date> or data/trend-scan/<date>."""
    roots = [p for base in (SCANS, TREND) for p in base.glob('????-??-??') if (p / market / 'universe.json').exists()]
    return max(roots, key=lambda p: (p.name, p.parent == SCANS)) if roots else None


def refresh(market, now=None):
    """Foreground, resumable fetch into data/trader-screens/<market-local date>/<market>; a fetch taken before the
    market's close of that date is redone after it."""
    from datetime import timedelta
    from studies.trend_breakout import fetch, scan as T, sources
    today = T.market_now(market, now).date()
    out = SCANS / today.isoformat()
    if T.stale(out, market, now):
        shutil.rmtree(out / market)
    keep = sources.OpenDSource.FILTERS
    if market == 'us':
        sources.OpenDSource.FILTERS = {**keep, 'us': US_FILTER}
    try:
        fetch.fetch(out, market, (today - timedelta(days=DATA_START_DAYS)).isoformat(), today.isoformat())
    finally:
        sources.OpenDSource.FILTERS = keep
    return out, T.audit(out, market)


def cache_path(folder, market):
    key = re.sub(r'[^A-Za-z0-9._-]+', '_', str(Path(folder).resolve().relative_to(ROOT.resolve())))
    return CACHE / f'{key}_{market}.npz'


def panel(folder, market):
    """Dense (days x codes) forward-adjusted panel of one fetched market folder (bars_raw + actions): open, high,
    low, close, volume (adjusted to the same basis), turnover, raw_close; built once into data/trader-screens/cache."""
    from studies.trend_breakout import panel as P
    sub = Path(folder) / market
    path = cache_path(folder, market)
    src = sub / 'bars_raw.csv.gz'
    if not path.exists() or path.stat().st_mtime < src.stat().st_mtime:
        actions = P.read_actions(sub / 'actions.csv.gz')
        listed = {s['code'] for s in json.loads((sub / 'universe.json').read_text(encoding='utf-8'))['stocks']}
        days = np.array(sorted({day for _, day, _ in P.read_bars(src)}))
        di = {d: i for i, d in enumerate(days)}
        codes = sorted(listed)
        ci = {c: i for i, c in enumerate(codes)}
        out = {k: np.full((len(days), len(codes)), np.nan, np.float32)
               for k in ('open', 'high', 'low', 'close', 'volume', 'turnover', 'raw_close')}

        def flush(code, dd, rows):
            if code not in ci or not rows:
                return
            r = np.array(rows, float)
            f = P.factors(r[:, 3], np.array(dd), actions.get(code, []))
            idx = [di[d] for d in dd]
            j = ci[code]
            for k, n in (('open', 0), ('high', 1), ('low', 2), ('close', 3)):
                out[k][idx, j] = r[:, n] * f
            with np.errstate(invalid='ignore', divide='ignore'):
                out['volume'][idx, j] = r[:, 4] / f          # shares on the adjusted price basis
            out['turnover'][idx, j] = r[:, 5]
            out['raw_close'][idx, j] = r[:, 3]

        cur, dd, rows = None, [], []
        for code, day, values in P.read_bars(src):
            if code != cur:
                flush(cur, dd, rows)
                cur, dd, rows = code, [], []
            dd.append(day)
            rows.append(values)
        flush(cur, dd, rows)
        CACHE.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(path, days=days, codes=np.array(codes), **out)
    z = np.load(path)
    return {k: z[k] for k in z.files}


def names(folder, market):
    stocks = json.loads((Path(folder) / market / 'universe.json').read_text(encoding='utf-8'))['stocks']
    return {s['code']: s.get('name', '') for s in stocks}


def industries(codes, market, fetch=False):
    """OpenD INDUSTRY plate per code (get_owner_plate, no quota), cached per market; the US cache starts from the
    Martin Luk research cache.  Without fetch, codes not in the cache get ''."""
    path = CACHE / f'industry_{market}.json'
    have = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    seed = ROOT / 'data' / 'martin-luk-cache' / 'industry.json'
    if market == 'us' and not have and seed.exists():
        have = json.loads(seed.read_text(encoding='utf-8'))
    todo = [c for c in codes if c not in have]
    if fetch and todo:
        import time
        import futu as ft
        q = ft.OpenQuoteContext(host='127.0.0.1', port=11111)
        try:
            for k in range(0, len(todo), 200):
                batch = todo[k:k + 200]
                ret, df = q.get_owner_plate(batch)
                if ret != ft.RET_OK:
                    raise RuntimeError(str(df))
                ind = df[df.plate_type == 'INDUSTRY']
                for c in batch:
                    got = ind[ind.code == c].plate_name.tolist()
                    have[c] = got[0] if got else ''
                time.sleep(3.5)                                  # 10 requests / 30 s
        finally:
            q.close()
    if fetch or (have and not path.exists()):
        CACHE.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(have, ensure_ascii=False, indent=0), encoding='utf-8')
    return {c: have.get(c, '') for c in codes}
