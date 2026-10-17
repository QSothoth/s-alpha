"""Conditional stress arithmetic; not inferred real holdings."""
def stress(qty,price,cash,debt,haircut,limit_returns):
    if qty<0 or price<0 or debt<0 or not 0<=haircut<=1:raise ValueError('invalid input')
    path=[]
    for change in limit_returns:
        if not -1<=change<=1:raise ValueError('invalid scenario')
        price*=1+change
        value=qty*price
        path.append({'price':price,'equity':cash+value-debt,'collateral_buffer':cash+haircut*value-debt,'inventory':qty,'assumed_fill':False})
    return path
