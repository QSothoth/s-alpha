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
