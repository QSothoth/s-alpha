import datetime
from types import SimpleNamespace
import unittest

import numpy as np

from studies.trader_replication.martin_continue_de import combine_book, cutoff_fidelity, entry_comparison, original_short_hits, reference_strength
from studies.trader_replication.martin_continue_bv import martin_rules


class EtfShortTests(unittest.TestCase):
    def test_etf_leader_matches_existing_full_universe_formula(self):
        rng = np.random.default_rng(73)
        close = 20 * np.cumprod(1 + rng.normal(.001, .02, size=(80, 27)), axis=0)
        rank_pool = rng.random(close.shape) > .05
        pool = rng.random(close.shape) > .1
        prev21 = martin_rules.luk.lag(close, 21)
        with np.errstate(invalid='ignore', divide='ignore'):
            pr21 = martin_rules.pct_rank(close / prev21 - 1, rank_pool)
        fake = {'close': close, 'rank_pool': rank_pool, 'pr21': pr21,
                'pr63': pr21, 'pr126': pr21}
        expected = martin_rules.S._past_any(martin_rules.strength_lists(fake, pool)['K9'], 40)[:, -2:]
        actual = reference_strength(close[:, :-2], rank_pool[:, :-2], pool[:, :-2],
                                    close[:, -2:], rank_pool[:, -2:], pool[:, -2:])
        np.testing.assert_array_equal(actual, expected)
        revised = close.copy()
        revised[65:] *= 3
        later = reference_strength(revised[:, :-2], rank_pool[:, :-2], pool[:, :-2],
                                   revised[:, -2:], rank_pool[:, -2:], pool[:, -2:])
        np.testing.assert_array_equal(actual[:65], later[:65])

    def test_fidelity_excludes_future_matured_windows_at_cutoff(self):
        days = [(datetime.date(2024, 1, 2) + datetime.timedelta(days=i)).isoformat() for i in range(30)]
        base = SimpleNamespace(trades=lambda: [], located=lambda A, t: [])
        data = SimpleNamespace(base=base, A={'days': np.array(days), 'codes': np.array(['US.X'])},
                               big=[(4, 0, 'X', '', days[4]), (5, 0, 'X', '', days[5])],
                               h=np.ones((30, 1)), di={day: i for i, day in enumerate(days)})
        trades = [{'code': 'US.X', 'side': 1, 'entry': days[4], 'exit': days[5]}]
        result = cutoff_fidelity(data, trades, 25, days[24])
        self.assertEqual(result['board_total'], 1)
        self.assertEqual(result['board'], 1)
        self.assertEqual(result['prepeak_ten_day']['2024']['windows'], 1)

    def test_entry_comparison_keeps_closed_and_marked_separate(self):
        def trade(code, pnl, why):
            return {'entry': '2026-01-03', 'code': code, 'side': -1, 'kind': 's_Z15', 'pnl': pnl, 'why': why}
        a = [trade('US.A', .1, 'stop'), trade('US.B', .2, 'end')]
        b = [trade('US.A', .15, 'stop'), trade('US.C', -.1, 'stop')]
        out = entry_comparison(a, b, '2026')
        self.assertEqual(out, entry_comparison(list(reversed(a)), list(reversed(b)), '2026'))
        self.assertEqual(out['u1_common']['closed_pnl'], .1)
        self.assertEqual(out['candidate_common']['closed_pnl'], .15)
        self.assertEqual(out['u1_only']['marked_pnl'], .2)
        self.assertEqual(out['candidate_only']['closed_pnl'], -.1)
        with self.assertRaises(AssertionError):
            entry_comparison(a + a, b, '2026')

    def test_original_short_hits_respect_the_cutoff(self):
        ledger = [{'id': 'before', 'ticker': 'A', 'entry_date': '2026-01-01',
                   'days': [{'day': '2026-01-02'}, {'day': '2026-01-05'}]},
                  {'id': 'after', 'ticker': 'B', 'entry_date': '2026-01-05',
                   'days': [{'day': '2026-01-05'}]}]
        trades = [{'entry': '2026-01-05', 'code': 'US.A', 'side': -1}]
        self.assertEqual(original_short_hits(ledger, trades, '2026-01-03'),
                         {'located_records': 1, 'hits': 0, 'hit_ids': []})
        self.assertEqual(original_short_hits(ledger, trades, '2026-01-05')['hit_ids'], ['before'])

    def test_etfs_compete_for_existing_short_cap_by_prior_turnover(self):
        old_long = ((0, -20.), 0, 1, 10., 9., 'n1')
        old_short = ((1, -100.), 1, -1, 10., 11., 's_Z15', None)
        etf = (-200., 0, -1, 20., 21., 's_Z15', None)
        entries, chosen = combine_book([[old_long, old_short]], [[etf]], 2, 1)
        self.assertEqual(chosen, {(0, 0)})
        self.assertEqual(entries[0][0], old_long)
        self.assertEqual(entries[0][1][0], (1, -200.))
        self.assertEqual(entries[0][1][1], 2)
        entries, chosen = combine_book([[old_long, old_short]], [[(-50.,) + etf[1:]]], 2, 1)
        self.assertEqual(chosen, set())
        self.assertEqual(entries[0], [old_long, old_short])


if __name__ == '__main__':
    unittest.main()
