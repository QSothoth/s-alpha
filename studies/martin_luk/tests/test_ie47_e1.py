"""E1 execution timing, specified before the implementation."""
from dataclasses import replace
import unittest

import numpy as np

from studies.martin_luk import ie47_e1 as M
from studies.trader_replication import gate, system as Y


def arrays(rows, columns=1, adr=6.):
    rows = np.asarray(rows, float)
    out = {name: np.repeat(rows[:, k:k+1], columns, axis=1)
           for k, name in enumerate(('open', 'high', 'low', 'close'))}
    out.update(days=np.array([f'2025-01-{i+2:02d}' for i in range(len(rows))]),
               codes=np.array([f'SYN_{j:02}' for j in range(columns)]), market='us',
               adr=np.full((len(rows), columns), adr), has=np.isfinite(out['close']))
    return out


def replay(a, entries, rules=None, e9=None):
    rules = replace(rules or M.execution_rules('E1'), buy_cost=0, sell_cost=0, margin_rate=0)
    ema = {'e9': np.full_like(a['close'], 90.) if e9 is None else np.asarray(e9, float).reshape(a['close'].shape)}
    ema['below_e9'] = a['close'] < ema['e9']
    px = {k: a[k] for k in ('open', 'high', 'low', 'close', 'codes')}
    px['dates'] = a['days']
    return Y.simulate(px, ema, rules, entries, a['days'][0], a['days'][-1], audit=True)


class EntryTimingTests(unittest.TestCase):
    def book(self, a, observe=5):
        return M.entry_book(a, {str(a['days'][0]): ['SYN_00']}, observe)[0]

    def test_observation_starts_tomorrow_and_first_break_uses_current_previous_high(self):
        a = arrays([(100, 102, 98, 100), (100, 101, 99, 100),
                    (102, 103, 101, 102), (103, 104, 102, 103)])
        entries = self.book(a)
        self.assertEqual([len(x) for x in entries], [0, 0, 1, 0])
        self.assertEqual(entries[2][0][3:5], (102., 99.))

    def test_touch_is_not_a_break_and_chasing_consumes_the_observation(self):
        a = arrays([(100, 104, 98, 100), (100, 104, 99, 103),
                    (100, 105, 99, 104), (105, 106, 104, 105)])
        self.assertFalse(any(self.book(a)))  # Day two's first break requires 4% chasing.
        a = arrays([(100, 103, 98, 100), (100, 104, 99, 103)])
        self.assertEqual(self.book(a)[1][0][3], 103.)  # Exactly 3% is allowed.

    def test_expiry_includes_t_plus_five_or_three_but_no_later(self):
        for observe in (3, 5):
            for when, expected in ((observe, 1), (observe+1, 0)):
                a = arrays([(99, 100, 98, 99)] * (observe+2))
                a['high'][when] = 101
                self.assertEqual(sum(map(len, self.book(a, observe))), expected)

    def test_stop_uses_previous_low_previous_adr_and_one_percent_floor(self):
        for previous_low, adr, expected in ((95., 10., 97.), (98., 10., 98.), (99.8, 10., 99.),
                                             (95., 4., 98.), (95., 1., 99.)):
            a = arrays([(99, 100, previous_low, 99), (100, 101, 98, 100)], adr=adr)
            a['adr'][1] = 1000  # Today's range cannot widen its own planned stop.
            self.assertAlmostEqual(self.book(a)[1][0][4], expected)

    def test_original_rank_orders_triggers_across_observation_nights(self):
        a = arrays([(99, 100, 98, 99)] * 3, columns=3)
        a['high'][2] = 101
        picks = {str(a['days'][0]): ['SYN_02', 'SYN_01'], str(a['days'][1]): ['SYN_00']}
        entries = M.entry_book(a, picks)[0]
        self.assertEqual([e[1] for e in sorted(entries[2], key=lambda e: e[0])], [2, 0, 1])


class ManagementTests(unittest.TestCase):
    def test_board_shows_the_active_ema_exit_line_on_the_entry_close(self):
        from studies.trader_replication import runner, systems
        a = arrays([(99, 100, 95, 99), (100, 103, 98, 102)])
        a.update(_ie47=dict(picks={str(a['days'][0]): ['SYN_00']}, pool=np.ones((2, 1), bool)),
                 e9=np.array([[99.], [101.]]), digest='synthetic')
        st = M.IE47Study()
        st.arrays = lambda *args, **kwargs: a
        system = systems.System('martin_luk_ie47', 'E1 synthetic', 'research',
                                lambda: (st, {'candidate': 'E1'}), freeze=str(a['days'][-1]), wrap=False)
        result = runner.run(system, 'us')
        self.assertEqual(result['holdings'][0]['trail'], 101.)

    def test_same_day_stop_precedes_any_partial(self):
        a = arrays([(99, 100, 95, 99), (100, 130, 96, 105)])
        entries = M.entry_book(a, {str(a['days'][0]): ['SYN_00']})[0]
        _, _, tr = replay(a, entries)
        self.assertEqual(tr[0]['why'], 'stop_day0')
        self.assertEqual([e['action'] for e in tr[0]['executions']], ['entry', 'stop_day0'])
        self.assertEqual(tr[0]['executions'][-1]['price'], 97.)
        self.assertTrue(gate.check_fills(a, tr)['ok'])

    def test_entry_day_completed_close_can_exit_below_nine_ema(self):
        a = arrays([(99, 100, 95, 99), (100, 110, 98, 98)])
        entries = M.entry_book(a, {str(a['days'][0]): ['SYN_00']})[0]
        _, _, tr = replay(a, entries, e9=[99, 99])
        self.assertEqual((tr[0]['why'], tr[0]['days'], tr[0]['exit']), ('signal', 0, a['days'][1]))
        _, _, old = replay(a, entries, replace(M.execution_rules('E1'), entry_day_exit_signal=False), e9=[99, 99])
        self.assertEqual(old[0]['why'], 'end')

    def test_no_unordered_entry_day_partials_then_fifteen_percent_of_original_at_three_and_five_r(self):
        a = arrays([(99, 100, 95, 99), (100, 125, 98, 104), (104, 120, 100, 110)])
        entries = M.entry_book(a, {str(a['days'][0]): ['SYN_00']})[0]
        _, _, tr = replay(a, entries)
        events = tr[0]['executions']
        trims = [e for e in events if e['action'] == 'trim']
        self.assertEqual([(e['time'], e['price']) for e in trims], [(a['days'][2], 109.), (a['days'][2], 115.)])
        for event in trims:
            self.assertAlmostEqual(event['shares']/events[0]['shares'], .15)

    def test_first_later_close_below_ema_exits_without_needing_an_armed_trail(self):
        a = arrays([(99, 100, 95, 99), (100, 101, 98, 100), (100, 105, 99, 104)])
        entries = M.entry_book(a, {str(a['days'][0]): ['SYN_00']})[0]
        _, _, tr = replay(a, entries, e9=[99, 99, 105])
        self.assertEqual((tr[0]['exit'], tr[0]['why']), (a['days'][2], 'signal'))

    def test_touching_ema_is_not_a_close_below_it(self):
        a = arrays([(99, 100, 95, 99), (100, 101, 98, 100), (100, 102, 99, 100),
                    (100, 102, 99, 100)])
        entries = M.entry_book(a, {str(a['days'][0]): ['SYN_00']})[0]
        _, _, tr = replay(a, entries, e9=[99, 99, 99, 100])
        self.assertEqual(tr[0]['why'], 'end')

    def test_market_filter_only_reads_previous_close(self):
        a = arrays([(99, 100, 95, 99), (100, 101, 98, 100), (100, 102, 98, 100)])
        a['_ie47'] = dict(qqq=np.array([100., 90., 110.]))
        study = M.IE47Study()
        before = study.market_gate(a, {'candidate': 'E2'})
        a['_ie47']['qqq'][2] = 1
        np.testing.assert_array_equal(before, study.market_gate(a, {'candidate': 'E2'}))
        self.assertEqual(before.tolist(), [False, True, False])

    def test_risk_feedback_uses_five_closed_trades_before_today(self):
        a = arrays([(100, 101, 96, 100)] * 7)
        entries = [[(0, 0, 1, 100., 97., M.KIND, 97.)] for _ in a['days']]
        curve, _, tr = replay(a, entries, M.execution_rules('E4'))
        for k, t in enumerate(tr):
            equity = 1. if k == 0 else curve[k-1]
            risk = t['executions'][0]['shares']*3/equity
            self.assertAlmostEqual(risk, .005 if k < 5 else .0025)

    def test_account_caps_count_successful_positions_and_keep_r74_defaults_off(self):
        a = arrays([(100, 100.5, 99.5, 100)] * 5, columns=30)
        entries = [[(j, j, 1, 100., 99., M.KIND) for j in range(30)] for _ in a['days']]
        rules = replace(M.execution_rules('E1'), buy_cost=0, sell_cost=0, margin_rate=0)
        ema = {'e9': np.full_like(a['close'], 90.), 'below_e9': np.zeros_like(a['close'], bool)}
        px = {k: a[k] for k in ('open', 'high', 'low', 'close', 'codes')}
        px['dates'] = a['days']
        track = {}
        _, _, tr = Y.simulate(px, ema, rules, entries, a['days'][0], a['days'][-1], audit=True, track=track)
        self.assertEqual(max(track['new']), 4)
        self.assertEqual(max(track['open']), 11)
        self.assertLessEqual(max(track['gross']), 2.8)
        self.assertTrue(all(t['executions'][0]['shares']*100 <= .25+1e-12 for t in tr))
        self.assertFalse(Y.Rules().entry_day_exit_signal)


if __name__ == '__main__':
    unittest.main()
