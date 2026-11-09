"""Replay IE27 narrow holding coverage and render its frozen research results."""
import argparse
import ast
from collections import Counter
import json
from pathlib import Path
import re

import numpy as np

from studies.trader_replication import ie26_report as upstream
from studies.trader_replication import martin_continue_ie27 as m

base = m.original.original.isolated(upstream, __name__ + '.base')
base.m = m
table, cov, pct = base.table, base.cov, base.pct


def reference_picks(d, ranks, k, permitted=None):
    """Advance an independent set queue on every calendar night, including empty pools."""
    out, recent = {}, []
    allowed = None if permitted is None else set(d.rows_for(permitted))
    for day in d.base.meta['days']:
        sl = d.slices.get(day, slice(0, 0))
        excluded = set().union(*recent[-k:]) if recent else set()
        order = np.argsort(ranks[sl], kind='stable') + sl.start
        names = [d.codes[q] for q in order if d.codes[q] not in excluded and
                 (allowed is None or q in allowed)][:k]
        out[day] = set(names)
        recent.append(set(names))
    return out


def replay_entry(d, entry, selected, h=3):
    """Explicitly build each night's held names, independently of expanded row queries."""
    days = d.base.meta['days']
    t = days.index(entry['entry_date'])
    for night in range(max(0, t - 4), min(len(days), t + 3)):
        held = set().union(*(selected.get(days[u], set()) for u in range(max(0, night - h + 1), night + 1)))
        if entry['code'] in held:
            return True
    return False


base.reference_picks, base.replay_entry = reference_picks, replay_entry


def diagnostics(d):
    base.diagnostics(d)
    saved = m.read('diagnostics')
    days = d.base.meta['days']
    positions = {day: t for t, day in enumerate(days)}
    for method, info in saved['methods'].items():
        schedules = {h: m.picks(d, np.load(m.rank_path('real', h, method), mmap_mode='r')) for h in m.HALVES}
        for row in info['misses']:
            t = positions[row['entry_date']]
            pool = [days[u] for u in range(max(0, t - 6), min(len(days), t + 3))
                    if row['code'] in d.lookup.get(days[u], {})]
            row['holding_window_pool_nights'] = row['pool_nights']
            row['pool_nights'] = pool
            row['reason'] = ('not_in_pool' if not pool else
                             'picked_late' if row['first_late_signal'] else 'in_pool_not_picked')
            row['late_beyond_deadline'] = row['first_late_offset'] - 2 if row['first_late_offset'] is not None else None
            selected = schedules[row['half']]
            earlier = []
            for u in range(max(0, t - 14), max(0, t - 6)):
                q = d.lookup.get(days[u], {}).get(row['code'], -1)
                if q >= 0 and selected[q]:
                    earlier.append(days[u])
            row['earlier_held_signal'] = earlier
        info['miss_counts'] = dict(Counter(row['reason'] for row in info['misses']))
        info['held_before_window'] = sum(bool(row['earlier_held_signal']) for row in info['misses'])
    m.write('diagnostics', saved)


def verify(d):
    base.verify(d)
    counts = Counter()
    def check(name, valid):
        if not valid:
            raise AssertionError(name)
        counts[name] += 1
    d.set_label('real')
    decision = m.read('decision')
    for k in m.BUDGETS:
        for method in m.METHODS:
            hits = np.zeros(len(d.entries), bool)
            for held in m.HALVES:
                ranks = np.load(m.rank_path('real', held, method), mmap_mode='r')
                independent = reference_picks(d, ranks, k)
                selected = m.picks(d, ranks, k)
                occupancy = []
                for t, day in enumerate(d.base.meta['days']):
                    sl = d.slices.get(day, slice(0, 0))
                    check('independent both-width picks', independent[day] ==
                          {d.codes[q] for q in np.flatnonzero(selected[sl]) + sl.start})
                    occupancy.append(len(set().union(*(independent[d.base.meta['days'][u]]
                        for u in range(max(0, t - k + 1), t + 1)))))
                check('maximum actual held width', max(occupancy) <= k * k)
                for i in np.flatnonzero(d.entry_half == held):
                    hits[i] = replay_entry(d, d.entries[i], independent, k)
            check('independent both-width coverage', hits.tolist() ==
                  decision['results'][method][str(k)]['coverage']['hit'])
    flags = m.winner_flags(d)
    rng = np.random.default_rng(m.RANDOM_SEED)
    for trial in m.read('random')['trials']:
        ranks = np.empty(d.n, np.int32)
        for sl in d.slices.values():
            ranks[sl] = rng.permutation(sl.stop - sl.start) + 1
        for k in m.BUDGETS:
            independent = reference_picks(d, ranks, k)
            hit = [replay_entry(d, entry, independent, k) for entry in d.entries]
            check('independent random coverage', hit == trial['budgets'][str(k)]['coverage']['hit'])
            check('random precision replay', m.precision(flags, m.picks(d, ranks, k)) ==
                  trial['budgets'][str(k)]['precision'])
    for label in ['real'] + ['shuffle_' + str(s) for s in m.SHUFFLES]:
        d.set_label(label, None if label == 'real' else int(label.split('_')[-1]))
        check('same nightly permutation for seven and nine labels',
              np.array_equal(d.current_query, d.current_eval_query[:, 2:]))
        for held in m.HALVES:
            train = [h for h in m.HALVES if h != held]
            mask = m.a.half_mask(train)
            equal = m.read('equal_fit_' + label + '_' + str(mask))
            chosen = max(equal['candidates'], key=lambda v:
                         (v['coverage']['primary']['hit'], -len(v['model']['terms']), -v['order']))
            check('E selects training total with fewer-term tie', equal['selected'] == chosen['model'])
            pipeline = m.read('pipeline_' + label + '_' + str(mask))
            chosen = max(pipeline['choices'], key=lambda v: (v['hit'], -v['columns'],
                -(v['model']['level'] if v['model']['family'] == 'boost' else 0),
                int(v['model']['family'] == 'logit'), -v['order']))
            check('A selects internal total with registered ties', pipeline['model'] == chosen['model'])
    for method in m.METHODS:
        outcome = decision['methods'][method]
        check('fixed improvement decision', outcome['passed'] ==
              (outcome['hit'] >= 25 and outcome['shuffle_pass'] and outcome['beat_random'] >= 27))
    for source in (Path(m.__file__), Path(__file__)):
        for node in ast.walk(ast.parse(source.read_text())):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                check('IE27 contains no literal stocks or entry dates',
                      re.search(r'\b(?:US\.[A-Z]+|\d{4}-\d{2}-\d{2})\b', node.value) is None)
    saved = m.read('verification')
    saved['checks'].update(counts)
    saved['assertions'] += sum(counts.values())
    saved['runtime'] = m.capacity('verify:independent:done')
    saved['peak_rss_bytes'] = max(saved['peak_rss_bytes'], saved['runtime']['peak_rss_bytes'])
    m.write('verification', saved)
    d.set_label('real')
    print('IE27 VERIFIED', saved['assertions'], flush=True)


def description_report(d):
    base.description_report(d)
    dest = m.REPORTS / (m.PREFIX + 'description_CN.md')
    dest.write_text(dest.read_text().replace('IE26：', 'IE27：').replace('strong_continue_ie26_', m.PREFIX))


def render(d):
    d.set_label('real')
    decision, inputs = m.read('decision'), m.read('inputs')
    controls, desc = m.read('random'), m.read('description')
    diagnostic = m.read('diagnostics')['methods']
    method = decision['display']
    result, outcome = decision['results'][method], decision['methods'][method]
    hit, secondary = result['3']['coverage']['primary']['hit'], result['2']['coverage']['primary']['hit']
    random_hits = {str(k): [r['budgets'][str(k)]['coverage']['primary']['hit'] for r in controls['trials']]
                   for k in m.BUDGETS}
    means = {k: float(np.mean(v)) for k, v in random_hits.items()}
    pool_rate = inputs['pool_precision']['rate']
    meanings = '；'.join(r['spec']['name'] + '：' + r['interpretation'].replace('；', '，')
                        for r in diagnostic[method]['factors']) or '精简后没有保留因子'
    status = '有方案通过提升线' if decision['selected'] else '没有方案通过提升线'
    text = ['# IE27：按约九只和四只的宽度找排序因子',
        f"第二十七段已完成，**{status}，41/51目标{'已达到' if hit >= 41 else '尚未达到'}**；展示{method}路线的全段精简因子：{meanings}。",
        f"主尺子（每天3只、持有3晚，最多9只）正式留出 **{hit}/51**，比IE9的22笔{hit - 22:+d}笔、比随机平均{means['3']:.1f}笔{hit - means['3']:+.1f}笔，离41笔差{max(0, 41 - hit)}笔。",
        f"副尺子（每天2只、持有2晚，最多4只）为 **{secondary}/51**，比IE9的15笔{secondary - 15:+d}笔、比随机平均{means['2']:.1f}笔{secondary - means['2']:+.1f}笔；副尺子没有参与选择。",
        f"五次完整打乱的两路线最高{decision['shuffle_maximum']}/51，展示方法{'通过' if outcome['shuffle_pass'] else '未通过'}打乱门槛，严格赢过{outcome['beat_random']}/30次随机；主尺子新挑票精度 **{pct(result['3']['precision']['rate'])}**，{'高于' if outcome['precision_pass'] else '低于或等于'}池平均 **{pct(pool_rate)}**。",
        '## 尺子、起点与隔离',
        '持有含挑中当晚及之后H−1晚，掉出池也继续计入H晚覆盖；入场−4…+2任一晚持有即命中。主尺子等价于−6…+2新挑中，副尺子为−5…+2。为严格复现任务书起点，沿用参考脚本“前H晚挑过不再挑”的去重边界：实际持有仍仅H晚，到期后还隔一晚才可重挑；没有将那一晚算作持有。交易日日历推进，空池、屏蔽夜晚也消耗时间，跨半年不重置。',
        '学习、描述、方向、中心只用0、+1、+2晚。每个外折只用另五半年从头选择；冻结后用同一模型执行完整夜晚序列，只评价该折入场。按信号半年拼接的连续名单另报，边界可能引用见过相邻入场标签的模型，未用于择优。精简版含全段身份选择偏差，只作解释，不替代正式嵌套留出。',
        table(['尺子', 'IE9', 'IE26-E', 'IE26-A', '随机均值', '随机范围'],
            [[f'K=H={k}', *[cov(inputs['baseline'][str(k)][v]['coverage']['primary'])
                for v in ('IE9', 'IE26_E', 'IE26_A')], f"{means[str(k)]:.1f}",
                f"{min(random_hits[str(k)])}–{max(random_hits[str(k)])}"] for k in (3, 2)]),
        '以上全部起点断言通过。IE26完整签名核对差异如下，本段描述和分组均重算，未恢复旧段的标签相关结果：' +
        '、'.join(inputs['previous_signature_mismatches']),
        '## 正式留出与通过判定',
        table(['半年', 'IE9', 'E', 'A', '池内可达主目标'],
            [[h, cov(inputs['baseline']['3']['IE9']['coverage']['halfyear'][h]),
                *[cov(decision['results'][v]['3']['coverage']['halfyear'][h]) for v in m.METHODS],
                f"{int((d.primary & (d.entry_half == h) & np.any(d.eval_query >= 0, axis=1)).sum())}/" +
                str(int((d.primary & (d.entry_half == h)).sum()))] for h in m.HALVES] +
            [['合计', '22/51', *[cov(decision['results'][v]['3']['coverage']['primary']) for v in m.METHODS],
              str(int((d.primary & np.any(d.eval_query >= 0, axis=1)).sum())) + '/51']]),
        table(['方法', '主目标', '全部入场', '至少25笔', '超过全部打乱', '赢随机', '提升通过', '距41笔'],
            [[v, cov(decision['results'][v]['3']['coverage']['primary']),
              cov(decision['results'][v]['3']['coverage']['all_entries']), r['coverage_pass'], r['shuffle_pass'],
              str(r['beat_random']) + '/30', r['passed'], max(0, 41 - r['hit'])] for v, r in decision['methods'].items()]),
        '通过条件只使用主尺子：至少25/51、严格高于五次打乱全部E/A结果、严格赢过至少27/30次随机。精度只报告。' +
        ('通过方法为' + decision['selected'] + '。' if decision['selected'] else '没有通过者，不推荐替换IE9。')]
    for k in (3, 2):
        text += [f'## K=H={k}：覆盖、精度与连续拼接',
            table(['排序', '主目标', '全部入场', '比IE9', '比随机均值', '精度', '连续主目标', '连续全部', '连续精度'],
                [[v, cov(decision['results'][v][str(k)]['coverage']['primary']),
                  cov(decision['results'][v][str(k)]['coverage']['all_entries']),
                  decision['results'][v][str(k)]['coverage']['primary']['hit'] -
                    inputs['baseline'][str(k)]['IE9']['coverage']['primary']['hit'],
                  f"{decision['results'][v][str(k)]['coverage']['primary']['hit'] - means[str(k)]:+.1f}",
                  pct(decision['results'][v][str(k)]['precision']['rate']),
                  cov(decision['results'][v][str(k)]['continuous']['coverage']['primary']),
                  cov(decision['results'][v][str(k)]['continuous']['coverage']['all_entries']),
                  pct(decision['results'][v][str(k)]['continuous']['precision']['rate'])] for v in m.METHODS]),
            table(['半年', 'E主目标', 'A主目标', 'E全部', 'A全部', '随机主目标均值'],
                [[h, *[cov(decision['results'][v][str(k)]['coverage']['halfyear'][h]) for v in m.METHODS],
                  *[cov(decision['results'][v][str(k)]['coverage']['all_halfyear'][h]) for v in m.METHODS],
                  f"{np.mean([r['budgets'][str(k)]['coverage']['halfyear'][h]['hit'] for r in controls['trials']]):.2f}"]
                  for h in m.HALVES])]
    text += ['## 五次完整打乱与三十次随机',
        table(['标签版本', 'E主尺子', 'A主尺子'],
            [[s, *[cov(m.read('shuffle_' + str(s))['methods'][v]['primary']) for v in m.METHODS]] for s in m.SHUFFLES]),
        '每次打乱从头重跑描述、E候选与内部删项、A全列预筛/拟合/内部选档及六折冻结；只共享本段无标签分组和同一标签版本同一训练集合的完整子问题。七晚学习查询与九晚评价查询使用同一每晚共享行置换。',
        f'随机用一个default_rng({m.RANDOM_SEED})连续生成30次逐晚排列，主副尺子共用；完整逐次成绩见random.json。',
        '## 描述与精度',
        table(['夜晚', '六半年同侧列数', '20次同票随机最多', '数量超过随机'],
            [[label, desc['same_side_count'][w], max(v[w] for v in desc['null_counts']), desc['clear_excess'][w]]
             for w, label in enumerate(('0', '+1', '+2', '三晚平均'))]),
        '完整5543列、各半年百分位与计数、同票跟随对照、公式及分组见[描述报告](' + m.PREFIX +
        'description_CN.md)和[描述表](' + m.PREFIX + 'description_columns.tsv)。',
        f"池均值{pct(pool_rate)}（{inputs['pool_precision']['winners']}/{inputs['pool_precision']['n']}）；精度取实际新挑票的次日开盘起最多60个交易日最高涨幅≥30%，未知开盘剔除，右端沿用缓存可用窗口。正式精度按各折信号半年提取实际名单，不参与选择。",
        table(['方法', '尺子', '大赢家', '有效票次', '精度', '比池平均百分点'],
            [[v, f'K=H={k}', decision['results'][v][str(k)]['precision']['winners'],
              decision['results'][v][str(k)]['precision']['n'], pct(decision['results'][v][str(k)]['precision']['rate']),
              f"{100 * (decision['results'][v][str(k)]['precision']['rate'] - pool_rate):+.2f}"]
             for v in m.METHODS for k in (3, 2)])]
    below = [f'{v}（K=H={k}）' for v in m.METHODS for k in (3, 2)
             if decision['results'][v][str(k)]['precision']['rate'] < pool_rate]
    if below:
        text.append('**精度低于池平均：' + '、'.join(below) + '。**')
    labels = {'not_in_pool': '可挑窗口不在池', 'picked_late': '窗口后才挑中', 'in_pool_not_picked': '在池未持有'}
    text += ['## 主尺子漏票归因',
        '互斥顺序为：−6…+2没有池内机会；有机会但+2以后才挑中；其余在池未持有。另报原−4…+2持有窗口的池内情况；晚到取缓存剩余期间首次新挑，隔很久重现不解释成同次启动。']
    for v in m.METHODS:
        diag = diagnostic[v]
        text += ['### ' + v,
            '、'.join(labels[key] + str(diag['miss_counts'].get(key, 0)) + '笔' for key in labels) +
            f"；+3…+10晚挑中{diag['late_within_ten']}笔。",
            table(['半年', '代码', '入场', '原因', '−6…+2池内晚', '−4…+2池内晚', '首次晚挑', '相对入场晚数', '超截止晚数'],
                [[r['half'], r['code'], r['entry_date'], labels[r['reason']], ','.join(r['pool_nights']) or '无',
                  ','.join(r['holding_window_pool_nights']) or '无', r['first_late_signal'] or '无',
                  r['first_late_offset'] if r['first_late_offset'] is not None else '无',
                  r['late_beyond_deadline'] if r['late_beyond_deadline'] is not None else '无'] for r in diag['misses']])]
    text += ['## 全段最终版本与逐项删除',
        '全六半年选择身份后固定身份，逐半年留出重拟合；主尺子合计不降即删，接受后从头。以下是有全段身份选择偏差的精简诊断。半年作用表示保留相对删除的命中增量；例子来自整个精简模型，不把组合命中归因于单一因子。']
    for v in m.METHODS:
        final, diag = m.read('final_' + v), diagnostic[v]
        text += ['### ' + v,
            f"固定身份删除前{cov(final['before']['primary'])}，精简后{cov(final['after']['primary'])}；保留{len(diag['factors'])}项，全段统一拟合名单精度{pct(diag['final_precision']['rate'])}。",
            '```text\n' + diag['formula'] + '\n```',
            table(['删除项', '删除前', '删除后', '接受'],
                [[d.specs[r['item']['feature']]['name'], cov(r['before']['primary']), cov(r['after']['primary']),
                  r['accepted']] for r in final['history']])]
        for factor in diag['factors']:
            text += ['#### ' + factor['spec']['name'], factor['interpretation'] + '。',
                '```text\n' + factor['formula'] + '\n```',
                '保留增加覆盖的半年：' + ('、'.join(h for h, value in factor['half_effect'].items() if value > 0) or '无') + '。',
                table(['作用', *m.HALVES], [['保留相对删除', *[factor['half_effect'].get(h, '无') for h in m.HALVES]]]),
                table(['结果', '代码', '入场', '0晚百分位', '+1晚', '+2晚', '新挑信号'],
                    [[label, r['code'], r['entry_date'], *[f'{x:.3f}' for x in r['percentiles']], r['picked_signal'] or '无']
                     for label, key in (('命中', 'hits'), ('漏掉', 'misses')) for r in factor['examples'][key]])]
        text += ['### ' + v + ' 各折因子与重合度',
            table(['留出半年', '因子'], [[h, '、'.join(d.specs[j]['name'] for j in diag['fold_features'][h]) or '零项原池顺序']
                                      for h in m.HALVES]),
            f"折间平均Jaccard为{np.mean([diag['overlap'][h][g] for i, h in enumerate(m.HALVES) for g in m.HALVES[i + 1:]]):.3f}。",
            table(['留出半年', *m.HALVES], [[h, *[f"{diag['overlap'][h][g]:.3f}" for g in m.HALVES]] for h in m.HALVES])]
    verification, tests = m.read('verification'), m.read('verification_tests')
    text += ['## 复算、资源与交付',
        f"完成{verification['model_searches']}个A训练集合/标签版本拟合、37个E选择、6个真实及30个打乱外折。冻结模型、真实预测、主副宽度独立集合/逐晚持有复算、30次随机、价格精度、输入及IE23–IE26保护摘要共{verification['assertions']}项检查通过。峰值内存{verification['peak_rss_bytes'] / 1_000_000:.1f}MB，ie27_work为{verification['runtime']['work_bytes'] / 1_000_000:.1f}MB，剩余磁盘{verification['runtime']['free_bytes'] / 1_000_000_000:.2f}GB。",
        table(['检查', '结果', '日志'], [[r['name'], '通过' if r['exit_code'] == 0 else '失败', r['log']] for r in tests['checks']]),
        '测试的跳过与预期失败按原测试日志披露，未作为新增通过项。未取数、未运行账户、未改旧段或登记版、未提交或推送。',
        '运行：`PYTHONDONTWRITEBYTECODE=1 OPENBLAS_NUM_THREADS=1 .venv/bin/python -m studies.trader_replication.martin_continue_ie27 all`；审计与报告：`... -m studies.trader_replication.ie27_report all`。完整子问题须源码/登记/输入摘要一致才恢复。',
        '## 已试 / 未试',
        '已试：5543列三晚描述和20次同票对照、IE26签名核对、七个真实训练集合重新分组、E四轮固定候选/中间最好/内部消融、logit和深二提升树固定档次、全部主尺子训练选择、六半年嵌套留出、五个新种子完整打乱、30次随机、主副两宽度、全段最终版本逐项删除、每项公式/行为/半年作用/三命中三漏例子、折间重合、漏票归因和规定测试。',
        '未试：公式搜索B、E/A组合、新因子、新过滤池、参数网格、新行情、持仓/执行/仓位/止损/退出/杠杆及账户回放。']
    (m.REPORTS / (m.PREFIX + 'report_CN.md')).write_text('\n\n'.join(text) + '\n')


def manifest():
    files = [Path(m.__file__), Path(__file__), m.PLAN, m.PREREG,
             m.ROOT / 'studies/trader_replication/tests/test_martin_continue_ie27.py']
    files.extend(f for f in m.REPORTS.glob(m.PREFIX + '*') if f.is_file() and f != m.path('delivery_manifest'))
    files.extend(f for f in m.WORK.glob('*.npy') if f.is_file())
    m.write('delivery_manifest', dict(files={str(f.relative_to(m.ROOT)): dict(bytes=f.stat().st_size, sha256=m.sha(f))
                                           for f in sorted(set(files))}, signature=m.signature()))


def main(stage):
    m.WORK.mkdir(exist_ok=True)
    m.guard()
    d = m.Data()
    m.initialize(d)
    functions = dict(diagnostics=diagnostics, verify=verify, description=description_report, report=render)
    if stage == 'all':
        for function in (diagnostics, verify, description_report, render):
            function(d)
        manifest()
    else:
        functions[stage](d)
        if stage == 'report':
            manifest()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=('diagnostics', 'verify', 'description', 'report', 'all'))
    main(parser.parse_args().stage)
