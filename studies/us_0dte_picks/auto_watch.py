"""Finite automatic card handoff under one persisted, explicit daily authorization.

No order API: all handoffs reuse session.accept; custody continues managing its jobs after
this coordinator expires, is revoked, or fails. This command never changes its authority.
"""
from __future__ import annotations

import argparse
from datetime import datetime
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import time

from custody.models import ET, instant
from .live_watch import write_json_atomic
from .session import (RUNTIME, RejectedEntryQuote, StaleReviewCard, accept, authorized_action,
                      selected_action, validate_authorization)


def load_authorization(folder, now):
    permission = json.loads((folder/'authorization.json').read_text())
    validate_authorization(permission, now)
    if permission.get('session') != str(folder.resolve()) or permission.get('ranking_sha256') != hashlib.sha256(
            (folder/'ranking.json').read_bytes()).hexdigest():
        raise ValueError('authorization is bound to a different session or frozen candidate file')
    ready = json.loads((folder/'monitor/ready.json').read_text())
    if ready.get('trade_date') != permission['trade_date'] or set(ready.get('candidates', [])) != set(permission['symbols']):
        raise ValueError('ready monitor must scan exactly the authorized symbols')
    return permission


def handoff_card(folder, permission, raw, attempted, now):
    """Only matching, fresh actions may use the fixed mode/account/action permission."""
    validate_authorization(permission, now)
    card = json.loads(raw)
    if card.get('status') != 'ENTER_REVIEW':
        return
    if not instant(card['as_of']) <= now < instant(card['valid_until']):
        return
    ledger_path = RUNTIME/permission['trade_date']/permission['mode']/'ledger.json'
    rows = json.loads(ledger_path.read_text()).get('accepted', []) if ledger_path.exists() else []
    if any(row.get('state') != 'JOB_CREATED' for row in rows):
        raise ValueError('unconfirmed existing reservation; reconcile the original custody job before new handoffs')
    reserved = {row['symbol'] for row in rows}
    used = sum((Decimal(str(row['cap'])) for row in rows), Decimal(0))
    digest = hashlib.sha256(raw).hexdigest()[:16]
    for action in card['actions']:
        if action['symbol'] not in permission['symbols']:
            continue
        if action['symbol'] in reserved or len(reserved) >= 2:
            continue
        selected_action(card, action['contract'], now)
        cap = Decimal(str(authorized_action(action, permission)['custody_request']['max_entry_premium']))
        if used + cap > Decimal('280'):
            continue
        key = digest, action['contract']
        if key in attempted:
            continue
        attempted.add(key)
        result = accept(folder, action['contract'], permission['mode'], permission['acc_id'],
                        permission['security_firm'], True, permission['trade_action'], authorization=permission)
        reserved.add(action['symbol'])
        used += cap
        yield result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--session', type=Path, required=True)
    args = parser.parse_args(argv)
    started = datetime.now(ET)
    try:
        permission = load_authorization(args.session, started)
    except (ValueError, OSError, KeyError) as exc:
        parser.error(str(exc))
    out = args.session/'auto'
    out.mkdir(exist_ok=False)
    (out/'source.py').write_bytes(Path(__file__).read_bytes())
    write_json_atomic(out/'ready.json', {'started_at': started.isoformat(), 'authorization': permission,
                                      'role': 'AUTOMATIC_CUSTODY_HANDOFF'})
    latest = {'as_of': started.isoformat(), 'status': 'WAITING_FOR_FRESH_SIGNAL',
              'mode': permission['mode'], 'handoffs': []}
    attempted = set()
    try:
        with (out/'events.jsonl').open('a', buffering=1) as events:
            while datetime.now(ET) < instant(permission['valid_until']):
                now = datetime.now(ET)
                # Any replacement, revocation or disappearance ends new handoffs.
                if load_authorization(args.session, now) != permission:
                    raise ValueError('authorization changed; obtain a new explicit decision')
                card_path = args.session/'monitor/review_card.json'
                handoffs = handoff_card(args.session, permission, card_path.read_bytes(), attempted, now) if card_path.exists() else ()
                try:
                    for handoff in handoffs:
                        latest['handoffs'].append(handoff)
                        latest['status'] = 'HANDOFF_CREATED_CHECK_CUSTODY_FILLS'
                        events.write(json.dumps({'at': now.isoformat(), 'handoff': handoff}, ensure_ascii=False)+'\n')
                except (StaleReviewCard, RejectedEntryQuote) as exc:
                    # No service/reservation was persisted; validate authority again before waiting.
                    current = datetime.now(ET)
                    if current >= instant(permission['valid_until']):
                        break
                    if load_authorization(args.session, current) != permission:
                        raise ValueError('authorization changed; obtain a new explicit decision')
                    field, status = ('last_skipped_quote', 'SKIPPED_ENTRY_QUOTE') if isinstance(
                        exc, RejectedEntryQuote) else ('last_skipped_review', 'SKIPPED_STALE_REVIEW')
                    latest[field] = {'at': current.isoformat(), 'reason': str(exc)}
                    events.write(json.dumps({'status': status, **latest[field]},
                                            ensure_ascii=False)+'\n')
                latest['as_of'] = datetime.now(ET).isoformat()
                write_json_atomic(out/'latest.json', latest)
                time.sleep(2)
            latest['status'] = 'ENTRY_AUTHORIZATION_EXPIRED'
    except Exception as exc:
        # Any malformed input or unexpected coordinator fault ends new handoffs.
        latest.update(status='STOPPED_REQUIRES_REVIEW', error=str(exc))
    finally:
        write_json_atomic(out/'final.json', {**latest, 'as_of': datetime.now(ET).isoformat(),
                         'finished_at': datetime.now(ET).isoformat(),
                         'attempted_card_contracts': sorted(attempted),
                         'note': 'No new entries; existing custody jobs retain their original management and permissions.'})
    return 1 if latest['status'] == 'STOPPED_REQUIRES_REVIEW' else 0


if __name__ == '__main__':
    raise SystemExit(main())
