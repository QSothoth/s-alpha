import unittest

import numpy as np

from studies.trader_replication import system
from studies.trader_replication.martin_continue_cl import without_adds


class NoAddTests(unittest.TestCase):
    def test_actual_adds_are_disabled_by_kind_without_global_fallback(self):
        close = np.array([[10., 10.], [11., 11.], [11., 11.]])
        px = {'open': close.copy(), 'high': close.copy(), 'low': close.copy(), 'close': close,
              'dates': np.array(['2025-01-02', '2025-01-03', '2025-01-06']),
              'codes': np.array(['LIST', 'CORE'])}
        entries = [[(0, 0, 1, 10., 9.5, 'list'), (1, 1, 1, 10., 9.5, 'core')], [], []]
        base = system.Rules(trail='', trims=(), risk=.01, max_position=1., max_gross=3.,
                            add_r=1., management_by_kind={'list': {'add_levels': (1., 3.)}},
                            buy_cost=0, sell_cost=0, margin_rate=0)
        def kinds(rules):
            _, _, trades = system.simulate(px, {}, rules, entries, px['dates'][0], px['dates'][-1], audit=True)
            return {t['kind'] for t in trades if any(e['action'] == 'add' for e in t['executions'])}
        self.assertEqual(kinds(base), {'list', 'core'})
        self.assertEqual(kinds(without_adds(base)), {'core'})
        self.assertEqual(kinds(without_adds(base, True)), set())

    def test_signal_adds_require_explicit_audit(self):
        with self.assertRaisesRegex(ValueError, 'signal adds'):
            without_adds(system.Rules(add_signal='buy_more'))


if __name__ == '__main__':
    unittest.main()
