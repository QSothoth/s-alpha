import unittest

from studies.trader_replication.martin_continue_hf import classify


class FunnelTest(unittest.TestCase):
    def test_same_day_and_channel_must_match(self):
        candidates = [{'day': '2025-01-02', 'code': 'US.A', 'kind': 'n1'},
                      {'day': '2025-01-03', 'code': 'US.A', 'kind': 'list'}]
        plans = {('2025-01-02', 'US.A', 'n1'): {'status': 'submitted', 'execution': 'limit_expired'},
                 ('2025-01-03', 'US.A', 'list'): {'status': 'not_submitted', 'reason': 'position_limit'}}
        stage, events = classify(candidates, plans, set())
        self.assertEqual(stage, 'submitted')
        self.assertEqual([e['stage'] for e in events], ['submitted', 'candidate'])
        with self.assertRaisesRegex(AssertionError, 'lacks matching submitted plan'):
            classify(candidates, plans, {('2025-01-03', 'US.A', 'list')})

    def test_actual_fill_requires_candidate_and_submitted_plan(self):
        candidate = [{'day': '2025-01-02', 'code': 'US.A', 'kind': 'n1'}]
        key = ('2025-01-02', 'US.A', 'n1')
        plans = {key: {'status': 'submitted', 'execution': 'gap_moc'}}
        self.assertEqual(classify(candidate, plans, {key})[0], 'filled')
        with self.assertRaisesRegex(AssertionError, 'lacks matching trade'):
            classify(candidate, plans, set())
        self.assertEqual(classify([], plans, set())[0], 'no_candidate')


if __name__ == '__main__':
    unittest.main()
