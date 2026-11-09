"""H2 saved-account diagnosis, execution audit, acceptance tests and Chinese report."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
import difflib
import json
from pathlib import Path
import sys
import unittest

import numpy as np

from . import h2_research as X, h2_policy as H, h1_report as H1R

ROOT, HOME, OUT = X.ROOT, X.HOME, X.OUT
read, write, sha, clean = X.read, X.write, X.sha, X.clean
NAMES = {'registered_master': '登记master', **{n: n for n in ('M1B', 'M2A', 'M3B', 'H1A', 'H1B', 'H2A', 'H2B')},
         'without_theme': '去题材优先', 'without_probe': '一次买满', 'without_limits': '去数量上限',
         'without_retry': '去再试', 'without_feedback': '去市况反馈'}


def folders():
    result = {n: OUT/'baseline/train'/n for n in X.BASELINES}
    result.update({n: OUT/'candidates'/n for n in X.CANDIDATES})
    if (OUT/'ablation.json').exists():
        result.update({n: OUT/'ablation'/n for n in read(OUT/'ablation.json')['results']})
    if (OUT/'validation.json').exists():
        result.update({n: OUT/'validation'/n for n in read(OUT/'validation.json')})
    return result


def correction_features():
    X.once('correction_features')
    with X.strategy_only():
        A = X.arrays(X.PREP)
    f = X.feature_set(A, 'train')
    old = OUT/'corrections/distribution_filter/features/train'
    checks = {}
    for name, value in f.items():
        if not isinstance(value, np.ndarray):
            checks[name] = value == read(old/(name+'.json'))
        elif name != 'distribution':
            checks[name] = np.array_equal(value, np.load(old/(name+'.npy'), mmap_mode='r'), equal_nan=True)
    assert all(checks.values()), checks
    previous = np.load(old/'distribution.npy', mmap_mode='r')
    assert np.all(f['distribution'] >= previous)
    write('execution_correction.json', dict(reason='Remove unrequested EMA9 filter on distribution exits',
        checks=checks, extra_exit_signals=int((f['distribution'] & ~previous).sum()),
        archive='corrections/distribution_filter', preregistration_unchanged=True,
        original_validation=read(OUT/'corrections/distribution_filter/validation_complete.json'),
        reused_baseline_accounts=6, new_candidate_parameters=False, resources=X.resources()))


def diagnose():
    X.once('diagnose')
    A, frozen = X.arrays(X.PREP), read(HOME/'notes/legs_frozen.json')
    f = X.feature_set(A, 'train')
    di, ci = {str(d): i for i, d in enumerate(A['days'])}, {str(c): i for i, c in enumerate(A['codes'])}
    legs = [g for g in frozen['legs'] if g['first_date'].startswith('2025')]
    assert len(legs) == 22
    details, nightly = [], {}
    for name, spec in X.CANDIDATES.items():
        folder = OUT/'candidates'/name
        trades, curve, rows, card, mgmt = (read(folder/(n+'.json')) for n in
                                          ('trades', 'curve', 'lots', 'scorecard', 'management'))
        equity = H1R.curve_array(curve, A['days'])
        with X.strategy_only():
            book, _, _, tolerance = H.build(A, X.PREP, f, spec)
        by_leg = {g['key']: [] for g in legs}
        with (folder/'attempts.jsonl').open() as stream:
            for line in stream:
                r = json.loads(line)
                if not r['kind'].startswith('h2_'):
                    continue
                d = di[r['day']]
                for g in legs:
                    if r['code'] == g['code'] and g['first']-3 <= d < g['peak']:
                        by_leg[g['key']].append({k: v for k, v in r.items() if k != 'held'})
        for g in legs:
            j = ci[g['code']]
            window = list(range(max(0, g['first']-3), min(g['peak'], len(A['days']))))
            pool = [d for d in window if f['pool'][d, j]]
            listed = [d for d in window if f['leaders'][d, j]]
            shapes = [d for d in listed if f['forms'][d, j]]
            offered = [d for d in window if any(e[1] == j and e[2] > 0 for e in book[d])]
            part = [r for r in rows if r['leg'] == g['key']]
            initial, maximum = H1R.leg_positions(part, g, A, equity)
            coverage = next(r for r in card['legs'] if r['key'] == g['key'])
            attempts = by_leg[g['key']]
            reasons = Counter(r['reason'] for r in attempts)
            if coverage['any']:
                reason = ('早买' if coverage['covered'] else '晚买')+('且段内盈利' if coverage['pnl'] > 0 else '但段内未盈利')
            elif not pool:
                reason = '未进ADR/绝对成交额池'
            elif not listed:
                reason = '未进领涨名单'
            elif not shapes:
                reason = '名单内无收盘确认形态'
            elif not offered:
                reason = '离9EMA超过2ADR或结构止损非正'
            else:
                reason = '账户拒绝：'+','.join(f'{k}={v}' for k, v in reasons.items())
            ids = sorted({r['trade'] for r in part})
            confirmations = sorted({t['confirmed_day'] for i in ids if (t := trades[i]).get('confirmed_day')
                                    and di[t['confirmed_day']] <= min(g['peak'], len(A['days'])-1)})
            details.append(dict(system=name, key=g['key'], code=g['code'], anchor=g['first_date'],
                precision=g['precision'], listed=bool(listed), listed_first=str(A['days'][listed[0]]) if listed else None,
                pool_first=str(A['days'][pool[0]]) if pool else None,
                first_fill=str(A['days'][coverage['first_fill']['index']]) if coverage['first_fill'] else None,
                offset=coverage['offset'], initial_position=initial, max_position=maximum,
                confirmed=bool(confirmations), confirmation_days=confirmations, leg_pnl=coverage['pnl'],
                capture=coverage['capture_total'], early=coverage['covered'], any=coverage['any'],
                reason=reason, account_reasons=reasons, attempts=attempts,
                offered_dates=[str(A['days'][d]) for d in offered],
                upgrade_dates=[str(A['days'][d]) for d in window if f['upgrades'][d, j]]))
        entries = {(r['day'], r['code']): r for r in mgmt['tolerance_entries']}
        selected = []
        for record in mgmt['tolerance_holdings']:
            if not '2025-09-08' <= record['day'] <= '2025-10-01':
                continue
            day = dict(record)
            annotated = []
            for q in record['holdings']:
                row = dict(q)
                entry = entries[(q['entry'], q['code'])]
                row.update(entry_group=entry['group'], evicted=entry['evicted'],
                    initial_fraction=entry['initial_fraction'], fraction=q['value']/record['equity'],
                    entry_upgraded=bool(f['upgrades'][di[q['entry']], ci[q['code']]]),
                    reason='剩余仓沿9EMA，未触发离场' if q['trimmed'] else
                           '证实仓有成本保护，未触发离场' if q['confirmed'] else '试仓未跌破结构收盘止损')
                annotated.append(row)
            day['holdings'] = annotated
            selected.append(day)
        nightly[name] = selected
    write('legs_2025.json', details)
    columns = ('system', 'code', 'anchor', 'precision', 'listed', 'listed_first', 'first_fill', 'offset',
               'initial_position', 'max_position', 'confirmed', 'confirmation_days', 'leg_pnl', 'early', 'reason')
    with (OUT/'legs_2025.csv').open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=columns, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(details)
    write('nightly_2025.json', nightly)
    write('diagnose_complete.json', dict(rows=len(details), legs=22, nights={n: len(v) for n, v in nightly.items()},
        resources=X.resources()))


def audit():
    if (OUT/'audit_started.json').exists():
        assert not (OUT/'audit.json').exists(), 'completed audit cannot be overwritten'
        X.once('audit_resumed')
        write('audit_resume_reason.json', dict(reason='Restore source snapshots to the hashes registered before simulation',
            repair=read(OUT/'archive_source_repair.json'), account_simulations=0))
    else:
        X.once('audit')
    X.registry_check()
    blocked = {}
    for p in (HOME/'notes/trades.csv', HOME/'notes/legs_frozen.json', HOME/'reports/t1_work/groups.jsonl',
              OUT/'baseline_scorecards.json'):
        with X.strategy_only():
            try:
                p.read_bytes()
            except PermissionError:
                blocked[str(p.relative_to(ROOT))] = True
            else:
                raise AssertionError('H2 label read guard failed')
    A = X.arrays(X.FULL)
    di, ci = {str(d): i for i, d in enumerate(A['days'])}, {str(c): i for i, c in enumerate(A['codes'])}
    checks, events = {}, 0
    for name, folder in folders().items():
        trades, rows = read(folder/'trades.json'), read(folder/'lots.json')
        assert abs(sum(t['pnl'] for t in trades)-sum(r['pnl'] for r in rows)) < 1e-8
        for t in trades:
            j = ci[t['code']]
            for e in t['executions']:
                d = di[e['time']]
                epsilon = 2*max(abs(float(np.spacing(A['low'][d, j]))), abs(float(np.spacing(A['high'][d, j]))))
                assert A['low'][d, j]-epsilon <= e['price'] <= A['high'][d, j]+epsilon, (name, t['code'], e)
                events += 1
            if t['kind'].startswith('h2_'):
                assert t['disaster_stop'] >= .85*t['fill']-1e-12
                assert t['add_tries'] <= 2
        if (folder/'management.json').exists():
            mgmt, spec = read(folder/'management.json'), read(folder/'policy.json')
            for r in mgmt['tolerance_holdings']:
                count = Counter(q['group'] for q in r['holdings'] if q['group'] is not None)
                assert max(count.values(), default=0) <= 2, (name, r['day'], count)
            weekly, retries = Counter(), defaultdict(list)
            for e in mgmt['tolerance_entries']:
                from datetime import date
                week = date.fromisoformat(e['day']).isocalendar()[:2]
                weekly[week] += 1
                assert e['initial_fraction'] <= (.1 if spec.get('probe', True) else e['cap'])+1e-12
                if e['retry']:
                    assert spec.get('retry', True)
                    retries[e['code']].append(di[e['day']])
                    assert sum(di[e['day']]-d < 10 for d in retries[e['code']]) <= 2
            if spec.get('limits', True):
                assert max(weekly.values(), default=0) <= 4
                assert max(len(r['holdings']) for r in mgmt['tolerance_holdings']) <= 4
            rules = read(folder/'rules.json')
            additions = {(r['entry'], r['code'], r['day']): r for r in mgmt.get('tolerance_adds', []) if r['filled']}
            for t in trades:
                if not t['kind'].startswith('h2_'):
                    continue
                size = 0.
                for e in t['executions']:
                    if e['action'] in ('entry', 'add'):
                        size += e['shares']
                    elif e['action'] != 'end':
                        size -= e['shares']
                    if e['action'] == 'add':
                        r = additions[(t['entry'], t['code'], e['time'])]
                        assert r['proof_R'] or r['proof_high']
                        assert r['stop'] >= t['fill']
                        assert size*e['price'] <= t['cap']*(r['equity']-r['amount']*rules['buy_cost'])+1e-10
            assert abs(read(folder/'reconciliation.json')['error']) < 1e-9
        card = read(folder/'scorecard.json')
        assert card['holdings_reconstruction_error'] < 1e-8
        for r in card['years'].values():
            h = r['habits']
            contribution = h['long_contribution']+h['short_contribution']-h['financing_contribution']
            assert abs(contribution-r['checks']['return']['ours']) < 1e-8
            assert r['checks']['narrow_profit']['ours']+1e-12 >= r['checks']['public_profit']['ours']
        checks[name] = dict(fifo_reconciled=True, fills_in_range=True, limits=True, actual_add_caps=True,
                            holdings_and_long_short_PnL_reconciled=True, trades=len(trades))
    protected = {p: sha(ROOT/p) == h for p, h in read(OUT/'protocol.json')['protected'].items()}
    assert all(protected.values()), [p for p, ok in protected.items() if not ok]
    archived_sources = {}
    for version in ('distribution_filter', 'theme_cap'):
        archive = OUT/'corrections'/version
        for p, expected in read(archive/'candidates.json')['code_sha256'].items():
            source = archive/'original_h2_system.py.txt' if Path(p).name == 'system.py' else \
                archive/('original_'+Path(p).name+'.txt')
            archived_sources[version+'/'+p] = sha(source) == expected
    assert all(archived_sources.values()), archived_sources
    write('audit.json', dict(ok=True, accounts=checks, execution_events=events,
        protected_unchanged=True, protected_checks=protected, archived_sources_exact=archived_sources,
        label_reads_rejected=blocked, resources=X.resources()))


def explain():
    """Evaluate upstream reach and losses from saved accounts without another simulation."""
    X.once('explain')
    A, f = X.arrays(X.PREP), None
    f = X.feature_set(A, 'train')
    frozen = read(HOME/'notes/legs_frozen.json')
    ci = {str(c): j for j, c in enumerate(A['codes'])}
    result = {}
    for name, spec in X.CANDIDATES.items():
        folder = OUT/'candidates'/name
        trades, mgmt, card = (read(folder/(n+'.json')) for n in ('trades', 'management', 'scorecard'))
        with X.strategy_only():
            book, _, _, _ = H.build(A, X.PREP, f, spec)
        reach = []
        for g in frozen['legs']:
            year = g['first_date'][:4]
            if year not in ('2024', '2025'):
                continue
            j = ci[g['code']]
            nights = [d for d in range(max(0, g['first']-3), min(g['peak'], len(A['days'])))
                      if np.isfinite(A['close'][d, j]) and
                      X.M.mainleg.leg_at(g['code'], d, [g], float(A['close'][d, j]), keep=.5)]
            pool = [d for d in nights if f['pool'][d, j]]
            leader = [d for d in pool if f['leaders'][d, j]]
            form = [d for d in leader if f['forms'][d, j]]
            offer = [d for d in form if any(e[1] == j and e[2] > 0 for e in book[d])]
            market = [d for d in offer if f['breadth_ok'][d]]
            reach.append(dict(key=g['key'], code=g['code'], year=year,
                pool=bool(pool), leader=bool(leader), form=bool(form), offer=bool(offer), market=bool(market),
                early_offer_dates=[str(A['days'][d]) for d in offer]))
        entries = {(r['day'], r['code']): r for r in mgmt['tolerance_entries']}
        years = {}
        for y in ('2024', '2025'):
            ts = [t for t in trades if t['entry'][:4] == y and t['side'] > 0]
            closed = [t for t in ts if t['why'] != 'end']
            initial = [r for r in mgmt['tolerance_entries'] if r['day'][:4] == y]
            holdings = [q['value']/r['equity'] for r in mgmt['tolerance_holdings'] if r['day'][:4] == y for q in r['holdings']]
            losses = []
            for t in closed:
                if t['pnl'] >= 0:
                    continue
                e = entries[(t['entry'], t['code'])]
                losses.append(dict(code=t['code'], entry=t['entry'], exit=t['exit'], why=t['why'],
                    pnl=t['pnl'], loss_entry_equity=-t['pnl']/e['equity'],
                    confirmed=t['confirmed'], ret_initial=t['ret'], ret_invested=t['ret_invested'],
                    initial_fraction=e['initial_fraction'], initial_planned_risk=e['initial_fraction']*t['risk_pct']))
            reach_year = [r for r in reach if r['year'] == y]
            theme_counts = []
            for r in mgmt['tolerance_holdings']:
                if r['day'][:4] == y:
                    counts = Counter(q['group'] for q in r['holdings'] if q['group'] is not None)
                    if counts:
                        theme_counts.append(dict(day=r['day'], maximum=max(counts.values())))
            years[y] = dict(reach={k: sum(r[k] for r in reach_year) for k in ('pool', 'leader', 'form', 'offer', 'market')},
                legs=len(reach_year), actual_early=card['years'][y]['early'],
                initial_mean=float(np.mean([r['initial_fraction'] for r in initial])),
                initial_median=float(np.median([r['initial_fraction'] for r in initial])),
                max_marked_position=max(holdings, default=0.), confirmed=sum(t['confirmed'] for t in ts),
                stop_retries=sum(r['retry'] for r in initial), exit_reasons=Counter(t['why'] for t in closed),
                long_profit=sum(max(0., t['pnl']) for t in closed), long_loss=sum(min(0., t['pnl']) for t in closed),
                confirmed_loss=sum(min(0., t['pnl']) for t in closed if t['confirmed']),
                probe_loss=sum(min(0., t['pnl']) for t in closed if not t['confirmed']),
                max_current_theme_holdings=max((r['maximum'] for r in theme_counts), default=0),
                merged_theme_over_two=[r for r in theme_counts if r['maximum'] > 2],
                largest_losses=sorted(losses, key=lambda r: -r['loss_entry_equity'])[:10])
        result[name] = dict(reach=reach, years=years)
    write('diagnostics.json', result)
    write('explain_complete.json', dict(resources=X.resources(), simulations=0, parameters_changed=0))


def test_group(group):
    def no_network(event, args):
        if event in ('socket.connect', 'socket.bind', 'socket.getaddrinfo'):
            raise PermissionError('H2 tests are offline')
    sys.addaudithook(no_network)
    before = X.resources()
    directory = 'custody/tests' if group == 'custody' else 'studies/'+group+'/tests'
    result = unittest.TextTestRunner(verbosity=1).run(unittest.defaultTestLoader.discover(directory))
    write('test_'+group+'_resources.json', dict(tests=result.testsRun, ok=result.wasSuccessful(),
        failures=len(result.failures), errors=len(result.errors), expected_failures=len(result.expectedFailures),
        before=before, after=X.resources()))
    sys.exit(0 if result.wasSuccessful() else 1)


def pct(value):
    return '—' if value is None else f'{100*value:.1f}%'


def num(value, digits=2):
    return '—' if value is None else f'{value:.{digits}f}'


def table(headers, rows):
    return '\n'.join(['| '+' | '.join(headers)+' |', '| '+' | '.join('---' for _ in headers)+' |']+
                     ['| '+' | '.join(map(str, row))+' |' for row in rows])


def coverage(r):
    return f"{r['early']}/{r['any']}/{r['positive_legs']}/{r['leg_count']}"


def shares(r, prefix):
    return '/'.join(pct(r['checks'][prefix+'_'+n]['ours']) for n in ('trades', 'capital', 'profit'))


def reference_cell(value, reference, percentage=False):
    if value is None:
        return '—'
    if percentage:
        return f'{pct(reference)}/{pct(value)}/{100*(value-reference):+.1f}点'
    return f'{num(reference)}/{num(value)}/{value-reference:+.2f}'


def render():
    selection, ablation, validation = (read(OUT/(n+'.json')) for n in ('selection', 'ablation', 'validation_complete'))
    cards = {n: read(p/'scorecard.json') for n, p in folders().items()}
    base = cards['registered_master']['years']
    details, nightly, diagnostics = (read(OUT/(n+'.json')) for n in ('legs_2025', 'nightly_2025', 'diagnostics'))
    candidate = {n: cards[n]['years'] for n in X.CANDIDATES}
    returns = lambda n: '、'.join(y+'年'+pct(candidate[n][y]['checks']['return']['ours']) for y in ('2024', '2025'))
    lines = ['# H2：少持几只做到了，买到他的段和高盈亏比没有做到', '',
        ('**两名候选都不合格，没有替换登记master，2026未打开。**' if selection['chosen'] is None else
         f'按冻结选择规则选中{selection["chosen"]}，验证单独列示。'), '',
        '修正实现后的H2A为'+returns('H2A')+'；H2B为'+returns('H2B')+'。'
        '早买段数为'+', '.join(n+' '+str(candidate[n]['2024']['early'])+'/9、'+str(candidate[n]['2025']['early'])+'/22' for n in X.CANDIDATES)+'。'
        '资金纯度远低于登记master的18.1%和16.4%。'
        '把账户集中到四只，并没有让钱集中到他的行情段里。', '',
        '两个候选2025年超过九成的多头已平仓亏损来自已经证实加仓的交易。'
        '按收盘保护成本仍会遇到低开穿线和大幅回落，试仓便宜并没有保证加重后也便宜认错。'
        '因此这轮同时缺在选票覆盖和加重后的盈亏结构，不能只用“集中度达标”解释为更像他。', '',
        '本轮只否定这两个日K版本。策略没有读本人台账、票名或日期，没有为重点股票改规则。'
        '2024–2025已被H1及更早研究看过，本轮属于同段比较。2026仍保留17段的评测分母，未测不能记成0段覆盖。', '',
        '执行纠错已完整保留：首跑多加了“放量退出须在9EMA上方”的条件，偏离任务书。'
        '最终版删除该条件，预登记原文未改，纠错另记在[执行纠错](../notes/H2_EXECUTION_CORRECTION_CN.md)。'
        '首跑H2A的2024/2025为+49.7%/−73.4%，H2B为+0.2%/−72.8%；这些账户和首跑选择、消融、测试均留在'
        '`h2_work/corrections/distribution_filter/`，没有覆盖成最终数字。两次运行都未打开2026。', '',
        '第二次执行纠错把同题材最多两只落实到每晚收盘。此前H2A有一晚因旧仓合组出现三只，第二版全部工件留在'
        '`h2_work/corrections/theme_cap/`，详见[题材上限纠错](../notes/H2_THEME_CAP_CORRECTION_CN.md)。'
        '最终版每晚检查旧仓合组，先退出未证实的弱仓，保持最多两只。H2的全部行情特征及候选参数未改变。', '',
        '归档校验还发现源码快照复制与后续编辑交错。已反向撤销已知的归档后编辑，并要求恢复文件逐字节匹配运行前登记的SHA256。'
        '错误副本另存，原账户工件没有改写；恢复证据在archive_source_repair.json，最终审计再次检查两次归档的全部登记源码。', '',
        '## 同一张记分卡先看覆盖，再看像不像', '',
        '下表全部为2024起、截至2025年末的同一连续窗口。每行最前面的四个数依次为早买、任意成交、段内盈利、全部段。'
        '资金和毛利使用H1的严格Y1代码，未放宽成我们自己的题材。段吃到为段内pnl之和除以实际lot投入名义乘本人总段涨幅，按金额加权。'
        '本人票及本人加窄同伴三数依次为笔数、资金、盈利份额。', '',
        '盈亏比与平均赢单单元为“他/我们/差距”。同时持仓以他约3–4只作参照。前三资金60%和赢单持有5–30日是本轮目标，'
        '本人没有可核实的这两项精确统计，表内不把目标冒充本人实测值。再试参照他约20%。成组占比只报告，不计分。', '']
    main_rows, reference_rows, long_rows, score_cells = [], [], [], []
    for name in (*X.BASELINES, *X.CANDIDATES):
        saved_trades = read(folders()[name]/'trades.json')
        for y, r in cards[name]['years'].items():
            v, h = r['b_values'], r['habits']
            checks = r['checks']
            capital_gap = 100*(r['strict']['cap_equity']-base[y]['strict']['cap_equity'])
            main_rows.append([NAMES[name], y, coverage(r), pct(r['strict']['cap_equity'])+f' ({capital_gap:+.1f}点)',
                pct(r['strict']['purity_gross']), pct(r['capture_total']), shares(r, 'public'), shares(r, 'narrow'),
                pct(checks['return']['ours']), pct(checks['win']['ours']), int(checks['trades']['ours']),
                reference_cell(v['payoff'], 5.), reference_cell(v['avg_win'], .15, True),
                f"3–4/{h['avg_long']:.2f}/距区间{max(0., 3-h['avg_long'], h['avg_long']-4):.2f}",
                f"目标60%/{pct(h['top3_share'])}/{100*(h['top3_share']-.6):+.1f}点" if h['top3_share'] is not None else '—',
                reference_cell(h['repeat_share'], .2, True), pct(h['grouped_share']),
                '目标5–30/'+num(v['holding_win'])+'/距区间'+num(max(0., 5-v['holding_win'], v['holding_win']-30))
                    if v['holding_win'] is not None else '—',
                str(r['b_score'])+'/6', ','.join(k for k, ok in r['hard'].items() if not ok) or '全过'])
            reference_rows.append([NAMES[name], y, coverage(r),
                f"{pct(checks['win']['his'])}/{pct(checks['win']['ours'])}/"+num(checks['win']['ours']/checks['win']['his']),
                f"{int(checks['trades']['his'])}/{int(checks['trades']['ours'])}/"+num(checks['trades']['ours']/checks['trades']['his']),
                f"{pct(checks['return']['his'])}/{pct(checks['return']['ours'])}/{pct(r['return_ratio'])}"])
            long_rows.append([NAMES[name], y, coverage(r), pct(r['strict']['cap_equity']),
                h['long_entries'], pct(h['long_win']), pct(h['long_contribution']), pct(h['short_contribution']),
                pct(h['financing_contribution']), pct(h['long_avg_win']), pct(h['long_avg_loss']),
                num(h['long_avg_win']/abs(h['long_avg_loss'])) if h['long_avg_loss'] and h['long_avg_win'] is not None else '—',
                pct(r['avg_win_invested']), pct(r['avg_loss_invested']),
                num(float(np.median([t['days'] for t in saved_trades if t['side'] > 0 and t['entry'][:4] == y
                    and t['why'] != 'end' and t['pnl'] > 0]))) if any(t['side'] > 0 and t['entry'][:4] == y
                    and t['why'] != 'end' and t['pnl'] > 0 for t in saved_trades) else '—'])
            score_cells.append(dict(system=name, year=y, coverage=coverage(r), values=v, passes=r['b_checks'],
                                    hard=r['hard'], reference_checks=checks))
    lines += [table(['系统', '年', '早/任意/盈利/总', '资金 (差master)', '毛利', '段吃到', '本人笔/资/利',
        '本人+窄伴笔/资/利', '收益', '胜率≤35%', '笔数≥52', '盈亏比 他/我/差', '平均赢 他/我/差',
        '同时多头 他/我/差', '前三资金 目标/我/差', '重做 他/我/差', '成组同日', '赢持有 目标/我/差',
        '像他通过', '硬门槛未过'], main_rows), '',
        '主表硬门槛是每年不亏、胜率≤35%、每年≥52笔，三者都独立判断；六项行为通过数不抵消亏损。'
        'H2A在2025年的盈亏比为'+num(candidate['H2A']['2025']['b_values']['payoff'])+'，H2B为'+
        num(candidate['H2B']['2025']['b_values']['payoff'])+'，距4倍仍远。'
        '同时持仓和前三资金达到要求，但没有因此提高严格段覆盖。', '',
        '主表的笔数、胜率、平均赚亏、盈亏比和赢单持有期包含S7；同时持仓、前三资金、重做及成组只看多头。'
        '下一表单列多头的笔数、胜率、盈亏比、损益贡献和赢单持有中位数。', '',
        '平均赢亏沿H1按整笔pnl除以首仓名义，含后续加仓，所以可能超过100%，不能当成股票本身涨幅。'
        '下一表最后两列另报整笔pnl除以全部实际买入名义，使用同一笔已平仓交易，不靠微小首仓把百分比放大。', '',
        '## 多头损益单独核对，S7维持原规则', '',
        '多头、空头贡献按实际每天持仓与成交重建，均除以该年年初权益。多头贡献加空头贡献减融资即年度权益收益；'
        '它们是同一多空账户的贡献，不是另跑一个纯多头账户的收益。胜率和平均赚亏按开仓年分组，排除end期末估值。', '',
        table(['系统', '年', '早/任意/盈利/总', '资金', '多头笔数', '多头胜率', '多头收益贡献', '空头贡献',
               '融资拖累', '多头平均赢/首仓', '多头平均亏/首仓', '多头盈亏比', '全账平均赢/总投入', '全账平均亏/总投入', '多头赢持有中位'], long_rows), '',
        'S7信号、空头管理和费用不改。多头改变后，账户权益、原反馈输入及可用资金也会改变，因此不宣称H2的空头台账与master相同。'
        '关闭新增功能后，master、M1B、M2A、M3B的完整旧连续台账，以及H1A、H1B原训练台账与权益逐值相同。', '',
        '## 按预登记选择，均未达到覆盖与年度底线', '',
        '每年各自早买与资金必须不低于master，再比较较差年的早买比例、毛利、行为通过项数、盈亏比。'
        '资金门槛使用相同训练窗口的未四舍五入原值，未用显示精度放宽。', '',
        table(['系统', '2024早/任意/盈利/总', '2025早/任意/盈利/总', '2024资金', '2025资金', '淘汰项'],
            [(n, coverage(candidate[n]['2024']), coverage(candidate[n]['2025']),
              pct(candidate[n]['2024']['strict']['cap_equity']), pct(candidate[n]['2025']['strict']['cap_equity']),
              ', '.join(selection['failures'][n])) for n in X.CANDIDATES]), '',
        '没有合格者。'+selection['diagnostic_first']+'只作为消融和工程检查起点，不是带入版。'
        f"2026单开{validation['standalone_evaluations']}次、连续{validation['continuous_evaluations']}次。", '',
        '胜率与笔数不再要求和他差±20%，收益只作参照。下面三列都是“他/我们/我们的比值”，收益参照2024年283%、2025年970%；'
        '2026的869%未用于择优，也没有生成H2验证成绩。', '',
        table(['系统', '年', '早/任意/盈利/总', '胜率 他/我/比', '笔数 他/我/比', '收益 他/我/比'], reference_rows), '',
        '## 上游可达性与损失落在哪一层', '',
        '先忽略账户容量，在每个段仍剩至少一半涨幅的窗口中，逐层检查有无合格收盘。'
        '“报价”是按该候选结构止损实际可交给账户的信号，“市况可开”再要求领涨宽度允许新仓；这些只是早买上限，不保证实际成交。', '']
    reach_rows, loss_rows = [], []
    for n in X.CANDIDATES:
        for y, d in diagnostics[n]['years'].items():
            r = candidate[n][y]
            reach_rows.append([n, y, coverage(r), pct(r['strict']['cap_equity']), *[d['reach'][k] for k in
                ('pool', 'leader', 'form', 'offer', 'market')], d['legs']])
            loss_rows.append([n, y, coverage(r), pct(r['strict']['cap_equity']), pct(d['initial_mean']),
                pct(d['initial_median']), d['confirmed'], d['stop_retries'], num(d['long_profit'], 3),
                num(d['long_loss'], 3), num(d['confirmed_loss'], 3), num(d['probe_loss'], 3),
                ', '.join(f'{k}={v}' for k, v in d['exit_reasons'].items())])
    lines += [table(['系统', '年', '实际早/任意/盈利/总', '资金', '进池', '领涨', '有形态', '报价', '市况可开', '分母'], reach_rows), '',
        '两名候选2024年的早买报价上限都是2/9，低于master已经买到的4/9，也低于至少一半的目标。'
        '9段都曾满足本轮股票池，领涨条件留下4段，离9EMA两ADR及止损条件再留下2段。'
        '所以只在名额、再试或离场上继续改，无法填平2024的覆盖差距。2025的报价上限为9/22，实际只早买1段，另有账户容量损失。', '',
        '这个漏斗使用评测标签检查机会，策略没有读取标签。2024的实际早买均为零，不能靠下游把已经失去资格的票补回来；'
        '有合格报价但未买到的段再看名额、周额度和既有证实仓，不能全归给股票池。完整逐段早买报价日期在diagnostics.json。', '',
        table(['系统', '年', '早/任意/盈利/总', '资金', '首仓均值', '首仓中位', '证实笔数', '止损后再试笔数',
               '多头已平毛利', '多头已平亏损', '其中证实仓亏损', '其中试仓亏损', '退出原因'], loss_rows), '',
        '这些损益单位是该连续账户初始本金1，按开仓年归集，不直接等于年度权益收益。'
        '加仓后收盘止损虽抬到成本，收盘仍可能跳过成本，重仓损失可明显大于原试仓的0.75%风险。'
        '灾难线限制的是报价距离，开盘跳空穿线仍按真实开盘成交，不能保证最终亏损不超过15%。', '',
        '2025年按相对开仓权益排序的最大多头亏损如下，完整前十保存在diagnostics.json。', '',
        table(['系统', '早/任意/盈利/总', '资金', '票', '入场→退出', '证实', '退出原因', '亏/开仓权益', '首仓', '初始结构计划风险'],
            [(n, coverage(candidate[n]['2025']), pct(candidate[n]['2025']['strict']['cap_equity']),
              d['code'].removeprefix('US.'), d['entry']+'→'+d['exit'], '是' if d['confirmed'] else '否', d['why'],
              pct(d['loss_entry_equity']), pct(d['initial_fraction']), pct(d['initial_planned_risk']))
             for n in X.CANDIDATES for d in diagnostics[n]['years']['2025']['largest_losses'][:3]]), '',
        '## 五项消融只诊断，不从中再选', '',
        '以下全部以'+ablation['base']+'为起点，每次只拿掉一项。去题材优先仍保留同题材上限及换仓资格；'
        '一次买满不会被伪标成证实试仓；去数量上限恢复master原本无持仓和周上限、每日四笔有效上限；'
        '去再试禁止实际止损后十个交易日内重开；去反馈同时取消QQQ、五笔止损和领涨宽度条件。', '']
    ablation_rows = []
    for n, value in ablation['results'].items():
        for y, r in value['years'].items():
            delta = 100*(r['checks']['return']['ours']-candidate[ablation['base']][y]['checks']['return']['ours'])
            ablation_rows.append([NAMES[n], y, coverage(r), pct(r['strict']['cap_equity']), pct(r['strict']['purity_gross']),
                pct(r['capture_total']), pct(r['checks']['return']['ours']), f'{delta:+.1f}点',
                num(r['b_values']['payoff']), num(r['habits']['avg_long']), pct(r['habits']['repeat_share']), str(r['b_score'])+'/6'])
    lines += [table(['消融', '年', '早/任意/盈利/总', '资金', '毛利', '段吃到', '收益', '较起点', '盈亏比',
                    '平均多头', '30日重做', '通过项'], ablation_rows), '',
        '这是整账户反事实比较，包含换票、资金和复利的联动。单年改善不替代“两年不亏且覆盖不退”的选择条件。'
        '未按消融结果加第三名候选、换参数或重开2026。', '',
        '## 2025年的22段逐段核对', '',
        '名单夜使用当晚真实数据。首仓和最大仓位沿H1的FIFO归属计算，最大值只计真正归到该段的T1资金；'
        '买在锚点前三日却提前退出的交易可被记为早买，但段内资金和pnl为零，这正是不能只奖励段数的原因。'
        '加仓列只认实际成功证实，后来的加仓不会重置早买时钟。', '']
    order = {r['key']: i for i, r in enumerate(details) if r['system'] == 'H2A'}
    sorted_details = sorted(details, key=lambda r: (order[r['key']], r['system']))
    lines += [table(['段/本人锚点', '系统', '进名单/首次夜', '首笔/相对他交易日', '试仓/段内最大', '证实/日期', '段内pnl', '早买', '未买到/最远层'],
        [(r['code'].removeprefix('US.')+' '+r['anchor'], r['system'],
          ('是 '+r['listed_first']) if r['listed'] else '否',
          r['first_fill']+f" / {r['offset']:+d}" if r['first_fill'] else '未成交',
          pct(r['initial_position'])+'/'+pct(r['max_position']),
          ','.join(r['confirmation_days']) if r['confirmed'] else '否', num(r['leg_pnl'], 4),
          '是' if r['early'] else '否', r['reason']) for r in sorted_details]), '',
        '重点核对没有使用个股例外：量子组的名单与报价时间、PL和AMPX的账户拒绝、ASTS的形态及AMD的名单时间均逐段保留。'
        '不能把“窗口内某夜上过名单”写成“在他入场当天就有资格”；每段的全部报价、升级夜及拒绝次数在legs_2025.json/CSV。', '',
        '## 9月8日至10月1日，每晚的四个名额由谁占用', '',
        '每格写票、收盘仓位、入场日、形态、入场时活跃题材或单票、当晚升级或旧领涨、当前保护。'
        '“试”表示尚未证实且未跌破结构收盘止损；“证”表示成功加仓、有首仓成本保护；“9”表示已减15%，剩余未收破9EMA。'
        '这些就是当晚继续持有的规则理由。入场日按题材、升级、强度、成交额排序，实际买满周额度或名额后不补票；已证实仓不让位。', '']
    nightly_rows = []
    for n, records in nightly.items():
        for r in records:
            cells = []
            for q in r['holdings']:
                form = q['kind'].removeprefix('h2_').replace('pull', '回调').replace('break', '突破').replace('ep', 'EP').replace('_', '+')
                state = '9' if q['trimmed'] else '证' if q['confirmed'] else '试'
                cells.append(q['code'].removeprefix('US.')+' '+pct(q['fraction'])+' ['+q['entry'][5:]+' '+form+'; '+
                    ('活跃题材' if q['entry_group'] is not None else '单票')+'; '+('升级' if q['entry_upgraded'] else '旧领涨')+'; '+state+']')
            nightly_rows.append([r['day'], n, len(cells), r['weekly_new'], '<br>'.join(cells) or '空仓'])
    lines += [table(['当晚', '系统', '多头数', '本周已新开', '持有及原因'], sorted(nightly_rows, key=lambda r: (r[0], r[1]))), '',
        '## 工程验收、工件与下一轮', '',
        '现有引擎按信号日收盘成交，管理从下一交易日开始，本轮按任务书允许沿用。'
        '这是一项收盘成交假设，报告没有把它写成提前知道最终收盘。结构止损按收盘，灾难止损按盘中真实触线或开盘跳空，彼此分开。', '',
        '30%和20%约束新买及加仓的目标名义。持仓被动上涨后不会每日强行卖回上限，所以逐晚表和段内最大仓位可能高于30%；'
        '这项沿用引擎的仓位口径已在预登记写明。', '',
        '真实行情截断到2025-06-30、以及只扰动之后OHLC×3、量×2、额×6，均独立重建领涨、题材、全部新特征和报价；'
        '实际执行与权益前缀一致，并与保存候选的执行前缀相同。默认关闭新增引擎功能，六套旧账户逐值不变。'
        '文件审计钩子阻止策略读取本人标签和评测结果，并阻止网络及子进程。', '',
        '最终两名候选、五项消融及其台账、lots分账、收盘持仓、成交拒绝均在h2_work；'
        '两次纠错前额外四名候选训练账户和十次消融也保留，不能称为总共只运行过两次账户。'
        '放量退出纠错只重建该掩码，其余行情特征逐位不变，见execution_correction.json。', '',
        '下一轮先根据这次的全段漏斗查领涨资格的可达上限，再查四个名额是否长期被不在本人段中的证实仓占用。'
        '同时单列证实加仓后的实际损失与首仓风险，检验“重仓后仍便宜认错”差在哪。'
        '这些只作为下一轮预登记的依据，本轮没有放松集中要求、提高名额或为量子、ASTS、AMPX、PL、AMD加例外。', '',
        '复核入口为h2_research的freeze、baseline、compatibility、register、candidates、ablate、prefix、validate；'
        'h2_report的correction_features、diagnose、explain、audit、tests、render、complete。正式模拟阶段有独占启动文件；'
        '仅重渲染报告可重复运行 `python -m studies.martin_luk.h2_report render`，它只读已存账户。', '',
        '密钥安装器检测到既有hooksPath而停止；已核对现有pre-commit和pre-push均调用secret_guard.py，未覆盖钩子。'
        '本轮不联网、不拉数据、不提交Git、不改登记与看板。来源为[任务书](../notes/PLAN_H2_CN.md)、'
        '[预登记](../notes/PREREG_H2_CN.md)、[日K翻译](../notes/TRANSLATION_CN.md)、'
        '[本人原话](../notes/RULES_CN.md)、[H1](H1_CN.md)、[D1](D1_CN.md)和[T1](T1_CN.md)。']
    if (OUT/'completion.json').exists():
        done = read(OUT/'completion.json')
        lines += ['', table(['测试组', '数量', '结果', '日志'], [(g, r['tests'],
            'OK'+(f'，预期失败{r["expected_failures"]}' if r['expected_failures'] else ''),
            f'[日志](h2_work/test_{g}.log)') for g, r in done['tests'].items()]), '',
            f"实际成交价格/FIFO/费用核对{done['execution_events']}条，阶段最大RSS {done['observed_peak_rss_mib']:.1f} MiB。"
            '全部阶段及测试使用.venv、CPUQuota=60%、MemoryMax=900M、单进程单线程。'
            '逐日期读mmap，相关只算中心向量，没有构造全市场N×N矩阵。'
            '原输入和旧工件指纹未变。完整验收见[completion.json](h2_work/completion.json)。']
    write('scorecard_cells.json', score_cells)
    (HOME/'reports/H2_CN.md').write_text('\n'.join(lines)+'\n')


def complete():
    X.once('complete')
    X.registry_check()
    tests = {g: read(OUT/f'test_{g}_resources.json') for g in ('custody', 'trader_replication', 'martin_luk')}
    assert all(t['ok'] for t in tests.values())
    for name in ('compatibility', 'audit', 'prefix'):
        assert read(OUT/(name+'.json'))['ok']
    protected = read(OUT/'protocol.json')['protected']
    assert all(sha(ROOT/p) == h for p, h in protected.items())
    selection, validation = read(OUT/'selection.json'), read(OUT/'validation_complete.json')
    if selection['chosen'] is None:
        assert validation['standalone_evaluations'] == validation['continuous_evaluations'] == 0
    assert read(OUT/'diagnose_complete.json')['rows'] == 44
    assert all(n == 18 for n in read(OUT/'diagnose_complete.json')['nights'].values())
    sources = [HOME/n for n in ('h2_research.py', 'h2_policy.py', 'h2_report.py', 'tests/test_h2.py',
                                'notes/H2_EXECUTION_CORRECTION_CN.md', 'notes/H2_THEME_CAP_CORRECTION_CN.md')]+[Path(X.Y.__file__)]
    (OUT/'engine_diff.patch').write_text(''.join(difflib.unified_diff(
        (OUT/'original_system.py.txt').read_text().splitlines(True), Path(X.Y.__file__).read_text().splitlines(True),
        fromfile='before_h2/system.py', tofile='after_h2/system.py')))
    observations = {n: read(OUT/(n+'.json'))['resources'] for n in ('baseline_complete', 'compatibility',
        'candidates_complete', 'ablation_complete', 'prefix', 'diagnose_complete', 'explain_complete', 'audit', 'execution_correction')}
    observations.update({'test_'+g: t['after'] for g, t in tests.items()})
    done = dict(ok=True, research_completed=True, strategy_success=False, selected=selection['chosen'],
        independent_out_of_sample=False,
        diagnostic_base=selection['diagnostic_first'], dataset='trader-data-v1',
        data_digest=read(X.PREP/'master_prepared.json')['digest'], train=X.TRAIN, validation=validation,
        final_candidate_accounts=2, final_ablation_accounts=5, additional_archived_candidate_accounts=4,
        additional_archived_ablation_accounts=10, execution_correction=read(OUT/'execution_correction.json'),
        theme_cap_correction=dict(note_sha256=sha(HOME/'notes/H2_THEME_CAP_CORRECTION_CN.md'),
            archive='corrections/theme_cap', every_closing_group_at_most_two=True),
        archived_source_recovery=read(OUT/'archive_source_repair.json'),
        tests=tests, execution_events=read(OUT/'audit.json')['execution_events'],
        preserved_systems=read(OUT/'compatibility.json')['checks'], protected_unchanged=True,
        preregistration_unchanged=True, prereg_sha256=sha(X.PREREG), implementation=read(OUT/'candidates.json'),
        source_sha256={str(p.relative_to(ROOT)): sha(p) for p in sources}, stage_resources=observations,
        observed_peak_rss_mib=max(r['peak_rss_mib'] for r in observations.values()),
        no_network=True, no_new_data=True, no_git_commit=True, registration_and_board_unchanged=True,
        requirements=dict(two_candidates=True, five_ablations=True, six_original_ledgers_exact=True,
            same_H1_Y1_evaluation=True, cutoff_and_future_perturbation=True, strategy_labels_blocked=True,
            all_22_legs_for_both=True, all_requested_nights=True, long_short_PnL_reconciled=True,
            all_three_test_groups=True, validation_not_opened_without_selection=True,
            every_closing_theme_at_most_two=True))
    write('completion.json', done)
    render()
    done['report_sha256'] = sha(HOME/'reports/H2_CN.md')
    write('completion.json', done)
    write('artifact_manifest.json', {str(p.relative_to(OUT)): sha(p) for p in sorted(OUT.rglob('*'))
        if p.is_file() and p.name not in ('artifact_manifest.json', 'complete.log')})
    for n in X.CANDIDATES:
        card = read(OUT/f'candidates/{n}/scorecard.json')
        print(n+': '+', '.join(y+' '+pct(r['checks']['return']['ours'])+'，早买'+str(r['early'])+'/'+str(r['leg_count'])
                              for y, r in card['years'].items()))
    print('两者均未过年度收益与覆盖底线；五项消融完成，2026评测0+0。')
    print('六套旧台账逐值不变；截断及未来扰动执行和权益前缀一致。')
    print('测试：'+', '.join(g+' '+str(r['tests'])+' OK' for g, r in tests.items()))
    print('报告：studies/martin_luk/reports/H2_CN.md')
    print('下一轮：先查领涨可达上限、四仓名额占用与证实加仓后的实际损失。')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=('correction_features', 'diagnose', 'audit', 'explain', 'tests', 'render', 'complete'))
    parser.add_argument('--group', choices=('custody', 'trader_replication', 'martin_luk'))
    args = parser.parse_args()
    if args.stage == 'tests':
        test_group(args.group)
    X.offline()
    globals()[args.stage]()


if __name__ == '__main__':
    main()
