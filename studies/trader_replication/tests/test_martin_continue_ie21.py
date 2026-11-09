import ast
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np

from studies.trader_replication import martin_continue_ie21 as m


class IE21Tests(unittest.TestCase):
    def fixture(self, closes=None, opens=None, cap=.25):
        closes = np.array(closes if closes is not None else [100.4] * 8, float)
        opens = np.array(opens if opens is not None else [100.] * len(closes), float)
        n = len(closes)
        days = [str(np.datetime64('2040-01') + np.timedelta64(k, 'D')) for k in range(n)]
        daily = dict(open=opens[:, None], close=closes[:, None],
                     high=np.maximum(opens, closes)[:, None] + .1,
                     low=np.minimum(opens, closes)[:, None] - .1)
        px = {name: np.repeat(a, 2, axis=0) for name, a in daily.items()}
        px['close'][::2] = daily['open']
        px.update(dates=np.repeat(days, 2), codes=np.array(['SYNTHETIC_A']),
                  session=np.repeat(np.arange(n), 2), daily_close=np.tile([False, True], n))
        book = [[] for _ in range(2 * n)]
        book[0] = [(0, 0, 1, 100., 98., 'long', None, None, cap)]
        return SimpleNamespace(days=days, di={s: k for k, s in enumerate(days)},
            codes=['SYNTHETIC_A'], ci={'SYNTHETIC_A': 0}, px=daily,
            f=dict(climax=np.zeros((n, 1))), management={}, phase_px=lambda: px), book

    def simulate(self, cfg, closes=None, opens=None, cap=.25, change=None):
        d, book = self.fixture(closes, opens, cap)
        rules = replace(m.policy(cfg), feedback=0, feedback_opened=False, trail='',
            arm_trail_on_entry=False, add_filter='', management_by_kind={},
            margin_rate=0., buy_cost=0., sell_cost=0.)
        if change:
            change(d, book)
        if cfg['probe']:
            book[0][0] = (*book[0][0][:8], cap / 2)
        track = {}
        curve, dates, trades = m.trial_simulator(cfg)(d.phase_px(), {}, rules, book,
            d.days[0], d.days[-1], audit=True, track=track)
        return d, trades, track, curve

    def test_trial_confirms_at_nth_completed_close_exits_next_open_without_full_capacity(self):
        for n in (2, 3, 5):
            d, trades, track, _ = self.simulate(dict(m.BASE, trial_days=n))
            self.assertEqual(trades[0]['why'], 'trial_open')
            self.assertEqual(trades[0]['exit'], d.days[n])
            self.assertEqual(track['trial_orders'][0]['signal_day'], d.days[n - 1])
            self.assertEqual([e['action'] for e in trades[0]['executions']], ['entry', 'trial_open'])

    def test_equal_threshold_is_kept_and_check_is_not_repeated(self):
        for threshold, level in ((0., 100.), (.5, 101.)):
            _, trades, track, _ = self.simulate(dict(m.BASE, trial_days=2, trial_r=threshold),
                closes=[100.4, level, 100.1, 100.1, 100.1, 100.1, 100.1, 100.1])
            self.assertEqual(track.get('trial_orders', []), [])
            self.assertEqual(trades[0]['why'], 'end')

    def test_only_checking_close_matters_not_an_earlier_high(self):
        _, trades, _, _ = self.simulate(dict(m.BASE, trial_days=2), closes=[101.5, 100.4] + [100.4] * 6)
        self.assertEqual(trades[0]['why'], 'trial_open')

    def test_missing_open_waits_and_gap_stop_has_priority(self):
        cfg = dict(m.BASE, trial_days=2)
        d, trades, _, _ = self.simulate(cfg, opens=[100., 100., np.nan, 100.] + [100.] * 4)
        self.assertEqual(trades[0]['exit'], d.days[3])
        d, trades, _, _ = self.simulate(cfg, opens=[100., 100., 97., 100.] + [100.] * 4)
        self.assertEqual(trades[0]['exit'], d.days[2])
        self.assertEqual(trades[0]['why'], 'gap_stop')

    def test_rejected_add_is_still_a_trial_but_actual_add_is_protected(self):
        cfg = dict(m.BASE, trial_days=2)
        q = SimpleNamespace(side=1, invested=100., size0=1., fill=100., stop0=98., adds=1)
        self.assertIsNotNone(m.trial_decision(q, 2, 100.4, cfg))
        q = SimpleNamespace(side=1, invested=200., size0=1., fill=100., stop0=98.)
        self.assertIsNone(m.trial_decision(q, 2, 100.4, cfg))
        _, trades, track, _ = self.simulate(dict(cfg, probe=True, trial_days=3),
            closes=[102.5, 101.5, 100.4] + [100.4] * 5,
            opens=[100., 103., 101.5] + [100.4] * 5)
        self.assertTrue(any(e['action'] == 'add' for e in trades[0]['executions']))
        self.assertEqual(track.get('trial_orders', []), [])

    def test_probe_is_half_of_risk_sized_initial_position_including_small_cap(self):
        for cap in (.2, .25):
            _, normal, _, _ = self.simulate(m.BASE, cap=cap)
            _, half, _, _ = self.simulate(dict(m.BASE, probe=True), cap=cap)
            self.assertAlmostEqual(half[0]['executions'][0]['shares'], normal[0]['executions'][0]['shares'] / 2)
        rules = m.policy(dict(m.BASE, probe=True, slots=16))
        self.assertEqual((rules.max_open, rules.max_gross, rules.max_position), (16, 2.8, .125))

    def test_probe_add_requires_completed_close_and_qualifying_next_open(self):
        cfg = dict(m.BASE, probe=True)
        def wider_risk(d, book):
            event = book[0][0]
            book[0][0] = (*event[:4], 90., *event[5:])
        d, trades, track, _ = self.simulate(cfg, closes=[110.5] * 8, opens=[100., 111.] + [111.] * 6,
            change=wider_risk)
        executions = trades[0]['executions']
        add = next(e for e in executions if e['action'] == 'add')
        self.assertEqual(add['time'], d.days[1])
        self.assertAlmostEqual(add['shares'], executions[0]['shares'])
        self.assertEqual(track['add_orders'][0]['signal_day'], d.days[0])
        for opening, status in ((102., 'precision_unknown'), (101., 'open_below_level')):
            d, trades, track, _ = self.simulate(cfg, closes=[102.5, 100.5] + [100.5] * 6,
                opens=[100., opening] + [100.5] * 6)
            self.assertFalse(any(e['action'] == 'add' for e in trades[0]['executions']))
            self.assertTrue(any(e['status'] == status for e in track['add_orders']))

    def test_probe_add_keeps_existing_fresh_setup_requirement(self):
        cfg = dict(m.BASE, probe=True)
        d, book = self.fixture(closes=[102.5] * 8, opens=[100., 103.] + [103.] * 6)
        book[0][0] = (*book[0][0][:8], .125)
        rules = replace(m.policy(cfg), feedback=0, feedback_opened=False, trail='',
            management_by_kind={}, arm_trail_on_entry=False)
        fresh = np.zeros((16, 1), bool)
        fresh[3] = True
        track = {}
        _, _, trades = m.trial_simulator(cfg)(d.phase_px(), dict(fresh_setup=fresh), rules,
            book, d.days[0], d.days[-1], audit=True, track=track)
        add = next(e for e in trades[0]['executions'] if e['action'] == 'add')
        self.assertEqual(add['time'], d.days[2])

    def test_future_suffix_cannot_change_completed_trial_decision(self):
        cfg = dict(m.BASE, probe=True, trial_days=2)
        first = self.simulate(cfg)
        second = self.simulate(cfg, closes=[100.4] * 3 + [500.] * 5)
        self.assertEqual(first[1], second[1])
        self.assertEqual(first[2], second[2])

    def test_account_applies_entry_specific_half_cap(self):
        cfg = dict(m.BASE, probe=True)
        d, book = self.fixture(cap=.2)
        d.management['fresh_setup'] = np.zeros((16, 1), bool)
        with patch.object(m, 'build', return_value=dict(book=book)), \
                patch.object(m.old.panels, 'WINDOW', (d.days[0], d.days[-1])):
            account = m.run_account(d, cfg, fresh=True)
        self.assertAlmostEqual(account['trades'][0]['executions'][0]['shares'], .001)

    def test_four_rounds_and_training_only_combinations(self):
        winners = {n: dict(config=m.proposals(i, {})[0]) for i, n in enumerate('AB', 1)}
        for number, count in ((1, 4), (2, 4), (3, 3), (4, 5)):
            self.assertEqual(len(m.proposals(number, winners)), count)
        self.assertEqual(m.proposals(5, winners), [])
        self.assertEqual(m.proposals(4, winners)[0]['trial_days'], winners['A']['config']['trial_days'])

    def test_expiry_releases_the_slot_before_next_open_entries(self):
        cfg = dict(m.BASE, trial_days=2, slots=1)
        d, book = self.fixture()
        px = d.phase_px()
        for name in ('open', 'high', 'low', 'close'):
            px[name] = np.repeat(px[name], 2, axis=1)
        px['codes'] = np.array(['SYNTHETIC_A', 'SYNTHETIC_B'])
        book[4] = [(0, 1, 1, 100., 98., 'long')]
        rules = replace(m.policy(cfg), feedback=0, feedback_opened=False, trail='',
            add_filter='', management_by_kind={}, arm_trail_on_entry=False)
        _, _, trades = m.trial_simulator(cfg)(px, {}, rules, book, d.days[0], d.days[-1], audit=True)
        second = next(t for t in trades if t['code'] == 'SYNTHETIC_B')
        self.assertEqual(second['entry'], d.days[2])
        self.assertEqual(trades[0]['exit'], d.days[2])

    def test_all_execution_candidates_share_one_unchanged_signal_book(self):
        d, sentinel = SimpleNamespace(built={}), {'book': []}
        winners = {n: dict(config=m.proposals(i, {})[0]) for i, n in enumerate('AB', 1)}
        with patch.object(m.previous, 'build', return_value=sentinel) as original:
            for number in range(1, 5):
                for cfg in m.proposals(number, winners):
                    self.assertIs(m.build(d, cfg), sentinel)
            self.assertEqual(original.call_count, 1)

    def test_prior_namespace_and_source_have_no_ledger_constants(self):
        self.assertEqual(m.previous.WORK.name, 'ie20_work')
        self.assertIs(m.previous.engine.run_account, m.previous.run_account)
        labels = m.old.ledger.load(m.old.LEDGER)
        forbidden = {r.ticker for r in labels} | {'US.' + r.ticker for r in labels}
        forbidden |= {r.entry_date for r in labels if r.entry_date}
        for path in (Path(m.__file__), Path(__file__), *m.WORK.glob('*.py')):
            literals = {n.value for n in ast.walk(ast.parse(path.read_text()))
                        if isinstance(n, ast.Constant) and isinstance(n.value, str)}
            self.assertFalse(literals & forbidden, path.name)


if __name__ == '__main__':
    unittest.main()
