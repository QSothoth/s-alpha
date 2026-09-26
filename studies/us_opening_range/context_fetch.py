"""One-shot, fixed-scope OpenD ETF history capture; never evaluates returns.

Run as a module. A failed/partial directory is evidence, not a resume target.
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import time

from custody.dataset import sha256_file
from custody.marketdata import Bar
from custody.models import ET

CODES = tuple('US.' + s for s in (
    'DIA', 'TLT', 'GLD', 'SLV', 'XLF', 'XLE', 'SMH', 'EEM', 'XLV', 'XLI', 'XLU', 'XLY'))
START, END = '2018-09-01', '2026-09-25'
MAX_NEW, MIN_REMAINING, PAGE_SIZE, MAX_PAGES = 12, 72, 1000, 2000
MIN_INTERVAL = 0.6
FIELDS = ('code', 'time_key', 'open', 'high', 'low', 'close', 'volume', 'turnover')
PLAN = Path(__file__).with_name('notes') / 'ALPHA_PLAN.md'


def _records(frame):
    if hasattr(frame, 'itertuples'):
        return (row._asdict() for row in frame.itertuples(index=False))
    return iter(frame)


def _quota(call, context):
    ret, data = call(context.get_history_kl_quota, get_detail=True)
    if ret != 0:
        raise RuntimeError('quota request failed: ' + str(data))
    used, remaining, details = data
    if any(isinstance(n, bool) or not isinstance(n, int) or n < 0
           for n in (used, remaining)):
        raise ValueError('invalid quota counts')
    codes = [row['code'] for row in details]
    # The server can list multiple request_time entries for one charged symbol.
    if len(set(codes)) != used:
        raise ValueError('quota detail/count mismatch')
    if not all(isinstance(code, str) and code for code in codes):
        raise ValueError('invalid quota codes')
    return {'used': used, 'remaining': remaining, 'charged_codes': sorted(set(codes)),
            'detail_rows': len(codes),
            'observed_at': datetime.now(timezone.utc).isoformat()}


def _row(raw, code):
    if raw['code'] != code:
        raise ValueError('unexpected symbol: ' + str(raw['code']))
    stamp = str(raw['time_key'])
    when = datetime.strptime(stamp, '%Y-%m-%d %H:%M:%S').replace(tzinfo=ET)
    if (stamp != when.strftime('%Y-%m-%d %H:%M:%S') or
            not START <= stamp[:10] <= END or when.weekday() > 4 or
            not '09:30:00' < stamp[11:] <= '16:00:00' or
            when.minute % 5 or when.second):
        raise ValueError('outside fixed RTH close-time scope: ' + stamp)
    values = {key: float(raw[key]) for key in FIELDS[2:]}
    if any(isinstance(raw[key], bool) or not math.isfinite(values[key]) for key in values):
        raise ValueError('invalid numeric field at ' + stamp)
    Bar(code, when, *(values[key] for key in FIELDS[2:7]), interval='5m')
    if min(values[key] for key in ('open', 'high', 'low', 'close')) <= 0 or values['turnover'] < 0:
        raise ValueError('nonpositive price or negative turnover at ' + stamp)
    # SDK time_key is retained, NOT shifted by five minutes.
    return {'code': code, 'time_key': stamp, **values}


def _fetch_symbol(context, call, root, item):
    code = item['code']
    if code not in CODES:
        raise ValueError('unauthorized history symbol')
    key, seen_keys, last, daily = None, set(), None, None
    with (root / item['file']).open('x', newline='', encoding='utf-8') as fh, \
            (root / item['coverage_file']).open('x', newline='', encoding='utf-8') as coverage:
        writer = csv.DictWriter(fh, fieldnames=FIELDS)
        writer.writeheader()
        daily_writer = csv.writer(coverage)
        daily_writer.writerow(('date', 'rows', 'first_close', 'last_close', 'missing_before_or_between'))
        try:
            for _ in range(MAX_PAGES):
                ret, frame, next_key = call(
                    context.request_history_kline, code, start=START, end=END,
                    ktype='K_5M', autype='qfq', session='RTH', extended_time=False,
                    max_count=PAGE_SIZE, page_req_key=key)
                item['pages_requested'] += 1
                if ret != 0:
                    raise RuntimeError('history request failed: ' + str(frame))
                if hasattr(frame, '__len__') and len(frame) > PAGE_SIZE:
                    raise ValueError('page exceeds 1000 rows')
                page_rows = 0
                for index, raw in enumerate(_records(frame)):
                    if index >= PAGE_SIZE:
                        raise ValueError('page exceeds 1000 rows')
                    page_rows += 1
                    row = _row(raw, code)
                    stamp = row['time_key']
                    if last and stamp <= last['time_key']:
                        if key is not None and index == 0 and row == last:
                            item['boundary_duplicates'] += 1
                            continue
                        raise ValueError('unordered/conflicting duplicate at ' + stamp)
                    if daily and daily[0] != stamp[:10]:
                        daily_writer.writerow(daily)
                        daily = None
                    minutes = int(stamp[11:13]) * 60 + int(stamp[14:16])
                    if daily is None:
                        daily = [stamp[:10], 0, stamp[11:], stamp[11:], (minutes - 575) // 5]
                        item['observed_sessions'] += 1
                    else:
                        prior = int(daily[3][:2]) * 60 + int(daily[3][3:5])
                        daily[4] += (minutes - prior) // 5 - 1
                    daily[1] += 1
                    daily[3] = stamp[11:]
                    writer.writerow(row)
                    item['rows'] += 1
                    item['first_time'] = item['first_time'] or stamp
                    item['last_time'] = stamp
                    last = row
                fh.flush()
                coverage.flush()
                if next_key is None:
                    if not item['rows']:
                        raise ValueError('empty history for authorized symbol')
                    item['status'] = 'downloaded'
                    return
                if not page_rows:
                    raise ValueError('empty nonterminal page')
                if not isinstance(next_key, bytes) or not next_key or next_key in seen_keys:
                    raise ValueError('invalid/repeated pagination key')
                seen_keys.add(next_key)
                key = next_key
            raise ValueError('pagination page limit exceeded')
        finally:
            if daily:
                daily_writer.writerow(daily)


def fetch(context, out, *, sdk_version='unknown', sleep=time.sleep, monotonic=time.monotonic,
          progress=None):
    """Capture through an injected quote context; caller owns its connection.

    Memory is one SDK page plus pagination keys; no full history is retained.
    Return a manifest, including failures. Never retry or overwrite an old root.
    """
    root = Path(out)
    root.mkdir(parents=True, exist_ok=False)
    last_call = None

    def call(method, *args, **kwargs):
        nonlocal last_call
        if last_call is not None:
            delay = MIN_INTERVAL - (monotonic() - last_call)
            if delay > 0:
                sleep(delay)
        last_call = monotonic()
        return method(*args, **kwargs)

    manifest = {
        'dataset': root.name, 'role': 'holdout/underlying-context', 'status': 'partial',
        'source': 'OpenD.request_history_kline', 'sdk_version': sdk_version,
        'interval': 'K_5M', 'adjustment': 'QFQ', 'session': 'RTH',
        'start': START, 'end': END, 'timezone': 'America/New_York',
        'timestamp': 'SDK time_key unchanged; bar close; first regular bar 09:35',
        'coverage_status': 'calendar_unverified',
        'coverage_note': 'Observed daily counts/gaps only; absent dates and missing tails are not inferred. '
                         'Downloaded means pagination ended, not complete calendar coverage.',
        'evaluation_status': 'not_evaluated', 'authorization': str(PLAN),
        'authorization_sha256': sha256_file(PLAN), 'code_sha256': sha256_file(__file__),
        'max_new_symbols': MAX_NEW, 'minimum_remaining': MIN_REMAINING,
        'max_page_rows': PAGE_SIZE, 'minimum_call_interval_seconds': MIN_INTERVAL,
        'started_at': datetime.now(timezone.utc).isoformat(),
        'quota_before': None, 'quota_after': None, 'quota_checks': [],
        'new_symbols_attempted': [], 'errors': [],
        'symbols': [{'code': code, 'status': 'not_started', 'file': code + '.csv',
                     'coverage_file': code + '.coverage.csv', 'rows': 0,
                     'pages_requested': 0, 'boundary_duplicates': 0,
                     'observed_sessions': 0, 'first_time': None, 'last_time': None,
                     'error': None} for code in CODES],
    }
    item = None
    try:
        if len(CODES) != MAX_NEW or len(set(CODES)) != MAX_NEW:
            raise ValueError('fixed authorization must contain exactly 12 unique ETFs')
        before = manifest['quota_before'] = _quota(call, context)
        uncharged = set(CODES) - set(before['charged_codes'])
        if before['remaining'] - len(uncharged) < MIN_REMAINING:
            raise ValueError('insufficient quota for the entire fixed batch while retaining 72')
        for item in manifest['symbols']:
            check = _quota(call, context)
            manifest['quota_checks'].append({'code': item['code'], **check})
            new = item['code'] not in check['charged_codes']
            if check['remaining'] - int(new) < MIN_REMAINING:
                raise ValueError('quota reserve guard: remaining would fall below 72')
            if new:
                if len(manifest['new_symbols_attempted']) >= MAX_NEW:
                    raise ValueError('new-symbol authorization cap exceeded')
                manifest['new_symbols_attempted'].append(item['code'])
            item['status'] = 'partial'
            _fetch_symbol(context, call, root, item)
            if progress is not None:
                progress({key: item[key] for key in ('code', 'rows', 'pages_requested')})
        manifest['status'] = 'downloaded'
    except (Exception, KeyboardInterrupt) as exc:
        message = type(exc).__name__ + ': ' + str(exc)
        manifest['errors'].append(message)
        if item is not None:
            item['status'], item['error'] = 'partial', message
    finally:
        try:
            manifest['quota_after'] = _quota(call, context)
            if manifest['quota_after']['remaining'] < MIN_REMAINING:
                manifest['errors'].append('final quota is below the 72 reserve')
        except (Exception, KeyboardInterrupt) as exc:
            manifest['errors'].append('quota_after: ' + type(exc).__name__ + ': ' + str(exc))
        if manifest['errors']:
            manifest['status'] = 'partial'
        manifest['finished_at'] = datetime.now(timezone.utc).isoformat()
        for entry in manifest['symbols']:
            for field in ('file', 'coverage_file'):
                path = root / entry[field]
                if path.exists():
                    entry[field + '_sha256'] = sha256_file(path)
        with (root / 'manifest.json').open('x', encoding='utf-8') as fh:
            json.dump(manifest, fh, indent=2, ensure_ascii=False, allow_nan=False)
            fh.write('\n')
        with (root / 'CHECKSUMS.sha256').open('x', encoding='utf-8') as fh:
            for path in sorted(root.iterdir()):
                if path.is_file() and path.name != 'CHECKSUMS.sha256':
                    fh.write(sha256_file(path) + '  ' + path.name + '\n')
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True, help='New output directory; no overwrite/resume')
    parser.add_argument('--host', default=os.environ.get('FUTU_HOST', '127.0.0.1'))
    parser.add_argument('--port', type=int, default=int(os.environ.get('FUTU_PORT', '11111')))
    args = parser.parse_args(argv)
    if Path(args.out).exists():
        parser.error('output directory already exists')
    import futu as ft
    context = ft.OpenQuoteContext(host=args.host, port=args.port)
    try:
        manifest = fetch(context, args.out, sdk_version=ft.__version__,
                         progress=lambda item: print(json.dumps(item), flush=True))
    finally:
        context.close()
    print(json.dumps({'status': manifest['status'], 'out': args.out,
                      'symbols_downloaded': sum(x['status'] == 'downloaded' for x in manifest['symbols']),
                      'rows': sum(x['rows'] for x in manifest['symbols']), 'errors': manifest['errors']}))
    return 0 if manifest['status'] == 'downloaded' else 1


if __name__ == '__main__':
    raise SystemExit(main())
