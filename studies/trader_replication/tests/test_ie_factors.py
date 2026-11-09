"""Synthetic checks for the frozen IE experiment, independent of real labels."""
from datetime import date,timedelta
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import numpy as np

from studies.trader_replication import ie_factor_library as lib
from studies.trader_replication import ie_factor_models as models
from studies.trader_replication import martin_continue_ie_factors as f


def synthetic(length=420):
    rng=np.random.default_rng(43)
    c=30*np.exp(np.cumsum(rng.normal(.001,.025,length)));o=c*np.exp(rng.normal(0,.01,length))
    h=np.maximum(o,c)*1.02;l=np.minimum(o,c)*.98;v=rng.uniform(1e5,3e5,length)
    arrays=dict(o=o,h=h,l=l,c=c,v=v,t=c*v,raw_c=c)
    days=[];day=date(2023,1,2)
    while len(days)<length:
        if day.weekday()<5: days.append(day.isoformat())
        day+=timedelta(days=1)
    extras=dict(earn_days=np.arange(length,dtype=float),earn_index=np.zeros(length,dtype=int),
        pot=(np.arange(length)%19==0).astype(float))
    for k in ('iv','hv','option_volume','call_volume','put_volume','option_open_interest','call_open_interest','put_open_interest'):
        extras[k]=rng.uniform(20,100,length)
    return arrays,days,c*.9,extras


class FactorLibraryTest(unittest.TestCase):
    def test_full_inventory_has_every_implemented_metric_and_parameters(self):
        arrays,days,q,extras=synthetic();stock=lib.Stock(arrays,days,q,extras)
        specs=lib.inventory();self.assertEqual(sum(s.family=='original53' for s in specs),53)
        self.assertGreater(len(specs)*3,4000);self.assertEqual(len(lib.PATTERNS),61)
        for family,n in dict.fromkeys((s.family,s.parameter) for s in specs):
            with self.subTest(family=family,n=n),np.errstate(all='ignore'):
                values=stock.evaluate(family,n)
                expected={s.metric for s in specs if s.family==family and s.parameter==n}
                self.assertEqual(set(values),expected)
                self.assertTrue(all(v.shape==(len(days),) for v in values.values()))
        stock.ema.cache_clear();stock.f_hilbert.cache_clear()

    def test_all_families_ignore_prices_options_and_events_after_evening(self):
        arrays,days,q,extras=synthetic(240);stop=200
        other={k:v.copy() for k,v in arrays.items()}
        other_extras={k:v.copy() for k,v in extras.items()}
        for k in other: other[k][stop:]*=7
        for k in other_extras: other_extras[k][stop:]=777
        q2=q.copy();q2[stop:]*=3
        before=lib.Stock(arrays,days,q,extras);after=lib.Stock(other,days,q2,other_extras)
        short=lib.Stock({k:v[:stop] for k,v in arrays.items()},days[:stop],q[:stop],
            {k:v[:stop] for k,v in extras.items()})
        first={}
        for s in lib.inventory(): first.setdefault(s.family,s.parameter)
        for family,n in first.items():
            with self.subTest(family=family),np.errstate(all='ignore'):
                a,b,c=before.evaluate(family,n),after.evaluate(family,n),short.evaluate(family,n)
                for k in a:
                    np.testing.assert_allclose(a[k][:stop],b[k][:stop],equal_nan=True,err_msg=family+'.'+k)
                    np.testing.assert_allclose(a[k][:stop],c[k],equal_nan=True,err_msg=family+'.'+k)
        before.ema.cache_clear();before.f_hilbert.cache_clear()

    def test_average_ties_and_missing_neutral(self):
        np.testing.assert_allclose(f.percentile(np.array([1.,1.,2.,np.nan]))[:,0],[.25,.25,1.,.5])
        np.testing.assert_allclose(f.percentile(np.ones(4))[:,0],.5)

    def test_future_action_common_scale_cannot_shift_chip_bins(self):
        arrays,days,q,extras=synthetic(180)
        changed={k:v.copy() for k,v in arrays.items()}
        for k in ('o','h','l','c'): changed[k]*=.125
        changed['v']/=.125
        a=lib.Stock(arrays,days,q,extras);b=lib.Stock(changed,days,q,extras)
        for family,n in (('chips',20),('hilbert',4),('original53',0),('volume',20)):
            aa,bb=a.evaluate(family,n),b.evaluate(family,n)
            for k in aa: np.testing.assert_allclose(aa[k],bb[k],equal_nan=True,rtol=1e-7,atol=1e-8,err_msg=family+'.'+k)
        a.ema.cache_clear();a.f_hilbert.cache_clear()

    def test_history_rank_stops_at_each_own_evening(self):
        x=np.array([[1.,5.],[2.,4.],[3.,3.],[999.,999.]])
        np.testing.assert_allclose(lib.history_rank(x,[1,2]),[[1.,0.],[1.,0.]])

    def test_earnings_never_observe_future_events_or_afterhours_price(self):
        days=['2025-01-02','2025-01-03','2025-01-06']
        events=[dict(earnings_date='2025-01-03',pub_type='AFTER'),dict(earnings_date='2026-01-02',pub_type='BEFORE')]
        age,index=f.earnings_arrays(days,events)
        self.assertTrue(np.isnan(age[0]));self.assertEqual(age[1],0)
        self.assertEqual(index.tolist(),[-1,-1,2])


def query_meta():
    return dict(entries=[dict(id='a',code='A'),dict(id='b',code='A'),dict(id='c',code='Z')],
        eval_days=['2025-01-02','2025-01-03'],
        windows=[['2025-01-02','2025-01-03']]*3,
        scope={'2025-01-02':{'active300':['A','B']},'2025-01-03':{'active300':['C','D','E']}})


class ControlsTest(unittest.TestCase):
    def test_finish_entry_does_not_prepare_or_evaluate_A_or_train_B(self):
        with tempfile.TemporaryDirectory() as directory:
            work=Path(directory)
            for name,value in (('prepared.json',{'prepared_last':'2025-12-31'}),('a.json',{'saved':'A'}),
                               ('b.json',{'saved':'B'}),('run_manifest.json',{'unchanged':'input'})):
                (work/name).write_text(json.dumps(value))
            with mock.patch.object(f,'WORK',work),mock.patch.object(f,'OUTPUT',work/'result.json'), \
                 mock.patch.object(f,'guard'),mock.patch.object(f,'stamp',return_value={'unchanged':'input'}), \
                 mock.patch.object(f,'prepare',side_effect=AssertionError('prepare called')), \
                 mock.patch.object(f,'stage_a',side_effect=AssertionError('A rerun')), \
                 mock.patch.object(models,'run',side_effect=AssertionError('B retrained')),mock.patch.object(f,'finish') as finish:
                f.main('finish')
                finish.assert_called_once_with({'prepared_last':'2025-12-31'},{'saved':'A'},{'saved':'B'})

    def test_saved_factor_restores_evening_row_order_and_rejects_corruption(self):
        with tempfile.TemporaryDirectory() as directory,mock.patch.object(f,'WORK',Path(directory)):
            work=Path(directory);(work/'design').mkdir()
            meta={'eval_days':['2025-01-02','2025-01-03']}
            slices={'active300':{'2025-01-02':np.array([0,2]),'2025-01-03':np.array([3])}}
            path=work/'design/active300.7.npy';np.save(path,np.array([.1,.9,.5],np.float32))
            value=f.saved_factor(meta,'active300',7,slices,4)
            np.testing.assert_array_equal(value,np.array([.1,.5,.9,.5],np.float32))
            np.save(path,np.array([.1,np.nan,.5]))
            with self.assertRaises(ValueError): f.saved_factor(meta,'active300',7,slices,4)

    def test_C_report_ranks_must_match_saved_A(self):
        with tempfile.TemporaryDirectory() as directory,mock.patch.object(f,'WORK',Path(directory)):
            expected=np.array([[[2,4,5,f.SENTINEL]]],np.uint16)
            np.save(Path(directory)/'active300_ranks.npy',expected)
            rows=[{'nights':[{'rank':2},{'rank':4},{'rank':5},{'rank':None}]}]
            f.check_ahead_ranks('active300',0,rows)
            rows[0]['nights'][0]['rank']=1
            with self.assertRaises(AssertionError): f.check_ahead_ranks('active300',0,rows)

    def test_output_guard_allows_atomic_report_rename_and_rejects_data_write(self):
        callbacks=[]
        with mock.patch.object(f.sys,'addaudithook',side_effect=callbacks.append): f.guard()
        audit=callbacks[0]
        audit('os.rename',(str(f.OUTPUT.with_suffix('.json.tmp')),str(f.OUTPUT),-1,-1))
        with self.assertRaises(PermissionError):
            audit('open',(str(f.ROOT/'data/forbidden.csv'),'w',f.os.O_WRONLY|f.os.O_CREAT))

    def test_random_replacement_same_night_same_scope_and_shared_duplicate(self):
        meta=query_meta();keys=[(d,c) for d in meta['eval_days'] for c in meta['scope'][d]['active300']]
        index={k:i for i,k in enumerate(keys)}
        q=f.random_queries(meta,index,'active300')
        np.testing.assert_array_equal(q[:,0,:2],q[:,1,:2])
        for draw in q:
            for e in range(3):
                for w,day in enumerate(meta['windows'][e]):
                    d,c=keys[draw[e,w]];self.assertEqual(d,day);self.assertIn(c,meta['scope'][day]['active300'])

    def test_shuffled_labels_share_duplicate_and_stay_in_scope(self):
        meta=query_meta();keys=[(d,c) for d in meta['eval_days'] for c in meta['scope'][d]['active300']]
        q=f.shuffled_queries(meta,{k:i for i,k in enumerate(keys)},'active300')
        np.testing.assert_array_equal(q[0,:2],q[1,:2])
        for e in range(3):
            for w,d in enumerate(meta['windows'][e]): self.assertEqual(keys[q[e,w]][0],d)

    def test_prefilter_uses_training_ranks_only_and_purges_shared_evening(self):
        ranks=np.full((3,3,4),40,np.uint16);ranks[0,0]=1;ranks[1,1]=1;ranks[2,2]=1
        allowed={0:[0,1,2,3]};before=models.screen(ranks,[0],allowed,1)
        ranks[:,1:]=1
        self.assertEqual(before,models.screen(ranks,[0],allowed,1));self.assertEqual(before,[0])
        meta=dict(windows=[['a','b','c','d'],['d','e','f','g']])
        self.assertEqual(models.training_windows(meta,[0],[1]),{0:[0,1,2]})

    def test_prototypes_use_only_previously_occurred_training_entries(self):
        class D: pass
        d=D();d.x=np.array([[0.],[1.],[.9],[.1],[.8],[.2]])
        d.features=[0];d.slices={'2024-01-02':slice(0,2),'2024-01-03':slice(2,4),'2024-01-04':slice(4,6)}
        d.meta=dict(entries=[dict(id='past',entry_date='2024-01-03'),dict(id='future',entry_date='2024-01-05')])
        d.query=np.array([[0,0,0,1],[0,0,0,0]])
        ctx=dict(train=[0,1],allowed={0:[3],1:[3]})
        score,model=models.prototype(d,ctx,1)
        self.assertEqual(model['prototype_history'][0]['entry_ids'],[])
        self.assertEqual(model['prototype_history'][1]['entry_ids'],['past'])
        self.assertTrue(all('future' not in x['entry_ids'] for x in model['prototype_history']))
        changed=d.x.copy();d.x[0]=999
        other,_=models.prototype(d,ctx,1)
        np.testing.assert_allclose(score,other)
        ctx['train']=[1]
        held,_=models.prototype(d,ctx,1)
        np.testing.assert_allclose(held,0)

    def test_conditional_objective_and_tree_respond_to_target(self):
        score=np.zeros(4);g,h,loss=models.gradient(score,[(slice(0,4),{1:1.})])
        self.assertLess(g[1],0);self.assertAlmostEqual(g.sum(),0)
        bins=np.tile(np.repeat([0,3],30)[:,None],(1,2)).astype(np.uint8)
        grad=np.r_[np.ones(30),-np.ones(30)]/60;hess=np.ones(60)/60
        tree=models.tree_fit(bins,np.arange(60),grad,hess)
        pred=models.tree_predict(tree,bins)
        self.assertGreater(pred[-1],pred[0])


if __name__=='__main__': unittest.main()
