"""Render Y1 and its completion record from saved evaluations, without rerunning them."""
from __future__ import annotations

import re
from pathlib import Path

from . import y1_research as Y


def rate(x):
    return '—' if x is None else f'{x:.1%}'


def amount(x):
    return '—' if x is None else f'{x:+.3f}'


def table(lines, columns, rows):
    lines.extend(['', '| '+' | '.join(columns)+' |', '| '+' | '.join(['---']*len(columns))+' |'])
    lines.extend('| '+' | '.join(map(str, row))+' |' for row in rows)
    lines.append('')


def completion():
    prereg = Y.read(Y.WORK/'preregistered.json')
    tests = {}
    for name in ('martin_luk', 'trader_replication', 'custody'):
        path = Y.WORK/f'test_{name}.log'
        log = path.read_text()
        matches = re.findall(r'^Ran (\d+) tests? in .+$', log, re.M)
        outcomes = re.findall(r'^(OK(?: \(.*\))?|FAILED.*)$', log, re.M)
        ok = bool(matches and outcomes and outcomes[-1].startswith('OK'))
        tests[name] = dict(ok=ok, count=int(matches[-1]) if matches else None,
                           outcome=outcomes[-1] if outcomes else 'incomplete', log=path.name)
    inputs = {p: Y.sha(Y.ROOT/p) == s for p, s in prereg['input_sha256'].items()}
    protected = {p: Y.sha(Y.ROOT/p) == s for p, s in prereg['protected_sha256'].items()}
    code = {p: Y.sha(Y.ROOT/p) == s for p, s in prereg['code_sha256'].items()}
    saved_checks = {}
    for name, summary in Y.read(Y.WORK/'accounts.json').items():
        if not summary['available']:
            continue
        account = Y.read(Y.WORK/f'{name}.json')
        pnl = sum(r['h_pnl'] for r in account['lots'] if r['bucket'] == 'T1')
        saved_checks[name] = (account['years'] == summary['years'] and
            len(account['legs']) == Y.read(Y.FROZEN)['counts']['new_legs'] and
            abs(account['reconciliation']['residual']) < 1e-9 and
            abs(account['H_book']['final']-1-pnl) < 1e-9)
    monotonic = all(r['K']['1'][k] <= r['K']['2'][k] <= r['K']['3'][k] <= r[k] <= r['n']
        for years in Y.read(Y.WORK/'selection.json').values() for r in years.values()
        for k in ('signal', 'trigger'))
    tests_unchanged = Y.sha(Y.ROOT/'studies/trader_replication/tests/test_mainleg_account.py') == prereg['tests_sha256']
    result = dict(ok=all(t['ok'] for t in tests.values()) and all(inputs.values()) and all(protected.values()) and all(code.values()),
        tests=tests, inputs_unchanged=all(inputs.values()), protected_unchanged=all(protected.values()),
        formulas_unchanged_since_evaluation=all(code.values()),
        checks=dict(inputs=inputs, protected=protected, code=code),
        frozen_sha256=Y.sha(Y.FROZEN), evaluations=Y.read(Y.WORK/'evaluation_complete.json'),
        independent_out_of_sample=False, no_network=True, no_new_data=True, no_strategy_rerun=True,
        no_git_commit=True, B_line_files_written=False,
        constraints=dict(CPUQuota='60%', MemoryMax='900M', OPENBLAS_NUM_THREADS=1, processes=1),
        outputs=['notes/legs_frozen.json', 'reports/Y1_CN.md', 'reports/y1_work/'],
        native_R74=prereg['native_R74'], secret_guard=prereg['secret_guard'])
    result['saved_artifact_checks'] = dict(accounts=saved_checks, K_curves_monotonic=monotonic,
                                         test_source_unchanged=tests_unchanged)
    result['ok'] &= all(saved_checks.values()) and monotonic and tests_unchanged
    Y.write(Y.WORK/'completion.json', result)
    assert result['ok'], 'Y1 checks failed; inspect completion.json'
    return result


def main():
    accounts, selection, frozen = (Y.read(p) for p in (Y.WORK/'accounts.json', Y.WORK/'selection.json', Y.FROZEN))
    done, prereg = completion(), Y.read(Y.WORK/'preregistered.json')
    records = [(n, y, a['years'][y]) for n, a in accounts.items() if a['available'] for y in Y.YEARS]
    passes = sum(r['targets']['passed'] for _, _, r in records)
    ie, master = accounts['IE47_C062']['years'], accounts['master_C062']['years']
    maximum_capital = max(r['cap_equity'] for _, _, r in records)
    maximum_gross = max(r['purity_gross'] for _, _, r in records)
    lines = ['# Y1：钱有没有花在他的行情段上', '',
        f"六组现有账户、三个年度共 {len(records)} 行，全部目标同时达标 {passes} 行。"
        f"资金占用纯度最高 {rate(maximum_capital)}，目标 50%；毛利纯度最高 {rate(maximum_gross)}，目标 60%。"
        '旧的信号覆盖不能代表账户已买到、已放大、已赚钱。', '',
        f"IE47+C062 的 2026 段内 H 为 {amount(ie['2026']['H'])}，毛利纯度 {rate(ie['2026']['purity_gross'])}，"
        f"资金占用纯度 {rate(ie['2026']['cap_equity'])}。master+C062 同年 H 为 {amount(master['2026']['H'])}，"
        f"毛利纯度 {rate(master['2026']['purity_gross'])}，资金占用纯度 {rate(master['2026']['cap_equity'])}。"
        'master 是正式结果基准。是否更接近目标必须同时看买到、吃到、资金和利润，不能只按选股名字判断。', '',
        '唯一段表完整使用原始多头行，并把非交易日锚点对齐后得到 48 段，按年为 9/22/17。'
        '旧 42 段与建议书的 46 段均可解释，差异见后表。2026 仍为 17 段，其中 2 段截断。'
        '这次只建立尺子与基准，没有拟合或替换策略。', '',
        '## 1. 同一连续账户的六组基准', '',
        '全部使用 2024-01-02 至 2026-10-16 的三年连续实际台账。2026 不混用单独开户；没有重跑账户。'
        '年度收益照读原权益曲线统计，资金比重按本日收盘股数与权益重算。'
        '下面五条目标分别是资金 ≥50%、毛利 ≥60%、早买至少一半段、吃到 ≥50%、前十赢单至少五笔有正的 H 净贡献。']
    table(lines, ['选股+执行', '年', '原账户收益', '他的段/权益日', '毛利来自他的段', '早买段', '段吃到', '前10赢单他的段', '五条及底线'], [
        [n.replace('_', '+'), y, rate(r['account_return']), rate(r['cap_equity']), rate(r['purity_gross']),
         f"{r['coverage']['including_censored']['covered']}/{r['coverage']['including_censored']['n']}",
         rate(r['capture_total']), r['top10_his_leg'], '全过' if r['targets']['passed'] else '未全过']
        for n, y, r in records])
    lines += ['“原账户收益”按权益年计算，包含跨年持仓与融资；H/O 的交易 pnl 按首次开仓年归属，不能直接与它相减。'
              '毛利对同一 FIFO 和时间切片逐片取正值，可能高于按整笔净盈亏取正值的旧毛利，因此本表与顾问的整笔近似不要求相同。', '',
              '原生 master R74 执行缺少可匹配的逐笔 executions 与完整权益曲线，标为无法重算。'
              '已有 r74.json、final_system_r74.json、diagnose_r74.json 是汇总或诊断，不从收益率反造 lots。'
              '六组交叉执行的台账均齐全。', '', '## 2. H 赚了多少，其他业务贡献多少', '',
              '金额单位为初始账户权益 1。O=总交易 pnl−H，含 T2、T3、其他股票及峰后部分；O>0 是其他业务盈利。'
              '总交易 pnl≤0 时净纯度为 None，表中用“—”。']
    table(lines, ['账户', '年', '交易总pnl', 'H段内', 'O其他', '净纯度', '非H亏损合计', '笔数/平仓', '胜率'], [
        [n.replace('_', '+'), y, amount(r['total_pnl']), amount(r['H']), amount(r['O']), rate(r['purity_net']),
         amount(r['tuition_loss']), f"{r['n_trades']}/{r['closed']}", rate(r['win'])] for n, y, r in records])
    table(lines, ['账户', '年', 'T1大段', 'T2其他公开段', 'T3他的票但段外', 'other其他票', 'post_peak峰后'], [
        [n.replace('_', '+'), y, *(amount(r['buckets'][b]['pnl']) for b in ('T1', 'T2', 'T3', 'other', 'post_peak'))]
        for n, y, r in records])
    lines += ['同一 lot 只归一个段，跨峰值时切成窗口内和峰后两份。上述五栏逐年相加等于总交易 pnl。'
              'T2 使用非大段公开多头行的相同窗口和截止规则。T3 只含本人当年公开做过的同票段外成交，其他代码不混入 T3。', '',
              '## 3. 放大仓位和出场的分开诊断']
    table(lines, ['账户', '年', 'H/已用资金', 'H/确认仓', '买点后吃到', '段内任意成交', '同笔synced', '早买offset中位', 'ticker-year整笔毛利诊断'], [
        [n.replace('_', '+'), y, rate(r['cap_share']), rate(r['cap_conf']), rate(r['capture_rem']),
         r['coverage']['including_censored']['any'], r['coverage']['including_censored']['synced'],
         r['coverage']['including_censored']['offset'],
         rate(r['ticker_year_purity_gross'])] for n, y, r in records])
    # Ticker-year gross has a whole-trade denominator, deliberately kept separate from lot-sliced gross.
    lines += ['确认仓从真实确认日起累计，不把此前试仓追溯成大仓。资金按日历年统计，包含上一年带入的持仓。'
              'synced 和 offset 只是过程指标。capture 按 lot 潜力加权，不平均每段比例；买价比他的锚点低时 capture 可以超过 100%。'
              'ticker-year 只作按股票识别的上限诊断，表中按整笔交易计算。它与 lot 切片的毛利分母不同，跨年归属也不同，'
              '数值不保证大于 T1 纯度，不能当成段窗口成绩；逐笔工件保留其毛利金额。', '',
              '## 4. 截断、事件和精度必须分开看', '',
              '2024、2025 没有截断大段，含/不含两行相同。2026 两行如下；不含截断时不把原来属于截断段的 lot 重新归给另一段，'
              '只从 H 分子拿掉。全账户分母不变。未覆盖的截断标签保持未决，不单独宣称失败。']
    censor_rows = []
    for n, a in accounts.items():
        if not a['available']:
            continue
        r = a['years']['2026']
        for view in ('含截断', '不含截断'):
            row = r if view == '含截断' else r['excluding_censored']
            c = r['coverage']['including_censored'] if view == '含截断' else row['coverage']
            censor_rows.append([n.replace('_', '+'), view, f"{c['covered']}/{c['n']}", rate(row['cap_equity']),
                rate(row['purity_gross']), rate(c['capture_total']), amount(row['H']), c['censored_uncovered']])
    table(lines, ['2026账户', '口径', '早买段', '资金纯度', '毛利纯度', '段吃到', 'H', '截断未覆盖'], censor_rows)
    table(lines, ['账户', '年', '事件段早买', '波段早买', 'exact早买', 'chart早买', 'window早买'], [
        [n.replace('_', '+'), y, *(f"{r['coverage'][k]['covered']}/{r['coverage'][k]['n']}" for k in ('event', 'swing', 'exact', 'chart', 'window'))]
        for n, y, r in records])
    lines += ['事件段 duration<5 仍在主分母，单列以辨认短脉冲与长期持有段的差异。'
              '精度沿用最早原始锚点，window 对齐不是精确成交日。各分层的 pnl、capture 与可达性在账户 JSON 中逐段公开。', '',
              '## 5. 只保留 H 的固定规模反事实', '',
              '从同一实际成交中仅保留 H 窗口内部分，峰值收盘切掉尾部，现金保留。'
              '沿用原账户已经发生的 lot 规模，不把腾出的资金重新投入，也不重新跑策略。'
              'H 书从权益 1 起，按实际日期连续估值，下面收益与回撤是 H 书各日历年的权益路径。'
              '与前表按开仓年归属的 H pnl 因跨年持仓会不同。交易费照算，融资未分摊；原账户融资影响另存核对。'
              '这是依赖事后段标签的归因反事实，不是可实时实施的筛选策略。']
    table(lines, ['来源账户', '年', 'H书收益', 'H书日历pnl', 'H书回撤', 'H/自身权益日', '毛利纯度', 'H来源笔数', 'H买入lots', '段吃到'], [
        [n.replace('_', '+'), y, rate(h['return_']), amount(h['pnl']), rate(h['maxdd']), rate(h['cap_equity']),
         rate(h['purity_gross']), h['trades'], h['lots'], rate(a['years'][y]['capture_total'])]
        for n, a in accounts.items() if a['available'] for y, h in a['H_book'].items()])
    hrows = [h for a in accounts.values() if a['available'] for h in a['H_book'].values()]
    lines += [f"只删除 O 书会把毛利纯度变成 100%，但 H 书资金占用最高 {rate(max(h['cap_equity'] for h in hrows))}，"
              f"各年只有 {min(h['trades'] for h in hrows)}–{max(h['trades'] for h in hrows)} 笔来源交易，"
              '仍未达到 50% 资金与每年 52 笔。不能用删掉其他业务后的比值代替完整目标。', '']
    lines += ['## 6. 点名到触发的选股诊断，没有拟合', '',
              '使用同一 48 段和首锚点总涨幅。C_signal 假设次日开盘；C_trig 是点名后五晚内收盘突破前高且仍剩一半的代理。'
              '它不包含观察已用掉、风险资格、同票持仓、每日名额与格子拒绝，不能当作实际成交。'
              'P_opp 与 lift 使用冻结 raw.npy 按 IE47 四层过滤规则逐夜复算的共同池，两种名单按同一机会集合比较。'
              'master 保存的是其原有收盘入场信号，不是同一种三名点名名单；其完整信号与前 K 信号分别报告。']
    table(lines, ['来源', '年', '完整信号覆盖', '五晚触发覆盖', '机会夜精度P_opp', '剩余比例E', '相对池lift', 'K1信号/触发', 'K2信号/触发', 'K3信号/触发'], [
        [name, year, f"{r['signal']}/{r['n']}", f"{r['trigger']}/{r['n']}", rate(r['P_opp']), rate(r['E']),
         '—' if r['lift'] is None else f"{r['lift']:.2f}×",
         *(f"{r['K'][str(k)]['signal']}/{r['K'][str(k)]['trigger']}" for k in (1, 2, 3))]
        for name, years in selection.items() for year, r in years.items()])
    lines += ['K 曲线的分母与同一年的完整段数相同，单元格依次为信号覆盖段数与触发覆盖段数。'
              'P_opp 每个(夜,code)只计一次，不因两个段重叠重复加分。lift 是该机会集合中的算术比例，没有跑随机选票。'
              '训练候选目标 `(C_trig,P_opp,E)` 的评测函数默认只取 2024–25，本轮未把它接进拟合器。'
              '2026 只作本轮一次固定公式评测；旧研究已经使用过 2026，不能新称独立样本外。']
    table(lines, ['来源', '年', '机会夜数', '机会夜点名数', '合格命中数', '实际每晚数量分布'], [
        [name, year, r['opportunity_nights'], r['opportunity_picks'], r['hits'],
         '，'.join(f"{k}只:{v}晚" for k, v in sorted(r['nomination_counts'].items(), key=lambda x: int(x[0])))]
        for name, years in selection.items() for year, r in years.items()])
    lines += ['## 7. 42、46、48 的差别和冻结段表', '',
              f"段表 SHA256：`{done['frozen_sha256']}`。来源台账 {frozen['counts']['raw_long']} 条多头行，"
              f"{frozen['counts']['valid_anchors']} 条有行情锚点，另 {frozen['counts']['missing']} 条无行情，空头另列不纳入本任务。", '',
              '旧 prepared 只选取 81 条多头锚点，形成 42 个大段。对原始全部多头行严格匹配交易日得到 90 条有效锚点、46 段。'
              '完整对齐的 93 条比 prepared 多 10 条 window 行以及 S19 PLTR、V20 TEL 两条 exact 行，新增大段的六条均为 window。'
              '2025-01-01 的 QS、SMR、TEM 均对齐到 01-02，SMR 与 TEM 增加两个大段，QS 未增加大段。'
              '所以不因“建议书说 46”而再删这两个窗口段。48 是本次唯一正式分母，旧 42 段报告原数字保留。']
    table(lines, ['新增于旧42的段', '来源ID', '精度', '原锚点', '对齐first', '峰值', '总涨幅'], [
        [g['code'], ','.join(e['label'] for e in g['entries']), g['precision'], g['anchor'], g['first_date'], g['peak_date'], rate(g['gain'])]
        for g in frozen['legs'] if not g['legacy_42']])
    table(lines, ['缺行情源记录', '股票', '原锚点', '原因'], [[r['id'], r['code'], r['anchor'], r['reason']] for r in frozen['missing']])
    lines += ['缺行情行不被假定为小段，也不能凭空得出峰值并与别段合并。它们作为“未知是否为大段”的未决记录保留。'
              '48 是可量的大段分母，另有 3 条未知源记录；报告没有把未知写成已覆盖或已失败。'
              '如果每条未知各自贡献一个独立大段，则最保守覆盖下界为已覆盖数/(已知段数+当年未知行数)。']
    table(lines, ['股票', 'first', 'peak', '精度', '总涨幅', '天数', '截断', '池内可达'], [
        [g['code'], g['first_date'], g['peak_date'], g['precision'], rate(g['gain']), g['duration'],
         '是' if g['censored'] else '否', '是' if g['reachable'] else '否'] for g in frozen['legs']])
    lines += ['## 8. 公式、工件与验证', '',
              'FIFO lot 级公式、归段冲突和峰值截止见 METHOD_CN 第 11 节。新指标与旧 `coverage/windows/forward` 并存，'
              '旧函数保留原算法和历史数字。首笔真实 fill 不用次日开盘替代，加仓不能用其较小 gain 重置“还剩一半”。', '',
              '工件包括 `preregistered.json`、`pool.json`、`accounts.json`、六组逐笔归因 JSON、`selection.json`、'
              '`evaluation_started.json`、`evaluation_complete.json`、三组测试日志与 `completion.json`。'
              '每个逐笔文件保存所有 lot 的来源、费用残差、段归属、窗口盈亏与峰后盈亏，可核到原始台账。'
              '账户交易 pnl 与 lots 对平；账户收益与交易 pnl 的差包括融资及 end 估值卖费，核对写在各组 `reconciliation`。'
              'end 是期末估值，不算真实平仓或前十赢单；原台账的估计卖费保留，核对权益时加回。']
    table(lines, ['测试组', '测试数', '结果'], [[n, r['count'], r['outcome']] for n, r in done['tests'].items()])
    lines += [f"本轮评测峰值 RSS {done['evaluations']['peak_rss_mib']:.1f} MiB。"
              '重计算与三组测试均使用 CPUQuota=60%、MemoryMax=900M，单进程、OPENBLAS_NUM_THREADS=1。'
              '价格最多缓存 16 只，过滤池按夜读取 mmap 的四列，不构造全市场 N×N 矩阵。', '',
              '补充测试覆盖建议书的 18 类边界，并实跑账户引擎证明其不读取评测函数。'
              '旧 E21 的真实未来扰动前缀审计仍保留，新评测没有改变任何真实成交。'
              '冻结数据、登记配置、IE47 分数、账户引擎、看板和旧 E16 报告的指纹均未改变；未联网、未拉数据、未提交 git、未写 D1 文件。', '',
              '只重新渲染报告：', '', '```bash',
              'OPENBLAS_NUM_THREADS=1 /opt/opend-us-options/.venv/bin/python -m studies.martin_luk.y1_report', '```', '',
              '计算入口是 `python -m studies.martin_luk.y1_research freeze`、`evaluate`，在仓库根目录运行并使用任务规定的 Python 与 systemd scope。'
              '两步都有一次性守卫；已存在冻结表或评测开始记录时会拒绝覆盖，避免悄悄重测 2026。']
    report = Y.STUDY/'reports/Y1_CN.md'
    report.write_text('\n'.join(lines)+'\n', encoding='utf-8')
    done['report_sha256'] = Y.sha(report)
    done['report_script_sha256'] = Y.sha(Path(__file__))
    Y.write(Y.WORK/'completion.json', done)
    print(f'Y1 report written; {len(records)} account-years, {passes} fully pass')
    for name, row in done['tests'].items():
        print(f"{name}: {row['count']} {row['outcome']}")


if __name__ == '__main__':
    Y.offline()
    main()
