"""R8 data (notes/PREREG_R8.md): broad daily universe (free), point-in-time sample, then 5-minute history (quota).

    nice -n 19 /opt/futu-opend/venv/bin/python -m studies.martin_luk.fetch_r8 daily
    nice -n 19 /opt/futu-opend/venv/bin/python -m studies.martin_luk.fetch_r8 sample
    nice -n 19 /opt/futu-opend/venv/bin/python -m studies.martin_luk.fetch_r8 k5        # resumable
"""
from __future__ import annotations

import csv
import gzip
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from . import intraday as I, luk

ROOT = luk.ROOT
DAILY = ROOT / 'data' / 'martin-luk-universe-us'
K5 = ROOT / 'data' / 'martin-luk-k5-r8'
SEED, N, MIN_DAYS = 20261017, 200, 5
K5_START, K5_END = '2023-10-02', '2026-10-16'
RESERVE = 80          # history quota left for custody


def daily():
    from studies.trend_breakout import fetch, sources
    sources.OpenDSource.FILTERS = {'us': ('US', 1.0, 2e6)}
    return fetch.fetch(DAILY.parent / DAILY.name, 'us', '2023-01-01', '2026-10-16')


def _eligible_days(days, rows, actions):
    """Point-in-time leader days for one stock (numpy over its own history only)."""
    from studies.trend_breakout import panel
    r = np.array(rows, float)                        # open, high, low, close, volume, turnover (raw)
    f = panel.factors(r[:, 3], np.array(days), actions)
    c, h, l = (r[:, k:k + 1] * f[:, None] for k in (3, 1, 2))
    e9, e21, e50 = luk.ema(c, 9), luk.ema(c, 21), luk.ema(c, 50)
    adr = luk.rolling_mean(h / l - 1, 20) * 100
    to20 = luk.rolling_mean(r[:, 5:6], 20)
    with np.errstate(invalid='ignore', divide='ignore'):
        mom = np.fmax(np.fmax(c / luk.lag(c, 21), c / luk.lag(c, 63)), c / luk.lag(c, 126)) - 1
        ok = ((r[:, 3:4] >= 5) & (to20 >= 20e6) & (adr >= 4) & (mom >= .30) & (e9 > e21) & (e21 > e50))[:, 0]
    d = np.array(days)
    return int((ok & (d >= '2024-01-02') & (d <= '2026-09-30')).sum())


def sample():
    """Stream the broad daily file one stock at a time (keeps memory flat), count eligible days, draw the sample."""
    from studies.trend_breakout import panel
    folder = DAILY / 'us'
    actions = panel.read_actions(folder / 'actions.csv.gz')
    listed = {s['code'] for s in json.loads((folder / 'universe.json').read_text())['stocks']}
    counts, cur, days, rows = {}, None, [], []
    for code, day, values in panel.read_bars(folder / 'bars_raw.csv.gz'):
        if code != cur:
            if cur in listed and len(rows) > 130:
                counts[cur] = _eligible_days(days, rows, actions.get(cur, []))
            cur, days, rows = code, [], []
        days.append(day)
        rows.append(values)
    if cur in listed and len(rows) > 130:
        counts[cur] = _eligible_days(days, rows, actions.get(cur, []))
    have = set(I.files())
    pool = sorted(c for c, n in counts.items() if n >= MIN_DAYS and c[3:] not in have)
    rng = np.random.default_rng(SEED)
    pick = sorted(rng.choice(pool, min(N, len(pool)), replace=False).tolist())
    K5.mkdir(parents=True, exist_ok=True)
    (K5 / 'sample.json').write_text(json.dumps(dict(seed=SEED, min_days=MIN_DAYS, universe=len(listed),
                                                    scored=len(counts), pool=len(pool), pool_codes=pool,
                                                    picked=pick), indent=1))
    print('universe', len(listed), 'scored', len(counts), 'pool', len(pool), 'picked', len(pick))


def k5():
    import futu as ft
    plan = json.loads((K5 / 'sample.json').read_text())
    prog_path = K5 / 'progress.json'
    prog = json.loads(prog_path.read_text()) if prog_path.exists() else {'done': [], 'failed': {}}
    q = ft.OpenQuoteContext(host='127.0.0.1', port=11111)
    try:
        ret, quota = q.get_history_kl_quota(get_detail=False)
        prog.setdefault('quota_before', list(quota))
        for code in plan['picked']:
            if code in prog['done']:
                continue
            ret, quota = q.get_history_kl_quota(get_detail=False)
            if ret == ft.RET_OK and quota[1] <= RESERVE:
                prog['stopped'] = f'quota remain {quota[1]} <= reserve {RESERVE}'
                break
            rows, key = [], None
            while True:
                for attempt in range(5):
                    ret, df, key2 = q.request_history_kline(code, start=K5_START, end=K5_END, ktype=ft.KLType.K_5M,
                                                             autype=ft.AuType.QFQ, max_count=1000, page_req_key=key)
                    if ret == ft.RET_OK:
                        break
                    time.sleep(3 * (attempt + 1))
                time.sleep(0.6)                          # stay well under 60 requests / 30 s
                if ret != ft.RET_OK:
                    prog['failed'][code] = str(df)[:200]
                    break
                rows += [(r.time_key, r.open, r.high, r.low, r.close, r.volume, r.turnover) for r in df.itertuples()]
                key = key2
                if key is None:
                    break
            if code in prog['failed'] and not rows:
                prog_path.write_text(json.dumps(prog, indent=1))
                continue
            with gzip.open(K5 / f'{code[3:]}.csv.gz', 'wt', newline='') as fh:
                w = csv.writer(fh)
                w.writerow(('time_key', 'open', 'high', 'low', 'close', 'volume', 'turnover'))
                w.writerows(rows)
            prog['done'].append(code)
            prog['failed'].pop(code, None)
            prog_path.write_text(json.dumps(prog, indent=1))
            print(f"{len(prog['done'])}/{len(plan['picked'])} {code} rows {len(rows)}", flush=True)
        ret, quota = q.get_history_kl_quota(get_detail=False)
        prog['quota_after'] = list(quota)
        prog['finished_utc'] = datetime.now(timezone.utc).isoformat(timespec='seconds')
        prog_path.write_text(json.dumps(prog, indent=1))
    finally:
        q.close()


if __name__ == '__main__':
    {'daily': daily, 'sample': sample, 'k5': k5}[sys.argv[1]]()
