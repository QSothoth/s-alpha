import datetime
import unittest

import numpy as np

from studies.trader_data import panel
from studies.trader_replication.martin_continue_dd import VerifiedPair, quality


def fixture():
    dates = [(datetime.date(2023, 1, 3) + datetime.timedelta(days=i)).isoformat() for i in range(500)]
    values = (10., 11., 9., 10.5, 100., 1050.)
    data = {symbol: {day: values for day in dates} for symbol in ('GLD', 'SLV')}
    return dates, data


class VerifiedEtfDatasetTests(unittest.TestCase):
    def test_standard_panel_reproduces_verified_price_and_volume(self):
        dates, raw = fixture()
        adjusted = {s: dict(rows) for s, rows in raw.items()}
        self.assertTrue(quality(adjusted['GLD'], raw['GLD'], dates)['eligible'])
        ds = VerifiedPair(raw, adjusted, dates, {'test': 'fixture'})
        result = panel.build(ds, cache=False, write_cache=False)
        self.assertEqual(result['codes'].tolist(), ['US.GLD', 'US.SLV'])
        self.assertEqual(result['days'].tolist(), dates)
        self.assertEqual(float(result['close'][0, 0]), 10.5)
        self.assertEqual(float(result['volume'][0, 0]), 100.)
        self.assertEqual(result['digest'], ds.digest())

    def test_missing_or_mismatched_raw_source_refuses_dataset(self):
        dates, raw = fixture()
        adjusted = {s: dict(rows) for s, rows in raw.items()}
        adjusted['GLD'][dates[20]] = (10., 11., 9., 10.6, 100., 1050.)
        self.assertFalse(quality(adjusted['GLD'], raw['GLD'], dates)['eligible'])
        with self.assertRaises(ValueError):
            VerifiedPair(raw, adjusted, dates, {})
        adjusted['GLD'][dates[20]] = raw['GLD'][dates[20]]
        del raw['SLV'][dates[30]]
        with self.assertRaises(ValueError):
            VerifiedPair(raw, adjusted, dates, {})

    def test_invalid_price_or_volume_is_not_an_eligible_bar(self):
        dates, raw = fixture()
        adjusted = {s: dict(rows) for s, rows in raw.items()}
        adjusted['SLV'][dates[0]] = (10., 9., 8., 10., 0., np.nan)
        report = quality(adjusted['SLV'], raw['SLV'], dates)
        self.assertFalse(report['eligible'])
        self.assertIn(dates[0], report['invalid_market_dates'])


if __name__ == '__main__':
    unittest.main()
