"""R30 research-only holding/exit overlay; original entry rules are preserved."""
from collections import deque

from custody.engines.zero_dte_timing import ZeroDteTiming, validate_params
from custody.strategy import Decision, session_minute

EXTRA = {'combo_policy', 'combo_period'}


def validate_position(params):
    base = validate_params({k: v for k, v in params.items() if k not in EXTRA})
    policy, period = params.get('combo_policy'), params.get('combo_period')
    if policy not in ('H', 'X', 'HX'):
        raise ValueError('invalid combo_policy')
    if isinstance(period, bool) or not isinstance(period, int) or not 2 <= period <= 10:
        raise ValueError('invalid combo_period')
    return {**base, 'combo_policy': policy, 'combo_period': period}


class BlockConfirmation:
    def __init__(self, period):
        self.period = period
        self.minute = 0
        self.block = []
        self.votes = deque(maxlen=2)
        self.direction = 0

    def update(self, bar, minute, vwap, fast, slow):
        if minute <= self.minute:
            raise ValueError('bars must arrive in increasing minute order')
        if minute != self.minute + 1:
            self.block.clear()
            self.votes.clear()
        if (minute - 1) // self.period != (self.minute - 1) // self.period:
            self.block.clear()
        self.minute = minute
        self.block.append(bar)
        support = 1 if bar.close > vwap and fast > slow else -1 if bar.close < vwap and fast < slow else 0
        if minute % self.period == 0 and len(self.block) == self.period:
            direction = support if support * (bar.close - self.block[0].open) > 0 else 0
            self.votes.append((direction, bar.close))
        self.direction = 0
        if len(self.votes) == 2:
            first, last = self.votes
            if support and first[0] == last[0] == support and support * (last[1] - first[1]) > 0:
                self.direction = support
        return self.direction


class PositionConfirmation(ZeroDteTiming):
    validate = staticmethod(validate_position)

    def __init__(self, params, direction, session, strike):
        checked = validate_position(params)
        super().__init__({k: v for k, v in params.items() if k not in EXTRA}, direction, session, strike)
        self.p.update({k: checked[k] for k in EXTRA})
        self.confirmation = BlockConfirmation(checked['combo_period'])
        self.current_bar = None

    def _observe(self, minute):
        if self.confirmation.minute != minute:
            self.confirmation.update(self.current_bar, minute, self.ind.vwap, self.ind.ema_fast, self.ind.ema_slow)

    def on_bar(self, bar):
        self.current_bar = bar
        decision = super().on_bar(bar)
        self._observe(session_minute(self.session, bar.close_time))
        return decision

    def _entry_reason(self, bar, minute):
        self._observe(minute)
        return super()._entry_reason(bar, minute)

    def _manage(self, minute):
        self._observe(minute)
        same = self.confirmation.direction == self.sign
        policy = self.p['combo_policy']
        original = self.p['take_profit_premium'], self.p['fail_minutes']
        if 'H' in policy and same:
            self.p['take_profit_premium'], self.p['fail_minutes'] = None, 390
        try:
            decision = super()._manage(minute)
        finally:
            self.p['take_profit_premium'], self.p['fail_minutes'] = original
        if decision.action == 'HOLD' and 'X' in policy and self.confirmation.direction == -self.sign:
            self.phase, self.exit_reason = 'EXITING', 'strong_reversal'
            return Decision('EXIT', self.exit_reason, self._diagnostics(minute))
        return decision
