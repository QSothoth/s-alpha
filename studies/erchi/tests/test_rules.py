import unittest
from studies.erchi.rules import Bar, sma, repaired, pullback, buy_gate, Inventory, size_order
from studies.erchi.replay import generate_signals, evaluate

def b(c=10, low=9, high=11, op=None):
    return Bar(c if op is None else op,high,low,c,10000)

class RulesTests(unittest.TestCase):
    def test_ten_percent_sizing(self):
        self.assertEqual(size_order(100000, 100000, 10), 1000)
        self.assertEqual(size_order(100000, 500, 10), 0)
        self.assertEqual(size_order(100000, 3000, 10), 300)

    def test_complete_repair(self):
        self.assertTrue(repaired([b()]*5))
        self.assertFalse(repaired([b()]*4))
        self.assertFalse(repaired([b(),None,b(),b(),b()]))
    def test_missing_ma(self):
        self.assertIsNone(sma([b()]*9,10))
        self.assertIsNone(sma([b()]*9+[None],10))
        self.assertFalse(pullback([b()]*20,0))
    def test_unknown_eligibility(self):
        self.assertEqual(buy_gate(b(),10,10),'unknown_historical_eligibility')
        self.assertEqual(buy_gate(None,10,10),'missing_next_session')
        self.assertEqual(buy_gate(b(11),10,10),'gap_above_cap')
    def test_t1_locked_and_reconcile(self):
        inv=Inventory(10000)
        self.assertIsNone(inv.buy('X',1,10,100,True))
        self.assertEqual(inv.equity({'X':10}),10000)
        self.assertEqual(inv.sell('X',1,9),'t_plus_one')
        self.assertEqual(inv.sell('X',2,9,True),'limit_locked_pending')
        self.assertIn('X',inv.pending)
        self.assertIsNone(inv.sell('X',3,9))
        self.assertEqual(inv.equity({}),9900)
        self.assertFalse(inv.pending)
    def test_no_cash_or_odd_lot(self):
        inv=Inventory(100)
        self.assertEqual(inv.buy('X',1,10,100,True),'size_or_cash')
        self.assertEqual(inv.buy('X',1,1,1,True),'size_or_cash')
    def fixture(self):
        dates=[f'2020-01-{j:02}' for j in range(1,31)]
        index={d:100 for d in dates}
        index[dates[20]]=96
        for j in range(21,30):index[dates[j]]=96-(j-20)*.1
        series={'X':{d:b() for d in dates}}
        actions={'X':set()}
        return dates,index,series,actions
    def test_prefix_invariance_and_three_day_delay(self):
        dates,index,series,actions=self.fixture()
        full,_=generate_signals(series,actions,dates,index,'A_sma10')
        prefix,_=generate_signals(series,actions,dates[:26],{d:index[d] for d in dates[:26]},'A_sma10')
        self.assertEqual(prefix,[e for e in full if e['signal_index']<26])
        self.assertTrue(full)
        self.assertGreaterEqual(full[0]['signal_index'],24)
    def test_next_open_and_t1(self):
        dates,index,series,actions=self.fixture()
        ev,_=generate_signals(series,actions,dates,index,'A_sma10')
        # Entry day's close can trigger; sale must use subsequent open.
        series['X'][dates[25]]=b(9,8,11,10)
        series['X'][dates[26]]=b(9,8,11,9)
        out,ledger=evaluate(ev,series,actions,dates,'A_sma10')
        self.assertEqual(out[0]['entry_date'],dates[25])
        self.assertEqual(out[0]['exit_date'],dates[26])
        self.assertEqual(ledger[0]['filled_quantity'],0)
    def test_open_selection_does_not_use_entry_day_future(self):
        dates,index,series,actions=self.fixture()
        ev,_=generate_signals(series,actions,dates,index,'A_sma10')
        series['X'][dates[25]]=Bar(10,10,10,10,0)
        out,ledger=evaluate(ev,series,actions,dates,'A_sma10')
        self.assertEqual(out[0]['entry_date'],dates[25])
        self.assertTrue(out[0]['entry_ex_post_zero_volume_or_one_price'])
        self.assertEqual(ledger[0]['rejection_reason'],'unknown_historical_eligibility')

    def test_exit_open_does_not_use_exit_day_future(self):
        dates,index,series,actions=self.fixture()
        ev,_=generate_signals(series,actions,dates,index,'A_sma10')
        series['X'][dates[25]]=b(9,8,11,10)
        series['X'][dates[26]]=Bar(9,9,9,9,0)
        out,_=evaluate(ev,series,actions,dates,'A_sma10')
        self.assertEqual(out[0]['exit_date'],dates[26])
        self.assertTrue(out[0]['exit_ex_post_zero_volume_or_one_price'])

    def test_actions_censor_without_erasing_signal(self):
        dates,index,series,actions=self.fixture()
        ev,_=generate_signals(series,actions,dates,index,'A_sma10')
        actions['X'].add(dates[27])
        out,_=evaluate(ev,series,actions,dates,'A_sma10')
        self.assertEqual(out[0]['status'],'corporate_action_censored')
    def test_missing_entry_cancels(self):
        dates,index,series,actions=self.fixture()
        ev,_=generate_signals(series,actions,dates,index,'A_sma10')
        del series['X'][dates[25]]
        out,_=evaluate(ev,series,actions,dates,'A_sma10')
        self.assertEqual(out[0]['status'],'missing_next_session')

if __name__=='__main__':unittest.main()
