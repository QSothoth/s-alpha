"""A lower bound from consecutive same-scope position snapshots."""
def turnover_lower_bound(before,after,corporate_actions_known=False):
    if not corporate_actions_known:raise ValueError('corporate actions unknown')
    return sum(abs(after.get(s,0)-before.get(s,0)) for s in set(before)|set(after))

def theme_asof(snapshot,decision_at):
    if snapshot['published_at']>decision_at:raise ValueError('future theme')
    return snapshot['members']
