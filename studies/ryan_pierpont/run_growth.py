"""Second round: immutable long-base technical condition plus PIT earnings gates."""
import argparse,json,hashlib,datetime
from pathlib import Path
from studies.sean_ryan.daily_engine import load,run
from .strategy import signal
from .fundamentals import SnapshotGate

def main():
 p=argparse.ArgumentParser();p.add_argument('--data',required=True);p.add_argument('--fundamentals',required=True);a=p.parse_args();here=Path(__file__).parent;cfg=json.loads((here/'notes/preregistered.json').read_text());gate=SnapshotGate(a.fundamentals);bars,actions,audit=load(a.data,cfg['symbols']);out=here/'reports/growth_round2';out.mkdir(exist_ok=True);results=[]
 for cand,both in [('P5_base63_revenue25',False),('P6_base63_revenue_netincome25',True)]:
  def gated(s,h,state,pos,unused,d):
   entry,exit,event=signal(s,h,state,pos,'P1_base63',d)
   # Source workflow: technique first, fundamentals next at weekly freeze, not hindsight at breakout.
   if event and event.get('event')=='weekend_watchlist':
    g=gate.evaluate(s,d,both);event.update(fundamental_status=g['status'],snapshot_available=g['snapshot'],fundamental_metrics=json.dumps(g.get('metrics',{})))
    state['growth_selected']=g['pass'];event['selected_with_growth']=state['selected'] and g['pass']
   if entry is not None and not state.get('growth_selected',False):entry=None
   return entry,exit,event
  results.append(run(bars,actions,gated,cfg,cand,out/cand))
 (out/'results.json').write_text(json.dumps(results,indent=2));(out/'manifest.json').write_text(json.dumps({'run_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'fundamental_sha256':hashlib.sha256(Path(a.fundamentals).read_bytes()).hexdigest(),'price_files':audit['files'],'source_sha256':{str(f):hashlib.sha256(f.read_bytes()).hexdigest() for f in [Path(__file__),here/'fundamentals.py',here/'strategy.py',Path('studies/sean_ryan/daily_engine.py')]},'command':'python -m studies.ryan_pierpont.run_growth --data '+a.data+' --fundamentals '+a.fundamentals,'exit_code':0,'oos':False},indent=2));print(json.dumps(results,indent=2))
if __name__=='__main__':main()
