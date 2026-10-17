import unittest, importlib.util
from pathlib import Path
p=Path(__file__).resolve().parents[1]/"screen.py"
spec=importlib.util.spec_from_file_location("subject",p)
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
class Invariants(unittest.TestCase):
    def test_nominal(self):
        self.assertTrue(m.eligible('SZ.300001',9.99))
        self.assertFalse(m.eligible('SZ.300001',10))
        self.assertFalse(m.eligible('SH.600001',5))

if __name__=="__main__":unittest.main()
