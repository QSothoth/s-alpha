"""PREREG_E10_CN.md: one-layer attribution from E8c, five end-to-end candidates from W selected on 2024-25, 2026 once."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from contextlib import ExitStack
from dataclasses import replace
import json
from pathlib import Path
import resource
import subprocess
import sys
from unittest.mock import patch

import numpy as np

from studies import trader_data as TD
from studies.trader_data import panel as TP, supplemental as SP
from studies.trader_replication import gate as G, panels, system as Y
from . import e1_research as E, e8_research as E8, ie47_e1 as M
from .e1_board_smoke import offline
from .ie47_audit import progress, write

ROOT = Path(__file__).resolve().parents[2]
OUT = M.STUDY.reports
WORK = OUT/'e10_work'
PREREG = M.STUDY.root/'notes/PREREG_E10_CN.md'
RESULT = OUT/'e10_train.json'
SELECTED = OUT/'e10_selected.json'
VALIDATION = OUT/'e10_validation.json'
LAYERS = ('P1', 'P0', 'AS', 'AF', 'X1', 'IN', 'RE', 'CS', 'SL')
CANDIDATES = ('K1', 'K2', 'K3', 'K4', 'K5')            # preregistered tie order
EXTRA = ('W+CS', 'W+RE', 'W+SL')


def fingerprints():
    paths = (PREREG, M.PROFILE, Path(M.__file__), Path(__file__), Path(Y.__file__), Path(E.__file__))
    return {str(p.relative_to(ROOT)): SP.sha(p) for p in paths}


def rule_layers(rules, names):
    for k in names:
        if k == 'AS':
            rules = replace(rules, add_signal_stop='low')
        elif k == 'AF':
            rules = replace(rules, add_signal_stop='fill')
        elif k == 'X1':
            rules = replace(rules, exit_signal='', stop_ema_buffer=.01, stop_ema_only=True)
        elif k == 'CS':
            rules = replace(rules, close_stop_days=2, hard_stop_mult=2.)
        elif k == 'SL':
            rules = replace(rules, stop_slip_r=.1)
        elif k == 'RE':
            rules = replace(rules, no_rebuy_day=True)
    return replace(rules, intraday_kinds=tuple(rules.intraday_kinds)+(M.RETEST_KIND, M.OPEN_KIND))


def configs(A, result, ref_book, ref_rules):
    """name -> (book, rules, derived events); every layer is one change from ref, K2-K4 one change back from W."""
    spec = M.E6['E6c']
    setup_book = M.entry_book(A, result['picks'], **spec, setup=True)
    books = dict(ref=(ref_book, []))
    books['P1'] = M.derived_book(A, (ref_book,), 'retest')[::2]
    books['P0'] = M.derived_book(A, (ref_book,), 'next_open')[::2]
    books['IN'] = (setup_book[0], [])
    books['IN+P1'] = M.derived_book(A, setup_book, 'retest')[::2]
    out = {}
    def add(name, book, layers):
        out[name] = (books[book][0], rule_layers(ref_rules, layers), books[book][1])
    add('ref', 'ref', ())
    for k in LAYERS:
        add(k, k if k in books else 'ref', (k,))
    out['RE'] = (M.reentry_book(A, ref_book, A['e9']), rule_layers(ref_rules, ('RE',)), [])
    add('K1', 'P1', ('AS', 'X1'))
    add('K2', 'ref', ('AS', 'X1'))
    add('K3', 'P1', ('X1',))
    add('K4', 'P1', ('AS',))
    add('K5', 'IN+P1', ('AS', 'X1'))
    add('W+CS', 'P1', ('AS', 'X1', 'CS'))
    add('W+SL', 'P1', ('AS', 'X1', 'SL'))
    out['W+RE'] = (M.reentry_book(A, books['P1'][0], A['e9']), rule_layers(ref_rules, ('AS', 'X1', 'RE')), [])
    return out


def forward_peak(A, trades):
    days = {str(d): i for i, d in enumerate(A['days'])}
    codes = {str(c): j for j, c in enumerate(A['codes'])}
    out = []
    for t in trades:
        i, j = days[t['entry']], codes[t['code']]
        hh = A['high'][i+1:i+61, j]
        out.append(float(np.nanmax(hh)/t['fill']-1) if np.isfinite(hh).any() else np.nan)
    return np.array(out)


def table(trades, key):
    rows = defaultdict(list)
    for t in trades:
        rows[key(t)].append(t)
    return {str(k): dict(n=len(v), mean_r=float(np.mean([t['r'] for t in v])), sum_r=float(sum(t['r'] for t in v)),
                         pnl=float(sum(t['pnl'] for t in v))) for k, v in sorted(rows.items(), key=lambda x: str(x[0]))}


def keyed(A, book):
    """(code, fill day) -> (watch night, code): pairs the same observation across configurations."""
    days, codes = list(map(str, A['days'])), list(map(str, A['codes']))
    return {(codes[e[1]], days[d]): (e[0][1], e[0][2]) for d, row in enumerate(book) for e in row}


def his_exact(st, A, trades, span):
    days = list(map(str, A['days']))
    di = {d: i for i, d in enumerate(days)}
    ours = defaultdict(list)
    for t in trades:
        ours[t['code']].append(t)
    rows = []
    for h in st.trades():
        if h.side != 'long' or h.precision != 'exact' or not span[0] <= h.entry_date <= span[1] or h.entry_date not in di:
            continue
        code = h.ticker if h.ticker.startswith('US.') else 'US.'+h.ticker
        i = di[h.entry_date]
        hit = [t for t in ours[code] if i-3 <= di[t['entry']] <= i+2]
        rows.append(dict(code=code, day=h.entry_date, bought=bool(hit), ret=hit[0]['ret_invested'] if hit else None))
    return dict(all=len(rows), bought=sum(r['bought'] for r in rows), won=sum(bool(r['ret'] and r['ret'] > 0) for r in rows),
                rows=rows)


def mechanism(A, book, events, trades, track, ref_keys, ref_r):
    closed = G.closed(trades)
    di = {str(d): i for i, d in enumerate(A['days'])}
    ci = {str(c): j for j, c in enumerate(A['codes'])}
    widths = np.array([t['risk_pct'] for t in trades if t.get('risk_pct')])
    peak = forward_peak(A, closed)
    ret = np.array([t['ret_invested'] for t in closed])
    big = peak >= .33
    keys = keyed(A, book)
    pairs = [t['r'] - ref_r[keys[(t['code'], t['entry'])]] for t in closed
             if (t['code'], t['entry']) in keys and keys[(t['code'], t['entry'])] in ref_r]
    pos = sorted((t['pnl'] for t in closed if t['pnl'] > 0), reverse=True)
    signals = sum(map(len, book))
    return dict(
        by_why=table(closed, lambda t: t['why']),
        by_added=table(closed, lambda t: any(e['action'] == 'add' for e in t.get('executions', ()))),
        survival={k: float(np.mean([t['days'] >= k for t in closed])) for k in range(1, 11)},
        funnel=dict(signals=signals, opened=len(trades), account_rejected=signals-len(trades),
                    derived=dict(Counter(e['why'] for e in events))),
        runs={name: dict(n=int(m.sum()), win=float((ret[m] > 0).mean()) if m.any() else None,
                         mean=float(ret[m].mean()) if m.any() else None)
              for name, m in (('<5%', peak < .05), ('5-15%', (peak >= .05) & (peak < .15)),
                              ('15-33%', (peak >= .15) & (peak < .33)), ('>=33%', big))},
        big_capture=dict(share_positive=float((ret[big] > 0).mean()) if big.any() else None,
                         median_ret_positive=float(np.median(ret[big & (ret > 0)])) if (big & (ret > 0)).any() else None),
        gap=dict(share=float(np.mean([t['why'] == 'gap_stop' for t in closed])),
                 mean_r=float(np.mean([t['r'] for t in closed if t['why'] == 'gap_stop'] or [np.nan]))),
        top10_share=float(sum(pos[:10])/sum(pos)) if pos else None,
        winners20=int((ret >= .2).sum()),
        paired=dict(n=len(pairs), median_dr=float(np.median(pairs)) if pairs else None),
        exposure=dict(gross=float(np.mean(track['gross'])), open=float(np.mean(track['open'])), margin=float(track['margin'])),
        by_kind=table(closed, lambda t: t['kind']),
        stop_width_median=float(np.median(widths)) if len(widths) else None,
        add_squeezed_share=float(np.mean(widths < .005/.25)) if len(widths) else None,
        added_share=float(np.mean([any(e['action'] == 'add' for e in t.get('executions', ())) for t in closed])),
        retest_after=dict(Counter(e['after'] for e in events if e.get('after') is not None)),
        entry_off_low=float(np.median([t['fill']/A['low'][di[t['entry']], ci[t['code']]]-1 for t in closed]))
        if closed else None)


def evaluate(st, A, pool, name, book, rules, events, span, ref_keys, ref_r):
    stats, trades, curve, dates = E.summary(st, A, book, rules, pool, span)
    E8.invested(st, stats, trades)
    track = {}
    Y.simulate(st.px(A), st.ema_inputs(A, pool, rules), rules, book, *span, track=track)
    stats['mechanism'] = mechanism(A, book, events, trades, track, ref_keys, ref_r)
    stats['his_exact'] = his_exact(st, A, trades, span)
    write(WORK/f'{name}_{span[0][:4]}_trades.json', trades)
    progress(f"{name}: {span[0][:4]} total={stats['total']:+.4f} closed={stats['trades']} win={stats['win']:.3f} "
             f"big+={stats['mechanism']['big_capture']['share_positive']} w20={stats['mechanism']['winners20']}")
    return stats, trades


def setup():
    st = M.IE47Study()
    st.progress = progress
    A = st.arrays('us')
    cfg = dict(candidate='E8c', profile_sha256=SP.sha(M.PROFILE), frozen_inputs_sha256=M.inputs_digest(st.selected(A)['sources']))
    ref_book, ref_rules, _, pool = st.build(A, cfg, {})
    return st, A, cfg, ref_book, ref_rules, pool, configs(A, st.selected(A), ref_book, ref_rules)


def train():
    if RESULT.exists() or SELECTED.exists():
        raise ValueError('E10 training already recorded; do not rerun or select again')
    write(WORK/'train_started.json', fingerprints())
    st, A, cfg, ref_book, ref_rules, pool, todo = setup()
    _, ref_trades, _, _ = E.summary(st, A, ref_book, ref_rules, pool, E.TRAIN)
    ref_keys = keyed(A, ref_book)
    ref_r = {ref_keys[(t['code'], t['entry'])]: t['r'] for t in G.closed(ref_trades)}
    out = dict(preregistered_sha256=SP.sha(PREREG), source_sha256=fingerprints(), span=list(E.TRAIN), base=cfg, runs={})
    for name in ('ref',) + LAYERS + CANDIDATES + EXTRA:
        book, rules, events = todo[name]
        out['runs'][name], _ = evaluate(st, A, pool, name, book, rules, events, E.TRAIN, ref_keys, ref_r)
        write(RESULT.with_suffix('.partial.json'), out)
    ref = out['runs']['ref']
    def eligible(k):
        s = out['runs'][k]
        return s['trades'] >= .7*ref['trades'] and s['mechanism']['winners20'] >= .9*ref['mechanism']['winners20']
    ok, fallback = [k for k in CANDIDATES if eligible(k)], False
    if not ok:
        ok, fallback = [k for k in LAYERS if eligible(k)], True
    chosen = None
    if ok:
        best = max(out['runs'][k]['total'] for k in ok)
        near = [k for k in ok if best-out['runs'][k]['total'] < .02]
        order = LAYERS if fallback else CANDIDATES
        chosen = min(near, key=lambda k: (out['runs'][k]['behaviour_gap'], order.index(k)))
    out.update(eligible=ok, fallback=fallback, chosen=chosen)
    write(RESULT, out)
    with SELECTED.open('x', encoding='utf-8') as stream:
        json.dump(dict(chosen=chosen, eligible=ok, fallback=fallback, preregistered_sha256=SP.sha(PREREG), source_sha256=fingerprints()),
                  stream, ensure_ascii=False, indent=1)
    progress(f'eligible={ok}; selected {chosen} on 2024-25 only; 2026 unmeasured')


def validate():
    if VALIDATION.exists():
        raise ValueError('E10 validation already recorded')
    selected = json.loads(SELECTED.read_text())
    if selected['preregistered_sha256'] != SP.sha(PREREG) or selected['source_sha256'] != fingerprints():
        raise ValueError('E10 preregistration or source changed after selection')
    if selected['chosen'] is None:
        raise ValueError('E10 selected nothing; 2026 is not measured')
    with (WORK/'validation_started.json').open('x', encoding='utf-8') as stream:
        json.dump(dict(selected_sha256=SP.sha(SELECTED)), stream)
    st, A, cfg, ref_book, ref_rules, pool, todo = setup()
    _, ref_trades, _, _ = E.summary(st, A, ref_book, ref_rules, pool, E.VALIDATE)
    ref_keys = keyed(A, ref_book)
    ref_r = {ref_keys[(t['code'], t['entry'])]: t['r'] for t in G.closed(ref_trades)}
    book, rules, events = todo[selected['chosen']]
    held, _ = evaluate(st, A, pool, selected['chosen'], book, rules, events, E.VALIDATE, ref_keys, ref_r)
    full, _ = evaluate(st, A, pool, selected['chosen']+'_full', book, rules, events, panels.WINDOW, ref_keys, ref_r)
    write(VALIDATION, dict(chosen=selected['chosen'], validate=held, full=full, preregistered_sha256=SP.sha(PREREG),
                           scope='one chosen E10 candidate; 2026 already used by IE47 and E3-E9'))
    progress(f"{selected['chosen']} 2026={held['total']:+.4f}; full={full['total']:+.4f}")


def checks():
    results = {}
    for name, args in (('custody', ['discover', '-s', 'custody/tests']),
                       ('trader_replication', ['discover', '-s', 'studies/trader_replication/tests']),
                       ('martin_luk', ['discover', '-s', 'studies/martin_luk/tests'])):
        path = WORK/f'test_{name}.log'
        with path.open('w', encoding='utf-8') as stream:
            rc = subprocess.run([sys.executable, '-m', 'unittest', *args], stdout=stream,
                                stderr=subprocess.STDOUT).returncode
        results[name] = dict(ok=rc == 0, summary=path.read_text().splitlines()[-3:])
        progress(name+' tests: '+('passed' if rc == 0 else 'failed'))
    write(OUT/'e10_checks.json', results)
    if not all(r['ok'] for r in results.values()):
        raise SystemExit('E10 required tests failed')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('stage', choices=('train', 'validate', 'checks'))
    stage = parser.parse_args().stage
    WORK.mkdir(exist_ok=True)
    if stage == 'checks':
        checks()
    else:
        resource.setrlimit(resource.RLIMIT_AS, (1_500_000_000, 1_500_000_000))
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
