import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from studies.martin_luk import e16_research as E16  # noqa: E402


def panel(closes, highs=None, lows=None):
    c = np.asarray(closes, float)[:, None]
    h = np.asarray(highs, float)[:, None] if highs is not None else c*1.01
    l = np.asarray(lows, float)[:, None] if lows is not None else c*.99
    n = len(c)
    return dict(days=[f'2024-01-{d+1:02d}' for d in range(n)], codes=['US.X'], high=h, low=l, close=c,
                adr=np.full((n, 1), 6.))


class PersistentBook(unittest.TestCase):
    def test_trigger_on_session_after_pick_and_again_after_a_stop(self):
        closes = [10, 10, 10.5, 10.2, 10.9, 11.5]
        A = panel(closes)
        line = np.zeros_like(A['close'])
        book, _ = E16.persistent_book(A, {'2024-01-02': ['US.X']}, line)
        days = [d for d, row in enumerate(book) if row]
        # picked the night of day 1: day 2 is the first possible trigger; day 3 closes below day 2's high
        self.assertEqual(days, [2, 4, 5])
        self.assertEqual(book[2][0][3], 10.5)

    def test_renew_needs_a_close_above_every_high_since_the_last_trigger(self):
        closes = [10, 10, 11, 10, 10.6, 11.2]
        highs = [10.1, 10.1, 11.3, 10.1, 10.7, 11.4]
        A = panel(closes, highs)
        line = np.zeros_like(A['close'])
        plain, _ = E16.persistent_book(A, {'2024-01-02': ['US.X']}, line)
        renew, _ = E16.persistent_book(A, {'2024-01-02': ['US.X']}, line, renew=True)
        self.assertEqual([d for d, r in enumerate(plain) if r], [2, 4, 5])
        # day 4 closes 10.6 under day 2's 11.3 high; day 5 closes 11.2, still under 11.3
        self.assertEqual([d for d, r in enumerate(renew) if r], [2])

    def test_close_below_the_line_removes_the_name_the_session_after(self):
        closes = [10, 10, 10.5, 9, 11, 12]
        A = panel(closes)
        line = np.full_like(A['close'], 9.5)
        book, sizes = E16.persistent_book(A, {'2024-01-02': ['US.X']}, line)
        self.assertEqual([d for d, r in enumerate(book) if r], [2])
        self.assertEqual(sizes, [0, 1, 1, 0, 0])

    def test_pick_night_close_does_not_remove(self):
        closes = [10, 9, 10.5]
        A = panel(closes)
        line = np.full_like(A['close'], 9.5)
        book, _ = E16.persistent_book(A, {'2024-01-02': ['US.X']}, line)
        self.assertEqual([d for d, r in enumerate(book) if r], [2])

    def test_width_drops_the_earliest_pick(self):
        n = 6
        A = dict(days=[f'2024-01-{d+1:02d}' for d in range(n)], codes=['US.A', 'US.B', 'US.C'],
                 close=np.tile(np.arange(10, 10+n, dtype=float)[:, None], 3), adr=np.full((n, 3), 6.))
        A['high'], A['low'] = A['close']*1.001, A['close']*.99
        picks = {'2024-01-01': ['US.A'], '2024-01-02': ['US.B'], '2024-01-03': ['US.C']}
        book, sizes = E16.persistent_book(A, picks, np.zeros_like(A['close']), width=2)
        self.assertEqual(max(sizes), 2)
        late = {A['codes'][e[1]] for row in book[4:] for e in row}
        self.assertEqual(late, {'US.B', 'US.C'})
        # the most recent pick comes first on a shared day
        self.assertEqual([A['codes'][e[1]] for e in book[4]], ['US.C', 'US.B'])

    def test_unlimited_width_keeps_every_pick(self):
        n = 6
        A = dict(days=[f'2024-01-{d+1:02d}' for d in range(n)], codes=['US.A', 'US.B', 'US.C'],
                 close=np.tile(np.arange(10, 10+n, dtype=float)[:, None], 3), adr=np.full((n, 3), 6.))
        A['high'], A['low'] = A['close']*1.001, A['close']*.99
        picks = {'2024-01-01': ['US.A'], '2024-01-02': ['US.B'], '2024-01-03': ['US.C']}
        _, sizes = E16.persistent_book(A, picks, np.zeros_like(A['close']), width=None)
        self.assertEqual(sizes, [1, 2, 3, 3, 3])

    def test_same_night_rank_survives_engine_priority_sort(self):
        A = dict(days=['2024-01-01', '2024-01-02'], codes=['US.A', 'US.Z'],
                 close=np.array([[10., 10.], [11., 11.]]), adr=np.full((2, 2), 6.))
        A['high'], A['low'] = A['close']*1.01, A['close']*.99
        book, _ = E16.persistent_book(A, {'2024-01-01': ['US.Z', 'US.A']},
                                     np.zeros_like(A['close']))
        ordered = sorted(book[1], key=lambda entry: entry[0])
        self.assertEqual([A['codes'][entry[1]] for entry in ordered], ['US.Z', 'US.A'])

    def test_overlay_keeps_the_base_and_puts_retries_last(self):
        closes = [10, 10, 10.5, 10.2, 10.9, 11.5]
        A = panel(closes)
        line = np.zeros_like(A['close'])
        base = [[] for _ in closes]
        base[2] = [((0, 1, 'US.X'), 0, 1, 10.5, 10.4, 'ie47_close_pdh', None)]
        out, _, retries = E16.overlay_book(A, base, {'2024-01-02': ['US.X']}, line)
        self.assertEqual(out[2], base[2])           # no duplicate of the base entry
        self.assertEqual(retries, 2)
        self.assertEqual([e[5] for e in out[4]+out[5]], [E16.RETRY_KIND]*2)
        self.assertGreaterEqual(out[4][0][0][0], 1000)

    def test_pool_gate_uses_the_previous_night(self):
        closes = [10, 10, 10.5, 10.2, 10.9, 11.5]
        A = panel(closes)
        pool = np.ones_like(A['close'], bool)
        pool[3] = False
        book, _ = E16.persistent_book(A, {'2024-01-02': ['US.X']}, np.zeros_like(A['close']), pool=pool)
        self.assertEqual([d for d, r in enumerate(book) if r], [2, 5])

    def test_e18_caps_survive_the_c062_rule_layers(self):
        from studies.martin_luk import e15_research as E15, ie47_e1 as M
        base = E16.arm_rules(M.e8_rules('E8c'), 'R5')
        k2 = E15.P.B.X.rule_layers(base, ('AS', 'X1'))
        c062 = E15.candidate_rules(k2, E15.SPECS['C062'])
        self.assertEqual(c062.max_open_by_kind, {E16.RETRY_KIND: 3})
        self.assertEqual(c062.max_new_by_kind, {E16.RETRY_KIND: 1})
        self.assertEqual(c062.max_open, 11)
        self.assertEqual(E16.arm_rules(M.e8_rules('E8c'), 'Q1').max_open_by_kind, {})

    def test_e18_type_caps_leave_other_entry_types_available(self):
        from studies.trader_replication import system as Y
        p = dict(dates=np.array(['2024-01-02', '2024-01-03']),
                 codes=np.array([f'US.X{j}' for j in range(8)]))
        for field in ('open', 'high', 'low', 'close'):
            p[field] = np.full((2, 8), 10.)
        def entry(j, retry=False):
            return ((1000 if retry else 0, j), j, 1, 10., 9.5,
                    E16.RETRY_KIND if retry else 'ie47_close_pdh', None)
        rules = Y.Rules(max_open=11, max_new_long=4, risk=.0001, trims=(),
                        buy_cost=0, sell_cost=0, margin_rate=0)
        book = [[entry(0, True), entry(1, True), entry(2, True), entry(3, True)],
                [entry(4), entry(5), entry(6), entry(7, True)]]
        _, _, rows = Y.simulate(p, {}, E16.arm_rules(rules, 'R1'), book, *p['dates'])
        self.assertEqual(sum(t['kind'] == E16.RETRY_KIND for t in rows), 3)
        self.assertEqual(sum(t['kind'] != E16.RETRY_KIND for t in rows), 3)
        book = [[entry(j) for j in range(4)]+[entry(4, True), entry(5, True)], []]
        _, _, rows = Y.simulate(p, {}, E16.arm_rules(rules, 'R5'), book, *p['dates'])
        self.assertEqual(sum(t['kind'] == E16.RETRY_KIND for t in rows), 1)
        self.assertEqual(sum(t['kind'] != E16.RETRY_KIND for t in rows), 4)

    def test_e18_review_keeps_end_marks_in_the_live_position_count(self):
        from studies.martin_luk import e18_review
        rows = [dict(entry='2024-01-02', exit='2024-01-03', why='end', kind=E16.RETRY_KIND),
                dict(entry='2024-01-02', exit='2024-01-03', why='stop', kind='base'),
                dict(entry='2024-01-03', exit='2024-01-03', why='end', kind='base')]
        day = e18_review.daily_positions(rows, ['2024-01-03'])['2024-01-03']
        self.assertEqual((day['at_open'], day['before_entries'], day['at_close']), (2, 1, 2))
        self.assertEqual((day['retry_at_close'], day['new_base']), (1, 1))

    def test_e18_selection_keeps_the_midpoint_gate(self):
        from studies.martin_luk import e18_review
        runs = {name+'_train': dict(by_year={'2024': .8, '2025': .8}, maxdd=.2, midpoint_his=11)
                for name in ('BASE',)+tuple(E16.E18)}
        self.assertEqual(e18_review.select(runs), ([], None))
        runs['R1_train']['midpoint_his'] = 12
        self.assertEqual(e18_review.select(runs), (['R1'], 'R1'))

    def test_no_future_bars_change_past_entries(self):
        rng = np.random.default_rng(3)
        closes = 10*np.cumprod(1+rng.normal(0, .03, 40))
        A = panel(closes)
        line = np.zeros_like(A['close'])
        picks = {A['days'][k]: ['US.X'] for k in (3, 15)}
        full, _ = E16.persistent_book(A, picks, line)
        cut = {k: v[:25] if hasattr(v, 'shape') else v[:25] if k == 'days' else v for k, v in A.items()}
        part, _ = E16.persistent_book(cut, {d: p for d, p in picks.items() if d in cut['days']}, line[:25])
        self.assertEqual(full[:25], part)


if __name__ == '__main__':
    unittest.main()
