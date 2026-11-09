"""WF01 entry observations and the three predeclared account switches."""
from dataclasses import replace

import numpy as np

from . import e15_research as E15, ie47_e1 as IE


def repeated_book(A, picks):
    days, codes = list(map(str, A['days'])), list(map(str, A['codes']))
    columns = {code: j for j, code in enumerate(codes)}
    entries = [[] for _ in days]
    episodes = np.full(A['close'].shape, -1, dtype=np.int32)
    watching = {}
    o, h, low, close = (A[k] for k in ('open', 'high', 'low', 'close'))
    for d in range(1, len(days)):
        for rank, code in enumerate(picks.get(days[d-1], ())):
            if code not in columns:
                raise ValueError('IE47 pick not on the common panel: '+code)
            watching[columns[code]] = (d-1, d-1+IE.E6['E6c']['observe'], rank, False)
        for j, (born, expiry, rank, has_offer) in list(watching.items()):
            if d > expiry:
                del watching[j]
                continue
            episodes[d, j] = born
            inputs = (o[d, j], h[d, j], low[d, j], close[d, j], h[d-1, j],
                      low[d-1, j], A['adr'][d-1, j])
            if not np.isfinite(inputs).all() or min(inputs) <= 0 or close[d, j] <= h[d-1, j]:
                continue
            fill = float(close[d, j])
            width = max(.01, (fill-float(low[d, j]))/fill)
            cap = min(IE.E6['E6c']['cap_max'], float(A['adr'][d-1, j])/200)
            stop = float(min(low[d, j], fill*.99))
            if width > cap+1e-12:
                if cap < .01:
                    if not has_offer:
                        del watching[j]
                    continue
                stop = fill*(1-cap)
            entries[d].append(((rank, born, codes[j]), j, 1, fill, stop, IE.CLOSE_KIND, None))
            watching[j] = (born, expiry, rank, True)
    return entries, episodes


def build(A, picks, rules, *, c1=False, c2=False, c3=False):
    if c1:
        book, episodes = repeated_book(A, picks)
        rules = replace(rules, entry_episode='entry_episode', entry_episode_max=1)
    else:
        book = IE.entry_book(A, picks, **IE.E6['E6c'])[0]
        episodes = None
    if c2:
        rules = replace(rules, rotate_below=.02, rotate_min_days=3)
    if c3:
        rules = replace(rules, risk=.005)
    book, metadata = E15.P.retry_book(A, book, {}, E15.SPECS['C062'])
    book = [[tuple(e[:7])+(None, .30)+tuple(e[9:]) for e in row] for row in book]
    return book, episodes, rules, metadata
