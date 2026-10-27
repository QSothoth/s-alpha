"""TK1: operator ticket rules replayed on real 0DTE option bars (notes/TK1_PREREG.md).

Reuses the custody evaluator's fill model, flatten, settlement, labels and mirror weighting, and the live
ticket's own exit trigger (``exit_reason`` below, the 2026-10-25 custody ticket rule) on the fill model's sellable price.

    PYTHONUTF8=1 python3 -m studies.us_0dte_picks.ticket_eval select --dataset <train dir> --out <dir>
    PYTHONUTF8=1 python3 -m studies.us_0dte_picks.ticket_eval validate --candidate K? --dataset <dir> [...] --out <dir>
"""
from __future__ import annotations

import argparse
import json
import random
from collections import Counter
from decimal import Decimal
from pathlib import Path

from custody.dataset import Dataset
from custody.evaluate import (PRIMARY_FILL, STRESS_FILLS, label_case, run_benchmark, run_strategy, simulate,
                              summarize)
from custody.models import instant
from custody.registry import Registry
from custody.strategy import Decision, build_strategy, flatten_minute, session_minute

# The 2026-10-25 operator-ticket exits, kept here verbatim for TK1-TK7 after custody moved to atomic smart orders.
TICKET_DEFAULTS = {'take_profit_price': None, 'take_profit_pct': None, 'stop_loss_price': None, 'stop_loss_pct': None,
                   'trail_after_pct': None, 'trail_keep': None, 'exit_at': None}


def gain(cost, bid):
    return None if cost is None or bid is None else float(Decimal(str(bid)) / Decimal(str(cost)) - 1)


def exit_reason(ticket, cost, bid, now, peak=None):
    if bid is None:
        return 'ticket_exit_at' if ticket['exit_at'] is not None and instant(now) >= instant(ticket['exit_at']) else None
    bid = Decimal(str(bid))
    cost = None if cost is None else Decimal(str(cost))
    stops = [Decimal(str(ticket['stop_loss_price']))] if ticket['stop_loss_price'] is not None else []
    targets = [Decimal(str(ticket['take_profit_price']))] if ticket['take_profit_price'] is not None else []
    if cost is not None and ticket['stop_loss_pct'] is not None:
        stops.append(cost * (1 - Decimal(str(ticket['stop_loss_pct']))))
    if cost is not None and ticket['take_profit_pct'] is not None:
        targets.append(cost * (1 + Decimal(str(ticket['take_profit_pct']))))
    if stops and bid <= max(stops):
        return 'ticket_stop_loss'
    if targets and bid >= min(targets):
        return 'ticket_take_profit'
    if (ticket['trail_after_pct'] is not None and cost is not None and peak is not None
            and peak >= ticket['trail_after_pct'] and gain(cost, bid) <= ticket['trail_keep'] * peak):
        return 'ticket_trail'
    if ticket['exit_at'] is not None and instant(now) >= instant(ticket['exit_at']):
        return 'ticket_exit_at'
    return None

FLATTEN = {'flatten_before_close_minutes': 15}
V66 = 'zero_dte_timing_v6.6'
V66_DEVELOPED_THROUGH = '2026-09-18'
TK1 = {
    'K1': {'entry': 15, 'take_profit_pct': 0.5, 'stop_loss_pct': 0.3, 'exit_minute': 360},
    'K2': {'entry': 15, 'take_profit_pct': 1.0, 'stop_loss_pct': 0.5, 'exit_minute': None},
    'K3': {'entry': 60, 'take_profit_pct': 1.0, 'stop_loss_pct': 0.5, 'exit_minute': None},
    'K4': {'entry': V66, 'take_profit_pct': 1.0, 'stop_loss_pct': 0.5, 'exit_minute': None},
    'K5': {'entry': V66, 'take_profit_pct': 0.5, 'stop_loss_pct': 0.3, 'exit_minute': 360},
}
TK2 = {
    'A1': {'entry': V66, 'take_profit_pct': None, 'stop_loss_pct': 0.5, 'exit_minute': None},
    'A2': {'entry': V66, 'take_profit_pct': 3.0, 'stop_loss_pct': 0.5, 'exit_minute': None},
    'A3': {'entry': V66, 'take_profit_pct': None, 'stop_loss_pct': 0.5, 'exit_minute': None,
           'trail_after_pct': 1.0, 'trail_keep': 0.5},
    'A4': {'entry': V66, 'take_profit_pct': None, 'stop_loss_pct': 0.7, 'exit_minute': None},
    'A5': {'entry': V66, 'take_profit_pct': None, 'stop_loss_pct': 0.5, 'exit_minute': None,
           'trail_after_pct': 2.0, 'trail_keep': 0.5},
}
OFF = {'breakeven_at_atr': 50.0, 'fail_minutes': 390, 'trail_activate_atr': 50.0, 'take_profit_premium': None,
       'profit_lock_at': None, 'profit_lock_keep': None}
TK3 = {
    'B1': {'engine': OFF},
    'B2': {'engine': {**OFF, 'breakeven_at_atr': 2.0}},
    'B3': {'engine': {**OFF, 'trail_activate_atr': 5.0}},
    'B4': {'engine': {**OFF, 'take_profit_premium': 3.0}},
    'B5': {'engine': {**OFF, 'fail_minutes': 10}},
}
B2 = TK3['B2']['engine']
TK4 = {
    'C1': {'engine': {**B2, 'persist_minutes': 15}},
    'C2': {'engine': {**B2, 'min_breakout_volume_ratio': 1.5}},
    'C3': {'engine': {**B2, 'entry_confirm_minutes': 2}},
    'C4': {'engine': {**B2, 'min_close_location': 0.75}},
    'C5': {'engine': {**B2, 'opening_minutes': 30}},
}
TK5 = {
    'D1': {'orb': 30, 'stop': 'opposite'},
    'D2': {'orb': 30, 'stop': 'mid'},
    'D3': {'orb': 30, 'stop': 'opposite', 'inplay': True},
    'D4': {'engine': {**B2, 'opening_minutes': 30}, 'inplay': True},
    'D5': {'orb': 30, 'stop': 'opposite', 'vwap': True},
}
TK6 = {
    'E1': {'orb': 30, 'stop': 'atr'},
    'E2': {'orb': 15, 'stop': 'swing'},
    'E3': {'orb': 30, 'stop': 'swing'},
    'E4': {'orb': 30, 'stop': 'swing', 'inplay': True},
    'E5': {'orb': 60, 'stop': 'swing'},
}
TK7 = {
    'F1': {'entry': V66, 'take_profit_pct': 1.0, 'stop_loss_pct': None, 'exit_minute': None},
    'F2': {'entry': V66, 'take_profit_pct': 2.0, 'stop_loss_pct': None, 'exit_minute': None},
    'F3': {'entry': V66, 'take_profit_pct': None, 'stop_loss_pct': None, 'exit_minute': None,
           'trail_after_pct': 1.0, 'trail_keep': 0.7},
    'F4': {'entry': V66, 'take_profit_pct': None, 'stop_loss_pct': None, 'exit_minute': None,
           'trail_after_pct': 0.5, 'trail_keep': 0.6},
    'F5': {'entry': V66, 'take_profit_pct': 2.0, 'stop_loss_pct': None, 'exit_minute': None,
           'trail_after_pct': 0.5, 'trail_keep': 0.6},
    'H0': {'entry': V66, 'take_profit_pct': None, 'stop_loss_pct': None, 'exit_minute': None},
}
# TK8 (notes/TK8_PREREG.md): a lock line that ratchets up with the peak gain; v6.6 entry, -50% stop, no target.
RATCHET = {'entry': V66, 'take_profit_pct': None, 'stop_loss_pct': 0.5, 'exit_minute': None}
TK8 = {
    'G1': {**RATCHET, 'ratchet': 'ladder'},
    'G2': {**RATCHET, 'ratchet': 'progressive'},
    'G3': {**RATCHET, 'ratchet': 'ladder', 'climax': True},
    'G4': {**RATCHET, 'ratchet': 'ladder', 'late_keep': 0.8},
    'G5': {**RATCHET, 'ratchet': 'ema'},
}
CLIMAX_AFTER, CLIMAX_RISE, CLIMAX_BARS, LATE_MINUTE, EMA_BARS = 1.0, .15, 3, 300, 9
# TK10 (notes/TK10_PREREG.md): how to buy after the signal, on TK8's exit if TK8 passed, else A2.
TK10_EXIT = 'A2'
TK10 = {
    'J0': {'entry_wait': None},
    'J1': {'entry_wait': 'no_chase', 'wait_minutes': 5},
    'J2': {'entry_wait': 'dip', 'wait_minutes': 10},
    'J3': {'entry_wait': 'pullback', 'wait_minutes': 5},
}
NO_CHASE_RISE, NO_CHASE_GUARD, DIP = .20, 1.20, .95
# TK9 (notes/TK9_PREREG.md): exits borrowed from crypto intraday bots (Freqtrade, Hummingbot).
TK9 = {
    'R1': {**RATCHET, 'roi': True},
    'R2': {**RATCHET, 'take_profit_pct': 3.0, 'time_limit': 120},
    'R3': {**RATCHET, 'price_trail': (1.0, .75)},
    'R4': {**RATCHET, 'chandelier': (.5, 3.0, 14)},
    'R5': {**RATCHET, 'roi': True, 'price_trail': (1.0, .75)},
}
ROI_TABLE, ROI_FLAT_MINUTE = ((120, .5), (60, 1.0), (30, 2.0), (0, 3.0)), 330   # held minutes -> target
TK9_TK8_REFERENCE = 'A2'   # TK8's most picked candidate (tk8_select.json: A2 in all 40 folds)
# TK11 (notes/TK11_PREREG.md): corrected yardstick; new candidates trail the underlying, as crypto bots do.
TK11_NEW = {
    'U1': {**RATCHET, 'under_trail': (3.0, None)},
    'U2': {**RATCHET, 'under_trail': (2.0, None)},
    'U3': {**RATCHET, 'under_trail': (1.0, 2.0)},
    'U4': {**RATCHET, 'under_trail': (3.0, None), 'roi': True},
    'U5': {**RATCHET, 'under_trail': (3.0, None), 'stop_loss_pct': None},
}
UNDER_ATR_BARS = 14
TK11_POOL = ['A2', 'K4', 'A3', 'G1', 'G2', 'G3', 'G4', 'G5', 'R1', 'R2', 'R3', 'R4', 'R5', 'U1', 'U2', 'U3', 'U4', 'U5']
FIXED_EXITS = {'A2', 'K4'}


def _contract(take_profit, steps=()):
    return {**RATCHET, 'take_profit_pct': take_profit, 'ratchet': 'steps' if steps else None, 'steps': list(steps)}


# TK12 (notes/TK12_PREREG.md): a position of 2 or 3 contracts, one exit rule per contract.
TK12 = {
    'P2A': [_contract(1.0), _contract(3.0, [(1.0, 0.0)])],
    'P2B': [_contract(1.0), TK8['G4']],
    'P3A': [_contract(1.0), _contract(2.0, [(1.0, 0.0)]), TK8['G4']],
    'P3B': [_contract(.5), _contract(1.0, [(.5, 0.0)]), _contract(3.0, [(.5, 0.0)])],
    'P3C': [_contract(1.0), _contract(2.0, [(1.0, 0.0)]), _contract(3.0, [(1.0, 0.0), (2.0, 1.0)])],
}
TK12_GROUPS = {'two': ['P2A', 'P2B', 'A2', 'G4'], 'three': ['P3A', 'P3B', 'P3C', 'A2', 'G4']}
# TK13 (notes/TK13_PREREG.md): every sale and the rest's stop follow the price action; no fixed profit target.
STRUCTURE_MINUTES, SWING_BARS = 15, 3


def _leg(sell_on_event=None, trail=None):
    return {**RATCHET, 'pa': {'sell_on_event': sell_on_event, 'trail': trail}}


TK13 = {
    'S1': [_leg(trail='ema')],
    'S2': [_leg(1), _leg(trail='ema')],
    'S3': [_leg(1), _leg(2), _leg(trail='ema')],
    'S4': [_leg(1), _leg(trail='swing')],
    'S5': [_leg(1), _leg(trail='swing'), _leg(trail='vwap')],
}
BREAKEVEN_R, TRAIL_R = 1.0, 2.0


def _r_leg(sell_at_r=None, trail=None):
    return {**RATCHET, 'rm': {'sell_at_r': sell_at_r, 'trail': trail}}


# TK14 (notes/TK14_PREREG.md): strength and breakeven measured in R = entry to structure stop of the underlying.
TK14 = {
    'T1': [_r_leg(trail='ema')],
    'T2': [_r_leg(2.0), _r_leg(trail='ema')],
    'T3': [_r_leg(2.0), _r_leg(4.0), _r_leg(trail='ema')],
    'T4': [_r_leg(2.0), _r_leg(trail='swing')],
    'T5': [_r_leg(2.0), _r_leg(trail='swing'), _r_leg(trail='ema')],
}
TK14_GROUPS = {'one': ['T1', 'A2', 'G4'], 'two': ['T2', 'T4', 'P2A', 'P2B', 'A2', 'G4'],
               'three': ['T3', 'T5', 'P3A', 'P3B', 'P3C', 'A2', 'G4']}
TK13_GROUPS = {'one': ['S1', 'A2', 'G4'], 'two': ['S2', 'S4', 'P2A', 'P2B', 'A2', 'G4'],
               'three': ['S3', 'S5', 'P3A', 'P3B', 'P3C', 'A2', 'G4']}
INPLAY_MINUTES, INPLAY_TOP = 30, 4
INPLAY = set()   # (symbol, trade_date) in the day's top INPLAY_TOP by opening-range width; set by evaluate()
ROUNDS = {'TK1': (TK1, []), 'TK2': (TK2, ['K4']), 'TK3': (TK3, ['A2']), 'TK4': (TK4, ['B2']), 'TK5': (TK5, ['B2']),
          'TK6': (TK6, ['B2']), 'TK7': (TK7, ['K4', 'A2', 'A3']), 'TK8': (TK8, ['A2', 'K4', 'A3']), 'TK10': (TK10, []),
          'TK9': (TK9, list(dict.fromkeys(['A2', 'K4', TK9_TK8_REFERENCE])))}
LODO_ROUNDS = {'TK4': ['B2', 'C1', 'C2', 'C3', 'C4', 'C5'], 'TK5': ['B2', 'D1', 'D2', 'D3', 'D4', 'D5'],
               'TK6': ['B2', 'E1', 'E2', 'E3', 'E4', 'E5'],
               'TK7': ['F1', 'F2', 'F3', 'F4', 'F5', 'K4', 'A2', 'A3', 'H0'],
               'TK8': ['G1', 'G2', 'G3', 'G4', 'G5', 'A2', 'K4', 'A3'],
               'TK9': list(dict.fromkeys(['R1', 'R2', 'R3', 'R4', 'R5', 'A2', 'K4', TK9_TK8_REFERENCE]))}
PREMISE_ROUNDS = {'TK7', 'TK8', 'TK9'}   # user premise: direction comes from the user's own selection; score at 60% hit rate
TARGETED_ROUNDS = {'TK5', 'TK6'}   # judged by notes/TK_TARGETS_CN.md   # round -> (candidates, earlier winners shown as references)
CANDIDATES = {**TK1, **TK2, **TK3, **TK4, **TK5, **TK6, **TK7, **TK8, **TK9, **TK11_NEW}
ROUNDS['TK11'] = ({name: CANDIDATES.get(name, {}) for name in TK11_POOL}, [])
ROUNDS['TK12'] = ({}, [])
ROUNDS['TK13'] = ({}, [])
ROUNDS['TK14'] = ({}, [])
CANDIDATES.update({name: {**CANDIDATES[TK10_EXIT], **spec} for name, spec in TK10.items()})
TK2_MIN_PAYOFF = 3.0
BOOTSTRAP_DRAWS = 500
PASS_MAX_BREAKEVEN, PASS_MIN_PAYOFF = 0.55, 2.0


class TicketEngine:
    """Enter at a fixed minute or on the v6.6 signal; exit on the ticket's trigger, judged per option bar."""

    def __init__(self, spec, data, fill, registry):
        self.spec, self.data, self.fill = spec, data, fill
        self.session = data.session
        self.options = {session_minute(self.session, b.close_time): b for b in data.option}
        self.signal = (build_strategy(registry.get(V66), data.case.direction, self.session, data.case.strike)
                       if spec['entry'] == V66 else None)
        exit_at = None
        if spec['exit_minute'] is not None:
            from datetime import timedelta
            exit_at = (self.session.opens + timedelta(minutes=spec['exit_minute'])).isoformat()
        self.ticket = dict(TICKET_DEFAULTS, take_profit_pct=spec['take_profit_pct'],
                           stop_loss_pct=spec['stop_loss_pct'], trail_after_pct=spec.get('trail_after_pct'),
                           trail_keep=spec.get('trail_keep'), exit_at=exit_at)
        self.phase, self.cost, self.reason, self.peak = 'FLAT', None, None, None
        self.sells, self.asks = [], []           # sellable / buyable price of every option bar so far
        self.sign = 1.0 if data.case.direction == 'LONG' else -1.0
        self.ema, self.below_ema = None, False   # directional 5-minute close vs its EMA9 (G5)
        self.signal_minute = self.signal_ask = None
        self.spike = False
        self.fill_minute, self.high, self.ranges, self.last_close = None, None, [], None   # TK9
        self.box_hi = self.box_lo = self.close5 = None   # TK11: directional 5-minute bars of the underlying
        self.true_ranges, self.under_high, self.under_entry = [], None, None
        self.lows, self.lows5, self.pv, self.volume = [], [], 0.0, 0.0   # TK13: structure, swing lows, VWAP
        self.structure, self.events, self.armed, self.rearm_above = None, 0, True, None
        self.r_unit, self.dir_close, self.prev_dir_close = None, None, None   # TK14

    def _five_minute(self, bar, minute):
        hi, lo = (bar.high, bar.low) if self.sign > 0 else (-bar.low, -bar.high)
        self.box_hi = hi if self.box_hi is None else max(self.box_hi, hi)
        self.box_lo = lo if self.box_lo is None else min(self.box_lo, lo)
        self.lows.append((minute, lo))
        self.prev_dir_close, self.dir_close = self.dir_close, self.sign * bar.close
        self.pv += bar.close * bar.volume
        self.volume += bar.volume
        if minute % 5:
            return
        close = self.sign * bar.close
        prev = close if self.close5 is None else self.close5
        self.true_ranges.append(max(self.box_hi, prev) - min(self.box_lo, prev))
        self.lows5.append(self.box_lo)
        self.close5, self.box_hi, self.box_lo = close, None, None
        self.ema = close if self.ema is None else self.ema + 2 / (EMA_BARS + 1) * (close - self.ema)
        self.below_ema = close < self.ema

    def under_reason(self, bar):
        """TK11: trail the underlying's directional high by a multiple of its 5-minute ATR(14)."""
        if not self.spec.get('under_trail'):
            return None
        mult, activate = self.spec['under_trail']
        recent = self.true_ranges[-UNDER_ATR_BARS:]
        atr = sum(recent) / len(recent) if recent else 0.0
        if atr <= 0 or (activate is not None and self.under_high - self.under_entry < activate * atr):
            return None
        return 'ticket_under_trail' if self.sign * bar.close <= self.under_high - mult * atr else None

    def _strength_event(self, bid):
        """TK13: a spike in the option while in profit, then the first bar that does not rise; one per new high."""
        if bid is None:
            return
        if not self.armed and bid > self.rearm_above:
            self.armed = True
        if not self.armed or len(self.sells) < CLIMAX_BARS + 2 or gain(self.cost, bid) <= 0:
            return
        prev, base = self.sells[-2], self.sells[-2 - CLIMAX_BARS]
        if prev / base - 1 >= CLIMAX_RISE and bid <= prev:
            self.events += 1
            self.armed, self.rearm_above = False, prev

    def action_reason(self, minute, bid, bar):
        """TK13: sell into strength on the k-th event; structure stop before the first, then breakeven + trail."""
        pa = self.spec.get('pa')
        if not pa:
            return None
        self._strength_event(bid)
        close = self.sign * bar.close
        if pa['sell_on_event'] is not None and self.events >= pa['sell_on_event']:
            return 'ticket_strength'
        if self.events == 0:
            return 'ticket_structure_stop' if self.structure is not None and close < self.structure else None
        if bid is not None and gain(self.cost, bid) <= 0:
            return 'ticket_ratchet'
        trail = pa['trail']
        if trail == 'ema' and minute % 5 == 0 and self.below_ema:
            return 'ticket_ema_trail'
        prior = self.lows5[:-1] if minute % 5 == 0 else self.lows5   # not the 5-minute bar this minute belongs to
        if trail == 'swing' and prior and close < min(prior[-SWING_BARS:]):
            return 'ticket_swing_trail'
        if trail == 'vwap' and self.volume > 0 and close < self.sign * self.pv / self.volume:
            return 'ticket_vwap_trail'
        return None

    def r_reason(self, minute):
        """TK14: structure stop, breakeven after 1R, sell into strength after kR, trail the runner after 2R."""
        rm = self.spec.get('rm')
        if not rm or self.r_unit is None:
            return None
        close, entry = self.dir_close, self.under_entry
        progress = (self.under_high - entry) / self.r_unit
        if (rm['sell_at_r'] is not None and progress >= rm['sell_at_r'] and self.prev_dir_close is not None
                and close <= self.prev_dir_close):
            return 'ticket_r_strength'
        if progress < BREAKEVEN_R:
            if self.structure is not None and close < self.structure:
                return 'ticket_structure_stop'
        elif close < entry:
            return 'ticket_breakeven'
        if progress < TRAIL_R:
            return None
        if rm['trail'] == 'ema' and minute % 5 == 0 and self.below_ema:
            return 'ticket_ema_trail'
        prior = self.lows5[:-1] if minute % 5 == 0 else self.lows5
        if rm['trail'] == 'swing' and prior and close < min(prior[-SWING_BARS:]):
            return 'ticket_swing_trail'
        return None

    def _start_wait(self, minute, ask):
        """TK10: the signal bar; remember its buyable price and whether the option is spiking into it."""
        self.signal_minute, self.signal_ask = minute, ask
        seen = self.asks[-(CLIMAX_BARS + 1):]
        self.spike = ask is not None and len(seen) == CLIMAX_BARS + 1 and seen[-1] / seen[0] - 1 >= NO_CHASE_RISE
        return 'WAITING' if ask is not None else 'ENTERING'

    def _wait_done(self, minute, ask):
        """TK10: act on this bar once the buy rule allows it; the deadline always acts."""
        rule = self.spec['entry_wait']
        if minute >= self.signal_minute + self.spec['wait_minutes'] or (rule == 'no_chase' and not self.spike):
            return True
        if ask is None:
            return False
        prev = self.asks[-2] if len(self.asks) >= 2 else None
        if rule == 'no_chase':
            return ask >= NO_CHASE_GUARD * self.signal_ask or (prev is not None and ask < prev)
        if rule == 'dip':
            return ask <= DIP * self.signal_ask
        return prev is not None and ask < prev

    def lock_line(self, minute):
        """TK8: the gain at or below which the position is sold; None until the peak reaches +50%."""
        kind, peak = self.spec.get('ratchet'), self.peak
        if kind == 'steps':   # TK12: the rest of a position steps its stop up as earlier contracts are sold
            hit = [lock for at, lock in self.spec['steps'] if peak is not None and peak >= at]
            return (max(hit) if hit else None), False
        if kind is None or peak is None or peak < .5:
            return None, False
        line = 0.0
        if kind == 'ladder' and peak >= 1:
            line = .5 if peak < 2 else 1.0 if peak < 3 else float(int(peak + 1e-9) - 1)
        elif kind == 'progressive' and peak >= 1:
            line = (.5 if peak < 2 else .6 if peak < 3 else .7) * peak
        late = self.spec.get('late_keep') is not None and minute >= LATE_MINUTE and self.spec['late_keep'] * peak > line
        return (self.spec['late_keep'] * peak if late else line), late

    def ratchet_reason(self, minute, bid):
        if bid is None:
            return None
        line, late = self.lock_line(minute)
        if line is not None and gain(self.cost, bid) <= line:
            return 'ticket_late_trail' if late else 'ticket_ratchet'
        if self.spec.get('climax') and self.peak >= CLIMAX_AFTER and len(self.sells) >= CLIMAX_BARS + 2:
            prev, base = self.sells[-2], self.sells[-2 - CLIMAX_BARS]
            if prev / base - 1 >= CLIMAX_RISE and bid <= prev:
                return 'ticket_climax'
        if (self.spec.get('ratchet') == 'ema' and minute % 5 == 0 and self.peak >= 1 and self.below_ema):
            return 'ticket_ema_trail'
        return None

    def crypto_reason(self, minute, bid):
        """TK9: time-decaying target, time limit, price trail after an offset, chandelier."""
        spec = self.spec
        if spec.get('time_limit') is not None and minute - self.fill_minute >= spec['time_limit']:
            return 'ticket_time_limit'
        if bid is None:
            return None
        g = gain(self.cost, bid)
        if spec.get('roi'):
            held = minute - self.fill_minute
            target = 0.0 if minute >= ROI_FLAT_MINUTE else next(t for start, t in ROI_TABLE if held >= start)
            if g >= target:
                return 'ticket_roi'
        if spec.get('price_trail') and self.peak >= spec['price_trail'][0] and bid <= spec['price_trail'][1] * self.high:
            return 'ticket_price_trail'
        if spec.get('chandelier') and self.peak >= spec['chandelier'][0]:
            _, mult, bars = spec['chandelier']
            recent = self.ranges[-bars:]
            atr = sum(recent) / len(recent) if recent else 0.0
            if atr > 0 and bid <= self.high - mult * atr:   # no range yet: no trail defined
                return 'ticket_chandelier'
        return None

    def on_bar(self, bar):
        minute = session_minute(self.session, bar.close_time)
        option = self.options.get(minute)
        bid = self.fill.sell(option) if option is not None else None
        ask = self.fill.buy(option) if option is not None else None
        if option is not None:
            self.sells.append(bid)
            self.asks.append(ask)
            prev = option.close if self.last_close is None else self.last_close
            self.ranges.append(max(option.high, prev) - min(option.low, prev))
            self.last_close = option.close
        self._five_minute(bar, minute)
        if self.phase == 'FLAT':
            if self.signal is not None:
                decision = self.signal.on_bar(bar)
                self.reason = decision.reason if decision.action == 'ENTER' else None
            elif minute >= self.spec['entry']:
                self.reason = 'ticket_entry'
            if self.reason:
                self.phase = self._start_wait(minute, ask) if self.spec.get('entry_wait') else 'ENTERING'
        if self.phase == 'WAITING' and self._wait_done(minute, ask):
            self.phase = 'ENTERING'
        if self.phase == 'ENTERING':
            return Decision('ENTER', self.reason)
        if self.phase == 'IN':
            if bid is not None:
                self.peak = max(self.peak if self.peak is not None else -1.0, gain(self.cost, bid))
                self.high = max(self.high or bid, bid)
            high = self.sign * (bar.high if self.sign > 0 else bar.low)
            self.under_high = high if self.under_high is None else max(self.under_high, high)
            reason = (exit_reason(self.ticket, self.cost, bid, bar.close_time, self.peak)
                      or self.action_reason(minute, bid, bar) or self.r_reason(minute) or self.ratchet_reason(minute, bid)
                      or self.crypto_reason(minute, bid) or self.under_reason(bar))
            if reason:
                self.phase = 'EXITING'
                self.reason = reason
        if self.phase == 'EXITING':
            return Decision('EXIT', self.reason)
        return Decision('HOLD' if self.phase == 'IN' else 'WAIT')

    def on_entry_filled(self, at, underlying_mark):
        self.phase = 'IN'
        self.fill_minute = session_minute(self.session, at)
        self.under_entry = self.sign * underlying_mark
        before = [lo for m, lo in self.lows if self.fill_minute - STRUCTURE_MINUTES <= m < self.fill_minute]
        self.structure = min(before) if before else None
        recent = self.true_ranges[-UNDER_ATR_BARS:]
        atr = sum(recent) / len(recent) if recent else 0.0
        risk = max(self.under_entry - self.structure if self.structure is not None else 0.0, atr)
        self.r_unit = risk if risk > 0 else None
        self.cost = self.fill.buy(self.options[self.fill_minute])


class Never:
    def on_bar(self, bar):
        return Decision('WAIT')


class OrbEngine:
    """Opening-range breakout on completed underlying 1m closes; structure stop, breakeven at 2R, hold to flatten."""

    def __init__(self, spec, data, force_minute=None):
        self.spec, self.session, self.force = spec, data.session, force_minute
        self.sign = 1 if data.case.direction == 'LONG' else -1
        self.ext = self.opp = None
        self.pv = self.volume = 0.0
        self.ranges, self.lows, self.prev_close = [], [], None
        self.phase, self.stop, self.entry, self.best, self.risk, self.reason = 'FLAT', None, None, None, None, None

    def on_bar(self, bar):
        minute, s = session_minute(self.session, bar.close_time), self.sign
        hi, lo, close = max(s * bar.high, s * bar.low), min(s * bar.high, s * bar.low), s * bar.close
        self.pv += (bar.high + bar.low + bar.close) / 3 * bar.volume
        self.volume += bar.volume
        vwap = s * self.pv / self.volume if self.volume else close
        true_range = bar.high - bar.low if self.prev_close is None else (
            max(bar.high, self.prev_close) - min(bar.low, self.prev_close))
        self.prev_close = bar.close
        self.ranges = (self.ranges + [true_range])[-14:]
        self.lows = (self.lows + [lo])[-10:]
        atr = sum(self.ranges) / len(self.ranges)
        if minute <= self.spec['orb']:
            self.ext = hi if self.ext is None else max(self.ext, hi)
            self.opp = lo if self.opp is None else min(self.opp, lo)
            return Decision('WAIT')
        if self.phase == 'FLAT':
            rule = {'opposite': lambda: self.opp, 'mid': lambda: (self.ext + self.opp) / 2,
                    'atr': lambda: close - 1.5 * atr,
                    'swing': lambda: close - min(max(close - min(self.lows), atr), 2 * atr)}[self.spec['stop']]()
            if self.force is not None:
                go, stop = minute >= self.force, close - max(close - rule, 0.25 * (self.ext - self.opp))
            else:
                go, stop = close > self.ext and (not self.spec.get('vwap') or close > vwap), rule
            if go and stop < close:
                self.phase, self.stop = 'ENTERING', stop
        if self.phase == 'ENTERING':
            return Decision('ENTER', 'orb_breakout' if self.force is None else 'random_entry')
        if self.phase == 'IN':
            self.best = max(self.best, close)
            if self.best - self.entry >= 2 * self.risk and self.stop < self.entry:
                self.stop, self.reason = self.entry, 'breakeven_stop'
            if close <= self.stop:
                self.phase = 'EXITING'
        if self.phase == 'EXITING':
            return Decision('EXIT', self.reason)
        return Decision('HOLD' if self.phase == 'IN' else 'WAIT')

    def on_entry_filled(self, at, underlying_mark):
        self.phase, self.reason = 'IN', 'orb_stop'
        self.entry = self.best = self.sign * float(underlying_mark)
        self.risk = max(self.entry - self.stop, 1e-9)


def inplay_set(datas, minutes=INPLAY_MINUTES, top=INPLAY_TOP):
    """Per day, the symbols whose first-``minutes`` range / open is among the ``top`` widest (known at that minute)."""
    width = {}
    for d in datas:
        key = (d.case.symbol, d.case.trade_date)
        if key not in width:
            bars = d.underlying[:minutes]
            width[key] = (max(b.high for b in bars) - min(b.low for b in bars)) / bars[0].open
    chosen = set()
    for day in {k[1] for k in width}:
        ranked = sorted((k for k in width if k[1] == day), key=lambda k: -width[k])
        chosen.update(ranked[:top])
    return chosen


def engine_item(registry, spec):
    item = registry.get(V66)
    item['config']['params'] = {**item['config']['params'], **spec['engine']}
    return item


def run_ticket(data, spec, fill, registry):
    if spec.get('inplay') and (data.case.symbol, data.case.trade_date) not in INPLAY:
        return simulate(data, Never(), FLATTEN, fill)
    if 'orb' in spec:
        return simulate(data, OrbEngine(spec, data), FLATTEN, fill)
    if 'engine' in spec:  # v6.6 itself with some of its exit parameters changed
        item = registry.get(V66)
        item['config']['params'] = {**item['config']['params'], **spec['engine']}
        return run_strategy(data, item, fill)
    return simulate(data, TicketEngine(spec, data, fill, registry), FLATTEN, fill)


def breakeven(trades, labels):
    """Hit rate at which the mirror-weighted expectancy crosses zero; None when it never does."""
    ev = lambda h: summarize(trades, labels, h)['balanced']['expectancy'] or 0.0
    lo, hi = 0.0, 1.0
    if ev(hi) < 0:
        return None
    if ev(lo) >= 0:
        return 0.0
    for _ in range(40):
        mid = (lo + hi) / 2
        lo, hi = (lo, mid) if ev(mid) >= 0 else (mid, hi)
    return hi


def day_bootstrap(datas, trades, labels, draws=BOOTSTRAP_DRAWS, seed=20261025):
    days = sorted({d.case.trade_date for d in datas})
    by_day = {day: [i for i, d in enumerate(datas) if d.case.trade_date == day] for day in days}
    rng = random.Random(seed)
    out = {0.5: [], 0.6: []}
    for _ in range(draws):
        idx = [i for _ in days for i in by_day[rng.choice(days)]]
        sub_t, sub_l = [trades[i] for i in idx], [labels[i] for i in idx]
        for h in out:
            value = summarize(sub_t, sub_l, h)['balanced']['expectancy']
            if value is not None:
                out[h].append(value)
    ci = lambda xs: [sorted(xs)[int(.025 * len(xs))], sorted(xs)[int(.975 * len(xs)) - 1]] if xs else None
    return {str(h): ci(xs) for h, xs in out.items()}


def describe(datas, trades, labels, bootstrap=True):
    view = lambda s: {k: s['balanced'][k] for k in ('expectancy', 'win_rate', 'payoff_ratio', 'profit_factor')}
    sides = {}
    for right, direction in (('CALL', 'LONG'), ('PUT', 'SHORT')):
        idx = [i for i, d in enumerate(datas) if d.case.direction == direction]
        sides[right] = view(summarize([trades[i] for i in idx], [labels[i] for i in idx]))
    s50 = summarize(trades, labels, .5)
    return {'cases': len(trades), 'sessions': len({d.case.trade_date for d in datas}),
            'traded': sum(t['entry'] is not None for t in trades), 'hit_0.5': view(s50),
            'traded_only_raw': {k: s50['traded_raw'][k] for k in ('win_rate', 'payoff_ratio', 'profit_factor', 'expectancy')},
            'hit_0.6': view(summarize(trades, labels, .6)), 'breakeven_hit_rate': breakeven(trades, labels),
            'sides': sides, 'hold_minutes_median': s50['hold_minutes_median'],
            'exit_reasons': dict(s50['exit_reasons']),
            'bootstrap_95': day_bootstrap(datas, trades, labels) if bootstrap else None}


def load(dirs):
    datas = []
    for root in dirs:
        dataset = Dataset(root)
        datas += [dataset.load(case) for case in dataset.cases]
    return datas


def select_premise(rows, names):
    return max(names, key=lambda n: (rows[n]['hit_0.6']['expectancy'] or -9, rows[n]['hit_0.5']['payoff_ratio'] or 0))


def lodo(datas, labels, runs, pool, min_payoff, premise=False):
    """Leave one day out: pick from ``pool`` on the other days, score the pick on the held-out day."""
    days = sorted({d.case.trade_date for d in datas})
    trades, picks = [None] * len(datas), {}
    for day in days:
        keep = [i for i, d in enumerate(datas) if d.case.trade_date != day]
        rows = {}
        for name in pool:
            sub_t, sub_l = [runs[name][i] for i in keep], [labels[i] for i in keep]
            if premise:
                rows[name] = {'hit_0.6': {'expectancy': summarize(sub_t, sub_l, .6)['balanced']['expectancy']},
                              'hit_0.5': {'payoff_ratio': summarize(sub_t, sub_l)['traded_raw']['payoff_ratio']}}
                continue
            rows[name] = {'breakeven_hit_rate': breakeven(sub_t, sub_l),
                          'hit_0.5': {'profit_factor': summarize(sub_t, sub_l)['balanced']['profit_factor']},
                          'traded_only_raw': {'payoff_ratio': summarize(sub_t, sub_l)['traded_raw']['payoff_ratio']}}
        pick = select_premise(rows, pool) if premise else (select(rows, pool, min_payoff) or pool[0])
        picks[day] = pick
        for i, d in enumerate(datas):
            if d.case.trade_date == day:
                trades[i] = runs[pick][i]
    return {'picks': picks, 'pick_counts': dict(Counter(picks.values())),
            'out_of_sample': describe(datas, trades, labels, False)}


def random_control(datas, trades, labels, spec, registry, draws=100, seed=20261026):
    """Same exits, entry minute drawn from the candidate's own entry minutes (custody G13 scheme)."""
    from custody.evaluate import _force_entry, case_value, mirror_weights, weighted_metrics
    entered = [i for i, t in enumerate(trades) if t['entry'] is not None]
    if not entered:
        return None
    weights, _ = mirror_weights([l['scenario'] for l in labels])
    observed = weighted_metrics([case_value(t) for t in trades], weights)['expectancy']
    minutes, cache, rng = [trades[i]['entry']['minute'] for i in entered], {}, random.Random(seed)

    def replay(i, minute):
        if (i, minute) not in cache:
            d = datas[i]
            if 'orb' in spec:
                engine, params = OrbEngine(spec, d, force_minute=minute), FLATTEN
            else:
                item = engine_item(registry, spec) if 'engine' in spec else registry.get(V66)
                engine = _force_entry(build_strategy(item, d.case.direction, d.session, d.case.strike), minute)
                params = item['config']['params']
            cache[i, minute] = case_value(simulate(d, engine, params, PRIMARY_FILL)) or 0.0
        return cache[i, minute]

    ge, values_all = 0, []
    for _ in range(draws):
        values = [0.0] * len(trades)
        for i in entered:
            values[i] = replay(i, rng.choice(minutes))
        ev = weighted_metrics(values, weights)['expectancy']
        values_all.append(ev)
        ge += ev >= observed
    return {'p_expectancy': (ge + 1) / (draws + 1), 'strategy_expectancy': observed,
            'random_expectancy_mean': sum(values_all) / len(values_all)}


def shape(datas, trades, labels):
    """TK_TARGETS shape and stability numbers."""
    r = [t['net_return'] for t in trades if t['net_return'] is not None]
    losses = [x for x in r if x <= 0]
    days = sorted({d.case.trade_date for d in datas})
    half = set(days[:len(days) // 2])
    pf = lambda idx: summarize([trades[i] for i in idx], [labels[i] for i in idx])['balanced']['profit_factor']
    first = [i for i, d in enumerate(datas) if d.case.trade_date in half]
    second = [i for i, d in enumerate(datas) if d.case.trade_date not in half]
    return {'trades': len(r), 'average_loss': sum(losses) / len(losses) if losses else None,
            'big_winner_200_share': sum(x >= 2 for x in r) / len(r) if r else None,
            'profit_factor_first_half': pf(first), 'profit_factor_second_half': pf(second)}


def kept_profit(datas, trades, fill=PRIMARY_FILL):
    """TK8: how much of the best sellable gain between entry and the flatten minute each exit kept."""
    rows = []
    for d, t in zip(datas, trades):
        if t['entry'] is None or t['net_return'] is None:
            continue
        flat = flatten_minute(FLATTEN, d.session)
        prices = [fill.sell(b) for b in d.option
                  if t['entry']['fill_minute'] <= session_minute(d.session, b.close_time) <= flat]
        if prices:
            rows.append((max(prices) / t['entry']['price'] - 1, t['net_return']))
    out = {}
    for level in (.5, 1.0):
        hit = [(peak, r) for peak, r in rows if peak >= level]
        mean = lambda xs: sum(xs) / len(xs) if xs else None
        exit_mean, peak_mean = mean([r for _, r in hit]), mean([p for p, _ in hit])
        out['peak_%d' % round(level * 100)] = {
            'trades': len(hit), 'share': len(hit) / len(rows) if rows else None, 'exit_mean': exit_mean,
            'peak_mean': peak_mean, 'kept': exit_mean / peak_mean if hit and peak_mean else None,
            'left_with_loss': mean([r <= 0 for _, r in hit])}
    return out


def entry_cost(datas, runs, names, base='J0', draws=1000, seed=20261026):
    """TK10: cost improvement of each buy rule against buying on the signal, paired per case, day-clustered."""
    labels = [label_case(d, flatten_minute(FLATTEN, d.session)) for d in datas]
    days = sorted({d.case.trade_date for d in datas})
    out = {}
    for name in names:
        pairs = [(d.case.trade_date, runs[base][i]['entry']['price'] / runs[name][i]['entry']['price'] - 1)
                 for i, d in enumerate(datas) if runs[base][i]['entry'] and runs[name][i]['entry']]
        values = sorted(v for _, v in pairs)
        by_day = {day: [v for dd, v in pairs if dd == day] for day in days}
        by_case = {day: [i for i, d in enumerate(datas) if d.case.trade_date == day] for day in days}
        rng = random.Random(seed)
        means, gaps = [], []
        for _ in range(draws):
            pick = [rng.choice(days) for _ in days]
            sample = [v for day in pick for v in by_day[day]]
            if sample:
                means.append(sum(sample) / len(sample))
            idx = [i for day in pick for i in by_case[day]]
            ev = lambda run: summarize([run[i] for i in idx], [labels[i] for i in idx], .6)['balanced']['expectancy'] or 0
            gaps.append(ev(runs[name]) - ev(runs[base]))
        ci = lambda xs: [sorted(xs)[int(.025 * len(xs))], sorted(xs)[int(.975 * len(xs)) - 1]] if xs else None
        out[name] = {'pairs': len(values), 'mean': sum(values) / len(values) if values else None,
                     'median': values[len(values) // 2] if values else None,
                     'worst_5pct': values[int(.05 * len(values))] if values else None,
                     'better_share': sum(v > 0 for v in values) / len(values) if values else None,
                     'mean_ci95': ci(means), 'ev60_gap_ci95': ci(gaps),
                     'missed_vs_base': sum(bool(runs[base][i]['entry']) and not runs[name][i]['entry']
                                           for i in range(len(datas)))}
        c = out[name]
        c['passed'] = (name != base and c['mean'] is not None and c['mean'] > 0 and c['mean_ci95'][0] > 0
                       and c['worst_5pct'] >= -.20 and c['ev60_gap_ci95'][1] >= 0)
    return out


def account(datas, trades, days=None):
    """TK11 account view: one unit of premium per trade, daily P&L = sum of net returns, no compounding."""
    from datetime import date
    days = sorted(days or {d.case.trade_date for d in datas})
    daily = dict.fromkeys(days, 0.0)
    for d, t in zip(datas, trades):
        if d.case.trade_date in daily and t['net_return'] is not None:
            daily[d.case.trade_date] += t['net_return']
    values = [daily[day] for day in days]
    n = len(values)
    mean = sum(values) / n if n else 0.0
    sd = (sum((v - mean) ** 2 for v in values) / (n - 1)) ** .5 if n > 1 else 0.0
    peak = curve = drawdown = 0.0
    for v in values:
        curve += v
        peak = max(peak, curve)
        drawdown = max(drawdown, peak - curve)
    weeks = Counter()
    for day in days:
        weeks[date.fromisoformat(day).isocalendar()[:2]] += daily[day]
    return {'days': n, 'sharpe': mean / sd * 252 ** .5 if sd else None, 'total': curve, 'max_drawdown': drawdown,
            'return_over_drawdown': curve / drawdown if drawdown else None,
            'positive_weeks': sum(v > 0 for v in weeks.values()) / len(weeks) if weeks else None}


SCENARIOS = ('trend_with', 'trend_against', 'reversal_against', 'reversal_with', 'chop')


def tk11_row(datas, trades, labels):
    raw = summarize(trades, labels)['traded_raw']
    by = {}
    for s in SCENARIOS:
        r = [t['net_return'] for t, l in zip(trades, labels) if l['scenario'] == s and t['net_return'] is not None]
        by[s] = {'trades': len(r), 'mean': sum(r) / len(r) if r else None}
    return {'account': account(datas, trades),
            'raw': {k: raw[k] for k in ('expectancy', 'win_rate', 'payoff_ratio', 'profit_factor')},
            'shape': shape(datas, trades, labels), 'kept_profit': kept_profit(datas, trades), 'by_scenario': by,
            'exit_reasons': dict(summarize(trades, labels)['exit_reasons'])}


def evaluate_tk11(datas, registry, lodo=True):
    """notes/TK11_PREREG.md: every exit re-scored on the account yardstick, with and without slippage."""
    labels = [label_case(d, flatten_minute(FLATTEN, d.session)) for d in datas]
    item = registry.get(V66)
    out, runs = {}, {}
    for name in TK11_POOL:
        runs[name] = [run_ticket(d, CANDIDATES[name], PRIMARY_FILL, registry) for d in datas]
        out[name] = tk11_row(datas, runs[name], labels)
        free = [run_ticket(d, CANDIDATES[name], STRESS_FILLS['slippage_0'], registry) for d in datas]
        out[name]['no_slippage'] = {'account': account(datas, free), 'raw_expectancy':
                                    summarize(free, labels)['traded_raw']['expectancy']}
    for name, trades in (('v6.6', [run_strategy(d, item) for d in datas]),
                         ('open_hold', [run_benchmark(d, item) for d in datas])):
        out[name] = tk11_row(datas, trades, labels)
    if not lodo:
        return out, None
    days = sorted({d.case.trade_date for d in datas})
    picks, stitched = {}, [None] * len(datas)
    for day in days:
        rest = [x for x in days if x != day]
        picks[day] = max(TK11_POOL, key=lambda n: account(datas, runs[n], rest)['sharpe'] or -9)
        for i, d in enumerate(datas):
            if d.case.trade_date == day:
                stitched[i] = runs[picks[day]][i]
    counts = Counter(picks.values())
    top = max(counts, key=counts.get)
    oos = account(datas, stitched)
    a2 = out['A2']['account']
    checks = {'most_picked_not_fixed': top not in FIXED_EXITS,
              'lodo_sharpe_above_A2': (oos['sharpe'] or -9) > (a2['sharpe'] or -9),
              'lodo_drawdown_within_A2': oos['max_drawdown'] <= a2['max_drawdown'],
              'top_total_positive': out[top]['account']['total'] > 0,
              'top_payoff_1_5': (out[top]['raw']['payoff_ratio'] or 0) >= 1.5}
    return out, {'picks': picks, 'pick_counts': dict(counts), 'most_picked': top, 'out_of_sample': oos,
                 'checks': checks, 'passed': all(checks.values())}


def run_position(data, specs, fill, registry):
    """TK12: every contract enters on the same signal; the position earns the mean of the contracts' returns."""
    trades = [run_ticket(data, spec, fill, registry) for spec in specs]
    if trades[0]['entry'] is None:
        return trades[0]
    last = max(trades, key=lambda t: t['exit']['fill_minute'])
    returns = [t['net_return'] for t in trades]
    return dict(last, net_return=sum(returns) / len(returns), contracts=[t['exit'] for t in trades])


def evaluate_tk12(datas, registry, lodo=True, new=None, groups=None):
    """notes/TK12_PREREG.md (and TK13): positions by contract count against one-contract exits, TK11 yardstick."""
    new, group_pools = (new or TK12), (groups or TK12_GROUPS)
    labels = [label_case(d, flatten_minute(FLATTEN, d.session)) for d in datas]
    specs = {**{name: [CANDIDATES[name]] for name in ('A2', 'G4')}, **TK12, **new}
    out, runs = {}, {}
    for name, legs in specs.items():
        runs[name] = [run_position(d, legs, PRIMARY_FILL, registry) for d in datas]
        out[name] = tk11_row(datas, runs[name], labels)
        out[name]['contracts'] = len(legs)
        free = [run_position(d, legs, STRESS_FILLS['slippage_0'], registry) for d in datas]
        out[name]['no_slippage'] = {'account': account(datas, free),
                                    'raw_expectancy': summarize(free, labels)['traded_raw']['expectancy']}
    if not lodo:
        return out, None
    days = sorted({d.case.trade_date for d in datas})
    groups = {}
    for group, pool in group_pools.items():
        picks, stitched = {}, [None] * len(datas)
        for day in days:
            rest = [x for x in days if x != day]
            picks[day] = max(pool, key=lambda n: account(datas, runs[n], rest)['sharpe'] or -9)
            for i, d in enumerate(datas):
                if d.case.trade_date == day:
                    stitched[i] = runs[picks[day]][i]
        counts = Counter(picks.values())
        top = max(counts, key=counts.get)
        oos = account(datas, stitched)
        references = [n for n in pool if n not in new]
        checks = {'most_picked_is_partial': top in new,
                  'lodo_sharpe_above_references': (oos['sharpe'] or -9) > max(out[n]['account']['sharpe'] or -9
                                                                             for n in references),
                  'lodo_drawdown_within_A2': oos['max_drawdown'] <= out['A2']['account']['max_drawdown'],
                  'top_total_positive': out[top]['account']['total'] > 0}
        groups[group] = {'pick_counts': dict(counts), 'most_picked': top, 'out_of_sample': oos, 'checks': checks,
                         'passed': all(checks.values())}
    return out, groups


def evaluate(datas, names, registry, bootstrap=True, lodo_pool=None):
    INPLAY.clear()
    INPLAY.update(inplay_set(datas))
    labels = [label_case(d, flatten_minute(FLATTEN, d.session)) for d in datas]
    item = registry.get(V66)
    runs = {name: [run_ticket(d, CANDIDATES[name], PRIMARY_FILL, registry) for d in datas] for name in names}
    runs['v6.6'] = [run_strategy(d, item) for d in datas]
    runs['open_hold'] = [run_benchmark(d, item) for d in datas]
    late = [i for i, d in enumerate(datas) if d.case.trade_date > V66_DEVELOPED_THROUGH]
    out = {}
    for name, trades in runs.items():
        row = describe(datas, trades, labels, bootstrap)
        if name in names:
            stressed = [run_ticket(d, CANDIDATES[name], STRESS_FILLS['slippage_0.5'], registry) for d in datas]
            row['stress_slippage_0.5'] = summarize(stressed, labels)['balanced']['expectancy']
            row['stress_slippage_0.5_profit_factor'] = summarize(stressed, labels)['balanced']['profit_factor']
        row['shape'] = shape(datas, trades, labels)
        row['kept_profit'] = kept_profit(datas, trades)
        if late and len(late) < len(datas) and (name == 'v6.6' or 'engine' in CANDIDATES.get(name, {}) or CANDIDATES.get(name, {}).get('entry') == V66):
            pick = lambda seq: [seq[i] for i in late]
            row['after_v66_development'] = describe(pick(datas), pick(trades), pick(labels), False)
        out[name] = row
    if set(names) == set(TK10):
        out['_entry_cost'] = entry_cost(datas, runs, list(TK10))
    if lodo_pool:
        premise = any(set(lodo_pool) == set(LODO_ROUNDS[r]) for r in PREMISE_ROUNDS)
        out['_lodo'] = lodo(datas, labels, runs, lodo_pool, TK2_MIN_PAYOFF, premise)
        oos = [runs[out['_lodo']['picks'][d.case.trade_date]][i] for i, d in enumerate(datas)]
        out['_lodo']['out_of_sample']['shape'] = shape(datas, oos, labels)
        top = max(out['_lodo']['pick_counts'], key=out['_lodo']['pick_counts'].get)
        out['_lodo']['most_picked'] = top
        out['_lodo']['most_picked_random_entry'] = (None if premise else
                                                    random_control(datas, runs[top], labels, CANDIDATES[top], registry))
    return out


def passes_targets(lodo_row, results):
    """notes/TK_TARGETS_CN.md gates; every check is reported."""
    o, sh = lodo_row['out_of_sample'], lodo_row['out_of_sample']['shape']
    top = results[lodo_row['most_picked']]
    rnd = lodo_row['most_picked_random_entry'] or {}
    raw = o['traded_only_raw']
    checks = {
        'win_rate_12_35': raw['win_rate'] is not None and .12 <= raw['win_rate'] <= .35,
        'payoff_at_least_3': (raw['payoff_ratio'] or 0) >= 3.0,
        'average_loss_within_35': sh['average_loss'] is not None and sh['average_loss'] >= -.35,
        'big_winner_share_4': (sh['big_winner_200_share'] or 0) >= .04,
        'profit_factor_1_2': (o['hit_0.5']['profit_factor'] or 0) >= 1.2,
        'breakeven_hit_0_50': o['breakeven_hit_rate'] is not None and o['breakeven_hit_rate'] <= .50,
        'trades_40': sh['trades'] >= 40,
        'random_entry_p_0_10': (rnd.get('p_expectancy') or 1) <= .10,
        'stress_profit_factor_1_0': (top.get('stress_slippage_0.5_profit_factor') or 0) >= 1.0,
        'halves_profit_factor_1_0': min(top['shape']['profit_factor_first_half'] or 0,
                                        top['shape']['profit_factor_second_half'] or 0) >= 1.0,
    }
    return all(checks.values()), checks


def select(results, names, min_payoff=None):
    eligible = [n for n in names if min_payoff is None or (results[n]['traded_only_raw']['payoff_ratio'] or 0) >= min_payoff]
    if not eligible:
        return None
    ranked = sorted(eligible, key=lambda n: (
        1.0 if results[n]['breakeven_hit_rate'] is None else round(results[n]['breakeven_hit_rate'], 2),
        -(results[n]['hit_0.5']['profit_factor'] or 0)))
    return ranked[0]


def passes(row):
    h, payoff, ev60 = row['breakeven_hit_rate'], row['hit_0.5']['payoff_ratio'], row['hit_0.6']['expectancy']
    return h is not None and h <= PASS_MAX_BREAKEVEN and (payoff or 0) >= PASS_MIN_PAYOFF and (ev60 or 0) > 0


def passes_tk2(row):
    late = row.get('after_v66_development') or {}
    h, late_h = row['breakeven_hit_rate'], late.get('breakeven_hit_rate')
    return (h is not None and h <= 0.50 and (row['hit_0.5']['profit_factor'] or 0) >= 1.1
            and (row['traded_only_raw']['payoff_ratio'] or 0) >= TK2_MIN_PAYOFF
            and late_h is not None and late_h <= 0.55)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('command', choices=['select', 'validate'])
    parser.add_argument('--round', choices=sorted(ROUNDS), default='TK1')
    parser.add_argument('--dataset', action='append', required=True)
    parser.add_argument('--candidate', choices=sorted(CANDIDATES))
    parser.add_argument('--out', required=True)
    args = parser.parse_args(argv)
    registry = Registry()
    datas = load(args.dataset)
    names, references = ROUNDS[args.round]
    if args.round in ('TK11', 'TK12', 'TK13', 'TK14'):
        lodo_flag = args.command == 'select'
        if args.round == 'TK11':
            results, lodo_row = evaluate_tk11(datas, registry, lodo=lodo_flag)
        elif args.round == 'TK12':
            results, lodo_row = evaluate_tk12(datas, registry, lodo=lodo_flag)
        elif args.round == 'TK13':
            results, lodo_row = evaluate_tk12(datas, registry, lodo=lodo_flag, new=TK13, groups=TK13_GROUPS)
        else:
            results, lodo_row = evaluate_tk12(datas, registry, lodo=lodo_flag, new=TK14, groups=TK14_GROUPS)
        passed = None
        if lodo_row:
            passed = (lodo_row['passed'] if args.round == 'TK11'
                      else {group: row['passed'] for group, row in lodo_row.items()})
        report = {'stage': 'selection' if lodo_row else 'used_validation_report_only', 'round': args.round,
                  'datasets': args.dataset, 'results': results, 'lodo': lodo_row, 'passed': passed}
    elif args.command == 'select':
        results = evaluate(datas, list(names) + references, registry, lodo_pool=LODO_ROUNDS.get(args.round))
        lodo_row = results.pop('_lodo', None)
        if args.round == 'TK1':
            chosen = select(results, list(names))
            report = {'stage': 'selection', 'round': 'TK1', 'datasets': args.dataset, 'results': results, 'selected': chosen}
        else:
            pool = LODO_ROUNDS.get(args.round, list(names))
            chosen = select(results, pool, TK2_MIN_PAYOFF)
            checks = None
            if args.round == 'TK10':
                cost = results.pop('_entry_cost')
                passing = [n for n in TK10 if cost[n]['passed']]
                chosen = max(passing, key=lambda n: cost[n]['mean']) if passing else None
                passed, checks = bool(passing), {'entry_cost': cost, 'exit': TK10_EXIT}
            elif args.round in ('TK8', 'TK9'):
                o, top = lodo_row['out_of_sample'], lodo_row['most_picked']
                row, a2 = results[top], results['A2']
                checks = {'lodo_ev60_positive': (o['hit_0.6']['expectancy'] or 0) > 0,
                          'lodo_pf60_1_2': (o['hit_0.6']['profit_factor'] or 0) >= 1.2,
                          'most_picked_is_new': top in (TK8 if args.round == 'TK8' else TK9),
                          'beats_A2_at_60': (row['hit_0.6']['expectancy'] or -9) > (a2['hit_0.6']['expectancy'] or -9),
                          'payoff_at_least_2': (row['traded_only_raw']['payoff_ratio'] or 0) >= 2.0,
                          'big_winner_share_4': (row['shape']['big_winner_200_share'] or 0) >= .04}
                passed, chosen = all(checks.values()), top
            elif args.round in PREMISE_ROUNDS:
                o, top = lodo_row['out_of_sample'], lodo_row['most_picked']
                checks = {'lodo_ev60_positive': (o['hit_0.6']['expectancy'] or 0) > 0,
                          'lodo_pf60_1_2': (o['hit_0.6']['profit_factor'] or 0) >= 1.2,
                          'most_picked_has_no_stop': CANDIDATES[top].get('stop_loss_pct') is None
                          and 'engine' not in CANDIDATES[top],
                          'most_picked_beats_K4_at_60': (results[top]['hit_0.6']['expectancy'] or -9)
                          > (results['K4']['hit_0.6']['expectancy'] or -9)}
                passed, chosen = all(checks.values()), top
            elif args.round in TARGETED_ROUNDS:
                passed, checks = passes_targets(lodo_row, results)
            elif lodo_row is None:
                passed = passes_tk2(results[chosen]) if chosen else False
            else:
                o = lodo_row['out_of_sample']
                passed = ((o['breakeven_hit_rate'] or 1) <= 0.50 and (o['hit_0.5']['profit_factor'] or 0) >= 1.1
                          and (o['traded_only_raw']['payoff_ratio'] or 0) >= TK2_MIN_PAYOFF)
            report = {'stage': 'selection', 'round': args.round, 'datasets': args.dataset, 'results': results,
                      'selected': chosen, 'lodo': lodo_row, 'passed': passed, 'checks': checks}
    elif args.round != 'TK1':
        results = evaluate(datas, list(names) + references, registry)
        report = {'stage': 'used_validation_report_only', 'round': args.round, 'datasets': args.dataset,
                  'results': results}
    else:
        if not args.candidate:
            parser.error('validate needs --candidate')
        results = evaluate(datas, [args.candidate], registry)
        report = {'stage': 'validation', 'datasets': args.dataset, 'candidate': args.candidate, 'results': results,
                  'passed': passes(results[args.candidate])}
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / ('%s_%s.json' % (args.round.lower(), args.command))).write_text(json.dumps(report, indent=1, ensure_ascii=False, default=str))
    print(json.dumps({k: v for k, v in report.items() if k != 'results'}, ensure_ascii=False))


if __name__ == '__main__':
    main()
