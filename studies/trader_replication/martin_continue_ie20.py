"""IE20: observation-led setup queues, narrower signals and premier ADR bands."""
from __future__ import annotations

import argparse
import gc
import importlib.util
from itertools import combinations
from pathlib import Path
import resource
import time

import numpy as np

from studies.trader_replication import martin_continue_ie19 as previous

old = previous.old
ROOT, REPORTS, FIXED = previous.ROOT, previous.REPORTS, previous.FIXED
WORK = REPORTS / 'ie20_work'
PREFIX = 'strong_continue_ie20_'
PLAN = ROOT / 'studies/martin_luk/notes/PLAN_IE20_CN.md'
PREREG = ROOT / 'studies/martin_luk/notes/PREREG_IE20_CN.md'
BASE = dict(previous.BASE, queue20='base', signal20='base', pool20='base')
SEEDS, REFERENCE = previous.SEEDS, previous.REFERENCE
selector = previous.previous.previous.previous
Data = previous.Data
admissible, better, offline = previous.admissible, previous.better, previous.offline

# Reuse the fixed account, diagnostics and scorecard in an isolated namespace.
_spec = importlib.util.spec_from_file_location(__name__ + '_engine', previous.__file__)
engine = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(engine)
shared = engine.shared
run_account, diagnosis = engine.run_account, engine.diagnosis


def output(name, value):
    old.save(REPORTS / (PREFIX + name + '.json'), value)


def selection_row(s, d, cfg, template):
    """One night only; EP is identified from that completed day's gap."""
    pool = template['pool'][s].copy()
    f, c = d.f, d.px['close'][s]
    unit = f['adr'][s] / 100
    x9 = old.lib.divide(old.lib.divide(c, f['e9'][s]) - 1, unit)
    x21 = d.strength['extension'][s]
    if cfg['pool20'] != 'base':
        threshold = 4 if cfg['pool20'] == 'premier4' else 3
        extra = (f['money'][s] >= 100e6) & (f['adr'][s] > threshold)
        if cfg['pool20'] == 'premier3_near':
            extra &= (x9 >= 0) & (x9 <= 1)
        pool |= extra
    signal = pool & template['trend'][s] & template['setup'][s]
    ep, pull = f['ep'][s] == 1, f['pullback'][s] == 1
    mode = cfg['signal20']
    if mode in ('near', 'near_momentum'):
        keep = (x21 >= 0) & (x21 <= 2)
        if mode == 'near_momentum':
            keep &= c > d.px['close'][max(0, s - 20)]
        signal &= ep | keep
    elif mode == 'structure':
        declined = np.zeros(len(c), bool)
        for lag in range(3):
            if s - lag > 0:
                declined |= d.px['close'][s - lag] < d.px['close'][s - lag - 1]
        signal &= ep | ~pull | declined | (f['inside'][s] == 1) | (f['narrow'][s] == 1)
    elif mode == 'trend':
        signal &= ep | ~pull | ((f['e9'][s] > f['e21'][s]) & (x9 >= 0) & (x9 <= 1))
    return pool, signal


def queue_keys(s, d, cfg, signals):
    indices, primary, _ = previous.queue_scores(s, d, cfg, signals)
    rank = previous.previous.previous.percentile
    ep, pull = d.f['ep'][s, indices] == 1, d.f['pullback'][s, indices] == 1
    x = d.strength['extension'][s, indices]
    launch = rank(-np.maximum(np.maximum(-x, x - 2), 0))
    mode = cfg['queue20']
    if mode == 'cap_money':
        primary = (launch + rank(np.minimum(d.f['money'][s, indices], 100e6))) / 2
    elif mode in ('adr', 'typed'):
        adr = (launch + rank(d.f['adr'][s, indices])) / 2
        primary = np.where(~ep & (~pull if mode == 'typed' else True), adr, primary)
    preferred = None
    if mode in ('ep_one', 'typed'):
        group = np.flatnonzero(ep)
        if len(group):
            c = d.px['close']
            growth = old.lib.divide(c[s, indices[group]], c[s - 1, indices[group]]) - 1
            activity = d.wave['own_money'][s, indices[group]]
            activity_score = (rank(growth) + rank(activity)) / 2
            preferred = min(group, key=lambda k: (-activity_score[np.searchsorted(group, k)], d.codes[indices[k]]))
    return {int(j): (0 if k == preferred else 1, -float(primary[k]), d.codes[j])
            for k, j in enumerate(indices)}


def build(d, cfg):
    ident = old.key(cfg)
    cachekey = old.key(dict(cfg=cfg, short=None))
    if d.latest is not None and d.latest[0] == ident:
        d.built[cachekey] = d.latest[1]
        return d.latest[1]
    if d.template is None:
        d.template = selector.selection_arrays(d, previous.BASE)
    b = dict(d.template)
    pool = np.zeros_like(b['pool'])
    signals = np.zeros_like(pool)
    triggers = np.zeros_like(pool)
    book = [[] for _ in range(2 * len(d.days))]
    for s in range(len(d.days)):
        pool[s], signals[s] = selection_row(s, d, cfg, d.template)
        t = s + 1
        if t < d.start or t >= d.end:
            continue
        keys = queue_keys(s, d, cfg, signals[s])
        for j, key in keys.items():
            event = selector.order(t, j, d, cfg)
            if event is not None:
                triggers[s, j] = True
                if b['market'][s]:
                    book[2 * t].append((key, *event[1:]))
    b.update(pool=pool, signals=dict(long=signals, short=np.zeros_like(pool)), triggers=triggers,
             book=book, short_market=np.ones(len(d.days), bool))
    d.built.clear()
    d.built[cachekey] = b
    d.latest = ident, b
    return b


def score(d, cfg, account, labels, supplied=False):
    build(d, cfg)
    return old.score(d, cfg, account, labels, supplied=supplied)


def proposals(number, effective):
    if number <= 3:
        field, values = {
            1: ('queue20', ('ep_one', 'cap_money', 'adr', 'typed')),
            2: ('signal20', ('near', 'structure', 'trend', 'near_momentum')),
            3: ('pool20', ('premier4', 'premier3', 'premier3_near')),
        }[number]
        return [dict(BASE, **{field: value}) for value in values] + [dict(BASE)]
    choices = []
    for size in (2, 3):
        for group in combinations('ABC', size):
            if all(n in effective for n in group):
                cfg = dict(BASE)
                for n in group:
                    field = dict(A='queue20', B='signal20', C='pool20')[n]
                    cfg[field] = effective[n]['config'][field]
                choices.append(cfg)
    return choices


def source_functions():
    paths = {Path(__file__), Path(previous.__file__), Path(previous.previous.__file__),
             Path(previous.previous.previous.__file__), Path(selector.__file__),
             Path(selector.previous.__file__), Path(old.__file__), Path(old.system.__file__),
             Path(old.lib.__file__), WORK / 'observe.py'}
    return {str(p.relative_to(ROOT)): old.sha(p) for p in sorted(paths)}


def prepare():
    path = WORK / 'prepared.json'
    if path.exists():
        return
    prior = old.read(previous.WORK / 'prepared.json')
    paths = {ROOT / p for p in prior['inputs']}
    paths.update(old.WORK / ('phase_' + n + '.npy') for n in ('open', 'high', 'low', 'close'))
    paths.update((old.WORK / 'turnover.npy', previous.WORK / 'prepared.json',
        REPORTS / 'strong_continue_ie19_final_diagnosis.json',
        REPORTS / (PREFIX + 'observations.json'), REPORTS / (PREFIX + 'observations_CN.md'),
        REPORTS / (PREFIX + 'comparisons.csv')))
    old.save(path, dict(source=old.sha(__file__), shape=prior['shape'],
        inputs={str(p.relative_to(ROOT)): old.sha(p) for p in sorted(paths)},
        input_snapshot=old.sha(WORK / 'initial_inputs.json')))


def seal():
    state = dict(source=source_functions(), plan=old.sha(PLAN), prereg=old.sha(PREREG),
        prepared=old.sha(WORK / 'prepared.json'), baseline=BASE, fixed=FIXED)
    path = WORK / 'run_source.json'
    if path.exists():
        if old.read(path) != state:
            raise AssertionError('IE20 frozen research inputs or logic changed')
    else:
        old.save(path, state)
        (WORK / 'research_source.txt').write_text(Path(__file__).read_text())


def search(d, labels, tag, held=None):
    path = WORK / 'searches' / (tag + '.json')
    if path.exists():
        return old.read(path)
    training = old.training_rows(labels, held)
    floor = shared.measure(d, BASE, training)
    chosen, exploration = floor, floor
    effective, rounds = {}, []
    for number in range(1, 5):
        choices = proposals(number, effective)
        if not choices:
            continue
        regpath = WORK / 'registrations' / (tag + '_r' + str(number) + '.json')
        registration = dict(tag=tag, heldout=held, round=number, candidates=choices,
            training_ids=sorted(r['id'] for r in training), incumbent=chosen['config'],
            effective={n: r['config'] for n, r in effective.items()},
            logic=source_functions(), prereg=old.sha(PREREG))
        if regpath.exists() and old.read(regpath) != registration:
            raise AssertionError('IE20 round registration changed')
        if not regpath.exists():
            old.save(regpath, registration)
        results, best_group = [], floor
        for cfg in choices:
            result = shared.measure(d, cfg, training)
            eligible = admissible(result['metrics'], floor['metrics'])
            useful = eligible and better(result['metrics'], floor['metrics'])
            result.update(admissible=eligible, effective=useful)
            results.append(result)
            if eligible and better(result['metrics'], chosen['metrics']):
                chosen = result
            if useful and better(result['metrics'], best_group['metrics']):
                best_group = result
            if better(result['metrics'], exploration['metrics']):
                exploration = result
            print(tag, 'round', number, cfg['queue20'], cfg['signal20'], cfg['pool20'],
                  'bought', result['metrics']['bought'], 'weight', round(result['metrics']['weighted_coverage'], 5), flush=True)
        if number <= 3 and best_group is not floor:
            effective['ABC'[number - 1]] = best_group
        round_ = dict(round=number, registration=str(regpath.relative_to(ROOT)), candidates=results,
                      selected=chosen['config'], metrics=chosen['metrics'])
        rounds.append(round_)
        old.save(WORK / 'rounds' / (tag + '_r' + str(number) + '.json'), round_)
        gc.collect()
    result = dict(tag=tag, heldout=held, config=chosen['config'], metrics=chosen['metrics'], floor=floor['metrics'],
        effective={n: r['config'] for n, r in effective.items()}, rounds=rounds,
        exploratory_config=exploration['config'], exploratory_metrics=exploration['metrics'])
    old.save(path, result)
    return old.clean(result)


for namespace in (engine, shared, shared.shared):
    for name in ('WORK', 'PREFIX', 'PLAN', 'PREREG', 'BASE', 'FIXED', 'Data', 'build', 'run_account',
                 'score', 'diagnosis', 'proposals', 'source_functions', 'seal', 'search', 'output'):
        setattr(namespace, name, globals()[name])
cross_validation, run_search = shared.cross_validation, shared.run_search
initial_diagnosis, finalize = shared.initial_diagnosis, shared.finalize


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=('prepare', 'diagnose', 'search', 'finalize'))
    parser.add_argument('--tag')
    args = parser.parse_args()
    offline()
    start = time.monotonic()
    if args.command == 'prepare':
        prepare()
    elif args.command == 'diagnose':
        initial_diagnosis()
    elif args.command == 'finalize':
        finalize()
    else:
        for tag in ([args.tag] if args.tag else ['true', *('shuffle_' + str(s) for s in SEEDS)]):
            run_search(tag)
            gc.collect()
    print('seconds', round(time.monotonic() - start, 1), 'RSS MiB',
          round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1), flush=True)


if __name__ == '__main__':
    main()
