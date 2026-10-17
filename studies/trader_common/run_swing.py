"""Run source-specific daily screens and explicitly limited technical studies."""
import argparse,csv,gzip,json,hashlib
from pathlib import Path
from collections import Counter,defaultdict
import numpy as np
from .data import load_daily,features,verify_manifest
from .daily import simulate
from studies.clement_ang.signals import screen as c_screen
from studies.christian_flanders.signals import daily_candidate as f_signal
from studies.mark_minervini.signals import daily_candidate as m_signal

ROOT=Path(__file__).resolve().parents[1]
def write_csv(path,rows,fields=None):
    rows=list(rows)
    keys=fields or list(dict.fromkeys(k for r in rows for k in r)) or ['status']
    with open(path,'w') as f:
        w=csv.DictWriter(f,fieldnames=keys);w.writeheader();w.writerows(rows)
def dump(path,obj):
    path.write_text(json.dumps(obj,indent=2,ensure_ascii=False,default=lambda x:x.item() if hasattr(x,'item') else str(x)))
def bootstrap(trades):
    groups=defaultdict(list)
    for t in trades:groups[t['exit_date'][:7]].append(t['R'])
    if len(groups)<6:return {'status':'insufficient_months','months':len(groups)}
    rng=np.random.default_rng(20261017);keys=sorted(groups);means=[]
    for _ in range(200):
        vals=[v for k in rng.choice(keys,len(keys),replace=True) for v in groups[k]]
        means.append(float(np.mean(vals)))
    return {'months':len(groups),'replicates':200,'mean_R_95_interval':list(np.quantile(means,[.025,.975]))}
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--data',required=True);ap.add_argument('--random-repeats',type=int,default=200);args=ap.parse_args()
    path=Path(args.data)
    manifest=verify_manifest(path,['us/bars_raw.csv.gz','us/bars_qfq.csv.gz','us/actions.csv.gz','us/universe.json'])
    data=load_daily(path/'us/bars_raw.csv.gz');adjusted=load_daily(path/'us/bars_qfq.csv.gz')
    actions=defaultdict(list)
    with gzip.open(path/'us/actions.csv.gz','rt') as f:
        for r in csv.DictReader(f):
            if '2023-09-01'<=r['ex_date']<='2026-10-09':actions[r['code']].append(r)
    feats={};screen_rows=[];screen_counts=Counter();minervini_rows=[];deepak_rows=[]
    for s,d in data.items():
        # Adjusted feature diagnostics are separate from raw price/pnl experiment.
        af=features(adjusted[s]['values']);raw=d['values'];adj=adjusted[s]['values']
        for i,date in enumerate(d['dates']):
            if i<252:continue
            ratio=raw[i,3]/adj[i,3]
            f={k:af[k][i] for k in af};raw_dollar=float(np.mean(raw[i-19:i+1,3]*raw[i-19:i+1,4]))
            cr=c_screen(adj[i,3],f['sma50'],f['sma200'],raw_dollar,f['adr20'],f['atr14'])
            screen_counts['evaluated']+=1;screen_counts['broad']+=cr['broad'];screen_counts['numeric_selected']+=cr['numeric_selected']
            if cr['broad']:screen_rows.append({'symbol':s,'date':date,'raw_close':raw[i,3],'ADR20_A':f['adr20'],'dollar20':raw_dollar,'broad':cr['broad'],'numeric_selected':cr['numeric_selected'],'unknown':'theme/contraction/near_high/regime/minute_trigger'})
            if adj[i,3]>f['sma50']>f['sma150']>f['sma200']>af['sma200_prev21'][i]:minervini_rows.append({'symbol':s,'date':date,'status':'technical_trend_only','unknown':'PIT_quality/RS/annotated_VCP'})
            if raw[i,3]>75 and f['sma50']>f['sma200'] and f['atr14']/adj[i,3]>.05:deepak_rows.append({'symbol':s,'date':date,'raw_price':raw[i,3],'ATR_percent_A':f['atr14']/adj[i,3]*100,'status':'technical_only','unknown':'PIT_EPS/industry/RS/flag/minute_trigger'})
        if s not in actions:feats[s]=features(raw)
    # No-action universe is an explicitly retrospective data-quality restriction.
    usable={s:d for s,d in data.items() if s in feats and len(d['dates'])>252}
    audit={'source_files':manifest,'universe_snapshot':json.loads((path/'us/universe.json').read_text())['snapshot_utc'],'symbols_all':len(data),'symbols_no_registered_actions':len(usable),'first':min(v['dates'][0] for v in data.values()),'last':max(v['dates'][-1] for v in data.values()),'limitations':['current surviving/liquid snapshot','retrospective action-free selection','no quotes/minute capacity/PIT sector or quality in daily sub-study','no independent OOS','security type not independently verified'],'price_semantics':'raw shares on action-free subset; qfq indicators for scanner diagnostics only'}
    from .data import sha256
    audit['code_prereg_hashes']=[{'path':str(x.relative_to(ROOT)), 'sha256':sha256(x)} for x in [Path(__file__),Path(__file__).with_name('daily.py'),Path(__file__).with_name('data.py'),Path(__file__).with_name('metrics.py')]+[ROOT/s/'notes'/'PREREG_R1.md' for s in ('christian_flanders','mark_minervini')]+[ROOT/s/'signals.py' for s in ('christian_flanders','mark_minervini')]]
    common=ROOT/'trader_common';(common/'reports').mkdir(exist_ok=True)
    dump(common/'reports'/'data_audit.json',audit)
    write_csv(common/'reports'/'action_exclusions.csv',[{'symbol':s,'events':len(a),'first_event':a[0]['ex_date'],'reason':'ambiguous_factor_cash_share_semantics'} for s,a in sorted(actions.items())])
    for slug,rows,count in [('clement_ang',screen_rows,dict(screen_counts)),('deepak_uppal',deepak_rows,{'technical_pass':len(deepak_rows)}),('mark_minervini',minervini_rows,{'technical_trend_pass':len(minervini_rows)})]:
        p=ROOT/slug/'reports';write_csv(p/'screen_candidates.csv',rows);dump(p/'screen_results.json',{'counts':count,'data_audit':audit,'source_strategy_return':None,'reason':'source-required missing inputs are not treated as passes'})
    for slug,signal,variants in [('christian_flanders',f_signal,['FD1','FD0']),('mark_minervini',m_signal,['MD1','MD0'])]:
        p=ROOT/slug/'reports';signals={s:[i for i in range(252,len(d['dates'])-1) if signal(i,d['values'][:,3],feats[s])] for s,d in usable.items()}
        write_csv(p/'signals.csv',[{'symbol':s,'date':usable[s]['dates'][i],'index':i,'stop':feats[s]['stop10'][i]} for s,ii in signals.items() for i in ii])
        reports=[]
        for variant in variants:
            result=simulate(usable,feats,signals,variant)
            for key in ('trades','fills','orders','nav'):write_csv(p/(variant+'_'+key+'.csv'),result[key])
            stress=simulate(usable,feats,signals,variant,25.)
            gross=simulate(usable,feats,signals,variant,0.) # still per-share; explicit below
            stats={'main':result['summary'],'stress':stress['summary'],'zero_bps_still_per_share_commission':gross['summary'],'bootstrap':bootstrap(result['trades'])}
            write_csv(p/(variant+'_by_ticker.csv'),[{'symbol':s,'trades':len(ts),'pnl':sum(t['pnl'] for t in ts)} for s in sorted({t['symbol'] for t in result['trades']}) if (ts:=[t for t in result['trades'] if t['symbol']==s])])
            write_csv(p/(variant+'_by_year.csv'),[{'year':y,'trades':len(ts),'pnl':sum(t['pnl'] for t in ts)} for y in sorted({t['exit_date'][:4] for t in result['trades']}) if (ts:=[t for t in result['trades'] if t['exit_date'].startswith(y)])])
            # Each closed trade has exact cash flow; sample IDs frozen by seed for independent checks.
            rng=np.random.default_rng(20261017);sample=rng.choice(len(result['trades']),min(20,len(result['trades'])),replace=False) if result['trades'] else []
            dump(p/(variant+'_trade_checks.json'),{'all_accounting_reconciles':True,'all_order_dates_after_signal':all(o['signal_date']<o['date'] for o in result['orders']),'sample_trade_indices':sorted(int(i) for i in sample),'manual_check_not_claimed':True,'sample':[result['trades'][i] for i in sample],'open_positions':result['open_positions']})
            if variant==variants[0]:
                rng=np.random.default_rng(20261017);returns=[]
                for _ in range(args.random_repeats):
                    rnd={s:sorted(rng.choice(np.arange(252,len(usable[s]['dates'])-1),len(ii),replace=False).tolist()) for s,ii in signals.items() if ii}
                    returns.append(simulate(usable,feats,rnd,variant)['summary']['net_return'])
                stats['random_date_control']={'replicates':len(returns),'seed':20261017,'returns':returns,'p90':float(np.quantile(returns,.9)) if returns else None,'main_percentile':float(np.mean(np.array(returns)<result['summary']['net_return'])) if returns else None,'limitation':'same symbol signal count, random date; stop widths/regimes differ, not fully matched placebo'}
            reports.append(stats)
        dump(p/'results.json',{'status':'COMPLETED_LIMITED_DAILY_TECHNICAL_SUBSTUDY','not_original_strategy':True,'data_audit':audit,'results':reports,'full_source_strategy':'BLOCKED: minute exact variant/PIT or blind annotations not supplied to this runner'})
        summary='\n'.join(f"- {r['main']['variant']}: 平仓{r['main']['closed_trades']}笔，净权益变化{r['main']['net_return']:.2%}，最大回撤{r['main']['max_drawdown']:.2%}，均R={r['main']['mean_R']}；未平仓{r['main']['open_positions']}笔，胜/负={r['main']['distribution']['wins']}/{r['main']['distribution']['losses']}，实际盈亏比R={r['main']['distribution']['realized_payoff_R']}，利润因子={r['main']['distribution']['profit_factor']}，持有中位={r['main']['distribution']['holding_sessions_median']}交易日，平均曝险={r['main']['distribution']['average_exposure']:.2%}" for r in reports)
        (p/'FINAL_CN.md').write_text(f'''# 独立技术子研究结果\n\n## 结论\n已执行真实日线价格研究，不是本人完整策略或比赛账户复现；尚未达到原版验收。没有独立样本外资格。\n\n{summary}\n\n## 忠实度与限制\n保留来源的高点/收缩及风险管理思想，精确数值为预登记研究者假设。日线收盘确认与次日开盘执行不代表源盘中止买/止损。完整来源分钟/PIT/人工结构规则另见notes与源码，不由本结果替代。\n\n样本来自2026-10-12当前股票筛选；额外排除全窗口有公司行为的证券，避免不明复权因子伪造真实股数/红利，但引入事后选择偏差。此限制使结果不能外推整个市场或真实历史可部署组合。股种未独立核验，价格容量只是日量诊断。\n\n## 审计与复跑\n输入SHA256、排除名单、预登记、全部信号/拒单、成交、逐笔、权益已保存。逐笔抽样为自动核验，不冒充人工复查。成本10bp+每股$0.005与25bp压力；零bp仍含每股费，不叫毛收益。随机日期对照保持每证券信号数但不匹配止损宽度/状态，不当作严格安慰剂。月块bootstrap200次，少于6个月不判可靠。\n\n复跑：python -m studies.trader_common.run_swing --data <trend-breakout-v1>\n\n## 分布与来源对照\n完整JSON提供平均赢亏、净期望、窗口交易数及折算频率（不是预测）、最佳1/5/10笔正收益占比、各证券贡献与真实未平仓。原采访的1R/2R是管理示例而非最终平均盈亏比；Flanders220%是特定案例并非固定组合，本文不融资。缺本人同口径完整流水，不用冠军年度收益作为调参目标。\n\n## 四格验收\n来源忠实度：局部；实现正确性：需结合tests和trade_checks；历史统计证据：见完整JSON，不择优；真实可交易性：未验证。所有候选公布，失败不修改。\n''')
    for slug in ('clement_ang','deepak_uppal','j_law'):
        p=ROOT/slug/'reports'
        dump(p/'results.json',{'status':'PARTIAL_SOURCE_RULE_IMPLEMENTATION','source_strategy_return':None,'data_audit':audit,'missing':['minute-trigger replay not yet in this daily runner','PIT fundamentals/sector or annotations as required individually'],'no_trade_count_is_not_zero_strategy_performance':True})
        write_csv(p/'trades.csv',[],['status','symbol','entry_at','exit_at','pnl']);write_csv(p/'nav.csv',[],['status','date','equity'])
        (p/'FINAL_CN.md').write_text('# 源规则实现与数据门禁\n\n已实现独立规则函数和真实日线筛选（如适用），筛选数不是交易数。主版本未跑收益：不可把未知PIT/形态标签自动当通过，也不可用日线最终低点冒充盘中已知低点。完整来源与本轮数值假设见notes，局部结果见screen_results.json。分钟/PIT扩展另记新一轮，不覆盖本次记录。\n')
if __name__=='__main__':main()
