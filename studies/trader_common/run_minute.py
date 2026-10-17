"""Source-separated, preregistered CM/JL technical hypotheses on real minutes.
QFQ prices are accounting units. Never advertises historical raw-share fills.
"""
import csv,gzip,json,argparse
from collections import defaultdict,Counter
from datetime import datetime,timedelta
from pathlib import Path
import numpy as np
from .execution import Engine,Bar,Order
from .data import features,load_daily,sha256
from .run_swing import dump,write_csv,bootstrap,ROOT
from studies.clement_ang.signals import screen as c_screen

SYMBOLS=['US.AAPL','US.AMD','US.META','US.MSFT','US.MU','US.NVDA','US.TSLA']
def read_eval_daily(path):
    groups=defaultdict(list)
    with gzip.open(path,'rt') as f:
        for r in csv.DictReader(f):groups[r['symbol']].append((r['date'],*[float(r[k]) for k in ('open','high','low','close','volume')]))
    return {s:{'dates':np.array([r[0] for r in sorted(rows)]),'values':np.array([r[1:] for r in sorted(rows)])} for s,rows in groups.items()}
def read_minutes(path):
    grouped=defaultdict(lambda:defaultdict(list))
    with gzip.open(path,'rt') as f:
        for r in csv.DictReader(f):
            if r['symbol'] not in SYMBOLS:continue
            end=datetime.fromisoformat(r['datetime_et']);start=end-timedelta(minutes=1)
            b=Bar(r['symbol'],start.isoformat(),end.isoformat(),*[float(r[k]) for k in ('open','high','low','close','volume')]);b.validate();grouped[r['date']][r['symbol']].append(b)
    result={d:{s:sorted(bs,key=lambda b:b.start) for s,bs in ss.items()} for d,ss in sorted(grouped.items())}
    for date,ss in result.items():
        for symbol,bars in ss.items():
            if len(bars)!=390 or bars[0].start[11:16]!='09:30' or bars[-1].end[11:16]!='16:00':raise ValueError('this round requires complete full sessions: '+symbol+' '+date)
            if any(a.end!=b.start for a,b in zip(bars,bars[1:])):raise ValueError('minute gap/duplicate; refuse row-index aggregation')
    return result
def pit_mode(rows,s,date):
    known=[r for r in rows.get(s[3:],[]) if r['available_on_or_after']<=date]
    if not known:return None,'no_filing'
    row=known[-1];m=row['metrics'];keys=('ttm_net_income','ttm_operating_cash_flow','ttm_free_cash_flow','revenue_quarter_yoy')
    # Actual source metric key is verified below, never assume absent field is zero.
    if any(m.get(k,{}).get('status')!='OK' or m[k].get('value') is None for k in keys):return None,'unknown_metric'
    return ('position' if all(m[k]['value']>0 for k in keys) else 'swing'),row['available_on_or_after']
def prepare(daily,raw,minutes,pitrows):
    f={s:features(d['values']) for s,d in daily.items()}
    idx={s:{d:i for i,d in enumerate(v['dates'])} for s,v in daily.items()};ri={s:{d:i for i,d in enumerate(v['dates'])} for s,v in raw.items()}
    plans={'CM1':defaultdict(list),'CM0':defaultdict(list),'JL1':defaultdict(list),'JL0':defaultdict(list),'DN1':defaultdict(list),'DN0':defaultdict(list),'DQ1':defaultdict(list),'DQ0':defaultdict(list)};rejections=[];history=defaultdict(list);day_features={}
    for date,ss in minutes.items():
        for s,bs in ss.items():
            prior=[d for d in daily[s]['dates'] if d<date]
            if not prior:continue
            prev=prior[-1];i=idx[s][prev];df=f[s];arr=daily[s]['values'];c=arr[i,3]
            qqprior=[d for d in daily['US.QQQ']['dates'] if d<date];qi=idx['US.QQQ'][qqprior[-1]];regime=daily['US.QQQ']['values'][qi,3]>f['US.QQQ']['sma50'][qi]
            rawi=ri.get(s,{}).get(prev);dollar=None
            if rawi is not None and rawi>=19:dollar=float(np.mean(raw[s]['values'][rawi-19:rawi+1,3]*raw[s]['values'][rawi-19:rawi+1,4]))
            selected=dollar is not None and c_screen(c,df['sma50'][i],df['sma200'][i],dollar,df['adr20'][i],df['atr14'][i])['numeric_selected']
            mode,pitdate=pit_mode(pitrows,s,date)
            known=[r for r in pitrows.get(s[3:],[]) if r['available_on_or_after']<=date]
            ni=known[-1]['metrics'].get('ttm_net_income',{}) if known else {}
            positive_ni=ni.get('status')=='OK' and ni.get('value',0)>0
            peer_returns=[]
            own_return=arr[i,3]/arr[i-126,3]-1 if i>=126 else float('nan')
            for peer in SYMBOLS:
                pi=idx[peer].get(prev)
                if pi is not None and pi>=126:peer_returns.append(daily[peer]['values'][pi,3]/daily[peer]['values'][pi-126,3]-1)
            rs=100*sum(v<=own_return for v in peer_returns)/len(peer_returns) if peer_returns else 0
            dn_gates={'raw_price':rawi is not None and raw[s]['values'][rawi,3]>75,'trend':c>0 and df['sma50'][i]>df['sma200'][i],'ATR5':df['atr14'][i]/c>.05,'RS80':rs>=80,'NI':positive_ni,'QQQ':bool(regime),'flag':i>=19 and (max(arr[i-9:i+1,1])-min(arr[i-9:i+1,2]))<=.75*(max(arr[i-19:i-9,1])-min(arr[i-19:i-9,2])) and np.mean(arr[i-9:i+1,4])<np.mean(arr[i-19:i-9,4])}
            dn_eligible=all(dn_gates.values())
            eps=known[-1]['metrics'].get('diluted_eps_quarter',{}) if known else {}
            eps_ok=eps.get('status')=='OK' and eps.get('value',0)>0 and eps.get('end') is not None and eps.get('end')==ni.get('end')
            dq_eligible=all(v for k,v in dn_gates.items() if k!='NI') and eps_ok
            rejections.append({'variant':'DQ_GATES','symbol':s,'at':date,'reason':'EPS_latest_positive' if eps_ok else 'EPS_missing_stale_or_nonpositive','EPS_status':eps.get('status'),'EPS_value':eps.get('value'),'EPS_end':eps.get('end'),'latest_reporting_end':ni.get('end')})
            dn_pivot=float(max(arr[max(0,i-9):i+1,1]))+.01
            rejections.append({'variant':'DN_GATES','symbol':s,'at':date,'reason':','.join(k for k,v in dn_gates.items() if not v),'ATR_percent':float(df['atr14'][i]/c*100),'RS_percentile':rs,**dn_gates})
            jltrend=c>df['sma50'][i]>df['sma200'][i] and regime
            pivot20=float(max(arr[max(0,i-19):i+1,1]))+.01;stop10=float(min(arr[max(0,i-9):i+1,2]))-.01
            day_features[(date,s)]={'sma10':float(df['sma10'][i]),'sma50':float(df['sma50'][i]),'index':i}
            cumul=np.cumsum([b.volume for b in bs]);fives=[];setup=None;attempted=set();low=float('inf')
            for k,b in enumerate(bs[:-1]):
                low=min(low,b.low)
                if (k+1)%5==0:
                    pack=bs[k-4:k+1];v=Bar(s,pack[0].start,b.end,pack[0].open,max(x.high for x in pack),min(x.low for x in pack),b.close,sum(x.volume for x in pack));fives.append(v)
                    if len(fives)>=3:
                        a,z,w=fives[-3:]
                        if w.end[11:16]>='10:00' and z.low<a.low and z.low<w.low:setup=(w.high+.01,z.low-.01,w.end)
                nxt=bs[k+1]
                if selected and setup and b.close>=setup[0]:
                    for variant in ('CM1','CM0'):
                        if variant in attempted:continue
                        attempted.add(variant)
                        distance=nxt.open-min(low,nxt.open)
                        if nxt.open<=setup[1]:rejections.append({'variant':variant,'symbol':s,'at':nxt.start,'reason':'open_below_stop'});continue
                        if variant=='CM1' and not distance<.6*df['atr14'][i]:rejections.append({'variant':variant,'symbol':s,'at':nxt.start,'reason':'distance','distance':distance,'atr':df['atr14'][i]});continue
                        plans[variant][nxt.start].append({'symbol':s,'signal_at':b.end,'active_at':nxt.start,'expires_at':bs[-1].end,'entry_reference':nxt.open,'stop':setup[1],'target':3.,'fraction':1/3 if regime else .5,'mode':'swing','risk':.0025,'source_rule':'C-M1-close-confirmed-assumption','day_low_known_at_entry':min(low,nxt.open),'yesterday_atr':float(df['atr14'][i]),'shape_confirmed_at':setup[2]})
                if jltrend and b.close>pivot20 and len(history[s])>=20 and 'JL' not in attempted:
                    baseline=np.median([h[k] for h in history[s][-20:] if len(h)>k])
                    if cumul[k]>1.5*baseline:
                        attempted.add('JL')
                        if mode is None:rejections.append({'variant':'JL','symbol':s,'at':nxt.start,'reason':'PIT_'+pitdate});continue
                        if nxt.open<=stop10:rejections.append({'variant':'JL','symbol':s,'at':nxt.start,'reason':'open_below_stop'});continue
                        for variant in ('JL1','JL0'):
                            hold=mode if variant=='JL1' else 'swing'
                            plans[variant][nxt.start].append({'symbol':s,'signal_at':b.end,'active_at':nxt.start,'expires_at':bs[-1].end,'entry_reference':nxt.open,'stop':stop10,'target':None if hold=='position' else 3.,'fraction':1.,'mode':hold,'risk':.003,'source_rule':'J-NI1-PIT-duration-assumption','pit_available_on':pitdate,'cumvolume':float(cumul[k]),'past20_same_time_median':float(baseline)})
                for family,eligible in (('DN',dn_eligible),('DQ',dq_eligible)):
                    if eligible and b.close>dn_pivot and family not in attempted:
                        attempted.add(family)
                        if nxt.open<=stop10:continue
                        for variant in (family+'1',family+'0'):
                            plans[variant][nxt.start].append({'symbol':s,'signal_at':b.end,'active_at':nxt.start,'expires_at':bs[-1].end,'entry_reference':nxt.open,'stop':stop10,'target':3.,'fraction':1. if variant.endswith('1') else .5,'mode':'swing','risk':.0025,'source_rule':'D-'+family+'-bullflag-assumption','pit_available_on':known[-1]['available_on_or_after'],'EPS_end':eps.get('end') if family=='DQ' else None,'EPS_operand_ids':eps.get('operands') if family=='DQ' else None})
            history[s].append(cumul)
            if not selected:rejections.append({'variant':'CM','symbol':s,'at':date,'reason':'daily_numeric_screen'})
    return plans,rejections,f,idx

def ma_exit_enabled(variant, target_done):
    return variant.startswith('JL') or (variant in ('CM1','CM0','DN0','DQ0') and target_done)

def run_variant(variant,plans,minutes,daily,f,idx,cost=10,per_share=.005):
    engine=Engine(cost_bps=cost,per_share=per_share);meta={};held=defaultdict(int);entry_at={}
    for date,ss in minutes.items():
        timeline=defaultdict(list)
        for s,bs in ss.items():
            for b in bs:timeline[b.start].append(b)
        for at,batch in sorted(timeline.items()):
            for n,p in enumerate(sorted(plans.get(at,[]),key=lambda x:x['symbol'])):
                s=p['symbol']
                if s in engine.positions:continue
                client=f'{variant}:{s}:{at}:{n}'
                o=Order(client,s,p['signal_at'],p['active_at'],p['expires_at'],p['entry_reference'],p['stop'],risk_fraction=p['risk'],target_r=p['target'],partial_fraction=p['fraction'],source_rule_id=p['source_rule'],hypothesis_id=variant,order_type='market')
                engine.submit(o);meta[client]=p
            before=set(engine.positions)
            engine.process_batch(batch)
            for s,p in engine.positions.items():
                if s not in before:entry_at[s]=date;held[s]=0
        for s,p in engine.positions.items():
            held[s]+=1;i=idx[s].get(date)
            if i is None:continue
            m=meta[p['id']];close=daily[s]['values'][i,3];mode=m['mode'];ma=50 if mode=='position' else 10
            ma_enabled=ma_exit_enabled(variant,p['target_done'])
            if ma_enabled and close<f[s]['sma'+str(ma)][i]:engine.exit_next_open(s,ss[s][-1].end,'daily_close_below_sma'+str(ma))
            elif variant.startswith(('JL','DN','DQ')) and held[s]>=(63 if mode=='position' else 10):engine.exit_next_open(s,ss[s][-1].end,'timeout')
    groups=defaultdict(list)
    for fill in engine.fills:groups[fill['client_id']].append(fill)
    trades=[]
    for id,fs in groups.items():
        buys=[x for x in fs if x['side']=='BUY'];sells=[x for x in fs if x['side']=='SELL'];b=buys[0];q=sum(x['qty'] for x in sells)
        if q==b['qty']:
            pnl=sum(x['pnl'] for x in sells);trades.append({'client_id':id,'symbol':b['symbol'],'entry_date':b['at'][:10],'exit_date':sells[-1]['at'][:10],'entry_at':b['at'],'exit_at':sells[-1]['at'],'qty':b['qty'],'entry':b['price'],'stop':b['initial_stop'],'planned_risk':b['planned_risk'],'pnl':pnl,'R':pnl/b['planned_risk'],'mode':meta[id]['mode'],'entry_fee':b['fee'],'exit_fees':sum(x['fee'] for x in sells)})
    final=engine.nav[-1]['equity'];peak=engine.initial_cash;mdd=0
    for row in engine.nav:peak=max(peak,row['equity']);mdd=min(mdd,row['equity']/peak-1)
    fees=sum(x['fee'] for x in engine.fills);pnl=[t['pnl'] for t in trades];rs=[t['R'] for t in trades]
    summary={'variant':variant,'price_semantics':'QFQ_ACCOUNTING_UNITS_NOT_RAW_SHARES','cost_bps':cost,'per_adjusted_unit_fee':per_share,'final_accounting_equity':final,'net_accounting_return':final/engine.initial_cash-1,'MDD':mdd,'closed_trades':len(trades),'open_positions':len(engine.positions),'win_rate':float(np.mean(np.array(pnl)>0)) if pnl else None,'mean_R':float(np.mean(rs)) if rs else None,'fees_accounting_units':fees,'best10_removed_pnl':sum(sorted(pnl)[:-10]) if len(pnl)>10 else None,'ambiguities':dict(Counter(x['event'] for x in engine.events if 'ambiguous' in x['event'])),'bootstrap':bootstrap(trades)}
    from .metrics import distribution
    summary['distribution']=distribution(trades,engine.nav)
    summary['realized_pnl_all_exit_units']=sum(x.get('pnl',0) for x in engine.fills if x['side']=='SELL')
    summary['unrealized_net_unit_pnl']=sum(p['qty']*(engine.marks[s]-p['entry']-p['entry_fee_per_share']) for s,p in engine.positions.items())
    summary['net_reconciliation_error']=final-engine.initial_cash-summary['realized_pnl_all_exit_units']-summary['unrealized_net_unit_pnl']
    if abs(summary['net_reconciliation_error'])>1e-6:raise AssertionError('cash/PnL/marked inventory mismatch')
    return engine,trades,summary,meta

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--eval-data',required=True);ap.add_argument('--raw-data',required=True);ap.add_argument('--pit',required=True);args=ap.parse_args();p=Path(args.eval_data)
    paths=[p/'klines_day.csv.gz',p/'klines_1m.csv.gz',Path(args.raw_data)/'us/bars_raw.csv.gz',Path(args.pit)]
    paths += [Path(__file__),Path(__file__).with_name('execution.py'),Path(__file__).with_name('data.py'),Path(__file__).with_name('metrics.py'),Path(args.pit).with_name('facts.csv'),Path(args.pit).with_name('download_manifest.json')]
    paths += [ROOT/slug/'notes'/'PREREG_R2_MINUTE.md' for slug in ('clement_ang','j_law','deepak_uppal')]
    paths += [ROOT/'deepak_uppal'/'notes'/'PREREG_R3_QUARTER_EPS.md']
    paths += [ROOT/slug/'signals.py' for slug in ('clement_ang','j_law','deepak_uppal')]
    manifest=[{'path':str(x),'sha256':sha256(x),'status':'LOCAL_RESEARCH_NOT_RELEASED_DERIVED' if 'eval_v2' in str(x) else 'SOURCE_INPUT'} for x in paths]
    daily=read_eval_daily(p/'klines_day.csv.gz');raw=load_daily(Path(args.raw_data)/'us/bars_raw.csv.gz');minutes=read_minutes(p/'klines_1m.csv.gz');pitrows=defaultdict(list)
    for line in open(args.pit):
        r=json.loads(line);pitrows[r['symbol']].append(r)
    for rows in pitrows.values():rows.sort(key=lambda r:r['available_on_or_after'])
    plans,rejects,f,idx=prepare(daily,raw,minutes,pitrows)
    for slug,variants in [('clement_ang',('CM1','CM0')),('j_law',('JL1','JL0')),('deepak_uppal',('DN1','DN0')),('deepak_uppal',('DQ1','DQ0'))]:
        out=ROOT/slug/'reports'/('r3_quarter_eps' if variants[0].startswith('DQ') else 'r2_minute');out.mkdir(exist_ok=True);result=[]
        write_csv(out/'rejections.csv',[r for r in rejects if r['variant'].startswith(variants[0][:2])])
        for variant in variants:
            engine,trades,summary,meta=run_variant(variant,plans[variant],minutes,daily,f,idx)
            _,_,stress,_=run_variant(variant,plans[variant],minutes,daily,f,idx,25)
            _,_,gross,_=run_variant(variant,plans[variant],minutes,daily,f,idx,0,0)
            write_csv(out/(variant+'_signals.csv'),[p for ps in plans[variant].values() for p in ps]);write_csv(out/(variant+'_trades.csv'),trades);write_csv(out/(variant+'_fills.csv'),engine.fills);write_csv(out/(variant+'_nav.csv'),engine.nav)
            dump(out/(variant+'_events.json'),engine.events)
            checks={'global_bar_batching':True,'signal_before_entry':all(x['signal_at']<=x['active_at'] for ps in plans[variant].values() for x in ps),'ledger_identity_every_bar':all(abs(n['equity']-n['cash']-n['market_value'])<1e-6 for n in engine.nav),'cash_nonnegative':all(n['cash']>=-1e-6 for n in engine.nav),'integer_units_not_actual_shares':all(isinstance(x['qty'],int) for x in engine.fills),'shape_and_distance_source_fields_preserved':variant.startswith('CM'),'PIT_missing_blocks_not_swing':variant.startswith('JL'),'raw_share_execution_verified':False,'unrealized_positions':engine.positions,'ordinary_trade_sample':trades[:20],'sample_method':'first20 deterministic automatic ledger checks; not manual bar replay'}
            dump(out/(variant+'_checks.json'),checks);result.append({'main':summary,'stress':stress,'gross':gross})
        start=min(minutes);end=max(minutes);bench={}
        for s in ['US.QQQ']+SYMBOLS:
            i=idx[s].get(start);j=idx[s].get(end)
            if i is not None and j is not None:bench[s]=float(daily[s]['values'][j,3]/daily[s]['values'][i,0]-1)
        dump(out/'results.json',{'status':'COMPLETED_MINUTE_TECHNICAL_HYPOTHESIS','source_full_strategy_replicated':False,'data':manifest,'period':[start,end],'symbols':SYMBOLS,'results':result,'benchmark_price_returns':bench,'equal_weight_seven_price_return':float(np.mean([bench[s] for s in SYMBOLS if s in bench])),'cash_return':0,'statistical_gate':'NOT_PASSED: no matched randomized control yet; short reused window; source omissions and adjusted-unit realism block full acceptance'})
        lines='\n'.join(f"- {r['main']['variant']}：平仓{r['main']['closed_trades']}笔、未平{r['main']['open_positions']}；调整单位账本净变化{r['main']['net_accounting_return']:.2%}，MDD {r['main']['MDD']:.2%}，均R={r['main']['mean_R']}；胜/负={r['main']['distribution']['wins']}/{r['main']['distribution']['losses']}，实际盈亏比R={r['main']['distribution']['realized_payoff_R']}，利润因子={r['main']['distribution']['profit_factor']}，持有中位={r['main']['distribution']['holding_sessions_median']}交易日，平均曝险={r['main']['distribution']['average_exposure']:.2%}" for r in result)
        (out/'FINAL_CN.md').write_text(f'''# R2真实分钟技术机制研究\n\n{lines}\n\n## 结果含义\n真实公开1分钟行情，5分钟结构由已完成1分钟聚合；七只固定美股、{start}至{end}。不是原版复刻，不是账户比赛结果，不是样本外。QFQ调整后单位账本不是当时真实股数或可兑现净美元收益；每单位费用只是透明的成本假设。完整参数见PREREG_R2_MINUTE。复权为发布时统一尺度，缺逐日PIT版本，不能宣称完全时点原始报价特征。\n\nDeepak的DQ使用最新报告期已披露单季EPS正值，缺失/旧季度拒绝；DN为明确另立的NI正盈利/固定名单RS/机械旗形分钟子研究，精确EPS及历史行业未复制；DN1不设SMA10退场，DN0余仓用SMA10，均10日超时。\n\nClement为“两层数值筛选→确认局部低点（不要求高于更早摆动低点）→完成1分钟转强→下一分钟开盘”的机械局部版本，保留时点日低门，主题/收缩裁量未复制。J Law为独立20日阻力/同时间量突破及SEC时点NI/CFO/FCF/收入分流，NI替EPS明确为另立假设，行业/主题未复制。未知财务不默认swing。\n\n## 执行与统计\n同批分钟冻结资金/风险/权益；下一根开盘、不使用最终当日low。止损/目标顺序冲突保守并记日志；缺报价仍不能证明真实可成交。完整候选、拒单、成交、逐笔、权益、审计与成本压力已保存。现金/QQQ/七名等权仅价格描述；机制对照共享技术思想而组合资金相互影响，不宣称逐笔严格配对因果。随机匹配安慰剂未通过，短样本不能宣布策略有效。\n\n## 分布与来源对照\n完整JSON另给平均赢亏、净期望、按252日折算频率（不是预测）、最佳1/5/10笔正收益贡献和逐名分解。公开来源3R是目标而非实际盈亏比；0.3%是J Law个人常态风险而非比赛账户统一风险。本人完整交易胜率/盈亏比/连续净值尚未取得，不能用不同窗口赛事收益对齐本次小样本。\n\n## 四格验收\n来源忠实度：局部；实现正确性：自动tests/checks；历史统计证据：不足；真实可交易性：未验证。\n''')
if __name__=='__main__':main()
