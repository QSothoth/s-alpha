"""Trade ledger of the trader being replicated: one row per publicly documented trade (see skills/trader-replication).

Columns: id, ticker, side (long/short), entry_date, window_lo, window_hi, precision, setup, trigger, stop_pct,
outcome, r_multiple, source, note.  precision is
  exact  - the day is pinned by his own statement: a stream date, a stated price that trades on one day only, a named event;
  chart  - the day is inferred by matching his chart description to daily bars (window_lo..window_hi holds the doubt);
  window - only a period is known (useful for watchlist recall, not for signal-day recall).
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

PRECISIONS = ('exact', 'chart', 'window')


@dataclass(frozen=True)
class Trade:
    id: str
    ticker: str
    side: str
    entry_date: str
    window_lo: str
    window_hi: str
    precision: str
    setup: str
    trigger: str
    stop_pct: float | None
    outcome: str
    r_multiple: float | None
    source: str
    note: str

    @property
    def dated(self):
        """True when the entry day itself is known (exact or chart-matched), not just a period."""
        return self.precision in ('exact', 'chart')


def _num(s):
    return float(s) if s not in ('', None) else None


def load(path):
    rows = []
    with open(path, newline='', encoding='utf-8') as fh:
        for r in csv.DictReader(fh):
            t = Trade(r['id'], r['ticker'].strip().upper(), r['side'], r['entry_date'], r['window_lo'],
                      r['window_hi'], r['precision'], r['setup'], r['trigger'], _num(r['stop_pct']), r['outcome'],
                      _num(r['r_multiple']), r['source'], r['note'])
            check(t)
            rows.append(t)
    ids = [t.id for t in rows]
    if len(set(ids)) != len(ids):
        raise ValueError('duplicate trade ids in %s' % Path(path).name)
    return rows


def check(t):
    if t.side not in ('long', 'short'):
        raise ValueError(f'{t.id}: side {t.side!r}')
    if t.precision not in PRECISIONS:
        raise ValueError(f'{t.id}: precision {t.precision!r}')
    if not (t.window_lo and t.window_hi and t.window_lo <= t.window_hi):
        raise ValueError(f'{t.id}: bad window {t.window_lo}..{t.window_hi}')
    if t.dated and not (t.window_lo <= t.entry_date <= t.window_hi):
        raise ValueError(f'{t.id}: entry_date outside its window')
    if t.precision == 'exact' and t.window_lo != t.window_hi:
        raise ValueError(f'{t.id}: an exact trade has a one-day window')


def split(trades, cutoff):
    """Selection = trades whose window starts before `cutoff` (ISO date); validation = the rest."""
    return [t for t in trades if t.window_lo < cutoff], [t for t in trades if t.window_lo >= cutoff]
