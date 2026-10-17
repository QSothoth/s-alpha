"""Daily-close/next-open diagnostic ledger. NOT an intraday stop simulator."""
from collections import defaultdict
from math import floor
import numpy as np
from studies.christian_flanders.signals import add_size

def simulate(data, feats, signals, variant, cost_bps=10., initial=100000.):
    calendar=sorted({d for v in data.values() for d in v['dates']})
    indices={s:{d:i for i,d in enumerate(v['dates'])} for s,v in data.items()}
    scheduled=defaultdict(list)
    for s,ii in signals.items():
        for i in ii:
            if i+1<len(data[s]['dates']):scheduled[data[s]['dates'][i+1]].append((s,i))
    cash=initial; positions={};trades=[];fills=[];nav=[];orders=[];loss_streak=0
    def fee(price,q):return q*(price*cost_bps/10000+.005)
    def mark(s,p,day,at_open=False):
        i=indices[s].get(day)
        return data[s]['values'][i,0 if at_open else 3] if i is not None else p['last_mark']
    def equity(day,at_open=False):return cash+sum(p['qty']*mark(s,p,day,at_open) for s,p in positions.items())
    def sell(s,p,q,price,day,why):
        nonlocal cash,loss_streak
        q=min(q,p['qty']);cost=fee(price,q);cash+=q*price-cost
        p['realized']+=q*(price-p['entry'])-cost-p['entry_fee_share']*q
        p['qty']-=q;p['exit_fees']+=cost
        fills.append({'symbol':s,'date':day,'side':'SELL','qty':q,'price':price,'fee':cost,'reason':why,'entry_date':p['date']})
        if p['qty']==0:
            trades.append({'symbol':s,'entry_date':p['date'],'exit_date':day,'entry_price':p['entry'],'last_exit_price':price,'initial_qty':p['original_qty'],'initial_stop':p['initial_stop'],'planned_risk':p['risk'],'pnl':p['realized'],'R':p['realized']/p['risk'],'bars_held':p['held'],'reason':why,'adds':p['adds'],'entry_fees':p['entry_fees'],'exit_fees':p['exit_fees']})
            loss_streak=loss_streak+1 if p['realized']<0 else 0
            del positions[s]
    for day in calendar:
        for s,p in list(sorted(positions.items())):
            i=indices[s].get(day)
            if i is None:continue
            price=data[s]['values'][i,0];volume=data[s]['values'][i-1,4] if i>0 else 0
            if p.get('pending') and volume>0:
                why,q=p.pop('pending')
                # Prior completed volume is a sizing cap only, not observed opening liquidity.
                capacity=floor(volume*.01);sold=min(q,capacity)
                if sold:sell(s,p,sold,price,day,why)
                if s in positions and sold<q:p['pending']=(why,q-sold)
                if s in positions and why=='partial' and sold==q:
                    p['partial_done']=True;p['stop']=max(p['stop'],p['entry'])
        for s,i in sorted(scheduled[day]):
            j=i+1;price=data[s]['values'][j,0];vol=data[s]['values'][i,4]
            stop=float(feats[s]['stop10'][i]);eq=equity(day,True)
            reason='accepted';q=0
            if vol<=0:reason='zero_volume'
            elif not 0<price-stop<price*.1:reason='stop_width_or_gap'
            elif s in positions:
                p=positions[s]
                if variant=='FD1' and p['adds']==0:
                    q,newstop=add_size(p['original_qty'],p['qty'],p['entry'],price,stop,p['stop'],eq,cash)
                    cap=floor(vol*.01);q=min(q,cap,floor(cash/(price+price*cost_bps/10000+.005)))
                    total_risk=sum(max(0,x['entry']-x['stop'])*x['qty'] for x in positions.values() if x is not p)+max(0,p['entry']-newstop)*p['qty']+max(0,price-newstop)*q
                    if total_risk>eq*.01:q=0
                    if q>0:
                        cost=fee(price,q);oldq=p['qty'];p['entry']=(p['entry']*oldq+price*q)/(oldq+q)
                        p['entry_fee_share']=(p['entry_fee_share']*oldq+cost)/(oldq+q)
                        p['qty']+=q;p['entry_fees']+=cost;p['risk']+=max(0,price-newstop)*q;p['stop']=newstop;p['adds']=1;cash-=price*q+cost
                        fills.append({'symbol':s,'date':day,'side':'BUY','qty':q,'price':price,'fee':cost,'reason':'pyramid','entry_date':p['date']})
                reason='existing_position_add' if q else 'existing_position_no_add'
            else:
                budget=eq*(.00125 if variant.startswith('FD') and loss_streak>=3 else .0025)
                openrisk=sum(max(0,p['entry']-p['stop'])*p['qty'] for p in positions.values())
                budget=min(budget,max(0,eq*.01-openrisk))
                q=floor(min(budget/(price-stop),eq*.20/price,cash/(price+price*cost_bps/10000+.005),vol*.01))
                if q>0:
                    cost=fee(price,q);cash-=q*price+cost
                    positions[s]={'qty':q,'original_qty':q,'entry':price,'date':day,'stop':stop,'initial_stop':stop,'risk':q*(price-stop),'initial_r_per_share':price-stop,'entry_fee_share':cost/q,'entry_fees':cost,'exit_fees':0.,'realized':0.,'held':0,'adds':0,'last_mark':price,'partial_done':False}
                    fills.append({'symbol':s,'date':day,'side':'BUY','qty':q,'price':price,'fee':cost,'reason':'new','entry_date':day})
                else:reason='risk_cash_capacity'
            orders.append({'symbol':s,'signal_date':data[s]['dates'][i],'date':day,'price':price,'stop':stop,'qty':q,'reason':reason})
        for s,p in positions.items():
            i=indices[s].get(day)
            if i is None:continue
            close=float(data[s]['values'][i,3]);p['last_mark']=close;p['held']+=1
            if p.get('pending'):continue
            why=None;q=p['qty']
            if close<p['stop']:why='close_stop'
            elif close<feats[s]['sma10'][i]:why='close_below_sma10'
            elif variant.startswith('MD') and p['held']>=10:why='timeout'
            elif variant.startswith('MD') and not p['partial_done']:
                target=2 if variant=='MD1' else 1
                if close>=p['entry']+target*p['initial_r_per_share']:
                    why='partial';q=max(1,p['qty']//2)
            if why:p['pending']=(why,q)
        eq=equity(day);mv=eq-cash
        nav.append({'date':day,'cash':cash,'market_value':mv,'equity':eq,'exposure':mv/eq if eq else 0,'positions':len(positions),'max_position_weight':max((p['qty']*mark(s,p,day)/eq for s,p in positions.items()),default=0)})
        if cash<-1e-6:raise AssertionError('negative cash')
    peak=initial;mdd=0
    for n in nav:peak=max(peak,n['equity']);mdd=min(mdd,n['equity']/peak-1)
    pnl=np.array([t['pnl'] for t in trades]);rs=np.array([t['R'] for t in trades]);fees=sum(f['fee'] for f in fills)
    summary={'variant':variant,'cost_bps':cost_bps,'initial_equity':initial,'final_equity':nav[-1]['equity'] if nav else initial,'net_return':nav[-1]['equity']/initial-1 if nav else 0,'max_drawdown':mdd,'closed_trades':len(trades),'win_rate':float(np.mean(pnl>0)) if len(pnl) else None,'mean_R':float(np.mean(rs)) if len(rs) else None,'realized_pnl':float(sum(pnl)),'fees':fees,'best10_removed_pnl':float(sum(sorted(pnl)[:-10])) if len(pnl)>10 else None,'open_positions':len(positions),'unrealized_net_pnl':sum(p['qty']*(p['last_mark']-p['entry']-p['entry_fee_share'])+p['realized'] for p in positions.values()),'average_exposure':float(np.mean([n['exposure'] for n in nav])) if nav else 0,'adds':sum(f['reason']=='pyramid' for f in fills)}
    assert abs(summary['final_equity']-initial-summary['realized_pnl']-summary['unrealized_net_pnl'])<1e-5
    from .metrics import distribution
    summary['distribution']=distribution(trades,nav)
    return {'summary':summary,'trades':trades,'fills':fills,'nav':nav,'orders':orders,'open_positions':positions}
