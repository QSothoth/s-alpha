"""Actual-input future perturbation: past candidate plans must stay identical."""
import argparse,json,copy
from pathlib import Path
from collections import defaultdict
from .run_minute import read_eval_daily,read_minutes,prepare
from .data import load_daily,sha256
from .run_swing import dump,ROOT

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--eval-data',required=True);ap.add_argument('--raw',required=True);ap.add_argument('--pit',required=True);a=ap.parse_args();root=Path(a.eval_data)
 daily=read_eval_daily(root/'klines_day.csv.gz');raw=load_daily(a.raw);mins=read_minutes(root/'klines_1m.csv.gz');pit=defaultdict(list)
 for line in open(a.pit):
  r=json.loads(line);pit[r['symbol']].append(r)
 for v in pit.values():v.sort(key=lambda r:r['available_on_or_after'])
 base=prepare(daily,raw,mins,pit)[0];cut='2026-07-01';d2=copy.deepcopy(daily);r2=copy.deepcopy(raw);p2=copy.deepcopy(pit)
 for d in d2.values():d['values'][d['dates']>=cut,:4]*=7;d['values'][d['dates']>=cut,4]*=100
 for d in r2.values():d['values'][d['dates']>=cut,:4]*=3;d['values'][d['dates']>=cut,4]*=1000
 for rows in p2.values():
  for row in rows:
   if row['available_on_or_after']>=cut:
    for m in row['metrics'].values():
     if isinstance(m,dict) and m.get('value') is not None:m['value']=-999999999999
 # Truncate minute stream; future data removed entirely, not only modified.
 truncated={d:ss for d,ss in mins.items() if d<cut};changed=prepare(d2,r2,truncated,p2)[0]
 def prefix(x):return {v:{at:ps for at,ps in plan.items() if at[:10]<cut} for v,plan in x.items()}
 lhs=prefix(base);rhs=prefix(changed);checks={v:lhs[v]==rhs[v] for v in lhs}
 report={'cutoff':cut,'all_variants_past_candidates_unchanged':checks,'past_candidate_counts':{v:sum(len(ps) for ps in lhs[v].values()) for v in lhs},'mutations':['future daily prices x7 and volume x100','future raw prices x3 and volume x1000','future SEC facts negative extreme','all future minute bars removed'],'source_sha256':sha256(__file__),'claim':'candidate causality on this observed prefix, not proof of all possible inputs or PIT adjustment basis'}
 dump(ROOT/'trader_common/reports/actual_input_future_mutation.json',report)
 if not all(checks.values()):raise AssertionError('future data changed past plans')
if __name__=='__main__':main()
