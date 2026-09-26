"""Fixed 2026-09-24 Yahoo/OpenD timestamp check; no signals, labels or history API."""
import argparse
import csv
from datetime import datetime, timedelta
import json
from math import isfinite, fsum
from pathlib import Path
from statistics import median
import urllib.error
import urllib.parse
import urllib.request

from custody.dataset import sha256_file, write_checksums
from custody.models import ET
from .source_recheck import _now, _write_json

DAY, SYMBOLS = '2026-09-24', ('XLV', 'XLI', 'XLY')
ROOT = Path('data/or-context-etf-k5-2018-2026-retry1-work')
CHECKSUM_SHA = '5ac28d322f91c5877349a2d1021bfabecce98c74e09f83cb45192d1f35cc66ee'
PINS = dict(zip(SYMBOLS, (
    'dd536bbcbca454b9c01a409c73648bf87d78482a6c040ba662dd26e014036f17',
    '4773b661dc964a78982f23866e56f4667086e228f7e4c765892d035bd1b58168',
    'c59db79b67d17171ccd6cbcfc77bb5a35e607d0b762bde75c80b441b1bc66107')))
FIELDS = ('open', 'high', 'low', 'close')
PUBLIC_HEADERS = {'date', 'content-type', 'content-length', 'cache-control', 'age'}
MIDNIGHT = datetime.fromisoformat(DAY).replace(tzinfo=ET)
OPEN = MIDNIGHT.replace(hour=9, minute=30)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # A redirect must not become an uncounted extra HTTP request.


def request_url(symbol):
    if symbol not in SYMBOLS:
        raise ValueError('only the three fixed ETF symbols are authorized')
    query = urllib.parse.urlencode({'period1': int(MIDNIGHT.timestamp()),
            'period2': int((MIDNIGHT + timedelta(days=1)).timestamp()),
            'interval': '5m', 'includePrePost': 'false'})
    return 'https://query1.finance.yahoo.com/v8/finance/chart/' + symbol + '?' + query


def _prices(row):
    values = {key: float(row[key]) for key in FIELDS}
    if (any(isinstance(row[key], bool) for key in FIELDS) or not all(isfinite(value) and value > 0 for value in values.values())
            or values['low'] > min(values['open'], values['close'])
            or values['high'] < max(values['open'], values['close'])):
        raise ValueError('invalid OHLC')
    return values


def local_day(path, symbol, out):
    rows = []
    with path.open(newline='', encoding='utf-8') as handle:
        reader = csv.DictReader(handle)
        fields = reader.fieldnames
        for row in reader:
            day = row['time_key'][:10]
            if day > DAY:
                break  # Do not parse sealed-day timestamps, OHLC or volume.
            if day != DAY:
                continue
            expected = OPEN + timedelta(minutes=5 * (len(rows) + 1))
            if len(rows) >= 78 or row['code'] != 'US.' + symbol or row['time_key'] != expected.strftime('%Y-%m-%d %H:%M:%S'):
                raise ValueError('invalid local code, order or RTH grid')
            _prices(row)
            if not isfinite(float(row['volume'])) or float(row['volume']) < 0:
                raise ValueError('invalid local volume')
            rows.append(row)
    if len(rows) != 78:
        raise ValueError('local fixed day must have exactly 78 RTH bars')
    with out.open('x', newline='', encoding='utf-8') as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    return {datetime.fromisoformat(row['time_key']).replace(tzinfo=ET): row for row in rows}


def yahoo_rows(raw_path, symbol):
    if raw_path.stat().st_size > 8 << 20:
        raise ValueError('body saved fully but too large for the fixed-day JSON parser')
    payload = json.loads(raw_path.read_bytes())['chart']
    if payload.get('error') or len(payload.get('result') or []) != 1:
        raise ValueError('Yahoo chart error or absent single result: ' + str(payload.get('error')))
    item = payload['result'][0]
    if item['meta'].get('symbol') != symbol or item['meta'].get('dataGranularity') != '5m':
        raise ValueError('Yahoo symbol or interval mismatch')
    stamps, quote = item['timestamp'], item['indicators']['quote'][0]
    if any(len(quote[key]) != len(stamps) for key in (*FIELDS, 'volume')):
        raise ValueError('Yahoo array length mismatch')
    rows, invalid, outside, previous = {}, [], [], None
    for index, timestamp in enumerate(stamps):
        stamp = datetime.fromtimestamp(timestamp, ET)
        if previous is not None and stamp <= previous:
            raise ValueError('duplicate or unordered Yahoo timestamp')
        previous = stamp
        if stamp.date() != MIDNIGHT.date() or not OPEN <= stamp < OPEN.replace(hour=16, minute=0):
            outside.append(stamp.isoformat())
            continue  # No prices from an out-of-scope timestamp are compared.
        if stamp.second or stamp.microsecond or stamp.minute % 5:
            raise ValueError('Yahoo timestamp off the 5m grid')
        row = {key: quote[key][index] for key in (*FIELDS, 'volume')}
        try:
            _prices(row)
        except (ValueError, TypeError):
            invalid.append(stamp.isoformat())
            continue
        rows[stamp] = row
    return rows, {'timestamps': len(stamps), 'valid_rth_rows': len(rows), 'invalid_ohlc_times': invalid,
                  'outside_rth_times': outside, 'meta_timezone': item['meta'].get('exchangeTimezoneName')}


def compare(local, yahoo):
    main = [(local[stamp + timedelta(minutes=5)], row) for stamp, row in yahoo.items()
            if stamp + timedelta(minutes=5) in local]
    ratios = [float(right[key]) / float(left[key]) for left, right in main for key in FIELDS]
    factor = median(ratios) if ratios else None
    result = {'quality_status': 'diagnostic_only' if yahoo else 'unknown_empty_yahoo_rth',
              'primary_yahoo_shift_minutes': 5, 'primary_full_78': len(main) == len(yahoo) == 78, 'factor_yahoo_over_opend': factor,
              'factor_method': 'median all matched OHLC ratios at primary +5 only; reused for every shift',
              'primary_ratio_min': min(ratios, default=None), 'primary_ratio_max': max(ratios, default=None),
              'shifts_from_raw_yahoo_timestamp_minutes': {}}
    for shift in (-5, 0, 5):
        shifted = {stamp + timedelta(minutes=shift): row for stamp, row in yahoo.items()}
        common, fields = sorted(local.keys() & shifted.keys()), {}
        for key in FIELDS:
            pairs = [(float(local[stamp][key]), float(shifted[stamp][key])) for stamp in common]
            raw = [abs(a / b - 1) for a, b in pairs]
            residual = [abs(a * factor / b - 1) for a, b in pairs] if factor is not None else []
            fields[key] = {'n': len(pairs), 'raw_max_relative_error': max(raw, default=None),
                           'scaled_max_relative_error': max(residual, default=None),
                           'scaled_mean_relative_error': fsum(residual) / len(residual) if residual else None,
                           'scaled_within_1e_6': sum(value <= 1e-6 for value in residual),
                           'scaled_within_1e_4': sum(value <= 1e-4 for value in residual)}
        volumes = [(float(local[stamp]['volume']), shifted[stamp]['volume']) for stamp in common]
        valid_volume = [(a, b) for a, b in volumes if isinstance(b, (int, float)) and isfinite(b) and b >= 0]
        result['shifts_from_raw_yahoo_timestamp_minutes'][str(shift)] = {
            'common_rows': len(common), 'local_only_times': [stamp.isoformat() for stamp in sorted(local.keys() - shifted.keys())],
            'yahoo_only_times': [stamp.isoformat() for stamp in sorted(shifted.keys() - local.keys())], 'ohlc': fields,
            'volume_compared': len(valid_volume), 'volume_different': sum(a != b for a, b in valid_volume),
            'volume_unknown': len(volumes) - len(valid_volume)}
    return result


def capture(out, root=ROOT, *, urlopen=None):
    out, root = Path(out), Path(root)
    out.mkdir(parents=True, exist_ok=False)
    report = {'purpose': 'fixed-day timestamp/OHLC source quality only; no strategy returns', 'date': DAY,
              'symbols': list(SYMBOLS), 'created_at': _now(), 'requests': [], 'errors': [], 'source_pins': {},
              'limitations': 'One-day fitted scale/residual diagnostic; not proof of full history or source independence.',
              'code_sha256': {str(path): sha256_file(path) for path in (Path(__file__), Path(__file__).with_name('source_recheck.py'))}}
    try:
        if sha256_file(root / 'CHECKSUMS.sha256') != CHECKSUM_SHA:
            raise ValueError('source checksum-list mismatch')
        report['source_checksums_sha256'] = CHECKSUM_SHA
        for symbol in SYMBOLS:
            path = root / ('US.' + symbol + '.csv')
            if path.is_symlink() or sha256_file(path) != PINS[symbol]:
                raise ValueError('source price pin mismatch: ' + symbol)
            report['source_pins'][str(path)] = PINS[symbol]
        local = {symbol: local_day(root / ('US.' + symbol + '.csv'), symbol, out / (symbol + '.opend.csv')) for symbol in SYMBOLS}
        urlopen = urlopen or urllib.request.build_opener(_NoRedirect()).open
        for symbol in SYMBOLS:
            record = {'symbol': symbol, 'url': request_url(symbol), 'started_at': _now(), 'file': symbol + '.yahoo.raw', 'body_complete': False}
            report['requests'].append(record)
            try:
                with (out / record['file']).open('xb') as handle:
                    try:
                        response = urlopen(urllib.request.Request(record['url'], headers={'User-Agent': 'Mozilla/5.0'}), timeout=20)
                    except urllib.error.HTTPError as exc:
                        response = exc  # Preserve the full error response, not just its message.
                    with response:
                        record.update(status=response.status, headers={key: value for key, value in
                                      (response.headers or {}).items() if key.lower() in PUBLIC_HEADERS})
                        while chunk := response.read(65536):
                            handle.write(chunk)
                    record['body_complete'] = True
                if record['status'] != 200:
                    raise ValueError('HTTP status ' + str(record['status']))
                yahoo, record['coverage'] = yahoo_rows(out / record['file'], symbol)
                record['comparison'] = compare(local[symbol], yahoo)
            except Exception as exc:
                record['error'] = type(exc).__name__ + ': ' + str(exc)
                report['errors'].append(symbol + ': ' + record['error'])
            record.update(finished_at=_now(), bytes=(out / record['file']).stat().st_size)
    except Exception as exc:
        report['errors'].append(type(exc).__name__ + ': ' + str(exc))
    report.update(completed_at=_now(), status='completed_with_errors' if report['errors'] else 'completed')
    _write_json(out / 'manifest.json', report)
    write_checksums(out)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args(argv)
    result = capture(args.out)
    print(json.dumps({'status': result['status'], 'requests': len(result['requests']), 'errors': result['errors']}))

if __name__ == '__main__':
    main()
