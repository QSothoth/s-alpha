"""Render the state and profile evidence attached to a version ledger."""
from __future__ import annotations

import math

YEARS = ('2024', '2025', '2026')
STATES = ('up', 'weak', 'pullback')
STATE_CN = {'up': '上升', 'weak': '弱', 'pullback': '回调'}


def pct(value, signed=False):
    return '—' if value is None else format(value, '+.1%' if signed else '.1%')


def number(value, digits=2):
    return '—' if value is None else f'{value:.{digits}f}'


def yr(year):
    return year + (' 留出*' if year == '2026' else '')


def counts(values):
    return '、'.join(f'{k} {v}' for k, v in values.items()) or '无'


def fit(value, target, tolerance):
    if value is None or target is None:
        return '无法判定'
    if target == 0:
        return '无法判定（目标为零，相对差未定义）'
    return '在范围' if abs(value/target-1) <= tolerance + 1e-12 else '不在范围'


def target_counts(group):
    item = group['side']
    return {key: part['count'] for key, part in (item['value'] or {}).items()}


def side_fit(row, tolerance):
    n, total = row['trader_sample_n'], row['entries']
    if not n or not total:
        return '无法判定'
    parts = row['trader_side']
    targets = {key: parts.get(key, {}).get('fraction', 0.) for key in ('long', 'short')}
    if not all(targets.values()):
        return '无法判定（本人某方向占比为零）'
    ok = all(abs(row['side'][key]/total/targets[key]-1) <= tolerance + 1e-12 for key in targets)
    return '画像范围内' if ok else '画像范围外'


def details(entries, evidence, config, draft):
    versions = [r for r in entries if r['version'].startswith('v') and r['version'][1:].isdigit()]
    rows = {r['version']: r for r in versions}
    profile = config['capital']['acceptance_profile']
    tol = config['hard_lines']['behaviour_tolerance']
    lines = ['', '## 执行开关', '',
             'B4_PCT2 经用户按证据弱、按原话可用接受并冻结，在这里仅作为所有版本共用的拆账日历；量和执行分开。', '',
             '| 版本 | 开关 |', '|---|---|']
    for entry in versions:
        v = entry['version']
        lines.append(f"| {v} | {evidence['switches'].get(v, '未提供')} |")
    lines += ['', '## 共用日历下的行为、峰前持有与账户', '',
        '本人只统计来源可归态的公开台账，非完整交易；日期窗口跨状态的记录不强行归类，'
        '已确认画像的样本证据弱。多头差距为系统多头占比减本人样本多头占比（百分点）；'
        '系统触发类型与本人买点形态没有经验证的等价关系。本人票档分位、分状态持有天数在限定来源中缺失。', '',
        '状态收益把该状态的实际日收益依时间顺序相乘；状态最大回撤取这条跳过其他状态日的合成收益序列，'
        '并非账户全年回撤，也不是连续行情段回撤。峰前持有按段的首锚点日归态，包括晚买。', '',
        '| 年份 | 状态 | 本人台账样本 | 版本 | 该状态的交易与行为差距 | 峰前持有/段 | 状态收益 | 状态最大回撤 |',
        '|---|---|---|---|---|---:|---:|---:|']
    for year in YEARS:
        for state in STATES:
            target = config['behaviour_card']['by_state'][year][state]
            side = target_counts(target)
            shapes = {k: p['count'] for k, p in (target['setup']['value'] or {}).items()}
            person = (f"n={target['side']['sample_n']}；多 {side.get('long', 0)} / 空 {side.get('short', 0)}；"
                      f"形态 {counts(shapes)}；证据弱") if side else '未观测，证据弱'
            for entry in versions:
                v = entry['version']
                year_states = evidence['by_state'].get(v, {}).get(year, {})
                row = year_states.get(state)
                if row is None:
                    lines.append(f'| {yr(year)} | {STATE_CN[state]} | {person} | {v} | 未提供 | — | — | — |')
                    continue
                sides = row['side']
                gap = '—' if row['long_share_gap_pp'] is None else f"{row['long_share_gap_pp']:+.1f} 个百分点"
                behavior = (f"{row['entries']} 笔，多 {sides['long']} / 空 {sides['short']}；多头差 {gap}；"
                            f"{side_fit(row, tol)}；触发 {counts(row['kind'])}；"
                            f"均持 {number(row['days'], 1)} 天（平仓 {row['closed']} 笔）")
                held = f"{row['peak_held']}/{row['segments']}" if row['segments'] else '未观测'
                lines.append(f"| {yr(year)} | {STATE_CN[state]} | {person} | {v} | {behavior} | "
                             f"{held} | {pct(row['return'], True)} | {pct(row['max_drawdown'])} |")
    lines += ['', '## 执行开关对照（L2.8）', '',
        'v0：不适用，无执行开关。v1：只将原规则的 `risk_scale=e8_scale` 关闭，其余规则、点名和资金档不变；'
        '差值均为“关闭减开启”。不以此改变版本或判定接受。', '',
        '| 年份 | 收益：开启 → 关闭（差） | 全年最大回撤：开启 → 关闭（差） | '
        '胜率、盈亏比、笔数、持有变化 | 峰前持有变化 | 最高杠杆变化 |',
        '|---|---|---|---|---|---|']
    switch = evidence['switch_comparison']['v1']
    for year in YEARS:
        row = switch[year]
        on, off, delta = row['annual_on'], row['annual_off'], row['annual_delta_off_minus_on']
        lines.append(f"| {yr(year)} | {pct(on['return'], True)} → {pct(off['return'], True)} "
            f"（{delta['return']*100:+.2f} 个百分点） | {pct(row['annual_max_drawdown_on'])} → "
            f"{pct(row['annual_max_drawdown_off'])}（{row['annual_max_drawdown_delta']*100:+.2f} 个百分点） | "
            f"胜率 {delta['win']*100:+.2f} 个百分点；盈亏比 {delta['payoff']:+.3f}；"
            f"{delta['trades']:+d} 笔；持有 {delta['days']:+.2f} 天 | {delta['peak_held']:+d} 段 | "
            f"{delta['max_gross']:+.2f} 倍 |")
    lines += ['', '按 B4 拆分的差值同样是关闭减开启；回撤差值按有符号回撤计算，正值表示合成序列回撤变浅。', '',
              '| 年份 | 状态 | 收益差 | 最大回撤差 | 峰前持有差 | 开仓笔数差 | 多头占比差 |',
              '|---|---|---:|---:|---:|---:|---:|']
    for year in YEARS:
        for state in STATES:
            d = switch[year]['by_state'][state]
            if d['return'] is None:
                continue
            long_gap = '—' if d['long_share_gap_pp'] is None else f"{d['long_share_gap_pp']:+.1f} 个百分点"
            lines.append(f"| {yr(year)} | {STATE_CN[state]} | {d['return']*100:+.2f} 个百分点 | "
                         f"{d['max_drawdown']*100:+.2f} 个百分点 | {d['peak_held']:+d} | {d['entries']:+d} | {long_gap} |")
    lines += ['', '## 档案逐项对齐', '',
        '“在范围/不在范围”只表示可量化项目相对现有配置或证据弱画像的算术对照；'
        '公开台账不完整，不能由此宣称交易行为已复刻。行为容差按配置 ±20%，'
        '本人样本某方向占比为零时相对差未定义，不擅定零值规则。', '',
        '| 档案项 | 依据 | v0 | v1 |', '|---|---|---|---|']
    def add(name, basis, v0, v1):
        lines.append('| ' + ' | '.join(str(x).replace('|', r'\|') for x in (name, basis, v0, v1)) + ' |')
    goals = config.get('goal', [])
    goal_results = [
        ('不在范围：2025收益及行为未达目标', '不在范围：2024/2025收益及行为未达目标'),
        ('无法判定：未指定可接受的本人票资金占比', '无法判定：未指定可接受的本人票资金占比'),
        ('无法判定：原话未指定撒网量化边界', '无法判定：原话未指定撒网量化边界'),
        ('无法判定：已有峰前持有数，目标覆盖率未指定', '无法判定：已有峰前持有数，目标覆盖率未指定'),
        ('不适用：允许项，不是必须使用', '不适用：允许项，不是必须使用'),
        ('无法判定：B4仅用于拆账', '无法判定：B4仅用于拆账'),
        ('不适用：基线，不是新一轮分线候选', '不适用：底座，不是新一轮分线候选'),
        ('不适用：v0 无执行开关', '待后续候选验证：保留 C062 原有执行开关'),
    ]
    for i, goal in enumerate(goals):
        value = goal.get('quote', str(goal)) if isinstance(goal, dict) else str(goal)
        a, b = goal_results[i] if i < len(goal_results) else ('无法判定', '无法判定')
        add(f'目标 {i+1}', value.replace('|', '／'), a, b)

    def hard_result(entry, field, op):
        annual = entry['scorecard'][profile]
        pieces = []
        for y in YEARS:
            value = annual[y].get(field)
            pieces.append(f"{yr(y)} {'在范围' if value is not None and op(value) else '不在范围' if value is not None else '无法判定'}")
        return '；'.join(pieces)

    hard = config['hard_lines']
    for label, field, threshold, op in (
        ('每年收益', 'return', f"不低于 {pct(hard['annual_return_min'])}", lambda x: x >= hard['annual_return_min']),
        ('胜率上限', 'win', f"不高于 {pct(hard['max_win'])}", lambda x: x <= hard['max_win']),
        ('已平仓笔数', 'closed', f"至少 {hard['min_closed']} 笔", lambda x: x >= hard['min_closed']),
        ('每年开仓数', 'trades', f"至少 {hard['min_entries_per_year']} 笔", lambda x: x >= hard['min_entries_per_year'])):
        add('底线：'+label, threshold, hard_result(rows['v0'], field, op), hard_result(rows['v1'], field, op))
    add('底线：行为容差', f"±{tol:.0%}；逐项见下方", '参见行为各项', '参见行为各项')
    add('底线：收益差距', f"|log((1+版本)/(1+本人))| ≤ {hard['max_log_return_gap']}",
        *[return_fit(rows[v], config, profile) for v in ('v0', 'v1')])
    add('各线接受条件', '对候选与比较对象判定', '不适用：底线参照', '不适用：起始底座')
    add('检查点', '触发即停止当前轮', '不适用：版本本身不是一轮', '不适用：版本本身不是一轮')
    add('数据白名单与 schema', '既有核对结果', '在范围：既有数据集核对通过', '在范围：既有数据集核对通过')
    add('底线 v0', f"配置为 {config['bar']}", '在范围：使用底线', '不适用：这是底座')
    base = config['base']
    add('底座 v1', f"{base['selection']} / {base['trading']} / {base['conversion']}",
        '不适用：这是底线', '在范围：组件与底座一致')
    add('资金、档位、追保', f'均为 {profile}，默认先减最弱',
        '在范围：原生回放规则及维持线已核对', '在范围：原生回放规则及维持线已核对')
    add('行情、原话和状态上限', 'B4 经用户接受，证据弱，按原话可用',
        '无法判定：不执行分状态修正', '无法判定：原有执行开关使用自身日历，不使用 B4')
    for field, key, title in (('win', 'win', '胜率'), ('payoff', 'payoff', '盈亏比'), ('n', 'trades', '笔数')):
        formatted = []
        for v in ('v0', 'v1'):
            pieces = []
            for y in ('2024', '2025'):
                val = rows[v]['scorecard'][profile][y][key]
                target = config['behaviour_card'][y].get(field)
                pieces.append(f'{y} {fit(val, target, tol)}（{number(val, 3)}/{number(target, 3)}）')
            pieces.append('2026 留出*无法判定：无同口径出处')
            formatted.append('；'.join(pieces))
        add('行为：'+title, f'本人年度数据，容差 ±{tol:.0%}', *formatted)
    hold = []
    for v in ('v0', 'v1'):
        val = rows[v]['scorecard'][profile]['2024']['days']
        group = evidence['holding_2025_by_outcome'][v]
        win, loss = group['win'], group['loss']
        hold.append(f"2024 仅说明（{number(val, 1)}/5天，原文样本数未知）；"
                    f"2025 仅说明：赢家 {number(win['days'], 1)}/约3天（n={win['n']}），"
                    f"输家 {number(loss['days'], 1)}/约1天（n={loss['n']}）；天数口径待核；2026无出处")
    add('行为：持有天数', '证据弱，只作说明，不计行为达标；2024平均约5天，2025为赢/亏分组', *hold)
    add('行为：收益', '2024、2025用同口径公开年收益',
        *[return_fit(rows[v], config, profile) for v in ('v0', 'v1')])
    def side_summary(v):
        out = []
        for y in YEARS:
            for state in ('up', 'weak'):
                row = evidence['by_state'].get(v, {}).get(y, {}).get(state)
                out.append(f"{yr(y)} {STATE_CN[state]}{side_fit(row, tol) if row else '无法判定'}")
        return '；'.join(out)
    add('行为：多空比例', f'分状态公开台账样本，证据弱，容差 ±{tol:.0%}；见分状态表',
        side_summary('v0'), side_summary('v1'))
    add('行为：买点形态', '本人 setup 与系统触发类型未建立可验证映射', '无法判定', '无法判定')
    add('行为：成交额分位', '限定来源没有本人逐笔横截面分位', '无法判定', '无法判定')
    add('行为：ADR 分位', '限定来源没有本人逐笔横截面分位', '无法判定', '无法判定')
    add('选择年', '2024、2025', '在范围：基线如实分年报告', '在范围：底座如实分年报告')
    add('留出年', '2026 留出*；已反复查看，不作独立样本外', '在范围：仅报告', '在范围：仅报告')
    add('冻结段表', '按已登记 SHA 的段表计算峰前持有', '在范围：原生回放核对', '在范围：原生回放核对')
    lines += ['', '分状态详情、原始账户指纹、开关关闭回放及重判依据分别见 '
             '[分状态数据](rounds/WF00/version_state_profile.json)、'
             '[已确认档案](PROFILE_CN.md)、[画像来源草稿](rounds/WF00/profile_draft.json) 和 '
             '[行情重判](rounds/WF00/regime_rejudge.json)。', '']
    return lines


def return_fit(entry, config, profile):
    result = []
    threshold = config['hard_lines']['max_log_return_gap']
    for year in ('2024', '2025'):
        value = entry['scorecard'][profile][year]['return']
        target = config['behaviour_card'][year]['return']
        gap = abs(math.log((1+value)/(1+target))) if value > -1 and target > -1 else None
        verdict = '在范围' if gap is not None and gap <= threshold else '不在范围'
        result.append(f'{year} {verdict}（差 {number(gap)}）')
    result.append('2026 留出*无法判定：本人截至7月，账户截至10月')
    return '；'.join(result)
