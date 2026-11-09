"""Render the fixed D1 measurements as a Chinese report; no strategy decisions."""
from __future__ import annotations

from collections import Counter

import numpy as np

from .d1_research import HOME, ROOT, OUT, clean, offline, read, sha, write

NAMES = {'master': '登记 master（R74+S7）', 'master_C062': 'master+C062',
         'IE47_C062': 'IE47+C062', 'master_S1': 'master+S1', 'IE47_S1': 'IE47+S1'}
STAGES = {'early_profitable': '早买且段内赚钱', 'early_lost': '早买但段内亏钱',
          'early_signal_blocked': '合格信号被账户挡住', 'pool_excluded': '合格窗口没进池',
          'market_blocked': '大盘门槛挡住', 'daily_cap': '信号排在每日四名以后',
          'no_setup_or_stop': '形态或止损未通过', 'momentum_watch_excluded': '动量/观察池没通过',
          'pool_not_named': '进池但该段未获有效新点名', 'observation_expired': '该段点名后等突破时五晚已过',
          'persistent_list_removed': '持续名单已因跌破 21 EMA 移除',
          'named_after_early_break': '本段点名已赶不上早期突破',
          'observation_consumed_or_stop': '观察已用掉或止损输入未过', 'no_early_close_break': '早期没有收盘过前高'}
EXITS = {'stop': '盘中止损', 'gap_stop': '跳空止损', 'close_stop': '收盘证伪', 'trail': '跌破跟踪线',
         'end': '期末估值', 'signal': '信号退出', 'make_room': '为底版腾仓', 'stop_day0': '当日止损'}
FEATURES_CN = {'dollar_vol20_M': '20 日成交额（百万美元）', 'adr20_pct': 'ADR（%）',
               'perf21_pct': '1 月涨幅（%）', 'perf63_pct': '3 月涨幅（%）', 'perf126_pct': '6 月涨幅（%）',
               'from_high252_pct': '距一年高点（%）', 'ema_stack': 'EMA 顺序（0–2）',
               'ext_ema9_adr': '离 9 EMA（ADR）', 'ext_ema21_adr': '离 21 EMA（ADR）',
               'ema9_21_gap_adr': '9/21 间距（ADR）', 'rvol20': '当日量比', 'rvol3_20': '三日量比',
               'inside_day': '内包日（0/1）', 'nr7': '七日最窄（0/1）', 'contract3_adr': '三日振幅/ADR',
               'gap_today_adr': '开盘跳空（ADR）', 'close_pos': '收盘在日内位置',
               'perf1_pct': '当日涨幅（%）', 'perf5_pct': '一周涨幅（%）', 'low252_distance_pct': '距一年低点（%）'}
ROUTES_CN = {'bpath': '长期强势 B', 'ep': '放量跳空 EP',
             'family_E11_E11': '跳空后握手', 'family_E10_E4': '贴线后日内跨 9 EMA',
             'family_E10_E2': '贴线后日内越前高', 'family_E2_E2': '内包/窄幅后越前高',
             'family_EW1_E2': '内包周突破'}


def route_text(names):
    return '、'.join(ROUTES_CN.get(n, n) for n in names)


def pct(x, signed=False):
    return '—' if x is None else format(x, '+.1%' if signed else '.1%')


def num(x, digits=3):
    return '—' if x is None else f'{x:+.{digits}f}'


def table(headers, rows):
    return '\n'.join(['| '+' | '.join(headers)+' |', '| '+' | '.join('---' for _ in headers)+' |']+
                     ['| '+' | '.join(str(v).replace('|', '/') for v in row)+' |' for row in rows])


def named(rows):
    return '、'.join(r['leg']+' '+r['code'].removeprefix('US.') for r in rows) or '无'


def evidence(rows):
    return f"{len(rows)} 段，master+C062 段内合计 {num(sum(r['pnl'] for r in rows))}；{named(rows)}"


def dominant(row):
    values = {}
    for lot in row['lots']:
        values[lot['trade_id']] = values.get(lot['trade_id'], 0.)+lot['pnl']
    if not values:
        return None
    tid = max(values, key=values.get)
    lot = next(x for x in row['lots'] if x['trade_id'] == tid)
    return lot, values[tid], row.get('entry_context', {}).get(lot['entry'], {})


def recommendations(legs, lookup, summary):
    pairs = [(lookup['master_C062', l['id']], lookup['IE47_C062', l['id']]) for l in legs]
    better = [(m, i) for m, i in pairs if m['pnl'] > i['pnl'] and m['any']]
    stale = [m for m, i in better if i['category'] == 'pool_not_named']
    reclaim = [m for m, _ in pairs if m['pnl'] > 0 and dominant(m) and
               dominant(m)[2].get('close_over_prior_high') is False]
    rearm = [i for _, i in pairs if i['category'] in ('pool_not_named', 'named_after_early_break', 'observation_expired')]
    blocked = [i for _, i in pairs if i['category'] == 'early_signal_blocked']
    repeat = [m for m, i in better if m['first_fill'] and i['first_fill']]
    failures = [m for m, i in better if i['early'] and i['pnl'] <= 0]
    rows = [
        ['1. 保留长期强势的第二入口，画像改为路径内排序',
         '沿用 master 已有 B 路径：过去 120 日曾进入六个月强势前 20%、周线向上、前晚靠近 9/21 EMA；'
         '与 IE47 原入口并存，再用当晚画像排序，不要求每晚各占固定名额。',
         evidence(stale)+'。本段无新点名与旧名单过期要分开。',
         '早买段、他的段金额、前十赢单来源；保留 IE47 已有赢家。',
         '② 周末 leader 扫描、③ 从中等升级领涨、④ 大底后的第一次回调。120 日/20% 是 master 已有拟合值，不冒充本人原话。'],
        ['2. 将日 K 均线区间相交/收回与收盘越前高并列',
         '直接复用 master 的三种原条件：E10 为前晚贴线、日内区间跨 9 EMA；E11 为跳空后的支撑握手；'
         'B 路径为长期强势股越前高或收回 9/21 EMA。全部看到当日日 K 后按收盘成交。'
         'E10 本身不要求收盘收回 9 EMA，不擅自把更严的收回过滤写成原版已有。',
         evidence(reclaim)+'。这些段的最大贡献交易当晚均未收过前高；只延长观察也不能在同晚触发。'
         '金额汇总全段，不是新入口的已验证增量。',
         '触发到成交、早买、capture、前十赢单。',
         '④ 9/21 EMA 回调、支撑重合；⑤ 急跌到支撑后收回。日 K 是任务授权的近似。'],
        ['3. 名单使用事件重置，观察过期允许再武装',
         '同一只票出现新的支撑收回/周线升级时，允许解除十晚冷却并重置观察；'
         '仍在有效日线结构中可再等一次触发；跌破结构后重新扫描，不靠几个月不撤销的旧点名。',
         f"本段缺有效新点名或点名赶不上早期突破 {len(rearm)} 段：{named(rearm)}；"
         f"IE47 这些段内 {num(sum(r['pnl'] for r in rearm))}。"
         f"S1 原样的 2026 段内 {num(summary['IE47_S1']['2026']['pnl'])}，没有证明简单长期挂名有效。",
         '早买、资金占用、capture；同时检验新增小亏和原有赢家是否被挤出。',
         '③ 名单升级重点看；⑤ 新入场动作；⑥ 错了先走。'],
        ['4. 把机会排序放在实际可成交的层上',
         '不要先按成交额截四名再让同票/风险拒绝浪费名额；用当晚可知的形态、画像和成交额排队，'
         '让已持同票跳过、未证实再试让位，已证实仓仍受风险保护；总仓数先沿用 11。',
         f"master 自身有 {sum(lookup['master_C062', l['id']]['category']=='daily_cap' for l in legs)} 段被预截四名；"
         f"IE47 有合格信号却未早买 {len(blocked)} 段，{named(blocked)}。完整拒绝状态保留，不能把同票已持也当作没有曝险。",
         '实际早买段、资金占用纯度；避免只提高信号覆盖。',
         '⑦ 同时 3–4 只、最多 11 只；新仓反馈决定继续加。排序函数需另登记，不用他的段标签。'],
        ['5. 资金预算给“当晚结构证实的仓”，保留探仓',
         'C062 已有 50% 单票上限，不再以提高上限当作解决方案；'
         '先对及时触发且结构证实的仓保留加仓预算，按风险上限扩仓，记录确认后实际名义与持有天数。',
         evidence(repeat)+'。同一 C062 下入场不同已造成实际仓位不同，表中逐段给试仓与最大仓位。'
         f"2026 master/IE47 的段资金占权益日为 {pct(summary['master_C062']['2026']['cap_equity'])}/{pct(summary['IE47_C062']['2026']['cap_equity'])}。",
         '资金占用纯度、段内绝对金额、毛利纯度、前十赢单；同时保留交易数与胜率约束。',
         '⑦ 百分比风险、证实后加大、新仓顺利才继续加。不是根据事后知道“他的票”分资金。'],
        ['6. 将确认后的持有规则与入场路径成对审查',
         '保留登记版 21 EMA / 10R 减仓作为完整对照；C062 侧可使用已实现 H21A，'
         '对支撑/周线结构证实的仓直接启用 21 EMA，而非统一等 5R。'
         '试单止损、风险预算、同日保守成交顺序保持明确；不是将所有亏单一律拿长。',
         evidence(failures)+'。同一 C062 中仍有早买亏损，必须先核对实际是证伪止损还是跟踪线退出；'
         '本次没有隔离出“只改均线”的收益，不重复宣传为新发现或保证。',
         'capture、前十赢单、确认仓资金日；同时核对峰后回吐与账户实际收益。',
         '⑥ 本人以 9 EMA 退出、留住大赢家；21 EMA/10R 是 master 的拟合机制，与原话有差别，需显式比较，不能写成本人已说过。'],
    ]
    return table(['建议', '具体机制（只用当晚信息）', '证据与金额', '希望改善的指标', '原话对应/边界'], rows)


def attribution(master, ie, own):
    statements = []
    if master['pnl'] > ie['pnl']:
        statements.append(f"master+C062 多赚 {num(master['pnl']-ie['pnl'])}。")
    elif ie['pnl'] > master['pnl']:
        statements.append(f"IE47+C062 多赚 {num(ie['pnl']-master['pnl'])}。")
    else:
        statements.append('两者段内金额相同。')
    if not ie['early']:
        statements.append('IE47 最远一层：'+STAGES[ie['category']]+'。')
        if ie['category'] == 'pool_excluded':
            fails = Counter(g for r in ie['gate_trace'] for g in r.get('failed', []))
            statements.append('过滤失败夜数 '+str(dict(fails))+'；四项可能同夜失败，不相加当段数。')
        if ie['category'] == 'pool_not_named':
            ranks = [r['eligible_rank'] for r in ie['gate_trace'] if r.get('eligible_rank') is not None]
            cooling = sum(r.get('cooling', False) for r in ie['gate_trace'])
            statements.append(f"扣除冷却后的最好排名 {min(ranks) if ranks else '无'}，目标处于冷却 {cooling} 夜。")
            if ie['previous_pick']:
                statements.append(f"此前旧点名为 {ie['previous_pick']}，本段应先解释为何没有及时重新点名，不能全归因于五晚太短。")
        if ie['category'] == 'observation_expired':
            breaks = ie['price_breaks']
            if breaks:
                statements.append(f"合格价位首次收盘过前高 {breaks[0]['day']}，距最近点名 {breaks[0]['age']} 晚。")
        if ie['rejection_counts']:
            statements.append('账户拒绝 '+str(ie['rejection_counts'])+'。')
    if master['first_fill'] and ie['first_fill']:
        m, i = master['first_fill'], ie['first_fill']
        statements.append(f"首次成交相对他入场为 {m['offset']:+d}/{i['offset']:+d} 个交易日；"
                          f"首次试单名义 {pct(m['initial_nominal_equity'])}/{pct(i['initial_nominal_equity'])}，"
                          f"峰前最大名义 {pct(master['max_nominal_equity'])}/{pct(ie['max_nominal_equity'])}。")
    if master['first_fill']:
        d = master['first_fill']['day']
        routes = master.get('signal_routes', {}).get(d, [])
        statements.append('master 首次成交当天符合路径 '+(route_text(routes) if routes else '见原始信号簿')+'。')
        context = master['entry_context'].get(d, {})
        if context:
            statements.append('当晚'+('收盘已过昨日高点' if context['close_over_prior_high'] else '收盘未过昨日高点，IE47 的严格突破条件不成立')+'；'
                              f"IE47 最近先行点名 {context['ie_previous_pick'] or '无'}，间隔 {context['ie_watch_age'] if context['ie_watch_age'] is not None else '无'} 晚。")
    if own['pnl'] != master['pnl'] and (own['any'] or master['any']):
        statements.append(f"同一 master 名单换执行：登记版 {num(own['pnl'])}，C062 {num(master['pnl'])}。"
                          '此差同时含再入场、资金复利、止损和跟踪规则，不能单独归功于某一条。')
    return ''.join(statements)


def render():
    frozen = read(OUT/'legs_legacy42.json')
    legs = frozen['legs']
    summary = read(OUT/'summary.json')
    funnels = read(OUT/'funnel.json')
    lookup = {(r['system'], r['leg']): r for r in funnels}
    master_rows = [lookup['master_C062', l['id']] for l in legs]
    ie_rows = [lookup['IE47_C062', l['id']] for l in legs]
    profile = read(OUT/'portrait_summary.json')
    portraits = read(OUT/'portraits.json')['records']
    routes = read(OUT/'master_paths.json')
    verdict = read(OUT/'verification.json') if (OUT/'verification.json').exists() else {}
    new_frozen = HOME/'notes/legs_frozen.json'
    new_note = '截至报告生成，A 线冻结段表未出现；本次按任务书使用旧 42 段。'
    if new_frozen.exists():
        new = read(new_frozen)
        old_keys = {(l['code'], l['peak']) for l in legs}
        new_keys = {(l['code'], l['peak']) for l in new['legs']}
        added = [l for l in new['legs'] if (l['code'], l['peak']) not in old_keys]
        removed = [l for l in legs if (l['code'], l['peak']) not in new_keys]
        diff = dict(frozen_sha256=sha(new_frozen), old=42, new=len(new['legs']),
                    counts=dict(Counter(l['first_date'][:4] for l in new['legs'])), added=added, removed=removed)
        write('frozen_diff.json', diff)
        new_note = f"A 线冻结段表已出现：{len(new['legs'])} 段，分年 {diff['counts']}；比本次多 {len(added)} 段、少 {len(removed)} 段。新增为 "+'、'.join(
            l['code'].removeprefix('US.')+' '+l['first_date']+'→'+l['peak_date'] for l in added)+'。本次保留旧 42 段以对应任务书和 pi 附录，不能拿两个分母直接比较覆盖率。差异清单见 `frozen_diff.json`。'
    headline = []
    for y in ('2024', '2025', '2026'):
        m, i = summary['master_C062'][y], summary['IE47_C062'][y]
        headline.append(f"{y}：master+C062 / IE47+C062 早买 {m['early']}/{m['n']} 对 {i['early']}/{i['n']}，"
                        f"截峰记账金额 {num(m['pnl'])} 对 {num(i['pnl'])}，资金占权益日 {pct(m['cap_equity'])} 对 {pct(i['cap_equity'])}。")
    deltas = sorted([(lookup['master_C062', l['id']]['pnl']-lookup['IE47_C062', l['id']]['pnl'], l)
                     for l in legs], key=lambda x: -x[0])[:4]
    major = '、'.join(l['code'].removeprefix('US.')+' '+l['first_date']+f"（差额 {num(delta)}）" for delta, l in deltas)
    fresh_missing = [r for r in ie_rows if r['category'] == 'pool_not_named']
    stale_count = sum(r['stale_nomination'] for r in fresh_missing)
    positive_master = [r for r in master_rows if r['pnl'] > 0]
    no_pdh = [r for r in positive_master if dominant(r)[2].get('close_over_prior_high') is False]
    headline += [
        f"最直接的触发差异：master+C062 的 {len(positive_master)} 个段内正贡献段中，{len(no_pdh)} 段的最大贡献交易，"
        '入场收盘没有越过昨日高点。IE47 当天的硬触发不成立；只延长观察期复制不了这些入场。',
        '差额最大的四段是 '+major+'。它们分别对应长期强势 B 路径、握手/均线区间相交等入口；'
        '逐段表还给出入场那晚究竟有没有收过昨日高点、IE47 的观察是否有效。',
        f"对合格早买窗口，IE47 有 {len(fresh_missing)} 段没有有效新点名，其中 {stale_count} 段只有更早的旧点名。"
        '旧点名距今可能已有几个月，须先查当前画像排序与重新点名；不能把这类差距全记成五晚观察太短。',
        '可移植的重点是“长期强势记忆＋接近均线时重新识别＋多种日 K 触发”，随后让证实仓真正占到资金并拿住。'
        'master 按成交额预取四名同样漏段，IE47 在其特有的段上也有优势，因此建议保留两条入口，按当晚状态分配机会。',
    ]
    text = ['# D1：master 怎样买到、拿住并放大他的行情段', '',
        '这次固定 42 段、五套已有系统，只做离线诊断，没有拟合参数、没有改登记版和看板。'
        'master 的优势要分别看“何时让这只票具备资格”“哪种日 K 动作就能成交”“成交后放了多少钱、拿了多久”。'
        '完整逐段核对在第 5 节；CSV/JSON 保留每次成交、加仓、拒绝与过滤细节。', '',
        *[line+'\n' for line in headline],
        '## 1. 口径与可比范围', '',
        '- 段固定为任务书指定的 `mainleg.legs` 旧 42 段：2024/25/26 = 9/16/17；'
        '输入为 `ie5_work/prepared.json` 的 81 条可用多头锚点。两个截断段保留，短脉冲段也保留。',
        '- 主表全部使用 2024 起的三年连续账户。登记 master 为实际 R74+S7 多空账户；其余四套为各自原有的多头账户。'
        'master+C062 与 master+S1 接收 master 的多头收盘信号，保留原有大盘过滤与每日四名上限。',
        '- 每次买入/加仓只分配一次：成交位于他首次入场前三个交易日到峰前；重叠窗口取剩余百分比涨幅最大的段，平手取最早锚点。'
        '同一笔的不同 lot 可以分属不同段，段外买入后来持有进来不倒算。',
        '- “早买”按真实首次买入价格判断：峰值相对成交价的剩余涨幅，不少于某个已到资格锚点涨幅的一半。'
        '加仓能贡献金额，但不能把已持有的旧单算作一次新的早买。',
        '- 段内 pnl：实际减仓按比例分给当时各 lot；未卖出的份额估值到峰日收盘，峰后收益进残余账。'
        '计入实际买卖费，峰日估值不虚扣卖费，不分摊融资利息。pnl 单位是各账户初始权益 1。',
        '- capture 总段 = 段内 pnl / Σ(每 lot 买入名义 × 他起点到峰值涨幅)；余段 capture 的分母改为每 lot 到峰的价差。'
        '按金额加权，不平均每笔百分比。允许早于他买得更低时超过 100%。',
        '- 生命周期位置 =（成交价 − 峰前 60 日最低价）/（峰价 − 同一最低价）。'
        '这和“剩一半百分比涨幅”是两种尺子，不能把生命周期位置 0.5 当成早买门槛。',
        '- 资金占权益日：每日收盘段内名义 / 当日权益，再按自然年平均；现金进分母。'
        '峰前最大仓位也是日末名义/权益，非盘中最大。段表的金额按段年，年度主表金额按交易首次成交年，跨年差异单列在 JSON。',
        '- 毛利纯度同时列两种：主列将每笔段内 H 与残余 O 分开取正数，GP(H)/(GP(H)+GP(O))；'
        '括号列沿 pi 试算，用 GP(H)/原整笔交易 GP。截峰产生的盈利回吐可能使后一口径失去 0–100% 边界，不能混用。'
        '前 10 赢单按原账户已平仓交易 pnl 排序，排除 end 期末估值，H>0 才计为来自他的段；含 end 的计数在 JSON 另存。',
        '- 所有峰值、段标签与“他的票”仅在评测侧使用。画像描述 2024–25 与固定 2026，未用 2026 再挑参数，亦不新增样本外资格。', '',
        '### 同一范围下的结果', '']
    text += [new_note, '']
    headers = ['系统', '年', '段内有首次买入', '早买/分母', '早买且段内正', '段内 pnl / 年初权益比',
               '资金占权益日', 'capture 总段', '毛利纯度（pi 比例）', '前十中 H']
    body = []
    for n in NAMES:
        for y in ('2024', '2025', '2026'):
            r = summary[n][y]
            body.append([NAMES[n], y, r['any'], f"{r['early']}/{r['n']}", r['early_positive'],
                         f"{num(r['pnl'])} / {pct(r['pnl_year_equity'], True)}", pct(r['cap_equity']),
                         pct(r['capture_total'], True), f"{pct(r['purity_gross'])}（{pct(r['purity_legacy'])}）", r['top10_h']])
    text += [table(headers, body), '',
        '金额大也可能部分来自该账户此前赚得多、可用权益更大，因此同时报相对年初权益的金额和日末仓位比例。'
        '登记 master 的空头会影响资金与权益，但不给多头段贴标签；不能把它和只有多头的 C062 当作单变量实验。'
        '另一个执行差别是：登记 master 的 `max_open=0`，没有 11 仓数上限；C062 才是最多 11 仓。'
        '登记风险为 0.5%/0.8% 加市况倍率，C062 的引擎探仓风险参数为 0.25% 加自己的市况倍率，确认后再扩仓。', '',
        '2025 的优势也要分开看：相对各自年初权益，master+C062 段金额为 '+pct(summary['master_C062']['2025']['pnl_year_equity'])+
        '，IE47 为 '+pct(summary['IE47_C062']['2025']['pnl_year_equity'])+'，小于初始权益金额表面上的倍数差；'
        '同年毛利纯度反而是 IE47 '+pct(summary['IE47_C062']['2025']['purity_gross'])+' 高于 master '+pct(summary['master_C062']['2025']['purity_gross'])+
        '。本次据此提取机制，不把 master 宣称为每个指标都优于 IE47。', '',
        '截峰记账金额中含峰日仍未卖出的浮盈，不等于最后实际落袋。拆开看：', '',
        table(['系统', '年', '峰前已卖部分 pnl', '峰日剩余仓估值 pnl', '合计'], [
            [NAMES[n], y, num(summary[n][y]['pnl_realized']), num(summary[n][y]['pnl_marked']), num(summary[n][y]['pnl'])]
            for n in ('master', 'master_C062', 'IE47_C062') for y in ('2024', '2025', '2026')]), '',
        '### pi 原试算的桥接', '',
        'pi 使用 master 的 2024–25 连续训练台账，加上 2026 单开台账；主表使用三年连续。'
        '本次还改为 lot 分账并剔除峰后收益，因此不应把 +1.330、+0.242 直接当成同口径验收数字。'
        '两份原账户的重算见 `d1_work/pi_bridge.json`；master+C062 的完整原台账与权益已逐值复现，'
        'IE47 的 '+str(read(OUT/'selection_check.json')['nights'])+' 夜点名及底版信号亦逐值核对，差异来自计量口径而非替换输入。', '',
        'IE47 的 2026“段内任意首次成交”由旧近似的 10 段变为本表 9 段，是重叠窗口按 lot 唯一归属后不再重复覆盖；'
        '未剔除段，分母仍为 17。重叠交易的所有可归属段和最终分配见 `overlap_audit.json`。', '',
        table(['原账户范围', '年', '早买段', '早买整笔最终 pnl（近似旧试算）', '段内全部 lot 截峰 pnl'], [
            [label, y, r['early'], num(r['early_full_trade_pnl']), num(r['pnl'])]
            for label, years in read(OUT/'pi_bridge.json').items() for y, r in years.items()
            if r['year_initial_equity'] is not None]), '',
        '## 2. 每层究竟有什么不同', '',
        table(['环节', '登记 master / master+C062 的输入', 'IE47+C062 的输入', '能得出的判断'], [
            ['流动性/强度池', f"{routes['pool']}：价格≥{routes['pool_thresholds'][0]:g} 美元、20 日成交额≥{routes['pool_thresholds'][1]/1e6:g} 百万美元、ADR≥{routes['pool_thresholds'][2]:g}%；"
             '主路径：1/3/6 月任一涨幅进入前 10%，保留五日；日线多头或周 9>21，并且 ADR≥5%。B/EP 有独立入口，可绕过主路径观察池',
             '上个完整周成交额>3 亿美元；H4 历史、ADR、期权量、距 20 日低点四项横截面分位同时过滤',
             'master 与 IE47 的池互不包含；不能把期权量/离低点门槛当作本人原话'],
            ['排名/名额', '原始信号按前晚 20 日成交额排序；大盘过滤后先截每日四名，再交账户',
             '固定画像分数；每晚三只新名字；前十晚点过名的排除',
             'master 不存在“画像分数不够前三”这一层，但也有成交额排序挤出'],
            ['触发', '当日高低价或收盘满足不同形态后按收盘成交；含日内跨 EMA、收回 EMA、周线突破、跳空；B 路径保留 120 日的六个月强势历史',
             '点名后下一日起五晚内，收盘严格高于前日最高价；首次突破消耗观察',
             '收回支撑与收盘越前高不是同一动作；不能把未越前高都写成没机会'],
            ['账户容量', '登记 master 每日四个预截信号；C062 另受最多 11 仓、每日四笔、同票、风险/总敞口约束',
             'C062 容量规则相同；信号来源不同，入场名额占用也不同',
             '必须看实际拒绝记录；观察过期不算格子不足'],
            ['仓位', '登记版按反馈风险 0.5%/0.8%、回调市况倍率、最多 50% 单票，10/20R 加；C062 原样探仓/确认',
             '同一 C062：先探仓、确认后风险约束加到目标仓、单票最多 50%',
             'master+C062 与 IE47+C062 差异不能归因于改过 C062 仓位上限'],
            ['退出', '登记版 10R 减 30%，沿 21 EMA；C062 依原规则确认、达到 5R 等条件后换 21 EMA',
             'C062 未证实可收盘证伪、盘中灾难止损，证实后成本保护；此前会沿 9 EMA',
             '相同卖法接入不同位置/波动的票，实际拿住时间也会不同'],
        ]), '',
        '### 42 段的最远一层', '']
    selection = read(OUT/'ie_selection.json')
    di = {d: i for i, d in enumerate(selection['days'])}
    ci = {c: j for j, c in enumerate(selection['codes'])}
    selected_nights = {r['index']: r for r in selection['nights']}
    scope_j = np.load(OUT/'ie_scope_j.npy', mmap_mode='r')
    gate_pct = np.load(OUT/'ie_gate_pct.npy', mmap_mode='r')
    critical = []
    filtered_critical = []
    for row in positive_master:
        lot, profit, context = dominant(row)
        if not context.get('ie_pool_previous_night') and (context.get('ie_watch_age') is None or context['ie_watch_age'] > 5):
            filtered_critical.append(row)
        d = di[lot['entry']]-1
        night = selected_nights.get(d)
        failure = '不在比较范围'
        if night:
            a, b = night['scope_start'], night['scope_end']
            found = np.flatnonzero(scope_j[a:b] == ci[row['code']])
            if len(found):
                ps = clean(gate_pct[a+int(found[0])])
                failed = [g[0] for k, g in enumerate(selection['gates'])
                          if (ps[k] is None and k != 0) or (ps[k] is not None and ps[k] < g[1])]
                failure = '、'.join(failed) or ('进池；分数第 '+str(night['ranks'].get(row['code'])))
        critical.append([row['leg']+' '+row['code'].removeprefix('US.'), lot['entry'],
                         num(profit), route_text(row['signal_routes'].get(lot['entry'], [])) or '已有仓加仓',
                         '是' if context.get('close_over_prior_high') else '否',
                         failure, str(context.get('ie_watch_age')) if context.get('ie_watch_age') is not None else '此前未点名',
                         lot['exit']+' / '+EXITS.get(lot['why'], lot['why'])])
    counts = {n: Counter(lookup[n, l['id']]['category'] for l in legs) for n in NAMES}
    cats = list(dict.fromkeys(c for n in NAMES for c in counts[n]))
    text += [table(['最远一层']+list(NAMES.values()),
                   [[STAGES[c]]+[counts[n].get(c, 0) for n in NAMES] for c in cats]), '',
        '这里只按“仍剩一半涨幅”的合格成交窗口归类；晚买即使赚钱，也保留其早期失败层。'
        '第 5 节同时列段内所有首次成交，避免把晚买造成的盈利静默删掉。', '',
        'E21 的 13/20 是另一组固定交易行的观察诊断，本表是 42 个合并大段、按可产生早买的点名窗口归类，人数不能直接照搬。'
        '这里“未获有效新点名”仍保留最近一次旧点名和突破时的年龄；“观察过期”专指本段已有点名但首次有效突破赶在其后。', '',
        '### master 的八个段内盈利段：最大贡献交易当晚', '',
        table(['段', '该笔入场', '该笔段内 pnl', 'master 同晚路径', '收盘过昨日高点', '前晚 IE47 池/排名', '距 IE47 先行点名晚数', '实际退出'], critical), '',
        '七笔“否”是真正的触发差，不依赖对点名窗口的分类。B 路径允许当日最高价越前高后回落，或回踩收回 EMA；'
        '握手/均线区间相交也允许收盘仍低于昨日高点。E10 回踩分支只要求当日低≤前晚 9 EMA≤当日高，'
        '没有额外的收盘收回要求；B 路径的 EMA 分支才明确要求收盘收回。'+named(filtered_critical)+' 在对应前晚还被 IE47 过滤，且当时没有有效旧观察。'
        '所以“整段某夜进过池”不能代表关键入场夜已经有资格。反之，前晚掉出池也不会取消仍有效的五晚观察。'
        '路径可以重叠，不重复相加归因金额。', '',
        '### IE47 反过来优于 master 的段（同一 C062）', '',
        table(['段', '票/锚点', 'IE47 段内 pnl', 'master 段内 pnl', '早买 IE47/master', 'master 最远一层'], [
            [l['id'], l['code'].removeprefix('US.')+' '+l['first_date'], num(lookup['IE47_C062', l['id']]['pnl']),
             num(lookup['master_C062', l['id']]['pnl']),
             str(int(lookup['IE47_C062', l['id']]['early']))+'/'+str(int(lookup['master_C062', l['id']]['early'])),
             STAGES[lookup['master_C062', l['id']]['category']]] for l in legs
            if lookup['IE47_C062', l['id']]['pnl'] > lookup['master_C062', l['id']]['pnl']]), '',
        '## 3. 起涨时的日 K 画像', '',
        '每段从他入场前三个交易日起，取实际收盘仍剩一半涨幅的头三个夜晚（不足三晚照实保留）。'
        '先在段内取中位数，再在同年各段之间取中位数，每段一票，避免长段重复投票。'
        '完整所有合格夜另存 `portraits.json`。所有同晚流动性股票只用于描述分布，没有做随机入场或安慰剂。', '',
        '表格为“目标票原值中位；在全流动性 / master 流动性池 / IE47 池的分位中位”。'
        '目标票不在该池也计算相对分位。50 是池中间，90 是约高过九成同池票；缺值不补。'
        'EMA 顺序沿 v1.1：0–2 分而非二元；内包/窄幅的分位受大量并列值影响，原值与逐段分布一起看。', '']
    body = []
    for f in FEATURES_CN:
        cells = []
        for y in ('2024', '2025', '2026'):
            r = profile[y][f]
            cells.append(f"{r['median']:.2f}；"+'/'.join('—' if r[g]['median'] is None else f"{r[g]['median']:.0f}" for g in ('liquid', 'master_pool', 'IE47_pool'))
                         if r['median'] is not None else '缺值')
        body.append([FEATURES_CN[f]]+cells)
    pool_portrait = []
    for year in ('2024', '2025', '2026'):
        per_leg = {l['id']: [r for r in portraits if r['leg'] == l['id'] and r['first_three']]
                   for l in legs if l['year'] == year}
        misses = {pool: [lid for lid, rs in per_leg.items() if not any(r['memberships'][pool] for r in rs)]
                  for pool in ('master_pool', 'master_momentum', 'IE47_pool')}
        label = {l['id']: l['code'].removeprefix('US.') for l in legs}
        pool_portrait.append([year, len(per_leg),
             str(len(per_leg)-len(misses['master_pool'])), str(len(per_leg)-len(misses['master_momentum'])),
             str(len(per_leg)-len(misses['IE47_pool'])),
             '、'.join(lid+' '+label[lid] for lid in misses['master_pool']) or '无',
             '、'.join(lid+' '+label[lid] for lid in misses['IE47_pool']) or '无'])
    text += [table(['画像项目', '2024', '2025', '2026'], body), '',
        '### 最早三个合格夜，哪些池已经接住', '',
        table(['年', '段数', 'master 流动性池有过', 'master 主观察池有过', 'IE47 池有过',
               'master 流动性池三夜都无', 'IE47 池三夜都无'], pool_portrait), '',
        '此表按画像的最早三个合格夜计，不等于整个可早买窗口的可达性。B/EP 不必进入 master 主观察池；'
        '表中未进入 IE47 的段，其每夜具体失败分位保留在逐段 `gate_trace`，关键盈利交易的前晚过滤另在第 2 节列明。', '',
        '稳定差异是成交额大、靠近短均线、量比普通或收缩。成交额相对全流动性范围的中位分位为 '+
        '/'.join(f"{profile[y]['dollar_vol20_M']['liquid']['median']:.0f}" for y in ('2024', '2025', '2026'))+
        '；离 9 EMA 的中位距离约 '+ '/'.join(f"{profile[y]['ext_ema9_adr']['median']:+.2f}" for y in ('2024', '2025', '2026'))+
        ' ADR。起涨前几晚的成交量并非共同处于爆量尾部，单靠当日放量排名容易错过准备期。', '',
        '强势周期按年份有区别：2025 的 1 月涨幅中位仅 '+f"{profile['2025']['perf21_pct']['median']:.1f}%"+
        '，但 6 月涨幅中位为 '+f"{profile['2025']['perf126_pct']['median']:.1f}%"+
        '，更像长期强票的回调再起；三年的一年高点距离都仍明显为负。'
        '2026 的 ADR 在 IE47 池里中位仅 '+f"{profile['2026']['adr20_pct']['IE47_pool']['median']:.0f}"+
        ' 分位。继续只偏爱最高 ADR、最近一个月最强、当晚最放量，会把与目标不同的票排到前面。'
        '这些是描述，不据此选阈值或重新拟合。', '',
        '成交额/ADR 的过滤实测使用各系统原代码；画像使用 `standard_indicators v1.1` 的既有单位与暖机。'
        '六个月收益是相同公式的 126 日扩展，v1.1 没有单列该名称，明确作为补充而非伪称已有字段。'
        '各组四分位数、有效样本数和 master 动量观察池分位见 `portrait_summary.json`。', '',
        '## 4. 可移植机制（待实现建议，未回测收益承诺）', '',
        '下面的证据是已固定系统之间的描述差，不是单项改动的因果收益。建议在 2024–25 另行预登记，'
        '只用当晚已有行情识别资格；“他的段”不得成为盘中/选股特征。2026 本次仅作固定诊断。', '',
        recommendations(legs, lookup, summary), '',
        '## 5. 42 段逐一核对', '',
        '“池/名单”列：master 为原流动性池/动量观察池的首次通过日；IE47 为过滤池/首次点名日。'
        '日期限用于早买的机会窗口（IE47 额外向前检查五晚观察的有效点名），不是历史上第一次入池。'
        '没有窗口内点名时列最近一次旧点名，标“旧”；其观察过期不能误写成从未点名。'
        'master 的 B/EP 路径不要求主路径动量观察池通过，路线单列，不能把名单列的“无”当成所有入口都不可达。'
        '“买入”列依次是首次成交日、相对他入场的交易日差、生命周期位置。'
        '“仓位”依次是首次探仓名义/权益、实际加仓、峰前最大日末名义/权益。退出列是首次匹配交易实际退出；金额汇总该段全部 lot。', '']
    for leg in legs:
        lid = leg['id']
        text += [f"### {lid} {leg['code'].removeprefix('US.')}：{leg['first_date']} → {leg['peak_date']}", '',
                 f"起点到峰价 {pct(leg['entries'][0]['gain'], True)}，{leg['duration']} 个交易日；"
                 f"台账精度 {'/'.join(leg['precisions'])}；{'后续 60 日截断' if leg['censored'] else '窗口完整'}。"
                 f"生命周期低点 {leg['trough_date']}、低价 {leg['low']:.3f}。", '']
        body = []
        for n in NAMES:
            r = lookup[n, lid]
            first = r['first_fill']
            buy = '未在段内首次买入' if not first else f"{first['day']}；{first['offset']:+d}；{first['lifecycle']:.3f}"
            size = '—' if not first else f"{pct(first['initial_nominal_equity'])}；证{'实' if first['confirmed_day'] else '否'}/加{'有' if r['had_add'] else '无'}；{pct(r['max_nominal_equity'])}"
            exit_ = '—' if not first else f"{first['exit']} / {EXITS.get(first['why'], first['why'])}"+(
                ' '+first['trailing_at_exit'] if first['why'] == 'trail' else '')
            sig = r['first_signal'] or '—'
            if r['first_early_signal'] and r['first_early_signal'] != r['first_signal']:
                sig += '（首合格 '+r['first_early_signal']+'）'
            nomination = r['first_momentum'] if n.startswith('master') else (r['first_pick'] or ((r['previous_pick']+'旧') if r['previous_pick'] else None))
            body.append([NAMES[n], (r['first_pool'] or '—')+' / '+(nomination or '—'),
                         sig, buy, size, exit_, f"{num(r['pnl'])} / {pct(r['capture_total'], True)}", STAGES[r['category']]])
        text += [table(['系统', '池 / 名单', '信号日', '买入：日/早晚/位置', '仓位：试/加/最大', '首笔实际退出', '段内 pnl / capture', '早买漏斗'], body), '',
                 attribution(lookup['master_C062', lid], lookup['IE47_C062', lid], lookup['master', lid]), '']
        contributions = []
        for n in ('master', 'master_C062', 'IE47_C062'):
            r = lookup[n, lid]
            by_trade = {}
            for lot in r['lots']:
                by_trade[lot['trade_id']] = by_trade.get(lot['trade_id'], 0.)+lot['pnl']
            if not by_trade:
                continue
            key = max(by_trade, key=by_trade.get)
            lot = next(x for x in r['lots'] if x['trade_id'] == key)
            contributions.append(f"{NAMES[n]} 最大段内贡献来自 {lot['entry']}→{lot['exit']}，{num(by_trade[key])}，"
                            f"{'有实际加仓' if lot['additions'] else '无实际加仓'}；段内记到 {lot['mark_to']}。")
            if n.startswith('master'):
                ctx = r['entry_context'].get(lot['entry'])
                if ctx:
                    contributions.append('这笔入场当晚'+('收过前高' if ctx['close_over_prior_high'] else '未收过前高')+
                        f"，IE47 先行点名距今 {ctx['ie_watch_age'] if ctx['ie_watch_age'] is not None else '无点名'} 晚。")
        text += [''.join(contributions), ''] if contributions else []
        if not any(lookup[n, lid]['any'] for n in NAMES):
            text += ['五套系统在本段都没有首次成交；这是否定这些固定规则在该窗口的触达，不是否定本人方法。', '']
    text += ['## 6. 工件、复算与验证', '',
        '- `d1_work/protocol.json`：计算前固定的范围、公式、资源与输入指纹。',
        '- `legs_legacy42.json`：42 段与锚点、峰值、低点、精度、截断标志；`funnel.csv/json`：210 行逐段漏斗。',
        '- `*_metrics.json`：每次买入/加仓的分配与金额、持仓资金日、年度来源和前十赢单；`summary.json` 为主表。',
        '- `portraits.json` / `portrait_summary.json`：全部机会夜、头三晚标记、原值、四类同晚池分位、样本数和四分位。',
        '- `master_*`、`ie_selection.json` 和内存映射数组：重放信号、拒绝、观察事件、过滤分位、排名与来源路径。',
        '- `trace_checks.json`：master+C062 的交易和权益逐值一致，IE47 点名与底版信号逐值一致；'
        '`self_check.json` 检查分批、加仓、重叠段唯一分配、峰值边界和未来卖价扰动。', '',
        '复算各阶段分别运行，始终单进程；首次选择输出的 JSON 展开触及内存上限前已主动终止，'
        '随后只改变工件存储为有界数组，原样重建固定选择，无参数更改。', '',
        '```bash',
        'systemd-run --scope -p CPUQuota=60% -p MemoryMax=900M -q env OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 PYTHONDONTWRITEBYTECODE=1 /opt/opend-us-options/.venv/bin/python -m studies.martin_luk.d1_research freeze',
        '# 同样的资源前缀，顺序执行 d1_research master / selection / trace / paths；',
        '# 再执行 d1_analyze check / measure / portraits，最后 d1_report。',
        '```', '',
        '本报告不改登记、看板、A 线共享文件；不联网、不拉数据、不提交 git。', '',
        '来源：[任务书](../notes/PLAN_D1_CN.md)、[本人原话与时间戳](../notes/RULES_CN.md)、'
        '[pi 口径](../notes/PI_METRIC_ADVICE_20261107_CN.md)、[登记系统](../../trader_replication/systems.py)、'
        '[IE47 选股与触发](../ie47_e1.py)。']
    if verdict.get('ok'):
        text += ['', f"验收：D1 持久化工件核对通过；Martin {verdict['tests']['martin']['count']} 项、"
                 f"custody {verdict['tests']['custody']['count']} 项测试全部通过。纳入指纹核对的登记配置、原实现及已有输入未变；"
                 'A 线自行修改的 mainleg 和新段表单独注明。']
    (OUT/'report_draft.md').write_text('\n'.join(text)+'\n', encoding='utf-8')
    if verdict.get('ok'):
        (HOME/'reports/D1_CN.md').write_text('\n'.join(text)+'\n', encoding='utf-8')
    write('report_groups.json', dict(master_better=[l['id'] for l, m, i in zip(legs, master_rows, ie_rows) if m['pnl'] > i['pnl']],
          ie_better=[l['id'] for l, m, i in zip(legs, master_rows, ie_rows) if i['pnl'] > m['pnl']],
          counts=counts))
    print(f'D1 report rendered: {len(legs)} segments / {len(funnels)} system rows')


if __name__ == '__main__':
    offline()
    render()
