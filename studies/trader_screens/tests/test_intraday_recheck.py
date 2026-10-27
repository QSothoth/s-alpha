"""Cutoff bars, missing data and the preregistered volume-only corrections."""
import unittest
import json
import tempfile
from pathlib import Path
from unittest import mock

import numpy as np

from studies.trader_screens import intraday_study as IS, intraday_i2 as I2, intraday_recheck as R
from studies.trader_screens.tests.test_confidence import panel


class CutoffTests(unittest.TestCase):
    def setUp(self):
        self.P = panel(n=40)
        self.d = 35
        self.P['raw_close'] = self.P['close'].copy()
        self.part = (10., 11., 9., 10.5, 100., 1050.)
        self.full = (10., 12., 8., 11., 300., 3300.)

    def test_raw_price_and_missing_names_do_not_retain_the_real_close(self):
        for version in ('I1', 'I2'):
            with self.subTest(version=version):
                if version == 'I1':
                    bars = {'US.A': {'15:50': self.part, 'full': self.full}}
                    row, _ = IS.provisional_row(self.P, self.d, bars, '15:50')
                else:
                    bars = {'US.A': ('recent', self.full, {'15:50': self.part[1:]})}
                    row, _ = I2.row_for(self.P, self.d, bars, '15:50', 'model', pred={})
                self.assertEqual(row['raw_close'][0], 10.5)
                self.assertEqual(row['volume'][0], 100.)
                for values in row.values():
                    self.assertTrue(np.isnan(values[1:]).all())

    def test_changes_after_cutoff_do_not_change_the_provisional_bar(self):
        bars = {'US.A': {'15:50': self.part, 'full': self.full}}
        a, _ = IS.provisional_row(self.P, self.d, bars, '15:50')
        Q = {k: v.copy() for k, v in self.P.items()}
        for k in ('high', 'low', 'close', 'volume', 'turnover', 'raw_close'):
            Q[k][self.d] *= 2
            Q[k][self.d + 1:] *= 5
        bars['US.A']['full'] = (10., 90., 1., 50., 0., 0.)
        b, _ = IS.provisional_row(Q, self.d, bars, '15:50')
        for key in a:
            np.testing.assert_array_equal(a[key], b[key], err_msg=key)

    def test_volume_schemes_never_change_prices_and_short_history_falls_back(self):
        row = {k: np.array([10., 20., 30.]) for k in R.FIELDS}
        for scheme in ('V1', 'V2', 'V3'):
            got = R.scale_row(row, scheme, .5, {'US.A': [.25] * 5, 'US.B': [.1] * 4}, self.P['codes'])
            for key in ('open', 'high', 'low', 'close', 'raw_close'):
                np.testing.assert_array_equal(got[key], row[key])
            expected = [40., 40., 60.] if scheme == 'V2' else [20., 40., 60.]
            np.testing.assert_array_equal(got['volume'], expected)
            np.testing.assert_array_equal(got['turnover'], row['turnover'] if scheme == 'V3' else expected)


class PartialSummaryTests(unittest.TestCase):
    def test_summarizing_completed_rows_never_loads_bars_or_replays_systems(self):
        trader = dict(sig=[['US.A', 1, 'pb']], buys=[['US.A', 1, False, 10., 9., 'pb']], sells=[])
        cases = {'true': {'toy': trader}}
        cases.update({f'{cut}/V0': {'toy': trader} for cut in IS.CUTS['us']})
        cases.update({f'15:50/{cause}': {'toy': trader} for cause in ('close', 'range', 'volume')})
        row = dict(day='2026-10-06', covered=1, systems=cases)
        def read(path):
            return dict(coverage=dict(names=1, sources=[])) if path.name.endswith('_plan.json') else {}
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(R, '__file__', str(Path(tmp) / 'recheck.py')), \
                mock.patch.object(R, 'MARKETS', ('us',)), mock.patch.object(R, 'read', side_effect=read), \
                mock.patch.object(R, 'records', return_value=iter([row])), \
                mock.patch.object(R.TP, 'build', side_effect=AssertionError('no bar loading')), \
                mock.patch.object(R.CF, 'decide_many', side_effect=AssertionError('no replay')):
            R.partial()
            result = json.loads((Path(tmp) / 'reports/intraday_recheck_partial.json').read_text())
        self.assertFalse(result['validation_run'])
        self.assertIsNone(result['chosen'])
        self.assertEqual(result['markets']['us']['cases']['15:50/V0']['toy']['buys'], [1, 0, 0])


if __name__ == '__main__':
    unittest.main()
