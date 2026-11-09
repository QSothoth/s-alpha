"""IE25: seven-night coverage with isolated reuse of the fixed IE23/24 searches."""
import argparse
from collections import defaultdict
from datetime import datetime, timezone
import gc
import hashlib
import json
import mmap
import os
from pathlib import Path
import resource
import shutil
import sys
import time
import types
import warnings

import numpy as np

from studies.trader_replication import martin_continue_ie23 as original_e
from studies.trader_replication import martin_continue_ie24 as original_a


def isolated(source, name):
    """Keep reused function globals private, including when all tests share a process."""
    module = types.ModuleType(name)
    module.__file__ = source.__file__
    module.__package__ = source.__package__
    exec(compile(Path(source.__file__).read_text(), source.__file__, 'exec'), module.__dict__)
    return module


e = isolated(original_e, __name__ + '.equal')
a = isolated(original_a, __name__ + '.adaptive')
a.prior = e
gp = a.gp
ROOT, REPORTS = a.ROOT, a.REPORTS
WORK = REPORTS / 'ie25_work'
PREFIX = 'strong_continue_ie25_'
PLAN = ROOT / 'studies/martin_luk/notes/PLAN_IE25_CN.md'
PREREG = ROOT / 'studies/martin_luk/notes/PREREG_IE25_CN.md'
SOURCE_WORK = REPORTS / 'ie24_work'
HALVES, TOPS, SENTINEL = a.HALVES, a.TOPS, a.SENTINEL
METHODS = ('E', 'A', 'B', 'AB')
OFFSETS = tuple(range(-4, 3))
SHUFFLES = tuple(range(2026112501, 2026112506))
RANDOMS = tuple(range(2026112530, 2026112560))
sha, digest, clean = a.sha, a.digest, e.clean


def path(name):
    return REPORTS / (PREFIX + name + '.json')


def write(name, value):
    dest = path(name)
    temp = dest.with_suffix('.json.tmp')
    temp.write_text(json.dumps(clean(value), ensure_ascii=False, separators=(',', ':'), allow_nan=False) + '\n')
    temp.replace(dest)


def read(name):
    return json.loads(path(name).read_text())


def signature():
    sources = (PLAN, PREREG, Path(__file__), Path(original_e.__file__), Path(original_a.__file__),
               Path(gp.__file__), Path(a.models.__file__), Path(e.lib.__file__))
    return {str(p.relative_to(ROOT)): sha(p) for p in sources}


def capacity(stage):
    used = sum(p.stat().st_size for p in WORK.rglob('*') if p.is_file())
    free = shutil.disk_usage(WORK).free
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024
    memory = {line.split(':')[0]: int(line.split()[1]) * 1024
              for line in Path('/proc/meminfo').read_text().splitlines() if line.startswith(('MemAvailable:', 'SwapFree:'))}
    if free < 1_000_000_000 or used > 800_000_000 or peak > 1_300_000_000:
        raise RuntimeError(f'{stage}: capacity exceeded: free={free}, work={used}, peak={peak}')
    print(stage, 'free_MB', free // 1_000_000, 'work_MB', used // 1_000_000,
          'peak_MB', peak // 1_000_000, flush=True)
    return dict(stage=stage, free_bytes=free, work_bytes=used, peak_rss_bytes=peak,
                memory=memory, utc=datetime.now(timezone.utc).isoformat())


def guard():
    # The upstream audit hook is parameterized only in this private module copy.
    a.guard()


def window(days, entry_date):
    t = days.index(entry_date)
    return [days[t + k] if 0 <= t + k < len(days) else None for k in OFFSETS]


def permitted_rows(days, slices, row_halves, halves):
    allowed = np.isin(row_halves, halves)
    for excluded in (h for h in HALVES if h not in halves):
        positions = [i for i, day in enumerate(days) if e.ie7.half(day) == excluded]
        if positions:
            first, last = positions[0], positions[-1]
            embargo = days[max(0, first - 4):first] + days[last + 1:last + 3]
            for day in embargo:
                sl = slices.get(day)
                if sl is not None:
                    allowed[sl] = False
    return np.flatnonzero(allowed)


class Data(a.Data):
    def __init__(self):
        e.Data.__init__(self, matrix=False)
        self.prepared = json.loads((SOURCE_WORK / 'ie23_prepared.json').read_text())
        self.matrix_path = SOURCE_WORK / 'ie23_ranks.npy'
        self.x = np.load(self.matrix_path, mmap_mode='r')
        if self.x.shape != (len(self.specs), self.n) or self.specs != self.prepared['specs']:
            raise ValueError('IE23 input layout differs')
        self.group = np.empty(self.n, np.int32)
        lookup = {}
        for k, (day, sl) in enumerate(self.slices.items()):
            self.group[sl] = k
            lookup[day] = dict(zip(self.codes[sl], range(sl.start, sl.stop)))
        query = []
        for entry in self.entries:
            entry['nights'] = window(self.base.meta['days'], entry['entry_date'])
            query.append([lookup.get(day, {}).get(entry['code'], -1) for day in entry['nights']])
        self.query = np.asarray(query, np.int32)
        self.current_label, self.current_query = 'real', self.query
        self._engine = None

    def rows_for(self, halves):
        return permitted_rows(self.base.meta['days'], self.slices, self.row_half, halves)

    def scoped_query(self, halves, query=None):
        query = self.current_query if query is None else query
        result = np.full((len(self.entries), len(OFFSETS)), -1, np.int32)
        allowed = np.zeros(self.n, bool)
        allowed[self.rows_for(halves)] = True
        for i in np.flatnonzero(np.isin(self.entry_half, halves)):
            row = np.asarray(query[i])
            good = row >= 0
            good[good] &= allowed[row[good]]
            result[i, good] = row[good]
        return result


def coverage(d, score, halves, permitted=None):
    ranks = d.rank(score)
    best = np.full(len(d.entries), SENTINEL, np.int32)
    allowed = np.ones(d.n, bool)
    if permitted is not None:
        allowed[:] = False
        allowed[d.rows_for(permitted)] = True
    for i in np.flatnonzero(np.isin(d.entry_half, halves)):
        q = d.current_query[i]
        q = q[q >= 0]
        q = q[allowed[q]]
        if len(q):
            best[i] = ranks[q].min()
    return a.summarize_best(d, best, halves)


def maximum(values, axis):
    with warnings.catch_warnings():
        warnings.simplefilter('ignore', RuntimeWarning)
        return np.nanmax(values, axis=axis)


def target_values(values, query):
    sampled = np.where(query[None] >= 0, values[:, np.maximum(query, 0)], np.nan)
    with warnings.catch_warnings():
        warnings.simplefilter('ignore', RuntimeWarning)
        medians = np.nanmedian(sampled, axis=2)
    return sampled, maximum(sampled, 2), medians


def describe(d, halves, query, columns=None, null=True):
    columns = list(range(len(d.specs))) if columns is None else list(columns)
    ids = np.flatnonzero(np.isin(d.entry_half, halves) & d.primary)
    qs = d.scoped_query(halves, query)[ids]
    entry_halves = d.entry_half[ids]
    eligible = {h: int(np.any(qs[entry_halves == h] >= 0, axis=1).sum()) for h in halves}
    shape = (len(columns), len(halves))
    means, centered_diff, pair_diff, pair_win = [np.full(shape, np.nan) for _ in range(4)]
    counts, centers = np.zeros(shape, int), np.full(len(columns), .5)
    baseline_best = np.min(np.where(qs >= 0, d.baseline_ranks[np.maximum(qs, 0)], SENTINEL), axis=1)
    pairs = []
    for local in range(len(ids)):
        if baseline_best[local] <= 5:
            continue
        for q in qs[local]:
            if q >= 0:
                sl = d.slices[d.days[q]]
                front = [r for r in range(sl.start, sl.stop) if d.baseline_ranks[r] <= 5 and r != q]
                pairs.extend((local, int(q), int(r)) for r in front)
    permutations = [d.shuffled(2026112560 + k, d.scoped_query(halves, query), indices=ids)
                    for k in range(20)] if null else []
    null_counts = np.zeros(20, int)
    for start in range(0, len(columns), 64):
        js = columns[start:start + 64]
        values = np.asarray(d.x[js])
        sampled, per_entry, medians = target_values(values, qs)
        means[start:start + len(js)], counts[start:start + len(js)] = e.half_means(
            per_entry, halves, entry_halves, eligible)
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', RuntimeWarning)
            m = np.nanmedian(medians, axis=1)
        centers[start:start + len(js)] = m
        target_center = maximum(-abs(sampled - m[:, None, None]), 2)
        other_entry = np.full_like(per_entry, np.nan)
        for local, row in enumerate(qs):
            other_nights = []
            for q in row:
                if q >= 0:
                    sl = d.slices[d.days[q]]
                    rest = np.arange(sl.start, sl.stop)
                    rest = rest[rest != q]
                    with warnings.catch_warnings():
                        warnings.simplefilter('ignore', RuntimeWarning)
                        other_nights.append(np.nanmean(-abs(values[:, rest] - m[:, None]), axis=1))
            if other_nights:
                other_entry[:, local] = maximum(np.asarray(other_nights), 0)
        centered_diff[start:start + len(js)] = e.half_means(target_center - other_entry, halves, entry_halves, eligible)[0]
        if pairs:
            paired = np.asarray(pairs)
            delta = values[:, paired[:, 1]] - values[:, paired[:, 2]]
            win = np.where(np.isfinite(delta), (delta > 0) + .5 * (delta == 0), np.nan)
            entry_delta, entry_win = np.full_like(per_entry, np.nan), np.full_like(per_entry, np.nan)
            for local in np.unique(paired[:, 0]):
                with warnings.catch_warnings():
                    warnings.simplefilter('ignore', RuntimeWarning)
                    entry_delta[:, local] = np.nanmean(delta[:, paired[:, 0] == local], axis=1)
                    entry_win[:, local] = np.nanmean(win[:, paired[:, 0] == local], axis=1)
            pair_eligible = {h: int(np.isfinite(entry_delta[:, entry_halves == h]).any(0).sum()) for h in halves}
            pair_diff[start:start + len(js)] = e.half_means(entry_delta, halves, entry_halves, pair_eligible, 1)[0]
            pair_win[start:start + len(js)] = e.half_means(entry_win, halves, entry_halves, pair_eligible, 1)[0]
        for k, permuted in enumerate(permutations):
            random_entry = target_values(values, permuted)[1]
            random_half = e.half_means(random_entry, halves, entry_halves, eligible)[0]
            null_counts[k] += int((e.same_side(random_half) & (np.asarray(js) < d.library_n)).sum())
        d.release_pages()
    observed = int((e.same_side(means) & (np.asarray(columns) < d.library_n)).sum())
    return dict(training_halves=list(halves), training_ids=[d.entries[i]['id'] for i in ids], columns=columns,
                means=means, counts=counts, centers=centers, center_diff=centered_diff, pair_diff=pair_diff,
                pair_win=pair_win, pair_count=len(pairs), paired_entries=len({r[0] for r in pairs}),
                same_side_count=observed, null_counts=null_counts,
                clear_excess=bool(observed > max(null_counts)) if null else None)


def group_factors(d, halves):
    label = '_'.join(halves)
    name = 'groups_' + label
    if path(name).exists():
        return read(name)
    capacity(name)
    rows = d.rows_for(halves)
    n = len(rows)
    chunks, used, vector_groups, groups, identical = [], [], [], [], {}
    order = sorted(range(d.library_n), key=lambda j: (d.specs[j]['length'], d.specs[j]['name']))
    for step, j in enumerate(order):
        p = np.nan_to_num(d.x[j, rows], nan=.5)
        vector = e.percentiles(p)[:, 0]
        key = hashlib.sha256(vector.tobytes()).digest()
        vector -= vector.mean()
        norm = np.linalg.norm(vector)
        if not norm:
            groups.append(dict(representative=j, members=[j], correlations=[None], constant=True))
            continue
        if key in identical and identical[key][1] == 1.:
            position, correlation = identical[key]
            groups[position]['members'].append(j)
            groups[position]['correlations'].append(correlation)
            continue
        vector /= norm
        best, position, offset = .7, None, 0
        for block, count in zip(chunks, used):
            correlation = block[:count] @ vector
            if len(correlation) and float(correlation.max()) > best:
                k = int(correlation.argmax())
                best, position = float(correlation[k]), vector_groups[offset + k]
            offset += count
        if position is None:
            if not chunks or used[-1] == 64:
                chunks.append(np.empty((64, n), np.float32))
                used.append(0)
            chunks[-1][used[-1]] = vector
            used[-1] += 1
            position = len(groups)
            vector_groups.append(position)
            groups.append(dict(representative=j, members=[j], correlations=[1.]))
            best = 1.
        else:
            groups[position]['members'].append(j)
            groups[position]['correlations'].append(best)
        identical[key] = position, best
        if step % 32 == 0:
            d.release_pages()
        if step % 500 == 0:
            print(name, step, 'representatives', len(groups), flush=True)
    d.release_pages()
    result = dict(training_halves=list(halves), rows=n, groups=groups, signature=signature())
    write(name, result)
    return result


def select_equal(d, halves):
    name = 'equal_fit_' + d.current_label + '_' + str(a.half_mask(halves))
    if path(name).exists():
        value = read(name)
        if value['signature'] != signature():
            raise ValueError('equal selection source differs')
        return value
    capacity(name + ':start')
    result = e.select(d, halves, d.scoped_query(halves), group_factors(d, halves))
    result['signature'] = signature()
    write(name, result)
    capacity(name + ':done')
    return result


def frozen_coverage(d, models, held):
    return {k: (d.coverage(d.predict(model), d.current_query, [held]) if k == 'E'
                else coverage(d, a.predict(d, model), [held])) for k, model in models.items()}


def score_model(d, method, model):
    return d.predict(model) if method == 'E' else d.rank(a.predict(d, model))


def leave_out(d):
    records = []
    best = {k: np.full(len(d.entries), SENTINEL, np.int32) for k in METHODS}
    for held in HALVES:
        name = d.current_label + '_' + held
        if path(name).exists():
            row = read(name)
            if row['signature'] != signature():
                raise ValueError('saved outer source differs')
        else:
            train = [h for h in HALVES if h != held]
            equal = select_equal(d, train)
            adaptive = a.pipeline(d, train)
            models = dict(E=equal['model'], **adaptive['models'])
            frozen = digest(models)
            write(name + '_frozen', dict(models=models, frozen_sha256=frozen, signature=signature()))
            # Selection has finished; only now may these held entry labels be read.
            held_coverage = frozen_coverage(d, models, held)
            row = dict(held_out=held, models=models, frozen_sha256=frozen,
                       coverage=held_coverage, signature=signature(), runtime=capacity(name + ':done'))
            write(name, row)
        for method, model in row['models'].items():
            dest = REPORTS / (PREFIX + name + '_' + method + '_ranks.npy')
            if not dest.exists():
                np.save(dest, score_model(d, method, model))
            mask = d.entry_half == held
            best[method][mask] = np.asarray(row['coverage'][method]['best'])[mask]
        records.append(row)
        print('OUTER', d.current_label, held, {k: row['coverage'][k]['primary'] for k in METHODS}, flush=True)
    value = dict(records=records, methods={k: a.summarize_best(d, v, HALVES) for k, v in best.items()}, signature=signature())
    write(d.current_label, value)


def initialize(d):
    if path('inputs').exists():
        if read('inputs')['signature'] != signature():
            raise ValueError('IE25 sources changed after initialization')
        return
    capacity('inputs')
    matrix_hash = sha(d.matrix_path)
    if matrix_hash != d.prepared['matrix_sha256']:
        raise ValueError('input matrix digest differs')
    baseline = d.coverage(d.baseline_ranks, d.query, HALVES)
    ceiling = {h: dict(n=int((d.primary & (d.entry_half == h)).sum()),
                      retained=int((d.primary & (d.entry_half == h) & np.any(d.query >= 0, axis=1)).sum())) for h in HALVES}
    expected = {}
    for half in HALVES:
        expected[half] = sum(1 - float(np.prod([1 - min(1., 5 / (d.slices[d.days[q]].stop - d.slices[d.days[q]].start))
                                               for q in d.query[i] if q >= 0]))
                             for i in np.flatnonzero(d.primary & (d.entry_half == half)))
    protected = [Path(original_e.__file__), Path(original_a.__file__), Path(gp.__file__), PLAN,
                 SOURCE_WORK / 'ie23_prepared.json']
    for tag in ('IE23', 'IE24'):
        protected.extend(ROOT / 'studies/martin_luk/notes' / (kind + '_' + tag + '_CN.md') for kind in ('PLAN', 'PREREG'))
    value = dict(signature=signature(), matrix_sha256=matrix_hash, shape=d.x.shape,
                 baseline=baseline, ceiling=ceiling, random_expectation=expected,
                 input_sha256=d.prepared['input_sha256'], dataset_digest=d.prepared['dataset_digest'],
                 protected_sha256={str(p.relative_to(ROOT)): sha(p) for p in protected},
                 entries=d.entries, query=d.query, runtime=capacity('inputs:done'))
    write('inputs', value)
    print('BASELINE', baseline['primary'], baseline['halfyear'], 'ceiling', ceiling, flush=True)


def run_description(d):
    if path('description').exists():
        return
    groups = group_factors(d, HALVES)
    result = describe(d, HALVES, d.query)
    write('description', dict(result, groups=groups, signature=signature()))
    print('DESCRIPTION', result['same_side_count'], result['null_counts'], flush=True)


def run_nested(d):
    for label, seed in [('real', None)] + [('shuffle_' + str(s), s) for s in SHUFFLES]:
        d.set_label(label, seed)
        leave_out(d)


def run_random(d):
    d.set_label('real')
    actual, trials = read('real'), []
    for seed in RANDOMS:
        trials.append(dict(seed=seed, coverage=coverage(d, np.random.default_rng(seed).random(d.n), HALVES)))
    def place(value, values):
        return dict(actual=value, rank=1 + sum(v > value for v in values), ties=sum(v == value for v in values),
                    mean=float(np.mean(values)), minimum=min(values), maximum=max(values), n=len(values))
    placement = {}
    for method in METHODS:
        full = actual['methods'][method]
        placement[method] = {h: place(full['halfyear'][h]['hits']['5'], [t['coverage']['halfyear'][h]['hits']['5'] for t in trials])
                             for h in HALVES}
        placement[method]['combined'] = place(full['primary']['hits']['5'], [t['coverage']['primary']['hits']['5'] for t in trials])
    write('random', dict(trials=trials, placement=placement, signature=signature()))


def run_final(d):
    d.set_label('real')
    equal = select_equal(d, list(HALVES))
    write('final_equal', dict(equal, coverage=d.coverage(d.predict(equal['model']), d.query, HALVES)))
    a.run_final(d)


def judge():
    real, baseline = read('real'), read('inputs')['baseline']
    shuffled = [read('shuffle_' + str(s)) for s in SHUFFLES]
    maximum_shuffle = max(v['methods'][k]['primary']['hits']['5'] for v in shuffled for k in METHODS)
    minimum_baseline = min(v['hits']['5'] / v['n'] for v in baseline['halfyear'].values())
    final = read('final')['methods']
    final_models = dict(E=read('final_equal')['model'], **{k: v['model'] for k, v in final.items()})
    decisions = {}
    for method in METHODS:
        cov = real['methods'][method]
        hits = cov['primary']['hits']['5']
        minimum = min(v['hits']['5'] / v['n'] for v in cov['halfyear'].values())
        valid = hits >= baseline['primary']['hits']['5'] + 3 and minimum >= minimum_baseline
        decisions[method] = dict(hits=hits, minimum_half=minimum, coverage_pass=valid,
                                 shuffle_pass=hits > maximum_shuffle, passed=valid and hits > maximum_shuffle)
    def complexity(method):
        return len(final_models[method]['terms']) if method == 'E' else a.complexity(final_models[method])
    def key(method):
        return -decisions[method]['hits'], complexity(method), METHODS.index(method)
    qualified = [k for k in METHODS if decisions[k]['passed']]
    selected = min(qualified, key=key) if qualified else None
    display = selected or min(METHODS, key=key)
    return dict(methods=decisions, selected=selected, display=display, shuffle_maximum=maximum_shuffle,
                baseline_minimum=minimum_baseline, final_models=final_models, signature=signature())


def stitched_ranks(d, method):
    ranks = np.full(d.n, SENTINEL, np.int32)
    for half in HALVES:
        full = np.load(REPORTS / (PREFIX + 'real_' + half + '_' + method + '_ranks.npy'), mmap_mode='r')
        mask = d.row_half == half
        ranks[mask] = full[mask]
    early = ranks == SENTINEL
    first = np.load(REPORTS / (PREFIX + 'real_' + HALVES[0] + '_' + method + '_ranks.npy'), mmap_mode='r')
    ranks[early] = first[early]
    return ranks


def run_accounts(d):
    d.set_label('real')
    decision = judge()
    write('decision', decision)
    method = decision['display']
    final = score_model(d, method, decision['final_models'][method])
    results = {}
    # Release research caches before the unchanged account adapter loads its panels.
    d._engine = None
    d.release_pages()
    gc.collect()
    for label, ranks in (('final', final), ('loo', stitched_ranks(d, method))):
        name = 'accounts_' + label
        if path(name).exists():
            results[label] = read(name)
            continue
        capacity(name + ':start')
        selected = {}
        for day, sl in d.slices.items():
            rows = np.arange(sl.start, sl.stop)
            order = rows[np.argsort(ranks[rows], kind='stable')][:5]
            selected[day] = [d.codes[q] for q in order]
        accounts = d.base.accounts(selected)
        eligible, failures = e.ie7.eligible(accounts)
        value = dict(method=method, accounts=accounts, eligible=eligible, failures=failures,
                     selected_sha256=digest(selected), signature=signature(), runtime=capacity(name + ':done'))
        write(name, value)
        results[label] = value
    write('accounts', dict(results=results, baseline=e.ie9.read('final')['accounts'], signature=signature()))


def hit_timing(d, ranks_by_half, method):
    days = d.base.meta['days']
    index = {day: k for k, day in enumerate(days)}
    rows = []
    for i, entry in enumerate(d.entries):
        ranks = ranks_by_half[d.entry_half[i]]
        hits = [(day, int(q)) for day, q in zip(entry['nights'], d.query[i]) if q >= 0 and ranks[q] <= 5]
        if not hits:
            continue
        day, q = min(hits)
        buy = index[day] + 1
        t = index[entry['entry_date']]
        with np.load(e.ie9.old.WORK / 'stocks' / (entry['code'] + '.npz')) as z:
            peak = float(maximum(z['h'][t:min(len(days), t + 61)], 0))
            reference = float(z['c'][t])
            price = float(z['o'][buy]) if buy < len(days) else float('nan')
        his_gain = peak / reference - 1
        ratio = (peak / price - 1) / his_gain if price > 0 and his_gain != 0 else None
        rows.append(dict(id=entry['id'], code=entry['code'], entry_date=entry['entry_date'], primary=entry['primary'],
                         half=d.entry_half[i], signal=day, buy_date=days[buy] if buy < len(days) else None,
                         delay_sessions=buy - t, rank=int(ranks[q]), buy_open=price, reference_close=reference,
                         peak=peak, his_gain=his_gain, captured_ratio=ratio))
    def summary(sample):
        delays = [r['delay_sessions'] for r in sample]
        ratios = [r['captured_ratio'] for r in sample if r['captured_ratio'] is not None and np.isfinite(r['captured_ratio'])]
        return dict(n=len(sample), mean_delay=float(np.mean(delays)) if delays else None,
                    median_delay=float(np.median(delays)) if delays else None,
                    late_hits=sum(v > 0 for v in delays),
                    mean_positive_delay=float(np.mean([v for v in delays if v > 0])) if any(v > 0 for v in delays) else None,
                    mean_ratio=float(np.mean(ratios)) if ratios else None, median_ratio=float(np.median(ratios)) if ratios else None)
    return dict(method=method, rows=rows, primary=summary([r for r in rows if r['primary']]), all_entries=summary(rows))


def run_timing(d):
    results = {}
    for method in METHODS:
        ranks = {h: np.load(REPORTS / (PREFIX + 'real_' + h + '_' + method + '_ranks.npy'), mmap_mode='r') for h in HALVES}
        results[method] = hit_timing(d, ranks, method)
    results['IE9'] = hit_timing(d, {h: d.baseline_ranks for h in HALVES}, 'IE9')
    write('timing', dict(methods=results, signature=signature()))


def configure():
    # Private copies retain the upstream algorithms while all mutations target IE25.
    for module in (e, a):
        module.WORK, module.PREFIX, module.PLAN, module.PREREG = WORK, PREFIX, PLAN, PREREG
        module.path, module.write, module.read = path, write, read
        module.capacity, module.signature = capacity, signature
    e.stamp = lambda: dict(signature=signature())
    e.describe, e.group_factors = describe, group_factors
    a.coverage = coverage
    original_cached_fit = a.cached_fit
    # Changing the search seed only: evolve itself and its training objective stay fixed.
    def cached_fit(d, halves, searcher):
        if searcher == 'A':
            return original_cached_fit(d, halves, searcher)
        name = 'fit_' + d.current_label + '_' + str(a.half_mask(halves)) + '_b'
        if path(name).exists():
            value = read(name)
            if value['signature'] != signature():
                raise ValueError('saved formula source differs')
            return value
        before, started = capacity(name + ':start'), time.monotonic()
        checkpoint = read(name + '_checkpoint') if path(name + '_checkpoint').exists() else None
        if checkpoint is not None and checkpoint['signature'] != signature():
            raise ValueError('formula checkpoint differs')
        def save(value):
            write(name + '_checkpoint', dict(value, signature=signature()))
        def progress(row):
            print(name, 'generation', row['generation'], 'fitness', round(row['best'], 6), row['formula'], flush=True)
        value = gp.evolve(d.engine(), d.labels(halves), d.rows_for(halves),
                          2026112500 + a.half_mask(halves), checkpoint, save, progress)
        value.update(training_halves=list(halves), signature=signature(), before=before,
                     after=capacity(name + ':done'), elapsed_seconds=time.monotonic() - started)
        write(name, value)
        return value
    a.cached_fit = cached_fit


configure()


def main(stage):
    WORK.mkdir(exist_ok=True)
    guard()
    before = capacity(stage + ':start')
    d = Data()
    initialize(d)
    stages = dict(describe=run_description, nested=run_nested, random=run_random, final=run_final,
                  accounts=run_accounts, timing=run_timing)
    stages[stage](d)
    write('runtime_' + stage, dict(before=before, after=capacity(stage + ':done'), signature=signature()))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=('describe', 'nested', 'random', 'final', 'accounts', 'timing'))
    main(parser.parse_args().stage)
