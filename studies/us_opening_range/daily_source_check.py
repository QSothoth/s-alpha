"""Fixed three-ETF daily-source quality check; no signals or future labels."""
import argparse
import csv
from datetime import date, datetime, time as dtime
from itertools import groupby
from pathlib import Path
import time

from custody.dataset import sha256_file, write_checksums
from custody.models import ET
from custody.opend import _records
from .daily_scan import _bar, _plain, _write
from .daily_replay import aggregate_daily
from .daily_signals import daily_levels


SYMBOLS = ('XLV', 'XLI', 'XLY')
ROOT = Path('data/or-context-etf-k5-2018-2026-retry1-work')
OUT = Path('data/or-daily-source-check-20260926-work')
PREREG = Path(__file__).with_name('notes') / 'DAILY_SOURCE_CHECK_20260926.md'
PREREG_SHA = '1420037dd5c243059b55357749202d2de5d8e1b9e99623e54bb9d195bb95f668'
CHECKSUM_SHA = '5ac28d322f91c5877349a2d1021bfabecce98c74e09f83cb45192d1f35cc66ee'
COVERAGE_SHA = '501c508b69124b1da76c0b986c997ae3a89106eb59e865847637043f21eb72b8'
PINS = dict(zip(SYMBOLS, (
    'dd536bbcbca454b9c01a409c73648bf87d78482a6c040ba662dd26e014036f17',
    '4773b661dc964a78982f23866e56f4667086e228f7e4c765892d035bd1b58168',
    'c59db79b67d17171ccd6cbcfc77bb5a35e607d0b762bde75c80b441b1bc66107')))
DAYS = tuple('2026-' + value for value in (
    '08-27', '08-28', '08-31', '09-01', '09-02', '09-03', '09-04', '09-08', '09-09', '09-10',
    '09-11', '09-14', '09-15', '09-16', '09-17', '09-18', '09-21', '09-22', '09-23', '09-24'))
FIELDS = ('open', 'high', 'low', 'close', 'volume')
CODE_FILES = ('daily_source_check.py', 'daily_scan.py', 'daily_signals.py', 'daily_replay.py',
              'context_replay.py', 'context_signals.py', 'context_stats.py')


def verify_inputs(root):
    """Verify coverage first, then hash only the three authorized price files."""
    root = Path(root)
    if sha256_file(PREREG) != PREREG_SHA:
        raise ValueError('quality plan checksum mismatch')
    checksum = root / 'CHECKSUMS.sha256'
    if checksum.is_symlink() or sha256_file(checksum) != CHECKSUM_SHA:
        raise ValueError('source checksum-list mismatch')
    pins = {}
    for line in checksum.read_text().splitlines():
        digest, name = line.split(maxsplit=1)
        name = name.strip().lstrip('*')
        if name in pins:
            raise ValueError('duplicate checksum entry')
        pins[name] = digest
    wanted = {}
    for symbol in SYMBOLS:
        name = 'US.' + symbol + '.coverage.csv'
        path = root / name
        if path.is_symlink() or pins.get(name) != COVERAGE_SHA or sha256_file(path) != COVERAGE_SHA:
            raise ValueError('coverage pin mismatch: ' + symbol)
        prior, previous = [], None
        with path.open(newline='') as handle:
            for row in csv.DictReader(handle):
                day = row['date']
                if day > DAYS[-1]:
                    break  # Metadata beyond the fixed window is unnecessary.
                date.fromisoformat(day)
                if previous is not None and day <= previous:
                    raise ValueError('duplicate or unordered coverage dates')
                previous = day
                prior.append(day)
                prior = prior[-20:]
                if day in DAYS and (int(row['rows']) != 78 or row['first_close'] != '09:35:00'
                        or row['last_close'] != '16:00:00' or int(row['missing_before_or_between']) != 0):
                    raise ValueError('incomplete fixed-day coverage')
        if tuple(prior) != DAYS:
            raise ValueError('fixed dates are not the last twenty complete sessions')
        wanted[name] = COVERAGE_SHA
    for symbol in SYMBOLS:
        name = 'US.' + symbol + '.csv'
        path = root / name
        if path.is_symlink() or pins.get(name) != PINS[symbol] or sha256_file(path) != PINS[symbol]:
            raise ValueError('price pin mismatch: ' + symbol)
        wanted[name] = PINS[symbol]
    return {'root': str(root), 'checksums_sha256': CHECKSUM_SHA, 'files_sha256': wanted,
            'days': list(DAYS), 'source': 'OpenD', 'adjustment': 'QFQ', 'session': 'RTH',
            'full_file_hash_includes_excluded_bytes_without_price_parsing': True}


def local_history(path, symbol):
    history = []
    with Path(path).open(newline='') as handle:
        for day, rows in groupby(csv.DictReader(handle), key=lambda row: row['time_key'][:10]):
            if day > DAYS[-1]:
                break  # Never extract 09/25 OHLCV.
            if day < DAYS[0]:
                continue
            if len(history) >= 20 or day != DAYS[len(history)]:
                raise ValueError('missing, duplicate or unordered local session')
            bars = []
            for row in rows:
                if len(bars) >= 78:
                    raise ValueError('too many local session bars')
                stamp = datetime.fromisoformat(row['time_key'])
                if stamp.tzinfo is not None:
                    raise ValueError('expected local ET timestamp')
                bars.append(_bar(row, 'US.' + symbol, stamp.replace(tzinfo=ET), '5m'))
            history.append(aggregate_daily(bars))
    if len(history) != 20:
        raise ValueError('missing local daily history')
    return history


def current_history(rows, symbol):
    """Inspect date before touching prices, including malformed excluded OHLCV."""
    found, outside, previous = {}, [], None
    for row in rows:
        stamp = str(row.get('time_key', ''))
        day = date.fromisoformat(stamp[:10]).isoformat()
        if previous is not None and day <= previous:
            raise ValueError('duplicate or unordered current daily dates')
        previous = day
        if day not in DAYS:
            outside.append(stamp)
            continue
        found[day] = _bar(row, 'US.' + symbol, datetime.combine(date.fromisoformat(day), dtime(16), ET), '1d')
    if set(found) != set(DAYS):
        raise ValueError('current daily response lacks fixed historical dates')
    return [found[day] for day in DAYS], outside


def comparison(left, right):
    """No fitted scale: left is K_DAY, right is the fixed K5 aggregation."""
    equal = left == right
    if isinstance(left, bool) or not isinstance(left, (int, float)):
        return {'current_daily': left, 'k5_aggregate': right, 'equal': equal}
    difference = left - right
    relative = abs(difference / right) if right else None
    return {'current_daily': left, 'k5_aggregate': right, 'equal': equal,
            'difference': difference, 'absolute_difference': abs(difference), 'relative_error': relative}


def compare_histories(current, local):
    days = {day: {field: comparison(getattr(a, field), getattr(b, field)) for field in FIELDS}
            for day, a, b in zip(DAYS, current, local)}
    summaries = {}
    for field in FIELDS:
        values = [day[field] for day in days.values()]
        errors = [value['relative_error'] for value in values if value['relative_error'] is not None]
        summaries[field] = {'n': len(values), 'equal': sum(value['equal'] for value in values),
                            'relative_error_known': len(errors), 'max_relative_error': max(errors, default=None),
                            'within_1e_6': sum(value <= 1e-6 for value in errors),
                            'within_1e_4': sum(value <= 1e-4 for value in errors)}
    left, right = (daily_levels(history, date(2026, 9, 25)) for history in (current, local))
    return {'daily': days, 'summary': summaries, 'history_levels_as_of': '2026-09-25',
            'levels': {key: comparison(left[key], right[key]) for key in left},
            'source_equivalence': 'unverified', 'price_scaling': 'none'}


def capture(context, sdk, out=OUT, root=ROOT, *, now_fn=lambda: datetime.now(ET), pause=time.sleep,
            clock=time.monotonic):
    """Caller closes its private context in finally; every request is persisted."""
    out, root = Path(out), Path(root)
    out.mkdir(parents=True, exist_ok=False)
    (out / 'raw').mkdir()
    files = [Path(__file__).with_name(name) for name in CODE_FILES]
    files += [Path('custody') / name for name in ('dataset.py', 'marketdata.py', 'models.py', 'opend.py')]
    report = {'purpose': 'fixed historical daily-source quality only; no signals or labels',
              'created_at': now_fn().isoformat(), 'plan_sha256': PREREG_SHA,
              'code_sha256': {str(path): sha256_file(path) for path in files},
              'sdk_version': sdk.__version__, 'requests': [], 'errors': [], 'comparisons': {},
              'source_equivalence': 'unverified', 'history_requests': 0,
              'excluded_price_policy': 'raw retained; outside dates listed only, never extracted for comparison'}
    last_call, last_subscription, subscribed = None, None, False
    codes = ['US.' + symbol for symbol in SYMBOLS]
    subtypes = [sdk.SubType.K_DAY, sdk.SubType.K_5M]

    def request(endpoint, *args, **kwargs):
        nonlocal last_call
        if last_call is not None:
            pause(max(0., 3.1 - (clock() - last_call)))
        record = {'endpoint': endpoint, 'args': args, 'kwargs': kwargs, 'requested_at': now_fn().isoformat()}
        path = 'raw/%04d_%s.json' % (len(report['requests']), endpoint)
        last_call = clock()
        try:
            ret, raw = getattr(context, endpoint)(*args, **kwargs)
            record.update(return_code=ret, data=_plain(raw))
            if ret != 0:
                raise RuntimeError(endpoint + ' failed')  # No raw values in exception/stdout.
            return raw
        except Exception as exc:
            record['error'] = type(exc).__name__ + ': ' + str(exc)
            raise
        finally:
            record['received_at'] = now_fn().isoformat()
            _write(out / path, record)
            report['requests'].append({'path': path, 'endpoint': endpoint,
                                      'requested_at': record['requested_at'], 'received_at': record['received_at'],
                                      'ok': 'error' not in record})

    def subscribe(session):
        nonlocal subscribed, last_subscription
        try:
            request('subscribe', codes, subtypes, subscribe_push=False, session=session)
        finally:
            subscribed, last_subscription = True, clock()

    try:
        report['inputs'] = verify_inputs(root)
        local = {symbol: local_history(root / ('US.' + symbol + '.csv'), symbol) for symbol in SYMBOLS}
        quota = request('query_subscription', is_all_conn=False)
        if quota.get('own_used') != 0 or quota.get('own_option_used_quota', 0) != 0:
            raise ValueError('private connection must have zero existing subscriptions')
        session = getattr(sdk.Session, 'ALL', sdk.Session.RTH)
        try:
            subscribe(session)
        except (RuntimeError, TypeError):
            if session == sdk.Session.RTH:
                raise
            report['extended_hours_unavailable'] = True
            session = sdk.Session.RTH
            subscribe(session)
        report['subscription_session'] = session
        for symbol in SYMBOLS:
            raw = request('get_cur_kline', 'US.' + symbol, 40, ktype=sdk.KLType.K_DAY, autype=sdk.AuType.QFQ)
            rows = _records(raw)
            if len(rows) > 40:
                raise ValueError('current daily response exceeds fixed 40-row cap')
            current, outside = current_history(rows, symbol)
            report['comparisons'][symbol] = compare_histories(current, local[symbol]) | {'outside_window_timestamps': outside}
    except Exception as exc:
        report['errors'].append(type(exc).__name__ + ': ' + str(exc))
    finally:
        if subscribed:
            remaining = max(0., 61. - (clock() - last_subscription))
            while remaining > 0:
                delay = min(30., remaining)
                pause(delay)
                remaining -= delay
            try:
                request('unsubscribe', codes, subtypes)
            except Exception as exc:
                report['errors'].append('unsubscribe: ' + str(exc))
        report.update(completed_at=now_fn().isoformat(),
                      status='completed' if not report['errors'] and len(report['comparisons']) == 3 else 'incomplete')
        _write(out / 'manifest.json', report)
        write_checksums(out)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=OUT)
    args = parser.parse_args(argv)
    if args.out.exists():
        parser.error('refuse existing output directory')
    import futu as sdk
    context = sdk.OpenQuoteContext(host='127.0.0.1', port=11111)
    try:
        result = capture(context, sdk, args.out)
    finally:
        context.close()
    print('status=' + result['status'] + ' compared_symbols=' + str(len(result['comparisons'])), flush=True)
    return 0 if result['status'] == 'completed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
