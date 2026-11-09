"""Verify persisted IE24 predictions and render the Chinese research report."""
import argparse
import ast
from collections import Counter
import json
import math
from pathlib import Path

import numpy as np

from studies.trader_replication import martin_continue_ie24 as m


def table(headers, rows):
    def cell(value):
        return str(value).replace('|', '\\|').replace('\n', ' ')
    return '\n'.join(['| ' + ' | '.join(map(cell, headers)) + ' |',
                      '| ' + ' | '.join(['---'] * len(headers)) + ' |'] +
                     ['| ' + ' | '.join(map(cell, row)) + ' |' for row in rows])


def cov(value, top=5):
    return str(value['hits'][str(top)]) + '/' + str(value['n'])


def identities(model):
    return (['a:' + str(j) for j in model.get('a', {}).get('features', [])] +
            ['b:' + m.gp.expression(m.gp.freeze(t)) for t in model.get('b', [])])


def all_half(d, result, half):
    best = np.asarray(result['best'])
    mask = d.entry_half == half
    return dict(n=int(mask.sum()), hits={str(k): int(((best <= k) & mask).sum()) for k in m.TOPS})


def judge():
    real = m.read('real')
    shuffled = [m.read('shuffle_' + str(seed)) for seed in range(2026112401, 2026112406)]
    maximum = max(v['methods'][k]['primary']['hits']['5'] for v in shuffled for k in m.METHODS)
    accounts = m.read('accounts')['results']
    methods = {}
    for method in m.METHODS:
        c = real['methods'][method]
        minimum = min(v['hits']['5'] / v['n'] for v in c['halfyear'].values())
        h = c['primary']['hits']['5']
        account_ok = all(accounts[method + '_' + label]['eligible'] for label in ('final', 'loo'))
        methods[method] = dict(hits=h, minimum_half=minimum, coverage_pass=h >= 26 and minimum >= .25,
                               shuffle_pass=h > maximum, account_pass=account_ok,
                               passed=h >= 26 and minimum >= .25 and h > maximum and account_ok)
    final = m.read('final')['methods']
    candidates = [k for k in m.METHODS if methods[k]['passed']]
    selected = min(candidates, key=lambda k: (-methods[k]['hits'], m.complexity(final[k]['model']), m.METHODS.index(k))) if candidates else None
    display = selected or min(m.METHODS, key=lambda k: (-methods[k]['hits'], m.complexity(final[k]['model']), m.METHODS.index(k)))
    return dict(methods=methods, shuffle_maximum=maximum, selected=selected, display=display,
                display_is_qualified=selected is not None)


def verify(d):
    checks = []
    def check(name, value):
        if not value:
            raise AssertionError(name)
        checks.append(name)
    inputs = m.read('inputs')
    check('frozen search sources', inputs['signature'] == m.signature())
    original_source = (m.REPORTS / (m.PREFIX + 'tie_fix_original_source.py.txt')).read_text()
    def unchanged_ast(source):
        tree = ast.parse(source)
        tree.body = [node for node in tree.body if not isinstance(node, ast.FunctionDef) or node.name != 'complexity']
        return ast.dump(tree, include_attributes=False)
    check('tie correction changes only complexity AST',
          unchanged_ast(original_source) == unchanged_ast(Path(m.__file__).read_text()))
    for p in sorted(m.REPORTS.glob(m.PREFIX + 'fit_*_[ab].json')):
        value = json.loads(p.read_text())
        if 'technical_reuse' not in value:
            continue
        old = json.loads((m.REPORTS / value['technical_reuse']['source']).read_text())
        current_payload = {k: v for k, v in value.items() if k not in ('signature', 'technical_reuse')}
        old_payload = {k: v for k, v in old.items() if k != 'signature'}
        check(p.name + ':reused fit payload identical', current_payload == old_payload)
    check('matrix unchanged', m.sha(d.matrix_path) == inputs['matrix_sha256'])
    for rel, expected in inputs['input_sha256'].items():
        check('cached input unchanged: ' + rel, m.sha(m.ROOT / rel) == expected)
    records = []
    versions = [('real', None)] + [('shuffle_' + str(seed), seed) for seed in range(2026112401, 2026112406)]
    for label, seed in versions:
        d.set_label(label, seed)
        saved = m.read(label)
        for row in saved['records']:
            h = row['held_out']
            check(label + ':' + h + ':frozen model digest', m.digest(row['models']) == row['frozen_sha256'])
            check(label + ':' + h + ':signature', row['signature'] == m.signature())
            frozen = m.read(label + '_' + h + '_frozen')
            check(label + ':' + h + ':pre-evaluation snapshot', frozen['models'] == row['models'])
            for method in m.METHODS:
                ranks = np.load(m.REPORTS / (m.PREFIX + label + '_' + h + '_' + method + '_ranks.npy'))
                for sl in d.slices.values():
                    check(label + ':' + h + ':' + method + ':rank permutation:' + str(sl.start),
                          np.array_equal(np.sort(ranks[sl]), np.arange(1, sl.stop - sl.start + 1)))
                best = np.full(len(d.entries), m.SENTINEL, np.int32)
                for i in np.flatnonzero(d.entry_half == h):
                    q = d.current_query[i]
                    q = q[q >= 0]
                    if len(q):
                        best[i] = ranks[q].min()
                check(label + ':' + h + ':' + method + ':stored coverage',
                      m.summarize_best(d, best, [h]) == row['coverage'][method])
                if label == 'real':
                    prediction = d.rank(m.predict(d, row['models'][method]))
                    check(h + ':' + method + ':prediction replay', np.array_equal(prediction, ranks))
            records.append(dict(label=label, held_out=h, digest=row['frozen_sha256']))
        for method in m.METHODS:
            best = np.full(len(d.entries), m.SENTINEL, np.int32)
            for row in saved['records']:
                mask = d.entry_half == row['held_out']
                best[mask] = np.asarray(row['coverage'][method]['best'])[mask]
            check(label + ':' + method + ':aggregate', m.summarize_best(d, best, m.HALVES) == saved['methods'][method])
    fit_inventory = []
    for p in sorted(m.REPORTS.glob(m.PREFIX + 'fit_*_b.json')):
        row = json.loads(p.read_text())
        check(p.name + ':twenty generations', len(row['history']) == 20)
        check(p.name + ':bounded formulas', all(m.gp.valid(m.gp.freeze(t)) for t in row['formulas']))
        check(p.name + ':signature', row['signature'] == m.signature())
        fit_inventory.append(dict(file=p.name, training_halves=row['training_halves'], elapsed=row['elapsed_seconds']))
    a_fits = sorted(m.REPORTS.glob(m.PREFIX + 'fit_*_a.json'))
    check('all 127 nested and final model searches', len(a_fits) == 127)
    check('all 127 nested and final formula searches', len(fit_inventory) == 127)
    for p in a_fits:
        row = json.loads(p.read_text())
        check(p.name + ':signature', row['signature'] == m.signature())
        check(p.name + ':bounded logit', all(len(a['features']) <= 10 for a in row['candidates'] if a['family'] == 'logit'))
        check(p.name + ':bounded trees', all(a['depth'] <= 3 for a in row['candidates'] if a['family'] == 'boost'))
    d.set_label('real')
    fix = m.read('tie_fix')
    comparisons = []
    for p in sorted(m.REPORTS.glob(m.PREFIX + 'invalid_tie_real_*H*.json')):
        if p.stem.endswith('_frozen'):
            continue
        old = json.loads(p.read_text())
        current = m.read('real_' + old['held_out'])
        comparisons.append(dict(held_out=old['held_out'], models_identical=old['models'] == current['models'],
                                predictions_identical=old['coverage'] == current['coverage']))
    fix['archived_outer_comparison'] = comparisons
    fix['all_archived_outer_predictions_identical'] = all(v['predictions_identical'] for v in comparisons)
    m.write('tie_fix', fix)
    ceilings = {h: dict(n=int((d.primary & (d.entry_half == h)).sum()),
                        retained=int((d.primary & (d.entry_half == h) & np.any(d.query >= 0, axis=1)).sum())) for h in m.HALVES}
    work_bytes = sum(p.stat().st_size for p in m.WORK.rglob('*') if p.is_file())
    check('workspace size', work_bytes <= 800_000_000)
    runtimes = [json.loads(p.read_text()) for p in m.REPORTS.glob(m.PREFIX + 'fit_*_[ab].json')]
    peak = max(v['after']['peak_rss_bytes'] for v in runtimes)
    check('search memory budget', peak <= 1_500_000_000)
    value = dict(assertions=len(checks), checks=checks, outer=records, formula_searches=fit_inventory,
                 model_searches=len(a_fits), ceilings=ceilings, peak_search_rss_bytes=peak,
                 work_bytes=work_bytes, runtime=m.capacity('verification:complete'), signature=m.signature())
    m.write('verification', value)
    print('VERIFIED', len(checks), 'checks;', len(records), 'outer folds;', len(fit_inventory), 'formula searches', flush=True)


def examples(d, full, column):
    best = np.asarray(full['best'])
    values = []
    for i in np.flatnonzero(d.primary):
        q = d.query[i]
        q = q[q >= 0]
        value = float(np.mean(column[q])) if len(q) else None
        values.append(dict(code=d.entries[i]['code'], entry_date=d.entries[i]['entry_date'],
                           rank=int(best[i]), mean_percentile=value))
    def order(row):
        return (row['mean_percentile'] is None, -(row['mean_percentile'] or 0), row['entry_date'], row['code'])
    return dict(hits=sorted([r for r in values if r['rank'] <= 5], key=order)[:3],
                misses=sorted([r for r in values if r['rank'] > 5], key=order)[:3])


def item_formula(d, item):
    if item['kind'] == 'a':
        return d.specs[item['feature']]['formula']
    return 'pool_pct(' + m.gp.expression(m.gp.freeze(item['formula'])) + ')'


def item_name(d, item):
    if item['kind'] == 'a':
        return d.specs[item['feature']]['name']
    return m.gp.expression(m.gp.freeze(item['formula']))


def explain_formula(tree):
    op = tree[0]
    names = dict(o='开盘价', h='最高价', l='最低价', c='收盘价', v='成交量', t='成交额', qqq='QQQ收盘价',
                 iv='隐含波动率', hv='历史波动率', option_volume='期权成交量', call_volume='认购成交量',
                 put_volume='认沽成交量', option_open_interest='期权未平仓量',
                 call_open_interest='认购未平仓量', put_open_interest='认沽未平仓量')
    if op == 'field':
        return names[tree[1]]
    if op in m.gp.BINARY:
        left, right = explain_formula(tree[1]), explain_formula(tree[2])
        return dict(add=f'{left}与{right}的和', sub=f'{left}减去{right}',
                    mul=f'{left}与{right}的乘积', div=f'{left}相对{right}的比值')[op]
    child = explain_formula(tree[-1])
    if op in m.gp.WINDOWED:
        w = tree[1]
        return dict(lag=f'{w}个交易日前的{child}', diff=f'{child}相对{w}个交易日前的变化',
                    mean=f'{child}的{w}日均值', high=f'{child}的{w}日最高值', low=f'{child}的{w}日最低值',
                    std=f'{child}的{w}日波动', ema=f'{child}的{w}日指数均值')[op]
    return dict(neg=f'{child}的反向强弱', adr=f'用日常振幅归一化的{child}',
                history250=f'{child}在自身过去250日的位置', pool=f'{child}在同晚池内的位置')[op]


def explain_feature(spec):
    # Generated after selection; these descriptions never enter either searcher.
    name, trans = spec['name'], spec['transform']
    if spec['family'] == 'options':
        description = '观察期权成交、未平仓量或波动率相对同池股票的位置'
    elif spec['family'] in ('volume', 'force', 'eom'):
        description = '观察成交活跃度及价格与成交的配合'
    elif spec['family'] in ('volatility', 'complexity', 'statistics'):
        description = '观察价格路径的波动、延续性或相对市场关系'
    elif spec['family'] in ('events', 'candles'):
        description = '观察近期事件位置或日线形状的差异'
    elif spec['family'] == 'group':
        description = '观察同伙群的强弱与相对位置'
    else:
        description = '观察价格、趋势或区间位置的差异'
    if trans == 'delta5':
        description += '，取池内位置相对五个交易日前的变化'
    elif trans == 'history250':
        description += '，先与自身过去250日比较'
    return description + '；具体数值按下式计算（' + name + '）'


def tree_expression(tree, features, d):
    if 'value' in tree:
        return f"{tree['value']:.12g}"
    name = d.specs[features[tree['feature']]]['name']
    threshold = (.25, .5, .75)[tree['threshold']]
    return ('(' + tree_expression(tree['left'], features, d) + ' if ' + name + '<' + str(threshold) +
            ' else ' + tree_expression(tree['right'], features, d) + ')')


def model_formula(d, model):
    parts = []
    a = model.get('a')
    if a:
        if a['family'] == 'logit':
            raw = ' + '.join(f"({w:.12g})*({d.specs[j]['name']}-0.5)" for j, w in zip(a['features'], a['weights'])) or '0'
        else:
            raw = '0.1*(' + ' + '.join(tree_expression(t, a['features'], d) for t in a['trees']) + ')'
        parts.append('pool_pct(' + raw + ')')
    b = model.get('b', [])
    if b:
        raw = ' + '.join('pool_pct(' + m.gp.expression(m.gp.freeze(t)) + ')' for t in b)
        parts.append('pool_pct((' + raw + ')/' + str(len(b)) + ')')
    return '(' + ' + '.join(parts) + ')/' + str(len(parts)) if parts else '0'


def render(d):
    d.set_label('real')
    result = judge()
    m.write('judgment', result)
    real, final, random = m.read('real'), m.read('final')['methods'], m.read('random')
    inputs, verification = m.read('inputs'), m.read('verification')
    tests = m.read('verification_tests')
    baseline, ie23 = inputs['baseline'], inputs['ie23']
    display = result['display']
    c = real['methods'][display]
    descriptions = []
    for item, _ in m.deletions(final[display]['model']):
        if item['kind'] == 'b':
            descriptions.append(explain_formula(m.gp.freeze(item['formula'])))
        else:
            descriptions.append(explain_feature(d.specs[item['feature']]))
    opening = '程序在全段拟合版中保留了' + '；'.join(descriptions) + '。' if descriptions else '程序最终精简为空排序，没有留下能改善最终删除诊断覆盖的特征。'
    hit = c['primary']['hits']['5']
    gaps = {h: max(0, math.ceil(.8 * v['n']) - v['hits']['5']) for h, v in c['halfyear'].items()}
    total_gap = max(0, math.ceil(.8 * c['primary']['n']) - hit)
    status = '有版本通过本段门槛' if result['selected'] else '没有版本通过本段全部门槛'
    random_place = random['placement'][display]['combined']
    text = [f'# IE24：程序搜索组合排序与公式\n\n第二十四段步骤已完成，**{status}，每半年80%的目标仍未达到**。{opening}',
            f"正式六半年留出最高覆盖版本为 {display}，前五 {hit}/51，比 IE9 的23/51 {'多' if hit >= 23 else '少'}{abs(hit - 23)}笔，比 IE23 的7/51 {'多' if hit >= 7 else '少'}{abs(hit - 7)}笔；总数到80%还差{total_gap}笔，每半年均到80%还差{sum(gaps.values())}笔。",
            f"它{'通过' if result['methods'][display]['shuffle_pass'] else '未通过'}五次完整打乱对照（打乱中三个方法的最高值{result['shuffle_maximum']}/51），同池30次随机排第{random_place['rank']}/31，随机均值{random_place['mean']:.2f}/51；随机对照未额外登记独立门槛，下面完整列排位。",
            '以下主表均为各折仅用另外五个半年搜索、内部再留一半年选超参后的冻结预测。全段统一模型及其删除诊断另列；后者先看过六半年标签，只用于精简和解释，不能替代正式成绩。没有通过者时，最高覆盖版本仅用于展示，不作为升级或交易版本。',
            '## 正式前1/3/5/10覆盖']
    rows = []
    for h in m.HALVES:
        b = baseline['halfyear'][h]
        old = next(v['held_coverage']['primary'] for v in ie23['records'] if v['held_out'] == h)
        rows.append([h, cov(b), cov(old), *[cov(real['methods'][k]['halfyear'][h]) for k in m.METHODS],
                     *[cov(c['halfyear'][h], k) for k in (1, 3, 10)], gaps[h],
                     str(verification['ceilings'][h]['retained']) + '/' + str(verification['ceilings'][h]['n'])])
    rows.append(['合计', cov(baseline['primary']), cov(ie23['primary']),
                 *[cov(real['methods'][k]['primary']) for k in m.METHODS],
                 *[cov(c['primary'], k) for k in (1, 3, 10)], sum(gaps.values()), '45/51'])
    text.append(table(['半年', 'IE9前5', 'IE23前5', 'A前5', 'B前5', 'AB前5',
                       display + '前1', display + '前3', display + '前10', '距本半年80%缺笔', '固定池上限'], rows))
    text.append('固定池让2025H2最多10/13（76.9%），达到该半年80%需要11笔。这一笔是过滤池的上限；其余缺口也按原分母保留。任务书要求保持池不变，本段没有借此改池或减分母。')
    for method in m.METHODS:
        a = real['methods'][method]
        text += ['### ' + method + ' 完整口径', table(['半年', '主前1', '主前3', '主前5', '主前10', '全部前1', '全部前3', '全部前5', '全部前10'],
                 [[h, *[cov(a['halfyear'][h], k) for k in m.TOPS], *[cov(all_half(d, a, h), k) for k in m.TOPS]] for h in m.HALVES] +
                 [['合计', *[cov(a['primary'], k) for k in m.TOPS], *[cov(a['all_entries'], k) for k in m.TOPS]]])]
    text += ['## 打乱、随机与通过线', table(['版本', '至少26/51且最差≥25%', '严格超过全部打乱', '固定账户否决', '最终通过'],
             [[k, v['coverage_pass'], v['shuffle_pass'], v['account_pass'], v['passed']] for k, v in result['methods'].items()])]
    shuffle_rows = []
    for seed in range(2026112401, 2026112406):
        shuffled = m.read('shuffle_' + str(seed))
        shuffle_rows.append([seed, *[cov(shuffled['methods'][k]['primary']) for k in m.METHODS]])
    text.append(table(['完整重跑标签种子', 'A前5', 'B前5', 'AB前5'], shuffle_rows))
    text.append('每个种子都在各训练集合从头预筛、拟合、公式演化、内部选档、外层评测；只复用无标签的行情/公式计算值，以及同一标签版本下完全相同训练集合的已完成子问题。按预登记，真实各方法与打乱三个方法的最大值比较。')
    for method in m.METHODS:
        text += ['### ' + method + ' 对同池随机', table(['半年', '实际前5', '随机均值', '随机范围', '实际排位', '同值次数'],
                 [[h, p['actual'], f"{p['mean']:.2f}", str(p['minimum']) + '–' + str(p['maximum']),
                   str(p['rank']) + '/31', p['ties']] for h, p in random['placement'][method].items()])]
    text += ['## 各折找到的是不是相近的特征']
    folds = []
    for row in real['records']:
        a, b = row['models']['A'].get('a'), row['models']['B'].get('b', [])
        folds.append([row['held_out'], a['family'] + '/' + str(a['level']),
                      '；'.join(d.specs[j]['name'] for j in a['features']),
                      '；'.join(m.gp.expression(m.gp.freeze(t)) for t in b)])
    text.append(table(['留出半年', 'A家族/档', 'A列', 'B公式'], folds))
    stability = {}
    for method in m.METHODS:
        sets = [set(identities(row['models'][method])) for row in real['records']]
        pairs = [len(a & b) / max(len(a | b), 1) for i, a in enumerate(sets) for b in sets[i + 1:]]
        counts = Counter(x for s in sets for x in s)
        stability[method] = dict(mean_jaccard=float(np.mean(pairs)), all_six=sorted(set.intersection(*sets)),
                                 repeated={k: v for k, v in counts.items() if v >= 2})
        text.append(f"{method} 两折间平均特征交集/并集为{np.mean(pairs):.1%}，六折共同项{len(stability[method]['all_six'])}个。" +
                    ('各折不同，不能把全段拟合版的项称为已找到的稳定特征。' if not stability[method]['all_six'] else '共同出现仍不替代留出与打乱检验。'))
    m.write('stability', stability)
    text += ['## 最终统一模型与逐项删除（精简诊断）',
             '下列特征身份先由全六半年选择，再固定身份和超参逐项删除：A每次在其余五半年重拟合，B公式固定无参数，六折合计不降就删。因为身份先见过全段，这些删除覆盖带选择偏差，不是另一份独立留出考试。前面的正式成绩没有被改写。']
    explanation_records = {}
    for method in m.METHODS:
        value = final[method]
        text += ['### ' + method, f"全段拟合前1/3/5/10：{'、'.join(cov(value['coverage']['primary'], k) for k in m.TOPS)}；固定身份删除诊断前五从{cov(value['before']['primary'])}到{cov(value['after']['primary'])}。",
                 '最终完整排序式（缺失百分位取0.5，`pool_pct`包含当晚并按平均秩处理平手）：',
                 '`' + model_formula(d, value['model']) + '`']
        entries = []
        for item, _ in m.deletions(value['model']):
            matching = [r for r in value['history'] if r['item'] == item]
            deletion = matching[-1] if matching else None
            if item['kind'] == 'a':
                column = np.nan_to_num(d.x[item['feature']], nan=.5)
                meaning = explain_feature(d.specs[item['feature']])
            else:
                column = d.engine().column(m.gp.freeze(item['formula']))
                meaning = '观察' + explain_formula(m.gp.freeze(item['formula'])) + '在同晚池中的相对位置'
            sample = examples(d, value['coverage'], column)
            text += ['#### ' + item_name(d, item), '`' + item_formula(d, item) + '`。' + meaning + '。']
            effects = []
            if deletion:
                effects = [h for h in m.HALVES if deletion['before']['halfyear'][h]['hits']['5'] > deletion['after']['halfyear'][h]['hits']['5']]
                text += ['删除后覆盖下降的半年：' + ('、'.join(effects) or '无') + '。',
                         table(['半年', '保留此项', '删除此项'], [[h, cov(deletion['before']['halfyear'][h]),
                              cov(deletion['after']['halfyear'][h])] for h in m.HALVES])]
            for label in ('hits', 'misses'):
                values = sample[label]
                rows = [r['code'] + ' ' + r['entry_date'] + '（组合最好第' +
                        ('池外' if r['rank'] >= m.SENTINEL else str(r['rank'])) + '；该项有效夜晚平均百分位' +
                        ('无' if r['mean_percentile'] is None else f"{r['mean_percentile']:.3f}") + '）' for r in values]
                text.append(('组合命中例子：' if label == 'hits' else '组合仍遗漏例子：') + '；'.join(rows) + '。')
                if len(values) < 3:
                    text.append('此口径不足3笔，已全部列出。')
            entries.append(dict(item=item, formula=item_formula(d, item), meaning=meaning, effects=effects, examples=sample))
        if not entries:
            text.append('删除后没有保留项，退化为全零分数；不能称为找到特征。')
        explanation_records[method] = entries
    m.write('explanations', explanation_records)
    text += ['## 检查与计算边界',
             '执行中修正一处平手实现：原代码将公式的零件总数当成简度，预登记要求在覆盖平手时优先公式更少。旧实现的反例已复现，新增测试和其他合成测试修正后通过；只改变complexity函数，模型拟合与公式搜索其余源码AST完全一致，因此保留原输入和训练搜索并记录复用依据。修正前已完成的外层结果全部归档为无效，按原登记算法重算；任务书、预登记及参数未改。修正前后对照见tie_fix.json，不能把执行历史写成从未算过这些留出标签。',
             f"全部{verification['assertions']}项产物核验通过，包括输入摘要、冻结模型、各晚名次排列、逐笔覆盖、六折汇总和真实模型重放。完成{verification['model_searches']}个训练集合的A路径、{len(verification['formula_searches'])}个B搜索，每个B均20代；每折、每种子与每代日志及检查点保留。",
             f"搜索峰值内存{verification['peak_search_rss_bytes'] / 1e6:.1f} MB；ie24_work文件总字节数{verification['work_bytes']:,}，主要是IE23的只读硬链接矩阵，未超800 MB；每步磁盘余量检查保留在JSON和日志中。",
             table(['验证命令', '退出码', '结果'], [[v['command'], v['exit_code'], v['summary']] for v in tests['checks']]),
             '只使用已有日K、成交额、QQQ及期权缓存，没有网络取数、额外数据、后台采集、代码中的股票名单/入场日期、持仓执行改进、提交或推送。研究代码运行时写入边界由审计钩子限制在IE24产物。没有修改IE23任务书、代码、结果或报告。',
             '标签分层沿用既有入场后大赢家评价；行情复权、样本范围和期权缺失沿用缓存限制。这六个半年此前已反复使用，本次嵌套隔离和打乱检验不能把它们变成新取得的独立样本。',
             '## 已试 / 未试',
             '已试：全部5543列的训练内预筛；最多10列前向条件logit；20/40/60轮深度二提升树；15种原始终端、固定窗口、七零件三层公式演化及每代相关去重；1/3/5公式等权；A/B等权组合；六半年嵌套留出；5个新种子的完整流程；30次同池随机；全段统一版本逐项删减、逐折稳定性与事后解释。',
             '未试：种群50、20代以外的更大搜索预算，深度三提升树、更多节点或其他运算、将公式再作为A的新输入（本段使用等权AB）、改变过滤池或评价窗口、新数据、开盘入口，以及持仓、执行、仓位、止损、退出或杠杆优化。本段完成的是任务书规定的搜索与检验，80%覆盖目标仍未完成。',
             '## 附：固定执行账户，仅作否决']
    accounts = m.read('accounts')
    account_rows = []
    for label, record in accounts['results'].items():
        for book, value in record['accounts'].items():
            for year, row in value['annual'].items():
                account_rows.append([label, book, year, row['entries'], f"{row['win']:.1%}", f"{row['return']:+.1%}", f"{row['maxdd']:.1%}"])
    for book, value in accounts['baseline'].items():
        for year, row in value['annual'].items():
            account_rows.append(['IE9', book, year, row['entries'], f"{row['win']:.1%}", f"{row['return']:+.1%}", f"{row['maxdd']:.1%}"])
    text.append(table(['版本', '账户', '年', '开仓', '已结束胜率', '收益', '回撤'], account_rows))
    text.append('全部复用IE9的次开成交、保护、退出、费用与融资。final为统一精简版，loo为按信号半年拼接的正式预测；2024和2025的开仓至少52、胜率至多35%只作否决。账户结果在选票搜索、留出与删除结束后才读取，没有参与任何排序或超参选择。')
    dest = m.REPORTS / (m.PREFIX + 'report_CN.md')
    dest.write_text('\n\n'.join(text) + '\n')
    print(dest, result, flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=('verify', 'render'))
    args = parser.parse_args()
    m.guard()
    data = m.Data()
    if args.stage == 'verify':
        verify(data)
    else:
        render(data)
