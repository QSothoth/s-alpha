"""Experimental quote-based exit mandate; no inherited live certification."""
from decimal import Decimal

POLICY = {
    'id': 'position_pnl_v1',
    'stop_loss_fraction': 0.30,
    'take_profit_fraction': 1.0,
    'profit_lock_at': 0.50,
    'profit_lock_keep': 0.50,
}


def decide(policy, cost, bid, peak):
    gross_return = Decimal(str(bid)) / Decimal(str(cost)) - 1
    peak = max(Decimal(str(peak)), gross_return)
    reason = None
    if gross_return <= -Decimal(str(policy['stop_loss_fraction'])):
        reason = 'position_stop_loss'
    elif gross_return >= Decimal(str(policy['take_profit_fraction'])):
        reason = 'position_take_profit'
    elif peak >= Decimal(str(policy['profit_lock_at'])) and gross_return <= peak * Decimal(str(policy['profit_lock_keep'])):
        reason = 'position_profit_lock'
    return reason, float(gross_return), float(peak)
