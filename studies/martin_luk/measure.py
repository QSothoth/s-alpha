"""R75 fixed three-layer measurement; stream local minute files one symbol at a time."""
from __future__ import annotations

import csv
import gzip
import hashlib
import json
from collections import Counter, defaultdict
from datetime import date

import numpy as np

from . import replicate as R


def context(A, pool, rules):
    px = {k: A[k] for k in ('open', 'high', 'low', 'close', 'codes')}
    px['dates'] = A['days']
    ema = {k: A[k] for k in ('e9', 'e21', 'e50')}
    for k in (rules.risk_scale, rules.exit_signal, rules.trim_signal, rules.trail_alt_days):
        if k:
            ema[k] = R.named_signal(A, pool, k) if k not in A or k.startswith('idx_') else A[k]
    return px, ema


def behavior(trades):
    out = {}
    for year in ('2024', '2025', '2026', 'all'):
        tr = [t for t in trades if year == 'all' or t['entry'][:4] == year]
        winners = [t for t in tr if t['ret'] > 0]
        losers = [t for t in tr if t['ret'] <= 0]
        mean = lambda vals: float(np.mean(vals)) if vals else None
        net = sum(t['pnl'] for t in tr)
        out[year] = dict(n=len(tr), win=len(winners) / len(tr) if tr else None,
                         avg_win=mean([t['ret'] for t in winners]),
                         avg_loss=mean([t['ret'] for t in losers]),
                         avg_win_invested=mean([t['ret_invested'] for t in winners if 'ret_invested' in t]),
                         avg_loss_invested=mean([t['ret_invested'] for t in losers if 'ret_invested' in t]),
                         days_win=mean([t['days'] for t in winners]),
                         calendar_days_win=mean([(date.fromisoformat(t['exit']) -
                                                  date.fromisoformat(t['entry'])).days for t in winners]),
                         short_net_profit_share=sum(t['pnl'] for t in tr if t['side'] < 0) / net if net > 0 else None)
    return out


def calendar_profit(A, trades, curve, dates, rules):
    """Attribute calendar-year marked-to-market profit by side, including positions carried across years."""
    columns = {str(code): j for j,code in enumerate(A['codes'])}
    out = {}
    for year in sorted({str(day)[:4] for day in dates}):
        start, end = year+'-01-01', year+'-12-31'
        i = int(np.searchsorted(dates,start))
        x = int(np.searchsorted(dates,end,side='right'))-1
        net = float(curve[x]-(curve[i-1] if i else 1.))
        sums = {1:0., -1:0.}
        d0 = int(np.searchsorted(A['days'],start))-1
        d1 = int(np.searchsorted(A['days'],str(dates[x]),side='right'))-1
        for t in trades:
            j, side = columns[t['code']], t['side']
            shares0 = shares1 = cash = 0.
            for event in t.get('executions',[]):
                if event['action']=='end':
                    continue  # terminal marks are not fills in the legacy equity curve
                day = event['time'][:10]
                opening = event['action'] in ('entry','add')
                delta = event['shares'] * (1 if opening else -1)
                if day < start:
                    shares0 += delta
                if day <= end:
                    shares1 += delta
                if start <= day <= end:
                    buy = (side > 0) == opening
                    cash += event['shares'] * event['price'] * (-(1+rules.buy_cost) if buy else 1-rules.sell_cost)
            def marked(d, shares):
                if abs(shares)<1e-12:
                    return 0.
                while d>0 and not np.isfinite(A['close'][d,j]):
                    d-=1
                return side*shares*float(A['close'][d,j])
            sums[side] += cash+marked(d1,shares1)-marked(d0,shares0)
        out[year]=dict(account_profit=net,long_profit=sums[1],short_profit=sums[-1],
                       financing_and_rounding=sums[1]+sums[-1]-net,
                       short_net_profit_share=sums[-1]/net if net>0 else None)
    return out


def summarize(A, px, ema, rules, entries, located, draws=0, pool=None):
    curve, dates, trades = R.Y.simulate(px, ema, rules, entries, *R.FULL, audit=True)
    st = R.Y.stats(curve, dates, trades)
    st['behavior'] = behavior(trades)
    st['profit_by_calendar_year'] = calendar_profit(A,trades,curve,dates,rules)
    st['bought'] = {k: [R.bought(A, trades, ls), len(ls)] for k, ls in located.items()}
    actual = {(t['code'], t['entry']) for t in trades if t['side'] > 0}
    st['bought_entry_date'] = {k: [sum((str(A['codes'][j]), t.entry_date) in actual for t, j, _, _ in ls),
                                  len(ls)] for k, ls in located.items()}
    st['bought_unique_stock_days'] = len(actual & {(str(A['codes'][j]), t.entry_date)
                                                 for ls in located.values() for t, j, _, _ in ls})
    a = int(np.searchsorted(dates, '2026-01-01'))
    b = int(np.searchsorted(dates, '2026-07-31', side='right')) - 1
    st['2026_jan_jul'] = float(curve[b] / curve[a - 1] - 1)
    late = R.Y.simulate(px, ema, rules, entries, '2024-03-01', R.FULL[1])
    st['march_start'] = R.Y.stats(*late)['by_year']
    if draws:
        st['placebo'] = R.Y.placebo_rank(px, ema, rules, entries, *R.FULL, pool, draws=draws, seed=1)
    return st, trades


def complete_trigger(bars, cap, floor=.01):
    """At bar close buy the first close above the previous completed high; future bars only stop it out."""
    for b in range(1, len(bars)):
        fill = bars[b, 3]
        if fill <= bars[b - 1, 1]:
            continue
        lod = float(np.min(bars[:b + 1, 2]))
        stop = min(max(lod, fill * (1 - cap)), fill * (1 - floor))
        day_exit = None
        for row in bars[b + 1:]:
            if row[0] <= stop:
                day_exit = float(row[0])
                break
            if row[2] <= stop:
                day_exit = float(stop)
                break
        return b, float(fill), float(stop), day_exit
    return None


def minute_paths(symbol):
    paths = [R.I.luk.ROOT / 'data' / src / 'k5' / f'{symbol}.csv' for src in R.I.SOURCES]
    paths.append(R.I.R8_DIR / f'{symbol}.csv.gz')
    return [p for p in paths if p.exists()]


def read_days(path, wanted):
    out = defaultdict(dict)
    lo = hi = None
    opener = gzip.open if path.suffix == '.gz' else open
    with opener(path, 'rt', newline='') as fh:
        rows = csv.reader(fh)
        next(rows)
        for timestamp, *values in rows:
            day = timestamp[:10]
            lo, hi = min(lo or day, day), max(hi or day, day)
            if day not in wanted:
                continue
            minute = int(timestamp[11:13]) * 60 + int(timestamp[14:16])
            if 575 <= minute <= 960 and minute % 5 == 0:
                out[day][(minute - 575) // 5] = [float(x) for x in values[:4]]
    return out, [lo, hi]


def independent(px, ema, rules, d, entry):
    """One ledger attempt; no inherited portfolio feedback. Same sizing/exit rules, no other stock exposure."""
    j = entry[1]
    one = {k: v[:, j:j + 1] if k in ('open', 'high', 'low', 'close') else v for k, v in px.items()}
    one['codes'] = px['codes'][j:j + 1]
    em = {k: v[:, j:j + 1] if v.ndim == 2 else v for k, v in ema.items()}
    entries = [[] for _ in px['dates']]
    entries[d] = [(entry[0], 0) + tuple(entry[2:])]
    _, _, trades = R.Y.simulate(one, em, rules, entries, str(px['dates'][d]), R.FULL[1])
    return trades[0] if trades else None


def price_audit(A, trades):
    codes = {str(c): j for j, c in enumerate(A['codes'])}
    rows = []
    for t in sorted(trades, key=lambda t: -t['pnl'])[:15]:
        j = codes[t['code']]
        d = int(np.searchsorted(A['days'], t['entry']))
        x = int(np.searchsorted(A['days'], t['exit']))
        rows.append(dict(trade=t, entry_close=float(A['close'][d, j]),
                         fill_matches_close=bool(np.isclose(t['fill'], A['close'][d, j])),
                         initial_stop_valid=bool(t['stop'] > 0 and (t['stop'] - t['fill']) * t['side'] < 0),
                         exit_ohlc={k: float(A[k][x, j]) for k in ('open', 'high', 'low', 'close')}))
        if 'executions' in t:
            for event in t['executions']:
                d = int(np.searchsorted(A['days'], event['time']))
                price = event['price']
                if event['action'] == 'end' and not np.isfinite(A['close'][d, j]):
                    # End marks use the last observed price, not a fabricated last-day quote.
                    while d > 0 and not np.isfinite(A['close'][d, j]):
                        d -= 1
                assert A['low'][d,j]-1e-5 <= price <= A['high'][d,j]+1e-5, (t['code'],event)
                if event['action'] in ('entry','add','trail','signal','time','no_follow','end'):
                    assert np.isclose(price,A['close'][d,j]), (t['code'],event)
    assert all(x['fill_matches_close'] and x['initial_stop_valid'] for x in rows)
    return rows


def append_short_prices(A, ema, pool, sources):
    """Append local ETF execution columns without changing stock signals or account risk scales."""
    days = {str(day): i for i,day in enumerate(A['days'])}
    codes = [code for code in sources if code not in set(A['codes'])]
    extra = {k: np.full((len(days),len(codes)),np.nan) for k in ('open','high','low','close','turnover')}
    for j,code in enumerate(codes):
        source = sources[code]
        path = R.I.luk.ROOT / source['path']
        assert hashlib.sha256(path.read_bytes()).hexdigest() == source['sha256'], path
        with path.open() as f:
            seen = set()
            for row in csv.DictReader(f):
                day = row.get('date',row.get('time_key',''))[:10]
                if day not in days:
                    continue
                assert day not in seen, (code,day)
                seen.add(day)
                for k in extra:
                    extra[k][days[day],j] = float(row[k])
                lo,hi = float(row['low']),float(row['high'])
                assert 0 < lo <= min(float(row['open']),float(row['close'])) <= max(float(row['open']),float(row['close'])) <= hi
    extra['to20'] = R.luk.rolling_mean(extra['turnover'],20)
    extra['adr'] = R.luk.rolling_mean(extra['high']/extra['low']-1,20)*100
    for n in (9,21,50):
        extra[f'e{n}'] = R.luk.ema(extra['close'],n)
    extra['has'] = np.isfinite(extra['close'])
    out = {k: np.concatenate((A[k],v),axis=1) for k,v in extra.items()}
    out.update(days=A['days'],codes=np.concatenate((A['codes'],np.array(codes))),market=A['market'])
    em = {k: out[k] if k in ('e9','e21','e50') else v for k,v in ema.items()}
    extra_pool = extra['has'] & np.isfinite(extra['adr']) & np.isfinite(extra['to20'])
    return out, em, np.concatenate((pool,extra_pool),axis=1)


def short_layers(name):
    """Diagnostic forced dated short picks, never a candidate for the live carry configuration."""
    path = R.I.OUT / f'{name.lower()}.json'
    spec = json.loads((R.ROUNDS / f'{name}.json').read_text())
    if spec.get('objective') == 'coverage_measurement_only':
        base = json.loads((R.I.OUT/spec['base'][0]).read_text())
        cfg = base['chosen_config']
        out = dict(chosen=spec['ref'],chosen_config=cfg,full={spec['ref']:base['full'][base['chosen']]},
                   configs={'SH9':R.merged(cfg,spec['diagnostic_config'])},
                   spec_sha256=hashlib.sha256((R.ROUNDS/f'{name}.json').read_bytes()).hexdigest())
    else:
        out = json.loads(path.read_text())
    A = R.us_arrays()
    ledger = R.L.load(R.LEDGER)
    shorts = [t for t in ledger if t.side == 'short']
    dated = [t for t in shorts if t.dated]
    located_longs = {k: [x for x in R.located_longs(A, part) if x[0].dated]
                     for k, part in zip(('select','validate'), R.L.split(ledger, R.CUTOFF))}
    own, rules, _, pool = R.build_system(A, out['configs']['SH9'])
    px, ema = context(A, pool, rules)
    if spec.get('extra_short_data'):
        A,ema,pool = append_short_prices(A,ema,pool,spec['extra_short_data'])
        px = {k:A[k] for k in ('open','high','low','close','codes')}
        px['dates'] = A['days']
        out['extra_short_data'] = spec['extra_short_data']
    located, missing = R.F.locate(dated, A['days'], A['codes'], has=A['has'])
    mask = np.zeros_like(A['has'])
    records = []
    for t,j,_,_ in located:
        d = int(np.searchsorted(A['days'], t.entry_date))
        valid = 0 < d < len(A['days']) and str(A['days'][d]) == t.entry_date and bool(A['has'][d,j])
        records.append(dict(id=t.id, code=str(A['codes'][j]), date=t.entry_date,
                            his_outcome=t.outcome, his_r=t.r_multiple, valid_day=valid))
        if valid:
            mask[d,j] = True
    forced_raw = R.entries_short_capped(A, mask)
    forced = [sorted(day,key=lambda e:e[0])[:1] for day in forced_raw]
    lookup = {(str(A['days'][d]), str(A['codes'][e[1]])): (d,e)
              for d,day in enumerate(forced_raw) for e in day}
    cap_keys = {(str(A['days'][d]), str(A['codes'][e[1]])) for d,day in enumerate(forced) for e in day}
    for row in records:
        key = row['date'], row['code']
        row['valid_stop'] = key in lookup
        row['after_daily_cap'] = key in cap_keys
        if key in lookup:
            d,e = lookup[key]
            row['independent'] = independent(px,ema,rules,d,e)
    own_short = [[e for e in day if e[2] < 0] for day in own]
    own_long = [[e for e in day if e[2] > 0] for day in own]
    combined = [longs + [((1,e[0]),)+tuple(e[1:]) for e in sh] for longs,sh in zip(own_long,forced)]
    layers = {}
    for key, entries in (('his_short_picks',forced),('our_short_picks',own_short),
                         ('our_longs_his_shorts',combined)):
        st,trades = summarize(A,px,ema,rules,entries,located_longs,spec['draws'],pool)
        actual = {(t['entry'],t['code']) for t in trades if t['side'] < 0}
        st['dated_short_records_bought'] = sum((r['date'],r['code']) in actual for r in records)
        st['dated_short_unique_days_bought'] = len(actual & set(lookup))
        layers[key] = dict(stats=st,price_audit=price_audit(A,trades),
                           shorts=[t for t in trades if t['side'] < 0])
        print(name,key,st['by_year'],st['behavior']['all'],flush=True)
    out['short_diagnostic'] = dict(ledger_sha256=hashlib.sha256(R.LEDGER.read_bytes()).hexdigest(),
        his_execution=dict(records=len(shorts),dated=len(dated),outcomes=dict(Counter(t.outcome or 'unknown' for t in shorts)),
                           public_profit_share=[.1,.3],account_reconstruction=None),
        missing=missing,records=records,layers=layers)
    path.write_text(json.dumps(out,indent=1,default=float))


def r75():
    spec_path = R.ROUNDS / 'R75.json'
    spec = json.loads(spec_path.read_text())
    cfg = R.system_config_after(spec['base'][0])
    print('R75 loading daily panel', flush=True)
    A = R.us_arrays()
    ledger = R.L.load(R.LEDGER)
    located = {k: [x for x in R.located_longs(A, part) if x[0].dated]
               for k, part in zip(('select', 'validate'), R.L.split(ledger, R.CUTOFF))}
    entries, rules, _, pool = R.build_system(A, cfg)
    px, ema = context(A, pool, rules)
    out = dict(chosen='R74', chosen_config=cfg, spec_sha256=hashlib.sha256(spec_path.read_bytes()).hexdigest(),
               ledger_sha256=hashlib.sha256(R.LEDGER.read_bytes()).hexdigest(), layers={}, coverage=[], pairs=[])
    known = [t for t in ledger if t.r_multiple is not None]
    out['layers']['his_execution'] = dict(n=len(ledger), outcomes=dict(Counter(t.outcome or 'unknown' for t in ledger)),
                                          known_r_n=len(known), known_r_mean=float(np.mean([t.r_multiple for t in known])),
                                          public=R.HIS, public_2026_jul=.0 + 8.686,
                                          account_reconstruction=None)
    out['layers']['our_system'], tr = summarize(A, px, ema, rules, entries, located, spec['draws'], pool)
    out['top_price_audit'] = price_audit(A, tr)
    print('R75 R74 baseline complete', flush=True)
    by_symbol = defaultdict(list)
    for ls in located.values():
        for row in ls:
            by_symbol[row[0].ticker].append(row)
    all_mask = np.zeros_like(A['has'])
    eligible = []
    missing = []
    for ls in located.values():
        for t, j, _, _ in ls:
            d = int(np.searchsorted(A['days'], t.entry_date))
            if d >= len(A['days']) or str(A['days'][d]) != t.entry_date or not A['has'][d, j]:
                missing.append(dict(id=t.id, date=t.entry_date, reason='no_entry_date_daily_bar'))
                continue
            all_mask[d, j] = True
            eligible.append((t, j, d))
    close_entries = R.entries_close_stop(A, all_mask, cfg['stop'], stop_min=cfg['stop_min'])
    close_lookup = {(d, e[1]): e for d, day in enumerate(close_entries) for e in day}
    out['entry_date_missing'] = missing
    out['ledger_missing_daily_panel'] = [t.id for t in ledger if t.side == 'long' and t.dated and
                                        t.id not in {x[0].id for ls in located.values() for x in ls}]
    capped = [sorted(day, key=lambda e: e[0])[:cfg['max_new']] for day in close_entries]
    out['layers']['his_picks_our_execution'], _ = summarize(A, px, ema, rules, capped, located, spec['draws'], pool)
    print('R75 ledger close portfolio complete', flush=True)
    pairs = {t.id: dict(id=t.id, ticker=t.ticker, date=t.entry_date, precision=t.precision,
                       his_outcome=t.outcome, his_r=t.r_multiple,
                       close=independent(px, ema, rules, d, close_lookup[d, j]))
             for t, j, d in eligible if (d, j) in close_lookup}
    for symbol, rows in sorted(by_symbol.items()):
        wanted = set()
        for t, j, _, _ in rows:
            d = int(np.searchsorted(A['days'], t.entry_date))
            wanted.update((t.entry_date, str(A['days'][max(0, d - 1)])))
        sources = [(path, *read_days(path, wanted)) for path in minute_paths(symbol)]
        for t, j, _, _ in rows:
            d = int(np.searchsorted(A['days'], t.entry_date))
            prior = str(A['days'][max(0, d - 1)])
            record = dict(id=t.id, ticker=symbol, date=t.entry_date,
                          files=[dict(path=str(p.relative_to(R.I.luk.ROOT)), span=span,
                                      bars=len(days.get(t.entry_date, {}))) for p, days, span in sources])
            record['status'] = 'no_file' if not sources else 'incomplete_day'
            for path, days, _ in sorted(sources, key=lambda x: -len(x[1].get(t.entry_date, {}))):
                bars = days.get(t.entry_date, {})
                if set(bars) != set(range(78)):
                    continue
                record['status'] = 'missing_previous_close'
                if 77 not in days.get(prior, {}):
                    continue
                if t.id not in pairs:
                    record['status'] = 'missing_daily_entry'
                    continue
                k = A['close'][d - 1, j] / days[prior][77][3]
                arr = np.array([bars[b] for b in range(78)]) * k
                agg = (arr[0, 0], max(arr[:, 1]), min(arr[:, 2]), arr[-1, 3])
                error = max(abs(v / A[key][d, j] - 1) for v, key in zip(agg, ('open', 'high', 'low', 'close')))
                record.update(adjustment=float(k), ohlc_error=float(error))
                if error > .02 or not np.isfinite(arr).all() or np.any(arr <= 0):
                    record['status'] = 'price_mismatch'
                    continue
                record['status'] = 'covered'
                trigger = complete_trigger(arr, min(.05, .5 * A['adr'][d - 1, j] / 100), cfg['stop_min'])
                if trigger:
                    b, fill, stop, day_exit = trigger
                    e = (-A['to20'][d - 1, j], j, 1, fill, stop, 'ledger_5m_close', day_exit)
                    pairs[t.id]['intraday'] = independent(px, ema, rules, d, e)
                    pairs[t.id]['trigger_bar'] = b
                    pairs[t.id]['minute_file'] = str(path.relative_to(R.I.luk.ROOT))
                else:
                    record['status'] = 'no_trigger'
                break
            out['coverage'].append(record)
        print('R75 coverage', symbol, flush=True)
    out['pairs'] = list(pairs.values())
    out['coverage_counts'] = dict(Counter(r['status'] for r in out['coverage']))
    out['pair_stats'] = {name: behavior([p[name] for p in pairs.values() if p.get(name) and
                                       (name == 'close' or p.get('intraday'))]) for name in ('close', 'intraday')}
    out['pair_stats']['matched_close'] = behavior([p['close'] for p in pairs.values() if p.get('intraday')])
    (R.I.OUT / 'r75.json').write_text(json.dumps(out, indent=1, default=float))
    print('R75 saved', out['coverage_counts'], flush=True)


if __name__ == '__main__':
    import sys
    short_layers(sys.argv[1]) if len(sys.argv)>1 else r75()
