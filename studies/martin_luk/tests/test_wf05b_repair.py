from dataclasses import asdict
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from studies.martin_luk import wf05_engine
from studies.martin_luk.workflow import adapter, frozen_cache, status, version_profile, versions
from studies.trader_replication import system


class FrozenBenchTests(unittest.TestCase):
    def test_save_replaces_inherited_marks_with_account_marks(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root/'prices.npy'
            source.write_bytes(b'price source')
            inputs = {'selection_end':'2025-12-31', 'selection_end_marks':{'OLD':1.}}
            files = {'inputs.json':inputs, 'account.json':{'record':{'trades':[]}}}
            with patch.object(frozen_cache, 'ROOT', root), patch.object(frozen_cache, 'FROZEN', root/'frozen'), \
                 patch.object(frozen_cache, 'identity', return_value=({}, 'data')), \
                 patch.object(frozen_cache, 'pinned_selection_end_marks', return_value=({'NEW':2.}, (source,))) as marks:
                frozen_cache.save('trading', 'v2', files, [])
            saved = json.loads((root/'frozen/trading/v2/inputs.json').read_text())
            manifest = json.loads((root/'frozen/trading/v2/manifest.json').read_text())
            self.assertEqual(saved['selection_end_marks'], {'NEW':2.})
            self.assertEqual(inputs['selection_end_marks'], {'OLD':1.})
            self.assertEqual(manifest['sources']['prices.npy'], adapter.sha(source))
            marks.assert_called_once()
            self.assertEqual(marks.call_args.args[0], files['account.json']['record'])
            self.assertEqual(marks.call_args.args[1]['selection_end'], inputs['selection_end'])

    def test_marks_use_only_crossing_positions_and_pre_cutoff_prices(self):
        calendar = ['2025-12-30', '2025-12-31', '2026-01-02']
        close = np.array([[10., 20., 30.], [11., np.nan, 31.], [99., 99., 99.]])
        trades = [{'code': 'A', 'entry': '2025-12-30', 'exit': '2026-01-02'},
                  {'code': 'B', 'entry': '2025-12-31', 'exit': '2026-01-02'},
                  {'code': 'C', 'entry': '2025-12-30', 'exit': '2025-12-31'}]
        self.assertEqual(frozen_cache.selection_end_marks({'trades': trades}, calendar,
                         ['A', 'B', 'C'], close, '2025-12-31'), {'A': 11., 'B': 20.})
        with self.assertRaises(ValueError):
            frozen_cache.selection_end_marks({'trades': [trades[1]]}, calendar,
                    ['A', 'B', 'C'], np.full_like(close, np.nan), '2025-12-31')

    def test_pinned_marks_validate_sources_and_selection_cutoff(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            reports, flow = root/'reports', root/'workflow'
            panel, market = reports/'u1_work/panel', reports/'p3_work/market'
            panel.mkdir(parents=True)
            market.mkdir(parents=True)
            flow.mkdir()
            paths = [panel/'days.npy', panel/'codes.npy', market/'close.npy']
            for path, value in zip(paths, (np.array(['2025-12-31', '2026-01-02']),
                                           np.array(['A']), np.array([[10.], [99.]]))):
                np.save(path, value)
            config = {'selection_years':['2025'], 'datasets':{'artifacts':[
                {'path':str(p.relative_to(root)), 'sha256':adapter.sha(p)} for p in paths]}}
            (flow/'config.json').write_text(json.dumps(config))
            inputs = {'selection_end':'2025-12-31', 'calendar':['2025-12-31', '2026-01-02']}
            record = {'trades':[{'code':'A', 'entry':'2025-12-31', 'exit':'2026-01-02'}]}
            with patch.object(frozen_cache, 'ROOT', root), patch.object(frozen_cache, 'FLOW', flow), \
                 patch.object(adapter, 'REPORTS', reports):
                marks, _ = frozen_cache.pinned_selection_end_marks(record, inputs)
                self.assertEqual(marks, {'A':10.})
                with self.assertRaises(ValueError):
                    frozen_cache.pinned_selection_end_marks(record, dict(inputs, selection_end='2026-01-02'))
                np.save(paths[2], np.array([[11.], [99.]]))
                with self.assertRaises(ValueError):
                    frozen_cache.pinned_selection_end_marks(record, inputs)

    def test_bench_rules_use_pinned_engine_and_reject_bad_identity(self):
        self.assertIsInstance(frozen_cache.bench_rules({}, asdict(system.Rules())), system.Rules)
        manifest = {'engine': 'studies.martin_luk.wf05_engine',
                    'engine_sha256': frozen_cache.sha(Path(wf05_engine.__file__))}
        values = asdict(wf05_engine.Rules(rotate_rmax_r=1.25))
        self.assertEqual(frozen_cache.bench_rules(manifest, values).rotate_rmax_r, 1.25)
        for bad in (dict(manifest, engine='untrusted.module'), dict(manifest, engine_sha256='bad')):
            with self.assertRaises(ValueError):
                frozen_cache.bench_rules(bad, values)
        with self.assertRaises(ValueError):
            frozen_cache.bench_rules(manifest, dict(values, typo=True))


class VersionEvidenceTests(unittest.TestCase):
    def test_version_evidence_preserves_legacy_and_rejects_stale_source(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            flow = root/'flow'
            evidence_path = flow/'rounds/WF05b/version_profile_v2.json'
            evidence_path.parent.mkdir(parents=True)
            source = root/'source.json'
            source.write_text('{}')
            entries = [{'version':v} for v in ('v0', 'v1', 'v2')]
            item = {'version':'v2', 'sources':{'source.json':adapter.sha(source)},
                    'entry_sha256':versions.entry_fingerprint(entries[-1]),
                    'by_state':{'2024':{}}, 'switch':'s', 'alignment':[], 'note':'n'}
            evidence_path.write_text(json.dumps(item))
            existing = {'by_state':{'v0':{'old':1}, 'v1':{'old':2}},
                        'switches':{'v0':'a', 'v1':'b'}}
            with patch.object(adapter, 'ROOT', root), patch.object(adapter, 'FLOW', flow):
                result = versions.add_version_evidence(entries, existing)
                self.assertEqual(result['by_state']['v0'], {'old':1})
                self.assertEqual(result['by_state']['v1'], {'old':2})
                self.assertEqual(result['by_state']['v2'], {'2024':{}})
                versions.add_version_evidence(entries + [{'version':'v3'}], existing)
                with self.assertRaises(ValueError):
                    versions.add_version_evidence(entries[:-1] + [{'version':'v2', 'name':'changed'}], existing)
                source.write_text('{"changed":true}')
                with self.assertRaises(ValueError):
                    versions.add_version_evidence(entries, existing)

    def test_state_behavior_keeps_legacy_format_and_marks_missing_holdout_details(self):
        row = {'side':{'long':1, 'short':1}, 'entries':2, 'long_share_gap_pp':0.,
               'trader_sample_n':2, 'trader_side':{'long':{'fraction':.5}, 'short':{'fraction':.5}},
               'kind':{'breakout':2}, 'days':3., 'closed':2, 'win':.5, 'payoff':2.}
        self.assertEqual(version_profile.state_behavior(row, .2),
            '2 笔，多 1 / 空 1；多头差 +0.0 个百分点；画像范围内；触发 breakout 2；均持 3.0 天（平仓 2 笔）')
        self.assertIn('胜率 50.0%；盈亏比 2.00',
                      version_profile.state_behavior(dict(row, report_win_payoff=True), .2))
        self.assertIn('多空、触发未在留出记录中分状态列出',
                      version_profile.state_behavior(dict(row, side=None), .2))


class AuditEvidenceTests(unittest.TestCase):
    def test_cache_readiness_checks_payloads_and_frozen_conversion(self):
        code = {name:'digest' for name in ('studies/trader_replication/system.py',
                'studies/martin_luk/workflow/adapter.py', 'studies/martin_luk/workflow/capital.py')}
        component = {'version':'v2', 'options':{'max_open':11}}
        state = {'frozen_caches':{'conversion':{'v2':{'manifest_sha256':'digest'}}},
                 'components':{'conversion':component}}
        cap = {'acceptance_profile':'L2.8'}
        def read(path):
            if Path(path).name == 'manifest.json':
                return {'code_fingerprints':code, 'data_fingerprint':'data'}
            return {'profile':'L2.8', 'curve_exact':True, 'trades_exact':True, 'attempts_exact':True,
                    'system_sha256':'digest', 'adapter_sha256':'digest', 'capital_sha256':'digest',
                    'script_sha256':'digest', 'input_sha256':'digest', 'account_sha256':'digest'}
        with patch.object(frozen_cache, 'identity', return_value=(code,'data')), \
             patch.object(adapter, 'read', side_effect=read), patch.object(adapter, 'sha', return_value='digest'), \
             patch.object(frozen_cache, 'load', return_value={'allocation.json':component}) as load:
            self.assertTrue(status._cache_evidence(state, cap))
            load.return_value = {'allocation.json':{'version':'v2', 'options':{'max_open':10}}}
            self.assertFalse(status._cache_evidence(state, cap))
            load.side_effect = ValueError('payload SHA mismatch')
            self.assertFalse(status._cache_evidence(state, cap))

    def test_dataset_evidence_requires_current_config_and_original_log(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            flow = root/'flow'
            logs = flow/'rounds/WF05b/logs'
            logs.mkdir(parents=True)
            cfg = {'datasets':{'approved_by_user':'2026-11-09'}}
            config_path = flow/'config.json'
            config_path.write_text(json.dumps(cfg))
            log = logs/'datasets_check.json'
            log.write_text(json.dumps({'ok':True, 'approved_by_user':'2026-11-09'}))
            evidence = {'ok':True, 'approved_by_user':'2026-11-09',
                        'config_sha256':adapter.sha(config_path), 'log':str(log.relative_to(root)),
                        'log_sha256':adapter.sha(log)}
            (logs/'datasets_evidence.json').write_text(json.dumps(evidence))
            with patch.object(adapter, 'ROOT', root), patch.object(adapter, 'FLOW', flow), \
                 patch.object(adapter, 'OUT', flow/'rounds/WF00'):
                self.assertTrue(status._dataset_evidence(cfg))
                log.write_text(json.dumps({'ok':False, 'approved_by_user':'2026-11-09'}))
                self.assertFalse(status._dataset_evidence(cfg))

    def test_selection_cutoff_funnel_keeps_missing_cross_year_segments(self):
        states = {'calendar':['2025-12-30', '2025-12-31', '2026-01-02', '2026-01-05'],
                  'label':['up', 'weak', 'up', 'weak']}
        legs = [{'key':'complete', 'first':0, 'peak':1},
                {'key':'crossing', 'first':1, 'peak':3}]
        missing = status._missing_unresolved(legs, states, [{'key':'complete'}], ['2025'], '2025-12-31')
        self.assertEqual(missing, [{'key':'crossing', 'year':'2025', 'state':'weak',
                                    'coverage':{'peak_eve':'2026-01-02'}}])
        with self.assertRaises(ValueError):
            status._missing_unresolved(legs, states, [], ['2025'], '2025-12-31')

    def test_test_evidence_checks_current_code_and_log_hashes(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            flow = root/'flow'
            logs = flow/'rounds/WF05b/logs'
            logs.mkdir(parents=True)
            code = ('studies/trader_replication/system.py', 'studies/martin_luk/workflow/capital.py',
                    'studies/martin_luk/workflow/status.py', 'studies/martin_luk/workflow/versions.py',
                    'studies/martin_luk/workflow/adapter.py', 'studies/martin_luk/workflow/frozen_cache.py',
                    'studies/trader_replication/tests/test_margin_call.py',
                    'studies/martin_luk/tests/test_workflow_versions_capital.py')
            fingerprints = {}
            for name in code:
                path = root/name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(name)
                fingerprints[name] = adapter.sha(path)
            suites = {}
            for index, name in enumerate(('custody/tests', 'studies/trader_replication/tests',
                                           'studies/martin_luk/tests', 'studies/trader_screens/tests')):
                log = logs/f'{index}.log'
                log.write_text('passed')
                suites[name] = {'passed':True, 'returncode':0, 'count':1,
                                'log':str(log.relative_to(root)), 'log_sha256':adapter.sha(log)}
            (logs/'tests.json').write_text(json.dumps({'code_sha256':fingerprints,
                'code_unchanged_during_tests':True, 'suites':suites}))
            with patch.object(adapter, 'ROOT', root), patch.object(adapter, 'FLOW', flow), \
                 patch.object(adapter, 'OUT', flow/'rounds/WF00'):
                self.assertTrue(status._test_evidence())
                (logs/'0.log').write_text('changed')
                self.assertFalse(status._test_evidence())

    def test_replay_audit_requires_every_version_and_unmodified_replay_numbers(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            flow = root/'flow'
            flow.mkdir()
            def write(path, value):
                path.write_text(json.dumps(value))
            cap = {'acceptance_profile':'L1', 'profiles':{'L1':{}}}
            write(flow/'config.json', {'capital':cap, 'selection_years':['2024', '2025']})
            annual = {'2024':{'return':.1}, '2025':{'return':.2}}
            entry = {'version':'v0', 'name':'base', 'scorecard':{'L1':annual}}
            write(flow/'versions.json', [entry])
            source = root/'source.py'
            source.write_text('source')
            reference = root/'reference.json'
            rules = {'key':1}
            write(reference, {'rules':rules, 'annual':annual})
            legacy_row = {'replay':'reference.json', 'sha256':adapter.sha(reference),
                          'curve_exact':True, 'trades_exact':True}
            old = {'ok':True, 'capital':cap, 'config_sha256':adapter.sha(flow/'config.json'),
                   'systems':{name:{key:legacy_row for key in ('L1','pro_rata','legacy')}
                              for name in ('master','C062')}}
            old_path = root/'old.json'
            write(old_path, old)
            replay = root/'replay.json'
            run = {'version':'v0', 'profile':'L1', 'reference':'reference.json',
                   'reference_sha256':adapter.sha(reference), 'end':'2025-12-31',
                   'rules_exact':True, 'annual_exact':True, 'comparison':{'ok':True},
                   'rules':rules, 'engine':'system', 'engine_sha256':'hash',
                   'annual':{y:{'computed':dict(value), 'differences':{}} for y,value in annual.items()}}
            write(replay, run)
            row = {'replay':'replay.json', 'sha256':adapter.sha(replay),
                   'reference':'reference.json', 'reference_sha256':adapter.sha(reference)}
            audit = {'ok':True, 'capital':cap, 'profile':'L1',
                     'config_sha256':adapter.sha(flow/'config.json'),
                     'versions_sha256':adapter.sha(flow/'versions.json'),
                     'sources':{'source.py':adapter.sha(source)},
                     'previous_audit':{'path':'old.json', 'sha256':adapter.sha(old_path)},
                     'versions':{'v0':{'name':'base', 'profiles':{'L1':row}}}}
            audit_path = root/'audit.json'
            write(audit_path, audit)
            with patch.object(adapter, 'ROOT', root), patch.object(adapter, 'FLOW', flow), \
                 patch.object(frozen_cache, 'bench_rules', return_value=object()), \
                 patch.object(status.capital, 'check_rules'):
                self.assertTrue(status._valid_replay_audit(audit_path, cap))
                run['annual']['2025']['computed']['return'] = .3
                write(replay, run)
                row['sha256'] = adapter.sha(replay)
                write(audit_path, audit)
                self.assertFalse(status._valid_replay_audit(audit_path, cap))
                run['annual']['2025']['computed']['return'] = .2
                write(replay, run)
                row['sha256'] = adapter.sha(replay)
                write(audit_path, audit)
                write(flow/'versions.json', [entry, dict(entry, version='v1')])
                audit['versions_sha256'] = adapter.sha(flow/'versions.json')
                write(audit_path, audit)
                self.assertFalse(status._valid_replay_audit(audit_path, cap))
