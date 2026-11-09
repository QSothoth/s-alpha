"""E13 execution timing and risk invariants, specified before implementation."""
import unittest

import numpy as np

from studies.trader_replication import system as Y


def replay(bars, **opts):
    b = np.asarray(bars, float)
    px = {k: b[:, i:i+1] for i, k in enumerate(('open', 'high', 'low', 'close'))}
    px.update(dates=np.array([f'2025-01-{i+2:02d}' for i in range(len(b))]), codes=np.array(['X']))
    ema = opts.pop('ema', {})
    rules = Y.Rules(**dict(dict(risk=.0025, max_position=.30, max_gross=2.8, trail='', trims=(),
                               buy_cost=0, sell_cost=0, margin_rate=0, probe_hard_mult=2., proof_risk=True,
                               proof_add_signal='again', proof_add_max=2), **opts))
    ema.setdefault('again', np.ones((len(b), 1), bool))
    entries = [[((0, 0, 'X'), 0, 1, 100., 97., 'probe', None)]] + [[] for _ in bars[1:]]
    track = {}
    curve, dates, trades = Y.simulate(px, ema, rules, entries, px['dates'][0], px['dates'][-1], audit=True, track=track)
    return trades[0], track, curve


class ProofRiskTests(unittest.TestCase):
    def test_entry_day_does_not_stop_trim_or_add(self):
        t, _, _ = replay([(100, 140, 10, 100), (99, 100, 98, 99)])
        self.assertEqual([e['action'] for e in t['executions']], ['entry', 'end'])
        self.assertAlmostEqual(t['executions'][0]['shares'], .0025/6)
        self.assertFalse(t['confirmed'])

    def test_close_stop_has_no_day_limit_and_uses_initial_l0(self):
        bars = [(100, 100, 100, 100)] + [(99, 100, 95, 99)]*6 + [(98, 99, 95, 96)]
        t, _, _ = replay(bars)
        self.assertEqual((t['why'], t['days']), ('close_stop', 7))
        self.assertEqual(t['executions'][-1]['price'], 96.)

    def test_hard_stop_precedes_close_stop_and_confirmation(self):
        for bar, why, price in (((99, 103, 93, 96), 'stop', 94.),
                                ((93, 103, 92, 102), 'gap_stop', 93.),
                                ((99, 103, 94, 102), 'stop', 94.)):
            t, _, _ = replay([(100, 100, 100, 100), bar])
            self.assertEqual((t['why'], t['executions'][-1]['price']), (why, price))
            self.assertFalse(t['confirmed'])
            self.assertFalse(any(e['action'] == 'add' for e in t['executions']))

    def test_confirmation_reaches_k2_full_shares_then_two_later_adds(self):
        bars = [(100, 100, 100, 100), (100, 102, 98, 101), (102, 103, 101, 102),
                (103, 104, 102, 103), (104, 105, 103, 104)]
        t, _, _ = replay(bars)
        ex = t['executions']
        adds = [e for e in ex if e['action'] == 'add']
        self.assertEqual([e['time'] for e in adds], ['2025-01-03', '2025-01-04', '2025-01-05'])
        self.assertAlmostEqual(ex[0]['shares'] + adds[0]['shares'], 2*.0025/3)
        self.assertAlmostEqual(adds[1]['shares'], .0025/3)
        self.assertGreater(adds[2]['shares'], 0.)
        self.assertLess(adds[2]['shares'], .0025/3)  # The second pyramid meets the 30% position cap.
        self.assertEqual(t['proof_adds'], 2)
        self.assertTrue(t['confirmed'])
        self.assertTrue(all(a['stop'] <= b['stop'] for a, b in zip(adds, adds[1:])))
        cash, shares = -100*ex[0]['shares'], ex[0]['shares']
        for e in adds:
            cash -= e['price']*e['shares']
            shares += e['shares']
            self.assertGreaterEqual(cash + shares*e['stop'], -.005-1e-12)

    def test_stop_risk_calculation_includes_realized_cash_and_both_fees(self):
        stop = Y.risk_limited_stop(-.101, .001, .005, .002)
        self.assertAlmostEqual(-.101 + .001*stop*(1-.002), -.005)
        self.assertLess(Y.risk_limited_stop(-.091, .001, .005, .002), stop)
        t, _, _ = replay([(100, 100, 100, 100), (100, 103, 98, 102), (103, 104, 102, 103)],
                         buy_cost=.001, sell_cost=.002)
        cash, shares = 0., 0.
        for e in t['executions']:
            if e['action'] in ('entry', 'add'):
                cash -= e['price']*e['shares']*1.001
                shares += e['shares']
            if e['action'] == 'add':
                self.assertGreaterEqual(cash+shares*e['stop']*.998, -t['risk_budget']-1e-12)

    def test_close_exit_beats_confirmation_add(self):
        ema = {'exit': np.array([[False], [True]])}
        t, _, _ = replay([(100, 100, 100, 100), (100, 103, 98, 102)], ema=ema, exit_signal='exit')
        self.assertEqual([e['action'] for e in t['executions']], ['entry', 'signal'])
        self.assertFalse(t['confirmed'])

    def test_unaffordable_risk_stop_leaves_probe_unconfirmed(self):
        t, track, _ = replay([(100, 100, 100, 100), (100, 102, 98, 101)], buy_cost=.1, sell_cost=.1)
        self.assertFalse(t['confirmed'])
        self.assertEqual([e['action'] for e in t['executions']], ['entry', 'end'])
        self.assertTrue(any(e['status'] == 'risk_rejected' for e in track['proof_orders']))

    def test_confirmed_stop_is_intraday_and_never_reverts_to_s(self):
        t, _, _ = replay([(100, 100, 100, 100), (100, 103, 98, 102), (102, 103, 95, 102)])
        stop = next(e['stop'] for e in t['executions'] if e['action'] == 'add')
        self.assertEqual(t['why'], 'stop')
        self.assertAlmostEqual(t['executions'][-1]['price'], stop)

    def test_f2_has_k2_initial_shares_and_regular_stop(self):
        t, _, _ = replay([(100, 100, 100, 100), (99, 103, 96, 102)], probe_hard_mult=0.)
        self.assertAlmostEqual(t['executions'][0]['shares'], .0025/3)
        self.assertEqual((t['why'], t['executions'][-1]['price']), ('stop', 97.))

    def test_f4_adds_only_its_own_small_initial_shares_and_raises_to_low(self):
        t, _, _ = replay([(100, 100, 100, 100), (100, 103, 98, 102), (103, 105, 102, 104)],
                         proof_risk=False, proof_add_signal='', add_signal='again', add_signal_profit=True,
                         add_signal_max=1, add_signal_frac=1., add_signal_stop='low')
        adds = [e for e in t['executions'] if e['action'] == 'add']
        self.assertEqual(len(adds), 1)
        self.assertAlmostEqual(adds[0]['shares'], t['executions'][0]['shares'])
        self.assertEqual(adds[0]['stop'], 98.)
        self.assertTrue(t['confirmed'])

    def test_s_does_not_use_the_armed_ema_as_its_close_or_intraday_stop(self):
        ema = {'e9': np.full((3, 1), 98.)}
        t, _, _ = replay([(100, 100, 100, 100), (99, 100, 95, 99), (98, 99, 95, 97.01)],
                         ema=ema, trail='e9', stop_ema_only=True, stop_ema_buffer=.01)
        self.assertEqual(t['why'], 'end')
        self.assertFalse(t['confirmed'])

    def test_f5_sizes_at_one_and_a_half_w(self):
        t, _, _ = replay([(100, 100, 100, 100), (99, 100, 95, 98)], probe_hard_mult=1.5)
        self.assertAlmostEqual(t['executions'][0]['shares'], .0025/4.5)
        self.assertEqual((t['why'], t['executions'][-1]['price']), ('stop', 95.5))

    def test_new_fields_default_off(self):
        r = Y.Rules()
        self.assertEqual((r.probe_hard_mult, r.proof_risk, r.proof_add_signal), (0., False, ''))


if __name__ == '__main__':
    unittest.main()
