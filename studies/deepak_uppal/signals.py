"""Deepak source-specific numeric / point-in-time gate."""
def screen(price,sma50,sma200,atr14,rs_percentile,pit,decision_at):
    reasons=[]
    if not sma50>sma200:reasons.append('trend')
    if not price>75:reasons.append('raw_price_not_above_75')
    if not atr14/price>.05:reasons.append('atr_percent_not_above_5')
    if rs_percentile is None or rs_percentile<80:reasons.append('RS_unavailable_or_low')
    if not pit or pit.get('available_at','z')>decision_at:reasons.append('PIT_EPS_unavailable')
    elif pit.get('ttm_diluted_eps') is None or pit['ttm_diluted_eps']<=0:reasons.append('EPS_not_positive_or_unknown')
    if not pit or not pit.get('growth_industry_asof'):reasons.append('PIT_growth_industry_unavailable')
    return {'eligible':not reasons,'reasons':reasons,'source_rule':'D-A1'}

def management(partial=False):
    return {'target_r':3.,'fraction':.5 if partial else 1.,'residual_ma':10 if partial else None,'timeout_sessions':10,'assumption':'full_vs_partial_exit_unknown_in_source'}
