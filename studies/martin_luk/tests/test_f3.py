"""Observable F3 state, queue and daily risk admission behavior."""
from dataclasses import replace
import unittest

import numpy as np

from studies.martin_luk import f3_research as F


class F3Tests(unittest.TestCase):
    def step(self, active=False, armed=False, seen=0, day=1, **kwargs):
        values = dict(strong=False, eligible=True, survives=True, pool=True, touch=False, action=False)
        values.update(kwargs)
        return tuple(x.item() for x in F.leader_step(np.array([active]), np.array([armed]),
            np.array([seen]), day, **{k: np.array([v]) for k, v in values.items()}))

    def test_leader_persists_after_rank_and_liquidity_fade(self):
        self.assertEqual(self.step(active=True, seen=-500, pool=False)[:2], (True, False))
        self.assertEqual(self.step(seen=-500)[:2], (False, False))

    def test_memory_is_120_nights_and_weekly_break_clears_arm(self):
        self.assertTrue(self.step(day=119)[0])
        self.assertFalse(self.step(day=120)[0])
        self.assertEqual(self.step(active=True, armed=True, survives=False)[:2], (False, False))

    def test_first_action_consumes_pullback_and_new_decline_rearms(self):
        active, armed, seen, fire = self.step(touch=True, action=True)
        self.assertTrue(fire)
        self.assertFalse(armed)
        second = self.step(active=active, armed=armed, seen=seen, action=True)
        self.assertFalse(second[3])
        self.assertTrue(self.step(active=True, touch=True, action=True)[3])

    def test_pool_refusal_preserves_arm_but_no_offer(self):
        r = self.step(active=True, armed=True, action=True, pool=False)
        self.assertTrue(r[1])
        self.assertFalse(r[3])

    def test_category_then_stop_distance_then_peers(self):
        self.assertLess(F.queue_key(2, .05, 0, np.nan), F.queue_key(1, .01, 9, 100))
        self.assertLess(F.queue_key(2, .01, 0, np.nan), F.queue_key(2, .02, 9, 100))
        self.assertLess(F.queue_key(1, .02, 4, 60), F.queue_key(1, .02, 3, 100))

    def simulate(self, budget=0., invalid=False, rotation=False):
        c = np.full((3, 3), 100.)
        if rotation:
            c[1:, 0] = 99.
        days = np.array(['2025-01-02', '2025-01-03', '2025-01-06'])
        px = dict(close=c, open=c, high=c+1, low=c-.1, dates=days, codes=np.array(['A', 'B', 'C']))
        book = [[(0, 0, 1, 100., 90., 'close'), (1, 1, 1, 100., 90., 'close')],
                [(0, 2, 1, 100., 101. if invalid else 90., 'close')], []]
        rules = F.Y.Rules(risk=.01, max_position=1., max_gross=5., max_new_risk=budget,
            max_open=1 if rotation else 0, rotate_score='score' if rotation else '',
            trail='', trims=(), buy_cost=0., sell_cost=0., margin_rate=0.)
        track = {}
        result = F.Y.simulate(px, {'score': np.tile([0., 0., 1.], (3, 1))}, rules, book,
                              days[0], days[-1], audit=True, track=track)
        return result[2], track

    def test_budget_allocates_partial_then_resets_next_session(self):
        trades, track = self.simulate(.015)
        by_code = {t['code']: t for t in trades}
        self.assertAlmostEqual(by_code['B']['executions'][0]['shares'],
                               .5*by_code['A']['executions'][0]['shares'])
        self.assertAlmostEqual(by_code['C']['executions'][0]['shares'],
                               by_code['A']['executions'][0]['shares'])
        self.assertAlmostEqual(track['new_risk'][1]['used'], .015)
        self.assertAlmostEqual(track['new_risk'][2]['used'], .01)

    def test_exhausted_budget_rejects_later_name_and_default_is_off(self):
        self.assertEqual({t['code'] for t in self.simulate(.01)[0]}, {'A', 'C'})
        default, track = self.simulate()
        self.assertEqual({t['code'] for t in default}, {'A', 'B', 'C'})
        self.assertNotIn('new_risk', track)
        self.assertEqual(F.Y.Rules().max_new_risk, 0.)

    def test_invalid_incoming_order_never_sells_old_probe(self):
        trades, _ = self.simulate(.01, invalid=True, rotation=True)
        self.assertEqual([(t['code'], t['why']) for t in trades], [('A', 'end')])

    def test_budget_refusal_never_sells_old_probe(self):
        days = np.array(['2025-01-02', '2025-01-03'])
        c = np.array([[100., 100., 100., 100.], [99., 99., 100., 100.]])
        px = dict(close=c, open=c, high=c+1, low=c-.1, dates=days, codes=np.array(['A', 'D', 'C', 'B']))
        book = [[(j, j, 1, 100., 90., 'close', None, None, None, .5) for j in (0, 1)],
                [(j, j, 1, 100., 90., 'close') for j in (2, 3)]]
        rules = F.Y.Rules(risk=.02, max_position=1., max_gross=5., max_new_risk=.02,
            max_open=2, rotate_score='score', trail='', trims=(), buy_cost=0., sell_cost=0., margin_rate=0.)
        trades = F.Y.simulate(px, {'score': np.tile([0., 0., 2., 3.], (2, 1))}, rules, book,
                             days[0], days[-1], audit=True)[2]
        self.assertEqual({t['code'] for t in trades}, {'A', 'D', 'C'})
        self.assertEqual([(t['code'], t['why']) for t in trades if t['why'] == 'make_room'], [('A', 'make_room')])

    def test_selection_uses_worse_year_early_count_before_drawdown(self):
        def result(early, dd):
            return dict(H=10., cap_equity=.2, years={y: dict(target_count=0, cap_equity=.2,
                purity_gross=.3, maxdd=dd, coverage=dict(including_censored=dict(covered=early)),
                targets=dict(checks=dict(trades=True, win=True))) for y in ('2024', '2025')})
        outcome = F.select(dict(V1=result(4, .1), V2=result(5, .5)), dict(H=5., cap_equity=.1))
        self.assertEqual(outcome['chosen'], 'V2')
        rejected = F.select(dict(V1=result(5, .5)), dict(H=11., cap_equity=.1))
        self.assertIsNone(rejected['chosen'])

    def test_failed_add_does_not_confirm_a_probe_when_explicitly_enabled(self):
        days = np.array(['2025-01-02', '2025-01-03', '2025-01-06'])
        c = np.array([[100., 100.], [110., 100.], [99., 100.]])
        px = dict(close=c, open=c, high=c+1, low=c-.1, dates=days, codes=np.array(['OLD', 'NEW']))
        book = [[(0, 0, 1, 100., 90., 'close')], [], [(0, 1, 1, 100., 90., 'close')]]
        rules = F.Y.Rules(risk=.01, max_position=.1, max_gross=2.8, max_open=1, trail='', trims=(),
            add_levels=(1,), rotate_score='score', buy_cost=0., sell_cost=0., margin_rate=0.)
        def codes(r):
            return [t['code'] for t in F.Y.simulate(px, {'score': np.tile([0., 1.], (3, 1))}, r,
                    book, days[0], days[-1], audit=True)[2]]
        self.assertEqual(codes(rules), ['OLD'])
        self.assertEqual(codes(replace(rules, rotate_actual_adds=True)), ['OLD', 'NEW'])
        self.assertFalse(F.Y.Rules().rotate_actual_adds)


if __name__ == '__main__':
    unittest.main()
