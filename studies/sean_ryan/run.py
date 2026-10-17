"""Run frozen daily research candidates; see Chinese scope and source map."""
import argparse,json,datetime,hashlib,subprocess
from pathlib import Path
from studies.sean_ryan.daily_engine import load,run
from .strategy import signal

def main():
    p=argparse.ArgumentParser();p.add_argument('--data',required=True);p.add_argument('--out');args=p.parse_args()
    here=Path(__file__).parent;out=Path(args.out) if args.out else here/'reports';out.mkdir(parents=True,exist_ok=True)
    cfg=json.loads((here/'notes/preregistered.json').read_text());start=datetime.datetime.now(datetime.timezone.utc).isoformat()
    bars,actions,audit=load(args.data,cfg['symbols'])
    audit['universe_metadata'].pop('stocks',None)
    (out/'data_audit.json').write_text(json.dumps(audit,indent=2))
    results=[]
    if not bars:
        results.append({'status':'BLOCKED_MISSING_REQUIRED_DAILY_PRICES','candidate':None})
    else:
        for candidate in cfg['candidates']:
            results.append(run(bars,actions,signal,cfg,candidate,out/candidate))
    (out/'results.json').write_text(json.dumps(results,indent=2))
    files=list(here.glob('*.py'))+[here/'notes/PREREG_CN.md',here/'notes/preregistered.json',Path('studies/sean_ryan/daily_engine.py')]
    manifest={'started_utc':start,'finished_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'command':'python -m studies.sean_ryan.run --data '+args.data,'exit_code':0,'base_commit':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),'source_sha256':{str(x):hashlib.sha256(x.read_bytes()).hexdigest() for x in files},'uncommitted_source_fingerprints_authoritative':True}
    (out/'run_manifest.json').write_text(json.dumps(manifest,indent=2));print(json.dumps(results,indent=2))
if __name__=='__main__':main()
