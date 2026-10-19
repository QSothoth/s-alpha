"""What a market's daily data is, independent of where it comes from (docs/TRADER_PROTOCOL_CN.md).

A Dataset is a fixed stock list with its rule, unadjusted daily bars and corporate actions (OpenD convention: a
price before the ex-date is worth factor_a * price + factor_b after it).  Bars are never stored adjusted: a new
action would rescale every earlier price, so a dataset could not be extended without rewriting it.  The panel
(panel.py) applies the actions; its digest names exactly what it was built from.

    FolderDataset   one folder in the studies.trend_breakout.fetch layout (<root>/<market>/bars_raw.csv.gz,
                    actions.csv.gz, universe.json), e.g. the frozen release data/trader-data-v1
    LiveDataset     (live.py) a frozen folder plus an append-only cache of the sessions after it
"""
from __future__ import annotations

import hashlib
import json
from abc import ABC, abstractmethod
from pathlib import Path

COLUMNS = ('code', 'date', 'open', 'high', 'low', 'close', 'volume', 'turnover')
ACTION_COLUMNS = ('code', 'ex_date', 'factor_a', 'factor_b')


class Dataset(ABC):
    """One market's daily data.  Subclasses supply the list, the bars, the actions and a digest of them."""
    market = ''

    @property
    @abstractmethod
    def id(self) -> str:
        """Stable identity (cache names, reports)."""

    @abstractmethod
    def stocks(self) -> list:
        """[{'code': 'US.AAPL', 'name': ...}, ...]: the fixed list."""

    @abstractmethod
    def rule(self) -> dict:
        """The rule the list was built with (universe.json 'filter')."""

    @abstractmethod
    def rows(self):
        """(code, day, [open, high, low, close, volume, turnover]) unadjusted, grouped by code, days ascending."""

    @abstractmethod
    def actions(self) -> dict:
        """{code: [(ex_date, factor_a, factor_b), ...]}"""

    @abstractmethod
    def digest(self) -> str:
        """SHA-256 of everything the panel is built from, with the panel builder's version."""

    def names(self) -> dict:
        return {s['code']: s.get('name', '') for s in self.stocks()}

    def panel(self, upto=None) -> dict:
        """Forward-adjusted (days x codes) panel; see panel.build."""
        from . import panel
        return panel.build(self, upto)

    def __str__(self):
        return self.id


class FolderDataset(Dataset):
    """A dataset folder in the fetch layout; read-only."""

    def __init__(self, root, market):
        self.root, self.market = Path(root), market
        self.sub = self.root / market

    @property
    def id(self):
        return f'{self.root.resolve()}/{self.market}'

    def exists(self):
        return (self.sub / 'universe.json').exists()

    def universe(self):
        return json.loads((self.sub / 'universe.json').read_text(encoding='utf-8'))

    def stocks(self):
        return self.universe()['stocks']

    def rule(self):
        return self.universe().get('filter')

    def rows(self):
        from studies.trend_breakout import panel as P
        return P.read_bars(self.sub / 'bars_raw.csv.gz')

    def actions(self):
        from studies.trend_breakout import panel as P
        return P.read_actions(self.sub / 'actions.csv.gz')

    def digest(self):
        from .panel import VERSION
        h = hashlib.sha256(f'panel v{VERSION}'.encode())
        for name in ('bars_raw.csv.gz', 'actions.csv.gz', 'universe.json'):
            h.update((self.sub / name).read_bytes())
        return h.hexdigest()
