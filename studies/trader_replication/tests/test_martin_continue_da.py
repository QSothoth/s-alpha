import unittest

import numpy as np

from studies.trader_replication.martin_continue_da import BLOCK, DRAWS, METRICS, moving_blocks


class FixedStart:
    def integers(self, low, high, size):
        self.low, self.high, self.size = low, high, size
        return np.zeros(size, dtype=int)


def day(weight, numerator):
    return {'matched': {m: {'h3_weight': weight, 'numerator': numerator} for m in METRICS}}


class MovingBlockTests(unittest.TestCase):
    def test_consecutive_block_sampling_keeps_original_candidate_weights(self):
        days = [day(1, 1.) for _ in range(BLOCK)] + [day(10, -10.) for _ in range(BLOCK)]
        rng = FixedStart()
        result = moving_blocks(days, rng)
        self.assertEqual((rng.low, rng.high, rng.size), (0, BLOCK + 1, (DRAWS, 2)))
        for value in result.values():
            self.assertEqual(value['weight'], BLOCK * 11)
            self.assertAlmostEqual(value['difference'], -9 / 11)
            self.assertEqual(value['interval95'], [1., 1.])

    def test_missing_matched_weight_does_not_become_a_negative_return(self):
        days = [day(0, 0.) for _ in range(BLOCK)] + [day(1, .2) for _ in range(BLOCK)]
        with self.assertRaises(ValueError):
            moving_blocks(days, FixedStart())
        with self.assertRaises(ValueError):
            moving_blocks(days[:BLOCK - 1], np.random.default_rng(1))


if __name__ == '__main__':
    unittest.main()
