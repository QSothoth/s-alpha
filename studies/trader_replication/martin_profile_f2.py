"""F2 offline adaptive profiles. Reuse F1 fitting without modifying its files.

Stages: prepare, fit, crossyear, evaluate, report, verify. All writes are isolated
in f2_work, except the requested Chinese report. Market features never read labels.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import csv
import gc
import hashlib
import json
import os
from pathlib import Path
import re
import resource
import sys
import time

import numpy as np

from studies.trader_replication import martin_profile_f1 as F

ROOT, HOME, SI = F.ROOT, F.HOME, F.SI
F1_WORK = F.WORK
WORK = HOME / 'reports/f2_work'
REPORT = HOME / 'reports/F2_CN.md'
PREREG = HOME / 'notes/PREREG_F2_CN.md'
BASE = tuple('pctl_'+n if n != 'long_strength_memory' else n for n in F.FEATURES)
RS = tuple(f'pctl_rs{n}_vs_qqq_pct' for n in (21, 63, 126))
PEERS = ('peer_leaders20_count', 'peer_perf21_median_pctl', 'peer_strength_pctl')
MONEY = tuple(f'money_rs{n}_product' for n in (21, 63, 126)) + ('attention20_120_pctl',)
PULLBACK = 'remembered_liquid_pullback_pctl'
FEATURES = BASE + RS + PEERS + MONEY + (PULLBACK,)
CANDIDATES = (
    dict(id='G1', features=BASE+RS),
    dict(id='G2', features=BASE+RS+PEERS),
    dict(id='G3', features=BASE+RS+PEERS+MONEY),
    dict(id='G4', features=BASE+RS+PEERS+MONEY, agreement=True),
    dict(id='G5', features=FEATURES),
)


@contextmanager
def fitter(names, start=F.START, end=F.TRAIN_END):
    """F1's parameter-free fitting functions, with process-local feature names."""
    before = F.FEATURES, F.START, F.TRAIN_END, F.WORK
    F.FEATURES, F.START, F.TRAIN_END, F.WORK = tuple(names), start, end, WORK
    try:
        yield
    finally:
        F.FEATURES, F.START, F.TRAIN_END, F.WORK = before


def offline():
    sys.dont_write_bytecode = True

    def audit(event, args):
        if event in ('socket.connect', 'socket.bind', 'socket.getaddrinfo', 'subprocess.Popen', 'os.system'):
            raise PermissionError('F2 is offline and single-process')
        if event == 'open' and not isinstance(args[0], int):
            if args[2] & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND):
                path = Path(os.fsdecode(args[0])).resolve()
                if not path.is_relative_to(WORK.resolve()) and path != REPORT.resolve():
                    raise PermissionError('F2 may write only its work directory and report')
    sys.addaudithook(audit)


def sources():
    paths = [Path(__file__), Path(F.__file__), Path(SI.__file__), PREREG,
             HOME/'notes/PLAN_F2_CN.md', HOME/'notes/RULES_CN.md', F.LEGS,
             WORK/'prediagnosis.json']
    paths += [F1_WORK/n for n in ('cache.json', 'rows.npz', 'features.npy', 'routes.npy',
                                 'train_labels.json', 'full_labels.json', 'selection.json',
                                 'fit_F1a.json', 'holdout.json')]
    return {str(p.relative_to(ROOT)): F.sha(p) for p in paths}


def protected():
    result = F.protected()
    result[str(Path(F.__file__).relative_to(ROOT))] = F.sha(F.__file__)
    return result


def rank_against(values, pool):
    finite = np.sort(np.asarray(pool)[np.isfinite(pool)])
    out = np.full(len(values), np.nan)
    ok = np.isfinite(values)
    if len(finite) == 1:
        out[ok] = np.where(values[ok] < finite[0], 0, np.where(values[ok] > finite[0], 100, 50))
    elif len(finite):
        left = np.searchsorted(finite, values[ok], side='left')
        right = np.searchsorted(finite, values[ok], side='right')
        out[ok] = np.clip(50*(left+right-1)/(len(finite)-1), 0, 100)
    return out


def peer_features(closes, monthly, monthly_rank, block=128):
    """Only tonight's pool and its trailing 61 closes; at most block² correlations."""
    if not 1 <= block <= 128:
        raise ValueError('correlation block must be between 1 and 128')
    n = len(monthly)
    out = np.full((3, n), np.nan)
    out[0] = 0
    if closes.shape != (61, n):
        return out
    returns = SI.divide(closes[1:], closes[:-1])-1
    complete = np.all(np.isfinite(returns), axis=0)
    normalized = np.zeros((n, 60))
    valid = np.flatnonzero(complete)
    centered = returns[:, valid].T - returns[:, valid].mean(axis=0)[:, None]
    norm = np.linalg.norm(centered, axis=1)
    valid, centered, norm = valid[norm > 1e-12], centered[norm > 1e-12], norm[norm > 1e-12]
    normalized[valid] = centered/norm[:, None]
    usable = np.zeros(n, bool)
    usable[valid] = True
    for start in range(0, n, block):
        stop = min(start+block, n)
        # A single row block's peer membership is discarded before the next block.
        members = np.zeros((stop-start, n), bool)
        for other in range(0, n, block):
            end = min(other+block, n)
            corr = normalized[start:stop] @ normalized[other:end].T
            members[:, other:end] = ((corr >= .6) & usable[start:stop, None]
                                    & usable[None, other:end])
        members[np.arange(stop-start), np.arange(start, stop)] = False
        out[0, start:stop] = np.sum(members & (monthly_rank >= 80)[None, :], axis=1)
        for local, mask in enumerate(members):
            i = start+local
            values = monthly[mask & np.isfinite(monthly)]
            if not len(values):
                continue
            out[1, i] = rank_against(np.array([np.median(values)]), monthly)[0]
            cohort = np.r_[values, monthly[i]]
            out[2, i] = SI.midrank(cohort)[-1]
    return out


def remembered_pullback(memory, dollar_rank, ext9, ext21):
    near = np.minimum(abs(ext9), abs(ext21))
    return SI.midrank(memory * (dollar_rank/100)/(1+near))


def original_cache():
    meta = F.read(F1_WORK/'cache.json')
    for name, digest in meta['cache_hashes'].items():
        if F.sha(F1_WORK/name) != digest:
            raise ValueError('F1 cache changed: '+name)
    with np.load(F1_WORK/'rows.npz') as archive:
        arrays = {k: archive[k] for k in archive.files}
    return meta, arrays, np.load(F1_WORK/'features.npy', mmap_mode='r')


def prepare():
    if (WORK/'cache.json').exists():
        raise FileExistsError('prepared F2 cache already exists')
    from studies import trader_data as TD
    from studies.trader_data import panel as TP, supplemental as SP
    before = sources()
    memory_before = Path('/proc/meminfo').read_text()
    meta, a, old = original_cache()
    panel = TP.build(TD.dataset('us', 'frozen'), write_cache=False)
    days, codes = meta['days'], meta['codes']
    assert list(map(str, panel['days'])) == days and list(map(str, panel['codes'])) == codes
    assert panel['digest'] == meta['dataset_digest']
    qqq, benchmark = SP.benchmark('US.QQQ', days, 'frozen')
    n = len(a['row_day'])
    x = np.lib.format.open_memmap(WORK/'features.npy', mode='w+', dtype='float32',
                                shape=(len(FEATURES), n))
    x[:] = np.nan
    attention = np.full(n, np.nan)
    order = np.argsort(a['row_code'], kind='stable')
    offsets = np.r_[0, np.cumsum(np.bincount(a['row_code'], minlength=len(codes)))]
    for j in range(len(codes)):
        rows = order[offsets[j]:offsets[j+1]]
        amount = panel['turnover'][:, j].astype(float)
        attention[rows] = SI.divide(SI.roll(amount, 20), SI.roll(amount, 120))[a['row_day'][rows]]
    qreturns = {p: 100*(SI.divide(qqq, SI.lag(qqq, p))-1) for p in (21, 63, 126)}
    fi = {name: k for k, name in enumerate(F.FEATURES)}
    output = {name: k for k, name in enumerate(FEATURES)}
    distinct, offsets, counts = np.unique(a['row_day'], return_index=True, return_counts=True)
    maximum = 0
    for t, start, count in zip(distinct, offsets, counts):
        rr = np.arange(start, start+count)
        rr = rr[a['new'][rr]]
        if not len(rr):
            continue
        ix = a['row_code'][rr]
        maximum = max(maximum, len(rr))
        for k, name in enumerate(F.FEATURES):
            values = old[k, rr].astype(float)
            x[output[BASE[k]], rr] = values if name == 'long_strength_memory' else SI.midrank(values)
        for p, name in zip((21, 63, 126), RS):
            x[output[name], rr] = SI.midrank(old[fi[f'perf{p}_pct'], rr].astype(float)-qreturns[p][t])
        monthly = old[fi['perf21_pct'], rr].astype(float)
        peers = peer_features(panel['close'][max(0, t-60):t+1, ix].astype(float), monthly,
                              x[output['pctl_perf21_pct'], rr])
        for k, name in enumerate(PEERS):
            x[output[name], rr] = peers[k]
        dollar = x[output['pctl_dollar_vol20_percentile'], rr]
        for name, strength in zip(MONEY[:3], RS):
            x[output[name], rr] = (dollar/100)*(x[output[strength], rr]/100)
        x[output[MONEY[-1]], rr] = SI.midrank(attention[rr])
        x[output[PULLBACK], rr] = remembered_pullback(old[fi['long_strength_memory'], rr], dollar,
            old[fi['ext_ema9_adr'], rr], old[fi['ext_ema21_adr'], rr])
        if t % 80 == 0:
            F.log(f'F2 date {days[int(t)]}: {len(rr)} stocks; correlation blocks <=128x128')
    x.flush()
    # Single-year labels cannot use the following year's prices, even in 2024.
    routes = np.load(F1_WORK/'routes.npy', mmap_mode='r')
    annual = {}
    labels = F.read(F1_WORK/'train_labels.json')
    for year in ('2024', '2025'):
        last = int(np.searchsorted(days, year+'-12-31', side='right'))-1
        annual[year] = []
        for label in labels:
            if label['year'] != year:
                continue
            j = codes.index(label['leg']['code'])
            price = {key: panel[name][:, j].astype(float) for key, name in
                     (('o', 'open'), ('h', 'high'), ('c', 'close'))}
            leg = F.clipped_leg(label['leg'], price, last)
            signal, triggers = F.label_windows(leg, price['o'], price['c'], routes[:, j], last)
            rr = np.flatnonzero(a['row_code'] == j)
            rowmap = dict(zip(map(int, a['row_day'][rr]), map(int, rr)))
            annual[year].append(dict(leg=leg, year=year, signal_nights=signal,
                signal_rows=[rowmap.get(t, -1) for t in signal],
                triggers=[dict(r, row=rowmap.get(r['night'], -1)) for r in triggers]))
    F.write(WORK/'annual_labels.json', annual)
    assert sources() == before, 'inputs changed during feature preparation'
    F.write(WORK/'cache.json', dict(days=days, codes=codes, first_night=meta['first_night'],
        train_last=meta['train_last'], features=FEATURES, dataset_digest=panel['digest'],
        sources=before, protected=protected(), benchmark_sources=benchmark,
        cache_hashes={name: F.sha(WORK/name) for name in ('features.npy', 'annual_labels.json')},
        peak_rss_mib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024,
        duration_seconds=time.monotonic()-F.T0, before_memory=memory_before,
        python=sys.executable, pool_maximum=maximum, correlation_block=128,
        industry_available=False, rows=n))
    F.log(f'F2 features frozen: {len(FEATURES)} features, {n} rows, maximum pool {maximum}')


def load_cache():
    meta = F.read(WORK/'cache.json')
    if meta['sources'] != sources():
        raise ValueError('F2 source or input drift')
    for name, digest in meta['cache_hashes'].items():
        if F.sha(WORK/name) != digest:
            raise ValueError('F2 cache changed: '+name)
    with np.load(F1_WORK/'rows.npz') as archive:
        arrays = {k: archive[k] for k in archive.files}
    return meta, arrays, np.load(WORK/'features.npy', mmap_mode='r')


def sample_for(model, meta, arrays, x, labels, end=None):
    source_names = F.FEATURES if model.get('baseline') else FEATURES
    indices = [source_names.index(n) for n in model['features']]
    return F.Sample(meta, arrays, x[indices], model['spec'], labels, end=end)


def agreement(sample, names, periods):
    masks = [np.array([lo <= sample.meta['days'][t] <= hi for t in sample.day]) for lo, hi in periods]
    train = masks[0] | masks[1]
    rows = []
    for f, name in enumerate(names):
        edges = F.bin_edges(sample.x[f, train])
        bins = F.bin_indices(sample.x[f], edges)
        profiles = []
        for mask, (lo, hi) in zip(masks, periods):
            groups = [rows for label, rows in zip(sample.labels, sample.leg_rows)
                      if lo[:4] <= label['year'] <= hi[:4]]
            profiles.append(F.preference(bins, len(edges)+2, mask, groups)[0][:-1])
        left, right = profiles
        r = float(np.corrcoef(left, right)[0, 1]) if len(left) > 1 and left.std() > 0 and right.std() > 0 else 0.
        rows.append(dict(name=name, correlation=r, keep=r >= .6, edges=edges,
                         profiles=profiles, periods=periods))
    return rows


def fit_one(candidate, meta, arrays, x, labels, start, end, single_year=False, baseline=False):
    names = tuple(candidate['features'])
    spec = dict(id=candidate['id'], pool='new', paired=not baseline, k=3, cooldown=10)
    model = dict(spec=spec, features=names, baseline=baseline)
    last = int(np.searchsorted(meta['days'], end, side='right'))-1
    sample = sample_for(model, meta, arrays, x, labels, last)
    agree = None
    if candidate.get('agreement'):
        periods = ((start, start[:4]+'-06-30'), (start[:4]+'-07-01', end)) if single_year else (
            ('2024-01-01', '2024-12-31'), ('2025-01-01', '2025-12-31'))
        agree = agreement(sample, names, periods)
        names = tuple(row['name'] for row in agree if row['keep'])
        model['features'] = names
        sample = sample_for(model, meta, arrays, x, labels, last)
    with fitter(names, start, end):
        tables, vectors = F.training_tables(sample)
        parts, scores = {}, np.zeros(len(sample.indices))
        for part, limit in (('shared', 7), ('up', 3), ('pullback', 3)):
            weights, scores = F.fit_part(sample, scores, vectors[part], limit, part)
            parts[part] = [dict(tables[part][f], weight=w) for f, w in sorted(weights.items())]
        model['parts'] = parts
        frozen = F.score_model(model, sample)
        assert np.array_equal(sample.nominate(scores), sample.nominate(frozen)), 'F2 inference drift'
        metrics = {str(k): F.yearly_metrics(sample, frozen, k) for k in (1, 2, 3)}
    years = sorted({r['year'] for r in labels})
    support = all(metrics['3']['by_year'][y]['first_action_opportunities'] >= 52 for y in years)
    return dict(model=model, metrics=metrics, support_52=support, agreement=agree,
        training_start=start, training_end=end, sources=meta['sources'],
        model_sha256=hashlib.sha256(json.dumps(F.clean(model), sort_keys=True).encode()).hexdigest(),
        peak_rss_mib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024)


def score(model, sample):
    with fitter(model['features']):
        return F.score_model(model, sample)


def fit():
    if (WORK/'selection.json').exists():
        raise FileExistsError('F2 selection is already frozen')
    meta, arrays, x = load_cache()
    labels = F.read(F1_WORK/'train_labels.json')
    results = []
    for candidate in CANDIDATES:
        path = WORK/f'fit_{candidate["id"]}.json'
        if path.exists():
            result = F.read(path)
            assert result['sources'] == meta['sources']
        else:
            result = fit_one(candidate, meta, arrays, x, labels, F.START, F.TRAIN_END)
            F.write(path, result)
        results.append(result)
        F.log(f'{candidate["id"]} fixed: {F.objective(result["metrics"]["3"])}')
        gc.collect()

    def ranking(pair):
        i, result = pair
        main = result['metrics']['3']
        missing = sum(max(0, 52-main['by_year'][y]['first_action_opportunities']) for y in ('2024', '2025'))
        return result['support_52'], -missing, *F.objective(main), -i

    ordered = sorted(enumerate(results), key=ranking, reverse=True)
    best, second = [r for _, r in ordered[:2]]
    selected = dict(chosen=best['model']['spec']['id'], second=second['model']['spec']['id'],
        ranked=[r['model']['spec']['id'] for _, r in ordered], passed=best['support_52'],
        objective='(C_trig count, P_opp, E), 52 first actions/year, training only',
        sources=meta['sources'], feature_sha256=meta['cache_hashes']['features.npy'],
        model_hashes={r['model']['spec']['id']: r['model_sha256'] for r in results})
    F.write(WORK/'selection.json', selected)
    exports = []
    for result in (best, second):
        model = result['model']
        indices = [FEATURES.index(n) for n in model['features']]
        with fitter(model['features']):
            exports.append(F.export_picks(model, meta, arrays, x[indices]))
    F.write(WORK/'exports.json', exports)
    ablations = []
    model = best['model']
    sample = sample_for(model, meta, arrays, x, labels, meta['train_last'])
    for part, items in model['parts'].items():
        for i, item in enumerate(items):
            changed = json.loads(json.dumps(F.clean(model)))
            del changed['parts'][part][i]
            metric = F.yearly_metrics(sample, score(changed, sample), 3)
            ablations.append(dict(part=part, removed=item['name'], objective=F.objective(metric),
                                  by_year=metric['by_year']))
    F.write(WORK/'training_ablations.json', ablations)
    F.log(f'F2 frozen: {selected["chosen"]}, runner-up {selected["second"]}; 2026 labels unopened')


def crossyear():
    meta, arrays, x = load_cache()
    selection_hash = F.sha(WORK/'selection.json')
    labels = F.read(WORK/'annual_labels.json')
    original = np.load(F1_WORK/'features.npy', mmap_mode='r')
    out = []
    baseline = dict(id='F1a', features=F.FEATURES)
    for candidate in (*CANDIDATES, baseline):
        for source, target in (('2024', '2025'), ('2025', '2024')):
            path = WORK/f'cross_{candidate["id"]}_{source}_{target}.json'
            if path.exists():
                result = F.read(path)
                assert result['fit']['sources'] == meta['sources']
            else:
                is_baseline = candidate['id'] == 'F1a'
                values = original if is_baseline else x
                fit_result = fit_one(candidate, meta, arrays, values, labels[source],
                    source+'-01-01', source+'-12-31', single_year=True, baseline=is_baseline)
                model = fit_result['model']
                last = int(np.searchsorted(meta['days'], target+'-12-31', side='right'))-1
                sample = sample_for(model, meta, arrays, values, labels[target], last)
                metric = F.yearly_metrics(sample, score(model, sample), 3)
                result = dict(candidate=candidate['id'], source_year=source, target_year=target,
                    fit=fit_result, transfer=metric,
                    agreement_uses_source_halves=candidate.get('agreement', False),
                    selection_sha256=selection_hash, diagnostic_only=True)
                F.write(path, result)
            out.append(dict(candidate=result['candidate'], source_year=source, target_year=target,
                self=F.objective(result['fit']['metrics']['3']),
                transfer=F.objective(result['transfer']),
                transfer_by_year=result['transfer']['by_year'][target],
                agreement_uses_source_halves=result['agreement_uses_source_halves']))
            F.log(f'cross {candidate["id"]} {source}->{target}: {F.objective(result["transfer"])}')
            gc.collect()
    assert F.sha(WORK/'selection.json') == selection_hash
    F.write(WORK/'crossyear.json', dict(results=out, selection_unchanged=True,
                                      diagnostic_only=True, selection_sha256=selection_hash))


def evaluate():
    meta, arrays, x = load_cache()
    selection = F.read(WORK/'selection.json')
    with (WORK/'evaluation_started.json').open('x', encoding='utf-8') as stream:
        json.dump(dict(chosen=selection['chosen'], selection_sha256=F.sha(WORK/'selection.json'),
                       started_utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())), stream)
    labels = [r for r in F.read(F1_WORK/'full_labels.json') if r['year'] == '2026']
    fitted = F.read(WORK/f'fit_{selection["chosen"]}.json')
    model = fitted['model']
    sample = sample_for(model, meta, arrays, x, labels)
    scores = score(model, sample)
    metrics = {str(k): F.yearly_metrics(sample, scores, k) for k in (1, 2, 3)}
    F.write(WORK/'holdout.json', dict(chosen=selection['chosen'], main_k=3, metrics=metrics,
        selection_sha256=F.sha(WORK/'selection.json'), model_sha256=fitted['model_sha256'],
        evaluated_once=True, runner_up_holdout_metrics=False))
    F.log(f'F2 2026 evaluated once: {F.objective(metrics["3"])}')


def diagnose(model, meta, arrays, x, labels, metric, end=None):
    sample = sample_for(model, meta, arrays, x, labels, end)
    scores = score(model, sample)
    picks = sample.nominate(scores)
    chosen = np.zeros(len(sample.indices), bool)
    chosen[picks[picks < len(chosen)]] = True
    order = np.argsort(-np.r_[np.round(scores, 10), -np.inf][sample.pad], axis=1, kind='stable')
    ranked = np.take_along_axis(sample.pad, order, axis=1)
    ranks = np.zeros(len(chosen), np.int32)
    for row in ranked:
        rr = row[row < len(chosen)]
        ranks[rr] = np.arange(1, len(rr)+1)
    nominations = {}
    for row in picks:
        for r in row[row < len(chosen)]:
            nominations.setdefault(int(sample.code[r]), []).append(int(sample.day[r]))
    out = []
    for per, label, sr, tr in zip(metric['per_leg'], labels, sample.signal_rows, sample.leg_rows):
        leg = label['leg']
        named = sr[chosen[sr]]
        actions = [int(arrays['action'][sample.indices[r]]) for r in named]
        actions = [t for t in actions if leg['first']-3 <= t < leg['peak'] and (end is None or t <= end)]
        trace = []
        for r in tr:
            t, code = int(sample.day[r]), int(sample.code[r])
            previous = max((d for d in nominations.get(code, []) if d < t), default=None)
            trace.append(dict(day=meta['days'][t], rank=int(ranks[r]), score=float(scores[r]),
                selected=bool(chosen[r]), previous_nomination=meta['days'][previous] if previous is not None else None,
                cooldown=previous is not None and t-previous <= 10))
        reason = ('早买代理接上，账户待验证' if per['covered'] else
                  '池内没有合格点名夜' if not per['reachable_signal'] else
                  '池内没有五晚早买动作' if not per['reachable_trigger'] else
                  '点名未接上早买动作' if per['nominated'] else '排序或冷却未点到')
        out.append(dict(per, actual_action=bool(actions),
            first_action=meta['days'][min(actions)] if actions else None, rank_trace=trace,
            best_unrestricted_rank=min((r['rank'] for r in trace), default=None), reason=reason,
            first_anchor_share=(leg['top']/per['first']['price']-1)/leg['gain'] if per['first'] else None))
    return out


def table(headers, rows):
    return '\n'.join(['| '+' | '.join(map(str, headers))+' |',
        '| '+' | '.join('---' for _ in headers)+' |',
        *['| '+' | '.join(map(str, row))+' |' for row in rows]])


def pct(value):
    return '—' if value is None else f'{100*value:.1f}%'


def yn(value):
    return '是' if value else '否'


def intervals(item):
    edges = item['edges']
    bounds = [-np.inf, *edges, np.inf]
    return [f'[{a:.4g}, {b:.4g})' for a, b in zip(bounds, bounds[1:])] + ['缺失']


def explanation(name, original):
    if name in original:
        value = original[name].copy()
        if name.startswith('pctl_'):
            value['label'] += '当晚分位'
        return value
    base = name.removeprefix('pctl_')
    if base in original:
        value = original[base].copy()
        value['label'] += '当晚分位'
        return value
    if name in RS:
        return dict(label=f'{name.split("_rs")[1].split("_")[0]}日相对QQQ强度分位', source='②leader扫描；QQQ比较为量化补充，顺序与同窗涨幅重复',
            not_following_crowd='相对强不等于逆人群，需回调位置', retail_counterparty='日K不能识别散户对手',
            small_capital='能小仓快速参与', payoff='须配近处风险位', compounding='单项不能证明复利')
    if name in PEERS:
        return dict(label=dict(zip(PEERS, ('强同伴只数', '同伴月涨幅中位的池内分位', '本票在同伴中的月强度分位')))[name],
            source='②同题材多只一起出现说明资金流入；lS9z@1:30:37–1:33:42、VKNE@2:31:03；相关为近似',
            not_following_crowd='准备期同伴开始走强可提前识别，未必逆人群',
            retail_counterparty='相关不能确认资金流入，更不能确认散户对手',
            small_capital='可在同步启动时少量试单', payoff='共振可能延伸行情，风险仍须靠支撑',
            compounding='重复识别共振周期只是待证机制')
    if name in MONEY:
        return dict(label='成交额×相对强度' if name in MONEY[:3] else '20/120日成交额关注度分位',
            source='①优先成交额最高、②leader扫描；lS9z@1:39:52、1:30:37–1:33:42；乘积/120日为本轮补充',
            not_following_crowd='资金关注上升不直接表示逆人群', retail_counterparty='成交额不是净流入或身份信息',
            small_capital='流动性便于小仓进出', payoff='成交额本身不给窄止损',
            compounding='成本与持续关注可能有利，尚无账户证明')
    return dict(label='长期强势×流动性×贴线分位', source='③旧leader重新升级、④回到9/21 EMA；VKNE@1:01:28、2:32:35；组合公式为本轮补充',
        not_following_crowd='旧强票回调降温时准备，避免只追当月最热', retail_counterparty='承接卖压是推断，不能识别交易者',
        small_capital='靠近支撑可小仓反复试错', payoff='用近处风险位参与旧趋势再起',
        compounding='小亏试错、证实放大交执行线验证')


def report():
    meta, arrays, x = load_cache()
    selected = F.read(WORK/'selection.json')
    fits = {c['id']: F.read(WORK/f'fit_{c["id"]}.json') for c in CANDIDATES}
    best, second = fits[selected['chosen']], fits[selected['second']]
    main = best['metrics']['3']
    hold = F.read(WORK/'holdout.json')['metrics']['3']
    cross = F.read(WORK/'crossyear.json')['results']
    baseline = F.read(F1_WORK/'fit_F1a.json')['metrics']['3']
    baseline_hold = F.read(F1_WORK/'holdout.json')['metrics']['3']
    labels = F.read(F1_WORK/'train_labels.json')
    held_labels = [r for r in F.read(F1_WORK/'full_labels.json') if r['year'] == '2026']
    train_diag = diagnose(best['model'], meta, arrays, x, labels, main, meta['train_last'])
    hold_diag = diagnose(best['model'], meta, arrays, x, held_labels, hold)
    F.write(WORK/'leg_diagnostics.json', dict(train=train_diag, holdout=hold_diag))
    originals = F.read(F1_WORK/'explanations.json')
    explanations = {n: explanation(n, originals) for n in FEATURES}
    F.write(WORK/'explanations.json', explanations)
    ranges = []
    for candidate, result in fits.items():
        for part, items in result['model']['parts'].items():
            for item in items:
                for entry, values in enumerate(item['scores']):
                    for label, value in zip(intervals(item), values):
                        ranges.append(dict(candidate=candidate, part=part, entry=entry,
                            feature=item['name'], interval=label, score=value, weight=item['weight']))
    with (WORK/'profile_ranges.csv').open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=('candidate', 'part', 'entry', 'feature', 'interval', 'score', 'weight'))
        writer.writeheader()
        writer.writerows(ranges)
    F.write(WORK/'handoff.json', dict(chosen=selected['chosen'], second=selected['second'],
        files=[f'picks_{n}.json' for n in (selected['chosen'], selected['second'])],
        observation_sessions=5, nomination_timing='after_close', fill_timing='trigger_day_close',
        routes=F.ROUTE_NAMES, account_results_available=False,
        first_action_may_consume_observation=True,
        caveat='F1 legacy per-anchor early-buy labels; not Y1 fixed-first-anchor account coverage'))

    comparison = []
    for title, train, test in (('F1a绝对值', baseline, baseline_hold), (selected['chosen']+'当晚自适应', main, hold)):
        for year in ('2024', '2025', '2026'):
            row = (test if year == '2026' else train)['by_year'][year]
            comparison.append((title, year, f'{row["covered"]}/{row["n"]}', pct(row['P_opp']), pct(row['E']),
                row['different_codes'], row['first_action_opportunities']))
    lines = ['# F2：当晚相对位置、同伴共振与资金关注',
        f'\n**本轮选股研究按训练规则选出{selected["chosen"]}，第二名{selected["second"]}；尚无可替换登记版的账户结论。** '
        f'2024–25早买触发代理为{main["by_year"]["2024"]["covered"]}/9、{main["by_year"]["2025"]["covered"]}/22，'
        f'合计{main["covered"]}/31（F1a为21/31）；首选冻结后2026一次评测为{hold["covered"]}/17（F1a为3/17）。'
        '点到、五晚能触发和账户实际买到是不同层。本轮没有账户收益、资金占用纯度、毛利纯度或胜率结论，不改登记版和看板。',
        '\n'+table(('画像', '年', '早买触发代理', '机会夜命中', '剩余涨幅中位', '不同票', '首动作供给'), comparison),
        '\n## 1. 五个候选与固定选择',
        '\n只据2024和2025画像差异设计：一个月中位约21%→4%、六个月约31%→87%，而流动性相对位置和均线附近结构较稳定。'
        '所有候选保留F1新池、两入口、长期记忆、K=3、10晚冷却及同一拟合器。共同至多7项、QQQ上升/回调各3项修正；弱势无修正。'
        '每年首动作供给≥52只是选股可供执行的资格，并非账户达到52笔。',
        '\n'+table(('候选', '2024', '2025', '合计', 'P_opp', 'E', '动作供给24/25', '资格'),
            [(c['id'], f'{fits[c["id"]]["metrics"]["3"]["by_year"]["2024"]["covered"]}/9',
              f'{fits[c["id"]]["metrics"]["3"]["by_year"]["2025"]["covered"]}/22',
              f'{fits[c["id"]]["metrics"]["3"]["covered"]}/31', pct(fits[c['id']]['metrics']['3']['P_opp']),
              pct(fits[c['id']]['metrics']['3']['E']),
              '/'.join(str(fits[c['id']]['metrics']['3']['by_year'][y]['first_action_opportunities']) for y in ('2024', '2025')),
              yn(fits[c['id']]['support_52'])) for c in CANDIDATES]),
        '\n冻结顺序：'+' → '.join(selected['ranked'])+'。只按(C_trig合计、P_opp、E)及52供给门槛选择；跨年诊断和2026不改变名次。',
        '\nG1是当晚分位；G2再加三个同伴项；G3再加四个资金项；G4保留双年偏好相关≥0.6的G3项；G5在G3加长期强势×成交额×贴线组合。'
        'G5事前诊断在prediagnosis.json：F1a漏10段，一段无池内合格夜，其余九段的最高分夜有六段属于长期强势回调，故用通用组合表达旧leader靠近风险位；未硬编码票名或交易日。',
        '\n## 2. 核心诊断：画像能否跨年移植',
        '\n各行重新只用源年的池行和标签拟合，目标年不参与边界、概率、系数或回退。源年/目标年标签各截止其年末，原段分母不变。'
        '2025→2024是逆向移植诊断，不能称前向样本外。G4*仅用源年上/下半年方向一致筛项；正式G4双年门槛会使用目标标签，故不能把其固定筛项冒充独立跨年。',
        '\n'+table(('画像', '源年→目标年', '源年拟合段', '移植早买段', '目标P_opp', '目标E'),
            [(r['candidate']+('*' if r['agreement_uses_source_halves'] else ''), r['source_year']+'→'+r['target_year'],
              f'{r["self"][0]}/{9 if r["source_year"] == "2024" else 22}',
              f'{r["transfer"][0]}/{9 if r["target_year"] == "2024" else 22}',
              pct(r['transfer'][1]), pct(r['transfer'][2])) for r in cross]),
        '\n当晚分位随市况变，但拟合的偏好区间仍可能只适合某年；跨年两行须同时看，不能用合并拟合分数证明可移植。'
        '1/3/6月相对QQQ强度在同晚仅减去常数，与对应涨幅的分位重复；本轮按要求保留并明确它不增加横截面信息。',
        '\n## 3. 特征、区间与赚钱理由',
        '\n全部市场特征只用当晚及此前日K。缺失保留单独一档。分位是当晚新池0–100平均秩，档边界仍只用拟合段20/40/60/80分位；'
        '没有按全期分位设档。长期记忆与入口直接沿用F1。行业字段不可用，相关仅作同伴近似：60日完整简单收益、相关≥0.6，剔除自己，'
        '全池分128×128块计算；历史不足或无同伴时计数0、同伴中位/本票同伴名次缺失。未把池截成400只，未建全市场矩阵。',
        '\n资金项是成交额分位与三种相对强度分位的乘积，以及20日成交额均值/120日均值的当晚分位。'
        'G5为memory×(成交额分位/100)/(1+距9/21最近绝对ADR)，再取当晚分位。价量项不能证明真实净流入或散户对手身份。',
    ]
    for result in (best, second):
        rows = []
        for part, items in result['model']['parts'].items():
            for item in items:
                favored = []
                for values in item['scores']:
                    labels_bin = intervals(item)
                    favored.append('、'.join(labels_bin[i] for i, value in enumerate(values) if abs(value-max(values)) < 1e-10))
                rows.append((part, explanations[item['name']]['label'], item['name'], item['weight'], *favored))
        lines.append('\n'+result['model']['spec']['id']+'最高分区间（不是硬过滤）：\n\n'+table(
            ('层', '项目', '字段', '系数', '新出现', '长期强势回调'), rows))
    used = {item['name'] for result in fits.values() for items in result['model']['parts'].values() for item in items}
    keys = ('label', 'source', 'not_following_crowd', 'retail_counterparty', 'small_capital', 'payoff', 'compounding')
    lines.append('\n下表覆盖五个候选实际保留项并集；所有档位、概率、权重与两入口全表在profile_ranges.csv和fit_G*.json。'
                 '缺失偏好、量比放大、远离支撑等若被选中，只是统计拟合，不能借原话追认解释。\n\n'+table(
                     ('项', '对应原话/补充', '不随大流', '散户对手盘', '小资金', '盈亏比', '复利'),
                     [tuple(explanations[n][k] for k in keys) for n in FEATURES if n in used]))
    agree = fits['G4']['agreement']
    lines.append('\nG4方向一致筛项：\n\n'+table(('项', '双年偏好相关', '保留'),
                 [(r['name'], f'{r["correlation"]:.3f}', yn(r['keep'])) for r in agree]))
    lines.append('\n## 4. 逐段点到、动作和早买')
    for title, diag in (('2024–25拟合', train_diag), ('2026首选一次评测', hold_diag)):
        lines.append('\n### '+title+'\n\n'+table(
            ('票/段起点', '精度', '点到', '随后有动作', '仍剩一半', '首个合格触发收盘', '剩余比例', '最高原始名次', '漏层'),
            [(r['leg']['code'].removeprefix('US.')+' '+r['leg']['first_date'], r['leg']['precision'],
              yn(r['nominated']), yn(r['actual_action']), yn(r['covered']),
              meta['days'][r['first']['fill']] if r['first'] else '—',
              pct(r['first']['share']) if r['first'] else '—', r['best_unrestricted_rank'] or '—', r['reason']) for r in diag]))
    flags = [r for r in train_diag+hold_diag if r['covered'] and r['first_anchor_share'] < .5]
    lines.append('\n点到采用F1合格信号夜；随后动作是该点名五晚内首动作且在峰前；早买允许五晚内任一合格收盘动作。'
        '较早动作可能先消费观察，账户需另验。C_trig沿F1多锚点窗口，不能替代Y1固定首锚点账户覆盖。'
        f'已覆盖但按固定首锚点剩余不足一半的段共{len(flags)}个，详见leg_diagnostics.json的first_anchor_share。')
    strata = []
    for year in ('2024', '2025', '2026'):
        rows = [r for r in train_diag+hold_diag if r['year'] == year]
        for label, fn in (('事件<5日', lambda r: r['leg']['duration'] < 5),
                          ('波段≥5日', lambda r: r['leg']['duration'] >= 5),
                          ('exact', lambda r: r['leg']['precision'] == 'exact'),
                          ('chart', lambda r: r['leg']['precision'] == 'chart'),
                          ('window', lambda r: r['leg']['precision'] == 'window'),
                          ('不含截断', lambda r: not r['leg']['censored'])):
            rr = [r for r in rows if fn(r)]
            strata.append((year, label, f'{sum(r["covered"] for r in rr)}/{len(rr)}'))
    lines.append('\n'+table(('年', '分层', '早买代理'), strata))
    lines.append('\n2025跨年裁剪沿F1：'+ '、'.join(r['leg']['key'] for r in F.read(F1_WORK/'train_labels.json')
                 if r['leg'].get('training_clipped'))+'。不删事件段、不可达段、截断段；2026被截断的未覆盖段属于未决。')
    all_k = []
    held_all = F.read(WORK/'holdout.json')['metrics']
    for k in (1, 2, 3):
        for year in ('2024', '2025', '2026'):
            row = (held_all if year == '2026' else best['metrics'])[str(k)]['by_year'][year]
            all_k.append((k, year, f'{row["covered"]}/{row["n"]}', pct(row['P_opp']), pct(row['E']),
                          row['different_codes'], row['first_action_opportunities']))
    lines.append('\nK同时诊断（各自重新运行冷却，不截短K=3名单）：\n\n'+table(
        ('K', '年', '早买代理', 'P_opp', 'E', '不同票', '首动作供给'), all_k))
    lines.extend(['\n## 5. 给执行线的文件与验证',
        f'\n首选`f2_work/picks_{selected["chosen"]}.json`，第二名`f2_work/picks_{selected["second"]}.json`；'
        '格式沿F1为`{交易日: [代码...]}`，含空名单夜、按分数排序；details含score/rank/entry_type/regime，warmup另存2023年末一晚。'
        f'范围2024-01至{meta["days"][-1]}。第二名2026只导出点名，未评测覆盖。',
        '\n点名为当晚收盘后，随后1–5个交易日观察close_pdh/E10/E11/B，触发日按收盘评测，B保留自身背景。'
        '仅PDH的旧消费器可读同样JSON，但覆盖含义不相同；观察消费、止损、同票、格子、资金与加仓仍由执行线处理。'
        '完整逐夜点名与首动作供给不是账户收益或利润纯度的替代。',
        '\n运行：`OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 systemd-run --scope -p CPUQuota=60% -p MemoryMax=900M -q '
        '.venv/bin/python -m studies.trader_replication.martin_profile_f2 阶段`；阶段依次prepare、fit、crossyear、evaluate、report、verify。'
        'prepare、selection、evaluation_started分别防止覆盖已完成特征、重新选择、重复打开2026。report只读已冻结指标，不再评测。',
        f'\n准备峰值RSS {meta["peak_rss_mib"]:.1f}MiB；主拟合峰值最高{max(r["peak_rss_mib"] for r in fits.values()):.1f}MiB。'
        f'当晚全池最大{meta["pool_maximum"]}只，相关块≤128×128，窗口60日；固定大小特征矩阵写磁盘映射。'
        f'数据digest `{meta["dataset_digest"]}`；预登记SHA256 `{F.sha(PREREG)}`。',
    ])
    tests = []
    for group in ('custody', 'martin_luk', 'trader_replication'):
        content = (WORK/f'tests_{group}.log').read_text()
        ok = content.rstrip().splitlines()[-1].split(' (', 1)[0] == 'OK'
        tests.append((group, '；'.join(re.findall(r'Ran \d+ tests? in [^\n]+', content)), '通过' if ok else '失败，见日志'))
    lines.append('\n'+table(('测试组', '原始结果', '状态'), tests))
    lines.append('\n源码、预登记、缓存、模型和点名指纹及三组原始日志见completion.json。未联网、未拉数据、未提交Git；'
                 'F1、M1和模拟引擎未由本轮修改，另线对共享引擎的变化单独记录，不写成全工作树未变。')
    REPORT.write_text('\n'.join(lines)+'\n', encoding='utf-8')
    F.write(WORK/'assessment.json', dict(chosen=selected['chosen'], second=selected['second'],
        training_objective=F.objective(main), holdout_objective=F.objective(hold),
        adoption_qualified=False, account_results_available=False, crossyear_diagnostic_only=True))
    F.log('F2 report rendered without refitting or reevaluating 2026')


def verify():
    meta, arrays, x = load_cache()
    selected = F.read(WORK/'selection.json')
    held = F.read(WORK/'holdout.json')
    assert held['chosen'] == selected['chosen'] and held['evaluated_once']
    assert held['selection_sha256'] == F.sha(WORK/'selection.json')
    assert F.read(WORK/'crossyear.json')['selection_sha256'] == F.sha(WORK/'selection.json')
    changed = [name for name, digest in protected().items() if meta['protected'][name] != digest]
    assert all(name == 'studies/trader_replication/system.py' for name in changed), 'protected input changed'
    checks = {}
    for name in (selected['chosen'], selected['second']):
        model = F.read(WORK/f'fit_{name}.json')['model']
        sample = sample_for(model, meta, arrays, x, [])
        nominations = sample.nominate(score(model, sample))
        expected = {meta['days'][int(t)]: [meta['codes'][int(sample.code[r])] for r in rr if r < len(sample.indices)]
                    for t, rr in zip(sample.nights, nominations) if meta['days'][int(t)] >= F.START}
        assert expected == F.read(WORK/f'picks_{name}.json')
        prefix = sample_for(model, meta, arrays, x, [], meta['train_last'])
        before = prefix.nominate(score(model, prefix))
        assert np.array_equal(nominations[:len(before)], before)
        assert all(len(items) <= (7 if part == 'shared' else 3) for part, items in model['parts'].items())
        checks[name] = dict(export_exact=True, inference_prefix_invariant=True,
            capacity_7_3_3=True, nights=len(expected), nominations=sum(map(len, expected.values())))
    tests = {}
    for group in ('custody', 'martin_luk', 'trader_replication'):
        path = WORK/f'tests_{group}.log'
        content = path.read_text()
        tests[group] = dict(ok=content.rstrip().splitlines()[-1].split(' (', 1)[0] == 'OK', sha256=F.sha(path),
            summary=re.findall(r'Ran \d+ tests? in [^\n]+', content))
    assert all(row['ok'] for row in tests.values()), 'required test group failed'
    assert REPORT.exists()
    F.write(WORK/'completion.json', dict(complete=True, task='PLAN_F2_CN.md', chosen=selected['chosen'],
        second=selected['second'], candidates=5, candidate_passed=selected['passed'],
        holdout_evaluations=1, runner_up_holdout_metrics=False, checks=checks, tests=tests,
        source_hashes=sources(), report_sha256=F.sha(REPORT), dataset_digest=meta['dataset_digest'],
        protected_unchanged=not changed, allowed_external_engine_changes=changed,
        python=sys.executable, resource_limits=dict(cpu_quota='60%', memory_max='900M', processes=1, threads=1),
        cache_peak_rss_mib=meta['peak_rss_mib'], correlation_block=128,
        network_disabled=True, new_data=False, git_commit=False,
        hook_install='existing hooks retained; installer refused overwrite',
        artifacts={p.name: F.sha(p) for p in WORK.iterdir() if p.is_file() and p.name != 'completion.json'}))
    F.log('F2 verification complete')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=('prepare', 'fit', 'crossyear', 'evaluate', 'report', 'verify'))
    args = parser.parse_args()
    WORK.mkdir(exist_ok=True)
    offline()
    globals()[args.stage]()


if __name__ == '__main__':
    main()
