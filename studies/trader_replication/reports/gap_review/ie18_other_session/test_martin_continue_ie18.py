import ast
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np

from studies.trader_replication import martin_continue_ie18 as m
from studies.trader_replication.tests import test_martin_continue_ie17 as prior_tests


class IE18Tests(unittest.TestCase):
    def synthetic(self, cut=320, change=None):
        d = prior_tests.IE17Tests().synthetic(cut=cut, change=change)
        t, j = np.arange(cut)[:, None], np.arange(len(d.codes))[None, :]
        volume = 10000 + 1000 * np.cos(t + j)
        history = np.sin(t / 25 + j)
        if change is not None:
            volume[change:] *= 100
            history[change:] *= 100
        d.ie18 = m.quiet_fields(d.px['close'], volume, d.meta['benchmark'][0]['close'])
        d.ie18['history'] = history
        return d

    def test_premier_union_preserves_other_pool_and_has_no_adr_floor(self):
        money = np.array([1e8 - 1, 1e8, 1e9, 3e6, 1e6])
        adr = np.array([2., 2., np.nan, 6., 9.])
        self.assertEqual(m.pool_union(money, adr, m.BASE).tolist(), [False, False, False, True, False])
        self.assertEqual(m.pool_union(money, adr, dict(m.BASE, premier=1e8)).tolist(),
                         [False, True, True, True, False])
        self.assertEqual(m.pool_union(money, adr, dict(m.BASE, premier=1e9)).tolist(),
                         [False, False, True, True, False])

    def test_premier_must_still_pass_the_downstream_filters(self):
        d = self.synthetic()
        cfg = dict(m.BASE, premier=1e8)
        s = 280
        d.f['adr'][s] = 2
        d.f['money'][s] = 2e8
        b = m.selection.selection_arrays(d, cfg)
        b['trend'][s] = [True, False, True, True, False, True]
        b['setup'][s] = [True, True, False, True, True, True]
        with patch.object(m.selection, 'selection_arrays', return_value=b):
            result = m.selection_arrays(d, cfg)
        self.assertTrue(result['pool'][s].all())
        self.assertEqual(result['signals']['long'][s].tolist(), [True, False, False, True, False, True])

    def test_type_intervals_use_signal_features_with_ep_precedence(self):
        d = SimpleNamespace(f=dict(ep=np.array([[0., 0., 1.]]), pullback=np.array([[1., 0., 1.]])),
                            strength=dict(extension=np.array([[2., 0., 2.5]])))
        cfg = dict(m.BASE, interval=m.TYPE_INTERVALS)
        np.testing.assert_array_equal(m.launch_values(0, d, cfg), [-.5, -.5, 0.])
        np.testing.assert_array_equal(m.launch_values(0, d, dict(cfg, launch_shape='center')),
                                      [-1.25, -1.25, -1.])

    def test_quiet_volume_denominator_excludes_the_signal_day(self):
        volume = np.array([[1.], [2.], [3.], [12.], [18.]])
        close = np.array([[10.], [11.], [10.], [12.], [12.]])
        benchmark = np.array([10., 10., 10., 10., 11.])
        fields = m.quiet_fields(close, volume, benchmark)
        self.assertEqual(fields['quiet_volume'][3, 0], -6.)
        self.assertEqual(fields['quiet_volume'][4, 0], -18 / (17 / 3))
        self.assertAlmostEqual(fields['quiet_return'][3, 0], -.2)
        self.assertAlmostEqual(fields['quiet_return'][4, 0], .1)
        self.assertTrue(np.isnan(fields['quiet_volume'][:3]).all())

    def test_new_components_are_equal_weight_and_missing_is_neutral(self):
        d = self.synthetic()
        cfg = dict(m.BASE, components=['launch', 'money', 'quiet', 'history'])
        s = 280
        mask = np.array([True, True, False, True, False, True])
        full = m.strength_scores(s, d, cfg, mask)
        singles = [m.strength_scores(s, d, dict(cfg, components=[n]), mask) for n in cfg['components']]
        np.testing.assert_allclose(full, np.mean(singles, axis=0), atol=1e-14)
        quiet = (m.previous.percentile(d.ie18['quiet_return'][s, mask]) +
                 m.previous.percentile(d.ie18['quiet_volume'][s, mask])) / 2
        np.testing.assert_array_equal(singles[2], quiet)
        d.ie18['history'][s] = np.nan
        np.testing.assert_array_equal(m.strength_scores(s, d, dict(cfg, components=['history']), mask), [.5] * 4)
        before = m.strength_scores(s, d, cfg, mask)
        for a in (*d.ie18.values(), *d.strength.values()):
            a[s, 2] = 1e9
        d.f['money'][s, 2] = 1e15
        np.testing.assert_array_equal(before, m.strength_scores(s, d, cfg, mask))

    def test_new_features_scores_and_orders_ignore_future_rows(self):
        configs = [m.BASE, dict(m.BASE, premier=1e8, interval=m.TYPE_INTERVALS, components=['launch', 'money', 'quiet']),
                   dict(m.BASE, premier=5e8, launch_shape='lower', components=['launch', 'money', 'history'])]
        for cfg in configs:
            full_data = self.synthetic()
            full = m.build(full_data, cfg)
            for other in (self.synthetic(cut=280), self.synthetic(change=280)):
                result = m.build(other, cfg)
                for name in ('quiet_return', 'quiet_volume', 'history'):
                    np.testing.assert_array_equal(full_data.ie18[name][:280], other.ie18[name][:280])
                for name in ('pool', 'market'):
                    np.testing.assert_array_equal(full[name][:280], result[name][:280])
                np.testing.assert_array_equal(full['signals']['long'][:280], result['signals']['long'][:280])
                self.assertEqual(full['book'][:560], result['book'][:560])

    def test_execution_day_trigger_subset_cannot_rerank_the_other_offers(self):
        d = self.synthetic()
        cfg = dict(m.BASE, premier=1e8, components=['launch', 'money', 'quiet'])
        fixed = m.selection_arrays(d, cfg)
        s = 280
        fixed['signals']['long'][s] = True
        fixed['market'][s] = True
        d.px['high'][s + 1] = d.px['high'][s] * 2
        with patch.object(m, 'selection_arrays', return_value=fixed):
            before = m.build(d, cfg)['book'][2 * (s + 1)]
            d.px['high'][s + 1, 0] = d.px['high'][s, 0] - 1
            d.latest = None
            after = m.build(d, cfg)['book'][2 * (s + 1)]
        self.assertEqual(len(before), len(after) + 1)
        self.assertEqual([(e[0], e[1]) for e in before if e[1] != 0], [(e[0], e[1]) for e in after])

    def test_round_budget_one_field_and_training_funnel_direction(self):
        branch, seen = dict(m.BASE), {m.old.key(m.BASE)}
        for number in range(1, 5):
            layer, choices = m.proposals(branch, {m.BLOCKS[0]: 23}, seen, number)
            self.assertTrue(choices)
            self.assertLessEqual(len(choices), 5)
            for cfg in choices:
                self.assertEqual([k for k in cfg if cfg[k] != branch[k]], [layer])
                self.assertEqual(cfg['trigger'], m.BASE['trigger'])
                self.assertNotIn(m.old.key(cfg), seen)
                seen.add(m.old.key(cfg))
            branch = choices[0]
        for block, layer in zip(m.BLOCKS, ('launch_shape', 'pool', 'setup', 'market', 'launch_shape', 'setup', 'trend')):
            self.assertEqual(m.proposals(m.BASE, {block: 10}, set(), 4)[0], layer)
        self.assertEqual(m.proposals(branch, {}, seen, 5), ('exhausted', []))
        self.assertEqual(m.previous.WORK.name, 'ie17_work')
        self.assertIsNot(m.previous.build, m.build)

    def test_source_contains_no_human_stock_or_entry_date_literals(self):
        labels = m.old.ledger.load(m.old.LEDGER)
        forbidden = {r.ticker for r in labels} | {'US.' + r.ticker for r in labels}
        forbidden |= {r.entry_date for r in labels if r.entry_date}
        for path in (Path(m.__file__), Path(__file__), *m.WORK.glob('*.py')):
            literals = {n.value for n in ast.walk(ast.parse(path.read_text()))
                        if isinstance(n, ast.Constant) and isinstance(n.value, str)}
            self.assertFalse(literals & forbidden, path.name)


if __name__ == '__main__':
    unittest.main()
