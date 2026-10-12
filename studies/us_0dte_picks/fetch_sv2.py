"""SV2 raw inputs (notes/SV2_PREREG.md): regular-session 1m bars, daily bars, IV/HV and earnings dates.

Only already-charged symbols (no new history-kline quota); refuses otherwise and records the quota
before and after. Resumable: a symbol whose files exist is skipped::

    /opt/futu-opend/venv/bin/python -m studies.us_0dte_picks.fetch_sv2 --out data/sv2-stock-raw
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import time
from datetime import date, timedelta
from pathlib import Path

from .fetch_sv1 import OUTSIDE, POOL
from custody.opend import _futu

START, END = '2023-06-20', '2026-08-14'
DAILY_START = '2022-12-01'
SYMBOLS = POOL + ('US.SPY',) + OUTSIDE
COLUMNS = ('time_key', 'open', 'high', 'low', 'close', 'volume')


def call(fn, *args, **kwargs):
    for attempt in range(8):
        time.sleep(0.55)
        result = fn(*args, **kwargs)
        if result[0] == 0:
            return result
        message = str(result[1])
        if 'freq' in message.lower() or '频率' in message or 'too many' in message.lower():
            time.sleep(10 * (attempt + 1))
            continue
        raise RuntimeError(message)
    raise RuntimeError('rate limited')


def klines(ctx, code, ktype, start, end):
    """Stream at most one API page; the caller writes it before requesting the next."""
    ft = _futu()
    key = None
    while True:
        _, frame, key = call(ctx.request_history_kline, code, start=start, end=end, ktype=ktype,
                             autype=ft.AuType.NONE, max_count=1000, page_req_key=key, extended_time=False)
        yield from ({c: row[c] for c in COLUMNS} for row in frame.to_dict('records'))
        if key is None:
            return


def volatility(ctx, code, start, end):
    rows, day = [], date.fromisoformat(start)
    while day <= date.fromisoformat(end):
        stop = min(day + timedelta(days=59), date.fromisoformat(end))
        _, frame, *_ = call(ctx.get_option_underlying_his_volatility, code, begin_time=day.isoformat(), end_time=stop.isoformat())
        rows += [{k: r[k] for k in ('time', 'iv', 'hv', 'underlying_price')} for r in frame.to_dict('records')]
        day = stop + timedelta(days=1)
    return sorted({r['time']: r for r in rows}.values(), key=lambda r: r['time'])


def write_csv(path, rows, columns):
    temporary = path.with_suffix('.csv.tmp')
    count = 0
    with temporary.open('w', newline='', encoding='utf-8') as fh:
        writer = csv.DictWriter(fh, columns)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
            count += 1
    temporary.replace(path)
    return count


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--symbols', default=','.join(SYMBOLS))
    args = parser.parse_args(argv)
    logging.disable(logging.CRITICAL)
    ft = _futu()
    symbols = [s.strip().upper() for s in args.symbols.split(',') if s.strip()]
    for sub in ('k1m', 'kday', 'vol', 'earnings'):
        (args.out / sub).mkdir(parents=True, exist_ok=True)
    log_path = args.out / 'fetch_log.json'
    log = json.loads(log_path.read_text(encoding='utf-8')) if log_path.exists() else {'runs': []}
    run = {'started': time.strftime('%Y-%m-%dT%H:%M:%S%z'), 'window': [START, END], 'rows': {}, 'errors': {}}
    ctx = ft.OpenQuoteContext(host='127.0.0.1', port=11111)
    try:
        used, remain, detail = ctx.get_history_kl_quota(get_detail=True)[1]
        uncharged = sorted(set(symbols) - {row['code'] for row in detail})
        if uncharged:
            raise SystemExit('refuse: not yet charged %s' % uncharged)
        run['quota_before'] = [used, remain]
        for code in symbols:
            name = code[3:]
            target = args.out / 'k1m' / (name + '.csv')
            if target.exists():
                continue
            try:
                counts = {}
                counts['kday'] = write_csv(args.out / 'kday' / (name + '.csv'),
                                           klines(ctx, code, ft.KLType.K_DAY, DAILY_START, END), COLUMNS)
                vol = volatility(ctx, code, START, END)
                counts['vol'] = write_csv(args.out / 'vol' / (name + '.csv'), vol,
                                          ('time', 'iv', 'hv', 'underlying_price'))
                # SPY is a market reference ETF, outside the stock-only earnings API.
                moves = [] if code == 'US.SPY' else call(ctx.get_financials_earnings_price_move, code, period_count=16)[1]
                (args.out / 'earnings' / (name + '.json')).write_text(
                    json.dumps(moves.to_dict('records') if hasattr(moves, 'to_dict') else moves,
                               default=str, ensure_ascii=False, indent=1), encoding='utf-8')
                counts['k1m'] = write_csv(target, klines(ctx, code, ft.KLType.K_1M, START, END), COLUMNS)
            except RuntimeError as exc:
                run['errors'][code] = str(exc)
                print('error', code, exc, flush=True)
                continue
            run['rows'][code] = counts  # minute file is last: its presence marks a complete symbol
            print(code, run['rows'][code], flush=True)
        run['quota_after'] = list(ctx.get_history_kl_quota()[1][:2])
    finally:
        ctx.close()
        run['finished'] = time.strftime('%Y-%m-%dT%H:%M:%S%z')
        log['runs'].append(run)
        log_path.write_text(json.dumps(log, indent=1, ensure_ascii=False), encoding='utf-8')
    print(json.dumps({k: run.get(k) for k in ('quota_before', 'quota_after')}), flush=True)


if __name__ == '__main__':
    main()
