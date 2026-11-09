import unittest

from studies.trader_replication.martin_continue_ic import append_one_peer, audit_plans


class SupplementalPeerTest(unittest.TestCase):
    def order(self, day, code, kind, priority):
        return {'day': day, 'code': code, 'kind': kind, 'priority': priority}

    def test_preserves_original_then_adds_only_first_peer(self):
        original = [self.order('d1', 'A', 'n1', [0., 0.]),
                    self.order('d1', 'B', 'list', [2., 1., -.2])]
        peers = [self.order('d1', 'C', 'list', [2., 1., 0.]),
                 self.order('d1', 'D', 'list', [2., 1., 1.])]
        result, keys, skipped = append_one_peer(original, peers)
        self.assertEqual(result[:2], original)
        self.assertEqual(result[2]['code'], 'C')
        self.assertEqual(result[2]['priority'], [2., 2., 0.])
        self.assertEqual(keys, {('d1', 'C')})
        self.assertEqual(skipped, {})
        self.assertEqual(peers[0]['priority'], [2., 1., 0.])

    def test_duplicate_first_peer_is_skipped_without_fallback(self):
        original = [self.order('2025-01-02', 'A', 'n1', [0., 0.])]
        peers = [self.order('2025-01-02', 'A', 'list', [2., 1., 0.]),
                 self.order('2025-01-02', 'B', 'list', [2., 1., 1.])]
        result, keys, skipped = append_one_peer(original, peers)
        self.assertEqual(result, original)
        self.assertEqual(keys, set())
        self.assertEqual(skipped, {'2025': 1})

    def test_plan_rejects_peer_processed_before_original(self):
        rows = [{'day': '2025-01-02', 'orders': [
            {'type': 'entry', 'kind': 'list', 'code': 'P', 'status': 'not_submitted', 'reason': 'risk_or_budget'},
            {'type': 'entry', 'kind': 'list', 'code': 'A', 'status': 'not_submitted', 'reason': 'position_limit'}]}]
        with self.assertRaises(AssertionError):
            audit_plans(rows, {('2025-01-02', 'P')}, 6)


if __name__ == '__main__':
    unittest.main()
