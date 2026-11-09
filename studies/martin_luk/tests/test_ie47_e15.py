"""E15 registered factorial selection, sizing, attribution, causality and one-shot records."""
from dataclasses import replace
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np

from studies.martin_luk import e15_research as Q
from studies.martin_luk.tests.test_ie47_e13 import panel
from studies.trader_replication.tests.test_proof_risk import replay


def row(a=.4, b=.2, held=0, dd=.3):
    return dict(by_year={'2024': a, '2025': b}, midpoint_his=held, maxdd=dd)


class FactorialTests(unittest.TestCase):
    def test_exact_binary_inventory_and_registered_mapping(self):
        self.assertEqual(tuple(Q.FACTORS), tuple('STCAHZM'))
        self.assertEqual(len(Q.SPECS), 128)
        self.assertEqual(Q.SPECS['C000'], dict(S='W', T='W', C='W', A='AE', H='H21A', Z='W', M='W'))
        self.assertEqual(Q.SPECS['C127'], dict(S='SK', T='T0', C='CF', A='A0', H='H21', Z='Z2', M='MD'))
        self.assertEqual(len({tuple(s.items()) for s in Q.SPECS.values()}), 128)
        k2 = Q.B.X.rule_layers(Q.M.e8_rules('E8c'), ('AS', 'X1'))
        for name, spec in Q.SPECS.items():
            rules = Q.candidate_rules(k2, spec)
            self.assertEqual(rules.proof_target_mult, 4. if spec['Z'] == 'Z2' else 2.)
            self.assertEqual(rules.max_position, .5 if spec['Z'] == 'Z2' else .3)
            self.assertEqual(rules.proof_trail, 'e21')
            self.assertEqual(rules.proof_add_max, 0 if spec['A'] == 'A0' else 2)
            self.assertEqual(Q.neighbors(name), [f'C{int(name[1:]) ^ (1 << (6-i)):03d}' for i in range(7)])

    def test_annual_floors_drawdown_and_strict_two_point_tie(self):
        runs = dict(K2=row(.39, .148), C000=row(.7, .14, 99), C001=row(.4, .2, 5),
                    C002=row(.42, .215, 7), C003=row(.5, .23, 4), C004=row(.42, .23, 4),
                    C005=row(.5, .4, 99, .50001), C006=row(.42, .2, 20, .5))
        self.assertEqual(Q.select(runs), (['C001', 'C002', 'C003', 'C004', 'C006'], 'C002'))
        runs['C002']['by_year']['2025'] = .2099
        self.assertEqual(Q.select(runs)[1], 'C003')
        for name in list(runs)[1:]:
            runs[name]['by_year']['2024'] = .38
        self.assertEqual(Q.select(runs), ([], None))

    def test_pairwise_main_effect_and_difference_in_differences(self):
        runs = {}
        for name in Q.SPECS:
            s, t, c, a, h, z, m = map(int, f'{int(name[1:]):07b}')
            score = .1 + .03*s - .04*t + .05*z + .07*s*z
            runs[name] = row(score, score)
        effects, interactions = Q.effects(runs)
        self.assertAlmostEqual(effects['Z']['median'], .085)
        self.assertAlmostEqual(effects['T']['median'], -.04)
        self.assertEqual(interactions[0]['factors'], ['S', 'Z'])
        self.assertAlmostEqual(interactions[0]['median'], .07)
        self.assertEqual(interactions[0]['n'], 32)


class SizingTests(unittest.TestCase):
    def test_larger_proof_target_keeps_probe_and_respects_half_equity_cap(self):
        bars = [(100, 100, 100, 100), (100, 102, 99.9, 101)]
        trades = []
        for target, cap in ((2., .3), (4., .5)):
            t = replay(bars, proof_stop='low', proof_target_mult=target, max_position=cap)[0]
            trades.append(t)
            add = next(e for e in t['executions'] if e['action'] == 'add')
            total = t['executions'][0]['shares']+add['shares']
            self.assertLessEqual(total*101, cap*(1+trades[0]['executions'][0]['shares'])+1e-12)
            self.assertLessEqual(total, target*t['k2_shares']+1e-12)
            self.assertLessEqual(add['risk_at_stop'], t['risk_budget']+1e-12)
        self.assertEqual(trades[0]['executions'][0], trades[1]['executions'][0])
        self.assertGreater(trades[1]['executions'][1]['shares'], trades[0]['executions'][1]['shares'])

    def test_four_blocks_are_reduced_by_one_u_including_float32_fees(self):
        t = replay(np.array([(100, 100, 100, 100), (99, 102, 94.5, 101)], np.float32),
                   proof_stop='low', proof_target_mult=4., max_position=.5, buy_cost=.0005, sell_cost=.0005)[0]
        add = next(e for e in t['executions'] if e['action'] == 'add')
        self.assertLess(t['executions'][0]['shares']+add['shares'], 4*t['k2_shares'])
        self.assertAlmostEqual(add['risk_at_stop'], t['risk_budget'])

    def test_close_exit_beats_large_confirmation_and_later_add(self):
        for exit_day in (1, 2):
            sig = np.zeros((3, 1), bool)
            sig[exit_day] = True
            t = replay([(100, 100, 100, 100), (100, 103, 98, 102), (103, 105, 102, 104)],
                       proof_stop='low', proof_target_mult=4., max_position=.5,
                       ema={'exit': sig}, exit_signal='exit')[0]
            self.assertFalse(any(e['action'] == 'add' and e['time'] == t['exit'] for e in t['executions']))

    def test_z_does_not_change_initial_position_cap_for_narrow_stop(self):
        for s in ('W', 'SK'):
            first = []
            A = panel([100., 101.])
            A.update(mode='frozen')
            book = [[((0, 0, 'X0'), 0, 1, 100., 99.99, Q.M.CLOSE_KIND, None)], []]
            k2 = Q.B.X.rule_layers(Q.M.e8_rules('E8c'), ('AS', 'X1'))
            base = (book, Q.M.e8_rules('E8c'), np.ones((2, 1), bool), np.ones((2, 1), bool))
            A['_e14_base'] = base
            for z in ('W', 'Z2'):
                st = Q.E15Study()
                spec = dict(Q.SPECS['C000'], S=s, Z=z)
                entries, rules, _, _ = st.build(A, {'candidate': 'unit', 'spec': spec})
                ema = dict(e9=np.full((2, 1), 90.), e21=np.full((2, 1), 90.),
                           e8_scale=np.ones(2), always=np.ones((2, 1), bool), e14_reclaim=np.ones((2, 1), bool))
                t = Q.Y.simulate(st.px(A), ema, rules, entries, A['days'][0], A['days'][-1], audit=True)[2][0]
                first.append(t['executions'][0])
            self.assertEqual(*first)
            self.assertLessEqual(first[0]['shares']*100, (.25 if s == 'SK' else .3)+1e-12)
            if s == 'SK':
                reference = Q.Y.simulate(st.px(A), ema, replace(k2, risk_scale=''), book,
                                          A['days'][0], A['days'][-1], audit=True)[2][0]
                self.assertEqual(first[0], reference['executions'][0])


class MeasurementTests(unittest.TestCase):
    def test_calendar_period_compounding_and_year_boundary(self):
        curve = dict(days=['2024-01-02', '2024-01-05', '2024-01-08', '2024-01-31',
                           '2024-02-29', '2024-12-31', '2025-01-02'],
                     equity=[1.1, 1.21, 1.089, 1.2, 1.08, 1.5, 1.65])
        periods = Q.periods(curve)
        self.assertAlmostEqual(periods['all']['months'][0]['return'], .2)
        self.assertAlmostEqual(periods['all']['months'][1]['return'], -.1)
        self.assertAlmostEqual(periods['annual']['2025']['months'][0]['return'], .1)
        self.assertAlmostEqual(periods['annual']['2024']['weeks'][0]['return'], .21)
        self.assertAlmostEqual(np.prod([1+x['return'] for x in periods['all']['months']]), 1.65)

    def test_true_phase_cashflow_reconciles_and_keeps_unconfirmed_classification(self):
        t = dict(entry='2024-01-02', why='stop', confirmed=True, confirmed_day='2024-01-03',
                 risk_budget=10., pnl=17., executions=[
                     dict(action='entry', time='2024-01-02', price=100., shares=1.),
                     dict(action='trim', time='2024-01-03', price=103., shares=.1),
                     dict(action='add', time='2024-01-03', price=102., shares=1.),
                     dict(action='stop', time='2024-01-05', price=110., shares=1.9)])
        # Unit-only cash result: -100 +10.3 -102 +209 =17.3.
        t['pnl'] = 17.3
        rules = Q.Y.Rules(buy_cost=0, sell_cost=0)
        source = Q.profit_sources([t], rules)['all']
        self.assertAlmostEqual(source['phase_probe_pnl'], 2.1)
        self.assertAlmostEqual(source['phase_confirmed_pnl'], 15.2)
        self.assertAlmostEqual(source['confirmed_trade_u'], 1.73)
        self.assertAlmostEqual(source['phase_probe_pnl']+source['phase_confirmed_pnl'], 17.3)
        self.assertEqual(Q.profit_sources([dict(t, why='end')], rules)['all']['closed'], 0)

    def test_finished_train_validation_and_ineligible_selection_never_load_data(self):
        with TemporaryDirectory() as folder:
            p = Path(folder)/'record.json'
            p.write_text('{}')
            for method, field in ((Q.train, 'RESULT'), (Q.validate, 'VALIDATION')):
                with patch.object(Q, field, p), patch.object(Q, 'setup') as setup:
                    with self.assertRaisesRegex(ValueError, 'already recorded'):
                        method()
                    setup.assert_not_called()
            selected = Path(folder)/'selected.json'
            selected.write_text(json.dumps(dict(chosen=None)))
            with patch.object(Q, 'SELECTED', selected), patch.object(Q, 'VALIDATION', Path(folder)/'absent'), \
                    patch.object(Q, 'setup') as setup:
                with self.assertRaisesRegex(ValueError, 'must not be tested'):
                    Q.validate()
                setup.assert_not_called()

    def test_resume_requires_same_source_without_rewriting_start(self):
        with TemporaryDirectory() as folder, patch.object(Q, 'WORK', Path(folder)):
            Q.resume_record('train', {'unit': 'fixed'})
            path = Path(folder)/'train_started.json'
            before = path.read_bytes()
            Q.resume_record('train', {'unit': 'fixed'})
            with self.assertRaisesRegex(ValueError, 'cannot resume'):
                Q.resume_record('train', {'unit': 'changed'})
            self.assertEqual(path.read_bytes(), before)

    def test_validation_resumes_without_remeasuring_saved_account(self):
        with TemporaryDirectory() as folder:
            work = Path(folder)
            result, selected, validation = (work/n for n in ('train.json', 'selected.json', 'validation.json'))
            result.write_text('{}')
            source = {'unit': 'fixed'}
            selected.write_text(json.dumps(dict(chosen='C000', source_sha256=source, train_sha256=Q.SP.sha(result))))
            saved = dict(total=.1, by_year={'2026': .1}, trades=3, win=.2)
            validation.with_suffix('.partial.json').write_text(json.dumps(dict(
                chosen='C000', selected_sha256=Q.SP.sha(selected), runs={'K2': saved}, full={})))
            (work/'e10_validation.json').write_text(json.dumps(dict(validate=saved)))
            st = SimpleNamespace(selected=lambda _: {'picks': {}})
            with patch.object(Q, 'WORK', work), patch.object(Q, 'OUT', work), \
                    patch.object(Q, 'RESULT', result), patch.object(Q, 'SELECTED', selected), \
                    patch.object(Q, 'VALIDATION', validation), patch.object(Q, 'fingerprints', return_value=source), \
                    patch.object(Q, 'setup', return_value=(st, {}, {})), \
                    patch.object(Q.B, 'main_legs', return_value={}), patch.object(Q, 'update_checks'), \
                    patch.object(Q, 'evaluate', return_value=saved) as evaluate:
                Q.validate()
                self.assertEqual([c.args[3] for c in evaluate.call_args_list], ['C000', 'K2', 'C000'])
                with self.assertRaisesRegex(ValueError, 'already recorded'):
                    Q.validate()
                self.assertEqual(evaluate.call_count, 3)


class CausalityTests(unittest.TestCase):
    def test_all_128_combinations_future_multiply_shuffle_preserve_inputs_and_executions(self):
        rng = np.random.default_rng(15)
        A = panel(50*np.exp(np.cumsum(rng.normal(.004, .035, (140, 3)), axis=0)))
        picks = {str(A['days'][t]): [str(A['codes'][t % 3])] for t in range(40, 135, 3)}
        cut = 95
        sig = Q.P.signal_arrays(A)
        a = dict(A, **sig)
        base = Q.M.entry_book(a, picks, **Q.M.E6['E6c'])[0]
        self.assertTrue(any(base[:cut+1]))
        k2 = Q.B.X.rule_layers(Q.M.e8_rules('E8c'), ('AS', 'X1'))
        for mode in ('multiply', 'shuffle'):
            b = {k: v.copy() if isinstance(v, np.ndarray) else v for k, v in A.items()}
            order = rng.permutation(np.arange(cut+1, len(A['days'])))
            for key in ('open', 'high', 'low', 'close'):
                b[key][cut+1:] = b[key][cut+1:]*3 if mode == 'multiply' else b[key][order]
            other_sig = Q.P.signal_arrays(b)
            b.update(other_sig)
            other = Q.M.entry_book(b, picks, **Q.M.E6['E6c'])[0]
            self.assertEqual(base[:cut+1], other[:cut+1])
            for key in sig:
                np.testing.assert_array_equal(sig[key][:cut+1], other_sig[key][:cut+1])
            for name, spec in Q.SPECS.items():
                events, books = [], []
                for data, signals, entries in ((a, sig, base), (b, other_sig, other)):
                    book, _ = Q.P.retry_book(data, entries, signals, spec)
                    books.append(book[:cut+1])
                    rules = Q.candidate_rules(k2, spec)
                    ema = dict(signals, always=np.ones(data['close'].shape, bool), e8_scale=np.ones(len(data['days'])))
                    trades = Q.Y.simulate(Q.E15Study().px(data), ema, rules, book,
                                          str(data['days'][40]), str(data['days'][-1]), audit=True)[2]
                    events.append(Q.B.execution_events(trades, str(data['days'][cut])))
                self.assertEqual(*books, name+':'+mode)
                self.assertEqual(*events, name+':'+mode)


if __name__ == '__main__':
    unittest.main()
