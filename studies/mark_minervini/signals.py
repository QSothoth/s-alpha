"""Mechanical two-contraction technical hypothesis, not complete SEPA."""
def trend(i,c,f):
    return bool(i>=221 and c[i]>f['sma50'][i]>f['sma150'][i]>f['sma200'][i]>f['sma200_prev21'][i])

def daily_candidate(i,c,f):
    return bool(i>=252 and trend(i,c,f) and f['range10'][i]<=.75*f['range10_prev'][i] and f['vol10_prior'][i]<f['vol10_older'][i] and c[i]>f['pivot10'][i])

def vcp_annotations_ok(annotation, decision_at):
    legs=annotation.get('contractions',[])
    return bool(len(legs)>=2 and all(x['end']<=decision_at for x in legs) and all(a['end']<b['start'] and a['depth']>b['depth'] for a,b in zip(legs,legs[1:])) and annotation.get('quality_pass') is True and annotation.get('available_at','z')<=decision_at)
