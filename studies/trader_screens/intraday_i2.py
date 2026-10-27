"""I2: provisional bars on 20 sessions per market (A-shares included) and a full-day volume estimate known at the cut.
Pre-registration notes/INTRADAY_I2_PREREG_CN.md; report reports/INTRADAY_CN.md (section I2).

Test days: every full session of the free five-minute fetch (whole list), topped up to 20 with sessions of the local
minute sets (US k5 union, HK 1m; a subset of the list: only those names get a provisional bar).  The volume model
predicts y = log(our daily volume / volume up to the cut) from what is known at the cut; it is fitted on the local
sets' 2024-01-02 .. 2026-06-30 (US, HK) or, for A-shares (no local set), on the sessions before each test day.

    PY="nice -n 19 env OPENBLAS_NUM_THREADS=1 PYTHONUTF8=1 /opt/futu-opend/venv/bin/python"
    $PY -m studies.trader_screens.intraday_i2 days us        # the 20 test days
    $PY -m studies.trader_screens.intraday_i2 model us       # fit E0..E4, choose on the training data, predict the test days
    $PY -m studies.trader_screens.intraday_i2 run us         # the systems on every test day (resumable)
    $PY -m studies.trader_screens.intraday_i2 summary        # reports/intraday_i2_summary.json

Decisions go to data/trader-screens/intraday-study/i2_<market>.jsonl (I1 runs of the same day, cut and scheme are
copied in, not rerun).
"""
from __future__ import annotations

import csv
import gc
import gzip
import json
import sys
import time
from collections import defaultdict
from pathlib import Path

import numpy as np

from . import intraday_study as IS, minute as MN

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / 'data'
WORK = IS.WORK
REPORTS = IS.REPORTS

CUTS = {'us': ('10:30', '12:30', '15:45', '15:50'), 'hk': ('10:30', '13:30', '15:45', '15:50'),
        'cn': ('10:30', '14:00', '14:45', '14:50')}
EARLY = {m: c[:2] for m, c in CUTS.items()}
MAIN = IS.MAIN
N_DAYS = 20
LOCAL_TEST = {'us': ('2026-07-01', '2026-09-30', 150), 'hk': ('2026-07-01', '2026-09-23', 100)}
TRAIN = ('2024-01-02', '2026-06-30')
CN_MIN_TRAIN = 5                       # A-shares: a test day needs this many earlier sessions to fit on
PRIOR_CONV = 5                         # sessions before D whose daily / minute volume ratio converts the units
US_LOCAL = ('martin-luk-k5-r8', 'p3-k5-validation-raw/k5', 'preopen-s20-valid-v1/k5', 'preopen-s20-k5-raw-a/k5',
            'preopen-s20-k5-raw-b/k5', 'preopen-us-k5-raw/k5')       # first wins for a code
HK_LOCAL = ('watch-hk1m-holdout-2025h2-v1', 'watch-hk1m-train-v1', 'watch-hk1m-valid-v1')
FEATURES = ('rvol', 'gap', 'liq', 'trend', 'adr', 'ret', 'pos', 'mkt')
MODELS = ('E0', 'E1', 'E2', 'E3', 'E4')            # simplest first (ties within 2% go to the simpler)
LAMBDA = 1.0
log = IS.log


def minus30(cut):
    h, m = map(int, cut.split(':'))
    t = h * 60 + m - 30
    return f'{t // 60:02d}:{t % 60:02d}'


def all_cuts(market):
    return tuple(sorted(set(CUTS[market]) | {minus30(c) for c in CUTS[market]}))


# ----- minute sources -----
def us_local_files():
    best = {}
    for src in US_LOCAL:
        base = DATA / src
        for f in sorted(list(base.glob('*.csv.gz')) + list(base.glob('*.csv'))):
            sym = f.name.split('.')[0]
            if sym in ('progress', 'sample') or not f.stat().st_size:
                continue
            best.setdefault('US.' + sym, f)
    return best


def local_chunks(market, codes):
    """Per source chunk: yield rows (code, day, hhmm, o, h, l, c, v, t) of the local minute sets, one chunk at a
    time (US: one file per code; HK: one file per period)."""
    if market == 'us':
        for code, f in sorted(us_local_files().items()):
            if code not in codes:
                continue
            fh = gzip.open(f, 'rt', encoding='utf-8', newline='') if f.suffix == '.gz' else open(f, newline='')

            def rows(fh=fh, code=code):
                with fh:
                    rd = csv.reader(fh)
                    head = next(rd)
                    ix = [head.index(k) for k in ('time_key', 'open', 'high', 'low', 'close', 'volume', 'turnover')]
                    for r in rd:
                        yield (code, r[ix[0]][:10], r[ix[0]][11:16], *(float(r[i]) for i in ix[1:]))
            yield rows()
    elif market == 'hk':
        for src in HK_LOCAL:
            def rows(src=src):
                with gzip.open(DATA / src / 'bars_1m.csv.gz', 'rt', encoding='utf-8', newline='') as fh:
                    rd = csv.reader(fh)
                    head = next(rd)
                    ix = [head.index(k) for k in ('code', 'time_key', 'open', 'high', 'low', 'close', 'volume',
                                                  'turnover')]
                    for r in rd:
                        if r[ix[0]] in codes:
                            yield (r[ix[0]], r[ix[1]][:10], r[ix[1]][11:16], *(float(r[i]) for i in ix[2:]))
            yield rows()


def compact(agg, market, kind):
    """{(code, day): (kind, full (o, h, l, c, v, t), {cut: (h, l, c, v, t)})} of the whole sessions."""
    out = {}
    for key, s in agg.items():
        if MN.complete(s, market):
            out[key] = (kind, s['parts'].pop('full'), {c: p[1:] for c, p in s['parts'].items()})
    return out


def records(market, codes):
    """Every whole session of the recent fetch and (US, HK) of the local sets, compacted at every needed cut."""
    cuts = all_cuts(market)
    rec = compact(MN.aggregate(MN.stream(MN.latest(market), codes=codes), cuts), market, 'recent')
    for chunk in local_chunks(market, codes):
        for key, v in compact(MN.aggregate(chunk, cuts), market, 'local').items():
            rec.setdefault(key, v)                     # the recent fetch wins on a shared day
        gc.collect()
    return rec


# ----- test days -----
def make_days(market):
    P = IS.panel(market)
    pdays = [str(d) for d in P['days']]
    uni = IS.universe(market)
    count = defaultdict(int)
    for (code, day), s in MN.aggregate(MN.stream(MN.latest(market), codes=uni), ()).items():
        if MN.complete(s, market):
            count[day] += 1
    recent = sorted(d for d, n in count.items() if n >= .5 * len(uni) and d in pdays)
    earlier = []
    if market == 'cn':
        earlier, recent = recent[:-N_DAYS], recent[-N_DAYS:]
    local = []
    need = N_DAYS - len(recent)
    if need > 0 and market in LOCAL_TEST:
        lo, hi, min_n = LOCAL_TEST[market]
        cnt = defaultdict(int)
        for chunk in local_chunks(market, uni):
            for code, day, hh, *_ in chunk:
                if hh == MN.LAST_BAR[market] and lo <= day <= hi:
                    cnt[day] += 1
        ok = sorted(d for d, n in cnt.items() if n >= min_n and d in pdays)
        local = [ok[i] for i in np.round(np.linspace(0, len(ok) - 1, need)).astype(int)]
        log(market, 'local candidate days', len(ok))
    out = dict(recent=recent, local=local, test=sorted(recent + local), earlier=earlier,
               file=MN.latest(market).name)
    WORK.mkdir(parents=True, exist_ok=True)
    (WORK / f'i2_{market}_days.json').write_text(json.dumps(out, indent=1), encoding='utf-8')
    return out


def days(market):
    path = WORK / f'i2_{market}_days.json'
    if not path.exists():
        raise SystemExit(f'run `days {market}` first')
    return json.loads(path.read_text(encoding='utf-8'))


# ----- features known at the cut -----
def features(P, rec, market, fm, wanted):
    """Rows of (code, day, cut) for wanted (code, day) pairs: dict(x=features, y=log(daily / cut volume), vcut,
    keep=training filter).  Only the minute bars up to the cut and the daily bars before the day enter x."""
    pdays = {str(d): i for i, d in enumerate(P['days'])}
    col = {str(c): j for j, c in enumerate(P['codes'])}
    by_code = defaultdict(list)
    for (code, day) in rec:
        by_code[code].append(day)
    for v in by_code.values():
        v.sort()
    vol, to = P['volume'], P['turnover']
    with np.errstate(invalid='ignore', divide='ignore'):
        rng = (P['high'] - P['low']) / P['close']
    out = defaultdict(list)                            # (day, cut) -> rows (tuples; arrays once complete)
    for code, day in wanted:
        if code not in col or day not in pdays:
            continue
        d, j = pdays[day], col[code]
        if d < 21 or not np.isfinite(P['close'][d, j]) or not vol[d, j] > 0:
            continue
        kind, full, parts = rec[(code, day)]
        prior = [x for x in by_code[code] if x < day][-PRIOR_CONV:]
        ratios = [vol[pdays[x], col[code]] / rec[(code, x)][1][4] for x in prior
                  if x in pdays and rec[(code, x)][1][4] > 0 and vol[pdays[x], col[code]] > 0]
        if len(ratios) >= 2:
            conv = float(np.median(ratios))
        elif kind == 'recent':
            conv = float(P['raw_close'][d, j] / P['close'][d, j])
        else:
            continue
        if kind == 'recent':
            k = float(P['close'][d, j] / P['raw_close'][d, j])
        else:
            k = float(np.median([P['open'][d, j] / full[0], P['high'][d, j] / full[1], P['low'][d, j] / full[2]]))
        adv = np.nanmean(vol[d - 20:d, j])
        to20 = np.nanmean(to[d - 20:d, j])
        adr = np.nanmean(rng[d - 20:d, j])
        prev = P['close'][d - 1, j]
        if not (adv > 0 and to20 > 0 and np.isfinite(prev) and prev > 0):
            continue
        for cut in CUTS[market]:
            p = parts.get(cut)
            if p is None or not p[3] > 0:
                continue
            h, l, c, v, t = p
            vcut = v * conv
            p30 = parts.get(minus30(cut))
            last30 = v - (p30[3] if p30 else 0.0)
            base = adv * fm[cut]
            out[(day, cut)].append((code, kind, float(np.log(vcut / base)), abs(P['open'][d, j] / prev - 1),
                                    float(np.log(to20)), float(np.log(max(last30, 1e-3 * v) / v)),
                                    float(adr) if np.isfinite(adr) else 0.0, c * k / prev - 1,
                                    (c - l) / (h - l) if h > l else .5,
                                    float(np.log(vol[d, j] / vcut)), vcut, t, base,
                                    abs(np.log(conv * full[4] / vol[d, j])) <= .5))
    groups = {}
    for key, rows in out.items():                      # arrays; the day's market-wide relative volume at the cut
        a = np.array([r[2:13] for r in rows], float)
        mkt = float(np.log(a[:, 8].sum() / a[:, 10].sum()))     # sum of volume so far / sum of its normal level
        groups[key] = dict(code=[r[0] for r in rows], kind=[r[1] for r in rows],
                           X=np.column_stack([a[:, :7], np.full(len(a), mkt)]), y=a[:, 7], vcut=a[:, 8],
                           tcut=a[:, 9], keep=np.array([r[13] for r in rows]))
    return groups


def stack(groups, keys_, keep=True):
    gs = [groups[k] for k in keys_ if k in groups]
    if not gs:
        return np.zeros((0, len(FEATURES))), np.zeros(0)
    X = np.vstack([g['X'][g['keep']] if keep else g['X'] for g in gs])
    y = np.concatenate([g['y'][g['keep']] if keep else g['y'] for g in gs])
    return X, y


class Model:
    """E0..E4 of the pre-registration, one cut of one market."""

    def __init__(self, X, y):
        ok = np.all(np.isfinite(X), axis=1) & np.isfinite(y)
        X, y = X[ok], y[ok]
        self.med = float(np.median(y))
        rv = X[:, 0]
        self.q = np.quantile(rv, [1 / 3, 2 / 3])
        g = self.bins(X)
        self.cell = {b: float(np.median(y[g == b])) for b in np.unique(g)}
        self.mu, self.sd = X.mean(0), X.std(0) + 1e-9
        Z = (X - self.mu) / self.sd
        A = np.column_stack([np.ones(len(Z)), Z])
        R = LAMBDA * np.eye(A.shape[1])
        R[0, 0] = 0
        self.beta = np.linalg.solve(A.T @ A + R, A.T @ y)
        self.cap = float(np.quantile(y, .99))          # 1 / (the 1% quantile of volume so far / the day's)

    def bins(self, X):
        r = np.searchsorted(self.q, X[:, 0])
        g = np.digitize(X[:, 1], [.02, .05])
        return r * 3 + g

    def predict(self, name, X):
        if name == 'E0':
            return np.zeros(len(X))
        if name == 'E1':
            return np.full(len(X), self.med)
        if name == 'E2':
            return np.array([self.cell.get(b, self.med) for b in self.bins(X)])
        Z = (np.nan_to_num(X) - self.mu) / self.sd
        e3 = self.beta[0] + Z @ self.beta[1:]
        return e3 if name == 'E3' else np.clip(e3, 0.0, self.cap)


def score(model, X, y):
    """{name: (all, rvol >= 1, sum)} median absolute errors."""
    ok = np.all(np.isfinite(X), axis=1) & np.isfinite(y)
    X, y = X[ok], y[ok]
    hot = X[:, 0] >= 0
    out = {}
    for name in MODELS:
        e = np.abs(model.predict(name, X) - y)
        a, b = float(np.median(e)), float(np.median(e[hot])) if hot.any() else float('nan')
        out[name] = (a, b, a + b)
    return out


def choose(sc):
    best = min(MODELS, key=lambda n: sc[n][2])
    for n in MODELS:                                   # the simplest within 2% of the best
        if sc[n][2] <= sc[best][2] * 1.02:
            return n
    return best


def fit(market):
    """Fit, choose on the training data, predict every test (code, day, cut); notes the volume errors too."""
    P = IS.panel(market)
    uni = IS.universe(market)
    D = days(market)
    rec = records(market, uni)
    log(market, 'records', len(rec))
    test = set(D['test'])
    if market == 'cn':
        train_days = None
    else:
        train_days = {d for (_, d) in rec if TRAIN[0] <= d <= TRAIN[1]}
    pool_days = {d for (_, d) in rec}
    wanted = [(c, d) for (c, d) in rec if d in test or (train_days and d in train_days) or
              (market == 'cn' and d < max(test))]
    fm0 = {}
    for cut in CUTS[market]:                           # f_m from the training sessions (A-shares: before the test)
        src = [rec[k] for k in wanted if (train_days and k[1] in train_days) or
               (market == 'cn' and k[1] < min(test))] or [rec[k] for k in wanted]
        fm0[cut] = float(np.median([r[2][cut][3] / r[1][4] for r in src if cut in r[2] and r[1][4] > 0]))
    rows = features(P, rec, market, fm0, wanted)
    del rec
    gc.collect()
    out = dict(market=market, fm=fm0, cuts={}, predictions={})
    for cut in CUTS[market]:
        if market == 'cn':                             # expanding window: fit on the sessions before each day
            chosen, per_day, sel = None, {}, defaultdict(list)
            order = sorted(pool_days)
            for i, day in enumerate(sorted(test)):
                past = [x for x in order if x < day]
                if len(past) < CN_MIN_TRAIN:
                    continue
                m = Model(*stack(rows, [(x, cut) for x in past]))
                per_day[day] = m
                if i < N_DAYS // 2 and (day, cut) in rows:     # selection: the first half, out of sample
                    for name, v in score(m, *stack(rows, [(day, cut)], keep=False)).items():
                        sel[name].append(v)
            sc = {n: tuple(np.mean(np.array(v), axis=0).tolist()) for n, v in sel.items()}
            chosen = choose(sc)
            out['cuts'][cut] = dict(score_select=sc, chosen=chosen, select_days=sorted(test)[:N_DAYS // 2],
                                    model_days=sorted(test)[N_DAYS // 2:])
            models = per_day
        else:
            X, y = stack(rows, [(x, cut) for x in sorted(train_days)])
            m = Model(X, y)
            sc = score(m, X, y)
            chosen = choose(sc)
            out['cuts'][cut] = dict(score_train=sc, chosen=chosen, n_train=len(y),
                                    beta=dict(zip(('const',) + FEATURES, m.beta.tolist())))
            models = {day: m for day in test}
        test_err = defaultdict(list)
        for day in sorted(test):
            m, g = models.get(day), rows.get((day, cut))
            if m is None or g is None:
                continue
            for name in ('E0', chosen):
                e = np.abs(m.predict(name, g['X']) - g['y'])
                test_err[name] += e[np.isfinite(e)].tolist()
            pred = m.predict(chosen, g['X'])
            for i, code in enumerate(g['code']):
                if np.isfinite(pred[i]):
                    out['predictions'].setdefault(day, {}).setdefault(cut, {})[code] = \
                        [float(np.exp(pred[i])), float(g['vcut'][i]), float(g['tcut'][i]), g['kind'][i]]
        out['cuts'][cut]['test_mae'] = {n: float(np.median(v)) for n, v in test_err.items()}
        log(market, cut, 'chosen', chosen, 'test median |error|', out['cuts'][cut]['test_mae'])
    (WORK / f'i2_{market}_model.json').write_text(json.dumps(out), encoding='utf-8')
    return out


# ----- the provisional rows -----
def row_for(P, d, parts_by_code, cut, scheme, pred=None, cause=None):
    """D's row with every name of parts_by_code provisional at `cut`: V0 (volume so far), 'model' (the chosen
    estimate of the full day), or a cause put back (true close / high-low / volume)."""
    row = {k: np.full(len(P['codes']), np.nan) for k in ('open', 'high', 'low', 'close', 'volume', 'turnover', 'raw_close')}
    covered = []
    for j, c in enumerate(str(c) for c in P['codes']):
        got = parts_by_code.get(c)
        if got is None or not np.isfinite(P['close'][d, j]):
            continue
        kind, full, parts = got
        if cut not in parts or not parts[cut][3] > 0:
            continue
        h, l, cl, v, t = parts[cut]
        if kind == 'recent':
            k = float(P['close'][d, j] / P['raw_close'][d, j])
            vol, to = v / k, t
        else:
            k = float(np.median([P['open'][d, j] / full[0], P['high'][d, j] / full[1], P['low'][d, j] / full[2]]))
            vol = P['volume'][d, j] * v / full[4]
            to = P['turnover'][d, j] * (t / full[5] if full[5] > 0 else v / full[4])
        if scheme == 'model':
            p = (pred or {}).get(c)
            if p is not None:
                vol, to = p[1] * p[0], to * p[0]
        op = float(P['open'][d, j])
        hi, lo, close = h * k, l * k, cl * k
        if cause == 'close':
            close = float(P['close'][d, j])
        elif cause == 'range':
            hi, lo = float(P['high'][d, j]), float(P['low'][d, j])
        elif cause == 'volume':
            vol, to = float(P['volume'][d, j]), float(P['turnover'][d, j])
        row['open'][j], row['close'][j] = op, close
        row['raw_close'][j] = close / k
        row['high'][j], row['low'][j] = max(hi, op, close), min(lo, op, close)
        row['volume'][j], row['turnover'][j] = vol, to
        covered.append(c)
    return row, covered


def plan(market):
    main, early = MAIN[market], EARLY[market]
    return ([('true', 'true', None)] + [(c, 'V0', None) for c in CUTS[market]] +
            [(c, 'model', None) for c in early + (main,)] + [(c, 'V0:volume', 'volume') for c in early] +
            [(main, f'V0:{x}', x) for x in ('close', 'range')])        # V0:volume at the main cut is in the list


def copy_i1(market, path):
    """I1 records of the same day, cut and scheme (same code, same data) into the I2 file."""
    src = WORK / f'{market}.jsonl'
    if path.exists() or not src.exists():
        return
    want = {(c, s) for c, s, _ in plan(market)} | {(MAIN[market], 'V0:volume')}
    with path.open('w', encoding='utf-8') as out:
        for line in src.open(encoding='utf-8'):
            r = json.loads(line)
            if (r['cut'], r['scheme']) in want:
                r['kind'] = 'recent'
                out.write(json.dumps(r) + '\n')


def run(market):
    import warnings
    warnings.simplefilter('ignore', RuntimeWarning)
    np.seterr(invalid='ignore', divide='ignore')
    D = days(market)
    model = json.loads((WORK / f'i2_{market}_model.json').read_text(encoding='utf-8'))
    P = IS.panel(market)
    pdays = [str(d) for d in P['days']]
    uni = IS.universe(market)
    path = WORK / f'i2_{market}.jsonl'
    copy_i1(market, path)
    done = {(r['day'], r['cut'], r['scheme']) for r in map(json.loads, path.open(encoding='utf-8'))} \
        if path.exists() else set()
    steps = plan(market) + [(MAIN[market], 'V0:volume', 'volume')]
    local = {}                                         # every local test day in one pass over the local sets
    want = set(D['local'])
    for chunk in local_chunks(market, uni) if want else ():
        for (c, day), v in compact(MN.aggregate((r for r in chunk if r[1] in want), CUTS[market]),
                                   market, 'local').items():
            local.setdefault(day, {})[c] = v
    t_rest = time.time()
    with path.open('a', encoding='utf-8') as out:
        for day in D['test']:
            kind = 'local' if day in D['local'] else 'recent'
            todo = [s for s in steps if (day, s[0], s[1]) not in done]
            if not todo:
                continue
            if kind == 'recent':
                parts = {c: v for (c, _), v in compact(MN.aggregate(MN.stream(MN.latest(market), {day}, uni),
                                                                    CUTS[market]), market, kind).items()}
            else:
                parts = local.get(day, {})
            d = pdays.index(day)
            for cut, scheme, cause in todo:
                t0 = time.time()
                if cut == 'true':
                    rec = dict(day=day, kind=kind, cut=cut, scheme=scheme,
                               systems=IS.decide(IS.cut_at(P, d), market, day))
                else:
                    pred = model['predictions'].get(day, {}).get(cut) if scheme == 'model' else None
                    if scheme == 'model' and not pred:
                        continue                       # A-shares: no model for the day (selection half)
                    row, covered = row_for(P, d, parts, cut, 'model' if scheme == 'model' else 'V0', pred, cause)
                    rec = dict(day=day, kind=kind, cut=cut, scheme=scheme, covered=covered,
                               chosen=model['cuts'][cut]['chosen'] if scheme == 'model' else None,
                               systems=IS.decide(IS.cut_at(P, d, row), market, day))
                out.write(json.dumps(rec) + '\n')
                out.flush()
                log(market, day, kind, cut, scheme, f'{time.time() - t0:.0f}s')
                if time.time() - t_rest > IS.WORK_SECONDS:
                    log(f'rest {IS.REST_SECONDS // 60} min')
                    time.sleep(IS.REST_SECONDS)
                    t_rest = time.time()


# ----- metrics -----
def load(market):
    rows = defaultdict(dict)
    for r in map(json.loads, (WORK / f'i2_{market}.jsonl').open(encoding='utf-8')):
        rows[r['day']][(r['cut'], r['scheme'])] = r
    return rows


def keys(sysres, what, covered=None):
    k = IS.keys(sysres, what)
    return {x for x in k if x[0] in covered} if covered is not None and what == 'sig' else k


def summarize(market, only=None):
    """{(kind, cut, scheme): totals}: same / false / missed per system and setup, price gaps, stop widths, and the
    side-adjusted move from the provisional price to the close of every provisional buy (same and false); `only`:
    these days alone (A-shares: the model is judged on the second half of its test days)."""
    P = IS.panel(market)
    pdays = {str(d): i for i, d in enumerate(P['days'])}
    col = {str(c): j for j, c in enumerate(P['codes'])}
    out = {}
    for day, r in sorted(load(market).items()):
        true = r.get(('true', 'true'))
        if not true or (only is not None and day not in only):
            continue
        d = pdays[day]
        for (cut, scheme), prov in r.items():
            if cut == 'true':
                continue
            kind = prov.get('kind', 'recent')
            cov = set(prov['covered']) if kind == 'local' else None
            for grp in (kind, 'all'):
                a = out.setdefault(f'{grp}|{cut}|{scheme}', dict(days=[], counts=defaultdict(lambda: [0, 0, 0]),
                                                                setup=defaultdict(lambda: [0, 0, 0]), gap=[],
                                                                width=[], move_same=[], move_false=[]))
                a['days'].append(day)
                for sid, t in true['systems'].items():
                    p = prov['systems'][sid]
                    for what in ('sig', 'buys', 'sells'):
                        x, y = keys(p, what, cov), keys(t, what, cov)
                        c = (len(x & y), len(x - y), len(y - x))
                        for key in (f'{sid}|{what}', f'all|{what}'):
                            a['counts'][key] = [u + v for u, v in zip(a['counts'][key], c)]
                        if what == 'sig':
                            for s, idx in [(z[2], 0) for z in x & y] + [(z[2], 1) for z in x - y] + \
                                          [(z[2], 2) for z in y - x]:
                                a['setup'][f'{sid}|{s}'][idx] += 1
                    tb = {(z[0], z[1], z[2]): z for z in t['buys']}
                    for z in p['buys']:
                        if z[2] or not z[3]:
                            continue
                        mv = z[1] * (float(P['close'][d, col[z[0]]]) / z[3] - 1)
                        tz = tb.get((z[0], z[1], z[2]))
                        if tz:
                            a['move_same'].append(mv)
                            a['gap'].append(tz[3] / z[3] - 1)
                            if z[4] and tz[4]:
                                a['width'].append(abs(tz[3] - tz[4]) / tz[3] - abs(z[3] - z[4]) / z[3])
                        else:
                            a['move_false'].append(mv)
    res = {}
    for k, a in out.items():
        def st(v):
            v = np.array(v, float)
            return dict(n=len(v), mean=float(v.mean()) if len(v) else None,
                        median=float(np.median(v)) if len(v) else None,
                        abs_median=float(np.median(np.abs(v))) if len(v) else None,
                        abs_p90=float(np.quantile(np.abs(v), .9)) if len(v) else None,
                        win=float(np.mean(v > 0)) if len(v) else None)
        res[k] = dict(days=len(set(a['days'])), counts=dict(a['counts']), setup=dict(a['setup']), gap=st(a['gap']),
                      width=st(a['width']), move_same=st(a['move_same']), move_false=st(a['move_false']))
    return res


def summary():
    out = {}
    for m in ('us', 'hk', 'cn'):
        if (WORK / f'i2_{m}.jsonl').exists():
            model = json.loads((WORK / f'i2_{m}_model.json').read_text(encoding='utf-8'))
            out[m] = dict(days=days(m), model={c: {k: v for k, v in x.items()} for c, x in model['cuts'].items()},
                          fm=model['fm'], agg=summarize(m))
            if m == 'cn':
                out[m]['agg_model_days'] = summarize(m, set(model['cuts'][MAIN[m]]['model_days']))
    (REPORTS / 'intraday_i2_summary.json').write_text(json.dumps(out, indent=1, default=float), encoding='utf-8')
    return out


if __name__ == '__main__':
    cmd = sys.argv[1] if len(sys.argv) > 1 else ''
    if cmd == 'days':
        print(json.dumps(make_days(sys.argv[2]), indent=1))
    elif cmd == 'model':
        fit(sys.argv[2])
    elif cmd == 'run':
        run(sys.argv[2])
    elif cmd == 'summary':
        summary()
    else:
        raise SystemExit(__doc__)
