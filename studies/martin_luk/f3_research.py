"""F3 offline daily-bar leader rearming and account experiments."""
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict, replace
import gc
import json
import os
from pathlib import Path
import resource
import sys
import time
from unittest.mock import patch

import numpy as np

from . import m3_research as M3
from studies.trader_replication import standard_indicators as SI

M2, M, Y = M3.M2, M3.M, M3.Y
ROOT, HOME, PREP = M3.ROOT, M3.HOME, M3.PREP
OUT = HOME/'reports/f3_work'
PREREG = HOME/'notes/PREREG_F3_CN.md'
TRAIN, VALID, CUT = M3.TRAIN, M3.VALID, M3.CUT
BASE = dict(add='one', trail='e21', trims=[], cap=.5)
CANDIDATES = dict(V1=dict(peer=False, funding=False), V2=dict(peer=True, funding=False),
                  V3=dict(peer=True, funding=True))
read, sha, clean, log = M.read, M.sha, M.clean, M.log
FEATURES = ('active', 'armed', 'fire', 'pool', 'peers', 'peer_rank', 'width', 'rotation')


def write(path, value):
    M.write(path if isinstance(path, Path) else OUT/path, value)


def offline():
    sys.dont_write_bytecode = True
    def guard(event, args):
        if event in ('socket.connect', 'socket.bind', 'socket.getaddrinfo', 'subprocess.Popen', 'os.system'):
            raise PermissionError('F3 is offline and single-process')
        if event == 'open' and not isinstance(args[0], int) and args[2] & (
                os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND):
            p = Path(os.fsdecode(args[0])).resolve()
            if not (p.is_relative_to(OUT.resolve()) or p == (HOME/'reports/F3_CN.md').resolve()):
                raise PermissionError('F3 output boundary: '+str(p))
    sys.addaudithook(guard)


def once(stage):
    with (OUT/(stage+'_started.json')).open('x') as f:
        json.dump(dict(time=time.time(), source=sha(Path(__file__)),
            memory=Path('/proc/meminfo').read_text()), f)


def freeze():
    once('protocol')
    paths = [HOME/'notes/legs_frozen.json', HOME/'notes/trades.csv', HOME/'replicate.py',
        ROOT/'studies/trader_replication/systems.py', ROOT/'studies/trader_replication/mainleg.py',
        ROOT/'studies/trader_replication/martin_profile_f2.py', HOME/'u1_research.py']
    paths += [HOME/(n+'_research.py') for n in ('m1', 'm2', 'm3')]
    paths += sorted((ROOT/'studies/trader_screens').glob('*.py'))
    for folder in ('m1_work', 'm2_work', 'm3_work', 'u1_work', 'f2_work'):
        paths += [p for p in (HOME/'reports'/folder).rglob('*') if p.is_file()]
    protected = {str(p.relative_to(ROOT)): sha(p) for p in paths}
    sources = [Path(__file__), HOME/'f3_report.py', HOME/'tests/test_f3.py',
               ROOT/'studies/trader_replication/system.py']
    write('protocol.json', dict(task='PLAN_F3_CN', train=TRAIN, validation=VALID, cutoff=CUT,
        specs=CANDIDATES, execution=BASE, prereg_sha256=sha(PREREG),
        source_sha256={str(p.relative_to(ROOT)): sha(p) for p in sources},
        protected=protected, resources=M3.resource_observation(),
        labels='evaluation only, after simulation; no ticker/date identity in source or sizing',
        independent_out_of_sample=False, offline=True))
    log('F3 preregistration, implementations and original inputs frozen')


def registry_check():
    r = read(OUT/'protocol.json')
    assert sha(PREREG) == r['prereg_sha256'], 'preregistration changed'
    assert all(sha(ROOT/p) == h for p, h in r['source_sha256'].items()), 'frozen implementation changed'
    return r


def leader_step(active, armed, last_strong, day, strong, eligible, survives, pool, touch, action):
    """Consume each pullback once; weak tape exits clear pending opportunities."""
    last_strong = np.where(strong, day, last_strong)
    active = (active | ((day-last_strong < 120) & eligible)) & survives
    armed = (armed | touch) & active
    fire = armed & action & pool
    return active, armed & ~fire, last_strong, fire


def action_at(A, d):
    c, o, lo, hi = (A[n][d].astype(float) for n in ('close', 'open', 'low', 'high'))
    pc, ph = A['close'][d-1].astype(float), A['high'][d-1].astype(float)
    e9, e21 = A['e9'][d-1], A['e21'][d-1]
    reclaim = (c > o) & (((lo <= e9) & (c >= e9)) | ((lo <= e21) & (c >= e21)))
    handshake = (o > pc*1.01) & (lo <= np.maximum(ph, e9)) & (c > np.minimum(ph, e9))
    return (c > ph) | reclaim | handshake


def queue_key(category, width, peers, strength):
    return (-int(category), float(width), -int(peers), -float(strength) if np.isfinite(strength) else 1.)


def feature_inputs(A, label):
    """Per-date cross sections, trailing windows and at most 128-square correlations."""
    from .u1_research import peer_queries
    meta = read(HOME/'reports/u1_work/prepare.json')
    assert meta['codes'] == list(A['codes'])
    assert meta['days'][:len(A['days'])] == list(A['days'])
    raw = np.load(HOME/'reports/u1_work/panel/raw_close.npy', mmap_mode='r')
    assert raw.shape[1] == len(A['codes']) and raw.shape[0] >= len(A['days'])
    folder = OUT/'features'/label
    folder.mkdir(parents=True, exist_ok=True)
    shape = A['close'].shape
    f = {}
    for name in FEATURES:
        dtype = bool if name in ('active', 'armed', 'fire', 'pool') else 'float32'
        f[name] = np.lib.format.open_memmap(folder/(name+'.npy'), mode='w+', dtype=dtype, shape=shape)
        f[name][:] = False if dtype is bool else np.nan
    active, armed = np.zeros(shape[1], bool), np.zeros(shape[1], bool)
    seen = np.full(shape[1], -1000, int)
    with (folder/'nightly.jsonl').open('w') as nights, np.errstate(all='ignore'):
        for d, day in enumerate(A['days']):
            c = A['close'][d].astype(float)
            raw_today = raw[d].astype(float)
            if label == 'perturbed' and day > CUT:
                raw_today *= 3
            pool = (raw_today >= 2) & (A['to20'][d] >= 50e6) & (A['adr'][d] >= 3) & np.isfinite(c)
            returns, ranks = {}, {}
            for n in (21, 63, 126):
                ret = c/A['close'][d-n].astype(float)-1 if d >= n else np.full(shape[1], np.nan)
                ranks[n] = np.full(shape[1], np.nan)
                ranks[n][pool] = SI.midrank(ret[pool])
                returns[n] = ret
            strong = (ranks[126] >= 80) | (ranks[21] >= 90) | (ranks[63] >= 90)
            survives = A['weekly_up'][d] & (c >= A['e50'][d]) & np.isfinite(c)
            near = np.minimum(abs(c/A['e9'][d]-1), abs(c/A['e21'][d]-1)) <= A['adr'][d]/100
            touch = near & ((A['low'][d] < A['low'][d-1]) | (c <= A['close'][d-1])) if d else near
            action = action_at(A, d) if d else np.zeros(shape[1], bool)
            active, armed, seen, fire = leader_step(active, armed, seen, d, strong, survives,
                                                    survives, pool, touch, action)
            count, strength = np.zeros(shape[1]), np.full(shape[1], np.nan)
            query, cohort = np.flatnonzero(active), np.flatnonzero(pool)
            if d >= 60 and len(query) and len(cohort):
                peers = peer_queries(A['close'][d-60:d+1, cohort].astype(float),
                    A['close'][d-60:d+1, query].astype(float), returns[21][cohort], ranks[21][cohort],
                    returns[21][query], A['codes'][cohort], A['codes'][query])
                count[query], strength[query] = peers[:, 0], peers[:, 2]
            width = np.full(shape[1], np.inf)
            if d:
                for j in np.flatnonzero(np.isfinite(c) & (c > 0)):
                    stop = M.M.capped_stop(float(c[j]), float(A['low'][d, j]), A['adr'][d-1, j])
                    if stop is not None:
                        width[j] = (c[j]-stop)/c[j]
            category = np.where(active & (armed | fire), 2, np.where(active & (count > 0), 1, 0))
            keys = [queue_key(category[j], width[j], count[j], strength[j]) for j in range(shape[1])]
            levels = {key: -rank for rank, key in enumerate(sorted(set(keys)))}
            rotation = np.array([levels[key] for key in keys], dtype='float32')
            for name, value in dict(active=active, armed=armed, fire=fire, pool=pool, peers=count,
                                    peer_rank=strength, width=width, rotation=rotation).items():
                f[name][d] = value
            nights.write(json.dumps(dict(day=str(day), count=int(active.sum()), pool=int(pool.sum()),
                armed=int(armed.sum()), fire=int(fire.sum()), codes=list(map(str, A['codes'][active]))))+'\n')
            if d and d % 200 == 0:
                log(f'F3 {label} market features {d}/{len(A["days"])}')
    for value in f.values():
        value.flush()
    write(folder/'meta.json', dict(days=A['days'], codes=A['codes'], dataset_digest=A['digest'],
        sha256={n: sha(folder/(n+'.npy')) for n in FEATURES}, resources=M3.resource_observation(),
        max_correlation_block=[128, 128], labels_read=False))
    A['_f3'] = f
    return f


def features(A, label='train'):
    if '_f3' in A:
        return A['_f3']
    folder = OUT/'features'/label
    meta = read(folder/'meta.json')
    assert list(A['days']) == meta['days'] and list(A['codes']) == meta['codes']
    A['_f3'] = {n: np.load(folder/(n+'.npy'), mmap_mode='r') for n in FEATURES}
    return A['_f3']


def new_book(A, f):
    out = [[] for _ in A['days']]
    for d in range(1, len(out)):
        order = sorted(np.flatnonzero(f['fire'][d]), key=lambda j: (-A['to20'][d, j], str(A['codes'][j])))
        for rank, j in enumerate(order):
            fill = float(A['close'][d, j])
            stop = M.M.capped_stop(fill, float(A['low'][d, j]), A['adr'][d-1, j])
            if stop is not None:
                out[d].append(((0, d, rank, str(A['codes'][j])), int(j), 1, fill, stop, 'f3_rearm', None))
    return out


def build(A, directory, spec, original=None):
    book, rules, ema = M3.build(A, directory, BASE, original=original)
    f = features(A)
    book = M.merge_books(book, new_book(A, f))
    if spec['funding']:
        rules = replace(rules, rotate_score='_f3_rotation', max_open=11, max_new_risk=.02,
                        add_after_entries=True, rotate_actual_adds=True)
        ema['_f3_rotation'] = f['rotation']
    out = []
    for d, row in enumerate(book):
        keyed = []
        for e in row:
            j = e[1]
            if spec['funding']:
                cat = 2 if f['fire'][d, j] else int(f['active'][d, j] and f['peers'][d, j] > 0)
                key = queue_key(cat, (e[3]-e[4])/e[3], f['peers'][d, j], f['peer_rank'][d, j])
                priority = ((*key, e[0][0]), *e[0][1:])
            elif spec['peer']:
                strength = f['peer_rank'][d, j]
                priority = ((int('retry' in e[5]), -float(f['peers'][d, j]),
                    -float(strength) if np.isfinite(strength) else 1., e[0][0]), *e[0][1:])
            else:
                priority = e[0]
            keyed.append((priority, *e[1:]))
        out.append(keyed)
    if spec['funding']:
        rules = replace(rules, make_room_kind={})
    return out, rules, ema


def run(A, name, spec, span=TRAIN, directory=PREP):
    old_out, old_build, sim = M.OUT, M.build, Y.simulate
    M.OUT = OUT
    M.build = lambda a, d, s: build(a, d, spec, original=old_build)
    def capture(*args, **kwargs):
        result = sim(*args, **kwargs)
        track = kwargs.get('track')
        if track is not None:
            write(name+'/management.json', {k: v for k, v in track.items() if k != 'entry_attempts'})
        return result
    try:
        with patch.object(Y, 'simulate', capture):
            return M.evaluate(A, directory, name, M3.BASE, span)
    finally:
        M.OUT, M.build = old_out, old_build


def select(runs, baseline):
    outcome = M.select(runs, baseline)
    def key(name):
        rows = [runs[name]['years'][y] for y in ('2024', '2025')]
        return (-min(r['target_count'] for r in rows), -min(r['cap_equity'] for r in rows),
            -min(r['purity_gross'] or 0. for r in rows),
            -min(r['coverage']['including_censored']['covered'] for r in rows),
            max(r['maxdd'] for r in rows), name)
    outcome['eligible'] = sorted(outcome['eligible'], key=key)
    outcome['chosen'] = next(iter(outcome['eligible']), None)
    return outcome


def prepare():
    registry_check()
    once('prepare_train')
    feature_inputs(M3.arrays(), 'train')


def candidates():
    registry_check()
    once('candidates')
    A, runs = M3.arrays(), {}
    features(A)
    for name, spec in CANDIDATES.items():
        runs[name] = run(A, 'candidates/'+name, spec)[0]
        write('candidates_train.json', runs)
        gc.collect()
    baseline = M.summary(read(HOME/'reports/m2_work/candidates/M2A/metrics.json'))
    write('selection.json', dict(select(runs, baseline), baseline=baseline,
        prereg_sha256=sha(PREREG), resources=M3.resource_observation()))


def compatibility():
    registry_check()
    once('compatibility')
    checks = {}
    for label, directory, span in (('train', PREP, TRAIN),
            ('continuous', HOME/'reports/m1_work/validation_prepared', (TRAIN[0], VALID[1]))):
        A = M3.arrays(directory)
        for name, spec in (('M2A', {}), ('M3B', BASE)):
            book, rules, ema = M3.build(A, directory, spec)
            px = dict(dates=A['days'], **{n: A[n].astype(float) if n != 'codes' else A[n]
                                        for n in ('open', 'high', 'low', 'close', 'codes')})
            curve, days, trades = Y.simulate(px, ema, rules, book, *span, audit=True)
            base = HOME/('reports/m2_work' if name == 'M2A' else 'reports/m3_work')
            ref = base/('candidates/'+name if label == 'train' else 'validation/continuous')
            checks[name+'_'+label] = dict(trades=clean(trades) == read(ref/'trades.json'),
                curve=clean(dict(days=days, equity=curve)) == read(ref/'curve.json'),
                reference_sha256={n: sha(ref/(n+'.json')) for n in ('trades', 'curve')},
                executions=sum(len(t['executions']) for t in trades))
            assert checks[name+'_'+label]['trades'] and checks[name+'_'+label]['curve'], (name, label)
            log('original ledger unchanged: '+name+' '+label)
        del A, px, book, ema, trades
        gc.collect()
    write('compatibility.json', dict(ok=True, checks=checks, resources=M3.resource_observation()))


def prefix_value(A, directory, spec):
    book, rules, ema = build(A, directory, spec)
    px = dict(dates=A['days'], **{n: A[n].astype(float) if n != 'codes' else A[n]
                                for n in ('open', 'high', 'low', 'close', 'codes')})
    curve, days, trades = Y.simulate(px, ema, rules, book, *TRAIN, audit=True)
    k = int(np.searchsorted(A['days'], CUT, side='right'))
    return clean(dict(book=book[:k], events=M.E15.B.execution_events(trades, CUT),
        curve=[float(v) for d, v in zip(days, curve) if d <= CUT]))


def prefix():
    registry_check()
    once('prefix')
    selected = read(OUT/'selection.json')['chosen']
    name = selected or 'V3'
    values, checks, feature_checks = {}, {}, {}
    for label, directory in (('full', PREP), ('cut', HOME/'reports/m1_work/prefix_cut'),
                              ('perturbed', HOME/'reports/m1_work/prefix_perturbed')):
        A = M3.arrays(directory)
        if label != 'full':
            path = HOME/('reports/m2_work/profile_'+label+'_G1')
            A['_m2_G1'] = np.load(path.with_suffix('.npy'), mmap_mode='r'), read(path.with_suffix('.json'))
        A['_m2_perturb_qqq'] = label == 'perturbed'
        f = feature_inputs(A, label)
        values[label] = prefix_value(A, directory, CANDIDATES[name])
        write('prefix_'+label+'.json', values[label])
        reference = OUT/'features/full'
        k = int(np.searchsorted(A['days'], CUT, side='right'))
        feature_checks[label] = {n: np.array_equal(f[n][:k], np.load(reference/(n+'.npy'),
            mmap_mode='r')[:k], equal_nan=True) for n in FEATURES}
        del A, f
        gc.collect()
    checks = {label: {k: values[label][k] == values['full'][k] for k in values['full']}
              for label in ('cut', 'perturbed')}
    stored = read(OUT/f'candidates/{name}/trades.json')
    assert values['full']['events'] == clean(M.E15.B.execution_events(stored, CUT))
    assert all(all(v.values()) for v in checks.values()), checks
    assert all(all(v.values()) for v in feature_checks.values()), feature_checks
    write('truncation.json', dict(ok=True, selected=selected, tested=name, cutoff=CUT, checks=checks,
        feature_checks=feature_checks, events=len(values['full']['events']),
        reused_inputs={str(p.relative_to(ROOT)): sha(p) for label in ('cut', 'perturbed') for p in
            (HOME/('reports/m2_work/profile_'+label+'_G1.npy'), HOME/('reports/m2_work/profile_'+label+'_G1.json'),
             HOME/('reports/m2_work/profile_'+label+'_complete.json'))}, resources=M3.resource_observation()))


def validate():
    registry_check()
    choice = read(OUT/'selection.json')['chosen']
    assert read(OUT/'truncation.json')['ok']
    once('validation' if choice else 'validation_features')
    directory = HOME/'reports/m1_work/validation_prepared'
    A, runs = M3.arrays(directory), {}
    feature_inputs(A, 'validation')
    if not choice:
        write('validation_complete.json', dict(skipped=True, reason='no eligible candidate',
            standalone_evaluations=0, continuous_evaluations=0, market_features_only=True,
            resources=M3.resource_observation()))
        return
    for label, span in (('standalone', VALID), ('continuous', (TRAIN[0], VALID[1]))):
        runs[label] = run(A, 'validation/'+label, CANDIDATES[choice], span, directory)[0]
        write('validation.json', runs)
    write('validation_complete.json', dict(chosen=choice, standalone_evaluations=1,
        continuous_evaluations=1, resources=M3.resource_observation(), independent_out_of_sample=False))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('stage', choices=('freeze', 'prepare', 'compatibility', 'candidates', 'prefix', 'validate'))
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    offline()
    globals()[args.stage]()


if __name__ == '__main__':
    main()
