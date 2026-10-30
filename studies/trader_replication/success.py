"""The success criteria of skills/trader-replication (user, 2026-10-29): a replication counts only when all seven
rules hold.  Selection inside a study stays with its own rounds; this only says whether a finished version is a
successful replication.

    1 gate        data, look-ahead, fills (gate.py, None until a compare run) and closed-trade win rate <= 35% with at
                  least 30 closed trades, for every style
    2 count       at least 52 trades a year (one a week) and within +-30% of his sourced count (or inside his sourced
                  range); no sourced count fails
    3 behaviour   every other measure he published (win, avg_win, avg_loss, days ...) within +-30%
    4 years       each of his years inside the data within 0.3 in |log((1 + ours) / (1 + his))|
    5 placebo     the whole segment above the same-pool random-entry median
    6 validate    the held-out segment, evaluated once, above its random-entry median
    7 not two     with his two best trades' entries removed, the whole segment still above the random-entry median

card  = dict(per_year=n | (lo, hi), source='...', behaviour={...}, years={name: his return})
ours  = dict(gate=dict(data=, lookahead=, fills=), win=, closed=, per_year=, behaviour={...}, years={name: ours},
             total=, placebo_median=, validate_total=, validate_placebo_median=, total_drop2=)
"""
from __future__ import annotations

import numpy as np

from studies.trader_options.goal import BEHAVIOUR_TOL, YEAR_TOL, deviations
from . import gate as G

MIN_PER_YEAR = 52


def _above(a, b):
    return a is not None and b is not None and a > b


def judge(card, ours):
    """[(rule, ok, why)] for the seven rules; a measure that is missing fails its rule."""
    out = []
    g = ours.get('gate', {})
    win, closed = ours.get('win'), ours.get('closed', 0)
    bad = [k for k in ('data', 'lookahead', 'fills') if g.get(k) is not True]
    win_ok = win is not None and closed >= G.MIN_TRADES and win <= G.MAX_WIN
    out.append(('gate', not bad and win_ok,
                f"win {win if win is None else round(win, 3)} over {closed} closed"
                + (f"; not passed or unchecked: {', '.join(bad)}" if bad else '')))

    n, his_n = ours.get('per_year'), card.get('per_year')
    if n is None or n < MIN_PER_YEAR:
        out.append(('count', False, f'{n} a year, under {MIN_PER_YEAR}'))
    elif his_n is None or not card.get('source'):
        out.append(('count', False, 'no sourced trade count of his'))
    else:
        dev = deviations({'per_year': n}, {'per_year': his_n})['per_year']
        out.append(('count', dev <= BEHAVIOUR_TOL, f'{n:.0f} a year vs his {his_n}: off {dev:.0%}'))

    devs = deviations(ours.get('behaviour', {}), card.get('behaviour', {}))
    far = {k: round(v, 2) for k, v in devs.items() if v > BEHAVIOUR_TOL}
    out.append(('behaviour', not far, f'outside +-30%: {far}' if far else f'{len(devs)} published measures within'))

    gaps = {}
    for y, h in card.get('years', {}).items():
        o = ours.get('years', {}).get(y)
        gaps[y] = abs(float(np.log((1 + o) / (1 + h)))) if o is not None and 1 + o > 0 else 9.0
    far = {y: round(v, 2) for y, v in gaps.items() if v > YEAR_TOL}
    out.append(('years', not far, f'log gap over {YEAR_TOL}: {far}' if far else f'{len(gaps)} of his years within'))

    out.append(('placebo', _above(ours.get('total'), ours.get('placebo_median')),
                f"{ours.get('total')} vs median {ours.get('placebo_median')}"))
    out.append(('validate', _above(ours.get('validate_total'), ours.get('validate_placebo_median')),
                f"{ours.get('validate_total')} vs median {ours.get('validate_placebo_median')}"))
    out.append(('not two', _above(ours.get('total_drop2'), ours.get('placebo_median')),
                f"without the best two {ours.get('total_drop2')} vs median {ours.get('placebo_median')}"))
    return out


def passed(rows):
    return all(ok for _, ok, _ in rows)


def drop_top(A, entries, trades, k=2):
    """The entries without those of the k best closed trades (same name, same entry day), for rule 7's rerun."""
    best = sorted((t for t in trades if t['why'] != 'end'), key=lambda t: -t['ret'])[:k]
    di = {str(d): i for i, d in enumerate(A['days'])}
    ci = {str(c): j for j, c in enumerate(A['codes'])}
    gone = {(di[t['entry']], ci[t['code']]) for t in best}
    return [[e for e in lst if (d, e[1]) not in gone] for d, lst in enumerate(entries)]
