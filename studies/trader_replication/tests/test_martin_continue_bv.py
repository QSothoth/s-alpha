import unittest
from types import SimpleNamespace

import numpy as np

from studies.trader_replication.martin_continue_bv import extra_names, selected_families, level_z15, daily_name_score, daily_pool_book
from studies.martin_luk.replicate import setup_families, level_shorts
from studies.trader_replication.martin_strong_scan import name_score, pool_book2


class ExpandedUniverseTests(unittest.TestCase):
    def test_compact_configured_setups_match_original_on_missing_values(self):
        rng = np.random.default_rng(72)
        shape = (90, 45)
        c = rng.uniform(4, 50, shape)
        c[12:15, 7] = np.nan
        h, low = c * rng.uniform(1, 1.15, shape), c * rng.uniform(.85, 1, shape)
        dates = np.busday_offset(np.datetime64('2024-01-01'), np.arange(shape[0]), roll='forward')
        a = {'days': dates, 'open': c * rng.uniform(.95, 1.05, shape), 'close': c,
             'high': h, 'low': low, 'e9': c * rng.uniform(.97, 1.03, shape),
             'e21': c * rng.uniform(.95, 1.05, shape), 'adr': rng.uniform(2, 15, shape),
             'tight': rng.random(shape) > .5, 'pr21': rng.random(shape),
             'to20': rng.uniform(1e6, 1e8, shape)}
        w = rng.random(shape) > .3
        old, new = setup_families(a, w), selected_families(a, w)
        for family, items in new.items():
            self.assertEqual(set(items), set(old[family]))
            for key, value in items.items():
                np.testing.assert_array_equal(value, old[family][key])

    def test_compact_z15_matches_original_across_chunks_and_missing_rows(self):
        rng = np.random.default_rng(61)
        shape = (100, 135)
        c = rng.uniform(4, 50, shape)
        c[20, :] = np.nan
        c[30:33, 2] = np.nan
        a = {'close': c, 'e9': c * rng.uniform(.95, 1.05, shape),
             'e21': c * rng.uniform(.9, 1.1, shape), 'rank_pool': rng.random(shape) > .2,
             'pr21': rng.random(shape), 'pr63': rng.random(shape), 'pr126': rng.random(shape)}
        pool = rng.random(shape) > .3
        old, new = level_shorts(a, pool)['Z15'], level_z15(a, pool)
        np.testing.assert_array_equal(new['armed'], old['armed'])
        np.testing.assert_array_equal(new['level'], old['level'])

    def test_daily_scores_match_original_including_ties_and_small_groups(self):
        rng = np.random.default_rng(11)
        shape = (20, 130)
        fields = {'a': rng.integers(0, 5, shape).astype(np.float32),
                  'b': rng.normal(size=shape).astype(np.float32),
                  'c': rng.normal(size=shape).astype(np.float32)}
        fields['a'][4, 2] = np.nan
        mask = rng.random(shape) > .2
        mask[6, 9:] = False
        groups = (('a', 'b'), ('c',))
        np.testing.assert_array_equal(daily_name_score(fields, mask, groups),
                                      name_score(SimpleNamespace(c=np.zeros(shape)), fields, mask, groups))

    def test_daily_candidates_match_original_with_missing_values(self):
        rng = np.random.default_rng(31)
        shape = (15, 40)
        c = rng.uniform(4, 50, shape).astype(np.float32)
        c[4, 3] = np.nan
        low = (c * rng.uniform(.90, .999, shape)).astype(np.float32)
        h = (c * rng.uniform(1.001, 1.1, shape)).astype(np.float32)
        D = SimpleNamespace(c=c, l=low, h=h, e9=c * 1.001,
                            adr=rng.uniform(.02, .15, shape).astype(np.float32))
        fields = {'lowe9': rng.uniform(-1, 1, shape).astype(np.float32),
                  'cpos': rng.uniform(0, 1, shape).astype(np.float32),
                  'ext21': rng.uniform(-1, 10, shape).astype(np.float32)}
        fields['ext21'][5, 8] = np.nan
        holding = rng.random(shape) > .3
        score = rng.uniform(-1, 1, shape).astype(np.float32)
        score[6, 9] = np.nan
        self.assertEqual(daily_pool_book(D, fields, holding, score),
                         pool_book2(D, fields, holding, score, True, 8.0, None, False))

    def test_new_name_closed_and_open_marks_are_separate(self):
        rows = [dict(entry='2025-02-01', code='US.A', why='stop', pnl=-.1, kind='list'),
                dict(entry='2025-03-01', code='US.B', why='trail', pnl=.3, kind='list'),
                dict(entry='2025-04-01', code='US.B', why='end', pnl=.2, kind='n1')]
        out = extra_names(rows, {'US.A'})['2025']
        self.assertEqual((out['entries'], out['closed'], out['open_at_end']), (2, 1, 1))
        self.assertAlmostEqual(out['closed_pnl'], .3)
        self.assertAlmostEqual(out['open_mark_pnl'], .2)
        self.assertEqual(out['kinds'], {'list': 1, 'n1': 1})


if __name__ == '__main__':
    unittest.main()
