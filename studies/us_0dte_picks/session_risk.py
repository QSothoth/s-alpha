"""Read-only loss budget for shared handoffs; fees are explicit user estimates."""
from contextlib import closing
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path
import sqlite3

from custody.models import ET, instant


def _money(value, name, *, positive=False):
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError('invalid ' + name) from None
    if not result.is_finite() or result < 0 or (positive and not result):
        raise ValueError('invalid ' + name)
    return result


def validate_risk_budget(config, now):
    if config is None:
        return None
    if not isinstance(config, dict):
        raise ValueError('risk_budget must be an object')
    try:
        start = date.fromisoformat(config['start_date'])
        if start.isoformat() != config['start_date'] or start > now.astimezone(ET).date():
            raise ValueError('loss budget start_date must be an explicit past or current ISO date')
        _money(config['loss_limit_usd'], 'loss_limit_usd', positive=True)
        _money(config['estimated_round_trip_fee_per_contract_usd'], 'estimated fees')
    except (KeyError, TypeError) as exc:
        raise ValueError('risk budget requires start_date, loss_limit_usd and estimated fees') from exc
    return config


def _closed_result(db_path, entry, day, mode, account):
    """Return (gross P&L, filled quantity, close date) or None for full-cap exposure."""
    if not db_path.exists():
        if entry.get('job_id'):
            raise ValueError('risk budget: recorded job database is missing')
        return None
    with closing(sqlite3.connect(db_path.resolve().as_uri() + '?mode=ro', uri=True)) as db:
        db.execute('BEGIN')  # One consistent job/order snapshot while custody updates.
        rows = db.execute('SELECT id, body FROM jobs WHERE account=? AND contract=? AND day=? LIMIT 2',
                          (account, entry['contract'], day)).fetchall()
        if not rows:
            if entry.get('job_id'):
                raise ValueError('risk budget: recorded job is missing')
            return None
        if len(rows) != 1 or (entry.get('job_id') and entry['job_id'] != rows[0][0]):
            raise ValueError('risk budget: ambiguous job')
        job_id, body = rows[0]
        job = json.loads(body)
        if (job['id'] != job_id or job['mode'] != mode
                or job['request']['contract'] != entry['contract'] or job['request']['trade_date'] != day):
            raise ValueError('risk budget: job scope mismatch')
        if job['state'] == 'TRANSFERRED' or job.get('adopted_position'):
            raise ValueError('risk budget: transferred holdings need independent reconciliation')
        if job['state'] != 'DONE' or job['position_qty'] != 0:
            return None
        quantities = {'BUY_OPEN': 0, 'SELL_CLOSE': 0}
        values = {'BUY_OPEN': Decimal(0), 'SELL_CLOSE': Decimal(0)}
        closed = day
        for row in db.execute('SELECT body FROM orders WHERE job_id=?', (job_id,)):
            order = json.loads(row[0])
            # Cancel acknowledgments carry no fills; reconcile the original orders.
            if order['kind'] == 'CANCEL':
                continue
            if order['status'] not in ('FILLED', 'CANCELED', 'REJECTED'):
                return None
            qty, side = order['cumulative_qty'], order['side']
            if type(qty) is not int or qty < 0 or side not in quantities:
                raise ValueError('risk budget: invalid recorded fill')
            quantities[side] += qty
            if qty:
                values[side] += _money(order['average_option_price'], 'fill price', positive=True) * qty
                if side == 'SELL_CLOSE':
                    update = json.loads(order['last_update'])
                    closed = max(closed, instant(update['as_of']).astimezone(ET).date().isoformat())
        qty = quantities['BUY_OPEN']
        if qty != quantities['SELL_CLOSE'] or qty > 1 or (not qty and job.get('entry_at') is not None):
            raise ValueError('risk budget: completed position does not reconcile')
        if job.get('attention') and (qty or job['attention'] not in (
                'ENTRY_NOT_FILLED', 'NO_ENTRY_SIGNAL', 'ENTRY_REVIEW_EXPIRED')):
            return None
        multiplier = job['contract']['multiplier']
        if type(multiplier) is not int or multiplier <= 0:
            raise ValueError('risk budget: invalid contract multiplier')
        return (values['SELL_CLOSE'] - values['BUY_OPEN']) * multiplier, qty, closed


def check_risk_budget(runtime_root, permission, proposed_premium='0', now=None):
    """Check under the handoff lock before reserving; outside-account trades are unknown.

    Budget use is max(0, -sum(closed estimated net P&L since start)) plus full
    outstanding premium caps and estimated fees, plus the proposed cap and fees.
    Older unresolved handoffs still consume budget, even before the start date.
    """
    now = now or datetime.now(ET)
    config = validate_risk_budget(permission.get('risk_budget'), now)
    if config is None:
        return None
    fee = _money(config['estimated_round_trip_fee_per_contract_usd'], 'estimated fees')
    limit = _money(config['loss_limit_usd'], 'loss_limit_usd', positive=True)
    proposed = _money(proposed_premium, 'proposed premium')
    mode, acc_id, firm = (permission[k] for k in ('mode', 'acc_id', 'security_firm'))
    if mode not in ('dryrun', 'paper', 'live') or (mode == 'dryrun' and acc_id is not None):
        raise ValueError('risk budget: invalid mode/account')
    if mode != 'dryrun' and (type(acc_id) is not int or acc_id <= 0):
        raise ValueError('risk budget: explicit account required')
    account = 'opend-dryrun' if mode == 'dryrun' else str(acc_id)
    net, exposure, counted = Decimal(0), Decimal(0), 0
    root = Path(runtime_root)
    try:
        # Daily ledgers have at most two handoffs; stream directories and orders.
        for folder in root.iterdir() if root.exists() else ():
            try:
                day = date.fromisoformat(folder.name).isoformat()
            except ValueError:
                continue
            if day > now.astimezone(ET).date().isoformat():
                continue
            runtime = folder / mode
            path = runtime / 'ledger.json'
            if not path.exists():
                if (runtime / 'custody.sqlite').exists():
                    raise ValueError('risk budget: custody database without handoff ledger')
                continue
            if path.stat().st_size > 1_048_576:
                raise ValueError('risk budget: oversized handoff ledger')
            entries = json.loads(path.read_text(encoding='utf-8'))['accepted']
            if not isinstance(entries, list) or len(entries) > 2:
                raise ValueError('risk budget: invalid handoff ledger')
            for entry in entries:
                if 'account' not in entry or 'security_firm' not in entry:
                    raise ValueError('risk budget: handoff account scope is missing')
                if ((mode == 'dryrun' and entry['account'] is not None)
                        or (mode != 'dryrun' and (type(entry['account']) is not int or entry['account'] <= 0))
                        or not isinstance(entry['security_firm'], str) or not entry['security_firm']):
                    raise ValueError('risk budget: invalid handoff account scope')
                if (entry['account'], entry['security_firm']) != (acc_id, firm):
                    continue
                cap = _money(entry['cap'], 'reserved premium', positive=True)
                result = _closed_result(runtime / 'custody.sqlite', entry, day, mode, account)
                if result is None:
                    exposure += cap + fee
                elif result[2] > now.astimezone(ET).date().isoformat():
                    raise ValueError('risk budget: future close date')
                elif result[2] >= config['start_date']:
                    gross, qty, _ = result
                    net += gross - qty * fee
                    counted += 1
    except (OSError, sqlite3.Error, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError('risk budget: incomplete or unreadable handoff records: ' + str(exc)) from exc
    loss = max(Decimal(0), -net)
    required = proposed + fee if proposed else Decimal(0)
    remaining = limit - loss - exposure
    report = {'start_date': config['start_date'], 'mode': mode, 'acc_id': acc_id,
              'security_firm': firm, 'loss_limit_usd': str(limit),
              'estimated_realized_net_pnl_usd': str(net), 'realized_loss_usd': str(loss),
              'reserved_exposure_usd': str(exposure), 'remaining_budget_usd': str(remaining),
              'proposed_exposure_usd': str(required), 'closed_jobs': counted,
              'fees': 'USER_ESTIMATE', 'coverage': 'shared handoff records only; external trades unknown'}
    if remaining < required or (proposed and remaining <= 0):
        raise ValueError('risk budget exhausted: ' + json.dumps(report, sort_keys=True))
    return report
