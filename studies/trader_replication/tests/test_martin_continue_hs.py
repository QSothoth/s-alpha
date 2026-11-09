import unittest
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from studies.trader_replication import martin_continue_cn as cn
from studies.trader_replication.martin_continue_hj import coil_fields_chunked
from studies.trader_replication.martin_continue_hs import coil_books
from studies.trader_replication.martin_list import ema


class CoilShortlistTest(unittest.TestCase):
    def test_reorders_all_candidates_before_limit_and_preserves_core(self):
        core = ((0., 0.), 9, 1, 10., 9., 'n1')
        trial = [((2., 1., float(j)), j, 1, 10., 9., 'list') for j in range(7)]
        book = [[], [core, *trial], []]
        mask = np.ones((3, 10), dtype=bool)
        with patch.object(cn, 'rank_coil', side_effect=lambda names, *args: names[::-1]):
            ranked, counts = coil_books(book, [1], mask, {}, np.zeros((1, 10)),
                                        np.zeros((1, 10)), np.array(list('ABCDEFGHIJ')))
        self.assertEqual(ranked[1][0], core)
        self.assertEqual([x[1] for x in sorted(ranked[1][1:], key=lambda x: x[0])[:6]],
                         [6, 5, 4, 3, 2, 1])
        self.assertEqual(counts, {'1': 7})
        self.assertEqual(book[1][1:], trial)

    def test_r4_uses_prior_day_factor_rows(self):
        names = np.arange(20)
        mask = np.ones(20, dtype=bool)
        codes = np.array([f'{i:02d}' for i in names])
        fields = {key: np.tile(names.astype(float), (4, 1))
                  for key in ('act20', 'stay250', 'fast250')}
        squeeze = np.zeros(20)
        weekly = np.zeros(20)
        before = cn.rank_coil(names, mask, fields, squeeze, weekly, 2, codes)
        for values in fields.values():
            values[2:] *= -100
        after = cn.rank_coil(names, mask, fields, squeeze, weekly, 2, codes)
        np.testing.assert_array_equal(before, after)

    def test_reused_h4_squeeze_matches_r4_prior_squeeze(self):
        rng = np.random.default_rng(11)
        close = rng.uniform(10, 50, (40, 16)).astype(np.float32)
        e9 = ema(close.astype(float), 9).astype(np.float32)
        adr = np.full_like(close, .05)
        data = SimpleNamespace(c=close, h=close * 1.02, l=close * .98, e9=e9, adr=adr)
        fields = coil_fields_chunked(data, width=8)
        targets = np.array([15, 30, 39])
        np.testing.assert_array_equal(-fields['nsq'][targets - 1],
                                      cn.prior_squeeze(close, e9, adr, targets))


if __name__ == '__main__':
    unittest.main()
