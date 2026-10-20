"""The short side of a registered trader system: one implementation for the short research rounds (S*), the
comparison and the board (docs/TRADER_PROTOCOL_CN.md section 5).

A configuration with a `short` dict is a long-short system; without it nothing here touches the long system (the
wrapper passes the study's own build through unchanged).  The trader's study module supplies his short setups:

    short_setups(A, sc) -> ({name: day-t trigger mask}, placebo pool as of t-1)

and this module turns them into engine entries with the common short execution:

    fill     that day's close (the setups are close-confirmed, like the longs)
    stop     above: the day's high, at least stop_min (1%) above the fill; stop_cap > 0 moves a wider stop down to it
             (a rule of his own words only); a gap above the stop covers at the open (engine)
    order    the day's longs are opened before any short (Martin R53 'short_last'); shorts by 20-day turnover as of
             t-1 (most liquid first), at most max_new offered a day
    gate     'below<n>': only while the market index (equal-weight, the comparison's common liquid pool as of t-1)
             closed below its EMA n the day before; 'above<n>' the opposite; '' none
    manage   kind 's_<setup>' gets its own trail / partial fraction / position cap (engine management_by_kind),
             short_trims (R levels), short_max_days, targets (lines covered at, engine short_targets) and
             target_frac, max_open (open shorts per setup), risk_mult (size)
    borrow   a yearly fee on the shorts' value (engine borrow_rate), 3% unless the round says otherwise

Shorts are researched on US data only (HK: only designated securities can be sold short and we have no list; A
shares: securities lending is restricted): elsewhere the long system runs alone and the report says "not applicable".

    PY="nice -n 19 env OPENBLAS_NUM_THREADS=1 PYTHONUTF8=1 /opt/futu-opend/venv/bin/python"
    $PY -m studies.trader_replication.shorts round martin_luk S1
    $PY -m studies.trader_replication.shorts gate martin_luk s1.json      # look-ahead gate of a round's choice
    $PY -m studies.trader_replication.shorts render martin_luk
"""
from __future__ import annotations

from dataclasses import replace
import gc
import json
import sys
from pathlib import Path

import numpy as np

from . import fidelity as F, gate as G, panels, study as ST, system as Y

ROOT = Path(__file__).resolve().parents[2]
BORROW = .03                       # yearly, on short market value
SMALL = (10.0, 20e6)               # a short on a name under 10 USD or under 20M USD 20-day turnover is "small"
LONG_TOL = dict(trades=.03, win=.01, hold=.10)     # the longs' behaviour may move this much (relative / absolute)
MAX_DD_WORSE = .02
GATE = 'v2'                        # 2026-10-19, the user's short gate (docs/TRADER_PROTOCOL_CN.md section 5)
MIN_RANK = .90                     # alpha: the short-only account against same-pool random shorts
MAX_HOLD = 10                      # every closed short within this many sessions
MAX_SHARE = .25                    # closed shorts at most this share of the long-only system's closed longs


def lag(x, n=1):
    return ST.lag(x, n)


def ema1(x, n):
    a, out, e = 2 / (n + 1), np.full(len(x), np.nan), np.nan
    for t, v in enumerate(x):
        if np.isfinite(v):
            e = v if np.isnan(e) else a * v + (1 - a) * e
        out[t] = e
    return out


def market_index(A):
    """Equal-weight daily-rebalanced index of the comparison's common liquid pool (compare.FLOORS), the pool as of
    the day before: the same yardstick for every trader's short gate and for the down-market report."""
    from .compare import FLOORS
    key = '_short_index'
    if key not in A:
        price, turnover = FLOORS[A['market']]
        c = A['close']
        with np.errstate(invalid='ignore', divide='ignore'):
            pool = lag((A['raw'] >= price) & (A['to20'] >= turnover))
            r = np.where(pool & np.isfinite(lag(c)), c / lag(c) - 1, np.nan)
            mean = np.nanmean(r, axis=1)
        A[key] = np.cumprod(1 + np.nan_to_num(mean))
    return A[key]


def index_below(A, n):
    """Day t: the index closed below its EMA n at t's own close (use lag() for a decision on day t)."""
    idx = market_index(A)
    return idx < ema1(idx, n)


def gate_days(A, spec):
    """Days on which new shorts are allowed, decided at the previous close."""
    if not spec:
        return np.ones(len(A['days']), bool)
    if spec.startswith('below'):
        return lag(index_below(A, int(spec[5:])))
    if spec.startswith('above'):
        return lag(~index_below(A, int(spec[5:]))) & (np.arange(len(A['days'])) > 0)
    raise ValueError(spec)


def level_width(A, sc, d, j):
    """Stop distance above a level entry: 'cap' = his long stop rule turned over, min(5%, half the ADR as of t-1)
    and at least stop_min; a number = that fraction."""
    w = sc.get('stop_w', 'cap')
    if w == 'cap':
        adr = A['adr'][d - 1, j]
        w = min(.05, .5 * adr / 100) if np.isfinite(adr) else .05
    return max(w, sc.get('stop_min', .01))


def level_entries(A, name, armed, level, sc, out, at_open=False, below=False, stop_line=None):
    """A sell-short limit at `level`, decided before day t (armed and level use t-1 data): filled when the day opens
    below the level and trades up to it; the stop sits stop_w above the level and, when the day's high reaches it,
    the short is stopped that day (the price passes the level before it can reach the stop: exact on daily bars).
    at_open: sold at the open instead (armed may then also read the day's open, the first price of the day).
    below: a sell-stop under `level` instead (a breakdown): filled when the day trades down to it, at the open when it
    opens under it; when the day's high also reaches the stop the short counts as stopped that day -- exact after an
    open under the level, a pessimistic bound otherwise (the high may have come before the fill).
    stop_line: the stop at this (days x codes) line known before the day instead of stop_w (at least stop_min
    above the fill)."""
    o, h, l, to20 = A['open'], A['high'], A['low'], A['to20']
    for d, j in zip(*np.nonzero(armed)):
        if d == 0:
            continue
        lv = o[d, j] if at_open else level[d, j]
        if below and np.isfinite(lv) and np.isfinite(o[d, j]) and l[d, j] <= lv:
            lv = min(o[d, j], lv)
        elif not (np.isfinite(lv) and np.isfinite(o[d, j]) and (at_open or (not below and o[d, j] < lv <= h[d, j]))):
            continue
        w = level_width(A, sc, d, j)
        if stop_line is not None:
            if not np.isfinite(stop_line[d, j]):
                continue
            w = max(stop_line[d, j] / lv - 1, sc.get('stop_min', .01))
        s = max(stop_line[d, j], lv * (1 + sc.get('stop_min', .01))) if stop_line is not None else lv * (1 + w)
        pr = -to20[d - 1, j] if np.isfinite(to20[d - 1, j]) else 0.0
        mult = sc.get('risk_mult', 1.0)
        out[d].append((float(pr), int(j), -1, float(lv), float(s), f's_{name}', float(s) if h[d, j] >= s else None,
                       w / mult if mult != 1.0 else None))


def fired(A, m):
    """Days a short setup would have filled: a close mask itself; a level entry where the day traded up to the
    level from below the open."""
    if not isinstance(m, dict):
        return m
    if m.get('at_open') or m.get('stop') is not None:
        return m['armed'] & np.isfinite(A['open'])
    if m.get('below'):
        with np.errstate(invalid='ignore'):
            return m['armed'] & (A['low'] <= m['level'])
    with np.errstate(invalid='ignore'):
        return m['armed'] & (A['open'] < m['level']) & (m['level'] <= A['high'])


def short_entries(A, masks, sc):
    """Engine entries (priority, column, -1, fill, stop, 's_<name>', day_exit, size_risk) of the day-t masks; a mask
    given as {'armed', 'level'} is a level entry (level_entries), {'armed', 'stop'} a close entry with the stop at
    that line (still at least stop_min above the fill), a plain mask a close entry with the stop at the day's high."""
    c, h, to20 = A['close'], A['high'], A['to20']
    smin, cap, mult = sc.get('stop_min', .01), sc.get('stop_cap', 0.0), sc.get('risk_mult', 1.0)
    stops = sc.get('_stop_ref') or {}
    out = [[] for _ in range(len(c))]
    for name, m in masks.items():
        if isinstance(m, dict) and m.get('stop') is not None:      # a close entry with his own stop line
            stops = dict(stops, **{name: m['stop']})
            m = m['armed']
        elif isinstance(m, dict):
            level_entries(A, name, m['armed'], m.get('level'), sc, out, m.get('at_open', False),
                          m.get('below', False), m.get('stop_line'))
            continue
        ref = stops.get(name, h)
        for d, j in zip(*np.nonzero(m)):
            if d == 0:
                continue
            fill, s = c[d, j], ref[d, j]
            if not (np.isfinite(fill) and np.isfinite(s) and fill > 0):
                continue
            s = max(s, fill * (1 + smin))
            if cap:
                s = min(s, fill * (1 + cap))
            if not s > fill:
                continue
            pr = -to20[d - 1, j] if np.isfinite(to20[d - 1, j]) else 0.0
            width = (s - fill) / fill
            out[d].append((float(pr), int(j), -1, float(fill), float(s), f's_{name}', None,
                           width / mult if mult != 1.0 else None))
    return out


def combine(longs, shorts, short_last=True):
    """One entry list a day: with short_last every long of the day comes before any short (engine order)."""
    if not short_last:
        return [a + b for a, b in zip(longs, shorts)]
    return [[((0, e[0]),) + tuple(e[1:]) for e in a] + [((1, e[0]),) + tuple(e[1:]) for e in b]
            for a, b in zip(longs, shorts)]


def short_rules(rules, sc, kinds):
    mg = {k: v for k, v in (('trail', sc.get('trail')), ('trim_frac', sc.get('trim_frac')),
                            ('max_position', sc.get('max_position'))) if v is not None}
    out = replace(rules, management_by_kind={**rules.management_by_kind, **{k: mg for k in kinds}} if mg
                  else rules.management_by_kind,
                  short_trims=tuple(sc['trims']) if 'trims' in sc else rules.short_trims,
                  short_max_days=sc.get('max_days', rules.short_max_days),
                  short_targets=tuple(sc.get('targets', ())), short_target_frac=sc.get('target_frac', 0.0),
                  short_trim_day=sc.get('trim_day', 0), short_trim_day_frac=sc.get('trim_day_frac', 0.0),
                  borrow_rate=sc.get('borrow', BORROW))
    return out


def split_cfg(cfg):
    return {k: v for k, v in cfg.items() if k != 'short'}, cfg.get('short')


class LongShort:
    """A trader study with the short side added; everything else is the study's own."""

    def __init__(self, base):
        self.base = base

    def __getattr__(self, k):
        return getattr(self.base, k)

    def build(self, A, cfg, trace=None):
        long_cfg, sc = split_cfg(cfg)
        entries, rules, mask, pool = self.base.build(A, long_cfg, trace)
        if not sc or A['market'] != 'us':
            return entries, rules, mask, pool
        masks, spool = self.base.short_setups(A, sc)
        ok = gate_days(A, sc.get('gate', ''))
        masks = {k: dict(m, armed=m['armed'] & ok[:, None]) if isinstance(m, dict) else m & ok[:, None]
                 for k, m in masks.items()}
        se = short_entries(A, masks, sc)
        if sc.get('max_new'):
            se = [sorted(lst, key=lambda e: e[0])[:sc['max_new']] for lst in se]
        if trace is not None:
            trace['short_mask'] = np.any(np.stack([fired(A, m) for m in masks.values()]), axis=0) if masks                 else np.zeros_like(mask)
            trace['short_entries'] = se
            trace['short_pool'] = spool
        kinds = [f's_{k}' for k in masks]
        rules = short_rules(rules, sc, kinds)
        if sc.get('max_open'):                     # open shorts of each short setup
            rules = replace(rules, max_open_by_kind={**rules.max_open_by_kind, **{k: sc['max_open'] for k in kinds}})
        return combine(entries, se, sc.get('short_last', True)), rules, mask, pool | spool

    def short_only(self, A, cfg):
        """The same system with the longs taken out: (entries, rules, short pool)."""
        trace = {}
        entries, rules, mask, pool = self.build(A, cfg, trace)
        only = [[e for e in lst if e[2] < 0] for lst in entries]
        return only, rules, trace.get('short_pool', np.zeros_like(mask))


def wrap(st):
    return st if isinstance(st, LongShort) else LongShort(st)


# ----- evaluation -----

def run(st, A, entries, rules, pool, audit=True):
    px, ema = st.px(A), st.ema_inputs(A, pool, rules)
    return Y.simulate(px, ema, rules, entries, *panels.WINDOW, audit=audit)


def daily(curve):
    c = np.asarray(curve)
    return c / np.concatenate([[1.0], c[:-1]]) - 1


def down_report(A, curves, days):
    """Returns on the days the market index closed below its EMA 50 the day before, overall and by month."""
    d0 = int(np.searchsorted(A['days'], days[0]))
    down = lag(index_below(A, 50))[d0:d0 + len(days)]
    out = dict(days=int(down.sum()), share=float(down.mean()), total={}, up={}, months={})
    months = sorted({str(d)[:7] for d, x in zip(days, down) if x})
    for name, c in curves.items():
        r = daily(c)
        out['total'][name] = float(np.prod(1 + r[down]) - 1)
        out['up'][name] = float(np.prod(1 + r[~down]) - 1)
        for m in months:
            sel = down & np.char.startswith(days.astype(str), m)
            out['months'].setdefault(m, dict(days=int(sel.sum())))[name] = float(np.prod(1 + r[sel]) - 1)
    return out


def side_stats(tr, side):
    t = [x for x in tr if x['side'] == side and x['why'] != 'end']
    ret = np.array([x['ret'] for x in t]) if t else np.zeros(0)
    win = ret > 0
    return dict(trades=len(t), open_at_end=sum(1 for x in tr if x['side'] == side and x['why'] == 'end'),
                win=float(win.mean()) if len(t) else None,
                avg_win=float(ret[win].mean()) if win.any() else None,
                avg_loss=float(ret[~win].mean()) if (~win).any() else None,
                hold=float(np.mean([x['days'] for x in t])) if t else None,
                hold_win=float(np.mean([x['days'] for x in t if x['ret'] > 0])) if win.any() else None,
                hold_loss=float(np.mean([x['days'] for x in t if x['ret'] <= 0])) if (~win).any() else None,
                hold_max=int(max(x['days'] for x in t)) if t else None,
                pnl=float(sum(x['pnl'] for x in tr if x['side'] == side)),
                why={w: sum(1 for x in t if x['why'] == w) for w in sorted({x['why'] for x in t})})


def small_split(A, tr):
    """Short pnl on small names (price < 10 USD or 20-day turnover < 20M USD as of the entry) and the rest."""
    di = {str(d): i for i, d in enumerate(A['days'])}
    ci = {str(c): j for j, c in enumerate(A['codes'])}
    out = {'small': [0, 0.0, 0], 'other': [0, 0.0, 0]}
    for t in tr:
        if t['side'] > 0:
            continue
        d, j = di[t['entry']], ci[t['code']]
        small = A['raw'][d, j] < SMALL[0] or not A['to20'][d - 1, j] >= SMALL[1]
        k = out['small' if small else 'other']
        k[0] += 1
        k[1] += t['pnl']
        k[2] += t['ret'] > 0
    return {k: dict(trades=n, pnl=p, win=w / n if n else None) for k, (n, p, w) in out.items()}


def his_shorts(st, A, trace, tr):
    """His dated shorts inside the window: on the panel, signal on a day of the window, short actually opened."""
    if st.ledger is None or not Path(st.ledger).exists():
        return None
    inside = [t for t in st.trades() if t.side == 'short' and t.dated
              and panels.WINDOW[0] <= t.entry_date <= panels.WINDOW[1]]
    loc = F.locate(inside, A['days'], A['codes'], prefix=ST.PREFIX.get(A['market'], ''), has=A['has'])[0]
    m = trace.get('short_mask')
    hits = F.recall(m, loc, A['has'])['hits'] if m is not None and loc else 0
    ours = {(t['code'], t['entry']) for t in tr if t['side'] < 0}
    bought = sum(any((str(A['codes'][j]), str(A['days'][d])) in ours for d in range(a, b + 1)) for _, j, a, b in loc)
    return dict(all=len(inside), on_panel=len(loc), hits=hits, bought=bought,
                missing=sorted({t.ticker for t in inside if t.id not in {x[0].id for x in loc}}))


def top_shorts(A, tr, n=8):
    """The biggest short winners and losers with the bars to check their dates and prices by hand."""
    di = {str(d): i for i, d in enumerate(A['days'])}
    ci = {str(c): j for j, c in enumerate(A['codes'])}
    rows = []
    for t in sorted([t for t in tr if t['side'] < 0], key=lambda t: -t['pnl'])[:n] + \
            sorted([t for t in tr if t['side'] < 0], key=lambda t: t['pnl'])[:n // 2]:
        d, j = di[t['entry']], ci[t['code']]
        rows.append(dict(code=t['code'], kind=t['kind'], entry=t['entry'], exit=t['exit'], days=t['days'],
                         fill=t['fill'], stop=t['stop'], why=t['why'], ret=t['ret'], r=t['r'], pnl=t['pnl'],
                         bar=[float(A[k][d, j]) for k in ('open', 'high', 'low', 'close')],
                         exits=[(e['time'][:10], round(e['price'], 4), e['action']) for e in t.get('executions', [])
                                if e['action'] != 'entry']))
    return rows


def evaluate(st, A, cfg, draws=50):
    """Long-only, long-short and short-only accounts of one configuration on the common window."""
    st = wrap(st)
    long_cfg, sc = split_cfg(cfg)
    d0 = int(np.searchsorted(A['days'], panels.WINDOW[0]))
    d1 = int(np.searchsorted(A['days'], panels.WINDOW[1], side='right'))
    days = A['days'][d0:d1]
    from .compare import metrics
    out, curves = {}, {}
    e, rules, mask, pool = st.build(A, long_cfg)
    curves['long'], _, trl = run(st, A, e, rules, pool)
    out['long'] = metrics(curves['long'], days, trl, e, d0, d1)
    out['long_side'] = side_stats(trl, 1)
    out['long_win_gate'] = G.check_win(trl)
    trace = {}
    e, rules, mask, pool = st.build(A, cfg, trace)
    curves['both'], _, trc = run(st, A, e, rules, pool)
    out['both'] = metrics(curves['both'], days, trc, e, d0, d1)
    out['both_long'], out['both_short'] = side_stats(trc, 1), side_stats(trc, -1)
    out['gate'] = dict(win_rate=G.check_win(trc), fills=G.check_fills(A, trc))
    out['gate']['ok'] = all(x['ok'] for x in out['gate'].values())
    se, srules, spool = st.short_only(A, cfg)
    curves['short'], _, trs = run(st, A, se, srules, spool)
    out['short'] = metrics(curves['short'], days, trs, se, d0, d1)
    out['short_side'] = side_stats(trs, -1)
    if draws and any(se[d0:d1]):
        px, ema = st.px(A), st.ema_inputs(A, spool, srules)
        out['short']['placebo'] = Y.placebo_rank(px, ema, srules, se, *panels.WINDOW, spool, draws=draws)
    out['down'] = down_report(A, curves, days)
    out['small'] = small_split(A, trs)
    out['small_both'] = small_split(A, trc)
    out['his'] = his_shorts(st, A, trace, trc)
    out['top'] = top_shorts(A, trs)
    out['short_cfg'] = sc
    del trl, trc, trs
    gc.collect()
    return out


def passes(r):
    """The S-round gates, version v2 (docs/TRADER_PROTOCOL_CN.md section 5); [] = pass.  The shorts must pick
    better than chance (alpha), be short-lived and few, and not hurt the account; how much they add is the
    objective, not a gate."""
    fails = []
    if not r['gate']['ok']:
        fails.append('gate')
    L, C, S = r['long_side'], r['both_long'], r['short_side']
    if L['trades'] and (abs(C['trades'] - L['trades']) > LONG_TOL['trades'] * L['trades']
                        or abs((C['win'] or 0) - (L['win'] or 0)) > LONG_TOL['win']
                        or abs((C['hold'] or 0) - (L['hold'] or 0)) > LONG_TOL['hold'] * (L['hold'] or 1)):
        fails.append('long_behaviour')
    p = r['short'].get('placebo')
    if not p or not (r['short']['total'] > p['median'] and p['rank'] >= MIN_RANK):
        fails.append('alpha')
    if S.get('hold_max') is None or S['hold_max'] > MAX_HOLD:
        fails.append('hold')
    if not S['trades'] <= MAX_SHARE * L['trades']:
        fails.append('count')
    b, l = r['both'], r['long']
    if b['maxdd'] > l['maxdd'] + MAX_DD_WORSE:
        fails.append('maxdd')
    if r['down']['total']['both'] < r['down']['total']['long']:
        fails.append('down')
    return fails


def objective(r):
    """The long-short account over the whole window (then what the down-market part gained from the shorts)."""
    return (r['both']['total'], r['down']['total']['both'] - r['down']['total']['long'])


# ----- rounds -----

def study_of(trader):
    from . import systems
    x = systems.get(trader)
    return x, wrap(x.study), split_cfg(x.config)[0]


def round_(trader, name):
    """notes/rounds/<name>.json: {"stage", "base": "" | "<report>", "candidates": {key: short change}, "draws"};
    a candidate's short config = the base's short config (none for "") with the change merged one level deep;
    "replace": true in a candidate starts from {} instead."""
    sysx, st, long_cfg = study_of(trader)
    spec = json.loads((st.root / 'notes' / 'rounds' / f'{name}.json').read_text(encoding='utf-8'))
    base_short = None
    if spec.get('base'):
        rb = json.loads((st.reports / spec['base']).read_text(encoding='utf-8'))
        base_short = rb['provisional_short'] if spec.get('base_key') == 'provisional' else rb['chosen_short']
    A = st.arrays('us')
    out = dict(name=name, stage=spec.get('stage', ''), trader=trader, system=sysx.version, base=spec.get('base', ''),
               base_key=spec.get('base_key', 'chosen'), long_config=long_cfg, base_short=base_short, configs={},
               results={}, gate_version=GATE)
    draws = spec.get('draws', 50)
    keys = list(spec['candidates'])
    for k in keys:
        ch = dict(spec['candidates'][k])
        start = {} if ch.pop('replace', False) or base_short is None else base_short
        sc = ST.merged(start, ch)
        out['configs'][k] = sc
        r = evaluate(st, A, dict(long_cfg, short=sc), draws=draws)
        r['fails'] = passes(r)
        out['results'][k] = r
        line(name, k, r)
    ref_obj = (None, None)                         # the carried version's objective (none carried yet)
    if base_short is not None:
        ref_obj = tuple(rb['provisional_objective'] if spec.get('base_key') == 'provisional'
                        else rb['chosen_objective'])
    ok = [k for k in keys if not out['results'][k]['fails']]
    for k in keys:
        out['results'][k]['objective'] = list(objective(out['results'][k]))
    best = max(ok, key=lambda k: objective(out['results'][k])) if ok else None
    if best is not None and base_short is not None and ref_obj[0] is not None \
            and objective(out['results'][best])[0] <= ref_obj[0]:
        best = None
    # the registered longs alone already over the win-rate gate: the gate is not changed and nothing is carried, but
    # the best candidate that passes everything else is kept as 'provisional' for the user (and as a labelled base)
    waived = [k for k in keys if out['results'][k]['fails'] == ['gate']
              and not out['results'][k]['long_win_gate']['ok'] and out['results'][k]['gate']['fills']['ok']
              and (ref_obj[0] is None or objective(out['results'][k])[0] > ref_obj[0])]
    out['provisional'] = max(waived, key=lambda k: objective(out['results'][k])) if waived and not ok else None
    out['provisional_short'] = out['configs'][out['provisional']] if out['provisional'] else None
    out['provisional_objective'] = out['results'][out['provisional']]['objective'] if out['provisional'] else None
    out['chosen'] = best or ('base' if base_short is not None else 'none')
    out['chosen_short'] = out['configs'][best] if best else base_short
    out['chosen_objective'] = out['results'][best]['objective'] if best else list(ref_obj)
    out['ref_objective'] = list(ref_obj)
    st.reports.mkdir(parents=True, exist_ok=True)
    (st.reports / f'{name.lower()}.json').write_text(json.dumps(out, indent=1, default=float), encoding='utf-8')
    print(name, 'chosen', out['chosen'], flush=True)
    negations(st, out)
    render(trader)
    return out


def line(tag, k, r):
    b, l, s = r['both'], r['long'], r['short']
    p = s.get('placebo') or {}
    print(tag, k, f"short {s['total']:+.3f} n {r['short_side']['trades']} win {r['short_side']['win']} "
          f"placebo {p.get('median', float('nan')):+.3f} | both {b['total']:+.3f} dd {b['maxdd']:.2f} vs long "
          f"{l['total']:+.3f} dd {l['maxdd']:.2f} | years", {y: (round(b['by_year'][y], 3), round(l['by_year'][y], 3))
                                                          for y in l['by_year']},
          f"| down both {r['down']['total']['both']:+.3f} long {r['down']['total']['long']:+.3f}",
          f"| win {b['win']:.3f} gate {r['gate']['ok']} longs {r['both_long']['trades']}/{r['long_side']['trades']}",
          'fails', r.get('fails'), flush=True)


def negations(st, out):
    from . import negations as N
    path = st.root / 'notes' / 'NEGATIONS.json'
    for k, r in out['results'].items():
        if k == out['chosen']:
            continue
        reason = 'gates: ' + ', '.join(r['fails']) if r['fails'] else f"objective below {out['chosen']}"
        N.add(path, dict(round=out['name'], stage=out['stage'], candidate=k, change=out['configs'][k],
                         base=[out['base'], 'chosen'], chosen=out['chosen'], reason=reason, objective='down_gain',
                         evidence=dict(short_total=r['short']['total'],
                                       short_placebo_median=(r['short'].get('placebo') or {}).get('median'),
                                       both_total=r['both']['total'], long_total=r['long']['total'],
                                       both_by_year=r['both']['by_year'], long_by_year=r['long']['by_year'],
                                       down=r['down']['total'], win=r['both']['win']),
                         base_config=dict(out['long_config'], short=out['base_short'])))
    N.render(path, st.name)


def lookahead(trader, report):
    """The look-ahead gate on a round's chosen long-short configuration."""
    sysx, st, long_cfg = study_of(trader)
    res = json.loads((st.reports / report).read_text(encoding='utf-8'))
    cfg = dict(long_cfg, short=res['chosen_short']) if res['chosen_short'] else long_cfg
    g = G.check_lookahead(st, cfg, 'us')
    res['lookahead'] = g
    (st.reports / report).write_text(json.dumps(res, indent=1, default=float), encoding='utf-8')
    print(report, 'lookahead', g, flush=True)
    return g


# ----- report -----

def pct(x, f='{:+.0%}'):
    return '—' if x is None else f.format(x)


def render(trader):
    """studies/<id>/reports/SHORTS_CN.md from every s*.json of the trader."""
    sysx, st, _ = study_of(trader)
    files = sorted(st.reports.glob('s[0-9]*.json'), key=lambda p: int(''.join(ch for ch in p.stem if ch.isdigit())))
    rows = [json.loads(p.read_text(encoding='utf-8')) for p in files]
    L = [f'# {st.name} 的空头（多空一体）', '',
         f'多头 = 登记的 {sysx.version}（配置不动）；空头只在美股研究（港股只有指定证券能沽空、我们没有名单；A 股融券受限：'
         '均为“不适用”）。评测区间 2024-01-02 → 2026-10-16，冻结数据 `trader-data-v1`，全部是样本内。'
         '空单当天收盘卖空，止损在当日高点（至少高出 1%），跳空高开越过止损按开盘价回补；同一天先开多再开空；'
         f'借券费按年化 {BORROW:.0%} 计（数据里没有可借数量和费率，一律假设借得到）。'
         '口径与选择规则见 docs/TRADER_PROTOCOL_CN.md 第 5 节。由 `python -m studies.trader_replication.shorts render` 生成。', '']
    if not rows:
        (st.reports / 'SHORTS_CN.md').write_text('\n'.join(L) + '\n', encoding='utf-8')
        return
    L += ['## 各轮候选', '',
          '| 轮 | 候选 | 只做空：收益 / 回撤 | 笔数 / 胜率 / 平均赚亏 / 持有 | 安慰剂中位 / 排位 | 多空合计 vs 只做多（全段） | '
          '分年（合计 / 只做多） | 回撤（合计 / 只做多） | 下跌时段（合计 / 只做多） | 多头笔数 合计 / 只做多 | 合计胜率 | '
          '小盘空单（笔 / 盈亏） | 他的空单 命中 / 做到 | 结果 |', '|' + '---|' * 14]
    for r in rows:
        for k, x in r['results'].items():
            s, ss, b, l = x['short'], x['short_side'], x['both'], x['long']
            p = s.get('placebo') or {}
            yrs = ' '.join(f"{y[2:]}:{pct(b['by_year'][y])}/{pct(l['by_year'][y])}" for y in l['by_year'])
            h = x.get('his') or {}
            res = '带入' if k == r['chosen'] else '暂定（只差多头本身就不过的胜率门禁）' if k == r.get('provisional')                 else ('不过：' + '、'.join(x['fails']) if x['fails'] else '未选')
            L.append('| ' + ' | '.join([
                r['name'], k, f"{pct(s['total'])} / {pct(s['maxdd'], '{:.0%}')}",
                f"{ss['trades']} / {pct(ss['win'], '{:.0%}')} / {pct(ss['avg_win'], '{:+.1%}')} {pct(ss['avg_loss'], '{:+.1%}')}"
                f" / {'—' if ss['hold'] is None else format(ss['hold'], '.1f')}",
                f"{pct(p.get('median'))} / {'—' if not p else format(p['rank'], '.2f')}",
                f"{pct(b['total'])} vs {pct(l['total'])}", yrs,
                f"{pct(b['maxdd'], '{:.0%}')} / {pct(l['maxdd'], '{:.0%}')}",
                f"{pct(x['down']['total']['both'])} / {pct(x['down']['total']['long'])}",
                f"{x['both_long']['trades']} / {x['long_side']['trades']}", pct(b['win'], '{:.1%}'),
                f"{x['small']['small']['trades']} / {x['small']['small']['pnl']:+.2f}",
                f"{h.get('hits', '—')} / {h.get('bought', '—')}（共 {h.get('on_panel', '—')}）", res]) + ' |')
    last = rows[-1]
    ch = last['chosen']
    show = ch if ch in last['results'] else last.get('provisional')
    L += ['', f"## 当前带入：{last['name']} → {ch}" + (f"（暂定 {show}，待用户判断胜率门禁）" if show and show != ch else ''),
          '']
    if show:
        x = last['results'][show]
        L += ['空头配置：`' + json.dumps(last['configs'][show], ensure_ascii=False) + '`', '',
              '### 下跌时段（等权指数前一日收盘在 50 EMA 下方的日子），按月', '',
              '| 月份 | 下跌日数 | 多空合计 | 只做多 | 只做空 |', '|---|---|---|---|---|']
        for m, v in x['down']['months'].items():
            L.append(f"| {m} | {v['days']} | {pct(v['both'], '{:+.1%}')} | {pct(v['long'], '{:+.1%}')} | "
                     f"{pct(v['short'], '{:+.1%}')} |")
        L += ['', '### 头部空单（逐笔核对日期与价格）', '', '| 股票 | 形态 | 卖空日 | 卖空价 | 当日开 / 高 / 低 / 收 | 止损 | 回补 | 原因 | 收益 |',
              '|---|---|---|---|---|---|---|---|---|']
        for t in x['top']:
            L.append(f"| {t['code']} | {t['kind']} | {t['entry']} | {t['fill']:.2f} | "
                     f"{' / '.join(f'{v:.2f}' for v in t['bar'])} | {t['stop']:.2f} | "
                     f"{'；'.join(f'{a} {b} {c}' for a, b, c in t['exits'])} | {t['why']} | {pct(t['ret'], '{:+.1%}')} |")
        sm = x['small']
        L += ['', f"小盘空单（价格 < 10 美元或 20 日成交额 < 2000 万）：{sm['small']['trades']} 笔、盈亏 "
                  f"{sm['small']['pnl']:+.3f}（起始资金 1）；其余 {sm['other']['trades']} 笔、{sm['other']['pnl']:+.3f}。"
                  '小盘、热门股的空单在现实里常借不到或费率很高，这部分盈亏偏乐观。']
        rob = last.get('robust')
        if rob:
            L += ['', '### 稳健性（只报告，不用来选）', '', '| 变体 | 多空合计 | 只做多 | 只做空 | 回撤 合计 / 只做多 | 下跌时段 合计 / 只做多 |',
                  '|---|---|---|---|---|---|']
            for k, v in rob.items():
                L.append(f"| {k} | {pct(v['both'])} | {pct(v['long'])} | {pct(v['short'])} | "
                         f"{pct(v['maxdd'][0], '{:.0%}')} / {pct(v['maxdd'][1], '{:.0%}')} | "
                         f"{pct(v['down']['both'], '{:+.1%}')} / {pct(v['down']['long'], '{:+.1%}')} |")
    note = st.root / 'notes' / 'SHORTS_CONCLUSION_CN.md'
    if note.exists():
        L += ['', note.read_text(encoding='utf-8').strip()]
    (st.reports / 'SHORTS_CN.md').write_text('\n'.join(L) + '\n', encoding='utf-8')


if __name__ == '__main__':
    act = sys.argv[1]
    if act == 'round':
        round_(sys.argv[2], sys.argv[3])
    elif act == 'gate':
        lookahead(sys.argv[2], sys.argv[3])
    elif act == 'render':
        render(sys.argv[2])
    else:
        raise SystemExit(__doc__)
