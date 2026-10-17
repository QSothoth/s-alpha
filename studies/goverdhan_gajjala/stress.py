"""All fixed nine execution stress cells, without selecting a winner."""
import csv,json,hashlib,argparse
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
from rules import Bar
from replay import read,run,write_csv

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--minute',default='data/trader-data/opend_us_options_eval_v2/klines_1m.csv.gz')
    ap.add_argument('--smallcap',default='data/trader-data/kaggle-v59')
    args=ap.parse_args()
    minute=read(args.minute)
    small={}
    for p in sorted(Path(args.smallcap).glob('*_5m.csv')):
        with p.open() as f:
            small[p.stem]=[Bar(datetime.fromisoformat(r['Datetime']).astimezone(ZoneInfo('America/New_York')),*[float(r[k]) for k in ('Open','High','Low','Close','Volume')]) for r in csv.DictReader(f)]
    out=Path(__file__).parent/'reports/stress';out.mkdir(exist_ok=True)
    results=[]
    prepared={}
    for label,data,interval,variants in [('r1',minute,1,('strict','nofloat','domain','noquiet','noema')),('r2',small,5,('strict','nofloat','nofloat_noquiet','nofloat_noema'))]:
        for variant in variants:
            for bps in (10,30,100):
                for participation in (.005,.01,.02):
                    result,ledger,trades,nav=run(data,variant,bps,interval,participation,prepared=prepared)
                    result['round']=label;results.append(result)
                    prefix=f'{label}_{variant}_{bps}_{participation}'
                    write_csv(out/f'{prefix}_trades.csv',trades)
                    write_csv(out/f'{prefix}_ledger.csv',ledger)
                    write_csv(out/f'{prefix}_nav.csv',nav)
    (out/'results.json').write_text(json.dumps(results,indent=2))
    print(len(results),'cells complete')
if __name__=='__main__':main()
