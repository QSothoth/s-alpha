"""U1 offline run library and causal daily portraits; no strategy execution."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
from datetime import date
import hashlib
import json
import os
from pathlib import Path
import resource
import shutil
import sys
import time
import zipfile

import numpy as np

from studies.trader_replication import mainleg, standard_indicators as SI
from studies.trader_replication import martin_profile_f2 as F2

ROOT = Path(__file__).resolve().parents[2]
HOME = ROOT / 'studies/martin_luk'
WORK = HOME / 'reports/u1_work'
REPORT = HOME / 'reports/U1_CN.md'
FROZEN = HOME / 'notes/legs_frozen.json'
PANEL = ROOT / 'data/trader-data/cache/_opt_opend-us-options_data_trader-data-v1_us_eb4c87f36b_v2.npz'
EARNINGS = ROOT / 'data/trader-options-v1/us/earnings.csv'
INDUSTRY = ROOT / 'data/trader-screens/cache/industry_us.json'
FIELDS = dict(o='open', h='high', l='low', c='close', v='volume', t='turnover', raw_c='raw_close')
YEARS = ('2024', '2025', '2026')
OFFSETS = tuple(range(-3, 4))
MODEL = ('pctl_dollar_vol20_M', 'pctl_adr20_pct', 'pctl_perf126_pct',
         'support_near_adr', 'long_strength_memory', 'log1p_peer_leaders20_count', 'ep10_recent3')
BASIC = tuple(s['name'] for s in SI.LEGACY_SPEC
              if s['layer'] == 'per_stock' and s['family'] != 'options') + (
    'low252_distance_pct', 'perf126_pct', 'attention20_120', 'gap_pct',
    'support_near_adr', 'ep10_recent3', 'earnings_gap_pct', 'post_earn3', 'earn_ep10_recent3')
PERCENTILES = tuple(n.replace('dollar_vol20_percentile', 'dollar_vol20_M')
                    for n in F2.F.FEATURES if n != 'long_strength_memory')
EXTRA = tuple('pctl_'+n for n in PERCENTILES) + (
    'long_strength_memory', 'pctl_rs21_vs_qqq_pct', 'pctl_rs63_vs_qqq_pct', 'pctl_rs126_vs_qqq_pct',
    'peer_leaders20_count', 'peer_perf21_median_pctl', 'peer_strength_pctl',
    'money_rs21_product', 'money_rs63_product', 'money_rs126_product',
    'attention20_120_pctl', 'remembered_liquid_pullback_pctl', 'log1p_peer_leaders20_count')
T0 = time.monotonic()


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def clean(value):
    if isinstance(value, dict):
        return {str(k): clean(v) for k, v in value.items()}
    if isinstance(value, (tuple, list, np.ndarray)):
        return [clean(v) for v in value]
    if isinstance(value, np.generic):
        return clean(value.item())
    if isinstance(value, float) and not np.isfinite(value):
        return None
    return value


def write(name, value):
    path = WORK / name
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix+'.tmp')
    temporary.write_text(json.dumps(clean(value), ensure_ascii=False, indent=1, allow_nan=False)+'\n', encoding='utf-8')
    temporary.replace(path)


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def log(message):
    print(f'[{time.monotonic()-T0:.0f}s; {resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024:.0f} MiB] {message}', flush=True)


def offline():
    sys.dont_write_bytecode = True

    def audit(event, args):
        if event in ('socket.connect', 'socket.bind', 'socket.getaddrinfo', 'subprocess.Popen', 'os.system'):
            raise PermissionError('U1 is offline and single-process')
        if event == 'open' and not isinstance(args[0], int):
            if args[2] & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND):
                path = Path(os.fsdecode(args[0])).resolve()
                if not path.is_relative_to(WORK.resolve()) and path != REPORT.resolve():
                    raise PermissionError('U1 writes only its artifacts and requested report')
    sys.addaudithook(audit)


def resources():
    group = next(line.split(':', 2)[2] for line in Path('/proc/self/cgroup').read_text().splitlines()
                 if line.startswith('0::'))
    base = Path('/sys/fs/cgroup') / group.lstrip('/')
    status = Path('/proc/self/status').read_text().splitlines()
    return dict(cpu_max=(base/'cpu.max').read_text().strip(),
                memory_max=(base/'memory.max').read_text().strip(),
                memory_peak=(base/'memory.peak').read_text().strip() if (base/'memory.peak').exists() else None,
                threads=int(next(s.split()[1] for s in status if s.startswith('Threads:'))),
                cgroup=group, peak_rss_mib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024,
                elapsed_seconds=time.monotonic()-T0, memory=Path('/proc/meminfo').read_text())


def start(stage):
    path = WORK/(stage+'_started.json')
    if path.exists():
        raise FileExistsError('U1 stage already started: '+stage)
    write(path.name, dict(stage=stage, resources=resources(), protocol_sha256=sha(WORK/'protocol.md')))


def source_paths():
    return [Path(__file__), Path(mainleg.__file__), Path(SI.__file__), Path(F2.__file__),
            Path(F2.F.__file__), WORK/'protocol.md', FROZEN, PANEL, EARNINGS, INDUSTRY,
            ROOT/'data/martin-luk-benchmarks-v1/US.QQQ.csv',
            HOME/'notes/PLAN_U1_CN.md', HOME/'notes/PI_METRIC_BRIEF_20261107_CN.md', HOME/'notes/RULES_CN.md',
            *[HOME/f'reports/{n}_CN.md' for n in ('Y1', 'D1', 'F1', 'F2', 'M1')],
            HOME/'reports/f1_work/cache.json', HOME/'reports/f2_work/cache.json']


def snapshots(paths):
    return {str(p.relative_to(ROOT)): sha(p) for p in paths}


def prepare():
    start('prepare')
    before = snapshots(source_paths())
    write('sources.json', before)
    protected = [ROOT/n for n in ('studies/trader_replication/system.py',
        'studies/trader_replication/systems.py', 'studies/trader_screens/board.py',
        'studies/martin_luk/reports/ie47_profile.json', 'studies/martin_luk/reports/final_system_r74.json')]
    write('protected_before.json', snapshots(protected))
    cache = WORK/'panel'
    cache.mkdir(exist_ok=True)
    # Copy one bounded compressed member at a time; readers use read-only mmap.
    with zipfile.ZipFile(PANEL) as archive:
        for field in (*FIELDS.values(), 'days', 'codes', 'digest'):
            with archive.open(field+'.npy') as source, (cache/(field+'.npy')).open('wb') as target:
                shutil.copyfileobj(source, target, length=1024*1024)
    p = load_panel()
    days, codes = p['days'].tolist(), p['codes'].tolist()
    frozen = read(FROZEN)
    assert days == frozen['calendar']
    meta = read(HOME/'reports/f1_work/cache.json')
    assert days == meta['days'] and codes == meta['codes'] and str(p['digest']) == meta['dataset_digest']
    shape = p['c'].shape
    core = {}
    for name in ('to20', 'adr20', 'perf126', 'ema9', 'ema21'):
        core[name] = np.lib.format.open_memmap(WORK/(name+'.npy'), mode='w+', dtype='float32', shape=shape)
    for name in ('liquid', 'broad', 'memory'):
        core[name] = np.lib.format.open_memmap(WORK/(name+'.npy'), mode='w+', dtype='bool', shape=shape)
    starts = np.lib.format.open_memmap(WORK/'starts.npy', mode='w+', dtype='uint8', shape=shape)
    lookup = {(g['code'], g['peak']): g for g in frozen['legs']}
    assert len(lookup) == 48
    industry = read(INDUSTRY)
    first = int(np.searchsorted(days, '2024-01-01'))
    census = {y: Counter() for y in YEARS}
    count, entries = 0, 0
    with (WORK/'library.jsonl').open('w', encoding='utf-8') as output:
        for j, code in enumerate(codes):
            a = stock(p, j)
            amount = SI.roll(a['t'], 20)
            adr = 100*SI.roll(SI.divide(a['h'], a['l'])-1, 20)
            e9, e21 = SI.ema(a['c'], 9), SI.ema(a['c'], 21)
            perf = 100*(SI.divide(a['c'], SI.lag(a['c'], 126))-1)
            liquid = (a['raw_c'] >= 2) & (amount >= 50e6) & (adr >= 3)
            broad = (a['raw_c'] >= 1) & (amount >= 2e6)
            events = local_starts(a['c'], e21)
            for name, values in (('to20', amount), ('adr20', adr), ('perf126', perf),
                                 ('ema9', e9), ('ema21', e21), ('liquid', liquid), ('broad', broad)):
                core[name][:, j] = values
            starts[:, j] = events
            indices = np.flatnonzero(liquid & (events > 0) & (np.arange(shape[0]) >= first))
            for t in indices:
                year = days[int(t)][:4]
                census[year]['local_starts'] += 1
                complete = t+60 < shape[0]
                census[year]['complete_60' if complete else 'censored_starts'] += 1
                gain = np.nanmax(a['h'][t:t+61])/a['c'][t]-1
                census[year]['observed_ge30' if gain >= .3 else ('complete_lt30' if complete else 'unresolved_lt30')] += 1
            legs = mainleg.legs(((code, int(t), str(days[int(t)])) for t in indices), {code: a})
            for g in legs:
                t = g['entries'][0]['index']
                target = lookup.get((code, g['peak']))
                g.update(id=count, first=t, first_date=days[t], peak_date=days[g['peak']], year=days[t][:4],
                         gain=g['entries'][0]['gain'], duration=g['peak']-t,
                         his=target is not None, target=target['key'] if target else None,
                         anchor=target['first_date'] if target else None,
                         industry=industry.get(code, '未分类'), start_kind=int(events[t]),
                         seed_count=len(g['entries']))
                output.write(json.dumps(clean(g), ensure_ascii=False, allow_nan=False)+'\n')
                count += 1
                entries += len(g['entries'])
            if j % 500 == 0:
                log(f'core {j}/{len(codes)}; library rows {count}')
    for t in range(shape[0]):
        ix = np.flatnonzero(core['broad'][t] & np.isfinite(core['perf126'][t]))
        core['memory'][t] = False
        core['memory'][t, ix] = SI.midrank(core['perf126'][t, ix]) >= 80
    for j in range(shape[1]):
        core['memory'][:, j] = F2.F.trailing_memory(core['memory'][:, j])
    for value in (*core.values(), starts):
        value.flush()
    assert snapshots(source_paths()) == before, 'U1 inputs changed during preparation'
    write('prepare.json', dict(days=days, codes=codes, dataset_digest=str(p['digest']), shape=shape,
        library_rows=count, qualifying_seeds=entries, seed_census=census, resources=resources(),
        industry_policy='current snapshot for descriptive strata only; excluded from model'))
    log(f'library complete: {count} rows; {entries} qualifying seeds')


def load_panel():
    p = {k: np.load(WORK/'panel'/(v+'.npy'), mmap_mode='r') for k, v in FIELDS.items()}
    p.update({k: np.load(WORK/'panel'/(k+'.npy'), mmap_mode='r') for k in ('days', 'codes', 'digest')})
    return p


def stock(p, j):
    return dict({k: p[k][:, j].astype(float) for k in FIELDS}, days=p['days'])


def library():
    # A fixed, audited file, with a hard bound independent of available RAM.
    result = []
    with (WORK/'library.jsonl').open(encoding='utf-8') as stream:
        for line in stream:
            if len(result) >= 100000:
                raise ValueError('library exceeds U1 bounded analysis size')
            result.append(json.loads(line))
    return result


def local_starts(close, e21):
    prior_high = SI.roll(SI.lag(close), 20, 'max')
    breakout = close > prior_high
    first = breakout & ~np.r_[False, breakout[:-1]]
    reclaim = (SI.lag(close) <= SI.lag(e21)) & (close > e21)
    return first.astype(np.uint8) + 2*reclaim.astype(np.uint8)


def earnings_rows():
    result = defaultdict(list)
    with EARNINGS.open(encoding='utf-8') as stream:
        for row in csv.DictReader(stream):
            result[row['security']].append((row['earnings_date'][:10], row['pub_type']))
    return result


def earnings_features(days, records, opening, close):
    """Only realized announcements; AFTER/REGULAR/unknown react on the next session."""
    ordinal = np.array([date.fromisoformat(str(d)).toordinal() for d in days])
    age, gap = np.full(len(days), np.nan), np.full(len(days), np.nan)
    reactions = {}
    for day, when in sorted(set(records)):
        i = int(np.searchsorted(days, day, side='left' if when == 'BEFORE' else 'right'))
        if i < len(days):
            reactions[i] = day
    last = None
    for t in range(len(days)):
        if t in reactions:
            last = t
        if last is not None:
            age[t] = ordinal[t]-date.fromisoformat(reactions[last]).toordinal()
            if last > 0 and np.isfinite(opening[last]) and close[last-1] > 0:
                gap[t] = 100*(opening[last]/close[last-1]-1)
    return age, gap, reactions


def base_features(a, qqq, records):
    age, earnings_gap, reactions = earnings_features(a['days'], records, a['o'], a['c'])
    values = SI.legacy_per_stock(a, qqq, dict(earn_days=age))
    values.update(SI.price_extremes(a['c'], a['h'], a['l']))
    gap = 100*(SI.divide(a['o'], SI.lag(a['c']))-1)
    eprev = np.full(len(gap), np.nan)
    post = np.zeros(len(gap))
    for t in range(len(gap)):
        recent = [u for u in range(max(0, t-2), t+1) if u in reactions]
        if recent:
            post[t] = 1
            eprev[t] = gap[recent[-1]]
    values.update(perf126_pct=100*(SI.divide(a['c'], SI.lag(a['c'], 126))-1),
        attention20_120=SI.divide(SI.roll(a['t'], 20), SI.roll(a['t'], 120)), gap_pct=gap,
        support_near_adr=np.minimum(abs(values['ext_ema9_adr']), abs(values['ext_ema21_adr'])),
        ep10_recent3=(SI.roll(np.where(np.isfinite(gap), gap, -np.inf), 3, 'max') >= 10).astype(float),
        earnings_gap_pct=earnings_gap, post_earn3=post,
        earn_ep10_recent3=((eprev >= 10) & (post > 0)).astype(float))
    return values, dict(earn_days=age, earn_index=np.array([max((r for r in reactions if r <= t), default=-1)
                                                         for t in range(len(gap))], float))


def peer_queries(pool_close, query_close, monthly, monthly_rank, query_monthly, pool_codes, query_codes, block=128):
    """Query versus pool in blocks; no all-market correlation matrix."""
    def normalize(c):
        r = SI.divide(c[1:], c[:-1])-1
        valid = np.all(np.isfinite(r), axis=0)
        z = np.nan_to_num(r.T-r.mean(axis=0)[:, None])
        norm = np.linalg.norm(z, axis=1)
        valid &= norm > 1e-12
        return z/np.where(norm > 0, norm, 1)[:, None], valid
    result = np.full((len(query_codes), 3), np.nan)
    result[:, 0] = 0
    if pool_close.shape[0] != 61 or query_close.shape[0] != 61:
        return result
    pool, pv = normalize(pool_close)
    query, qv = normalize(query_close)
    for start in range(0, len(query_codes), block):
        end = min(start+block, len(query_codes))
        members = np.zeros((end-start, len(pool_codes)), bool)
        for other in range(0, len(pool_codes), block):
            stop = min(other+block, len(pool_codes))
            corr = query[start:end] @ pool[other:stop].T
            members[:, other:stop] = ((corr >= .6) & qv[start:end, None] & pv[None, other:stop])
        members &= query_codes[start:end, None] != pool_codes[None, :]
        result[start:end, 0] = np.sum(members & (monthly_rank >= 80)[None, :], axis=1)
        for k, mask in enumerate(members):
            i = start+k
            values = monthly[mask & np.isfinite(monthly)]
            if len(values):
                result[i, 1] = F2.rank_against(np.array([np.median(values)]), monthly)[0]
                result[i, 2] = SI.midrank(np.r_[values, query_monthly[i]])[-1]
    return result


def features():
    start('features')
    meta, legs = read(WORK/'prepare.json'), library()
    p = load_panel()
    days, codes = meta['days'], meta['codes']
    ci = {c: j for j, c in enumerate(codes)}
    shape = p['c'].shape
    liquid = np.load(WORK/'liquid.npy', mmap_mode='r')
    memory = np.load(WORK/'memory.npy', mmap_mode='r')
    query = set()
    for g in legs:
        for delta in OFFSETS:
            if 0 <= g['first']+delta < shape[0]:
                query.add((g['first']+delta, ci[g['code']]))
    for g in read(FROZEN)['legs']:
        query.update((g['first']+delta, ci[g['code']]) for delta in range(-5, 4)
                     if 0 <= g['first']+delta < shape[0])
    queries = np.array(sorted(query), np.int32)
    qday, qcode = queries.T
    np.save(WORK/'query.npy', queries)
    rd, rc = np.nonzero(liquid)
    keys = np.unique(np.r_[rd*shape[1]+rc, qday*shape[1]+qcode])
    rd, rc = (keys//shape[1]).astype(np.int32), (keys % shape[1]).astype(np.int32)
    np.savez(WORK/'rows.npz', day=rd, code=rc)
    order = np.argsort(rc, kind='stable')
    offsets = np.r_[0, np.cumsum(np.bincount(rc, minlength=shape[1]))]
    qorder = np.argsort(qcode, kind='stable')
    qoffsets = np.r_[0, np.cumsum(np.bincount(qcode, minlength=shape[1]))]
    raw = np.lib.format.open_memmap(WORK/'raw.npy', mode='w+', dtype='float32', shape=(len(BASIC), len(rd)))
    raw[:] = np.nan
    full_names = tuple(s['name'] for s in SI.SPEC if s['layer'] == 'per_stock'
                       and s['family'] != 'options' and not s['name'].startswith('h4_') and s['name'] not in BASIC)
    all_names = BASIC + full_names + EXTRA
    assert len(all_names) == len(set(all_names))
    x = np.lib.format.open_memmap(WORK/'features.npy', mode='w+', dtype='float32',
                                shape=(len(qday), len(all_names)))
    x[:] = np.nan
    from studies.trader_data.supplemental import benchmark
    qqq, benchmark_sources = benchmark('US.QQQ', days)
    records = earnings_rows()
    bi = {n: k for k, n in enumerate(BASIC)}
    fi = {n: k for k, n in enumerate(all_names)}
    for j, code in enumerate(codes):
        rr, qr = order[offsets[j]:offsets[j+1]], qorder[qoffsets[j]:qoffsets[j+1]]
        if not len(rr):
            continue
        a = stock(p, j)
        values, extras = base_features(a, qqq, records.get(code, ()))
        for k, name in enumerate(BASIC):
            raw[k, rr] = values[name][rd[rr]]
            x[qr, k] = values[name][qday[qr]]
        if len(qr):
            # One stock's full v1.1 values at a time; no H4 or option inputs supplied.
            full = SI.per_stock(a, qqq, extras, version='v1.1')
            for name in full_names:
                x[qr, fi[name]] = full[name][qday[qr]]
        if j % 200 == 0:
            raw.flush()
            x.flush()
            log(f'per-stock portraits {j}/{len(codes)}')
    raw.flush()
    qrows = np.searchsorted(keys, qday*shape[1]+qcode)
    np.save(WORK/'query_row.npy', qrows)
    maximum, valid_dates = 0, 0
    for t in np.unique(qday):
        lo, hi = np.searchsorted(rd, [t, t+1])
        pool = np.arange(lo, hi)
        pool = pool[liquid[t, rc[pool]]]
        ql, qh = np.searchsorted(qday, [t, t+1])
        qr = np.arange(ql, qh)
        r = qrows[qr]
        if not len(pool):
            x[qr, fi['long_strength_memory']] = memory[t, qcode[qr]]
            continue
        maximum = max(maximum, len(pool))
        valid_dates += 1
        for name in PERCENTILES:
            x[qr, fi['pctl_'+name]] = F2.rank_against(raw[bi[name], r], raw[bi[name], pool])
        x[qr, fi['long_strength_memory']] = memory[t, qcode[qr]]
        for n in (21, 63, 126):
            x[qr, fi[f'pctl_rs{n}_vs_qqq_pct']] = x[qr, fi[f'pctl_perf{n}_pct']]
            x[qr, fi[f'money_rs{n}_product']] = (x[qr, fi['pctl_dollar_vol20_M']]/100
                                                           * x[qr, fi[f'pctl_perf{n}_pct']]/100)
        peers = peer_queries(p['c'][max(0, t-60):t+1, rc[pool]].astype(float),
            p['c'][max(0, t-60):t+1, qcode[qr]].astype(float), raw[bi['perf21_pct'], pool],
            SI.midrank(raw[bi['perf21_pct'], pool]), raw[bi['perf21_pct'], r], rc[pool], qcode[qr])
        for k, name in enumerate(('peer_leaders20_count', 'peer_perf21_median_pctl', 'peer_strength_pctl')):
            x[qr, fi[name]] = peers[:, k]
        x[qr, fi['log1p_peer_leaders20_count']] = np.log1p(peers[:, 0])
        x[qr, fi['attention20_120_pctl']] = F2.rank_against(raw[bi['attention20_120'], r], raw[bi['attention20_120'], pool])
        pool_near = np.minimum(abs(raw[bi['ext_ema9_adr'], pool]), abs(raw[bi['ext_ema21_adr'], pool]))
        pool_dollar = SI.midrank(raw[bi['dollar_vol20_M'], pool])
        mix = memory[t, rc[pool]]*(pool_dollar/100)/(1+pool_near)
        query_mix = memory[t, qcode[qr]]*(x[qr, fi['pctl_dollar_vol20_M']]/100)/(1+raw[bi['support_near_adr'], r])
        x[qr, fi['remembered_liquid_pullback_pctl']] = F2.rank_against(query_mix, mix)
        if t % 80 == 0:
            x.flush()
            log(f'date {days[int(t)]}; pool {len(pool)}, query {len(qr)}, blocks <=128x128')
    x.flush()
    write('features.json', dict(names=all_names, basic=BASIC, per_stock_full=full_names,
        model=MODEL, query_rows=len(queries), sparse_pool_rows=len(rd), maximum_pool=maximum,
        dates=valid_dates, shape=x.shape, resources=resources(), benchmark_sources=benchmark_sources,
        hashes={n: sha(WORK/n) for n in ('features.npy', 'query.npy', 'query_row.npy', 'rows.npz', 'raw.npy')},
        unavailable=['future earnings schedule publication history', 'historical industry membership',
                     'verified news themes', 'H4 and option inputs excluded'],
        percentile_scope='same-night full U4 liquidity range, without F1 trend gate'))
    log(f'features frozen: {x.shape}; maximum pool {maximum}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=('prepare', 'features'))
    args = parser.parse_args()
    offline()
    globals()[args.stage]()


if __name__ == '__main__':
    main()
