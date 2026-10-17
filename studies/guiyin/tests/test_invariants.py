import unittest, importlib.util
from pathlib import Path
p=Path(__file__).resolve().parents[1]/"accounting.py"
spec=importlib.util.spec_from_file_location("subject",p)
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
class Invariants(unittest.TestCase):
    def test_reconcile(self):
        self.assertTrue(m.reconcile(100,[{'qty':10,'mark':20}],50,250)['matches'])
    def test_deposit(self):
        self.assertEqual(m.flow_adjusted_pnl(100,160,50,0),10)

if __name__=="__main__":unittest.main()
