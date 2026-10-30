import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from studies.trader_screens import aggregation as A, context
from studies.trader_screens.tests.test_focus import DAY, row, run, trader


def stock(code, **changes):
    return row(**dict(dict(code='US.' + code, industry='通讯设备'), **changes))


def panel(n=254):
    days = np.arange(np.datetime64('2026-01-01'), np.datetime64('2026-01-01') + n).astype(str)
    shape = (n, 10)
    return dict(days=days, codes=np.array(['US.' + str(i) for i in range(10)]), digest='test',
                close=np.full(shape, 10.), raw_close=np.full(shape, 10.), high=np.full(shape, 10.2),
                low=np.full(shape, 9.8), volume=np.full(shape, 100.), turnover=np.full(shape, 1e7))


class AggregationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        patcher = patch.object(A, 'ROOT', self.root)
        patcher.start()
        self.addCleanup(patcher.stop)

    def industry(self, report):
        return [g for g in A.groups(report) if any(t['dimension'] == '行业' for t in g['tags'])]

    def test_two_traders_and_two_stocks_are_both_required(self):
        for report in (run(trader('A', holdings=[stock('X'), stock('Y')])),
                       run(trader('A', holdings=[stock('X')]), trader('B', holdings=[stock('X')]))):
            self.assertEqual(A.groups(report), [])
        g, = self.industry(run(trader('A', holdings=[stock('X')]), trader('B', holdings=[stock('Y')])))
        self.assertEqual((g['trader_count'], g['stock_count']), (2, 2))
        self.assertEqual(g['labels'], ['共同持多'])

    def test_new_and_current_are_separate_and_count_people_once(self):
        r = run(trader('A', buys=[stock('X')], holdings=[stock('X', entry_day=DAY)]),
                trader('B', holdings=[stock('Y')]))
        g, = self.industry(r)
        self.assertEqual(g['trader_count'], 2)
        self.assertNotIn('共同开多', g['labels'])
        self.assertIn('新开加入老持仓', g['labels'])
        self.assertTrue(any(line.startswith('开多：A X') for line in A.lines(g)))

    def test_cover_and_partial_exits_are_never_long_entries(self):
        r = run(trader('A', sells=[stock('X', side=-1, full=False)] * 2),
                trader('B', sells=[stock('Y', side=-1)]), trader('C', holdings=[stock('Z')]))
        g, = self.industry(r)
        self.assertEqual(g['labels'], ['共同退出空头'])
        self.assertFalse(g['conflict'])
        self.assertEqual(sum(m['trader_id'] == 'A' for m in g['members']), 1)
        self.assertIn('减空：A X', A.lines(g))
        self.assertIn('平空：B Y', A.lines(g))

    def test_different_days_adds_skipped_entries_and_options_do_not_create_new_consensus(self):
        for second in (stock('Y', day='2026-10-27'), stock('Y', setup='加码'),
                       stock('Y', limit_up=True), stock('Y', option={'strike': 9})):
            self.assertEqual(self.industry(run(trader('A', buys=[stock('X')]),
                                               trader('B', buys=[second]), days=5)), [])

    def test_opposing_positions_and_exits_remain_visible(self):
        g, = self.industry(run(trader('A', holdings=[stock('X', side=-1)]),
                              trader('B', holdings=[stock('Y')]), trader('C', sells=[stock('Z')])))
        self.assertTrue(g['conflict'])
        self.assertIn('组内多空并存', g['labels'])
        self.assertIn('退出与持有并存', g['labels'])

    def test_identical_members_merge_labels_and_keep_their_evidence(self):
        cache = self.root / 'data/martin-luk-cache/concepts.json'
        cache.parent.mkdir(parents=True)
        cache.write_text(json.dumps({'US.X': ['光通信'], 'US.Y': ['光通信']}))
        groups = A.groups(run(trader('A', holdings=[stock('X')]), trader('B', holdings=[stock('Y')])))
        self.assertEqual(len(groups), 1)
        self.assertEqual({t['dimension'] for t in groups[0]['tags']}, {'行业', '概念', '入场形态'})
        self.assertEqual(len(groups[0]['members'][0]['evidence']), 3)

    def test_position_weights_are_not_added_across_accounts(self):
        for weight in (.12, .25):
            groups = A.groups(run(trader('A', holdings=[stock('X', weight=weight)]),
                                  trader('B', holdings=[stock('Y', weight=weight)])))
            tags = [t for g in groups for t in g['tags'] if t['dimension'] == '仓位']
            self.assertEqual(bool(tags), weight >= .2)

    def test_same_account_lots_sum_and_preview_examples_cover_different_traders(self):
        report = run(trader('A', holdings=[stock('X', weight=.12), stock('X', weight=.1), stock('Y')]),
                     trader('B', holdings=[stock('Z', weight=.25)]), trader('C', holdings=[stock('W')]))
        groups = A.groups(report)
        risk, = [g for g in groups if any(t['dimension'] == '仓位' for t in g['tags'])]
        self.assertEqual(risk['trader_count'], 2)
        group, = self.industry(report)
        line, = A.lines(group, limit=3)
        self.assertIn('A X', line)
        self.assertIn('B Z', line)
        self.assertIn('C W', line)
        self.assertNotIn('A Y', line)

    def test_current_metrics_do_not_describe_previous_days_entries(self):
        r = run(trader('A', buys=[stock('X', day='2026-10-27')]),
                trader('B', buys=[stock('Y', day='2026-10-27')]), days=5)
        features = dict(asof=DAY, basis='close', stocks={c: dict(metrics={'rvol20': 3}, tags=['volume_high'])
                                                       for c in ('US.X', 'US.Y')}, background={
            'volume_high': dict(dimension='量能', label='放量', definition='test', matched=2, valid=10)})
        A.attach(r, features)
        self.assertFalse(any(t['dimension'] == '量能' for g in A.groups(r) for t in g['tags']))

    def test_unknown_and_empty_concepts_are_distinguished_without_guessing(self):
        cache = self.root / 'data/martin-luk-cache/concepts.json'
        cache.parent.mkdir(parents=True)
        cache.write_text(json.dumps({'US.X': []}))
        r = run(trader('A', holdings=[stock('X', industry='')]), trader('B', holdings=[stock('Y', industry='')]))
        c = A.attach(r)
        self.assertEqual(c['coverage'], dict(total=2, industry=0, concepts=0, concepts_known=1))
        self.assertFalse(any(t['dimension'] in ('行业', '概念') for g in A.groups(r) for t in g['tags']))

    def test_legacy_intraday_never_loads_completed_daily_data(self):
        r = run(trader('A', holdings=[stock('X')]))
        r.update(provisional={'now': DAY + 'T10:30:00'}, mode='live', digest='test')
        with patch('studies.trader_data.dataset', side_effect=AssertionError('must not read later daily bars')):
            context.enrich_cached(r)
        self.assertEqual(r['presentation']['aggregation']['basis'], 'unavailable')

    def test_legacy_daily_does_not_reconstruct_from_changed_data(self):
        r = run(trader('A', holdings=[stock('X')]))
        r.update(mode='live', digest='original')
        with patch('studies.trader_data.dataset', return_value=SimpleNamespace(digest=lambda: 'changed')), \
                patch('studies.trader_data.panel.build', side_effect=AssertionError('source digest mismatch')):
            context.enrich_cached(r)
        self.assertEqual(r['presentation']['aggregation']['basis'], 'unavailable')


class FeatureTests(unittest.TestCase):
    def test_volume_baseline_excludes_today_and_reports_valid_market_population(self):
        p = panel()
        p['volume'][-1, 0] = 1000
        p['volume'][-2, 1] = np.nan
        c = context.market_features(p, 'us')
        self.assertEqual(c['stocks']['US.0']['metrics']['rvol20'], 10)
        self.assertNotIn('rvol20', c['stocks']['US.1']['metrics'])
        self.assertEqual((c['background']['volume_high']['matched'], c['background']['volume_high']['valid']), (1, 9))

    def test_partial_volume_is_cumulative_not_projected_or_low_volume(self):
        p = panel()
        p['volume'][-1, 0], p['volume'][-1, 1] = 20, 200
        c = context.market_features(p, 'us', partial=True)
        self.assertEqual(c['stocks']['US.0']['metrics']['rvol20'], .2)
        self.assertNotIn('volume_low', c['stocks']['US.0']['tags'])
        self.assertIn('volume_partial', c['stocks']['US.1']['tags'])
        self.assertNotIn('volume_high', c['background'])

    def test_high_requires_full_history_and_flat_market_is_not_all_strong(self):
        c = context.market_features(panel(n=252), 'us')
        self.assertEqual(c['background']['near_high']['valid'], 0)
        self.assertEqual(c['background']['strong']['matched'], 0)
        self.assertEqual(c['background']['weak']['matched'], 0)
        c = context.market_features(panel(), 'us')
        self.assertEqual(c['background']['near_high']['matched'], 10)

    def test_no_quote_is_not_a_price_or_volume_signal_and_ranks_have_a_population(self):
        p = panel()
        p['close'][-1] = np.arange(5., 15.)
        p['volume'][-1, 9] = 0
        c = context.market_features(p, 'us')
        self.assertNotIn('US.9', c['stocks'])
        self.assertEqual(c['background']['strong']['valid'], 9)
        self.assertEqual(c['background']['strong']['matched'], 2)
        self.assertEqual(c['pool']['eligible'], 9)


if __name__ == '__main__':
    unittest.main()
