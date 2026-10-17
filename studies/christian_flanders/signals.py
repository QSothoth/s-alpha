"""F-S1 preserving 52-week high structure; FD1 is a daily technical sub-study."""
def daily_candidate(i,c,f):
    return bool(i>=252 and c[i]>f['high252'][i] and c[i]>f['sma50'][i] and f['range10'][i]<=f['range10_prev'][i])

def add_size(original_qty, old_qty, entry, price, new_stop, old_stop, equity,cash,max_weight=.2):
    stop=max(old_stop,new_stop)
    qty=original_qty//2
    if price<=entry or qty<=0:return 0,old_stop
    risk=max(0,entry-stop)*old_qty+max(0,price-stop)*qty
    if risk>equity*.0025 or (old_qty+qty)*price>equity*max_weight or qty*price>cash:return 0,old_stop
    return qty,stop
