import unittest, importlib.util
from pathlib import Path
p=Path(__file__).resolve().parents[1]/"accounting.py"
spec=importlib.util.spec_from_file_location("subject",p)
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
class Invariants(unittest.TestCase):
    def test_conversion_wait(self):
        lot=m.convert(1000,3,'2026-01-01','2026-01-02')
        self.assertEqual(lot['shares'],333)
        self.assertFalse(m.can_sell(lot,'2026-01-01'))
        self.assertTrue(m.can_sell(lot,'2026-01-02'))
    def test_deposit_not_profit(self):
        self.assertEqual(m.flow_neutral_pnl(1000000,4000000,3000000),0)

if __name__=="__main__":unittest.main()
