"""Render M1's persisted account results, per-leg comparisons and completion record."""
from __future__ import annotations

import csv
import json
from pathlib import Path
import re

from . import m1_research as M

OUT, HOME = M.OUT, M.HOME

DESCRIPTIONS = {
    'B': '长期强势 B 并列', 'B_reclaim': 'B 只留均线收回', 'E10': '并列贴线日内跨 9 EMA',
    'E11': '并列跳空支撑握手', 'parallel': '并列全部日 K 触发', 'reclaim': '并列均线收回',
    'reset': '支撑/周线事件重置', 'queue': '成交层排队、再试让位',
    'structure2': '结构确认，2倍基准股数/50%', 'structure3': '结构确认，3倍/50%',
    'structure3_75': '结构确认，3倍/75%', 'structure4': '结构确认，4倍/50%',
    'H21A': '确认即沿21 EMA', 'R74_exit': '10R减30%＋21 EMA',
    'R74': '完整R74仓位离场', 'P90': '成交额前10%替换池', 'P90_near': '前10%且贴均线替换池',
}


def pct(x):
    return '—' if x is None else f'{x*100:.1f}%'


def amount(x):
    return '—' if x is None else f'{x:+.3f}'


def table(lines, columns, rows):
    lines.extend(['', '| '+' | '.join(columns)+' |', '| '+' | '.join('---' for _ in columns)+' |'])
    lines.extend('| '+' | '.join(map(str, row))+' |' for row in rows)
    lines.append('')


def annual_cells(name, year, row):
    c = row['coverage']['including_censored']
    return [name, year, pct(row['cap_equity']), pct(row['purity_gross']),
            f'{c["covered"]}/{c["n"]}', pct(row['capture_total']), row['top10_his_leg'],
            amount(row['H']), amount(row['O']), pct(row['account_return']), pct(row['maxdd']),
            row['n_trades'], pct(row['win']), f'{row["target_count"]}/5']


COLUMNS = ['方案', '年', '他的段/权益日', '段毛利/全部毛利', '早买段', '段吃到', '前10赢单中他的段',
           'H段内pnl', 'O其他pnl', '账户收益', '年内回撤', '开仓笔数', '平仓胜率', '五线通过']


def completion():
    protocol = M.read(OUT/'protocol.json')
    tests = {}
    for name in ('martin_luk', 'trader_replication', 'custody'):
        path = OUT/f'test_{name}.log'
        text = path.read_text(encoding='utf-8') if path.exists() else ''
        match = re.search(r'Ran (\d+) tests? in', text)
        outcome = re.search(r'^OK(?: \([^\n]+\))?$', text, re.MULTILINE)
        tests[name] = dict(ok=bool(match and outcome), count=int(match[1]) if match else None,
                           outcome=outcome[0] if outcome else '未通过或未运行', log=path.name)
    protected = {p: M.sha(M.ROOT/p) == digest for p, digest in protocol['protected_sha256'].items()}
    defaults = M.read(OUT/'defaults.json')
    native = M.read(OUT/'native_checks.json')
    selected = M.read(OUT/'selection.json')
    registry = M.read(OUT/'candidates.json')
    validation = M.read(OUT/'validation_complete.json') if (OUT/'validation_complete.json').exists() else None
    truncation = M.read(OUT/'truncation.json') if (OUT/'truncation.json').exists() else None
    policy = (bool(validation and truncation and truncation['ok']) if selected['chosen'] else
              validation is None and not (OUT/'validation_started.json').exists())
    compatibility = M.read(OUT/'source_compatibility.json') if (OUT/'source_compatibility.json').exists() else None
    expected_code = compatibility['corrected_code_sha256'] if compatibility else registry['code_sha256']
    source_checks = {p: M.sha(M.ROOT/p) == digest for p, digest in expected_code.items()}
    if compatibility:
        assert compatibility['registered_code_sha256'] == registry['code_sha256']
        assert compatibility['registry_sha256'] == M.sha(OUT/'candidates.json')
        assert compatibility['prereg_sha256'] == M.sha(M.PREREG)
    full_defaults = M.read(OUT/'defaults_full.json') if (OUT/'defaults_full.json').exists() else None
    original_bytes = M.read(OUT/'original_account_bytes.json') if (OUT/'original_account_bytes.json').exists() else None
    artifacts = M.read(OUT/'artifact_audit.json') if (OUT/'artifact_audit.json').exists() else None
    files = [Path(M.__file__), Path(__file__), HOME/'tests/test_m1.py', M.PREREG,
             M.ROOT/'studies/trader_replication/system.py', M.ROOT/'studies/trader_replication/study.py']
    code_sha = {str(p.relative_to(M.ROOT)): M.sha(p) for p in files}
    result = dict(ok=all(t['ok'] for t in tests.values()) and all(protected.values()) and
                  all(all(v.values()) for v in defaults.values()) and all(native.values()) and policy and
                  registry['prereg_sha256'] == M.sha(M.PREREG) and all(source_checks.values()) and
                  bool(artifacts and artifacts['ok']) and bool(original_bytes and original_bytes['ok']) and
                  (all(all(r.values()) for r in full_defaults.values()) if selected['chosen'] and full_defaults else
                   selected['chosen'] is None),
        tests=tests, original_ledgers_bitwise=defaults, native_master_prefix_bitwise=native,
        protected_unchanged=all(protected.values()), protected_checks=protected,
        preregistration_unchanged=registry['prereg_sha256'] == M.sha(M.PREREG),
        selected_code_unchanged=all(source_checks.values()), selected_code_checks=source_checks,
        source_correction=compatibility,
        original_full_ledgers_bitwise=full_defaults, artifact_audit=artifacts,
        original_account_files=original_bytes,
        diagnostic_runs=len(M.read(OUT/'diagnostics.json')), candidates=len(registry['specs']),
        selected=selected['chosen'], validation=validation, truncation=truncation,
        validation_policy_passed=policy, independent_out_of_sample=False,
        network_disabled=True, new_data=False, git_commit=False, registration_changed=False, board_changed=False,
        B_line_write_boundary='all research writers guarded to m1_work plus M1 report/preregistration',
        code_sha256=code_sha,
        resource_records={str(p.relative_to(OUT)): M.read(p) for p in
            [OUT/'diagnostics_complete.json', *sorted(OUT.glob('*/master_prepared.json')),
             *sorted(OUT.glob('*/ie_prepared.json'))]})
    runs = M.read(OUT/'candidates_train.json')
    result['training_all_five_targets'] = {n: all(r['targets']['passed'] for r in a['years'].values())
                                           for n, a in runs.items()}
    result['strategy_success'] = any(result['training_all_five_targets'].values())
    result['research_completed'] = result['ok']
    if (OUT/'r74_cap_correction_complete.json').exists():
        result['implementation_correction'] = M.read(OUT/'r74_cap_correction_complete.json')
        result['ok'] = result['ok'] and result['implementation_correction']['ok']
        result['research_completed'] = result['ok']
    # Keep the completion record compact: calendars/codes are recorded in prepared metadata already.
    for r in result['resource_records'].values():
        r.pop('days', None)
        r.pop('codes', None)
        r.pop('sources', None)
    M.write('completion.json', result)
    return result


def leg_cell(leg):
    if not leg['any']:
        return '未买'
    return f'{"早" if leg["covered"] else "晚"}；{pct(leg["capture_total"])}；{amount(leg["pnl"])}'


def export_legs():
    rows = []
    for category in ('baseline', 'diagnostics', 'candidates'):
        for path in sorted((OUT/category).glob('*/metrics.json')):
            result = M.read(path)
            for g in result['legs']:
                if g['year'] not in ('2024', '2025'):
                    continue
                rows.append(dict(category=category, account=path.parent.name, key=g['key'], code=g['code'],
                    year=g['year'], early=g['covered'], any=g['any'], H=g['pnl'], capture=g['capture_total'],
                    first_fill=g['first_fill'], offset=g['offset'], lots=g['lots'], trades=g['n_trades']))
    with (OUT/'all_leg_comparisons.csv').open('w', newline='', encoding='utf-8') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    M.write('all_leg_comparisons.json', rows)


def main():
    done = completion()
    diagnostics, candidates = M.read(OUT/'diagnostics.json'), M.read(OUT/'candidates_train.json')
    registry, selection = M.read(OUT/'candidates.json'), M.read(OUT/'selection.json')
    baseline = {n: M.read(OUT/f'baseline/{n}/metrics.json') for n in ('IE47_C062', 'master_C062', 'native_master')}
    chosen = selection['chosen']
    focus = chosen or next(iter(registry['specs']))
    focus_metrics = M.read(OUT/f'candidates/{focus}/metrics.json')
    all_pass = [n for n, r in candidates.items() if all(x['targets']['passed'] for x in r['years'].values())]
    lines = ['# M1：把 master 的机制移入日 K 账户', '']
    if not all_pass:
        lines.append('本轮没有候选在 2024、2025 两年同时完成五条目标线。已完成单机制诊断与最多五个组合的固定评测；不能据此宣布复刻成功或替换 master。')
    else:
        lines.append('训练段同时完成五条目标线的候选：'+ '、'.join(all_pass)+'。是否达到整体目标还须看固定 2026 检查和账户收益对照。')
    lines.append('')
    if chosen:
        lines.append(f'按任务书的资格与排序选中 **{chosen}**；合格候选为 '+ '、'.join(selection['eligible'])+'。'
                     '这里的资格仅表示年度笔数、胜率，以及两年 H 和资金占用不低于 master+C062，不代表五条目标线已全过。')
        cr = candidates[chosen]['years']
        nr = baseline['native_master']['years']
        lines += ['', f'{chosen} 的2024/2025收益为 {pct(cr["2024"]["account_return"])}/{pct(cr["2025"]["account_return"])}，'
                  f'登记 master 为 {pct(nr["2024"]["account_return"])}/{pct(nr["2025"]["account_return"])}。'
                  '因此相对 master+C062 的资格改善，不等于达到“不低于登记 master”的整体目标。', '',
                  f'资金纯度为 {pct(cr["2024"]["cap_equity"])}/{pct(cr["2025"]["cap_equity"])}，'
                  f'毛利纯度为 {pct(cr["2024"]["purity_gross"])}/{pct(cr["2025"]["purity_gross"])}，'
                  '与50%/60%的要求仍有明显距离。H很大或O为负，也不能替代这两条线：O内的盈利和亏损可能互相抵消，毛利仍要逐片计算。']
    else:
        lines.append('**没有合格候选，因此没有测 2026，也没有启动 2026 防未来检查。** 下表保留所有失败项，没有临时放宽门槛。')
    lines += ['', '## 口径与本轮边界', '',
        '采用 Y1 的 `mainleg.summary_account`、FIFO lot 分账与唯一冻结的 48 段；本轮训练主分母为 2024 的 9 段、2025 的 22 段。段标签只在账户模拟完成后评测使用，不参与资格、排序、买卖或仓位。', '',
        '所有训练账户统一从 2024-01-02 连续跑到 2025-12-31，年末仍持有的仓仅估值。没有让训练仓继续跑入 2026。2025 年底三段仍使用冻结段的原始峰值与总涨幅作为尺子，但本轮实际持有和 pnl 截止 2025 年末；它们的后续收益没有提前计入。Y1 原主表是三年连续台账，因此本表的 2025 数字可能与其不同。', '',
        '资金占用是每日段内名义/本日权益的自然年平均，现金日计入分母；两年资格按全部交易日加权。H、O 按交易首次开仓年归属，段吃到按段年与 lot 潜力加权，不能将 H/O 直接与账户年度收益相减。毛利分子、分母都使用同一 FIFO/时间切片。前十赢单排除年末估值，只有 H 净贡献大于零才计数。回撤为各自然年从年初权益起算的峰谷回撤。', '',
        '底线为每年开仓至少 52 笔、已平仓胜率不超过 35%；五条目标是资金≥50%、毛利≥60%、早买至少一半段、段吃到≥50%、前十赢单至少五笔来自他的段。原始未决缺行情记录沿 Y1 保留，没有拉新数据。', '',
        'C062 按实码执行：探仓风险参数 0.25%，灾难止损按 2R 定尺寸，确认目标为 K2 基准股数的 4 倍且单票≤50%，达到 5R 后才切 21 EMA。本轮 2倍/3倍指同一个 K2 基准股数；风险总预算仍由原引擎约束，75% 只是上限，不保证实际加得上去。结构证实是当晚越前高或新收回支撑，同时收在 9 EMA 上且 9>21；仍须盈利收盘才能首次加仓。', '',
        '登记 master 是原 R74+S7 多空账户，空头盈利/亏损及真实借券费全部计入 O；资金的权益分母包含空头对权益的真实影响。另两个基准和候选是多头账户，完整 R74 执行替换保留其风险反馈、市场倍率、无 11 仓上限和 10/20R 加仓，未添加新空头。R74沿其原实现使用float64行情运算，C062保留原精度；原登记与看板均未更改。C062各替换均保留原IE47池宽和QQQ的市况缩放，以隔离所改机制。', '',
        '## 三组基准（相同训练截止）']
    table(lines, COLUMNS, [annual_cells(n, y, r) for n, a in baseline.items() for y, r in a['years'].items()])
    lines += ['## 第一步：一次铺开的单机制诊断', '',
        '共 17 种替换×两种底版=34 个账户，以下仅诊断，未从单项直接选最终版本。IE 为 IE47+C062，M 为 master+C062。每个账户的两年原台账、权益、拒绝记录、FIFO lots 和逐段结果均在 `m1_work/diagnostics/`。全部逐段对照另存 `all_leg_comparisons.csv/json`。', '',
        'master 已含 B、E10、E11 并列触发并逐日重新扫描，没有十晚点名冷却；再次加入 B、E10、E11、全部并列和事件重置会保持原样。其 B 收回变体只收紧 B 独有信号，并在原四名截取之前处理；收回触发变体保留越前高或新支撑收回的信号。IE 事件重置会在当晚支撑收回/周线升级时解除点名冷却、重置有效观察，结构跌破 21 EMA 后移出；没有永久挂着几个月的旧名单。', '',
        '成交层排队在 master 侧取消成交额预截四名，将完整可成交信号交给引擎按成功成交计每天四笔，同票已持会跳过；新信号排在再试之前，再试最多两仓且未证实仓可以让位。原 C062 不生成再试，因此IE单机制中没有真实让位；排序改为先观察日、再原名次，仍可能改变成交。过滤池替换保留 IE 原周成交额范围、画像分数、每晚三名和冷却，只替换其 H4/期权量/离低点等四层筛选；P90 用全流动性范围的成交额前10%且 ADR≥3%，P90_near 再要求距9/21 EMA至少一条不超过1 ADR。master 侧保留原触发系统，仅替换流动性池。']
    rows = []
    for basis, label in (('ie', 'IE'), ('master', 'M')):
        for name in M.DIAGNOSTICS:
            for y, r in diagnostics[f'{basis}_{name}']['years'].items():
                rows.append(annual_cells(label+' '+DESCRIPTIONS[name], y, r))
    table(lines, COLUMNS, rows)
    lines += ['## 第二步：冻结的端到端候选', '',
        f'预登记文件：`notes/{M.PREREG.name}`；SHA256：`{registry["prereg_sha256"]}`。写完后未修改。候选来自第一步的结构性差异，最多五个，没有做参数网格。']
    if done['source_correction']:
        lines += ['', '**冻结后的实现修正，参数未变。** 最初的R74适配仍带着C062报价元组内的30%探仓上限，'
                  '与预登记写明的R74自身50%单票上限不符。2026开始前移除了这个残留；新增真实账户回归测试证明首仓确实能达到50%。'
                  '原两组R74单机制、五个组合及旧前缀检查完整封存在 `corrections/r74_probe_cap/`，'
                  '原源码备份的SHA与冻结指纹逐值一致。受影响的训练结果和前缀均已重算；M1A、M1E的汇总逐值不变。'
                  '预登记和候选配置JSON均未改，未追加候选。`source_compatibility.json`钉住修正前后源码和结果指纹，'
                  '只允许本研究适配文件这一处依赖变化，之后的2026使用修正后的固定源码。'
                  '预登记引用的旧单机制数字保留为当时记录，本报告大表采用修正后的真实R74结果。']
    table(lines, ['候选', '结构性理由', '完整配置', '资格失败项'],
          [[n, registry['reasons'][n], json.dumps(s, ensure_ascii=False),
            '、'.join(selection['failures'][n]) or '合格'] for n, s in registry['specs'].items()])
    table(lines, COLUMNS, [annual_cells(n, y, r) for n, a in candidates.items() for y, r in a['years'].items()])
    base = M.summary(baseline['master_C062'])
    table(lines, ['账户', '两年H合计', '两年资金占用', '较差年五线数', '较差年资金占用', '较差年毛利纯度'],
          [[n, amount(r['H']), pct(r['cap_equity']), min(x['target_count'] for x in r['years'].values()),
            pct(min(x['cap_equity'] for x in r['years'].values())),
            pct(min(x['purity_gross'] or 0. for x in r['years'].values()))]
           for n, r in [('master+C062', base), *candidates.items()]])
    lines += ['资格严格按任务书：两年分别过底线，两年 H 合计及按交易日加权的资金占用均不低于 master+C062；'
              '排序依次是较差年五线通过数、较差年资金占用、较差年毛利纯度、两年 H 合计，完全相同时按候选 ID。'
              '账户收益与登记 master 的差距也保留在表中；没有把较差的账户收益隐藏成“复刻成功”。', '',
              '## 他的段逐段对照（早买；吃到；H）']
    metrics = dict(baseline)
    metrics.update({n: M.read(OUT/f'candidates/{n}/metrics.json') for n in candidates})
    maps = {n: {g['key']: g for g in a['legs']} for n, a in metrics.items()}
    frozen = M.read(HOME/'notes/legs_frozen.json')
    for year in ('2024', '2025'):
        lines += [f'### {year}', '']
        table(lines, ['段（锚点→峰）', *metrics],
              [[f'{g["code"]} {g["first_date"]}→{g["peak_date"]}',
                *[leg_cell(maps[n][g['key']]) for n in metrics]]
               for g in frozen['legs'] if g['first_date'].startswith(year)])
    lines += ['“早/晚”只看该段的首个实际 lot；后续加仓或重试不会重置首笔时钟。未买不写成零收益率；金额单列为零。'
              '所有 34 个单机制的逐段早买与吃到在 `all_leg_comparisons.csv/json`，未只挑盈利段。', '',
              '## 固定的 2026 检查与防未来验证', '']
    if done['validation']:
        lines.append(f'选中 {chosen} 先通过截止 {M.CUT} 的逐笔截断一致与真实未来 OHLC×3、量×2、成交额×6 扰动检查；'
                     '均在重建选股、指标、触发和账户后比较截止日前的点名、信号与真实 execution 事件。随后只测一次 2026 单开与一次连续账户，看完未调候选。2026 已被历史研究多次使用，仅是本轮及格检查。')
        validation = M.read(OUT/'validation.json')
        table(lines, COLUMNS, [annual_cells(name, '2026', r['years']['2026']) for name, r in validation.items()])
        continuous = M.read(OUT/'validation/continuous/metrics.json')
        standalone = M.read(OUT/'validation/standalone/metrics.json')
        vmaps = [{g['key']: g for g in a['legs']} for a in (standalone, continuous)]
        table(lines, ['2026段', '单开：早/吃到/H', '连续：早/吃到/H', '标签截断'],
              [[g['key'], *[leg_cell(v[g['key']]) for v in vmaps], '是' if g['censored'] else '否']
               for g in frozen['legs'] if g['first_date'].startswith('2026')])
    else:
        lines.append('无人达到预登记资格，2026 未运行。没有用 2026 帮助挑选、替换或补测失败候选。')
    lines += ['', '## 差距落在哪一层，以及下一轮', '']
    table(lines, ['重点账户', '年', '上游可早买段/分母', '实际早买', '资金差50%多少点', '毛利差60%多少点',
                  '吃到差50%多少点', '前十还差几笔'],
          [[focus, y, f'{sum(bool(g["offered"]) for g in focus_metrics["funnel"] if g["year"] == y)}/'
                        f'{r["coverage"]["including_censored"]["n"]}',
            r['coverage']['including_censored']['covered'], f'{max(0., .5-r["cap_equity"])*100:.1f}',
            f'{max(0., .6-(r["purity_gross"] or 0.))*100:.1f}',
            f'{max(0., .5-(r["capture_total"] or 0.))*100:.1f}', max(0, 5-r['top10_his_leg'])]
           for y, r in focus_metrics['years'].items()])
    missing = [g for g in focus_metrics['funnel'] if not g['offered']]
    blocked = [g for g in focus_metrics['funnel'] if g['offered'] and not g['early']]
    lines.append(f'{focus} 在训练段有 {len(missing)} 段连可早买报价都没有，另有 {len(blocked)} 段有报价但首笔实际成交未早买。'
                 '前者应回到过滤池、当晚重新点名和触发的交集；后者要沿 `attempts.jsonl` 查同票旧仓、每日成功成交上限、总敞口与风险。'
                 '单纯提高仓位上限不能填补没有报价的行情段。')
    if (OUT/'selected_funnel.json').exists():
        funnel = M.read(OUT/'selected_funnel.json')
        rs = funnel['missed_early_offer_legs']
        counts = funnel['attempt_reasons']
        table(lines, ['未早买报价的实际处理', '报价次数', '涉及段数'],
              [[reason, n, sum(reason in g['reasons'] for g in rs)] for reason, n in counts.items()])
        lines.append('这些拒绝层来自真实账户记录，而非由最终收益倒推。各段的原报价日期、理由、首次fill与已持同票记录保留在'
                     '`selected_funnel.json`；若没有同票拒绝，不把“同票已持”当成本轮主因。')
    lines.append('')
    lines.append(('当前早期报价已接近完整覆盖，下一轮主攻实际成交排序、旧仓占用与证实后资金预算；'
                  '不要继续扩大已很宽的信号来源。逐段查同票旧仓是否在窗口外开仓、每日四个真实名额先给了谁、'
                  '何时被总敞口拒绝，并用全体事件验证一般化的仓位重评机制。'
                  if len(blocked) > len(missing) else
                  '下一轮先把未产生早期报价的完整段组沿“数据→过滤池→点名→触发→成交”逐层定位。')+
                 '继续保留 master+C062 与登记 master 的账户收益对照；若组合只增加 H 金额、资金和毛利纯度仍远离目标，应先收敛机会来源及无效探仓，不能把它升格为完成复刻。'
                 '规则仍只依赖日 K，不使用段名作策略特征。')
    lines += ['', '## 工程验收与复算', '',
        '共享引擎只新增默认关闭的 `proof_confirm_signal`，并接入通用指标输入；未启用时，C062、S1、master+C062 的原训练逐笔交易字段和权益逐值相等。合格者防未来检查通过后，另用原三年完整账户做兼容回放，仍逐值相等；这不是候选选择或新增验证。比较仅排除旧报告后加的origin/observed/attempt评测注释；原九份台账、权益和统计文件另与Y1冻结SHA核对，连同注释在内的原文件字节均未改变。登记 master 的原 D1 连续账户在训练截止前的权益与真实执行事件也逐值相等。', '']
    lines += ['逐笔成交价按日K源文件float32的两ULP存储精度核对；最初比这个存储精度更紧的检查把小数止损与已舍入日低之间的微小误差误报，原日志保留。'
              '该核对修正没有改动成交、台账或策略。FIFO交易pnl、H+O和融资/期末费用另外逐值对账。', '']
    table(lines, ['测试组', '测试数', '结果', '日志'], [[n, r['count'], r['outcome'], r['log']] for n, r in done['tests'].items()])
    peaks = [r.get('peak_rss_mib', 0.) for r in done['resource_records'].values()]
    lines += [f'准备及训练评测的峰值 RSS 为 {max(peaks):.1f} MiB。重计算使用任务规定的 systemd scope（CPUQuota=60%、MemoryMax=900M）及单进程单线程。'
              '报价拒绝逐条流式写 JSONL，计算输入 mmap，替换池画像按股票计算；没有构造股票×股票矩阵或无界保留全市场拒绝日志。', '',
              '工件包括 `protocol.json`、`defaults.json`、`native_checks.json`、`diagnostics.json`、`candidates.json`、'
              '`candidates_train.json`、`selection.json`、每组账户的 trades/curve/rules/metrics/reconciliation、'
              '`all_leg_comparisons.csv/json`、三组测试日志与 `completion.json`。存在合格者时另含截断/扰动与单开/连续 2026 文件。', '',
              '未联网、未拉新数据、未提交 git、未改登记/看板、未写 F1 文件。已有密钥钩子已核对；安装器拒绝覆盖已有 hooksPath，没有绕过钩子。'
              '当前工作树原有大量其他修改，本轮保护清单只核对本次依赖及登记/看板，F1 并行工作的改动不归到本轮。', '',
              '```bash',
              'RUN=(systemd-run --scope -p CPUQuota=60% -p MemoryMax=900M -q env OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 PYTHONDONTWRITEBYTECODE=1 /opt/opend-us-options/.venv/bin/python)',
              '"${RUN[@]}" -m studies.martin_luk.m1_research freeze',
              '"${RUN[@]}" -m studies.martin_luk.m1_research prepare-master',
              '"${RUN[@]}" -m studies.martin_luk.m1_research prepare-ie',
              '"${RUN[@]}" -m studies.martin_luk.m1_research diagnose',
              '"${RUN[@]}" -m studies.martin_luk.m1_research native',
              '# 写一次 PREREG_M1_CN.md 和 candidates.json 后：candidates；合格者才做 prefix、validate。',
              '# 每阶段有开始记录，正式评测拒绝覆盖。只重新渲染报告：',
              '"${RUN[@]}" -m studies.martin_luk.m1_report', '```', '']
    export_legs()
    (HOME/'reports/M1_CN.md').write_text('\n'.join(lines), encoding='utf-8')
    print(f'M1 report written; completion={done["ok"]}; selected={chosen}')


if __name__ == '__main__':
    M.offline()
    main()
