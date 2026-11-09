"""E5 close-entry timing; written before the execution implementation."""
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from studies.martin_luk import ie47_e1 as M
from studies.martin_luk.tests.test_ie47_e1 import arrays, replay
from studies.trader_replication import gate, system as Y


class E5TimingTests(unittest.TestCase):
    def book(self, a, picks=None):
        picks = picks or {str(a['days'][0]): ['SYN_00']}
        return M.entry_book(a, picks, observe=3, close_confirmed=True)

    def test_waits_for_strict_close_above_previous_high_then_fills_at_close(self):
        a = arrays([(99, 100, 98, 99), (100, 103, 99, 100),
                    (103, 105, 102, 104), (105, 106, 104, 105)])
        book, mask, _ = self.book(a)
        self.assertEqual([len(row) for row in book], [0, 0, 1, 0])
        self.assertEqual(book[2][0][3:5], (104., 102.))
        self.assertIsNone(book[2][0][6])
        self.assertEqual(np.argwhere(mask).tolist(), [[2, 0]])

    def test_entry_low_and_high_cannot_stop_or_trim_a_close_entry(self):
        a = arrays([(99, 100, 98, 99), (102, 130, 101, 104)])
        book, _, _ = self.book(a)
        _, _, trades = replay(a, book, M.execution_rules('E5'), e9=[99, 105])
        self.assertEqual([e['action'] for e in trades[0]['executions']], ['entry', 'end'])
        self.assertEqual(trades[0]['fill'], 104.)
        self.assertTrue(gate.check_fills(a, trades)['ok'])

    def test_both_width_caps_reject_without_retry_and_one_percent_floor(self):
        for adr, low, allowed in ((20, 98.7, False), (6, 100.8, False),
                                  (6, 101., True), (20, 100., True), (20, 103.8, True),
                                  (1, 103.8, False)):
            with self.subTest(adr=adr, low=low):
                a = arrays([(99, 100, 98, 99), (104, 105, low, 104),
                            (105, 107, 105, 106)], adr=adr)
                book, _, events = self.book(a)
                self.assertEqual(bool(book[1]), allowed)
                self.assertFalse(book[2])
                if allowed:
                    self.assertAlmostEqual(book[1][0][4], min(low, 104*.99))
                else:
                    self.assertEqual(events[0]['why'], 'wide_stop')

    def test_previous_adr_boundary_is_inclusive_and_today_cannot_widen_it(self):
        a = arrays([(99, 100, 98, 99), (100, 102, 97, 101)], adr=8)
        a['adr'][1] = 1000
        self.assertTrue(self.book(a)[0][1])
        a['low'][1] = 96.9
        self.assertFalse(self.book(a)[0][1])
        a['low'][1] = 95.95
        a['adr'][0] = 20
        self.assertTrue(self.book(a)[0][1])  # Exactly 5% from the close.

    def test_three_day_expiry_and_no_original_intraday_chase_filter(self):
        for when, expected in ((3, 1), (4, 0)):
            a = arrays([(99, 100, 98, 99)]*5, adr=10)
            a['open'][when], a['high'][when], a['low'][when], a['close'][when] = 97, 102, 97, 101
            self.assertEqual(sum(map(len, self.book(a)[0])), expected)

    def test_next_day_stops_and_partials_then_first_below_ema_close(self):
        a = arrays([(99, 100, 98, 99), (102, 130, 101, 104),
                    (104, 120, 102, 116), (116, 117, 110, 112)], adr=10)
        _, _, trades = replay(a, self.book(a)[0], M.execution_rules('E5'), e9=[99, 105, 110, 113])
        ex = trades[0]['executions']
        self.assertEqual([e['action'] for e in ex], ['entry', 'trim', 'trim', 'trail'])
        self.assertEqual([e['price'] for e in ex[1:3]], [113., 119.])
        for e in ex[1:3]:
            self.assertEqual(e['time'], a['days'][2])
            self.assertAlmostEqual(e['shares']/ex[0]['shares'], .15)
        a['low'][2] = 100
        _, _, stopped = replay(a, self.book(a)[0], M.execution_rules('E5'))
        self.assertEqual((stopped[0]['days'], stopped[0]['why']), (1, 'stop'))
        self.assertEqual([e['action'] for e in stopped[0]['executions']], ['entry', 'stop'])

    def test_build_uses_e5_and_keeps_e3_account_rules(self):
        a = arrays([(99, 100, 98, 99), (100, 103, 99, 100), (103, 105, 102, 104)])
        a['_ie47'] = dict(picks={str(a['days'][0]): ['SYN_00']}, pool=np.ones((3, 1), bool))
        book, rules, _, pool = M.IE47Study().build(a, {'candidate': 'E5'})
        self.assertEqual([len(x) for x in book], [0, 0, 1])
        self.assertEqual(rules.intraday_kinds, ())
        self.assertFalse(rules.entry_day_exit_signal)
        self.assertEqual(replace(rules, intraday_kinds=(M.KIND,), entry_day_exit_signal=True), M.execution_rules('E3'))
        self.assertFalse(pool[0].any())
        self.assertTrue(pool[1:].all())

    def test_account_rejection_does_not_defer_the_first_confirmation(self):
        a = arrays([(99, 100, 98, 99), (101, 103, 100, 102),
                    (103, 105, 102, 104)], columns=2)
        book, _, _ = self.book(a, {str(a['days'][0]): ['SYN_00', 'SYN_01']})
        self.assertEqual([len(row) for row in book], [0, 2, 0])
        _, _, trades = replay(a, book, replace(M.execution_rules('E5'), max_new_long=1))
        self.assertEqual([t['code'] for t in trades], ['SYN_00'])

    def test_recorded_validation_cannot_load_prices_or_evaluate_again(self):
        from studies.martin_luk import e5_research
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder)
            (output/'e5_validation.json').write_text('{}', encoding='utf-8')
            with patch.object(e5_research, 'OUT', output), patch.object(M.IE47Study, 'arrays') as prices:
                with self.assertRaisesRegex(ValueError, 'already recorded'):
                    e5_research.validate()
                prices.assert_not_called()

    def test_placebo_preserves_close_fill_width_and_no_day_zero_management(self):
        a = arrays([(99, 100, 98, 99), (102, 130, 101, 104),
                    (104, 105, 103, 104)], columns=2)
        a['close'][1, 1], a['high'][1, 1], a['low'][1, 1] = 208, 260, 200
        a['open'][1, 1] = 204
        a['open'][2, 1], a['close'][2, 1], a['high'][2, 1], a['low'][2, 1] = 208, 208, 210, 206
        book = self.book(a)[0]
        rules = replace(M.execution_rules('E5'), buy_cost=0, sell_cost=0, margin_rate=0)
        px = M.STUDY.px(a)
        ema = dict(e9=np.full_like(a['close'], 90.), below_e9=np.zeros_like(a['close'], bool))
        pool = np.zeros_like(a['close'], bool)
        pool[:, 1] = True
        _, _, trades = Y.simulate(px, ema, rules, book, a['days'][0], a['days'][-1],
                                  placebo=np.random.default_rng(1), pool=pool, audit=True)
        self.assertEqual(trades[0]['fill'], 208.)
        self.assertAlmostEqual(trades[0]['risk_pct'], 3/104)
        self.assertEqual([e['action'] for e in trades[0]['executions']], ['entry', 'end'])


if __name__ == '__main__':
    unittest.main()
