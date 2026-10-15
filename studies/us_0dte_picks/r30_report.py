"""Paired R30 diagnostics; never changes candidates, gates or source data."""
from collections import Counter, defaultdict
import csv
import hashlib
import json
from pathlib import Path
import random

from custody.dataset import Dataset
from custody.evaluate import _plain, case_value, composite_score, simulate, summarize
from custody.strategy import session_minute
from .baselines import ROOT, details
from .position_confirmation import PositionConfirmation
from .r27 import write_json
from .r30 import BASES, POLICIES

OUT = ROOT / 'studies/us_0dte_picks/reports/R30'


def expectancy(rows):
    return summarize(rows, rows)['balanced']['expectancy']


def paired_intervals(base, candidate):
    days = defaultdict(list)
    for i, row in enumerate(base):
        days[row['trade_date']].append(i)
    names = sorted(days)
    rng = random.Random(20261014)
    values = []
    invalid = 0
    for _ in range(1000):
        indices = [i for _ in names for i in days[rng.choice(names)]]
        a = expectancy([base[i] for i in indices])
        b = expectancy([candidate[i] for i in indices])
        if a is None or b is None:
            invalid += 1
        else:
            values.append(b - a)
    values.sort()
    return {'draws': 1000, 'invalid_draws': invalid,
            'interval_95': [values[int(q * (len(values) - 1))] for q in (.025, .975)] if values else [None, None]}


def daily_tracks(rows):
    tracks = {}
    for side, direction in (('CALL', 'LONG'), ('PUT', 'SHORT')):
        selected = {}
        for row in sorted(rows, key=lambda r: (r['trade_date'], r['symbol'], r['contract'])):
            if row['direction'] == direction:
                selected.setdefault(row['trade_date'], row)
        trades = list(selected.values())
        tracks[side] = {'days': len(trades), 'completed': sum(t['outcome'] == 'COMPLETED' for t in trades),
            'raw_mean_return': sum(case_value(t) for t in trades) / len(trades),
            'one_contract_net_pnl_usd': sum(t['net_pnl'] or 0 for t in trades),
            'plans': [{k: t[k] for k in ('trade_date', 'symbol', 'contract', 'outcome', 'net_return', 'net_pnl')} for t in trades]}
    return tracks



def leave_one_day_diagnostics(reports):
    """Training-only simplified selection; no claim of nested full-gate validation."""
    days = sorted({t['trade_date'] for t in reports['selective']['base']['cases']})
    held = {m: [] for m in BASES}
    folds = []
    for day in days:
        training = {m: {p: [t for t in r['cases'] if t['trade_date'] != day] for p, r in group.items()}
                    for m, group in reports.items()}
        def passes(mode, policy):
            new, old = training[mode][policy], training[mode]['base']
            a, b = summarize(new, new), summarize(old, old)
            if not (a['balanced']['expectancy'] > 0 and (a['balanced']['profit_factor'] or 0) > 1 and
                    a['completed'] >= b['completed']):
                return False
            for hit in (.5, .6):
                if composite_score(summarize(new, new, hit))['score'] < composite_score(summarize(old, old, hit))['score']:
                    return False
            for direction in ('LONG', 'SHORT'):
                x = expectancy([t for t in new if t['direction'] == direction])
                y = expectancy([t for t in old if t['direction'] == direction])
                if x is None or y is None or x <= 0 or x < y:
                    return False
            return True
        eligible = [p for p in POLICIES if all(passes(m, p) for m in BASES)]
        chosen = max(eligible, key=lambda p: min(expectancy(training[m][p]) - expectancy(training[m]['base'])
                                                for m in BASES)) if eligible else 'base'
        folds.append({'held_day': day, 'chosen': chosen})
        for mode in BASES:
            held[mode].extend(t for t in reports[mode][chosen]['cases'] if t['trade_date'] == day)
    return {'folds': folds, 'choices': dict(Counter(f['chosen'] for f in folds)),
            'held_days': {m: details(rs) for m, rs in held.items()},
            'limitation': '仅训练段收益、分侧和分数筛选，不是嵌套官方全门槛；反复使用开发集，不能当独立样本外。'}


def markdown(result):
    pct = lambda x: '—' if x is None else '%.2f%%' % (x * 100)
    stats = result['stats']
    lines = ['# R30：组合信号用于持有与卖出的双 mode 结果', '',
        '研究日期：2026-10-14。只使用已反复研究的真实 0DTE 开发集：2026-08-18 至 09-16，21 个交易日、146 个 case（73 CALL / 73 PUT）。', '',
        '**没有通过联合晋级门槛，不注册 V6.7。**' if result['winner'] is None else '**开发候选：%s；仍需另行预登记独立验证。**' % result['winner'], '',
        '这是历史真实期权成交模型回放，不是券商实际成交或实盘业绩。主口径沿用官方方向情景平衡权重；全部 case 保留，未买入贡献 0。下一根可成交期权分钟线成交，原滑点及每边每张 0.65 美元费用不变，不能保证真实挂单一定成交。', '',
        '## 基线及完整交易', '',
        '统一版本为 V6.6；selective 映射原 zero_dte_timing_v6.6，required 映射原 open_hold_v3。H = 同向组合暂缓止盈/无进展退出；X = 反向组合提前退出；HX = 两者结合。三者入场全部与各自基线逐笔相同。', '',
        '| mode | 方案 | 完整买卖 / 146 | 净均值 | CALL 净均值 | PUT 净均值 | 盈亏比 | 利润因子 | 综合分 50% / 60% | 最差一笔 |',
        '|---|---|---:|---:|---:|---:|---:|---:|---:|---:|']
    for mode in BASES:
        for p in ('base', *POLICIES):
            s = stats[mode][p]; o = s['overall']; b = o['balanced']
            lines.append('| %s | %s | %s | %s | %s | %s | %.2f | %.2f | %.2f / %.2f | %s |' %
                (mode, 'V6.6 基线' if p == 'base' else p, o['completed'], pct(b['expectancy']),
                 pct(s['sides']['CALL']['balanced']['expectancy']), pct(s['sides']['PUT']['balanced']['expectancy']),
                 b['payoff_ratio'], b['profit_factor'], o['score'], s['score_60'], pct(o['worst_return'])))
    lines += ['', 'CALL/PUT 各自重新按情景平衡，不等于两侧算术平均能还原总值；每侧均保留 73 个 case。净均值不是账户收益率。', '',
        '九版旧策略完整基线见 [R29](R29_BASELINES_CN.md)。其中历史 required v2 同样完成 146/146，净均值 -2.13%、综合分 69.41；它是额外旧策略对照。超过当前 required v3 的 -6.27% 并不自动代表优于所有历史配置。', '',
        '## 择时与组合动作', '',
        '组合只使用两个已完成的 3 分钟块；当前分钟条件失效或缺分钟时不会延续无效确认。普通入场保留，required 第 60 分钟的兜底不等待强信号；不加仓、反手或做第二笔。', '',
        '| mode | 方案 | 提前 / 推迟 / 同时 / 未交易 | 持有分钟中位数 | 改善 / 恶化笔数 | 净均值差 | 按日配对 95% 区间 |',
        '|---|---|---|---:|---|---:|---|']
    for mode in BASES:
        for p in POLICIES:
            s = stats[mode][p]; t = s['timing']; d = s['combo_diagnostics']
            lines.append('| %s | %s | %s | %s | %s / %s | %s | [%s, %s] |' %
                (mode, p, ' / '.join(str(t.get(k, 0)) for k in ('earlier', 'later', 'same', 'no_exit')),
                 s['overall']['hold_minutes_median'], d['improved_trade_count'], d['worse_trade_count'],
                 pct(s['delta_expectancy']), *map(pct, s['bootstrap']['interval_95'])))
    lines += ['', '差值和区间以百分点理解；1,000 次按交易日配对重抽样，seed=20261014。区间含 0 表示不能可靠区分改善与波动。事件诊断及分侧指标来自官方报告的 6 位小数逐笔数据；正式评级、压力成本和分数用官方评测，不改口径。', '',
        '强 B/S 是方向证据，不是无条件期权买卖命令。CALL 持仓遇强 B 属同向，PUT 持仓遇强 S 属同向。这里评价其持有/退出用途，不以信号后固定 30 根正股涨幅代替期权净损益。', '',
        '## 每天一个计划的交易诊断', '',
        '每个交易日先按标的/合约名排序取首个标的，分别固定 CALL、固定 PUT 两条备选路径；不看当天收益选标的，不把两侧合并成一天两笔。每条路径 21 日，selective 允许空仓，required 要完成一买一卖。每次一张，资金未约束，因此金额只是逐笔盈亏之和，不是可执行账户净值。', '',
        '| mode | 方案 | CALL 完成日 / 21 | CALL 日均净收益 | CALL 一张累计盈亏 | PUT 完成日 / 21 | PUT 日均净收益 | PUT 一张累计盈亏 |',
        '|---|---|---:|---:|---:|---:|---:|---:|']
    for mode in BASES:
        for p in ('base', *POLICIES):
            tracks = stats[mode][p]['daily_tracks']; a, b = tracks['CALL'], tracks['PUT']
            lines.append('| %s | %s | %s | %s | $%.2f | %s | %s | $%.2f |' %
                (mode, p, a['completed'], pct(a['raw_mean_return']), a['one_contract_net_pnl_usd'],
                 b['completed'], pct(b['raw_mean_return']), b['one_contract_net_pnl_usd']))
    lines += ['', '这两条路径只检验固定上游计划下的买卖效果，不证明有选方向能力。当前运行时仍是每合约每天一笔、会话层原名额；本轮没有实现跨合约/跨数据库的账户级一天一笔保证，也没有启动交易。', '',
        '## 晋级检查与优化边界', '']
    for p, q in result['qualification'].items():
        for mode, checks in q['checks'].items():
            failed = [k for k, ok in checks.items() if not ok]
            lines.append('- %s / %s：未通过 %s；原正式评级 %s。' % (p, mode, '、'.join(failed) or '无', stats[mode][p]['verdict']))
    lines += ['', '联合门槛要求两个 mode 均盈利、两侧均盈利且不劣化、完整交易覆盖、两种方向命中假设的综合分不退步、配对区间下限为正、成本压力和最差一笔不退步，并保留 selective 原正式门槛。required 原评级按旧标准显示，不能以 PROVISIONAL 冒充联合晋级。', '',
        '买入不变使收益差可以归因于卖出规则；它也意味着本轮没有优化 required 的兜底入场。真实期权价格已包含时间价值变化，不再虚扣一个 theta。逐笔表同时列出正股卖点变化和期权净收益变化，两者不一致也保留。', '',
        '留一天简化选择：%s。各折只用其余日期的收益、分侧和分数选方案，未做嵌套完整门槛；仅为开发集内部诊断，不能当新样本外。' % result['leave_one_day']['choices'], '',
        '## 文件与复现', '',
        '- [冻结预登记](../notes/R30_PREREG.md)',
        '- [完整机器结果及门槛](R30/analysis.json)',
        '- [876 行逐笔配对 CSV](R30/paired_trades.csv)：包括没有交易、没有组合及亏损 case。',
        '- R30 下每个 mode/方案目录含官方 REPORT.md、report.json；保存 CLI 命令、冻结参数、源码哈希。两个统一版本基线除新增 release 显示字段外，完整旧报告一致；876 个候选主交易复放一致。', '',
        '```bash', 'python3 -m studies.us_0dte_picks.r30 --out <新的空输出目录>',
        'python3 -m studies.us_0dte_picks.r30_report', '```', '',
        '第二条从固定 reports/R30 读取本轮结果。不要覆盖已冻结结果或把本开发段另命名为验证段。']
    return '\n'.join(lines) + '\n'

def main():
    assert (OUT / 'run_complete.json').exists()
    reports = {mode: {p: json.loads((OUT / (mode + '_' + p) / 'report.json').read_text())
                      for p in ('base', *POLICIES)} for mode in BASES}
    stats, rows = {}, []
    for mode, group in reports.items():
        stats[mode] = {}
        for policy, report in group.items():
            cases = report['cases']
            stats[mode][policy] = {'overall': details(cases), 'sides': {
                side: details([t for t in cases if t['direction'] == direction])
                for side, direction in (('CALL', 'LONG'), ('PUT', 'SHORT'))},
                'daily_tracks': daily_tracks(cases), 'verdict': report['verdict'],
                'score_60': report['score']['strategy_hit_0.6']['score'],
                'failed_gates': [k for k, v in report['gates_in_sample'].items() if v is False]}
        base = group['base']['cases']
        for policy in POLICIES:
            candidate = group[policy]['cases']
            assert [(t['contract'], t['trade_date']) for t in base] == [(t['contract'], t['trade_date']) for t in candidate]
            timing = Counter()
            for old, new in zip(base, candidate):
                assert old['entry'] == new['entry'] and old['entry_signal'] == new['entry_signal']
                before, after = old['exit'], new['exit']
                shift = None if before is None or after is None else after['minute'] - before['minute']
                category = 'no_exit' if shift is None else 'earlier' if shift < 0 else 'later' if shift > 0 else 'same'
                timing[category] += 1
                row = {k: old[k] for k in ('symbol', 'contract', 'trade_date', 'direction')}
                row.update(mode=mode, policy=policy, exit_timing=category, exit_shift_minutes=shift,
                           delta_net_return=case_value(new) - case_value(old))
                for label, t in (('base', old), ('new', new)):
                    row.update({label + '_' + k: t[k] for k in ('outcome', 'net_return', 'net_pnl', 'hold_minutes')})
                    for leg in ('entry', 'exit'):
                        for field in ('minute', 'fill_minute', 'reason', 'price'):
                            row[label + '_' + leg + '_' + field] = t[leg][field] if t[leg] else None
                rows.append(row)
            stat = stats[mode][policy]
            stat.update(timing=dict(timing), entries_identical=True, bootstrap=paired_intervals(base, candidate))
            stat['delta_expectancy'] = stat['overall']['balanced']['expectancy'] - stats[mode]['base']['overall']['balanced']['expectancy']
            stat['stress_delta'] = {k: v['strategy']['expectancy'] - group['base']['stress'][k]['strategy']['expectancy']
                                    for k, v in group[policy]['stress'].items()}

    # Real tapes only; stream one case, replay the exact frozen primary path.
    dataset = Dataset(ROOT / 'data/custody-0dte-v6.1')
    by_case = defaultdict(list)
    official = {}
    configs = {}
    for mode in BASES:
        for policy in POLICIES:
            configs[mode, policy] = json.loads((OUT / (mode + '_' + policy + '_config.json')).read_text())['params']
            for trade in reports[mode][policy]['cases']:
                official[mode, policy, trade['contract'], trade['trade_date']] = trade
    for row in rows:
        by_case[row['contract'], row['trade_date']].append(row)
    for case in dataset.cases:
        data = dataset.load(case)
        prices = {session_minute(data.session, b.close_time): b.close for b in data.underlying}
        for row in by_case[case.key]:
            params = configs[row['mode'], row['policy']]
            engine = PositionConfirmation(params, case.direction, data.session, case.strike)
            original = engine.on_bar
            events = Counter()
            def observe(bar):
                holding = engine.phase == 'IN'
                decision = original(bar)
                if holding and engine.confirmation.direction:
                    events['same' if engine.confirmation.direction == engine.sign else 'opposite'] += 1
                return decision
            engine.on_bar = observe
            replay = _plain(simulate(data, engine, params))
            replay['decisions'] = None
            expected = official[row['mode'], row['policy'], case.contract, case.trade_date]
            assert all(expected[k] == v for k, v in replay.items()), (case.key, row['policy'])
            row['same_combo_holding_minutes'] = events['same']
            row['opposite_combo_holding_minutes'] = events['opposite']
            a, b = row['base_exit_minute'], row['new_exit_minute']
            row['signed_underlying_exit_change'] = engine.sign * (prices[b] / prices[a] - 1) if a and b else None
        dataset._tapes.clear()
    with (OUT / 'paired_trades.csv').open('w') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    qualified = {}
    for policy in POLICIES:
        mode_checks = {}
        for mode in BASES:
            stat, base = stats[mode][policy], stats[mode]['base']
            report = reports[mode][policy]
            value, control = stat['overall'], base['overall']
            ci = stat['bootstrap']
            mode_checks[mode] = {
                'causal_entry_and_completion': report['prefix_consistency']['passed'] and stat['entries_identical'] and
                    value['completed'] >= (146 if mode == 'required' else control['completed']),
                'positive_mean_pf_and_scores': value['balanced']['expectancy'] > 0 and (value['balanced']['profit_factor'] or 0) > 1 and
                    report['score']['strategy']['score'] >= reports[mode]['base']['score']['strategy']['score'] and stat['score_60'] >= base['score_60'],
                'both_sides_positive_and_not_worse': all(stat['sides'][s]['balanced']['expectancy'] > 0 and
                    stat['sides'][s]['balanced']['expectancy'] >= base['sides'][s]['balanced']['expectancy'] and
                    not stat['sides'][s]['coverage_gaps'] for s in ('CALL', 'PUT')),
                'paired_day_interval_positive': ci['invalid_draws'] == 0 and ci['interval_95'][0] is not None and ci['interval_95'][0] > 0,
                'stress_and_worst_trade': all(v >= 0 for v in stat['stress_delta'].values()) and value['worst_return'] >= control['worst_return'],
                'formal_selective_gates': all(v is True for v in report['gates_in_sample'].values()) if mode == 'selective' else True,
            }
            subset = [r for r in rows if r['mode'] == mode and r['policy'] == policy]
            stat['combo_diagnostics'] = {'cases_with_same_combo_while_holding': sum(r['same_combo_holding_minutes'] > 0 for r in subset),
                'cases_with_opposite_combo_while_holding': sum(r['opposite_combo_holding_minutes'] > 0 for r in subset),
                'improved_trade_count': sum(r['delta_net_return'] > 0 for r in subset),
                'worse_trade_count': sum(r['delta_net_return'] < 0 for r in subset),
                'underlying_better_option_worse': sum((r['signed_underlying_exit_change'] or 0) > 0 and r['delta_net_return'] < 0 for r in subset)}
        qualified[policy] = {'checks': mode_checks, 'passed': all(all(v.values()) for v in mode_checks.values())}
    eligible = [p for p in POLICIES if qualified[p]['passed']]
    winner = max(eligible, key=lambda p: min(stats[m][p]['delta_expectancy'] for m in BASES)) if eligible else None
    result = {'dataset_fingerprint': dataset.fingerprint, 'stats': stats, 'qualification': qualified,
                'winner': winner, 'all_primary_replays_identical': True,
                'limitations': ['反复使用开发集，不是独立验证', '历史真实期权回放，不是券商实际成交',
                                '日内路径为事先机械选标的的两条分侧诊断，不是组合账户']}
    result['leave_one_day'] = leave_one_day_diagnostics(reports)
    result['analysis_source_sha256'] = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in (Path(__file__).resolve(), ROOT / 'studies/us_0dte_picks/baselines.py')}
    write_json(OUT / 'analysis.json', result)
    (OUT.parent / 'R30_RESULTS_CN.md').write_text(markdown(result))
    print(json.dumps({'winner': winner, 'qualification': qualified}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
