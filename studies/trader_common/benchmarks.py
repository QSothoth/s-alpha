"""Post-run descriptive baselines only; never used for selecting candidates."""
import argparse,csv,json
from pathlib import Path
import numpy as np
from .data import load_daily,sha256
from .run_minute import read_eval_daily
from .run_swing import ROOT,dump

def main():
 p=argparse.ArgumentParser();p.add_argument('--raw',required=True);p.add_argument('--eval-day',required=True);a=p.parse_args();data=load_daily(a.raw);daily=read_eval_daily(a.eval_day)
 exclusions={r['symbol'] for r in csv.DictReader(open(ROOT/'trader_common/reports/action_exclusions.csv'))}
 usable={s:v for s,v in data.items() if s not in exclusions and len(v['dates'])>252}
 # Fixed equal initial cash allocations; buy on each constituent's first observed bar,
 # otherwise allocation stays in cash. No retroactive allocation to early winners.
 eq=float(np.mean([v['values'][-1,3]/v['values'][0,0]-1 for v in usable.values()]))
 q=daily['US.QQQ'];first=max(min(v['dates'][0] for v in data.values()),q['dates'][0]);last=min(max(v['dates'][-1] for v in data.values()),q['dates'][-1]);ix={d:i for i,d in enumerate(q['dates'])};qq=float(q['values'][ix[last],3]/q['values'][ix[first],0]-1)
 for slug,variants in [('christian_flanders',('FD1','FD0')),('mark_minervini',('MD1','MD0'))]:
  r={'post_run_descriptive_not_selection':True,'source_hashes':{a.raw:sha256(a.raw),a.eval_day:sha256(a.eval_day),__file__:sha256(__file__)},'cash_return':0,'equal_initial_allocations_buy_first_observed_bar':{'symbols':len(usable),'price_return_no_cost':eq,'first_possible':min(v['dates'][0] for v in usable.values()),'last_possible':max(v['dates'][-1] for v in usable.values()),'limitations':'fixed hindsight survivor/actionfree universe; allocation to later listings waits in cash; fractions; no costs/capacity; not strict exposure matched'},'QQQ_common_overlap':{'first':first,'last':last,'qfq_price_return_no_cost':qq,'limitations':'endpoint ends before daily strategies Oct09; QFQ not audited total-return cash accounting'},'strategy_common_overlap':{}}
  for variant in variants:
   nav={n['date']:float(n['equity']) for n in csv.DictReader(open(ROOT/slug/'reports'/(variant+'_nav.csv')))};r['strategy_common_overlap'][variant]=nav[last]/nav[first]-1
  dump(ROOT/slug/'reports'/'benchmarks.json',r)
if __name__=='__main__':main()
