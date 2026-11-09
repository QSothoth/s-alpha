"""Offline M2 account research; frozen inputs, bounded arrays, isolated outputs."""
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

import numpy as np

from . import m1_research as M
from studies.trader_replication import system as Y

ROOT, HOME = M.ROOT, M.HOME
OUT = HOME/'reports/m2_work'
PREP = HOME/'reports/m1_work/prepared'
F2DIR = HOME/'reports/f2_work'
PREREG = HOME/'notes/PREREG_M2_CN.md'
TRAIN, VALID, CUT = M.TRAIN, M.VALID, M.CUT
BASE = dict(basis='master', queue=True, execution='R74')
read, sha, clean, log = M.read, M.sha, M.clean, M.log


def write(path, value):
    M.write(path if isinstance(path, Path) else OUT/path, value)


def offline():
    sys.dont_write_bytecode = True
    def guard(event, args):
        if event in ('socket.connect', 'socket.bind', 'socket.getaddrinfo', 'subprocess.Popen', 'os.system'):
            raise PermissionError('M2 is offline and single-process')
        if event == 'open' and not isinstance(args[0], int):
            if args[2] & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND):
                path = Path(os.fsdecode(args[0])).resolve()
                if not path.is_relative_to(OUT.resolve()):
                    raise PermissionError('M2 research writes only m2_work: '+str(path))
    sys.addaudithook(guard)


def once(name):
    with (OUT/(name+'_started.json')).open('x') as f:
        json.dump(dict(time=time.time(), source=sha(Path(__file__)), memory=Path('/proc/meminfo').read_text()), f)


def freeze():
    once('protocol')
    protected = [ROOT/'studies/trader_replication/systems.py', ROOT/'studies/trader_replication/mainleg.py',
        HOME/'notes/trades.csv', HOME/'notes/legs_frozen.json', HOME/'replicate.py']
    protected += sorted((ROOT/'studies/trader_screens').glob('*.py'))
    protected += sorted((HOME/'reports/m1_work').rglob('*.json'))
    protected += sorted(F2DIR.glob('*.json'))
    protected += [F2DIR/'features.npy', HOME/'reports/f1_work/rows.npz']
    protected += [HOME/f'reports/{n}_CN.md' for n in ('M1', 'F2', 'Y1')]
    write('protocol.json', dict(task='PLAN_M2_CN', train=TRAIN, validation=VALID, cutoff=CUT,
        label_policy='frozen Y1 labels only after account simulation; never in account decisions',
        high_score_policy='prior completed night G1 score, missing pool scores rank last',
        resources=dict(python=sys.executable, cpu='60%', memory='900M', threads=1),
        protected={str(p.relative_to(ROOT)): sha(p) for p in protected}))
    (OUT/'original_engine.py.txt').write_text(Path(Y.__file__).read_text())
    log('M2 inputs frozen; U1 is outside the write boundary')


def arrays(directory=PREP):
    A = M.load_arrays(directory)
    A.pop('_e15_books', None)
    return A


def run(A, name, spec, span=TRAIN, directory=PREP):
    """Reuse M1 attribution and financing checks without changing any M1 artifact."""
    old_out, old_build = M.OUT, M.build
    M.OUT = OUT
    M.build = lambda a, d, s: build(a, d, s, original=old_build)
    try:
        return M.evaluate(A, directory, name, spec, span)
    finally:
        M.OUT, M.build = old_out, old_build


def profile(A, source='G1'):
    key = '_m2_'+source
    if key in A:
        return A[key]
    # Only inference: Sample gets no labels, frozen model tables never refitted.
    from studies.trader_replication import martin_profile_f2 as F
    meta = read(F2DIR/'cache.json')
    with np.load(HOME/'reports/f1_work/rows.npz') as archive:
        rows = {k: archive[k] for k in archive.files}
    x = np.load(F2DIR/'features.npy', mmap_mode='r')
    model = read(F2DIR/('fit_'+source+'.json'))['model']
    last = int(np.searchsorted(meta['days'], str(A['days'][-1]), side='right'))-1
    sample = F.sample_for(model, meta, rows, x, [], last)
    scores = F.score(model, sample)
    matrix = np.full(A['close'].shape, np.nan, dtype=np.float64)
    matrix[sample.day, sample.code] = scores
    nominated = sample.nominate(scores)
    picks = {meta['days'][int(t)]: [meta['codes'][int(sample.code[r])] for r in row if r < len(scores)]
             for t, row in zip(sample.nights, nominated)}
    exported = read(F2DIR/('picks_'+source+'.json'))
    warm = read(F2DIR/('picks_'+source+'_warmup.json'))
    assert all(picks.get(d, []) == cs for d, cs in dict(warm, **exported).items() if d <= str(A['days'][-1]))
    A[key] = matrix, picks
    log('loaded label-free '+source+' inference and checked exported nominations')
    return A[key]


def source_book(A, directory, picks):
    """F2 replaces the scan/watch gate; master's completed-day trigger union and stop remain."""
    key = '_m2_master_trigger'
    if key not in A:
        from . import replicate as R
        c, h, l = (A[n].astype(float) for n in ('close', 'high', 'low'))
        with np.errstate(all='ignore'):
            tight = ((h <= R.prev(h)) & (l >= R.prev(l))) | ((h/l-1)*100 <= .5*A['adr'])
        fire = A['master_e10'] | A['master_e11'] | (R.prev(tight) & (h > R.prev(h)))
        fire |= R.weekly_breakouts(A)['EW1']
        fire |= A['b_fire']
        # Existing master EP signals remain available; no new earnings data are used.
        for d, row in enumerate(M.load_book(directory, 'master_raw')):
            for e in row:
                fire[d, e[1]] = True
        A[key] = fire
    ci = {str(c): j for j, c in enumerate(A['codes'])}
    out, live = [[] for _ in A['days']], {}
    for d in range(1, len(out)):
        for code in picks.get(str(A['days'][d-1]), ()):
            live[ci[code]] = d+4
        live = {j: end for j, end in live.items() if end >= d}
        for j in sorted(live, key=lambda j: (-A['to20'][d-1, j], str(A['codes'][j]))):
            if not A[key][d, j]:
                continue
            # The first qualifying trigger consumes the observation even if the account refuses it.
            del live[j]
            fill = float(A['close'][d, j])
            stop = M.M.capped_stop(fill, float(A['low'][d, j]), A['adr'][d-1, j])
            if stop is not None:
                out[d].append((-float(A['to20'][d-1, j]), j, 1, fill, stop, 'm2_f2_close'))
    return out


def qqq_good(A):
    if '_m2_qqq_good' not in A:
        from studies.trader_data import supplemental as SP
        qqq, _ = SP.benchmark('US.QQQ', A['days'], 'frozen')
        if A.get('_m2_perturb_qqq'):
            qqq = qqq.copy()
            qqq[np.searchsorted(A['days'], CUT, side='right'):] *= 3
        SI = M.M.SI
        good = (qqq > SI.ema(qqq, 50)) & (SI.ema(qqq, 9) > SI.ema(qqq, 21))
        A['_m2_qqq_good'] = np.r_[False, good[:-1]]
    return A['_m2_qqq_good']


def build(A, directory, spec, original=None):
    original = original or M.build
    basic = {k: v for k, v in spec.items() if k in ('basis', 'queue', 'execution', 'memory', 'trigger',
        'reset', 'order', 'hybrid', 'funding', 'holding', 's1', 'pool', 'b_reclaim')}
    source = spec.get('source', '')
    if source:
        scores, picks = profile(A, source)
        f2 = source_book(A, directory, picks)
        master = M.load_book(directory, 'master_filtered')
        if spec.get('union'):
            f2 = M.merge_books(master, f2)
        from unittest.mock import patch
        load = M.load_book
        with patch.object(M, 'load_book', lambda p, n: f2 if n == 'master_filtered' else load(p, n)):
            book, rules, ema = original(A, directory, dict(basic, basis='master', queue=True))
    else:
        book, rules, ema = original(A, directory, basic)
    if not any(spec.get(k) for k in ('rank', 'rotate', 'tier', 'probe_gate', 'source')):
        if spec.get('gross'):
            rules = replace(rules, max_gross=spec['gross'])
        if spec.get('equity_ma'):
            rules = replace(rules, equity_ma_days=spec['equity_ma'])
        return book, rules, ema
    scores, _ = profile(A)
    # An entry at today's close ranks on the preceding completed night's profile.
    if '_m2_prior_scores' not in A:
        A['_m2_prior_scores'] = np.vstack((np.full((1, scores.shape[1]), np.nan), scores[:-1]))
    shifted = A['_m2_prior_scores']
    A['_m2_rotation'] = shifted
    if spec.get('rotate'):
        rules = replace(rules, rotate_score='_m2_rotation')
        ema['_m2_rotation'] = shifted
    if spec.get('gross'):
        rules = replace(rules, max_gross=spec['gross'])
    if spec.get('equity_ma'):
        rules = replace(rules, equity_ma_days=spec['equity_ma'])
    out = []
    good = qqq_good(A) if spec.get('probe_gate') == 'qqq' else None
    for d, row in enumerate(book):
        ranked = sorted(row, key=lambda e: (not np.isfinite(shifted[d, e[1]]),
            -round(float(shifted[d, e[1]]), 10) if np.isfinite(shifted[d, e[1]]) else 0., e[0]))
        high = {e[1] for e in ranked[:spec.get('top_k', 3)] if np.isfinite(shifted[d, e[1]])}
        kept, probes = [], 0
        for rank, e in enumerate(ranked if spec.get('rank') else row):
            priority, j = e[0], e[1]
            if j not in high and spec.get('probe_gate') == 'qqq' and not good[d]:
                continue
            if j not in high and spec.get('probe_gate') == 'one':
                # This limits offered probes; held-name skips cannot silently create extra probes.
                probes += 1
                if probes > 1:
                    continue
            if spec.get('rank'):
                priority = (rank, str(A['codes'][j]))
            e = (priority, *e[1:])
            if spec.get('tier'):
                mult = (spec['tier'] if j in high else .0025)/.005
                e = (*e[:9], mult, *e[10:]) if len(e) > 9 else (*e, *([None]*(9-len(e))), mult)
            kept.append(e)
        out.append(kept)
    return out, rules, ema


DIAGNOSTICS = {
    'G1_rank': dict(rank=True),
    'G1_rotation': dict(rank=True, rotate=True),
    'risk_100': dict(tier=.01),
    'risk_150': dict(tier=.015),
    'gross_140': dict(gross=1.4),
    'gross_400': dict(gross=4.),
    'probes_qqq': dict(probe_gate='qqq'),
    'probes_one': dict(probe_gate='one'),
    'equity_ma20': dict(equity_ma=20),
    'F2_G1': dict(source='G1'),
    'F2_G3': dict(source='G3'),
    'F2_G1_union': dict(source='G1', union=True),
}

CANDIDATES = {
    'M2A': dict(BASE, probe_gate='qqq'),
    'M2B': dict(BASE, probe_gate='qqq', equity_ma=20, gross=4.),
    'M2C': dict(BASE, rank=True, rotate=True, tier=.01, probe_gate='qqq'),
    'M2D': dict(BASE, source='G1', rank=True, rotate=True, tier=.015, equity_ma=20, gross=4.),
    'M2E': dict(BASE, source='G3', union=True, rank=True, rotate=True, tier=.01,
                equity_ma=20, probe_gate='qqq'),
}


def select(runs, baseline):
    outcome = M.select(runs, baseline)
    def key(n):
        r = runs[n]
        rows = [r['years'][y] for y in ('2024', '2025')]
        return (-min(x['target_count'] for x in rows), -min(x['cap_equity'] for x in rows),
            -min(x['purity_gross'] or 0. for x in rows), max(x['maxdd'] for x in rows), -r['H'], n)
    outcome['eligible'] = sorted(outcome['eligible'], key=key)
    outcome['chosen'] = next(iter(outcome['eligible']), None)
    return outcome


def candidates():
    once('candidates')
    assert PREREG.exists() and len(CANDIDATES) <= 5
    registry = dict(specs=CANDIDATES, prereg_sha256=sha(PREREG), diagnostics_sha256=sha(OUT/'diagnostics.json'),
        code_sha256={str(p.relative_to(ROOT)): sha(p) for p in (Path(__file__), Path(Y.__file__),
            ROOT/'studies/trader_replication/study.py')})
    write('candidates.json', registry)
    A, runs = arrays(), {}
    for n, spec in CANDIDATES.items():
        runs[n] = run(A, 'candidates/'+n, spec)[0]
        write('candidates_train.json', runs)
        gc.collect()
    baseline = M.summary(read(HOME/'reports/m1_work/candidates/M1B/metrics.json'))
    write('selection.json', dict(select(runs, baseline), baseline=baseline,
        prereg_sha256=sha(PREREG), independent_out_of_sample=False))


def compatibility():
    once('compatibility')
    A = arrays()
    specs = dict(IE47_C062=dict(basis='ie'), IE47_S1=dict(basis='ie', s1=True),
                 master_C062=dict(basis='master'), M1B=BASE)
    checks = {}
    for n, spec in specs.items():
        _, trades, curve = run(A, 'compatibility/'+n, spec)
        origin = 'candidates/M1B' if n == 'M1B' else 'baseline/'+n
        checks[n] = compare_saved(origin, trades, curve)
        assert all(checks[n].values()), (n, checks[n])
    write('compatibility.json', dict(ok=True, train=checks))


def full_compatibility():
    """Replay existing complete ledgers only; no new candidate or 2026 attribution."""
    once('full_compatibility')
    A, directory = arrays(HOME/'reports/m1_work/validation_prepared'), HOME/'reports/m1_work/validation_prepared'
    checks = {}
    for n, spec in dict(IE47_C062=dict(basis='ie'), IE47_S1=dict(basis='ie', s1=True),
                        master_C062=dict(basis='master'), M1B=BASE).items():
        book, rules, ema = M.build(A, directory, spec)
        px = dict(dates=A['days'], **{k: A[k].astype(float) if n == 'M1B' and k != 'codes' else A[k]
                                    for k in ('open', 'high', 'low', 'close', 'codes')})
        curve, dates, trades = Y.simulate(px, ema, rules, book, TRAIN[0], VALID[1], audit=True)
        origin = 'validation/continuous' if n == 'M1B' else 'compatibility/'+n
        checks[n] = compare_saved(origin, trades, dict(days=dates, equity=curve))
        assert all(checks[n].values()), (n, checks[n])
        log('complete original ledger unchanged: '+n)
    write('full_compatibility.json', dict(ok=True, full=checks, candidate_selection=False))


def registry_check():
    r = read(OUT/'candidates.json')
    assert r['prereg_sha256'] == sha(PREREG)
    assert r['specs'] == CANDIDATES
    assert all(sha(ROOT/p) == digest for p, digest in r['code_sha256'].items()), 'candidate implementation changed'
    return r


def prefix_value(A, directory, spec):
    book, rules, ema = build(A, directory, spec)
    px = dict(dates=A['days'], **{n: A[n].astype(float) if n != 'codes' else A[n]
                                for n in ('open', 'high', 'low', 'close', 'codes')})
    curve, dates, trades = Y.simulate(px, ema, rules, book, *TRAIN, audit=True)
    k = int(np.searchsorted(A['days'], CUT, side='right'))
    scores, picks = profile(A)
    keys = dict(book=book[:k], events=M.E15.B.execution_events(trades, CUT),
        curve=[float(v) for d, v in zip(dates, curve) if d <= CUT],
        picks={d: cs for d, cs in picks.items() if d <= CUT})
    if spec.get('source') == 'G3':
        keys['G3_picks'] = {d: cs for d, cs in profile(A, 'G3')[1].items() if d <= CUT}
    return clean(keys)


def prefix():
    once('prefix')
    registry_check()
    choice = read(OUT/'selection.json')['chosen']
    if choice is None:
        write('truncation.json', dict(ok=False, reason='no eligible candidate; 2026 not opened'))
        return
    spec = CANDIDATES[choice]
    values = {}
    for label, directory in (('full', PREP), ('cut', HOME/'reports/m1_work/prefix_cut'),
                              ('perturbed', HOME/'reports/m1_work/prefix_perturbed')):
        A = arrays(directory)
        A['_m2_perturb_qqq'] = label == 'perturbed'
        if label == 'full':
            values[label] = prefix_value(A, directory, spec)
        else:
            # Independent raw-bar feature rebuilding happens in the rebuild-profile stage.
            for source in ('G1', 'G3') if spec.get('source') == 'G3' else ('G1',):
                rebuilt = OUT/('profile_'+label+'_'+source)
                A['_m2_'+source] = (np.load(rebuilt.with_suffix('.npy'), mmap_mode='r'), read(rebuilt.with_suffix('.json')))
            values[label] = prefix_value(A, directory, spec)
        write('prefix_'+label+'.json', values[label])
        del A
        gc.collect()
    stored = read(OUT/f'candidates/{choice}/trades.json')
    assert values['full']['events'] == clean(M.E15.B.execution_events(stored, CUT))
    checks = {label: {k: values[label][k] == values['full'][k] for k in values['full']}
              for label in ('cut', 'perturbed')}
    assert all(all(v.values()) for v in checks.values()), checks
    write('truncation.json', dict(ok=True, chosen=choice, cutoff=CUT, checks=checks,
        real_future_perturbation='M1 cached raw OHLC x3, volume x2, turnover x6; M2 F2 features independently rebuilt',
        actual_events=len(values['full']['events'])))


def validate():
    assert read(OUT/'truncation.json')['ok']
    registry_check()
    once('validation')
    choice = read(OUT/'selection.json')['chosen']
    A = arrays(HOME/'reports/m1_work/validation_prepared')
    results = {}
    for label, span in (('standalone', VALID), ('continuous', (TRAIN[0], VALID[1]))):
        results[label] = run(A, 'validation/'+label, CANDIDATES[choice], span,
                             HOME/'reports/m1_work/validation_prepared')[0]
        write('validation.json', results)
    write('validation_complete.json', dict(chosen=choice, standalone_evaluations=1,
        continuous_evaluations=1, independent_out_of_sample=False))


def rebuild_profile(label):
    """Recompute pool, features, ranks, route and model inference from the actual cut/perturbed bars."""
    once('rebuild_'+label)
    from studies.trader_replication import martin_profile_f2 as F
    from studies.trader_data import supplemental as SP
    upto = CUT if label == 'cut' else TRAIN[1]
    p = M.panel(upto)
    if label == 'perturbed':
        M.perturb_panel(p)
    days, codes = list(map(str, p['days'])), list(map(str, p['codes']))
    qqq, _ = SP.benchmark('US.QQQ', days, 'frozen')
    if label == 'perturbed':
        qqq = qqq.copy()
        qqq[np.searchsorted(days, CUT, side='right'):] *= 3
    SI, old_names = F.SI, F.F.FEATURES
    shape = p['close'].shape
    new, broad = np.zeros(shape, bool), np.zeros(shape, bool)
    amount, ret = np.full(shape, np.nan, np.float32), np.full(shape, np.nan, np.float32)
    fields = (('o', 'open'), ('h', 'high'), ('l', 'low'), ('c', 'close'), ('v', 'volume'),
              ('t', 'turnover'), ('raw_c', 'raw_close'))
    def stock(j):
        return {k: p[n][:, j].astype(float) for k, n in fields}
    for j in range(shape[1]):
        core = F.F.stock_core(stock(j), days)
        new[:, j], broad[:, j] = core['new'], core['broad']
        amount[:, j], ret[:, j] = core['to20'], core['perf126']
    memory, dollar = np.zeros(shape, bool), np.full(shape, np.nan, np.float32)
    for t in range(shape[0]):
        ix = np.flatnonzero(broad[t] & np.isfinite(ret[t]))
        memory[t, ix] = SI.midrank(ret[t, ix]) >= 80
        ix = np.flatnonzero(new[t])
        dollar[t, ix] = SI.midrank(amount[t, ix])
    for j in range(shape[1]):
        memory[:, j] = F.F.trailing_memory(memory[:, j])
    del amount, ret, broad
    first = max(0, int(np.searchsorted(days, F.F.START))-1)
    new[:first] = False
    rd, rc = np.nonzero(new)
    raw = np.full((len(old_names), len(rd)), np.nan, np.float32)
    entry = np.zeros(len(rd), np.uint8)
    attention = np.full(len(rd), np.nan)
    order = np.argsort(rc, kind='stable')
    offsets = np.r_[0, np.cumsum(np.bincount(rc, minlength=len(codes)))]
    for j in range(shape[1]):
        rr = order[offsets[j]:offsets[j+1]]
        if not len(rr):
            continue
        a = stock(j)
        values = F.F.stock_features(a, qqq)
        values['long_strength_memory'] = memory[:, j].astype(float)
        values['dollar_vol20_percentile'] = dollar[:, j]
        for k, name in enumerate(old_names):
            raw[k, rr] = values[name][rd[rr]]
        near = np.minimum(abs(values['ext_ema9_adr']), abs(values['ext_ema21_adr'])) <= 1
        entry[rr] = (memory[:, j] & near)[rd[rr]]
        attention[rr] = SI.divide(SI.roll(a['t'], 20), SI.roll(a['t'], 120))[rd[rr]]
        if j % 600 == 0:
            log(f'{label}: real-bar profile features {j}/{shape[1]}')
    del memory, dollar, new
    x = np.full((len(F.FEATURES), len(rd)), np.nan, np.float32)
    fi, out = {n: k for k, n in enumerate(old_names)}, {n: k for k, n in enumerate(F.FEATURES)}
    qreturns = {n: 100*(SI.divide(qqq, SI.lag(qqq, n))-1) for n in (21, 63, 126)}
    distinct, offsets, counts = np.unique(rd, return_index=True, return_counts=True)
    choice = read(OUT/'selection.json')['chosen']
    need_g3 = CANDIDATES[choice].get('source') == 'G3' if choice else False
    for t, offset, count in zip(distinct, offsets, counts):
        rr = np.arange(offset, offset+count)
        for k, name in enumerate(old_names):
            values = raw[k, rr].astype(float)
            x[out[F.BASE[k]], rr] = values if name == 'long_strength_memory' else SI.midrank(values)
        for n, name in zip((21, 63, 126), F.RS):
            x[out[name], rr] = SI.midrank(raw[fi[f'perf{n}_pct'], rr].astype(float)-qreturns[n][t])
        if need_g3:
            ix = rc[rr]
            peers = F.peer_features(p['close'][max(0, t-60):t+1, ix].astype(float),
                raw[fi['perf21_pct'], rr].astype(float), x[out['pctl_perf21_pct'], rr])
            for k, name in enumerate(F.PEERS):
                x[out[name], rr] = peers[k]
            dollar = x[out['pctl_dollar_vol20_percentile'], rr]
            for name, strength in zip(F.MONEY[:3], F.RS):
                x[out[name], rr] = (dollar/100)*(x[out[strength], rr]/100)
            x[out[F.MONEY[-1]], rr] = SI.midrank(attention[rr])
    regime = np.where(qqq < SI.ema(qqq, 50), 2, np.where(qqq <= 1.01*SI.ema(qqq, 21), 1, 0))
    a = dict(row_day=rd, row_code=rc, new=np.ones(len(rd), bool), entry=entry, regime=regime[rd])
    meta = dict(days=days, codes=codes, first_night=first)
    for source in ('G1', 'G3') if need_g3 else ('G1',):
        model = read(F2DIR/('fit_'+source+'.json'))['model']
        sample = F.sample_for(model, meta, a, x, [], len(days)-1)
        scores = F.score(model, sample)
        matrix = np.full(shape, np.nan)
        matrix[sample.day, sample.code] = scores
        picks = {days[int(t)]: [codes[int(sample.code[r])] for r in row if r < len(scores)]
                 for t, row in zip(sample.nights, sample.nominate(scores))}
        np.save(OUT/('profile_'+label+'_'+source+'.npy'), matrix)
        write('profile_'+label+'_'+source+'.json', picks)
    write('profile_'+label+'_complete.json', dict(ok=True, sources=['G1', 'G3'] if need_g3 else ['G1'],
        real_bar_rebuild=True, rows=len(rd), cutoff=CUT, independent_of_cached_features=True,
        peak_rss_mib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024))
    log('raw-bar profile reconstruction complete: '+label)


def diagnose():
    once('diagnostics')
    A = arrays()
    write('diagnostics_protocol.json', dict(arms=DIAGNOSTICS, base=BASE,
        comparisons='rotation adds only rotation to G1_rank; all other arms change one mechanism versus M1B',
        high='top 3 finite prior-night G1 scores among offered entries; ties use original priority',
        risk='1.0% or 1.5% high / 0.25% low at feedback-low; original feedback and index multiplier retained'))
    runs = {}
    for n, s in DIAGNOSTICS.items():
        runs[n] = run(A, 'diagnostics/'+n, dict(BASE, **s))[0]
        write('diagnostics.json', runs)
        gc.collect()
    write('diagnostics_complete.json', dict(arms=len(runs), peak_rss_mib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024))


def correct_diagnostics():
    once('diagnostic_correction')
    import shutil
    old = OUT/'corrections/initial_diagnostics'
    old.mkdir(parents=True, exist_ok=True)
    for n in ('probes_qqq', 'F2_G1', 'F2_G3', 'F2_G1_union'):
        shutil.move(str(OUT/'diagnostics'/n), str(old/n))
    for n in ('diagnostics.json', 'diagnostics_protocol.json', 'diagnostics_complete.json'):
        shutil.copyfile(OUT/n, old/n)
    write('diagnostic_correction.json', dict(before_candidates=True, after_2026=False,
        changes=['QQQ gate uses actual QQQ > EMA50 and EMA9 > EMA21, rather than the unrelated master index multiplier',
                 'F2 replaces stock scan/watch gate; consume first master-style trigger in five nights, not repeat every raw signal'],
        source_sha256=sha(Path(__file__))))
    A, runs = arrays(), read(OUT/'diagnostics.json')
    for n in ('probes_qqq', 'F2_G1', 'F2_G3', 'F2_G1_union'):
        runs[n] = run(A, 'diagnostics/'+n, dict(BASE, **DIAGNOSTICS[n]))[0]
        write('diagnostics.json', runs)
    write('diagnostics_complete.json', dict(arms=len(runs), corrected=True,
        peak_rss_mib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024))


def compare_saved(name, trades, curve):
    old = HOME/'reports/m1_work'/name
    return dict(trades=clean(trades) == read(old/'trades.json'), curve=clean(curve) == read(old/'curve.json'))


def diagnose_collapse():
    once('collapse')
    A = arrays()
    registry = read(HOME/'reports/m1_work/candidates.json')['specs']
    specs = {'IE_R74': dict(basis='ie', execution='R74'),
        'IE_R74_queue': dict(basis='ie', execution='R74', queue=True),
        'IE_R74_structure': dict(basis='ie', execution='R74', queue=True, order='structure'),
        **{n: registry[n] for n in ('M1C', 'M1D', 'M1E')},
        'M1C_no_structure': {k: v for k, v in registry['M1C'].items() if k != 'order'},
        'M1C_without_B': {k: v for k, v in registry['M1C'].items() if k != 'memory'},
        'M1D_no_structure': {k: v for k, v in registry['M1D'].items() if k != 'order'},
        'M1D_master_duplicate': dict(registry['M1D'], master_duplicate=True)}
    runs, checks = {}, {}
    for n, spec in specs.items():
        s = dict(spec)
        # Keep master quotes for duplicates as a single isolated diagnostic.
        if s.pop('master_duplicate', False):
            ie = M.load_book(directory:=PREP, 'ie_base')
            master = M.master_adapter(A, M.load_book(directory, 'master_filtered'))
            override = M.merge_books(master, ie)
            from unittest.mock import patch
            merge = M.merge_books
            with patch.object(M, 'merge_books', lambda _a, _b: override):
                r, trades, curve = run(A, 'collapse/'+n, s)
        else:
            r, trades, curve = run(A, 'collapse/'+n, s)
        runs[n] = dict(spec=spec, **r)
        if n in registry:
            checks[n] = compare_saved('candidates/'+n, trades, curve)
        elif n == 'IE_R74':
            checks[n] = compare_saved('diagnostics/ie_R74', trades, curve)
        write('collapse.json', dict(runs=runs, original_replay=checks))
        gc.collect()
    assert all(all(r.values()) for r in checks.values()), checks
    collapse_funnel()
    write('collapse_complete.json', dict(replay_identical=True, arms=len(specs)))


def collapse_funnel():
    """Evaluation only: pair each original IE trade/early offer with actual refusal and competitors."""
    reference = read(OUT/'collapse/IE_R74/trades.json')
    base = {(t['entry'], t['code']): t for t in reference}
    out = {}
    for n in ('IE_R74_queue', 'IE_R74_structure', 'M1C', 'M1D', 'M1E',
              'M1C_no_structure', 'M1C_without_B', 'M1D_no_structure', 'M1D_master_duplicate'):
        directory = OUT/'collapse'/n
        result = read(directory/'metrics.json')
        early = {(d, g['code']): g['key'] for g in result['funnel'] for d in g['offered']}
        wanted = set(base) | set(early)
        details, filled = {}, {}
        with (directory/'attempts.jsonl').open() as f:
            for line in f:
                row = json.loads(line)
                key = row['day'], row['code']
                if row['reason'] == 'filled':
                    filled.setdefault(row['day'], []).append(row['code'])
                if key in wanted:
                    details.setdefault(key, []).append(row)
        ledger = read(directory/'trades.json')
        actual = {(t['entry'], t['code']): t for t in ledger}
        pairs = [dict(day=d, code=c, from_original_IE=(d, c) in base,
                    original_pnl=base[d, c]['pnl'] if (d, c) in base else None,
                    early_leg=early.get((d, c)), actual_entry=(d, c) in actual,
                    attempts=details.get((d, c), []), day_fills=filled.get(d, [])) for d, c in sorted(wanted)]
        write(directory/'paired_events.json', pairs)
        out[n] = dict(original_IE_entries=len(base), retained=len(set(base) & set(actual)),
            early_offer_days=len(early), early_refusals=Counter(r['reason'] for k, rows in details.items()
                if k in early for r in rows), common_original_pnl=sum(base[k]['pnl'] for k in set(base) & set(actual)))
    write('collapse_funnel.json', out)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('stage', choices=('freeze', 'collapse', 'diagnose', 'correct-diagnostics',
        'compatibility', 'full-compatibility', 'candidates', 'rebuild-profile', 'prefix', 'validate'))
    parser.add_argument('--variant', choices=('cut', 'perturbed'), default='cut')
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    offline()
    {'freeze': freeze, 'collapse': diagnose_collapse, 'diagnose': diagnose,
     'correct-diagnostics': correct_diagnostics, 'compatibility': compatibility,
     'full-compatibility': full_compatibility,
     'candidates': candidates, 'rebuild-profile': lambda: rebuild_profile(args.variant),
     'prefix': prefix, 'validate': validate}[args.stage]()


if __name__ == '__main__':
    main()
