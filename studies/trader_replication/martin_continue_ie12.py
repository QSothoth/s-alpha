"""IE12: fit compact, explainable preferences inside the unchanged IE8 pool."""
import argparse
from collections import defaultdict
import csv
from datetime import datetime, timezone
import gc
import json
from pathlib import Path
import resource

import numpy as np

from studies.trader_replication import martin_continue_ie10 as prior

ROOT, REPORTS = prior.ROOT, prior.REPORTS
WORK = REPORTS / 'ie12_work'
PREFIX = 'strong_continue_ie12_'
PLAN = ROOT / 'studies/martin_luk/notes/PLAN_IE12_CN.md'
REGISTRATION = WORK / 'registration.json'
SEED = 120031
NEW = ('pool_streak', 'pool_visits20', 'pool_gap', 'prior_run63',
       'state_pullback', 'state_breakout', 'state_ep', 'market_g21',
       'high_age20', 'drawdown_adr20', 'range_contract5', 'volume_dry3',
       'ema9_gap_adr', 'efficiency21', 'gap_age20', 'market_percentile')
VIEW = ('rs1', 'fresh_pot', 'volume_rebound', 'h4_history', 'g21', 'offlow252',
        'peer_rank', 'h4_peers', 'option_volume', 'near_ema9', 'after_inside',
        'iv_change5', 'call_surge5', 'high20', 'low20') + NEW


def read(name):
    return prior.ie7.read(REPORTS / (PREFIX + name + '.json'))


def write(name, value):
    def clean(x):
        if isinstance(x, dict):
            return {k: clean(v) for k, v in x.items()}
        if isinstance(x, (list, tuple)):
            return [clean(v) for v in x]
        if isinstance(x, (float, np.floating)) and not np.isfinite(x):
            return None
        return x
    prior.old.prior.write_json(REPORTS / (PREFIX + name + '.json'), clean(value))


def sequence_values(passed):
    """Past pool membership, including tonight; no later membership is inspected."""
    passed = np.asarray(passed, bool)
    streak = np.zeros(len(passed))
    gap = np.full(len(passed), np.nan)
    previous = None
    for t, flag in enumerate(passed):
        gap[t] = min(t - previous, 63) if previous is not None else 63
        if flag:
            streak[t] = (streak[t - 1] if t else 0) + 1
            previous = t
    total = np.cumsum(passed, dtype=float)
    visits = total.copy()
    visits[20:] -= total[:-20]
    return dict(pool_streak=streak, pool_visits20=visits, pool_gap=gap)


def path_values(arrays):
    """Classify the current observable state, never the ledger's later setup label."""
    lib = prior.lib
    c, o, h, l, v = (np.asarray(arrays[k], float) for k in ('c', 'o', 'h', 'l', 'v'))
    previous = lib.lag(c)
    gap = lib.divide(o, previous) - 1
    volume = lib.divide(v, lib.lag(lib.roll(v, 20)))
    high = lib.lag(lib.roll(h, 20, 'max'))
    adr = lib.roll(lib.divide(h, l) - 1, 20)
    drawdown = lib.divide(lib.divide(high, c) - 1, adr)
    contraction = lib.divide(lib.roll(lib.divide(h, l) - 1, 5), adr)
    high_age = np.full(len(c), np.nan)
    gap_age = np.full(len(c), np.nan)
    last_gap = None
    for t in range(len(c)):
        if np.isfinite(gap[t]) and np.isfinite(volume[t]):
            if gap[t] >= .03 and volume[t] >= 1.5:
                last_gap = t
            gap_age[t] = min(t - last_gap, 21) if last_gap is not None else 21
        if t >= 19 and np.isfinite(h[t - 19:t + 1]).all():
            high_age[t] = np.argmax(h[t - 19:t + 1][::-1])
    valid = np.isfinite(drawdown) & np.isfinite(contraction) & np.isfinite(gap_age)
    ep = gap_age <= 5
    breakout = ~ep & (drawdown <= 1) & (contraction <= 1)
    pullback = ~ep & ~breakout
    return dict(prior_run63=lib.roll(lib.divide(c, lib.lag(c, 21)) - 1, 63, 'max'),
        state_pullback=np.where(valid, pullback, np.nan),
        state_breakout=np.where(valid, breakout, np.nan),
        state_ep=np.where(valid, ep, np.nan), high_age20=high_age,
        drawdown_adr20=drawdown, range_contract5=contraction,
        volume_dry3=lib.divide(lib.roll(v, 3), lib.roll(v, 20)),
        ema9_gap_adr=lib.divide(lib.divide(c, lib.smooth(c, 9)) - 1, adr),
        efficiency21=lib.divide(np.abs(c - lib.lag(c, 21)), lib.roll(np.abs(c - previous), 21, 'sum')),
        gap_age20=gap_age)


def market_value(raw_g21):
    finite = np.asarray(raw_g21)[np.isfinite(raw_g21)]
    return float(np.median(finite)) if len(finite) else np.nan


def market_history_percentile(values):
    """Rank tonight against at most 252 already observed market nights."""
    out = np.full(len(values), np.nan)
    for t, value in enumerate(values):
        history = np.asarray(values[max(0, t - 251):t + 1])
        history = history[np.isfinite(history)]
        if len(history) >= 20 and np.isfinite(value):
            out[t] = (np.count_nonzero(history < value) + .5 * np.count_nonzero(history == value)) / len(history)
    return out


def prepare():
    if (WORK / 'features.json').exists():
        raise ValueError('prepared inputs already exist')
    d = prior.Data(full=True)
    old_values = d.features()
    indices = np.flatnonzero(d.base_passed)
    names = d.names + list(NEW)
    np.save(WORK / 'indices.npy', indices)
    dest = np.lib.format.open_memmap(WORK / 'features.npy', mode='w+',
        dtype=np.float32, shape=(len(indices), len(names)))
    for a in range(0, len(indices), 2048):
        dest[a:a + 2048, :len(d.names)] = old_values[indices[a:a + 2048]]
    dest[:, len(d.names):] = np.nan
    days = sorted(d.slices)
    position = {day: i for i, day in enumerate(d.meta['days'])}
    slices, codes, bycode = {}, {}, defaultdict(list)
    market = [market_value(d.base_raw[d.slices[day], d.base_names.index('g21')]) for day in days]
    market_pct = market_history_percentile(market)
    for t, day in enumerate(days):
        sl = d.slices[day]
        a, b = np.searchsorted(indices, (sl.start, sl.stop))
        slices[day] = [int(a), int(b)]
        codes[day] = [d.meta['scope'][day][int(q - sl.start)] for q in indices[a:b]]
        dest[a:b, names.index('market_g21')] = market[t]
        dest[a:b, names.index('market_percentile')] = market_pct[t]
        for row, code in zip(range(a, b), codes[day]):
            bycode[code].append((t, position[day], row))
    for number, (code, positions) in enumerate(bycode.items()):
        source = prior.old.WORK / 'stocks' / (code + '.npz')
        with np.load(source) as z:
            path = path_values({k: z[k] for k in ('c', 'o', 'h', 'l', 'v')})
        membership = np.zeros(len(days), bool)
        ts, stock_ts, rows = map(np.asarray, zip(*positions))
        membership[ts] = True
        for name, values in sequence_values(membership).items():
            dest[rows, names.index(name)] = values[ts]
        for name, values in path.items():
            dest[rows, names.index(name)] = values[stock_ts]
        if number % 200 == 0:
            print('prepare security', number, '/', len(bycode), flush=True)
    for day, (a, b) in slices.items():
        for name in NEW[:4] + NEW[8:-1]:
            j = names.index(name)
            dest[a:b, j] = prior.ie7.night_percentiles(dest[a:b, j:j + 1])[:, 0]
    dest.flush()
    remap = np.full(d.n, -1, np.int32)
    remap[indices] = np.arange(len(indices))
    query = [[int(remap[q]) if q >= 0 else -1 for q in qs] for qs in d.query]
    metadata = dict(names=names, days=days, slices=slices, codes=codes, query=query,
        scope_entries=[any(q >= 0 for q in qs) for qs in d.query],
        entries=d.entries, plan_sha256=prior.prior.file_sha(PLAN),
        upstream=prior.ie9.GATES, feature_sha256=prior.prior.file_sha(WORK / 'features.npy'),
        source_inputs={str(p.relative_to(ROOT)): prior.prior.file_sha(p) for p in
            (prior.WORK / 'features.json', prior.ie9.WORK / 'full_features.json',
             prior.ie7.WORK / 'full_pct.npy')},
        dataset_digest=d.meta['dataset_digest'], utc=datetime.now(timezone.utc).isoformat())
    prior.old.prior.write_json(WORK / 'features.json', metadata)
    print('prepared', dest.shape, 'RSS MiB', resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, flush=True)


class Data:
    def __init__(self, shuffled=False):
        self.meta = prior.ie7.read(WORK / 'features.json')
        self.names = self.meta['names']
        self.x = np.load(WORK / 'features.npy', mmap_mode='r')
        self.entries = self.meta['entries']
        self.query = self.meta['query']
        self.slices = {day: slice(*ab) for day, ab in self.meta['slices'].items()}
        if shuffled:
            rng = np.random.default_rng(SEED)
            mapping = np.arange(len(self.x))
            for sl in self.slices.values():
                mapping[sl] = rng.permutation(mapping[sl])
            self.query = [[int(mapping[q]) if q >= 0 else -1 for q in qs] for qs in self.query]

    def coverage(self, scores, years=None):
        ranks = np.full(len(self.x), prior.old.prior.SENTINEL, np.int32)
        selected = {}
        for day, sl in self.slices.items():
            if years is not None and day[:4] not in years:
                continue
            order = np.argsort(-scores[sl], kind='stable')
            ranks[sl.start + order] = np.arange(1, len(order) + 1)
            selected[day] = [self.meta['codes'][day][k] for k in order[:5]]
        which = [i for i, e in enumerate(self.entries) if years is None or e['entry_date'][:4] in years]
        coverage = prior.ie7.coverage([self.entries[i] for i in which], [self.query[i] for i in which],
            ranks, np.ones(len(self.x), bool))
        for i, row in zip(which, coverage['rows']):
            row['in_scope'] = self.meta['scope_entries'][i]
        rows = coverage['rows']
        primary = [r for r in rows if r['primary']]
        coverage.update(primary=prior.ie7.summarize(primary), all_entries=prior.ie7.summarize(rows),
            annual={y: dict(primary=prior.ie7.summarize([r for r in primary if r['entry_date'].startswith(y)]),
                all_entries=prior.ie7.summarize([r for r in rows if r['entry_date'].startswith(y)]))
                for y in (*prior.YEARS, '2026')},
            halfyear={h: prior.ie7.summarize([r for r in primary if prior.ie7.half(r['entry_date']) == h])
                for h in prior.HALVES})
        return coverage, selected, ranks

    def expected(self):
        widths = np.zeros(len(self.x), np.int32)
        for sl in self.slices.values():
            widths[sl] = sl.stop - sl.start
        return prior.ie9.random_expectation(self.entries, self.query, np.ones(len(self.x), bool), widths)


def baseline_scores(d):
    return (np.nan_to_num(d.x[:, d.names.index('after_inside')], nan=.5) +
            np.nan_to_num(d.x[:, d.names.index('near_ema9')], nan=.5)) / 2


def regime(value):
    if not np.isfinite(value):
        return 'unknown'
    return 'weak' if value < 1 / 3 else 'flat' if value < 2 / 3 else 'strong'


def observe():
    d = Data()
    coverage, selected, ranks = d.coverage(baseline_scores(d))
    rows, grouped = [], defaultdict(list)
    for entry, qs, result in zip(d.entries, d.query, coverage['rows']):
        nights = []
        for signal, q in zip(entry['systems']['h4'], qs):
            day = signal['date']
            if day not in d.slices:
                continue
            sl = d.slices[day]
            best = np.argsort(ranks[sl], kind='stable')[:5] + sl.start
            own = {n: float(d.x[q, d.names.index(n)]) if q >= 0 else None for n in VIEW}
            other = {n: float(np.nanmedian(d.x[best, d.names.index(n)])) if len(best) else None for n in VIEW}
            mv = float(d.x[sl.start, d.names.index('market_percentile')]) if sl.stop > sl.start else .5
            row = dict(day=day, retained=q >= 0, rank=int(ranks[q]) if q >= 0 else None,
                market=regime(mv), market_percentile=mv, own=own, top5=selected[day],
                top5_median=other, top5_features=[dict(code=code,
                    values={n: float(d.x[k, d.names.index(n)]) for n in VIEW})
                    for k, code in zip(best, selected[day])])
            nights.append(row)
        value = dict(id=entry['id'], code=entry['code'], entry_date=entry['entry_date'],
            setup=entry['setup'], primary=result['primary'], baseline_rank=result['best_rank'],
            in_scope=bool(any(q >= 0 for q in qs)), nights=nights)
        rows.append(value)
        if not result['primary']:
            continue
        valid = [r for r in nights if r['retained']]
        if valid:
            for n in VIEW:
                own = float(np.nanmedian([r['own'][n] for r in valid]))
                other = float(np.nanmedian([r['top5_median'][n] for r in valid]))
                for key in (entry['entry_date'][:4] + ':' + entry['setup'],
                            entry['entry_date'][:4] + ':' + valid[-1]['market']):
                    grouped[key, n].append((own, other))
    summary = []
    for (key, name), pairs in grouped.items():
        a = np.asarray(pairs)
        summary.append(dict(group=key, name=name, n=len(a), own=float(np.nanmedian(a[:, 0])),
            top5=float(np.nanmedian(a[:, 1])), difference=float(np.nanmedian(a[:, 0] - a[:, 1]))))
    write('observation', dict(rows=rows, groups=summary, baseline=coverage, expected=d.expected()))
    with (REPORTS / (PREFIX + 'observation.csv')).open('w') as stream:
        fields = ['id', 'code', 'entry_date', 'setup', 'primary', 'baseline_rank', 'retained_nights',
                  'market', 'quiet_difference', 'history_difference', 'peer_difference', 'pool_streak_difference']
        writer = csv.DictWriter(stream, fields)
        writer.writeheader()
        for row in rows:
            if not row['primary']:
                continue
            valid = [r for r in row['nights'] if r['retained']]
            out = {k: row[k] for k in fields[:6]}
            out.update(retained_nights=len(valid), market=valid[-1]['market'] if valid else '')
            for field, name in (('quiet_difference', 'volume_rebound'), ('history_difference', 'h4_history'),
                                ('peer_difference', 'peer_rank'), ('pool_streak_difference', 'pool_streak')):
                out[field] = round(float(np.nanmedian([r['own'][name] - r['top5_median'][name]
                    for r in valid])), 3) if valid else ''
            writer.writerow(out)
    print('observed', len(rows), 'entries', flush=True)


def basis_value(x, names, rule):
    """A preference is a function of one night's observable columns only."""
    if 'and' in rule:
        return np.prod([basis_value(x, names, r) for r in rule['and']], axis=0)
    a = x[:, names.index(rule['name'])]
    finite = np.isfinite(a)
    shape = rule['shape']
    if shape == 'up':
        value = a
    elif shape == 'down':
        value = 1 - a
    elif shape == 'middle':
        value = 1 - 2 * np.abs(a - .5)
    elif shape == 'band':
        low = a > rule['low'] if rule.get('low_open') else a >= rule['low']
        high = a < rule['high'] if rule.get('high_open') else a <= rule['high']
        value = low & high
    else:
        raise ValueError('unknown preference shape')
    return np.where(finite, value, 0.).astype(np.float32)


def predict(x, names, model):
    score = np.zeros(len(x), np.float64)
    for term in model['terms']:
        score += term['weight'] * basis_value(x, names, term['rule'])
    return score


def score_years(d, model, years=None):
    scores = np.zeros(len(d.x), np.float64)
    for day, sl in d.slices.items():
        if years is None or day[:4] in years:
            scores[sl] = predict(d.x[sl], d.names, model)
    return scores


def training_bundle(d, years):
    indices = [i for i, e in enumerate(d.entries)
               if e['entry_date'][:4] in years and e['target']['tier'] == 'primary']
    days = sorted({s['date'] for i in indices for s, q in
                   zip(d.entries[i]['systems']['h4'], d.query[i]) if q >= 0})
    rows = np.concatenate([np.arange(d.slices[day].start, d.slices[day].stop) for day in days])
    mapping = {int(q): i for i, q in enumerate(rows)}
    nights = {}
    for day in days:
        sl = d.slices[day]
        a = mapping[sl.start]
        nights[day] = np.arange(a, a + sl.stop - sl.start)
    bags = [[(nights[s['date']], mapping[q]) for s, q in
             zip(d.entries[i]['systems']['h4'], d.query[i]) if q >= 0] for i in indices]
    return dict(x=np.asarray(d.x[rows]), bags=bags, rows=rows,
        years=[d.entries[i]['entry_date'][:4] for i in indices], train_years=sorted(years),
        ids=[d.entries[i]['id'] for i in indices])


def candidate_ranks(bundle, score, values, weight):
    """Evaluate all preferences in bounded night-by-candidate arrays, never stock pairs."""
    result = np.full((len(bundle['bags']), values.shape[1]), prior.old.prior.SENTINEL, np.int32)
    for i, bag in enumerate(bundle['bags']):
        for rows, q in bag:
            trial = score[rows, None] + weight * values[rows]
            own = score[q] + weight * values[q]
            ahead = (trial > own) | ((trial == own) & (rows[:, None] < q))
            result[i] = np.minimum(result[i], 1 + ahead.sum(axis=0))
    return result


def objectives(bundle, ranks):
    hits = (ranks <= 5).sum(axis=0)
    rates = [np.mean(ranks[np.array(bundle['years']) == y] <= 5, axis=0)
             for y in bundle['train_years']]
    minimum = np.min(rates, axis=0)
    loss = np.log1p(np.minimum(ranks, 100) / 5).sum(axis=0)
    return hits, minimum, -loss


def best_index(metrics):
    # Stable candidate order is the last tie breaker.
    return max(range(len(metrics[0])), key=lambda j: tuple(float(m[j]) for m in metrics))


def make_candidates(bundle, names, spec, registration):
    core = registration['core_features']
    features = core if spec['universe'] == 'core' else names
    features = [n for n in features if n != 'market_g21' and
        np.mean(np.isfinite(bundle['x'][:, names.index(n)])) >= .8]
    rules = []
    for name in features:
        for shape in ('up', 'down', 'middle'):
            if name.startswith('state_') and shape == 'middle':
                continue
            rules.append(dict(name=name, shape=shape))
        if spec['bands']:
            for cut in registration['cutoffs']:
                rules.extend((dict(name=name, shape='band', low=0., high=cut),
                              dict(name=name, shape='band', low=cut, high=1.)))
            for lo, hi in registration['middle_bands']:
                rules.append(dict(name=name, shape='band', low=lo, high=hi))
    if spec.get('interactions') == 'pairs':
        binary = [r for r in rules if r['shape'] == 'band']
        columns = np.column_stack([basis_value(bundle['x'], names, r) for r in binary])
        metrics = objectives(bundle, candidate_ranks(bundle, np.zeros(len(columns)), columns, 1.))
        ordered = sorted(range(len(binary)), key=lambda j: tuple(float(m[j]) for m in metrics), reverse=True)
        chosen, counts = [], defaultdict(int)
        for j in ordered:
            r = binary[j]
            if counts[r['name']] < 2:
                chosen.append(r)
                counts[r['name']] += 1
            if len(chosen) == registration['interaction_shortlist']:
                break
        rules.extend(dict(**{'and': [a, b]}) for i, a in enumerate(chosen) for b in chosen[i + 1:]
                     if a['name'] != b['name'])
    elif spec.get('interactions') == 'state':
        gates = [dict(name=n, shape='band', low=1., high=1.) for n in NEW[4:7]]
        gates += [dict(name='market_percentile', shape='band', low=0., high=1 / 3, high_open=True),
                  dict(name='market_percentile', shape='band', low=1 / 3, high=2 / 3, high_open=True),
                  dict(name='market_percentile', shape='band', low=2 / 3, high=1.)]
        plain = list(rules)
        rules.extend({'and': [g, r]} for g in gates for r in plain
                     if not r['name'].startswith('state_'))
    return rules


def fit_model(d, years, spec, registration):
    if spec['id'] == 'quiet':
        return dict(id=spec['id'], terms=[dict(weight=1., rule=dict(name=n, shape=s)) for n, s in
            (('rs1', 'down'), ('fresh_pot', 'down'), ('volume_rebound', 'down'), ('h4_history', 'up'))])
    bundle = training_bundle(d, years)
    rules = make_candidates(bundle, d.names, spec, registration)
    values = np.column_stack([basis_value(bundle['x'], d.names, r) for r in rules])
    score = np.zeros(len(values), np.float64)
    chosen, weights, trace = [], [], []

    def search(base, excluded):
        best = None
        for weight in registration['weights']:
            metrics = objectives(bundle, candidate_ranks(bundle, base, values, weight))
            metrics[0][excluded] = -1
            j = best_index(metrics)
            key = tuple(float(m[j]) for m in metrics)
            if best is None or key > best[0]:
                best = key, j, weight
        return best

    for step in range(spec['terms']):
        key, j, weight = search(score, chosen)
        chosen.append(j)
        weights.append(weight)
        score += weight * values[:, j]
        trace.append(dict(step=step, objective=key, rule=rules[j], weight=weight))
        print('fit', sorted(years), spec['id'], step + 1, key, flush=True)
    for sweep in range(registration['refinement_passes']):
        for k in range(len(chosen)):
            base = score - weights[k] * values[:, chosen[k]]
            current = objectives(bundle, candidate_ranks(bundle, score, values[:, :1] * 0, 0.))
            old_key = tuple(float(m[0]) for m in current)
            key, j, weight = search(base, chosen[:k] + chosen[k + 1:])
            if key > old_key:
                chosen[k], weights[k] = j, weight
                score = base + weight * values[:, j]
                trace.append(dict(sweep=sweep, slot=k, objective=key, rule=rules[j], weight=weight))
        print('refine', sorted(years), spec['id'], sweep + 1, flush=True)
    terms = [dict(rule=rules[j], weight=w) for j, w in zip(chosen, weights)]
    model = dict(id=spec['id'], terms=terms)
    # Delete a term if coverage and the worst training year do not decline.
    while len(model['terms']) > 1:
        current = objectives(bundle, candidate_ranks(bundle, predict(bundle['x'], d.names, model), values[:, :1] * 0, 0.))
        old_key = tuple(float(m[0]) for m in current[:2])
        for k in range(len(model['terms'])):
            trial = dict(model, terms=model['terms'][:k] + model['terms'][k + 1:])
            metrics = objectives(bundle, candidate_ranks(bundle, predict(bundle['x'], d.names, trial), values[:, :1] * 0, 0.))
            if tuple(float(m[0]) for m in metrics[:2]) >= old_key:
                model = trial
                break
        else:
            break
    model.update(trace=trace, training_ids=bundle['ids'], candidates=len(rules))
    return model


def selection_key(result, years):
    c = result['coverage']
    return (c['primary']['hits']['5'], min(prior.ie7.rate(c['annual'][y]['primary']) for y in years),
            -len(result['model']['terms']), c['all_entries']['hits']['5'])


def fit_suite(d, years, label):
    registration = prior.ie7.read(REGISTRATION)
    results = []
    for spec in registration['models']:
        model = fit_model(d, years, spec, registration)
        score = score_years(d, model, years)
        coverage, _, _ = d.coverage(score, years)
        result = dict(model=model, coverage=coverage)
        results.append(result)
        write('fit_' + label + '_' + spec['id'], result)
        print('candidate complete', label, spec['id'], selection_key(result, years), flush=True)
        gc.collect()
    winner = max(results, key=lambda r: selection_key(r, years))
    return dict(results=results, winner=winner, years=sorted(years),
                registration_sha256=prior.prior.file_sha(REGISTRATION))


def fit():
    d = Data()
    result = fit_suite(d, set(prior.YEARS), 'combined')
    write('fit', result)
    write('frozen', dict(model=result['winner']['model'], upstream=prior.ie9.GATES,
        plan_sha256=prior.prior.file_sha(PLAN), registration_sha256=prior.prior.file_sha(REGISTRATION),
        source_sha256=prior.prior.file_sha(Path(__file__)), utc=datetime.now(timezone.utc).isoformat()))


def crossyear():
    d = Data()
    rows = []
    for train, test in (prior.YEARS, prior.YEARS[::-1]):
        suite = fit_suite(d, {train}, train)
        model = suite['winner']['model']
        coverage, selected, _ = d.coverage(score_years(d, model, {test}), {test})
        rows.append(dict(train=train, test=test, suite=suite, coverage=coverage, selected=selected))
        write('crossyear_' + train, rows[-1])
    write('crossyear', rows)


def shuffle():
    d = Data(shuffled=True)
    suite = fit_suite(d, set(prior.YEARS), 'shuffle')
    model = suite['winner']['model']
    coverage, _, _ = d.coverage(predict(d.x, d.names, model))
    write('shuffle', dict(seed=SEED, suite=suite, coverage=coverage))


def final():
    frozen = read('frozen')
    if (REPORTS / (PREFIX + 'final.json')).exists():
        raise ValueError('the final reference evaluation is already saved')
    d = Data()
    coverage, selected, ranks = d.coverage(predict(d.x, d.names, frozen['model']))
    write('final', dict(coverage=coverage, selected=selected, model=frozen['model'], expected=d.expected()))
    np.save(WORK / 'final_ranks.npy', ranks)
    rng_results = []
    for seed in range(SEED + 100, SEED + 130):
        rng = np.random.default_rng(seed)
        c, _, _ = d.coverage(rng.random(len(d.x)))
        rng_results.append(dict(seed=seed, coverage=c))
    write('random', dict(expected=d.expected(), repetitions=rng_results))
    account_data = prior.Data(full=True)
    accounts = account_data.accounts(selected)
    write('accounts', accounts)
    print('final', coverage['primary'], 'RSS MiB', resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=('prepare', 'observe', 'fit', 'crossyear', 'shuffle', 'final'))
    args = parser.parse_args()
    WORK.mkdir(exist_ok=True)
    globals()[args.stage]()


if __name__ == '__main__':
    main()
