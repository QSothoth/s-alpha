"""Render and audit M3 artifacts; this module never simulates an account."""
from __future__ import annotations

from collections import Counter
import csv
import difflib
from pathlib import Path
import re
import xml.etree.ElementTree as ET

import numpy as np

from . import m3_research as R
from .m1_report import COLUMNS, annual_cells, amount, pct, table, leg_cell

OUT, HOME = R.OUT, R.HOME
DESCRIPTIONS = dict(confirm_hold='盈利收盘证实→保本/21EMA', trail9='9EMA跟踪', trail21='21EMA原样',
    trail21_two='21EMA连续两收盘跌破', no_trim='取消10R减仓', trim20='减仓推迟20R',
    trim35='3R/5R各减初仓15%', reentry10='实际洗出后10天收回再试', add1='额外首个+1R收盘加仓',
    add1020='原10/20R加仓', add_high='收盘创前20日高加仓两次', cap50='单票50%原样', cap75='单票75%上限')


def metrics(folder):
    return R.read(folder/'metrics.json')


def audit():
    A = R.arrays(HOME/'reports/m1_work/validation_prepared')
    di, ci = ({str(v): i for i, v in enumerate(A[n])} for n in ('days', 'codes'))
    executions = accounts = 0
    errors = []
    for path in sorted(OUT.rglob('trades.json')):
        accounts += 1
        folder = path.parent
        for t in R.read(path):
            for e in t['executions']:
                d, j = di[e['time']], ci[t['code']]
                lo, hi = float(A['low'][d, j]), float(A['high'][d, j])
                tol = 2*max(abs(float(np.spacing(np.float32(lo)))), abs(float(np.spacing(np.float32(hi)))))
                executions += 1
                if not lo-tol <= e['price'] <= hi+tol:
                    errors.append(dict(file=str(path.relative_to(OUT)), code=t['code'], event=e, range=[lo, hi]))
        rec = R.read(folder/'reconciliation.json')
        if abs(rec['error']) >= 1e-9:
            errors.append(dict(file=str(path), reconciliation=rec))
    images = sorted((OUT/'timelines').glob('*.svg'))
    for p in images:
        ET.parse(p)
    unchanged = {}
    ref = HOME/'reports/m2_work/candidates/M2A'
    for n in ('trail21', 'add1020', 'cap50'):
        unchanged[n] = {k: R.read(OUT/f'diagnostics/{n}/{k}.json') == R.read(ref/(k+'.json'))
                        for k in ('trades', 'curve')}
    assert not errors and all(all(v.values()) for v in unchanged.values()), (errors, unchanged)
    result = dict(ok=True, accounts=accounts, executions=executions, valid_svg=len(images),
        violations=errors, financing_fifo_and_terminal_checked=True,
        unchanged_diagnostic_controls=unchanged, tolerance='two ULP of stored float32 daily high/low')
    R.write('artifact_audit.json', result)
    return result


def management_summary():
    rows = R.read(OUT/'compatibility/M2A/management.json')['management_attempts']
    trades = R.read(OUT/'compatibility/M2A/trades.json')
    labels = metrics(OUT/'compatibility/M2A')['lots']
    his = {(trades[r['trade']]['code'], trades[r['trade']]['entry']) for r in labels if r['bucket'] == 'T1'}
    result = {}
    for group in ('his', 'other'):
        part = [r for r in rows if ((r['code'], r['entry']) in his) == (group == 'his')]
        result[group] = dict(attempts=len(part), filled=sum(r['filled'] for r in part),
            rejected=sum(not r['filled'] for r in part),
            position_limited=sum(r['position_room'] < r['desired'] for r in part),
            gross_limited=sum(r['gross_room'] < r['desired'] for r in part),
            requested_notional=sum(r['desired'] for r in part), allowed_notional=sum(r['allowed'] for r in part))
    R.write('management_summary.json', result)
    return result


def review_diagnosis():
    """Keep sizing counterfactuals inside actual holding intervals; never change account metrics."""
    diagnosis = R.read(OUT/'lot_diagnosis.json')
    trades = R.read(HOME/'reports/m2_work/candidates/M2A/trades.json')
    curve = R.read(HOME/'reports/m2_work/candidates/M2A/curve.json')
    days = R.read(HOME/'notes/legs_frozen.json')['calendar']
    di = {d: i for i, d in enumerate(days)}
    equity = dict(zip(curve['days'], curve['equity']))
    prices = R.M.Y1.Prices()
    buys = {}
    for t in trades:
        buys.setdefault(t['code'], []).extend(di[e['time']] for e in t['executions'] if e['action'] in ('entry', 'add'))
    changes = dict(reentry_assignments=0, size_scenarios=0)
    for c in diagnosis['cases']:
        first, peak = di[c['anchor']], di[c['peak']]
        p = prices[c['code']]
        amounts = Counter(c['amounts'])
        amounts['a_delay'] = 0.
        candidates = []
        proof_days = {}
        for number in {row['trade'] for row in c['lots']}:
            t = trades[number]
            start = max(di[t['entry']]+1, first-3)
            stop = min(di[t['exit']]+int(t['why'] == 'end'), peak, di[R.TRAIN[1]]+1)
            proof = next((d for d in range(start, stop) if p['c'][d] >= t['fill']+abs(t['fill']-t['stop'])), None)
            proof_days[number] = proof
            if proof is not None:
                candidates.append(proof)
        for row in c['lots']:
            if row['reason'] in ('b', 'b_returned'):
                returned = any(di[row['exit']] < d < peak for d in buys.get(c['code'], ()))
                reason = 'b_returned' if returned else 'b'
                if row['reason'] != reason:
                    changes['reentry_assignments'] += 1
                    amounts[row['reason']] -= row['missed_peak']
                    amounts[reason] += row['missed_peak']
                    row['reason'] = reason
                row['reentered_before_peak'] = returned
            proof = proof_days[row['trade']]
            row['proof_close'] = days[proof] if proof is not None else None
            row['add_delay_potential'] = 0.
            if row['action'] == 'add' and proof is not None and proof <= di[row['entry']]:
                row['add_delay_potential'] = row['shares']*max(0., row['price']-float(p['c'][proof]))
                amounts['a_delay'] += row['add_delay_potential']
        previous = (amounts.get('a', 0.), amounts.get('a75', 0.))
        amounts['a'] = amounts['a75'] = 0.
        c['sizing'] = None
        if candidates:
            proof = min(candidates)
            held = sum(e['shares']*(1 if e['action'] in ('entry', 'add') else -1)
                       for e in c['events'] if e['index'] <= proof)
            if held > 1e-12:
                price, eq = float(p['c'][proof]), equity[days[proof]]
                for cap, key in ((.5, 'a'), (.75, 'a75')):
                    amounts[key] = max(0., cap*eq/price-held)*max(0., c['peak_price']-price)
                c['sizing'] = dict(day=days[proof], close=price, shares=held, equity=eq,
                    actual_weight=held*price/eq, hypothetical_target=.5,
                    assumption='actual surviving trade at completed +1R close; additional shares held to peak, ignoring risk/gross/costs')
        changes['size_scenarios'] += previous != (amounts['a'], amounts['a75'])
        c['amounts'] = amounts
    diagnosis['names']['a_delay'] = '实际加仓相对仍持仓时首个+1R收盘的买价延迟'
    diagnosis['names']['peak_close'] = '峰日实际卖价/收盘与日内最高差'
    for group, total in diagnosis['totals'].items():
        selected = [c for c in diagnosis['cases'] if c['group'] == group]
        total['amounts'] = sum((Counter(c['amounts']) for c in selected), Counter())
        total['sizing_observed'] = sum(c['sizing'] is not None for c in selected)
        total['stopped_without_return'] = sum(row['reason'] == 'b' for c in selected for row in c['lots'])
    diagnosis['review'] = dict(original_sha256=R.sha(OUT/'lot_diagnosis.json'), changes=changes,
        policy='size ceiling requires an actual surviving position; add delay uses its first surviving +1R close; return checks every actual same-stock buy',
        selection_or_validation_changed=False)
    R.write('lot_diagnosis_reviewed.json', diagnosis)
    for group in ('his', 'other'):
        with (OUT/('lot_diagnosis_'+group+'_reviewed.csv')).open('w', newline='') as f:
            rows = [row for c in diagnosis['cases'] if c['group'] == group for row in c['lots']]
            writer = csv.DictWriter(f, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    from . import m3_diagnose
    m3_diagnose.NAMES.update(diagnosis['names'])
    m3_diagnose.render(diagnosis['cases'])
    return diagnosis


def completion(artifact):
    registry = R.registry_check()
    protocol = R.read(OUT/'protocol.json')
    protected = {p: R.sha(R.ROOT/p) == h for p, h in protocol['protected'].items()}
    tests = {}
    for n in ('martin_luk', 'trader_replication', 'custody'):
        path = OUT/('test_'+n+'.log')
        text = path.read_text()
        ran = re.search(r'Ran (\d+) tests? in', text)
        ok = re.search(r'^OK(?: \([^\n]+\))?$', text, re.MULTILINE)
        tests[n] = dict(ok=bool(ran and ok), count=int(ran[1]) if ran else None,
            result=ok[0] if ok else 'FAILED', sha256=R.sha(path), log=path.name)
    selection = R.read(OUT/'selection.json')
    validation = R.read(OUT/'validation_complete.json')
    prefix = R.read(OUT/'truncation.json')
    train, full = R.read(OUT/'compatibility.json'), R.read(OUT/'full_compatibility.json')
    policy = ((validation.get('standalone_evaluations'), validation.get('continuous_evaluations')) == (1, 1)
              if selection['chosen'] else validation.get('skipped') and not (OUT/'validation_started.json').exists())
    runs = R.read(OUT/'candidates_train.json')
    success = bool(selection['chosen'] and all(r['target_count'] == 5 for r in runs[selection['chosen']]['years'].values()))
    if success:
        success = all(v['years']['2026']['target_count'] == 5 for v in R.read(OUT/'validation.json').values())
    done = dict(ok=all(protected.values()) and all(v['ok'] for v in tests.values()) and artifact['ok'] and
        train['ok'] and full['ok'] and prefix['ok'] and policy,
        research_completed=True, strategy_success=success, selected=selection['chosen'], tests=tests,
        source_sha256=registry['code_sha256'], prereg_sha256=registry['prereg_sha256'],
        preregistration_unchanged=True, protected_unchanged=all(protected.values()), protected_checks=protected,
        original_training_ledgers_bitwise=train, original_complete_ledgers_bitwise=full,
        truncation=prefix, validation=validation, artifact_audit=artifact,
        diagnostics=len(R.DIAGNOSTICS), endpoint_candidates=len(registry['specs']),
        resource_observations=dict(initial=protocol['resources'],
            diagnostics=R.read(OUT/'diagnostics_complete.json')['resources'], full=full['resources']),
        network_disabled=True, new_data=False, git_commit=False, registration_changed=False, board_changed=False,
        U1_write_boundary='M3 analysis writers permit only m3_work, M3 preregistration and M3 report',
        independent_out_of_sample=False)
    R.write('completion.json', done)
    assert done['ok'], {k: v for k, v in done.items() if v is False}
    return done


def main():
    R.offline()
    artifact, management = audit(), management_summary()
    done = completion(artifact)
    runs, selection = R.read(OUT/'candidates_train.json'), R.read(OUT/'selection.json')
    chosen = selection['chosen']
    diagnosis = review_diagnosis()
    lines = ['# M3：买到之后怎样拿住、怎样加仓', '']
    if chosen:
        r = runs[chosen]
        lines += [f'**按任务书资格与排序选中 {chosen}；本轮复刻目标'+('全部通过。**' if done['strategy_success'] else '仍未完成，不能替换登记 master。**'), '',
            f'2024/2025 段吃到为 {pct(r["years"]["2024"]["capture_total"])}/{pct(r["years"]["2025"]["capture_total"])}，'
            f'资金纯度为 {pct(r["years"]["2024"]["cap_equity"])}/{pct(r["years"]["2025"]["cap_equity"])}，两年 H 为 {amount(r["H"])}。', '']
        ref = metrics(HOME/'reports/m2_work/candidates/M2A')
        lines += [f'2024/2025账户收益为 {pct(r["years"]["2024"]["account_return"])}/{pct(r["years"]["2025"]["account_return"])}，'
            f'回撤为 {pct(r["years"]["2024"]["maxdd"])}/{pct(r["years"]["2025"]["maxdd"])}；'
            f'M2A回撤为 {pct(ref["years"]["2024"]["maxdd"])}/{pct(ref["years"]["2025"]["maxdd"])}。'
            '较差年吃到改善并没有同时解决早买、资金与毛利纯度，回撤代价也必须保留；不把研究入围写成全面改善。', '']
        val = R.read(OUT/'validation.json')
        prior_val = R.read(HOME/'reports/m2_work/validation.json')
        lines += [f'固定2026检查：单开收益 {pct(val["standalone"]["years"]["2026"]["account_return"])}、'
            f'连续账户当年收益 {pct(val["continuous"]["years"]["2026"]["account_return"])}，'
            f'M2A分别为 {pct(prior_val["standalone"]["years"]["2026"]["account_return"])}/'
            f'{pct(prior_val["continuous"]["years"]["2026"]["account_return"])}。'
            '训练的吃到改善没有延续为验证年的整体改善，保留M2A及登记master作后续参照。', '']
    else:
        lines += ['**五个端到端候选均未达到相对 M2A 的研究资格，本轮不选中方案、不打开 2026。** '
            '只延迟卖出、提前加仓或提高单票上限，在这批日 K 和固定 M2A 选股上没有同时守住 H、资金纯度与吃到比例。', '']
    lines += ['以下“潜力”是若持有到已知峰值高点还可多得的金额，单位为初始本金1。'
        '它不是实际可实现收益；未买仓位的潜力、实际lot的买晚损失、实际lot的提前卖出缺口使用不同反事实，不能相加。', '',
        '## 口径与约束', '',
        '完全沿用 Y1 冻结的48段、FIFO/时间切片和五条目标：资金≥50%、段毛利≥60%、早买至少一半段、'
        '段吃到≥50%、前十真实平仓赢单至少五笔有正的H。底线是每年≥52笔、已平仓胜率≤35%。'
        '训练从2024-01-02连续至2025-12-31，年末持仓只估值；2025年底尚未到峰的段保留冻结分母，2026收益不提前记入。'
        'H/O按首次开仓年，资金按日历年，吃到按段年，不能将H/O直接与账户年度收益相减。', '',
        '画像、点名、买卖资格和先后顺序均沿M2A；他的票、日期和段标签只在模拟结束后的评测侧使用。'
        '本轮不拟合模型、不联网、不拉数据、不改U1、登记或看板、不提交Git。', '',
        '## 与M2A、M1B、登记master、master+C062同表', '']
    baselines = {n: metrics(HOME/'reports'/p) for n, p in (
        ('M2A', 'm2_work/candidates/M2A'), ('M1B', 'm1_work/candidates/M1B'),
        ('登记master', 'm1_work/baseline/native_master'), ('master+C062', 'm1_work/baseline/master_C062'))}
    table(lines, COLUMNS, [annual_cells(n, y, r) for n, data in baselines.items() for y, r in data['years'].items()]+
        [annual_cells(n, y, r) for n, data in runs.items() for y, r in data['years'].items()])
    lines += ['研究资格不等于允许替换登记master；上述每年收益与回撤始终一并对照。', '',
        '## 逐段逐lot：缺口在哪里', '',
        f'M2A实际成交的本人段共 {diagnosis["totals"]["his"]["cases"]} 段、{diagnosis["totals"]["his"]["lots"]} 个FIFO卖出切片。'
        '全部建仓、加仓、减仓和离场事件、日期、价格与股数见 [时间线图册](m3_work/timelines/index.html)；'
        '逐lot金额见 [本人段CSV](m3_work/lot_diagnosis_his_reviewed.csv) 和 [其他赢家CSV](m3_work/lot_diagnosis_other_reviewed.csv)。', '']
    table(lines, ['归因/潜力（初始本金1）', '本人段', '非本人段大赢家'],
        [[('峰日实际卖价/收盘与日内最高差' if k == 'peak_close' else diagnosis['names'][k]), amount(diagnosis['totals']['his']['amounts'].get(k, 0.)),
          amount(diagnosis['totals']['other']['amounts'].get(k, 0.))]
         for k in ('a', 'a75', 'a_delay', 'b', 'b_returned', 'c_trim', 'c_trail', 'd', 'e', 'peak_close', 'horizon')])
    lines += ['(a)首仓/加仓空间：只在该段相关交易实际仍有持仓的首个+1R收盘，以当晚权益的50%/75%减实际持股得到缺股，按当晚买到后拿到峰值计潜力。'
        '这是忽略总敞口、风险、费用和中间止损的仓位上限情景；不声称现金能同时支持这些仓位。'
        '实际加仓的买价延迟另列相对同一真实持仓首个+1R收盘的正价差，避免把首仓本已买晚的差额都归为加仓迟。', '',
        '(b)止损类按实际lot退出至峰值的价差计；“没有再买”要求该账户峰前没有后续买入，'
        '曾回来另列，旧lot被卖掉的全部潜力不能等同重入可恢复金额。'
        '(c)10R分批和跟踪线按实际卖出动作分开；(d)强制减仓单列，原M2A未启用gross_close，'
        '且没有全账户止损风险预算自动减仓；敞口主要限制开仓和加仓。'
        '(e)首仓或再试相对段起点的正买价差，不把每笔晚买都归为退出错误。'
        '峰日实际卖价（未卖则用峰日收盘）到当日日内最高的差，以及训练结束仍未到峰另列，不归为峰前退出。', '',
        '实际H切片还逐段核对恒等式：按段起点计的峰值潜力−H = 有正有负的买价时差 + 峰值到实际退出价差 + 费用。'
        '它与Y1的“实际买入名义×段总涨幅”分母不同，仅作金额核对，未替换主指标。', '']
    lines += ['最终交付归因见lot_diagnosis_reviewed.json：资金情景限定在实际仍持仓的窗口，'
        '是否回来按全账户同票的全部真实买入核对。冻结前的初始归因保留在lot_diagnosis.json，'
        '此项交付核对没有改变任何候选规则、主指标、选择或2026评测。', '']
    table(lines, ['本人段', '首笔早/吃到', '没有回来', '10R减仓', '跟踪退出', '买晚', '图'],
        [[c['key'], ('早' if c['covered'] else '晚')+' / '+pct(c['capture_total']),
          amount(c['amounts'].get('b', 0)), amount(c['amounts'].get('c_trim', 0)),
          amount(c['amounts'].get('c_trail', 0)), amount(c['amounts'].get('e', 0)),
          '[时间线](m3_work/'+c['timeline']+')'] for c in diagnosis['cases'] if c['group'] == 'his'])
    lines += [f'非本人段对照使用全部 {diagnosis["totals"]["other"]["cases"]} 组机会：'
        'M2A实际买过、入场后至多60个交易日（不越过训练末日）最高价≥入场价30%，按同票同峰合并，'
        '剔除与任何本人段窗口重叠者，没有只挑最赚钱几笔。它们同样存在洗出、减仓和跟踪退出损失；'
        '这支持机制的通用性，但并不保证延后退出会改善账户，因为还会改变失败单、仓位竞争和权益反馈。', '']
    table(lines, ['原M2A实际加仓', '尝试', '成交', '拒绝', '单票上限限制', '总敞口限制'],
        [[n, r['attempts'], r['filled'], r['rejected'], r['position_limited'], r['gross_limited']]
         for n, r in management.items()])
    lines += ['尝试按真实持仓和实际10/20R触发记录；限制表示允许金额低于申请金额，可能部分成交且两类可重叠，'
        '不能把拒绝次数直接当作可补回的收益。', '', '## 13项单机制诊断', '']
    diagnostic = R.read(OUT/'diagnostics.json')
    table(lines, COLUMNS, [annual_cells(DESCRIPTIONS[n], y, r) for n, data in diagnostic.items() for y, r in data['years'].items()])
    lines += ['21EMA、10/20R和50%三项是原样控制，台账与权益逐值等于M2A。其余各项只改一个机制，均从M2A开始，'
        '不把单项名次机械拼装。盈利收盘证实采用C062的“先盈利再确认”思想，但只移植保本与21EMA，'
        '不同时搬入C062的探仓尺寸、2R灾难止损或风险预算。保本和新跟踪线从下一交易日生效。', '',
        '+1R方案只在原10/20R前增加一次收盘加仓；新高方案替换为收盘超过前20日最高价、最多两次盈利加仓。'
        '3R/5R各卖初仓15%，10R减仓原为初仓30%；全部保留实际止损、费用和融资。'
        '50%/75%是单票新增资金的仓位上限，价格上涨可以被动超过上限，不按事后“他的段”设差异限额。', '',
        'RE只在实际成交后、3R或收盘失守9EMA之前被真实止损的清洁尝试上生效；止损后1–10个交易日，'
        '首个收盘高于原买价只消费一次，沿E10的ADR半幅/5%上限、1%下限重新定止损。'
        '新机会先于再试，再试仍受M2A的QQQ/前夜高分许可、每日4笔、总敞口与单票上限约束，'
        '不让未实际买过的假想止损生成再试，也不递归衍生再试。', '',
        '## 冻结的端到端候选与选择', '',
        f'预登记见 [PREREG_M3_CN](../notes/PREREG_M3_CN.md)，SHA256：`{R.sha(R.PREREG)}`。'
        '候选及实现写定后没有修改。资格是每年过底线、两年H与加权资金纯度均≥M2A、较差年吃到严格>M2A。'
        '排序严格为较差年五线通过数→较差年吃到→较差年资金纯度→较差年回撤较小→两年H。', '']
    table(lines, ['候选', '配置', '两年H', '两年资金', '较差年五线', '较差年吃到', '较差年资金', '较差年回撤', '资格失败'],
        [[n, str(R.candidate_specs()[n]), amount(r['H']), pct(r['cap_equity']),
          min(v['target_count'] for v in r['years'].values()), pct(min(v['capture_total'] or 0. for v in r['years'].values())),
          pct(min(v['cap_equity'] for v in r['years'].values())), pct(max(v['maxdd'] for v in r['years'].values())),
          '、'.join(selection['failures'][n]) or '合格'] for n, r in runs.items()])
    all_legs = [dict(account=n, **g) for n, data in baselines.items() for g in data['legs']]
    all_legs += [dict(account=n, **g) for n in runs for g in metrics(OUT/'candidates'/n)['legs']]
    R.write('all_leg_comparisons.json', all_legs)
    with (OUT/'all_leg_comparisons.csv').open('w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=['account', 'key', 'code', 'year', 'covered', 'any',
            'capture_total', 'pnl', 'first_fill', 'offset'], extrasaction='ignore')
        writer.writeheader()
        writer.writerows(all_legs)
    table(lines, ['段', *baselines, *runs], [[g['key'], *[leg_cell(next(r for r in all_legs if
        r['account'] == n and r['key'] == g['key'])) for n in (*baselines, *runs)]]
        for g in baselines['M2A']['legs']])
    lines += ['## 截断、未来扰动和2026', '',
        '用真实截至2025-06-30的输入，以及仅将此后OHLC×3、量×2、额×6的输入，比较选中者的报价、点名、'
        '实际成交事件和权益前缀；逐值一致。M1的真实截断/扰动行情与M2从其独立重建的G1特征直接复用并核指纹，'
        '本轮新增退出/加仓/再试在三套输入上重新运行，没有只切结果缓存。若无合格候选，'
        '同样检查冻结候选中机制最全的一项，但不打开2026。', '']
    if chosen:
        val = R.read(OUT/'validation.json')
        refs = R.read(HOME/'reports/m2_work/reference_2026.json')
        refs.update({'M2A'+('单开' if k == 'standalone' else '连续'): v['years']['2026']
                     for k, v in R.read(HOME/'reports/m2_work/validation.json').items()})
        table(lines, COLUMNS, [annual_cells(n, '2026', r) for n, r in refs.items()]+
            [annual_cells(chosen+('单开' if k == 'standalone' else '连续'), '2026', v['years']['2026']) for k, v in val.items()])
        single, continuous = (metrics(OUT/'validation'/n) for n in ('standalone', 'continuous'))
        table(lines, ['2026段', '单开：早/吃到/H', '连续：早/吃到/H', '截断'],
            [[g['key'], leg_cell(g), leg_cell(next(r for r in continuous['legs'] if r['key'] == g['key'])),
              '是' if g['censored'] else '否'] for g in single['legs']])
        lines += ['选中者在前缀通过后，2026单开和连续各评一次；该年份已被既有研究使用，不称全新样本外。', '']
    else:
        lines += ['无候选取得资格，因此2026单开与连续评测次数均为0，保留M2A，不另挑失败项测2026。', '']
    lines += ['## 下一轮', '',
        '优先把本轮有改善的持有/加仓机制与U1的来源区分度和可达上限合看。若同一来源在入场前不能区分他的段，'
        '延迟卖出或提高仓位会同时放大其他票；不能将“峰值潜力很大”当成可用资金、可成交和可承担风险的证明。'
        '继续用逐段实际建仓→证实→占资→退出的漏斗，先核每个已买段还有哪些真实加仓窗口，'
        '再决定是否值得改变上游。所有失败配置保留，不回写M1/M2结论。', '',
        '## 工程验收与复算', '',
        '共享引擎仅新增默认关闭的盈利收盘证实、连续收盘跟踪、实际止损再试；管理尝试只在track请求时记录。'
        'C062、master+C062、M1B、M2A训练及原完整台账/权益逐值一致。'
        '成交区间、FIFO与费用/融资/期末估值对账通过，原M2工件和登记/看板指纹未变。', '']
    table(lines, ['测试组', '数量', '结果', '日志'], [[n, v['count'], v['result'], '[日志](m3_work/'+v['log']+')']
        for n, v in done['tests'].items()])
    lines += [f'核对{artifact["accounts"]}个账户、{artifact["executions"]}条执行和{artifact["valid_svg"]}张时间线。'
        '全部计算用.venv、CPUQuota=60%、MemoryMax=900M、单进程单线程；读已有价格数组使用mmap，'
        '归因与绘图按票/段处理。实际cgroup/线程/RSS记录见completion.json。'
        '首次密钥保护安装器拒绝覆盖已有hooksPath；现有提交/推送钩子已调用secret_guard.py，未绕过。', '',
        '报告渲染只读已存账户，不重新回测：', '', '```bash',
        'systemd-run --scope -p CPUQuota=60% -p MemoryMax=900M -q env OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m studies.martin_luk.m3_report',
        '```', '',
        '研究入口为m3_research的freeze、compatibility、full-compatibility、diagnose、candidates、prefix、validate；'
        '逐lot入口为m3_diagnose。正式阶段使用独占开始文件，2026重复调用会失败。'
        '候选冻结依据、逐笔拒绝、管理尝试、图册、前缀证据、三组测试、源指纹与completion.json均在m3_work。']
    report = HOME/'reports/M3_CN.md'
    report.write_text('\n'.join(lines)+'\n')
    done['report_sha256'] = R.sha(report)
    done['delivery_sha256'] = {str(p.relative_to(R.ROOT)): R.sha(p) for p in
        (Path(__file__), HOME/'m3_diagnose.py', HOME/'tests/test_m3.py')}
    R.write('completion.json', done)
    before, after = (OUT/'original_engine.py.txt').read_text(), Path(R.Y.__file__).read_text()
    (OUT/'engine_delta.diff').write_text(''.join(difflib.unified_diff(before.splitlines(True), after.splitlines(True),
        fromfile='engine_before_M3', tofile='engine_after_M3')))
    summary = [f'M3完成；选中={chosen}；复刻成功={done["strategy_success"]}',
        '报告：studies/martin_luk/reports/M3_CN.md',
        f'逐段图册：13个本人段及{diagnosis["totals"]["other"]["cases"]}组其他赢家；原台账四组训练/完整重放一致。',
        '三组测试通过；截断与未来扰动通过；2026'+('单开/连续各一次。' if chosen else '未打开。'),
        '下一轮：结合U1可达上限，检查真实证实加仓窗口及来源区分度。']
    (OUT/'terminal_summary.txt').write_text('\n'.join(summary)+'\n')
    R.write('artifact_manifest.json', {str(p.relative_to(OUT)): R.sha(p) for p in sorted(OUT.rglob('*'))
        if p.is_file() and p.name not in ('artifact_manifest.json', 'report.log')})
    print('\n'.join(summary))


if __name__ == '__main__':
    main()
