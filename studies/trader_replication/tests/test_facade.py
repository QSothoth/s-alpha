"""A dummy trader fills only the public facade; execution uses the real engine."""
import json
import unittest
from pathlib import Path
import tempfile

import numpy as np

from studies.trader_replication import allocation, gate, study, system, shorts, pipeline
from studies.trader_replication.config import Config


class Dummy(study.Study):
    def __init__(self):
        c = np.tile([10., 20., 30.], (90, 1))
        self.A = dict(days=np.array([str(np.datetime64('2024-01-01')+i) for i in range(90)]),
            codes=np.array(['A', 'B', 'C']), close=c, open=c, high=c*1.02, low=c*.98,
            has=np.ones(c.shape, bool), adr=np.tile([3., 5., 4.], (90, 1)), to20=c*2e6, market='us')

    def arrays(self, market, upto=None):
        k = len(self.A['days']) if upto is None else np.searchsorted(self.A['days'], upto, side='right')
        return {key: value[:k] if isinstance(value, np.ndarray) and key != 'codes' else value
                for key, value in self.A.items()}

    def universe(self, A, cfg):
        return np.ones(A['close'].shape, bool)

    def signal(self, A, pool, cfg):
        return {t: [str(A['codes'][j]) for j in sorted(np.flatnonzero(pool[t]),
                  key=lambda j: -A['adr'][t, j])] if t % 3 == 0 else [] for t in range(len(A['days']))}

    def trade(self, cfg):
        return system.Rules(risk=.005, max_days=2, trail='', trims=(), intraday_kinds=('signal',))


class FacadeTests(unittest.TestCase):
    def test_dummy_runs_full_facade_and_engine(self):
        st, cfg = Dummy(), dict(allocate=dict(max_new=1, cooldown=10, max_open=1))
        A, trace = st.arrays('us'), {}
        entries, rules, mask, pool = st.build(A, cfg, trace)
        self.assertFalse(st.legacy)
        self.assertEqual(trace['picks'][0], ['B', 'C', 'A'])
        self.assertEqual(trace['picks'][1], [])
        self.assertEqual(len(trace['picks']), len(A['days']))
        self.assertTrue(mask[0, 1])
        self.assertEqual(entries[0], [])
        curve, dates, trades = system.simulate(st.px(A), st.ema_inputs(A, pool, rules), rules,
            entries, str(A['days'][0]), str(A['days'][-1]), audit=True)
        self.assertTrue(trades)
        self.assertEqual(trades[0]['code'], 'B')
        self.assertEqual(trades[0]['entry'], str(A['days'][1]))
        self.assertTrue(gate.check_fills(A, trades)['ok'])
        self.assertTrue(gate.check_lookahead(st, cfg, 'us', full=A, cuts=(str(A['days'][40]),))['ok'])

    def test_config_aliases_are_read_only_and_sections_round_trip(self):
        cfg = Config(dict(risk=.005, max_new=4, pool='U0'))
        self.assertEqual(cfg['risk'], cfg['trade']['risk'])
        self.assertEqual(cfg['max_new'], cfg['allocate']['max_new'])
        self.assertEqual(Config(cfg).flat(), dict(risk=.005, max_new=4, pool='U0'))
        with self.assertRaises(TypeError):
            cfg['risk'] = .01
        with self.assertRaises(TypeError):
            cfg['trade']['risk'] = .01
        with self.assertRaises(ValueError):
            Config(dict(risk=.01, trade=dict(risk=.02)))

    def test_sections_can_have_independent_parameters_with_the_same_name(self):
        cfg = Config(dict(signal=dict(length=20), trade=dict(length=10)))
        self.assertEqual(cfg['signal']['length'], 20)
        self.assertEqual(cfg['trade']['length'], 10)
        self.assertEqual(Config(cfg)['trade']['length'], 10)
        with self.assertRaises(KeyError):
            _ = cfg['length']
        with self.assertRaises(ValueError):
            cfg.flat()

    def test_budget_cooldown_includes_empty_and_cross_year_nights(self):
        picks = {0: ['A', 'B'], 1: ['A', 'B'], 5: [], 10: ['A'], 11: ['A']}
        self.assertEqual(allocation.nominations(picks, 1), {0: ['A'], 1: ['B'], 5: [], 10: [], 11: ['A']})

    def test_successful_fill_cap_can_skip_a_held_name(self):
        A = Dummy().arrays('us')
        entries = [[] for _ in A['days']]
        entries[1] = [(0, 0, 1, 10., 9., 'x')]
        entries[2] = [(0, 0, 1, 10., 9., 'x'), (1, 1, 1, 20., 18., 'x')]
        rules = allocation.policy(system.Rules(trail='', trims=()), dict(max_new=1, daily_cap='fills'))
        _, _, trades = system.simulate(dict(Dummy().px(A)), {}, rules, entries, A['days'][0], A['days'][-1])
        self.assertEqual([t['code'] for t in trades], ['A', 'B'])
        capped = allocation.offers(entries, 1)
        _, _, trades = system.simulate(Dummy().px(A), {}, rules, capped, A['days'][0], A['days'][-1])
        self.assertEqual([t['code'] for t in trades], ['A'])

    def test_regime_reaches_named_lookahead_inputs(self):
        st = Dummy()
        cfg = dict(allocate=dict(max_new=1), switch=dict(spec=dict(producer='idx_ema')))
        A = st.arrays('us')
        _, _, arrays, _, _ = gate.decisions(st, A, cfg, 40)
        self.assertIn('regime', arrays)
        self.assertEqual(len(arrays['regime']), 41)

    def test_overridden_build_is_legacy(self):
        class Old(Dummy):
            def build(self, A, cfg, trace=None):
                return super().build(A, cfg, trace)
        self.assertTrue(Old().legacy)

    def test_sourced_state_controls_size_and_slots_without_reordering(self):
        st = Dummy()
        with tempfile.TemporaryDirectory() as directory:
            st.root = Path(directory)
            (st.root/'notes').mkdir()
            (st.root/'notes/RULES_CN.md').write_text('reduce risk; hold fewer names')
            cfg = dict(allocate=dict(max_new=3, cooldown=0), switch=dict(spec=dict(producer='idx_ema'),
                controls=[dict(field='risk_mult', quote='reduce risk', values=dict(up=1., pullback=.5, weak=.25)),
                          dict(field='max_open', quote='hold fewer names', values=dict(up=2, pullback=1, weak=1))]))
            A, trace = st.arrays('us'), {}
            book, rules, _, pool = st.build(A, cfg, trace)
            self.assertEqual(trace['picks'][0], ['B', 'C', 'A'])
            self.assertEqual([e[1] for e in book[1]], [1, 2, 0])
            self.assertEqual(book[1][0][9], .5)
            _, _, trades = system.simulate(st.px(A), st.ema_inputs(A, pool, rules), rules,
                                           book, A['days'][0], A['days'][-1], audit=True)
            self.assertEqual({t['code'] for t in trades}, {'B'})
            self.assertTrue(gate.check_lookahead(st, cfg, 'us', full=A, cuts=(A['days'][40],))['ok'])

    def test_sectioned_short_side_obeys_the_same_direction_switch(self):
        class Both(Dummy):
            def short_setups(self, A, sc):
                pool = np.ones(A['close'].shape, bool)
                return dict(x=pool), pool
        with tempfile.TemporaryDirectory() as directory:
            base = Both()
            base.root = Path(directory)
            (base.root/'notes').mkdir()
            (base.root/'notes/RULES_CN.md').write_text('trade permitted directions')
            control = dict(field='sides', quote='trade permitted directions',
                           values=dict(up=[], pullback=[], weak=[]))
            cfg = dict(trade=dict(short=dict(max_new=1)), switch=dict(spec={}, controls=[control]))
            wrapped = shorts.wrap(base)
            book, _, _, _ = wrapped.build(base.arrays('us'), cfg)
            self.assertFalse(any(book))
            control['values'] = dict(up=[-1], pullback=[-1], weak=[-1])
            book, _, _, _ = wrapped.build(base.arrays('us'), cfg)
            self.assertTrue(any(book))
            self.assertEqual({e[2] for row in book for e in row}, {-1})

    def test_round_rejects_downstream_change_before_loading_market(self):
        class Guarded(Dummy):
            def arrays(self, *args, **kwargs):
                raise AssertionError('blocked round must not load market data')
        with tempfile.TemporaryDirectory() as directory:
            st = Guarded()
            st.root = Path(directory)
            st.rounds.mkdir(parents=True)
            st.reports.mkdir()
            gates = {k: pipeline.result('pass', 'test') for k in ('G0', 'G1', 'G2')}
            gates['G3'] = pipeline.result('fail', 'coverage below 80%')
            (st.reports/'pipeline.json').write_text(json.dumps(gates))
            spec = dict(base=['', 'base'], ref='BASE', layer='trade', sections_changed=['trade'],
                        upper_bound=1., pipeline='reports/pipeline.json', candidates=dict(A=dict(trade=dict(risk=.01))))
            (st.rounds/'BLOCKED.json').write_text(json.dumps(spec))
            with self.assertRaisesRegex(ValueError, 'upstream gate'):
                st.round('BLOCKED')


if __name__ == '__main__':
    unittest.main()
