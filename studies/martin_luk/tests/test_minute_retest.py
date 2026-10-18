"""Only information already available at a five-minute close may trigger entry."""
import unittest

import numpy as np

from studies.martin_luk.minute_retest import trigger_day,weekly_levels,normalize_bars


class MinuteRetestTests(unittest.TestCase):
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
