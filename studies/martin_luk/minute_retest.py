"""Five-minute execution diagnostics: strict R77 inputs or provider-conditional R91 inputs."""
import gc
import hashlib
import json
import math
import os
import sys
from dataclasses import replace
from pathlib import Path

import numpy as np

from . import continue_round as C, measure as M, replicate as R
from studies.trend_breakout import panel


def cap_signal_stream(stream, limit, bars_per_session=78):
    """Cap chronological raw attempts; zero leaves all attempts for portfolio capacity checks."""
    if limit < 0:
        raise ValueError('signal limit must be nonnegative')
    out = []
    for row, entries in enumerate(stream):
        if row % bars_per_session == 0:
            remaining = limit
        ranked = sorted(entries, key=lambda e: e[0])
        selected = ranked[:remaining] if limit else ranked
        out.append(selected)
        remaining -= len(selected)
    return out


def minute_priority(bars, bar, prior_close, prior_turnover, mode=None):
    """Rank only simultaneous completed-bar orders; ties retain prior dollar-volume priority."""
    if mode is None:
        return -float(prior_turnover)
    if mode=='gain':
        score=float(bars[bar,3]/prior_close-1) if prior_close>0 else math.nan
    elif mode=='rvol':
        observed=bars[:bar+1]
        valid=np.isfinite(observed[:,:4]).all(1)&np.isfinite(observed[:,5])
        score=float(observed[valid,5].sum()/prior_turnover) if prior_turnover>0 else math.nan
    else:
        raise ValueError('unknown minute priority: '+mode)
    return (-score if np.isfinite(score) else math.inf,-float(prior_turnover))


def minute_kind(name, opts, prior_turnover):
    if opts.get('liquidity_groups'):
        return 'thin' if prior_turnover<100e6 else 'premier'
    return name


def carried_scoreboard(filename):
    report = json.loads((R.I.OUT / filename).read_text())
    return report['global_scoreboard'] if 'global_scoreboard' in report else report['full'][report['chosen']]


def normalize_bars(bars, days, raw_close, actions, rehab=None, source_asof=None, target_factor=None):
    """Undo the provider's affine QFQ, then use the same action-based ratio units as the daily panel."""
    a, b = np.ones(len(days)), np.zeros(len(days))
    for ex, aa, bb in sorted(actions):
        if source_asof is not None and ex > source_asof:
            continue
        past = days < ex
        a[past] *= aa
        b[past] = b[past] * aa + bb
    if target_factor is None:
        ratio = np.full(len(days), np.nan)
        have = np.isfinite(raw_close)
        ratio[have] = panel.factors(raw_close[have], days[have], actions)
    else:
        # The daily panel retains its original full-history action units when the evaluation is truncated.
        ratio = np.asarray(target_factor)
    raw_prices = (bars[:, :, :4] - b[:,None,None]) / a[:,None,None]
    bars[:, :, :4] = raw_prices * ratio[:,None,None]
    finite = np.isfinite(bars[:, :, :4]).all(2)
    lo, hi = bars[:, :, 2], bars[:, :, 1]
    malformed = finite & ((hi < lo) | (bars[:,:,0] < lo-1e-5) | (bars[:,:,0] > hi+1e-5) |
                          (bars[:,:,3] < lo-1e-5) | (bars[:,:,3] > hi+1e-5))
    no_trade = finite & (bars[:,:,4] <= 0)
    bad = malformed | no_trade
    quality = dict(malformed=int(malformed.sum()), zero_volume=int(no_trade.sum()))
    if rehab is not None:
        shares = np.ones(len(days))
        for row in rehab:
            past = days < row['ex_div_date']
            if not past.any():
                continue
            split = row.get('split_ratio')
            if split:
                shares[past] /= split
            if row.get('spin_off_ratio'):
                shares[past] /= row['spin_off_ratio']
            for key in ('per_share_div_ratio','per_share_trans_ratio'):
                if row.get(key):
                    shares[past] *= 1 + 1/row[key]
            if row.get('allotment_ratio') or row.get('stk_spo_ratio'):
                raise ValueError('rights/issuance volume adjustment needs source verification')
        with np.errstate(divide='ignore', invalid='ignore'):
            vwap = bars[:,:,5] / bars[:,:,4] * shares[:,None]
        missing = finite & (bars[:,:,4]>0) & (~np.isfinite(vwap) | (vwap<=0))
        outside = finite & (bars[:,:,4]>0) & np.isfinite(vwap) & (
            (vwap < raw_prices[:,:,2]-.01) | (vwap > raw_prices[:,:,1]+.01))
        # Raw provider VWAP also disagrees with OHLC; the underlying cause is unresolved.
        # This is an audit flag, not evidence sufficient to delete an OHLC bar.
        quality.update(vwap_outside=int(outside.sum()),vwap_unavailable=int(missing.sum()))
    bars[:,:,:4][bad] = np.nan
    return quality


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


def hourly_support(bars):
    """RTH hourly EMAs, exposed only after completion and only while rising; one stock at a time."""
    out=np.full((*bars.shape[:2],2),np.nan)
    value=np.full(2,np.nan);rising=np.zeros(2,bool);alpha=np.array([.2,2/22])
    for d,day in enumerate(bars):
        start=0;last_update=-1
        valid=np.isfinite(day[:,:4]).all(1)
        for end in (*range(11,72,12),77):
            out[d,start:end+1]=np.where(rising,value,np.nan)
            if end==77:
                # At session end all remaining observed bars are in the past, including a half-day tail.
                tail=np.flatnonzero(valid & (np.arange(78)>last_update))
                mark=int(tail[-1]) if len(tail) else None
            else:
                mark=end if valid[start:end+1].all() else None
            if mark is not None:
                old=value.copy();close=day[mark,3]
                value=np.where(np.isfinite(value),value+alpha*(close-value),close)
                rising=value>old;last_update=mark
            start=end+1
    return out


def entry_stop(bars, bar, lod, cap, floor, mode=None):
    """Keep the original capped LOD, or wait for a causal narrow structural stop."""
    fill=bars[bar,3]
    if mode is None:
        return min(max(lod,fill*(1-cap)),fill*(1-floor))
    fill=float(fill)
    if mode not in ('lod3','bar3'):
        raise ValueError('unknown stop mode: '+str(mode))
    limit=min(.03,cap)
    if not np.isfinite(fill) or fill<=0 or not np.isfinite(lod) or lod<=0 or limit<floor:
        return None
    if fill/lod-1<=.03+1e-12 and 1-lod/fill<=limit+1e-12:
        low=lod
    elif mode=='bar3':
        lows=[float(bars[b,2]) for b in (bar-1,bar) if b>=0 and np.isfinite(bars[b,:4]).all()
              and 0<bars[b,2]<fill]
        if not lows:
            return None
        low=max(lows)
    else:
        return None
    if 1-low/fill>limit+1e-12:
        return None
    return min(low,fill*(1-floor))


def trigger_day(bars, flags, levels, cap, floor, b_start, trigger_mode=None, hourly=None, stop_mode=None, trace=None):
    """Completed-bar decision using prior-day eligibility and only bars at/before that close."""
    if trigger_mode not in (None,'previous_bar','hourly_pullback','opening_range'):
        raise ValueError('unknown trigger mode: '+str(trigger_mode))
    if trigger_mode=='hourly_pullback' and hourly is None:
        raise ValueError('hourly pullback needs completed-hour support')
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
    dipped9 = dipped21 = handshake = hour_touch = False
    lod, volume = math.inf, 0.0
    for b, row in enumerate(bars):
        if not np.isfinite(row[:4]).all():
            continue
        lod = min(lod, row[2])
        volume += row[5] if np.isfinite(row[5]) else 0
        dipped9 |= row[2] <= e9
        dipped21 |= row[2] <= e21
        handshake |= row[2] <= max(e9, pdh)
        if trigger_mode=='hourly_pullback':
            hour_touch |= bool(np.any(row[2]<=hourly[b]))
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
        earlier = (watch or base) and bounce and (trigger_mode=='previous_bar' or
                   (trigger_mode=='hourly_pullback' and hour_touch and bool(np.any(fill>hourly[b]))))
        opening_range = trigger_mode=='opening_range' and (watch or base) and fill>bars[first,1]
        if not (w or ep or leader or earlier or opening_range):
            continue
        stop = entry_stop(bars,b,lod,cap,floor,stop_mode)
        if stop is None:
            continue
        if trace is not None:
            trace.append('+'.join(label for label,ok in zip(('watch','ep','leader','earlier','opening_range'),
                                                           (w,ep,leader,earlier,opening_range)) if ok))
        return b, float(fill), float(stop)
    return None


def reentry_day(bars, flags, levels, cap, floor, b_start, trigger_mode=None, hourly=None, stop_mode=None, trace=None,
                reentry_mode=None):
    """After a failed price setup, require a new completed three-bar range before another entry."""
    if reentry_mode not in (None,'setup','opening_range'):
        raise ValueError('unknown reentry mode: '+str(reentry_mode))
    first=trigger_day(bars,flags,levels,cap,floor,b_start,trigger_mode,hourly,stop_mode,trace)
    if first is None:
        return []
    hits=[first]
    opening_high=bars[np.flatnonzero(np.isfinite(bars[:,:4]).all(1))[0],1]
    last_entry,_,stop=first
    failed=None
    lod=float(np.nanmin(bars[:last_entry+1,2]))
    for b in range(last_entry+1,len(bars)):
        row=bars[b]
        if not np.isfinite(row[:4]).all():
            continue
        lod=min(lod,float(row[2]))
        if failed is None:
            if row[2]<=stop:
                failed=b
            continue
        if b<failed+4:
            continue
        prior=bars[b-3:b,:4]
        if not np.isfinite(prior).all():
            continue
        high,low=float(prior[:,1].max()),float(prior[:,2].min())
        if high<=0 or (high-low)/high>cap or row[3]<=high:
            continue
        if reentry_mode=='opening_range' and row[3]<=opening_high:
            continue
        if reentry_mode=='setup' and trigger_day(bars[:b+1],flags,levels,cap,floor,b,
                                                 trigger_mode,hourly,stop_mode) is None:
            continue
        fill=float(row[3])
        # Preserve the original float64 reentry arithmetic; first entries retain their source dtype.
        new_stop=min(max(lod,fill*(1-cap)),fill*(1-floor)) if stop_mode is None else \
            entry_stop(bars,b,lod,cap,floor,stop_mode)
        if new_stop is None:
            continue
        stop=new_stop
        hits.append((b,fill,float(stop)))
        if trace is not None:
            trace.append('reentry')
        failed=None
    return hits


def minute_indicators(daily_ema, daily_close):
    """Daily risk scales are already lagged; price indicators become known at the session close."""
    out = {}
    for key, arr in daily_ema.items():
        if arr.ndim == 1:
            out[key] = np.repeat(arr, 78)
        else:
            prev = np.full_like(arr, np.nan)
            prev[1:] = arr[:-1]
            out[key] = np.repeat(prev, 78, axis=0).astype(np.float32)
            rows = np.flatnonzero(daily_close)
            out[key][rows] = arr[rows // 78]
    return out


def first_break(bars, cap, floor):
    """The ledger supplies the date, never the future low or a later winning attempt."""
    lod = math.inf
    for b, row in enumerate(bars):
        if not np.isfinite(row[:4]).all():
            continue
        lod = min(lod, row[2])
        if b and np.isfinite(bars[b-1,:4]).all() and row[3] > bars[b-1,1]:
            fill = float(row[3])
            return b, fill, min(max(lod, fill*(1-cap)), fill*(1-floor))
    return None


def ledger_mask(A):
    mask = np.zeros_like(A['close'], bool)
    for t,j,_,_ in R.located_longs(A,R.L.load(R.LEDGER)):
        if t.dated:
            d = int(np.searchsorted(A['days'],t.entry_date))
            if d<len(A['days']) and str(A['days'][d])==t.entry_date:
                mask[d,j] = True
    return mask


def ledger_pairs(A, located, trades):
    records=[]
    by_code={}
    for x in trades:
        if x['side']>0:
            by_code.setdefault(x['code'],[]).append(x)
    def serialize(xs):
        return [dict({k:v for k,v in x.items() if k!='executions'},order_events=x.get('executions',[])) for x in xs]
    for segment, rows in located.items():
        for t,j,a,b in rows:
            ours=by_code.get(str(A['codes'][j]),[])
            days={str(d) for d in A['days'][a:b+1]}
            hits=[x for x in ours if x['entry']==t.entry_date]
            records.append(dict(id=t.id,segment=segment,code=str(A['codes'][j]),date=t.entry_date,precision=t.precision,
                                his_outcome=t.outcome,his_r=t.r_multiple,
                                window_lo=str(A['days'][a]),window_hi=str(A['days'][b]),
                                executions=serialize(hits),window_executions=serialize([x for x in ours if x['entry'] in days]),
                                carried_this_date=[dict(entry=x['entry'],exit=x['exit']) for x in ours
                                                   if x['entry']<t.entry_date<=x['exit']]))
    return records


def weekly_reclaim_watch(A,pool,watch,scanned):
    """Add already-scanned names above the previous day's running-week EMA9."""
    above=R.prev(A['close']>R.weekly_ema(A['close'],A['days'],9))
    return watch | (pool & scanned & above)


def prepare(spec, cfg, rehab=None, coverage_name='r77_coverage.json', origins=None):
    full = R.us_arrays()
    full_entries, rules, mask, pool = R.build_system(full, cfg)
    _, w, _ = R.system_signals(full, cfg)
    watch_modes={opts.get('watch_mode') for opts in spec['candidates'].values()}
    if not watch_modes<={None,'weekly_reclaim'}:
        raise ValueError('unknown minute watch mode')
    recovery=weekly_reclaim_watch(full,pool,w,R.strength_lists(full,pool)['K9']) \
        if 'weekly_reclaim' in watch_modes else None
    day_ok = R.market_ok(full, pool, w, cfg['filter'])
    market_masks={cfg['filter']:day_ok}
    for opts in spec['candidates'].values():
        gate=opts.get('market_filter',cfg['filter'])
        if gate not in market_masks:
            market_masks[gate]=R.market_ok(full,pool,w,gate)
    full_px, ema = M.context(full, pool, rules)
    baseline = None
    if spec.get('ledger_diagnostic') or spec.get('verify_global_baseline'):
        parts=R.L.split(R.L.load(R.LEDGER),R.CUTOFF)
        loc={k:[x for x in R.located_longs(full,part) if x[0].dated]
             for k,part in zip(('select','validate'),parts)}
        baseline=M.summarize(full,full_px,ema,rules,full_entries,loc)[0]
        expected=carried_scoreboard(spec['base'][0])
        assert np.isclose(baseline['total'],expected['total'],rtol=0,atol=1e-10)
        assert baseline['behavior']==expected['behavior']
        assert baseline['bought']==expected['bought']
        assert baseline['bought_entry_date']==expected['bought_entry_date']
        assert all(np.isclose(v,expected['by_year'][k],rtol=0,atol=1e-10) for k,v in baseline['by_year'].items())
        print('Full carry reproduced before minute diagnostic',flush=True)
    del full_entries,full_px
    picked = set(spec['sources']) if 'sources' in spec else set(json.loads(Path(spec['sample']).read_text())['picked'])
    cols = np.array([j for j, code in enumerate(full['codes']) if str(code) in picked])
    first = int(np.searchsorted(full['days'], '2023-06-01'))
    last_day = int(np.searchsorted(full['days'],spec.get('end',R.FULL[1]),side='right'))
    A = {k: v[first:last_day, cols].copy() for k, v in full.items()
         if isinstance(v, np.ndarray) and v.ndim == 2 and v.shape == full['close'].shape}
    A.update(days=full['days'][first:last_day], codes=full['codes'][cols], market='us')
    daily_ema = {k: v[first:last_day, cols].copy() if v.ndim == 2 else v[first:last_day].copy() for k, v in ema.items()}
    mask, pool, w = (x[first:last_day, cols].copy() for x in (mask, pool, w))
    if recovery is not None:
        recovery=recovery[first:last_day,cols].copy()
    day_ok = day_ok[first:last_day]
    market_masks={k:v[first:last_day] for k,v in market_masks.items()}
    variant_market={name:market_masks[opts.get('market_filter',cfg['filter'])]
                    for name,opts in spec['candidates'].items()}
    # Compute history-dependent eligibility before discarding the broad panel and its warmup.
    btop = R.S._past_any((full['pr126'] >= 1 - cfg['bpath']) & full['rank_pool'], cfg['bopts']['lookback'])
    bup = R.prev(R.weekly_ema(full['close'], full['days'], 9) > R.weekly_ema(full['close'], full['days'], 21))
    near = R.prev((np.abs(full['close'] / full['e9'] - 1) <= .03) |
                  (np.abs(full['close'] / full['e21'] - 1) <= .03))
    base = (btop & bup & near)[first:last_day, cols].copy() & pool
    del full, ema, btop, bup, near
    gc.collect()
    nday, nstock = A['close'].shape
    nbar = nday * 78
    cache = R.I.luk.CACHE / spec.get('cache', 'r92' if spec.get('ledger_diagnostic') else 'r77')
    cache.mkdir(exist_ok=True)
    keys=('open','high','low','close','mark')
    memory=os.environ.get('LUK_MINUTE_MEMORY')=='1'
    if memory:
        # Explicit recovery from cache-device write failure; bounded well below this VPS's RAM.
        if nbar*nstock*4*len(keys)>512*1024**2:
            raise ValueError('minute in-memory price arrays exceed 512 MiB limit')
        px={k:np.empty((nbar,nstock),dtype=np.float32) for k in keys}
    else:
        px={k:np.lib.format.open_memmap(cache/f'{k}.npy',mode='w+',dtype='float32',shape=(nbar,nstock))
            for k in keys}
    for arr in px.values():
        arr[:] = np.nan
    times = [f'{(575 + b * 5) // 60:02d}:{(575 + b * 5) % 60:02d}' for b in range(78)]
    px.update(dates=np.array([str(day) + ' ' + tm for day in A['days'] for tm in times]),
              codes=A['codes'], session=np.repeat(np.arange(nday), 78))
    streams = {k: [[] for _ in range(nbar)] for k in ('CLOSE', *spec['candidates'])}
    if origins is not None:
        origins.update({name:{} for name in streams})
    his = ledger_mask(A) if spec.get('ledger_diagnostic') else None
    diagnose = ledger_mask(A) if spec.get('ledger_funnel') else None
    funnel=[]
    if his is not None:
        streams.update({k:[[] for _ in range(nbar)] for k in ('HIS_CLOSE','HIS_M0')})
    cover, anomalies = [], []
    week = weekly_levels(A)
    last_bar = np.full(nday, -1)
    di = {str(day): d for d, day in enumerate(A['days'])}
    actions = panel.read_actions(R.I.R8_DAILY/'actions.csv.gz')
    for j, code in enumerate(A['codes']):
        source=spec.get('sources',{}).get(str(code))
        path = Path(source['path']) if source else R.I.R8_DIR / f'{str(code)[3:]}.csv.gz'
        if source:
            with path.open('rb') as fh:
                assert hashlib.file_digest(fh,'sha256').hexdigest()==source['sha256'],path
        raw = np.full((6, 1, nday, 78), np.nan, np.float32)
        R.I._k5_into(raw, 0, path, di)
        bars = raw[:, 0].transpose(1, 2, 0)
        quality = normalize_bars(bars,A['days'],A['raw'][:,j],actions.get(str(code),[]),
                                 rehab.get(str(code),[]) if rehab is not None else None,
                                 source_asof=source['source_asof'] if source else None,
                                 target_factor=A['close'][:,j]/A['raw'][:,j] if source else None)
        hour=hourly_support(bars) if any(x.get('trigger_mode')=='hourly_pullback'
                                       for x in spec['candidates'].values()) else None
        valid = np.isfinite(bars[:, :, :4]).all(2)
        last = np.max(np.where(valid,np.arange(78),-1),axis=1)
        last_bar = np.maximum(last_bar, np.max(np.where(valid, np.arange(78), -1), axis=1))
        for z, key in enumerate(('open', 'high', 'low', 'close')):
            px[key][:, j] = bars[:, :, z].reshape(-1)
        observed = px['close'][:, j]
        known = np.maximum.accumulate(np.where(np.isfinite(observed), np.arange(nbar), 0))
        px['mark'][:, j] = observed[known]
        relevant = (A['days'] >= R.FULL[0]) & (A['days'] <= R.FULL[1])
        cover.append(dict(code=str(code), file=str(path.resolve().relative_to(R.I.luk.ROOT)),
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
            if d == 0:
                continue
            priority = -A['to20'][d - 1, j]
            cap = min(.05, .5 * A['adr'][d - 1, j] / 100)
            if his is not None and his[d,j]:
                if b in (41,77):
                    fill=float(bars[d,b,3])
                    stop=min(max(np.nanmin(bars[d,:,2]),fill*(1-cap)),fill*(1-cfg['stop_min']))
                    streams['HIS_CLOSE'][d*78+b].append((priority,j,1,fill,float(stop),'ledger_close'))
                hit=first_break(bars[d],cap,cfg['stop_min'])
                if hit:
                    hb,fill,stop=hit
                    streams['HIS_M0'][d*78+hb].append((priority,j,1,fill,stop,'ledger_first_break'))
            if day_ok[d] and mask[d, j] and b in (41, 77):
                fill = bars[d, b, 3]
                stop = min(max(np.nanmin(bars[d, :, 2]), fill * (1-cap)), fill * (1-cfg['stop_min']))
                streams['CLOSE'][d * 78 + b].append((priority,j,1,float(fill),float(stop),'close'))
                if origins is not None:
                    origins['CLOSE'][d*78+b,j]='close'
            flags = (w[d,j], A['tight'][d-1,j], abs(A['close'][d-1,j]/A['e9'][d-1,j]-1)<=.03,
                     A['e9'][d-1,j]>A['e21'][d-1,j], base[d,j], pool[d,j])
            levels = (A['high'][d-1,j], A['close'][d-1,j], A['e9'][d-1,j], A['e21'][d-1,j], week[d,j],
                      max(.05,A['adr'][d-1,j]/100), 2*A['to20'][d-1,j])
            diagnosis=None
            if diagnose is not None and diagnose[d,j]:
                opening=float(bars[d,np.flatnonzero(valid[d])[0],0])
                diagnosis=dict(code=str(code),day=str(A['days'][d]),market_ok=bool(day_ok[d]),
                               market_ok_by_variant={name:bool(gate[d]) for name,gate in variant_market.items()},
                               watch_by_variant={name:bool(recovery[d,j] if opts.get('watch_mode') else w[d,j])
                                                 for name,opts in spec['candidates'].items()},
                               pool=bool(pool[d,j]),watch=bool(w[d,j]),leader=bool(base[d,j]),
                               gap=bool(opening>=levels[1]*(1+levels[5])),daily_signal=bool(mask[d,j]),
                               raw_price_triggers={})
                funnel.append(diagnosis)
            if not any(gate[d] for gate in variant_market.values()) and diagnosis is None:
                continue
            hit_cache={};trace_cache={}
            for name, opts in spec['candidates'].items():
                key=(bool(opts.get('reentry')),opts['bar_start'],opts.get('trigger_mode'),opts.get('stop_mode'),
                     opts.get('reentry_mode'),opts.get('watch_mode'))
                if key not in hit_cache:
                    trace_cache[key]=[]
                    variant_flags=(recovery[d,j],*flags[1:]) if opts.get('watch_mode') else flags
                    extra=dict(trigger_mode=opts.get('trigger_mode'),hourly=hour[d] if hour is not None else None,
                               stop_mode=opts.get('stop_mode'),trace=trace_cache[key] if origins is not None else None)
                    if opts.get('reentry'):
                        hit_cache[key]=reentry_day(bars[d],variant_flags,levels,cap,cfg['stop_min'],opts['bar_start'],
                                                  reentry_mode=opts.get('reentry_mode'),**extra)
                    else:
                        hit=trigger_day(bars[d],variant_flags,levels,cap,cfg['stop_min'],opts['bar_start'],**extra)
                        hit_cache[key]=[hit] if hit else []
                hits=hit_cache[key]
                if diagnosis is not None:
                    diagnosis['raw_price_triggers'][name]=[
                        dict(time=str(px['dates'][d*78+hb]),fill=fill,stop=stop) for hb,fill,stop in hits]
                for hit_number,(b,fill,stop) in enumerate(hits if variant_market[name][d] else []):
                    pr=minute_priority(bars[d],b,levels[1],A['to20'][d-1,j],opts.get('priority'))
                    kind=minute_kind(name,opts,A['to20'][d-1,j])
                    streams[name][d*78+b].append((pr,j,1,fill,stop,kind))
                    if origins is not None:
                        origins[name][d*78+b,j]=trace_cache[key][hit_number]
        if (j+1)%20==0:
            print('R77 prepared',j+1,'/',nstock,flush=True)
    # Data anomalies are explicit: never convert a complete-day consistency check into a trading feature.
    coverage=dict(stocks=cover, price_anomalies=anomalies,ledger_funnel=funnel,
                  storage='memory_512MiB_limit' if memory else 'memmap',
                  empty_sessions=[str(A['days'][d]) for d in np.flatnonzero(last_bar<0) if A['days'][d]>=R.FULL[0]])
    if baseline is not None:
        coverage['full_carry_reproduction']=baseline
    (R.I.OUT/coverage_name).write_text(json.dumps(coverage,indent=1))
    diagnostic = spec.get('data_policy') == 'provider_conditional_diagnostic'
    if diagnostic and spec.get('carry') != 'unchanged_full_market_requires_separate_validation':
        raise ValueError('conditional provider prices cannot qualify for global carry')
    if anomalies and not diagnostic:
        raise ValueError(f'{len(anomalies)} minute/daily price anomalies; inspect {coverage_name} before evaluation')
    px['daily_close']=np.zeros(nbar,bool)
    px['daily_close'][np.arange(nday)*78+np.where(last_bar>=0,last_bar,77)]=True
    streams['CLOSE']=[entries if px['daily_close'][row] else [] for row,entries in enumerate(streams['CLOSE'])]
    if his is not None:
        streams['HIS_CLOSE']=[entries if px['daily_close'][row] else [] for row,entries in enumerate(streams['HIS_CLOSE'])]
    coverage['signal_counts']={}
    for name, stream in streams.items():
        limit = spec['candidates'].get(name, {}).get('max_new', cfg['max_new'])
        streams[name] = cap_signal_stream(stream, limit)
        coverage['signal_counts'][name]={year:dict(
            raw=sum(len(es) for row,es in enumerate(stream) if str(A['days'][row//78]).startswith(year)),
            retained=sum(len(es) for row,es in enumerate(streams[name]) if str(A['days'][row//78]).startswith(year)))
            for year in ('2024','2025','2026')}
    ci={str(c):j for j,c in enumerate(A['codes'])}
    for row in funnel:
        d=di[row['day']];j=ci[row['code']]
        row['retained']={name:[str(px['dates'][i]) for i in range(d*78,(d+1)*78)
                               for e in stream[i] if e[1]==j] for name,stream in streams.items()}
    (R.I.OUT/coverage_name).write_text(json.dumps(coverage,indent=1))
    minute_ema=minute_indicators(daily_ema,px['daily_close'])
    minute_pool=np.repeat(pool,78,axis=0)
    daily_entries=R.entries_close_stop(A,mask & day_ok[:,None],cfg['stop'],stop_min=cfg['stop_min'])
    daily_entries=cap_signal_stream(daily_entries,cfg['max_new'],bars_per_session=1)
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


def replayed_placebo(st, reference, draws, seed):
    """Reuse a frozen random result only for an exactly reproduced measurement account."""
    for metric in ('total','by_year','2026_jan_jul','behavior','bought','bought_entry_date','march_start'):
        assert st[metric]==reference[metric],('replay',metric)
    assert reference['placebo']['draws']==draws and reference['placebo']['seed']==seed
    return dict(reference['placebo'])


def evaluate(A,px,ema,rules,entries,pool,located,draws,seed,coverage=None,record_ledger=False,stop_policy=None,
             origins=None,replay_reference=None,coverage_accounting='stock_day'):
    attempts={(str(A['codes'][j]),t.entry_date):[] for rows in located.values() for t,j,_,_ in rows} \
        if coverage and coverage.get('ledger_funnel') else None
    if attempts is not None and origins is not None:
        for rows in located.values():
            for _,j,a,b in rows:
                for day in A['days'][a:b+1]:
                    attempts.setdefault((str(A['codes'][j]),str(day)),[])
    def one(start=R.FULL[0],rng=None,audit=False):
        curve,dates,tr=R.Y.simulate(px,ema,rules,entries,start,R.FULL[1]+' 23:59',placebo=rng,pool=pool,audit=audit,
                                   entry_audit=attempts if audit else None)
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
    if origins is not None:
        ci={str(c):j for j,c in enumerate(px['codes'])}
        groups={};seen=set();timeline=[]
        for t in sorted(tr,key=lambda t:t['entry_time']):
            i=int(np.searchsorted(px['dates'],t['entry_time']));j=ci[t['code']]
            t['entry_origin']=origins[i,j]
            key=t['entry'][:4],t['entry_origin']
            groups.setdefault(key,[]).append(t)
            stock_day=t['code'],t['entry']
            timeline.append(dict(code=t['code'],entry=t['entry_time'],exit=t['exit_time'],
                                 origin=t['entry_origin'],actual_same_day_repeat=stock_day in seen,
                                 ret=t['ret'],pnl=t['pnl'],why=t['why'],fill=t['fill'],stop=t['stop']))
            seen.add(stock_day)
        st['entry_timeline']=timeline
        st['behavior_by_origin']={year:{origin:M.behavior(ts) for (y,origin),ts in groups.items() if y==year}
                                  for year in sorted({y for y,_ in groups})}
    if stop_policy is not None:
        groups={};ci={str(c):j for j,c in enumerate(px['codes'])};floor=stop_policy['floor']
        for t in tr:
            i=int(np.searchsorted(px['dates'],t['entry_time']));j=ci[t['code']];d=i//78
            lod=float(np.nanmin(px['low'][d*78:i+1,j]));fill=t['fill']
            bars=np.array([px[k][max(d*78,i-1):i+1,j] for k in ('open','high','low','close')]).T
            cap=min(.05,.5*A['adr'][d-1,j]/100)
            if stop_policy['mode'] is not None:
                expected=entry_stop(bars,len(bars)-1,lod,cap,floor,stop_policy['mode'])
                assert expected is not None and np.isclose(t['stop'],expected,rtol=0,atol=1e-9)
                assert floor-1e-10<=t['risk_pct']<=min(.03,cap)+1e-10
            lows=[float(row[2]) for row in bars if np.isfinite(row[:4]).all() and 0<row[2]<fill]
            source='lod' if np.isclose(t['stop'],min(lod,fill*(1-floor)),rtol=1e-7) else \
                ('bar' if lows and np.isclose(t['stop'],min(max(lows),fill*(1-floor)),rtol=1e-7) else 'capped_or_other')
            t['entry_geometry']=dict(lod=lod,lod_rise=fill/lod-1,source=source,
                                     previous_low=float(bars[-2,2]) if len(bars)>1 else None,
                                     current_low=float(bars[-1,2]))
            groups.setdefault(t['entry'][:4],[]).append(t)
        st['stop_geometry_by_year']={year:dict(n=len(ts),
            source_counts={src:sum(t['entry_geometry']['source']==src for t in ts) for src in ('lod','bar','capped_or_other')},
            mean_risk_pct=float(np.mean([t['risk_pct'] for t in ts])),max_risk_pct=max(t['risk_pct'] for t in ts),
            lod_rise_over_3pct=sum(t['entry_geometry']['lod_rise']>.03+1e-12 for t in ts)) for year,ts in groups.items()}
    if rules.management_by_kind:
        st['behavior_by_entry_kind']={kind:M.behavior([t for t in tr if t['kind']==kind])
                                     for kind in sorted({t['kind'] for t in tr})}
    if record_ledger:
        st['ledger_pairs']=ledger_pairs(A,located,tr)
        if attempts is not None:
            for row in st['ledger_pairs']:
                row['entry_attempts']=attempts[(row['code'],row['date'])]
                if origins is not None:
                    row['window_entry_attempts']=[event for (code,day),events in attempts.items()
                        if code==row['code'] and row['window_lo']<=day<=row['window_hi'] for event in events]
        by_day={}
        for t in sorted(tr,key=lambda t:t['entry_time']):
            by_day.setdefault((t['code'],t['entry']),[]).append(t)
        repeats=[ts for ts in by_day.values() if len(ts)>1]
        st['same_day_reentries']=dict(stock_days=len(repeats),extra_entries=sum(len(ts)-1 for ts in repeats),
            prior_exit_reasons={reason:sum(t['why']==reason for ts in repeats for t in ts[:-1])
                                for reason in sorted({t['why'] for ts in repeats for t in ts[:-1]})},
            trades=[dict(code=t['code'],entry=t['entry_time'],exit=t['exit_time'],why=t['why'],pnl=t['pnl'])
                    for ts in repeats for t in ts])
        st['largest_loss_price_audit']=audit_prices(px,sorted([t for t in tr if t['ret']<=0],key=lambda t:t['pnl'])[:15])
        sizes=[int(np.sum(pool[d] & np.isfinite(px['close'][d]))) for d,es in enumerate(entries)
               if es and str(px['dates'][d])>=R.FULL[0]]
        st['random_pool_sizes_at_signal']=dict(min=min(sizes,default=0),median=float(np.median(sizes)) if sizes else 0,
                                              empty=sum(n==0 for n in sizes),signals=len(sizes))
    if coverage is not None:
        exposures=[]
        for t in tr:
            days=[a['day'] for a in coverage['price_anomalies']
                  if a['code']==t['code'] and t['entry']<=a['day']<=t['exit']]
            if days:
                exposures.append(dict(code=t['code'],entry=t['entry'],exit=t['exit'],days=days,
                                      execution_events=[e for e in t['executions'] if e['time'][:10] in days]))
        st['price_anomaly_exposures']=exposures
    st['bought']={k:[R.bought(A,tr,ls),len(ls)] for k,ls in located.items()}
    actual={(t['code'],t['entry']) for t in tr}
    st['bought_entry_date']={k:[sum((str(A['codes'][j]),t.entry_date) in actual for t,j,_,_ in ls),len(ls)]
                             for k,ls in located.items()}
    if record_ledger:
        for segment in located:
            pairs=[p for p in st['ledger_pairs'] if p['segment']==segment]
            assert sum(bool(p['window_executions']) for p in pairs)==st['bought'][segment][0]
            assert sum(bool(p['executions']) for p in pairs)==st['bought_entry_date'][segment][0]
    a=int(np.searchsorted(dates,'2026-01-01'));b=int(np.searchsorted(dates,'2026-07-31',side='right'))-1
    st['2026_jan_jul']=float(curve[b]/curve[a-1]-1)
    st['march_start']=R.Y.stats(*one('2024-03-01'))['by_year']
    if coverage_accounting=='one_to_one':
        st=M.account_attempts(st)
    if replay_reference is not None:
        st['placebo']=replayed_placebo(st,replay_reference,draws,seed)
        st['placebo_reused_after_exact_replay']=True
        return st,audit
    rng=np.random.default_rng(seed)
    random=[]
    for n in range(draws):
        random.append(float(one(rng=rng)[0][-1]-1))
        if (n+1)%5==0: print('R77 placebo',n+1,'/',draws,flush=True)
    st['placebo']=dict(real=st['total'],median=float(np.median(random)),p90=float(np.percentile(random,90)),
                       rank=float(np.mean(np.array(random)<st['total'])),draws=draws,seed=seed)
    return st,audit


def run(round_name='R77'):
    path=R.ROUNDS/f'{round_name}.json';spec=json.loads(path.read_text());cfg=R.system_config_after(spec['base'][0])
    prior_report=json.loads((R.I.OUT/spec.get('reproduction_reference',spec['base'][0])).read_text()) \
        if spec.get('ledger_funnel') else {}
    accounting=spec.get('coverage_accounting','stock_day')
    if accounting not in ('stock_day','one_to_one'):
        raise ValueError('unknown coverage accounting')
    if prior_report.get('coverage_accounting')=='one_to_one' and accounting!='one_to_one':
        raise ValueError('a corrected reference requires one-to-one accounting')
    if accounting=='one_to_one' and not (spec.get('record_entry_origins') and
                                         (spec.get('record_ledger') or spec.get('ledger_diagnostic'))):
        raise ValueError('one-to-one accounting needs ledger records and actual entry events')
    replay=None
    if spec.get('replay_reference'):
        assert spec.get('measurement_only')
        frozen=R.I.OUT/spec['replay_reference']
        assert hashlib.sha256(frozen.read_bytes()).hexdigest()==spec['replay_sha256']
        replay=json.loads(frozen.read_text())
    assert len(spec['candidates'])<=5
    for file,expected in (spec.get('data_files',{})|spec.get('source_files',{})).items():
        with Path(file).open('rb') as source:
            assert hashlib.file_digest(source,'sha256').hexdigest()==expected,file
    if 'manifest_sha256' in spec:
        manifest=R.I.OUT/f'{round_name.lower()}_input_manifest.json'
        assert hashlib.sha256(manifest.read_bytes()).hexdigest()==spec['manifest_sha256']
    if 'diagnostic_sha256' in spec:
        diagnostic=R.I.OUT/f'{round_name.lower()}_input_audit.json'
        assert hashlib.sha256(diagnostic.read_bytes()).hexdigest()==spec['diagnostic_sha256']
    origins={} if spec.get('record_entry_origins') else None
    A,px,ema,rules,streams,pool,daily_pool,daily_ema,daily_entries,coverage=prepare(
        spec,cfg,coverage_name=f'{round_name.lower()}_coverage.json',origins=origins)
    ledger=R.L.load(R.LEDGER)
    located={k:[x for x in R.located_longs(A,part) if x[0].dated]
             for k,part in zip(('select','validate'),R.L.split(ledger,R.CUTOFF))}
    dpx={k:A[k] for k in ('open','high','low','close','codes')};dpx['dates']=A['days']
    control,control_trades=M.summarize(A,dpx,daily_ema,rules,daily_entries,located)
    out=dict(chosen=spec['base'][0],chosen_config=cfg,spec_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
             data_policy=spec.get('data_policy','strict'),global_carry_changed=False,
             scope=spec.get('scope','R8_200_local_sample_only'),daily_control=control,sample={},
             price_audit={'DAILY':M.price_audit(A,control_trades)},coverage=coverage)
    if spec.get('ledger_diagnostic'):
        his_entries=R.entries_close_stop(A,ledger_mask(A),cfg['stop'],stop_min=cfg['stop_min'])
        his_entries=cap_signal_stream(his_entries,cfg['max_new'],bars_per_session=1)
        hs,ht=M.summarize(A,dpx,daily_ema,rules,his_entries,located)
        out['his_daily_control']=hs
        out['price_audit']['HIS_DAILY']=M.price_audit(A,ht)
        out['his_daily_control']['ledger_pairs']=ledger_pairs(A,located,ht)
        out['scope']='ledger_24_sources_to_'+spec['end']
    record_ledger=spec.get('record_ledger',False) or spec.get('ledger_diagnostic',False)
    if record_ledger:
        out['daily_control']['ledger_pairs']=ledger_pairs(A,located,control_trades)
        out['eligible_for_carry']=False
        out['global_scoreboard']=carried_scoreboard(spec['base'][0])
        out['ledger_coverage']=[]
        ci={str(c):j for j,c in enumerate(A['codes'])}
        for t in ledger:
            if not (t.side=='long' and t.dated):
                continue
            code='US.'+t.ticker;j=ci.get(code);d=int(np.searchsorted(A['days'],t.entry_date))
            status='no_file' if j is None else 'outside_common_period'
            count=0;last=-1
            if j is not None and d<len(A['days']) and str(A['days'][d])==t.entry_date:
                valid=np.flatnonzero(np.isfinite(px['close'][d*78:(d+1)*78,j]))
                count=len(valid);last=int(valid[-1]) if count else -1
                status='has_traded_bars' if count else 'no_traded_bar'
            out['ledger_coverage'].append(dict(id=t.id,code=code,date=t.entry_date,status=status,
                                               valid_bars=count,last_bar=last))
    for name,entries in streams.items():
        print(round_name,'evaluating',name,flush=True)
        stream_rules=replace(rules,**spec['candidates'].get(name,{}).get('rule_opts',{}))
        st,audit=evaluate(A,px,ema,stream_rules,entries,pool,located,spec['draws'],spec['seed'],coverage,
                          record_ledger=record_ledger,
                          stop_policy=dict(mode=spec['candidates'].get(name,{}).get('stop_mode'),floor=cfg['stop_min'])
                          if spec.get('record_stop_geometry') else None,
                          origins=origins[name] if origins is not None else None,
                          replay_reference=replay['sample'][name] if replay is not None else None,
                          coverage_accounting=accounting)
        if record_ledger:
            for metric in ('bought','bought_entry_date'):
                st[metric+'_full_denominator']={k:[v[0],out['global_scoreboard'][metric][k][1]]
                                               for k,v in st[metric].items()}
        if name in prior_report.get('sample',{}):
            expected=prior_report['sample'][name]
            for metric in ('total','by_year','2026_jan_jul','behavior','bought','bought_entry_date','march_start','placebo'):
                assert st[metric]==expected[metric],(name,metric)
            out.setdefault('sample_reproduced',[]).append(name)
        if spec.get('ledger_funnel'):
            for pair in st['ledger_pairs']:
                pair['funnel']=next((row for row in coverage['ledger_funnel']
                                     if row['code']==pair['code'] and row['day']==pair['date']),None)
        out['sample'][name]=st;out['price_audit'][name]=audit
        print(round_name,'result',name,json.dumps({k:st[k] for k in ('by_year','total','placebo','bought','march_start')},default=float),flush=True)
        (R.I.OUT/f'{round_name.lower()}.partial.json').write_text(json.dumps(out,indent=1,default=float))
    out['coverage_accounting']=accounting
    out['rejected']={}
    if spec.get('measurement_only'):
        out.update(measurement_only=True,sample_passed=[],replay_reference=spec.get('replay_reference'))
        (R.I.OUT/f'{round_name.lower()}.json').write_text(json.dumps(out,indent=1,default=float))
        print(round_name,'measurement saved; all fixed accounts reproduced; no selection',flush=True)
        return
    names=list(spec['candidates'])+(['HIS_M0'] if spec.get('ledger_diagnostic') else [])
    for name in names:
        reference='HIS_CLOSE' if name=='HIS_M0' else spec.get('ref','CLOSE')
        if name==reference:
            continue
        ref=out['sample'][reference]
        st=out['sample'][name];bad=C.failures(st,ref)
        objective=spec.get('objective','2025_log_distance')
        if objective=='sample_2025_log_distance':
            objective='2025_log_distance'
        if not spec.get('ledger_diagnostic') and C.objective(st,objective)<=C.objective(ref,objective):
            bad.append('objective_not_improved')
        out['rejected'][name]=bad
    out['sample_passed']=[k for k,v in out['rejected'].items() if not v]
    (R.I.OUT/f'{round_name.lower()}.json').write_text(json.dumps(out,indent=1,default=float))
    print(round_name,'saved; global carry unchanged; conditional numeric candidates',out['sample_passed'],flush=True)


if __name__=='__main__':
    run(sys.argv[1] if len(sys.argv)>1 else 'R77')
