"""PREREG_E12_CN.md: a standing watch list scanned every close for his setups, bought at that close; five candidates
selected on 2024-25 by his trades we bought and closed in profit, 2026 once."""
from __future__ import annotations

import argparse
import csv
from bisect import bisect_left
from contextlib import ExitStack
from dataclasses import replace
import json
from pathlib import Path
import resource
from unittest.mock import patch

import numpy as np

from studies import trader_data as TD
from studies.trader_data import panel as TP, supplemental as SP
from studies.trader_replication import gate as G, panels, system as Y
from studies.trader_screens import screens as S
from . import e1_research as E, e8_research as E8, e10_research as X, ie47_e1 as M
from .e1_board_smoke import offline
from .ie47_audit import progress, write

ROOT = Path(__file__).resolve().parents[2]
OUT = M.STUDY.reports
WORK = OUT/'e12_work'
PREREG = M.STUDY.root/'notes/PREREG_E12_CN.md'
RESULT = OUT/'e12_train.json'
SELECTED = OUT/'e12_selected.json'
VALIDATION = OUT/'e12_validation.json'
CANDIDATES = ('C1', 'C2', 'C3', 'C4', 'C5')            # preregistered tie order
PRIORITY = dict(D0=0, D1a=0, D1b=0, EP=1, PB=2, D1c=3)
PER_NIGHT = 5
SPEC = dict(C1=dict(channels=('D0',), pool='strict', order='profile'),
            C2=dict(channels=('D1a', 'D1b', 'D1c'), pool='wide', order='turnover'),
            C3=dict(channels=('D1a', 'D1b', 'D1c', 'EP'), pool='wide', order='turnover'),
            C4=dict(channels=('D1a', 'D1b', 'D1c', 'EP', 'PB'), pool='wide', order='turnover'),
            C5=dict(channels=('D1a', 'D1b', 'D1c', 'EP', 'PB'), pool='wide', order='comove', flag=True))


def fingerprints():
    paths = (PREREG, M.PROFILE, Path(M.__file__), Path(X.__file__), Path(__file__), Path(Y.__file__), Path(E.__file__))
    return {str(p.relative_to(ROOT)): SP.sha(p) for p in paths}


def lag(x, k):
    """out[t] = x[t-k]; NaN (False for booleans) before k."""
    out = np.full(x.shape, False if x.dtype == bool else np.nan, x.dtype if x.dtype == bool else float)
    out[k:] = x[:len(x)-k]
    return out


def span_max(x, a, b):
    """Max of x[t-a..t-b] (a >= b >= 0); NaN while any is missing."""
    out = lag(x, b)
    for k in range(b+1, a+1):
        out = np.maximum(out, lag(x, k))
    return out


def span_min(x, a, b):
    out = lag(x, b)
    for k in range(b+1, a+1):
        out = np.minimum(out, lag(x, k))
    return out


def watch_list(pool_prev, close, e50):
    """In the list from the night after any pool night; out after three closes below the 50 EMA or a 20-day
    closing low, both judged at the previous close."""
    with np.errstate(invalid='ignore'):
        below = close < e50
        out = (below & lag(below, 1) & lag(below, 2)) | (close <= span_min(close, 19, 0))
    wl = np.zeros(close.shape, bool)
    for t in range(1, len(close)):
        wl[t] = (wl[t-1] & ~out[t-1]) | pool_prev[t]
    return wl


def setups(P, pool_prev, scope_prev, flag=False):
    """name -> days x codes masks; everything at day t uses prices of t and earlier only."""
    o, h, l, c = (np.asarray(P[k], float) for k in ('open', 'high', 'low', 'close'))
    adr = np.asarray(P['adr'], float)/100
    e9, e21, e50 = S.ema(c, 9), S.ema(c, 21), S.ema(c, 50)
    with np.errstate(invalid='ignore', divide='ignore'):
        rng = h/l-1
        h1, l1, adr1 = lag(h, 1), lag(l, 1), lag(adr, 1)
        r5, r10 = c/lag(c, 5)-1, c/lag(c, 10)-1
        ext = c/e21-1
        upper = (c-l)/np.maximum(h-l, 1e-9)
        inside1 = (h1 <= lag(h, 2)) & (l1 >= lag(l, 2))
        tight1 = inside1 | (lag(rng, 1) <= .5*adr1)
        coil3 = span_max(h, 3, 1)/span_min(l, 3, 1)-1 <= adr
        leader = (e9 > e21) & (e21 > e50) & (c > e9)
        extended = (ext >= .2) | (r10 >= .25)
        wl = watch_list(pool_prev, c, e50)
        base = wl & leader & np.isfinite(adr1)
        out = dict(D0=base & (c > h1))
        d1a = c > h1
        d1a &= (tight1 | coil3) & (upper >= .6) & (ext <= .1) & (r5 <= .15)
        flag3 = (rng <= .6*adr) & (lag(rng, 1) <= .6*adr1) & (lag(rng, 2) <= .6*lag(adr, 2)) & \
                (c <= span_max(h, 3, 1)*1.02)
        out['D1a'] = base & d1a & (~extended | (flag3 if flag else False))
        out['D1b'] = base & ~extended & (o >= 1.02*h1) & (c > o) & (upper >= .5) & (ext <= .15)
        out['D1c'] = base & ~extended & (c >= span_max(c, 19, 0)) & (r10 <= .2) & (ext <= .12)
        out['EP'] = scope_prev & (o/h1-1 >= np.maximum(.05, .5*adr1)) & (c >= .95*span_max(h, 20, 1)) & \
            (upper >= .5) & (adr1 >= .05)
        trend = (c > e21) & (e21 > e50) & (e9 >= e21) & (e21 > lag(e21, 5))
        fresh = span_max(h, 5, 0) >= span_max(h, 20, 0)
        dd10 = 1-l/span_max(h, 10, 1)
        touch = ((l <= e9) & (c > e9)) | ((l <= e21) & (c > e21)) | ((upper <= 1/3) & (c > e21))
        out['PB'] = wl & trend & fresh & (dd10 >= .03) & (dd10 <= .15) & (l >= span_min(l, 3, 1)) & (c > o) & touch
    out['wl'] = wl
    return out


def comove(c, t, js, peers, r10):
    """Per name in js: peers (watch list) whose last 20 daily returns correlate >= 0.6 with it and are up >= 10% in 10 days."""
    if t < 21 or not len(peers):
        return np.zeros(len(js))
    with np.errstate(invalid='ignore', divide='ignore'):
        ret = np.diff(c[t-20:t+1], axis=0)/c[t-20:t]
    strong = peers[np.isfinite(ret[:, peers]).all(0) & (r10[peers] >= .1)]
    out = []
    for j in js:
        x = ret[:, j]
        if not np.isfinite(x).all() or not len(strong):
            out.append(0)
            continue
        cor = [np.corrcoef(x, ret[:, k])[0, 1] for k in strong if k != j]
        out.append(int(np.sum(np.array(cor) >= .6)))
    return np.array(out, float)


def book(A, sig, spec, score_prev):
    """At most PER_NIGHT entries a close, ordered by setup then the candidate's key; fill at that close, E6c stop."""
    c, l = A['close'], A['low']
    entries = [[] for _ in A['days']]
    codes = list(map(str, A['codes']))
    r10 = c/lag(c, 10)-1 if spec['order'] == 'comove' else None
    for t in range(1, len(entries)):
        prio = {}
        for name in spec['channels']:
            for j in np.flatnonzero(sig[name][t]):
                prio[j] = min(prio.get(j, 9), PRIORITY[name])
        if not prio:
            continue
        js = np.array(sorted(prio))
        if spec['order'] == 'profile':
            key = np.nan_to_num(score_prev[t, js], nan=-1e9)
        elif spec['order'] == 'comove':
            key = comove(c, t, js, np.flatnonzero(sig['wl'][t]), r10[t])*1e12 + np.nan_to_num(A['to20'][t-1, js])
        else:
            key = np.nan_to_num(A['to20'][t-1, js])
        order = sorted(range(len(js)), key=lambda k: (prio[js[k]], -key[k], codes[js[k]]))
        for k in order[:PER_NIGHT]:
            j = int(js[k])
            stop = M.capped_stop(float(c[t, j]), l[t, j], A['adr'][t-1, j])
            if stop is None:
                continue
            name = next(n for n in spec['channels'] if sig[n][t, j] and PRIORITY[n] == prio[j])
            entries[t].append(((prio[j], len(entries[t]), codes[j]), j, 1, float(c[t, j]), stop, 'e12_'+name, None))
    return entries


def pools(A, R):
    """Pool masks by night (strict = IE47's, wide = H4 plus two of the other three) lagged one session, the
    previous night's liquidity scope, and the previous night's IE47 profile score."""
    shape = A['close'].shape
    strict, wide, scope, score = (np.zeros(shape, bool), np.zeros(shape, bool), np.zeros(shape, bool),
                                  np.full(shape, np.nan, np.float32))
    for k, t in enumerate(R['night_indices']):
        ix = R['scopes'][k]
        if t+1 >= shape[0] or not len(ix):
            continue
        passed, pct = M.filter_night(R['raw'][k])
        ok = np.stack([np.where(np.isfinite(pct[:, q]), pct[:, q] >= cut, q == 0) for q, (_, cut) in enumerate(M.GATES)], 1)
        strict[t+1, ix[passed]] = True
        wide[t+1, ix[ok[:, 0] & (ok[:, 1:].sum(1) >= 2)]] = True
        scope[t+1, ix] = True
    rows = np.flatnonzero(R['row_t']+1 < shape[0])
    score[R['row_t'][rows]+1, R['row_j'][rows]] = R['scores'][rows]
    return dict(strict=strict, wide=wide), scope, score


def his_longs(span):
    rows = []
    for h in csv.DictReader(open(M.STUDY.ledger, encoding='utf-8')):
        day = h['entry_date'] or h['window_lo']
        if h['side'] == 'long' and span[0] <= day <= span[1]:
            rows.append(dict(id=h['id'], code='US.'+h['ticker'], day=day, setup=h['setup']))
    return rows


def his_hits(A, trades, sig, spec, span):
    """His longs: bought within [d-3, d+1], that buy closed in profit, any setup fired within [d-2, d+1]."""
    days, codes = list(map(str, A['days'])), {str(c): j for j, c in enumerate(A['codes'])}
    di = {d: i for i, d in enumerate(days)}
    ours = {}
    for t in G.closed(trades):
        ours.setdefault(t['code'], []).append(t)
    out = []
    for h in his_longs(span):
        D = bisect_left(days, h['day'])
        j = codes.get(h['code'])
        got = [t for t in ours.get(h['code'], ()) if -3 <= di[t['entry']]-D <= 1]
        fired = j is not None and sig is not None and any(sig[n][max(D-2, 0):D+2, j].any() for n in spec['channels'])
        out.append(dict(h, bought=bool(got), won=bool(got and got[0]['ret_invested'] > 0),
                        rel=di[got[0]['entry']]-D if got else None, ret=got[0]['ret_invested'] if got else None,
                        kind=got[0]['kind'] if got else None, fired=bool(fired)))
    by = {}
    for r in out:
        y = by.setdefault(r['day'][:4], dict(n=0, bought=0, won=0, fired=0))
        y['n'] += 1
        for k in ('bought', 'won', 'fired'):
            y[k] += r[k]
    return dict(n=len(out), bought=sum(r['bought'] for r in out), won=sum(r['won'] for r in out),
                fired=sum(r['fired'] for r in out), by_year=by, rows=out)


def evaluate(st, A, pool, name, entries, rules, span, sig=None, spec=None):
    stats, trades, _, _ = E.summary(st, A, entries, rules, pool, span)
    E8.invested(st, stats, trades)
    track = {}
    Y.simulate(st.px(A), st.ema_inputs(A, pool, rules), rules, entries, *span, track=track)
    stats['mechanism'] = X.mechanism(A, entries, [], trades, track, None, {})
    stats['his'] = his_hits(A, trades, sig, spec, span)
    d0, d1 = np.searchsorted(A['days'], span[0]), np.searchsorted(A['days'], span[1], side='right')
    per = np.array([len(r) for r in entries[d0:d1]])
    stats['per_night'] = dict(mean=float(per.mean()), median=float(np.median(per)), p90=float(np.percentile(per, 90)),
                              zero_share=float(np.mean(per == 0)))
    if sig is not None:
        stats['watch_list'] = dict(median=float(np.median(sig['wl'][d0:d1].sum(1))))
        stats['fires'] = {n: int(sig[n][d0:d1].sum()) for n in spec['channels']}
    write(WORK/f'{name}_{span[0][:4]}_trades.json', trades)
    hs = stats['his']
    progress(f"{name}: {span[0][:4]} total={stats['total']:+.4f} closed={stats['trades']} win={stats['win']:.3f} "
             f"his won/bought/fired/n={hs['won']}/{hs['bought']}/{hs['fired']}/{hs['n']} w20={stats['mechanism']['winners20']}")
    return stats


def setup():
    st = M.IE47Study()
    st.progress = progress
    A = st.arrays('us')
    R = st.selected(A)
    cfg = dict(candidate='E8c', profile_sha256=SP.sha(M.PROFILE), frozen_inputs_sha256=M.inputs_digest(R['sources']))
    ref_book, ref_rules, _, pool = st.build(A, cfg, {})
    k2 = X.rule_layers(ref_rules, ('AS', 'X1'))
    rules = replace(k2, max_new_long=PER_NIGHT, no_rebuy_day=True)
    masks, scope, score = pools(A, R)
    return st, A, pool, ref_book, k2, rules, masks, scope, score


def candidate(A, name, masks, scope, score):
    """Setups only on names ever in the liquidity scope (memory), expanded back to the full panel."""
    spec = SPEC[name]
    cols = np.flatnonzero(scope.any(0))
    P = {k: A[k][:, cols] for k in ('open', 'high', 'low', 'close', 'adr')}
    small = setups(P, masks[spec['pool']][:, cols], scope[:, cols], flag=spec.get('flag', False))
    sig = {}
    for k, v in small.items():
        sig[k] = np.zeros(A['close'].shape, bool)
        sig[k][:, cols] = v
    del small, P
    return spec, sig, book(A, sig, spec, score)


def train():
    if RESULT.exists() or SELECTED.exists():
        raise ValueError('E12 training already recorded; do not rerun or select again')
    write(WORK/'train_started.json', fingerprints())
    st, A, pool, ref_book, k2, rules, masks, scope, score = setup()
    out = dict(preregistered_sha256=SP.sha(PREREG), source_sha256=fingerprints(), span=list(E.TRAIN), runs={})
    out['runs']['K2'] = evaluate(st, A, pool, 'K2', ref_book, k2, E.TRAIN)
    for name in CANDIDATES:
        spec, sig, entries = candidate(A, name, masks, scope, score)
        out['runs'][name] = evaluate(st, A, pool, name, entries, rules, E.TRAIN, sig, spec)
        write(RESULT.with_suffix('.partial.json'), out)
        del sig, entries
    ok = [k for k in CANDIDATES if out['runs'][k]['total'] > -.2]
    chosen = None
    if ok:
        best = max(out['runs'][k]['his']['won'] for k in ok)
        near = [k for k in ok if best-out['runs'][k]['his']['won'] <= 1]
        chosen = max(near, key=lambda k: (out['runs'][k]['total'], -CANDIDATES.index(k)))
    out.update(eligible=ok, chosen=chosen)
    write(RESULT, out)
    with SELECTED.open('x', encoding='utf-8') as stream:
        json.dump(dict(chosen=chosen, eligible=ok, preregistered_sha256=SP.sha(PREREG), source_sha256=fingerprints()),
                  stream, ensure_ascii=False, indent=1)
    progress(f'eligible={ok}; selected {chosen} on 2024-25 only; 2026 unmeasured')


def validate():
    if VALIDATION.exists():
        raise ValueError('E12 validation already recorded')
    selected = json.loads(SELECTED.read_text())
    if selected['preregistered_sha256'] != SP.sha(PREREG) or selected['source_sha256'] != fingerprints():
        raise ValueError('E12 preregistration or source changed after selection')
    if selected['chosen'] is None:
        raise ValueError('E12 selected nothing; 2026 is not measured')
    with (WORK/'validation_started.json').open('x', encoding='utf-8') as stream:
        json.dump(dict(selected_sha256=SP.sha(SELECTED)), stream)
    st, A, pool, ref_book, k2, rules, masks, scope, score = setup()
    name = selected['chosen']
    spec, sig, entries = candidate(A, name, masks, scope, score)
    held = evaluate(st, A, pool, name, entries, rules, E.VALIDATE, sig, spec)
    full = evaluate(st, A, pool, name+'_full', entries, rules, panels.WINDOW, sig, spec)
    k2_held = evaluate(st, A, pool, 'K2', ref_book, k2, E.VALIDATE)
    write(VALIDATION, dict(chosen=name, validate=held, full=full, k2_validate=k2_held, preregistered_sha256=SP.sha(PREREG),
                           scope='one chosen E12 candidate; 2026 already used by IE47 and E3-E11'))
    progress(f"{name} 2026={held['total']:+.4f}; full={full['total']:+.4f}")


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('stage', choices=('train', 'validate'))
    stage = parser.parse_args().stage
    WORK.mkdir(exist_ok=True)
    resource.setrlimit(resource.RLIMIT_AS, (2_000_000_000, 2_000_000_000))
    offline()
    original = TP.build
    def existing_load(market, mode=None, version=None, upto=None, **kwargs):
        return original(TD.dataset(market, mode, version), upto=upto, write_cache=False)
    def read_only_build(ds, upto=None, cache=True, write_cache=True):
        return original(ds, upto=upto, cache=cache, write_cache=False)
    with ExitStack() as stack:
        stack.enter_context(patch.object(TD, 'load', existing_load))
        stack.enter_context(patch.object(TP, 'build', read_only_build))
        {'train': train, 'validate': validate}[stage]()
