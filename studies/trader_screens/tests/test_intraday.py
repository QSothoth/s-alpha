"""The provisional (intraday) board on synthetic folders and a fake provider: only the stored sessions plus one
snapshot reach the systems, nothing is stored, every refusal, the in-memory append equals a full rebuild, the
A-share limit-up skip and the diff classes."""
import tempfile
import csv
import gzip
import contextlib
import io
import unittest
from pathlib import Path
from unittest import mock
from types import SimpleNamespace

import numpy as np

import studies.trader_data as TD
from studies.trader_data import panel as TP
from studies.trader_data.tests.test_trader_data import CODES, DAYS, SESS, Fake, ny, snap, write_folder
from studies.trader_screens import intraday as I

TODAY = '2026-10-19'                        # the session after DAYS[-1]
LAST = {c: 10.0 + j + 3 for j, c in enumerate(CODES)}  # write_folder's closes on DAYS[-1]


def calendar(types=None):
    return lambda s, e: {d: (types or {}).get(d, 'WHOLE') for d in SESS if s <= d <= e}


def quote(close, prev, when=f'{TODAY} 15:49:30', vol=1000):
    return dict(snap(close, prev, vol), time=when)


def fake_board(seen):
    def board(market, mode, days, only, panel=None, seconds=None):
        seen.append(panel)
        last = str(panel['days'][-1])
        return dict(market=market, last_day=last, traders=[dict(id='x', name='X', buys=[
            dict(code='US.A', side=1, setup='brk', price=float(panel['close'][-1, 0]), stop=1.0, weight=.1)],
            sells=[], holdings=[], wanted=[])])
    return board


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        write_folder(self.root / 'data' / 'trader-data-v1')
        self.patches = [mock.patch.object(TP, 'CACHE', self.root / 'cache'),
                        mock.patch.object(TD, 'ROOT', self.root), mock.patch.object(TD, 'LIVE_ROOT', self.root / 'live')]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def run_at(self, when, quotes=None, cal=None):
        quotes = quotes if quotes is not None else {c: quote(LAST[c] + 1, LAST[c]) for c in CODES}
        self.fake, self.seen = Fake(SESS, snap=quotes), []
        return I.run('us', now=when, provider=self.fake, calendar=cal or calendar(), board=fake_board(self.seen),
                     log=lambda *_: None)

    def files(self):
        return sorted(str(p.relative_to(self.root)) for p in self.root.rglob('*') if p.is_file())


class ProvisionalTests(Base):
    def test_order_table_distinguishes_signal_fill_from_snapshot_quote(self):
        from studies.trader_screens import board
        result = self.run_at(ny(TODAY, 15, 50))
        buy = result['traders'][0]['buys'][0]
        self.assertEqual(buy['snapshot_price'], LAST['US.A'] + 1)
        buy['price'] = 12.
        text = '\n'.join(board.orders(result))
        self.assertIn('信号价 | 快照价', text)
        self.assertIn(f"12.00 | {buy['snapshot_price']:.2f}", text)

    def test_scan_shares_one_snapshot_with_all_seven_registered_systems(self):
        from studies.trader_replication import panels, runner, systems
        from studies.trader_screens import scan
        seen = []
        def replay(system, market, mode, days):
            p = panels.load(market, mode=mode)
            seen.append((system.id, p['close'].copy()))
            return dict(id=system.id, name=system.id, last_day=str(p['days'][-1]),
                        buys=[], sells=[], holdings=[], wanted=[])
        quotes = {c: quote(LAST[c] + 1, LAST[c]) for c in CODES}
        provider = Fake(SESS, snap=quotes)
        before = self.files()
        with mock.patch.object(runner, 'run', side_effect=replay), mock.patch.object(scan.data, 'industries', return_value={}):
            result = I.run('us', now=ny(TODAY, 15, 50), provider=provider, calendar=calendar(),
                           board=scan.run, log=lambda *_: None)
        stock = {s.id for s in systems.board('us') if not s.board_run}     # Holguin sells at the open: not provisional
        self.assertEqual({sid for sid, _ in seen}, stock)
        self.assertEqual(len(result['traders']), len(stock))
        self.assertEqual(provider.calls, ['snapshot'])
        self.assertEqual(self.files(), before)
        for _, values in seen:
            np.testing.assert_array_equal(values, seen[0][1])

    def test_systems_see_the_stored_sessions_and_the_snapshot_only(self):
        before = self.files()
        r = self.run_at(ny(TODAY, 15, 50))
        self.assertEqual(self.files(), before)                       # cold cache is read-only too
        p = self.seen[0]
        self.assertEqual([str(d) for d in p['days']], list(DAYS) + [TODAY])
        np.testing.assert_allclose(p['close'][-1], [LAST[c] + 1 for c in CODES])
        np.testing.assert_allclose(p['close'][:-1], TD.dataset('us', 'live').panel()['close'])
        self.assertEqual(r['last_day'], TODAY)
        self.assertEqual(r['provisional']['hhmm'], '1550')
        self.assertEqual(self.fake.calls, ['snapshot'])              # once, shared by every system, no history
        new = [f for f in self.files() if f not in before]
        self.assertFalse([f for f in new if not f.startswith('cache/')])   # nothing in the data, nothing out
        self.assertFalse((self.root / 'live').exists())

    def test_refused_outside_the_session(self):
        for when in (ny(TODAY, 9, 20), ny(TODAY, 16, 0), ny(TODAY, 17), ny('2026-10-18', 12)):
            with self.subTest(when=when), self.assertRaises(I.Refused):
                self.run_at(when)

    def test_refused_after_a_half_day_close(self):
        with self.assertRaises(I.Refused):
            self.run_at(ny(TODAY, 13, 30), cal=calendar({TODAY: 'MORNING'}))
        self.run_at(ny(TODAY, 12, 50),
                    quotes={c: quote(LAST[c] + 1, LAST[c], when=f'{TODAY} 12:49:30') for c in CODES},
                    cal=calendar({TODAY: 'MORNING'}))

    def test_afternoon_only_session_has_not_opened_in_the_morning(self):
        with self.assertRaisesRegex(I.Refused, 'has not opened'):
            I.session('hk', DAYS[-1], ny(TODAY, 0), calendar({'2026-10-19': 'AFTERNOON'}))

    def test_refused_when_the_stored_data_is_not_the_previous_session(self):
        with self.assertRaises(I.Refused):                         # 2026-10-19 missing: refresh first
            self.run_at(ny('2026-10-20', 15, 50))

    def test_refused_when_the_snapshot_is_of_another_day(self):
        old = {c: quote(LAST[c] + 1, LAST[c], when='2026-10-16 16:00:00') for c in CODES}
        with self.assertRaises(I.Refused):
            self.run_at(ny(TODAY, 15, 50), old)

    def test_refused_when_previous_closes_do_not_match(self):
        bad = {c: quote(LAST[c] + 1, LAST[c] * 1.3) for c in CODES}
        with self.assertRaises(I.Refused):
            self.run_at(ny(TODAY, 15, 50), bad)

    def test_future_or_missing_opend_quote_times_are_refused(self):
        for when in (f'{TODAY} 15:50:01', f'{TODAY} 23:00:00', '15:49:30', ''):
            with self.subTest(time=when), self.assertRaises(I.Refused):
                self.run_at(ny(TODAY, 15, 50), {c: quote(LAST[c] + 1, LAST[c], when=when) for c in CODES})

    def test_snapshot_completion_and_system_completion_must_precede_close(self):
        def clock_run(values):
            with mock.patch.object(I, 'market_now', side_effect=values), self.assertRaises(I.Refused):
                self.run_at(None)
        clock_run([ny(TODAY, 15, 59), ny(TODAY, 16)])
        clock_run([ny(TODAY, 15, 59), ny(TODAY, 15, 59), ny(TODAY, 15, 59), ny(TODAY, 16)])

    def test_minor_wrong_day_quotes_are_quarantined(self):
        codes = [f'US.T{i}' for i in range(20)]
        quotes = {c: quote(10, 10) for c in codes}
        quotes[codes[0]]['time'] = '2026-10-16 16:00:00'
        check = I.check_time('us', quotes, TODAY, now=ny(TODAY, 15, 50))
        self.assertEqual(check['rejected_times'], codes[:1])
        self.assertEqual(check['quotes_on_day'], [19, 20])
        quotes['US.HALT'] = dict(quote(10, 10), trading=False, time='2026-10-16 16:00:00')  # suspended: not a bad quote
        self.assertEqual(I.check_time('us', quotes, TODAY, now=ny(TODAY, 15, 50))['rejected_times'], codes[:1])

    def test_read_only_industry_lookup_does_not_write_seed_cache(self):
        from studies.trader_screens import data
        seed = self.root / 'data' / 'martin-luk-cache' / 'industry.json'
        seed.parent.mkdir(parents=True)
        seed.write_text('{"US.A": "Technology"}')
        with mock.patch.object(data, 'ROOT', self.root), mock.patch.object(data, 'CACHE', self.root / 'industry-cache'):
            self.assertEqual(data.industries(['US.A'], 'us'), {'US.A': 'Technology'})
        self.assertFalse((self.root / 'industry-cache').exists())

    def test_sina_tick_time_must_be_recent(self):
        fresh = {'US.A': dict(trading=True, time='15:45:00')}
        I.check_time('cn', fresh, TODAY, now=ny(TODAY, 3, 50))     # 15:50 Shanghai
        with self.assertRaises(I.Refused):
            I.check_time('cn', {'US.A': dict(trading=True, time='11:30:00')}, TODAY, now=ny(TODAY, 2, 50))
        I.check_time('cn', {'US.A': dict(trading=True, time='11:30:00')}, TODAY, now=ny(TODAY, 0, 10))  # lunch
        for when in ('15:50:01', '', 'bad'):
            with self.subTest(time=when), self.assertRaises(I.Refused):
                I.check_time('cn', {'SH.A': dict(trading=True, time=when)}, TODAY, now=ny(TODAY, 3, 50))

    def test_corporate_action_today_equals_a_full_rebuild(self):
        split = {c: quote(LAST[c] / 2 + .5, LAST[c] / 2 if c == 'US.B' else LAST[c]) for c in CODES}
        from studies.trader_data import live as LV
        with mock.patch.object(LV, 'SNAP_MATCH', .6):                 # one name in three has the action
            self.run_at(ny(TODAY, 15, 50), split)
        got = self.seen[0]
        acts = [(c, TODAY, split[c]['prev_close'] / LAST[c], 0.0) for c in CODES if c == 'US.B']
        closes = {(c, TODAY): split[c]['close'] for c in CODES}
        ref = write_folder(self.root / 'ref', days=DAYS + (TODAY,), close=closes, actions=acts).panel()
        for k in TP.FIELDS:
            np.testing.assert_allclose(got[k], ref[k], rtol=1e-6, err_msg=k)


class SharedTests(Base):
    def test_every_study_reads_the_one_panel(self):
        from studies.trader_replication import panels
        p = TD.dataset('us', 'live').panel()
        with I.shared(p, 'us'):
            q = panels.load('us', None, 'live')
            np.testing.assert_array_equal(q['close'], p['close'])
            q['close'][:] = 0                                          # a copy: one system cannot change the next
            self.assertTrue(np.all(panels.load('us')['close'] > 0))
            self.assertEqual(str(panels.load('us', DAYS[1])['days'][-1]), DAYS[1])
        self.assertIsNot(panels.load, None)


class LimitTests(unittest.TestCase):
    def test_provisional_cli_refuses_silently_ignored_modes(self):
        from studies.trader_screens import scan
        for argv in (['run', 'us', '--provisional', '--mode', 'frozen'],
                     ['run', 'us', '--provisional', '--days', '5'], ['refresh', 'us', '--provisional']):
            with self.subTest(argv=argv), contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as cm:
                scan.main(argv)
            self.assertEqual(cm.exception.code, 2)

    def test_bad_quote_is_quarantined_and_cannot_inflate_coverage(self):
        codes = [f'US.T{i}' for i in range(20)]
        base = dict(raw_close=np.ones((1, 20)), volume=np.ones((1, 20)))
        quotes = {c: quote(10., 10.) for c in codes}
        quotes[codes[0]]['open'] = 0.
        clean, rejected, coverage = I.valid_snapshot(quotes, codes, base)
        self.assertNotIn(codes[0], clean)
        self.assertEqual(rejected, codes[:1])
        self.assertEqual(coverage, [19, 20])
        quotes[codes[1]]['volume'] = float('nan')
        with self.assertRaisesRegex(I.Refused, 'insufficient snapshot coverage'):
            I.valid_snapshot(quotes, codes, base)

    def test_limit_up(self):
        self.assertTrue(I.at_limit_up('SH.600000', '浦发银行', 11.0, 10.0))
        self.assertFalse(I.at_limit_up('SH.600000', '浦发银行', 10.99, 10.0))
        self.assertFalse(I.at_limit_up('SZ.300750', '宁德时代', 11.0, 10.0))
        self.assertTrue(I.at_limit_up('SZ.300750', '宁德时代', 12.0, 10.0))
        self.assertTrue(I.at_limit_up('SZ.000001', '*ST 某某', 10.5, 10.0, '2026-07-03'))
        self.assertFalse(I.at_limit_up('SZ.000001', '*ST 某某', 10.5, 10.0, '2026-07-06'))
        self.assertTrue(I.at_limit_up('SZ.000001', '*ST 某某', 11., 10., '2026-07-06'))
        self.assertFalse(I.at_limit_up('SZ.300001', '*ST 某某', 10.5, 10.0, '2026-07-03'))
        self.assertTrue(I.at_limit_up('SZ.300001', '*ST 某某', 12., 10., '2026-07-03'))
        self.assertFalse(I.at_limit_up('SH.600001', '', float('nan'), 10.))
        self.assertTrue(I.at_limit_up('SH.600001', '', 11.28, 10.25))   # 11.275 rounds to the cent: 11.28
        self.assertFalse(I.at_limit_up('SH.600001', '', 11.27, 10.25))
        self.assertFalse(I.at_limit_up('SH.600001', '', 11.16, np.float32(10.15)))
        self.assertTrue(I.at_limit_up('SH.600001', '', 11.17, np.float32(10.15)))
        self.assertTrue(I.at_limit_up('SH.600001', '', np.float32(32.12), np.float32(29.20)))
        self.assertFalse(I.at_limit_up('SH.600001', '', np.float32(32.11), np.float32(29.20)))


class MinuteTests(unittest.TestCase):
    def test_unknown_symbols_are_removed_only_for_explicit_symbol_errors(self):
        from studies.trader_screens.minute import invalid_codes
        codes = ['US.ATII', 'US.AT', 'US.TII']
        self.assertEqual(invalid_codes(codes, '未知股票 ATII'), ['US.ATII'])
        self.assertEqual(invalid_codes(codes, 'subscription quota exceeded: ATII'), [])

    def test_coverage_counts_missing_slots_and_merges_files_without_duplicates(self):
        from studies.trader_screens import minute as MN
        times = [f'{t // 60:02d}:{t % 60:02d}' for t in range(9 * 60 + 35, 16 * 60 + 1, 5)]
        codes = ('US.A', 'US.B')
        ds = SimpleNamespace(stocks=lambda: [dict(code=c) for c in codes],
                             rows=lambda: ((c, TODAY, [10, 10, 10, 10, 100, 1000]) for c in codes))
        with tempfile.TemporaryDirectory() as tmp:
            def write(name, rows):
                path = Path(tmp) / name
                with gzip.open(path, 'wt', newline='') as f:
                    w = csv.writer(f)
                    w.writerow(MN.HEADER)
                    w.writerows((c, f'{TODAY} {t}:00', 10, 10, 10, 10, 1, 10) for c, t in rows)
                return path
            a = write('a.csv.gz', [(c, t) for c in codes for t in times if c == 'US.A' or t != '09:35'])
            result = MN.coverage('us', [a, a], ds=ds, target=1)
            self.assertEqual(result['expected_slots'], 78)
            self.assertEqual(result['days'][0]['complete'], 1)
            self.assertEqual(result['days'][0]['missing_active'], ['US.B'])
            self.assertEqual(result['deficit_all_active'], 1)
            b = write('b.csv.gz', [('US.B', '09:35')])
            merged = MN.coverage('us', [a, b], ds=ds, target=1)
            self.assertEqual(merged['days_all_active_complete'], [TODAY])
            self.assertEqual(merged['deficit_all_active'], 0)

    def test_bar_known_at_each_cut_and_whole_sessions(self):
        from studies.trader_screens import minute as MN
        rows = [('US.A', TODAY, '15:45', 10, 11, 9, 10.5, 100, 1000), ('US.A', TODAY, '15:50', 10.5, 12, 10, 11, 50, 600),
                ('US.A', TODAY, '16:00', 11, 11.5, 8, 9, 300, 2700), ('US.B', TODAY, '13:00', 5, 5, 5, 5, 1, 5),
                ('US.B', TODAY, '16:00', 5, 6, 4, 6, 1, 6)]
        g = MN.aggregate(iter(rows), ('15:40', '15:50', '15:55'))
        a = g[('US.A', TODAY)]
        self.assertNotIn('15:40', a['parts'])                        # nothing had ended by then
        self.assertEqual(a['parts']['15:50'], (10, 12, 9, 11, 150, 1600))
        self.assertEqual(a['parts']['15:55'], a['parts']['15:50'])
        self.assertEqual(a['parts']['full'], (10, 12, 8, 9, 450, 4300))
        self.assertEqual(a['last_v'], 300)
        self.assertFalse(MN.complete(a, 'us'))                        # first bar after 10:00
        self.assertFalse(MN.complete(g[('US.B', TODAY)], 'us'))
        a['first'] = '09:35'
        self.assertTrue(MN.complete(a, 'us'))


class DiffTests(unittest.TestCase):
    def test_partial_and_trailing_exit_on_same_stock_are_both_kept(self):
        def res(sells):
            return dict(market='us', last_day=TODAY, traders=[dict(id='x', name='X', buys=[], sells=sells)])
        trim = dict(code='US.A', side=1, why='按 R 分批', price=10., full=False)
        trail = dict(code='US.A', side=1, why='收盘跌破跟踪线', price=9., full=True)
        result = I.diff(res([trim, trail]), res([trail]))['sells']
        self.assertEqual(len(result['same']), 1)
        self.assertEqual(result['same'][0]['prov'], 9.)
        self.assertEqual(len(result['gone']), 1)
        self.assertEqual(result['gone'][0]['prov'], 10.)

    def test_classes_and_price_gap(self):
        def res(buys, sells):
            return dict(market='us', last_day=TODAY, traders=[dict(id='x', name='X', buys=buys, sells=sells)])
        b = lambda code, px, **kw: dict(dict(code=code, side=1, setup='brk', price=px, stop=px * .95, weight=.1), **kw)
        s = lambda code, px: dict(code=code, side=1, why='收盘跌破跟踪线', price=px, ret=0, full=True)
        prov = res([b('US.A', 10.0), b('US.B', 20.0), b('US.L', 5.0, limit_up=True)], [s('US.C', 30.0)])
        off = res([b('US.A', 10.2), b('US.D', 40.0)], [s('US.C', 30.0), s('US.E', 50.0)])
        d = I.diff(prov, off)
        self.assertEqual([x['code'] for x in d['buys']['same']], ['US.A'])
        self.assertAlmostEqual(d['buys']['same'][0]['gap'], .02)
        self.assertEqual([x['code'] for x in d['buys']['gone']], ['US.B'])
        self.assertEqual([x['code'] for x in d['buys']['missed']], ['US.D'])
        self.assertEqual([x['code'] for x in d['sells']['same']], ['US.C'])
        self.assertEqual([x['code'] for x in d['sells']['missed']], ['US.E'])
        with self.assertRaises(ValueError):
            I.diff(prov, dict(off, last_day='2026-10-20'))
        with self.assertRaisesRegex(ValueError, 'different trader sets'):
            I.diff(prov, dict(off, traders=[]))


if __name__ == '__main__':
    unittest.main()
