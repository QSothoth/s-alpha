import unittest

import numpy as np

from studies.trader_replication.martin_continue_bx import first_persistent, compact_families
from studies.trader_replication.martin_continue_bv import selected_families


class FirstPersistentTests(unittest.TestCase):
    def test_compact_families_match_existing_configured_formulas(self):
        rng = np.random.default_rng(24)
        shape = (50, 70)
        c = rng.uniform(5, 60, shape)
        c[11:14, 2] = np.nan
        days = np.busday_offset(np.datetime64('2024-01-01'), np.arange(shape[0]), roll='forward')
        A = {'days': days, 'close': c, 'open': c * .99, 'high': c * 1.05, 'low': c * .95,
             'e9': c * .98, 'e21': c * .96, 'adr': np.full(shape, 5.),
             'tight': rng.random(shape) > .5}
        w = rng.random(shape) > .3
        old, new = selected_families(A, w), compact_families(A, w)
        for family, items in old.items():
            for key, value in items.items():
                np.testing.assert_array_equal(value, new[family][key])

    def test_transient_earlier_difference_is_not_a_persistent_cause(self):
        stages = ('pool', 'mask', 'raw', 'cap')
        a = dict(pool=True, mask=True, raw=True, cap=True)
        b = dict(pool=False, mask=True, raw=False, cap=False)
        self.assertEqual(first_persistent(a, b, stages), 'raw')

    def test_missing_stage_is_not_silently_classified(self):
        self.assertEqual(first_persistent({'pool': True}, {'pool': False}, ('pool', 'cap')), 'unobserved')


if __name__ == '__main__':
    unittest.main()
