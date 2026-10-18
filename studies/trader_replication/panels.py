"""Research daily panels for every trader study: the same point-in-time universes Martin Luk's research uses
(data/martin-luk-cache: US 3433 names from 2023-01, HK 505 and A-shares 1697 from 2023-10, all forward-adjusted),
read straight from the cache files so no study depends on another study's code.

`arrays(market)` returns the A dict study.Study expects (days, codes, market, open / high / low / close / turnover
/ raw, to20, adr, has) plus `F`, a trader_screens.screens.Feat over the same panel, so the board's draft screens run
unchanged on research data.  US bars carry no share volume: volume = turnover / adjusted close (shares on the
adjusted basis, the same basis trader_screens.data builds).
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / 'data' / 'martin-luk-cache'
FILES = {'us': 'broad_daily.npz', 'hk': 'hk.npz', 'cn': 'cn.npz'}


def load(market):
    z = np.load(CACHE / FILES[market], allow_pickle=False)
    p = {k: z[k] for k in z.files}
    if 'dates' in p:
        p['days'] = p.pop('dates')
    if 'volume' not in p:
        with np.errstate(invalid='ignore', divide='ignore'):
            p['volume'] = (p['turnover'] / p['close']).astype(np.float32)
    return p


def arrays(market):
    from studies.trader_screens import screens as S
    p = load(market)
    F = S.Feat(p, market)
    A = dict(days=p['days'], codes=p['codes'], market=market, F=F,
             open=F.o, high=F.h, low=F.l, close=F.c, turnover=F.turnover, raw=F.raw, volume=F.v)
    A['to20'] = F.to20
    A['adr'] = F.adr
    A['has'] = np.isfinite(F.c)
    return A
