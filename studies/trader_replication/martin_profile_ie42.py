"""IE42: regime profiles = one shared profile + small up / pullback corrections.

Fit on 2024-25 only, write the profile, label each item explainable or not in
ie42_work/explain.json, then evaluate 2026 once:
python -m studies.trader_replication.martin_profile_ie29 --library std_v1_1 --train-edges \
  --shrink --missing-zero --drop '' --learn 0,1,2 --bins 3,5,10 --max-attrs 7 --cooldown 10 \
  --tag ie42 --ie42-stage fit|evaluate
"""
import json
import resource
import time

import numpy as np
import pandas as pd

from studies.trader_replication import mainleg
from studies.trader_replication.martin_profile_ie40 import GAP

WORK = GAP / 'ie42_work'
OUTPUT = GAP / 'strong_continue_ie42.json'
TRAIN_HALVES = ('2024H1', '2024H2', '2025H1', '2025H2')
YEARS = ('2024', '2025', '2026')
REGIMES = ('up', 'pullback', 'weak')
CORRECTION_ITEMS = 3
AGREE_R, AGREE_SPREAD = .6, .5
MIN_CORRECTION_TARGETS = 5
T0 = time.monotonic()


def log(*values):
    print(f'[{time.monotonic()-T0:6.0f}s]', *values, flush=True)


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=1, default=str), encoding='utf-8')


def qqq_regime(ctx):
    """His market read: weak = below EMA50; pullback = back to within 1% of EMA21 (or under it); else up."""
    q = pd.Series(np.asarray(ctx['qqq_np'], float))
    e21 = q.ewm(span=21, adjust=False).mean().to_numpy()
    e50 = q.ewm(span=50, adjust=False).mean().to_numpy()
    q = q.to_numpy()
    return np.where(q < e50, 2, np.where(q <= e21*1.01, 1, 0))


def regime_table(ctx, train, mask):
    """Same bin table as the shared profile, with pool and his rows limited to one regime."""
    lookup, learn = ctx['lookup'], ctx['LEARN']
    groups = []
    for code, i0, _, primary in train:
        if primary:
            rows = [lookup[(code, i0+w)] for w in learn if (code, i0+w) in lookup and mask[lookup[(code, i0+w)]]]
            if rows:
                groups.append(rows)
    tables = {key: ctx['bin_table'](bins, edges, mask, groups) for key, (bins, edges) in ctx['BINS'].items()}
    return tables, len(groups)


def fit_correction(ctx, train, base, tables, rows):
    """Forward add up to three items scored only on this regime's nights, tune weights, drop idle items."""
    evaluate, score, ranks_of, better = ctx['evaluate'], ctx['score'], ctx['ranks_of'], ctx['better']

    def value(model):
        s = base.copy()
        if model:
            s[rows] += score(model, tables)[rows]
        return evaluate(ranks_of(s), train)

    model, best = {}, value({})
    path = [({}, best)]
    while len(model) < CORRECTION_ITEMS:
        trial = []
        for k in ctx['USE']:
            if any(key[0] == k for key in model):
                continue
            for q in ctx['BIN_CHOICES']:
                cand = {**model, (k, q): 1}
                v = value(cand)
                trial.append((ctx['OBJ'](v), -q, -k, cand, v))
        trial.sort(key=lambda x: x[:3], reverse=True)
        model = trial[0][3]
        path.append((dict(model), trial[0][4]))
        log('correction step', len(model), trial[0][4])
    model, best = max(path, key=lambda x: ctx['OBJ'](x[1]))
    model = dict(model)
    for _ in range(2):
        changed = False
        for key in list(model):
            for w in ctx['WEIGHTS']:
                if w != model[key]:
                    v = value({**model, key: w})
                    if better(v, best):
                        model[key], best, changed = w, v, True
        model = {k: w for k, w in model.items() if w}
        if not changed:
            break
    for key in sorted(model, key=lambda k: model[k]):
        trial = {k: w for k, w in model.items() if k != key}
        v = value(trial)
        if (ctx['OBJ'](v) >= ctx['OBJ'](best)) if ctx['args'].quality_objective else v[0] >= best[0]:
            model, best = trial, v
    return model, best


def combined(ctx, shared, corrections, tables):
    s = ctx['score'](shared, tables['shared'])
    for name, model in corrections.items():
        if model:
            rows = tables['rows'][name]
            s[rows] += ctx['score'](model, tables[name])[rows]
    return s


def build(ctx, train, fit=None):
    """Tables are a pure function of the 2024-25 targets; refitting is only done in the fit stage."""
    regime = qqq_regime(ctx)
    row_regime = regime[ctx['row_day']]
    shared_tables = ctx['tables_for'](train)
    tables = dict(shared=shared_tables, rows={}, n={})
    for g, name in enumerate(REGIMES[:2]):
        mask = ctx['TRAIN_MASK'] & (row_regime == g)
        tables[name], tables['n'][name] = regime_table(ctx, train, mask)
        tables['rows'][name] = np.flatnonzero(row_regime == g)
    if fit is None:
        return regime, tables, None
    shared, _, shared_fit = ctx['fit'](train)
    log('shared', shared_fit, shared)
    corrections, base = {}, ctx['score'](shared, shared_tables)
    ctx['FITTING'] = True
    for name in REGIMES[:2]:
        if tables['n'][name] < MIN_CORRECTION_TARGETS:
            corrections[name] = {}
            continue
        corrections[name], best = fit_correction(ctx, train, base, tables[name], tables['rows'][name])
        log('correction', name, best, corrections[name])
        rows = tables['rows'][name]
        if corrections[name]:
            base[rows] += ctx['score'](corrections[name], tables[name])[rows]
    ctx['FITTING'] = False
    return regime, tables, dict(shared=shared, corrections=corrections)


def coverage(ctx, scores, targets, regime, K=3, H=3):
    """Hits by entry year and by the regime of the night before his entry."""
    ranks = ctx['ranks_of'](scores)
    hits = ctx['covered'](ctx['picks'](ranks, K, H), targets, H)
    table = {}
    for hit, (code, i0, half, primary) in zip(hits, targets):
        if not primary:
            continue
        year, name = half[:4], REGIMES[regime[i0-1]]
        for key in (year, f'{year} {name}'):
            row = table.setdefault(key, dict(hit=0, n=0))
            row['hit'] += bool(hit)
            row['n'] += 1
    return table, hits, ranks


def items(ctx, model):
    return [dict(name=ctx['NAMES'][k], bins=q, weight=w) for (k, q), w in model.items()]


def unpack(ctx, rows):
    return {(ctx['NAMES'].index(r['name']), r['bins']): r['weight'] for r in rows}


def profile(ctx, model, table, pool_rows, groups):
    out = {}
    for (k, q), w in model.items():
        bins, e = ctx['BINS'][(k, q)]
        labels = ([f'< {e[0]:.3g}'] + [f'{e[i]:.3g} – {e[i+1]:.3g}' for i in range(len(e)-1)]
                  + [f'>= {e[-1]:.3g}', 'missing']) if len(e) else ['all', 'missing']
        nb = len(e)+2
        pool = np.bincount(bins[pool_rows], minlength=nb)
        his = np.zeros(nb)
        for g in groups:
            np.add.at(his, bins[g], 1/len(g))
        out[ctx['NAMES'][k]] = dict(weight=w, bins=[dict(bin=labels[i], pool=round(pool[i]/max(pool.sum(), 1), 3),
            his=round(his[i]/max(his.sum(), 1e-9), 3), score=round(float(table[(k, q)][i]), 2)) for i in range(nb) if pool[i]])
    return out


def regime_groups(ctx, train, mask):
    lookup = ctx['lookup']
    groups = [[lookup[(c, i0+w)] for w in ctx['LEARN'] if (c, i0+w) in lookup and mask[lookup[(c, i0+w)]]]
              for c, i0, _, p in train if p]
    return [g for g in groups if g]


def fit_stage(ctx):
    WORK.mkdir(exist_ok=True)
    train = [t for t in ctx['REAL'] if t[2] in TRAIN_HALVES]
    regime, tables, model = build(ctx, train, fit=True)
    train_mask = ctx['TRAIN_MASK']
    row_regime = regime[ctx['row_day']]
    shared_scores = ctx['score'](model['shared'], tables['shared'])
    regime_scores = combined(ctx, model['shared'], model['corrections'], tables)
    result = dict(config=vars(ctx['args']), regime_rule='weak: QQQ < EMA50; pullback: QQQ <= 1.01*EMA21; up: otherwise; target regime = night before entry',
                  nights={name: int(sum(regime[ctx['cpos'][d]] == g for d in ctx['days'] if d[:4] in ('2024', '2025')))
                          for g, name in enumerate(REGIMES)},
                  learn_targets=tables['n'], model=dict(shared=items(ctx, model['shared']),
                  corrections={k: items(ctx, v) for k, v in model['corrections'].items()}))
    for label, scores in (('shared_only', shared_scores), ('regime', regime_scores)):
        main, _, _ = coverage(ctx, scores, train, regime)
        four, _, _ = coverage(ctx, scores, train, regime, K=2, H=2)
        result[label] = dict(main=main, four=four)
        log(label, main)
    groups = regime_groups(ctx, train, train_mask)
    result['profile'] = dict(shared=profile(ctx, model['shared'], tables['shared'], train_mask, groups))
    for g, name in enumerate(REGIMES[:2]):
        mask = train_mask & (row_regime == g)
        result['profile'][name] = profile(ctx, model['corrections'][name], tables[name], mask,
                                          regime_groups(ctx, train, mask))
    _, hits, ranks = coverage(ctx, regime_scores, train, regime)
    lookup = ctx['lookup']
    result['targets'] = [dict(code=c, entry=ctx['cal'][i0], regime=REGIMES[regime[i0-1]], hit=bool(h),
        best_rank=min((int(ranks[lookup[(c, j)]]) for j in range(i0-6, i0+3) if (c, j) in lookup), default=None))
        for h, (c, i0, _, p) in zip(hits, train) if p]
    result['peak_rss_mb'] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss // 1024
    write(WORK/'fit.json', result)
    log('FIT_DONE', result['regime']['main'])


def evaluate_stage(ctx):
    if OUTPUT.exists():
        raise ValueError('2026 is evaluated once; output already exists')
    fit = json.loads((WORK/'fit.json').read_text(encoding='utf-8'))
    explain = json.loads((WORK/'explain.json').read_text(encoding='utf-8'))
    train = [t for t in ctx['REAL'] if t[2] in TRAIN_HALVES]
    regime, tables, _ = build(ctx, train)
    shared = unpack(ctx, fit['model']['shared'])
    corrections = {k: unpack(ctx, v) for k, v in fit['model']['corrections'].items()}
    unexplained = {(part, row['name']) for part, rows in explain.items() for row in rows if not row['explainable']}
    keep = lambda part, model: {k: w for k, w in model.items() if (part, ctx['NAMES'][k[0]]) not in unexplained}
    versions = dict(regime=combined(ctx, shared, corrections, tables),
                    shared_only=ctx['score'](shared, tables['shared']),
                    regime_explainable=combined(ctx, keep('shared', shared),
                                                {k: keep(k, v) for k, v in corrections.items()}, tables),
                    ie9=ctx['_score'].astype(np.float32))
    result = dict(fit=fit, explain=explain, versions={})
    for name, scores in versions.items():
        main, hits, ranks = coverage(ctx, scores, ctx['REAL'], regime)
        four, _, _ = coverage(ctx, scores, ctx['REAL'], regime, K=2, H=2)
        result['versions'][name] = dict(main=main, four=four)
        log(name, {y: main[y] for y in YEARS})
        if name == 'regime':
            result['targets_2026'] = [dict(code=c, entry=ctx['cal'][i0], regime=REGIMES[regime[i0-1]], hit=bool(h))
                                      for h, (c, i0, half, p) in zip(hits, ctx['REAL']) if p and half[:4] == '2026']
    ablation = []
    for part, model in (('shared', shared), *corrections.items()):
        for key in model:
            rest = {k: w for k, w in model.items() if k != key}
            s = (combined(ctx, rest, corrections, tables) if part == 'shared'
                 else combined(ctx, shared, {**corrections, part: rest}, tables))
            main, _, _ = coverage(ctx, s, ctx['REAL'], regime)
            ablation.append(dict(part=part, drop=ctx['NAMES'][key[0]], yearly={y: main.get(y) for y in YEARS}))
            log('ablate', part, ctx['NAMES'][key[0]], ablation[-1]['yearly'])
    result['ablation'] = ablation
    write(OUTPUT, result)
    log('FINAL_2026_ONCE', {k: v['main'].get('2026') for k, v in result['versions'].items()})


def mainleg_targets(ctx):
    """IE43: one target per big-winner leg; `covered` = we bought it while half of his move was still ahead."""
    prices = {}
    for code in {t[0] for t in ctx['REAL']}:
        with np.load(GAP/'ie5_work/stocks'/(code+'.npz')) as z:
            prices[code] = {k: z[k].astype(float) for k in ('o', 'h', 'l', 'c')}
    legs = mainleg.legs([(code, i0, k) for k, (code, i0, _, _) in enumerate(ctx['REAL'])], prices)
    qualify, targets = {}, []
    for leg in legs:
        first = leg['entries'][0]['index']
        rows = mainleg.coverage({t: {leg['code']} for t in range(first-4, leg['peak']-1)}, [leg], prices)[0]['buys']
        qualify[(leg['code'], first)] = [r['fill']-1 for r in rows if r['ok']]
        targets.append((leg['code'], first, ctx['REAL'][leg['entries'][0]['label']][2], True))
    ctx['original_real'], ctx['REAL'] = ctx['REAL'], targets
    ctx['qualify'] = qualify
    ctx['covered'] = lambda sel, tg, H: [any(c in sel.get(t, ()) for t in qualify[(c, i0)]) for c, i0, _, _ in tg]
    log('main legs', len(targets), {y: sum(t[2][:4] == y for t in targets) for y in YEARS})


def quality_objective(ctx):
    """IE46: rank fits by (covered legs, share of picks that double within 60 sessions, median 60-session run).
    A pick's run only counts when its 60-session window closes by 2025-12-31, so 2026 prices never enter fitting."""
    cal, row_day, codes = ctx['cal'], ctx['row_day'], ctx['codes']
    run = np.full(ctx['N'], np.nan, np.float32)
    last = max(i for i, d in enumerate(cal) if d <= '2025-12-31')
    for code in np.unique(codes):
        rows = np.flatnonzero(codes == code)
        with np.load(GAP/'ie5_work/stocks'/(code+'.npz')) as z:
            o, h = z['o'].astype(float), z['h'].astype(float)
        for r in rows:
            f = row_day[r]+1
            if f+60 <= last and np.isfinite(o[f]) and o[f] > 0:
                run[r] = np.nanmax(h[f:f+61])/o[f]-1
    base, lookup, picks, covered = ctx['evaluate'], ctx['lookup'], ctx['picks'], ctx['covered']

    def evaluate(r, targets, K=3, H=3):
        selected = picks(r, K, H)
        if ctx['FITTING']:
            halves = {t[2] for t in targets}
            selected = {j: v for j, v in selected.items() if cal[j][:4]+('H1' if cal[j][5:7] <= '06' else 'H2') in halves}
        hit = covered(selected, targets, H)
        got = run[[lookup[(c, j)] for j, v in selected.items() for c in v]]
        got = got[np.isfinite(got)]
        return (sum(x for x, t in zip(hit, targets) if t[3]), sum(hit),
                round(float(np.mean(got >= 1)), 4) if len(got) else 0., round(float(np.median(got)), 4) if len(got) else 0.)
    ctx['evaluate'] = evaluate
    ctx['OBJ'] = lambda v: (v[0], v[2], v[3])
    ok = np.isfinite(run) & (np.asarray([cal[d][:4] for d in row_day]) <= '2025')
    log('quality objective: pool rows with a closed run', int(ok.sum()), 'pool doubles', round(float(np.mean(run[ok] >= 1)), 4),
        'median', round(float(np.median(run[ok])), 4))


def run_stage(ctx, stage):
    global WORK, OUTPUT
    WORK, OUTPUT = GAP/f"{ctx['args'].tag}_work", GAP/f"strong_continue_{ctx['args'].tag}.json"
    if not (ctx['args'].shrink and ctx['args'].missing_zero and ctx['args'].train_edges):
        raise ValueError('IE42 requires --shrink --missing-zero --train-edges')
    if ctx['args'].mainleg_objective:
        if stage == 'audit':
            raise ValueError('audit already measures main legs')
        mainleg_targets(ctx)
    if ctx['args'].quality_objective:
        quality_objective(ctx)
    log('nights', ctx['N'], 'rows; library', len(ctx['NAMES']), 'items')
    dict(fit=fit_stage, evaluate=evaluate_stage, audit=audit_stage, breadth=breadth_stage, quality=quality_stage, scorecard=scorecard_stage, agree=agree_stage)[stage](ctx)


def audit_stage(ctx):
    """Main-leg coverage (mainleg.py) of the frozen IE42 profile and of IE9 under the same nightly budget."""
    fit = json.loads((WORK/'fit.json').read_text(encoding='utf-8'))
    train = [t for t in ctx['REAL'] if t[2] in TRAIN_HALVES]
    regime, tables, _ = build(ctx, train)
    profile = combined(ctx, unpack(ctx, fit['model']['shared']),
                       {k: unpack(ctx, v) for k, v in fit['model']['corrections'].items()}, tables)
    prices = {}
    for path in sorted((GAP/'ie5_work/stocks').glob('*.npz')):
        with np.load(path) as z:
            prices[path.stem] = {k: z[k].astype(float) for k in ('o', 'h', 'l', 'c')}
    entries = [(code, i0, e['id']) for e, (code, i0, _, _) in zip(ctx['d'].entries, ctx['REAL'])]
    legs = mainleg.legs(entries, prices)
    in_leg = {x['label'] for leg in legs for x in leg['entries']}
    others = [x for x in dict.fromkeys((c, i, label) for c, i, label in entries) if x[2] not in in_leg]
    pool = set(ctx['lookup'])
    base = mainleg.precision({t: {c for c, n in pool if n == t} for t in {n for _, n in pool}}, prices)
    out = dict(rule=dict(lead=3, keep=.5, lag=2, stop=.03, horizon=60, big=.30, new_per_night=3, cooldown=10),
               legs=len(legs), pool_precision=base, in_sample=list(YEARS[:2]), holdout=YEARS[2])
    for label, scores in (('ie42', profile), ('ie9', ctx['_score'].astype(np.float32))):
        buys = ctx['picks'](ctx['ranks_of'](scores), 3, 3)
        rows = mainleg.coverage(buys, legs, prices, pool=pool)
        years = [ctx['cal'][r['first']][:4] for r in rows]
        hits = mainleg.entry_hits(buys, others)
        out[label] = dict(summary=mainleg.summary(rows, years), precision=mainleg.precision(buys, prices),
                          others={y: f"{sum(h for h, x in zip(hits, others) if ctx['cal'][x[1]][:4] == y)}/"
                                     f"{sum(ctx['cal'][x[1]][:4] == y for x in others)}" for y in YEARS},
                          legs=[dict(r, first=ctx['cal'][r['first']], peak=ctx['cal'][r['peak']]) for r in rows])
        log(label, out[label]['summary'], out[label]['precision'], 'others', out[label]['others'])
    log('pool precision', base)
    write(WORK/'audit_mainleg.json', out)


def breadth_stage(ctx):
    """How wide is the net: picks per night, distinct names, and how much of the pool we cycle through per leg."""
    fit = json.loads((WORK/'fit.json').read_text(encoding='utf-8'))
    train = [t for t in ctx['REAL'] if t[2] in TRAIN_HALVES]
    _, tables, _ = build(ctx, train)
    scores = combined(ctx, unpack(ctx, fit['model']['shared']),
                      {k: unpack(ctx, v) for k, v in fit['model']['corrections'].items()}, tables)
    cal, pool = ctx['cal'], set(ctx['lookup'])
    out = {}
    for label, s in (('ie43', scores), ('ie9', ctx['_score'].astype(np.float32))):
        buys = ctx['picks'](ctx['ranks_of'](s), 3, 3)
        per_night = [len(v) for v in buys.values()]
        years = {y: [t for t in buys if cal[t][:4] == y] for y in YEARS}
        rows = []
        for code, first, half, _ in ctx['REAL']:
            nights = [t for t in ctx['qualify'][(code, first)]]
            if not nights:
                continue
            window = range(min(nights), max(nights)+1)
            picked = set().union(*(buys.get(t, set()) for t in window))
            inpool = {c for c, t in pool if t in window}
            rows.append(dict(year=half[:4], nights=len(window), picked=len(picked), pool=len(inpool),
                             hit=code in picked))
        out[label] = dict(per_night=dict(min=min(per_night), max=max(per_night), mean=round(float(np.mean(per_night)), 2)),
                          per_year={y: dict(buys=sum(len(buys[t]) for t in v), names=len(set().union(*(buys[t] for t in v))) if v else 0)
                                    for y, v in years.items()},
                          legs={y: dict(window_nights=float(np.median([r['nights'] for r in rows if r['year'] == y])),
                                        picked_in_window=float(np.median([r['picked'] for r in rows if r['year'] == y])),
                                        pool_in_window=float(np.median([r['pool'] for r in rows if r['year'] == y])),
                                        share=round(float(np.median([r['picked']/r['pool'] for r in rows if r['year'] == y])), 2))
                                for y in YEARS})
        log(label, json.dumps(out[label], ensure_ascii=False))
    pool_per_night = [sl.stop-sl.start for sl in ctx['SL'].values()]
    log('pool per night median', float(np.median(pool_per_night)))
    write(WORK/'breadth.json', out)


def quality_stage(ctx):
    """What our signals are worth on their own: the run after each next-open buy, versus the whole pool."""
    fit = json.loads((WORK/'fit.json').read_text(encoding='utf-8'))
    train = [t for t in ctx['REAL'] if t[2] in TRAIN_HALVES]
    _, tables, _ = build(ctx, train)
    scores = combined(ctx, unpack(ctx, fit['model']['shared']),
                      {k: unpack(ctx, v) for k, v in fit['model']['corrections'].items()}, tables)
    cal, prices = ctx['cal'], {}
    for path in sorted((GAP/'ie5_work/stocks').glob('*.npz')):
        with np.load(path) as z:
            prices[path.stem] = {k: z[k].astype(float) for k in ('o', 'h')}

    def runs(pairs, horizon):
        out = {y: [] for y in YEARS}
        for code, t in pairs:
            p, f = prices.get(code), t+1
            if cal[t][:4] not in out or p is None or f+horizon >= len(p['o']) or not (np.isfinite(p['o'][f]) and p['o'][f] > 0):
                continue
            out[cal[t][:4]].append(np.nanmax(p['h'][f:f+horizon+1])/p['o'][f]-1)
        return {y: dict(n=len(v), median=round(float(np.median(v))*100, 1), ge30=round(float(np.mean(np.array(v) >= .3))*100, 1),
                        ge100=round(float(np.mean(np.array(v) >= 1))*100, 1)) for y, v in out.items() if v}
    out = dict(pool={h: runs(ctx['lookup'], h) for h in (20, 60)})
    for label, s in (('ie43', scores), ('ie9', ctx['_score'].astype(np.float32))):
        buys = ctx['picks'](ctx['ranks_of'](s), 3, 3)
        pairs = [(c, t) for t, v in buys.items() for c in v]
        out[label] = {h: runs(pairs, h) for h in (20, 60)}
    for k, v in out.items():
        log(k, json.dumps(v, ensure_ascii=False))
    write(WORK/'quality.json', out)


def scorecard_stage(ctx):
    """Selection scorecard (METHOD_CN §11): main-leg coverage, net width, forward runs — IE43, IE9, and IE45 =
    IE43 rank + IE9 rank (no weights fitted)."""
    fit = json.loads((WORK/'fit.json').read_text(encoding='utf-8'))
    train = [t for t in ctx['REAL'] if t[2] in TRAIN_HALVES]
    _, tables, _ = build(ctx, train)
    profile = combined(ctx, unpack(ctx, fit['model']['shared']),
                       {k: unpack(ctx, v) for k, v in fit['model']['corrections'].items()}, tables)
    prices = {}
    for path in sorted((GAP/'ie5_work/stocks').glob('*.npz')):
        with np.load(path) as z:
            prices[path.stem] = {k: z[k].astype(float) for k in ('o', 'h', 'l', 'c')}
    cal, pool = ctx['cal'], set(ctx['lookup'])
    legs = mainleg.legs([(c, i0, k) for k, (c, i0, _, _) in enumerate(ctx['original_real'])], prices)
    spans = mainleg.windows(legs, prices)
    years = [t[2][:4] for t in ctx['REAL']]
    ie43, ie9 = ctx['ranks_of'](profile), ctx['ranks_of'](ctx['_score'].astype(np.float32))
    versions = dict(profile=ie43, ie9=ie9, slots_2_1=(ie43, ie9))
    ctx['SLOTS'] = (2, 1)                          # tuples: 2 nightly names from the profile, then 1 from IE9
    out = {}
    for label, ranks in versions.items():
        buys = ctx['picks'](ranks, 3, 3)
        hits = ctx['covered'](buys, ctx['REAL'], 3)
        nets = mainleg.net_share(buys, spans, pool)
        row = {}
        for y in YEARS:
            part = [i for i, x in enumerate(years) if x == y]
            fw = mainleg.forward({t: v for t, v in buys.items() if cal[t][:4] == y}, prices)
            row[y] = dict(covered=f'{sum(hits[i] for i in part)}/{len(part)}',
                          net=round(float(np.median([nets[i] for i in part if nets[i] is not None]))*100),
                          run_median=round(fw['median']*100, 1), ge100=round(fw['ge100']*100, 1), runs=fw['n'])
        row['legs'] = [[t[0], cal[t[1]], bool(h)] for t, h in zip(ctx['REAL'], hits)]
        if not isinstance(ranks, tuple):
            row['picks'] = {cal[t]: sorted(v, key=lambda c: ranks[ctx['lookup'][(c, t)]]) for t, v in sorted(buys.items()) if v}
        out[label] = row
        log(label, json.dumps(row, ensure_ascii=False))
    pool_runs = {y: mainleg.forward({t: {c for c, n in pool if n == t} for t in {n for _, n in pool} if cal[t][:4] == y}, prices)
                 for y in YEARS}
    out['pool'] = {y: dict(run_median=round(v['median']*100, 1), ge100=round(v['ge100']*100, 1)) for y, v in pool_runs.items()}
    log('pool', out['pool'])
    write(WORK/'scorecard.json', out)


def agree_stage(ctx):
    """IE47: indicators whose 5-bin preference (his legs vs pool) points the same way in 2024 and in 2025."""
    train = [t for t in ctx['REAL'] if t[2] in TRAIN_HALVES]
    ctx['tables_for'](train)                       # training-only bin edges and TRAIN_MASK
    year_of_row = np.asarray([ctx['cal'][d][:4] for d in ctx['row_day']])
    rows = []
    for k in ctx['USE']:
        bins, edges = ctx['BINS'][(k, 5)]
        prof = {}
        for y in ('2024', '2025'):
            mask = ctx['TRAIN_MASK'] & (year_of_row == y)
            groups = regime_groups(ctx, [t for t in train if t[2][:4] == y], mask)
            prof[y] = ctx['bin_table'](bins, edges, mask, groups)[:-1].astype(float)
        a, b = prof['2024'], prof['2025']
        r = float(np.corrcoef(a, b)[0, 1]) if a.std() > 0 and b.std() > 0 else 0.
        both = ctx['bin_table'](bins, edges, ctx['TRAIN_MASK'], regime_groups(ctx, train, ctx['TRAIN_MASK']))[:-1]
        rows.append(dict(name=ctx['NAMES'][k], r=round(r, 3), spread=round(float(both.max()-both.min()), 3),
                         y2024=np.round(a, 2).tolist(), y2025=np.round(b, 2).tolist()))
    keep = [x for x in rows if x['r'] >= AGREE_R and x['spread'] >= AGREE_SPREAD]
    keep.sort(key=lambda x: -x['r'])
    write(WORK/'agree.json', dict(rule=dict(bins=5, r=AGREE_R, spread=AGREE_SPREAD), keep=[x['name'] for x in keep], rows=rows))
    log('kept', len(keep), 'of', len(rows), [(x['name'], x['r'], x['spread']) for x in keep])
    log('DROP', ','.join(x['name'] for x in rows if x not in keep))
