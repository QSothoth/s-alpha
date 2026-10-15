"""R28 research-only confirmation; registered solely in isolated evaluation copies."""
from collections import deque

from custody.engines.zero_dte_timing import ZeroDteTiming, validate_params
from custody.strategy import session_minute

EXTRA = {'confirmation_mode', 'confirmation_count', 'confirmation_window_minutes', 'confirmation_bar_minutes'}


def validate_confirmation(params):
    base = validate_params({k: v for k, v in params.items() if k not in EXTRA})
    mode = params.get('confirmation_mode')
    if mode not in ('window', 'episode', 'higher'):
        raise ValueError('unknown confirmation_mode')
    expected = {'confirmation_mode', 'confirmation_count',
                'confirmation_bar_minutes' if mode == 'higher' else 'confirmation_window_minutes'}
    if set(params) & EXTRA != expected:
        raise ValueError('confirmation parameters do not match mode')
    extra = {k: params[k] for k in expected}
    for name in expected - {'confirmation_mode'}:
        value = extra[name]
        limit = 10 if name == 'confirmation_count' else 60
        if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= limit:
            raise ValueError('invalid ' + name)
    if mode != 'higher' and extra['confirmation_count'] > extra['confirmation_window_minutes']:
        raise ValueError('count exceeds the available minutes')
    if base['entry_confirm_minutes'] != 1 or base['must_enter_by_minute'] is not None:
        raise ValueError('do not stack R27 confirmation or a deadline entry')
    return {**base, **extra}


class MultiConfirmation(ZeroDteTiming):
    validate = staticmethod(validate_confirmation)

    def __init__(self, params, direction, session, strike):
        checked = validate_confirmation(params)
        super().__init__({k: v for k, v in params.items() if k not in EXTRA}, direction, session, strike)
        self.p.update({k: v for k, v in checked.items() if k in EXTRA})
        self.events = deque()
        self.previous_signal = False
        self.votes = deque(maxlen=self.p['confirmation_count'])
        self.block = []
        self.block_id = None
        self.completed_block = None

    def on_bar(self, bar):
        minute = session_minute(self.session, bar.close_time)
        if minute <= self.ind.minute:
            raise ValueError('bars must arrive in increasing minute order')
        if minute != self.ind.minute + 1:
            self.events.clear()
            self.votes.clear()
            self.block.clear()
            self.previous_signal = False
        self.completed_block = None
        if self.p['confirmation_mode'] == 'higher':
            period = self.p['confirmation_bar_minutes']
            bucket = (minute - 1) // period
            if bucket != self.block_id:
                self.block.clear()
                self.block_id = bucket
            self.block.append(bar)
            if minute % period == 0 and len(self.block) == period:
                self.completed_block = (self.block[0].open, bar.close)
        return super().on_bar(bar)

    def _entry_reason(self, bar, minute):
        reason = self._raw_entry_reason(bar, minute)
        s, ind, p = self.sign, self.ind, self.p
        supportive = s * (bar.close - ind.vwap) > 0 and s * (ind.ema_fast - ind.ema_slow) >= 0
        if p['confirmation_mode'] == 'higher':
            if self.completed_block is not None:
                opening, close = self.completed_block
                self.votes.append((s * close, supportive and s * (close - opening) > 0))
            if (reason is not None and len(self.votes) == p['confirmation_count']
                    and all(ok for _, ok in self.votes)
                    and (len(self.votes) == 1 or self.votes[-1][0] > self.votes[0][0])):
                return reason
            return None
        if not supportive:
            self.events.clear()
            self.previous_signal = False
            return None
        while self.events and minute - self.events[0] >= p['confirmation_window_minutes']:
            self.events.popleft()
        signal = reason is not None
        fresh = signal and (p['confirmation_mode'] == 'window' or not self.previous_signal)
        if fresh:
            self.events.append(minute)
        self.previous_signal = signal
        if fresh and len(self.events) >= p['confirmation_count']:
            return reason
        return None
