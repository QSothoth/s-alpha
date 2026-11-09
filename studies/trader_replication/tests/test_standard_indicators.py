"""Synthetic defaults, causal clocks and representative/alias checks."""
from datetime import date, timedelta
import ast
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest import mock

import numpy as np

from studies.trader_replication import standard_indicators as lib


def synthetic(n=360):
    rng = np.random.default_rng(831)
    c = 40*np.exp(np.cumsum(rng.normal(.0007, .027, n)))
    o = c*np.exp(rng.normal(0, .015, n))
    h, l = np.maximum(o, c)*rng.uniform(1.001, 1.04, n), np.minimum(o, c)/rng.uniform(1.001, 1.04, n)
    v = rng.uniform(10000, 1000000, n)
    days, day = [], date(2021, 1, 4)
    while len(days) < n:
        if day.weekday() < 5:
            days.append(day.isoformat())
        day += timedelta(days=1)
    arrays = dict(o=o, h=h, l=l, c=c, raw_c=c.copy(), v=v, t=c*v, days=np.array(days))
    extra = {key: rng.uniform(10, 100, n) for key in (
        'iv', 'hv', 'option_volume', 'call_volume', 'put_volume', 'option_open_interest',
        'call_open_interest', 'put_open_interest', 'h4_momentum', 'h4_stack', 'h4_coil', 'h4_history')}
    extra.update(earn_index=np.maximum(0, np.arange(n)//65*65), earn_days=np.arange(n)%65,
                 pot=(np.arange(n)%17 == 0).astype(float))
    q = 80*np.exp(np.cumsum(rng.normal(.0003, .01, n)))
    return arrays, q, extra


def reference_mean(x, window, function=np.mean):
    result = np.full(len(x), np.nan)
    for t in range(window-1, len(x)):
        block = x[t-window+1:t+1]
        if np.isfinite(block).all():
            result[t] = function(block)
    return result


def reference_smooth(x, window, wilder=False):
    result = np.full(len(x), np.nan)
    alpha = 1/window if wilder else 2/(window+1)
    current = np.nan
    for t, value in enumerate(x):
        if not np.isfinite(value):
            continue
        if not np.isfinite(current):
            if wilder:
                block = x[max(0, t-window+1):t+1]
                if len(block) < window or not np.isfinite(block).all():
                    continue
                current = block.mean()
            else:
                current = value
        else:
            current = (1-alpha)*current+alpha*value
        result[t] = current
    return result


class StandardIndicatorsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.a, cls.q, cls.e = synthetic()
        cls.values = lib.per_stock(cls.a, cls.q, cls.e)

    def test_each_series_ignores_every_later_bar_including_partial_weeks(self):
        for stop in (37, 100, 201, 253, 309, 310, 311, 312, 313, 359):
            short = lib.per_stock({k: v[:stop] for k, v in self.a.items()}, self.q[:stop],
                                  {k: v[:stop] for k, v in self.e.items()})
            for name, values in self.values.items():
                with self.subTest(stop=stop, name=name):
                    np.testing.assert_allclose(values[:stop], short[name], rtol=1e-8, atol=1e-8, equal_nan=True)

    def test_default_rsi_macd_bollinger_stochastic_cmf_mfi(self):
        a, value = self.a, self.values
        c, h, l, v = (a[k] for k in ('c', 'h', 'l', 'v'))
        previous = np.r_[np.nan, c[:-1]]
        up, down = np.maximum(c-previous, 0), np.maximum(previous-c, 0)
        pu, pd = reference_smooth(up, 14, True), reference_smooth(down, 14, True)
        np.testing.assert_allclose(value['rsi14'], 100*pu/(pu+pd), equal_nan=True)
        macd = reference_smooth(c, 12)-reference_smooth(c, 26)
        np.testing.assert_allclose(value['macd_hist_pct'], 100*(macd-reference_smooth(macd, 9))/c, atol=1e-11)
        mean, sd = reference_mean(c, 20), reference_mean(c, 20, np.std)
        np.testing.assert_allclose(value['bollinger_percent_b'], (c-mean+2*sd)/(4*sd), atol=1e-10, equal_nan=True)
        low, high = reference_mean(l, 14, np.min), reference_mean(h, 14, np.max)
        np.testing.assert_allclose(value['stochastic_k'], 100*(c-low)/(high-low), equal_nan=True)
        rsi = 100*pu/(pu+pd)
        rlow, rhigh = reference_mean(rsi, 14, np.min), reference_mean(rsi, 14, np.max)
        stoch_rsi = reference_mean(100*(rsi-rlow)/(rhigh-rlow), 3)
        np.testing.assert_allclose(value['stochastic_rsi'], stoch_rsi, equal_nan=True, atol=1e-9)
        money = (2*c-h-l)/(h-l)*v
        cmf = reference_mean(money, 20, np.sum)/reference_mean(v, 20, np.sum)
        np.testing.assert_allclose(value['cmf20'], cmf, equal_nan=True, atol=1e-11)
        tp = (h+l+c)/3
        prev_tp = np.r_[np.nan, tp[:-1]]
        pos = reference_mean(np.where(np.isfinite(prev_tp), np.where(tp > prev_tp, tp*v, 0), np.nan), 14, np.sum)
        neg = reference_mean(np.where(np.isfinite(prev_tp), np.where(tp < prev_tp, tp*v, 0), np.nan), 14, np.sum)
        np.testing.assert_allclose(value['mfi14'], 100*pos/(pos+neg), equal_nan=True, atol=1e-10)

    def test_supertrend10_3_matches_handwritten_recurrence(self):
        a = self.a
        h, l, c = (a[k] for k in ('h', 'l', 'c'))
        tr = np.array([h[0]-l[0]]+[max(h[i]-l[i], abs(h[i]-c[i-1]), abs(l[i]-c[i-1])) for i in range(1, len(c))])
        atr = reference_smooth(tr, 10, True)
        top, bottom = (h+l)/2+3*atr, (h+l)/2-3*atr
        line = np.full(len(c), np.nan)
        direction = -1
        for i in range(9, len(c)):
            if i > 9:
                if not (top[i] < top[i-1] or c[i-1] > top[i-1]):
                    top[i] = top[i-1]
                if not (bottom[i] > bottom[i-1] or c[i-1] < bottom[i-1]):
                    bottom[i] = bottom[i-1]
                direction = (1 if c[i] > top[i] else -1) if direction < 0 else (-1 if c[i] < bottom[i] else 1)
            line[i] = bottom[i] if direction > 0 else top[i]
        np.testing.assert_allclose(self.values['supertrend_distance'], (c-line)/atr, equal_nan=True, atol=1e-10)

    def test_aliases_have_identical_ranks_with_matching_smoothing(self):
        c = self.a['c']
        delta = c-np.r_[np.nan, c[:-1]]
        up, down = reference_smooth(np.maximum(delta, 0), 14, True), reference_smooth(np.maximum(-delta, 0), 14, True)
        cmo = 100*(up-down)/(up+down)
        k = self.values['stochastic_k']
        z = (c-reference_mean(c, 20))/reference_mean(c, 20, np.std)
        for a, b in ((self.values['rsi14'], cmo), (k, k-100), (self.values['bollinger_percent_b'], z)):
            np.testing.assert_allclose(lib.midrank(a), lib.midrank(b), equal_nan=True)
        # Unsmoothed rolling CMO is deliberately not claimed to equal Wilder RSI.
        rolling = reference_mean(np.maximum(delta, 0), 14, np.sum)-reference_mean(np.maximum(-delta, 0), 14, np.sum)
        rolling /= reference_mean(abs(delta), 14, np.sum)
        self.assertFalse(np.allclose(rolling[30:], (2*self.values['rsi14'][30:]-100)/100))

    def test_spec_exactly_matches_both_layers_without_identity_features(self):
        c = np.stack([self.a['c']*(1+i*.03) for i in range(4)])
        h, l = c*1.02, c*.98
        cross = lib.cross_section(c, h, l, block_size=2)
        names = [s['name'] for s in lib.SPEC]
        self.assertEqual(len(lib.V1_SPEC), 127)
        self.assertEqual(len(names), len(lib.V1_SPEC)+12)
        self.assertEqual(len(names), len(set(names)))
        self.assertEqual(set(names), set(self.values) | set(cross))
        self.assertFalse(set(self.values) & set(cross))
        self.assertTrue(set(lib.V1_NAMES) <= {s['name'] for s in lib.V1_SPEC})
        self.assertTrue(set(lib.LEGACY_NAMES) <= set(names))
        for s in lib.SPEC:
            self.assertRegex(s['name'], r'^[a-z][a-z0-9_]*$' if s['origin'] != 'legacy' else r'^[a-z][a-zA-Z0-9_]*$')
            self.assertFalse(any(x in s['name'] for x in ('ticker', 'code', 'date', 'listed', 'bought', 'entry')))
            self.assertTrue(s['formula'])
        tree = ast.parse(Path(lib.__file__).read_text())
        imports = [n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
        imports += [a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names]
        self.assertTrue(set(imports) <= {'datetime', 'math', 'numpy'})

    def test_missing_optional_inputs_and_calendar_stay_missing(self):
        values = lib.per_stock({k: v for k, v in self.a.items() if k != 'days'}, self.q)
        for name in ('iv_pct', 'iv_percentile252', 'iv_minus_hv', 'option_rvol20',
                     'put_call_volume_ratio', 'put_call_oi_ratio', 'option_oi_change5_pct',
                     'earn_days', 'earnings_gap_pct', 'avwap_earnings_distance_adr',
                     'weekly_rsi14', 'weekly_macd_hist_pct', 'h4_momentum', 'potent_days20'):
            self.assertTrue(np.isnan(values[name]).all(), name)

    def test_weekly_values_match_whole_weeks_and_previous_pivots(self):
        a = self.a
        ends = np.arange(4, len(a['c']), 5)
        wc = a['c'][ends]
        np.testing.assert_allclose(self.values['weekly_rsi14'][ends], lib.rsi(wc, 14), equal_nan=True)
        macd = reference_smooth(wc, 12)-reference_smooth(wc, 26)
        np.testing.assert_allclose(self.values['weekly_macd_hist_pct'][ends], 100*(macd-reference_smooth(macd, 9))/wc, atol=1e-11)
        high, low, close = a['h'][:5].max(), a['l'][:5].min(), a['c'][4]
        p = (high+low+close)/3
        expected = (a['c'][5]-(2*p-high))/(high-low)
        self.assertAlmostEqual(self.values['weekly_pivot_position'][5], expected)

    def test_weekly_warmup_starts_at_first_observed_bar(self):
        arrays = {k: v.copy() for k, v in self.a.items()}
        for key in ('o', 'h', 'l', 'c', 'v', 't'):
            arrays[key][:55] = np.nan
        values = lib.per_stock(arrays, self.q, self.e)
        ends = np.arange(4, len(arrays['c']), 5)
        np.testing.assert_allclose(values['weekly_rsi14'][ends], lib.rsi(arrays['c'][ends], 14), equal_nan=True)
        wc = arrays['c'][ends]
        macd = reference_smooth(wc, 12)-reference_smooth(wc, 26)
        np.testing.assert_allclose(values['weekly_macd_hist_pct'][ends], 100*(macd-reference_smooth(macd, 9))/wc, equal_nan=True, atol=1e-11)

    def test_volume_profile_distributes_actual_volume(self):
        h, l = np.full(100, 20.), np.full(100, 10.)
        c, v, adr = np.full(100, 15.), np.ones(100), np.ones(100)
        poc, pos = lib._volume_profile(h, l, c, v, adr)
        self.assertTrue(np.isfinite(poc[-1]+pos[-1]))
        # Compare with an independent 100 x 50 CDF integration of uniform log-price volume.
        edges = np.linspace(np.log(10), np.log(20), 51)
        mass = np.diff(np.clip((edges-np.log(10))/np.log(2), 0, 1))*100
        center = int(np.argmax(mass))
        # Floating point ties may choose neighboring bins: nonuniform fixture below is exact.
        self.assertLessEqual(abs(poc[-1]-(15/np.exp((edges[center]+edges[center+1])/2)-1)), .5)
        rng = np.random.default_rng(23)
        ll = rng.uniform(10, 12, 100)
        hh = ll+rng.uniform(.1, 3, 100)
        vv = rng.uniform(1, 100, 100)
        pp, vp = lib._volume_profile(hh, ll, c, vv, adr)
        edges = np.linspace(np.log(ll.min()), np.log(hh.max()), 51)
        cdf = np.clip((edges[None, :]-np.log(ll)[:, None])/(np.log(hh)-np.log(ll))[:, None], 0, 1)
        mass = (np.diff(cdf, axis=1)*vv[:, None]).sum(0)
        center = int(np.argmax(mass))
        lower = upper = center
        total = mass[center]
        while total < .7*mass.sum():
            if upper == 49 or (lower > 0 and mass[lower-1] >= mass[upper+1]):
                lower -= 1
                total += mass[lower]
            else:
                upper += 1
                total += mass[upper]
        self.assertAlmostEqual(pp[-1], 15/np.exp((edges[center]+edges[center+1])/2)-1)
        self.assertAlmostEqual(vp[-1], (15-np.exp(edges[lower]))/(np.exp(edges[upper+1])-np.exp(edges[lower])))

    def test_cross_section_uses_market_and_pairwise_observations(self):
        rng = np.random.default_rng(91)
        returns = rng.normal(0, .02, (5, 360))
        returns[1] = returns[0]+rng.normal(0, .001, 360)
        c = 50*np.exp(returns.cumsum(1))
        c[1, -31:-25] = np.nan
        out = lib.cross_section(c, c*1.02, c*.98, rows=[0, 1], pool_mask=np.array([True, False, False, False, False]), block_size=1)
        self.assertGreaterEqual(out['theme_peers'][0], 1)
        self.assertEqual(out['theme_peers_pool'][0], 0)
        self.assertEqual(out['theme_peers_pool'][1], 1)
        all_rows = lib.cross_section(c, c*1.02, c*.98, block_size=2)
        for name in lib.CROSS_SECTION_NAMES:
            np.testing.assert_allclose(out[name], all_rows[name][:2], equal_nan=True)
        weighted = sum(w*(c[:, -1]/c[:, -1-k]-1) for k, w in ((63,.4),(126,.2),(189,.2),(252,.2)))
        np.testing.assert_allclose(all_rows['ibd_rs_percentile'], lib.midrank(weighted))

    def test_each_prior_close_above_one_adr_can_rearm_a_retest(self):
        c = np.full(60, 100.)
        c[30:] = np.arange(105., 135.)
        h, l = c*1.001, c*.999
        e21 = lib.ema(c, 21)
        l[31:33] = e21[31:33]*.999
        arrays = dict(o=c.copy(), h=h, l=l, c=c, v=np.ones(60)*1000, t=c*1000)
        values = lib.per_stock(arrays, c)
        self.assertEqual(values['ema21_retest_count'][31], 1)
        self.assertEqual(values['ema21_retest_count'][32], 2)

    def test_candidate_selection_ignores_final_year_and_breaks_ties_as_registered(self):
        from studies.trader_replication.martin_profile_ie38 import select_candidate
        rows = {f'h{i}': dict(cv_hit=12, model=[{}]*3, test_hit=i) for i in range(1, 6)}
        self.assertEqual(select_candidate(rows), 'h1')
        rows['h5']['model'] = [{}]*2
        self.assertEqual(select_candidate(rows), 'h5')
        rows['h2']['cv_hit'] = 13
        self.assertEqual(select_candidate(rows), 'h2')
        rows['h1']['test_hit'] = 999
        self.assertEqual(select_candidate(rows), 'h2')

    def test_parallel_rank_partitions_merge_bit_for_bit_in_serial_order(self):
        from studies.trader_replication import standard_indicators_dedup as dedup
        rng = np.random.default_rng(381)
        sample = rng.normal(size=(80, len(dedup.SPECS))).astype(np.float32)
        sample[:, 1] = sample[:, 0]
        sample[:, 3] = -sample[:, 0]
        sample[rng.random(sample.shape) < .1] = np.nan
        with mock.patch.object(dedup, 'capacity', return_value={}), mock.patch.object(dedup, 'log'):
            serial = dedup.pair_correlations(sample)
            partitioned = dedup.pair_correlations(sample, 0, 38)+dedup.pair_correlations(sample, 38, len(dedup.SPECS))
        self.assertEqual(serial, partitioned)


def fitter_functions(names, namespace):
    """Load pure CLI functions without executing its real-data initialization."""
    source = Path(__file__).resolve().parents[1]/'martin_profile_ie29.py'
    tree = ast.parse(source.read_text())
    nodes = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
    namespace['np'] = np
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(source), 'exec'), namespace)
    return namespace


class ProfileV1BoundaryTest(unittest.TestCase):
    def test_holdout_values_cannot_change_training_edges_or_pool_prior(self):
        ctx = fitter_functions({'binning', 'tables_for', 'learn_groups', 'bin_table'}, dict(
            args=SimpleNamespace(train_edges=True, shrink=False, missing_zero=False, unimodal=False), ROW_HALVES=np.array(['a']*6+['b']*6),
            TRAIN_MASK=np.ones(12, bool), X=np.arange(12, dtype=float)[None, :],
            BINS={}, USE=[0], BIN_CHOICES=(3, 5, 10), SMOOTH=2., FOCUS={}, LEARN=(0,), lookup={('A', 1): 1}))
        target = [('A', 1, 'a', True)]
        before = ctx['tables_for'](target)
        edges = {key: item[1].copy() for key, item in ctx['BINS'].items()}
        ctx['X'][0, 6:] = -np.arange(6)*10000-99999
        after = ctx['tables_for'](target)
        for key in before:
            np.testing.assert_array_equal(edges[key], ctx['BINS'][key][1])
            np.testing.assert_allclose(before[key], after[key])
        np.testing.assert_array_equal(ctx['TRAIN_MASK'], np.array([True]*6+[False]*6))

    def test_learning_nights_cannot_cross_into_an_excluded_half(self):
        ctx = fitter_functions({'learn_groups'}, dict(args=SimpleNamespace(train_edges=True),
            FOCUS={}, LEARN=(0, 1, 2), lookup={('A', i): i for i in range(4)},
            TRAIN_MASK=np.array([True, True, False, False])))
        self.assertEqual(ctx['learn_groups']([('A', 1, 'a', True)]), [[1]])

    def test_bounded_rank_and_pick_path_matches_legacy_with_ties_and_empty_nights(self):
        days = [f'2021-01-{i+1:02d}' for i in range(25)]
        slices, codes, offset = {}, [], 0
        for i, day in enumerate(days):
            width = 0 if i == 9 else 7
            slices[day] = slice(offset, offset+width)
            codes.extend('ABCDEFG'[:width])
            offset += width
        pad = np.full((len(days), 7), offset, np.int32)
        row_night = np.empty(offset, np.int32)
        for i, sl in enumerate(slices.values()):
            pad[i, :sl.stop-sl.start] = np.arange(sl.start, sl.stop)
            row_night[sl] = i
        ctx = fitter_functions({'ranks_of', 'picks'}, dict(args=SimpleNamespace(train_edges=False, renew=0, cooldown=4),
            N=offset, SL=slices, CODES=codes, days=days, cpos={day: i for i, day in enumerate(days)},
            SLOTS=(), _PAD=pad, _ROW_NIGHT=row_night,
            _ROW_CODE_IDS=np.array([ord(c)-ord('A') for c in codes])))
        for seed in range(3):
            scores = np.random.default_rng(seed).integers(0, 4, offset).astype(float)
            ctx['args'].train_edges = False
            legacy_rank = ctx['ranks_of'](scores)
            legacy_picks = ctx['picks'](legacy_rank, 3, 3)
            ctx['args'].train_edges = True
            new_rank = ctx['ranks_of'](scores)
            np.testing.assert_array_equal(legacy_rank, new_rank)
            self.assertEqual(legacy_picks, ctx['picks'](new_rank, 3, 3))


if __name__ == '__main__':
    unittest.main()
