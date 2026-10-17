"""Causal price-only H-EC-01 rules; no external trading interface."""
from dataclasses import dataclass

@dataclass(frozen=True)
class Bar:
    open: float
    high: float
    low: float
    close: float
    volume: float

def sma(history, n):
    if len(history) < n or any(b is None for b in history[-n:]):
        return None
    return sum(b.close for b in history[-n:]) / n

def repaired(bars):
    """s-1 through s+3: all five completed market-session bars required."""
    return len(bars) == 5 and all(b is not None for b in bars) and bars[-1].close >= bars[0].close

def pullback(history, market_return, require_pullback=True):
    ma = sma(history, 10)
    return bool(ma and market_return < 0 and (not require_pullback or history[-1].low <= ma <= history[-1].close))

def buy_gate(bar, previous_close, signal_close, eligibility=None):
    if bar is None:
        return 'missing_next_session'
    if bar.open > 1.01 * signal_close:
        return 'gap_above_cap'
    if previous_close and bar.open / previous_close >= 1.045:
        return 'conservative_limit_risk'
    if not eligibility or any(k not in eligibility for k in ('st', 'upper_limit', 'lower_limit', 'buy_allowed')):
        return 'unknown_historical_eligibility'
    if not eligibility['buy_allowed'] or bar.open >= eligibility['upper_limit']:
        return 'buy_not_available'
    return None

def size_order(equity, cash, price):
    """H: 10% marked NAV target, cash bounded, mainland 100-share lots."""
    if min(equity, cash, price) <= 0:
        return 0
    return int(min(.10 * equity, cash) / price / 100) * 100


class Inventory:
    """Small long-only accounting contract, synthetic tests only when eligibility absent."""
    def __init__(self, cash=1000000):
        self.cash = cash
        self.positions = {}
        self.pending = set()

    def buy(self, code, day, price, quantity, eligible):
        if not eligible:
            return 'unknown_historical_eligibility'
        if code in self.positions or len(self.positions) >= 5:
            return 'position_limit'
        if quantity <= 0 or quantity % 100 or price * quantity > self.cash:
            return 'size_or_cash'
        self.cash -= price * quantity
        self.positions[code] = (day, quantity, price)
        return None

    def sell(self, code, day, price, locked=False):
        acquired, qty, cost = self.positions[code]
        self.pending.add(code)
        if day <= acquired:
            return 't_plus_one'
        if locked:
            return 'limit_locked_pending'
        self.cash += qty * price
        del self.positions[code]
        self.pending.discard(code)
        return None

    def equity(self, marks):
        return self.cash + sum(qty * marks[code] for code, (_, qty, _) in self.positions.items())
