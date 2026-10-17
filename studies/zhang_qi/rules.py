"""Independent H-ZQ-TECH price mechanism, never substitute indices for ETFs."""
import math

def eligible_product(metadata, asof):
    """Product identity/listing/sellability; no irrelevant stock-ST or NAV gate."""
    needed={'product_id','kind','sector_etf','sellability'}
    if not needed.issubset(metadata):return False
    listed=metadata.get('listing_date',metadata.get('listed_by_date'))
    return bool(metadata['kind']=='ETF' and metadata['sector_etf'] and listed and listed<=asof and
                metadata['sellability'] in ('T+0','T+1'))

def execution_and_total_return_ready(metadata):
    """Separate certification, not a claim that a verified ETF is ineligible."""
    return all(metadata.get(k,False) for k in ('opening_execution_evidence','fees_verified','cash_distributions_complete'))

def technical_reversal(history):
    # history ends at today's complete close; return rank deliberately excludes today.
    if len(history)<22:return None
    prior_return=history[-2]['close']/history[-22]['close']-1
    confirmation=history[-1]['close']>history[-2]['high'] and history[-2]['close']<=history[-2]['high']
    return {'prior_20d_return':prior_return,'confirmation':confirmation,'signal_low':history[-1]['low']}

def bottom_decile(features, require_confirmation=True):
    if len(features)<10:return []
    ordered=sorted(features,key=lambda k:(features[k]['prior_20d_return'],k))
    cohort=ordered[:max(1,math.ceil(len(ordered)/10))]
    return [k for k in cohort if not require_confirmation or features[k]['confirmation']][:5]

def exit_intent(close, signal_low, held_sessions, fixed_only=False):
    return held_sessions>=5 or (not fixed_only and close<signal_low)
