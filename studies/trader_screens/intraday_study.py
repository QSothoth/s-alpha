"""Provisional (pre-close) daily bars against the closing bars: how far the seven registered systems' decisions move,
and whether the partial volume should be scaled up.  Pre-registration notes/INTRADAY_PREREG_CN.md (I1-lite, the run
version); report reports/INTRADAY_CN.md.

For a test day D and cut C the panel is the true daily panel up to D - 1 plus D's provisional bar from the
five-minute bars ending at or before C (minute.py; prices as they are, volume and turnover as they are (V0) or
divided by the market's cumulative share f_m(C) (V1)); every registered system runs on it and its D decisions
(entry candidates, buys, exits) are stored beside the same on the true bar.  Test days: the last 5 full sessions of
the one fetch; f_m comes from the fetch's earlier full sessions only.

    PY="nice -n 19 env OPENBLAS_NUM_THREADS=1 PYTHONUTF8=1 /opt/futu-opend/venv/bin/python"
    $PY -m studies.trader_screens.minute fetch us                    # once: the five-minute bars (no quota)
    $PY -m studies.trader_screens.intraday_study reconcile us        # minute aggregate vs daily bars
    $PY -m studies.trader_screens.intraday_study days us             # the test days
    $PY -m studies.trader_screens.intraday_study lite us             # V0 at every cut; V1 and the causes at the main cut
    $PY -m studies.trader_screens.intraday_study early us            # V0 at 1 h / 3 h after the open
    $PY -m studies.trader_screens.intraday_study summary             # reports/intraday_summary.json

Raw decisions go to data/trader-screens/intraday-study/<market>.jsonl (resumable; one line per day, cut, scheme).
"""
from __future__ import annotations

import gc
import json
import sys
import time
from collections import defaultdict
from pathlib import Path

import numpy as np

from . import minute as MN

ROOT = Path(__file__).resolve().parents[2]
WORK = ROOT / 'data' / 'trader-screens' / 'intraday-study'
REPORTS = Path(__file__).resolve().parent / 'reports'

CUTS = {'us': ('15:40', '15:45', '15:50', '15:55'), 'hk': ('15:40', '15:45', '15:50', '15:55'),
        'cn': ('14:40', '14:45', '14:50', '14:55')}
MAIN = {'us': '15:50', 'hk': '15:50', 'cn': '14:50'}
TEST_DAYS = 5
CAUSES = ('close', 'range', 'volume')        # the provisional field replaced by the true one
WORK_SECONDS, REST_SECONDS = 40 * 60, 8 * 60     # pause the CPU (vps: two busy cores for hours shut it down)


def log(*a):
    print(time.strftime('%H:%M:%S'), *a, flush=True)


def universe(market):
    from studies import trader_data as TD
    return {s['code'] for s in TD.dataset(market, 'live').stocks()}


def panel(market):
    from studies import trader_data as TD
    return TD.dataset(market, 'live').panel()


# ----- test days -----
def days(market):
    path = WORK / f'{market}_days.json'
    if not path.exists():
        raise SystemExit(f'run `days {market}` first')
    return json.loads(path.read_text(encoding='utf-8'))


def make_days(market):
    """The fetch's full sessions with >= half the list complete and in our daily panel: the last TEST_DAYS are the
    test days, the earlier ones estimate f_m."""
    pdays = {str(d) for d in panel(market)['days']}
    uni = universe(market)
    rp = MN.latest(market)
    count = defaultdict(int)
    for (code, day), s in MN.aggregate(MN.stream(rp, codes=uni), ()).items():
        if MN.complete(s, market):
            count[day] += 1
    full = sorted(d for d, n in count.items() if n >= .5 * len(uni) and d in pdays)
    out = dict(test=full[-TEST_DAYS:], earlier=full[:-TEST_DAYS], file=rp.name,
               names={d: count[d] for d in full})
    WORK.mkdir(parents=True, exist_ok=True)
    (WORK / f'{market}_days.json').write_text(json.dumps(out, indent=1), encoding='utf-8')
    return out


def minute_for(market, D, cuts=None):
    """{day: {code: parts}} for the test days and {(code, day): {cut: cumulative volume share}} for every full
    session of the fetch."""
    cuts = cuts or CUTS[market]
    rp = MN.latest(market)
    bars, frac = defaultdict(dict), {}
    for (code, day), s in MN.aggregate(MN.stream(rp, set(D['test']) | set(D['earlier']), universe(market)),
                                       cuts).items():
        if not MN.complete(s, market):
            continue
        tot = s['parts']['full'][4]
        if tot > 0:
            frac[(code, day)] = {c: s['parts'][c][4] / tot if c in s['parts'] else 0.0 for c in cuts}
        if day in D['test']:
            bars[day][code] = s['parts']
    return bars, frac


# ----- the provisional panel -----
def provisional_row(P, d, bars, cut, scale=1.0, cause=None):
    """D's row (field -> array over codes): every name with minute bars gets its bar at `cut` (open = the day's
    open, high / low include it, unadjusted prices on the day's adjustment, volume and turnover / scale); `cause`
    puts the true close, high / low or volume / turnover back.  Names without minute bars keep the true bar."""
    row = {k: P[k][d].astype(float).copy() for k in ('open', 'high', 'low', 'close', 'volume', 'turnover')}
    covered = 0
    for j, c in enumerate(str(c) for c in P['codes']):
        parts = bars.get(c)
        if parts is None or not np.isfinite(P['close'][d, j]) or cut not in parts or not parts['full'][4] > 0:
            continue
        _, h, l, cl, v, t = parts[cut]
        k = float(P['close'][d, j] / P['raw_close'][d, j])
        op = float(P['open'][d, j])
        hi, lo, close, vol, to = h * k, l * k, cl * k, v / k / scale, t / scale
        if cause == 'close':
            close = float(P['close'][d, j])
        elif cause == 'range':
            hi, lo = float(P['high'][d, j]), float(P['low'][d, j])
        elif cause == 'volume':
            vol, to = float(P['volume'][d, j]), float(P['turnover'][d, j])
        row['open'][j], row['close'][j] = op, close
        row['high'][j], row['low'][j] = max(hi, op, close), min(lo, op, close)
        row['volume'][j], row['turnover'][j] = vol, to
        covered += 1
    return row, covered


def cut_at(P, d, row=None):
    q = {k: (v[:d + 1] if isinstance(v, np.ndarray) and v.ndim and k != 'codes' else v) for k, v in P.items()}
    for k, v in (row or {}).items():
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


def run(market):
    """Every test day: the true bar; V0 at every cut; V1 at the main cut; the three causes (V0, main cut)."""
    import warnings
    warnings.simplefilter('ignore', RuntimeWarning)
    np.seterr(invalid='ignore', divide='ignore')
    D = days(market)
    P = panel(market)
    pdays = [str(d) for d in P['days']]
    bars, frac = minute_for(market, D)
    fm = {c: float(np.median([f[c] for (_, day), f in frac.items() if day in D['earlier']])) for c in CUTS[market]}
    log(market, 'f_m', fm, 'from', len(D['earlier']), 'days')
    main = MAIN[market]
    plan = [(c, 'V0', 1.0, None) for c in CUTS[market]] + [(main, 'V1', fm[main], None)] + \
           [(main, f'V0:{x}', 1.0, x) for x in CAUSES]
    path = WORK / f'{market}.jsonl'
    done = {(r['day'], r['cut'], r['scheme']) for r in map(json.loads, path.open(encoding='utf-8'))} \
        if path.exists() else set()
    t_rest = time.time()
    with path.open('a', encoding='utf-8') as out:
        for day in D['test']:
            d = pdays.index(day)
            for cut, scheme, scale, cause in [('true', 'true', None, None)] + plan:
                if (day, cut, scheme) in done:
                    continue
                t0 = time.time()
                if cut == 'true':
                    rec = dict(day=day, cut=cut, scheme=scheme, systems=decide(cut_at(P, d), market, day))
                else:
                    row, covered = provisional_row(P, d, bars.get(day, {}), cut, scale, cause)
                    rec = dict(day=day, cut=cut, scheme=scheme, covered=covered, fm=fm[cut],
                               systems=decide(cut_at(P, d, row), market, day))
                out.write(json.dumps(rec) + '\n')
                out.flush()
                log(market, day, cut, scheme, f'{time.time() - t0:.0f}s')
                if time.time() - t_rest > WORK_SECONDS:
                    log(f'rest {REST_SECONDS // 60} min')
                    time.sleep(REST_SECONDS)
                    t_rest = time.time()


EARLY = {'us': ('10:30', '12:30'), 'hk': ('10:30', '13:30')}   # 1 h / 3 h of trading after the open (HK: lunch)


def run_early(market):
    """V0 at EARLY's cuts on the same test days (the true decisions are the ones `lite` stored): what an earlier run
    of the board would have shown."""
    import warnings
    warnings.simplefilter('ignore', RuntimeWarning)
    np.seterr(invalid='ignore', divide='ignore')
    D = days(market)
    P = panel(market)
    pdays = [str(d) for d in P['days']]
    bars, _ = minute_for(market, D, EARLY[market])
    path = WORK / f'{market}.jsonl'
    done = {(r['day'], r['cut'], r['scheme']) for r in map(json.loads, path.open(encoding='utf-8'))}
    with path.open('a', encoding='utf-8') as out:
        for day in D['test']:
            if (day, 'true', 'true') not in done:
                raise SystemExit(f'{market} {day}: run `lite {market}` first (the true decisions)')
            d = pdays.index(day)
            for cut in EARLY[market]:
                for scheme, cause in (('V0', None), ('V0:volume', 'volume')):   # V0:volume: the ceiling of any
                    if (day, cut, scheme) in done:                           # full-day volume estimate
                        continue
                    t0 = time.time()
                    row, covered = provisional_row(P, d, bars.get(day, {}), cut, cause=cause)
                    out.write(json.dumps(dict(day=day, cut=cut, scheme=scheme, covered=covered,
                                              systems=decide(cut_at(P, d, row), market, day))) + '\n')
                    out.flush()
                    log(market, day, cut, scheme, f'{time.time() - t0:.0f}s')


# ----- the reconciliation -----
def reconcile(market):
    """Full-session minute aggregates of the fetch against our unadjusted daily bars."""
    P = panel(market)
    pdays = {str(d): i for i, d in enumerate(P['days'])}
    col = {str(c): j for j, c in enumerate(P['codes'])}
    rp = MN.latest(market)
    diffs = defaultdict(list)
    n = 0
    for (code, day), s in MN.aggregate(MN.stream(rp, codes=set(col)), CUTS[market][-1:]).items():
        if day not in pdays or not MN.complete(s, market):
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


def keys(sysres, what):
    if what == 'sig':
        return {tuple(x) for x in sysres['sig']}
    if what == 'buys':
        return {(x[0], x[1], x[2]) for x in sysres['buys']}
    return {(x[0], x[1]) for x in sysres['sells']}


def compare(true, prov):
    """Per system and what: [same, false, missed], plus price / stop gaps of shared buys and per-setup counts."""
    out = {}
    for sid, t in true['systems'].items():
        p = prov['systems'][sid]
        o = {}
        for what in ('sig', 'buys', 'sells'):
            a, b = keys(p, what), keys(t, what)
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
    """({'cut|scheme': {'all': totals over the test days}}, per day comparisons)."""
    rows = load(market)
    res = {}
    for day, r in sorted(rows.items()):
        true = r.get(('true', 'true'))
        if not true:
            continue
        for (cut, scheme), prov in r.items():
            if cut != 'true':
                res.setdefault(f'{cut}|{scheme}', {})[day] = compare(true, prov)
    agg = {}
    for key, per_day in res.items():
        tot = defaultdict(lambda: np.zeros(3, int))
        setup = defaultdict(lambda: np.zeros(3, int))
        gaps = []
        for v in per_day.values():
            for sid, o in v.items():
                for what in ('sig', 'buys', 'sells'):
                    tot[(sid, what)] += o[what]
                    tot[('all', what)] += o[what]
                for s, c in o['setup'].items():
                    setup[(sid, s)] += c
                gaps += o['gaps']
        g = np.array([x['gap'] for x in gaps]) if gaps else np.zeros(0)
        w = np.array([x['width'] for x in gaps if 'width' in x]) if gaps else np.zeros(0)
        agg[key] = dict(days=sorted(per_day), all=dict(
            counts={f'{s}|{w_}': v.tolist() for (s, w_), v in tot.items()},
            setup={f'{s}|{k}': v.tolist() for (s, k), v in setup.items()},
            gap=dict(n=len(g), abs_median=float(np.median(np.abs(g))) if len(g) else None,
                     abs_p90=float(np.quantile(np.abs(g), .9)) if len(g) else None,
                     median=float(np.median(g)) if len(g) else None),
            width=dict(n=len(w), abs_median=float(np.median(np.abs(w))) if len(w) else None,
                       median=float(np.median(w)) if len(w) else None),
            days=len(per_day)))
    return agg, res


def attribution(market):
    """Main cut, V0: each mismatch (false or missed) by the replaced field that removes it ('several' when more
    than one does, 'joint' when none alone does)."""
    cut = MAIN[market]
    out = defaultdict(lambda: defaultdict(int))
    for day, r in load(market).items():
        true, base = r.get(('true', 'true')), r.get((cut, 'V0'))
        subs = {x: r.get((cut, f'V0:{x}')) for x in CAUSES}
        if not true or not base or not all(subs.values()):
            continue
        for sid, t in true['systems'].items():
            for what in ('sig', 'buys', 'sells'):
                a, b = keys(base['systems'][sid], what), keys(t, what)
                for x, side in [(x, 'false') for x in a - b] + [(x, 'missed') for x in b - a]:
                    fixed = [s for s, rr in subs.items() if (x in keys(rr['systems'][sid], what)) == (x in b)]
                    why = fixed[0] if len(fixed) == 1 else ('several' if fixed else 'joint')
                    out[f'{what}|{side}'][why] += 1
                    out[f'{what}|{side}|{sid}'][why] += 1
    return {k: dict(v) for k, v in out.items()}


def summary():
    out = {}
    for m in ('us', 'hk', 'cn'):
        if (WORK / f'{m}.jsonl').exists():
            out[m] = dict(days=days(m), agg=summarize(m)[0], attribution=attribution(m))
    REPORTS.mkdir(exist_ok=True)
    (REPORTS / 'intraday_summary.json').write_text(json.dumps(out, indent=1, default=float), encoding='utf-8')
    return out


if __name__ == '__main__':
    cmd = sys.argv[1] if len(sys.argv) > 1 else ''
    if cmd == 'days':
        print(json.dumps(make_days(sys.argv[2]), indent=1))
    elif cmd == 'reconcile':
        reconcile(sys.argv[2])
    elif cmd == 'lite':
        run(sys.argv[2])
    elif cmd == 'early':
        run_early(sys.argv[2])
    elif cmd == 'summary':
        summary()
    else:
        raise SystemExit(__doc__)
