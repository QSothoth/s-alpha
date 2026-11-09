"""Render the E1 delivery from its immutable selection and evaluation artifacts."""
from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
import resource

import numpy as np

from studies import trader_data as TD
from studies.trader_data import panel as TP, supplemental as SP
from . import ie47_e1 as M
from .ie47_audit import WORK, progress, write

ROOT = Path(__file__).resolve().parents[2]
REPORTS = WORK.parent


def load(name):
    return json.loads((REPORTS/name).read_text(encoding='utf-8'))


def pct(x):
    return '—' if x is None else f'{x:+.1%}'


def num(x):
    return '—' if x is None else f'{x:.2f}'


def diagnose():
    """Inspect recorded chosen trades and the same entry builder, without simulating another account."""
    selected, val = load('e1_selected.json'), load('e1_validation.json')
    A = M.STUDY.arrays('us', mode='frozen')
    picks = json.loads((WORK/'picks.json').read_text())
    entries, _, events = M.entry_book(A, picks, 3 if selected['chosen'] == 'E3' else 5)
    trades = json.loads((WORK/'chosen_full_trades.json').read_text())
    expected = {(str(A['codes'][e[1]]), str(A['days'][d])): e for d, row in enumerate(entries) for e in row}
    bad = []
    for t in trades:
        e = expected.get((t['code'], t['entry']))
        if e is None or t['fill'] != e[3] or t['stop'] != e[4]:
            bad.append((t['code'], t['entry']))
    if bad:
        raise AssertionError(('recorded chosen fills differ from the unchanged entry builder', bad[:5]))
    years = {}
    for y in ('2024', '2025', '2026'):
        part = [t for t in trades if t['entry'].startswith(y)]
        years[y] = dict(selected=sum(len(v) for d, v in picks.items() if d.startswith(y)),
                        eligible=sum(len(row) for d, row in zip(A['days'], entries) if str(d).startswith(y)),
                        opened=len(part), closed=sum(t['why'] != 'end' for t in part),
                        chase=sum(e['why'] == 'chase' and e['day'].startswith(y) for e in events),
                        expired=sum(e['why'] == 'expired' and e['day'].startswith(y) for e in events),
                        same_day_stop=sum(t['why'] == 'stop_day0' for t in part),
                        exits=dict(Counter(t['why'] for t in part)))
    top = sorted(trades, key=lambda t: -t['pnl'])[:5]
    result = dict(chosen=selected['chosen'], annual=years, exact_entry_checks=len(trades), differences=bad,
                  top=[{k: t[k] for k in ('code', 'entry', 'exit', 'fill', 'stop', 'ret', 'r', 'days', 'why', 'executions')}
                       for t in top], source_sha256=SP.sha(Path(M.__file__)),
                  note='Only the selected execution is inspected; no new candidate or account is evaluated.')
    write(REPORTS/'e1_execution_diagnostics.json', result)
    progress('recorded trades match the entry builder exactly')
    return result


def render():
    migration, candidates, selected = load('e1_selection.json'), load('e1_candidates.json'), load('e1_selected.json')
    val, three, smoke, checks = load('e1_validation.json'), load('e1_three.json'), load('e1_board_smoke.json'), load('e1_checks.json')
    if not all(r['ok'] for r in checks.values()):
        raise AssertionError('required test suites must pass before the delivery report is rendered')
    from studies.trader_replication import compare
    comparison = json.loads((ROOT/'studies/trader_replication/reports/compare.json').read_text())['martin_luk_ie47']['markets']['us']
    if comparison['run']['code_digest'] != compare.code_digest() or not comparison['gate']['ok']:
        raise AssertionError('comparison must pass with the delivered source')
    if comparison['by_year'] != val['full']['by_year'] or smoke['frozen']['check']['ok'] is not True:
        raise AssertionError('comparison, once-evaluated account and board replay must agree')
    diag = diagnose()
    n_pass = sum(row[1] for row in val['success'])
    L = ['# IE47 + E3：E1 任务交付', '',
         f"结论：**选股移植完成，但执行复刻没有成功**。冻结期 {migration['exact_nights']}/{migration['nights']} 晚，名单及顺序完全一致；"
         '三把尺子、两次截断检查均通过。四个执行候选按预登记选出 E3（观察期三天），'
         f"连续账户 2024 / 2025 / 2026 为 {pct(val['full']['by_year']['2024'])} / {pct(val['full']['by_year']['2025'])} / "
         f"{pct(val['full']['by_year']['2026'])}，全段 {pct(val['full']['total'])}，最大回撤 {val['full']['maxdd']:.1%}，"
         f"复刻标准仅 {n_pass}/7。没有可替换 master 的方案。", '',
         '新系统独立登记为 `martin_luk_ie47`（归属 `martin_luk`，`IE47 + E3`，研究版、未冻结）。'
         'R74 + S7 保留，默认整板未切换。只改 gap-review 工作区；未提交、推送、冻结或发送 QQ；未取新行情、未调用 OpenD、未扣历史额度。', '',
         '## 1. 选股、来源和缺口', '',
         '画像只恢复已有九项的完整精度档边界和分数，没有重新选择指标或拟合权重；全部展示分数与 `fit.json` 一致。'
         '边界只用 2024–25 的训练行，`ie47_profile.json` 保存来源、原库指纹与导出时的源码 SHA256，文件设为只读。'
         '运行时不读研究价格缓存、拟合器或台账；日线、QQQ、每日股票期权统计均通过 `studies/trader_data`。', '',
         '| 项目 | 结果 |', '|---|---|',
         '| 比较范围 | 逐晚与 `prepared.json.scope` 相同，按上一完整周成交额 >3 亿美元及历史有效性重建；范围中位约1048只 |',
         f"| 名单和顺序完全一致 | {migration['exact_nights']}/{migration['nights']}，{migration['ordered_exact_rate']:.1%}；含一个空名单夜晚，原 scorecard 只保存 701 个非空夜晚 |",
         '| 不一致原因 | 无；四个过滤字段与七个指标在核对容差内一致，七个指标各核对47,410个过滤后样本；名单及顺序完全相同 |',
         '| 不看未来 | 截到 2024-09-30：189/189 晚；2025-09-30：439/439 晚，均与全量前缀一致；执行门禁另检查全部入场字段、规则及数组 |', '',
         '**`h4_history` 不是四小时 K 线。** 来源是 `martin_continue_ie5.prepare` 导出的 H4 历史组：'
         '前一日的 `stay250`（U4 中滞后一日的活跃度前 100 名频率）与 `fast250`（按当时未复权收盘及公司行动校正的 ≥5% 波动频率），'
         '分别在当日 H4 active 范围内排名后等权平均。统一数据层按股票分块重建同一套日线计算，不需要 81 只小时线数据。'
         '只保留这个组，没有为了它构造股票相关性大矩阵；H4 缺失按 h4nan 通过。', '',
         '**`option_volume` 是股票当日的期权总成交量。** 原生成链是 `martin_continue_ie_factors.option_arrays` → '
         '`data/trader-options-v1/us/stat/<code>.csv` → `extra_option_volume`；没有延用旧日期。'
         '本机实际冻结文件有 3,433 只，超过任务书所述约 72 只。因此冻结期不缺这条输入，不需要替代，也没有改范围或删除过滤条件。'
         'ADR20 和 low20 继续用原 IE 指标定义，四条分位均在当晚完整比较范围内计算，并列取平均名次。', '',
         '| 年份 | 主升浪覆盖 | 撒网比例中位 | 信号后 60 日最高涨幅中位 | 翻倍比例 |', '|---|---|---|---|---|']
    for y, row in migration['scorecard'].items():
        L.append(f"| {y} | {row['covered']} | {row['net']}% | {row['run_median']}% | {row['ge100']}% |")
    L += ['', '三把尺子均由 `mainleg.py` 复算并与 IE47 scorecard 完全一致。2026 选股结果是既有研究的复现，不是新的执行择优或新盲测。', '',
          '## 2. E1–E4：只在 2024–25 选择', '',
          '下面是连续账户的分年收益、年内最大回撤、按入场年份统计的已平仓笔数 / 开仓笔数；平均赚亏及持有天数只计已平仓。'
          '成本取 `COSTS[\'us\']`，保留原引擎融资成本。', '',
          '| 候选 | 年份 | 收益 | 年内最大回撤 | 平仓 / 开仓 | 胜率 | 平均赚 / 亏 | 平均持有交易日 |',
          '|---|---|---|---|---|---|---|---|']
    for name, result in candidates['candidates'].items():
        for y, row in result['annual'].items():
            L.append(f"| {name} | {y} | {pct(row['ret'])} | {row['maxdd']:.1%} | {row['n']} / {row['opened']} | "
                     f"{row['win']:.1%} | {pct(row['avg_win'])} / {pct(row['avg_loss'])} | {num(row['mean_days'])} |")
    L += ['', '| 对照 | 2024 收益 / 笔数 / 胜率 / 平均赚亏 | 2025 |', '|---|---|---|',
          '| Martin 本人（任务书目标） | +283% / 423 / 约25% / +15% 与 −3% | +970% / 940 / 22% / +14.1% 与 −2.1% |',
          '| master R74 多头（既有报告） | 约+326% / 开仓308笔 | 约+239% / 开仓222笔 |', '',
          'master 的既有全段胜率 18.5%、平均赚 / 亏 +27.5% / −2.6%、最大回撤约61%；这些是全段数，未冒充分年数。'
          '本人没有可核对的平均持有天数目标，持有天数只报告、不虚构门槛。', '',
          '| 候选 | 两年合计 | 两年最大回撤 | 同池随机中位 | 可判断标准通过 | 两年行为差距均值 |',
          '|---|---|---|---|---|---|']
    for name, r in candidates['candidates'].items():
        L.append(f"| {name} | {pct(r['total'])} | {r['maxdd']:.1%} | {pct(r['placebo']['median'])} | "
                 f"{r['selection_passes']}/6 | {r['behaviour_gap']:.4f} |")
    L += ['', 'E1 原样；E2 加前一收盘 QQQ ≥50 EMA；E3 仅把观察期缩为三天；E4 仅按前一收盘已经平仓的最近五笔反馈减半风险。'
          '四者都只通过工程门禁。按预登记先比通过组数，再比 `study.gap`，E3 的行为差距最小而被选中。'
          'E2 的训练收益较高，但行为差距较大；没有把 E3 称为收益最优，也没有改选择规则追 E2。', '',
          '**时点约定：** t 晚入选，最早 t+1 触发；首次严格越过昨高消耗观察机会，追价、账户拒绝或市况拦截后不在同次观察里重试。'
          'ADR 用前一收盘。止损为 `min(max(昨低, 成交价×(1−min(3%,半ADR))), 成交价×99%)`。'
          '日内先后未知，买入日触止损先出；当天不算可能早于入场的 R 分批，收盘跌破9 EMA仍清仓。'
          '以后交易日沿用引擎保守顺序，分批均为原始仓位15%。原话对应③⑤观察、④⑤买点、⑤不追、⑥止损分批离场、⑦仓位市况及反馈；'
          '同日保守口径对应 METHOD 第10节。新引擎字段默认关闭。', '',
          '## 3. 挑中者的 2026（其余未测）', '',
          '| 候选 | 2026 连续账户收益 |', '|---|---|']
    for name in M.CANDIDATES:
        L.append(f"| {name} | {pct(val['full']['by_year']['2026']) if name == selected['chosen'] else '未测'} |")
    r = val['full']['annual']['2026']
    L += ['', f"E3：{r['n']} 笔已平仓 / {r['opened']} 笔开仓，胜率 {r['win']:.1%}，平均赚 / 亏 "
          f"{pct(r['avg_win'])} / {pct(r['avg_loss'])}，平均持有 {r['mean_days']:.2f} 个交易日，年内最大回撤 {r['maxdd']:.1%}。"
          f"另按成功标准的独立验证账户（年初净值1、不带2025仓位）为 {pct(val['validate']['total'])}，"
          f"同池随机中位 {pct(val['validate']['placebo']['median'])}，排位 {val['validate']['placebo']['rank']:.0%}。", '',
          '选择文件先写入，再只评估 E3；比对和看板随后只是固定配置的确定性复放。2026 已被此前 IE47 选股研究使用，'
          '这里是执行候选未用2026择优的检验，不宣称整个系统获得全新的独立样本外。', '',
          '## 4. 三层对照与差距', '',
          '本次固定 E1 执行的三层对照仅看 2024–25，避免额外查看未被选中的 E1 在2026的账户结果。'
          '本人确切日期的买入在当日检查 E1 买点；不满足突破或不追条件的逐笔列出，没有挪日期，也没有把少量公开样本当作其完整账户。', '',
          '| 层 | 2024 | 2025 | 两年合计 |', '|---|---|---|---|']
    for label, row in (('他的确切日期股票 + E1，同样账户约束', three['his_tickers_e1']), ('IE47 股票 + E1', three['ie47_e1'])):
        L.append(f"| {label} | {pct(row['by_year'].get('2024'))} | {pct(row['by_year'].get('2025'))} | {pct(row['total'])} |")
    master = three['master_execution']['profile']
    first2 = (1+master['by_year']['2024'])*(1+master['by_year']['2025'])-1
    L.append(f"| IE47 股票 + master 执行（已有） | {pct(master['by_year']['2024'])} | {pct(master['by_year']['2025'])} | {pct(first2)} |")
    status = Counter(r['status'] for r in three['per_trade'])
    status_labels = dict(bought='买到', no_break_or_invalid_bar='未突破或输入无效',
                         duplicate_same_stock_day='同日同股重复', missing_data='缺数据', chase='追价跳过',
                         account_rejected='账户约束拦截')
    statuses = '；'.join(f'{status_labels.get(k, k)}{n}笔' for k, n in status.items() if k != 'bought')
    L += ['', f"确切日期台账 {three['exact']['all']} 笔，实际买到 {three['exact']['bought']} 笔；{statuses}。"
          '详情见 `e1_three.json`。原 IE47 + master 的全段约−72%含2026，不能直接与上表两年合计当作同区间比较。', '',
          f"差距至少在两层：同样 E1 执行，给本人公开样本票为 {pct(three['his_tickers_e1']['total'])}，给 IE47 股票为 "
          f"{pct(three['ie47_e1']['total'])}，说明仍有选股差距；IE47 换成 E1 比交给 master 的执行少亏，但日K执行仍未逼近本人。"
          '本人样本实际只有12笔，不能把这份部分台账当完整账户，也不能据两条规模不同的路径精确分配因果份额；'
          '该样本胜率41.7%且不足30笔，不能当作通过系统胜率门禁的方案。', '',
          '| 年份 | 入选信号 | E3合规触发上限 | 实际开仓 | 当天止损 | 追价跳过 | 到期未触发 |', '|---|---|---|---|---|---|---|']
    for y, d in diag['annual'].items():
        L.append(f"| {y} | {d['selected']} | {d['eligible']} | {d['opened']} | {d['same_day_stop']} | {d['chase']} | {d['expired']} |")
    upper = diag['annual']['2025']['eligible']
    upper_note = (f'2025年只有{upper}次合规触发，少于本人笔数下限658笔，单改账户名额或仓位不能补出这些触发。'
                  if upper < 658 else '合规触发上限仍高于笔数下限，账户约束造成的差距需另行定位，本次不据结果改参数。')
    L += ['', '合规触发上限是固定画像、三日观察和不追规则已经放行的次数，账户约束只能进一步减少。'+upper_note+
          '2025 年开仓数量和胜率不足，平均亏损约3%又高于他的2.1%。'
          '这里否定的是 IE47画像 × 日K保守入场 × E1/E3离场这一版本。日K无法分辨最低价发生在触发前还是后，本次一律先止损，可能提前洗出；'
          '同时观察期限和不追条件会漏掉其公开交易。三层对照的样本和缺失均保留，不能据此否定他的方法。'
          f"已核对挑中版本全部 {diag['exact_entry_checks']} 笔的入场价、原始止损与同一入场函数完全一致；头部五笔执行记录留在诊断 JSON。", '',
          '## 5. 成功标准、门禁及看板', '', '| 成功标准 | 结果 | 证据 |', '|---|---|---|']
    labels = dict(gate='四项工程门禁', count='逐年笔数', behaviour='公开交易行为', years='逐年收益距离',
                  placebo='全段超过随机中位', validate='验证段超过随机中位', **{'not two': '去掉最大两笔后仍超过随机中位'})
    yr = val['full']['annual']
    evidence = dict(gate=f"四项通过；{val['full']['trades']}笔平仓，胜率{val['full']['win']:.1%}",
                    count=f"2024：{yr['2024']['n']}对423；2025：{yr['2025']['n']}对940，后者少{1-yr['2025']['n']/940:.0%}",
                    behaviour=f"2025胜率{yr['2025']['win']:.1%}对22%，平均亏损{pct(yr['2025']['avg_loss'])}对−2.1%，超出±30%",
                    years='2024、2025收益对数距离约1.13、2.91，均大于0.3',
                    placebo=f"全段{pct(val['full']['total'])}，随机中位{pct(val['full']['placebo']['median'])}",
                    validate=f"独立验证账户{pct(val['validate']['total'])}，随机中位{pct(val['validate']['placebo']['median'])}",
                    **{'not two': f"去掉两笔后{pct(val['full']['drop2'])}，随机中位{pct(val['full']['placebo']['median'])}"})
    for key, ok, why in val['success']:
        L.append(f"| {labels[key]} | {'通过' if ok else '未通过'} | {evidence[key]} |")
    L += ['', '成功标准逐年调用 `success.judge`，再合并两年的结论；缺失目标没有补造。'
          '2025 年在全段报告里有一笔跨年平仓，因此已平仓数为449，训练截断时为448。', '',
          '四项门禁的数据、截断、每笔实际成交区间和胜率均通过；`compare run us martin_luk` 同时运行原冻结版和新研究版。'
          'R74 + S7的三年收益与任务前比对表逐位相同；新版本与唯一一次验证结果也逐位相同（`e1_engine_compatibility.json`）。'
          '看板的冻结期复放逐年与同配置、同代码比对表核对。', '']
    for mode in ('frozen', 'live', 'provisional'):
        s = smoke[mode]
        status_text = dict(passed='通过', unavailable='数据不足', skipped='按任务书跳过')[s['status']]
        L.append(f"- {mode}：{status_text}。" +
                 (f"截止 {s['last_day']}，回放核对逐年一致，买入 {len(s['buys'])}、卖出/减仓 {len(s['sells'])}、持仓 {len(s['holdings'])}。"
                  if mode == 'frozen' and s['status'] == 'passed' else s.get('reason', '原始输入缺失，明细如下。')))
    info = smoke['live']['inventory']
    L += ['', f"live 日线缓存到 {info['last_day']}，完整比较范围 {info['scope']} 只；当日期权量仅有 "
          f"{info['option_available']}/{info['scope']}，缺 {info['option_missing']} 只；QQQ 缺 {len(info['qqq_missing'])} 个交易日。"
          '现有完整 QQQ 基准到2026-10-16，补齐它也不能替代缺失的期权量。两项缺失均已测试为拒绝生成部分名单。'
          '任务书禁止为缺字段新取数据，live冒烟只允许协议第4节范围内补数；因此本次跳过完整当日与真实盘中输出，未伪造快照、未改比较范围、未删条件或用旧值顶替。'
          '已经验证可运行的是截止冻结末日的完整复放，702晚与原IE47完全一致；它不替代今天名单。'
          '缺少完整当日统计，无法量出今天某个替代名单相对真实完整名单的偏差，不能声称偏差为0。'
          '本次没有采用删字段、缩范围或旧值填补等变体；若决定采用这些变体，需要另行预登记并在可核对数据上量名单变化。'
          '若要今天完整运行，仍需按用户决定补齐 QQQ 及完整范围的当日统计。', '',
          '## 6. 文件、验证与复现', '',
          '新增：`notes/PREREG_E1_CN.md`；`ie47_e1.py`、`ie47_audit.py`、`e1_research.py`、`e1_board_smoke.py`、`e1_report.py`；'
          '`trader_data/supplemental.py`；`trader_replication/tests/test_martin_ie47_e1.py`、`tests/test_ie47_registration.py`、'
          '`martin_luk/tests/test_ie47_e1.py`、`trader_data/tests/test_supplemental.py`；'
          '`reports/ie47_profile.json`、`e1_selection.json`、`e1_candidates.json`、`e1_selected.json`、`e1_validation.json`、'
          '`e1_three.json`、`e1_board_smoke.json`、`e1_execution_diagnostics.json`、`e1_engine_compatibility.json`、`e1_checks.json`及本报告。', '',
          '修改：`trader_replication/system.py`（两个默认关闭的执行字段）、`study.py` / `runner.py`（E1入场日已生效的离场线显示）、'
          '`standard_indicators.py`（按需复用现有指标组）、`systems.py` / `compare.py` / `trader_screens/scan.py`（独立版本登记和选择）；'
          'Martin、数据层、看板的 README；`.gitignore`（忽略工作缓存）；比较输出 `compare.json` / `COMPARISON_CN.md`。'
          '原工作区已有修改均保留，不把它们计作本次实现。', '',
          '标准指标源码指纹变化后，重新运行既有 `verify_legacy`：44项旧缓存值一致，price仍核对真实未复权收盘。'
          '旧兼容性缓存先按原字节归档到工作目录，再生成新的验证缓存；未修改 IE47 既有拟合、scorecard或历史收益报告。'
          '旧 IE21 按源码定位引擎的入口保留，IE21与E1的相关时点测试均通过。', '',
          '| 测试目录 | 结果 |', '|---|---|']
    for name, row in checks.items():
        detail = next((line for line in row['summary'] if line.startswith('Ran ')), '')
        if any('expected failures=' in line for line in row['summary']):
            detail += '（含1项原有预期失败）'
        if any('skipped=' in line for line in row['summary']):
            detail += '（含1项原有数据条件跳过）'
        L.append(f"| {name} | {'通过' if row['ok'] else '未通过'}；{detail} |")
    L += ['', '首次密钥保护安装器因已配置主目录的同版 hooks 而拒绝覆盖；原 hooks 保留，没有绕过。'
          'custody 的真实密钥扫描测试独立运行通过；测试入口取消了会妨碍 Go 扫描器预留虚拟地址的地址空间上限，重研究进程仍有1.5GB硬限制，测试另记录实际常驻峰值。', '',
          '所有 Python 使用指定虚拟环境、`nice -n 10`、单线程 BLAS、UTF-8；重计算串行，逐股票/日期分块，未构造大规模 N×N 矩阵。'
          '实测最高常驻内存约965 MiB，测试子进程最高约237 MiB；最终磁盘余量约4.9GB。'
          '资源与详细日志留在 `reports/e1_work/`。本次改动的差异格式检查通过；全工作区检查还提示原有 `MARTIN_LUK_CN.md` 第93行末尾空行，未改动该文件。', '',
          '只读运行与复现命令见本目录 README。候选选择、验证都防止覆盖已存结果；正常查看使用登记版本，不能重跑选择后再改参数。']
    (REPORTS/'E1_CN.md').write_text('\n'.join(L)+'\n', encoding='utf-8')
    progress('Chinese delivery report rendered')


if __name__ == '__main__':
    resource.setrlimit(resource.RLIMIT_AS, (1_500_000_000, 1_500_000_000))
    render()
