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
            yield c, [r for r in self.hist.get(c, []) if start <= r[1] <= end], []


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
        return TD.LiveDataset(base, self.root / 'live', provider=lambda: fake)


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


class LiveTests(Base):
    def test_one_missing_session_comes_from_one_snapshot(self):
        last = {c: 10.0 + j + 3 for j, c in enumerate(CODES)}
        fake = Fake(SESS, snap={c: snap(last[c] + 1, last[c]) for c in CODES})
        ds = self.live(fake)
        r = ds.update(ny('2026-10-19', 17))
        self.assertEqual((r['method'], r['days'], r['rows'], r['actions']), ('snapshot', ['2026-10-19'], 3, 0))
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
