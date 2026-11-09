"""M2 replacement is transactional, only evicts losing probes, and uses completed account history."""
import unittest
from dataclasses import replace
from unittest.mock import patch

import numpy as np

from studies.martin_luk import m2_research as M
from studies.trader_replication import system as Y
from studies.trader_replication.study import Study


class M2Tests(unittest.TestCase):
    def account(self, rotate=True, winner=False, invalid=False):
        days = np.array(['2025-01-02', '2025-01-03', '2025-01-06'])
        c = np.array([[100., 100.], [101. if winner else 99., 100.], [101. if winner else 99., 100.]])
        px = dict(close=c, open=c, high=c+1, low=c-.1, dates=days, codes=np.array(['OLD', 'NEW']))
        book = [[(0, 0, 1, 100., 50., 'close')], [(0, 1, 1, 100., 101. if invalid else 90., 'close')], []]
        r = Y.Rules(risk=.5, max_gross=.5, max_position=.5, max_open=1, trail='', trims=(),
                    buy_cost=.001, sell_cost=.002, margin_rate=0., rotate_score='score' if rotate else '')
        ema = dict(score=np.array([[0., 1.], [0., 1.], [0., 1.]]))
        return Y.simulate(px, ema, r, book, days[0], days[-1], audit=True)[2]

    def test_score_rotation_replaces_only_a_lower_score_losing_probe(self):
        trades = self.account()
        self.assertEqual([(t['code'], t['why']) for t in trades], [('OLD', 'make_room'), ('NEW', 'end')])
        self.assertTrue(any(e['action'] == 'entry' for e in trades[1]['executions']))
        self.assertEqual([t['code'] for t in self.account(rotate=False)], ['OLD'])
        self.assertEqual([t['code'] for t in self.account(winner=True)], ['OLD'])

    def test_rejected_replacement_leaves_original_position_untouched(self):
        trades = self.account(invalid=True)
        self.assertEqual([(t['code'], t['why']) for t in trades], [('OLD', 'end')])
        self.assertEqual([e['action'] for e in trades[0]['executions']], ['entry', 'end'])

    def test_equity_mean_changes_only_new_risk_after_enough_completed_closes(self):
        days = np.array(['2025-01-02', '2025-01-03', '2025-01-06', '2025-01-07'])
        c = np.array([[100., 100.], [90., 100.], [90., 100.], [90., 100.]])
        px = dict(close=c, open=c, high=c+1, low=c-.01, dates=days, codes=np.array(['A', 'B']))
        book = [[(0, 0, 1, 100., 50., 'close')], [], [(0, 1, 1, 100., 90., 'close')], []]
        r = Y.Rules(risk=.01, max_gross=5., max_position=1., trail='', trims=(),
                    buy_cost=0., sell_cost=0., margin_rate=0.)
        def shares(rules):
            ts = Y.simulate(px, {}, rules, book, days[0], days[-1], audit=True)[2]
            return next(t for t in ts if t['code'] == 'B')['executions'][0]['shares']
        self.assertAlmostEqual(shares(replace(r, equity_ma_days=2)), shares(r)*.5)
        self.assertEqual(shares(replace(r, equity_ma_days=3)), shares(r))
        self.assertEqual(Y.Rules().equity_ma_days, 0)
        self.assertEqual(Y.Rules().rotate_score, '')

    def test_named_score_is_available_to_generic_study(self):
        score = np.ones((2, 1))
        self.assertIs(Study().ema_inputs({'score': score}, None, Y.Rules(trail='', rotate_score='score'))['score'], score)

    def test_selection_takes_drawdown_before_H_after_equal_purity(self):
        def row(dd, h=10.):
            return dict(H=h, cap_equity=.2, years={y: dict(target_count=0, cap_equity=.2,
                purity_gross=.3, maxdd=dd, targets=dict(checks=dict(trades=True, win=True)))
                for y in ('2024', '2025')})
        selected = M.select(dict(A=row(.6, 11.), B=row(.5)), dict(H=5., cap_equity=.1))
        self.assertEqual(selected['chosen'], 'B')

    def test_decisions_do_not_read_evaluation_labels(self):
        with patch.object(M.M.mainleg, 'summary_account', side_effect=AssertionError('labels in account')):
            self.assertEqual(len(self.account()), 2)


if __name__ == '__main__':
    unittest.main()
