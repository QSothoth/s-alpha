"""Descriptive distributions with explicit denominators; no success inference."""
from collections import defaultdict
import numpy as np

def distribution(trades, nav):
    pnl=np.array([t['pnl'] for t in trades],dtype=float);r=np.array([t['R'] for t in trades],dtype=float)
    win=pnl[pnl>0];loss=pnl[pnl<0];wr=r[pnl>0];lr=r[pnl<0]
    days=sorted({str(n.get('date',n.get('at','')))[:10] for n in nav});index={d:i for i,d in enumerate(days)}
    hold=[t.get('bars_held',index[t['exit_date']]-index[t['entry_date']]+1) for t in trades]
    positive=sum(win);totalloss=-sum(loss)
    expo=[n.get('exposure',n.get('market_value',0)/n['equity'] if n.get('equity') else 0) for n in nav]
    by=defaultdict(list)
    for t in trades:by[t['symbol']].append(t)
    return {'count':len(trades),'wins':len(win),'losses':len(loss),'flat':int(sum(pnl==0)),'win_rate':len(win)/len(trades) if trades else None,'mean_win_pnl':float(np.mean(win)) if len(win) else None,'mean_loss_pnl':float(np.mean(loss)) if len(loss) else None,'realized_payoff_pnl':float(np.mean(win)/-np.mean(loss)) if len(win) and len(loss) else None,'mean_win_R':float(np.mean(wr)) if len(wr) else None,'mean_loss_R':float(np.mean(lr)) if len(lr) else None,'realized_payoff_R':float(np.mean(wr)/-np.mean(lr)) if len(wr) and len(lr) else None,'expectancy_pnl':float(np.mean(pnl)) if len(pnl) else None,'expectancy_R':float(np.mean(r)) if len(r) else None,'profit_factor':float(positive/totalloss) if totalloss else None,'window_sessions':len(days),'first_session':days[0] if days else None,'last_session':days[-1] if days else None,'annualized_trade_count_252_session_rate':len(trades)*252/len(days) if days else None,'annualized_count_not_prediction':True,'holding_sessions_median':float(np.median(hold)) if hold else None,'holding_sessions_max':max(hold) if hold else None,'holding_sessions_p90':float(np.quantile(hold,.9)) if hold else None,'average_exposure':float(np.mean(expo)) if expo else None,'max_exposure':max(expo) if expo else None,'max_single_position_weight':max((n.get('max_position_weight',0) for n in nav),default=0),'best_1_positive_pnl_share':float(max(win)/positive) if len(win) else None,'best_5_positive_pnl_share':float(sum(sorted(win)[-5:])/positive) if len(win) else None,'best_10_positive_pnl_share':float(sum(sorted(win)[-10:])/positive) if len(win) else None,'by_symbol':{s:{'trades':len(ts),'pnl':sum(t['pnl'] for t in ts),'mean_R':float(np.mean([t['R'] for t in ts]))} for s,ts in sorted(by.items())},'capacity_qualification':'NOT_VERIFIED: no opening quotes or full order book; volume upper-bound/sizing hypothesis only'}
