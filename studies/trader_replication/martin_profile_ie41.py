"""IE41: offline variance reduction, training-only selection, frozen holdout.

OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 .venv/bin/python -m
studies.trader_replication.martin_profile_ie41 --stage fit
"""
import argparse
from collections import Counter
import csv
import hashlib
import json
import math
import os
from pathlib import Path
import resource
import shutil
import sys
import time

import numpy as np

from studies.trader_replication import standard_indicators as standard

ROOT = Path(__file__).resolve().parents[2]
GAP = ROOT / 'studies/trader_replication/reports/gap_review'
WORK = GAP / 'ie41_work'
SOURCE = GAP / 'ie5_work'
OUTPUT = GAP / 'strong_continue_ie41.json'
HALVES = ('2024H1', '2024H2', '2025H1', '2025H2')
NAMES = list(standard.V1_1_NAMES)
SPEC = {s['name']: s for s in standard.SPEC}
WEIGHTS = (0, .5, 1, 1.5, 2, 3)
SETUPS = ('breakout', 'pullback', 'ep')
SEEDS = tuple(range(20261105411, 20261105416))
T0 = time.monotonic()


def half(day):
    return day[:4] + ('H1' if day[5:7] <= '06' else 'H2')


def clean(x):
    if isinstance(x, dict):
        return {str(k): clean(v) for k, v in x.items()}
    if isinstance(x, (list, tuple, np.ndarray)):
        return [clean(v) for v in x]
    if isinstance(x, (float, np.floating)):
        return float(x) if np.isfinite(x) else None
    if isinstance(x, (np.integer, np.bool_)):
        return x.item()
    return x


def write(path, obj):
    temporary = path.with_suffix(path.suffix+'.tmp')
    temporary.write_text(json.dumps(clean(obj), ensure_ascii=False, indent=2, allow_nan=False)+'\n')
    temporary.replace(path)


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        while block := stream.read(1024*1024):
            h.update(block)
    return h.hexdigest()


def capacity(stage):
    size = sum(p.stat().st_size for p in WORK.rglob('*') if p.is_file())
    free = shutil.disk_usage(WORK).free
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024
    if size > 800_000_000 or free < 1_000_000_000 or peak > 900_000_000:
        raise RuntimeError(f'{stage}: work={size}, free={free}, peak={peak}')
    return dict(stage=stage, work_bytes=size, free_bytes=free, peak_rss_bytes=peak)


def log(*args):
    print(f'[{time.monotonic()-T0:.0f}s]', *args, flush=True)


def allowed_write(path):
    p = Path(os.fsdecode(path)).resolve()
    return p.is_relative_to(WORK) or p in (OUTPUT, OUTPUT.with_suffix('.json.tmp'))


def guard():
    def audit(event, values):
        if event in ('socket.connect', 'socket.bind', 'socket.getaddrinfo', 'subprocess.Popen', 'os.system'):
            raise PermissionError('IE41 is offline and has no child processes')
        if event == 'open' and not isinstance(values[0], int):
            p = Path(os.fsdecode(values[0])).resolve()
            if p.name.startswith('RULES') or p.suffix in ('.srt', '.vtt') or p.name in ('trades.csv', 'INTERVIEWS_CORE_CN.md'):
                raise PermissionError('IE41 forbidden source: '+str(p))
            if values[2] & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND):
                if not allowed_write(p):
                    raise PermissionError('IE41 write boundary: '+str(p))
        if event in ('os.remove', 'os.rename', 'os.rmdir', 'os.mkdir'):
            paths = values[:2] if event == 'os.rename' else values[:1]
            if any(not allowed_write(p) for p in paths):
                raise PermissionError('IE41 mutation boundary')
    sys.addaudithook(audit)


def snapshot():
    path = WORK/'protected_before.json'
    if path.exists():
        return verify()
    prior = json.loads((GAP/'ie40_work/inputs_before.json').read_text())
    protected = json.loads((GAP/'ie40_work/protected_before.json').read_text())
    files = set(prior) | set(protected)
    files.update(str(p.relative_to(ROOT)) for p in GAP.glob('strong_continue_ie3[0-9]*') if p.is_file())
    files.update(str(p.relative_to(ROOT)) for p in GAP.glob('strong_continue_ie40*') if p.is_file())
    files.update(str(p.relative_to(ROOT)) for p in GAP.glob('standard_indicators_v1*') if p.is_file())
    files.update(('AGENTS.md', 'studies/AGENTS.md',
                  'studies/martin_luk/notes/PLAN_IE41_CN.md',
                  'studies/martin_luk/notes/PREREG_IE41_CN.md',
                  'studies/martin_luk/notes/PI_FIT_ADVICE_20261105_CN.md',
                  'studies/trader_replication/martin_profile_ie29.py',
                  'studies/trader_replication/martin_profile_ie40.py',
                  'studies/trader_replication/standard_indicators.py',
                  'studies/trader_replication/reports/gap_review/ie40_work/pool_standard_v1_1.npz',
                  'studies/trader_replication/reports/gap_review/ie40_work/real_scores.npy',
                  'data/martin-luk-benchmarks-v1/US.QQQ.csv'))
    # Hash bytes only; forbidden narrative sources are never opened.
    files = {f for f in files if not Path(f).name.startswith('RULES') and Path(f).name != 'trades.csv'
             and Path(f).suffix not in ('.srt', '.vtt') and Path(f).name != 'INTERVIEWS_CORE_CN.md'}
    write(path, {f: sha(ROOT/f) for f in sorted(files)})
    return verify()


def verify():
    protected = json.loads((WORK/'protected_before.json').read_text())
    for name, expected in protected.items():
        if sha(ROOT/name) != expected:
            raise ValueError('protected file changed: '+name)
    return dict(protected_files=len(protected), all_unchanged=True)


def average_ranks(values):
    """One-based average ranks; missing values remain missing."""
    result = np.full(len(values), np.nan)
    good = np.flatnonzero(np.isfinite(values))
    order = good[np.argsort(values[good], kind='stable')]
    if len(order):
        starts = np.r_[0, np.flatnonzero(np.diff(values[order]) != 0)+1]
        stops = np.r_[starts[1:], len(order)]
        result[order] = np.repeat((starts+stops+1)/2, stops-starts)
    return result


def nightly_percentiles(x, slices, binary):
    out = np.full(x.shape, np.nan, np.float32)
    for k in range(len(x)):
        if binary[k]:
            out[k] = x[k]
        else:
            for sl in slices:
                count = np.isfinite(x[k, sl]).sum()
                if count:
                    out[k, sl] = average_ranks(x[k, sl])/count
    return out


class Data:
    """Read only the frozen pool and the four permitted ledger fields."""
    def __init__(self):
        meta = json.loads((SOURCE/'prepared.json').read_text())
        self.cal = meta['days']
        self.cpos = {day: j for j, day in enumerate(self.cal)}
        self.targets = [dict(code=e['code'], day=self.first(e['entry_date']), half=half(e['entry_date']),
                             primary=e['target']['tier'] == 'primary', setup=e['setup']) for e in meta['entries']]
        names = json.loads((GAP/'strong_continue_ie4_frozen.json').read_text())['raw_feature_names']
        pct = np.load(GAP/'ie7_work/full_pct.npy', mmap_mode='r')
        trigger = np.load(GAP/'ie9_work/full_features.npy', mmap_mode='r')
        self.codes, self.slices, self.nights, self.base = [], [], [], []
        offset = 0
        for day, codes in sorted(meta['scope'].items()):
            sl = slice(offset, offset+len(codes))
            offset += len(codes)
            if day < meta['first_signal']:
                continue
            passed = np.ones(len(codes), bool)
            for name, cut in (('h4_history', .6), ('adr20', .7), ('option_volume', .8), ('low20', .5)):
                v = pct[sl, names.index(name)]
                passed &= np.where(np.isfinite(v), v >= cut, name == 'h4_history')
            positions = np.flatnonzero(passed)+sl.start
            start = len(self.codes)
            self.codes.extend(c for c, ok in zip(codes, passed) if ok)
            self.slices.append(slice(start, len(self.codes)))
            self.nights.append(self.cpos[day])
            self.base.extend((np.nan_to_num(trigger[positions, 13], nan=.5)
                              + np.nan_to_num(trigger[positions, 29], nan=.5)).tolist())
        self.n = len(self.codes)
        self.base = np.array(self.base)
        self.codes = np.array(self.codes)
        self.row_day = np.repeat(self.nights, [sl.stop-sl.start for sl in self.slices])
        self.row_half = np.array([half(self.cal[t]) for t in self.row_day])
        self.night_half = np.array([half(self.cal[t]) for t in self.nights])
        self.lookup = {(c, int(t)): i for i, (c, t) in enumerate(zip(self.codes, self.row_day))}
        self.day_slice = dict(zip(self.nights, self.slices))
        self.code_ids = {c: i for i, c in enumerate(dict.fromkeys(self.codes))}
        self.row_code = np.array([self.code_ids[c] for c in self.codes], np.int32)
        width = max(sl.stop-sl.start for sl in self.slices)
        self.pad = np.full((len(self.slices), width), self.n, np.int32)
        for k, sl in enumerate(self.slices):
            self.pad[k, :sl.stop-sl.start] = np.arange(sl.start, sl.stop)
        with np.load(GAP/'ie40_work/pool_standard_v1_1.npz') as z:
            if list(z['names']) != NAMES or z['x'].shape != (117, self.n):
                raise ValueError('frozen pool shape or names changed')
            signature = hashlib.sha256(json.dumps([sha(Path(standard.__file__)),
                sha(Path(__file__).with_name('martin_profile_ie40.py')), NAMES, list(self.codes),
                list(map(int, self.row_day)), self.cal, meta['scope']],
                sort_keys=True, separators=(',', ':')).encode()).hexdigest()
            if str(z['signature']) != signature:
                raise ValueError('frozen pool row order or observable scope changed')
            self.raw = z['x']
        self.pct = nightly_percentiles(self.raw, self.slices, [SPEC[n]['binary'] for n in NAMES])
        self.bins = np.where(np.isfinite(self.pct), np.minimum((np.nan_to_num(self.pct)*3).astype(int), 2), 3)
        self.regime, self.r = self.market()
        self.windows = {}
        self.targets = [t for t in self.targets if t['half'][:4] in ('2024', '2025', '2026')]
        log('pool', self.n, 'nights', len(self.nights), capacity('loaded'))

    def first(self, day):
        return next(i for i, value in enumerate(self.cal) if value >= day)

    def market(self):
        rows = list(csv.DictReader((ROOT/'data/martin-luk-benchmarks-v1/US.QQQ.csv').open()))
        dates = [r['time_key'][:10] for r in rows]
        c, h, l = (np.array([float(r[k]) for r in rows]) for k in ('close', 'high', 'low'))
        e21, e50 = standard.ema(c, 21), standard.ema(c, 50)
        adr = standard.roll(h/l-1, 20)
        distance = (c/e50-1)/adr
        labels = np.where(c <= e50, '弱势', np.where((c > e21) & (e21 > e50), '上升', '回调'))
        pos = {day: k for k, day in enumerate(dates)}
        idx = np.array([pos[self.cal[t]] for t in self.nights])
        cached = np.load(SOURCE/'qqq.npy')
        if not np.allclose(c[idx], cached[self.nights], rtol=1e-10, atol=1e-8):
            raise ValueError('QQQ OHLC and frozen close differ')
        return labels[idx], distance[idx]

    def window(self, t, H=3):
        key = (t['code'], t['day'], H)
        if key not in self.windows:
            self.windows[key] = np.array([self.lookup[(t['code'], j)]
                                         for j in range(t['day']-4-H+1, t['day']+3)
                                         if (t['code'], j) in self.lookup], int)
        return self.windows[key]

    def order(self, scores):
        return self.pad[np.arange(len(self.pad))[:, None],
                        np.argsort(-np.r_[scores, -np.inf][self.pad], axis=1, kind='stable')]

    def replay(self, scores, halves=None, K=3, H=3, slots=None):
        orders = [self.order(s) for s in slots] if slots is not None else [self.order(scores)]
        fallback = self.order(scores) if slots is not None else None
        effective = np.full(self.n, np.inf)
        chosen = np.zeros(self.n, bool)
        available_at = np.zeros(len(self.code_ids), int)
        for night, (day, sl) in enumerate(zip(self.nights, self.slices)):
            if halves is not None and self.night_half[night] not in halves:
                continue
            blocked = available_at[self.row_code[sl]] > night
            if slots is None:
                rows = orders[0][night]
                rows = rows[rows < self.n]
                rows = rows[~blocked[rows-sl.start]]
                effective[rows] = np.arange(1, len(rows)+1)
                selected = rows[:K]
            else:
                lists = []
                for order in orders[:K]:
                    rows = order[night]
                    rows = rows[rows < self.n]
                    lists.append(rows[available_at[self.row_code[rows]] <= night])
                backup = fallback[night]
                backup = backup[backup < self.n]
                backup = backup[available_at[self.row_code[backup]] <= night]
                pointers, seen, sequence = [0]*len(lists), set(), []
                while len(seen) < len(backup):
                    for k, rows in enumerate(lists):
                        while pointers[k] < len(rows) and int(rows[pointers[k]]) in seen:
                            pointers[k] += 1
                        if pointers[k] < len(rows):
                            row = int(rows[pointers[k]])
                            pointers[k] += 1
                        else:
                            row = next((int(r) for r in backup if int(r) not in seen), None)
                        if row is not None:
                            sequence.append(row)
                            seen.add(row)
                effective[sequence] = np.arange(1, len(sequence)+1)
                selected = np.array(sequence[:K], int)
            chosen[selected] = True
            available_at[self.row_code[selected]] = night+max(H, 10)+1
        return chosen, effective

    def metric(self, prediction, targets, halves=None, K=3, H=3):
        chosen, effective = self.replay(prediction['score'], halves, K, H, prediction.get('slots'))
        rows = []
        for t in targets:
            window = self.window(t, H)
            if halves is not None:
                window = window[np.isin(self.row_half[window], list(halves))]
            hit = bool(chosen[window].any())
            best = float(np.min(effective[window])) if len(window) else math.inf
            u = 1/(1+math.exp(min(700., (best-3.5)/2))) if np.isfinite(best) else 0.
            later = np.flatnonzero(chosen & (self.codes == t['code']) & (self.row_day > t['day']+2))
            late_day = int(self.row_day[later[0]]) if len(later) else None
            rows.append(dict(code=t['code'], entry=self.cal[t['day']], half=t['half'], primary=t['primary'],
                             setup=t['setup'], hit=hit, u=u, best_effective_rank=best,
                             in_pool=bool(len(window)), later_day=self.cal[late_day] if late_day is not None else None,
                             later_sessions=late_day-t['day'] if late_day is not None else None,
                             category='命中' if hit else '不在池' if not len(window) else
                             '晚几晚才挑中' if late_day is not None else '在池没挑中'))
        prim = [r for r in rows if r['primary']]
        return dict(hit=sum(r['hit'] for r in prim), n=len(prim), soft=sum(r['u'] for r in prim),
                    all_hit=sum(r['hit'] for r in rows), all_n=len(rows), details=rows)


def shrink_table(bins, positive, mask, q=3):
    """Missing bin has exactly zero contribution, not a learned coefficient."""
    pool = np.bincount(bins[mask & (bins < q)], minlength=q).astype(float)
    his = np.bincount(bins[bins < q], weights=positive[bins < q], minlength=q)
    p = pool/pool.sum() if pool.sum() else pool
    H = his.sum()
    scores = np.zeros(q+1)
    if H:
        ok = p > 0
        scores[:q][ok] = np.log((his[ok]+H/q*p[ok])/(H+H/q)/p[ok])
    return scores


def positive_weights(d, targets, mask):
    y = np.zeros(d.n)
    used = 0
    for t in targets:
        if not t['primary']:
            continue
        rows = [d.lookup[(t['code'], t['day']+w)] for w in (0, 1, 2)
                if (t['code'], t['day']+w) in d.lookup and mask[d.lookup[(t['code'], t['day']+w)]]]
        if rows:
            np.add.at(y, rows, 1/len(rows))
            used += 1
    return y, used


def spearman_groups(raw, mask, count=12):
    n = len(raw)
    corr = np.eye(n)
    for j in range(n):
        for k in range(j):
            good = mask & np.isfinite(raw[j]) & np.isfinite(raw[k])
            if good.sum() < 3:
                value = 0.
            else:
                a, b = average_ranks(raw[j, good]), average_ranks(raw[k, good])
                a -= a.mean()
                b -= b.mean()
                denom = np.linalg.norm(a)*np.linalg.norm(b)
                value = float(a @ b/denom) if denom else 0.
            corr[j, k] = corr[k, j] = value
    groups = [[k] for k in range(n)]
    distance = 1-np.abs(corr)
    while len(groups) > count:
        _, j, k = min((float(distance[np.ix_(a, b)].mean()), j, k)
                      for j, a in enumerate(groups) for k, b in enumerate(groups[:j]))
        groups[k] = sorted(groups[k]+groups[j])
        del groups[j]
    result = []
    for members in sorted(groups, key=lambda v: v[0]):
        center = members[int(np.argmax(np.abs(corr[np.ix_(members, members)]).mean(1)))]
        signs = [1 if corr[k, center] >= 0 else -1 for k in members]
        result.append(dict(members=members, signs=signs, center=center, kind=group_kind(members)))
    return result


def indicator_kind(name):
    family = SPEC[name]['family']
    if name in ('contract3_adr', 'inside_day', 'nr7', 'bollinger_width_percentile252', 'ttm_squeeze_days',
                'h4_coil', 'vcp_contractions', 'base_length', 'high20_days', 'pullback_depth_adr',
                'ema21_retest_count', 'avwap_base_low_adr', 'avwap_base_high_adr',
                'avwap_low252_distance_adr', 'avwap_high50_distance_adr', 'avwap_high252_distance_adr',
                'avwap_gap_distance_adr', 'avwap_earnings_distance_adr', 'avwap_big_gap_adr'):
        return 'B'
    if family in ('trend', 'momentum', 'relative_strength') or name in (
            'new_high252', 'new_high50', 'darvas_breakout', 'over_prior_high_adr', 'gap_today_adr',
            'from_high252_pct', 'from_high20_pct', 'from_high50_adr', 'high50_distance_pct',
            'close_pos', 'weekly_close_position', 'potent_days20', 'h4_momentum', 'h4_stack'):
        return 'M'
    return 'C'


def group_kind(members):
    votes = Counter(indicator_kind(NAMES[k]) for k in members)
    return max(('C', 'M', 'B'), key=lambda name: votes[name])


def factors(pct, groups):
    return np.stack([.5+np.sum(np.nan_to_num(pct[g['members']]-.5)*np.array(g['signs'])[:, None], axis=0)
                     /len(g['members']) for g in groups], axis=1)


def basis(x):
    centered = x-.5
    return np.concatenate((centered, centered*centered), axis=1)


def logit_groups(z, y, slices, mask):
    groups = []
    for sl in slices:
        rows = np.arange(sl.start, sl.stop)
        rows = rows[mask[rows]]
        if len(rows) > 1 and y[rows].sum() > 0:
            groups.append((np.asarray(z[rows], float), y[rows].copy()))
    return groups


def conditional_loss(beta, groups, ridge, derivatives=True):
    value = ridge*float(beta @ beta)/2
    gradient = ridge*beta.copy()
    information = ridge*np.eye(len(beta))
    for x, y in groups:
        s = x @ beta
        maximum = s.max()
        ex = np.exp(s-maximum)
        p = ex/ex.sum()
        mass = y.sum()
        value += mass*(maximum+np.log(ex.sum()))-float(y @ s)
        if derivatives:
            mean = p @ x
            gradient += mass*mean-y @ x
            information += mass*((x.T*p) @ x-np.outer(mean, mean))
    return value, gradient, information


def fixed_ridge(info, df=4):
    eigen = np.maximum(np.linalg.eigvalsh(info), 0)
    rank = int(np.sum(eigen > max(float(eigen.max()), 1)*1e-12))
    target = min(df, rank)
    if target == 0:
        return 1., 0.
    if target == rank:
        return 1e-10, float(np.sum(eigen/(eigen+1e-10)))
    low, high = 0., max(1., float(eigen.sum()))
    for _ in range(80):
        mid = (low+high)/2
        if np.sum(eigen/(eigen+mid)) > target:
            low = mid
        else:
            high = mid
    return high, float(np.sum(eigen/(eigen+high)))


def fit_logit(z, y, slices, mask):
    groups = logit_groups(z, y, slices, mask)
    beta = np.zeros(z.shape[1])
    ridge, df = fixed_ridge(conditional_loss(beta, groups, 0)[2])
    iterations = 0
    for iterations in range(40):
        value, gradient, info = conditional_loss(beta, groups, ridge)
        if np.linalg.norm(gradient, ord=np.inf) < 1e-8:
            break
        step = np.linalg.solve(info, gradient)
        rate = 1.
        while rate > 1e-8 and conditional_loss(beta-rate*step, groups, ridge, False)[0] > value-1e-4*rate*float(gradient @ step):
            rate /= 2
        beta -= rate*step
    value, grad, _ = conditional_loss(beta, groups, ridge)
    if np.linalg.norm(grad, ord=np.inf) > 1e-6:
        raise RuntimeError('conditional logit did not converge')
    return dict(beta=beta.tolist(), ridge=ridge, null_effective_df=df, iterations=iterations,
                gradient_max=float(np.max(np.abs(grad))), loss=value, positive_mass=float(y.sum()),
                training_nights=len(groups))


def predict_logit(z, model):
    return z @ np.array(model['beta'])


def utility(d, prediction, targets, halves):
    chosen, effective = d.replay(prediction['score'], halves, slots=prediction.get('slots'))
    total, hit = 0., 0
    for t in targets:
        if not t['primary']:
            continue
        rows = d.window(t)
        rows = rows[np.isin(d.row_half[rows], list(halves))]
        hit += bool(chosen[rows].any())
        best = float(np.min(effective[rows])) if len(rows) else math.inf
        if np.isfinite(best):
            total += 1/(1+math.exp(min(700., (best-3.5)/2)))
    return total, hit


def fit_g1(d, targets, mask, halves):
    y, learned = positive_weights(d, targets, mask)
    tables = np.stack([shrink_table(b, y, mask) for b in d.bins])
    components = np.take_along_axis(tables, d.bins, axis=1).astype(np.float32)

    def score(model):
        return sum((components[k]*w for k, w in model.items()), np.zeros(d.n, np.float32))

    def val(model):
        return utility(d, dict(score=score(model)), targets, halves)

    model, path, seen = {}, [], set()
    while len(model) < 5:
        trials = []
        for k in range(len(NAMES)):
            if k in model:
                continue
            candidate = {**model, k: 1}
            signature = frozenset(candidate)
            if signature in seen:
                continue
            seen.add(signature)
            trials.append((val(candidate), -k, candidate))
        if not trials:
            break
        value, _, model = max(trials, key=lambda row: row[:2])
        path.append((dict(model), value))
    model, best = max(path, key=lambda row: row[1])
    for _ in range(3):
        changed = False
        for key in list(model):
            for weight in WEIGHTS:
                if weight == model[key]:
                    continue
                candidate = {**model, key: weight}
                value = val(candidate)
                if value > best:
                    model, best, changed = candidate, value, True
        model = {k: w for k, w in model.items() if w}
        for key in list(model):
            for k in range(len(NAMES)):
                if k in model:
                    continue
                candidate = {j: w for j, w in model.items() if j != key}
                candidate[k] = model[key]
                value = val(candidate)
                if value > best:
                    model, best, changed = candidate, value, True
                    break
        if not changed:
            break
    for key in sorted(model, key=lambda k: model[k]):
        candidate = {k: w for k, w in model.items() if k != key}
        if candidate:
            value = val(candidate)
            if value >= best:
                model, best = candidate, value
    result = dict(terms=[dict(index=k, name=NAMES[k], weight=w, table=tables[k]) for k, w in model.items()],
                  learned_events=learned, training_utility=best[0], training_hit=best[1])
    return dict(score=score(model)), result, components


def pool_labels(d):
    path = WORK/'pool_labels.npz'
    if path.exists():
        with np.load(path) as z:
            return z['label'], z['end_day']
    labels, end = np.full(d.n, np.nan), np.full(d.n, -1, int)
    for k, code in enumerate(dict.fromkeys(d.codes)):
        rows = np.flatnonzero(d.codes == code)
        rows = rows[d.row_half[rows] < '2026']
        if not len(rows):
            continue
        with np.load(SOURCE/'stocks'/(code+'.npz')) as z:
            o, h = z['o'], z['h']
        for row in rows:
            t = d.row_day[row]
            finish = t+60
            if finish >= len(d.cal) or half(d.cal[t+1]) != d.row_half[row] or half(d.cal[finish]) != d.row_half[row]:
                continue
            if d.cal[finish] > '2025-12-31' or not np.isfinite(o[t+1]) or o[t+1] <= 0:
                continue
            window = h[t+1:finish+1]
            if np.isfinite(window).all():
                labels[row] = float(window.max()/o[t+1]-1 >= .30)
                end[row] = finish
        if k % 200 == 0:
            capacity('pool_labels')
    np.savez(path, label=labels, end_day=end)
    return labels, end


def fit_pool_leg(d, z, mask):
    label, end = pool_labels(d)
    eligible = mask & np.isfinite(label)
    clusters = Counter((d.codes[r], int(d.row_day[r])//60) for r in np.flatnonzero(eligible))
    weights = np.zeros(d.n)
    for r in np.flatnonzero(eligible):
        weights[r] = label[r]/clusters[(d.codes[r], int(d.row_day[r])//60)]
    model = fit_logit(z, weights, d.slices, eligible)
    model.update(eligible_rows=int(eligible.sum()), positive_rows=int(np.nansum(label[eligible])),
                 clusters=len(clusters), latest_label_end=d.cal[int(end[eligible].max())] if eligible.any() else None,
                 label_source_halves=sorted(set(d.row_half[eligible])))
    return model


def tilt_score(d, parts, a0, a1, r=None):
    r = d.r if r is None else r
    a = np.repeat(np.clip(a0+a1*r, 0, 1), [sl.stop-sl.start for sl in d.slices])
    return parts['C']+(1-a)*parts['M']+a*parts['B']


def optimize_tilt(d, parts, targets, halves, r, constant=False):
    def value(a0, a1):
        return utility(d, dict(score=tilt_score(d, parts, a0, a1, r)), targets, halves)
    point = (.5, 0.)
    best = value(*point)
    steps = (.5, 1.)
    for _ in range(7):
        for _ in range(8):
            choices = [(best, point)]
            for dim in range(1 if constant else 2):
                for sign in (-1, 1):
                    trial = list(point)
                    trial[dim] += sign*steps[dim]
                    if 0 <= trial[0] <= 1 and -2 <= trial[1] <= 2:
                        choices.append((value(*trial), tuple(trial)))
            candidate = max(choices, key=lambda row: row[0])
            if candidate[0] <= best:
                break
            best, point = candidate
        steps = tuple(max(1/64, v/2) for v in steps)
    return dict(a0=point[0], a1=point[1], soft=best[0], hit=best[1])


def permute_regime(r, train_nights, rng):
    result = r.copy()
    result[train_nights] = rng.permutation(result[train_nights])
    return result


def fit_g4(d, z, groups, model, targets, halves, seed, checkpoint):
    beta = np.array(model['beta'])
    parts = {kind: np.zeros(d.n) for kind in ('C', 'M', 'B')}
    for k, group in enumerate(groups):
        parts[group['kind']] += z[:, k]*beta[k]+z[:, k+len(groups)]*beta[k+len(groups)]
    constant = optimize_tilt(d, parts, targets, halves, d.r, constant=True)
    observed = optimize_tilt(d, parts, targets, halves, d.r)
    gain = max(0., observed['soft']-constant['soft'])
    rng = np.random.default_rng(seed)
    train_nights = np.isin(d.night_half, list(halves))
    draws = json.loads(checkpoint.read_text()) if checkpoint.exists() else []
    for j in range(200):
        r = permute_regime(d.r, train_nights, rng)
        if j < len(draws):
            continue
        null_constant = optimize_tilt(d, parts, targets, halves, r, constant=True)
        null = optimize_tilt(d, parts, targets, halves, r)
        draws.append(dict(gain=max(0., null['soft']-null_constant['soft']), a0=null['a0'], a1=null['a1']))
        if (j+1) % 10 == 0:
            write(checkpoint, draws)
            capacity('G4_permutation')
        if (j+1) % 50 == 0:
            log('G4', checkpoint.stem, 'permutations', j+1)
    p = (1+sum(row['gain'] >= gain-1e-12 for row in draws))/201
    adopted = observed if p < .1 else constant
    result = dict(**adopted, raw_a0=observed['a0'], raw_a1=observed['a1'], constant=constant,
                  permutation_p=p, observed_gain=gain, permutation_count=200, seed=seed,
                  regime_supported=p < .1, permutation_gains=[r['gain'] for r in draws])
    return dict(score=tilt_score(d, parts, adopted['a0'], adopted['a1'])), result, parts


def fit_g5(d, x, targets, mask, halves, fallback, seed):
    rng = np.random.default_rng(seed)
    scores, legs = [], []
    for setup in SETUPS:
        members = [t for t in targets if t['setup'] == setup and t['primary']]
        y, learned = positive_weights(d, members, mask)
        keep, path = [], []
        for _ in range(4):
            trials = []
            for k in range(x.shape[1]):
                if k in keep:
                    continue
                columns = keep+[k]
                z = basis(x[:, columns])
                model = fit_logit(z, y, d.slices, mask)
                score = predict_logit(z, model)
                value = utility(d, dict(score=score), members, halves)
                trials.append((value, -k, columns, model))
            value, _, keep, model = max(trials, key=lambda row: row[:2])
            path.append((value, keep, model))
        value, keep, initial = max(path, key=lambda row: row[0])
        z = basis(x[:, keep])
        cluster_keys = list(dict.fromkeys((t['code'], t['half']) for t in members))
        average = np.zeros(d.n)
        draws = []
        for _ in range(30):
            sampled = rng.integers(len(cluster_keys), size=len(cluster_keys)) if cluster_keys else []
            multiplicity = Counter(cluster_keys[j] for j in sampled)
            sample = [t for t in members for _ in range(multiplicity[(t['code'], t['half'])])]
            yy, _ = positive_weights(d, sample, mask)
            fitted = fit_logit(z, yy, d.slices, mask)
            s = predict_logit(z, fitted)
            for sl in d.slices:
                if sl.stop > sl.start:
                    average[sl] += average_ranks(s[sl])/(sl.stop-sl.start)/30
            draws.append(fitted)
        scores.append(average)
        legs.append(dict(setup=setup, factor_indices=keep, learned_events=learned,
                         cluster_count=len(cluster_keys), training_utility=value[0], model=initial, bootstrap=draws))
    return dict(score=fallback['score'], slots=scores), dict(legs=legs, seed=seed, bootstrap_count=30)


def model_fingerprint():
    return {str(p.relative_to(ROOT)): sha(p) for p in (
        Path(__file__), Path(standard.__file__), ROOT/'studies/martin_luk/notes/PLAN_IE41_CN.md',
        ROOT/'studies/martin_luk/notes/PREREG_IE41_CN.md')}


def save_prediction(path, prediction):
    np.savez(path, score=prediction['score'], **{f'slot{k}': s for k, s in enumerate(prediction.get('slots', []))})


def load_prediction(path):
    with np.load(path) as z:
        result = dict(score=z['score'])
        slots = [z[f'slot{k}'] for k in range(3) if f'slot{k}' in z]
        if slots:
            result['slots'] = slots
        return result


def grouped(d, mask, label):
    path = WORK/f'groups_{label}.json'
    if path.exists():
        return json.loads(path.read_text())
    groups = spearman_groups(d.raw, mask)
    write(path, groups)
    return groups


def fit_one(d, targets, heldout, label, candidates):
    halves = set(HALVES)-{heldout}
    train = [t for t in targets if t['half'] in halves]
    test = [t for t in targets if t['half'] == heldout]
    mask = np.isin(d.row_half, list(halves))
    source = model_fingerprint()
    groups = grouped(d, mask, heldout)
    x = factors(d.pct, groups)
    z = basis(x)
    y, learned = positive_weights(d, train, mask)
    shared_path = WORK/f'{label}_{heldout}_G2_model.json'
    if shared_path.exists():
        g2 = json.loads(shared_path.read_text())
    else:
        g2 = fit_logit(z, y, d.slices, mask)
        write(shared_path, g2)
    fallback = dict(score=predict_logit(z, g2))
    output = {}
    for name in candidates:
        path = WORK/f'{label}_{heldout}_{name}.json'
        if path.exists():
            saved = json.loads(path.read_text())
            if saved['fingerprints'] != source:
                raise ValueError('fit source changed: '+str(path))
            output[name] = saved
            continue
        log('fit', label, heldout, name)
        if name == 'G1':
            prediction, model, _ = fit_g1(d, train, mask, halves)
        elif name == 'G2':
            prediction, model = fallback, g2
        elif name == 'G3':
            leg = fit_pool_leg(d, z, mask)
            prediction, model = dict(score=fallback['score']+.3*predict_logit(z, leg)), dict(first=g2, second=leg, mix=.3)
        elif name == 'G4':
            seed = 20261105417+(*HALVES, 'full').index(heldout)+(0 if label == 'real' else int(label.split('_')[-1]))
            prediction, model, _ = fit_g4(d, z, groups, g2, train, halves, seed,
                                         WORK/f'{label}_{heldout}_regime_permutations.json')
        else:
            seed = 20261105418+(*HALVES, 'full').index(heldout)+(0 if label == 'real' else int(label.split('_')[-1]))
            prediction, model = fit_g5(d, x, train, mask, halves, fallback, seed)
        saved = dict(candidate=name, heldout=heldout, train_halves=sorted(halves), train_rows=int(mask.sum()),
                     training=d.metric(prediction, train, halves=halves), learned_events=learned,
                     model=model, groups=groups, fingerprints=source, resources=capacity('fit_'+name))
        if heldout != 'full':
            saved['validation'] = d.metric(prediction, test)
        save_prediction(WORK/f'{label}_{heldout}_{name}_scores.npz', prediction)
        write(path, saved)
        output[name] = saved
        log('done', label, heldout, name, 'train', saved['training']['hit'],
            'CV', saved.get('validation', {}).get('hit'), capacity('done_'+name))
    return output


def summarize_fits(label, candidates):
    result = {}
    for name in candidates:
        folds = [json.loads((WORK/f'{label}_{h}_{name}.json').read_text()) for h in HALVES]
        full = json.loads((WORK/f'{label}_full_{name}.json').read_text())
        result[name] = dict(cv_hit=sum(f['validation']['hit'] for f in folds), cv_n=sum(f['validation']['n'] for f in folds),
                            cv_soft=sum(f['validation']['soft'] for f in folds),
                            cv_all_hit=sum(f['validation']['all_hit'] for f in folds), folds=folds, full=full)
    return result


def fit_all(d):
    for heldout in (*HALVES, 'full'):
        fit_one(d, d.targets, heldout, 'real', ('G1', 'G2', 'G3', 'G4', 'G5'))
    candidates = summarize_fits('real', ('G1', 'G2', 'G3', 'G4', 'G5'))
    candidates['G3']['eligible'] = candidates['G3']['cv_all_hit'] >= candidates['G2']['cv_all_hit']-1
    for name in candidates:
        candidates[name].setdefault('eligible', True)
    selected = min((n for n in candidates if candidates[n]['eligible']),
                   key=lambda n: (-candidates[n]['cv_hit'], -candidates[n]['cv_soft'], n))
    baseline = json.loads((GAP/'strong_continue_ie40.json').read_text())
    b0 = [f['hit'] for f in baseline['fit']['folds']]
    regressions = sum(f['validation']['hit'] < b for f, b in zip(candidates[selected]['folds'], b0))
    threshold = 18 if selected == 'G1' else 19
    selection = dict(selected=selected, selected_without_2026=True, forward=candidates[selected]['cv_hit'] >= threshold and regressions < 2,
                     threshold=threshold, b0_fold_hits=b0, lower_folds=regressions,
                     candidates={n: {k: v for k, v in c.items() if k not in ('folds', 'full')} for n, c in candidates.items()},
                     fingerprints=model_fingerprint())
    path = WORK/'selection.json'
    if path.exists() and json.loads(path.read_text()) != clean(selection):
        raise ValueError('immutable selection changed')
    write(path, selection)
    log('SELECTION_FROZEN', selection)
    return selection


def yearly(metric):
    return {year: dict(hit=sum(r['hit'] for r in metric['details'] if r['primary'] and r['half'].startswith(year)),
                       n=sum(r['primary'] for r in metric['details'] if r['half'].startswith(year)))
            for year in ('2024', '2025', '2026')}


def shuffled_targets(d, seed):
    rng = np.random.default_rng(seed)
    mappings, permutations, result = {}, {}, []
    for target in d.targets:
        if target['half'] not in HALVES:
            continue
        t = dict(target)
        key = (t['code'], t['day'])
        if key not in mappings:
            rows = d.window(t)
            rows = rows[d.row_half[rows] == t['half']]
            if len(rows):
                anchor = min(d.row_day[rows], key=lambda j: (abs(j-t['day']), j))
                if anchor not in permutations:
                    codes = d.codes[d.day_slice[anchor]]
                    permutations[anchor] = dict(zip(codes, rng.permutation(codes)))
                mappings[key] = permutations[anchor][t['code']]
            else:
                mappings[key] = t['code']
        t['code'] = mappings[key]
        result.append(t)
    return result


def cluster_interval(details, seed=20261105419, draws=2000):
    primary = [r for r in details if r['primary']]
    codes = list(dict.fromkeys(r['code'] for r in primary))
    counts = np.array([[sum(r['hit'] for r in primary if r['code'] == c),
                        sum(r['code'] == c for r in primary)] for c in codes])
    rng = np.random.default_rng(seed)
    values = []
    for _ in range(draws):
        sample = counts[rng.integers(len(codes), size=len(codes))].sum(0)
        values.append(float(sample[0]/sample[1]))
    lo, hi = np.quantile(values, [.025, .975])
    return dict(low=lo, high=hi, seed=seed, draws=draws, clusters=len(codes),
                method='stock-cluster bootstrap of fixed out-of-fold predictions; no refit or candidate selection')


def random_diagnostics(d):
    rng = np.random.default_rng(20261105416)
    train = [t for t in d.targets if t['half'] in HALVES]
    draws = []
    for _ in range(30):
        cv_details, cv_four = [], []
        for h in HALVES:
            prediction = dict(score=rng.random(d.n))
            targets = [t for t in train if t['half'] == h]
            cv_details.extend(d.metric(prediction, targets)['details'])
            cv_four.extend(d.metric(prediction, targets, K=2, H=2)['details'])
        prediction = dict(score=rng.random(d.n))
        full = d.metric(prediction, d.targets)
        four = d.metric(prediction, d.targets, K=2, H=2)
        draws.append(dict(cv_hit=sum(r['hit'] for r in cv_details if r['primary']),
                          cv_yearly=yearly(dict(details=cv_details)),
                          cv_four_yearly=yearly(dict(details=cv_four)),
                          full_yearly=yearly(full), four_yearly=yearly(four)))
    hits = [r['cv_hit'] for r in draws]
    return dict(seed=20261105416, draws=draws, cv_mean=float(np.mean(hits)), cv_min=min(hits), cv_max=max(hits),
                yearly_cv_mean={y: float(np.mean([r['cv_yearly'][y]['hit'] for r in draws])) for y in ('2024', '2025')},
                yearly_full_mean={y: float(np.mean([r['full_yearly'][y]['hit'] for r in draws])) for y in ('2024', '2025', '2026')})


def ablations(d, selected, full):
    name, model, groups = selected, full['model'], full['groups']
    prediction = load_prediction(WORK/f'real_full_{name}_scores.npz')
    x = factors(d.pct, groups)
    z = basis(x)
    output = []
    for group_index, group in enumerate(groups):
        pred = dict(score=prediction['score'].copy())
        if name == 'G1':
            for term in model['terms']:
                if term['index'] in group['members']:
                    pred['score'] -= term['weight']*np.array(term['table'])[d.bins[term['index']]]
        elif name in ('G2', 'G3', 'G4'):
            first = model if name == 'G2' else model['first'] if name == 'G3' else json.loads((WORK/'real_full_G2_model.json').read_text())
            beta = np.array(first['beta'])
            contribution = z[:, group_index]*beta[group_index]+z[:, group_index+12]*beta[group_index+12]
            if name == 'G4' and group['kind'] != 'C':
                a = np.repeat(np.clip(model['a0']+model['a1']*d.r, 0, 1), [sl.stop-sl.start for sl in d.slices])
                contribution *= a if group['kind'] == 'B' else 1-a
            if name == 'G3':
                beta = np.array(model['second']['beta'])
                contribution += .3*(z[:, group_index]*beta[group_index]+z[:, group_index+12]*beta[group_index+12])
            pred['score'] -= contribution
        else:
            first = json.loads((WORK/'real_full_G2_model.json').read_text())
            beta = np.array(first['beta'])
            pred['score'] -= z[:, group_index]*beta[group_index]+z[:, group_index+12]*beta[group_index+12]
            pred['slots'] = []
            for leg in model['legs']:
                keep = leg['factor_indices']
                score = np.zeros(d.n)
                for draw in leg['bootstrap']:
                    columns = basis(x[:, keep])
                    b = np.array(draw['beta'])
                    if group_index in keep:
                        k = keep.index(group_index)
                        b[[k, k+len(keep)]] = 0
                    s = columns @ b
                    for sl in d.slices:
                        if sl.stop > sl.start:
                            score[sl] += average_ranks(s[sl])/(sl.stop-sl.start)/30
                pred['slots'].append(score)
        metric = d.metric(pred, d.targets)
        output.append(dict(group=group_index, members=[NAMES[k] for k in group['members']], yearly=yearly(metric)))
    return output


def profile_rows(d, selected, full):
    model, groups = full['model'], full['groups']
    rows = []
    if selected == 'G1':
        for term in model['terms']:
            k = term['index']
            table = np.array(term['table'][:3])
            best = int(np.argmax(table))
            rows.append(dict(name=NAMES[k], members=[NAMES[k]], interval=f'当晚分位第{best+1}档（{best/3:.2f}–{(best+1)/3:.2f}）',
                             weight=term['weight'], scores=table, quote='原话没有'))
        return rows
    models = []
    if selected == 'G5':
        for leg in model['legs']:
            models.append((leg['setup'], leg['factor_indices'], np.mean([r['beta'] for r in leg['bootstrap']], axis=0)))
    else:
        first = model if selected == 'G2' else model['first'] if selected == 'G3' else json.loads((WORK/'real_full_G2_model.json').read_text())
        beta = np.array(first['beta'])
        if selected == 'G3':
            beta += .3*np.array(model['second']['beta'])
        models.append(('', list(range(len(groups))), beta))
    for label, indices, beta in models:
        for j, index in enumerate(indices):
            group = groups[index]
            linear, square = beta[j], beta[j+len(indices)]
            options = [(linear*-.5+square*.25, 0.), (linear*.5+square*.25, 1.)]
            if square < 0:
                peak = .5-linear/(2*square)
                if 0 <= peak <= 1:
                    options.append((linear*(peak-.5)+square*(peak-.5)**2, peak))
            peak = max(options)[1]
            rows.append(dict(name=(label+' ' if label else '')+f'因子{index+1}', group=index, kind=group['kind'],
                             members=[NAMES[k] for k in group['members']], signs=group['signs'], center=NAMES[group['center']],
                             linear=linear, square=square, preferred_factor_value=peak,
                             interval='低位（0附近）' if peak == 0 else '高位（1附近）' if peak == 1 else f'中间段（{peak:.2f}附近）',
                             quote='原话没有'))
    return rows


def evaluate_once(d):
    if OUTPUT.exists():
        result = json.loads(OUTPUT.read_text())
        if result['fingerprints'] != model_fingerprint():
            raise ValueError('formal evaluation source changed')
        return result
    selection = json.loads((WORK/'selection.json').read_text())
    if selection['fingerprints'] != model_fingerprint():
        raise ValueError('source changed after selection')
    selected = selection['selected']
    candidates = summarize_fits('real', ('G1', 'G2', 'G3', 'G4', 'G5'))
    full = candidates[selected]['full']
    prediction = load_prediction(WORK/f'real_full_{selected}_scores.npz')
    formal = d.metric(prediction, d.targets)
    four = d.metric(prediction, d.targets, K=2, H=2)
    cv_details = [r for f in candidates[selected]['folds'] for r in f['validation']['details']]
    ie9 = d.metric(dict(score=d.base), d.targets)
    b0 = d.metric(dict(score=np.load(GAP/'ie40_work/real_scores.npy')), d.targets)
    expected = json.loads((GAP/'strong_continue_ie40.json').read_text())
    if yearly(b0) != expected['yearly'] or yearly(ie9) != expected['ie9']:
        raise ValueError('yardstick replay differs from IE40')
    result = dict(selected=selected, selection=selection, candidates=candidates, yearly=yearly(formal),
                  yearly_cv=yearly(dict(details=cv_details)), four=yearly(four),
                  ie9=yearly(ie9), b0=yearly(b0), details=formal['details'],
                  interval=cluster_interval(cv_details), random=random_diagnostics(d),
                  ablation=ablations(d, selected, full), profile=profile_rows(d, selected, full),
                  regimes={h: dict(Counter(d.regime[d.night_half == h])) for h in HALVES},
                  regime_switches=int(np.sum(d.regime[1:][d.night_half[1:] < '2026'] != d.regime[:-1][d.night_half[1:] < '2026'])),
                  regime_targets={r: sum(t['primary'] and t['half'] in HALVES and
                                        d.regime[min(range(len(d.nights)), key=lambda k: abs(d.nights[k]-t['day']))] == r
                                        for t in d.targets) for r in ('上升', '回调', '弱势')},
                  final_year_evaluated=True, evaluated_2026_candidates=[selected], diagnostics_complete=False,
                  fingerprints=model_fingerprint(), resources=capacity('formal'))
    write(OUTPUT, result)
    log('FINAL_YEAR_ONCE', selected, result['yearly'], 'CV', candidates[selected]['cv_hit'])
    return result


def run_shuffle(d, seed):
    selection = json.loads((WORK/'selection.json').read_text())
    name = selection['selected']
    label = f'shuffle_{seed}'
    targets = shuffled_targets(d, seed)
    for h in (*HALVES, 'full'):
        fit_one(d, targets, h, label, (name,))
    result = summarize_fits(label, (name,))[name]
    result.update(seed=seed, fingerprints=model_fingerprint(), resources=capacity(label))
    write(WORK/(label+'.json'), result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stage', choices=('prepare', 'fit', 'evaluate', 'shuffle', 'finish'), required=True)
    parser.add_argument('--seed', type=int, choices=SEEDS)
    args = parser.parse_args()
    if any(os.environ.get(name) != '1' for name in ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS')):
        parser.error('set all four numerical thread counts to 1')
    WORK.mkdir(exist_ok=True)
    guard()
    log('start', args.stage, capacity('start'))
    snapshot()
    if args.stage == 'prepare':
        d = Data()
        write(WORK/'layout.json', dict(rows=d.n, nights=len(d.nights),
              primary={h: sum(t['primary'] for t in d.targets if t['half'] == h) for h in HALVES},
              regime_nights=dict(Counter(d.regime[d.night_half < '2026'])), resources=capacity('prepare')))
        return
    execution = WORK/'execution.json'
    if execution.exists() and json.loads(execution.read_text()) != model_fingerprint():
        raise ValueError('research source changed after fitting began')
    write(execution, model_fingerprint())
    d = Data()
    if args.stage == 'fit':
        fit_all(d)
    elif args.stage == 'evaluate':
        evaluate_once(d)
    elif args.stage == 'shuffle':
        if args.seed is None:
            parser.error('shuffle requires --seed')
        run_shuffle(d, args.seed)
    else:
        result = json.loads(OUTPUT.read_text())
        result['shuffled'] = [json.loads((WORK/f'shuffle_{seed}.json').read_text()) for seed in SEEDS]
        result.update(diagnostics_complete=True, verification=verify(), resources=capacity('complete'))
        write(OUTPUT, result)
    log('complete', args.stage, verify(), capacity('complete'))


if __name__ == '__main__':
    main()
