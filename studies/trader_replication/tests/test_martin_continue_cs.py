import unittest

import numpy as np

from studies.martin_luk.replicate import climax
from studies.trader_replication.martin_continue_cs import climax_by_chunk, prior_signal
from studies.trader_replication import system


class ClimaxTimingTests(unittest.TestCase):
    def test_chunking_preserves_existing_rule_and_previous_day_gate(self):
        rng = np.random.default_rng(19)
        c = rng.uniform(10, 100, (280, 70)).astype(np.float32)
        turnover = rng.uniform(1e6, 1e9, c.shape).astype(np.float32)
        c[15, 1] = np.nan
        turnover[20:30, 2] = np.nan
        actual = climax_by_chunk(c, turnover)
        expected = climax({'close': c, 'turnover': turnover}, .5)
        np.testing.assert_array_equal(actual, expected)
        shifted = prior_signal(actual)
        self.assertFalse(shifted[0].any())
        np.testing.assert_array_equal(shifted[1:], actual[:-1])
        altered_c, altered_t = c.copy(), turnover.copy()
        altered_c[200:], altered_t[200:] = 1e8, 1e12
        altered = climax_by_chunk(altered_c, altered_t)
        np.testing.assert_array_equal(actual[:200], altered[:200])
        np.testing.assert_array_equal(shifted[:201], prior_signal(altered)[:201])

    def test_previous_close_signal_exits_at_following_close(self):
        dates = np.array(['2025-01-02', '2025-01-03', '2025-01-06', '2025-01-07'])
        close = np.array([[10.], [11.], [12.], [13.]])
        px = {'dates': dates, 'codes': np.array(['US.A']), 'open': close.copy(),
              'high': close.copy(), 'low': close.copy(), 'close': close.copy()}
        entries = [[(0, 0, 1, 10., 9., 'list')], [], [], []]
        signal = np.array([[False], [True], [False], [False]])
        rules = system.Rules(trail='', trims=(), exit_signal='previous', buy_cost=0., sell_cost=0., margin_rate=0.)
        _, _, trades = system.simulate(px, {'previous': prior_signal(signal)}, rules, entries, dates[0], dates[-1])
        self.assertEqual((trades[0]['exit'], trades[0]['why']), ('2025-01-06', 'signal'))
        self.assertAlmostEqual(trades[0]['ret'], .2)


if __name__ == '__main__':
    unittest.main()
