"""Launch one bounded, supervised read-only 0DTE watch session."""
from __future__ import annotations

import argparse
from datetime import datetime
import json
import math
import os
from pathlib import Path
import pwd
import subprocess
import time

from custody.models import ET


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PYTHON = Path('/opt/futu-opend/venv/bin/python')


def validate_launch(candidates, baselines, out, until, budget, fee_reserve, now):
    if out.exists():
        raise ValueError('output directory already exists')
    ranking = json.loads(candidates.read_text())
    json.loads(baselines.read_text())
    if ranking.get('trade_date') != now.date().isoformat():
        raise ValueError('candidate file must be for today')
    cutoff = datetime.fromisoformat(f'{now.date().isoformat()}T{until}').replace(tzinfo=ET)
    latest = now.replace(hour=15, minute=45, second=0, microsecond=0)
    if not now < cutoff <= latest:
        raise ValueError('cutoff must be later today and no later than 15:45 ET')
    if not all(math.isfinite(x) for x in (budget, fee_reserve)) or not 0 <= fee_reserve < budget:
        raise ValueError('budget must exceed a nonnegative fee reserve')
    return cutoff


def build_command(unit, candidates, baselines, out, until, budget, fee_reserve,
                  cutoff, now, python=DEFAULT_PYTHON):
    runtime = math.ceil((cutoff - now).total_seconds()) + 90
    user = pwd.getpwuid(os.getuid()).pw_name
    return [
        'systemd-run', f'--unit={unit}', '--collect', '--property=Type=exec',
        f'--property=User={user}', '--property=MemoryMax=512M',
        f'--property=RuntimeMaxSec={runtime}s', f'--property=WorkingDirectory={ROOT}',
        '--setenv=PYTHONUTF8=1', '--setenv=PYTHONIOENCODING=utf-8',
        str(python), '-m', 'studies.us_0dte_picks.live_watch',
        '--candidates', str(candidates.resolve()), '--baselines', str(baselines.resolve()),
        '--out', str(out.resolve()), '--until', until,
        '--budget-usd', str(budget), '--fee-reserve-usd', str(fee_reserve),
    ]


def wait_ready(unit, ready, timeout):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if ready.exists():
            return json.loads(ready.read_text())
        state = subprocess.run(
            ['systemctl', 'show', unit, '--property=ActiveState', '--value'],
            check=False, capture_output=True, text=True).stdout.strip()
        if state in {'failed', 'inactive'}:
            raise RuntimeError(f'{unit} stopped before readiness: {state}')
        time.sleep(1)
    subprocess.run(['systemctl', 'stop', unit], check=False, capture_output=True, text=True)
    raise TimeoutError(f'{unit} did not become ready within {timeout:g}s')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidates', type=Path, required=True)
    parser.add_argument('--baselines', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--until', default='10:45')
    parser.add_argument('--budget-usd', type=float, default=300)
    parser.add_argument('--fee-reserve-usd', type=float, default=20)
    parser.add_argument('--startup-timeout', type=float, default=120)
    parser.add_argument('--check-only', action='store_true')
    args = parser.parse_args(argv)
    now = datetime.now(ET)
    try:
        cutoff = validate_launch(args.candidates, args.baselines, args.out, args.until,
                                 args.budget_usd, args.fee_reserve_usd, now)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    unit = 'us0dte-watch-' + now.strftime('%Y%m%d-%H%M%S')
    command = build_command(unit, args.candidates, args.baselines, args.out, args.until,
                            args.budget_usd, args.fee_reserve_usd, cutoff, now)
    summary = {'unit': unit, 'command': command, 'ready': str(args.out/'ready.json'),
               'latest': str(args.out/'latest.json'),
               'review_card': str(args.out/'review_card.json'), 'check_only': args.check_only}
    if args.check_only:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0
    subprocess.run(command, check=True)
    summary['readiness'] = wait_ready(unit, args.out/'ready.json', args.startup_timeout)
    (args.out/'service.json').write_text(json.dumps({'unit': unit, 'cutoff': cutoff.isoformat()}) + '\n')
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
