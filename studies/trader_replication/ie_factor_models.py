"""Training-only factor screening, purged nested folds, and four model families."""
from collections import defaultdict
import gc
import json

import numpy as np

from studies.trader_replication import martin_continue_ie_factors as f
from studies.trader_replication import ie_factor_library as lib

METHODS=('single','forward','logit','boost','prototype')
LEVELS={'single':(1,), 'forward':(1,3,5), 'logit':(.1,1.,10.),
        'boost':(20,40,60), 'prototype':(1,3,5)}


def training_windows(meta,train,test):
    """Purge every evening used by a held-out entry, including its four-night window."""
    excluded={day for i in test for day in meta['windows'][i]}
    return {i:[j for j,day in enumerate(meta['windows'][i]) if day not in excluded] for i in train}


def screen(ranks,train,allowed,limit=f.PREFILTER):
    """The held-out labels and their ranks are never indexed here."""
    best=np.full((len(ranks),len(train)),f.SENTINEL,np.uint16)
    for k,i in enumerate(train):
        nights=allowed[i]
        if nights: best[:,k]=ranks[:,i,nights].min(1)
    hits=(best<=5).sum(1)
    reciprocal=np.where(best<f.SENTINEL,1/np.maximum(best,1),0.).sum(1)
    order=np.lexsort((np.arange(len(ranks)),-reciprocal,-hits))
    return order[:limit].tolist()


def contexts(meta,a):
    primary=[i for i,r in enumerate(meta['entries']) if r['target']['tier']=='primary']
    folds=[f.split_id(r['entry_date']) for r in meta['entries']]
    result={};union={s:set() for s in f.SCOPE_NAMES}
    for scope in f.SCOPE_NAMES:
        for shuffled in (False,True):
            ranks=np.load(f.WORK/(scope+('_shuffle_ranks.npy' if shuffled else '_ranks.npy')))
            for outer in range(4):
                train=[i for i in primary if folds[i]!=outer];test=[i for i in primary if folds[i]==outer]
                allowed=training_windows(meta,train,test)
                key=(scope,shuffled,outer,-1)
                chosen=screen(ranks,train,allowed);union[scope].update(chosen)
                result[key]=dict(train=train,test=test,allowed=allowed,features=chosen)
                for inner in range(4):
                    if inner==outer: continue
                    itr=[i for i in train if folds[i]!=inner];ite=[i for i in train if folds[i]==inner]
                    ia=training_windows(meta,itr,test+ite)
                    # Drop outer test evenings from the inner validation windows too.
                    itest_allowed=training_windows(meta,ite,test)
                    chosen=screen(ranks,itr,ia);union[scope].update(chosen)
                    result[scope,shuffled,outer,inner]=dict(train=itr,test=ite,allowed=ia,
                        test_allowed=itest_allowed,features=chosen)
            chosen=screen(ranks,primary,{i:list(range(4)) for i in primary})
            result[scope,shuffled,-1,-1]=dict(train=primary,test=[],allowed={i:list(range(4)) for i in primary},features=chosen)
            union[scope].update(chosen)
    return result,union


def prepare_design(meta,union):
    """Recalculate only the union of fold-local, training-selected columns."""
    keys,index,slices,bycode=f.layout(meta);specs=f.factor_specs()
    (f.WORK/'design').mkdir(exist_ok=True)
    needed=set().union(*union.values());families=list(dict.fromkeys(specs[k][0].family for k in sorted(needed)))
    for family in families:
        wanted=[k for k in needed if specs[k][0].family==family]
        absent=[k for k in wanted if any(k in union[s] and not (f.WORK/'design'/f'{s}.{k}.npy').exists() for s in f.SCOPE_NAMES)]
        if not absent: continue
        subset=list(dict.fromkeys(specs[k][0] for k in absent))
        print('B recalculate',family,len(subset),'base columns',flush=True)
        raw,hist=f.calculate_block(subset,meta,len(keys),bycode)
        for scope,trans,value in f.transformed(raw,hist,slices,meta):
            ids=np.concatenate([slices[scope][day] for day in meta['eval_days']])
            for k in absent:
                if k in union[scope] and specs[k][1]==trans:
                    path=f.WORK/'design'/f'{scope}.{k}.npy'
                    if not path.exists(): np.save(path,value[ids,subset.index(specs[k][0])])
        del raw,hist;gc.collect()
        for name in ('raw_scratch.npy','hist_scratch.npy'): (f.WORK/name).unlink()


class Design:
    def __init__(self,meta,scope,a,shuffled=False):
        self.meta=meta;self.scope=scope;self.shuffled=shuffled
        keys,index,slices,bycode=f.layout(meta)
        self.global_rows=np.concatenate([slices[scope][day] for day in meta['eval_days']])
        reverse={int(v):k for k,v in enumerate(self.global_rows)}
        self.slices={};offset=0
        for day in meta['eval_days']:
            width=len(slices[scope][day]);self.slices[day]=slice(offset,offset+width);offset+=width
        raw=np.asarray(a['shuffle_queries' if shuffled else 'queries'][scope])
        self.query=np.array([[reverse.get(int(v),-1) for v in row] for row in raw])
        self.true_query=np.array([[reverse.get(int(v),-1) for v in row] for row in np.asarray(a['queries'][scope])])
        self.features=[];self.x=None

    def load(self,features):
        self.features=features
        self.x=np.column_stack([np.load(f.WORK/'design'/f'{self.scope}.{j}.npy') for j in features]).astype(np.float32)-.5

    def best(self,scores,indices,allowed=None):
        out=[]
        for i in indices:
            ranks=[]
            for w in (allowed[i] if allowed is not None else range(4)):
                q=self.query[i,w]
                if q<0: continue
                day=self.meta['windows'][i][w];sl=self.slices[day];v=scores[sl];t=q-sl.start
                rank=1+int((v>scores[q]).sum())+int((v[:t]==scores[q]).sum())
                ranks.append(rank)
            out.append(min(ranks,default=f.SENTINEL))
        return np.asarray(out)

    def objective(self,scores,indices,allowed):
        r=self.best(scores,indices,allowed)
        return int((r<=5).sum()),float(np.where(r<f.SENTINEL,1/np.maximum(r,1),0).sum())

    def groups(self,train,allowed):
        positives=defaultdict(lambda:defaultdict(float))
        for i in train:
            for w in allowed[i]:
                q=self.query[i,w]
                if q>=0: positives[self.meta['windows'][i][w]][q]+=1.
        return [(self.slices[day],dict(p)) for day,p in sorted(positives.items())]


def gradient(scores,groups):
    grad=np.zeros(len(scores));hess=np.zeros(len(scores));loss=0.
    for sl,positive in groups:
        x=scores[sl];p=np.exp(x-x.max());p/=p.sum();weight=sum(positive.values())
        grad[sl]=weight*p;hess[sl]=weight*p*(1-p)
        normal=x.max()+np.log(np.exp(x-x.max()).sum())
        for q,w in positive.items(): grad[q]-=w;loss+=w*(normal-scores[q])
    total=sum(sum(v.values()) for sl,v in groups) or 1
    return grad/total,hess/total,loss/total


def forward(design,ctx,maximum):
    x=design.x;selected=[];score=np.zeros(len(x));before=design.objective(score,ctx['train'],ctx['allowed'])
    for step in range(maximum):
        best=None
        for j in range(x.shape[1]):
            if j in selected: continue
            value=design.objective(score+x[:,j],ctx['train'],ctx['allowed'])
            key=(value[0],value[1],-design.features[j])
            if best is None or key>best[0]: best=(key,j,value)
        if best is None or best[2]<=before: break
        _,j,before=best;selected.append(j);score+=x[:,j]
    return score,dict(features=[design.features[j] for j in selected],weights=[1.]*len(selected))


def logit(design,ctx,penalty):
    x=design.x;groups=design.groups(ctx['train'],ctx['allowed']);w=np.zeros(x.shape[1]);history=[]
    # Fixed 100 deterministic gradient steps; Lipschitz bound from bounded percentiles.
    rate=1/(penalty+x.shape[1]/4)
    for step in range(100):
        score=x@w;g,h,loss=gradient(score,groups)
        w-=rate*(x.T@g+penalty*w)
        if step in (0,99): history.append(float(loss+penalty*np.dot(w,w)/2))
    return x@w,dict(features=design.features,weights=w.tolist(),penalty=penalty,loss=history)


def tree_fit(bins,rows,grad,hess,depth=0):
    total_g=grad[rows].sum();total_h=hess[rows].sum();value=-total_g/(total_h+.01)
    if depth==2 or len(rows)<40: return {'value':float(value)}
    best_gain=0.;best=None
    parent=total_g**2/(total_h+.01)
    for j in range(bins.shape[1]):
        b=bins[rows,j];g=np.bincount(b,weights=grad[rows],minlength=4).cumsum()
        h=np.bincount(b,weights=hess[rows],minlength=4).cumsum();count=np.bincount(b,minlength=4).cumsum()
        for threshold in range(3):
            if count[threshold]<20 or len(rows)-count[threshold]<20: continue
            gain=g[threshold]**2/(h[threshold]+.01)+(total_g-g[threshold])**2/(total_h-h[threshold]+.01)-parent
            if gain>best_gain+1e-12: best_gain=gain;best=(j,threshold)
    if best is None: return {'value':float(value)}
    j,t=best;left=bins[rows,j]<=t
    return dict(feature=int(j),threshold=int(t),left=tree_fit(bins,rows[left],grad,hess,depth+1),
                right=tree_fit(bins,rows[~left],grad,hess,depth+1))


def tree_predict(tree,bins):
    result=np.empty(len(bins))
    def visit(node,rows):
        if 'value' in node: result[rows]=node['value'];return
        left=bins[rows,node['feature']]<=node['threshold']
        visit(node['left'],rows[left]);visit(node['right'],rows[~left])
    visit(tree,np.arange(len(bins)))
    return result


def boost(design,ctx,rounds):
    x=design.x;groups=design.groups(ctx['train'],ctx['allowed']);score=np.zeros(len(x));trees=[]
    bins=np.searchsorted(np.array([-.25,0.,.25]),x,side='right').astype(np.uint8)
    rows=np.concatenate([np.arange(sl.start,sl.stop) for sl,p in groups]) if groups else np.array([],int)
    for step in range(rounds):
        g,h,loss=gradient(score,groups);tree=tree_fit(bins,rows,g,h)
        score+=.1*tree_predict(tree,bins);trees.append(tree)
    return score,dict(features=design.features,trees=trees,learning_rate=.1,depth=2,rounds=rounds)


def level_fits(method,design,ctx):
    """A fixed boosting path supplies 20/40/60 rounds without refitting prefixes."""
    if method!='boost':
        for level in LEVELS[method]: yield level,fit(method,level,design,ctx)
        return
    groups=design.groups(ctx['train'],ctx['allowed']);score=np.zeros(len(design.x));trees=[]
    bins=np.searchsorted(np.array([-.25,0.,.25]),design.x,side='right').astype(np.uint8)
    rows=np.concatenate([np.arange(sl.start,sl.stop) for sl,p in groups]) if groups else np.array([],int)
    for step in range(max(LEVELS[method])):
        g,h,loss=gradient(score,groups);tree=tree_fit(bins,rows,g,h)
        score+=.1*tree_predict(tree,bins);trees.append(tree)
        if step+1 in LEVELS[method]:
            yield step+1,(score.copy(),dict(features=design.features,trees=list(trees),learning_rate=.1,depth=2,rounds=step+1))


def prototype(design,ctx,k):
    x=design.x;score=np.zeros(len(x));history=[]
    # Both positive and secondary earlier real entries are legitimate prototypes;
    # every outer/inner held-out *entry* is excluded by the caller's train IDs.
    prior_ids=ctx.get('prototype_train',ctx['train'])
    for day,sl in design.slices.items():
        prot=[]
        for i in prior_ids:
            if design.meta['entries'][i]['entry_date']>day: continue
            if 3 not in ctx['allowed'].get(i,[]): continue
            q=design.query[i,3]
            if q>=0: prot.append((i,q))
        history.append(dict(date=day,entry_ids=[design.meta['entries'][i]['id'] for i,q in prot]))
        if not prot: continue
        v=x[sl];nearest=np.full((len(v),min(k,len(prot))),np.inf)
        for i,q in prot:
            d=np.mean((v-x[q])**2,axis=1)
            nearest=np.partition(np.column_stack((nearest,d)),nearest.shape[1]-1,axis=1)[:,:nearest.shape[1]]
        score[sl]=-nearest.mean(1)
    return score,dict(features=design.features,neighbors=k,prototype_history=history)


def fit(method,level,design,ctx):
    if method=='single':
        return design.x[:,0],dict(features=design.features[:1],weights=[1.])
    return globals()[method](design,ctx,level)


def run(meta,a):
    ctxs,union=contexts(meta,a)
    write=f.WORK/'b_screening.json'
    f.write_json(write,dict(contexts=[dict(scope=s,shuffled=b,outer=o,inner=i,**c) for (s,b,o,i),c in ctxs.items()],
        union_counts={s:len(v) for s,v in union.items()}))
    prepare_design(meta,union)
    (f.WORK/'b').mkdir(exist_ok=True)
    results=[]
    foldids=[f.split_id(r['entry_date']) for r in meta['entries']]
    for scope in f.SCOPE_NAMES:
        for shuffled in (False,True):
            design=Design(meta,scope,a,shuffled)
            for method in METHODS:
                path=f.WORK/'b'/f'{scope}.{shuffled}.{method}.json'
                if path.exists():
                    results.append(json.loads(path.read_text()));continue
                outer_results=[]
                for outer in range(4):
                    inner_hits={level:0 for level in LEVELS[method]};inner_rows=[]
                    if method!='single':
                        for inner in range(4):
                            if inner==outer: continue
                            ctx=ctxs[scope,shuffled,outer,inner];design.load(ctx['features'])
                            if method=='prototype': add_prototype_entries(ctx,meta,foldids,{outer,inner})
                            row=dict(inner=inner,train_ids=[meta['entries'][i]['id'] for i in ctx['train']],
                                test_ids=[meta['entries'][i]['id'] for i in ctx['test']],features=ctx['features'],levels={})
                            for level,(scores,model) in level_fits(method,design,ctx):
                                ranks=design.best(scores,ctx['test'],ctx['test_allowed']);hits=int((ranks<=5).sum())
                                inner_hits[level]+=hits;row['levels'][str(level)]=dict(hits=hits,ranks=ranks.tolist())
                            inner_rows.append(row)
                    level=max(LEVELS[method],key=lambda v:(inner_hits[v],-LEVELS[method].index(v)))
                    ctx=ctxs[scope,shuffled,outer,-1];design.load(ctx['features'])
                    if method=='prototype': add_prototype_entries(ctx,meta,foldids,{outer})
                    scores,model=fit(method,level,design,ctx);ranks=design.best(scores,ctx['test'])
                    outer_results.append(dict(fold=outer,n=len(ranks),hits=int((ranks<=5).sum()),test_ranks=ranks.tolist(),
                        train_ids=[meta['entries'][i]['id'] for i in ctx['train']],test_ids=[meta['entries'][i]['id'] for i in ctx['test']],
                        screened_features=ctx['features'],level=level,inner_hits={str(k):v for k,v in inner_hits.items()},
                        inner=inner_rows,model=model))
                    print('B',scope,'shuffled',shuffled,method,'fold',outer,'hits',outer_results[-1]['hits'],'/',len(ranks),flush=True)
                value=dict(scope=scope,shuffled=shuffled,method=method,hits=sum(r['hits'] for r in outer_results),
                    n=sum(r['n'] for r in outer_results),folds=outer_results)
                byid={r['id']:r for r in meta['entries']};unique={}
                for fold in outer_results:
                    for ident,rank in zip(fold['test_ids'],fold['test_ranks']):
                        entry=byid[ident];unique.setdefault((entry['code'],entry['entry_date']),rank)
                value['unique_n']=len(unique);value['unique_hits']=sum(v<=5 for v in unique.values())
                f.write_json(path,value);results.append(value)
            del design;gc.collect()
    true=[r for r in results if not r['shuffled']]
    winner=max(true,key=lambda r:(r['hits'],-METHODS.index(r['method']),-f.SCOPE_NAMES.index(r['scope'])))
    level_totals=defaultdict(int)
    for fold in winner['folds']:
        for k,v in fold['inner_hits'].items(): level_totals[k]+=v
    levels=LEVELS[winner['method']]
    level=max(levels,key=lambda v:(level_totals[str(v)],-levels.index(v)))
    ctx=ctxs[winner['scope'],False,-1,-1]
    design=Design(meta,winner['scope'],a);design.load(ctx['features'])
    if winner['method']=='prototype': add_prototype_entries(ctx,meta,foldids,set())
    scores,model=fit(winner['method'],level,design,ctx)
    np.save(f.WORK/'final_scores.npy',scores)
    final=dict(scope=winner['scope'],method=winner['method'],level=level,model=model,
        outer_hits=winner['hits'],n=winner['n'],selection_bias=True,
        frozen_features=[f.factor_name(*f.factor_specs()[j]) for j in model['features']])
    value=dict(candidates=results,final=final,screening_union_counts={s:len(v) for s,v in union.items()})
    f.write_json(f.WORK/'b.json',value)
    return value


def add_prototype_entries(ctx,meta,foldids,excluded):
    ids=[i for i,r in enumerate(meta['entries']) if foldids[i] not in excluded]
    test=[i for i in range(len(meta['entries'])) if foldids[i] in excluded]
    ctx['prototype_train']=ids
    allowed=training_windows(meta,ids,test)
    for i in ids: ctx['allowed'][i]=allowed[i]
