"""Post-hoc (after e9_arms.json): C2 draws split by the drawn close vs the watch's break day; before-break is lookahead."""
from __future__ import annotations

from contextlib import ExitStack
from collections import defaultdict
import resource
from unittest.mock import patch

import numpy as np

from studies import trader_data as TD
from studies.trader_data import panel as TP, supplemental as SP
from studies.trader_replication import gate as G, system as Y
from . import e9_research as R, ie47_e1 as M
from .e1_board_smoke import offline
from .ie47_audit import progress, write

DRAWS = 20   # the first 20 of E9's C2 draws (same seed)
OUT = R.OUT/'e9_split.json'


def phase(entries, breaks, days):
    """(day index, code) -> 'before' / 'same' / 'after' the watch's close break in A."""
    out = {}
    for d, row in enumerate(entries):
        for (rank, born, code), *_ in row:
            b = breaks[(days[born], code)]
            out[(d, code)] = 'before' if d < b else 'same' if d == b else 'after'
    return out


def stats(trades):
    closed = G.closed(trades)
    r = np.array([t['r'] for t in closed])
    ret = np.array([t['ret_invested'] for t in closed])
    return dict(n=len(closed), mean_r=float(r.mean()) if len(r) else None, win=float((ret > 0).mean()) if len(r) else None,
                r5_rate=float((r >= 5).mean()) if len(r) else None,
                mean_ret=float(ret.mean()) if len(r) else None)


def run():
    if OUT.exists():
        raise ValueError('E9 split already recorded')
    st = M.IE47Study()
    st.progress = progress
    A = st.arrays('us')
    cfg = dict(candidate='E8c', profile_sha256=SP.sha(M.PROFILE), frozen_inputs_sha256=M.inputs_digest(st.selected(A)['sources']))
    trace = {}
    _, rules, _, pool = st.build(A, cfg, trace)
    result = st.selected(A)
    px, ema = st.px(A), st.ema_inputs(A, pool, rules)
    days = list(map(str, A['days']))
    di = {v: i for i, v in enumerate(days)}
    breaks = {(e['observed'], e['code']): di[e['day']] for e in trace['observations'] if e['why'] == 'triggered'}
    rng = np.random.default_rng(1)
    rows = defaultdict(lambda: defaultdict(list))
    for i in range(DRAWS):
        book = R.books(A, result, trace['observations'], 'C2', rng)
        tag = phase(book, breaks, days)
        legit = [[e for e in row if tag[(d, e[0][2])] != 'before'] for d, row in enumerate(book)]
        for span, (s, e) in R.SPANS.items():
            curve, _, trades = Y.simulate(px, ema, rules, book, s, e, audit=True)
            for p in ('before', 'same', 'after'):
                rows[span][p].append(stats([t for t in trades if tag[(di[t['entry']], t['code'])] == p]))
            curve2, _, trades2 = Y.simulate(px, ema, rules, legit, s, e, audit=True)
            rows[span]['no_before_account'].append(dict(total=float(curve2[-1]-1), **stats(trades2)))
        progress(f'split {i+1}/{DRAWS}')
    out = dict(post_hoc=True, draws=DRAWS, seed=1, source_sha256=R.fingerprints(), spans={})
    for span, parts in rows.items():
        out['spans'][span] = {p: {k: float(np.median([x[k] for x in v if x[k] is not None])) for k in v[0]}
                              for p, v in parts.items()}
    write(OUT, out)
    for span, v in out['spans'].items():
        progress(span+' '+'; '.join(f"{p}: " + ' '.join(f'{k}={x:.3f}' for k, x in s.items()) for p, s in v.items()))


if __name__ == '__main__':
    resource.setrlimit(resource.RLIMIT_AS, (1_500_000_000, 1_500_000_000))
    offline()
    original = TP.build
    def existing_load(market, mode=None, version=None, upto=None, **kwargs):
        return original(TD.dataset(market, mode, version), upto=upto, write_cache=False)
    def read_only_build(ds, upto=None, cache=True, write_cache=True):
        return original(ds, upto=upto, cache=cache, write_cache=False)
    with ExitStack() as stack:
        stack.enter_context(patch.object(TD, 'load', existing_load))
        stack.enter_context(patch.object(TP, 'build', read_only_build))
        run()
