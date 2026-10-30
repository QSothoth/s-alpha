"""One-off pull of the US option statistics the option traders' replications need (user approved 2026-10-25):
the earnings calendar (date, before / after the session, option volume, IV, IV rank) and, per underlying of the
trader-data-v1 US list, the daily IV / HV and daily call / put volume and open interest.  OpenD, no history-kline
quota.  Output: data/trader-options-v1/us/{earnings.csv, iv/<code>.csv, stat/<code>.csv}; resumable.  The finished
pull is frozen in the GitHub release trader-pack-20261025 (trader-options-v1.zip); unpack it rather than refetch.

    PY="nice -n 19 env PYTHONUTF8=1 /opt/opend-us-options/.venv/bin/python"
    $PY -m studies.trader_options.fetch earnings
    $PY -m studies.trader_options.fetch underlyings
"""
from __future__ import annotations

import csv
import datetime as dt
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'data' / 'trader-options-v1' / 'us'
BEGIN, END = '2023-06-01', '2026-10-23'


def ctx():
    import futu as ft
    return ft, ft.OpenQuoteContext(host='127.0.0.1', port=11111)


def call(fn, *a, **k):
    """OpenD call with retries on rate limits / transient errors."""
    for i in range(8):
        res = fn(*a, **k)
        ret, data = res[0], (res[1] if len(res) == 2 else tuple(res[1:]))
        if ret == 0:
            return data
        msg = str(data)
        if 'frequen' in msg.lower() or '频率' in msg or 'too many' in msg.lower():
            time.sleep(5 + 5 * i)
            continue
        if i < 2:
            time.sleep(2)
            continue
        raise RuntimeError(msg)
    raise RuntimeError('rate limited')


def earnings():
    ft, q = ctx()
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / 'earnings.csv'
    cols = ['security', 'earnings_date', 'pub_type', 'period_text', 'option_volume', 'iv', 'iv_rank',
            'iv_percentile', 'market_cap', 'price']
    rows = {}
    d = dt.date.fromisoformat(BEGIN)
    end = dt.date.fromisoformat(END)
    while d <= end:
        e = min(d + dt.timedelta(days=6), end)
        df = call(q.get_earnings_calendar, ft.Market.US, begin_date=d.isoformat(), end_date=e.isoformat())
        for r in df.to_dict('records'):
            rows[(r['security'], r['earnings_date'], r['period_text'])] = [r[c] for c in cols]
        print('earnings', d, len(df), flush=True)
        d = e + dt.timedelta(days=1)
        time.sleep(.5)
    q.close()
    with path.open('w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(cols)
        w.writerows(sorted(rows.values(), key=lambda r: (r[1], r[0])))
    print('wrote', path, len(rows))


def paged(fn, code):
    out, key = [], None
    while True:
        data = call(fn, code, begin_time=BEGIN, end_time=END, page_req_key=key)
        if isinstance(data, tuple):
            df, key = data[0], data[1] if len(data) > 1 else None
        else:
            df, key = data, None
        out.append(df)
        if not key or len(df) == 0:
            break
        time.sleep(.1)
    import pandas as pd
    return pd.concat(out).drop_duplicates('time').sort_values('time') if out else None


def underlyings():
    ft, q = ctx()
    codes = json.loads((ROOT / 'data/trader-data-v1/us/universe.json').read_text(encoding='utf-8'))['stocks']
    codes = sorted(c['code'] if isinstance(c, dict) else c for c in codes)
    vol = {}                         # most liquid option underlyings first (earnings-calendar option volume)
    with (OUT / 'earnings.csv').open(encoding='utf-8') as f:
        for r in csv.DictReader(f):
            try:
                vol[r['security']] = max(vol.get(r['security'], 0), float(r['option_volume'] or 0))
            except ValueError:
                pass
    codes.sort(key=lambda c: -vol.get(c, 0))
    for sub, fn, cols in (('iv', q.get_option_underlying_his_volatility, ['time', 'iv', 'hv', 'underlying_price']),
                          ('stat', q.get_option_underlying_his_statistic,
                           ['time', 'option_volume', 'call_volume', 'put_volume', 'option_open_interest',
                            'call_open_interest', 'put_open_interest', 'underlying_price'])):
        (OUT / sub).mkdir(parents=True, exist_ok=True)
    done = 0
    for i, c in enumerate(codes):
        code = c if str(c).startswith('US.') else f'US.{c}'
        for sub, fn, cols in (('iv', q.get_option_underlying_his_volatility, ['time', 'iv', 'hv', 'underlying_price']),
                              ('stat', q.get_option_underlying_his_statistic,
                               ['time', 'option_volume', 'call_volume', 'put_volume', 'option_open_interest',
                                'call_open_interest', 'put_open_interest', 'underlying_price'])):
            p = OUT / sub / f'{code}.csv'
            if p.exists():
                continue
            try:
                df = paged(fn, code)
            except RuntimeError as e:
                p.write_text('error,' + str(e).replace('\n', ' ')[:200] + '\n', encoding='utf-8')
                continue
            if df is None or len(df) == 0:
                p.write_text(','.join(cols) + '\n', encoding='utf-8')
            else:
                df[[x for x in cols if x in df.columns]].to_csv(p, index=False)
            time.sleep(.1)
        done += 1
        if i % 50 == 0:
            print('underlyings', i, len(codes), code, flush=True)
    q.close()
    print('done', done)


if __name__ == '__main__':
    {'earnings': earnings, 'underlyings': underlyings}[sys.argv[1]]()
