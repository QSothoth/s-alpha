"""Render E5's Chinese delivery using saved results; never rerun an account."""
import json
from pathlib import Path
import re
import resource
import shutil
from unittest.mock import patch

import numpy as np

from studies import trader_data as TD
from studies.trader_data import panel as TP, supplemental as SP
from studies.trader_replication import compare
from . import ie47_e1 as M
from .e1_board_smoke import offline
from .e5_research import OUT, WORK, details


def load(name):
    return json.loads((OUT/name).read_text(encoding='utf-8'))


def pct(x):
    return '—' if x is None else f'{x:+.1%}'


def num(x):
    return '—' if x is None else f'{x:.2f}'


def diagnose():
    """Check saved fills against real daily bars and the protected nightly picks, without another simulation."""
    p = TP.build(TD.dataset('us', 'frozen'), write_cache=False)
    with patch.object(M.panels, 'load', return_value=p):
        A = M.STUDY.arrays('us', mode='frozen')
    picks = load('e1_work/picks.json')
    book = M.entry_book(A, picks, 3, close_confirmed=True)[0]
    expected = {(str(A['codes'][e[1]]), str(day)): e for day, row in zip(A['days'], book) for e in row}
    trades = load('e5_work/full_trades.json')
    bad = []
    for t in trades:
        key = t['code'], t['entry']
        e = expected.get(key)
        if e is None or (t['fill'], t['stop']) != e[3:5] or t['kind'] != M.CLOSE_KIND:
            bad.append(dict(code=key[0], day=key[1], why='entry_or_stop_mismatch'))
        if any(x['action'] not in ('entry', 'end') and x['time'][:10] == t['entry'] for x in t['executions']):
            bad.append(dict(code=key[0], day=key[1], why='entry_day_management'))
    if bad:
        raise AssertionError(('E5 saved trade/bar audit failed', bad[:5]))
    result = dict(checked=len(trades), differences=bad, entry_day_management=0,
                  source_sha256=SP.sha(Path(M.__file__)),
                  protected_picks_sha256=SP.sha(OUT/'e1_work/picks.json'),
                  top=sorted(trades, key=lambda t: -t['pnl'])[:5])
    (OUT/'e5_execution_diagnostics.json').write_text(json.dumps(result, ensure_ascii=False, indent=1)+'\n', encoding='utf-8')
    return result


def render():
    train, val, three = load('e5_train.json')['stats'], load('e5_validation.json'), load('e5_three.json')
    smoke, checks, kept = load('e5_board_smoke.json'), load('e5_checks.json'), load('e5_preserved.json')
    cmp = load('e5_compare.json')['martin_luk_ie47']['markets']['us']
    if not all(x['ok'] for x in checks.values()) or not kept['ok']:
        raise AssertionError('tests and prior-artifact preservation must pass before reporting')
    if cmp['run']['code_digest'] != compare.code_digest() or smoke['frozen']['check']['ok'] is not True:
        raise AssertionError('delivered code, comparison and frozen board must agree')
    diag = diagnose()
    old, old_full = load('e1_work/E3_train.json'), load('e1_validation.json')
    details(old, load('e1_work/E3_train_trades.json'))
    details(old_full['full'], load('e1_work/chosen_full_trades.json'))
    full, held = val['full'], val['validate']
    passed = sum(ok for _, ok, _ in val['success'])
    peaks = [int(v) for stage in ('train', 'validate', 'board')
             for v in re.findall(r'peak=(\d+) MiB', (WORK/f'{stage}.log').read_text())]
    resources = dict(research_peak_mib=max(peaks), disk_free_gib=shutil.disk_usage(OUT).free/2**30,
                     child_peak_mib=max(x['peak_child_rss_mib'] for x in checks.values()))
    (OUT/'e5_resources.json').write_text(json.dumps(resources, indent=1)+'\n', encoding='utf-8')
    baseline = dict(e3_train=old, e3_full=old_full['full'], e3_validate=old_full['validate'])
    (OUT/'e5_baselines.json').write_text(json.dumps(baseline, ensure_ascii=False, indent=1)+'\n', encoding='utf-8')
    L = ['# E5：只用日 K 的收盘确认买点', '',
         f"结论：**E5 消除了买入日止损的先后歧义，但没有完成复刻**。连续账户 2024 / 2025 / 2026 为 "+
         ' / '.join(pct(full['by_year'][y]) for y in ('2024', '2025', '2026'))+
         f"，全段 {pct(full['total'])}，最大回撤 {full['maxdd']:.1%}；复刻成功标准 {passed}/7。"
         f"2024–25 只有 {train['trades']} 笔已平仓，对比 E3 的 {old['trades']} 笔，"
         f"行为差距从 {old['behaviour_gap']:.4f} 扩大到 {train['behaviour_gap']:.4f}。"
         '没有得到可替换 R74 + S7 的方案。'
         '本结果只评价 IE47 画像 × E5 收盘确认与止损上限 × E3 管理这个版本，不能归结为 Martin 本人的方法无效。', '',
         '按唯一任务书 [PLAN_E5_CN.md](../notes/PLAN_E5_CN.md) 与[预登记](../notes/PREREG_E5_CN.md)执行，'
         '只有 E5 一个候选，跑后没有改规则或挑选其他版本。E3 数字直接读取 E1 已存结果。'
         '登记研究版现在为 `martin_luk_ie47 / IE47 + E5`，未冻结；R74 + S7 与默认整板保留。'
         '只改 gap-review 工作区，未取新数据、未调用 OpenD、未用小时或分钟线校准，未提交、推送或发布看板。', '',
         '## 1. 执行规则与时点', '',
         '沿用 IE47 固定画像与四条过滤，不重新拟合；`h4_history` 是日线历史组，不是四小时 K。'
         't 晚入选，t+1～t+3 内首次收盘严格高于前一天最高价时，按当天收盘价买入。'
         '盘中突破而收盘未确认继续观察；首次确认后因宽止损或账户限制未成交，不顺延。', '',
         '止损为买入日低点，不足 1% 向下扩到 1%；最终宽度超过 min(5%、前一收盘 ADR20 的一半) 就不买。'
         'ADR 沿用 E3 前一收盘口径；上限不足 1% 时跳过。没有把过宽止损上移后强买。'
         '买入当天只收盘成交，从次日起才检查止损、3R / 5R 各卖原始仓位 15%、收盘首次严格低于 9 EMA 清仓。'
         '风险 0.5%、单只 25%、总 280%、最多 11 只、每日最多四笔，费用及融资成本沿用 E3。', '',
         '时点单测先写后实现：收盘价成交、当天不止损/分批/均线清仓、两个宽度上限及边界、1% 下限、'
         '观察到期、拒单不重试、次日止损与分批、随机换票保留收盘成交和止损宽度。'
         '共用引擎无需新增执行字段。盘中模式沿用其他系统收盘前 10–15 分钟的临时日 K 约定；本次没有完整实时输入，未声称实盘验证。', '',
         '## 2. 2024–25 与 E3、本人并列', '',
         '下表均在 2025 年末截断；平仓笔数按入场年份，收益是从 2024 连续运行的分年账户收益。'
         '平均赚亏含买卖成本；持有天数是交易日，入场日为第零天。', '',
         '| 版本 | 年份 | 收益 | 年内最大回撤 | 平仓 / 开仓 | 胜率 | 平均赚 / 亏 | 平均 / 中位持有 | study.gap |',
         '|---|---|---|---|---|---|---|---|---|']
    for label, stats in [('E3（已存）', old), ('E5', train)]:
        for y, r in stats['annual'].items():
            L.append(f"| {label} | {y} | {pct(r['ret'])} | {r['maxdd']:.1%} | {r['n']} / {r['opened']} | "
                     f"{r['win']:.1%} | {pct(r['avg_win'])} / {pct(r['avg_loss'])} | "
                     f"{num(r['mean_days'])} / {num(r['median_days'])} | {r['gap']:.4f} |")
    L += ['| Martin 本人 | 2024 | +283% | 未公开 | 423 | 约25% | +15% / −3% | 未公开 | 目标 |',
          '| Martin 本人 | 2025 | +970% | 未公开 | 940 | 22% | +14.1% / −2.1% | 未公开 | 目标 |', '',
          '本人目标沿用 E1 任务书与 `RULES_CN.md` / `IE47Study.his`，未新增联网核实；没有公开平均持有天数目标，故不虚构持有期达标判断。'
          'master R74 多头已有对照为 2024 约 +326%、308 笔，2025 约 +239%、222 笔；全段胜率18.5%、平均赚亏 +27.5% / −2.6%，后两项不是分年数。', '',
          '| 2024–25 合计 | 收益 | 最大回撤 | 同池随机中位 | 随机排位 | 行为差距均值 |', '|---|---|---|---|---|---|']
    for label, stats in [('E3（已存）', old), ('E5', train)]:
        L.append(f"| {label} | {pct(stats['total'])} | {stats['maxdd']:.1%} | {pct(stats['placebo']['median'])} | "
                 f"{stats['placebo']['rank']:.0%} | {stats['behaviour_gap']:.4f} |")
    L += ['', '随机对照 100 次、种子 1，来自前一晚完整过滤池，随机换票保留当天收盘成交、原信号的百分比止损宽度、相同账户与次日起管理。'
          'E3 自己的随机对照保持历史盘中成交口径；两者只与各自同执行的随机结果比较，不把不同成交时点的随机中位当作同一个基准。', '',
          '## 3. 2026 只测一次与全段', '',
          '| 版本 | 2024 | 2025 | 2026 至10-16 | 全段 | 全段最大回撤 | 全段随机中位 / 排位 |', '|---|---|---|---|---|---|---|']
    for label, stats in [('E3（已存）', old_full['full']), ('E5', full)]:
        L.append('| '+' | '.join([label, *(pct(stats['by_year'][y]) for y in ('2024', '2025', '2026')),
                 pct(stats['total']), f"{stats['maxdd']:.1%}",
                 f"{pct(stats['placebo']['median'])} / {stats['placebo']['rank']:.0%}"])+ ' |')
    r = full['annual']['2026']
    L += ['', f"E5 连续账户 2026：平仓 / 开仓 {r['n']} / {r['opened']}，胜率 {r['win']:.1%}，"
          f"平均赚亏 {pct(r['avg_win'])} / {pct(r['avg_loss'])}，平均 / 中位持有 {num(r['mean_days'])} / {num(r['median_days'])} 天，"
          f"年内回撤 {r['maxdd']:.1%}。", '',
          '| 2026 独立账户（年初净值1） | 收益 | 随机中位 | 排位 |', '|---|---|---|---|']
    for label, stats in [('E3（已存）', old_full['validate']), ('E5', held)]:
        L.append(f"| {label} | {pct(stats['total'])} | {pct(stats['placebo']['median'])} | {stats['placebo']['rank']:.0%} |")
    L += ['', 'E5 在说明段完成并固定配置后，落启动标记评估2026一次；随后的比较与看板是同配置确定性复放，结果完全一致。'
          'IE47 选股与 E3 之前已使用2026，因此这里只能称 E5 执行未用2026调参的检验，不能称整个系统全新独立样本外。'
          '全段统计包括后来平仓的跨年交易，可能与在2025年末截断的平仓数不同。', '',
          '## 4. 离场分布与入场上限', '',
          '| 版本 | 入场年 | 平仓数 | 买入当天止损 | 后续止损 | 跳空止损 | 9 EMA 清仓（trail / signal） |',
          '|---|---|---|---|---|---|---|']
    for label, stats in [('E3（已存）', old_full['full']), ('E5', full)]:
        for y, r in stats['annual'].items():
            q = r['exit_reasons']
            L.append(f"| {label} | {y} | {r['n']} | {q.get('stop_day0',0)} | {q.get('stop',0)} | "
                     f"{q.get('gap_stop',0)} | {q.get('trail',0)+q.get('signal',0)}（{q.get('trail',0)} / {q.get('signal',0)}） |")
    L += ['', '两种均线离场原因表示同一条首次收盘低于9 EMA的规则：引擎已激活跟踪线记 `trail`，尚未激活记 `signal`。'
          '上表仅含已平仓；期末未平另按收盘估值。', '',
          '| 年份 | E5 合规确认上限 | 实际开仓 | 首次确认但止损过宽 | 观察到期 |', '|---|---|---|---|---|']
    for y, r in full['annual'].items():
        q = r['observation_events']
        L.append(f"| {y} | {q.get('triggered',0)} | {r['opened']} | {q.get('wide_stop',0)} | {q.get('expired',0)} |")
    L += ['', '事件按发生日归年，开仓按入场日归年；跨年观察不强制归到入选年。合规确认是进入账户之前的上限，'
          '减少账户拦截不能补出被宽止损和未收盘确认消耗的机会。2025 本人笔数下限为658笔，本版本的上游触发数量已经不足；'
          '不能期待下游名额或仓位调整填补这一缺口。', '',
          '## 5. 三层对照：确切日期不挪日', '',
          '| 层 | 2024 | 2025 | 两年合计 |', '|---|---|---|---|',
          '| 他的公开账户（目标） | +283% | +970% | 不以部分台账重建完整账户 |']
    for label, stats in [('他的确切日期票 + E5', three['his_tickers_e5']), ('IE47 票 + E5', train)]:
        L.append(f"| {label} | {pct(stats['by_year']['2024'])} | {pct(stats['by_year']['2025'])} | {pct(stats['total'])} |")
    statuses = dict(wide_stop='止损过宽', duplicate_same_stock_day='同股同日重复',
                    no_close_break_or_invalid_bar='未收盘确认或K线无效', missing_data='缺数据',
                    account_rejected='账户拒绝', bought='买到')
    L += ['', f"确切日期台账 {three['exact']['all']} 条，实际买到 {three['exact']['bought']} 条。状态："+
          '、'.join(f'{statuses[k]} {v}' for k,v in three['exact']['statuses'].items())+'。逐条保留在 `e5_three.json`，没有把未成交信号挪到别的日期。'
          '零收益表示没有合规交易，不能解释成 E5 已经拿住了这些股票。'
          'E1 同一部分台账曾实际买到12条、两年+22.0%，是已存的历史对照，不是重测；E5 的收盘确认与低点距离约束明显改变了入场行为。'
          'IE47 + master 执行的已存两年收益约−49.6%，见 E1 报告；本次未重算旧账户。', '',
          '差距定位：E5 确实消除了买入日先后不明，代价是大量收盘距低点过远或没有收盘确认的机会直接失效。'
          '在当前确切日期台账上，执行条件本身已阻止全部可观察的买入，因此不能把剩余收益差距只归于选股。'
          '部分台账没有成交，无法据此估计选股和执行各占多少因果份额；本轮也没有继续调参。', '',
          '## 6. 门禁与成功标准', '',
          '| 门禁 | 结果 | 证据 |', '|---|---|---|']
    for key, label in [('data','数据'),('lookahead','不看未来'),('fills','成交价'),('win_rate','胜率')]:
        q = val['gate'][key]
        if key == 'data':
            why = 'trader-data-v1 摘要与固定值相同，净值覆盖2024-01-02至2026-10-16'
        elif key == 'lookahead':
            why = '；'.join(c['cut']+(' 一致' if c['ok'] else ' '+','.join(c['diff'])) for c in q['cuts'])
        elif key == 'fills':
            why = f"{q['executions']} 次实际成交，区间外 {q['n_bad']} 次"
        else:
            why = f"{q['trades']} 笔已平仓，胜率 {q['win']:.1%}，上限35%"
        L.append(f"| {label} | {'通过' if q['ok'] else '未通过'} | {why} |")
    labels = {'gate':'1 四项门禁','count':'2 逐年笔数','behaviour':'3 公开行为','years':'4 逐年收益距离',
              'placebo':'5 全段超过随机','validate':'6 验证段超过随机','not two':'7 去掉最大两笔仍超过随机'}
    L += ['', '| 成功标准 | 结果 | 逐条证据 |', '|---|---|---|']
    for name, ok, why in val['success']:
        if name == 'gate':
            reason = f"四项门禁{'全部通过' if val['gate']['ok'] else '有未通过项'}"
        elif name == 'count':
            reason = '；'.join(f"{y}：{full['annual'][y]['n']} 对 {n}" for y,n in [('2024',423),('2025',940)])
        elif name == 'behaviour':
            reason = '；'.join(f"{y}：胜率{full['annual'][y]['win']:.1%}，平均赚亏"
                               f"{pct(full['annual'][y]['avg_win'])}/{pct(full['annual'][y]['avg_loss'])}" for y in ('2024','2025'))
        elif name == 'years':
            reason = '；'.join(f"{y} 对数距离 {abs(np.log((1+full['by_year'][y])/(1+h))):.2f}>0.3"
                               for y,h in [('2024',2.83),('2025',9.7)])
        elif name == 'placebo':
            reason = f"{pct(full['total'])} 对随机中位 {pct(full['placebo']['median'])}"
        elif name == 'validate':
            reason = f"{pct(held['total'])} 对随机中位 {pct(held['placebo']['median'])}"
        else:
            reason = f"去两笔后 {pct(full['drop2'])}，随机中位 {pct(full['placebo']['median'])}"
        L.append(f"| {labels[name]} | {'通过' if ok else '未通过'} | {reason} |")
    L += ['', '`success.judge` 分别检查2024、2025后合并，原始逐项判定保留在 `e5_validation.json`。'
          '去两笔完全沿用 `success.drop_top`（按已平仓单笔收益率排序），没有换成其他排序口径。', '',
          '## 7. 看板、保护与验证', '',
          f"冻结期看板通过：截止 {smoke['frozen']['last_day']}，同一登记和 `build` / `runner`，"
          '逐年收益与 `e5_compare.json` 一致，总收益、平仓笔数也一致。独立比较路径由登记元数据指定，'
          '正常调用看板也会读取它，无需临时替换比较表；旧 E3 比较记录保留。', '',
          f"live 输入截至 {smoke['live']['inventory']['last_day']}：QQQ 缺 {len(smoke['live']['inventory']['qqq_missing'])} 个交易日；"
          f"完整比较范围当晚期权量仅覆盖 {smoke['live']['inventory']['option_available']}/{smoke['live']['inventory']['scope']}，"
          f"缺 {smoke['live']['inventory']['option_missing']} 只。运行如实拒绝，没有删过滤条件或使用旧值填补。", '',
          'provisional：'+smoke['provisional']['reason']+'。完整当日数据不足，不能把冻结回放当作今天或真实盘中成功。', '',
          f"既有 {kept['checked']} 个保护文件 SHA256 全部未变，涵盖 E1–E4 结果、预登记、画像、IE47 拟合/scorecard、原比较表和 master 报告/实现。"
          '首次密钥钩子安装器因已有 core.hooksPath 拒绝覆盖；保留现有钩子，没有绕过，规定测试中的真实密钥检查通过。', '',
          '| 测试 | 结果 |', '|---|---|']
    for name, r in checks.items():
        summary = next((s.strip() for s in r['summary'] if s.startswith('Ran ')), '；'.join(r['summary']))
        status = next((s for s in r['summary'] if s.startswith('OK')), '')
        L.append(f"| {name} | 通过；{summary}；{status} |")
    L += ['', f"单一重计算进程，指定虚拟环境、nice 10、单线程 BLAS、UTF-8，峰值约 {resources['research_peak_mib']} MiB；"
          f"测试子进程峰值约 {resources['child_peak_mib']:.0f} MiB；磁盘余量 {resources['disk_free_gib']:.1f} GiB。"
          '真实行情按股票/日期处理，未构造 N×N 矩阵；网络及工作区外写入由研究入口拒绝。', '',
          '新增源码/记录：`e5_research.py`、`e5_report.py`、`tests/test_ie47_e5.py`、`notes/PREREG_E5_CN.md`；'
          '新增结果：`e5_selected.json`、`e5_train.json`、`e5_validation.json`、`e5_three.json`、`e5_compare.json`、'
          '`e5_board_smoke.json`、`e5_checks.json`、`e5_preserved.json`、`e5_resources.json`、`e5_baselines.json`及本报告。'
          f"`e5_execution_diagnostics.json` 用真实日 K 与未改的逐晚名单核对全部 {diag['checked']} 笔的入场、止损与当天管理，差异0，另存头部五笔实际执行。"
          '逐笔、曲线与运行日志在忽略目录 `reports/e5_work/`。', '',
          '修改：`ie47_e1.py`（仅增加E5开关）、`trader_replication/systems.py` / `runner.py`（研究登记与独立比较路径）、'
          '`trader_replication/tests/test_ie47_registration.py`、两个目录 README、`.gitignore`。工作区原有修改保留。', '',
          '复现入口：指定环境运行 `python -m studies.martin_luk.e5_research train`、`validate`、`board`，'
          '按此顺序且各仅一次；已存启动标记防止重复评价。日常只读查看 JSON，测试用 `e5_research checks`，'
          '保护核对用 `e5_research preserved`，报告从现有结果生成用 `python -m studies.martin_luk.e5_report`。'
          '不删除标记重跑验证。配置、预登记与源码指纹保存在结果文件中。', '',
          f"本次预登记 SHA256：`{val['preregistered_sha256']}`。"]
    (OUT/'E5_CN.md').write_text('\n'.join(L)+'\n', encoding='utf-8')
    print(f'E5 report rendered; {passed}/7 success criteria')


if __name__ == '__main__':
    resource.setrlimit(resource.RLIMIT_AS, (1_500_000_000, 1_500_000_000))
    offline()
    render()
