"""H1 observable admission, account risk, and market-only grouping boundaries."""
from dataclasses import replace
import unittest

import numpy as np

from studies.martin_luk import h1_policy as H, h1_research as X
from studies.trader_replication import system as Y


class H1Tests(unittest.TestCase):
    def account(self, c, book, extra=None, ema=None, **changes):
        c = np.asarray(c, float)
        dates = np.array([f'2025-01-{i+1:02d}' for i in range(len(c))])
        px = dict(open=c.copy(), high=c+1, low=c-.1, close=c, dates=dates,
                  codes=np.array([f'S{i}' for i in range(c.shape[1])]))
        px.update(extra or {})
        rules = replace(Y.Rules(risk=.006, max_position=1., max_gross=2.8, trail='', trims=(),
                        buy_cost=0., sell_cost=0., margin_rate=0.), **changes)
        track = {'entry_attempts': []}
        result = Y.simulate(px, ema or {}, rules, book, dates[0], dates[-1], audit=True, track=track)
        return result, track

    def test_group_shares_one_budget_three_fills_and_held_quotes_are_safe(self):
        c = np.full((3, 4), 100.)
        row = [(j, j, 1, 100., 90., 'close') for j in range(4)]
        book = [row, row, []]
        groups = [{j: 0 for j in range(4)} for _ in c]
        (_, _, trades), track = self.account(c, book, {'entry_groups': groups}, entry_group_risk=True)
        first = [r for r in track['habit_entries'] if r['day'] == '2025-01-01']
        self.assertEqual(len(first), 3)
        self.assertAlmostEqual(sum(r['stop_risk_fraction'] for r in first), .006)
        self.assertEqual(sum(t['entry'] == '2025-01-01' for t in trades), 3)
        self.assertIn('group_limit', [r['reason'] for r in track['entry_attempts']])
        # With the feature off, the same optional metadata changes neither sizes nor count.
        (_, _, plain), _ = self.account(c, [row, [], []], {'entry_groups': groups})
        self.assertEqual(len(plain), 4)
        self.assertAlmostEqual(sum(t['executions'][0]['shares']*10 for t in plain), .024)

    def test_actual_event_fill_teaches_name_but_refused_quote_does_not(self):
        c = np.full((3, 1), 100.)
        row = [(0, 0, 1, 100., 90., 'close')]
        ema = dict(familiar=np.zeros(c.shape, bool), event=np.array([[True], [False], [False]]))
        low = c-.1
        low[1] = 85
        (_, _, trades), _ = self.account(c, [row, row, []], {'low': low}, ema,
            entry_familiar='familiar', entry_exception='event')
        self.assertEqual([t['entry'] for t in trades], ['2025-01-01', '2025-01-02'])
        blocked = [(0, 0, 1, 100., 90., 'close', None, None, 0.)]
        (_, _, trades), track = self.account(c, [blocked, row, []], {'low': low}, ema,
            entry_familiar='familiar', entry_exception='event')
        self.assertEqual(trades, [])
        self.assertEqual(track['entry_attempts'][-1]['reason'], 'unfamiliar')

    def test_episode_caps_real_attempts_and_only_causal_new_episode_rearms(self):
        c = np.full((7, 1), 100.)
        low = c-.1
        low[1:] = 85
        row = [(0, 0, 1, 100., 90., 'close')]
        episode = np.array([[1], [1], [1], [1], [1], [2], [2]])
        (_, _, trades), track = self.account(c, [row]*6+[[]], {'low': low}, {'episode': episode},
            entry_episode='episode', entry_episode_max=3)
        self.assertEqual([t['entry'] for t in trades], ['2025-01-01', '2025-01-02', '2025-01-03', '2025-01-06'])
        self.assertEqual(sum(r['reason'] == 'episode_limit' for r in track['entry_attempts']), 2)

    def test_equity_state_uses_prior_closes_and_drawdown_overrides_ma(self):
        c = np.full((26, 3), 100.)
        c[:22, 0] = 100+5*np.arange(22)
        book = [[] for _ in c]
        book[0] = [(0, 0, 1, 100., 99., 'close')]
        book[21] = [(0, 1, 1, 100., 90., 'close')]
        book[24] = [(0, 2, 1, 100., 90., 'close')]
        (_, _, _), track = self.account(c, book, risk=.005, risk_high=.01, risk_low=.0025,
            equity_state_days=20, max_position=.35)
        self.assertEqual([r['state_risk'] for r in track['habit_entries']], [.005, .01, .0025])
        self.assertTrue(all(r['notional_fraction'] <= .35+1e-12 for r in track['habit_entries']))
        changed = c.copy()
        changed[25:] *= 10
        _, second = self.account(changed, book, risk=.005, risk_high=.01, risk_low=.0025,
            equity_state_days=20, max_position=.35)
        self.assertEqual(track['habit_entries'], second['habit_entries'])

    def test_active_groups_need_two_watched_names_and_pool_relative_momentum(self):
        rng = np.random.default_rng(34)
        ret = rng.normal(0, .01, (80, 5))
        ret[:, 1] = ret[:, 0]
        close = np.vstack((np.ones(5), np.cumprod(1+ret, axis=0)))
        month = np.array([.9, .8, 0., 0., 0.])
        watched = np.array([True, True, False, False, False])
        args = (close, np.arange(5), 70, watched, month, np.array(list('ABCDE')))
        groups = H.active_groups(*args)
        self.assertEqual(groups[0]['members'], [0, 1])
        watched[1] = False
        self.assertEqual(H.active_groups(*args), [])

    def test_selection_requires_both_years_nonnegative_then_worse_year_behavior(self):
        def arm(scores, shares, positive=True):
            return dict(years={y: dict(score=s, narrow_profit_share=p, nonnegative=positive)
                for y, s, p in zip(('2024', '2025'), scores, shares)})
        result = X.select(dict(A=arm((5, 5), (.9, .9), False),
                               B=arm((3, 2), (.6, .6)), C=arm((2, 2), (.7, .5))))
        self.assertEqual(result['chosen'], 'B')
        self.assertEqual(X.select(dict(A=arm((5, 5), (.9, .9), False)))['chosen'], None)

    def test_defaults_disable_every_new_admission_and_risk_rule(self):
        r = Y.Rules()
        self.assertEqual((r.entry_familiar, r.entry_exception, r.entry_episode,
                          r.entry_episode_max, r.entry_group_risk, r.equity_state_days),
                         ('', '', '', 0, False, 0))


if __name__ == '__main__':
    unittest.main()
