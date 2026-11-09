"""Frozen E19 candidates, offline evaluation and ledger diagnostics; never writes E16-E18 results."""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import ExitStack, contextmanager
import csv
from dataclasses import replace
from functools import partial
import hashlib
import json
from pathlib import Path
import resource
from unittest.mock import patch

import numpy as np

from . import e16_research as E16, e18_review as D, e15_research as E15


REFERENCE = E16.OUT
WORK = E16.M.STUDY.root/'reports/e19_work'
PREREG = E16.M.STUDY.root/'notes/PREREG_E19_CN.md'
RETRY = E16.RETRY_KIND
ROOM = {E16.M.CLOSE_KIND: RETRY, E16.M.PB_KIND: RETRY}
SPECS = {
    'S1': ('Q1', dict(max_open_by_kind={RETRY: 2}, make_room_kind=ROOM)),
    'S2': ('Q1', dict(max_open_by_kind={RETRY: 2}, make_room_kind=ROOM, make_room_confirmed=True)),
    'S3': ('Q4', dict(max_open_by_kind={RETRY: 2})),
    'S4': ('Q5', dict(max_open_by_kind={RETRY: 2})),
    'S5': ('Q1', dict(max_open_by_kind={RETRY: 1})),
}
read, write = D.read, D.write


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def provenance():
    paths = [PREREG, Path(__file__), Path(E16.__file__), Path(E15.__file__), Path(D.__file__),
             Path(E15.Y.__file__), REFERENCE/'summary.json']
    return {str(p.relative_to(E16.ROOT.parent)): sha(p) for p in paths}


def same_sources(measured):
    current = provenance()
    if measured == current:
        return True
    path = WORK/'trace_correction/compatibility.json'
    if not path.exists():
        return False
    proof = read(path)
    return (proof['ok'] and proof['measured_source_sha256'] == measured
            and proof['current_source_sha256'] == current)


def once(stage):
    with (WORK/f'{stage}_started.json').open('x', encoding='utf-8') as stream:
        json.dump(dict(source_sha256=provenance(), memory=E15.B.memory()), stream, indent=1)


@contextmanager
def runtime():
    from studies import trader_data as TD
    from studies.trader_data import panel as TP
    build = TP.build
    def load(market, mode=None, version=None, upto=None, **kw):
        return build(TD.dataset(market, mode, version), upto=upto, write_cache=False)
    def existing(ds, upto=None, cache=True, write_cache=True):
        return build(ds, upto=upto, cache=cache, write_cache=False)
    with ExitStack() as stack:
        stack.enter_context(patch.object(TD, 'load', load))
        stack.enter_context(patch.object(TP, 'build', existing))
        stack.enter_context(patch.object(E16, 'E18', dict(E16.E18, **SPECS)))
        audit = E15.execution_audit
        stack.enter_context(patch.object(E15, 'execution_audit', partial(audit, allow_add_exit=('make_room',))))
        for module in (E15.B, E15.P, E15):
            for name in ('baseline_check', 'update_checks'):
                if hasattr(module, name):
                    stack.enter_context(patch.object(module, name, lambda *a, **kw: None))
        yield


def prepare(upto=None):
    st, A, cfg = E15.setup(upto=upto)
    st.build(A, dict(cfg, candidate='K2'))
    return st, A, cfg, A['_e14_base'], st.selected(A)


def configure(A, original, R, name):
    if name == 'BASE':
        book, info = original[0], {}
    else:
        book, info = E16.arm_book(A, R, name, original[0])
    mask = np.zeros_like(original[2])
    for d, row in enumerate(book):
        for e in row:
            mask[d, e[1]] = True
    A['_e14_base'] = book, E16.arm_rules(original[1], name), mask, original[3]
    A.pop('_e15_books', None)
    return book, info


def ledger():
    with E16.M.STUDY.ledger.open(encoding='utf-8', newline='') as stream:
        return [r for r in csv.DictReader(stream) if r['side'] == 'long'
                and (r['entry_date'] or r['window_lo'])[:4] in ('2024', '2025')]


def rows(name, span='train'):
    root = REFERENCE if name == 'Q1' else WORK
    year = '2026' if span == '2026' else '2024'
    return read(root/f'{name}_{span}/C062_{year}_trades.json')


def evaluate(st, A, cfg, original, R, name, span_name):
    span = {'train': E15.E.TRAIN, '2026': E15.E.VALIDATE,
            'full': (E15.E.TRAIN[0], E15.E.VALIDATE[1])}[span_name]
    book, info = configure(A, original, R, name)
    directory = WORK/f'{name}_{span_name}'
    simulate = E15.Y.simulate
    def capture(*args, **kw):
        kw['track']['entry_attempts'] = []
        result = simulate(*args, **kw)
        write(directory/'attempts.json', kw['track']['entry_attempts'])
        write(directory/'make_room.json', kw['track'].get('make_room', []))
        return result
    with patch.object(E15.Y, 'simulate', capture):
        stats = E15.evaluate(st, A, cfg, 'C062', E15.B.main_legs(A, R['picks'], span), span, directory)
    result = dict(total=stats['total'], by_year=stats['by_year'], maxdd=stats['maxdd'], account=stats['account'],
                  midpoint_his=stats.get('midpoint_his'), entries=sum(map(len, book)), **info)
    if span_name == 'train':
        his = [('US.'+r['ticker'], r['entry_date']) for r in ledger() if r['entry_date'][:4] in ('2024', '2025')]
        master = read(E16.M.STUDY.root/'reports/e15_work/master_swap/train/C062_2024_trades.json')
        result.update(E16.extra(rows(name), master, his))
    summary = read(WORK/'summary.json') if (WORK/'summary.json').exists() else {}
    summary[f'{name}_{span_name}'] = result
    write(WORK/'summary.json', summary)
    print(name, span_name, {k: result[k] for k in ('by_year', 'maxdd', 'midpoint_his')}, flush=True)
    return result


def default_checks():
    old, new = read(REFERENCE/'summary.json'), read(WORK/'summary.json')
    checks = {}
    for name in ('BASE', 'R2'):
        details = dict(summary=new[name+'_train'] == old[name+'_train'])
        for suffix in ('trades', 'curve', 'legs', 'stats'):
            filename = f'{name}_train/C062_2024_{suffix}.json'
            details[suffix] = read(WORK/filename) == read(REFERENCE/filename)
        checks[name] = details
    write(WORK/'defaults.json', checks)
    assert all(all(v.values()) for v in checks.values()), checks
    return checks


def train():
    once('train')
    st, A, cfg, original, R = prepare()
    write(WORK/'inputs.json', dict(cfg=cfg, picks=R['picks']))
    for name in ('BASE', 'R2'):
        evaluate(st, A, cfg, original, R, name, 'train')
    default_checks()
    for name in SPECS:
        evaluate(st, A, cfg, original, R, name, 'train')
    funnel(A, R)
    counterfactuals(st, A, cfg, original, R)
    assess()
    write(WORK/'train_complete.json', dict(source_sha256=provenance(), memory=E15.B.memory()))


def select(summary):
    with patch.object(D, 'ARMS', tuple(SPECS)):
        return D.select(summary)


def daily_positions(trades, days):
    daily = D.daily_positions(trades, days)
    for day, value in daily.items():
        # A make_room exit occurs inside the entry loop, after the ordinary old-position exits.
        evicted = [t for t in trades if t['entry'] < day == t['exit'] and t['why'] == 'make_room']
        value['before_entries'] += len(evicted)
        value['retry_before_entries'] += sum(t['kind'] == RETRY for t in evicted)
    return daily


def assess():
    summary = read(WORK/'summary.json')
    default_checks()
    baseline, his = rows('BASE'), ledger()
    eligible, chosen = select(summary)
    output = dict(eligible=eligible, chosen=chosen, runs={})
    for name in ('BASE', 'Q1', 'R2', *SPECS):
        trades = rows(name)
        root = REFERENCE if name == 'Q1' else WORK
        daily = daily_positions(trades, read(root/f'{name}_train/C062_2024_curve.json')['days'])
        stats = read(root/f'{name}_train/C062_2024_stats.json')
        attempts = read(root/f'{name}_train/attempts.json') if name != 'Q1' else []
        lookup = {(a['code'], a['day'], a['kind']): a for a in attempts}
        keys = {(t['code'], t['entry']) for t in trades if t['kind'] != RETRY}
        annual = {}
        for year in ('2024', '2025'):
            missing = []
            for t in sorted(baseline, key=lambda t: -t['pnl']):
                day = t['entry']
                if not day.startswith(year) or (t['code'], day) in keys:
                    continue
                held = [r for r in trades if r['code'] == t['code'] and r['entry'] < day
                        and (r['exit'] > day or r['why'] == 'end' and r['exit'] == day)]
                missing.append(dict(code=t['code'], entry=day, pnl=t['pnl'], r=t['r'],
                    same_code_held=bool(held), **daily[day], attempt=lookup.get((t['code'], day, t['kind']))))
            annual[year] = dict(**D.annual(trades, year), his=D.hits(trades, his, year),
                midpoint=stats['legs']['his'][year]['midpoint'], missing_count=len(missing),
                missing_pnl=sum(t['pnl'] for t in missing), missing=missing)
        limit = 1 if name == 'S5' else 2 if name in SPECS or name == 'R2' else None
        caps = dict(limit=limit,
                    max_retry=max(max(v['retry_at_open'], v['retry_at_close']) for v in daily.values()),
                    max_total=max(max(v['at_open'], v['at_close']) for v in daily.values()),
                    max_new=max(v['new_base']+v['new_retry'] for v in daily.values()))
        if limit is not None:
            assert caps['max_retry'] <= limit and caps['max_total'] <= 11 and caps['max_new'] <= 4, (name, caps)
        pnl = sorted((t['pnl'] for t in trades if t['why'] != 'end'), reverse=True)
        output['runs'][name] = dict(summary=summary.get(name+'_train', read(REFERENCE/'summary.json').get(name+'_train')),
            annual=annual, caps=caps, daily=daily, pnl=sum(pnl), pnl_ex_top1=sum(pnl[1:]), pnl_ex_top3=sum(pnl[3:]),
            r15=sum(t['r'] >= 15 for t in trades if t['why'] != 'end'))
    write(WORK/'diagnostics.json', output)
    train = {name: summary[name+'_train'] for name in ('BASE', *SPECS)}
    selection = dict(eligible=eligible, chosen=chosen,
                    train_sha256=hashlib.sha256(json.dumps(train, sort_keys=True).encode()).hexdigest(),
                    source_sha256=provenance())
    path = WORK/'selection.json'
    if path.exists():
        prior = read(path)
        if any(prior[k] != selection[k] for k in ('eligible', 'chosen', 'train_sha256')) \
                or not same_sources(prior['source_sha256']):
            raise ValueError('E19 selection cannot change after its first assessment')
    else:
        write(path, selection)


def funnel(A, R):
    his = ledger()
    assert len(his) == 43, len(his)
    days = list(map(str, A['days']))
    ci = {str(c): j for j, c in enumerate(A['codes'])}
    result = {}
    for name in ('BASE', 'R2'):
        trades, attempts = rows(name), read(WORK/f'{name}_train/attempts.json')
        records = []
        for h in his:
            code, lo, hi = 'US.'+h['ticker'], h['window_lo'], h['window_hi']
            j = ci.get(code)
            stop = int(np.searchsorted(A['days'], hi, side='right'))
            pool = [days[i] for i in np.flatnonzero(R['pool'][:stop, j])] if j is not None else []
            picks = [day for day, codes in R['picks'].items() if day <= hi and code in codes]
            triggered = [a for a in attempts if a['code'] == code and lo <= a['day'] <= hi]
            matched = [t for t in trades if t['code'] == code and lo <= t['entry'] <= hi]
            won = any(t['pnl'] > 0 and t['why'] != 'end' for t in matched)
            category = ('bought_won' if won else 'bought_lost' if matched else 'triggered_blocked' if triggered
                        else 'named_outside_window' if picks else 'pool_not_named' if pool else 'not_in_pool')
            records.append(dict(id=h['id'], code=code, entry=h['entry_date'], window=[lo, hi],
                precision=h['precision'], category=category, pool_nights=pool, pick_nights=picks,
                window_pool_nights=[d for d in pool if lo <= d <= hi],
                window_pick_nights=[d for d in picks if lo <= d <= hi],
                triggers=triggered, matches=matched,
                rejection_counts=dict(Counter(a['reason'] for a in triggered if a['reason'] != 'filled'))))
        result[name] = dict(counts=dict(Counter(r['category'] for r in records)), records=records,
            blocked_reasons=dict(Counter(a['reason'] for r in records if r['category'] == 'triggered_blocked'
                                         for a in r['triggers'])))
    write(WORK/'funnel.json', result)


def counterfactuals(st, A, cfg, original, R):
    result = {}
    for name in ('S1', 'S2'):
        configure(A, original, R, name)
        book, rules, _, pool = st.build(A, dict(cfg, candidate='C062'))
        ema = st.ema_inputs(A, pool, rules)
        rules = replace(rules, make_room_kind={})
        attempts = read(WORK/f'{name}_train/attempts.json')
        events = read(WORK/f'{name}_train/make_room.json')
        trades = [t for t in rows(name) if t['why'] == 'make_room']
        assert len(events) == len(trades)
        by_key = {(str(A['codes'][e[1]]), str(A['days'][d])): e for d, row in enumerate(book) for e in row}
        records = []
        for t in trades:
            key = t['code'], t['entry']
            entry = by_key[key]
            b = int(np.searchsorted(A['days'], t['entry']))
            d = int(np.searchsorted(A['days'], t['exit']))
            j = entry[1]
            isolated = [[] for _ in book]
            isolated[b] = [entry]
            replayed = E15.Y.simulate(st.px(A), ema, rules, isolated, t['entry'], E15.E.TRAIN[1], audit=True)[2][0]
            alive = replayed['exit'] > t['exit'] or replayed['exit'] == t['exit'] and replayed['why'] == 'end'
            train_end = int(np.searchsorted(A['days'], E15.E.TRAIN[1], side='right'))
            future = slice(d+1, min(train_end, d+61))
            closes = A['close'][future, j]
            valid = np.flatnonzero(np.isfinite(closes))
            price = t['executions'][-1]['price']
            event = next(e for e in events if e['evicted'] == t['code'] and e['entry'] == t['entry'])
            incoming = next(a for a in attempts if a['code'] == event['incoming'] and a['day'] == t['exit']
                            and a['kind'] == event['incoming_kind'])
            assert incoming['reason'] == 'filled' and t['kind'] == RETRY
            assert price == float(A['close'][d, j])
            if name == 'S1':
                assert not t['confirmed']
            records.append(dict(code=t['code'], entry=t['entry'], exit=t['exit'], picked=event['picked'],
                confirmed=t['confirmed'], incoming=event['incoming'], pnl=t['pnl'], r=t['r'], price=price,
                replay_alive_at_eviction=alive, replay_exit=replayed['exit'], replay_why=replayed['why'],
                replay_r=replayed['r'], replay_pnl=replayed['pnl'],
                post_eviction_exit_return=replayed['executions'][-1]['price']/price-1 if alive else None,
                next60_return=float(closes[valid[-1]]/price-1) if len(valid) else None,
                next60_sessions=len(closes), next60_censored=len(closes) < 60,
                next60_max=float(np.nanmax(A['high'][future, j])/price-1) if len(valid) else None,
                next60_min=float(np.nanmin(A['low'][future, j])/price-1) if len(valid) else None))
        result[name] = dict(count=len(records), confirmed=sum(r['confirmed'] for r in records), records=records,
            limitation='isolated C062 replay: no competing holdings; sizing and confirmation can differ before eviction')
    write(WORK/'counterfactuals.json', result)


def check_sources():
    selected = read(WORK/'selection.json')
    if not same_sources(selected['source_sha256']):
        raise ValueError('E19 source or input fingerprint changed after selection')
    return selected


def truncate():
    if check_sources()['chosen'] is None:
        raise ValueError('No eligible E19 arm: prefix check and validation must remain unmeasured')
    with patch.object(D, 'WORK', WORK):
        D.truncate()


def validate():
    selected = check_sources()
    if selected['chosen'] is None or not read(WORK/'truncation.json')['ok']:
        raise ValueError('Validation requires an eligible arm and a passed prefix check')
    once('validation')
    st, A, cfg, original, R = prepare()
    for span in ('2026', 'full'):
        evaluate(st, A, cfg, original, R, selected['chosen'], span)
    write(WORK/'validation_complete.json', dict(chosen=selected['chosen'], independent_out_of_sample=False,
                                              source_sha256=provenance(), memory=E15.B.memory()))


def summary():
    selected, runs = read(WORK/'selection.json'), read(WORK/'summary.json')
    print('E19 eligible:', ','.join(selected['eligible']) or 'none', '; selected:', selected['chosen'] or 'none')
    for name in ('BASE', 'R2', *SPECS):
        r = runs[name+'_train']
        print(f"{name}: 2024 {r['by_year']['2024']:+.2%}; 2025 {r['by_year']['2025']:+.2%}; "
              f"maxdd {r['maxdd']:.2%}; his midpoint {r['midpoint_his']}")
    print('2026/full:', 'measured' if (WORK/'validation_complete.json').exists() else 'not measured')


if __name__ == '__main__':
    from .e1_board_smoke import offline
    offline()
    WORK.mkdir(exist_ok=True)
    parser = argparse.ArgumentParser()
    parser.add_argument('stage', choices=('train', 'assess', 'truncate', 'validate', 'summary'))
    args = parser.parse_args()
    if args.stage in ('train', 'truncate', 'validate'):
        resource.setrlimit(resource.RLIMIT_AS, (E15.LIMIT, E15.LIMIT))
    with runtime():
        globals()[args.stage]()
