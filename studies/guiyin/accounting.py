"""Account identity before inferring strategy."""
def reconcile(cash,positions,liabilities,reported_equity,tolerance=.01):
    calculated=cash+sum(p['qty']*p['mark'] for p in positions)-liabilities
    return {'calculated_equity':calculated,'difference':calculated-reported_equity,'matches':abs(calculated-reported_equity)<=tolerance}

def flow_adjusted_pnl(start,end,deposits,withdrawals):
    return end-start-deposits+withdrawals
