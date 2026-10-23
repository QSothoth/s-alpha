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
import math
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np

from .dataset import ACTION_COLUMNS, COLUMNS, Dataset, FolderDataset
from . import providers as PV

SNAP_MATCH = .95
OVERLAP_BAD = .01
TOL = 1e-6


def valid_bar(values):
    return (len(values) == 6 and all(isinstance(v, (int, float)) and math.isfinite(v) for v in values)
            and min(values[:4]) > 0 and values[1] >= values[2] and min(values[4:]) >= 0)


def rejected_bar(code, day, values):
    return dict(code=code, day=day, reason='invalid OHLCV',
                values=[v if isinstance(v, (int, float)) and math.isfinite(v) else None for v in values])


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

    def cached_records(self):
        path = self.dir / 'bars_raw.csv.gz'
        if not path.exists():
            return
        from studies.trend_breakout import panel as P
        yield from P.read_bars(path)

    def rejected_cached_bars(self):
        return [rejected_bar(c, d, v) for c, d, v in self.cached_records() if not valid_bar(v)]

    def cached_rows(self):
        out = {}
        for code, day, values in self.cached_records():
            if valid_bar(values):
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
            rejected = {(r['code'], r['day']) for r in self.rejected_cached_bars()}
            for c, v in P.read_actions(path).items():
                out[c] = sorted(set(out.get(c, [])) | {a for a in v if (c, a[0]) not in rejected})
        return out

    def digest(self):
        h = hashlib.sha256(self.base.digest().encode())
        h.update(b'validated live bars v1')
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
        date.fromisoformat(last)
        if last > today:
            raise RuntimeError(f'{self.market}: stored session {last} is after local date {today}')
        sess = sessions if sessions is not None else self.provider_sessions(last, today)
        sess = sorted(set(d for d in sess if last <= d <= today))
        if last not in sess:
            raise RuntimeError(f'{self.market}: trading calendar omits stored session {last}')
        zone, close_at = PV.CLOSE[self.market]
        open_at = PV.OPEN[self.market][1]
        closed = today in sess and mnow.time() >= close_at
        trading = today in sess and open_at <= mnow.time() < close_at
        if last == today and not closed:
            raise RuntimeError(f'{self.market}: stored session {last} has not closed')
        complete = [d for d in sess if d > last and (d < today or closed)]
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
        expected = complete[-1] if complete else last
        report = dict(market=self.market, last_before=last, missing=complete, method=None, rows=0, actions=0,
                      expected_last_day=expected, last_day=last, status='current',
                      checked_at=(now or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat(timespec='seconds'))
        if not complete:
            rejected = {r['code']: r for r in self.rejected_cached_bars() if r['day'] == last}
            committed = False
            for entry in reversed(self.log()):
                if entry.get('last_day') == last or last in entry.get('days', []):
                    committed = True
                    rejected.update({r['code']: r for r in entry.get('rejected_bars', []) if r['day'] == last})
                    if len(p0['days']) > 1:
                        prev = np.isfinite(p0['raw_close'][-2]) & (p0['volume'][-2] > 0)
                        current = np.isfinite(p0['raw_close'][-1]) & (p0['volume'][-1] > 0)
                        covered, total = int(np.sum(prev & current)), int(np.sum(prev))
                        if not total or covered / total < SNAP_MATCH:
                            raise RuntimeError(f'{self.market}: insufficient trading-name coverage in cache {covered}/{total}')
                        report['session_coverage'] = {last: [covered, total]}
                    break
            if not committed and any(d == last for _, d, _ in self.cached_records()):
                raise RuntimeError(f'{self.market}: cached session {last} has no completed update record')
            report['rejected_bars'] = list(rejected.values())
            return report
        codes = [str(c) for c in p0['codes']]
        raw = p0['raw_close']
        prior_trading = {c for j, c in enumerate(codes)
                         if np.isfinite(raw[-1, j]) and raw[-1, j] > 0
                         and np.isfinite(p0['volume'][-1, j]) and p0['volume'][-1, j] > 0}
        if not prior_trading:
            raise RuntimeError(f'{self.market}: no trading names in stored session {last}')
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
        received = {day: set() for day in complete}
        known = set(codes)
        seen_rows = set()
        accepted, rejected = [], report.get('rejected_bars', [])
        for row in rows:
            c, day, *values = row
            if c not in known or day not in received or len(values) != 6:
                raise RuntimeError(f'{self.market}: invalid provider bar identity for {c} on {day}')
            if (c, day) in seen_rows:
                raise RuntimeError(f'{self.market}: duplicate provider bar for {c} on {day}')
            seen_rows.add((c, day))
            if not valid_bar(values):
                rejected.append(rejected_bar(c, day, values))
                continue
            accepted.append(row)
            if values[4] > 0:
                received[day].add(c)
        rows = accepted
        rejected_keys = {(r['code'], r['day']) for r in rejected}
        acts = [a for a in acts if (a[0], a[1]) not in rejected_keys]
        if any(a[0] not in known or a[1] not in received or not math.isfinite(a[2]) or a[2] <= 0
               or not math.isfinite(a[3]) for a in acts):
            raise RuntimeError(f'{self.market}: invalid corporate action')
        report['rejected_bars'] = rejected
        counts = {day: len(names) for day, names in received.items()}
        absent = [day for day, count in counts.items() if not count]
        if absent:
            raise RuntimeError(f'{self.market}: no trading bars for completed sessions {absent}')
        coverage = {day: [len(names & prior_trading), len(prior_trading)] for day, names in received.items()}
        incomplete = {day: pair for day, pair in coverage.items() if pair[0] / pair[1] < SNAP_MATCH}
        if incomplete:
            raise RuntimeError(f'{self.market}: insufficient trading-name coverage (received/prior) {incomplete}')
        self.dir.mkdir(parents=True, exist_ok=True)
        append(self.dir / 'bars_raw.csv.gz', rows, COLUMNS)
        append(self.dir / 'actions.csv.gz', acts, ACTION_COLUMNS)
        report.update(rows=len(rows), actions=len(acts), days=complete, digest=self.digest(),
                      last_day=expected, status='updated', session_rows=counts, session_coverage=coverage,
                      utc=datetime.now(timezone.utc).isoformat(timespec='seconds'))
        log = self.log() + [report]
        (self.dir / 'log.json').write_text(json.dumps(log, indent=1, ensure_ascii=False), encoding='utf-8')
        return report

    @staticmethod
    def from_snapshot(prov, codes, day, last_raw):
        snap = prov.snapshot(codes)
        rows, acts, rejected, match, seen = [], [], [], 0, 0
        for c in codes:
            s = snap.get(c)
            if not s or not s['trading']:
                continue
            if not math.isfinite(s['prev_close']) or s['prev_close'] <= 0:
                rejected.append(dict(rejected_bar(c, day, [s[k] for k in
                                     ('open', 'high', 'low', 'close', 'volume', 'turnover')]),
                                     reason='invalid previous close'))
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
        return rows, acts, dict(prev_close_match=[match, seen], snapshot_names=len(snap), rejected_bars=rejected)

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
