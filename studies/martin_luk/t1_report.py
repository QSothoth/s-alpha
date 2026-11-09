"""Render and verify T1 from saved attribution; never recompute an account."""
import argparse
from . import t1_research as T

NAMES = dict(IE47_C062='IE47+C062', master_C062='master+C062', registered_master='登记master',
             M1B='M1B', M2A='M2A', M3B='M3B')


def table(headers, rows):
    return '\n'.join(['| '+' | '.join(headers)+' |', '| '+' | '.join('---' for _ in headers)+' |']+
                     ['| '+' | '.join(map(str, row))+' |' for row in rows])


def pct(v):
    return '—' if v is None else f'{100*v:.1f}%'


def num(v):
    return '—' if v is None else f'{v:+.3f}'


def interval(s):
    return f"{pct(s['median'])} [{pct(s['q05'])}, {pct(s['q95'])}]"


def results():
    accounts = T.read(T.OUT/'accounts.json')
    return [(name, year, account['strict'][year], account['modes']['correlation'][year], account)
            for name, account in accounts.items() for year in T.YEARS]


def test_results():
    return {group: T.read(T.OUT/('test_'+group+'_resources.json'))
            for group in ('martin_luk', 'trader_replication', 'custody')}


def render():
    rows, groups = results(), T.read(T.OUT/'groups_summary.json')
    passed = sum(r['cap_equity'] >= .5 and r['purity_gross'] >= .6 for _, _, _, r, _ in rows)
    capital_pass = sum(r['cap_equity'] >= .5 for _, _, _, r, _ in rows)
    gross_pass = sum(r['purity_gross'] >= .6 for _, _, _, r, _ in rows)
    maxcap = max(rows, key=lambda x: x[3]['cap_equity'])
    maxgross = max(rows, key=lambda x: x[3]['purity_gross'])
    cap_increases = [100*(r['cap_equity']-b['cap_equity']) for _, _, b, r, _ in rows]
    gross_increases = [100*(r['purity_gross']-b['purity_gross']) for _, _, b, r, _ in rows]
    cap_lifts = [100*(r['cap_equity']-a['random']['correlation'][y]['cap_equity']['median']) for _, y, _, r, a in rows]
    gp_lifts = [100*(r['purity_gross']-a['random']['correlation'][y]['purity_gross']['median']) for _, y, _, r, a in rows]
    broad = groups['overwide_legs']
    lines = ['# T1：把同期同伴也算进来，钱和利润有多接近他的题材', '',
        f'**相关同伴口径下，六组连续账户、三年共18行，资金50%与毛利60%同时达到{passed}行。'
        f'资金单项达到{capital_pass}行，毛利单项达到{gross_pass}行。**', '',
        f'最高资金纯度为{NAMES[maxcap[0]]}的{maxcap[1]}年{pct(maxcap[3]["cap_equity"])}；'
        f'最高毛利纯度为{NAMES[maxgross[0]]}的{maxgross[1]}年{pct(maxgross[3]["purity_gross"])}。'
        '这两个最大值可能来自不同账户或年份，不能拼成一个达标结果。', '',
        f'相对原Y1归因，资金增加{min(cap_increases):.1f}至{max(cap_increases):.1f}个百分点，'
        f'毛利变化{min(gross_increases):+.1f}至{max(gross_increases):+.1f}个百分点。'
        f'48段中有{broad}段至少一晚同伴数超过当晚U4池的20%。'
        f'与同样大小的随机组中位数相比，实际相关组资金差为{min(cap_lifts):+.1f}至{max(cap_lifts):+.1f}个百分点，'
        f'毛利差为{min(gp_lifts):+.1f}至{max(gp_lifts):+.1f}个百分点。', '',
        '相关组表示过去60日日收益一起变动，不能直接证明它们属于相同新闻题材。'
        '是否过宽，要结合后面的逐段组大小、题材并集及随机审计；高于随机只表示这一定义有区分，不能据此改选股或宣称策略有效。', '',
        '**行业口径(a)缺少合规历史输入。** 冻结面板没有行业或子行业字段；本地industry_us.json只有当前快照，没有历史有效日期。'
        '所以(a)的资金、毛利、前十赢单及同期同题材pnl均记为不可用；下文另报快照参考，不能当作当晚可见结果。没有联网补资料。', '',
        '下表为严格Y1 → 相关题材(b)。资金是全年平均的题材收盘市值/真实账户权益，空仓日照计；'
        '毛利是同一FIFO和时间切片上的正pnl。差距单位为百分点，负值表示已经超过该单项目标。', '',
        table(['账户', '年', 'Y1资金', '相关题材资金', '距50%', 'Y1毛利', '相关题材毛利', '距60%', '前10题材赢单'],
              [(NAMES[n], y, pct(b['cap_equity']), pct(r['cap_equity']), f"{r['distance_capital_pp']:.1f}",
                pct(b['purity_gross']), pct(r['purity_gross']), f"{r['distance_gross_pp']:.1f}",
                f"{b['top10_his_leg']} → {r['top10_his_leg']}") for n, y, b, r, _ in rows]), '',
        '六组都直接读取完整2024-01-02至2026-10-16连续台账，没有重跑账户。'
        'M1B/M2A/M3B旧F3、F4汇报的2024–25利润列来自截至2025年末的训练账户；本表全部来自完整连续账，'
        '2025开仓并在2026退出的交易仍归2025，因此毛利分母和前十赢单会不同，旧数字没有改写。'
        '登记master保留原R74+S7全账，144笔空头均为O，分母及权益仍含这些交易。', '',
        '新增的钱来自哪里：H与pnl单位均为初始本金1，不是年度收益。'
        '“同期未见本人公开段”是新增同伴切片中不属于本人同票公开大段/小段窗口的部分；'
        '不把他在同年其他时候做过的股票排除，也不推测未记录交易。', '',
        table(['账户', '年', '原Y1 H', '新增同伴pnl', '题材H', '同期未见本人公开段pnl', '占题材净H', '占账户净pnl', '占题材毛利'],
              [(NAMES[n], y, num(b['H']), num(r['peer_h_pnl']), num(r['H']), num(r['unseen_peer_h_pnl']),
                pct(r['unseen_peer_pnl_share_H']), pct(r['unseen_peer_pnl_share_all']),
                pct(r['unseen_peer_gross_share_H'])) for n, y, b, r, _ in rows]), '',
        '净pnl分母不为正时记“—”；净占比可以为负或超过100%，不截尾。题材H=原Y1 H+新增同伴pnl逐行对平。'
        '前十赢单仍按整笔真实已平仓pnl排序，只有其题材窗口内净贡献>0才计数，end估值不当赢单。', '',
        '随机对照仅审计定义：每段、每个买入夜，保持实际同伴数量、同一可比较U4池和同一窗口，'
        '等概率无放回抽取100次；中心自身排除，原Y1 H始终保留。所有账户复用相同抽签。'
        '相关池要求完整60个日收益且非零方差；快照参考池要求行业已知。下列中括号为100次的5%至95%分位。', '',
        table(['账户', '年', '实际资金', '随机资金中位[5%,95%]', '资金差', '实际毛利', '随机毛利中位[5%,95%]', '毛利差'],
              [(NAMES[n], y, pct(r['cap_equity']), interval(a['random']['correlation'][y]['cap_equity']),
                f"{100*(r['cap_equity']-a['random']['correlation'][y]['cap_equity']['median']):+.1f}",
                pct(r['purity_gross']), interval(a['random']['correlation'][y]['purity_gross']),
                f"{100*(r['purity_gross']-a['random']['correlation'][y]['purity_gross']['median']):+.1f}")
               for n, y, _, r, a in rows]), '',
        '以下逐段包含窗口内每一晚；中心不在U4、历史不完整或无方差的夜晚以0个同伴保留，并报告可用夜数。'
        '同伴不含自身，只有与中心直接相关≥0.6的股票，不进行传递聚类。超过池20%的任一夜就给该段标“过宽”。', '',
        table(['本人段', '可用夜/窗口夜', '同伴数中位', '25%–75%', '最少–最多', '最大占当晚池', '过宽夜'],
              [(s['key'], f"{s['usable_nights']}/{s['nights']}", f"{s['correlation']['median']:.1f}",
                f"{s['correlation']['q25']:.1f}–{s['correlation']['q75']:.1f}",
                f"{s['correlation']['minimum']:.0f}–{s['correlation']['maximum']:.0f}", pct(s['max_pool_fraction']),
                str(s['overwide_nights'])+('（过宽）' if s['overwide_nights'] else '')) for s in groups['legs']]), '',
        '多个小组的并集也可能很宽。下表是活跃窗口晚的“所有相关同伴+池内中心”并集/当晚U4池；'
        '它只描述标签覆盖面，不等于真实账户的资金比例。', '']
    union_rows = []
    for year in T.YEARS:
        all_nights = [r for r in groups['nightly_union'] if r['day'].startswith(year)]
        active = [r['correlation'] for r in all_nights if r['active']]
        s = T.spread(active)
        union_rows.append((year, f'{len(active)}/{len(all_nights)}', pct(s['median']), pct(s['q90']),
                           pct(s['maximum']), sum(v > .2 for v in active)))
    lines += [table(['年', '有窗口夜/全部夜', '并集中位', '90%分位', '最大', '并集>20%夜'], union_rows), '',
        '本轮同伴按lot买入当晚的关系冻结，不是每日回头替已经买入的仓位重新分组。'
        '买入必须在[first−3,peak)且至少持有至first；窗口前已经买入的仓位不能追溯变成H。'
        '每夜相关只读过去61个收盘形成的60个简单收益，双方须在当晚U4。'
        '同伴数的逐夜分布是持续滚动的关系，持仓则遵守这条买入归属规则。', '',
        '本人段窗口仍有事后峰值，这是评测标签；它没有进入选股或账户决策。'
        '新增同伴在多个有效段之间取窗口并集，到最晚有效峰日收盘截止，同一lot只计一次。'
        '原H/T2/峰后边界保留，新增题材截止再切片；费用在真实成交片、pnl残差在最终片，峰日切片不虚构卖费。'
        '额外切片可能把一笔总亏损分成窗口内盈利、窗口外亏损，所以毛利分母随定义变化；各账户JSON公开原/新gross金额。', '',
        '**当前行业快照参考（非当晚可见口径(a)）**：仅同一已知行业的其他U4股票。'
        f'48段中{len(groups["unknown_industry_centers"])}段的中心没有已知行业，不把“未分类”凑成一个大组。'
        '这也不是量子、AI等新闻题材标签。', '',
        table(['账户', '年', '快照资金', '快照毛利', '前10快照赢单', '随机资金中位', '随机毛利中位'],
              [(NAMES[n], y, pct(a['modes']['industry_snapshot'][y]['cap_equity']),
                pct(a['modes']['industry_snapshot'][y]['purity_gross']),
                a['modes']['industry_snapshot'][y]['top10_his_leg'],
                pct(a['random']['industry_snapshot'][y]['cap_equity']['median']),
                pct(a['random']['industry_snapshot'][y]['purity_gross']['median'])) for n, y, _, _, a in rows]), '',
        '快照参考的同期同伴净pnl、毛利份额、逐段组大小与100次随机分布也保存在同名工件中；'
        '它们不能填补正式行业历史数据缺口。', '',
        '工程核验保留五个已有完整连续账户的原Y1资金、毛利、H、gross、总pnl和前十赢单逐值复核，'
        '登记master另与U1全部48段的多头H逐值相同。全账pnl、分片pnl、H增量对账，'
        '题材资金不小于原H，全部持仓市值逐日不变。'
        '真实行情截断至2025-06-30以及仅扰动未来OHLC×3、成交额×6后，重新计算池和相关组，前缀逐值一致。', '']
    checks = test_results()
    lines += [table(['测试组', '数量', '结果', '日志'],
        [(g, r['tests'], 'OK' if r['ok'] else 'FAIL', f'[日志](t1_work/test_{g}.log)') for g, r in checks.items()]), '',
        '新增单测覆盖相关的标量对照、未来数据隔离、池与中心独立、缺失/平价序列、未知行业、默认关闭、'
        '重叠并集、费用/FIFO、同期公开小段、同日卖出与期末估值。完整要求及计算前固定定义见'
        '[protocol.md](t1_work/protocol.md)，审计与资源、输入/旧报告/登记/看板指纹和工件SHA256见'
        '[completion.json](t1_work/completion.json)。', '',
        '所有计算与三组测试使用.venv、CPUQuota=60%、MemoryMax=900M、单线程。'
        '只读mmap按日期处理，仅算活跃中心到当晚U4的相关，不构造全市场N×N矩阵。'
        '新增评测函数默认保持原Y1，未改mainleg、账户引擎、登记或看板。'
        '密钥安装器因既有hooksPath拒绝覆盖，既有pre-commit/pre-push均调用secret_guard.py；本轮全程离线，没有提交git。', '',
        '重新渲染只读工件，不重测账户：', '',
        '```bash',
        'systemd-run --scope -p CPUQuota=60% -p MemoryMax=900M -q env OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1 PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m studies.martin_luk.t1_report render',
        '```', '']
    T.REPORT.write_text('\n'.join(lines))


def verify():
    T.once('verify')
    protocol, evaluated = T.read(T.OUT/'protocol.json'), T.read(T.OUT/'evaluate_complete.json')
    tests = test_results()
    assert all(t['ok'] for t in tests.values())
    unchanged = {}
    for category in ('inputs', 'protected'):
        changes = [path for path, digest in protocol[category].items() if T.sha(T.ROOT/path) != digest]
        assert not changes, (category, changes)
        unchanged[category] = True
    assert T.read(T.OUT/'prefix.json')['ok']
    assert evaluated['accounts'] == 6 and evaluated['strategy_runs'] == 0
    stages = [T.read(T.OUT/(n+'_started.json'))['resources'] for n in ('freeze', 'groups', 'evaluate', 'prefix', 'verify')]
    for r in stages+[t['after'] for t in tests.values()]:
        assert r['cpu_max'] == '60000 100000' and r['memory_max'] == str(900*1024**2) and r['threads'] == 1
    artifacts = {str(p.relative_to(T.OUT)): dict(bytes=p.stat().st_size, sha256=T.sha(p))
                 for p in sorted(T.OUT.rglob('*')) if p.is_file() and p.name != 'completion.json'}
    T.write('completion.json', dict(task='PLAN_T1_CN.md', complete=True,
        industry_a=dict(available=False, requirement_conditional_on_panel_field=True,
                        reason='no panel field or point-in-time history; snapshot is separately labeled'),
        requirements=dict(six_continuous_accounts=True, original_y1_and_two_definitions_reported=True,
                          per_leg_sizes_and_twenty_percent_flags=True, top10_and_peer_pnl_shares=True,
                          size_matched_random_definition_audit=True, target_distances_reported=True),
        unchanged=unchanged, compatibility=T.read(T.OUT/'compatibility.json'),
        tests=tests, prefix=T.read(T.OUT/'prefix.json'), resources=T.resources(),
        evaluation=evaluated, artifacts=artifacts, report_sha256=T.sha(T.REPORT),
        network_used=False, new_data=False, git_commits=False, strategy_runs=0,
        registered_or_board_changes=False, independent_out_of_sample=False))
    rows = results()
    print(f'T1 complete: 6 accounts x 3 years; {sum(r[3]["cap_equity"] >= .5 and r[3]["purity_gross"] >= .6 for r in rows)}/18 pass both purity lines')
    print('Report: studies/martin_luk/reports/T1_CN.md')
    print('Artifacts: studies/martin_luk/reports/t1_work/completion.json')
    print('Tests: '+', '.join(f'{g} {v["tests"]} OK' for g, v in tests.items()))
    print('Industry history unavailable; snapshot is descriptive only. Offline; no account/default/registry/board changes.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=('render', 'verify'))
    args = parser.parse_args()
    T.offline()
    globals()[args.stage]()


if __name__ == '__main__':
    main()
