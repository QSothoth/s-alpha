"""Offline IE4 interval gates and numeric ranking; no evaluation beyond 2025."""
from collections import defaultdict
from datetime import date
import argparse
import gc
import json
import os
from pathlib import Path
import resource
import sys

import numpy as np

from studies.trader_replication import ie_factor_library as lib
from studies.trader_replication import ie_factor_models as models
from studies.trader_replication import martin_continue_ie_factors as prior
from studies.trader_replication.martin_continue_ie_periods import file_sha

REPORTS = prior.REPORTS
WORK = REPORTS / 'ie4_work'
PROGRESS = REPORTS / 'ie4_progress_CN.md'
GATES = ((0, 0., 0, False), (12, .1, 0, True), (20, .05, 0, False),
         (40, .02, 0, False), (40, .05, 1, False))
PRIORITY = ('money20', 'raw_price', 'adr20', 'iv', 'hv', 'low20', 'low60',
            'low120', 'offlow252', 'high20', 'high60', 'high252', 'ema9',
            'ema21', 'ema50', 'ema_stack', 'observed_sessions', 'earn_age')
RAW_EXTRA = ('raw_price', 'observed_sessions', 'offlow252', 'iv', 'hv',
             'option_volume', 'call_volume', 'put_volume', 'option_open_interest',
             'iv_hv', 'pcr')
METHODS = ('L1', 'L2', 'T1', 'P1', 'E1')


def load_meta():
    meta = json.loads((prior.WORK / 'prepared.json').read_text())
    if (meta['prepared_last'] > prior.CUTOFF or any(d > prior.CUTOFF for d in meta['days'])
            or any(d > prior.CUTOFF for d in meta['eval_days'])
            or any(r['entry_date'][:4] not in ('2024', '2025') for r in meta['entries'])):
        raise ValueError('research boundary exceeded')
    if len(meta['entries']) != 32 or sum(r['target']['tier'] == 'primary' for r in meta['entries']) != 28:
        raise ValueError('frozen labels differ')
    return meta


def raw_factors(arrays, days, qqq, extras):
    stock = lib.Stock(arrays, days, qqq, extras)
    out = stock.evaluate('original53', 0)
    out.update(raw_price=np.asarray(arrays['raw_c'], float),
               observed_sessions=np.cumsum(np.isfinite(arrays['raw_c'])).astype(float),
               offlow252=lib.divide(stock.c, lib.roll(stock.l, 252, 'min')) - 1)
    for key in RAW_EXTRA[3:9]:
        out[key] = extras.get(key, np.full(len(days), np.nan))
    out['iv_hv'] = lib.divide(out['iv'], out['hv'])
    out['pcr'] = lib.divide(out['put_volume'], out['call_volume'])
    stock.ema.cache_clear()
    return out


class Design(models.Design):
    def __init__(self, meta, scope, shuffled=False):
        self.meta, self.scope, self.shuffled = meta, scope, shuffled
        self.slices = {}
        self.keys = []
        for day in meta['eval_days']:
            start = len(self.keys)
            self.keys.extend((day, c) for c in meta['scope'][day][scope])
            self.slices[day] = slice(start, len(self.keys))
        self.index = {key: i for i, key in enumerate(self.keys)}
        self.true_query = np.array([[self.index.get((day, r['code']), -1) for day in window]
                                    for r, window in zip(meta['entries'], meta['windows'])])
        self.query = self.true_query.copy()
        if shuffled:
            rng = np.random.default_rng(20261103)
            mappings = {}
            for day, sl in self.slices.items():
                names = meta['scope'][day][scope]
                mappings[day] = dict(zip(names, rng.permutation(np.arange(sl.start, sl.stop))))
            for i, (entry, window) in enumerate(zip(meta['entries'], meta['windows'])):
                for w, day in enumerate(window):
                    mapping = mappings[day]
                    if entry['code'] not in mapping and mapping:
                        sl = self.slices[day]
                        mapping[entry['code']] = int(rng.integers(sl.start, sl.stop))
                    self.query[i, w] = mapping.get(entry['code'], -1)
        self.mask = np.ones(len(self.keys), bool)
        self.features = []
        self.x = None

    def load(self, features, extra=False):
        ensure_features(self.meta, self.scope, features)
        columns = []
        for j in features:
            path = prior.WORK / 'design' / f'{self.scope}.{j}.npy'
            columns.append(np.load(path if path.exists() else WORK / 'design' / path.name))
        names = [prior.factor_name(*prior.factor_specs()[j]) for j in features]
        if extra:
            raw = np.load(WORK / f'{self.scope}.raw.npy', mmap_mode='r')
            p = np.full(raw.shape, .5, np.float32)
            for sl in self.slices.values():
                p[sl] = prior.percentile(raw[sl])
            columns.extend(p[:, j] for j in range(p.shape[1]))
            names.extend('raw_pct.' + name for name in raw_names())
        self.features = names
        self.x = np.column_stack(columns).astype(np.float32) - .5

    def best(self, scores, indices, allowed=None):
        out = []
        for i in indices:
            ranks = []
            for w in (allowed[i] if allowed is not None else range(4)):
                q = self.query[i, w]
                if q < 0 or not self.mask[q]:
                    continue
                sl = self.slices[self.meta['windows'][i][w]]
                values = scores[sl]
                keep = self.mask[sl]
                t = q - sl.start
                ranks.append(1 + int(((values > scores[q]) & keep).sum())
                             + int(((values[:t] == scores[q]) & keep[:t]).sum()))
            out.append(min(ranks, default=prior.SENTINEL))
        return np.asarray(out)

    def groups(self, train, allowed):
        positives = defaultdict(lambda: defaultdict(float))
        for i in train:
            for w in allowed[i]:
                q = self.query[i, w]
                if q >= 0 and self.mask[q]:
                    positives[self.meta['windows'][i][w]][q] += 1.
        return [(np.flatnonzero(self.mask[sl]) + sl.start, dict(positives[day]))
                for day, sl in self.slices.items() if day in positives]


def raw_names():
    return [s.name for s in lib.inventory() if s.family == 'original53'] + list(RAW_EXTRA)


def ensure_features(meta, scope, features):
    missing = [j for j in features if not (prior.WORK/'design'/f'{scope}.{j}.npy').exists()
               and not (WORK/'design'/f'{scope}.{j}.npy').exists()]
    if not missing:
        return
    (WORK/'design').mkdir(exist_ok=True)
    keys,index,slices,bycode=prior.layout(meta)
    specs=prior.factor_specs()
    qqq=np.load(prior.WORK/'qqq.npy')
    for family in dict.fromkeys(specs[j][0].family for j in missing):
        wanted=[j for j in missing if specs[j][0].family==family]
        subset=list(dict.fromkeys(specs[j][0] for j in wanted))
        raw=np.full((len(keys),len(subset)),np.nan,np.float32)
        hist=np.full_like(raw,np.nan)
        for code,positions in bycode.items():
            with np.load(prior.WORK/'stocks'/(code+'.npz')) as z:
                arrays={k:z[k] for k in z.files if not k.startswith('extra_')}
                extras={k[6:]:z[k] for k in z.files if k.startswith('extra_')}
            if family=='group':
                for n in {s.parameter for s in subset}:
                    with np.load(prior.WORK/'group'/(code+f'.{n}.npz')) as z:
                        extras.update({f'group.{k}.{n}':z[k] for k in z.files})
            stock=lib.Stock(arrays,meta['days'],qqq,extras)
            values={n:stock.evaluate(family,n) for n in {s.parameter for s in subset}}
            x=np.column_stack([values[s.parameter][s.metric] for s in subset])
            rows=np.array([p[0] for p in positions]);dest=np.array([p[1] for p in positions])
            raw[dest]=x[rows];hist[dest]=lib.history_rank(x,rows)
            stock.ema.cache_clear();stock.f_hilbert.cache_clear()
        ids=np.concatenate([slices[scope][day] for day in meta['eval_days']])
        for s,transform,value in prior.transformed(raw,hist,slices,meta):
            if s!=scope: continue
            for j in wanted:
                if specs[j][1]==transform:
                    np.save(WORK/'design'/f'{scope}.{j}.npy',value[ids,subset.index(specs[j][0])])
        print('reconstructed training-only columns',scope,family,len(wanted),flush=True)


def prepare_raw(meta):
    if (WORK / 'raw_complete.json').exists():
        return
    designs = [Design(meta, scope) for scope in prior.SCOPE_NAMES]
    dest = {}
    for d in designs:
        dest[d.scope] = np.lib.format.open_memmap(WORK / f'{d.scope}.raw.npy', mode='w+',
                                                 dtype=np.float32, shape=(len(d.keys), len(raw_names())))
        dest[d.scope][:] = np.nan
    bycode = defaultdict(list)
    di = {day: i for i, day in enumerate(meta['days'])}
    for d in designs:
        for row, (day, code) in enumerate(d.keys):
            bycode[code].append((d.scope, di[day], row))
    qqq = np.load(prior.WORK / 'qqq.npy')
    for count, (code, positions) in enumerate(bycode.items()):
        with np.load(prior.WORK / 'stocks' / (code + '.npz')) as z:
            arrays = {k: z[k] for k in z.files if not k.startswith('extra_')}
            extras = {k[6:]: z[k] for k in z.files if k.startswith('extra_')}
        values = raw_factors(arrays, meta['days'], qqq, extras)
        for scope in dest:
            rows = [(t, row) for s, t, row in positions if s == scope]
            if rows:
                ts, target = map(np.asarray, zip(*rows))
                dest[scope][target] = np.column_stack([values[name][ts] for name in raw_names()])
        if count % 300 == 0:
            print('raw stock block', count, '/', len(bycode), flush=True)
    for x in dest.values():
        x.flush()
    prior.write_json(WORK / 'raw_complete.json', dict(names=raw_names(), stocks=len(bycode),
                                                    last_session=meta['days'][-1]))


def context(meta, fold):
    primary = [i for i, r in enumerate(meta['entries']) if r['target']['tier'] == 'primary']
    test = [i for i in range(len(meta['entries'])) if prior.split_id(meta['entries'][i]['entry_date']) == fold]
    train = [i for i in primary if i not in test]
    return dict(train=train, test=test, allowed=models.training_windows(meta, train, test))


def selection(scores, design, train, allowed):
    return design.objective(scores, train, allowed)


def fit_gates(design, ctx, profile):
    maximum, margin, losses, priority_only = GATES[profile]
    raw = np.load(WORK / f'{design.scope}.raw.npy', mmap_mode='r')
    if not maximum:
        return np.ones(len(raw),bool),dict(profile='G0',gates=[],diagnostics=[],
                                          remaining_by_night={day:sl.stop-sl.start for day,sl in design.slices.items()})
    names = raw_names()
    columns = [j for j, name in enumerate(names) if not priority_only or name in PRIORITY]
    positive = np.full((len(ctx['train']), 4), -1, int)
    for k, i in enumerate(ctx['train']):
        for w in ctx['allowed'][i]:
            positive[k, w] = design.query[i, w]
    valid = positive >= 0
    reachable = valid.any(1)
    q = np.maximum(positive, 0)
    train_days = {design.meta['windows'][i][w] for i in ctx['train'] for w in ctx['allowed'][i]}
    background = np.concatenate([np.arange(sl.start, sl.stop) for day, sl in design.slices.items()
                                 if day in train_days]) if train_days else np.array([], int)
    candidates, masks = [], []
    diagnostics = []
    for j in columns:
        values = raw[np.unique(positive[valid]), j]
        values = values[np.isfinite(values)]
        if not len(values):
            diagnostics.append(dict(name=names[j],valid_positive_nights=0,missing=True))
            continue
        quantiles = np.quantile(values, (0., .05, .1, .9, .95, 1.))
        diagnostics.append(dict(name=names[j], valid_positive_nights=len(values),
                                quantiles=quantiles.tolist(), background_missing=float(np.mean(~np.isfinite(raw[background,j])))))
        seen = set()
        for a, b in ((0, 5), (1, 4), (2, 3)):
            lo, hi = float(quantiles[a]), float(quantiles[b])
            pad = max(hi-lo, abs(lo)*.01, 1e-8) * margin
            lo, hi = lo-pad, hi+pad
            for lower, upper in ((lo, hi), (lo, None), (None, hi)):
                key = lower, upper
                if key in seen:
                    continue
                seen.add(key)
                v = raw[:, j]
                keep = ~np.isfinite(v) | (((v >= lower) if lower is not None else True)
                                          & ((v <= upper) if upper is not None else True))
                candidates.append(dict(feature=j,name=names[j],lower=lower,upper=upper))
                masks.append(keep)
    keep = np.ones(len(raw), bool)
    gates, used = [], set()
    if masks and maximum:
        masks = np.asarray(masks, bool)
        qmask = masks[:, q] & valid[None, :, :]
        for step in range(maximum):
            possible = ((qmask & keep[q][None, :, :]).any(2)).sum(1) >= int(reachable.sum()) - losses
            remaining = background[keep[background]]
            if not len(remaining):
                break
            counts = masks[:, remaining].sum(1)
            possible &= np.array([c['feature'] not in used for c in candidates])
            counts = np.where(possible, counts, len(remaining)+1)
            chosen = int(counts.argmin())
            if counts[chosen] >= len(remaining):
                break
            keep &= masks[chosen]
            gate = dict(candidates[chosen])
            gate.update(step=step+1,removed_training_rows=int(len(remaining)-counts[chosen]),
                        kept_training_rows=int(counts[chosen]),
                        lost_training_entries=int(reachable.sum() - ((keep[q] & valid).any(1)).sum()))
            gates.append(gate)
            used.add(gate['feature'])
    return keep, dict(profile='G'+str(profile),gates=gates,diagnostics=diagnostics,
                      training_entries=len(ctx['train']),reachable_training_entries=int(reachable.sum()),
                      remaining_by_night={day:int(keep[sl].sum()) for day,sl in design.slices.items()})


def apply_gates(raw, model):
    keep = np.ones(len(raw), bool)
    for gate in model['gates']:
        v = raw[:, gate['feature']]
        lo, hi = gate['lower'], gate['upper']
        keep &= ~np.isfinite(v) | (((v >= lo) if lo is not None else True)
                                  & ((v <= hi) if hi is not None else True))
    return keep


def summary(meta, ranks, ids=None):
    ids = list(range(len(meta['entries']))) if ids is None else list(ids)
    out = {}
    for tier in ('primary','all'):
        subset = [i for i in ids if tier == 'all' or meta['entries'][i]['target']['tier']=='primary']
        out[tier] = dict(n=len(subset), hits={str(k):int(sum(ranks[i]<=k for i in subset)) for k in prior.TOPS})
    out['ranks'] = {meta['entries'][i]['id']:int(ranks[i]) for i in ids}
    return out


def features_for(design, ctx):
    suffix = '_shuffle_ranks.npy' if design.shuffled else '_ranks.npy'
    ranks = np.load(prior.WORK / (design.scope+suffix), mmap_mode='r')
    return models.screen(ranks,ctx['train'],ctx['allowed'])


def fit_logit(design,ctx,penalty,steps=400):
    groups=design.groups(ctx['train'],ctx['allowed'])
    x=design.x
    weights=np.zeros(x.shape[1])
    rate=1/(penalty+x.shape[1]/4)
    for _ in range(steps):
        g,_,_=models.gradient(x@weights,groups)
        weights-=rate*(x.T@g+penalty*weights)
    return x@weights,dict(features=design.features,weights=weights.tolist(),penalty=penalty,steps=steps)


def prototype_fit(design,ctx):
    categories=defaultdict(list)
    latest=max((design.meta['entries'][i]['entry_date'] for i in ctx['train']),default='2024-01-01')
    for i in ctx['train']:
        rows=[design.query[i,w] for w in ctx['allowed'][i] if design.query[i,w]>=0 and design.mask[design.query[i,w]]]
        if rows:
            age=(date.fromisoformat(latest)-date.fromisoformat(design.meta['entries'][i]['entry_date'])).days
            categories[design.meta['entries'][i]['setup']].append((np.mean(design.x[rows],axis=0),2**(-age/180)))
    centers=[]
    for category,rows in sorted(categories.items()):
        points=np.asarray([x for x,w in rows]);weights=np.asarray([w for x,w in rows])
        mean=np.average(points,axis=0,weights=weights)
        k=min(3,len(points));cur=points[np.linspace(0,len(points)-1,k).astype(int)].copy()
        for _ in range(15):
            distances=np.column_stack([np.mean((points-c)**2,axis=1) for c in cur])
            labels=distances.argmin(1)
            for j in range(k):
                if (labels==j).any(): cur[j]=np.average(points[labels==j],axis=0,weights=weights[labels==j])
        centers.extend((.9*cur+.1*mean).tolist())
    model=dict(features=design.features,centers=centers,half_life_calendar_days=180,shrink=.1)
    return predict_numeric(design.x,model),model


def predict_numeric(x,model):
    if 'components' in model:
        return sum(weight*prior.percentile(predict_numeric(x,component))[:,0]
                   for weight,component in zip(model['weights'],model['components']))
    if 'weights' in model:
        return x@np.asarray(model['weights'])
    if 'centers' in model:
        best=np.full(len(x),np.inf)
        for center in model['centers']:
            best=np.minimum(best,np.mean((x-np.asarray(center))**2,axis=1))
        return -best if model['centers'] else np.zeros(len(x))
    bins=np.searchsorted(np.asarray(model['edges']),x,side='right').astype(np.uint8)
    out=np.zeros(len(x))
    for tree in model['trees']:
        out+=model['learning_rate']*models.tree_predict(tree,bins)
    return out


def boost_fit(design,ctx):
    score=np.zeros(len(design.x));trees=[]
    edges=[-.25,0.,.25]
    bins=np.searchsorted(edges,design.x,side='right').astype(np.uint8)
    groups=design.groups(ctx['train'],ctx['allowed'])
    rows=np.concatenate([rows for rows,p in groups]) if groups else np.array([],int)
    for _ in range(60):
        g,h,_=models.gradient(score,groups)
        tree=models.tree_fit(bins,rows,g,h)
        score+=.1*models.tree_predict(tree,bins)
        trees.append(tree)
    return score,dict(features=design.features,edges=edges,trees=trees,learning_rate=.1,depth=2,rounds=60)


def percentile_scores(scores,design):
    out=np.zeros(len(scores),np.float32)
    for sl in design.slices.values():
        rows=np.flatnonzero(design.mask[sl])+sl.start
        out[rows]=prior.percentile(scores[rows])[:,0]
    return out


def completed_row(direction,description,result):
    winner=result['winner'];full=winner['full'];cv=winner['holdout'];null=winner['shuffle']
    def count(value):
        p=value['primary'];return f"{p['hits']['5']}/{p['n']}"
    row=f"| {direction} | {description}；{winner['scope']}/{winner['candidate']} | {count(full)} | {count(cv)} | 全段 {count(null['full'])}；留出 {count(null['holdout'])} |"
    text=PROGRESS.read_text()
    lines=[line for line in text.splitlines() if not line.startswith('| '+str(direction)+' |')]
    pos=next(i for i,line in enumerate(lines) if line.startswith('尚未完成'))
    lines.insert(pos-1,row)
    done=[i for i in range(1,7) if any(line.startswith('| '+str(i)+' |') for line in lines)]
    if full['primary']['hits']['5']>=23:
        lines[pos+1]='已停止增加方向：全段拟合达到 80%；2026 未运行，总目标尚未验证。'
    else:
        pending=[str(i) for i in range(1,7) if i not in done]
        lines[pos+1]='尚未完成方向：'+'、'.join(pending)+'。'
    temp=PROGRESS.with_suffix('.md.tmp');temp.write_text('\n'.join(lines)+'\n');temp.replace(PROGRESS)


def run_direction(meta,direction):
    results=[]
    for scope in prior.SCOPE_NAMES:
        for shuffled in (False,True):
            design=Design(meta,scope,shuffled)
            for fold in (-1,0,1,2,3):
                checkpoint=WORK/f'd{direction}.{scope}.{shuffled}.{fold}.json'
                if checkpoint.exists():
                    results.append(json.loads(checkpoint.read_text()));continue
                ctx=context(meta,fold)
                features=features_for(design,ctx)
                design.load(features,extra=direction==2)
                design.mask[:]=True
                base,base_model=fit_logit(design,ctx,.1,100)
                profiles=[]
                for profile in range(5):
                    keep,gate=fit_gates(design,ctx,profile)
                    design.mask=keep
                    profiles.append((selection(base,design,ctx['train'],ctx['allowed']),-profile,keep,gate))
                records={}
                if direction==1:
                    fits=[('G'+str(p),(base,base_model),item[2],item[3]) for p,item in enumerate(profiles)]
                else:
                    chosen=max(profiles,key=lambda item:(item[0],item[1]))
                    design.mask=chosen[2]
                    fits=[]
                    for method,fit in (('L1',lambda:fit_logit(design,ctx,.1)),
                                       ('L2',lambda:fit_logit(design,ctx,.001)),
                                       ('T1',lambda:boost_fit(design,ctx)),
                                       ('P1',lambda:prototype_fit(design,ctx))):
                        fits.append((method,fit(),chosen[2],chosen[3]))
                    byname={name:value[0] for name,value,mask,gate in fits}
                    ensemble=sum(percentile_scores(byname[name],design) for name in ('L2','T1','P1'))/3
                    component_models={name:value[1] for name,value,mask,gate in fits}
                    fits.append(('E1',(ensemble,dict(components=[component_models[n] for n in ('L2','T1','P1')],
                                                     weights=[1/3]*3,per_night=True)),chosen[2],chosen[3]))
                for name,(scores,model),keep,gate in fits:
                    design.mask=keep
                    ranks=design.best(scores,range(len(meta['entries'])))
                    train_value=selection(scores,design,ctx['train'],ctx['allowed'])
                    records[name]=dict(summary=summary(meta,ranks),selection=list(train_value),
                                       model=model,gate=gate)
                    if fold==-1:
                        np.save(WORK/f'd{direction}.{scope}.{shuffled}.{name}.scores.npy',scores)
                record=dict(direction=direction,scope=scope,shuffled=shuffled,fold=fold,
                            train=ctx['train'],test=ctx['test'],features=features,candidates=records)
                prior.write_json(checkpoint,record);results.append(record)
                print('direction',direction,scope,'shuffle',shuffled,'fold',fold,
                      {k:v['summary']['primary']['hits']['5'] for k,v in records.items()},flush=True)
                del design.x,profiles,fits;design.x=None;gc.collect()
    candidates=[]
    names=['G'+str(i) for i in range(5)] if direction==1 else METHODS
    for scope in prior.SCOPE_NAMES:
        for name in names:
            sides={}
            for shuffled in (False,True):
                records=[r for r in results if r['scope']==scope and r['shuffled']==shuffled]
                full=next(r for r in records if r['fold']==-1)['candidates'][name]
                cv_ranks={}
                folds=[]
                for r in records:
                    if r['fold']<0: continue
                    value=r['candidates'][name]['summary']
                    cv_ranks.update({meta['entries'][i]['id']:value['ranks'][meta['entries'][i]['id']] for i in r['test']})
                    folds.append(dict(fold=r['fold'],test_ids=[meta['entries'][i]['id'] for i in r['test']],
                                      primary=summary(meta,[value['ranks'][e['id']] for e in meta['entries']],r['test'])['primary']))
                sides[shuffled]=dict(full=full['summary'],holdout=summary(meta,[cv_ranks[e['id']] for e in meta['entries']]),
                                     selection=full['selection'],folds=folds)
            candidates.append(dict(scope=scope,candidate=name,**sides[False],shuffle=sides[True]))
    winner=max(candidates,key=lambda r:(r['selection'],-prior.SCOPE_NAMES.index(r['scope']),-list(names).index(r['candidate'])))
    full=next(r for r in results if r['scope']==winner['scope'] and not r['shuffled'] and r['fold']==-1)
    frozen=full['candidates'][winner['candidate']]
    result=dict(direction=direction,candidates=candidates,winner=winner,
                frozen=dict(scope=winner['scope'],candidate=winner['candidate'],model=frozen['model'],gate=frozen['gate'],
                            numeric_feature_names=raw_names(),training_cutoff=prior.CUTOFF),
                evaluation_years=[2024,2025],evaluation_nights=len(meta['eval_days']),
                no_2026=True,peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                limitations=['全段是重代入拟合，留出只参考；选择性台账及重复交易不代表独立样本',
                             '历史市值、真实上市日、事前财报日程缺失；缺值门禁放行',
                             '宽度只统计有标签的68个夜晚；冻结证券池有幸存者偏差'])
    prior.write_json(REPORTS/f'strong_continue_ie4_direction{direction}.json',result)
    completed_row(direction,'区间门禁五档' if direction==1 else '门禁后回归、提升树、分类数值原型与组合',result)
    return result


def main(direction):
    WORK.mkdir(exist_ok=True)
    offline_guard()
    meta=load_meta()
    manifest=dict(source={str(p.relative_to(prior.ROOT)):file_sha(p) for p in
                         (Path(__file__),Path(lib.__file__),Path(models.__file__),Path(prior.__file__),
                          prior.ROOT/'studies/martin_luk/notes/PLAN_IE4_CN.md',
                          prior.ROOT/'studies/martin_luk/notes/PREREG_IE4_R1_CN.md',prior.OUTPUT)},
                  prepared_sha256=file_sha(prior.WORK/'prepared.json'))
    prior.write_json(WORK/f'direction{direction}_manifest.json',manifest)
    prepare_raw(meta)
    run_direction(meta,direction)
    for name,digest in manifest['source'].items():
        if file_sha(prior.ROOT/name)!=digest:
            raise ValueError('source changed during run: '+name)


def offline_guard():
    def audit(event,args):
        def allowed(path):
            p=Path(os.fsdecode(path)).resolve()
            return p.is_relative_to(WORK.resolve()) or p in (PROGRESS.resolve(),PROGRESS.with_suffix('.md.tmp').resolve()) or (
                p.parent==REPORTS.resolve() and p.name.startswith('strong_continue_ie4_'))
        if event=='open':
            path,mode,flags=args
            if not isinstance(path,int) and flags & (os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_TRUNC|os.O_APPEND):
                if not allowed(path): raise PermissionError('IE4 output boundary: '+os.fsdecode(path))
        if event in ('socket.connect','socket.bind','os.system','subprocess.Popen'):
            raise PermissionError('IE4 runs offline in one process')
        if event in ('os.remove','os.rename','os.rmdir','os.mkdir'):
            paths=args[:2] if event=='os.rename' else args[:1]
            if any(not allowed(p) for p in paths): raise PermissionError('IE4 output boundary')
    sys.addaudithook(audit)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('direction',type=int,choices=(1,2))
    main(parser.parse_args().direction)
