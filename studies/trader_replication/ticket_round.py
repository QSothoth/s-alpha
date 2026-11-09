"""One ticket-first round: did the variant buy his dated longs of 2024-25, and what did it make on them?  Candidates
come from notes/PREREG_<round>.md; reports/gap_review/ticket_<id>_<round>.json.

    $PY -m studies.trader_replication.ticket_round martin T1
"""
from __future__ import annotations

import sys
from dataclasses import replace

import numpy as np

from . import panels, review as RV, study as ST, systems as SY

WINDOW = panels.WINDOW
NEW = dict(max_new_long=0, max_new_by_kind={})
ROUNDS = {('martin', 'T1'): ('martin_luk', dict(
    REG=({}, {}),
    T1A=(dict(max_position=.17), dict(max_new=8)),
    T1B=(dict(NEW, max_position=.17), dict(max_new=0)),
    T1C=(dict(max_position=.17), dict(max_new=8, priority='theme')),
    T1D=(dict(max_position=.17, max_gross=1.7), dict(max_new=8)))),
          ('martin', 'T2'): ('martin_luk', dict(
    REG=({}, {}),
    T2A=(dict(max_position=.17, nft_days=1), dict(max_new=8)),
    T2B=(dict(max_position=.17, nft_days=2), dict(max_new=8)),
    T2C=(dict(NEW, max_position=.17, nft_days=1), dict(max_new=0)),
    T2D=(dict(NEW, max_position=.17, nft_days=2), dict(max_new=0))))}


def one(W, base, A, his, rc, cc, cfg):
    entries, rules, mask, pool = W.build(A, {**cfg, **cc})
    rules = replace(rules, **rc)
    st, tr = base.run(A, entries, WINDOW, pool, rules, placebo=0, audit=True)
    st.pop('_curve', None)
    b = st['behaviour']
    ours = {}
    for t in tr:
        if t['side'] > 0:
            ours.setdefault((t['code'], t['entry']), t)
    got = []
    for t, j, a, z in his:
        for d in range(a, z + 1):
            x = ours.get((str(A['codes'][j]), str(A['days'][d])))
            if x:
                got.append((t.id, t.ticker, round(x['ret'], 3), round(x['r'], 1)))
                break
    return dict(by_year=st['by_year'], total=st['total'], maxdd=st['maxdd'], per_year=b['per_year'], win=b['win'],
                avg_win=b['avg_win'], avg_loss=b['avg_loss'], days_win=b['days_win'], days_loss=b.get('days_loss'), bought=len(got),
                ticket_mean_ret=float(np.mean([g[2] for g in got])) if got else None, tickets=got), (entries, rules, pool)


def main(who, name):
    id_, cands = ROUNDS[who, name]
    W, cfg = SY.get(id_).load()
    base = getattr(W, 'base', W)
    A = base.arrays('us')
    his = [x for x in base.located(A, base.trades()) if '2024-01-02' <= x[0].entry_date <= '2025-12-31' and x[0].side == 'long']
    out = dict(id=id_, round=name, tickets=len(his), results={})
    for k, (rc, cc) in cands.items():
        r, _ = one(W, base, A, his, rc, cc, cfg)
        out['results'][k] = r
        print(k, {y: round(v, 2) for y, v in r['by_year'].items()}, f"dd {r['maxdd']:.2f} n/yr {r['per_year']:.0f} win {r['win']:.3f}",
              f"aw {r['avg_win']:+.3f} al {r['avg_loss']:+.3f} dw {r['days_win']} dl {r['days_loss']} bought {r['bought']}/{len(his)} tmean {r['ticket_mean_ret']}", flush=True)
        RV.write(f'ticket_{id_}_{name}.json', out)




def scored(A, entries, keys, n):
    """The day's long signals ranked by the mean within-day percentile of `keys`, first n kept; shorts untouched."""
    from .signal_lift import feats
    out = []
    for d, lst in enumerate(entries):
        lon, sho = [e for e in lst if e[2] > 0], [e for e in lst if e[2] <= 0]
        if len(lon) > 1:
            f = [feats(A, d, e[1], 0) or {} for e in lon]
            s = np.zeros(len(lon))
            for k in keys:
                v = np.array([x.get(k, np.nan) for x in f], float)
                ok = np.isfinite(v)
                p = np.zeros(len(v))
                if ok.any():
                    p[ok] = (v[ok][:, None] > v[ok]).mean(1)
                s += p
            lon = [lon[i] for i in np.argsort(-s)[:n]]
        out.append(lon + sho)
    return out


T3 = dict(REG=None, T3A=(('dollar_range',), 4, {}), T3B=(('dollar_range', 'gain1'), 4, {}),
          T3C=(('dollar_range', 'gain1', 'rvol'), 4, {}), T3D=(('dollar_range', 'gain1'), 8, {}),
          T3E=(('dollar_range', 'gain1'), 8, dict(max_position=.17)))


def t3():
    W, cfg = SY.get('martin_luk').load()
    base = getattr(W, 'base', W)
    A = base.arrays('us')
    his = [x for x in base.located(A, base.trades()) if '2024-01-02' <= x[0].entry_date <= '2025-12-31' and x[0].side == 'long']
    all_e, rules, mask, pool = W.build(A, {**cfg, 'max_new': 0})
    reg, rg, _, pg = W.build(A, cfg)
    out = dict(id='martin_luk', round='T3', tickets=len(his), results={})
    for k, c in T3.items():
        if c is None:
            e, ru, po = reg, rg, pg
        else:
            e, ru, po = scored(A, all_e, c[0], c[1]), replace(rules, max_new_long=0, max_new_by_kind={}, **c[2]), pool
        st, tr = base.run(A, e, WINDOW, po, ru, placebo=0, audit=True)
        st.pop('_curve', None)
        b = st['behaviour']
        o = {(t['code'], t['entry']): t for t in tr if t['side'] > 0}
        got = [(t.id, t.ticker, round(o[(str(A['codes'][j]), str(A['days'][d]))]['ret'], 3)) for t, j, a, z in his for d in range(a, z + 1)
               if (str(A['codes'][j]), str(A['days'][d])) in o]
        r = out['results'][k] = dict(by_year=st['by_year'], maxdd=st['maxdd'], per_year=b['per_year'], win=b['win'], avg_win=b['avg_win'],
                                     avg_loss=b['avg_loss'], days_win=b['days_win'], bought=len({g[0] for g in got}), tickets=got)
        print(k, {y: round(v, 2) for y, v in r['by_year'].items()}, f"dd {r['maxdd']:.2f} n/yr {r['per_year']:.0f} win {r['win']:.3f}",
              f"aw {r['avg_win']:+.3f} al {r['avg_loss']:+.3f} dw {r['days_win']:.1f} bought {r['bought']}/{len(his)}", flush=True)
        RV.write('ticket_martin_luk_T3.json', out)


if __name__ == '__main__':
    t3() if sys.argv[1:] == ['t3'] else main(sys.argv[1], sys.argv[2])
