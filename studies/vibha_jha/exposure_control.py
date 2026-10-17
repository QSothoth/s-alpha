"""Post-result fixed-risk-budget benchmark: 6.667% target, daily open rebalance.
Same actual ETF units and fee assumptions; different turnover explicitly disclosed.
"""
import csv,json,math,datetime,hashlib
from pathlib import Path

def main():
 here=Path(__file__).parent;path=Path('data/trader-data/public-daily/xjcarter_TQQQ.csv');bars=list(csv.DictReader(path.open()));cash=100000.;qty=0.;fees=0.;nav=[];orders=[];peak=100000.;mdd=0.;weight=1/15
 for i,b in enumerate(bars):
  o=float(b['Open']);c=float(b['Close']);eq=cash+qty*o
  if i>=61:
   want=math.floor(eq*weight/o);delta=want-qty;delta=math.copysign(min(abs(delta),math.floor(float(bars[i-1]['Volume'])*.01)),delta)
   if delta:
    fill=o*(1.001 if delta>0 else .999);fee=abs(delta)*.005;cash-=delta*fill+fee;qty+=delta;fees+=abs(delta)*o*.001+fee
    orders.append({'date':b['Date'],'delta_units':delta,'fill':fill,'fee':fee,'target_weight':weight})
  eq=cash+qty*c;peak=max(peak,eq);mdd=min(mdd,eq/peak-1);nav.append({'date':b['Date'],'cash':cash,'market_value':qty*c,'equity':eq,'exposure':qty*c/eq})
 end=float(bars[-1]['Close']);cash+=qty*end*.999-qty*.005;fees+=qty*end*.001+qty*.005
 result={'candidate':'C1_daily_open_fixed_6p667pct','status':'POST_RESULT_EXPOSURE_AUDIT_NOT_OOS','start':bars[0]['Date'],'end':bars[-1]['Date'],'initial_cash':100000,'target_weight':weight,'net_return':cash/100000-1,'max_drawdown':min(mdd,cash/peak-1),'rebalance_orders':len(orders),'transaction_costs':fees,'mean_exposure':sum(x['exposure'] for x in nav)/len(nav),'warning':'Constant target budget approximately matches V2-V5 initial risk-based weight; not exactly realized time-in-market exposure. Same next-open price/cost basis; daily rebalance turnover differs. Split-adjusted unit path, no dividend cash. Post-result diagnostic, no fitted parameters.'}
 out=here/'reports/exposure_control';out.mkdir(exist_ok=True)
 for name,rs in [('nav',nav),('orders',orders)]:
  with (out/(name+'.csv')).open('w') as f:w=csv.DictWriter(f,fieldnames=list(rs[0]));w.writeheader();w.writerows(rs)
 (out/'results.json').write_text(json.dumps(result,indent=2));(out/'manifest.json').write_text(json.dumps({'run_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'code_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'data_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'command':'python -m studies.vibha_jha.exposure_control','exit_code':0},indent=2));print(json.dumps(result,indent=2))
if __name__=='__main__':main()
