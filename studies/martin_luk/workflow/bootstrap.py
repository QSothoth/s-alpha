"""Offline WF00 stages. Existing policies only; never launches WF01."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import asdict
from datetime import datetime, timezone
import gc
import hashlib
import json
import os
from pathlib import Path
import resource
import re
import sys

import numpy as np

from . import adapter as D
from studies.trader_replication import datasets, funnel, ledger, mainleg, pipeline, regime

ROOT, HOME, FLOW, OUT = D.ROOT, D.HOME, D.FLOW, D.OUT
read, write = D.read, D.write


def resources():
    relative = next(s.split(':', 2)[2].strip() for s in Path('/proc/self/cgroup').read_text().splitlines()
                    if s.startswith('0:'))
    folder = Path('/sys/fs/cgroup')/relative.lstrip('/')
    return dict(python=sys.executable, cpu_max=(folder/'cpu.max').read_text().strip(),
        memory_max=(folder/'memory.max').read_text().strip(),
        peak_rss_mib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024,
        threads=next(s.split(':')[1].strip() for s in Path('/proc/self/status').read_text().splitlines()
                     if s.startswith('Threads:')))


def config():
    plan = 'studies/martin_luk/workflow/rounds/WF00/PLAN_CN.md'
    goal = [
        ('2026-11-08', '不要收益最高，要在框架内最像他，各项差距 ≤20%，每年不亏，收益也不能差太多（尤其 2025）', 'replicate-like-him-not-best.md'),
        ('2026-11-07', '大资金一定要花在他的票上', 'coverage-needs-purity.md'),
        ('2026-11-08', '只用日 K，不能撒网，瞄准盈亏比和低胜率', 'replicate-like-him-not-best.md'),
        ('2026-11-08', '最终追求对他持仓的覆盖', 'replicate-like-him-not-best.md'),
        ('2026-11-08', '可以放入单看是负向、但更像他的人性条件', 'replicate-like-him-not-best.md'),
        ('2026-11-05', '一套画像套所有行情不算拟合，要分行情，并且对得上他的原话、作为策略讲得通', 'fit-regime-and-interpretability.md'),
        ('2026-11-09', '选股和交易要拆开各自做成立，再合并', 'replication-dynamic-workflow.md')]
    source2024 = 'studies/martin_luk/notes/SOURCES.md（2024年104胜319负、平均赚15%/亏3%、收益283%）'
    source2025 = 'studies/martin_luk/notes/SOURCES.md（2025年209胜731负、平均赚14.1%/亏2.1%、收益969.8%）'
    cards = {}
    for year, wins, losses, avgwin, avgloss, ret, source in (
            ('2024', 104, 319, .15, .03, 2.83, source2024),
            ('2025', 209, 731, .141, .021, 9.698, source2025)):
        cards[year] = dict(win=wins/(wins+losses), n=wins+losses, payoff=avgwin/avgloss,
            days=None, **{'return': ret}, sources=dict.fromkeys(('win', 'n', 'payoff', 'return'), source))
    systems = {}
    def add(name, account, picks, recipe, prefix=False):
        systems[name] = dict(account='studies/martin_luk/reports/'+account, prefix=prefix,
            picks='studies/martin_luk/reports/'+picks, recipe=recipe, source='frozen',
            replay='adapter.load_account; funnel.run; registered systems are unchanged')
    add('master', 'p4_work/a1/master', 's0_work/picks/master_filtered.json', 'R74+S7真实台账；P4 A1与D1逐位一致')
    add('M3B', 'm3_work/validation/continuous', 's0_work/picks/M3B.json', 'M3B连续账户、保存规则与逐笔准入JSONL')
    add('X1_OPEN', 'p4_work/accounts/X1_OPEN', 's0_work/picks/IE9.json', 'P4固定IE9点名，次日开盘执行')
    for name in ('S1_NOBLOCK', 'S2_CLOSESTOP', 'S3_BOTH'):
        add(name, 'p5_work/accounts/'+name, 'p5_work/accounts/'+name+'/nominations.json.gz', 'P5保存连续账户；原始IE9排序，按各自冷却和首5日止损')
    add('IE9_master', 'p4_work/a1/IE9_master', 's0_work/picks/IE9.json', 'P4 X3对照：IE9名单加master原触发；不是A2的X3_UNION')
    add('C062', 'e21_work/BASE_full/C062_2024', 's0_work/picks/IE47.json', 'E15 C062原IE47账户（E21 BASE逐位沿用）；master换名版本另见历史报告', True)
    add('K2', 'e15_work/full/K2_2024', 's0_work/picks/IE47.json', 'E15 K2连续账户；E10 AS+X1原执行', True)
    items = []
    for name in ('trader-data-v1', 'trader-options-v1', 'trader-hourly-v1', 'martin-luk-benchmarks-v1'):
        path = ROOT/'data'/name
        print('inventory', name, flush=True)
        manifest = path/'CHECKSUMS.sha256'
        items.append(dict(name=name, release_tag={'trader-data-v1': 'trader-data-v1',
            'trader-options-v1': 'trader-pack-20261025', 'trader-hourly-v1': 'trader-hourly-v1',
            'martin-luk-benchmarks-v1': None}[name],
            path=str(path.relative_to(ROOT)), checksums_sha256=datasets.sha(manifest) if manifest.exists() else None,
            checksum_issue=None if manifest.exists() else '现有数据集缺CHECKSUMS；禁止WF00补写，check必须失败',
            schema=datasets.inventory(path)))
    evaluation = [dict(path=str(p.relative_to(ROOT)), sha256=datasets.sha(p), usage='evaluation_only')
                  for p in (HOME/'notes/trades.csv', HOME/'notes/legs_frozen.json')]
    cfg = dict(version=1, study='martin_luk',
        goal=[dict(date=date, quote=quote, source=plan, memory_reference=memory,
                   verification='任务书授权原话；本机对应记忆核对，非新收集的一手交易资料') for date, quote, memory in goal],
        datasets=dict(approved_by_user=None, items=items, evaluation=evaluation,
            derived_caches=[dict(path='data/trader-data/cache', producer='studies.trader_data.panel',
                                 source_datasets=['trader-data-v1'])]),
        hard_lines=dict(annual_return_min=0., max_win=.35, min_closed=30, min_entries_per_year=52,
                        behaviour_tolerance=.2, max_log_return_gap=.3),
        accept=dict(regime=dict(min_agreement=.9), selection=dict(min_extra_legs=3,
            max_unlimited_mean_new_names=5., max_unique_growth=.2), trading=dict(min_extra_legs=3),
            conversion=dict(min_extra_legs=3), merge=dict(min_extra_legs=3)),
        checkpoint=dict(default_rounds=3, no_progress_rounds=2, review_failures=2),
        selection_years=['2024', '2025'], holdout=dict(year='2026', label='留出*', independent=False,
            note='已反复查看，只作历史留出；WF00只回放基线，不根据它选执行'),
        legs=dict(path=evaluation[1]['path'], sha256=evaluation[1]['sha256']),
        bar='master', reference_accounts=['master', 'M3B'], systems=systems,
        behaviour_card=cards, components=dict(selection=dict(common=dict(version='IE9'), by_state={}),
            trading=dict(common={}, by_state={}), conversion=dict(common=dict(version='master_allocate'), by_state={})))
    assert cfg['legs']['sha256'] == 'af4618772ad79596afbae54809f8180e34f73a8e81fbfe4f48eebfe1ec32bdf2'
    write(FLOW/'config.json', cfg)


def selection():
    A, legs, result = D.market(), D.labels(), {}
    ci = {str(c): j for j, c in enumerate(A['codes'])}
    opens = {g['code']: A['open'][:, ci[g['code']]] for g in legs}
    states = D.state_labels(A)
    paths = dict(IE9='s0_work/picks/IE9.json', IE47='s0_work/picks/IE47.json',
                 P3_C2='p3_work/picks/C2_NEAR21.json', P2B_B3='p2b_work/picks/B3_RAW_ZIP.json')
    for name, path in paths.items():
        picks = D.indexed(A, D.REPORTS/path)
        score = mainleg.signal_coverage_budget(picks, None, legs, list(A['days']), opens, 3)
        wide = mainleg.signal_coverage_budget(picks, None, legs, list(A['days']), opens, None)
        if name == 'IE47':
            possible = defaultdict(list)
            with np.load(D.REPORTS/'e1_work/selection.npz') as z:
                for t, j in zip(z['row_t'], z['row_j']):
                    possible[int(t)].append(str(A['codes'][j]))
        else:
            possible = {t: A['ordered'].get(str(day), []) for t, day in enumerate(A['days'][:-1])}
        reachable = {}
        for g in legs:
            reachable[g['key']] = any(g['code'] in possible.get(t, ()) and np.isfinite(opens[g['code']][t+1])
                and opens[g['code']][t+1] > 0 and (g['top']/opens[g['code']][t+1]-1)/g['gain'] >= .5-1e-12
                for t in range(max(0, g['first']-4), min(g['peak']-1, len(A['days'])-1)))
        for y, annual in score['annual'].items():
            annual['unlimited_mean_new_names'] = wide['annual'][y]['mean_new_names']
            annual['unlimited_unique_names'] = wide['annual'][y]['unique_names']
            annual['reachable'] = sum(reachable[g['key']] for g in legs if str(A['days'][g['first']]).startswith(y))
            annual['by_state'] = {}
            for s in regime.NAMES:
                rows = [r for g, r in zip(legs, score['per_leg']) if r['year'] == y and states[g['first']] == s]
                nights = [t for t in wide['picks'] if str(A['days'][t]).startswith(y) and states[t] == s]
                names = [c for t in nights for c in wide['picks'][t]]
                annual['by_state'][s] = dict(n=len(rows), covered=sum(r['covered'] for r in rows),
                    reachable=sum(reachable[g['key']] for g in legs if str(A['days'][g['first']]).startswith(y) and states[g['first']] == s),
                    unlimited_mean_new_names=len(names)/len(nights) if nights else None,
                    unique_names=len({c for t in nights for c in score['picks'][t]}),
                    unlimited_unique_names=len(set(names)))
        score.pop('picks')
        score.update(source=path, unlimited=wide['annual'], reachable_per_leg=reachable,
            upper_bound_policy='同一冻结候选池与合格夜，忽略K/冷却冲突的乐观上限；B3/C2以IE9共同上游池作宽松上限')
        result[name] = score
        print('selection', name, {y: (r['covered'], r['n']) for y, r in score['annual'].items() if y >= '2024'}, flush=True)
    assert [result['IE9']['annual'][y]['covered'] for y in ('2024', '2025', '2026')] == [3, 14, 11]
    write(OUT/'selection.json', result)


def accounts():
    A, cfg = D.market(), read(FLOW/'config.json')
    for name in cfg['systems']:
        value = D.run(name, A)
        write(OUT/'funnels'/f'{name}.json', value)
        print('funnel', name, value['total']['early'], value['total']['peak_held'], value['total']['layers'], flush=True)
        del value
        gc.collect()


def regime_stage():
    A, cfg = D.market(), read(FLOW/'config.json')
    from .. import p5_policy as P5
    picks = P5.nominations(A, 'S3_BOTH')
    A['nominations'] = picks
    measured = regime.states(A, dict(producer='B4_PCT2'))
    old = read(D.REPORTS/'p5_work/regimes/B4_PCT2.json')
    assert list(measured['label']) == old['full_label'], 'B4 state replay mismatch'
    end = int(np.searchsorted(A['days'], '2025-12-31', side='right'))
    cut = {k: v[:end] if isinstance(v, np.ndarray) and k != 'codes' else v for k, v in A.items()}
    cut['nominations'] = {t: cs for t, cs in picks.items() if t < end-1}
    np.testing.assert_array_equal(regime.states(cut, dict(producer='B4_PCT2'))['label'], measured['label'][:end])
    stable = regime.stability(cut, dict(producer='B4_PCT2'), ('2024-01-02', '2025-12-31'))
    stable['lookahead_ok'] = True
    expected = read(D.REPORTS/'p5_work/regimes/train/B4_PCT2.json')['stability']
    assert stable['minimum'] == expected['minimum'], (stable['minimum'], expected['minimum'])
    states, split, monthly = D.state_labels(A), {}, {}
    for name in cfg['reference_accounts']:
        record = D.load_account(name)
        split[name], monthly[name] = {}, {}
        di = {str(d): t for t, d in enumerate(A['days'])}
        prior, daily = 1., {}
        for day, eq in zip(record['curve']['days'], record['curve']['equity']):
            daily[day], prior = eq/prior, eq
        for year in ('2024', '2025', '2026'):
            split[name][year] = {s: float(np.prod([v for d, v in daily.items()
                if d.startswith(year) and states[di[d]] == s])-1)
                if any(d.startswith(year) and states[di[d]] == s for d in daily) else None for s in regime.NAMES}
        for month in sorted({d[:7] for d in daily}):
            monthly[name][month] = float(np.prod([v for d, v in daily.items() if d.startswith(month)])-1)
    decision = pipeline.freeze_switch(stable, split, cfg)
    rows = []
    ci, di = {str(c): j for j, c in enumerate(A['codes'])}, {str(d): t for t, d in enumerate(A['days'])}
    for trade in ledger.load(HOME/'notes/trades.csv'):
        day = trade.entry_date
        if not day or day not in di:
            rows.append(dict(id=trade.id, precision=trade.precision, date=day or None,
                side=trade.side, setup=trade.setup, state=None, reason='无确定日期或不在冻结日历'))
            continue
        t, code = di[day], 'US.'+trade.ticker
        j = ci.get(code)
        point = dict(id=trade.id, date=day, year=day[:4], month=day[:7], state=states[t],
                     precision=trade.precision, side=trade.side, setup=trade.setup, ticker=code)
        for key in ('to20', 'adr'):
            values = A[key][max(0, t-1)]
            v = values[j] if j is not None else np.nan
            valid = values[np.isfinite(values)]
            rank = float(np.sum(valid <= v)/len(valid)) if len(valid) and np.isfinite(v) else None
            point[key+'_percentile'] = rank
        rows.append(point)
    def profile(parts):
        return dict(n=len(parts), sides=dict(Counter(r['side'] for r in parts)),
            shapes=dict(Counter(r['setup'] for r in parts)),
            precision=dict(Counter(r['precision'] for r in parts)),
            turnover_percentile_median=float(np.median([r['to20_percentile'] for r in parts if r.get('to20_percentile') is not None]))
                if any(r.get('to20_percentile') is not None for r in parts) else None,
            adr_percentile_median=float(np.median([r['adr_percentile'] for r in parts if r.get('adr_percentile') is not None]))
                if any(r.get('adr_percentile') is not None for r in parts) else None)
    observed = [r for r in rows if r.get('state') is not None]
    portrait = {key: {value: profile([r for r in observed if r[key] == value])
                     for value in sorted({r[key] for r in observed})} for key in ('year', 'month', 'state')}
    portrait['year_state'] = {y: {s: profile([r for r in observed if r['year'] == y and r['state'] == s])
        for s in regime.NAMES} for y in ('2024', '2025', '2026')}
    for name in cfg['reference_accounts']:
        print('regime', name, split[name], flush=True)
    write(OUT/'regime.json', dict(definition=measured['spec'], spec_sha=measured['spec_sha'],
        stability=stable, reference_returns=split, decision=decision, monthly_accounts=monthly,
        public_profile=portrait, public_rows=rows, calendar=list(A['days']), label=list(states),
        counts=measured['counts'], episodes=measured['episodes'],
        consistency=dict(full_B4_exact=True, training_prefix_exact=True, stability_exact=True),
        sample_note='不比较台账笔数密度；2026为已用历史留出*；无样本状态标未观测'))
    import csv
    with (OUT/'july_august_states.csv').open('w', newline='') as stream:
        writer = csv.writer(stream)
        writer.writerow(['date', 'state'])
        writer.writerows((str(day), state) for day, state in zip(A['days'], states)
                        if '2026-07-01' <= str(day) <= '2026-08-31')
    print('freeze_switch', decision['status'], flush=True)


def bench():
    A, legs, cfg = D.market(), D.labels(), read(FLOW/'config.json')
    D.execution_inputs(A)
    A['master_filtered'] = D.master_books(A)['filtered']
    own = D.indexed(A, D.REPORTS/'s0_work/picks/IE9.json')
    states, ci = D.state_labels(A), {str(c): j for j, c in enumerate(A['codes'])}
    calendar, di = list(map(str, A['days'])), {str(d): t for t, d in enumerate(A['days'])}
    result, training_results = {}, {}
    for name in ('master', 'C062', 'K2', 'X1_OPEN', 'S3_BOTH'):
        train_record, train_rules, _ = funnel.execution_bench(A, legs, own,
            lambda market, picks: D.execution(market, picks, name, profile=cfg['capital']['acceptance_profile'],
                                              end='2025-12-31'))
        train_cov = funnel.holding_coverage(A, train_record, train_rules, legs)
        train_assigned = []
        for trade in train_record['trades']:
            g = mainleg.leg_at(trade['code'], di[trade['entry']], legs, trade['fill']) if trade['side'] > 0 else None
            train_assigned.append(dict(trade, leg=g['key'] if g else None,
                                       anchor_year=calendar[g['first']][:4] if g else None))
        training = dict(annual={}, selection={})
        for year in cfg['selection_years']:
            part = [r for r in train_cov if r['year'] == year]
            training['annual'][year] = dict(peak_held=sum(r['peak_held'] is True for r in part),
                peak_unknown=sum(r['peak_held'] is None for r in part),
                by_state={s: dict(n=sum(r['year'] == year and states[g['first']] == s for g, r in zip(legs, train_cov)),
                    peak_held=sum(r['year'] == year and states[g['first']] == s and r['peak_held'] is True for g, r in zip(legs, train_cov)),
                    peak_unknown=sum(r['year'] == year and states[g['first']] == s and r['peak_held'] is None for g, r in zip(legs, train_cov)))
                    for s in regime.NAMES})
        hs = [t for t in train_assigned if t['anchor_year'] in cfg['selection_years'] and t['why'] != 'end']
        training['selection'] = dict(his_mean_r=float(np.mean([t['r'] for t in hs])) if hs else None,
            control_pnl=sum(t['pnl'] for t in train_assigned if t['leg'] is None),
            behaviour_within=sum(funnel.behaviour_gap(funnel.trade_stats([t for t in train_assigned if t['entry'].startswith(y)]),
                cfg['behaviour_card'][y], cfg['hard_lines']['behaviour_tolerance'])['within'] for y in cfg['selection_years']))
        write(OUT/'work'/f'bench_train_{name}.json', training)
        training_results[name] = training
        del train_record, train_assigned
    reference = read(OUT/'work/bench_train_master.json')
    for row in reference['annual'].values():
        row['peak_held'] += row['peak_unknown']
    decisions = {name: pipeline.accept('trading', row, reference, cfg)
                 for name, row in training_results.items() if name != 'master'}
    accepted = [n for n, d in decisions.items() if d['status'] == 'accepted']
    chosen = max(accepted, key=lambda n: (sum(training_results[n]['annual'][y]['peak_held'] for y in cfg['selection_years']),
        training_results[n]['selection']['his_mean_r'])) if accepted else 'master'
    write(OUT/'bench_decision.json', dict(chosen=chosen, accepted=accepted, comparisons=decisions,
        fallback='master execution on bench only; not master turnover stock selection',
        holdout_used_for_selection=False, cross_year_policy='candidate lower bound versus master upper bound',
        timestamp=datetime.now(timezone.utc).isoformat()))
    for name in ('master', 'C062', 'K2', 'X1_OPEN', 'S3_BOTH'):
        training = training_results[name]
        record, rules, inputs = funnel.execution_bench(A, legs, own,
            lambda market, picks: D.execution(market, picks, name, profile=cfg['capital']['acceptance_profile']))
        write(OUT/'bench_accounts'/f'{name}.json', dict(record=record, rules=asdict(rules)))
        cov = funnel.holding_coverage(A, record, rules, legs)
        assigned = []
        for trade in record['trades']:
            g = mainleg.leg_at(trade['code'], di[trade['entry']], legs, trade['fill']) if trade['side'] > 0 else None
            assigned.append(dict(trade, leg=g['key'] if g else None,
                anchor_year=calendar[g['first']][:4] if g else None,
                state=states[di[trade['entry']]]))
        annual = {}
        prior = 1.
        for year in ('2024', '2025', '2026'):
            all_trades = [t for t in assigned if t['entry'].startswith(year)]
            his = [t for t in assigned if t['anchor_year'] == year]
            controls = [t for t in all_trades if t['leg'] is None]
            eq = [e for d, e in zip(record['curve']['days'], record['curve']['equity']) if d.startswith(year)]
            stats = funnel.trade_stats(all_trades)
            stats['return'], prior = eq[-1]/prior-1, eq[-1]
            counts = [r for r in cov if r['year'] == year]
            annual[year] = dict(n=len(counts), peak_held=sum(r['peak_held'] is True for r in counts),
                early=sum(r['covered'] for r in counts), his=funnel.trade_stats(his), control=funnel.trade_stats(controls),
                account=stats, behaviour_gap=funnel.behaviour_gap(stats, cfg['behaviour_card'].get(year, {}),
                    cfg['hard_lines']['behaviour_tolerance']), by_state={})
            for state in regime.NAMES:
                part = [r for g, r in zip(legs, cov) if r['year'] == year and states[g['first']] == state]
                h = [t for t in his if states[next(g['first'] for g in legs if g['key'] == t['leg'])] == state]
                annual[year]['by_state'][state] = dict(n=len(part), peak_held=sum(r['peak_held'] is True for r in part),
                    early=sum(r['covered'] for r in part), his=funnel.trade_stats(h),
                    control=funnel.trade_stats([t for t in controls if t['state'] == state]),
                    account=funnel.trade_stats([t for t in all_trades if t['state'] == state]))
        chosen_his = [t for t in assigned if t['anchor_year'] in cfg['selection_years']]
        chosen_control = [t for t in assigned if t['leg'] is None and t['entry'][:4] in cfg['selection_years']]
        closed = [t for t in chosen_his if t['why'] != 'end']
        selection_metrics = dict(his_mean_r=float(np.mean([t['r'] for t in closed])) if closed else None,
            control_pnl=sum(t['pnl'] for t in chosen_control),
            behaviour_within=sum(annual[y]['behaviour_gap']['within'] for y in cfg['selection_years']))
        result[name] = dict(annual=annual, selection=selection_metrics, per_leg=cov,
            attribution=assigned, rules=asdict(rules), training=training,
            input_policy='IE9同晚非活动段的票作对照，同账户同执行；自身点名顺序优先，新增票按代码排；仅多头',
            labels_visible_to_execution=False, selection_years=cfg['selection_years'])
        print('bench', name, {y: (r['peak_held'], r['his']['pnl'], r['control']['pnl']) for y, r in annual.items()}, flush=True)
        del record
        gc.collect()
    write(OUT/'bench.json', result)


def audit():
    """Read every registered saved account under a real open-event recorder."""
    cfg, current, opened = read(FLOW/'config.json'), [''], defaultdict(set)
    def record(event, args):
        if event == 'open' and not isinstance(args[0], int):
            path = Path(os.fsdecode(args[0])).resolve()
            if path.is_relative_to((ROOT/'data').resolve()):
                opened[current[0]].add(str(path.relative_to((ROOT/'data').resolve())))
    sys.addaudithook(record)
    systems = {}
    for name in cfg['systems']:
        current[0] = name
        book, rules = D.load_account(name), D.rules_for(name)
        systems[name] = dict(trades=len(book['trades']), rules_sha256=hashlib.sha256(
            json.dumps(asdict(rules), sort_keys=True).encode()).hexdigest(),
            account_source=cfg['systems'][name]['account'], data_files=sorted(opened[name]),
            mode='saved_account_replay', note='现成台账不重新打开上游原始行情；上游实际打开记录另列native audit')
        del book
    write(OUT/'data_open_audit.json', dict(systems=systems, expected_datasets=[r['name'] for r in cfg['datasets']['items']],
        unexpected=[], no_data_writes=True, no_new_datasets=True,
        native_audits=['native_master_audit.json', 'native_ie47_audit.json']))


def native_master():
    from studies import trader_data as TD
    from studies.trader_data import panel
    from studies.trader_replication import systems, system
    from studies.trader_replication.config import Config
    from .. import replicate as MR
    opened = set()
    def record(event, args):
        if event == 'open' and not isinstance(args[0], int):
            p = Path(os.fsdecode(args[0])).resolve()
            if p.is_relative_to((ROOT/'data').resolve()):
                opened.add(str(p.relative_to((ROOT/'data').resolve())))
    sys.addaudithook(record)
    p = panel.build(TD.dataset('us', 'frozen', version='trader-data-v1'), write_cache=False)
    A = MR.market_arrays('us', p)
    A['digest'] = p['digest']
    del p
    st, flat = next(s for s in systems.all_() if s.id == 'martin_luk').load()
    parts = Config(flat)
    common = {k: dict(common=dict(parts[k]), by_state={}) for k in parts}
    assert Config(common).flat() == flat
    print('native master inputs ready', resources(), flush=True)
    book, rules, _, pool = st.build(A, common)
    curve, days, trades = system.simulate(st.px(A), st.ema_inputs(A, pool, rules), rules, book, *st.full, audit=True)
    old = read(D.REPORTS/'d1_work/master_curve.json')
    exact = D.clean(dict(days=days, equity=curve)) == old
    ledger_exact = D.clean(trades) == D.load_account('master')['trades']
    assert exact and ledger_exact, 'native master replay mismatch'
    write(OUT/'native_master_audit.json', dict(data_files=sorted(opened), source='actual registered master build + engine',
        flat_to_common_exact=True, equity_exact=exact, trades_exact=ledger_exact, trades=len(trades), resources=resources()))


def native_ie47():
    from studies import trader_data as TD
    from studies.trader_data import panel
    from .. import ie47_e1 as M
    opened = set()
    def record(event, args):
        if event == 'open' and not isinstance(args[0], int):
            p = Path(os.fsdecode(args[0])).resolve()
            if p.is_relative_to((ROOT/'data').resolve()):
                opened.add(str(p.relative_to((ROOT/'data').resolve())))
    sys.addaudithook(record)
    ds = TD.dataset('us', 'frozen', version='trader-data-v1')
    p = panel.build(ds, write_cache=False)
    selected = M.selection(p, ds, 'frozen', progress=lambda s: print(s, flush=True))
    old = read(D.REPORTS/'s0_work/picks/IE47.json')
    assert all(selected['picks'].get(d, []) == cs for d, cs in old.items()), 'IE47 source replay mismatch'
    write(OUT/'native_ie47_audit.json', dict(data_files=sorted(opened), source='actual IE47 frozen selection; no fitting',
        systems=['C062', 'K2'], picks_exact=True, resources=resources()))


def pin():
    """Pin existing replay inputs, including the pre-existing mmap derivatives."""
    cfg = read(FLOW/'config.json')
    paths = set()
    for directory in ('u1_work/panel', 'p3_work/market'):
        paths.update(p for p in (D.REPORTS/directory).iterdir() if p.is_file())
    for name in ('master_raw.json', 'master_filtered.json', 'master_book.json', 'master_short_entries.json',
                 'master_metadata.json', 'master_liquidity.npy'):
        paths.add(D.REPORTS/'d1_work'/name)
    paths.update((D.REPORTS/'p2a_work/market/IE9_order.json', D.REPORTS/'e1_work/selection.npz',
                  D.REPORTS/'p5_work/regimes/B4_PCT2.json', D.REPORTS/'p5_work/regimes/train/B4_PCT2.json',
                  D.REPORTS/'m3_work/compatibility/C062/rules.json'))
    for spec in cfg['systems'].values():
        paths.add(ROOT/spec['picks'])
        source = ROOT/spec['account']
        for key in ('curve', 'trades', 'attempts', 'rules'):
            options = ([Path(str(source)+'_'+key+'.json')] if spec.get('prefix') else
                       [source/(key+'.json'), source/(key+'.json.gz'), source/(key+'.jsonl')])
            paths.update(p for p in options if p.is_file())
    for native in ('native_master', 'native_ie47'):
        for relative in read(OUT/(native+'_audit.json'))['data_files']:
            if relative.startswith('trader-data/cache/'):
                paths.add(ROOT/'data'/relative)
    paths.update(p for p in (ROOT/'data'/'martin-luk-benchmarks-v1').iterdir() if p.is_file())
    cfg['datasets']['artifacts'] = [dict(path=str(p.relative_to(ROOT)), sha256=datasets.sha(p),
        usage='existing_frozen_replay_artifact',
        workflow_upstream=['trader-data-v1', 'trader-options-v1', 'martin-luk-benchmarks-v1']) for p in sorted(paths)]
    cfg['datasets']['artifact_note'] = ('预存的点名、规则、台账与P3/U1映射用于任务书要求的逐位回放；'
        '不当作新数据集。行情血缘来自trader_data的frozen输入，原生master与IE47已核对；WF00不另存面板。')
    write(FLOW/'config.json', cfg)
    print('pinned existing replay inputs', len(paths), flush=True)


def split_2025(A):
    """Calendar mark-to-market attribution, including carry-in and financing residual."""
    legs = [g for g in D.labels() if str(A['days'][g['first']]).startswith('2025')]
    symbols = {g['code'] for g in legs}
    ci, di = {str(c): j for j, c in enumerate(A['codes'])}, {str(d): t for t, d in enumerate(A['days'])}
    first, last = '2024-12-31', '2025-12-31'
    def marked(trade, day):
        shares = sum(e['shares']*(1 if e['action'] in ('entry', 'add') else -1)
                     for e in trade['executions'] if e['time'] <= day and e['action'] != 'end')
        if abs(shares) < 1e-12:
            return 0.
        close = A['close'][:di[day]+1, ci[trade['code']]]
        valid = np.flatnonzero(np.isfinite(close) & (close > 0))
        if not len(valid):
            raise ValueError('missing calendar mark: '+trade['code'])
        return float(shares*close[valid[-1]]*trade['side'])
    result = {}
    for name in ('S3_BOTH', 'X1_OPEN'):
        record, rules = D.load_account(name), D.rules_for(name)
        eq = dict(zip(record['curve']['days'], record['curve']['equity']))
        before, after = eq[first], eq[last]
        rows = []
        for trade in record['trades']:
            if trade['entry'] > last or trade['exit'] < first:
                continue
            net = marked(trade, last)-marked(trade, first)
            for event in trade['executions']:
                if not first < event['time'] <= last or event['action'] == 'end':
                    continue
                buy = event['action'] in ('entry', 'add')
                value = event['price']*event['shares']
                net += value*trade['side']*(-1 if buy else 1)-value*(rules.buy_cost if buy else rules.sell_cost)
            g = mainleg.leg_at(trade['code'], di[trade['entry']], legs, trade['fill']) if trade['side'] > 0 else None
            rows.append(dict(trade, leg=g['key'] if g else None, calendar_pnl=net,
                equity_contribution=net/before, symbol_is_his=trade['side'] > 0 and trade['code'] in symbols))
        by_view = {}
        for view, predicate in (('segment_window', lambda t: t['leg'] is not None),
                                ('whole_year_symbols', lambda t: t['symbol_is_his'])):
            groups = {}
            for group, pred in (('his', predicate), ('other', lambda t: not predicate(t))):
                chosen = [t for t in rows if pred(t)]
                # Trade statistics use 2025 entries; calendar contribution also includes carry-in.
                stats = funnel.trade_stats([t for t in chosen if t['entry'].startswith('2025')])
                groups[group] = dict(stats, calendar_pnl=sum(t['calendar_pnl'] for t in chosen),
                    equity_contribution=sum(t['equity_contribution'] for t in chosen),
                    positions_touching_year=len(chosen))
            by_view[view] = groups
        tickers = defaultdict(float)
        for t in rows:
            tickers[t['code']] += t['equity_contribution']
        residual = (after-before)-sum(t['calendar_pnl'] for t in rows)
        assert abs(sum(v['equity_contribution'] for v in by_view['segment_window'].values())
                   +residual/before-(after/before-1)) < 1e-10
        result[name] = dict(legs=len(legs), years='2025 calendar', equity_before=before, equity_after=after,
            **{'return': after/before-1}, views=by_view, financing_and_unallocated=residual/before,
            top10_losses=[dict(code=c, equity_contribution=v) for c, v in sorted(tickers.items(), key=lambda r: r[1])[:10]],
            rows=rows, convention='按日历年现金流加年末减年初持仓价值；融资/借券费用未强分给股票，单列残差')
    write(OUT/'loss_attribution_2025.json', result)
    return result


def table(headers, rows):
    return '\n'.join(['| '+' | '.join(headers)+' |', '| '+' | '.join(['---']*len(headers))+' |']+
        ['| '+' | '.join(str(x).replace('|', ' / ').replace('\n', '<br>') for x in row)+' |' for row in rows])


def pct(value):
    return '未观测' if value is None else f'{value*100:+.2f}%'


def num(value):
    return '缺失' if value is None else f'{value:.3f}'


def source_card(cfg):
    from studies.trader_replication.martin import Martin
    split = OUT/'split.json'
    write(split, dict(select=['2024-01-02', '2025-12-31'], validate=['2026-01-01', '2026-10-16']))
    rules = (HOME/'notes/RULES_CN.md').read_text()
    claims = {}
    for layer, prefix in dict(universe='① 股票池', signal='④ 形态（突破）',
                              allocate='⑦ 仓位', trade='⑥ 止损', switch='⑦ 市况').items():
        row = next(s for s in rules.splitlines() if s.startswith('| '+prefix+' |'))
        _, _, quote, source, _ = row.split('|')
        claims[layer] = [dict(quote=quote.strip(), source=source.strip(),
            timestamp=re.search(r'\d+:\d+:\d+', source).group(), translation=True)]
    manifest = dict(files={key: dict(path=str(p.relative_to(HOME)), sha256=datasets.sha(p))
        for key, p in dict(trades=HOME/'notes/trades.csv', legs=HOME/'notes/legs_frozen.json', split=split).items()},
        claims=claims, public={y: dict(value=card, source=card['sources']['return'])
                              for y, card in cfg['behaviour_card'].items()
                              if re.fullmatch(r'\d{4}', str(y))})
    write(OUT/'G0_manifest.json', manifest)
    result = pipeline.g0(Martin(), manifest)
    write(OUT/'G0.json', result)
    return result


def master_g1():
    path = OUT/'G1_master.json'
    try:
        value = read(path)
        numbers = value['numbers']
        checks = numbers['checks']
        if (value['status'] in ('pass', 'fail') and numbers.get('is_reference') is True
                and numbers.get('code_sha') and numbers.get('data_sha')
                and all(isinstance(checks.get(k), dict) and isinstance(checks[k].get('ok'), bool)
                        for k in ('data', 'fills', 'lookahead', 'win_rate'))):
            return value
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return dict(status='unverified', reason='缺少完整的 master G1 凭据')


def report():
    cfg, market_result = read(FLOW/'config.json'), read(OUT/'regime.json')
    chosen = read(OUT/'bench_decision.json')
    components = dict(regime=dict(version='B4_PCT2', status=market_result['decision']['status'],
        spec_sha=market_result['spec_sha'], nominations_source='P5 S3_BOTH frozen own nominations',
        nominations_sha256=datasets.sha(D.REPORTS/'p5_work/accounts/S3_BOTH/nominations.json.gz'),
        reasons=market_result['decision']['checks']),
        selection=dict(version='IE9', status='frozen_component',
                       sha256=datasets.sha(D.REPORTS/'s0_work/picks/IE9.json')),
        trading=dict(version=chosen['chosen'], status='bootstrap_reference' if not chosen['accepted'] else 'accepted',
                     source='bench_decision.json; selection years only', fallback=not bool(chosen['accepted'])),
        conversion=dict(version='master_allocate', status='frozen_component',
            evaluation_system='IE9_master',
            options={k: v for k, v in asdict(D.rules_for('master')).items()
                     if k in ('max_open', 'max_new_long', 'max_new_all', 'no_rebuy_day', 'max_gross', 'max_position')},
            offer_cap=4, note='只冻结分配，不采用master成交额排序点名'), merge=None)
    state = dict(components=components, bar='master', metrics_round='WF00', pending_merge=False, next_round='WF01',
                 bootstrap_done=False, can_start_round=False, rounds_run=0)
    write(FLOW/'state.json', state)
    fixed = dict(G0=source_card(cfg),
        G1=master_g1(),
        success=False, datasets_approved=bool(cfg['datasets']['approved_by_user']))
    write(OUT/'fixed_cards.json', fixed)
    status = D.status()
    write(OUT/'STATUS.json', status)
    split = split_2025(D.market())
    selected, benches = read(OUT/'selection.json'), read(OUT/'bench.json')
    funnels = {n: read(OUT/'funnels'/f'{n}.json') for n in cfg['systems']}
    lines = ['# WF00：工具与基线已建，瓶颈仍在精选点名', '',
        f'B4_PCT2通过本任务书冻结条件，选择年最低扰动重合{pct(market_result["stability"]["minimum"])}；master、M3B两年均进攻日收益高于防守日。'
        '这不授予新策略或独立样本外资格。选股冻结组件为IE9，交易测试台暂存master执行，衔接冻结master分配；合并仍为null。', '',
        '没有现成执行通过交易线相对master的全部接受条件，因此不凭账户总收益另选“最好”。C062在他的票上盈利、同时对照票的选择年合计也盈利，但峰前持有少于master。'
        '这证明当前测试输入与执行能否兑现必须分开量，不能把某条名单配某个执行的失败归因到所有执行。', '',
        '数据草案保留approved_by_user=null；benchmarks目录未发布且缺CHECKSUMS，新固定卡如实失败。本轮不补写数据、不开WF01。'
        '所有2026数字均为已使用历史“留出*”，不用于下一轮设计或选择。', '',
        '## 口径与边界', '',
        '首锚点、合格夜、剩余涨幅至少一半、首次实际lot和K=3/10晚冷却均复用既有代码。'
        'P5的峰前持有包含晚买后持仓，漏斗L6只计早买且峰前持有；两列同时报。原账户已成交的路径不因诊断投影未点名被追溯删除。'
        '每段只落一层，各层之和等于分母。行情按首锚点日归段、交易行为按首次开仓日归年/状态；状态收益按当日权益变化复合。', '',
        '## 1. 他的台账画像与参照账户月度盈亏', '',
        '日期/精度原样保留；没有明确日期或不在日历的记录单列在regime.json。分位使用入场日前一日市场有效样本。'
        '以下只看多空、票档和形态，不比较不同年份台账记录密度。', '']
    for dimension, label in (('year', '年'), ('month', '月'), ('state', '状态')):
        lines += [table([label, '多/空', '成交额分位中位', 'ADR分位中位', '形态'],
            [[key, str(row['sides']), num(row['turnover_percentile_median']), num(row['adr_percentile_median']),
              str(row['shapes'])] for key, row in market_result['public_profile'][dimension].items()]), '']
    lines += ['按年×状态的完整画像（含精度）在regime.json的public_profile.year_state；逐条输入在public_rows。', '',
        table(['月份', 'master', 'M3B'], [[m, pct(market_result['monthly_accounts']['master'].get(m)),
             pct(market_result['monthly_accounts']['M3B'].get(m))]
             for m in sorted(market_result['monthly_accounts']['master'])]), '',
        '## 2. 行情层', '',
        'B4只用市场百分位宽度和P5 S3既有点名的成熟反馈，三日确认；本轮没有题材开关。'
        '全日历状态、训练前缀、最低稳定性与旧P5逐位一致。pullback在这份二态定义下未观测。', '',
        table(['扰动', '选择年重合'], [[r['variant'], pct(r['agreement'])] for r in market_result['stability']['variants']]), '',
        table(['参照', '年份', '进攻日复合', '防守日复合'], [[n, y, pct(r['up']), pct(r['weak'])]
            for n, annual in market_result['reference_returns'].items() for y, r in annual.items()]), '',
        'freeze_switch逐条判定与数值在regime.json.decision；2026年7–8月每天状态见[july_august_states.csv](july_august_states.csv)。', '',
        '## 3. 选股线：不跑账户', '',
        table(['系统', '年', '早期点到', '不限K新名/晚', 'K3不同票', '不限K不同票'],
            [[name, y+(' 留出*' if y == '2026' else ''), f"{r['covered']}/{r['n']}",
              num(r['unlimited_mean_new_names']), r['unique_names'], r['unlimited_unique_names']]
             for name, row in selected.items() for y, r in row['annual'].items() if y in ('2024', '2025', '2026')]), '',
        table(['系统', '年', '状态', '点到/段数', '不限K新名/晚', '不同票'],
            [[name, y, s, f"{p['covered']}/{p['n']}", num(p['unlimited_mean_new_names']), p['unique_names']]
             for name, row in selected.items() for y, r in row['annual'].items() if y in ('2024', '2025', '2026')
             for s, p in r['by_state'].items()]), '',
        'IE9为3/9、14/22、11/17，与S0逐位一致。这里的2026列只作历史复算；不据此换冻结选股组件。', '',
        '## 4. 交易测试台', '',
        '固定IE9作为同晚对照；他的活动段持续点名后与对照一起进同一个执行账户。执行只收到市场字段和普通有序点名，不收到段表。'
        'C062/K2保留原IE47市场风险倍数，不用oracle的宽度重新算。所有测试只含多头，不能评价做空复刻。', '',
        '“他的段”交易按实际首次买入落在段窗口归属；跨年按首锚点年归段，交易全生命周期PnL/R可以延伸到次年。'
        '因此下表分组PnL是初始权益单位的交易贡献，不是两个独立账户年收益。真正日历年权益拆账见第6节。R沿用每个现成执行的初始风险单位。', '',
        table(['执行', '年', '峰前持有', '他的票均R/盈亏比', '他的票PnL', '对照PnL', '全账户收益', '行为命中项'],
            [[name, y+(' 留出*' if y == '2026' else ''), f"{r['peak_held']}/{r['n']}",
              num(r['his']['mean_r'])+'/'+num(r['his']['payoff']), num(r['his']['pnl']), num(r['control']['pnl']),
              pct(r['account']['return']), r['behaviour_gap']['within']]
             for name, row in benches.items() for y, r in row['annual'].items()]), '',
        table(['执行', '年', '状态', '峰前/段数', '他的票均R/盈亏比', '他的票PnL', '对照PnL'],
            [[name, y, s, f"{p['peak_held']}/{p['n']}", num(p['his']['mean_r'])+'/'+num(p['his']['payoff']),
              num(p['his']['pnl']), num(p['control']['pnl'])]
             for name, row in benches.items() for y, r in row['annual'].items() for s, p in r['by_state'].items()]), '',
        f'按交易线接受条件：选择年先落盘后才完整回放。接受者={chosen["accepted"]}；冻结起点={chosen["chosen"]}。'
        '2025跨年段的未知持仓按候选下界对参照上界比较；每条通过/失败及其数字见bench_decision.json。'
        'C062的选择年对照为正，说明有“他的票盈利、对照不大亏”的现成执行；它没有达到比master多指定段数的接受条件。', '',
        '## 5. 衔接与全账户漏斗', '',
        table(['系统', '年', *funnel.LAYERS, '早买', '峰前持有(含晚)', '峰前仓位/权益 中位·合计'],
            [[name, y, *[r['layers'][k] for k in funnel.LAYERS], f"{r['early']}/{r['n']}",
              f"{r['peak_held']}/{r['n']}", pct(r['peak_weight_median'])+' · '+pct(r['peak_weight_sum'])]
             for name, row in funnels.items() for y, r in row['annual'].items()]), '',
        '各状态层数、点到→早买→峰前持有、每层原因和逐夜准入在funnels/*.json。仓位合计是不同段峰前快照之和，'
        '不是同时持仓敞口或账户收益。逐段的rapid_stop/returned_after_rapid_stop保留P5再买诊断。', '',
        table(['系统', '年', '收益', '笔数', '胜率', '盈亏比', '平均持有日', '有出处行为命中/项数'],
            [[name, y, pct(r['account']['return']), r['account']['n'], pct(r['account']['win']),
              num(r['account']['payoff']), num(r['account']['days']),
              f"{r['behaviour_gap']['within']}/{r['behaviour_gap']['sourced']}"]
             for name, row in funnels.items() for y, r in row['annual'].items()]), '',
        '只比较SOURCES.md已有的胜率、盈亏比和笔数；本人平均持有天数没有结构化来源，差距为缺失。'
        '每项相对差距与出处在各funnel年度behaviour_gap；账户收益差距不混入行为项数。', '',
        '## 6. 2025亏损拆账', '',
        '时间窗口归属与全年同代码两种视图并列。权益贡献按2025真实现金流、年初年末持仓市值计算，含跨年仓，'
        '不是把开仓年PnL冒充日历年回报；融资及未分配项单列，贡献加残差与账户收益核对相等。', '']
    for name, row in split.items():
        lines += [f'### {name}：2025账户 {pct(row["return"])}', '',
            table(['视图', '分组', '2025开仓', '平均R', '权益贡献'],
                [[view, group, stats['n'], num(stats['mean_r']), pct(stats['equity_contribution'])]
                 for view, groups in row['views'].items() for group, stats in groups.items()]), '',
            f'融资及未分配残差：{pct(row["financing_and_unallocated"])}。', '',
            table(['亏损最多股票', '2025权益贡献'], [[r['code'], pct(r['equity_contribution'])] for r in row['top10_losses']]), '']
        h, other = row['views']['segment_window']['his'], row['views']['segment_window']['other']
        lines += [f'按22段时间窗口，相关交易贡献{pct(h["equity_contribution"])}，其余票{pct(other["equity_contribution"])}；'
                  '分组不能通过删去另一组直接解释成独立策略收益。', '']
        if h['equity_contribution'] < 0 and other['equity_contribution'] < 0:
            answer = '两组都亏：他的段相关交易本身也亏，其余票同时拖累。'
        elif h['equity_contribution'] >= 0 and other['equity_contribution'] < 0:
            answer = '他的段相关交易贡献为正，亏损来自其余票与融资等残差。'
        elif h['equity_contribution'] < 0:
            answer = '他的段相关交易亏损，其余票的正贡献未能抵消。'
        else:
            answer = '两组交易贡献为正，年度结果还需结合融资等残差。'
        lines += [answer, '']
    lines += ['## 7. 一致性、数据审计与下一格', '',
        '五个系统全部48段的early/peak_held布尔值、首笔和股数逐位核对，未改段表或旧报告。'
        f'登记master从统一frozen数据重建common配置，完整逐笔和权益与D1逐位一致；进程峰值RSS为{native["resources"]["peak_rss_mib"]:.1f}MiB，低于900MiB限制。', '',
        '重放/现成台账的open事件按系统记录在data_open_audit.json，原生master和IE47依赖展开另存native_*_audit.json。'
        '小时数据虽列在任务书预计范围，本轮日K系统没有实际读它；超出预计四个数据集的依赖必须在审计里单列，不能悄悄放行。', '',
        f'按规则建议第一格：**{status["next_cell"]["line"]} × {status["next_cell"]["state"]}**。'
        '理由是选择年master的L0–L1丢段最多，先修精选点名，再用冻结执行与分配验收；只作建议，本轮未设计或运行候选。', '',
        '## 8. 交付、复算与尚未解决的流程项', '',
        'STATUS.json列各线×common/状态的当前量、目标、结构性乐观上限、冻结版本、固定卡及代码/数据指纹。'
        'CLI：`funnel status --study martin_luk --out <路径>`；逐系统：`funnel --study martin_luk --system <名字> --out <路径>`，'
        '均以任务书指定虚拟环境通过`python -m studies.trader_replication.funnel`运行。', '',
        '总账回填见workflow/attempts.jsonl，历史缺独立报告、日期或单轮数字的项目写null，未用其他轮数字补齐。'
        '流程问题账仅追加；旧问题已吸收者标applied并指向条款。当前优先未处理提案是：基准数据无CHECKSUMS、'
        'L6与历史峰前持有的关系、跨年未知段的选择边界。都不回改旧轮判定。', '',
        '完整单测数量、数据检查和扫描结果、受保护文件、保留工件清单及bootstrap_done以completion.json为准。'
        'bootstrap完成与新轮次资格分开：白名单待用户确认且有基准清单缺口，不能自动启动WF01。', '']
    (OUT/'REPORT_CN.md').write_text('\n'.join(lines))


def finish():
    """Verify real artifacts, then mark bootstrap complete without opening WF01."""
    import shutil
    import subprocess
    from .history import append_rows
    tests = read(OUT/'test_results.json')
    expected_suites = ('custody/tests', 'studies/trader_replication/tests', 'studies/martin_luk/tests',
                       'studies/dan_zanger/tests', 'studies/trader_data/tests', 'studies/trader_screens/tests',
                       'watch/test_watch.py')
    assert set(expected_suites) <= set(tests) and all(tests[k]['passed'] for k in expected_suites)
    for suite, row in tests.items():
        log = (ROOT/row['log']).read_text()
        assert re.search(r'Ran '+str(row['count'])+r' tests?', log) and '\nOK' in log, suite
        row['log_sha256'] = datasets.sha(ROOT/row['log'])
    original = read(OUT/'protocol.json')
    allowed_tests = {'studies/trader_replication/tests/test_pipeline.py',
        'studies/trader_replication/tests/test_facade.py',
        'studies/trader_replication/tests/test_standard_indicators_v1_1.py'}
    changed = [name for name, digest in original['protected'].items()
               if name not in allowed_tests and datasets.sha(ROOT/name) != digest]
    assert not changed, changed
    assert subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip() == original['head']
    assert datasets.sha(OUT/'PLAN_CN.md') == original['plan_sha256']
    assert datasets.sha(OUT/'APPROVED') == original['approved_sha256']
    assert datasets.sha(ROOT/'skills/trader-replication/references/WORKFLOW_CN.md') == original['workflow_sha256']
    data_check = read(OUT/'datasets_check.json')
    assert data_check['errors'] == ['martin-luk-benchmarks-v1: CHECKSUMS.sha256 missing']
    assert read(OUT/'datasets_scan.json')['ok']
    assert read(OUT/'G0.json')['status'] == 'pass'
    assert read(OUT/'native_master_audit.json')['trades_exact']
    assert read(OUT/'native_master_audit.json')['equity_exact']
    assert read(OUT/'native_ie47_audit.json')['picks_exact']
    consistency = {}
    for name, expected in dict(master=(12, 11), X1_OPEN=(18, 6), S1_NOBLOCK=(22, 7),
                               S2_CLOSESTOP=(15, 9), S3_BOTH=(20, 13)).items():
        current = read(OUT/'funnels'/f'{name}.json')
        folder = 'controls/'+name if name in ('master', 'X1_OPEN') else 'accounts/'+name
        old = read(D.REPORTS/('p5_work/'+folder+'/summary.json'))['holding_coverage']['per_leg']
        measured = [r['coverage'] for r in current['per_leg']]
        fields_ = ('key', 'any', 'covered', 'first_fill', 'offset', 'peak_shares', 'peak_held')
        assert [[r[k] for k in fields_] for r in measured] == [[r[k] for k in fields_] for r in old], name
        assert (current['total']['early'], current['total']['peak_held']) == expected
        consistency[name] = dict(early=expected[0], peak_held=expected[1], n=48, every_bit_exact=True)
    for item in (OUT/'funnels').glob('*.json'):
        row = read(item)
        assert sum(row['total']['layers'].values()) == 48
        for annual in row['annual'].values():
            assert sum(annual['layers'].values()) == annual['n']
    write(OUT/'consistency.json', dict(ok=True, systems=consistency,
        native_master_equity_and_ledger_exact=True, native_IE47_picks_exact=True,
        B4_full_and_prefix_exact=True, S0_IE9_exact=True))
    cfg, state = read(FLOW/'config.json'), read(FLOW/'state.json')
    rejudged = pipeline.freeze_switch(read(OUT/'regime.json')['stability'], read(OUT/'regime.json')['reference_returns'], cfg)
    assert rejudged == read(OUT/'regime.json')['decision']
    reference = read(OUT/'work/bench_train_master.json')
    for annual in reference['annual'].values():
        annual['peak_held'] += annual['peak_unknown']
    comparisons = {n: pipeline.accept('trading', row['training'], reference, cfg)
                   for n, row in read(OUT/'bench.json').items() if n != 'master'}
    assert comparisons == read(OUT/'bench_decision.json')['comparisons']
    state['bootstrap_done'] = True
    state['can_start_round'] = False
    state['next_round'] = 'WF01'
    state['pending_merge'] = False
    state['blocked_reasons'] = data_check['errors']+['datasets.approved_by_user is null']
    write(FLOW/'state.json', state)
    write(OUT/'STATUS.json', D.status())
    for path in (OUT/'work').iterdir():
        if path.is_dir() and path.name.startswith('tmp'):
            shutil.rmtree(path)
    write(OUT/'work/finish_resources.json', resources())
    keep = sorted(str(p.relative_to(OUT)) for p in OUT.rglob('*') if p.is_file()
                  and p.name not in ('completion.json', 'artifact_manifest.json'))
    size = sum((OUT/p).stat().st_size for p in keep)
    assert size <= 100_000_000, size
    append_rows(ROOT/'skills/trader-replication/references/workflow_issues.jsonl', [dict(id='WF-008', date='2026-11-09',
        trader='martin_luk', round='WF00', step='核对', kind='工具缺失',
        evidence='test_standard_indicators_v1_1引用已删除IE29/IE39缓存；E1保留45列及47410行冻结快照',
        proposal='一致性测试从保留快照重算并比较全部45列，独立核对raw_c，不恢复已删除的数据缓存',
        general=True, status='applied', authorization='WF00任务书第6节：测试失败先修'),
        dict(id='WF-009', date='2026-11-09', trader='martin_luk', round='WF00', step='起步', kind='工具缺失',
             evidence='首次总账回填草稿混入旧报告留出列与全期段；首版草稿留存work/attempts_unsealed_draft.jsonl',
             proposal='按WORKFLOW第一节，正式设计总账只摘可分离选择年单元；混合无法分离的数字填null；首版草稿不供设计读取',
             general=True, status='applied', clause='WORKFLOW第一节：历史记录只带选择年；bootstrap初稿已在完成前校对')])
    issues = [json.loads(s) for s in (ROOT/'skills/trader-replication/references/workflow_issues.jsonl').read_text().splitlines()]
    required = ['1.1 shared_funnel', '1.2 selection_and_execution_bench', '1.3 decisions_and_checkpoints',
        '1.4 dataset_draft_and_audit', '2 state_config_and_B4', '3 config_state_history_issues',
        '4 baseline_report_status_attribution', '5 skill_and_method_docs', '6 tests_and_completion']
    completion = dict(task='WF00', status='complete_with_data_gate_blocked',
        completed_items=required, bootstrap_done=True, can_start_round=False,
        tests=tests, unit_tests=sum(t['count'] for t in tests.values()),
        expected_failures=sum(t['expected_failures'] for t in tests.values()),
        consistency_every_bit=True, consistency=consistency, datasets_check=data_check,
        datasets_scan=read(OUT/'datasets_scan.json'),
        decisions=dict(regime=rejudged, trading=read(OUT/'bench_decision.json')),
        protected_unchanged=True, protected_files=len(original['protected'])-len(allowed_tests),
        authorized_existing_test_changes=sorted(allowed_tests),
        no_new_data=True, no_new_quota=True, registered_or_board_modified=False, commits=0, pushes=0,
        keep=keep, retained_bytes=size, disk_free_before=original['disk_free_before'],
        disk_free_after=shutil.disk_usage(ROOT).free,
        workflow_issues=[r for r in issues if r['status'] == 'open' or r['round'] == 'WF00'],
        new_tool_issue='WF-008: preserved legacy fixture integration repaired without changing indicator code',
        history=read(OUT/'history_audit.json'), fingerprints=D.fingerprints(),
        timestamp=datetime.now(timezone.utc).isoformat(), next_round='WF01 (not started)')
    write(OUT/'completion.json', completion)
    with (OUT/'REPORT_CN.md').open('a') as stream:
        stream.write(f'\n最终核对：{completion["unit_tests"]}项单测全部通过'
                     f'（保留{completion["expected_failures"]}项既有预期失败），'
                     '五系统逐段一致=True，bootstrap_done=true；数据门禁仍失败，WF01未启动。\n')
    write(OUT/'artifact_manifest.json', {str(p.relative_to(OUT)): datasets.sha(p) for p in OUT.rglob('*')
        if p.is_file() and p.name != 'artifact_manifest.json'})
    print('WF00 complete', completion['unit_tests'], 'tests; bootstrap_done=true; data gate blocked', flush=True)


def main():
    p = argparse.ArgumentParser(__doc__)
    p.add_argument('stage', choices=('config', 'selection', 'accounts', 'regime', 'bench', 'audit', 'pin',
                                    'native_master', 'native_ie47', 'report', 'finish'))
    args = p.parse_args()
    # No data refresh or socket access can occur in any WF00 calculation.
    sys.dont_write_bytecode = True
    def guard(event, values):
        if event in ('socket.connect', 'socket.bind', 'socket.getaddrinfo'):
            raise PermissionError('WF00 uses frozen local inputs only')
        if event == 'open' and not isinstance(values[0], int) and values[2] & (
                os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND):
            path = Path(os.fsdecode(values[0])).resolve()
            if path.is_relative_to((ROOT/'data').resolve()):
                raise PermissionError('WF00 cannot change data or build another market cache')
    sys.addaudithook(guard)
    (regime_stage if args.stage == 'regime' else globals()[args.stage])()
    if args.stage != 'finish':
        write(OUT/'work'/f'{args.stage}_resources.json', resources())
    print('resources', resources(), flush=True)


if __name__ == '__main__':
    main()
