"""Synthetic timing and account checks for the WF01 switches."""
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path
import unittest

import numpy as np

from studies.martin_luk import e15_research as E15, ie47_e1 as IE, wf01_joint as W
from studies.trader_replication import system as Y


def panel(rows, columns=1, adr=10.):
    bars = np.asarray(rows, float)
    a = {name: np.repeat(bars[:, k:k+1], columns, axis=1)
         for k, name in enumerate(('open', 'high', 'low', 'close'))}
    a.update(days=np.array([str(date(2025, 1, 2)+timedelta(days=i)) for i in range(len(rows))]),
             codes=np.array([f'SYN_{i:02d}' for i in range(columns)]),
             adr=np.full((len(rows), columns), adr))
    return a


def rules(**changes):
    return replace(Y.Rules(risk=.005, max_position=.5, max_gross=2.8, max_open=11,
                           max_new_long=0, trail='', trims=(), buy_cost=0., sell_cost=0.,
                           margin_rate=0.), **changes)


def simulate(a, book, policy, episodes=None, scale=None):
    px = {k: a[k] for k in ('open', 'high', 'low', 'close', 'codes')}
    px['dates'] = a['days']
    ema = {'always': np.ones_like(a['close'], bool), 'scale': np.ones(len(a['days'])) if scale is None else scale}
    if episodes is not None:
        ema['entry_episode'] = episodes
    track = {'entry_attempts': []}
    curve, days, trades = Y.simulate(px, ema, policy, book, a['days'][0], a['days'][-1], audit=True, track=track)
    return curve, days, trades, track


def entry(j, priority, fill=100., stop=50., multiplier=None):
    return (priority, j, 1, fill, stop, 'close', None, None, .30, multiplier)


class ObservationTests(unittest.TestCase):
    def test_disabled_matches_original_book_and_small_account(self):
        a = panel([(99, 100, 98, 99), (101, 103, 99, 102), (103, 105, 100, 104),
                   (104, 105, 100, 103)])
        picks = {a['days'][0]: ['SYN_00']}
        original = IE.entry_book(a, picks, **IE.E6['E6c'])[0]
        original, meta = E15.P.retry_book(a, original, {}, E15.SPECS['C062'])
        original = [[tuple(e[:7])+(None, .30)+tuple(e[9:]) for e in row] for row in original]
        actual, episodes, policy, actual_meta = W.build(a, picks, rules())
        self.assertEqual((actual, episodes, policy, actual_meta), (original, None, rules(), meta))
        first = simulate(a, original, rules())[:3]
        second = simulate(a, actual, policy)[:3]
        np.testing.assert_array_equal(first[0], second[0])
        np.testing.assert_array_equal(first[1], second[1])
        self.assertEqual(first[2], second[2])

    def test_repeated_breaks_expiry_stops_and_no_future_input(self):
        a = panel([(99, 100, 98, 99), (101, 103, 99, 102), (103, 105, 100, 104),
                   (105, 107, 102, 106), (107, 109, 104, 108), (109, 111, 106, 110),
                   (111, 113, 108, 112)], adr=4.)
        picks = {a['days'][0]: ['SYN_00']}
        book, episodes, _, _ = W.build(a, picks, rules(), c1=True)
        self.assertEqual([len(row) for row in book], [0, 1, 1, 1, 1, 1, 0])
        self.assertEqual(episodes[:, 0].tolist(), [-1, 0, 0, 0, 0, 0, -1])
        self.assertAlmostEqual(book[1][0][4], 102*.98)
        changed = {k: v.copy() for k, v in a.items()}
        changed['adr'][1, 0] = 8.
        changed['low'][2:, 0] = 1.
        changed['high'][2:, 0] = 500.
        later, _, _, _ = W.build(changed, picks, rules(), c1=True)
        self.assertEqual(book[:2], later[:2])
        changed['low'][2, 0] = 95.
        changed['high'][2, 0] = 105.
        later, _, _, _ = W.build(changed, picks, rules(), c1=True)
        self.assertAlmostEqual(later[2][0][4], 104*.96)

    def test_book_rejection_ends_observation(self):
        a = panel([(99, 100, 98, 99), (101, 103, 90, 102), (103, 105, 100, 104)], adr=1.6)
        a['adr'][1, 0] = 10.
        book, episodes, _, _ = W.build(a, {a['days'][0]: ['SYN_00']}, rules(), c1=True)
        self.assertFalse(any(book))
        self.assertEqual(episodes[:, 0].tolist(), [-1, 0, -1])

    def test_later_book_rejection_does_not_consume_a_valid_observation(self):
        a = panel([(99, 100, 98, 99), (101, 103, 99, 102),
                   (103, 105, 90, 104), (105, 107, 103, 106)])
        a['adr'][1, 0] = 1.6
        book, episodes, _, _ = W.build(a, {a['days'][0]: ['SYN_00']}, rules(), c1=True)
        self.assertEqual([len(row) for row in book], [0, 1, 0, 1])
        self.assertEqual(episodes[3, 0], 0)

    def test_original_priority_is_kept_across_nights(self):
        a = panel([(99, 100, 98, 99), (101, 103, 99, 102), (103, 105, 100, 104)], columns=3)
        picks = {a['days'][0]: ['SYN_02', 'SYN_01'], a['days'][1]: ['SYN_00']}
        book, _, _, _ = W.build(a, picks, rules(), c1=True)
        self.assertEqual([e[0] for e in book[2]], [(0, 0, 'SYN_02'), (0, 1, 'SYN_00'), (1, 0, 'SYN_01')])
        self.assertEqual(len({e[1] for e in book[2]}), len(book[2]))

    def test_episode_limit_after_fill_and_day_zero_stop(self):
        a = panel([(99, 100, 98, 99), (101, 103, 99, 102), (103, 105, 100, 104)])
        book, ep, policy, _ = W.build(a, {a['days'][0]: ['SYN_00']}, rules(), c1=True)
        _, _, trades, track = simulate(a, book, policy, ep)
        self.assertEqual([x['reason'] for x in track['entry_attempts']], ['filled', 'episode_limit'])
        self.assertEqual(len(trades), 1)
        original = book[1][0]
        book[1][0] = original[:5]+('intraday', original[4])+original[7:]
        _, _, trades, track = simulate(a, book, replace(policy, intraday_kinds=('intraday',)), ep)
        self.assertEqual(trades[0]['why'], 'stop_day0')
        self.assertEqual([x['reason'] for x in track['entry_attempts']], ['filled', 'episode_limit'])

    def test_max_open_block_then_fill_without_rotation(self):
        a = panel([(99, 100, 98, 99), (101, 103, 99, 102), (103, 105, 100, 104)], columns=2)
        a['open'][2, 0], a['low'][2, 0] = 90., 89.
        book, ep, policy, _ = W.build(a, {a['days'][0]: ['SYN_01']}, rules(max_open=1), c1=True)
        book[0].append(entry(0, (-1, 0, 'SYN_00'), 99., 95.))
        self.assertEqual(policy.rotate_below, 0.)
        _, _, trades, track = simulate(a, book, policy, ep)
        attempts = [x['reason'] for x in track['entry_attempts'] if x['code'] == 'SYN_01']
        self.assertEqual(attempts, ['max_open', 'filled'])
        self.assertEqual(next(t for t in trades if t['code'] == 'SYN_01')['entry'], a['days'][2])

    def test_daily_long_block_then_fill(self):
        a = panel([(99, 100, 98, 99), (101, 103, 99, 102), (103, 105, 100, 104)], columns=2)
        book, ep, policy, _ = W.build(a, {a['days'][0]: ['SYN_01']}, rules(max_new_long=1), c1=True)
        book[1].append(entry(0, (-1, 0, 'SYN_00'), 102., 95.))
        _, _, _, track = simulate(a, book, policy, ep)
        self.assertEqual([x['reason'] for x in track['entry_attempts'] if x['code'] == 'SYN_01'],
                         ['daily_long', 'filled'])

    def test_new_nomination_has_new_episode_and_can_fill_again(self):
        a = panel([(99, 100, 98, 99)]*14)
        a['open'][1, 0], a['high'][1, 0], a['close'][1, 0] = 101, 103, 102
        a['open'][2, 0], a['low'][2, 0] = 90, 89
        a['open'][12, 0], a['high'][12, 0], a['close'][12, 0] = 101, 103, 102
        picks = {a['days'][0]: ['SYN_00'], a['days'][11]: ['SYN_00']}
        book, ep, policy, _ = W.build(a, picks, rules(), c1=True)
        self.assertEqual((ep[1, 0], ep[6, 0], ep[12, 0]), (0, -1, 11))
        _, _, trades, track = simulate(a, book, policy, ep)
        self.assertEqual([t['entry'] for t in trades], [a['days'][1], a['days'][12]])
        self.assertEqual([x['reason'] for x in track['entry_attempts']], ['filled', 'filled'])


class AccountTests(unittest.TestCase):
    def rotation_case(self, *, eligible=True, tiny=False):
        a = panel([(100, 105, 90, 100)]*5, columns=12)
        a['close'][3:, :10] = 102.
        if eligible:
            a['close'][3:, 0], a['close'][3:, 1] = 95., 98.
        a['close'][3:, 10] = 90.  # A younger, weaker position is ineligible.
        book = [[] for _ in a['days']]
        book[0] = [entry(j, (j, 0, str(a['codes'][j]))) for j in range(10)]
        book[2] = [entry(10, (10, 2, str(a['codes'][10])))]
        book[3] = [entry(11, (0, 3, str(a['codes'][11])), multiplier=.00001 if tiny else None)]
        policy = rules(rotate_below=.02, rotate_min_days=3, buy_cost=.001, sell_cost=.002)
        return a, book, policy, simulate(a, book, policy)

    def test_rotation_sells_weakest_eligible_at_close_with_fee_then_opens(self):
        a, _, policy, (_, _, trades, track) = self.rotation_case()
        victim = next(t for t in trades if t['why'] == 'rotate')
        self.assertEqual((victim['code'], victim['exit']), ('SYN_00', a['days'][3]))
        self.assertEqual(victim['executions'][-1]['price'], 95.)
        shares = victim['executions'][0]['shares']
        self.assertAlmostEqual(victim['pnl'], shares*(95*(1-policy.sell_cost)-100*(1+policy.buy_cost)))
        self.assertIn('SYN_11', [t['code'] for t in trades])
        self.assertNotIn('SYN_10', [t['code'] for t in trades if t['why'] == 'rotate'])
        self.assertLessEqual(max(x['positions'] for x in track['entry_attempts']), 11)

    def test_no_rotation_if_only_young_or_two_percent_winners(self):
        _, _, _, (_, _, trades, track) = self.rotation_case(eligible=False)
        self.assertFalse(any(t['why'] == 'rotate' for t in trades))
        self.assertEqual(track['entry_attempts'][-1]['reason'], 'max_open')
        self.assertNotIn('SYN_11', [t['code'] for t in trades])

    def test_rotation_can_sell_before_incoming_size_is_rejected(self):
        _, _, _, (_, _, trades, track) = self.rotation_case(tiny=True)
        self.assertIn(('SYN_00', 'rotate'), [(t['code'], t['why']) for t in trades])
        self.assertNotIn('SYN_11', [t['code'] for t in trades])
        self.assertEqual(track['entry_attempts'][-1]['reason'], 'risk_or_gross')

    def test_c3_probe_size_doubles_and_confirmed_risk_stays_within_budget(self):
        a = panel([(100, 101, 99, 100), (100, 102, 98, 101)])
        book = [[entry(0, (0, 0, 'SYN_00'), 100., 95.)], []]
        base = rules(risk=.0025, risk_scale='scale', probe_hard_mult=2., proof_risk=True,
                     proof_stop='fill', proof_target_mult=4., add_signal='always', add_signal_profit=True,
                     add_signal_max=1, add_signal_frac=1.)
        amounts = []
        for policy in (base, replace(base, risk=.005)):
            _, _, trades, _ = simulate(a, book, policy, scale=np.array([.5, .5]))
            t = trades[0]
            amounts.append(t['executions'][0]['shares']*100)
            add = next(x for x in t['executions'] if x['action'] == 'add')
            self.assertLessEqual(add['risk_at_stop'], t['risk_budget']+1e-12)
        self.assertAlmostEqual(amounts[0], min(.0025*.5/(2*.05), .30, 2.8))
        self.assertAlmostEqual(amounts[1], 2*amounts[0])

    def test_module_has_no_evaluation_inputs(self):
        source = Path(W.__file__).read_text()
        for forbidden in ('legs_frozen', 'trades.csv', 'labels(', 'notes/'):
            self.assertNotIn(forbidden, source)


if __name__ == '__main__':
    unittest.main()
