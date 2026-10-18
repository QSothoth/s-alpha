"""R75 measurement timing; synthetic bars are test data only."""
import unittest
import hashlib
import tempfile
from pathlib import Path
from unittest.mock import patch
from copy import deepcopy

import numpy as np

from studies.martin_luk.measure import complete_trigger, behavior, calendar_profit, append_short_prices
from studies.trader_replication import system as Y
from studies.martin_luk.continue_round import failures, objective
from studies.martin_luk import replicate as R


class MeasurementTests(unittest.TestCase):
    def test_short_rejection_uses_previous_ema_and_previous_slope(self):
        a={'e9':np.array([[12.],[11.],[100.]]),'e21':np.array([[15.],[15.],[15.]]),
           'e50':np.array([[20.],[20.],[20.]]),'high':np.array([[10.],[10.],[11.1]]),
           'close':np.array([[10.],[10.],[10.9]])}
        pool=np.ones((3,1),bool)
        with patch.object(R,'short_signals',return_value={}),patch.object(R,'leader_shorts',return_value={}):
            self.assertTrue(R.short_masks(a,pool)['Z12'][2,0])
            a['e9'][2,0]=1.
            self.assertTrue(R.short_masks(a,pool)['Z12'][2,0])
            a['e9'][0,0]=10.
            self.assertFalse(R.short_masks(a,pool)['Z12'][2,0])

    def test_no_short_profit_is_zero_contribution_even_when_account_loses(self):
        st={'profit_by_calendar_year':{'2025':dict(short_profit=0,short_net_profit_share=None)}}
        self.assertEqual(objective(st,'2025_short_profit_share'),-.1)
        st['profit_by_calendar_year']['2025']['short_profit']=-.1
        self.assertEqual(objective(st,'2025_short_profit_share'),-float('inf'))

    def test_append_etf_prices_keeps_stock_columns_and_prior_risk_scale(self):
        days=np.array([f'2025-01-{d:02d}' for d in range(1,26)])
        a={k:np.full((25,1),10.) for k in ('open','high','low','close','turnover','to20','adr','e9','e21','e50')}
        a.update(days=days,codes=np.array(['US.OLD']),market='us',has=np.ones((25,1),bool))
        em={k:a[k] for k in ('e9','e21','e50')};em['scale']=np.linspace(1,2,25)
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'ETF.csv'
            def write(last):
                p.write_text('date,open,high,low,close,turnover\n'+'\n'.join(
                    f'{day},{last if i==24 else 20},{last if i==24 else 20},{last if i==24 else 20},{last if i==24 else 20},1000'
                    for i,day in enumerate(days)))
                return {'US.ETF':dict(path=str(p),sha256=hashlib.sha256(p.read_bytes()).hexdigest())}
            out,ema,pool=append_short_prices(a,em,np.ones((25,1),bool),write(20))
            changed,_,_=append_short_prices(a,em,np.ones((25,1),bool),write(200))
        np.testing.assert_array_equal(out['close'][:,0],a['close'][:,0])
        np.testing.assert_array_equal(ema['scale'],em['scale'])
        np.testing.assert_array_equal(out['e9'][:-1,1],changed['e9'][:-1,1])
        self.assertEqual((pool.shape,out['codes'].tolist()),((25,2),['US.OLD','US.ETF']))

    def test_liquidity_group_uses_previous_turnover_and_preserves_entry_overrides(self):
        a={'to20':np.array([[99e6],[101e6],[1e9]])}
        entry=(0,0,1,10.,9.,'original',None,.2,.3)
        entries=[[],[entry],[entry]]
        grouped=R.liquidity_groups(a,entries)
        self.assertEqual([grouped[d][0][5] for d in (1,2)],['thin','premier'])
        self.assertEqual(grouped[1][0][6:],entry[6:])
        a['to20'][1,0]=1e9
        self.assertEqual(R.liquidity_groups(a,entries)[1],grouped[1])

    def test_real_benchmark_gate_and_risk_scale_use_only_previous_close(self):
        a={'market':'us','_benchmark_QQQ':np.array([[10.],[12.],[1.],[20.]])}
        pool=np.ones((4,1),bool)
        gate=R.market_ok(a,pool,pool,'QQQ50')
        self.assertTrue(gate[2])
        a['_benchmark_QQQ'][2,0]=100.
        self.assertTrue(R.market_ok(a,pool,pool,'QQQ50')[2])
        index=np.array([[10.],[10.1],[11.],[5.]])
        scale=R.index_risk_scale({},pool,index_close=index)
        self.assertEqual(scale[2],1.6)
        index[2,0]=100.
        self.assertEqual(R.index_risk_scale({},pool,index_close=index)[2],scale[2])

    def test_weekly_support_watchlist_is_decided_from_previous_close(self):
        a={'close':np.array([[11.],[9.],[12.]]),'stack':np.zeros((3,1),bool),
           'days':np.array(['2025-01-02','2025-01-03','2025-01-06']),
           'e50':np.full((3,1),10.),'to20':np.full((3,1),1e8),'adr':np.full((3,1),3.5)}
        with patch.object(R,'weekly_ema',return_value=np.full((3,1),10.)):
            np.testing.assert_array_equal(R.watch_lists(a)['V10'][:,0],[False,True,False])

    def test_ema21_reclaim_uses_prior_line_and_requires_completed_recovery(self):
        a={'open':np.array([[10.],[11.],[11.]]),'high':np.array([[10.],[11.],[11.]]),
           'low':np.array([[10.],[9.],[9.]]),'close':np.array([[10.],[10.5],[9.5]]),
           'e9':np.full((3,1),12.),'e21':np.full((3,1),10.),
           'adr':np.full((3,1),5.),'tight':np.zeros((3,1),bool)}
        np.testing.assert_array_equal(R.setups(a)['E21'][:,0],[False,True,False])
        a['e21'][1,0]=100.
        self.assertTrue(R.setups(a)['E21'][1,0])

    def test_potent_rank_uses_previous_day_gain_not_the_entry_day(self):
        a={'close':np.array([[10.,10.],[12.,9.],[6.,18.]])}
        score=R.priority_score(a,'prior_gain')
        np.testing.assert_allclose(score[2],[.2,-.1])
        a['close'][2]=[100.,1.]
        np.testing.assert_allclose(R.priority_score(a,'prior_gain')[2],score[2])

    def test_preregistered_behavior_objectives_measure_distance_not_more_is_better(self):
        scores=[]
        for share in (None,-.05,.05,.1,.2,.3,.4):
            st={'profit_by_calendar_year':{'2025':{'short_net_profit_share':share}}}
            scores.append(objective(st,'2025_short_profit_share'))
        np.testing.assert_allclose(scores,[-np.inf,-.15,-.05,0,0,0,-.1])
        self.assertEqual(objective({'behavior':{'2025':{'n':1000}}},'2025_count_distance'),-60)

    def test_calendar_profit_counts_old_long_and_current_short_in_same_year(self):
        price=np.array([[10.,10.],[12.,10.],[12.,9.]])
        p={k:price.copy() for k in ('open','high','low','close')}
        p.update(codes=np.array(['LONG','SHORT']),dates=np.array(['2024-12-31','2025-01-02','2025-01-03']))
        e=[[(0,0,1,10.,9.5,'x')],[(0,1,-1,10.,10.5,'x')],[]]
        rules=Y.Rules(trail='',trims=(),buy_cost=0,sell_cost=0,margin_rate=0)
        curve,dates,tr=Y.simulate(p,{},rules,e,p['dates'][0],p['dates'][-1],audit=True)
        a=dict(p,days=p['dates'])
        split=calendar_profit(a,tr,curve,dates,rules)['2025']
        self.assertAlmostEqual(split['long_profit'],.02)
        # Short sizing sees 1.02 equity when it opens, so its profit is 0.0102.
        self.assertAlmostEqual(split['short_profit'],.0102)
        self.assertAlmostEqual(split['short_net_profit_share'],.0102/.0302)
        self.assertAlmostEqual(split['financing_and_rounding'],0.)

    def test_structural_stop_filter_uses_prior_adr_and_no_future_lows(self):
        a=dict(close=np.full((3,1),10.),low=np.array([[9.8],[9.75],[1.]]),
               adr=np.array([[8.],[1.],[1.]]),to20=np.full((3,1),1e8))
        mask=np.array([[False],[True],[False]])
        first=R.entries_close_stop(a,mask,'skip',cap_max=.03,stop_min=.01)[1]
        self.assertEqual(len(first),1)
        self.assertAlmostEqual(first[0][4],9.75)
        a['adr'][1:]=1000; a['low'][2]=.01
        self.assertEqual(first,R.entries_close_stop(a,mask,'skip',cap_max=.03,stop_min=.01)[1])
        a['low'][1]=9.6
        self.assertEqual(R.entries_close_stop(a,mask,'skip',cap_max=.03)[1],[])
        self.assertAlmostEqual(R.entries_close_stop(a,mask,'cap',cap_max=.03)[1][0][4],9.7)
        a['low'][1]=9.75; a['adr'][0]=4
        self.assertEqual(R.entries_close_stop(a,mask,'skip',cap_max=.03)[1],[])

    def test_stop_floor_and_previous_low_only_use_known_bars(self):
        a=dict(close=np.array([[10.],[10.],[11.]]),low=np.array([[9.8],[9.99],[1.]]),
               adr=np.full((3,1),10.),to20=np.full((3,1),1e8))
        mask=np.array([[False],[True],[False]])
        e=R.entries_close_stop(a,mask,'cap',stop_min=.01,stop_floor_adr=.3)[1][0]
        self.assertAlmostEqual(e[4],9.7)
        e=R.entries_close_stop(a,mask,'cap',stop_min=.01,stop_floor_adr=.5)[1][0]
        self.assertAlmostEqual(e[4],9.5)
        e=R.entries_close_stop(a,mask,'cap',stop_min=.01,stop_reference='prior_low')[1][0]
        self.assertAlmostEqual(e[4],9.8)
        a['low'][2,0]=.01
        self.assertEqual(e,R.entries_close_stop(a,mask,'cap',stop_min=.01,stop_reference='prior_low')[1][0])
        a['low'][0,0]=10.1
        self.assertEqual(R.entries_close_stop(a,mask,'cap',stop_reference='prior_low')[1],[])

    def test_completed_close_not_touch_and_future_low_cannot_set_stop(self):
        bars = np.array([(10, 10.2, 9.9, 10), (10, 10.4, 9.95, 10.1),
                         (10.1, 10.6, 10, 10.5), (10.5, 10.6, 8, 9)])
        b, fill, stop, out = complete_trigger(bars, .05)
        self.assertEqual((b, fill), (2, 10.5))
        self.assertAlmostEqual(stop, 9.975)
        self.assertEqual(out, stop)
        self.assertEqual(complete_trigger(bars[:3], .05)[:3], (b, fill, stop))

    def test_later_gap_uses_open_and_entry_bar_low_does_not_stop_close_entry(self):
        bars = np.array([(10, 10.1, 9.9, 10), (10, 10.6, 8, 10.5), (9, 9.1, 8, 9)])
        self.assertEqual(complete_trigger(bars, .05)[3], 9)
        self.assertIsNone(complete_trigger(bars[:2], .05)[3])

    def test_calendar_and_session_holding_are_distinct(self):
        t = dict(entry='2025-01-03', exit='2025-01-06', ret=.1, days=1, pnl=.1, side=1)
        b = behavior([t])['2025']
        self.assertEqual((b['days_win'], b['calendar_days_win']), (1, 3))
        self.assertEqual(b['short_net_profit_share'], 0)

    def test_small_book_trims_before_first_ema_break_without_adding(self):
        px = dict(open=np.array([[10.], [10.], [11.]]), high=np.array([[10.], [11.1], [11.]]),
                  low=np.array([[10.], [10.], [10.6]]), close=np.array([[10.], [11.], [10.7]]),
                  codes=np.array(['TEST']), dates=np.array(['2025-01-02', '2025-01-03', '2025-01-06']))
        entries = [[(0, 0, 1, 10., 9.8, 'test')], [], []]
        rules = Y.Rules(risk=.01, max_position=.2, trims=(3, 5), trim_frac=.15,
                        trail='e9', buy_cost=0, sell_cost=0, margin_rate=0)
        curve, _, trades = Y.simulate(px, {'e9': np.array([[9.9], [10.5], [10.8]])}, rules,
                                     entries, '2025-01-02', '2025-01-06')
        self.assertAlmostEqual(curve[0], 1.)
        # 0.02 initial shares, 15% each at 10.6 and 11.0, rest at the EMA break close 10.7.
        self.assertAlmostEqual(trades[0]['pnl'], .02 * (.15 * .6 + .15 * 1 + .7 * .7))
        self.assertEqual((trades[0]['why'], trades[0]['days'], trades[0]['add_tries']), ('trail', 2, 0))

    def test_more_total_hits_cannot_hide_lost_segment_or_worse_holding(self):
        ref = dict(total=2, placebo={'median': 0}, bought={'select': [5, 42], 'validate': [2, 40]},
                   bought_entry_date={'select': [3, 42], 'validate': [1, 40]},
                   behavior={'2024': {'days_win': 20}, '2025': {'n': 229, 'days_win': 22}},
                   march_start={'2024': .05})
        st = deepcopy(ref)
        st['bought'] = {'select': [20, 42], 'validate': [1, 40]}
        st['behavior']['2025']['days_win'] = 23
        self.assertEqual(failures(st, ref), ['bought_validate', '2025_holding_distance'])
        st = deepcopy(ref)
        st['behavior']['2025']['n'] = 1700  # overshooting the target is not a frequency improvement
        st['march_start']['2024'] = .04
        self.assertEqual(failures(st, ref), ['2025_count_distance', 'march_start'])


if __name__ == '__main__':
    unittest.main()
