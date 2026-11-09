import unittest

import numpy as np

from studies.trader_replication import systems
from studies.trader_replication.martin_continue_bb import data_with_system, reanchor


class Reanchor(unittest.TestCase):
    def test_data_factory_receives_the_selected_system_instance(self):
        selected = object()
        self.assertIs(data_with_system(selected, lambda: systems.get('martin_luk')), selected)
        self.assertIsNot(systems.get('martin_luk'), selected)

    def test_one_factor_per_name_preserves_turnover_and_raw(self):
        p = {'open': np.array([[2., 4.], [3., np.nan]]), 'high': np.array([[2., 4.], [3., np.nan]]),
             'low': np.array([[2., 4.], [3., np.nan]]), 'close': np.array([[2., 4.], [3., np.nan]]),
             'raw_close': np.array([[4., 4.], [6., np.nan]]), 'volume': np.array([[10., 20.], [12., np.nan]]),
             'turnover': np.array([[100., 200.], [300., np.nan]])}
        result = reanchor(p)
        self.assertEqual(result, {'missing_anchor': 0, 'changed_anchor': 1})
        np.testing.assert_allclose(p['close'][:, 0], [4., 6.])
        np.testing.assert_allclose(p['volume'][:, 0], [5., 6.])
        np.testing.assert_allclose(p['raw_close'][:, 0], [4., 6.])
        np.testing.assert_allclose(p['turnover'][:, 0], [100., 300.])
