"""David Trullas replication driver (see notes/RULES_CN.md, notes/PREREG_R*.md).

    PY=/opt/futu-opend/venv/bin/python
    $PY -m studies.david_trullas.replicate three  [round-json]   # three-layer comparison on his ledger
    $PY -m studies.david_trullas.replicate round R2              # one pre-registered round (selection quarters)
    $PY -m studies.david_trullas.replicate validate R6           # chosen config of a round, 2026 quarters, once
    $PY -m studies.david_trullas.replicate robust R6             # neighbours / costs / start shifts, report only

Selection = the four 2025 quarters, validation = 2026 Q1-Q3 (engine.SELECT / VALIDATE). Each quarter starts at
$2,500 like his contest accounts. Objective: the worst selection quarter's share of his log growth,
log(1 + ours) / log(1 + his). A candidate is carried only if it beats the reference on the objective, its
median quarter beats the same-day random-entry placebo median and the behaviour gates hold.
"""
from __future__ import annotations

import csv
import json
import math
import os
import sys
from dataclasses import asdict, replace

import numpy as np

from . import engine as E
from .data import at, load

HERE = os.path.dirname(__file__)
NOTES, REPORTS = os.path.join(HERE, 'notes'), os.path.join(HERE, 'reports')
GATES = dict(long_share=0.9, win=0.55, per_active_day=5.0)


def market():
    return E.Market(load())


def override(cfg, over):
    d = dict(over)
    if 'windows' in d:
        d['windows'] = tuple(tuple(w) for w in d['windows'])
    return replace(cfg, **d)


def cfg_of(spec):
    return override(E.Cfg(), spec)


def share(ours, his):
    return math.log1p(max(ours, -99.9) / 100) / math.log1p(his / 100)


def evaluate(mk, cfg, quarters, draws=0, seed=0):
    rows = {}
    for q in quarters:
        ret, tr = E.quarter(mk, cfg, q)
        a, b = E.day_range(mk, *E.QUARTERS[q][:2])
        st = E.stats(tr, b - a + 1)
        row = dict(ret=round(ret, 1), his=E.QUARTERS[q][2], share=round(share(ret, E.QUARTERS[q][2]), 3), **st)
        if draws:
            pl = placebo(mk, cfg, q, tr, draws, seed)
            row['placebo_med'] = round(float(np.median(pl)), 1)
            row['placebo_pct'] = round(float((np.array(pl) < ret).mean()), 3)
        rows[q] = row
    return rows


def placebo(mk, cfg, q, trades, draws, seed):
    """Same days, same number of trades, same stop distance (fraction), same target distance and units rule;
    entry minute drawn uniformly inside the entry windows of that day, entry at that bar's close."""
    rng = np.random.default_rng(seed)
    px = mk.px
    lo, hi, _ = E.QUARTERS[q]
    a, b = E.day_range(mk, lo, hi)
    by_day = {}
    for t in trades:
        by_day.setdefault(t.date, []).append(t)
    pools = {}
    for d in range(a, b + 1):
        if px['dates'][d] in by_day:
            s, e = mk.starts[d], mk.ends[d]
            m = px['mins'][s:e]
            ok = np.zeros(e - s, bool)
            for w0, w1 in cfg.windows:
                ok |= (m >= w0) & (m < w1)
            pools[d] = np.nonzero(ok)[0] + s
    out = []
    for _ in range(draws):
        entries = {}
        for d, pool in pools.items():
            ts = by_day[px['dates'][d]]
            picks = np.sort(rng.choice(pool, size=min(len(ts), len(pool)), replace=False))
            lst = []
            for i, t in zip(picks, ts):
                c = px['c'][i]
                rf = abs(t.entry - t.stop0) / t.entry
                tf = abs(t.target - t.entry) / t.entry
                lst.append((int(i), c, c * (1 - t.side * rf), c * (1 + t.side * tf), 'fixed_placebo', t.conf,
                            False, t.side))
            entries[d] = lst
        ret, _ = E.quarter(mk, cfg, q, entries=entries)
        out.append(ret)
    return out


def gates_ok(rows):
    fails = []
    for q, r in rows.items():
        if r.get('n', 0) == 0:
            fails.append(f'{q}: no trades'); continue
        if r['long_share'] < GATES['long_share']:
            fails.append(f'{q}: long share {r["long_share"]}')
        if r['win'] < GATES['win']:
            fails.append(f'{q}: win {r["win"]}')
        if r['per_active_day'] > GATES['per_active_day']:
            fails.append(f'{q}: {r["per_active_day"]} trades/day')
    return fails


def objective(rows):
    return min(r['share'] for r in rows.values())


def load_round(name):
    with open(os.path.join(NOTES, 'rounds', f'{name}.json'), encoding='utf-8') as f:
        return json.load(f)


def base_cfg(spec):
    """A round's base: {} = engine defaults, or {"from": "R3"} = chosen config of an earlier round, plus overrides."""
    spec = dict(spec)
    src = spec.pop('from', None)
    cfg = E.Cfg()
    if src:
        with open(os.path.join(REPORTS, f'{src.lower()}.json'), encoding='utf-8') as f:
            cfg = cfg_of(json.load(f)['chosen_cfg'])
    return override(cfg, spec)


def run_round(name):
    rd = load_round(name)
    mk = market()
    base = base_cfg(rd.get('base', {}))
    draws = rd.get('draws', 100)
    res = {'ref': dict(cfg=asdict(base), rows=evaluate(mk, base, E.SELECT, draws))}
    for cname, over in rd['candidates'].items():
        cfg = override(base, over)
        res[cname] = dict(over=over, cfg=asdict(cfg), rows=evaluate(mk, cfg, E.SELECT, draws))
    ref_obj = objective(res['ref']['rows'])
    best, best_obj = 'ref', ref_obj
    for cname, r in res.items():
        rows = r['rows']
        r['objective'] = round(objective(rows), 3)
        r['gate_fails'] = gates_ok(rows)
        r['beats_placebo'] = bool(np.median([x['ret'] for x in rows.values()])
                                  > np.median([x.get('placebo_med', -1e9) for x in rows.values()]))
        if cname == 'ref':
            continue
        if not r['gate_fails'] and r['beats_placebo'] and r['objective'] > best_obj:
            best, best_obj = cname, r['objective']
    out = dict(round=name, stage=rd.get('stage'), chosen=best, chosen_cfg=res[best]['cfg'], results=res)
    os.makedirs(REPORTS, exist_ok=True)
    with open(os.path.join(REPORTS, f'{name.lower()}.json'), 'w', encoding='utf-8') as f:
        json.dump(out, f, indent=1, ensure_ascii=False)
    print_round(out)
    return out


def print_round(out):
    print(f"== {out['round']} ({out['stage']}) chosen: {out['chosen']}")
    for cname, r in out['results'].items():
        rows = r['rows']
        cells = ' '.join(f"{q[2:]} {x['ret']:+.0f}% n{x.get('n', 0)} w{x.get('win', 0):.2f} "
                         f"pl{x.get('placebo_med', float('nan')):+.0f}" for q, x in rows.items())
        pts = sum(x.get('pts_total', 0) for x in rows.values())
        print(f"{cname:>8} obj {r['objective']:+.3f} pts {pts:+.0f} gates {'ok' if not r['gate_fails'] else r['gate_fails'][:2]} "
              f"placebo {'ok' if r['beats_placebo'] else 'no'} | {cells}")


def validate(name):
    with open(os.path.join(REPORTS, f'{name.lower()}.json'), encoding='utf-8') as f:
        chosen = cfg_of(json.load(f)['chosen_cfg'])
    mk = market()
    rows = evaluate(mk, chosen, E.VALIDATE, draws=200)
    sel = evaluate(mk, chosen, E.SELECT, draws=200)
    out = dict(round=name, cfg=asdict(chosen), selection=sel, validation=rows, gate_fails=gates_ok(rows),
               objective=round(objective(rows), 3))
    path = os.path.join(REPORTS, f'validate_{name.lower()}.json')
    if os.path.exists(path):
        raise SystemExit(f'{path} exists: the validation quarters are evaluated once')
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(out, f, indent=1, ensure_ascii=False)
    for part in ('selection', 'validation'):
        for q, r in out[part].items():
            print(part, q, r)
    return out


# ---------------------------------------------------------------- three-layer comparison on his ledger

def ledger_rows():
    with open(os.path.join(NOTES, 'trades.csv'), newline='', encoding='utf-8') as f:
        return list(csv.DictReader(f))


def three(cfg=None):
    """① his trades as he reported them; ② his day / minute / side with our execution on QQQ 1m (1 MNQ, points);
    ③ our own setups that day. Also: did our system have a setup within +-10 minutes of his entry?"""
    cfg = cfg or E.Cfg()
    mk = market()
    px = mk.px
    out = []
    for r in ledger_rows():
        if r['time_prec'] == 'unknown':
            continue
        d = px['dates'].index(r['entry_date']) if r['entry_date'] in px['dates'] else None
        i = at(px, r['entry_date'], r['time_et']) if d is not None else None
        if i is None:
            continue
        side = 1 if r['side'] == 'long' else -1
        e = mk.ends[d]
        entry = px['c'][i]
        lows = px['l'][i - 4:i + 1] if side == 1 else px['h'][i - 4:i + 1]
        stop = (lows.min() - E.TICK) if side == 1 else (lows.max() + E.TICK)
        top = px['h'][i - 30:i + 1].max() if side == 1 else px['l'][i - 30:i + 1].min()
        R = abs(entry - stop)
        tgt = E.target_of(cfg, side, entry, stop, top, R)
        k, fill, added, avg, why = E.manage(px, i, side, entry, stop, tgt, 1, cfg, e)
        ours = [s for s in E.setups(mk, d, cfg, side)]
        near = [s for s in ours if abs(s[0] - i) <= 10]
        out.append(dict(id=r['id'], date=r['entry_date'], time=r['time_et'], side=r['side'], his_outcome=r['outcome'],
                        his_pts=r['pts'], his_usd=r['usd_gross'],
                        l2_pts=round(side * (fill - entry) * E.NQ_PER_QQQ, 1), l2_stop_pts=round(R * E.NQ_PER_QQQ, 1),
                        l2_exit=why, l2_minutes=int(k - i),
                        l3_setups_that_day=len(ours), l3_within_10min=len(near)))
    return out


ROBUST = {   # one change each from the chosen config; report only, never used to choose
    'cost2': {'cost_pts': 2.0}, 'cost3': {'cost_pts': 3.0},
    'piv2': {'piv': 2}, 'no_hidden': {'hidden': False},
    'fib38': {'tgt': 'fib38'}, 'fib66': {'tgt': 'fib66'},
    'lev40': {'lev': 40.0}, 'lev200': {'lev': 200.0}, 'S300': {'lev_hi': 300.0, 'lev_until': 10.0},
    'losses3': {'max_losses': 3}, 'afternoon': {'windows': [[510, 660], [780, 945]]},
    'shorts': {'shorts': True},
}


def robust(name):
    with open(os.path.join(REPORTS, f'{name.lower()}.json'), encoding='utf-8') as f:
        chosen = cfg_of(json.load(f)['chosen_cfg'])
    mk = market()
    qs = E.SELECT + E.VALIDATE
    out = {}
    for vname, over in [('chosen', {})] + list(ROBUST.items()):
        rows = evaluate(mk, override(chosen, over), qs)
        out[vname] = {q: {k: r[k] for k in ('ret', 'n', 'win', 'pts_total', 'long_share') if k in r}
                      for q, r in rows.items()}
        print(f'{vname:>10} ' + ' '.join(f"{q[2:]} {r['ret']:+7.0f}% {r.get('pts_total', 0):+5.0f}p"
                                          for q, r in rows.items()))
    late = {}   # each quarter entered 10 sessions late
    for q in qs:
        lo, hi, _ = E.QUARTERS[q]
        a, b = E.day_range(mk, lo, hi)
        eq, tr = E.run(mk, chosen, a + 10, b)
        late[q] = round(100 * (eq / E.START - 1), 1)
    out['start_10_sessions_late'] = late
    print('late start', late)
    with open(os.path.join(REPORTS, f'robust_{name.lower()}.json'), 'w', encoding='utf-8') as f:
        json.dump(out, f, indent=1)


def main(argv):
    cmd = argv[0]
    if cmd == 'robust':
        return robust(argv[1])
    if cmd == 'round':
        run_round(argv[1])
    elif cmd == 'validate':
        validate(argv[1])
    elif cmd == 'three':
        cfg = None
        if len(argv) > 1:
            with open(os.path.join(REPORTS, f'{argv[1].lower()}.json'), encoding='utf-8') as f:
                cfg = cfg_of(json.load(f)['chosen_cfg'])
        rows = three(cfg)
        name = argv[1].lower() if len(argv) > 1 else 'base'
        with open(os.path.join(REPORTS, f'three_{name}.json'), 'w', encoding='utf-8') as f:
            json.dump(rows, f, indent=1)
        for x in rows:
            print(x)
        l2 = [x['l2_pts'] for x in rows]
        print('layer2: n %d, pts total %.1f, win %.2f; our setup within 10 min of his entry: %d/%d'
              % (len(l2), sum(l2), np.mean([p > 0 for p in l2]), sum(x['l3_within_10min'] > 0 for x in rows), len(rows)))
    else:
        raise SystemExit(__doc__)


if __name__ == '__main__':
    main(sys.argv[1:])
