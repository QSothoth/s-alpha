"""Offline E18 artifact review, selection and the selected arm's prefix check."""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import ExitStack
import csv
from datetime import date
import hashlib
import json
from pathlib import Path
from unittest.mock import patch

from . import e16_research as E16


WORK = E16.OUT/'e18_review'
ARMS = tuple(E16.E18)
CUT = '2025-06-30'


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=1)+'\n', encoding='utf-8')


def trades(name, directory=E16.OUT):
    return read(directory/f'{name}_train/C062_2024_trades.json')


def select(summary):
    base = summary['BASE_train']
    eligible = [name for name in ARMS if
                all(summary[name+'_train']['by_year'][y] >= base['by_year'][y] for y in ('2024', '2025'))
                and summary[name+'_train']['maxdd'] <= .5
                and summary[name+'_train']['midpoint_his'] >= 12]
    if not eligible:
        return eligible, None
    score = lambda name: min(summary[name+'_train']['by_year'].values())
    best = max(map(score, eligible))
    near = [name for name in eligible if best-score(name) < .02]
    return eligible, min(near, key=lambda name: (-summary[name+'_train']['midpoint_his'], name))


def daily_positions(rows, days):
    result = {}
    for day in days:
        old = [t for t in rows if t['entry'] < day <= t['exit']]
        before = [t for t in old if t['exit'] > day or t['why'] == 'end']
        new = [t for t in rows if t['entry'] == day]
        closing = before+new
        retry = lambda xs: sum(t['kind'] == E16.RETRY_KIND for t in xs)
        result[day] = dict(at_open=len(old), retry_at_open=retry(old), before_entries=len(before),
                           retry_before_entries=retry(before), at_close=len(closing),
                           retry_at_close=retry(closing), new_retry=retry(new), new_base=len(new)-retry(new))
    return result


def annual(rows, year):
    opened = [t for t in rows if t['entry'].startswith(year)]
    closed = [t for t in opened if t['why'] != 'end']
    pnls = sorted((t['pnl'] for t in closed), reverse=True)
    result = dict(opened=len(opened), closed=len(closed), pnl=sum(pnls),
                  end_mark_pnl=sum(t['pnl'] for t in opened if t['why'] == 'end'),
                  pnl_ex_top1=sum(pnls[1:]), pnl_ex_top3=sum(pnls[3:]))
    for name, is_retry in (('base', False), ('retry', True)):
        tr = [t for t in opened if (t['kind'] == E16.RETRY_KIND) == is_retry]
        done = [t for t in tr if t['why'] != 'end']
        result[name] = dict(opened=len(tr), closed=len(done),
                            mean_r=sum(t['r'] for t in done)/len(done) if done else None,
                            pnl=sum(t['pnl'] for t in done))
    return result


def hits(rows, ledger, year):
    records = []
    legacy = []
    for h in ledger:
        if not (h['entry_date'] or h['window_lo']).startswith(year):
            continue
        matches = [t for t in rows if t['code'] == 'US.'+h['ticker'] and
                   h['window_lo'] <= t['entry'] <= h['window_hi']]
        records.append(dict(id=h['id'], code=h['ticker'], day=h['entry_date'],
                            window=[h['window_lo'], h['window_hi']], precision=h['precision'],
                            bought=bool(matches), won=any(t['pnl'] > 0 and t['why'] != 'end' for t in matches)))
        if h['entry_date']:
            legacy.append(any(t['code'] == 'US.'+h['ticker'] and t['pnl'] > 0 and
                              abs((date.fromisoformat(t['entry'])-date.fromisoformat(h['entry_date'])).days) <= 5
                              for t in rows))
    return dict(all=len(records), bought=sum(r['bought'] for r in records),
                won=sum(r['won'] for r in records), legacy_dated_won=sum(legacy),
                legacy_dated_all=len(legacy), records=records)


def assess():
    summary = read(E16.OUT/'summary.json')
    reference = read(E16.OUT/'summary_e16.json')
    base_equal = summary['BASE_train'] == reference['BASE_train']
    if not base_equal:
        raise AssertionError('BASE differs from the E16 summary')
    baseline = trades('BASE')
    with E16.M.STUDY.ledger.open(encoding='utf-8', newline='') as stream:
        ledger = [r for r in csv.DictReader(stream) if r['side'] == 'long'
                  and (r['entry_date'] or r['window_lo'])[:4] in ('2024', '2025')]
    eligible, chosen = select(summary)
    output = dict(base_bitwise=base_equal, eligible=eligible, chosen=chosen, runs={})
    prior_summary = read(WORK/'pre_fix/summary.json')
    for name in ('BASE', 'Q1')+ARMS:
        rows = trades(name)
        days = read(E16.OUT/f'{name}_train/C062_2024_curve.json')['days']
        daily = daily_positions(rows, days)
        stats = read(E16.OUT/f'{name}_train/C062_2024_stats.json')
        by_year = {}
        keys = {(t['code'], t['entry']) for t in rows if t['kind'] != E16.RETRY_KIND}
        for year in ('2024', '2025'):
            missing = [t for t in baseline if t['entry'].startswith(year)
                       and (t['code'], t['entry']) not in keys]
            details = []
            for t in sorted(missing, key=lambda t: -t['pnl']):
                day = t['entry']
                held = [r for r in rows if r['code'] == t['code'] and r['entry'] < day
                        and (r['exit'] > day or r['why'] == 'end' and r['exit'] == day)]
                details.append(dict(code=t['code'], entry=day, pnl=t['pnl'], r=t['r'],
                                    same_code_held=bool(held), **daily[day]))
            by_year[year] = dict(**annual(rows, year), his=hits(rows, ledger, year),
                                 midpoint=stats['legs']['his'][year]['midpoint'],
                                 missing_count=len(missing), missing_pnl=sum(t['pnl'] for t in missing),
                                 missing=details)
        cap = E16.E18.get(name, ('', {}))[1].get('max_open_by_kind', {}).get(E16.RETRY_KIND)
        maximum = max(max(v['retry_at_open'], v['retry_at_close']) for v in daily.values())
        max_new_retry = max(v['new_retry'] for v in daily.values())
        cap_check = dict(limit=cap, observed=maximum, max_new_retry=max_new_retry,
                         max_new_base=max(v['new_base'] for v in daily.values()),
                         max_new_all=max(v['new_base']+v['new_retry'] for v in daily.values()),
                         max_total=max(max(v['at_open'], v['at_close']) for v in daily.values()))
        if name in ARMS:
            assert maximum <= cap and cap_check['max_total'] <= 11, (name, cap_check)
            assert cap_check['max_new_base'] <= 4, (name, cap_check)
            assert max_new_retry <= 1 if name == 'R5' else cap_check['max_new_all'] <= 4, (name, cap_check)
        closed = sorted((t['pnl'] for t in rows if t['why'] != 'end'), reverse=True)
        output['runs'][name] = dict(summary=summary[name+'_train'], prior=prior_summary[name+'_train'],
                                  annual=by_year, caps=cap_check, daily=daily,
                                  pnl=sum(closed), pnl_ex_top1=sum(closed[1:]), pnl_ex_top3=sum(closed[3:]),
                                  r15=sum(t['r'] >= 15 for t in rows if t['why'] != 'end'))
    write(WORK/'diagnostics.json', output)
    train = {name: summary[name+'_train'] for name in ('BASE',)+ARMS}
    selection = dict(eligible=eligible, chosen=chosen, base_bitwise=base_equal,
                     train_sha256=hashlib.sha256(json.dumps(train, sort_keys=True).encode()).hexdigest())
    path = WORK/'selection.json'
    if path.exists() and read(path) != selection:
        raise ValueError('E18 training or selection changed after the recorded decision')
    write(path, selection)
    print('E18 selection:', dict(eligible=eligible, chosen=chosen), flush=True)


def truncate():
    import gc
    import numpy as np
    from studies import trader_data as TD
    from studies.trader_data import panel as TP
    from . import e13_research as B, e14_research as P, e15_research as E15, e1_research as E

    selected = read(WORK/'selection.json')
    name = selected['chosen']
    if name is None:
        raise ValueError('No eligible E18 arm; do not run prefix or 2026 evaluation')
    original_build = TP.build
    def load(market, mode=None, version=None, upto=None, **kw):
        return original_build(TD.dataset(market, mode, version), upto=upto, write_cache=False)
    def build(ds, upto=None, cache=True, write_cache=True):
        return original_build(ds, upto=upto, cache=cache, write_cache=False)
    comparison = {}
    with ExitStack() as stack:
        stack.enter_context(patch.object(TD, 'load', load))
        stack.enter_context(patch.object(TP, 'build', build))
        for module in (B, P, E15):
            for function in ('baseline_check', 'update_checks'):
                if hasattr(module, function):
                    stack.enter_context(patch.object(module, function, lambda *a, **k: None))
        for label, upto in (('full', None), ('cut', CUT)):
            st, A, cfg = E15.setup(upto=upto)
            st.build(A, dict(cfg, candidate='K2'))
            original = A['_e14_base']
            R = st.selected(A)
            book, _ = E16.arm_book(A, R, name, original[0])
            mask = np.zeros_like(original[2])
            for d, row in enumerate(book):
                for entry in row:
                    mask[d, entry[1]] = True
            A['_e14_base'] = (book, E16.arm_rules(original[1], name), mask, original[3])
            A.pop('_e15_books', None)
            entries, rules, _, pool = st.build(A, dict(cfg, candidate='C062'))
            k = int(np.searchsorted(A['days'], CUT, side='right'))
            serialized = [[(list(e[0]), str(A['codes'][e[1]]), *e[2:]) for e in row] for row in entries[:k]]
            result = E15.Y.simulate(st.px(A), st.ema_inputs(A, pool, rules), rules, entries,
                                   E.TRAIN[0], CUT if upto else E.TRAIN[1], audit=True)[2]
            events = B.execution_events(result, CUT)
            picks = {d: row for d, row in R['picks'].items() if d <= CUT}
            write(WORK/f'truncation_{label}.json', dict(entries=serialized, events=events, picks=picks))
            if label == 'full':
                reference = dict(entries=serialized, events=events, picks=picks)
            else:
                comparison = dict(entries_equal=reference['entries'] == serialized,
                                  events_equal=reference['events'] == events, picks_equal=reference['picks'] == picks,
                                  event_count=len(events), cut=CUT, chosen=name)
            del A, st, entries, book, result, mask, R, pool, original
            gc.collect()
    comparison['ok'] = all(comparison[k] for k in ('entries_equal', 'events_equal', 'picks_equal'))
    write(WORK/'truncation.json', comparison)
    assert comparison['ok'], comparison
    print('E18 prefix check:', comparison)


if __name__ == '__main__':
    from .e1_board_smoke import offline
    offline()
    parser = argparse.ArgumentParser()
    parser.add_argument('stage', choices=('assess', 'truncate'))
    args = parser.parse_args()
    {'assess': assess, 'truncate': truncate}[args.stage]()
