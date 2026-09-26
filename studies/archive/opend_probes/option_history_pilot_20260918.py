import csv
import hashlib
import json
import time
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import futu as ft
from futu.quote.quote_query import RequestHistoryKlineQuery

ROOT = Path('/opt/opend-us-options')
OUT = ROOT / 'data/or-option-history-pilot-20260918-work'
OLD = ROOT / 'data/custody-eval-2026-09-18-v2'
NOTE = ROOT / 'studies/us_opening_range/notes/OPTION_HISTORY_PILOT.md'
DAY = '2026-09-18'
CODES = ('US.SPY260918C761000', 'US.SPY260918P761000')
ET = ZoneInfo('America/New_York')


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def now():
    return datetime.now(ET).isoformat()


def write_json(path, value):
    with path.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False, allow_nan=False)
        stream.write('\n')


def quota(ctx):
    ret, value = ctx.get_history_kl_quota(get_detail=False)
    if ret != ft.RET_OK:
        return {'ret': ret, 'error': str(value)}
    return {'ret': ret, 'used': int(value[0]), 'remaining': int(value[1]),
            'independent_option_remaining': None}


def quality(code, rows):
    times = [datetime.fromisoformat(str(row['time_key'])).replace(tzinfo=ET)
             for row in rows]
    start = datetime.fromisoformat(DAY + 'T09:30:00').replace(tzinfo=ET)
    expected = [start + timedelta(minutes=i) for i in range(1, 406)]
    with (OLD / 'option' / (code + '.csv')).open(newline='') as stream:
        old_times = [datetime.fromisoformat(row['close_time'])
                     for row in csv.DictReader(stream)]
    report = {
        'rows': len(times), 'first_time': min(times).isoformat() if times else None,
        'last_time': max(times).isoformat() if times else None,
        'unique_times': len(set(times)), 'duplicate_times': len(times) - len(set(times)),
        'dates': sorted({value.date().isoformat() for value in times}),
        'codes': sorted({row['code'] for row in rows}),
        'missing_full_405_times': sorted(value.isoformat() for value in set(expected) - set(times)),
        'unexpected_full_405_times': sorted(value.isoformat() for value in set(times) - set(expected)),
        'core_390_complete': set(expected[:390]).issubset(times),
        'full_405_complete': times == expected,
        'positive_volume_rows': sum(float(row['volume']) > 0 for row in rows),
        'old_rows': len(old_times), 'old_first_time': min(old_times).isoformat(),
        'old_last_time': max(old_times).isoformat(),
        'timestamps_exactly_equal_to_existing': times == old_times,
        'existing_file_sha256': digest(OLD / 'option' / (code + '.csv')),
        'comparison_scope': 'row_counts_and_timestamps_only_no_return_evaluation',
    }
    report['passes'] = (report['full_405_complete'] and report['codes'] == [code])
    return report


def main():
    pair = [row for row in json.loads((OLD / 'cases.json').read_text())['cases']
            if row['symbol'] == 'US.SPY' and row['trade_date'] == DAY]
    assert {row['contract'] for row in pair} == set(CODES)
    assert len(pair) == 2 and {row['right'] for row in pair} == {'CALL', 'PUT'}
    assert all(row['expiry'] == DAY and row['strike'] == 761
               and row['selection'] == 'both_sides_atm_at_open' for row in pair)
    OUT.mkdir(exist_ok=False)
    manifest = {
        'schema': 'option-history-availability-pilot/1',
        'role': 'availability_only_previously_evaluated_data_not_new_validation',
        'source': 'OpenD/request_history_kline', 'sdk_version': ft.__version__,
        'started_at': now(), 'finished_at': None, 'status': 'RUNNING',
        'authorization_max_new_independent_option_chain_quota': 1,
        'codes': list(CODES), 'chain': {'underlying': 'US.SPY', 'expiry': DAY},
        'parameters': {'start': DAY, 'end': DAY, 'ktype': ft.KLType.K_1M,
                       'autype': ft.AuType.NONE, 'session': ft.Session.RTH,
                       'extended_time': False, 'max_count': 1000},
        'max_history_packets_per_leg': 2, 'min_history_packet_interval_seconds': 1.05,
        'preregistration_sha256_before_run': digest(NOTE),
        'oneoff_script_sha256': digest(Path(__file__)),
        'existing_cases_sha256': digest(OLD / 'cases.json'),
        'ordinary_quota_before': None, 'ordinary_quota_after': None,
        'independent_option_remaining': None,
        'quota_caveat': 'No independent option history quota field is exposed; concurrent ordinary ETF collection prevents attribution of ordinary quota changes.',
        'history_packets': [], 'quality': {}, 'errors': [], 'connection_closed': False,
        'output_sha256': {},
    }
    write_json(OUT / 'authorization.json', {
        key: manifest[key] for key in ('started_at', 'codes', 'chain', 'parameters',
            'authorization_max_new_independent_option_chain_quota',
            'preregistration_sha256_before_run', 'oneoff_script_sha256')})
    counts = Counter()
    last_packet = 0.0
    original_pack = RequestHistoryKlineQuery.pack_req

    def guarded_pack(cls, **args):
        nonlocal last_packet
        assert args['code'] in CODES and args['start_date'][:10] == DAY
        assert args['end_date'][:10] == DAY and args['ktype'] == ft.KLType.K_1M
        assert args['autype'] == ft.AuType.NONE and args['session'] == ft.Session.RTH
        assert args['extended_time'] is False and args['max_num'] <= 1000
        if counts[args['code']] >= 2:
            raise RuntimeError('Hard history packet limit reached; no further packet sent')
        time.sleep(max(0.0, 1.05 - (time.monotonic() - last_packet)))
        last_packet = time.monotonic()
        counts[args['code']] += 1
        manifest['history_packets'].append({'code': args['code'], 'sent_at': now(),
                                           'page': counts[args['code']]})
        return original_pack(**args)

    RequestHistoryKlineQuery.pack_req = classmethod(guarded_pack)
    ctx = None
    try:
        ctx = ft.OpenQuoteContext(host='127.0.0.1', port=11111)
        manifest['ordinary_quota_before'] = quota(ctx)
        for code in CODES:
            rows = []
            page_key = None
            raw_path = OUT / (code + '.csv')
            while True:
                ret, frame, next_key = ctx.request_history_kline(
                    code, page_req_key=page_key, **manifest['parameters'])
                if ret != ft.RET_OK:
                    raise RuntimeError(f'{code}: {frame}')
                with raw_path.open('x' if page_key is None else 'a', newline='') as stream:
                    frame.to_csv(stream, index=False, header=page_key is None)
                rows.extend(frame.to_dict(orient='records'))
                manifest['output_sha256'][raw_path.name] = digest(raw_path)
                if next_key is None:
                    break
                if counts[code] >= 2:
                    raise RuntimeError(f'{code}: pagination incomplete after hard two-page limit')
                page_key = next_key
            # Each leg has at most 2 bounded pages; no full-dataset tapes are retained.
            manifest['quality'][code] = quality(code, rows)
            if not manifest['quality'][code]['passes']:
                raise RuntimeError(f'{code}: fixed time-grid quality check failed; stop without trying another leg')
        manifest['status'] = 'SUCCESS'
    except Exception as error:
        manifest['status'] = 'FAILED'
        manifest['errors'].append({'type': type(error).__name__, 'message': str(error), 'at': now()})
    finally:
        if ctx is not None:
            try:
                manifest['ordinary_quota_after'] = quota(ctx)
            except Exception as error:
                manifest['errors'].append({'type': type(error).__name__, 'message': str(error), 'at': now()})
            finally:
                ctx.close()
                manifest['connection_closed'] = True
        RequestHistoryKlineQuery.pack_req = original_pack
        manifest['finished_at'] = now()
        write_json(OUT / 'manifest.json', manifest)
        with (OUT / 'CHECKSUMS.sha256').open('x') as stream:
            for path in sorted(OUT.iterdir()):
                if path.is_file() and path.name != 'CHECKSUMS.sha256':
                    stream.write(f'{digest(path)}  {path.name}\n')
    print(json.dumps({key: manifest[key] for key in ('status', 'started_at', 'finished_at',
        'history_packets', 'quality', 'errors', 'ordinary_quota_before',
        'ordinary_quota_after', 'independent_option_remaining', 'connection_closed')},
        indent=2, ensure_ascii=False))
    return 0 if manifest['status'] == 'SUCCESS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
