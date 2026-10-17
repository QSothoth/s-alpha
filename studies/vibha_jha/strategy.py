"""ETF close-confirmed partial study. Growth and capital rotation intentionally gated."""
from studies.sean_ryan.daily_engine import mean

def signal(symbol,h,state,position,candidate,date):
    if symbol!='TQQQ' or len(h)<61:return None,None,None
    c=h[-1]['close'];ma=mean([x['close'] for x in h[-50:]]);oldma=mean([x['close'] for x in h[-51:-1]])
    # Two-bar-confirmed local low, made available only after right-side bars close.
    j=len(h)-3
    if all(h[j]['low']<h[k]['low'] for k in (j-2,j-1,j+1,j+2)):
        state.setdefault('lows',[]).append(h[j]['low']);state['lows']=state['lows'][-2:]
    higher=len(state.get('lows',[]))==2 and state['lows'][-1]>state['lows'][-2]
    dist=sum(h[k]['close']<h[k-1]['close']*.998 and h[k]['volume']>h[k-1]['volume'] for k in range(len(h)-20,len(h)))
    enter=(c>ma and h[-2]['close']<=oldma and state.get('market_recovery',False))
    if 'higherlow' in candidate or candidate=='V5_full_cost25':enter=enter and higher
    if candidate=='V1_hold':enter=not state.get('entered',False)
    reason=None
    if position and candidate!='V1_hold' and c<ma:reason='H_ma50_loss'
    if position and ('distribution' in candidate or candidate=='V5_full_cost25') and dist>=4:reason='H_4_distribution_days20'
    event={'event':'ETF_state','ma50':ma,'higherlow':higher,'distribution20':dist}
    if enter:state['entered']=True
    # Hold control deliberately uses a remote stop; other candidates use 15% H stop.
    return (c*.01 if candidate=='V1_hold' else c*.85) if enter else None,reason,event
