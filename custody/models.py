"""Broker-neutral public input and trusted adapter messages. No network clients."""
from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo
import math

ET = ZoneInfo('America/New_York')


def instant(value):
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError('timezone-aware timestamp required')
    return value


def positive(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        raise ValueError(name + ' must be finite and positive')
    return float(value)


def symbol(value):
    if not isinstance(value, str): raise ValueError('symbol must be a string')
    value = value.upper().removeprefix('US.')
    if not value or len(value) > 12 or any(c not in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ.-' for c in value):
        raise ValueError('invalid underlying symbol')
    return value


@dataclass(frozen=True)
class JobRequest:
    """Public custody input chosen upstream: strategy, underlying, direction, exact option contract.

    * ``trade_action`` restricts the day's mandate to buy/sell, buy-only or sell-only;
    * ``symbol`` supplies the same-day underlying 1m bars used only for timing;
    * success is measured on the option fills, never on an underlying proxy.
    """

    strategy_id: str
    symbol: str
    direction: str
    contract: str
    max_qty: int = 1
    trade_date: str | None = None
    max_entry_premium: float | None = None
    expiry_policy: str = '0_1dte'
    entry_valid_until: str | None = None
    trade_action: str = 'round_trip'

    @classmethod
    def parse(cls, payload, now):
        if not isinstance(payload, dict): raise ValueError('JSON object required')
        allowed = set(cls.__dataclass_fields__)
        if set(payload) - allowed: raise ValueError('unknown fields: ' + ','.join(sorted(set(payload)-allowed)))
        for k in ['strategy_id', 'symbol', 'direction', 'contract']:
            if not isinstance(payload.get(k), str) or not payload[k].strip(): raise ValueError(k + ' required')
        if payload['direction'] not in ('LONG', 'SHORT'): raise ValueError('direction must be LONG or SHORT')
        qty = payload.get('max_qty', 1)
        if type(qty) is not int or qty < 1: raise ValueError('max_qty must be a positive integer')
        day = payload.get('trade_date', instant(now).astimezone(ET).date().isoformat())
        if not isinstance(day, str) or date.fromisoformat(day).isoformat() != day: raise ValueError('ISO trade_date required')
        premium = payload.get('max_entry_premium')
        expiry_policy = payload.get('expiry_policy', '0_1dte')
        trade_action = payload.get('trade_action', 'round_trip')
        if trade_action not in ('round_trip', 'buy_only', 'sell_only'):
            raise ValueError('trade_action must be round_trip, buy_only or sell_only')
        if trade_action == 'sell_only' and (premium is not None or payload.get('entry_valid_until') is not None):
            raise ValueError('sell_only does not accept entry constraints')
        if expiry_policy not in ('0_1dte', 'nearest'):
            raise ValueError('expiry_policy must be 0_1dte or nearest')
        if premium is not None:
            premium = positive(premium, 'max_entry_premium')
        deadline = payload.get('entry_valid_until')
        if deadline is not None:
            deadline = instant(deadline).astimezone(ET)
            if deadline.date().isoformat() != day:
                raise ValueError('entry deadline must be on trade_date')
            deadline = deadline.isoformat()
        return cls(payload['strategy_id'], symbol(payload['symbol']), payload['direction'], payload['contract'].strip(),
                   qty, day, premium, expiry_policy, deadline, trade_action)


@dataclass(frozen=True)
class Contract:
    code: str
    underlying: str
    expiry: str
    right: str
    strike: float
    multiplier: int = 100
    lot_size: int = 1
    currency: str = 'USD'
    tradable: bool = True

    def validate(self, request, nearest_expiry=None):
        if self.code != request.contract or symbol(self.underlying) != request.symbol:
            raise ValueError('resolved contract does not match request')
        days = (date.fromisoformat(self.expiry) - date.fromisoformat(request.trade_date)).days
        if request.trade_action == 'sell_only':
            if days < 0:
                raise ValueError('cannot sell an expired contract')
        elif request.expiry_policy == 'nearest':
            if days < 0 or self.expiry != nearest_expiry:
                raise ValueError('contract must match the verified nearest unexpired expiry')
        elif not 0 <= days <= 1:
            raise ValueError('contract must expire on trade_date or next day (0-1 DTE only)')
        if self.right != ('CALL' if request.direction == 'LONG' else 'PUT'): raise ValueError('contract right/direction mismatch')
        positive(self.strike, 'strike')
        if self.currency != 'USD' or self.tradable is not True: raise ValueError('contract not tradable USD option')
        if type(self.multiplier) is not int or self.multiplier <= 0 or type(self.lot_size) is not int or self.lot_size <= 0:
            raise ValueError('invalid contract sizing metadata')
        if request.max_qty % self.lot_size: raise ValueError('quantity does not match contract lot size')


@dataclass(frozen=True)
class Session:
    day: str
    opens: datetime
    closes: datetime

    def __post_init__(self):
        a, b = instant(self.opens).astimezone(ET), instant(self.closes).astimezone(ET)
        if a.date().isoformat() != self.day or b.date() != a.date() or b <= a:
            raise ValueError('invalid exchange session')


@dataclass(frozen=True)
class Quote:
    contract: str
    bid: float
    ask: float
    as_of: datetime


@dataclass(frozen=True)
class PositionSnapshot:
    """Trusted broker evidence for adopting an existing long position; not a fill."""
    account: str
    mode: str
    contract: str
    quantity: int
    as_of: datetime
    average_cost: float | None = None


@dataclass(frozen=True)
class Frame:
    """One strategy decision on a completed underlying 1m bar (trusted, never HTTP input)."""
    symbol: str
    strategy_hash: str
    bar_close: datetime
    close: float
    action: str
    reason: str | None = None
    diagnostics: dict | None = None


@dataclass(frozen=True)
class OrderUpdate:
    client_order_id: str
    sequence: int
    status: str
    cumulative_qty: int
    as_of: datetime
    underlying_mark: float | None = None
    average_option_price: float | None = None
    first_fill_at: datetime | None = None


class HardSubmitError(RuntimeError):
    """Broker refused the order before accepting it; a new client order id is safe."""


class UnlockRequiredError(HardSubmitError):
    """Live trade unlock is required (or unlock with the env password failed)."""
