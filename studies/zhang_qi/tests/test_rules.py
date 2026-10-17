import unittest
from studies.zhang_qi.rules import eligible_product,technical_reversal,bottom_decile,exit_intent,execution_and_total_return_ready
class ETFTests(unittest.TestCase):
    def test_index_cannot_be_etf(self):
        self.assertFalse(eligible_product({'product_id':'SH.000300','kind':'index'},'2026-01-01'))
        self.assertFalse(eligible_product({},'2026-01-01'))
    def test_verified_product_does_not_require_cash_dividend_or_nav(self):
        m=dict(product_id='512170',kind='ETF',sector_etf=True,listed_by_date='2022-12-31',sellability='T+1')
        self.assertTrue(eligible_product(m,'2024-02-26'))
        self.assertFalse(execution_and_total_return_ready(m))
    def test_causal_prior_return(self):
        h=[{'close':10,'high':11,'low':9} for _ in range(21)]+[{'close':12,'high':13,'low':10}]
        f=technical_reversal(h)
        self.assertEqual(f['prior_20d_return'],0)
        self.assertTrue(f['confirmation'])
        h[-1]['close']=14
        self.assertEqual(technical_reversal(h)['prior_20d_return'],0)
    def test_decile_before_confirmation(self):
        f={str(i):{'prior_20d_return':i,'confirmation':i>0} for i in range(10)}
        self.assertEqual(bottom_decile(f),[])
        self.assertEqual(bottom_decile(f,False),['0'])
        self.assertEqual(bottom_decile(dict(list(f.items())[:9])),[])
    def test_exit(self):
        self.assertTrue(exit_intent(9,10,1))
        self.assertFalse(exit_intent(9,10,1,True))
        self.assertTrue(exit_intent(12,10,5,True))
if __name__=='__main__':unittest.main()
