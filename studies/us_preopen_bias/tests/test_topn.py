import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'code'))
import topn  # noqa: E402


def row(sym, score, ret, d='2024-03-01'):
    return {'symbol': sym, 'date': d, 'f': {'s': score, 'atr20': 0.02, 'ovol1': 5000, 'ovol20': 3000}, 'y': {'ret_oc': ret}}


class TopNTests(unittest.TestCase):
    def test_pick_top_and_bottom(self):
        pool = [row('US.%s' % c, i, 0.01) for i, c in enumerate('ABCDEFG')]
        items = topn.pick({'2024-03-01': pool}, lambda f: f['s'], n=3)
        self.assertEqual([r['symbol'] for d, s, r in items if s > 0], ['US.E', 'US.F', 'US.G'])
        self.assertEqual([r['symbol'] for d, s, r in items if s < 0], ['US.A', 'US.B', 'US.C'])

    def test_pool_too_small_is_skipped(self):
        self.assertEqual(topn.pick({'2024-03-01': [row('US.A', 1, 0.0)] * 5}, lambda f: f['s'], n=3), [])

    def test_evaluate_nets_cost_and_signs_shorts(self):
        items = [('2024-03-01', 1, row('US.A', 0, 0.02)), ('2024-03-01', -1, row('US.B', 0, 0.01))]
        m = topn.evaluate(items)
        self.assertAlmostEqual(m['exp'], ((200 - 10) + (-100 - 10)) / 2)
        self.assertEqual(m['win'], 0.5)
        self.assertAlmostEqual(m['payoff'], 190 / 110)

    def test_unusual_filter(self):
        rows = [row('US.A', 0, 0.0), row('US.B', 0, 0.0)]
        rows[1]['f']['ovol1'] = 3000
        gate = {'US.A': {'2024-03-01'}, 'US.B': {'2024-03-01'}}
        pools = topn.active_pools(rows, gate, unusual=1.5)
        self.assertEqual([r['symbol'] for r in pools['2024-03-01']], ['US.A'])

    def test_s27_option_volume_floor(self):
        rows = [row('US.A', 0, 0.0), row('US.B', 0, 0.0)]
        rows[1]['f']['ovol1'] = 1500
        gate = {'US.A': {'2024-03-01'}, 'US.B': {'2024-03-01'}}
        self.assertEqual(len(topn.active_pools(rows, gate)['2024-03-01']), 1)
        self.assertEqual(len(topn.active_pools(rows, gate, min_ovol=topn.S27_MIN_OPTION_VOLUME)['2024-03-01']), 2)

    def test_iv_half_keeps_the_higher_implied_moves(self):
        pool = [row('US.%s' % c, 0, 0.0) for c in 'ABCDE']
        for k, r in enumerate(pool):
            r['f']['implied_move'] = 0.01 * (k + 1)
        pool[0]['f']['implied_move'] = None
        half = topn.iv_half({'2024-03-01': pool})['2024-03-01']
        self.assertEqual([r['symbol'] for r in half], ['US.E', 'US.D'])

    def test_s27_gates_and_options_view(self):
        items = [('2024-03-01', 1, row('US.A', 0, 0.02)), ('2024-03-01', -1, row('US.B', 0, -0.01))]
        for _, _, r in items:
            r['f']['implied_move'] = 0.02
        self.assertAlmostEqual(topn.dir_move(items), (1.0 + 0.5) / 2)
        b = {'spread': 30.0, 'ci95': (25.0, 35.0), 'win': 0.55, 'half1': 21.0, 'half2': 40.0}
        m = {'exp': 5.0, 'ci95': (1.0, 9.0), 'pf': 1.2}
        bk, pk = topn.s27_gates(m, b)
        self.assertTrue(all(bk.values()) and all(pk.values()))
        b['half1'] = 19.0
        self.assertFalse(topn.s27_gates(m, b)[0]['halves>cost'])


if __name__ == '__main__':
    unittest.main()


class DailyTopTests(unittest.TestCase):
    def test_placeholder_bar_does_not_change_the_composite_inputs(self):
        import tempfile
        import daily_top
        import preopen
        from test_preopen import synthetic
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            days = synthetic(root)
            data = preopen.load([root])
            T = days[45]
            real = {r['symbol']: r['f'] for r in preopen.build(data, T, T)}
            for s, t in data['tables'].items():
                t['daily'] = daily_top.with_placeholder(t['daily'], T)
            fake = {r['symbol']: r['f'] for r in preopen.build(data, T, T)}
            for s in real:
                for key in ('pcr_z', 'iv', 'hv', 'clv1', 'ovol1', 'ovol20', 'atr20'):
                    self.assertEqual(real[s][key], fake[s][key], (s, key))
