import csv
from datetime import date, timedelta
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np

from studies.trader_screens import board, focus, martin_candidates as m, scan


def sample():
    rng = np.random.default_rng(31)
    days, day = [], date(2024, 1, 2)
    while len(days) < 285:
        if day.weekday() < 5:
            days.append(day.isoformat())
        day += timedelta(days=1)
    close = (20 * np.exp(np.cumsum(rng.normal(.001, .04, (285, 340)), axis=0))).astype(np.float32)
    spread = rng.uniform(.01, .09, close.shape).astype(np.float32)
    p = dict(days=np.array(days), codes=np.array([f'SYN_{j:03}' for j in range(340)]),
             close=close, raw_close=close.copy(), open=close.copy(), high=close * (1 + spread),
             low=close / (1 + spread), turnover=np.full(close.shape, 2e8, np.float32),
             volume=np.full(close.shape, 1e7, np.float32), digest='synthetic')
    def rows():
        for j, code in enumerate(p['codes']):
            for t, day in enumerate(p['days']):
                yield str(code), str(day), [float(p[k][t, j]) for k in
                                           ('open', 'high', 'low', 'raw_close', 'volume', 'turnover')]
    ds = SimpleNamespace(rows=rows, actions=lambda: {}, names=lambda: {})
    return p, ds


class CandidateTests(unittest.TestCase):
    def test_fixed_filters_use_full_scope_and_ranking_uses_events_and_small_pool(self):
        codes = ['SYN_' + str(j) for j in range(100)]
        raw = np.repeat(np.arange(100, dtype=np.float32)[:, None], 6, axis=1)
        raw[:, 4] = 0
        raw[81, 4] = raw[82, 4] = 1
        raw[82, 5] = raw[81, 5]  # A stable code tie.
        raw[99, 2] = np.nan
        result = m.rank_night(codes[::-1], raw[::-1])
        selected = result['codes'][result['order']].tolist()
        self.assertEqual(set(selected), set(codes[79:99]))
        self.assertEqual(selected[:2], [codes[81], codes[82]])
        self.assertEqual(result['ranked'][result['order'][0], 0], 1.)
        self.assertEqual(result['ranked'][result['codes'] == codes[98], 1], [1.])

    def test_missing_filter_fails_and_missing_rank_is_neutral(self):
        raw = np.ones((4, 6), np.float32)
        raw[:, 4:] = [[1, np.nan], [0, 0], [1, 1], [1, 2]]
        # A single finite filtering value ranks neutral, below the option cutoff.
        raw[:3, 2] = np.nan
        result = m.rank_night(['D', 'C', 'B', 'A'], raw)
        self.assertFalse(result['passed'].any())
        self.assertEqual(result['order'].tolist(), [])
        raw = np.repeat(np.arange(100, dtype=np.float32)[:, None], 6, axis=1)
        raw[:, 4] = 0
        raw[99, 4:] = [1, np.nan]
        result = m.rank_night([f'SYN_{j:03}' for j in range(100)], raw)
        self.assertEqual(result['codes'][result['order'][0]], 'SYN_099')
        self.assertEqual(result['scores'][-1], .75)

    def test_all_price_and_history_inputs_stop_at_the_observation_night(self):
        p, ds = sample()
        cut = 273  # Friday: complete week is known without a later price.
        self.assertEqual(date.fromisoformat(str(p['days'][cut])).weekday(), 4)
        shortened = {k: v[:cut + 1] if isinstance(v, np.ndarray) and v.ndim and k != 'codes' else v
                     for k, v in p.items()}
        with patch.object(m, 'option_volume', side_effect=lambda codes, day, mode:
                          (np.arange(len(codes), dtype=np.float32), day)):
            before = m.build(shortened, ds, asof=str(p['days'][cut]), names={}, industries={})
            for key in ('open', 'high', 'low', 'close', 'raw_close', 'volume', 'turnover'):
                p[key][cut + 1:] *= 50
            after = m.build(p, ds, asof=str(p['days'][cut]), names={}, industries={})
        self.assertEqual(before, after)
        self.assertGreater(before['count'], 0)

    def test_option_cache_is_exact_day_and_honors_the_data_mode(self):
        from studies.trader_options import pricing
        with tempfile.TemporaryDirectory() as tmp:
            base, live = Path(tmp) / 'frozen', Path(tmp) / 'live'
            for root, rows in ((base, [('2026-01-02', 10), ('2026-01-06', 99999)]),
                               (live, [('2026-01-02', 20), ('2026-01-05', 30)])):
                (root / 'stat').mkdir(parents=True)
                with (root / 'stat' / 'SYN_A.csv').open('w') as stream:
                    writer = csv.writer(stream)
                    writer.writerow(['time', 'option_volume'])
                    writer.writerows(rows)
            with patch.object(pricing, 'DATA', base), patch.object(pricing, 'LIVE', live):
                values, latest = m.option_volume(['SYN_A', 'SYN_MISSING'], '2026-01-05', 'frozen')
                self.assertTrue(np.isnan(values).all())
                self.assertEqual(latest, '2026-01-02')
                values, latest = m.option_volume(['SYN_A', 'SYN_MISSING'], '2026-01-05', 'live')
                self.assertEqual(values[0], 30)
                self.assertTrue(np.isnan(values[1]))
                self.assertEqual(latest, '2026-01-05')
                self.assertEqual(m.option_volume(['SYN_A'], '2026-01-02', 'live')[0][0], 10)

    def test_insufficient_history_is_reported_even_with_complete_option_data(self):
        p, ds = sample()
        shortened = {k: v[:40] if isinstance(v, np.ndarray) and v.ndim and k != 'codes' else v
                     for k, v in p.items()}
        with patch.object(m, 'option_volume', side_effect=lambda codes, day, mode:
                          (np.arange(len(codes), dtype=np.float32), day)):
            result = m.build(shortened, ds, names={}, industries={})
        self.assertEqual(result['status'], 'unavailable')
        self.assertEqual(result['count'], 0)
        self.assertIn('h4_history', result['unavailable_inputs'])
        self.assertIn('没有可用的历史反复强势', result['note'])

    def test_empty_and_partial_pools_render_separately_from_transactions(self):
        from studies.trader_screens.tests.test_review_fixes import result, trader
        r = result([trader('Martin Luk')])
        original = json.dumps(r['traders'], sort_keys=True)
        original_groups = focus.stock_groups(r)
        pool = dict(label=m.LABEL, asof=r['last_day'], count=12, status='partial',
                    note='期权输入未齐，当前结果不能视为完整候选池。', candidates=[
            dict(code=f'SYN_{j}', name=f'Company {j}', industry='半导体', label=m.LABEL, rank=j + 1,
                 reference=j < 5, reason=m.REASON, ranking_reason='内包日次日；靠近9日线')
            for j in range(12)])
        r['martin_candidates'] = pool
        rendered = board.render(r)
        self.assertIn('共 12 只', rendered)
        self.assertEqual(rendered.count('排名参考'), 5)
        self.assertIn('Company 0（SYN_0；半导体）', rendered)
        self.assertNotIn('Company 5', rendered)
        self.assertEqual(focus.stock_groups(r), original_groups)
        self.assertEqual(json.dumps(r['traders'], sort_keys=True), original)
        self.assertEqual(rendered.count('<details>'), rendered.count('</details>'))
        pool.update(count=0, candidates=[], status='unavailable', note='没有当晚期权成交量。')
        self.assertIn('输入不足', board.render(r))
        empty = {k: v[:0] if isinstance(v, np.ndarray) and k != 'codes' else v for k, v in sample()[0].items()}
        self.assertEqual(m.build(empty, SimpleNamespace(), asof='2026-01-02')['status'], 'unavailable')

    def test_scan_attaches_observation_without_changing_registered_records(self):
        from studies import trader_data
        from studies.trader_replication import runner, systems
        from studies.trader_replication.tests.test_runner import panel, system
        p = panel()
        p.update(volume=np.full(p['close'].shape, 1e6), turnover=np.full(p['close'].shape, 1e8),
                 raw_close=p['close'].copy(), digest='synthetic')
        selected = system(p, str(p['days'][-1]))
        records = runner.run(selected, 'us')
        ds = SimpleNamespace(id='synthetic', panel=lambda: p, names=lambda: {})
        pool = {'label': m.LABEL}
        with patch.object(trader_data, 'dataset', return_value=ds), \
                patch.object(systems, 'board', return_value=[selected]), \
                patch.object(runner, 'run', return_value=records), \
                patch.object(scan.data, 'industries', return_value={}), \
                patch.object(m, 'build', return_value=pool) as build:
            r = scan.run('us', 'frozen')
            self.assertIs(r['martin_candidates'], pool)
            self.assertEqual(r['traders'][0]['buys'], records['buys'])
            self.assertEqual(r['traders'][0]['holdings'], records['holdings'])
            build.assert_called_once()
            build.reset_mock()
            scan.run('us', 'live', panel=p)
            build.assert_not_called()


@unittest.skipUnless((m.ie9.WORK / 'full_features.npy').exists()
                     and (m.ie8.old.WORK / 'prepared.json').exists()
                     and (m.ie8.ROOT / 'data/trader-data-v1/us/universe.json').exists(),
                     'requires the existing frozen dataset and IE8/IE9 research caches; never fetches')
class ResearchParityTests(unittest.TestCase):
    def test_three_real_2026_nights_match_every_value_pool_and_rank(self):
        from studies import trader_data as TD
        from studies.trader_data import panel
        ds = TD.frozen('us')
        p = panel.build(ds, write_cache=False)
        research = m.ie8.ie7.Data(full=True)
        values = np.load(m.ie9.WORK / 'full_features.npy', mmap_mode='r')
        for day in ('2026-01-09', '2026-06-05', '2026-10-16'):
            with self.subTest(day=day), patch.object(m, 'rank_night', wraps=m.rank_night) as ranked:
                actual = m.build(p, ds, 'frozen', asof=day, names={}, industries={})
                codes, raw = ranked.call_args.args
                sl = research.slices[day]
                self.assertEqual(codes, research.meta['scope'][day])
                columns = [research.names.index(f) for f in m.FACTORS[:4]]
                expected_raw = research.raw[sl][:, columns]
                np.testing.assert_array_equal(raw[:, :4], expected_raw)
                np.testing.assert_array_equal(raw[:, 5], research.raw[sl, research.names.index('near_ema9')])
                expected_pct = m.ie8.ie7.night_percentiles(expected_raw)
                passed = m.ie8.gate_mask(expected_pct, list(m.FACTORS[:4]), m.ie9.GATES)
                np.testing.assert_array_equal(raw[passed, 4], values[sl][passed, m.ie9.NAMES.index('after_inside')])
                order, _ = m.ie9.rank_night(values[sl], passed, list(m.ie9.NAMES), list(m.FACTORS[4:]))
                self.assertEqual([r['code'] for r in actual['candidates']], [codes[k] for k in order])
                for row, k in zip(actual['candidates'], order):
                    for j, name in enumerate(m.FACTORS[:4]):
                        self.assertEqual(row['factors'][name]['percentile'], float(expected_pct[k, j]))
                    near = values[sl][k, m.ie9.NAMES.index('near_ema9')]
                    self.assertEqual(row['factors']['near_ema9']['percentile'], float(near))
                    event = values[sl][k, m.ie9.NAMES.index('after_inside')]
                    self.assertEqual(row['score'], (float(event) + float(near)) / 2)


if __name__ == '__main__':
    unittest.main()
