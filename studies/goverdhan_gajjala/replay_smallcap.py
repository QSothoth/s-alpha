"""R2 public smallcap-domain five-minute diagnostic, explicitly not minute replay."""
import argparse,csv,json,hashlib
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
from rules import Bar
from replay import run,write_csv

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--data',required=True);args=ap.parse_args()
    data={};audit=[]
    for path in sorted(Path(args.data).glob('*_5m.csv')):
        bs=[]
        with path.open() as f:
            for r in csv.DictReader(f):
                t=datetime.fromisoformat(r['Datetime']).astimezone(ZoneInfo('America/New_York'))
                bs.append(Bar(t,*[float(r[k]) for k in ('Open','High','Low','Close','Volume')]))
        symbol=path.name.removesuffix('_5m.csv');data[symbol]=sorted(bs,key=lambda b:b.t)
        audit.append({'symbol':symbol,'rows':len(bs),'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'source':str(path)})
    out=Path(__file__).parent/'reports/r2';out.mkdir(exist_ok=True)
    results=[]
    for variant in ('strict','nofloat','nofloat_noquiet','nofloat_noema'):
        for bps in (10,25):
            result,ledger,trades,nav=run(data,variant,bps,bar_minutes=5)
            result.update(bar_resolution_minutes=5,minute_path_verified=False,readiness='E2-limited-conditional',survivor_and_download_subset_bias=True)
            results.append(result);prefix=f'{variant}_{bps}'
            write_csv(out/f'{prefix}_ledger.csv',ledger);write_csv(out/f'{prefix}_trades.csv',trades);write_csv(out/f'{prefix}_nav.csv',nav)
    (out/'results.json').write_text(json.dumps(results,indent=2));(out/'data_audit.json').write_text(json.dumps(audit,indent=2));print(json.dumps(results,indent=2))
if __name__=='__main__':main()
