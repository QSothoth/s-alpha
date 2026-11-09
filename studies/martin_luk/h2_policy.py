"""H2 market-only daily signals; trader identities and evaluation labels are never inputs."""
from __future__ import annotations

import numpy as np

from . import m1_research as M, t1_research as T
from studies.trader_replication import system as Y


def theme_groups(close, pool, night, leaders, upgrades, strength, amount, codes):
    centers = sorted(map(int, np.flatnonzero(leaders)),
        key=lambda j: (not upgrades[j], -float(strength[j]), -float(amount[j]), str(codes[j])))
    peers, _, _ = T.peer_groups(close, pool, night, centers)
    used, result = set(), []
    for j in centers:
        if j in used:
            continue
        members = [k for k in [j, *map(int, peers[j])] if k not in used]
        if sum(leaders[members]) >= 2:
            result.append(dict(center=j, members=sorted(members)))
            used.update(members)
    return result


def features(A, p, qqq):
    """One completed cross-section at a time, with only bounded historical slices."""
    c, h, l, o = (A[n] for n in ('close', 'high', 'low', 'open'))
    shape = c.shape
    result = {n: np.zeros(shape, bool) for n in ('pool', 'leaders', 'upgrades', 'distribution', 'stretch')}
    result.update(forms=np.zeros(shape, np.uint8), strength=np.full(shape, np.nan),
                  adr=np.full(shape, np.nan), cap=np.full(shape, np.nan, np.float32))
    groups, counts, stats = [], [], []
    e9, e21, e50 = (A['native_'+n] for n in ('e9', 'e21', 'e50'))
    from . import luk
    qema = luk.ema(np.asarray(qqq, float)[:, None], 21)[:, 0]
    result['qqq_good'] = np.isfinite(qqq) & (qqq >= qema)
    result['breadth_ok'] = np.zeros(shape[0], bool)
    for d in range(shape[0]):
        grouped = []
        if d >= 19:
            s = slice(d-19, d+1)
            with np.errstate(all='ignore'):
                adr_pct = (np.asarray(h[s], float)/l[s]-1).mean(axis=0)
                amount = np.asarray(p['turnover'][s], float).mean(axis=0)
                pool = np.isfinite(c[d]) & (adr_pct > .05) & (amount >= 20e6)
                result['adr'][d] = adr_pct*c[d]
                result['cap'][d] = np.where(amount >= 100e6, .3, .2)
                ranked = np.zeros(shape[1], bool)
                strength = np.full(shape[1], -np.inf)
                for horizon in (21, 63):
                    if d < horizon:
                        continue
                    ret = np.asarray(c[d], float)/c[d-horizon]-1
                    good = pool & np.isfinite(ret)
                    if good.any():
                        ranked |= good & (ret >= np.quantile(ret[good], .9))
                    strength = np.fmax(strength, ret)
                result['strength'][d] = strength
                leaders = pool & ranked & (e9[d] > e21[d]) & (e21[d] > e50[d])
                upgrades = leaders & ~result['leaders'][d-1]
                result['pool'][d], result['leaders'][d], result['upgrades'][d] = pool, leaders, upgrades
                touch = np.zeros(shape[1], bool)
                for t in range(max(19, d-4), d+1):
                    touch |= (l[t] <= e9[t]+.25*result['adr'][t]) | (l[t] <= e21[t]+.25*result['adr'][t])
                width = np.asarray(h[d], float)-l[d]
                upper_half = (width > 0) & (c[d] >= l[d]+.5*width)
                pull = touch & (c[d] > e9[d]) & upper_half & (e21[d] > e21[d-1])
                tight = ((h[d-1] <= h[d-2]) & (l[d-1] >= l[d-2])) | \
                    ((np.asarray(h[d-1], float)-l[d-1]) < .7*result['adr'][d-1])
                breakout = tight & (c[d] > h[d-1]) & (width > 0) & (c[d] >= l[d]+2*width/3)
                ep = (o[d] >= 1.1*np.asarray(c[d-1], float)) & (p['turnover'][d] >= 2*amount) & upper_half
                for j in np.flatnonzero(ep):
                    top = np.nanmax(h[max(0, d-251):d+1, j])
                    ep[j] = c[d, j] >= .85*top
                result['forms'][d] = pull.astype(np.uint8) | (breakout.astype(np.uint8) << 1) | (ep.astype(np.uint8) << 2)
                result['stretch'][d] = c[d] > e9[d]+3*result['adr'][d]
                if d >= 50:
                    history = np.asarray(p['turnover'][d-50:d])
                    previous_max = np.max(np.where(np.isfinite(history), history, -np.inf), axis=0)
                    result['distribution'][d] = np.isfinite(previous_max) & (p['turnover'][d] > previous_max) & \
                        (c[d] < l[d]+.5*width)
            grouped = theme_groups(c, np.flatnonzero(pool), d, leaders, upgrades, strength, amount, A['codes'])
        groups.append(grouped)
        counts.append(int(result['leaders'][d].sum()))
        if d >= 49:
            result['breadth_ok'][d] = counts[-1] >= .5*np.median(counts[-50:])
        stats.append(dict(day=str(A['days'][d]), pool=int(result['pool'][d].sum()), leaders=counts[-1],
                          upgrades=int(result['upgrades'][d].sum()), groups=len(grouped),
                          breadth_ok=bool(result['breadth_ok'][d])))
    return dict(result, groups=groups, stats=stats)


def build(A, directory, f, spec):
    rules = Y.Rules(**M.read(directory/'master_rules.json'))
    # The ordinary native short branch remains unchanged; tolerance governs longs only.
    if spec.get('limits') is False:
        from dataclasses import replace
        rules = replace(rules, max_new_long=4)
    native = M.load_book(directory, 'native')
    groups = [{j: k for k, g in enumerate(row) for j in g['members']} for row in f['groups']]
    books = []
    for d in range(len(A['days'])):
        row = []
        for j in np.flatnonzero(f['leaders'][d] & (f['forms'][d] > 0)):
            fill, adr = float(A['close'][d, j]), float(f['adr'][d, j])
            if fill > A['native_e9'][d, j]+2*adr:
                continue
            stop = float(min(A['low'][d, j], A['native_e21'][d, j])-spec['buffer']*adr)
            if not 0 < stop < fill:
                continue
            priority = (0, int(j not in groups[d]) if spec.get('theme', True) else 0,
                        int(not f['upgrades'][d, j]), -float(f['strength'][d, j]),
                        -float(A['to20'][d, j]), str(A['codes'][j]))
            kind = 'h2_'+('_'.join(n for bit, n in ((1, 'pull'), (2, 'break'), (4, 'ep')) if f['forms'][d, j] & bit))
            cap = .3 if f['cap'][d, j] > .25 else .2
            row.append((priority, int(j), 1, fill, stop, kind, None, None, cap))
        row += [((1, e[0], str(A['codes'][e[1]])), *e[1:]) for e in native[d] if e[2] < 0]
        books.append(row)
    ema = dict(e9=A['native_e9'], e21=A['native_e21'], idx_pb16=A['idx_pb16'])
    tolerance = dict(adr=f['adr'], groups=groups, strength=f['strength'], forms=f['forms'],
        e50=A['native_e50'], distribution=f['distribution'], stretch=f['stretch'],
        breadth_ok=f['breadth_ok'], qqq_good=f['qqq_good'], disaster=spec['disaster'],
        max_long=4 if spec.get('limits', True) else 0, weekly=4 if spec.get('limits', True) else 0,
        probe=spec.get('probe', True), retry=spec.get('retry', True), feedback=spec.get('feedback', True))
    return books, rules, ema, tolerance
