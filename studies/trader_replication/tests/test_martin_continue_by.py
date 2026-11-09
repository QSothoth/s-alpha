import unittest

from studies.trader_replication.martin_continue_by import gate_book


class GateReconstructionTests(unittest.TestCase):
    def test_gate_changes_only_long_rows_and_preserves_daily_cap(self):
        a = ((2.,), 0, 1, 10., 9., 'n1')
        b = ((1.,), 1, 1, 20., 19., 'n1')
        short = ((3.,), 2, -1, 10., 11., 's_Z15')
        out = gate_book([[a, b], [a]], [True, False], 1, [[short], [short]], True)
        self.assertEqual([e[1] for e in out[0]], [1, 2])
        self.assertEqual([e[1] for e in out[1]], [2])


if __name__ == '__main__':
    unittest.main()
