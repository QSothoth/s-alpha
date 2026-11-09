import unittest

import numpy as np

from studies.trader_replication.martin_continue_ib import peer_matrix, peer_priority


class CorrelatedPeerTest(unittest.TestCase):
    def test_peer_membership_uses_only_prior_forty_sessions(self):
        rng = np.random.default_rng(40)
        leader = rng.normal(size=45)
        residuals = np.column_stack([leader, -leader, leader]).astype(np.float32)
        active = np.array([True, True, True])
        held = np.array([False, False, True])
        pool, leaders, near = peer_matrix(residuals, active, held, 40)
        np.testing.assert_array_equal(pool, [0, 1])
        np.testing.assert_array_equal(leaders, [2])
        np.testing.assert_array_equal(near[:, 0], [True, False])
        changed = residuals.copy()
        changed[40:] = 1000
        _, _, later = peer_matrix(changed, active, held, 40)
        np.testing.assert_array_equal(near, later)

    def test_qualifying_peers_rank_by_prior_relative_strength(self):
        day = 40
        book = [[] for _ in range(42)]
        core = ((0., 0.), 2, 1, 10., 9., 'n1')
        book[day] = [core, ((2., 1., 0.), 0, 1, 10., 9., 'list'),
                     ((2., 1., 1.), 1, 1, 10., 9., 'list')]
        meta = {day: (np.array([0, 1]), np.array([2]), np.ones((2, 1), dtype=bool))}
        gain = np.zeros((42, 3))
        gain[39] = [.2, .1, .15]
        gain[40] = [0., 10., 0.]
        high = np.full((42, 3), 11.)
        low = np.full((42, 3), 10.)
        adr = np.full((42, 3), .05)
        turnover = np.full((42, 3), 1e8)
        ranked = peer_priority(book, meta, gain, high, low, adr, turnover, np.array(['A', 'B', 'C']))
        self.assertEqual(ranked[day][0], core)
        self.assertEqual([e[1] for e in sorted(ranked[day][1:], key=lambda e: e[0])], [0, 1])
        self.assertEqual(book[day][1][0], (2., 1., 0.))


if __name__ == '__main__':
    unittest.main()
