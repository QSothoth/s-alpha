"""The generic round loop's pieces: config merging, the choice, behaviour measures and the negation register."""
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from studies.trader_replication import negations as N, study as S


def st(total, med, hits, bought, gap=.5, years=None):
    return dict(total=total, placebo=dict(median=med), fidelity=dict(select=[hits, 10], validate=[0, 5]),
                bought=dict(select=[bought, 10], validate=[0, 5]), behaviour_gap=gap,
                by_year=years or {'2024': total, '2025': total}, min_2024_2025=total)


class ChoiceTests(unittest.TestCase):
    def test_merged_goes_one_level_into_dicts(self):
        base = dict(a=1, rule_opts=dict(risk=.005, trail='e21'))
        self.assertEqual(S.merged(base, dict(rule_opts=dict(trail='sma10'), b=2)),
                         dict(a=1, b=2, rule_opts=dict(risk=.005, trail='sma10')))
        self.assertEqual(base['rule_opts']['trail'], 'e21')

    def test_gates(self):
        ref = st(.5, 0, 3, 2)
        self.assertEqual(S.Study.passes(st(.6, .7, 3, 2), ref, ['placebo', 'hits']), ['placebo'])
        self.assertEqual(S.Study.passes(st(.6, 0, 2, 2), ref, ['placebo', 'hits']), ['hits'])
        self.assertEqual(S.Study.passes(st(.6, 0, 3, 1), ref, ['bought']), ['bought'])
        self.assertEqual(S.Study.passes(st(.6, 0, 3, 2, gap=.6), ref, ['behaviour']), ['behaviour'])
        self.assertEqual(S.Study.passes(st(.6, 0, 3, 2), ref, ['placebo', 'hits', 'bought', 'behaviour']), [])

    def test_scores(self):
        a = st(.5, 0, 3, 2)
        self.assertEqual(S.Study.score(a, 'bought'), (2, .5))
        self.assertEqual(S.Study.score(a, 'hits_select'), (3, .5))
        self.assertEqual(S.Study.score(a, 'min_2024_2025'), .5)
        self.assertEqual(S.Study.score(a, 'behaviour'), -.5)


class BehaviourTests(unittest.TestCase):
    def test_holding_and_weights(self):
        dates = np.array(['2025-01-0%d' % i for i in range(1, 7)])
        curve = np.array([1.0, 1.0, 1.1, 1.1, 1.0, 1.0])
        tr = [dict(entry='2025-01-02', exit='2025-01-05', days=3, ret=.2, executions=[dict(shares=10, price=.02)]),
              dict(entry='2025-01-03', exit='2025-01-04', days=1, ret=-.05, executions=[dict(shares=10, price=.01)])]
        b = S.behaviour(curve, dates, tr)
        self.assertEqual((b['trades'], b['win'], b['days_win'], b['days_loss']), (2, .5, 3.0, 1.0))
        self.assertAlmostEqual(b['entry_weight_mean'], (.2 / 1.0 + .1 / 1.0) / 2)
        self.assertEqual(b['open_max'], 2)

    def test_gap_is_zero_for_his_own_numbers(self):
        his = dict(per_year=400, win=.3, avg_win=.12, avg_loss=-.034, days_win=11, days_loss=2)
        self.assertEqual(S.gap(his, his)[0], 0.0)
        self.assertGreater(S.gap(dict(his, win=.5), his)[0], 0)


class NegationTests(unittest.TestCase):
    def test_stale_only_when_an_untouched_key_changed(self):
        path = Path(tempfile.mkdtemp()) / 'NEGATIONS.json'
        base = dict(exits='X1', rule_opts=dict(trail='sma10', risk=.005), pool='U1')
        N.add(path, dict(round='R3', candidate='C1', change=dict(rule_opts=dict(trail='sma20')), base_config=base,
                         reason='objective'))
        self.assertEqual(N.stale(path, dict(base, rule_opts=dict(trail='sma50', risk=.005))), [])
        rows = N.stale(path, dict(base, pool='U2'))
        self.assertEqual([r['changed'] for r in rows], [['pool']])
        N.add(path, dict(round='R3', candidate='C1', change={}, base_config=base, reason='again'))
        self.assertEqual(len(json.loads(path.read_text())), 1)
        self.assertTrue(N.render(path, 'X').exists())


if __name__ == '__main__':
    unittest.main()
