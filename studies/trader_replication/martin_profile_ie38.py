"""IE38 stages: freeze candidate selection before opening final-year results.

The fitter calls run_stage with its namespace. Each candidate's ``fit`` stage
saves only training and internal CV results. ``finish`` selects from those files,
writes selection.json, then evaluates the five saved score vectors exactly once.
"""
import hashlib
import json
import os
from pathlib import Path

import numpy as np

from studies.trader_replication.standard_indicators_dedup import WORK, GAP, capacity, process_rss
from studies.trader_replication import standard_indicators as standard

TRAIN_HALVES = ('2024H1', '2024H2', '2025H1', '2025H2')
HOLDOUT_HALVES = ('2026H1', '2026H2')
CANDIDATES = ('h1', 'h2', 'h3', 'h4', 'h5')
SHUFFLE_SEEDS = (20261104381, 20261104382, 20261104383, 20261104384, 20261104385)
RANDOM_SEED = 20261104386
ROOT = Path(__file__).resolve().parents[2]
_GUARD_INSTALLED = False


def _offline_audit(event, values):
    if event in ('socket.connect', 'socket.bind', 'socket.getaddrinfo', 'subprocess.Popen', 'os.system'):
        raise PermissionError('IE38 research workers are offline and do not spawn children')
    if event == 'open' and not isinstance(values[0], int):
        name = Path(os.fsdecode(values[0])).name
        if (name.startswith('RULES') and name.endswith('.md')) or name in ('trades.csv', 'INTERVIEWS_CORE_CN.md') or name.endswith(('.srt', '.vtt')):
            raise PermissionError('IE38 does not read human rules, interviews or ledger remarks')


def install_offline_guard():
    import sys
    global _GUARD_INSTALLED
    if not _GUARD_INSTALLED:
        sys.addaudithook(_offline_audit)
        _GUARD_INSTALLED = True


def clean(value):
    if isinstance(value, dict):
        return {str(k): clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, np.ndarray)):
        return [clean(v) for v in value]
    if isinstance(value, (np.floating, float)):
        return float(value) if np.isfinite(value) else None
    if isinstance(value, (np.integer, np.bool_)):
        return value.item()
    return value


def write(path, value):
    temp = path.with_suffix(path.suffix+'.tmp')
    temp.write_text(json.dumps(clean(value), ensure_ascii=False, indent=2, allow_nan=False)+'\n')
    temp.replace(path)


def fingerprints():
    relative = ('studies/martin_luk/notes/PLAN_IE38_CN.md',
                'studies/martin_luk/notes/PREREG_IE38_CN.md',
                'studies/trader_replication/martin_profile_ie29.py',
                'studies/trader_replication/martin_profile_ie38.py',
                'studies/trader_replication/standard_indicators.py',
                'studies/trader_replication/standard_indicators_dedup.py',
                'studies/trader_replication/reports/gap_review/standard_indicators_v1_dedup.json')
    return {p: hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in relative}


def verify_preregistration():
    original = json.loads((WORK/'initial_fingerprints.json').read_text())
    for name, digest in original.items():
        if name.endswith(('PLAN_IE38_CN.md', 'PREREG_IE38_CN.md')):
            if hashlib.sha256((ROOT/name).read_bytes()).hexdigest() != digest:
                raise ValueError('task book or preregistration changed')


def candidate_name(ctx):
    name = ctx['TAG'].lower().removeprefix('ie38_')
    if name not in CANDIDATES:
        raise ValueError('IE38 tag must be h1..h5')
    return name


def cv_fit(ctx, targets):
    log, fit, rank, evaluate = (ctx[k] for k in ('log', 'fit_scorer', 'ranks_of', 'evaluate'))
    folds = []
    for half in TRAIN_HALVES:
        train = [t for t in targets if t[2] in TRAIN_HALVES and t[2] != half]
        test = [t for t in targets if t[2] == half]
        scores, models, _ = fit(train)
        check_model(ctx, models[0])
        val = evaluate(rank(scores), test)
        model = [dict(name=ctx['NAMES'][k], bins=q, weight=w) for (k, q), w in models[0].items()]
        folds.append(dict(half=half, hit=val[0], n=sum(t[3] for t in test), model=model,
                          bin_source_halves=sorted(set(ctx['ROW_HALVES'][ctx['TRAIN_MASK']])),
                          bin_source_rows=int(ctx['TRAIN_MASK'].sum())))
        capacity('cv_'+half)
        log('CV', half, val, model)
    train = [t for t in targets if t[2] in TRAIN_HALVES]
    scores, models, _ = fit(train)
    if len(models) != 1 or isinstance(scores, tuple):
        raise ValueError('IE38 requires a single profile')
    model = models[0]
    check_model(ctx, model)
    val = evaluate(rank(scores), train)
    return dict(cv_hit=sum(row['hit'] for row in folds), cv_n=sum(row['n'] for row in folds),
                folds=folds, train_fit=val, model=[dict(name=ctx['NAMES'][k], bins=q, weight=w)
                                                  for (k, q), w in model.items()]), scores, model


def check_model(ctx, model):
    if len(model) > ctx['args'].max_attrs or any(w not in (1, 1.5, 2, 3) for w in model.values()):
        raise ValueError('model exceeded preregistered capacity or weights')
    if ctx['args'].one_per_family:
        families = [family(ctx['NAMES'][key[0]]) for key in model]
        if len(families) != len(set(families)):
            raise ValueError('more than one indicator selected from a family')


def select_candidate(candidates):
    return min(CANDIDATES, key=lambda name: (-candidates[name]['cv_hit'], len(candidates[name]['model']), CANDIDATES.index(name)))


def profile(ctx, train, model):
    tables = ctx['tables_for'](train)
    groups = ctx['learn_groups'](train)
    result = {}
    for (k, q), weight in model.items():
        bins, edges = ctx['BINS'][(k, q)]
        nb = len(edges)+2
        pool = np.bincount(bins[ctx['TRAIN_MASK']], minlength=nb)
        his = np.zeros(nb)
        for group in groups:
            np.add.at(his, bins[group], 1/len(group))
        labels = ([f'< {edges[0]:.6g}']+[f'{a:.6g} 至 {b:.6g}' for a, b in zip(edges, edges[1:])]
                  +[f'>= {edges[-1]:.6g}', '缺失']) if len(edges) else ['全部有效值', '缺失']
        result[ctx['NAMES'][k]] = dict(weight=weight, bins=q, edges=edges,
            distribution=[dict(interval=labels[j], pool_share=pool[j]/pool.sum(),
                               target_share=his[j]/his.sum() if his.sum() else 0,
                               preference_ratio=float(np.exp(tables[(k, q)][j])))
                          for j in range(nb) if pool[j]])
    return result


def fit_candidate(ctx):
    name = candidate_name(ctx)
    args = ctx['args']
    expected_bins = (3, 5) if name == 'h5' else (3, 5, 10)
    if (args.max_attrs != 7 or args.cooldown != 10 or args.filter != 'h4nan'
            or ctx['LEARN'] != (0, 1, 2) or ctx['BIN_CHOICES'] != expected_bins
            or args.library != ('legacy' if name == 'h1' else 'std_v1')
            or args.own_scan != (name == 'h3') or args.one_per_family != (name == 'h4')
            or args.mix or args.em or args.bag or args.interval or args.nested or args.renew
            or args.beam != 1 or args.smooth != 2 or args.learn_all):
        raise ValueError('candidate differs from IE38 preregistration')
    if name == 'h1' and ctx['DROP'] != {'listed_days', 'pool_run_nights', 'pool_nights_20', 'theme_peers_pool', 'theme_rank_rs21'}:
        raise ValueError('H1 must use the IE32 exclusion list')
    path = WORK/(name+'_fit.json')
    if path.exists():
        raise ValueError('candidate already fitted; inspect its immutable artifact instead of refitting')
    result, scores, model = cv_fit(ctx, ctx['REAL'])
    train = [t for t in ctx['REAL'] if t[2] in TRAIN_HALVES]
    result.update(candidate=name, stage='training_only', profile=profile(ctx, train, model),
                  config=vars(ctx['args']), names_used=[ctx['NAMES'][k] for k in ctx['USE']],
                  fingerprints=fingerprints(), resources=capacity(name+'_fit_complete'))
    np.save(WORK/(name+'_scores.npy'), scores)
    write(path, result)
    ctx['log']('TRAINING_ONLY_COMPLETE', name, result['cv_hit'], result['train_fit'], result['model'])


def legacy_family(name):
    if name.startswith(('ext_ema', 'ema', 'above_ema')):
        return 'trend'
    if name.startswith(('perf', 'rs', 'up_days')):
        return 'relative_strength'
    if name in ('close_pos', 'lod_stop_pct'):
        return 'mean_reversion'
    if name.startswith(('adr', 'range', 'contract')) or name in ('inside_day', 'nr7'):
        return 'volatility'
    if name.startswith(('dollar', 'rvol')):
        return 'volume'
    if name.startswith('avwap'):
        return 'anchored_volume'
    if name.startswith('theme'):
        return 'theme'
    if name.startswith(('option', 'iv')):
        return 'options'
    if name.startswith('earn'):
        return 'events'
    if name == 'price':
        return 'price'
    return 'structure'


def family(name):
    if name in ('pool_nights_20', 'theme_peers_pool'):
        return 'own_scan'
    return next((s['family'] for s in standard.V1_SPEC if s['name'] == name), legacy_family(name))


def target_details(ctx, ranks, targets):
    selected = ctx['picks'](ranks, 3, 3)
    hits = ctx['covered'](selected, targets, 3)
    lookup, cal = ctx['lookup'], ctx['cal']
    details = []
    for (code, i0, half, primary), hit in zip(targets, hits):
        if not primary:
            continue
        pool_nights = [j for j in range(i0-6, i0+3) if (code, j) in lookup]
        later = next((j for j in sorted(selected) if j > i0+2 and code in selected[j]), None)
        kind = '命中' if hit else '不在池' if not pool_nights else '晚几晚才挑中' if later is not None else '在池没挑中'
        details.append(dict(code=code, entry=cal[i0], half=half, hit=hit, category=kind,
                            pool_nights=[cal[j] for j in pool_nights],
                            best_rank=min((int(ranks[lookup[(code, j)]]) for j in pool_nights), default=None),
                            later_pick=cal[later] if later is not None else None,
                            later_sessions=later-i0 if later is not None else None))
    return details


def summarize_random(ctx, train, test, observed):
    rng = np.random.default_rng(RANDOM_SEED)
    rows = []
    for _ in range(30):
        ranks = np.empty(ctx['N'], np.int32)
        for sl in ctx['SL'].values():
            ranks[sl] = rng.permutation(sl.stop-sl.start)+1
        rows.append(dict(train=ctx['evaluate'](ranks, train)[0], test=ctx['evaluate'](ranks, test)[0],
                         four_train=ctx['evaluate'](ranks, train, K=2, H=2)[0],
                         four_test=ctx['evaluate'](ranks, test, K=2, H=2)[0]))
    summary = {}
    for key in rows[0]:
        values = [row[key] for row in rows]
        summary[key] = dict(mean=float(np.mean(values)), min=min(values), max=max(values),
                            at_least_observed=sum(v >= observed[key] for v in values), draws=values)
    return dict(seed=RANDOM_SEED, draws=30, results=summary)


def shuffled_labels(ctx, seed):
    rng = np.random.default_rng(seed)
    mapping, night_permutations, fake = {}, {}, []
    for code, i0, half, primary in ctx['REAL']:
        key = (code, i0)
        if key not in mapping:
            available = [j for j in range(i0-6, i0+3) if (code, j) in ctx['lookup']]
            same_half = [j for j in available if ctx['ROW_HALVES'][ctx['lookup'][(code, j)]] == half]
            if same_half:
                anchor = min(same_half, key=lambda j: (abs(j-i0), j))
                sl = ctx['SL'][ctx['cal'][anchor]]
                if anchor not in night_permutations:
                    codes = ctx['CODES'][sl]
                    night_permutations[anchor] = dict(zip(codes, rng.permutation(codes)))
                mapping[key] = night_permutations[anchor][code]
            else:
                mapping[key] = code
        fake.append((mapping[key], i0, half, primary))
    return fake


def finish(ctx, defer_shuffles=False):
    output = GAP/'strong_continue_ie38.json'
    if output.exists():
        result = json.loads(output.read_text())
        if result['fingerprints'] != fingerprints() or candidate_name(ctx) != result['selected']:
            raise ValueError('resume source or candidate changed')
        if not defer_shuffles:
            complete_diagnostics(ctx, result)
        return
    candidates = {name: json.loads((WORK/(name+'_fit.json')).read_text()) for name in CANDIDATES}
    if any(row['fingerprints'] != fingerprints() for row in candidates.values()):
        raise ValueError('candidates were fitted from different source versions')
    chosen = select_candidate(candidates)
    selection = dict(selected=chosen, rule='max internal CV hits, then fewer full-training terms, then H1..H5',
                     candidates={name: dict(cv_hit=candidates[name]['cv_hit'], terms=len(candidates[name]['model'])) for name in CANDIDATES},
                     selected_without_holdout_results=True)
    path = WORK/'selection.json'
    if path.exists():
        if json.loads(path.read_text()) != selection:
            raise ValueError('saved selection changed')
    else:
        write(path, selection)
    if candidate_name(ctx) != chosen:
        raise ValueError(f'selected {chosen}; finish must use its saved configuration')
    if candidates[chosen]['config'] != {**vars(ctx['args']), 'ie38_stage': 'fit'}:
        raise ValueError('finish configuration differs from selected training configuration')
    expected = candidates[chosen]['fingerprints']
    if fingerprints() != expected:
        raise ValueError('source changed since candidates were fitted')
    train = [t for t in ctx['REAL'] if t[2] in TRAIN_HALVES]
    test = [t for t in ctx['REAL'] if t[2] in HOLDOUT_HALVES]
    if sum(t[3] for t in train) != 28 or sum(t[3] for t in test) != 23:
        raise ValueError('primary targets no longer match the preregistration')
    for name, row in candidates.items():
        ranks = ctx['ranks_of'](np.load(WORK/(name+'_scores.npy')))
        row.update(test_hit=ctx['evaluate'](ranks, test)[0],
                   four_train_hit=ctx['evaluate'](ranks, train, K=2, H=2)[0],
                   four_test_hit=ctx['evaluate'](ranks, test, K=2, H=2)[0],
                   details=target_details(ctx, ranks, ctx['REAL']))
        ctx['log']('FINAL_YEAR_ONCE', name, row['test_hit'])
    selected = candidates[chosen]
    ranks = ctx['ranks_of'](np.load(WORK/(chosen+'_scores.npy')))
    baseline = ctx['ranks_of'](ctx['_score'])
    ie9 = dict(train=ctx['evaluate'](baseline, train)[0], test=ctx['evaluate'](baseline, test)[0])
    observed = dict(train=selected['train_fit'][0], test=selected['test_hit'],
                    four_train=selected['four_train_hit'], four_test=selected['four_test_hit'])
    random = summarize_random(ctx, train, test, observed)
    names = ctx['NAMES']
    model = {(names.index(row['name']), row['bins']): row['weight'] for row in selected['model']}
    tables = ctx['tables_for'](train)
    groups = {}
    for key in model:
        groups.setdefault(family(names[key[0]]), []).append(key)
    ablations = []
    for kind, drop, keys in ([('indicator', names[key[0]], [key]) for key in model]+
                              [('family', group, keys) for group, keys in groups.items()]):
        rest = {key: value for key, value in model.items() if key not in keys}
        r = ctx['ranks_of'](ctx['score'](rest, tables))
        ablations.append(dict(kind=kind, drop=drop, names=[names[key[0]] for key in keys],
                              train=ctx['evaluate'](r, train)[0], test=ctx['evaluate'](r, test)[0]))
    # Save final-year results before the long, purely diagnostic shuffle refits.
    result = dict(selection=selection, candidates=candidates, selected=chosen, ie9=ie9, random=random,
                  ablation=ablations, shuffled=[], final_year_evaluated=True, diagnostics_complete=False,
                  forward=selected['cv_hit'] > candidates['h1']['cv_hit'] and selected['test_hit'] >= 11,
                  fingerprints=expected, resources=capacity('final_year_saved'))
    write(output, result)
    if not defer_shuffles:
        complete_diagnostics(ctx, result)


def shuffle_one(ctx, seed):
    fake = shuffled_labels(ctx, seed)
    row, scores, _ = cv_fit(ctx, fake)
    fake_test = [t for t in fake if t[2] in HOLDOUT_HALVES]
    row.update(seed=seed, test_hit=ctx['evaluate'](ctx['ranks_of'](scores), fake_test)[0],
               fingerprints=fingerprints(), resources=capacity('shuffle_complete'))
    ctx['log']('SHUFFLE_COMPLETE', seed, row['cv_hit'], row['train_fit'], row['test_hit'])
    return row


def isolated_shuffle(ctx):
    seed = ctx['args'].ie38_shuffle_seed
    if seed not in SHUFFLE_SEEDS:
        raise ValueError('unregistered shuffle seed')
    result = json.loads((GAP/'strong_continue_ie38.json').read_text())
    if candidate_name(ctx) != result['selected'] or result['fingerprints'] != fingerprints():
        raise ValueError('shuffle source or selected candidate changed')
    expected = result['candidates'][result['selected']]['config']
    actual = {**vars(ctx['args']), 'ie38_stage': 'fit', 'ie38_shuffle_seed': 0}
    if actual != expected:
        raise ValueError('shuffle configuration differs from selected candidate')
    path = WORK/f'shuffle_{seed}.json'
    if path.exists():
        if json.loads(path.read_text())['fingerprints'] != fingerprints():
            raise ValueError('saved shuffle source changed')
        return
    write(path, shuffle_one(ctx, seed))


def complete_diagnostics(ctx, result):
    output = GAP/'strong_continue_ie38.json'
    completed = {row['seed'] for row in result['shuffled']}
    for seed in SHUFFLE_SEEDS:
        if seed in completed:
            continue
        row = shuffle_one(ctx, seed)
        result['shuffled'].append(row)
        write(output, result)
        ctx['log']('SHUFFLE_COMPLETE', seed, row['cv_hit'], row['train_fit'], row['test_hit'])
    result['diagnostics_complete'] = True
    result['resources'] = capacity('all_checks_complete')
    write(output, result)
    report(result)


def report(result):
    frozen = json.loads((GAP/'standard_indicators_v1_dedup.json').read_text())
    selected = result['candidates'][result['selected']]
    label = result['selected'].upper()
    random = result['random']['results']
    strongest = []
    for name, profile_ in selected['profile'].items():
        bins = sorted(profile_['distribution'], key=lambda row: -row['preference_ratio'])
        strongest.append(f"`{name}`：{bins[0]['interval']}（权重 {profile_['weight']}、偏好倍数 {bins[0]['preference_ratio']:.2f}）")
    merges = [row for row in frozen['dropped'] if row['reason'] == 'absolute_spearman_at_least_0.9']
    rare = [row for row in frozen['dropped'] if row['reason'] == 'binary_occurrence_below_1pct']
    family_cn = dict(trend='均线趋势', momentum='动量震荡', relative_strength='涨幅与相对强弱',
                     mean_reversion='均值回归', volatility='波动通道', volume='成交量资金流',
                     anchored_volume='锚定成交量', structure='价格结构', candles='K 线形态',
                     chan='缠论', smc='SMC', chips='筹码', templates='体系模板',
                     multi_timeframe='多周期', theme='题材同伴', options='期权', events='事件', price='价格', own_scan='自己的扫描')
    merged_families = '、'.join(dict.fromkeys(family_cn[family(row['name'])] for row in merges))
    portrait_families = '、'.join(dict.fromkeys(family_cn.get(family(row['name']), '自己的扫描') for row in selected['model']))
    text = [f"# IE38：统一标准指标库 v1 与第一次拟合\n\n",
            f"结论：标准库从 127 项代表冻结为 **{len(frozen['retained'])} 项**；主要在{merged_families}合并 {len(merges)} 项，出现率不足 1% 去掉 {len(rare)} 项。",
            f"只看 2024–25 内部交叉验证，挑中 **{label}**：**{selected['cv_hit']}/28**，正式 2026 结果 **{selected['test_hit']}/23**。",
            f"对照 IE32 的内部交叉验证 18/28、2026 10/23，以及 IE9 的 14/28、7/23；本段同预算随机 30 次在 2026 平均 {random['test']['mean']:.2f}/23、范围 {random['test']['min']}–{random['test']['max']}。",
            f"按预登记双门槛，本段**{'前进' if result['forward'] else '未前进'}**（必须内部交叉验证超过本段 H1，且 2026 至少 11/23）。",
            '画像：'+'；'.join(strongest)+f"，主要在看{portrait_families}。\n\n",
            "## 五个候选\n\n| 候选 | 可选指标数 | 最终项数 | 拟合命中 / 28 | 内部 CV / 28 | 2026 / 23 | 约 4 只：拟合 / 28 | 约 4 只：2026 / 23 |\n|---|---:|---:|---:|---:|---:|---:|---:|\n"]
    for name, row in result['candidates'].items():
        text.append(f"| {name.upper()}{'（选中）' if name == result['selected'] else ''} | {len(row['names_used'])} | {len(row['model'])} | {row['train_fit'][0]} | {row['cv_hit']} | {row['test_hit']} | {row['four_train_hit']} | {row['four_test_hit']} |\n")
    text.append("\nH1 为 IE32 的现行缓存库并沿用原排除清单；H2 为 std_v1；H3 加自己的扫描次数与扫描内同伴；H4 每个流派最多一项；H5 只用 3/5 档。所有候选均最多 7 项、权重 1/1.5/2/3、h4nan、3 新/晚、持有 3 晚、冷却 10 晚。约 4 只使用 2 新/晚、持有 2 晚，仅报告。\n")
    text.append("\n每个训练折各自确定分档边界、池占比和标签分布；2026 不参与分档、选指标、选参数或挑版本。先保存四折与全训练模型，`ie38_work/selection.json` 落盘之后才打开五个冻结模型的 2026 结果。为保留现行拟合器及 H1 对照，搜索同分仍看目标票窗口内最佳名次的倒数之和（目标数固定，与平均倒数名次等价）；规格第四节的“平均名次”没有另行替换成算术平均名次。共同权重菜单按本段任务书取 1/1.5/2/3，旧版默认中的 0.5 不在本段预算内；未开新选项的旧复现路径保留原菜单。2026 已在前段多次使用，本段正式结果仍属已反复研究的留出年，不能称全新样本外。\n")
    text.append("\n## 内部四折与画像\n\n| 候选 | 2024H1 / 5 | 2024H2 / 6 | 2025H1 / 4 | 2025H2 / 13 |\n|---|---:|---:|---:|---:|\n")
    for name, row in result['candidates'].items():
        text.append('| '+name.upper()+' | '+' | '.join(str(fold['hit']) for fold in row['folds'])+' |\n')
    text.append('\n'+"\n".join('- '+line for line in strongest)+'\n')
    text.append("\n每项完整训练边界、池占比、目标占比与偏好倍数见 JSON 的 `candidates.*.profile`。偏好倍数高于 1 说明在该区间的目标占比较池占比高；缺失单列一档。\n")
    text.append("\n## 消融：固定已拟合模型，去掉贡献，不重新挑项\n\n| 去掉范围 | 去掉项 / 流派 | 拟合 / 28 | 2026 / 23 |\n|---|---|---:|---:|\n")
    for row in result['ablation']:
        text.append(f"| {'逐项' if row['kind'] == 'indicator' else '整组'} | `{row['drop']}` | {row['train']} | {row['test']} |\n")
    text.append("\n整组按 SPEC 流派去掉；若全删空，以零分和原池顺序排序，不临时换成 IE9。2026 消融只报告，不据此换正式模型。H3 与 H2 同时提供自己的扫描量有无对照。\n")
    text.append("\n## 同预算随机与打乱标签\n\n| 对照 | 拟合命中 | 内部 CV | 2026 |\n|---|---|---|---|\n")
    text.append(f"| 随机 30 次 | 均值 {random['train']['mean']:.2f}，{random['train']['min']}–{random['train']['max']} | 同一冻结随机排序按四折计数，等于训练段总命中 | 均值 {random['test']['mean']:.2f}，{random['test']['min']}–{random['test']['max']} |\n")
    for row in result['shuffled']:
        text.append(f"| 打乱标签 {row['seed']}，重做选中候选的四折与全段拟合 | {row['train_fit'][0]} | {row['cv_hit']}/28 | {row['test_hit']}/23 |\n")
    exceed = sum(row['test_hit'] >= selected['test_hit'] for row in result['shuffled'])
    text.append(f"\n随机 2026 ≥ 正式模型的次数 {random['test']['at_least_observed']}/30；打乱标签 ≥ 正式模型 {exceed}/5，有限次校正尾概率 {(1+exceed)/6:.3f}。打乱保留原入场日期、半年、主/次目标和缺池状态，在原目标可见的同半年邻近池夜晚对代码标签作一一置换；每次重新确定训练档、选项、调权，2026 只做诊断，不在五个候选间重新择优。\n")
    text.append("\n## 漏掉的票\n\n分类按固定窗口判定：主尺子的持有折算为新挑夜晚 −6..+2；窗口中无池行记“不在池”；有池行但后来也未挑中记“在池没挑中”；窗口后出现第一次新挑记“晚几晚才挑中”，这里完整列出延迟，不把几十晚后的巧合当有效命中。\n\n| 段 | 股票 | 入场 | 分类 | 窗口内最好名次 | 后来新挑 / 延迟交易晚数 |\n|---|---|---|---|---:|---|\n")
    for row in selected['details']:
        if not row['hit']:
            later = f"{row['later_pick']} / {row['later_sessions']}" if row['later_pick'] else '未挑中'
            text.append(f"| {row['half']} | {row['code']} | {row['entry']} | {row['category']} | {row['best_rank'] if row['best_rank'] is not None else '—'} | {later} |\n")
    text.append("\n## 冻结、边界与复算\n\n标准库只依赖标准库和 numpy，未引用旧指标库；127 项全部有 SPEC 元数据。每项截断因果性、默认公式、别名秩、周内合成周线、成交量分布及全市场同伴均以合成数据验证。全部数据来自已有日线与 extras 缓存，无网络取数、无 OpenD、无后台采集。市场相关性按请求行与 128 只分块，不创建全市场 N×N 矩阵。\n")
    peak = max(result['resources']['peak_rss_bytes'], *(row['resources']['peak_rss_bytes'] for row in result['candidates'].values()))
    parallel = [json.loads(path.read_text()) for path in WORK.glob('*_resources.json')
                if path.name.startswith(('parallel_', 'fit_parallel', 'evaluation_parallel', 'shuffle_parallel'))]
    dedup_peak = max([frozen['freeze_resources']['peak_rss_bytes']]+
                     [value for row in parallel for value in row.get('process_peak_bytes', [])])
    aggregate = max((row['aggregate_upper_bound_bytes'] for row in parallel), default=max(dedup_peak, peak))
    text.append(f"\n指标去重固定抽样 300,000 行，各进程最高 RSS {dedup_peak/1e6:.1f} MB；拟合及诊断各进程最高 RSS {peak/1e6:.1f} MB；并发阶段合计 RSS 的保守上界 {aggregate/1e6:.1f} MB（含协调进程）。`ie38_work/` {result['resources']['work_bytes']/1e6:.1f} MB，磁盘剩余 {result['resources']['free_bytes']/1e9:.2f} GB。完整相关对与稀少项清单见 `standard_indicators_v1_dedup.json`、规格末尾及代码常量 `V1_NAMES`。\n")
    text.append("\n运行中用户追加资源授权：外层两核合计 CPU 上限 120%，同时最多两个研究工作进程；每个进程内部 OPENBLAS_NUM_THREADS=1、OMP_NUM_THREADS=1，每进程峰值上限 900 MB、合计 1.8 GB。按固定股票/夜晚/相关对索引分片，写入互不重叠的样本位置，整数计数及相关对按串行顺序汇总；候选、种子和选择规则保持原样。并行逐值复核见 `ie38_work/parallel_consistency.json`。任务书与预登记没有修改。\n")
    text.append("\n数据与实现限制：IPO 前缺行情不填零；期权、财报、4 小时数据缺失时输出 NaN；缠论沿用因果包含合并/简化笔与中枢；筹码以日线成交量换手代理。CMO 别名只针对与 RSI 同平滑版本，滚动求和 CMO 不作恒等承诺。2026 的同伴与 IBD RS 仅使用当晚及以前的全市场行情，是观察输入而非拟合输入。\n")
    text.append("\n已试：127 项库、全市场去重与稀少形态处理、五候选四折及冻结模型、5 次新种子完整标签对照、30 次同预算随机、逐项与按流派消融、约 4 只口径。未试：新数据、参数网格、改目标、改过滤、收益回测、盘中择时、交易执行；本段不替换登记版、不提交、不推送。\n")
    (GAP/'strong_continue_ie38_CN.md').write_text(''.join(text))


def run_stage(ctx, stage):
    WORK.mkdir(exist_ok=True)
    verify_preregistration()
    capacity('start_'+stage)
    if stage == 'fit':
        fit_candidate(ctx)
    elif stage == 'shuffle':
        isolated_shuffle(ctx)
    else:
        finish(ctx, defer_shuffles=stage == 'evaluate')


def fitter_flags(name, action, seed=0):
    flags = ['--tag', name, '--filter', 'h4nan', '--learn', '0,1,2', '--max-attrs', '7',
             '--cooldown', '10', '--holdout', ','.join(HOLDOUT_HALVES), '--inner-cv',
             '--train-edges', '--ie38-stage', action]
    if name == 'h1':
        flags += ['--drop', 'listed_days,pool_run_nights,pool_nights_20,theme_peers_pool,theme_rank_rs21']
    else:
        flags += ['--library', 'std_v1']
    if name == 'h3':
        flags += ['--own-scan']
    if name == 'h4':
        flags += ['--one-per-family']
    if name == 'h5':
        flags += ['--bins', '3,5']
    if seed:
        flags += ['--ie38-shuffle-seed', str(seed)]
    return flags


def run_process_jobs(jobs, label):
    """At most two single-threaded fitters; only their parent owns the final report."""
    import subprocess
    import sys
    import time

    pending, active, completed = list(jobs), [], []
    peak_sum = 0
    environment = {**os.environ, 'OPENBLAS_NUM_THREADS': '1', 'OMP_NUM_THREADS': '1', 'PYTHONDONTWRITEBYTECODE': '1'}
    try:
        while pending or active:
            for job in list(pending):
                if len(active) >= 2:
                    break
                name, action, seed = job
                artifact = WORK/(f'shuffle_{seed}.json' if action == 'shuffle' else name+'_fit.json')
                if action != 'evaluate' and artifact.exists():
                    saved = json.loads(artifact.read_text())
                    if saved['fingerprints'] != fingerprints():
                        raise ValueError('saved worker artifact belongs to different source')
                    completed.append(saved['resources']['peak_rss_bytes'])
                    pending.remove(job)
                    continue
                # H2 is the only writer of the common standard matrix. An atomic
                # rename publishes it, after which other candidates may read it.
                if action == 'fit' and name in ('h3', 'h4', 'h5') and not (WORK/'pool_standard.npz').exists():
                    continue
                suffix = f'shuffle_{seed}' if seed else action
                stream = (WORK/f'{name}_{suffix}.log').open('a')
                command = [sys.executable, '-m', 'studies.trader_replication.martin_profile_ie29']+fitter_flags(name, action, seed)
                process = subprocess.Popen(command, cwd=ROOT, env=environment, stdout=stream, stderr=subprocess.STDOUT)
                active.append((job, process, stream))
                pending.remove(job)
                print('start worker', name, action, seed, process.pid, flush=True)
            for item in list(active):
                (name, action, seed), process, stream = item
                code = process.poll()
                if code is None:
                    continue
                stream.close()
                active.remove(item)
                if code:
                    raise RuntimeError(f'{name} {action} {seed} failed; inspect its worker log')
                artifact = GAP/'strong_continue_ie38.json' if action == 'evaluate' else WORK/(f'shuffle_{seed}.json' if seed else name+'_fit.json')
                saved = json.loads(artifact.read_text())
                completed.append(saved['resources']['peak_rss_bytes'])
                print('complete worker', name, action, seed, flush=True)
            rss = [process_rss(os.getpid())]+[process_rss(process.pid) for _, process, _ in active]
            peak_sum = max(peak_sum, sum(rss))
            if any(value > 900_000_000 for value in rss) or sum(rss) > 1_800_000_000:
                raise RuntimeError('parallel fitter memory limit exceeded')
            capacity('driver_'+label)
            if pending and not active and all(action == 'fit' and name in ('h3', 'h4', 'h5')
                                              and not (WORK/'pool_standard.npz').exists()
                                              for name, action, _ in pending):
                raise RuntimeError('standard cache dependency is unavailable')
            if active:
                time.sleep(1)
    finally:
        for _, process, stream in active:
            if process.poll() is None:
                process.terminate()
                process.wait()
            stream.close()
    # The two largest worker peaks plus the parent peak are a conservative bound
    # even if the sampled aggregate monitor missed a short-lived allocation.
    upper = capacity('driver_done')['peak_rss_bytes']+sum(sorted(completed, reverse=True)[:2])
    if upper > 1_800_000_000 or any(value > 900_000_000 for value in completed):
        raise RuntimeError('recorded fitter peaks exceed the execution budget')
    resources = dict(max_research_workers=2, process_peaks=completed,
                     monitored_aggregate_peak_bytes=peak_sum, aggregate_upper_bound_bytes=upper)
    write(WORK/(label+'_parallel_resources.json'), resources)
    return resources


def collect_diagnostics():
    path = GAP/'strong_continue_ie38.json'
    result = json.loads(path.read_text())
    if result['fingerprints'] != fingerprints():
        raise ValueError('source changed after formal evaluation')
    rows = [json.loads((WORK/f'shuffle_{seed}.json').read_text()) for seed in SHUFFLE_SEEDS]
    if any(row['fingerprints'] != result['fingerprints'] for row in rows):
        raise ValueError('shuffled fits used different source')
    result['shuffled'] = rows
    result['diagnostics_complete'] = True
    resources = capacity('all_checks_complete')
    resources['peak_rss_bytes'] = max(resources['peak_rss_bytes'], result['resources']['peak_rss_bytes'],
                                     *(row['resources']['peak_rss_bytes'] for row in rows))
    result['resources'] = resources
    result['parallel_resources'] = {stage: json.loads((WORK/(stage+'_parallel_resources.json')).read_text())
                                    for stage in ('fit', 'evaluation', 'shuffle')}
    write(path, result)
    report(result)


def main():
    import argparse
    from contextlib import redirect_stdout, redirect_stderr
    import gc
    import runpy
    import sys

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=('all', 'fit_all', 'finish_selected', 'report'))
    parser.add_argument('--workers', type=int, choices=(1, 2), default=1)
    arguments = parser.parse_args()
    stage = arguments.stage
    WORK.mkdir(exist_ok=True)
    if stage == 'report':
        result = json.loads((GAP/'strong_continue_ie38.json').read_text())
        if not result['diagnostics_complete']:
            raise ValueError('diagnostics are incomplete')
        report(result)
        return

    if arguments.workers == 2:
        if stage in ('all', 'fit_all'):
            run_process_jobs([(name, 'fit', 0) for name in CANDIDATES], 'fit')
        if stage in ('all', 'finish_selected'):
            candidates = {name: json.loads((WORK/(name+'_fit.json')).read_text()) for name in CANDIDATES}
            chosen = select_candidate(candidates)
            run_process_jobs([(chosen, 'evaluate', 0)], 'evaluation')
            run_process_jobs([(chosen, 'shuffle', seed) for seed in SHUFFLE_SEEDS], 'shuffle')
            collect_diagnostics()
        return

    def invoke(name, action):
        flags = fitter_flags(name, action)
        print('start', name, action, capacity('driver'), flush=True)
        original = sys.argv
        sys.argv = ['martin_profile_ie29']+flags
        try:
            with (WORK/f'{name}_{action}.log').open('a') as stream, redirect_stdout(stream), redirect_stderr(stream):
                try:
                    runpy.run_module('studies.trader_replication.martin_profile_ie29', run_name='__main__')
                except SystemExit as exc:
                    if exc.code not in (None, 0):
                        raise
        finally:
            sys.argv = original
            gc.collect()
        print('complete', name, action, capacity('driver'), flush=True)

    if stage in ('all', 'fit_all'):
        for name in CANDIDATES:
            path = WORK/(name+'_fit.json')
            if path.exists():
                old = json.loads(path.read_text())
                if old['fingerprints'] != fingerprints():
                    raise ValueError('source changed; never silently refit a saved candidate')
                print('reuse immutable training fit', name, old['cv_hit'], flush=True)
            else:
                invoke(name, 'fit')
    if stage in ('all', 'finish_selected'):
        candidates = {name: json.loads((WORK/(name+'_fit.json')).read_text()) for name in CANDIDATES}
        invoke(select_candidate(candidates), 'finish')


if __name__ == '__main__':
    main()
