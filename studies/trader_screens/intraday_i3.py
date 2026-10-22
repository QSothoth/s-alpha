"""I3: one intraday confidence method for any time t (notes/INTRADAY_I3_PREREG_CN.md; report reports/INTRADAY_CN.md,
section I3).  The shared pieces (time, the volume model, scenario rows, the fast rerun, candidates, the probability
model) are in confidence.py; this module gathers the minute sessions, fits and chooses, runs the scenarios on the
training / selection / validation days and scores them.

    PY="nice -n 19 env OPENBLAS_NUM_THREADS=1 PYTHONUTF8=1 /opt/futu-opend/venv/bin/python"
    $PY -m studies.trader_screens.intraday_i3 sessions us     # minute sessions (local sets and the recent fetch) -> npz
    $PY -m studies.trader_screens.intraday_i3 days us         # training / selection / validation days
    $PY -m studies.trader_screens.intraday_i3 volume          # fit VG / VQ on US + HK, choose on the selection days
    $PY -m studies.trader_screens.intraday_i3 run us train    # scenario reruns (resumable, one line per day)
    $PY -m studies.trader_screens.intraday_i3 run us test
    $PY -m studies.trader_screens.intraday_i3 prob            # fit PL / PG, thresholds, choose; saves the live model
    $PY -m studies.trader_screens.intraday_i3 evaluate        # validation (once) -> reports/intraday_i3_summary.json
    $PY -m studies.trader_screens.intraday_i3 posthoc         # after it, not a result: other thresholds (next round)

Work files: data/trader-screens/intraday-study/i3_*.
"""
from __future__ import annotations

import gc
import json
import sys
import time
from collections import defaultdict, deque

import numpy as np

from . import confidence as CF, intraday_i2 as I2, intraday_study as IS, minute as MN

WORK = IS.WORK
REPORTS = IS.REPORTS
TRAIN = ('2024-01-02', '2026-06-30')
LOCAL_END = '2026-09-30'
N_TRAIN = 40
MIN_NAMES = {'us': 150, 'hk': 100}
PER_MARKET = 300_000               # volume-model training rows per market
log = IS.log


def agg_cuts(market):
    return tuple(sorted(set(CF.CUTS[market]) | {b for b in map(lambda c: CF.back30(market, c), CF.CUTS[market])
                                                  if b}))


# ----- minute sessions -----
def _sessions(rows, market, cuts):
    """Complete sessions of a code-contiguous, time-ordered row stream: yields (code, day, parts (len(cuts) x 6:
    o, h, l, c, v, t so far at each cut), full (6,)) in O(rows)."""
    key, cur, parts, first, last, ci = None, None, None, None, None, 0

    def done():
        if key is None or not (first <= '10:00' and last == MN.LAST_BAR[market]):
            return None
        for i in range(ci, len(cuts)):
            parts[i] = cur
        return key[0], key[1], np.array(parts, float), np.array(cur, float)

    for code, day, hh, o, h, l, c, v, t in rows:
        if (code, day) != key:
            got = done()
            if got:
                yield got
            key, cur, parts, first, ci = (code, day), None, [None] * len(cuts), hh, 0
        while ci < len(cuts) and hh > cuts[ci]:
            parts[ci] = cur if cur is not None else (o, h, l, o, 0.0, 0.0)
            ci += 1
        if cur is None:
            cur = (o, h, l, c, v, t)
        else:
            cur = (cur[0], max(cur[1], h), min(cur[2], l), c, cur[4] + v, cur[5] + t)
        last = hh
    got = done()
    if got:
        yield got


def collect(market):
    """All complete sessions of the local sets (up to LOCAL_END) and of the recent fetch, with the unit conversion
    of each from the code's previous sessions (CF prereg: the median daily / minute ratio of the last 5, >= 2):
    npz of code / day indices, kind, parts, full, conv (volume, turnover)."""
    P = IS.panel(market)
    pdays = {str(d): i for i, d in enumerate(P['days'])}
    col = {str(c): j for j, c in enumerate(P['codes'])}
    cuts = agg_cuts(market)
    out = defaultdict(list)
    seen = set()

    def take(stream, kind):
        hist = defaultdict(lambda: deque(maxlen=I2.PRIOR_CONV))
        n = 0
        for code, day, parts, full in _sessions(stream, market, cuts):
            if code not in col or day not in pdays:
                continue
            d, j = pdays[day], col[code]
            rv = [x[0] for x in hist[code]]
            rt = [x[1] for x in hist[code]]
            cv = float(np.median(rv)) if len(rv) >= 2 else np.nan
            ct = float(np.median(rt)) if len(rt) >= 2 else np.nan
            dv, dt = float(P['volume'][d, j]), float(P['turnover'][d, j])
            if full[4] > 0 and dv > 0:
                hist[code].append((dv / full[4], dt / full[5] if full[5] > 0 and dt > 0 else np.nan))
            if (code, day) in seen or (kind == 'local' and day > LOCAL_END):
                continue
            seen.add((code, day))
            out['j'].append(j)
            out['d'].append(d)
            out['kind'].append(kind == 'recent')
            out['parts'].append(parts.astype(np.float32))
            out['full'].append(full.astype(np.float32))
            out['conv'].append((cv, ct))
            n += 1
        return n

    n = take((r for r in MN.stream(MN.latest(market), codes=set(col))), 'recent')
    log(market, 'recent sessions', n)
    for chunk in I2.local_chunks(market, set(col)):
        take(chunk, 'local')
        gc.collect()
    log(market, 'all sessions', len(out['j']))
    np.savez_compressed(WORK / f'i3_{market}_sessions.npz', j=np.array(out['j'], np.int32),
                        d=np.array(out['d'], np.int32), recent=np.array(out['kind'], bool),
                        parts=np.array(out['parts'], np.float32), full=np.array(out['full'], np.float32),
                        conv=np.array(out['conv'], np.float64), cuts=np.array(cuts))


def load_sessions(market):
    z = np.load(WORK / f'i3_{market}_sessions.npz')
    return {k: z[k] for k in z.files}


# ----- days -----
def make_days(market):
    P = IS.panel(market)
    S = load_sessions(market)
    i2 = I2.days(market)
    test = sorted(i2['test'])
    out = dict(select=test[:len(test) // 2], validate=test[len(test) // 2:], local_test=i2['local'],
               earlier=i2.get('earlier', []), train=[])
    if market in MIN_NAMES:
        days = np.array([str(x) for x in P['days']])
        cnt = defaultdict(int)
        for d, rec in zip(S['d'], S['recent']):
            if not rec:
                cnt[days[d]] += 1
        ok = sorted(x for x, n in cnt.items() if TRAIN[0] <= x <= TRAIN[1] and n >= MIN_NAMES[market])
        out['train'] = [ok[i] for i in np.round(np.linspace(0, len(ok) - 1, N_TRAIN)).astype(int)]
        out['train_candidates'] = len(ok)
    (WORK / f'i3_{market}_days.json').write_text(json.dumps(out, indent=1), encoding='utf-8')
    return out


def days(market):
    return json.loads((WORK / f'i3_{market}_days.json').read_text(encoding='utf-8'))


# ----- the provisional state of every session at every cut -----
def rolling(P):
    """20-day means of volume, turnover and range over the 20 sessions before each day (days x codes)."""
    with np.errstate(invalid='ignore', divide='ignore'):
        rng = (P['high'] - P['low']) / P['close']
    out = {}
    for name, a in (('adv', P['volume']), ('to20', P['turnover']), ('adr', rng)):
        a = np.asarray(a, float)
        ok = np.isfinite(a)
        cs = np.vstack([np.zeros((1, a.shape[1])), np.cumsum(np.where(ok, a, 0), 0)])
        cn = np.vstack([np.zeros((1, a.shape[1])), np.cumsum(ok, 0)])
        m = np.full(a.shape, np.nan)
        m[20:] = (cs[20:-1] - cs[:-21]) / np.maximum(cn[20:-1] - cn[:-21], 1)
        m[20:][(cn[20:-1] - cn[:-21]) < 10] = np.nan
        out[name] = m
    return out


def states(P, R, S, idx, market):
    """Per session in idx and per eval cut: the provisional bar (panel units) and the inputs of the volume
    features.  Units: prices x k = today's daily open / the minute open (the open is known at t), volume x the
    conversion of earlier sessions (recent fetch without two earlier sessions: x 1 / k)."""
    cuts = [str(c) for c in S['cuts']]
    ci = [cuts.index(c) for c in CF.CUTS[market]]
    bi = [cuts.index(CF.back30(market, c)) if CF.back30(market, c) else -1 for c in CF.CUTS[market]]
    j, d = S['j'][idx], S['d'][idx]
    parts, full = S['parts'][idx].astype(float), S['full'][idx].astype(float)
    op = P['open'][d, j].astype(float)
    k = op / full[:, 0]
    cv, ct = S['conv'][idx, 0], S['conv'][idx, 1]
    cv = np.where(np.isfinite(cv), cv, np.where(S['recent'][idx], 1 / k, np.nan))
    ct = np.where(np.isfinite(ct), ct, 1.0)
    prev = P['close'][d - 1, j].astype(float)
    fac = (P['close'][d - 1, j] / P['raw_close'][d - 1, j]).astype(float)
    out = dict(j=j, d=d, op=op, prev=prev, fac=fac, adv=R['adv'][d, j], to20=R['to20'][d, j], adr=R['adr'][d, j],
               day_v=P['volume'][d, j].astype(float), keep=np.abs(np.log(cv * full[:, 4] /
                                                                          P['volume'][d, j])) <= .5)
    for n, (c, b) in enumerate(zip(ci, bi)):
        p = parts[:, c]
        v = p[:, 4] * cv
        out[n] = dict(hi=p[:, 1] * k, lo=p[:, 2] * k, cl=p[:, 3] * k, v=v, to=p[:, 5] * ct,
                      last30=v - (parts[:, b, 4] * cv if b >= 0 else 0.0))
    return out


def fm_of(st, market, rows):
    """{cut: median share of the day's volume so far} over the rows (training sessions)."""
    fm = {}
    for n, c in enumerate(CF.CUTS[market]):
        s = st[n]['v'][rows] / st['day_v'][rows]
        s = s[np.isfinite(s) & st['keep'][rows]]
        fm[c] = float(np.median(s))
    return fm


def vol_table(st, market, fm, groups):
    """Rows (session, cut) for the sessions grouped by day (groups: list of index arrays): X, t, cut tau, z, rvol."""
    X, T, Z, ix, cut = [], [], [], [], []
    for n, c in enumerate(CF.CUTS[market]):
        t = CF.tau(market, c)
        f = fm[c]
        s = st[n]
        for g in groups:
            x = CF.vol_features(t, f, s['v'][g], s['last30'][g], st['op'][g], st['prev'][g], st['adv'][g],
                                st['to20'][g], st['adr'][g], s['hi'][g], s['lo'][g], s['cl'][g])
            with np.errstate(divide='ignore', invalid='ignore'):
                y = np.log(st['day_v'][g] / s['v'][g])
            X.append(x)
            T.append(np.full(len(g), t))
            Z.append(np.where(st['keep'][g], y - np.log(1 / f), np.nan))
            ix.append(g)
            cut.append(np.full(len(g), n))
    return dict(X=np.vstack(X), t=np.concatenate(T), z=np.concatenate(Z), i=np.concatenate(ix),
                cut=np.concatenate(cut))


def by_day(S, idx):
    order = idx[np.argsort(S['d'][idx], kind='stable')]
    dd = S['d'][order]
    cuts = np.flatnonzero(np.diff(dd)) + 1
    return [g for g in np.split(order, cuts) if len(g)]


def volume():
    """Fit VG / VQ on the US + HK training sessions, choose on the selection days (all three markets), and note
    the errors on every test day; saves i3_volume.json (model, f_m per market, scores)."""
    rng = np.random.default_rng(0)
    train, fms = [], {}
    sel, val = {}, {}
    for m in ('us', 'hk', 'cn'):
        P = IS.panel(m)
        R = rolling(P)
        S = load_sessions(m)
        D = days(m)
        pd_ = np.array([str(x) for x in P['days']])
        sday = pd_[S['d']]
        all_i = np.arange(len(S['j']))
        st = states(P, R, S, all_i, m)
        if m == 'cn':
            fit_rows = np.isin(sday, D['earlier'])
        else:
            fit_rows = (~S['recent']) & (sday >= TRAIN[0]) & (sday <= TRAIN[1])
        fms[m] = fm_of(st, m, fit_rows)
        log(m, 'f_m', {c: round(v, 3) for c, v in fms[m].items()})
        if m != 'cn':
            tb = vol_table(st, m, fms[m], by_day(S, np.flatnonzero(fit_rows)))
            ok = np.isfinite(tb['z']) & np.all(np.isfinite(tb['X']), axis=1)
            pick = np.flatnonzero(ok)
            pick = rng.choice(pick, min(PER_MARKET, len(pick)), replace=False)
            train.append({k: v[pick] for k, v in tb.items()})
            log(m, 'training rows', len(pick), 'of', int(ok.sum()))
            del tb
        for seg, store in (('select', sel), ('validate', val)):
            rows = np.flatnonzero(np.isin(sday, D[seg]))
            store[m] = vol_table(st, m, fms[m], by_day(S, rows))
        del P, R, S, st
        gc.collect()
    T = {k: np.concatenate([x[k] for x in train]) for k in train[0]}
    models = {}
    for kind in ('VG', 'VQ'):
        models[kind] = CF.VolumeModel(kind).fit(T['X'], T['t'], T['z'], T['t'])
    score = {}
    for kind, mdl in models.items():
        sc = {}
        for m, tb in sel.items():
            ok = np.isfinite(tb['z']) & np.all(np.isfinite(tb['X']), axis=1)
            zq = mdl.predict(tb['X'][ok], tb['t'][ok])
            hot = tb['X'][ok, 0] >= 0
            sc[m] = (CF.pinball(zq, tb['z'][ok]), CF.pinball(zq[hot], tb['z'][ok][hot]))
        a = np.mean([v[0] for v in sc.values()])
        b = np.mean([v[1] for v in sc.values()])
        score[kind] = dict(by_market=sc, all=a, hot=b, sum=a + b)
    best = min(score, key=lambda k: score[k]['sum'])
    chosen = 'VG' if score['VG']['sum'] <= score[best]['sum'] * 1.02 else best
    log('volume scores', {k: round(v['sum'], 4) for k, v in score.items()}, 'chosen', chosen)
    errors = {}
    for seg, store in (('select', sel), ('validate', val)):
        for m, tb in store.items():
            ok = np.isfinite(tb['z']) & np.all(np.isfinite(tb['X']), axis=1)
            for kind, mdl in list(models.items()) + [('E0', None)]:
                for n, c in enumerate(CF.CUTS[m]):
                    r = ok & (tb['cut'] == n)
                    if not r.any():
                        continue
                    z, lf = tb['z'][r], np.log(1 / fms[m][c])
                    if mdl is None:                    # no scaling: y = 0, z = -log(1 / f)
                        e = np.abs(z + lf)
                        cover = None
                    else:
                        zq = mdl.predict(tb['X'][r], tb['t'][r])
                        e = np.abs(zq[:, 1] - z)
                        cover = float(np.mean((z >= zq[:, 0]) & (z <= zq[:, 2])))
                    hot = tb['X'][r, 0] >= 0
                    errors.setdefault(seg, {}).setdefault(m, {}).setdefault(kind, {})[c] = dict(
                        n=int(r.sum()), mae=float(np.median(e)), mae_hot=float(np.median(e[hot])) if hot.any()
                        else None, cover=cover)
    out = dict(chosen=chosen, score=score, fm=fms, models={k: v.to_json() for k, v in models.items()},
               errors=errors, n_train=int(len(T['z'])))
    (WORK / 'i3_volume.json').write_text(json.dumps(out, default=float), encoding='utf-8')
    return out


def volume_model():
    v = json.loads((WORK / 'i3_volume.json').read_text(encoding='utf-8'))
    return CF.VolumeModel.from_json(v['models'][v['chosen']]), v['fm'], v['chosen']


# ----- scenario runs -----
def train_cuts(i, market):
    n = len(CF.CUTS[market])
    return sorted({CF.CUTS[market][(i + r * n // 4) % n] for r in range(4)}, key=CF.CUTS[market].index)


def day_rows(P, R, S, idx, market, cuts, vm, fm, with_v0):
    """{(cut, scenario): row} for one day's sessions idx, plus per cut the provisional info of each name
    (price so far, u, q50 full day over the 20-day mean)."""
    st = states(P, R, S, idx, market)
    rows, info = {}, {}
    for n, c in enumerate(CF.CUTS[market]):
        if c not in cuts:
            continue
        t, s = CF.tau(market, c), st[n]
        X = CF.vol_features(t, fm[c], s['v'], s['last30'], st['op'], st['prev'], st['adv'], st['to20'], st['adr'],
                            s['hi'], s['lo'], s['cl'])
        ok = np.all(np.isfinite(X), axis=1) & np.isfinite(s['cl']) & (s['v'] > 0)
        zq = vm.predict(np.nan_to_num(X[ok]), t)
        yq = zq + np.log(1 / fm[c])
        prov = dict(j=st['j'][ok], high=s['hi'][ok], low=s['lo'][ok], close=s['cl'][ok], volume=s['v'][ok],
                    turnover=s['to'][ok], adr=st['adr'][ok], k=st['fac'][ok])
        names = (('V0',) if with_v0 else ()) + CF.SCEN
        for name, row in CF.scenario_rows(P, int(st['d'][0]), prov, yq, t, names).items():
            rows[(c, name)] = row
        codes = np.asarray(P['codes'])[prov['j']]
        info[c] = {str(code): [float(cl), float(a * np.sqrt(1 - t)), float(np.exp(y) * v / ad) if ad > 0 else None]
                   for code, cl, a, y, v, ad in zip(codes, prov['close'], np.nan_to_num(prov['adr']), yq[:, 1],
                                                    prov['volume'], st['adv'][ok])}
    covered = sorted(str(c) for c in np.asarray(P['codes'])[st['j']])     # the rest keep their true bar
    return rows, info, covered


def compact(dec):
    return {sid: dict(sig=x['sig'], buys=[b[:2] + [b[2], b[3], b[5]] for b in x['buys']], sells=x['sells'])
            for sid, x in dec.items()}


def run(market, seg):
    import warnings
    warnings.simplefilter('ignore', RuntimeWarning)
    D = days(market)
    todo_days = D['train'] if seg == 'train' else D['select'] + D['validate']
    vm, fms, chosen = volume_model()
    fm = fms[market]
    P = IS.panel(market)
    R = rolling(P)
    S = load_sessions(market)
    pd_ = [str(x) for x in P['days']]
    sday = np.array(pd_)[S['d']]
    path = WORK / f'i3_{market}_{seg}.jsonl'
    done = {json.loads(x)['day'] for x in path.open(encoding='utf-8')} if path.exists() else set()
    t_rest = time.time()
    for i, day in enumerate(todo_days):
        if day in done:
            continue
        t0 = time.time()
        local = day in D.get('local_test', []) or seg == 'train'
        idx = np.flatnonzero((sday == day) & (S['recent'] != local))
        if not len(idx):
            log(market, day, 'no sessions')
            continue
        cuts = train_cuts(i, market) if seg == 'train' else CF.CUTS[market]
        rows, info, covered = day_rows(P, R, S, idx, market, cuts, vm, fm, seg != 'train')
        d = pd_.index(day)
        names = list(rows)
        rows_named = {f'{c}|{s}': r for (c, s), r in rows.items()}
        rows_named['true'] = {k: P[k][d].astype(float).copy() for k in ('open', 'high', 'low', 'close', 'volume',
                                                                        'turnover', 'raw_close')}
        dec = CF.decide_many(P, d, rows_named, market)
        rec = dict(day=day, seg=seg, local=local, covered=covered, cuts=list(cuts), volume_model=chosen,
                   true=compact(dec.pop('true')), info=info,
                   scen={k: compact(v) for k, v in dec.items()})
        with path.open('a', encoding='utf-8') as out:
            out.write(json.dumps(rec, default=float) + '\n')
        log(market, seg, day, f'{len(names)} rows', f'{time.time() - t0:.0f}s')
        del rows, rows_named, dec, rec
        gc.collect()
        if time.time() - t_rest > IS.WORK_SECONDS:
            log(f'rest {IS.REST_SECONDS // 60} min')
            time.sleep(IS.REST_SECONDS)
            t_rest = time.time()


# ----- candidates, the probability model, evaluation -----
def expand(b):
    """compact -> the decision format of confidence.keys_of."""
    return {sid: dict(sig=x['sig'], buys=[[z[0], z[1], z[2], z[3], None, z[4]] for z in x['buys']],
                      sells=x['sells']) for sid, x in b.items()}


def load_runs(market, seg):
    path = WORK / f'i3_{market}_{seg}.jsonl'
    if not path.exists():
        return []
    return [json.loads(x) for x in path.open(encoding='utf-8')]


def day_items(rec, market):
    """Per cut: (candidate rows with labels, true keys, V0 keys) of one stored day."""
    cov = set(rec['covered']) if rec['covered'] else None
    true = CF.keys_of(expand(rec['true']), cov)
    out = {}
    for c in rec['cuts']:
        t = CF.tau(market, c)
        by = {s: expand(rec['scen'][f'{c}|{s}']) for s in CF.SCEN}
        cand = CF.candidates(by, t, cov)
        for r in cand:
            r['y'] = r['key'] in true
            r['market'], r['day'], r['cut'] = market, rec['day'], c
            r['info'] = rec['info'][c].get(r['key'][2])
        v0 = CF.keys_of(expand(rec['scen'][f'{c}|V0']), cov) if f'{c}|V0' in rec['scen'] else None
        out[c] = (cand, true, v0)
    return out


def order(key):
    return key[0] in ('buy', 'sell')


def prob():
    """Fit PL / PG on the training days (US + HK), thresholds on the training days, choose on the selection days
    (all markets) by the Brier score of order candidates; saves i3_prob.json and the live model."""
    tr = [r for m in ('us', 'hk') for rec in load_runs(m, 'train') for c in day_items(rec, m).values() for r in c[0]]
    X, y = CF.pfeatures(tr), np.array([r['y'] for r in tr], float)
    is_o = np.array([order(r['key']) for r in tr])
    sel = []
    for m in ('us', 'hk', 'cn'):
        Dm = days(m)
        for rec in load_runs(m, 'test'):
            if rec['day'] in Dm['select']:
                sel += [r for c in day_items(rec, m).values() for r in c[0]]
    Xs, ys = CF.pfeatures(sel), np.array([r['y'] for r in sel], float)
    os_ = np.array([order(r['key']) for r in sel])
    res = {}
    models = {}
    for kind in ('PL', 'PG'):
        mdl = CF.ProbModel(kind).fit(X, y)
        models[kind] = mdl
        p_tr = mdl.predict(X)
        th = CF.thresholds(p_tr, y, is_o)
        ps = mdl.predict(Xs)
        res[kind] = dict(thresholds=th, brier_select=float(np.mean((ps[os_] - ys[os_]) ** 2)),
                         brier_train=float(np.mean((p_tr[is_o] - y[is_o]) ** 2)), n_train=int(len(y)),
                         n_train_orders=int(is_o.sum()), n_select_orders=int(os_.sum()))
    chosen = 'PG' if res['PG']['brier_select'] <= res['PL']['brier_select'] * 1.02 else 'PL'
    log('prob', {k: (v['thresholds'], round(v['brier_select'], 4)) for k, v in res.items()}, 'chosen', chosen)
    out = dict(chosen=chosen, res=res, models={k: v.to_json() for k, v in models.items()})
    if chosen == 'PL':
        out['coef'] = dict(zip(('const',) + CF.PFEAT, models['PL'].beta.tolist()))
    (WORK / 'i3_prob.json').write_text(json.dumps(out, default=float), encoding='utf-8')
    vm, fm, vchosen = volume_model()
    CF.save_model(vm, models[chosen], fm, dict(p_hi=res[chosen]['thresholds'][0], p_lo=res[chosen]['thresholds'][1]),
                  dict(volume=vchosen, prob=chosen, prereg='notes/INTRADAY_I3_PREREG_CN.md',
                       train=TRAIN, step=CF.STEP))
    return out


def side_move(key, price, close):
    """Side-adjusted move from the provisional price to the close (buys: the trade's; sells: of the position
    sold)."""
    if not price or not np.isfinite(close):
        return None
    return key[3] * (close / price - 1)


def score_segment(seg_days, mdl, th):
    """{market: {cut: totals}} for the direct board and the unified columns, plus per trader / class tallies and
    the moves of false and true orders."""
    p_hi, p_lo = th
    out = {}
    for m in ('us', 'hk', 'cn'):
        P = IS.panel(m)
        pd_ = {str(x): i for i, x in enumerate(P['days'])}
        col = {str(c): j for j, c in enumerate(P['codes'])}
        res = out[m] = {}
        for rec in load_runs(m, 'test'):
            if rec['day'] not in seg_days[m]:
                continue
            d = pd_[rec['day']]
            for c, (cand, true, v0) in day_items(rec, m).items():
                a = res.setdefault(c, dict(days=0, direct=[0, 0, 0], order=[0, 0, 0], watch_recall=[0, 0],
                                           by_trader=defaultdict(lambda: [0] * 9), by_cls=defaultdict(lambda: [0] * 9),
                                           false_direct=[], false_order=[], true_order_gap=[], true_direct_gap=[],
                                           false_sell_order=[], false_sell_direct=[], p_true=[], p_false=[]))
                a['days'] += 1
                tk = {k for k in true if order(k)}
                p = mdl.predict(CF.pfeatures(cand)) if cand else np.zeros(0)
                ords = {r['key']: (r, pi) for r, pi in zip(cand, p) if order(r['key'])}
                col_o = {k for k, (r, pi) in ords.items() if pi >= p_hi}
                col_w = {k for k, (r, pi) in ords.items() if p_lo <= pi < p_hi}
                dk = {k for k in (v0 or {}) if order(k)}
                for k, (r, pi) in ords.items():
                    (a['p_true'] if k in tk else a['p_false']).append(float(pi))
                a['direct'] = [x + y for x, y in zip(a['direct'], (len(dk & tk), len(dk - tk), len(tk - dk)))]
                a['order'] = [x + y for x, y in zip(a['order'], (len(col_o & tk), len(col_o - tk), len(tk - col_o)))]
                a['watch_recall'] = [a['watch_recall'][0] + len((col_o | col_w) & tk), a['watch_recall'][1] + len(tk)]
                cls_of = {r['key']: r['cls'] for r in cand}
                tinfo = CF.keys_of(expand(rec['true']), set(rec['covered']) if rec['covered'] else None)
                for k in tk | dk | col_o | col_w:
                    cl = cls_of.get(k) or CF.pclass(k, tinfo.get(k, {}).get('setup'))
                    flags = (k in dk and k in tk, k in dk and k not in tk, k in tk and k not in dk,
                             k in col_o and k in tk, k in col_o and k not in tk, k in tk and k not in col_o,
                             k in (col_o | col_w) and k in tk, k in tk, k in col_w)
                    for store, g in ((a['by_trader'], k[1]), (a['by_cls'], f'{k[0]}|{cl}')):
                        store[g] = [x + int(f) for x, f in zip(store[g], flags)]
                for k in (dk | col_o):
                    j = col.get(k[2])
                    if j is None:
                        continue
                    close = float(P['close'][d, j])
                    price = (rec['info'][c].get(k[2]) or [None])[0]
                    mv = side_move(k, price, close)
                    if mv is None:
                        continue
                    is_buy = k[0] == 'buy'
                    if k in dk and k not in tk:
                        (a['false_direct'] if is_buy else a['false_sell_direct']).append(mv)
                    if k in col_o and k not in tk:
                        (a['false_order'] if is_buy else a['false_sell_order']).append(mv)
                    if is_buy and k in tk:
                        if k in col_o:
                            a['true_order_gap'].append(mv)
                        if k in dk:
                            a['true_direct_gap'].append(mv)
        del P
        gc.collect()
    return out


def stats(v):
    v = np.array(v, float)
    if not len(v):
        return dict(n=0)
    return dict(n=len(v), mean=float(v.mean()), median=float(np.median(v)), p05=float(np.quantile(v, .05)),
                win=float(np.mean(v > 0)))


def finish(res):
    out = {}
    for m, cuts in res.items():
        out[m] = {}
        for c, a in cuts.items():
            def pr(x):
                s, f, mi = x
                return dict(same=s, false=f, missed=mi, precision=s / (s + f) if s + f else None,
                            recall=s / (s + mi) if s + mi else None)
            out[m][c] = dict(days=a['days'], direct=pr(a['direct']), order=pr(a['order']),
                             order_watch_recall=a['watch_recall'][0] / a['watch_recall'][1]
                             if a['watch_recall'][1] else None, n_true=a['watch_recall'][1],
                             by_trader={k: v for k, v in a['by_trader'].items()},
                             by_cls={k: v for k, v in a['by_cls'].items()},
                             false_direct=stats(a['false_direct']), false_order=stats(a['false_order']),
                             false_sell_direct=stats(a['false_sell_direct']),
                             false_sell_order=stats(a['false_sell_order']),
                             true_order_gap=stats(a['true_order_gap']), true_direct_gap=stats(a['true_direct_gap']),
                             p_true=stats(a['p_true']), p_false=stats(a['p_false']))
    return out


def judge(fin):
    """The pre-registered judgements per market on the validation days."""
    out = {}
    for m, cuts in fin.items():
        if CF.MAIN[m] not in cuts:
            continue
        a = cuts[CF.MAIN[m]]
        err_u = a['order']['false'] + a['order']['missed']
        err_d = a['direct']['false'] + a['direct']['missed']
        early = {}
        for c in CF.EARLY[m]:
            x = cuts.get(c)
            if not x:
                continue
            pu, pd_ = x['order']['precision'], x['direct']['precision']
            early[c] = dict(precision=[pu, pd_], recall_watch=[x['order_watch_recall'], x['direct']['recall']],
                            ok=pu is not None and pd_ is not None and pu >= pd_ + .10 and
                            (x['order_watch_recall'] or 0) >= (x['direct']['recall'] or 0),
                            tail=[x['false_order'].get('p05'), x['false_direct'].get('p05')])
        out[m] = dict(main=dict(errors=[err_u, err_d], ok=err_u <= 1.1 * err_d), early=early,
                      early_ok=bool(early) and all(v['ok'] for v in early.values()))
    out['integrate'] = all(v['main']['ok'] for k, v in out.items() if k != 'integrate') and \
        sum(v['early_ok'] for k, v in out.items() if k != 'integrate') >= 2
    return out


def evaluate():
    pr = json.loads((WORK / 'i3_prob.json').read_text(encoding='utf-8'))
    mdl = CF.ProbModel.from_json(pr['models'][pr['chosen']])
    th = pr['res'][pr['chosen']]['thresholds']
    segs = {s: {m: days(m)[s] for m in ('us', 'hk', 'cn')} for s in ('select', 'validate')}
    out = dict(prob=dict(chosen=pr['chosen'], res=pr['res'], coef=pr.get('coef')),
               volume={k: v for k, v in json.loads((WORK / 'i3_volume.json').read_text(encoding='utf-8')).items()
                       if k != 'models'},
               days={m: days(m) for m in ('us', 'hk', 'cn')})
    for s, sd in segs.items():
        out[s] = finish(score_segment(sd, mdl, th))
    out['judge'] = judge(out['validate'])
    if CF.MODEL_PATH.exists():                         # the board uses the model only when the judgement says so
        d = json.loads(CF.MODEL_PATH.read_text(encoding='utf-8'))
        d['meta']['integrate'] = out['judge']['integrate']
        d['meta']['judge'] = {m: dict(main_ok=v['main']['ok'], early_ok=v['early_ok'])
                              for m, v in out['judge'].items() if m != 'integrate'}
        CF.MODEL_PATH.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding='utf-8')
    (REPORTS / 'intraday_i3_summary.json').write_text(json.dumps(out, indent=1, default=float, ensure_ascii=False),
                                                     encoding='utf-8')
    return out


def posthoc():
    """After the validation, NOT a validated result: the validation days under order thresholds 0.5 and 0.8 (the
    training rule gave 0.2), to point the next round; reports/intraday_i3_posthoc.json."""
    pr = json.loads((WORK / 'i3_prob.json').read_text(encoding='utf-8'))
    mdl = CF.ProbModel.from_json(pr['models'][pr['chosen']])
    sd = {m: days(m)['validate'] for m in ('us', 'hk', 'cn')}
    out = {}
    for th in ((.5, .2), (.8, .2)):
        fin = finish(score_segment(sd, mdl, th))
        out[f'{th[0]}/{th[1]}'] = {m: {c: dict(order=a['order'], direct=a['direct'],
                                               watch_recall=a['order_watch_recall'], false_order=a['false_order'],
                                               false_direct=a['false_direct'])
                                       for c, a in cuts.items()} for m, cuts in fin.items()}
    (REPORTS / 'intraday_i3_posthoc.json').write_text(json.dumps(out, default=float, indent=1), encoding='utf-8')
    return out


if __name__ == '__main__':
    cmd = sys.argv[1] if len(sys.argv) > 1 else ''
    if cmd == 'sessions':
        collect(sys.argv[2])
    elif cmd == 'days':
        print(json.dumps(make_days(sys.argv[2]), indent=1))
    elif cmd == 'volume':
        volume()
    elif cmd == 'run':
        run(sys.argv[2], sys.argv[3])
    elif cmd == 'prob':
        prob()
    elif cmd == 'evaluate':
        evaluate()
    elif cmd == 'posthoc':
        posthoc()
    else:
        raise SystemExit(__doc__)
