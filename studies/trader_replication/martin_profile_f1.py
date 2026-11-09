"""F1 offline daily preference fitting; labels never enter scoring or nomination.

Run prepare, fit, evaluate, verify in that order. Outputs stay in f1_work.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import resource
import sys
import time

import numpy as np

from studies.trader_replication import standard_indicators as SI

ROOT = Path(__file__).resolve().parents[2]
HOME = ROOT / 'studies/martin_luk'
WORK = HOME / 'reports/f1_work'
D1 = HOME / 'reports/d1_work'
PREREG = HOME / 'notes/PREREG_F1_CN.md'
LEGS = HOME / 'notes/legs_frozen.json'
TRAIN_END = '2025-12-31'
START = '2024-01-01'
FEATURES = ('dollar_vol20_percentile', 'adr20_pct', 'perf21_pct', 'perf63_pct',
            'perf126_pct', 'from_high252_pct', 'low252_distance_pct', 'ema_stack',
            'ext_ema9_adr', 'ext_ema21_adr', 'ema9_21_gap_adr', 'rvol20', 'rvol3_20',
            'contract3_adr', 'gap_today_adr', 'close_pos', 'long_strength_memory',
            'perf1_pct', 'perf5_pct')
LIBRARY_FEATURES = tuple(n for n in FEATURES if n not in
                         ('dollar_vol20_percentile', 'perf126_pct', 'long_strength_memory'))
CANDIDATES = (
    dict(id='F1a', pool='new', paired=False, k=3, cooldown=10),
    dict(id='F1b', pool='new', paired=True, k=3, cooldown=10),
    dict(id='F1c', pool='new', paired=True, k=2, cooldown=10),
    dict(id='F1d', pool='ie47', paired=False, k=3, cooldown=10),
    dict(id='F1e', pool='new', paired=True, k=3, cooldown=5),
)
ROUTE_NAMES = ('close_pdh', 'E10', 'E11', 'B')
T0 = time.monotonic()


def log(message):
    print(f'[{time.monotonic()-T0:.0f}s; '
          f'{resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024:.0f} MiB] {message}', flush=True)


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


def write(path, value):
    path = Path(path)
    tmp = path.with_suffix(path.suffix+'.tmp')
    tmp.write_text(json.dumps(clean(value), ensure_ascii=False, indent=1, allow_nan=False)+'\n', encoding='utf-8')
    tmp.replace(path)


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def offline():
    sys.dont_write_bytecode = True
    def audit(event, args):
        if event in ('socket.connect', 'socket.bind', 'socket.getaddrinfo', 'subprocess.Popen', 'os.system'):
            raise PermissionError('F1 is offline and single-process')
        if event == 'open' and not isinstance(args[0], int):
            if args[2] & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND):
                if not Path(os.fsdecode(args[0])).resolve().is_relative_to(WORK.resolve()):
                    raise PermissionError('F1 may write only f1_work')
    sys.addaudithook(audit)


def sources():
    paths = [Path(__file__), Path(SI.__file__), PREREG, LEGS,
             HOME/'notes/PLAN_F1_CN.md', HOME/'notes/RULES_CN.md',
             HOME/'notes/PI_METRIC_ADVICE_20261107_CN.md',
             D1/'master_metadata.json', D1/'master_paths.json', D1/'master_bpath.npy',
             D1/'ie_pool.npy', D1/'ie_selection.json',
             ROOT/'studies/martin_luk/replicate.py', ROOT/'studies/martin_luk/luk.py']
    return {str(p.relative_to(ROOT)): sha(p) for p in paths}


def protected():
    names = ('studies/trader_replication/system.py', 'studies/trader_replication/systems.py',
             'studies/trader_replication/martin_profile_ie29.py',
             'studies/trader_replication/martin_profile_ie42.py',
             'studies/martin_luk/reports/ie47_profile.json', 'studies/trader_screens/board.py')
    return {n: sha(ROOT/n) for n in names}


def stock_core(arrays, days):
    """Small one-stock vectors, with master U4's full-window liquidity rules."""
    from studies.martin_luk import luk
    from studies.martin_luk.replicate import weekly_ema
    c, h, l = (np.asarray(arrays[k], float) for k in ('c', 'h', 'l'))
    e9, e21 = (luk.ema(c[:, None], n)[:, 0] for n in (9, 21))
    to20 = SI.roll(arrays['t'], 20)
    adr = 100*SI.roll(SI.divide(h, l)-1, 20)
    weekly_up = weekly_ema(c[:, None], days, 9)[:, 0] > weekly_ema(c[:, None], days, 21)[:, 0]
    liquid = (arrays['raw_c'] >= 2) & (to20 >= 50e6) & (adr >= 3)
    broad = (arrays['raw_c'] >= 1) & (to20 >= 2e6)
    trend = (c >= e21) | (e9 > e21) | weekly_up
    return dict(e9=e9, e21=e21, to20=to20, adr=adr, liquid=liquid, broad=broad,
                new=liquid & trend, perf126=100*(SI.divide(c, SI.lag(c, 126))-1))


def stock_features(arrays, qqq):
    out = SI.per_stock(arrays, qqq, version='v1.1', names=LIBRARY_FEATURES)
    out['perf126_pct'] = 100*(SI.divide(arrays['c'], SI.lag(arrays['c'], 126))-1)
    return out


def daily_routes(arrays, e9, e21, bpath=None):
    """D1 daily actions, known only at this day's close; no intraday-price fiction."""
    o, h, l, c = (np.asarray(arrays[k], float) for k in ('o', 'h', 'l', 'c'))
    pc, ph, e9p, e21p = map(SI.lag, (c, h, e9, e21))
    near = abs(SI.divide(pc, e9p)-1) <= .03
    close_pdh = c > ph
    e10 = near & ((h > ph) | ((e9p > e21p) & (l <= e9p) & (h >= e9p)))
    e11 = (o > pc*1.01) & (l <= np.fmax(ph, e9p)) & (c > np.fmin(ph, e9p))
    bpath = np.zeros(len(c), bool) if bpath is None else np.asarray(bpath, bool)
    return np.where(np.isfinite(o+h+l+c), close_pdh.astype(np.uint8)
                    + 2*e10.astype(np.uint8) + 4*e11.astype(np.uint8) + 8*bpath.astype(np.uint8), 0)


def trailing_memory(top, length=120):
    """Feature memory includes tonight; B's cached action uses the prior-night rule."""
    cs = np.r_[0, np.cumsum(top, dtype=np.int32)]
    end = np.arange(1, len(top)+1)
    return cs[end]-cs[np.maximum(0, end-length)] > 0


def eligible(leg, index, price):
    if not np.isfinite(price) or price <= 0 or index >= leg['peak']:
        return []
    ahead = leg['top']/price-1
    return [e for e in leg['entries'] if index >= e['index']-3 and ahead >= .5*e['gain']]


def label_windows(leg, o, c, routes, last):
    """Future prices live exclusively in this label builder, outside scoring."""
    signal, trigger = [], []
    first = min(e['index'] for e in leg['entries'])
    for t in range(max(0, first-4), min(leg['peak']-1, last)):
        if not eligible(leg, t+1, o[t+1]):
            continue
        signal.append(t)
        for u in range(t+1, min(t+5, last, leg['peak']-1)+1):
            anchors = eligible(leg, u, c[u])
            if routes[u] and anchors:
                trigger.append(dict(night=t, fill=u, price=float(c[u]),
                                    share=max((leg['top']/c[u]-1)/e['gain'] for e in anchors),
                                    offset=u-first,
                                    synced=any(u <= e['index']+2 for e in anchors),
                                    routes=[n for k, n in enumerate(ROUTE_NAMES) if int(routes[u]) & (1 << k)]))
                break
    return signal, trigger


def clipped_leg(leg, prices, last):
    """Keep the frozen leg identity/denominator; mature its training label at the cutoff."""
    leg = json.loads(json.dumps(leg))
    if leg['peak'] > last:
        first = leg['first']
        peak = first+int(np.nanargmax(prices['h'][first:last+1]))
        leg['original_peak'], leg['original_top'] = leg['peak'], leg['top']
        leg['peak'], leg['top'], leg['training_clipped'] = peak, float(prices['h'][peak]), True
        leg['entries'] = [e for e in leg['entries'] if e['index'] <= last]
        for e in leg['entries']:
            e['gain'] = leg['top']/float(prices['c'][e['index']])-1
        leg['gain'] = leg['entries'][0]['gain']
    return leg


def prepare():
    if (WORK/'cache.json').exists():
        raise FileExistsError('F1 cache is immutable; use existing artifacts')
    from studies import trader_data as TD
    from studies.trader_data import panel as TP, supplemental as SP
    before, fingerprints = Path('/proc/meminfo').read_text(), sources()
    frozen = read(LEGS)
    p = TP.build(TD.dataset('us', 'frozen'), write_cache=False)
    days, codes = list(map(str, p['days'])), list(map(str, p['codes']))
    meta = read(D1/'master_metadata.json')
    ie_meta = read(D1/'ie_selection.json')
    assert days == frozen['calendar'] == meta['days'] == ie_meta['days']
    assert codes == meta['codes'] == ie_meta['codes']
    qqq, benchmark_sources = SP.benchmark('US.QQQ', days, 'frozen')
    shape = p['close'].shape
    old = np.load(D1/'ie_pool.npy', mmap_mode='r')
    bpath = np.load(D1/'master_bpath.npy', mmap_mode='r')
    assert old.shape == bpath.shape == shape
    regime = np.where(qqq < SI.ema(qqq, 50), 2, np.where(qqq <= 1.01*SI.ema(qqq, 21), 1, 0))
    new, broad = np.zeros(shape, bool), np.zeros(shape, bool)
    amount, ret = np.full(shape, np.nan, np.float32), np.full(shape, np.nan, np.float32)
    routes = np.lib.format.open_memmap(WORK/'routes.npy', mode='w+', dtype='uint8', shape=shape)
    fields = (('o', 'open'), ('h', 'high'), ('l', 'low'), ('c', 'close'), ('v', 'volume'),
              ('t', 'turnover'), ('raw_c', 'raw_close'))
    def stock(j):
        return {k: p[n][:, j].astype(float) for k, n in fields}
    for j in range(shape[1]):
        a = stock(j)
        core = stock_core(a, days)
        new[:, j], broad[:, j] = core['new'], core['broad']
        amount[:, j], ret[:, j] = core['to20'], core['perf126']
        routes[:, j] = daily_routes(a, core['e9'], core['e21'], bpath[:, j])
        if j % 500 == 0:
            log(f'liquidity/actions {j}/{shape[1]}')
    routes.flush()
    memory = np.zeros(shape, bool)
    dollar_rank = np.full(shape, np.nan, np.float32)
    top126 = np.zeros(shape, bool)
    for t in range(shape[0]):
        ix = np.flatnonzero(broad[t] & np.isfinite(ret[t]))
        if len(ix):
            top126[t, ix] = SI.midrank(ret[t, ix]) >= 80
        ix = np.flatnonzero(new[t])
        if len(ix):
            dollar_rank[t, ix] = SI.midrank(amount[t, ix])
        # IE47-only rows still receive a percentile against tonight's U4 trend pool.
        other = np.flatnonzero(old[t] & ~new[t])
        if len(ix) and len(other):
            peers = np.sort(amount[t, ix])
            values = amount[t, other]
            dollar_rank[t, other] = 50*(np.searchsorted(peers, values, 'left')
                                      + np.searchsorted(peers, values, 'right'))/len(peers)
    for j in range(shape[1]):
        memory[:, j] = trailing_memory(top126[:, j])
    del top126, amount, ret, broad
    # Include the warm-up nomination night for the first session of the target period.
    first = max(0, int(np.searchsorted(days, START))-1)
    union = new | old
    union[:first] = False
    row_day, row_code = np.nonzero(union)
    count = len(row_day)
    x = np.lib.format.open_memmap(WORK/'features.npy', mode='w+', dtype='float32', shape=(len(FEATURES), count))
    row_map = np.full(shape, -1, np.int32)
    row_map[row_day, row_code] = np.arange(count)
    entry = np.zeros(count, np.uint8)
    label_prices = {}
    target_codes = {g['code'] for g in frozen['legs']}
    for j, code in enumerate(codes):
        rr = np.flatnonzero(row_code == j)
        if not len(rr) and code not in target_codes:
            continue
        a = stock(j)
        if code in target_codes:
            label_prices[code] = {k: a[k] for k in ('o', 'h', 'c')}
        if len(rr):
            values = stock_features(a, qqq)
            values['long_strength_memory'] = memory[:, j].astype(float)
            values['dollar_vol20_percentile'] = dollar_rank[:, j]
            for k, name in enumerate(FEATURES):
                x[k, rr] = values[name][row_day[rr]]
            near = np.minimum(abs(values['ext_ema9_adr']), abs(values['ext_ema21_adr'])) <= 1
            entry[rr] = (memory[:, j] & near)[row_day[rr]]
        if j % 300 == 0:
            log(f'v1.1 features {j}/{shape[1]}')
    x.flush()
    last = int(np.searchsorted(days, TRAIN_END, side='right'))-1
    train_labels, full_labels = [], []
    for leg in frozen['legs']:
        j = codes.index(leg['code'])
        price = label_prices[leg['code']]
        for mode, target, end in (('full', full_labels, len(days)-1), ('train', train_labels, last)):
            if mode == 'train' and leg['first_date'][:4] not in ('2024', '2025'):
                continue
            g = clipped_leg(leg, price, end) if mode == 'train' else leg
            signal, triggers = label_windows(g, price['o'], price['c'], routes[:, j], end)
            target.append(dict(leg=g, year=leg['first_date'][:4], signal_nights=signal,
                               triggers=[dict(r, row=int(row_map[r['night'], j])) for r in triggers],
                               signal_rows=[int(row_map[t, j]) for t in signal]))
    write(WORK/'train_labels.json', train_labels)
    write(WORK/'full_labels.json', full_labels)
    action = np.full(count, -1, np.int32)
    for shift in range(5, 0, -1):
        u = row_day+shift
        ok = u < shape[0]
        ix = np.flatnonzero(ok)
        ix = ix[routes[u[ix], row_code[ix]] > 0]
        action[ix] = u[ix]
    np.savez(WORK/'rows.npz', row_day=row_day.astype(np.int32), row_code=row_code.astype(np.int32),
             new=new[row_day, row_code], ie47=old[row_day, row_code], entry=entry,
             regime=regime[row_day].astype(np.int8), action=action)
    widths = {}
    for name, mask in (('new', new), ('ie47', old)):
        widths[name] = {year: dict(nights=int(sum(d[:4] == year for d in days)),
            median=float(np.median(mask[[d[:4] == year for d in days]].sum(1))),
            mean=float(np.mean(mask[[d[:4] == year for d in days]].sum(1))),
            minimum=int(np.min(mask[[d[:4] == year for d in days]].sum(1))),
            maximum=int(np.max(mask[[d[:4] == year for d in days]].sum(1)))) for year in ('2024', '2025', '2026')}
    write(WORK/'pool_widths.json', widths)
    current = sources()
    assert fingerprints == current, 'source changed during preparation'
    write(WORK/'cache.json', dict(days=days, codes=codes, features=FEATURES, rows=count,
          dataset_digest=p['digest'], benchmark_sources=benchmark_sources, sources=fingerprints,
          protected=protected(), before_memory=before, python=sys.executable,
          peak_rss_mib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024,
          duration_seconds=time.monotonic()-T0, train_last=last, first_night=first,
          cache_hashes={n: sha(WORK/n) for n in ('features.npy', 'routes.npy', 'rows.npz',
                       'train_labels.json', 'full_labels.json')},
          cut_training_legs=[r['leg']['key'] for r in train_labels if r['leg'].get('training_clipped')]))
    log(f'cache ready: {count} bounded rows, {len(train_labels)} training legs; holdout metrics unopened')


def bin_edges(x):
    finite = x[np.isfinite(x)]
    unique = np.unique(finite)
    if len(unique) <= 3:
        return (unique[:-1]+unique[1:])/2
    return np.unique(np.quantile(finite, [.2, .4, .6, .8]))


def bin_indices(x, edges):
    return np.where(np.isfinite(x), np.searchsorted(edges, x, 'right'), len(edges)+1).astype(np.uint8)


def preference(bins, size, mask, groups):
    """Each leg casts one vote; missing is a normal, explicitly shrunk bin."""
    pool = np.bincount(bins[mask], minlength=size).astype(float)
    his = np.zeros(size)
    n = 0
    for rows in groups:
        rr = rows[mask[rows]]
        if len(rr):
            his += np.bincount(bins[rr], minlength=size)/len(rr)
            n += 1
    if not pool.sum() or not n:
        return np.zeros(size), n, pool, his
    ps, prior = pool/pool.sum(), n/size
    hs = (his+prior*ps)/(n+prior)
    scores = np.zeros(size)
    ok = ps > 0
    scores[ok] = np.log(hs[ok]/ps[ok])
    return scores, n, pool, his


def objective(result):
    return (result['covered'], result['P_opp'] or 0., result['E'] or 0.)


class Sample:
    def __init__(self, meta, arrays, x, spec, labels, end=None):
        self.meta, self.a, self.spec, self.labels = meta, arrays, spec, labels
        days = meta['days']
        rd = arrays['row_day']
        allowed = arrays[spec['pool']].copy()
        if end is not None:
            allowed &= rd <= end
        self.indices = np.flatnonzero(allowed)
        self.x = np.asarray(x[:, self.indices], np.float32)
        self.day = rd[self.indices]
        self.code = arrays['row_code'][self.indices]
        self.entry, self.regime = (arrays[k][self.indices] for k in ('entry', 'regime'))
        distinct, offset, counts = np.unique(self.day, return_index=True, return_counts=True)
        stop = len(days)-1 if end is None else end
        self.nights = np.arange(meta['first_night'], stop+1)
        width = int(counts.max()) if len(counts) else 0
        self.pad = np.full((len(self.nights), width), len(self.indices), np.int32)
        for t, start, n in zip(distinct, offset, counts):
            i = int(t-meta['first_night'])
            self.pad[i, :n] = np.arange(start, start+n)
        self.code_pad = np.r_[self.code, -1]
        self.remap = np.full(len(rd), -1, np.int32)
        self.remap[self.indices] = np.arange(len(self.indices))
        self.leg_rows, self.signal_rows, self.fill_info = [], [], []
        self.row_legs = {}
        for g, label in enumerate(labels):
            byrow = {}
            for row in label['triggers']:
                r = int(self.remap[row['row']]) if row['row'] >= 0 else -1
                if r >= 0:
                    byrow[r] = row
                    self.row_legs.setdefault(r, []).append(g)
            self.fill_info.append(byrow)
            self.leg_rows.append(np.array(sorted(byrow), np.int32))
            rows = [int(self.remap[r]) for r in label['signal_rows'] if r >= 0 and self.remap[r] >= 0]
            self.signal_rows.append(np.array(rows, np.int32))
        self.opportunity = np.zeros(len(self.nights), bool)
        good = np.array(sorted(self.row_legs), np.int32)
        if len(good):
            self.opportunity[np.searchsorted(self.nights, self.day[good])] = True
        self.good = np.zeros(len(self.indices), bool)
        self.good[good] = True
        self.years = np.array([days[t][:4] for t in self.nights])

    def nominate(self, scores, k=None):
        k = self.spec['k'] if k is None else k
        order = np.argsort(-np.r_[np.round(scores, 10), -np.inf][self.pad], axis=1, kind='stable')
        ranked = np.take_along_axis(self.pad, order, axis=1)
        selected = np.full((len(self.nights), k), len(self.indices), np.int32)
        last = {}
        for night, rows in enumerate(ranked):
            t, n = int(self.nights[night]), 0
            for r in rows:
                if r == len(self.indices):
                    break
                code = int(self.code[r])
                if t-last.get(code, -100000) <= self.spec['cooldown']:
                    continue
                selected[night, n] = r
                last[code] = t
                n += 1
                if n == k:
                    break
        return selected

    def evaluate(self, scores, k=None, details=False):
        picks = self.nominate(scores, k)
        valid = picks < len(self.indices)
        rows = picks[valid]
        chosen = np.zeros(len(self.indices), bool)
        chosen[rows] = True
        hit, shares, per_leg = [], [], []
        for label, rr, sr, info in zip(self.labels, self.leg_rows, self.signal_rows, self.fill_info):
            got = rr[chosen[rr]]
            hit.append(bool(len(got)))
            first = min((info[int(r)] for r in got), key=lambda r: (r['fill'], r['night']), default=None)
            if first is not None:
                shares.append(first['share'])
            if details:
                named = sr[chosen[sr]]
                per_leg.append(dict(key=label['leg']['key'], year=label['year'], leg=label['leg'],
                    reachable_signal=bool(len(sr)), reachable_trigger=bool(len(rr)),
                    nominated=bool(len(named)), covered=bool(len(got)),
                    first_nomination=self.meta['days'][int(self.day[named[0]])] if len(named) else None,
                    first=first, pool_trigger_nights=len(rr)))
        good = np.r_[self.good, False]
        denom = int(valid[self.opportunity].sum())
        numer = int(good[picks[self.opportunity]].sum())
        result = dict(n=len(self.labels), covered=sum(hit), C_trig=sum(hit)/len(hit) if hit else None,
                      opportunity_nights=int(self.opportunity.sum()), opportunity_picks=denom,
                      opportunity_hits=numer, P_opp=numer/denom if denom else None,
                      E=float(np.median(shares)) if shares else None)
        if details:
            by_year = {}
            for year in sorted(set(self.years) & {'2024', '2025', '2026'}):
                p = picks[self.years == year]
                rr = p[p < len(self.indices)]
                end = max(i for i, d in enumerate(self.meta['days']) if d[:4] == year)
                actions = self.a['action'][self.indices[rr]]
                capacity = {(int(self.code[r]), int(u)) for r, u in zip(rr, actions) if 0 <= u <= end}
                by_year[year] = dict(nominations=len(rr), different_codes=len(set(map(int, self.code[rr]))),
                    first_action_opportunities=len(capacity), nights=len(p),
                    fully_supplied_nights=int(np.sum((p < len(self.indices)).sum(1) == p.shape[1])))
            result.update(per_leg=per_leg, by_year=by_year)
        return result


def training_tables(sample):
    groups = sample.leg_rows
    n = len(sample.indices)
    train = np.array([START <= sample.meta['days'][t] <= TRAIN_END for t in sample.day])
    contexts = dict(shared=train, up=train & (sample.regime == 0), pullback=train & (sample.regime == 1))
    tables, vectors = {}, {}
    for part, context in contexts.items():
        tables[part], vectors[part] = [], []
        for f in range(len(FEATURES)):
            edges = bin_edges(sample.x[f, train])
            bins = bin_indices(sample.x[f], edges)
            size = len(edges)+2
            pooled, targets, pool, his = preference(bins, size, context, groups)
            lookup = [pooled, pooled]
            branch_targets = [targets, targets]
            if sample.spec['paired'] and part == 'shared':
                for entry in (0, 1):
                    table, count, _, _ = preference(bins, size, context & (sample.entry == entry), groups)
                    branch_targets[entry] = count
                    if count >= 5:
                        lookup[entry] = table
            value = np.where(sample.entry == 1, lookup[1][bins], lookup[0][bins])
            score_context = np.ones(n, bool) if part == 'shared' else sample.regime == (0 if part == 'up' else 1)
            value[~score_context] = 0
            if part != 'shared' and targets < 5:
                value[:] = 0
                lookup = [np.zeros(size), np.zeros(size)]
            tables[part].append(dict(name=FEATURES[f], edges=edges.tolist(),
                scores=[t.tolist() for t in lookup], pool=pool.tolist(), target_votes=his.tolist(),
                target_count=targets, branch_target_counts=branch_targets, missing_bin=size-1))
            vectors[part].append(value)
    return tables, vectors


def fit_part(sample, base, vectors, limit, label):
    model, current = {}, sample.evaluate(base)
    history, scores = [(dict(model), current)], base.copy()
    for step in range(limit):
        best = None
        for f, v in enumerate(vectors):
            if f in model:
                continue
            value = sample.evaluate(scores+v)
            key = (*objective(value), -f)
            if best is None or key > best[0]:
                best = key, f, value
        if best is None:
            break
        _, f, value = best
        model[f] = 1
        scores += vectors[f]
        history.append((dict(model), value))
        log(f'{sample.spec["id"]} {label} add {step+1}: {FEATURES[f]} {objective(value)}')
    model, current = max(history, key=lambda pair: (*objective(pair[1]), -len(pair[0])))
    scores = base+sum((w*vectors[f] for f, w in model.items()), start=np.zeros(len(base)))
    for f in list(model):
        old = model[f]
        best = (objective(current), -int(old != 0), -old, old, current)
        for weight in (0, 1, 2, 3):
            if weight == old:
                continue
            value = sample.evaluate(scores+(weight-old)*vectors[f])
            key = (objective(value), -int(weight != 0), -weight)
            if key > best[:3]:
                best = (*key, weight, value)
        scores += (best[3]-old)*vectors[f]
        model[f], current = best[3], best[4]
    model = {f: w for f, w in model.items() if w}
    for f in list(model):
        value = sample.evaluate(scores-model[f]*vectors[f])
        if objective(value) >= objective(current):
            scores -= model.pop(f)*vectors[f]
            current = value
    return model, scores


def score_model(model, sample):
    """Pure market features + frozen tables. No labels are read here."""
    total = np.zeros(len(sample.indices))
    for part, items in model['parts'].items():
        context = np.ones(len(total), bool) if part == 'shared' else sample.regime == (0 if part == 'up' else 1)
        for item in items:
            f = FEATURES.index(item['name'])
            bins = bin_indices(sample.x[f], np.asarray(item['edges']))
            tables = np.asarray(item['scores'])
            total[context] += item['weight']*tables[sample.entry[context], bins[context]]
    return total


def yearly_metrics(sample, scores, k):
    full = sample.evaluate(scores, k, details=True)
    picks = sample.nominate(scores, k)
    selected = np.zeros(len(sample.indices), bool)
    selected[picks[picks < len(selected)]] = True
    for year in sorted({label['year'] for label in sample.labels}):
        legs = [r for r in full['per_leg'] if r['year'] == year]
        nightmask = np.zeros(len(sample.nights), bool)
        good = np.zeros(len(sample.indices), bool)
        for label, rr in zip(sample.labels, sample.leg_rows):
            if label['year'] == year and len(rr):
                good[rr] = True
                nightmask[np.searchsorted(sample.nights, sample.day[rr])] = True
        chosen = picks[nightmask]
        valid = chosen < len(sample.indices)
        hits = int(np.r_[good, False][chosen].sum())
        shares = [r['first']['share'] for r in legs if r['covered']]
        row = full['by_year'].setdefault(year, {})
        row.update(n=len(legs), covered=sum(r['covered'] for r in legs),
                   nominated=sum(r['nominated'] for r in legs),
                   C_trig=sum(r['covered'] for r in legs)/len(legs) if legs else None,
                   opportunity_nights=int(nightmask.sum()), opportunity_picks=int(valid.sum()),
                   opportunity_hits=hits, P_opp=hits/int(valid.sum()) if valid.any() else None,
                   E=float(np.median(shares)) if shares else None)
    return full


def load_cache():
    meta = read(WORK/'cache.json')
    if meta['sources'] != sources():
        raise ValueError('F1 inputs/source differ from the prepared cache')
    if any(sha(WORK/name) != digest for name, digest in meta['cache_hashes'].items()):
        raise ValueError('F1 prepared arrays/labels changed')
    with np.load(WORK/'rows.npz') as z:
        arrays = {k: z[k] for k in z.files}
    return meta, arrays, np.load(WORK/'features.npy', mmap_mode='r')


def export_picks(model, meta, arrays, x):
    sample = Sample(meta, arrays, x, model['spec'], [])
    scores = score_model(model, sample)
    picks = sample.nominate(scores)
    selected, details = {}, {}
    for t, row in zip(sample.nights, picks):
        day = meta['days'][int(t)]
        if day < START:
            continue
        rr = row[row < len(sample.indices)]
        selected[day] = [meta['codes'][int(sample.code[r])] for r in rr]
        details[day] = [dict(code=code, rank=k+1, score=float(scores[r]),
                             entry_type='long_strength_pullback' if sample.entry[r] else 'emerging',
                             regime=('up', 'pullback', 'weak')[int(sample.regime[r])])
                        for k, (r, code) in enumerate(zip(rr, selected[day]))]
    name = model['spec']['id']
    write(WORK/f'picks_{name}.json', selected)
    write(WORK/f'picks_{name}_details.json', details)
    # Keep the preceding nomination for an executor that starts on the first session.
    warmup = {meta['days'][int(t)]: [meta['codes'][int(sample.code[r])] for r in row if r < len(sample.indices)]
              for t, row in zip(sample.nights, picks) if meta['days'][int(t)] < START}
    write(WORK/f'picks_{name}_warmup.json', warmup)
    return dict(path=f'picks_{name}.json', sha256=sha(WORK/f'picks_{name}.json'), nights=len(selected))


def fit():
    if (WORK/'selection.json').exists():
        raise FileExistsError('F1 selection already frozen')
    meta, arrays, x = load_cache()
    labels = read(WORK/'train_labels.json')
    fits = []
    for spec in CANDIDATES:
        path = WORK/f'fit_{spec["id"]}.json'
        if path.exists():
            result = read(path)
            if result['sources'] != meta['sources']:
                raise ValueError('completed candidate source drift')
            fits.append(result)
            continue
        sample = Sample(meta, arrays, x, spec, labels, end=meta['train_last'])
        tables, vectors = training_tables(sample)
        parts, scores = {}, np.zeros(len(sample.indices))
        for part, limit in (('shared', 7), ('up', 3), ('pullback', 3)):
            weights, scores = fit_part(sample, scores, vectors[part], limit, part)
            parts[part] = [dict(tables[part][f], weight=w) for f, w in sorted(weights.items())]
        model = dict(spec=spec, parts=parts)
        # Fit arithmetic and exported inference must produce identical nominations.
        frozen_scores = score_model(model, sample)
        assert np.array_equal(sample.nominate(scores), sample.nominate(frozen_scores)), 'export drift'
        metrics = {str(k): yearly_metrics(sample, frozen_scores, k) for k in (1, 2, 3)}
        main = metrics[str(spec['k'])]
        support = all(main['by_year'][y]['first_action_opportunities'] >= 52 for y in ('2024', '2025'))
        result = dict(model=model, metrics=metrics, support_52=support, sources=meta['sources'],
                      peak_rss_mib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024,
                      model_sha256=hashlib.sha256(json.dumps(clean(model), sort_keys=True).encode()).hexdigest())
        write(path, result)
        fits.append(result)
        log(f'{spec["id"]} fixed: {objective(main)}, supports 52/year={support}')
    def rank(pair):
        index, result = pair
        main = result['metrics'][str(result['model']['spec']['k'])]
        shortage = sum(max(0, 52-main['by_year'][y]['first_action_opportunities']) for y in ('2024', '2025'))
        return (result['support_52'], -shortage, *objective(main), -index)
    ordered = sorted(enumerate(fits), key=rank, reverse=True)
    best, second = (pair[1] for pair in ordered[:2])
    selection = dict(chosen=best['model']['spec']['id'], second=second['model']['spec']['id'],
        ranked=[r['model']['spec']['id'] for _, r in ordered], passed=best['support_52'],
        objective='(C_trig count, P_opp, E), training only', sources=meta['sources'],
        model_hashes={r['model']['spec']['id']: r['model_sha256'] for r in fits})
    write(WORK/'selection.json', selection)
    # Once selection is frozen, only the two finalists get inference on 2026 rows.
    exports = [export_picks(r['model'], meta, arrays, x) for r in (best, second)]
    write(WORK/'exports.json', exports)
    ablations = []
    sample = Sample(meta, arrays, x, best['model']['spec'], labels, end=meta['train_last'])
    for part, items in best['model']['parts'].items():
        for i, item in enumerate(items):
            model = json.loads(json.dumps(best['model']))
            del model['parts'][part][i]
            result = yearly_metrics(sample, score_model(model, sample), model['spec']['k'])
            ablations.append(dict(part=part, removed=item['name'], objective=objective(result), by_year=result['by_year']))
    write(WORK/'training_ablations.json', ablations)
    log(f'frozen selection {selection["chosen"]}; second {selection["second"]}; no holdout metrics yet')


def evaluate():
    meta, arrays, x = load_cache()
    selection = read(WORK/'selection.json')
    claim = WORK/'evaluation_started.json'
    with claim.open('x', encoding='utf-8') as stream:
        json.dump(dict(chosen=selection['chosen'], selection_sha256=sha(WORK/'selection.json'),
                       started_utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())), stream)
    labels = [r for r in read(WORK/'full_labels.json') if r['year'] == '2026']
    fitted = read(WORK/f'fit_{selection["chosen"]}.json')
    model = fitted['model']
    sample = Sample(meta, arrays, x, model['spec'], labels)
    scores = score_model(model, sample)
    metrics = {str(k): yearly_metrics(sample, scores, k) for k in (1, 2, 3)}
    write(WORK/'holdout.json', dict(chosen=selection['chosen'], main_k=model['spec']['k'], metrics=metrics,
        selection_sha256=sha(WORK/'selection.json'), model_sha256=fitted['model_sha256'],
        evaluated_once=True, runner_up_holdout_metrics=False))
    log(f'2026 evaluated once: {objective(metrics[str(model["spec"]["k"])])}')


def reachability():
    meta, arrays, x = load_cache()
    labels = read(WORK/'full_labels.json')
    result = {}
    for name in ('new', 'ie47'):
        spec = dict(pool=name, paired=False, k=3, cooldown=10)
        sample = Sample(meta, arrays, x, spec, labels)
        rows = [dict(key=label['leg']['key'], year=label['year'],
                     signal=bool(len(sr)), trigger=bool(len(tr)), signal_nights=len(sr), trigger_nights=len(tr),
                     censored=label['leg']['censored'], event=label['leg']['duration'] < 5,
                     precision=label['leg']['precision'])
                for label, sr, tr in zip(labels, sample.signal_rows, sample.leg_rows)]
        result[name] = dict(per_leg=rows, by_year={year: dict(n=sum(r['year'] == year for r in rows),
            signal=sum(r['signal'] for r in rows if r['year'] == year),
            trigger=sum(r['trigger'] for r in rows if r['year'] == year)) for year in ('2024', '2025', '2026')})
    write(WORK/'reachability.json', result)
    log('fixed-pool reachability complete; no candidate holdout refit')


def verify():
    meta, arrays, x = load_cache()
    selection = read(WORK/'selection.json')
    heldout = read(WORK/'holdout.json')
    assert heldout['chosen'] == selection['chosen'] and heldout['evaluated_once']
    changed = [name for name, digest in protected().items() if meta['protected'][name] != digest]
    shared_engine = 'studies/trader_replication/system.py'
    assert all(name == shared_engine for name in changed), 'legacy/registration/board source changed externally'
    checks = {}
    for name in (selection['chosen'], selection['second']):
        model = read(WORK/f'fit_{name}.json')['model']
        sample = Sample(meta, arrays, x, model['spec'], [])
        s = score_model(model, sample)
        nominations = sample.nominate(s)
        exported = read(WORK/f'picks_{name}.json')
        expected = {meta['days'][int(t)]: [meta['codes'][int(sample.code[r])] for r in rows if r < len(sample.indices)]
                    for t, rows in zip(sample.nights, nominations) if meta['days'][int(t)] >= START}
        assert expected == exported
        assert all(len(items) <= (7 if part == 'shared' else 3) for part, items in model['parts'].items())
        # Replacing future market rows cannot affect any earlier nomination or cooldown.
        cut = meta['train_last']
        prefix = Sample(meta, arrays, x, model['spec'], [], end=cut)
        before = prefix.nominate(score_model(model, prefix))
        assert np.array_equal(nominations[:len(before)], before)
        checks[name] = dict(export_exact=True, inference_prefix_invariant=True,
                            nominations=sum(map(len, exported.values())), nights=len(exported))
    tests = {}
    for group in ('custody', 'martin_luk', 'trader_replication'):
        path = WORK/f'tests_{group}.log'
        content = path.read_text()
        tests[group] = dict(ok=content.rstrip().splitlines()[-1].split(' (', 1)[0] == 'OK', sha256=sha(path),
                            summary=[line for line in content.splitlines() if line.startswith('Ran ')])
    assert all(t['ok'] for t in tests.values()), 'required test group failed'
    write(WORK/'completion.json', dict(complete=True, task='PLAN_F1_CN.md', chosen=selection['chosen'],
        second=selection['second'], candidate_passed=selection['passed'], candidates=len(CANDIDATES),
        holdout_evaluations=1, runner_up_holdout_metrics=False, checks=checks, tests=tests,
        source_hashes=sources(), protected_unchanged=not changed, allowed_shared_engine_changes=changed,
        dataset_digest=meta['dataset_digest'],
        resource_limits=dict(cpu_quota='60%', memory_max='900M', threads=1, processes=1),
        cache_peak_rss_mib=meta['peak_rss_mib'], python=sys.executable,
        network_disabled=True, new_data=False, git_commit=False,
        hook_install='existing secret_guard hooks retained; installer refused to overwrite them',
        artifacts={p.name: sha(p) for p in WORK.iterdir() if p.is_file() and p.suffix == '.json'
                   and p.name != 'completion.json'}))
    log('F1 verification complete')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=('prepare', 'fit', 'evaluate', 'reachability', 'verify'))
    args = parser.parse_args()
    WORK.mkdir(exist_ok=True)
    offline()
    globals()[args.stage]()


if __name__ == '__main__':
    main()
