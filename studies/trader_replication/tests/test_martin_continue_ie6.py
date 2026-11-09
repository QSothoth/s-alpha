import ast
import csv
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from studies.trader_replication import martin_continue_ie6 as ie6
from studies.trader_replication.system import Rules


def synthetic_experiment():
    e = object.__new__(ie6.Experiment)
    days = np.array(['2030-01-02', '2030-01-03', '2030-01-04', '2030-01-07', '2030-01-08', '2030-01-09'])
    opening = np.array([[10.], [10.], [10.1], [10.4], [10.7], [10.8]])
    close = np.array([[10.], [10.1], [10.3], [10.6], [10.8], [10.9]])
    high = np.maximum(opening, close) + .05
    low = np.minimum(opening, close) - .05
    e.d = SimpleNamespace(days=days.tolist(), di={s: i for i, s in enumerate(days)},
                          A=dict(codes=np.array(['SYN_A']), days=days, open=opening,
                                 close=close, high=high, low=low))
    e.px = dict(dates=days, codes=e.d.A['codes'], open=opening, close=close, high=high, low=low)
    e.keys = [(s, 'SYN_A') for s in days]
    e.ci = {'SYN_A': 0}
    e.end = days[-1]
    e.raw = np.full((len(days), 1), .04)
    e.names = ['adr20']
    e.meta = dict(days=days.tolist(), entries=[], first_signal=days[0])
    return e


class IE6Tests(unittest.TestCase):
    def test_catalogue_explains_every_allowed_raw_value_and_excludes_bad_fields(self):
        specs = ie6.catalogue()
        self.assertEqual(set(specs), set(ie6.old.ie4.raw_names()) - {'raw_price', 'observed_sessions'})
        gates, starts = ie6.candidate_pool()
        self.assertEqual(len(starts['class12']), 25)
        self.assertEqual(len(starts['core5']), 5)
        for gate in gates:
            self.assertTrue(gate['meaning'] and gate['reason'])
        for name in ie6.ABSOLUTE:
            self.assertTrue(any(g['name'] == name and g['form'] == 'pct' for g in gates))

    def test_delta_marks_scope_absence_missing_and_ignores_future(self):
        days = [(date(2030, 1, 1) + timedelta(days=i)).isoformat() for i in range(12)]
        scope = {day: ['SYN_A', 'SYN_B'] for day in days}
        scope[days[0]] = ['SYN_B']
        meta = dict(days=days, scope=scope)
        keys, slices, _ = ie6.old.layout(meta)
        raw = np.arange(len(keys), dtype=np.float32)[:, None]
        values, missing = ie6.corrected_delta(raw, meta, slices)
        q = slices[days[5]].start
        self.assertTrue(missing[q, 0])
        self.assertEqual(values[q, 0], .5)
        raw[slices[days[8]].start:] *= -100
        again, missing_again = ie6.corrected_delta(raw, meta, slices)
        cut = slices[days[8]].start
        np.testing.assert_array_equal(values[:cut], again[:cut])
        np.testing.assert_array_equal(missing[:cut], missing_again[:cut])

    def test_absolute_percentiles_preserve_missing_instead_of_neutral_admission(self):
        raw = np.array([[10.], [np.nan], [20.], [100.], [200.], [300.]])
        slices = dict(a=slice(0, 3), b=slice(3, 6))
        pct = ie6.percentile_missing(raw, slices)[:, 0]
        np.testing.assert_allclose(pct, [0., np.nan, 1., 0., .5, 1.], equal_nan=True)
        gate = dict(lower=.75, upper=None)
        self.assertTrue(ie6.condition_mask(pct, gate)[1])
        self.assertFalse(ie6.condition_mask(pct, gate, False)[1])
        changed = raw.copy()
        changed[3:] *= -1
        np.testing.assert_array_equal(pct[:3], ie6.percentile_missing(changed, slices)[:3, 0])

    def test_adapter_reproduces_existing_book_and_never_uses_future_close(self):
        e = synthetic_experiment()
        day = e.d.days[0]
        selected = {day: [0]}
        direct, _ = e.book(selected)
        orders = ie6.old.selected_orders(e.d, {day: ['SYN_A']}, window=(e.d.days[1], e.end))
        official = ie6.old.hc.make_books(e.d, orders, ie6.old.hh.observations(e.d, orders), True)[0]
        rule = Rules(trail='', trims=(), risk=.005, max_gross=1., max_position=.35, intraday_kinds=('list',))
        a = ie6.account(e.d, e.px, {}, rule, direct, e.meta, end=e.end, detail=True)
        b = ie6.account(e.d, e.px, {}, rule, official, e.meta, end=e.end, detail=True)
        self.assertEqual(a['trade_digest'], b['trade_digest'])
        e.d.A['close'][1:] *= 10
        after, _ = e.book(selected)
        self.assertEqual(direct, after)
        self.assertEqual(direct[1][0][4], 9.75)

    def test_all_calendar_nights_are_selected_even_without_target_labels(self):
        e = synthetic_experiment()
        e.slices = {day: slice(k, k + 1) for k, day in enumerate(e.d.days)}
        e.order = {day: np.array([k]) for k, day in enumerate(e.d.days)}
        selected, widths, _ = e.selected(np.ones(len(e.keys), bool))
        self.assertEqual(len(selected), len(e.d.days))
        self.assertTrue(all(n == 1 for n in widths.values()))

    def test_k1_and_k2_adds_require_prior_close_then_next_open(self):
        for variant in ('K1', 'K2'):
            e = synthetic_experiment()
            book, stops = e.book({e.d.days[0]: [0]}, variant)
            rule = ie6.execution_rule(Rules(trail='', trims=(), feedback=0), variant, stops)
            result = ie6.account(e.d, e.px, {}, rule, book, e.meta, end=e.end, detail=True, stop_map=stops,
                                  entry_close_add=True)
            executions = result['trades'][0]['executions']
            adds = [r for r in executions if r['action'] == 'add']
            self.assertEqual([r['time'] for r in adds], [e.d.days[3], e.d.days[4]])
            self.assertEqual([r['price'] for r in adds], [10.4, 10.7])
            self.assertEqual(result['trades'][0]['tier'], 1.5 if variant == 'K2' else 1.)

    def test_new_execution_can_confirm_r_add_at_completed_entry_close(self):
        for variant in ('K1', 'K2', 'K3', 'K4'):
            e = synthetic_experiment()
            e.px['close'][1, 0] = 10.3
            e.px['high'][1, 0] = 10.35
            book, stops = e.book({e.d.days[0]: [0]}, variant)
            rule = ie6.execution_rule(Rules(trail='', trims=(), feedback=0), variant, stops)
            legacy = ie6.account(e.d, e.px, {}, rule, book, e.meta, end=e.end, detail=True, stop_map=stops)
            legacy_adds = [x for x in legacy['trades'][0]['executions'] if x['action'] == 'add']
            self.assertEqual(legacy_adds[0]['time'], e.d.days[3])
            result = ie6.account(e.d, e.px, {}, rule, book, e.meta, end=e.end, detail=True, stop_map=stops,
                                  entry_close_add=True, cancel_loss_add=variant in ('K3', 'K4'))
            adds = [x for x in result['trades'][0]['executions'] if x['action'] == 'add']
            self.assertEqual(adds[0]['time'], e.d.days[2])
            self.assertEqual(adds[0]['price'], e.px['open'][2, 0])
            self.assertFalse(any(x['time'] == e.d.days[1] for x in adds))
            confirmations = [x for x in result['add_orders'] if x['status'] == 'confirmed']
            self.assertEqual(confirmations[0]['signal_day'], e.d.days[1])
            e.px['low'][1, 0] = 9.7
            stopped = ie6.account(e.d, e.px, {}, rule, book, e.meta, end=e.end, detail=True, stop_map=stops,
                                  entry_close_add=True, cancel_loss_add=variant in ('K3', 'K4'))
            self.assertEqual(stopped['trades'][0]['why'], 'stop_day0')
            self.assertFalse(any(x['action'] == 'add' for x in stopped['trades'][0]['executions']))

    def test_k3_k4_stop_uses_signal_adr_and_cancel_losing_open_add_without_freeing_reservation(self):
        for variant in ('K3', 'K4'):
            e = synthetic_experiment()
            e.px['open'][3, 0] = 9.9
            e.px['high'][3, 0] = 9.95
            e.px['low'][3, 0] = 9.85
            e.px['close'][3, 0] = 9.9
            book, stops = e.book({e.d.days[0]: [0]}, variant)
            self.assertAlmostEqual(book[1][0][4], 9.8)
            e.raw[1:, 0] = .001
            self.assertEqual(book, e.book({e.d.days[0]: [0]}, variant)[0])
            rule = ie6.execution_rule(Rules(trail='', trims=(), feedback=0), variant, stops)
            result = ie6.account(e.d, e.px, {}, rule, book, e.meta, end=e.end, detail=True,
                                  stop_map=stops, cancel_loss_add=True, entry_close_add=True)
            self.assertAlmostEqual(result['trades'][0]['stop'], 9.8)
            self.assertFalse(any(r['action'] == 'add' and r['time'] == e.d.days[3]
                                 for r in result['trades'][0]['executions']))
            plans = next(p['orders'] for p in result['plans'] if p['day'] == e.d.days[3])
            cancelled = [r for r in plans if r['type'] == 'add' and r.get('cancelled_at_open')]
            self.assertEqual(len(cancelled), 1)
            self.assertEqual(cancelled[0]['status'], 'submitted')
            self.assertGreater(cancelled[0]['shares'], 0)
            self.assertFalse(ie6.audit_prices({'synthetic': result}, e.d)['errors'])

    def test_scoring_requires_both_accounts_and_ablation_cannot_hide_a_bad_year(self):
        base = {label: dict(annual={year: dict(entries=52, win=.3, return_=.1) for year in ie6.YEARS})
                for label in ('cash6', 'lever')}
        for value in base.values():
            for row in value['annual'].values():
                row['return'] = row.pop('return_')
        self.assertTrue(ie6.feasible(base, base)[0])
        other = json_copy(base)
        other['cash6']['annual'][ie6.YEARS[1]]['return'] = .099
        self.assertFalse(ie6.feasible(other, base)[0])
        before = dict(eligible=True, accounts=base, coverage=dict(primary=dict(hits={'5': 20})))
        after = dict(eligible=True, accounts=other, coverage=dict(primary=dict(hits={'5': 20})))
        self.assertFalse(ie6.removable(after, before))
        after['accounts'] = base
        after['coverage']['primary']['hits']['5'] = 19
        self.assertTrue(ie6.removable(after, before))
        after['coverage']['primary']['hits']['5'] = 18
        self.assertFalse(ie6.removable(after, before))

    def test_all_execution_variants_keep_selection_and_budget_caps(self):
        e = synthetic_experiment()
        for variant in ('K0', 'K1', 'K2', 'K3', 'K4'):
            book, stops = e.book({e.d.days[0]: [0]}, variant)
            rule = ie6.execution_rule(Rules(max_gross=2.8, max_position=.35), variant, stops)
            self.assertEqual(book[1][0][1], 0)
            self.assertEqual(rule.max_gross, 2.8)
            self.assertEqual(rule.max_position, .35)

    def test_ablation_starts_from_best_scoring_prefix_not_later_account_only_adds(self):
        def value(ids):
            returns = .2 + .1 * len(ids)
            return dict(conditions=sorted(ids), eligible=True, lever_geo=returns,
                        coverage=dict(primary=dict(hits={'5': int(0 in ids)}, n=1), halfyear={}),
                        accounts={label: dict(annual={year: dict(return_=returns, entries=52)
                                  for year in ie6.YEARS}) for label in ('cash6', 'lever')})
        def evaluate(ids):
            out = value(ids)
            for account in out['accounts'].values():
                for row in account['annual'].values():
                    row['return'] = row.pop('return_')
            return out
        fake = SimpleNamespace(label='true', gates=[dict(id=0), dict(id=1)], evaluate=evaluate)
        ie6.WORK.mkdir(exist_ok=True)
        original_read = ie6.read
        with tempfile.TemporaryDirectory(dir=ie6.WORK) as folder:
            directory = Path(folder)
            pool = directory / (ie6.PREFIX + 'candidate_pool.json')
            def read(path):
                return dict(starts=dict(empty=[])) if path == pool else original_read(path)
            with patch.object(ie6, 'WORK', directory), patch.object(ie6, 'REPORTS', directory), \
                    patch.object(ie6, 'Experiment', return_value=fake), patch.object(ie6, 'read', side_effect=read):
                ie6.search()
            result = original_read(directory / (ie6.PREFIX + 'true_empty.json'))
            self.assertEqual(result['forward_final']['conditions'], [0, 1])
            self.assertEqual(result['final']['conditions'], [0])
            self.assertEqual(result['forward_choice']['conditions'], [0])

    def test_no_human_ticker_or_entry_date_constants(self):
        with (ie6.ROOT / 'studies/martin_luk/notes/trades.csv').open() as f:
            rows = list(csv.DictReader(f))
        forbidden = {r['ticker'] for r in rows} | {'US.' + r['ticker'] for r in rows}
        forbidden |= {r['entry_date'] for r in rows if r['entry_date']}
        tree = ast.parse(Path(ie6.__file__).read_text())
        literals = {n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)}
        self.assertFalse(literals & forbidden, literals & forbidden)


def json_copy(value):
    import json
    return json.loads(json.dumps(value))


if __name__ == '__main__':
    unittest.main()
