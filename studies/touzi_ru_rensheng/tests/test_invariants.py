import unittest, importlib.util
from pathlib import Path
p=Path(__file__).resolve().parents[1]/"risk.py"
spec=importlib.util.spec_from_file_location("subject",p)
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
class Invariants(unittest.TestCase):
    def test_locked_inventory(self):
        path=m.stress(100,10,0,700,.7,[-.1,-.1,-.1])
        self.assertTrue(all(x['inventory']==100 and not x['assumed_fill'] for x in path))
        self.assertLess(path[-1]['collateral_buffer'],0)
    def test_invalid(self):
        with self.assertRaises(ValueError):m.stress(100,10,0,700,2,[-.1])

if __name__=="__main__":unittest.main()
