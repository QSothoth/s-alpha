"""IE23: bounded factor descriptions and label-isolated half-year ranking."""
import argparse
from collections import defaultdict
from datetime import date, datetime, timezone
import gc
import hashlib
import json
import os
from pathlib import Path
import resource
import shutil
import sys
import warnings

import numpy as np

from studies.trader_replication import martin_continue_ie9 as ie9

lib, ie7 = ie9.lib, ie9.ie7
ROOT, REPORTS = ie9.ROOT, ie9.REPORTS
WORK = REPORTS / 'ie23_work'
PREFIX = 'strong_continue_ie23_'
PLAN = ROOT / 'studies/martin_luk/notes/PLAN_IE23_CN.md'
PREREG = ROOT / 'studies/martin_luk/notes/PREREG_IE23_CN.md'
HALVES = tuple(y + 'H' + str(h) for y in (*ie9.YEARS, '2026') for h in (1, 2))
LIMIT = 800_000_000
ANCHORS = ('IE9:after_inside', 'IE9:near_ema9')
SENTINEL = ie9.old.prior.SENTINEL


def sha(path):
    return ie9.prior.file_sha(path)


def clean(value):
    if isinstance(value, dict):
        return {str(k): clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, np.ndarray)):
        return [clean(v) for v in value]
    if isinstance(value, (float, np.floating)):
        return float(value) if np.isfinite(value) else None
    if isinstance(value, (np.integer, np.bool_)):
        return value.item()
    return value


def write(name, value):
    path = REPORTS / (PREFIX + name + '.json')
    temporary = path.with_suffix('.json.tmp')
    temporary.write_text(json.dumps(clean(value), ensure_ascii=False, separators=(',', ':'), allow_nan=False) + '\n')
    temporary.replace(path)


def read(name):
    return json.loads((REPORTS / (PREFIX + name + '.json')).read_text())


def stamp():
    return dict(utc=datetime.now(timezone.utc).isoformat(), plan_sha256=sha(PLAN),
                prereg_sha256=sha(PREREG), source_sha256=sha(Path(__file__)),
                library_sha256=sha(Path(lib.__file__)))


def capacity(stage):
    size = sum(p.stat().st_size for p in WORK.rglob('*') if p.is_file())
    free = shutil.disk_usage(WORK).free
    if free < 1_000_000_000 or size > LIMIT:
        raise RuntimeError(f'{stage}: disk boundary: free={free}, work={size}')
    print(stage, 'disk_free_MB', free // 1_000_000, 'work_MB', size // 1_000_000,
          'peak_RSS_MiB', round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1), flush=True)
    return dict(stage=stage, free_bytes=free, work_bytes=size)


def guard():
    def allowed(path):
        p = Path(os.fsdecode(path)).resolve()
        return p.is_relative_to(WORK.resolve()) or (p.parent == REPORTS.resolve() and p.name.startswith(PREFIX))

    def audit(event, args):
        if event == 'open':
            path, _, flags = args
            if isinstance(path, int):
                return
            p = Path(os.fsdecode(path))
            if flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND):
                if not allowed(path):
                    raise PermissionError('IE23 write boundary: ' + str(p))
            elif p.name.startswith('RULES') or p.suffix in ('.srt', '.vtt') or p.name in ('trades.csv', 'INTERVIEWS_CORE_CN.md'):
                raise PermissionError('IE23 does not read human rules or ledger remarks')
        if event in ('socket.connect', 'socket.bind', 'os.system', 'subprocess.Popen'):
            raise PermissionError('IE23 offline single process')
        if event in ('os.remove', 'os.rename', 'os.rmdir', 'os.mkdir'):
            paths = args[:2] if event == 'os.rename' else args[:1]
            if any(not allowed(p) for p in paths):
                raise PermissionError('IE23 mutation boundary')
    sys.addaudithook(audit)


class CausalStock(lib.Stock):
    def weekly(self):
        """A shortened holiday week is confirmed only when the next session exists."""
        from studies.trend_breakout.chan import week_rows
        first, last = week_rows(self.days)
        availability, high, low, close = [], [], [], []
        for a, b in zip(first, last):
            ready = b if date.fromisoformat(self.days[b]).weekday() == 4 else b + 1
            if ready >= len(self.days):
                continue
            availability.append(ready)
            high.append(np.nanmax(self.h[a:b + 1]))
            low.append(np.nanmin(self.l[a:b + 1]))
            close.append(self.c[b])
        return np.asarray(availability, int), np.asarray(high), np.asarray(low), np.asarray(close)


def percentiles(raw):
    x = np.asarray(raw, float)
    if x.ndim == 1:
        x = x[:, None]
    result = np.full(x.shape, np.nan, np.float32)
    for j in range(x.shape[1]):
        valid = np.flatnonzero(np.isfinite(x[:, j]))
        n = len(valid)
        if not n:
            continue
        order = valid[np.argsort(x[valid, j], kind='stable')]
        values = x[order, j]
        starts = np.r_[0, np.flatnonzero(values[1:] != values[:-1]) + 1]
        stops = np.r_[starts[1:], n]
        result[order, j] = np.repeat((starts + stops - 1) / (2 * max(n - 1, 1)), stops - starts) if n > 1 else .5
    return result


def catalogue():
    rows = []
    for s in lib.inventory():
        for trans in lib.TRANSFORMS:
            name = s.name if trans == 'pct' else s.name + '__' + trans
            formula = s.formula
            if trans == 'delta5':
                formula = 'pool_pct(pool_pct(' + formula + ')-pool_pct[-5])'
            elif trans == 'history250':
                formula = 'pool_pct(own_rank250(' + formula + '))'
            else:
                formula = 'pool_pct(' + formula + ')'
            rows.append(dict(name=name, family=s.family, parameter=s.parameter, metric=s.metric,
                             transform=trans, formula=formula, length=len(''.join(formula.split()))))
    for name in ANCHORS:
        rows.append(dict(name=name, family='anchor', transform='pct',
                         formula='pool_pct(' + name.split(':')[1] + ')', length=len(name) + 10))
    return rows


class Data:
    def __init__(self, matrix=True):
        self.base = ie9.Data(full=True)
        b = self.base
        self.entries = [dict(id=e['id'], code=e['code'], entry_date=e['entry_date'],
                             primary=e['target']['tier'] == 'primary',
                             nights=[x['date'] for x in e['systems']['h4']]) for e in b.entries]
        b.entries = [dict(id=e['id'], code=e['code'], entry_date=e['entry_date'],
                          systems=dict(h4=[dict(date=day) for day in e['nights']]),
                          target=dict(tier='primary' if e['primary'] else 'secondary')) for e in self.entries]
        b.meta['entries'] = b.entries
        self.kept = np.flatnonzero(b.passed)
        full_to_small = np.full(b.n, -1, np.int32)
        full_to_small[self.kept] = np.arange(len(self.kept))
        self.query = np.asarray([[int(full_to_small[q]) if q >= 0 else -1 for q in qs] for qs in b.query], np.int32)
        self.slices, self.days, self.codes = {}, [], []
        self.full_slices = b.slices
        offset = 0
        for day, sl in b.slices.items():
            if day not in b.widths:
                continue
            names = [c for k, c in enumerate(b.meta['scope'][day]) if b.passed[sl.start + k]]
            self.slices[day] = slice(offset, offset + len(names))
            self.days.extend([day] * len(names))
            self.codes.extend(names)
            offset += len(names)
        self.n = offset
        self.row_half = np.asarray([ie7.half(day) for day in self.days])
        self.entry_half = np.asarray([ie7.half(e['entry_date']) for e in self.entries])
        self.primary = np.asarray([e['primary'] for e in self.entries])
        self.specs = catalogue()
        self.name_index = {r['name']: i for i, r in enumerate(self.specs)}
        self.library_n = len(self.specs) - len(ANCHORS)
        self.baseline_values = np.load(ie9.WORK / 'full_features.npy', mmap_mode='r')[self.kept]
        self.baseline_score = np.nan_to_num(self.baseline_values[:, ie9.NAMES.index('after_inside')], nan=.5)
        self.baseline_score += np.nan_to_num(self.baseline_values[:, ie9.NAMES.index('near_ema9')], nan=.5)
        self.baseline_ranks = self.rank(self.baseline_score)
        self.x = np.load(WORK / 'ranks.npy', mmap_mode='r') if matrix else None

    def rank(self, score):
        ranks = np.full(self.n, SENTINEL, np.int32)
        for sl in self.slices.values():
            order = np.argsort(-score[sl], kind='stable')
            ranks[sl.start + order] = np.arange(1, sl.stop - sl.start + 1)
        return ranks

    def shuffled(self, seed, query=None, indices=None):
        rng = np.random.default_rng(seed)
        mapping = np.arange(self.n, dtype=np.int32)
        for sl in self.slices.values():
            mapping[sl] = rng.permutation(mapping[sl])
        q = self.query if query is None else query
        if indices is not None:
            q = q[indices]
        return np.where(q >= 0, mapping[np.maximum(q, 0)], -1)

    def predict(self, model):
        if model.get('baseline'):
            return self.baseline_ranks
        score = np.zeros(self.n, np.float32)
        for term in model['terms']:
            if term['form'] == 'raw':
                name = self.specs[term['j']]['name'].split(':')[1]
                p = np.nan_to_num(self.baseline_values[:, ie9.NAMES.index(name)], nan=.5)
            else:
                p = np.nan_to_num(self.x[term['j']], nan=.5)
            score += -np.abs(p - term['center']) if term['form'] == 'center' else term['direction'] * p
        return self.rank(score)

    def coverage(self, ranks, query, halves):
        included = np.isin(self.entry_half, halves)
        best = np.full(len(self.entries), SENTINEL, np.int32)
        qs = query[included]
        best[included] = np.min(np.where(qs >= 0, ranks[np.maximum(qs, 0)], SENTINEL), axis=1)
        def summary(mask):
            return dict(n=int(mask.sum()), hits={str(k): int(((best <= k) & mask).sum()) for k in ie9.TOPS})
        return dict(primary=summary(included & self.primary), all_entries=summary(included),
                    halfyear={h: summary(included & self.primary & (self.entry_half == h)) for h in halves},
                    all_halfyear={h: summary(included & (self.entry_half == h)) for h in halves}, best=best.tolist())


def prepare():
    d = Data(matrix=False)
    if (WORK / 'prepared.json').exists():
        record = json.loads((WORK / 'prepared.json').read_text())
        if record['source_sha256'] != sha(Path(__file__)) or record['prereg_sha256'] != sha(PREREG):
            raise ValueError('prepared source or registration changed')
        return
    if d.n * len(d.specs) * 4 + 1_000_000 > LIMIT:
        raise RuntimeError('float32 pool cache exceeds workspace budget')
    path = WORK / 'ranks.npy'
    out = np.lib.format.open_memmap(path, mode='w+', dtype=np.float32, shape=(len(d.specs), d.n))
    bycode = defaultdict(list)
    day_index = {day: k for k, day in enumerate(d.base.meta['days'])}
    for k, (day, code) in enumerate(zip(d.days, d.codes)):
        bycode[code].append((day_index[day], k))
    source_hashes = {}
    qpath = ie9.old.WORK / 'qqq.npy'
    qqq = np.load(qpath)
    source_hashes[str(qpath.relative_to(ROOT))] = sha(qpath)
    inventory = lib.inventory()
    for family in dict.fromkeys(s.family for s in inventory):
        capacity('factor:' + family)
        specs = [s for s in inventory if s.family == family]
        raw = np.full((d.n, len(specs)), np.nan, np.float32)
        hist = raw.copy()
        for counter, (code, positions) in enumerate(bycode.items()):
            source = ie9.old.WORK / 'stocks' / (code + '.npz')
            source_hashes[str(source.relative_to(ROOT))] = sha(source)
            with np.load(source) as z:
                arrays = {k: z[k] for k in ('o', 'h', 'l', 'c', 'v', 't')}
                extras = {k[6:]: z[k] for k in z.files if k.startswith('extra_')}
            if family == 'group':
                for n in {s.parameter for s in specs}:
                    source = ie9.old.WORK / 'group' / (code + f'.{n}.npz')
                    source_hashes[str(source.relative_to(ROOT))] = sha(source)
                    with np.load(source) as z:
                        extras.update({f'group.{key}.{n}': z[key] for key in z.files})
            stock = CausalStock(arrays, d.base.meta['days'], qqq, extras)
            values = {n: ie9.old.indicator_values(stock, family, n, {s.metric for s in specs if s.parameter == n})
                      for n in dict.fromkeys(s.parameter for s in specs)}
            values = np.column_stack([values[s.parameter][s.metric] for s in specs])
            ts, rows = map(np.asarray, zip(*positions))
            raw[rows] = values[ts]
            hist[rows] = lib.history_rank(values, ts)
            stock.ema.cache_clear()
            stock.f_hilbert.cache_clear()
            if counter % 100 == 0:
                print('factor', family, counter, '/', len(bycode), flush=True)
        pct = np.full_like(raw, np.nan)
        for sl in d.slices.values():
            pct[sl] = percentiles(raw[sl])
        for trans in lib.TRANSFORMS:
            value = pct if trans == 'pct' else np.full_like(raw, np.nan)
            if trans == 'history250':
                for sl in d.slices.values():
                    value[sl] = percentiles(hist[sl])
            elif trans == 'delta5':
                for day, sl in d.slices.items():
                    t = day_index[day]
                    previous = d.base.meta['days'][t - 5] if t >= 5 else ''
                    ps = d.slices.get(previous, slice(0, 0))
                    lookup = dict(zip(d.codes[ps], range(ps.start, ps.stop)))
                    prior_rows = np.asarray([lookup.get(code, -1) for code in d.codes[sl]], int)
                    prior_values = np.full((sl.stop - sl.start, len(specs)), .5, np.float32)
                    valid = prior_rows >= 0
                    prior_values[valid] = np.nan_to_num(pct[prior_rows[valid]], nan=.5)
                    value[sl] = percentiles(pct[sl] - prior_values)
            for j, s in enumerate(specs):
                name = s.name if trans == 'pct' else s.name + '__' + trans
                out[d.name_index[name]] = value[:, j]
        out.flush()
        del raw, hist, pct, value, stock, arrays, extras, values
        gc.collect()
    for name in ANCHORS:
        j = ie9.NAMES.index(name.split(':')[1])
        for sl in d.slices.values():
            out[d.name_index[name], sl] = percentiles(d.baseline_values[sl, j])[:, 0]
    out.flush()
    del out
    baseline = d.coverage(d.baseline_ranks, d.query, HALVES)
    saved = ie9.read('final')['coverage']
    if baseline['primary'] != {k: saved['primary'][k] for k in ('n', 'hits')}:
        raise AssertionError('IE9 coverage does not reproduce')
    record = dict(rows=d.n, columns=len(d.specs), baseline=baseline, specs=d.specs,
                  input_sha256=source_hashes, matrix_sha256=sha(path), dataset_digest=d.base.meta['dataset_digest'], **stamp())
    (WORK / 'prepared.json').write_text(json.dumps(clean(record), ensure_ascii=False, separators=(',', ':')) + '\n')
    write('prepared', record)
    print('PREPARED', d.n, len(d.specs), baseline['primary'], flush=True)


def group_factors(d, halves):
    label = '_'.join(halves)
    path = REPORTS / (PREFIX + 'groups_' + label + '.json')
    if path.exists():
        return json.loads(path.read_text())
    mask = np.isin(d.row_half, halves)
    n = int(mask.sum())
    chunks, used, vector_groups, groups, identical = [], [], [], [], {}
    order = sorted(range(d.library_n), key=lambda j: (d.specs[j]['length'], d.specs[j]['name']))
    for step, j in enumerate(order):
        p = np.nan_to_num(d.x[j, mask], nan=.5)
        vector = percentiles(p)[:, 0]
        signature = hashlib.sha256(vector.tobytes()).digest()
        vector -= vector.mean()
        norm = np.linalg.norm(vector)
        if not norm:
            groups.append(dict(representative=j, members=[j], correlations=[None], constant=True))
            continue
        if signature in identical and identical[signature][1] == 1.:
            position, correlation = identical[signature]
            groups[position]['members'].append(j)
            groups[position]['correlations'].append(correlation)
            continue
        vector = vector / norm
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
        identical[signature] = position, best
        if step % 500 == 0:
            print('groups', label, step, '/', d.library_n, 'representatives', len(groups), flush=True)
    result = dict(training_halves=list(halves), rows=n, groups=groups,
                  method='shortest-formula greedy representative Spearman, rho>0.7', **stamp())
    write('groups_' + label, result)
    return result


def target_means(values, query):
    sampled = np.where(query[None] >= 0, values[:, np.maximum(query, 0)], np.nan)
    with warnings.catch_warnings():
        warnings.simplefilter('ignore', RuntimeWarning)
        means = np.nanmean(sampled, axis=2)
        medians = np.nanmedian(sampled, axis=2)
    return sampled, means, medians


def half_means(means, halves, entry_halves, eligible, minimum=2):
    out = np.full((means.shape[0], len(halves)), np.nan)
    counts = np.zeros(out.shape, int)
    for k, half in enumerate(halves):
        mask = entry_halves == half
        count = np.isfinite(means[:, mask]).sum(1)
        counts[:, k] = count
        enough = (count >= minimum) & (count >= eligible[half] / 2)
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', RuntimeWarning)
            out[:, k] = np.where(enough, np.nanmean(means[:, mask], axis=1), np.nan)
    return out, counts


def same_side(half_values, pivot=.5):
    return np.all(half_values > pivot, axis=1) | np.all(half_values < pivot, axis=1)


def describe(d, halves, query, columns=None, null=True):
    """Filter labels before any target lookup; held-out target rows never enter here."""
    columns = list(range(len(d.specs))) if columns is None else list(columns)
    ids = np.flatnonzero(np.isin(d.entry_half, halves) & d.primary)
    qs = query[ids]
    entry_halves = d.entry_half[ids]
    eligible = {h: int(np.any(qs[entry_halves == h] >= 0, axis=1).sum()) for h in halves}
    mean = np.full((len(columns), len(halves)), np.nan)
    counts = np.zeros(mean.shape, int)
    centers = np.full(len(columns), .5)
    center_diff = np.full_like(mean, np.nan)
    pair_diff, pair_win = np.full_like(mean, np.nan), np.full_like(mean, np.nan)
    baseline_best = np.min(np.where(qs >= 0, d.baseline_ranks[np.maximum(qs, 0)], SENTINEL), axis=1)
    pair_records = []
    for local, i in enumerate(ids):
        if baseline_best[local] <= 5:
            continue
        for q in qs[local]:
            if q < 0:
                continue
            sl = d.slices[d.days[q]]
            others = np.arange(sl.start, sl.stop)
            front = others[d.baseline_ranks[others] <= 5]
            pair_records.extend((local, int(q), int(other)) for other in front if other != q)
    null_counts = np.zeros(20, int)
    permutations = [d.shuffled(2026112360 + k, query, indices=ids) for k in range(20)] if null else []
    for start in range(0, len(columns), 96):
        js = columns[start:start + 96]
        values = d.x[js]
        sampled, per_entry, medians = target_means(values, qs)
        block_mean, block_count = half_means(per_entry, halves, entry_halves, eligible)
        mean[start:start + len(js)] = block_mean
        counts[start:start + len(js)] = block_count
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', RuntimeWarning)
            m = np.nanmedian(medians, axis=1)
        centers[start:start + len(js)] = m
        centered = -np.abs(sampled - m[:, None, None])
        other_entry = np.full_like(per_entry, np.nan)
        for local, row in enumerate(qs):
            others = []
            for q in row:
                if q >= 0:
                    sl = d.slices[d.days[q]]
                    rest = np.arange(sl.start, sl.stop)
                    rest = rest[rest != q]
                    with warnings.catch_warnings():
                        warnings.simplefilter('ignore', RuntimeWarning)
                        others.append(np.nanmean(-np.abs(values[:, rest] - m[:, None]), axis=1))
            if others:
                with warnings.catch_warnings():
                    warnings.simplefilter('ignore', RuntimeWarning)
                    other_entry[:, local] = np.nanmean(others, axis=0)
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', RuntimeWarning)
            cent_entry = np.nanmean(centered, axis=2) - other_entry
        center_diff[start:start + len(js)] = half_means(cent_entry, halves, entry_halves, eligible)[0]
        if pair_records:
            pair = np.asarray(pair_records)
            delta = values[:, pair[:, 1]] - values[:, pair[:, 2]]
            win = np.where(np.isfinite(delta), (delta > 0) + .5 * (delta == 0), np.nan)
            entry_delta, entry_win = np.full_like(per_entry, np.nan), np.full_like(per_entry, np.nan)
            for local in np.unique(pair[:, 0]):
                with warnings.catch_warnings():
                    warnings.simplefilter('ignore', RuntimeWarning)
                    entry_delta[:, local] = np.nanmean(delta[:, pair[:, 0] == local], axis=1)
                    entry_win[:, local] = np.nanmean(win[:, pair[:, 0] == local], axis=1)
            pair_eligible = {h: int(np.isfinite(entry_delta[:, entry_halves == h]).any(0).sum()) for h in halves}
            pair_diff[start:start + len(js)] = half_means(entry_delta, halves, entry_halves, pair_eligible, 1)[0]
            pair_win[start:start + len(js)] = half_means(entry_win, halves, entry_halves, pair_eligible, 1)[0]
        for k, permuted in enumerate(permutations):
            _, random_entry, _ = target_means(values, permuted)
            random_half = half_means(random_entry, halves, entry_halves, eligible)[0]
            library = np.asarray(js) < d.library_n
            null_counts[k] += int((same_side(random_half) & library).sum())
    library = np.asarray(columns) < d.library_n
    observed = int((same_side(mean) & library).sum())
    return dict(training_halves=list(halves), training_ids=[d.entries[i]['id'] for i in ids], columns=columns,
                means=mean, counts=counts, centers=centers, center_diff=center_diff, pair_diff=pair_diff,
                pair_win=pair_win, pair_count=len(pair_records), paired_entries=len({r[0] for r in pair_records}),
                same_side_count=observed, null_counts=null_counts,
                clear_excess=bool(observed > max(null_counts)) if null else None)


def representative_lists(d, desc, groups):
    means = np.asarray(desc['means'])
    pair_diff, pair_win = np.asarray(desc['pair_diff']), np.asarray(desc['pair_win'])
    center_diff = np.asarray(desc['center_diff'])
    reps = [g['representative'] for g in groups['groups']]
    stable = [j for j in reps if same_side(means[[j]])[0]]
    directional = sorted(stable, key=lambda j: (-min(abs(means[j] - .5)), -np.mean(abs(means[j] - .5)),
                                              d.specs[j]['length'], d.specs[j]['name']))
    paired = [j for j in reps if same_side(pair_diff[[j]], 0)[0] and same_side(pair_win[[j]])[0]
              and np.sign(np.mean(pair_diff[j])) == np.sign(np.mean(pair_win[j] - .5))]
    paired.sort(key=lambda j: (-min(abs(pair_win[j] - .5)), -np.mean(abs(pair_win[j] - .5)),
                               d.specs[j]['length'], d.specs[j]['name']))
    centered = [j for j in reps if np.all(center_diff[j] > 0)]
    centered.sort(key=lambda j: (-min(center_diff[j]), -np.mean(center_diff[j]), d.specs[j]['length'], d.specs[j]['name']))
    return directional, paired, centered


def candidates(d, desc, groups):
    directional, paired, centered = representative_lists(d, desc, groups)
    means = np.asarray(desc['means'])
    rows = [dict(id='IE9', baseline=True, terms=[dict(j=d.name_index[n], form='raw', direction=1) for n in ANCHORS])]
    seen = set()
    def add(label, selected, form='direction', pair=False, anchors=()):
        terms = []
        for j in selected + [d.name_index[n] for n in anchors]:
            # near_ema9's library pct and its identical IE9 anchor are the same input.
            alias = 'near_ema9' if d.specs[j]['name'] == ANCHORS[1] else d.specs[j]['name']
            if any(t['alias'] == alias for t in terms):
                continue
            direction_mean = np.asarray(desc['pair_diff'])[j].mean() if pair else np.nanmean(means[j] - .5)
            terms.append(dict(j=int(j), alias=alias, form=form if j < d.library_n else 'direction',
                              direction=1 if direction_mean >= 0 else -1, center=float(desc['centers'][j]),
                              direction_source='pair' if pair and j < d.library_n else 'mean'))
        key = tuple((t['j'], t['form']) for t in terms)
        if key not in seen:
            seen.add(key)
            rows.append(dict(id=label, terms=terms))
    for round_number, sequence, form, pair in ((1, directional, 'direction', False), (2, paired, 'direction', True),
                                                (4, centered, 'center', False)):
        for k in range(1, 6):
            if len(sequence) >= k:
                add(f'R{round_number}K{k}', sequence[:k], form=form, pair=pair)
    for k in range(1, 4):
        if len(directional) >= k:
            add(f'R3K{k}', directional[:k], anchors=ANCHORS)
    for k in range(1, 3):
        if len(directional) >= k:
            add(f'R3REPLACE{k}', directional[:k], anchors=ANCHORS[:1])
    rows[1:] = sorted(rows[1:], key=lambda row: (int(row['id'][1]), row['id']))
    return rows


def candidate_key(result):
    coverage, model = result['coverage'], result['model']
    return (coverage['primary']['hits']['5'], -len(model['terms']), coverage['all_entries']['hits']['5'], -result['order'])


def refit(d, model, halves, query):
    if model.get('baseline') or all(t['form'] == 'raw' for t in model['terms']):
        return model
    js = [t['j'] for t in model['terms']]
    desc = describe(d, halves, query, columns=js, null=False)
    terms = []
    for k, old in enumerate(model['terms']):
        if old['form'] == 'raw':
            terms.append(old)
            continue
        values = desc['pair_diff'][k] if old.get('direction_source') == 'pair' else desc['means'][k] - .5
        if not np.isfinite(values).any():
            values = desc['means'][k] - .5
        terms.append(dict(old, direction=1 if np.nanmean(values) >= 0 else -1,
                          center=float(desc['centers'][k])))
    return dict(model, terms=terms)


def ablate(d, model, halves, query):
    def inner_score(candidate):
        summaries = {}
        for held in halves:
            trained = [h for h in halves if h != held]
            fitted = refit(d, candidate, trained, query)
            c = d.coverage(d.predict(fitted), query, [held])
            summaries[held] = c['primary']
        return dict(hits=sum(r['hits']['5'] for r in summaries.values()), halves=summaries)
    current, history = model, []
    score = inner_score(current)
    while current['terms']:
        accepted = False
        for k, term in enumerate(current['terms']):
            trial = dict(current, baseline=False, terms=current['terms'][:k] + current['terms'][k + 1:])
            # Raw IE9 anchors retain their original amplitude and direction when one is removed.
            if current.get('baseline') or any(t['form'] == 'raw' for t in current['terms']):
                trial['raw_anchors'] = True
            after = inner_score(trial)
            accepted = after['hits'] >= score['hits']
            history.append(dict(removed=term, before=score, after=after, accepted=accepted))
            if accepted:
                current, score = trial, after
                break
        if not accepted:
            break
    return dict(initial=model, final=current, inner_score=score, trials=history)


def select(d, halves, query, groups):
    desc = describe(d, halves, query)
    models = candidates(d, desc, groups)
    results = []
    for order, model in enumerate(models):
        coverage = d.coverage(d.predict(model), query, halves)
        eligible = all(r['hits']['5'] / r['n'] >= .25 for r in coverage['halfyear'].values() if r['n'])
        results.append(dict(model=model, coverage=coverage, eligible=eligible, order=order))
    allowed = [r for r in results if r['eligible']]
    chosen = max(allowed, key=candidate_key) if allowed else results[0]
    ablation = ablate(d, chosen['model'], halves, query)
    return dict(training_halves=list(halves), description=desc, candidates=results, selected=chosen['model'],
                ablation=ablation, model=ablation['final'])


def leave_out(d, query, label):
    records, best = [], np.full(len(d.entries), SENTINEL, np.int32)
    for held in HALVES:
        capacity(label + ':' + held)
        train = [h for h in HALVES if h != held]
        path = REPORTS / (PREFIX + label + '_' + held + '.json')
        if path.exists():
            result = json.loads(path.read_text())
            if result['source_sha256'] != sha(Path(__file__)):
                raise ValueError('fold source changed')
            c = result['held_coverage']
        else:
            groups = group_factors(d, train)
            result = select(d, train, query, groups)
            result['held_out'] = held
            result['model_frozen_sha256'] = ie9.prior.digest(clean(result['model']))
            # This is the first and only evaluation of the fixed fold on its held labels.
            c = d.coverage(d.predict(result['model']), query, [held])
            result['held_coverage'] = c
            write(label + '_' + held, dict(result, **stamp()))
        mask = d.entry_half == held
        best[mask] = np.asarray(c['best'])[mask]
        records.append(result)
        print(label, held, c['primary'], 'model', result['model']['id'],
              [d.specs[t['j']]['name'] for t in result['model']['terms']], flush=True)
    primary = d.primary
    summary = dict(n=int(primary.sum()), hits={str(k): int(((best <= k) & primary).sum()) for k in ie9.TOPS})
    all_entries = dict(n=len(best), hits={str(k): int((best <= k).sum()) for k in ie9.TOPS})
    return dict(records=[dict(held_out=r['held_out'], model=r['model'], held_coverage=r['held_coverage'],
                             model_frozen_sha256=r['model_frozen_sha256']) for r in records],
                primary=summary, all_entries=all_entries, best=best,
                passed=summary['hits']['5'] >= 26 and all(ie7.rate(r['held_coverage']['primary']) >= .25 for r in records))


def run_description():
    d = Data()
    groups = group_factors(d, HALVES)
    result = describe(d, HALVES, d.query)
    result['groups'] = groups
    result.update(stamp())
    write('description', result)
    print('DESCRIPTION', result['same_side_count'], result['null_counts'].tolist(), flush=True)


def run_real():
    d = Data()
    result = leave_out(d, d.query, 'loo')
    result.update(stamp())
    write('loo', result)
    print('REAL LOO', result['primary'], flush=True)


def run_shuffle():
    d = Data()
    real = read('loo')['primary']['hits']['5']
    records = []
    for seed in range(2026112301, 2026112306):
        result = leave_out(d, d.shuffled(seed), 'shuffle_' + str(seed))
        write('shuffle_' + str(seed), dict(result, seed=seed, **stamp()))
        records.append(dict(seed=seed, primary=result['primary'], all_entries=result['all_entries']))
        print('SHUFFLE', seed, result['primary'], flush=True)
    write('shuffle', dict(records=records, actual=real, passed=all(real > r['primary']['hits']['5'] for r in records), **stamp()))


def run_final():
    d = Data()
    result = select(d, list(HALVES), d.query, group_factors(d, HALVES))
    result['coverage'] = d.coverage(d.predict(result['model']), d.query, HALVES)
    result.update(stamp())
    write('final', result)
    print('FINAL', result['coverage']['primary'], result['model'], flush=True)


def run_random():
    d = Data()
    actual = read('loo')
    trials = []
    for seed in range(2026112330, 2026112360):
        rng = np.random.default_rng(seed)
        score = rng.random(d.n)
        c = d.coverage(d.rank(score), d.query, HALVES)
        trials.append(dict(seed=seed, coverage=c))
    def place(value, values):
        return dict(actual=value, rank=1 + sum(x > value for x in values), ties=sum(x == value for x in values),
                    mean=float(np.mean(values)), minimum=min(values), maximum=max(values), trials=len(values))
    placement = {r['held_out']: place(r['held_coverage']['primary']['hits']['5'],
                 [t['coverage']['halfyear'][r['held_out']]['hits']['5'] for t in trials]) for r in actual['records']}
    placement['combined'] = place(actual['primary']['hits']['5'], [t['coverage']['primary']['hits']['5'] for t in trials])
    expected = {}
    for half in HALVES:
        probabilities = []
        for i in np.flatnonzero(d.primary & (d.entry_half == half)):
            probs = [min(1., 5 / (d.slices[d.days[q]].stop - d.slices[d.days[q]].start)) for q in d.query[i] if q >= 0]
            probabilities.append(1 - float(np.prod(1 - np.asarray(probs))))
        expected[half] = sum(probabilities)
    write('random', dict(trials=trials, placement=placement, union_expectation=expected, **stamp()))


def run_accounts():
    d = Data()
    final = read('final')['model']
    loo = read('loo')
    full_ranks = d.predict(final)
    stitched = np.full(d.n, SENTINEL, np.int32)
    for record in loo['records']:
        prediction = d.predict(record['model'])
        mask = d.row_half == record['held_out']
        stitched[mask] = prediction[mask]
    early = stitched == SENTINEL
    stitched[early] = d.predict(loo['records'][0]['model'])[early]
    results = {}
    for label, ranks in (('final', full_ranks), ('loo', stitched)):
        capacity('accounts:' + label)
        selected = {day: [d.codes[q] for q in range(sl.start, sl.stop) if ranks[q] <= 5]
                    for day, sl in d.slices.items()}
        # The existing adapter uses order as a tie-break, so preserve rank order.
        for day, sl in d.slices.items():
            selected[day].sort(key=lambda code: int(ranks[sl.start + d.codes[sl].index(code)]))
        accounts = d.base.accounts(selected)
        eligible, failures = ie7.eligible(accounts)
        results[label] = dict(accounts=accounts, eligible=eligible, failures=failures,
                              selected_hash=ie9.prior.digest(selected))
        np.save(REPORTS / (PREFIX + label + '_ranks.npy'), ranks)
        print('ACCOUNTS', label, eligible,
              {k: {y: v for y, v in a['annual'].items()} for k, a in accounts.items()}, flush=True)
    results['baseline'] = ie9.read('final')['accounts']
    results.update(stamp())
    write('accounts', results)


def run_diagnostics():
    d = Data()
    final, description = read('final'), read('description')
    model = final['model']
    means = np.asarray(description['means'], float)
    groups = description['groups']['groups']
    stable = [g['representative'] for g in groups if same_side(means[[g['representative']]])[0]]
    baseline = d.coverage(d.baseline_ranks, d.query, HALVES)
    misses = []
    day_index = {day: k for k, day in enumerate(d.base.meta['days'])}
    for i, e in enumerate(d.entries):
        if not e['primary'] or baseline['best'][i] <= 5 or not np.any(d.query[i] >= 0):
            continue
        k = max(range(len(e['nights'])), key=lambda j: e['nights'][j])
        q = int(d.query[i, k])
        distinct, largest, informative = False, None, 0
        if q >= 0:
            sl = d.slices[d.days[q]]
            rows = np.arange(sl.start, sl.stop)
            front = rows[d.baseline_ranks[rows] <= 5]
            for j in stable:
                own, others = d.x[j, q], d.x[j, front]
                if not np.isfinite(own) or not np.isfinite(others).any():
                    continue
                informative += 1
                direction = 1 if np.mean(means[j]) > .5 else -1
                difference = float(direction * (own - np.nanmean(others)))
                largest = difference if largest is None else max(largest, difference)
                distinct |= difference > .05
        source = ie9.old.WORK / 'stocks' / (e['code'] + '.npz')
        with np.load(source) as z:
            o, c, h, l = (z[k] for k in ('o', 'c', 'h', 'l'))
        t = day_index.get(e['entry_date'], -1)
        adr = float(lib.roll(lib.divide(h, l) - 1, 20)[t - 1]) if t > 0 else np.nan
        gap = float(o[t] / c[t - 1] - 1) if t > 0 else np.nan
        large_gap = bool(np.isfinite(gap + adr) and gap >= 2 * adr)
        misses.append(dict(id=e['id'], code=e['code'], entry_date=e['entry_date'], half=d.entry_half[i],
                           previous_night_in_pool=q >= 0, informative_stable_groups=informative,
                           previous_distinction=distinct if q >= 0 and informative else None,
                           largest_directed_difference=largest, gap=gap, previous_adr20=adr,
                           gap_adr=gap / adr if adr > 0 else None, large_gap=large_gap,
                           opening_only_proxy=bool(q >= 0 and informative and not distinct and large_gap)))
    factor_records = []
    best = np.asarray(final['coverage']['best'])
    for term in model['terms']:
        alone = dict(baseline=False, terms=[term])
        one = d.coverage(d.predict(alone), d.query, HALVES)
        single = np.asarray(one['best'])
        def examples(mask):
            return [dict(id=e['id'], code=e['code'], entry_date=e['entry_date'],
                         combined_rank=int(best[i]), factor_rank=int(single[i]))
                    for i, e in enumerate(d.entries) if mask[i]][:3]
        trials = [r for r in final['ablation']['trials'] if r['removed']['j'] == term['j'] and not r['accepted']]
        retained = trials[-1] if trials else None
        factor_records.append(dict(term=term, spec=d.specs[term['j']], standalone=one,
            deletion=retained, hits=examples(d.primary & (best <= 5) & (single <= 5)),
            misses=examples(d.primary & (best > 5))))
    # Concrete target-versus-front rows, without setup or human notes.
    pairs = []
    for i, e in enumerate(d.entries):
        if not e['primary'] or baseline['best'][i] <= 5:
            continue
        for q in d.query[i]:
            if q >= 0:
                sl = d.slices[d.days[q]]
                front = [k for k in range(sl.start, sl.stop) if d.baseline_ranks[k] <= 5]
                pairs.append(dict(id=e['id'], code=e['code'], entry_date=e['entry_date'], signal=d.days[q],
                                  rank=int(d.baseline_ranks[q]), front=[d.codes[k] for k in sorted(front, key=lambda k: d.baseline_ranks[k])]))
    write('diagnostics', dict(opening=misses, opening_only_count=sum(r['opening_only_proxy'] for r in misses),
                             baseline_pairs=pairs, factors=factor_records, **stamp()))


def verify():
    d = Data()
    loo, final, controls = read('loo'), read('final'), read('shuffle')
    assertions = []
    def check(name, condition):
        if not condition:
            raise AssertionError(name)
        assertions.append(name)
    prepared = read('prepared')
    check('matrix checksum', sha(WORK / 'ranks.npy') == prepared['matrix_sha256'])
    check('readonly registration', prepared['plan_sha256'] == sha(PLAN) and prepared['prereg_sha256'] == sha(PREREG))
    check('baseline coverage', d.coverage(d.baseline_ranks, d.query, HALVES)['primary'] == prepared['baseline']['primary'])
    check('loo denominators', sum(r['held_coverage']['primary']['n'] for r in loo['records']) == loo['primary']['n'])
    check('loo total', sum(r['held_coverage']['primary']['hits']['5'] for r in loo['records']) == loo['primary']['hits']['5'])
    check('five complete shuffles', len(controls['records']) == 5)
    check('thirty random trials', len(read('random')['trials']) == 30)
    for record in loo['records']:
        held = record['held_out']
        r = read('loo_' + held)
        ids = set(r['description']['training_ids'])
        held_ids = {e['id'] for e, h in zip(d.entries, d.entry_half) if h == held}
        check('label isolation ' + held, not (ids & held_ids))
        check('frozen model ' + held, ie9.prior.digest(record['model']) == record['model_frozen_sha256'])
        check('candidate budget ' + held, all(sum(c['model']['id'].startswith('R' + str(k)) for c in r['candidates']) <= 5
                                               for k in range(1, 5)))
        check('factor budget ' + held, all(len(c['model']['terms']) <= 5 for c in r['candidates']))
    check('final factor budget', len(final['model']['terms']) <= 5)
    for path, digest in prepared['input_sha256'].items():
        check('input ' + path, sha(ROOT / path) == digest)
    initial_path = REPORTS / (PREFIX + 'initial_files.json')
    if initial_path.exists():
        initial = json.loads(initial_path.read_text())
        for path, digest in initial['hashes'].items():
            check('original ' + path, sha(ROOT / path) == digest)
    write('verification', dict(assertions=len(assertions), checks=assertions, peak_work=capacity('verify'), **stamp()))
    print('VERIFIED', len(assertions), flush=True)


def main(stage):
    WORK.mkdir(exist_ok=True)
    (WORK / 'tmp').mkdir(exist_ok=True)
    os.environ['TMPDIR'] = str(WORK / 'tmp')
    import tempfile
    tempfile.tempdir = str(WORK / 'tmp')
    guard()
    before = capacity(stage)
    if stage == 'prepare':
        prepare()
    else:
        prepared = read('prepared')
        if prepared['source_sha256'] != sha(Path(__file__)) or prepared['prereg_sha256'] != sha(PREREG):
            raise ValueError('source or registration changed after preparation')
        dict(describe=run_description, loo=run_real, shuffle=run_shuffle, final=run_final, random=run_random,
             accounts=run_accounts, diagnostics=run_diagnostics, verify=verify)[stage]()
    write('runtime_' + stage, dict(before=before, after=capacity(stage + ':done'),
                                 peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss, **stamp()))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('stage', choices=('prepare', 'describe', 'loo', 'shuffle', 'final', 'random', 'accounts', 'diagnostics', 'verify'))
    main(parser.parse_args().stage)
