"""Deterministic descriptive diagnostics; no selection, no optimized parameters."""
import csv,json,datetime,collections,statistics
from pathlib import Path

def make(folder):
 folder=Path(folder);allres=[]
 for rp in sorted(folder.rglob('results.json')):
  if not (rp.parent/'trades.csv').exists():continue
  r=json.loads(rp.read_text());ts=list(csv.DictReader((rp.parent/'trades.csv').open()));nav=list(csv.DictReader((rp.parent/'nav.csv').open()));ev=list(csv.DictReader((rp.parent/'events.csv').open()))
  periods={};previous=100000
  for y in sorted({x['date'][:4] for x in nav}):
   xs=[x for x in nav if x['date'][:4]==y];start=previous;end=float(xs[-1]['equity']);peak=start;dd=0
   for x in xs:peak=max(peak,float(x['equity']));dd=min(dd,float(x['equity'])/peak-1)
   periods[y]={'return':end/start-1,'max_drawdown':dd,'mean_exposure':sum(float(x['market_value'])/float(x['equity']) for x in xs)/len(xs)};previous=end
  losing=longest=0
  for t in ts:
   losing=losing+1 if float(t['pnl'])<0 else 0;longest=max(longest,losing)
  holds=[(datetime.date.fromisoformat(t['exit_date'])-datetime.date.fromisoformat(t['entry_date'])).days for t in ts]
  quarters=collections.Counter(t['entry_date'][:4]+'Q'+str((int(t['entry_date'][5:7])-1)//3+1) for t in ts)
  selected=collections.Counter();fund=collections.Counter()
  for e in ev:
   if e['event']=='weekend_watchlist':selected[str(e.get('selected'))]+=1
   if e.get('fundamental_status'):fund[e['fundamental_status']]+=1
  diag={'evidence_scope':'factor-unit H price-path diagnostics; not verified actual historical shares/cash or original trader returns; reused and survivor-selected sample, not OOS','candidate':r['candidate'],'calendar_periods':periods,'longest_losing_streak':longest,'holding_calendar_days':{'median':statistics.median(holds) if holds else None,'max':max(holds) if holds else None},'quarter_entry_counts':dict(quarters),'gap_stop_count':sum(t['reason']=='gap_stop' for t in ts),'realized_loss_below_minus1R':sum(float(t['realized_r'])< -1 for t in ts),'terminal_liquidation_count':sum(t['reason']=='terminal_mark_liquidation' for t in ts),'terminal_liquidation_pnl':sum(float(t['pnl']) for t in ts if t['reason']=='terminal_mark_liquidation'),'weekend_technical_counts':dict(selected),'fundamental_gate_counts':dict(fund),'worst_five_trades':sorted(ts,key=lambda x:float(x['pnl']))[:5],'best_five_trades':sorted(ts,key=lambda x:float(x['pnl']),reverse=True)[:5],'top_trade_removal_warning':'arithmetical PnL sensitivity only; no capital/selection rerun, not counterfactual portfolio'}
  (rp.parent/'diagnostics.json').write_text(json.dumps(diag,indent=2));allres.append(diag)
 (folder/'diagnostics_summary.json').write_text(json.dumps(allres,indent=2))
if __name__=='__main__':
 import sys
 for f in sys.argv[1:]:make(f)
