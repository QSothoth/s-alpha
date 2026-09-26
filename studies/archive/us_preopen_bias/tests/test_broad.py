import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'code'))
import broad  # noqa: E402


def row(sym, ovol20, ovol1=10000, gap=0.02, gap_z=1.0, atr=0.02, imp=0.02, mag=1.0, ret=0.01, iv=50, hv=50):
    return {'symbol': sym, 'date': '2024-03-01',
            'f': {'ovol20': ovol20, 'ovol1': ovol1, 'gap': gap, 'gap_z': gap_z, 'atr20': atr, 'implied_move': imp, 'iv': iv, 'hv': hv},
            'y': {'mag': mag, 'ret_oc': ret, 'up': ret > 0, 'down': ret < 0}}


class PoolTests(unittest.TestCase):
    def test_top_by_trailing_option_volume_then_gates(self):
        rows = [row('US.S%03d' % i, ovol20=1000 + i) for i in range(80)]
        rows.append(row('US.THIN', ovol20=10 ** 9, ovol1=100))                  # top by volume but fails the T-1 gate
        elig = {r['symbol']: {'2024-03-01'} for r in rows}
        pool = broad.day_pools(rows, elig)['2024-03-01']
        self.assertEqual(len(pool), broad.TOP_UNIVERSE - 1)                     # THIN took a top-60 slot, then was gated out
        self.assertNotIn('US.S000', {r['symbol'] for r in pool})
        self.assertIn('US.S079', {r['symbol'] for r in pool})

    def test_select_and_lifts(self):
        big = row('US.BIG', 5000, gap=0.05, gap_z=3.0, mag=3.0, ret=-0.04)
        pool = [big] + [row('US.P%d' % i, 5000, gap=0.001, gap_z=0.05, mag=1.0, ret=0.01) for i in range(9)]
        items = broad.select({'2024-03-01': pool}, broad.b1_gap_size, k=1)
        self.assertEqual(items[0][1]['symbol'], 'US.BIG')
        self.assertEqual(items[0][2], 1)                                        # side follows the gap (context only)
        m = broad.evaluate(items)
        self.assertAlmostEqual(m['payoff_lift'], 3.0 / ((3.0 + 9 * 1.0) / 10))
        self.assertEqual(m['gap_hit'], 0.0)                                     # gapped up, closed down


if __name__ == '__main__':
    unittest.main()
