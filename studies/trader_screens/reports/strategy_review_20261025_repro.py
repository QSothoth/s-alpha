"""Characterize reviewed defects on synthetic unit fixtures, not expected post-fix behavior."""
import json
import subprocess
import unittest
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from studies.trader_replication import system as Y, shorts as SH, systems
from studies.trader_replication.tests.test_shorts import arrays
from studies.trader_replication.tests.test_system import px, one


class ReviewRepros(unittest.TestCase):
    def test_open_short_size_reads_later_close_of_existing_position(self):
        sizes = []
        for later_close in (100., 200.):
            p = dict(open=np.array([[100., 10.], [100., 10.]]),
                     high=np.array([[101., 10.5], [200., 10.5]]),
                     low=np.array([[90., 9.5], [90., 9.5]]),
                     close=np.array([[100., 10.], [later_close, 10.]]),
                     dates=np.array(['2025-01-02', '2025-01-03']), codes=np.array(['US.A', 'US.B']))
            a = dict(p, days=p['dates'], adr=np.full((2, 2), 20.), to20=np.full((2, 2), 1e8))
            armed = np.array([[False, False], [False, True]])
            entries = SH.short_entries(a, {'ptop': dict(armed=armed, at_open=True)}, {'stop_w': .1})
            entries[0].append((0., 0, 1, 100., 50., 'long'))
            r = Y.Rules(risk=.1, max_position=2., max_gross=5., trail='', trims=(),
                        buy_cost=0, sell_cost=0, margin_rate=0)
            _, _, tr = Y.simulate(p, {}, r, entries, p['dates'][0], p['dates'][-1], audit=True)
            sizes.append(next(t for t in tr if t['side'] < 0)['executions'][0]['shares'])
        print('Opening short shares with identical information at open:', sizes)
        self.assertNotAlmostEqual(*sizes)

    def test_open_short_uses_slot_released_at_close(self):
        p = dict(open=np.array([[100., 10.], [100., 10.]]),
                 high=np.array([[101., 10.5], [101., 10.5]]),
                 low=np.array([[90., 9.5], [90., 9.5]]),
                 close=np.array([[100., 10.], [100., 10.]]),
                 dates=np.array(['2025-01-02', '2025-01-03']), codes=np.array(['US.A', 'US.B']))
        a = dict(p, days=p['dates'], adr=np.full((2, 2), 20.), to20=np.full((2, 2), 1e8))
        armed = np.array([[False, False], [False, True]])
        e = SH.short_entries(a, {'ptop': dict(armed=armed, at_open=True)}, {'stop_w': .1})
        e[0].append((0., 0, 1, 100., 50., 'long'))
        r = Y.Rules(max_open=1, max_days=1, trail='', trims=(), buy_cost=0, sell_cost=0, margin_rate=0)
        _, _, tr = Y.simulate(p, {}, r, e, p['dates'][0], p['dates'][-1], audit=True)
        self.assertEqual(len(tr), 2)
        self.assertEqual(tr[0]['why'], 'time')
        self.assertEqual(tr[1]['side'], -1)
        print('Opening short admitted before the existing long exits at close:', tr[1]['entry'])

    def test_active_extension_trim_repeats_until_position_is_gone(self):
        p = px([(100, 101, 99, 100), (140, 141, 139, 140), (141, 142, 140, 141),
                (142, 143, 141, 142), (143, 144, 142, 143)])
        for sid in ('clement_ang', 'oliver_kell'):
            opts = systems.get(sid).config['rule_opts']
            opts = {k: tuple(v) if isinstance(v, list) else v for k, v in opts.items()}
            r = replace(Y.Rules(), **opts, buy_cost=0, sell_cost=0, margin_rate=0)
            ema = {r.trail: np.full((5, 1), 90.), r.trim_signal: np.array([[False], [True], [True], [True], [True]])}
            _, _, tr = Y.simulate(p, ema, r, one(5, 0, 1, 100., 99.), p['dates'][0], p['dates'][-1], audit=True)
            actions = [(x['time'], x['action']) for x in tr[0]['executions']]
            print(sid, 'consecutive extension closes:', actions)
            self.assertGreater(sum(a == 'signal_trim' for _, a in actions), 1)
            self.assertEqual(tr[0]['why'], 'signal_trim')

    def test_same_name_placebo_changes_short_fill_time(self):
        a = arrays([(10, 10.1, 9.9, 10), (10, 10.1, 8, 8)])
        p = {k: a[k] for k in ('open', 'high', 'low', 'close', 'codes')}
        p['dates'] = a['days']
        e = SH.short_entries(a, {'ptop': dict(armed=np.array([[False], [True]]), at_open=True)}, {'stop_w': .1})
        r = Y.Rules(trail='', trims=(), buy_cost=0, sell_cost=0, margin_rate=0)
        real = Y.simulate(p, {}, r, e, a['days'][0], a['days'][-1])[0][-1]
        control = Y.simulate(p, {}, r, e, a['days'][0], a['days'][-1],
                             placebo=np.random.default_rng(1), pool=np.ones((2, 1), bool))[0][-1]
        print('Same name, same signal, actual opening short versus placebo close:', real, control)
        self.assertGreater(real, control)

    def test_limit_up_skipped_label_keeps_simulated_holding(self):
        from studies.trader_screens import scan
        from studies.trader_screens.tests.test_screens import panel
        from studies.trader_replication import study
        p = panel([10.] * 79 + [11.])
        p['codes'] = np.array(['SH.600000'])
        p['digest'] = 'synthetic-review-unit-case'
        a = dict(p, market='cn')
        class Toy(study.Study):
            def arrays(self, *args, **kwargs):
                return a
            def build(self, A, cfg, trace=None):
                e = [[] for _ in A['days']]
                e[-1] = [(0., 0, 1, 11., 10.8, 'brk')]
                return e, Y.Rules(trail='', trims=()), np.zeros((80, 1), bool), np.ones((80, 1), bool)
        sys_ = SimpleNamespace(id='review_toy', study=Toy(), config={}, name='Review', version='test',
                               status='research', label='test', freeze=str(p['days'][0]), strategy={})
        ds = SimpleNamespace(id='synthetic-review-unit-case', names=lambda: {'SH.600000': 'Test'})
        with patch.object(scan.data, 'industries', return_value={}), \
             patch('studies.trader_data.dataset', return_value=ds), \
             patch.object(systems, 'all_', return_value=[sys_]):
            result = scan.run('cn', panel=p)
        t = result['traders'][0]
        self.assertTrue(t['buys'][0]['limit_up'])
        self.assertEqual(t['holdings'][0]['code'], 'SH.600000')
        self.assertGreater(t['account']['exposure'], 0)
        print('Limit-up marked skipped but remains held:', t['holdings'][0]['code'], t['account']['exposure'])


if __name__ == '__main__':
    print(json.dumps(dict(commit=subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip(),
                          numpy=np.__version__, fixture='synthetic unit cases'), sort_keys=True), flush=True)
    unittest.main(verbosity=2)
