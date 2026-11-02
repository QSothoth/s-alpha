import unittest

from studies.opportunity_events.hk_ccass_participants import parse


class CcassTest(unittest.TestCase):
    def test_snapshot_checks_date_and_keeps_participant_not_owner(self):
        page = '''<input name="originalShareholdingDate" value="2026/10/30">
        <input name="txtStockCode" value="02513">
        <table><tr><td>Participant ID:</td><td>A00003</td>
        <td>Name:</td><td>Custodian</td><td>Address:</td><td>Hong Kong</td>
        <td>Shareholding:</td><td>1,200</td><td>Percentage:</td><td>1.25%</td></tr></table>'''
        data = parse(page, "02513", "2026-10-30")
        self.assertEqual(data["participants"]["A00003"]["shares"], 1200)
        with self.assertRaises(ValueError):
            parse(page, "02513", "2026-10-29")


if __name__ == "__main__":
    unittest.main()
