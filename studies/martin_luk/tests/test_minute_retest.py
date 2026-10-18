"""Only information already available at a five-minute close may trigger entry."""
import unittest
from types import SimpleNamespace

import numpy as np

from studies.martin_luk.minute_retest import trigger_day,weekly_levels,normalize_bars,minute_indicators,first_break,cap_signal_stream,reentry_day,minute_priority,minute_kind,hourly_support,entry_stop
from studies.martin_luk.minute_retest import ledger_pairs,replayed_placebo,weekly_reclaim_watch
from studies.martin_luk.replicate import bought


class MinuteRetestTests(unittest.TestCase):
    def test_rank_group_management_and_actual_cap_work_together(self):
        from studies.trader_replication import system as Y
        bars=np.array([[10,10,10,10,1,100],[10,10,10,10,1,100]],float)
        px={k:np.array([[10.,10.],[11.,11.]]) for k in ('open','high','low','close')}
        px.update(codes=np.array(['FAST','LIQUID']),dates=np.array(['2025-01-02 09:40','2025-01-02 09:45']),
                  session=np.array([0,0]),daily_close=np.array([False,True]))
        rules=Y.Rules(risk=.05,max_position=.5,max_gross=1,max_new_long=1,
                      buy_cost=0,sell_cost=0,margin_rate=0,trims=(),trail='',
                      management_by_kind={'thin':{'max_position':.2,'trims':(3,5),'trim_frac':.15,
                                                   'trail':'e9','add_r':0,'add_levels':()}})
        for mode,code,profit in [(None,'LIQUID',.05),('gain','FAST',.02)]:
            entries=[]
            for j,prior_close,turnover in [(0,9.,50e6),(1,9.9,200e6)]:
                priority=minute_priority(bars,1,prior_close,turnover,mode)
                kind=minute_kind('signal',{'liquidity_groups':True},turnover)
                entries.append((priority,j,1,10.,9.,kind))
            _,_,trades=Y.simulate(px,{},rules,[entries,[]],px['dates'][0],px['dates'][-1],audit=True)
            self.assertEqual(len(trades),1);self.assertEqual(trades[0]['code'],code)
            self.assertAlmostEqual(trades[0]['pnl'],profit)

    def test_first_opening_range_uses_completed_close_and_original_eligibility(self):
        bars=np.array([[10,10.2,9.9,10,1,1],[10,10.3,10,10.2,1,1],
                       [10.2,10.5,10.1,10.4,1,1],[10.4,99,1,90,1,1]],np.float32)
        flags=(True,False,False,False,False,False)
        args=(flags,(20,10,8,7,np.nan,.05,1000),.05,.01,1)
        self.assertIsNone(trigger_day(bars[:3],*args))
        self.assertIsNone(trigger_day(bars[:2],*args,trigger_mode='opening_range'))
        trace=[];hit=trigger_day(bars,*args,trigger_mode='opening_range',trace=trace)
        self.assertEqual(hit[0],2);self.assertEqual(hit[1],float(bars[2,3]))
        self.assertEqual(trace,['opening_range'])
        self.assertEqual(hit,trigger_day(bars[:3],*args,trigger_mode='opening_range'))
        self.assertIsNone(trigger_day(bars[:3],(False,)*6,*args[1:],trigger_mode='opening_range'))
        missing=np.vstack([np.full((1,6),np.nan),bars[:3]])
        self.assertEqual(trigger_day(missing,*args,trigger_mode='opening_range')[0],3)
        old_args=((True,True,False,False,False,False),(10.1,10,8,7,np.nan,.05,1000),.05,.01,1)
        self.assertEqual(trigger_day(bars,*old_args),trigger_day(bars,*old_args,trigger_mode='opening_range'))

    def test_weekly_reclaim_uses_prior_close_and_requires_scan_and_pool(self):
        days=np.array(['2025-01-06','2025-01-07','2025-01-08','2025-01-09','2025-01-10',
                       '2025-01-13','2025-01-14','2025-01-15'])
        close=np.full((8,4),10.);close[5:]=11
        pool=np.ones_like(close,bool);pool[:,2]=False
        scanned=np.ones_like(pool);scanned[:,1]=False
        watch=np.zeros_like(pool);watch[:,3]=True
        a=dict(close=close,days=days)
        actual=weekly_reclaim_watch(a,pool,watch,scanned)
        self.assertFalse(actual[5,0]);self.assertTrue(actual[6,0])
        self.assertFalse(actual[:,1:3].any());self.assertTrue(actual[:,3].all())
        changed=dict(a,close=close.copy());changed['close'][6:]=1
        np.testing.assert_equal(weekly_reclaim_watch(changed,pool,watch,scanned)[:7],actual[:7])

    def test_reentry_recheck_waits_for_current_setup_and_preserves_first_entry(self):
        bars=np.array([[10,10.2,9.9,10,1,1],[10,10.5,10,10.4,1,1],
                       [10.4,10.4,9.7,9.9,1,1],[9.9,10.1,9.9,10,1,1],
                       [10,10.1,9.9,10,1,1],[10,10.1,9.9,10,1,1],
                       [10,10.25,10,10.2,1,1],[10.2,10.5,10.1,10.4,1,1]],np.float32)
        args=((True,True,False,False,False,False),(10.3,10,8,7,np.nan,.05,1000),.05,.01,1)
        old=reentry_day(bars,*args)
        self.assertEqual([h[0] for h in old],[1,6])
        for mode in ('setup','opening_range'):
            with self.subTest(mode=mode):
                trace=[];hits=reentry_day(bars,*args,reentry_mode=mode,trace=trace)
                self.assertEqual([h[0] for h in hits],[1,7])
                self.assertEqual(hits[0],old[0])
                self.assertEqual(trace,['watch','reentry'])
                self.assertEqual(reentry_day(bars[:7],*args,reentry_mode=mode),old[:1])
                fill=float(bars[7,3]);lod=float(bars[2,2])
                self.assertEqual(hits[1][2],min(max(lod,fill*.95),fill*.99))
        with self.assertRaises(ValueError):reentry_day(bars,*args,reentry_mode='unknown')

    def test_opening_range_reentry_keeps_waiting_above_original_first_bar_high(self):
        bars=np.array([[10,11,9.9,10,1,1],[10,10.5,10,10.4,1,1],
                       [10.4,10.4,9.7,9.9,1,1],[9.9,10.1,9.9,10,1,1],
                       [10,10.1,9.9,10,1,1],[10,10.1,9.9,10,1,1],
                       [10,10.25,10,10.2,1,1],[10.2,10.4,10.1,10.4,1,1],
                       [10.4,11.3,10.4,11.2,1,1]],float)
        args=((True,True,False,False,False,False),(10.3,10,8,7,np.nan,.05,1000),.05,.01,1)
        hits=reentry_day(bars,*args,reentry_mode='opening_range')
        self.assertEqual([h[0] for h in hits],[1,8])
        self.assertEqual([h[0] for h in reentry_day(bars[:8],*args,reentry_mode='opening_range')],[1])
        future=np.vstack([bars,[11.2,100,1,90,1,1]])
        self.assertEqual(reentry_day(future,*args,reentry_mode='opening_range')[:2],hits)

    def test_window_executions_use_both_bounds_and_do_not_count_carried_or_short(self):
        A=dict(codes=np.array(['US.X']),days=np.array(['2025-01-02','2025-01-03','2025-01-06','2025-01-07']))
        t=SimpleNamespace(id='A',entry_date='2025-01-03',precision='exact',outcome='win',r_multiple=2)
        loc={'select':[(t,0,0,2)],'validate':[(t,0,0,2)]}
        trades=[dict(code='US.X',entry=e,exit=z,side=s,executions=[]) for e,z,s in [
            ('2025-01-01','2025-01-07',1),('2025-01-02','2025-01-02',1),
            ('2025-01-03','2025-01-06',-1),('2025-01-06','2025-01-07',1),
            ('2025-01-07','2025-01-07',1)]]
        pairs=ledger_pairs(A,loc,trades)
        for p in pairs:
            self.assertEqual([x['entry'] for x in p['window_executions']],['2025-01-02','2025-01-06'])
            self.assertEqual(p['executions'],[])
            self.assertEqual(p['carried_this_date'],[dict(entry='2025-01-01',exit='2025-01-07')])
            self.assertEqual(bought(A,trades,loc[p['segment']]),1)
        exact=dict(code='US.X',entry='2025-01-03',exit='2025-01-03',side=1,executions=[{'action':'entry'}])
        p=ledger_pairs(A,loc,[exact])[0]
        self.assertEqual(len(p['executions']),1)
        self.assertEqual(p['executions'][0]['order_events'],exact['executions'])
        self.assertIn('executions',exact)

    def test_frozen_random_reuse_rejects_changed_real_account_or_draws(self):
        keys=('total','by_year','2026_jan_jul','behavior','bought','bought_entry_date','march_start')
        st=dict.fromkeys(keys,1);ref=dict(st,placebo=dict(draws=31,seed=1,median=-.2))
        self.assertEqual(replayed_placebo(st,ref,31,1),ref['placebo'])
        for key in keys:
            with self.assertRaises(AssertionError):replayed_placebo(dict(st,**{key:2}),ref,31,1)
        with self.assertRaises(AssertionError):replayed_placebo(st,ref,30,1)
        with self.assertRaises(AssertionError):replayed_placebo(st,ref,31,2)

    def test_origin_trace_is_passive_and_reentry_is_not_a_new_watch_trigger(self):
        bars=np.array([[10.1,10.2,10,10.1,1,1],[10.1,10.4,10.1,10.3,1,1],
                       [10.3,10.3,9.7,9.9,1,1],[9.9,10.1,9.9,10,1,1],
                       [10,10.1,9.9,10,1,1],[10,10.1,9.9,10,1,1],
                       [10,10.3,10,10.2,1,1]],float)
        args=((True,True,False,False,True,False),(10.25,10.1,8,7,np.nan,.05,1000),.05,.01,1)
        trace=[];hits=reentry_day(bars,*args,trace=trace)
        self.assertEqual(hits,reentry_day(bars,*args))
        self.assertEqual(trace,['watch+leader','reentry'])
        prefix=[]
        self.assertEqual(trigger_day(bars[:2],*args,trace=prefix),hits[0])
        self.assertEqual(prefix,trace[:1])

    def test_default_stop_preserves_existing_float32_first_entry_arithmetic(self):
        bars=np.array([[10,10.2,9.8,10,1,1],[10,10.5,10,10.4,1,1]],np.float32)
        expected=min(max(bars[0,2],bars[1,3]*.95),bars[1,3]*.99)
        self.assertEqual(entry_stop(bars,1,bars[0,2],.05,.01),expected)
        hit=trigger_day(bars,(True,True,False,False,False,False),(10.3,10,8,7,np.nan,.05,1000),.05,.01,1)
        self.assertEqual(hit[2],float(expected))

    def test_structural_stop_prefers_lod_and_never_moves_wide_structure_to_cap(self):
        bars=np.array([[10.2,10.4,10.1,10.2,1,1],[10.2,10.5,10.2,10.3,1,1]],float)
        self.assertAlmostEqual(entry_stop(bars,1,10.1,.05,.01,'bar3'),10.1)
        bars[0,2]=9.5
        self.assertIsNone(entry_stop(bars,1,9.5,.05,.01,'lod3'))
        self.assertAlmostEqual(entry_stop(bars,1,9.5,.05,.01,'bar3'),10.3*.99)
        bars[1,2]=9.6
        self.assertIsNone(entry_stop(bars,1,9.5,.05,.01,'bar3'))
        self.assertAlmostEqual(entry_stop(bars,1,9.5,.05,.01),10.3*.95)
        with self.assertRaises(ValueError):entry_stop(bars,1,9.5,.05,.01,'unknown')

    def test_structural_filter_waits_for_later_valid_trigger_not_a_fake_failed_trade(self):
        bars=np.array([[10,10.2,9.8,10,1,1],[10,10.4,10,10.3,1,1],
                       [10.3,10.3,9.9,10.08,1,1],[10,11,1,10.8,1,1]],float)
        args=((True,True,False,False,False,False),(10.05,10,8,7,np.nan,.05,1000),.05,.01,1)
        self.assertEqual(trigger_day(bars,*args)[0],1)
        self.assertIsNone(trigger_day(bars[:2],*args,stop_mode='lod3'))
        hit=trigger_day(bars,*args,stop_mode='lod3')
        self.assertEqual(hit,(2,10.08,9.8))
        self.assertEqual(hit,trigger_day(bars[:3],*args,stop_mode='lod3'))
        self.assertEqual(reentry_day(bars,*args,stop_mode='lod3')[0],hit)

    def test_structural_stop_uses_only_current_and_previous_completed_bar(self):
        bars=np.array([[10.2,10.4,10,10.3,1,1],[10.3,10.6,10.3,10.5,1,1],
                       [10.5,100,1,90,1,1]],float)
        hit=entry_stop(bars,1,9,.05,.01,'bar3')
        self.assertAlmostEqual(hit,10.3)
        self.assertEqual(hit,entry_stop(bars[:2],1,9,.05,.01,'bar3'))
        self.assertIsNone(entry_stop(bars,1,9,.005,.01,'bar3'))
        bars[0,:4]=np.nan
        self.assertEqual(hit,entry_stop(bars,1,9,.05,.01,'bar3'))

    def test_reentry_applies_structure_policy_to_each_new_attempt(self):
        bars=np.array([[10.1,10.2,10,10.1,1,1],[10.1,10.4,10.1,10.3,1,1],
                       [10.3,10.3,9.7,9.9,1,1],[9.9,10.1,9.9,10,1,1],
                       [10,10.1,9.9,10,1,1],[10,10.1,9.9,10,1,1],
                       [10,10.3,10,10.2,1,1]],float)
        args=((True,True,False,False,False,False),(10.25,10.1,8,7,np.nan,.05,1000),.05,.01,1)
        self.assertEqual([h[0] for h in reentry_day(bars,*args,stop_mode='lod3')],[1])
        hits=reentry_day(bars,*args,stop_mode='bar3')
        self.assertEqual([h[0] for h in hits],[1,6])
        self.assertEqual(hits[1][2],10.)
        self.assertEqual(hits[:1],reentry_day(bars[:6],*args,stop_mode='bar3'))

    def test_hourly_support_waits_for_completed_hour_and_carries_partial_session(self):
        bars=np.full((2,78,6),10.)
        bars[0,12:24,:4]=12
        bars[0,24:36,:4]=14
        bars[0,36:42,:4]=16
        bars[0,42:]=np.nan
        support=hourly_support(bars)
        self.assertTrue(np.isnan(support[0,:24]).all())
        self.assertAlmostEqual(support[0,24,0],10.4)
        self.assertAlmostEqual(support[0,24,1],10+2/11)
        self.assertAlmostEqual(support[0,41,0],11.12)
        self.assertAlmostEqual(support[1,0,0],12.096)
        changed=bars.copy();changed[0,30:,:4]=100
        np.testing.assert_equal(hourly_support(changed)[0,:30],support[0,:30])
        changed=bars.copy();changed[1]=200
        np.testing.assert_equal(hourly_support(changed)[0],support[0])

    def test_previous_bar_branch_keeps_eligibility_and_reentry_first_trigger(self):
        bars=np.array([[10,10.2,9.9,10,1,1],[10,10.5,10,10.4,1,1],
                       [10.4,11,10.4,10.8,1,1]],float)
        flags=(True,False,False,False,False,False)
        levels=(12,10,8,7,np.nan,.05,1000)
        self.assertIsNone(trigger_day(bars,flags,levels,.05,.01,1))
        args=(bars,flags,levels,.05,.01,1)
        hit=trigger_day(*args,trigger_mode='previous_bar')
        self.assertEqual(hit[:2],(1,10.4))
        self.assertEqual(reentry_day(*args,trigger_mode='previous_bar')[0],hit)
        self.assertEqual(trigger_day(bars[:2],*args[1:],trigger_mode='previous_bar'),hit)
        self.assertIsNone(trigger_day(bars,(False,)*6,levels,.05,.01,1,trigger_mode='previous_bar'))

    def test_hourly_pullback_requires_known_rising_support_touch_and_reclaim(self):
        bars=np.array([[10,10.2,9.9,10,1,1],[10,10.5,10,10.4,1,1]],float)
        args=(bars,(True,False,False,False,False,False),(12,10,8,7,np.nan,.05,1000),.05,.01,1)
        for line in (8,11,np.nan):
            self.assertIsNone(trigger_day(*args,trigger_mode='hourly_pullback',hourly=np.full((2,2),line)))
        support=np.full((2,2),10.)
        self.assertEqual(trigger_day(*args,trigger_mode='hourly_pullback',hourly=support)[:2],(1,10.4))
        with self.assertRaises(ValueError):trigger_day(*args,trigger_mode='hourly_pullback')

    def test_hourly_new_branch_does_not_cross_missing_preceding_bar(self):
        bars=np.array([[10,10.2,9.9,10,1,1],[np.nan]*6,[10,10.5,10,10.4,1,1]],float)
        flags=(True,False,False,False,False,False);levels=(12,10,8,7,np.nan,.05,1000)
        for mode in ('previous_bar','hourly_pullback'):
            self.assertIsNone(trigger_day(bars,flags,levels,.05,.01,1,trigger_mode=mode,hourly=np.full((3,2),10.)))

    def test_minute_rank_uses_completed_prefix_and_keeps_chronological_priority(self):
        bars=np.array([[10,11,10,11,100,1000],[11,12,11,12,100,2000],
                       [12,13,12,13,100,900000]],float)
        for mode,score in [('gain',-.2),('rvol',-.03)]:
            rank=minute_priority(bars,1,10,100000,mode)
            self.assertAlmostEqual(rank[0],score)
            changed=bars.copy();changed[2]=[100,200,100,200,1e9,1e9]
            self.assertEqual(rank,minute_priority(changed,1,10,100000,mode))
        a=minute_priority(bars,0,10,100000,'gain')
        b=minute_priority(bars,1,10,200000,'gain')
        self.assertLess(b,a)
        capped=cap_signal_stream([[(a,'early')],[(b,'late')]],1)
        self.assertEqual(capped,[[(a,'early')],[]])

    def test_minute_liquidity_boundary_and_invalid_volume_bar(self):
        self.assertEqual(minute_kind('signal',{'liquidity_groups':True},100e6-1),'thin')
        self.assertEqual(minute_kind('signal',{'liquidity_groups':True},100e6),'premier')
        self.assertEqual(minute_kind('signal',{},1),'signal')
        bars=np.array([[10,10,10,10,100,1000],[np.nan,np.nan,np.nan,np.nan,1e6,1e9]],float)
        self.assertEqual(minute_priority(bars,1,10,100000,'rvol'),(-.01,-100000.))

    def test_reentry_waits_for_failed_setup_and_three_completed_new_bars(self):
        bars=np.array([[10,10.2,9.8,10,100,1000],[10,10.5,10,10.4,100,1000],
                       [10.4,10.4,9.7,9.9,100,1000],
                       [9.9,10.1,9.9,10,100,1000],[10,10.1,9.9,10,100,1000],
                       [10,10.1,9.9,10,100,1000],[10,10.3,10,10.2,100,1000],
                       [10.2,10.5,10.1,10.4,100,1000]],float)
        args=((True,True,False,False,False,False),(10.3,10,10,9,np.nan,.05,10000),.05,.01,1)
        hits=reentry_day(bars,*args)
        self.assertEqual([h[0] for h in hits],[1,6])
        self.assertEqual(hits[0],trigger_day(bars,*args))
        self.assertEqual(hits[:1],reentry_day(bars[:6],*args))
        self.assertEqual(hits,reentry_day(bars[:7],*args))
        changed=bars.copy();changed[7,:4]=[10.2,100,1,50]
        self.assertEqual(reentry_day(changed,*args),hits)
        # A missing completed bar invalidates the new range.
        changed=bars.copy();changed[4]=np.nan
        self.assertEqual(len(reentry_day(changed[:7],*args)),1)
        # Calling the next session starts a fresh state, not an inherited failed setup.
        self.assertEqual(reentry_day(bars,*args),hits)

    def test_entry_bar_low_cannot_retroactively_fail_a_new_setup(self):
        bars=np.array([[10,10.2,9.8,10,100,1000],[10,10.5,8,10.4,100,1000]]+
                      [[10.4,10.5,10.3,10.4,100,1000]]*3+
                      [[10.4,10.7,10.3,10.6,100,1000]],float)
        args=((True,True,False,False,False,False),(10.3,10,10,9,np.nan,.05,10000),.05,.01,1)
        self.assertEqual(len(reentry_day(bars,*args)),1)

    def test_raw_cap_uses_chronology_then_priority_and_resets_next_session(self):
        stream=[[(2,'a'),(1,'b')],[(0,'c'),(-1,'d')],[(-5,'e')],[(0,'f')],[(0,'g')],[]]
        capped=cap_signal_stream(stream,3,bars_per_session=3)
        self.assertEqual(capped,[[(1,'b'),(2,'a')],[(-1,'d')],[],[(0,'f')],[(0,'g')],[]])
        self.assertEqual(cap_signal_stream(stream[:2],3,bars_per_session=3),capped[:2])
        self.assertEqual(len(stream[1]),2)

    def test_zero_raw_cap_preserves_every_attempt_for_engine_and_daily_control(self):
        stream=[[(2,'a'),(1,'b')],[(0,'c')],[]]
        for bars in (1,78):
            self.assertEqual(cap_signal_stream(stream,0,bars),[[(1,'b'),(2,'a')],[(0,'c')],[]])
        with self.assertRaises(ValueError):
            cap_signal_stream(stream,-1)

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
