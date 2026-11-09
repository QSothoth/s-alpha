import ast
from copy import deepcopy
import csv
from datetime import date, timedelta
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import warnings

import numpy as np

from studies.trader_replication import martin_continue_ie23 as m


def stock_data(n=360):
    days, current = [], date(2001, 1, 1)
    while len(days) < n:
        if current.weekday() < 5 and not (len(days) == 133 and current.weekday() == 4):
            days.append(current.isoformat())
        current += timedelta(days=1)
    t = np.arange(n, dtype=float)
    close = 50 + t / 50 + 4 * np.sin(t / 7) + np.sin(t / 3)
    arrays = dict(o=close * (1 + .01 * np.sin(t)), c=close, h=close * 1.035,
                  l=close * .96, v=1000 + 200 * np.cos(t / 5), t=close * (1000 + 200 * np.cos(t / 5)))
    extras = {key: 1 + t / 1000 for key in ('iv', 'hv', 'option_volume', 'call_volume', 'put_volume',
              'option_open_interest', 'call_open_interest', 'put_open_interest', 'peer_g5', 'peer_rank')}
    extras.update(earn_index=np.maximum(0, (t // 60 * 60).astype(int)), earn_days=t % 60, pot=(t % 11 == 0).astype(float))
    for name in ('activity', 'momentum', 'history', 'stack', 'peers', 'coil'):
        extras['h4_' + name] = (t % 17) / 16
    for s in m.lib.inventory():
        if s.family == 'group':
            extras[f'group.{s.metric}.{s.parameter}'] = np.sin(t / max(1, s.parameter))
    return days, arrays, extras, 100 + t / 20


def all_values(days, arrays, extras, benchmark):
    stock = m.CausalStock(arrays, days, benchmark, extras)
    out = {}
    specs = m.lib.inventory()
    with warnings.catch_warnings():
        warnings.simplefilter('ignore', RuntimeWarning)
        for family, parameter in dict.fromkeys((s.family, s.parameter) for s in specs):
            subset = [s for s in specs if s.family == family and s.parameter == parameter]
            values = m.ie9.old.indicator_values(stock, family, parameter, {s.metric for s in subset})
            out.update({s.name: values[s.metric] for s in subset})
    stock.ema.cache_clear()
    stock.f_hilbert.cache_clear()
    return out


def synthetic_data():
    d = m.Data.__new__(m.Data)
    d.specs = [dict(name='factor' + str(k), length=k + 1) for k in range(6)]
    d.specs += [dict(name=name, length=20) for name in m.ANCHORS]
    d.library_n = 6
    d.name_index = {r['name']: k for k, r in enumerate(d.specs)}
    d.slices, d.days, d.codes, entries, query = {}, [], [], [], []
    for h in m.HALVES:
        night_rows = []
        for night in range(4):
            day = h[:4] + ('-02-' if h.endswith('1') else '-08-') + str(night + 1).zfill(2)
            start = len(d.days)
            d.slices[day] = slice(start, start + 20)
            d.days.extend([day] * 20)
            d.codes.extend(['asset_' + str(k) for k in range(20)])
            night_rows.append(start)
        for k in range(3):
            entries.append(dict(id=h + '_' + str(k), code='asset_' + str(k + 8),
                                entry_date=day, primary=True, nights=list(d.slices)[-4:]))
            query.append([start + k + 8 for start in night_rows])
    d.entries, d.query = entries, np.asarray(query)
    d.n = len(d.days)
    d.row_half = np.asarray([m.ie7.half(day) for day in d.days])
    d.entry_half = np.asarray([m.ie7.half(e['entry_date']) for e in entries])
    d.primary = np.ones(len(entries), bool)
    rng = np.random.default_rng(42)
    d.x = rng.random((8, d.n)).astype(np.float32)
    d.x[0, d.query.ravel()] = .99
    d.baseline_values = np.zeros((d.n, len(m.ie9.NAMES)), np.float32)
    d.baseline_values[:, m.ie9.NAMES.index('near_ema9')] = d.x[-1]
    d.baseline_score = d.x[-1].copy()
    d.baseline_ranks = d.rank(d.baseline_score)
    return d


class IE23Tests(unittest.TestCase):
    def test_duplicate_member_rechecks_a_later_better_representative(self):
        rng = np.random.default_rng(1)
        first, noise, later_noise = rng.normal(size=(3, 10000))
        member = .74 * first + np.sqrt(1 - .74 ** 2) * noise
        later = .95 * member + np.sqrt(1 - .95 ** 2) * later_noise
        d = m.Data.__new__(m.Data)
        d.library_n = 4
        d.x = np.asarray([first, member, later, member], np.float32)
        d.row_half = np.full(10000, 'synthetic')
        d.specs = [dict(name='factor' + str(i), length=i + 1) for i in range(4)]
        ranks = np.asarray([m.percentiles(row)[:, 0] for row in d.x])
        correlation = np.corrcoef(ranks)
        self.assertGreater(correlation[0, 1], .7)
        self.assertLess(correlation[0, 2], .7)
        self.assertGreater(correlation[1, 2], correlation[0, 1])
        with tempfile.TemporaryDirectory() as folder, patch.object(m, 'REPORTS', Path(folder)):
            result = m.group_factors(d, ['synthetic'])
        membership = {j: g['representative'] for g in result['groups'] for j in g['members']}
        self.assertEqual(membership[1], 0)
        self.assertEqual(membership[3], 2)

    def test_all_1847_specs_are_prefix_causal_and_ignore_future_perturbations(self):
        days, arrays, extras, benchmark = stock_data()
        arrays['c'][119] = np.nan
        arrays['v'][173] = np.nan
        full = all_values(days, arrays, extras, benchmark)
        self.assertEqual(len(full), 1847)
        stop = 234
        short = all_values(days[:stop], {k: v[:stop] for k, v in arrays.items()},
                           {k: v[:stop] for k, v in extras.items()}, benchmark[:stop])
        changed = {k: v.copy() for k, v in arrays.items()}
        for value in changed.values():
            value[stop:] *= 7
        altered = all_values(days, changed, extras, benchmark)
        for name in full:
            np.testing.assert_allclose(full[name][:stop], short[name], atol=1e-7, rtol=1e-7, equal_nan=True, err_msg=name)
            np.testing.assert_allclose(full[name][:stop], altered[name][:stop], atol=1e-7, rtol=1e-7, equal_nan=True, err_msg=name)
        x = np.column_stack(list(full.values()))
        xs = np.column_stack(list(short.values()))
        np.testing.assert_array_equal(m.lib.history_rank(x, np.arange(stop - 5, stop)),
                                      m.lib.history_rank(xs, np.arange(stop - 5, stop)))

    def test_nightly_transform_handles_ties_missing_and_singletons(self):
        a = m.percentiles(np.array([[1., np.nan], [1., np.nan], [3., 8.]]))
        np.testing.assert_array_equal(a[:, 0], [.25, .25, 1.])
        self.assertTrue(np.isnan(a[:2, 1]).all())
        self.assertEqual(a[2, 1], .5)
        np.testing.assert_array_equal(m.percentiles([7., 7.])[:, 0], [.5, .5])

    def test_holiday_week_is_not_confirmed_using_a_future_session(self):
        days, arrays, extras, benchmark = stock_data(30)
        removed = next(i for i, day in enumerate(days) if i > 5 and date.fromisoformat(day).weekday() == 4)
        keep = np.arange(len(days)) != removed
        days = [day for i, day in enumerate(days) if keep[i]]
        arrays = {k: v[keep] for k, v in arrays.items()}
        extras = {k: v[keep] for k, v in extras.items()}
        benchmark = benchmark[keep]
        full = m.CausalStock(arrays, days, benchmark, extras)
        last, _, _, close = full.weekly()
        expanded = full.expand_week(last, close)
        stop = removed
        short = m.CausalStock({k: v[:stop] for k, v in arrays.items()}, days[:stop], benchmark[:stop],
                              {k: v[:stop] for k, v in extras.items()})
        short_last, _, _, short_close = short.weekly()
        np.testing.assert_array_equal(expanded[:stop], short.expand_week(short_last, short_close))
        self.assertIn(removed, last.tolist())

    def test_full_selection_and_inner_ablation_do_not_read_held_labels(self):
        d = synthetic_data()
        held = m.HALVES[-1]
        halves = list(m.HALVES[:-1])
        groups = dict(groups=[dict(representative=j) for j in range(d.library_n)])
        original = m.select(d, halves, d.query, groups)
        changed = d.query.copy()
        changed[d.entry_half == held] = -1
        second = m.select(d, halves, changed, groups)
        self.assertEqual(m.clean(original), m.clean(second))
        class ProtectedQuery:
            def __getitem__(self, selector):
                indices = np.arange(len(d.entries))[selector]
                if np.any(d.entry_half[indices] == held):
                    raise AssertionError('held labels read during training')
                return d.query[selector]
        protected = m.select(d, halves, ProtectedQuery(), groups)
        self.assertEqual(m.clean(original), m.clean(protected))

    def test_baseline_ablation_preserves_original_event_amplitude(self):
        d = synthetic_data()
        j = m.ie9.NAMES.index('after_inside')
        d.baseline_values[:3, j] = [1., 0., 1.]
        d.x[-2, :3] = [.6, .2, .6]
        term = dict(j=d.name_index[m.ANCHORS[0]], form='raw', direction=1)
        model = dict(terms=[term])
        ranks = d.predict(model)
        self.assertEqual(ranks[0], 1)
        self.assertEqual(ranks[2], 2)
        self.assertEqual(m.refit(d, model, list(m.HALVES), d.query), model)

    def test_shuffling_is_shared_and_preserves_outside_pool(self):
        d = synthetic_data()
        q = d.query.copy()
        q[0, 0] = -1
        q[1, 0] = q[2, 0]
        shuffled = d.shuffled(17, q)
        self.assertEqual(shuffled[0, 0], -1)
        self.assertEqual(shuffled[1, 0], shuffled[2, 0])
        for row, original in zip(shuffled, q):
            for a, b in zip(row, original):
                if a >= 0:
                    self.assertEqual(d.days[a], d.days[b])

    def test_candidate_budget_and_fewer_factor_tiebreak(self):
        d = synthetic_data()
        desc = m.describe(d, list(m.HALVES), d.query)
        groups = dict(groups=[dict(representative=j) for j in range(d.library_n)])
        rows = m.candidates(d, desc, groups)
        for round_number in range(1, 5):
            self.assertLessEqual(sum(r['id'].startswith('R' + str(round_number)) for r in rows), 5)
        self.assertTrue(all(len(r['terms']) <= 5 for r in rows))
        a = dict(coverage=dict(primary=dict(hits={'5': 5}), all_entries=dict(hits={'5': 6})),
                 model=dict(terms=[1, 2]), order=0)
        b = deepcopy(a)
        b['model']['terms'].pop()
        b['order'] = 1
        self.assertGreater(m.candidate_key(b), m.candidate_key(a))

    def test_source_has_no_human_security_or_entry_date_literals(self):
        source = Path(m.__file__).read_text()
        constants = {node.value for node in ast.walk(ast.parse(source))
                     if isinstance(node, ast.Constant) and isinstance(node.value, str)}
        with (m.ROOT / 'studies/martin_luk/notes/trades.csv').open() as stream:
            rows = list(csv.DictReader(stream))
        forbidden = {r['ticker'] for r in rows} | {'US.' + r['ticker'] for r in rows}
        forbidden |= {r['entry_date'] for r in rows if r['entry_date']}
        self.assertFalse(constants & forbidden)


if __name__ == '__main__':
    unittest.main()
