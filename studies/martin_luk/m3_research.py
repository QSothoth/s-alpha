"""Offline M3 holding research; reuse frozen M2 selection and Y1 attribution."""
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict, replace
import difflib
import gc
import json
import os
from pathlib import Path
import resource
import sys
import time
from unittest.mock import patch

import numpy as np

from . import m2_research as M2

M, Y = M2.M, M2.Y
ROOT, HOME, PREP = M2.ROOT, M2.HOME, M2.PREP
OUT = HOME/'reports/m3_work'
PREREG = HOME/'notes/PREREG_M3_CN.md'
TRAIN, VALID, CUT = M2.TRAIN, M2.VALID, M2.CUT
BASE = M2.CANDIDATES['M2A']
read, sha, clean, log = M.read, M.sha, M.clean, M.log

# One mechanism per arm, specified before measuring any M3 training result.
DIAGNOSTICS = {
    'confirm_hold': dict(confirm=True),
    'trail9': dict(trail='e9'),
    'trail21': dict(trail='e21'),
    'trail21_two': dict(trail='e21', trail_days=2),
    'no_trim': dict(trims=[]),
    'trim20': dict(trims=[20]),
    'trim35': dict(trims=[3, 5], trim_frac=.15),
    'reentry10': dict(reentry=True),
    'add1': dict(add='one'),
    'add1020': dict(add='r74'),
    'add_high': dict(add='high'),
    'cap50': dict(cap=.5),
    'cap75': dict(cap=.75),
}


def write(path, value):
    M.write(path if isinstance(path, Path) else OUT/path, value)


def offline():
    sys.dont_write_bytecode = True
    def guard(event, args):
        if event in ('socket.connect', 'socket.bind', 'socket.getaddrinfo', 'subprocess.Popen', 'os.system'):
            raise PermissionError('M3 is offline and single-process')
        if event == 'open' and not isinstance(args[0], int) and args[2] & (
                os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND):
            p = Path(os.fsdecode(args[0])).resolve()
            if not (p.is_relative_to(OUT.resolve()) or p == PREREG.resolve() or
                    p == (HOME/'reports/M3_CN.md').resolve()):
                raise PermissionError('M3 output boundary: '+str(p))
    sys.addaudithook(guard)


def once(stage):
    with (OUT/(stage+'_started.json')).open('x') as f:
        json.dump(dict(time=time.time(), source=sha(Path(__file__)),
            memory=Path('/proc/meminfo').read_text()), f)


def resource_observation():
    cg = next(line.split(':', 2)[2] for line in Path('/proc/self/cgroup').read_text().splitlines()
              if line.startswith('0:'))
    folder = Path('/sys/fs/cgroup')/cg.lstrip('/')
    return dict(python=sys.executable, cpu_max=(folder/'cpu.max').read_text().strip(),
        memory_max=(folder/'memory.max').read_text().strip(),
        threads=next(line for line in Path('/proc/self/status').read_text().splitlines() if line.startswith('Threads:')),
        peak_rss_mib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024)


def freeze():
    once('protocol')
    paths = [HOME/'notes/legs_frozen.json', HOME/'notes/trades.csv', HOME/'replicate.py',
        ROOT/'studies/trader_replication/systems.py', ROOT/'studies/trader_replication/mainleg.py',
        HOME/'m1_research.py', HOME/'m2_research.py', HOME/'m2_report.py']
    paths += sorted((HOME/'reports/m2_work').rglob('*'))
    paths += sorted((ROOT/'studies/trader_screens').glob('*.py'))
    paths += [HOME/f'reports/{n}_CN.md' for n in ('M1', 'M2', 'Y1')]
    write('protocol.json', dict(task='PLAN_M3_CN', train=TRAIN, validation=VALID, cutoff=CUT,
        diagnostics=DIAGNOSTICS, base=BASE,
        labels='Y1 labels are read only after simulations, never by build or engine',
        protected={str(p.relative_to(ROOT)): sha(p) for p in paths if p.is_file()},
        resources=resource_observation(),
        scope='single process, one thread, offline; no U1, registry, board or git writes'))
    (OUT/'original_engine.py.txt').write_text(Path(Y.__file__).read_text())
    log('M3 protocol and original artifact hashes frozen')


def arrays(directory=PREP):
    return M2.arrays(directory)


def build(A, directory, spec, original=None):
    book, rules, ema = M2.build(A, directory, BASE, original=original)
    if spec.get('confirm'):
        rules = replace(rules, confirm_trail='e21')
    if spec.get('trail'):
        rules = replace(rules, trail=spec['trail'])
    if spec.get('trail_days'):
        rules = replace(rules, trail_confirm_days=spec['trail_days'])
    if 'trims' in spec:
        rules = replace(rules, trims=tuple(spec['trims']), trim_frac=spec.get('trim_frac', rules.trim_frac))
    if spec.get('add') == 'one':
        rules = replace(rules, add_levels=(1., 10., 20.))
    elif spec.get('add') == 'r74':
        rules = replace(rules, add_levels=(10., 20.))
    elif spec.get('add') == 'high':
        rules = replace(rules, add_levels=(), add_r=0., add_signal='_m3_high',
            add_signal_frac=1., add_signal_max=2, add_signal_stop='fill', add_signal_profit=True)
        # A fresh completed-close 20-session high; rolling one stock at a time.
        if '_m3_high' not in A:
            from studies.trader_replication.standard_indicators import roll, lag
            high = np.zeros(A['close'].shape, bool)
            for j in range(high.shape[1]):
                high[:, j] = A['close'][:, j] > lag(roll(A['high'][:, j].astype(float), 20, 'max'))
            A['_m3_high'] = high
        ema['_m3_high'] = A['_m3_high']
    if spec.get('cap'):
        rules = replace(rules, max_position=spec['cap'])
    if spec.get('reentry'):
        rules = replace(rules, reentry_days=10, reentry_adr='_m3_adr', reentry_filter='_m3_retry_ok', no_rebuy_day=True)
        ema['_m3_adr'] = A['adr']
        good = M2.qqq_good(A)
        ok = np.broadcast_to(good[:, None], A['close'].shape).copy()
        scores = A['_m2_prior_scores']
        for d, row in enumerate(book):
            ranked = sorted(row, key=lambda e: (not np.isfinite(scores[d, e[1]]),
                -round(float(scores[d, e[1]]), 10) if np.isfinite(scores[d, e[1]]) else 0., e[0]))
            for e in ranked[:3]:
                if np.isfinite(scores[d, e[1]]):
                    ok[d, e[1]] = True
        ema['_m3_retry_ok'] = ok
    # M2's native float64 EMA convention, including lines absent from its default policy.
    from . import luk
    for name, n in (('e9', 9), ('e21', 21)):
        if 'native_'+name not in A:
            A['native_'+name] = luk.ema(A['close'].astype(float), n)
        ema[name] = A['native_'+name]
    return book, rules, ema


def run(A, name, spec, span=TRAIN, directory=PREP, base_spec=None):
    old_out, old_build, sim = M.OUT, M.build, Y.simulate
    M.OUT = OUT
    M.build = (lambda a, d, s: build(a, d, spec, original=old_build)) if base_spec is None else old_build
    def capture(*args, **kwargs):
        track = kwargs.get('track')
        if track is not None:
            track['management_attempts'] = []
        result = sim(*args, **kwargs)
        if track is not None:
            write(name+'/management.json', {k: v for k, v in track.items() if k != 'entry_attempts'})
        return result
    try:
        with patch.object(Y, 'simulate', capture):
            return M.evaluate(A, directory, name, base_spec or BASE, span)
    finally:
        M.OUT, M.build = old_out, old_build


def diagnose():
    once('diagnostics')
    A, results = arrays(), {}
    for name, spec in DIAGNOSTICS.items():
        results[name] = run(A, 'diagnostics/'+name, spec)[0]
        write('diagnostics.json', results)
        gc.collect()
    write('diagnostics_complete.json', dict(arms=len(results), resources=resource_observation()))


def compatibility():
    once('compatibility')
    A, checks = arrays(), {}
    specs = dict(C062=dict(basis='ie'), master_C062=dict(basis='master'), M1B=M2.BASE)
    for name, spec in specs.items():
        _, trades, curve = run(A, 'compatibility/'+name, {}, base_spec=spec)
        ref = HOME/'reports/m1_work'/('candidates/M1B' if name == 'M1B' else
            'baseline/'+('IE47_C062' if name == 'C062' else name))
        checks[name] = dict(trades=clean(trades) == read(ref/'trades.json'), curve=clean(curve) == read(ref/'curve.json'))
    _, trades, curve = run(A, 'compatibility/M2A', {})
    ref = HOME/'reports/m2_work/candidates/M2A'
    checks['M2A'] = dict(trades=clean(trades) == read(ref/'trades.json'), curve=clean(curve) == read(ref/'curve.json'))
    assert all(all(v.values()) for v in checks.values()), checks
    write('compatibility.json', dict(ok=True, train=checks))


def full_compatibility():
    """Replay original complete ledgers without attributing or selecting a new validation account."""
    once('full_compatibility')
    directory = HOME/'reports/m1_work/validation_prepared'
    A, checks = arrays(directory), {}
    for name, spec in dict(C062=dict(basis='ie'), master_C062=dict(basis='master'),
                           M1B=M2.BASE, M2A=None).items():
        book, rules, ema = M.build(A, directory, spec) if spec else build(A, directory, {})
        native = name in ('M1B', 'M2A')
        px = dict(dates=A['days'], **{n: A[n].astype(float) if native and n != 'codes' else A[n]
                                    for n in ('open', 'high', 'low', 'close', 'codes')})
        curve, dates, trades = Y.simulate(px, ema, rules, book, TRAIN[0], VALID[1], audit=True)
        ref = HOME/'reports/m1_work'/('validation/continuous' if name == 'M1B' else
            'compatibility/'+('IE47_C062' if name == 'C062' else name))
        if name == 'M2A':
            ref = HOME/'reports/m2_work/validation/continuous'
        checks[name] = dict(trades=clean(trades) == read(ref/'trades.json'),
            curve=clean(dict(days=dates, equity=curve)) == read(ref/'curve.json'),
            executions=sum(len(t['executions']) for t in trades))
        assert checks[name]['trades'] and checks[name]['curve'], (name, checks[name])
        log('original complete ledger unchanged: '+name)
    write('full_compatibility.json', dict(ok=True, full=checks, candidate_validation=False,
        resources=resource_observation()))


def candidate_specs():
    return read(OUT/'candidates.json')['specs']


def select(runs, baseline):
    outcome = M.select(runs, baseline)
    base_capture = min(baseline['years'][y]['capture_total'] or 0. for y in ('2024', '2025'))
    for name, r in runs.items():
        if min(r['years'][y]['capture_total'] or 0. for y in ('2024', '2025')) <= base_capture:
            outcome['failures'][name].append('worse_year_capture')
    def key(name):
        r = runs[name]
        rows = [r['years'][y] for y in ('2024', '2025')]
        return (-min(x['target_count'] for x in rows), -min(x['capture_total'] or 0. for x in rows),
            -min(x['cap_equity'] for x in rows), max(x['maxdd'] for x in rows), -r['H'], name)
    outcome['eligible'] = sorted((n for n in runs if not outcome['failures'][n]), key=key)
    outcome['chosen'] = next(iter(outcome['eligible']), None)
    return outcome


def registry_check():
    r = read(OUT/'candidates.json')
    assert r['prereg_sha256'] == sha(PREREG)
    assert all(sha(ROOT/p) == h for p, h in r['code_sha256'].items()), 'frozen implementation changed'
    return r


def candidates():
    once('candidates')
    r = registry_check()
    assert 0 < len(r['specs']) <= 5
    A, results = arrays(), {}
    for name, spec in r['specs'].items():
        results[name] = run(A, 'candidates/'+name, spec)[0]
        write('candidates_train.json', results)
        gc.collect()
    baseline = M.summary(read(HOME/'reports/m2_work/candidates/M2A/metrics.json'))
    write('selection.json', dict(select(results, baseline), baseline=baseline,
        prereg_sha256=sha(PREREG), independent_out_of_sample=False))


def prefix_value(A, directory, spec):
    book, rules, ema = build(A, directory, spec)
    px = dict(dates=A['days'], **{n: A[n].astype(float) if n != 'codes' else A[n]
                                for n in ('open', 'high', 'low', 'close', 'codes')})
    curve, dates, trades = Y.simulate(px, ema, rules, book, *TRAIN, audit=True)
    k = int(np.searchsorted(A['days'], CUT, side='right'))
    _, picks = M2.profile(A)
    return clean(dict(book=book[:k], picks={d: cs for d, cs in picks.items() if d <= CUT},
        events=M.E15.B.execution_events(trades, CUT), curve=[float(v) for d, v in zip(dates, curve) if d <= CUT]))


def prefix():
    once('prefix')
    registry_check()
    choice = read(OUT/'selection.json')['chosen']
    # With no eligible account, prove the most complete frozen diagnostic anyway; do not open 2026.
    name = choice or next(reversed(candidate_specs()))
    spec = candidate_specs()[name]
    values = {}
    for label, directory in (('full', PREP), ('cut', HOME/'reports/m1_work/prefix_cut'),
                              ('perturbed', HOME/'reports/m1_work/prefix_perturbed')):
        A = arrays(directory)
        if label != 'full':
            p = HOME/('reports/m2_work/profile_'+label+'_G1')
            A['_m2_G1'] = np.load(p.with_suffix('.npy'), mmap_mode='r'), read(p.with_suffix('.json'))
        A['_m2_perturb_qqq'] = label == 'perturbed'
        values[label] = prefix_value(A, directory, spec)
        write('prefix_'+label+'.json', values[label])
        del A
        gc.collect()
    stored = read(OUT/f'candidates/{name}/trades.json')
    assert values['full']['events'] == clean(M.E15.B.execution_events(stored, CUT))
    checks = {label: {k: values[label][k] == values['full'][k] for k in values['full']}
              for label in ('cut', 'perturbed')}
    assert all(all(v.values()) for v in checks.values()), checks
    write('truncation.json', dict(ok=True, tested=name, selected=choice, cutoff=CUT, checks=checks,
        actual_events=len(values['full']['events']),
        provenance='M1 real truncated / future OHLC x3, volume x2, turnover x6 inputs; M2 independently rebuilt G1 features',
        reused_proofs={n: sha(HOME/('reports/m2_work/'+n)) for n in
            ('profile_cut_complete.json', 'profile_perturbed_complete.json', 'truncation.json')}))


def validate():
    registry_check()
    choice = read(OUT/'selection.json')['chosen']
    if not choice:
        write('validation_complete.json', dict(skipped=True, reason='no eligible candidate; 2026 not opened',
            standalone_evaluations=0, continuous_evaluations=0))
        return
    assert read(OUT/'truncation.json')['ok']
    once('validation')
    directory = HOME/'reports/m1_work/validation_prepared'
    A, results = arrays(directory), {}
    for label, span in (('standalone', VALID), ('continuous', (TRAIN[0], VALID[1]))):
        results[label] = run(A, 'validation/'+label, candidate_specs()[choice], span, directory)[0]
        write('validation.json', results)
    write('validation_complete.json', dict(chosen=choice, standalone_evaluations=1,
        continuous_evaluations=1, independent_out_of_sample=False))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('stage', choices=('freeze', 'compatibility', 'full-compatibility', 'diagnose', 'candidates', 'prefix', 'validate'))
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    offline()
    dict(freeze=freeze, compatibility=compatibility, **{'full-compatibility': full_compatibility}, diagnose=diagnose, candidates=candidates,
         prefix=prefix, validate=validate)[args.stage]()


if __name__ == '__main__':
    main()
