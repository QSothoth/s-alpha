"""One finite, read-only P5 collection. No historical-kline requests.

Use the OpenD venv: python -m studies.us_0dte_picks.fetch_p5 --out <new directory>
--check verifies the locked local screening inputs and exercises industry selection without connecting.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
from datetime import datetime, timezone
import json
from math import isfinite
from pathlib import Path
from statistics import mean, median

from . import daily_k
from .daily_list import Client, records
from .parity import sha256

HERE = Path(__file__).resolve().parent
PREREG = HERE / 'notes/P5_PREREG.md'
PREREG_SHA256 = '99d4f1ec0523be9c7f7510460dd2a50cf0522a4aec471c42a0c04489bf815ea3'
INVENTORY = HERE / 'notes/test_sets_inventory.json'
INVENTORY_SHA256 = '418646c358fb7ddec307f905f1fe9ca9c9cadc631efcdb1c2788a1e447371cb3'
BATCH = 50


def now():
    return datetime.now(timezone.utc).isoformat()


def write(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8') as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, allow_nan=False, default=str)
        handle.write('\n')


def check(path, expected):
    if sha256(path) != expected:
        raise ValueError('Frozen input checksum mismatch: ' + str(path))


def candidates():
    check(PREREG, PREREG_SHA256)
    check(INVENTORY, INVENTORY_SHA256)
    inventory = json.loads(INVENTORY.read_text(encoding='utf-8'))
    pinned, checksums = {}, {}
    for dataset in inventory['datasets']:
        root = Path(dataset['directory'])
        checksum_path = root / 'CHECKSUMS.sha256'
        check(checksum_path, dataset['checksums_sha256'])
        pinned[str(checksum_path)] = dataset['checksums_sha256']
        for line in checksum_path.read_text(encoding='utf-8').splitlines():
            digest, name = line.split(maxsplit=1)
            checksums[str(root / name.lstrip('*'))] = digest
    ranks = {}
    for universe in inventory['universes']:
        path = Path(universe['path'])
        check(path, universe['sha256'])
        pinned[str(path)] = universe['sha256']
        for row in json.loads(path.read_text(encoding='utf-8'))['symbols']:
            if row['code'] in ranks:
                raise ValueError('Duplicate universe code: ' + row['code'])
            ranks[row['code']] = len(ranks) + 1
    eligible = []
    for original in inventory['p5_feasibility_only']['candidates']:
        symbol = original['symbol']
        if symbol in inventory['existing_minute_files_by_symbol']:
            raise ValueError('Previously observed minute symbol: ' + symbol)
        if symbol in ('GOOG', 'SPCX', 'B') or original['daily_screen_days'] < 40:
            continue
        row = dict(original, code='US.' + symbol)
        if row['rank'] != ranks[row['code']]:
            raise ValueError('Inventory rank differs: ' + symbol)
        expiry = daily_k.EVENTS / 'expiry' / (symbol + '.json')
        path = Path(row['daily_source'])
        for source in (expiry, path):
            digest = checksums[str(source)]
            check(source, digest)
            pinned[str(source)] = digest
        row['weekly'], row['mon_wed'] = daily_k.schedule(symbol)
        if not row['weekly']:
            raise ValueError('Frozen weekly eligibility differs: ' + symbol)
        previous, scores, days = None, [], []
        with path.open(newline='', encoding='utf-8') as handle:
            for bar in csv.DictReader(handle):
                high, low, close = (float(bar[f]) for f in ('high', 'low', 'close'))
                if ('2026-03-01' <= bar['date'] <= '2026-05-31' and previous is not None
                        and all(isfinite(v) and v > 0 for v in (high, low, close, previous))):
                    scores.append((max(high, previous) - min(low, previous)) / close)
                    days.append(bar['date'])
                previous = close
        if len(scores) < 40:
            continue
        score = mean(scores)
        if len(scores) != row['daily_screen_days'] or abs(score - row['mean_true_range_over_close']) > 1e-12:
            raise ValueError('Inventory activity measure differs: ' + symbol)
        keep = ('symbol', 'code', 'rank', 'market_cap_b', 'daily_source', 'weekly', 'mon_wed')
        eligible.append({**{k: row[k] for k in keep}, 'daily_sha256': pinned[str(path)],
                         'daily_screen_days': len(scores), 'daily_screen_window': [days[0], days[-1]],
                         'mean_true_range_over_close': score})
    cutoff = median(r['mean_true_range_over_close'] for r in eligible)
    active = sorted((r for r in eligible if r['mean_true_range_over_close'] >= cutoff), key=lambda r: (r['rank'], r['code']))
    if len(eligible) != 419 or len(active) != 210:
        raise ValueError('Locked 419 eligible / 210 active counts differ')
    return active, cutoff, pinned


def select(active, industry_rows):
    by_code, counts, selected, excluded = defaultdict(list), Counter(), [], []
    for row in industry_rows:
        if row['plate_type'] == 'INDUSTRY' and row.get('plate_code'):
            by_code[row['code']].append(row)
    for row in sorted(active, key=lambda r: (r['rank'], r['code'])):
        industries = {r['plate_code']: r for r in by_code[row['code']]}
        if not industries:
            excluded.append({'code': row['code'], 'reason': 'no INDUSTRY metadata or request failed'})
            continue
        codes = sorted(industries)
        industry = industries[codes[0]]
        if counts[codes[0]] >= 10:
            excluded.append({'code': row['code'], 'reason': 'industry cap 10', 'industry_code': codes[0]})
            continue
        counts[codes[0]] += 1
        selected.append(dict(row, industry_code=codes[0], industry_name=industry['plate_name'],
                             multiple_industries=len(codes) > 1, industry_candidates=codes))
    return selected, excluded, dict(sorted(counts.items()))


def collect(client, out, active, cutoff, pinned):
    out.mkdir(parents=True, exist_ok=False)
    requests, errors = [], []
    manifest = {'started_at': now(), 'preregistration_sha256': PREREG_SHA256, 'inventory_sha256': INVENTORY_SHA256,
                'collector_sha256': sha256(Path(__file__)), 'sdk_version': client.ft.__version__,
                'input_sha256': pinned, 'parameters': {'ktype': 'K_30M', 'autype': 'QFQ', 'session': 'RTH',
                    'subscribe_push': False, 'num': 1000, 'batch_max': BATCH, 'hold_seconds': 61,
                    'calendar_start': '2026-05-01', 'calendar_end': '2026-09-25'}, 'status': 'incomplete'}

    def request(endpoint, *args, **kwargs):
        log = {'endpoint': endpoint, 'args': args, 'kwargs': kwargs, 'requested_at': now()}
        requests.append(log)
        try:
            result = client.call(endpoint, *args, **kwargs)
            log['ok'] = True
            return result
        except Exception as exc:
            log.update(ok=False, error=str(exc))
            raise
        finally:
            log['returned_at'] = now()

    try:
        initial_quota = request('query_subscription', is_all_conn=True)[1]
        write(out / 'subscription_before.json', initial_quota)
        if int(initial_quota['remain']) < 1:
            raise RuntimeError('No available subscription quota')
        write(out / 'candidates.json', {'eligible_count': 419, 'median': cutoff, 'active': active})
        calendar = records(request('request_trading_days', market='US', start='2026-05-01', end='2026-09-25')[1])
        write(out / 'calendar.json', calendar)
        industries = []
        for start in range(0, len(active), 200):
            codes = [row['code'] for row in active[start:start + 200]]
            try:
                rows = records(request('get_owner_plate', codes)[1])
                write(out / 'owner_plate' / ('%03d.json' % start), {'codes': codes, 'rows': rows})
                industries.extend(rows)
            except RuntimeError as exc:
                write(out / 'owner_plate' / ('%03d.json' % start), {'codes': codes, 'error': str(exc)})
                errors.extend({'stage': 'industry', 'code': code, 'error': str(exc), 'requested_at': now()} for code in codes)
        selected, excluded, counts = select(active, industries)
        selection = {'preregistration_sha256': PREREG_SHA256, 'inventory_sha256': INVENTORY_SHA256,
                     'frozen_at': now(), 'screen_window': ['2026-03-01', '2026-05-31'], 'median': cutoff,
                     'selected': selected, 'excluded': excluded, 'industry_counts': counts}
        write(out / 'selection.json', selection)
        frozen = {str(p.relative_to(out)): sha256(p) for p in sorted(out.rglob('*.json'))}
        write(out / 'metadata_checksums.json', frozen)
        manifest.update(selection_sha256=frozen['selection.json'], metadata_checksums_sha256=sha256(out / 'metadata_checksums.json'),
                        selected_count=len(selected), industry_count=len(counts))
        print('FROZEN', len(selected), 'stocks', len(counts), 'industries', 'selection_sha256', frozen['selection.json'], flush=True)
        print('SELECTED', ','.join(row['symbol'] for row in selected), flush=True)
        for start in range(0, len(selected), BATCH):
            check(PREREG, PREREG_SHA256)
            check(INVENTORY, INVENTORY_SHA256)
            check(out / 'metadata_checksums.json', manifest['metadata_checksums_sha256'])
            for name, digest in frozen.items():
                check(out / name, digest)
            for name, digest in pinned.items():
                check(Path(name), digest)
            part = selected[start:start + BATCH]
            codes = [row['code'] for row in part]
            quota = request('query_subscription', is_all_conn=True)[1]
            write(out / 'subscription_batches' / ('%03d.json' % start), quota)
            if int(quota['remain']) < len(codes):
                raise RuntimeError('Insufficient subscription quota for the frozen batch')
            request('subscribe', codes, [client.ft.SubType.K_30M], session=client.ft.Session.RTH, subscribe_push=False)
            began = client.clock()
            try:
                for row in part:
                    try:
                        bars = records(request('get_cur_kline', row['code'], 1000, client.ft.SubType.K_30M, client.ft.AuType.QFQ)[1])
                        write(out / 'k30' / (row['symbol'] + '.json'), bars)
                        requests[-1]['rows'] = len(bars)
                        print('SAVED', row['symbol'], len(bars), flush=True)
                    except RuntimeError as exc:
                        errors.append({'stage': 'minutes', 'code': row['code'], 'error': str(exc), 'requested_at': now()})
                        print('FAILED', row['symbol'], str(exc), flush=True)
            finally:
                while client.clock() - began < 61:
                    client.pause(max(0, min(30, 61 - (client.clock() - began))))
                request('unsubscribe', codes, [client.ft.SubType.K_30M])
        write(out / 'subscription_after.json', request('query_subscription', is_all_conn=True)[1])
        manifest['status'] = 'complete'
    except Exception as exc:
        errors.append({'stage': 'collection', 'error': str(exc), 'requested_at': now()})
        raise
    finally:
        write(out / 'errors.json', errors)
        manifest.update(finished_at=now(), requests=requests, client_attempts=client.log, error_count=len(errors))
        write(out / 'manifest.json', manifest)
        paths = sorted(p for p in out.rglob('*') if p.is_file())
        with (out / 'CHECKSUMS.sha256').open('x', encoding='utf-8') as handle:
            for path in paths:
                handle.write(sha256(path) + '  ' + str(path.relative_to(out)) + '\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=Path('data/p5-k30-validation-raw'))
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    active, cutoff, pinned = candidates()
    if args.check:
        sample = [{'code': 'US.TEST', 'symbol': 'TEST', 'rank': 1}]
        rows = [dict(code='US.TEST', plate_type=t, plate_code=c, plate_name=c)
                for t, c in [('CONCEPT', 'A'), ('INDUSTRY', 'C'), ('INDUSTRY', 'B')]]
        chosen, excluded, _ = select(sample, rows)
        assert chosen[0]['industry_code'] == 'B' and chosen[0]['multiple_industries'] and not excluded
        assert not select(sample, rows[:1])[0]
        sample = [dict(code='US.T%02d' % i, rank=i) for i in range(12)]
        rows = [dict(code=r['code'], plate_type='INDUSTRY', plate_code='A', plate_name='A') for r in sample]
        assert [r['rank'] for r in select(list(reversed(sample)), rows)[0]] == list(range(10))
        print('Checked:', len(active), 'active candidates; median:', cutoff, '; source hashes:', len(pinned))
        return
    import futu as ft
    context = ft.OpenQuoteContext(host='127.0.0.1', port=11111)
    try:
        collect(Client(context, ft), args.out, active, cutoff, pinned)
    finally:
        context.close()


if __name__ == '__main__':
    main()
