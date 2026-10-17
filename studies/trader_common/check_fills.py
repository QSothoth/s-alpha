"""Independent checks against source bars, not merely simulator assertions."""
import argparse,csv,gzip,json,math
from collections import defaultdict
from pathlib import Path
from datetime import datetime,timedelta
from .data import load_daily,sha256
from .run_swing import ROOT,dump

def main():
 p=argparse.ArgumentParser();p.add_argument('--raw',required=True);p.add_argument('--minute',required=True);a=p.parse_args();raw=load_daily(a.raw);lookup={s:{d:raw[s]['values'][i,0] for i,d in enumerate(v['dates'])} for s,v in raw.items()}
 allchecks=[]
 for slug,variants in [('christian_flanders',('FD1','FD0')),('mark_minervini',('MD1','MD0'))]:
  for var in variants:
   fills=list(csv.DictReader(open(ROOT/slug/'reports'/(var+'_fills.csv'))));errors=[]
   for i,f in enumerate(fills):
    price=float(f['price']);q=int(f['qty']);fee=float(f['fee'])
    if abs(price-lookup[f['symbol']][f['date']])>1e-7:errors.append([i,'not_source_open'])
    if abs(fee-q*(price*.001+.005))>1e-7:errors.append([i,'fee'])
   check={'variant':var,'all_fills_checked':len(fills),'errors':errors,'source_sha256':sha256(a.raw),'independent_price_and_fee_check':True};dump(ROOT/slug/'reports'/(var+'_independent_fill_checks.json'),check);allchecks.append(check)
 for slug in ('christian_flanders','mark_minervini'):
  path=ROOT/slug/'reports/results.json';r=json.loads(path.read_text());text='\n## 证据门实际判定\n\n'
  for x in r['results']:
   m=x['main'];text+=f"- {m['variant']}：均R={m['mean_R']:.4f}；月块95%区间={x['bootstrap'].get('mean_R_95_interval')}；剔除最好10笔后已实现PnL={m['best10_removed_pnl']:.2f}；25bp压力权益变化={x['stress']['net_return']:.2%}"
   if 'random_date_control' in x:text+=f"；随机日期200次分位={x['random_date_control']['main_percentile']:.0%}（非完全匹配安慰剂）"
   text+='。未通过预登记整体证据门。\n'
  text+='\n即便净权益变化为正，也不代表每笔风险单位期望为正；仓位/成本/未平仓会使两者不同。描述基准见benchmarks.json，QQQ重叠期另列，不用不等长窗口做优劣宣称。\n'
  p=ROOT/slug/'reports/FINAL_CN.md';existing=p.read_text().split('\n## 证据门实际判定')[0];p.write_text(existing+text)
 bars={}
 with gzip.open(a.minute,'rt') as f:
  for r in csv.DictReader(f):
   end=datetime.fromisoformat(r['datetime_et']);start=(end-timedelta(minutes=1)).isoformat();bars[(r['symbol'],start)]=(float(r['low']),float(r['high']),float(r['volume']),end.isoformat())
 for slug,folder,variants in [('clement_ang','r2_minute',('CM1','CM0')),('j_law','r2_minute',('JL1','JL0')),('deepak_uppal','r2_minute',('DN1','DN0')),('deepak_uppal','r3_quarter_eps',('DQ1','DQ0'))]:
  for var in variants:
   p=ROOT/slug/'reports'/folder/(var+'_fills.csv')
   if not p.exists():continue
   fills=list(csv.DictReader(open(p)));errors=[];volumes=defaultdict(int)
   for i,f in enumerate(fills):
    key=f['symbol'],f['fill_time_lower'];lo,hi,v,end=bars[key];price=float(f['price']);qty=int(f['qty']);fee=float(f['fee']);volumes[key]+=qty
    if not lo-1e-8<=price<=hi+1e-8:errors.append([i,'outside_source_bar'])
    if abs(fee-qty*(price*.001+.005))>1e-7:errors.append([i,'fee'])
    if not f['fill_time_lower']<=f['at']<=f['fill_time_upper']:errors.append([i,'timestamp_bounds'])
   for key,qty in volumes.items():
    if qty>math.floor(bars[key][2]*.01):errors.append([key,'bar_volume_cap'])
   check={'variant':var,'all_fills_checked':len(fills),'errors':errors,'source_sha256':sha256(a.minute),'independent_price_fee_capacity_time_check':True,'minute_bar_bounds_not_actual_tick_fill':True};dump(ROOT/slug/'reports'/folder/(var+'_independent_fill_checks.json'),check);allchecks.append(check)
 dump(ROOT/'trader_common/reports/independent_fill_checks.json',allchecks)
 if any(c['errors'] for c in allchecks):raise AssertionError('independent fill audit failures')
if __name__=='__main__':main()
