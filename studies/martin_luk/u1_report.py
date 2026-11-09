"""Render U1 from closed evaluation artifacts; never refit or re-evaluate."""
import argparse
from collections import defaultdict
import csv
from pathlib import Path
import re
import statistics

from . import u1_research as U


def percent(value):
    return '—' if value is None else f'{100*value:.1f}%'


def number(value, digits=2):
    return '—' if value is None else f'{value:.{digits}f}'


def table(headers, rows):
    return '\n'.join(['| '+' | '.join(headers)+' |', '| '+' | '.join('---' for _ in headers)+' |',
                      *['| '+' | '.join(map(str, row))+' |' for row in rows]])


def tests():
    result = {}
    for group in ('custody', 'martin_luk', 'trader_replication'):
        path = U.WORK/('test_'+group+'.log')
        if not path.exists():
            result[group] = dict(ok=False, reason='not yet run')
            continue
        text = path.read_text(encoding='utf-8')
        run = re.findall(r'Ran (\d+) tests? in ([0-9.]+)s', text)
        ending = text.rstrip().splitlines()[-1]
        result[group] = dict(ok=bool(re.fullmatch(r'OK(?: \([^\n]*\))?', ending)) and bool(run),
            n=int(run[-1][0]) if run else None, seconds=float(run[-1][1]) if run else None,
            ending=ending, sha256=U.sha(path), log=path.name)
    return result


def readout():
    """Aggregate sealed results for the report; no scores or labels are rebuilt."""
    legs = U.library()
    frozen = U.read(U.FROZEN)['legs']
    targets = {g['key']: g for g in frozen}
    matched = [g for g in legs if g['his']]
    offsets = [g['first']-targets[g['target']]['first'] for g in matched]
    result = dict(library_matched=len(matched), representative_offset_median=statistics.median(offsets),
        representative_next_open_before_Y1=sum(g['first']+1 < targets[g['target']]['first']-3 for g in matched),
        offset_min=min(offsets), offset_max=max(offsets), years={}, fitting_collapsed_binary={},
        note='descriptive aggregation of sealed artifacts; no model, prediction, or outcome re-evaluation')
    for year in U.YEARS:
        part = [g for g in legs if g['year'] == year]
        by = defaultdict(list)
        for g in part:
            by[g['code']].append(g)
        overlap = clusters = 0
        for series in by.values():
            peak = -1
            for g in sorted(series, key=lambda x: x['first']):
                if g['first'] <= peak:
                    overlap += 1
                else:
                    clusters += 1
                peak = max(peak, g['peak'])
        ambiguous = sum(not g['his'] and any(h['code'] == g['code'] and g['first'] < h['peak']
            and g['peak'] >= h['first']-3 for h in frozen) for g in part)
        cases = [r for r in U.read(U.WORK/'oracle_scenarios.json') if r['year'] == year
                 and r['selection'] == 'retrospective_target_year_top'
                 and r['kind'] in ('in_sample_diagnostic', 'fixed_validation')]
        row = dict(n=len(part), different_codes=len(by), overlap_with_previous_same_code=overlap,
            connected_intervals=clusters, peak_at_60=sum(g['duration'] == 60 for g in part),
            negative_code_interval_overlapping_frozen=ambiguous)
        for field in ('relaxed_cap_equity_280', 'relaxed_gross', 'strict_cap_equity_280', 'strict_gross'):
            output = field.replace('_cap_equity_', '_cap_')
            row['max_'+output] = max(r[field] or 0 for r in cases)
        result['years'][year] = row
    for source in ('2024', '2025', '2024_2025'):
        model = U.read(U.WORK/('model_'+source+'.json'))
        result['fitting_collapsed_binary'][source] = [n for n, lo, hi in zip(model['features'], model['low'], model['high']) if lo == hi]
    U.write('readout.json', result)


def render():
    meta = U.read(U.WORK/'prepare.json')
    features = U.read(U.WORK/'features.json')
    annual = U.read(U.WORK/'annual_library.json')
    strata = U.read(U.WORK/'strata.json')
    discrimination = U.read(U.WORK/'discrimination.json')
    scenarios = U.read(U.WORK/'oracle_scenarios.json')
    patterns = U.read(U.WORK/'patterns_48.json')
    capacity = U.read(U.WORK/'calendar_capacity.json')
    five = U.read(U.WORK/'five_percent_scenario.json')
    fit = U.read(U.WORK/'fit.json')
    descriptive = U.read(U.WORK/'readout.json')
    checks = tests()
    lines = ['# U1：大行情里面，日 K 能否认出他的行情', '',
             (U.WORK/'conclusion.md').read_text(encoding='utf-8').strip(), '',
             '## 1. 用同一种起点看全体股票', '',
             '本地冻结v1面板含3433只股票，日历为2023-01-03至2026-10-16；2023只作暖机。'
             '“全市场”在本报告指这份完整面板，未声称它含全部历史上市证券。价格≥2美元、完整20日成交额均值≥5000万美元、完整20日ADR≥3%，与master U4相同。', '',
             '当晚首次收盘超过此前20日最高收盘，或前晚收盘≤前晚21 EMA、当晚收盘>当晚21 EMA，构成一个起点。'
             '连续创新高只取第一晚；收回均线不加事后确认。它们分别近似突破整理、回调再起。'
             '随后只在标签侧调用原mainleg.legs：当日至后60个交易日最高high至少涨30%，同票同峰合并，最早合格起点作统一代表。'
             '他的票与其他票完全相同，没有给他的样本另外选一个更漂亮的起点。', '',
             table(['起点年', '大行情段', '严格同票同峰的他的段', '占比', '完整60日段/其中他的', '截断段', '本人锚点年固定分母'],
                   [[y, annual[y]['n'], annual[y]['his'], percent(annual[y]['precision']),
                     f"{annual[y]['complete_n']}/{annual[y]['complete_his']}", annual[y]['censored_n'],
                     annual[y]['frozen_anchor_denominator']] for y in U.YEARS]), '',
             '上表按统一起点年归属，不等同于原48段的锚点年。严格同峰只有code和peak完全相同才算；'
             '因60日滚动窗口产生的相近峰值不硬并。未对齐的48段仍留在后表及分母。'
             '尚未满60日且尚未涨30%的起点属于未决，未塞进已失败样本。', '',
             table(['年', '原始局部起点', '已观察到≥30%的起点', '完整60日且<30%', '未决<30%'],
                   [[y, meta['seed_census'][y]['local_starts'], meta['seed_census'][y]['observed_ge30'],
                     meta['seed_census'][y].get('complete_lt30', 0), meta['seed_census'][y].get('unresolved_lt30', 0)]
                    for y in U.YEARS]), '',
             '同票不同峰的区间可能重叠，因此“5711段”不是5711次互不相干的趋势。'
             '原始局部起点及每个合并段的全部起点保存在library.jsonl。模型每个合并段只投一票，七个偏移夜不扩成七个独立样本。', '',
             table(['年', '不同股票', '与前段重叠的同票段', '相连区间数', '峰恰在第60日', '负标签但同票区间与冻结段相交'],
                   [[y, descriptive['years'][y]['different_codes'],
                     descriptive['years'][y]['overlap_with_previous_same_code'], descriptive['years'][y]['connected_intervals'],
                     descriptive['years'][y]['peak_at_60'], descriptive['years'][y]['negative_code_interval_overlapping_frozen']]
                    for y in U.YEARS]), '',
             '最后一列只是标签歧义审计，不把区间相交直接重贴为H，也未据此重拟合或另算2026成绩。'
             '严格同峰口径会把同票但峰不同的相交区间列入负组，所以本报告的0.7%–1.0%不是所有独立趋势起点的自然基准率。'
             '相连区间数只说明重复程度，跨长期上涨连在一起的区间也未必是同一笔交易。', '',
             '### 成交额与段长分层', '']
    for kind, title in (('liquidity_quartile', '当晚U4成交额分位'), ('duration', '起点至峰值天数'),
                         ('peer_resonance', '当晚同伴共振')):
        group = [r for r in strata if r['kind'] == kind]
        lines += [title+'。', '', table(['年', '分组', '全部段', '他的段', '占比'],
            [[r['year'], r['group'], r['n'], r['his'], percent(r['precision'])] for r in group]), '']
    lines += ['### 行业是描述标签，题材强度用当晚同伴近似', '',
        '已有industry_us.json是当前行业快照，没有历史版本。本轮只用它分组描述，不输入起点、模型、排序或资金换算，'
        '也不把它当作历史行业强度。未拉新闻或新行业数据。真实题材名称及其历史变更无法由这份日K面板验证；'
        '同期强度用60日完整简单收益相关≥0.6的其他U4股票近似，强同伴指当晚月涨幅前20%的同伴。相关块≤128×128，剔除自身。', '',
        '下表列有本人段的行业，其余全部分组在strata.json。', '',
        table(['年', '当前行业快照', '全部段', '他的段', '占比'],
              [[r['year'], r['group'], r['n'], r['his'], percent(r['precision'])]
               for r in strata if r['kind'] == 'industry_snapshot' and r['his']]), '',
        '## 2. 单项能分开多少', '',
        f"共{len(features['names'])}项日频特征，起点−3至+3每晚分别计算。v1.1日K、D1画像、F2分位/同伴/资金项均保留，"
        '未读取H4、小时线、分钟线或期权字段。原值、四分位、可用样本、缺失和AUC全表见single_features.csv。'
        '下面固定展示主要画像，单元格为“他的中位/其他中位；AUC”。AUC按数值越大越像他计算，'
        '0.5表示没有排序区分度，低于0.5表示小值方向更像他，未按目标年反向重选模型。', '']
    with (U.WORK/'single_features.csv').open(encoding='utf-8') as stream:
        single = {(r['year'], r['feature']): r for r in csv.DictReader(stream) if r['offset'] == '0'}
    fields = [('20日成交额，百万美元', 'dollar_vol20_M'), ('ADR，%', 'adr20_pct'),
        ('1月涨幅，%', 'perf21_pct'), ('3月涨幅，%', 'perf63_pct'), ('6月涨幅，%', 'perf126_pct'),
        ('距一年高点，%', 'from_high252_pct'), ('距一年低点，%', 'low252_distance_pct'),
        ('离9 EMA，ADR', 'ext_ema9_adr'), ('离21 EMA，ADR', 'ext_ema21_adr'),
        ('距最近短均线，绝对ADR', 'support_near_adr'), ('9/21间距，ADR', 'ema9_21_gap_adr'),
        ('当日量比', 'rvol20'), ('三日量比', 'rvol3_20'), ('三日振幅/ADR', 'contract3_adr'),
        ('当日成交额/20日均额', 'dollar_vol_today_vs20'), ('开盘跳空，%', 'gap_pct'),
        ('近3晚≥10%跳空', 'ep10_recent3'), ('过去财报距离，最多120日', 'earn_days'),
        ('最近已知财报反应跳空，%', 'earnings_gap_pct'), ('近3晚财报≥10%跳空', 'earn_ep10_recent3'),
        ('长期强势记忆', 'long_strength_memory'), ('强同伴数', 'peer_leaders20_count'),
        ('同伴月强度中位的分位', 'peer_perf21_median_pctl'), ('成交额×6月强度', 'money_rs126_product'),
        ('20日/120日成交额关注度分位', 'attention20_120_pctl')]
    rows = []
    for label, name in fields:
        row = [label]
        for year in U.YEARS:
            r = single[(year, name)]
            def parsed(k):
                return float(r[k]) if r[k] else None
            row.append(f"{number(parsed('his_median'))}/{number(parsed('other_median'))}；{number(parsed('auc'), 3)}")
        rows.append(row)
    lines += [table(['项目', '2024', '2025', '2026'], rows), '',
        '较稳定的是ADR偏高，单项AUC为0.792/0.759/0.661；成交额为0.489/0.757/0.874，年份差异很大。'
        '六个月涨幅为0.543/0.690/0.405，同伴月强度中位分位为0.634/0.416/0.457，方向不能直接跨年搬。'
        '最近均线距离为0.500/0.447/0.636，也不是统一偏好。这里是统一大行情起点；D1在本人锚点附近看到的准备期画像，'
        '不能未经转换就当成大趋势最初起点的画像。没有单项被本轮提升为新筛选规则。', '',
        '财报只使用已发生记录：BEFORE在当日反应，AFTER、REGULAR及未知时间保守延至下一交易日，'
        '非交易日顺延；不使用“距离下一次财报”或无法核定当时已公布的未来日程。'
        '普通≥10%跳空只是EP形态近似，另列已知财报反应，不能把所有跳空说成财报催化。'
        '同晚1/3/6月相对QQQ分位与对应涨幅分位相同，只减了共同常数；资金乘积不是净流入证明。', '',
        '## 3. 一个固定七项组合，跨年是否仍有效', '',
        '模型只有一个，七项在统计前固定。逻辑回归用等类权重、L2=1；源训练中位填缺失、5/95分位裁剪和标准差缩放。'
        '源年起点后60日必须在源年末全部到齐，不用次年峰值确定源年训练标签。'
        '2025→2024是逆向诊断；合并2024–25后评2026仅一次。2026此前已被其他轮使用，不称全新独立样本外。', '',
        table(['训练', '已成熟段/他的段', '训练AUC', '未成熟未入训练'],
              [[n, f"{r['n']}/{r['positives']}", number(r['training_auc'], 3), r['dropped_not_mature']]
               for n, r in fit['models'].items()]), '',
        '下表是标准化后的系数；它表达本模型的统计方向，不是本人明确给出的权重。类权重改变了截距，分数只用于排序，不能当作实际命中概率。', '',
        table(['项目', '2024拟合', '2025拟合', '2024–25合并拟合'],
              [[name, *[number(fit['models'][source]['coefficients'][name], 3)
                        for source in ('2024', '2025', '2024_2025')]] for name in U.MODEL]), '',
        '两个单年模型中，稀少的二值ep10_recent3被统一的源训练5/95截尾压为0，系数为0；合并模型该项仍有变化。'
        '因此两项跨年结果并没有有效检验EP项，不能把0系数解释成EP没有作用。'
        '本轮按预登记保留该转换，未看过目标年后重拟合。下一轮应在训练前区分二值和连续变量的转换。', '',
        table(['源→目标', '性质', '目标段/他的段', 'AUC', '完整60日AUC'],
              [[r['source']+'→'+r['target'], r['kind'], f"{r['n']}/{r['positives']}",
                number(r['auc'], 3), number(r['complete_auc'], 3)] for r in discrimination]), '',
        '### 排在前x%的大行情段里，他占多少', '',
        '这里使用目标年度全部分数作回顾性排序；年度分位在当年初不可知。边界同分按分数权重计，'
        '不按代码选择，因此段数和命中数允许小数。这是区分度诊断，不能伪装成当晚可执行的年度前x%规则。', '',
        table(['源→目标', '保留前x%', '有效段数', '其中他的', '他的占比', '他的召回'],
              [[r['source']+'→'+r['target'], str(k['percent'])+'%', number(k['selected'], 1),
                number(k['his'], 1), percent(k['precision']), percent(k['recall'])]
               for r in discrimination for k in r['ranking']]), '',
        '偏移夜用同一冻结模型，不另拟合。+1至+3已经看到了起点后的K线，不能冒充起点当晚可用。'
        '数据尾端缺少后续偏移时保留缺失，AUC只使用当晚可观测行；CSV另存两侧可用数量。', '',
        table(['源→目标', *[f'{d:+d}晚' for d in U.OFFSETS]],
              [[r['source']+'→'+r['target'], *[number(r['offset_auc'][str(d)], 3) for d in U.OFFSETS]]
               for r in discrimination if r['kind'] != 'in_sample_diagnostic']), '',
        '### 把源年的分数门槛真正移到下一年', '',
        '阈值来自源训练段的分数分位，目标年只用当晚分数判断。仍假定已完美认出大行情，'
        '不是全体局部起点上的真实入场系统。逆向行也保留为诊断。', '',
        table(['源→目标', '源训练前x%门槛', '目标实际保留', '他的/全部', '占比', '召回'],
              [[r['source']+'→'+r['target'], str(k['source_percent'])+'%', percent(k['selected_fraction']),
                f"{k['his']}/{k['selected']}", percent(k['precision']), percent(k['recall'])]
               for r in discrimination if r['kind'] != 'in_sample_diagnostic'
               for k in r['transplanted_thresholds'] if k['source_percent'] in (1, 5, 10, 20)]), '',
        '## 4. 完美认出大行情后，钱和毛利的乐观换算', '',
        'AUC不能直接推出资金纯度或毛利纯度的绝对上限。它没有指定仓位、持有期、兑现利润、空仓天数和融资。'
        '以下把假设写定后换算：次日开盘买入，事后知道峰日并在峰日收盘估值，每段相同初始金额；'
        '资金从2024连续计算，含上年带入仓；按各段当日市值占当前候选总市值分配100%或280%预算，空仓日为0。'
        '毛利按每段相同初始金额的正收益加总，归起点年；不是这个每日再平衡资金账的年度收益。'
        '没有假设能在最高high卖出，也没有计止损、费用、风险拒绝和交易频率，不能当成真实账户已达标。', '',
        '“宽松”把匹配到的整段行情算他的；“严格”只给买入落在Y1首锚点前3日至峰前、并持有跨过本人锚点的lot记H。'
        '统一起点早了几周也许认对行情，但按冻结Y1不能倒算H。这里展示完整拟合2024–25及固定2026的最乐观诊断，'
        '跨年门槛换算另表。', '',
        f"45个匹配段的统一起点相对本人锚点中位为{descriptive['representative_offset_median']}个交易日，"
        f"范围{descriptive['offset_min']}至{descriptive['offset_max']}；其中{descriptive['representative_next_open_before_Y1']}段的代表起点次日开盘早于Y1的H窗口。"
        '这说明“同峰最早起点”和“他的资金段内入场”需要分层；严格列较低不能全部归咎于认不出股票。', '',
        table(['年', '回顾性前x%', '有效段数', '宽松H/投入市值日', '宽松H/权益日：100% / 280%',
               '宽松毛利纯度', '严格H/权益日：280%', '严格毛利纯度'],
              [[r['year'], str(r['cut'])+'%', number(r['selected'], 1), percent(r['relaxed_cap_share']),
                percent(r['relaxed_cap_equity_100'])+' / '+percent(r['relaxed_cap_equity_280']),
                percent(r['relaxed_gross']), percent(r['strict_cap_equity_280']), percent(r['strict_gross'])]
               for r in scenarios if r['selection'] == 'retrospective_target_year_top'
               and r['kind'] in ('in_sample_diagnostic', 'fixed_validation')]), '',
        '与用户主目标一致的资金口径是mean(H当日市值/当日权益)，现金日在分母。它和H/已投入资金不同，'
        '杠杆下可以超过100%。不能把前一列投入份额直接称为资金占用纯度。', '',
        table(['源→目标', '源门槛', '保留段', '宽松资金100% / 280%', '宽松毛利', '严格资金280%', '严格毛利'],
              [[r['source']+'→'+r['year'], str(r['cut'])+'%', number(r['selected'], 0),
                percent(r['relaxed_cap_equity_100'])+' / '+percent(r['relaxed_cap_equity_280']),
                percent(r['relaxed_gross']), percent(r['strict_cap_equity_280']), percent(r['strict_gross'])]
               for r in scenarios if r['selection'] == 'source_threshold_transplant'
               and r['kind'] != 'in_sample_diagnostic' and r['cut'] in (5, 10)]), '',
        '30%标签从起点收盘至最高high定义；实际次日开盘可能已经跳空，峰日收盘也可能回落。'
        '因此“完美认出大行情”仍不保证拿到30%收益。全部段情景中的下一开盘不可交易/峰日估值不盈利数量在oracle_scenarios.json，'
        '没有用不可成交的起点收盘或事后最高价填补。', '',
        '### 连他的身份也全知道时，日历有多少容量', '',
        '这张表不使用画像分数，而是假设事前知道哪些就是他的段，取H窗口内首次合格局部起点后持到冻结峰日，'
        '同票同日只计一次。100%/280%的宽松容量只受总多头和有无H股票约束，放松风险、初始开仓、融资和加仓路径，'
        '所以只是必要条件的上界。每票每天强制≤50%是更严的配置敏感性；原R74只在买入/加仓时限制50%，上涨可自然漂移，'
        '不能用这一列否定原引擎或所有日K方法。', '',
        table(['年', '有可达H的日数/全年', '平均同时可达H票数', '总多头100%宽松上界', '总多头280%宽松上界',
               '每日每票50%、总280%敏感性'],
              [[y, f"{capacity['years'][y]['any_his_days']}/{capacity['years'][y]['sessions']}",
                number(capacity['years'][y]['mean_his_codes']),
                percent(capacity['years'][y]['relaxed_calendar_upper_100']),
                percent(capacity['years'][y]['relaxed_calendar_upper_280']),
                percent(capacity['years'][y]['continuous_half_cap_280'])] for y in U.YEARS]), '',
        '若身份完全可知且只做H的正收益，毛利纯度的算术上界为100%；它没有证明每年52笔、胜率≤35%、'
        '资金、早买、吃到和账户收益能一起通过。任何一个AUC数值都不是“所有日K方法只能做到多少”的定理。', '',
        '### 假设仍只能认出5%', '',
        'P_opp约5%是“存在机会夜时，实际点名有多少命中”的比例，分母与大行情段库不同。以下明确另假设事件选择精度也等于5%，'
        '不把旧P_opp直接当成已测得的段级概率。等持有期、等每美元毛利、满仓时，H/投入资金及毛利均为5%，'
        '100%总多头时H/权益日为5%，280%时为14%；这是一组条件换算，不是无条件数学上限。', '',
        table(['年', 'H/其他平均可持天数', 'H/其他每美元正收益', '按实测天数换算H/投入资金', '按实测毛利换算毛利纯度'],
              [[r['year'], number(r['his_duration'])+' / '+number(r['other_duration']),
                number(r['his_gross_per_dollar'])+' / '+number(r['other_gross_per_dollar']),
                percent(r['empirical_duration_cap_share']), percent(r['empirical_profit_purity'])] for r in five]), '',
        '令p为选中段里他的占比，dH/dO为每个H段相对其他段的平均资金日，gH/gO为每个H段的平均毛利，'
        '则投入纯度=p·dH/[p·dH+(1−p)·dO]，毛利纯度同理换成g。p=5%时，投入纯度50%要求dH/dO=19，'
        '毛利纯度60%要求gH/gO=28.5。若总投入平均为权益的L倍且全年利用率为u，则主资金口径还要乘L·u；'
        '满280%时，50%主资金目标对应已用资金中的H份额至少17.9%，等期基线需H相对其他约4.13倍资金日。'
        '空仓、亏损或资金反馈会改变这些数，不能由5%一项唯一反推出绝对上限。', '',
        '## 5. 48段起点模式与系统实际抓到多少', '',
        '分类只看本人原锚点当晚及此前，固定优先级为EP形态、长期强势回调、新共振近似、突破整理、其他。'
        'EP=近3晚正跳空≥10%；长期回调=120晚强势记忆、近5晚触9/21 EMA且当晚最近距离≤1 ADR；'
        '新共振=无该记忆而强同伴≥3；突破整理=近3晚突破或三日振幅≤1 ADR。没有用新闻给事后赢家硬贴题材。', '',
        '每个实际账户单元格为“早买 / 段内任意首次成交 / 段内赚钱”。IE47为Y1连续C062；master为已存三年连续登记R74+S7真实多头成交，'
        '按冻结48段重新归因；M1B的24–25用训练账户，26用已存连续验证。F2 G1列只有五晚触发代理，不能当账户成交。', '',
        table(['起点模式', '段数', '本地局部动作可早买', '同峰库匹配', 'IE47：早/任意/赚', 'master：早/任意/赚',
               'M1B：早/任意/赚', 'F2 G1早买代理', '其中财报EP'],
              [[r['pattern'], r['n'], r['local_early_reachable'], r['library_matches'],
                *[f"{r[n+'_early']}/{r[n+'_any']}/{r[n+'_profitable']}" for n in ('IE47_C062', 'master', 'M1B')],
                r['F2_G1_early_proxy'], r['earnings_ep']]
               for r in patterns['groups'] if r['year'] == 'all']), '',
        '类别不等于可交易优势。日K能够看到跳空、回踩、均线收回、突破和同步价格变化；不能只靠这些观察证明新闻题材身份或当晚一定会走成大行情。'
        '“本地动作可早买”只说明局部定义可到达，系统没有成交还须查资格、排队和资金；不是日K看不见。'
        '无合格局部动作时只否定这两个局部动作的定义，不否定所有日K触发。', '',
        '### 全48段，不删未匹配或截断项', '',
        '下表“库起点”与本人锚点可能相差很久；“无同峰”不等于他的行情不存在。48段的精度、截断、'
        '同票不同峰重叠、本地动作次数、支撑和同伴明细均在patterns_48.json。', '',
        table(['本人段：代码/锚点', '模式', '统一库起点', '局部可早买', 'IE早/任意', 'master早/任意', 'M1B早/任意', 'G1代理'],
              [[r['code'].replace('US.', '')+' '+r['anchor']+(' 截断' if r['censored'] else ''), r['pattern'],
                r['library_first'] or '无同峰', '有' if r['local']['early_local_entry'] else '无',
                *[('早' if r['capture'][n]['early'] else '—')+'/'+('有' if r['capture'][n]['any'] else '无')
                  for n in ('IE47_C062', 'master', 'M1B')],
                '有' if r['capture']['F2_G1']['early'] else '无'] for r in patterns['legs']]), '',
        '## 6. 工件、复算与验收', '',
        '使用trader-data-v1冻结输入，digest为`'+meta['dataset_digest']+'`。'
        '来源、预登记与代码指纹见sources.json、fit.json和completion.json。当前行业快照从未进入模型；'
        '财报近远只从已发生记录推导。所有起点/原始日K特征在读本人标签之前已定义，标签只用于拟合和评测，'
        '评分函数仅接收七项市场数值和固定参数。', '',
        '主要工件：library.jsonl为全段库；single_features.csv为全部偏移的单项分布和AUC；'
        'model_*.json为固定系数、训练ID和裁剪参数；scores_*.csv为逐段分数；strata.json为全部行业及其他分组；'
        'oracle_scenarios.json、calendar_capacity.json为上限假设和换算；patterns_48.json为48段逐段核对。', '',
        table(['测试组', '测试数', '结果', '原始日志'],
              [[n, r.get('n', '—'), r.get('ending', r.get('reason')), r.get('log', '—')]
               for n, r in checks.items()]), '',
        'U1另有12项行为自检，涵盖起点不看未来、同峰合并、财报发布时间、并列AUC与排名、年末60日成熟约束、'
        '源训练/目标标签隔离、缺失偏移、同伴与F2逐值一致、现金日、跨年带入、严格H窗口，以及真实COIN日K全v1.1历史前缀一致。', '',
        '所有计算及测试使用.venv、CPUQuota=60%、MemoryMax=900M和单线程环境。输入逐字段解压至U1只读mmap；'
        '特征逐股票、截面逐日期，相关最多128×128，未构造股票数×股票数大矩阵。各阶段的cgroup实读、峰值RSS和内存快照在开始/完成JSON。'
        '未联网、未拉新数据、未提交git，未修改M2、共享引擎、登记版或看板；外部并行引擎改动只在最终保护清单中记录。', '',
        '资源前缀如下。已完成的计算阶段拒绝覆盖；重新渲染只读取保存的评测结果，不重开2026。', '',
        '```bash',
        'RUN=(systemd-run --scope -p CPUQuota=60% -p MemoryMax=900M -q env OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1 PYTHONDONTWRITEBYTECODE=1 .venv/bin/python)',
        '"${RUN[@]}" -m studies.martin_luk.u1_research prepare',
        '"${RUN[@]}" -m studies.martin_luk.u1_research features',
        '"${RUN[@]}" -m studies.martin_luk.u1_checks',
        '"${RUN[@]}" -m studies.martin_luk.u1_analysis fit',
        '"${RUN[@]}" -m studies.martin_luk.u1_analysis evaluate',
        '"${RUN[@]}" -m studies.martin_luk.u1_report readout',
        '"${RUN[@]}" -m studies.martin_luk.u1_report render',
        '"${RUN[@]}" -m studies.martin_luk.u1_report verify',
        '```', '']
    U.REPORT.write_text('\n'.join(lines), encoding='utf-8')
    U.log('Chinese report rendered from saved metrics')


def verify():
    checks = tests()
    assert all(r['ok'] for r in checks.values()), checks
    assert U.read(U.WORK/'self_checks.json')['ok']
    current = U.snapshots(U.source_paths())
    before = U.read(U.WORK/'sources.json')
    assert before == current, 'fixed U1 sources or inputs changed'
    for name, digest in U.read(U.WORK/'fit.json')['hashes'].items():
        assert U.sha(U.WORK/name) == digest, name
    for name, digest in U.read(U.WORK/'features.json')['hashes'].items():
        assert U.sha(U.WORK/name) == digest, name
    evaluation = U.read(U.WORK/'evaluation_complete.json')
    assert evaluation['validation_evaluations'] == 1
    assert evaluation['evaluation_source_sha256'] == U.sha(Path(__file__).with_name('u1_analysis.py'))
    assert len(U.read(U.WORK/'patterns_48.json')['legs']) == 48
    for name in ('prepare_started.json', 'prepare.json', 'features_started.json', 'features.json',
                 'fit_started.json', 'fit.json', 'evaluation_started.json', 'evaluation_complete.json', 'self_checks.json'):
        r = U.read(U.WORK/name)['resources']
        quota, period = map(int, r['cpu_max'].split())
        assert quota/period <= .6 and int(r['memory_max']) == 900*1024**2 and r['threads'] == 1, name
    protected = U.read(U.WORK/'protected_before.json')
    after = {n: U.sha(U.ROOT/n) for n in protected}
    for n in protected:
        if not n.endswith('system.py'):
            assert protected[n] == after[n], n
    external = {n: dict(before=protected[n], after=after[n]) for n in protected if protected[n] != after[n]}
    outputs = {}
    for path in sorted(U.WORK.rglob('*')):
        if path.is_file() and path.name != 'completion.json' and not path.name.endswith('.tmp'):
            outputs[str(path.relative_to(U.WORK))] = dict(size=path.stat().st_size, sha256=U.sha(path))
    sources = [U.HOME/n for n in ('u1_research.py', 'u1_analysis.py', 'u1_checks.py', 'u1_report.py')]
    U.write('completion.json', dict(ok=True, task='PLAN_U1_CN', tests=checks,
        self_checks=U.read(U.WORK/'self_checks.json'), input_fingerprints_unchanged=True,
        source_fingerprints=U.snapshots(sources), report_sha256=U.sha(U.REPORT),
        validation_evaluations=1, independent_out_of_sample=False,
        no_network=True, no_new_data=True, no_git_commit=True, no_strategy_simulation=True,
        no_M2_writes=True, write_scope=['studies/martin_luk/u1_*.py', 'studies/martin_luk/reports/u1_work/',
                                       'studies/martin_luk/reports/U1_CN.md'],
        protected_after=after, external_shared_changes=external, outputs=outputs,
        resources=U.resources(), head='18606deb22f3e99a56aa9191e3c70e039202e908',
        secret_guard='installer refused to replace existing root .githooks; hooks preserved, no network installer used',
        upper_bound_caveat='scenario bounds conditional on allocation, clocks and exits; AUC does not bound all daily algorithms'))
    U.log('completion.json closed; three test groups and artifact hashes verified')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=('readout', 'render', 'verify'))
    args = parser.parse_args()
    U.offline()
    globals()[args.stage]()


if __name__ == '__main__':
    main()
