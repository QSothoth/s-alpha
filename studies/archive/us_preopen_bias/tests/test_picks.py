import sys
import unittest
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'code'))
import picks  # noqa: E402


def _days(n):
    out, d = [], date(2024, 1, 2)
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d += timedelta(days=1)
    return out


def row(sym, gap_z, pcr_z=None, ret=0.01, atr=0.02, hi=0.02, lo=-0.01, ah_z=None, pm=None, gap=None):
    f = {'gap_z': gap_z, 'gap': gap if gap is not None else gap_z * atr, 'pcr_z': pcr_z, 'ah_z': ah_z, 'pm_ratio': pm,
         'atr20': atr, 'ovol1': 10000}
    return {'symbol': sym, 'date': '2024-03-01', 'f': f,
            'y': {'ret_oc': ret, 'up': ret > 0, 'down': ret < 0, 'hi_oc': hi, 'lo_oc': lo}}


class EligibilityTests(unittest.TestCase):
    def test_gate_and_no_lookahead(self):
        days = _days(30)
        dn = {d: (20.0, 21.0, 19.0, 2e7) for d in days}
        T = days[25]
        self.assertIn(T, picks.eligible_days(dn))
        dn[T] = (1.0, 1.0, 1.0, 0.0)
        self.assertIn(T, picks.eligible_days(dn))
        self.assertEqual(picks.eligible_days({d: (4.0, 4.5, 3.5, 2e7) for d in days}), set())
        self.assertEqual(picks.eligible_days({d: (10.0, 10.1, 9.9, 2e7) for d in days}), set())


class RuleTests(unittest.TestCase):
    def pool(self):
        return [row('US.A', 3.0, pcr_z=-2), row('US.B', 1.0, pcr_z=1.5), row('US.C', 0.2, pcr_z=0),
                row('US.D', -2.5, pcr_z=2.5), row('US.E', -0.7, pcr_z=-0.5)]

    def test_gap_go_and_fade(self):
        longs, shorts = picks.p1_gap_go(self.pool(), 2)
        self.assertEqual([r['symbol'] for r in longs], ['US.A', 'US.B'])
        self.assertEqual([r['symbol'] for r in shorts], ['US.D', 'US.E'])
        fl, fs = picks.p2_gap_fade(self.pool(), 2)
        self.assertEqual(([r['symbol'] for r in fl], [r['symbol'] for r in fs]), (['US.D', 'US.E'], ['US.A', 'US.B']))

    def test_inplay_pcr_sides_do_not_overlap(self):
        longs, shorts = picks.p4_inplay_pcr(self.pool(), 3)
        self.assertEqual(len(longs), 2)
        self.assertFalse({r['symbol'] for r in longs} & {r['symbol'] for r in shorts})
        self.assertEqual(longs[0]['symbol'], 'US.D')
        self.assertEqual(shorts[-1]['symbol'], 'US.A')


class ScoreTests(unittest.TestCase):
    def test_hit_signed_move_and_magnitude(self):
        up = row('US.A', 2.0, ret=0.02, atr=0.02, hi=0.03, lo=-0.005)
        flat = row('US.B', 0.1, ret=-0.002, atr=0.02, hi=0.001, lo=-0.004)
        items = picks.pick_items({'2024-03-01': [up, flat]}, lambda pool, n: ([up], []), 3)
        m = picks.score(items)
        self.assertEqual(m['hit'], 1.0)
        self.assertAlmostEqual(m['base'], 0.5)
        self.assertAlmostEqual(m['signed_atr'], 1.0)
        self.assertAlmostEqual(m['mfe_atr'], 1.5)
        self.assertAlmostEqual(m['mag_ratio'], 1.0 / ((1.0 + 0.1) / 2))


if __name__ == '__main__':
    unittest.main()


class DailyListTests(unittest.TestCase):
    def test_live_features_match_the_backtest(self):
        import tempfile
        import daily_list
        import preopen
        from test_preopen import synthetic
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            days = synthetic(root)
            data = preopen.load([root])
            T = days[45]
            built = {r['symbol']: r['f'] for r in preopen.build(data, T, T)}
            for s, t in data['tables'].items():
                daily = {d: v for d, v in t['daily'].items() if d < T}
                f = daily_list.features_at(daily, t['ext'], T, float(t['daily'][T]['open']))
                self.assertAlmostEqual(f['atr20'], built[s]['atr20'])
                self.assertAlmostEqual(f['gap_z'], built[s]['gap_z'])
                self.assertAlmostEqual(f['pm_ratio'], built[s]['pm_ratio'])

    def test_gate_matches_the_backtest_gate(self):
        import daily_list
        days = _days(30)
        dn = {d: (20.0 + i % 3, 21.0 + i % 3, 19.0, 2e7) for i, d in enumerate(days)}
        backtest = picks.eligible_days(dn)
        for T in days[21:]:
            self.assertEqual(daily_list.gate_before(dn, T), T in backtest, T)
