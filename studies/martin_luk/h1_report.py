"""Read saved H1 accounts, diagnose missed legs, verify artifacts, and render Chinese findings."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
import difflib
import gc
import json
from pathlib import Path
import sys
import unittest

import numpy as np

from . import h1_research as X, h1_policy as H

OUT, HOME, ROOT = X.OUT, X.HOME, X.ROOT
read, write, sha, clean = X.read, X.write, X.sha, X.clean
NAMES = {'registered_master': '登记master', 'M1B': 'M1B', 'M2A': 'M2A', 'M3B': 'M3B',
         'H1A': 'H1A', 'H1B': 'H1B', **{'without_'+k: '去H-'+k for k in 'abcde'}, 'only_ab': '仅H-a+H-b'}


def folders():
    result = {n: OUT/'baseline/train'/n for n in X.BASELINES}
    result.update({n: OUT/'candidates'/n for n in X.CANDIDATES})
    if (OUT/'ablation.json').exists():
        result.update({n: OUT/'ablation'/n for n in read(OUT/'ablation.json')['results']})
    return result


def engineering_prefix():
    """Failure to select a strategy does not waive the task's no-future engineering requirement."""
    X.once('prefix')
    X.registry_check()
    selection = read(OUT/'selection.json')
    tested = selection['chosen'] or selection['diagnostic_first']
    values = {}
    for variant, directory in (('train', X.PREP), ('cut', HOME/'reports/m1_work/prefix_cut'),
                               ('perturbed', HOME/'reports/m1_work/prefix_perturbed')):
        with X.strategy_only():
            A = X.arrays(directory)
        values[variant] = X.prefix_value(A, directory, variant, X.CANDIDATES[tested])
        write('prefix_'+variant+'.json', values[variant])
        del A
        gc.collect()
    checks = {v: {k: values[v][k] == values['train'][k] for k in values['train']} for v in ('cut', 'perturbed')}
    original = read(OUT/f'candidates/{tested}/trades.json')
    assert values['train']['events'] == clean(X.M.E15.B.execution_events(original, X.CUT))
    assert all(all(v.values()) for v in checks.values()), checks
    write('prefix.json', dict(ok=True, chosen=selection['chosen'], tested=tested, cutoff=X.CUT,
        checks=checks, actual_executions=len(values['train']['events']), resources=X.resources(),
        strategy_reads=sorted(X.STRATEGY_READS), independent_rebuild=True,
        no_selection_does_not_waive_engineering_check=selection['chosen'] is None))


def curve_array(curve, days):
    values = np.ones(len(days))
    di = {str(d): i for i, d in enumerate(days)}
    for d, e in zip(curve['days'], curve['equity']):
        values[di[d]] = e
    return values


def leg_positions(part, leg, A, equity):
    daily = np.zeros(len(A['days']))
    j = next(i for i, c in enumerate(A['codes']) if c == leg['code'])
    for r in part:
        if r['bucket'] != 'T1':
            continue
        start, stop = r['entry'], min(r['exit']+int(r['open']), leg['peak']+1)
        daily[start:stop] += r['shares']*A['close'][start:stop, j]
    first = min(part, key=lambda r: (r['entry'], str(r['trade']), r['source'])) if part else None
    if first:
        qty = sum(r['shares'] for r in part if r['trade'] == first['trade'] and r['source'] == first['source'])
        initial = qty*first['price']/equity[first['entry']]
    else:
        initial = None
    return initial, float(np.max(daily/equity))


def attempt_source(name):
    if name in X.CANDIDATES:
        return OUT/'candidates'/name/'attempts.jsonl', False
    if name == 'registered_master':
        return HOME/'reports/d1_work/master_attempts.json', True
    return HOME/'reports'/dict(M1B='m1_work', M2A='m2_work', M3B='m3_work')[name]/'candidates'/name/'attempts.jsonl', False


def attempts(path, array=False):
    if array:
        yield from read(path)
    else:
        with path.open() as stream:
            for line in stream:
                yield json.loads(line)


def habit_stats(trades, management, days):
    di = {str(d): i for i, d in enumerate(days)}
    output = {}
    for year in ('2024', '2025'):
        longs = sorted([t for t in trades if t['side'] > 0 and t['entry'][:4] == year], key=lambda t: t['entry'])
        previous, repeated, stopped = {}, [], []
        # Include the preceding year's account attempts for January's retry count.
        history = sorted([t for t in trades if t['side'] > 0 and t['entry'][:4] <= year], key=lambda t: t['entry'])
        for t in history:
            last = previous.get(t['code'])
            if t['entry'][:4] == year and last:
                if di[t['entry']]-di[last['entry']] <= 30:
                    repeated.append(t)
                if last['why'] in ('stop', 'gap_stop', 'close_stop', 'stop_day0') and last['exit'] <= t['entry']:
                    stopped.append(t)
            previous[t['code']] = t
        cohorts = defaultdict(list)
        for e in management.get('habit_entries', []):
            if e['day'][:4] == year and e['side'] > 0 and e['group'] is not None:
                cohorts[(e['day'], e['group'])].append(e['code'])
        grouped = {key: cs for key, cs in cohorts.items() if len(cs) >= 2}
        trade_lookup = {(t['entry'], t['code']): t for t in longs}
        same_stop, group_examples = 0, []
        for (day, group), codes in grouped.items():
            exits = Counter(trade_lookup[(day, c)]['exit'] for c in codes if
                trade_lookup[(day, c)]['why'] in ('stop', 'gap_stop', 'close_stop', 'stop_day0'))
            same_stop += sum(v for v in exits.values() if v >= 2)
            group_examples.append(dict(day=day, group=group, codes=codes,
                pnl=sum(trade_lookup[(day, c)]['pnl'] for c in codes), joint_stop_days={k: v for k, v in exits.items() if v >= 2}))
        closed = [t for t in longs if t['why'] != 'end']
        output[year] = dict(long_entries=len(longs), repeat_30_sessions=len(repeated),
            repeat_share=len(repeated)/len(longs) if longs else None,
            actual_stop_retries=len(stopped), retry_pnl=sum(t['pnl'] for t in stopped),
            retry_losses=sum(t['pnl'] for t in stopped if t['pnl'] < 0),
            retry_wins=sum(t['pnl'] for t in stopped if t['pnl'] > 0),
            grouped_entry_days=len(grouped), grouped_entries=sum(map(len, grouped.values())),
            same_cohort_same_day_stops=same_stop, group_examples=group_examples,
            days_win_median=float(np.median([t['days'] for t in closed if t['pnl'] > 0])) if any(t['pnl'] > 0 for t in closed) else None,
            days_loss_median=float(np.median([t['days'] for t in closed if t['pnl'] <= 0])) if any(t['pnl'] <= 0 for t in closed) else None,
            avg_win_invested=float(np.mean([t['ret_invested'] for t in closed if t['pnl'] > 0])) if any(t['pnl'] > 0 for t in closed) else None,
            avg_loss_invested=float(np.mean([t['ret_invested'] for t in closed if t['pnl'] <= 0])) if any(t['pnl'] <= 0 for t in closed) else None)
    return output


def diagnose():
    X.once('diagnose')
    A, f = X.arrays(X.PREP), None
    f = X.feature_set(A, 'train')
    frozen = read(HOME/'notes/legs_frozen.json')
    legs = [g for g in frozen['legs'] if g['first_date'].startswith('2025')]
    assert len(legs) == 22
    di, ci = {str(d): i for i, d in enumerate(A['days'])}, {str(c): i for i, c in enumerate(A['codes'])}
    raw, filtered, native = (X.M.load_book(X.PREP, n) for n in ('master_raw', 'master_filtered', 'native'))
    focus_codes = {'US.QBTS', 'US.IONQ', 'US.RGTI', 'US.ASTS', 'US.AMPX', 'US.PL'}
    focus = [g for g in legs if g['code'] in focus_codes and g['first_date'] >= '2025-09-01']
    focus_dates = {str(A['days'][d]) for g in focus for d in range(g['first']-3, min(g['peak'], len(A['days'])))}
    all_rows, crowding, habits = [], {}, {}
    base_folders = folders()
    for name, folder in base_folders.items():
        trades, curve = read(folder/'trades.json'), read(folder/'curve.json')
        management = read(folder/'management.json') if (folder/'management.json').exists() else {}
        habits[name] = habit_stats(trades, management, A['days'])
        if name not in (*X.BASELINES, *X.CANDIDATES):
            continue
        rows, card = read(folder/'lots.json'), read(folder/'scorecard.json')
        equity = curve_array(curve, A['days'])
        if name in X.CANDIDATES:
            book, _, _, memberships = H.build(A, X.PREP, f, X.CANDIDATES[name])
        else:
            book = native if name == 'registered_master' else filtered
            memberships = [{} for _ in A['days']]
        by_leg = {g['key']: [] for g in legs}
        states = {}
        for r in attempts(*attempt_source(name)):
            if r['day'] > X.TRAIN[1] or r.get('kind', '').startswith('s_'):
                continue
            if r['day'] in focus_dates and r['day'] not in states:
                states[r['day']] = dict(held=r.get('held'), positions=r['positions'], new_longs=r['new_longs'])
            d = di.get(r['day'])
            if d is None:
                continue
            for g in legs:
                if r['code'] == g['code'] and g['first']-3 <= d < g['peak']:
                    by_leg[g['key']].append({k: v for k, v in r.items() if k != 'held'})
        for day in focus_dates:
            d = di[day]
            states.setdefault(day, dict(held=None, positions=None, new_longs=0))
            states[day].update(actual_new=[t['code'] for t in trades if t['entry'] == day and t['side'] > 0],
                offered_front=[str(A['codes'][e[1]]) for e in sorted(book[d], key=lambda e: e[0]) if e[2] > 0][:4])
        crowding[name] = states
        for g in legs:
            j = ci[g['code']]
            window = range(max(0, g['first']-3), min(g['peak'], len(A['days'])))
            pool_days = [d for d in window if A['master_pool'][d, j]]
            listed = [d for d in window if A['master_watch'][d, j] or A['b_eligible'][d, j] or j in memberships[d]]
            raw_days = [d for d in window if any(e[1] == j and e[2] > 0 for e in raw[d])]
            filtered_days = [d for d in window if any(e[1] == j and e[2] > 0 for e in filtered[d])]
            offered = [d for d in window if any(e[1] == j and e[2] > 0 for e in book[d])]
            attn_fail = [d for d in filtered_days if not f['attention'][d, j]] if name in X.CANDIDATES else []
            part = [r for r in rows if r['leg'] == g['key']]
            covered = next(g2 for g2 in card['legs'] if g2['key'] == g['key'])
            initial, maximum = leg_positions(part, g, A, equity)
            reasons = Counter(r['reason'] for r in by_leg[g['key']])
            if covered['any']:
                reason = ('早买' if covered['covered'] else '晚买')+('且段内盈利' if covered['pnl'] > 0 else '但段内未盈利')
            elif not pool_days:
                reason = '未进流动性池'
            elif not listed:
                reason = '未进名单/题材组'
            elif not raw_days and not offered:
                reason = '名单内没有合格日K触发'
            elif not filtered_days and not offered:
                reason = '市况过滤'
            elif not offered:
                reason = 'H-b关注度门槛' if attn_fail else '原成交额每日预截四名'
            else:
                reason = '账户拒绝：'+','.join(f'{k}={v}' for k, v in reasons.items() if k != 'filled')
            all_rows.append(dict(system=name, key=g['key'], code=g['code'], anchor=g['first_date'],
                precision=g['precision'], pool_first=str(A['days'][pool_days[0]-1]) if pool_days else None,
                listed=bool(listed), listed_first=str(A['days'][listed[0]-1]) if listed else None,
                first_fill=str(A['days'][covered['first_fill']['index']]) if covered['first_fill'] else None,
                offset=covered['offset'], early=covered['covered'], any=covered['any'],
                initial_position=initial, max_position=maximum, leg_pnl=covered['pnl'],
                reason=reason, raw_dates=[str(A['days'][d]) for d in raw_days],
                offered_dates=[str(A['days'][d]) for d in offered], attention_rejected_dates=[str(A['days'][d]) for d in attn_fail],
                account_reasons=reasons, attempts=by_leg[g['key']]))
    write('legs_2025.json', all_rows)
    columns = ('system', 'code', 'anchor', 'precision', 'listed', 'listed_first', 'first_fill', 'offset',
               'initial_position', 'max_position', 'leg_pnl', 'early', 'reason')
    with (OUT/'legs_2025.csv').open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=columns, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(all_rows)
    write('crowding_2025.json', crowding)
    write('habits.json', habits)
    write('diagnose_complete.json', dict(resources=X.resources(), legs=len(legs), comparisons=len(all_rows)))


def audit():
    """Check actual OHLC fills, FIFO sums, caps, risk sharing, and the frozen input boundary."""
    X.once('audit')
    blocked_labels = {}
    for path in (HOME/'notes/trades.csv', HOME/'notes/legs_frozen.json', HOME/'reports/t1_work/groups.jsonl',
                 OUT/'baseline_scorecards.json'):
        with X.strategy_only():
            try:
                path.read_bytes()
            except PermissionError:
                blocked_labels[str(path.relative_to(ROOT))] = True
            else:
                raise AssertionError('strategy label guard did not reject '+str(path))
    p = {n: np.load(X.FULL/(n+'.npy'), mmap_mode='r') for n in ('open', 'high', 'low', 'close')}
    meta = read(X.FULL/'ie_prepared.json')
    di, ci = {d: i for i, d in enumerate(meta['days'])}, {c: i for i, c in enumerate(meta['codes'])}
    checks, events = {}, 0
    for name, folder in folders().items():
        trades = read(folder/'trades.json')
        rows = read(folder/'lots.json')
        assert abs(sum(t['pnl'] for t in trades)-sum(r['pnl'] for r in rows)) < 1e-8, name
        for t in trades:
            j = ci[t['code']]
            for e in t['executions']:
                d, price = di[e['time']], e['price']
                epsilon = 2*max(abs(float(np.spacing(p['low'][d, j]))), abs(float(np.spacing(p['high'][d, j]))))
                assert float(p['low'][d, j])-epsilon <= price <= float(p['high'][d, j])+epsilon, (name, t['code'], e)
                events += 1
        if (folder/'management.json').exists():
            mgmt = read(folder/'management.json')
            rules = read(folder/'rules.json')
            grouped = defaultdict(list)
            episodes = Counter()
            for r in mgmt.get('habit_entries', []):
                assert r['notional_fraction'] <= rules['max_position']+1e-12, (name, r)
                if r['group'] is not None:
                    grouped[(r['day'], r['group'])].append(r)
                if r['side'] > 0 and rules['entry_episode_max']:
                    episodes[(r['code'], r['episode'])] += 1
            assert not episodes or max(episodes.values()) <= 3, name
            for rs in grouped.values():
                assert len(rs) <= 3, (name, rs)
                if rules['equity_state_days']:
                    assert sum(r['stop_risk_fraction'] for r in rs) <= rs[0]['state_risk']+1e-12, (name, rs)
        checks[name] = dict(fifo_reconciled=True, fills_in_actual_range=True, trades=len(trades))
    protocol = read(OUT/'protocol.json')
    protected = {s: sha(ROOT/s) == h for s, h in protocol['protected'].items()}
    assert all(protected.values()), [p for p, ok in protected.items() if not ok]
    write('audit.json', dict(ok=True, accounts=checks, execution_events=events,
          protected_unchanged=True, protected_checks=protected, label_reads_rejected=blocked_labels,
          resources=X.resources()))


def rescore():
    """Correct evaluation partitioning from saved ledgers; never execute a candidate again."""
    if (OUT/'scorecard_correction_started.json').exists():
        assert not (OUT/'source_compatibility.json').exists(), 'evaluation correction already completed'
        X.once('scorecard_correction_resumed')
        write('corrections/profit_denominator/resume_reason.json', dict(
            reason='Preserve each saved scorecard original calendar length; initial rescore stopped at first candidate leg-list assertion',
            account_simulations=0, parameter_changes=0))
    else:
        X.once('scorecard_correction')
    registry = read(OUT/'candidates.json')
    archive = OUT/'corrections/profit_denominator'
    assert sha(archive/'original_h1_research.py.txt') == registry['code_sha256']['studies/martin_luk/h1_research.py']
    destinations = dict(folders())
    destinations.update({n+'_continuous': OUT/'baseline/continuous'/n for n in X.BASELINES})
    account_hashes = {str(p.relative_to(OUT)): sha(p) for folder in destinations.values()
                      for p in (folder/n for n in ('trades.json', 'curve.json', 'rules.json', 'lots.json'))}
    A, directory, labels, updated = None, None, X.evaluation_labels(), {}
    for name, folder in destinations.items():
        wanted = X.FULL if name in X.BASELINES or name.endswith('_continuous') else X.PREP
        if directory != wanted:
            del A
            gc.collect()
            A, directory = X.arrays(wanted), wanted
        tr, curve, policy = read(folder/'trades.json'), read(folder/'curve.json'), read(folder/'rules.json')
        span = (X.TRAIN[0], X.VALID[1]) if name.endswith('_continuous') else X.TRAIN
        value, _ = X.scorecard(A, tr, curve, X.Y.Rules(**policy), span, labels)
        original = read(folder/'scorecard.json')
        assert value['legs'] == original['legs']
        for y, r in value['years'].items():
            assert r['score'] == original['years'][y]['score']
            for key in ('win', 'avg_win', 'avg_loss', 'payoff', 'trades', 'return'):
                assert r['checks'][key] == original['years'][y]['checks'][key]
            assert r['checks']['narrow_profit']['ours']+1e-12 >= r['checks']['public_profit']['ours']
        write(folder/'scorecard.json', value)
        updated[name] = value
    baselines = dict(train={n: updated[n] for n in X.BASELINES},
                     continuous={n: updated[n+'_continuous'] for n in X.BASELINES})
    write('baseline_scorecards.json', baselines)
    candidates = {n: updated[n] for n in X.CANDIDATES}
    write('candidates_train.json', candidates)
    selection = X.select(candidates)
    original_selection = read(OUT/'selection.json')
    assert all(selection[k] == original_selection[k] for k in ('chosen', 'eligible', 'diagnostic_first'))
    write('selection.json', selection)
    ablation = read(OUT/'ablation.json')
    ablation['results'] = {n: updated[n] for n in ablation['results']}
    write('ablation.json', ablation)
    assert all(sha(OUT/p) == h for p, h in account_hashes.items())
    corrected_sources = {p: sha(ROOT/p) for p in registry['code_sha256']}
    write('source_compatibility.json', dict(registered_code_sha256=registry['code_sha256'],
        corrected_code_sha256=corrected_sources, registry_sha256=sha(OUT/'candidates.json'),
        prereg_sha256=sha(X.PREREG), evaluation_only=True, candidate_account_reruns=0,
        reason='Public and public+peer profit fractions now use the same FIFO/time partition and denominator',
        unchanged_behavior_scores=True, unchanged_choice=True, unchanged_account_hashes=account_hashes,
        old_scorecards='corrections/profit_denominator', resources=X.resources()))
    X.registry_check()


def test_group(group):
    def no_network(event, args):
        if event in ('socket.connect', 'socket.bind', 'socket.getaddrinfo'):
            raise PermissionError('H1 tests are offline')
    sys.addaudithook(no_network)
    before = X.resources()
    directory = 'custody/tests' if group == 'custody' else 'studies/'+group+'/tests'
    result = unittest.TextTestRunner(verbosity=1).run(unittest.defaultTestLoader.discover(directory))
    write('test_'+group+'_resources.json', dict(tests=result.testsRun, ok=result.wasSuccessful(),
        failures=len(result.failures), errors=len(result.errors), expected_failures=len(result.expectedFailures),
        before=before, after=X.resources()))
    sys.exit(0 if result.wasSuccessful() else 1)


def pct(x):
    return '—' if x is None else f'{100*x:.1f}%'


def num(x, digits=2):
    return '—' if x is None else f'{x:.{digits}f}'


def table(headers, rows):
    return '\n'.join(['| '+' | '.join(headers)+' |', '| '+' | '.join('---' for _ in headers)+' |']+
                     ['| '+' | '.join(map(str, row))+' |' for row in rows])


def cell(r, kind='pct'):
    fmt = (lambda v: '—' if v is None else str(int(v))) if kind == 'int' else (lambda v: num(v)) if kind == 'num' else pct
    gap = '—' if r['relative_gap'] is None else f'{r["relative_gap"]*100:+.1f}%'
    mark = '—' if r['within20'] is None else '是' if r['within20'] else '否'
    return f'{fmt(r["his"])} / {fmt(r["ours"])} / {gap} / {mark}'


def render():
    selection = read(OUT/'selection.json')
    cards = {n: read(p/'scorecard.json') for n, p in folders().items()}
    continuous = read(OUT/'baseline_scorecards.json')['continuous']
    for n in X.BASELINES:
        cards[n]['years']['2026'] = continuous[n]['years']['2026']
    habits, legs = read(OUT/'habits.json'), read(OUT/'legs_2025.json')
    with (HOME/'notes/trades.csv').open() as stream:
        public_rows = [r for r in csv.DictReader(stream) if r['side'] == 'long']
    write('input_counts.json', dict(actual_long_rows=len(public_rows),
        actual_long_tickers=len({r['ticker'] for r in public_rows}), task_quoted_long_rows=87,
        missing_frozen_records=[r for r in read(HOME/'notes/legs_frozen.json')['audit'] if r['reason']]))
    retry_history = {}
    for name in X.CANDIDATES:
        tr = read(OUT/'candidates'/name/'trades.json')
        mg = read(OUT/'candidates'/name/'management.json')['habit_entries']
        retry_history[name] = []
        for e in mg:
            if e['side'] > 0 and e['code'] in ('US.IONQ', 'US.RGTI') and '2025-01-01' <= e['day'] < '2025-09-08':
                t = next(t for t in tr if t['code'] == e['code'] and t['entry'] == e['day'] and t['side'] > 0)
                retry_history[name].append(dict(e, exit=t['exit'], why=t['why'], pnl=t['pnl']))
    write('retry_history_2025.json', retry_history)
    a, b = cards['H1A']['years'], cards['H1B']['years']
    lines = ['# H1：五个习惯加进去以后，仍没有合格方案', '',
        f'**H1A、H1B都未过每年不亏的底线，没有选中者。** H1A的2024/2025收益为{pct(a["2024"]["checks"]["return"]["ours"])}/{pct(a["2025"]["checks"]["return"]["ours"])}；'
        f'H1B为{pct(b["2024"]["checks"]["return"]["ours"])}/{pct(b["2025"]["checks"]["return"]["ours"])}。'
        '它们没有替代登记master，也没有因笔数增加就完成“像他”。', '',
        '按冻结规则，H1A只作为消融的诊断起点。截断和未来扰动仍做工程核验；候选2026单开/连续评测均未打开。'
        '下文2026基线列只读取早已保存的原账户，不是H1的新验证。', '',
        '2025年的早买从登记master的4/22提高到两个H1的7/22，但H1A/H1B实际笔数仍只有558/498，胜率为17.1%/15.3%，均低于本人约22%。'
        '段数有改善，整套账户的收益和行为仍未达到目标。', '',
        '重点漏项已换了一层：PL、AMPX被85分位关注度门槛挡住；IONQ、RGTI在同一因果段的三次首开已于5–6月耗完，9月机会全部被拒绝；'
        'ASTS被总敞口和每日成功成交数挡住；QBTS在H1A/H1B分别到9月18日/24日才成交，已不是早买。'
        '本轮定位的是这份日K实现和规则之间的相互阻挡。', '',
        '## 记分卡B：先核参照，再看结果', '',
        '表格单元统一为“他 / 我们 / 相对差 / 是否±20%”，相对差=我们÷他−1，使用未四舍五入值判定。'
        '前五列进入候选计分；持有期缺可计算的本人退出，不编参照。收益只看不亏及比例，不按收益大小选择。', '',
        '参照来自任务书及本地已存资料：[PLAN_H1_CN](../notes/PLAN_H1_CN.md)、'
        '[RULES_CN](../notes/RULES_CN.md)的VKNE@0:20:24（2025年209赢/731亏）、'
        '[SOURCES](../notes/SOURCES.md)所列TraderLion访谈（2024年104赢/319亏、+15%/−3%、35%单票上限）。'
        '本轮离线引用，未重新联网核验。2024胜率用104/423=24.59%，2025用209/940=22.23%；笔数按任务书约420/940，另保留2024精确合计423。', '',
        '输入数量核对：实际冻结台账为96条多头、57只股票，与任务书摘要中的87条不同；本轮沿文件指纹原样评测，没有删改原台账。'
        '其中3条缺冻结行情继续保留为未决记录，明细见input_counts.json。', '',
        '主表2024–25均截止2025年末，与候选使用同一连续训练窗口；四个基线的2026行只读已有完整连续账，未重开H1验证。'
        '登记master与H1包含S7空头，M1B/M2A/M3B是原有多头账户。笔数按开仓年，胜率/平均赚亏排除年末估值；'
        '平均赚亏用含加仓的整笔pnl÷首仓名义，因此另在habits.json保存按全部投入资金计算的收益。'
        '本金为1，H是段内金额；年度权益收益另含融资与跨年持仓估值，两者不直接相减。', '',
        table(['系统', '年', '胜率', '平均赢', '平均亏', '盈亏比', '笔数', '赢单持有天', '亏单持有天', '行为计分', '收益：他/我/比例/不亏'],
            [(NAMES[n], y, cell(r['checks']['win']), cell(r['checks']['avg_win']), cell(r['checks']['avg_loss']),
              cell(r['checks']['payoff'], 'num'), cell(r['checks']['trades'], 'int'),
              cell(r['checks']['holding_win'], 'num'), cell(r['checks']['holding_loss'], 'num'),
              f'{r["score"]}/{r["scored_items"]}',
              f'{pct(r["checks"]["return"]["his"])} / {pct(r["checks"]["return"]["ours"])} / {pct(r["return_ratio"])} / '+('是' if r['nonnegative'] else '否'))
             for n in (*X.BASELINES, *X.CANDIDATES) for y, r in cards[n]['years'].items()]), '',
        '买票各列的“他=100%”仅表示完全落在**当年公开样本**的描述参照，不是他完整账户经审计的真实资金/盈利分布，'
        '所以不进入五项行为计分，也不设新的纯度门槛。仅比较当年公开多头名字，不读以后年份的名字作该年评测。'
        '资金列是投入名义份额，含空头的总名义作分母，空仓日贡献零；盈利列是正pnl份额。'
        '窄同伴剔除T1标过宽的OKLO五月、UPST五月、HOOD五月、IONQ五月四段新增同伴，保留本人票本身。'
        '同伴按实际买入当晚冻结，未把其他日期持仓追溯贴标签；两个盈利份额使用同一FIFO/时间切片和同一正pnl分母，费用不重复。'
        '纯评测口径修正：最初本人票按整笔、同伴按切片，可能使扩大集合后的占比反而下降。已从保存台账统一重算，'
        '修正前20份记分工件和源码保留在corrections/profit_denominator；账户、五项行为得分、无合格者的结论和消融对象全部不变，未重跑任何候选。', '',
        table(['系统', '年', '本人票：笔数份额', '本人票：资金份额', '本人票：盈利份额', '本人+窄同伴：笔数', '本人+窄同伴：资金', '本人+窄同伴：盈利'],
            [(NAMES[n], y, *(cell(r['checks'][k]) for k in ('public_trades', 'public_capital', 'public_profit',
                'narrow_trades', 'narrow_capital', 'narrow_profit')))
             for n in (*X.BASELINES, *X.CANDIDATES) for y, r in cards[n]['years'].items()]), '',
        '冻结48段的9/22/17分母不变；三个缺冻结行情的公开记录继续留在未决表，2026两段截断保留。'
        '本人实得的各段pnl和持有期缺结构化退出数据，不用事后最高价补成他的卖出。早买/任意成交的100%也是描述参照，段资金和毛利纯度只作参考。', '',
        table(['系统', '年', '早买段（参照/我/差/±20%）', '任意成交段（参照/我/差/±20%）', '段内正pnl段/分母', '段内pnl：他/我/差', 'Y1资金/权益日', 'Y1毛利纯度', '窄题材资金/权益日', '窄题材毛利纯度'],
            [(NAMES[n], y, cell(r['checks']['early_legs'])+f'（{r["early"]}/{r["leg_count"]}）',
              cell(r['checks']['any_legs'])+f'（{r["any"]}/{r["leg_count"]}）', f'{r["positive_legs"]}/{r["leg_count"]}',
              '— / '+num(r['checks']['leg_pnl']['ours'], 3)+' / —', pct(r['strict']['cap_equity']),
              pct(r['strict']['purity_gross']), pct(r['narrow']['cap_equity']), pct(r['narrow']['purity_gross']))
             for n in (*X.BASELINES, *X.CANDIDATES) for y, r in cards[n]['years'].items()]), '',
        '## 选择、消融与习惯的代价', '',
        f'预登记SHA256：`{sha(X.PREREG)}`。候选只有H1A/H1B；排序先要求两年不亏，再取较差年的五项行为计分，最后取较差年本人票+窄同伴盈利份额。'
        '两个候选都不合格，selection.json中的diagnostic_first=H1A只决定消融对象，不是策略选择。', '',
        table(['诊断', '年', '收益', '对H1A收益差（百分点）', '胜率', '平均赢/亏', '盈亏比', '笔数', '行为计分', '本人+窄同伴盈利', '早买/任意/分母'],
            [(NAMES[n], y, pct(r['checks']['return']['ours']), f'{100*(r["checks"]["return"]["ours"]-a[y]["checks"]["return"]["ours"]):+.1f}',
              pct(r['checks']['win']['ours']), pct(r['checks']['avg_win']['ours'])+'/'+pct(r['checks']['avg_loss']['ours']),
              num(r['checks']['payoff']['ours']), r['checks']['trades']['ours'], f'{r["score"]}/5',
              pct(r['narrow_profit_share']), f'{r["early"]}/{r["any"]}/{r["leg_count"]}')
             for n in ('H1A', *('without_'+k for k in 'abcde'), 'only_ab') for y, r in cards[n]['years'].items()]), '',
        '每项消融的完整同口径记分卡在对应scorecard.json，另有scorecards_all.csv，包含上述所有“他/我/差/±20%”列；'
        '这里压成六个诊断行×两年，便于看机制代价，不从中追加候选。相减是完整账户反事实差，包含名额、资金和复利相互影响，不能把差全归给某笔小亏。', '',
        table(['系统', '年', '多头首开', '30交易日内重做', '重做份额（本人约20%仅参考）', '实际止损后再试', '再试pnl/其中亏损', '同日成组批次/笔数', '同组同日止损笔数', '赢/亏持有中位天'],
            [(NAMES[n], y, r['long_entries'], r['repeat_30_sessions'], pct(r['repeat_share']), r['actual_stop_retries'],
              num(r['retry_pnl'], 3)+'/'+num(r['retry_losses'], 3), f'{r["grouped_entry_days"]}/{r["grouped_entries"]}',
              r['same_cohort_same_day_stops'], num(r['days_win_median'])+'/'+num(r['days_loss_median']))
             for n in ('H1A', 'H1B', 'without_d', 'only_ab') for y, r in habits[n].items()]), '',
        'H-d没有可取消的master同票冷却；它本轮真正新增的是每个因果趋势段三次首开的上限。'
        '不把它与M3原来的“止损后10日首个收回”机制混为一谈。因果段只在21 EMA重新上穿50 EMA时重置，未使用本人峰值或日期。'
        'H-e风险是绝对0.25/0.5/1%，回撤降风险优先，35%约束新增资金，行情被动涨过35%不会强卖。', '',
        'H-a在这个组合中对两年收益均有帮助：关掉后2024/2025再少4.3/10.7个百分点；H-c影响较小。'
        'H-b和H-d有跨年取舍：去掉其中一条可让2024转盈，却让2025更差；去H-e可把2025变成+5.9%，2024仍为−43.6%。'
        '这些消融均未成为新增候选，不能用一年的改善替换整组底线。', '',
        '三次上限的具体失配：H1A的IONQ在5月12日、6月6日、6月13日已用完同一段，RGTI在5月12/14/16日用完；'
        'H1B的IONQ为5月12/22/27日，RGTI相同。21/50 EMA分段把5月与9月连在一起。'
        '因此本版本的拒绝首先落在因果分段粒度，不能直接据此否定本人“止损后再试”的习惯；全部真实尝试和退出保存在retry_history_2025.json。', '',
        '## 2025年的22段：到底卡在哪里', '',
        '名单夜使用前一完成夜；首笔与最大仓位分别为首lot名义/当日收盘权益、段窗口内实际归属lot的最大收盘名义/权益。'
        '日差是交易日，负数为早于本人锚点。所有系统用同一Y1 FIFO分账，后来的加仓或再试不重置早买时钟。'
        '主表列登记master与两个H1，另外三个基线的全部逐段结果在legs_2025.csv/json（共132行）。', '',
        table(['段（本人锚点）', '系统', '名单/首次夜', '首笔日/相对他', '首仓/峰前最大', '段内pnl', '早买', '最远一层'],
            [(r['code'].removeprefix('US.')+' '+r['anchor'], NAMES[r['system']],
              ('是 '+r['listed_first']) if r['listed'] else '否',
              (r['first_fill']+f' / {r["offset"]:+d}') if r['first_fill'] else '未成交',
              pct(r['initial_position'])+'/'+pct(r['max_position']), num(r['leg_pnl'], 3), '是' if r['early'] else '否', r['reason'])
             for g in [g for g in read(HOME/'notes/legs_frozen.json')['legs'] if g['first_date'].startswith('2025')]
             for r in legs if r['key'] == g['key'] and r['system'] in ('registered_master', 'H1A', 'H1B')]), '',
        '重点日期真实占仓与每日名额如下；“前四报价”与“实际新成交”分开，已持同票或风险拒绝会使两者不同。'
        '每个重点段从first−3至peak前的所有夜晚均保存在crowding_2025.json，完整拒绝理由在attempts.jsonl。', '',
        table(['日期', '系统', '开多前已有仓位', '前四报价', '当日实际新开多'],
            [(d, NAMES[n], ', '.join(h['code'].removeprefix('US.') for h in (r['held'] or [])) or '—',
              ', '.join(c.removeprefix('US.') for c in r['offered_front']) or '—',
              ', '.join(c.removeprefix('US.') for c in r['actual_new']) or '—')
             for d in ('2025-09-08', '2025-09-09', '2025-09-17', '2025-09-26', '2025-10-01')
             for n in ('registered_master', 'H1A', 'H1B') for r in [read(OUT/'crowding_2025.json')[n][d]]]), '',
        '## 工程验收与本轮边界', '',
        '共享引擎的熟悉名单、因果段次数、成组风险和权益状态均默认关闭。登记master、M1B、M2A、M3B完整原台账与权益逐值相等；'
        '登记及看板、旧报告、段表、台账和已存数据的原指纹未变。策略运行期间有读文件白名单，禁止读取本人台账、段标签、T1评测组和本轮评测结果；'
        '逐文件实读记录在strategy_reads.json及prefix.json。', '',
        '真实行情截断到2025-06-30，以及只改变之后OHLC×3、量×2、额×6，均重新计算H1的滚动相关、熟悉名单、关注度与因果段。'
        '比较前缀报价/分组/全部新特征、真实逐笔执行和权益；没有用裁过的结果替代重建输入。'
        '原master输入复用M1已独立重建的cut/perturbed准备集。', '',
        '所有计算与三组测试使用指定.venv、CPUQuota=60%、MemoryMax=900M和单线程。按日期读取mmap，相关只在当晚流动性池计算中心向量，未构造全市场N×N矩阵。'
        '密钥安装器拒绝覆盖已有hooksPath；现有pre-commit/pre-push均调用secret_guard.py，没有绕过或git提交。', '',
        '基线完整连续账的2026年结果另列，年度交易结果含2025带入仓；它不能与本人截至7月+869%直接当作同期限成绩。', '',
        table(['原系统（既有连续账）', '2026至10-16收益', '相对本人至7月869%的算术比例（期限不同）', '本系统2026至7月底收益', '至7月同期比例', '早买/任意/分母'],
            [(NAMES[n], pct(r['checks']['return']['ours']), pct(r['return_ratio']),
              pct(july_return(OUT/'baseline/continuous'/n)), pct(july_return(OUT/'baseline/continuous'/n)/8.69),
              f'{r["early"]}/{r["any"]}/{r["leg_count"]}')
             for n, card in read(OUT/'baseline_scorecards.json')['continuous'].items() for r in [card['years']['2026']]]), '',
        '候选验证计数为单开0、连续0。未采用任何消融结果反向调参数，未联网、未拉新数据、未接交易接口。'
        '下一轮先核全体股票的“新一轮结构如何重新给三次机会”，以及85分位门槛为何把PL/AMPX排掉；保留成组机制的整体对照，'
        '同时拆清H-e的35%仓位与权益降风险各自的2025代价，再预登记。规则需对全体股票一致，不能给量子、PL或AMPX加例外。本轮不追加搜索。', '',
        '可复核入口：`h1_research`的freeze、baseline、register、compatibility、candidates、ablate；'
        '`h1_report`的prefix、diagnose、audit、rescore、tests、render、complete。'
        '所有正式阶段都有独占开始文件，拒绝悄悄重测。报告渲染只读取已存账户。']
    if (OUT/'completion.json').exists():
        done = read(OUT/'completion.json')
        lines += ['', table(['测试组', '测试数', '结果', '日志'],
            [(g, t['tests'], 'OK'+(f'（预期失败{t["expected_failures"]}）' if t['expected_failures'] else ''),
              f'[日志](h1_work/test_{g}.log)') for g, t in done['tests'].items()]), '',
            f'逐笔价格/费用/FIFO核对{done["execution_events"]}条实际执行；实读RSS峰值{done["observed_peak_rss_mib"]:.1f}MiB。'
            '完整验收、预登记与实现指纹、资源实读和工件清单见[completion.json](h1_work/completion.json)。']
    (HOME/'reports/H1_CN.md').write_text('\n'.join(lines)+'\n')


def july_return(folder):
    c = read(folder/'curve.json')
    prior = [v for d, v in zip(c['days'], c['equity']) if d <= '2025-12-31'][-1]
    july = [v for d, v in zip(c['days'], c['equity']) if d <= '2026-07-31'][-1]
    return july/prior-1


def export_cards():
    rows = []
    for n, p in folders().items():
        for year, r in read(p/'scorecard.json')['years'].items():
            row = dict(system=n, year=year, score=r['score'], scored_items=r['scored_items'])
            for k, c in r['checks'].items():
                row.update({k+'_'+field: c[field] for field in ('his', 'ours', 'relative_gap', 'within20', 'scored')})
            rows.append(row)
    with (OUT/'scorecards_all.csv').open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def complete():
    X.once('complete')
    X.registry_check()
    tests = {g: read(OUT/f'test_{g}_resources.json') for g in ('custody', 'trader_replication', 'martin_luk')}
    assert all(r['ok'] for r in tests.values()), tests
    audit_ = read(OUT/'audit.json')
    assert audit_['ok'] and read(OUT/'compatibility.json')['ok'] and read(OUT/'prefix.json')['ok']
    protected = read(OUT/'protocol.json')['protected']
    assert all(sha(ROOT/p) == h for p, h in protected.items()), 'protected input changed after tests'
    bitwise = {}
    for n in X.BASELINES:
        bitwise[n] = {}
        for field in ('trades', 'curve'):
            values = [read(OUT/base/n/(field+'.json')) for base in ('baseline/continuous', 'compatibility')]
            canonical = [json.dumps(v, sort_keys=True, separators=(',', ':'), allow_nan=False) for v in values]
            assert canonical[0] == canonical[1], (n, field)
            bitwise[n][field] = dict(exact=True, canonical_sha256=X.hashlib.sha256(canonical[0].encode()).hexdigest())
    write('bitwise_compatibility.json', bitwise)
    export_cards()
    source = [HOME/'h1_research.py', HOME/'h1_policy.py', HOME/'h1_report.py', HOME/'tests/test_h1.py',
              HOME/'tests/test_h1_scorecard.py', Path(X.Y.__file__)]
    (OUT/'engine_diff.patch').write_text(''.join(difflib.unified_diff(
        (OUT/'original_system.py.txt').read_text().splitlines(True), Path(X.Y.__file__).read_text().splitlines(True),
        fromfile='before_h1/system.py', tofile='after_h1/system.py')))
    observations = {n: read(OUT/(n+'.json'))['resources'] for n in ('baseline_complete', 'compatibility',
        'candidates_complete', 'ablation_complete', 'prefix', 'audit', 'diagnose_complete')}
    observations.update({'test_'+g: t['after'] for g, t in tests.items()})
    observations['evaluation_correction'] = read(OUT/'source_compatibility.json')['resources']
    done = dict(ok=True, research_completed=True, strategy_success=False,
        selected=read(OUT/'selection.json')['chosen'], diagnostic_base=read(OUT/'selection.json')['diagnostic_first'],
        dataset='trader-data-v1', data_digest=read(X.PREP/'master_prepared.json')['digest'],
        candidate_accounts=2, ablation_accounts=6, validation=read(OUT/'validation_complete.json'),
        tests=tests, execution_events=audit_['execution_events'], protected_unchanged=audit_['protected_unchanged'],
        prereg_sha256=sha(X.PREREG), preregistration_unchanged=True,
        implementation=read(OUT/'candidates.json'), resource_observation=X.resources(),
        current_source_sha256={str(p.relative_to(ROOT)): sha(p) for p in source},
        evaluation_correction=read(OUT/'source_compatibility.json'), stage_resources=observations,
        observed_peak_rss_mib=max(r['peak_rss_mib'] for r in observations.values()),
        no_network=True, no_new_data=True, no_git_commit=True, registration_and_board_unchanged=True,
        scoring_policy='five observed behavior metrics; public composition and leg purity descriptive; no fabricated holding target')
    write('completion.json', done)
    render()
    write('artifact_manifest.json', {str(p.relative_to(OUT)): sha(p) for p in sorted(OUT.rglob('*'))
          if p.is_file() and p.name not in ('artifact_manifest.json', 'complete.log')})
    summary = ['H1A: '+str({y: pct(r['checks']['return']['ours']) for y, r in read(OUT/'candidates/H1A/scorecard.json')['years'].items()}),
        'H1B: '+str({y: pct(r['checks']['return']['ours']) for y, r in read(OUT/'candidates/H1B/scorecard.json')['years'].items()}),
        '均未过每年不亏底线；六项消融已完成，2026评测0+0。',
        '四个原系统逐笔不变；截断/未来扰动1778条执行及权益前缀一致。',
        '测试: '+', '.join(f'{g} {r["tests"]} OK' for g, r in tests.items()),
        '报告: studies/martin_luk/reports/H1_CN.md',
        '下一轮: 先核三次机会的因果重置、关注度门槛和H-e的2025代价，不给个股加例外。']
    print('\n'.join(summary))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('stage', choices=('prefix', 'diagnose', 'audit', 'rescore', 'tests', 'render', 'complete'))
    p.add_argument('--group', choices=('custody', 'trader_replication', 'martin_luk'))
    args = p.parse_args()
    if args.stage == 'tests':
        test_group(args.group)
    X.offline()
    dict(prefix=engineering_prefix, diagnose=diagnose, audit=audit, rescore=rescore, render=render, complete=complete)[args.stage]()


if __name__ == '__main__':
    main()
