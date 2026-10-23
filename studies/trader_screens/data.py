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
PANEL_VERSION = 2                     # = studies.trader_data.panel.VERSION


UNIVERSE = {                          # each market's list rule (universe.json 'filter'), research and board alike
    'us': {'min_price': 1.0, 'min_avg_turnover_20d': 2000000.0},
    'hk': {'min_price': None, 'min_avg_turnover_20d': 20000000.0},
    'cn': {'min_mktcap_cny': 10000000000.0, 'exclude': 'Beijing exchange'},
}
DATASET = ROOT / 'data' / 'trader-data-v1'  # the published common data layer (docs/TRADER_PROTOCOL_CN.md)


def folder_ok(folder, market):
    """The folder holds <market>/universe.json built with the market's list rule."""
    path = Path(folder) / market / 'universe.json'
    return path.exists() and json.loads(path.read_text(encoding='utf-8')).get('filter') == UNIVERSE[market]


def latest_folder(market):
    """Newest dataset with the market's list rule: data/trader-screens/<date>, data/trend-scan/<date> or the common
    data layer (dated by the end of its window); a folder built with another list rule is never used."""
    roots = [(p.name, p.parent == SCANS, p) for base in (SCANS, TREND) for p in base.glob('????-??-??')]
    if (DATASET / market / 'universe.json').exists():
        end = json.loads((DATASET / market / 'universe.json').read_text(encoding='utf-8'))['window'][1]
        roots.append((end, False, DATASET))
    roots = [r for r in roots if folder_ok(r[2], market)]
    return max(roots, key=lambda r: r[:2])[2] if roots else None


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
    from studies.trader_data import FolderDataset, panel as TP
    return TP.cache_path(FolderDataset(folder, market))


def source_digest(folder, market):
    """SHA-256 of what a panel is built from (raw bars, actions, list) and the builder's version."""
    from studies.trader_data import FolderDataset
    return FolderDataset(folder, market).digest()


def panel(folder, market):
    """The panel of one fetch-layout folder, built by the one panel builder (studies.trader_data.panel)."""
    from studies.trader_data import FolderDataset
    return FolderDataset(folder, market).panel()


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
    if fetch:
        CACHE.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(have, ensure_ascii=False, indent=0), encoding='utf-8')
    return {c: have.get(c, '') for c in codes}
