"""Synthetic P5 protocol checks only; never opens the new validation sample."""
from datetime import date, timedelta
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from studies.us_0dte_picks import p3, p4, p5


def fixture():
    day, days = date(2026, 7, 10), []
    while len(days) < 50:
        if day.weekday() < 5:
            days.append(day.isoformat())
        day -= timedelta(days=1)
    days.sort()
    bars = {day: [(clock, 100., 101., 99., 100., 10000.) for clock in p5.GRID] for day in days}
    bars[days[-2]] = [(clock, 100., 106., 99.5, 105.8, 30000.) for clock in p5.GRID]
    bars[days[-1]] = [(clock, 106., 106.8, 105.9, 106.6, 20000.) for clock in p5.GRID]
    calendar = dict.fromkeys(days, 'WHOLE')
    tables = ({day: 100. for day in days}, {day: 5000. for day in days},
              {'iv_days': days, 'iv': [40.] * len(days)})
    return days, bars, calendar, tables


def last_feature(bars, calendar, tables):
    return list(p5.features('AAA', bars, set(calendar), calendar, tables))[-1]


class P5Tests(unittest.TestCase):
    def test_native_30m_features_match_original_a4(self):
        days, bars, calendar, tables = fixture()
        day, reason, record = last_feature(bars, calendar, tables)
        self.assertIsNone(reason)
        expanded = {d: [(p3.GRID[i * 6 + j], *bar[1:5], bar[5] / 6)
                        for i, bar in enumerate(values) for j in range(6)] for d, values in bars.items()}
        old = p3.features('AAA', expanded, days, tables, True, False, set(), None, (day, day))[0]
        self.assertEqual(p3.signal(record, p5.NAME), p3.signal(old, p5.NAME))
        self.assertAlmostEqual(record['rvol30'], 1.75)
        self.assertEqual(record['rvol30_days'], days[-15:-1])
        for key in ('thrust', 'drive_z', 'above_c1', 'p10', 'iv', 'sigma_rem'):
            self.assertEqual(record[key], old[key], key)
        record['rvol30'] = 1.5
        self.assertIsNotNone(p3.signal(record, p5.NAME))
        record['rvol30'] = 1.499
        self.assertIsNone(p3.signal(record, p5.NAME))

    def test_session_grid_half_days_cutoff_and_invalid_values(self):
        days, bars, calendar, _ = fixture()
        def raw(day):
            return [dict(zip(('time_key', 'open', 'high', 'low', 'close', 'volume'),
                             (day + ' ' + bar[0], *bar[1:]))) for bar in bars[days[-1]]]
        rows = raw(days[-1])
        self.assertEqual(list(p5.sessions(rows, calendar)[0]), [days[-1]])
        for bad in (rows[:-1], rows + rows[:1], [dict(rows[0], high=float('nan'))] + rows[1:]):
            self.assertEqual(p5.sessions(bad, calendar)[0], {})
        self.assertEqual(p5.sessions(rows, dict(calendar, **{days[-1]: 'MORNING'}))[0], {})
        self.assertEqual(p5.sessions(raw('2026-09-28'), calendar), ({}, set()))

    def test_warmup_previous_day_and_14_in_20_boundaries(self):
        days, bars, calendar, tables = fixture()
        self.assertIsNone(last_feature({d: bars[d] for d in days[-26:]}, calendar, tables)[1])
        self.assertEqual(last_feature({d: bars[d] for d in days[-25:]}, calendar, tables)[1],
                         'fewer_than_25_complete_prior_days')
        missing_previous = {d: b for d, b in bars.items() if d != days[-2]}
        self.assertEqual(last_feature(missing_previous, calendar, tables)[1], 'previous_market_day_not_complete')
        # Six incomplete market days still leave 14 complete days inside the previous 20.
        removed = set(days[-8:-2])
        sparse = {d: b for d, b in bars.items() if d not in removed}
        self.assertIsNone(last_feature(sparse, calendar, tables)[1])
        del sparse[days[-9]]
        self.assertEqual(last_feature(sparse, calendar, tables)[1], 'baseline_14_outside_20_market_days')

    def test_previous_day_liquidity_and_iv_age(self):
        days, bars, calendar, tables = fixture()
        nominal, volume, _ = tables
        yesterday = days[-2]
        self.assertEqual(last_feature(bars, calendar, ({}, volume, tables[2]))[1], 'nominal_t1_close_missing_or_invalid')
        self.assertEqual(last_feature(bars, calendar, (nominal, dict(volume, **{yesterday: 999.}), tables[2]))[1],
                         'option_volume_t1_below_1000')
        for iv_day, expected in (('2026-07-03', None), ('2026-07-02', 'iv_missing_or_stale'),
                                 ('2026-07-10', 'iv_missing_or_stale')):
            self.assertEqual(last_feature(bars, calendar, (nominal, volume, {'iv_days': [iv_day], 'iv': [40.]}))[1], expected)
        for day in days[:-1]:
            bars[day][0] = (*bars[day][0][:5], 0.)
        self.assertEqual(last_feature(bars, calendar, tables)[1], 'opening_volume_baseline_invalid')

    def test_exit_uses_next_30m_bar_and_same_bar_stop_first(self):
        _, bars, _, _ = fixture()
        path = list(bars['2026-07-10'])
        path[0] = ('10:00:00', 100., 110., 90., 100., 1000.)
        path[1] = ('10:30:00', 100., 101.2, 99.4, 100., 1000.)
        for side in (1, -1):
            result = p4.first_touch_from(path, 0, 100., .01, side)
            self.assertEqual(result[:3], (-.5, False, True))
            self.assertEqual(result[4], 1)

    def test_cap_thirds_and_all_four_frozen_gates(self):
        selected = [dict(symbol='S%d' % i, market_cap_b=i) for i in range(8)]
        groups = p5.cap_groups(selected)
        self.assertEqual([groups['S%d' % i] for i in range(8)],
                         ['missing', 'small', 'small', 'small', 'middle', 'middle', 'large', 'large'])
        passing = dict(picks=40, payoff_lo90=.01, edge_lo90=.01, target_rate=.30)
        self.assertTrue(all(p5.gates(passing).values()))
        for key, value in (('picks', 39), ('payoff_lo90', 0), ('edge_lo90', 0), ('target_rate', .299)):
            self.assertFalse(all(p5.gates(dict(passing, **{key: value})).values()))
        self.assertFalse(p5.summary([])['passed'])

    def test_checksums_fail_before_loading_payloads(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'k30.json').write_text('[]', encoding='utf-8')
            (root / 'CHECKSUMS.sha256').write_text('0' * 64 + '  k30.json\n', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'checksum'):
                p5.verified_inputs(root)
            (root / 'manifest.json').write_text(json.dumps({'status': 'incomplete'}), encoding='utf-8')
            (root / 'selection.json').write_text('{}', encoding='utf-8')
            names = ('k30.json', 'manifest.json', 'selection.json')
            (root / 'CHECKSUMS.sha256').write_text(''.join(p5.sha256(root / name) + '  ' + name + '\n'
                                                        for name in names), encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'collection is incomplete'):
                p5.verified_inputs(root)


if __name__ == '__main__':
    unittest.main()
