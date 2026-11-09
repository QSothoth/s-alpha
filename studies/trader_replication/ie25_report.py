"""Audit frozen IE25 artifacts and render the Chinese result, without selection."""
import argparse
import ast
from collections import Counter
import json
import math
from pathlib import Path
import re

import numpy as np

from studies.trader_replication import martin_continue_ie25 as m
from studies.trader_replication import ie24_report as prose

table, cov = prose.table, prose.cov


def identities(method, model):
    if method == 'E':
        return ['e:' + str(t['j']) + ':' + t['form'] for t in model['terms']]
    return prose.identities(model)


def final_records():
    equal = m.read('final_equal')
    return dict(E=dict(model=equal['model'], coverage=equal['coverage'], ablation=equal['ablation']),
                **m.read('final')['methods'])


def all_half(d, result, half):
    best = np.asarray(result['best'])
    mask = d.entry_half == half
    return dict(n=int(mask.sum()), hits={str(k): int(((best <= k) & mask).sum()) for k in m.TOPS})


def verify(d):
    counts = Counter()
    def check(category, condition):
        if not condition:
            raise AssertionError(category)
        counts[category] += 1
    inputs = m.read('inputs')
    check('source signature', inputs['signature'] == m.signature())
    check('matrix readonly', not d.x.flags.writeable)
    check('matrix checksum', m.sha(d.matrix_path) == inputs['matrix_sha256'])
    for name, expected in inputs['protected_sha256'].items():
        check('protected file checksum', m.sha(m.ROOT / name) == expected)
    for name, expected in inputs['input_sha256'].items():
        check('cached input checksum', m.sha(m.ROOT / name) == expected)
    check('new window baseline replay', d.coverage(d.baseline_ranks, d.query, m.HALVES) == inputs['baseline'])
    check('unchanged denominators', int(d.primary.sum()) == 51 and len(d.entries) == 81)
    check('seven nights', d.query.shape == (len(d.entries), 7))
    expected_shape = tuple(inputs['shape'])
    check('matrix shape', d.x.shape == expected_shape)
    versions = [('real', None)] + [('shuffle_' + str(s), s) for s in m.SHUFFLES]
    for label, seed in versions:
        d.set_label(label, seed)
        saved = m.read(label)
        check('six complete outer folds', len(saved['records']) == len(m.HALVES))
        for row in saved['records']:
            half = row['held_out']
            check('frozen model digest', m.digest(row['models']) == row['frozen_sha256'])
            check('outer source signature', row['signature'] == m.signature())
            frozen = m.read(label + '_' + half + '_frozen')
            check('saved before evaluation', frozen['models'] == row['models'])
            for method in m.METHODS:
                ranks = np.load(m.REPORTS / (m.PREFIX + label + '_' + half + '_' + method + '_ranks.npy'), mmap_mode='r')
                for sl in d.slices.values():
                    check('night rank permutation', np.array_equal(np.sort(ranks[sl]), np.arange(1, sl.stop - sl.start + 1)))
                actual = d.coverage(ranks, d.current_query, [half])
                actual.pop('all_halfyear')
                check('stored coverage replay', actual == row['coverage'][method] if method != 'E' else
                      dict(actual, all_halfyear=d.coverage(ranks, d.current_query, [half])['all_halfyear']) == row['coverage'][method])
                if label == 'real':
                    check('real model prediction replay', np.array_equal(m.score_model(d, method, row['models'][method]), ranks))
            fit = m.read('equal_fit_' + label + '_' + str(m.a.half_mask([h for h in m.HALVES if h != half])))
            held_ids = {entry['id'] for entry, h in zip(d.entries, d.entry_half) if h == half}
            check('E label isolation', not (held_ids & set(fit['description']['training_ids'])))
            check('E candidate budget', all(sum(v['model']['id'].startswith('R' + str(k)) for v in fit['candidates']) <= 5 for k in range(1, 5)))
            check('E term budget', all(len(v['model']['terms']) <= 5 for v in fit['candidates']))
        for method in m.METHODS:
            best = np.full(len(d.entries), m.SENTINEL, np.int32)
            for row in saved['records']:
                mask = d.entry_half == row['held_out']
                best[mask] = np.asarray(row['coverage'][method]['best'])[mask]
            check('outer aggregate replay', m.a.summarize_best(d, best, m.HALVES) == saved['methods'][method])
    afits = sorted(m.REPORTS.glob(m.PREFIX + 'fit_*_a.json'))
    bfits = sorted(m.REPORTS.glob(m.PREFIX + 'fit_*_b.json'))
    check('127 complete model searches', len(afits) == 127)
    check('127 complete formula searches', len(bfits) == 127)
    peak = 0
    for p in afits + bfits:
        row = json.loads(p.read_text())
        check('search signature', row['signature'] == m.signature())
        peak = max(peak, row['after']['peak_rss_bytes'])
        if p in bfits:
            check('twenty generations', len(row['history']) == 20)
            check('bounded formulas', all(m.gp.valid(m.gp.freeze(t)) for t in row['formulas']))
        else:
            check('bounded logit', all(len(v['features']) <= 10 for v in row['candidates'] if v['family'] == 'logit'))
            check('bounded trees', all(v['depth'] == 2 and v['level'] in (20, 40, 60) for v in row['candidates'] if v['family'] == 'boost'))
    for p in m.REPORTS.glob(m.PREFIX + 'runtime_*.json'):
        peak = max(peak, json.loads(p.read_text())['after']['peak_rss_bytes'])
    check('five complete shuffled versions', len(versions) == 6)
    check('thirty random trials', len(m.read('random')['trials']) == 30)
    for p in (Path(m.__file__), Path(__file__)):
        for node in ast.walk(ast.parse(p.read_text())):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                check('no literal stock or entry date', re.search(r'\b(?:US\.[A-Z]+|\d{4}-\d{2}-\d{2})\b', node.value) is None)
    d.set_label('real')
    timing = m.read('timing')['methods']
    real = m.read('real')
    for method in m.METHODS:
        check('timing matches official hits', timing[method]['primary']['n'] == real['methods'][method]['primary']['hits']['5'])
        check('timing buy offset', all(-3 <= r['delay_sessions'] <= 3 for r in timing[method]['rows']))
    runtime = m.capacity('verification:complete')
    peak = max(peak, runtime['peak_rss_bytes'])
    check('memory budget', peak <= 1_300_000_000)
    check('work disk budget', runtime['work_bytes'] <= 800_000_000)
    m.write('verification', dict(checks=dict(counts), assertions=sum(counts.values()), model_searches=len(afits),
                                 formula_searches=len(bfits), peak_rss_bytes=peak, runtime=runtime, signature=m.signature()))
    print('VERIFIED', sum(counts.values()), dict(counts), flush=True)


def describe_report(d):
    desc = m.read('description')
    means = np.asarray(desc['means'], float)
    delta, win = np.asarray(desc['pair_diff'], float), np.asarray(desc['pair_win'], float)
    stable = m.e.same_side(means)
    rows = []
    paired_rows = []
    for group in desc['groups']['groups']:
        j = group['representative']
        if stable[j]:
            rows.append([d.specs[j]['name'], len(group['members']), *[f'{v:.3f}' for v in means[j]], d.specs[j]['formula']])
        if (m.e.same_side(delta[[j]], 0)[0] and m.e.same_side(win[[j]])[0]
                and np.sign(np.mean(delta[j])) == np.sign(np.mean(win[j] - .5))):
            paired_rows.append([d.specs[j]['name'], *[f'{v:+.3f}' for v in delta[j]], *[f'{v:.3f}' for v in win[j]]])
    text = [f"# IE25 七晚描述\n\n5541个库列中，六半年同侧{desc['same_side_count']}列；20次同晚共享置换的最大值为{max(desc['null_counts'])}列。真实数量{'明显超出' if desc['clear_excess'] else '未超出'}最大偶然数量。",
            '每笔有效七晚取池内百分位最大值，再按笔与半年等权。随机也取相同最大值，不能把最大值自然偏高当成规律。配对只对IE9七晚仍未命中的池内目标逐夜比较，先笔内再半年等权；对照没有增加独立样本数。',
            '20次偶然同侧列数：' + '、'.join(map(str, desc['null_counts'])) + '。',
            f"精确Spearman>0.7的贪心代表分组共{len(desc['groups']['groups'])}组；下表同侧代表{len(rows)}组，稳定配对代表{len(paired_rows)}组。组和方向在正式各折均只用训练半年重算。",
            table(['代表', '组内列数', *m.HALVES, '公式'], rows),
            '## 稳定配对差异', table(['代表', *[h + '差' for h in m.HALVES], *[h + '胜率' for h in m.HALVES]], paired_rows)]
    (m.REPORTS / (m.PREFIX + 'description_CN.md')).write_text('\n\n'.join(text) + '\n')
    baseline = m.read('inputs')['baseline']
    pairs = []
    for i, entry in enumerate(d.entries):
        if not d.primary[i] or baseline['best'][i] <= 5:
            continue
        for q in d.query[i]:
            if q >= 0:
                sl = d.slices[d.days[q]]
                front = sorted([k for k in range(sl.start, sl.stop) if d.baseline_ranks[k] <= 5], key=lambda k: d.baseline_ranks[k])
                pairs.append(dict(id=entry['id'], code=entry['code'], entry_date=entry['entry_date'], signal=d.days[q],
                                  rank=int(d.baseline_ranks[q]), front=[d.codes[k] for k in front]))
    m.write('description_pairs', dict(records=pairs, stable_representatives=[r[0] for r in paired_rows]))


def term_items(method, model):
    if method == 'E':
        return [dict(kind='e', term=t) for t in model['terms']]
    return [item for item, _ in m.a.deletions(model)]


def formula_name(d, item):
    if item['kind'] == 'e':
        return d.specs[item['term']['j']]['name']
    return prose.item_name(d, item)


def formula_text(d, item):
    if item['kind'] != 'e':
        return prose.item_formula(d, item)
    t = item['term']
    p = d.specs[t['j']]['formula']
    if t['form'] == 'center':
        return '-abs((' + p + ')-' + str(t['center']) + ')'
    if t['form'] == 'raw':
        return 'raw(' + formula_name(d, item) + ')'
    return str(t['direction']) + '*(' + p + ')'


def explain_item(d, item):
    if item['kind'] == 'b':
        return '观察' + prose.explain_formula(m.gp.freeze(item['formula'])) + '在同晚池中的相对位置'
    j = item['term']['j'] if item['kind'] == 'e' else item['feature']
    return prose.explain_feature(d.specs[j])


def examples(d, full, column):
    best = np.asarray(full['best'])
    values = {}
    for i in np.flatnonzero(d.primary):
        entry = d.entries[i]
        key = entry['code'], entry['entry_date']
        if key in values:
            continue
        q = d.query[i]
        q = q[q >= 0]
        values[key] = dict(code=entry['code'], entry_date=entry['entry_date'], rank=int(best[i]),
                           max_percentile=float(np.max(column[q])) if len(q) else None)
    def order(row):
        return row['max_percentile'] is None, -(row['max_percentile'] or 0), row['entry_date'], row['code']
    return {label: sorted([r for r in values.values() if (r['rank'] <= 5) == hit], key=order)[:3]
            for label, hit in (('hits', True), ('misses', False))}


def render(d):
    d.set_label('real')
    decision = m.read('decision')
    real, final = m.read('real'), final_records()
    inputs, desc = m.read('inputs'), m.read('description')
    random, timing = m.read('random'), m.read('timing')['methods']
    verification, tests = m.read('verification'), m.read('verification_tests')
    accounts = m.read('accounts')
    account_ok = all(v['eligible'] for v in accounts['results'].values())
    method = decision['display']
    result, baseline = real['methods'][method], inputs['baseline']
    hit, basehit = result['primary']['hits']['5'], baseline['primary']['hits']['5']
    gaps = {h: max(0, math.ceil(.8 * v['n']) - v['hits']['5']) for h, v in result['halfyear'].items()}
    t = timing[method]['primary']
    items = term_items(method, final[method]['model'])
    meanings = '；'.join(explain_item(d, item) for item in items) or '最终删除后没有保留因子'
    rp = random['placement'][method]['combined']
    status = ('有版本通过提升线' if account_ok else '选票提升通过，但被账户条件否决') if decision['selected'] else '没有版本通过全部提升门槛'
    text = [f"# IE25：允许晚三天买入的前五覆盖\n\n第二十五段规定步骤全部完成，**{status}，每半年80%的目标{'已达到' if not any(gaps.values()) else '仍未达到'}**。展示的单一拟合版本为{method}：{meanings}。",
            f"新窗口正式六半年留出前五为 **{hit}/51（{hit / 51:.1%}）**，比同口径IE9的{basehit}/51{'多' if hit >= basehit else '少'}{abs(hit - basehit)}笔；总数达到80%还差{max(0, math.ceil(.8 * 51) - hit)}笔，每半年分别达到80%合计还差{sum(gaps.values())}笔。",
            f"{'通过' if decision['methods'][method]['shuffle_pass'] else '未通过'}五次完整打乱对照（四种方法打乱最高{decision['shuffle_maximum']}/51）；同池30次随机排第{rp['rank']}/31，随机均值{rp['mean']:.2f}/51。命中主目标第一次出现信号后的次开买入，平均相对他入场{t['mean_delay']:+.2f}个交易日（正为晚买），能取得其原参照涨幅的均值{t['mean_ratio']:.1%}、中位数{t['median_ratio']:.1%}。",
            '正式成绩来自各外层折只用其余五半年重新描述、搜索、内部选档和冻结后的预测；全段统一模型用于解释和精简，不能替代正式成绩。无通过者时展示版本只作诊断，不替代IE9或登记版。',
            '## 七晚口径、基准与上限',
            '信号从其入场前第四晚到入场后第二晚，任一晚前五即命中；名单下一交易日开盘买入，最多晚三天。主目标51笔、全部入场81笔、重复披露及IE9四条过滤均保留。训练屏蔽非训练半年以及其前四晚、后两晚；内部验证也不借外层半年夜晚。',
            table(['半年', 'IE9前5', '池内可达上限', '随机并集理论期望'],
                  [[h, cov(baseline['halfyear'][h]), str(inputs['ceiling'][h]['retained']) + '/' + str(inputs['ceiling'][h]['n']),
                    f"{inputs['random_expectation'][h]:.2f}"] for h in m.HALVES] +
                  [['合计', cov(baseline['primary']), str(sum(v['retained'] for v in inputs['ceiling'].values())) + '/51',
                    f"{sum(inputs['random_expectation'].values()):.2f}"]]),
            '2025H2固定池最多留住10/13，达到本半年80%需要11笔。这一笔是池上限缺口，按任务书保持池不变，没有减少分母。',
            '## 正式六半年留出前五',
            table(['半年', 'IE9', *m.METHODS, method + '距80%缺笔'],
                  [[h, cov(baseline['halfyear'][h]), *[cov(real['methods'][k]['halfyear'][h]) for k in m.METHODS], gaps[h]] for h in m.HALVES] +
                  [['合计', cov(baseline['primary']), *[cov(real['methods'][k]['primary']) for k in m.METHODS], sum(gaps.values())]])]
    for name in m.METHODS:
        r = real['methods'][name]
        text += ['### ' + name + ' 前1/3/5/10',
                 table(['半年', '主前1', '主前3', '主前5', '主前10', '全部前1', '全部前3', '全部前5', '全部前10'],
                       [[h, *[cov(r['halfyear'][h], k) for k in m.TOPS], *[cov(all_half(d, r, h), k) for k in m.TOPS]] for h in m.HALVES] +
                       [['合计', *[cov(r['primary'], k) for k in m.TOPS], *[cov(r['all_entries'], k) for k in m.TOPS]]])]
    text += ['## 描述和成对比较',
             f"5541个库列六半年同侧{desc['same_side_count']}个，20次同晚置换最多{max(desc['null_counts'])}个，数量{'明显超出' if desc['clear_excess'] else '未超出'}偶然基准。每笔取有效七晚最大值，随机也取七晚最大值；只看百分位偏高不能证明有信号。去重代表、半年值、完整公式及稳定配对见[描述报告](strong_continue_ie25_description_CN.md)，逐夜挤出目标的票见description_pairs.json。",
             '## 打乱与同池随机',
             f"提升要求：主目标至少{basehit + 3}/51，且每半年不低于IE9最差半年的{decision['baseline_minimum']:.1%}，并严格高于所有打乱版本在四种方法中的最高合计。账户仅在最后否决，未参与选择。",
             table(['方法', '覆盖提升线', '超过全部打乱', '选票通过'],
                   [[k, v['coverage_pass'], v['shuffle_pass'], v['passed']] for k, v in decision['methods'].items()]),
             table(['完整重跑标签种子', *m.METHODS],
                   [[s, *[cov(m.read('shuffle_' + str(s))['methods'][k]['primary']) for k in m.METHODS]] for s in m.SHUFFLES]),
             '每个新种子均完整重跑描述、E候选与内部消融、A预筛与拟合、B演化、内层选档和外层评测；只共用无标签的分组/因果行情值及同一标签版本同一训练集合的已完成子问题。']
    for name in m.METHODS:
        text += ['### ' + name + ' 对三十次随机前五',
                 table(['半年', '真实命中', '随机均值', '范围', '真实排位', '同值次数'],
                       [[h, r['actual'], f"{r['mean']:.2f}", str(r['minimum']) + '–' + str(r['maximum']), str(r['rank']) + '/31', r['ties']]
                        for h, r in random['placement'][name].items()])]
    text += ['## 最早命中与剩余涨幅',
             '每笔使用原入场后60交易日内共同最高价。比例为 `(最高价/我们次日开盘−1)/(最高价/原入场日收盘−1)`，不截断负值或大于100%的值；它是事后价格空间比较，不代表实际能实现的账户收益。详细每笔日期、延误和价格见timing.json，没有参与选择。',
             table(['正式版本', '主目标命中', '平均买入早晚/交易日', '中位早晚', '晚买笔数', '晚买者平均晚几天', '剩余涨幅均值', '中位数'],
                   [[k, v['primary']['n'], f"{v['primary']['mean_delay']:+.2f}", v['primary']['median_delay'], v['primary']['late_hits'],
                     v['primary']['mean_positive_delay'], f"{v['primary']['mean_ratio']:.1%}", f"{v['primary']['median_ratio']:.1%}"] for k, v in timing.items()]),
             '## 各折所选因子的重合度']
    stability = {}
    for name in m.METHODS:
        sets = [set(identities(name, row['models'][name])) for row in real['records']]
        jaccard = [len(x & y) / max(len(x | y), 1) for i, x in enumerate(sets) for y in sets[i + 1:]]
        count = Counter(value for values in sets for value in values)
        stability[name] = dict(mean_jaccard=float(np.mean(jaccard)), all_six=sorted(set.intersection(*sets)),
                               repeated={k: v for k, v in count.items() if v >= 2})
        text.append(f"{name}两折间平均交集/并集{np.mean(jaccard):.1%}，六折共同项{len(stability[name]['all_six'])}个。" +
                    ('各折缺少共同项，不能将单一全段拟合版称为稳定因子。' if not stability[name]['all_six'] else '共同出现仍须结合留出和打乱判断。'))
        text.append(table(['留出半年', '固定因子/公式'], [[row['held_out'], '；'.join(formula_name(d, item) for item in term_items(name, row['models'][name]))]
                                                  for row in real['records']]))
    m.write('stability', stability)
    text += ['## 全六半年最终版本、消融与解释',
             '这些因子身份先见过全部六半年，删除诊断带选择偏差，只用于精简，正式外层预测不改。E在内部重估方向和中心；A固定身份和档次在其他五半年重拟合；B固定公式。删后合计不降即删，接受后重新开始。']
    explanations = {}
    for name, record in final.items():
        model = record['model']
        text += ['### ' + name, '全段拟合前1/3/5/10：' + '、'.join(cov(record['coverage']['primary'], k) for k in m.TOPS) + '。']
        if name == 'E':
            text.append('等权总分：`' + ' + '.join(formula_text(d, item) for item in term_items(name, model)) + '`。')
            history = record['ablation']['trials']
        else:
            text.append('完整总分：`' + prose.model_formula(d, model) + '`。')
            history = record['history']
        records = []
        for item in term_items(name, model):
            if name == 'E':
                matches = [r for r in history if r['removed'] == item['term'] and not r['accepted']]
            else:
                matches = [r for r in history if r['item'] == item and not r['accepted']]
            deletion = matches[-1] if matches else None
            formula, meaning = formula_text(d, item), explain_item(d, item)
            text += ['#### ' + formula_name(d, item), '`' + formula + '`。' + meaning + '。']
            effects = []
            if deletion:
                def halves_of(row):
                    return row.get('halfyear', row.get('halves'))
                before, after = halves_of(deletion['before']), halves_of(deletion['after'])
                effects = [h for h in m.HALVES if before[h]['hits']['5'] > after[h]['hits']['5']]
                text += ['保留它有贡献的半年：' + ('、'.join(effects) or '无') + '。',
                         table(['半年', '保留', '删掉'], [[h, cov(before[h]), cov(after[h])] for h in m.HALVES])]
            j = item.get('feature', item.get('term', {}).get('j'))
            column = np.nan_to_num(d.x[j], nan=.5) if j is not None else d.engine().column(m.gp.freeze(item['formula']))
            sample = examples(d, record['coverage'], column)
            for label, title in (('hits', '组合命中'), ('misses', '组合仍遗漏')):
                text.append(title + '例子：' + '；'.join(r['code'] + ' ' + r['entry_date'] + '（组合最好名次' +
                            ('池外' if r['rank'] >= m.SENTINEL else str(r['rank'])) + '）' for r in sample[label]) + '。' +
                            ('不足三笔，已全列。' if len(sample[label]) < 3 else ''))
            records.append(dict(item=item, formula=formula, meaning=meaning, effects=effects, deletion=deletion, examples=sample))
        if not term_items(name, model):
            text.append('删除后没有保留项，退化为原池顺序。')
        explanations[name] = records
    m.write('explanations', explanations)
    text += ['## 验证与限制',
             f"完成{verification['model_searches']}个A训练集合、{verification['formula_searches']}个B训练集合，B每个二十代，五个种子各六个外层折；完成{verification['assertions']}项产物核验。研究及核验进程已记录峰值{verification['peak_rss_bytes'] / 1e6:.1f}MB，ie25_work占{verification['runtime']['work_bytes']:,}字节。日志与每折/代际检查点均保留。",
             table(['验证命令', '退出码', '结果'], [[r['command'], r['exit_code'], r['summary']] for r in tests['checks']]),
             '只用已有缓存，输入矩阵以只读memmap分块读取，没有取数、提交、推送、改登记版或custody。IE23/IE24任务书、预登记、代码和输入摘要逐项一致；另一进程自行新增的IE24结果不算本段修改。写入审计将研究进程限制在IE25目录和产物前缀。',
             '这六半年已反复研究，嵌套留出和打乱不能使它们成为新数据的独立检验。主目标分层含事后涨幅，仅用于评价；复权、期权缺失及样本范围沿用缓存。A/B训练仍沿用逐晚平均损失，七晚最大值只用于描述与覆盖，设置差异已在预登记说明。',
             '## 附：原执行账户，只作否决']
    account_rows = []
    for label, record in accounts['results'].items():
        for book, value in record['accounts'].items():
            for year, row in value['annual'].items():
                account_rows.append([method + '/' + label, book, year, row['entries'], f"{row['win']:.1%}", f"{row['return']:+.1%}", f"{row['maxdd']:.1%}"])
    for book, value in accounts['baseline'].items():
        for year, row in value['annual'].items():
            account_rows.append(['IE9', book, year, row['entries'], f"{row['win']:.1%}", f"{row['return']:+.1%}", f"{row['maxdd']:.1%}"])
    text += [table(['版本', '账户', '年', '开仓', '已结束胜率', '收益', '回撤'], account_rows),
             '只回放选票阶段选定（无通过者则展示）的一个方法及其正式拼接预测，完全沿用IE9的执行、保护、退出、费用和融资。2024、2025开仓至少52、已结束胜率至多35%：' +
             '；'.join(label + ('通过' if row['eligible'] else '未通过') for label, row in accounts['results'].items()) + '。账户不参与排序选择，否决后也不回选。',
             '## 已试 / 未试',
             '已试：七晚窗口和池上限；5543列最大值描述、二十次同晚置换和逐夜成对比较；训练内精确相关代表；IE23四轮固定候选与内部消融；IE24前向logit、深二树、固定规模公式演化及AB等权；六半年嵌套留出；五新种子完整打乱；三十次同池随机；全段精简、因子解释、逐折重合度；逐笔最早命中及剩余涨幅；原执行两类账户否决。',
             '未试：登记预算外的候选/参数、更多节点或更大种群/代数、改变过滤池、开盘入口、新数据，以及持仓、执行、仓位、止损、退出或杠杆改进。覆盖每半年80%的目标是否完成以前述正式表为准，未达处不归因到交易员本人。']
    dest = m.REPORTS / (m.PREFIX + 'report_CN.md')
    dest.write_text('\n\n'.join(text) + '\n')
    m.write('delivery', dict(selected=decision['selected'] if account_ok else None,
                             selection_selected=decision['selected'], display=method, coverage=result,
                             account_pass=account_ok,
                             timing=t, report_sha256=m.sha(dest), signature=m.signature()))
    print('REPORT', dest, 'method', method, 'hits', hit, flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=('verify', 'render'))
    args = parser.parse_args()
    m.guard()
    data = m.Data()
    if args.stage == 'verify':
        verify(data)
    else:
        describe_report(data)
        render(data)
