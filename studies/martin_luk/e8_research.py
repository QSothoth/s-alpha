"""PREREG_E8_CN.md: four fixed market risk-scale candidates on E7a selected on 2024-25, the chosen one on 2026 once."""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import ExitStack
from functools import lru_cache
import json
from pathlib import Path
import resource
import subprocess
import sys
from unittest.mock import patch

import numpy as np

from studies import trader_data as TD
from studies.trader_data import panel as TP, supplemental as SP
from studies.trader_replication import gate as G, panels, study, success, system as Y
from . import e1_research as E, ie47_e1 as M
from .e1_board_smoke import offline
from .ie47_audit import progress, write

ROOT = Path(__file__).resolve().parents[2]
OUT = M.STUDY.reports
WORK = OUT/'e8_work'
PREREG = M.STUDY.root/'notes/PREREG_E8_CN.md'
ORDER = ('E8c', 'E8d', 'E8a', 'E8b')  # preregistered tie order
CANDIDATES = OUT/'e8_candidates.json'
SELECTED = OUT/'e8_selected.json'
VALIDATION = OUT/'e8_validation.json'
HALF = {'2024': 212, '2025': 470}


def fingerprints():
    paths = (PREREG, M.PROFILE, Path(M.__file__), Path(__file__), Path(E.__file__), Path(Y.__file__),
             ROOT/'studies/trader_replication/success.py')
    return {str(p.relative_to(ROOT)): SP.sha(p) for p in paths}


def invested(st, stats, trades):
    """PREREG_E7: with adds the engine's ret is on the first shares; average win / loss and gap use ret_invested."""
    closed = [dict(t, ret=t['ret_invested']) for t in G.closed(trades)]
    for y, row in stats['annual'].items():
        yt = study.year_trades(closed, y)
        row['avg_win_first_shares'], row['avg_loss_first_shares'] = row['avg_win'], row['avg_loss']
        row.update(avg_win=yt['avg_win'], avg_loss=yt['avg_loss'])
        row['gap'], row['gap_parts'] = study.gap(dict(row, per_year=row['n']), st.his.get(y, {}))
    gaps = [r['gap'] for r in stats['annual'].values() if r['gap'] is not None]
    stats['behaviour_gap'] = float(np.mean(gaps)) if gaps else None


def extras(stats, trades, events, span):
    """Report-only diagnostics; none of them enters the selection key."""
    for year, row in [('all', stats), *stats['annual'].items()]:
        inside = (lambda day: span[0] <= day <= span[1]) if year == 'all' else (lambda day, y=year: day.startswith(y))
        closed = [t for t in G.closed(trades) if inside(t['entry'])]
        opened = [t for t in trades if inside(t['entry'])]
        ev = Counter(e['why'] for e in events if inside(e['day']))
        row['exit_reasons'] = dict(Counter(t['why'] for t in closed))
        row['median_days'] = float(np.median([t['days'] for t in closed])) if closed else None
        row['observation_events'] = dict(ev)
        confirmed = ev['triggered']
        row['confirmed_cap'] = confirmed
        row['account_rejected'] = confirmed-len(opened)
        row['capped_share'] = ev['capped']/confirmed if confirmed else None
        row['ema_exits'] = sum(t['why'] in ('trail', 'signal') for t in closed)
        row['r5_plus'] = sum(t['r'] >= 5 for t in closed)
        row['added'] = sum(any(e['action'] == 'add' for e in t.get('executions', ())) for t in closed)
        row['by_kind'] = {k: dict(n=len(v), mean_r=float(np.mean([t['r'] for t in v])))
                          for k in {t['kind'] for t in closed} for v in [[t for t in closed if t['kind'] == k]]}
        months = Counter()
        for t in closed:
            months[t['entry'][:7]] += t['r']
        row['r_by_month'] = {k: round(v, 1) for k, v in sorted(months.items())}
        if 'scale' in stats:
            row['scale_share'] = {str(k): v for k, v in Counter(stats['scale'].get(t['entry'], 1.) for t in opened).items()}
        widths = [t['risk_pct'] for t in opened if t.get('risk_pct')]
        row['stop_width_median'] = float(np.median(widths)) if widths else None
        row['position_capped_share'] = float(np.mean([w < .005/.25 for w in widths])) if widths else None
        if year in HALF:
            row['his_half'] = HALF[year]


def his_tickers(st, A, rules, pool, candidate):
    """His exact-date long entries under one candidate's entry rule, same day only, same account."""
    entries = [[] for _ in A['days']]
    di, ci = ({str(v): i for i, v in enumerate(A[k])} for k in ('days', 'codes'))
    rows, seen = [], set()
    spec = dict(M.E6['E6c'], observe=1, pullback=M.E8[candidate]['pullback'])
    for t in st.trades():
        if t.side != 'long' or t.precision != 'exact' or not E.TRAIN[0] <= t.entry_date <= E.TRAIN[1]:
            continue
        code = t.ticker if t.ticker.startswith('US.') else 'US.'+t.ticker
        d, j = di.get(t.entry_date), ci.get(code)
        row = dict(id=t.id, code=code, day=t.entry_date, his_outcome=t.outcome, his_r=t.r_multiple)
        if d is None or j is None or not d or not A['has'][d, j]:
            row['status'] = 'missing_data'
        elif (d, j) in seen:
            row['status'] = 'duplicate_same_stock_day'
        else:
            seen.add((d, j))
            book, _, events = M.entry_book(A, {str(A['days'][d-1]): [code]}, **spec)
            if book[d]:
                entries[d].append(book[d][0])
                row['status'] = 'triggered'
                row['capped'] = any(e['why'] == 'capped' for e in events)
            else:
                row['status'] = 'wide_stop' if any(e['why'] == 'wide_stop' for e in events) \
                    else 'no_close_break_or_invalid_bar'
        rows.append(row)
    stats, trades, _, _ = E.summary(st, A, entries, rules, pool, E.TRAIN)
    bought = {(t['code'], t['entry']): t for t in trades}
    for row in rows:
        if row['status'] == 'triggered':
            trade = bought.get((row['code'], row['day']))
            row['status'] = 'bought' if trade else 'account_rejected'
            if trade:
                row.update(our_ret=trade['ret'], our_r=trade['r'], days=trade['days'], why=trade['why'])
    return dict(stats=stats, per_trade=rows, all=len(rows),
                bought=sum(r['status'] == 'bought' for r in rows), statuses=dict(Counter(r['status'] for r in rows)))


def train():
    if CANDIDATES.exists() or SELECTED.exists():
        raise ValueError('E8 training/selection already recorded; do not overwrite or select again')
    write(WORK/'train_started.json', fingerprints())
    st = M.IE47Study()
    st.progress = progress
    st.arrays = lru_cache(maxsize=3)(st.arrays)
    A = st.arrays('us', upto=E.TRAIN[1])
    sources = M.inputs_digest(st.selected(A)['sources'])
    out = dict(preregistered_sha256=SP.sha(PREREG), source_sha256=fingerprints(), selection_span=list(E.TRAIN),
               draws=100, seed=1, candidates={})
    for k in ORDER:
        cfg = dict(candidate=k, profile_sha256=SP.sha(M.PROFILE), frozen_inputs_sha256=sources)
        trace = {}
        entries, rules, _, pool = st.build(A, cfg, trace)
        stats, trades, curve, dates = E.summary(st, A, entries, rules, pool, E.TRAIN, draws=100)
        stats['scale'] = dict(zip(map(str, A['days']), map(float, A['e8_scale'])))
        extras(stats, trades, trace['observations'], E.TRAIN)
        del stats['scale']
        invested(st, stats, trades)
        checks = G.verdict(dict(data=E.data_gate(A, E.TRAIN), lookahead=G.check_lookahead(st, cfg, 'us', full=A),
                                fills=G.check_fills(A, trades), win_rate=G.check_win(trades)))
        dropped = success.drop_top(A, entries, trades)
        stats['drop2'] = float(Y.simulate(st.px(A), st.ema_inputs(A, pool, rules), rules, dropped, *E.TRAIN)[0][-1]-1)
        stats['gate'] = checks
        stats['judgements'], stats['success'] = E.judge_years(st, stats, checks, stats['placebo']['median'], stats['drop2'])
        stats['selection_passes'] = sum(ok for name, ok, _ in stats['success'] if name != 'validate')
        stats['his_exact'] = his_tickers(st, A, rules, pool, k)
        stats['2026'] = '未测'
        out['candidates'][k] = dict(config=cfg, **stats)
        write(WORK/f'{k}_train_trades.json', trades)
        write(WORK/f'{k}_train_curve.json', dict(days=dates.tolist(), equity=curve.tolist()))
        write(WORK/f'{k}_train.json', out['candidates'][k])
        progress(f"{k}: train={stats['total']:+.4f} closed={stats['trades']} gate={checks['ok']} "
                 f"passes={stats['selection_passes']}/6 gap={stats['behaviour_gap']:.4f} "
                 f"his_exact={stats['his_exact']['bought']}/{stats['his_exact']['all']}")

    def score(k):
        s = out['candidates'][k]
        return s['selection_passes'], s['placebo']['rank'], -s['behaviour_gap'], -ORDER.index(k)
    chosen = max(ORDER, key=score)
    out.update(chosen=chosen, selection_keys={k: score(k) for k in ORDER})
    write(CANDIDATES, out)
    with SELECTED.open('x', encoding='utf-8') as stream:
        json.dump(dict(chosen=chosen, config=out['candidates'][chosen]['config'], selection_key=score(chosen),
                       preregistered_sha256=SP.sha(PREREG), source_sha256=fingerprints()),
                  stream, ensure_ascii=False, indent=1)
        stream.write('\n')
    progress(f'selected {chosen} on 2024-25 only; 2026 unmeasured')


def validate():
    if VALIDATION.exists():
        raise ValueError('E8 validation already recorded; read it without reevaluation')
    selected = json.loads(SELECTED.read_text())
    if selected['preregistered_sha256'] != SP.sha(PREREG) or selected['source_sha256'] != fingerprints():
        raise ValueError('E8 preregistration or source changed after selection')
    with (WORK/'validation_started.json').open('x', encoding='utf-8') as stream:
        json.dump(dict(selected_sha256=SP.sha(SELECTED)), stream)
    st, cfg = M.IE47Study(), selected['config']
    st.progress = progress
    A = st.arrays('us')
    trace = {}
    entries, rules, _, pool = st.build(A, cfg, trace)
    full, trades, curve, dates = E.summary(st, A, entries, rules, pool, panels.WINDOW, draws=100)
    heldout, held, _, _ = E.summary(st, A, entries, rules, pool, E.VALIDATE, draws=100)
    extras(full, trades, trace['observations'], panels.WINDOW)
    extras(heldout, held, trace['observations'], E.VALIDATE)
    invested(st, full, trades)
    invested(st, heldout, held)
    dropped = success.drop_top(A, entries, trades)
    full['drop2'] = float(Y.simulate(st.px(A), st.ema_inputs(A, pool, rules), rules, dropped, *panels.WINDOW)[0][-1]-1)
    checks = G.verdict(dict(data=E.data_gate(A, panels.WINDOW), lookahead=G.check_lookahead(st, cfg, 'us', full=A),
                            fills=G.check_fills(A, trades), win_rate=G.check_win(trades)))
    raw, judged = E.judge_years(st, full, checks, full['placebo']['median'], full['drop2'], heldout)
    write(VALIDATION, dict(chosen=selected['chosen'], config=cfg, full=full, validate=heldout, gate=checks,
                           judgements=raw, success=judged, preregistered_sha256=SP.sha(PREREG),
                           selection_scope='one chosen E8 candidate; IE47, E3, E5, E6c and E7a already used 2026'))
    write(WORK/'full_trades.json', trades)
    write(WORK/'full_curve.json', dict(days=dates.tolist(), equity=curve.tolist()))
    progress(f"{selected['chosen']} 2026={full['by_year']['2026']:+.4f}; gate={checks['ok']}; "
             f"success={sum(ok for _, ok, _ in judged)}/7")


def checks():
    results = {}
    suites = [('custody', ['discover', '-s', 'custody/tests']),
              ('trader_replication', ['discover', '-s', 'studies/trader_replication/tests']),
              ('trader_screens', ['discover', '-s', 'studies/trader_screens/tests', '-t', '.']),
              ('martin_luk', ['discover', '-s', 'studies/martin_luk/tests'])]
    for name, args in suites:
        path = WORK/f'test_{name}.log'
        with path.open('w', encoding='utf-8') as stream:
            rc = subprocess.run([sys.executable, '-m', 'unittest', *args], stdout=stream,
                                stderr=subprocess.STDOUT).returncode
        results[name] = dict(ok=rc == 0, summary=path.read_text().splitlines()[-3:])
        write(OUT/'e8_checks.json', results)
        progress(name+' tests: '+('passed' if rc == 0 else 'failed'))
    if not all(r['ok'] for r in results.values()):
        raise SystemExit('E8 required tests failed')


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
