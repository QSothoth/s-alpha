"""Offline E20: causal re-nominations of previously known IE47 names."""
from __future__ import annotations

import argparse
from collections import Counter
import gc
import hashlib
import json
from pathlib import Path
import resource
from unittest.mock import patch

import numpy as np

from . import e19_research as E19

E16, E15 = E19.E16, E19.E15
M = E16.M
WORK = M.STUDY.root/'reports/e20_work'
PREREG = M.STUDY.root/'notes/PREREG_E20_CN.md'
END = E15.E.TRAIN[1]
TYPES = ('upgrade', 'potent', 'leader', 'theme')
SPECS = {'A1': (('upgrade',), False, False),
         'A2': (('potent',), False, False),
         'A3': (('leader',), False, False),
         'A4': (TYPES[:3], False, True),
         'A5': (TYPES[:3], True, True)}
read, write = E19.read, E15.write


def signals(A):
    for span in (9, 21, 50):
        key = f'e{span}'
        if key not in A:
            A[key] = E16.ema(A['close'], span)


def theme_names(close, t, seeds, known):
    """A group is a triangle with all three 60-return correlations >= .6.

    Two event seeds nominate a third, previously known name. Only complete
    60-session histories count. Scratch correlations have at most 64 rows.
    """
    seeds = np.asarray(sorted(seeds), int)
    if t < 60 or len(seeds) < 2:
        return set()
    with np.errstate(all='ignore'):
        returns = close[t-59:t+1].astype(float)/close[t-60:t].astype(float)-1
    valid = np.isfinite(returns).all(0)
    returns[:, ~valid] = 0
    returns -= returns.mean(0)
    norm = np.sqrt((returns*returns).sum(0))
    valid &= norm > 0
    returns /= np.where(valid, norm, 1)
    seeds = seeds[valid[seeds]]
    if len(seeds) < 2:
        return set()
    seed_vectors = returns[:, seeds]
    candidates = np.asarray(sorted(set(np.flatnonzero(known & valid))-set(seeds)), int)
    nominated = set()
    for start in range(0, len(candidates), 64):
        ix = candidates[start:start+64]
        corr = returns[:, ix].T @ seed_vectors
        hit = np.zeros(len(ix), bool)
        for k in range(len(seeds)-1):
            peers = np.flatnonzero(seed_vectors[:, k] @ seed_vectors[:, k+1:] >= .6)+k+1
            if len(peers):
                hit |= (corr[:, k] >= .6) & (corr[:, peers] >= .6).any(1)
        nominated.update(map(int, ix[hit]))
    return nominated


def event_rows(A, R, end=END):
    """Market scope and ranks use tonight only; known means an earlier IE47 pick.

    The leader's raw upper bound uses ten sessions since the last IE47 pick.
    Actual re-nominations also enforce ten since the last emitted nomination.
    """
    signals(A)
    codes, days = list(map(str, A['codes'])), list(map(str, A['days']))
    ci = {c: j for j, c in enumerate(codes)}
    known = np.zeros(len(codes), bool)
    last = np.full(len(codes), -10000, int)
    c = A['close']
    stacked = (A['e9'] > A['e21']) & (A['e21'] > A['e50'])
    result = {}
    for t, scope in zip(R['night_indices'], R['scopes']):
        if days[t] > end:
            break
        base = {ci[code] for code in R['picks'][days[t]]}
        finite = np.isfinite(c[t]) & (c[t] > 0)
        available = known & finite
        upgrade = set(np.flatnonzero(available & stacked[t] & ~stacked[t-1])) if t else set()
        with np.errstate(all='ignore'):
            gain = c[t].astype(float)/c[t-1].astype(float)-1 if t else np.full(len(codes), np.nan)
            month = c[t].astype(float)/c[t-21].astype(float)-1 if t >= 21 else np.full(len(codes), np.nan)
        ix = scope[np.isfinite(gain[scope])]
        order = ix[np.lexsort((np.asarray(codes)[ix], -gain[ix]))][:10]
        potent = set(map(int, order[available[order]]))
        ix = scope[np.isfinite(month[scope])]
        order = ix[np.lexsort((np.asarray(codes)[ix], -month[ix]))][:int(np.ceil(len(ix)*.1))]
        leader = set(map(int, order[available[order] & (t-last[order] >= 10)]))
        seeds = upgrade | potent | leader
        theme = theme_names(c, t, seeds, available)
        events = dict(upgrade=upgrade-base, potent=potent-base, leader=leader-base, theme=theme-base)
        if R['regime'][t] < 0:
            events = {kind: set() for kind in TYPES}
        result[days[t]] = {kind: [codes[j] for j in sorted(ix)] for kind, ix in events.items()}
        known[list(base)] = True
        last[list(base)] = t
        if len(result) % 100 == 0:
            print(f'E20 event nights {len(result)}', flush=True)
    return result


def nominations(A, R, events, kinds, cap=None, source_priority=False):
    """Base IE47 order stays intact. Extras rank by 21-session gain then code.

    A combined scan can first prioritize upgrades, then potent, then leaders.
    """
    codes = list(map(str, A['codes']))
    ci = {c: j for j, c in enumerate(codes)}
    di = {str(d): t for t, d in enumerate(A['days'])}
    last = {}
    merged, extras = {}, {}
    for day, row in events.items():
        t = di[day]
        base = list(R['picks'][day])
        names = set().union(*(set(row[k]) for k in kinds))-set(base)
        names = [code for code in names if any(code in row[k] for k in kinds if k != 'leader')
                 or t-last.get(code, -10000) >= 10]
        def priority(code):
            j = ci[code]
            old = A['close'][t-21, j] if t >= 21 else np.nan
            gain = float(A['close'][t, j])/float(old)-1 if np.isfinite(old) and old > 0 else -np.inf
            tier = min(TYPES.index(k) for k in kinds if code in row[k]) if source_priority else 0
            return tier, -gain, code
        names = sorted(names, key=priority)
        if cap is not None:
            names = names[:cap]
        merged[day], extras[day] = base+names, names
        for code in base+names:
            last[code] = t
    return merged, extras


def watch_book(A, picks, pullback=False):
    """Five sessions, first strict close break or 9/21 EMA reclaim consumes the watch.

    Same capped C062 probe stop, rank and born metadata as IE47.entry_book.
    """
    codes, days = list(map(str, A['codes'])), list(map(str, A['days']))
    ci = {code: j for j, code in enumerate(codes)}
    book, watching, events = [[] for _ in days], {}, []
    for d in range(1, len(days)):
        for rank, code in enumerate(picks.get(days[d-1], ())):
            watching[ci[code]] = d-1, rank
        for j, (born, rank) in list(watching.items()):
            if d > born+5:
                del watching[j]
                continue
            o, h, l, c = (A[k][d, j] for k in ('open', 'high', 'low', 'close'))
            prev_h, prev_l, adr = A['high'][d-1, j], A['low'][d-1, j], A['adr'][d-1, j]
            if not np.isfinite((o, h, l, c, prev_h, prev_l, adr)).all() or min(o, h, l, c, prev_h, prev_l, adr) <= 0:
                continue
            reclaim = pullback and A['e9'][d, j] > A['e21'][d, j] and any(
                l <= A[k][d, j] < c for k in ('e9', 'e21'))
            if c <= prev_h and not reclaim:
                continue
            del watching[j]
            stop = M.capped_stop(float(c), float(l), float(adr))
            events.append(dict(code=codes[j], day=days[d], observed=days[born], valid=stop is not None))
            if stop is not None:
                kind = M.CLOSE_KIND if c > prev_h else M.PB_KIND
                book[d].append(((rank, born, codes[j]), j, 1, float(c), stop, kind, None))
    return book, events


def cost(extras):
    counts = [len(v) for d, v in extras.items() if E15.E.TRAIN[0] <= d <= END]
    return dict(nights=len(counts), total=sum(counts), mean=float(np.mean(counts)),
                median=float(np.median(counts)), p95=float(np.percentile(counts, 95)),
                maximum=max(counts), active=sum(n > 0 for n in counts))


def reach_records(A, extras, book):
    days = list(map(str, A['days']))
    signals_by_code = {}
    for d, row in enumerate(book):
        for entry in row:
            signals_by_code.setdefault(str(A['codes'][entry[1]]), []).append(
                dict(day=days[d], observed=days[entry[0][1]]))
    missing = {r['id'] for r in read(E19.WORK/'funnel.json')['R2']['records']
               if r['category'] == 'named_outside_window'}
    records = []
    for h in E19.ledger():
        code, lo, hi = 'US.'+h['ticker'], h['window_lo'], h['window_hi']
        start = max(0, int(np.searchsorted(days, lo))-4)
        nights = [d for d, row in extras.items() if days[start] <= d <= hi and code in row]
        triggers = [r for r in signals_by_code.get(code, ()) if lo <= r['day'] <= hi]
        from_renames = [r for r in triggers if r['observed'] in nights]
        records.append(dict(id=h['id'], code=code, window=[lo, hi], nomination_lo=days[start],
                            nights=nights, triggers=triggers, from_renames=from_renames,
                            r2_missing=h['id'] in missing))
    return dict(named=sum(bool(r['nights']) for r in records),
                triggered=sum(bool(r['triggers']) for r in records),
                named_and_triggered=sum(bool(r['from_renames']) for r in records),
                missing_named=sum(r['r2_missing'] and bool(r['nights']) for r in records),
                missing_triggered=sum(r['r2_missing'] and bool(r['triggers']) for r in records),
                missing_named_and_triggered=sum(r['r2_missing'] and bool(r['from_renames'])
                                               for r in records), records=records)


def reach():
    with (WORK/'reach_started.json').open('x') as stream:
        json.dump(dict(memory=E15.B.memory(), source_sha256=E19.sha(Path(__file__))), stream, indent=1)
    st, A, cfg, original, R = E19.prepare(upto=END)
    reference, _ = watch_book(A, R['picks'])
    assert reference == original[0], 'E20 close-break watches differ from the C062 base'
    events = event_rows(A, R)
    write(WORK/'events.json', events)
    write(WORK/'reach_inputs.json', dict(panel_digest=A['digest'], sources=R['sources'], picks=R['picks']))
    output = {}
    for kinds in ((k,) for k in TYPES):
        for cap in (None, 3):
            picks, extras = nominations(A, R, events, kinds, cap)
            book, _ = watch_book(A, extras)
            combined, _ = watch_book(A, picks)
            output[kinds[0]+('_cap3' if cap else '_raw')] = dict(
                cost=cost(extras), isolated=reach_records(A, extras, book),
                combined=reach_records(A, extras, combined))
    for cap in (None, 3):
        picks, extras = nominations(A, R, events, TYPES, cap)
        for pullback in (False, True):
            book, _ = watch_book(A, picks, pullback)
            output['union'+('_cap3' if cap else '_raw')+('_pullback' if pullback else '')] = dict(
                cost=cost(extras), combined=reach_records(A, extras, book))
    base, empty = R['picks'], {d: [] for d in events}
    for pb in (False, True):
        book, _ = watch_book(A, base, pb)
        output['base'+('_pullback' if pb else '')] = dict(combined=reach_records(A, empty, book))
    write(WORK/'reach.json', dict(results=output, memory=E15.B.memory(), account_measured=False))
    for name, result in output.items():
        x = result['combined']
        print(name, 'named/triggered/missing-triggered', x['named'], x['triggered'], x['missing_triggered'],
              'extra/night', result.get('cost', {}).get('mean', 0), flush=True)
    write(WORK/'reach_complete.json', dict(reach_sha256=E19.sha(WORK/'reach.json'), memory=E15.B.memory()))


def provenance():
    frozen = read(WORK/'preregistered.json')
    assert E19.sha(PREREG) == frozen['preregistered_sha256'], 'E20 preregistration changed'
    for name, digest in frozen['reach_sha256'].items():
        assert E19.sha(WORK/name) == digest, 'E20 reach results changed: '+name
    paths = [PREREG, Path(__file__), Path(__file__).parent/'tests/test_ie47_e20.py', M.PROFILE,
             WORK/'events.json', WORK/'reach_inputs.json', WORK/'preregistered.json']
    return dict(E15.P.fingerprints(), **E19.provenance(),
                **{str(p.relative_to(E16.ROOT)): E19.sha(p) for p in paths})


def once(stage):
    with (WORK/f'{stage}_started.json').open('x') as stream:
        json.dump(dict(source_sha256=provenance(), memory=E15.B.memory()), stream, indent=1)


def prepare(upto=None, end=END):
    st, A, cfg, original, R = E19.prepare(upto)
    signals(A)
    cached = read(WORK/'reach_inputs.json')['picks']
    expected = {d: v for d, v in cached.items() if d <= min(end, END)}
    actual = {d: v for d, v in R['picks'].items() if d <= min(end, END)}
    assert expected == actual, 'E20 IE47 past nominations changed'
    A['_e20_events'] = read(WORK/'events.json') if end == END and upto in (None, END) else event_rows(A, R, end)
    return st, A, cfg, original, R


def candidate_picks(A, R, name):
    cache = A.setdefault('_e20_nominations', {})
    if name not in cache:
        kinds, _, priority = SPECS[name]
        cache[name] = nominations(A, R, A['_e20_events'], kinds, 3, priority)
    return cache[name]


def configure(A, original, R, name):
    if name in ('BASE', 'S1'):
        book, info = (original[0], {}) if name == 'BASE' else E16.arm_book(A, R, 'S1', original[0])
        rules = E16.arm_rules(original[1], name)
    else:
        candidate, execution = name.split('_')
        picks, extras = candidate_picks(A, R, candidate)
        book, _ = watch_book(A, picks, SPECS[candidate][1])
        info = dict(extra_cost=cost(extras))
        rules = original[1]
        if execution == 'S1':
            book, sizes, retries = E16.overlay_book(A, book, picks, A['e21'])
            rules = E16.arm_rules(rules, 'S1')
            info.update(width_median=float(np.median(sizes)), width_max=max(sizes), retries=retries)
        elif execution != 'BASE':
            raise ValueError('unknown E20 execution: '+execution)
    mask = np.zeros_like(original[2])
    for d, row in enumerate(book):
        for e in row:
            mask[d, e[1]] = True
    A['_e14_base'] = book, rules, mask, original[3]
    A.pop('_e15_books', None)
    return book, info


def funnel(A, R, picks, trades, attempts):
    days = list(map(str, A['days']))
    ci = {str(c): j for j, c in enumerate(A['codes'])}
    records = []
    for h in E19.ledger():
        code, lo, hi = 'US.'+h['ticker'], h['window_lo'], h['window_hi']
        j = ci.get(code)
        stop = int(np.searchsorted(A['days'], hi, side='right'))
        pool = [days[i] for i in np.flatnonzero(R['pool'][:stop, j])] if j is not None else []
        named = [d for d, row in picks.items() if d <= hi and code in row]
        triggered = [a for a in attempts if a['code'] == code and lo <= a['day'] <= hi]
        matched = [t for t in trades if t['code'] == code and lo <= t['entry'] <= hi]
        won = any(t['pnl'] > 0 and t['why'] != 'end' for t in matched)
        category = ('bought_won' if won else 'bought_lost' if matched else 'triggered_blocked' if triggered
                    else 'named_outside_window' if named else 'pool_not_named' if pool else 'not_in_pool')
        records.append(dict(id=h['id'], code=code, entry=h['entry_date'], window=[lo, hi], precision=h['precision'],
            category=category, pool_nights=pool, pick_nights=named, matches=matched, triggers=triggered,
            window_pool_nights=[d for d in pool if lo <= d <= hi],
            window_pick_nights=[d for d in named if lo <= d <= hi],
            rejection_counts=dict(Counter(a['reason'] for a in triggered if a['reason'] != 'filled'))))
    assert len(records) == 43
    return dict(counts=dict(Counter(r['category'] for r in records)), records=records,
                blocked_reasons=dict(Counter(a['reason'] for r in records if r['category'] == 'triggered_blocked'
                                             for a in r['triggers'])))


def evaluate(st, A, cfg, original, R, name, span):
    with patch.object(E19, 'WORK', WORK), patch.object(E19, 'configure', configure):
        result = E19.evaluate(st, A, cfg, original, R, name, span)
        trades = E19.rows(name, span)
    directory = WORK/f'{name}_{span}'
    attempts, evictions = read(directory/'attempts.json'), read(directory/'make_room.json')
    evicted = {(t['code'], t['entry']): t for t in trades if t['why'] == 'make_room'}
    ci, di = {str(c): j for j, c in enumerate(A['codes'])}, {str(d): t for t, d in enumerate(A['days'])}
    assert len(evictions) == len(evicted)
    for event in evictions:
        t = evicted[event['evicted'], event['entry']]
        assert t['kind'] == E16.RETRY_KIND and not t['confirmed'] and not event['confirmed']
        assert t['executions'][-1]['price'] == float(A['close'][di[t['exit']], ci[t['code']]])
        incoming = next(a for a in attempts if a['code'] == event['incoming'] and a['day'] == t['exit']
                        and a['kind'] == event['incoming_kind'])
        assert incoming['reason'] == 'filled'
    write(directory/'room_checks.json', dict(ok=True, evictions=len(evictions)))
    if span == 'train':
        picks = R['picks'] if name in ('BASE', 'S1') else candidate_picks(A, R, name.split('_')[0])[0]
        write(WORK/f'{name}_{span}/funnel.json', funnel(A, R, picks, trades, attempts))
        if name not in ('BASE', 'S1'):
            candidate = name.split('_')[0]
            merged, extras = candidate_picks(A, R, candidate)
            value = dict(picks=merged, extras=extras, cost=cost(extras))
            path = WORK/f'{candidate}_nominations.json'
            if path.exists():
                assert read(path) == value, 'paired executions must use identical nominations'
            else:
                write(path, value)
    return result


def default_checks():
    summary, prior = read(WORK/'summary.json'), read(E19.WORK/'summary.json')
    checks = {}
    for name in ('BASE', 'S1'):
        details = dict(summary=summary[name+'_train'] == prior[name+'_train'])
        for suffix in ('trades', 'curve', 'legs', 'stats'):
            filename = f'{name}_train/C062_2024_{suffix}.json'
            details[suffix] = read(WORK/filename) == read(E19.WORK/filename)
        checks[name] = details
    write(WORK/'defaults.json', checks)
    assert all(all(v.values()) for v in checks.values()), checks
    return checks


def select(summary):
    paired = dict(BASE_train=summary['BASE_train'])
    paired.update({n+'_train': summary[n+'_S1_train'] for n in SPECS})
    with patch.object(E19.D, 'ARMS', tuple(SPECS)):
        return E19.D.select(paired)


def train():
    once('train')
    st, A, cfg, original, R = prepare()
    write(WORK/'inputs.json', dict(cfg=cfg, picks=R['picks'], memory=E15.B.memory()))
    for name in ('BASE', 'S1'):
        evaluate(st, A, cfg, original, R, name, 'train')
    default_checks()
    for candidate in SPECS:
        for execution in ('S1', 'BASE'):
            evaluate(st, A, cfg, original, R, candidate+'_'+execution, 'train')
    assess()
    write(WORK/'train_complete.json', dict(source_sha256=provenance(), memory=E15.B.memory(),
                                          summary_sha256=E19.sha(WORK/'summary.json')))


def assess():
    summary = read(WORK/'summary.json')
    default_checks()
    eligible, chosen = select(summary)
    output = dict(eligible=eligible, chosen=chosen, runs={})
    his = E19.ledger()
    for name in ('BASE', 'S1', *(n+'_'+x for n in SPECS for x in ('S1', 'BASE'))):
        directory = WORK/f'{name}_train'
        trades = read(directory/'C062_2024_trades.json')
        stats = read(directory/'C062_2024_stats.json')
        days = read(directory/'C062_2024_curve.json')['days']
        daily = E19.daily_positions(trades, days)
        maximum = lambda field: max(v[field] for v in daily.values())
        caps = dict(max_retry=max(maximum('retry_at_open'), maximum('retry_at_close')),
                    max_total=max(maximum('at_open'), maximum('at_close')),
                    max_new=max(v['new_base']+v['new_retry'] for v in daily.values()))
        assert caps['max_total'] <= 11 and caps['max_new'] <= 4
        assert caps['max_retry'] <= (2 if name == 'S1' or name.endswith('_S1') else 0)
        attempts = read(directory/'attempts.json')
        evictions = read(directory/'make_room.json')
        evicted = [t for t in trades if t['why'] == 'make_room']
        assert len(evictions) == len(evicted)
        assert all(t['kind'] == E16.RETRY_KIND and not t['confirmed'] for t in evicted)
        for event in evictions:
            t = next(t for t in evicted if t['code'] == event['evicted'] and t['entry'] == event['entry'])
            incoming = next(a for a in attempts if a['code'] == event['incoming'] and a['day'] == t['exit']
                            and a['kind'] == event['incoming_kind'])
            assert incoming['reason'] == 'filled'
        assert read(directory/'room_checks.json')['ok']
        closed = sorted((t['pnl'] for t in trades if t['why'] != 'end'), reverse=True)
        annual = {y: dict(**E19.D.annual(trades, y), his=E19.D.hits(trades, his, y),
                          midpoint=stats['legs']['his'][y]['midpoint']) for y in ('2024', '2025')}
        output['runs'][name] = dict(annual=annual, caps=caps, pnl=sum(closed), pnl_ex_top1=sum(closed[1:]),
            pnl_ex_top3=sum(closed[3:]), r15=sum(t['r'] >= 15 for t in trades if t['why'] != 'end'),
            funnel=read(directory/'funnel.json'), evicted=len(evicted), daily=daily)
    write(WORK/'diagnostics.json', output)
    selection = dict(eligible=eligible, chosen=chosen, source_sha256=provenance(),
                     train_sha256=training_digest())
    path = WORK/'selection.json'
    if path.exists():
        assert read(path) == selection, 'E20 selection cannot change'
    else:
        write(path, selection)


def training_digest():
    train = {k: v for k, v in read(WORK/'summary.json').items() if k.endswith('_train')}
    return hashlib.sha256(json.dumps(train, sort_keys=True).encode()).hexdigest()


def check_selection():
    selected = read(WORK/'selection.json')
    assert selected['source_sha256'] == provenance(), 'E20 source or inputs changed after selection'
    assert selected['train_sha256'] == training_digest(), 'E20 training results changed'
    return selected


def truncate():
    selected = check_selection()
    if selected['chosen'] is None:
        raise ValueError('No eligible E20 candidate: do not run truncation or validation')
    once('truncate')
    cut, reference, comparisons = E19.D.CUT, {}, {}
    for label, upto in (('full', None), ('cut', cut)):
        st, A, cfg, original, R = prepare(upto, cut if upto else END)
        k = int(np.searchsorted(A['days'], cut, side='right'))
        for execution in ('S1', 'BASE'):
            name = selected['chosen']+'_'+execution
            configure(A, original, R, name)
            book, rules, _, pool = st.build(A, dict(cfg, candidate='C062'))
            entries = [[(list(e[0]), str(A['codes'][e[1]]), *e[2:]) for e in row] for row in book[:k]]
            trades = E15.Y.simulate(st.px(A), st.ema_inputs(A, pool, rules), rules, book,
                                   E15.E.TRAIN[0], cut if upto else END, audit=True)[2]
            merged, extra = candidate_picks(A, R, selected['chosen'])
            value = dict(entries=entries, events=E15.B.execution_events(trades, cut),
                         picks={d: v for d, v in merged.items() if d <= cut},
                         extras={d: v for d, v in extra.items() if d <= cut})
            write(WORK/f'truncation_{name}_{label}.json', value)
            if label == 'full':
                reference[execution] = value
            else:
                comparisons[execution] = {field: reference[execution][field] == value[field] for field in value}
        del st, A, original, R, book, rules, pool, trades, entries, merged, extra
        gc.collect()
    ok = all(all(row.values()) for row in comparisons.values())
    write(WORK/'truncation.json', dict(ok=ok, chosen=selected['chosen'], cut=cut, comparisons=comparisons))
    assert ok, comparisons


def validate():
    selected = check_selection()
    if selected['chosen'] is None or not read(WORK/'truncation.json')['ok']:
        raise ValueError('E20 validation requires an eligible candidate and passed prefix check')
    once('validation')
    st, A, cfg, original, R = prepare(end=E15.E.VALIDATE[1])
    for execution in ('S1', 'BASE'):
        for span in ('2026', 'full'):
            evaluate(st, A, cfg, original, R, selected['chosen']+'_'+execution, span)
    write(WORK/'validation_complete.json', dict(chosen=selected['chosen'], source_sha256=provenance(),
        independent_out_of_sample=False, memory=E15.B.memory()))


def checks():
    selected = check_selection()
    default_checks()
    before = read(WORK/'before.json')
    protected = {}
    report = 'studies/martin_luk/reports/E16_CN.md'
    for path, digest in before.items():
        protected[path] = E19.sha(E16.ROOT/path) == digest if path != report else (
            (E16.ROOT/path).read_bytes().startswith((WORK/'E16_before.md').read_bytes())
            and E19.sha(WORK/'E16_before.md') == digest)
    caps = {n: all(len(row) <= 3 for row in read(WORK/f'{n}_nominations.json')['extras'].values()) for n in SPECS}
    conditional = bool(selected['chosen']) or not any((WORK/n).exists() for n in (
        'truncate_started.json', 'validation_started.json', 'validation_complete.json'))
    value = dict(ok=all(protected.values()) and all(caps.values()) and conditional,
                 protected=protected, nomination_caps=caps, no_validation_if_ineligible=conditional)
    write(WORK/'checks.json', value)
    assert value['ok'], value


def summary():
    selected, runs = read(WORK/'selection.json'), read(WORK/'summary.json')
    print('E20 eligible:', ','.join(selected['eligible']) or 'none', '; selected:', selected['chosen'] or 'none')
    for name in ('BASE', 'S1', *(n+'_S1' for n in SPECS)):
        row = runs[name+'_train']
        print(f"{name}: 2024 {row['by_year']['2024']:+.2%}; 2025 {row['by_year']['2025']:+.2%}; "
              f"maxdd {row['maxdd']:.2%}; his midpoint {row['midpoint_his']}")
    print('2026/full:', 'measured' if (WORK/'validation_complete.json').exists() else 'not measured')


if __name__ == '__main__':
    from .e1_board_smoke import offline
    offline()
    WORK.mkdir(exist_ok=True)
    parser = argparse.ArgumentParser()
    parser.add_argument('stage', choices=('reach', 'train', 'assess', 'truncate', 'validate', 'checks', 'summary'))
    args = parser.parse_args()
    if args.stage in ('reach', 'train', 'truncate', 'validate'):
        resource.setrlimit(resource.RLIMIT_AS, (E15.LIMIT, E15.LIMIT))
    with E19.runtime():
        globals()[args.stage]()
