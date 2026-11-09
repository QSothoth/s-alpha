"""IE27: rerun the fixed IE26 searches with narrow holding coverage."""
import argparse
from functools import lru_cache
from pathlib import Path
import sys

import numpy as np

from studies.trader_replication import martin_continue_ie26 as original

fixed = original.original.isolated(original, __name__ + '.fixed')
p, e, a = fixed.p, fixed.e, fixed.a
ROOT, REPORTS = fixed.ROOT, fixed.REPORTS
WORK, PREFIX = REPORTS / 'ie27_work', 'strong_continue_ie27_'
PLAN = ROOT / 'studies/martin_luk/notes/PLAN_IE27_CN.md'
PREREG = ROOT / 'studies/martin_luk/notes/PREREG_IE27_CN.md'
YARDSTICK = original.YARDSTICK
HALVES, SENTINEL, POSITIVE = fixed.HALVES, fixed.SENTINEL, fixed.POSITIVE
METHODS, BUDGETS, HOLD = ('E', 'A'), (2, 3), 3
SHUFFLES = tuple(range(2026112701, 2026112706))
RANDOM_SEED, RANDOM_TRIALS = fixed.RANDOM_SEED, fixed.RANDOM_TRIALS
sha, digest, clean = fixed.sha, fixed.digest, fixed.clean


def path(name):
    return REPORTS / (PREFIX + name + '.json')


@lru_cache(maxsize=1)
def signature():
    sources = set(original.signature())
    sources.update(str(f.relative_to(ROOT)) for f in (PLAN, PREREG, Path(__file__),
        ROOT / 'studies/trader_replication/ie27_report.py',
        ROOT / 'studies/trader_replication/ie26_report.py',
        ROOT / 'studies/trader_replication/tests/test_martin_continue_ie27.py'))
    sources.add(str(Path(original.__file__).relative_to(ROOT)))
    return {name: sha(ROOT / name) for name in sorted(sources)}


def picks(d, ranks, k=3, permitted=None):
    """Keep the reference's H-night exclusion; actual holding lasts only H nights."""
    h = k
    selected = np.zeros(d.n, bool)
    last = np.full(len(d.code_index), -h - len(d.base.meta['days']) - 1, np.int32)
    allowed = None
    if permitted is not None:
        allowed = np.zeros(d.n, bool)
        allowed[d.rows_for(permitted)] = True
    calendar = {day: t for t, day in enumerate(d.base.meta['days'])}
    for day, sl in d.slices.items():
        if sl.start == sl.stop or (allowed is not None and not allowed[sl.start]):
            continue
        night, count = calendar[day], 0
        for q in np.argsort(ranks[sl], kind='stable') + sl.start:
            code = d.code_ids[q]
            if night - last[code] <= h:
                continue
            selected[q], last[code] = True, night
            count += 1
            if count == k:
                break
    return selected


class Data(fixed.Data):
    def __init__(self):
        super().__init__()
        # Description and paired controls are unchanged from IE26.
        self.baseline_selected = original.picks(self, self.baseline_ranks)
        self.extend_queries()

    def extend_queries(self):
        calendar = self.base.meta['days']
        position = {day: t for t, day in enumerate(calendar)}
        self.eval_query = np.full((len(self.entries), 9), -1, np.int32)
        for i, entry in enumerate(self.entries):
            t = position[entry['entry_date']]
            for w, offset in enumerate(range(-6, 3)):
                if 0 <= t + offset < len(calendar):
                    self.eval_query[i, w] = self.lookup.get(calendar[t + offset], {}).get(entry['code'], -1)
        self.current_eval_query = self.eval_query

    def set_label(self, label, seed=None):
        super().set_label(label, seed)
        self.current_eval_query = self.eval_query if seed is None else self.shuffled(seed, self.eval_query)


def coverage(d, ranks, halves, query=None, permitted=None, k=3, selected=None):
    query = d.current_eval_query if query is None else query
    selected = picks(d, ranks, k, permitted) if selected is None else selected
    hit, first = np.zeros(len(d.entries), bool), np.full(len(d.entries), -1, np.int32)
    for i in np.flatnonzero(np.isin(d.entry_half, halves)):
        q = np.asarray(query[i])[-(7 + k - 1):]
        q = q[q >= 0]
        found = q[selected[q]]
        if len(found):
            hit[i], first[i] = True, found[0]
    return fixed.summarize(d, hit, halves, first)


def initialize(d):
    if path('inputs').exists():
        if read('inputs')['signature'] != signature():
            raise ValueError('IE27 sources changed after initialization')
        return
    before = capacity('inputs')
    matrix_hash = sha(d.matrix_path)
    if matrix_hash != d.prepared['matrix_sha256']:
        raise ValueError('input matrix digest differs')
    assert list(d.slices) == sorted(d.slices)
    flags = winner_flags(d)
    baseline = {}
    old = {method: original.stitched_ranks(d, method) for method in METHODS}
    for k in BUDGETS:
        methods = dict(IE9=d.baseline_ranks, IE26_E=old['E'], IE26_A=old['A'])
        baseline[str(k)] = {}
        for name, ranks in methods.items():
            selected = picks(d, ranks, k)
            baseline[str(k)][name] = dict(coverage=coverage(d, ranks, HALVES, k=k, selected=selected),
                                          precision=fixed.precision(flags, selected))
    trials = fixed.random_controls(d, flags)
    expected = {3: (22, 18, 19, 17.5, 11, 26), 2: (15, 13, 15, 10.6, 3, 18)}
    for k, (ie9, old_e, old_a, mean, low, high) in expected.items():
        hits = [v['budgets'][str(k)]['coverage']['primary']['hit'] for v in trials]
        assert [baseline[str(k)][name]['coverage']['primary']['hit'] for name in ('IE9', 'IE26_E', 'IE26_A')] == [ie9, old_e, old_a]
        assert (round(float(np.mean(hits)), 1), min(hits), max(hits)) == (mean, low, high)
    protected = {ROOT / name for name in original.signature()}
    protected.update((Path(original.__file__), ROOT / 'studies/trader_replication/ie26_report.py',
                      p.SOURCE_WORK / 'ie23_prepared.json'))
    for stage in ('23', '24', '25', '26'):
        for kind in ('PLAN', 'PREREG'):
            protected.add(ROOT / 'studies/martin_luk/notes' / (kind + '_IE' + stage + '_CN.md'))
        protected.update(f for f in REPORTS.glob('strong_continue_ie' + stage + '_*') if f.is_file())
    old_inputs = original.read('inputs')
    mismatches = {name: dict(previous=value, current=sha(ROOT / name))
                  for name, value in old_inputs['signature'].items() if sha(ROOT / name) != value}
    value = dict(signature=signature(), matrix_sha256=matrix_hash, shape=d.x.shape, baseline=baseline,
        pool_precision=fixed.precision(flags, np.ones(d.n, bool)), input_sha256=d.prepared['input_sha256'],
        protected_sha256={str(f.relative_to(ROOT)): sha(f) for f in sorted(protected)},
        entries=d.entries, query=d.query, eval_query=d.eval_query, dataset_digest=d.prepared['dataset_digest'],
        previous_signature_mismatches=mismatches, reuse_previous_description=False,
        before=before, after=capacity('inputs:done'))
    write('inputs', value)
    write('random', dict(seed=RANDOM_SEED, trials=trials, signature=signature()))
    print('BASELINES', {k: {name: row['coverage']['primary']['hit'] for name, row in rows.items()}
                        for k, rows in baseline.items()}, flush=True)


def run_evaluate(d):
    d.set_label('real')
    flags = winner_flags(d)
    results = {method: {str(k): fixed.fold_budget(d, method, k, flags) for k in BUDGETS} for method in METHODS}
    random = read('random')
    maximum = max(read('shuffle_' + str(s))['methods'][method]['primary']['hit'] for s in SHUFFLES for method in METHODS)
    decisions = {}
    for method in METHODS:
        result = results[method]['3']
        hits = result['coverage']['primary']['hit']
        beat = sum(row['budgets']['3']['coverage']['primary']['hit'] < hits for row in random['trials'])
        decisions[method] = dict(hit=hits, beat_random=beat, shuffle_pass=hits > maximum,
            coverage_pass=hits >= 25, random_pass=beat >= 27, passed=hits >= 25 and hits > maximum and beat >= 27,
            precision_pass=result['precision']['rate'] > read('inputs')['pool_precision']['rate'])
    def key(method):
        model = read('final_' + method)['model']
        return (-decisions[method]['hit'], len(model['terms'] if method == 'E' else model['features']), METHODS.index(method))
    qualified = [method for method in METHODS if decisions[method]['passed']]
    selected = min(qualified, key=key) if qualified else None
    write('decision', dict(methods=decisions, selected=selected, display=selected or min(METHODS, key=key),
        shuffle_maximum=maximum, results=results, signature=signature()))
    print('DECISION', decisions, 'selected', selected, flush=True)


def configure():
    for module in (fixed, p, e, a):
        module.WORK, module.PREFIX, module.PLAN, module.PREREG = WORK, PREFIX, PLAN, PREREG
        module.path, module.signature = path, signature
        module.write, module.read = fixed.write, fixed.read
        module.capacity = fixed.capacity
    fixed.BUDGETS, fixed.SHUFFLES, fixed.HOLD = BUDGETS, SHUFFLES, HOLD
    fixed.picks, fixed.coverage = picks, coverage
    fixed.Data, fixed.initialize, fixed.run_evaluate = Data, initialize, run_evaluate


configure()
write, read, capacity, guard = fixed.write, fixed.read, fixed.capacity, fixed.guard
winner_flags, precision, summarize = fixed.winner_flags, fixed.precision, fixed.summarize
ranks_for, rank_path, stitched_ranks = fixed.ranks_for, fixed.rank_path, fixed.stitched_ranks
select_equal, pipeline_a, ablate = fixed.select_equal, fixed.pipeline_a, fixed.ablate
fold_budget = fixed.fold_budget


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=('prepare', 'describe', 'nested', 'final', 'evaluate', 'all'))
    parser.add_argument('--seed', type=int, choices=SHUFFLES)
    args = parser.parse_args()
    fixed.main(args.stage, args.seed)
