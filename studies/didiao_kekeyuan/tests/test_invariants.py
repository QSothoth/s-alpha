import unittest, importlib.util
from pathlib import Path
p=Path(__file__).resolve().parents[1]/"evidence.py"
spec=importlib.util.spec_from_file_location("subject",p)
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
class Invariants(unittest.TestCase):
    def test_unknown_actions(self):
        with self.assertRaises(ValueError):m.turnover_lower_bound({}, {})
    def test_bound(self):
        self.assertEqual(m.turnover_lower_bound({'a':100},{'a':50,'b':20},True),70)
    def test_future_theme(self):
        with self.assertRaises(ValueError):m.theme_asof({'published_at':'2026','members':[]},'2025')

if __name__=="__main__":unittest.main()
