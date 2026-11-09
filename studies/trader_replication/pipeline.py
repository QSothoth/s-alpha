"""G0--G6 evidence checks, not a strategy selector. Labels stay in evaluation.

Year folds consume already-frozen signal outputs. Episode folds describe a
fixed policy: neither refits nor a new claim of independent out-of-sample data.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re

import numpy as np

from . import gate, mainleg, regime, success
from .config import Config, SECTIONS, ALLOCATION_RULES, plain, validate_switch

ALLOWED = {'G0': ('sources',), 'G1': ('data', 'engine'), 'G2': ('switch',),
           'G3': ('universe', 'signal'), 'G4': ('allocate', 'trade'),
           'G5': ('diagnose',), 'G6': ('freeze',)}


def result(status, reason, **numbers):
    if status not in ('pass', 'fail', 'unobserved'):
        raise ValueError(status)
    return dict(status=status, reason=reason, numbers=numbers)


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1 << 20), b''):
            h.update(block)
    return h.hexdigest()


def g0(study, manifest):
    """Manifest freezes ledger, leg labels, split file, claims and public sources."""
    if study.ledger is None or not Path(study.ledger).is_file():
        return result('fail', 'missing public trade ledger; rule evaluation only', dated=0, exact=0)
    trades = study.trades()
    dated = [t for t in trades if t.dated]
    rules_path = study.root/'notes/RULES_CN.md'
    text = rules_path.read_text() if rules_path.is_file() else ''
    missing = []
    if any(not (t.source or '').strip() for t in dated):
        missing.append('public source on each dated trade')
    for layer in SECTIONS:
        claims = manifest.get('claims', {}).get(layer, [])
        if layer == 'switch' and not claims:
            continue  # regime is optional; enabled controls are sourced again at G2
        if not claims or any(not c.get('quote') or c['quote'] not in text or not c.get('source') or
                             not (c.get('timestamp') or re.search(r'\d+:\d+|[?&]t=', c['source'])) for c in claims):
            missing.append('sourced claims: '+layer)
    files = manifest.get('files', {})
    for name in ('trades', 'legs', 'split'):
        item = files.get(name, {})
        path = study.root/item.get('path', '')
        if not path.is_file() or sha(path) != item.get('sha256'):
            missing.append('frozen file: '+name)
        elif name == 'trades' and path.resolve() != Path(study.ledger).resolve():
            missing.append('frozen trades file differs from the study ledger')
    split = None
    if 'frozen file: split' not in missing:
        split = json.loads((study.root/files['split']['path']).read_text())
        if not (len(split.get('select', [])) == len(split.get('validate', [])) == 2
                and split['select'][0] <= split['select'][1] < split['validate'][0] <= split['validate'][1]):
            missing.append('selection / validation split')
    public = manifest.get('public', {})
    if not public or any(v.get('value') is not None and not v.get('source') for v in public.values()):
        missing.append('published statistics or explicit missing fields')
    if len(dated) < 30:
        missing.append('30 dated trades')
    return result('fail' if missing else 'pass', '; '.join(missing) or 'sources and frozen inputs complete',
                  dated=len(dated), exact=sum(t.precision == 'exact' for t in dated), split=split,
                  files=files)


def g1(checks, *, code_sha, data_sha, reference=None, is_reference=False):
    """Consume gate.check_data / check_fills / check_lookahead / check_win results."""
    bad = [k for k in ('data', 'fills', 'lookahead', 'win_rate')
           if checks.get(k, {}).get('ok') is not True or checks.get(k, {}).get('status') == 'unchecked']
    if not code_sha or not data_sha:
        bad.append('fingerprints')
    if not is_reference and (not reference or reference.get('status') != 'pass'):
        bad.append('reference G1')
    return result('fail' if bad else 'pass', ', '.join(bad) or 'reference and engineering checks passed',
                  checks=checks, code_sha=code_sha, data_sha=data_sha, is_reference=is_reference)


def episode_folds(episodes, evaluate):
    """Every episode held out once, in time order; caller receives train and test."""
    return [dict(held_out=e['id'], state=e['state'], start=e['start'], end=e['end'],
                 train=evaluate([x for x in episodes if x['id'] != e['id']]), test=evaluate([e]))
            for e in episodes]


def exposure_scale(baseline, switched):
    """Global risk multiplier for a no-switch, matched-mean-exposure diagnostic."""
    a, b = np.asarray(baseline, float), np.asarray(switched, float)
    if a.shape != b.shape or not len(a) or not np.all(np.isfinite(a)) or not np.all(np.isfinite(b)):
        raise ValueError('aligned finite exposure histories required')
    if np.any(a < 0) or np.any(b < 0):
        raise ValueError('exposures must be nonnegative')
    return dict(baseline_mean=float(a.mean()), switched_mean=float(b.mean()),
                multiplier=float(b.mean()/a.mean()) if a.mean() > 0 else None)


def _episode_rows(episodes, observations):
    by_episode = {e['id']: [] for e in episodes}
    for row in observations:
        day, value = row['day'], row['value']
        if not np.isfinite(value):
            raise ValueError('non-finite observed behaviour')
        match = next((e for e in episodes if e['first'] <= day <= e['last']), None)
        if match is None:
            raise ValueError('observation outside episodes')
        by_episode[match['id']].append(value)
    return [dict(e, trades=len(by_episode[e['id']]), value=float(np.mean(by_episode[e['id']]))
                 if by_episode[e['id']] else None) for e in episodes]


def block_permutation(rows, state, draws=199):
    """Shuffle whole episode summaries, not individual days / trades (fixed seed)."""
    rows = [r for r in rows if r['value'] is not None]
    inside = np.array([r['state'] == state for r in rows])
    values = np.array([r['value'] for r in rows])
    if not inside.any() or inside.all():
        return dict(p=None, effect=None, same_direction=0)
    other = float(values[~inside].mean())
    effect = float(values[inside].mean()-other)
    same = int(np.sum((values[inside]-other)*effect > 0))
    rng, count = np.random.default_rng(0), 0
    for _ in range(draws):
        shuffled = rng.permutation(values)
        count += abs(float(shuffled[inside].mean()-shuffled[~inside].mean())) >= abs(effect)-1e-12
    return dict(p=(count+1)/(draws+1), effect=effect, same_direction=same, draws=draws)


def g2(labels, observations, *, controls, rules_text, stable, lookahead, metric, draws=199):
    """One predeclared behaviour metric, per-state evidence; missing samples keep sourced rules."""
    if labels is None:
        return result('pass', 'Switch disabled; single-state policy', permitted=True, folds=[])
    validate_switch(dict(controls=controls), rules_text)
    rows = _episode_rows(labels['episodes'], observations)
    states = {}
    for state in regime.NAMES:
        part = [r for r in rows if r['state'] == state]
        n, observed = sum(r['trades'] for r in part), sum(r['trades'] > 0 for r in part)
        if observed < 3 or n < 15:
            states[state] = result('unobserved', '按原话冻结；前向记录检验',
                episodes=len(part), observed_episodes=observed, trades=n, rules_sourced=bool(controls))
        else:
            evidence = block_permutation(rows, state, draws)
            ok = evidence['p'] is not None and evidence['p'] < .1 and evidence['same_direction'] >= 2
            states[state] = result('pass' if ok else 'fail', 'episode permutation and direction',
                episodes=len(part), observed_episodes=observed, trades=n, **evidence)
    folds = episode_folds(rows, lambda part: {s: block_permutation(part, s, draws) for s in regime.NAMES})
    for fold, held in zip(folds, rows):
        other = [r['value'] for r in rows if r['state'] != held['state'] and r['value'] is not None]
        effect = held['value']-float(np.mean(other)) if held['value'] is not None and other else None
        trained = fold['train'][held['state']]['effect']
        fold['test'] = dict(trades=held['trades'], value=held['value'], effect=effect,
            same_direction=(effect*trained > 0) if effect is not None and trained is not None else None)
    for state, row in states.items():
        same = sum(f['test']['same_direction'] is True for f in folds if f['state'] == state)
        row['numbers']['leave_one_same_direction'] = same
        if row['status'] == 'pass' and same < 2:
            row.update(status='fail', reason='fewer than two held episodes agree with training direction')
    valid = lookahead.get('ok') is True and stable.get('ok') is True
    failed = not valid or any(r['status'] == 'fail' for r in states.values())
    unobserved = any(r['status'] == 'unobserved' for r in states.values())
    permitted = not failed and (not unobserved or bool(controls))
    return result('fail' if failed else 'unobserved' if unobserved else 'pass',
        '逐状态检验；未观测状态保留有原话的规则' if valid else 'lookahead or definition stability failed',
        states=states, folds=folds, metric=metric, stability=stable, lookahead=lookahead,
        permitted=permitted, spec_sha=labels['spec_sha'])


def g3(folds, legs, calendar, opens, *, upper_bound, holdout='2026', legacy=False):
    """Three frozen leave-year-out nominations; missing folds are never manufactured."""
    rows, unavailable = {}, []
    for year in ('2024', '2025', '2026'):
        fold = folds.get(year)
        if not fold or year in set(map(str, fold.get('trained_years', []))) or not fold.get('model_sha'):
            unavailable.append(year)
            rows[year] = dict(status='unobserved', reason='missing frozen leave-year-out model / nominations')
            continue
        picks = fold['picks']
        expected = {t for t in range(len(calendar)-1) if '2024' <= str(calendar[t])[:4] <= '2026'}
        if not expected.issubset(picks):
            raise ValueError('signal must include empty evaluation nights')
        budget = mainleg.signal_coverage_budget(picks, fold.get('ranks'), legs, calendar, opens, 3)
        wide = mainleg.signal_coverage_budget(picks, fold.get('ranks'), legs, calendar, opens, None)
        row, width = budget['annual'][year], wide['annual'][year]['mean_new_names']
        ok = row['coverage'] is not None and row['coverage'] >= .8 and width is not None and width <= 5
        rows[year] = dict(row, status='pass' if ok else 'fail', unlimited_mean_new_names=width,
            sample=fold.get('sample', 'historical holdout*'), trained_years=fold.get('trained_years', []),
            model_sha=fold['model_sha'], K=3, cooldown=10)
    main = rows[holdout]
    state = 'fail' if legacy or main['status'] == 'fail' or upper_bound < .8 else (
        'unobserved' if unavailable else 'pass')
    return result(state, 'legacy build has no S facade' if legacy else
        'K=3 early coverage >=80%; unlimited new nominations <=5/night; all year folds reported',
        folds=rows, holdout=holdout, upper_bound=upper_bound, missing_folds=unavailable,
        mean_coverage=float(np.mean([r['coverage'] for r in rows.values() if r.get('coverage') is not None]))
            if any(r.get('coverage') is not None for r in rows.values()) else None)


def account_facts(curve, dates, trades):
    closed = gate.closed(trades)
    returns = np.array([t['ret'] for t in closed], float)
    years, previous = {}, 1.
    for year in sorted({str(d)[:4] for d in dates}):
        idx = np.flatnonzero(np.array([str(d).startswith(year) for d in dates]))
        years[year], previous = float(curve[idx[-1]]/previous-1), float(curve[idx[-1]])
    wins, losses = returns[returns > 0], returns[returns <= 0]
    behaviour = dict(days=float(np.mean([t['days'] for t in closed])) if closed else None,
        days_win=float(np.mean([t['days'] for t in closed if t['ret'] > 0])) if len(wins) else None,
        days_loss=float(np.mean([t['days'] for t in closed if t['ret'] <= 0])) if len(losses) else None,
        payoff=float(wins.mean()/-losses.mean()) if len(wins) and len(losses) and losses.mean() < 0 else None)
    return dict(win=float(np.mean(returns > 0)) if len(returns) else None, closed=len(closed),
        counts={y: sum(t['entry'].startswith(y) for t in trades) for y in years}, years=years,
        behaviour=behaviour)


def _trade_summary(trades):
    ret = [t['ret'] for t in trades if t['why'] != 'end']
    win, loss = [v for v in ret if v > 0], [v for v in ret if v <= 0]
    return dict(closed=len(ret), win=len(win)/len(ret) if ret else None,
                payoff=float(np.mean(win)/-np.mean(loss)) if win and loss and np.mean(loss) < 0 else None,
                days=float(np.mean([t['days'] for t in trades if t['why'] != 'end'])) if ret else None)


def g4(card, facts, trades, episodes, *, bought, three_layer):
    checks = [r for r in success.judge(card, facts) if r[0] in ('gate', 'count', 'behaviour')]
    def measure(parts):
        chosen = [t for t in trades if any(e['start'] <= t['entry'] <= e['end'] for e in parts)]
        return _trade_summary(chosen)
    folds = episode_folds(episodes, measure)
    ok = success.passed(checks) and bought is not None and bool(three_layer)
    return result('fail' if not ok else 'pass' if folds else 'unobserved',
                  'win <=35% (>=30 closed), >=52/year, sourced payoff / holding / counts within 20%',
                  checks=checks, bought=bought, three_layer=three_layer, folds=folds)


def g5(card, facts, curve, dates, episodes, *, diagnostics=None):
    checks = [r for r in success.judge(card, facts) if r[0] in ('nonnegative', 'years')]
    returns = np.asarray(curve, float)/np.r_[1., np.asarray(curve[:-1], float)]-1
    dates = np.asarray(dates, str)
    def measure(parts):
        mask = np.zeros(len(dates), bool)
        for e in parts:
            mask |= (dates >= e['start']) & (dates <= e['end'])
        return dict(days=int(mask.sum()), ret=float(np.prod(1+returns[mask])-1))
    folds = episode_folds(episodes, measure)
    return result('fail' if not success.passed(checks) else 'pass' if folds else 'unobserved',
        'each year nonnegative; sourced annual return log gap <=0.3; episode block omission is descriptive',
        checks=checks, folds=folds, diagnostics=diagnostics or {})


def g6(*, code_sha, data_sha, freeze, data_last, registered, forward_start, markets, robust, approved):
    missing = [name for name, ok in dict(code=bool(code_sha), data=bool(data_sha), freeze=freeze == data_last,
        registration=bool(registered), forward=forward_start == freeze,
        markets=set(markets) == {'us', 'hk', 'cn'}, robust=robust is not None).items() if not ok]
    return result('fail' if missing else 'pass' if approved is True else 'unobserved',
                  ', '.join(missing) if missing else 'freeze requires user approval' if approved is not True else 'ready',
                  code_sha=code_sha, data_sha=data_sha, freeze=freeze, approved=approved)


def allowed_actions(results):
    for key, allowed in ALLOWED.items():
        row = results.get(key)
        if not row or (row['status'] != 'pass' and not (key == 'G2' and row['numbers'].get('permitted'))):
            return dict(gate=key, allowed=list(allowed),
                        paired_downstream=['allocate', 'trade'] if key == 'G3' else [],
                        reason=row['reason'] if row else 'no evidence')
    return dict(gate=None, allowed=[], reason='pipeline complete')


def _merge(base, change):
    out = plain(base)
    for k, value in change.items():
        out[k] = _merge(out[k], value) if isinstance(value, dict) and isinstance(out.get(k), dict) else plain(value)
    return out


def validate_round(spec, base, *, legacy=False, gates=None):
    """Old frozen JSON is exempt. New JSON declares its layer before any arrays load."""
    if legacy and 'layer' not in spec:
        return dict(legacy=True)
    layer = spec.get('layer')
    if layer not in SECTIONS or not spec.get('upper_bound') and spec.get('upper_bound') != 0:
        raise ValueError('new round requires layer and upper_bound')
    if not spec.get('candidates') or len(spec['candidates']) > 5:
        raise ValueError('one to five candidates required')
    changed = set()
    normalized = plain(Config(base))
    for candidate in spec['candidates'].values():
        for change in (spec.get('base_change', {}), candidate):
            if set(change)-set(SECTIONS):
                raise ValueError('new candidates change sections, not flat aliases')
            trade = change.get('trade', {})
            if set(trade) & ALLOCATION_RULES or set(trade.get('rule_opts', {})) & ALLOCATION_RULES:
                raise ValueError('account admission rules belong to allocate')
        final = _merge(_merge(normalized, spec.get('base_change', {})), candidate)
        diff = {k for k in SECTIONS if final[k] != normalized[k]}
        if diff-{layer} and not (spec.get('paired') is True and spec.get('mechanism', '').strip()):
            raise ValueError('candidate changes another layer; paired mechanism required')
        changed |= diff
    if set(spec.get('sections_changed', [])) != changed:
        raise ValueError('sections_changed differs from actual candidate diff')
    if spec.get('paired') is True and not spec.get('mechanism', '').strip():
        raise ValueError('paired round requires mechanism')
    if gates is not None:
        allowed = allowed_actions(gates)
        if not changed.issubset(allowed['allowed']):
            paired = (spec.get('paired') is True and layer in allowed['allowed']
                and spec.get('selection_layer') == layer and bool(spec.get('selection_metric', '').strip())
                and changed.issubset(set(allowed['allowed']) | set(allowed.get('paired_downstream', []))))
            if not paired:
                raise ValueError('upstream gate blocks changes; paired work must select on the upstream metric: '+str(allowed))
    return dict(legacy=False, layer=layer, sections_changed=sorted(changed),
                selection_layer=spec.get('selection_layer', layer), selection_metric=spec.get('selection_metric'))
