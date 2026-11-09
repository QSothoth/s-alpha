"""Gate failures block downstream work; missing observations never become evidence."""
from copy import deepcopy
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

import numpy as np

from studies.trader_replication import pipeline as P, regime as R
from studies.trader_replication import ledger


class PipelineTests(unittest.TestCase):
    def test_sources_and_frozen_files_are_checked_before_research(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'notes').mkdir()
            (root/'notes/RULES_CN.md').write_text('Only liquid stocks.')
            trades = root/'trades.csv'
            trades.write_text('id,ticker,side,entry_date,window_lo,window_hi,precision,setup,trigger,stop_pct,outcome,r_multiple,source,note\n'+
                ''.join(f'{k},A,long,2024-01-02,2024-01-02,2024-01-02,exact,breakout,close,,,,video @1:00,\n'
                        for k in range(30)))
            (root/'legs.json').write_text('{}')
            (root/'split.json').write_text('{"select":["2024-01-02","2025-12-31"],"validate":["2026-01-02","2026-10-16"]}')
            st = SimpleNamespace(root=root, ledger=trades, trades=lambda: ledger.load(trades))
            manifest = dict(files={k: dict(path=name, sha256=P.sha(root/name)) for k, name in
                (('trades', 'trades.csv'), ('legs', 'legs.json'), ('split', 'split.json'))},
                claims={k: [dict(quote='Only liquid stocks.', source='video @1:00')] for k in P.SECTIONS},
                public=dict(per_year=dict(value=None, source=None)))
            self.assertEqual(P.g0(st, manifest)['status'], 'pass')
            del manifest['claims']['switch']
            self.assertEqual(P.g0(st, manifest)['status'], 'pass')
            original = manifest['files']['trades']
            manifest['files']['trades'] = manifest['files']['legs']
            self.assertEqual(P.g0(st, manifest)['status'], 'fail')
            manifest['files']['trades'] = original
            (root/'legs.json').write_text('[]')
            self.assertEqual(P.g0(st, manifest)['status'], 'fail')
            st.ledger = None
            self.assertEqual(P.g0(st, manifest)['status'], 'fail')

    def test_new_round_rejects_flat_missing_or_cross_layer_changes(self):
        base = dict(signal=dict(rank='adr'), trade=dict(risk=.005))
        spec = dict(layer='signal', sections_changed=['signal'], upper_bound=.9,
                    candidates=dict(A=dict(signal=dict(rank='turnover'))))
        self.assertFalse(P.validate_round(spec, base)['legacy'])
        for change in ({'trade': {'risk': .01}}, {'rank': 'turnover'}):
            bad = dict(spec, candidates=dict(A=change))
            with self.assertRaises(ValueError):
                P.validate_round(bad, base)
        with self.assertRaises(ValueError):
            P.validate_round(dict(candidates=spec['candidates']), base)
        self.assertTrue(P.validate_round({}, base, legacy=True)['legacy'])

    def test_reference_engine_can_be_checked_before_other_systems(self):
        checks = {k: dict(ok=True, status='checked') for k in ('data', 'fills', 'lookahead', 'win_rate')}
        args = dict(checks=checks, code_sha='code', data_sha='data')
        self.assertEqual(P.g1(**args)['status'], 'fail')
        master = P.g1(**args, is_reference=True)
        self.assertEqual(master['status'], 'pass')
        self.assertEqual(P.g1(**args, reference=master)['status'], 'pass')
        checks['win_rate']['status'] = 'unchecked'
        self.assertEqual(P.g1(**args, is_reference=True)['status'], 'fail')

    def test_paired_requires_mechanism_and_exact_changed_sections(self):
        spec = dict(layer='signal', sections_changed=['signal', 'trade'], upper_bound=.9, paired=True,
                    candidates=dict(A=dict(signal=dict(rank='adr'), trade=dict(risk=.01))))
        with self.assertRaises(ValueError):
            P.validate_round(spec, {})
        spec['mechanism'] = 'entry volatility and position risk must change together'
        self.assertEqual(P.validate_round(spec, {})['sections_changed'], ['signal', 'trade'])
        spec['sections_changed'] = ['signal']
        with self.assertRaises(ValueError):
            P.validate_round(spec, {})

    def test_admission_cannot_be_hidden_in_trade_rules(self):
        spec = dict(layer='trade', sections_changed=['trade'], upper_bound=.9,
                    candidates=dict(A=dict(trade=dict(rule_opts=dict(max_open=4)))))
        with self.assertRaises(ValueError):
            P.validate_round(spec, {})

    def test_upstream_failure_blocks_paired_downstream_too(self):
        gates = {k: P.result('pass', 'test') for k in ('G0', 'G1', 'G2')}
        gates['G3'] = P.result('fail', 'coverage 65%')
        self.assertEqual(P.allowed_actions(gates, legacy=True)['allowed'], ['universe', 'signal'])
        spec = dict(layer='trade', sections_changed=['trade'], upper_bound=1.,
                    candidates=dict(A=dict(trade=dict(risk=.01))))
        with self.assertRaises(ValueError):
            P.validate_round(spec, {}, gates=gates, legacy=True)

    def test_signal_round_can_pair_trade_but_must_select_on_signal(self):
        gates = {k: P.result('pass', 'test') for k in ('G0', 'G1', 'G2')}
        gates['G3'] = P.result('fail', 'coverage below target')
        spec = dict(layer='signal', sections_changed=['signal', 'trade'], upper_bound=1.,
            paired=True, mechanism='state changes signal tiers and entry risk together',
            candidates=dict(A=dict(signal=dict(rank='tier'), trade=dict(risk=.008))))
        with self.assertRaises(ValueError):
            P.validate_round(spec, {}, gates=gates, legacy=True)
        spec.update(selection_layer='signal', selection_metric='S_K3_early_coverage')
        self.assertEqual(P.validate_round(spec, {}, gates=gates, legacy=True)['selection_layer'], 'signal')
        spec['selection_layer'] = 'trade'
        with self.assertRaises(ValueError):
            P.validate_round(spec, {}, gates=gates, legacy=True)
        spec['selection_layer'] = 'signal'
        gates['G1'] = P.result('fail', 'bad fills')
        with self.assertRaises(ValueError):
            P.validate_round(spec, {}, gates=gates, legacy=True)

    def test_unobserved_weak_state_retains_quoted_rules(self):
        labels = dict(episodes=R.episodes([0]*10+[1]*10+[2]*10, list(map(str, range(30)))), spec_sha='frozen')
        control = dict(field='risk_mult', quote='reduce risk', values=dict(up=1., pullback=1.6, weak=.5))
        out = P.g2(labels, [], controls=[control], rules_text='reduce risk', stable=dict(ok=True),
                   lookahead=dict(ok=True), metric='holding_days', draws=9)
        self.assertEqual(out['status'], 'unobserved')
        self.assertTrue(out['numbers']['permitted'])
        self.assertEqual(out['numbers']['states']['weak']['status'], 'unobserved')
        self.assertEqual(len(out['numbers']['folds']), 3)
        out = P.g2(labels, [], controls=[control], rules_text='reduce risk', stable=dict(ok=False),
                   lookahead=dict(ok=True), metric='holding_days', draws=9)
        self.assertEqual(out['status'], 'fail')

    def test_observed_switch_compares_held_episode_with_training_direction(self):
        label = np.tile(np.repeat([0, 2], 3), 6)
        labels = dict(episodes=R.episodes(label, list(map(str, range(len(label))))), spec_sha='frozen')
        observations = [dict(day=t, value=10. if state == 0 else 1.) for t, state in enumerate(label)]
        control = dict(field='risk_mult', quote='reduce risk', values=dict(up=1., pullback=1., weak=.5))
        out = P.g2(labels, observations, controls=[control], rules_text='reduce risk',
                   stable=dict(ok=True), lookahead=dict(ok=True), metric='holding_days')
        self.assertEqual(out['numbers']['states']['up']['status'], 'pass')
        self.assertEqual(out['numbers']['states']['weak']['status'], 'pass')
        self.assertEqual(out['status'], 'unobserved')  # no pullback observations
        self.assertTrue(out['numbers']['permitted'])
        self.assertTrue(all(f['test']['same_direction'] for f in out['numbers']['folds']))

    def test_s_gate_reports_all_years_and_cannot_drop_empty_nights(self):
        calendar = np.array(['2024-01-02', '2024-01-03', '2024-01-04', '2025-01-02',
                             '2025-01-03', '2025-01-04', '2026-01-02', '2026-01-03', '2026-01-04'])
        legs = [dict(code='A', first=t+1, peak=t+2, gain=.5, top=15.) for t in (0, 3, 6)]
        picks = {t: ['A'] if t in (0, 3, 6) else [] for t in range(8)}
        folds = {y: dict(picks=picks, trained_years=[], model_sha='fixed-rule', sample='holdout*')
                 for y in ('2024', '2025', '2026')}
        out = P.g3(folds, legs, calendar, {'A': np.full(9, 10.)}, upper_bound=1.)
        self.assertEqual(set(out['numbers']['folds']), set(folds))
        # The same name stays in the 10-session cooldown across calendar years.
        self.assertEqual(out['status'], 'fail')
        bad = deepcopy(folds)
        del bad['2026']['picks'][1]
        with self.assertRaises(ValueError):
            P.g3(bad, legs, calendar, {'A': np.full(9, 10.)}, upper_bound=1.)

    def test_missing_year_models_are_unobserved_not_new_fits(self):
        out = P.g3({}, [], np.array(['2024-01-01']), {}, upper_bound=1.)
        self.assertEqual(out['status'], 'unobserved')
        self.assertEqual(out['numbers']['missing_folds'], ['2024', '2025', '2026'])

    def test_episode_holdouts_never_include_held_episode_in_train(self):
        episodes = R.episodes([0, 0, 1, 2], list('abcd'))
        folds = P.episode_folds(episodes, lambda part: [e['id'] for e in part])
        for row in folds:
            self.assertEqual(row['test'], [row['held_out']])
            self.assertNotIn(row['held_out'], row['train'])

    def test_account_gate_ignores_purity_and_random_diagnostics(self):
        card = dict(years={'2024': .2}, source='published')
        facts = dict(years={'2024': .2})
        episodes = R.episodes([0, 0, 2], ['2024-01-01', '2024-01-02', '2024-01-03'])
        out = P.g5(card, facts, [1., 1.1, 1.2], [e for e in ('2024-01-01', '2024-01-02', '2024-01-03')],
                   episodes, diagnostics=dict(cap_equity=0., placebo_rank=0.))
        self.assertEqual(out['status'], 'pass')
        facts['years']['2024'] = -.01
        self.assertEqual(P.g5(card, facts, [1., 1.1, .99], ['2024-01-01', '2024-01-02', '2024-01-03'],
                              episodes)['status'], 'fail')

    def test_behaviour_uses_closed_win_rate_but_counts_actual_openings(self):
        dates = ['2024-01-01', '2024-01-02', '2024-01-03', '2024-01-04']
        trades = [dict(entry=dates[0 if k % 2 == 0 else 2], ret=.1 if k % 4 == 0 else -.02,
                       days=10 if k % 4 == 0 else 4, why='trail') for k in range(52)]
        trades.append(dict(entry=dates[2], ret=1., days=1, why='end'))
        facts = P.account_facts([1., 1.1, 1.2, 1.3], dates, trades)
        facts['gate'] = dict(data=True, fills=True, lookahead=True)
        self.assertEqual(facts['closed'], 52)
        self.assertEqual(facts['counts']['2024'], 53)
        self.assertEqual(facts['win'], .25)
        card = dict(source='unit interview @1:00', per_year=52, behaviour=dict(payoff=5., days=5.5))
        out = P.g4(card, facts, trades, R.episodes([0, 0, 2, 2], dates),
                   bought=dict(hits=3, n=4), three_layer=dict(his=1., his_our_execution=.8, ours=.3))
        self.assertEqual(out['status'], 'pass')
        self.assertEqual(len(out['numbers']['folds']), 2)

    def test_freeze_waits_for_approval_and_preserves_date(self):
        args = dict(code_sha='code', data_sha='data', freeze='2026-10-16', data_last='2026-10-16',
                    registered='2026-11-08', forward_start='2026-10-16', markets=['us', 'hk', 'cn'], robust={}, approved=False)
        self.assertEqual(P.g6(**args)['status'], 'unobserved')
        args['approved'] = True
        self.assertEqual(P.g6(**args)['status'], 'pass')
        args['freeze'] = '2026-11-08'
        self.assertEqual(P.g6(**args)['status'], 'fail')

    def test_matched_exposure_is_one_global_scale(self):
        row = P.exposure_scale([1., 2., 0.], [.5, 1., 0.])
        self.assertEqual(row['multiplier'], .5)
        with self.assertRaises(ValueError):
            P.exposure_scale([1.], [np.nan])


if __name__ == '__main__':
    unittest.main()
