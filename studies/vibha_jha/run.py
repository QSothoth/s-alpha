"""Run frozen daily research candidates; see Chinese scope and source map."""
import argparse,json,datetime,hashlib,subprocess,csv
from pathlib import Path
from studies.sean_ryan.daily_engine import load,run
from .strategy import signal

def main():
    p=argparse.ArgumentParser();p.add_argument('--data',required=True);p.add_argument('--out');args=p.parse_args()
    here=Path(__file__).parent;out=Path(args.out) if args.out else here/'reports';out.mkdir(parents=True,exist_ok=True)
    cfg=json.loads((here/'notes/preregistered.json').read_text());start=datetime.datetime.now(datetime.timezone.utc).isoformat()
    bars={};actions={};fingerprints={}
    for symbol in cfg['symbols']:
        path=Path(args.data)/('xjcarter_'+symbol+'.csv')
        if not path.exists():continue
        bars[symbol]={r['Date']:{'date':r['Date'],**{k:float(r[k.title()]) for k in ('open','high','low','close','volume')}} for r in csv.DictReader(path.open())}
        fingerprints[path.name]=hashlib.sha256(path.read_bytes()).hexdigest()
    audit={'files':fingerprints,'coverage':{s:{'start':min(x),'end':max(x),'bars':len(x)} for s,x in bars.items()},'price_basis':'split-adjusted units; dividends excluded; per-unit fee H; true-share historical net returns blocked','pit':False,'source':'public xjcarter GitHub mirror, source acquisition manifest in trader-data','growth_positions':'BLOCKED_PIT_EARNINGS_UNIVERSE','rotation':'BLOCKED_GROWTH_LINE','oos':False}
    qhist=[];market={}
    for d,b in sorted(bars.get('QQQ',{}).items()):
        qhist.append(b['close'])
        market[d]=len(qhist)>=50 and b['close']>sum(qhist[-50:])/50
    if 'TQQQ' in bars:
        start_date=min(bars['TQQQ'])
        bars={s:{d:b for d,b in x.items() if d>=start_date} for s,x in bars.items()}
    def observed_signal(symbol,h,state,position,candidate,date):
        state['market_recovery']=market.get(date,False)
        return signal(symbol,h,state,position,candidate,date)
    (out/'data_audit.json').write_text(json.dumps(audit,indent=2))
    results=[]
    if not bars:
        results.append({'status':'BLOCKED_MISSING_REQUIRED_DAILY_PRICES','candidate':None})
    else:
        for candidate in cfg['candidates']:
            results.append(run(bars,actions,observed_signal,cfg,candidate,out/candidate))
    (out/'results.json').write_text(json.dumps(results,indent=2))
    files=list(here.glob('*.py'))+[here/'notes/PREREG_CN.md',here/'notes/preregistered.json',Path('studies/sean_ryan/daily_engine.py')]
    manifest={'started_utc':start,'finished_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'command':'python -m studies.vibha_jha.run --data '+args.data,'exit_code':0,'base_commit':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),'source_sha256':{str(x):hashlib.sha256(x.read_bytes()).hexdigest() for x in files},'uncommitted_source_fingerprints_authoritative':True}
    (out/'run_manifest.json').write_text(json.dumps(manifest,indent=2));print(json.dumps(results,indent=2))
if __name__=='__main__':main()
