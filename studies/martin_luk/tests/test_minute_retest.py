"""Only information already available at a five-minute close may trigger entry."""
import unittest

import numpy as np

from studies.martin_luk.minute_retest import trigger_day,weekly_levels,normalize_bars,minute_indicators,first_break


class MinuteRetestTests(unittest.TestCase):
    def test_old_source_is_not_unadjusted_for_actions_after_its_fetch(self):
        days=np.array(['2025-01-02','2025-01-03'])
        bars=np.array([[[10,11,9,10,100,1000]],[[10,11,9,10,100,1000]]],float)
        normalize_bars(bars,days,np.array([10.,10.]),[('2025-01-06',.5,0.)],
                       source_asof='2025-01-03',target_factor=np.array([.5,.5]))
        np.testing.assert_equal(bars[0,0,:4],[5,5.5,4.5,5])

    def test_ledger_trigger_ignores_missing_adjacent_bar_and_future_low(self):
        bars=np.array([[10,10.2,9.8,10,100,1000],[np.nan]*6,
                       [10,10.4,9.7,10.3,100,1000],[10.3,10.6,10,10.5,100,1000],
                       [10.5,10.6,8,8.5,100,1000]],float)
        hit=first_break(bars,.05,.01)
        self.assertEqual(hit[:2],(3,10.5))
        self.assertEqual(hit,first_break(bars[:4],.05,.01))
        self.assertAlmostEqual(hit[2],9.975)

    def test_half_session_ema_is_available_at_1300_not_1600(self):
        close=np.zeros(156,bool);close[[41,155]]=True
        a=minute_indicators({'e9':np.array([[10.],[20.]])},close)['e9']
        self.assertTrue(np.isnan(a[40,0]))
        self.assertEqual(a[41,0],10)
        self.assertEqual(a[78,0],10)
        self.assertEqual(a[155,0],20)

    def test_vwap_restores_split_shares_but_cash_dividend_does_not_change_volume(self):
        days=np.array(['2025-01-02','2025-01-03'])
        for factor,volume,detail in ((.5,200,{'split_ratio':.5}),(.5,200,{'spin_off_ratio':.5}),(.9,100,{})):
            bars=np.array([[[10*factor,10*factor,10*factor,10*factor,volume,1000]],
                           [[10,10,10,10,100,1000]]],float)
            q=normalize_bars(bars,days,np.array([10.,10.]),[('2025-01-03',factor,0.)],
                             [dict(ex_div_date='2025-01-03',**detail)])
            self.assertEqual(q['vwap_outside'],0)
            self.assertTrue(np.isfinite(bars[:,:,:4]).all())

    def test_vwap_flags_bonus_adjusted_disagreement_without_deleting_provider_prices(self):
        days=np.array(['2025-01-02','2025-01-03'])
        bars=np.array([[[10,10,10,10,110,1100]],[[78.21,78.21,78.21,78.21,204,15174.54]]],float)
        q=normalize_bars(bars,days,np.array([11.,78.21]),[('2025-01-03',1/1.1,0.)],
                         [dict(ex_div_date='2025-01-03',per_share_div_ratio=10)])
        self.assertEqual(q['vwap_outside'],1)
        self.assertTrue(np.isfinite(bars[0,0,:4]).all())
        self.assertTrue(np.isfinite(bars[1,0,:4]).all())

    def test_minute_entry_arming_uses_previous_ema_until_completed_daily_close(self):
        close=np.zeros(156,bool);close[[77,155]]=True
        daily={'e9':np.array([[10.],[20.]]),'risk':np.array([1.,1.6])}
        a=minute_indicators(daily,close)
        self.assertTrue(np.isnan(a['e9'][:77]).all())
        np.testing.assert_equal(a['e9'][77:155],10)
        self.assertEqual(a['e9'][155,0],20)
        self.assertEqual(a['risk'][78],1.6)
        daily['e9'][1,0]=100
        np.testing.assert_equal(minute_indicators(daily,close)['e9'][:155],a['e9'][:155])

    def test_affine_actions_do_not_use_current_minute_close_as_conversion_factor(self):
        days=np.array(['2025-01-02','2025-01-03'])
        bars=np.array([[[1,5,1,5,100,100]],[[5,6,5,6,100,100]]],float)
        q=normalize_bars(bars,days,np.array([10.,6.]),[('2025-01-03',1.,-5.)])
        # Yesterday raw intraday low 6 became QFQ 1; ratio-adjusted low is 6*0.5 = 3, not 1.
        self.assertEqual(bars[0,0,2],3)
        self.assertEqual(q['malformed'],0)

    def test_zero_volume_and_close_outside_ohlc_are_not_tradable_bars(self):
        bars=np.array([[[10,10,10,11,100,1000],[10,10,10,10,0,0],[10,11,9,10,100,1000]]],float)
        q=normalize_bars(bars,np.array(['2025-01-02']),np.array([10.]),[])
        self.assertEqual(q,dict(malformed=1,zero_volume=1))
        self.assertTrue(np.isnan(bars[0,:2,:4]).all())
        self.assertEqual(bars[0,2,3],10)

    def test_bounce_needs_completed_close_and_future_low_cannot_change_stop(self):
        bars=np.array([(10,10.3,9.8,10,100,1000), (10,10.4,9.7,10.2,100,1000),
                       (10.2,10.6,10,10.5,100,1000), (10.5,10.6,8,9,100,1000)],float)
        flags=(True,False,True,True,False,False)
        levels=(11,10,9.9,9.8,np.nan,.05,10000)
        hit=trigger_day(bars,flags,levels,.05,.01,1)
        self.assertEqual(hit[:2],(2,10.5))
        self.assertEqual(hit,trigger_day(bars[:3],flags,levels,.05,.01,1))
        self.assertAlmostEqual(hit[2],9.975)

    def test_ep_waits_for_cumulative_volume_not_final_daily_volume(self):
        bars=np.array([(11,11.1,10.9,11,100,1000), (11,11.3,11,11.2,100,1000),
                       (11.2,11.5,11.1,11.4,100,4000)],float)
        flags=(False,False,False,False,False,True)
        levels=(10,10,10,9,np.nan,.05,5000)
        self.assertEqual(trigger_day(bars,flags,levels,.05,.01,1)[0],2)
        self.assertIsNone(trigger_day(bars[:2],flags,levels,.05,.01,1))

    def test_delay_does_not_forget_earlier_support_touch(self):
        bars=np.array([(10,10.3,9.8,10,100,1000), (10,10.4,9.7,10.2,100,1000),
                       (10.2,10.6,10,10.5,100,1000), (10.5,10.8,10.4,10.7,100,1000)],float)
        hit=trigger_day(bars,(True,False,True,True,False,False),(11,10,9.9,9.8,np.nan,.05,10000),.05,.01,3)
        self.assertEqual(hit[:2],(3,10.7))

    def test_weekly_level_does_not_see_later_daily_highs(self):
        a=dict(days=np.array(['2025-01-06','2025-01-13','2025-01-20','2025-01-21']),
               high=np.array([[12.],[11.],[10.5],[15.]]),low=np.array([[8.],[9.],[9.5],[10.]]),
               close=np.array([[10.],[10.],[10.],[14.]]))
        level=weekly_levels(a)
        self.assertEqual(level[2,0],11)
        a['high'][3,0]=100
        np.testing.assert_equal(weekly_levels(a)[:3],level[:3])


if __name__=='__main__':
    unittest.main()
