"""Synthetic checks for WF05's close-time rotation."""
from dataclasses import asdict, replace
from pathlib import Path
import unittest

import numpy as np

from studies.martin_luk import wf03_engine, wf05_engine as engine, wf05_joint
from studies.martin_luk.tests.test_wf01_joint import panel
from studies.trader_replication import system


def entry(j, fill=100., stop=90., multiplier=None):
    return ((j, 0, f'SYN_{j:02d}'), j, 1, fill, stop, 'close', None, None, .50, multiplier)


def policy(**changes):
    base = engine.Rules(risk=.005, max_position=.5, max_gross=2.8, max_open=2,
                        trail='', trims=(), buy_cost=0., sell_cost=0., margin_rate=0.)
    return replace(base, **changes)


def run(a, book, rules, implementation=engine):
    px = {k: a[k] for k in ('open', 'high', 'low', 'close', 'codes')}
    px['dates'] = a['days']
    ema = {'always': np.ones_like(a['close'], dtype=bool)}
    track = {'entry_attempts': [], 'proof_orders': [], 'margin': [], 'gross': [], 'open': [], 'new': []}
    curve, days, trades = implementation.simulate(px, ema, rules, book, a['days'][0], a['days'][-1],
                                                   audit=True, track=track)
    return curve, days, trades, track


def fixture(n=6, columns=5):
    a = panel([(100., 101., 99., 100.)] * n, columns=columns)
    book = [[] for _ in a['days']]
    return a, book


def rot_rules(**changes):
    return policy(rotate_rmax_r=3., rotate_min_days=3, **changes)


class WF05Tests(unittest.TestCase):
    def test_default_copy_matches_old_engine_with_q2_and_c2(self):
        a, book = fixture()
        book[0] = [entry(0), entry(1)]
        book[3] = [entry(2)]
        for q2 in (False, True):
            for c2 in (False, True):
                p = policy(confirmed_close_stop=q2, rotate_below=.02 if c2 else 0.,
                           rotate_min_days=3 if c2 else 0)
                old = wf03_engine.Rules(**{k: v for k, v in asdict(p).items() if k != 'rotate_rmax_r'})
                before = run(a, book, old, wf03_engine)
                after = run(a, book, p)
                np.testing.assert_array_equal(before[0], after[0])
                np.testing.assert_array_equal(before[1], after[1])
                self.assertEqual(before[2:], after[2:])

    def test_rotate_at_close_and_skip_young_positions(self):
        a, book = fixture()
        book[0] = [entry(0)]
        book[1] = [entry(1)]
        book[3] = [entry(2)]
        a['close'][3:, 0] = 98.
        a['close'][3:, 1] = 95.
        result = run(a, book, rot_rules())
        victim = next(t for t in result[2] if t['why'] == 'rotate')
        incoming = next(t for t in result[2] if t['code'] == 'SYN_02')
        self.assertEqual((victim['code'], victim['exit'], victim['executions'][-1]['price']),
                         ('SYN_00', a['days'][3], 98.))
        self.assertEqual((incoming['entry'], incoming['fill']), (a['days'][3], 100.))

    def test_close_peak_protects_three_r_but_intraday_high_does_not(self):
        a, book = fixture()
        book[0] = [entry(0), entry(1)]
        book[3] = [entry(2)]
        a['close'][1, 0] = 130.
        a['high'][1, 0] = a['high'][1, 1] = 131.
        a['close'][3:, 0] = 95.
        a['close'][3:, 1] = 99.
        trades = run(a, book, rot_rules())[2]
        self.assertEqual([t['code'] for t in trades if t['why'] == 'rotate'], ['SYN_01'])

    def test_lowest_current_r_then_entry_age_then_code(self):
        a, book = fixture(columns=6)
        book[0] = [entry(0, stop=90.), entry(1, stop=95.)]
        book[3] = [entry(2)]
        a['close'][3:, 0] = a['close'][3:, 1] = 98.
        trades = run(a, book, rot_rules())[2]
        self.assertEqual([t['code'] for t in trades if t['why'] == 'rotate'], ['SYN_01'])
        a, book = fixture(columns=6)
        book[0] = [entry(1)]
        book[1] = [entry(0)]
        book[4] = [entry(2)]
        trades = run(a, book, rot_rules())[2]
        self.assertEqual([t['code'] for t in trades if t['why'] == 'rotate'], ['SYN_01'])
        book[0] = [entry(1), entry(0)]
        book[1] = []
        trades = run(a, book, rot_rules())[2]
        self.assertEqual([t['code'] for t in trades if t['why'] == 'rotate'], ['SYN_00'])

    def test_future_bars_cannot_change_decision(self):
        a, book = fixture()
        book[0] = [entry(0), entry(1)]
        book[3] = [entry(2)]
        a['close'][3, 0] = 98.
        baseline = run(a, book, rot_rules())
        changed = {k: v.copy() for k, v in a.items()}
        for key in ('open', 'high', 'low', 'close'):
            changed[key][4:] = 500.
        later = run(changed, book, rot_rules())
        self.assertEqual([t['code'] for t in baseline[2] if t['why'] == 'rotate'],
                         [t['code'] for t in later[2] if t['why'] == 'rotate'])
        self.assertEqual(baseline[3]['entry_attempts'], later[3]['entry_attempts'])
        np.testing.assert_array_equal(baseline[0][:4], later[0][:4])

    def test_daily_limit_and_same_code_do_not_sell(self):
        a, book = fixture()
        book[0] = [entry(0)]
        book[1] = [entry(1)]
        book[3] = [entry(2), entry(3)]
        result = run(a, book, rot_rules(max_open=3, max_new_long=1))
        self.assertEqual([x['reason'] for x in result[3]['entry_attempts'][-2:]], ['filled', 'daily_long'])
        self.assertFalse(any(t['why'] == 'rotate' for t in result[2]))
        book[3] = [entry(0)]
        result = run(a, book, rot_rules())
        self.assertEqual(result[3]['entry_attempts'][-1]['reason'], 'same_code')
        self.assertFalse(any(t['why'] == 'rotate' for t in result[2]))

    def test_mutually_exclusive_rotation_rules(self):
        a, book = fixture()
        with self.assertRaisesRegex(ValueError, 'mutually exclusive'):
            run(a, book, rot_rules(rotate_below=.02))

    def test_q2_close_stop_precedes_c2_and_m3(self):
        for rotation in ('c2', 'm3'):
            for count in (1, 2):
                with self.subTest(rotation=rotation, incoming=count):
                    a, book = fixture()
                    book[0] = [entry(0, stop=97.), entry(1, stop=97.)]
                    book[3] = [entry(j, stop=97.) for j in range(2, 2 + count)]
                    a['close'][1, 0], a['high'][1, 0] = 102., 103.
                    a['close'][3, 0], a['low'][3, 0] = 99., 98.
                    options = dict(confirmed_close_stop=True, probe_hard_mult=2., proof_risk=True,
                                   proof_stop='fill', proof_target_mult=4., proof_add_max=0,
                                   add_signal='always', add_signal_profit=True, rotate_min_days=3)
                    options['rotate_below' if rotation == 'c2' else 'rotate_rmax_r'] = .02 if rotation == 'c2' else 3.
                    trades = run(a, book, policy(**options))[2]
                    stopped = next(t for t in trades if t['code'] == 'SYN_00')
                    self.assertEqual((stopped['why'], stopped['exit']), ('close_stop', a['days'][3]))
                    self.assertEqual([t['code'] for t in trades if t['why'] == 'rotate'],
                                     ['SYN_01'] if count == 2 else [])

    def test_low_gross_room_triggers_rotation_before_slots_are_full(self):
        a, book = fixture()
        book[0] = [entry(0, stop=50.), entry(1, stop=50.)]
        book[3] = [entry(2, stop=50.)]
        result = run(a, book, rot_rules(max_open=3, risk=.15, max_gross=.6))
        self.assertEqual([t['code'] for t in result[2] if t['why'] == 'rotate'], ['SYN_00'])
        self.assertEqual(result[3]['entry_attempts'][-1]['positions'], 2)
        self.assertEqual(result[3]['entry_attempts'][-1]['reason'], 'filled')

    def test_rotation_sells_even_when_new_size_is_rejected(self):
        a, book = fixture()
        book[0] = [entry(0), entry(1)]
        book[3] = [entry(2, multiplier=.00001)]
        result = run(a, book, rot_rules())
        self.assertEqual([t['code'] for t in result[2] if t['why'] == 'rotate'], ['SYN_00'])
        self.assertEqual(result[3]['entry_attempts'][-1]['reason'], 'risk_or_gross')
        self.assertFalse(any(t['code'] == 'SYN_02' for t in result[2]))

    def test_position_cap_applies_to_confirmation_add(self):
        a, book = fixture()
        book[0] = [entry(0, stop=97.)]
        a['close'][1, 0], a['high'][1, 0] = 102., 103.
        base = system.Rules(risk=.01, max_position=.5, max_gross=2.8, max_open=2,
                            trail='', trims=(), buy_cost=0., sell_cost=0., margin_rate=0.,
                            probe_hard_mult=2., proof_risk=True, proof_stop='fill',
                            proof_target_mult=4., proof_add_max=0, add_signal='always', add_signal_profit=True)
        trade = run(a, book, wf05_joint.rules(base, q2=True, p30=True))[2][0]
        add = next(e for e in trade['executions'] if e['action'] == 'add')
        initial = trade['executions'][0]['shares']
        equity = 1. + initial * (102. - 100.)
        self.assertLessEqual((initial + add['shares']) * 102., .30 * equity + 1e-12)
        self.assertAlmostEqual((initial + add['shares']) * 102., .30 * equity)

    def test_strategy_modules_have_no_evaluation_inputs(self):
        for module in (engine, wf05_joint):
            source = Path(module.__file__).read_text()
            for term in ('legs_frozen', 'trades.csv', 'labels(', 'notes/', 'legs'):
                self.assertNotIn(term, source)


if __name__ == '__main__':
    unittest.main()
