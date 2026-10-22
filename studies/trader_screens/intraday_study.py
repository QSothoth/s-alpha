"""Provisional (pre-close) daily bars against the closing bars: how far the seven registered systems' decisions move,
and whether the partial volume should be scaled up.  Pre-registration notes/INTRADAY_PREREG_CN.md (I1); report
reports/INTRADAY_CN.md.

For a test day D, cut C and scheme V the panel is the true daily panel up to D - 1 plus D's provisional bar from the
five- / one-minute bars ending at or before C (prices unscaled, volume and turnover scaled by V); every registered
system runs on it and its D decisions (entry candidates, buys, exits) are stored, beside the same on the true bar.

    PY="nice -n 19 env OPENBLAS_NUM_THREADS=1 PYTHONUTF8=1 /opt/futu-opend/venv/bin/python"
    $PY -m studies.trader_screens.intraday_study days us             # the test days (selection / validation)
    $PY -m studies.trader_screens.intraday_study reconcile us        # minute aggregate vs daily bars
    $PY -m studies.trader_screens.intraday_study select us           # selection half: V0 at every cut, V1-V3 main cut
    $PY -m studies.trader_screens.intraday_study choose              # the scheme, from the three selection halves
    $PY -m studies.trader_screens.intraday_study validate us         # once: V0 and the chosen scheme, every cut
    $PY -m studies.trader_screens.intraday_study summary             # reports/intraday_summary.json

Raw decisions go to data/trader-screens/intraday-study/<market>.jsonl (resumable; one line per day, cut, scheme).
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

from . import minute as MN

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / 'data'
WORK = DATA / 'trader-screens' / 'intraday-study'
HERE = Path(__file__).resolve().parent
REPORTS = HERE / 'reports'
CHOICE = HERE / 'notes' / 'intraday_choice.json'

CUTS = {'us': ('15:40', '15:45', '15:50', '15:55'), 'hk': ('15:40', '15:45', '15:50', '15:55'),
        'cn': ('14:40', '14:45', '14:50', '14:55')}
MAIN = {'us': '15:50', 'hk': '15:50', 'cn': '14:50'}
LAST_BAR = {'us': '16:00', 'hk': '16:00', 'cn': '15:00'}
SCHEMES = ('V0', 'V1', 'V2', 'V3')
LOCAL_N = {'us': 0, 'hk': 0, 'cn': 0}        # I1-lite: no local minute sets (I1 had us 12, hk 10)
LITE_DAYS = 5                                  # I1-lite: the last 5 full sessions of the one fetch
LOCAL_MIN = {'us': 150, 'hk': 100}
US_LOCAL = ('martin-luk-k5-r8', 'p3-k5-validation-raw/k5', 'preopen-s20-valid-v1/k5', 'preopen-s20-k5-raw-a/k5',
            'preopen-s20-k5-raw-b/k5', 'preopen-us-k5-raw/k5')       # first wins for a code
HK_LOCAL = ('watch-hk1m-holdout-2025h2-v1', 'watch-hk1m-train-v1', 'watch-hk1m-valid-v1')
START = '2024-01-02'
PRIOR = 20                     # V2: the stock's last <= 20 minute days before D
PRIOR_MIN = 5
WORK_SECONDS, REST_SECONDS = 40 * 60, 8 * 60     # pause the CPU (vps: two busy cores for hours shut it down)


def log(*a):
    print(time.strftime('%H:%M:%S'), *a, flush=True)


# ----- minute sources -----
def universe(market):
    from studies import trader_data as TD
    return {s['code'] for s in TD.dataset(market, 'live').stocks()}


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


def opener(f):
    return gzip.open(f, 'rt', encoding='utf-8', newline='') if f.suffix == '.gz' else open(f, newline='')


def local_rows(market, want_days=None, codes=None):
    """yield (code, day, hhmm, o, h, l, c, v, t) of the local minute sets (want_days: only those days)."""
    if market == 'us':
        for code, f in sorted(us_local_files().items()):
            if codes is not None and code not in codes:
                continue
            with opener(f) as fh:
                rd = csv.reader(fh)
                head = next(rd)
                ix = [head.index(k) for k in ('time_key', 'open', 'high', 'low', 'close', 'volume', 'turnover')]
                for r in rd:
                    day = r[ix[0]][:10]
                    if want_days is not None and day not in want_days:
                        continue
                    yield (code, day, r[ix[0]][11:16], *(float(r[i]) for i in ix[1:]))
    elif market == 'hk':
        for src in HK_LOCAL:
            with gzip.open(DATA / src / 'bars_1m.csv.gz', 'rt', encoding='utf-8', newline='') as fh:
                rd = csv.reader(fh)
                head = next(rd)
                ix = [head.index(k) for k in ('code', 'time_key', 'open', 'high', 'low', 'close', 'volume',
                                              'turnover')]
                for r in rd:
                    day = r[ix[1]][:10]
                    if want_days is not None and day not in want_days:
                        continue
                    if codes is not None and r[ix[0]] not in codes:
                        continue
                    yield (r[ix[0]], day, r[ix[1]][11:16], *(float(r[i]) for i in ix[2:]))


def recent_path(market):
    got = sorted(MN.K5.glob(f'{market}_????-??-??.csv.gz'))
    return got[-1] if got else None


# ----- test days -----
def days(market, P=None):
    """{'local': [...], 'recent': [...], 'select': [...], 'validate': [...]} (pre-registered rules)."""
    path = WORK / f'{market}_days.json'
    if path.exists():
        return json.loads(path.read_text(encoding='utf-8'))
    raise SystemExit(f'run `days {market}` first')


def make_days(market):
    from studies import trader_data as TD
    P = TD.dataset(market, 'live').panel()
    pdays = [str(d) for d in P['days']]
    uni = universe(market)
    local = []
    if LOCAL_N.get(market):
        count = defaultdict(int)
        for code, day, hhmm, *_ in local_rows(market):
            if hhmm == LAST_BAR[market] and code in uni and day >= START:
                count[day] += 1
        ok = sorted(d for d, n in count.items() if n >= LOCAL_MIN[market] and d in pdays)
        idx = np.round(np.linspace(0, len(ok) - 1, LOCAL_N[market])).astype(int)
        local = [ok[i] for i in idx]
        log(market, 'local days with >=', LOCAL_MIN[market], 'names:', len(ok), ok[:1], ok[-1:])
    recent = []
    rp = recent_path(market)
    if rp:
        count = defaultdict(int)
        for (code, day), s in aggregate(stream_recent(rp, codes=uni), ()).items():
            if complete(s, market):
                count[day] += 1
        recent = sorted(d for d, n in count.items() if n >= .5 * len(uni) and d in pdays and d not in local)
        log(market, 'recent full-universe days', recent, {d: count[d] for d in recent})
    out = dict(local=local, recent=recent[-LITE_DAYS:], earlier=recent[:-LITE_DAYS], select=[],
               validate=recent[-LITE_DAYS:], recent_file=rp.name if rp else None)   # I1-lite: no halves
    path = WORK / f'{market}_days.json'
    if path.exists():                                     # US: recent days added after its selection half ran
        old = json.loads(path.read_text(encoding='utf-8'))
        if old['select'] != out['select']:
            raise SystemExit(f"{market}: the selection half would change {old['select']} -> {out['select']}")
    WORK.mkdir(parents=True, exist_ok=True)
    (WORK / f'{market}_days.json').write_text(json.dumps(out, indent=1), encoding='utf-8')
    return out


def stream_recent(path, need=None, codes=None):
    """(code, day, hhmm, o, h, l, c, v, t) of a minute.fetch file, one row at a time (the US file holds ~3.4M bars:
    read whole, it took the 4GB machine out of memory)."""
    with gzip.open(path, 'rt', encoding='utf-8', newline='') as f:
        rows = csv.reader(f)
        if tuple(next(rows)) != MN.HEADER:
            raise ValueError(f'unexpected header in {path}')
        for code, tk, *v in rows:
            day = tk[:10]
            if (need is None or day in need) and (codes is None or code in codes):
                yield (code, day, tk[11:16], *map(float, v))


def aggregate(rows, cuts):
    """{(code, day): dict(first, last, last_v, parts={cut | 'full': (o, h, l, c, v, t)})} from rows in time order
    within each (code, day): the partial bar at every cut, without keeping the bars."""
    out = {}
    for code, day, hh, o, h, l, c, v, t in rows:
        s = out.get((code, day))
        if s is None:
            s = out[(code, day)] = dict(first=hh, last=hh, last_v=v, cur=[o, h, l, c, v, t], parts={})
        else:
            cur = s['cur']
            cur[1], cur[2], cur[3] = max(cur[1], h), min(cur[2], l), c
            cur[4] += v
            cur[5] += t
            s['last'], s['last_v'] = hh, v
        for cut in cuts:
            if hh <= cut:
                s['parts'][cut] = tuple(s['cur'])
    for s in out.values():
        s['parts']['full'] = tuple(s.pop('cur'))
    return out


def complete(s, market):
    """From the morning (first bar by 10:00; the first day of a 1000-bar window starts mid-session) to the close."""
    return s['first'] <= '10:00' and s['last'] == LAST_BAR[market]


def minute_for(market, test_days, P):
    """{day: {code: (kind, parts)}} for the test days, and {(code, day): {cut: f}} volume fractions for the test
    days and, for V2, every earlier minute day of the same source (>= the 20 before each test day)."""
    pdays = [str(d) for d in P['days']]
    uni = universe(market)
    di = {d: i for i, d in enumerate(pdays)}
    need = set(test_days)
    for d in test_days:                                   # V2 history: the 20 sessions before each test day
        i = di[d]
        need.update(pdays[max(0, i - PRIOR - 5):i])
    rp = recent_path(market)
    sources = []
    if rp:
        sources.append(('recent', aggregate(stream_recent(rp, need, uni), CUTS[market])))
    if LOCAL_N.get(market):
        sources.append(('local', aggregate(local_rows(market, need, uni), CUTS[market])))
    bars, frac = defaultdict(dict), {}
    for kind, g in sources:
        for (code, day), s in g.items():
            if not complete(s, market):
                continue
            tot = s['parts']['full'][4]
            if tot > 0:
                frac.setdefault((code, day), {c: s['parts'][c][4] / tot if c in s['parts'] else 0.0
                                              for c in CUTS[market]})
            if day in test_days and code not in bars[day]:
                bars[day][code] = (kind, s['parts'])
    return bars, frac


# ----- the provisional panel -----
def provisional_row(P, d, bars, cut, scheme, frac, fm, prior, subst=None):
    """D's row (dict field -> array over codes) with the covered names provisional; others stay true."""
    row = {k: P[k][d].astype(float).copy() for k in ('open', 'high', 'low', 'close', 'volume', 'turnover')}
    codes = [str(c) for c in P['codes']]
    covered = []
    for j, c in enumerate(codes):
        got = bars.get(c)
        if got is None or not np.isfinite(P['close'][d, j]):
            continue
        kind, parts = got
        part, full = parts.get(cut), parts['full']
        if part is None or not full[4] > 0:
            continue
        o, h, l, cl, v, t = part
        if kind == 'recent':                              # unadjusted: the day's adjustment factor
            k = float(P['close'][d, j] / P['raw_close'][d, j])
            vol = v / k
            to = t
        else:                                             # local adjusted sets: rescaled to our bar, ratios for v / t
            k = float(np.median([P['open'][d, j] / full[0], P['high'][d, j] / full[1], P['low'][d, j] / full[2]]))
            vol = P['volume'][d, j] * v / full[4]
            to = P['turnover'][d, j] * (t / full[5] if full[5] > 0 else v / full[4])
        op = float(P['open'][d, j])
        hi, lo, close = h * k, l * k, cl * k
        if scheme in ('V1', 'V3'):
            s_v = fm
        elif scheme == 'V2':
            s_v = prior.get(c, fm)
        else:
            s_v = 1.0
        s_t = 1.0 if scheme in ('V0', 'V3') else s_v
        vol, to = vol / s_v, to / s_t
        if subst == 'close':
            close = float(P['close'][d, j])
        elif subst == 'range':
            hi, lo = float(P['high'][d, j]), float(P['low'][d, j])
        elif subst == 'volume':
            vol, to = float(P['volume'][d, j]), float(P['turnover'][d, j])
        row['open'][j], row['close'][j] = op, close
        row['high'][j], row['low'][j] = max(hi, op, close), min(lo, op, close)
        row['volume'][j], row['turnover'][j] = vol, to
        covered.append(c)
    return row, covered


def with_row(P, d, row):
    q = {k: (v[:d + 1] if isinstance(v, np.ndarray) and v.ndim and k != 'codes' else v) for k, v in P.items()}
    for k, v in row.items():
        q[k] = q[k].copy()
        q[k][d] = v
    return q


def decide(P, market, day):
    """{system id: {'sig': [[code, side, setup]], 'buys': [[code, side, add, price, stop]],
    'sells': [[code, side, price, why]]}} of day `day` (P cut at it)."""
    from studies.trader_replication import runner, systems as SY
    from .intraday import shared
    out = {}
    with shared(P, market):
        for x in SY.all_():
            r = runner.run(x, market, 'live', 1)
            if r['last_day'] != day:
                raise RuntimeError(f'{x.id}: ends {r["last_day"]}, expected {day}')
            sig = sorted({(b['code'], b['side'], b['setup']) for b in r['buys'] if b['setup'] != '加码'}
                         | {(w['code'], w['side'], w['setup']) for w in r['wanted']})
            out[x.id] = dict(sig=[list(s) for s in sig],
                             buys=[[b['code'], b['side'], b['setup'] == '加码', b['price'], b['stop']]
                                   for b in r['buys']],
                             sells=[[s['code'], s['side'], s['price'], s['why']] for s in r['sells']])
            del r
            gc.collect()
    return out


class Pacer:
    def __init__(self):
        self.t0 = time.time()

    def tick(self):
        if time.time() - self.t0 > WORK_SECONDS:
            log(f'rest {REST_SECONDS // 60} min')
            time.sleep(REST_SECONDS)
            self.t0 = time.time()


def done_keys(market):
    path = WORK / f'{market}.jsonl'
    if not path.exists():
        return set()
    return {(r['day'], r['cut'], r['scheme']) for r in map(json.loads, path.open(encoding='utf-8'))}


def market_fraction(market, select_days, frac, cut):
    vals = [f[cut] for (c, d), f in frac.items() if d in select_days]
    return float(np.median(vals)) if vals else 1.0


def run_phase(market, phase):
    from studies import trader_data as TD
    import warnings
    warnings.simplefilter('ignore', RuntimeWarning)
    np.seterr(invalid='ignore', divide='ignore')
    D = days(market)
    test = D['validate'] if phase == 'lite' else D[phase]
    P = TD.dataset(market, 'live').panel()
    pdays = [str(d) for d in P['days']]
    bars, frac = minute_for(market, set(D['select']) | set(test), P)
    est = set(D['earlier']) if phase == 'lite' else set(D['select'])   # lite: f_m from the days before the test
    fm = {c: market_fraction(market, est, frac, c) for c in CUTS[market]}
    log(market, phase, 'f_m', fm, 'from', len(est), 'days')
    if phase == 'lite':
        plan = [(c, 'V0', None) for c in CUTS[market]] + [(MAIN[market], 'V1', None)] + \
               [(MAIN[market], 'V0', s) for s in ('close', 'range', 'volume')]
    elif phase == 'select':
        plan = [(c, 'V0', None) for c in CUTS[market]] + [(MAIN[market], v, None) for v in SCHEMES[1:]] + \
               [(MAIN[market], 'V0', s) for s in ('close', 'range', 'volume')]
    else:
        chosen = json.loads(CHOICE.read_text(encoding='utf-8'))['chosen']
        plan = [(c, v, None) for c in CUTS[market] for v in sorted({'V0', chosen})] + \
               [(MAIN[market], 'V0', s) for s in ('close', 'range', 'volume')]
    done = done_keys(market)
    out = (WORK / f'{market}.jsonl').open('a', encoding='utf-8')
    pace = Pacer()
    for day in test:
        d = pdays.index(day)
        known = set(pdays[:d])
        prior = {}
        for c in CUTS[market]:
            pc = {}
            for (code, dd), f in frac.items():
                pc.setdefault(code, []).append((dd, f[c]))
            prior[c] = {}
            for code, lst in pc.items():
                past = sorted(x for x in lst if x[0] in known)[-PRIOR:]
                if len(past) >= PRIOR_MIN:
                    prior[c][code] = float(np.mean([x[1] for x in past]))
        kind = 'local' if day in D['local'] else 'recent'
        if (day, 'true', 'true') not in done:
            t0 = time.time()
            res = decide({k: (v[:d + 1] if isinstance(v, np.ndarray) and v.ndim and k != 'codes' else v)
                          for k, v in P.items()}, market, day)
            out.write(json.dumps(dict(day=day, kind=kind, cut='true', scheme='true', systems=res)) + '\n')
            out.flush()
            log(market, day, 'true', f'{time.time() - t0:.0f}s')
            pace.tick()
        for cut, scheme, subst in plan:
            key = (day, cut, scheme if subst is None else f'{scheme}:{subst}')
            if key in done:
                continue
            t0 = time.time()
            row, covered = provisional_row(P, d, bars.get(day, {}), cut, scheme, frac, fm[cut], prior[cut], subst)
            res = decide(with_row(P, d, row), market, day)
            out.write(json.dumps(dict(day=day, kind=kind, cut=cut, scheme=key[2], covered=covered, systems=res,
                                      fm=fm[cut])) + '\n')
            out.flush()
            log(market, day, cut, key[2], f'{len(covered)} names', f'{time.time() - t0:.0f}s')
            pace.tick()
    out.close()


# ----- the reconciliation -----
def reconcile(market):
    """Full-session minute aggregates of the recent fetch against our unadjusted daily bars."""
    from studies import trader_data as TD
    P = TD.dataset(market, 'live').panel()
    pdays = {str(d): i for i, d in enumerate(P['days'])}
    col = {str(c): j for j, c in enumerate(P['codes'])}
    rp = recent_path(market)
    diffs = defaultdict(list)
    n = 0
    for (code, day), s in aggregate(stream_recent(rp, codes=set(col)), CUTS[market][-1:]).items():
        if day not in pdays or not complete(s, market):
            continue
        d, j = pdays[day], col[code]
        rc = P['raw_close'][d, j]
        if not np.isfinite(rc) or not P['volume'][d, j] > 0:
            continue
        k = P['close'][d, j] / rc
        o, h, l, c, v, t = s['parts']['full']
        truth = dict(open=P['open'][d, j] / k, high=P['high'][d, j] / k, low=P['low'][d, j] / k, close=rc,
                     volume=P['volume'][d, j] * k, turnover=P['turnover'][d, j])
        mine = dict(open=o, high=h, low=l, close=c, volume=v, turnover=t)
        for key in truth:
            diffs[key].append(mine[key] / truth[key] - 1 if truth[key] else np.nan)
        before = s['parts'].get(CUTS[market][-1])          # the last cut: 15:55 / 14:55
        diffs['last_bar_volume_share'].append(s['last_v'] / v if v else np.nan)
        diffs['close_vs_prior_bar'].append(rc / before[3] - 1 if before else np.nan)
        n += 1
    out = dict(market=market, file=rp.name, pairs=n)
    for key, v in diffs.items():
        a = np.abs(np.array(v, float))
        a = a[np.isfinite(a)]
        out[key] = dict(median=float(np.median(np.array(v)[np.isfinite(v)])), abs_median=float(np.median(a)),
                        within_0_1pct=float(np.mean(a <= .001)), within_1pct=float(np.mean(a <= .01)),
                        p90_abs=float(np.quantile(a, .9)))
    REPORTS.mkdir(exist_ok=True)
    (REPORTS / f'intraday_reconcile_{market}.json').write_text(json.dumps(out, indent=1), encoding='utf-8')
    print(json.dumps(out, indent=1))
    return out


# ----- metrics -----
def load(market):
    rows = defaultdict(dict)
    for r in map(json.loads, (WORK / f'{market}.jsonl').open(encoding='utf-8')):
        rows[r['day']][(r['cut'], r['scheme'])] = r
    return rows


def keys(sysres, what, covered=None):
    if what == 'sig':
        return {tuple(x) for x in sysres['sig'] if covered is None or x[0] in covered}
    if what == 'buys':
        return {(x[0], x[1], x[2]) for x in sysres['buys']}
    return {(x[0], x[1]) for x in sysres['sells']}


def compare(true, prov, covered):
    """Per system and what: [same, false, missed], plus price / stop gaps of shared buys and per-setup counts."""
    cov = set(covered) if covered is not None else None
    out = {}
    for sid, t in true['systems'].items():
        p = prov['systems'][sid]
        o = {}
        for what in ('sig', 'buys', 'sells'):
            a, b = keys(p, what, cov), keys(t, what, cov)
            o[what] = [len(a & b), len(a - b), len(b - a)]
            if what == 'sig':
                per = defaultdict(lambda: [0, 0, 0])
                for x in a & b:
                    per[x[2]][0] += 1
                for x in a - b:
                    per[x[2]][1] += 1
                for x in b - a:
                    per[x[2]][2] += 1
                o['setup'] = dict(per)
            o[what + '_diff'] = [sorted(map(list, a - b)), sorted(map(list, b - a))]
        tb = {(x[0], x[1], x[2]): x for x in t['buys']}
        gaps = []
        for x in p['buys']:
            y = tb.get((x[0], x[1], x[2]))
            if y and x[3]:
                g = dict(gap=y[3] / x[3] - 1)
                if x[4] and y[4]:
                    g['width'] = abs(y[3] - y[4]) / y[3] - abs(x[3] - x[4]) / x[3]
                gaps.append(g)
        o['gaps'] = gaps
        out[sid] = o
    return out


def summarize(market):
    rows = load(market)
    D = days(market)
    res = {}
    for day, r in sorted(rows.items()):
        true = r.get(('true', 'true'))
        if not true:
            continue
        for (cut, scheme), prov in r.items():
            if cut == 'true':
                continue
            res.setdefault(f'{cut}|{scheme}', {})[day] = compare(true, prov, prov.get('covered')
                                                                if prov.get('kind') == 'local' else None)
    agg = {}
    for key, per_day in res.items():
        a = dict(days=sorted(per_day), select=[d for d in per_day if d in D['select']],
                 validate=[d for d in per_day if d in D['validate']])
        for seg in ('select', 'validate', 'all'):
            ds = per_day if seg == 'all' else {d: v for d, v in per_day.items() if d in D[seg]}
            if not ds:
                continue
            tot = defaultdict(lambda: np.zeros(3, int))
            setup = defaultdict(lambda: np.zeros(3, int))
            gaps = []
            for d, v in ds.items():
                for sid, o in v.items():
                    for what in ('sig', 'buys', 'sells'):
                        tot[(sid, what)] += o[what]
                        tot[('all', what)] += o[what]
                    for s, c in o['setup'].items():
                        setup[(sid, s)] += c
                    gaps += o['gaps']
            g = np.array([x['gap'] for x in gaps]) if gaps else np.zeros(0)
            w = np.array([x['width'] for x in gaps if 'width' in x]) if gaps else np.zeros(0)
            a[seg] = dict(
                counts={f'{s}|{w_}': v.tolist() for (s, w_), v in tot.items()},
                setup={f'{s}|{k}': v.tolist() for (s, k), v in setup.items()},
                gap=dict(n=len(g), abs_median=float(np.median(np.abs(g))) if len(g) else None,
                         abs_p90=float(np.quantile(np.abs(g), .9)) if len(g) else None,
                         median=float(np.median(g)) if len(g) else None),
                width=dict(n=len(w), abs_median=float(np.median(np.abs(w))) if len(w) else None,
                           median=float(np.median(w)) if len(w) else None),
                days=len(ds))
        agg[key] = a
    return agg, res


def attribution(market, res):
    """Main cut, V0: each mismatch (false or missed) of buys / sells / signals, by the substitution that removes it."""
    rows = load(market)
    cut = MAIN[market]
    out = defaultdict(lambda: defaultdict(int))
    for day, r in rows.items():
        true, base = r.get(('true', 'true')), r.get((cut, 'V0'))
        if not true or not base:
            continue
        cov = set(base['covered']) if base.get('kind') == 'local' else None
        subs = {s: r.get((cut, f'V0:{s}')) for s in ('close', 'range', 'volume')}
        if not all(subs.values()):
            continue
        for sid, t in true['systems'].items():
            for what in ('sig', 'buys', 'sells'):
                a, b = keys(base['systems'][sid], what, cov), keys(t, what, cov)
                for x, side in [(x, 'false') for x in a - b] + [(x, 'missed') for x in b - a]:
                    fixed = [s for s, rr in subs.items()
                             if (x in keys(rr['systems'][sid], what, cov)) == (x in b)]
                    why = fixed[0] if len(fixed) == 1 else ('several' if fixed else 'joint')
                    out[f'{what}|{side}'][why] += 1
                    out[f'{what}|{side}|{sid}'][why] += 1
    return {k: dict(v) for k, v in out.items()}


def choose():
    """Pre-registered: fewest (false + missed) buys + sells at the main cut over the three selection halves; a
    scheme replaces V0 only with >= 10% fewer."""
    tot = defaultdict(int)
    per = {}
    for m in ('us', 'hk', 'cn'):
        agg, _ = summarize(m)
        per[m] = {}
        for v in SCHEMES:
            a = agg.get(f'{MAIN[m]}|{v}', {}).get('select')
            if not a:
                continue
            c = a['counts']
            n = sum(c['all|buys'][1:]) + sum(c['all|sells'][1:])
            per[m][v] = n
            tot[v] += n
    base = tot['V0']
    best = min(SCHEMES, key=lambda v: (tot.get(v, 1e18), v != 'V0'))
    chosen = best if tot[best] <= .9 * base else 'V0'
    out = dict(rule='min (false + missed) buys + sells at the main cut, selection halves of us + hk + cn; '
                    'replace V0 only with >= 10% fewer', totals=dict(tot), per_market=per, best=best, chosen=chosen,
               utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()))
    CHOICE.write_text(json.dumps(out, indent=1), encoding='utf-8')
    print(json.dumps(out, indent=1))
    return out


def summary():
    out = {}
    for m in ('us', 'hk', 'cn'):
        if not (WORK / f'{m}.jsonl').exists():
            continue
        agg, res = summarize(m)
        out[m] = dict(days=days(m), agg=agg, attribution=attribution(m, res))
    REPORTS.mkdir(exist_ok=True)
    (REPORTS / 'intraday_summary.json').write_text(json.dumps(out, indent=1, default=float), encoding='utf-8')
    return out


if __name__ == '__main__':
    cmd = sys.argv[1]
    if cmd == 'days':
        print(json.dumps(make_days(sys.argv[2]), indent=1))
    elif cmd == 'reconcile':
        reconcile(sys.argv[2])
    elif cmd in ('select', 'validate', 'lite'):
        run_phase(sys.argv[2], cmd)
    elif cmd == 'choose':
        choose()
    elif cmd == 'summary':
        summary()
    else:
        raise SystemExit(__doc__)
