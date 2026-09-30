"""Synthetic fixtures verify exact arithmetic, complete sessions and checksum guards."""
from decimal import Decimal
import json
from pathlib import Path
import tempfile
import unittest

from studies.us_0dte_picks import parity


class ParityTests(unittest.TestCase):
    def test_exact_aggregation_and_audit_rejects_unverified_input(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            bars5 = [dict(code='US.AAA', time_key='2026-09-25 ' + clock,
                          open=100, high=101, low=99, close=100, volume=10, turnover=1000.001)
                     for clock in parity.GRID]
            bars30 = [dict(code='US.AAA', time_key='2026-09-25 ' + clock,
                           open=100, high=101, low=99, close=100, volume=62, turnover=6000.006)
                      for clock in parity.GRID30]
            # Matching 13 and 78 close timestamps; volume differs deliberately.
            for name, rows in (('AAA.K_5M.json', bars5), ('AAA.K_30M.json', bars30)):
                (root / name).write_text(json.dumps(rows), encoding='utf-8')
            checksums = root / 'CHECKSUMS.sha256'
            checksums.write_text(''.join(parity.sha256(p) + '  ' + p.name + '\n' for p in sorted(root.glob('*.json'))))
            report = parity.audit(root)
            self.assertFalse(report['strict_parity'])
            self.assertEqual(report['daily']['fields']['volume']['max_absolute_delta'], 26)
            self.assertEqual(report['blocks']['fields']['turnover']['different'], 0)
            self.assertEqual(report['opening']['fields']['volume']['max_relative_delta'], Decimal(2) / 60)
            self.assertEqual(report['symbols']['AAA']['k30']['complete_days'], ['2026-09-25'])
            self.assertEqual(report['block_anomalies'], [])
            # Duplicate clocks must fail even if the checksum matches.
            bars30[-1] = bars30[-2]
            path = root / 'AAA.K_30M.json'
            path.write_text(json.dumps(bars30), encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'Checksum mismatch'):
                parity.audit(root)
            checksums.write_text(''.join(parity.sha256(p) + '  ' + p.name + '\n' for p in sorted(root.glob('*.json'))))
            with self.assertRaisesRegex(ValueError, 'Duplicate timestamp'):
                parity.audit(root)
            # A partial session must never become a complete day by count alone.
            path.write_text(json.dumps(bars30[:-1]), encoding='utf-8')
            _, complete, coverage = parity.sessions(path, 'AAA', parity.GRID30)
            self.assertEqual(complete, {})
            self.assertEqual(coverage['excluded_days'][0]['bars'], 12)


if __name__ == '__main__':
    unittest.main()
