"""Replay frozen IE26 artifacts, explain retained factors and write Chinese reports."""
import argparse
import ast
from collections import Counter
import csv
import json
from pathlib import Path
import re

import numpy as np

from studies.trader_replication import martin_continue_ie26 as m
from studies.trader_replication.ie24_report import table, explain_feature


def cov(value):
    return str(value['hit']) + '/' + str(value['n'])


def pct(value):
    return '无' if value is None or not np.isfinite(value) else f'{value:.2%}'


def features(method, model):
    return [t['j'] for t in model['terms']] if method == 'E' else list(model['features'])


def term_formula(d, method, model, j):
    spec = d.specs[j]
    formula = spec['formula']
    n = spec.get('parameter')
    if isinstance(n, int):
        formula = re.sub(r'(?<!\w)(\d+)n\b', lambda match: str(int(match[1]) * n), formula)
        formula = re.sub(r'\bn\b', str(n), formula)
    if method == 'E':
        term = next(t for t in model['terms'] if t['j'] == j)
        if term['form'] == 'raw':
            return spec['name'].split(':')[-1]
        if term['form'] == 'center':
            return f'-abs(({formula})-{term["center"]:.12g})'
        return str(term['direction']) + '*(' + formula + ')'
    if model['family'] == 'logit':
        weight = model['weights'][model['features'].index(j)]
        return f'({weight:.12g})*(({formula})-0.5)'
    return formula + '; bins=searchsorted([0.25,0.5,0.75],p,side="right")'


def interpretation(spec, method, model, j):
    n = spec.get('parameter')
    key = spec['family'], spec.get('metric')
    precise = {
        ('overlap', 'sar'): '收盘价相对慢速SAR止转线的位置，观察趋势离转弱线有多远',
        ('overlap', 'sarext'): '收盘价相对较快SAR止转线的位置，观察趋势离转弱线有多远',
        ('overlap', 'kama'): f'收盘价相对{n}日自适应均线的位置，观察短期趋势是否抬升',
        ('overlap', 'bb_position'): f'收盘价在{n}日布林通道中的位置，观察短期价格是否走强',
        ('avwap', 'high'): f'收盘价相对从近{n}日高点开始计算的成交量均价的位置，观察离高点以来的成本区有多远',
        ('volatility', 'trange'): f'近{n}日平均真实振幅占收盘价的比例，观察波动是否收窄',
        ('force', 'value'): f'近{n}日价格涨跌乘成交量的平滑力量，观察量价推动的方向',
        ('volume', 'pvi'): f'近{n}日放量日的累计对数涨幅，观察上涨是否伴随成交放大',
        ('volume', 'nvi'): f'近{n}日缩量日的累计对数涨幅，观察缩量时价格的方向',
        ('volume', 'vwap'): f'收盘价相对近{n}日成交量加权均价的位置，观察价格是否站上近期成交成本',
        ('momentum', 'rocr'): f'收盘价相对{n}日前的涨幅比例，观察中短期动量',
        ('momentum', 'roc'): f'近{n}日价格变化比例，观察中短期动量',
        ('vcp', 'higher_low'): f'最近{n}日低点相对{2 * n if isinstance(n, int) else n}日低点的位置，观察低点是否抬高',
        ('channels', 'breakout'): f'收盘价相对之前{n}日最高价的位置，观察短期突破',
        ('price_transform', 'add'): f'近{n}日高低价中点相对收盘价的偏移，观察收盘是否经常靠近日内高位',
        ('statistics', 'linearreg'): f'近{n}日线性回归线相对收盘价的位置，观察价格与较长趋势线的距离',
    }
    description = precise.get(key)
    if description is None:
        description = explain_feature(spec).split('；')[0]
    elif spec['transform'] == 'delta5':
        description += '，使用池内位置相对五晚前的上升幅度'
    elif spec['transform'] == 'history250':
        description += '，先与自身过去250日比较，再与同池比较'
    if method == 'E':
        term = next(t for t in model['terms'] if t['j'] == j)
        if term['form'] == 'center':
            description += f"；得分偏好池内百分位靠近训练中心{term['center']:.3f}"
        elif term['form'] != 'raw':
            description += '；得分偏好较高值' if term['direction'] > 0 else '；得分偏好较低值'
    elif model['family'] == 'logit':
        weight = model['weights'][model['features'].index(j)]
        description += '；本次系数偏好较高值' if weight > 0 else '；本次系数偏好较低值'
    else:
        description += '；与其他因子按四分位阈值共同决定得分'
    return description


def full_formula(d, method, model):
    if method == 'E' or model['family'] == 'logit':
        return ' + '.join(term_formula(d, method, model, j) for j in features(method, model)) or '0'
    def expression(node):
        if 'value' in node:
            return f'{node["value"]:.12g}'
        name = d.specs[model['features'][node['feature']]]['name']
        threshold = (.25, .5, .75)[node['threshold']]
        return '(' + expression(node['left']) + ' if ' + name + '<' + str(threshold) + ' else ' + expression(node['right']) + ')'
    return '0.1*(' + ' + '.join(expression(t) for t in model['trees']) + ')'


def reference_picks(d, ranks, k):
    """The yardstick's independent set-based implementation, for actual predictions."""
    out, recent = {}, []
    for day, sl in d.slices.items():
        held = set().union(*recent[-m.HOLD:]) if recent else set()
        order = np.argsort(ranks[sl], kind='stable') + sl.start
        names = [d.codes[q] for q in order if d.codes[q] not in held][:k]
        out[day] = set(names)
        recent.append(set(names))
    return out


def replay_entry(d, entry, selected):
    days = d.base.meta['days']
    t = days.index(entry['entry_date'])
    return any(entry['code'] in selected.get(days[t + w], ()) for w in range(-4, 3) if 0 <= t + w < len(days))


def independent_winners(d):
    days = d.base.meta['days']
    index = {day: i for i, day in enumerate(days)}
    bycode = {}
    for q, code in enumerate(d.codes):
        bycode.setdefault(code, []).append(q)
    expected = np.full(d.n, -1, np.int8)
    for code, rows in bycode.items():
        with np.load(m.e.ie9.old.WORK / 'stocks' / (code + '.npz')) as stock:
            opening, high = stock['o'], stock['h']
        forward = high.copy()
        for offset in range(1, min(60, len(high))):
            forward[:-offset] = np.fmax(forward[:-offset], high[offset:])
        for q in rows:
            t = index[d.days[q]] + 1
            if t < len(days) - 1 and np.isfinite(opening[t]) and opening[t] > 0:
                expected[q] = forward[t] / opening[t] - 1 >= .3
    return expected


def diagnostics(d):
    d.set_label('real')
    decision = m.read('decision')
    days = d.base.meta['days']
    index = {day: i for i, day in enumerate(days)}
    all_methods = {}
    for method in m.METHODS:
        frozen = m.read('real')
        final = m.read('final_' + method)
        model = final['model']
        schedules = {}
        diagnostic_hits = np.asarray(final['after']['hit'])
        diagnostic_first = np.asarray(final['after']['first_rows'])
        for held in m.HALVES:
            ranks = np.load(m.rank_path('real', held, method), mmap_mode='r')
            schedules[held] = m.picks(d, ranks)
        missed, timing = [], []
        actual = np.asarray(decision['results'][method]['3']['coverage']['hit'])
        first = np.asarray(decision['results'][method]['3']['coverage']['first_rows'])
        for i, entry in enumerate(d.entries):
            if actual[i]:
                q = first[i]
                timing.append(dict(id=entry['id'], code=entry['code'], entry_date=entry['entry_date'],
                    primary=bool(d.primary[i]), signal=d.days[q], signal_offset=index[d.days[q]] - index[entry['entry_date']]))
            if actual[i] or not d.primary[i]:
                continue
            selected = schedules[d.entry_half[i]]
            t = index[entry['entry_date']]
            pool_nights = [day for day, q in zip(entry['nights'], d.query[i]) if q >= 0]
            later, earlier = [], []
            for u in range(max(0, t - 14), len(days)):
                q = d.lookup.get(days[u], {}).get(entry['code'], -1)
                if q >= 0 and selected[q]:
                    if u > t + 2:
                        later.append(u)
                    elif u < t - 4:
                        earlier.append(u)
            reason = 'not_in_pool' if not pool_nights else ('picked_late' if later else 'in_pool_not_picked')
            missed.append(dict(id=entry['id'], code=entry['code'], entry_date=entry['entry_date'],
                half=d.entry_half[i], reason=reason, pool_nights=pool_nights,
                first_late_signal=days[later[0]] if later else None,
                first_late_offset=later[0] - t if later else None,
                late_within_ten=bool(later and later[0] <= t + 10),
                earlier_held_signal=[days[u] for u in earlier]))
        factors = []
        for j in features(method, model):
            rejects = [r for r in final['history'] if r['item']['feature'] == j and not r['accepted']]
            deletion = rejects[-1] if rejects else None
            effects = {h: deletion['before']['halfyear'][h]['hit'] - deletion['after']['halfyear'][h]['hit']
                       for h in m.HALVES} if deletion else {}
            examples = {'hits': [], 'misses': []}
            seen = set()
            for i in sorted(np.flatnonzero(d.primary), key=lambda i: (d.entries[i]['entry_date'], d.entries[i]['id'])):
                entry = d.entries[i]
                key = entry['code'], entry['entry_date']
                if key in seen:
                    continue
                seen.add(key)
                category = 'hits' if diagnostic_hits[i] else 'misses'
                if len(examples[category]) == 3:
                    continue
                q = d.query[i, 4:7]
                sampled = [float(d.x[j, r]) if r >= 0 and np.isfinite(d.x[j, r]) else .5 for r in q]
                picked = int(diagnostic_first[i])
                examples[category].append(dict(code=entry['code'], entry_date=entry['entry_date'],
                    half=d.entry_half[i], percentiles=sampled,
                    picked_signal=d.days[picked] if picked >= 0 else None))
            factors.append(dict(j=j, spec=d.specs[j], formula=term_formula(d, method, model, j),
                interpretation=interpretation(d.specs[j], method, model, j), deletion=deletion,
                half_effect=effects, examples=examples))
            d.release_pages()
        sets = {r['held_out']: set(features(method, r['models'][method])) for r in frozen['records']}
        overlap = {h: {g: len(sets[h] & sets[g]) / len(sets[h] | sets[g]) if sets[h] | sets[g] else 1.
                       for g in m.HALVES} for h in m.HALVES}
        all_methods[method] = dict(misses=missed, miss_counts=dict(Counter(r['reason'] for r in missed)),
            late_within_ten=sum(r['late_within_ten'] for r in missed),
            held_before_window=sum(bool(r['earlier_held_signal']) for r in missed),
            timing=timing, factors=factors,
            fold_features={h: sorted(s) for h, s in sets.items()}, overlap=overlap,
            formula=full_formula(d, method, model),
            final_precision=m.precision(m.winner_flags(d), m.picks(d, m.ranks_for(d, method, model))))
    continuous_shuffles = {}
    for seed in m.SHUFFLES:
        label = 'shuffle_' + str(seed)
        d.set_label(label, seed)
        continuous_shuffles[str(seed)] = {method: m.coverage(d, m.stitched_ranks(d, method, label), m.HALVES)
                                         for method in m.METHODS}
    d.set_label('real')
    m.write('diagnostics', dict(methods=all_methods, continuous_shuffles=continuous_shuffles, signature=m.signature()))
    print('DIAGNOSTICS', {k: v['miss_counts'] for k, v in all_methods.items()}, flush=True)


def verify(d):
    counts = Counter()
    def check(category, condition):
        if not condition:
            raise AssertionError(category)
        counts[category] += 1
    inputs = m.read('inputs')
    check('source signature', inputs['signature'] == m.signature())
    for filename, expected in inputs['signature'].items():
        check('source unchanged', m.sha(m.ROOT / filename) == expected)
    check('matrix readonly', not d.x.flags.writeable)
    check('matrix checksum', m.sha(d.matrix_path) == inputs['matrix_sha256'])
    check('matrix layout', list(d.x.shape) == inputs['shape'] == [d.n, len(d.specs)][::-1])
    check('denominators', len(d.entries) == 81 and int(d.primary.sum()) == 51)
    check('three positive evenings', m.POSITIVE == slice(4, 7))
    for filename, expected in inputs['protected_sha256'].items():
        check('old stage unchanged', m.sha(m.ROOT / filename) == expected)
    for filename, expected in inputs['input_sha256'].items():
        check('cached input unchanged', m.sha(m.ROOT / filename) == expected)
    flags = independent_winners(d)
    check('independent sixty-session winner replay', np.array_equal(flags, m.winner_flags(d)))
    check('pool precision replay', m.precision(flags, np.ones(d.n, bool)) == inputs['pool_precision'])
    peak = 0
    for label, seed in [('real', None)] + [('shuffle_' + str(s), s) for s in m.SHUFFLES]:
        d.set_label(label, seed)
        saved = m.read(label)
        check('six complete outer folds', len(saved['records']) == 6)
        total = {method: np.zeros(len(d.entries), bool) for method in m.METHODS}
        first = {method: np.full(len(d.entries), -1, np.int32) for method in m.METHODS}
        for row in saved['records']:
            held = row['held_out']
            train = [h for h in m.HALVES if h != held]
            check('model frozen digest', m.digest(row['models']) == row['frozen_sha256'])
            check('saved before evaluation', m.read(label + '_' + held + '_frozen')['models'] == row['models'])
            check('fold source signature', row['signature'] == m.signature())
            peak = max(peak, row['runtime']['peak_rss_bytes'])
            equal = m.read('equal_fit_' + label + '_' + str(m.a.half_mask(train)))
            held_ids = {entry['id'] for entry, half in zip(d.entries, d.entry_half) if half == held}
            check('E labels isolated', not (held_ids & set(equal['description']['training_ids'])))
            check('E term budget', all(len(r['model']['terms']) <= 5 for r in equal['candidates']))
            check('E four candidate budgets', all(sum(r['model']['id'].startswith('R' + str(k))
                                                   for r in equal['candidates']) <= 5 for k in range(1, 5)))
            for method in m.METHODS:
                ranks = np.load(m.rank_path(label, held, method), mmap_mode='r')
                for sl in d.slices.values():
                    check('night rank permutation', np.array_equal(np.sort(ranks[sl]), np.arange(1, sl.stop - sl.start + 1)))
                replay = m.coverage(d, ranks, [held])
                check('frozen coverage replay', replay == row['coverage'][method])
                if label == 'real':
                    check('frozen prediction replay', np.array_equal(m.ranks_for(d, method, row['models'][method]), ranks))
                    independent = reference_picks(d, ranks, 3)
                    selected = m.picks(d, ranks)
                    for day, sl in d.slices.items():
                        check('independent budget replay', independent[day] ==
                              {d.codes[q] for q in np.flatnonzero(selected[sl]) + sl.start})
                    for i in np.flatnonzero(d.entry_half == held):
                        check('independent calendar window replay', replay_entry(d, d.entries[i], independent) == replay['hit'][i])
                mask = d.entry_half == held
                total[method][mask] = np.asarray(replay['hit'])[mask]
                first[method][mask] = np.asarray(replay['first_rows'])[mask]
        for method in m.METHODS:
            check('outer aggregate replay', m.summarize(d, total[method], m.HALVES, first[method]) == saved['methods'][method])
    afits = sorted(m.REPORTS.glob(m.PREFIX + 'fit_*_a.json'))
    check('127 complete model searches', len(afits) == 127)
    check('37 complete equal selections', len(list(m.REPORTS.glob(m.PREFIX + 'equal_fit_*.json'))) == 37)
    check('no formula searches', not list(m.REPORTS.glob(m.PREFIX + 'fit_*_b.json')))
    for filename in afits:
        row = json.loads(filename.read_text())
        check('search signature', row['signature'] == m.signature())
        check('screening column budget', len(row['screening']) <= 128)
        check('logit bounds', all(len(v['features']) <= 10 for v in row['candidates'] if v['family'] == 'logit'))
        check('tree bounds', all(v['depth'] == 2 and v['level'] in (20, 40, 60)
                                 for v in row['candidates'] if v['family'] == 'boost'))
        peak = max(peak, row['after']['peak_rss_bytes'])
    d.set_label('real')
    for method in m.METHODS:
        final = m.read('final_' + method)
        retained = set(features(method, final['model']))
        for j in retained:
            last = [r for r in final['history'] if r['item']['feature'] == j][-1]
            check('every retained item costs coverage', not last['accepted'] and
                  last['after']['primary']['hit'] < last['before']['primary']['hit'])
        for k in m.BUDGETS:
            check('frozen budget sensitivity replay', m.fold_budget(d, method, k, flags) ==
                  m.read('decision')['results'][method][str(k)])
        check('diagnostic miss denominator', len(m.read('diagnostics')['methods'][method]['misses']) ==
              51 - m.read('decision')['results'][method]['3']['coverage']['primary']['hit'])
    check('thirty random trials', len(m.read('random')['trials']) == 30)
    check('random starting seed', m.read('random')['seed'] == m.RANDOM_SEED)
    for filename in (Path(m.__file__), Path(__file__)):
        for node in ast.walk(ast.parse(filename.read_text())):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                check('no literal stocks or entry dates', re.search(r'\b(?:US\.[A-Z]+|\d{4}-\d{2}-\d{2})\b', node.value) is None)
    runtime = m.capacity('verify:done')
    peak = max(peak, runtime['peak_rss_bytes'])
    check('peak memory', peak <= 1_300_000_000)
    check('work disk', runtime['work_bytes'] <= 800_000_000)
    m.write('verification', dict(assertions=sum(counts.values()), checks=dict(counts),
        model_searches=len(afits), peak_rss_bytes=peak, runtime=runtime, signature=m.signature()))
    print('VERIFIED', sum(counts.values()), dict(counts), flush=True)


def description_report(d):
    desc = m.read('description')
    means = np.asarray(desc['offset_means'], float)
    counts = np.asarray(desc['offset_counts'], int)
    controls = np.asarray(desc['null_means'], float)
    nulls = np.asarray(desc['null_counts'])
    labels = ('0', '+1', '+2', '三晚平均')
    target = m.REPORTS / (m.PREFIX + 'description_columns.tsv')
    with target.open('w', newline='') as stream:
        writer = csv.writer(stream, delimiter='\t')
        writer.writerow(['column', 'name', 'offset', 'same_side', 'formula',
                         *[h + '_target' for h in m.HALVES], *[h + '_available' for h in m.HALVES],
                         *[h + '_random_mean' for h in m.HALVES]])
        for j, spec in enumerate(d.specs):
            for w, label in enumerate(labels):
                writer.writerow([j, spec['name'], label, bool(m.e.same_side(means[w, [j]])[0]), spec['formula'],
                    *[f'{v:.9g}' if np.isfinite(v) else '' for v in means[w, j]],
                    *counts[w, j], *[f'{v:.9g}' if np.isfinite(v) else '' for v in controls[w, j]]])
    representatives = [g['representative'] for g in desc['groups']['groups']]
    stable_groups = [sum(m.e.same_side(means[w, [j]])[0] for j in representatives) for w in range(4)]
    text = ['# IE26：三晚目标百分位与同票随机对照',
        '5543列包括5541个库列和两个IE9锚。0、+1、+2分别描述，三晚汇总取算术平均；没有使用提前四晚作为正例。池外和缺失为中性0.5。随机在入场当晚抽一只票，同票跟随两晚，共20次。',
        table(['夜晚', '5543列同侧', '5541库列同侧', '随机同侧均值', '随机最多', '明显超出随机', '同侧代表组'],
            [[label, desc['same_side_count'][w], desc['library_same_side_count'][w], f'{nulls[:, w].mean():.1f}',
              int(nulls[:, w].max()), desc['clear_excess'][w], int(stable_groups[w])] for w, label in enumerate(labels)]),
        '所有5543列、四种描述、各半年百分位/可用数/随机均值见[完整表](strong_continue_ie26_description_columns.tsv)。20次随机数量及完整分组保存在description.json。',
        f"按训练池行精确Spearman>0.7、短公式优先贪心去重，全六半年共{len(representatives)}组；正式留出每折重新分组和描述。以下仅展示稳定代表中分离最强的前12组，不据此增加候选。"]
    for w, label in enumerate(labels):
        stable = [j for j in representatives if m.e.same_side(means[w, [j]])[0]]
        stable.sort(key=lambda j: (-min(abs(means[w, j] - .5)), -np.mean(abs(means[w, j] - .5)),
                                   d.specs[j]['length'], d.specs[j]['name']))
        text += ['## ' + label,
            table(['代表', *m.HALVES, '公式'], [[d.specs[j]['name'], *[f'{v:.3f}' for v in means[w, j]],
                                              d.specs[j]['formula']] for j in stable[:12]])]
    delta, win = np.asarray(desc['pair_diff'], float), np.asarray(desc['pair_win'], float)
    paired = [j for j in representatives if m.e.same_side(delta[[j]], 0)[0] and m.e.same_side(win[[j]])[0]
              and np.sign(np.mean(delta[j])) == np.sign(np.mean(win[j] - .5))]
    paired.sort(key=lambda j: (-min(abs(win[j] - .5)), d.specs[j]['length'], d.specs[j]['name']))
    text += ['## 与IE9当晚新挑三只成对比较',
        f"共{desc['pair_count']}对，涉及{desc['paired_entries']}笔主目标；先晚内、再笔内、再半年等权，稳定代表{len(paired)}组。比较票来自IE9实际K=3、HOLD=10名单，目标本身剔除。",
        table(['代表', *[h + '差' for h in m.HALVES], *[h + '胜率' for h in m.HALVES]],
              [[d.specs[j]['name'], *[f'{v:+.3f}' for v in delta[j]], *[f'{v:.3f}' for v in win[j]]] for j in paired[:20]])]
    pairs = []
    for i in np.flatnonzero(d.primary):
        entry = d.entries[i]
        for q in d.query[i, 4:7]:
            if q < 0:
                continue
            sl = d.slices[d.days[q]]
            front = np.flatnonzero(d.baseline_selected[sl]) + sl.start
            front = [int(r) for r in front if r != q]
            pairs.append(dict(id=entry['id'], code=entry['code'], entry_date=entry['entry_date'],
                signal=d.days[q], target_ie9_rank=int(d.baseline_ranks[q]),
                selected=[dict(code=d.codes[r], rank=int(d.baseline_ranks[r])) for r in front]))
    m.write('description_pairs', dict(pairs=pairs, stable_representatives=paired, signature=m.signature()))
    (m.REPORTS / (m.PREFIX + 'description_CN.md')).write_text('\n\n'.join(text) + '\n')


def render(d):
    d.set_label('real')
    decision = m.read('decision')
    inputs, controls = m.read('inputs'), m.read('random')
    desc, diagnostic = m.read('description'), m.read('diagnostics')['methods']
    method = decision['display']
    result = decision['results'][method]['3']
    hit = result['coverage']['primary']['hit']
    outcome = decision['methods'][method]
    factors = diagnostic[method]['factors']
    random_hits = [r['budgets']['3']['coverage']['primary']['hit'] for r in controls['trials']]
    random_mean = float(np.mean(random_hits))
    pool_rate = inputs['pool_precision']['rate']
    continuous = result['continuous']['coverage']['primary']['hit']
    uniform_rate = diagnostic[method]['final_precision']['rate']
    continuous_shuffles = m.read('diagnostics')['continuous_shuffles']
    continuous_maximum = max(row[v]['primary']['hit'] for row in continuous_shuffles.values() for v in m.METHODS)
    meanings = '；'.join(f"{r['spec']['name']}：{r['interpretation'].replace('；', '，')}" for r in factors) or '精简后没有保留因子'
    status = '有方案通过覆盖提升线' if decision['selected'] else '没有方案通过覆盖提升线'
    text = ['# IE26：每天新挑三只的排序因子',
        f"第二十六段已完成，**{status}，41/51的目标{'已达到' if hit >= 41 else '尚未达到'}**。展示方法{method}的全段精简版本：{meanings}。",
        f"正式六半年嵌套留出覆盖 **{hit}/51（{pct(hit / 51)}）**，比IE9的16笔{'多' if hit >= 16 else '少'}{abs(hit - 16)}笔，比同预算随机平均{random_mean:.1f}笔{'多' if hit >= random_mean else '少'}{abs(hit - random_mean):.1f}笔，离41笔还差{max(0, 41 - hit)}笔；按既有尺子拼成连续名单为**{continuous}/51**，距41笔差{max(0, 41 - continuous)}笔。",
        f"五次完整打乱中两路线最高{decision['shuffle_maximum']}/51，展示方法{'通过' if outcome['shuffle_pass'] else '未通过'}打乱门槛；严格赢过{outcome['beat_random']}/30次同预算随机。新挑票留出精度为**{pct(result['precision']['rate'])}**，{'高于' if outcome['precision_pass'] else '低于或等于'}池均值**{pct(pool_rate)}**；全段统一精简版精度**{pct(uniform_rate)}**，{'高于' if uniform_rate > pool_rate else '低于或等于'}池均值。",
        '## 正式覆盖与通过条件',
        '学习只用入场当晚及后两晚；评价为−4…+2任一晚新挑中。每晚最多三只、前十个池夜晚挑过的不占新名额。分母固定51笔主目标/81笔全部入场，半年只展示。',
        table(['半年', 'IE9', 'E等权', 'A模型', '主目标池内上限'],
            [[h, cov(inputs['baseline']['3']['IE9']['coverage']['halfyear'][h]),
              *[cov(decision['results'][v]['3']['coverage']['halfyear'][h]) for v in m.METHODS],
              str(int((d.primary & (d.entry_half == h) & np.any(d.query >= 0, axis=1)).sum())) + '/' +
              str(int((d.primary & (d.entry_half == h)).sum()))] for h in m.HALVES] +
            [['合计', '16/51', *[cov(decision['results'][v]['3']['coverage']['primary']) for v in m.METHODS],
              str(int((d.primary & np.any(d.query >= 0, axis=1)).sum())) + '/51']]),
        table(['方法', '全部入场', '至少19笔', '超过全部打乱', '赢过随机次数', '覆盖提升通过', '精度高于池平均'],
            [[v, cov(decision['results'][v]['3']['coverage']['all_entries']), r['coverage_pass'], r['shuffle_pass'],
              str(r['beat_random']) + '/30', r['passed'], r['precision_pass']] for v, r in decision['methods'].items()]),
        table(['半年', 'IE9全部入场', 'E全部入场', 'A全部入场'],
            [[h, cov(inputs['baseline']['3']['IE9']['coverage']['all_halfyear'][h]),
              *[cov(decision['results'][v]['3']['coverage']['all_halfyear'][h]) for v in m.METHODS]] for h in m.HALVES]),
        '正式成绩按入场半年评价：模型冻结后，在完整夜晚序列执行预算和十晚规则，只读取该折入场标签。跨半年窗口和持有状态均使用同一未见该笔标签的模型。全段统一精简版用于解释和消融，不能替代正式成绩。']
    if decision['selected'] and not outcome['precision_pass']:
        text.append('**覆盖提升通过，但精度未达到新尺子的要求，因此不把它报成可替代IE9的完整方案。**')
    if not decision['selected']:
        text.append('展示方法按登记规则在未通过版本中选取，仅作为诊断，未替换IE9或登记版。')
    text += ['## 连续拼接核对',
        '下表把各信号半年的留出排序拼成一条连续名单，再执行相同预算。它用于和既有尺子直接核对；半年边界的窗口可能引用见过相邻入场半年标签的模型，正式判定使用上面的入场半年隔离成绩。',
        table(['排序', '入场半年隔离主目标', '连续拼接主目标', '连续全部入场', '连续精度'],
            [['IE9', '16/51', '16/51', cov(inputs['baseline']['3']['IE9']['coverage']['all_entries']),
              pct(inputs['baseline']['3']['IE9']['precision']['rate'])],
             ['IE25-E（既有排序）', '本段未重训', '18/51', cov(inputs['baseline']['3']['IE25_E']['coverage']['all_entries']),
              pct(inputs['baseline']['3']['IE25_E']['precision']['rate'])]] +
            [[v, cov(decision['results'][v]['3']['coverage']['primary']),
              cov(decision['results'][v]['3']['continuous']['coverage']['primary']),
              cov(decision['results'][v]['3']['continuous']['coverage']['all_entries']),
              pct(decision['results'][v]['3']['continuous']['precision']['rate'])] for v in m.METHODS]),
        f"同样拼接五组完整打乱预测后，两路线最高为{continuous_maximum}/51；展示方法的连续名单{'超过' if continuous > continuous_maximum else '未超过'}该值，严格赢过{sum(v < continuous for v in random_hits)}/30次随机。连续口径未用于回选模型。",
        '## 同票描述和随机对照',
        table(['描述夜晚', '六半年同侧列数', '20次同票对照最多', '超过对照最大值'],
            [[label, desc['same_side_count'][w], max(v[w] for v in desc['null_counts']), desc['clear_excess'][w]]
              for w, label in enumerate(('0', '+1', '+2', '三晚平均'))]),
        '每个对照在入场当晚只抽一只票并跟随两晚，缺池记0.5。5543列的各半年值、可用数和随机均值见[完整描述表](strong_continue_ie26_description_columns.tsv)，去重代表、公式和与IE9当晚三只票的成对比较见[描述报告](strong_continue_ie26_description_CN.md)。因子差异明显也可能无法转化成每天三只的覆盖优势，判定仍使用留出名单。',
        '## 五次完整打乱',
        table(['标签版本', 'E', 'A'],
            [[str(s), *[cov(m.read('shuffle_' + str(s))['methods'][v]['primary']) for v in m.METHODS]] for s in m.SHUFFLES] +
            [['真实', *[cov(decision['results'][v]['3']['coverage']['primary']) for v in m.METHODS]]]),
        '每个新种子重跑E描述/候选/内部删除，以及A全部列预筛、logit/树拟合、内部选档和六折冻结；没有只打乱最终标签。标签打乱沿用每晚共享行置换，保留池外损失和重复映射；描述的20次对照使用同票三晚跟随。只复用无标签分组以及同一训练集合、同一标签版本的完整子问题。',
        f"随机固定为一个种子{m.RANDOM_SEED}连续30次逐晚排列，K=3均值{random_mean:.1f}、范围{min(random_hits)}–{max(random_hits)}。"]
    for v in m.METHODS:
        c = decision['results'][v]['3']['coverage']
        text += ['### ' + v + ' 相对同预算随机',
            table(['半年', '真实命中', '随机均值', '范围', '严格胜出次数'],
                [[h, cov(c['halfyear'][h]),
                  f"{np.mean([r['budgets']['3']['coverage']['halfyear'][h]['hit'] for r in controls['trials']]):.2f}",
                  str(min(r['budgets']['3']['coverage']['halfyear'][h]['hit'] for r in controls['trials'])) + '–' +
                  str(max(r['budgets']['3']['coverage']['halfyear'][h]['hit'] for r in controls['trials'])),
                  str(sum(r['budgets']['3']['coverage']['halfyear'][h]['hit'] < c['halfyear'][h]['hit'] for r in controls['trials'])) + '/30']
                  for h in m.HALVES])]
    text += ['## 每天新挑两只、三只、四只',
        '只在K=3下选择和精简模型。下列K=2/4使用同一冻结排序重新执行十晚规则，没有重新选参数。',
        table(['每天新票', 'IE9主目标', '随机平均（范围）', 'E主目标', 'E全部', 'E精度', 'A主目标', 'A全部', 'A精度'],
            [[k, cov(inputs['baseline'][str(k)]['IE9']['coverage']['primary']),
              f"{np.mean([r['budgets'][str(k)]['coverage']['primary']['hit'] for r in controls['trials']]):.1f}（" +
              str(min(r['budgets'][str(k)]['coverage']['primary']['hit'] for r in controls['trials'])) + '–' +
              str(max(r['budgets'][str(k)]['coverage']['primary']['hit'] for r in controls['trials'])) + '）',
              *[value for v in m.METHODS for value in
                (cov(decision['results'][v][str(k)]['coverage']['primary']),
                 cov(decision['results'][v][str(k)]['coverage']['all_entries']),
                 pct(decision['results'][v][str(k)]['precision']['rate']))]] for k in m.BUDGETS]),
        'E相对同预算IE9的覆盖增量分别为：' + '、'.join(
            f"每天{k}只{decision['results']['E'][str(k)]['coverage']['primary']['hit'] - inputs['baseline'][str(k)]['IE9']['coverage']['primary']['hit']:+d}笔"
            for k in m.BUDGETS) + '。只有K=3用于正式通过判定，K=2/4不重新选择。',
        '## 精度检查',
        f"池平均为{pct(pool_rate)}（{inputs['pool_precision']['winners']}/{inputs['pool_precision']['n']}个有效股票夜晚）。精度按各留出折信号半年内真正新挑的票计算；边界的持有状态使用对应折完整历史。次日开盘不可用的样本不进入精度分母，右端沿用既有尺子的可用价格窗口。",
        f"同预算随机30次精度均值{pct(float(np.mean([r['budgets']['3']['precision']['rate'] for r in controls['trials']])))}；IE9为{pct(inputs['baseline']['3']['IE9']['precision']['rate'])}，既有IE25-E连续排序为{pct(inputs['baseline']['3']['IE25_E']['precision']['rate'])}。",
        table(['版本', '+30%大赢家', '有效新挑票', '精度', '相对池平均百分点'],
            [[v, decision['results'][v]['3']['precision']['winners'], decision['results'][v]['3']['precision']['n'],
              pct(decision['results'][v]['3']['precision']['rate']),
              f"{100 * (decision['results'][v]['3']['precision']['rate'] - pool_rate):+.2f}"] for v in m.METHODS]),
        '精度低于池均值的版本，不能以覆盖增加冒称挑中票更容易成为大赢家。连续名单的完整预算精度也已列在拼接核对表。',
        '## 离41笔还差在哪里']
    below = [(v, k, decision['results'][v][str(k)]['precision']['rate']) for v in m.METHODS for k in m.BUDGETS
             if decision['results'][v][str(k)]['precision']['rate'] < pool_rate]
    if below:
        text.insert(-1, '**低于池平均的预算版本：**' + '；'.join(f'{v}每天{k}只为{pct(rate)}' for v, k, rate in below) + '。')
    labels = {'not_in_pool': '窗口内不在池', 'picked_late': '窗口后才挑中', 'in_pool_not_picked': '在池未挑中'}
    for v in m.METHODS:
        diag = diagnostic[v]
        total = decision['results'][v]['3']['coverage']['primary']['hit']
        text += ['### ' + v,
            f"覆盖{total}/51，离41笔还差{max(0, 41 - total)}笔；未命中{51 - total}笔。互斥归因：" +
            '、'.join(labels[k] + str(diag['miss_counts'].get(k, 0)) + '笔' for k in labels) + '。',
            f"其中窗口内至少一晚在池、却没在窗口内挑中的共{sum(r['reason'] != 'not_in_pool' for r in diag['misses'])}笔。",
            f"窗口后挑中的样本中，+3…+10晚即挑中{diag['late_within_ten']}笔；所有未命中中，窗口前10晚已有挑选记录{diag['held_before_window']}笔。‘窗口后才挑中’取缓存剩余区间的第一次挑选，不把隔很久的同票重现解释成同一次启动信号。",
            table(['半年', '代码', '入场日', '漏掉原因', '窗口内池夜晚', '首次晚信号', '晚几晚', '更早持有信号'],
                [[r['half'], r['code'], r['entry_date'], labels[r['reason']], ','.join(r['pool_nights']),
                  r['first_late_signal'] or '无', r['first_late_offset'] if r['first_late_offset'] is not None else '无',
                  ','.join(r['earlier_held_signal']) or '无'] for r in diag['misses']])]
    text += ['## 全段最终版本与逐项删除',
        '以下身份在全部六半年中选择，再固定身份逐半年留出重拟合做删除诊断。删后合计不降即删；这是精简诊断，有全段身份选择偏差，正式外层成绩保持原样。每项的半年作用为“删除前命中−删除后命中”，正数表示该半年删除会丢覆盖，负数表示删除反而改善。']
    for v in m.METHODS:
        final = m.read('final_' + v)
        diag = diagnostic[v]
        text += ['### ' + v + ' 最终模型',
            f"初始固定身份删除诊断{cov(final['before']['primary'])}，精简后{cov(final['after']['primary'])}；保留{len(diag['factors'])}项。完整公式如下，池内同分仍沿用原行顺序。",
            f"全段统一模型拟合后名单精度{pct(diag['final_precision']['rate'])}（{diag['final_precision']['winners']}/{diag['final_precision']['n']}），相对池均值{100 * (diag['final_precision']['rate'] - pool_rate):+.2f}个百分点；此项为同段拟合描述。",
            '```text\n' + diag['formula'] + '\n```',
            table(['删除项目', '删除前', '删除后', '接受删除'],
                [[d.specs[r['item']['feature']]['name'], cov(r['before']['primary']), cov(r['after']['primary']),
                  r['accepted']] for r in final['history']])]
        for factor in diag['factors']:
            effect = factor['half_effect']
            active = [h for h, delta in effect.items() if delta > 0]
            text += ['#### ' + factor['spec']['name'],
                factor['interpretation'] + '。',
                '```text\n' + factor['formula'] + '\n```',
                '删除损失覆盖的半年：' + ('、'.join(active) if active else '无') + '。',
                table(['半年', *m.HALVES], [['保留相对删除的命中增量', *[effect.get(h, '无') for h in m.HALVES]]]),
                '以下例子来自完整精简模型的固定身份留出诊断，列出该因子三晚池内百分位，不将个案命中归因于单一因子。',
                table(['结果', '代码', '入场日', '0晚百分位', '+1晚', '+2晚', '挑中信号'],
                    [[label, r['code'], r['entry_date'], *[f'{x:.3f}' for x in r['percentiles']], r['picked_signal'] or '无']
                     for label, key in (('命中', 'hits'), ('漏掉', 'misses')) for r in factor['examples'][key]])]
    text += ['## 各外折因子重合度']
    for v in m.METHODS:
        diag = diagnostic[v]
        text += ['### ' + v,
            table(['留出半年', '选中因子'], [[h, '、'.join(d.specs[j]['name'] for j in diag['fold_features'][h]) or '零项原池顺序']
                                            for h in m.HALVES]),
            '以下为因子身份集合Jaccard重合度；E的方向和中心可能随折改变，完整折模型保存在对应frozen.json。',
            f"不同折之间的平均Jaccard重合度为{np.mean([diag['overlap'][h][g] for k, h in enumerate(m.HALVES) for g in m.HALVES[k + 1:]]):.3f}。",
            table(['留出半年', *m.HALVES], [[h, *[f"{diag['overlap'][h][g]:.3f}" for g in m.HALVES]] for h in m.HALVES])]
    verification, tests = m.read('verification'), m.read('verification_tests')
    text += ['## 复算与资源',
        f"完成{verification['model_searches']}个A训练集合/标签版本拟合、37个E选择、六个真实外折和30个打乱外折。实际预测、独立集合版预算、独立交易日日历窗口、冻结摘要、输入及IE23–IE25文件不变性共{verification['assertions']}项检查通过。研究峰值内存{verification['peak_rss_bytes'] / 1_000_000:.1f}MB，工作目录{verification['runtime']['work_bytes'] / 1_000_000:.1f}MB，验证时磁盘剩余{verification['runtime']['free_bytes'] / 1_000_000_000:.2f}GB。",
        table(['验证', '结果', '日志'], [[r['name'], '通过' if r['exit_code'] == 0 else '失败', r['log']] for r in tests['checks']]),
        'trader_replication测试中的1项预期失败来自既有IE5盘前加仓止损范围测试，本段未运行账户，也未改该测试或账户实现。',
        '运行入口：`PYTHONDONTWRITEBYTECODE=1 OPENBLAS_NUM_THREADS=1 .venv/bin/python -m studies.trader_replication.martin_continue_ie26 all`；审计与报告：`... -m studies.trader_replication.ie26_report all`。已有完整缓存会核对登记和源码摘要后恢复，不重复选择留出参数。',
        '## 已试 / 未试',
        '已试：5543列三晚独立和平均描述、20次同票跟随对照、IE9三只新票成对比较、逐训练集合精确去重、E四轮固定候选与中间最好形式、条件logit最多十列、深二提升树20/40/60轮、六半年嵌套留出、五个新种子完整打乱、30次同预算随机、K=2/4预算敏感性、全段固定身份逐项删除、保留因子解释与例子、漏票归因和全部规定测试。',
        '未试：公式搜索B、E/A组合、新因子或新过滤池、参数网格、新行情、持仓/执行/仓位/止损/退出/杠杆和账户回放。本段结果不赋予生产或交易资格。']
    (m.REPORTS / (m.PREFIX + 'report_CN.md')).write_text('\n\n'.join(text) + '\n')


def manifest():
    files = [Path(m.__file__), Path(__file__), m.PREREG,
             m.ROOT / 'studies/trader_replication/tests/test_martin_continue_ie26.py']
    files.extend(f for f in m.REPORTS.glob(m.PREFIX + '*') if f.is_file() and f != m.path('delivery_manifest'))
    files.extend(f for f in m.WORK.glob('*.npy') if f.is_file())
    m.write('delivery_manifest', dict(files={str(f.relative_to(m.ROOT)): dict(bytes=f.stat().st_size, sha256=m.sha(f))
                                           for f in sorted(set(files))}, signature=m.signature()))


def main(stage):
    m.WORK.mkdir(exist_ok=True)
    m.guard()
    d = m.Data()
    functions = dict(diagnostics=diagnostics, verify=verify, description=description_report, report=render)
    if stage == 'all':
        for function in (diagnostics, verify, description_report, render):
            function(d)
        manifest()
    else:
        functions[stage](d)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=('diagnostics', 'verify', 'description', 'report', 'all'))
    main(parser.parse_args().stage)
