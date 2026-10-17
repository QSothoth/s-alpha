import unittest
from studies.trader_common.run_minute import ma_exit_enabled,pit_mode
class MinuteRuleTests(unittest.TestCase):
 def test_residual_ma_only_after_target(self):
  for v in ('CM1','CM0','DN0'):
   self.assertFalse(ma_exit_enabled(v,False));self.assertTrue(ma_exit_enabled(v,True))
  self.assertFalse(ma_exit_enabled('DN1',True));self.assertTrue(ma_exit_enabled('JL1',False))
 def test_jlaw_unknown_not_swing(self):
  rows={'AAPL':[{'available_on_or_after':'2026-01-02','metrics':{'ttm_net_income':{'status':'OK','value':1}}}]}
  self.assertIsNone(pit_mode(rows,'US.AAPL','2026-01-03')[0])
 def test_future_filing_not_visible(self):
  keys=('ttm_net_income','ttm_operating_cash_flow','ttm_free_cash_flow','revenue_quarter_yoy')
  row={'available_on_or_after':'2026-01-03','metrics':{k:{'status':'OK','value':1} for k in keys}}
  self.assertIsNone(pit_mode({'AAPL':[row]},'US.AAPL','2026-01-02')[0]);self.assertEqual(pit_mode({'AAPL':[row]},'US.AAPL','2026-01-03')[0],'position')
 def test_known_negative_is_swing(self):
  keys=('ttm_net_income','ttm_operating_cash_flow','ttm_free_cash_flow','revenue_quarter_yoy');m={k:{'status':'OK','value':1} for k in keys};m['ttm_free_cash_flow']['value']=-1
  self.assertEqual(pit_mode({'AAPL':[{'available_on_or_after':'2026-01-03','metrics':m}]},'US.AAPL','2026-01-03')[0],'swing')
