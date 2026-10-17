"""Weekend long-base price candidate research; PIT growth/manual selection blocked."""
from datetime import date as Date

def signal(symbol,h,state,position,candidate,date):
    n=126 if '126' in candidate else (20 if 'no_base' in candidate else 63)
    if len(h)<n+2:return None,None,None
    b=h[-1];c=b['close'];entry=None;reason=None;event=None
    if position and c<min(x['low'] for x in h[-11:-1]):reason='H_structure_low10'
    # Friday's completed bar freezes next-week technical watchlist. Holiday-short weeks
    # without Friday are conservatively skipped; no advance holiday-calendar inference.
    if Date.fromisoformat(date).weekday()==4:
        base=h[-n:];high=max(x['high'] for x in base);low=min(x['low'] for x in base);depth=1-low/high
        tight=max(x['high'] for x in h[-10:])/min(x['low'] for x in h[-10:])-1
        # Long duration + bounded depth + two separated visits to upper area.
        early=max(x['high'] for x in base[:n//3])>=.9*high
        recent=max(x['high'] for x in base[-n//3:])>=.9*high
        ok=c>=10 and .08<=depth<=.35 and tight<=.12 and early and recent
        if candidate=='P3_no_base_control':ok=c>=10 and tight<=.12
        state.update(pivot=high,stop=min(x['low'] for x in h[-10:]),selected=ok,freeze_index=len(h)-1)
        event={'event':'weekend_watchlist','selected':ok,'base_sessions':n,'base_depth':depth,'tight10':tight,'pivot':high,'growth_status':'BLOCKED_NO_PIT_FUNDAMENTALS','reason':'technical_pass' if ok else 'price_depth_tightness_or_base_fail'}
    elif state.get('selected') and 0<len(h)-1-state['freeze_index']<=5 and c>state['pivot']:
        entry=state['stop'];state['selected']=False
        event={'event':'frozen_watchlist_breakout','pivot':state['pivot'],'base_sessions':n}
    return entry,reason,event
