"""Common gaps across the registered trader systems (notes/COMMON_GAPS_CN.md, reports/COMMON_RESULTS_CN.md).

A configuration's `common` dict switches shared mechanisms on for one trader's long side; without it (every
registered system) shorts.LongShort calls the study's own build unchanged.  The mechanisms:

    rank       the day's long entries reordered before the daily cap: 'rvol' by relative turnover (the day's
               turnover / the 20-day average as of the day before, known at the close the entry is bought),
               highest first; 'ep_rvol' his EPs first by relative turnover, then the rest in his own order;
               'ep_own' his EPs first, each group in his own order.  A study whose build keeps the day's first
               max_new entries itself (daily_cap 'build', Martin R74) is built uncapped, reordered, then cut to
               max_new the same way
    stop       a long's stop wider than min(pct, adr x the ADR as of the day before; adr_ep for his EPs) moved up
               to it ('cap') or the entry dropped ('skip'); his own skip / cap of wide stops is taken out
               (Study.own_stop_off)
    add        a held long whose close is above its fill buys `frac` of its original size at the close of a day his
               signal mask fires again (not the entry day), at most `max` times, the stop then at the fill ('fill')
               or kept ('keep'): engine add_signal with add_signal_profit
    floor      (turnover, price): every long pool floor of his higher than these lowered to them (his own
               config keys through Study.own_floor, the board's built-in floors through Feat.floor for this build
               only; the short side keeps its floors)
    small      (turnover, cap): a long on a name under that 20-day turnover (as of the day before) holds at most
               cap of equity (the engine's per-entry max_position)
    ep_slots   his EPs (kind 'ep', or the study's ep_mask) opened up to this many a day on their own count, not
               taking the daily cap of his other setups (engine max_new_by_kind; a build-capped study keeps the
               day's first max_new non-EP entries plus its first ep_slots EPs)

Commands:

funnel     every registered system on US data with its registered configuration: for each of his dated longs up
           to the end of the selection segment, the furthest step reached (pool floor, setup, entry and stop rule,
           market filter, daily cap, engine room) and the R of his ticker on his day with our execution (layer two
           of the three-layer replay), so missed trades of all traders sort into the same stages.
round      notes/common_rounds/<name>.json: each candidate on every registered system over the selection segment
           (2024-01-02 -> 2025-12-31, US), against the registered system; the acceptance rule of the
           pre-registration (notes/COMMON_PREREG_<name>.md); reports/common_<name>.json

    PY="nice -n 19 env OPENBLAS_NUM_THREADS=1 PYTHONUTF8=1 /opt/futu-opend/venv/bin/python"
    $PY -m studies.trader_replication.common funnel [system ...]
    $PY -m studies.trader_replication.common round C1 [system ...]
    $PY -m studies.trader_replication.common validate V1      # once: the validation segment (2026)
"""
from __future__ import annotations

from dataclasses import replace
import gc
import json
import sys
from pathlib import Path

import numpy as np

from . import systems as SY, system as Y, study as ST

OUT = Path(__file__).resolve().parent / 'reports'
DIAG = ('2023-02-01', '2025-12-31')      # his 2023 trades count (Qullamaggie, Marios); 2026 is the validation segment
SELECT = ('2024-01-02', '2025-12-31')
VALIDATE = ('2026-01-02', '2026-10-16')
lag = ST.lag

STAGES = ('not_listed', 'pool', 'setup', 'entry_stop', 'market', 'daily_cap', 'held', 'max_open', 'room', 'traded')
STAGE_CN = {'not_listed': '不在面板', 'pool': '股票池门槛', 'setup': '形态定义', 'entry_stop': '入场与止损',
            'market': '市况', 'daily_cap': '名额与排序（每天）', 'held': '名额与排序（已持有）',
            'max_open': '名额与排序（持仓上限）', 'room': '仓位（总敞口 / 单只）', 'traded': '买到'}


# ----- shared mechanisms -----

def rvol(A):
    """The day's turnover over the 20-day average turnover as of the day before (whole-day figures: known at the
    close, when a close-confirmed entry is bought)."""
    with np.errstate(invalid='ignore', divide='ignore'):
        return A['turnover'] / lag(A['to20'])


def strength(A):
    """The best of the 1 / 3 / 6-month (21 / 63 / 126-session) return percentiles across the panel's names on each
    day (1 = the strongest), NaN before any window; as of that close (callers lag it).  The board's strength for
    studies without its features (Martin), shared by the G rounds."""
    if '_strength' in A:
        return A['_strength']
    c = A['close']
    best = np.full(c.shape, np.nan)
    for k in (21, 63, 126):
        r = np.full(c.shape, np.nan)
        with np.errstate(invalid='ignore', divide='ignore'):
            r[k:] = c[k:] / c[:-k] - 1
        for d in range(k, len(c)):
            ok = np.isfinite(r[d])
            n = int(ok.sum())
            if n < 2:
                continue
            pct = np.empty(n)
            pct[np.argsort(r[d, ok], kind='stable')] = np.arange(n) / (n - 1)
            row = best[d, ok]
            best[d, ok] = np.fmax(row, pct)
    A['_strength'] = best
    return best


def rerank(A, entries, how, ep=None):
    """Long entries with a new first field (lower goes first); `ep(d, e)` tells his EPs apart.  'strength' /
    'ep_strength': by the strength percentile as of the day before (his EPs first in the second)."""
    rv = rvol(A)
    st = lag(strength(A)) if how in ('strength', 'ep_strength') else None

    def key(d, e):
        v = rv[d, e[1]]
        neg = -float(v) if np.isfinite(v) else np.inf
        own = e[0]
        if how == 'rvol':
            return neg
        if st is not None:
            s = st[d, e[1]]
            s = -float(s) if np.isfinite(s) else np.inf
            if how == 'strength':
                return s
            return (0 if ep(d, e) else 1, s)
        first = 0 if ep(d, e) else 1
        if how == 'ep_rvol':
            return (first, neg if first == 0 else own)
        if how == 'ep_own':
            return (first, own)
        raise ValueError(how)
    return [[(key(d, e),) + tuple(e[1:]) if e[2] > 0 else e for e in lst] for d, lst in enumerate(entries)]


def stop_width(A, entries, spec, ep):
    """Long entries whose stop is wider than the cap: moved up to it ('cap', the stop at fill x (1 - cap)) or
    dropped ('skip').  cap = the smallest of pct and adr (adr_ep for his EPs) x the ADR as of the day before."""
    adr = lag(A['adr'])
    out = []
    for d, lst in enumerate(entries):
        row = []
        for e in lst:
            if e[2] > 0:
                k = spec.get('adr_ep', spec.get('adr')) if ep(d, e) else spec.get('adr')
                caps = [spec['pct']] if spec.get('pct') else []
                if k and np.isfinite(adr[d, e[1]]):
                    caps.append(k * adr[d, e[1]] / 100)
                if caps and (e[3] - e[4]) / e[3] > min(caps) + 1e-12:
                    if spec.get('mode', 'cap') == 'skip':
                        continue
                    e = e[:4] + (float(e[3] * (1 - min(caps))),) + tuple(e[5:])
            row.append(e)
        out.append(row)
    return out


def build_long(base, A, cfg, trace=None):
    """The study's long build with cfg['common'] applied (see the module docstring)."""
    cm = cfg['common']
    cfg = {k: v for k, v in cfg.items() if k != 'common'}
    precap = getattr(base, 'daily_cap', 'engine') == 'build' and cfg.get('max_new')
    if cm.get('stop'):                             # the stop rule replaces his own skip / cap of wide stops
        cfg = base.own_stop_off(cfg, cm['stop'].get('mode', 'cap'))
    fl = cm.get('floor')                           # (turnover, price) pool floors, lowered where higher
    F = A.get('F')
    if fl:
        cfg = base.own_floor(cfg, *fl)
        if F is not None:
            F.floor = tuple(fl)
    try:
        entries, rules, mask, pool = base.build(A, dict(cfg, max_new=0) if precap else cfg, trace)
    finally:
        if F is not None:
            F.floor = None
    if cm.get('small'):                            # (turnover, cap): a name under this 20-day turnover (t-1)
        lim, capp = cm['small']                    # holds at most cap of equity
        to20 = lag(A['to20'])
        entries = [[e[:6] + (e[6] if len(e) > 6 else None, e[7] if len(e) > 7 else None,
                             min(capp, e[8]) if len(e) > 8 and e[8] is not None else capp)
                    if e[2] > 0 and to20[d, e[1]] < lim else e for e in lst] for d, lst in enumerate(entries)]
    epm = base.ep_mask(A, cfg) if hasattr(base, 'ep_mask') else None
    ep = (lambda d, e: e[5] == 'ep') if epm is None else (lambda d, e: bool(epm[d, e[1]]))
    if cm.get('stop'):
        entries = stop_width(A, entries, cm['stop'], ep)
        if trace is not None:
            trace['raw'] = entries
            trace['filtered'] = entries
    if cm.get('rank'):
        entries = rerank(A, entries, cm['rank'], ep)
        if trace is not None:
            trace['filtered'] = entries
    if cm.get('add'):                              # a held winner buys more at the close of a new buy point
        a = cm['add']
        A['common_sig'] = mask
        rules = replace(rules, add_signal='common_sig', add_signal_frac=a.get('frac', .5),
                        add_signal_max=a.get('max', 1), add_signal_stop=a.get('stop', 'fill'),
                        add_signal_profit=a.get('profit', True))
    slots = cm.get('ep_slots')                     # his EPs get their own daily count, outside max_new
    if slots and precap:
        entries = [sorted([e for e in lst if not (e[2] > 0 and ep(d, e))], key=lambda e: e[0])[:cfg['max_new']]
                   + sorted([e for e in lst if e[2] > 0 and ep(d, e)], key=lambda e: e[0])[:slots]
                   for d, lst in enumerate(entries)]
    elif slots:
        entries = [[e[:5] + ('ep',) + tuple(e[6:]) if e[2] > 0 and ep(d, e) else e for e in lst]
                   for d, lst in enumerate(entries)]
        rules = replace(rules, max_new_by_kind={**rules.max_new_by_kind, 'ep': slots})
    elif precap:
        entries = [sorted(lst, key=lambda e: e[0])[:cfg['max_new']] for lst in entries]
    if trace is not None and (precap or cm.get('rank') or slots):
        trace['capped'] = entries
    return entries, rules, mask, pool


def floors(sid, st, A, cfg):
    """{'brk': [(label, mask)], 'ep': [...]}: each system's own pool floors for its non-EP and EP setups, as of the
    day before (what the day's signal could see).  The setup's own shape conditions are not floors."""
    F = A['F'] if 'F' in A else None
    raw, to20, adr = A['raw'], A['to20'], A['adr']
    with np.errstate(invalid='ignore'):
        def f(price=0.0, turnover=0.0, a=0.0, above50=False):
            out = [('price', lag(raw >= price)), ('turnover', lag(to20 >= turnover))]
            if a:
                out.append(('adr', lag(adr >= a)))
            if above50:
                out.append(('above50', lag(F.c > F.sma(50))))
            return out
        if sid == 'martin_luk':
            R = st.base.R
            pool, w, _ = R.system_signals(A, cfg)
            spec = R.POOLS[cfg.get('pool') or R.chosen('r20_pool.json', 'U0')]
            base = f(*spec)
            return {'brk': base + [('strength_list', w)], 'ep': base}
        p = cfg.get('pool', {})
        price = p.get('price', 5.0)
        if sid == 'christian_flanders':
            e = cfg.get('ep_pool', p)
            return {'brk': f(price, p.get('turnover', 20e6), p.get('adr', 3.0), p.get('above50', True)),
                    'ep': f(e.get('price', 5.0), e.get('turnover', 20e6))}
        if sid == 'clement_ang':
            return {'brk': f(price, p.get('turnover', 50e6), p.get('adr', 3.0), p.get('above50', True)),
                    'ep': f(price, p.get('turnover', 50e6))}
        if sid == 'qullamaggie':
            return {'brk': f(5.0, 20e6, p.get('adr', 4.0)) + [('strength_top2', lag(ST_strength(F) >= .98))],
                    'ep': f(5.0, cfg.get('ep', {}).get('liquid', 20e6))}
        if sid == 'oliver_kell':
            rs = cfg.get('strength', '')
            out = f(price, p.get('turnover', 20e6), p.get('adr', 3.0))
            if rs.startswith('rs'):
                out.append(('rs', lag(st.base.rs(A)) >= int(rs[2:]) / 100))
            return {'brk': out, 'ep': out}
        if sid == 'mark_minervini':
            return {'brk': f(5.0, p.get('turnover', 20e6)), 'ep': f(5.0, p.get('turnover', 20e6))}
        if sid == 'marios_stamatoudis':
            b, e = cfg.get('brk', {}), cfg.get('ep', {})
            return {'brk': f(b.get('price', 5.0), b.get('turnover', 20e6), b.get('adr', 4.0))
                    + [('strength_top2', lag(ST_strength(F) >= 1 - b.get('top', .02)))],
                    'ep': f(e.get('price', 5.0), e.get('liquid', 20e6))}
    raise KeyError(sid)


def ST_strength(F):
    from studies.trader_screens import screens as S
    return S.strength(F)


def is_ep(t):
    s = (t.setup + ' ' + t.trigger).lower()
    return any(k in s for k in ('ep', 'episodic', 'gap', 'earnings', 'breakaway'))


def his_entry(st, A, d, j, cfg):
    return st.his_entry(A, d, j, cfg)


def funnel_one(system):
    st, cfg = system.load()
    A = st.arrays('us')
    trace = {}
    entries, rules, mask, pool = st.build(A, cfg, trace)
    px, ema = st.px(A), st.ema_inputs(A, pool, rules)
    curve, dates, tr = Y.simulate(px, ema, rules, entries, *DIAG, audit=True)
    codes = [str(c) for c in A['codes']]
    di = {str(d): i for i, d in enumerate(A['days'])}
    ours = {(t['code'], t['entry']): t for t in tr if t['side'] > 0}
    sets = {k: [{e[1] for e in lst} for lst in trace[k]] for k in ('raw', 'filtered', 'capped')}
    fl = floors(system.id, st, A, cfg)
    located = [x for x in st.located(A, st.trades(), dated=False)
               if x[0].dated and DIAG[0] <= x[0].entry_date <= DIAG[1]]
    # layer two: his ticker on his day, our execution, every trade alone
    mine = [[] for _ in range(len(A['days']))]
    for t, j, a, b in located:
        d = di.get(t.entry_date)
        if d is not None:
            e = his_entry(st, A, d, j, cfg)
            if e is not None:
                mine[d].append(e)
    alone = replace(rules, max_open=0, max_new_long=0, max_gross=1e9, max_position=1e9, feedback=0,
                    risk_scale='', margin_rate=0.0, max_open_by_kind={}, month_loss_cap=0.0)
    _, _, tr2 = Y.simulate(px, ema, alone, mine, *DIAG, audit=False)
    lay2 = {(t['code'], t['entry']): t for t in tr2}
    # engine state per day: open longs (all sides count for max_open) and new longs opened
    n = len(A['days'])
    open_n, new_long = np.zeros(n, int), np.zeros(n, int)
    held = {}
    for t in tr:
        i0, i1 = di[t['entry']], di.get(t['exit'], n - 1)
        open_n[i0 + 1:i1 + 1] += 1                      # open at the start of day d's entries (exits first)
        if t['side'] > 0:
            new_long[i0] += 1
        held.setdefault(t['code'], []).append((i0, i1))
    max_new = rules.max_new_long or cfg.get('max_new', 0)
    rows = []
    known = set(codes)
    for t in [t for t in st.trades() if t.side == 'long' and t.dated and DIAG[0] <= t.entry_date <= DIAG[1]]:
        hit = [x for x in located if x[0].id == t.id]
        if not hit:
            rows.append(dict(id=t.id, ticker=t.ticker, date=t.entry_date, setup=t.setup, ep=is_ep(t),
                             outcome=t.outcome, his_r=t.r_multiple, stage='not_listed', detail=''))
            continue
        _, j, a, b = hit[0]
        code = codes[j]
        best, detail, our = 0, '', None
        kind = 'ep' if is_ep(t) else 'brk'
        fail_counts = {}
        for d in range(a, b + 1):
            fails = [lab for lab, m in fl[kind] if not m[d, j]]
            for x in fails:
                fail_counts[x] = fail_counts.get(x, 0) + 1
            k = 1 if fails else 2                       # 1 pool, 2 setup
            if mask[d, j]:
                k = 3
                if j in sets['raw'][d]:
                    k = 4
                    if j in sets['filtered'][d]:
                        k = 5
                        if j in sets['capped'][d]:
                            k = 6
                            if (code, str(A['days'][d])) in ours:
                                k = 9
                                our = ours[(code, str(A['days'][d]))]
                            elif any(i0 <= d - 1 and d <= i1 for i0, i1 in held.get(code, [])) or \
                                    any(i0 < d <= i1 for i0, i1 in held.get(code, [])):
                                k = 6.5
                            elif max_new and new_long[d] >= max_new:
                                k = 6
                            elif rules.max_open and open_n[d] >= rules.max_open:
                                k = 7
                            else:
                                k = 8
            if k > best:
                best = k
        stage = {1: 'pool', 2: 'setup', 3: 'entry_stop', 4: 'market', 5: 'daily_cap', 6: 'daily_cap',
                 6.5: 'held', 7: 'max_open', 8: 'room', 9: 'traded'}[best] if best else 'pool'
        if stage == 'pool':
            detail = ','.join(sorted(fail_counts, key=lambda x: -fail_counts[x]))
        d = di.get(t.entry_date)
        x2 = lay2.get((code, t.entry_date))
        c, l = A['close'][d, j], A['low'][d, j]
        rows.append(dict(id=t.id, ticker=t.ticker, date=t.entry_date, setup=t.setup, ep=kind == 'ep',
                         outcome=t.outcome, his_r=t.r_multiple, stage=stage, detail=detail,
                         l2_r=x2 and round(x2['r'], 2), l2_ret=x2 and round(x2['ret'], 3),
                         our_r=our and round(our['r'], 2), our_ret=our and round(our['ret'], 3),
                         prior_to20=float(A['to20'][d - 1, j]), prior_price=float(A['raw'][d - 1, j]),
                         prior_adr=float(A['adr'][d - 1, j]),
                         gap=float(A['open'][d, j] / A['close'][d - 1, j] - 1),
                         rvol=float(A['turnover'][d, j] / A['to20'][d - 1, j]),
                         stop_width=float((c - l) / c) if c > 0 else None))
    out = dict(id=system.id, version=system.version, period=DIAG, rows=rows,
               by_stage={s: dict(n=sum(r['stage'] == s for r in rows),
                                 l2_r=float(sum(r.get('l2_r') or 0 for r in rows if r['stage'] == s)))
                         for s in STAGES})
    del A, entries, mask, pool, trace, tr, tr2
    gc.collect()
    return out


def funnel(ids=()):
    path = OUT / 'common_funnel.json'
    res = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    for x in SY.all_():
        if ids and x.id not in ids:
            continue
        r = funnel_one(x)
        res[x.id] = r
        print('FUNNEL', x.id, {s: (v['n'], round(v['l2_r'], 1)) for s, v in r['by_stage'].items() if v['n']},
              flush=True)
        for row in r['rows']:
            print('  ', {k: (round(v, 3) if isinstance(v, float) else v) for k, v in row.items()}, flush=True)
        path.write_text(json.dumps(res, indent=1, default=float), encoding='utf-8')
    return res


# ----- rounds: every candidate on every registered system, selection segment only -----

ROUNDS = Path(__file__).resolve().parent / 'notes' / 'common_rounds'
DD_WORSE = .02              # a drawdown more than this above the registered system's is "clearly worse"
GAP_WORSE = .02             # behaviour gap at most this above the registered system's (fixed from C1 on)
YEAR_TOL = .01              # an improved system may lose at most this much in either calendar year
MIN_BETTER = 4              # of the 7 systems


def his_select(st, A):
    """His dated longs entered inside the selection segment, on the panel."""
    return [x for x in st.located(A, st.trades()) if SELECT[0] <= x[0].entry_date <= SELECT[1]]


def evaluate(st, A, cfg, located, draws=50, seg=SELECT):
    entries, rules, mask, pool = st.build(A, cfg)
    px, ema = st.px(A), st.ema_inputs(A, pool, rules)
    curve, dates, tr = Y.simulate(px, ema, rules, entries, *seg, audit=True)
    s = Y.stats(curve, dates, tr)
    b = ST.behaviour(curve, dates, tr)
    pnl = sorted((t['pnl'] for t in tr), reverse=True)
    profit = sum(x for x in pnl if x > 0)
    top = sorted(tr, key=lambda t: -t['pnl'])[:3]
    out = dict(total=s['total'], by_year=s['by_year'], maxdd=s['maxdd'], trades=len(tr), win=s['win'],
               behaviour_gap=ST.gap(b, st.his_targets())[0], behaviour=b,
               bought=[ST.bought(A, tr, located), len(located)],
               top2_share=float(sum(pnl[:2]) / profit) if profit > 0 else None,
               ex_top=float(curve[-1] - 1 - max(pnl[0], 0.0)) if pnl else float(curve[-1] - 1),
               top=[dict(code=t['code'], entry=t['entry'], kind=t['kind'], pnl=t['pnl'], ret=t['ret']) for t in top])
    if draws:
        out['placebo'] = Y.placebo_rank(px, ema, rules, entries, *seg, pool, draws=draws)
    del entries, mask, pool, tr
    return out


def verdict(base, cand):
    """One system under the pre-registered rule: better (whole segment higher, neither calendar year more than
    YEAR_TOL lower, still higher with each account's best trade taken out), worse, clearly worse drawdown,
    behaviour gap above the tolerance."""
    yrs = [y for y in base['by_year'] if y in cand['by_year']]
    better = (cand['total'] > base['total'] + 1e-12
              and all(cand['by_year'][y] >= base['by_year'][y] - YEAR_TOL for y in yrs)
              and cand['ex_top'] > base['ex_top'])
    return dict(better=bool(better), worse=bool(cand['total'] < base['total'] - 1e-12),
                same=bool(abs(cand['total'] - base['total']) < 1e-12),
                dd_bad=bool(cand['maxdd'] > base['maxdd'] + DD_WORSE),
                gap_bad=bool((cand['behaviour_gap'] or 9) > (base['behaviour_gap'] or 9) + GAP_WORSE),
                log_gain=float(np.log((1 + cand['total']) / (1 + base['total']))))


def accept(res, keys):
    """{candidate: passed, why, better, worse, same, verdicts, median log gain}: at least MIN_BETTER systems
    better, none with a clearly worse drawdown or a behaviour gap beyond the tolerance."""
    out = {}
    for k in keys:
        v = {sid: verdict(r['base'], r[k]) for sid, r in res.items() if k in r}
        better = [s for s, x in v.items() if x['better']]
        why = [f'better {len(better)} < {MIN_BETTER}'] if len(better) < MIN_BETTER else []
        why += [f'{s} drawdown' for s, x in v.items() if x['dd_bad']]
        why += [f'{s} behaviour' for s, x in v.items() if x['gap_bad']]
        out[k] = dict(passed=not why, why=why, better=better, worse=[s for s, x in v.items() if x['worse']],
                      same=[s for s, x in v.items() if x['same']], verdicts=v,
                      median_log_gain=float(np.median([x['log_gain'] for x in v.values()])) if v else None)
    return out


def change_for(spec, key, sid):
    """A candidate's common dict for one system: its own entry, else 'all' (null: off for that system)."""
    c = spec['candidates'][key]
    return c[sid] if sid in c else c.get('all')


def round_(name, ids=()):
    spec = json.loads((ROUNDS / f'{name}.json').read_text(encoding='utf-8'))
    path = OUT / f'common_{name.lower()}.json'
    res = json.loads(path.read_text(encoding='utf-8'))['systems'] if path.exists() else {}
    draws = spec.get('draws', 50)
    keys = list(spec['candidates'])

    def save():
        out = dict(name=name, spec=spec, segment=SELECT, systems=res, accept=accept(res, keys))
        path.write_text(json.dumps(out, indent=1, default=float), encoding='utf-8')
        return out
    for x in SY.all_():
        if (ids and x.id not in ids) or (not ids and x.id in res):
            continue
        st, cfg = x.load()
        A = st.arrays('us')
        located = his_select(st, A)
        r = {'base': evaluate(st, A, cfg, located, draws)}
        row(name, x.id, 'base', r['base'])
        for k in keys:
            ch = change_for(spec, k, x.id)
            r[k] = dict(r['base'], unchanged=True) if not ch else \
                dict(evaluate(st, A, dict(cfg, common=ch), located, draws), change=ch)
            row(name, x.id, k, r[k])
        res[x.id] = r
        save()
        del A
        gc.collect()
    out = save()
    for k, a in out['accept'].items():
        print('ACCEPT', name, k, a['passed'], a['why'], 'better', a['better'], 'worse', a['worse'], flush=True)
    return out


VCUTS = ('2024-09-30', '2025-09-30', '2026-06-30')


def validate(name):
    """notes/common_rounds/<name>.json {"systems": {id: common dict}}: each new version once on the validation
    segment (a fresh account from its first day, against the registered version), the four engineering gates, the
    down-market days, and every market over the whole window (reported only); reports/common_<name>.json."""
    from . import gate as G, panels, shorts as SH
    spec = json.loads((ROUNDS / f'{name}.json').read_text(encoding='utf-8'))
    path = OUT / f'common_{name.lower()}.json'
    res = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    pin = panels.pinned()['markets']
    for x in SY.all_():
        if x.id not in spec['systems'] or x.id in res:
            continue
        st, cfg = x.load()
        new = dict(cfg, common=spec['systems'][x.id])
        A = st.arrays('us')
        located = [t for t in st.located(A, st.trades()) if VALIDATE[0] <= t[0].entry_date <= VALIDATE[1]]
        r = {}
        for k, c in (('base', cfg), ('new', new)):
            v = evaluate(st, A, c, located, 50, seg=VALIDATE)
            entries, rules, mask, pool = st.build(A, c)
            px, ema = st.px(A), st.ema_inputs(A, pool, rules)
            curve, dates, tr = Y.simulate(px, ema, rules, entries, *VALIDATE, audit=True)
            v['down'] = SH.down_report(A, {'x': curve}, dates)['total']['x']
            v['gate_validate'] = dict(win=G.check_win(tr), fills=G.check_fills(A, tr))
            wc, wd, wt = Y.simulate(px, ema, rules, entries, *panels.WINDOW, audit=True)
            w = Y.stats(wc, wd, wt)
            v['window'] = dict(total=w['total'], by_year=w['by_year'], maxdd=w['maxdd'],
                               win=G.check_win(wt), fills=G.check_fills(A, wt))
            r[k] = v
            row(name, x.id, k, v)
            del entries, mask, pool, tr, wt
        g = dict(data=A.get('digest') == pin.get('us'), lookahead=G.check_lookahead(st, new, 'us', full=A, cuts=VCUTS))
        g['ok'] = bool(g['data'] and g['lookahead']['ok'] and r['new']['gate_validate']['win']['ok']
                       and r['new']['gate_validate']['fills']['ok'] and r['new']['window']['win']['ok']
                       and r['new']['window']['fills']['ok'])
        b, n = r['base'], r['new']
        checks = dict(gate=g['ok'], total=n['total'] >= b['total'], maxdd=n['maxdd'] <= b['maxdd'] + .01,
                      down=n['down'] >= b['down'],
                      behaviour=(n['behaviour_gap'] or 9) <= (b['behaviour_gap'] or 9) + GAP_WORSE)
        r.update(gate=g, checks=checks, passed=all(checks.values()))
        del A
        gc.collect()
        r['markets'] = {}
        for m in ('hk', 'cn'):
            B = st.arrays(m)
            r['markets'][m] = {}
            for k, c in (('base', cfg), ('new', new)):
                v = evaluate(st, B, c, [], 50, seg=panels.WINDOW)
                r['markets'][m][k] = {q: v[q] for q in ('total', 'by_year', 'maxdd', 'trades', 'win', 'placebo')}
                row(name, x.id, f'{m} {k}', v)
            del B
            gc.collect()
        res[x.id] = r
        print('VALIDATE', x.id, 'passed', r['passed'], checks, flush=True)
        path.write_text(json.dumps(res, indent=1, default=float), encoding='utf-8')
    return res


def row(name, sid, k, r):
    p = r.get('placebo', {})
    print(name, sid, k, f"total {r['total']:+.3f} dd {r['maxdd']:.3f} years",
          {y: round(v, 3) for y, v in r['by_year'].items()}, f"rank {p.get('rank', float('nan')):.2f}",
          f"gap {r['behaviour_gap']:.3f}" if r['behaviour_gap'] is not None else 'gap -',
          'bought', r['bought'], 'n', r['trades'], f"top2 {r['top2_share'] or 0:.2f}", flush=True)


if __name__ == '__main__':
    if sys.argv[1] == 'funnel':
        funnel(sys.argv[2:])
    elif sys.argv[1] == 'round':
        round_(sys.argv[2], sys.argv[3:])
    elif sys.argv[1] == 'validate':
        validate(sys.argv[2])
    else:
        raise SystemExit(__doc__)
