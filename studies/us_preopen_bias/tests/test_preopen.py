import copy
import csv
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'code'))
import evaluate as ev  # noqa: E402
import package_release  # noqa: E402
import plan  # noqa: E402
import preopen  # noqa: E402
import signals  # noqa: E402


def _days(n, start=date(2024, 1, 2)):
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d += timedelta(days=1)
    return out


def _write(path, cols, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', newline='', encoding='utf-8') as fh:
        w = csv.writer(fh)
        w.writerow(cols)
        w.writerows(rows)


def synthetic(root, symbols=('US.SPY', 'US.AAA'), n=60):
    """Synthetic tables for unit tests only (no real market data)."""
    days = _days(n)
    for k, s in enumerate(symbols):
        tag = s.split('.')[1] + '.csv'
        px, daily, opt, iv, sv = 100.0 + k, [], [], [], []
        for i, d in enumerate(days):
            o = px * (1 + 0.003 * ((i * 7 + k) % 5 - 2))
            c = o * (1 + 0.004 * ((i * 3 + k) % 7 - 3))
            daily.append([d, o, max(o, c) * 1.01, min(o, c) * 0.99, c, 1e6 + 1e4 * (i % 9), (1e6 + 1e4 * (i % 9)) * c])
            opt.append([d, 3000 + 50 * (i % 11), 2000 + 40 * (i % 7), 1000 + 30 * (i % 5), 0.5, 0, 0, 0, c])
            iv.append([d, 30 + (i % 4), 25 + (i % 3), c])
            sv.append([d, 1000 + i, 0, 0, 10 + (i % 6), 1e6, c, px])
            px = c
        _write(root / 'daily' / tag, ['date', 'open', 'high', 'low', 'close', 'volume', 'turnover'], daily)
        _write(root / 'option_stats' / tag, ['time', 'option_volume', 'call_volume', 'put_volume', 'put_call_volume_ratio',
                                             'option_open_interest', 'call_open_interest', 'put_open_interest',
                                             'underlying_price'], opt)
        _write(root / 'iv' / tag, ['time', 'iv', 'hv', 'underlying_price'], iv)
        _write(root / 'short_volume' / tag, ['timestamp_str', 'total_shares_short', 'nasdaq_shares_short',
                                             'nyse_shares_short', 'short_percent', 'volume', 'close_price',
                                             'last_close_price'], sv)
    for k, s in enumerate(symbols):
        bars = []
        for i, d in enumerate(days):
            for j, hm in enumerate(('08:30', '09:00', '09:30', '16:30', '20:00')):
                px = 100 + k + (i % 5) + 0.1 * j
                bars.append(['%s %s:00' % (d, hm), px, px, px, px, 100 + 10 * ((i + j) % 4), (100 + 10 * ((i + j) % 4)) * px])
        _write(root / 'ext30' / (s.split('.')[1] + '.csv'), ['time_key', 'open', 'high', 'low', 'close', 'volume', 'turnover'], bars)
    _write(root / 'market_option.csv', ['kind', 'time', 'call_value', 'put_value', 'total_value', 'ratio'],
           [['VOLUME', d, 100, 80 + i % 5, 180, (80 + i % 5) / 100] for i, d in enumerate(days)])
    return days


class PointInTimeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.days = synthetic(self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def test_features_ignore_everything_after_the_open_of_T(self):
        data = preopen.load([self.root])
        T = self.days[40]
        before = {r['symbol']: r for r in preopen.build(data, T, T)}
        spoiled = copy.deepcopy(data)
        for t in spoiled['tables'].values():
            row = t['daily'][T]
            row['close'], row['high'], row['low'] = '1000', '2000', '1'
            row['turnover'] = row['volume'] = '1'
            t['opt'][T]['call_volume'] = t['opt'][T]['put_volume'] = t['opt'][T]['option_volume'] = '999999'
            t['iv'][T]['iv'] = t['iv'][T]['hv'] = '500'
            t['sv'][T]['short_percent'] = '99'
            t['ext'][T]['ah_last'] = 999.0   # after-hours of T itself is not known at T's open
        spoiled['market']['VOLUME'][T]['ratio'] = '9'
        after = {r['symbol']: r for r in preopen.build(spoiled, T, T)}
        for s in before:
            self.assertIsNotNone(before[s]['f']['pm_late_z'], s)
            self.assertIsNotNone(before[s]['f']['ah_z'], s)
            self.assertEqual(before[s]['f'], after[s]['f'], s)
            self.assertNotEqual(before[s]['y'], after[s]['y'], s)

    def test_gap_uses_the_open_of_T_and_label_is_open_to_close(self):
        rows = preopen.build(preopen.load([self.root]), self.days[40], self.days[40])
        daily = preopen.load([self.root])['tables']['US.AAA']['daily']
        r = [x for x in rows if x['symbol'] == 'US.AAA'][0]
        o, c = float(daily[self.days[40]]['open']), float(daily[self.days[40]]['close'])
        pc = float(daily[self.days[39]]['close'])
        self.assertAlmostEqual(r['f']['gap'], o / pc - 1)
        self.assertAlmostEqual(r['y']['ret_oc'], c / o - 1)
        self.assertEqual(r['y']['up'], c > o)

    def test_plan_matches_the_backtest(self):
        data = preopen.load([self.root])
        T = self.days[45]
        rows = {r['symbol']: r for r in preopen.build(data, T, T)}
        for s, t in data['tables'].items():
            daily = {d: v for d, v in t['daily'].items() if d < T}   # the scan never sees day T
            P, z, side = plan.q2(daily, t['ext'], T)
            self.assertEqual(P, self.days[44])
            self.assertAlmostEqual(z, rows[s]['f']['ah_z'])
            self.assertEqual(side, -1 if abs(z) >= 1 else 0)

    def test_signals_never_receive_labels(self):
        rows = preopen.build(preopen.load([self.root]))
        for r in rows:
            for key in r['y']:
                self.assertNotIn(key, r['f'])
        for fn in list(signals.S1.values()):
            for r in rows:
                self.assertIn(fn(r['f']), (-1, 0, 1))


class EvaluateTests(unittest.TestCase):
    def rows(self):
        out = []
        for i, d in enumerate(_days(40)):
            for s, up in (('US.A', i % 2 == 0), ('US.B', i % 4 == 0)):
                out.append({'symbol': s, 'date': d, 'f': {'is_index': False, 'i': i, 's': s},
                            'y': {'up': up, 'down': not up, 'ret_oc': 0.01 if up else -0.01}})
        return out

    def test_hit_and_base_rate(self):
        rows = self.rows()
        m = ev.score(rows, lambda f: 1 if f['s'] == 'US.A' and f['i'] % 2 == 0 else 0)
        self.assertEqual(m['hit'], 1.0)
        self.assertAlmostEqual(m['base'], 0.5)
        self.assertAlmostEqual(m['excess'], 0.5)
        m = ev.score(rows, lambda f: -1 if f['s'] == 'US.B' else 0)
        self.assertAlmostEqual(m['hit'], 0.75)
        self.assertAlmostEqual(m['excess'], 0.0)

    def test_gates(self):
        rows = self.rows()
        m = ev.score(rows, lambda f: 1, split=rows[40]['date'])
        g = ev.gates(m)
        self.assertFalse(g['enough'])
        self.assertIn('halves', g)


class PackageTests(unittest.TestCase):
    def test_split_has_no_overlap(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / 'a.csv'
            _write(src, ['date', 'x'], [['2025-06-30', 1], ['2025-07-01', 2], ['2025-07-02', 3]])
            tr, va = Path(tmp) / 't.csv', Path(tmp) / 'v.csv'
            package_release.split_csv(src, tr, va, 'date')
            t = [r['date'] for r in csv.DictReader(tr.read_text().splitlines())]
            v = [r['date'] for r in csv.DictReader(va.read_text().splitlines())]
            self.assertEqual(t, ['2025-06-30'])
            self.assertEqual(v, ['2025-07-01', '2025-07-02'])


if __name__ == '__main__':
    unittest.main()
