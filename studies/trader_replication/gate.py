"""The engineering gate every replicated system passes before a person looks at its results.  The checks know
nothing about how the trader trades; they only ask whether the numbers can be trusted:

    data       the run used the common data layer (panels.TAG, its fingerprint) over the common window
    lookahead  what the system decides on days <= a cut day (entries, the arrays its exits read, its placebo pool) is
               the same when the bars after the cut are removed
    fills      every execution price lies inside that day's low..high
    win_rate   at most MAX_WIN over the run's closed trades (with at least MIN_TRADES; fewer is 'unchecked'): a
               higher one on these traders' kind of system means a bug or a leak, not an edge

How good a system is (returns against his published years, behaviour, placebo) is for a person to judge; this gate
only says "fit to be judged".
"""
from __future__ import annotations

import numpy as np

MAX_WIN = .35
MIN_TRADES = 30
CUTS = ('2024-09-30', '2025-09-30')
TOL = 1e-6


def closed(trades):
    """Trades the system closed itself; 'end' rows only mark open positions at the window's last close."""
    return [t for t in trades if t['why'] != 'end']


def check_win(trades):
    """Win rate of closed trades (ret > 0).  A non-finite return fails; fewer than MIN_TRADES is 'unchecked'."""
    tr = closed(trades)
    ret = np.array([t['ret'] for t in tr], float)
    if len(ret) and not np.all(np.isfinite(ret)):
        return dict(ok=False, status='failed', win=None, trades=len(tr), max_win=MAX_WIN, note='non-finite return')
    if len(ret) < MIN_TRADES:
        return dict(ok=True, status='unchecked', win=float((ret > 0).mean()) if len(ret) else None, trades=len(tr),
                    max_win=MAX_WIN, note=f'fewer than {MIN_TRADES} closed trades')
    win = float((ret > 0).mean())
    return dict(ok=win <= MAX_WIN, status='checked', win=win, trades=len(tr), max_win=MAX_WIN, note='')


def check_fills(A, trades):
    """Every trade carries its executions (engine audit) and every execution price lies inside that day's
    low..high; 'end' marks are valuations at the last close and are not executions."""
    di = {str(d): i for i, d in enumerate(A['days'])}
    ci = {str(c): j for j, c in enumerate(A['codes'])}
    bad, n = [], 0
    for t in trades:
        ex = t.get('executions')
        if not ex:
            bad.append(dict(code=t.get('code'), problem='no executions recorded'))
            continue
        j = ci[t['code']]
        for e in ex:
            if e['action'] == 'end':
                continue
            n += 1
            d = di[e['time'][:10]]
            lo, hi, p = A['low'][d, j], A['high'][d, j], e['price']
            if not (np.isfinite(lo) and np.isfinite(p) and lo * (1 - TOL) <= p <= hi * (1 + TOL)):
                bad.append(dict(code=t['code'], day=e['time'][:10], action=e['action'], price=p,
                                low=float(lo), high=float(hi)))
    return dict(ok=not bad and n > 0, executions=n, bad=bad[:20], n_bad=len(bad))


def _same(a, b):
    a, b = np.asarray(a), np.asarray(b)
    if a.shape != b.shape:
        return False
    if a.dtype == bool or b.dtype == bool or a.dtype.kind in 'OUS' or b.dtype.kind in 'OUS':
        return bool(np.array_equal(a, b))
    return bool(np.allclose(a, b, rtol=1e-9, atol=1e-12, equal_nan=True))


def _norm(x):
    if x is None or isinstance(x, (str, bool)):
        return x
    if isinstance(x, (int, np.integer)):
        return int(x)
    if isinstance(x, (float, np.floating)):
        return 'nan' if np.isnan(x) else round(float(x), 9)
    if isinstance(x, (tuple, list)):
        return tuple(_norm(v) for v in x)
    if isinstance(x, dict):
        return tuple(sorted((k, _norm(v)) for k, v in x.items()))
    return repr(x)


def decisions(study, A, cfg, k):
    """Everything the engine consumes up to row k: the entries in their order with every field, the account
    rules, the arrays the rules read by name, the signal mask and the placebo pool."""
    import dataclasses
    entries, rules, mask, pool = study.build(A, cfg)
    ema = study.ema_inputs(A, pool, rules)
    ent = [[_norm(tuple(e)) for e in lst] for lst in entries[:k + 1]]
    return ent, _norm(dataclasses.asdict(rules)), {n: v[:k + 1] for n, v in ema.items()}, mask[:k + 1], pool[:k + 1]


def check_lookahead(study, cfg, market, full=None, cuts=CUTS):
    """Decisions up to each cut day with the full panel vs with the panel cut after that day."""
    A = full if full is not None else study.arrays(market)
    out = []
    for cut in cuts:
        k = int(np.searchsorted(A['days'], cut, side='right')) - 1
        e1, r1, x1, m1, p1 = decisions(study, A, cfg, k)
        B = study.arrays(market, upto=cut)
        e2, r2, x2, m2, p2 = decisions(study, B, cfg, k)
        del B
        diff = []
        first = next((d for d in range(k + 1) if e1[d] != e2[d]), None)
        if first is not None:
            diff.append(f'entries differ from {A["days"][first]}')
        if r1 != r2:
            diff.append('rules differ')
        diff += [f'array {n} differs' for n in x1 if n not in x2 or not _same(x1[n], x2[n])]
        diff += [f'array {n} only with the cut panel' for n in x2 if n not in x1]
        if not _same(m1, m2):
            diff.append('signal mask differs')
        if not _same(p1, p2):
            diff.append('placebo pool differs')
        out.append(dict(cut=cut, ok=not diff, diff=diff))
    return dict(ok=all(x['ok'] for x in out), cuts=out)


def check_data(tag, digest, span, expect_tag, expect_digest, window, days):
    """The run read the pinned dataset (the digest the loaded panel carries) and its equity curve covers exactly
    the market's trading days of the common window."""
    why = []
    if tag != expect_tag:
        why.append(f'data {tag} != {expect_tag}')
    if not expect_digest or digest != expect_digest:
        why.append('loaded panel digest is not the pinned one')
    inside = [str(d) for d in days if window[0] <= str(d) <= window[1]]
    want = [inside[0], inside[-1]] if inside else None
    if list(span) != want:
        why.append(f'run covers {list(span)}, window trading days {want}')
    return dict(ok=not why, why=why, span=list(span))


def verdict(checks):
    return dict(ok=all(c['ok'] for c in checks.values()), **checks)
