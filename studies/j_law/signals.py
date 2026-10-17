"""J Law duration split must be frozen from actually available facts."""
def holding_mode(pit,decision_at,theme_valid):
    fields=('ttm_diluted_eps','ttm_operating_cashflow','ttm_free_cashflow','quarter_revenue_yoy')
    if not pit or pit.get('available_at','z')>decision_at or any(pit.get(k) is None for k in fields):
        return {'mode':None,'reason':'PIT_unavailable','rule':'J-A1'}
    return {'mode':'position' if theme_valid and all(pit[k]>0 for k in fields) else 'swing','rule':'J-A1'}

def volume_gate(completed_cumulative, historical_same_time):
    if len(historical_same_time)<20:return False
    from statistics import median
    return completed_cumulative>1.5*median(historical_same_time[-20:])

def management(mode):
    if mode not in ('swing','position'):raise ValueError('unknown holding mode')
    return {'target_r':3 if mode=='swing' else None,'exit_sma':10 if mode=='swing' else 50,'timeout_sessions':10 if mode=='swing' else 63}
