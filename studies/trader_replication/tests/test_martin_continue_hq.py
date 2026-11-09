import unittest

from studies.trader_replication.martin_continue_hq import random_union


def order(code, priority, kind='list'):
    return {'day': '2025-01-02', 'signal_day': '2024-12-31', 'code': code, 'kind': kind,
            'priority': priority, 'close': 10., 'stop': 9., 'risk_mult': .5}


class RandomUnionTest(unittest.TestCase):
    def test_seeded_selection_is_distinct_and_preserves_core(self):
        core = order('US.CORE', [0., -3.], 'n1')
        h3 = [core] + [order('US.' + x, [2., 1., i]) for i, x in enumerate('ABCDEF')]
        h4 = [core] + [order('US.' + x, [2., 1., i]) for i, x in enumerate('CDEFGH')]
        selected = random_union(h3, h4, 1)
        self.assertEqual(selected, random_union(h3, h4, 1))
        self.assertEqual(selected[0], core)
        self.assertEqual(len(selected), 7)
        self.assertEqual(len({x['code'] for x in selected}), 7)
        self.assertTrue({x['code'] for x in selected[1:]} <= {'US.' + x for x in 'ABCDEFGH'})
        self.assertNotEqual(selected, random_union(h3, h4, 2))


if __name__ == '__main__':
    unittest.main()
