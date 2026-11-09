"""Preregistered E1-E4 selection on 2024-25, then the chosen execution on 2026 once."""
from __future__ import annotations

import argparse
from functools import lru_cache
import json
from pathlib import Path
import resource
import subprocess
import sys

import numpy as np

from studies.trader_data import supplemental as SP
from studies.trader_replication import compare, gate as G, panels, study, success, system as Y
from . import ie47_e1 as M
from .ie47_audit import WORK, progress, write

ROOT = Path(__file__).resolve().parents[2]
PREREG = M.STUDY.root / 'notes/PREREG_E1_CN.md'
TRAIN = ('2024-01-02', '2025-12-31')
VALIDATE = ('2026-01-02', panels.WINDOW[1])
SELECTED = WORK.parent / 'e1_selected.json'
RESULT = WORK.parent / 'e1_candidates.json'
VALIDATION = WORK.parent / 'e1_validation.json'


def fingerprints():
    files = [PREREG, M.PROFILE, Path(M.__file__), Path(Y.__file__), Path(__file__),
             ROOT/'studies/trader_replication/standard_indicators.py',
             ROOT/'studies/trader_data/supplemental.py']
    return {str(p.relative_to(ROOT)): SP.sha(p) for p in files}


def summary(st, A, entries, rules, pool, span, draws=0):
    px, ema = st.px(A), st.ema_inputs(A, pool, rules)
    curve, dates, trades = Y.simulate(px, ema, rules, entries, *span, audit=True)
    d0, d1 = np.searchsorted(A['days'], span[0]), np.searchsorted(A['days'], span[1], side='right')
    out = compare.metrics(curve, dates, trades, entries, d0, d1)
    closed = G.closed(trades)
    out['mean_days'] = float(np.mean([t['days'] for t in closed])) if closed else None
    out['annual'] = {}
    for y in out['by_year']:
        tr = [t for t in closed if t['entry'].startswith(y)]
        row = study.year_trades(tr, y)
        row.update(opened=sum(t['entry'].startswith(y) for t in trades),
                   mean_days=float(np.mean([t['days'] for t in tr])) if tr else None,
                   days_win=float(np.mean([t['days'] for t in tr if t['ret'] > 0])) if any(t['ret'] > 0 for t in tr) else None,
                   days_loss=float(np.mean([t['days'] for t in tr if t['ret'] <= 0])) if any(t['ret'] <= 0 for t in tr) else None)
        ix = np.flatnonzero(np.char.startswith(dates.astype(str), y))
        seg = np.r_[curve[ix[0]-1] if ix[0] else 1., curve[ix]]
        row['maxdd'] = float(np.max(1-seg/np.maximum.accumulate(seg)))
        row['ret'] = out['by_year'][y]
        behaviour = dict(row, per_year=row['n'])
        row['gap'], row['gap_parts'] = study.gap(behaviour, st.his.get(y, {}))
        out['annual'][y] = row
    gaps = [r['gap'] for r in out['annual'].values() if r['gap'] is not None]
    out['behaviour_gap'] = float(np.mean(gaps)) if gaps else None
    out['year_gap'] = st.year_gap(out['by_year'])
    if draws:
        out['placebo'] = Y.placebo_rank(px, ema, rules, entries, *span, pool, draws=draws, seed=1)
    return out, trades, curve, dates


def judge_years(st, stats, gate, placebo_median, drop2, validate=None):
    raw = {}
    for y in ('2024', '2025'):
        his = st.his[y]
        row = stats['annual'][y]
        card = dict(counts={y: his['per_year']}, source='PLAN_E1_CN.md §5; RULES_CN.md; replicate.HIS',
                    behaviour={k: his[k] for k in ('win', 'avg_win', 'avg_loss')}, years={y: his['ret']})
        ours = dict(gate={k: gate[k]['ok'] for k in ('data', 'lookahead', 'fills')}, win=stats['win'],
                    closed=stats['trades'], per_year=row['n'],
                    counts={year: r.get('opened', r['n']) for year, r in stats['annual'].items()},
                    behaviour={k: row[k] for k in ('win', 'avg_win', 'avg_loss')}, years=stats['by_year'],
                    total=stats['total'], placebo_median=placebo_median, total_drop2=drop2,
                    validate_total=validate['total'] if validate else None,
                    validate_placebo_median=validate['placebo']['median'] if validate else None)
        raw[y] = success.judge(card, ours)
    combined = [(name, all(r[i][1] for r in raw.values()), {y: r[i][2] for y, r in raw.items()})
                for i, (name, _, _) in enumerate(raw['2024'])]
    return raw, combined


def data_gate(A, span):
    dates = [str(d) for d in A['days'] if span[0] <= str(d) <= span[1]]
    pin = panels.pinned()
    return G.check_data(panels.TAG, A['digest'], [dates[0], dates[-1]], pin['tag'], pin['markets']['us'], span, A['days'])


def train():
    if RESULT.exists() or SELECTED.exists():
        raise ValueError('E1-E4 training/selection already recorded; do not overwrite or select again')
    audit = json.loads((WORK.parent/'e1_selection.json').read_text())
    if audit['ordered_exact_rate'] < .95 or not audit['scorecard_equal']:
        raise ValueError('selection migration gate failed')
    for cut in G.CUTS:
        if not json.loads((WORK/f'selection_cut_{cut}.json').read_text())['prefix_equal']:
            raise ValueError('selection truncation gate failed')
    st = M.IE47Study()
    st.progress = progress
    # Each distinct cutoff is actually rebuilt once, then reused across the four fixed candidates. Cache keys
    # include the cutoff: no full-panel selection is sliced to stand in for a truncated calculation.
    st.arrays = lru_cache(maxsize=3)(st.arrays)
    A = st.arrays('us', upto=TRAIN[1])
    st.selected(A)
    out = dict(preregistered_sha256=SP.sha(PREREG), profile_sha256=SP.sha(M.PROFILE),
               source_sha256=fingerprints(), selection_span=list(TRAIN), validation_span=list(VALIDATE),
               draws=100, seed=1, candidates={})
    for candidate in M.CANDIDATES:
        cfg = dict(candidate=candidate, profile_sha256=SP.sha(M.PROFILE),
                   frozen_inputs_sha256=M.inputs_digest(st.selected(A)['sources']))
        entries, rules, mask, pool = st.build(A, cfg)
        stats, trades, curve, dates = summary(st, A, entries, rules, pool, TRAIN, draws=100)
        progress(f'{candidate}: training return={stats["total"]:+.4f}, closed={stats["trades"]}')
        checks = G.verdict(dict(data=data_gate(A, TRAIN), lookahead=G.check_lookahead(st, cfg, 'us', full=A),
                                fills=G.check_fills(A, trades), win_rate=G.check_win(trades)))
        dropped = success.drop_top(A, entries, trades)
        drop_curve = Y.simulate(st.px(A), st.ema_inputs(A, pool, rules), rules, dropped, *TRAIN)[0]
        stats['drop2'] = float(drop_curve[-1]-1)
        stats['gate'] = checks
        stats['judgements'], stats['success'] = judge_years(st, stats, checks, stats['placebo']['median'], stats['drop2'])
        stats['selection_passes'] = sum(ok for name, ok, _ in stats['success'] if name != 'validate')
        stats['2026'] = '未测'
        out['candidates'][candidate] = dict(config=cfg, **stats)
        write(WORK/f'{candidate}_train_trades.json', trades)
        write(WORK/f'{candidate}_train.json', out['candidates'][candidate])
        progress(f'{candidate}: gate={checks["ok"]}, success groups={stats["selection_passes"]}/6, gap={stats["behaviour_gap"]:.4f}')
    def score(k):
        s = out['candidates'][k]
        return s['selection_passes'], -s['behaviour_gap'], -s['year_gap'], -M.CANDIDATES.index(k)
    chosen = max(M.CANDIDATES, key=score)
    selected = dict(chosen=chosen, config=out['candidates'][chosen]['config'], selection_key=score(chosen),
                    preregistered_sha256=SP.sha(PREREG), source_sha256=fingerprints(),
                    validation_not_yet_run=True)
    out.update(chosen=chosen, selection_keys={k: score(k) for k in M.CANDIDATES})
    write(RESULT, out)
    with SELECTED.open('x', encoding='utf-8') as stream:
        json.dump(selected, stream, ensure_ascii=False, indent=1)
        stream.write('\n')
    progress('selected '+chosen+' on 2024-25 only; 2026 remains unmeasured')


def validate():
    if VALIDATION.exists():
        progress('validation already recorded; reuse it without reevaluation')
        return
    selected = json.loads(SELECTED.read_text())
    if SP.sha(PREREG) != selected['preregistered_sha256']:
        raise ValueError('pre-registration changed after selection')
    marker = WORK/'validation_started.json'
    if marker.exists():
        raise ValueError('validation started without a completed artifact; inspect the failure before resuming')
    write(marker, dict(selected_sha256=SP.sha(SELECTED), source_sha256=fingerprints()))
    st, cfg = M.IE47Study(), selected['config']
    st.progress = progress
    A = st.arrays('us')
    entries, rules, mask, pool = st.build(A, cfg)
    full, trades, curve, dates = summary(st, A, entries, rules, pool, panels.WINDOW, draws=100)
    heldout, _, _, _ = summary(st, A, entries, rules, pool, VALIDATE, draws=100)
    dropped = success.drop_top(A, entries, trades)
    dropped_curve = Y.simulate(st.px(A), st.ema_inputs(A, pool, rules), rules, dropped, *panels.WINDOW)[0]
    full['drop2'] = float(dropped_curve[-1]-1)
    checks = G.verdict(dict(data=data_gate(A, panels.WINDOW), lookahead=G.check_lookahead(st, cfg, 'us', full=A),
                            fills=G.check_fills(A, trades), win_rate=G.check_win(trades)))
    raw, judged = judge_years(st, full, checks, full['placebo']['median'], full['drop2'], heldout)
    result = dict(chosen=selected['chosen'], config=cfg, full=full, validate=heldout, gate=checks,
                  judgements=raw, success=judged, selected_sha256=SP.sha(SELECTED),
                  preregistered_sha256=SP.sha(PREREG), source_sha256=fingerprints(),
                  validation_scope='one execution candidate; IE47 selection has already been evaluated on 2026')
    write(VALIDATION, result)
    write(WORK/'chosen_full_trades.json', trades)
    write(WORK/'chosen_curve.json', dict(days=dates.tolist(), equity=curve.tolist()))
    progress(f"{selected['chosen']} 2026={full['by_year']['2026']:+.4f}, gate={checks['ok']}, success="
             f"{sum(ok for _, ok, _ in judged)}/7")


def three():
    path = WORK.parent/'e1_three.json'
    if path.exists():
        raise ValueError('E1 three-layer diagnostic already recorded')
    selected = json.loads(SELECTED.read_text())
    # The task fixes this diagnostic to E1. Do not expose an unselected E1's 2026 outcome.
    span = panels.WINDOW if selected['chosen'] == 'E1' else TRAIN
    st = M.IE47Study()
    st.progress = progress
    A = st.arrays('us', upto=span[1])
    cfg = dict(candidate='E1')
    entries, rules, mask, pool = st.build(A, cfg)
    ours, tr3, _, _ = summary(st, A, entries, rules, pool, span)
    mine = [[] for _ in A['days']]
    di, ci = {str(d): i for i, d in enumerate(A['days'])}, {str(c): j for j, c in enumerate(A['codes'])}
    rows, seen = [], set()
    for t in st.trades():
        if t.side != 'long' or t.precision != 'exact' or not span[0] <= t.entry_date <= span[1]:
            continue
        code = 'US.'+t.ticker if not t.ticker.startswith('US.') else t.ticker
        d, j = di.get(t.entry_date), ci.get(code)
        row = dict(id=t.id, code=code, day=t.entry_date, his_outcome=t.outcome, his_r=t.r_multiple)
        if d is None or j is None or not d:
            row['status'] = 'missing_data'
        elif (d, j) in seen:
            row['status'] = 'duplicate_same_stock_day'
        else:
            seen.add((d, j))
            book, _, events = M.entry_book(A, {str(A['days'][d-1]): [code]}, observe=1)
            if book[d]:
                mine[d].append(book[d][0])
                row['status'] = 'triggered'
            else:
                row['status'] = 'chase' if any(e['why'] == 'chase' for e in events) else 'no_break_or_invalid_bar'
        rows.append(row)
    his, tr2, _, _ = summary(st, A, mine, rules, pool, span)
    by_entry = {(t['code'], t['entry']): t for t in tr2}
    for row in rows:
        trade = by_entry.get((row['code'], row['day']))
        if row['status'] == 'triggered':
            row['status'] = 'bought' if trade else 'account_rejected'
        if trade and row['status'] == 'bought':
            row.update(our_ret=trade['ret'], our_r=trade['r'], days=trade['days'], why=trade['why'])
    result = dict(span=list(span), his_public=st.his, his_tickers_e1=his, ie47_e1=ours,
                  master_execution=json.loads((M.ROOT/'studies/trader_replication/reports/gap_review/ie47_work/swap_master_execution.json').read_text()),
                  exact=dict(all=len(rows), bought=sum(r['status'] == 'bought' for r in rows)),
                  per_trade=rows, same_account_rules=True)
    write(path, result)
    write(WORK/'his_exact_e1_trades.json', tr2)
    progress(f"three layers: his tickers {his['total']:+.4f}; IE47 {ours['total']:+.4f}; span={span}")


def checks():
    suites = [('custody', ['discover', '-s', 'custody/tests']),
              ('trader_replication', ['discover', '-s', 'studies/trader_replication/tests']),
              ('trader_screens', ['discover', '-s', 'studies/trader_screens/tests', '-t', '.']),
              ('martin_luk', ['discover', '-s', 'studies/martin_luk/tests']),
              ('trader_data', ['discover', '-s', 'studies/trader_data/tests', '-t', '.'])]
    results = {}
    for name, args in suites:
        path = WORK/f'test_{name}.log'
        with path.open('w') as stream:
            result = subprocess.run([sys.executable, '-m', 'unittest', *args], stdout=stream, stderr=subprocess.STDOUT)
        results[name] = dict(ok=result.returncode == 0, returncode=result.returncode,
                             log=str(path.relative_to(ROOT)), summary=path.read_text().splitlines()[-5:])
        results[name]['peak_child_rss_mib'] = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss/1024
        write(WORK.parent/'e1_checks.json', results)
        progress(f'{name} tests: '+('passed' if result.returncode == 0 else 'failed'))
    if not all(r['ok'] for r in results.values()):
        raise SystemExit('required tests failed; see e1_checks.json')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('stage', choices=('train', 'validate', 'three', 'checks'))
    args = parser.parse_args()
    # Gitleaks' Go runtime reserves a large virtual arena while using little resident memory. The research
    # processes retain their hard address-space cap; test subprocesses report their actual resident peak.
    if args.stage != 'checks':
        resource.setrlimit(resource.RLIMIT_AS, (1_500_000_000, 1_500_000_000))
    WORK.mkdir(exist_ok=True)
    {'train': train, 'validate': validate, 'three': three, 'checks': checks}[args.stage]()
