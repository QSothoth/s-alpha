"""Offline minute replay, with deliberately limited execution realism."""
import argparse
import csv
import gzip
import hashlib
import json
from pathlib import Path
from datetime import datetime, timedelta
from collections import defaultdict
from itertools import groupby
from rules import Bar, aggregate, features, setups, entry_path


def read(path):
    result = defaultdict(list)
    with gzip.open(path, 'rt') as f:
        for r in csv.DictReader(f):
            # Source minute labels are bar CLOSE in NY wall time.
            t = datetime.fromisoformat(r['datetime_et']) - timedelta(minutes=1)
            result[r.get('code', r.get('symbol'))].append(Bar(t, *[float(r[k]) for k in ('open','high','low','close','volume')]))
    return {s:sorted(bs,key=lambda b:b.t) for s,bs in result.items()}


def run(data, variant, bps, bar_minutes=1, participation=.01, prepared=None):
    cache_key=(id(data),variant,bar_minutes)
    if prepared is not None and cache_key in prepared:
        signals,decisions,tape=prepared[cache_key]
    else:
        signals, decisions, tape = defaultdict(list), {}, []
        for symbol, minutes in sorted(data.items()):
            bars = aggregate(minutes) if bar_minutes == 1 else [Bar(b.t+timedelta(minutes=5),b.o,b.h,b.l,b.c,b.v) for b in minutes if (9,30)<=(b.t.hour,b.t.minute)<(16,0)]
            for b, f in zip(bars, features(bars)):
                decisions[symbol,b.t] = b.c < f[0]
            for setup in setups(bars, variant):
                signals[datetime.fromisoformat(setup['signal_at'])].append(dict(setup,symbol=symbol))
            tape.extend((b.t,symbol,b) for b in minutes if (9,30) <= (b.t.hour,b.t.minute) < (16,0))
        tape.sort(key=lambda x:(x[0],x[1]))
        if prepared is not None:
            prepared[cache_key]=(signals,decisions,tape)
    cash, positions, pending, marks, losses, ledger, trades, nav = 100000., {}, {}, {}, defaultdict(float), [], [], []
    def close(symbol, b, price, reason):
        nonlocal cash
        p = positions.pop(symbol)
        fill = price*(1-bps/10000)
        fee = p['qty']*.005
        cash += p['qty']*fill-fee
        pnl = p['qty']*(fill-p['entry'])-fee-p['entry_fee']
        losses[b.t.date()] += max(0,-pnl)
        exit_unknown=reason in ('stop','ambiguous_adverse_stop')
        exit_upper=(b.t+timedelta(minutes=bar_minutes)).isoformat() if exit_unknown else b.t.isoformat()
        tr = dict(p,exit_time_lower=b.t.isoformat(),exit_time_upper=exit_upper,exit_intrabar_timestamp_unknown=exit_unknown,exit_at=b.t.isoformat(),exit=fill,exit_raw=price,exit_reason=reason,pnl=pnl,gross_pnl=p['qty']*(price-p['entry_raw']),exit_fee=fee)
        trades.append(tr)
        ledger.append(dict(event='sell',symbol=symbol,at=b.t.isoformat(),fill_time_lower=b.t.isoformat(),fill_time_upper=exit_upper,intrabar_timestamp_unknown=exit_unknown,qty=p['qty'],price=fill,fee=fee,reason=reason,setup_id=p['setup_id']))
    previous_date=None
    for t, group in groupby(tape,key=lambda x:x[0]):
        batch=list(group)
        # Simultaneous open marks are known at interval start. No later symbol
        # can see an earlier symbol's future close or spend its intrabar sale.
        open_marks=dict(marks)
        open_marks.update({symbol:bar.o for _,symbol,bar in batch})
        frozen_equity=cash+sum(p['qty']*open_marks[k] for k,p in positions.items())
        frozen_cash_budget=cash
        frozen_daily_loss=losses[t.date()]
        held_at_open=set(positions)
        # Reserve all contemporaneous intended orders before observing any
        # interval high/low/volume. Unfilled orders release only next interval.
        candidates=dict(pending)
        if frozen_daily_loss<300:
            candidates.update({x['symbol']:x for x in signals.get(t,[]) if x['symbol'] not in held_at_open})
        reservations={}
        current_bars={symbol:bar for _,symbol,bar in batch}
        for symbol, order in sorted(candidates.items()):
            if symbol in held_at_open or frozen_daily_loss>=300 or t>=datetime.fromisoformat(order['expiry']):
                continue
            opening=current_bars[symbol].o if symbol in current_bars else order['trigger']
            if opening<=order['stop'] or opening>order['trigger']+.25*(order['trigger']-order['stop']):
                continue
            raw=max(opening,order['trigger'])
            planned=raw*(1+bps/10000)
            unit_risk=planned-order['stop']*(1-bps/10000)+.01
            quantity=int(min(.001*frozen_equity/unit_risk,.05*frozen_equity/planned,order['volume_cap']*participation/.01,frozen_cash_budget/(planned+.005)))
            reservations[symbol]=quantity
            frozen_cash_budget-=quantity*(planned+.005)
        for _,s,b in batch:
            if previous_date is not None and t.date()!=previous_date:
                nav.append({'date':str(previous_date),'equity':cash+sum(p['qty']*marks[k] for k,p in positions.items()),'cash':cash,'positions':len(positions)})
            previous_date=t.date()
            marks[s]=b.o
            if b.v <= 0:
                # Orders formed from the previous completed bar still exist;
                # lack of a trade prevents execution, not signal publication.
                if s not in held_at_open:
                    for sig in signals.get(t,[]):
                        if sig['symbol']==s:
                            if frozen_daily_loss>=300:
                                ledger.append(dict(sig,event='daily_loss_gate',at=t.isoformat()))
                            else:
                                pending[s]=sig
                                ledger.append(dict(sig,event='order_created',at=t.isoformat(),source_rule_id='C1_BULL_FLAG',hypothesis_id=variant))
                if s in positions and (decisions.get((s,t),False) or (t.hour,t.minute)>=(15,55)):
                    positions[s]['exit_pending']=True
                if s in positions or s in pending or any(x['symbol']==s for x in signals.get(t,[])):
                    ledger.append(dict(event='no_eligible_volume',symbol=s,at=t.isoformat()))
                marks[s]=b.c
                continue
            if s in positions:
                p=positions[s]
                if b.o <= p['stop']:
                    close(s,b,b.o,'stop_gap')
                elif p.get('exit_pending') or decisions.get((s,t),False) or (t.hour,t.minute)>=(15,55):
                    close(s,b,b.o,'completed_bar_or_session_exit')
                elif b.l <= p['stop']:
                    close(s,b,p['stop'],'stop')
            # Signal bar ends at t. First available print is t; no retrospective bar-close fill.
            if s in positions and (decisions.get((s,t),False) or (t.hour,t.minute)>=(15,55)):
                close(s,b,b.o,'completed_bar_or_session_exit')
            if s not in positions and s not in held_at_open:
                for sig in signals.get(t,[]):
                    if sig['symbol']==s:
                        if frozen_daily_loss>=300:
                            ledger.append(dict(sig,event='daily_loss_gate',at=t.isoformat()))
                        else:
                            pending[s]=sig
                            ledger.append(dict(sig,event='order_created',at=t.isoformat(),source_rule_id='C1_BULL_FLAG',hypothesis_id=variant))
            if s in pending and s not in positions:
                p=pending[s]
                if t >= datetime.fromisoformat(p['expiry']):
                    ledger.append(dict(p,event='expired',at=t.isoformat())); del pending[s]
                else:
                    status, price=entry_path(b,p['trigger'],p['stop'])
                    if status in ('gap_cancel','invalidated'):
                        ledger.append(dict(p,event=status,at=t.isoformat())); del pending[s]
                    elif price is not None:
                        equity=frozen_equity
                        fill=price*(1+bps/10000)
                        loss_per_share=fill-p['stop']*(1-bps/10000)+.01
                        qty=reservations.get(s,0)
                        del pending[s]
                        if qty:
                            fee=qty*.005; cash-=qty*fill+fee
                            entry_unknown=b.o<p['trigger']
                            entry_upper=(t+timedelta(minutes=bar_minutes)).isoformat() if entry_unknown else t.isoformat()
                            positions[s]=dict(p,entry_time_lower=t.isoformat(),entry_time_upper=entry_upper,entry_intrabar_timestamp_unknown=entry_unknown,entry_at=t.isoformat(),entry=fill,entry_raw=price,entry_fee=fee,qty=qty,ambiguous=status=='ambiguous_entry_stop')
                            ledger.append(dict(event=status,symbol=s,at=t.isoformat(),fill_time_lower=t.isoformat(),fill_time_upper=entry_upper,intrabar_timestamp_unknown=entry_unknown,qty=qty,price=fill,fee=fee,setup_id=p['setup_id']))
                            if status=='ambiguous_entry_stop': close(s,b,min(b.o,p['stop']),'ambiguous_adverse_stop')
            marks[s]=b.c
    if previous_date:
        nav.append({'date':str(previous_date),'equity':cash+sum(p['qty']*marks[k] for k,p in positions.items()),'cash':cash,'positions':len(positions)})
    equity=nav[-1]['equity'] if nav else cash
    peak=100000.; dd=0
    for n in nav:
        peak=max(peak,n['equity']); dd=min(dd,n['equity']/peak-1)
    flow_cash=100000.+sum((1 if e['event']=='sell' else -1)*e['qty']*e['price']-e['fee'] for e in ledger if e['event'] in ('sell','entry','ambiguous_entry_stop'))
    realized=sum(x['pnl'] for x in trades)
    unrealized=sum(p['qty']*(marks[k]-p['entry'])-p['entry_fee'] for k,p in positions.items())
    summary={'participation_fraction':participation,'ledger_cash':flow_cash,'pnl_reconciliation_error':equity-100000.-realized-unrealized,'variant':variant,'one_way_price_offset_bps':bps,'signal_count':sum(map(len,signals.values())),'closed_trades':len(trades),'win_rate':sum(t['pnl']>0 for t in trades)/len(trades) if trades else None,'gross_realized_pnl':sum(t['gross_pnl'] for t in trades),'scenario_realized_pnl':sum(t['pnl'] for t in trades),'scenario_equity':equity,'scenario_return':equity/100000-1,'max_daily_drawdown':dd,'open_positions':len(positions),'ambiguous_trades':sum(t['ambiguous'] for t in trades),'cash_reconciliation_error':cash-flow_cash,'periods':{label:{'trades':len(ts),'scenario_pnl':sum(t['pnl'] for t in ts)} for label,ts in [('before_2026_07_01',[t for t in trades if t['entry_at']<'2026-07-01']),('from_2026_07_01',[t for t in trades if t['entry_at']>='2026-07-01'])]}}
    return summary,ledger,trades,nav


def write_csv(path, rows):
    keys=sorted(set().union(*(r.keys() for r in rows))) if rows else ['empty']
    with open(path,'w') as f:
        w=csv.DictWriter(f,keys);w.writeheader();w.writerows(rows)


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--data',required=True);ap.add_argument('--out',default=str(Path(__file__).parent/'reports'));args=ap.parse_args()
    out=Path(args.out);out.mkdir(exist_ok=True,parents=True)
    data=read(args.data)
    audit={'source_path':args.data,'sha256':hashlib.sha256(Path(args.data).read_bytes()).hexdigest(),'rows':{s:len(bs) for s,bs in data.items()},'range':{s:[bs[0].t.isoformat(),bs[-1].t.isoformat()] for s,bs in data.items()},'symbols':sorted(data),'missing_float':True,'domain_mismatch':True,'qfq_not_raw_inventory':True}
    results=[]
    for variant in ('strict','nofloat','domain','noquiet','noema'):
        for bps in (10,25):
            summary,ledger,trades,nav=run(data,variant,bps);results.append(summary)
            prefix=f'{variant}_{bps}'
            write_csv(out/f'{prefix}_ledger.csv',ledger);write_csv(out/f'{prefix}_trades.csv',trades);write_csv(out/f'{prefix}_nav.csv',nav)
    (out/'data_audit.json').write_text(json.dumps(audit,indent=2))
    (out/'results.json').write_text(json.dumps(results,indent=2))
    print(json.dumps(results,indent=2))
if __name__=='__main__':main()
