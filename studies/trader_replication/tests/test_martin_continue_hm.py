import unittest

from studies.trader_replication.martin_continue_hm import blend


def order(code, priority, kind='list'):
    return {'day': '2025-01-02', 'signal_day': '2024-12-31', 'code': code, 'kind': kind,
            'priority': priority, 'close': 10., 'stop': 9., 'risk_mult': .5}


class BlendTest(unittest.TestCase):
    def test_alternate_unique_trials_and_keep_core(self):
        core = order('US.CORE', [0., -3.], 'n1')
        h4 = [core, order('US.A', [2., 1., -5.]), order('US.B', [2., 1., -4.]),
              order('US.C', [2., 1., -3.]), order('US.D', [2., 1., -2.])]
        h3 = [core, order('US.B', [2., 1., -8.]), order('US.E', [2., 1., -7.]),
              order('US.F', [2., 1., -6.]), order('US.G', [2., 1., -5.])]
        result = blend(h3, h4)
        self.assertEqual(result[0], core)
        self.assertEqual([r['code'] for r in result[1:]],
                         ['US.A', 'US.B', 'US.E', 'US.C', 'US.F', 'US.D'])
        self.assertEqual([r['priority'][-1] for r in result[1:]], list(map(float, range(6))))
        self.assertEqual(h4[1]['priority'], [2., 1., -5.])

    def test_shared_trial_cannot_have_inconsistent_economic_terms(self):
        a = order('US.A', [2., 1., 0.])
        b = {**a, 'stop': 8.}
        with self.assertRaisesRegex(AssertionError, 'fields differ'):
            blend([a], [b])


if __name__ == '__main__':
    unittest.main()
