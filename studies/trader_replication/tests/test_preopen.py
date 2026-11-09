import unittest

from studies.trader_replication.preopen import plan
from studies.trader_replication.system import Rules


def order(rank, j, kind='n1'):
    return ((rank,), j, 1, 9., kind, None, None, None, None)


class PreopenReservationTests(unittest.TestCase):
    def test_unfilled_first_order_cannot_release_its_reservation(self):
        rules = Rules(risk=.5, max_position=1., max_gross=1., gross_cost=True, buy_cost=.001)
        result = plan([order(0, 0), order(1, 1)], [], [10., 10.], 1., 1., rules, .5, 0)
        self.assertEqual(set(result['entries']), {('n1', 0)})
        self.assertEqual(result['trace'][1]['reason'], 'risk_or_budget')
        submitted = result['entries'][('n1', 0)]
        self.assertLessEqual(submitted['shares'] * submitted['limit'] * (1 + rules.buy_cost), 1.)

    def test_held_name_and_capacity_are_reserved_even_if_exit_is_pending(self):
        rules = Rules(risk=.1, max_position=1., max_gross=2., max_open=1)
        holding = {'j': 0, 'code': 'US.A', 'kind': 'n1', 'side': 1, 'shares': .02,
                   'shares0': .02, 'mark': 10., 'pending': None, 'trail_pending': True,
                   'entry_index': 0, 'management': rules, 'cap': 1., 'add_mult': None}
        result = plan([order(0, 1)], [holding], [10., 10.], 1., .8, rules, .1, 0)
        self.assertFalse(result['entries'])
        self.assertEqual(result['trace'][0]['reason'], 'position_limit')

    def test_pending_add_is_reserved_before_new_entry(self):
        rules = Rules(risk=.5, max_position=1., max_gross=1., gross_cost=True, buy_cost=0., add_frac=1.)
        holding = {'j': 0, 'code': 'US.A', 'kind': 'list', 'side': 1, 'shares': .04,
                   'shares0': .04, 'mark': 10., 'pending': 10., 'trail_pending': False,
                   'entry_index': 0, 'management': rules, 'cap': 1., 'add_mult': None}
        result = plan([order(0, 1)], [holding], [10., 10.], 1., .6, rules, .5, 0)
        self.assertEqual(result['trace'][0]['type'], 'add')
        self.assertAlmostEqual(result['adds'][0]['shares'], .04)
        self.assertLessEqual(sum(x['shares'] * x['limit'] for x in result['adds'].values()) +
                             sum(x['shares'] * x['limit'] for x in result['entries'].values()), .6 + 1e-12)

    def test_priority_and_prior_stop_control_quantity(self):
        rules = Rules(risk=.01, max_position=1., max_gross=2., max_new_long=1)
        result = plan([order(1, 1), order(0, 0)], [], [10., 10.], 1., 1., rules, .01, 0)
        planned = result['entries'][('n1', 0)]
        self.assertAlmostEqual(planned['shares'] * (planned['limit'] - 9.), .01)
        self.assertEqual(result['trace'][1]['reason'], 'long_daily_limit')


class OpeningAccountTests(unittest.TestCase):
    @staticmethod
    def run_sim(opening, lows, book, rules):
        import numpy as np
        from studies.trader_replication.system import simulate
        dates = np.array([f'2025-01-{i + 1:02d}' for i in range(len(opening))])
        op = np.array(opening, float)
        low = np.array(lows, float)
        px = {'dates': dates, 'codes': np.array([f'US.{i}' for i in range(op.shape[1])]),
              'open': op, 'high': np.maximum(op, 12.), 'low': low, 'close': op.copy()}
        track = {}
        _, _, trades = simulate(px, {}, rules, book, dates[1], dates[-1], audit=True, track=track, preopen=True)
        return trades, track

    def test_expired_opening_order_does_not_release_reserved_cash(self):
        rules = Rules(risk=.5, max_position=1., max_gross=1., max_open=6, gross_cost=True,
                      intraday_kinds=('n1',), trail='', trims=(), buy_cost=0., sell_cost=0., margin_rate=0.)
        book = [[], [((0,), 0, 1, 11., 9., 'n1', None), ((1,), 1, 1, 10., 9., 'n1', None)]]
        trades, track = self.run_sim([[10., 10.], [11., 10.]], [[10., 10.], [10., 10.]], book, rules)
        self.assertEqual(trades, [])
        rows = track['preopen_plans'][0]['orders']
        self.assertEqual(rows[0]['execution'], 'limit_expired')
        self.assertEqual(rows[1]['reason'], 'risk_or_budget')

    def test_gap_below_stop_is_bought_then_stress_exited(self):
        rules = Rules(risk=.01, max_position=1., max_gross=1., gross_cost=True,
                      intraday_kinds=('n1',), trail='', trims=(), buy_cost=0., sell_cost=0., margin_rate=0.)
        book = [[], [((0,), 0, 1, 8., 9., 'n1', 7.5)]]
        trades, track = self.run_sim([[10.], [8.]], [[10.], [7.5]], book, rules)
        self.assertEqual((trades[0]['fill'], trades[0]['why'], trades[0]['executions'][-1]['price']),
                         (8., 'stop_day0', 7.5))
        self.assertEqual(track['preopen_plans'][0]['orders'][0]['execution'], 'gap_stress')
        self.assertAlmostEqual(trades[0]['r'], -.5 / 1.5)

    def test_opening_price_does_not_change_the_prior_share_plan(self):
        rules = Rules(risk=.1, max_position=1., max_gross=2., intraday_kinds=('n1',),
                      trail='', trims=(), buy_cost=0., sell_cost=0., margin_rate=0.)
        def run(opening):
            book = [[], [((0,), 0, 1, opening, 9., 'n1', None)]]
            return self.run_sim([[10.], [opening]], [[10.], [min(opening, 10.)]], book, rules)[1]
        low = run(9.5)['preopen_plans'][0]['orders'][0]
        high = run(11.)['preopen_plans'][0]['orders'][0]
        self.assertEqual((low['shares'], low['limit']), (high['shares'], high['limit']))
        self.assertEqual((low['execution'], high['execution']), ('filled', 'limit_expired'))

    def test_preconfirmed_add_does_not_depend_on_next_open_trigger(self):
        rules = Rules(risk=.1, max_position=1., max_gross=2., gross_cost=True,
                      intraday_kinds=('n1',), trail='', trims=(), buy_cost=0., sell_cost=0.,
                      margin_rate=0., add_levels=(1,), add_next_open=True, add_frac=.2)
        book = [[], [((0,), 0, 1, 10., 9., 'n1', None)], [], []]
        trades, track = self.run_sim([[10.], [10.], [12.], [10.5]],
                                     [[10.], [10.], [10.], [10.]], book, rules)
        adds = [e for t in trades for e in t['executions'] if e['action'] == 'add']
        self.assertEqual(len(adds), 1)
        self.assertEqual(adds[0]['price'], 10.5)
        rec = track['preopen_plans'][2]['orders'][0]
        self.assertGreater(rec['level'], 10.5)
        self.assertEqual(rec['execution'], 'preopen_filled')

    def test_open_stop_precision_boundary_remains_unknown(self):
        rules = Rules(risk=.1, max_position=1., max_gross=1., gross_cost=True,
                      intraday_kinds=('n1',), trail='', trims=(), buy_cost=0., sell_cost=0., margin_rate=0.)
        book = [[], [((0,), 0, 1, 9., 9., 'n1', 8.5)]]
        trades, track = self.run_sim([[10.], [9.]], [[10.], [8.5]], book, rules)
        self.assertEqual(trades, [])
        self.assertEqual(track['preopen_plans'][0]['orders'][0]['execution'], 'precision_unknown')

    def test_pending_exit_does_not_fund_a_same_open_entry(self):
        rules = Rules(risk=.1, max_position=1., max_gross=1., max_open=1, gross_cost=True,
                      intraday_kinds=('n1',), trail='', trims=(), buy_cost=0., sell_cost=0., margin_rate=0.)
        book = [[], [((0,), 0, 1, 10., 9., 'n1', None)], [((0,), 1, 1, 10., 9., 'n1', None)]]
        trades, track = self.run_sim([[10., 10.], [10., 10.], [8., 10.]],
                                     [[10., 10.], [10., 10.], [8., 10.]], book, rules)
        self.assertEqual([(t['code'], t['why']) for t in trades], [('US.0', 'gap_stop')])
        self.assertEqual(track['preopen_plans'][1]['orders'][0]['reason'], 'position_limit')


if __name__ == '__main__':
    unittest.main()
