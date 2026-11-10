"""WF00 decisions and data boundaries, using synthetic fixtures except replay tests."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from studies.trader_replication import datasets, funnel, pipeline, regime
from studies.trader_replication.config import Config


def config():
    return dict(selection_years=['2024', '2025'], reference_accounts=['master', 'M3B'],
        hard_lines=dict(annual_return_min=0., behaviour_tolerance=.2),
        accept=dict(selection=dict(min_extra_legs=3, max_unlimited_mean_new_names=5., max_unique_growth=.2),
            trading=dict(min_extra_legs=3), conversion=dict(min_extra_legs=3), merge=dict(min_extra_legs=3),
            regime=dict(min_agreement=.9)),
        checkpoint=dict(default_rounds=3, no_progress_rounds=2, review_failures=2))


def metrics(n=4):
    return dict(annual={y: dict(covered=n, peak_held=n, unlimited_mean_new_names=4., unique_names=100,
                              **{'return': .1}) for y in ('2024', '2025')},
        selection=dict(his_mean_r=1., control_pnl=.1, behaviour_within=2, peak_weight_median=.3),
        uses_bar_turnover_selection=False)


class Decisions(unittest.TestCase):
    def test_missing_master_g1_is_unverified(self):
        from studies.martin_luk.workflow import bootstrap
        with tempfile.TemporaryDirectory() as directory, patch.object(bootstrap, 'OUT', Path(directory)):
            self.assertEqual(bootstrap.master_g1()['status'], 'unverified')
            path = Path(directory)/'G1_master.json'
            path.write_text('{"status": "pass"}')
            self.assertEqual(bootstrap.master_g1()['status'], 'unverified')
            checks = {key: {'ok': True} for key in ('data', 'fills', 'lookahead', 'win_rate')}
            result = pipeline.g1(checks, code_sha='code', data_sha='data', is_reference=True)
            path.write_text(json.dumps(result))
            self.assertEqual(bootstrap.master_g1(), result)

    def test_history_design_view_keeps_only_identifiable_selection_year_cells(self):
        from studies.martin_luk.workflow.history import selection_excerpts, design_text
        source = '| 系统 | 2024收益 | 2025收益 | 2026收益 |\n|---|---|---|---|\n| A | +10% | +20% | -99% |'
        values, returns = selection_excerpts(source)
        self.assertTrue(returns)
        self.assertIn('+10%', str(values))
        self.assertIn('+20%', str(values))
        self.assertNotIn('-99%', str(values))
        self.assertNotIn('2026', str(values))
        self.assertEqual(design_text(['全段收益70%，2026亏损。没有候选通过。']), ['没有候选通过。'])

    def test_selection_accepts_three_segments_without_annual_decline(self):
        ref, trial, cfg = metrics(), metrics(6), config()
        self.assertEqual(pipeline.accept('selection', trial, ref, cfg)['status'], 'accepted')
        trial['annual']['2024']['covered'] = 3
        self.assertEqual(pipeline.accept('selection', trial, ref, cfg)['status'], 'branch')

    def test_width_and_unique_names_are_independent_guards(self):
        ref, trial = metrics(), metrics(6)
        for key, value in (('unlimited_mean_new_names', 5.1), ('unique_names', 121)):
            bad = deepcopy(trial)
            bad['annual']['2024'][key] = value
            self.assertEqual(pipeline.accept('selection', bad, ref, config())['status'], 'branch')

    def test_thresholds_come_from_config(self):
        cfg = config()
        cfg['accept']['selection']['min_extra_legs'] = 5
        self.assertEqual(pipeline.accept('selection', metrics(6), metrics(), cfg)['status'], 'branch')

    def test_trading_guards_r_control_and_behaviour(self):
        ref, trial = metrics(), metrics(6)
        self.assertEqual(pipeline.accept('trading', trial, ref, config())['status'], 'accepted')
        for key in ('his_mean_r', 'control_pnl', 'behaviour_within'):
            bad = deepcopy(trial)
            bad['selection'][key] = 0
            self.assertEqual(pipeline.accept('trading', bad, ref, config())['status'], 'branch')

    def test_conversion_requires_both_profitable_selection_years(self):
        trial = metrics(6)
        trial['annual']['2025']['return'] = -.01
        self.assertEqual(pipeline.accept('conversion', trial, metrics(), config())['status'], 'branch')

    def test_merge_requires_position_weight_and_separate_stock_selection(self):
        trial = metrics(6)
        self.assertEqual(pipeline.accept('merge', trial, metrics(), config())['status'], 'accepted')
        trial['selection']['peak_weight_median'] = .2
        self.assertEqual(pipeline.accept('merge', trial, metrics(), config())['status'], 'branch')
        trial['selection']['peak_weight_median'] = .3
        trial['uses_bar_turnover_selection'] = True
        self.assertEqual(pipeline.accept('merge', trial, metrics(), config())['status'], 'branch')

    def test_merge_fidelity_accepts_closer_returns_without_extra_segments(self):
        cfg = config()
        cfg['accept']['merge'].update(fidelity_min_log_gap_gain=.1, fidelity_max_year_gap_loss=.1)
        cfg['behaviour_card'] = {'2024': {'return': 2.}, '2025': {'return': 9.}}
        ref, trial = metrics(), metrics()
        trial['annual']['2025']['return'] = .5
        result = pipeline.accept('merge', trial, ref, cfg)
        self.assertEqual((result['status'], result['mode']), ('accepted', 'fidelity'))
        self.assertEqual(pipeline.accept('merge', metrics(6), ref, cfg)['mode'], 'standard')
        fewer = deepcopy(trial)
        fewer['annual']['2024']['peak_held'] = 3
        self.assertEqual(pipeline.accept('merge', fewer, ref, cfg)['status'], 'branch')
        small = deepcopy(trial)
        small['annual']['2025']['return'] = .15
        self.assertEqual(pipeline.accept('merge', small, ref, cfg)['status'], 'branch')
        higher_2024 = metrics()
        higher_2024['annual']['2024']['return'] = .3  # trial's 2024 gap widens by log(1.3/1.1) > 0.1
        self.assertEqual(pipeline.accept('merge', trial, higher_2024, cfg)['status'], 'branch')
        no_card = config()
        no_card['accept']['merge'].update(fidelity_min_log_gap_gain=.1, fidelity_max_year_gap_loss=.1)
        self.assertEqual(pipeline.accept('merge', trial, ref, no_card)['status'], 'branch')
        self.assertEqual(pipeline.accept('merge', trial, ref, config())['status'], 'branch')

    def test_holdout_cannot_change_acceptance_and_missing_facts_do_not_pass(self):
        a, b = metrics(6), metrics()
        a['annual']['2026'] = dict(covered=-100, **{'return': -.99})
        self.assertEqual(pipeline.accept('selection', a, b, config())['status'], 'accepted')
        a['annual'].pop('2024')
        self.assertEqual(pipeline.accept('selection', a, b, config())['status'], 'branch')

    def test_freeze_requires_every_reference_and_year(self):
        split = {n: {y: dict(up=.2, weak=.1) for y in ('2024', '2025')} for n in ('master', 'M3B')}
        stable = dict(minimum=.91, lookahead_ok=True)
        self.assertEqual(pipeline.freeze_switch(stable, split, config())['status'], 'frozen')
        split['M3B']['2025']['weak'] = .3
        self.assertEqual(pipeline.freeze_switch(stable, split, config())['status'], 'candidate')
        stable['minimum'] = .89
        self.assertEqual(pipeline.freeze_switch(stable, split, config())['status'], 'candidate')

    def test_checkpoint_stops_and_requires_merge_after_acceptance(self):
        hist = [dict(cell='selection/common', progress=False, status='branch')]*2
        self.assertTrue(pipeline.checkpoint(hist, dict(cell='selection/common'), config())['stop'])
        hist = [dict(status='accepted')]
        self.assertTrue(pipeline.checkpoint(hist, {}, config())['pending_merge'])
        for facts in (dict(rule_drift=True), dict(fixed_card_failed=True), dict(holdout_return=-.1),
                      dict(rounds_in_run=4), dict(review_failures=2), dict(success=True)):
            self.assertTrue(pipeline.checkpoint([], facts, config())['stop'])
        self.assertTrue(pipeline.checkpoint([dict(cell='x', progress=False)],
            dict(cell='x', progress=False, id='latest'), config())['stop'])
        self.assertFalse(pipeline.checkpoint([dict(cell='x', progress=False)]*2,
            dict(cell='x', progress=True, status='accepted', line='selection', rounds_in_run=2), config())['stop'])
        self.assertFalse(pipeline.checkpoint([], dict(status='accepted', line='merge'), config())['pending_merge'])

    def test_only_g0_g1_block_new_downstream_work(self):
        evidence = {k: pipeline.result('pass', 'ok') for k in pipeline.ALLOWED}
        for k in ('G2', 'G3', 'G4'):
            evidence[k] = pipeline.result('fail', 'missing')
        self.assertEqual(pipeline.allowed_actions(evidence)['gate'], 'G4')
        self.assertEqual(pipeline.allowed_actions(evidence, legacy=True)['gate'], 'G2')
        evidence['G1'] = pipeline.result('fail', 'bad data')
        self.assertEqual(pipeline.allowed_actions(evidence)['gate'], 'G1')


class StateConfig(unittest.TestCase):
    def test_common_resolves_and_corrections_require_frozen_regime(self):
        value = dict(trade=dict(common=dict(risk=.01, rule_opts=dict(trims=[3, 5])),
                                by_state=dict(weak=dict(risk=.005))))
        with self.assertRaises(ValueError):
            Config(value)
        cfg = Config(value, regime_frozen=True)
        self.assertEqual(cfg['risk'], .01)
        self.assertEqual(cfg.for_state('weak')['risk'], .005)
        self.assertEqual(cfg.for_state('weak').for_state('up')['risk'], .01)

    def test_cannot_hide_more_than_two_corrections_in_nested_rules(self):
        value = dict(trade=dict(common={}, by_state=dict(up=dict(rule_opts=dict(a=1, b=2, c=3)))))
        with self.assertRaises(ValueError):
            Config(value, regime_frozen=True)
        with self.assertRaises(ValueError):
            Config(dict(trade=dict(common={}, by_state=dict(unknown=dict(risk=1)))), regime_frozen=True)
        with self.assertRaises(ValueError):
            Config(dict(universe=dict(common={}, by_state=dict(up=dict(a=1, b=2))),
                        signal=dict(common={}, by_state=dict(up=dict(c=3)))), regime_frozen=True)

    def test_flat_aliases_and_empty_common_wrappers_match(self):
        flat = dict(risk=.005, max_new=4, pool='U0', rule_opts=dict(trail='e21'))
        cfg = Config(flat)
        wrapped = {k: dict(common=dict(cfg[k]), by_state={}) for k in cfg}
        self.assertEqual(Config(wrapped).flat(), flat)
        old = dict(common=dict(trail='e9'), risk=.005)
        self.assertEqual(Config(Config(old)).flat(), old)


class DatasetBoundary(unittest.TestCase):
    def fixture(self, directory):
        root = Path(directory)
        path = root/'frozen'
        path.mkdir(parents=True)
        bars = path/'bars.csv'
        bars.write_text('code,date,close\nUS.A,2024-01-01,10.5\n')
        (path/'CHECKSUMS.sha256').write_text(datasets.sha(bars)+'  bars.csv\n')
        return dict(root=str(root), datasets=dict(approved_by_user=None, items=[dict(name='frozen',
            path=str(path.relative_to(root)), checksums_sha256=datasets.sha(path/'CHECKSUMS.sha256'),
            schema=datasets.inventory(path))])), path

    def test_original_matches_but_unapproved_does_not_start_round(self):
        with tempfile.TemporaryDirectory() as d:
            cfg, _ = self.fixture(d)
            result = datasets.check(cfg)
            self.assertTrue(result['ok'])
            self.assertFalse(result['can_start_round'])

    def test_one_byte_change_is_blocked(self):
        with tempfile.TemporaryDirectory() as d:
            cfg, path = self.fixture(d)
            p = path/'bars.csv'
            p.write_text(p.read_text().replace('10.5', '11.5'))
            self.assertFalse(datasets.check(cfg)['ok'])

    def test_removed_column_is_blocked_even_after_local_checksums_are_replaced(self):
        with tempfile.TemporaryDirectory() as d:
            cfg, path = self.fixture(d)
            p = path/'bars.csv'
            p.write_text('code,date\nUS.A,2024-01-01\n')
            (path/'CHECKSUMS.sha256').write_text(datasets.sha(p)+'  bars.csv\n')
            result = datasets.check(cfg)
            self.assertFalse(result['ok'])
            self.assertTrue(any('schema' in e for e in result['errors']))

    def test_extra_file_is_blocked(self):
        with tempfile.TemporaryDirectory() as d:
            cfg, path = self.fixture(d)
            (path/'extra.csv').write_text('close\n1\n')
            self.assertFalse(datasets.check(cfg)['ok'])

    def test_unregistered_path_and_cache_prefix_spoof_are_blocked(self):
        with tempfile.TemporaryDirectory() as d:
            cfg, _ = self.fixture(d)
            source = Path(d)/'source.py'
            source.write_text("p = '"+'data'+'/rogue/bars.csv' + "'\n")
            self.assertFalse(datasets.scan(cfg, [source])['ok'])
            cfg['datasets']['derived_caches'] = [dict(path='data'+'/cache', producer='studies.trader_data.panel')]
            source.write_text("p = '"+'data'+'/cache2/bars.csv' + "'\n")
            self.assertFalse(datasets.scan(cfg, [source])['ok'])
            source.write_text("p = '"+'data'+'/cache/bars.csv' + "'\n")
            self.assertTrue(datasets.scan(cfg, [source])['ok'])
            source.write_text("p = 'trader-"+'data'+'/cache/bars.csv' + "'\n")
            self.assertTrue(datasets.scan(cfg, [source])['ok'])


class FrozenCache(unittest.TestCase):
    def test_selection_source_comes_from_registered_version(self):
        from studies.martin_luk.workflow import frozen_cache
        cfg = {'systems': {'old': {'picks': 'picks/IE9.json'},
                           'execution_a': {'picks': 'picks/IE47.json'},
                           'execution_b': {'picks': 'picks/IE47.json'}}}
        self.assertEqual(frozen_cache.selection_source(cfg, 'IE47'), frozen_cache.ROOT/'picks/IE47.json')
        with self.assertRaises(ValueError):
            frozen_cache.selection_source(cfg, 'missing')
        cfg['systems']['other'] = {'picks': 'elsewhere/IE47.json'}
        with self.assertRaises(ValueError):
            frozen_cache.selection_source(cfg, 'IE47')

    def test_bench_rejects_a_different_selection_version(self):
        from unittest.mock import patch
        from studies.martin_luk.workflow import frozen_cache
        state = {'components': {'selection': {'version': 'IE47'}, 'trading': {'version': 'master'}}}
        files = {'inputs.json': {'selection_version': 'IE9'}, 'account.json': {}}
        with patch.object(frozen_cache.D, 'read', return_value=state), patch.object(frozen_cache, 'load', return_value=files):
            with self.assertRaisesRegex(ValueError, 'different frozen selection'):
                frozen_cache.bench_score()

    def test_refresh_manifest_preserves_and_verifies_payload(self):
        from unittest.mock import patch
        from studies.martin_luk.workflow import frozen_cache
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            flow = root/'workflow'
            folder = flow/'frozen/regime/example'
            folder.mkdir(parents=True)
            payload = folder/'states.json'
            payload.write_bytes(b'{"states": [1, 2]}\n')
            manifest = {'line': 'regime', 'version': 'example', 'sources': {},
                        'files': {'states.json': hashlib.sha256(payload.read_bytes()).hexdigest()}}
            (folder/'manifest.json').write_text(json.dumps(manifest))
            with patch.object(frozen_cache, 'ROOT', root), patch.object(frozen_cache, 'FLOW', flow), \
                 patch.object(frozen_cache, 'FROZEN', flow/'frozen'), \
                 patch.object(frozen_cache, 'identity', return_value=({'code': 'new'}, 'data')):
                frozen_cache.refresh_manifest('regime', 'example')
                self.assertEqual(payload.read_bytes(), b'{"states": [1, 2]}\n')
                self.assertEqual(json.loads((folder/'manifest.json').read_text())['code_fingerprints'], {'code': 'new'})
                payload.write_bytes(b'corrupted')
                with self.assertRaisesRegex(ValueError, 'content mismatch'):
                    frozen_cache.refresh_manifest('regime', 'example')

    def test_manifest_must_match_state_fingerprint(self):
        from unittest.mock import patch
        from studies.martin_luk.workflow import frozen_cache
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            folder = root/'selection'/'IE9'
            folder.mkdir(parents=True)
            (folder/'data.json').write_text('{"picks": []}')
            manifest = dict(line='selection', version='IE9', code_fingerprints={'code': 'a'},
                data_fingerprint='b', files={'data.json': hashlib.sha256((folder/'data.json').read_bytes()).hexdigest()})
            path = folder/'manifest.json'
            path.write_text(json.dumps(manifest))
            state = {'frozen_caches': {'selection': {'IE9': {'manifest_sha256': hashlib.sha256(path.read_bytes()).hexdigest()}}}}
            with patch.object(frozen_cache, 'FROZEN', root), patch.object(frozen_cache, 'identity', return_value=({'code': 'a'}, 'b')), patch.object(frozen_cache.D, 'read', return_value=state):
                self.assertEqual(frozen_cache.load('selection', 'IE9')['data.json']['picks'], [])
                path.write_text(path.read_text()+' ')
                with self.assertRaises(ValueError):
                    frozen_cache.load('selection', 'IE9')

    def test_approval_does_not_change_pinned_data_identity(self):
        from unittest.mock import patch
        from studies.martin_luk.workflow import frozen_cache
        cfg = {'datasets': {'approved_by_user': None, 'items': [{'sha256': 'data-a'}]}}
        with patch.object(frozen_cache.D, 'read', return_value=cfg):
            original = frozen_cache.identity()[1]
            cfg['datasets']['approved_by_user'] = '2026-11-09'
            self.assertEqual(frozen_cache.identity()[1], original)
            cfg['datasets']['items'][0]['sha256'] = 'data-b'
            self.assertNotEqual(frozen_cache.identity()[1], original)

    def test_identity_and_payload_must_match(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            payload = folder/'data.json'
            payload.write_text('{"nights": [["A"], []]}')
            manifest = dict(line='selection', version='IE9', code_fingerprints={'signal.py': 'abc'},
                data_fingerprint='dataset-sha', files={'data.json': hashlib.sha256(payload.read_bytes()).hexdigest()})
            (folder/'manifest.json').write_text(json.dumps(manifest))
            read = lambda version, code, data: funnel.load_frozen(folder, version, code, data)
            self.assertEqual(read('IE9', {'signal.py': 'abc'}, 'dataset-sha')['data.json']['nights'], [['A'], []])
            for version, code, data in [('IE47', {'signal.py': 'abc'}, 'dataset-sha'),
                                        ('IE9', {'signal.py': 'changed'}, 'dataset-sha'),
                                        ('IE9', {'signal.py': 'abc'}, 'changed')]:
                with self.assertRaises(ValueError):
                    read(version, code, data)
            with self.assertRaises(ValueError):
                funnel.load_frozen(folder, 'IE9', {'signal.py': 'abc'}, 'dataset-sha', line='trading')
            payload.write_text('{"nights": []}')
            with self.assertRaises(ValueError):
                read('IE9', {'signal.py': 'abc'}, 'dataset-sha')


class BenchBoundary(unittest.TestCase):
    def test_pool_failure_precedes_nominations_and_layers_partition_segments(self):
        from studies.trader_replication.system import Rules
        days = ['2024-01-0'+str(i+1) for i in range(5)]
        prices = np.full((5, 1), 10.)
        A = dict(days=days, codes=['A'], open=prices, high=prices, low=prices, close=prices)
        g = dict(code='A', key='one', first=1, peak=4, top=20., gain=1.)
        record = dict(trades=[], curve=dict(days=days, equity=[1.]*5))
        picks = {0: ['A'], 1: [], 2: [], 3: []}
        row = funnel.measure(A, record, Rules(), picks, [g], pool=np.zeros((5, 1), bool))
        self.assertEqual(row['total']['layers']['L0'], 1)
        self.assertEqual(sum(row['total']['layers'].values()), 1)
        row = funnel.measure(A, record, Rules(), picks, [g], pool=np.ones((5, 1), bool))
        self.assertEqual(row['total']['layers']['L2'], 1)

    def test_execution_sees_only_market_and_nominations_and_cannot_open_labels(self):
        A = dict(days=['a', 'b', 'c', 'd', 'e'], codes=['A'], close=np.ones((5, 1)),
                 legs=object(), ledger=object(), account=object())
        legs = [dict(code='A', first=3, peak=4)]
        seen = []
        def execute(market, picks):
            self.assertEqual(set(market), {'days', 'codes', 'close'})
            self.assertEqual(picks[0], ['B', 'A'])
            with self.assertRaises(PermissionError):
                Path('legs_frozen.json').read_text()
            seen.append(True)
            return {}, None
        funnel.execution_bench(A, legs, {t: ['B'] for t in range(4)}, execute)
        self.assertTrue(seen)

    def test_labels_never_enter_the_execution_module(self):
        source = Path(regime.__file__).read_text()
        self.assertNotIn("['legs']", source)
        self.assertNotIn('legs_frozen.json', source)


if __name__ == '__main__':
    unittest.main()
