"""E14 structural-stop sizing and close-management timing, registered before implementation."""
from dataclasses import replace
import unittest

import numpy as np

from studies.trader_replication import system as Y
from studies.trader_replication.tests.test_proof_risk import replay


class StructuralRiskTests(unittest.TestCase):
    def test_float32_quotes_do_not_round_the_risk_denominator(self):
        price, stop = np.float32(98.89), 96.57296904195422
        cash, shares, budget = -.04, .0004, .005
        extra = Y.risk_limited_shares(cash, shares, price, stop, budget, .0005, .0005)
        pnl = cash-extra*float(price)*1.0005 + (shares+extra)*stop*.9995
        self.assertGreaterEqual(pnl, -budget-1e-14)

    def test_float32_portfolio_prices_preserve_the_actual_cash_risk_cap(self):
        b = np.array([(100, 100, 100, 100), (100, 101.3, 94.3, 101.23),
                      (101.7, 105.8, 101.6, 105.43), (106.1, 109.4, 105.7, 108.11)], np.float32)
        px = {k: b[:, i:i+1] for i, k in enumerate(('open', 'high', 'low', 'close'))}
        px.update(dates=np.array(['2024-01-02', '2024-01-03', '2024-01-04', '2024-01-05']), codes=np.array(['X']))
        rules = Y.Rules(risk=.0025, max_position=.3, max_gross=2.8, trail='', trims=(),
                        probe_hard_mult=2., proof_risk=True, proof_stop='low', proof_target_mult=2.,
                        proof_add_signal='again')
        book = [[((0,), 0, 1, 100., 97., 'unit', None)], [], [], []]
        trade = Y.simulate(px, {'again': np.ones((4, 1), bool)}, rules, book,
                           px['dates'][0], px['dates'][-1], audit=True)[2][0]
        cash, shares = 0., 0.
        for e in trade['executions']:
            if e['action'] in ('entry', 'add'):
                cash -= e['shares']*e['price']*(1+rules.buy_cost)
                shares += e['shares']
            elif e['action'] != 'end':
                cash += e['shares']*e['price']*(1-rules.sell_cost)
                shares -= e['shares']
            if e['action'] == 'add':
                self.assertGreaterEqual(cash+shares*e['stop']*(1-rules.sell_cost), -trade['risk_budget']-1e-14)

    def test_budget_reduces_shares_instead_of_lowering_the_structural_stop(self):
        t, _, _ = replay([(100, 100, 100, 100), (99, 102, 94.5, 101)],
                         proof_stop='low', proof_target_mult=2.)
        add = next(e for e in t['executions'] if e['action'] == 'add')
        self.assertEqual(add['stop'], 97.)
        self.assertLess(add['shares'] + t['executions'][0]['shares'], 2*.0025/3)
        self.assertAlmostEqual(add['risk_at_stop'], t['risk_budget'])

    def test_remaining_probe_over_budget_stays_unconfirmed(self):
        t, _, _ = replay([(100, 100, 100, 100), (100, 102, 98, 101)],
                         proof_stop='low', proof_target_mult=2., buy_cost=.1, sell_cost=.1)
        self.assertFalse(t['confirmed'])
        self.assertEqual([e['action'] for e in t['executions']], ['entry', 'end'])

    def test_fees_and_realized_trim_cash_are_in_the_share_limit(self):
        shares = Y.risk_limited_shares(-.03, .0003, 102., 98., .005, .001, .002)
        result = -.03-shares*102*1.001 + (.0003+shares)*98*.998
        self.assertAlmostEqual(result, -.005)
        self.assertGreater(Y.risk_limited_shares(-.029, .0003, 102., 98., .005, .001, .002), shares)

    def test_confirmation_uses_day_low_and_fill_variant_uses_original_fill(self):
        bars = [(100, 100, 100, 100), (101, 103, 101, 102)]
        low = replay(bars, proof_stop='low', proof_target_mult=2.)[0]
        fill = replay(bars, proof_stop='fill', proof_target_mult=2.)[0]
        self.assertEqual(next(e['stop'] for e in low['executions'] if e['action'] == 'add'), 101.)
        self.assertEqual(next(e['stop'] for e in fill['executions'] if e['action'] == 'add'), 100.)

    def test_add_day_low_is_effective_tomorrow_and_stops_only_rise(self):
        t, _, _ = replay([(100, 100, 100, 100), (100, 103, 98, 102),
                          (102, 105, 101, 104), (104, 105, 100, 104)],
                         proof_stop='low', proof_target_mult=2.)
        adds = [e for e in t['executions'] if e['action'] == 'add']
        self.assertEqual([e['stop'] for e in adds], [98., 101.])
        self.assertEqual((t['days'], t['why']), (3, 'stop'))
        self.assertFalse(any(e['time'] == t['exit'] and e['action'] == 'add' for e in t['executions']))

    def test_r_levels_are_after_proof_and_consume_rejected_levels(self):
        t, _, _ = replay([(100, 100, 100, 100), (100, 102, 99, 101),
                          (102, 107, 101, 106), (107, 113, 106, 112)],
                         proof_stop='low', proof_target_mult=2., proof_add_signal='', add_levels=(2, 4))
        adds = [e for e in t['executions'] if e['action'] == 'add']
        self.assertEqual([e['time'] for e in adds], ['2025-01-03', '2025-01-04', '2025-01-05'])
        self.assertEqual(t['add_tries'], 2)
        self.assertEqual(t['proof_adds'], 2)
        rejected = replay([(100, 100, 100, 100), (100, 102, 99, 101),
                           (102, 107, 101, 106), (107, 109, 106, 108)],
                          proof_stop='low', proof_target_mult=2., proof_add_signal='',
                          add_levels=(2, 4), max_position=.05)[0]
        self.assertEqual(rejected['add_tries'], 1)
        self.assertEqual(rejected['proof_adds'], 0)

    def test_sc2_preserves_small_size_but_restores_intraday_stop_on_day_three(self):
        t, _, _ = replay([(100, 100, 100, 100), (99, 100, 95, 99),
                          (99, 100, 95, 99), (99, 100, 96, 99)],
                         proof_stop='low', probe_close_days=2)
        self.assertAlmostEqual(t['executions'][0]['shares'], .0025/6)
        self.assertEqual((t['days'], t['why'], t['executions'][-1]['price']), (3, 'stop', 97.))

    def test_21ema_switch_cannot_exit_on_confirmation_day(self):
        ema = dict(e9=np.full((3, 1), 99.), e21=np.full((3, 1), 105.))
        t, _, _ = replay([(100, 100, 100, 100), (100, 103, 98, 102), (102, 104, 101, 103)],
                         proof_stop='low', proof_target_mult=2., proof_add_max=0,
                         proof_trail='e21', ema=ema, trail='e9', stop_ema_only=True, stop_ema_buffer=.01)
        self.assertEqual((t['days'], t['why']), (2, 'trail'))
        self.assertEqual(t['confirmed_day'], '2025-01-03')

    def test_h21_waits_for_pyramid_or_five_r_close_then_starts_next_day(self):
        ema = dict(e9=np.full((5, 1), 98.), e21=np.full((5, 1), 120.))
        bars = [(100, 100, 100, 100), (101, 103, 100, 102), (102, 110, 101, 109),
                (110, 116, 109, 115), (115, 117, 114, 116)]
        t, _, _ = replay(bars, ema=ema, trail='e9', stop_ema_only=True, stop_ema_buffer=.01,
                         proof_stop='low', proof_target_mult=2., proof_add_max=0,
                         proof_trail='e21', proof_trail_adds=1, proof_trail_r=5.)
        self.assertEqual((t['days'], t['why']), (4, 'trail'))

    def test_h21_can_switch_after_one_pyramid_before_five_r(self):
        ema = dict(e9=np.full((4, 1), 98.), e21=np.full((4, 1), 110.))
        bars = [(100, 100, 100, 100), (100, 103, 98, 102),
                (103, 105, 102, 104), (104, 106, 103, 105)]
        t, _, _ = replay(bars, ema=ema, trail='e9', stop_ema_only=True, stop_ema_buffer=.01,
                         proof_stop='low', proof_target_mult=2., proof_trail='e21',
                         proof_trail_adds=1, proof_trail_r=5.)
        self.assertEqual(t['proof_trail_day'], '2025-01-04')
        self.assertEqual((t['days'], t['why'], t['proof_adds']), (3, 'trail', 1))
        self.assertFalse(any(e['action'] == 'add' and e['time'] == t['exit'] for e in t['executions']))

    def test_dd_risk_uses_previous_close_even_if_today_rebounds(self):
        b = np.array([[100, 100, 100, 100], [100, 100, 40, 50], [50, 110, 50, 100]], float)
        px = {k: np.repeat(b[:, i:i+1], 2, axis=1) for i, k in enumerate(('open', 'high', 'low', 'close'))}
        px.update(dates=np.array(['2024-01-02', '2024-01-03', '2024-01-04']), codes=np.array(['X', 'Z']))
        book = [[((0,), 0, 1, 100., 1., 'probe', None)], [],
                [((0,), 1, 1, 100., 90., 'probe', None)]]
        rules = Y.Rules(risk=.396, max_position=10., max_gross=30., trail='', trims=(),
                        buy_cost=0, sell_cost=0, margin_rate=0, dd_risk=.2, dd_risk_inclusive=True)
        trade = Y.simulate(px, {}, rules, book, px['dates'][0], px['dates'][-1], audit=True)[2][1]
        self.assertAlmostEqual(trade['executions'][0]['shares'], .198/10)
        off = Y.simulate(px, {}, replace(rules, dd_risk=0.), book, px['dates'][0], px['dates'][-1], audit=True)[2][1]
        self.assertAlmostEqual(off['executions'][0]['shares'], 2*trade['executions'][0]['shares'])

    def test_all_e14_fields_default_off(self):
        r = Y.Rules()
        self.assertEqual((r.probe_close_days, r.proof_stop, r.proof_target_mult, r.proof_trail,
                          r.proof_trail_adds, r.proof_trail_r, r.dd_risk_inclusive), (0, '', 0., '', 0, 0., False))


if __name__ == '__main__':
    unittest.main()
