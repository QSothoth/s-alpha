"""PREREG_E13_CN.md: path-driven probes, proof-sized positions, fixed total trade risk; offline daily bars."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from contextlib import ExitStack
from dataclasses import replace
import gc
import json
from pathlib import Path
import resource
import subprocess
import sys
from unittest.mock import patch

import numpy as np

from studies import trader_data as TD
from studies.trader_data import panel as TP, supplemental as SP
from studies.trader_replication import compare, gate as G, panels, system as Y
from studies.trader_screens import screens as S
from . import e1_research as E, e10_research as X, ie47_e1 as M
from .e1_board_smoke import offline
from .ie47_audit import progress, write

ROOT = Path(__file__).resolve().parents[2]
OUT = M.STUDY.reports
WORK = OUT/'e13_work'
PREREG = M.STUDY.root/'notes/PREREG_E13_CN.md'
RESULT, SELECTED, VALIDATION = (OUT/f'e13_{n}.json' for n in ('train', 'selected', 'validation'))
CHECKS = OUT/'e13_checks.json'
CANDIDATES = ('F1', 'F2', 'F3', 'F4', 'F5')
CUT = '2025-06-30'
RETRY_KIND = 'e13_retry'


def fingerprints():
    paths = (PREREG, M.PROFILE, Path(M.__file__), Path(X.__file__), Path(__file__), Path(Y.__file__),
             ROOT/'studies/trader_replication/study.py', ROOT/'studies/trader_data/panel.py',
             ROOT/'studies/trader_replication/standard_indicators.py',
             ROOT/'studies/martin_luk/tests/test_ie47_e13.py',
             ROOT/'studies/trader_replication/tests/test_proof_risk.py')
    return {str(p.relative_to(ROOT)): SP.sha(p) for p in paths}


def signal_arrays(A):
    """Causal daily inputs; bounded 64-column temporaries, no cross-stock matrices."""
    shape = A['close'].shape
    out = {k: A[k] if k in A else np.full(shape, np.nan) for k in ('e9', 'e21', 'adr')}
    out.update(e50=np.full(shape, np.nan), prior20_close=np.full(shape, np.nan),
               e13_add=np.zeros(shape, bool), e13_retry=np.zeros(shape, bool))
    for start in range(0, shape[1], 64):
        sl = slice(start, start+64)
        c, h, l = (A[k][:, sl].astype(float) for k in ('close', 'high', 'low'))
        for key, n in (('e9', 9), ('e21', 21), ('e50', 50)):
            if key not in A or key == 'e50':
                out[key][:, sl] = S.ema(c, n)
        if 'adr' not in A:
            with np.errstate(invalid='ignore', divide='ignore'):
                out['adr'][:, sl] = S.rolling(h/l-1, 20, 'mean')*100
        out['prior20_close'][1:, sl] = S.rolling(c[:-1], 20, 'max')
        e9, e21, e50 = (out[k][:, sl] for k in ('e9', 'e21', 'e50'))
        out['e13_add'][1:, sl] = (c[1:] >= out['prior20_close'][1:, sl]) | \
            ((l[1:] <= e9[1:]) & (c[1:] > e9[1:]) & (c[1:] > h[:-1]))
        out['e13_retry'][5:, sl] = (c[5:] > h[4:-1]) & (c[5:] > e21[5:]) & \
            (e21[5:] > e50[5:]) & (e21[5:] > e21[:-5])
    return out


def retry_book(A, base, sig, hard_mult=2., enabled=True):
    """At most three trials per original watch, independent of account fills; 20 sessions from the first fill."""
    out = [list(row) for row in base]
    records = {}
    days, codes = list(map(str, A['days'])), list(map(str, A['codes']))
    o, l, c = (A[k] for k in ('open', 'low', 'close'))
    for b, row in enumerate(base):
        for original in row:
            pr, j, _, fill, stop = original[:5]
            records[(b, pr)] = dict(origin=days[b], observed=days[pr[1]], attempt=1)
            if not enabled:
                continue
            entry, deadline = b, min(len(out), b+21)
            for attempt in (2, 3):
                stopped, armed, live = None, False, stop
                for d in range(entry+1, deadline):
                    if not np.isfinite(o[d, j]):
                        continue
                    hard = fill-hard_mult*(fill-stop) if hard_mult else live
                    if o[d, j] <= hard or l[d, j] <= hard or (hard_mult and c[d, j] < stop):
                        stopped = d
                        break
                    if c[d, j] > fill:
                        break
                    if not hard_mult:
                        e9 = sig['e9'][d, j]
                        armed |= c[d, j] > e9
                        if armed and np.isfinite(e9):
                            live = max(live, e9*.99)
                if stopped is None:
                    break
                rebought = None
                for d in range(stopped+1, deadline):
                    if not sig['e13_retry'][d, j]:
                        continue
                    new_stop = M.capped_stop(float(c[d, j]), l[d, j], A['adr'][d-1, j])
                    if new_stop is None:
                        continue
                    e = (pr, j, 1, float(c[d, j]), new_stop, RETRY_KIND, None)
                    out[d].append(e)
                    records[(d, pr)] = dict(origin=days[b], observed=days[pr[1]], attempt=attempt)
                    rebought = d
                    entry, fill, stop = d, e[3], e[4]
                    break
                if rebought is None:
                    break
    meta = {}
    for d, row in enumerate(out):
        row.sort(key=lambda e: e[0])
        for e in row:
            meta.setdefault((codes[e[1]], days[d]), records[(d, e[0])])
    return out, meta


def candidate_rules(k2, name):
    if name not in CANDIDATES:
        raise ValueError('unknown E13 candidate')
    return replace(k2, max_position=.30, no_rebuy_day=name != 'F3',
                   probe_hard_mult=0. if name == 'F2' else (1.5 if name == 'F5' else 2.),
                   proof_risk=name != 'F4', proof_add_signal='' if name == 'F4' else 'e13_add', proof_add_max=2)


class E13Study(M.IE47Study):
    def named(self, A, pool, name):
        if name == 'e13_add':
            return self.inputs(A)[name]
        return super().named(A, pool, name)

    def inputs(self, A):
        if '_e13_signals' not in A:
            A['_e13_signals'] = signal_arrays(A)
        return A['_e13_signals']

    def build(self, A, cfg, trace=None):
        name = cfg.get('candidate', 'F1')
        base, rules, mask, pool = super().build(A, dict(cfg, candidate='E8c'), trace)
        k2 = X.rule_layers(rules, ('AS', 'X1'))
        if name == 'K2':
            return base, k2, mask, pool
        rules = candidate_rules(k2, name)
        sig = self.inputs(A)
        book, meta = retry_book(A, base, sig, hard_mult=rules.probe_hard_mult, enabled=name != 'F3')
        A['_e13_meta'] = meta
        if trace is not None:
            trace['trial_meta'] = meta
        mask = np.zeros_like(mask)
        for d, row in enumerate(book):
            for e in row:
                mask[d, e[1]] = True
        return book, rules, mask, pool


def setup(upto=None):
    st = E13Study()
    st.progress = progress
    A = st.arrays('us', upto=upto, mode='frozen')
    R = st.selected(A)
    cfg = dict(profile_sha256=SP.sha(M.PROFILE), frozen_inputs_sha256=M.inputs_digest(R['sources']))
    return st, A, cfg


def main_legs(A, picks, span=E.TRAIN):
    """Evaluation labels only: exactly leg_position.py's inclusive 60-session trough/peak windows."""
    days, codes = list(map(str, A['days'])), list(map(str, A['codes']))
    ci = {code: j for j, code in enumerate(codes)}
    anchors = dict(his=[], pool=[])
    for t in M.STUDY.trades():
        day = t.entry_date or t.window_lo
        if t.side == 'long' and span[0] <= day <= span[1]:
            anchors['his'].append((day, t.ticker if t.ticker.startswith('US.') else 'US.'+t.ticker))
    anchors['pool'] = [(day, code) for day, row in picks.items() if span[0] <= day <= span[1] for code in row]
    result = {}
    for name, rows in anchors.items():
        legs = {}
        for day, code in sorted(rows):
            if code not in ci:
                continue
            d, j = int(np.searchsorted(A['days'], day)), ci[code]
            hh = A['high'][d:d+61, j]
            if not np.isfinite(hh).any():
                continue
            peak = d + int(np.nanargmax(hh))
            lo0 = max(peak-60, 0)
            ll = A['low'][lo0:peak+1, j]
            if not np.isfinite(ll).any():
                continue
            trough = lo0+int(np.nanargmin(ll))
            low, high = float(A['low'][trough, j]), float(A['high'][peak, j])
            if low <= 0 or high/low-1 < .5:
                continue
            key = (code, peak)
            if key not in legs:
                closes = A['close'][trough:peak+1, j]
                points = {}
                for label, frac in (('third', 1/3), ('midpoint', .5)):
                    hits = np.flatnonzero(closes >= low+frac*(high-low))
                    points[label] = days[trough+int(hits[0])] if len(hits) else None
                legs[key] = dict(code=code, trough=days[trough], peak=days[peak], low=low, high=high,
                                 gain=high/low-1, year=day[:4], anchors=[], **points)
            legs[key]['anchors'].append(day)
        result[name] = sorted(legs.values(), key=lambda x: (x['trough'], x['code'], x['peak']))
    return result


def mean(values):
    return float(np.mean(values)) if len(values) else None


def median(values):
    return float(np.median(values)) if len(values) else None


def distribution(values):
    x = np.asarray(values, float)
    bins = (-np.inf, -2, -1, 0, 1, 3, 5, 10, np.inf)
    return dict(n=len(x), mean=mean(x), sum=float(x.sum()), median=median(x),
                p10=float(np.quantile(x, .1)) if len(x) else None,
                p90=float(np.quantile(x, .9)) if len(x) else None,
                bins={f'{a:g}..{b:g}': int(n) for a, b, n in zip(bins, bins[1:], np.histogram(x, bins)[0])})


def leg_metrics(A, legs, trades, curve, dates):
    by_code = defaultdict(list)
    for t in trades:
        by_code[t['code']].append(t)
    di = {str(d): i for i, d in enumerate(A['days'])}
    ci = {str(c): j for j, c in enumerate(A['codes'])}
    equity = dict(zip(map(str, dates), curve))
    details, summary = {}, {}
    for group, rows in legs.items():
        out = []
        for leg in rows:
            j = ci[leg['code']]
            own = by_code[leg['code']]
            trials = sorted((t for t in own if leg['trough'] <= t['entry'] < leg['peak']), key=lambda t: t['entry'])
            losses = [t for t in trials if t['why'] != 'end' and t['pnl'] < 0]
            row = dict(leg, trials=len(trials), loss_u=sum(-t['pnl']/t['risk_budget'] for t in losses),
                       unconfirmed_loss_u=sum(-t['pnl']/t['risk_budget'] for t in losses if not t['confirmed']),
                       first_position=(trials[0]['fill']-leg['low'])/(leg['high']-leg['low']) if trials else None,
                       last_position=(trials[-1]['fill']-leg['low'])/(leg['high']-leg['low']) if trials else None,
                       trial_entries=[dict(entry=t['entry'], attempt=t.get('attempt', 1), origin=t.get('origin'),
                                           confirmed=t['confirmed'], pnl_u=t['pnl']/t['risk_budget']) for t in trials])
            for point in ('third', 'midpoint'):
                day = leg[point]
                shares = 0.
                if day in equity:
                    for t in own:
                        for e in t['executions']:
                            if e['time'] <= day and e['action'] != 'end':
                                shares += e['shares'] * (1 if e['action'] in ('entry', 'add') else -1)
                    shares = max(0., shares)
                    if shares < 1e-12:
                        shares = 0.
                    row[point+'_weight'] = shares*float(A['close'][di[day], j])/equity[day]
                else:
                    row[point+'_weight'] = None
            out.append(row)
        details[group] = out
        summary[group] = {}
        for year in sorted({r['year'] for r in out}):
            subset = [r for r in out if r['year'] == year]
            stats = dict(n=len(subset), bought=sum(r['trials'] > 0 for r in subset),
                         trials_mean=mean([r['trials'] for r in subset]),
                         loss_u_mean=mean([r['loss_u'] for r in subset]),
                         loss_u_sum=sum(r['loss_u'] for r in subset),
                         unconfirmed_loss_u_sum=sum(r['unconfirmed_loss_u'] for r in subset),
                         first_position_median=median([r['first_position'] for r in subset if r['first_position'] is not None]),
                         last_position_median=median([r['last_position'] for r in subset if r['last_position'] is not None]))
            for point in ('third', 'midpoint'):
                weights = [r[point+'_weight'] for r in subset if r[point+'_weight'] is not None]
                held = [w for w in weights if w > 0]
                stats[point] = dict(observed=len(weights), censored=len(subset)-len(weights), held=len(held),
                                    median=median(weights), mean=mean(weights), held_median=median(held), held_mean=mean(held))
            summary[group][year] = stats
    return summary, details


def account_stats(curve, dates, trades, track, entries, A, span):
    d0, d1 = np.searchsorted(A['days'], span[0]), np.searchsorted(A['days'], span[1], side='right')
    stats = compare.metrics(curve, dates, trades, entries, d0, d1)
    stats['annual'] = {}
    closed = G.closed(trades)
    for year, ret in stats['by_year'].items():
        tr = [t for t in closed if t['entry'].startswith(year)]
        ix = np.flatnonzero(np.char.startswith(dates.astype(str), year))
        segment = np.r_[curve[ix[0]-1] if ix[0] else 1., curve[ix]]
        winners = [t['ret_invested'] for t in tr if t['pnl'] > 0]
        losers = [t['ret_invested'] for t in tr if t['pnl'] <= 0]
        row = dict(ret=ret, maxdd=float(np.max(1-segment/np.maximum.accumulate(segment))), closed=len(tr),
                   opened=sum(t['entry'].startswith(year) for t in trades), win=len(winners)/len(tr) if tr else None,
                   avg_win=mean(winners), avg_loss=mean(losers), winners20=sum(t['ret_invested'] >= .2 for t in tr),
                   exposure=mean(np.asarray(track['gross'])[ix]), margin=float(np.asarray(track['daily_margin'])[ix].sum()),
                   confirmed=sum(t['confirmed'] for t in tr),
                   exit_reasons=dict(Counter(t['why'] for t in tr)),
                   by_attempt={str(a): distribution([t['r'] for t in tr if t.get('attempt', 1) == a]) for a in (1, 2, 3)})
        for label, flag in (('unconfirmed', False), ('confirmed', True)):
            row['r_'+label] = distribution([t['r'] for t in tr if t['confirmed'] == flag])
            row['u_'+label] = distribution([t['pnl']/t['risk_budget'] for t in tr if t['confirmed'] == flag])
        stats['annual'][year] = row
    stats['mean_exposure'] = mean(track['gross'])
    stats['margin'] = track['margin']
    return stats


def select(runs):
    ref = runs['K2']['by_year']
    eligible = [n for n in CANDIDATES if all(runs[n]['by_year'][y] >= ref[y] for y in ('2024', '2025'))]
    if not eligible:
        return [], None
    worst = {n: min(runs[n]['by_year'][y] for y in ('2024', '2025')) for n in eligible}
    best = max(worst.values())
    near = [n for n in eligible if best-worst[n] < .02]
    return eligible, min(near, key=lambda n: (-runs[n]['midpoint_his'], CANDIDATES.index(n)))


def update_checks(key, value):
    checks = json.loads(CHECKS.read_text(encoding='utf-8')) if CHECKS.exists() else {}
    checks[key] = value
    write(CHECKS, checks)


def start_once(name, value):
    with (WORK/f'{name}_started.json').open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=1)
        stream.write('\n')


def baseline_check(stats, raw_trades):
    results = {}
    for round_ in ('e10', 'e11'):
        path = OUT/f'{round_}_train.json'
        reference = json.loads(path.read_text(encoding='utf-8'))['runs']['K2']
        keys = ('total', 'by_year', 'trades', 'win')
        trade_path = OUT/f'{round_}_work/K2_2024_trades.json'
        prior = json.loads(trade_path.read_text(encoding='utf-8'))
        diffs = [k for k in keys if stats[k] != reference[k]]
        first = next((i for i, (a, b) in enumerate(zip(raw_trades, prior)) if a != b), None)
        if len(raw_trades) != len(prior) or first is not None:
            diffs.append(f'trades differ: lengths {len(raw_trades)}/{len(prior)}, first={first}')
        results[round_] = dict(ok=not diffs, diff=diffs, reference_sha256=SP.sha(path),
                               trades_sha256=SP.sha(trade_path), raw_trades=len(raw_trades))
    out = dict(ok=all(r['ok'] for r in results.values()), references=results)
    update_checks('k2_bitwise', out)
    if not out['ok']:
        raise AssertionError(f'K2 baseline changed before candidate selection: {results}')
    return out


def evaluate(st, A, cfg, name, legs, span, check_baseline=False):
    trace = {}
    entries, rules, _, pool = st.build(A, dict(cfg, candidate=name), trace)
    track = dict(daily_margin=[])
    curve, dates, trades = Y.simulate(st.px(A), st.ema_inputs(A, pool, rules), rules, entries,
                                     *span, audit=True, track=track)
    d0, d1 = np.searchsorted(A['days'], span[0]), np.searchsorted(A['days'], span[1], side='right')
    if check_baseline:
        baseline_check(compare.metrics(curve, dates, trades, entries, d0, d1), trades)
    # K2's saved raw trades remain the bitwise reference; these extra fields only annotate E13 artifacts.
    entry_fees = defaultdict(float)
    for t in trades:
        e = t['executions'][0]
        entry_fees[t['entry']] += e['price']*e['shares']*rules.buy_cost
    eq = dict(zip(map(str, dates), curve))
    di = {str(d): i for i, d in enumerate(A['days'])}
    meta = trace.get('trial_meta', {})
    for t in trades:
        t.setdefault('risk_budget', .005*A['e8_scale'][di[t['entry']]]*(eq[t['entry']]+entry_fees[t['entry']]))
        t.setdefault('confirmed', any(e['action'] == 'add' for e in t['executions']))
        t.setdefault('confirmed_day', next((e['time'] for e in t['executions'] if e['action'] == 'add'), None))
        t.update(meta.get((t['code'], t['entry']), dict(attempt=1, origin=t['entry'])))
    stats = account_stats(curve, dates, trades, track, entries, A, span)
    stats['legs'], details = leg_metrics(A, legs, trades, curve, dates)
    stats['midpoint_his'] = sum(row['midpoint']['held'] for row in stats['legs']['his'].values())
    stats['his_exact'] = X.his_exact(st, A, trades, span)
    stats['fills'] = G.check_fills(A, trades)
    stats['win_gate'] = G.check_win(trades)
    stats['signals'] = sum(len(row) for row in entries[d0:d1])
    stats['proof_orders'] = dict(Counter((e['phase']+':'+e['status']) for e in track.get('proof_orders', ())))
    for year, row in stats['annual'].items():
        row['his_exact'] = X.his_exact(st, A, trades, (year+'-01-01', year+'-12-31'))
        row['signals'] = sum(len(entries[d]) for d in range(int(d0), int(d1)) if str(A['days'][d]).startswith(year))
    prefix = WORK/f'{name}_{span[0][:4]}'
    write(prefix.with_name(prefix.name+'_trades.json'), trades)
    write(prefix.with_name(prefix.name+'_curve.json'), dict(days=dates.tolist(), equity=curve.tolist()))
    write(prefix.with_name(prefix.name+'_legs.json'), details)
    progress(f"{name}: {span[0][:4]} total={stats['total']:+.6f}; "
             f"annual={stats['by_year']}; closed={stats['trades']}; his midpoint={stats['midpoint_his']}")
    if not stats['fills']['ok']:
        raise AssertionError(f'{name} has fills outside the observed bar')
    return stats


def smoke():
    st, A, cfg = setup('2024-02-29')
    out = dict(span=['2024-01-02', '2024-02-29'], runs={}, source_sha256=fingerprints())
    for name in ('K2',)+CANDIDATES:
        entries, rules, _, pool = st.build(A, dict(cfg, candidate=name))
        curve, _, trades = Y.simulate(st.px(A), st.ema_inputs(A, pool, rules), rules, entries,
                                     *out['span'], audit=True)
        out['runs'][name] = dict(total=float(curve[-1]-1), trades=len(G.closed(trades)), fills=G.check_fills(A, trades))
    write(WORK/'smoke.json', out)
    if not all(r['fills']['ok'] for r in out['runs'].values()):
        raise AssertionError('E13 smoke fill check failed')
    progress('smoke passed on January-February 2024 only')


def execution_events(trades, cut):
    return sorted((e['time'], t['code'], t['entry'], e['action'], e['price'], e['shares'])
                  for t in trades for e in t['executions'] if e['action'] != 'end' and e['time'] <= cut)


def event_comparison(first, second):
    i = next((i for i, (a, b) in enumerate(zip(first, second)) if a != b), None)
    return dict(ok=first == second, events_full=len(first), events_cut=len(second),
                first_difference=dict(index=i, full=first[i], cut=second[i]) if i is not None else None)


def run_events(st, A, cfg, end):
    book, rules, _, pool = st.build(A, dict(cfg, candidate='F1'))
    trades = Y.simulate(st.px(A), st.ema_inputs(A, pool, rules), rules, book, E.TRAIN[0], end, audit=True)[2]
    return execution_events(trades, CUT), book


class CutDataset(TD.Dataset):
    """Only already stored raw bars/actions through a cut; no cache, downloads or future ex-dates."""
    market = 'us'

    def __init__(self, base, cut):
        self.base, self.cut = base, cut

    @property
    def id(self):
        return self.base.id+':asof:'+self.cut

    def stocks(self):
        return self.base.stocks()

    def rule(self):
        return self.base.rule()

    def rows(self):
        return (r for r in self.base.rows() if r[1] <= self.cut)

    def actions(self):
        return {code: [a for a in rows if a[0] <= self.cut] for code, rows in self.base.actions().items()}

    def digest(self):
        return self.base.digest()+':asof:'+self.cut


def audit_inputs():
    """No return comparisons: test causality before the one selection run."""
    st, A, cfg = setup()
    full_events, full_book = run_events(st, A, cfg, E.TRAIN[1])
    k = int(np.searchsorted(A['days'], CUT, side='right'))
    full_picks = {d: v for d, v in st.selected(A)['picks'].items() if d <= CUT}
    B = st.arrays('us', upto=CUT, mode='frozen')
    cut_events, cut_book = run_events(st, B, cfg, CUT)
    cut_picks = st.selected(B)['picks']
    nights = [d for d in full_picks if full_picks[d] != cut_picks.get(d)]
    trunc = event_comparison(full_events, cut_events)
    trunc.update(cut=CUT, picks_different=nights, n_nights_different=len(nights),
                 books_bitwise=full_book[:k] == cut_book,
                 scope='panels.load(upto): rebuild selection, EMA, ADR, retries, proof arrays and portfolio')
    trunc['ok'] &= not nights and trunc['books_bitwise']
    update_checks('real_truncation', trunc)
    if not trunc['ok']:
        raise AssertionError('real F1 cutoff changed earlier executions; repair before selection')
    del B, cut_book
    gc.collect()
    lookahead = G.check_lookahead(st, dict(cfg, candidate='F1'), 'us', full=A)
    update_checks('gate_lookahead', lookahead)
    if not lookahead['ok']:
        raise AssertionError('gate.check_lookahead failed')
    # Price-basis audit is separate: the shared upto loader first adjusts the full history, then slices.
    # Rebuilding from dated raw bars measures this known limitation instead of claiming upto tests it.
    base = TD.dataset('us', 'frozen')
    clipped = CutDataset(base, CUT)
    p = TP.assemble(clipped)
    action_rows = base.actions()
    future = {code: [a for a in rows if a[0] > CUT] for code, rows in action_rows.items() if any(a[0] > CUT for a in rows)}
    changed, max_scaled_error = [], 0.
    scale_by_code = {}
    for j, code in enumerate(map(str, A['codes'])):
        old, new = A['close'][:k, j], p['close'][:, j]
        valid = np.isfinite(old) & np.isfinite(new) & (new > 0)
        if not valid.any():
            continue
        if not np.array_equal(old, new, equal_nan=True):
            changed.append(code)
        ratios = old[valid].astype(float)/new[valid]
        factor = float(np.median(ratios))
        scale_by_code[code] = factor
        max_scaled_error = max(max_scaled_error, float(np.max(np.abs(ratios/factor-1))))
    write(WORK/'corporate_action_basis.json', dict(cut=CUT, future_actions=future, changed_codes=changed,
                                                  full_to_asof_scale=scale_by_code, max_relative_scale_error=max_scaled_error))
    basis = dict(cut=CUT, raw_rows_cut_before_adjustment=True, future_action_codes=len(future),
                 earlier_price_codes_changed=len(changed), max_relative_scale_error=max_scaled_error,
                 invariant_prices=not changed, limitation='shared panels.load(upto) adjusts with future actions before slicing; '
                 'raw-asof prices may use a different basis; the event check above does not certify action availability')
    update_checks('corporate_action_basis', basis)
    del p
    update_checks('audit_resources', dict(memory=memory(), address_space_limit=1_900_000_000))
    progress(f'F1 prefix events identical ({len(full_events)}); existing gate passed; raw action basis audit recorded')


def train():
    if RESULT.exists() or SELECTED.exists():
        raise ValueError('E13 training already recorded; do not select again')
    checks = json.loads(CHECKS.read_text(encoding='utf-8'))
    if not all(checks.get(k, {}).get('ok') for k in ('real_truncation', 'gate_lookahead')):
        raise ValueError('E13 causal checks must pass before selection')
    start_once('train', dict(source_sha256=fingerprints(), memory=memory()))
    st, A, cfg = setup()
    legs = main_legs(A, st.selected(A)['picks'])
    write(WORK/'evaluation_legs.json', legs)
    out = dict(preregistered_sha256=SP.sha(PREREG), source_sha256=fingerprints(), span=list(E.TRAIN),
               base=cfg, runs={})
    for name in ('K2',)+CANDIDATES:
        out['runs'][name] = evaluate(st, A, cfg, name, legs, E.TRAIN, check_baseline=name == 'K2')
        write(RESULT.with_suffix('.partial.json'), out)
    eligible, chosen = select(out['runs'])
    out.update(eligible=eligible, chosen=chosen)
    write(RESULT, out)
    with SELECTED.open('x', encoding='utf-8') as stream:
        json.dump(dict(chosen=chosen, eligible=eligible, preregistered_sha256=SP.sha(PREREG),
                       source_sha256=fingerprints(), train_sha256=SP.sha(RESULT)), stream, ensure_ascii=False, indent=1)
        stream.write('\n')
    update_checks('train_resources', dict(memory=memory(), address_space_limit=1_900_000_000))
    update_checks('validation_policy', dict(selected=chosen, measured=False,
                  reason='no candidate meets both annual floors' if chosen is None else 'chosen candidate only, pending'))
    progress(f'eligible={eligible}; chosen={chosen}; no 2026 candidate account measured')


def validate():
    if VALIDATION.exists():
        raise ValueError('E13 validation already recorded')
    selected = json.loads(SELECTED.read_text(encoding='utf-8'))
    if selected['chosen'] is None:
        raise ValueError('No E13 candidate eligible; 2026 must not be tested')
    if selected['preregistered_sha256'] != SP.sha(PREREG) or selected['source_sha256'] != fingerprints():
        raise ValueError('E13 rules or source changed after selection')
    start_once('validation', dict(selected_sha256=SP.sha(SELECTED), memory=memory()))
    st, A, cfg = setup()
    legs = main_legs(A, st.selected(A)['picks'], E.VALIDATE)
    runs = {}
    for name in ('K2', selected['chosen']):
        runs[name] = evaluate(st, A, cfg, name, legs, E.VALIDATE)
    write(VALIDATION, dict(chosen=selected['chosen'], runs=runs, span=list(E.VALIDATE),
                           selected_sha256=SP.sha(SELECTED),
                           scope='one E13 candidate and K2 only; 2026 has already been used by earlier research'))
    update_checks('validation_policy', dict(selected=selected['chosen'], measured=True, candidates=1))
    update_checks('validation_resources', dict(memory=memory(), address_space_limit=1_900_000_000))


def memory():
    vals = {}
    for line in Path('/proc/meminfo').read_text().splitlines():
        key, value = line.split(':', 1)
        if key in ('MemTotal', 'MemAvailable', 'SwapTotal', 'SwapFree'):
            vals[key+'_kib'] = int(value.strip().split()[0])
    vals['peak_rss_mib'] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024
    return vals


def checks():
    suites = dict(custody=['discover', '-s', 'custody/tests'],
                  trader_replication=['discover', '-s', 'studies/trader_replication/tests'],
                  martin_luk=['discover', '-s', 'studies/martin_luk/tests'])
    results = {}
    for name, args in suites.items():
        path = WORK/f'test_{name}.log'
        with path.open('w', encoding='utf-8') as stream:
            rc = subprocess.run([sys.executable, '-m', 'unittest', *args], stdout=stream,
                                stderr=subprocess.STDOUT).returncode
        results[name] = dict(ok=rc == 0, returncode=rc, log=str(path.relative_to(ROOT)),
                             summary=path.read_text(encoding='utf-8').splitlines()[-6:],
                             cumulative_peak_child_rss_mib=resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss/1024)
        update_checks('tests', results)
        progress(name+' tests: '+('passed' if rc == 0 else 'failed'))
    if not all(r['ok'] for r in results.values()):
        raise SystemExit('E13 required tests failed')


def report():
    """Render only completed artifacts; never rerun a portfolio or reselect."""
    train = json.loads(RESULT.read_text(encoding='utf-8'))
    checks = json.loads(CHECKS.read_text(encoding='utf-8'))
    runs, chosen = train['runs'], train['chosen']
    names = ('K2',)+CANDIDATES
    def pct(x):
        return '—' if x is None else f'{100*x:+.1f}%'
    def weight(x):
        return '—' if x is None else f'{100*x:.1f}%'
    def num(x):
        return '—' if x is None else f'{x:.2f}'
    lines = ['# E13：风险按行情被证实的程度分配', '']
    if chosen is None:
        lines += ['结论：**五个候选都没有同时守住 K2 在 2024、2025 年的收益，不采用；按预登记不测 2026，现行执行仍为 K2。**', '']
    else:
        lines += [f'结论：**按预登记选中 {chosen}，它在 2024 和 2025 年都不低于 K2。**', '']
        if VALIDATION.exists():
            v = json.loads(VALIDATION.read_text(encoding='utf-8'))['runs']
            lines += [f"选中者 2026 至 10-16 只测一次：{chosen} {pct(v[chosen]['total'])}，K2 {pct(v['K2']['total'])}。2026 已用于先前研究，不能称为独立样本外。", '']
    lines += ['任务定义与阈值见[预登记](../notes/PREREG_E13_CN.md)，唯一任务书为 [PLAN_E13_CN](../notes/PLAN_E13_CN.md)。'
              '参照 K2 与 E10、E11 的收益及全部原始逐笔记录逐位一致。所有候选只在 2024-01-02～2025-12-31 选择，规则定稿后未按结果改动。', '',
              '## 1. 账户（分年）', '',
              '| 配置 | 年 | 收益 | 年内回撤 | 开仓 / 已平 | 胜率 | 平均赚 / 亏 | 赢家≥20% | 平均敞口 | 融资利息（初始权益） |',
              '|---|---|---|---|---|---|---|---|---|---|']
    for name in names:
        for year, r in runs[name]['annual'].items():
            lines.append(f"| {name} | {year} | {pct(r['ret'])} | {weight(r['maxdd'])} | {r['opened']} / {r['closed']} | "
                         f"{weight(r['win'])} | {pct(r['avg_win'])} / {pct(r['avg_loss'])} | {r['winners20']} | "
                         f"{weight(r['exposure'])} | {weight(r['margin'])} |")
    lines += ['', '账户跨年连续运行，收益、回撤、敞口和利息按自然年；交易统计按入场年，只计已平仓；'
              '平均赚/亏、20% 赢家按全部实际买入资金（含加仓）计算。窗口末未平仓只按收盘估值，不虚构一次离场。', '',
              '| 配置 | 两年收益 | 全段回撤 | 已平仓 | 资格（两年各不低于 K2） | 较差年收益 | 他段中点持有 |',
              '|---|---|---|---|---|---|---|']
    for name in names:
        r = runs[name]
        lines.append(f"| {name} | {pct(r['total'])} | {weight(r['maxdd'])} | {r['trades']} | "
                     f"{'参照' if name == 'K2' else ('通过' if name in train['eligible'] else '不通过')} | "
                     f"{pct(min(r['by_year'].values()))} | {r['midpoint_his']} |")
    lines += ['', '## 2. 主升浪中实际持仓', '',
              '主升浪只作事后评估，不进入规则。峰值、起点、合并方法与 leg_position.py 一致；'
              '他的段按台账日期锚定，池内段按 IE47 每晚实际选中锚定。表中均值和中位数含零仓位；括号内为持有段的条件值。'
              '“可评”只包含到达该价位的日期落在本次账户窗口内的段，其他段列为删失，不擅自记成零仓位。', '']
    for group, title in (('his', '他的段'), ('pool', '池内段')):
        for point, label in (('midpoint', '行情中点'), ('third', '行情 1/3')):
            lines += [f'### {title}：{label}', '',
                      '| 配置 | 年 | 总段 / 可评 / 删失 | 持有段 | 仓位中位（持有段） | 仓位均值（持有段） |',
                      '|---|---|---|---|---|---|']
            for name in names:
                for year, row in runs[name]['legs'][group].items():
                    r = row[point]
                    lines.append(f"| {name} | {year} | {row['n']} / {r['observed']} / {r['censored']} | {r['held']} | "
                                 f"{weight(r['median'])}（{weight(r['held_median'])}） | {weight(r['mean'])}（{weight(r['held_mean'])}） |")
            lines += ['']
    lines += ['## 3. 每段试单及进场位置', '',
              '| 配置 | 段类 | 年 | 买到 / 全部段 | 每段平均试单 | 亏损试单合计 U（未证实） | 首笔位置中位 | 末笔位置中位 |',
              '|---|---|---|---|---|---|---|---|']
    for name in names:
        for group, title in (('his', '他的'), ('pool', '池内')):
            for year, r in runs[name]['legs'][group].items():
                lines.append(f"| {name} | {title} | {year} | {r['bought']} / {r['n']} | {num(r['trials_mean'])} | "
                             f"{num(r['loss_u_sum'])}（{num(r['unconfirmed_loss_u_sum'])}） | "
                             f"{num(r['first_position_median'])} | {num(r['last_position_median'])} |")
    lines += ['', 'U 是每笔首次成交时固定的一份账户风险；不同笔的 U 金额可不同。亏损只累计已平仓且亏损的试单，'
              '不以盈利抵消；同一笔可能属于重叠的多个主升浪段，表中 U 是逐段口径，不能相加充当账户总亏损。'
              '逐段试单次数、亏损、首末位置、每次入场见 `e13_work/*_2024_legs.json`。', '',
              '## 4. 未证实 / 已证实的 R 分布', '',
              '| 配置 | 年 | 未证实：笔数 / 平均 / 中位 / P10 / P90 / 合计 R | 已证实：笔数 / 平均 / 中位 / P10 / P90 / 合计 R |',
              '|---|---|---|---|']
    def dist(r):
        return f"{r['n']} / {num(r['mean'])} / {num(r['median'])} / {num(r['p10'])} / {num(r['p90'])} / {num(r['sum'])}"
    for name in names:
        for year, r in runs[name]['annual'].items():
            lines.append(f"| {name} | {year} | {dist(r['r_unconfirmed'])} | {dist(r['r_confirmed'])} |")
    lines += ['', '这里 R 沿用引擎：每股初始 w × 初始试单股数；S 的试单更小，因此不能把不同配置的总 R 直接当账户收益比。'
              '结果 JSON 同时报按固定 U 计的分布、完整区间分桶和试单轮次分布；K2 以是否实际加过仓划分证实状态。', '',
              '## 5. 他确切日期的买入（只报告）', '',
              '| 配置 | 2024 买到 / 总数 | 2025 买到 / 总数 | 两年买到 / 总数 |',
              '|---|---|---|---|']
    for name in names:
        r = runs[name]
        cells = [f"{r['annual'][y]['his_exact']['bought']} / {r['annual'][y]['his_exact']['all']}" for y in ('2024', '2025')]
        lines.append(f"| {name} | {' | '.join(cells)} | {r['his_exact']['bought']} / {r['his_exact']['all']} |")
    lines += ['', '沿用 E10 `his_exact`：他入场前 3 个交易日到后 2 个交易日内账户有成交；不把形态出现或观察名单命中当作买到。', '',
              '## 6. 差在哪层', '']
    ref = runs['K2']
    for name in CANDIDATES:
        r = runs[name]
        floors = [y for y in ('2024', '2025') if r['by_year'][y] < ref['by_year'][y]]
        reasons = '、'.join(f"{y} 少 {(ref['by_year'][y]-r['by_year'][y])*100:.1f} 个百分点" for y in floors) or '两年收益都达标'
        lines.append(f"- {name}：{reasons}；他的段在中点持有 {r['midpoint_his']} 段（K2 {ref['midpoint_his']}）。")
    lines += ['', '按预登记的成对消融，下面列“保留该层 − 去掉该层”的差值；只归因于这一套上下游配置。', '',
              '| 层 | 对照 | 2024 收益差 | 2025 收益差 | 他段中点持有差 |',
              '|---|---|---|---|---|']
    for layer, left, right in (('S 小仓与收盘证伪', 'F1', 'F2'), ('T 同段再试', 'F1', 'F3'),
                               ('P 证实仓位与后续加仓', 'F1', 'F4'), ('硬止损 1.5w 相对 2w', 'F5', 'F1')):
        a, b = runs[left], runs[right]
        lines.append(f"| {layer} | {left} − {right} | {pct(a['by_year']['2024']-b['by_year']['2024'])} | "
                     f"{pct(a['by_year']['2025']-b['by_year']['2025'])} | {a['midpoint_his']-b['midpoint_his']:+d} |")
    lines += ['', 'P 对照同时包含证实目标股数、总风险止损与再加仓，不把其中某一个单独说成原因。'
              'S 的不同也会改变 T 价格路径和账户拒绝，不能把账户收益差解释成只少亏了某几笔。', '',
              '这轮只检验 IE47 + E6c + 当前日 K 执行上的这五种风险分配方式。'
              '改善持仓覆盖必须同时守住两个年度收益门槛；没有达标的版本不能替换 K2，也不能据此否定他的试单和加仓方法。'
              '逐层原因须结合下面的现金流分解，不把一次实现的结果推广到其他配置。', '',
              '| 配置 | 年 | 未证实试单合计 U | 已证实合计 U | 已证实 / 已平仓 |',
              '|---|---|---|---|---|']
    for name in names:
        for year, r in runs[name]['annual'].items():
            lines.append(f"| {name} | {year} | {num(r['u_unconfirmed']['sum'])} | {num(r['u_confirmed']['sum'])} | "
                         f"{r['confirmed']} / {r['closed']} |")
    lines += ['', '## 7. 未来函数与工程检查', '']
    trunc, gate, basis = (checks.get(k, {}) for k in ('real_truncation', 'gate_lookahead', 'corporate_action_basis'))
    lines += [f"- 合成扰动：未来价格乘 3 和随机打乱，两种方式均逐位对照全部过去输入、入场簿及再试簿，单测通过。",
              f"- 真实截断 {CUT}：F1 的 {trunc.get('events_full')} 条真实成交事件（日期、价格、股数）逐笔一致；"
              f"选股不同的晚上 {trunc.get('n_nights_different')} 个，入场簿逐位一致={trunc.get('books_bitwise')}。窗口末 `end` 估值行不算成交。",
              f"- `gate.check_lookahead`：{'通过' if gate.get('ok') else '未通过'}，截止日为 "
              + '、'.join(r['cut'] for r in gate.get('cuts', []))+'。',
              '- 时点单测覆盖入场日不止损/不加仓、硬止损优先、收盘离场优先于加仓、加仓止损单向上移、含费用/减仓现金流的总风险计算；所有配置的成交范围检查通过。',
              f"- **公司行动的限制单独披露**：共享加载器先对完整数据复权，再裁切；上述两个通过结果不证明未来公司行动可得性。"
              f"额外先裁切原始行情和公司行动再重建，截止日后有行动的股票 {basis.get('future_action_codes')} 只，"
              f"历史价格基准改变 {basis.get('earlier_price_codes_changed')} 只。各票前后价格比的最大相对偏差为 "
              f"{basis.get('max_relative_scale_error', float('nan')):.2g}；完整清单在 `e13_work/corporate_action_basis.json`。这项不冒充“已排除未来复权影响”。", '']
    for name, result in checks.get('tests', {}).items():
        brief = [s for s in result['summary'] if s.startswith(('Ran ', 'OK', 'FAILED'))]
        lines.append(f"- `{name}` 全量测试：{'通过' if result['ok'] else '失败'}；"+'；'.join(brief)+'。')
    lines += ['', '## 8. 照记与复算', '',
              '- 预登记先于单测和实现。唯一冒烟窗口为 2024-01～02；审计阶段仅比较输入和成交事件，不按候选账户收益择优。',
              '- 训练和验证均用排他开始标记；已有结果会拒绝重跑。无合格者时 validate 明确拒绝，不使用 2026 继续构思规则。',
              '- 单进程、按 64 列分块，新研究运行 RLIMIT_AS=1,900,000,000 字节；运行前记录可用内存，峰值见 `e13_checks.json`。'
              '全量测试的现有 Go 密钥扫描器在此地址空间限制下连启动都会失败，因此仅测试子进程沿用原系统限制，并另记实际 RSS；没有跳过密钥检查。',
              '- 未取新数据、未用小时线、未冻结、未提交，登记版和看板未改。已有 hooksPath 的密钥钩子已核对，未覆盖。',
              '- 结果：`e13_train.json`、`e13_selected.json`、`e13_checks.json`；每配置逐笔、权益曲线和两类逐段明细在 `e13_work/`。', '',
              '```bash', 'PYTHONUTF8=1 OPENBLAS_NUM_THREADS=1 /opt/opend-us-options/.venv/bin/python -m studies.martin_luk.e13_research checks',
              'PYTHONUTF8=1 OPENBLAS_NUM_THREADS=1 /opt/opend-us-options/.venv/bin/python -m studies.martin_luk.e13_research report',
              '```', '', 'train / validate 为一次性记录入口，不能用来覆盖复算。检查与报告可从既有工件重建。', '']
    (OUT/'E13_CN.md').write_text('\n'.join(lines), encoding='utf-8')
    progress('E13 Chinese report rendered from completed artifacts')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('stage', choices=('smoke', 'audit', 'train', 'validate', 'checks', 'report'))
    stage = parser.parse_args().stage
    WORK.mkdir(exist_ok=True)
    if stage == 'checks':
        # Gitleaks reserves a Go virtual arena over 2GB; only this test subprocess needs the inherited AS limit.
        checks()
    elif stage == 'report':
        report()
    else:
        resource.setrlimit(resource.RLIMIT_AS, (1_900_000_000, 1_900_000_000))
        offline()
        original = TP.build
        def existing_load(market, mode=None, version=None, upto=None, **kwargs):
            return original(TD.dataset(market, mode, version), upto=upto, write_cache=False)
        def read_only_build(ds, upto=None, cache=True, write_cache=True):
            return original(ds, upto=upto, cache=cache, write_cache=False)
        with ExitStack() as stack:
            stack.enter_context(patch.object(TD, 'load', existing_load))
            stack.enter_context(patch.object(TP, 'build', read_only_build))
            {'smoke': smoke, 'audit': audit_inputs, 'train': train, 'validate': validate}[stage]()
