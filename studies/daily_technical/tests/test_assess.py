import contextlib
import io
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from studies.daily_technical import assess as a


def sample(count=80):
    # Synthetic bars belong only in unit tests.
    start = datetime(2025, 1, 1)
    return [a.Bar((start + timedelta(days=i)).date().isoformat(),
                  100 + i, 102 + i, 99 + i, 101 + i, 1000) for i in range(count)]


def rows(bars):
    return [dict(date=b.day, open=b.open, high=b.high, low=b.low,
                 close=b.close, volume=b.volume) for b in bars]


class TechnicalTests(unittest.TestCase):
    def test_money_flow_known_values_and_flat_market(self):
        bars = sample()
        flow = a.money_flow(bars)
        self.assertAlmostEqual(flow['cmf21'], 1 / 3)
        self.assertEqual(flow['mfi14'], 100)
        falling = [a.Bar(b.day, 300-b.open, 300-b.low, 300-b.high,
                         300-b.close, b.volume) for b in bars]
        self.assertEqual(a.money_flow(falling)['mfi14'], 0)
        flat = [a.Bar(b.day, 100, 100, 100, 100, 1000) for b in bars]
        self.assertEqual(a.money_flow(flat)['cmf21'], 0)
        self.assertIsNone(a.money_flow(flat)['mfi14'])
        self.assertEqual(a.assess(flat, 'US.AAPL', {'adjustment': 'qfq'})['review']['stance'], 'check_data_first')

    def test_market_clock_and_dst(self):
        before = datetime(2026, 10, 14, 19, 0, tzinfo=timezone.utc)
        self.assertEqual(str(a.closed_through('US.AAPL', before)), '2026-10-13')
        self.assertEqual(str(a.closed_through('HK.00700', before)), '2026-10-14')
        self.assertEqual(str(a.closed_through('SH.600519', before)), '2026-10-14')
        after = before.replace(hour=21)
        self.assertEqual(str(a.closed_through('US.AAPL', after)), '2026-10-14')
        winter = datetime(2026, 12, 14, 21, 0, tzinfo=timezone.utc)
        self.assertEqual(str(a.closed_through('US.AAPL', winter)), '2026-12-13')

    def test_validation_excludes_unclosed_bars_and_rejects_bad_data(self):
        data = rows(sample())
        data.append(dict(date='2026-10-14', open=1, high=2, low=1, close=2, volume=1))
        now = datetime(2026, 10, 14, 19, tzinfo=timezone.utc)
        bars, metadata = a.clean(data, 'US.AAPL', now)
        self.assertEqual(len(bars), 80)
        self.assertEqual(metadata['ignored_after_cutoff'], 1)
        for changes in ({'volume': 'nan'}, {'high': 1}, {'close': -1}):
            bad = data.copy()
            bad[0] = dict(bad[0], **changes)
            with self.assertRaises(ValueError):
                a.clean(bad, 'US.AAPL', now)
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            a.clean(data + [dict(data[0], volume=999)], 'US.AAPL', now)
        with self.assertRaisesRegex(ValueError, '60'):
            a.clean(data[:20], 'US.AAPL', now)

    def test_pivot_confirmation_and_break_only_once(self):
        bars = [a.Bar(f'2025-01-{i+1:02}', 9, high, 8, 9, 100) for i, high in enumerate([10, 11, 15, 12, 11])]
        self.assertIsNone(a.smc(bars[:4])['swing_high'])
        pivot = a.smc(bars)['swing_high']
        self.assertEqual(pivot['pivot_date'], '2025-01-03')
        self.assertEqual(pivot['confirmed_date'], '2025-01-05')
        for day, close in ((6, 16), (7, 17), (8, 14), (9, 16)):
            bars.append(a.Bar(f'2025-01-{day:02}', close, close + 1, close - 1, close, 100))
        breaks = [e for e in a.smc(bars)['events_last_20_bars'] if e.get('pivot_date') == pivot['pivot_date']
                  and e['kind'] in ('structure_break', 'BOS', 'CHoCH')]
        self.assertEqual(len(breaks), 1)
        self.assertEqual(breaks[0]['date'], '2025-01-06')

    def test_fvg_is_partially_then_fully_filled(self):
        bars = [a.Bar('2025-01-01', 9, 10, 8, 9, 100),
                a.Bar('2025-01-02', 10, 13, 9, 12, 100),
                a.Bar('2025-01-03', 13, 14, 12, 13, 100)]
        self.assertEqual(a.smc(bars)['unfilled_fvg'][0]['lower'], 10)
        bars.append(a.Bar('2025-01-04', 12, 13, 11, 12, 100))
        self.assertEqual(a.smc(bars)['unfilled_fvg'][0]['upper'], 11)
        bars.append(a.Bar('2025-01-05', 11, 12, 10, 11, 100))
        self.assertEqual(a.smc(bars)['unfilled_fvg'], [])

    def test_price_and_volume_scale_do_not_change_classification(self):
        bars = sample()
        result = a.assess(bars, 'US.AAPL', {'adjustment': 'qfq'})
        scaled = [a.Bar(b.day, b.open*3, b.high*3, b.low*3, b.close*3, b.volume*100) for b in bars]
        other = a.assess(scaled, 'HK.00700', {'adjustment': 'qfq'})
        self.assertEqual(result['cycle']['stage'], other['cycle']['stage'])
        self.assertAlmostEqual(result['money_flow']['cmf21'], other['money_flow']['cmf21'])
        self.assertAlmostEqual(result['latest']['atr14']*3, other['latest']['atr14'])
        json.dumps(result, allow_nan=False)

    def test_cycle_distinguishes_pullback_extension_and_breakdown(self):
        bars = sample()
        for last, expected, stance in (
            (a.Bar(bars[-1].day, 179, 181, 171, 180, 1000), 'ema_crossback_candidate', 'review_entry_conditions'),
            (a.Bar(bars[-1].day, 180, 221, 179, 220, 1000), 'extended', 'avoid_chasing'),
            (a.Bar(bars[-1].day, 180, 181, 150, 151, 1000), 'wedge_drop_candidate', 'avoid_new_entry_for_now'),
        ):
            result = a.assess(bars[:-1] + [last], 'US.AAPL', {'adjustment': 'qfq'})
            self.assertEqual(result['cycle']['stage'], expected)
            self.assertEqual(result['review']['stance'], stance)

    def test_quality_overrides_entry_and_conflict_is_visible(self):
        bars = [a.Bar(b.day, b.open, b.high+5, b.low, b.close, b.volume) for b in sample()]
        result = a.assess(bars, 'US.AAPL', {'adjustment': 'qfq', 'calendar_days_since_bar': 10})
        self.assertEqual(result['review']['stance'], 'check_data_first')
        self.assertTrue(result['review']['conflicts'])
        self.assertEqual(a.assess(bars, 'US.AAPL', {'adjustment': 'raw'})['review']['stance'], 'check_data_first')

    def test_tencent_mapping_and_no_silent_raw_fallback(self):
        payload = {'data': {'sh600519': {'qfqday': [['2026-01-02', '10', '11', '12', '9', '100']]}}}
        def response(data):
            return io.BytesIO(json.dumps(data).encode())
        with patch.object(a.urllib.request, 'urlopen', return_value=response(payload)):
            data, meta = a.fetch_tencent('SH.600519', 300)
        self.assertEqual((data[0]['high'], data[0]['close']), ('12', '11'))
        self.assertEqual(meta['adjustment'], 'qfq')
        with patch.object(a.urllib.request, 'urlopen', return_value=response({'data': {'sh600519': {'day': []}}})):
            with self.assertRaises(ValueError):
                a.fetch_tencent('SH.600519', 300)
        hk = {'data': {'hk00700': payload['data']['sh600519']}}
        with patch.object(a.urllib.request, 'urlopen', return_value=response(hk)) as request:
            a.fetch_tencent('HK.00700', 300)
            self.assertIn('/hkfqkline/', request.call_args.args[0].full_url)

    def test_cli_partial_failure_and_offline_csv(self):
        metadata = dict(source='test', adjustment='qfq', warnings=[])
        with patch.object(a, 'fetch', side_effect=[(rows(sample()), metadata), RuntimeError('permission denied')]):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                status = a.main(['US.AAPL', 'HK.00700'])
        self.assertEqual(status, 1)
        result = json.loads(out.getvalue())['results']
        self.assertNotIn('error', result[0])
        self.assertIn('permission denied', result[1]['error'])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'bars.csv'
            path.write_text('date,open,high,low,close,volume\n' + '\n'.join(
                f'{b.day},{b.open},{b.high},{b.low},{b.close},{b.volume}' for b in sample()))
            with patch.object(a, 'fetch', side_effect=AssertionError('offline must not fetch')):
                out = io.StringIO()
                with contextlib.redirect_stdout(out):
                    self.assertEqual(a.main(['SH.600519', '--csv', str(path), '--csv-adjustment', 'qfq']), 0)
            self.assertEqual(json.loads(out.getvalue())['results'][0]['data']['source'], 'local_csv')


if __name__ == '__main__':
    unittest.main()
