"""Render saved F4 evidence; never run an account while writing the report."""
from __future__ import annotations

import re

from . import f4_research as R
from .m1_report import COLUMNS, annual_cells, table as append_table

OUT, HOME = R.OUT, R.HOME
TITLES = dict(F3_list='F3长期名单', F3_fire='F3回撤触发', master_raw='master原始信号',
              master_filtered='master过滤后信号', V1='V1：9 EMA+一支撑',
              V2='V2：9/21 EMA+一支撑', V3='V3：9/21 EMA+双支撑')


def pct(value):
    return '缺失' if value is None else f'{100*value:.2f}%'


def table(columns, rows):
    lines = []
    append_table(lines, columns, rows)
    return '\n'.join(lines)


def early_cell(row):
    dates = row['early']
    return f'{len(dates)}晚，首个{dates[0]}' if dates else '无'


def tests():
    results = {}
    for name in ('martin_luk', 'trader_replication', 'custody'):
        path = OUT/('test_'+name+'.log')
        content = path.read_text()
        count = re.search(r'Ran (\d+) tests? in', content)
        ok = bool(count and re.search(r'^OK(?:\s|$)', content, re.M) and not
                  re.search(r'^FAILED|^ERROR:|^FAIL:', content, re.M))
        assert ok, name
        results[name] = dict(ok=ok, count=int(count[1]), log=path.name, sha256=R.sha(path))
    return results


def report():
    protocol = R.registry_check()
    metrics, gate = R.read(OUT/'list_metrics.json'), R.read(OUT/'gate.json')
    selection, validation = R.read(OUT/'selection.json'), R.read(OUT/'validation_complete.json')
    prefix, compatibility = R.read(OUT/'truncation.json'), R.read(OUT/'compatibility.json')
    mechanism = R.read(OUT/'mechanism_audit.json')
    availability = R.read(OUT/'forward_availability.json')
    assert all(r['missing_future_quotes'] == 0 for r in availability['counts'].values())
    checks = tests()
    assert prefix['ok'] and compatibility['ok'] and compatibility['serialized_bytes']['ok'] and mechanism['ok']
    changed = [p for p, h in protocol['protected'].items() if R.sha(R.ROOT/p) != h]
    assert not changed, changed
    feature_hashes = {}
    for label in ('train', 'cut', 'perturbed', 'validation'):
        folder = OUT/'features'/label
        if not (folder/'meta.json').exists():
            continue
        meta = R.read(folder/'meta.json')
        feature_hashes[label] = {n: R.sha(folder/(n+'.npy')) == h for n, h in meta['sha256'].items()}
        assert all(feature_hashes[label].values())
    rows = []
    for name, result in metrics.items():
        for year in ('2024', '2025', 'all'):
            r = result['years'][year]
            base = metrics['F3_list']['years'][year]['precision']
            rows.append([TITLES[name], '两年' if year == 'all' else year, r['triggers'], r['distinct'],
                f"{r['hits']}/{r['triggers']}", pct(r['precision']),
                f"{r['precision']/base:.2f}倍" if base else '缺失', pct(r['early_precision']),
                f"{r['coverage']}/{r['denominator']}"])
    best = max(R.SPECS, key=lambda n: gate['variants'][n]['lift'])
    b = gate['variants'][best]
    choice = selection['chosen']
    if not gate['eligible']:
        conclusion = ('**三个定义均未同时通过名单精度和覆盖门槛，按预登记停止在名单层；'
                      '新增候选账户运行零次，2026名单和账户均未打开。**')
    elif choice is None:
        conclusion = '**名单已有过线变体，但账户没有合格者；2026未打开。**'
    else:
        conclusion = f'**名单过线后，以固定的M2A执行选中{choice}；2026固定验证结果见后表。研究入围不等于复刻成功。**'
    answer = (f"精度最高的{best}把名单中本人段窗口占比提高到F3长期名单的{b['lift']:.2f}倍，"
              f"从{pct(gate['reference'])}到{pct(metrics[best]['years']['all']['precision'])}。"
              f"严格覆盖为{metrics[best]['years']['2024']['coverage']}/9、"
              f"{metrics[best]['years']['2025']['coverage']}/22。")
    master_precision = metrics['master_raw']['years']['all']['precision']
    lift_text = '、'.join(f"{n} {r['lift']:.2f}倍" for n, r in gate['variants'].items())
    lines = ['# F4：首次回撤加支撑重合，名单里他的行情是否更集中', '', conclusion, '', answer, '',
        f"这只是约{(b['lift']-1)*100:.0f}%的描述性提升；{best}两年"
        f"{metrics[best]['years']['all']['triggers']}条触发中只有{metrics[best]['years']['all']['hits']}条落在本人段窗口内，"
        f"精度还低于master原始信号的{pct(master_precision)}。三种定义的倍数分别为{lift_text}，没有哪个达到3倍。", '',
        ('按本轮门槛，这个具体版本不值得继续投入账户优化；名单变窄带来的倍数，不能抵消本人行情仍未触发的缺口。'
         '保留首次回撤和支撑重合作为可解释的线索；下一步若继续，应先修正逐段漏斗中已经量出的上游缺口，另行预登记，不能靠放大仓位补。'
         if not gate['eligible'] else '是否值得继续以实际账户的H、资金与早买结果为准，不能把名单提升直接当作账户改善。'), '',
        '## 同一个窗口、同一种计数', '',
        '一个股票在一个交易夜算一条名单/触发；重叠的本人段只给该条记录计一次命中。'
        '窗口为冻结锚点前3交易日至峰值前一夜；精度只问是否落在窗口内，严格精度还要求按当晚收盘买入仍剩原涨幅至少一半。'
        '覆盖用严格要求，按段锚点年归属，分母固定9/22；跨年命中可贡献上一年覆盖，触发本身按实际触发年归属。'
        '全部选择段触发止于2025年末，没有用2026触发补覆盖。F3长期名单以全部active股票夜为分母，'
        '另列F3动作和master信号，避免把长期名单与可成交信号混作同一个来源。', '',
        table(['来源', '年', '总记录', '不同票', '本人窗口记录', '窗口精度', '相对F3名单', '严格精度', '严格覆盖'], rows), '',
        '## 冻结门槛的逐项结果', '',
        f"两年窗口精度至少{pct(gate['threshold'])}（F3长期名单的3倍），并且严格覆盖2024≥5/9、2025≥11/22。"
        '三项必须同时通过，不根据结果放宽。', '',
        table(['定义', '两年精度倍数', '精度≥3倍', '2024≥5段', '2025≥11段', '允许跑账户'],
            [[name, f"{row['lift']:.2f}", *['是' if row['checks'][k] else '否' for k in
             ('precision', 'coverage2024', 'coverage2025')], '是' if row['eligible'] else '否']
             for name, row in gate['variants'].items()]), '',
        '## 每晚名单缩到多大', '',
        table(['来源', '年', '均值', '中位', '90%分位', '最少/最多', '不同票'],
            [[TITLES[name], year, f"{r['mean']:.2f}", f"{r['median']:.1f}", f"{r['p90']:.1f}",
              f"{r['minimum']}/{r['maximum']}", r['distinct']]
             for name, result in metrics.items() for year, r in result['years'].items() if year != 'all']), '',
        '含零触发夜。没有每天固定名额，也没有按本人代码或日期选择。逐夜名单见features/train/nightly.jsonl。', '',
        '## 触发后会不会成为大行情，其中多少是他的段', '',
        '每条触发后的第1至第60个交易日最高价相对当晚收盘涨≥30%，才记为后续大行情；'
        '不能拿触发前的当日最高价充数。主表比例只用完整60日记录；2025年底不够60日的记录另列，'
        '不把未决当失败，也不借2026行情补齐。再用code+未来最高日严格对齐U1原库，'
        '“其中他的”以U1固定同峰标签为准，与上面的本人窗口精度是不同分母。'
        '三种F4定义的完整60日记录均已核对后续high无缺失。', '',
        table(['来源', '年', '完整60日', '随后大涨', '大涨比例', '对齐U1/其中他的', '本人占比', '未满60日/已见大涨'],
            [[TITLES[name], year, r['forward'].get('mature', 0), r['forward'].get('big_complete', 0), pct(r['big_rate']),
              f"{r['forward'].get('library_big_complete', 0)}/{r['forward'].get('library_his_complete', 0)}",
              pct(r['library_his_share']), f"{r['forward'].get('incomplete', 0)}/{r['forward'].get('big_incomplete', 0)}"]
             for name, result in metrics.items() for year, r in result['years'].items() if year != 'all']), '',
        table(['来源', '年', '对齐的不同U1段', '其中他的段', '去重后本人占比'],
            [[TITLES[name], year, r['unique_library'], r['unique_library_his'],
              pct(r['unique_library_his']/r['unique_library'] if r['unique_library'] else None)]
             for name, result in metrics.items() for year, r in result['years'].items() if year != 'all']), '',
        '去重表包括训练末尚未满60日但已经达到30%的记录；与完整60日主表范围不同，按实际触发年分组，不按本人锚点年。'
        'U1同票不同峰可重叠，去重库段也不代表彼此独立的趋势。', '',
        '## 逐段触发', '',
        table(['段', 'F3名单早买夜', 'master原信号早买夜', 'V1早触发', 'V2早触发', 'V3早触发'],
            [[g['key'], *[early_cell(metrics[name]['legs'][i]) for name in
              ('F3_list', 'master_raw', 'V1', 'V2', 'V3')]]
             for i, g in enumerate(metrics['V1']['legs'])]), '',
        '这31段均保留，未因定义没触发而删掉。逐条窗口命中、剩余半程、未来峰值与U1对齐见evaluation_events.jsonl；'
        '这些标签只在市场状态和触发落盘后读取。', '',
        '## 早买窗口内的逐段漏斗', '',
        table(['年/段数', '存在领涨状态', '首次回撤进行中', '回撤触9/21', '当夜支撑重合', '当夜双支撑', 'V1触发', 'V2触发', 'V3触发'],
            [[year+'/'+str(sum(g['year'] == year for g in mechanism['funnel'])),
              *[sum(g['year'] == year and g[key] > 0 for g in mechanism['funnel']) for key in
                ('leader', 'first_pullback', 'touch', 'confluence', 'double', 'V1', 'V2', 'V3')]]
             for year in ('2024', '2025')]), '',
        '表内按段计存在至少一晚，所有晚均须仍剩本人原涨幅一半；各列未必是同一晚，'
        '已合格支撑可以从本次回撤更早一晚带入，因此不能把列差直接当成单一规则的独立损失。'
        '逐段夜数保留在mechanism_audit.json。这里没有账户资金竞争；未触发的缺口发生在来源定义层。', '',
        '## 定义与局限', '',
        '新领涨由1/3/6月前10%首次升级或9>21>50 EMA首次成立识别。首次回撤在首个收回动作后消费，'
        '即使支撑不合格或报价被拒绝也不重复；重新超过回撤前高后下一晚才可再武装。'
        '三种定义分别为9 EMA+一支撑、9/21 EMA+一支撑、9/21 EMA+两项不同价位支撑。'
        '支撑包括20日前高突破位、大量向上缺口上沿、最近放量跳空/突破的日K累计均价、整理区上沿，最多60夜。'
        '双支撑至少相隔0.1 ADR，避免同一突破位重复计数。精确定义与所有距离、期限在预登记中冻结。', '',
        '日K累计典型价只是AVWAP近似；收回、握手也是日K近似。当前版本的首次状态、支撑有效期、'
        '每日收回的切分是本轮待检验的具体实现；失败不能归给本人方法，不能据此断言日K不能复刻。', '',
        '## 账户与2026', '']
    if gate['eligible']:
        account_rows = []
        for name in gate['eligible']:
            for execution in ('M2A', 'M3B'):
                result = R.read(OUT/f'candidates/{name}_{execution}/metrics.json')
                account_rows += [annual_cells(name+'_'+execution, y, r) for y, r in result['years'].items()]
        for name, folder in (('M2A', 'm2_work'), ('M3B', 'm3_work')):
            result = R.read(HOME/f'reports/{folder}/candidates/{name}/metrics.json')
            account_rows += [annual_cells(name, y, r) for y, r in result['years'].items()]
        lines += [table(COLUMNS, account_rows), '',
            f"唯一选择执行为{R.PRIMARY}，选中者：{choice or '无'}。M3B仅敏感性对照。", '']
        if choice:
            lines += [table(COLUMNS, [annual_cells(label+'_'+choice, y, r) for label in ('standalone', 'continuous')
                for y, r in R.read(OUT/f'validation/{label}/metrics.json')['years'].items() if y == '2026']), '']
    else:
        lines += ['名单闸门失败，按任务书没有运行新增候选账户。M2A/M3B的四次原账户重放仅检验兼容性，'
                  '与F4新增来源收益评测分开。2026名单统计、候选单开和连续账户均为零次。', '']
    lines += ['## 工程验收', '',
        '真实截断至2025-06-30、CUT后OHLC×3/量×2/额×6的扰动输入分别重建全部滚动量、'
        '横截面、状态和支撑，CORE及全部状态/触发逐值相同；报价前缀也完全一致。'
        '没有只裁剪已经算好的状态。构建阶段禁止读取本人台账、段表与U1标签库。'
        f"另用独立标量状态机复核{mechanism['independently_rebuilt_stocks']}只股票、"
        f"{mechanism['scalar_sessions']}个股票夜，重新计算各支撑和前10%升级，全部状态/触发一致；"
        '实际尝试读取段表确认构建期会拒绝，并流式核对全部评测记录计数。'
        'M2A/M3B原训练与完整连续台账、权益逐值一致，实际序列化文件SHA256也一致；'
        '共享引擎没有修改，登记与看板及旧研究工件指纹未变。', '',
        table(['测试组', '数量', '结果', '日志'], [[n, r['count'], 'OK', f"[日志](f4_work/{r['log']})"]
              for n, r in checks.items()]), '',
        '所有研究及测试用.venv、CPUQuota=60%、MemoryMax=900M、单进程单线程；按票/日期处理，'
        '只读原数组使用mmap，没有全市场N×N矩阵。实际cgroup和RSS记录见各阶段meta和completion.json。'
        '安装器拒绝覆盖既有hooksPath；已核对原pre-commit/pre-push均调用secret_guard.py，未绕过。', '',
        f"预登记SHA256：`{protocol['prereg_sha256']}`。正式阶段有独占开始文件，防止重复计算后悄悄择优。", '',
        '```bash',
        'RUN=(systemd-run --scope -p CPUQuota=60% -p MemoryMax=900M -q env OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 PYTHONDONTWRITEBYTECODE=1 .venv/bin/python)',
        '"${RUN[@]}" -m studies.martin_luk.f4_research freeze',
        '"${RUN[@]}" -m studies.martin_luk.f4_research prepare',
        '"${RUN[@]}" -m studies.martin_luk.f4_research evaluate',
        '"${RUN[@]}" -m studies.martin_luk.f4_research prefix',
        '"${RUN[@]}" -m studies.martin_luk.reports.f4_work.verify_delivery compatibility',
        '"${RUN[@]}" -m studies.martin_luk.f4_research accounts',
        '"${RUN[@]}" -m studies.martin_luk.reports.f4_work.verify_delivery audit',
        '"${RUN[@]}" -m studies.martin_luk.f4_report', '```', '',
        '以上是首次执行顺序；同一输出目录不能重跑正式阶段。report仅重新读取工件，不重跑名单或账户。', '']
    path = HOME/'reports/F4_CN.md'
    path.write_text('\n'.join(lines), encoding='utf-8')
    R.write('completion.json', dict(ok=True, research_completed=True, strategy_success=False,
        chosen=choice, list_eligible=gate['eligible'], gate=gate, tests=checks,
        candidate_account_evaluations=selection['candidate_account_evaluations'], validation=validation,
        truncation=prefix, compatibility=compatibility, mechanism_audit=mechanism,
        forward_availability=availability, preregistration_unchanged=True,
        prereg_sha256=protocol['prereg_sha256'], source_sha256=protocol['source_sha256'],
        protected_files=len(protocol['protected']), protected_unchanged=True, feature_hashes=feature_hashes,
        report_sha256=R.sha(path), resources=dict(report=R.resources(),
            stages={label: R.read(OUT/'features'/label/'meta.json')['resources'] for label in feature_hashes}),
        implementation_revision=R.read(OUT/'implementation_revision.json'),
        delivery_revision=R.read(OUT/'delivery_revision.json'), labels_only_in_evaluation=True,
        test_resources={name: R.read(OUT/('test_'+name+'_resources.json')) for name in checks},
        network_disabled=True, new_data=False, git_commit=False, shared_engine_changed=False,
        registration_changed=False, board_changed=False, independent_out_of_sample=False))
    artifacts = {str(p.relative_to(OUT)): R.sha(p) for p in OUT.rglob('*') if p.is_file()
                 and p.name != 'artifact_manifest.json'}
    R.write('artifact_manifest.json', artifacts)
    print('\n'.join(['F4完成：'+('名单闸门失败，停止在名单层。' if not gate['eligible'] else '账户阶段已按固定选择执行。'),
        answer, f"入围名单：{','.join(gate['eligible']) or '无'}；新增候选账户：{selection['candidate_account_evaluations']}次。",
        '2026单开/连续：'+str(validation['standalone_evaluations'])+'/'+str(validation['continuous_evaluations'])+'次。',
        '这条路：'+('本版本未过覆盖与精度闸门，先修名单，不继续优化账户。' if not gate['eligible'] else '按固定账户资格评判，名单改善不等于复刻成功。'),
        '截断、未来扰动、原台账重放及三组测试：通过。',
        '报告：studies/martin_luk/reports/F4_CN.md',
        '工件：studies/martin_luk/reports/f4_work/completion.json']))


def main():
    R.offline()
    report()


if __name__ == '__main__':
    main()
