import unittest
from studies.trader_common.execution import Bar,Order,Engine
from studies.clement_ang.signals import screen,trigger_distance_ok,higher_low_setup
from studies.deepak_uppal.signals import screen as deepak
from studies.j_law.signals import holding_mode,volume_gate
from studies.mark_minervini.signals import vcp_annotations_ok

def bar(s='A',start='2026-06-01T10:00',end='2026-06-01T10:01',o=100,h=102,l=99,c=101,v=100000):return Bar(s,start,end,o,h,l,c,v)
def order(s='A',id='a',trigger=100,stop=95,**kw):return Order(id,s,'2026-06-01T09:59','2026-06-01T10:00','2026-06-01T16:00',trigger,stop,**kw)
class ExecutionTests(unittest.TestCase):
 def test_duplicate(self):
  e=Engine();self.assertTrue(e.submit(order()));self.assertFalse(e.submit(order()))
 def test_noncausal_order(self):
  with self.assertRaises(ValueError):Engine().submit(Order('x','A','2026-06-01T10:02','2026-06-01T10:00','2026-06-01T16:00',100,95))
 def test_no_precreation_fill(self):
  e=Engine();e.submit(order());e.process_bar(bar(start='2026-06-01T09:58',end='2026-06-01T09:59'));self.assertEqual(len(e.fills),0)
 def test_gap_entry_and_stop(self):
  e=Engine();e.submit(order());e.process_bar(bar(o=110,h=112,l=108,c=111));self.assertEqual(e.fills[0]['price'],110)
  e.process_bar(bar(start='2026-06-02T09:30',end='2026-06-02T09:31',o=90,h=94,l=89,c=92));self.assertEqual(e.fills[-1]['price'],90)
 def test_entry_bar_ambiguity(self):
  e=Engine();e.submit(order());e.process_bar(bar(o=99,h=102,l=94,c=101));self.assertTrue(any(x['event']=='ambiguous_entry_stop' for x in e.events));self.assertFalse(e.positions)
 def test_future_low_not_entry_filter(self):
  a,b=Engine(),Engine();a.submit(order());b.submit(order());a.process_bar(bar(l=99));b.process_bar(bar(l=90));self.assertEqual(a.fills[0]['qty'],b.fills[0]['qty']);self.assertEqual(a.fills[0]['price'],b.fills[0]['price'])
 def test_zero_volume_no_fill(self):
  e=Engine();e.submit(order());e.process_bar(bar(v=0));self.assertFalse(e.fills)
 def test_batch_order_invariance(self):
  a,b=Engine(),Engine()
  for e in (a,b):e.submit(order('A','a'));e.submit(order('B','b'))
  bars=[bar('A',h=1000,c=1000),bar('B')]
  a.process_batch(bars);b.process_batch(list(reversed(bars)))
  self.assertEqual(a.fills,b.fills);self.assertEqual(a.cash,b.cash)
  self.assertEqual(a.fills[0]['qty'],a.fills[1]['qty'])
 def test_single_stream_global_guard(self):
  e=Engine();e.process_bar(bar('A'))
  with self.assertRaises(ValueError):e.process_bar(bar('B'))
 def test_partial_target_remaining(self):
  e=Engine(participation=1)
  e.positions['A']={'id':'a','entry':100,'qty':100,'stop':90,'initial_stop':90,'entry_fee_per_share':0,'target':110,'target_done':False,'fraction':.5,'breakeven':False};e.marks['A']=100;e.cash=90000
  e.process_bar(bar(o=110,h=111,l=109,c=110,v=20))
  e.process_bar(bar(start='2026-06-01T10:01',end='2026-06-01T10:02',o=110,h=111,l=109,c=110,v=100))
  self.assertEqual(e.positions['A']['qty'],50);self.assertTrue(e.positions['A']['target_done'])
 def test_accounting(self):
  e=Engine();e.submit(order());e.process_bar(bar());n=e.nav[-1];self.assertAlmostEqual(n['cash']+n['market_value'],n['equity'])
class RuleTests(unittest.TestCase):
 def test_clement_layers(self):
  self.assertTrue(screen(100,90,80,50e6,3,3)['broad']);self.assertFalse(screen(100,90,80,50e6,3,3)['numeric_selected']);self.assertFalse(trigger_distance_ok(106,100,10));self.assertTrue(trigger_distance_ok(105.99,100,10))
 def test_deepak_pit(self):
  self.assertFalse(deepak(100,90,80,6,90,{'available_at':'2027','ttm_diluted_eps':2,'growth_industry_asof':True},'2026')['eligible'])
 def test_jlaw_unknown_not_weak(self):
  self.assertIsNone(holding_mode(None,'2026',True)['mode']);self.assertFalse(volume_gate(200,[100]*19));self.assertTrue(volume_gate(151,[100]*20))
 def test_future_vcp(self):
  a={'available_at':'2025','quality_pass':True,'contractions':[{'start':'2025-01','end':'2025-02','depth':10},{'start':'2025-03','end':'2027','depth':5}]}
  self.assertFalse(vcp_annotations_ok(a,'2026'))
if __name__=='__main__':unittest.main()

class BatchAdversarialTests(unittest.TestCase):
 def test_requested_size_independent_of_other_future_volume(self):
  out=[]
  for volume in (10,100000):
   e=Engine(cash=1000)
   e.submit(order('A','a',risk_fraction=.01,max_weight=1));e.submit(order('B','b',risk_fraction=.01,max_weight=1))
   e.process_batch([bar('A',v=volume),bar('B')])
   out.append([x['requested_qty_known_at_open'] for x in e.events if x['event']=='capacity_bound' and x['client_id']=='b'][0])
  self.assertEqual(out[0],out[1])
 def test_no_same_bar_reentry_from_prior_high(self):
  e=Engine();e.submit(order());e.process_bar(bar())
  e.submit(Order('new','A','2026-06-01T10:01','2026-06-01T10:01','2026-06-01T16:00',101,96))
  e.process_bar(bar(start='2026-06-01T10:01',end='2026-06-01T10:02',o=100,h=110,l=90,c=95))
  self.assertFalse(any(f['client_id']=='new' for f in e.fills))
