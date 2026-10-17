import unittest
from studies.ty_rajnus.events import events_for_symbol
class EventTests(unittest.TestCase):
 def test_first_causal_event_missing_horizon(self):
  rows=[{'end':'2026-01-01T16:00:00-05:00','close':10,'high':10,'volume':1},{'end':'2026-01-02T10:00:00-05:00','close':13,'high':13,'volume':200000},{'end':'2026-01-02T10:10:00-05:00','close':14,'high':15,'volume':200000}]
  r=events_for_symbol(rows,'X');self.assertEqual(len(r),1);self.assertIsNone(r[0]['forward_price_return_5m']);self.assertEqual(r[0]['borrow_status'],'UNKNOWN')
 def test_future_does_not_change_event(self):
  rows=[{'end':'2026-01-01T16:00:00-05:00','close':10,'high':10,'volume':1},{'end':'2026-01-02T10:00:00-05:00','close':13,'high':13,'volume':200000}]
  a=events_for_symbol(rows,'X')[0];b=events_for_symbol(rows+[{'end':'2026-01-02T10:05:00-05:00','close':1,'high':100,'volume':1}],'X')[0];self.assertEqual(a['at'],b['at']);self.assertEqual(a['price'],b['price'])
