"""E14 fixed diagnostic inventory, automatic composition, causality and once-only artifacts."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np

from studies.martin_luk import e14_research as Q, ie47_e1 as M
from studies.martin_luk.tests import test_ie47_e13 as F

panel = F.panel


def row(a, b, held=0):
    return dict(by_year={'2024': a, '2025': b}, midpoint_his=held)


class CompositionTests(unittest.TestCase):
    def diagnostics(self):
        return {n: row(.4, .2) for n in Q.DIAGNOSTICS}

    def test_exactly_twenty_single_replacements_plus_w_and_k2(self):
        self.assertEqual(len(Q.DIAGNOSTICS), 22)
        for name in Q.DIAGNOSTICS:
            if name not in ('W', 'K2'):
                spec = Q.specification(name)
                self.assertEqual(sum(v != 'W' for v in spec.values()), 1)

    def test_w_fallback_is_two_percentage_points_and_second_is_recorded(self):
        runs = self.diagnostics()
        runs['S15'] = row(.4, .219)
        runs['CF'] = row(.4, .24)
        combined, choices = Q.compose(runs)
        self.assertEqual(combined['S'], 'W')
        self.assertEqual(combined['C'], 'CF')
        self.assertEqual(choices['S']['second'], 'S15')
        self.assertAlmostEqual(choices['S']['gap'], -.019)
        self.assertEqual(choices['C']['second'], 'W')

    def test_five_unique_candidates_when_combination_equals_w(self):
        specs, _ = Q.candidate_specs(self.diagnostics())
        self.assertEqual(tuple(specs), Q.CANDIDATES)
        self.assertEqual(specs['G1'], Q.specification('W'))
        self.assertEqual(len({tuple(s.items()) for s in specs.values()}), 5)
        self.assertEqual(specs['G2']['S'], 'S15')

    def test_candidates_follow_smallest_gaps_and_skip_duplicate_w(self):
        runs = self.diagnostics()
        runs['S15'] = row(.4, .25)
        specs, choices = Q.candidate_specs(runs)
        self.assertEqual(specs['G1']['S'], 'S15')
        self.assertEqual(specs['G2'], Q.specification('W'))
        self.assertEqual(len({tuple(s.items()) for s in specs.values()}), 5)
        self.assertTrue(all(sum(v != specs['G1'][k] for k, v in specs[n].items()) == 1 for n in ('G3', 'G4', 'G5')))

    def test_both_years_then_worst_year_midpoint_and_g_order(self):
        runs = dict(K2=row(.39, .148), G1=row(.7, .14, 20), G2=row(.4, .2, 5),
                    G3=row(.42, .215, 7), G4=row(.5, .23, 4), G5=row(.42, .23, 4))
        self.assertEqual(Q.select(runs), (['G2', 'G3', 'G4', 'G5'], 'G3'))
        for n in Q.CANDIDATES:
            runs[n]['by_year']['2024'] = .38
        self.assertEqual(Q.select(runs), ([], None))


class InputsAndRetryTests(unittest.TestCase):
    def test_all_replacements_past_arrays_entries_and_retries_survive_future_perturbation(self):
        rng = np.random.default_rng(14)
        A = panel(50*np.exp(np.cumsum(rng.normal(.004, .035, (150, 5)), axis=0)))
        picks = {str(A['days'][t]): [str(A['codes'][t % 5])] for t in range(40, 140, 3)}
        cut = 100
        before = Q.signal_arrays(A)
        a = dict(A, **before)
        base = M.entry_book(a, picks, **M.E6['E6c'])[0]
        self.assertTrue(any(base[:cut+1]))
        for mode in ('multiply', 'shuffle'):
            B = {k: v.copy() if isinstance(v, np.ndarray) else v for k, v in A.items()}
            order = rng.permutation(np.arange(cut+1, len(A['days'])))
            for k in ('open', 'high', 'low', 'close'):
                B[k][cut+1:] = B[k][cut+1:]*3 if mode == 'multiply' else B[k][order]
            after = Q.signal_arrays(B)
            b = dict(B, **after)
            book = M.entry_book(b, picks, **M.E6['E6c'])[0]
            self.assertEqual(base[:cut+1], book[:cut+1])
            for key in before:
                np.testing.assert_array_equal(before[key][:cut+1], after[key][:cut+1], err_msg=key+':'+mode)
            for name in Q.DIAGNOSTICS:
                if name == 'K2':
                    continue
                spec = Q.specification(name)
                old, old_meta = Q.retry_book(a, base, before, spec)
                new, new_meta = Q.retry_book(b, book, after, spec)
                self.assertEqual(old[:cut+1], new[:cut+1], name+':'+mode)
                self.assertEqual({k:v for k,v in old_meta.items() if k[1] <= str(A['days'][cut])},
                                 {k:v for k,v in new_meta.items() if k[1] <= str(A['days'][cut])})
                k2 = Q.B.X.rule_layers(M.e8_rules('E8c'), ('AS', 'X1'))
                rules = Q.candidate_rules(k2, spec)
                executed = []
                for data, sig, entries in ((a, before, old), (b, after, new)):
                    ema = dict(sig, always=np.ones(data['close'].shape, bool), e8_scale=np.ones(len(data['days'])))
                    trades = Q.Y.simulate(Q.E14Study().px(data), ema, rules, entries,
                                          str(data['days'][40]), str(data['days'][-1]), audit=True)[2]
                    executed.append(Q.B.execution_events(trades, str(A['days'][cut])))
                self.assertEqual(*executed, name+':'+mode+' executions')

    def test_high_close_excludes_today_and_reclaim_uses_previous_high(self):
        A = panel(np.r_[np.arange(100., 130.), 300.])
        sig = Q.signal_arrays(A)
        self.assertEqual(sig['prior20_close'][-1, 0], 129.)
        self.assertTrue(sig['e14_high'][-1, 0])
        self.assertFalse(sig['e14_reclaim'][-1, 0])

    def test_retry_limits_and_deadlines_for_all_t_variants(self):
        for name, maximum, window in (('W', 3, 20), ('T0', 1, 20), ('T2', 2, 10), ('T5', 5, 30)):
            A, sig, base = F.RetryTests().fixture()
            A['close'][3::2] = 96
            A['low'][3::2] = 95
            out, meta = Q.retry_book(A, base, sig, Q.specification(name))
            self.assertEqual(sum(map(len, out)), maximum, name)
            self.assertEqual(max(v['attempt'] for v in meta.values()), maximum)
            A, sig, base = F.RetryTests().fixture()
            A['close'][3] = 96
            sig['e13_retry'][:] = False
            last = min(2+window, len(A['days'])-1)
            sig['e13_retry'][last] = True
            out, _ = Q.retry_book(A, base, sig, Q.specification(name))
            self.assertEqual(bool(out[last]), maximum > 1)

    def test_sc2_path_stops_intraday_on_day_three_and_sk_stops_on_day_one(self):
        A, sig, base = F.RetryTests().fixture()
        A['low'][3:6] = 96
        sc, _ = Q.retry_book(A, base, sig, Q.specification('SC2'))
        sk, _ = Q.retry_book(A, base, sig, Q.specification('SK'))
        self.assertTrue(sc[6])
        self.assertTrue(sk[4])

    def test_t5_includes_thirtieth_session_and_excludes_thirty_first(self):
        A = panel(np.full(40, 100.))
        A['adr'] = np.full_like(A['close'], 10.)
        A['low'][:] = 98
        A['high'][:] = 102
        A['close'][3] = 96
        sig = dict(e13_retry=np.zeros_like(A['close'], bool), e9=np.full_like(A['close'], 90.))
        base = [[] for _ in A['days']]
        base[2] = [((0, 1, 'X0'), 0, 1, 100., 97., M.CLOSE_KIND, None)]
        sig['e13_retry'][32] = True
        out, _ = Q.retry_book(A, base, sig, Q.specification('T5'))
        self.assertTrue(out[32])
        sig['e13_retry'][32] = False
        sig['e13_retry'][33] = True
        out, _ = Q.retry_book(A, base, sig, Q.specification('T5'))
        self.assertEqual(out, base)

    def test_every_replacement_maps_to_the_registered_engine_semantics(self):
        k2 = Q.B.X.rule_layers(M.e8_rules('E8c'), ('AS', 'X1'))
        rules = {n: Q.candidate_rules(k2, Q.specification(n)) for n in Q.DIAGNOSTICS if n != 'K2'}
        self.assertEqual(rules['W'].proof_stop, 'low')
        self.assertEqual(rules['CU'].proof_stop, 'budget')
        self.assertEqual(rules['Z15'].proof_target_mult, 3.)
        self.assertEqual(rules['Z075'].proof_target_mult, 1.5)
        self.assertEqual(rules['AR'].add_levels, (2, 4))
        self.assertEqual(rules['A4'].proof_add_max, 4)
        self.assertEqual(rules['A0'].proof_add_max, 0)
        self.assertEqual(rules['AE'].proof_add_signal, 'e14_reclaim')
        self.assertEqual(rules['H21A'].proof_trail, 'e21')
        self.assertEqual(rules['HN'].trims, ())
        self.assertEqual(rules['M0'].risk_scale, '')
        self.assertEqual(rules['MD'].dd_risk, .2)


class ArtifactTests(unittest.TestCase):
    def test_resume_requires_identical_source_and_preserves_start_record(self):
        with TemporaryDirectory() as folder, patch.object(Q, 'WORK', Path(folder)):
            Q.resume_record('train', {'unit': 'first'})
            path = Path(folder)/'train_started.json'
            before = path.read_bytes()
            Q.resume_record('train', {'unit': 'first'})
            with self.assertRaisesRegex(ValueError, 'cannot resume'):
                Q.resume_record('train', {'unit': 'changed'})
            self.assertEqual(path.read_bytes(), before)

    def test_validation_resume_never_remeasures_a_completed_account(self):
        with TemporaryDirectory() as folder:
            work = Path(folder)
            result, selected, validation = (work/n for n in ('train.json', 'selected.json', 'validation.json'))
            result.write_text('{}')
            sources = {'unit': 'fixed'}
            selected.write_text(json.dumps(dict(chosen='G1', specs={'G1': Q.specification('W')},
                                               source_sha256=sources, train_sha256=Q.SP.sha(result))))
            partial = dict(chosen='G1', selected_sha256=Q.SP.sha(selected),
                           runs={'K2': {'saved': True}}, full={})
            validation.with_suffix('.partial.json').write_text(json.dumps(partial))
            st = SimpleNamespace(selected=lambda _: {'picks': {}})
            with patch.object(Q, 'WORK', work), patch.object(Q, 'RESULT', result), \
                    patch.object(Q, 'SELECTED', selected), patch.object(Q, 'VALIDATION', validation), \
                    patch.object(Q, 'fingerprints', return_value=sources), \
                    patch.object(Q, 'setup', return_value=(st, {}, {})), \
                    patch.object(Q.B, 'main_legs', return_value={}), patch.object(Q, 'update_checks'), \
                    patch.object(Q, 'evaluate', return_value={'new': True}) as evaluate:
                Q.validate()
                self.assertEqual([c.args[3] for c in evaluate.call_args_list], ['G1', 'K2', 'G1'])
                self.assertTrue(json.loads(validation.read_text())['runs']['K2']['saved'])
                with self.assertRaisesRegex(ValueError, 'already recorded'):
                    Q.validate()
                self.assertEqual(evaluate.call_count, 3)

    def test_selection_and_validation_are_not_overwritable(self):
        with TemporaryDirectory() as folder:
            p = Path(folder)/'record.json'
            p.write_text('{}')
            with patch.object(Q, 'RESULT', p), patch.object(Q, 'setup') as setup:
                with self.assertRaisesRegex(ValueError, 'already recorded'):
                    Q.train()
                setup.assert_not_called()
            with patch.object(Q, 'VALIDATION', p), patch.object(Q, 'setup') as setup:
                with self.assertRaisesRegex(ValueError, 'already recorded'):
                    Q.validate()
                setup.assert_not_called()

    def test_no_selection_cannot_load_or_measure_2026(self):
        with TemporaryDirectory() as folder:
            selected, validation = Path(folder)/'selected.json', Path(folder)/'validation.json'
            selected.write_text(json.dumps(dict(chosen=None)))
            with patch.object(Q, 'SELECTED', selected), patch.object(Q, 'VALIDATION', validation), \
                    patch.object(Q, 'setup') as setup:
                with self.assertRaisesRegex(ValueError, 'must not be tested'):
                    Q.validate()
                setup.assert_not_called()
                self.assertFalse(validation.exists())


if __name__ == '__main__':
    unittest.main()
