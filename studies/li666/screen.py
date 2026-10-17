"""Historical nominal-price screen, no invented trading policy."""
import csv,gzip,json,hashlib,argparse
from collections import defaultdict
from pathlib import Path

def eligible(code, nominal_close):
    return code.startswith('SZ.300') and 0 < nominal_close < 10

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--data',required=True);args=ap.parse_args()
    dates=defaultdict(list);rows=0
    with gzip.open(args.data,'rt') as f:
        for r in csv.DictReader(f):
            rows+=1
            if eligible(r['code'],float(r['close'])):dates[r['date']].append(r['code'])
    out=Path(__file__).parent/'reports'
    with (out/'screen_counts.csv').open('w') as f:
        w=csv.writer(f);w.writerow(['date','eligible_count','symbols'])
        for d,ss in sorted(dates.items()):w.writerow([d,len(set(ss)),';'.join(sorted(set(ss)))])
    result={'rows_read':rows,'qualifying_security_days':sum(len(set(v)) for v in dates.values()),'qualifying_symbols':len(set(s for ss in dates.values() for s in ss)),'qualifying_dates':len(dates),'sha256':hashlib.sha256(Path(args.data).read_bytes()).hexdigest(),'path':args.data,'selection_bias':'current-surviving universe, not historical investable universe','returns_computed':False}
    (out/'results.json').write_text(json.dumps(result,indent=2));print(result)
if __name__=='__main__':main()
