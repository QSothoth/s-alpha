import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import unittest
from datetime import datetime,timedelta
from rules import Bar,aggregate,features,setups,entry_path
class RulesTest(unittest.TestCase):
    def test_complete_only(self):
        t=datetime(2026,1,1,9,30)
        bs=[Bar(t+timedelta(minutes=i),10,11,9,10,100) for i in range(5)]
        self.assertEqual(len(aggregate(bs)),1)
        self.assertEqual(aggregate(bs)[0].t,t+timedelta(minutes=5))
        self.assertEqual(aggregate(bs[:4]),[])
    def test_adverse_order(self):
        b=Bar(datetime(2026,1,1),10,12,8,11,100)
        self.assertEqual(entry_path(b,11,9),('ambiguous_entry_stop',11))
    def test_gap_reject(self):
        b=Bar(datetime(2026,1,1),12,13,11,12,100)
        self.assertEqual(entry_path(b,11,9)[0],'gap_cancel')
    def test_invalidate(self):
        b=Bar(datetime(2026,1,1),10,10,8,9,100)
        self.assertEqual(entry_path(b,11,9)[0],'invalidated')
    def test_prefix(self):
        t=datetime(2026,1,1,9,30)
        bs=[Bar(t+timedelta(minutes=5*i),10,11,9,10+i*.01,1000) for i in range(200)]
        self.assertEqual(features(bs)[:150],features(bs[:150]))
        self.assertEqual([x for x in setups(bs) if x['signal_at']<=bs[149].t.isoformat()],setups(bs[:150]))
    def test_float_fail_closed(self):
        self.assertEqual(setups([], 'strict'),[])
if __name__=='__main__':unittest.main()

class PositiveFixtureTest(unittest.TestCase):
    def test_positive_prefix_nonvacuous(self):
        t=datetime(2026,1,1,9,35)
        bs=[]
        for day in (1,2):
            for i in range(78 if day==1 else 27):
                bs.append(Bar(t.replace(day=day)+timedelta(minutes=5*i),10,10.02,9.98,10,100000))
        t=bs[-1].t+timedelta(minutes=5)
        bs += [Bar(t,10,10.25,9.99,10.2,100000),Bar(t+timedelta(minutes=5),10.2,10.5,10.19,10.45,110000),Bar(t+timedelta(minutes=10),10.4,10.42,10.3,10.35,30000)]
        signals=setups(bs)
        self.assertEqual(len(signals),1)
        extended=bs+[Bar(t+timedelta(minutes=15),10.35,10.6,10.3,10.5,100000)]
        self.assertEqual(signals,[x for x in setups(extended) if x['signal_at']<=bs[-1].t.isoformat()])
        self.assertEqual(setups(bs,'strict'),[])

class ReplayBatchTest(unittest.TestCase):
    def test_known_open_invalidation(self):
        self.assertEqual(entry_path(Bar(datetime(2026,1,1),8,11,8,10,100),10,9),('invalidated',None))
    def test_concurrent_future_close_cannot_resize(self):
        from unittest.mock import patch
        from replay import run
        t=datetime(2026,1,1,10,0)
        def signal(bs,variant):
            first=bs[0]
            start=t if first.o==10 else t+timedelta(minutes=5)
            trigger=first.o
            return [dict(signal_at=start.isoformat(),information_cutoff=start.isoformat(),setup_id=start.isoformat(),trigger=trigger,stop=trigger-1,volume_cap=100000,expiry=(start+timedelta(minutes=5)).isoformat(),variant=variant)]
        def simulate(future_close):
            data={'A':[Bar(t,10,10.1,9.9,10,10000),Bar(t+timedelta(minutes=5),10,500,9.9,future_close,10000)],'B':[Bar(t,20,20.1,19.9,20,10000),Bar(t+timedelta(minutes=5),20,20.1,19.9,20,10000)]}
            with patch('replay.setups',signal):
                summary,ledger,_,_=run(data,'domain',10,bar_minutes=5)
            self.assertAlmostEqual(summary['cash_reconciliation_error'],0,places=8)
            self.assertAlmostEqual(summary['pnl_reconciliation_error'],0,places=8)
            return [e['qty'] for e in ledger if e.get('symbol')=='B' and e['event']=='entry']
        self.assertEqual(simulate(10),simulate(500))
        self.assertTrue(simulate(10))
    def test_no_reentry_after_future_stop(self):
        from unittest.mock import patch
        from replay import run
        t=datetime(2026,1,1,10,0)
        def signal(bs,variant):
            return [dict(signal_at=u.isoformat(),information_cutoff=u.isoformat(),setup_id=u.isoformat(),trigger=10,stop=9,volume_cap=100000,expiry=(u+timedelta(minutes=5)).isoformat(),variant=variant) for u in (t,t+timedelta(minutes=5))]
        data={'A':[Bar(t,10,10.1,9.9,10,10000),Bar(t+timedelta(minutes=5),10,10.1,8,10,10000)]}
        with patch('replay.setups',signal):_,ledger,_,_=run(data,'domain',10,bar_minutes=5)
        self.assertEqual(len([e for e in ledger if e['event'] in ('entry','ambiguous_entry_stop')]),1)
    def test_future_stops_cannot_close_daily_gate(self):
        from unittest.mock import patch
        from replay import run
        t=datetime(2026,1,1,10,0)
        def signal(bs,variant):
            start=t if bs[0].o==10 else t+timedelta(minutes=5)
            price=bs[0].o
            return [dict(signal_at=start.isoformat(),information_cutoff=start.isoformat(),setup_id=start.isoformat(),trigger=price,stop=price-1,volume_cap=100000,expiry=(start+timedelta(minutes=5)).isoformat(),variant=variant)]
        data={f'A{i}':[Bar(t,10,10.1,9.9,10,10000),Bar(t+timedelta(minutes=5),10,10.1,8,10,10000)] for i in range(4)}
        data['Z']=[Bar(t,20,20.1,19.9,20,10000),Bar(t+timedelta(minutes=5),20,20.1,19.9,20,10000)]
        with patch('replay.setups',signal):_,ledger,_,_=run(data,'domain',10,bar_minutes=5)
        self.assertEqual(len([e for e in ledger if e.get('symbol')=='Z' and e['event']=='entry']),1)
    def test_zero_volume_cannot_fill(self):
        self.assertEqual(entry_path(Bar(datetime(2026,1,1),10,12,8,11,0),11,9),('waiting',None))
    def test_future_zero_volume_does_not_release_budget(self):
        from unittest.mock import patch
        from replay import run
        t=datetime(2026,1,1,10,0)
        def signal(bs,variant):
            return [dict(signal_at=t.isoformat(),information_cutoff=t.isoformat(),setup_id=t.isoformat(),trigger=10,stop=9.999,volume_cap=100000,expiry=(t+timedelta(minutes=5)).isoformat(),variant=variant)]
        def simulate(v):
            data={f'A{i:02d}':[Bar(t,10,10.1,10,10,10000)] for i in range(20)}
            data['A00']=[Bar(t,10,10.1,10,10,v)]
            data['Z']=[Bar(t,10,10.1,10,10,10000)]
            with patch('replay.setups',signal):_,ledger,_,_=run(data,'domain',10,bar_minutes=5)
            return [e['qty'] for e in ledger if e.get('symbol')=='Z' and e['event']=='entry']
        self.assertEqual(simulate(0),simulate(10000))
        self.assertTrue(simulate(0))
