"""Causal factor-unit daily research ledger; shared explicitly by three study slices.
No broker connections. Signals consume completed bars; orders fill next session.
"""
import csv,gzip,json,hashlib,math
from pathlib import Path
from collections import defaultdict

def load(folder,symbols):
    folder=Path(folder); bars=defaultdict(dict); actions=defaultdict(dict)
    for r in csv.DictReader(gzip.open(folder/'bars_raw.csv.gz','rt')):
        s=r['code'].removeprefix('US.')
        if s in symbols:
            b={k:float(r[k]) for k in ('open','high','low','close','volume')}; b['date']=r['date']
            if min(b[k] for k in ('open','high','low','close'))<=0: continue
            bars[s][r['date']]=b
    for r in csv.DictReader(gzip.open(folder/'actions.csv.gz','rt')):
        s=r['code'].removeprefix('US.')
        if s in symbols: actions[s][r['ex_date']]=(float(r['factor_a']),float(r['factor_b']))
    audit={'files':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in [folder/'bars_raw.csv.gz',folder/'actions.csv.gz',folder/'universe.json']},'universe_metadata':json.loads((folder/'universe.json').read_text()),'coverage':{s:{'start':min(x),'end':max(x),'bars':len(x)} for s,x in bars.items()},'pit':False,'warning':'2026 snapshot-selected survivor list; no PIT fundamentals or delisted universe; no fresh OOS'}
    return bars,actions,audit

def rsi(h,n=14):
    if len(h)<n+1:return 50.
    d=[h[i]['close']-h[i-1]['close'] for i in range(len(h)-n,len(h))]
    u=sum(max(0,x) for x in d);v=sum(max(0,-x) for x in d)
    return 100*u/(u+v) if u+v else 50.

def mean(xs):return sum(xs)/len(xs)

def run(bars,actions,signal,config,candidate,out):
    cash=config['initial_cash']; positions={}; history=defaultdict(list); pending={}; exits={}; marks={}; trades=[]; nav=[]; events=[]; states={}; fees=0.; dividends=0.; last={}; accounting=0.; peak=cash; maxdd=0.
    dates=sorted({d for x in bars.values() for d in x}); cost=(25 if 'cost25' in candidate else config['cost_bps'])/10000; per=config['commission_per_share']; risk=config['risk_fraction']; cap=config['max_weight']; applied=set()
    def sell(s,px,date,reason):
        nonlocal cash,fees
        p=positions.pop(s); fill=px*(1-cost); fee=p['qty']*per;cash+=p['qty']*fill-fee;fees+=p['qty']*(px-fill)+fee
        pnl=p['qty']*fill-fee-p['basis']+p['dividends']
        trades.append({'symbol':s,'entry_date':p['entry_date'],'exit_date':date,'entry_price':p['entry_price'],'exit_price':fill,'quantity_exit':p['qty'],'basis':p['basis'],'pnl':pnl,'dividends':p['dividends'],'reason':reason,'planned_risk':p['planned_risk'],'realized_r':pnl/p['planned_risk'] if p['planned_risk'] else 0,'signal_date':p['signal_date']})
        events.append({'date':date,'symbol':s,'event':'exit','reason':reason,'fill':fill})
    for date in dates:
        today={s:x[date] for s,x in bars.items() if date in x}
        # Apply only actions known to have become effective; never future-adjust prices.
        for s,b in today.items():
            for ex,(a,bb) in sorted(actions.get(s,{}).items()):
                if ex<=date and (s,ex) not in applied and history[s] and ex>history[s][0]['date']:
                    applied.add((s,ex))
                    if a<=0: raise ValueError('invalid corporate action')
                    for old in history[s]:
                        for k in ('open','high','low','close'):old[k]=a*old[k]+bb
                        old['volume']/=a
                    if s in positions:
                        p=positions[s]; div=p['qty']*(-bb/a);cash+=div;dividends+=div;p['dividends']+=div;p['qty']/=a;p['stop']=a*p['stop']+bb;p['entry_price']=a*p['entry_price']+bb
                    if s in pending:pending[s]['stop']=a*pending[s]['stop']+bb
                    # Pattern state price levels must undergo same effective-date transformation.
                    for k in ('first_high','trough','first_low','pivot','stop'):
                        if k in states.get(s,{}):states[s][k]=a*states[s][k]+bb
                    if 'lows' in states.get(s,{}):states[s]['lows']=[a*x+bb for x in states[s]['lows']]
                    events.append({'date':date,'symbol':s,'event':'corporate_action','a':a,'b':bb})
            marks[s]=b['open']
        for s in sorted(list(positions)):
            if s not in today:continue
            b=today[s]
            if s in exits:sell(s,b['open'],date,exits.pop(s))
            elif b['open']<=positions[s]['stop']:sell(s,b['open'],date,'gap_stop')
        # Deterministic symbol order, prior-close volume capacity; no future daily volume for sizing.
        for s,o in sorted(pending.items()):
            if s not in today:continue
            b=today[s]
            if s in positions:continue
            if len(positions)>=config.get('max_positions',100000):
                events.append({'date':date,'symbol':s,'event':'rejected','reason':'max_positions'});continue
            eq=cash+sum(p['qty']*marks.get(t,p['entry_price']) for t,p in positions.items()); fill=b['open']*(1+cost); distance=fill-o['stop']
            if distance<=0 or (distance/fill>.25 and candidate!='V1_hold'):
                events.append({'date':date,'symbol':s,'event':'rejected','reason':'invalid_or_wide_stop'});continue
            risk_qty=eq*risk/distance if candidate!='V1_hold' else eq/fill
            qty=math.floor(min(risk_qty,eq*cap/fill,cash/(fill+per),history[s][-1]['volume']*config['participation']))
            if qty<=0:
                events.append({'date':date,'symbol':s,'event':'rejected','reason':'cash_or_capacity'});continue
            basis=qty*(fill+per);cash-=basis;fees+=qty*(fill-b['open']+per)
            positions[s]={'qty':qty,'basis':basis,'entry_date':date,'entry_price':fill,'stop':o['stop'],'planned_risk':qty*distance,'signal_date':o['date'],'dividends':0.,'be':False,'entry_index':len(history[s])}
            events.append({'date':date,'symbol':s,'event':'entry','fill':fill,'qty':qty,'stop':o['stop'],'signal_date':o['date']})
        pending={s:o for s,o in pending.items() if s not in today}
        for s,b in sorted(today.items()):
            p=positions.get(s)
            if p and b['low']<=p['stop']:
                sell(s,p['stop'],date,'intraday_stop_conservative')
            history[s].append(dict(b));marks[s]=b['close'];last[s]=date
            entry,reason,details=signal(s,history[s],states.setdefault(s,{}),positions.get(s),candidate,date)
            if details:events.append({'date':date,'symbol':s,**details})
            if reason and s in positions:exits[s]=reason
            if entry is not None and s not in positions:pending[s]={'stop':entry,'date':date}
            p=positions.get(s)
            if p and candidate.startswith('S') and ('_be' in candidate) and not p['be'] and b['close']>=1.10*p['entry_price']:
                # Close confirmation: protection starts next bar; never retroactively stop at same-day low.
                p['stop']=max(p['stop'],p['entry_price']);p['be']=True
                events.append({'date':date,'symbol':s,'event':'breakeven_armed_next_bar'})
        eq=cash+sum(p['qty']*marks[s] for s,p in positions.items());peak=max(peak,eq);maxdd=min(maxdd,eq/peak-1)
        accounting=max(accounting,abs(eq-cash-sum(p['qty']*marks[s] for s,p in positions.items())))
        if cash < -1e-6:raise AssertionError('negative cash')
        nav.append({'date':date,'cash':cash,'market_value':eq-cash,'equity':eq,'positions':len(positions),'drawdown':eq/peak-1})
    # Explicit terminal liquidation is artificial and separately labeled, not a learned exit.
    for s in list(positions):sell(s,marks[s],dates[-1],'terminal_mark_liquidation')
    if nav:nav[-1].update(cash=cash,market_value=0.,equity=cash,positions=0)
    pnl=sum(t['pnl'] for t in trades);reconciliation=abs(cash-config['initial_cash']-pnl)
    results={'candidate':candidate,'status':'EXECUTED_DAILY_FACTOR_UNIT_H_PROXY','share_accounting':'factor-unit adjustment; multiplicative dividend factors are reinvestment proxies, not verified actual shares; per-unit fees H','start':dates[0] if dates else None,'end':dates[-1] if dates else None,'trades':len(trades),'net_return':cash/config['initial_cash']-1,'max_drawdown':min(maxdd,cash/peak-1),'net_pnl':pnl,'transaction_costs':fees,'dividend_cash':dividends,'win_rate':sum(t['pnl']>0 for t in trades)/len(trades) if trades else None,'removed_top_trade_pnl_diagnostic_not_portfolio_rerun':pnl-max([t['pnl'] for t in trades]+[0]),'by_symbol':{s:sum(t['pnl'] for t in trades if t['symbol']==s) for s in bars},'by_exit_year':{y:sum(t['pnl'] for t in trades if t['exit_date'][:4]==y) for y in sorted({t['exit_date'][:4] for t in trades})},'mean_close_exposure':sum(x['market_value']/x['equity'] for x in nav if x['equity'])/len(nav) if nav else 0,'max_close_exposure':max([x['market_value']/x['equity'] for x in nav if x['equity']]+[0]),'pending_unexecuted_end':len(pending),'accounting_error':max(accounting,reconciliation),'oos':False}
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    for name,rows in [('trades',trades),('nav',nav),('events',events)]:
        keys=sorted({k for r in rows for k in r})
        with (out/(name+'.csv')).open('w') as f:
            w=csv.DictWriter(f,fieldnames=keys);w.writeheader();w.writerows(rows)
    (out/'results.json').write_text(json.dumps(results,indent=2));(out/'checks.json').write_text(json.dumps({'ledger_reconciles':reconciliation<1e-6,'max_error':max(accounting,reconciliation),'nonnegative_cash':all(x['cash']>=-1e-6 for x in nav),'signal_before_entry':all(t['signal_date']<t['entry_date'] for t in trades)},indent=2))
    return results
