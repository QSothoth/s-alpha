"""Backfill exact report excerpts; never recompute or rewrite old verdicts."""
from __future__ import annotations

import json
from pathlib import Path
import re

from . import adapter as D

GAP = D.ROOT/'studies/trader_replication/reports/gap_review'


def selection_excerpts(text):
    """Keep identifiable 2024/25 cells, never a mixed full-period result."""
    future = re.compile(r'2026|202[45]\s*[–—/-]\s*26')
    results, returns, header, context = [], [], None, None
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith('|'):
            cells = [s.strip() for s in stripped.strip('|').split('|')]
            if all(not c or set(c) <= set('-: ') for c in cells):
                continue
            if header is None:
                header = cells
                continue
            if not header or len(header) != len(cells):
                continue
            year_column = next((i for i, c in enumerate(header) if c in ('年', '年份', '年度')), None)
            if year_column is not None:
                if not re.match(r'^202[45]', cells[year_column]) or future.search(stripped):
                    continue
                excerpt = stripped
            else:
                columns = [i for i, c in enumerate(header) if re.search(r'2024|2025|选择|训练', c)
                           and not future.search(c) and not re.search(r'全段|全期|三年', c)]
                if columns:
                    chosen = [cells[i] for i in columns]
                    if any(future.search(c) for c in chosen):
                        continue
                    label = cells[0] if 0 not in columns and not future.search(cells[0]) else ''
                    excerpt = ' / '.join(([label] if label else [])+[header[i]+': '+cells[i] for i in columns])
                elif context == 'selection' and not future.search(stripped) \
                        and not any(re.search(r'全段|全期|三年|验证|留出|2026', c) for c in header):
                    excerpt = stripped
                else:
                    continue
            results.append(excerpt)
            if any(re.search(r'收益|回报|净值|return', c) for c in header+[cells[0]]) or (
                    context == 'selection' and any(re.search(r'美股|港股|A 股', c) for c in header)):
                returns.append(excerpt)
        else:
            header = None
            if stripped.startswith('#'):
                context = ('excluded' if future.search(stripped) or re.search(r'全段|全期|三年|验证|留出', stripped)
                    else 'selection' if re.search(r'2024|2025|选择|训练', stripped) else None)
            if context == 'excluded':
                continue
            for sentence in re.split(r'(?<=[。；])|\n', stripped):
                if re.search(r'2024|2025', sentence) and not future.search(sentence) \
                        and not re.search(r'全段|全期|三年|验证|留出', sentence):
                    results.append(sentence)
                    if re.search(r'收益|回报|幅度', sentence) and '%' in sentence:
                        returns.append(sentence)
    return results, returns


def design_text(parts):
    future = re.compile(r'2026|202[45]\s*[–—/-]\s*26')
    out = []
    for paragraph in parts:
        for sentence in re.split(r'(?<=[。；，])|\n', paragraph):
            identifiers_removed = re.sub(r'(?<![A-Za-z0-9_])[A-Za-z_]+\d+[A-Za-z_]*(?![A-Za-z0-9_])', '', sentence)
            if sentence.strip() and not future.search(sentence) and not re.search(r'全段|全期|三年|验证|留出', sentence) \
                    and not re.search(r'\d', identifiers_removed):
                out.append(sentence)
    return out


def section(text, heading):
    match = re.search(r'^## '+heading+r'[^\n]*\n', text, re.M)
    if not match:
        return None
    rest = text[match.end():]
    end = re.search(r'^## ', rest, re.M)
    return text[match.start():match.end()]+rest[:end.start() if end else len(rest)]


def entry(id_, path, line, sections, *, excerpt=None, lesson=None):
    text = excerpt if excerpt is not None else path.read_text() if path and path.exists() else ''
    lines = [s.strip() for s in text.splitlines() if s.strip()]
    title = next((s.lstrip('# ') for s in lines if s.startswith('#')), None)
    paragraphs = [p.strip() for p in text.split('\n\n') if p.strip() and not p.lstrip().startswith(('#', '|', '```'))]
    results = [p for p in paragraphs if re.search(r'结论|选中|保留|未通过|没有|收益|覆盖|结果', p)]
    selected, returns = selection_excerpts(text)
    if not returns and line in ('trading', 'conversion', 'merge'):
        returns = [s for s in selected if '2024:' in s and '2025:' in s and '%' in s]
    old_lesson = [p for p in paragraphs if re.search(r'教训|任务书.*(?:错|误)|口径.*(?:换|改)|走偏|不能.*(?:证明|称)|事后', p)]
    date = re.search(r'(?m)^2026-\d\d-\d\d(?=[ 。：，；])', text[:1800])
    if date is None and lines and lines[0].startswith('#'):
        date = re.search(r'2026-\d\d-\d\d', lines[0])
    row = dict(id=id_, date=date.group() if date else None, line=line, scope='common',
        sections_changed=sections if text else None, mechanism=title, his_words=None,
        main_result=(selected[:6] or design_text(results)[:2]) or None, returns=returns or None,
        verdict=next((p for p in design_text(results) if re.search(r'选中|保留|未通过|没有|结论|不合格|失败', p)),
                     title if title and re.search(r'选中|保留|未通过|不合格|失败', title) else None),
        report=str(path.relative_to(D.ROOT)) if path and path.exists() else None,
        lesson=lesson or (design_text(old_lesson)[:2] if old_lesson else None),
        selection_years=['2024', '2025'],
        extraction='只带可分离的选择年原文句子或表格单元；不带留出/全期数字、不重算旧结果；缺项null')
    if not text:
        row['lesson'] = '未找到该轮独立已提交报告；不能用预登记或其他轮的数字填空。'
    for suffix in ('_CN.md', '.md'):
        prereg = D.HOME/'notes'/('PREREG_'+id_+suffix)
        if prereg.exists():
            # Report rhetoric in quotation marks is not necessarily his statement.
            paragraphs = prereg.read_text().split('\n\n')
            sourced = [p for p in paragraphs if ('原话' in p or '本人' in p)
                       and (re.search(r'\d+:\d+|https?://', p))]
            row['his_words'] = dict(reference=str(prereg.relative_to(D.ROOT)), excerpts=sourced[:2] or None)
            break
    return row


def append_rows(path, rows):
    path = Path(path)
    existing = {}
    if path.exists():
        for line in path.read_text().splitlines():
            row = json.loads(line)
            existing[row['id']] = row
    with path.open('a') as stream:
        for row in rows:
            if row['id'] not in existing:
                stream.write(json.dumps(row, ensure_ascii=False)+'\n')


def backfill():
    rows = []
    replication = D.REPORTS/'REPLICATION_CN.md'
    rep = replication.read_text()
    for id_, name in [('R1', 'R1_RESULTS_CN.md'), ('R2', 'R2_RESULTS_CN.md'), ('R3', 'R3_RESULTS_CN.md'),
                      ('R4', 'R4_RESULTS_CN.md'), ('R5', 'R5_RESULTS_CN.md'), ('R6', 'R6_RESULTS_CN.md'),
                      ('R7', 'R7_RESULTS_CN.md'), ('R8', 'R8_RESULTS_CN.md'),
                      ('R9-R10', 'R9_R10_RESULTS_CN.md'), ('R11-R12', 'R11_R12_RESULTS_CN.md'),
                      ('R13-R18', 'FINAL_CN.md')]:
        rows.append(entry(id_, D.REPORTS/name, 'merge', ['universe', 'signal', 'trade', 'allocate']))
    for id_, pattern, line, parts in [
            ('R19', 'R19 ', 'metric', []), ('R20', 'R20 ', 'selection', ['universe']),
            ('R21-R21b', 'R21 /', 'selection', ['signal']), ('R22-R22b', 'R22 /', 'selection', ['signal']),
            ('R23-R23c', 'R23 /', 'selection', ['signal']), ('R24-R24b', 'R24 ', 'trading', ['trade']),
            ('R25', 'R25 ', 'trading', ['trade']), ('R26', 'R26 ', 'conversion', ['allocate']),
            ('R27-R27b', 'R27 /', 'trading', ['trade']), ('R28', 'R28 ', 'merge', ['trade', 'allocate', 'signal']),
            ('R29', 'R29 ', 'metric', []), ('R30', 'R30 ', 'selection', ['signal']),
            ('R31', 'R31 ', 'trading', ['trade']), ('R32', 'R32 ', 'conversion', ['allocate']),
            ('R33', 'R33 ', 'regime', ['switch']), ('R34', 'R34 ', 'selection', ['signal']),
            ('R35', '选择目标改为三年最差一年', 'metric', []), ('R36', 'R36 ', 'trading', ['trade']),
            ('R37', 'R37 ', 'trading', ['trade']), ('R38', 'R38 ', 'conversion', ['allocate']),
            ('R39', 'R39 ', 'conversion', ['allocate']), ('R40-R51', 'R40–R51', 'merge', ['signal', 'trade', 'allocate']),
            ('R52-R69', 'R52–R69', 'merge', ['signal', 'trade', 'allocate']),
            ('R70-R74', 'R70–R74', 'merge', ['signal', 'trade', 'allocate'])]:
        rows.append(entry(id_, replication, line, parts, excerpt=section(rep, pattern) or ''))
    post = D.REPORTS/'POSTMORTEM_R75_R108_CN.md'
    rows.append(entry('R75-R107', post, 'merge', ['signal', 'trade', 'allocate'],
        lesson='方向错误：毁掉收益后在可达上限不足的框架内改退出/名额；应审查方向、分开三层并保留原基线。WORKFLOW第二、四、五节已吸收。'))
    rows.append(entry('R108', post, 'infra', [], excerpt=post.read_text().split('\n\n')[1],
        lesson='只完成预登记与部分实现，没有策略评测结果。禁止拿它当一次失败账户。'))
    review = D.HOME/'notes/REVIEW_IE1_IE22_CN.md'
    review_text = review.read_text()
    for i in range(1, 49):
        candidates = [GAP/f'strong_continue_ie{i}_report_CN.md', GAP/f'strong_continue_ie{i}_CN.md',
                      GAP/f'strong_continue_ie{i}_profile_CN.md']
        path = next((p for p in candidates if p.exists()), None)
        excerpt = None
        if i <= 3:
            path = review
            excerpt = next((s for s in review_text.splitlines() if s.startswith('| 1–3 |')), '')
        line = 'selection'
        if 14 <= i <= 21:
            line = 'merge'
        elif i == 48:
            line = 'metric'
        row = entry('IE'+str(i), path, line, ['signal'] if line == 'selection' else ['signal', 'trade', 'allocate'], excerpt=excerpt)
        if i <= 3:
            row.update(main_result=None, returns=None, verdict=None,
                mechanism=excerpt, lesson='只有IE1–IE3合并回顾，未找到逐轮结果；合并数字不分摊到单轮。')
        if 14 <= i <= 21:
            row['lesson'] = '历史尺子由选股前五覆盖换成账户成交覆盖；REVIEW_IE1_IE22_CN.md记为走偏。WORKFLOW第一、四节已拆线固定主尺。'
        rows.append(row)
    e16 = D.REPORTS/'E16_CN.md'
    e16_text = e16.read_text()
    for i in range(1, 22):
        path = D.REPORTS/f'E{i}_CN.md'
        excerpt = None
        if i in (2, 3, 4):
            path = D.REPORTS/'E1_CN.md'
            text = path.read_text()
            excerpt = '\n'.join(s for s in text.splitlines() if re.search(r'\bE'+str(i)+r'\b', s))
        elif i >= 17:
            path = e16
            excerpt = section(e16_text, rf'\d+\. E{i}\b') or ''
        elif i == 16:
            excerpt = re.split(r'(?m)^## 5\. ', e16_text)[0]
        line = 'selection' if i == 20 else 'conversion' if i in (16, 17, 18, 19, 21) else 'metric' if i == 11 else 'trading'
        rows.append(entry('E'+str(i), path, line, ['signal'] if line == 'selection' else ['allocate', 'trade'], excerpt=excerpt))
    for id_, line, parts in [
            ('Y1', 'metric', []), ('D1', 'metric', []), ('M1', 'merge', ['signal', 'trade', 'allocate']),
            ('M2', 'conversion', ['allocate']), ('M3', 'trading', ['trade']),
            ('F1', 'selection', ['signal']), ('F2', 'selection', ['signal']), ('F3', 'selection', ['signal']),
            ('F4', 'selection', ['signal']), ('U1', 'metric', []), ('T1', 'metric', []),
            ('H1', 'merge', ['signal', 'trade', 'allocate']), ('H2', 'merge', ['signal', 'trade', 'allocate']),
            ('S0', 'metric', []), ('P1', 'infra', []), ('P2A', 'metric', []), ('P2B', 'selection', ['signal']),
            ('P3', 'merge', ['switch', 'signal', 'allocate']), ('P4', 'merge', ['switch', 'trade']),
            ('P5', 'merge', ['switch', 'signal', 'trade'])]:
        row = entry(id_, D.REPORTS/f'{id_}_CN.md', line, parts)
        if id_ == 'H1':
            row['lesson'] = '任务书把宽止损配固定风险，首仓过小；ADR排序及过严关注度挡票。WORKFLOW第五节审查清单已吸收。'
        if id_ == 'H2':
            row['lesson'] = '任务书把小试仓占满名额，加仓后止损未覆盖加仓风险，上游可达上限不足。WORKFLOW第五节审查清单已吸收。'
        if id_ == 'P5':
            row['lesson'] = '以X1而非master/M3B选行情；进攻/防守方向跨年相反。取消点名冷却与收盘止损成对改，仍无选择年不亏者。WORKFLOW第四节固定参照账户已吸收。'
        rows.append(row)
    append_rows(FLOW/'attempts.jsonl', rows)
    D.write(D.OUT/'history_audit.json', dict(rows=len(rows), ids=[r['id'] for r in rows],
        missing_reports=[r['id'] for r in rows if r['report'] is None],
        missing_dates=[r['id'] for r in rows if r['date'] is None],
        policy='缺失为null，不重算、不换旧结论；摘录的数字只来自报告原文'))
    issues = []
    for id_, rounds, kind, evidence, proposal, applied in [
            ('WF-001', 'IE14–IE21/S0', '尺子缺陷', 'notes/REVIEW_IE1_IE22_CN.md：八轮偏离前五覆盖；S0改S统一复算', 'WORKFLOW第一、四节固定各线主尺；不回改旧轮', True),
            ('WF-002', 'R75–R108/H1/H2', '任务书老坑', 'POSTMORTEM、H1/H2：底座漂移、上限不足、宽止损小仓与小试仓占槽', 'WORKFLOW第二、五节：分线、先算上限、审查翻译老坑', True),
            ('WF-003', 'P5', '任务书老坑', 'P5_CN.md：X1参照的进攻/防守区分跨年反向', 'WORKFLOW第四节行情固定master/M3B逐年方向', True),
            ('WF-004', 'WF00', '规则不清', '本地martin-luk-benchmarks-v1没有CHECKSUMS，docs/DATA.md说未发布、metadata有两个CSV的SHA', '由用户决定为已有只读metadata清单制定登记方式，或另批数据发布；WF00不得补写数据', False),
            ('WF-005', 'WF00', '尺子缺陷', 'P5 peak_held含晚买后持有；master 11个峰前持有中只有9个早买', '明确漏斗L6的交集口径与P5总峰前持有并列，统一以哪个作未来接受主尺；旧数字保留', False),
            ('WF-006', 'WF00', '规则不清', '2025锚点的跨年段峰前日在2026；按完整峰前数选执行会用留出信息', '固定跨年选择的未知上下界规则；WF00保守用候选下界对参照上界', False),
            ('WF-007', 'WF00', '成本', '完整数据schema核对需要流式扫描多市场CSV，量步骤并非纯轻量读取', '在WORKFLOW量步骤注明数据核验成本；禁止省略校验或把缓存结果当已核对', False)]:
        issues.append(dict(id=id_, date='2026-11-09', trader='martin_luk', round=rounds,
            step='起步', kind=kind, evidence=evidence, proposal=proposal, general=True,
            status='applied' if applied else 'open', clause=proposal if applied else None))
    append_rows(D.ROOT/'skills/trader-replication/references/workflow_issues.jsonl', issues)


FLOW = D.FLOW

if __name__ == '__main__':
    backfill()
