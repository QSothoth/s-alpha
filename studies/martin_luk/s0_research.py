"""Offline S0 signal-only audit. Reuses saved orders; never runs an account."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import fcntl
import hashlib
import json
import os
from pathlib import Path
import resource
import sys

import numpy as np

from studies.trader_replication.mainleg import signal_coverage_budget

ROOT = Path(__file__).resolve().parents[2]
HOME = Path(__file__).resolve().parent
OUT = HOME/'reports/s0_work'
GAP = ROOT/'studies/trader_replication/reports/gap_review'
YEARS = ('2024', '2025', '2026')
SOURCES = {}


def sha(path):
    with Path(path).open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def source(path):
    path = Path(path)
    key = str(path.relative_to(ROOT))
    if key not in SOURCES:
        SOURCES[key] = sha(path)
    return path


def read(path):
    return json.loads(source(path).read_text())


def array(path):
    return np.load(source(path), mmap_mode='r')


def write(name, value):
    path = OUT/name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=1, allow_nan=False)+'\n')


def resources():
    folder = Path('/sys/fs/cgroup')/next(line.split(':', 2)[2].lstrip('/') for line in
        Path('/proc/self/cgroup').read_text().splitlines() if line.startswith('0:'))
    return dict(python=sys.executable, cpu_max=(folder/'cpu.max').read_text().strip(),
        memory_max=(folder/'memory.max').read_text().strip(),
        threads=next(line.split(':')[1].strip() for line in Path('/proc/self/status').read_text().splitlines()
                     if line.startswith('Threads:')),
        peak_rss_mib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024)


def offline(test_mode=False):
    sys.dont_write_bytecode = True
    def guard(event, args):
        if event in ('socket.connect', 'socket.bind', 'socket.getaddrinfo') or (
                not test_mode and event in ('subprocess.Popen', 'os.system')):
            raise PermissionError('S0 is offline and single-process')
        if not test_mode and event == 'open' and not isinstance(args[0], int) and args[2] & (
                os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND):
            path = Path(os.fsdecode(args[0])).resolve()
            if not (path.is_relative_to(OUT.resolve()) or path == (HOME/'reports/S0_CN.md').resolve()):
                raise PermissionError('S0 output boundary: '+str(path))
    sys.addaudithook(guard)


def freeze():
    OUT.mkdir(parents=True, exist_ok=True)
    protected = []
    for directory in ('studies', 'skills', 'custody', 'watch', 'scripts', 'docs'):
        for path in (ROOT/directory).rglob('*'):
            if not path.is_file() or OUT in path.parents or path.name.startswith('s0_'):
                continue
            if path.suffix in ('.py', '.md') and path.name != 'S0_CN.md' and path != ROOT/'studies/trader_replication/mainleg.py' \
                    and path != ROOT/'studies/trader_replication/tests/test_signal_budget.py' \
                    and path != ROOT/'skills/trader-replication/references/METHOD_CN.md':
                protected.append(path)
    protected += list((HOME/'reports').glob('*.json'))
    protected += [HOME/'notes/legs_frozen.json', HOME/'notes/trades.csv']
    with (OUT/'protocol.json').open('x') as f:
        json.dump(dict(task='PLAN_S0_CN', memory_before=Path('/proc/meminfo').read_text(), resources=resources(),
            protected={str(p.relative_to(ROOT)): sha(p) for p in protected},
            plan_sha256=sha(HOME/'notes/PLAN_S0_CN.md'),
            denominator_sha256=sha(HOME/'notes/legs_frozen.json'),
            budgets=[1, 3, 5, None], cooldown=10,
            scope='saved signal/list recovery only; no fitting, execution, positions or accounts',
            cooldown_policy='previous ten calendar sessions; rejected repeats do not renew cooldown',
            width_policy='filter repeats then take at most K from the original system order; never expand a saved capped list',
            sample_policy='fit/tuning years are in-sample; per-system historical holdout is not a new independent validation',
            secret_guard='installer refused existing core.hooksPath; no hooks changed, no commit'), f, ensure_ascii=False, indent=1)
    print('S0 protocol frozen', resources(), flush=True)


def labels():
    frozen = read(HOME/'notes/legs_frozen.json')
    assert Counter(str(frozen['calendar'][g['first']])[:4] for g in frozen['legs']) == {'2024': 9, '2025': 22, '2026': 17}
    return frozen


def evaluate(name, picks, *, policy, order, evidence, end='2026-10-15', start='2024-01-01', notes=''):
    frozen = labels()
    for name_ in policy['sources']+evidence:
        path = ROOT/name_
        if path.is_file():
            source(path)
    calendar, legs = frozen['calendar'], frozen['legs']
    di = {d: t for t, d in enumerate(calendar)}
    # Only label opens are needed; the shared frozen panel is mmap-backed.
    panel = HOME/'reports/u1_work/panel'
    codes = array(panel/'codes.npy')
    days = array(panel/'days.npy')
    assert list(map(str, days)) == calendar
    opening = array(panel/'open.npy')
    ci = {str(c): j for j, c in enumerate(codes)}
    opens = {c: opening[:, ci[c]] for c in {g['code'] for g in legs} if c in ci}
    indices = {di[d]: cs for d, cs in picks.items() if d in di and d <= end and di[d] < len(calendar)-1}
    # Preserve all supplied warmup; add every empty evaluation night.
    for t, day in enumerate(calendar[:-1]):
        if start <= day <= end:
            indices.setdefault(t, [])
    results = {}
    for k in (1, 3, 5, None):
        result = signal_coverage_budget(indices, None, legs, calendar, opens, k)
        # Keep warmup in cooldown but exclude it from width/precision annual totals.
        result['annual'] = {y: result['annual'][y] for y in YEARS}
        result['total'] = dict(n=48, covered=sum(v['covered'] for v in result['annual'].values()))
        result['total']['coverage'] = result['total']['covered']/48
        shares = [r['first_hit']['share'] for r in result['per_leg'] if r['covered']]
        stats = result['annual'].values()
        count = sum(v['new_names'] for v in stats)
        result['total'].update(remaining_share_median=float(np.median(shares)) if shares else None,
            precision=sum(v['precision_hits'] for v in stats)/count if count else None,
            mean_new_names=count/sum(v['nights'] for v in stats) if sum(v['nights'] for v in stats) else None)
        result.pop('picks')
        results['unlimited' if k is None else str(k)] = result
    record = dict(system=name, policy=policy, order=order, evidence=evidence, start=start, end=end, notes=notes,
                  results=results, resources=resources())
    write('systems/'+name+'.json', record)
    write('picks/'+name+'.json', {calendar[t]: indices[t] for t in sorted(indices)})
    write('sources.json', SOURCES)
    print(name, {y: results['3']['annual'][y]['covered'] for y in YEARS}, resources()['peak_rss_mib'], flush=True)
    return record


def sample_policy(family, held=True):
    return dict(years={'2024': '样本内', '2025': '样本内', '2026': '留出*' if held else '未评测'},
                sources=[str((HOME/f'notes/PREREG_{family}_CN.md').relative_to(ROOT))],
                warning='留出*为该模型历史留出，2026已被前轮反复查看，不是全新独立样本外')


def saved():
    policy = sample_policy('IE47')
    d1 = HOME/'reports/d1_work'
    for stage in ('filtered', 'capped'):
        path = d1/f'master_{stage}.json'
        nights = defaultdict(list)
        for r in read(path):
            if r['side'] > 0:
                nights[r['day']].append(r)
        picks = {d: [r['code'] for r in sorted(rows, key=lambda r: r['priority'])] for d, rows in nights.items()}
        master_policy = dict(years={y: '样本内' for y in YEARS},
            sources=['skills/trader-replication/references/MARTIN_LUK_CN.md',
                     'studies/martin_luk/reports/final_system_r74.json', 'studies/martin_luk/reports/s7.json'],
            warning='登记R74/S7来自同段择优，三个历史年份均已参与研究；无留出')
        evaluate('master_'+stage, picks, policy=master_policy,
            order='原 priority 升序（成交额降序），相等保留原发信号顺序', evidence=[str(path.relative_to(ROOT))],
            notes='saved day作为可知信号夜，统一用下一交易日open评测；不复用旧报告的当日close口径')
    path = d1/'ie_selection.json'
    selection = read(path)
    base = selection['picks']
    evaluate('IE47', base, policy=policy, order='保存的逐晚点名顺序；系统原生最多3只，不扩充候选',
             evidence=[str(path.relative_to(ROOT))])
    path = GAP/'ie47_work/scorecard.json'
    scorecard = read(path)
    evaluate('IE47_legacy', scorecard['profile']['picks'], policy=policy,
        order='旧研究缓存保存的逐晚点名顺序，最多3只', evidence=[str(path.relative_to(ROOT))],
        notes='与全市场冻结面板适配版IE47分列；所有标签和价格仍统一到48段冻结面板')
    evaluate('IE9', scorecard['ie9']['picks'], policy=sample_policy('IE9'),
        order='保存的IE9冷却后每晚3个新点名顺序', evidence=[str(path.relative_to(ROOT))])
    for family, names in (('F1', ['F1a', 'F1b']), ('F2', ['G1', 'G3'])):
        for name in names:
            folder = HOME/f'reports/{family.lower()}_work'
            path = folder/f'picks_{name}.json'
            warmup = folder/f'picks_{name}_warmup.json'
            picks = read(warmup) | read(path)
            evaluate(family+'_'+name, picks, policy=sample_policy(family),
                order='保存的模型分数排序及原生每晚3个新名额；保留暖机点名',
                evidence=[str(p.relative_to(ROOT)) for p in (path, warmup)],
                notes='首选之外版本的2026为S0首次离线描述；不作事后选择或替换原结论')
    # These rounds changed observation life/retry/execution, not new-name nominations.
    for family in ('E16', 'E17', 'E18', 'E19', 'E21'):
        evaluate(family+'_IE47_list', base, policy=sample_policy(family),
            order='原IE47点名顺序；观察期限和重试不作为新的点名',
            evidence=[str((HOME/f'{"e16" if family in ("E16", "E17", "E18") else family.lower()}_research.py').relative_to(ROOT)),
                      'studies/martin_luk/reports/d1_work/ie_selection.json'],
            notes='同一名单的执行/观察变体合并一行；N0无冷却点名单列；E21没有新增点名')
    # E16 N0 explicitly emits the first three names without native cooldown.
    path = HOME/'reports/m1_work/validation_prepared/ie_nights.json'
    meta = read(HOME/'reports/m1_work/validation_prepared/ie_prepared.json')
    picks = {}
    for row in read(path):
        ix = np.argsort(-np.asarray(row['scores']), kind='stable')[:3] if row['available'] else []
        picks[meta['days'][row['t']]] = [meta['codes'][row['js'][k]] for k in ix]
    evaluate('E16_N0', picks, policy=sample_policy('E16'),
        order='原冻分降序稳定排序，无原生冷却，原生最多3；S评测统一再加10日冷却且不补第四名',
        evidence=[str(path.relative_to(ROOT)), 'studies/martin_luk/e16_research.py'])
    for name in ('A1', 'A2', 'A3', 'A4', 'A5'):
        path = HOME/f'reports/e20_work/{name}_nominations.json'
        evaluate('E20_'+name, read(path)['picks'], policy=sample_policy('E20', held=False), end='2025-12-30',
            order='原保存的picks顺序（原IE47点名与因果再点名的原次序）',
            evidence=[str(path.relative_to(ROOT))], notes='原实验未打开2026；不把缺工件写成0覆盖')


def profiles():
    from studies.trader_replication import martin_profile_f1 as F1, martin_profile_f2 as F2
    folder = HOME/'reports/f1_work'
    meta = read(folder/'cache.json')
    with np.load(source(folder/'rows.npz')) as archive:
        rows = {k: archive[k] for k in archive.files}
    checks = {}
    for family, module, names in (('F1', F1, ['F1a', 'F1b', 'F1c', 'F1d', 'F1e']),
                                  ('F2', F2, ['G1', 'G2', 'G3', 'G4', 'G5'])):
        work = HOME/f'reports/{family.lower()}_work'
        x = array(work/'features.npy')
        for name in names:
            path = work/f'fit_{name}.json'
            model = read(path)['model']
            sample = F1.Sample(meta, rows, x, model['spec'], []) if family == 'F1' else F2.sample_for(model, meta, rows, x, [])
            scores = F1.score_model(model, sample) if family == 'F1' else F2.score(model, sample)
            chosen = sample.nominate(scores)
            picks = {meta['days'][int(t)]: [meta['codes'][int(sample.code[r])] for r in row if r < len(scores)]
                     for t, row in zip(sample.nights, chosen)}
            export = work/f'picks_{name}.json'
            if export.exists():
                checks[family+'_'+name] = all(picks.get(day, []) == cs for day, cs in read(export).items())
                assert checks[family+'_'+name], name
            else:
                evaluate(family+'_'+name, picks, policy=sample_policy(family),
                    order=f'原Sample.nominate冻结模型推断；原生K={model["spec"]["k"]}、原生冷却={model["spec"]["cooldown"]}',
                    evidence=[str(path.relative_to(ROOT)), str((work/'features.npy').relative_to(ROOT))],
                    notes='只推断已冻结模型，不拟合；2026为S0固定描述，不据此改原选择')
            del sample, scores, chosen
    write('profile_replay_checks.json', checks)


def ie_context(config):
    """Execute the original module's setup/definitions, stopping before stage dispatch.

    No fit/evaluate stage, random trials, or original output writer is invoked.
    This keeps legacy score arithmetic and tie ordering byte-for-byte unchanged.
    """
    import ast
    path = source(ROOT/'studies/trader_replication/martin_profile_ie29.py')
    tree = ast.parse(path.read_text(), filename=str(path))
    nodes, tail, skip = [], [], False
    for node in tree.body:
        if isinstance(node, ast.If) and ast.unparse(node.test) == 'args.ie42_stage':
            break
        if config.get('library') == 'std_v1_1':
            if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'cache' for t in node.targets):
                skip = True
            if isinstance(node, ast.If) and ast.unparse(node.test) == "args.library != 'std_v1_1'":
                skip = False
                tail.append(node)
                continue
            if tail:
                tail.append(node)
                continue
            if skip:
                continue
        nodes.append(node)
    argv = [str(path)]
    for key, value in config.items():
        if key in ('ie40_stage', 'ie38_stage') or not value:
            continue
        flag = '--'+key.replace('_', '-')
        argv.extend([flag] if value is True else [flag+'='+str(value)])
    if config.get('library') == 'std_v1_1' and '--ie42-stage' not in argv:
        argv += ['--ie42-stage', 'fit']  # parser validation only; dispatch is outside the executed prefix
    old = sys.argv
    sys.argv = argv
    ctx = dict(__name__='s0_legacy_context', __file__=str(path))
    try:
        exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), 'exec'), ctx)
        if config.get('library') == 'std_v1_1':
            # This is a saved historical input, not a cache generated by today's code.
            # Validate its original signature with the recorded historical source hashes.
            manifest = read(GAP/'ie40_work/pool_manifest.json')
            fingerprints = read(GAP/'ie40_work/real_fit.json')['fingerprints']
            with np.load(source(GAP/'ie40_work/pool_standard_v1_1.npz')) as z:
                names, x, signature = list(z['names']), z['x'], str(z['signature'])
            expected = hashlib.sha256(json.dumps([
                fingerprints['studies/trader_replication/standard_indicators.py'],
                fingerprints['studies/trader_replication/martin_profile_ie40.py'], names, list(ctx['CODES']),
                list(map(int, ctx['row_day'])), ctx['cal'], ctx['b'].meta['scope']],
                sort_keys=True, separators=(',', ':')).encode()).hexdigest()
            assert signature == expected == manifest['signature'], 'historical cache row/source signature mismatch'
            assert names == manifest['names'] and x.shape == (len(names), ctx['N'])
            write('historical_cache_check.json', dict(ok=True, signature=signature, rows=ctx['N'],
                reason='current pool_matrix signature rejected source drift; historical artifact and row order verified against frozen source hashes'))
            ctx.update(NAMES=names, X=x)
            exec(compile(ast.Module(body=tail, type_ignores=[]), str(path), 'exec'), ctx)
    finally:
        sys.argv = old
    return ctx


def ranked_picks(ctx, scores):
    ranks = ctx['ranks_of'](scores)
    emitted = ctx['picks'](ranks, 3, 3)
    return {ctx['cal'][t]: sorted(cs, key=lambda c: int(ranks[ctx['lookup'][(c, t)]])) for t, cs in emitted.items()}


def ie_standard():
    from studies.trader_replication import martin_profile_ie42 as original
    fit = read(GAP/'ie43_work/fit.json')
    ctx = ie_context(fit['config'])
    path = GAP/'ie40_work/real_scores.npy'
    scores = array(path)
    assert len(scores) == ctx['N']
    evaluate('IE40', ranked_picks(ctx, scores), policy=sample_policy('IE40'),
        order='原保存real_scores降序稳定排序、原生3新名/晚及10夜冷却', evidence=[str(path.relative_to(ROOT))])
    # Reconstruct the fixed probability tables, never coefficient/item selection.
    original.mainleg_targets(ctx)
    train = [t for t in ctx['REAL'] if t[2] in original.TRAIN_HALVES]
    regime, tables, _ = original.build(ctx, train)
    shared = original.unpack(ctx, fit['model']['shared'])
    corrections = {k: original.unpack(ctx, v) for k, v in fit['model']['corrections'].items()}
    explain = read(GAP/'ie43_work/explain.json')
    unexplained = {(part, r['name']) for part, rr in explain.items() for r in rr if not r['explainable']}
    keep = lambda part, model: {k: w for k, w in model.items() if (part, ctx['NAMES'][k[0]]) not in unexplained}
    versions = dict(regime=original.combined(ctx, shared, corrections, tables),
        shared=ctx['score'](shared, tables['shared']),
        explainable=original.combined(ctx, keep('shared', shared), {k: keep(k, v) for k, v in corrections.items()}, tables))
    checks = {}
    previous = read(GAP/'strong_continue_ie43.json')
    for name, scores in versions.items():
        old_name = {'shared': 'shared_only', 'explainable': 'regime_explainable'}.get(name, name)
        legacy, _, _ = original.coverage(ctx, scores, ctx['REAL'], regime)
        expected = previous['versions'][old_name]['main']
        checks[name] = all(legacy[y]['hit'] == expected[y]['hit'] for y in YEARS)
        assert checks[name], (name, legacy, expected)
        evaluate('IE43_'+name, ranked_picks(ctx, scores), policy=sample_policy('IE43'),
            order='原冻结共同/行情修正模型推断；原picks与ranks_of，3新名/晚',
            evidence=['studies/trader_replication/reports/gap_review/ie43_work/fit.json'],
            notes='原42段旧口径覆盖已逐年核对；S指标另用48段和首锚点')
    write('ie43_replay_checks.json', checks)


def ie_extra():
    import gc
    from studies.trader_replication import martin_profile_ie42 as original
    checks = {}
    for family in ('IE42', 'IE44', 'IE46'):
        folder = GAP/(family.lower()+'_work')
        fit = read(folder/'fit.json')
        ctx = ie_context(fit['config'])
        if ctx['args'].mainleg_objective:
            original.mainleg_targets(ctx)
        train = [t for t in ctx['REAL'] if t[2] in original.TRAIN_HALVES]
        regime, tables, _ = original.build(ctx, train)
        shared = original.unpack(ctx, fit['model']['shared'])
        corrections = {k: original.unpack(ctx, v) for k, v in fit['model']['corrections'].items()}
        explain = read(folder/'explain.json')
        bad = {(part, r['name']) for part, rr in explain.items() for r in rr if not r['explainable']}
        keep = lambda part, model: {k: w for k, w in model.items() if (part, ctx['NAMES'][k[0]]) not in bad}
        versions = dict(regime=original.combined(ctx, shared, corrections, tables),
            shared=ctx['score'](shared, tables['shared']),
            explainable=original.combined(ctx, keep('shared', shared), {k: keep(k, v) for k, v in corrections.items()}, tables))
        previous = read(GAP/('strong_continue_'+family.lower()+'.json'))
        for name, scores in versions.items():
            legacy, _, _ = original.coverage(ctx, scores, ctx['REAL'], regime)
            old_name = {'shared': 'shared_only', 'explainable': 'regime_explainable'}.get(name, name)
            checks[family+'_'+name] = all(legacy[y]['hit'] == previous['versions'][old_name]['main'][y]['hit'] for y in YEARS)
            assert checks[family+'_'+name], (family, name)
            policy = sample_policy(family)
            if family == 'IE44':
                policy['years']['2026'] = '样本内'
                policy['warning'] = 'PREREG明确根据IE42/IE43的2026锯齿问题设计本规则；2026参与规则设计，无完整留出'
            evaluate(family+'_'+name, ranked_picks(ctx, scores), policy=policy,
                order='原冻结模型及原概率表推断，3新名/晚；相同分数沿原rank稳定次序',
                evidence=[str((folder/'fit.json').relative_to(ROOT))],
                notes='额外恢复的历史画像版本，原口径逐年命中核对一致；不调用fit')
        del ctx, versions, regime, tables, shared, corrections, scores
        gc.collect()
    path = HOME/'reports/e21_work/master/picks.json'
    evaluate('E21_master_list', read(path),
        policy=dict(years={y: '样本内' for y in YEARS}, sources=['studies/martin_luk/e21_research.py'],
                    warning='点名直接来自登记master，沿用同段择优资格；无留出'),
        order='保存的master long close signal原顺序，已知日点名、次日生效', evidence=[str(path.relative_to(ROOT))],
        notes='E21给master追加观察/执行前的原点名，单列以核对名单层；不评测其账户')
    write('ie_extra_replay_checks.json', checks)


def book_picks(book, days, codes):
    return {str(day): list(dict.fromkeys(str(codes[e[1]]) for e in sorted(row, key=lambda e: e[0]) if e[2] > 0))
            for day, row in zip(days, book)}


def native():
    from studies.martin_luk import m1_research as M, m2_research as M2
    from unittest.mock import patch
    directory = HOME/'reports/m1_work/validation_prepared'
    A = M.load_arrays(directory)
    raw = M.load_book(directory, 'master_filtered')
    evaluate('M1B', book_picks(M.master_adapter(A, raw), A['days'], A['codes']),
        policy=sample_policy('M1'), order='原master_adapter的成交额次序，取消原前4截断，S层另行预算',
        evidence=[str((directory/'master_filtered.json').relative_to(ROOT)), 'studies/martin_luk/m1_research.py'])
    def forbidden(*args, **kwargs):
        raise AssertionError('S0 must never run account simulation')
    with patch.object(M.Y, 'simulate', forbidden):
        book, _, _ = M2.build(A, directory, M2.CANDIDATES['M2A'])
    picks = book_picks(book, A['days'], A['codes'])
    for family, name in (('M2', 'M2A'), ('M3', 'M3B')):
        evaluate(name, picks, policy=sample_policy(family),
            order='原M2A报价队列顺序；QQQ低分许可过滤后保留成交额次序，非G1重排',
            evidence=['studies/martin_luk/m2_research.py', 'studies/martin_luk/m3_research.py'],
            notes='M3B只改后续持有，选股点名与M2A相同；这里只恢复信号，不运行任何账户')


def ie26():
    from studies.trader_replication import martin_continue_ie23 as original
    d = original.Data(matrix=False)
    cal = read(GAP/'ie5_work/prepared.json')['days']
    di = {day: t for t, day in enumerate(cal)}
    for method in ('E', 'A'):
        ranks = np.empty(d.n, np.int32)
        evidence = []
        for half in ('2024H1', '2024H2', '2025H1', '2025H2', '2026H1', '2026H2'):
            path = GAP/f'ie26_work/ranks_real_{half}_{method}.npy'
            r = array(path)
            assert len(r) == d.n
            evidence.append(str(path.relative_to(ROOT)))
            for day, sl in d.slices.items():
                if day[:4]+('H1' if day[5:7] <= '06' else 'H2') == half:
                    ranks[sl] = r[sl]
        recent, picks = [], {}
        for day, sl in d.slices.items():
            held = set().union(*recent[-10:]) if recent else set()
            order = np.argsort(ranks[sl], kind='stable')
            names = [d.codes[sl.start+k] for k in order if d.codes[sl.start+k] not in held][:3]
            picks[day] = names
            recent.append(set(names))
        policy = dict(years={y: '样本内' for y in YEARS},
            sources=['studies/martin_luk/notes/PREREG_IE26_CN.md'],
            warning='六半年外折的连续拼接名单；每个年份均进入其他折拟合及全段消融，无整年未用留出；跨折窗口可泄漏，不能冒称正式外折成绩')
        evaluate('IE26_'+method+'_stitched', picks, policy=policy,
            order='原ranks_real逐信号半年拼接，原稳定rank次序、3新名、10池夜冷却', evidence=evidence,
            notes='只量可还原的一条连续名单；正式按入场半年的六套持有状态不能拼成同一条信号流。无整年留出')


def ie30():
    ctx = ie_context(dict(cooldown=10, max_attrs=7, holdout='2026H1,2026H2'))
    missing = []
    for family, tag in [('IE30', 'ho2026')]+[('IE33', 'ie33_c'+str(i)) for i in range(1, 6)]:
        path = GAP/f'strong_continue_ie30_{tag}.json'
        frozen = read(path)
        if tag == 'ie33_c3' or len(frozen['model']) != 1:
            missing.append(dict(system=family+'_'+tag, status='不可复算',
                reason='未保存装袋各内折模型/排名' if tag == 'ie33_c3' else '未保存混合画像的类别成员、先验和分组概率表',
                evidence=str(path.relative_to(ROOT)),
                why_not_rerun='原完整脚本会重做标签拟合和候选择优；没有仅推断所需的冻结状态，S0不重拟合或臆造缺失状态'))
            continue
        ctx['LEARN'] = (-2, -1, 0, 1, 2) if tag == 'ie33_c5' else (0, 1, 2)
        train = [t for t in ctx['REAL'] if t[2][:4] in ('2024', '2025')]
        model = {(ctx['NAMES'].index(r['name']), r['bins']): r['weight'] for r in frozen['model'][0]}
        scores = ctx['score'](model, ctx['tables_for'](train))
        ranks = ctx['ranks_of'](scores)
        test = [t for t in ctx['REAL'] if t[2][:4] == '2026']
        legacy = ctx['evaluate'](ranks, test)[0]
        assert legacy == frozen['test_hit'], (tag, legacy, frozen['test_hit'])
        policy = dict(years={y: '样本内' for y in YEARS},
            sources=[str((HOME/f'notes/PREREG_{family}_CN.md').relative_to(ROOT)),
                     'studies/trader_replication/martin_profile_ie29.py'],
            warning='2026仅目标标签留出；原脚本train_edges=False，分档边界和池分布使用全期特征，S口径无完整留出年份')
        evaluate(family+'_'+tag, ranked_picks(ctx, scores), policy=policy,
            order='原冻结单画像系数与原概率表算术，仅重算分数及3新名/晚点名；旧2026命中逐值核对',
            evidence=[str(path.relative_to(ROOT))], notes='原训练模型不改；原报告的标签留出标记不能掩盖全期分档输入')
    write('unrecoverable_ie33.json', missing)


def ie33_mix():
    """Recover deterministic legacy type assignment, keeping both saved profiles fixed."""
    import ast
    ctx = ie_context(dict(cooldown=10, max_attrs=7, holdout='2026H1,2026H2', mix=2,
        drop='listed_days,pool_run_nights,pool_nights_20,theme_peers_pool,theme_rank_rs21'))
    path = ROOT/'studies/trader_replication/martin_profile_ie29.py'
    tree = ast.parse(path.read_text())
    function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'fit_scorer')
    nodes, collecting = [], False
    for node in function.body:
        target = node.targets[0].id if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name) else None
        if target == 'prim':
            collecting = True
        if collecting:
            nodes.append(node)
        if target == 'tabs':
            break
    assert nodes and target == 'tabs'
    train = [t for t in ctx['REAL'] if t[2][:4] in ('2024', '2025')]
    ctx['train'] = train
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), 'exec'), ctx)
    frozen_path = GAP/'strong_continue_ie30_ie33_c4.json'
    frozen = read(frozen_path)
    models = [{(ctx['NAMES'].index(r['name']), r['bins']): r['weight'] for r in rr} for rr in frozen['model']]
    assert len(models) == ctx['K']
    components = np.stack([ctx['prior'][k]+ctx['score'](m, ctx['tabs'][k]) for k, m in enumerate(models)])
    mx = components.max(0)
    scores = mx+np.log(np.exp(components-mx).sum(0))
    ranks = ctx['ranks_of'](scores)
    test = [t for t in ctx['REAL'] if t[2][:4] == '2026']
    assert ctx['evaluate'](ranks, train)[0] == frozen['train_fit'][0]
    assert ctx['evaluate'](ranks, test)[0] == frozen['test_hit']
    policy = dict(years={y: '样本内' for y in YEARS},
        sources=['studies/martin_luk/notes/PREREG_IE33_CN.md'],
        warning='原train_edges=False的全期分档与池分布使2026不是完整留出')
    evaluate('IE33_ie33_c4', ranked_picks(ctx, scores), policy=policy,
        order='原确定性类别分组代码与冻结双画像；原log-sum-exp合分、3新名及10夜冷却',
        evidence=[str(frozen_path.relative_to(ROOT)), str(path.relative_to(ROOT))],
        notes='仅重放原类型划分和概率表构造，未调用fit或拟合/重选任何指标、权重；原训练与2026命中均核对')
    write('ie33_mix_replay.json', dict(ok=True, fixed_models=True, fit_called=False,
        cluster_sizes=[len(p) for p in ctx['parts']],
        original_train_hits=frozen['train_fit'][0], original_test_hits=frozen['test_hit']))
    old = read(OUT/'unrecoverable_ie33.json')
    write('unrecoverable_ie33.json', [r for r in old if r['system'] != 'IE33_ie33_c4'])


def ie33_bag():
    """Replay the four original historical selection folds; no S target enters fitting."""
    path = GAP/'strong_continue_ie30_ie33_c3.json'
    frozen = read(path)
    write('protocol_clarification.json', dict(
        original_scope='protocol.json said no fitting',
        task_authority='PLAN_S0_CN explicitly permits replaying original selection code when nightly artifacts are missing',
        correction='recover only the four missing historical IE33-C3 inner-fold states using the original frozen objective and defaults',
        forbidden='no S0 objective, candidate, threshold, weight menu, validation selection or upstream output changes',
        resources=resources()))
    ctx = ie_context(dict(cooldown=10, max_attrs=7, holdout='2026H1,2026H2', inner_cv=True, bag=True,
        drop='listed_days,pool_run_nights,pool_nights_20,theme_peers_pool,theme_rank_rs21'))
    train = [t for t in ctx['REAL'] if t[2][:4] in ('2024', '2025')]
    rank_sum, restored = np.zeros(ctx['N'], np.float32), {}
    for half in sorted({t[2] for t in train}):
        source_targets = [t for t in train if t[2] != half]
        held_targets = [t for t in train if t[2] == half]
        model, tables, fitted = ctx['fit'](source_targets)
        ranks = ctx['ranks_of'](ctx['score'](model, tables))
        observed = int(ctx['evaluate'](ranks, held_targets)[0])
        assert observed == frozen['inner_cv']['by_half'][half], (half, observed)
        rank_sum += ranks
        restored[half] = dict(model=[dict(name=str(ctx['NAMES'][k]), bins=int(q), weight=float(w))
                                    for (k, q), w in model.items()], old_validation_hits=observed,
                             original_fit=[float(v) for v in fitted])
        write('ie33_bag_folds.json', restored)
        print('IE33 C3 restored original fold', half, 'old hits', observed, resources(), flush=True)
    full = {(ctx['NAMES'].index(r['name']), r['bins']): r['weight'] for r in frozen['model'][0]}
    rank_sum += ctx['ranks_of'](ctx['score'](full, ctx['tables_for'](train)))
    scores = -rank_sum/5
    ranks = ctx['ranks_of'](scores)
    test = [t for t in ctx['REAL'] if t[2][:4] == '2026']
    assert ctx['evaluate'](ranks, train)[0] == frozen['train_fit'][0]
    assert ctx['evaluate'](ranks, test)[0] == frozen['test_hit']
    evaluate('IE33_ie33_c3', ranked_picks(ctx, scores),
        policy=dict(years={y: '样本内' for y in YEARS},
            sources=['studies/martin_luk/notes/PREREG_IE33_CN.md'],
            warning='原全期分档与池分布使用2026特征，无完整年份留出'),
        order='原4内折与保存的全段模型共5套排名等权装袋，再沿原3新名/10夜冷却',
        evidence=[str(path.relative_to(ROOT)), 'studies/trader_replication/reports/gap_review/ie30_logs/run33.sh'],
        notes='按原代码重放缺失的4内折选择，逐折对回旧命中；没有引入S目标或新参数，不写旧报告/模型')
    write('ie33_bag_recovery.json', dict(ok=True, original_fold_selections_replayed=4,
        original_inner_hits=frozen['inner_cv']['by_half'], original_train_hits=frozen['train_fit'][0],
        original_test_hits=frozen['test_hit'], full_model_refitted=False, S_objective_used=False))
    write('unrecoverable_ie33.json', [r for r in read(OUT/'unrecoverable_ie33.json')
                                    if r['system'] != 'IE33_ie33_c3'])


def h_signals(family):
    from studies.martin_luk import h1_research as H1, h2_research as H2, h1_policy, h2_policy
    from studies.trader_data import supplemental as SP
    from unittest.mock import patch
    module, policy_module = (H1, h1_policy) if family == 'H1' else (H2, h2_policy)
    directory = HOME/'reports/m1_work/validation_prepared'
    A = module.arrays(directory)
    p = {key: array(HOME/f'reports/u1_work/panel/{key}.npy') for key in
         ('close', 'high', 'low', 'raw_close', 'turnover', 'volume')}
    if family == 'H1':
        f = policy_module.features(A, p)
    else:
        qqq, _ = SP.benchmark('US.QQQ', A['days'], 'frozen')
        f = policy_module.features(A, p, qqq)
    # Confirm the regenerated signal features on all saved training sessions.
    checks = {}
    folder = HOME/f'reports/{family.lower()}_work/features/train'
    for path in folder.glob('*.npy'):
        old = array(path)
        checks[path.stem] = bool(np.array_equal(np.asarray(f[path.stem])[:len(old)], old, equal_nan=True))
    old_groups = read(folder/'groups.json')
    checks['groups'] = f['groups'][:len(old_groups)] == old_groups
    assert all(checks.values()), checks
    write(family.lower()+'_feature_replay.json', dict(checks=checks, resources=resources(), no_accounts=True))
    def forbidden(*args, **kwargs):
        raise AssertionError('S0 must never run account simulation')
    for name, spec in module.CANDIDATES.items():
        with patch.object(H1.Y, 'simulate', forbidden):
            book = policy_module.build(A, directory, f, spec)[0]
        evaluate(name+'_signals', book_picks(book, A['days'], A['codes']), policy=sample_policy(family),
            order='原policy.build报价priority次序（只含多头信号）；不调用simulate、不读持仓/盈亏',
            evidence=[str(Path(policy_module.__file__).relative_to(ROOT)), str(folder.relative_to(ROOT))],
            notes='从原日K特征逻辑固定重放至数据末日，训练特征和题材组逐值核对；2026仅S0信号描述，原账户验证未打开')


def h1():
    h_signals('H1')


def h2():
    h_signals('H2')


def e12():
    from studies.martin_luk import e12_research as original, m1_research as M
    directory = HOME/'reports/m1_work/validation_prepared'
    A = M.load_arrays(directory)
    selection = read(HOME/'reports/d1_work/ie_selection.json')
    assert selection['days'] == list(A['days']) and selection['codes'] == list(A['codes'])
    scope_j = array(HOME/'reports/d1_work/ie_scope_j.npy')
    raw = array(HOME/'reports/d1_work/ie_gate_raw.npy')
    R = dict(night_indices=[], scopes=[], raw=[], row_t=[], row_j=[], scores=[])
    for row in selection['nights']:
        t = row['index']
        sl = slice(row['scope_start'], row['scope_end'])
        R['night_indices'].append(t)
        R['scopes'].append(scope_j[sl])
        R['raw'].append(raw[sl])
        for j in row['kept']:
            R['row_t'].append(t)
            R['row_j'].append(j)
            R['scores'].append(row['scores'][str(A['codes'][j])])
    for key in ('row_t', 'row_j', 'scores'):
        R[key] = np.asarray(R[key])
    masks, scope, scores = original.pools(A, R)
    checks = {}
    for name in original.CANDIDATES:
        _, sig, book = original.candidate(A, name, masks, scope, scores)
        picks = book_picks(book, A['days'], A['codes'])
        path = HOME/f'reports/e12_work/{name}_2024_trades.json'
        historical = read(path)
        # Every persisted trade must have been an original emitted signal.
        checks[name] = all(t['code'] in picks.get(t['entry'], ()) for t in historical)
        assert checks[name], name
        evaluate('E12_'+name, picks, policy=sample_policy('E12'),
            order='原candidate/book：形态优先，再原画像/成交额/共振键，原生前5；S冷却后不补第6名',
            evidence=['studies/martin_luk/e12_research.py', 'studies/martin_luk/reports/d1_work/ie_selection.json'],
            notes='只重放日K选股；所有历史成交只用于证明有对应原信号，不重算收益或执行')
        del sig, book
    write('e12_replay_checks.json', checks)


def f3():
    from studies.martin_luk import f3_research as original, m1_research as M
    from unittest.mock import patch
    directory = HOME/'reports/m1_work/validation_prepared'
    A = M.load_arrays(directory)
    original.OUT = OUT/'replay/f3'
    f = original.feature_inputs(A, 'full')
    checks = {}
    for path in (HOME/'reports/f3_work/features/train').glob('*.npy'):
        old = array(path)
        checks[path.stem] = bool(np.array_equal(f[path.stem][:len(old)], old, equal_nan=True))
    assert all(checks.values()), checks
    write('f3_feature_replay.json', dict(checks=checks, resources=resources()))
    with (original.OUT/'features/full/nightly.jsonl').open() as stream:
        active = {row['day']: row['codes'] for row in map(json.loads, stream)}
    evaluate('F3_active_list', active, policy=sample_policy('F3'),
        order='原nightly.jsonl的codes记录顺序；原长期名单没有评分排序，采用实际名单输出顺序',
        evidence=['studies/martin_luk/f3_research.py', 'studies/martin_luk/reports/f3_work/features/train/nightly.jsonl'],
        notes='长期活动名单层单列，不能与下面的fire或合并报价混称')
    new = original.new_book(A, f)
    evaluate('F3_fire', book_picks(new, A['days'], A['codes']), policy=sample_policy('F3'),
        order='原new_book的当晚成交额降序及代码平手次序', evidence=['studies/martin_luk/f3_research.py'],
        notes='仅F3新增点名；与长期名单及合并后的V1/V2/V3分列')
    def forbidden(*args, **kwargs):
        raise AssertionError('S0 must never run account simulation')
    for name, spec in original.CANDIDATES.items():
        with patch.object(M.Y, 'simulate', forbidden):
            book = original.build(A, directory, spec)[0]
        evaluate('F3_'+name, book_picks(book, A['days'], A['codes']), policy=sample_policy('F3'),
            order='原F3.build合并信号priority：V1原队列，V2同伴，V3原类别/止损宽度/同伴队列',
            evidence=['studies/martin_luk/f3_research.py', 'studies/martin_luk/reports/f3_work/features/train'],
            notes='固定重放原选股状态；全部训练特征逐值对齐；2026只作S0信号描述，原账户验证未打开')


def f4():
    from studies.martin_luk import f4_research as original, m1_research as M, m2_research as M2
    directory = HOME/'reports/m1_work/validation_prepared'
    original.OUT = OUT/'replay/f4'
    original.feature_inputs('full', '2026-10-16')
    f = original.load_features('full')
    checks = {}
    for path in (HOME/'reports/f4_work/features/train').glob('*.npy'):
        old = array(path)
        checks[path.stem] = bool(np.array_equal(f[path.stem][:len(old)], old, equal_nan=True))
    assert all(checks.values()), checks
    write('f4_feature_replay.json', dict(checks=checks, resources=resources()))
    A = M.load_arrays(directory)
    base = M2.build(A, directory, M2.CANDIDATES['M2A'])[0]
    for name in original.SPECS:
        new = original.new_book(A, name, 'full')
        for suffix, book in (('', new), ('_union', M.merge_books(base, new))):
            evaluate('F4_'+name+suffix, book_picks(book, A['days'], A['codes']), policy=sample_policy('F4'),
                order='原F4.new_book/F3.new_book的当晚成交额降序及代码平手；union沿M2A在前、原合并优先键',
                evidence=['studies/martin_luk/f4_research.py', 'studies/martin_luk/reports/f4_work/features/train'],
                notes='单独新点名与原M2A合并版本分列；全部训练状态逐值对齐；只恢复信号，不运行账户')


def e20():
    from studies.martin_luk import e20_research as original, m1_research as M
    directory = HOME/'reports/m1_work/validation_prepared'
    A = M.load_arrays(directory)
    selection = read(HOME/'reports/d1_work/ie_selection.json')
    scope_j = array(HOME/'reports/d1_work/ie_scope_j.npy')
    R = dict(picks=selection['picks'], night_indices=[r['index'] for r in selection['nights']],
             scopes=[scope_j[r['scope_start']:r['scope_end']] for r in selection['nights']],
             regime=np.full(len(A['days']), -1))
    for row in read(directory/'ie_nights.json'):
        if row['available']:
            R['regime'][row['t']] = 0
    events = original.event_rows(A, R, end='2026-10-16')
    old_events = read(HOME/'reports/e20_work/events.json')
    assert all(events[day] == row for day, row in old_events.items())
    checks = {'training_events': True}
    for name, (kinds, _, priority) in original.SPECS.items():
        picks, _ = original.nominations(A, R, events, kinds, 3, priority)
        old = read(HOME/f'reports/e20_work/{name}_nominations.json')['picks']
        checks[name] = all(picks[day] == cs for day, cs in old.items())
        assert checks[name], name
        evaluate('E20_'+name, picks, policy=sample_policy('E20'),
            order='原IE47点名顺序在前，原nominations的21日涨幅/来源次序在后；额外最多3',
            evidence=['studies/martin_luk/e20_research.py', 'studies/martin_luk/reports/e20_work/events.json'],
            notes='原训练事件与点名逐晚完全对齐；S0仅固定延长信号推断至末日，不打开旧实验的2026账户')
    write('e20_replay_checks.json', checks)


def aliases():
    from studies.martin_luk import e16_research as E16, e19_research as E19
    groups = dict(E16=[n for n in E16.ARMS if n != 'N0'], E17=list(E16.E17), E18=list(E16.E18),
                  E19=list(E19.SPECS), E21=['BASE', 'S1'])
    for family, variants in groups.items():
        record = read(OUT/f'systems/{family}_IE47_list.json')
        record['table_aliases'] = [family+'_'+n+'_list' for n in variants]
        write('systems/'+record['system']+'.json', record)
    for path in (OUT/'systems').glob('IE44_*.json'):
        record = read(path)
        record['policy']['years']['2026'] = '样本内'
        record['policy']['warning'] = 'PREREG明确根据IE42/IE43的2026锯齿问题设计本规则；2026参与规则设计，无完整留出'
        write('systems/'+record['system']+'.json', record)
    write('resource_incidents.json', dict(
        brief_overlap='E12 finishing C5 and initial H1 overlapped about ten seconds; H1 was interrupted before any signal output',
        prevention='fcntl nonblocking exclusive run.lock acquired before every later stage',
        limits='each Python process remained under CPUQuota=60% and MemoryMax=900M; no OOM',
        disk='initial replay inspection found about 1.8 GiB free; no dataset copied or downloaded'))


def tests(suite):
    import unittest
    paths = dict(custody=ROOT/'custody/tests', trader_replication=ROOT/'studies/trader_replication/tests',
                 martin_luk=HOME/'tests')
    result = unittest.TextTestRunner(verbosity=1).run(unittest.defaultTestLoader.discover(str(paths[suite])))
    write('tests_'+suite+'.json', dict(count=result.testsRun, failures=len(result.failures),
        errors=len(result.errors), skipped=len(result.skipped), passed=result.wasSuccessful(), resources=resources()))
    if not result.wasSuccessful():
        raise SystemExit(1)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('stage', choices=('freeze', 'saved', 'profiles', 'ie_standard', 'ie_extra', 'native', 'ie26', 'ie30',
        'h1', 'h2', 'e12', 'f3', 'f4', 'e20', 'ie33_mix', 'ie33_bag', 'aliases', 'test_custody', 'test_trader_replication', 'test_martin_luk'))
    args = parser.parse_args()
    offline(test_mode=args.stage.startswith('test_'))
    OUT.mkdir(parents=True, exist_ok=True)
    run_lock = (OUT/'run.lock').open('a')
    fcntl.flock(run_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    if (OUT/'sources.json').exists():
        SOURCES.update(json.loads((OUT/'sources.json').read_text()))
    write('runs/'+args.stage+'_started.json', dict(memory_before=Path('/proc/meminfo').read_text(), resources=resources()))
    try:
        if args.stage.startswith('test_'):
            tests(args.stage.removeprefix('test_'))
        else:
            globals()[args.stage]()
    finally:
        write('sources.json', SOURCES)
