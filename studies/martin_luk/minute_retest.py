"""Five-minute execution diagnostics: strict R77 inputs or provider-conditional R91 inputs."""
import gc
import hashlib
import json
import math
import sys
from pathlib import Path

import numpy as np

from . import continue_round as C, measure as M, replicate as R
from studies.trend_breakout import panel


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
    for segment, rows in located.items():
        for t,j,_,_ in rows:
            hits=[x for x in trades if x['code']==str(A['codes'][j]) and x['entry']==t.entry_date]
            records.append(dict(id=t.id,segment=segment,code=str(A['codes'][j]),date=t.entry_date,precision=t.precision,
                                his_outcome=t.outcome,his_r=t.r_multiple,
                                executions=[dict({k:v for k,v in x.items() if k!='executions'},
                                                 order_events=x.get('executions',[])) for x in hits],
                                carried_this_date=[dict(entry=x['entry'],exit=x['exit']) for x in trades
                                                   if x['code']==str(A['codes'][j]) and x['entry']<t.entry_date<=x['exit']]))
    return records


def prepare(spec, cfg, rehab=None, coverage_name='r77_coverage.json'):
    full = R.us_arrays()
    full_entries, rules, mask, pool = R.build_system(full, cfg)
    _, w, _ = R.system_signals(full, cfg)
    day_ok = R.market_ok(full, pool, w, cfg['filter'])
    full_px, ema = M.context(full, pool, rules)
    baseline = None
    if spec.get('ledger_diagnostic'):
        parts=R.L.split(R.L.load(R.LEDGER),R.CUTOFF)
        loc={k:[x for x in R.located_longs(full,part) if x[0].dated]
             for k,part in zip(('select','validate'),parts)}
        baseline=M.summarize(full,full_px,ema,rules,full_entries,loc)[0]
        expected=json.loads((R.I.OUT/spec['base'][0]).read_text())['global_scoreboard']
        assert np.isclose(baseline['total'],expected['total'],rtol=0,atol=1e-10)
        assert baseline['behavior']==expected['behavior']
        assert baseline['bought']==expected['bought']
        assert baseline['bought_entry_date']==expected['bought_entry_date']
        assert all(np.isclose(v,expected['by_year'][k],rtol=0,atol=1e-10) for k,v in baseline['by_year'].items())
        print('Full carry reproduced before ledger diagnostic',flush=True)
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
    day_ok = day_ok[first:last_day]
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
    cache = R.I.luk.CACHE / ('r92' if spec.get('ledger_diagnostic') else 'r77')
    cache.mkdir(exist_ok=True)
    px = {k: np.lib.format.open_memmap(cache / f'{k}.npy', mode='w+', dtype='float32', shape=(nbar, nstock))
          for k in ('open', 'high', 'low', 'close', 'mark')}
    for arr in px.values():
        arr[:] = np.nan
    times = [f'{(575 + b * 5) // 60:02d}:{(575 + b * 5) % 60:02d}' for b in range(78)]
    px.update(dates=np.array([str(day) + ' ' + tm for day in A['days'] for tm in times]),
              codes=A['codes'], session=np.repeat(np.arange(nday), 78))
    streams = {k: [[] for _ in range(nbar)] for k in ('CLOSE', *spec['candidates'])}
    his = ledger_mask(A) if spec.get('ledger_diagnostic') else None
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
            if not day_ok[d]:
                continue
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
    for stream in streams.values():
        for d in range(nday):
            remaining=cfg['max_new']
            for b in range(78):
                ix=d*78+b
                stream[ix]=sorted(stream[ix],key=lambda e:e[0])[:remaining]
                remaining-=len(stream[ix])
    minute_ema=minute_indicators(daily_ema,px['daily_close'])
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


def evaluate(A,px,ema,rules,entries,pool,located,draws,seed,coverage=None,record_ledger=False):
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
    if record_ledger:
        st['ledger_pairs']=ledger_pairs(A,located,tr)
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


def run(round_name='R77'):
    path=R.ROUNDS/f'{round_name}.json';spec=json.loads(path.read_text());cfg=R.system_config_after(spec['base'][0])
    A,px,ema,rules,streams,pool,daily_pool,daily_ema,daily_entries,coverage=prepare(
        spec,cfg,coverage_name=f'{round_name.lower()}_coverage.json')
    ledger=R.L.load(R.LEDGER)
    located={k:[x for x in R.located_longs(A,part) if x[0].dated]
             for k,part in zip(('select','validate'),R.L.split(ledger,R.CUTOFF))}
    dpx={k:A[k] for k in ('open','high','low','close','codes')};dpx['dates']=A['days']
    control,control_trades=M.summarize(A,dpx,daily_ema,rules,daily_entries,located)
    out=dict(chosen=spec['base'][0],chosen_config=cfg,spec_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
             data_policy=spec.get('data_policy','strict'),global_carry_changed=False,
             scope='R8_200_local_sample_only',daily_control=control,sample={},
             price_audit={'DAILY':M.price_audit(A,control_trades)},coverage=coverage)
    if spec.get('ledger_diagnostic'):
        his_entries=R.entries_close_stop(A,ledger_mask(A),cfg['stop'],stop_min=cfg['stop_min'])
        his_entries=[sorted(es,key=lambda e:e[0])[:cfg['max_new']] for es in his_entries]
        hs,ht=M.summarize(A,dpx,daily_ema,rules,his_entries,located)
        out['his_daily_control']=hs
        out['price_audit']['HIS_DAILY']=M.price_audit(A,ht)
        out['daily_control']['ledger_pairs']=ledger_pairs(A,located,control_trades)
        out['his_daily_control']['ledger_pairs']=ledger_pairs(A,located,ht)
        out['scope']='ledger_24_sources_to_'+spec['end']
        out['eligible_for_carry']=False
        out['global_scoreboard']=json.loads((R.I.OUT/spec['base'][0]).read_text())['global_scoreboard']
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
        st,audit=evaluate(A,px,ema,rules,entries,pool,located,spec['draws'],spec['seed'],coverage,
                          record_ledger=spec.get('ledger_diagnostic',False))
        out['sample'][name]=st;out['price_audit'][name]=audit
        print(round_name,'result',name,json.dumps({k:st[k] for k in ('by_year','total','placebo','bought','march_start')},default=float),flush=True)
        (R.I.OUT/f'{round_name.lower()}.partial.json').write_text(json.dumps(out,indent=1,default=float))
    out['rejected']={}
    names=list(spec['candidates'])+(['HIS_M0'] if spec.get('ledger_diagnostic') else [])
    for name in names:
        ref=out['sample']['HIS_CLOSE' if name=='HIS_M0' else 'CLOSE']
        st=out['sample'][name];bad=C.failures(st,ref)
        if not spec.get('ledger_diagnostic') and C.objective(st,'2025_log_distance')<=C.objective(ref,'2025_log_distance'):
            bad.append('objective_not_improved')
        out['rejected'][name]=bad
    out['sample_passed']=[k for k,v in out['rejected'].items() if not v]
    (R.I.OUT/f'{round_name.lower()}.json').write_text(json.dumps(out,indent=1,default=float))
    print(round_name,'saved; global carry unchanged; conditional numeric candidates',out['sample_passed'],flush=True)


if __name__=='__main__':
    run(sys.argv[1] if len(sys.argv)>1 else 'R77')
