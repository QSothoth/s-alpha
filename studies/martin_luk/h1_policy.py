"""H1 market-only decisions. No trader ledger, identities, dates, labels, or fitted portrait."""
from __future__ import annotations

from dataclasses import replace

import numpy as np

from . import m1_research as M, replicate as R, t1_research as T
from studies.trader_replication import system as Y


def active_groups(close, pool, night, watched, month, codes):
    """Disjoint T1 direct-peer stars; only eligible centers are evaluated, one vector at a time."""
    if not len(pool):
        return []
    valid = pool[np.isfinite(month[pool])]
    if not len(valid):
        return []
    threshold = np.quantile(month[valid], .8)
    centers = sorted((int(j) for j in pool if watched[j] and np.isfinite(month[j])),
                     key=lambda j: (-float(month[j]), str(codes[j])))
    used, output = set(), []
    peers, _, _ = T.peer_groups(close, pool, night, centers)
    for j in centers:
        if j in used:
            continue
        # T1 normalizes this night's pool once and evaluates one center vector at a time.
        members = np.array([k for k in [j, *map(int, peers[j])] if k not in used], dtype=int)
        if sum(watched[members]) < 2 or not np.isfinite(month[members]).all():
            continue
        strength = float(np.median(month[members]))
        if strength < threshold:
            continue
        output.append(dict(center=j, members=sorted(map(int, members)), strength=strength))
        used.update(map(int, members))
    return sorted(output, key=lambda g: (-g['strength'], str(codes[g['center']])))


def features(A, p):
    """Date-streamed cross-sections and bounded per-name memory, indexed by the following fill day."""
    shape = A['close'].shape
    attention = np.zeros(shape, bool)
    familiar = np.zeros(shape, bool)
    events = np.zeros(shape, bool)
    episodes = np.zeros(shape, np.int32)
    score = np.full(shape, np.nan)
    pool_mask = np.zeros(shape, bool)
    groups, stats = [[] for _ in A['days']], []
    last_familiar = np.full(shape[1], -1000, dtype=int)
    episode = np.zeros(shape[1], dtype=np.int32)
    up_before = np.zeros(shape[1], bool)
    watched = A['master_watch'] | A['b_eligible']
    c = A['close']
    for d in range(1, shape[0]):
        t = d-1
        pool = T.night_pool(p, t)
        pool_mask[d, pool] = True
        month = np.full(shape[1], np.nan)
        leaders = set()
        with np.errstate(all='ignore'):
            if t >= 21:
                month = c[t].astype(float)/c[t-21]-1
            for horizon in (21, 63, 126):
                if t < horizon or not len(pool):
                    continue
                ret = c[t, pool].astype(float)/c[t-horizon, pool]-1
                good = np.isfinite(ret)
                if good.any():
                    threshold = np.quantile(ret[good], .9)
                    ranked = pool[good & (ret >= threshold)]
                    # Attention is assigned below once; retain leaders until it is known.
                    leaders.update(map(int, ranked))
        if len(pool):
            amount = np.asarray(p['turnover'][t, pool], float)
            valid = np.isfinite(amount)
            if valid.any():
                attention[d, pool[valid & (amount >= np.quantile(amount[valid], .85))]] = True
            if t >= 21:
                hot = [j for j in leaders if attention[d, j]]
                last_familiar[hot] = t
        familiar[d] = last_familiar >= t-249
        up = A['e21'][t] > A['e50'][t]
        episode += up & ~up_before
        episodes[d], up_before = episode, up
        score[d] = np.asarray(A['adr'][t], float)*month
        with np.errstate(all='ignore'):
            mean_volume = np.asarray(p['volume'][max(0, d-20):d], float).mean(axis=0)
            events[d] = (d >= 20) & (A['open'][d] >= 1.1*c[d-1]) & (p['volume'][d] >= 2*mean_volume)
        groups[d] = active_groups(c, pool, t, watched[d], month, A['codes'])
        stats.append(dict(day=str(A['days'][d]), pool=len(pool), watched=int(watched[d, pool].sum()),
                          attention=int(attention[d].sum()), familiar=int(familiar[d].sum()),
                          groups=len(groups[d]), grouped_names=sum(len(g['members']) for g in groups[d])))
    return dict(attention=attention, familiar=familiar, events=events, episodes=episodes,
                score=score, pool=pool_mask, groups=groups, stats=stats)


def build(A, directory, f, spec):
    native = M.load_book(directory, 'native')
    raw = M.load_book(directory, 'master_filtered')
    rules = Y.Rules(**M.read(directory/'master_rules.json'))
    rules = replace(rules, max_new_long=4)
    if spec['holding'] == 'M3B':
        rules = replace(rules, trims=(), add_levels=(1., 10., 20.))
    if spec.get('e'):
        rules = replace(rules, risk=.005, risk_low=.0025, risk_high=.01, feedback=0, risk_scale='',
                        equity_state_days=20, equity_state_drawdown=.10, max_position=.35)
    if spec.get('c'):
        rules = replace(rules, entry_familiar='h1_familiar', entry_exception='h1_events')
    if spec.get('d'):
        rules = replace(rules, entry_episode='h1_episodes', entry_episode_max=3)
    if spec.get('a'):
        rules = replace(rules, entry_group_risk=True)
    # Original trigger shapes outside the watch gate, so a qualifying group can introduce a new name.
    weekly = R.weekly_breakouts(A)['EW1'] if spec.get('a') else None
    market = R.market_ok(A, A['master_pool'], A['master_watch'], 'IDX50') if spec.get('a') else None
    books, memberships = [], []
    for d, row in enumerate(raw):
        tagged = {j: k for k, g in enumerate(f['groups'][d]) for j in g['members']} if spec.get('a') else {}
        offered = {e[1]: e for e in row if e[2] > 0}
        if d >= 2 and tagged and market[d]:
            for j in tagged:
                if j in offered:
                    continue
                tight = (A['high'][d-1, j] <= A['high'][d-2, j] and A['low'][d-1, j] >= A['low'][d-2, j]) \
                    or (A['high'][d-1, j]/A['low'][d-1, j]-1)*100 <= .5*A['adr'][d-1, j]
                trigger = A['master_e10'][d, j] or A['master_e11'][d, j] or A['b_fire'][d, j] \
                    or (tight and A['high'][d, j] > A['high'][d-1, j]) or weekly[d, j]
                if not trigger or not f['pool'][d, j]:
                    continue
                fill = float(A['close'][d, j])
                stop = M.M.capped_stop(fill, float(A['low'][d, j]), A['adr'][d-1, j])
                if stop is not None:
                    offered[j] = (-float(A['to20'][d-1, j]), j, 1, fill, stop, 'n1')
        kept = []
        for j, e in offered.items():
            if spec.get('b') and not f['attention'][d, j]:
                continue
            group = tagged.get(j)
            rank = -float(f['score'][d, j]) if spec.get('b') and np.isfinite(f['score'][d, j]) else e[0]
            priority = (0, group, rank, str(A['codes'][j])) if group is not None else (1, 0, rank, str(A['codes'][j]))
            kept.append((priority, *e[1:]))
        kept += [((2, 0, e[0], str(A['codes'][e[1]])), *e[1:]) for e in native[d] if e[2] < 0]
        books.append(kept)
        memberships.append(tagged)
    ema = {n: A['native_'+n] for n in ('e9', 'e21')}
    ema.update(idx_pb16=A['idx_pb16'], h1_familiar=f['familiar'], h1_events=f['events'], h1_episodes=f['episodes'])
    return books, rules, ema, memberships
