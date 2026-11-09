"""E20 causal nomination, bounded correlation groups and shared-watch behavior."""
from datetime import date, timedelta
import unittest

import numpy as np

from studies.martin_luk import e20_research as E20


def panel(n=80, width=4):
    c = np.tile(np.linspace(10., 15., n)[:, None], (1, width))
    days = np.array([str(date(2024, 1, 1)+timedelta(days=d)) for d in range(n)])
    return dict(days=days, codes=np.array([f'US.X{j}' for j in range(width)]),
                open=c*.995, high=c*1.001, low=c*.99, close=c,
                adr=np.full_like(c, 6.), e9=c*.99, e21=c*.98, e50=c*.97)


class E20Tests(unittest.TestCase):
    def test_only_earlier_ie47_names_reenter_and_future_cannot_change_events(self):
        A = panel()
        indices = list(range(65, 80))
        R = dict(night_indices=indices, scopes=[np.arange(4) for _ in indices], regime=np.zeros(80),
                 picks={str(A['days'][t]): ['US.X0'] if t == 65 else [] for t in indices})
        events = E20.event_rows(A, R, end='9999')
        self.assertTrue(all(not v for v in events[str(A['days'][65])].values()))
        self.assertEqual(events[str(A['days'][66])]['potent'], ['US.X0'])
        self.assertTrue(all(set(v) <= {'US.X0'} for row in events.values() for v in row.values()))
        A['close'][75:] *= 3
        for key in ('e9', 'e21', 'e50'):
            del A[key]
        # Use the same causal EMA inputs in both versions.
        B = panel()
        for key in ('e9', 'e21', 'e50'):
            del B[key]
        before = E20.event_rows(B, R, end='9999')
        after = E20.event_rows(A, R, end='9999')
        cut = str(A['days'][75])
        self.assertEqual({d: r for d, r in before.items() if d < cut},
                         {d: r for d, r in after.items() if d < cut})

    def test_reentry_cap_preserves_three_base_names_and_leader_cooldown(self):
        A = panel(width=7)
        indices = range(30, 43)
        rows = {str(A['days'][t]): dict(upgrade=[], potent=[], leader=['US.X3', 'US.X4', 'US.X5', 'US.X6'], theme=[])
                for t in indices}
        R = dict(picks={d: ['US.X0', 'US.X1', 'US.X2'] for d in rows})
        picks, extras = E20.nominations(A, R, rows, ('leader',), 3)
        ds = list(rows)
        self.assertEqual(picks[ds[0]][:3], R['picks'][ds[0]])
        self.assertEqual(extras[ds[0]], ['US.X3', 'US.X4', 'US.X5'])
        self.assertEqual(extras[ds[1]], ['US.X6'])
        self.assertFalse(extras[ds[2]])
        self.assertEqual(extras[ds[10]], extras[ds[0]])
        self.assertTrue(all(len(x) <= 3 for x in extras.values()))

    def test_breakout_book_matches_existing_and_first_break_consumes_watch(self):
        A = panel(n=9, width=1)
        A['high'] = A['close']*.999
        picks = {str(A['days'][1]): ['US.X0']}
        expected = E20.M.entry_book(A, picks, **E20.M.E6['E6c'])[0]
        actual = E20.watch_book(A, picks)[0]
        self.assertEqual(actual, expected)
        self.assertEqual([d for d, r in enumerate(actual) if r], [2])
        A['adr'][1] = 1.
        book, events = E20.watch_book(A, picks)
        self.assertFalse(any(book))
        self.assertFalse(events[0]['valid'])

    def test_twenty_one_reclaim_is_next_session_and_consumes_same_watch(self):
        A = panel(n=7, width=1)
        A['high'][:] = 30.
        A['close'][:] = 11.
        A['open'][:] = 11.5
        A['low'][:] = 9.
        A['e9'][:] = 12.
        A['e21'][:] = 10.
        picks = {str(A['days'][1]): ['US.X0']}
        self.assertFalse(any(E20.watch_book(A, picks)[0]))
        book, _ = E20.watch_book(A, picks, True)
        self.assertEqual([d for d, r in enumerate(book) if r], [2])
        self.assertEqual(book[2][0][5], E20.M.PB_KIND)

    def test_theme_requires_two_correlated_event_seeds_and_complete_history(self):
        n = 80
        x = np.arange(n-1)
        returns = .005+.02*np.sin(x)
        c = np.r_[10., 10.*np.cumprod(1+returns)]
        opposite = np.r_[10., 10.*np.cumprod(1-returns)]
        closes = np.column_stack((c, c*2, c*3, opposite))
        known = np.ones(4, bool)
        self.assertEqual(E20.theme_names(closes, 70, {0, 1}, known), {2})
        self.assertFalse(E20.theme_names(closes, 70, {0}, known))
        closes[45, 2] = np.nan
        self.assertFalse(E20.theme_names(closes, 70, {0, 1}, known))

    def test_combined_scan_prioritizes_state_upgrade_before_monthly_rank(self):
        A = panel()
        day = str(A['days'][35])
        row = {day: dict(upgrade=['US.X3'], potent=['US.X2'], leader=['US.X0', 'US.X1'], theme=[])}
        R = dict(picks={day: []})
        plain = E20.nominations(A, R, row, E20.TYPES[:3], 1)[1][day]
        priority = E20.nominations(A, R, row, E20.TYPES[:3], 1, True)[1][day]
        self.assertEqual(plain, ['US.X0'])
        self.assertEqual(priority, ['US.X3'])

    def test_only_s1_execution_participates_in_selection_and_all_gates_stay_fixed(self):
        summary = {'BASE_train': dict(by_year={'2024': .7, '2025': .6}, maxdd=.3, midpoint_his=12)}
        for name in E20.SPECS:
            summary[name+'_S1_train'] = dict(by_year={'2024': .8, '2025': .8}, maxdd=.3, midpoint_his=11)
            summary[name+'_BASE_train'] = dict(by_year={'2024': 2., '2025': 2.}, maxdd=.2, midpoint_his=20)
        self.assertEqual(E20.select(summary), ([], None))
        summary['A2_S1_train']['midpoint_his'] = 12
        self.assertEqual(E20.select(summary), (['A2'], 'A2'))
        summary['A2_S1_train']['by_year']['2025'] = .599999
        self.assertEqual(E20.select(summary), ([], None))
        summary['A2_S1_train']['by_year']['2025'] = .8
        summary['A2_S1_train']['maxdd'] = .500001
        self.assertEqual(E20.select(summary), ([], None))

    def test_near_tie_uses_midpoint_and_then_number(self):
        summary = {'BASE_train': dict(by_year={'2024': .7, '2025': .7}, maxdd=.3, midpoint_his=12)}
        for name in E20.SPECS:
            summary[name+'_S1_train'] = dict(by_year={'2024': .8, '2025': .8}, maxdd=.3, midpoint_his=12)
        summary['A2_S1_train']['midpoint_his'] = 13
        summary['A3_S1_train']['midpoint_his'] = 13
        self.assertEqual(E20.select(summary)[1], 'A2')

    def test_paired_executions_keep_the_same_primary_entries_and_fixed_limits(self):
        A = panel(n=9)
        days = list(map(str, A['days']))
        R = dict(picks={day: ['US.X0'] if i == 1 else [] for i, day in enumerate(days)})
        A['_e20_events'] = {day: {k: ['US.X1'] if k == 'upgrade' and i == 2 else [] for k in E20.TYPES}
                           for i, day in enumerate(days)}
        base, _ = E20.watch_book(A, R['picks'])
        original = base, E20.M.e8_rules('E8c'), np.zeros_like(A['close'], bool), np.zeros_like(A['close'], bool)
        with E20.E19.runtime():
            plain, _ = E20.configure(A, original, R, 'A1_BASE')
            retry, _ = E20.configure(A, original, R, 'A1_S1')
        self.assertEqual([[e for e in row if e[5] != E20.E16.RETRY_KIND] for row in retry], plain)
        rules = A['_e14_base'][1]
        self.assertEqual(rules.max_open_by_kind, {E20.E16.RETRY_KIND: 2})
        self.assertEqual((rules.max_open, rules.max_new_long), (11, 4))
        self.assertFalse(rules.make_room_confirmed)


if __name__ == '__main__':
    unittest.main()
