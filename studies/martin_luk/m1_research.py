"""PLAN_M1_CN: offline causal mechanism replacements, then at most five frozen accounts."""
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

from . import e15_research as E15, ie47_e1 as M, y1_research as Y1
from studies.trader_replication import mainleg, system as Y

ROOT = Path(__file__).resolve().parents[2]
HOME = Path(__file__).resolve().parent
OUT = HOME/'reports/m1_work'
PREREG = HOME/'notes/PREREG_M1_CN.md'
TRAIN = ('2024-01-02', '2025-12-31')
VALID = ('2026-01-02', '2026-10-16')
CUT = '2025-06-30'
STARTED = time.monotonic()
read, sha = Y1.read, Y1.sha

# One mechanism per arm, declared before any training account is measured.
DIAGNOSTICS = {
    'B': dict(memory=True),
    'B_reclaim': dict(memory=True, b_reclaim=True),
    'E10': dict(trigger='e10'),
    'E11': dict(trigger='e11'),
    'parallel': dict(trigger='parallel'),
    'reclaim': dict(trigger='reclaim'),
    'reset': dict(reset=True),
    'queue': dict(queue=True),
    'structure2': dict(funding='structure2'),
    'structure3': dict(funding='structure3'),
    'structure3_75': dict(funding='structure3_75'),
    'structure4': dict(funding='structure4'),
    'H21A': dict(holding='H21A'),
    'R74_exit': dict(holding='R74_exit'),
    'R74': dict(execution='R74'),
    'P90': dict(pool='P90'),
    'P90_near': dict(pool='P90_near'),
}


def clean(x):
    if isinstance(x, dict):
        return {str(k): clean(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [clean(v) for v in x]
    if isinstance(x, np.ndarray):
        return clean(x.tolist())
    if isinstance(x, np.generic):
        return clean(x.item())
    return None if isinstance(x, float) and not np.isfinite(x) else x


def write(path, value):
    path = OUT/path if not isinstance(path, Path) else path
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix+'.tmp')
    tmp.write_text(json.dumps(clean(value), ensure_ascii=False, indent=1, allow_nan=False)+'\n', encoding='utf-8')
    tmp.replace(path)


def log(message):
    print(f'[{time.monotonic()-STARTED:.0f}s; {resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024:.0f} MiB] '
          +message, flush=True)


def offline():
    sys.dont_write_bytecode = True
    def guard(event, args):
        if event in ('socket.connect', 'socket.bind', 'socket.getaddrinfo', 'subprocess.Popen', 'os.system'):
            raise PermissionError('M1 is offline and single-process')
        if event == 'open' and not isinstance(args[0], int):
            if args[2] & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND):
                path = Path(os.fsdecode(args[0])).resolve()
                allowed = (OUT.resolve(), PREREG.resolve(), (HOME/'reports/M1_CN.md').resolve())
                if not any(path == p or path.is_relative_to(p) for p in allowed):
                    raise PermissionError(f'M1 output boundary: {path}')
    sys.addaudithook(guard)


def once(stage):
    with (OUT/f'{stage}_started.json').open('x', encoding='utf-8') as stream:
        json.dump(dict(time=time.time(), memory=Path('/proc/meminfo').read_text(),
                       source_sha256=sha(Path(__file__))), stream, indent=1)


def freeze():
    once('protocol')
    protected = [ROOT/'studies/trader_replication/systems.py', ROOT/'studies/trader_replication/mainleg.py',
                 HOME/'reports/final_system_r74.json', HOME/'reports/s7.json', M.PROFILE,
                 HOME/'notes/legs_frozen.json', HOME/'notes/trades.csv', Path(M.__file__),
                 HOME/'replicate.py']
    protected += sorted((ROOT/'studies/trader_screens').glob('*.py'))
    protected += [HOME/f'{n}_research.py' for n in ('e15', 'e19', 'e21', 'd1')]
    protected += [HOME/f'reports/{n}_CN.md' for n in ('D1', 'Y1', 'E16')]
    write('protocol.json', dict(task='PLAN_M1_CN, A line', train=TRAIN, validation=VALID,
        labels='Y1 frozen 48 legs; labels only used after account simulation', diagnostics=DIAGNOSTICS,
        training_policy='stop all accounts at 2025-12-31, terminal mark; no 2026 decisions or returns',
        crossing_legs='retain frozen gains and denominators; actual lots stop at training end',
        baseline='master+C062 replay on the identical training horizon',
        combined_capital='sum H/equity over both years / total sessions (cash included)',
        candidate_rules=dict(max_candidates=5, min_trades=52, max_win=.35,
            H='2024+2025 sum >= master+C062', capital='session-weighted 2024+2025 >= master+C062',
            ordering=['min annual five-target count', 'min annual cap_equity',
                      'min annual purity_gross', 'sum H'], tie='candidate ID ascending'),
        resources=dict(python='/opt/opend-us-options/.venv/bin/python', CPUQuota='60%', MemoryMax='900M', threads=1),
        memory_before=Path('/proc/meminfo').read_text(),
        protected_sha256={str(p.relative_to(ROOT)): sha(p) for p in protected},
        forbidden_writes=['martin_profile_ie29.py', 'martin_profile_ie42.py', 'f1_*', 'reports/f1_work/'],
        secret_guard='existing shared pre-commit/pre-push call secret_guard.py; installer did not overwrite hooks'))
    log('diagnostic protocol frozen')


def panel(upto):
    from studies import trader_data as TD
    from studies.trader_data import panel as TP
    return TP.build(TD.dataset('us', 'frozen'), upto=upto, write_cache=False)


def save_book(directory, name, book):
    write(directory/f'{name}.json', book)


def load_book(directory, name):
    return [[(tuple(e[0]) if isinstance(e[0], list) else e[0], *e[1:]) for e in row]
            for row in read(directory/f'{name}.json')]


def pools(A):
    """Replacement filters: top decile of dollar liquidity; optional distance <= one ADR."""
    liquid = (A['raw'] >= 1) & (A['to20'] >= 2e6)
    top = np.zeros_like(liquid)
    for t in range(len(top)):
        ix = np.flatnonzero(liquid[t] & np.isfinite(A['to20'][t]))
        if len(ix):
            top[t, ix] = A['to20'][t, ix] >= np.quantile(A['to20'][t, ix], .90)
    top &= A['adr'] >= 3
    with np.errstate(all='ignore'):
        near = np.minimum(np.abs(A['close']/A['e9']-1), np.abs(A['close']/A['e21']-1)) <= A['adr']/100
    return dict(P90=top, P90_near=top & near)


def prepare_master(directory, upto=TRAIN[1], perturb=False):
    from . import replicate as R
    from studies.trader_replication import systems
    directory.mkdir(parents=True, exist_ok=True)
    p = panel(upto)
    if perturb:
        perturb_panel(p)
    A = R.market_arrays('us', p)
    A['digest'] = p['digest']
    del p
    st, cfg = next(s for s in systems.all_() if s.id == 'martin_luk').load()
    trace = {}
    native, rules, mask, pool = st.build(A, cfg, trace)
    save_book(directory, 'native', native)
    for name in ('raw', 'filtered', 'capped'):
        save_book(directory, 'master_'+name, trace[name])
    write(directory/'master_rules.json', asdict(rules))
    ema = st.ema_inputs(A, pool, rules)
    np.save(directory/'idx_pb16.npy', ema['idx_pb16'])
    log(f'master book prepared through {upto}; {sum(map(len, native))} offered signals')
    del native, trace, mask, ema
    gc.collect()
    pool, watch, families = R.system_signals(A, cfg)
    np.save(directory/'master_nonb_fire.npy', R.union(families) | R.ep_signal(A, pool, **cfg.get('ep_opts', {})))
    del families
    f = R.setup_families(A, watch)
    e10 = R.union(f['E10'])
    e11 = R.union(f['E11'])
    del f
    b = R.base_path(A, pool, cfg['bpath'], **cfg.get('bopts', {}))
    for name, value in dict(master_pool=pool, master_watch=watch, master_e10=e10, master_e11=e11,
                            b_fire=b).items():
        np.save(directory/f'{name}.npy', value)
    # Eligibility is independent of the current-day trigger, exactly as in base_path.
    with np.errstate(all='ignore'):
        leader = R.S._past_any((A['pr126'] >= .8) & A['rank_pool'], 120)
        up = R.weekly_ema(A['close'], A['days'], 9) > R.weekly_ema(A['close'], A['days'], 21)
        near = (np.abs(A['close']/A['e9']-1) <= .03) | (np.abs(A['close']/A['e21']-1) <= .03)
    np.save(directory/'b_eligible.npy', pool & leader & R.prev(up) & R.prev(near))
    np.save(directory/'weekly_up.npy', up)
    del leader, up, near, e10, e11, b, watch
    for name, value in pools(A).items():
        np.save(directory/f'{name}_pool.npy', value)
        shifted = R.prev(value)
        # Same master entry logic; only its liquidity pool is replaced.
        replacement_trace = {}
        with patch.object(R, 'pool_for', lambda *_a, **_k: shifted):
            replacement = R.build_system(A, {k: v for k, v in cfg.items() if k != 'short'}, replacement_trace)[0]
        save_book(directory, name+'_master', replacement)
        save_book(directory, name+'_master_filtered', replacement_trace['filtered'])
        del replacement, replacement_trace, shifted
        gc.collect()
    write(directory/'master_prepared.json', dict(digest=A['digest'], days=A['days'], codes=A['codes'],
        peak_rss_mib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024))


def prepare_ie(directory, upto=TRAIN[1], perturb=False, replacements=True):
    from studies import trader_data as TD
    from studies.trader_screens import screens as S
    p = panel(upto)
    if perturb:
        perturb_panel(p)
    A = dict(p, raw=p['raw_close'], market='us', mode='frozen')
    shape = A['close'].shape
    A['adr'], A['to20'] = np.full(shape, np.nan), np.full(shape, np.nan)
    for start in range(0, shape[1], 64):
        sl = slice(start, start+64)
        with np.errstate(all='ignore'):
            A['adr'][:, sl] = S.rolling(A['high'][:, sl].astype(float)/A['low'][:, sl].astype(float)-1, 20, 'mean')*100
        A['to20'][:, sl] = S.rolling(A['turnover'][:, sl].astype(float), 20, 'mean')
    for name, n in (('e9', 9), ('e21', 21), ('e50', 50)):
        A[name] = S.ema(A['close'], n)
    selected = M.selection(p, TD.dataset('us', 'frozen'), 'frozen', progress=log)
    A['e8_scale'] = M.regime_scale(selected['qqq'], selected['pool'].sum(1), M.E8['E8c'])
    base, mask, _ = M.entry_book(A, selected['picks'], **M.E6['E6c'])
    A['_e14_base'] = base, M.e8_rules('E8c'), mask, selected['pool']
    st = E15.E15Study()
    st.build(A, dict(candidate='C062'))
    save_book(directory, 'ie_base', base)
    for name in ('open', 'high', 'low', 'close', 'adr', 'to20', 'e9', 'e21', 'e50', 'e8_scale'):
        np.save(directory/f'{name}.npy', A[name])
    for name, value in st.inputs(A).items():
        if name.startswith('e13_') or name.startswith('e14_'):
            np.save(directory/f'{name}.npy', value)
    np.save(directory/'ie_pool.npy', selected['pool'])
    write(directory/'ie_picks.json', selected['picks'])
    nights, offset = [], 0
    for t, js in zip(selected['night_indices'], selected['kept']):
        scores = selected['scores'][offset:offset+len(js)]
        offset += len(js)
        nights.append(dict(t=t, js=js, scores=scores, available=bool(selected['regime'][t] >= 0)))
    write(directory/'ie_nights.json', nights)
    if not replacements:
        write(directory/'ie_prepared.json', dict(days=A['days'], codes=A['codes'], digest=p['digest'],
            sources=selected['sources'], peak_rss_mib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024))
        log('IE47 and execution inputs prepared; unused replacement-pool profiles skipped')
        return
    # Reuse the unchanged fitted profile on newly eligible stocks, one stock at a time.
    new_pools = {n: np.load(directory/f'{n}_pool.npy', mmap_mode='r') for n in ('P90', 'P90_near')}
    eligible = np.zeros(shape, bool)
    for t, scope in zip(selected['night_indices'], selected['scopes']):
        eligible[t, scope] = True
    union = eligible & new_pools['P90']
    profile = read(M.PROFILE)
    scores = np.full(shape, -np.inf, np.float32)
    for number, j in enumerate(np.flatnonzero(union.any(0))):
        arrays = {k: p[v][:, j] for k, v in (('o', 'open'), ('h', 'high'), ('l', 'low'), ('c', 'close'),
                                             ('v', 'volume'), ('t', 'turnover'), ('raw_c', 'raw_close'))}
        arrays['days'] = list(map(str, p['days']))
        values = {k: v.astype(np.float32) for k, v in M.SI.per_stock(arrays, selected['qqq'], names=M.INDICATORS).items()
                  if k in M.INDICATORS}
        scores[:, j] = M.profile_scores(values, selected['regime'], profile)
        if number % 200 == 0:
            log(f'replacement pool profile {number}')
    for name, newpool in new_pools.items():
        rows, row_scores = [], []
        for row in nights:
            t = row['t']
            js = np.flatnonzero(eligible[t] & newpool[t]) if row['available'] else np.array([], int)
            rows.append(js)
            row_scores.append(scores[t, js])
        picks = M.select_nights(rows, row_scores, A['codes'], profile['cooldown'])
        write(directory/f'{name}_picks.json', {str(A['days'][r['t']]): [str(A['codes'][j]) for j in js]
                                             for r, js in zip(nights, picks)})
    write(directory/'ie_prepared.json', dict(days=A['days'], codes=A['codes'], digest=p['digest'],
        sources=selected['sources'], peak_rss_mib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024))
    log('IE47, replacement pools and execution inputs prepared')


def load_arrays(directory):
    meta = read(directory/'ie_prepared.json')
    A = {n: np.asarray(meta[n]) for n in ('days', 'codes')}
    for path in directory.glob('*.npy'):
        A[path.stem] = np.load(path, mmap_mode='r')
    A.update(market='us', mode='frozen', digest=meta['digest'])
    A['_e14_signals'] = {n: A[n] for n in ('e9', 'e21', 'adr', 'e13_add', 'e13_retry', 'e14_high', 'e14_reclaim')}
    with np.errstate(all='ignore'):
        c, h, l = (A[n] for n in ('close', 'high', 'low'))
        A['pdh'] = np.zeros(c.shape, bool)
        A['pdh'][1:] = c[1:] > h[:-1]
        A['support'] = np.zeros(c.shape, bool)
        for n in ('e9', 'e21'):
            e = A[n]
            A['support'][1:] |= (l[1:] <= e[:-1]) & (c[1:] >= e[:-1]) & (c[:-1] <= e[:-1])
        stack = (A['e9'] > A['e21']) & (A['e21'] > A['e50'])
        A['upgrade'] = np.zeros(c.shape, bool)
        A['upgrade'][1:] = (stack[1:] & ~stack[:-1]) | (A['weekly_up'][1:] & ~A['weekly_up'][:-1])
        A['m1_proof'] = (A['pdh'] | A['support']) & (c > A['e9']) & (A['e9'] > A['e21'])
    return A


def changed_picks(A, directory, name, reset=False):
    if name != 'original':
        return read(directory/f'{name}_picks.json')
    if not reset:
        return read(directory/'ie_picks.json')
    recent, picks = [], {}
    for row in read(directory/'ie_nights.json'):
        t = row['t']
        cooldown = set().union(*map(set, recent[-10:])) if recent else set()
        chosen = []
        if row['available']:
            for k in np.argsort(-np.asarray(row['scores']), kind='stable'):
                j = row['js'][k]
                if j not in cooldown or A['support'][t, j] or A['upgrade'][t, j]:
                    chosen.append(j)
                    if len(chosen) == 3:
                        break
        recent.append(chosen)
        picks[str(A['days'][t])] = [str(A['codes'][j]) for j in chosen]
    return picks


def watch_book(A, picks, trigger='', reset=False):
    """Five completed sessions; new structural events rearm only currently observed names."""
    ci = {str(c): j for j, c in enumerate(A['codes'])}
    out, live = [[] for _ in A['days']], {}
    c, h, l = (A[n] for n in ('close', 'high', 'low'))
    for d in range(1, len(out)):
        for rank, code in enumerate(picks.get(str(A['days'][d-1]), ())):
            live[ci[code]] = (d-1, d+4, rank)
        for j, (born, expiry, rank) in list(live.items()):
            if reset:
                if c[d-1, j] < A['e21'][d-1, j]:
                    del live[j]
                    continue
                if d-1 > born and (A['support'][d-1, j] or A['upgrade'][d-1, j]):
                    born, expiry = d-1, d+4
                    live[j] = (born, expiry, rank)
            if d > expiry:
                del live[j]
                continue
            ph, e9p, e21p = h[d-1, j], A['e9'][d-1, j], A['e21'][d-1, j]
            pdh = c[d, j] > ph
            near = abs(c[d-1, j]/e9p-1) <= .03
            e10 = near and (h[d, j] > ph or (e9p > e21p and l[d, j] <= e9p <= h[d, j]))
            e11 = (A['open'][d, j] > c[d-1, j]*1.01 and l[d, j] <= max(ph, e9p)
                   and c[d, j] > min(ph, e9p))
            reclaim = (l[d, j] <= e9p <= c[d, j]) or (l[d, j] <= e21p <= c[d, j])
            extra = {'': False, 'e10': e10, 'e11': e11, 'parallel': e10 or e11 or reclaim,
                     'reclaim': reclaim}[trigger]
            if not (pdh or extra):
                continue
            del live[j]
            stop = M.capped_stop(float(c[d, j]), float(l[d, j]), A['adr'][d-1, j])
            if stop is not None:
                out[d].append(((rank, born, str(A['codes'][j])), j, 1, float(c[d, j]), stop, M.CLOSE_KIND, None))
    return out


def master_adapter(A, book):
    return [[((rank, d, str(A['codes'][e[1]])), e[1], 1, float(e[3]), float(e[4]), 'master_close', None)
             for rank, e in enumerate(sorted(row, key=lambda e: e[0])) if e[2] > 0]
            for d, row in enumerate(book)]


def b_book(A, reclaim=False):
    mask = A['b_fire'].copy()
    if reclaim:
        ok = np.zeros_like(mask)
        ok[1:] = ((A['low'][1:] <= A['e9'][:-1]) & (A['close'][1:] >= A['e9'][:-1])) | \
                 ((A['low'][1:] <= A['e21'][:-1]) & (A['close'][1:] >= A['e21'][:-1]))
        mask &= ok
    out = [[] for _ in A['days']]
    for d in np.flatnonzero(mask.any(1)):
        for rank, j in enumerate(sorted(np.flatnonzero(mask[d]), key=lambda j: -A['to20'][d-1, j])):
            stop = M.capped_stop(float(A['close'][d, j]), float(A['low'][d, j]), A['adr'][d-1, j])
            if stop is not None:
                out[d].append(((rank+3, d, str(A['codes'][j])), int(j), 1, float(A['close'][d, j]), stop, 'm1_b', None))
    return out


def merge_books(base, extra):
    return [list(row)+[e for e in more if e[1] not in {r[1] for r in row}] for row, more in zip(base, extra)]


def queue_book(A, book, structural=False):
    out = []
    for d, row in enumerate(book):
        offered = []
        for e in row:
            retry, born, rank = int('retry' in e[5]), e[0][1], e[0][0]
            if structural:
                j = e[1]
                with np.errstate(all='ignore'):
                    distance = min(abs(A['close'][d, j]/A['e9'][d, j]-1),
                                   abs(A['close'][d, j]/A['e21'][d, j]-1))/(A['adr'][d-1, j]/100)
                quality = (retry, -int(A['m1_proof'][d, j]), float(distance) if np.isfinite(distance) else np.inf,
                           -float(A['to20'][d-1, j]))
                priority = (quality, born, rank, str(A['codes'][j]))
            else:
                priority = (retry, born, rank, str(A['codes'][e[1]]))
            offered.append((priority, *e[1:]))
        out.append(offered)
    return out


def build(A, directory, spec):
    basis = spec.get('basis', 'ie')
    pool_name = spec.get('pool', 'original')
    st = E15.E15Study()
    if basis == 'master':
        name = 'master_filtered' if spec.get('queue') else 'master_capped'
        if pool_name != 'original':
            original = load_book(directory, pool_name+'_master'+('_filtered' if spec.get('queue') else ''))
        else:
            original = load_book(directory, name)
        if spec.get('b_reclaim'):
            # Change only B-exclusive signals, before the original four-offer cap.
            original = load_book(directory, 'master_filtered')
            filtered = []
            for d, row in enumerate(original):
                keep = []
                for e in row:
                    j = e[1]
                    reclaimed = d > 0 and ((A['low'][d, j] <= A['e9'][d-1, j] <= A['close'][d, j]) or
                                           (A['low'][d, j] <= A['e21'][d-1, j] <= A['close'][d, j]))
                    if A['master_nonb_fire'][d, j] or reclaimed:
                        keep.append(e)
                filtered.append(keep if spec.get('queue') else sorted(keep, key=lambda e: e[0])[:4])
            original = filtered
        if spec.get('trigger') == 'reclaim':
            original = load_book(directory, 'master_filtered')
            original = [[e for e in row if A['support'][d, e[1]] or A['pdh'][d, e[1]]]
                        for d, row in enumerate(original)]
            if not spec.get('queue'):
                original = [sorted(row, key=lambda e: e[0])[:4] for row in original]
        base = master_adapter(A, original)
    else:
        picks = changed_picks(A, directory, pool_name, spec.get('reset', False))
        if not spec.get('trigger') and not spec.get('reset') and pool_name == 'original':
            base = load_book(directory, 'ie_base')
        else:
            base = watch_book(A, picks, spec.get('trigger', ''), spec.get('reset', False))
    if spec.get('memory') and basis != 'master':
        base = merge_books(base, b_book(A, spec.get('b_reclaim', False)))
    if spec.get('hybrid'):
        name = 'master_filtered' if spec.get('queue') else 'master_capped'
        more = master_adapter(A, load_book(directory, name))
        more = [[((e[0][0]+3, *e[0][1:]), *e[1:]) for e in row] for row in more]
        base = merge_books(base, more)
    A['_e14_base'] = base, M.e8_rules('E8c'), np.zeros(A['close'].shape, bool), A['ie_pool']
    A.pop('_e15_books', None)
    book, rules, _, pool = st.build(A, dict(candidate='C062'))
    if spec.get('s1'):
        from . import e16_research as E16, e19_research as E19
        book = E16.overlay_book(A, base, read(directory/'ie_picks.json'), A['e21'])[0]
        A['_e14_base'] = book, replace(M.e8_rules('E8c'), **E19.SPECS['S1'][1]), np.zeros_like(pool), pool
        A.pop('_e15_books', None)
        book, rules, _, pool = st.build(A, dict(candidate='C062'))
    funding = spec.get('funding', '')
    if funding:
        mult = float(funding[len('structure')])
        rules = replace(rules, proof_confirm_signal='m1_proof', proof_target_mult=mult,
                        max_position=.75 if funding.endswith('_75') else .5)
    if spec.get('holding') == 'H21A':
        rules = replace(rules, proof_trail_adds=0, proof_trail_r=0.)
    elif spec.get('holding') == 'R74_exit':
        rules = replace(rules, trims=(10,), trim_frac=.30, trail='e21', stop_ema_only=False,
                        stop_ema_buffer=-1., proof_trail_adds=0, proof_trail_r=0.)
    if spec.get('execution') == 'R74':
        native = read(directory/'master_rules.json')
        for k in ('trims', 'short_trims', 'add_levels', 'short_targets', 'intraday_kinds', 'month_cap_ladder'):
            if isinstance(native[k], list):
                native[k] = tuple(native[k])
        rules = Y.Rules(**native)
        rules = replace(rules, management_by_kind={}, max_open_by_kind={}, intraday_kinds=(), borrow_rate=0.,
                        max_new_long=4)
        # The entry tuple's C062 probe cap must not override R74's own initial position cap.
        book = [[tuple(e[:8])+(None,)+tuple(e[9:]) if len(e) > 8 else e for e in row] for row in book]
    if spec.get('queue'):
        # Engine caps count successful fills and already skip held tickers. Fresh setups precede retries.
        book = queue_book(A, book, spec.get('order') == 'structure')
        kinds = {e[5] for row in book for e in row if 'retry' not in e[5]}
        rules = replace(rules, max_new_long=4, max_open_by_kind={**rules.max_open_by_kind, 'e14_retry': 2},
                        make_room_kind={k: 'e14_retry' for k in kinds})
    ema = st.ema_inputs(A, pool, rules)
    if rules.risk_scale == 'idx_pb16':
        ema['idx_pb16'] = A['idx_pb16']
        # R74 computes EMAs after converting the stored float32 closes to float64.
        from . import luk
        for name, n in (('e9', 9), ('e21', 21)):
            if name in ema:
                key = 'native_'+name
                if key not in A:
                    A[key] = luk.ema(A['close'].astype(float), n)
                ema[name] = A[key]
    return book, rules, ema


class Prices:
    def __init__(self, A):
        self.A, self.ci = A, {str(c): j for j, c in enumerate(A['codes'])}

    def __getitem__(self, code):
        j = self.ci[code.removeprefix('SHORT:')]
        return {k: self.A[v][:, j] for k, v in (('o', 'open'), ('h', 'high'), ('l', 'low'), ('c', 'close'))}


def adapt(trades, calendar, rules, prices=None):
    di = {str(d): i for i, d in enumerate(calendar)}
    out, maximum = [], 0.
    for number, t in enumerate(trades):
        short = t['side'] < 0
        fills = []
        for e in t['executions']:
            buy = e['action'] in ('entry', 'add')
            rate = (rules.sell_cost if buy else rules.buy_cost) if short else (rules.buy_cost if buy else rules.sell_cost)
            fills.append(dict(index=di[e['time']], quantity=e['shares']*(1 if buy else -1), price=e['price'],
                              fee=e['shares']*e['price']*rate, open=e['action'] == 'end'))
        pieces = mainleg.lots(fills)
        if short:
            for r in pieces:
                r['pnl'] = r['shares']*(r['price']-r['exit_price'])-r['buy_fee']-r['sell_fee']
                if rules.borrow_rate:
                    assert prices is not None, 'borrow attribution needs actual prior closes'
                    r['borrow_fee'] = (rules.borrow_rate/252*r['shares'] *
                                       float(np.sum(prices[t['code']]['c'][r['entry']:r['exit']])))
                    r['pnl'] -= r['borrow_fee']
        residual = t['pnl']-sum(r['pnl'] for r in pieces)
        maximum = max(maximum, abs(residual))
        notional = sum(r['shares']*r['price'] for r in pieces)
        for r in pieces:
            r['residual'] = residual*r['shares']*r['price']/notional
            r['pnl'] += r['residual']
        confirmed = t.get('confirmed_day')
        if not confirmed and not rules.proof_risk:
            confirmed = next((e['time'] for e in t['executions'] if e['action'] == 'add'), None)
        out.append(dict(id=number, code=('SHORT:' if short else '')+t['code'], entry=di[t['entry']],
                        pnl=t['pnl'], closed=t['why'] != 'end', lots=pieces,
                        confirmed=di[confirmed] if confirmed else None))
    assert maximum < 1e-9, maximum
    return out, maximum


def measure(A, trades, curve, dates, rules, span):
    frozen = read(HOME/'notes/legs_frozen.json')
    calendar = list(map(str, A['days']))
    assert calendar == frozen['calendar'][:len(calendar)]
    normalized, residual = adapt(trades, calendar, rules, Prices(A))
    equity = np.ones(len(calendar))
    lo, hi = np.searchsorted(A['days'], span[0]), np.searchsorted(A['days'], span[1], side='right')
    equity[lo:hi] = curve
    # Cash warmup days are removed from the annual denominator below, exactly as in Y1's 2024+ account.
    ticker_years = {(r['code'], r['anchor'][:4]) for r in frozen['audit'] if r['anchor']}
    available = [g for g in frozen['legs'] if g['first'] < len(calendar)]
    other = [g for g in frozen['other_legs'] if g['first'] < len(calendar)]
    result = mainleg.summary_account(normalized, available, Prices(A), calendar, equity, other, ticker_years)
    stats = Y.stats(curve, dates, trades)
    for year in tuple(result['years']):
        if year not in stats['by_year']:
            del result['years'][year]
            continue
        row = result['years'][year]
        ix = [i for i, d in enumerate(dates) if str(d).startswith(year)]
        values = np.r_[curve[ix[0]-1] if ix[0] else 1., curve[ix]]
        row['account_return'] = stats['by_year'][year]
        row['maxdd'] = float(np.max(1-values/np.maximum.accumulate(values)))
        row['targets'] = Y1.targets(row, row['coverage']['including_censored'])
        row['target_count'] = sum(row['targets']['checks'][k] for k in ('capital', 'gross', 'early', 'capture', 'top10'))
    result['legs'] = [g for g in result['legs'] if span[0][:4] <= g['year'] <= span[1][:4]]
    result.update(stats=stats, max_adapter_residual=residual,
                  borrow_fee=sum(r.get('borrow_fee', 0.) for t in normalized for r in t['lots']))
    return result


def summary(result):
    return dict(years=result['years'], stats=result['stats'],
                H=sum(r['H'] for r in result['years'].values()),
                cap_equity=sum(r['capital_days']['his_equity'] for r in result['years'].values()) /
                           sum(r['sessions'] for r in result['years'].values()))


def offer_funnel(A, book, result, span):
    """Evaluation only: the account's actual early fills versus its upstream close offers."""
    frozen = read(HOME/'notes/legs_frozen.json')
    by_code, offers = {}, {}
    for g in frozen['legs']:
        by_code.setdefault(g['code'], []).append(g)
    for d, row in enumerate(book):
        if not span[0] <= str(A['days'][d]) <= span[1]:
            continue
        for e in row:
            code = str(A['codes'][e[1]])
            if e[2] < 0 or code not in by_code:
                continue
            g = mainleg.leg_at(code, d, by_code[code], e[3], keep=.5)
            if g:
                offers.setdefault(g['key'], set()).add(str(A['days'][d]))
    return [dict(key=g['key'], code=g['code'], year=g['year'], offered=sorted(offers.get(g['key'], ())),
                 early=g['covered'], any=g['any'], H=g['pnl'], capture=g['capture_total'],
                 first_fill=g['first_fill'], offset=g['offset']) for g in result['legs']]


class AttemptStream:
    """Flush the preceding record after the engine assigns its final refusal reason."""
    def __init__(self, path):
        self.stream = path.open('w', encoding='utf-8')
        self.pending = None
        self.counts = Counter()

    def flush(self):
        if self.pending is not None:
            row = self.pending
            held = row.pop('held')
            row['held_confirmed'] = sum(q['confirmed'] for q in held)
            row['held_retries'] = sum('retry' in q['kind'] for q in held)
            self.counts[row['reason']] += 1
            self.stream.write(json.dumps(clean(row), ensure_ascii=False)+'\n')
            self.pending = None

    def append(self, row):
        self.flush()
        self.pending = row

    def close(self):
        self.flush()
        self.stream.close()


def evaluate(A, directory, name, spec, span=TRAIN, save=True):
    book, rules, ema = build(A, directory, spec)
    destination = OUT/name
    destination.mkdir(parents=True, exist_ok=True)
    attempts = AttemptStream(destination/'attempts.jsonl')
    track = {'entry_attempts': attempts}
    px = {n: A[n].astype(float) if spec.get('execution') == 'R74' and n != 'codes' else A[n]
          for n in ('open', 'high', 'low', 'close', 'codes')}
    px['dates'] = A['days']
    try:
        curve, dates, trades = Y.simulate(px, ema, rules, book, *span, audit=True, track=track)
    finally:
        attempts.close()
    if rules.proof_risk:
        E15.execution_audit(trades, rules, allow_add_exit=('make_room',))
    result = measure(A, trades, curve, dates, rules, span)
    result['funnel'] = offer_funnel(A, book, result, span)
    terminal = sum(e['shares']*e['price']*(rules.sell_cost if t['side'] > 0 else rules.buy_cost)
                   for t in trades for e in t['executions'] if e['action'] == 'end')
    error = sum(t['pnl'] for t in trades)+terminal-track['margin']-(curve[-1]-1)
    assert abs(error) < 1e-9, error
    if save:
        write(destination/'trades.json', trades)
        write(destination/'curve.json', dict(days=dates, equity=curve))
        write(destination/'rules.json', asdict(rules))
        write(destination/'metrics.json', result)
        write(destination/'attempt_counts.json', attempts.counts)
        write(destination/'reconciliation.json', dict(error=error, financing=track['margin'], terminal_fee=terminal))
    log(f'{name}: '+str({y: (round(r["account_return"], 3), round(r["cap_equity"], 3),
                        round(r["H"], 3), r["n_trades"]) for y, r in result["years"].items()}))
    return summary(result), trades, dict(days=dates, equity=curve)


def defaults(A, directory):
    checks = {}
    refs = {'IE47_C062': ('e21_work/BASE_train', 'C062_2024', dict(basis='ie')),
            'IE47_S1': ('e21_work/S1_train', 'C062_2024', dict(basis='ie', s1=True)),
            'master_C062': ('e15_work/master_swap/train', 'C062_2024', dict(basis='master'))}
    for name, (folder, prefix, spec) in refs.items():
        result, trades, curve = evaluate(A, directory, 'baseline/'+name, spec)
        # Original annotations are evaluation-only and were appended after simulation.
        expected = read(HOME/'reports'/folder/f'{prefix}_trades.json')
        annotations = {'origin', 'observed', 'attempt'}
        expected = [{k: v for k, v in t.items() if k not in annotations} for t in expected]
        checks[name] = dict(trades=trades == expected,
                           curve=clean(curve) == read(HOME/'reports'/folder/f'{prefix}_curve.json'))
        assert all(checks[name].values()), (name, checks[name])
    write('defaults.json', checks)
    return checks


def diagnose():
    if (OUT/'diagnostics_started.json').exists():
        assert not (OUT/'diagnostics_complete.json').exists(), 'diagnostics already complete'
        resumes = read(OUT/'diagnostics_resumed.json') if (OUT/'diagnostics_resumed.json').exists() else []
        if isinstance(resumes, dict):
            resumes = [resumes]
        resumes.append(dict(source_sha256=sha(Path(__file__)),
              reason='incomplete run resumed; retain completed arms; native execution uses its original float64 OHLC'))
        write('diagnostics_resumed.json', resumes)
    else:
        once('diagnostics')
    directory = OUT/'prepared'
    A = load_arrays(directory)
    defaults(A, directory)
    runs = read(OUT/'diagnostics.json') if (OUT/'diagnostics.json').exists() else {}
    for basis in ('ie', 'master'):
        for name, spec in DIAGNOSTICS.items():
            key = f'{basis}_{name}'
            if key in runs:
                continue
            runs[key] = evaluate(A, directory, 'diagnostics/'+key, dict(spec, basis=basis))[0]
            write('diagnostics.json', runs)
            gc.collect()
    write('diagnostics_complete.json', dict(runs=len(runs), years=('2024', '2025'),
        peak_rss_mib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024,
        source_sha256=sha(Path(__file__))))


def select(runs, baseline):
    eligible, failures = [], {}
    for name, r in runs.items():
        failed = [y+'_'+k for y in ('2024', '2025') for k in ('trades', 'win')
                  if not r['years'][y]['targets']['checks'][k]]
        if r['H']+1e-12 < baseline['H']:
            failed.append('H')
        if r['cap_equity']+1e-12 < baseline['cap_equity']:
            failed.append('capital')
        failures[name] = failed
        if not failed:
            eligible.append(name)
    def key(name):
        r = runs[name]
        rows = list(r['years'].values())
        return (-min(x['target_count'] for x in rows), -min(x['cap_equity'] for x in rows),
                -min(x['purity_gross'] or 0. for x in rows), -r['H'], name)
    ranked = sorted(eligible, key=key)
    return dict(eligible=ranked, chosen=ranked[0] if ranked else None, failures=failures)


def check_sources(registry):
    current = {p: sha(ROOT/p) for p in registry['code_sha256']}
    if current == registry['code_sha256']:
        return
    correction = read(OUT/'source_compatibility.json')
    assert correction['registered_code_sha256'] == registry['code_sha256']
    assert correction['corrected_code_sha256'] == current
    assert correction['registry_sha256'] == sha(OUT/'candidates.json')
    assert correction['prereg_sha256'] == sha(PREREG)
    assert [p for p in current if current[p] != registry['code_sha256'][p]] == [str(Path(__file__).relative_to(ROOT))]


def candidates():
    once('candidates')
    registry = read(OUT/'candidates.json')
    assert 0 < len(registry['specs']) <= 5 and registry['prereg_sha256'] == sha(PREREG)
    if registry['diagnostics_sha256'] != sha(OUT/'diagnostics.json'):
        correction = read(OUT/'source_compatibility.json')
        assert correction['registered_diagnostics_sha256'] == registry['diagnostics_sha256']
        assert correction['corrected_diagnostics_sha256'] == sha(OUT/'diagnostics.json')
    check_sources(registry)
    A = load_arrays(OUT/'prepared')
    defaults(A, OUT/'prepared')
    runs = {}
    for name, spec in registry['specs'].items():
        runs[name] = evaluate(A, OUT/'prepared', 'candidates/'+name, spec)[0]
        write('candidates_train.json', runs)
    baseline = summary(read(OUT/'baseline/master_C062/metrics.json'))
    selection = select(runs, baseline)
    write('selection.json', dict(selection, prereg_sha256=sha(PREREG),
          candidates_sha256=sha(OUT/'candidates_train.json'), independent_out_of_sample=False))
    log('selected '+str(selection))


def perturb_panel(p):
    k = int(np.searchsorted(p['days'], CUT, side='right'))
    for name in ('open', 'high', 'low', 'close', 'raw_close'):
        p[name][k:] *= 3
    p['volume'][k:] *= 2
    p['turnover'][k:] *= 6


def prefix_value(A, directory, spec):
    book, rules, ema = build(A, directory, spec)
    px = dict(dates=A['days'], **{n: A[n].astype(float) if spec.get('execution') == 'R74' and n != 'codes' else A[n]
                                for n in ('open', 'high', 'low', 'close', 'codes')})
    trades = Y.simulate(px, ema, rules, book, *TRAIN, audit=True)[2]
    k = int(np.searchsorted(A['days'], CUT, side='right'))
    return clean(dict(book=book[:k], events=E15.B.execution_events(trades, CUT),
                      picks={d: cs for d, cs in changed_picks(A, directory, spec.get('pool', 'original'),
                             spec.get('reset', False)).items() if d <= CUT}))


def prefix():
    once('prefix')
    choice = read(OUT/'selection.json')['chosen']
    assert choice, 'No eligible candidate: do not measure 2026'
    registry = read(OUT/'candidates.json')
    assert registry['prereg_sha256'] == sha(PREREG)
    check_sources(registry)
    spec = registry['specs'][choice]
    full = prefix_value(load_arrays(OUT/'prepared'), OUT/'prepared', spec)
    actual_events = clean(E15.B.execution_events(read(OUT/f'candidates/{choice}/trades.json'), CUT))
    assert full['events'] == actual_events, 'prefix replay differs from the selected training ledger'
    write('prefix_full.json', full)
    comparisons = {}
    for name in ('cut', 'perturbed'):
        directory = OUT/('prefix_'+name)
        actual = prefix_value(load_arrays(directory), directory, spec)
        write('prefix_'+name+'.json', actual)
        comparisons[name] = {k: full[k] == actual[k] for k in full}
    ok = all(all(r.values()) for r in comparisons.values())
    write('truncation.json', dict(ok=ok, cut=CUT, comparisons=comparisons, chosen=choice,
        events=len(full['events']), code_sha256=sha(Path(__file__)), engine_sha256=sha(Path(Y.__file__))))
    assert ok, comparisons
    log('truncation and real future-bar perturbation passed')


def validate():
    assert read(OUT/'truncation.json')['ok']
    once('validation')
    registry = read(OUT/'candidates.json')
    assert registry['prereg_sha256'] == sha(PREREG)
    check_sources(registry)
    choice = read(OUT/'selection.json')['chosen']
    spec = registry['specs'][choice]
    A = load_arrays(OUT/'validation_prepared')
    runs = {}
    for name, span in (('standalone', VALID), ('continuous', (TRAIN[0], VALID[1]))):
        runs[name] = evaluate(A, OUT/'validation_prepared', 'validation/'+name, spec, span)[0]
        write('validation.json', runs)
    write('validation_complete.json', dict(chosen=choice, standalone_evaluations=1, continuous_evaluations=1,
                                         independent_out_of_sample=False))


def native():
    """Original registered R74+S7 baseline, using Y1 FIFO attribution including short O business."""
    if (OUT/'native_started.json').exists():
        assert not (OUT/'baseline/native_master/metrics.json').exists(), 'native baseline already complete'
        write('native_resumed.json', dict(reason='explicit attribution of original short stock-borrow fees'))
    else:
        once('native')
    directory = OUT/'prepared'
    A = load_arrays(directory)
    cfg = read(directory/'master_rules.json')
    for k in ('trims', 'short_trims', 'add_levels', 'short_targets', 'intraday_kinds', 'month_cap_ladder'):
        if isinstance(cfg[k], list):
            cfg[k] = tuple(cfg[k])
    rules = Y.Rules(**cfg)
    book = load_book(directory, 'native')
    # Native books have nested priority keys, which need recursive tuples for sorting.
    def tuples(x):
        return tuple(tuples(v) for v in x) if isinstance(x, list) else x
    book = [[(tuples(e[0]), *e[1:]) for e in row] for row in book]
    px = dict(dates=A['days'], **{n: A[n].astype(float) if n != 'codes' else A[n]
                                for n in ('open', 'high', 'low', 'close', 'codes')})
    from . import luk
    ema = {n: luk.ema(A['close'].astype(float), length) for n, length in (('e9', 9), ('e21', 21))}
    ema['idx_pb16'] = A['idx_pb16']
    track = {}
    curve, dates, trades = Y.simulate(px, ema, rules, book, *TRAIN, audit=True, track=track)
    result = measure(A, trades, curve, dates, rules, TRAIN)
    result['funnel'] = offer_funnel(A, book, result, TRAIN)
    old = read(HOME/'reports/d1_work/master_curve.json')
    expected_curve = [v for d, v in zip(old['days'], old['equity']) if TRAIN[0] <= d <= TRAIN[1]]
    old_trades = read(HOME/'reports/d1_work/master_trades.json')
    checks = dict(curve=clean(curve) == expected_curve,
                  events=E15.B.execution_events(trades, TRAIN[1]) == E15.B.execution_events(old_trades, TRAIN[1]))
    write('native_checks.json', checks)
    assert all(checks.values()), checks
    write('baseline/native_master/trades.json', trades)
    write('baseline/native_master/curve.json', dict(days=dates, equity=curve))
    write('baseline/native_master/metrics.json', result)
    write('baseline/native_master/rules.json', asdict(rules))
    terminal = sum(e['shares']*e['price']*(rules.sell_cost if t['side'] > 0 else rules.buy_cost)
                   for t in trades for e in t['executions'] if e['action'] == 'end')
    error = sum(t['pnl'] for t in trades)+terminal-track['margin']-(curve[-1]-1)
    assert abs(error) < 1e-9, error
    write('baseline/native_master/reconciliation.json', dict(error=error, financing=track['margin'],
          stock_borrow=result['borrow_fee'], terminal_fee=terminal))
    log('registered native baseline measured on Y1 48 legs')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('stage', choices=('freeze', 'prepare-master', 'prepare-ie', 'diagnose', 'native',
                                          'candidates', 'prefix', 'validate'))
    parser.add_argument('--directory', default='prepared')
    parser.add_argument('--upto', default=TRAIN[1])
    parser.add_argument('--perturb', action='store_true')
    parser.add_argument('--skip-replacements', action='store_true')
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    offline()
    if args.stage.startswith('prepare-'):
        directory = OUT/args.directory
        record = OUT/(args.directory+'_'+args.stage+'_started.json')
        if not record.exists():
            once(args.directory+'_'+args.stage)
        else:
            assert not (OUT/'diagnostics_started.json').exists(), 'training inputs already measured'
        if args.stage == 'prepare-master':
            prepare_master(directory, args.upto, args.perturb)
        else:
            prepare_ie(directory, args.upto, args.perturb, not args.skip_replacements)
    else:
        globals()[args.stage]()
