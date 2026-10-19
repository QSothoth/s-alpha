"""Daily arrays of every trader study, from the one data interface studies.trader_data (docs/TRADER_PROTOCOL_CN.md).

The frozen release (TRADER_DATA_TAG, default trader-data-v1; GitHub release of the same name):

    US  3433 names (price >= 1 USD, 20-day turnover >= 2M USD as of 2026-10-17)
    HK   505 names (20-day turnover >= 20M HKD as of 2026-10-15)
    CN  1697 names (market cap >= 10bn CNY as of 2026-10-15, no Beijing exchange)

All three markets cover 2023-01-03 -> 2026-10-16; 2023 is indicator warm-up and research evaluates on WINDOW.  With
TRADER_DATA_MODE=live the same arrays continue to the newest finished session (live running); research, gates and
comparisons run frozen.  `arrays(market, upto)` returns the A dict study.Study expects (days, codes, market, open /
high / low / close / turnover / raw / volume, to20, adr, has, digest) plus `F`, a trader_screens.screens.Feat over the
same panel, so the board's screens run unchanged on research data.  `upto` (ISO date) cuts the panel after that day:
the look-ahead gate compares what a system decides on days <= upto with and without the later bars.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from studies import trader_data as TD

ROOT = Path(__file__).resolve().parents[2]
DEFAULT = TD.DEFAULT_TAG
TAG = TD.tag()
DATASET = ROOT / 'data' / TAG
WINDOW = ('2024-01-02', '2026-10-16')          # common evaluation window, all markets
PIN = Path(__file__).resolve().parent / 'DATA_PIN.json'


def fingerprint(market):
    """Digest of the frozen release's market (what every panel built from it carries)."""
    return TD.frozen(market).digest()


def pins():
    return json.loads(PIN.read_text(encoding='utf-8')) if PIN.exists() else {}


def pinned():
    """The committed digests of the current version ({'tag', 'markets': {market: sha256}}); `TRADER_DATA_TAG=<tag>
    python -m studies.trader_replication.panels pin us,hk` writes them once a version is complete."""
    return {'tag': TAG, 'markets': pins().get(TAG, {})}


def pin(markets=('us', 'hk', 'cn')):
    allp = pins()
    allp[TAG] = {**allp.get(TAG, {}), **{m: fingerprint(m) for m in markets}}
    PIN.write_text(json.dumps(allp, indent=1, sort_keys=True) + '\n', encoding='utf-8')


def load(market, upto=None, mode=None):
    return TD.load(market, mode=mode, upto=upto)


def arrays(market, upto=None, mode=None):
    from studies.trader_screens import screens as S
    p = load(market, upto, mode)
    F = S.Feat(p, market)
    A = dict(days=p['days'], codes=p['codes'], market=market, F=F,
             open=F.o, high=F.h, low=F.l, close=F.c, turnover=F.turnover, raw=F.raw, volume=F.v)
    A['to20'] = F.to20
    A['adr'] = F.adr
    A['has'] = np.isfinite(F.c)
    A['digest'] = p['digest']
    return A


if __name__ == '__main__':
    import sys
    if sys.argv[1] == 'pin':                    # pin [us,hk,cn]
        pin(tuple(sys.argv[2].split(',')) if len(sys.argv) > 2 else ('us', 'hk', 'cn'))
