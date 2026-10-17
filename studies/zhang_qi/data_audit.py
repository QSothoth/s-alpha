"""Enumerate actual local product identifiers without inferring ETF from index names."""
import argparse,csv,gzip,hashlib,json
from pathlib import Path

def main():
    p=argparse.ArgumentParser();p.add_argument('--data-root',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    inventories=[]; candidates=set()
    for path in sorted(a.data_root.rglob('bars*.csv.gz')):
        codes=set(); count=0
        with gzip.open(path,'rt') as f:
            for row in csv.DictReader(f):
                count+=1;code=row.get('code','');codes.add(code)
                # Mainland exchange ETF code families. A prefix candidate is not verified eligibility.
                if code.startswith(('SH.51','SH.56','SH.58','SZ.15')):candidates.add(code)
        h=hashlib.sha256(path.read_bytes()).hexdigest()
        inventories.append({'path':str(path.relative_to(a.data_root)),'rows':count,'codes':len(codes),'sha256':h})
    result={'inventories':inventories,'etf_prefix_candidates':sorted(candidates),'verified_sector_etfs':0,
            'readiness':'E0','replay_performed':False,'blocker':'No verified sector ETF product corpus, historic eligibility, NAV, distributions or sellability metadata'}
    a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k!='inventories'},ensure_ascii=False))
if __name__=='__main__':main()
