"""E13 causal inputs, path-driven retries and fixed selection, before implementation."""
from datetime import date, timedelta
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np

from studies.martin_luk import e13_research as E13, ie47_e1 as M


def panel(c):
    c = np.asarray(c, float)
    if c.ndim == 1:
        c = c[:, None]
    return dict(days=np.array([str(date(2024, 1, 1)+timedelta(days=t)) for t in range(len(c))]),
                codes=np.array([f'X{j}' for j in range(c.shape[1])]), open=c*.995, high=c*1.01,
                low=c*.98, close=c, market='us')


class CausalInputTests(unittest.TestCase):
    def test_future_multiplication_and_shuffle_leave_all_past_inputs_and_books_bitwise_equal(self):
        rng = np.random.default_rng(13)
        A = panel(50*np.exp(np.cumsum(rng.normal(.004, .035, (130, 5)), axis=0)))
        picks = {str(A['days'][t]): [str(A['codes'][t % 5])] for t in range(40, 120, 3)}
        cut = 90
        before = E13.signal_arrays(A)
        a = dict(A, **before)
        base = M.entry_book(a, picks, **M.E6['E6c'])[0]
        retries = E13.retry_book(a, base, before, hard_mult=2.)[0]
        self.assertTrue(any(base[:cut+1]))
        self.assertGreater(sum(map(len, retries[:cut+1])), sum(map(len, base[:cut+1])))
        for mode in ('multiply', 'shuffle'):
            B = {k: v.copy() if isinstance(v, np.ndarray) else v for k, v in A.items()}
            order = rng.permutation(np.arange(cut+1, len(A['days'])))
            for k in ('open', 'high', 'low', 'close'):
                B[k][cut+1:] = B[k][cut+1:]*3 if mode == 'multiply' else B[k][order]
            after = E13.signal_arrays(B)
            b = dict(B, **after)
            book = M.entry_book(b, picks, **M.E6['E6c'])[0]
            retry = E13.retry_book(b, book, after, hard_mult=2.)[0]
            self.assertEqual(base[:cut+1], book[:cut+1])
            self.assertEqual(retries[:cut+1], retry[:cut+1])
            for key in before:
                np.testing.assert_array_equal(before[key][:cut+1], after[key][:cut+1], err_msg=key+':'+mode)

    def test_twenty_day_high_excludes_today_and_adr_for_entry_is_yesterday(self):
        A = panel(np.r_[np.arange(100., 130.), 300.])
        sig = E13.signal_arrays(A)
        self.assertEqual(sig['prior20_close'][-1, 0], 129.)
        B = dict(A, **sig)
        picks = {str(A['days'][-2]): ['X0']}
        first = M.entry_book(B, picks, **M.E6['E6c'])[0][-1][0]
        B['adr'] = sig['adr'].copy()
        B['adr'][-1] = 1000
        self.assertEqual(first, M.entry_book(B, picks, **M.E6['E6c'])[0][-1][0])

    def test_retry_trend_and_add_masks_use_the_named_ema_and_prior_high(self):
        A = panel(100*1.016**np.arange(90))
        sig = E13.signal_arrays(A)
        t = 89
        self.assertTrue(sig['e13_add'][t, 0])
        self.assertTrue(sig['e13_retry'][t, 0])
        B = dict(A)
        B['close'] = A['close'].copy()
        B['close'][-1] = A['high'][-2]
        self.assertFalse(E13.signal_arrays(B)['e13_retry'][-1, 0])


class RetryTests(unittest.TestCase):
    def fixture(self):
        A = panel(np.full(30, 100.))
        A['adr'] = np.full_like(A['close'], 10.)
        A['low'][:] = 98
        A['high'][:] = 102
        sig = dict(e13_retry=np.ones_like(A['close'], bool), e9=np.full_like(A['close'], 90.))
        base = [[] for _ in A['days']]
        base[2] = [((0, 1, 'X0'), 0, 1, 100., 97., M.CLOSE_KIND, None)]
        return A, sig, base

    def test_at_most_three_from_first_entry_and_no_same_day_rebuy(self):
        A, sig, base = self.fixture()
        A['close'][3:8, 0] = [96, 101, 97, 102, 97]
        A['low'][3:8, 0] = [95, 98, 96, 99, 96]
        out, meta = E13.retry_book(A, base, sig, hard_mult=2.)
        self.assertEqual([d for d, row in enumerate(out) if row], [2, 4, 6])
        self.assertEqual([meta[('X0', str(A['days'][d]))]['attempt'] for d in (2, 4, 6)], [1, 2, 3])
        self.assertEqual(meta[('X0', str(A['days'][6]))]['origin'], str(A['days'][2]))

    def test_confirmation_ends_retries_and_hard_stop_has_priority_over_profitable_close(self):
        A, sig, base = self.fixture()
        A['close'][3] = 101
        A['low'][4] = 90
        out, _ = E13.retry_book(A, base, sig, hard_mult=2.)
        self.assertEqual([d for d, row in enumerate(out) if row], [2])
        A['low'][3] = 93
        out, _ = E13.retry_book(A, base, sig, hard_mult=2.)
        self.assertEqual([d for d, row in enumerate(out) if row][:2], [2, 4])

    def test_window_runs_from_first_entry_and_uses_new_stop_and_prior_adr(self):
        A, sig, base = self.fixture()
        A['close'][3] = 96
        sig['e13_retry'][:] = False
        sig['e13_retry'][22] = True
        A['low'][22] = 95
        A['adr'][21] = 4
        A['adr'][22] = 100
        out, _ = E13.retry_book(A, base, sig, hard_mult=2.)
        self.assertAlmostEqual(out[22][0][4], 98.)
        sig['e13_retry'][22] = False
        sig['e13_retry'][23] = True
        self.assertFalse(any(E13.retry_book(A, base, sig, hard_mult=2.)[0][3:]))

    def test_f2_uses_intraday_k2_stop_while_s_survives(self):
        A, sig, base = self.fixture()
        A['low'][3] = 96
        out, _ = E13.retry_book(A, base, sig, hard_mult=0.)
        self.assertTrue(out[4])
        out, _ = E13.retry_book(A, base, sig, hard_mult=2.)
        self.assertFalse(any(out[3:]))

    def test_without_t_is_exactly_original_book(self):
        A, sig, base = self.fixture()
        A['close'][3] = 96
        self.assertEqual(E13.retry_book(A, base, sig, hard_mult=2., enabled=False)[0], base)


class SelectionTests(unittest.TestCase):
    def test_both_years_required_then_worst_year_then_midpoint_then_fixed_order(self):
        def row(a, b, held):
            return dict(by_year={'2024': a, '2025': b}, midpoint_his=held)
        runs = dict(K2=row(.39, .148, 1), F1=row(.70, .14, 20), F2=row(.40, .20, 5),
                    F3=row(.42, .215, 7), F4=row(.50, .23, 4), F5=row(.42, .23, 4))
        eligible, chosen = E13.select(runs)
        self.assertEqual(eligible, ['F2', 'F3', 'F4', 'F5'])
        self.assertEqual(chosen, 'F3')
        runs['F3']['by_year']['2025'] = .19
        self.assertEqual(E13.select(runs)[1], 'F4')
        for name in E13.CANDIDATES:
            runs[name]['by_year']['2025'] = .1
        self.assertEqual(E13.select(runs), ([], None))

    def test_ablation_rules_and_legacy_k2_are_separate(self):
        k2 = E13.X.rule_layers(M.e8_rules('E8c'), ('AS', 'X1'))
        f1, f2, f4, f5 = (E13.candidate_rules(k2, n) for n in ('F1', 'F2', 'F4', 'F5'))
        self.assertEqual((f1.probe_hard_mult, f2.probe_hard_mult, f5.probe_hard_mult), (2., 0., 1.5))
        self.assertTrue(f1.proof_risk)
        self.assertFalse(f4.proof_risk)
        self.assertTrue(all(r.no_rebuy_day for r in (f1, f2, f4, f5)))
        self.assertEqual(E13.candidate_rules(k2, 'F3').no_rebuy_day, k2.no_rebuy_day)
        self.assertEqual(k2.probe_hard_mult, 0.)


class EvaluationTests(unittest.TestCase):
    def test_labels_merge_same_stock_peak_and_only_count_first_close_reaching_each_fraction(self):
        A = panel(np.r_[np.arange(100., 201., 10.), np.arange(180., 90., -10.)])
        A['codes'] = np.array(['US.X0'])
        trades = [SimpleNamespace(side='long', entry_date=str(A['days'][d]), window_lo='', ticker='X0')
                  for d in (3, 5)]
        picks = {str(A['days'][3]): ['US.X0'], str(A['days'][5]): ['US.X0']}
        with patch.object(M.STUDY, 'trades', return_value=trades):
            result = E13.main_legs(A, picks, ('2024-01-01', '2024-12-31'))
        self.assertEqual((len(result['his']), len(result['pool'])), (1, 1))
        leg = result['his'][0]
        self.assertEqual((leg['trough'], leg['peak']), (str(A['days'][0]), str(A['days'][10])))
        self.assertEqual((leg['third'], leg['midpoint']), (str(A['days'][4]), str(A['days'][5])))

    def test_point_holdings_use_close_after_adds_and_exits_and_ignore_end_marks(self):
        A = panel(np.full(6, 100.))
        ds = list(map(str, A['days']))
        leg = dict(code='X0', low=80., high=120., trough=ds[0], peak=ds[5], year='2024',
                   anchors=[ds[1]], third=ds[3], midpoint=ds[4])
        events = [dict(time=ds[d], action=act, shares=s, price=100.) for d, act, s in
                  ((1, 'entry', .001), (2, 'add', .001), (3, 'trim', .0002), (4, 'stop', .0018), (5, 'end', .1))]
        trade = dict(code='X0', entry=ds[1], fill=100., why='stop', pnl=-.001, risk_budget=.005,
                     confirmed=True, executions=events)
        summary, detail = E13.leg_metrics(A, {'his': [leg]}, [trade], np.ones(6), A['days'])
        self.assertAlmostEqual(detail['his'][0]['third_weight'], .18)
        self.assertEqual(detail['his'][0]['midpoint_weight'], 0.)
        self.assertAlmostEqual(detail['his'][0]['loss_u'], .2)
        self.assertEqual(summary['his']['2024']['third']['held'], 1)
        self.assertEqual(summary['his']['2024']['midpoint']['held'], 0)


class OnceOnlyTests(unittest.TestCase):
    def test_started_marker_is_exclusive_and_never_overwritten(self):
        with TemporaryDirectory() as folder, patch.object(E13, 'WORK', Path(folder)):
            E13.start_once('train', {'first': True})
            with self.assertRaises(FileExistsError):
                E13.start_once('train', {'first': False})
            self.assertEqual(json.loads((Path(folder)/'train_started.json').read_text()), {'first': True})

    def test_training_result_cannot_be_replaced(self):
        with TemporaryDirectory() as folder:
            p = Path(folder)/'train.json'
            p.write_text('{}')
            with patch.object(E13, 'RESULT', p), patch.object(E13, 'setup') as setup:
                with self.assertRaisesRegex(ValueError, 'already recorded'):
                    E13.train()
                setup.assert_not_called()

    def test_nothing_selected_never_loads_or_evaluates_2026(self):
        with TemporaryDirectory() as folder:
            selected, validation = Path(folder)/'selected.json', Path(folder)/'validation.json'
            selected.write_text(json.dumps({'chosen': None}))
            with patch.object(E13, 'SELECTED', selected), patch.object(E13, 'VALIDATION', validation), \
                    patch.object(E13, 'setup') as setup:
                with self.assertRaisesRegex(ValueError, 'must not be tested'):
                    E13.validate()
                setup.assert_not_called()
                self.assertFalse(validation.exists())

    def test_existing_validation_cannot_be_repeated(self):
        with TemporaryDirectory() as folder:
            p = Path(folder)/'validation.json'
            p.write_text('{}')
            with patch.object(E13, 'VALIDATION', p), patch.object(E13, 'setup') as setup:
                with self.assertRaisesRegex(ValueError, 'already recorded'):
                    E13.validate()
                setup.assert_not_called()


if __name__ == '__main__':
    unittest.main()
