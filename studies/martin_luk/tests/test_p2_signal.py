"""P2 confirmation timing, frozen source merge, and signal-only boundary."""
import copy
import unittest

import numpy as np

from studies.martin_luk import p2_signal as S
from studies.martin_luk.p2_research import strategy_only, select_internal, family
from studies.trader_replication.config import Config


class P2SignalTests(unittest.TestCase):
    def test_confirmation_never_backfills_and_resets_pending_state(self):
        self.assertEqual(S.confirm([0, 0, 0, 2, 2, 1, 2, 2, 2]).tolist(),
                         [1, 1, 0, 0, 0, 0, 0, 0, 2])
        self.assertEqual(S.confirm([2, 2]).tolist(), [1, 1])

    def test_fixed_merge_order_and_duplicates(self):
        native, raw, theme = ['n', 'b'], ['a', 'b', 'c'], ['b', 'd', 'a']
        self.assertEqual(S.merge_night(native, raw, theme, 'native_zip'), ['n', 'b', 'd', 'a'])
        self.assertEqual(S.merge_night(native, raw, theme, 'raw_ie9'), ['a', 'b', 'c'])
        self.assertEqual(S.merge_night(native, raw, theme, 'raw_zip'), ['a', 'b', 'd', 'c'])
        self.assertEqual(S.merge_night(native, raw, theme, 'theme_first'), ['b', 'a', 'd', 'c'])
        self.assertEqual(S.merge_night(native, raw, theme, 'agreement'), ['b', 'a', 'd', 'c'])
        self.assertEqual((native, raw, theme), (['n', 'b'], ['a', 'b', 'c'], ['b', 'd', 'a']))

    def test_facade_uses_next_session_pool_and_preserves_source_prefix(self):
        A = dict(days=np.array(['2024-01-02', '2024-01-03', '2024-01-04']), codes=np.array(['a', 'b', 'c']),
                 eligible=np.array([[False]*3, [False, True, True], [True]*3]),
                 ie9={}, raw_ie9={'2024-01-02': ['a', 'b', 'c'], '2024-01-03': ['c', 'a']}, h1={})
        old = copy.deepcopy(A['raw_ie9'])
        st = S.P2Signals()
        cfg = Config(dict(signal=dict(merge='raw_ie9', native_max=5), switch=dict(mode='single')))
        with strategy_only():
            picks = st.signal(A, st.universe(A, cfg), cfg)
        self.assertEqual(picks, {0: ['b', 'c'], 1: ['c', 'a'], 2: []})
        self.assertEqual(A['raw_ie9'], old)
        short = dict(A, days=A['days'][:2], eligible=A['eligible'][:2])
        self.assertEqual(st.signal(short, st.universe(short, cfg), cfg)[0], picks[0])

    def test_strategy_rejects_label_read_attempts(self):
        with strategy_only(), self.assertRaises(PermissionError):
            (S.HOME/'notes/legs_frozen.json').read_text()
        with strategy_only(), self.assertRaises(PermissionError):
            (S.HOME/'notes/trades.csv').open()

    def test_source_cooldown_boundary_and_setup_classification(self):
        ordered = {str(t): ['a'] for t in range(12)}
        picked = select_internal(ordered)
        self.assertEqual([t for t, codes in picked.items() if codes], ['0', '11'])
        self.assertEqual(family('EP'), 'ep')
        self.assertEqual(family('first pullback breakout'), 'pullback')
        self.assertEqual(family('inside breakout'), 'breakout')
        self.assertEqual(family('unspecified'), 'unknown')


if __name__ == '__main__':
    unittest.main()
