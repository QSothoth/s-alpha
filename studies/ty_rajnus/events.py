"""Non-trading 30% overextension events. No short fills or borrow assumptions."""
import argparse,csv,json,hashlib
from pathlib import Path
from collections import defaultdict
from datetime import datetime,timedelta
from zoneinfo import ZoneInfo
import numpy as np
SYMBOLS='ABM ACLS AII ATEC ATLC BHRB BORR CBIO CBK CECO CENTA CENX CHCI CHPT CWBC'.split()
def events_for_symbol(rows,symbol):
    days=defaultdict(list)
    for row in rows:days[row['end'][:10]].append(row)
    dates=sorted(days);events=[]
    for di,date in enumerate(dates[1:],1):
        bars=days[date];prior=days[dates[di-1]][-1]['close'];cum=0
        for i,b in enumerate(bars):
            cum+=b['close']*b['volume']
            if b['close']>=prior*1.3 and cum>=2e6:
                event={'symbol':symbol,'at':b['end'],'price':b['close'],'prior_observed_session_close':prior,'cum_dollar_A':cum,'borrow_status':'UNKNOWN','is_trade':False,'next_session_date':dates[di+1] if di+1<len(dates) else None}
                for horizon in (5,15,60):
                    wanted=(datetime.fromisoformat(b['end'])+timedelta(minutes=horizon)).isoformat()
                    matches=[r for r in bars[i+1:] if r['end']==wanted]
                    event['forward_price_return_'+str(horizon)+'m']=matches[0]['close']/b['close']-1 if matches else None
                future=bars[i+1:]
                event['remaining_observed_session_max_up_move']=max([r['high']/b['close']-1 for r in future],default=None)
                event['next_observed_session_close_return']=days[dates[di+1]][-1]['close']/b['close']-1 if di+1<len(dates) else None
                events.append(event);break
    return events

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--data',required=True);a=ap.parse_args();events=[];manifest=[];quality=[]
    for symbol in SYMBOLS:
        p=Path(a.data)/(symbol+'_5m.csv');rows=[]
        with open(p) as f:
            for r in csv.DictReader(f):
                end=datetime.fromisoformat(r['Datetime']).astimezone(ZoneInfo('America/New_York'))+timedelta(minutes=5)
                if not '09:35'<=end.strftime('%H:%M')<='16:00':continue
                rows.append({'end':end.isoformat(),**{k:float(r[k.title()]) for k in ('open','high','low','close','volume')}})
        rows.sort(key=lambda r:r['end']);events+=events_for_symbol(rows,symbol)
        manifest.append({'symbol':symbol,'path':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'rows':len(rows)})
        quality.append({'symbol':symbol,'missing_intervals':sum((datetime.fromisoformat(b['end'])-datetime.fromisoformat(c['end'])).total_seconds()!=300 for c,b in zip(rows,rows[1:]) if b['end'][:10]==c['end'][:10])})
    out=Path(__file__).parent/'reports';out.mkdir(exist_ok=True)
    fields=list(dict.fromkeys(k for r in events for k in r)) or ['symbol','at','is_trade','borrow_status']
    with open(out/'events.csv','w') as f:w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(events)
    result={'status':'E1_NONTRADING_EVENT_STUDY','events':len(events),'input_manifest':manifest,'quality':quality,'borrow':'UNKNOWN_ALL','strategy_returns':None,'net_short_profit':None,'universe':'frozen15 contemporaneous small-cap candidates; no PIT float; incomplete acquisition; not whole market','source_statistics':{'published_episode_trades':238,'published_episode_win_rate':.66,'audited_trade_ledger':False,'comparison':'not comparable to price events; no performance fit'},'horizons':{str(h):{'count':len(vals),'mean_price_return':float(np.mean(vals)) if vals else None,'median_price_return':float(np.median(vals)) if vals else None} for h in (5,15,60) if (vals:=[r['forward_price_return_'+str(h)+'m'] for r in events if r['forward_price_return_'+str(h)+'m'] is not None])}}
    (out/'results.json').write_text(json.dumps(result,indent=2,ensure_ascii=False));(out/'FINAL_CN.md').write_text(f'''# Ty Rajnus：过热事件与借券缺口\n\n在固定15个小盘候选、2026-07-21至10-13的真实5分钟数据中识别{len(events)}个“较前观察日收盘上涨至少30%、累计close×volume≥200万美元”的事件；数值是研究者假设。逐事件前瞻5/15/60分钟价格、当日后续不利上冲与下一观察日已输出，缺价保持空值。这里没有卖空成交、没有净收益，也没有默认借券可得。\n\n原节目说明给238笔、66%胜率，但不是审计流水；不能与本事件样本胜率或均值对齐。需要历史locate数量/有效期/费用、borrow利率/召回、强平/停牌、报价和股息负债才可研究可实现卖空收益。公开材料没有精确入场/退出/仓位算法，不能造VWAP策略冒名。\n\n样本为当代名单、不完整抓取、非PIT流通盘；部分5分钟缺失，严格前瞻时点不存在就不插值。融资披露关联尚未完成，不能声称“公开融资过热”组已测试。\n''')
if __name__=='__main__':main()
