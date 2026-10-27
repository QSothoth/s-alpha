"""Smart buy / smart sell pricing: a limit that starts at the mid and walks to the side that fills.

Pure functions; the service owns state and orders. Prices are per share (the option quote).

``start_price`` (``bid`` / ``mid`` / ``ask``) is the start of the ladder; reprice k sits k x ``chase_step`` of
the way from that start to the side that fills (the ask for a buy, the bid for a sell) and never past it, so
0.25 reaches the far side on the fourth reprice. Urgent triggers go to the far side at once: the deadline,
protection, operator stop, and a sale that leaves weakness (stop below the day's low, a flush, a lost VWAP).
"""
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal

URGENT = {'deadline', 'scheduled_flatten', 'operator_stop', 'protect', 'protect_quote', 'stop_low'}
URGENT_SELL = URGENT | {'spike_down', 'sunk', 'against', 'lose'}   # playbook v2 leaves weakness at once


def tick_size(price):
    """US penny-pilot increments: 0.01 below 3.00, 0.05 from 3.00. A reject on other classes reprices."""
    return Decimal('0.01') if price < 3 else Decimal('0.05')


def urgent(side, reason):
    return reason in (URGENT if side == 'BUY_OPEN' else URGENT_SELL)


def limit_price(ticket, side, bid, ask, attempt, reason=None):
    bid, ask = Decimal(str(bid)), Decimal(str(ask))
    buy = side == 'BUY_OPEN'
    target = ask if buy else bid
    if urgent(side, reason):
        return float(target)
    start = {'bid': bid, 'mid': (bid + ask) / 2, 'ask': ask}[ticket['start_price']]
    share = min(Decimal(1), Decimal(str(ticket['chase_step'])) * attempt)
    price = start + share * (target - start)
    if price != target:  # quotes already sit on the grid; only interior prices are rounded, passively
        tick = tick_size(price)
        price = (price / tick).to_integral_value(ROUND_FLOOR if buy else ROUND_CEILING) * tick
        price = min(price, ask) if buy else max(price, bid)
    return float(price)
