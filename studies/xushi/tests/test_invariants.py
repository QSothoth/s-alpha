import unittest, importlib.util
from pathlib import Path
p=Path(__file__).resolve().parents[1]/"evidence.py"
spec=importlib.util.spec_from_file_location("subject",p)
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
class Invariants(unittest.TestCase):
    def test_revision(self):
        a={'product':'A','bar_end':'2020-01-01','observed_at':'2020-01-02','version':'v1','signal':1}
        b=dict(a,observed_at='2020-01-03',signal=0)
        self.assertEqual(len(m.revisions([a,b])),1)
    def test_future_reject(self):
        with self.assertRaises(ValueError):m.revisions([dict(product='A',bar_end='2021',observed_at='2020',version='v1',signal=1)])

if __name__=="__main__":unittest.main()
