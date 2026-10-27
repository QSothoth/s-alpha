"""The one data interface of every trader system, in research (replication, comparison) and in live running (the
trader-screens board): docs/TRADER_PROTOCOL_CN.md.

    from studies import trader_data as TD
    p = TD.load('us')                        # panel in the configured mode
    p = TD.load('us', mode='frozen')         # the frozen release only (research, gates, comparisons)
    p = TD.load('us', mode='live')           # the release continued to the newest finished session
    ds = TD.dataset('hk', mode='live'); ds.update(); ds.panel()
    h = TD.load_hourly('us')                 # hourly bars, same modes (hourly.py)

Mode and version come from the arguments, else from TRADER_DATA_MODE (frozen | live, default frozen) and
TRADER_DATA_TAG (default trader-data-v1).  Both modes read the same frozen bars and build panels with the same
function; live adds an append-only cache of the sessions after the release (data/trader-live/<tag>/<market>),
filled on demand by a Provider (OpenD for US / HK, Sina for A-shares) from one snapshot of the list per missing
session, or a history re-read when several sessions are missing.  Dataset and Provider are the extension points.
"""
from __future__ import annotations

import os
from pathlib import Path

from .dataset import Dataset, FolderDataset
from .live import LiveDataset, Provisional
from . import panel, providers

ROOT = Path(__file__).resolve().parents[2]
MODES = ('frozen', 'live')
DEFAULT_TAG = 'trader-data-v1'
LIVE_ROOT = ROOT / 'data' / 'trader-live'


def resolve_mode(value=None):
    m = value or os.environ.get('TRADER_DATA_MODE', 'frozen')
    if m not in MODES:
        raise ValueError(f'TRADER_DATA_MODE {m!r}: one of {MODES}')
    return m


def tag(value=None):
    return value or os.environ.get('TRADER_DATA_TAG', DEFAULT_TAG)


def frozen(market, version=None):
    ds = FolderDataset(ROOT / 'data' / tag(version), market)
    if not ds.exists():
        raise FileNotFoundError(f'{ds.sub}: unpack the GitHub release {tag(version)} into data/ (docs/DATA.md)')
    return ds


def dataset(market, mode=None, version=None, provider=None):
    """The market's Dataset in the given mode."""
    base = frozen(market, version)
    if resolve_mode(mode) == 'frozen':
        return base
    return LiveDataset(base, LIVE_ROOT / tag(version), provider)


def load(market, mode=None, version=None, upto=None, update=True, now=None, provisional=False):
    """The market's panel.  live: first fills the missing finished sessions (update=False reads what is cached);
    provisional=True adds today's bars from a snapshot taken during the session, never stored."""
    ds = dataset(market, mode, version)
    if isinstance(ds, LiveDataset):
        if update:
            ds.update(now)
        if provisional:
            prov = ds.provider()
            try:
                snap = prov.snapshot([s['code'] for s in ds.stocks()])
            finally:
                prov.close()
            day = live_today(market, now)
            rows = [(c, day, s['open'], s['high'], s['low'], s['close'], s['volume'], s['turnover'])
                    for c, s in snap.items() if s['trading']]
            ds = Provisional(ds, rows)
    return ds.panel(upto)


def hourly_dataset(market, mode=None, version=None, provider=None):
    """The market's hourly Dataset (studies/trader_data/hourly.py): the frozen release TRADER_HOURLY_TAG (default
    trader-hourly-v1), in live mode plus the bars after it."""
    from . import hourly as H
    base = H.HourlyDataset(ROOT / 'data' / H.tag(version), market)
    if not base.exists():
        raise FileNotFoundError(f'{base.sub}: unpack the GitHub release {H.tag(version)} into data/ (docs/DATA.md)')
    if resolve_mode(mode) == 'frozen':
        return base
    return H.LiveHourly(base, H.LIVE_ROOT / H.tag(version), provider)


def load_hourly(market, mode=None, version=None, upto=None, update=True):
    """The market's hourly panel: (bars x codes) forward-adjusted, with 'times' (bar end, exchange time) and
    'days'.  live: first appends the bars after the newest stored one (update=False reads what is cached)."""
    from . import hourly as H
    ds = hourly_dataset(market, mode, version)
    if isinstance(ds, H.LiveHourly) and update:
        ds.update()
    return ds.panel(upto)


def live_today(market, now=None):
    from .live import market_now
    return market_now(market, now).date().isoformat()
