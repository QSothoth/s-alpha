"""Opt-in close slot release uses known prices and originating pick order."""
from dataclasses import replace
import unittest

import numpy as np

from studies.trader_replication import system as Y


RETRY = 'ie47_close_retry'


def replay(allow=False, confirmed=(), **overrides):
    prices = np.full((5, 4), 100.)
    for j in confirmed:
        prices[3:, j] = 101.
    p = dict(dates=np.array([f'2024-01-0{i+2}' for i in range(5)]), codes=np.array(['A', 'Z', 'B', 'C']))
    for field in ('open', 'high', 'low', 'close'):
        p[field] = prices.copy()
    p['low'] *= .999
    rules = Y.Rules(risk=.001, max_open=2, max_new_long=4, max_gross=2.8, trail='', trims=(),
                    proof_risk=True, probe_hard_mult=2., proof_add_max=0,
                    buy_cost=.001, sell_cost=.002, margin_rate=0,
                    make_room_kind={'base': RETRY} if allow else {},
                    make_room_confirmed=allow == 'all')
    rules = replace(rules, **overrides)
    # Z was picked earlier, despite entering at the same close as A and sorting later by code.
    book = [[], [], [((1000, 1, 0, 'A'), 0, 1, 100., 95., RETRY),
                     ((1001, 0, 1, 'Z'), 1, 1, 100., 95., RETRY)],
            [((0, 2, 'B'), 2, 1, 100., 95., 'base')], []]
    return p, rules, book


def run(p, rules, book):
    track = dict(entry_attempts=[])
    result = Y.simulate(p, {}, rules, book, p['dates'][0], p['dates'][-1], audit=True, track=track)
    return result, track


class MakeRoomTests(unittest.TestCase):
    def test_off_keeps_the_existing_positions(self):
        (curve, _, trades), track = run(*replay())
        self.assertEqual({t['code'] for t in trades}, {'A', 'Z'})
        self.assertNotIn('make_room', track)
        self.assertEqual(track['entry_attempts'][-1]['reason'], 'max_open')

    def test_oldest_pick_is_sold_at_this_close_before_the_new_entry(self):
        p, rules, book = replay(True)
        (curve, _, trades), track = run(p, rules, book)
        sold = next(t for t in trades if t['why'] == 'make_room')
        bought = next(t for t in trades if t['code'] == 'B')
        self.assertEqual((sold['code'], sold['exit'], sold['executions'][-1]['price']), ('Z', '2024-01-05', 100.))
        self.assertEqual(bought['entry'], sold['exit'])
        self.assertEqual(track['make_room'][0]['incoming'], 'B')
        self.assertEqual(track['entry_attempts'][-1]['reason'], 'filled')
        self.assertEqual(max(track['open']), 2)
        self.assertLess(curve[3], curve[2])  # both the sale and the new purchase pay their costs

    def test_s1_protects_confirmed_positions(self):
        (_, _, trades), track = run(*replay(True, confirmed=(1,)))
        self.assertEqual(next(t['code'] for t in trades if t['why'] == 'make_room'), 'A')
        self.assertFalse(track['make_room'][0]['confirmed'])
        (_, _, trades), track = run(*replay(True, confirmed=(0, 1)))
        self.assertNotIn('B', {t['code'] for t in trades})
        self.assertNotIn('make_room', track)

    def test_same_pick_night_uses_the_original_nightly_rank(self):
        p, rules, book = replay(True)
        book[2] = [((1000, 0, 1, 'A'), 0, 1, 100., 95., RETRY),
                   ((1000, 0, 0, 'Z'), 1, 1, 100., 95., RETRY)]
        (_, _, trades), track = run(p, rules, book)
        self.assertEqual(next(t['code'] for t in trades if t['why'] == 'make_room'), 'Z')

    def test_s2_falls_back_to_the_oldest_confirmed_position(self):
        (_, _, trades), track = run(*replay('all', confirmed=(0, 1)))
        sold = next(t for t in trades if t['why'] == 'make_room')
        self.assertEqual(sold['code'], 'Z')
        self.assertTrue(sold['confirmed'])
        self.assertEqual(sold['confirmed_day'], sold['exit'])
        from studies.martin_luk.e15_research import execution_audit
        with self.assertRaises(AssertionError):
            execution_audit(trades, replay()[1])
        self.assertTrue(execution_audit(trades, replay()[1], allow_add_exit=('make_room',))['ok'])

    def test_retries_and_same_name_signals_cannot_evict(self):
        for entry in (((1002, 2, 0, 'B'), 2, 1, 100., 95., RETRY),
                      ((0, 2, 'A'), 0, 1, 100., 95., 'base')):
            p, rules, book = replay('all')
            book[3] = [entry]
            (_, _, trades), track = run(p, rules, book)
            self.assertNotIn('make_room', track)

    def test_daily_limit_does_not_cause_an_extra_sale(self):
        p, rules, book = replay(True, max_new_long=1)
        book[1] = [book[2].pop()]
        book[3].append(((1, 2, 'C'), 3, 1, 100., 95., 'base'))
        (_, _, trades), track = run(p, rules, book)
        self.assertEqual(len(track['make_room']), 1)
        self.assertEqual(track['entry_attempts'][-1]['reason'], 'daily_long')

    def test_invalid_entry_kind_cap_and_missing_close_cannot_cause_a_sale(self):
        for case in ('stop', 'kind_cap', 'close', 'room'):
            p, rules, book = replay(True)
            if case == 'stop':
                book[3] = [((0, 2, 'B'), 2, 1, 100., 101., 'base')]
            elif case == 'kind_cap':
                rules = replace(rules, max_open_by_kind={'base': 0})
            elif case == 'close':
                p['close'][3, :2] = np.nan
            else:
                rules = replace(rules, max_position=.001)
            (_, _, trades), track = run(p, rules, book)
            self.assertNotIn('make_room', track, case)

    def test_no_sale_with_a_free_slot_or_when_future_prices_change(self):
        p, rules, book = replay(True, max_open=3)
        (_, _, trades), track = run(p, rules, book)
        self.assertNotIn('make_room', track)
        p, rules, book = replay(True)
        full, track = run(p, rules, book)
        p['close'][4] *= 3
        changed, new_track = run(p, rules, book)
        self.assertEqual(track['make_room'], new_track['make_room'])
        np.testing.assert_array_equal(full[0][:4], changed[0][:4])


if __name__ == '__main__':
    unittest.main()
