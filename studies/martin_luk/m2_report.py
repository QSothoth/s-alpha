"""Render M2 from immutable account artifacts and audit the delivered result."""
from __future__ import annotations

from collections import Counter
import csv
import difflib
import json
from pathlib import Path
import re

import numpy as np

from . import m2_research as M
from .m1_report import COLUMNS, annual_cells, amount, leg_cell, pct, table

OUT, HOME = M.OUT, M.HOME

DESCRIPTIONS = {
    'G1_rank': 'G1画像重排', 'G1_rotation': '重排后换弱探仓', 'risk_100': '高分1%/其他0.25%',
    'risk_150': '高分1.5%/其他0.25%', 'gross_140': '总敞口1.4倍', 'gross_400': '总敞口4倍',
    'probes_qqq': '低分探仓仅QQQ强时开', 'probes_one': '低分探仓每天只报价1只',
    'equity_ma20': '20日权益均线下新风险减半', 'F2_G1': '只用F2 G1＋master触发',
    'F2_G3': '只用F2 G3＋master触发', 'F2_G1_union': 'F2 G1并入master',
}


def metrics(directory):
    return M.read(directory/'metrics.json')


def reference_2026():
    """Attribute existing complete reference ledgers; never simulate a second candidate validation."""
    path = OUT/'reference_2026.json'
    if path.exists():
        return M.read(path)
    rows = {}
    for label, directory in [('M1B单开', HOME/'reports/m1_work/validation/standalone'),
                             ('M1B连续', HOME/'reports/m1_work/validation/continuous'),
                             ('master+C062连续', HOME/'reports/m1_work/compatibility/master_C062')]:
        rows[label] = metrics(directory)['years']['2026']
    A = M.arrays(HOME/'reports/m1_work/validation_prepared')
    A['close'] = A['close'].astype(float)  # Native R74 borrow sums use its original float64 arithmetic.
    curve = M.read(HOME/'reports/d1_work/master_curve.json')
    trades = M.read(HOME/'reports/d1_work/master_trades.json')
    r = M.read(HOME/'reports/m1_work/baseline/native_master/rules.json')
    rules = M.Y.Rules(**r)
    result = M.M.measure(A, trades, np.asarray(curve['equity']), np.asarray(curve['days']),
                         rules, (M.TRAIN[0], M.VALID[1]))
    M.write('reference_native_full_metrics.json', result)
    rows['登记master连续'] = result['years']['2026']
    M.write(path, rows)
    return rows


def paired_funnel(choice):
    data = metrics(OUT/'candidates'/choice)
    items = []
    for g in data['funnel']:
        matches = []
        offered = set(g['offered'])
        with (OUT/'candidates'/choice/'attempts.jsonl').open() as f:
            for line in f:
                r = json.loads(line)
                if r['code'] == g['code'] and r['day'] in offered:
                    matches.append(r)
        original = next(x for x in metrics(HOME/'reports/m1_work/candidates/M1B')['funnel'] if x['key'] == g['key'])
        items.append(dict(g, upstream_M1B=original['offered'], actual_attempts=matches))
    M.write('selected_funnel.json', items)
    reasons, affected = Counter(), {}
    for g in items:
        if not g['early']:
            for r in g['actual_attempts']:
                reasons[r['reason']] += 1
                affected.setdefault(r['reason'], set()).add(g['key'])
    return items, [(r, n, len(affected[r])) for r, n in reasons.items()]


def artifacts():
    A = M.arrays(HOME/'reports/m1_work/validation_prepared')
    di = {str(d): i for i, d in enumerate(A['days'])}
    ci = {str(c): j for j, c in enumerate(A['codes'])}
    checked, executions, errors = 0, 0, []
    for path in sorted(OUT.rglob('trades.json')):
        if path.is_relative_to(OUT/'corrections'):
            continue
        directory = path.parent
        trades, curve, rules = M.read(path), M.read(directory/'curve.json'), M.read(directory/'rules.json')
        checked += 1
        for t in trades:
            j = ci[t['code']]
            for e in t['executions']:
                d = di[e['time']]
                lo, hi = float(A['low'][d, j]), float(A['high'][d, j])
                tol = 2*max(abs(float(np.spacing(np.float32(lo)))), abs(float(np.spacing(np.float32(hi)))))
                executions += 1
                if not lo-tol <= e['price'] <= hi+tol:
                    errors.append(dict(file=str(path.relative_to(OUT)), code=t['code'], event=e, range=[lo, hi]))
        rec = M.read(directory/'reconciliation.json')
        if abs(rec['error']) >= 1e-9:
            errors.append(dict(file=str(path.relative_to(OUT)), reconciliation=rec))
        if not all(np.isfinite(curve['equity'])):
            errors.append(dict(file=str(path.relative_to(OUT)), nonfinite_equity=True))
    result = dict(ok=not errors, accounts=checked, executions=executions, violations=errors[:10],
                  tolerance='two ULP of the stored float32 daily high/low', financing_checked=True)
    M.write('artifact_audit.json', result)
    assert result['ok'], result
    return result


def completion(audit):
    protocol, registry = M.read(OUT/'protocol.json'), M.registry_check()
    protected = {p: M.sha(M.ROOT/p) == digest for p, digest in protocol['protected'].items()}
    tests = {}
    for n in ('martin_luk', 'trader_replication', 'custody'):
        path = OUT/('test_'+n+'.log')
        text = path.read_text()
        match = re.search(r'Ran (\d+) tests? in', text)
        outcome = re.search(r'^OK(?: \([^\n]+\))?$', text, re.MULTILINE)
        tests[n] = dict(ok=bool(match and outcome), count=int(match[1]) if match else None,
            result=outcome[0] if outcome else 'FAILED', sha256=M.sha(path), log=path.name)
    selection = M.read(OUT/'selection.json')
    train, full = M.read(OUT/'compatibility.json'), M.read(OUT/'full_compatibility.json')
    trunc = M.read(OUT/'truncation.json') if (OUT/'truncation.json').exists() else None
    validation = M.read(OUT/'validation_complete.json') if (OUT/'validation_complete.json').exists() else None
    policy = bool(trunc and trunc['ok'] and validation) if selection['chosen'] else validation is None
    resource_records = {p.name: M.read(p) for p in sorted(OUT.glob('profile_*_complete.json'))}
    resource_records['diagnostics'] = M.read(OUT/'diagnostics_complete.json')
    observation = M.read(OUT/'resource_observation.json')
    log_peaks = [float(v) for p in OUT.glob('*.log') for v in re.findall(r'; ([0-9.]+) MiB\]', p.read_text())]
    result = dict(ok=all(protected.values()) and all(t['ok'] for t in tests.values()) and train['ok']
        and full['ok'] and audit['ok'] and policy, tests=tests, selected=selection['chosen'],
        preregistration_unchanged=registry['prereg_sha256'] == M.sha(M.PREREG),
        source_sha256=registry['code_sha256'], prereg_sha256=M.sha(M.PREREG),
        protected_unchanged=all(protected.values()), protected_checks=protected,
        original_training_ledgers_bitwise=train, original_complete_ledgers_bitwise=full,
        collapse_original_replays=M.read(OUT/'collapse.json')['original_replay'],
        collapse_supplement=M.read(OUT/'E_supplement.json') if (OUT/'E_supplement.json').exists() else None,
        diagnostic_correction=M.read(OUT/'diagnostic_correction.json'),
        artifact_audit=audit, truncation=trunc, validation=validation, validation_policy_passed=policy,
        diagnostic_arms=len(M.DIAGNOSTICS), endpoint_candidates=len(M.CANDIDATES),
        strategy_success=False, research_completed=False, independent_out_of_sample=False,
        network_disabled=True, new_data=False, git_commit=False, registration_changed=False, board_changed=False,
        U1_write_boundary='all research writers restricted to m2_work; no U1 edits',
        resources=dict(cpu='60%', memory='900M', threads=1, python='/opt/opend-us-options/.venv/bin/python'),
        resource_records=resource_records, resource_observation=observation,
        peak_rss_mib=max([r.get('peak_rss_mib', 0.) for r in resource_records.values()] + log_peaks))
    candidates = M.read(OUT/'candidates_train.json')
    native = metrics(HOME/'reports/m1_work/baseline/native_master')
    all_targets, beats_master = {}, {}
    for n, r in candidates.items():
        all_targets[n] = all(x['targets']['passed'] for x in r['years'].values())
        beats_master[n] = all(r['years'][y]['account_return'] >= native['years'][y]['account_return']
                              for y in ('2024', '2025'))
    result['training_all_targets'] = all_targets
    result['training_not_worse_than_registered_master'] = beats_master
    result['strategy_success'] = any(all_targets[n] and beats_master[n] for n in candidates)
    result['research_completed'] = result['ok']
    M.write('completion.json', result)
    assert result['ok'], {k: v for k, v in result.items() if k in ('ok', 'tests', 'protected_unchanged')}
    return result


def main():
    audit = artifacts()
    done = completion(audit)
    choice = done['selected']
    lines = ['# M2：画像排序、资金让位与F2选股的实际账户检验', '']
    selected = M.read(OUT/'selection.json')
    runs = M.read(OUT/'candidates_train.json')
    if choice:
        rows = runs[choice]['years']
        lines += [f'**按任务书的研究资格与排序选中{choice}，但本轮没有完成复刻目标，也没有可替换登记master的方案。** '
            f'选中者2024/2025资金占用为{pct(rows["2024"]["cap_equity"])}/{pct(rows["2025"]["cap_equity"])}，'
            f'毛利纯度为{pct(rows["2024"]["purity_gross"])}/{pct(rows["2025"]["purity_gross"])}；仍低于50%/60%。', '']
        lines += [f'{choice}的账户收益为{pct(rows["2024"]["account_return"])}/{pct(rows["2025"]["account_return"])}，'
            'M1B为209.1%/139.2%，登记master为297.3%/243.6%。'
            '两年H增加和回撤收窄，没有同时改善毛利纯度与吃到比例，2025收益也退步；不把研究入围写成整体改善。', '']
        val = M.read(OUT/'validation.json')
        single, continuous = (val[n]['years']['2026'] for n in ('standalone', 'continuous'))
        lines += [f'固定2026检查的单开收益{pct(single["account_return"])}、连续账户当年收益{pct(continuous["account_return"])}，'
            f'但资金纯度只有{pct(single["cap_equity"])}、早买{single["coverage"]["including_censored"]["covered"]}/17，'
            f'毛利纯度为{pct(single["purity_gross"])}/{pct(continuous["purity_gross"])}，两种账户五线都为0/5。'
            '收益提高仍未解决钱花在他的段上的目标。', '']
    else:
        lines += ['**五个候选均未过相对M1B的资格，本轮不选中方案、不打开2026。** 失败记录完整保留。', '']
    lines += ['M1C–E崩溃的主因是宽入口与结构排序共同挤占名额和敞口，原台账逐笔重放一致，未发现需要更正M1历史结果的实现错误。'
        '直接把G1画像排序放到master成交队列前面，也没有把大资金与大盈利转向他的段。'
        '保留master原顺序、在QQQ弱时少开低分探仓，提供了一个可以继续检查的机制；研究入围不等于达到全部目标。', '',
        '## 口径和执行边界', '',
        '训练账户统一从2024-01-02连续至2025-12-31，年底持仓只估值；同表基准沿M1相同训练截止。'
        '段表与FIFO分账完全沿Y1：2024为9段、2025为22段，2026为17段（其中2段截断）。'
        '资金纯度是每日段内仓位/当日权益的自然年均值，含现金日；两年按交易日加权。'
        'H/O金额以初始本金1为单位，按首开仓年归属；段覆盖与吃到按段年，资金按日历年，因此不能将H直接与年度账户收益相减。'
        '前十只算真实平仓赢单、且段内净H为正。', '',
        '段名、本人股票/日期和未来峰值只用于模拟完成后的评测，不参与画像推断、入场、排序、仓位或离场。'
        'G1/G3只读冻结模型，未重新拟合；前一夜分数用于次日收盘队列，池外缺分排最后。'
        '高分为当日报价中有效分数的前3只；低分QQQ开关用前夜QQQ>50EMA且9EMA>21EMA。'
        '风险分层用原低反馈0.5%作倍数基准，高反馈和原指数倍率继续作用，表中1%/1.5%不是每天固定风险。'
        '现有risk_or_gross标签主要是总敞口/最小可下单金额拒绝；原引擎没有额外的全账户止损风险预算上限。', '',
        'F2点名观察五晚，只消费第一个master式日K触发；只用点名替换扫描/观察门槛，E10/E11、窄K破高、前周内包破高、B及已有EP触发沿原算法。'
        'F2独立通道不再重复套master等权指数50日信号过滤；master原通道仍保留，所有通道保留R74原风险倍率。'
        'B的长期资格和既有EP信号保留，并入同票时master原报价优先。换仓仅卖低分且未加仓的亏损探仓，保护盈利或已加仓仓；不合法的新单不会先卖旧仓。'
        '权益低于此前20个完成收盘均值时仅新入场风险减半，原加仓和存量仓不因该开关直接减半。', '',
        '## 与M1B、登记master、master+C062同表', '']
    baselines = {n: metrics(HOME/'reports/m1_work'/p) for n, p in
        [('M1B', 'candidates/M1B'), ('登记master', 'baseline/native_master'), ('master+C062', 'baseline/master_C062')]}
    rows = [annual_cells(n, y, r) for n, data in baselines.items() for y, r in data['years'].items()]
    rows += [annual_cells(n, y, r) for n, data in runs.items() for y, r in data['years'].items()]
    table(lines, COLUMNS, rows)
    table(lines, ['候选', '两年H', '两年资金', '较差年五线', '较差年资金', '较差年毛利', '较差年回撤', '资格失败项'],
        [[n, amount(r['H']), pct(r['cap_equity']), min(x['target_count'] for x in r['years'].values()),
          pct(min(x['cap_equity'] for x in r['years'].values())), pct(min(x['purity_gross'] or 0 for x in r['years'].values())),
          pct(max(x['maxdd'] for x in r['years'].values())), '、'.join(selected['failures'][n]) or '合格'] for n, r in runs.items()])
    lines += ['资格严格按预登记：两年每年≥52笔、胜率≤35%，两年H及加权资金均不低于M1B。'
        '排序依次为较差年五线数、资金、毛利、回撤更小、两年H。账户收益与登记master的差另报，不自动升级。', '',
        '## 先查M1C–E：逐笔、逐拒绝与配对拆解', '']
    collapse = M.read(OUT/'collapse.json')
    table(lines, COLUMNS, [annual_cells(n, y, r) for n, data in collapse['runs'].items() for y, r in data['years'].items()])
    funnel = M.read(OUT/'collapse_funnel.json')
    table(lines, ['账户', '原IE+R74共723笔中同日同票仍开仓', '早买报价中的实际处理'],
        [[n, r['retained'], '；'.join(f'{k}={v}' for k, v in r['early_refusals'].items())] for n, r in funnel.items()])
    lines += ['仅给IE+R74加成交层排队，并未使资金占用崩到零；C去结构排序后为13.8%/12.1%，去B为6.2%/10.4%，'
        'D去结构排序后为15.6%/12.6%。C的早买报价有74次敞口拒绝和10次每日名额拒绝；D为104次和13次，实际仅2次成交。'
        '这支持“宽来源先占仓、结构排序把原机会放到后面”的机制解释。改为重复票使用master报价的诊断与D结果相同，'
        '不支持把重复票报价覆盖当成这次崩溃的主因。没有据此回写M1报告、预登记或旧结果。', '',
        '逐笔文件在collapse各账户的paired_events.json：每个原IE入场和每个合格早买报价，列原pnl、实际是否同日开仓、全部拒绝、当日成交竞争者；'
        '原始逐条拒绝保留在attempts.jsonl。净值路径和反馈会连锁改变后续仓位，以上拆解不把全部收益差额硬分摊给某一个因素。', '',
        '## 单机制诊断（不从单项名次机械拼装）', '']
    if (OUT/'E_supplement.json').exists():
        extra = M.read(OUT/'E_supplement.json')['results']
        no_order, no_hybrid = extra['M1E_no_structure'], extra['M1E_without_hybrid']
        text = ('E另有102次满11仓拒绝、10次每日名额拒绝；其逐条拒绝已在冻结前核对。'
            f'冻结后补做的同执行拆解中，去结构排序的资金为{pct(no_order["years"]["2024"]["cap_equity"])}/'
            f'{pct(no_order["years"]["2025"]["cap_equity"])}, '
            f'去混合入口为{pct(no_hybrid["years"]["2024"]["cap_equity"])}/'
            f'{pct(no_hybrid["years"]["2025"]["cap_equity"])}。'
            '这两项只补充解释E的仓位挤占，不参与候选选择，不打开2026、不修改既有预登记。')
        pos = lines.index('## 单机制诊断（不从单项名次机械拼装）')
        lines[pos:pos] = [text, '']
    diagnoses = M.read(OUT/'diagnostics.json')
    table(lines, COLUMNS, [annual_cells(DESCRIPTIONS[n], y, r) for n, data in diagnoses.items() for y, r in data['years'].items()])
    lines += ['换弱仓一项相对G1重排只增加换仓，其余单项均以M1B为底。低分每天一只为报价上限，已持同票被跳过不会补出第二份探仓。'
        '本轮诊断初版有两处适配问题，在端到端候选和2026打开前更正：QQQ开关原误用master指数倍率而未生效；'
        'F2原只与master既有筛选交集并反复报价，改为独立扫描/观察来源及首个触发消费。旧工件封存于corrections/initial_diagnostics，'
        '当前表只用更正后的12项结果。M1原结果不受影响。', '',
        '## 冻结的五个端到端方案', '',
        f'预登记SHA256：`{M.sha(M.PREREG)}`。候选代码与预登记写定后未改。']
    table(lines, ['候选', '配置', '研究资格'], [[n, json.dumps(s, ensure_ascii=False), '合格' if not selected['failures'][n] else '、'.join(selected['failures'][n])]
          for n, s in M.CANDIDATES.items()])
    all_legs = []
    for n, folder in [(n, HOME/'reports/m1_work'/p) for n, p in
                     [('M1B', 'candidates/M1B'), ('登记master', 'baseline/native_master'), ('master+C062', 'baseline/master_C062')]] \
            + [(n, OUT/'candidates'/n) for n in M.CANDIDATES] + [(n, OUT/'diagnostics'/n) for n in M.DIAGNOSTICS]:
        for g in metrics(folder)['legs']:
            all_legs.append(dict(account=n, **g))
    M.write('all_leg_comparisons.json', all_legs)
    with (OUT/'all_leg_comparisons.csv').open('w', newline='') as f:
        fields = ['account', 'key', 'code', 'year', 'covered', 'any', 'capture_total', 'pnl', 'first_fill', 'offset']
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(all_legs)
    lines += ['', '## 逐段：买得早不早、吃到多少', '']
    compare_names = ['M1B', '登记master', 'master+C062', *M.CANDIDATES]
    for y in ('2024', '2025'):
        leg_keys = [r['key'] for r in all_legs if r['account'] == 'M1B' and r['year'] == y]
        table(lines, ['段', *compare_names], [[key, *[leg_cell(next(r for r in all_legs if r['account'] == n and r['key'] == key))
                         for n in compare_names]] for key in leg_keys])
    if choice:
        items, reasons = paired_funnel(choice)
        lines += ['', '## 选中者的漏斗和2026固定检查', '']
        table(lines, ['年', '可早买报价段', '实际首笔早买', '没有早买报价的段'],
            [[y, sum(bool(g['offered']) for g in items if g['year'] == y),
              sum(g['early'] for g in items if g['year'] == y),
              sum(not g['offered'] for g in items if g['year'] == y)] for y in ('2024', '2025')])
        table(lines, ['未早买的真实拒绝', '次数', '涉及段'], reasons)
        val = M.read(OUT/'validation.json')
        table(lines, COLUMNS, [annual_cells(n, '2026', row) for n, row in reference_2026().items()] +
            [annual_cells(choice+('单开' if n == 'standalone' else '连续'), '2026', data['years']['2026']) for n, data in val.items()])
        single = metrics(OUT/'validation/standalone')
        continuous = metrics(OUT/'validation/continuous')
        table(lines, ['2026段', '单开：早/吃到/H', '连续：早/吃到/H', '截断'],
            [[g['key'], leg_cell(g), leg_cell(next(r for r in continuous['legs'] if r['key'] == g['key'])),
              '是' if g.get('censored', False) else '否']
             for g in single['legs']])
        lines += ['2026只在通过2025-06-30逐笔截断和真实未来扰动之后，各测一次单开和连续。'
            '该年份已被历轮使用，本轮是固定及格检查，不称新样本外。点名、报价、真实执行事件和权益前缀均逐值一致；'
            '画像池、分位、特征与点名从真实cut/perturbed日K独立重建，不只切一份缓存冒充未来检查。', '']
    lines += ['## 缺口和下一轮', '',
        '资金与毛利纯度依旧远离50%/60%。低分探仓的市况控制可以减少错误占用，却不能把画像本身未分清的机会变成他的段；'
        '本轮G1重排及F2替代账户直接暴露了这个差距。下一轮优先沿选中者的逐段漏斗核对“前夜画像排名→真实可成交→证实后占资→峰前退出”，'
        '把遗漏和挤占放到同一张实际成交表；结合并行U1的区分度与上限结论，先决定画像/来源是否足以支持目标。'
        '在明确上游能分清什么以前，不继续靠扩大敞口和多开试仓冒充完成复刻。保留M1B与登记master的年度收益对照。', '',
        '## 工程验收与复算', '',
        '共享引擎只新增默认关闭的画像换弱仓与权益均线新风险控制；通用Study接入可选分数数组。'
        'C062、S1、master+C062、M1B的训练和完整原台账、权益逐位相等；原文件字节指纹未变。'
        '所有实际成交均按原始日K区间（float32存储精度两ULP容差）核对，FIFO、费用、融资和期末估值对账通过。'
        '运行均为指定.venv、CPUQuota=60%、MemoryMax=900M、单进程单线程；逐拒绝流式JSONL，价格/已有数组mmap，画像按票、按夜处理。', '']
    table(lines, ['测试组', '测试数', '结果', '日志'], [[n, r['count'], r['result'], r['log']] for n, r in done['tests'].items()])
    lines += [f'验收核对{audit["accounts"]}个账户、{audit["executions"]}条实际执行事件，未发现成交区间或费用对账违规。'
        f'准备与诊断的峰值RSS为{done["peak_rss_mib"]:.1f}MiB；resource_observation.json实读cpu.max=60000/100000、memory.max=943718400字节、Threads=1。'
        '密钥保护安装器拒绝覆盖已有hooksPath；现有pre-commit/pre-push已调用secret_guard.py，未绕过或提交。'
        '没有联网、拉数据、写U1、改登记版或看板。研究完成与策略成功分别记录在completion.json，不能相互替代。', '',
        '只渲染报告不会运行账户：', '', '```bash',
        'systemd-run --scope -p CPUQuota=60% -p MemoryMax=900M -q env OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 PYTHONDONTWRITEBYTECODE=1 /opt/opend-us-options/.venv/bin/python -m studies.martin_luk.m2_report',
        '```', '',
        '计算入口为m2_research的freeze、collapse、diagnose、correct-diagnostics、compatibility、candidates、'
        'rebuild-profile --variant cut/perturbed、prefix、validate、full-compatibility。正式阶段均有一次性开始守卫，防止悄悄重测2026。'
        '原始指纹、诊断修正、逐笔拒绝、所有账户、逐段CSV/JSON、前缀比较、三组测试与completion.json均在m2_work。']
    report = HOME/'reports/M2_CN.md'
    report.write_text('\n'.join(lines)+'\n')
    done['report_sha256'] = M.sha(report)
    done['delivery_sha256'] = {str(p.relative_to(M.ROOT)): M.sha(p) for p in (Path(__file__), HOME/'tests/test_m2.py')}
    M.write('completion.json', done)
    before, after = (OUT/'original_engine.py.txt').read_text(), Path(M.Y.__file__).read_text()
    (OUT/'engine_delta.diff').write_text(''.join(difflib.unified_diff(before.splitlines(True), after.splitlines(True),
        fromfile='engine_before_M2', tofile='engine_after_M2')))
    summary = [f'M2完成；选中 {choice}；五线全过={done["strategy_success"]}',
        f'报告：{report.relative_to(M.ROOT)}', '原台账四组训练/完整重放一致；三组测试通过。',
        '下一轮：用实际成交漏斗和U1区分度检查画像来源，再调整资金集中。']
    (OUT/'terminal_summary.txt').write_text('\n'.join(summary)+'\n')
    M.write('artifact_manifest.json', {str(p.relative_to(OUT)): M.sha(p) for p in sorted(OUT.rglob('*'))
        if p.is_file() and p.name not in ('artifact_manifest.json', 'report.log')})
    print('\n'.join(summary))


if __name__ == '__main__':
    main()
