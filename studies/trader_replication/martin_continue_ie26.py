"""IE26: three positive evenings, episode controls and budgeted nested ranking."""
import argparse
from collections import defaultdict
from datetime import datetime, timezone
from functools import lru_cache
import gc
import json
import os
from pathlib import Path
import resource
import shutil
import sys
import time
import warnings

import numpy as np

from studies.trader_replication import martin_continue_ie25 as original

p = original.isolated(original, __name__ + '.upstream')
e, a = p.e, p.a
ROOT, REPORTS = p.ROOT, p.REPORTS
WORK = REPORTS / 'ie26_work'
PREFIX = 'strong_continue_ie26_'
PLAN = ROOT / 'studies/martin_luk/notes/PLAN_IE26_CN.md'
PREREG = ROOT / 'studies/martin_luk/notes/PREREG_IE26_CN.md'
YARDSTICK = ROOT / 'studies/martin_luk/notes/YARDSTICK_BUDGET_CN.md'
HALVES, SENTINEL = p.HALVES, p.SENTINEL
METHODS, BUDGETS = ('E', 'A'), (2, 3, 4)
HOLD, POSITIVE = 10, slice(4, 7)
SHUFFLES = tuple(range(2026112601, 2026112606))
NULL_SEEDS = tuple(range(2026112660, 2026112680))
RANDOM_SEED, RANDOM_TRIALS = 2026110401, 30
sha, digest, clean = p.sha, p.digest, p.clean


def path(name):
    return REPORTS / (PREFIX + name + '.json')


def write(name, value):
    dest = path(name)
    temp = dest.with_suffix('.json.tmp')
    temp.write_text(json.dumps(clean(value), ensure_ascii=False, separators=(',', ':'), allow_nan=False) + '\n')
    temp.replace(dest)


def read(name):
    return json.loads(path(name).read_text())


@lru_cache(maxsize=1)
def signature():
    sources = (PLAN, PREREG, YARDSTICK, Path(__file__), Path(original.__file__),
               Path(original.original_e.__file__), Path(original.original_a.__file__),
               Path(a.models.__file__), Path(e.lib.__file__),
               ROOT / 'studies/trader_replication/martin_budget_metric.py')
    return {str(f.relative_to(ROOT)): sha(f) for f in sources}


def capacity(stage):
    used = sum(f.stat().st_size for f in WORK.rglob('*') if f.is_file())
    free = shutil.disk_usage(WORK).free
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024
    memory = {s.split(':')[0]: int(s.split()[1]) * 1024 for s in Path('/proc/meminfo').read_text().splitlines()
              if s.startswith(('MemAvailable:', 'SwapFree:'))}
    if free < 1_000_000_000 or used > 800_000_000 or peak > 1_300_000_000:
        raise RuntimeError(f'{stage}: capacity exceeded: free={free}, work={used}, peak={peak}')
    print(stage, 'free_MB', free // 1_000_000, 'work_MB', used // 1_000_000,
          'peak_MB', peak // 1_000_000, flush=True)
    return dict(stage=stage, free_bytes=free, work_bytes=used, peak_rss_bytes=peak,
                memory=memory, utc=datetime.now(timezone.utc).isoformat())


def guard():
    def allowed(value):
        f = Path(os.fsdecode(value)).resolve()
        return f.is_relative_to(WORK.resolve()) or (f.parent == REPORTS.resolve() and f.name.startswith(PREFIX))

    def audit(event, args):
        if event == 'open':
            value, _, flags = args
            if isinstance(value, int):
                return
            f = Path(os.fsdecode(value))
            if flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND):
                if not allowed(value):
                    raise PermissionError('IE26 write boundary: ' + str(f))
            elif (f.name.startswith('RULES') or f.suffix in ('.srt', '.vtt') or
                  f.name in ('trades.csv', 'INTERVIEWS_CORE_CN.md', 'PLAN_IE_CN.md')):
                raise PermissionError('IE26 excludes human rules and ledger remarks')
        if event in ('socket.connect', 'socket.bind', 'os.system', 'subprocess.Popen'):
            raise PermissionError('IE26 offline single process')
        if event in ('os.remove', 'os.rename', 'os.rmdir', 'os.mkdir'):
            values = args[:2] if event == 'os.rename' else args[:1]
            if any(not allowed(v) for v in values):
                raise PermissionError('IE26 mutation boundary')
    sys.addaudithook(audit)


class Data(p.Data):
    def __init__(self):
        super().__init__()
        self.lookup = {day: dict(zip(self.codes[sl], range(sl.start, sl.stop))) for day, sl in self.slices.items()}
        self.code_index = {code: k for k, code in enumerate(dict.fromkeys(self.codes))}
        self.code_ids = np.asarray([self.code_index[c] for c in self.codes], np.int32)
        self.baseline_selected = picks(self, self.baseline_ranks)

    def labels(self, halves, row_halves=None):
        allowed = np.zeros(self.n, bool)
        allowed[self.rows_for(halves if row_halves is None else row_halves)] = True
        result = {}
        for half in halves:
            records = []
            for i in np.flatnonzero(self.primary & (self.entry_half == half)):
                q = np.asarray(self.current_query[i])[POSITIVE]
                q = q[q >= 0]
                records.append(q[allowed[q]])
            result[half] = records
        return result


def picks(d, ranks, k=3, permitted=None):
    """Skip held names, filling the new-name budget farther down the same ranking."""
    selected = np.zeros(d.n, bool)
    last = np.full(len(d.code_index), -HOLD - 1, np.int32)
    allowed = None
    if permitted is not None:
        allowed = np.zeros(d.n, bool)
        allowed[d.rows_for(permitted)] = True
    for night, sl in enumerate(d.slices.values()):
        if sl.start == sl.stop or (allowed is not None and not allowed[sl.start]):
            continue
        order = np.argsort(ranks[sl], kind='stable') + sl.start
        count = 0
        for q in order:
            code = d.code_ids[q]
            if night - last[code] <= HOLD:
                continue
            selected[q], last[code] = True, night
            count += 1
            if count == k:
                break
    return selected


def summarize(d, hit, halves, first=None):
    hit = np.asarray(hit, bool)
    included = np.isin(d.entry_half, halves)
    def part(mask):
        return dict(n=int(mask.sum()), hit=int((hit & mask).sum()))
    result = dict(primary=part(included & d.primary), all_entries=part(included),
                  halfyear={h: part(included & d.primary & (d.entry_half == h)) for h in halves},
                  all_halfyear={h: part(included & (d.entry_half == h)) for h in halves}, hit=hit.tolist())
    if first is not None:
        result['first_rows'] = np.asarray(first).tolist()
    return result


def coverage(d, ranks, halves, query=None, permitted=None, k=3, selected=None):
    query = d.current_query if query is None else query
    selected = picks(d, ranks, k, permitted) if selected is None else selected
    hit, first = np.zeros(len(d.entries), bool), np.full(len(d.entries), -1, np.int32)
    for i in np.flatnonzero(np.isin(d.entry_half, halves)):
        q = np.asarray(query[i])
        q = q[q >= 0]
        found = q[selected[q]]
        if len(found):
            hit[i], first[i] = True, found[0]
    return summarize(d, hit, halves, first)


def ranks_for(d, method, model):
    value = d.predict(model) if method == 'E' else d.rank(a.predict_a(d, model))
    d.release_pages()
    return value


def episode_queries(d, ids, seed, halves):
    """One random stock on evening zero, followed across the next two evenings."""
    rng = np.random.default_rng(seed)
    out = np.full((len(ids), 3), -1, np.int32)
    allowed = np.zeros(d.n, bool)
    allowed[d.rows_for(halves)] = True
    draws = {}
    for local, i in enumerate(ids):
        entry = d.entries[i]
        nights = entry['nights'][POSITIVE]
        sl = d.slices.get(nights[0], slice(0, 0))
        if sl.start == sl.stop or not allowed[sl.start]:
            continue
        key = entry['code'], entry['entry_date']
        if key not in draws:
            draws[key] = d.codes[int(rng.integers(sl.start, sl.stop))]
        code = draws[key]
        for w, day in enumerate(nights):
            q = d.lookup.get(day, {}).get(code, -1)
            if q >= 0 and allowed[q]:
                out[local, w] = q
    return out


def samples(values, query):
    raw = values[:, np.maximum(query, 0)]
    available = (query[None] >= 0) & np.isfinite(raw)
    return np.where(available, raw, .5), available


def sample_summary(sampled, available, query, entry_halves, halves):
    per_entry = np.concatenate((sampled, sampled.mean(2, keepdims=True)), axis=2)
    valid = np.concatenate((available, available.any(2, keepdims=True)), axis=2)
    pool = np.column_stack((query >= 0, (query >= 0).any(1)))
    means = np.full((4, len(sampled), len(halves)), np.nan)
    counts = np.zeros(means.shape, int)
    for h, half in enumerate(halves):
        mask = entry_halves == half
        if not mask.any():
            continue
        for w in range(4):
            count = valid[:, mask, w].sum(1)
            enough = (count >= 2) & (count >= pool[mask, w].sum() / 2)
            counts[w, :, h] = count
            means[w, :, h] = np.where(enough, per_entry[:, mask, w].mean(1), np.nan)
    return means, counts


def average(value, axis):
    with warnings.catch_warnings():
        warnings.simplefilter('ignore', RuntimeWarning)
        return np.nanmean(value, axis=axis)


def describe(d, halves, query, columns=None, null=True):
    columns = list(range(len(d.specs))) if columns is None else list(columns)
    ids = np.flatnonzero(np.isin(d.entry_half, halves) & d.primary)
    qs = d.scoped_query(halves, query)[ids, POSITIVE]
    entry_halves = d.entry_half[ids]
    shape = (len(columns), len(halves))
    offset_means, offset_counts = np.full((4, *shape), np.nan), np.zeros((4, *shape), int)
    centers = np.full(len(columns), .5)
    center_diff, pair_diff, pair_win = [np.full(shape, np.nan) for _ in range(3)]
    permutations = [episode_queries(d, ids, seed, halves) for seed in NULL_SEEDS] if null else []
    null_counts = np.zeros((len(permutations), 4), int)
    library_null_counts = np.zeros_like(null_counts)
    null_means = np.zeros((4, *shape)) if null else None
    pair_records = []
    for local, row in enumerate(qs):
        for w, q in enumerate(row):
            if q < 0:
                continue
            sl = d.slices[d.days[q]]
            front = np.flatnonzero(d.baseline_selected[sl]) + sl.start
            pair_records.extend((local, w, int(q), int(other)) for other in front if other != q)
    eligible = {h: int((qs[entry_halves == h] >= 0).any(1).sum()) for h in halves}
    for start in range(0, len(columns), 64):
        js = columns[start:start + 64]
        values = np.asarray(d.x[js])
        sampled, available = samples(values, qs)
        means, counts = sample_summary(sampled, available, qs, entry_halves, halves)
        offset_means[:, start:start + len(js)] = means
        offset_counts[:, start:start + len(js)] = counts
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', RuntimeWarning)
            medians = np.nanmedian(np.where(available, sampled, np.nan), axis=2)
            m = np.nanmedian(medians, axis=1)
        m = np.nan_to_num(m, nan=.5)
        centers[start:start + len(js)] = m
        centered = np.zeros_like(sampled)
        for local, row in enumerate(qs):
            for w, q in enumerate(row):
                if q < 0:
                    continue
                sl = d.slices[d.days[q]]
                rest = np.arange(sl.start, sl.stop)
                rest = rest[rest != q]
                if len(rest):
                    other = np.nan_to_num(values[:, rest], nan=.5)
                    centered[:, local, w] = -abs(sampled[:, local, w] - m) + abs(other - m[:, None]).mean(1)
        center_diff[start:start + len(js)] = e.half_means(centered.mean(2), halves, entry_halves, eligible)[0]
        if pair_records:
            pairs = np.asarray(pair_records)
            delta = np.nan_to_num(values[:, pairs[:, 2]], nan=.5) - np.nan_to_num(values[:, pairs[:, 3]], nan=.5)
            win = (delta > 0) + .5 * (delta == 0)
            night_delta, night_win = np.full_like(sampled, np.nan), np.full_like(sampled, np.nan)
            for local, w in dict.fromkeys(map(tuple, pairs[:, :2])):
                mask = (pairs[:, 0] == local) & (pairs[:, 1] == w)
                night_delta[:, local, w] = delta[:, mask].mean(1)
                night_win[:, local, w] = win[:, mask].mean(1)
            per_delta, per_win = average(night_delta, 2), average(night_win, 2)
            pair_eligible = {h: int(np.isfinite(per_delta[:, entry_halves == h]).any(0).sum()) for h in halves}
            pair_diff[start:start + len(js)] = e.half_means(per_delta, halves, entry_halves, pair_eligible, 1)[0]
            pair_win[start:start + len(js)] = e.half_means(per_win, halves, entry_halves, pair_eligible, 1)[0]
        for k, permuted in enumerate(permutations):
            random_sampled, random_available = samples(values, permuted)
            random_mean = sample_summary(random_sampled, random_available, permuted, entry_halves, halves)[0]
            null_means[:, start:start + len(js)] += random_mean / len(permutations)
            for w in range(4):
                same = e.same_side(random_mean[w])
                null_counts[k, w] += int(same.sum())
                library_null_counts[k, w] += int((same & (np.asarray(js) < d.library_n)).sum())
        d.release_pages()
    observed = [int(e.same_side(v).sum()) for v in offset_means]
    library = np.asarray(columns) < d.library_n
    library_counts = [int((e.same_side(v) & library).sum()) for v in offset_means]
    return dict(training_halves=list(halves), training_ids=[d.entries[i]['id'] for i in ids], columns=columns,
                means=offset_means[3], counts=offset_counts[3], offset_means=offset_means,
                offset_counts=offset_counts, centers=centers, center_diff=center_diff, pair_diff=pair_diff,
                pair_win=pair_win, pair_count=len(pair_records), paired_entries=len({r[0] for r in pair_records}),
                same_side_count=observed, library_same_side_count=library_counts,
                null_counts=null_counts, library_null_counts=library_null_counts, null_means=null_means,
                clear_excess=[bool(observed[w] > max(null_counts[:, w])) for w in range(4)] if null else None)


def refit_equal(d, model, halves):
    return e.refit(d, model, halves, d.scoped_query(halves))


def diagnostic_loo(d, method, model, halves=HALVES):
    hit, first, records = np.zeros(len(d.entries), bool), np.full(len(d.entries), -1, np.int32), {}
    for held in halves:
        train = [h for h in halves if h != held]
        fitted = refit_equal(d, model, train) if method == 'E' else a.fit_a(d, train, fixed=model)
        c = coverage(d, ranks_for(d, method, fitted), [held], permitted=halves if len(halves) < len(HALVES) else None)
        mask = d.entry_half == held
        hit[mask], first[mask] = np.asarray(c['hit'])[mask], np.asarray(c['first_rows'])[mask]
        records[held] = fitted
    return dict(coverage=summarize(d, hit, halves, first), fitted=records)


def deletion_trials(method, model):
    if method == 'E':
        for k, term in enumerate(model['terms']):
            yield dict(feature=term['j'], term=term), dict(model, baseline=False,
                terms=model['terms'][:k] + model['terms'][k + 1:])
    else:
        for j in model['features']:
            yield dict(feature=j), dict(model, features=[x for x in model['features'] if x != j])


def ablate(d, method, model, halves):
    current, history = model, []
    before = diagnostic_loo(d, method, current, halves)
    initial = before
    while True:
        accepted = False
        for item, trial in deletion_trials(method, current):
            after = diagnostic_loo(d, method, trial, halves)
            accepted = after['coverage']['primary']['hit'] >= before['coverage']['primary']['hit']
            history.append(dict(item=item, before=before['coverage'], after=after['coverage'], accepted=accepted))
            if accepted:
                current, before = trial, after
                break
        if not accepted:
            break
    fitted = refit_equal(d, current, halves) if method == 'E' else a.fit_a(d, halves, fixed=current)
    return dict(initial_model=model, model=fitted, before=initial['coverage'], after=before['coverage'],
                diagnostic_models=before['fitted'], history=history, selection_biased_diagnostic=True)


def select_equal(d, halves):
    name = 'equal_fit_' + d.current_label + '_' + str(a.half_mask(halves))
    if path(name).exists():
        value = read(name)
        if value['signature'] != signature():
            raise ValueError('saved equal source differs')
        return value
    before = capacity(name + ':start')
    desc = describe(d, halves, d.current_query)
    groups = p.group_factors(d, halves)
    candidates = []
    for order, model in enumerate(e.candidates(d, desc, groups)):
        c = coverage(d, ranks_for(d, 'E', model), halves, permitted=halves)
        candidates.append(dict(model=model, coverage=c, order=order))
    chosen = max(candidates, key=lambda v: (v['coverage']['primary']['hit'], -len(v['model']['terms']), -v['order']))
    ablation = ablate(d, 'E', chosen['model'], halves)
    value = dict(training_halves=list(halves), description=desc, candidates=candidates,
                 selected=chosen['model'], ablation=ablation, model=ablation['model'], signature=signature(),
                 before=before, after=capacity(name + ':done'))
    write(name, value)
    return value


def pipeline_a(d, halves):
    name = 'pipeline_' + d.current_label + '_' + str(a.half_mask(halves))
    if path(name).exists():
        value = read(name)
        if value['signature'] != signature():
            raise ValueError('saved model pipeline source differs')
        return value
    inner = []
    for held in halves:
        fit = a.cached_fit(d, [h for h in halves if h != held], 'A')
        for order, model in enumerate(fit['candidates']):
            c = coverage(d, ranks_for(d, 'A', model), [held], permitted=halves)
            inner.append(dict(held=held, key=[model['family'], model['level']], coverage=c['primary'],
                              features=model['features'], order=order))
    fit = a.cached_fit(d, halves, 'A')
    choices = []
    for order, model in enumerate(fit['candidates']):
        rows = [r for r in inner if r['key'] == [model['family'], model['level']]]
        choices.append(dict(model=model, hit=sum(r['coverage']['hit'] for r in rows),
                            columns=sum(len(r['features']) for r in rows), order=order))
    chosen = max(choices, key=lambda v: (v['hit'], -v['columns'],
        -(v['model']['level'] if v['model']['family'] == 'boost' else 0),
        int(v['model']['family'] == 'logit'), -v['order']))
    value = dict(training_halves=list(halves), inner=inner, choices=choices,
                 model=chosen['model'], selected=chosen, signature=signature())
    write(name, value)
    return value


def rank_path(label, held, method):
    return WORK / ('ranks_' + label + '_' + held + '_' + method + '.npy')


def leave_out(d):
    rows = []
    totals = {method: np.zeros(len(d.entries), bool) for method in METHODS}
    firsts = {method: np.full(len(d.entries), -1, np.int32) for method in METHODS}
    for held in HALVES:
        name = d.current_label + '_' + held
        if path(name).exists():
            row = read(name)
            if row['signature'] != signature():
                raise ValueError('saved outer source differs')
        else:
            train = [h for h in HALVES if h != held]
            capacity(name + ':start')
            models = dict(E=select_equal(d, train)['model'], A=pipeline_a(d, train)['model'])
            frozen = dict(models=models, frozen_sha256=digest(models), signature=signature())
            write(name + '_frozen', frozen)
            results = {}
            for method, model in models.items():
                ranks = ranks_for(d, method, model)
                np.save(rank_path(d.current_label, held, method), ranks)
                results[method] = coverage(d, ranks, [held])
            row = dict(held_out=held, coverage=results, **frozen, runtime=capacity(name + ':done'))
            write(name, row)
        for method, model in row['models'].items():
            if not rank_path(d.current_label, held, method).exists():
                np.save(rank_path(d.current_label, held, method), ranks_for(d, method, model))
            mask = d.entry_half == held
            totals[method][mask] = np.asarray(row['coverage'][method]['hit'])[mask]
            firsts[method][mask] = np.asarray(row['coverage'][method]['first_rows'])[mask]
        rows.append(row)
        print('OUTER', d.current_label, held, {k: row['coverage'][k]['primary'] for k in METHODS}, flush=True)
    result = dict(records=rows, methods={k: summarize(d, totals[k], HALVES, firsts[k]) for k in METHODS}, signature=signature())
    write(d.current_label, result)
    return result


def winner_flags(d):
    dest = WORK / 'winners.npy'
    if dest.exists():
        return np.load(dest, mmap_mode='r')
    days = d.base.meta['days']
    positions = {day: k for k, day in enumerate(days)}
    bycode = defaultdict(list)
    for q, (code, day) in enumerate(zip(d.codes, d.days)):
        bycode[code].append((q, positions[day] + 1))
    flags = np.full(d.n, -1, np.int8)
    for code, rows in bycode.items():
        with np.load(e.ie9.old.WORK / 'stocks' / (code + '.npz')) as z:
            opening, high = z['o'], z['h']
        for q, i in rows:
            if i >= len(days) - 1 or not np.isfinite(opening[i]) or opening[i] <= 0:
                continue
            with warnings.catch_warnings():
                warnings.simplefilter('ignore', RuntimeWarning)
                peak = np.nanmax(high[i:min(len(days), i + 60)])
            flags[q] = bool(peak / opening[i] - 1 >= .3)
    np.save(dest, flags)
    return flags


def precision(flags, selected):
    values = flags[selected]
    values = values[values >= 0]
    return dict(rate=float(values.mean()) if len(values) else None, n=len(values), winners=int(values.sum()))


def stitched_ranks(d, method, label='real', old=False):
    result = np.full(d.n, SENTINEL, np.int32)
    first = None
    for half in HALVES:
        dest = (REPORTS / ('strong_continue_ie25_real_' + half + '_' + method + '_ranks.npy')
                if old else rank_path(label, half, method))
        ranks = np.load(dest, mmap_mode='r')
        if first is None:
            first = ranks
        mask = d.row_half == half
        result[mask] = ranks[mask]
    early = result == SENTINEL
    result[early] = first[early]
    return result


def random_controls(d, flags):
    rng = np.random.default_rng(RANDOM_SEED)
    trials = []
    for trial in range(RANDOM_TRIALS):
        ranks = np.empty(d.n, np.int32)
        for sl in d.slices.values():
            ranks[sl] = rng.permutation(sl.stop - sl.start) + 1
        budgets = {}
        for k in BUDGETS:
            selected = picks(d, ranks, k)
            budgets[str(k)] = dict(coverage=coverage(d, ranks, HALVES, k=k, selected=selected),
                                   precision=precision(flags, selected))
        trials.append(dict(trial=trial + 1, budgets=budgets))
    return trials


def initialize(d):
    if path('inputs').exists():
        if read('inputs')['signature'] != signature():
            raise ValueError('IE26 sources changed after initialization')
        return
    before = capacity('inputs')
    assert list(d.slices) == sorted(d.slices)
    matrix_hash = sha(d.matrix_path)
    if matrix_hash != d.prepared['matrix_sha256']:
        raise ValueError('input matrix digest differs')
    flags = winner_flags(d)
    baseline = {}
    old = stitched_ranks(d, 'E', old=True)
    for k in BUDGETS:
        selected = picks(d, d.baseline_ranks, k)
        old_selected = picks(d, old, k)
        baseline[str(k)] = dict(IE9=dict(coverage=coverage(d, d.baseline_ranks, HALVES, k=k, selected=selected),
                                        precision=precision(flags, selected)),
                               IE25_E=dict(coverage=coverage(d, old, HALVES, k=k, selected=old_selected),
                                           precision=precision(flags, old_selected)))
    trials = random_controls(d, flags)
    random_hit = [v['budgets']['3']['coverage']['primary']['hit'] for v in trials]
    assert baseline['3']['IE9']['coverage']['primary']['hit'] == 16
    assert baseline['3']['IE25_E']['coverage']['primary']['hit'] == 18
    assert (min(random_hit), max(random_hit)) == (10, 20) and round(float(np.mean(random_hit)), 1) == 14.2
    protected = {Path(original.__file__), Path(original.original_e.__file__), Path(original.original_a.__file__)}
    for stage in ('23', '24', '25'):
        for kind in ('PLAN', 'PREREG'):
            protected.add(ROOT / 'studies/martin_luk/notes' / (kind + '_IE' + stage + '_CN.md'))
        protected.update(f for f in REPORTS.glob('strong_continue_ie' + stage + '_*') if f.is_file())
    protected.add(p.SOURCE_WORK / 'ie23_prepared.json')
    value = dict(signature=signature(), matrix_sha256=matrix_hash, shape=d.x.shape,
                 baseline=baseline, pool_precision=precision(flags, np.ones(d.n, bool)),
                 input_sha256=d.prepared['input_sha256'],
                 protected_sha256={str(f.relative_to(ROOT)): sha(f) for f in sorted(protected)},
                 entries=d.entries, query=d.query, dataset_digest=d.prepared['dataset_digest'],
                 before=before, after=capacity('inputs:done'))
    write('inputs', value)
    write('random', dict(seed=RANDOM_SEED, trials=trials, signature=signature()))
    print('BASELINE', {k: v['coverage']['primary'] for k, v in baseline['3'].items()},
          'random', float(np.mean(random_hit)), min(random_hit), max(random_hit),
          'pool_precision', value['pool_precision'], flush=True)


def run_description(d):
    if path('description').exists():
        return
    value = describe(d, list(HALVES), d.query)
    value['groups'] = p.group_factors(d, list(HALVES))
    value['signature'] = signature()
    write('description', value)
    print('DESCRIPTION', value['same_side_count'], 'null maxima', value['null_counts'].max(0).tolist(), flush=True)


def run_nested(d, seed=None):
    labels = [('real', None)] + [('shuffle_' + str(s), s) for s in SHUFFLES]
    if seed is not None:
        labels = [(label, s) for label, s in labels if s == seed]
    for label, seed in labels:
        d.set_label(label, seed)
        leave_out(d)


def run_final(d):
    d.set_label('real')
    for method in METHODS:
        name = 'final_' + method
        if path(name).exists():
            continue
        model = select_equal(d, list(HALVES))['model'] if method == 'E' else pipeline_a(d, list(HALVES))['model']
        result = ablate(d, method, model, list(HALVES))
        result['signature'] = signature()
        write(name, result)
        print('FINAL', method, result['after']['primary'], flush=True)


def fold_budget(d, method, k, flags):
    hit, first = np.zeros(len(d.entries), bool), np.full(len(d.entries), -1, np.int32)
    selected_by_signal_half = np.zeros(d.n, bool)
    for held in HALVES:
        ranks = np.load(rank_path('real', held, method), mmap_mode='r')
        selected = picks(d, ranks, k)
        c = coverage(d, ranks, [held], k=k, selected=selected)
        mask = d.entry_half == held
        hit[mask], first[mask] = np.asarray(c['hit'])[mask], np.asarray(c['first_rows'])[mask]
        rows = d.row_half == held
        selected_by_signal_half[rows] = selected[rows]
    stitched = stitched_ranks(d, method)
    stitched_selected = picks(d, stitched, k)
    return dict(coverage=summarize(d, hit, HALVES, first),
                precision=precision(flags, selected_by_signal_half),
                continuous=dict(coverage=coverage(d, stitched, HALVES, k=k, selected=stitched_selected),
                                precision=precision(flags, stitched_selected)))


def run_evaluate(d):
    d.set_label('real')
    flags = winner_flags(d)
    methods = {method: {str(k): fold_budget(d, method, k, flags) for k in BUDGETS} for method in METHODS}
    random = read('random')
    shuffled = [read('shuffle_' + str(s)) for s in SHUFFLES]
    maximum = max(v['methods'][m]['primary']['hit'] for v in shuffled for m in METHODS)
    decisions = {}
    for method in METHODS:
        result = methods[method]['3']
        hits = result['coverage']['primary']['hit']
        random_hits = [v['budgets']['3']['coverage']['primary']['hit'] for v in random['trials']]
        beat = sum(v < hits for v in random_hits)
        decisions[method] = dict(hit=hits, beat_random=beat, shuffle_pass=hits > maximum,
            coverage_pass=hits >= 19, random_pass=beat >= 27,
            passed=hits >= 19 and hits > maximum and beat >= 27,
            precision_pass=result['precision']['rate'] > read('inputs')['pool_precision']['rate'])
    def complexity(method):
        model = read('final_' + method)['model']
        return len(model['terms'] if method == 'E' else model['features'])
    def key(method):
        return -decisions[method]['hit'], complexity(method), METHODS.index(method)
    qualified = [m for m in METHODS if decisions[m]['passed']]
    selected = min(qualified, key=key) if qualified else None
    decision = dict(methods=decisions, selected=selected, display=selected or min(METHODS, key=key),
                    shuffle_maximum=maximum, results=methods, signature=signature())
    write('decision', decision)
    print('DECISION', decisions, 'selected', selected, flush=True)


def configure():
    for module in (p, e, a):
        module.WORK, module.PREFIX, module.PLAN, module.PREREG = WORK, PREFIX, PLAN, PREREG
        module.path, module.write, module.read = path, write, read
        module.capacity, module.signature = capacity, signature
    e.describe = describe
    e.stamp = lambda: dict(signature=signature())


configure()


def main(stage, seed=None):
    WORK.mkdir(exist_ok=True)
    guard()
    before = capacity(stage + ':start')
    d = Data()
    initialize(d)
    stages = dict(prepare=lambda d: None, describe=run_description, nested=lambda d: run_nested(d, seed),
                  final=run_final, evaluate=run_evaluate)
    if stage == 'all':
        for function in (run_description, run_nested, run_final, run_evaluate):
            function(d)
            gc.collect()
    else:
        stages[stage](d)
    write('runtime_' + stage + ('_' + str(seed) if seed else ''),
          dict(before=before, after=capacity(stage + ':done'), signature=signature()))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=('prepare', 'describe', 'nested', 'final', 'evaluate', 'all'))
    parser.add_argument('--seed', type=int, choices=SHUFFLES)
    args = parser.parse_args()
    main(args.stage, args.seed)
