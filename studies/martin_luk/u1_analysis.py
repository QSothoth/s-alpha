"""Fixed U1 discrimination, optimistic accounting scenarios, and 48-leg audit."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
from functools import lru_cache
from pathlib import Path

import numpy as np

from . import u1_research as U

CUTS = (1, 5, 10, 20, 50, 100)
CATEGORIES = ('EP跳空形态', '长期强势回调再起', '新共振近似', '突破整理', '其他')


def data():
    meta = U.read(U.WORK/'prepare.json')
    features = U.read(U.WORK/'features.json')
    x = np.load(U.WORK/'features.npy', mmap_mode='r')
    queries = np.load(U.WORK/'query.npy', mmap_mode='r')
    keys = queries[:, 0].astype(np.int64)*len(meta['codes'])+queries[:, 1]
    return meta, features, x, keys, U.library()


def query_indices(legs, keys, codes, offset=0, allow_missing=False):
    ci = {c: j for j, c in enumerate(codes)}
    wanted = np.array([(g['first']+offset)*len(codes)+ci[g['code']] for g in legs])
    indices = np.searchsorted(keys, wanted)
    valid = indices < len(keys)
    valid[valid] &= keys[indices[valid]] == wanted[valid]
    if not allow_missing:
        assert valid.all()
    indices[~valid] = -1
    return indices


def offset_values(legs, keys, codes, x, offset):
    indices = query_indices(legs, keys, codes, offset, allow_missing=True)
    values = np.full((len(legs), x.shape[1]), np.nan)
    valid = indices >= 0
    values[valid] = x[indices[valid]]
    return values, valid


def auc(values, labels):
    values, labels = np.asarray(values, float), np.asarray(labels, bool)
    ok = np.isfinite(values)
    values, labels = values[ok], labels[ok]
    n1, n0 = int(labels.sum()), int((~labels).sum())
    if not n1 or not n0:
        return None
    order = np.argsort(values, kind='stable')
    sorted_values = values[order]
    _, first, count = np.unique(sorted_values, return_index=True, return_counts=True)
    ranks = np.empty(len(values))
    ranks[order] = np.repeat(first+(count+1)/2, count)
    return float((ranks[labels].sum()-n1*(n1+1)/2)/(n1*n0))


def fit_logistic(values, labels):
    values, labels = np.asarray(values, float), np.asarray(labels, int)
    n, k = values.shape
    if not 0 < labels.sum() < n:
        raise ValueError('both classes required')
    median = np.array([np.median(c[np.isfinite(c)]) if np.isfinite(c).any() else 0. for c in values.T])
    v = np.where(np.isfinite(values), values, median)
    low, high = np.quantile(v, [.05, .95], axis=0)
    v = np.clip(v, low, high)
    center, scale = v.mean(0), v.std(0)
    scale[scale < 1e-8] = 1
    z = np.column_stack([np.ones(n), (v-center)/scale])
    weight = np.where(labels > 0, n/(2*labels.sum()), n/(2*(n-labels.sum())))
    beta = np.zeros(k+1)
    penalty = np.diag(np.r_[0., np.ones(k)])

    def loss(b):
        eta = z@b
        return float(np.dot(weight, np.logaddexp(0, eta)-labels*eta)+.5*np.dot(b[1:], b[1:]))

    converged = False
    for iteration in range(60):
        probability = 1/(1+np.exp(-np.clip(z@beta, -40, 40)))
        gradient = z.T@(weight*(probability-labels))+penalty@beta
        hessian = z.T@((weight*probability*(1-probability))[:, None]*z)+penalty
        delta = np.linalg.solve(hessian, gradient)
        step = 1.
        previous = loss(beta)
        while step > 1e-8 and loss(beta-step*delta) > previous:
            step *= .5
        beta -= step*delta
        if np.max(abs(step*delta)) < 1e-8:
            converged = True
            break
    if not converged:
        raise ValueError('fixed logistic fit did not converge')
    return dict(median=median, low=low, high=high, center=center, scale=scale, beta=beta,
                l2=1, iterations=iteration+1, converged=converged, n=n, positives=int(labels.sum()),
                loss=loss(beta), features=U.MODEL, weighting='n/(2*class_count); sum loss + .5*L2')


def score(model, values):
    values = np.asarray(values, float)
    v = np.where(np.isfinite(values), values, np.asarray(model['median']))
    v = np.clip(v, model['low'], model['high'])
    z = (v-np.asarray(model['center']))/np.asarray(model['scale'])
    return np.asarray(model['beta'])[0]+z@np.asarray(model['beta'])[1:]


def mature_mask(legs, days, years, cutoff):
    last = int(np.searchsorted(days, cutoff, side='right'))-1
    return np.array([g['year'] in years and g['first']+60 <= last and not g['censored'] for g in legs])


def fit():
    U.start('fit')
    meta, feature, x, keys, legs = data()
    names = feature['names']
    columns = [names.index(n) for n in U.MODEL]
    ix = query_indices(legs, keys, meta['codes'])
    values = np.asarray(x[ix][:, columns], float)
    y = np.array([g['his'] for g in legs])
    outputs = {}
    for name, years, cutoff in (('2024', ('2024',), '2024-12-31'),
                                ('2025', ('2025',), '2025-12-31'),
                                ('2024_2025', ('2024', '2025'), '2025-12-31')):
        train = mature_mask(legs, meta['days'], years, cutoff)
        model = fit_logistic(values[train], y[train])
        model.update(id=name, cutoff=cutoff, source_years=years, train_ids=np.flatnonzero(train),
                     train_positive_targets=[g['target'] for g, ok in zip(legs, train) if ok and g['his']],
                     model_source_sha256=U.sha(Path(__file__)), protocol_sha256=U.sha(U.WORK/'protocol.md'),
                     clarification_sha256=U.sha(U.WORK/'protocol_clarification.md'),
                     features_sha256=U.sha(U.WORK/'features.npy'))
        U.write('model_'+name+'.json', model)
        outputs[name] = dict(n=int(train.sum()), positives=int(y[train].sum()),
            training_auc=auc(score(model, values[train]), y[train]),
            coefficients=dict(zip(U.MODEL, model['beta'][1:])), cutoff=cutoff,
            dropped_not_mature=sum(g['year'] in years and not ok for g, ok in zip(legs, train)))
    U.write('fit.json', dict(models=outputs, resources=U.resources(), candidates=1,
        selection='none; seven features, penalty and every reporting cut fixed before fitting',
        hashes={n: U.sha(U.WORK/n) for n in ('model_2024.json', 'model_2025.json', 'model_2024_2025.json')}))
    U.log('three fixed training fits complete; 2026 metrics unopened')


def top_weights(scores, percent):
    """Fractional boundary ties preserve requested mass without using ticker names."""
    scores = np.asarray(scores, float)
    if not len(scores):
        return np.empty(0)
    mass = len(scores)*percent/100
    cutoff = np.sort(scores)[max(0, len(scores)-int(np.ceil(mass)))]
    result = (scores > cutoff).astype(float)
    equal = scores == cutoff
    result[equal] = (mass-result.sum())/equal.sum()
    return result


def ranking(scores, labels):
    labels = np.asarray(labels, bool)
    rows = []
    for percent in CUTS:
        w = top_weights(scores, percent)
        hits = float(w@labels)
        rows.append(dict(percent=percent, selected=float(w.sum()), his=hits,
                         precision=hits/w.sum() if w.sum() else None,
                         recall=hits/labels.sum() if labels.sum() else None))
    return rows


def distribution(values):
    v = np.asarray(values, float)
    finite = v[np.isfinite(v)]
    return dict(n=len(v), finite=len(finite), missing=len(v)-len(finite),
                q25=float(np.quantile(finite, .25)) if len(finite) else None,
                median=float(np.median(finite)) if len(finite) else None,
                q75=float(np.quantile(finite, .75)) if len(finite) else None)


def strata(legs, values, names):
    field = names.index('pctl_dollar_vol20_M')
    result = []
    for year in U.YEARS:
        part = [(g, row) for g, row in zip(legs, values) if g['year'] == year]
        for kind in ('liquidity_quartile', 'duration', 'industry_snapshot', 'peer_resonance'):
            groups = defaultdict(list)
            for g, row in part:
                if kind == 'liquidity_quartile':
                    v = row[field]
                    label = ('缺失' if not np.isfinite(v) else
                             ('0–25', '25–50', '50–75', '75–100')[min(3, int(v//25))])
                elif kind == 'duration':
                    label = '0–5日' if g['duration'] <= 5 else ('6–20日' if g['duration'] <= 20 else '21–60日')
                elif kind == 'industry_snapshot':
                    label = g['industry'] or '未分类'
                else:
                    peers = row[names.index('peer_leaders20_count')]
                    label = '无强同伴' if peers == 0 else ('1–2强同伴' if peers < 3 else '≥3强同伴')
                groups[label].append(g)
            for label, group in sorted(groups.items()):
                result.append(dict(year=year, kind=kind, group=label, n=len(group),
                                   his=sum(g['his'] for g in group),
                                   precision=sum(g['his'] for g in group)/len(group)))
    return result


def scenario(legs, weights, year, p, codes, frozen):
    """An explicit oracle-entry/peak-close policy, not an upper bound over all algorithms."""
    days = p['days'].tolist()
    mask = np.array([d[:4] == year for d in days])
    total, relaxed, strict = (np.zeros(len(days)) for _ in range(3))
    ci = {c: j for j, c in enumerate(codes)}
    target = {g['key']: g for g in frozen}
    gross = his_gross = strict_gross = 0.
    tradable, bad_next_open, pre_window, negative_mark = 0, 0, 0, 0
    for g, weight in zip(legs, weights):
        if weight <= 0:
            continue
        current_year = g.get('year', year) == year
        j, born, peak = ci[g['code']], g['first']+1, g['peak']
        if born > peak or born >= len(days) or not (np.isfinite(p['o'][born, j]) and p['o'][born, j] > 0):
            bad_next_open += current_year
            continue
        tradable += current_year
        opening = float(p['o'][born, j])
        path = np.nan_to_num(p['c'][born:peak+1, j].astype(float)/opening)*weight
        total[born:peak+1] += path
        profit = weight*(float(p['c'][peak, j])/opening-1)
        gross += max(0., profit) if current_year else 0
        negative_mark += current_year and profit <= 0
        if g['his']:
            relaxed[born:peak+1] += path
            his_gross += max(0., profit) if current_year else 0
            f = target[g['target']]
            if f['first']-3 <= born < f['peak'] and peak >= f['first']:
                strict[born:peak+1] += path
                strict_gross += max(0., profit) if current_year else 0
            else:
                pre_window += current_year
    active = total > 0
    daily_relaxed = np.divide(relaxed, total, out=np.zeros(len(days)), where=active)
    daily_strict = np.divide(strict, total, out=np.zeros(len(days)), where=active)
    current = np.array([g.get('year', year) == year for g in legs])
    return dict(year=year, selected=float(np.sum(np.asarray(weights)[current])), selected_positive_weight=float(
        np.dot(np.asarray(weights)[current], np.array([g['his'] for g in legs])[current])), tradable=tradable,
        invalid_next_open=bad_next_open, nonpositive_peak_close=negative_mark,
        his_entry_outside_Y1_window=pre_window, active_days=int(sum(active & mask)), sessions=int(mask.sum()),
        gross_potential=gross, relaxed_gross=his_gross/gross if gross else None,
        strict_gross=strict_gross/gross if gross else None,
        relaxed_cap_share=float(relaxed[mask].sum()/total[mask].sum()) if total[mask].sum() else None,
        strict_cap_share=float(strict[mask].sum()/total[mask].sum()) if total[mask].sum() else None,
        relaxed_cap_equity_100=float(daily_relaxed[mask].mean()),
        relaxed_cap_equity_280=float(2.8*daily_relaxed[mask].mean()),
        strict_cap_equity_100=float(daily_strict[mask].mean()),
        strict_cap_equity_280=float(2.8*daily_strict[mask].mean()),
        convention='continuous cohorts since 2024 including prior-year carry; next-open entry; oracle peak-close terminal mark; '
                   'equal initial notional, daily marked weights normalized to 100%/280%, cash days included; '
                   'gross potential assigned by start year, not an annual account return')


def calendar_capacity(p, frozen):
    meta = U.read(U.WORK/'prepare.json')
    days, codes = meta['days'], meta['codes']
    ci = {c: j for j, c in enumerate(codes)}
    liquid = np.load(U.WORK/'liquid.npy', mmap_mode='r')
    starts = np.load(U.WORK/'starts.npy', mmap_mode='r')
    by_code = defaultdict(lambda: np.zeros(len(days), bool))
    evidence = []
    for g in frozen:
        j = ci[g['code']]
        candidates = []
        early = []
        for night in range(max(0, g['first']-4), g['peak']-1):
            born = night+1
            opening = p['o'][born, j]
            if liquid[night, j] and starts[night, j] and np.isfinite(opening) and opening > 0:
                candidates.append(born)
                if g['top']/opening-1 >= .5*g['gain']:
                    early.append(born)
        if candidates:
            by_code[g['code']][candidates[0]:g['peak']+1] = True
        evidence.append(dict(key=g['key'], local_entry=len(candidates), early_local_entry=len(early),
                             first_entry=days[candidates[0]] if candidates else None,
                             first_early=days[early[0]] if early else None))
    counts = sum(by_code.values(), np.zeros(len(days), int))
    result = {}
    for year in U.YEARS:
        ix = np.array([d[:4] == year for d in days])
        n = counts[ix]
        result[year] = dict(sessions=int(ix.sum()), any_his_days=int((n > 0).sum()),
            mean_his_codes=float(n.mean()), max_his_codes=int(n.max()),
            relaxed_calendar_upper_100=float((n > 0).mean()),
            relaxed_calendar_upper_280=float(2.8*(n > 0).mean()),
            continuous_half_cap_100=float(np.minimum(1., .5*n).mean()),
            continuous_half_cap_280=float(np.minimum(2.8, .5*n).mean()),
            continuous_half_cap_is_engine_upper=False)
    return dict(years=result, legs=evidence, assumptions='future H identity; earliest admissible local entry; '
        'hold to frozen peak; unique codes per day; relax prices, risk, financing and funding path; '
        '50% continuous cap is a sensitivity, since R74 entry cap permits appreciation drift')


def pattern(g, features, p, ci):
    t, j = g['first'], ci[g['code']]
    e9 = np.load(U.WORK/'ema9.npy', mmap_mode='r')
    e21 = np.load(U.WORK/'ema21.npy', mmap_mode='r')
    starts = np.load(U.WORK/'starts.npy', mmap_mode='r')
    look = slice(max(0, t-4), t+1)
    touched = bool(np.any((p['l'][look, j] <= e9[look, j]) | (p['l'][look, j] <= e21[look, j])))
    if features['ep10_recent3'] > 0:
        category = CATEGORIES[0]
    elif features['long_strength_memory'] > 0 and touched and features['support_near_adr'] <= 1:
        category = CATEGORIES[1]
    elif features['long_strength_memory'] == 0 and features['peer_leaders20_count'] >= 3:
        category = CATEGORIES[2]
    elif np.any(starts[max(0, t-2):t+1, j] & 1) or features['contract3_adr'] <= 1:
        category = CATEGORIES[3]
    else:
        category = CATEGORIES[4]
    return category, touched


def account_capture(meta, frozen):
    """Use recorded fills, including registered master's full continuous long book."""
    sources = {
        'IE47_C062': U.HOME/'reports/y1_work/IE47_C062.json',
        'M1B_train': U.HOME/'reports/m1_work/candidates/M1B/metrics.json',
        'M1B_continuous': U.HOME/'reports/m1_work/validation/continuous/metrics.json',
        'F2_G1': U.HOME/'reports/f2_work/leg_diagnostics.json',
        'master_trades': U.HOME/'reports/d1_work/master_trades.json',
        'master_curve': U.HOME/'reports/d1_work/master_curve.json',
    }
    U.write('capture_sources.json', U.snapshots(list(sources.values())))
    ie = {r['key']: r for r in U.read(sources['IE47_C062'])['legs']}
    m1b = {r['key']: r for r in U.read(sources['M1B_train'])['legs']}
    m1b.update({r['key']: r for r in U.read(sources['M1B_continuous'])['legs'] if r['year'] == '2026'})
    f2 = U.read(sources['F2_G1'])
    f2 = {r['key']: r for part in f2.values() for r in part}
    # Re-evaluate the stored 3-year registered account under the frozen 48 labels.
    # This does not call the simulator, signal builder, or an M1/M2 module.
    from . import y1_research as Y1
    trades = [r for r in U.read(sources['master_trades']) if r['side'] == 1]
    U.write('native_master_recorded_longs.json', trades)
    normalized, adapter = Y1.adapt(U.WORK/'native_master_recorded_longs.json', meta['days'])
    p = U.load_panel()
    ci = {c: j for j, c in enumerate(meta['codes'])}

    class Prices:
        @lru_cache(maxsize=16)
        def __getitem__(self, code):
            return {k: p[k][:, ci[code]].astype(float) for k in ('o', 'h', 'l', 'c')}

    curve = U.read(sources['master_curve'])
    equity = np.ones(len(meta['days']))
    di = {d: i for i, d in enumerate(meta['days'])}
    for day, e in zip(curve['days'], curve['equity']):
        equity[di[day]] = e
    result = U.mainleg.summary_account(normalized, frozen, Prices(), meta['days'], equity)
    U.write('native_master_capture.json', dict(legs=result['legs'], adapter=adapter,
        scope='stored full 3-year registered R74+S7 account, long fills only; per-leg capture, '
              'not whole-account gross purity (short O excluded)'))
    native = {r['key']: r for r in result['legs']}
    output = {}
    for g in frozen:
        key = g['key']
        output[key] = {}
        for name, lookup in (('IE47_C062', ie), ('master', native), ('M1B', m1b)):
            r = lookup[key]
            output[key][name] = dict(any=r['any'], early=r['covered'], pnl=r['pnl'], profitable=r['pnl'] > 0)
        r = f2[key]
        output[key]['F2_G1'] = dict(early=r['covered'], nominated=r['nominated'],
                                    action=r['actual_action'], account_available=False)
    return output


def audit_48(meta, feature, x, keys, legs, p):
    frozen = U.read(U.FROZEN)['legs']
    ci = {c: j for j, c in enumerate(meta['codes'])}
    indices = query_indices(frozen, keys, meta['codes'])
    names = feature['names']
    capture = account_capture(meta, frozen)
    capacity = calendar_capacity(p, frozen)
    caplegs = {r['key']: r for r in capacity['legs']}
    matched = {g['target']: g for g in legs if g['his']}
    output = []
    for g, index in zip(frozen, indices):
        values = dict(zip(names, map(float, x[index])))
        category, touched = pattern(g, values, p, ci)
        match = matched.get(g['key'])
        overlap = [r for r in legs if r['code'] == g['code'] and r['first'] < g['peak']
                   and r['peak'] >= g['first']-3 and r['peak'] != g['peak']]
        output.append(dict(key=g['key'], code=g['code'], year=g['first_date'][:4],
            anchor=g['first_date'], peak=g['peak_date'], duration=g['duration'], censored=g['censored'],
            precision=g['precision'], pattern=category, touched_support5=touched,
            generic_ep=values['ep10_recent3'] > 0, earnings_ep=values['earn_ep10_recent3'] > 0,
            earnings_days=values['earn_days'], memory=values['long_strength_memory'],
            support_near_adr=values['support_near_adr'], peers=values['peer_leaders20_count'],
            industry=U.read(U.INDUSTRY).get(g['code']) or '未分类',
            library_match=bool(match), library_id=match['id'] if match else None,
            library_first=match['first_date'] if match else None,
            library_offset=match['first']-g['first'] if match else None,
            other_peak_overlaps=len(overlap), local=caplegs[g['key']], capture=capture[g['key']],
            unmatched_reason=None if match else ('no admissible early local action' if not caplegs[g['key']]['early_local_entry']
                else 'local actions exist; their 60-session maxima do not equal the frozen peak')))
    summary = []
    for year in (*U.YEARS, 'all'):
        for category in CATEGORIES:
            group = [r for r in output if r['pattern'] == category and (year == 'all' or r['year'] == year)]
            row = dict(year=year, pattern=category, n=len(group),
                       library_matches=sum(r['library_match'] for r in group),
                       local_early_reachable=sum(r['local']['early_local_entry'] > 0 for r in group),
                       earnings_ep=sum(r['earnings_ep'] for r in group))
            for name in ('IE47_C062', 'master', 'M1B'):
                for measure in ('early', 'any', 'profitable'):
                    row[name+'_'+measure] = sum(r['capture'][name][measure] for r in group)
            row['F2_G1_early_proxy'] = sum(r['capture']['F2_G1']['early'] for r in group)
            summary.append(row)
    U.write('calendar_capacity.json', capacity)
    U.write('patterns_48.json', dict(legs=output, groups=summary,
        definitions='fixed priority at original trader anchor; full 48 retained; all categories are causal daily proxies',
        native_master_source='stored D1 continuous 3-year registered account, evaluated against frozen Y1 48 legs',
        F2='five-night daily action proxy, not actual account fills'))
    return output


def evaluate():
    U.start('evaluation')
    meta, feature, x, keys, legs = data()
    frozen = U.read(U.FROZEN)['legs']
    names = feature['names']
    ix = query_indices(legs, keys, meta['codes'])
    x0 = np.asarray(x[ix], float)
    y = np.array([g['his'] for g in legs])
    years = np.array([g['year'] for g in legs])
    complete = np.array([not g['censored'] for g in legs])
    annual = {}
    for year in U.YEARS:
        mask = years == year
        matched = [g for g in legs if g['year'] == year and g['his']]
        annual[year] = dict(n=int(mask.sum()), his=int(sum(y[mask])),
            precision=float(y[mask].mean()), complete_n=int(sum(mask & complete)),
            complete_his=int(sum(y[mask & complete])), censored_n=int(sum(mask & ~complete)),
            his_anchor_year=dict(Counter(g['anchor'][:4] for g in matched)),
            frozen_anchor_denominator=sum(g['first_date'][:4] == year for g in frozen),
            nonpositive_duration=sum(g['duration'] == 0 for g in legs if g['year'] == year),
            target_codes=sorted({g['code'] for g in matched}))
    U.write('annual_library.json', annual)
    U.write('strata.json', strata(legs, x0, names))
    with (U.WORK/'single_features.csv').open('w', encoding='utf-8', newline='') as output:
        fields = ['year', 'offset', 'feature', 'auc', 'his_n', 'his_finite', 'his_q25', 'his_median', 'his_q75',
                  'other_n', 'other_finite', 'other_q25', 'other_median', 'other_q75', 'missing_his', 'missing_other']
        writer = csv.DictWriter(output, fields)
        writer.writeheader()
        for offset in U.OFFSETS:
            values, _ = offset_values(legs, keys, meta['codes'], x, offset)
            for year in U.YEARS:
                mask = years == year
                for k, name in enumerate(names):
                    h, o = distribution(values[mask & y, k]), distribution(values[mask & ~y, k])
                    writer.writerow(dict(year=year, offset=offset, feature=name, auc=auc(values[mask, k], y[mask]),
                        his_n=h['n'], his_finite=h['finite'], his_q25=h['q25'], his_median=h['median'], his_q75=h['q75'],
                        other_n=o['n'], other_finite=o['finite'], other_q25=o['q25'], other_median=o['median'], other_q75=o['q75'],
                        missing_his=h['missing'], missing_other=o['missing']))
    model_columns = [names.index(n) for n in U.MODEL]
    p = U.load_panel()
    models = {n: U.read(U.WORK/('model_'+n+'.json')) for n in ('2024', '2025', '2024_2025')}
    results, scenarios = [], []
    # One frozen pass over all requested metrics, including all 2026 diagnostics.
    for source, target, kind in (('2024', '2025', 'forward_crossyear'),
                                  ('2025', '2024', 'reverse_diagnostic'),
                                  ('2024_2025', '2024', 'in_sample_diagnostic'),
                                  ('2024_2025', '2025', 'in_sample_diagnostic'),
                                  ('2024_2025', '2026', 'fixed_validation')):
        model = models[source]
        mask = years == target
        target_legs = [g for g, ok in zip(legs, mask) if ok]
        scores = score(model, x0[mask][:, model_columns])
        history = years <= target
        history_legs = [g for g, ok in zip(legs, history) if ok]
        history_years = years[history]
        history_scores = score(model, x0[history][:, model_columns])
        train_scores = score(model, x0[np.asarray(model['train_ids'])][:, model_columns])
        result = dict(source=source, target=target, kind=kind, n=int(mask.sum()), positives=int(y[mask].sum()),
            auc=auc(scores, y[mask]), complete_auc=auc(scores[complete[mask]], y[mask & complete]),
            ranking=ranking(scores, y[mask]), offset_auc={}, transplanted_thresholds=[])
        for delta in U.OFFSETS:
            v, valid = offset_values(target_legs, keys, meta['codes'], x, delta)
            result['offset_auc'][str(delta)] = auc(score(model, v[valid][:, model_columns]), y[mask][valid])
        for percent in CUTS:
            threshold = float(np.quantile(train_scores, 1-percent/100)) if percent < 100 else float(train_scores.min())
            chosen = scores >= threshold
            hits = int(y[mask][chosen].sum())
            result['transplanted_thresholds'].append(dict(source_percent=percent, threshold=threshold,
                selected=int(chosen.sum()), selected_fraction=float(chosen.mean()), his=hits,
                precision=hits/int(chosen.sum()) if chosen.sum() else None,
                recall=hits/int(y[mask].sum()) if y[mask].sum() else None))
            weights = np.zeros(len(history_legs))
            for yr in np.unique(history_years):
                ym = history_years == yr
                weights[ym] = top_weights(history_scores[ym], percent)
            scenario_row = scenario(history_legs, weights, target, p, meta['codes'], frozen)
            scenario_row.update(source=source, kind=kind, cut=percent, selection='retrospective_target_year_top')
            scenarios.append(scenario_row)
            if percent in (1, 5, 10, 20):
                row = scenario(history_legs, (history_scores >= threshold).astype(float),
                               target, p, meta['codes'], frozen)
                row.update(source=source, kind=kind, cut=percent, selection='source_threshold_transplant')
                scenarios.append(row)
        with (U.WORK/('scores_'+source+'_to_'+target+'.csv')).open('w', encoding='utf-8', newline='') as stream:
            writer = csv.writer(stream)
            writer.writerow(('id', 'code', 'first', 'peak', 'score', 'his', 'target', 'censored'))
            for g, s in zip(target_legs, scores):
                writer.writerow((g['id'], g['code'], g['first_date'], g['peak_date'], float(s), g['his'], g['target'], g['censored']))
        results.append(result)
    U.write('discrimination.json', results)
    U.write('oracle_scenarios.json', scenarios)
    patterns = audit_48(meta, feature, x, keys, legs, p)
    current = []
    for year in U.YEARS:
        mask = years == year
        durations = np.array([g['duration'] for g in legs], float)
        profits = []
        ci = {c: j for j, c in enumerate(meta['codes'])}
        for g in legs:
            born, j = g['first']+1, ci[g['code']]
            if born <= g['peak'] and np.isfinite(p['o'][born, j]) and p['o'][born, j] > 0:
                profits.append(max(0., float(p['c'][g['peak'], j]/p['o'][born, j]-1)))
            else:
                profits.append(np.nan)
        profits = np.array(profits)
        dh, do = np.mean(durations[mask & y]), np.mean(durations[mask & ~y])
        gh, go = np.nanmean(profits[mask & y]), np.nanmean(profits[mask & ~y])
        current.append(dict(year=year, hypothetical_event_precision=.05, his_duration=dh, other_duration=do,
            his_gross_per_dollar=gh, other_gross_per_dollar=go,
            equal_duration_equal_profit=dict(cap_share=.05, gross=.05,
                                            cap_equity_100_full_utilization=.05, cap_equity_280_full_utilization=.14),
            empirical_duration_cap_share=.05*dh/(.05*dh+.95*do),
            empirical_profit_purity=.05*gh/(.05*gh+.95*go),
            required_relative_dollar_days_for_50=19., required_relative_gross_for_60=28.5,
            warning='P_opp is nomination precision conditional on opportunity nights, not episode precision; '
                    '5% is an explicit counterfactual assumption, not a measured bound'))
    U.write('five_percent_scenario.json', current)
    U.write('evaluation_complete.json', dict(ok=True, validation_evaluations=1,
        independent_out_of_sample=False, annual=annual,
        matched_frozen=sum(r['library_match'] for r in patterns),
        local_early_reachable=sum(r['local']['early_local_entry'] > 0 for r in patterns),
        resources=U.resources(), model_hashes=U.read(U.WORK/'fit.json')['hashes'],
        evaluation_source_sha256=U.sha(Path(__file__)), no_candidate_selection=True))
    U.log('single fixed evaluation complete; all 48 anchors retained')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=('fit', 'evaluate'))
    args = parser.parse_args()
    U.offline()
    globals()[args.stage]()


if __name__ == '__main__':
    main()
