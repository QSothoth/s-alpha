"""custody.playbook (runtime) must decide exactly like exec_eval.run_playbook2 (EXEC8 research twin)."""
import random
import unittest
from datetime import timedelta

from custody.evaluate import PRIMARY_FILL
from custody.marketdata import Bar
from custody import playbook
from studies.us_0dte_picks.exec_eval import Path_, _fill_after, _forced_bar, run_playbook2, underlying_series


class PlaybookParityTests(unittest.TestCase):
    def test_runtime_and_research_playbooks_agree_on_random_paths(self):
        from custody.dataset import Case, CaseData
        from custody.tests.helpers import path_bars, session
        s = session()
        rng = random.Random(7)
        checked = 0
        for trial in range(60):
            right = 'C' if trial % 2 else 'P'
            closes, price = [], 600.0
            for _ in range(390):
                price += rng.gauss(0, .25) + (rng.random() < .02) * rng.choice((-2, 2))
                closes.append(price)
            bars = path_bars(closes)
            data = CaseData(Case('US.SPY', 'US.SPY260914%s600000' % right, '2026-09-14',
                                 'LONG' if right == 'C' else 'SHORT', 600.0), s, tuple(bars), ())
            sign = 1 if right == 'C' else -1
            options, opt = {}, 2.0
            for m in range(1, 391):
                opt = max(.05, opt * (1 + rng.gauss(0, .04)))
                if rng.random() < (.3 if trial % 5 == 0 else .9):     # some contracts trade thinly
                    w = opt * rng.random() * .1
                    options[m] = Bar('US.X', s.opens + timedelta(minutes=m), opt, opt + w, opt - w, opt, 10.0)
            research = underlying_series(data)
            runtime = playbook.underlying_series(bars, s, sign)
            for side in ('BUY', 'SELL'):
                for start, length in ((0, 60), (45, 330), (200, 60), (315, 60)):
                    path = Path_(options, side, start, start + length, PRIMARY_FILL)
                    if not path.window:
                        continue
                    arrival = path.window[0][1]
                    m, _, _, trigger = run_playbook2(path, research, arrival, start, trial % 3 == 0)
                    got = playbook.decide(side, runtime, options, start, start + length, arrival, trial % 3 == 0)
                    if got is None:
                        expect = _forced_bar(path)[0], 'forced'
                    else:
                        expect = _fill_after(path, got[0])[0], got[1]
                    self.assertEqual((m, trigger), expect, (trial, side, start, length))
                    checked += 1
        self.assertGreater(checked, 400)

    def test_decide_reads_nothing_after_the_last_completed_minute(self):
        from custody.tests.helpers import path_bars, session
        s = session()
        closes = [600.0] * 60 + [600.5, 601.5, 602.5, 603.5, 603.4] + [603.4] * 325
        series = playbook.underlying_series(path_bars(closes), s, 1)
        options = {m: Bar('US.X', s.opens + timedelta(minutes=m), 1.0, 1.0, 1.0, 1.0, 10.0) for m in range(1, 391)}
        self.assertIsNone(playbook.decide('SELL', series, options, 62, 120, 1.0, False, until=64))
        self.assertEqual(playbook.decide('SELL', series, options, 62, 120, 1.0, False, until=65), (65, 'spike_up'))


if __name__ == '__main__':
    unittest.main()
