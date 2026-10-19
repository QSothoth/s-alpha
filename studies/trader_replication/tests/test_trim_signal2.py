"""The second signal trim (Kell: half off at the first close below the 10 EMA, the rest on the 20 EMA): once per
position, at the first close the signal is true."""
import unittest

import numpy as np

from studies.trader_replication import system as Y

DATES = np.array([f'2025-01-{d:02d}' for d in range(2, 9)])
RULES = dict(buy_cost=0, sell_cost=0, margin_rate=0, trail='', trims=(), risk=.01, max_position=10.0, max_gross=10.0)
C = np.array([10, 10.5, 11, 10.8, 10.6, 10.9, 11.2])
PX = {'open': C[:, None], 'high': C[:, None] + .1, 'low': C[:, None] - .1, 'close': C[:, None], 'dates': DATES,
      'codes': np.array(['US.A'])}
SIG = np.zeros((7, 1), bool)
SIG[3:5, 0] = True                                      # true on days 3 and 4


def run(**kw):
    e = [[] for _ in DATES]
    e[0].append((0, 0, 1, 10.0, 9.0, 'a'))
    _, _, tr = Y.simulate(PX, {'sig': SIG}, Y.Rules(**{**RULES, **kw}), e, DATES[0], DATES[-1], audit=True)
    return tr


class TrimSignal2Tests(unittest.TestCase):
    def test_off_by_default(self):
        (t,) = run()
        self.assertEqual([x['action'] for x in t['executions']], ['entry', 'end'])

    def test_once_at_the_first_true_close(self):
        (t,) = run(trim_signal2='sig', trim_signal2_frac=.5)
        ex = [x for x in t['executions'] if x['action'] == 'signal_trim2']
        self.assertEqual(len(ex), 1)
        self.assertEqual(ex[0]['time'], '2025-01-05')
        self.assertAlmostEqual(ex[0]['price'], 10.8)


if __name__ == '__main__':
    unittest.main()
