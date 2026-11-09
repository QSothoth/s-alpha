"""Observable-scope and yearly-accounting checks for the fixed IE40 run."""
import argparse
import ast
from datetime import date, timedelta
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import warnings

import numpy as np

from studies.trader_replication import martin_profile_ie40 as study
from studies.trader_replication.tests.test_standard_indicators import fitter_functions


class IE40Tests(unittest.TestCase):
    def test_scope_and_history_exclude_outsiders_and_future_for_all_cross_sections(self):
        rng = np.random.default_rng(40)
        close = np.exp(np.cumsum(rng.normal(.002, .04, (5, 330)), axis=1))*20
        panels = [close.copy(), close*1.02, close*.98]
        index = {str(k): k for k in range(5)}
        scope = ['0', '1', '3']
        wanted = ['1', '0']
        before = study.scope_values(panels, index, scope, wanted, 300, block_size=1)
        expected = study.standard.cross_section(*(p[[0, 1, 3], 48:301] for p in panels),
                                                 rows=[1, 0], version='v1.1')
        for p in panels:
            p[[2, 4]] *= np.linspace(.01, 1000, p.shape[1])
            p[:, 301:] *= 10000
        after = study.scope_values(panels, index, scope, wanted, 300, block_size=2)
        for name in before:
            np.testing.assert_allclose(before[name], expected[name], atol=1e-10, rtol=0, equal_nan=True)
            np.testing.assert_allclose(before[name], after[name], atol=1e-10, rtol=0, equal_nan=True)

    def test_cache_retains_raw_price_and_rejects_changed_observable_scope(self):
        n = 305
        days = [(date(2021, 1, 1)+timedelta(days=i)).isoformat() for i in range(n)]
        rng = np.random.default_rng(41)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'stocks').mkdir()
            work = root/'work'
            work.mkdir()
            q = np.exp(np.cumsum(rng.normal(0, .01, n)))*100
            np.save(root/'qqq.npy', q)
            raw = {}
            for code in ('a', 'b', 'c'):
                close = np.exp(np.cumsum(rng.normal(0, .03, n)))*20
                raw[code] = close*7
                np.savez(root/'stocks'/(code+'.npz'), o=close*.99, h=close*1.03,
                         l=close*.97, c=close, raw_c=raw[code], v=np.full(n, 10000.), t=close*10000)
            codes = ['b', 'a', 'a']
            rows = np.array([300, 300, 304])
            scopes = {days[300]: ['a', 'b'], days[304]: ['a', 'b', 'c']}
            with mock.patch.object(study, 'WORK', work), mock.patch.object(study, 'SOURCE', root), \
                    mock.patch.object(study, 'log'), warnings.catch_warnings():
                warnings.simplefilter('ignore', RuntimeWarning)
                names, x = study.pool_matrix(codes, rows, days, scopes)
                self.assertEqual(names, list(study.standard.V1_1_NAMES))
                np.testing.assert_allclose(x[names.index('price')], [raw[c][t] for c, t in zip(codes, rows)], rtol=1e-7)
                with mock.patch.object(study.standard, 'per_stock', side_effect=AssertionError('must reuse cache')):
                    cached_names, cached = study.pool_matrix(codes, rows, days, scopes)
                self.assertEqual(cached_names, names)
                np.testing.assert_array_equal(cached, x)
                scopes[days[300]] = ['a', 'b', 'c']
                with self.assertRaisesRegex(ValueError, 'scope or row order changed'):
                    study.pool_matrix(codes, rows, days, scopes)

    def test_yearly_primary_counts_include_holding_extension_but_not_secondary_targets(self):
        ctx = fitter_functions({'covered'}, dict(args=argparse.Namespace(renew=0)))
        ctx['picks'] = lambda ranks, K, H: {3: {'a'}, 10: {'b'}, 20: {'c'}}
        targets = [('a', 9, '2024H1', True), ('b', 10, '2025H2', True),
                   ('c', 20, '2026H1', False), ('d', 22, '2026H2', True)]
        self.assertEqual(study.yearly(ctx, None, targets),
                         {'2024': {'hit': 1, 'n': 1}, '2025': {'hit': 1, 'n': 1}, '2026': {'hit': 0, 'n': 1}})
        self.assertEqual(study.yearly(ctx, None, targets, K=2, H=2)['2024']['hit'], 0)

    def test_new_library_cli_keeps_half_weight_and_prior_libraries_keep_their_menu(self):
        source = Path(__file__).resolve().parents[1]/'martin_profile_ie29.py'
        tree = ast.parse(source.read_text())
        start = next(i for i, node in enumerate(tree.body) if isinstance(node, ast.Assign)
                     and any(isinstance(t, ast.Name) and t.id == 'WEIGHTS' for t in node.targets))
        stop = next(i for i, node in enumerate(tree.body) if isinstance(node, ast.Assign)
                    and any(isinstance(t, ast.Name) and t.id == 'SMOOTH' for t in node.targets))
        code = compile(ast.Module(body=tree.body[start:stop], type_ignores=[]), str(source), 'exec')
        for library in ('legacy', 'std_v1', 'std_v1_1'):
            flags = study.worker_flags('fit') if library == 'std_v1_1' else ['--library', library]
            namespace = dict(argparse=argparse)
            with mock.patch('sys.argv', ['fitter']+flags):
                exec(code, namespace)
            expected = (0, 1, 1.5, 2, 3) if library == 'std_v1' else (0, .5, 1, 1.5, 2, 3)
            self.assertEqual(namespace['WEIGHTS'], expected)


if __name__ == '__main__':
    unittest.main()
