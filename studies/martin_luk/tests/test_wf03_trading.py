"""WF03 timing checks. Prices in this file are synthetic."""
from dataclasses import asdict, replace
from pathlib import Path
import unittest

import numpy as np

from studies.martin_luk import e15_research as E15, ie47_e1 as IE
from studies.martin_luk import wf01_joint, wf03_engine as E, wf03_trading as W
from studies.martin_luk.tests.test_wf01_joint import panel
from studies.martin_luk.workflow import adapter, capital
from studies.trader_replication import system


def simulate(bars, *, q1=False, q2=False, q3=False, trail=False, old=False, risk=.005):
    a = panel(bars)
    ema = {'always': np.ones_like(a['close'], dtype=bool)}
    opts = dict(risk=risk, max_position=.5, max_gross=2.8, trail='', trims=(),
                buy_cost=0., sell_cost=0., margin_rate=0., probe_hard_mult=2.,
                proof_risk=True, proof_stop='fill', proof_target_mult=4., proof_add_max=0,
                add_signal='always', add_signal_profit=True)
    if trail:
        ema['e9'] = np.array(trail, dtype=float).reshape(-1, 1)
        opts.update(trail='e9', stop_ema_only=True, stop_ema_buffer=.01)
    source = system.Rules(**opts)
    rules = W.trading_rules(source, q1=q1, q2=q2, q3=q3)
    if q3:
        ema['wf03_confirm'] = W.confirm_signal(a)
    book = [[((0, 0, 'SYN_00'), 0, 1, 100., 97., 'probe', None)]] + [[] for _ in bars[1:]]
    px = {k: a[k] for k in ('open', 'high', 'low', 'close', 'codes')}
    px['dates'] = a['days']
    track = {'entry_attempts': []}
    engine = system if old else E
    result = engine.simulate(px, ema, source if old else rules, book,
                             a['days'][0], a['days'][-1], audit=True, track=track)
    return result, track


def confirmation(result):
    return next(e for e in result[2][0]['executions'] if e['action'] == 'add')


class WF03EngineTests(unittest.TestCase):
    def test_disabled_copy_matches_original_for_both_risks(self):
        bars = [(100, 100, 100, 100), (100, 103, 98, 102),
                (102, 104, 101, 103), (103, 105, 99, 102)]
        for risk in (.0025, .005):
            original, original_track = simulate(bars, old=True, risk=risk)
            copy, copy_track = simulate(bars, risk=risk)
            np.testing.assert_array_equal(original[0], copy[0])
            np.testing.assert_array_equal(original[1], copy[1])
            self.assertEqual(original[2], copy[2])
            self.assertEqual(original_track, copy_track)

    def test_q1_changes_stop_without_changing_confirmation_size(self):
        bars = [(100, 100, 100, 100), (100, 103, 98, 102)]
        baseline, _ = simulate(bars)
        for q2 in (False, True):
            actual, _ = simulate(bars, q1=True, q2=q2)
            self.assertEqual(confirmation(actual)['shares'], confirmation(baseline)['shares'])
            self.assertEqual(confirmation(actual)['stop'], 97.)
            self.assertEqual(confirmation(baseline)['stop'], 100.)

    def test_q1_respects_an_ema_stop_above_original_fill(self):
        bars = [(100, 100, 100, 100), (100, 103, 98, 102)]
        baseline, _ = simulate(bars, trail=[98., 101.5])
        actual, _ = simulate(bars, q1=True, trail=[98., 101.5])
        self.assertGreater(confirmation(actual)['stop'], 100.)
        self.assertEqual(confirmation(actual), confirmation(baseline))

    def test_q2_closes_only_at_close_or_the_fixed_hard_stop(self):
        first = [(100, 100, 100, 100), (100, 103, 98, 102)]
        cases = [((101, 103, 99, 101), 'end', 101.),
                 ((101, 102, 98, 99), 'close_stop', 99.),
                 ((93, 100, 92, 98), 'gap_stop', 93.),
                 ((97, 102, 96, 101), 'end', 101.),
                 ((97, 103, 93, 101), 'stop', 94.)]
        for bar, why, price in cases:
            with self.subTest(bar=bar):
                result, _ = simulate(first + [bar], q2=True)
                trade = result[2][0]
                self.assertEqual((trade['why'], trade['executions'][-1]['price']), (why, price))
                baseline, _ = simulate(first + [bar])
                self.assertEqual(confirmation(result)['shares'], confirmation(baseline)['shares'])

    def test_q2_keeps_hard_stop_fixed_when_ema_stop_rises(self):
        bars = [(100, 100, 100, 100), (100, 103, 98, 102),
                (102, 105, 101, 104), (102, 104, 99, 103), (93, 102, 92, 98)]
        result, _ = simulate(bars, q2=True, trail=[98., 98., 103., 103., 103.])
        trade = result[2][0]
        self.assertEqual((trade['why'], trade['exit'], trade['executions'][-1]['price']),
                         ('gap_stop', '2025-01-06', 93.))
        stopped, _ = simulate(bars[:3] + [(102, 103, 99, 101)], q2=True,
                              trail=[98., 98., 103., 103.])
        self.assertEqual((stopped[2][0]['why'], stopped[2][0]['executions'][-1]['price']),
                         ('close_stop', 101.))

    def test_probe_rules_still_apply_before_confirmation(self):
        result, _ = simulate([(100, 100, 100, 100), (99, 101, 93, 101)], q2=True)
        self.assertEqual((result[2][0]['why'], result[2][0]['executions'][-1]['price']), ('stop', 94.))
        self.assertFalse(result[2][0]['confirmed'])

    def test_q3_uses_only_current_and_previous_completed_bars(self):
        bars = [(100, 105, 99, 100), (100, 103, 98, 102),
                (102, 105, 101, 104), (104, 106, 103, 105)]
        result, _ = simulate(bars, q3=True)
        self.assertEqual(confirmation(result)['time'], '2025-01-04')
        a = panel(bars)
        before = W.confirm_signal(a)
        a['high'][3:] = 999.
        a['close'][3:] = 1.
        np.testing.assert_array_equal(before[:3], W.confirm_signal(a)[:3])


class WF03EntryTests(unittest.TestCase):
    def test_book_disabled_is_the_original_c062_path(self):
        a = panel([(99, 100, 98, 99), (101, 103, 99, 102),
                   (103, 105, 100, 104)])
        picks = {0: ['SYN_00']}
        dated = {str(a['days'][t]): names for t, names in picks.items()}
        expected = IE.entry_book(a, dated, **IE.E6['E6c'])[0]
        expected = E15.P.retry_book(a, expected, {}, E15.SPECS['C062'])[0]
        expected = [[tuple(e[:7]) + (None, .30) + tuple(e[9:]) for e in row] for row in expected]
        self.assertEqual(W.entry_book(a, picks), expected)

    def test_q4_pullback_entry_and_future_independence(self):
        a = panel([(100, 105, 99, 100), (98.5, 102, 98, 100),
                   (100, 101, 98, 99), (99, 104, 98, 103)])
        a['e9'] = np.full_like(a['close'], 99.)
        a['e21'] = np.full_like(a['close'], 98.)
        picks = {0: ['SYN_00']}
        original = W.entry_book(a, picks, pullback=True)
        self.assertEqual(original[1][0][5], IE.PB_KIND)
        self.assertEqual(W.entry_book(a, picks)[1], [])
        later = {k: v.copy() for k, v in a.items()}
        for key in ('open', 'high', 'low', 'close', 'e9', 'e21'):
            later[key][2:, :] = 999.
        self.assertEqual(original[:2], W.entry_book(later, picks, pullback=True)[:2])

    def test_policy_fields_preserve_the_base_and_no_evaluation_inputs(self):
        base = system.Rules(risk=.005)
        copy = W.trading_rules(base)
        actual = asdict(copy)
        actual.pop('confirmed_close_stop')
        self.assertEqual(actual, asdict(base))
        source = Path(W.__file__).read_text()
        for forbidden in ('legs_frozen', 'trades.csv', 'labels(', 'notes/'):
            self.assertNotIn(forbidden, source)

    def test_b0_rules_match_wf01_c3(self):
        a = panel([(99, 100, 98, 99), (101, 103, 99, 102), (103, 105, 100, 104)])
        original = adapter.rules_for('C062')
        _, _, c3, _ = wf01_joint.build(a, {str(a['days'][0]): ['SYN_00']}, original, c3=True)
        capital_cfg = adapter.read(adapter.FLOW / 'config.json')['capital']
        expected = capital.candidate_rules(c3, capital_cfg, 'L2.8')
        base = capital.candidate_rules(replace(original, risk=.005), capital_cfg, 'L2.8')
        actual = asdict(W.trading_rules(base))
        actual.pop('confirmed_close_stop')
        self.assertEqual(actual, asdict(expected))


if __name__ == '__main__':
    unittest.main()
