"""Execution timing checks for the WF02 switches."""
from dataclasses import replace
from pathlib import Path
import unittest

import numpy as np

from studies.martin_luk import e15_research as E15, ie47_e1 as IE, wf01_joint as W1, wf02_joint as W2
from studies.martin_luk.tests.test_wf01_joint import entry, panel, rules, simulate


class OrderingTests(unittest.TestCase):
    def setUp(self):
        self.a = panel([(99, 100, 98, 99), (99, 100, 98, 99),
                        (101, 103, 99, 102), (102, 103, 100, 101)], columns=4)
        self.picks = {self.a['days'][0]: ['SYN_00'],
                      self.a['days'][1]: ['SYN_01', 'SYN_02']}

    def test_off_matches_wf01_with_every_account_switch(self):
        for c2 in (False, True):
            for c3 in (False, True):
                self.assertEqual(W2.build(self.a, self.picks, rules(), c2=c2, c3=c3),
                                 W1.build(self.a, self.picks, rules(), c1=False, c2=c2, c3=c3))

    def test_latest_night_then_rank_for_last_slot_or_daily_limit(self):
        base, _, _, _ = W2.build(self.a, self.picks, rules())
        new, _, _, _ = W2.build(self.a, self.picks, rules(), c4=True)
        self.assertEqual([[e[1:] for e in row] for row in base],
                         [[e[1:] for e in row] for row in new])
        self.assertEqual([e[0] for e in sorted(new[2])],
                         [(-1, 0, 'SYN_01'), (-1, 1, 'SYN_02'), (0, 0, 'SYN_00')])
        new[0].append(entry(3, (-10, 0, 'SYN_03'), 99., 95.))
        for policy, reason in ((rules(max_open=2), 'max_open'),
                               (rules(max_new_long=1), 'daily_long')):
            _, _, trades, trace = simulate(self.a, new, policy)
            admitted = [t for t in trades if t['entry'] == self.a['days'][2]]
            self.assertEqual([t['code'] for t in admitted], ['SYN_01'])
            self.assertEqual([a['reason'] for a in trace['entry_attempts'] if a['day'] == self.a['days'][2]],
                             ['filled', reason, reason])
            candidate = next(e for e in base[2] if e[1] == 1)
            self.assertEqual((admitted[0]['fill'], admitted[0]['stop']), (candidate[3], candidate[4]))

    def test_same_day_only_and_no_future_bars(self):
        original = W2.build(self.a, self.picks, rules(), c4=True)[0]
        later = {k: v.copy() for k, v in self.a.items()}
        later['high'][3:, :] = 500.
        later['low'][3:, :] = 1.
        later['close'][3:, :] = 2.
        changed = W2.build(later, self.picks, rules(), c4=True)[0]
        self.assertEqual(original[:3], changed[:3])
        plain = W2.build(self.a, self.picks, rules())[0]
        self.assertEqual([[e[1:] for e in row] for row in original],
                         [[e[1:] for e in row] for row in plain])

    def test_intraday_fill_precedes_newer_close_fill(self):
        a = panel([(100, 101, 99, 100)] * 3, columns=2)
        early = entry(0, (0, 0, 'SYN_00'), 100., 95.)
        early = early[:5] + ('intraday',) + early[6:]
        close = entry(1, (0, 1, 'SYN_01'), 100., 95.)
        book = [[], [early, close], []]
        _, _, trades, trace = simulate(a, W2.newest_first(book),
                                       rules(max_open=1, intraday_kinds=('intraday',)))
        self.assertEqual([t['code'] for t in trades], ['SYN_00'])
        self.assertEqual([(e['code'], e['reason']) for e in trace['entry_attempts']],
                         [('SYN_00', 'filled'), ('SYN_01', 'max_open')])

    def test_rejects_other_priority_consumer(self):
        with self.assertRaises(ValueError):
            W2.build(self.a, self.picks, rules(make_room_kind={'close': 'close'}), c4=True)


class ObservationTests(unittest.TestCase):
    def test_three_nights_and_rebuilt_retry_metadata(self):
        a = panel([(99, 100, 98, 99)] * 4 + [(101, 103, 99, 102),
                                               (101, 103, 99, 102)], columns=2)
        picks = {a['days'][0]: ['SYN_00'], a['days'][2]: ['SYN_01']}
        old, _, _, old_meta = W2.build(a, picks, rules())
        short, episodes, _, meta = W2.build(a, picks, rules(), c5=True)
        self.assertIsNone(episodes)
        self.assertIn(0, [e[1] for e in old[4]])
        self.assertNotIn(0, [e[1] for e in short[4]])
        self.assertIn(1, [e[1] for e in short[4]])
        expected, metadata = E15.P.retry_book(a, IE.entry_book(a, picks, **IE.E6['E6a'])[0],
                                               {}, E15.SPECS['C062'])
        expected = [[tuple(e[:7]) + (None, .30) + tuple(e[9:]) for e in row] for row in expected]
        self.assertEqual((short, meta), (expected, metadata))
        original, metadata = E15.P.retry_book(a, IE.entry_book(a, picks, **IE.E6['E6c'])[0],
                                               {}, E15.SPECS['C062'])
        original = [[tuple(e[:7]) + (None, .30) + tuple(e[9:]) for e in row] for row in original]
        self.assertEqual((old, old_meta), (original, metadata))


class RotationTests(unittest.TestCase):
    def make_case(self, *, fail=False):
        a = panel([(100, 105, 90, 100)] * 5, columns=13)
        a['close'][3:, :10] = 102.
        a['close'][3:, 0] = 95.
        a['close'][3:, 10] = 90.
        book = [[] for _ in a['days']]
        book[0] = [entry(j, (j, 0, str(a['codes'][j]))) for j in range(10)]
        book[2] = [entry(10, (10, 2, 'SYN_10'))]
        book[3] = [entry(11, (0, 1, 'SYN_11')),
                   entry(12, (1, 2, 'SYN_12'), multiplier=.00001 if fail else None)]
        policy = rules(rotate_below=.02, rotate_min_days=3)
        return a, simulate(a, W2.newest_first(book), policy)

    def test_order_precedes_rotation_and_protects_young_or_up_two_percent(self):
        a, (_, _, trades, trace) = self.make_case()
        self.assertEqual([(t['code'], t['why']) for t in trades if t['why'] == 'rotate'],
                         [('SYN_00', 'rotate')])
        self.assertIn(('SYN_12', str(a['days'][3])), [(t['code'], t['entry']) for t in trades])
        attempted = [(t['code'], t['reason']) for t in trace['entry_attempts'] if t['day'] == a['days'][3]]
        self.assertEqual(attempted, [('SYN_12', 'filled'), ('SYN_11', 'max_open')])

    def test_failed_incoming_after_rotation_is_visible(self):
        a, (_, _, trades, trace) = self.make_case(fail=True)
        self.assertEqual(sum(t['why'] == 'rotate' for t in trades), 1)
        attempts = [x for x in trace['entry_attempts'] if x['day'] == a['days'][3]]
        self.assertEqual([(x['code'], x['reason']) for x in attempts],
                         [('SYN_12', 'risk_or_gross'), ('SYN_11', 'filled')])
        self.assertEqual(sum(x['reason'] != 'filled' for x in attempts[:1]), 1)

    def test_module_does_not_read_evaluation_inputs(self):
        source = Path(W2.__file__).read_text()
        for forbidden in ('legs_frozen', 'trades.csv', 'labels(', 'notes/'):
            self.assertNotIn(forbidden, source)


if __name__ == '__main__':
    unittest.main()
