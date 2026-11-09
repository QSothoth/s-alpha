import unittest

from studies.trader_replication.martin_continue_bu import describe, trigger


class TriggerAttributionTests(unittest.TestCase):
    def test_trigger_categories_are_disjoint_and_missing_is_rejected(self):
        self.assertEqual(trigger(True, False), 'pullback_only')
        self.assertEqual(trigger(False, True), 'breakout_only')
        self.assertEqual(trigger(True, True), 'both')
        with self.assertRaises(ValueError):
            trigger(False, False)

    def test_invested_weight_includes_adds_and_excludes_open_marks(self):
        rows = [dict(why='trail', ret=.2, ret_invested=.1, pnl=.2, risk_pct=.05,
                     executions=[dict(action='entry', price=1., shares=1.),
                                 dict(action='add', price=2., shares=.5)]),
                dict(why='stop', ret=-.1, ret_invested=-.1, pnl=-.1, risk_pct=.03,
                     executions=[dict(action='entry', price=1., shares=1.)]),
                dict(why='end', ret=2., ret_invested=2., pnl=.5, risk_pct=.04,
                     executions=[dict(action='entry', price=1., shares=1.)])]
        result = describe(rows)
        self.assertEqual((result['closed'], result['open_at_end']), (2, 1))
        self.assertAlmostEqual(result['weighted_invested'], .1 / 3)
        self.assertAlmostEqual(result['closed_pnl'], .1)
        self.assertAlmostEqual(result['open_mark_pnl'], .5)


if __name__ == '__main__':
    unittest.main()
