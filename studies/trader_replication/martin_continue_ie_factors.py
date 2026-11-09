"""IE A/B/C, offline and resumable; the 2026 price boundary is structural."""
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
import csv
from dataclasses import asdict
import gc
import hashlib
from itertools import groupby
import json
import os
from pathlib import Path
import resource
import sys
import warnings

import numpy as np

from studies.trader_replication import ie_factor_library as lib
from studies.trader_replication import martin_continue_ie as ie
from studies.trader_replication.martin_continue_ie_periods import file_sha

ROOT=Path(__file__).resolve().parents[2]
REPORTS=ROOT/'studies/trader_replication/reports/gap_review'
WORK=REPORTS/'ie_factor_work'
OUTPUT=REPORTS/'strong_continue_ie_factors.json'
CUTOFF='2025-12-31'
SCOPE_NAMES=('active300','leader_weekend')
TOPS=(1,3,5,10)
SENTINEL=65535
PREFILTER=100


def write_json(path,value):
    tmp=path.with_suffix(path.suffix+'.tmp')
    with tmp.open('w',encoding='utf-8') as f:
        json.dump(value,f,ensure_ascii=False,separators=(',',':'),allow_nan=False,default=ie.json_default)
        f.write('\n')
    tmp.replace(path)


def save_npz(path,**arrays):
    tmp=path.with_suffix('.npz.tmp')
    with tmp.open('wb') as stream: np.savez_compressed(stream,**arrays)
    tmp.replace(path)


def guard():
    """Enforce the user's filesystem and offline restrictions in the actual run."""
    work=WORK.resolve();report=OUTPUT.resolve()
    def audit(event,args):
        if event=='open':
            path,mode,flags=args
            if isinstance(path,int): return
            p=Path(os.fsdecode(path)).resolve()
            if flags & (os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_TRUNC|os.O_APPEND):
                if p==ie.PREREG.resolve() and flags & os.O_APPEND: return
                if p!=report and p!=OUTPUT.with_suffix('.json.tmp').resolve() and not p.is_relative_to(work):
                    raise PermissionError('IE writes only its workspace checkpoints and new result')
        if event in ('socket.connect','socket.bind','os.system','subprocess.Popen'):
            raise PermissionError('IE is offline, single-process')
        if event in ('os.remove','os.rename','os.rmdir','os.mkdir'):
            paths=args[:2] if event=='os.rename' else args[:1]
            if any(not Path(os.fsdecode(p)).resolve().is_relative_to(work) and
                   Path(os.fsdecode(p)).resolve() not in (report,OUTPUT.with_suffix('.json.tmp').resolve()) for p in paths):
                raise PermissionError('IE cannot mutate outside its checkpoint directory')
    sys.addaudithook(audit)


def stamp():
    return {str(p.relative_to(ROOT)):file_sha(p) for p in (
        Path(__file__),Path(lib.__file__),ROOT/'studies/trader_replication/ie_factor_models.py',
        ie.PREREG,ie.TIMELINE,ie.FRAMES,ROOT/'studies/martin_luk/notes/trades.csv',
        ROOT/'studies/martin_luk/notes/PLAN_IE_CN.md',ROOT/'studies/trader_options/live.py',
        ROOT/'studies/trader_data/live.py')}


def factor_specs():
    return [(s,t) for s in lib.inventory() for t in lib.TRANSFORMS]


def factor_name(s,t):
    return s.name if t=='pct' else s.name+'__'+t


def percentile(values):
    """Average ties; all missing and constant columns stay neutral."""
    x=np.asarray(values,float)
    if x.ndim==1: x=x[:,None]
    out=np.full(x.shape,.5,np.float32)
    for j in range(x.shape[1]):
        valid=np.flatnonzero(np.isfinite(x[:,j]));n=len(valid)
        if n<2: continue
        idx=valid[np.argsort(x[valid,j],kind='stable')];v=x[idx,j]
        a=np.r_[0,np.flatnonzero(v[1:]!=v[:-1])+1];b=np.r_[a[1:],n]
        out[idx,j]=np.repeat((a+b-1)/2/(n-1),b-a)
    return out


def split_id(day):
    if not '2024-01-01'<=day<=CUTOFF: raise ValueError('label outside frozen research years')
    return (int(day[:4])-2024)*2+int(day[5:7]>'06')


def load_inputs():
    frames=json.loads(ie.FRAMES.read_text(encoding='utf-8'))
    entries=sorted(frames['entries'],key=lambda r:(r['entry_date'],r['id']))
    if len(entries)!=32 or sum(r['target']['tier']=='primary' for r in entries)!=28:
        raise ValueError('stage two labels differ')
    timeline=json.loads(ie.TIMELINE.read_text(encoding='utf-8'))
    active={day:[r[0] for r in item['rows']] for day,item in timeline['nightly_candidates'].items() if day<=CUTOFF}
    baseline={day:{r[0]:r[1] for r in item['rows']} for day,item in timeline['nightly_candidates'].items() if day<=CUTOFF}
    digest=timeline['dataset_digest']
    del timeline
    return entries,active,baseline,digest


def earnings_arrays(days,events):
    """Calendar observability and next post-publication session are separate."""
    age=np.full(len(days),np.nan);index=np.full(len(days),-1,np.int32)
    observed=[]
    for r in events:
        pub=r['earnings_date'][:10]
        if pub>CUTOFF: continue
        typ=r['pub_type']
        visible=pub if typ in ('BEFORE','AFTER') else (date.fromisoformat(pub)+timedelta(days=1)).isoformat()
        session=int(np.searchsorted(days,pub,side='left' if typ=='BEFORE' else 'right'))
        observed.append((visible,pub,session))
    observed.sort()
    for i,day in enumerate(days):
        past=[r for r in observed if r[0]<=day]
        if past:
            _,pub,k=past[-1];age[i]=(date.fromisoformat(day)-date.fromisoformat(pub)).days
            if k<=i: index[i]=k
    return age,index


def option_arrays(code,days):
    out={};di={d:i for i,d in enumerate(days)}
    for kind in ('iv','stat'):
        path=ROOT/'data/trader-options-v1/us'/kind/(code+'.csv')
        if not path.exists(): continue
        with path.open() as f:
            for row in csv.DictReader(f):
                day=row['time'][:10]
                if day>CUTOFF or day not in di: continue
                for k,value in row.items():
                    if k in ('time','underlying_price'): continue
                    if k not in out: out[k]=np.full(len(days),np.nan)
                    try: v=float(value)
                    except (ValueError,TypeError): continue
                    if np.isfinite(v): out[k][di[day]]=v
    return out


def prepare():
    """Rebuild the fixed H4 support once, truncated before any 2026 calculation."""
    from studies import trader_data
    from studies.trader_replication import martin_continue_du as du, martin_continue_ep as ep
    from studies.trader_replication import martin_continue_hj as hj
    from studies.trader_replication.martin_continue_ea import LimitedDataset
    from studies.trader_replication.martin_strong import pct
    from studies.trader_replication.martin_strong_scan import HOLD
    if (WORK/'prepared.json').exists(): return
    entries,active,baseline,digest=load_inputs()
    base=trader_data.dataset('us',mode='frozen',version='trader-data-v1')
    if base.digest()!=digest: raise ValueError('frozen input digest differs')
    class Before2026(LimitedDataset):
        def actions(self):
            return {c:[a for a in rows if a[0]<=CUTOFF] for c,rows in self.base.actions().items()}
    ds=Before2026(base,CUTOFF)
    d=du.make_data(ds)
    if d.days[-1]>CUTOFF: raise AssertionError('2026 input escaped boundary')
    # market_arrays intentionally drops volume/raw-close. Recover just these two
    # fields in a streaming pass, without rebuilding another price panel.
    codes=list(map(str,d.A['codes']));ci={c:i for i,c in enumerate(codes)}
    d.A['volume']=np.full(d.c.shape,np.nan,np.float32)
    d.A['raw_close']=np.full(d.c.shape,np.nan,np.float32)
    for code,day,row in ds.rows():
        if code in ci and day in d.di:
            t,j=d.di[day],ci[code]
            d.A['raw_close'][t,j]=row[3]
            if np.isfinite(d.c[t,j]) and d.c[t,j]>0: d.A['volume'][t,j]=row[4]*row[3]/d.c[t,j]
    fields,mask,unused=du.compute_fields(d);del unused;gc.collect()
    events,eligible,_=ep.causal_inputs(ds,d,list(map(str,d.A['codes'])))
    fast=np.empty(events.shape,np.float32)
    for start in range(0,len(codes),64):
        sl=slice(start,start+64);fast[:,sl]=du._ROLL_MEAN(events[:,sl].astype(np.float32),250)
    fields['fast250']=fast;del fast
    del events
    fields['peer_pot'],pot=ep.peer_potential(d,eligible);del eligible
    fields.update(hj.coil_fields_chunked(d))
    codes=list(map(str,d.A['codes']));ci={c:i for i,c in enumerate(codes)};days=d.days
    windows=[[e['date'] for e in r['systems']['h4']] for r in entries]
    eval_days=sorted({day for w in windows for day in w})
    needed=sorted(set(eval_days)|{days[d.di[day]-5] for day in eval_days})
    leader={};scope={}
    for day in needed:
        t=d.di[day];a,b=ie.completed_week(days,t)
        with np.errstate(all='ignore'):
            v=d.c[b]*np.sum(d.A['volume'][a:b+1],axis=0)
            gain=d.c[b]/d.c[b-21]-1
        ix=np.flatnonzero((v>3e8)&np.isfinite(gain)&np.isfinite(d.c[t])&(d.c[t]>0))
        leader[day]=[codes[j] for j in ix]
        scope[day]={'active300':sorted(active[day]),'leader_weekend':sorted(leader[day])}
    # Original H4 group values, lag and ordinal ties are intentionally retained.
    groups=np.full((len(days),len(codes),6),np.nan,np.float32)
    for t in range(1,len(days)):
        for k,group in enumerate(HOLD['H4']):
            value=np.zeros(len(codes),np.float32)
            for field in group:
                value+=np.nan_to_num(pct(fields[field][t-1:t],mask[t:t+1])[0]-.5)/len(group)
            groups[t,mask[t],k]=value[mask[t]]+.5
    maxdiff=0.;membership=[];checks=0
    for day in needed:
        t=d.di[day];original=set(active[day]);current={codes[j] for j in np.flatnonzero(mask[t])}
        if original!=current: membership.append(dict(date=day,only_saved=sorted(original-current),only_rebuilt=sorted(current-original)))
        for code in original&current:
            value=float((groups[t,ci[code]]-.5).sum());maxdiff=max(maxdiff,abs(value-baseline[day][code]));checks+=1
    # Actual scope membership is always the saved stage-two active membership.
    # Float32 ties from a changed adjustment horizon are recorded, never hidden.
    if maxdiff>.05 or membership: raise AssertionError(('H4 replay differs materially',maxdiff,membership[:2]))
    earnings=defaultdict(list)
    with (ROOT/'data/trader-options-v1/us/earnings.csv').open() as f:
        for row in csv.DictReader(f):
            if row['earnings_date'][:10]<=CUTOFF: earnings[row['security']].append(row)
    wanted_codes=sorted({c for x in scope.values() for v in x.values() for c in v})
    data_hashes={}
    for path in [ROOT/'data/trader-options-v1/us/earnings.csv',ROOT/'data/martin-luk-benchmarks-v1/US.QQQ.csv']:
        data_hashes[str(path.relative_to(ROOT))]=file_sha(path)
    (WORK/'stocks').mkdir(exist_ok=True);(WORK/'group').mkdir(exist_ok=True)
    peer_g5=np.full(d.c.shape,np.nan,np.float32)
    rr=np.empty(d.c.shape,np.float32)
    for t in range(len(days)):
        r=d.c[t]/d.c[t-1]-1 if t else np.full(len(codes),np.nan)
        rr[t]=np.nan_to_num(r-np.nanmedian(np.where(d.rk[t]<300,r,np.nan)))
    # Retain only <=300 x <=300 graphs, never a full-universe correlation.
    graphs={};near=names=None
    for t in range(60,len(days)):
        cur=np.flatnonzero(d.rk[t]<300)
        if len(cur)<30: continue
        if near is None or t%5==0:
            w=rr[t-39:t+1][:,cur];w=w-w.mean(0);sd=w.std(0)+1e-6
            near=(w.T@w/len(w)/np.outer(sd,sd))>=.5;names=cur
            graphs[t]=(names.copy(),near.copy())
        g=d.c[t,names]/d.c[t-5,names]-1
        peer_g5[t,names]=(near*np.where(np.isfinite(g),g,0)).sum(1)/near.sum(1)
    for k,code in enumerate(wanted_codes):
        j=ci[code];age,ei=earnings_arrays(days,earnings[code])
        extras=dict(pot=pot[:,j],peer_g5=peer_g5[:,j],peer_rank=fields['peer_rank'][:,j],earn_days=age,earn_index=ei)
        extras.update({f'h4_{name}':groups[:,j,q] for q,name in enumerate(('activity','momentum','history','stack','peers','coil'))})
        extras.update(option_arrays(code,days))
        for kind in ('iv','stat'):
            path=ROOT/'data/trader-options-v1/us'/kind/(code+'.csv')
            if path.exists(): data_hashes[str(path.relative_to(ROOT))]=file_sha(path)
        arrays={k:d.A[v][:,j] for k,v in dict(o='open',h='high',l='low',c='close',v='volume',t='turnover',raw_c='raw_close').items()}
        np.savez(WORK/'stocks'/(code+'.npz'),**arrays,**{'extra_'+k:v for k,v in extras.items()})
    del groups,peer_g5,fields,mask;gc.collect()
    # Compute the group family one window at a time; persist sparse stock shards.
    for n in lib.WINDOWS:
        group=np.lib.format.open_memmap(WORK/'group_scratch.npy',mode='w+',dtype=np.float32,shape=(len(days),len(codes),8))
        group[:]=np.nan;near=names=None
        gain=np.full(d.c.shape,np.nan,np.float32);gain[n:]=d.c[n:]/d.c[:-n]-1
        rv=np.full(d.c.shape,np.nan,np.float32);pp=rv.copy()
        for start in range(0,len(codes),64):
            sl=slice(start,start+64)
            rv[:,sl]=d.A['volume'][:,sl]/du._ROLL_MEAN(d.A['volume'][:,sl],n)
            pp[:,sl]=du._ROLL_MEAN(pot[:,sl].astype(float),n)
        for t in range(60,len(days)):
            if t in graphs: names,near=graphs[t]
            if names is None: continue
            g=gain[t,names];valid=np.isfinite(g);weight=near*valid[None,:];den=weight.sum(1)
            mean=lib.divide(weight@np.nan_to_num(g),den);second=lib.divide(weight@np.nan_to_num(g*g),den)
            values=[mean,g-mean,lib.divide((weight&(g[None,:]>0)).sum(1),den),
                lib.divide(near@np.nan_to_num(rv[t,names]),(near*np.isfinite(rv[t,names])[None,:]).sum(1)),
                lib.divide(near@np.nan_to_num(pp[t,names]),(near*np.isfinite(pp[t,names])[None,:]).sum(1)),
                -np.sqrt(np.maximum(0,second-mean**2)),
                lib.divide(((g[None,:]<=g[:,None])&weight).sum(1),den)]
            for q,value in enumerate(values): group[t,names,q]=value
            cur=np.flatnonzero(d.rk[t]<300);gg=gain[t,cur];good=np.isfinite(gg)
            if good.any(): group[t,:,7]=np.mean(gg[good]>0)
        keys=('peer_return','peer_excess','peer_positive','peer_volume','peer_potent','peer_dispersion','peer_rank','breadth')
        for code in wanted_codes:
            np.savez_compressed(WORK/'group'/(code+f'.{n}.npz'),**{k:group[:,ci[code],q] for q,k in enumerate(keys)})
        group.flush();del group,gain,rv,pp;gc.collect();(WORK/'group_scratch.npy').unlink()
        print('prepared group window',n,flush=True)
    qqq=ie.du.required_fields.__globals__['bench'](days,'QQQ')
    np.save(WORK/'qqq.npy',qqq)
    meta=dict(days=days,codes=wanted_codes,scope=scope,eval_days=eval_days,windows=windows,entries=entries,
        dataset_digest=digest,h4_replay=dict(compared=checks,max_score_abs_difference=maxdiff,membership_differences=membership),
        prepared_last=days[-1],source_sha256={**stamp(),**data_hashes},peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    write_json(WORK/'prepared.json',meta)
    print('prepared',len(wanted_codes),'stocks',len(eval_days),'evaluation nights; cutoff',days[-1],flush=True)


def layout(meta):
    keys=[(day,code) for day in sorted(meta['scope']) for code in sorted(set().union(*[set(x) for x in meta['scope'][day].values()]))]
    index={k:i for i,k in enumerate(keys)}
    slices={s:{} for s in SCOPE_NAMES}
    for s in SCOPE_NAMES:
        for day,item in meta['scope'].items(): slices[s][day]=np.array([index[day,c] for c in item[s]],np.int32)
    bycode=defaultdict(list)
    for i,(day,code) in enumerate(keys): bycode[code].append((meta['days'].index(day),i))
    return keys,index,slices,bycode


def random_queries(meta,index,scope,draws=200,seed=20261102):
    """Same (original code, night) shares replacement across repeated labels."""
    rng=np.random.default_rng(seed);mapping={};out=np.full((draws,len(meta['entries']),4),-1,np.int32)
    for e,(entry,window) in enumerate(zip(meta['entries'],meta['windows'])):
        for w,day in enumerate(window):
            key=(entry['code'],day)
            candidates=meta['scope'][day][scope]
            if key not in mapping:
                mapping[key]=rng.integers(0,len(candidates),draws) if candidates else None
            if mapping[key] is not None:
                out[:,e,w]=[index[day,candidates[k]] for k in mapping[key]]
    return out


def shuffled_queries(meta,index,scope):
    rng=np.random.default_rng(20261103);mapping={};result=np.full((len(meta['entries']),4),-1,np.int32)
    for day in sorted(meta['eval_days']):
        names=meta['scope'][day][scope];perm=rng.permutation(len(names))
        mapping[day]={c:names[k] for c,k in zip(names,perm)}
    for e,(entry,window) in enumerate(zip(meta['entries'],meta['windows'])):
        for w,day in enumerate(window):
            names=meta['scope'][day][scope]
            code=mapping[day].get(entry['code'])
            if code is None and names:
                code=names[int(rng.integers(len(names)))];mapping[day][entry['code']]=code
            if code is not None: result[e,w]=index[day,code]
    return result


def actual_queries(meta,index,scope):
    return np.array([[index.get((day,r['code']),-1) if r['code'] in meta['scope'][day][scope] else -1
        for day in w] for r,w in zip(meta['entries'],meta['windows'])],np.int32)


def calculate_block(specs,meta,shape,bycode):
    """One indicator block, one stock at a time; raw and history shards on disk."""
    if meta['days'][-1]>CUTOFF: raise ValueError('2026 factor computation is forbidden')
    raw=np.lib.format.open_memmap(WORK/'raw_scratch.npy',mode='w+',dtype=np.float32,shape=(shape,len(specs)))
    hist=np.lib.format.open_memmap(WORK/'hist_scratch.npy',mode='w+',dtype=np.float32,shape=raw.shape)
    raw[:]=np.nan;hist[:]=np.nan
    qqq=np.load(WORK/'qqq.npy')
    for code,positions in bycode.items():
        with np.load(WORK/'stocks'/(code+'.npz')) as z:
            arrays={k:z[k] for k in z.files if not k.startswith('extra_')}
            extras={k[6:]:z[k] for k in z.files if k.startswith('extra_')}
        if specs[0].family=='group':
            for n in {s.parameter for s in specs}:
                with np.load(WORK/'group'/(code+f'.{n}.npz')) as z:
                    extras.update({f'group.{k}.{n}':z[k] for k in z.files})
        stock=lib.Stock(arrays,meta['days'],qqq,extras)
        values={}
        for n in dict.fromkeys(s.parameter for s in specs): values[n]=stock.evaluate(specs[0].family,n)
        x=np.column_stack([values[s.parameter][s.metric] for s in specs])
        rows=np.array([p[0] for p in positions]);dest=np.array([p[1] for p in positions])
        raw[dest]=x[rows];hist[dest]=lib.history_rank(x,rows)
        stock.ema.cache_clear();stock.f_hilbert.cache_clear()
        del stock,arrays,extras,values,x
    raw.flush();hist.flush()
    return raw,hist


def transformed(raw,hist,slices,meta):
    """Yield at most one scope's small indicator block; lag is a market-day lag."""
    di={d:i for i,d in enumerate(meta['days'])}
    for scope in SCOPE_NAMES:
        p=np.full(raw.shape,.5,np.float32)
        for day,rows in slices[scope].items(): p[rows]=percentile(raw[rows])
        for trans in lib.TRANSFORMS:
            if trans=='pct': yield scope,trans,p
            elif trans=='history250':
                value=np.full(raw.shape,.5,np.float32)
                for day in meta['eval_days']:
                    rows=slices[scope][day];value[rows]=percentile(hist[rows])
                yield scope,trans,value
            else:
                value=np.full(raw.shape,.5,np.float32)
                for day in meta['eval_days']:
                    rows=slices[scope][day];prev=meta['days'][di[day]-5]
                    lookup=dict(zip(meta['scope'][prev][scope],slices[scope][prev]))
                    prior=np.array([lookup.get(c,-1) for c in meta['scope'][day][scope]])
                    old=np.full((len(rows),raw.shape[1]),.5,np.float32);valid=prior>=0
                    old[valid]=p[prior[valid]]
                    value[rows]=percentile(p[rows]-old)
                yield scope,trans,value


def ranks_for_values(value,slices,meta,scope):
    rank=np.full(value.shape,SENTINEL,np.uint16)
    for day in meta['eval_days']:
        rows=slices[scope][day]
        if len(rows)>=SENTINEL: raise ValueError('rank storage too small')
        # Scope rows are code-ascending, stable sort resolves exact ties.
        order=np.argsort(-value[rows],axis=0,kind='stable')
        inverse=np.empty_like(order);np.put_along_axis(inverse,order,np.arange(len(rows))[:,None],axis=0)
        rank[rows]=inverse+1
    return rank


def take_ranks(rank,query):
    out=rank[np.maximum(query,0)]
    return np.where((query>=0)[...,None],out,SENTINEL).astype(np.uint16)


def stage_a(meta):
    keys,index,slices,bycode=layout(meta);specs=lib.inventory();allmeta=[]
    primary=np.array([r['target']['tier']=='primary' for r in meta['entries']])
    seen=set();unique=np.zeros(len(primary),bool)
    for i,r in enumerate(meta['entries']):
        key=(r['code'],r['entry_date'])
        if key not in seen: unique[i]=True;seen.add(key)
    queries={s:actual_queries(meta,index,s) for s in SCOPE_NAMES}
    random={s:random_queries(meta,index,s) for s in SCOPE_NAMES}
    shuffled={s:shuffled_queries(meta,index,s) for s in SCOPE_NAMES}
    (WORK/'a').mkdir(exist_ok=True)
    families=list(dict.fromkeys(s.family for s in specs))
    for block,family in enumerate(families):
        target=WORK/'a'/(family+'.npz')
        subset=[s for s in specs if s.family==family]
        if target.exists():
            print('resume A',family,flush=True);continue
        print('A block',block+1,'/',len(families),family,len(subset),'base indicators',flush=True)
        raw,hist=calculate_block(subset,meta,len(keys),bycode)
        out={};missing={}
        for scope,trans,value in transformed(raw,hist,slices,meta):
            prefix=scope+'_'+trans
            rank=ranks_for_values(value,slices,meta,scope)
            true=take_ranks(rank,queries[scope]);shuffle=take_ranks(rank,shuffled[scope])
            out[prefix+'_rank']=true.transpose(2,0,1);out[prefix+'_shuffle']=shuffle.transpose(2,0,1)
            # 200 draws are reduced one factor at a time, not a 4-D market matrix.
            null=np.zeros((len(subset),200,4),np.uint8)
            for j in range(len(subset)):
                rr=np.where(random[scope]>=0,rank[np.maximum(random[scope],0),j],SENTINEL)
                best=rr[:,primary].min(2)
                for k,top in enumerate(TOPS): null[j,:,k]=(best<=top).sum(1)
            out[prefix+'_null']=null
            ids=np.concatenate([slices[scope][day] for day in meta['eval_days']])
            base_values=hist[ids] if trans=='history250' else raw[ids]
            out[prefix+'_missing']=np.mean(~np.isfinite(base_values),axis=0)
            del rank,value
        save_npz(target,**out)
        del raw,hist,out;gc.collect()
        for name in ('raw_scratch.npy','hist_scratch.npy'): (WORK/name).unlink()
        print('A saved',family,'rss KiB',resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,flush=True)
    factors=factor_specs();names=[factor_name(s,t) for s,t in factors]
    ranks={s:np.empty((len(factors),len(primary),4),np.uint16) for s in SCOPE_NAMES}
    shuffle={s:np.empty_like(ranks[s]) for s in SCOPE_NAMES}
    nullmax={s:np.zeros((200,4),np.uint8) for s in SCOPE_NAMES};summary=[]
    loaded={}
    for f,(spec,trans) in enumerate(factors):
        if spec.family not in loaded:
            loaded.clear()
            with np.load(WORK/'a'/(spec.family+'.npz')) as z:
                loaded[spec.family]={k:z[k] for k in z.files}
        z=loaded[spec.family];subset=[s for s in specs if s.family==spec.family];j=subset.index(spec)
        row=dict(name=names[f],family=spec.family,parameter=spec.parameter,metric=spec.metric,transform=trans,formula=spec.formula,scopes={})
        for scope in SCOPE_NAMES:
            p=scope+'_'+trans;r=z[p+'_rank'][j];ranks[scope][f]=r;shuffle[scope][f]=z[p+'_shuffle'][j]
            nullmax[scope]=np.maximum(nullmax[scope],z[p+'_null'][j])
            row['scopes'][scope]=dict(missing_fraction=float(z[p+'_missing'][j]),
                **{tier:dict(n=int(mask.sum()),top={str(k):int((r[mask].min(1)<=k).sum()) for k in TOPS},
                    prior_evening_top={str(k):int((r[mask,-1]<=k).sum()) for k in TOPS},
                    best_ranks=[int(v) if v!=SENTINEL else None for v in r[mask].min(1)])
                    for tier,mask in (('primary',primary),('secondary',~primary),('all',np.ones(len(primary),bool)),
                                      ('primary_unique',primary&unique),('all_unique',unique))})
        summary.append(row)
    for scope in SCOPE_NAMES:
        np.save(WORK/(scope+'_ranks.npy'),ranks[scope]);np.save(WORK/(scope+'_shuffle_ranks.npy'),shuffle[scope])
    cross=np.maximum.reduce(list(nullmax.values()))
    thresholds={str(k):int(np.sort(cross[:,j])[189]) for j,k in enumerate(TOPS)}
    for row in summary:
        for scope in SCOPE_NAMES:
            observed=row['scopes'][scope]['primary']['top']['5']
            row['scopes'][scope]['effective_top5']=observed>thresholds['5']
            row['scopes'][scope]['familywise_p_top5']=(1+int((cross[:,2]>=observed).sum()))/201
    result=dict(factors=summary,factor_count=len(factors),base_count=len(specs),
        family_counts=dict(Counter(s.family for s,t in factors)),
        null=dict(seed=20261102,draws=200,cross_scope_threshold95=thresholds,
            cross_scope_maximum=cross.tolist(),scope_maximum={s:v.tolist() for s,v in nullmax.items()}),
        queries={s:queries[s].tolist() for s in SCOPE_NAMES},shuffle_queries={s:shuffled[s].tolist() for s in SCOPE_NAMES})
    write_json(WORK/'a.json',result)
    return result


def future_evaluation(meta):
    keys,index,slices,bycode=layout(meta);out={day:{} for day in meta['eval_days']}
    for code,positions in bycode.items():
        with np.load(WORK/'stocks'/(code+'.npz')) as z: c,h=z['c'],z['h']
        for t,dest in positions:
            day=meta['days'][t]
            if day not in out: continue
            stop=min(t+20,len(c)-1);w=h[t+1:stop+1];valid=np.isfinite(w)&(w>0)
            gain=float(np.max(w[valid])/c[t]-1) if valid.any() and np.isfinite(c[t]) else None
            end=float(c[stop]/c[t]-1) if stop>t and np.isfinite(c[stop]+c[t]) else None
            out[day][code]=dict(max_high_gain=gain,end_close_gain=end,valid_high_bars=int(valid.sum()),
                observed_market_sessions=stop-t,complete=stop-t==20 and int(valid.sum())==20)
    return out


def ahead_records(meta,scope,values,keys,slices):
    table={};records=[]
    for e,(entry,window) in enumerate(zip(meta['entries'],meta['windows'])):
        nights=[]
        for day in window:
            names=meta['scope'][day][scope];rows=slices[scope][day]
            if entry['code'] not in names:
                nights.append(dict(date=day,rank=None,width=len(names),ahead=[]));continue
            order=np.argsort(-values[rows],kind='stable');ordered=[names[j] for j in order]
            rank=ordered.index(entry['code'])+1
            ahead=[dict(code=names[j],score=float(values[rows[j]])) for j in order[:rank-1]]
            nights.append(dict(date=day,rank=rank,width=len(names),score=float(values[rows[names.index(entry['code'])]]),ahead=ahead))
        records.append(dict(id=entry['id'],code=entry['code'],entry_date=entry['entry_date'],tier=entry['target']['tier'],nights=nights,
            best_rank=min((r['rank'] for r in nights if r['rank'] is not None),default=None)))
    return records


def saved_factor(meta,scope,index,slices,total_rows):
    path=WORK/'design'/f'{scope}.{index}.npy'
    if not path.exists(): return None
    rows=np.concatenate([slices[scope][day] for day in meta['eval_days']])
    column=np.load(path)
    if column.shape!=(len(rows),) or not np.isfinite(column).all() or np.any((column<0)|(column>1)):
        raise ValueError('invalid saved percentile column: '+str(path))
    value=np.full(total_rows,.5,np.float32);value[rows]=column
    return value


def check_ahead_ranks(scope,index,records):
    expected=np.load(WORK/(scope+'_ranks.npy'),mmap_mode='r')[index]
    observed=np.array([[n['rank'] if n['rank'] is not None else SENTINEL for n in r['nights']]
                       for r in records],np.uint16)
    if not np.array_equal(observed,expected):
        raise AssertionError('C report ranks differ from saved A: '+scope+' '+str(index))


def finish(meta,a,b):
    from studies.trader_replication.ie_factor_models import Design
    if stamp()!=json.loads((WORK/'run_manifest.json').read_text()): raise ValueError('input changed during research')
    if meta['prepared_last']>CUTOFF or any(day>CUTOFF for day in meta['eval_days']):
        raise ValueError('2026 finish inputs are forbidden')
    completed_pins=json.loads((WORK/'ab_completion_pins.json').read_text()) if (WORK/'ab_completion_pins.json').exists() else {}
    for name,digest in completed_pins.items():
        if file_sha(WORK/name)!=digest: raise ValueError('completed A/B checkpoint changed: '+name)
    report_inputs={name:file_sha(WORK/name) for name in ('a.json','b.json','final_scores.npy','prepared.json')}
    (WORK/'c').mkdir(exist_ok=True)
    keys,index,slices,bycode=layout(meta);factors=factor_specs()
    primary=np.array([r['target']['tier']=='primary' for r in meta['entries']])
    family_best=[]
    for scope in SCOPE_NAMES:
        ranks=np.load(WORK/(scope+'_ranks.npy'))
        for family in dict.fromkeys(s.family for s,t in factors):
            ids=[i for i,(s,t) in enumerate(factors) if s.family==family]
            def key(i):
                best=ranks[i,primary].min(1)
                return (int((best<=5).sum()),float(np.where(best<SENTINEL,1/np.maximum(best,1),0).sum()),-i)
            j=max(ids,key=key)
            family_best.append(dict(scope=scope,family=family,index=j,name=factor_name(*factors[j]),
                **a['factors'][j]['scopes'][scope]))
    family_ahead=[]
    for family in dict.fromkeys(s.family for s,t in factors):
        chosen=[r for r in family_best if r['family']==family]
        selection=[[r['scope'],r['index']] for r in chosen]
        checkpoint=WORK/'c'/(family+'.json')
        if checkpoint.exists():
            saved=json.loads(checkpoint.read_text())
            if saved['inputs']!=report_inputs or saved['selection']!=selection:
                raise ValueError('C checkpoint inputs differ: '+family)
            for item,record in zip(chosen,saved['records']): check_ahead_ranks(item['scope'],item['index'],record['rows'])
            family_ahead.extend(saved['records']);print('resume C',family,flush=True);continue
        records=[];missing=[]
        for item in chosen:
            value=saved_factor(meta,item['scope'],item['index'],slices,len(keys))
            if value is None: missing.append(item);continue
            rows=ahead_records(meta,item['scope'],value,keys,slices)
            check_ahead_ranks(item['scope'],item['index'],rows)
            records.append(dict(scope=item['scope'],family=family,factor=item['name'],rows=rows,score_source='saved_design'))
        if missing:
            subset=list(dict.fromkeys(factors[r['index']][0] for r in missing))
            print('C report columns',family,'reconstruct',len(subset),flush=True)
            raw,hist=calculate_block(subset,meta,len(keys),bycode)
            for scope,trans,value in transformed(raw,hist,slices,meta):
                for item in missing:
                    spec,t=factors[item['index']]
                    if scope==item['scope'] and trans==t:
                        rows=ahead_records(meta,scope,value[:,subset.index(spec)],keys,slices)
                        check_ahead_ranks(scope,item['index'],rows)
                        records.append(dict(scope=scope,family=family,factor=item['name'],rows=rows,score_source='frozen_formula'))
            del raw,hist;gc.collect()
            for name in ('raw_scratch.npy','hist_scratch.npy'): (WORK/name).unlink()
        records.sort(key=lambda r:SCOPE_NAMES.index(r['scope']))
        write_json(checkpoint,dict(inputs=report_inputs,selection=selection,records=records))
        family_ahead.extend(records);print('C saved',family,flush=True)
    final=b['final'];scores=np.load(WORK/'final_scores.npy');scope=final['scope'];design=Design(meta,scope,a)
    value=np.zeros(len(keys));value[design.global_rows]=scores
    final_rows=ahead_records(meta,scope,value,keys,slices)
    frozen_sorting_sha256=hashlib.sha256(json.dumps(final,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    evaluation=future_evaluation(meta)
    duplicate_factors={}
    for scope in SCOPE_NAMES:
        ranks=np.load(WORK/(scope+'_ranks.npy'));groups=defaultdict(list)
        for j,r in enumerate(ranks): groups[hashlib.sha256(r.tobytes()).hexdigest()].append(a['factors'][j]['name'])
        duplicate_factors[scope]=dict(distinct_target_rank_signatures=len(groups),
            warning='仅本人窗口排名相同，不代表全范围因子完全相同',
            largest_equivalent_target_rank_groups=sorted(groups.values(),key=len,reverse=True)[:5])
    text=('\n\n### IE 第三段 C 最终冻结（2024–25；A/B/C 完成后追加）\n\n'
        f"最终范围 `{scope}`；方法 `{final['method']}`；固定档次 `{final['level']}`。"
        f"四段外层留出前5覆盖 **{final['outer_hits']}/{final['n']}**；此数字参与最终候选择优，仍有选择偏差。"
        '完整因子、方向、权重或树结构和原型历史见本轮 JSON 的 `B.final`，不改登记版，不接账户。\n\n'
        '冻结因子：'+ '、'.join('`'+s+'`' for s in final['frozen_features'])+'。\n\n'
        f"冻结排序 SHA256 `{frozen_sorting_sha256}`，对应本轮 JSON 的 `B.final`。条件 logit 使用 `score=sum(w_j*(P_j-0.5))`，权重按 `B.final.model.features` 与 `weights` 逐项对应。\n\n"
        '因子及模型的日 K 和期权时序输入截至 2025-12-31；主次标签沿用第二段，不重算其后续走势。无 2026 因子或模型结果。缺值中性0.5、范围内平均并列百分位；最终同分代码升序。'
        '下一步仅在另行授权后单次评测2026，本次停下。源码／输入摘要及完整计算清单保存在 '
        '`studies/trader_replication/reports/gap_review/strong_continue_ie_factors.json`。\n')
    # Append only after all evaluations. The audit hook only permits O_APPEND.
    execution_hashes=stamp()
    with ie.PREREG.open('a',encoding='utf-8') as stream: stream.write(text)
    result=dict(stage=3,parts_completed=['A','B','C'],cutoff=CUTOFF,no_2026_factor_or_model_results=True,
        generated_utc=datetime.now(timezone.utc).isoformat(),input_sha256=meta['source_sha256'],
        execution_source_sha256=execution_hashes,
        prereg_after_freeze_sha256=file_sha(ie.PREREG),dataset_digest=meta['dataset_digest'],
        entries=[dict(id=r['id'],code=r['code'],entry_date=r['entry_date'],tier=r['target']['tier'],fold=split_id(r['entry_date'])) for r in meta['entries']],
        A=a,B=b,family_best=family_best,final_ranking=final_rows,family_ahead=family_ahead,
        C=dict(frozen_sorting_sha256=frozen_sorting_sha256,only_finish=True,model_scores_source='final_scores.npy',
            preserved_A_B_sha256=completed_pins,report_inputs_sha256=report_inputs,
            family_score_sources=dict(Counter(r['score_source'] for r in family_ahead))),
        plan_change_audit=json.loads((WORK/'finish_plan_audit.json').read_text())
            if (WORK/'finish_plan_audit.json').exists() else None,
        future20_evaluation=evaluation,h4_replay=meta['h4_replay'],
        anomalies=dict(equivalent_target_rank_signatures=duplicate_factors,
            wholly_missing_factors={s:[r['name'] for r in a['factors'] if r['scopes'][s]['missing_fraction']==1] for s in SCOPE_NAMES},
            unavailable=['缺历史股本，筹码换手率使用预登记量价代理，非真实流通筹码',
                '61种蜡烛与Hilbert为明示公式的numpy因果实现，未声称TA-Lib逐点兼容',
                '无点时题材／行业／人工名单；同伙限原相关图',
                '财报表中附带现价、IV等为采集时快照，全部禁止使用；仅历史日期和有日期的IV/stat时序',
                'IV/stat不存在的标的和长窗口预热不足保持缺失，不取数补齐']),
        processing=dict(single_research_process=True,network_access=False,data_cache_written=False,
            peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,checkpoint_directory=str(WORK.relative_to(ROOT)),
            largest_correlation_width=300,screened_features_per_fit=PREFILTER),
        live_data_audit=dict(passed=True,daily_bars='studies/trader_data/live.py:LiveDataset.update',
            options_and_earnings='studies/trader_options/live.py:refresh',
            allowed_cached_types=['日K、公司行动','历史IV/HV','历史期权量及未平仓量','已发生财报日期','QQQ基准'],
            historical_only_metadata_used_as_factor=False,
            prototypes='冻结的训练实例；每日只更新当前因子，不要求补录新本人交易',
            refreshed_in_this_run=False),
        implementation_notes=['每股OHLC固定首个有效收盘=100，成交量相反缩放，使筹码对数网格也不受未来行动公共复权尺度影响；比例/方向/清单不变',
            '使用T/复权成交量作为复权均价，与原average_price的raw-volume输入约定等价，不重复复权'],
        implementation_compatibility=json.loads((WORK/'implementation_compatibility.json').read_text())
            if (WORK/'implementation_compatibility.json').exists() else None,
        limitations=['本人台账选择性披露且有重复、日期近似；按笔与去重敏感性并报',
            '2024–25已反复研究，四段留出为分块CV，早段可能用晚段训练；不称前向独立样本外',
            '最终方案按外层结果择优，有选择偏差；标签打乱仅一次完整流程对照',
            '单因子门槛已同时覆盖全部参数、变换、体系和两个范围；未对收益或交易可行性作验证',
            '前5覆盖是候选排序问题，尚不等于买入他的票或复刻本人收益'])
    write_json(OUTPUT,result)
    print('completed A/B/C',final['scope'],final['method'],final['outer_hits'],'/',final['n'],'wrote',OUTPUT,flush=True)


def main(command='run'):
    if command not in ('run','prepare','a','finish'): raise ValueError('expected run, prepare, a or finish')
    WORK.mkdir(exist_ok=True)
    (WORK/'.gitignore').write_text('*\n',encoding='utf-8')
    if '### IE 系统扩库完整冻结清单' not in ie.PREREG.read_text(encoding='utf-8'):
        raise ValueError('complete inventory must be preregistered before computation')
    guard()
    if OUTPUT.exists(): raise FileExistsError('refusing to overwrite IE final report')
    manifest=WORK/'run_manifest.json';current=stamp()
    if manifest.exists():
        if json.loads(manifest.read_text())!=current: raise ValueError('checkpoint source/input fingerprint changed')
    else: write_json(manifest,current)
    if command=='finish':
        meta=json.loads((WORK/'prepared.json').read_text())
        a=json.loads((WORK/'a.json').read_text());b=json.loads((WORK/'b.json').read_text())
        finish(meta,a,b)
        return
    prepare()
    meta=json.loads((WORK/'prepared.json').read_text())
    if meta['prepared_last']>CUTOFF: raise ValueError('checkpoint crossed the forbidden 2026 boundary')
    if command=='prepare': return
    a=stage_a(meta)
    if command=='a': return
    from studies.trader_replication import ie_factor_models as models
    b=models.run(meta,a)
    finish(meta,a,b)


if __name__=='__main__':
    warnings.filterwarnings('ignore',category=RuntimeWarning)
    main(sys.argv[1] if len(sys.argv)>1 else 'run')
