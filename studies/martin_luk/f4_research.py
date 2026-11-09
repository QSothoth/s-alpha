"""Offline F4 first-pullback supply test, with a hard gate before accounts."""
from __future__ import annotations

import argparse
from collections import Counter
import gc
import json
import os
from pathlib import Path
import sys
import time
from unittest.mock import patch

import numpy as np

from . import f3_research as F3, u1_research as U

M3, M2, M, Y, SI = F3.M3, F3.M2, F3.M, F3.Y, F3.SI
ROOT, HOME, PREP = F3.ROOT, F3.HOME, F3.PREP
OUT, PREREG = HOME/'reports/f4_work', HOME/'notes/PREREG_F4_CN.md'
TRAIN, VALID, CUT = F3.TRAIN, F3.VALID, F3.CUT
SPECS = dict(V1=dict(lines=[9], supports=1), V2=dict(lines=[9, 21], supports=1),
             V3=dict(lines=[9, 21], supports=2))
PRIMARY = 'M2A'
CORE = ('e9', 'e21', 'e50', 'adr', 'to20', 'vol20', 'prior_high20', 'prior_low20')
FIELDS = ('active', 'ready', 'pullback', 'touch9', 'touch21', 'confluence9', 'confluence21',
          'double9', 'double21', 'action', 'V1', 'V2', 'V3')
read, sha, clean, log = M.read, M.sha, M.clean, M.log
BUILDING = False


def write(name, value):
    M.write(name if isinstance(name, Path) else OUT/name, value)


def resources():
    value = M3.resource_observation()
    assert value['cpu_max'] == '60000 100000' and value['memory_max'] == '943718400', value
    assert value['threads'].split()[-1] == '1', value
    return value


def offline():
    sys.dont_write_bytecode = True
    def guard(event, args):
        if event in ('socket.connect', 'socket.bind', 'socket.getaddrinfo', 'subprocess.Popen', 'os.system'):
            raise PermissionError('F4 is offline and single-process')
        if event != 'open' or isinstance(args[0], int):
            return
        path = Path(os.fsdecode(args[0])).resolve()
        if BUILDING and (path.name in ('legs_frozen.json', 'trades.csv', 'library.jsonl') or
                         path.name == 'patterns_48.json'):
            raise PermissionError('evaluation labels forbidden during F4 feature construction')
        if args[2] & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND):
            if not (path.is_relative_to(OUT.resolve()) or path == (HOME/'reports/F4_CN.md').resolve()):
                raise PermissionError('F4 output boundary: '+str(path))
    sys.addaudithook(guard)


def once(stage):
    with (OUT/(stage+'_started.json')).open('x') as stream:
        json.dump(dict(time=time.time(), source=sha(Path(__file__)), resources=resources(),
                       memory=Path('/proc/meminfo').read_text()), stream)


def freeze():
    once('protocol')
    protected = [HOME/'notes/legs_frozen.json', HOME/'notes/trades.csv', HOME/'replicate.py',
                 ROOT/'studies/trader_replication/system.py', ROOT/'studies/trader_replication/systems.py']
    protected += sorted((ROOT/'studies/trader_screens').glob('*.py'))
    for folder in ('m1_work', 'm2_work', 'm3_work', 'u1_work', 'f3_work'):
        protected += [p for p in (HOME/'reports'/folder).rglob('*') if p.is_file()]
    protected += [HOME/f'reports/{n}_CN.md' for n in ('M2', 'M3', 'U1', 'F3')]
    sources = [Path(__file__), HOME/'f4_report.py', HOME/'tests/test_f4.py']
    sources += [HOME/(n+'.py') for n in ('f3_research', 'm3_research', 'm2_research', 'm1_research')]
    sources += [Path(SI.__file__), ROOT/'studies/trader_replication/mainleg.py']
    write('protocol.json', dict(task='PLAN_F4_CN', prereg_sha256=sha(PREREG), specs=SPECS,
        primary_execution=PRIMARY, train=TRAIN, validation=VALID, cutoff=CUT,
        source_sha256={str(p.relative_to(ROOT)): sha(p) for p in sources},
        protected={str(p.relative_to(ROOT)): sha(p) for p in protected}, resources=resources(),
        offline=True, labels_in_features=False, independent_out_of_sample=False))
    log('F4 preregistration and inputs frozen; no F4 statistics calculated')


def registry_check():
    record = read(OUT/'protocol.json')
    assert sha(PREREG) == record['prereg_sha256'], 'preregistration changed'
    assert record['specs'] == SPECS
    assert all(sha(ROOT/p) == h for p, h in record['source_sha256'].items()), 'frozen source changed'
    return record


def inputs(label, end=TRAIN[1]):
    """Rebuild rolling features from actual bars, one bounded stock at a time."""
    original = U.load_panel()
    n = int(np.searchsorted(original['days'], end, side='right'))
    days, codes = original['days'][:n], original['codes']
    shape = n, len(codes)
    folder = OUT/'features'/label
    folder.mkdir(parents=True, exist_ok=True)
    p = {k: original[k][:n] for k in U.FIELDS}
    if label == 'perturbed':
        cut = int(np.searchsorted(days, CUT, side='right'))
        for key in U.FIELDS:
            values = np.lib.format.open_memmap(folder/(U.FIELDS[key]+'.npy'), mode='w+',
                                              dtype='float32', shape=shape)
            for j in range(shape[1]):
                values[:, j] = original[key][:n, j]
                values[cut:, j] *= 2 if key == 'v' else 6 if key == 't' else 3
            values.flush()
            p[key] = values
    core = {key: np.lib.format.open_memmap(folder/(key+'.npy'), mode='w+', dtype='float32', shape=shape)
            for key in CORE}
    for j in range(shape[1]):
        c, h, lo, v, amount = (p[k][:, j].astype(float) for k in ('c', 'h', 'l', 'v', 't'))
        with np.errstate(all='ignore'):
            values = dict(e9=SI.ema(c, 9), e21=SI.ema(c, 21), e50=SI.ema(c, 50),
                adr=100*SI.roll(SI.divide(h, lo)-1, 20), to20=SI.roll(amount, 20), vol20=SI.roll(v, 20),
                prior_high20=SI.lag(SI.roll(h, 20, 'max')), prior_low20=SI.lag(SI.roll(lo, 20, 'min')))
        for key, value in values.items():
            core[key][:, j] = value
    for value in core.values():
        value.flush()
    return p, core, days, codes


def support_counts(low, close, ema, unit, levels):
    """Count distinct, held support prices; repeated descriptions of one level count once."""
    accepted = []
    count = np.zeros(len(low), np.uint8)
    for level in levels:
        yes = (np.isfinite(level) & (abs(level-low) <= .5*unit) &
               (abs(level-ema) <= .5*unit) & (close >= level))
        for prior, valid in accepted:
            yes &= ~valid | (abs(level-prior) >= .1*unit)
        count += yes
        accepted.append((level, yes))
    return count


def initial_state(n):
    return dict(active=np.zeros(n, bool), ready=np.zeros(n, bool), pullback=np.zeros(n, bool),
        peak=np.full(n, np.nan), hurdle=np.full(n, np.nan), birth=np.full(n, -1, int),
        qualified=np.zeros((3, n), bool))


def state_step(state, day, upgrade, survives, high, decline, action, qualified, admissible):
    """First recovery consumes a pullback; only a later new high can rearm it."""
    active, ready, pending = (state[k] & survives for k in ('active', 'ready', 'pullback'))
    new = ~active & upgrade & survives
    active |= new
    ready |= new
    state['birth'][new] = day
    state['peak'][new] = high[new]
    state['qualified'][:, ~active] = False
    # A consumed opportunity can rearm at today's high, but only for tomorrow.
    rearm = active & ~new & ~ready & ~pending & (high > state['hurdle'])
    start = active & ready & ~new & (day > state['birth']) & decline
    state['hurdle'][start] = state['peak'][start]
    pending |= start
    ready &= ~start
    state['qualified'][:, pending] |= qualified[:, pending]
    consumed = pending & action
    fire = state['qualified'] & consumed[None, :] & admissible
    snapshot = dict(active=active.copy(), ready=ready.copy(), pullback=pending.copy())
    pending &= ~consumed
    state['qualified'][:, consumed] = False
    ready |= rearm
    state['birth'][rearm] = day
    state['qualified'][:, rearm] = False
    state['peak'][active & ~pending] = np.fmax(state['peak'][active & ~pending], high[active & ~pending])
    state.update(active=active, ready=ready, pullback=pending)
    return fire, snapshot


def feature_inputs(label='train', end=TRAIN[1]):
    global BUILDING
    BUILDING = True
    try:
        return compute_features(label, end)
    finally:
        BUILDING = False


def compute_features(label, end):
    p, a, days, codes = inputs(label, end)
    folder, shape = OUT/'features'/label, p['c'].shape
    f = {key: np.lib.format.open_memmap(folder/(key+'.npy'), mode='w+', dtype=bool, shape=shape)
         for key in FIELDS}
    for value in f.values():
        value[:] = False
    state = initial_state(shape[1])
    previous_ranks = {n: np.zeros(shape[1], bool) for n in (21, 63, 126)}
    previous_stack = np.zeros(shape[1], bool)
    level = {k: np.full(shape[1], np.nan) for k in ('breakout', 'box', 'gap', 'bottom')}
    born = {k: np.full(shape[1], -1000, int) for k in ('breakout', 'box', 'gap', 'vwap')}
    numerator, denominator = np.zeros(shape[1]), np.zeros(shape[1])
    with (folder/'nightly.jsonl').open('w') as nights, np.errstate(all='ignore'):
        for d, day in enumerate(days):
            c, lo, hi, o, volume = (p[k][d].astype(float) for k in ('c', 'l', 'h', 'o', 'v'))
            valid = np.isfinite(c+lo+hi+o+volume) & (lo > 0) & (volume > 0)
            pool = valid & (p['raw_c'][d] >= 2) & (a['to20'][d] >= 50e6) & (a['adr'][d] >= 3)
            upgrade = np.zeros(shape[1], bool)
            for n in (21, 63, 126):
                ret = c/p['c'][d-n]-1 if d >= n else np.full(shape[1], np.nan)
                ranks = np.full(shape[1], np.nan)
                ranks[pool] = SI.midrank(ret[pool])
                strong = ranks >= 90
                upgrade |= strong & ~previous_ranks[n]
                previous_ranks[n] = strong
            stack = (a['e9'][d] > a['e21'][d]) & (a['e21'][d] > a['e50'][d])
            upgrade = pool & (upgrade | (stack & ~previous_stack))
            previous_stack = stack
            survives = valid & (c >= a['e50'][d])
            if d == 0:
                continue
            pc, pl, ph = (p[k][d-1].astype(float) for k in ('c', 'l', 'h'))
            unit = pc*a['adr'][d-1]/100
            e9, e21 = a['e9'][d-1], a['e21'][d-1]
            numerator += np.where(valid, (hi+lo+c)/3*volume, 0.)
            denominator += np.where(valid, volume, 0.)
            gap_live = (d-born['gap'] <= 60) & (lo > level['bottom']) & valid
            level['gap'][~gap_live] = np.nan
            supports = [np.where(d-born[k] <= 60, level[k], np.nan) for k in ('breakout', 'gap')]
            supports += [np.where((d-born['vwap'] <= 60) & (denominator > 0),
                                 numerator/denominator, np.nan)]
            supports += [np.where(d-born['box'] <= 60, level['box'], np.nan)]
            touch9, touch21 = abs(lo-e9) <= .5*unit, abs(lo-e21) <= .5*unit
            count9, count21 = (support_counts(lo, c, e, unit, supports) for e in (e9, e21))
            q9, q21 = touch9 & (count9 >= 1), touch21 & (count21 >= 1)
            double9, double21 = touch9 & (count9 >= 2), touch21 & (count21 >= 2)
            reclaim = ((pc <= e9) & (c > a['e9'][d])) | ((lo <= e9) & (c >= e9) & (c > o))
            handshake = (o > pc*1.01) & (lo <= np.maximum(ph, e9)) & (c > np.minimum(ph, e9))
            action = reclaim | (c > ph) | handshake
            near9 = abs(c-a['e9'][d]) <= unit
            near21 = abs(c-a['e21'][d]) <= unit
            trend = pool & (a['e21'][d] >= e21) & (a['e50'][d] >= a['e50'][d-1])
            admissible = np.array([trend & near9, trend & (near9 | near21), trend & (near9 | near21)])
            fire, status = state_step(state, d, upgrade, survives, hi, (lo < pl) | (c <= pc), action,
                np.array([q9, q9 | q21, double9 | double21]), admissible)
            values = dict(status, touch9=touch9, touch21=touch21, confluence9=q9, confluence21=q21,
                          double9=double9, double21=double21, action=action, **dict(zip(SPECS, fire)))
            for key, value in values.items():
                f[key][d] = value
            # Register today's levels only after testing the current pullback.
            for key in ('breakout', 'box', 'gap', 'bottom'):
                level[key][~valid] = np.nan
            born['vwap'][~valid] = -1000
            breakout = valid & (c > a['prior_high20'][d]) & (pc <= a['prior_high20'][d-1])
            box = breakout & ((a['prior_high20'][d]/a['prior_low20'][d]-1)*100 <= 3*a['adr'][d-1])
            large = volume >= 2*a['vol20'][d-1]
            gap = valid & large & (o >= 1.10*pc) & (lo > ph)
            for key, mask, value in (('breakout', breakout, a['prior_high20'][d]),
                                     ('box', box, a['prior_high20'][d]), ('gap', gap, lo)):
                level[key][mask], born[key][mask] = value[mask], d
            level['bottom'][gap] = ph[gap]
            anchor = gap | (breakout & large)
            born['vwap'][anchor] = d
            numerator[anchor] = ((hi+lo+c)/3*volume)[anchor]
            denominator[anchor] = volume[anchor]
            nights.write(json.dumps(dict(day=str(day), active=int(status['active'].sum()),
                pullback=int(status['pullback'].sum()), **{key: list(map(str, codes[fire[k]]))
                for k, key in enumerate(SPECS)}))+'\n')
            if d % 200 == 0:
                log(f'F4 {label}: completed {d}/{len(days)} nights')
    for value in f.values():
        value.flush()
    write(folder/'meta.json', dict(days=days, codes=codes, fields=FIELDS, core=CORE,
        sha256={key: sha(folder/(key+'.npy')) for key in (*CORE, *FIELDS)},
        labels_read=False, resources=resources(), perturbation=label == 'perturbed'))
    return f


def load_features(label='train'):
    folder = OUT/'features'/label
    return {key: np.load(folder/(key+'.npy'), mmap_mode='r') for key in (*CORE, *FIELDS)}


def prepare():
    registry_check()
    once('prepare')
    feature_inputs()


def source_masks(days, codes):
    folder = HOME/'reports/f3_work/features/train'
    meta = read(folder/'meta.json')
    assert meta['days'] == list(days) and meta['codes'] == list(codes)
    result = {key: np.load(folder/(name+'.npy'), mmap_mode='r') for key, name in
              (('F3_list', 'active'), ('F3_fire', 'fire'))}
    for label, name in (('master_raw', 'master_raw'), ('master_filtered', 'master_filtered')):
        mask = np.zeros((len(days), len(codes)), bool)
        for d, row in enumerate(M.load_book(PREP, name)):
            for e in row:
                if e[2] > 0:
                    mask[d, e[1]] = True
        result[label] = mask
    return result


def mask_metrics(mask, days, codes, p, frozen, library, evidence, source):
    """Labels are used only here, after the market-only masks have been saved."""
    ci = {str(code): j for j, code in enumerate(codes)}
    by_code = {}
    for g in frozen:
        by_code.setdefault(g['code'], []).append(g)
    library_keys = {(g['code'], g['peak']): g for g in library}
    totals, per_leg = {}, []
    for g in frozen:
        if g['first_date'][:4] not in ('2024', '2025'):
            continue
        j = ci[g['code']]
        ix = np.flatnonzero(mask[max(0, g['first']-3):min(len(days), g['peak']), j])+max(0, g['first']-3)
        early = [int(d) for d in ix if g['top']/p['c'][d, j]-1 >= .5*g['gain']-1e-12]
        per_leg.append(dict(key=g['key'], year=g['first_date'][:4], code=g['code'],
            anchor=g['first_date'], peak=g['peak_date'], hits=[str(days[d]) for d in ix],
            early=[str(days[d]) for d in early], covered=bool(early)))
    for year in ('2024', '2025', 'all'):
        in_year = np.array([str(day)[:4] in ('2024', '2025') if year == 'all'
                            else str(day).startswith(year) for day in days])
        dates = np.flatnonzero(in_year)
        counts = np.array([np.count_nonzero(mask[d]) for d in dates])
        seen, tally, matched, his_matches = set(), Counter(), set(), set()
        for d in dates:
            for j in np.flatnonzero(mask[d]):
                code = str(codes[j])
                seen.add(code)
                gs = [g for g in by_code.get(code, ()) if max(0, g['first']-3) <= d < g['peak']]
                hit = bool(gs)
                early = any(g['top']/p['c'][d, j]-1 >= .5*g['gain']-1e-12 for g in gs)
                tally['hits'] += hit
                tally['early_hits'] += early
                end = min(len(days), d+61)
                complete = d+60 < len(days)
                highs = p['h'][d+1:end, j]
                available = len(highs) and np.isfinite(highs).any()
                peak = d+1+int(np.nanargmax(highs)) if available else None
                big = available and p['h'][peak, j]/p['c'][d, j]-1 >= .3
                tally['mature' if complete else 'incomplete'] += 1
                if big:
                    tally['big_complete' if complete else 'big_incomplete'] += 1
                    g = library_keys.get((code, peak))
                    if g:
                        tally['library_big'] += 1
                        tally['library_his'] += bool(g['his'])
                        if complete:
                            tally['library_big_complete'] += 1
                            tally['library_his_complete'] += bool(g['his'])
                        matched.add(g['id'])
                        if g['his']:
                            his_matches.add(g['id'])
                if year != 'all':
                    evidence.write(json.dumps(clean(dict(source=source, day=str(days[d]), code=code,
                        hit=hit, early=early, legs=[g['key'] for g in gs], complete60=complete,
                        big=bool(big), peak=str(days[peak]) if peak is not None else None,
                        library_id=library_keys.get((code, peak), {}).get('id'))))+'\n')
        n = int(counts.sum())
        covered = [g for g in per_leg if year == 'all' or g['year'] == year]
        totals[year] = dict(nights=len(dates), triggers=n, distinct=len(seen), hits=tally['hits'],
            precision=tally['hits']/n if n else 0., early_hits=tally['early_hits'],
            early_precision=tally['early_hits']/n if n else 0.,
            mean=float(counts.mean()) if len(counts) else None,
            median=float(np.median(counts)) if len(counts) else None,
            p90=float(np.quantile(counts, .9)) if len(counts) else None,
            minimum=int(counts.min()) if len(counts) else None,
            maximum=int(counts.max()) if len(counts) else None,
            coverage=sum(g['covered'] for g in covered), denominator=len(covered), forward=dict(tally),
            big_rate=tally['big_complete']/tally['mature'] if tally['mature'] else None,
            library_his_share=tally['library_his_complete']/tally['library_big_complete']
                if tally['library_big_complete'] else None,
            unique_library=len(matched), unique_library_his=len(his_matches))
    return dict(years=totals, legs=per_leg)


def gate(results):
    reference = results['F3_list']['years']['all']['precision']
    outcome = {}
    for name in SPECS:
        rows = results[name]['years']
        checks = dict(precision=rows['all']['precision'] >= 3*reference,
                      coverage2024=rows['2024']['coverage'] >= 5,
                      coverage2025=rows['2025']['coverage'] >= 11)
        outcome[name] = dict(checks=checks, eligible=all(checks.values()),
                             lift=rows['all']['precision']/reference if reference else None)
    return dict(reference=reference, threshold=3*reference, variants=outcome,
                eligible=[name for name, row in outcome.items() if row['eligible']])


def evaluate():
    registry_check()
    once('list_evaluation')
    meta = read(OUT/'features/train/meta.json')
    days, codes = meta['days'], meta['codes']
    p = {k: v[:len(days)] for k, v in U.load_panel().items() if k in U.FIELDS}
    frozen, library = read(HOME/'notes/legs_frozen.json')['legs'], U.library()
    masks = source_masks(days, codes)
    masks.update({name: load_features()[name] for name in SPECS})
    results = {}
    with (OUT/'evaluation_events.jsonl').open('w') as evidence:
        for name, mask in masks.items():
            results[name] = mask_metrics(mask, days, codes, p, frozen, library, evidence, name)
            write('list_metrics.json', results)
            log('F4 label-side list evaluation complete: '+name)
    write('gate.json', gate(results))


def new_book(A, name, label='train'):
    fire = load_features(label)[name]
    assert fire.shape == A['close'].shape
    book = F3.new_book(A, dict(fire=fire))
    return [[(*e[:5], 'f4_first_pullback', *e[6:]) for e in row] for row in book]


def build(A, directory, name, execution=PRIMARY, label='train', original=None):
    spec = F3.BASE if execution == 'M3B' else {}
    book, rules, ema = M3.build(A, directory, spec, original=original)
    return M.merge_books(book, new_book(A, name, label)), rules, ema


def run(A, name, execution, destination, span=TRAIN, directory=PREP, label='train'):
    old_out, old_build = M.OUT, M.build
    M.OUT = OUT
    M.build = lambda a, d, s: build(a, d, name, execution, label, original=old_build)
    try:
        return M.evaluate(A, directory, destination, M3.BASE, span)[0]
    finally:
        M.OUT, M.build = old_out, old_build


def compatibility():
    registry_check()
    once('compatibility')
    checks = {}
    for label, directory, span in (('train', PREP, TRAIN),
            ('continuous', HOME/'reports/m1_work/validation_prepared', (TRAIN[0], VALID[1]))):
        A = M3.arrays(directory)
        for name, spec in (('M2A', {}), ('M3B', F3.BASE)):
            book, rules, ema = M3.build(A, directory, spec)
            px = dict(dates=A['days'], **{k: A[k].astype(float) if k != 'codes' else A[k]
                                        for k in ('open', 'high', 'low', 'close', 'codes')})
            curve, dates, trades = Y.simulate(px, ema, rules, book, *span, audit=True)
            base = HOME/('reports/m2_work' if name == 'M2A' else 'reports/m3_work')
            ref = base/('candidates/'+name if label == 'train' else 'validation/continuous')
            checks[name+'_'+label] = dict(trades=clean(trades) == read(ref/'trades.json'),
                curve=clean(dict(days=dates, equity=curve)) == read(ref/'curve.json'),
                executions=sum(len(t['executions']) for t in trades))
            assert all(checks[name+'_'+label][k] for k in ('trades', 'curve'))
            log('unchanged original ledger: '+name+' '+label)
        del A, px, book, ema, trades
        gc.collect()
    write('compatibility.json', dict(ok=True, checks=checks, resources=resources(), new_candidate_accounts=0))


def account_prefix(A, directory, name, execution, label):
    book, rules, ema = build(A, directory, name, execution, label)
    px = dict(dates=A['days'], **{k: A[k].astype(float) if k != 'codes' else A[k]
                                for k in ('open', 'high', 'low', 'close', 'codes')})
    curve, dates, trades = Y.simulate(px, ema, rules, book, *TRAIN, audit=True)
    k = int(np.searchsorted(A['days'], CUT, side='right'))
    return clean(dict(book=book[:k], events=M.E15.B.execution_events(trades, CUT),
                      curve=[float(v) for d, v in zip(dates, curve) if d <= CUT]))


def prefix():
    registry_check()
    once('prefix')
    checks = {}
    for label, end in (('cut', CUT), ('perturbed', TRAIN[1])):
        feature_inputs(label, end)
        short, full = load_features(label), load_features()
        k = int(np.searchsorted(read(OUT/'features/train/meta.json')['days'], CUT, side='right'))
        checks[label] = {key: np.array_equal(short[key][:k], full[key][:k], equal_nan=True)
                         for key in (*CORE, *FIELDS)}
        assert all(checks[label].values()), checks[label]
        del short, full
        gc.collect()
    # Quote generation uses current close/low and prior ADR, so compare the real books as well.
    quote_checks = {}
    for label, directory in (('train', PREP), ('cut', HOME/'reports/m1_work/prefix_cut'),
                              ('perturbed', HOME/'reports/m1_work/prefix_perturbed')):
        A = M3.arrays(directory)
        for name in SPECS:
            book = clean(new_book(A, name, label)[:k])
            if label == 'train':
                write('quotes_'+name+'_prefix.json', book)
            else:
                quote_checks[label+'_'+name] = book == read(OUT/('quotes_'+name+'_prefix.json'))
        del A
        gc.collect()
    assert all(quote_checks.values()), quote_checks
    write('truncation.json', dict(ok=True, cutoff=CUT, features=checks, quotes=quote_checks,
        actual_bar_rebuild=True, labels_forbidden_during_build=True, resources=resources()))


def accounts():
    registry_check()
    once('accounts')
    admitted = read(OUT/'gate.json')['eligible']
    assert read(OUT/'truncation.json')['ok']
    if not admitted:
        write('selection.json', dict(chosen=None, eligible=[], reason='no list variant passed the fixed gate',
                                    primary_execution=PRIMARY, candidate_account_evaluations=0))
        write('validation_complete.json', dict(skipped=True, reason='list gate failed',
            standalone_evaluations=0, continuous_evaluations=0, market_2026_evaluations=0))
        return
    A, runs = M3.arrays(), {}
    for name in admitted:
        runs[name] = {}
        for execution in ('M2A', 'M3B'):
            runs[name][execution] = run(A, name, execution, 'candidates/'+name+'_'+execution)
            write('accounts_train.json', runs)
            gc.collect()
    baseline = M.summary(read(HOME/'reports/m2_work/candidates/M2A/metrics.json'))
    outcome = F3.select({name: r[PRIMARY] for name, r in runs.items()}, baseline)
    write('selection.json', dict(outcome, primary_execution=PRIMARY,
        candidate_account_evaluations=2*len(admitted), baseline=baseline))
    choice = outcome['chosen']
    if choice is None:
        write('validation_complete.json', dict(skipped=True, reason='account eligibility failed',
            standalone_evaluations=0, continuous_evaluations=0, market_2026_evaluations=0))
        return
    del A
    gc.collect()
    values = {}
    for label, directory in (('train', PREP), ('cut', HOME/'reports/m1_work/prefix_cut'),
                              ('perturbed', HOME/'reports/m1_work/prefix_perturbed')):
        A = M3.arrays(directory)
        if label != 'train':
            path = HOME/('reports/m2_work/profile_'+label+'_G1')
            A['_m2_G1'] = np.load(path.with_suffix('.npy'), mmap_mode='r'), read(path.with_suffix('.json'))
        A['_m2_perturb_qqq'] = label == 'perturbed'
        values[label] = account_prefix(A, directory, choice, PRIMARY, label)
        write('account_prefix_'+label+'.json', values[label])
        del A
        gc.collect()
    assert values['train'] == values['cut'] == values['perturbed']
    stored = read(OUT/f'candidates/{choice}_{PRIMARY}/trades.json')
    assert values['train']['events'] == clean(M.E15.B.execution_events(stored, CUT))
    write('account_truncation.json', dict(ok=True, chosen=choice, resources=resources()))
    once('validation')
    feature_inputs('validation', VALID[1])
    directory = HOME/'reports/m1_work/validation_prepared'
    A, results = M3.arrays(directory), {}
    for label, span in (('standalone', VALID), ('continuous', (TRAIN[0], VALID[1]))):
        results[label] = run(A, choice, PRIMARY, 'validation/'+label, span, directory, 'validation')
        write('validation.json', results)
    write('validation_complete.json', dict(chosen=choice, standalone_evaluations=1,
        continuous_evaluations=1, market_2026_evaluations=1, independent_out_of_sample=False))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('stage', choices=('freeze', 'prepare', 'evaluate', 'prefix', 'compatibility', 'accounts'))
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    offline()
    resources()
    globals()[args.stage]()


if __name__ == '__main__':
    main()
