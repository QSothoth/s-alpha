import copy
import json
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from studies.martin_luk.workflow import adapter, capital, status, versions
from studies.trader_replication import system
from studies.trader_replication.system import Rules


class CapitalChecks(unittest.TestCase):
    def test_candidate_rules_read_capital_and_reject_invalid_limits(self):
        cap = adapter.read(adapter.FLOW/'config.json')['capital']
        rules = capital.candidate_rules(Rules(max_gross=99, margin_rate=0, max_position=9, max_open=99), cap, 'L2.8')
        self.assertEqual((rules.max_gross, rules.margin_rate, rules.maintenance, rules.deleverage,
                          rules.max_position, rules.max_open), (2.8, .07, .3, 'weakest_first', 9, 99))
        self.assertIs(capital.check_rules(rules, cap, 'L2.8'), rules)
        for bad in (replace(rules, max_gross=2.0), replace(rules, max_gross=2.81),
                    replace(rules, maintenance=None), replace(rules, maintenance=.25),
                    replace(rules, margin_rate=.08), replace(rules, deleverage='other'),
                    replace(rules, max_gross=float('nan'))):
            with self.assertRaises(ValueError):
                capital.check_rules(bad, cap, 'L2.8')
        for profile, limit, maintenance in (('L1', 1., None), ('L2', 2., .25), ('L2.8', 2.8, .3)):
            candidate = capital.candidate_rules(rules, cap, profile, 'pro_rata')
            self.assertEqual((candidate.max_gross, candidate.maintenance, candidate.deleverage),
                             (limit, maintenance, 'pro_rata'))
            self.assertIs(capital.check_rules(candidate, cap, profile), candidate)
            if profile == 'L1':
                self.assertTrue(candidate.gross_cost)
                with self.assertRaises(ValueError):
                    capital.check_rules(replace(candidate, gross_cost=False), cap, profile)
        for missing in (None, '', 'unknown'):
            with self.assertRaises(ValueError):
                capital.check_rules(rules, cap, missing)

    def test_cash_profile_does_not_borrow_to_pay_entry_fees(self):
        cap = adapter.read(adapter.FLOW/'config.json')['capital']
        rules = capital.candidate_rules(Rules(risk=1., max_position=1., trail='', trims=(),
                                              buy_cost=.01, sell_cost=0.), cap, 'L1')
        prices = np.array([[10.], [10.]])
        px = dict(open=prices, high=prices, low=prices, close=prices,
                  dates=np.array(['2025-01-01', '2025-01-02']), codes=np.array(['A']))
        entries = [[(0, 0, 1, 10., 1., 'close')], []]
        track = {}
        system.simulate(px, {}, rules, entries, *px['dates'], audit=True, track=track)
        self.assertAlmostEqual(track['gross'][0], 1.)
        self.assertAlmostEqual(track['margin'], 0.)

    def test_exposure_uses_close_positions_and_retains_final_mark(self):
        record = {'curve': {'days': ['2024-01-02', '2024-01-03'], 'equity': [100, 110]},
                  'trades': [
                      {'code': 'A', 'side': 1, 'executions': [
                          {'time': '2024-01-02', 'action': 'entry', 'shares': 4},
                          {'time': '2024-01-03', 'action': 'trim', 'shares': 1},
                          {'time': '2024-01-03', 'action': 'end', 'shares': 3}]},
                      {'code': 'B', 'side': -1, 'executions': [
                          {'time': '2024-01-02', 'action': 'entry', 'shares': 1},
                          {'time': '2024-01-03', 'action': 'end', 'shares': 1}]}]}
        rows = capital.daily_exposure(record, ['2024-01-02', '2024-01-03'], ['A', 'B'],
                                      np.array([[10., 20.], [12., np.nan]]))
        self.assertAlmostEqual(rows[0]['gross'], .6)
        self.assertAlmostEqual(rows[1]['gross'], 56/110)
        annual = capital.annual_exposure(rows)['2024']
        self.assertAlmostEqual(annual['max'], .6)
        self.assertEqual(annual['max_day'], '2024-01-02')


class VersionsLedger(unittest.TestCase):
    def test_append_requires_merge_acceptance_and_preserves_existing_rows(self):
        score = {k: None for k in versions.FIELDS}
        score.update({'return': 0., 'max_gross': 1., 'peak_held': 0, 'segments': 1, 'margin_calls': 0})
        row = dict(version='v0', name='bar', role='底线', components=dict(regime='R', selection='S', trading='T', conversion='C'),
                   source_account='account', date='2026-11-09', capital_profile='L2.8',
                   scorecard={p: {y: dict(score) for y in versions.YEARS} for p in versions.PROFILES})
        person = dict(version='本人', name='他本人', role='公开资料', components=None, capital_profile=None,
                      scorecard={'public': {y: dict(score) for y in versions.YEARS}})
        candidate = dict(row, version='v1', name='new', role='合并通过')
        rules = dict(capital_profile='L2.8', max_gross=2.8, margin_rate=.07,
                     maintenance=.3, deleverage='weakest_first')
        passed = {'decision': {'line': 'merge', 'status': 'accepted', 'checks': [{'ok': True}]}}
        with tempfile.TemporaryDirectory() as folder:
            ledger, table = Path(folder)/'versions.json', Path(folder)/'VERSIONS_CN.md'
            versions.write_initial([row, person], ledger)
            original = ledger.read_text()
            with self.assertRaises(ValueError):
                versions.append(candidate, {'decision': {'line': 'selection', 'status': 'accepted'}},
                                rules, ledger, table)
            self.assertEqual(ledger.read_text(), original)
            with self.assertRaises(ValueError):
                versions.append(candidate, passed, dict(rules, max_gross=3.), ledger, table)
            self.assertEqual(ledger.read_text(), original)
            with self.assertRaises(ValueError):
                versions.append(candidate, passed, {k: v for k, v in rules.items() if k != 'capital_profile'}, ledger, table)
            versions.append(candidate, passed, rules, ledger, table)
            self.assertTrue(ledger.read_text().startswith(original[:-3]))
            self.assertEqual([r['version'] for r in json.loads(ledger.read_text())], ['v0', '本人', 'v1'])
            self.assertIn('2026 留出*', table.read_text())
            with self.assertRaises(ValueError):
                versions.append(candidate, passed, rules, ledger, table)


@unittest.skipUnless((adapter.FLOW/'state.json').exists(), 'workflow artifacts unavailable')
class StatusRegression(unittest.TestCase):
    def test_status_uses_current_merge_and_excludes_unfinished_legs(self):
        state = adapter.read(adapter.FLOW/'state.json')
        if (state['components']['merge']['version'] != 'C062' or
                state['components']['selection']['version'] != 'IE47' or state['bar'] != 'master'):
            self.skipTest('WF00 base has since changed')
        current = adapter.status()
        cells = {r['line']: r for r in current['cells'] if r['state'] == 'common'}
        self.assertEqual(current['current_merge']['system'], 'C062')
        self.assertEqual(current['baseline_master']['system'], 'master')
        self.assertEqual(sum(r['peak_held'] for r in current['baseline_master']['annual'].values()), 7)
        self.assertEqual((cells['merge']['current'], cells['merge']['retrospective_current']), (11, 13))
        self.assertEqual((cells['selection']['current'], cells['selection']['retrospective_current']), (20, 22))
        self.assertEqual((cells['selection']['reachable_upper'], cells['selection']['upper_observed_in_emitted_list']), (30, 22))
        self.assertEqual(len(current['unresolved_segments']), 3)
        self.assertEqual((current['next_cell']['line'], current['next_cell']['state']), ('trading', 'common'))
        self.assertEqual(cells['trading']['loss_known_by_selection_cutoff'], 12)
        self.assertEqual(current['can_start_round'],
                         bool(state['can_start_round'] and all(current['readiness_checks'].values())))

    def test_readiness_requires_profile_replays_tests_and_matching_caches(self):
        cfg = adapter.read(adapter.FLOW/'config.json')
        state = copy.deepcopy(adapter.read(adapter.FLOW/'state.json'))
        state['rule_fingerprints'] = {'studies/trader_replication/system.py':
                                      adapter.sha(adapter.ROOT/'studies/trader_replication/system.py')}
        data_path = adapter.OUT/'work/leverage_profiles/datasets_check.json'
        data = dict(ok=True, approved_by_user=cfg['datasets']['approved_by_user'],
                    config_sha256=adapter.sha(adapter.FLOW/'config.json'))
        read = adapter.read
        def fake_read(path):
            return data if Path(path) == data_path else read(path)
        with patch.object(adapter, 'read', side_effect=fake_read), \
                patch.object(status, '_replay_evidence', return_value=True) as replay, \
                patch.object(status, '_test_evidence', return_value=True) as tests, \
                patch.object(status, '_cache_evidence', return_value=True) as caches:
            self.assertTrue(all(status.readiness(cfg, state).values()))
            for evidence in (replay, tests, caches):
                evidence.return_value = False
                self.assertFalse(all(status.readiness(cfg, state).values()))
                evidence.return_value = True


if __name__ == '__main__':
    unittest.main()
