"""A frozen dataset continued to the latest session: base folder + an append-only cache of later sessions in
data/trader-live/<base tag>/<market>/ (bars_raw.csv.gz, actions.csv.gz, log.json; the fetch layout).

update(now) fills only what is missing, from the provider:
  * exactly one finished session missing and today's session not yet open: one snapshot of the whole list
    (seconds); a corporate action shows as the exchange's previous close differing from our last raw close and is
    recorded as factor_a = prev_close / our close
  * more sessions missing (or today's session already trading): a history re-read of the window from the last
    stored session, whose overlapping day must equal what is stored (raw OHLC), with the source's own actions
Nothing is ever rewritten.  Checks that stop an update: the snapshot's previous closes must match our last closes
for at least SNAP_MATCH of the trading names (otherwise the snapshot is not the session we think it is), and a
history overlap (the unadjusted close of our last session) may differ for at most OVERLAP_BAD of the names.
"""
from __future__ import annotations

import csv
import gzip
import hashlib
import io
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np

from .dataset import ACTION_COLUMNS, COLUMNS, Dataset, FolderDataset
from . import providers as PV

SNAP_MATCH = .95
OVERLAP_BAD = .01
TOL = 1e-6


def market_now(market, now=None):
    return (now or datetime.now(timezone.utc)).astimezone(ZoneInfo(PV.CLOSE[market][0]))


def append(path, rows, header):
    new = not path.exists()
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator='\n')
    if new:
        w.writerow(header)
    w.writerows(rows)
    with gzip.open(path, 'at', encoding='utf-8', newline='') as f:
        f.write(buf.getvalue())


class LiveDataset(Dataset):
    def __init__(self, base: FolderDataset, root, provider=None):
        self.base, self.market = base, base.market
        self.dir = Path(root) / base.market
        self.provider = provider or (lambda: PV.get(base.market))

    @property
    def id(self):
        return f'live:{self.base.id}'

    def stocks(self):
        return self.base.stocks()

    def rule(self):
        return self.base.rule()

    def cached_rows(self):
        path = self.dir / 'bars_raw.csv.gz'
        if not path.exists():
            return {}
        from studies.trend_breakout import panel as P
        out = {}
        for code, day, values in P.read_bars(path):
            out.setdefault(code, []).append((day, values))
        return {c: sorted(v) for c, v in out.items()}

    def rows(self):
        extra = self.cached_rows()
        cur = None
        for code, day, values in self.base.rows():
            if code != cur:
                for d, v in extra.pop(cur, []):
                    yield cur, d, v
                cur = code
            yield code, day, values
        for d, v in extra.pop(cur, []):
            yield cur, d, v
        for code in sorted(extra):
            for d, v in extra[code]:
                yield code, d, v

    def actions(self):
        out = {c: list(v) for c, v in self.base.actions().items()}
        path = self.dir / 'actions.csv.gz'
        if path.exists():
            from studies.trend_breakout import panel as P
            for c, v in P.read_actions(path).items():
                out[c] = sorted(set(out.get(c, [])) | set(v))
        return out

    def digest(self):
        h = hashlib.sha256(self.base.digest().encode())
        for name in ('bars_raw.csv.gz', 'actions.csv.gz'):
            path = self.dir / name
            h.update(path.read_bytes() if path.exists() else b'')
        return h.hexdigest()

    def log(self):
        path = self.dir / 'log.json'
        return json.loads(path.read_text(encoding='utf-8')) if path.exists() else []

    # ----- the update -----
    def plan(self, last, now=None, sessions=None):
        """(complete sessions after `last`, snapshot usable): finished sessions up to now, and whether the regular
        session that a snapshot shows is the newest finished one."""
        mnow = market_now(self.market, now)
        today = mnow.date().isoformat()
        start = (date.fromisoformat(last) + timedelta(days=1)).isoformat()
        if start > today:                                   # already holds today's bar
            return [], False
        sess = sessions if sessions is not None else self.provider_sessions(start, today)
        sess = [d for d in sess if start <= d <= today]
        zone, close_at = PV.CLOSE[self.market]
        open_at = PV.OPEN[self.market][1]
        closed = today in sess and mnow.time() >= close_at
        trading = today in sess and open_at <= mnow.time() < close_at
        complete = [d for d in sess if d < today or closed]
        return complete, len(complete) == 1 and not trading

    def provider_sessions(self, start, end):
        p = self.provider()
        try:
            return p.sessions(start, end)
        finally:
            p.close()

    def update(self, now=None):
        """Bring the cache to the newest finished session; returns what was done."""
        p0 = self.panel()
        last = str(p0['days'][-1])
        complete, snap_ok = self.plan(last, now)
        report = dict(market=self.market, last_before=last, missing=complete, method=None, rows=0, actions=0)
        if not complete:
            return report
        codes = [str(c) for c in p0['codes']]
        raw = p0['raw_close']
        last_raw = {}
        for j, c in enumerate(codes):
            ok = np.flatnonzero(np.isfinite(raw[:, j]))
            if len(ok):
                last_raw[c] = (str(p0['days'][ok[-1]]), float(raw[ok[-1], j]))
        close_last = {c: float(raw[-1, j]) for j, c in enumerate(codes)}   # unadjusted closes on `last`
        del p0
        prov = self.provider()
        try:
            if snap_ok:
                rows, acts, chk = self.from_snapshot(prov, codes, complete[0], last_raw)
                report.update(method='snapshot', **chk)
            else:
                rows, acts, chk = self.from_history(prov, codes, last, complete, close_last)
                report.update(method='history', **chk)
        finally:
            prov.close()
        self.dir.mkdir(parents=True, exist_ok=True)
        append(self.dir / 'bars_raw.csv.gz', rows, COLUMNS)
        append(self.dir / 'actions.csv.gz', acts, ACTION_COLUMNS)
        report.update(rows=len(rows), actions=len(acts), days=complete, digest=self.digest(),
                      utc=datetime.now(timezone.utc).isoformat(timespec='seconds'))
        log = self.log() + [report]
        (self.dir / 'log.json').write_text(json.dumps(log, indent=1, ensure_ascii=False), encoding='utf-8')
        return report

    @staticmethod
    def from_snapshot(prov, codes, day, last_raw):
        snap = prov.snapshot(codes)
        rows, acts, match, seen = [], [], 0, 0
        for c in codes:
            s = snap.get(c)
            if not s or not s['trading']:
                continue
            if c in last_raw:
                seen += 1
                ours = last_raw[c][1]
                if abs(s['prev_close'] - ours) <= TOL * ours:
                    match += 1
                elif ours > 0 and s['prev_close'] > 0:
                    acts.append((c, day, s['prev_close'] / ours, 0.0))
            rows.append((c, day, s['open'], s['high'], s['low'], s['close'], s['volume'], s['turnover']))
        if not seen or match / seen < SNAP_MATCH:
            raise RuntimeError(f'snapshot is not the session after ours: previous close matches {match}/{seen}')
        return rows, acts, dict(prev_close_match=[match, seen], snapshot_names=len(snap))

    @staticmethod
    def from_history(prov, codes, last, complete, close_last):
        want = set(complete)
        rows, acts, bad, failed, checked = [], [], [], [], 0
        for code, raw, actions in prov.history(codes, last, complete[-1]):
            if not raw:
                failed.append(code)
                continue
            for r in raw:
                if r[1] == last and np.isfinite(close_last.get(code, np.nan)):
                    checked += 1
                    if abs(r[5] - close_last[code]) > TOL * close_last[code]:
                        bad.append(code)
                elif r[1] in want:
                    rows.append(tuple(r))
            acts += [a for a in actions if last < a[1] <= complete[-1]]
        if checked and len(bad) / checked > OVERLAP_BAD:
            raise RuntimeError(f'history disagrees with stored bars on {last} for {len(bad)}/{checked} names')
        return rows, acts, dict(overlap_bad=bad[:20], overlap_checked=checked, failed=failed[:50],
                                n_failed=len(failed))


class Provisional(Dataset):
    """A dataset plus today's not-yet-final bars (a snapshot during the session); never cached or stored."""

    def __init__(self, inner, rows):
        self.inner, self.market, self.extra = inner, inner.market, rows

    @property
    def id(self):
        return f'provisional:{self.inner.id}'

    def stocks(self):
        return self.inner.stocks()

    def rule(self):
        return self.inner.rule()

    def rows(self):
        extra = {}
        for r in self.extra:
            extra.setdefault(r[0], []).append((r[1], list(r[2:])))
        cur = None
        for code, day, values in self.inner.rows():
            if code != cur:
                for d, v in extra.pop(cur, []):
                    yield cur, d, v
                cur = code
            yield code, day, values
        for d, v in extra.pop(cur, []):
            yield cur, d, v

    def actions(self):
        return self.inner.actions()

    def digest(self):
        return hashlib.sha256((self.inner.digest() + repr(self.extra)).encode()).hexdigest()

    def panel(self, upto=None):
        from . import panel
        return panel.build(self, upto, cache=False)
