"""Fixed SPY/date source-quality recheck; three history pages, two HTTP calls at most."""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import time
import urllib.request

from custody.dataset import sha256_file, write_checksums

CODE, DAY = 'US.SPY', '2024-05-30'
JOBS = (
    ('opend_k5.csv', {'ktype': 'K_5M', 'session': 'RTH', 'extended_time': False}),
    ('opend_daily.csv', {'ktype': 'K_DAY', 'extended_time': False}),
    ('opend_k30_extended.csv', {'ktype': 'K_30M', 'extended_time': True}),
)
BEGIN = int(datetime(2024, 5, 30, tzinfo=timezone.utc).timestamp())
URLS = (
    ('yahoo.json', 'https://query1.finance.yahoo.com/v8/finance/chart/SPY?'
     f'period1={BEGIN}&period2={BEGIN + 86400}&interval=1d&events=div,split'),
    ('tencent.json', 'https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?'
     'param=usSPY.AM,day,2024-05-30,2024-05-30,1,qfq'),
)
OLD = {
    'k5': Path('data/preopen-us-k5-select-v1/k5/SPY.csv'),
    'daily': Path('data/preopen-us-train-v1/daily/SPY.csv'),
    'ext30': Path('data/preopen-us-ext30-select-v1/ext30/SPY.csv'),
}


def _now():
    return datetime.now(timezone.utc).isoformat()


def _write_json(path, data):
    with path.open('x', encoding='utf-8') as handle:
        json.dump(data, handle, indent=2, ensure_ascii=False, allow_nan=False)
        handle.write('\n')


def _day_rows(path, key='time_key'):
    result = []
    if not path.exists():
        return result
    with path.open(newline='', encoding='utf-8') as handle:
        for row in csv.DictReader(handle):
            if row[key][:10] == DAY:
                result.append(row)
            elif row[key][:10] > DAY:
                break
    return result


def compare_rows(old, new):
    left = {row['time_key']: row for row in old}
    right = {row['time_key']: row for row in new}
    common = sorted(left.keys() & right.keys())
    fields = {}
    for field in ('open', 'high', 'low', 'close', 'volume', 'turnover'):
        pairs = [(float(left[key][field]), float(right[key][field])) for key in common]
        ratios = [b / a for a, b in pairs if a != 0]
        fields[field] = {'compared': len(pairs), 'equal': sum(a == b for a, b in pairs),
                         'max_abs_difference': max((abs(a - b) for a, b in pairs), default=None),
                         'ratio_min': min(ratios, default=None), 'ratio_max': max(ratios, default=None)}
    return {'old_rows': len(old), 'new_rows': len(new), 'common_times': len(common),
            'old_only_times': sorted(left.keys() - right.keys()),
            'new_only_times': sorted(right.keys() - left.keys()), 'fields': fields}


def quality(root):
    old = {key: _day_rows(path, 'date' if key == 'daily' else 'time_key') for key, path in OLD.items()}
    new = {key: _day_rows(root / filename) for key, filename in
           (('k5', 'opend_k5.csv'), ('daily', 'opend_daily.csv'), ('ext30', 'opend_k30_extended.csv'))}
    new['ext30'] = [row for row in new['ext30'] if row['time_key'][11:16] <= '09:30'
                    or row['time_key'][11:16] > '16:00']
    report = {'purpose': 'source/time/price-basis quality only; no signals or returns',
              'symbol': CODE, 'date': DAY, 'comparisons': {
                  key: compare_rows(old[key], new[key]) for key in ('k5', 'ext30')}}
    report['old_daily'] = old['daily']
    report['new_daily'] = new['daily']
    report['daily_from_k5'] = {}
    for name, rows in (('old', old['k5']), ('new', new['k5'])):
        if rows:
            report['daily_from_k5'][name] = {
                'rows': len(rows), 'first_time': rows[0]['time_key'], 'last_time': rows[-1]['time_key'],
                'open': float(rows[0]['open']), 'high': max(float(row['high']) for row in rows),
                'low': min(float(row['low']) for row in rows), 'close': float(rows[-1]['close']),
                'volume': sum(float(row['volume']) for row in rows),
                'turnover': sum(float(row['turnover']) for row in rows)}
    report['clock_shift_checks'] = {}
    for shift in (-5, 0, 5):
        shifted = [dict(row, time_key=(datetime.fromisoformat(row['time_key']) +
                   timedelta(minutes=shift)).isoformat(sep=' ')) for row in new['k5']]
        report['clock_shift_checks'][str(shift)] = compare_rows(old['k5'], shifted)
    yahoo = root / 'yahoo.json'
    if yahoo.exists():
        try:
            payload = json.loads(yahoo.read_text())
        except (ValueError, UnicodeError):
            payload = {}
            report['yahoo_parse_error'] = True
        results = payload.get('chart', {}).get('result') or []
        if results:
            item = results[0]
            report['yahoo_daily'] = {'timestamps': item.get('timestamp'),
                                      'indicators': item.get('indicators'),
                                      'events': item.get('events'),
                                      'exchangeTimezoneName': item.get('meta', {}).get('exchangeTimezoneName')}
    tencent = root / 'tencent.json'
    if tencent.exists():
        try:
            payload = json.loads(tencent.read_text())
        except (ValueError, UnicodeError):
            payload = {}
            report['tencent_parse_error'] = True
        item = payload.get('data', {}).get('usSPY.AM', {})
        report['tencent_daily'] = {key: item[key] for key in ('qfqday', 'day') if key in item}
    _write_json(root / 'quality_report.json', report)


def capture(context, out, sdk_version, *, sleep=time.sleep, urlopen=urllib.request.urlopen):
    """Caller owns the quote connection; no retries, pagination or fallback."""
    root = Path(out)
    root.mkdir(parents=True, exist_ok=False)
    manifest = {'purpose': 'fixed already-used SPY source-quality recheck, not validation',
                'code': CODE, 'date': DAY, 'sdk_version': sdk_version, 'created_at': _now(),
                'authorization': 'notes/DATA_RECHECK_20260926.md',
                'code_sha256': sha256_file(__file__),
                'old_files_sha256': {str(path): sha256_file(path) for path in OLD.values()},
                'quota_before': None, 'quota_after': None, 'history_requests': [],
                'http_requests': [], 'errors': []}

    def quota():
        ret, data = context.get_history_kl_quota(get_detail=True)
        if ret != 0:
            raise RuntimeError('quota read failed')
        used, remaining, details = data
        return {'used': used, 'remaining': remaining,
                'spy_already_charged': CODE in {row['code'] for row in details}, 'at': _now()}

    try:
        manifest['quota_before'] = quota()
        if not manifest['quota_before']['spy_already_charged']:
            raise ValueError('SPY would require new quota; refused')
        for filename, specific in JOBS:
            sleep(1.05)
            kwargs = dict(start=DAY, end=DAY, autype='qfq', max_count=1000,
                          page_req_key=None, **specific)
            record = {'file': filename, 'kwargs': kwargs, 'started_at': _now()}
            manifest['history_requests'].append(record)
            ret, frame, next_key = context.request_history_kline(CODE, **kwargs)
            record.update(finished_at=_now(), ret=ret)
            if ret != 0:
                record['error'] = str(frame)
                raise RuntimeError('history request failed: ' + filename)
            if len(frame) > 1000:
                raise ValueError('response exceeds fixed page cap')
            with (root / filename).open('x', newline='', encoding='utf-8') as handle:
                writer = csv.writer(handle)
                writer.writerow(frame.columns)
                writer.writerows(frame.itertuples(index=False, name=None))
            record.update(rows=len(frame), more_pages=next_key is not None)
            if next_key is not None:
                raise ValueError('unexpected pagination; no extra request permitted')
    except Exception as exc:
        manifest['errors'].append(type(exc).__name__ + ': ' + str(exc))
    finally:
        try:
            manifest['quota_after'] = quota()
        except Exception as exc:
            manifest['errors'].append(type(exc).__name__ + ': ' + str(exc))
    for filename, url in URLS:
        record = {'file': filename, 'url': url, 'started_at': _now()}
        manifest['http_requests'].append(record)
        try:
            request = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urlopen(request, timeout=20) as response:
                raw = response.read(2 << 20)
                record['status'] = response.status
            with (root / filename).open('xb') as handle:
                handle.write(raw)
            record['bytes'] = len(raw)
            json.loads(raw)
        except Exception as exc:
            record['error'] = type(exc).__name__ + ': ' + str(exc)
        record['finished_at'] = _now()
    quality(root)
    manifest['completed_at'] = _now()
    _write_json(root / 'manifest.json', manifest)
    write_checksums(root)
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args(argv)
    if args.out.exists():
        parser.error('refuse existing output directory')
    import futu as ft
    context = ft.OpenQuoteContext(host='127.0.0.1', port=11111)
    try:
        result = capture(context, args.out, ft.__version__)
    finally:
        context.close()
    print(json.dumps({'out': str(args.out), 'history_requests': len(result['history_requests']),
                      'http_requests': len(result['http_requests']), 'errors': result['errors']}))


if __name__ == '__main__':
    main()
