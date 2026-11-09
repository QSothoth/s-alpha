"""Which of our own limits holds a registered system below the years its trader published?  Diagnosis only: every
variant lifts one limit of the registered configuration on the US window, nothing here is chosen or carried.  Years,
count, win rate, average win and loss, entry weight, his dated longs bought; reports/gap_review/limits_<id>.json.

    $PY -m studies.trader_replication.limits limits|years <id> ...
"""
from __future__ import annotations

import gc
import json
import sys
from dataclasses import replace

import numpy as np

from . import panels, review as RV, study as ST, systems as SY

WINDOW = panels.WINDOW
OPEN = dict(max_open=0, max_open_by_kind={})
NEW = dict(max_new_long=0, max_new_by_kind={})
SIZE = dict(max_position=1.0, max_gross=2.2)     # 220%: the most any of the three published (Flanders, NVDA 2024-01)
VARIANTS = dict(REG=({}, {}),
                NO_NEW=(NEW, {'max_new': 0}),
                NO_OPEN=(OPEN, {}),
                NO_MARKET=({}, {'filter': ''}),
                GROSS220=(dict(max_gross=2.2), {}),
                POS100=(dict(max_position=1.0), {}),
                SIZE=(SIZE, {}),
                RISKx2=(dict(risk_mult=2), {}),
                RISKx2_SIZE=(dict(SIZE, risk_mult=2), {}),
                ALL=(dict(NEW, **OPEN, **SIZE), {'max_new': 0, 'filter': ''}))


def one(system, A, his, rules_change, cfg_change):
    W, cfg = system.load()
    base = getattr(W, 'base', W)
    entries, rules, mask, pool = W.build(A, {**cfg, **cfg_change})
    change = dict(rules_change)
    mult = change.pop('risk_mult', 1)
    if mult != 1:                                  # the tiers too: Martin's risk comes from risk_low / risk_high
        change.update(risk=rules.risk * mult, risk_low=rules.risk_low * mult, risk_high=rules.risk_high * mult)
    for k in ('max_position', 'max_gross'):        # lifting only: a system already above stays where it is
        if k in change:
            change[k] = max(change[k], getattr(rules, k))
    rules = replace(rules, **change)
    st, tr = base.run(A, entries, WINDOW, pool, rules, placebo=0, audit=True)
    st.pop('_curve', None)
    b = st['behaviour']
    return dict(by_year=st['by_year'], total=st['total'], maxdd=st['maxdd'], per_year=b['per_year'], win=b['win'],
                avg_win=b['avg_win'], avg_loss=b['avg_loss'], days_win=b['days_win'],
                **{k: v for k, v in b.items() if 'weight' in k or 'open' in k}, top10=b.get('top10_share'),
                bought=ST.bought(A, tr, his))


def limits(id_):
    system = SY.get(id_)
    W, _ = system.load()
    base = getattr(W, 'base', W)
    A = base.arrays('us')
    his = [x for x in base.located(A, base.trades()) if WINDOW[0] <= x[0].entry_date <= WINDOW[1]]
    out = dict(id=id_, version=system.version, card=RV.card(id_).get('years'), variants={})
    print(id_, 'his', out['card'], 'dated', len(his), flush=True)
    for k, (r, c) in VARIANTS.items():
        s = out['variants'][k] = one(system, A, his, r, c)
        print(f"{k:12}", {y: round(v, 2) for y, v in s['by_year'].items()},
              f"dd {s['maxdd']:.2f} n/yr {s['per_year']:.0f} win {s['win']:.3f} aw {s['avg_win']:+.3f}",
              f"al {s['avg_loss']:+.3f} bought {s['bought']}", {a: round(v, 3) for a, v in s.items()
                                                                if ('weight' in a or 'open' in a) and v is not None},
              flush=True)
        RV.write(f'limits_{id_}.json', out)
    del A
    gc.collect()


def years(id_):
    """The registered system by entry year: count, win rate, average win / loss, entry weight, and the names that made
    the account (pnl / equity at entry, summed); reports/gap_review/years_<id>.json."""
    system = SY.get(id_)
    W, cfg = system.load()
    base = getattr(W, 'base', W)
    A = base.arrays('us')
    entries, rules, mask, pool = W.build(A, cfg)
    st, tr = base.run(A, entries, WINDOW, pool, rules, placebo=0, audit=True)
    curve = np.asarray(st.pop('_curve'))
    days = A['days'][(A['days'] >= WINDOW[0]) & (A['days'] <= WINDOW[1])]
    at = {str(d): float(curve[i]) for i, d in enumerate(days)}
    print(id_, {k: getattr(rules, k) for k in ('risk', 'max_position', 'max_gross', 'max_open', 'max_new_long',
                                               'risk_scale', 'feedback', 'risk_low', 'risk_high', 'margin_rate')},
          'filter', cfg.get('filter'), flush=True)
    out = {}
    for y in ('2024', '2025', '2026'):
        t = [x for x in tr if x['entry'][:4] == y and x['side'] > 0]
        ret = np.array([x['ret'] for x in t])
        win = ret > 0
        w = np.array([x['pnl'] / x['ret'] / at[x['entry']] if x['ret'] else 0.0 for x in t])
        names = {}
        for x in t:
            names[x['code']] = names.get(x['code'], 0.0) + x['pnl'] / at[x['entry']]
        top = sorted(names.items(), key=lambda kv: -kv[1])[:6]
        s = out[y] = dict(n=len(t), win=float(win.mean()), avg_win=float(ret[win].mean()), avg_loss=float(ret[~win].mean()),
                          weight=float(w.mean()), weight_win=float(w[win].mean()), weight_loss=float(w[~win].mean()),
                          max_win=float(ret.max()), big=int((ret >= .5).sum()), sum_contrib=float(sum(names.values())),
                          top=[(c, round(v, 3)) for c, v in top], ret=st['by_year'].get(y))
        print(y, {k: round(v, 3) if isinstance(v, float) else v for k, v in s.items()}, flush=True)
    RV.write(f'years_{id_}.json', out)
    del A
    gc.collect()


if __name__ == '__main__':
    for x in sys.argv[2:]:
        dict(limits=limits, years=years)[sys.argv[1]](x)
