"""PREREG_E15_CN: all 128 registered daily-bar execution combinations, sequential and resumable."""
from __future__ import annotations

import argparse
from contextlib import ExitStack
import csv
from dataclasses import replace
from datetime import date
import gc
from itertools import combinations
import json
import os
from pathlib import Path
import resource
from unittest.mock import patch

import numpy as np

from . import e14_research as P

B, M, Y, G, E, SP, TD, TP = P.B, P.M, P.Y, P.G, P.E, P.SP, P.TD, P.TP
ROOT, OUT, LIMIT = P.ROOT, P.OUT, P.LIMIT
WORK = OUT/'e15_work'
PREREG = M.STUDY.root/'notes/PREREG_E15_CN.md'
RESULT, SELECTED, VALIDATION = (OUT/f'e15_{n}.json' for n in ('train', 'selected', 'validation'))
CHECKS = OUT/'e15_checks.json'
FACTORS = dict(S=('W', 'SK'), T=('W', 'T0'), C=('W', 'CF'), A=('AE', 'A0'),
               H=('H21A', 'H21'), Z=('W', 'Z2'), M=('W', 'MD'))
SPECS = {f'C{i:03d}': {k: v[int(bit)] for (k, v), bit in zip(FACTORS.items(), f'{i:07b}')}
         for i in range(128)}
write, progress = P.write, P.progress


def update_checks(key, value):
    checks = json.loads(CHECKS.read_text(encoding='utf-8')) if CHECKS.exists() else {}
    checks[key] = value
    write(CHECKS, checks)


def fingerprints():
    paths = (PREREG, Path(__file__), ROOT/'studies/martin_luk/tests/test_ie47_e15.py',
             ROOT/'studies/trader_replication/gate.py', ROOT/'studies/trader_data/supplemental.py')
    return dict(P.fingerprints(), **{str(p.relative_to(ROOT)): SP.sha(p) for p in paths})


def candidate_rules(k2, spec):
    rules = P.candidate_rules(k2, spec)
    return replace(rules, proof_target_mult=4., max_position=.5) if spec['Z'] == 'Z2' else rules


class E15Study(P.E14Study):
    def build(self, A, cfg, trace=None):
        base, k2, base_mask, pool = super().build(A, dict(cfg, candidate='K2'))
        name = cfg.get('candidate', 'C000')
        if name == 'K2':
            return base, k2, base_mask, pool
        spec = cfg.get('spec') or self.specs.get(name) or SPECS[name]
        rules = candidate_rules(k2, spec)
        cache = A.setdefault('_e15_books', {})
        key = (spec['S'], spec['T'])
        if key not in cache:
            book, meta = P.retry_book(A, base, self.inputs(A), spec)
            # An entry's cap applies only to its probe; proof adds use the policy's 30% / 50% cap.
            probe_cap = k2.max_position if spec['S'] == 'SK' else .30
            book = [[tuple(e[:7])+(None, probe_cap)+tuple(e[9:]) for e in row] for row in book]
            cache[key] = book, meta
        book, meta = cache[key]
        if trace is not None:
            trace['trial_meta'] = meta
        mask = np.zeros_like(base_mask)
        for d, row in enumerate(book):
            for entry in row:
                mask[d, entry[1]] = True
        return book, rules, mask, pool


def setup(upto=None, specs=None):
    st = E15Study(specs)
    st.progress = progress
    A = st.arrays('us', upto=upto, mode='frozen')
    selected = st.selected(A)
    cfg = dict(profile_sha256=SP.sha(M.PROFILE), frozen_inputs_sha256=M.inputs_digest(selected['sources']),
               panel_digest=A['digest'])
    return st, A, cfg


def score(row):
    return min(row['by_year'][y] for y in ('2024', '2025'))


def select(runs):
    eligible = [n for n in SPECS if n in runs and runs[n]['maxdd'] <= .5 and
                all(runs[n]['by_year'][y] >= runs['K2']['by_year'][y] for y in ('2024', '2025'))]
    if not eligible:
        return [], None
    best = max(score(runs[n]) for n in eligible)
    near = [n for n in eligible if best-score(runs[n]) < .02]
    return eligible, min(near, key=lambda n: (-runs[n]['midpoint_his'], n))


def neighbors(name):
    return [f'C{int(name[1:]) ^ (1 << (6-i)):03d}' for i in range(7)]


def effects(runs):
    values = {int(n[1:]): score(runs[n]) for n in SPECS}
    main = {}
    for i, factor in enumerate(FACTORS):
        bit = 1 << (6-i)
        main[factor] = B.distribution([values[j | bit]-values[j] for j in range(128) if not j & bit])
    interactions = []
    for i, j in combinations(range(7), 2):
        a, b = 1 << (6-i), 1 << (6-j)
        delta = [values[k | a | b]-values[k | a]-values[k | b]+values[k]
                 for k in range(128) if not k & (a | b)]
        interactions.append(dict(factors=[tuple(FACTORS)[i], tuple(FACTORS)[j]], **B.distribution(delta)))
    interactions.sort(key=lambda r: -abs(r['median']))
    return main, interactions


def period_rows(days, equity, monthly, initial=1.):
    groups = {}
    for day, value in zip(days, equity):
        iso = date.fromisoformat(day).isocalendar()
        key = day[:7] if monthly else f'{iso.year}-W{iso.week:02d}'
        groups.setdefault(key, []).append((day, float(value)))
    rows, before = [], initial
    for key, group in groups.items():
        rows.append(dict(period=key, first=group[0][0], last=group[-1][0], sessions=len(group),
                         base=before, equity=group[-1][1], **{'return': group[-1][1]/before-1}))
        before = group[-1][1]
    return rows


def period_summary(months, weeks):
    m, w = [r['return'] for r in months], [r['return'] for r in weeks]
    return dict(months=len(m), month_median=B.median(m), month_positive=B.mean([r > 0 for r in m]),
                month_worst=min(m) if m else None, month_best=max(m) if m else None,
                weeks=len(w), week_positive=B.mean([r > 0 for r in w]), week_worst=min(w) if w else None)


def periods(curve):
    days, equity = curve['days'], curve['equity']
    def measure(ds, eq, initial):
        m, w = period_rows(ds, eq, True, initial), period_rows(ds, eq, False, initial)
        return dict(months=m, weeks=w, summary=period_summary(m, w))
    out = dict(all=measure(days, equity, 1.), annual={})
    for year in sorted({d[:4] for d in days}):
        ix = [i for i, d in enumerate(days) if d.startswith(year)]
        out['annual'][year] = measure([days[i] for i in ix], [equity[i] for i in ix],
                                      equity[ix[0]-1] if ix[0] else 1.)
    return out


def profit_sources(trades, rules):
    closed = G.closed(trades)
    def measure(rows):
        out = dict(closed=len(rows), unconfirmed_trade_u=0., confirmed_trade_u=0.,
                   phase_probe_u=0., phase_confirmed_u=0., phase_probe_pnl=0., phase_confirmed_pnl=0.,
                   total_pnl=sum(t['pnl'] for t in rows))
        for t in rows:
            label = 'confirmed' if t['confirmed'] else 'unconfirmed'
            out[label+'_trade_u'] += t['pnl']/t['risk_budget']
            cash, shares, probe = 0., 0., t['pnl']
            for e in t['executions']:
                if e['action'] == 'add':
                    probe = cash+shares*e['price']
                    break
                if e['action'] == 'entry':
                    cash -= e['shares']*e['price']*(1+rules.buy_cost)
                    shares += e['shares']
                else:
                    cash += e['shares']*e['price']*(1-rules.sell_cost)
                    shares -= e['shares']
            after = t['pnl']-probe
            for phase, pnl in (('probe', probe), ('confirmed', after)):
                out['phase_'+phase+'_pnl'] += pnl
                out['phase_'+phase+'_u'] += pnl/t['risk_budget']
        out['confirmed_phase_share_of_net_profit'] = (out['phase_confirmed_pnl']/out['total_pnl']
                                                      if out['total_pnl'] > 0 else None)
        out['reconciliation_error'] = out['phase_probe_pnl']+out['phase_confirmed_pnl']-out['total_pnl']
        return out
    return dict(all=measure(closed), annual={y: measure([t for t in closed if t['entry'].startswith(y)])
                                             for y in sorted({t['entry'][:4] for t in trades})})


def execution_audit(trades, rules, allow_add_exit=()):
    row = dict(ok=True, adds=0, max_budget_excess_u=0., violations=[])
    for t in trades:
        cash, shares, prior_stop, add_days = 0., 0., -np.inf, []
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
                    row['violations'].append(dict(code=t['code'], entry=t['entry'], excess_u=excess))
                prior_stop = e['stop']
        if len(add_days) != len(set(add_days)) or t['proof_adds'] > rules.proof_add_max or \
                (t['why'] != 'end' and t['why'] not in allow_add_exit and t['exit'] in add_days):
            row['violations'].append(dict(code=t['code'], entry=t['entry'], reason='add/exit timing'))
        if t.get('proof_trail_day') and t['why'] == 'trail' and t['exit'] <= t['proof_trail_day']:
            row['violations'].append(dict(code=t['code'], entry=t['entry'], reason='same-day trail switch'))
    row['ok'] = not row['violations']
    if not row['ok']:
        raise AssertionError('E15 execution risk/timing audit failed: '+str(row['violations'][:2]))
    return row


def baseline_check(stats, trades):
    result = {}
    for round_ in ('e13', 'e14'):
        reference = json.loads((OUT/f'{round_}_train.json').read_text(encoding='utf-8'))['runs']['K2']
        prior = json.loads((OUT/f'{round_}_work/K2_2024_trades.json').read_text(encoding='utf-8'))
        result[round_] = dict(ok=all(stats[k] == reference[k] for k in ('total', 'by_year', 'trades', 'win'))
                                 and trades == prior, trades=len(trades))
    update_checks('k2_e13_e14_bitwise', dict(ok=all(v['ok'] for v in result.values()), references=result))
    if not all(v['ok'] for v in result.values()):
        raise AssertionError('K2 differs from E13/E14')


def evaluate(st, A, cfg, name, legs, span, directory=WORK):
    directory.mkdir(exist_ok=True)
    with patch.object(P, 'update_checks', update_checks):
        stats = P.evaluate(st, A, cfg, name, legs, span, directory)
    prefix = directory/f'{name}_{span[0][:4]}'
    trades = json.loads(prefix.with_name(prefix.name+'_trades.json').read_text(encoding='utf-8'))
    curve = json.loads(prefix.with_name(prefix.name+'_curve.json').read_text(encoding='utf-8'))
    if name == 'K2' and span == E.TRAIN:
        baseline_check(stats, trades)
    rules = st.build(A, dict(cfg, candidate=name))[1]
    stats['periods'] = periods(curve)
    stats['profit_sources'] = profit_sources(trades, rules)
    stats['maxdd'] = float(np.max(1-np.r_[1., curve['equity']]/np.maximum.accumulate(np.r_[1., curve['equity']])))
    closed = G.closed(trades)
    winners = [t['ret_invested'] for t in closed if t['pnl'] > 0]
    losers = [t['ret_invested'] for t in closed if t['pnl'] <= 0]
    stats['account'] = dict(opened=len(trades), closed=len(closed), win=len(winners)/len(closed) if closed else None,
                           avg_win=B.mean(winners), avg_loss=B.mean(losers),
                           winners20=sum(t['ret_invested'] >= .2 for t in closed),
                           exposure=stats['mean_exposure'], margin=stats['margin'])
    if name != 'K2':
        stats['execution_audit'] = execution_audit(trades, rules)
    write(prefix.with_name(prefix.name+'_stats.json'), stats)
    return stats


def resume_record(stage, provenance):
    with patch.object(P, 'WORK', WORK):
        P.resume_record(stage, provenance)


def audit(st, A, cfg, focus):
    specs = {n: SPECS[n] for n in dict.fromkeys((focus, 'C000', 'C127'))}
    with patch.object(P, 'WORK', WORK), patch.object(P, 'CHECKS', CHECKS), \
            patch.object(P, 'update_checks', update_checks):
        P.audit_configurations(st, A, cfg, specs)
        P.corporate_action_basis(A)


def flatten(value, prefix=''):
    out = {}
    for key, item in value.items():
        name = prefix+str(key)
        if isinstance(item, dict):
            out.update(flatten(item, name+'_'))
        elif not isinstance(item, list):
            out[name] = item
    return out


def all_configs(runs):
    rows = []
    for name, spec in SPECS.items():
        if name not in runs:
            continue
        r = runs[name]
        data = dict(config=name, binary=f'{int(name[1:]):07b}', **spec, min_year=score(r),
                    total=r['total'], maxdd=r['maxdd'], closed=r['trades'], mean_exposure=r['mean_exposure'],
                    margin=r['margin'], exact_hit=r['his_exact']['bought'], exact_total=r['his_exact']['all'])
        data.update(flatten(r['annual'], 'annual_'))
        data.update(flatten(r['account'], 'account_'))
        data.update(flatten(r['legs'], 'legs_'))
        data.update(flatten(r['profit_sources'], 'profit_'))
        data.update(flatten(r['periods']['all']['summary'], 'period_all_'))
        for year, period in r['periods']['annual'].items():
            data.update(flatten(period['summary'], f'period_{year}_'))
        rows.append(data)
    if rows:
        fields = list(dict.fromkeys(k for row in rows for k in row))
        path = WORK/'all_configs.csv'
        temporary = path.with_suffix('.csv.tmp')
        with temporary.open('w', encoding='utf-8', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
        os.replace(temporary, path)


def train():
    if RESULT.exists() or SELECTED.exists():
        raise ValueError('E15 training already recorded; do not select again')
    sources = fingerprints()
    resume_record('train', sources)
    update_checks('train_before_memory', B.memory())
    st, A, cfg = setup()
    partial = RESULT.with_suffix('.partial.json')
    out = json.loads(partial.read_text(encoding='utf-8')) if partial.exists() else dict(
        preregistered_sha256=SP.sha(PREREG), source_sha256=sources, span=list(E.TRAIN), base=cfg, runs={})
    if out['source_sha256'] != sources or out['base'] != cfg:
        raise ValueError('partial E15 inputs or source changed')
    legs = B.main_legs(A, st.selected(A)['picks'])
    write(WORK/'evaluation_legs.json', legs)
    for name in ('K2',)+tuple(SPECS):
        if name in out['runs']:
            continue
        path = WORK/f'{name}_2024_stats.json'
        out['runs'][name] = json.loads(path.read_text(encoding='utf-8')) if path.exists() else \
            evaluate(st, A, cfg, name, legs, E.TRAIN)
        write(partial, out)
        all_configs(out['runs'])
        progress(f'E15 saved {len(out["runs"])-1}/128 configurations; RSS peak {B.memory()["peak_rss_mib"]:.0f} MiB')
    eligible, chosen = select(out['runs'])
    ranking = sorted(SPECS, key=lambda n: (-score(out['runs'][n]), n))
    main, interactions = effects(out['runs'])
    focus = chosen or ranking[0]
    out.update(eligible=eligible, chosen=chosen, focus=focus, ranking=ranking,
               main_effects=main, interactions=interactions, specs=SPECS)
    if chosen:
        adjacent = {n: score(out['runs'][n]) for n in neighbors(chosen)}
        out['robustness'] = dict(neighbors=adjacent, median=B.median(list(adjacent.values())),
                                  minimum=min(adjacent.values()))
    write(partial, out)
    audit(st, A, cfg, focus)
    write(RESULT, out)
    with SELECTED.open('x', encoding='utf-8') as stream:
        json.dump(dict(chosen=chosen, eligible=eligible, focus=focus, specs=SPECS,
                       preregistered_sha256=SP.sha(PREREG), source_sha256=sources,
                       train_sha256=SP.sha(RESULT)), stream, ensure_ascii=False, indent=1)
        stream.write('\n')
    update_checks('train_resources', dict(memory=B.memory(), address_space_limit=LIMIT,
                                         inputs_built_once=True, configurations=128))
    update_checks('validation_policy', dict(selected=chosen, measured=False,
                  reason='no eligible combination' if chosen is None else 'selected combination only, pending'))
    progress(f'E15 training complete: eligible={eligible}; chosen={chosen}; focus={focus}')


def validate():
    if VALIDATION.exists():
        raise ValueError('E15 validation already recorded')
    selected = json.loads(SELECTED.read_text(encoding='utf-8'))
    if selected['chosen'] is None:
        raise ValueError('No E15 combination eligible; 2026 must not be tested')
    if selected['source_sha256'] != fingerprints() or selected['train_sha256'] != SP.sha(RESULT):
        raise ValueError('E15 source or training changed after selection')
    resume_record('validation', dict(selected_sha256=SP.sha(SELECTED), **fingerprints()))
    st, A, cfg = setup()
    partial = VALIDATION.with_suffix('.partial.json')
    out = json.loads(partial.read_text(encoding='utf-8')) if partial.exists() else dict(
        chosen=selected['chosen'], selected_sha256=SP.sha(SELECTED), runs={}, full={},
        scope='one selected E15 combination; 2026 was used in prior research, no independent holdout')
    if out['selected_sha256'] != SP.sha(SELECTED):
        raise ValueError('partial validation selection changed')
    for key, span, directory in (('runs', E.VALIDATE, WORK/'validation'),
                                 ('full', (E.TRAIN[0], E.VALIDATE[1]), WORK/'full')):
        legs = B.main_legs(A, st.selected(A)['picks'], span)
        for name in ('K2', selected['chosen']):
            if name not in out[key]:
                path = directory/f'{name}_{span[0][:4]}_stats.json'
                out[key][name] = json.loads(path.read_text(encoding='utf-8')) if path.exists() else \
                    evaluate(st, A, cfg, name, legs, span, directory)
                write(partial, out)
    reference = json.loads((OUT/'e10_validation.json').read_text(encoding='utf-8'))
    baseline = reference['validate']
    same = all(out['runs']['K2'][k] == baseline[k] for k in ('total', 'by_year', 'trades', 'win'))
    update_checks('validation_k2_reference', dict(ok=same, actual=out['runs']['K2']['total'],
                                                reference=baseline['total']))
    if not same:
        raise AssertionError('K2 2026 differs from E10')
    write(VALIDATION, out)
    update_checks('validation_policy', dict(selected=selected['chosen'], measured=True, candidates=1))
    update_checks('validation_resources', dict(memory=B.memory(), address_space_limit=LIMIT))


def smoke():
    if (WORK/'smoke.json').exists():
        raise ValueError('E15 smoke already recorded')
    st, A, cfg = setup('2024-02-29')
    out = dict(span=['2024-01-02', '2024-02-29'], source_sha256=fingerprints(), runs={})
    for name in ('K2', 'C000', 'C127'):
        entries, rules, _, pool = st.build(A, dict(cfg, candidate=name))
        curve, _, trades = Y.simulate(st.px(A), st.ema_inputs(A, pool, rules), rules, entries, *out['span'], audit=True)
        out['runs'][name] = dict(total=float(curve[-1]-1), trades=len(G.closed(trades)), fills=G.check_fills(A, trades))
    write(WORK/'smoke.json', out)
    if not all(r['fills']['ok'] for r in out['runs'].values()):
        raise AssertionError('E15 smoke fills failed')
    progress('E15 smoke passed, January-February 2024 only')


def artifact_checks():
    train = json.loads(RESULT.read_text(encoding='utf-8'))
    selected = json.loads(SELECTED.read_text(encoding='utf-8'))
    provenance = dict(ok=selected['source_sha256'] == fingerprints() == train['source_sha256'] and
                         selected['train_sha256'] == SP.sha(RESULT) and
                         selected['preregistered_sha256'] == SP.sha(PREREG))
    update_checks('provenance', provenance)
    before = json.loads((WORK/'before_e15.json').read_text(encoding='utf-8'))
    protected = {p: SP.sha(ROOT/p) == h for p, h in before.items()}
    update_checks('protected_sources', dict(ok=all(protected.values()), files=protected))
    with (WORK/'all_configs.csv').open(encoding='utf-8', newline='') as stream:
        rows = list(csv.DictReader(stream))
    audits = [train['runs'][n]['execution_audit'] for n in SPECS]
    checks = json.loads(CHECKS.read_text(encoding='utf-8'))
    complete = dict(ok=len(rows) == 128 and {r['config'] for r in rows} == set(SPECS) and
                       all(a['ok'] for a in audits), csv_rows=len(rows),
                    adds=sum(a['adds'] for a in audits),
                    max_budget_excess_u=max(a['max_budget_excess_u'] for a in audits),
                    no_2026_if_ineligible=bool(train['chosen']) or not (WORK/'validation_started.json').exists())
    update_checks('complete_artifacts', complete)
    ok = provenance['ok'] and all(protected.values()) and complete['ok'] and complete['no_2026_if_ineligible']
    ok &= all(v['ok'] for v in checks.get('real_truncation', {}).values())
    ok &= all(v['ok'] for v in checks.get('gate_lookahead', {}).values())
    if not ok:
        raise AssertionError('E15 artifact checks failed')


def checks():
    with patch.object(B, 'WORK', WORK), patch.object(B, 'update_checks', update_checks):
        B.checks()
    if RESULT.exists():
        artifact_checks()


def report():
    train = json.loads(RESULT.read_text(encoding='utf-8'))
    checks = json.loads(CHECKS.read_text(encoding='utf-8'))
    runs, chosen, focus = train['runs'], train['chosen'], train['focus']
    def pct(x):
        return '—' if x is None else f'{100*x:+.1f}%'
    def weight(x):
        return '—' if x is None else f'{100*x:.1f}%'
    def number(x):
        return '—' if x is None else f'{x:.2f}'
    def desc(name):
        return '、'.join(k+':'+v for k, v in SPECS[name].items())
    lines = ['# E15：有效方向全组合与证实后仓位', '']
    if chosen:
        lines += [f'结论：**128 个组合中 {len(train["eligible"])} 个达标，按预登记选中 {chosen}；'
                  '它同时达到 K2 两个年度的收益门槛，且两年回撤不超过 50%。**', '']
    else:
        lines += ['结论：**128 个组合均未同时满足两个年度收益和回撤门槛，不采用；按预登记不测 2026。**', '']
    r = runs[focus]
    lines += [f'{"选中者" if chosen else "较差年收益第一名"} {focus}（{desc(focus)}）：'
              f'2024 {pct(r["by_year"]["2024"])}、2025 {pct(r["by_year"]["2025"])}、'
              f'两年 {pct(r["total"])}，最大回撤 {weight(r["maxdd"])}。', '',
              '本轮只执行[唯一任务书](../notes/PLAN_E15_CN.md)。[预登记](../notes/PREREG_E15_CN.md)先于单测、实现与冒烟；'
              '**用户批准的例外：128 个组合全部参加选择**。阈值固定，结果不回填规则。', '',
              '## 1. 主效应与值得保留的方向', '',
              '| 因子 | 档 0 → 档 1 | min-year 配对差中位（百分点） | P10 / P90（百分点） |',
              '|---|---|---|---|']
    for k, v in train['main_effects'].items():
        lines.append(f'| {k} | {FACTORS[k][0]} → {FACTORS[k][1]} | {100*v["median"]:+.2f} | '
                     f'{100*v["p10"]:+.2f} / {100*v["p90"]:+.2f} |')
    directions = sorted(train['main_effects'], key=lambda k: -abs(train['main_effects'][k]['median']))
    lines += ['', '按影响绝对值排序：'+'；'.join(
        f'{k} 的档 1 {"改善" if train["main_effects"][k]["median"] > 0 else "降低"}'
        f'较差年收益中位 {abs(100*train["main_effects"][k]["median"]):.2f} 个百分点' for k in directions)+'。',
        '每个效应来自其余六档完全相同的 64 个配对；它描述本轮配置内的平均方向，不能当作每个上下文都有效的保证。', '',
        '## 2. 最强的五对交互', '',
        '| 因子对 | 差中差中位（百分点） | P10 / P90（百分点） |', '|---|---|---|']
    for v in train['interactions'][:5]:
        lines.append(f'| {" × ".join(v["factors"])} | {100*v["median"]:+.2f} | '
                     f'{100*v["p10"]:+.2f} / {100*v["p90"]:+.2f} |')
    lines += ['', '固定其余五档的 32 个差中差：y11−y10−y01+y00。正值表示两项档 1 同时采用时存在额外改善，'
              '负值表示额外拖累；按中位绝对值排序，完整 21 对在 e15_train.json。', '',
              '## 3. min-year 前十与选择', '',
              '| 配置 | 二进制 STCAHZM | 2024 | 2025 | 两年 | 回撤 | 较差年 | 他段中点 | 合格 |',
              '|---|---|---|---|---|---|---|---|---|']
    for n in train['ranking'][:10]:
        v = runs[n]
        lines.append(f'| {n} | {int(n[1:]):07b} | {pct(v["by_year"]["2024"])} | {pct(v["by_year"]["2025"])} | '
                     f'{pct(v["total"])} | {weight(v["maxdd"])} | {pct(score(v))} | {v["midpoint_his"]} | '
                     f'{"是" if n in train["eligible"] else "否"} |')
    lines += ['', '编号按 S,T,C,A,H,Z,M 从高位到低位。资格使用本次 K2 未四舍五入年度收益；'
              '合格者先最大化较差年收益，与最高分差严格小于 2 个百分点时比他的段中点持有段数，再比编号。', '']
    if chosen:
        v = train['robustness']
        lines += [f'七个只翻一位邻居的较差年收益：中位 {pct(v["median"])}，最低 {pct(v["minimum"])}。'
                  '只报告，不参与选择。', '', '| 邻居 | 翻转因子 | 较差年 |', '|---|---|---|']
        for k, (n, value) in zip(FACTORS, v['neighbors'].items()):
            lines.append(f'| {n} | {k} | {pct(value)} |')
        lines += ['']
    else:
        gaps = [f'{y} 少 {100*(runs["K2"]["by_year"][y]-r["by_year"][y]):.2f} 个百分点'
                for y in ('2024', '2025') if r['by_year'][y] < runs['K2']['by_year'][y]]
        if r['maxdd'] > .5:
            gaps.append(f'回撤超过上限 {100*(r["maxdd"]-.5):.2f} 个百分点')
        lines += [f'{focus} 与资格门槛的差距：'+ '；'.join(gaps)+'。第一名只供诊断，不称选中。', '']
    lines += ['## 4. 详细表现与 K2 并列', '',
              '| 配置 | 年 | 收益 | 回撤 | 开仓/已平 | 胜率 | 平均赚/亏（实际投入） | ≥20%赢家 | 平均敞口 | 融资利息 | 确切日期 |',
              '|---|---|---|---|---|---|---|---|---|---|---|']
    for n in ('K2', focus):
        for year, v in runs[n]['annual'].items():
            lines.append(f'| {n} | {year} | {pct(v["ret"])} | {weight(v["maxdd"])} | {v["opened"]}/{v["closed"]} | '
                         f'{weight(v["win"])} | {pct(v["avg_win"])}/{pct(v["avg_loss"])} | {v["winners20"]} | '
                         f'{weight(v["exposure"])} | {weight(v["margin"])} | {v["his_exact"]["bought"]}/{v["his_exact"]["all"]} |')
        v = runs[n]['account']
        lines.append(f'| {n} | 两年 | {pct(runs[n]["total"])} | {weight(runs[n]["maxdd"])} | '
                     f'{v["opened"]}/{v["closed"]} | {weight(v["win"])} | {pct(v["avg_win"])}/{pct(v["avg_loss"])} | '
                     f'{v["winners20"]} | {weight(v["exposure"])} | {weight(v["margin"])} | '
                     f'{runs[n]["his_exact"]["bought"]}/{runs[n]["his_exact"]["all"]} |')
    lines += ['', '收益按连续账户自然年，交易统计按入场年归类且只计已平仓；融资利息为初始权益单位。'
              '确切日期沿用 E10：他的日期前 3 个交易日到后 2 日实际买入，2024–25 共 17 笔，只报告。', '',
              '### 周 / 月尺度', '',
              '| 配置 | 区间 | 月中位 | 正月占比 | 最差月 | 最好月 | 正周占比 | 最差周 | 月/周数 |',
              '|---|---|---|---|---|---|---|---|---|']
    def period_table(n, scope, v):
        return (f'| {n} | {scope} | {pct(v["month_median"])} | {weight(v["month_positive"])} | '
                f'{pct(v["month_worst"])} | {pct(v["month_best"])} | {weight(v["week_positive"])} | '
                f'{pct(v["week_worst"])} | {v["months"]}/{v["weeks"]} |')
    for n in ('K2', focus):
        lines.append(period_table(n, '2024–25', runs[n]['periods']['all']['summary']))
        for year, v in runs[n]['periods']['annual'].items():
            lines.append(period_table(n, year, v['summary']))
    lines += ['', '周按 ISO 年周、月按自然年月，以各期末权益相对上期期末计算；首期基准为初始权益。'
              '年度分布在年界重新分段并继承上年末权益，首末不完整周/月均保留；全年周数之和可多于整体周数。', '',
              '### 利润来源', '',
              '| 配置 | 区间 | 未证实整笔 U | 已证实整笔 U | 试单阶段 U | 证实阶段 U | 证实阶段/净盈利 |',
              '|---|---|---|---|---|---|---|']
    for n in ('K2', focus):
        for scope, v in [('两年', runs[n]['profit_sources']['all']), *runs[n]['profit_sources']['annual'].items()]:
            lines.append(f'| {n} | {scope} | {number(v["unconfirmed_trade_u"])} | {number(v["confirmed_trade_u"])} | '
                         f'{number(v["phase_probe_u"])} | {number(v["phase_confirmed_u"])} | '
                         f'{weight(v["confirmed_phase_share_of_net_profit"])} |')
    lines += ['', '前两列保留 E14 按整笔是否证实的分组。阶段拆分以第一次实际证实加仓前的收盘市值划分，'
              '证实加仓费用归后段；两阶段之和逐笔等于交易净损益。占比按现金金额而非 U 比率计算，'
              '前段亏损时可超过 100%，净亏损不称盈利比例。融资利息单列，期末未平仓不计已实现。', '',
              '### 主升浪的中点与 1/3 仓位', '',
              '| 配置 | 段类 | 年 | 位置 | 总段/可评/删失 | 持有段 | 仓位均值（持有段） | 仓位中位（持有段） |',
              '|---|---|---|---|---|---|---|---|']
    for n in ('K2', focus):
        for group, title in (('his', '他的'), ('pool', '池内')):
            for year, v in runs[n]['legs'][group].items():
                for point, title2 in (('midpoint', '中点'), ('third', '1/3')):
                    p = v[point]
                    lines.append(f'| {n} | {title} | {year} | {title2} | {v["n"]}/{p["observed"]}/{p["censored"]} | '
                                 f'{p["held"]} | {weight(p["mean"])}（{weight(p["held_mean"])}） | '
                                 f'{weight(p["median"])}（{weight(p["held_median"])}） |')
    lines += ['', '沿用 E13/E14 的 ≥50% 主升浪、60 日峰谷窗口与删失。未来峰谷只作评估标签，不进入决策；'
              '均值/中位包含零仓位，括号内仅含持有段。', '']
    if chosen:
        validation = json.loads(VALIDATION.read_text(encoding='utf-8'))
        lines += ['## 5. 2026 一次验证与全段', '',
                  '| 配置 | 区间 | 收益 | 最大回撤 | 已平仓 |', '|---|---|---|---|---|']
        for key, label in (('runs', '2026-01-01–10-16'), ('full', '2024-01-02–2026-10-16')):
            for n in ('K2', chosen):
                v = validation[key][n]
                lines.append(f'| {n} | {label} | {pct(v["total"])} | {weight(v["maxdd"])} | {v["trades"]} |')
        lines += ['', '| 配置 | 区间 | 月中位 | 正月占比 | 最差月 | 最好月 | 正周占比 | 最差周 | 月/周数 |',
                  '|---|---|---|---|---|---|---|---|---|']
        for key, label in (('runs', '2026'), ('full', '全段')):
            for n in ('K2', chosen):
                lines.append(period_table(n, label, validation[key][n]['periods']['all']['summary']))
        lines += ['', '2026 单段从初始权益 1 开始，全段为连续账户；2026 年 10 月截至 16 日，保留部分月。'
                  '2026 已用于此前研究，本次一次验证不授予独立样本外资格。', '']
    lines += ['## 6. 未来函数与工程检查', '']
    for n, v in checks.get('real_truncation', {}).items():
        lines.append(f'- 真实截断 2025-06-30，{n}：{v["events_full"]}/{v["events_cut"]} 条成交事件逐位一致={v["ok"]}；'
                     f'入场/再试簿一致={v["books_bitwise"]}，选股差异 {v["n_nights_different"]} 晚。')
    for n, v in checks.get('gate_lookahead', {}).items():
        lines.append(f'- gate.check_lookahead，{n}：通过={v["ok"]}；2024-09-30、2025-09-30。')
    a = checks['complete_artifacts']
    basis = checks['corporate_action_basis']
    lines += ['- 合成未来乘三与打乱覆盖全部 128 个组合的过去信号、入场/再试簿与逐笔；单测覆盖放大股数、50% 上限、'
              '试单不放大、1U 上限（含费用和 float32 报价）及收盘离场优先。',
              f'- 128 组真实现金流独立复核：{a["adds"]} 次加仓，计划止损风险均 ≤1U；最大浮点超差 '
              f'{a["max_budget_excess_u"]:.2g}U；同时核对加仓次数、止损只上移和次日切换。跳空仍可越过计划止损。',
              '- K2 与 E10/E11 原始逐笔、账户指标逐位一致；与 E13/E14 的完整标注逐笔、账户指标逐位一致。'
              '共享引擎、登记版、看板、E13/E14 实现的运行前后指纹不变。',
              f'- 公司行动另行复核：先裁原始行情与行动后重建。截止日后有行动 {basis["future_action_codes"]} 只，'
              f'历史基准改变 {basis["earlier_price_codes_changed"]} 只；比例最大相对偏差 '
              f'{basis["max_relative_scale_error"]:.2g}。共享加载器先全段复权后裁切，前缀检查通过不证明未来公司行动可得。']
    for n, v in checks['tests'].items():
        lines.append(f'- {n} 全量测试：'+('通过' if v['ok'] else '失败')+'；'+
                     '；'.join(s for s in v['summary'] if s.startswith(('Ran ', 'OK', 'FAILED')))+'。')
    lines += ['', '## 7. 照记与工件', '',
              '- 128 组按编号单进程顺序执行，输入、选股与信号仅构建一次并复用；每组立即保存 stats、逐笔、曲线、逐段、partial 与 CSV。'
              '源码/输入指纹不同拒绝续跑，train 及 validate 完成结果拒绝覆盖。',
              f'- 研究 RLIMIT_AS={LIMIT:,} 字节，按 64 列临时块；训练峰值 RSS '
              f'{checks["train_resources"]["memory"]["peak_rss_mib"]:.1f} MiB。测试子进程保留系统地址空间限制供 Go 密钥扫描器启动，'
              '三套全量测试顺序运行，未跳过密钥检查。',
              '- 未取新数据、未用小时线、未冻结、未提交、未改登记版和看板。已有密钥 hooksPath 已核对继续使用，未覆盖。',
              '- 首次构建输入时修正 SK 试单上限：继承 K2 已有的 25%，证实后仍按 Z 的 30%/50%。'
              '中止时尚无任何账户结果；原实现、预登记和日志保留于 e15_work/setup_correction/，修正后重跑同窗冒烟。',
              '- 本轮是已使用数据上的 128 次组合选择；因子效应与交互只能归于这些规则、数据与账户约束，'
              '不能推广为否定交易员或获得生产资格。',
              '- [128 行全表](e15_work/all_configs.csv)包含每组分年账户、周月、利润与主升浪尺子；'
              '[训练](e15_train.json)、[一次选择](e15_selected.json)、[检查](e15_checks.json)。'
              '完整每周/月收益与阶段归因在各配置 stats.json；真实逐笔、曲线与逐段在 e15_work/。', '',
              '```bash',
              'PYTHONUTF8=1 OPENBLAS_NUM_THREADS=1 /opt/opend-us-options/.venv/bin/python -m studies.martin_luk.e15_research checks',
              'PYTHONUTF8=1 OPENBLAS_NUM_THREADS=1 /opt/opend-us-options/.venv/bin/python -m studies.martin_luk.e15_research report',
              '```', '', 'checks / report 可复核已存工件；train / validate 完成记录不得覆盖。', '']
    (OUT/'E15_CN.md').write_text('\n'.join(lines), encoding='utf-8')
    progress('E15 Chinese report rendered from completed artifacts')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('stage', choices=('smoke', 'train', 'validate', 'checks', 'report'))
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
            {'smoke': smoke, 'train': train, 'validate': validate}[stage]()
