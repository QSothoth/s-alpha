"""PREREG_E14_CN: twenty one-layer diagnoses, deterministic composition, at most five final candidates."""
from __future__ import annotations

import argparse
from contextlib import ExitStack
from dataclasses import asdict, replace
import gc
import json
import os
from pathlib import Path
import resource
import sys
from types import ModuleType
from unittest.mock import patch

import numpy as np

from . import e13_research as B, ie47_e1 as M
from .ie47_audit import progress

Y, G, E, SP, TD, TP = B.Y, B.G, B.E, B.SP, B.TD, B.TP
ROOT, OUT = B.ROOT, B.OUT
WORK = OUT/'e14_work'
PREREG = M.STUDY.root/'notes/PREREG_E14_CN.md'
RESULT, SELECTED, VALIDATION = (OUT/f'e14_{n}.json' for n in ('train', 'selected', 'validation'))
CHECKS = OUT/'e14_checks.json'
CUT, LIMIT = B.CUT, 1_900_000_000
LAYERS = dict(S=('S15', 'S30', 'SK', 'SC2'), C=('CF', 'CU'), Z=('Z15', 'Z075'),
              A=('A0', 'AE', 'AR', 'A4'), T=('T0', 'T2', 'T5'), H=('H21', 'H21A', 'HN'), M=('M0', 'MD'))
DIAGNOSTICS = ('K2', 'W') + tuple(n for ns in LAYERS.values() for n in ns)
CANDIDATES = tuple(f'G{i}' for i in range(1, 6))


def write(path, value):
    temporary = path.with_suffix(path.suffix+'.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=1, default=lambda x: x.item())+'\n', encoding='utf-8')
    os.replace(temporary, path)


def fingerprints():
    paths = (PREREG, M.PROFILE, Path(M.__file__), Path(B.__file__), Path(B.X.__file__), Path(E.__file__),
             Path(__file__), Path(Y.__file__), ROOT/'studies/trader_replication/study.py',
             ROOT/'studies/trader_data/panel.py', ROOT/'studies/trader_replication/standard_indicators.py',
             ROOT/'studies/martin_luk/tests/test_ie47_e14.py',
             ROOT/'studies/trader_replication/tests/test_e14_execution.py')
    return {str(p.relative_to(ROOT)): SP.sha(p) for p in paths}


def update_checks(key, value):
    checks = json.loads(CHECKS.read_text(encoding='utf-8')) if CHECKS.exists() else {}
    checks[key] = value
    write(CHECKS, checks)


def specification(name):
    spec = {k: 'W' for k in LAYERS}
    if name == 'W':
        return spec
    for layer, names in LAYERS.items():
        if name in names:
            spec[layer] = name
            return spec
    raise ValueError('unknown E14 diagnostic: '+name)


def signal_arrays(A):
    out = B.signal_arrays(A)
    out['e14_high'] = A['close'] >= out['prior20_close']
    out['e14_reclaim'] = np.zeros(A['close'].shape, bool)
    for start in range(0, A['close'].shape[1], 64):
        sl = slice(start, start+64)
        c, h, l, e9 = (x[:, sl] for x in (A['close'], A['high'], A['low'], out['e9']))
        out['e14_reclaim'][1:, sl] = (l[1:] <= e9[1:]) & (c[1:] > e9[1:]) & (c[1:] > h[:-1])
    return out


def candidate_rules(k2, spec):
    s, c, z, a, t, h, m = (spec[k] for k in LAYERS)
    return replace(k2, max_position=.30, no_rebuy_day=t != 'T0',
                   probe_hard_mult={'S15': 1.5, 'S30': 3., 'SK': 0.}.get(s, 2.),
                   probe_close_days=2 if s == 'SC2' else 0,
                   proof_risk=True, proof_stop={'CF': 'fill', 'CU': 'budget'}.get(c, 'low'),
                   proof_target_mult={'Z15': 3., 'Z075': 1.5}.get(z, 2.),
                   proof_add_signal='' if a in ('A0', 'AR') else 'e14_reclaim' if a == 'AE' else 'e14_high',
                   proof_add_max=0 if a == 'A0' else 4 if a == 'A4' else 2,
                   add_levels=(2, 4) if a == 'AR' else (),
                   proof_trail='e21' if h in ('H21', 'H21A') else '',
                   proof_trail_adds=1 if h == 'H21' else 0, proof_trail_r=5. if h == 'H21' else 0.,
                   trims=() if h == 'HN' else k2.trims, risk_scale='' if m == 'M0' else k2.risk_scale,
                   dd_risk=.2 if m == 'MD' else 0., dd_risk_inclusive=m == 'MD')


def retry_book(A, base, sig, spec):
    """Price-only replay of each original watch; failed account fills cannot create retry signals."""
    s, t = spec['S'], spec['T']
    hard_mult = {'S15': 1.5, 'S30': 3., 'SK': 0.}.get(s, 2.)
    maximum, window = {'T0': (1, 20), 'T2': (2, 10), 'T5': (5, 30)}.get(t, (3, 20))
    out, records = [list(row) for row in base], {}
    days, codes = list(map(str, A['days'])), list(map(str, A['codes']))
    o, l, c = (A[k] for k in ('open', 'low', 'close'))
    for b, row in enumerate(base):
        for original in row:
            pr, j, _, fill, stop = original[:5]
            records[b, pr] = dict(origin=days[b], observed=days[pr[1]], attempt=1)
            entry, deadline = b, min(len(out), b+window+1)
            for attempt in range(2, maximum+1):
                stopped, armed, live = None, False, stop
                for d in range(entry+1, deadline):
                    if not np.isfinite(o[d, j]):
                        continue
                    close_window = bool(hard_mult) and (s != 'SC2' or d-entry <= 2)
                    hard = fill-hard_mult*(fill-stop) if close_window else live
                    if o[d, j] <= hard or l[d, j] <= hard or (close_window and c[d, j] < stop):
                        stopped = d
                        break
                    if c[d, j] > fill:
                        break
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
                    e = (pr, j, 1, float(c[d, j]), new_stop, 'e14_retry', None)
                    out[d].append(e)
                    records[d, pr] = dict(origin=days[b], observed=days[pr[1]], attempt=attempt)
                    entry, fill, stop, rebought = d, e[3], e[4], d
                    break
                if rebought is None:
                    break
    meta = {}
    for d, row in enumerate(out):
        row.sort(key=lambda e: e[0])
        for e in row:
            meta.setdefault((codes[e[1]], days[d]), records[d, e[0]])
    return out, meta


class E14Study(M.IE47Study):
    def __init__(self, specs=None):
        self.specs = specs or {}

    def inputs(self, A):
        if '_e14_signals' not in A:
            A['_e14_signals'] = signal_arrays(A)
        return A['_e14_signals']

    def named(self, A, pool, name):
        if name.startswith('e14_'):
            return self.inputs(A)[name]
        return super().named(A, pool, name)

    def ema_inputs(self, A, pool, rules):
        out = super().ema_inputs(A, pool, rules)
        if rules.proof_trail:
            out[rules.proof_trail] = A[rules.proof_trail]
        return out

    def build(self, A, cfg, trace=None):
        name = cfg.get('candidate', 'W')
        if '_e14_base' not in A:
            A['_e14_base'] = super().build(A, dict(cfg, candidate='E8c'))
        base, rules, mask, pool = A['_e14_base']
        k2 = B.X.rule_layers(rules, ('AS', 'X1'))
        if name == 'K2':
            return base, k2, mask, pool
        spec = cfg.get('spec') or self.specs.get(name) or specification(name)
        rules = candidate_rules(k2, spec)
        book, meta = retry_book(A, base, self.inputs(A), spec)
        if trace is not None:
            trace['trial_meta'] = meta
        mask = np.zeros_like(mask)
        for d, row in enumerate(book):
            for e in row:
                mask[d, e[1]] = True
        return book, rules, mask, pool


def setup(upto=None, specs=None):
    st = E14Study(specs)
    st.progress = progress
    A = st.arrays('us', upto=upto, mode='frozen')
    R = st.selected(A)
    cfg = dict(profile_sha256=SP.sha(M.PROFILE), frozen_inputs_sha256=M.inputs_digest(R['sources']))
    return st, A, cfg


def compose(runs):
    spec, choices = {}, {}
    for layer, alternatives in LAYERS.items():
        names = ('W',)+alternatives
        scores = {n: min(runs[n]['by_year'][y] for y in ('2024', '2025')) for n in names}
        ranking = sorted(names, key=lambda n: (-scores[n], names.index(n)))
        first = ranking[0]
        if scores[first]-scores['W'] < .02:
            first = 'W'
        second = next(n for n in ranking if n != first)
        spec[layer] = first
        choices[layer] = dict(first=first, second=second, gap=scores[first]-scores[second],
                              first_min_year=scores[first], second_min_year=scores[second],
                              ranking=ranking, scores=scores, w_fallback=first == 'W' and ranking[0] != 'W')
    return spec, choices


def candidate_specs(runs):
    star, choices = compose(runs)
    specs = [star]
    w = specification('W')
    if star != w:
        specs.append(w)
    order = sorted(LAYERS, key=lambda k: (choices[k]['gap'], tuple(LAYERS).index(k)))
    for layer in order:
        other = dict(star, **{layer: choices[layer]['second']})
        if other not in specs:
            specs.append(other)
        if len(specs) == 5:
            break
    if len(specs) != 5:
        raise AssertionError('E14 needs five distinct complete configurations')
    return dict(zip(CANDIDATES, specs)), choices


def select(runs):
    with patch.object(B, 'CANDIDATES', CANDIDATES):
        return B.select(runs)


def evaluate(st, A, cfg, name, legs, span, directory=WORK):
    directory.mkdir(exist_ok=True)
    with patch.object(B, 'WORK', directory), patch.object(B, 'update_checks', update_checks):
        stats = B.evaluate(st, A, cfg, name, legs, span, check_baseline=name == 'K2' and span == E.TRAIN)
    trades = json.loads((directory/f'{name}_{span[0][:4]}_trades.json').read_text(encoding='utf-8'))
    for year, row in stats['annual'].items():
        closed = [t for t in trades if t['why'] != 'end' and t['entry'].startswith(year)]
        row['by_attempt'] = {str(a): B.distribution([t['r'] for t in closed if t.get('attempt', 1) == a])
                             for a in range(1, 6)}
    return stats


def smoke():
    st, A, cfg = setup('2024-02-29')
    out = dict(span=['2024-01-02', '2024-02-29'], runs={}, source_sha256=fingerprints())
    for name in DIAGNOSTICS:
        entries, rules, _, pool = st.build(A, dict(cfg, candidate=name))
        curve, _, trades = Y.simulate(st.px(A), st.ema_inputs(A, pool, rules), rules, entries, *out['span'], audit=True)
        out['runs'][name] = dict(total=float(curve[-1]-1), trades=len(G.closed(trades)), fills=G.check_fills(A, trades))
    write(WORK/'smoke.json', out)
    if not all(r['fills']['ok'] for r in out['runs'].values()):
        raise AssertionError('E14 smoke fills failed')
    progress('all 22 smoke configurations passed, January-February 2024 only')


def corporate_action_basis(A):
    base = TD.dataset('us', 'frozen')
    p = TP.assemble(B.CutDataset(base, CUT))
    k = int(np.searchsorted(A['days'], CUT, side='right'))
    future = {code: [a for a in rows if a[0] > CUT] for code, rows in base.actions().items()
              if any(a[0] > CUT for a in rows)}
    changed, factors, error = [], {}, 0.
    for j, code in enumerate(map(str, A['codes'])):
        old, new = A['close'][:k, j], p['close'][:, j]
        valid = np.isfinite(old) & np.isfinite(new) & (new > 0)
        if not valid.any():
            continue
        if not np.array_equal(old, new, equal_nan=True):
            changed.append(code)
        ratio = old[valid].astype(float)/new[valid]
        factors[code] = factor = float(np.median(ratio))
        error = max(error, float(np.max(np.abs(ratio/factor-1))))
    write(WORK/'corporate_action_basis.json', dict(cut=CUT, future_actions=future, changed_codes=changed,
                                                  full_to_asof_scale=factors, max_relative_scale_error=error))
    update_checks('corporate_action_basis', dict(cut=CUT, raw_rows_cut_before_adjustment=True,
                  future_action_codes=len(future), earlier_price_codes_changed=len(changed),
                  max_relative_scale_error=error, invariant_prices=not changed,
                  limitation='shared upto loader adjusts full history before slicing; raw-asof price basis can differ'))


def compatibility_check():
    """Unit-only synthetic paths: compare every trade dictionary and curve with the saved pre-E14 engine."""
    path = WORK/'system_before_e14.py.txt'
    old = ModuleType('e14_prior_engine')
    sys.modules[old.__name__] = old
    exec(compile(path.read_text(encoding='utf-8'), str(path), 'exec'), old.__dict__)
    rng = np.random.default_rng(1400)
    c = 100*np.exp(np.cumsum(rng.normal(.002, .025, (70, 4)), axis=0))
    days = np.arange('2024-01-01', '2024-03-11', dtype='datetime64[D]').astype(str)
    px = dict(open=c*.998, high=c*1.025, low=c*.97, close=c, dates=days, codes=np.array(list('ABCD')))
    ema = dict(e9=B.S.ema(c, 9), e21=B.S.ema(c, 21), again=c > 90)
    book = [[] for _ in days]
    for d in range(0, 65, 4):
        for j in range(4):
            side = 1 if j < 3 else -1
            book[d].append(((j,), j, side, float(c[d, j]), float(c[d, j]*(1-side*.04)), 'unit', None))
    policies = [Y.Rules(), Y.Rules(add_levels=(2, 4), short_trims=(2, 3), short_max_days=8),
                Y.Rules(close_stop_days=2, add_signal='again', add_signal_max=1, add_signal_stop='low'),
                Y.Rules(trail='e21', dd_risk=.1, trail_next_open=True),
                Y.Rules(probe_hard_mult=2., proof_risk=True, proof_add_signal='again')]
    rows = []
    for i, rules in enumerate(policies):
        opts = {k: v for k, v in asdict(rules).items() if k in old.Rules.__dataclass_fields__}
        before = old.simulate(px, ema, old.Rules(**opts), book, days[0], days[-1], audit=True)
        after = Y.simulate(px, ema, rules, book, days[0], days[-1], audit=True)
        rows.append(dict(case=i, ok=np.array_equal(before[0], after[0]) and before[2] == after[2],
                         trades=len(after[2])))
    result = dict(ok=all(r['ok'] for r in rows), cases=rows, before_sha256=SP.sha(path))
    update_checks('default_off_bitwise', result)
    if not result['ok']:
        raise AssertionError('disabled E14 fields changed prior behavior')


def audit_configurations(st, A, cfg, specs):
    """Rebuild prefix inputs from existing stored bars, comparing only decisions and real executions."""
    checks = json.loads(CHECKS.read_text(encoding='utf-8')) if CHECKS.exists() else {}
    truncations, gates = checks.get('real_truncation', {}), checks.get('gate_lookahead', {})
    cut_A = st.arrays('us', upto=CUT, mode='frozen')
    k = len(cut_A['days'])
    full_picks = {d: v for d, v in st.selected(A)['picks'].items() if d <= CUT}
    cut_picks = st.selected(cut_A)['picks']
    nights = [d for d in full_picks if full_picks[d] != cut_picks.get(d)]
    for name, spec in specs.items():
        config = dict(cfg, candidate=name, spec=spec)
        book, rules, _, pool = st.build(A, config)
        trades = Y.simulate(st.px(A), st.ema_inputs(A, pool, rules), rules, book, *E.TRAIN, audit=True)[2]
        full_events = B.execution_events(trades, CUT)
        other, rules, _, pool = st.build(cut_A, config)
        trades = Y.simulate(st.px(cut_A), st.ema_inputs(cut_A, pool, rules), rules, other,
                            E.TRAIN[0], CUT, audit=True)[2]
        result = B.event_comparison(full_events, B.execution_events(trades, CUT))
        result.update(cut=CUT, spec=spec, books_bitwise=book[:k] == other,
                      n_nights_different=len(nights), picks_different=nights)
        result['ok'] &= result['books_bitwise'] and not nights
        truncations[name] = result
        update_checks('real_truncation', truncations)
        if not result['ok']:
            raise AssertionError(name+' real cutoff changed earlier decisions or executions')
        progress(f'{name}: {result["events_full"]} prefix executions exactly identical')
    del cut_A, other, book, trades
    gc.collect()
    collected = {name: [] for name in specs}
    original_arrays = st.arrays
    for cut in G.CUTS:
        prefix = original_arrays('us', upto=cut, mode='frozen')
        with patch.object(st, 'arrays', return_value=prefix):
            for name, spec in specs.items():
                result = G.check_lookahead(st, dict(cfg, candidate=name, spec=spec), 'us', full=A, cuts=(cut,))
                collected[name].extend(result['cuts'])
                if not result['ok']:
                    raise AssertionError(name+' gate lookahead failed')
        del prefix
        gc.collect()
    for name, cuts in collected.items():
        gates[name] = dict(ok=all(c['ok'] for c in cuts), cuts=cuts)
        progress(name+': gate.check_lookahead passed')
    update_checks('gate_lookahead', gates)
    update_checks('audit_resources', dict(memory=B.memory(), address_space_limit=LIMIT))


def audit_inputs():
    update_checks('audit_before_memory', B.memory())
    compatibility_check()
    st, A, cfg = setup()
    audit_configurations(st, A, cfg, {'W': specification('W')})
    corporate_action_basis(A)


def resume_record(stage, provenance):
    path = WORK/f'{stage}_started.json'
    if path.exists():
        prior = json.loads(path.read_text(encoding='utf-8'))
        if prior['source_sha256'] != provenance:
            raise ValueError('cannot resume after source or preregistration changed')
        return
    with path.open('x', encoding='utf-8') as stream:
        json.dump(dict(source_sha256=provenance, memory=B.memory()), stream, ensure_ascii=False, indent=1)
        stream.write('\n')


def train():
    if RESULT.exists() or SELECTED.exists():
        raise ValueError('E14 training already recorded; do not select again')
    checks = json.loads(CHECKS.read_text(encoding='utf-8'))
    if not (checks.get('real_truncation', {}).get('W', {}).get('ok') and
            checks.get('gate_lookahead', {}).get('W', {}).get('ok')):
        raise ValueError('W causal checks must pass before training')
    sources = fingerprints()
    resume_record('train', sources)
    st, A, cfg = setup()
    partial = RESULT.with_suffix('.partial.json')
    out = json.loads(partial.read_text(encoding='utf-8')) if partial.exists() else dict(
        preregistered_sha256=SP.sha(PREREG), source_sha256=sources, span=list(E.TRAIN), base=cfg, runs={})
    if out['source_sha256'] != sources or out['base'] != cfg:
        raise ValueError('partial train inputs changed')
    legs = B.main_legs(A, st.selected(A)['picks'])
    write(WORK/'evaluation_legs.json', legs)
    for name in DIAGNOSTICS:
        if name not in out['runs']:
            path = WORK/f'{name}_2024_stats.json'
            if path.exists():
                out['runs'][name] = json.loads(path.read_text(encoding='utf-8'))
            else:
                out['runs'][name] = evaluate(st, A, cfg, name, legs, E.TRAIN)
                write(path, out['runs'][name])
            write(partial, out)
    specs, choices = candidate_specs(out['runs'])
    out.update(specs=specs, composition=choices)
    st.specs = specs
    for name in CANDIDATES:
        if name not in out['runs']:
            path = WORK/f'{name}_2024_stats.json'
            if path.exists():
                out['runs'][name] = json.loads(path.read_text(encoding='utf-8'))
            else:
                out['runs'][name] = evaluate(st, A, cfg, name, legs, E.TRAIN)
                write(path, out['runs'][name])
            write(partial, out)
    eligible, chosen = select(out['runs'])
    out.update(eligible=eligible, chosen=chosen)
    write(partial, out)
    audit_specs = {'W*': specs['G1']}
    if chosen:
        audit_specs[chosen] = specs[chosen]
    audit_configurations(st, A, cfg, audit_specs)
    write(RESULT, out)
    with SELECTED.open('x', encoding='utf-8') as stream:
        json.dump(dict(chosen=chosen, eligible=eligible, specs=specs, composition=choices,
                       preregistered_sha256=SP.sha(PREREG), source_sha256=sources,
                       train_sha256=SP.sha(RESULT)), stream, ensure_ascii=False, indent=1)
        stream.write('\n')
    update_checks('train_resources', dict(memory=B.memory(), address_space_limit=LIMIT))
    update_checks('validation_policy', dict(selected=chosen, measured=False,
                  reason='no candidate meets both annual floors' if chosen is None else 'selected candidate only, pending'))
    progress(f'E14 complete selection: eligible={eligible}; chosen={chosen}')


def validate():
    if VALIDATION.exists():
        raise ValueError('E14 validation already recorded')
    selected = json.loads(SELECTED.read_text(encoding='utf-8'))
    if selected['chosen'] is None:
        raise ValueError('No E14 candidate eligible; 2026 must not be tested')
    if selected['source_sha256'] != fingerprints() or selected['train_sha256'] != SP.sha(RESULT):
        raise ValueError('E14 source or training changed after selection')
    marker = WORK/'validation_started.json'
    provenance = dict(selected_sha256=SP.sha(SELECTED), source_sha256=fingerprints())
    if marker.exists():
        prior = json.loads(marker.read_text(encoding='utf-8'))
        if any(prior.get(k) != v for k, v in provenance.items()):
            raise ValueError('cannot resume validation after selection or source changed')
    else:
        with marker.open('x', encoding='utf-8') as stream:
            json.dump(dict(provenance, memory=B.memory()), stream, indent=1)
    st, A, cfg = setup(specs=selected['specs'])
    partial = VALIDATION.with_suffix('.partial.json')
    out = json.loads(partial.read_text(encoding='utf-8')) if partial.exists() else dict(
        chosen=selected['chosen'], span=list(E.VALIDATE), selected_sha256=SP.sha(SELECTED), runs={}, full={},
        scope='2026 was used in prior research; one E14 chosen candidate, no independent holdout claim')
    if out['selected_sha256'] != SP.sha(SELECTED):
        raise ValueError('partial validation selection changed')
    for key, span, directory in (('runs', E.VALIDATE, WORK/'validation'),
                                 ('full', (E.TRAIN[0], E.VALIDATE[1]), WORK/'full')):
        legs = B.main_legs(A, st.selected(A)['picks'], span)
        for name in ('K2', selected['chosen']):
            if name not in out[key]:
                out[key][name] = evaluate(st, A, cfg, name, legs, span, directory)
                write(partial, out)
    write(VALIDATION, out)
    update_checks('validation_policy', dict(selected=selected['chosen'], measured=True, candidates=1))
    update_checks('validation_resources', dict(memory=B.memory(), address_space_limit=LIMIT))


def checks():
    with patch.object(B, 'WORK', WORK), patch.object(B, 'update_checks', update_checks):
        B.checks()
    if RESULT.exists():
        artifact_checks()


def artifact_checks():
    train = json.loads(RESULT.read_text(encoding='utf-8'))
    selected = json.loads(SELECTED.read_text(encoding='utf-8'))
    provenance = dict(ok=selected['source_sha256'] == fingerprints() == train['source_sha256'] and
                         selected['train_sha256'] == SP.sha(RESULT) and
                         selected['preregistered_sha256'] == SP.sha(PREREG))
    update_checks('provenance', provenance)
    before = json.loads((WORK/'before_e14.json').read_text(encoding='utf-8'))
    protected = {p: SP.sha(ROOT/p) == h for p, h in before.items()
                 if p != 'studies/trader_replication/system.py'}
    update_checks('protected_sources', dict(ok=all(protected.values()), files=protected))
    result = dict(ok=True, configurations={}, adds=0, max_budget_excess_u=0.)
    k2 = B.X.rule_layers(M.e8_rules('E8c'), ('AS', 'X1'))
    for name in DIAGNOSTICS[1:]+CANDIDATES:
        spec = train['specs'][name] if name in CANDIDATES else specification(name)
        rules = candidate_rules(k2, spec)
        trades = json.loads((WORK/f'{name}_2024_trades.json').read_text(encoding='utf-8'))
        row = dict(ok=True, adds=0, max_budget_excess_u=0., violations=[])
        for t in trades:
            cash, shares, prior_stop = 0., 0., -np.inf
            add_days = []
            for e in t['executions']:
                if e['action'] in ('entry', 'add'):
                    cash -= e['shares']*e['price']*(1+rules.buy_cost)
                    shares += e['shares']
                elif e['action'] != 'end':
                    cash += e['shares']*e['price']*(1-rules.sell_cost)
                    shares -= e['shares']
                if e['action'] == 'add':
                    row['adds'] += 1
                    add_days.append(e['time'])
                    excess = -(cash+shares*e['stop']*(1-rules.sell_cost))/t['risk_budget']-1
                    row['max_budget_excess_u'] = max(row['max_budget_excess_u'], excess)
                    if excess > 1e-10 or e['stop'] < prior_stop or e['time'] == t['entry']:
                        row['violations'].append(dict(code=t['code'], entry=t['entry'], event=e, excess_u=excess))
                    prior_stop = e['stop']
                if e['action'] not in ('entry', 'end') and e['time'] == t['entry']:
                    row['violations'].append(dict(code=t['code'], entry=t['entry'], reason='entry day management'))
            if len(add_days) != len(set(add_days)) or t['proof_adds'] > rules.proof_add_max:
                row['violations'].append(dict(code=t['code'], entry=t['entry'], reason='pyramid count/timing'))
            if t['why'] != 'end' and t['exit'] in add_days:
                row['violations'].append(dict(code=t['code'], entry=t['entry'], reason='exit and add conflict'))
            if t.get('proof_trail_day') and t['why'] == 'trail' and t['exit'] <= t['proof_trail_day']:
                row['violations'].append(dict(code=t['code'], entry=t['entry'], reason='trail switched before next session'))
        row['ok'] = not row['violations']
        result['configurations'][name] = row
        result['ok'] &= row['ok']
        result['adds'] += row['adds']
        result['max_budget_excess_u'] = max(result['max_budget_excess_u'], row['max_budget_excess_u'])
    update_checks('actual_execution_risk', result)
    if not (provenance['ok'] and all(protected.values()) and result['ok']):
        raise AssertionError('E14 artifact provenance, protection or execution checks failed')


def report():
    """Render the fixed measurements; never select again or rerun a portfolio."""
    train = json.loads(RESULT.read_text(encoding='utf-8'))
    checks = json.loads(CHECKS.read_text(encoding='utf-8'))
    runs, chosen, choices = train['runs'], train['chosen'], train['composition']
    names = DIAGNOSTICS+CANDIDATES
    def pct(x):
        return '—' if x is None else f'{100*x:+.1f}%'
    def weight(x):
        return '—' if x is None else f'{100*x:.1f}%'
    def num(x):
        return '—' if x is None else f'{x:.2f}'
    def held(r, group, point='midpoint'):
        return sum(v[point]['held'] for v in r['legs'][group].values())
    def usum(r, label):
        return sum(v['u_'+label]['sum'] for v in r['annual'].values())
    def desc(spec):
        return '、'.join(k+':'+v for k, v in spec.items())
    lines = ['# E14：执行层多方向诊断与自动组合', '']
    if chosen:
        lines += [f'结论：**按预登记选中 {chosen}（{desc(train["specs"][chosen])}）；2024、2025 两年收益均不低于 K2。**', '']
        r = runs[chosen]
        lines += [f'它在 2024 年赚 {pct(r["by_year"]["2024"])}、2025 年赚 {pct(r["by_year"]["2025"])}，'
                  f'两年合计 {pct(r["total"])}、最大回撤 {weight(r["maxdd"])}；'
                  f'他的主升浪中点持有 {held(r,"his")} 段，K2 为 {held(runs["K2"],"his")} 段。'
                  '这是本轮研究选择，登记版与看板未改。', '']
    else:
        best = max(CANDIDATES, key=lambda n: min(runs[n]['by_year'].values()))
        r, ref = runs[best], runs['K2']
        failures = '；'.join(f'{y} 少 {(ref["by_year"][y]-r["by_year"][y])*100:.1f} 个百分点'
                             for y in ('2024', '2025') if r['by_year'][y] < ref['by_year'][y])
        lines += ['结论：**五个端到端候选都未同时达到 K2 两个年度的收益门槛，不采用；按预登记不测 2026。**', '',
                  f'较差年收益最高的是 {best}：2024 {pct(r["by_year"]["2024"])}、2025 {pct(r["by_year"]["2025"])}；{failures}。', '']
    if VALIDATION.exists():
        validation = json.loads(VALIDATION.read_text(encoding='utf-8'))
        v, full = validation['runs'], validation['full']
        lines += [f'选中者 2026 至 10-16 仅测一次：{chosen} {pct(v[chosen]["total"])}，'
                  f'K2 {pct(v["K2"]["total"])}；2024–2026 全段分别 {pct(full[chosen]["total"])}、{pct(full["K2"]["total"])}。'
                  '2026 已用于先前研究，不称独立样本外。', '']
    lines += ['本轮只执行[唯一任务书](../notes/PLAN_E14_CN.md)。[预登记](../notes/PREREG_E14_CN.md)先于测试和实现；'
              '20 个单环节替换全部保留测量，随后机械组合、产生五个唯一候选；单项诊断不能直接当作选中版本。', '',
              '## 1. 单环节替换总表（22 行）', '',
              '| 配置 | 2024 | 2025 | 两年 | 回撤 | 他段中点持有 | 池内段中点持有 | 未证实合计 U | 已证实合计 U |',
              '|---|---|---|---|---|---|---|---|---|']
    for name in DIAGNOSTICS:
        r = runs[name]
        lines.append(f'| {name} | {pct(r["by_year"]["2024"])} | {pct(r["by_year"]["2025"])} | '
                     f'{pct(r["total"])} | {weight(r["maxdd"])} | {held(r,"his")} | {held(r,"pool")} | '
                     f'{num(usum(r,"unconfirmed"))} | {num(usum(r,"confirmed"))} |')
    lines += ['', 'U 为每笔首次成交时固定的一份账户风险，合计按每笔实际买卖现金流 / 该笔 U，计费用和减仓；'
              '不同配置的 R 分母随试单股数改变，不能用总 R 直接代替账户收益。以下全部交易统计只计已平仓；end 行仅估值。', '',
              '## 2. 自动组合过程', '',
              '| 环节 | 第一名（含 W 回退） | 较差年收益 | 第二名 | 较差年收益 | 差距（百分点） | W 回退 |',
              '|---|---|---|---|---|---|---|']
    for k, r in choices.items():
        lines.append(f'| {k} | {r["first"]} | {pct(r["first_min_year"])} | {r["second"]} | '
                     f'{pct(r["second_min_year"])} | {100*r["gap"]:+.2f} | {"是" if r["w_fallback"] else "否"} |')
    lines += ['', '每环节原始排名、所有 min-year 分数均保存在 e14_train.json / e14_selected.json。'
              '与 W 改善不足 2 个百分点保留 W；因此有符号第一/第二差距可能为负。'
              '按差距由小到大做单环节第二名替换，跳过重复配置，平手按 S,C,Z,A,T,H,M。', '',
              '## 3. 端到端候选与资格', '',
              '| 候选 | 组成 | 2024 | 2025 | 两年 | 回撤 | 较差年 | 他段中点 | 资格 |',
              '|---|---|---|---|---|---|---|---|---|']
    for name in CANDIDATES:
        r = runs[name]
        lines.append(f'| {name} | {desc(train["specs"][name])} | {pct(r["by_year"]["2024"])} | '
                     f'{pct(r["by_year"]["2025"])} | {pct(r["total"])} | {weight(r["maxdd"])} | '
                     f'{pct(min(r["by_year"].values()))} | {held(r,"his")} | {"通过" if name in train["eligible"] else "未通过"} |')
    lines += ['', '资格采用同次重算、未四舍五入的 K2 同年收益；只有同时达标者才按较差年收益、2 个百分点内的他段中点覆盖、G 顺序选择。'
              'K2 与 E10/E11 全部原始逐笔及账户指标逐位核对；单层改善只对本轮上下游配置成立。', '',
              '## 4. 差在哪年、哪层', '']
    w, cu = runs['W'], runs['CU']
    lines += [f'先看任务书要修正的止损层：结构止损基底 W 在 2024 / 2025 为 '
              f'{pct(w["by_year"]["2024"])} / {pct(w["by_year"]["2025"])}，'
              f'把证实止损放回预算价的 CU 为 {pct(cu["by_year"]["2024"])} / {pct(cu["by_year"]["2025"])}。'
              f'已证实交易合计分别为 {num(usum(w,"confirmed"))}U、{num(usum(cu,"confirmed"))}U。'
              'CU 仅恢复证实这一步的预算止损，后续再加仓仍同 W，不能把 CU 说成 E13 完整版。', '']
    if VALIDATION.exists():
        lines += ['| 验证窗口 | 配置 | 收益 | 回撤 | 已平仓 | 胜率 | 平均敞口 | 融资利息 |',
                  '|---|---|---|---|---|---|---|---|']
        for key, label in (('runs', '2026 至 10-16'), ('full', '2024–2026 全段')):
            for name, r in validation[key].items():
                lines.append(f'| {label} | {name} | {pct(r["total"])} | {weight(r["maxdd"])} | '
                             f'{r["trades"]} | {weight(r["win"])} | {weight(r["mean_exposure"])} | {weight(r["margin"])} |')
        lines += ['']
    for name in CANDIDATES:
        r = runs[name]
        failures = [y for y in ('2024', '2025') if r['by_year'][y] < runs['K2']['by_year'][y]]
        text = '、'.join(f'{y} 少 {(runs["K2"]["by_year"][y]-r["by_year"][y])*100:.1f} 个百分点' for y in failures) or '两年均达标'
        lines.append(f'- {name}：{text}；未证实 {num(usum(r,"unconfirmed"))}U、已证实 {num(usum(r,"confirmed"))}U。')
    lines += ['', '| 单环节 − W | 2024 收益差（百分点） | 2025 收益差（百分点） | 他段中点差 |', '|---|---|---|---|']
    for name in DIAGNOSTICS[2:]:
        r, w = runs[name], runs['W']
        lines.append(f'| {name} | {100*(r["by_year"]["2024"]-w["by_year"]["2024"]):+.2f} | '
                     f'{100*(r["by_year"]["2025"]-w["by_year"]["2025"]):+.2f} | {held(r,"his")-held(w,"his"):+d} |')
    lines += ['', '这些是整套账户路径的受控单环节替换；改变止损会同时影响账户拒绝、再试和后续加仓。'
              '不同配置的 U 金额也不同，U 合计用于解释现金流层，不与账户百分点作机械相加。'
              '这轮的失败只能归于本轮规则、数据和执行配置，不能推广为否定交易员的方法。', '',
              '## 5. 未来函数与工程验证', '']
    for name, r in checks.get('real_truncation', {}).items():
        lines.append(f'- 真实截断 {CUT}，{name}：{r["events_full"]} / {r["events_cut"]} 条成交事件，'
                     f'逐位一致={r["ok"]}；选股不同 {r["n_nights_different"]} 晚，入场/再试簿一致={r["books_bitwise"]}。')
    for name, r in checks.get('gate_lookahead', {}).items():
        lines.append(f'- gate.check_lookahead，{name}：{"通过" if r["ok"] else "失败"}；'
                     + '、'.join(c['cut'] for c in r['cuts'])+'。')
    basis = checks.get('corporate_action_basis', {})
    risk = checks.get('actual_execution_risk', {})
    lines += ['- 合成测试逐个覆盖 W 和全部 20 个替换的过去信号数组、入场簿、再试簿及元数据；未来乘三和打乱均不改变过去。'
              '时点测试覆盖 1U 反解股数、费用/已实现现金流、同日离场优先、加仓当天低点次日生效、21EMA 次日切换与前收盘回撤刹车。',
              f'- 新字段默认关闭：与修改前引擎五组多空/加仓/费用/止损/跟踪场景的完整权益和逐笔字典逐位一致='
              f'{checks.get("default_off_bitwise",{}).get("ok")}；三套全量测试见下。',
              f'- 真实成交现金流独立复核：{risk.get("adds")} 次加仓，'
              f'计划止损风险均 ≤1U={risk.get("ok")}，最大浮点超差 {risk.get("max_budget_excess_u",float("nan")):.2g}U；'
              '同时查加仓止损不下移、再加仓次数、同日离场冲突与 21EMA 生效日。实际跳空仍可能越过计划止损。',
              f'- 公司行动单独复核：先裁原始行情和行动再重建；截止日后有行动 {basis.get("future_action_codes")} 只，'
              f'历史价格基准改变 {basis.get("earlier_price_codes_changed")} 只，前后比例最大相对误差 '
              f'{basis.get("max_relative_scale_error",float("nan")):.2g}。共享加载器先完整复权再裁切，'
              '前缀事件与 gate 通过不能冒充已排除未来公司行动影响。完整明细见 e14_work/corporate_action_basis.json。']
    for name, r in checks.get('tests', {}).items():
        brief = '；'.join(s for s in r['summary'] if s.startswith(('Ran ', 'OK', 'FAILED')))
        lines.append(f'- {name} 全量测试：{"通过" if r["ok"] else "失败"}；{brief}。')
    lines += ['', '## 6. 照记与工件', '',
              '- 首次训练在最终现金流检查发现 float32 风险超差，整套结果与原指纹源码原样保存在 e14_float32_attempt/；'
              '修复后按原预登记重做，不隐瞒第二次工程执行。未改候选、门槛或选择规则，详见[数值更正记录](../notes/E14_NUMERICAL_CORRECTION_CN.md)。',
              '- 修正后的 train 排他选择写 e14_selected.json；每配置立即保存独立 stats、逐笔、权益和段明细，可恢复尚未完成的配置。'
              '开始记录和 partial 的指纹必须一致；完成记录不可覆盖。validate 单次排他开始，未达标不测 2026。',
              '- 单进程，64 列临时块，RLIMIT_AS=1,900,000,000 字节；研究峰值与开始内存见 e14_checks.json。'
              '全量测试子进程沿用原系统地址空间限制，以运行现有 Go 密钥扫描器；未跳过密钥检查。',
              '- 未取新数据、未用小时线、未冻结、未提交、未改登记版和看板；既有密钥 hooksPath 经核对继续使用。',
              '- 结果：e14_train.json、e14_selected.json、e14_checks.json；若有资格另写 e14_validation.json（2026 与全段）。'
              '下面附表逐配置分年提供 E13 全部尺子，逐段试单/亏损/首末位置在 e14_work/*_2024_legs.json。', '',
              '## 附表 A：分年账户、风险分布与确切日期', '',
              '| 配置 | 年 | 收益 | 回撤 | 开仓/已平 | 胜率 | 平均赚/亏（实际投入） | ≥20%赢家 | 平均敞口 | 融资利息 | 确切日期买到/全部 |',
              '|---|---|---|---|---|---|---|---|---|---|---|']
    for name in names:
        for year, r in runs[name]['annual'].items():
            lines.append(f'| {name} | {year} | {pct(r["ret"])} | {weight(r["maxdd"])} | {r["opened"]}/{r["closed"]} | '
                         f'{weight(r["win"])} | {pct(r["avg_win"])}/{pct(r["avg_loss"])} | {r["winners20"]} | '
                         f'{weight(r["exposure"])} | {weight(r["margin"])} | {r["his_exact"]["bought"]}/{r["his_exact"]["all"]} |')
    lines += ['', '确切日期沿用 E10：他的日期前 3 个交易日到后 2 日内账户有实际买入，2024–25 合计 17 笔。', '',
              '| 配置 | 年 | 未证实 R：笔数/均值/中位/P10/P90/合计 | 已证实 R：笔数/均值/中位/P10/P90/合计 | 未证实 U | 已证实 U |',
              '|---|---|---|---|---|---|']
    def dist(r):
        return f'{r["n"]}/'+ '/'.join(num(r[k]) for k in ('mean', 'median', 'p10', 'p90', 'sum'))
    for name in names:
        for year, r in runs[name]['annual'].items():
            lines.append(f'| {name} | {year} | {dist(r["r_unconfirmed"])} | {dist(r["r_confirmed"])} | '
                         f'{num(r["u_unconfirmed"]["sum"])} | {num(r["u_confirmed"]["sum"])} |')
    lines += ['', 'R/U 完整分桶、1–5 次试单分布、退出原因均在 e14_train.json；K2 用实际是否加过仓区分证实。', '',
              '## 附表 B：中点与 1/3 的持仓（全部 E13 尺子）', '']
    for group, title in (('his', '他的段'), ('pool', '池内段')):
        for point, label in (('midpoint', '中点'), ('third', '1/3')):
            lines += [f'### {title} · {label}', '',
                      '| 配置 | 年 | 总段/可评/删失 | 持有段 | 仓位中位（持有段） | 仓位均值（持有段） |',
                      '|---|---|---|---|---|---|']
            for name in names:
                for year, r in runs[name]['legs'][group].items():
                    p = r[point]
                    lines.append(f'| {name} | {year} | {r["n"]}/{p["observed"]}/{p["censored"]} | {p["held"]} | '
                                 f'{weight(p["median"])}（{weight(p["held_median"])}） | {weight(p["mean"])}（{weight(p["held_mean"])}） |')
            lines += ['']
    lines += ['段年份按最早锚定日；均值/中位含零仓位，括号内只含持有段；窗口外的到达日列删失，未当零。'
              '峰值/低点未来标签只在评估使用，决策不读取。', '', '## 附表 C：每段试单与入场位置', '',
              '| 配置 | 段类 | 年 | 买到/全部段 | 每段试单均值 | 亏损合计 U（未证实） | 首笔位置中位 | 末笔位置中位 |',
              '|---|---|---|---|---|---|---|---|']
    for name in names:
        for group, title in (('his', '他的'), ('pool', '池内')):
            for year, r in runs[name]['legs'][group].items():
                lines.append(f'| {name} | {title} | {year} | {r["bought"]}/{r["n"]} | {num(r["trials_mean"])} | '
                             f'{num(r["loss_u_sum"])}（{num(r["unconfirmed_loss_u_sum"])}） | '
                             f'{num(r["first_position_median"])} | {num(r["last_position_median"])} |')
    lines += ['', '这里的亏损只累计亏损试单，盈利不抵消；一笔交易可能属于多个重叠段，不能把逐段 U 合计当账户总亏损。', '',
              '```bash', 'PYTHONUTF8=1 OPENBLAS_NUM_THREADS=1 /opt/opend-us-options/.venv/bin/python -m studies.martin_luk.e14_research checks',
              'PYTHONUTF8=1 OPENBLAS_NUM_THREADS=1 /opt/opend-us-options/.venv/bin/python -m studies.martin_luk.e14_research report',
              '```', '', 'checks / report 可复查既有工件；train / validate 完成记录不得覆盖。', '']
    (OUT/'E14_CN.md').write_text('\n'.join(lines), encoding='utf-8')
    progress('E14 Chinese report rendered from saved artifacts')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('stage', choices=('smoke', 'audit', 'train', 'validate', 'checks', 'report'))
    stage = parser.parse_args().stage
    WORK.mkdir(exist_ok=True)
    if stage in ('checks', 'report'):
        {'checks': checks, 'report': report}[stage]()
    else:
        resource.setrlimit(resource.RLIMIT_AS, (LIMIT, LIMIT))
        B.offline()
        original = TP.build
        def existing_load(market, mode=None, version=None, upto=None, **kwargs):
            return original(TD.dataset(market, mode, version), upto=upto, write_cache=False)
        def read_only_build(ds, upto=None, cache=True, write_cache=True):
            return original(ds, upto=upto, cache=cache, write_cache=False)
        with ExitStack() as stack:
            stack.enter_context(patch.object(TD, 'load', existing_load))
            stack.enter_context(patch.object(TP, 'build', read_only_build))
            {'smoke': smoke, 'audit': audit_inputs, 'train': train, 'validate': validate}[stage]()
