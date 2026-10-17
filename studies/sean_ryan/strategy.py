"""Sean Ryan source-informed second-wave hypotheses; every numerical shape is H."""
from .daily_engine import rsi,mean

def signal(symbol,h,state,position,candidate,date):
    if len(h)<61:return None,None,None
    b=h[-1];prev=h[:-1];c=b['close'];i=len(h)-1;exit_reason=None;event=None;entry=None
    if position:
        if c<min(x['low'] for x in h[-11:-1]):exit_reason='structure_low10'
        if 'rsi' in candidate and c>=max(x['close'] for x in h[-21:-1]):
            prior=max(range(max(14,len(h)-31),len(h)-5),key=lambda j:h[j]['close'])
            if c>h[prior]['close'] and rsi(h)<rsi(h[:prior+1])-5:exit_reason='H_RSI14_simple_bearish_divergence'
    phase=state.get('phase','flat')
    if phase=='flat':
        # Candidate base then first thrust: no global extrema or future ZigZag.
        base=h[-21:-1];depth=max(x['high'] for x in base)/min(x['low'] for x in base)-1
        if depth<=.30 and c>max(x['high'] for x in base) and b['volume']>=1.5*mean([x['volume'] for x in h[-51:-1]]):
            state.update(phase='first',first_index=i,first_high=b['high'],first_low=min(x['low'] for x in h[-6:]),trough=b['low'])
            event={'event':'first_wave_confirmed','phase':'first','first_high':b['high'],'rsi':rsi(h)}
            if candidate=='S1_first_wave':entry=state['first_low']
    elif phase=='first':
        if i-state['first_index']>25 or c<state['first_low']:
            state['phase']='flat';event={'event':'wave_invalidated','phase':'flat'}
        elif c<state['first_high']*.98:
            state.update(phase='consolidation',consolidation_index=i,trough=min(state['trough'],b['low']))
            event={'event':'consolidation_confirmed','phase':'consolidation'}
        else:state['first_high']=max(state['first_high'],b['high'])
    elif phase=='consolidation':
        state['trough']=min(state['trough'],b['low']);age=i-state['consolidation_index']
        if age>20 or state['trough']<.80*state['first_high']:
            state['phase']='flat';event={'event':'consolidation_invalidated','phase':'flat'}
        elif age>=3 and c>state['first_high']:
            event={'event':'second_wave_confirmed','phase':'second','first_high':state['first_high'],'trough':state['trough']}
            if candidate!='S1_first_wave':entry=state['trough']
            state['phase']='flat'
    return entry,exit_reason,event
