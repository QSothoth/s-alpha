"""Detect revision in supplied point-in-time indicator exports."""
def revisions(exports):
    seen={};out=[]
    for x in sorted(exports,key=lambda x:x['observed_at']):
        if x['observed_at'] < x['bar_end']: raise ValueError('future bar observation')
        key=(x['product'],x['bar_end'],x['version'])
        if key in seen and seen[key]!=x['signal']:out.append(key)
        seen[key]=x['signal']
    return out
