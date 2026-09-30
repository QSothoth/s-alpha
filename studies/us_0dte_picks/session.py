"""Inspect a watch session or explicitly accept one fresh review card into custody."""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta
from decimal import Decimal
import fcntl
import hashlib
import json
import os
import pwd
from pathlib import Path
import sqlite3
import subprocess
import time

from custody.models import ET, instant
from custody.runner import SECURITY_FIRMS
from .launch_watch import ROOT, DEFAULT_PYTHON
from .live_watch import option_check, write_json_atomic

RUNTIME = ROOT / 'data/near-expiry-runtime'


def selected_action(card, contract, now):
    if card.get('status') != 'ENTER_REVIEW':
        raise ValueError('no fresh opportunity: ' + card.get('status', 'missing'))
    start, end = instant(card['as_of']), instant(card['valid_until'])
    if not start <= now < end or end-start > timedelta(minutes=1):
        raise ValueError('review card expired or invalid')
    if card.get('trade_date') != now.astimezone(ET).date().isoformat():
        raise ValueError('review card must be for today')
    matches = [a for a in card['actions'] if a['contract'] == contract]
    if len(matches) != 1:
        raise ValueError('contract not uniquely present in current review card')
    action = matches[0]
    request = action['custody_request']
    if (request['contract'] != contract or request['symbol'] != action['symbol'] or
            request['direction'] != action['direction'] or request['strategy'] != 'open_hold_v3' or
            request['max_qty'] != 1 or request['expiry_policy'] != 'nearest' or
            not 0 < Decimal(str(request['max_entry_premium'])) <= Decimal('280')):
        raise ValueError('invalid custody handoff request')
    return action


def reserve(ledger, action):
    """Reserve caps, not quoted costs; never recycle spent or uncertain reservations."""
    rows = ledger.get('accepted', [])
    if any(r['symbol'] == action['symbol'] or r['contract'] == action['contract'] for r in rows):
        raise ValueError('symbol or contract already accepted today')
    cap = Decimal(str(action['custody_request']['max_entry_premium']))
    if len(rows) >= 2 or sum((Decimal(str(r['cap'])) for r in rows), cap) > Decimal('280'):
        raise ValueError('daily limit: two contracts, total premium caps <= 280 USD')
    entry = {'symbol': action['symbol'], 'contract': action['contract'], 'cap': float(cap),
             'state': 'RESERVED', 'accepted_at': datetime.now(ET).isoformat()}
    rows.append(entry)
    ledger['accepted'] = rows
    return entry


def custody_command(action, deadline, db, mode='dryrun', acc_id=None, firm='FUTUSECURITIES', trade_action='round_trip'):
    r = action['custody_request']
    command = [str(DEFAULT_PYTHON), '-m', 'custody', 'dryrun' if mode == 'dryrun' else 'run']
    if trade_action not in ('round_trip', 'buy_only'):
        raise ValueError('review cards only support round_trip or buy_only; sell_only uses existing holdings')
    if trade_action != 'round_trip':
        command += ['--trade-action', trade_action]
    if mode != 'dryrun':
        if acc_id is None:
            raise ValueError('explicit account required for paper/live')
        command += ['--mode', mode, '--acc-id', str(acc_id), '--security-firm', firm]
    for key in ('strategy', 'symbol', 'direction', 'contract', 'max_qty', 'max_entry_premium', 'expiry_policy'):
        command += ['--' + key.replace('_', '-'), str(r[key])]
    return command + ['--entry-valid-until', deadline, '--stream-only', '--db', str(db)]


def jobs_in(db):
    if not db.exists():
        return []
    with sqlite3.connect(db.resolve().as_uri() + '?mode=ro', uri=True) as conn:
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='jobs'").fetchone():
            return []
        return [json.loads(row[0]) for row in conn.execute('SELECT body FROM jobs')]


def status(folder):
    if not folder.is_dir():
        raise ValueError('session directory does not exist: ' + str(folder))
    monitor = folder/'monitor'
    ready = json.loads((monitor/'ready.json').read_text()) if (monitor/'ready.json').exists() else None
    service = json.loads((monitor/'service.json').read_text()) if (monitor/'service.json').exists() else {}
    if service:
        service['active_state'] = subprocess.run(
            ['systemctl', 'show', service['unit'], '--property=ActiveState', '--value'],
            capture_output=True, text=True, check=False).stdout.strip()
    card = json.loads((monitor/'review_card.json').read_text()) if (monitor/'review_card.json').exists() else None
    now = datetime.now(ET)
    latest = json.loads((monitor/'latest.json').read_text()) if (monitor/'latest.json').exists() else {}
    day = ready['trade_date'] if ready else now.date().isoformat()
    workers = []
    for path in sorted((RUNTIME/day).glob('*/ledger.json')):
        ledger = json.loads(path.read_text())
        for entry in ledger.get('accepted', []):
            if entry.get('unit'):
                entry['active_state'] = subprocess.run(
                    ['systemctl', 'show', entry['unit'], '--property=ActiveState', '--value'],
                    capture_output=True, text=True, check=False).stdout.strip()
        workers.append({'ledger': str(path), **ledger})
    jobs = []
    for db in sorted((RUNTIME/day).glob('*/custody.sqlite')):
        for job in jobs_in(db):
            jobs.append({'db': str(db), **{k: job[k] for k in ('id', 'mode', 'state', 'position_qty', 'attention')},
                         'trade_action': job['request'].get('trade_action', 'round_trip'),
                         'symbol': job['request']['symbol'], 'contract': job['request']['contract']})
    current = bool(card and card.get('as_of') and card.get('valid_until')
                   and instant(card['as_of']) <= now < instant(card['valid_until'])
                   and card.get('trade_date') == now.date().isoformat())
    mock_path = folder/'mock/latest.json'
    mock = json.loads(mock_path.read_text()) if mock_path.exists() else None
    if mock is not None:
        stamp = instant(mock['as_of']) if mock.get('as_of') else None
        age = (now-stamp).total_seconds() if stamp else None
        mock = {**mock, 'source': str(mock_path), 'age_seconds': age,
                'fresh': age is not None and 0 <= age <= 120,
                'finished': (folder/'mock/final.json').exists()}
    return {'now': now.isoformat(), 'session': str(folder.resolve()),
            'runtime_scope': 'all sessions and accounts for this trade date, grouped by mode',
            'trade_date': day, 'ready': ready, 'service': service, 'mock': mock,
            'status': 'STOPPED' if service and service['active_state'] != 'active' else
                      card['status'] if current else 'PREMARKET_WAIT' if ready and day == now.date().isoformat()
                      and now.hour*60+now.minute < 570 else 'STALE_OR_STOPPED',
            'review_card': card, 'errors': latest.get('errors', {}),
            'ranking': [{k: r.get(k) for k in ('code', 'direction', 'strength_sigma', 'rvol', 'expiry')}
                        for r in latest.get('ranking', [])], 'handoffs': workers, 'jobs': jobs}


def accept(folder, contract, mode, acc_id, firm, execute, trade_action='round_trip'):
    path = folder/'monitor/review_card.json'
    raw = path.read_bytes()
    card = json.loads(raw)
    action = selected_action(card, contract, datetime.now(ET))
    digest = hashlib.sha256(raw).hexdigest()[:16]
    # All sessions share one per-day ledger for each execution mode, even across accounts.
    runtime = RUNTIME/card['trade_date']/mode
    command = custody_command(action, card['valid_until'], runtime/'custody.sqlite', mode, acc_id, firm, trade_action)
    if not execute:
        return {'executed': False, 'request': action, 'command': command,
                'next': 'add --execute to accept this still-fresh card; live also requires --mode live --acc-id'}
    if mode == 'live' and not any(os.environ.get(key) for key in ('FUTU_TRADE_PASSWORD', 'FUTU_TRADE_PASSWORD_MD5')):
        raise ValueError('live requires trade password in the environment')
    runtime.mkdir(parents=True, exist_ok=True)
    with (runtime/'handoff.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        ledger_path = runtime/'ledger.json'
        ledger = json.loads(ledger_path.read_text()) if ledger_path.exists() else {'accepted': []}
        reserve(ledger, action)  # Check the session budget before any preflight.
        preflight_db = runtime/f'preflight-{digest}-{contract}.sqlite'
        preflight = custody_command(action, card['valid_until'], preflight_db, trade_action=trade_action) + ['--once']
        environment = {**os.environ, 'PYTHONUTF8': '1', 'PYTHONIOENCODING': 'utf-8'}
        environment.setdefault('HOME', pwd.getpwuid(os.getuid()).pw_dir)
        environment.pop('CUSTODY_WXPUSHER_SPT', None)
        result = subprocess.run(preflight, cwd=ROOT, capture_output=True, text=True,
                                timeout=45, env=environment)
        (runtime/f'preflight-{digest}-{contract}.log').write_text(result.stdout + result.stderr)
        jobs = jobs_in(preflight_db)
        if result.returncode or len(jobs) != 1 or jobs[0]['position_qty'] != 1:
            raise ValueError('dryrun did not confirm a simulated entry; inspect preflight log')
        # Recheck both freshness and the live quote after the real dryrun.
        selected_action(card, contract, datetime.now(ET))
        if path.read_bytes() != raw:
            raise ValueError('review card changed during dryrun; read the current card')
        from custody.opend import OpenDMarket, OpenDContractResolver
        with OpenDMarket() as market:
            expiry = OpenDContractResolver(market).nearest_expiry(action['symbol'], card['trade_date'])
            quote = market.snapshot([contract])[contract]
            checked = option_check(quote, action['direction'], card['trade_date'], datetime.now(ET),
                                   action['custody_request']['max_entry_premium'], expiry)
            if checked['rejections'] or expiry != action['expiry']:
                raise ValueError('live contract check failed: ' + str(checked))
        selected_action(card, contract, datetime.now(ET))
        unit = 'near-expiry-' + mode + '-' + card['trade_date'].replace('-', '') + '-' + contract.replace('.', '-').lower()
        entry = ledger['accepted'][-1]
        entry.update(unit=unit, card_hash=digest, account=acc_id, security_firm=firm, trade_action=trade_action)
        write_json_atomic(runtime/f'accepted-{digest}-{contract}.json', card)
        write_json_atomic(ledger_path, ledger)  # A crash or uncertain launch keeps the reservation.
        service_command = ['systemd-run', '--unit='+unit, '--collect', '--property=Type=exec',
                           '--property=User='+pwd.getpwuid(os.getuid()).pw_name,
                           '--property=MemoryMax=512M', '--property=Restart=on-failure', '--property=RestartSec=5s',
                           '--property=WorkingDirectory='+str(ROOT),
                           '--setenv=PYTHONUTF8=1', '--setenv=PYTHONIOENCODING=utf-8']
        names = ['FUTU_HOST', 'FUTU_PORT']
        if mode == 'live':
            names += ['FUTU_TRADE_PASSWORD', 'FUTU_TRADE_PASSWORD_MD5']
        for name in names:
            if os.environ.get(name):
                service_command.append('--setenv='+name)  # Forward by name; never place secrets in argv.
        subprocess.run(service_command + command, check=True, cwd=ROOT)
        entry['state'] = 'SERVICE_STARTED'
        write_json_atomic(ledger_path, ledger)
        for _ in range(15):
            jobs = [j for j in jobs_in(runtime/'custody.sqlite') if j['request']['contract'] == contract]
            if jobs:
                entry.update(state='JOB_CREATED', job_id=jobs[0]['id'])
                write_json_atomic(ledger_path, ledger)
                break
            active = subprocess.run(['systemctl', 'show', unit, '--property=ActiveState', '--value'],
                                    check=False, capture_output=True, text=True).stdout.strip()
            if active not in ('active', 'activating'):
                raise ValueError('custody service not ready; reservation retained; inspect journal: ' + unit)
            time.sleep(1)
        else:
            raise ValueError('custody job readiness timed out; reservation retained: ' + unit)
        return {'unit': unit, 'db': str(runtime/'custody.sqlite'), 'mode': mode,
                'state': entry['state'], 'job_id': entry['job_id'],
                'note': 'inspect status for actual position/fill; reservation retained'}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['status', 'accept'])
    parser.add_argument('--session', type=Path, required=True)
    parser.add_argument('--contract')
    parser.add_argument('--mode', choices=['dryrun', 'paper', 'live'], default='dryrun')
    parser.add_argument('--acc-id', type=int)
    parser.add_argument('--security-firm', choices=SECURITY_FIRMS, default='FUTUSECURITIES')
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--trade-action', choices=['round_trip', 'buy_only'], default='round_trip')
    args = parser.parse_args(argv)
    try:
        if args.command == 'status':
            result = status(args.session)
        else:
            if not args.contract:
                parser.error('accept requires --contract from the current review card')
            result = accept(args.session, args.contract, args.mode, args.acc_id, args.security_firm, args.execute,
                            args.trade_action)
    except (ValueError, OSError, KeyError, subprocess.SubprocessError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
