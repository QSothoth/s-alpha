import unittest
from studies.vibha_jha.strategy import signal
class ETFTest(unittest.TestCase):
 def test_not_growth_ticker(self):
  self.assertEqual(signal('AAPL',[],{},None,'V2_ma50','2024-01-01'),(None,None,None))
 def test_higher_low_needs_two_right_bars(self):
  hs=[dict(date=str(i),close=100,open=100,high=102,low=99,volume=1000) for i in range(62)];hs[-1]['low']=90;state={}
  signal('TQQQ',hs,state,None,'V3_ma50_higherlow','2024-01-01');self.assertEqual(state.get('lows',[]),[])
 def test_market_gate_blocks(self):
  hs=[dict(date=str(i),close=100,open=100,high=102,low=99,volume=1000) for i in range(62)];hs[-1]['close']=110
  a=signal('TQQQ',hs,{'market_recovery':False},None,'V2_ma50','2024-01-01');self.assertIsNone(a[0])
if __name__=='__main__':unittest.main()
