"""Three frozen real-ETF mechanisms; raw-price hypothetical ledger, not total return."""
import argparse,csv,hashlib,json,statistics,math
from pathlib import Path
from .rules import technical_reversal,bottom_decile,exit_intent
VARIANTS={'A_confirmation':(True,False),'B_no_confirmation':(False,False),'C_fixed_five':(True,True)}

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def read_csv(p):
    with p.open() as f:
        return {r['date']:{k:float(r[k]) for k in ('open','high','low','close','volume_provider')} for r in csv.DictReader(f)}
def load(root):
    selection=json.loads((root/'selection_prereg.json').read_text());symbols=selection['symbols']
    assert len(symbols)==12 and len(set(symbols))==12
    raw={};qfq={};manifest=[]
    for code in symbols:
        for typ,target in [('raw',raw),('qfq',qfq)]:
            p=root/f'{code}_{typ}.csv';target[code]=read_csv(p)
            assert target[code],f'No {typ} data: {code}'
            for d,b in target[code].items():
                assert 0<b['low']<=min(b['open'],b['close'])<=max(b['open'],b['close'])<=b['high'],(code,d,b)
            manifest.append({'path':str(p),'sha256':sha(p),'rows':len(target[code])})
    start=max('2024-02-26',max(min(v) for v in qfq.values()),max(min(v) for v in raw.values()))
    end=min(min(max(v) for v in raw.values()),min(max(v) for v in qfq.values()))
    dates=sorted({d for v in raw.values() for d in v if start<=d<=end})
    actions=[]
    for code in symbols:
        previous=None
        for d in dates:
            if d not in raw[code] or d not in qfq[code]:continue
            ratio=raw[code][d]['close']/qfq[code][d]['close']
            if previous and abs(ratio/previous-1)>.002:
                actions.append({'code':code,'date':d,'ratio_change':ratio/previous-1,'status':'inferred_adjustment_difference_not_verified_cash_action'})
            previous=ratio
    manifest.append({'path':str(root/'selection_prereg.json'),'sha256':sha(root/'selection_prereg.json')})
    return raw,qfq,dates,actions,manifest

def simulate(raw,dates,variant,actions=(),splits=(),cost_bps=0):
    fee_rate=cost_bps/10000.
    confirmation,fixed=VARIANTS[variant];cash=1000000.;positions={};marks={};pending_buys=[];pending_sells={}
    signals=[];orders=[];fills=[];trades=[];equity=[];adjusted={(x['code'],x['date']) for x in actions}
    order_serial=0
    def order(code,side,date,cutoff,**kw):
        nonlocal order_serial
        order_serial+=1
        obj=dict(order_id=f'{variant}-{order_serial}',variant=variant,code=code,side=side,
            signal_at=cutoff+'T15:00:00+08:00',information_cutoff=cutoff+'T15:00:00+08:00',
            order_created_at=cutoff+'T15:00:01+08:00',intended_session=date,
            hypothesis_id='H-ZQ-TECH-01',source_rule_id='ZQ-2024-05-22',**kw)
        orders.append(obj);return obj
    corporate_ledger=[]
    for t,date in enumerate(dates):
        for action in splits:
            if action['effective_session'] != date:continue
            code=action['code'];factor=action['share_factor']
            if code in positions:
                pos=positions[code];before_qty=pos['quantity'];before_cost=pos['cost']
                theoretical_quantity=pos['quantity']*factor
                pos['quantity']=math.ceil(theoretical_quantity) if action.get('rounding')=='ceil' else theoretical_quantity
                pos['entry_price']=pos['cost']/pos['quantity'];pos['signal_low']/=factor
                pos['adjustment_flag']=True
                marks[code]=marks.get(code,pos['entry_price']*factor)/factor
                corporate_ledger.append(dict(action,old_quantity=before_qty,new_quantity=pos['quantity'],cost_before=before_cost,cost_after=pos['cost'],
                    economic_value_rounding_residual=pos['quantity']*marks[code]-before_qty*marks[code]*factor,
                    fractional_entitlement_units=pos['quantity']%1,
                    fractional_entitlement_marked_value=(pos['quantity']%1)*marks[code],
                    actual_credit_rounding_verified=action.get('rounding')=='ceil',
                    rounding_credit_units=pos['quantity']-theoretical_quantity,
                    rounding_credit_marked_value=(pos['quantity']-theoretical_quantity)*marks[code]))
                if code in pending_sells:pending_sells[code]['requested_quantity']=pos['quantity']
            for intent in pending_buys:
                if intent['code']==code:intent['signal_low']/=factor
        # Opening batch can use only the open plus previous completed information.
        opening_cash=cash
        spent_from_prior_cash=0.
        for code,o in sorted(list(pending_sells.items())):
            b=raw[code].get(date)
            if b is None:continue
            pos=positions[code]
            if t<=pos['entry_index']:continue
            price=b['open'];before=cash;fee=pos['quantity']*price*fee_rate;cash+=pos['quantity']*price-fee
            o.update(status='hypothetical_filled',filled_at=date+'T09:30:00+08:00',price=price,quantity=pos['quantity'])
            fills.append(dict(o,cash_before=before,cash_after=cash,fee_assumption=fee,cost_basis_released=pos['cost']))
            trades.append(dict(code=code,variant=variant,entry_date=pos['entry_date'],exit_date=date,quantity=pos['quantity'],
                entry_price=pos['entry_price'],exit_price=price,pnl=pos['quantity']*(price-pos['entry_price']),
                raw_price_return=price/pos['entry_price']-1,pnl_after_modeled_costs=pos['quantity']*(price-pos['entry_price'])-pos['entry_fee']-fee,holding_sessions=t-pos['entry_index'],
                adjustment_flag_during_hold=pos['adjustment_flag'] or (code,date) in adjusted))
            del positions[code];del pending_sells[code]
        for intent in pending_buys:
            code=intent['code'];b=raw[code].get(date);o=intent['order']
            if b is None:o['status']='cancelled_missing_next_open';continue
            qty=int(min(intent['budget'],opening_cash-spent_from_prior_cash)/(b['open']*(1+fee_rate))/100)*100
            if qty<=0:o['status']='rejected_budget_or_lot';continue
            if code in positions or len(positions)>=5:o['status']='rejected_position_limit';continue
            value=qty*b['open'];fee=value*fee_rate;before=cash;cash-=value+fee;spent_from_prior_cash+=value+fee
            o.update(status='hypothetical_filled',quantity=qty,price=b['open'],filled_at=date+'T09:30:00+08:00')
            fills.append(dict(o,cash_before=before,cash_after=cash,fee_assumption=fee,cost_basis_added=value))
            positions[code]=dict(quantity=qty,cost=value,entry_price=b['open'],entry_date=date,entry_index=t,
                signal_low=intent['signal_low'],entry_fee=fee,adjustment_flag=(code,date) in adjusted)
        pending_buys=[]
        assert cash>=-1e-6
        # Daily close: future daily fields become available only here.
        stale=[]
        for code,pos in positions.items():
            b=raw[code].get(date)
            if b:marks[code]=b['close']
            else:stale.append(code);marks.setdefault(code,pos['entry_price'])
            pos['adjustment_flag'] |= (code,date) in adjusted
        nav=cash+sum(pos['quantity']*marks[code] for code,pos in positions.items())
        equity.append(dict(date=date,cash=cash,marked_positions=nav-cash,equity=nav,positions=len(positions),stale_marks=stale,
            inventory_lots={code:dict(pos,mark=marks[code]) for code,pos in positions.items()}))
        for f in fills:
            if f['filled_at'][:10]==date:
                b=raw[f['code']][date]
                f['ex_post_zero_volume_or_one_price']=b['volume_provider']<=0 or b['high']==b['low']
        if t+1>=len(dates):continue
        for code,pos in sorted(positions.items()):
            b=raw[code].get(date)
            if b and code not in pending_sells and exit_intent(b['close'],pos['signal_low'],t-pos['entry_index']+1,fixed):
                pending_sells[code]=order(code,'sell',dates[t+1],date,status='pending',requested_quantity=pos['quantity'])
        features={}
        if t>=21:
            for code,bars in raw.items():
                history=[bars.get(d) for d in dates[t-21:t+1]]
                if all(history):
                    adjusted_history=[]
                    for historical_date,bar in zip(dates[t-21:t+1],history):
                        factor=1.
                        for action in splits:
                            if action['code']==code and historical_date<action['effective_session']<=date:factor*=action['share_factor']
                        adjusted_history.append({k:(v/factor if k in ('open','high','low','close') else v) for k,v in bar.items()})
                    features[code]=technical_reversal(adjusted_history)
        cohort=bottom_decile(features,confirmation)
        free_slots=5-len(positions);reserved=0.
        for code in sorted(cohort):
            signal=dict(variant=variant,code=code,date=date,information_cutoff=date+'T15:00:00+08:00',**features[code])
            signals.append(signal)
            if code in positions:signal['status']='already_held';continue
            if free_slots<=0:signal['status']='position_limit';continue
            budget=min(.1*nav,cash-reserved)
            if budget<=0:signal['status']='no_cash';continue
            signal['status']='order_created';free_slots-=1;reserved+=budget
            o=order(code,'buy',dates[t+1],date,status='pending',target_budget=budget,quantity_policy='100-unit lots from frozen prior-close budget at visible open')
            pending_buys.append(dict(code=code,budget=budget,signal_low=features[code]['signal_low'],order=o))
    for o in orders:
        if o['status']=='pending':o['status']='right_censored_pending'
    strict=[dict(o,status='unverified_execution_quote_queue_and_cashflow_coverage',quantity=0,price=None,filled_at=None) for o in orders if o['side']=='buy']
    return dict(signals=signals,orders=orders,fills=fills,trades=trades,equity=equity,strict_orders=strict,corporate_actions=corporate_ledger,execution_metadata=[dict(cost_bps=cost_bps,product_identity_and_pre_window_listing_verified=True,domestic_equity_etf_t_plus_one=True,opening_execution_feasibility_verified=False,cash_dividends_complete=False)])

def summary(run):
    eq=run['equity'];peak=1000000.;dd=0.
    for r in eq:peak=max(peak,r['equity']);dd=min(dd,r['equity']/peak-1)
    values=[x['raw_price_return'] for x in run['trades']]
    turnover=sum(x['price']*x['quantity'] for x in run['fills'])
    end=eq[-1];pnl=end['equity']-1000000.
    return dict(modeled_one_way_cost_bps=run['execution_metadata'][0]['cost_bps'],price_equity_change_after_modeled_costs=pnl/1000000.,signals=len(run['signals']),orders=len(run['orders']),hypothetical_fills=len(run['fills']),round_trips=len(values),
        mean_trade_price_return=statistics.mean(values) if values else None,median_trade_price_return=statistics.median(values) if values else None,
        positive_fraction=sum(x>0 for x in values)/len(values) if values else None,
        hypothetical_price_equity_change=pnl/1000000.,maximum_drawdown_raw_price=dd,
        end_equity=end['equity'],end_cash=end['cash'],end_inventory_count=end['positions'],turnover=turnover,
        uniform_one_way_breakeven_bps=pnl/turnover*10000 if turnover else None,
        adjustment_exposed_completed_trades=sum(t['adjustment_flag_during_hold'] for t in run['trades']),
        strict_fills=0,strict_equity=1000000.,net_total_return_claim=False)

def main():
    p=argparse.ArgumentParser();p.add_argument('--data-root',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--cost-bps',type=float,default=0,choices=[0,10,30]);a=p.parse_args()
    raw,qfq,dates,actions,manifest=load(a.data_root)
    split_path=a.data_root/'split_events_verified.json'
    splits=json.loads(split_path.read_text())
    manifest.append({'path':str(split_path),'sha256':sha(split_path)})
    a.output.mkdir(parents=True,exist_ok=True)
    results={}
    for v in VARIANTS:
        run=simulate(raw,dates,v,actions,splits,a.cost_bps);results[v]=summary(run)
        for key,records in run.items():
            with (a.output/f'{v}_{key}.jsonl').open('w') as f:
                for r in records:f.write(json.dumps(r,sort_keys=True)+'\n')
        results[v]['period_equity_changes']={}
        for label,lo,hi in [('description_2024','2024','2025'),('validation_2025_plus','2025','2027')]:
            selected=[r for r in run['equity'] if lo<=r['date']<hi]
            earlier=[r for r in run['equity'] if r['date']<lo]
            base=earlier[-1]['equity'] if earlier else 1000000.
            results[v]['period_equity_changes'][label]=selected[-1]['equity']/base-1 if selected else None
    audit=dict(readiness='E1_real_ETF_price_mechanism',symbols=sorted(raw),start=dates[0],end=dates[-1],sessions=len(dates),
        adjustment_flags=actions,raw_rows=sum(len(x) for x in raw.values()),qfq_rows=sum(len(x) for x in qfq.values()),
        actual_total_return_ready=False,historical_tradability_verified=False,volume_units_verified=False)
    for name,obj in [('summary.json',results),('data_audit.json',audit),('input_manifest.json',manifest)]:
        (a.output/name).write_text(json.dumps(obj,indent=2,ensure_ascii=False)+'\n')
    source=Path(__file__).parent
    (a.output/'source_hashes.json').write_text(json.dumps({str(x.relative_to(source)):sha(x) for x in sorted(source.rglob('*.py'))},indent=2)+'\n')
    print(json.dumps(results,indent=2))
if __name__=='__main__':main()
