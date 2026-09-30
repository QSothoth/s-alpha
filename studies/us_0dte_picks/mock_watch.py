"""Finite real-quote observation; auto-accept fresh cards into local dryrun only."""
from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
import math
import os
from pathlib import Path
import sqlite3
import subprocess
import time

from custody.marketdata import _et, _num
from custody.models import ET
from custody.opend import OpenDMarket
from .live_watch import write_json_atomic
from .session import RUNTIME, accept, jobs_in


def mark_job(job, orders, quote, now):
    multiplier = job['contract']['multiplier']
    bought = sum(o['cumulative_qty'] for o in orders if o['side'] == 'BUY_OPEN')
    cost = sum(o['cumulative_qty'] * (o.get('average_option_price') or 0) * multiplier
               for o in orders if o['side'] == 'BUY_OPEN')
    proceeds = sum(o['cumulative_qty'] * (o.get('average_option_price') or 0) * multiplier
                   for o in orders if o['side'] == 'SELL_CLOSE')
    bid, ask, stamp = _num(quote.get('bid_price')), _num(quote.get('ask_price')), _et(quote.get('update_time'))
    fresh = (stamp is not None and 0 <= (now-stamp).total_seconds() <= 30
             and bid is not None and ask is not None and 0 < bid <= ask)
    mark = bid * multiplier if fresh else None
    qty = job['position_qty']
    pnl = proceeds-cost if qty == 0 else proceeds+qty*mark-cost if fresh else None
    return {'job_id':job['id'], 'contract':job['request']['contract'], 'state':job['state'],
            'position_qty':qty, 'entry_reason':job['entry_reason'], 'exit_reason':job['exit_reason'],
            'attention':job['attention'], 'bought_qty':bought, 'simulated_cost_usd':cost,
            'simulated_proceeds_usd':proceeds, 'bid':bid, 'ask':ask, 'quote_time':quote.get('update_time'),
            'fresh_quote':fresh, 'gross_pnl_usd':pnl,
            'gross_return_pct':100*pnl/cost if cost and pnl is not None else None,
            'hold_counterfactual_gross_pnl_usd':bought*mark-cost if fresh and bought else None,
            'fees':'NOT_DEDUCTED', 'orders_submitted':False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--session',type=Path,required=True)
    parser.add_argument('--until',default='16:05')
    args = parser.parse_args(argv)
    started = datetime.now(ET)
    cutoff = datetime.fromisoformat(started.date().isoformat()+'T'+args.until).replace(tzinfo=ET)
    if not started < cutoff <= started.replace(hour=16,minute=10,second=0,microsecond=0):
        parser.error('finite same-day cutoff no later than 16:10 required')
    for key in ('FUTU_TRADE_PASSWORD','FUTU_TRADE_PASSWORD_MD5','CUSTODY_WXPUSHER_SPT'):
        os.environ.pop(key,None)
    out = args.session/'mock'
    out.mkdir(exist_ok=False)
    (out/'source.py').write_bytes(Path(__file__).read_bytes())
    day = started.date().isoformat()
    runtime = RUNTIME/day/'dryrun'
    db = runtime/'custody.sqlite'
    attempted, owned, peaks = set(), set(), {}
    latest = {'status':'WAITING_FOR_FRESH_SIGNAL', 'mode':'dryrun', 'orders_submitted':False, 'positions':[]}
    write_json_atomic(out/'ready.json', {'started_at':started.isoformat(),'until':cutoff.isoformat(),
                                       'mode':'dryrun','orders_submitted':False})
    last_minute = None
    handoff_errors = []
    try:
        with OpenDMarket() as market, (out/'events.jsonl').open('a',buffering=1) as events:
            def record(kind, data):
                events.write(json.dumps({'at':datetime.now(ET).isoformat(),'kind':kind,**data},ensure_ascii=False)+'\n')
            while datetime.now(ET) < cutoff:
                now = datetime.now(ET)
                card_path = args.session/'monitor/review_card.json'
                if now.hour*60+now.minute < 645 and card_path.exists():
                    raw = card_path.read_bytes()
                    card = json.loads(raw)
                    digest = hashlib.sha256(raw).hexdigest()[:16]
                    for action in card.get('actions',[]) if card.get('status')=='ENTER_REVIEW' else []:
                        key = (digest,action['contract'])
                        if key in attempted:
                            continue
                        attempted.add(key)
                        try:
                            result = accept(args.session,action['contract'],'dryrun',None,'FUTUSECURITIES',True)
                            record('mock_handoff',result)
                        except (ValueError,KeyError,OSError,RuntimeError,sqlite3.Error,subprocess.SubprocessError) as exc:
                            failure = {'contract':action['contract'],'error':str(exc)}
                            handoff_errors.append(failure)
                            record('mock_handoff_rejected',failure)
                        finally:
                            ledger_path = runtime/'ledger.json'
                            if ledger_path.exists():
                                ledger = json.loads(ledger_path.read_text())
                                owned.update(r['unit'] for r in ledger['accepted'] if r.get('card_hash')==digest and r.get('unit'))
                minute = now.strftime('%H:%M')
                if minute != last_minute:
                    last_minute = minute
                    ledger_path = runtime/'ledger.json'
                    ledger = json.loads(ledger_path.read_text()) if ledger_path.exists() else {'accepted':[]}
                    contracts = {r['contract'] for r in ledger['accepted'] if r.get('unit') in owned}
                    jobs = [j for j in jobs_in(db) if j['request']['contract'] in contracts]
                    quotes, error = {}, None
                    if contracts:
                        try:
                            quotes = market.snapshot(sorted(contracts))
                        except RuntimeError as exc:
                            error = str(exc)
                    positions = []
                    if jobs:
                        with sqlite3.connect(db.resolve().as_uri()+'?mode=ro',uri=True) as conn:
                            for job in jobs:
                                orders = [json.loads(r[0]) for r in conn.execute('SELECT body FROM orders WHERE job_id=?',(job['id'],))]
                                row = mark_job(job,orders,quotes.get(job['request']['contract'],{}),datetime.now(ET))
                                pnl = row['gross_pnl_usd']
                                if row['bought_qty'] and pnl is not None:
                                    peaks[job['id']] = max(peaks.get(job['id'],-math.inf),pnl)
                                row['peak_observed_gross_pnl_usd'] = peaks.get(job['id'])
                                row['giveback_from_observed_peak_usd'] = peaks[job['id']]-pnl if job['id'] in peaks and pnl is not None else None
                                positions.append(row)
                    latest = {'as_of':datetime.now(ET).isoformat(),'mode':'dryrun','orders_submitted':False,
                              'status':observation_status(positions,handoff_errors,now),
                              'handoff_errors':handoff_errors,
                              'positions':positions,'quote_error':error,'units':sorted(owned)}
                    write_json_atomic(out/'latest.json',latest)
                    record('mark',latest)
                time.sleep(2)
    finally:
        for unit in sorted(owned):
            subprocess.run(['systemctl','stop',unit],check=False,capture_output=True,text=True)
        write_json_atomic(out/'final.json',{**latest,'finished_at':datetime.now(ET).isoformat(),
                         'unfinished_jobs':[r['job_id'] for r in latest['positions'] if r['state']!='DONE'],
                         'note':'Local simulated fills only; stale marks excluded; gross of fees; no profit validation'})
    return 0


def observation_status(positions, errors, now):
    if positions:
        return 'OBSERVING'
    if errors:
        return 'HANDOFF_FAILED'
    return 'NO_ENTRY' if now.hour*60+now.minute >= 645 else 'WAITING_FOR_FRESH_SIGNAL'


if __name__=='__main__':
    raise SystemExit(main())
