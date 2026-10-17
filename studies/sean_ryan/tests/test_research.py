import unittest,tempfile,json,csv
from pathlib import Path
from studies.sean_ryan.daily_engine import run,rsi
from studies.sean_ryan.strategy import signal
from studies.ryan_pierpont.strategy import signal as pierpont
from studies.vibha_jha.strategy import signal as vibha

CFG={'initial_cash':100000,'cost_bps':10,'commission_per_share':.005,'risk_fraction':.01,'max_weight':.2,'participation':.01}
def bar(d,o=100,h=102,l=99,c=101,v=1000000):return dict(date=d,open=o,high=h,low=l,close=c,volume=v)
class ResearchTests(unittest.TestCase):
 def simulate(self,bs,fn,variant='S2_second_wave',actions=None):
  with tempfile.TemporaryDirectory() as td:
   result=run({'X':{b['date']:b for b in bs}},actions or {},fn,CFG,variant,td)
   with (Path(td)/'trades.csv').open() as f:ts=list(csv.DictReader(f))
   with (Path(td)/'events.csv').open() as f:ev=list(csv.DictReader(f))
   return result,ts,ev
 def once(self,s,h,state,p,c,d):return (95 if len(h)==1 else None),None,None
 def test_next_open_not_signal_close(self):
  r,t,e=self.simulate([bar('2024-01-01'),bar('2024-01-02',o=105,h=106,l=100,c=104)],self.once)
  self.assertEqual(t[0]['signal_date'],'2024-01-01');self.assertAlmostEqual(float(t[0]['entry_price']),105.105)
 def test_entry_bar_stop_not_skipped(self):
  r,t,e=self.simulate([bar('2024-01-01'),bar('2024-01-02',l=90)],self.once)
  self.assertEqual(t[0]['reason'],'intraday_stop_conservative')
 def test_gap_can_exceed_risk(self):
  r,t,e=self.simulate([bar('2024-01-01'),bar('2024-01-02'),bar('2024-01-03',o=80,h=82,l=79,c=81)],self.once)
  self.assertEqual(t[0]['reason'],'gap_stop');self.assertLess(float(t[0]['realized_r']),-1)
 def test_fees_not_free(self):
  r,t,e=self.simulate([bar('2024-01-01',c=100),bar('2024-01-02',c=100)],self.once)
  self.assertLess(r['net_return'],0);self.assertGreater(r['transaction_costs'],0)
 def test_cash_identity(self):
  r,t,e=self.simulate([bar('2024-01-01'),bar('2024-01-02')],self.once)
  self.assertLess(r['accounting_error'],1e-6)
 def test_capacity_zero_volume(self):
  r,t,e=self.simulate([bar('2024-01-01',v=0),bar('2024-01-02')],self.once)
  self.assertEqual(r['trades'],0)
 def test_no_future_entry_without_next_bar(self):
  r,t,e=self.simulate([bar('2024-01-01')],self.once)
  self.assertEqual(r['trades'],0);self.assertEqual(r['pending_unexecuted_end'],1)
 def test_be_only_next_bar(self):
  r,t,e=self.simulate([bar('2024-01-01'),bar('2024-01-02',h=113,l=96,c=112),bar('2024-01-03',o=99,h=101,l=98,c=100)],self.once,'S3_second_be')
  self.assertEqual(t[0]['exit_date'],'2024-01-03');self.assertEqual(t[0]['reason'],'gap_stop')
 def test_known_split_preserves_ledger(self):
  r,t,e=self.simulate([bar('2024-01-01'),bar('2024-01-02'),bar('2024-01-03',o=50,h=51,l=49,c=50)],self.once,actions={'X':{'2024-01-03':(.5,0)}})
  self.assertLess(r['accounting_error'],1e-6);self.assertTrue(any(x['event']=='corporate_action' for x in e))
 def test_rsi_flat_and_up(self):
  self.assertEqual(rsi([bar(str(i),c=100) for i in range(20)]),50)
  self.assertEqual(rsi([bar(str(i),c=100+i) for i in range(20)]),100)
 def test_pierpont_requires_long_warmup(self):
  self.assertEqual(pierpont('X',[bar('2024-01-05')]*30,{},None,'P1_base63','2024-01-05'),(None,None,None))
 def test_signal_prefix_causal(self):
  import copy
  hs=[bar('2024-01-01',c=100+i*.1) for i in range(70)]
  a=signal('X',copy.deepcopy(hs),{},None,'S2_second_wave','2024-01-01')
  future=hs+[bar('2099-01-01',c=9999)]
  b=signal('X',copy.deepcopy(future[:70]),{},None,'S2_second_wave','2024-01-01');self.assertEqual(a,b)
if __name__=='__main__':unittest.main()
