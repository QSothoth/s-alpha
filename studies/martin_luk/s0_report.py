"""Render and verify the persisted S0 signal audit, without any account research."""
from __future__ import annotations

from collections import Counter
import json
import re
import numpy as np

from . import s0_research as S


def records():
    return [S.read(path) for path in sorted((S.OUT/'systems').glob('*.json'))]


def missing():
    rows = S.read(S.OUT/'unrecoverable_ie33.json')
    rows.append(dict(system='U1_profile', status='不可复算',
        reason='只有事后行情段库的画像分数、分组排序及移植阈值，没有逐晚点名和系统自己的夜内顺序',
        why_not_rerun='原脚本评价已知行情段，重跑仍不产生逐晚信号；改成每晚前K或在事后大段上点名都会发明新选股逻辑',
        evidence='studies/martin_luk/u1_analysis.py；reports/u1_work/scores_2024_2025_to_2026.csv'))
    return rows


def value(row, k, year):
    return row['results'][str(k)]['annual'][year]


def pct(x):
    return '—' if x is None else f'{100*x:.1f}%'


def triple(row, k, field, digits=1):
    out = []
    for year in S.YEARS:
        x = value(row, k, year)[field]
        out.append('—' if x is None or row['policy']['years'][year] == '未评测' else
                   str(x) if isinstance(x, int) else f'{x:.{digits}f}')
    return ' · '.join(out)


def coverage(row, k, year, status=False):
    v = value(row, k, year)
    tag = row['policy']['years'][year]
    if tag == '未评测':
        return '—（未评测）'
    return f'{v["covered"]}/{v["n"]}'+(f'（{pct(v["coverage"])}，{tag}）' if status else '')


def coverage_triple(row, k):
    return ' · '.join(coverage(row, k, year) for year in S.YEARS)


def passed(row):
    held = [y for y in S.YEARS if row['policy']['years'][y].startswith('留出')]
    return '无留出' if not held else '达标' if all(value(row, 3, y)['coverage'] >= .8 for y in held) else '未达'


def best(rows):
    candidates = [(value(row, 3, year)['coverage'], row, year) for row in rows for year in S.YEARS
                  if row['policy']['years'][year].startswith('留出')]
    return max(candidates, key=lambda r: (r[0], r[1]['system'] == 'IE9'))


def render():
    rows = records()
    rate, leader, year = best(rows)
    v = value(leader, 3, year)
    distance = f'距80%还差{100*(.8-rate):.1f}个百分点' if rate < .8 else '达到80%线'
    main = (f'当前水位：{leader["system"]} 在 {year} 历史留出段的 K=3 早期覆盖为 '
            f'{v["covered"]}/{v["n"]}（{pct(rate)}），{distance}。')
    lines = ['# S0：每晚几只时，历史信号覆盖到了哪里', '',
        ('本次复算没有发现留出段 K=3 早期覆盖达到80%的系统。' if rate < .8 else '已有系统在历史留出段的K=3覆盖达到80%。')+main, '',
        '这里的留出是某个历史模型没有用于选择的年份。2026已被前轮反复查看，表中记为“留出*”，不能称为全新独立样本外。'
        '这张表只评价点名，不评价执行、仓位、账户或收益，也不按S0结果替换历史选择。', '',
        'IE33的部分2026样本内结果在K=3时覆盖超过80%，但原脚本以全期特征估计分档边界及池分布。'
        '这些年份按新标准标为样本内。IE26按半年折拼接的名单也没有完整未用年份，不能拿来填主数字。', '',
        '## 固定口径', '',
        f'分母为冻结的48段，2024、2025、2026分别为9、22、17。'
        f'`notes/legs_frozen.json` 的 SHA256 为 `{S.sha(S.HOME/"notes/legs_frozen.json")}`。'
        '事件段、不可达段和截断段均保留。', '',
        't晚点名，统一看t+1开盘。买入日必须在首锚点前3个交易日至峰值前1个交易日之间，'
        '且开盘至峰值剩余涨幅至少为首锚点总涨幅的一半。后续锚点不重置总涨幅。'
        '先跳过过去10个交易日已点过的名字，再按系统自己的顺序取前K。冷却跨年延续，跳过不续期。', '',
        '只截断系统实际输出的名单。原生最多3只的版本不会为K=5或不限宽度补出第四只。'
        '每个K独立计算冷却，但不重新运行候选选择或改写原系统的原生点名过程。'
        'K不同，较早的点名和随后冷却也会不同，覆盖不保证随K单调。'
        '原始信号在当日收盘后可知，统一作为当晚点名，不能再按原成交日的收盘价套用旧漏斗数字。', '',
        '统计信号夜为2024-01-02至2026-10-15，包含没有点名的交易夜。2026-10-16之后没有冻结开盘数据，'
        '末夜不评测。保存的2023暖机点名保留冷却作用，落在跨年合格窗口时也能命中，但不计入2024点名宽度。'
        '段覆盖按首锚点年，点名数、不同票和精度按信号夜年。'
        '2025段跨入2026的合格夜仍归2025分母。', '',
        '## 历史水位表', '',
        '所有三项并列值均依次为2024、2025、2026。K=1、K=5和不限宽度各格的样本属性与该行K=3对应年份完全相同。'
        '不限宽度仍有10日冷却，同时给新点名均数和冷却前原始名单均数。'
        '不同票同时列K=3和不限宽度，剩余涨幅中位和精度取K=3，逐年报告。'
        '精度是新点名落在任一段合格夜的比例，重叠段只计一次，仅作参照。', '',
        '`master_filtered`是每晚前4截断之前，`master_capped`是截断之后。'
        '`regime`为分行情版，`shared`为共同画像版，`explainable`为去掉不可解释项的版本。', '',
        '| 系统 | K=3：2024 | K=3：2025 | K=3：2026 | K=1 | K=5 | 不限宽度覆盖；每晚新名均数；原始均数 | K=3每晚新名均数 | 每年不同票 | 剩余涨幅中位 | 精度 | 是否达标 |',
        '|---|---|---|---|---|---|---|---|---|---|---|---|']
    for row in rows:
        cells = [coverage(row, 3, y, True) for y in S.YEARS]
        unlimited = coverage_triple(row, 'unlimited')+'<br>新名 '+triple(row, 'unlimited', 'mean_new_names')+'<br>原始 '+triple(row, 'unlimited', 'mean_raw_names')
        med = ' · '.join(pct(value(row, 3, y)['remaining_share_median']) for y in S.YEARS)
        precision = ' · '.join(pct(value(row, 3, y)['precision']) for y in S.YEARS)
        distinct = 'K=3 '+triple(row, 3, 'unique_names')+'<br>不限 '+triple(row, 'unlimited', 'unique_names')
        tail = [coverage_triple(row, 1), coverage_triple(row, 5), unlimited,
                triple(row, 3, 'mean_new_names'), distinct, med, precision, passed(row)]
        for name in row.get('table_aliases', [row['system']]):
            lines.append('| '+' | '.join([name]+cells+tail)+' |')
    for row in missing():
        lines.append('| '+row['system']+' | —（样本内） | —（样本内） | —（模型标签留出*，无点名） | — | — | — | — | — | — | — | 不可复算 |')
    lines += ['', '每个系统的四组逐段记录在 `s0_work/systems/`，输入名单在 `s0_work/picks/`。'
        '主表中共享名单的观察/执行变体逐一列行，底层复用同一份评测工件。', '',
        '## 哪些年份参与过拟合或调参', '',
        '| 系统组 | 样本内年份 | 留出或缺口 | 证据 |', '|---|---|---|---|']
    lines += [
        '| 登记master，截断前和后 | 2024、2025、2026，同段研究择优 | 无留出 | `references/MARTIN_LUK_CN.md`、`final_system_r74.json`、`s7.json` |',
        '| IE9 | 2024、2025 | 2026为模型历史留出*，此前已查看四次 | `notes/PREREG_IE9_CN.md`开头、选择与冻结段 |',
        '| IE26 E、A拼接 | 三个年份都进入其他外折拟合及全段精简 | 六半年交叉留出不能当作一个整年未用留出；跨界拼接可能引用见过相邻标签的模型 | `notes/PREREG_IE26_CN.md`第1、5节 |',
        '| IE30、IE33 | 2024、2025用于标签拟合。2026参与全期分档及池分布估计，因此也标样本内 | 原“2026留出”只指标签，无完整年份留出 | `PREREG_IE30_CN.md`、`PREREG_IE33_CN.md`、`ie30_logs/run*.sh`、`martin_profile_ie29.py`的binning与bin_table |',
        '| IE40、IE42、IE43、IE46、IE47 | 2024、2025；分档边界和概率表使用训练段 | 2026为模型历史留出* | 对应 `notes/PREREG_IE*_CN.md`、`ie40_work/real_fit.json`及各轮`fit.json` |',
        '| IE44 | 2024、2025拟合。2026用于规则设计，按S口径也标样本内 | 无完整留出 | `PREREG_IE44_CN.md`明确根据IE42、IE43的2026锯齿问题设计单峰偏好 |',
        '| E12、E16至E21 | 2024、2025用于原候选选择 | 2026按冻结名单逻辑作历史留出*描述；未开账户的年份本轮也只重放信号 | 对应 `notes/PREREG_E*_CN.md`、原训练工件及逐晚重放核对 |',
        '| F1、F2 | 2024、2025拟合概率表、系数及候选选择 | 2026为模型历史留出*；非原首选的数为S0固定描述，不据此换首选 | `PREREG_F1_CN.md`、`PREREG_F2_CN.md`及所有fit模型 |',
        '| M1B、M2A、M3B、F3、F4、H1、H2 | 2024、2025用于各轮选择 | 2026为本轮配置历史留出*。M系列及部分F/H沿用master等既有环节，不能声称所有祖先参数从未看过2026 | 对应 `notes/PREREG_*_CN.md`、逐轮固定候选与重放核对 |',
        '| U1画像 | 两年合并模型使用2024、2025；另有双向单年移植 | 2026虽有画像分数，但没有可评测的逐晚点名 | `u1_analysis.py`、`u1_work/model_*.json`、`scores_*.csv` |', '',
        '上述“留出*”仅保留模型当时的切分身份。它不证明整条历史研究链对2026完全未知。'
        'S0重算后再据结果选最好的系统，也不产生新的样本外资格。', '',
        '## 恢复规则和限制', '',
        'master按原priority的成交额顺序排序，截断前后分列。M1B保留取消前4截断后的原顺序；'
        'M2A保留QQQ低分许可过滤后的队列，M3B的名单与M2A相同。E12保留原形态优先及画像、成交额、共振排序，原生最多5只。', '',
        'E16的L1至L4、E17的Q1至Q5、E18的R1至R5、E19的S1至S5及E21的BASE/S1没有新增点名规则，'
        '其观察期限、消费和重试不伪造新命中。E16 N0和E20的A1至A5单列真实新点名。'
        'F3按原报价优先键恢复合并信号；F4的新信号与合并到M2A的信号分列；H1/H2按原policy.build的多头信号次序。', '',
        'D1漏斗中的IE47早期信号是观察后的触发日close口径。S0的IE47行读取初始逐晚点名，'
        '再用下一交易日open评价首锚点剩余幅度。点名和触发是不同环节，所以S0数字不等于D1的早期触发数字，旧报告没有据此改写。', '',
        'IE40的当前缓存校验因历史源码指纹变化而拒绝直接重跑。S0没有改旧脚本或重建指标库，'
        '而是读取保存的评分及指标工件，并以当时记录的源码哈希、代码序列、交易日和scope重算原签名。'
        '`historical_cache_check.json`证明行序和原签名一致。IE43冻结推断还逐年对回旧42段口径的原报告。', '',
        'IE33 C4用原代码的确定性类别划分恢复双画像概率表，保留保存的全部系数。'
        'C3缺少四个内折模型，按原预登记和原代码复演四次历史选择，再与保存的全段模型等权合并。'
        '每折旧命中数、全段旧命中数和旧2026命中数均核对一致。S0没有进入旧选择器的目标，未改候选、参数菜单或旧工件。'
        '最初protocol把“不得新增拟合”写成了过宽的“no fitting”，这一恢复解释另记在 `protocol_clarification.json`，原protocol保留。', '',
        'F1/F2已导出的点名与冻结模型重放逐晚相同。E12历史交易只用于核查该日确有原信号；'
        'E20训练事件和点名逐晚相同。F3/F4/H1/H2先将重放的所有训练特征与保存工件逐值核对，再评测信号。'
        '所有重放均只运行选股或信号生成，没有调用账户simulate，没有研究仓位或收益。', '',
        '| 不可复算系统 | 原因 | 复跑限制 |', '|---|---|---|']
    for row in missing():
        lines.append('| '+' | '.join([row['system'], row['reason'], row['why_not_rerun']])+' |')
    lines += ['', '## 规则、验证和工件', '',
        '报警规则已写入METHOD §11.2及其报告模板：覆盖数字没有同时给出宽度和样本内/留出标记，就不能进入结论。'
        '这是一条报告要求，尚未声称旧拟合器、登记版或看板自动实现了它。旧C_signal保留为不限宽度诊断，旧报告数字没有改。', '',
        '新增评测函数只处理顺序、冷却及标签统计。单测覆盖宽度截断、稳定平手、10日边界、名额不足、'
        'first−3、peak−1、恰剩一半、首锚点不重置、跨年及重叠精度。三组完整测试结果如下。', '',
        '| 测试组 | 测试数 | 结果 | 日志 |', '|---|---:|---|---|']
    for suite in ('custody', 'trader_replication', 'martin_luk'):
        t = S.read(S.OUT/f'tests_{suite}.json')
        log = (S.OUT/f'tests_{suite}.log').read_text()
        expected = re.search(r'expected failures=(\d+)', log)
        result = '通过' if t['passed'] else '失败'
        if expected:
            result += f'，{expected.group(1)}项预期失败'
        lines.append(f'| {suite} | {t["count"]} | {result} | `s0_work/tests_{suite}.log` |')
    lines += ['', 'Python均使用项目.venv及systemd scope，CPUQuota=60%、MemoryMax=900M，单线程。'
        'E12与初次H1启动曾短暂重叠，已中断H1，随后在入口加了非阻塞互斥锁。各进程未触及OOM，细节保留在 `resource_incidents.json`。'
        '测试自身使用临时目录和局部Git测试仓库；本工作树没有提交。', '',
        '复算入口为 `s0_research.py` 的各固定恢复阶段，启动时的内存和资源记录见 `runs/`，各阶段日志保留在本工件目录。'
        '报告生成与最终检查入口为 `s0_report.py`。`sources.json`记录实际输入SHA256，`protocol.json`记录开始前受保护文件，'
        '`completion.json`记录最终核对。没有联网、下载、改登记版、改看板或改旧报告数字。', '', main, '']
    (S.HOME/'reports/S0_CN.md').write_text('\n'.join(lines))
    S.write('unrecoverable.json', missing())
    return main


def complete():
    rows = records()
    protected = S.read(S.OUT/'protocol.json')['protected']
    changed = [name for name, digest in protected.items() if S.sha(S.ROOT/name) != digest]
    assert not changed, changed
    sources = S.read(S.OUT/'sources.json')
    drift = [name for name, digest in sources.items() if not name.startswith('studies/martin_luk/reports/s0_work/')
             and S.sha(S.ROOT/name) != digest]
    assert not drift, drift
    tests = {n: S.read(S.OUT/f'tests_{n}.json') for n in ('custody', 'trader_replication', 'martin_luk')}
    assert all(t['passed'] for t in tests.values())
    for suite, result in tests.items():
        log = S.OUT/f'tests_{suite}.log'
        text = log.read_text()
        assert f'Ran {result["count"]} tests' in text and '\nOK' in text, suite
        result['log_sha256'] = S.sha(log)
        expected = re.search(r'expected failures=(\d+)', text)
        result['expected_failures'] = int(expected.group(1)) if expected else 0
    observations = [r['resources'] for r in rows]+[t['resources'] for t in tests.values()]
    assert all(r['cpu_max'] == '60000 100000' and r['memory_max'] == '943718400' and r['threads'] == '1'
               for r in observations)
    expected = {'master_filtered', 'master_capped', 'M1B', 'M2A', 'M3B', 'IE9', 'IE26_E_stitched',
        'IE26_A_stitched', 'IE30_ho2026', 'IE33_ie33_c1', 'IE33_ie33_c2', 'IE33_ie33_c3', 'IE33_ie33_c4',
        'IE33_ie33_c5', 'IE40', 'IE42_regime', 'IE43_regime', 'IE44_regime', 'IE46_regime', 'IE47',
        'E12_C1', 'E12_C2', 'E12_C3', 'E12_C4', 'E12_C5', 'E16_N0', 'E20_A1', 'F1_F1a',
        'F2_G1', 'F3_V1', 'F3_V2', 'F3_V3', 'F4_V1', 'F4_V2', 'F4_V3',
        'H1A_signals', 'H1B_signals', 'H2A_signals', 'H2B_signals', 'E21_master_list'}
    assert expected <= {r['system'] for r in rows}, sorted(expected-{r['system'] for r in rows})
    for row in rows:
        for k, result in row['results'].items():
            assert [result['annual'][y]['n'] for y in S.YEARS] == [9, 22, 17]
            assert all(v['mean_new_names'] <= int(k)+1e-12 for v in result['annual'].values()) if k != 'unlimited' else True
            assert result['total']['covered'] == sum(v['covered'] for v in result['annual'].values())
    # A second existing implementation checks real S0 labels independently of the new budget helper.
    from studies.trader_replication.mainleg import selection_diagnostics
    frozen = S.labels()
    panel = S.HOME/'reports/u1_work/panel'
    codes = list(map(str, S.array(panel/'codes.npy')))
    columns = {c: codes.index(c) for c in {g['code'] for g in frozen['legs']}}
    prices = {c: {} for c in columns}
    for short, field in (('o', 'open'), ('h', 'high'), ('c', 'close')):
        matrix = S.array(panel/(field+'.npy'))
        for c, j in columns.items():
            prices[c][short] = matrix[:, j]
    di = {d: i for i, d in enumerate(frozen['calendar'])}
    picks = {di[d]: cs for d, cs in S.read(S.OUT/'picks/IE47.json').items()}
    ie47 = next(r for r in rows if r['system'] == 'IE47')
    reference = {}
    for year in S.YEARS:
        old = selection_diagnostics(picks, frozen['legs'], prices, frozen['calendar'], picks,
                                    years=(year,), k=3, training=False)
        measured = {r['key']: r['covered'] for r in ie47['results']['3']['per_leg'] if r['year'] == year}
        reference[year] = measured == {r['key']: r['signal'] for r in old['per_leg']}
    assert all(reference.values()), reference
    S.write('signal_reference_check.json', dict(ok=True, checks=reference,
        reference='existing selection_diagnostics C_signal, frozen 48 legs, original IE47 native cooldown stream'))
    before = (S.OUT/'git_head_before.txt').read_text().strip()
    after = (S.OUT/'git_head_after.txt').read_text().strip()
    assert before == after, 'workspace HEAD changed'
    summary = render()
    rate, leader, year = best(rows)
    completion = dict(status='complete', task='PLAN_S0_CN', denominator=S.sha(S.HOME/'notes/legs_frozen.json'),
        counts=dict(Counter(S.labels()['calendar'][g['first']][:4] for g in S.labels()['legs'])),
        systems=len(rows), displayed_rows=sum(len(r.get('table_aliases', [r['system']])) for r in rows),
        system_ids=[r['system'] for r in rows], unavailable=missing(), tests=tests,
        protected_files=len(protected), protected_unchanged=True, input_hashes_unchanged=True,
        no_network=True, no_new_data=True, research_account_simulations=0, no_workspace_commit=True,
        historical_fold_selections_replayed=4, S_objective_used_for_fitting=False,
        recorded_max_peak_rss_mib=max(r['peak_rss_mib'] for r in observations),
        recorded_resource_limits_match=True,
        code_sha256={str(p.relative_to(S.ROOT)): S.sha(p) for p in
            (S.HOME/'s0_research.py', S.HOME/'s0_report.py', S.ROOT/'studies/trader_replication/mainleg.py',
             S.ROOT/'studies/trader_replication/tests/test_signal_budget.py',
             S.ROOT/'skills/trader-replication/references/METHOD_CN.md')},
        best_historical_holdout=dict(system=leader['system'], year=year, K=3, coverage=rate,
            covered=value(leader, 3, year)['covered'], n=value(leader, 3, year)['n'],
            shortfall_percentage_points=100*(.8-rate), independent_out_of_sample=False),
        report_sha256=S.sha(S.HOME/'reports/S0_CN.md'), resources=S.resources())
    S.write('completion.json', completion)
    S.write('sources.json', S.SOURCES)
    S.write('artifact_manifest.json', {str(p.relative_to(S.OUT)): S.sha(p) for p in sorted(S.OUT.rglob('*'))
        if p.is_file() and p.name not in ('artifact_manifest.json', 'run.lock', 'report.log')})
    print(summary)


if __name__ == '__main__':
    S.offline()
    run_lock = (S.OUT/'run.lock').open('a')
    S.fcntl.flock(run_lock, S.fcntl.LOCK_EX | S.fcntl.LOCK_NB)
    if (S.OUT/'sources.json').exists():
        S.SOURCES.update(json.loads((S.OUT/'sources.json').read_text()))
    complete()
