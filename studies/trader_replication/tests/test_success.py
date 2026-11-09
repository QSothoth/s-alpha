"""P1 behaviour/account hard lines; random diagnostics cannot veto success."""
import unittest

import numpy as np

from studies.trader_replication import success as S

CARD = dict(per_year=100, source='interview 2025 @12:00', behaviour=dict(win=.25, days_win=10.0),
            years={'2024': 1.0})
OURS = dict(gate=dict(data=True, lookahead=True, fills=True), win=.24, closed=200, per_year=110, counts={'2024': 110},
            behaviour=dict(win=.24, days_win=12.0), years={'2024': .8}, total=.9, placebo_median=.1,
            validate_total=-.05, validate_placebo_median=-.1, total_drop2=.3)


def verdict(card=CARD, **ours):
    return dict((r, ok) for r, ok, _ in S.judge(card, dict(OURS, **ours)))


class SuccessTests(unittest.TestCase):
    def test_current_success_rules_pass(self):
        rows = S.judge(CARD, OURS)
        self.assertEqual([r for r, _, _ in rows],
                         ['gate', 'count', 'behaviour', 'years', 'nonnegative'])
        self.assertTrue(S.passed(rows))

    def test_win_rate_ceiling_holds_for_every_style(self):
        self.assertFalse(verdict(win=.36)['gate'])

    def test_unchecked_gate_fails(self):
        self.assertFalse(verdict(gate=dict(data=True, lookahead=None, fills=True))['gate'])

    def test_one_trade_a_week_floor(self):
        self.assertFalse(verdict(dict(CARD, per_year=40), counts={'2024': 40})['count'])

    def test_match_only_sourced_count_and_enforce_each_year(self):
        self.assertTrue(verdict(dict(CARD, source=''), counts={'2024': 140})['count'])
        self.assertFalse(verdict(counts={'2024': 121})['count'])
        self.assertTrue(verdict(counts={'2024': 120})['count'])
        self.assertTrue(verdict(dict(CARD, per_year=(80, 150)), counts={'2024': 140})['count'])
        self.assertFalse(verdict(counts={'2024': 200, '2025': 51}, years={'2024': .8, '2025': .5})['count'])
        self.assertFalse(verdict(counts={})['count'])

    def test_his_year_within_log_point_three(self):
        self.assertTrue(verdict(years={'2024': .5})['years'])          # log(2 / 1.5) = 0.29
        self.assertFalse(verdict(years={'2024': .4})['years'])

    def test_random_validation_and_top_two_are_diagnostics(self):
        self.assertTrue(all(verdict(validate_total=-.2, total_drop2=-1., placebo_median=100).values()))

    def test_nonnegative_and_sourced_behaviour_cannot_be_missing(self):
        self.assertFalse(verdict(years={'2024': -.01})['nonnegative'])
        self.assertFalse(verdict(behaviour={})['behaviour'])
        self.assertFalse(verdict(behaviour=dict(days_win=12.1))['behaviour'])
        self.assertTrue(verdict(behaviour=dict(days_win=12.0))['behaviour'])

    def test_drop_top_removes_the_two_best_entries(self):
        A = dict(days=np.array(['2024-01-02', '2024-01-03']), codes=np.array(['US.A', 'US.B', 'US.C']))
        entries = [[(0, 0, 1, 10., 9., 'k', None), (0, 1, 1, 10., 9., 'k', None)], [(0, 2, 1, 10., 9., 'k', None)]]
        trades = [dict(code='US.A', entry='2024-01-02', ret=.5, why='trail'),
                  dict(code='US.B', entry='2024-01-02', ret=-.1, why='stop'),
                  dict(code='US.C', entry='2024-01-03', ret=2.0, why='trail')]
        out = S.drop_top(A, entries, trades)
        self.assertEqual([[e[1] for e in lst] for lst in out], [[1], []])


if __name__ == '__main__':
    unittest.main()
