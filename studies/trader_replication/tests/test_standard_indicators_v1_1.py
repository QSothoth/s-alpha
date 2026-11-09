"""v1.1 inclusion, exact earlier values and per-indicator causal clocks."""
import json
from pathlib import Path
import unittest
import warnings

import numpy as np

from studies.trader_replication import standard_indicators as lib
from studies.trader_replication import standard_indicators_dedup as dedup
from studies.trader_replication.tests.test_standard_indicators import synthetic


def latest_data_time(name):
    """The latest observation permitted by the formula, not a vendor timestamp claim."""
    if name == 'price':
        return 't 日真实未复权收盘 raw_c；缺失记 NaN，不用复权 c 回填'
    if name in ('gap_today_adr', 'days_since_10pct_gap'):
        return '跳空值最晚用 t 日开盘和 t−1 历史；输出有效性还检查 t 日收盘是否存在'
    if name == 'earnings_gap_pct':
        return 't 行已知财报索引须 ≤ t；跳空价格最晚取 t 日开盘，输出有效性检查 t 日收盘'
    if name == 'weekly_pivot_position':
        return 't 日收盘；P、R1、S1 来自上一完整周，区间位置使用 t 日收盘价'
    if name == 'chan_weekly_buy':
        return '结构值截至上一完整周收盘；输出有效性还检查 t 日收盘是否存在'
    if name.startswith('h4_'):
        return 'extras 第 t 行；现有缓存组分取 t−1、按 t 行可见范围排名，不读取 t+1 行'
    if name in ('iv_pct', 'iv_percentile252', 'iv_minus_hv', 'option_rvol20',
                'put_call_volume_ratio', 'put_call_oi_ratio', 'option_oi_change5_pct', 'earn_days', 'potent_days20'):
        return 'extras 第 t 行及以前；输入须在计算当晚已发布，缺失不向前回填'
    if name in ('rising_swing_lows', 'smc_bos', 'smc_choch', 'smc_low_sweep', 'smc_order_block_distance_adr'):
        return 't 日收盘；左右各 2 根的摆动点最早在中心 t−2 的右侧 2 根走完后确认'
    if name == 'darvas_breakout':
        return 't 日收盘；箱顶候选 t−3，右侧 3 根确认到 t，突破也只看 t'
    if name.startswith('chan_'):
        return 't 日收盘；包含合并、分型右侧确认、笔与中枢只用截至 t 的已走完 K 线'
    if name.startswith('weekly_') or name in ('inside_week', 'weinstein_stage'):
        return 't 日收盘；本周只合成到 t，此前完整周最晚在上周收盘'
    if name == 'avwap_earnings_distance_adr':
        return 't 日收盘；财报锚点为已可见的首个公告后交易日，索引必须 ≤ t'
    if name.startswith(('theme_', 'ibd_')) or name == 'minervini_score':
        return '全市场或给定范围截至 t 日收盘的尾窗；成员和有效样本只看当晚，不看后续上市行情'
    return 't 日收盘；滚动窗口、累计状态和锚点均不越过 t'


def _fixtures():
    a, q, e = synthetic(420)
    yield 'random_ohlcv', a, q, e
    missing = {k: v.copy() for k, v in a.items()}
    for key in ('o', 'h', 'l', 'c', 'raw_c', 'v', 't'):
        missing[key][:55] = np.nan
        missing[key][181:185] = np.nan
    yield 'ipo_and_internal_missing', missing, q, e
    weekly = {k: v.copy() for k, v in a.items()}
    centers = np.interp(np.arange(84), np.arange(0, 85, 6),
                        [100, 160, 90, 150, 60, 140, 80, 170, 100, 190, 120, 210, 150, 230, 170])
    c = np.repeat(centers, 5)
    weekly.update(c=c, raw_c=c.copy(), o=c*.999, h=c+1, l=c-1, t=c*weekly['v'])
    yield 'confirmed_weekly_structure', weekly, q, e


def _assert_equal(actual, expected, name):
    np.testing.assert_array_equal(np.isnan(actual), np.isnan(expected), err_msg=name)
    np.testing.assert_allclose(actual, expected, rtol=0, atol=1e-10, equal_nan=True, err_msg=name)


def audit_adjustment_invariance():
    """A later corporate action may rescale the past, never alter its features."""
    rows = {name: dict(name=name, comparisons=0, finite_values=0, max_abs_difference=0., passed=True)
            for name in lib.V1_1_NAMES}
    cases = list(_fixtures())
    a, q, extras = synthetic(420)
    c = np.full(len(q), 20.)
    a.update(o=c.copy(), h=c*1.5, l=c*.5, c=c, raw_c=c.copy(), t=c*a['v'])
    cases.append(('flat_uniform_volume_profile', a, q, extras))
    failures = []

    def compare(name, before, after, case):
        row = rows[name]
        finite = np.isfinite(before) & np.isfinite(after)
        difference = float(np.max(abs(before[finite]-after[finite]))) if finite.any() else 0.
        passed = bool(np.array_equal(np.isnan(before), np.isnan(after)) and
                      np.allclose(before, after, rtol=0, atol=1e-9, equal_nan=True))
        row['comparisons'] += before.size
        row['finite_values'] += int(finite.sum())
        row['max_abs_difference'] = max(row['max_abs_difference'], difference)
        row['passed'] &= passed
        if not passed:
            failures.append(dict(name=name, case=case, max_abs_difference=difference))

    with warnings.catch_warnings():
        warnings.filterwarnings('ignore', message='Mean of empty slice')
        for label, arrays, q, extras in cases:
            full = lib.per_stock(arrays, q, extras)
            for stop in (61, 202, 360):
                for k in (10., .05):
                    changed = {key: value.copy() for key, value in arrays.items()}
                    for key in ('o', 'h', 'l', 'c'):
                        changed[key][:stop] *= k
                    changed['v'][:stop] /= k
                    # Traded amount and raw close describe actual historical trades.
                    np.testing.assert_array_equal(changed['t'], arrays['t'])
                    np.testing.assert_array_equal(changed['raw_c'], arrays['raw_c'])
                    transformed = lib.per_stock(changed, q, extras)
                    for name in rows:
                        if name in full:
                            compare(name, full[name][:stop], transformed[name][:stop], [label, stop-1, k])

        arrays, q, _ = synthetic(320)
        rng = np.random.default_rng(3902)
        c = np.stack([arrays['c']*np.exp(np.cumsum(rng.normal(0, .003, len(q)))) for _ in range(9)])
        c[-1, :290] = np.nan
        c[1, 121:128] = np.nan
        h, l = c*1.02, c*.98
        for end in (61, 126, 253, 320):
            start = max(0, end-253)
            full = lib.cross_section(c[:, start:end], h[:, start:end], l[:, start:end], block_size=3)
            for k in (10., .05):
                for chosen in ([3], list(range(len(c)))):
                    changed = [value[:, :end].copy() for value in (c, h, l)]
                    for value in changed:
                        value[chosen] *= k
                    transformed = lib.cross_section(*(value[:, start:] for value in changed), block_size=2)
                    for name in rows:
                        if name in full:
                            compare(name, full[name], transformed[name], ['market', end-1, k, chosen])
    if any(not row['comparisons'] or not row['finite_values'] for row in rows.values()):
        raise AssertionError('every frozen indicator needs finite adjustment comparisons')
    return dict(passed=not failures, indicators=len(rows), scales=[10., .05], atol=1e-9, rtol=0,
                cases=[case[0] for case in cases]+['market_single_stock_and_whole_market'],
                failures=failures, details=list(rows.values()))


def audit_causality():
    """Compare every earlier output with independent prefix recomputations.

    Every retained item is checked, including missing values. Event-adjacent
    checkpoints force the structural and weekly branches to execute.
    """
    rows = {s['name']: dict(name=s['name'], layer=s['layer'], prefix_values_checked=0,
                           finite_values_checked=0, nonzero_values_checked=0, checkpoints=0,
                           latest_data_time=latest_data_time(s['name']), passed=True) for s in lib.SPEC}
    cases = []
    with warnings.catch_warnings():
        warnings.filterwarnings('ignore', message='Mean of empty slice')
        for label, arrays, q, extras in _fixtures():
            full = lib.per_stock(arrays, q, extras)
            stops = {1, 2, 3, 5, 6, 14, 15, 19, 20, 21, 50, 51, 55, 56, 59, 60,
                     61, 65, 66, 99, 100, 101, 126, 150, 181, 182, 185, 186,
                     190, 191, 194, 195, 200, 201, 252, 253, 254, 255, 256, 309, 310, 311,
                     312, 313, 314, 315, 316, 359, 360, 419, 420}
            for spec in lib.SPEC:
                name = spec['name']
                if spec['layer'] != 'per_stock':
                    continue
                finite = np.flatnonzero(np.isfinite(full[name]))
                if len(finite):
                    stops.update(int(t)+1 for t in (finite[0], finite[len(finite)//2], finite[-1]))
                if spec['binary']:
                    active = np.flatnonzero(full[name] > 0)
                    if len(active):
                        first = int(active[0])+1
                        stops.update((max(1, first-1), first, min(len(q), first+1)))
            for stop in sorted(stops):
                short = lib.per_stock({k: value[:stop] for k, value in arrays.items()}, q[:stop],
                                      {k: value[:stop] for k, value in extras.items()})
                for name, values in full.items():
                    _assert_equal(values[:stop], short[name], f'{label}/{name}/prefix={stop}')
                    row = rows[name]
                    finite = np.isfinite(short[name])
                    row['prefix_values_checked'] += stop
                    row['finite_values_checked'] += int(finite.sum())
                    row['nonzero_values_checked'] += int(np.sum(finite & (short[name] != 0)))
                    row['checkpoints'] += 1
            # Give the future different prices, volume and optional observations.
            # The early prefix must survive even when future anchors change.
            stop = 201
            changed = {k: value.copy() for k, value in arrays.items()}
            changed_extras = {k: value.copy() for k, value in extras.items()}
            for key in ('o', 'h', 'l', 'c'):
                changed[key][stop:] *= 13
            changed['v'][stop:] *= 100
            changed['t'][stop:] *= 1300
            for key in changed_extras:
                changed_extras[key][stop:] += 123
            altered = lib.per_stock(changed, q, changed_extras)
            for name in full:
                _assert_equal(full[name][:stop], altered[name][:stop], f'{label}/{name}/changed-future')
            cases.append(dict(case=label, sessions=len(q), prefix_checkpoints=len(stops), future_mutation_checked=True))

        arrays, q, _ = synthetic(320)
        rng = np.random.default_rng(3901)
        c = np.stack([arrays['c']*np.exp(np.cumsum(rng.normal(0, .001, len(q)))) for _ in range(9)])
        c[-1, :290] = np.nan
        c[1, 121:128] = np.nan
        h, l = c*1.02, c*.98
        scope = np.array([True]*8+[False])
        # Full timeline, then the same interface on independently truncated data.
        timeline = {name: [] for name in lib.CROSS_SECTION_NAMES}
        for t in range(len(q)):
            start = max(0, t-252)
            values = lib.cross_section(c[:, start:t+1], h[:, start:t+1], l[:, start:t+1],
                                       scope_mask=scope, block_size=3)
            for name in timeline:
                timeline[name].append(values[name])
        cross_stops = (1, 40, 60, 61, 62, 121, 128, 200, 252, 253, 254, 289, 290, 291, 319, 320)
        for stop in cross_stops:
            cc, hh, ll = (x[:, :stop].copy() for x in (c, h, l))
            start = max(0, stop-253)
            values = lib.cross_section(cc[:, start:], hh[:, start:], ll[:, start:], scope_mask=scope, block_size=2)
            for name in timeline:
                _assert_equal(timeline[name][stop-1], values[name], f'{name}/cross-prefix={stop}')
                row, finite = rows[name], np.isfinite(values[name])
                row['prefix_values_checked'] += len(c)
                row['finite_values_checked'] += int(finite.sum())
                row['nonzero_values_checked'] += int(np.sum(finite & (values[name] != 0)))
                row['checkpoints'] += 1
        cases.append(dict(case='market_cross_sections_with_future_ipo_and_missing', sessions=len(q),
                          stocks=len(c), prefix_checkpoints=len(cross_stops), block_sizes=[3, 2]))
    for row in rows.values():
        if not row['checkpoints'] or not row['finite_values_checked']:
            raise AssertionError('no observed causal comparisons: '+row['name'])
    return dict(passed=True, indicators=len(rows), retained=list(lib.V1_1_NAMES), cases=cases,
                tolerance=dict(atol=1e-10, rtol=0, nan_positions_equal=True), details=list(rows.values()))


class V11IndicatorsTest(unittest.TestCase):
    def test_future_splits_and_reverse_splits_cannot_rewrite_any_frozen_indicator(self):
        result = audit_adjustment_invariance()
        self.assertTrue(result['passed'], result['failures'])
        self.assertEqual(result['indicators'], len(lib.V1_1_NAMES))

    def test_price_requires_actual_raw_close_and_never_falls_back_to_adjusted_close(self):
        a, q, extras = synthetic(120)
        a['raw_c'] = a['c']*10
        for getter in (lib.per_stock, lib.legacy_per_stock):
            np.testing.assert_array_equal(getter(a, q, extras)['price'], a['raw_c'])
            missing = {key: value for key, value in a.items() if key != 'raw_c'}
            self.assertTrue(np.isnan(getter(missing, q, extras)['price']).all())
            missing['raw_c'] = np.full(len(q), np.nan)
            self.assertTrue(np.isnan(getter(missing, q, extras)['price']).all())

    def test_legacy_metadata_and_same_definition_aliases_have_one_canonical_item(self):
        self.assertEqual({s['name'] for s in lib.SPEC if s['origin'] == 'legacy'}, set(lib.LEGACY_NAMES))
        by_name = {s['name']: s for s in lib.SPEC}
        for alias, canonical in lib.LEGACY_ALIASES.items():
            self.assertNotIn(alias, by_name)
            self.assertIn(alias, by_name[canonical]['aliases'])

    def test_all_indicators_ignore_future_prices_and_extras_including_structural_events(self):
        result = audit_causality()
        self.assertTrue(result['passed'])
        self.assertEqual(set(lib.V1_1_NAMES)-{r['name'] for r in result['details']}, set())
        flags = [s['name'] for s in lib.SPEC if s['binary']]
        counts = {row['name']: row['nonzero_values_checked'] for row in result['details']}
        for name in flags:
            self.assertGreater(counts[name], 0, name)

    def test_future_earnings_anchor_is_ignored_until_its_session(self):
        a, q, extras = synthetic(120)
        extras['earn_index'] = np.full(len(q), 80.)
        values = lib.per_stock(a, q, extras)
        for name in ('avwap_earnings_distance_adr', 'earnings_gap_pct'):
            self.assertTrue(np.isnan(values[name][:80]).all(), name)
            self.assertTrue(np.isfinite(values[name][80:]).all(), name)
            short = lib.per_stock({k: v[:65] for k, v in a.items()}, q[:65], {k: v[:65] for k, v in extras.items()})
            _assert_equal(short[name], values[name][:65], name)

    def test_frozen_versions_and_every_legacy_item_are_preserved(self):
        original = json.loads((dedup.GAP/'standard_indicators_v1_dedup.json').read_text())
        self.assertEqual(list(lib.V1_NAMES), original['retained'])
        path = dedup.GAP/'standard_indicators_v1_1_dedup.json'
        self.assertTrue(path.exists(), 'v1.1 must be frozen before final verification')
        frozen = json.loads(path.read_text())
        self.assertEqual(list(lib.V1_1_NAMES), frozen['retained'])
        coverage = dedup.legacy_coverage(lib.V1_1_NAMES, frozen['pairs_abs_rho_at_least_0_8'])
        self.assertEqual({r['name'] for r in coverage}, set(lib.LEGACY_NAMES))
        self.assertEqual(coverage, frozen['legacy_coverage'])
        self.assertEqual(len(coverage), 45)

    def test_legacy_priority_and_tradingview_priority_follow_specification(self):
        specs = [dict(name='other', origin='standard_v1'), dict(name='rsi14', origin='standard_v1'),
                 dict(name='old_first', origin='legacy'), dict(name='macd_hist_pct', origin='standard_v1'),
                 dict(name='old_second', origin='legacy')]
        self.assertEqual(dedup.retention_order(specs, 'v1.1'), [2, 4, 1, 3, 0])
        self.assertEqual(dedup.retention_order(specs, 'v1'), list(range(5)))
        frozen = json.loads((dedup.GAP/'standard_indicators_v1_1_dedup.json').read_text())
        rare = {row['name'] for row in frozen['dropped'] if row['reason'] == 'binary_occurrence_below_1pct'}
        self.assertFalse(rare & set(lib.LEGACY_NAMES))

    def test_v1_family_metadata_and_binary_stack_keep_their_original_meaning(self):
        from studies.trader_replication.martin_profile_ie38 import family
        for spec in lib.V1_SPEC:
            self.assertEqual(family(spec['name']), spec['family'], spec['name'])
        a, q, extras = synthetic(120)
        old = lib.per_stock(a, q, extras, version='v1')['ema_stack']
        current = lib.per_stock(a, q, extras)['ema_stack']
        self.assertTrue(set(old) <= {0, 1})
        self.assertEqual(set(current), {0, 1, 2})

    def test_44_legacy_columns_match_old_cache_and_price_is_checked_against_raw(self):
        path = dedup.GAP/'ie39_work/pool_legacy.npz'
        self.assertTrue(path.exists(), 'run --version v1.1 --verify-legacy before this integration check')
        provenance = json.loads((path.parent/'legacy_consistency.json').read_text())
        self.assertEqual(provenance['library_sha256'], dedup.library_hash())
        with np.load(path) as z:
            names, actual = list(z['names']), z['x']
        with np.load(dedup.GAP/'ie29_work/indicators_h4nan_v2.npz') as z:
            old_names, expected = list(z['names']), z['x']
        self.assertEqual(set(names), set(lib.LEGACY_NAMES))
        self.assertEqual(len(names), 45)
        for name, row in zip(names, actual):
            if name == 'price':
                self.assertEqual(provenance['exempt_indicators'], ['price'])
                self.assertTrue(provenance['price_matches_raw_c'])
                continue
            earlier = expected[old_names.index(name)]
            np.testing.assert_array_equal(np.isnan(row), np.isnan(earlier), err_msg=name)
            np.testing.assert_allclose(row, earlier, rtol=0, atol=1e-6, equal_nan=True, err_msg=name)


if __name__ == '__main__':
    unittest.main()
