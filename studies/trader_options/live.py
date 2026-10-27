"""On-demand live overlay of the option statistics (data/trader-options-live/us): the days after the frozen release
(trader-options-v1, to 2026-10-23) for the given underlyings, and the earnings calendar around today.  OpenD, no
history-kline quota; run by `trader_screens.scan refresh us` for the board's option traders only -- never scheduled
(root AGENTS.md: no background or scheduled collection without the user).  pricing.load_panel / earnings read the
release first and take only missing days from here.
"""
from __future__ import annotations

import csv
import datetime as dt
import time

from . import fetch as FX
from .pricing import DATA, LIVE

COLS = {'iv': ['time', 'iv', 'hv', 'underlying_price'],
        'stat': ['time', 'option_volume', 'call_volume', 'put_volume', 'option_open_interest', 'call_open_interest',
                 'put_open_interest', 'underlying_price']}


def last_day(sub, code):
    """The newest day stored for the code, release or overlay."""
    best = ''
    for base in (DATA, LIVE):
        p = base / sub / f'{code}.csv'
        if p.exists():
            with p.open(encoding='utf-8') as f:
                for r in csv.DictReader(f):
                    if r.get('time'):
                        best = max(best, r['time'][:10])
    return best


def refresh(codes, today=None, ahead=45):
    """Fetch the missing days of IV / statistics for `codes` and the earnings calendar from two weeks back to
    `ahead` days on; returns {'codes': n, 'rows': added, 'earnings': n, 'errors': [...]}."""
    today = today or dt.date.today().isoformat()
    ft, q = FX.ctx()
    added, errors = 0, []
    try:
        fns = {'iv': q.get_option_underlying_his_volatility, 'stat': q.get_option_underlying_his_statistic}
        for code in sorted(codes):
            for sub, fn in fns.items():
                since = last_day(sub, code)
                if since >= today:
                    continue
                begin = (dt.date.fromisoformat(since) + dt.timedelta(days=1)).isoformat() if since else FX.BEGIN
                try:
                    out, key = [], None
                    while True:
                        data = FX.call(fn, code, begin_time=begin, end_time=today, page_req_key=key)
                        df, key = (data[0], data[1] if len(data) > 1 else None) if isinstance(data, tuple) else (data, None)
                        out.append(df)
                        if not key or len(df) == 0:
                            break
                except RuntimeError as e:
                    errors.append(f'{code} {sub}: {e}')
                    continue
                rows = [r for df in out if df is not None for r in df.to_dict('records')]
                rows = [r for r in rows if str(r.get('time', ''))[:10] > since]
                if not rows:
                    continue
                p = LIVE / sub / f'{code}.csv'
                p.parent.mkdir(parents=True, exist_ok=True)
                new = not p.exists()
                with p.open('a', newline='', encoding='utf-8') as f:
                    w = csv.writer(f)
                    if new:
                        w.writerow(COLS[sub])
                    for r in sorted(rows, key=lambda r: str(r['time'])):
                        w.writerow([r.get(c, '') for c in COLS[sub]])
                added += len(rows)
                time.sleep(.1)
        cols = ['security', 'earnings_date', 'pub_type', 'period_text', 'option_volume', 'iv', 'iv_rank',
                'iv_percentile', 'market_cap', 'price']
        rows, d = {}, dt.date.fromisoformat(today) - dt.timedelta(days=14)
        if (LIVE / 'earnings.csv').exists():                         # keep the dates an earlier refresh added
            with (LIVE / 'earnings.csv').open(encoding='utf-8') as f:
                for r in csv.DictReader(f):
                    rows[(r['security'], r['earnings_date'], r['period_text'])] = [r[c] for c in cols]
        end = dt.date.fromisoformat(today) + dt.timedelta(days=ahead)
        while d <= end:
            e = min(d + dt.timedelta(days=6), end)
            df = FX.call(q.get_earnings_calendar, ft.Market.US, begin_date=d.isoformat(), end_date=e.isoformat())
            for r in df.to_dict('records'):
                rows[(r['security'], r['earnings_date'], r['period_text'])] = [r[c] for c in cols]
            d = e + dt.timedelta(days=1)
            time.sleep(.5)
        LIVE.mkdir(parents=True, exist_ok=True)
        with (LIVE / 'earnings.csv').open('w', newline='', encoding='utf-8') as f:
            w = csv.writer(f)
            w.writerow(cols)
            w.writerows(sorted(rows.values(), key=lambda r: (r[1], r[0])))
    finally:
        q.close()
    return dict(codes=len(codes), rows=added, earnings=len(rows), errors=errors)
