"""M1 structural confirmation, causal watches, FIFO shorts and frozen selection gates."""
import unittest
from unittest.mock import patch
from dataclasses import asdict
import json
from pathlib import Path
import tempfile

import numpy as np

from studies.martin_luk import m1_research as M
from studies.trader_replication import system as Y
from studies.trader_replication.study import Study


class M1Tests(unittest.TestCase):
    def test_generic_study_supplies_the_optional_confirmation_array(self):
        signal = np.array([[False], [True]])
        r = Y.Rules(trail='', proof_confirm_signal='structure')
        self.assertIs(Study().ema_inputs({'structure': signal}, None, r)['structure'], signal)

    def test_structural_confirmation_waits_and_still_requires_profit(self):
        bars = np.array([[100, 100, 100, 100], [100, 103, 98, 102],
                         [102, 104, 101, 103], [103, 105, 102, 104]], float)
        px = {k: bars[:, i:i+1] for i, k in enumerate(('open', 'high', 'low', 'close'))}
        days = np.array(['2025-01-02', '2025-01-03', '2025-01-06', '2025-01-07'])
        px.update(dates=days, codes=np.array(['X']))
        entries = [[((0, 0, 'X'), 0, 1, 100., 97., 'probe', None)], [], [], []]
        opts = dict(risk=.0025, max_position=.5, max_gross=2.8, trail='', trims=(),
                    buy_cost=0, sell_cost=0, margin_rate=0, probe_hard_mult=2., proof_risk=True,
                    proof_stop='fill', proof_add_max=0)
        def replay(signal):
            rules = Y.Rules(**opts, proof_confirm_signal=signal)
            return Y.simulate(px, {'structure': np.array([[True], [False], [True], [True]])}, rules,
                              entries, days[0], days[-1], audit=True)[2][0]
        self.assertEqual(replay('structure')['confirmed_day'], days[2])
        self.assertEqual(replay('')['confirmed_day'], days[1])
        self.assertEqual(Y.Rules().proof_confirm_signal, '')
        bars[2:, 3] = 99
        self.assertFalse(replay('structure')['confirmed'])

    def test_watches_match_original_without_optional_mechanisms(self):
        n = 12
        c = np.full((n, 1), 100., np.float32)
        c[4] = 103
        A = dict(days=np.array([f'2025-01-{i+1:02d}' for i in range(n)]), codes=['X'], close=c,
                 open=c.copy(), high=c+1, low=c-2, adr=np.full((n, 1), 6.),
                 e9=np.full((n, 1), 100.), e21=np.full((n, 1), 99.))
        picks = {str(A['days'][1]): ['X']}
        expected = M.M.entry_book(A, picks, **M.M.E6['E6c'])[0]
        self.assertEqual(M.watch_book(A, picks), expected)
        # Actual close fills, with management starting on the following session.
        self.assertEqual(expected[4][0][3], float(c[4, 0]))
        A['close'][8:] *= 3
        self.assertEqual(M.watch_book(A, picks)[:8], expected[:8])

    def test_e10_cross_does_not_require_close_above_previous_high(self):
        c = np.array([[100.], [100.], [99.]])
        A = dict(days=['2025-01-01', '2025-01-02', '2025-01-03'], codes=['X'], close=c,
                 open=c, high=np.array([[102.], [103.], [101.]]), low=np.full((3, 1), 98.),
                 adr=np.full((3, 1), 6.), e9=np.full((3, 1), 100.), e21=np.full((3, 1), 98.))
        picks = {'2025-01-02': ['X']}
        self.assertFalse(any(M.watch_book(A, picks)))
        book = M.watch_book(A, picks, trigger='e10')
        self.assertEqual(book[2][0][3], 99.)

    def test_short_fifo_is_other_business_and_reconciles_with_fees(self):
        rules = Y.Rules(buy_cost=.001, sell_cost=.002)
        trades = [dict(side=-1, code='X', entry='2025-01-01', why='stop', pnl=.1-.002-.0009,
                       executions=[dict(time='2025-01-01', action='entry', shares=.01, price=100.),
                                   dict(time='2025-01-02', action='stop', shares=.01, price=90.)])]
        normalized, residual = M.adapt(trades, ['2025-01-01', '2025-01-02'], rules)
        self.assertLess(residual, 1e-12)
        self.assertEqual(normalized[0]['code'], 'SHORT:X')
        self.assertAlmostEqual(sum(r['pnl'] for r in normalized[0]['lots']), trades[0]['pnl'])
        borrowed = Y.Rules(buy_cost=.001, sell_cost=.002, borrow_rate=.03)
        prices = {'X': {'c': np.array([100., 90.])}}
        fee = .03/252*.01*100
        trades[0]['pnl'] -= fee
        normalized, residual = M.adapt(trades, ['2025-01-01', '2025-01-02'], borrowed, prices)
        self.assertLess(residual, 1e-12)
        self.assertAlmostEqual(normalized[0]['lots'][0]['borrow_fee'], fee)

    def test_joint_queue_uses_structure_before_path_rank_and_never_held_labels(self):
        A = dict(codes=['A', 'B'], close=np.full((2, 2), 100.), e9=np.full((2, 2), 100.),
                 e21=np.full((2, 2), 99.), adr=np.full((2, 2), 6.), to20=np.full((2, 2), 1e8),
                 m1_proof=np.array([[False, False], [False, True]]))
        row = [((0, 0, 'A'), 0, 1, 100., 97., 'ie', None),
               ((9, 0, 'B'), 1, 1, 100., 97., 'master_close', None)]
        ordered = M.queue_book(A, [[], row], structural=True)[1]
        self.assertEqual([e[1] for e in sorted(ordered, key=lambda e: e[0])], [1, 0])
        self.assertEqual(len(M.merge_books([[], row[:1]], [[], row])[1]), 2)

    def test_r74_execution_really_opens_fifty_percent_without_the_probe_cap(self):
        days = np.array(['2025-01-02', '2025-01-03'])
        c = np.full((2, 1), 100.)
        A = dict(days=days, codes=np.array(['X']), close=c, open=c, high=c+1, low=c-1,
                 adr=np.full_like(c, 6.), e9=c, e21=c, ie_pool=np.ones_like(c, bool))
        A['_e14_signals'] = {n: np.zeros_like(c, bool) for n in ('e13_retry', 'e14_high', 'e14_reclaim')}
        native = Y.Rules(risk=.008, max_position=.5, max_gross=2.8, trail='', trims=(),
                         buy_cost=0, sell_cost=0, margin_rate=0)
        with tempfile.TemporaryDirectory() as directory:
            p = Path(directory)
            (p/'master_capped.json').write_text(json.dumps([[[-1e8, 0, 1, 100., 99., 'n1']], []]))
            (p/'master_rules.json').write_text(json.dumps(asdict(native)))
            book, rules, ema = M.build(A, p, dict(basis='master', execution='R74'))
        px = dict(dates=days, **{n: A[n] for n in ('open', 'high', 'low', 'close', 'codes')})
        t = Y.simulate(px, ema, rules, book, days[0], days[-1], audit=True)[2][0]
        first = t['executions'][0]
        self.assertAlmostEqual(first['shares']*first['price'], .5)

    def test_qualification_uses_both_years_and_H_and_capital(self):
        def run(h=2., cap=.2, n=52, win=True):
            return dict(H=h, cap_equity=cap, years={y: dict(target_count=1, cap_equity=cap,
                purity_gross=.3, targets=dict(checks=dict(trades=n >= 52, win=win))) for y in ('2024', '2025')})
        baseline = run()
        runs = dict(ok=run(), low_H=run(h=1.), low_cap=run(cap=.1), low_n=run(n=51), high_win=run(win=False))
        result = M.select(runs, baseline)
        self.assertEqual(result['eligible'], ['ok'])
        self.assertEqual(result['failures']['low_H'], ['H'])
        self.assertIn('2025_win', result['failures']['high_win'])

    def test_truncated_evaluation_keeps_all_available_anchors(self):
        days = np.array(['2024-01-02', '2024-01-03', '2024-01-04'])
        A = dict(days=days, codes=['X'], close=np.full((3, 1), 10.))
        available = dict(key='X:0:2', code='X', first=0, peak=2, top=20., gain=1.,
                         entries=[dict(index=0, gain=1.)])
        future = dict(available, key='X:4:5', first=4, peak=5, entries=[dict(index=4, gain=1.)])
        frozen = dict(calendar=list(days)+['2024-01-05', '2024-01-08', '2024-01-09'],
                      legs=[available, future], other_legs=[], audit=[])
        with patch.object(M, 'read', return_value=frozen):
            result = M.measure(A, [], np.ones(3), days, Y.Rules(), (str(days[0]), str(days[-1])))
        self.assertEqual(len(result['legs']), 1)
        self.assertEqual(result['years']['2024']['coverage']['including_censored']['n'], 1)


if __name__ == '__main__':
    unittest.main()
