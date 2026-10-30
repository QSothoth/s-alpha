"""Hourly bars through the same interface as the daily ones (docs/TRADER_PROTOCOL_CN.md, section 6).

A frozen hourly release is a folder like the daily one: <root>/<market>/bars_raw.csv.gz (unadjusted regular-session
60-minute bars, `time` = the bar's end in exchange time, e.g. 2020-01-02 10:30:00), bars_qfq.csv.gz (the source's
own forward adjustment, audit only), actions.csv.gz (OpenD get_rehab, the daily convention) and universe.json (the
list and the rule it was built with).  The panel applies the actions the way the daily panel does, per bar.

    from studies import trader_data as TD
    h = TD.load_hourly('us')                 # frozen release (TRADER_HOURLY_TAG, default trader-hourly-v1)
    h = TD.load_hourly('us', mode='live')    # plus the bars after it, from OpenD's subscription (no history quota)

    PY="nice -n 19 env OPENBLAS_NUM_THREADS=1 PYTHONUTF8=1 /opt/opend-us-options/.venv/bin/python"
    $PY -m studies.trader_data.hourly fetch data/trader-hourly-v1 us 2020-01-01 2026-10-23 <codes.json> <rule.json>

`fetch` uses request_history_kline (one history-quota unit per stock not fetched in the last 30 days: ask first,
AGENTS.md) and is resumable (progress.json).  Live mode reads get_cur_kline(K_60M, 1000) per stock (about seven
months, no quota) and appends only bars after the newest stored one, after checking the overlap.
"""
from __future__ import annotations

import csv
from datetime import datetime, timezone
import gzip
import hashlib
import json
import os
from itertools import groupby
from pathlib import Path
import re
import time

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TAG = 'trader-hourly-v1'
LIVE_ROOT = ROOT / 'data' / 'trader-live-hourly'
CACHE = ROOT / 'data' / 'trader-data' / 'cache'
VERSION = 1
COLUMNS = ('code', 'time', 'open', 'high', 'low', 'close', 'volume', 'turnover')
ACTION_COLUMNS = ('code', 'ex_date', 'factor_a', 'factor_b')
FIELDS = ('open', 'high', 'low', 'close', 'volume', 'turnover', 'raw_close')


def tag(value=None):
    return value or os.environ.get('TRADER_HOURLY_TAG', DEFAULT_TAG)


# ----- files -----

def write_rows(path, rows, header):
    new = not Path(path).exists()
    with gzip.open(path, 'at', encoding='utf-8', newline='') as f:
        w = csv.writer(f)
        if new:
            w.writerow(header)
        w.writerows(rows)


def read_bars(path):
    """(code, time, [open, high, low, close, volume, turnover]) in file order."""
    with gzip.open(path, 'rt', encoding='utf-8', newline='') as f:
        rows = csv.reader(f)
        if tuple(next(rows)) != COLUMNS:
            raise ValueError(f'unexpected header in {path}')
        for row in rows:
            if row:
                yield row[0], row[1], [float(x) for x in row[2:]]


def read_actions(path):
    out = {}
    with gzip.open(path, 'rt', encoding='utf-8', newline='') as f:
        rows = csv.reader(f)
        if tuple(next(rows)) != ACTION_COLUMNS:
            raise ValueError(f'unexpected header in {path}')
        for code, ex_date, a, b in rows:
            out.setdefault(code, set()).add((ex_date, float(a), float(b)))
    return {c: sorted(v) for c, v in out.items()}


def valid(values):
    """A usable bar: finite positive prices, low <= open / close <= high, some volume.  A bar with no volume is no
    trade: its price can be a stale print (BMNR 2025-06-05 10:30 shows 0.40, the pre-split price, between 7 USD bars)."""
    o, h, l, c, v, t = values
    return (all(np.isfinite(values)) and min(o, h, l, c) > 0 and v > 0 and l <= min(o, c) + 1e-9
            and h >= max(o, c) - 1e-9)


# ----- datasets -----

class HourlyDataset:
    """A frozen hourly folder; read-only."""

    def __init__(self, root, market):
        self.root, self.market = Path(root), market
        self.sub = self.root / market

    @property
    def id(self):
        return f'{self.root.resolve()}/{self.market}/hourly'

    def exists(self):
        return (self.sub / 'universe.json').exists()

    def universe(self):
        return json.loads((self.sub / 'universe.json').read_text(encoding='utf-8'))

    def stocks(self):
        return self.universe()['stocks']

    def rows(self):
        return read_bars(self.sub / 'bars_raw.csv.gz')

    def actions(self):
        return read_actions(self.sub / 'actions.csv.gz')

    def digest(self):
        h = hashlib.sha256(f'hourly panel v{VERSION}'.encode())
        for name in ('bars_raw.csv.gz', 'actions.csv.gz', 'universe.json'):
            h.update((self.sub / name).read_bytes())
        return h.hexdigest()

    def panel(self, upto=None):
        return build(self, upto)


class LiveHourly(HourlyDataset):
    """A frozen hourly folder plus an append-only cache of the bars after it (cache/<market>/bars_raw.csv.gz and
    actions.csv.gz, the newest actions OpenD knows)."""

    def __init__(self, base, cache_root, provider=None):
        self.base = base
        self.market = base.market
        self.cache = Path(cache_root) / base.market
        self._provider = provider

    @property
    def id(self):
        return f'{self.base.id}+live:{self.cache.resolve()}'

    def stocks(self):
        return self.base.stocks()

    def universe(self):
        return self.base.universe()

    def rows(self):
        extra = {}
        if (self.cache / 'bars_raw.csv.gz').exists():
            for code, grp in groupby(read_bars(self.cache / 'bars_raw.csv.gz'), key=lambda r: r[0]):
                extra.setdefault(code, []).extend(grp)
        for code, grp in groupby(self.base.rows(), key=lambda r: r[0]):
            yield from grp
            yield from extra.pop(code, [])
        for code in sorted(extra):
            yield from extra[code]

    def actions(self):
        p = self.cache / 'actions.csv.gz'
        return read_actions(p) if p.exists() else self.base.actions()

    def digest(self):
        h = hashlib.sha256(self.base.digest().encode())
        for name in ('bars_raw.csv.gz', 'actions.csv.gz'):
            p = self.cache / name
            if p.exists():
                h.update(p.read_bytes())
        return h.hexdigest()

    def last_times(self):
        last = {}
        for code, t, _ in self.rows():
            last[code] = t
        return last

    def last_closes(self):
        last = {}
        for code, t, v in self.rows():
            last[code] = (t, v[3])
        return last

    def update(self, max_mismatch=.01):
        """Append the bars after the newest stored one from get_cur_kline(K_60M, 1000), raw.  The bars both
        sides have must agree (raw close within 0.5%) for all but `max_mismatch` of the stocks that overlap, else
        nothing is written.  Invalid bars are skipped and reported.  Returns a summary."""
        prov = self._provider or OpenDHourly()
        try:
            stored = {}
            for code, t, v in self.rows():
                stored.setdefault(code, {})[t] = v
            got = prov.recent([s['code'] for s in self.stocks()])
            new_rows, rejected, checked, bad = [], [], 0, []
            for code, bars in got.items():
                have = stored.get(code, {})
                last = max(have) if have else ''
                over = [(t, v) for t, v in bars if t in have]
                if over:
                    checked += 1
                    if any(abs(v[3] / have[t][3] - 1) > .005 for t, v in over):
                        bad.append(code)
                for t, v in bars:
                    if t > last:
                        (new_rows if valid(v) else rejected).append((code, t, *v))
            if checked and len(bad) > max_mismatch * checked:
                raise RuntimeError(f'hourly live update: {len(bad)}/{checked} stocks disagree with the stored bars '
                                   f'({bad[:10]}); nothing written')
            if checked == 0 and new_rows:
                raise RuntimeError('hourly live update: no stored bar to compare with; nothing written')
            self.cache.mkdir(parents=True, exist_ok=True)
            new_rows.sort(key=lambda r: (r[0], r[1]))
            if new_rows:
                write_rows(self.cache / 'bars_raw.csv.gz', new_rows, COLUMNS)
            acts = [a for s in self.stocks() for a in prov.actions(s['code'])]
            p = self.cache / 'actions.csv.gz'
            if p.exists():
                p.unlink()
            write_rows(p, acts, ACTION_COLUMNS)
            return dict(appended=len(new_rows), rejected=rejected, checked=checked, mismatched=bad)
        finally:
            if self._provider is None:
                prov.close()


# ----- panel -----

def factors(raw_close, times, actions):
    """Per-bar multiplicative factor (latest bar = 1): an action with ex-date d rescales every bar before the first
    bar on or after d by (a * previous close + b) / previous close (the daily rule, studies/trend_breakout/panel)."""
    raw = np.asarray(raw_close, float)
    step = np.ones(len(raw))
    for ex_date, a, b in actions:
        t = int(np.searchsorted(times, ex_date))
        if 0 < t < len(raw):
            step[t] *= (a * raw[t - 1] + b) / raw[t - 1]
    return np.append(np.cumprod(step[::-1])[::-1][1:], 1.0) if len(raw) else step


def cache_path(ds):
    key = re.sub(r'[^A-Za-z0-9._-]+', '_', ds.id)[-60:]
    return CACHE / f'hourly_{key}_{hashlib.sha256(ds.id.encode()).hexdigest()[:10]}_v{VERSION}.npz'


def assemble(ds):
    actions = ds.actions()
    codes = sorted({s['code'] for s in ds.stocks()})
    ci = {c: i for i, c in enumerate(codes)}
    times = np.array(sorted({t for code, t, _ in ds.rows() if code in ci}))
    ti = {t: i for i, t in enumerate(times)}
    out = {k: np.full((len(times), len(codes)), np.nan, np.float32) for k in FIELDS}
    for code, records in groupby(ds.rows(), key=lambda r: r[0]):
        if code not in ci:
            continue
        tt, rows = [], []
        for _, t, v in records:
            if tt and t <= tt[-1]:
                raise ValueError(f'{ds.id}: {code} bars out of order or repeated at {t}')
            if valid(v):
                tt.append(t)
                rows.append(v)
        if not rows:
            continue
        r = np.array(rows, float)
        f = factors(r[:, 3], np.array(tt), actions.get(code, []))
        idx, j = [ti[t] for t in tt], ci[code]
        for k, n in (('open', 0), ('high', 1), ('low', 2), ('close', 3)):
            out[k][idx, j] = r[:, n] * f
        out['volume'][idx, j] = r[:, 4] / f
        out['turnover'][idx, j] = r[:, 5]
        out['raw_close'][idx, j] = r[:, 3]
    return dict(times=times, days=np.array([t[:10] for t in times]), codes=np.array(codes), **out)


def build(ds, upto=None, cache=True):
    """(bars x codes) forward-adjusted hourly panel, cached by digest; `upto` (a day or a time) cuts after it."""
    digest = ds.digest()
    path = cache_path(ds)
    p = None
    if cache and path.exists():
        with np.load(path) as z:
            if str(z['digest']) == digest:
                p = {k: z[k] for k in z.files}
    if p is None:
        p = assemble(ds)
        if cache:
            CACHE.mkdir(parents=True, exist_ok=True)
            np.savez_compressed(path, digest=np.array(digest), **p)
    p['digest'], p['dataset'] = digest, ds.id
    if upto is not None:
        cut = upto if len(upto) > 10 else upto + ' 99'
        k = int(np.searchsorted(p['times'], cut, side='right'))
        p = {key: (v[:k] if isinstance(v, np.ndarray) and v.ndim and key not in ('codes',) else v)
             for key, v in p.items()}
    return p


def daily(p):
    """Daily bars rebuilt from an hourly panel: (days, open, high, low, close, volume, turnover, raw_close), days x
    codes; raw_close is the day's last unadjusted close (price filters must not read the adjusted one)."""
    days, first = np.unique(p['days'], return_index=True)
    last = np.append(first[1:], len(p['days'])) - 1
    o = np.full((len(days), p['close'].shape[1]), np.nan)
    h, l, c, v, t, rc = (o.copy() for _ in range(6))
    for k, (a, b) in enumerate(zip(first, last)):
        seg = slice(a, b + 1)
        with np.errstate(invalid='ignore'), __import__('warnings').catch_warnings():
            __import__('warnings').simplefilter('ignore', RuntimeWarning)
            oo, cc = p['open'][seg], p['close'][seg]
            fo = np.argmax(np.isfinite(oo), axis=0)
            lc = len(cc) - 1 - np.argmax(np.isfinite(cc[::-1]), axis=0)
            o[k] = oo[fo, np.arange(oo.shape[1])]
            c[k] = cc[lc, np.arange(cc.shape[1])]
            rc[k] = p['raw_close'][seg][lc, np.arange(cc.shape[1])]
            h[k] = np.nanmax(p['high'][seg], axis=0)
            l[k] = np.nanmin(p['low'][seg], axis=0)
            v[k] = np.nansum(p['volume'][seg], axis=0)
            t[k] = np.nansum(p['turnover'][seg], axis=0)
    gone = ~np.isfinite(c)
    v[gone] = np.nan
    t[gone] = np.nan
    return dict(days=days, codes=p['codes'], open=o, high=h, low=l, close=c, volume=v, turnover=t, raw_close=rc)


# ----- the source -----

class OpenDHourly:
    """OpenD: request_history_kline(K_60M) for releases (history quota), get_cur_kline(K_60M, 1000) for live."""
    BATCH, HOLD, WARMUP = 100, 61.0, 8.0

    def __init__(self, host='127.0.0.1', port=11111):
        import futu as ft
        self.ft = ft
        self.q = ft.OpenQuoteContext(host=host, port=port)

    def close(self):
        self.q.close()

    @staticmethod
    def _rows(df):
        return [(r.time_key[:19], [float(r.open), float(r.high), float(r.low), float(r.close), float(r.volume),
                                   float(r.turnover)]) for r in df.itertuples()]

    def history(self, code, start, end, au):
        """All 60-minute bars of one stock in [start, end] (paged; request_history_kline is 60 calls / 30 s)."""
        ft, out, key = self.ft, [], None
        while True:
            time.sleep(.55)
            ret, df, key = self.q.request_history_kline(code, start=start, end=end, ktype=ft.KLType.K_60M,
                                                        autype=au, max_count=1000, page_req_key=key)
            if ret != ft.RET_OK:
                raise RuntimeError(f'request_history_kline {code}: {df}')
            out += self._rows(df)
            if key is None:
                return out

    def recent(self, codes):
        """{code: [(time, values)]}: the last 1000 regular-session 60-minute bars, unadjusted (no quota)."""
        ft, out = self.ft, {}
        for b in range(0, len(codes), self.BATCH):
            batch = list(codes[b:b + self.BATCH])
            ret, err = self.q.subscribe(batch, [ft.SubType.K_60M], subscribe_push=False)
            if ret != ft.RET_OK:
                raise RuntimeError(f'subscribe: {err}')
            t0 = time.time()
            time.sleep(self.WARMUP)
            try:
                for code in batch:
                    ret, df = self.q.get_cur_kline(code, 1000, ft.SubType.K_60M, ft.AuType.NONE)
                    if ret == ft.RET_OK:
                        out[code] = self._rows(df)
            finally:
                time.sleep(max(0.0, self.HOLD - (time.time() - t0)))
                self.q.unsubscribe(batch, [ft.SubType.K_60M])
        return out

    def actions(self, code):
        time.sleep(.55)
        ret, df = self.q.get_rehab(code)
        if ret != self.ft.RET_OK:
            raise RuntimeError(f'get_rehab {code}: {df}')
        return [(code, str(r.ex_div_date)[:10], float(r.forward_adj_factorA), float(r.forward_adj_factorB))
                for r in df.itertuples()]

    def quota(self):
        ret, q = self.q.get_history_kl_quota(get_detail=False)
        return list(q) if ret == self.ft.RET_OK else str(q)


def fetch(out, market, start, end, codes, rule, source=None):
    """Write a frozen hourly release folder (resumable: progress.json lists finished codes)."""
    sub = Path(out) / market
    sub.mkdir(parents=True, exist_ok=True)
    prog_path = sub / 'progress.json'
    prog = json.loads(prog_path.read_text(encoding='utf-8')) if prog_path.exists() else dict(done=[], empty=[])
    src = source or OpenDHourly()
    ft = getattr(src, 'ft', None)
    try:
        before = src.quota()
        for code in codes:
            if code in prog['done'] or code in prog['empty']:
                continue
            raw = src.history(code, start, end, ft.AuType.NONE if ft else 'raw')
            if not raw:
                prog['empty'].append(code)
            else:
                qfq = src.history(code, start, end, ft.AuType.QFQ if ft else 'qfq')
                write_rows(sub / 'bars_raw.csv.gz', [(code, t, *v) for t, v in raw], COLUMNS)
                write_rows(sub / 'bars_qfq.csv.gz', [(code, t, *v) for t, v in qfq], COLUMNS)
                write_rows(sub / 'actions.csv.gz', src.actions(code), ACTION_COLUMNS)
                prog['done'].append(code)
            prog_path.write_text(json.dumps(prog, indent=1), encoding='utf-8')
            print(code, len(raw), flush=True)
        after = src.quota()
    finally:
        if source is None:
            src.close()
    names = {c: '' for c in codes}
    universe = dict(market=market, source='OpenD request_history_kline(K_60M, regular session) + get_rehab',
                    filter=rule, window=[start, end], snapshot_utc=datetime.now(timezone.utc).isoformat(timespec='seconds'),
                    quota_before=before, quota_after=after, empty=prog['empty'],
                    stocks=[dict(code=c, name=names[c]) for c in codes if c in prog['done']])
    (sub / 'universe.json').write_text(json.dumps(universe, indent=1, ensure_ascii=False), encoding='utf-8')
    return universe


def checksums(out):
    lines = []
    for p in sorted(Path(out).rglob('*')):
        if p.is_file() and p.name not in ('CHECKSUMS.sha256', 'progress.json'):
            lines.append(f'{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.relative_to(out)}')
    (Path(out) / 'CHECKSUMS.sha256').write_text('\n'.join(lines) + '\n', encoding='utf-8')


if __name__ == '__main__':
    import sys
    if sys.argv[1] == 'fetch':                      # fetch <out> <market> <start> <end> <codes.json> <rule.json>
        out, market, start, end = sys.argv[2:6]
        codes = json.loads(Path(sys.argv[6]).read_text(encoding='utf-8'))
        rule = json.loads(Path(sys.argv[7]).read_text(encoding='utf-8'))
        print(fetch(out, market, start, end, codes, rule)['quota_after'])
        checksums(out)
