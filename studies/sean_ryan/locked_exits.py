"""Conditional exit experiment on frozen S2 fills, not a realizable portfolio return."""
import argparse,csv,json,hashlib,datetime
from pathlib import Path
from .daily_engine import load,rsi

def replay(bars,actions,ticket,variant):
 s=ticket['symbol'];entry=ticket['date'];qty=float(ticket['qty']);fill=float(ticket['fill']);stop=float(ticket['stop']);initial=qty*(fill+.005);risk=qty*(fill-stop);cashdiv=0;history=[];pending=None;entered=False;armed=False
 for date,b in sorted(bars[s].items()):
  for ex,(a,bb) in actions.get(s,{}).items():
   if ex==date:
    for old in history:
     for k in ('open','high','low','close'):old[k]=a*old[k]+bb
    if entered:cashdiv+=qty*(-bb/a);qty/=a;stop=a*stop+bb;fill=a*fill+bb
  if date==entry:entered=True
  px=None;reason=None
  if entered:
   if pending:px=b['open'];reason=pending
   elif b['open']<=stop:px=b['open'];reason='gap_stop'
   elif b['low']<=stop:px=stop;reason='intraday_stop_conservative'
  history.append(dict(b))
  if px is not None:break
  if entered:
   c=b['close']
   if len(history)>=11 and c<min(x['low'] for x in history[-11:-1]):pending='structure_low10'
   if variant=='S4_second_be_rsi' and len(history)>31 and c>=max(x['close'] for x in history[-21:-1]):
    prior=max(range(max(14,len(history)-31),len(history)-5),key=lambda j:history[j]['close'])
    if c>history[prior]['close'] and rsi(history)<rsi(history[:prior+1])-5:pending='H_RSI14_simple_bearish_divergence'
   if variant!='S2_second_wave' and not armed and c>=fill*1.10:stop=max(stop,fill);armed=True
 else:px=history[-1]['close'];reason='terminal_mark_liquidation';date=history[-1]['date']
 pnl=qty*px*.999-qty*.005-initial+cashdiv
 return {'symbol':s,'entry_date':entry,'exit_date':date,'variant':variant,'initial_fill':ticket['fill'],'initial_quantity':ticket['qty'],'initial_risk':risk,'pnl':pnl,'r_multiple':pnl/risk if risk else 0,'reason':reason}

def main():
 p=argparse.ArgumentParser();p.add_argument('--data',required=True);a=p.parse_args();here=Path(__file__).parent;cfg=json.loads((here/'notes/preregistered.json').read_text());bars,actions,_=load(a.data,cfg['symbols'])
 with (here/'reports/S2_second_wave/events.csv').open() as f:tickets=[x for x in csv.DictReader(f) if x['event']=='entry']
 rows=[replay(bars,actions,t,v) for t in tickets for v in ['S2_second_wave','S3_second_be','S4_second_be_rsi']]
 with (here/'reports/locked_exit_tickets.csv').open('w') as f:w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
 summary={v:{'tickets':sum(x['variant']==v for x in rows),'sum_conditional_pnl':sum(x['pnl'] for x in rows if x['variant']==v),'mean_r':sum(x['r_multiple'] for x in rows if x['variant']==v)/len(tickets)} for v in ['S2_second_wave','S3_second_be','S4_second_be_rsi']}
 summary['warning']='Same S2 actual entries, sizes, costs; independent potentially overlapping tickets, not a feasible portfolio/equity return. Post-result attribution audit; no new optimization. Factor-unit corporate adjustment limitations inherited.'
 (here/'reports/locked_exit_summary.json').write_text(json.dumps(summary,indent=2))
 (here/'reports/locked_exit_manifest.json').write_text(json.dumps({'run_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'command':'python -m studies.sean_ryan.locked_exits --data '+a.data,'exit_code':0,'source_sha256':{str(f):hashlib.sha256(f.read_bytes()).hexdigest() for f in [Path(__file__),here/'daily_engine.py',here/'reports/S2_second_wave/events.csv']}},indent=2));print(json.dumps(summary,indent=2))
if __name__=='__main__':main()
