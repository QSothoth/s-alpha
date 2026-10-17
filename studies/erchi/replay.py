"""Run preregistered real-data E1 event experiment; strict execution remains gated."""
import argparse
import csv
import gzip
import hashlib
import json
import statistics
from collections import defaultdict, Counter
from pathlib import Path
from .rules import Bar, sma, repaired, pullback, buy_gate

VARIANTS = {'A_sma10': (10, True, True), 'B_sma20': (20, True, True),
            'C_no_repair': (10, False, True), 'D_no_pullback': (10, True, False)}

def sha(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for block in iter(lambda: f.read(1048576), b''):
            h.update(block)
    return h.hexdigest()

def rows(path):
    with gzip.open(path, 'rt') as f:
        yield from csv.DictReader(f)

def load(root):
    stems = ['trend-breakout-v1/cn', 'trend-breakout-cn-pit-v1/hist/cn', 'trend-breakout-cn-pit-v1/hist-cnx/cn']
    series = defaultdict(dict)
    actions = defaultdict(set)
    manifest = []
    conflict = set()
    counts = Counter()
    for stem in stems:
        for kind in ('bars_raw', 'actions'):
            p = root / stem / (kind + '.csv.gz')
            manifest.append({'path': str(p), 'sha256': sha(p), 'bytes': p.stat().st_size})
            for r in rows(p):
                if kind == 'actions':
                    if float(r['factor_a']) != 1 or float(r['factor_b']) != 0:
                        actions[r['code']].add(r['ex_date'])
                    continue
                if r['date'] < '2018-01-01':
                    continue
                code, date = r['code'], r['date']
                b = Bar(*(float(r[k]) for k in ('open', 'high', 'low', 'close', 'volume')))
                if not (0 < b.low <= min(b.open, b.close) <= max(b.open, b.close) <= b.high) or b.volume < 0:
                    counts['invalid_rows'] += 1
                    conflict.add((code,date))
                    continue
                old = series[code].get(date)
                if old is not None:
                    counts['duplicate_rows'] += 1
                    if old != b:
                        conflict.add((code,date))
                series[code][date] = b
    for code, date in conflict:
        series[code].pop(date, None)
    ip = root / 'index-cn-daily-v1/bars.csv.gz'
    manifest.append({'path': str(ip), 'sha256': sha(ip), 'bytes': ip.stat().st_size})
    index = {r['date']: float(r['close']) for r in rows(ip) if r['code'] == 'SH.000300' and '2018-01-01' <= r['date'] <= '2026-10-09'}
    dates = sorted(index)
    counts.update({'conflicting_or_invalid_dates_removed': len(conflict), 'symbols': len(series), 'bars': sum(map(len,series.values())), 'market_sessions': len(dates)})
    return series, actions, dates, index, manifest, dict(counts)

def generate_signals(series, actions, dates, index, variant):
    _, need_repair, need_pullback = VARIANTS[variant]
    returns = {dates[i]: index[dates[i]] / index[dates[i-1]] - 1 for i in range(1,len(dates))}
    shocks = [i for i in range(1,len(dates)) if returns[dates[i]] <= -.03]
    owners, seen = {}, set()
    events = []
    # Date-major iteration prevents a later shock assigning an already-owned symbol.
    active = {}
    for t, date in enumerate(dates):
        for s in shocks:
            if t != s+3:
                continue
            eligible = []
            for code, bars in series.items():
                window = [bars.get(dates[j]) for j in range(s-1,s+4)]
                if not all(window) or (need_repair and not repaired(window)):
                    continue
                if any(dates[s-1] <= a <= date for a in actions[code]):
                    continue
                eligible.append((-(window[-1].close/window[0].close-1),code))
            chosen = [c for _,c in sorted(eligible)[:5]]
            active[s] = chosen
        owners = {}
        for s in sorted(active):
            if s+3 <= t <= s+13:
                for c in active[s]:
                    owners.setdefault(c,s)
        for code,s in sorted(owners.items()):
            if not s+4 <= t <= s+13 or (code,s) in seen or t < 19:
                continue
            history = [series[code].get(dates[j]) for j in range(t-19,t+1)]
            if any(b is None for b in history) or any(dates[t-19] <= a <= date for a in actions[code]):
                continue
            if pullback(history, returns.get(date,0), need_pullback):
                seen.add((code,s))
                events.append({'variant':variant, 'code':code, 'shock_date':dates[s], 'signal_date':date, 'signal_index':t,
                               'information_cutoff':date+'T15:00:00+08:00', 'signal_close':history[-1].close,
                               'source_rule_id':'EC-2025-01-09', 'hypothesis_id':'H-EC-01', 'setup_id':f'{dates[s]}:{code}'})
    return events, len(shocks)

def evaluate(events, series, actions, dates, variant):
    ma_n = VARIANTS[variant][0]
    occupied_until = {}
    result, ledger = [], []
    for e0 in sorted(events,key=lambda e:(e['signal_index'],e['code'])):
        e = dict(e0)
        code,t = e['code'],e['signal_index']
        bars = series[code]
        if occupied_until.get(code,-1) >= t+1:
            e.update(status='overlapping_event_suppressed')
            result.append(e)
            continue
        if t+1 >= len(dates):
            e.update(status='no_next_session')
            result.append(e)
            continue
        entry_day = dates[t+1]
        entry = bars.get(entry_day)
        reject = buy_gate(entry,e['signal_close'],e['signal_close'])
        ledger.append(dict(variant=variant, code=code, setup_id=e['setup_id'], source_rule_id=e['source_rule_id'],
            hypothesis_id=e['hypothesis_id'], signal_at=e['information_cutoff'], information_cutoff=e['information_cutoff'],
            order_created_at=e['signal_date']+'T15:00:01+08:00', intended_session=entry_day, side='buy',type='conditional_next_open',
            limit=1.01*e['signal_close'], requested_quantity=0, quantity_reason='strict eligibility gate before sizing',
            filled_quantity=0, filled_at=None, fees=0, inventory_lots=[], status='rejected', rejection_reason=reject))
        if reject != 'unknown_historical_eligibility':
            e.update(status=reject)
            result.append(e)
            continue
        if entry_day in actions[code]:
            e.update(status='corporate_action_entry_censored')
            result.append(e)
            continue
        e.update(entry_date=entry_day, entry_price=entry.open, status='right_censored',
                 entry_ex_post_zero_volume_or_one_price=(entry.volume <= 0 or entry.high == entry.low))
        pending = False
        for j in range(t+1,len(dates)):
            d=dates[j]
            if d in actions[code]:
                e.update(status='corporate_action_censored', censor_date=d)
                occupied_until[code]=j
                break
            b=bars.get(d)
            # Event exit uses next available open after completed close; unobserved sellability retained as E1 caveat.
            if pending and b is not None:
                prev=bars.get(dates[j-1])
                if prev is not None and b.open/prev.close <= .955:
                    continue
                e.update(status='completed',exit_date=d,exit_price=b.open,gross_price_markout=b.open/entry.open-1,
                         holding_market_sessions=j-(t+1), exit_information_cutoff=exit_signal+'T15:00:00+08:00',
                         exit_ex_post_zero_volume_or_one_price=(b.volume <= 0 or b.high == b.low))
                occupied_until[code]=j
                break
            if b is None:
                continue
            history=[bars.get(dates[k]) for k in range(max(0,j-ma_n+1),j+1)]
            ma=sma(history,ma_n)
            if (ma and b.close < ma) or j-(t+1)+1 >= 20:
                if not pending:
                    exit_signal=d
                pending=True
        else:
            occupied_until[code]=len(dates)
        result.append(e)
    return result,ledger

def summarize(events):
    out={}
    for block,lo,hi in [('description','2018','2023'),('heldout_once','2023','2027'),('all','2018','2027')]:
        selected=[e for e in events if lo <= e['signal_date'] < hi]
        values=[e['gross_price_markout'] for e in selected if e['status']=='completed']
        out[block]={'signals':len(selected),'statuses':dict(Counter(e['status'] for e in selected)),
                    'completed':len(values), 'mean_gross_event_return':statistics.mean(values) if values else None,
                    'median_gross_event_return':statistics.median(values) if values else None,
                    'positive_fraction':sum(x>0 for x in values)/len(values) if values else None,
                    'roundtrip_breakeven_bps':statistics.mean(values)*10000 if values else None,
                    'worst_event':min(values) if values else None, 'best_event':max(values) if values else None}
    return out

def main():
    p=argparse.ArgumentParser();p.add_argument('--data-root',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    a.output.mkdir(parents=True,exist_ok=True)
    series,actions,dates,index,manifest,audit=load(a.data_root)
    summary={}; all_events=[]; all_orders=[]
    for v in VARIANTS:
        signals,n=generate_signals(series,actions,dates,index,v)
        events,ledger=evaluate(signals,series,actions,dates,v)
        summary[v]=summarize(events);all_events.extend(events);all_orders.extend(ledger)
    audit.update(start=dates[0],end=dates[-1],shock_count=n,readiness='E1',historical_st_and_limits=False,
        clean_point_in_time_universe=False,actual_fills=0,strict_initial_cash=1000000,strict_final_cash=1000000,
        strict_inventory=0,strict_equity=1000000,strict_net_performance_claim=False)
    for name,obj in [('summary.json',summary),('data_audit.json',audit),('input_manifest.json',manifest)]:
        (a.output/name).write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n')
    for name,objects in [('events.jsonl',all_events),('orders.jsonl',all_orders)]:
        with (a.output/name).open('w') as f:
            for obj in objects:f.write(json.dumps(obj,ensure_ascii=False,sort_keys=True)+'\n')
    here=Path(__file__).parent
    files=sorted(here.glob('*.py'))+[here/'notes/PREREGISTRATION.md']
    (a.output/'source_hashes.json').write_text(json.dumps({str(x.relative_to(here)):sha(x) for x in files},indent=2)+'\n')
    print(json.dumps({'audit':audit,'summary':summary},ensure_ascii=False,indent=2))

if __name__=='__main__':main()
