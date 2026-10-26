"""Hourly bars through the data interface, on synthetic folders and a fake provider: the per-bar adjustment, daily
bars rebuilt from hours, invalid bars, and the live append with its overlap check."""
import gzip
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

import studies.trader_data as TD
from studies.trader_data import hourly as H

CODES = ('US.A', 'US.B')
TIMES = ('2026-10-15 10:30:00', '2026-10-15 16:00:00', '2026-10-16 10:30:00', '2026-10-16 16:00:00')


def write_folder(root, closes=None, actions=(), bad=None):
    sub = Path(root) / 'us'
    sub.mkdir(parents=True)
    with gzip.open(sub / 'bars_raw.csv.gz', 'wt', encoding='utf-8') as f:
        f.write(','.join(H.COLUMNS) + '\n')
        for j, c in enumerate(CODES):
            for i, t in enumerate(TIMES):
                px = (closes or {}).get((c, t), 10.0 + j + i)
                hi = px * 1.01 if (c, t) != bad else px * .5          # high below the close: invalid
                f.write(f'{c},{t},{px},{hi},{px * .99},{px},100,{px * 100}\n')
    with gzip.open(sub / 'actions.csv.gz', 'wt', encoding='utf-8') as f:
        f.write(','.join(H.ACTION_COLUMNS) + '\n')
        for a in actions:
            f.write(','.join(map(str, a)) + '\n')
    (sub / 'universe.json').write_text(json.dumps({'filter': {}, 'stocks': [{'code': c} for c in CODES]}))
    return H.HourlyDataset(root, 'us')


class FakeSource:
    def __init__(self, bars, acts=()):
        self.bars, self.acts = bars, acts

    def recent(self, codes):
        return {c: self.bars.get(c, []) for c in codes}

    def actions(self, code):
        return [a for a in self.acts if a[0] == code]

    def close(self):
        pass


def bar(px):
    return [px, px * 1.01, px * .99, px, 100.0, px * 100]


class HourlyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        patch = mock.patch.object(H, 'CACHE', self.root / 'cache')
        patch.start()
        self.addCleanup(patch.stop)
        self.addCleanup(self.tmp.cleanup)

    def test_split_adjusts_earlier_bars(self):
        closes = {('US.A', TIMES[2]): 5.5, ('US.A', TIMES[3]): 6.5}          # a 2:1 split on 2026-10-16
        ds = write_folder(self.root / 'f', closes, actions=[('US.A', '2026-10-16', .5, 0.0)])
        p = ds.panel()
        a = list(p['codes']).index('US.A')
        self.assertAlmostEqual(float(p['close'][0, a]), 10.0 * .5, places=4)
        self.assertAlmostEqual(float(p['close'][3, a]), 6.5, places=4)
        self.assertAlmostEqual(float(p['raw_close'][0, a]), 10.0, places=4)

    def test_daily_from_hours(self):
        p = write_folder(self.root / 'f').panel()
        d = H.daily(p)
        self.assertEqual(list(d['days']), ['2026-10-15', '2026-10-16'])
        self.assertAlmostEqual(float(d['open'][0, 0]), 10.0, places=4)
        self.assertAlmostEqual(float(d['close'][0, 0]), 11.0, places=4)
        self.assertAlmostEqual(float(d['high'][1, 0]), 13.0 * 1.01, places=3)
        self.assertAlmostEqual(float(d['volume'][1, 0]), 200.0)

    def test_invalid_bar_is_left_out(self):
        p = write_folder(self.root / 'f', bad=('US.B', TIMES[1])).panel()
        self.assertTrue(np.isnan(p['close'][1, 1]))
        self.assertTrue(np.isfinite(p['close'][2, 1]))

    def test_zero_volume_bar_is_no_trade(self):
        self.assertFalse(H.valid([.4, .4, .4, .4, 0.0, 0.0]))
        self.assertTrue(H.valid([7.25, 7.89, 6.9, 7.28, 399312.0, 2864247.0]))

    def test_upto_cuts_by_day_or_time(self):
        p = write_folder(self.root / 'f').panel()
        self.assertEqual(len(H.build(write_folder(self.root / 'g'), '2026-10-15')['times']), 2)
        self.assertEqual(len(H.build(write_folder(self.root / 'h'), '2026-10-16 10:30:00')['times']), 3)
        self.assertEqual(len(p['times']), 4)

    def test_live_appends_after_the_newest_bar(self):
        base = write_folder(self.root / 'f')
        new_t = '2026-10-19 10:30:00'
        src = FakeSource({'US.A': [(TIMES[3], bar(13.0)), (new_t, bar(14.0))],
                          'US.B': [(TIMES[3], bar(14.0)), (new_t, bar(15.0))]})
        live = H.LiveHourly(base, self.root / 'live', src)
        out = live.update()
        self.assertEqual(out['appended'], 2)
        p = live.panel()
        self.assertEqual(p['times'][-1], new_t)
        self.assertAlmostEqual(float(p['close'][-1, 0]), 14.0, places=4)
        self.assertEqual(live.update()['appended'], 0)                     # nothing new the second time

    def test_live_stops_when_the_overlap_disagrees(self):
        base = write_folder(self.root / 'f')
        src = FakeSource({'US.A': [(TIMES[3], bar(20.0)), ('2026-10-19 10:30:00', bar(14.0))],
                          'US.B': [(TIMES[3], bar(14.0)), ('2026-10-19 10:30:00', bar(15.0))]})
        live = H.LiveHourly(base, self.root / 'live', src)
        with self.assertRaises(RuntimeError):
            live.update()
        self.assertFalse((self.root / 'live' / 'us' / 'bars_raw.csv.gz').exists())

    def test_interface_switch(self):
        write_folder(self.root / 'data' / 'trader-hourly-v1')
        with mock.patch.object(TD, 'ROOT', self.root):
            self.assertIsInstance(TD.hourly_dataset('us', 'frozen'), H.HourlyDataset)
            self.assertIsInstance(TD.hourly_dataset('us', 'live'), H.LiveHourly)
            with self.assertRaises(FileNotFoundError):
                TD.hourly_dataset('hk', 'frozen')


if __name__ == '__main__':
    unittest.main()
