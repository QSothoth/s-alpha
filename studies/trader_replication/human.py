"""Human-sized trading (2026-10-20, the user's goal; reports/HUMAN_SIZING_CN.md): the registered systems under hard
limits a person can trade, with up to three sizing tiers so that a few large, good trades can carry the account
instead of dozens of names at once.

A configuration's `human` dict switches it on (shorts.LongShort applies it after the study's build and the short
side; without it every registered system is unchanged):

    hard limits   the researcher's values of the goal, whole numbers, never tuned (LIMITS): long + short value at most
                  100% of equity and the gross room of every entry and add includes its cost (no margin is drawn),
                  at most 10 positions open, 3 new positions a session and 250 a calendar year (both sides, every
                  kind), at most 50% of equity in one name, no new position in a name sold or stopped that session
    tiers         [{"when": [condition, ...], "risk": multiplier, "cap": max_position}, ...]: the first tier whose
                  conditions all hold sizes the entry (its risk times the multiplier, at most cap of equity, adds
                  inside the same cap); entries no tier takes keep the base tier (`base`: {"risk", "cap"}, default
                  1 and the study's own cap).  At most three tiers counting the base.  Conditions are known at the
                  entry's close (CONDITIONS, or the study's own tier_mask(A, cfg, name))
    engine_cap    a study that keeps the day's first max_new entries inside its build (daily_cap 'build', Martin
                  R74) is built uncapped and the engine counts max_new successful new longs instead (names already
                  held no longer use up the day's places)

Commands (one process, nice; rounds are data: studies/<id>/notes/rounds/H<n>.json with PREREG_H<n>.md):

    PY="nice -n 19 env OPENBLAS_NUM_THREADS=1 PYTHONUTF8=1 /opt/futu-opend/venv/bin/python"
    $PY -m studies.trader_replication.human h0 [system ...]       # registered version vs the same under the limits
    $PY -m studies.trader_replication.human round <system> H1     # a pre-registered round against H0
"""
from __future__ import annotations

from dataclasses import replace
import gc
import json
import sys
from pathlib import Path

import numpy as np

from . import study as ST, system as Y

OUT = Path(__file__).resolve().parent / 'reports'
LIMITS = dict(gross=1.0, max_open=10, max_new=3, max_year=250, max_position=.50, tiers=3)
SELECT = ('2024-01-02', '2025-12-31')
VALIDATE = ('2026-01-02', '2026-10-16')          # used by V1 / V2: reported only, never judged
DD_WORSE = .02                                   # a drawdown more than this above H0's is clearly worse
GAP_TOL = .02                                    # behaviour gap at most this above H0's
REL_TOL = .10                                    # a measure he did not publish: within 10% (log) of H0's
WIN_TOL = .02                                    # ... and a win rate within 2 points
lag = ST.lag


# ----- the transform -----

def condition(st, A, cfg, name):
    """(d, entry) -> bool for one tier condition, from what is known at the entry's close."""
    base = getattr(st, 'base', st)
    if hasattr(base, 'tier_mask'):
        m = base.tier_mask(A, cfg, name)
        if m is not None:
            return lambda d, e: bool(m[d, e[1]])
    if name.startswith('kind='):
        kinds = set(name[5:].split('|'))
        return lambda d, e: e[5] in kinds
    if name == 'ep':
        epm = base.ep_mask(A, cfg) if hasattr(base, 'ep_mask') else None
        if epm is None:
            return lambda d, e: e[5] == 'ep'
        return lambda d, e: e[5] == 'ep' or bool(epm[d, e[1]])
    if name.startswith('rvol>='):                 # the day's turnover over the 20-day average as of the day before
        k = float(name[6:])
        with np.errstate(invalid='ignore', divide='ignore'):
            rv = A['turnover'] / lag(A['to20'])
        return lambda d, e: bool(rv[d, e[1]] >= k)
    if name.startswith('gap>='):                  # the day's open over the close before
        k = float(name[5:])
        with np.errstate(invalid='ignore', divide='ignore'):
            g = A['open'] / lag(A['close']) - 1
        return lambda d, e: bool(g[d, e[1]] >= k)
    if name.startswith('stop<='):                 # the entry's own stop distance
        k = float(name[6:])
        return lambda d, e: abs(e[3] - e[4]) / e[3] <= k + 1e-12
    if name == 'long':
        return lambda d, e: e[2] > 0
    F = A.get('F')
    if name.startswith('near52<='):               # the fill within this fraction of the 52-week high before the day
        k = float(name[8:])
        hi = lag(F.hi(252))
        return lambda d, e: bool(e[3] >= (1 - k) * hi[d, e[1]])
    if name.startswith('tight<='):                # the 10 sessions before the day ranged at most this many percent
        k = float(name[7:])
        rg = lag(F.range(10))
        return lambda d, e: bool(rg[d, e[1]] <= k)
    if name.startswith('strength>='):             # the board's strength percentile (best of 1 / 3 / 6 months), t-1
        from studies.trader_screens import screens as S
        k = float(name[10:])
        s = lag(S.strength(F))
        return lambda d, e: bool(s[d, e[1]] >= k)
    raise KeyError(name)


def tiers(st, A, cfg, entries, spec, base):
    """Entries with the tier's risk multiplier (field 9) and cap (field 8, the lower of it and the entry's own);
    a list of (tier index, d, entry) for the report."""
    if len(spec) + 1 > LIMITS['tiers']:
        raise ValueError(f"at most {LIMITS['tiers']} tiers counting the base")
    conds = [[condition(st, A, cfg, c) for c in t.get('when', [])] for t in spec]
    out = []
    for d, lst in enumerate(entries):
        row = []
        for e in lst:
            k = next((i for i, cs in enumerate(conds) if all(f(d, e) for f in cs)), None)
            t = spec[k] if k is not None else base
            mult = float(t.get('risk', 1.0))
            cap = t.get('cap')
            e = tuple(e) + (None,) * (9 - len(e)) if len(e) < 9 else tuple(e[:9])
            own = e[8]
            if cap is not None:
                own = min(cap, own) if own is not None else cap
            if own is not None:
                own = min(own, LIMITS['max_position'])
            row.append(e[:8] + (own, mult if (mult != 1.0 or k is not None) else None))
        out.append(row)
    return out


PARTS = ('gross', 'max_open', 'max_new', 'max_year', 'max_position', 'no_rebuy')


def limit_rules(rules, only=None):
    """The hard limits on top of the study's own rules (its own tighter values stay); `only` (decompose): just
    these PARTS, to see what each one costs."""
    if only is not None:
        full = limit_rules(rules)
        keep = {'gross': ('max_gross', 'gross_cost', 'gross_close'), 'max_open': ('max_open',),
                'max_new': ('max_new_all',), 'max_year': ('max_new_year',),
                'max_position': ('max_position', 'management_by_kind', 'cap_adds_entry'), 'no_rebuy': ('no_rebuy_day',)}
        return replace(rules, **{f: getattr(full, f) for p in only for f in keep[p]})
    cap = LIMITS['max_position']
    mbk = {k: dict(v, max_position=min(v['max_position'], cap)) if 'max_position' in v else v
           for k, v in rules.management_by_kind.items()}
    return replace(rules, max_gross=min(rules.max_gross, LIMITS['gross']),
                   max_open=min(rules.max_open, LIMITS['max_open']) if rules.max_open else LIMITS['max_open'],
                   max_new_all=LIMITS['max_new'], max_new_year=LIMITS['max_year'], no_rebuy_day=True,
                   gross_cost=True, gross_close=True, cap_adds_entry=True, max_position=min(rules.max_position, cap),
                   management_by_kind=mbk)


def apply(st, A, cfg, h, entries, rules):
    """(entries, rules) under the hard limits and the tiers of h."""
    if h.get('only') is not None:                # decompose: one part of the limits alone, not a candidate
        return entries, limit_rules(rules, h['only'])
    rules = limit_rules(rules)
    if h.get('rule_opts'):                       # sizing rules of his inside the limits (feedback, risk_high, ...)
        ro = {k: tuple(v) if isinstance(v, list) else v for k, v in h['rule_opts'].items()}
        rules = limit_rules(replace(rules, **ro))
    if h.get('tiers') or h.get('base'):
        entries = tiers(st, A, cfg, entries, h.get('tiers', []), h.get('base', {}))
    return entries, rules


# ----- the hard limits as measured -----

def humanized(tr, track, dates):
    """What a person would see in the account: positions open (max, mean), gross exposure at the closes (max),
    new positions a session (max), a calendar year (max), margin interest paid, same-day rebuys, the largest first
    fill as a share of equity, and whether every hard limit holds."""
    years = {}
    for t in tr:
        years[t['entry'][:4]] = years.get(t['entry'][:4], 0) + 1
    # a new position on a session another position of the same name was sold or stopped (one position a name)
    from collections import Counter
    exits = Counter((u['code'], u['exit']) for u in tr if u['why'] != 'end')
    rebuy = sum(exits[(t['code'], t['entry'])] - (t['why'] != 'end' and t['exit'] == t['entry']) > 0 for t in tr)
    out = dict(max_open=int(max(track['open'])) if track['open'] else 0,
               mean_open=float(np.mean(track['open'])) if track['open'] else 0.0,
               max_gross=float(max(track['gross'])) if track['gross'] else 0.0,
               max_new_day=int(max(track['new'])) if track['new'] else 0,
               per_year={y: n for y, n in sorted(years.items())},
               max_year=max(years.values()) if years else 0, margin=float(track['margin']), rebuy=rebuy)
    out['ok'] = bool(out['max_open'] <= LIMITS['max_open'] and out['max_gross'] <= LIMITS['gross'] + 1e-9
                     and out['max_new_day'] <= LIMITS['max_new'] and out['max_year'] <= LIMITS['max_year']
                     and out['margin'] <= 1e-12 and rebuy == 0)
    return out


def run(st, A, cfg, seg, placebo=0, seed=1):
    """One account on a segment: stats, behaviour, the hard limits, tier counts, top trades; placebo draws."""
    entries, rules, mask, pool = st.build(A, cfg)
    px, ema = st.px(A), st.ema_inputs(A, pool, rules)
    track = {}
    curve, dates, tr = Y.simulate(px, ema, rules, entries, *seg, audit=True, track=track)
    s = Y.stats(curve, dates, tr)
    cl = [t for t in tr if t['why'] != 'end']
    b = ST.behaviour(curve, dates, cl)
    pnl = np.sort([t['pnl'] for t in tr])[::-1]
    gross = pnl[pnl > 0].sum()
    k = max(1, len(pnl) // 10)
    di = {str(d): i for i, d in enumerate(dates)}
    top = []
    for t in sorted(tr, key=lambda t: -t['pnl'])[:5]:
        i = di.get(t['entry'])
        ex = t.get('executions') or []
        w = ex[0]['shares'] * ex[0]['price'] / (curve[i - 1] if i else 1.0) if ex and i is not None else None
        top.append(dict(code=t['code'], kind=t['kind'], entry=t['entry'], exit=t['exit'], fill=t['fill'],
                        stop=t['stop'], tier=t.get('tier'), weight=w,
                        gross_at_entry=track['gross'][i] if i is not None else None, pnl=t['pnl'], ret=t['ret'],
                        days=t['days'], adds=sum(x['action'] == 'add' for x in ex), why=t['why']))
    tiers_ = {}
    for t in tr:
        key = 'base' if t.get('tier') is None else f"x{t['tier']:g}"
        n, w, p = tiers_.get(key, (0, 0, 0.0))
        tiers_[key] = (n + 1, w + (t['ret'] > 0), p + t['pnl'])
    out = dict(total=s['total'], by_year=s['by_year'], maxdd=s['maxdd'], trades=len(cl), open_at_end=len(tr) - len(cl),
               win=b['win'], avg_win=b['avg_win'], avg_loss=b['avg_loss'], days_win=b['days_win'],
               median_days_win=b['median_days_win'], per_year=b['per_year'],
               pnl_top10=float(pnl[:k][pnl[:k] > 0].sum() / gross) if gross > 0 else None,
               human=humanized(tr, track, dates), tiers={k: dict(n=v[0], wins=v[1], pnl=v[2]) for k, v in tiers_.items()},
               top=top)
    if placebo:
        out['placebo'] = Y.placebo_rank(px, ema, rules, entries, *seg, pool, draws=placebo, seed=seed)
    out['_tr'] = tr
    del entries, mask, pool
    return out


# ----- his yardstick -----

def targets(st):
    """His published behaviour: win (or wins / (wins + losses)), avg win / loss, days held by winners; mean of his
    years, his_behaviour on top."""
    out = {}
    for k in ('win', 'avg_win', 'avg_loss', 'days_win'):
        v = []
        for y in (st.his or {}).values():
            x = y.get(k)
            if x is None and k == 'win' and y.get('wins') is not None and y.get('losses') is not None:
                x = y['wins'] / (y['wins'] + y['losses'])
            if x is not None:
                v.append(x)
        if v:
            out[k] = float(np.mean(v))
    out.update({k: v for k, v in (st.his_behaviour or {}).items() if k in ('win', 'avg_win', 'avg_loss', 'days_win')})
    return out


def year_gaps(st, by_year):
    """|log((1 + ours) / (1 + his))| for each of his published years inside the selection segment."""
    return {y: abs(float(np.log((1 + by_year[y]) / (1 + h['ret'])))) for y, h in (st.his or {}).items()
            if y in by_year and h.get('ret') is not None and SELECT[0][:4] <= y <= SELECT[1][:4]}


def behaviour_check(st, cand, h0):
    """Not worse than H0: his dated longs bought at least as many; win rate, avg win / loss, winners' days held no
    farther from his (mean log distance, a win rate as log odds) than H0's + GAP_TOL; measures he did not publish
    within REL_TOL (log) of H0's, the win rate within WIN_TOL."""
    tg = targets(st)
    why = []
    if cand['bought'][0] < h0['bought'][0]:
        why.append(f"bought {cand['bought'][0]} < {h0['bought'][0]}")

    def dist(r, k):
        a, b = r.get(k), tg[k]
        if a is None:
            return None
        if k == 'win':
            return abs(np.log(a / (1 - a)) - np.log(b / (1 - b))) if 0 < a < 1 else None
        return abs(np.log(abs(a) / abs(b))) if a * b > 0 else None
    known = [k for k in ('win', 'avg_win', 'avg_loss', 'days_win') if k in tg]
    if known:
        dc = [dist(cand, k) for k in known]
        d0 = [dist(h0, k) for k in known]
        if None in dc:
            why.append('behaviour measure missing')
        elif None not in d0 and np.mean(dc) > np.mean(d0) + GAP_TOL:
            why.append(f'behaviour gap {np.mean(dc):.3f} > {np.mean(d0):.3f} + {GAP_TOL}')
    for k in ('win', 'avg_win', 'avg_loss', 'days_win'):
        if k in tg:
            continue
        a, b = cand.get(k), h0.get(k)
        if a is None or b is None:
            continue
        if k == 'win' and a < b - WIN_TOL:
            why.append(f'win {a:.3f} < H0 {b:.3f} - {WIN_TOL}')
        elif k != 'win' and a * b > 0 and abs(np.log(a / b)) > REL_TOL:
            why.append(f'{k} {a:.3f} vs H0 {b:.3f}')
    return why


def accept(st, cand, h0, gate_ok=None):
    """The goal's acceptance rule: hard limits held, gate (four checks; lookahead filled in for the carried one),
    above the same-pool placebo median, his years closer than H0 in both (traders with published years) or the
    segment higher with no clearly worse drawdown (the others), behaviour not worse than H0."""
    why = []
    if not cand['human']['ok']:
        why.append('hard limits')
    if not cand['gate']['win']['ok'] or not cand['gate']['fills']['ok'] or not cand['gate']['data']:
        why.append('gate')
    if gate_ok is False:
        why.append('lookahead')
    if not cand['total'] > cand['placebo']['median']:
        why.append('placebo')
    gc_, g0 = year_gaps(st, cand['by_year']), year_gaps(st, h0['by_year'])
    if g0:
        bad = [y for y in g0 if not gc_[y] < g0[y] - 1e-12]
        if bad:
            why.append('his years not closer: ' + ','.join(bad))
    else:
        if not cand['total'] > h0['total'] + 1e-12:
            why.append('segment not above H0')
        if cand['maxdd'] > h0['maxdd'] + DD_WORSE:
            why.append('drawdown')
    why += behaviour_check(st, cand, h0)
    return why


def objective(st, r):
    """Higher is better: minus the mean of his year gaps (traders with published years), else the segment total."""
    g = year_gaps(st, r['by_year'])
    return -float(np.mean(list(g.values()))) if g else r['total']


# ----- evaluation -----

def evaluate(st, A, cfg, draws, located):
    """Selection segment with placebo, the 2026 segment and the whole window (reported only), the gate's win-rate
    and fill checks on the whole window and the data digest."""
    from . import gate as G, panels
    r = run(st, A, cfg, SELECT, placebo=draws)
    tr = r.pop('_tr')
    r['bought'] = [ST.bought(A, tr, located), len(located)]
    w = run(st, A, cfg, panels.WINDOW)
    wt = w.pop('_tr')
    v = run(st, A, cfg, VALIDATE)
    v.pop('_tr')
    r['window'] = {k: w[k] for k in ('total', 'by_year', 'maxdd', 'trades', 'win', 'human')}
    r['validate'] = {k: v[k] for k in ('total', 'maxdd', 'trades', 'win', 'human')}
    r['gate'] = dict(win=G.check_win(wt), fills=G.check_fills(A, wt),
                     data=A.get('digest') == panels.pinned()['markets'].get(A['market']))
    r['gate']['fills'].pop('bad', None)
    r['year_gap'] = year_gaps(st, r['by_year'])
    del tr, wt
    return r


def h0_cfg(cfg):
    return dict(cfg, human={})


def located_select(st, A):
    return [x for x in st.located(A, st.trades()) if SELECT[0] <= x[0].entry_date <= SELECT[1]]


def line(sid, k, r):
    hm, p = r['human'], r.get('placebo', {})
    print(sid, k, f"total {r['total']:+.3f}", {y: round(v, 3) for y, v in r['by_year'].items()},
          f"dd {r['maxdd']:.3f} rank {p.get('rank', float('nan')):.2f} med {p.get('median', float('nan')):+.3f}",
          f"n {r['trades']} win {r['win'] or 0:.3f} aw {r['avg_win'] or 0:+.3f} al {r['avg_loss'] or 0:+.3f}",
          f"dw {r['days_win'] or 0:.1f} bought {r.get('bought')} top10 {r['pnl_top10'] or 0:.2f}",
          f"open {hm['max_open']}/{hm['mean_open']:.1f} gross {hm['max_gross']:.2f} new {hm['max_new_day']}",
          f"yr {hm['max_year']} margin {hm['margin']:.2e} rebuy {hm['rebuy']} ok {hm['ok']}",
          f"2026 {r['validate']['total']:+.3f}" if 'validate' in r else '', flush=True)


def h0(ids=()):
    """Every registered system: the registered version and H0 (the same under the hard limits) on the selection
    segment, the 2026 segment and the window (reported), US; HK / CN whole window (reported).  reports/human_h0.json."""
    from . import systems as SY
    path = OUT / 'human_h0.json'
    res = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    for x in SY.all_():
        if ids and x.id not in ids:
            continue
        st, cfg = x.load()
        A = st.arrays('us')
        loc = located_select(st, A)
        r = {}
        for k, c in (('registered', cfg), ('H0', h0_cfg(cfg))):
            r[k] = evaluate(st, A, c, 100, loc)
            line(x.id, k, r[k])
        del A
        gc.collect()
        r['markets'] = {}
        for m in ('hk', 'cn'):
            B = st.arrays(m)
            r['markets'][m] = {}
            from . import panels
            for k, c in (('registered', cfg), ('H0', h0_cfg(cfg))):
                w = run(st, B, c, panels.WINDOW)
                w.pop('_tr')
                r['markets'][m][k] = {q: w[q] for q in ('total', 'by_year', 'maxdd', 'trades', 'win', 'human')}
                print(x.id, m, k, f"total {w['total']:+.3f}", {y: round(v, 3) for y, v in w['by_year'].items()},
                      f"open {w['human']['max_open']} gross {w['human']['max_gross']:.2f}", flush=True)
            del B
            gc.collect()
        res[x.id] = dict(version=x.version, **r)
        OUT.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(res, indent=1, default=float, ensure_ascii=False), encoding='utf-8')
    return res


def decompose(ids=()):
    """Each part of the hard limits alone on the registered version (selection segment, US, no placebo): what the
    registered returns owe to margin (gross), the number of names open, the daily and the yearly count.
    reports/human_decompose.json."""
    from . import systems as SY
    path = OUT / 'human_decompose.json'
    res = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    for x in SY.all_():
        if ids and x.id not in ids:
            continue
        st, cfg = x.load()
        A = st.arrays('us')
        r = {}
        for p in PARTS:
            v = run(st, A, dict(cfg, human={'only': [p]}), SELECT)
            v.pop('_tr')
            r[p] = {k: v[k] for k in ('total', 'by_year', 'maxdd', 'trades', 'human')}
            print(x.id, p, f"total {v['total']:+.3f}", {y: round(q, 3) for y, q in v['by_year'].items()},
                  f"n {v['trades']} open {v['human']['max_open']} gross {v['human']['max_gross']:.2f}", flush=True)
        res[x.id] = r
        del A
        gc.collect()
        path.write_text(json.dumps(res, indent=1, default=float, ensure_ascii=False), encoding='utf-8')
    return res


def round_(sid, name):
    """studies/<sid>/notes/rounds/<name>.json: {"base": "H0" | [report, key], "candidates": {key: changes},
    "draws": 50}.  Every candidate against H0 by accept(); the passing one with the best objective, if it also
    beats the base it was built on, is carried (its placebo redrawn 100 times and its lookahead checked first).
    studies/<sid>/reports/<name lower>.json; failures go to the negation register."""
    from . import gate as G, negations as N, systems as SY
    x = SY.get(sid)
    st, reg = x.load()
    spec = json.loads((st.rounds / f'{name}.json').read_text(encoding='utf-8'))
    h0r = json.loads((OUT / 'human_h0.json').read_text(encoding='utf-8'))[sid]['H0']
    if spec['base'] == 'H0':
        base, base_r = h0_cfg(reg), h0r
    else:
        rep, key = spec['base']
        prev = json.loads((st.reports / rep).read_text(encoding='utf-8'))
        base, base_r = prev['configs'][key], prev['results'][key]
    cfgs = {k: ST.merged(base, v) for k, v in spec['candidates'].items()}
    A = st.arrays('us')
    loc = located_select(st, A)
    res, why = {}, {}
    for k, c in cfgs.items():
        res[k] = evaluate(st, A, c, spec.get('draws', 50), loc)
        why[k] = accept(st, res[k], h0r)
        line(sid, k, res[k])
        print('   accept' if not why[k] else '   fail', why[k], flush=True)
    ok = sorted([k for k in cfgs if not why[k] and objective(st, res[k]) > objective(st, base_r) + 1e-12],
                key=lambda k: -objective(st, res[k]))
    chosen = None
    for k in ok:                                         # the carried one: 100 draws and the lookahead check
        r = evaluate(st, A, cfgs[k], 100, loc)
        la = G.check_lookahead(st, cfgs[k], 'us', full=A)
        r['lookahead'] = la
        res[k + '@100'] = r
        why[k] = accept(st, r, h0r, gate_ok=la['ok'])
        line(sid, k + '@100', r)
        print('   lookahead', la['ok'], why[k], flush=True)
        if not why[k]:
            chosen = k
            break
    out = dict(name=name, base=spec['base'], configs=dict(cfgs, **({'base': base})), results=dict(res, base=base_r),
               why=why, chosen=chosen, h0=dict(total=h0r['total'], by_year=h0r['by_year']))
    st.out.mkdir(parents=True, exist_ok=True)
    (st.out / f'{name.lower()}.json').write_text(json.dumps(out, indent=1, default=float, ensure_ascii=False),
                                                encoding='utf-8')
    for k in cfgs:
        if k == chosen:
            continue
        reason = 'H gates: ' + ', '.join(why[k]) if why[k] else f'objective not above the base / {chosen}'
        N.add(st.negations, dict(round=name, stage='human sizing', candidate=k, change=spec['candidates'][k],
                                 base=spec['base'], chosen=chosen, reason=reason, objective='human.objective',
                                 evidence=dict(total=res[k]['total'], by_year=res[k]['by_year'],
                                               placebo_median=res[k]['placebo']['median'], win=res[k]['win'],
                                               bought=res[k]['bought'], year_gap=res[k]['year_gap'],
                                               human_ok=res[k]['human']['ok']), base_config=base))
    if st.negations.exists():
        N.render(st.negations, st.name)
    print(name, 'chosen', chosen, flush=True)
    del A
    gc.collect()
    return out


if __name__ == '__main__':
    if sys.argv[1] == 'h0':
        h0(sys.argv[2:])
    elif sys.argv[1] == 'decompose':
        decompose(sys.argv[2:])
    elif sys.argv[1] == 'round':
        round_(sys.argv[2], sys.argv[3])
    else:
        raise SystemExit(__doc__)
