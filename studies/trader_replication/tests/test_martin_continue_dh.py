import unittest

from studies.trader_replication.martin_continue_dh import index_trades, paired


def trade(entry, code, ret, why='stop'):
    return {'entry': entry, 'code': code, 'side': 1, 'kind': 'n1', 'why': why,
            'fill': 10., 'risk_pct': .05, 'days': 2, 'pnl': ret * 100,
            'ret_invested': ret, 'executions': [{'action': 'entry', 'price': 10., 'shares': 10.}]}


class PairingTest(unittest.TestCase):
    def test_next_session_maps_to_signal_and_groups_exhaust(self):
        days = ['2024-01-02', '2024-01-03', '2024-01-04']
        left = index_trades([trade(days[0], 'US.A', .1), trade(days[0], 'US.B', -.1)], days, False)
        right = index_trades([trade(days[1], 'US.A', -.05), trade(days[2], 'US.C', .2, 'end')], days, True)
        out = paired(left, right, 'all')
        self.assertEqual((out['left_entries'], out['right_entries'], out['common']), (2, 2, 1))
        self.assertEqual(out['left_only']['entries'], 1)
        self.assertEqual(out['right_only']['marked'], 1)
        self.assertEqual(out['outcomes_left_right'], {'win:nonwin': 1})

    def test_duplicate_signal_is_rejected(self):
        row = trade('2024-01-02', 'US.A', .1)
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            index_trades([row, row], ['2024-01-02'], False)


if __name__ == '__main__':
    unittest.main()
