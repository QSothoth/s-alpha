"""C-S1 numeric screens and causal completed 5m higher-low setup.
Unknown theme, near-high annotations, regime remain explicit external inputs.
"""
def screen(close,sma50,sma200,dollar20,adr20,atr14):
    broad=close>sma50 and close>sma200 and dollar20>=50_000_000 and adr20>=3
    selected=broad and adr20>=4 and (close-sma50)<4*atr14
    return {'broad':bool(broad),'numeric_selected':bool(selected),'source_rule':'C-S1/Q6/Q11','needs':['theme_RS','daily_weekly_contraction','near_high','regime']}

def higher_low_setup(completed, session_date, annotations, tick=.01):
    if len(completed)<3:return {'eligible':False,'reason':'warmup'}
    a,b,c=completed[-3:]
    if c.end[11:16]<'10:00':return {'eligible':False,'reason':'before_1000'}
    if not annotations.get('setup_valid') or annotations.get('regime') not in ('trend','chop'):
        return {'eligible':False,'reason':'missing_prior_annotation'}
    if annotations['available_at']>a.start:return {'eligible':False,'reason':'future_annotation'}
    if not b.low<a.low or not b.low<c.low:return {'eligible':False,'reason':'no_confirmed_higher_low'}
    return {'eligible':True,'created_at':c.end,'trigger':c.high+tick,'stop':b.low-tick,'partial_fraction':1/3 if annotations['regime']=='trend' else .5,'source_rule':'C-A1','requires_trigger_time_low':True}

def trigger_distance_ok(price, observed_day_low, yesterday_atr):
    return 0<=price-observed_day_low<.6*yesterday_atr
