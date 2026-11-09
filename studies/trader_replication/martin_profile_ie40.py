"""IE40: one frozen v1.1 profile, yearly coverage and diagnostic refits.

Run offline from the worktree root with single-threaded BLAS:
python -m studies.trader_replication.martin_profile_ie40 --workers 2
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import resource
import shutil
import sys
import time

import numpy as np

from studies.trader_replication import standard_indicators as standard
from studies.trader_replication import martin_profile_ie38 as previous
from studies.trader_replication.standard_indicators_dedup import load_stock, process_rss

ROOT = Path(__file__).resolve().parents[2]
GAP = ROOT / 'studies/trader_replication/reports/gap_review'
WORK = GAP / 'ie40_work'
SOURCE = GAP / 'ie5_work'
OUTPUT = GAP / 'strong_continue_ie40.json'
TRAIN_HALVES = previous.TRAIN_HALVES
YEARS = ('2024', '2025', '2026')
SHUFFLE_SEEDS = (20261105401, 20261105402, 20261105403, 20261105404, 20261105405)
RANDOM_SEED = 20261105406
T0 = time.monotonic()


def log(*values):
    print(f'[{time.monotonic()-T0:.0f}s]', *values, flush=True)


def capacity(stage):
    size = 0
    for path in WORK.rglob('*'):
        try:
            if path.is_file():
                size += path.stat().st_size
        except FileNotFoundError:
            pass
    free = shutil.disk_usage(WORK).free
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024
    if size > 800_000_000 or free < 1_000_000_000 or rss > 900_000_000:
        raise RuntimeError(f'{stage}: work={size}, free={free}, peak_rss={rss}')
    return dict(stage=stage, work_bytes=size, free_bytes=free, peak_rss_bytes=rss)


def install_offline_guard():
    def allowed(path):
        p = Path(os.fsdecode(path)).resolve()
        return p.is_relative_to(WORK) or p in (OUTPUT, OUTPUT.with_suffix('.json.tmp'))

    def audit(event, values):
        previous._offline_audit(event, values)
        if event == 'open' and not isinstance(values[0], int):
            if values[2] & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND):
                if not allowed(values[0]):
                    raise PermissionError('IE40 write boundary: '+str(values[0]))
        if event in ('os.remove', 'os.rename', 'os.rmdir', 'os.mkdir'):
            paths = values[:2] if event == 'os.rename' else values[:1]
            if any(not allowed(p) for p in paths):
                raise PermissionError('IE40 mutation boundary')
    sys.addaudithook(audit)


def sha(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        while block := stream.read(1024*1024):
            digest.update(block)
    return digest.hexdigest()


def fingerprints():
    files = ['studies/martin_luk/notes/PLAN_IE40_CN.md',
             'studies/martin_luk/notes/PREREG_IE40_CN.md',
             'skills/trader-replication/references/STANDARD_INDICATORS_CN.md',
             'studies/trader_replication/reports/gap_review/standard_indicators_v1_1_dedup.json',
             'studies/trader_replication/reports/gap_review/ie40_work/inputs_before.json']
    files += [str(Path(module.__file__).resolve().relative_to(ROOT)) for name, module in sys.modules.copy().items()
              if name.startswith('studies.') and getattr(module, '__file__', None)
              and Path(module.__file__).suffix == '.py']
    files += ['studies/trader_replication/martin_profile_ie29.py',
              'studies/trader_replication/martin_profile_ie40.py']
    return {name: sha(ROOT/name) for name in sorted(set(files))}


def scope_values(panels, code_index, scope, codes, t, block_size=128):
    """Slice first: all RS ranks and both peer definitions see tonight's scope."""
    positions = {code: j for j, code in enumerate(scope)}
    selected = np.array([code_index[code] for code in scope], int)
    wanted = np.array([positions[code] for code in codes], int)
    trailing = [panel[selected, max(0, t-252):t+1] for panel in panels]
    return standard.cross_section(*trailing, wanted, version='v1.1', block_size=block_size)


def pool_matrix(codes, row_day, days, scopes):
    """Bounded per-stock computation; only the retained 117 rows are cached."""
    names = list(standard.V1_1_NAMES)
    signature = hashlib.sha256(json.dumps([sha(Path(standard.__file__)), sha(Path(__file__)), names, list(codes),
        list(map(int, row_day)), days, scopes], sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    path = WORK/'pool_standard_v1_1.npz'
    if path.exists():
        with np.load(path) as z:
            if str(z['signature']) != signature or list(z['names']) != names:
                raise ValueError('cached library, scope or row order changed')
            return names, z['x']
    index = {name: k for k, name in enumerate(names)}
    x = np.full((len(names), len(codes)), np.nan, np.float32)
    code_array = np.asarray(codes)
    q = np.load(SOURCE/'qqq.npy')
    for k, code in enumerate(dict.fromkeys(codes)):
        rows = np.flatnonzero(code_array == code)
        arrays, extras = load_stock(SOURCE/'stocks'/(code+'.npz'), days)
        values = standard.per_stock(arrays, q, extras, version='v1.1')
        for name, column in values.items():
            if name in index:
                x[index[name], rows] = column[row_day[rows]]
        if k % 50 == 0:
            log('pool stock', k, capacity('pool_series'))
    files = sorted((SOURCE/'stocks').glob('*.npz'))
    code_index = {p.stem: j for j, p in enumerate(files)}
    panels = [np.full((len(files), len(days)), np.nan) for _ in range(3)]
    for i, source in enumerate(files):
        with np.load(source) as z:
            for panel, field in zip(panels, ('c', 'h', 'l')):
                panel[i] = z[field]
    for k, t in enumerate(np.unique(row_day)):
        rows = np.flatnonzero(row_day == t)
        values = scope_values(panels, code_index, scopes[days[t]], code_array[rows], t)
        for name, column in values.items():
            if name in index:
                x[index[name], rows] = column
        if k % 100 == 0:
            log('pool scope', k, capacity('pool_cross_section'))
    temporary = path.with_name(path.stem+'.tmp.npz')
    np.savez(temporary, names=names, x=x, signature=signature)
    temporary.replace(path)
    previous.write(WORK/'pool_manifest.json', dict(signature=signature, names=names,
        rows=len(codes), nights=len(np.unique(row_day)), scope='b.meta[scope][day]',
        finite_counts={name: int(np.isfinite(x[j]).sum()) for j, name in enumerate(names)},
        resources=capacity('pool_complete')))
    return names, x


def yearly(ctx, ranks, targets, K=3, H=3):
    selected = ctx['picks'](ranks, K, H)
    hit = ctx['covered'](selected, targets, H)
    return {year: dict(hit=sum(bool(h) for h, t in zip(hit, targets) if t[3] and t[2][:4] == year),
                       n=sum(bool(t[3]) for t in targets if t[2][:4] == year))
            for year in YEARS if any(t[2][:4] == year for t in targets)}


def fit_profiles(ctx, targets, label):
    """Every completed fold is immutable; no holdout metrics before the full fit."""
    source = fingerprints()
    folds = []
    for half in (*TRAIN_HALVES, 'full'):
        path = WORK/f'{label}_{half}_fit.json'
        if path.exists():
            row = json.loads(path.read_text())
            if row['fingerprints'] != source:
                raise ValueError('saved fit source changed')
        else:
            train = [t for t in targets if t[2] in TRAIN_HALVES and t[2] != half]
            test = [t for t in targets if t[2] == half]
            scores, models, _ = ctx['fit_scorer'](train)
            model = models[0]
            if len(models) != 1 or len(model) > 7 or any(w not in ctx['WEIGHTS'][1:] for w in model.values()):
                raise ValueError('profile exceeds the registered capacity')
            ranks = ctx['ranks_of'](scores)
            row = dict(half=half, model=[dict(name=ctx['NAMES'][k], bins=q, weight=w)
                       for (k, q), w in model.items()], train_fit=ctx['evaluate'](ranks, train),
                       bin_source_halves=sorted(set(ctx['ROW_HALVES'][ctx['TRAIN_MASK']])),
                       bin_source_rows=int(ctx['TRAIN_MASK'].sum()), fingerprints=source)
            if half == 'full':
                row.update(profile=previous.profile(ctx, train, model),
                           yearly_train=yearly(ctx, ranks, train), config=vars(ctx['args']))
                np.save(WORK/(label+'_scores.npy'), scores)
            else:
                row.update(hit=ctx['evaluate'](ranks, test)[0], n=sum(t[3] for t in test))
            row['resources'] = capacity(label+'_'+half)
            previous.write(path, row)
        log(label, half, row['train_fit'], row.get('hit'), row['model'])
        if half != 'full':
            folds.append(row)
    row.update(folds=folds, cv_hit=sum(f['hit'] for f in folds), cv_n=sum(f['n'] for f in folds),
               yearly_cv={year: dict(hit=sum(f['hit'] for f in folds if f['half'][:4] == year),
                                     n=sum(f['n'] for f in folds if f['half'][:4] == year)) for year in YEARS[:2]})
    return row


def evaluate_frozen(ctx):
    if OUTPUT.exists():
        saved = json.loads(OUTPUT.read_text())
        if saved['fingerprints'] != fingerprints():
            raise ValueError('formal evaluation source changed')
        log('reuse immutable formal evaluation')
        return
    full = json.loads((WORK/'real_full_fit.json').read_text())
    if full['fingerprints'] != fingerprints():
        raise ValueError('source changed after fitting')
    formal = json.loads((WORK/'real_fit.json').read_text())
    ranks = ctx['ranks_of'](np.load(WORK/'real_scores.npy'))
    observed = yearly(ctx, ranks, ctx['REAL'])
    secondary = yearly(ctx, ranks, ctx['REAL'], K=2, H=2)
    baseline = yearly(ctx, ctx['ranks_of'](ctx['_score']), ctx['REAL'])
    rng = np.random.default_rng(RANDOM_SEED)
    draws = []
    for _ in range(30):
        random_ranks = np.empty(ctx['N'], np.int32)
        for sl in ctx['SL'].values():
            random_ranks[sl] = rng.permutation(sl.stop-sl.start)+1
        draws.append(dict(main=yearly(ctx, random_ranks, ctx['REAL']),
                          four=yearly(ctx, random_ranks, ctx['REAL'], K=2, H=2)))
    random = {}
    for year in YEARS:
        values = [row['main'][year]['hit'] for row in draws]
        random[year] = dict(mean=float(np.mean(values)), min=min(values), max=max(values),
                           at_least_observed=sum(v >= observed[year]['hit'] for v in values))
    train = [t for t in ctx['REAL'] if t[2] in TRAIN_HALVES]
    model = {(ctx['NAMES'].index(t['name']), t['bins']): t['weight'] for t in full['model']}
    tables = ctx['tables_for'](train)
    families = {s['name']: s['family'] for s in standard.SPEC}
    groups = {}
    for key in model:
        groups.setdefault(families[ctx['NAMES'][key[0]]], []).append(key)
    drops = [('indicator', ctx['NAMES'][key[0]], [key]) for key in model]
    drops += [('family', name, keys) for name, keys in groups.items()]
    ablations = []
    for kind, name, keys in drops:
        rest = {key: w for key, w in model.items() if key not in keys}
        r = ctx['ranks_of'](ctx['score'](rest, tables))
        ablations.append(dict(kind=kind, drop=name, names=[ctx['NAMES'][k[0]] for k in keys],
                              yearly=yearly(ctx, r, ctx['REAL'])))
    result = dict(config=vars(ctx['args']), fit=formal, yearly=observed, four=secondary, ie9=baseline,
        random=dict(seed=RANDOM_SEED, draws=draws, yearly=random), ablation=ablations,
        details=previous.target_details(ctx, ranks, ctx['REAL']), shuffled=[],
        final_year_evaluated=True, diagnostics_complete=False, fingerprints=fingerprints(),
        resources=capacity('formal_evaluation'))
    previous.write(OUTPUT, result)
    log('FINAL_YEAR_ONCE', observed, 'CV', formal['yearly_cv'])


def run_stage(ctx, stage):
    capacity('start_'+stage)
    expected = dict(library='std_v1_1', filter='h4nan', learn='0,1,2', bins='3,5,10',
        max_attrs=7, cooldown=10, smooth=2., beam=1, train_edges=True, own_scan=False,
        one_per_family=False, drop='', obj='hit', holdout='2026H1,2026H2', inner_cv=True,
        mix=0, em=0, bag=False, interval=False, nested=0, renew=0, learn_all=False, slots='')
    if any(getattr(ctx['args'], k) != v for k, v in expected.items()):
        raise ValueError('configuration differs from IE40 preregistration')
    if ctx['WEIGHTS'] != (0, .5, 1, 1.5, 2, 3) or ctx['NAMES'] != list(standard.V1_1_NAMES):
        raise ValueError('weight menu or frozen library changed')
    totals = {year: sum(bool(t[3]) for t in ctx['REAL'] if t[2][:4] == year) for year in YEARS}
    if list(totals.values()) != [11, 17, 23]:
        raise ValueError('primary target counts changed')
    execution = WORK/'execution.json'
    if execution.exists():
        if json.loads(execution.read_text())['fingerprints'] != fingerprints():
            raise ValueError('source changed during execution')
    else:
        previous.write(execution, dict(fingerprints=fingerprints(), primary_targets=totals))
    if stage == 'evaluate':
        evaluate_frozen(ctx)
    elif stage == 'fit':
        row = fit_profiles(ctx, ctx['REAL'], 'real')
        previous.write(WORK/'real_fit.json', row)
    else:
        seed = ctx['args'].ie40_shuffle_seed
        if seed not in SHUFFLE_SEEDS or not OUTPUT.exists():
            raise ValueError('shuffle requires a registered seed and frozen formal evaluation')
        fake = previous.shuffled_labels(ctx, seed)
        row = fit_profiles(ctx, fake, f'shuffle_{seed}')
        row.update(seed=seed, yearly=yearly(ctx, ctx['ranks_of'](np.load(WORK/f'shuffle_{seed}_scores.npy')), fake))
        previous.write(WORK/f'shuffle_{seed}.json', row)
        log('SHUFFLE_COMPLETE', seed, row['yearly'], row['yearly_cv'])


def worker_flags(stage, seed=0):
    return ['--library', 'std_v1_1', '--filter', 'h4nan', '--learn', '0,1,2', '--bins', '3,5,10',
            '--max-attrs', '7', '--cooldown', '10', '--holdout', '2026H1,2026H2', '--inner-cv',
            '--train-edges', '--drop', '', '--tag', 'ie40', '--ie40-stage', stage,
            '--ie40-shuffle-seed', str(seed)]


def run_jobs(jobs, workers):
    import subprocess
    pending, active, peaks = list(jobs), [], []
    aggregate = 0
    environment = {**os.environ, 'OPENBLAS_NUM_THREADS': '1', 'OMP_NUM_THREADS': '1',
                   'MKL_NUM_THREADS': '1', 'NUMEXPR_NUM_THREADS': '1', 'PYTHONDONTWRITEBYTECODE': '1'}
    try:
        while pending or active:
            while pending and len(active) < workers:
                stage, seed = pending.pop(0)
                name = f'shuffle_{seed}' if seed else stage
                stream = (WORK/(name+'.log')).open('a')
                command = [sys.executable, '-m', 'studies.trader_replication.martin_profile_ie29']+worker_flags(stage, seed)
                process = subprocess.Popen(command, cwd=ROOT, env=environment, stdout=stream, stderr=subprocess.STDOUT)
                active.append((stage, seed, process, stream))
                log('worker started', stage, seed, process.pid)
            for item in list(active):
                stage, seed, process, stream = item
                if process.poll() is None:
                    continue
                stream.close()
                active.remove(item)
                if process.returncode:
                    raise RuntimeError(f'worker failed: {stage} {seed}; inspect its log')
                path = OUTPUT if stage == 'evaluate' else WORK/(f'shuffle_{seed}.json' if seed else 'real_fit.json')
                peaks.append(json.loads(path.read_text())['resources']['peak_rss_bytes'])
                log('worker completed', stage, seed)
            rss = [process_rss(os.getpid())]+[process_rss(p.pid) for _, _, p, _ in active]
            aggregate = max(aggregate, sum(rss))
            if any(v > 900_000_000 for v in rss) or sum(rss) > 1_800_000_000:
                raise RuntimeError('parallel memory limit exceeded')
            capacity('driver')
            if active:
                time.sleep(1)
    finally:
        for _, _, process, stream in active:
            if process.poll() is None:
                process.terminate()
                process.wait()
            stream.close()
    upper = capacity('driver_complete')['peak_rss_bytes']+sum(sorted(peaks, reverse=True)[:workers])
    if upper > 1_800_000_000:
        raise RuntimeError('recorded peaks exceed aggregate budget')
    return dict(workers=workers, process_peak_bytes=peaks, aggregate_upper_bound_bytes=upper,
                monitored_aggregate_peak_bytes=aggregate)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workers', choices=(1, 2), type=int, default=1)
    args = parser.parse_args()
    WORK.mkdir(exist_ok=True)
    capacity('before_run')
    protected = json.loads((WORK/'protected_before.json').read_text())
    if any(sha(ROOT/name) != value for name, value in protected.items()):
        raise ValueError('protected input or prior result changed')
    inputs = json.loads((WORK/'inputs_before.json').read_text())
    if any(sha(ROOT/name) != value['sha256'] for name, value in inputs.items()):
        raise ValueError('cached input changed since preregistration')
    resources = dict(fit=run_jobs([('fit', 0)], 1), evaluate=run_jobs([('evaluate', 0)], 1),
                     shuffle=run_jobs([('shuffle', seed) for seed in SHUFFLE_SEEDS], args.workers))
    result = json.loads(OUTPUT.read_text())
    result['shuffled'] = [json.loads((WORK/f'shuffle_{seed}.json').read_text()) for seed in SHUFFLE_SEEDS]
    if any(row['fingerprints'] != result['fingerprints'] for row in result['shuffled']):
        raise ValueError('diagnostic source differs from the formal source')
    result.update(diagnostics_complete=True, parallel_resources=resources, resources=capacity('complete'))
    previous.write(OUTPUT, result)
    if any(sha(ROOT/name) != value for name, value in protected.items()):
        raise ValueError('protected input or prior result changed')
    if any(sha(ROOT/name) != value['sha256'] for name, value in inputs.items()):
        raise ValueError('cached input changed during execution')
    log('COMPLETE', result['yearly'], result['fit']['yearly_cv'], resources)


if __name__ == '__main__':
    main()
