import unittest,datetime
from studies.ryan_pierpont.strategy import signal
class LongBaseTest(unittest.TestCase):
 def test_63_and_126_distinct(self):
  hs=[dict(date='2024-01-05',open=95,high=100,low=90,close=95,volume=1000000) for i in range(70)]
  a=signal('X',hs,{},None,'P1_base63','2024-01-05');b=signal('X',hs,{},None,'P2_base126','2024-01-05')
  self.assertEqual(a[2]['base_sessions'],63);self.assertIsNone(b[2]);self.assertTrue(a[2]['selected'])
 def test_weekend_levels_fixed(self):
  hs=[dict(date='2024-01-05',open=95,high=100,low=90,close=95,volume=1000000) for i in range(70)];state={}
  signal('X',hs,state,None,'P1_base63','2024-01-05');hs.append(dict(date='2024-01-08',open=99,high=104,low=98,close=103,volume=1000000))
  result=signal('X',hs,state,None,'P1_base63','2024-01-08');self.assertEqual(result[0],90);self.assertEqual(result[2]['pivot'],100)
if __name__=='__main__':unittest.main()

class FundamentalTests(unittest.TestCase):
 def test_future_snapshot_inaccessible(self):
  import tempfile,json
  from pathlib import Path
  from studies.ryan_pierpont.fundamentals import SnapshotGate
  with tempfile.TemporaryDirectory() as td:
   p=Path(td)/'facts.jsonl';p.write_text(json.dumps({'symbol':'X','available_on_or_after':'2099-01-01','metrics':{}})+'\n')
   self.assertEqual(SnapshotGate(p).evaluate('X','2024-01-01')['status'],'UNKNOWN_NO_PRIOR_SNAPSHOT')
 def test_missing_is_unknown(self):
  import tempfile,json
  from pathlib import Path
  from studies.ryan_pierpont.fundamentals import SnapshotGate
  with tempfile.TemporaryDirectory() as td:
   p=Path(td)/'facts.jsonl';p.write_text(json.dumps({'symbol':'X','available_on_or_after':'2024-01-01','metrics':{'revenue_quarter_yoy':{'status':'OK','value':.5}}})+'\n')
   self.assertEqual(SnapshotGate(p).evaluate('X','2024-01-02')['status'],'UNKNOWN_METRIC')
