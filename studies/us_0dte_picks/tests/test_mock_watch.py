import unittest
from datetime import datetime
from custody.models import ET
from studies.us_0dte_picks.mock_watch import mark_job, observation_status

class MockWatchTests(unittest.TestCase):
    def test_failed_handoff_and_closed_entry_window_are_not_waiting(self):
        now=datetime(2026,9,29,11,0,5,tzinfo=ET)
        self.assertEqual(observation_status([],['failed'],now),'HANDOFF_FAILED')
        self.assertEqual(observation_status([],[],now),'NO_ENTRY')
        self.assertEqual(observation_status([{}],[],now),'OBSERVING')

    def test_bid_marks_fees_excluded_stale_quotes_and_realized_exit(self):
        now=datetime(2026,9,29,11,0,5,tzinfo=ET)
        job={'id':'test','contract':{'multiplier':100},'request':{'contract':'US.AAA260930P100000'},
             'state':'IN','position_qty':1,'entry_reason':'test','exit_reason':None,'attention':None}
        orders=[{'side':'BUY_OPEN','cumulative_qty':1,'average_option_price':2}]
        quote={'bid_price':2.5,'ask_price':2.6,'update_time':'2026-09-29 11:00:00'}
        row=mark_job(job,orders,quote,now)
        self.assertEqual((row['gross_pnl_usd'],row['gross_return_pct']),(50,25))
        self.assertFalse(row['orders_submitted'])
        self.assertIsNone(mark_job(job,orders,{},now)['gross_pnl_usd'])
        job.update(state='DONE',position_qty=0)
        orders.append({'side':'SELL_CLOSE','cumulative_qty':1,'average_option_price':2.2})
        closed=mark_job(job,orders,{},now)
        self.assertAlmostEqual(closed['gross_pnl_usd'],20)
        self.assertIsNone(closed['hold_counterfactual_gross_pnl_usd'])
        self.assertEqual(closed['fees'],'NOT_DEDUCTED')

if __name__=='__main__':
    unittest.main()
