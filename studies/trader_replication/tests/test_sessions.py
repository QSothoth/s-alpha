"""Same strategy on real intraday rows must retain daily management clocks."""
import unittest

import numpy as np

from studies.trader_replication import system as Y


def panel(rows, sessions, closes):
    a = np.array(rows, float)
    return dict(open=a[:, :1], high=a[:, 1:2], low=a[:, 2:3], close=a[:, 3:4],
                dates=np.array([f'2025-01-{sessions[i]+2:02d} {9+i:02d}:35' for i in range(len(a))]),
                codes=np.array(['TEST']), session=np.array(sessions), daily_close=np.array(closes))


class SessionTests(unittest.TestCase):
    def test_requested_entry_audit_records_rejections_without_changing_execution(self):
        p={k:np.full((3,3),10.) for k in ('open','high','low','close')}
        p.update(codes=np.array(['A','B','C']),dates=np.array(['2025-01-02 09:35','2025-01-02 09:40','2025-01-03 09:35']),
                 session=np.array([0,0,1]),daily_close=np.array([False,True,True]))
        entries=[[(0,0,1,10,9,'first')],[(0,0,1,10,9,'held'),(1,1,1,10,11,'bad'),
                   (2,1,1,10,9,'second'),(3,2,1,10,9,'capped')],[(0,2,1,10,9,'capacity')]]
        rule=Y.Rules(trail='',trims=(),max_new_long=2,risk=.1,max_position=.5,max_gross=1,
                     buy_cost=0,sell_cost=0,margin_rate=0)
        log={(c,d):[] for c,d in [('A','2025-01-02'),('B','2025-01-02'),('C','2025-01-02'),('C','2025-01-03')]}
        plain=Y.simulate(p,{},rule,entries,p['dates'][0],p['dates'][-1],audit=True)
        checked=Y.simulate(p,{},rule,entries,p['dates'][0],p['dates'][-1],audit=True,entry_audit=log)
        np.testing.assert_equal(plain[0],checked[0]);self.assertEqual(plain[2],checked[2])
        self.assertEqual([x['reason'] for x in log[('A','2025-01-02')]],['opened','already_held'])
        self.assertEqual([x['reason'] for x in log[('B','2025-01-02')]],['invalid_stop','opened'])
        self.assertEqual(log[('C','2025-01-02')][0]['reason'],'daily_success_cap')
        self.assertEqual(log[('C','2025-01-03')][0]['reason'],'no_capacity')

    def test_short_first_partial_does_not_force_full_exit_on_day_three(self):
        c=np.array([10,9.6,9.4,9.2,9.,9.1])[:,None]
        p={k:c.copy() for k in ('open','high','low','close')}
        p.update(codes=np.array(['S']),dates=np.array([f'2025-01-{i+2:02d}' for i in range(6)]))
        ema={'e9':np.array([10.1,9.8,9.6,9.4,9.2,9.05])[:,None]}
        rules=Y.Rules(short_trims=(3,5),short_max_days=0,arm_trail_on_entry=True,
                      management_by_kind={'short':dict(trim_frac=.15)})
        _,_,tr=Y.simulate(p,ema,rules,[[(0,0,-1,10.,10.2,'short')]]+[[]]*5,
                           p['dates'][0],p['dates'][-1],audit=True)
        events=tr[0]['executions']; initial=events[0]['shares']
        self.assertEqual([e['time'] for e in events if e['action']=='trim'],[p['dates'][2],p['dates'][4]])
        for event in events:
            if event['action']=='trim': self.assertAlmostEqual(event['shares']/initial,.15)
        self.assertEqual((tr[0]['exit'],tr[0]['why']),(p['dates'][5],'trail'))

    def test_entry_kind_keeps_its_partials_trail_and_add_policy_in_placebo(self):
        p={k:np.repeat(np.array([10,16,13,13.])[:,None],2,axis=1) for k in ('open','high','low','close')}
        p['open'][1]=10; p['low'][1]=10
        p.update(codes=np.array(['A','B']),dates=np.array(['2025-01-02','2025-01-03','2025-01-06','2025-01-07']))
        ema={'e9':np.array([[9,9],[14,14],[14,14],[14,14.]]),'e21':np.full((4,2),9.)}
        rules=Y.Rules(trail='e21',trims=(10,),add_levels=(2,),risk=.1,max_position=.5,
                      arm_trail_on_entry=True,buy_cost=0,sell_cost=0,margin_rate=0,
                      management_by_kind={'thin':dict(max_position=.2,trims=(3,5),trim_frac=.15,
                                                      trail='e9',add_r=0,add_levels=())})
        entries=[[(0,0,1,10.,9.,'thin'),(1,1,1,10.,9.,'premier')],[],[],[]]
        _,_,tr=Y.simulate(p,ema,rules,entries,p['dates'][0],p['dates'][-1],audit=True)
        thin=next(t for t in tr if t['kind']=='thin'); premier=next(t for t in tr if t['kind']=='premier')
        self.assertAlmostEqual(thin['executions'][0]['shares']*10,.2)
        self.assertEqual([e['price'] for e in thin['executions'] if e['action']=='trim'],[13,15])
        self.assertEqual((thin['why'],thin['exit'],thin['add_tries']),('trail',p['dates'][2],0))
        self.assertEqual((premier['why'],premier['add_tries']),('end',1))
        entries[0]=entries[0][:1]
        _,_,tr=Y.simulate(p,ema,rules,entries,p['dates'][0],p['dates'][-1],audit=True,
                         placebo=np.random.default_rng(1),pool=np.ones((4,2),bool))
        self.assertEqual((tr[0]['kind'],tr[0]['why'],tr[0]['add_tries']),('thin','trail',0))

    def test_opened_feedback_uses_prior_close_and_freezes_before_today_stop(self):
        p={k:np.full((4,4),10.) for k in ('open','high','low','close')}
        p.update(codes=np.array(['A','B','C','D']),dates=np.array(['2025-01-02','2025-01-03','2025-01-06','2025-01-07']))
        for k in ('open','high','low','close'):
            p[k][:,0]=[10,12,8,8]
        entries=[[(0,0,1,10.,9.,'a')],[],[(0,1,1,10.,9.,'b'),(1,2,1,10.,9.,'c')],
                 [(0,3,1,10.,9.,'d')]]
        rules=Y.Rules(trail='',trims=(),feedback=1,feedback_opened=True,risk=.01,
                      risk_low=.005,risk_high=.02,max_position=1,buy_cost=0,sell_cost=0,margin_rate=0)
        curve,_,tr=Y.simulate(p,{},rules,entries,p['dates'][0],p['dates'][-1],audit=True)
        by={t['code']:t for t in tr}
        for name in ('B','C'):
            self.assertAlmostEqual(by[name]['executions'][0]['shares']*10/curve[2],.2)
        # Latest opening C, still flat at yesterday's close, supersedes the older stopped A.
        self.assertAlmostEqual(by['D']['executions'][0]['shares']*10/curve[3],.1)

    def test_opened_feedback_keeps_same_day_stop_until_next_session(self):
        p=panel([(10,10,10,10)]*3,[0,0,1],[False,True,True])
        entries=[[(0,0,1,10.,9.,'a',9.)],[(0,0,1,10.,9.,'b',9.)],[(0,0,1,10.,9.,'c')]]
        rules=Y.Rules(trail='',trims=(),feedback=1,feedback_opened=True,risk=.01,
                      risk_low=.005,risk_high=.02,buy_cost=0,sell_cost=0,margin_rate=0)
        _,_,tr=Y.simulate(p,{},rules,entries,p['dates'][0],p['dates'][-1],audit=True)
        self.assertAlmostEqual(tr[0]['executions'][0]['shares'],.01)
        self.assertAlmostEqual(tr[1]['executions'][0]['shares'],.0099)
        self.assertAlmostEqual(tr[2]['executions'][0]['shares'],.0049005)

    def test_entry_close_can_arm_first_next_day_break_without_looking_forward(self):
        p=panel([(10,10,10,10),(10,10,9.8,9.8),(9.8,9.8,9.8,9.8)], [0,1,2],[True]*3)
        e=[[(0,0,1,10.,9.,'x')],[],[]]
        rules=Y.Rules(trims=(),arm_trail_on_entry=True)
        for entry_ema,expected in ((9.9,1),(10.1,2),(np.nan,2)):
            ema={'e9':np.array([[entry_ema],[9.9],[9.9]])}
            _,_,tr=Y.simulate(p,ema,rules,e,p['dates'][0],p['dates'][-1])
            self.assertEqual(tr[0]['exit'],p['dates'][expected])
        # The historical default remains a separate reference.
        _,_,tr=Y.simulate(p,{'e9':np.full((3,1),9.9)},Y.Rules(trims=()),e,p['dates'][0],p['dates'][-1])
        self.assertEqual(tr[0]['why'],'end')

    def test_successful_long_cap_ignores_existing_and_invalid_orders_but_allows_short(self):
        price=np.full((2,4),10.)
        p={k:price.copy() for k in ('open','high','low','close')}
        p.update(codes=np.array(['A','B','C','S']),dates=np.array(['2025-01-02','2025-01-03']))
        e=[[(0,0,1,10.,9.5,'x')],[(0,0,1,10.,9.5,'held'),(1,1,1,10.,11.,'invalid'),
              (2,1,1,10.,9.5,'valid'),(3,2,1,10.,9.5,'capped'),(4,3,-1,10.,10.5,'short')]]
        rules=Y.Rules(trail='',trims=(),max_new_long=1)
        _,_,tr=Y.simulate(p,{},rules,e,p['dates'][0],p['dates'][-1])
        self.assertEqual({t['code'] for t in tr},{'A','B','S'})

    def test_successful_cap_counts_same_day_stop_and_resets_only_next_session(self):
        p=panel([(10,10,10,10)]*3,[0,0,1],[False,True,True])
        e=[[(0,0,1,10.,9.5,'x',9.5)]]*3
        rules=Y.Rules(trail='',trims=(),max_new_long=1)
        _,_,tr=Y.simulate(p,{},rules,e,p['dates'][0],p['dates'][-1])
        self.assertEqual([t['entry'] for t in tr],[p['dates'][0],p['dates'][2]])

    def test_adds_only_at_daily_close_and_audit_keeps_actual_prices(self):
        p = panel([(10,10,10,10), (10,12,10,12), (12,12,11,11), (11,12,11,12)],
                  [0,0,0,1], [False,False,True,True])
        e = [[(0,0,1,10,9.5,'x')],[],[],[]]
        rule = Y.Rules(trail='', trims=(), add_levels=(2,4), max_position=10, max_gross=10,
                       buy_cost=0,sell_cost=0,margin_rate=0)
        _,_,tr = Y.simulate(p, {}, rule, e, p['dates'][0], p['dates'][-1], audit=True)
        self.assertEqual([x['price'] for x in tr[0]['executions'] if x['action']=='add'], [11,12])
        self.assertEqual(tr[0]['days'], 1)
        self.assertAlmostEqual(tr[0]['ret_invested'], 3/33)

    def test_holding_limit_uses_sessions_and_only_exits_at_session_close(self):
        p = panel([(10,10,10,10)]*4,[0,0,1,1],[False,True,False,True])
        e = [[(0,0,1,10,9.5,'x')],[],[],[]]
        _,_,tr = Y.simulate(p, {}, Y.Rules(trail='',trims=(),max_days=1), e,p['dates'][0],p['dates'][-1])
        self.assertEqual((tr[0]['exit'],tr[0]['days'],tr[0]['why']),(p['dates'][3],1,'time'))

    def test_margin_charged_once_per_session(self):
        p = panel([(10,10,10,10)]*4,[0,0,1,1],[False,True,False,True])
        e = [[(0,0,1,10,9.5,'x')],[],[],[]]
        rule = Y.Rules(trail='',trims=(),risk=.1,max_position=2,max_gross=2,buy_cost=0,sell_cost=0,
                       margin_rate=.252)
        curve,_,_ = Y.simulate(p,{},rule,e,p['dates'][0],p['dates'][-1])
        np.testing.assert_allclose(curve,[1,1,.999,.999])

    def test_next_bar_stop_is_same_day_and_close_signal_cannot_exit_early(self):
        p=panel([(10,10,9,10),(10,10,9.4,9.6),(10,10,10,10)], [0,0,0],[False,False,True])
        e=[[(0,0,1,10,9.5,'x')],[],[]]
        _,_,tr=Y.simulate(p,{},Y.Rules(trail='',trims=()),e,p['dates'][0],p['dates'][-1])
        self.assertEqual((tr[0]['days'],tr[0]['exit'],tr[0]['why']),(0,p['dates'][1],'stop'))
        p=panel([(10,10,10,10)]*3,[0,0,0],[False,False,True])
        _,_,tr=Y.simulate(p,{'exit':np.ones((3,1),bool)},Y.Rules(trail='',trims=(),exit_signal='exit'),
                          e,p['dates'][0],p['dates'][-1])
        self.assertEqual(tr[0]['exit'],p['dates'][2])


if __name__=='__main__':
    unittest.main()
