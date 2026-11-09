import ast
import csv
from datetime import date, timedelta
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from studies.trader_replication import martin_continue_ie4 as ie4


def small_meta():
    days=['2024-02-01','2025-02-03']
    entries=[dict(id=str(i),code='US.BBB',entry_date=entry,setup='breakout',target=dict(tier='primary'))
             for i,entry in enumerate(('2024-02-02','2025-02-04'))]
    return dict(days=days,eval_days=days,entries=entries,windows=[[d]*4 for d in days],
                scope={d:{s:['US.AAA','US.BBB','US.CCC'] for s in ie4.prior.SCOPE_NAMES} for d in days})


class IE4Tests(unittest.TestCase):
    def test_all_raw_features_ignore_future_prices_options_and_earnings(self):
        n=340;cut=300
        days=[(date(2024,1,1)+timedelta(days=i)).isoformat() for i in range(n)]
        close=10+np.arange(n)/50+np.sin(np.arange(n)/4)
        arrays=dict(o=close*.99,h=close*1.03,l=close*.97,c=close,v=np.arange(n)+100.,
                    t=(np.arange(n)+100.)*close,raw_c=close.copy())
        extras=dict(earn_days=np.arange(n,dtype=float),iv=np.linspace(.2,.6,n),hv=np.linspace(.1,.4,n))
        full=ie4.raw_factors(arrays,days,close,extras)
        truncated=ie4.raw_factors({k:v[:cut] for k,v in arrays.items()},days[:cut],close[:cut],
                                 {k:v[:cut] for k,v in extras.items()})
        changed={k:v.copy() for k,v in arrays.items()}
        for values in changed.values(): values[cut:]*=100
        future={k:v.copy() for k,v in extras.items()}
        for values in future.values(): values[cut:]+=10000
        amended=ie4.raw_factors(changed,days,close,future)
        self.assertEqual(set(full),set(ie4.raw_names()))
        for name in full:
            np.testing.assert_allclose(full[name][:cut],truncated[name],equal_nan=True,err_msg=name)
            np.testing.assert_allclose(full[name][:cut],amended[name][:cut],equal_nan=True,err_msg=name)

    def test_gates_use_train_only_preserve_one_night_and_pass_missing(self):
        ie4.WORK.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=ie4.WORK) as folder,patch.object(ie4,'WORK',Path(folder)):
            design=ie4.Design(small_meta(),'active300')
            raw=np.zeros((len(design.keys),len(ie4.raw_names())),np.float32)
            raw[:,0]=[0,5,10,100,200,300]
            raw[0,1]=np.nan
            path=ie4.WORK/'active300.raw.npy';np.save(path,raw)
            ctx=dict(train=[0],test=[1],allowed={0:[0,1,2,3]})
            keep,model=ie4.fit_gates(design,ctx,2)
            self.assertTrue(keep[1]);self.assertTrue(model['gates'])
            np.testing.assert_array_equal(keep,ie4.apply_gates(raw,model))
            raw[3:]*=1000;np.save(path,raw)
            _,again=ie4.fit_gates(design,ctx,2)
            self.assertEqual(model['gates'],again['gates'])
            missing=raw.copy();missing[:,model['gates'][0]['feature']]=np.nan
            self.assertTrue(ie4.apply_gates(missing,dict(gates=model['gates'][:1])).all())

    def test_held_out_evenings_are_purged_and_secondaries_do_not_train(self):
        meta=small_meta()
        meta['windows'][0][0]=meta['windows'][1][0]
        ctx=ie4.context(meta,2)
        self.assertEqual(ctx['train'],[0]);self.assertEqual(ctx['test'],[1])
        self.assertEqual(ctx['allowed'][0],[1,2,3])
        meta['entries'][1]['target']['tier']='secondary'
        self.assertEqual(ctx,ie4.context(meta,2))

    def test_gated_target_is_never_ranked_and_ties_stay_in_scope(self):
        design=ie4.Design(small_meta(),'active300')
        score=np.zeros(len(design.keys))
        self.assertEqual(design.best(score,[0]).tolist(),[2])
        design.mask[0]=False
        self.assertEqual(design.best(score,[0]).tolist(),[1])
        design.mask[1]=False
        self.assertEqual(design.best(score,[0]).tolist(),[ie4.prior.SENTINEL])
        design.query[0,:]=-1
        self.assertEqual(design.best(score,[0]).tolist(),[ie4.prior.SENTINEL])

    def test_numeric_prototype_contains_no_identity_or_runtime_ledger(self):
        design=ie4.Design(small_meta(),'active300')
        design.x=np.arange(12,dtype=np.float32).reshape(6,2)/12
        design.features=['a','b']
        score,model=ie4.prototype_fit(design,dict(train=[0],allowed={0:[0,1,2,3]}))
        self.assertNotIn('US.',json.dumps(model));self.assertNotIn('2024-',json.dumps(model))
        np.testing.assert_allclose(score,ie4.predict_numeric(design.x,model))
        permutation=np.array([2,1,0,5,4,3])
        np.testing.assert_allclose(score[permutation],ie4.predict_numeric(design.x[permutation],model))

    def test_new_implementation_has_no_real_ticker_or_entry_date_literals(self):
        path=Path(ie4.__file__)
        with (ie4.prior.ROOT/'studies/martin_luk/notes/trades.csv').open() as f:
            rows=list(csv.DictReader(f))
        forbidden={r['ticker'] for r in rows}|{'US.'+r['ticker'] for r in rows}
        forbidden|={r['entry_date'] for r in rows if r['entry_date']}
        literals={n.value for n in ast.walk(ast.parse(path.read_text())) if isinstance(n,ast.Constant) and isinstance(n.value,str)}
        self.assertFalse(literals&forbidden,literals&forbidden)

    def test_progress_has_one_row_per_direction_and_stops_at_23(self):
        ie4.WORK.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=ie4.WORK) as folder:
            path=Path(folder)/'progress.md'
            path.write_text('| 方向 | 内容 |\n|---|---|\n\n尚未完成：1、2。\n')
            def counts(n): return dict(primary=dict(n=28,hits={'5':n}))
            result=dict(winner=dict(scope='active300',candidate='G1',full=counts(22),holdout=counts(3),
                                    shuffle=dict(full=counts(9),holdout=counts(1))))
            with patch.object(ie4,'PROGRESS',path):
                ie4.completed_row(1,'gates',result)
                result['winner']['full']=counts(23)
                ie4.completed_row(1,'gates',result)
            text=path.read_text()
            self.assertEqual(text.count('| 1 |'),1)
            self.assertIn('已停止',text)


if __name__=='__main__':
    unittest.main()
