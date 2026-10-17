"""Separate long-horizon growth sleeve; never substitutes ETF-only for whole method."""
import argparse,json,hashlib,datetime
from pathlib import Path
from studies.sean_ryan.daily_engine import load,run,mean
from studies.ryan_pierpont.fundamentals import SnapshotGate

def main():
 p=argparse.ArgumentParser();p.add_argument('--data',required=True);p.add_argument('--fundamentals',required=True);a=p.parse_args();here=Path(__file__).parent
 cfg=json.loads((here/'notes/growth_preregistered.json').read_text());bars,actions,audit=load(a.data,cfg['symbols']);gate=SnapshotGate(a.fundamentals);out=here/'reports/growth_round2';out.mkdir(exist_ok=True);results=[]
 for cand in cfg['candidates']:
  def growth(s,h,state,pos,unused,d):
   if len(h)<127:return None,None,None
   c=h[-1]['close'];ma=mean([x['close'] for x in h[-50:]]);base=h[-64:-1];high=max(x['high'] for x in base);low=min(x['low'] for x in base)
   early_base=(.08<=1-low/high<=.35 and max(x['high'] for x in base[:21])>=.9*high)
   trigger=early_base and c>high
   g=gate.evaluate(s,d,True);event=None
   if trigger:event={'event':'growth_breakout','fundamental_status':g['status'],'snapshot_available':g['snapshot'],'fundamental_metrics':json.dumps(g.get('metrics',{})),'RS_gate':'NOT_AVAILABLE_MARKET_BENCHMARK'}
   allowed=trigger and (cand=='G1_technical_control' or g['pass'])
   return c*.85 if allowed else None,('growth_ma50_failure' if pos and c<ma else None),event
  results.append(run(bars,actions,growth,cfg,cand,out/cand))
 (out/'results.json').write_text(json.dumps(results,indent=2));(out/'manifest.json').write_text(json.dumps({'run_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'fundamental_sha256':hashlib.sha256(Path(a.fundamentals).read_bytes()).hexdigest(),'price_files':audit['files'],'source_sha256':{str(f):hashlib.sha256(f.read_bytes()).hexdigest() for f in [Path(__file__),Path('studies/sean_ryan/daily_engine.py'),Path('studies/ryan_pierpont/fundamentals.py'),here/'notes/GROWTH_ROUND2_CN.md']},'config_sha256':hashlib.sha256((here/'notes/growth_preregistered.json').read_bytes()).hexdigest(),'command':'python -m studies.vibha_jha.growth --data '+a.data+' --fundamentals '+a.fundamentals,'exit_code':0,'oos':False,'rotation':'BLOCKED_NONOVERLAPPING_ETF_LONG_HISTORY','RS_gate':'BLOCKED_NO_MARKET_BENCHMARK_2023_2026'},indent=2));print(json.dumps(results,indent=2))
if __name__=='__main__':main()
