import copy,datetime,unittest
from studies.zhang_qi.replay import simulate,summary
class ReplayTests(unittest.TestCase):
    def fixture(self,n=45):
        start=datetime.date(2024,1,1);dates=[]
        while len(dates)<n:
            if start.weekday()<5:dates.append(str(start))
            start+=datetime.timedelta(days=1)
        raw={}
        for k in range(12):
            raw[str(k).zfill(6)]={d:dict(open=10+k*.1+i*.1,close=10+k*.1+i*.1,high=10+k*.1+i*.1+.02,low=10+k*.1+i*.1-.02,volume_provider=10000) for i,d in enumerate(dates)}
        return raw,dates
    def test_cash_reconciliation_lots_and_t1(self):
        raw,dates=self.fixture();run=simulate(raw,dates,'A_confirmation')
        self.assertTrue(run['trades'])
        for e in run['equity']:
            self.assertGreaterEqual(e['cash'],0);self.assertLessEqual(e['positions'],5)
            self.assertAlmostEqual(e['cash']+sum(p['quantity']*p['mark'] for p in e['inventory_lots'].values()),e['equity'])
        self.assertTrue(all(t['exit_date']>t['entry_date'] for t in run['trades']))
        self.assertTrue(all(f['quantity']%100==0 for f in run['fills'] if f['side']=='buy'))
        self.assertTrue(all(o['quantity']==0 for o in run['strict_orders']))
    def test_fees_reserved_and_reconciled(self):
        raw,dates=self.fixture();run=simulate(raw,dates,'A_confirmation',cost_bps=30)
        cash=1000000.
        for fill in run['fills']:
            self.assertAlmostEqual(cash,fill['cash_before'])
            self.assertAlmostEqual(fill['fee_assumption'],fill['quantity']*fill['price']*.003)
            cash+=fill['quantity']*fill['price']*(1 if fill['side']=='sell' else -1)-fill['fee_assumption']
            self.assertAlmostEqual(cash,fill['cash_after'])
        self.assertAlmostEqual(cash,run['equity'][-1]['cash'])

    def test_prefix_invariance(self):
        raw,dates=self.fixture();full=simulate(raw,dates,'A_confirmation');prefix=simulate(raw,dates[:30],'A_confirmation')
        self.assertEqual(prefix['equity'],full['equity'][:30])
        self.assertEqual(prefix['signals'],[s for s in full['signals'] if s['date']<dates[29]])
    def test_no_full_day_open_selection(self):
        raw,dates=self.fixture();a=simulate(raw,dates,'A_confirmation')
        first=a['fills'][0];day=first['filled_at'][:10];code=first['code'];op=raw[code][day]['open']
        raw[code][day].update(high=op,low=op,close=op,volume_provider=0)
        b=simulate(raw,dates,'A_confirmation');fill=next(f for f in b['fills'] if f['order_id']==first['order_id'])
        self.assertEqual(first['quantity'],fill['quantity']);self.assertEqual(first['price'],fill['price'])
        self.assertTrue(fill['ex_post_zero_volume_or_one_price'])
    def test_missing_next_open_cancels(self):
        raw,dates=self.fixture();a=simulate(raw,dates,'A_confirmation');first=a['fills'][0]
        del raw[first['code']][first['filled_at'][:10]]
        b=simulate(raw,dates,'A_confirmation')
        self.assertEqual(next(o for o in b['orders'] if o['order_id']==first['order_id'])['status'],'cancelled_missing_next_open')
    def test_split_preserves_cost_and_nav(self):
        raw,dates=self.fixture();base=simulate(raw,dates,'A_confirmation')
        held=base['equity'][24]['inventory_lots'];code=next(iter(held))
        for date in dates[25:]:
            for k in ('open','high','low','close'):raw[code][date][k]/=2
        split=dict(code=code,effective_session=dates[25],share_factor=2)
        run=simulate(raw,dates,'A_confirmation',splits=[split])
        ca=run['corporate_actions'][0]
        self.assertEqual(ca['new_quantity'],2*ca['old_quantity']);self.assertEqual(ca['cost_before'],ca['cost_after'])
        self.assertAlmostEqual(run['equity'][25]['equity'],base['equity'][25]['equity'])
    def test_reverse_split_ceil_credit(self):
        raw,dates=self.fixture();base=simulate(raw,dates,'A_confirmation')
        code=next(iter(base['equity'][24]['inventory_lots']));factor=.35806260
        for date in dates[25:]:
            for key in ('open','high','low','close'):raw[code][date][key]/=factor
        run=simulate(raw,dates,'A_confirmation',splits=[dict(code=code,effective_session=dates[25],share_factor=factor,rounding='ceil')])
        action=run['corporate_actions'][0]
        self.assertEqual(action['new_quantity']%1,0)
        self.assertGreaterEqual(action['rounding_credit_units'],0)
        self.assertLess(action['rounding_credit_units'],1)
        self.assertAlmostEqual(action['economic_value_rounding_residual'],action['rounding_credit_marked_value'])
        self.assertEqual(action['cost_before'],action['cost_after'])

    def test_pending_buy_signal_low_is_split_scaled(self):
        raw,dates=self.fixture();base=simulate(raw,dates,'A_confirmation')
        first=base['fills'][0];code=first['code'];day=first['filled_at'][:10];idx=dates.index(day)
        for d in dates[idx:]:
            for key in ('open','high','low','close'):raw[code][d][key]/=2
        run=simulate(raw,dates,'A_confirmation',splits=[dict(code=code,effective_session=day,share_factor=2)])
        self.assertEqual(run['equity'][idx]['inventory_lots'][code]['signal_low'],base['equity'][idx]['inventory_lots'][code]['signal_low']/2)

    def test_future_split_does_not_revise_earlier(self):
        raw,dates=self.fixture();a=simulate(raw,dates,'A_confirmation')
        b=simulate(raw,dates,'A_confirmation',splits=[dict(code='000000',effective_session='2030-01-01',share_factor=2)])
        self.assertEqual(a,b)
    def test_no_same_open_proceeds_in_buy_budget(self):
        raw,dates=self.fixture();run=simulate(raw,dates,'B_no_confirmation')
        previous_cash=1000000.
        for e in run['equity']:
            buys=[f for f in run['fills'] if f['side']=='buy' and f['filled_at'][:10]==e['date']]
            self.assertLessEqual(sum(f['price']*f['quantity'] for f in buys),previous_cash+1e-6)
            previous_cash=e['cash']
if __name__=='__main__':unittest.main()
