"""R77: the R8 sample on chronological five-minute bars with R74 daily management."""
import gc
import hashlib
import json
import math
from pathlib import Path

import numpy as np

from . import continue_round as C, measure as M, replicate as R
from studies.trend_breakout import panel


def normalize_bars(bars, days, raw_close, actions):
    """Undo the provider's affine QFQ, then use the same action-based ratio units as the daily panel."""
    a, b = np.ones(len(days)), np.zeros(len(days))
    for ex, aa, bb in sorted(actions):
        past = days < ex
        a[past] *= aa
        b[past] = b[past] * aa + bb
    ratio = np.full(len(days), np.nan)
    have = np.isfinite(raw_close)
    ratio[have] = panel.factors(raw_close[have], days[have], actions)
    bars[:, :, :4] = (bars[:, :, :4] - b[:,None,None]) / a[:,None,None] * ratio[:,None,None]
    finite = np.isfinite(bars[:, :, :4]).all(2)
    lo, hi = bars[:, :, 2], bars[:, :, 1]
    malformed = finite & ((hi < lo) | (bars[:,:,0] < lo-1e-5) | (bars[:,:,0] > hi+1e-5) |
                          (bars[:,:,3] < lo-1e-5) | (bars[:,:,3] > hi+1e-5))
    no_trade = finite & (bars[:,:,4] <= 0)
    bars[:,:,:4][malformed | no_trade] = np.nan
    return dict(malformed=int(malformed.sum()), zero_volume=int(no_trade.sum()))


def weekly_levels(A):
    """Prior inside-week high, only before its first break in the current week."""
    weeks = (np.array(A['days'], dtype='datetime64[D]').astype('int64') + 3) // 7
    levels = np.full_like(A['close'], np.nan)
    completed = []
    hi = np.full(A['close'].shape[1], np.nan)
    lo = hi.copy()
    for d, week in enumerate(weeks):
        if d and week != weeks[d - 1]:
            completed.append((hi.copy(), lo.copy()))
            completed = completed[-2:]
            hi[:] = np.nan
            lo[:] = np.nan
        if len(completed) == 2:
            (h0, l0), (h1, l1) = completed
            ok = (h1 <= h0) & (l1 >= l0) & ~(hi > h1)
            levels[d] = np.where(ok, h1, np.nan)
        hi, lo = np.fmax(hi, A['high'][d]), np.fmin(lo, A['low'][d])
    return levels


def trigger_day(bars, flags, levels, cap, floor, b_start):
    """Completed-bar decision using prior-day eligibility and only bars at/before that close."""
    pdh, pc, e9, e21, week_high, gap_size, volume_need = levels
    watch, tight, near, up, base, ep_pool = flags
    valid = np.flatnonzero(np.isfinite(bars[:,:4]).all(1))
    if not len(valid):
        return None
    first = int(valid[0])
    opening = bars[first, 0]
    gap = opening >= pc * (1 + gap_size)
    if not (watch or base or (ep_pool and gap)):
        return None
    dipped9 = dipped21 = handshake = False
    lod, volume = math.inf, 0.0
    for b, row in enumerate(bars):
        if not np.isfinite(row[:4]).all():
            continue
        lod = min(lod, row[2])
        volume += row[5] if np.isfinite(row[5]) else 0
        dipped9 |= row[2] <= e9
        dipped21 |= row[2] <= e21
        handshake |= row[2] <= max(e9, pdh)
        if b < max(first+1, b_start) or not np.isfinite(bars[b - 1, 1]):
            continue
        fill = row[3]
        bounce = fill > bars[b - 1, 1]
        w = watch and ((tight and fill > pdh) or
                       (near and (fill > pdh or (up and dipped9 and bounce))) or
                       (opening > pc * 1.01 and handshake and bounce) or
                       (np.isfinite(week_high) and fill > week_high))
        ep = ep_pool and gap and volume >= volume_need and fill > bars[first, 1]
        leader = base and (fill > pdh or ((dipped9 or dipped21) and bounce))
        if not (w or ep or leader):
            continue
        stop = min(max(lod, fill * (1 - cap)), fill * (1 - floor))
        return b, float(fill), float(stop)
    return None


def prepare(spec, cfg):
    full = R.us_arrays()
    _, rules, mask, pool = R.build_system(full, cfg)
    _, w, _ = R.system_signals(full, cfg)
    day_ok = R.market_ok(full, pool, w, cfg['filter'])
    _, ema = M.context(full, pool, rules)
    picked = set(json.loads(Path(spec['sample']).read_text())['picked'])
    cols = np.array([j for j, code in enumerate(full['codes']) if str(code) in picked])
    first = int(np.searchsorted(full['days'], '2023-06-01'))
    A = {k: v[first:, cols].copy() for k, v in full.items()
         if isinstance(v, np.ndarray) and v.ndim == 2 and v.shape == full['close'].shape}
    A.update(days=full['days'][first:], codes=full['codes'][cols], market='us')
    daily_ema = {k: v[first:, cols].copy() if v.ndim == 2 else v[first:].copy() for k, v in ema.items()}
    mask, pool, w = (x[first:, cols].copy() for x in (mask, pool, w))
    day_ok = day_ok[first:]
    # Compute history-dependent eligibility before discarding the broad panel and its warmup.
    btop = R.S._past_any((full['pr126'] >= 1 - cfg['bpath']) & full['rank_pool'], cfg['bopts']['lookback'])
    bup = R.prev(R.weekly_ema(full['close'], full['days'], 9) > R.weekly_ema(full['close'], full['days'], 21))
    near = R.prev((np.abs(full['close'] / full['e9'] - 1) <= .03) |
                  (np.abs(full['close'] / full['e21'] - 1) <= .03))
    base = (btop & bup & near)[first:, cols].copy() & pool
    del full, ema, btop, bup, near
    gc.collect()
    nday, nstock = A['close'].shape
    nbar = nday * 78
    cache = R.I.luk.CACHE / 'r77'
    cache.mkdir(exist_ok=True)
    px = {k: np.lib.format.open_memmap(cache / f'{k}.npy', mode='w+', dtype='float32', shape=(nbar, nstock))
          for k in ('open', 'high', 'low', 'close', 'mark')}
    for arr in px.values():
        arr[:] = np.nan
    times = [f'{(575 + b * 5) // 60:02d}:{(575 + b * 5) % 60:02d}' for b in range(78)]
    px.update(dates=np.array([str(day) + ' ' + tm for day in A['days'] for tm in times]),
              codes=A['codes'], session=np.repeat(np.arange(nday), 78))
    streams = {k: [[] for _ in range(nbar)] for k in ('CLOSE', *spec['candidates'])}
    cover, anomalies = [], []
    week = weekly_levels(A)
    last_bar = np.full(nday, -1)
    di = {str(day): d for d, day in enumerate(A['days'])}
    actions = panel.read_actions(R.I.R8_DAILY/'actions.csv.gz')
    for j, code in enumerate(A['codes']):
        path = R.I.R8_DIR / f'{str(code)[3:]}.csv.gz'
        raw = np.full((6, 1, nday, 78), np.nan, np.float32)
        R.I._k5_into(raw, 0, path, di)
        bars = raw[:, 0].transpose(1, 2, 0)
        quality = normalize_bars(bars,A['days'],A['raw'][:,j],actions.get(str(code),[]))
        valid = np.isfinite(bars[:, :, :4]).all(2)
        last = np.max(np.where(valid,np.arange(78),-1),axis=1)
        last_bar = np.maximum(last_bar, np.max(np.where(valid, np.arange(78), -1), axis=1))
        for z, key in enumerate(('open', 'high', 'low', 'close')):
            px[key][:, j] = bars[:, :, z].reshape(-1)
        observed = px['close'][:, j]
        known = np.maximum.accumulate(np.where(np.isfinite(observed), np.arange(nbar), 0))
        px['mark'][:, j] = observed[known]
        relevant = (A['days'] >= R.FULL[0]) & (A['days'] <= R.FULL[1])
        cover.append(dict(code=str(code), file=str(path.relative_to(R.I.luk.ROOT)),
                          days=int((valid.any(1) & relevant).sum()),
                          complete_days=int(((valid.sum(1) == 78) & relevant).sum()),
                          half_days=int(((valid.sum(1) == 42) & relevant).sum()), **quality))
        for d in np.flatnonzero(relevant & valid.any(1)):
            b = last[d]
            if b in (41,77):
                first_valid=int(np.flatnonzero(valid[d])[0])
                aggregate = (bars[d, first_valid, 0], np.nanmax(bars[d, :, 1]), np.nanmin(bars[d, :, 2]), bars[d, b, 3])
                err = max(abs(v / A[k][d, j] - 1) for v, k in zip(aggregate, ('open','high','low','close')))
                if err > .02:
                    anomalies.append(dict(code=str(code), day=str(A['days'][d]), error=float(err),
                                          in_pool=bool(pool[d,j]),
                                          daily=[float(A[k][d,j]) for k in ('open','high','low','close')],
                                          minute=[float(v) for v in aggregate]))
            if not day_ok[d] or d == 0:
                continue
            priority = -A['to20'][d - 1, j]
            cap = min(.05, .5 * A['adr'][d - 1, j] / 100)
            if mask[d, j] and b in (41, 77):
                fill = bars[d, b, 3]
                stop = min(max(np.nanmin(bars[d, :, 2]), fill * (1-cap)), fill * (1-cfg['stop_min']))
                streams['CLOSE'][d * 78 + b].append((priority,j,1,float(fill),float(stop),'close'))
            flags = (w[d,j], A['tight'][d-1,j], abs(A['close'][d-1,j]/A['e9'][d-1,j]-1)<=.03,
                     A['e9'][d-1,j]>A['e21'][d-1,j], base[d,j], pool[d,j])
            levels = (A['high'][d-1,j], A['close'][d-1,j], A['e9'][d-1,j], A['e21'][d-1,j], week[d,j],
                      max(.05,A['adr'][d-1,j]/100), 2*A['to20'][d-1,j])
            for name, opts in spec['candidates'].items():
                hit = trigger_day(bars[d],flags,levels,cap,cfg['stop_min'],opts['bar_start'])
                if hit:
                    b,fill,stop=hit
                    streams[name][d*78+b].append((priority,j,1,fill,stop,name))
        if (j+1)%20==0:
            print('R77 prepared',j+1,'/',nstock,flush=True)
    # Data anomalies are explicit: never convert a complete-day consistency check into a trading feature.
    coverage=dict(stocks=cover, price_anomalies=anomalies,
                  empty_sessions=[str(A['days'][d]) for d in np.flatnonzero(last_bar<0) if A['days'][d]>=R.FULL[0]])
    (R.I.OUT/'r77_coverage.json').write_text(json.dumps(coverage,indent=1))
    if anomalies:
        raise ValueError(f'{len(anomalies)} minute/daily price anomalies; inspect r77_coverage.json before evaluation')
    px['daily_close']=np.zeros(nbar,bool)
    px['daily_close'][np.arange(nday)*78+np.where(last_bar>=0,last_bar,77)]=True
    streams['CLOSE']=[entries if px['daily_close'][row] else [] for row,entries in enumerate(streams['CLOSE'])]
    for stream in streams.values():
        for d in range(nday):
            remaining=cfg['max_new']
            for b in range(78):
                ix=d*78+b
                stream[ix]=sorted(stream[ix],key=lambda e:e[0])[:remaining]
                remaining-=len(stream[ix])
    minute_ema={}
    for key, arr in daily_ema.items():
        if arr.ndim==1:
            minute_ema[key]=np.repeat(arr,78)
        else:
            minute_ema[key]=np.full((nbar,nstock),np.nan,np.float32)
            minute_ema[key][np.flatnonzero(px['daily_close'])]=arr
    minute_pool=np.repeat(pool,78,axis=0)
    daily_entries=R.entries_close_stop(A,mask & day_ok[:,None],cfg['stop'],stop_min=cfg['stop_min'])
    daily_entries=[sorted(e,key=lambda v:v[0])[:cfg['max_new']] for e in daily_entries]
    for v in px.values():
        if isinstance(v,np.memmap): v.flush()
    return A,px,minute_ema,rules,streams,minute_pool,pool,daily_ema,daily_entries,coverage


def audit_prices(px,trades):
    rows=[]
    ci={str(code):j for j,code in enumerate(px['codes'])}
    for t in sorted(trades,key=lambda x:-x['pnl'])[:15]:
        events=[]
        for e in t['executions']:
            d=int(np.searchsorted(px['dates'],e['time']));j=ci[t['code']]
            lo,hi=float(px['low'][d,j]),float(px['high'][d,j])
            if e['action']=='end' and not np.isfinite(lo):
                ok=bool(np.isclose(e['price'],px['mark'][d,j]))
            else:
                ok=bool(lo-1e-5<=e['price']<=hi+1e-5)
            if e['action'] in ('entry','add','trail','signal','time','no_follow'):
                ok &= bool(np.isclose(e['price'],px['close'][d,j]))
            events.append(dict(**e,low=lo,high=hi,verified=ok))
        assert all(e['verified'] for e in events),(t['code'],events)
        rows.append(dict(code=t['code'],entry=t['entry'],pnl=t['pnl'],executions=events))
    return rows


def evaluate(A,px,ema,rules,entries,pool,located,draws,seed):
    def one(start=R.FULL[0],rng=None,audit=False):
        curve,dates,tr=R.Y.simulate(px,ema,rules,entries,start,R.FULL[1]+' 23:59',placebo=rng,pool=pool,audit=audit)
        begin=int(np.searchsorted(px['dates'],start))
        end=begin+len(dates)
        daily=px['daily_close'][begin:end]
        return curve[daily],np.array([str(d)[:10] for d in dates[daily]]),tr
    curve,dates,tr=one(audit=True)
    audit=audit_prices(px,tr)
    for t in tr:
        t['entry_time'],t['exit_time']=t['entry'],t['exit']
        t['entry'],t['exit']=t['entry'][:10],t['exit'][:10]
    st=R.Y.stats(curve,dates,tr)
    st['behavior']=M.behavior(tr)
    st['bought']={k:[R.bought(A,tr,ls),len(ls)] for k,ls in located.items()}
    actual={(t['code'],t['entry']) for t in tr}
    st['bought_entry_date']={k:[sum((str(A['codes'][j]),t.entry_date) in actual for t,j,_,_ in ls),len(ls)]
                             for k,ls in located.items()}
    a=int(np.searchsorted(dates,'2026-01-01'));b=int(np.searchsorted(dates,'2026-07-31',side='right'))-1
    st['2026_jan_jul']=float(curve[b]/curve[a-1]-1)
    st['march_start']=R.Y.stats(*one('2024-03-01'))['by_year']
    rng=np.random.default_rng(seed)
    random=[]
    for n in range(draws):
        random.append(float(one(rng=rng)[0][-1]-1))
        if (n+1)%5==0: print('R77 placebo',n+1,'/',draws,flush=True)
    st['placebo']=dict(real=st['total'],median=float(np.median(random)),p90=float(np.percentile(random,90)),
                       rank=float(np.mean(np.array(random)<st['total'])),draws=draws,seed=seed)
    return st,audit


def run():
    path=R.ROUNDS/'R77.json';spec=json.loads(path.read_text());cfg=R.system_config_after(spec['base'][0])
    A,px,ema,rules,streams,pool,daily_pool,daily_ema,daily_entries,coverage=prepare(spec,cfg)
    ledger=R.L.load(R.LEDGER)
    located={k:[x for x in R.located_longs(A,part) if x[0].dated]
             for k,part in zip(('select','validate'),R.L.split(ledger,R.CUTOFF))}
    dpx={k:A[k] for k in ('open','high','low','close','codes')};dpx['dates']=A['days']
    control=M.summarize(A,dpx,daily_ema,rules,daily_entries,located)[0]
    out=dict(chosen='R76',chosen_config=cfg,spec_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
             scope='R8_200_local_sample_only',daily_control=control,sample={},price_audit={},coverage=coverage)
    for name,entries in streams.items():
        print('R77 evaluating',name,flush=True)
        st,audit=evaluate(A,px,ema,rules,entries,pool,located,spec['draws'],spec['seed'])
        out['sample'][name]=st;out['price_audit'][name]=audit
        print('R77 result',name,json.dumps(st,default=float),flush=True)
        (R.I.OUT/'r77.partial.json').write_text(json.dumps(out,indent=1,default=float))
    ref=out['sample']['CLOSE'];out['rejected']={}
    for name in spec['candidates']:
        st=out['sample'][name];bad=C.failures(st,ref)
        if abs(math.log1p(st['by_year']['2025'])-math.log(10.7))>=abs(math.log1p(ref['by_year']['2025'])-math.log(10.7)):
            bad.append('objective_not_improved')
        out['rejected'][name]=bad
    out['sample_passed']=[k for k,v in out['rejected'].items() if not v]
    (R.I.OUT/'r77.json').write_text(json.dumps(out,indent=1,default=float))
    print('R77 saved; global carry unchanged; sample candidates',out['sample_passed'],flush=True)


if __name__=='__main__':
    run()
