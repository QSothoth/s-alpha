import unittest
import gzip
from pathlib import Path
from tempfile import TemporaryDirectory

from studies.opportunity_events.hk_webb_ccass import Selector
from studies.opportunity_events.hk_webb_corrected_signals import latest_available
from studies.opportunity_events.hk_webb_enigma_tables import TableCopies
from studies.opportunity_events.hk_webb_pool import PoolSelector


class WebbSelectorTest(unittest.TestCase):
    def test_streams_snapshot_and_carries_unchanged_participants_forward(self):
        dump = (
            b"-- Dumping data for table `dailylog`\n"
            b"INSERT INTO `dailylog` VALUES "
            b"('2021-11-01',30520,1000,3,10,1,0,0,900,950,800,200),"
            b"('2022-01-25',30520,1100,3,20,1,0,0,990,1050,900,200);\n"
            b"-- Dumping data for table `holdings`\n"
            b"INSERT INTO `holdings` VALUES "
            b"(1323,30520,100,'2021-10-30'),(1323,30520,125,'2022-01-20'),"
            b"(1323,30520,130,'2022-02-01'),(460,30520,50,'2021-10-01'),"
            b"(999,12345,10,'2021-01-01');\n"
            b"-- Dumping data for table `participants`\n"
            b"INSERT INTO `participants` VALUES (1323,'A00003');\n"
            b"-- Dumping data for table `quotes`\n"
        )
        selector = Selector()
        for i in range(0, len(dump), 17):
            selector.feed(dump[i:i + 17])
        selector.feed(b"", final=True)
        self.assertEqual(selector.snapshots["30520:2021-11-01"]["1323"], ["2021-10-30", 100])
        self.assertEqual(selector.snapshots["30520:2022-01-25"]["1323"], ["2022-01-20", 125])
        self.assertEqual(selector.snapshots["30520:2022-01-25"]["460"], ["2021-10-01", 50])
        self.assertEqual(len(selector.south["30520:1323"]), 3)
        self.assertEqual(selector.daily["30520:2022-01-25"][0], 1100)
        self.assertIn(b"A00003", selector.participants)
        self.assertNotIn(b"quotes", selector.participants)

    def test_selected_enigma_tables_are_written_without_neighboring_tables(self):
        dump = (b"-- Dumping data for table `issuedshares`\n"
                b"INSERT VALUES (1,'2022-01-01',100);\n"
                b"-- Dumping data for table `other`\n"
                b"INSERT VALUES (99,'ignore');\n"
                b"-- Dumping data for table `stocklistings`\n"
                b"INSERT VALUES (1,'01024');\n")
        with TemporaryDirectory() as directory:
            copies = TableCopies(Path(directory))
            for i in range(0, len(dump), 13):
                copies.feed(dump[i:i + 13])
            copies.feed(b"", final=True)
            copies.close()
            with gzip.open(Path(directory) / "issuedshares.sql.gz", "rb") as file:
                issued = file.read()
            with gzip.open(Path(directory) / "stocklistings.sql.gz", "rb") as file:
                listings = file.read()
            self.assertIn(b"2022-01-01", issued)
            self.assertNotIn(b"ignore", issued)
            self.assertIn(b"01024", listings)
            self.assertNotIn(b"ignore", listings)

    def test_pool_keeps_only_selected_participants_and_a_pre_2020_baseline(self):
        dump = (b"-- Dumping data for table `dailylog`\n"
                b"INSERT VALUES ('2021-11-01',30520,1000,3,10,1,0,0,900,950,800,200);\n"
                b"-- Dumping data for table `holdings`\n"
                b"INSERT VALUES (1323,30520,50,'2019-01-01'),"
                b"(1323,30520,60,'2019-12-31'),(1323,30520,100,'2021-11-01'),"
                b"(999,30520,500,'2021-11-01'),(1323,99999,500,'2021-11-01');\n"
                b"-- Dumping data for table `parthold`\n")
        selector = PoolSelector({"30520": {}})
        for i in range(0, len(dump), 11):
            selector.feed(dump[i:i + 11])
        selector.feed(b"", final=True)
        self.assertEqual(selector.before["30520:1323"], ["2019-12-31", 60])
        self.assertEqual(selector.history["30520:1323"], [["2021-11-01", 100]])
        self.assertEqual(selector.daily["30520"]["2021-11-01"][0], 1000)
        self.assertEqual(len(selector.history), 1)

    def test_share_count_uses_only_records_available_on_observation_date(self):
        records = [("2021-11-30", 100, "2021-12-02 08:00:00"),
                   ("2021-12-31", 120, "2022-01-10 08:00:00")]
        self.assertEqual(latest_available(records, "2022-01-05")[1], 100)
        self.assertEqual(latest_available(records, "2022-01-10")[1], 120)


if __name__ == "__main__":
    unittest.main()
