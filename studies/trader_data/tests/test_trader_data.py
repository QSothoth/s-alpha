"""The data interface on synthetic folders and a fake provider: panels, the frozen / live switch, and every path of
the live update (snapshot, corporate action from the previous close, history re-read, the checks that stop it)."""
import gzip
import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock
from zoneinfo import ZoneInfo

import numpy as np

import studies.trader_data as TD
from studies.trader_data import live as LV, panel as TP, providers as PV

CODES = ('US.A', 'US.B', 'US.C')
DAYS = ('2026-10-13', '2026-10-14', '2026-10-15', '2026-10-16')


def write_folder(root, market='us', days=DAYS, close=None, actions=()):
    sub = Path(root) / market
    sub.mkdir(parents=True)
    with gzip.open(sub / 'bars_raw.csv.gz', 'wt', encoding='utf-8') as f:
        f.write('code,date,open,high,low,close,volume,turnover\n')
        for j, c in enumerate(CODES):
            for i, d in enumerate(days):
                px = (close or {}).get((c, d), 10.0 + j + i)
                f.write(f'{c},{d},{px},{px * 1.01},{px * .99},{px},1000,{px * 1000}\n')
    with gzip.open(sub / 'actions.csv.gz', 'wt', encoding='utf-8') as f:
        f.write('code,ex_date,factor_a,factor_b\n')
        for a in actions:
            f.write(','.join(map(str, a)) + '\n')
    (sub / 'universe.json').write_text(json.dumps({'filter': {'min_price': 1.0}, 'window': [days[0], days[-1]],
                                                   'stocks': [{'code': c, 'name': c[3:]} for c in CODES]}))
    return TD.FolderDataset(root, market)


class Fake(PV.Provider):
    """Sessions Mon-Fri; a snapshot of `snap_day` built from `closes`; history rows from `hist`."""
    market = 'us'

    def __init__(self, sessions, snap=None, hist=None):
        self._s, self.snap, self.hist, self.calls = sessions, snap or {}, hist or {}, []
        self.anchor = {}                # code -> the stored close of the anchor day, served as a real provider does

    def sessions(self, start, end):
        if start > end:
            raise RuntimeError('invalid period')                # as OpenD request_trading_days
        return [d for d in self._s if start <= d <= end]

    def snapshot(self, codes):
        self.calls.append('snapshot')
        return {c: self.snap[c] for c in codes if c in self.snap}

    def history(self, codes, start, end):
        self.calls.append('history')
        for c in codes:
            rows = [r for r in self.hist.get(c, []) if start <= r[1] <= end]
            if rows and c in self.anchor and not any(r[1] == start for r in rows):
                x = self.anchor[c]
                rows = [(c, start, x, x, x, x, 1000, x * 1000)] + rows
            yield c, rows, []


def anchored(fake, base):
    """The fake serves the stored anchor-day bar (as OpenD's history does) where a test gives none."""
    if isinstance(fake, Fake) and not fake.anchor:
        p = base.panel()
        fake.anchor = {str(c): float(p['raw_close'][-1, j]) for j, c in enumerate(p['codes'])}
    return fake


def snap(close, prev, vol=1000):
    return dict(open=close, high=close * 1.01, low=close * .99, close=close, volume=vol, turnover=close * vol,
                prev_close=prev, trading=vol > 0)


def ny(day, hh, mm=0):
    return datetime.fromisoformat(f'{day}T{hh:02d}:{mm:02d}').replace(tzinfo=ZoneInfo('America/New_York'))


SESS = ('2026-10-16', '2026-10-19', '2026-10-20', '2026-10-21')


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.cache = mock.patch.object(TP, 'CACHE', self.root / 'cache')
        self.cache.start()

    def tearDown(self):
        self.cache.stop()
        self.tmp.cleanup()

    def live(self, fake, **kw):
        base = write_folder(self.root / 'rel', **kw)
        return TD.LiveDataset(base, self.root / 'live', provider=lambda: anchored(fake, base))


class PanelTests(Base):
    def test_bad_bar_is_widened_and_digest_rebuilds(self):
        ds = write_folder(self.root / 'a', close={('US.A', DAYS[1]): 11.0})
        p = ds.panel()
        self.assertTrue(np.all(p['low'] <= p['close']) and np.all(p['close'] <= p['high']))
        raw = ds.sub / 'bars_raw.csv.gz'
        st = raw.stat()
        with gzip.open(raw, 'wt', encoding='utf-8') as f:
            f.write('code,date,open,high,low,close,volume,turnover\nUS.A,2026-10-13,5,5,5,5.5,1,1\n')
        os.utime(raw, (st.st_atime, st.st_mtime - 3600))            # older than the cache: still rebuilt
        q = ds.panel()
        self.assertNotEqual(p['digest'], q['digest'])
        self.assertEqual(float(q['high'][0, 0]), 5.5)               # close above the bar's high: high widened

    def test_symlink_and_real_path_share_one_cache(self):
        write_folder(self.root / 'a')
        (self.root / 'link').symlink_to(self.root / 'a')
        self.assertEqual(TP.cache_path(TD.FolderDataset(self.root / 'link', 'us')),
                         TP.cache_path(TD.FolderDataset(self.root / 'a', 'us')))

    def test_upto_cuts_rows(self):
        p = write_folder(self.root / 'a').panel(upto=DAYS[1])
        self.assertEqual(list(p['days']), list(DAYS[:2]))
        self.assertEqual(p['close'].shape, (2, 3))


class ProviderTests(unittest.TestCase):
    def test_snapshot_recovers_from_a_transient_page_timeout(self):
        from studies.trend_breakout import sources
        payload = json.dumps([dict(symbol='sh600000', open='10', high='10.4', low='9.9', trade='10.2',
                                   volume='1000', amount='10200', settlement='10')]).encode()
        response = mock.Mock(read=mock.Mock(return_value=payload))
        end = mock.Mock(read=mock.Mock(return_value=b'[]'))
        with mock.patch.object(sources.urllib.request, 'urlopen', side_effect=[TimeoutError(), response, end]) as fetch, \
                mock.patch.object(sources.time, 'sleep'):
            snap = PV.SinaProvider().snapshot(['SH.600000'])
        self.assertEqual(snap['SH.600000']['close'], 10.2)
        self.assertTrue(snap['SH.600000']['trading'])
        self.assertEqual(fetch.call_count, 3)


class LiveTests(Base):
    def test_one_missing_session_comes_from_one_snapshot(self):
        last = {c: 10.0 + j + 3 for j, c in enumerate(CODES)}
        fake = Fake(SESS, snap={c: snap(last[c] + 1, last[c]) for c in CODES})
        ds = self.live(fake)
        r = ds.update(ny('2026-10-19', 17))
        self.assertEqual((r['method'], r['days'], r['rows'], r['actions']), ('snapshot', ['2026-10-19'], 3, 0))
        self.assertEqual((r['expected_last_day'], r['last_day'], r['status']),
                         ('2026-10-19', '2026-10-19', 'updated'))
        p = ds.panel()
        self.assertEqual(str(p['days'][-1]), '2026-10-19')
        self.assertAlmostEqual(float(p['close'][-1, 0]), 14.0)
        self.assertEqual(ds.update(ny('2026-10-19', 18))['method'], None)          # nothing missing now
        self.assertEqual(ds.update(ny('2026-10-20', 8))['missing'], [])            # next session not yet traded
        self.assertEqual(fake.calls, ['snapshot'])

    def test_nothing_before_the_session_closes(self):
        fake = Fake(SESS)
        ds = self.live(fake)
        self.assertEqual(ds.update(ny('2026-10-19', 12))['missing'], [])

    def test_split_is_read_from_the_previous_close(self):
        last = {c: 10.0 + j + 3 for j, c in enumerate(CODES)}
        snaps = {c: snap(last[c], last[c]) for c in CODES}
        snaps['US.A'] = snap(6.6, last['US.A'] / 2)              # 2-for-1 split on 10-19
        ds = self.live(Fake(SESS, snap=snaps))
        with mock.patch.object(LV, 'SNAP_MATCH', .5):           # 3 names here; thousands in a real list
            r = ds.update(ny('2026-10-19', 17))
        self.assertEqual(r['actions'], 1)
        acts = ds.actions()['US.A']
        self.assertEqual(acts[0][0], '2026-10-19')
        self.assertAlmostEqual(acts[0][1], .5)
        p = ds.panel()
        self.assertAlmostEqual(float(p['close'][-2, 0]), 6.5)    # 13 before the split, halved: no fake gap
        self.assertAlmostEqual(float(p['raw_close'][-2, 0]), 13.0)

    def test_snapshot_of_another_session_is_refused(self):
        snaps = {c: snap(20.0, 19.0) for c in CODES}            # previous closes match nothing we hold
        ds = self.live(Fake(SESS, snap=snaps))
        with self.assertRaises(RuntimeError):
            ds.update(ny('2026-10-19', 17))
        self.assertFalse((ds.dir / 'bars_raw.csv.gz').exists())

    def test_several_missing_sessions_use_history_and_check_the_overlap(self):
        last = {c: 10.0 + j + 3 for j, c in enumerate(CODES)}
        hist = {c: [(c, d, x, x, x, x, 1000, x * 1000) for d, x in
                    (('2026-10-16', last[c]), ('2026-10-19', last[c] + 1), ('2026-10-20', last[c] + 2))]
                for c in CODES}
        fake = Fake(SESS, hist=hist)
        ds = self.live(fake)
        r = ds.update(ny('2026-10-20', 17))
        self.assertEqual((r['method'], r['rows'], r['overlap_checked']), ('history', 6, 3))
        self.assertEqual([str(d) for d in ds.panel()['days'][-2:]], ['2026-10-19', '2026-10-20'])

    def test_history_that_rewrites_our_last_day_is_refused(self):
        hist = {c: [(c, '2026-10-16', 99, 99, 99, 99, 1, 99), (c, '2026-10-19', 1, 1, 1, 1, 1, 1)] for c in CODES}
        ds = self.live(Fake(SESS, hist=hist))
        with self.assertRaises(RuntimeError):
            ds.update(ny('2026-10-20', 12))

    def test_while_today_trades_yesterday_comes_from_history(self):
        last = {c: 10.0 + j + 3 for j, c in enumerate(CODES)}
        hist = {c: [(c, '2026-10-16', last[c], last[c], last[c], last[c], 1, 1),
                    (c, '2026-10-19', 1, 1, 1, 1, 1, 1)] for c in CODES}
        fake = Fake(SESS, snap={c: snap(1, last[c]) for c in CODES}, hist=hist)
        ds = self.live(fake)
        self.assertEqual(ds.update(ny('2026-10-20', 11))['method'], 'history')    # a snapshot shows today now
        self.assertEqual(fake.calls, ['history'])

    def test_missing_latest_session_is_rejected_before_any_cache_write(self):
        hist = {c: [(c, '2026-10-19', 15, 15, 15, 15, 1000, 15000)] for c in CODES}
        latest_only = {c: [(c, '2026-10-20', 15, 15, 15, 15, 1000, 15000)] for c in CODES}
        for i, available in enumerate(({}, hist, latest_only)):
            with self.subTest(case=i):
                fake = Fake(SESS, hist=available)
                base = write_folder(self.root / f'rel-{i}')
                ds = TD.LiveDataset(base, self.root / f'live-{i}', provider=lambda: anchored(fake, base))
                before = ds.digest()
                with self.assertRaisesRegex(RuntimeError, 'no trading bars for completed sessions'):
                    ds.update(ny('2026-10-20', 17))
                self.assertEqual(ds.digest(), before)
                self.assertFalse(ds.dir.exists())
                self.assertEqual(ds.log(), [])

    def test_empty_calendar_is_not_mistaken_for_a_holiday(self):
        ds = self.live(Fake([]))
        with self.assertRaisesRegex(RuntimeError, 'calendar omits stored session'):
            ds.update(ny('2026-10-20', 17))
        self.assertFalse(ds.dir.exists())

    def test_weekends_and_calendar_holidays_keep_last_completed_session(self):
        fake = Fake(['2026-10-16'])
        ds = self.live(fake)
        for day in ('2026-10-17', '2026-10-18', '2026-10-19'):
            r = ds.update(ny(day, 17))
            self.assertEqual((r['expected_last_day'], r['last_day'], r['status']),
                             ('2026-10-16', '2026-10-16', 'current'))
        self.assertEqual(fake.calls, [])
        self.assertFalse(ds.dir.exists())

    def test_severely_incomplete_history_cannot_mark_session_current(self):
        hist = {'US.A': [('US.A', day, 15, 15, 15, 15, 1000, 15000)
                         for day in ('2026-10-19', '2026-10-20')]}
        ds = self.live(Fake(SESS, hist=hist))
        with self.assertRaisesRegex(RuntimeError, 'insufficient trading-name coverage'):
            ds.update(ny('2026-10-20', 17))
        self.assertFalse(ds.dir.exists())

    def test_coverage_allows_one_suspension_in_twenty_previous_trading_names(self):
        codes = tuple(f'US.T{i}' for i in range(20))
        hist = {c: [(c, day, 15, 15, 15, 15, 1000, 15000)
                    for day in ('2026-10-19', '2026-10-20')] for c in codes[:19]}
        with mock.patch(__name__ + '.CODES', codes):
            ds = self.live(Fake(SESS, hist=hist))
        report = ds.update(ny('2026-10-20', 17))
        self.assertEqual(report['session_rows'], {'2026-10-19': 19, '2026-10-20': 19})
        self.assertEqual(report['session_coverage'], {'2026-10-19': [19, 20], '2026-10-20': [19, 20]})
        self.assertEqual(report['n_failed'], 1)

    def test_coverage_rejects_two_missing_of_twenty_previous_trading_names(self):
        codes = tuple(f'US.T{i}' for i in range(20))
        hist = {c: [(c, day, 15, 15, 15, 15, 1000, 15000)
                    for day in ('2026-10-19', '2026-10-20')] for c in codes[:18]}
        with mock.patch(__name__ + '.CODES', codes):
            ds = self.live(Fake(SESS, hist=hist))
        with self.assertRaisesRegex(RuntimeError, 'insufficient trading-name coverage'):
            ds.update(ny('2026-10-20', 17))
        self.assertFalse(ds.dir.exists())

    def test_duplicate_bars_cannot_inflate_coverage(self):
        row = ('US.A', '2026-10-19', 15, 15, 15, 15, 1000, 15000)
        ds = self.live(Fake(SESS, hist={'US.A': [row] * 100}))
        with self.assertRaisesRegex(RuntimeError, 'duplicate provider bar'):
            ds.update(ny('2026-10-20', 11))
        self.assertFalse(ds.dir.exists())

    def test_coverage_baseline_excludes_previously_nontrading_names(self):
        codes = tuple(f'US.T{i}' for i in range(20))
        active = set(codes[:10])
        hist = {c: [(c, day, 15, 15, 15, 15, 1000, 15000)
                    for day in ('2026-10-19', '2026-10-20')] for c in active}
        with mock.patch(__name__ + '.CODES', codes):
            ds = self.live(Fake(SESS, hist=hist))
        previous = ds.panel()
        for j, c in enumerate(previous['codes']):
            if c not in active:
                previous['volume'][-1, j] = 0
        with mock.patch.object(ds, 'panel', return_value=previous):
            report = ds.update(ny('2026-10-20', 17))
        self.assertEqual(report['session_coverage'], {'2026-10-19': [10, 10], '2026-10-20': [10, 10]})

    def test_invalid_latest_bar_cannot_advance_last_day(self):
        ds = self.live(Fake(SESS, hist={'US.A': [('US.A', '2026-10-19', 15, 15, 15, float('nan'), 1, 15)]}))
        with self.assertRaisesRegex(RuntimeError, 'no trading bars'):
            ds.update(ny('2026-10-20', 11))
        self.assertFalse(ds.dir.exists())

    def test_invalid_snapshot_is_quarantined_without_price_or_action_fabrication(self):
        codes = tuple(f'US.T{i}' for i in range(20))
        cases = (dict(open=0., high=0., low=0.), dict(close=float('nan')),
                 dict(volume=-1.), dict(turnover=float('inf')), dict(low=100.), dict(close=None),
                 dict(prev_close=float('nan')), dict(prev_close=0.))
        for i, invalid in enumerate(cases):
            with self.subTest(invalid=invalid), mock.patch(__name__ + '.CODES', codes):
                base = write_folder(self.root / f'rel-{i}')
                snaps = {c: snap(14. + j, 13. + j) for j, c in enumerate(codes)}
                snaps[codes[0]].update(prev_close=6.5)
                snaps[codes[0]].update(invalid)
                ds = TD.LiveDataset(base, self.root / f'live-{i}',
                                    provider=lambda: Fake(SESS, snap=snaps))
                report = ds.update(ny('2026-10-19', 17))
                self.assertEqual(report['session_coverage'], {'2026-10-19': [19, 20]})
                self.assertEqual((report['rows'], report['actions']), (19, 0))
                rejected = report['rejected_bars']
                self.assertEqual([(r['code'], r['day']) for r in rejected], [(codes[0], '2026-10-19')])
                json.dumps(report, allow_nan=False)
                panel = ds.panel()
                self.assertTrue(np.isnan(panel['close'][-1, 0]))
                self.assertFalse(ds.actions())
                self.assertEqual(ds.update(ny('2026-10-19', 18))['rejected_bars'], rejected)

    def test_invalid_history_is_quarantined_and_still_counts_against_coverage(self):
        codes = tuple(f'US.T{i}' for i in range(20))
        hist = {c: [(c, '2026-10-19', 15., 15., 15., 15., 1000., 15000.)] for c in codes}
        hist[codes[0]] = [(codes[0], '2026-10-19', 0., 0., 0., 9.97, 6., 60.)]
        with mock.patch(__name__ + '.CODES', codes):
            ds = self.live(Fake(SESS, hist=hist))
        report = ds.update(ny('2026-10-20', 11))
        self.assertEqual(report['rows'], 19)
        self.assertEqual(len(report['rejected_bars']), 1)
        hist[codes[1]] = [(codes[1], '2026-10-19', 15., 15., 15., float('nan'), 1000., 15000.)]
        with mock.patch(__name__ + '.CODES', codes):
            base = write_folder(self.root / 'other')
        ds = TD.LiveDataset(base, self.root / 'other-live', provider=lambda: anchored(Fake(SESS, hist=hist), base))
        with self.assertRaisesRegex(RuntimeError, 'insufficient trading-name coverage'):
            ds.update(ny('2026-10-20', 11))
        self.assertFalse(ds.dir.exists())

    def test_malformed_provider_numbers_remain_invalid(self):
        for value in (None, '', 'bad'):
            self.assertTrue(np.isnan(PV.number(value)))
        self.assertEqual(PV.number('9.97'), 9.97)

    def test_old_invalid_cache_is_quarantined_and_checked_without_rewriting_source(self):
        codes = tuple(f'US.T{i}' for i in range(20))
        with mock.patch(__name__ + '.CODES', codes):
            ds = self.live(Fake(SESS))
        ds.dir.mkdir(parents=True)
        rows = [(c, '2026-10-19', 15., 15., 15., 15., 1000., 15000.) for c in codes]
        rows[0] = (codes[0], '2026-10-19', 0., 0., 0., 9.97, 6., 60.)
        LV.append(ds.dir / 'bars_raw.csv.gz', rows, LV.COLUMNS)
        original = (ds.dir / 'bars_raw.csv.gz').read_bytes()
        with self.assertRaisesRegex(RuntimeError, 'no completed update record'):
            ds.update(ny('2026-10-19', 18))
        (ds.dir / 'log.json').write_text(json.dumps([dict(days=['2026-10-19'])]))
        report = ds.update(ny('2026-10-19', 18))
        self.assertEqual(report['session_coverage'], {'2026-10-19': [19, 20]})
        self.assertEqual(report['rejected_bars'][0]['code'], codes[0])
        self.assertTrue(np.isnan(ds.panel()['close'][-1, 0]))
        self.assertEqual((ds.dir / 'bars_raw.csv.gz').read_bytes(), original)


class ReviewBoundaryTests(unittest.TestCase):
    """2026-10-25 strategy review R07: no relabelled snapshot, no agreement claimed on nothing compared."""

    def test_snapshot_dated_another_session_is_rejected(self):
        class Snap:
            @staticmethod
            def snapshot(codes):
                return {'US.A': dict(open=10, high=10, low=10, close=10, volume=1, turnover=10, prev_close=10,
                                     trading=True, time='2026-10-15 16:00:00'),
                        'US.B': dict(open=11, high=11, low=11, close=11, volume=1, turnover=11, prev_close=11,
                                     trading=True, time='2026-10-19 16:00:00')}
        rows, _, check = LV.LiveDataset.from_snapshot(Snap, ['US.A', 'US.B'], '2026-10-19',
                                                      {'US.A': ('2026-10-16', 10), 'US.B': ('2026-10-16', 11)})
        self.assertEqual([r[0] for r in rows], ['US.B'])
        self.assertEqual(check['rejected_bars'][0]['reason'], 'quote dated 2026-10-15')

    def test_history_without_the_anchor_day_is_refused(self):
        class NoOverlap:
            @staticmethod
            def history(codes, start, end):
                yield 'US.A', [('US.A', '2026-10-19', 10, 10, 10, 10, 1, 10)], []
        with self.assertRaisesRegex(RuntimeError, 'no bar on 2026-10-16'):
            LV.LiveDataset.from_history(NoOverlap, ['US.A'], '2026-10-16', ['2026-10-19'], {'US.A': 10})


class ApiTests(Base):
    def test_mode_switch_and_provisional_bars_are_not_stored(self):
        write_folder(self.root / 'data' / 'trader-data-v1')
        last = {c: 10.0 + j + 3 for j, c in enumerate(CODES)}
        fake = Fake(SESS, snap={c: snap(last[c] + 5, last[c]) for c in CODES})
        with mock.patch.object(TD, 'ROOT', self.root), mock.patch.object(TD, 'LIVE_ROOT', self.root / 'live'), \
                mock.patch.object(PV, 'get', lambda m: fake):
            with mock.patch.dict(os.environ, {'TRADER_DATA_MODE': 'frozen'}):
                self.assertIsInstance(TD.dataset('us'), TD.FolderDataset)
                self.assertEqual(str(TD.load('us')['days'][-1]), DAYS[-1])
            with mock.patch.dict(os.environ, {'TRADER_DATA_MODE': 'live'}):
                self.assertIsInstance(TD.dataset('us'), TD.LiveDataset)
                p = TD.load('us', update=False, provisional=True, now=ny('2026-10-19', 15))
                self.assertEqual(str(p['days'][-1]), '2026-10-19')
                self.assertFalse((self.root / 'live' / 'trader-data-v1' / 'us' / 'bars_raw.csv.gz').exists())
            with self.assertRaises(ValueError):
                TD.resolve_mode('paper')


if __name__ == '__main__':
    unittest.main()
