"""Synthetic-data checks for the trend-breakout sources, fetch and panel helpers (no network, no OpenD)."""
import gzip
import tempfile
import types
import unittest
from unittest import mock
from pathlib import Path

import numpy as np

from studies.trend_breakout import fetch, panel, sources


class Sources(unittest.TestCase):
    def test_sina_rows_keep_the_window_and_estimate_turnover(self):
        payload = [{'day': '2023-08-31', 'open': '1', 'high': '1', 'low': '1', 'close': '1', 'volume': '1'},
                   {'day': '2024-01-02', 'open': '10.0', 'high': '10.8', 'low': '9.9', 'close': '10.5', 'volume': '1000'}]
        self.assertEqual(sources.sina_rows('SZ.000001', payload, '2023-09-01', '2026-10-09'),
                         [('SZ.000001', '2024-01-02', 10.0, 10.8, 9.9, 10.5, 1000.0, 10500.0)])

    def test_sina_factors_become_opend_style_actions(self):
        text = ('var sz300394qfq={"total":3,"data":[{"d":"2026-06-12", "f":"1.0"},'
                '{"d":"2025-09-19", "f":"1.4"},{"d":"2024-05-30", "f":"1.96"}]}')
        factors = sources.sina_factors(text)
        self.assertEqual(factors, [('2024-05-30', 1.96), ('2025-09-19', 1.4), ('2026-06-12', 1.0)])
        self.assertEqual(sources.factor_on(factors, '2026-06-11'), 1.4)
        self.assertEqual(sources.factor_on(factors, '2026-06-12'), 1.0)
        src = sources.CnHttpSource()
        src._factors['SZ.300394'] = factors
        acts = src.actions('SZ.300394')
        self.assertEqual([a[1] for a in acts], ['2025-09-19', '2026-06-12'])
        self.assertAlmostEqual(acts[1][2], 1 / 1.4)  # a 10-for-4 conversion: 1.4 shares per old share

    def test_tencent_rows_convert_lots_and_keep_the_window(self):
        days = [['2017-12-29', '1', '1', '1', '1', '1'], ['2018-01-02', '700.0', '703.85', '710.16', '689.89', '49612.0']]
        self.assertEqual(sources.tencent_rows('SH.600519', days, '2018-01-01', '2023-08-31'),
                         [('SH.600519', '2018-01-02', 700.0, 710.16, 689.89, 703.85, 4961200.0, 3491940620.0)])
        star = [['2023-09-01', '54.38', '53.68', '54.68', '52.76', '37284250.000']]  # STAR volume is in shares
        self.assertEqual(sources.tencent_rows('SH.688981', star, '2023-09-01', '2023-09-01')[0][6], 37284250.0)

    def test_sina_share_history_parses_dates_and_10k_units(self):
        html = ('<td><div align="center">2001-07-31</div></td>\n   <td><div align="center">18500万股</div></td>'
                '<td><div align="center">2024-05-30</div></td>\n   <td><div align="center">125619.78万股</div></td>')
        self.assertEqual(sources.sina_shares(html), [('2001-07-31', 185000000.0), ('2024-05-30', 1256197800.0)])

    def test_cn_selection_uses_opend_codes_and_drops_beijing_and_small_caps(self):
        rows = [{'symbol': 'sh600519', 'name': 'A', 'mktcap': '2000000', 'amount': '1'},
                {'symbol': 'bj830799', 'name': 'B', 'mktcap': '9000000', 'amount': '1'},
                {'symbol': 'sz000002', 'name': 'C', 'mktcap': '500000', 'amount': '1'}]
        self.assertEqual([r['code'] for r in sources.select_cn(rows, 100e8)], ['SH.600519'])


class FakeFrame:
    def __init__(self, days):
        self.time_key = FakeColumn([d + ' 00:00:00' for d in days])

    def __len__(self):
        return len(self.time_key.values)


class FakeColumn:
    def __init__(self, values):
        self.values = values
        self.iloc = values


class FakeQuote:
    """get_cur_kline that serves a growing history, the way OpenD loads HK bars after subscribing."""
    def __init__(self, stages):
        self.stages, self.calls = stages, 0

    def get_cur_kline(self, code, num, ktype, au):
        days = self.stages[min(self.calls, len(self.stages) - 1)]
        self.calls += 1
        return 0, FakeFrame(days)


class LoadingWait(unittest.TestCase):
    def source(self, stages, listed):
        src = sources.OpenDSource.__new__(sources.OpenDSource)
        src.ft = types.SimpleNamespace(RET_OK=0, SubType=types.SimpleNamespace(K_DAY='K_DAY'))
        src.q, src._listed = FakeQuote(stages), {'HK.1': listed}
        return src

    def test_partial_history_is_not_accepted_before_it_reaches_the_listing_date(self):
        full = ['2019-01-02', '2024-01-02', '2026-10-15']
        src = self.source([full[-1:], full[-2:], full], '2019-01-02')
        with mock.patch.object(sources.time, 'sleep'):
            self.assertEqual(len(src.full_kline('HK.1', 'raw')), 3)
        self.assertEqual(src.q.calls, 3)

    def test_unknown_listing_needs_a_stable_count_and_a_timeout_gives_none(self):
        clock = iter(range(0, 1000, 2))
        with mock.patch.object(sources.time, 'sleep'), mock.patch.object(sources.time, 'time', lambda: next(clock)):
            src = self.source([['2026-10-14'], ['2026-10-14', '2026-10-15']], '1970-01-01')
            self.assertEqual(len(src.full_kline('HK.1', 'raw')), 2)
            src = self.source([['2026-10-15']], '2019-01-02')
            self.assertIsNone(src.full_kline('HK.1', 'raw'))  # never reaches the listing date
            src = self.source([['2026-10-15']], '2019-01-02')
            self.assertEqual(len(src.full_kline('HK.1', 'qfq', expect=1)), 1)  # matches the accepted raw history


class Actions(unittest.TestCase):
    def test_factors_apply_actions_to_earlier_days(self):
        days = np.array(['2024-01-01', '2024-01-02', '2024-01-03', '2024-01-04'])
        raw = np.array([10.0, 10.5, 10.0, 11.0])
        f = panel.factors(raw, days, [('2024-01-03', 1.0, -1.0), ('2030-01-01', 0.5, 0.0), ('2024-01-01', 2.0, 0.0)])
        np.testing.assert_allclose(f, [1 - 1 / 10.5] * 2 + [1, 1])
        # standard back-adjustment: the ex-day return is raw / (previous raw - dividend)
        self.assertAlmostEqual(raw[2] * f[2] / (raw[1] * f[1]), 10.0 / (10.5 - 1.0))

    def test_action_on_a_non_trading_day_applies_on_the_next_bar(self):
        days = np.array(['2024-01-01', '2024-01-03'])
        np.testing.assert_allclose(panel.factors([20.0, 10.0], days, [('2024-01-02', 0.5, 0.0)]), [0.5, 1.0])


class PanelLoading(unittest.TestCase):
    def test_load_builds_aligned_panels_and_splits(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            fetch.prepare(folder)
            fetch.write_json(folder / 'universe.json', {'stocks': [{'code': 'A'}, {'code': 'B'}]})
            fetch.append_rows(folder / 'bars_raw.csv.gz', [('DELISTED', '2024-09-30', 1, 1, 1, 1, 1, 1)])
            fetch.append_rows(folder / 'actions.csv.gz', [('A', '2024-09-30', 0.5, 0), ('A', '2024-09-30', 0.5, 0)])
            fetch.append_rows(folder / 'bars_qfq.csv.gz', [
                ('A', '2024-09-30', 1, 2, 0.5, 1.5, 100, 150), ('B', '2024-10-01', 5, 6, 4, 5.5, 10, 55)])
            fetch.append_rows(folder / 'bars_raw.csv.gz', [
                ('A', '2024-09-30', 2, 4, 1, 3, 100, 300), ('B', '2024-10-01', 5, 6, 4, 5.5, 10, 55)])
            p = panel.load(folder)
            folder_actions = folder / 'actions.csv.gz'
            self.assertEqual(panel.read_actions(folder_actions)['A'], [('2024-09-30', 0.5, 0.0)])
        self.assertEqual(list(p['codes']), ['A', 'B'])
        self.assertEqual(p['close'][0, 0], 3.0)  # the only action is on the first day: nothing earlier to rescale
        self.assertEqual(p['turnover'][0, 0], 300.0)
        self.assertTrue(np.isnan(p['close'][0, 1]))
        self.assertEqual(list(panel.mask(p['dates'], 'train')), [False, True])

    def test_splits_are_contiguous_and_ordered(self):
        spans = [panel.SPLITS[k] for k in ('warmup', 'train', 'test')]
        for (_, end), (start, _) in zip(spans, spans[1:]):
            self.assertLess(end, start)
        self.assertEqual(spans[0][0], fetch.START)
        self.assertEqual(spans[-1][1], fetch.END)

    def test_header_mismatch_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'bars_qfq.csv.gz'
            with gzip.open(path, 'wt') as f:
                f.write('code,date,close\n')
            with self.assertRaises(ValueError):
                list(panel.read_bars(path))


if __name__ == '__main__':
    unittest.main()
