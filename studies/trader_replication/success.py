"""G4/G5 success checks (PLAN_P1_CN, 2026-11-08); historical reports keep their verdicts.

Hard lines: no losing calendar year, closed win rate <=35% over >=30 trades,
>=52 entries each year. Sourced payoff, holding and annual counts must
be within 20%; sourced annual returns within 0.3 in log wealth. Random-entry
and top-two-removal results remain optional diagnostics, never vetoes.

card: source (or sources per field), per_year, behaviour, years.
ours: gate={data, lookahead, fills}, win, closed, counts={year: n},
      behaviour={payoff, days, days_win, days_loss}, years={year: return}.
"""
from __future__ import annotations

import numpy as np

from . import gate as G

MIN_PER_YEAR = 52
BEHAVIOUR_TOL, YEAR_TOL = .2, .3


def _deviation(value, target):
    if value is None or not np.isfinite(value):
        return float('inf')
    if isinstance(target, (list, tuple)):
        low, high = target
        target = low if value < low else high if value > high else value
    return abs(value/target-1) if target and value*target > 0 else (0. if value == target else float('inf'))


def _source(card, key):
    return card.get('sources', {}).get(key) or card.get('source')


def judge(card, ours):
    """[(rule, ok, why)]; missing required facts fail, unpublished targets are skipped."""
    out = []
    g = ours.get('gate', {})
    win, closed = ours.get('win'), ours.get('closed', 0)
    bad = [k for k in ('data', 'lookahead', 'fills') if g.get(k) is not True]
    win_ok = win is not None and np.isfinite(win) and closed >= G.MIN_TRADES and 0 <= win <= G.MAX_WIN
    out.append(('gate', not bad and win_ok,
                f"win {win if win is None else round(win, 3)} over {closed} closed"
                + (f"; not passed or unchecked: {', '.join(bad)}" if bad else '')))

    years, counts = ours.get('years', {}), ours.get('counts', {})
    bad_counts = {y: counts.get(y) for y in years if counts.get(y) is None or
                  not np.isfinite(counts[y]) or counts[y] < MIN_PER_YEAR}
    count_devs = {}
    for y in years:
        target = card.get('counts', {}).get(y, card.get('per_year'))
        if target is not None and _source(card, 'counts.'+y if y in card.get('counts', {}) else 'per_year'):
            count_devs[y] = _deviation(counts.get(y), target)
    far_counts = {y: v for y, v in count_devs.items() if v > BEHAVIOUR_TOL+1e-12}
    out.append(('count', bool(years) and not bad_counts and not far_counts,
                f'under 52 or missing: {bad_counts}; outside +-20%: {far_counts}'))

    his, behaviour = dict(card.get('behaviour', {})), dict(ours.get('behaviour', {}))
    for values in (his, behaviour):
        if 'payoff' not in values and values.get('avg_win') is not None and values.get('avg_loss', 0):
            values['payoff'] = abs(values['avg_win']/values['avg_loss'])
    devs = {k: _deviation(behaviour.get(k), h) for k, h in his.items()
            if k in ('payoff', 'days', 'days_win', 'days_loss', 'days_mean', 'median_days_win',
                     'median_days_loss', 'max_days') and h is not None and _source(card, k)}
    far = {k: round(v, 2) for k, v in devs.items() if v > BEHAVIOUR_TOL+1e-12}
    out.append(('behaviour', not far, f'outside +-20% or missing: {far}' if far else
                f'{len(devs)} sourced payoff / holding measures within +-20%'))

    gaps = {}
    for y, h in card.get('years', {}).items():
        if h is None:
            continue
        if years and not min(years) <= y <= max(years):
            continue
        if not _source(card, 'years.'+y):
            continue
        o = ours.get('years', {}).get(y)
        gaps[y] = abs(float(np.log((1 + o) / (1 + h)))) if (
            o is not None and np.isfinite(o) and np.isfinite(h) and 1 + o > 0 and 1 + h > 0) else float('inf')
    far = {y: round(v, 2) for y, v in gaps.items() if v > YEAR_TOL+1e-12}
    out.append(('years', not far, f'log gap over {YEAR_TOL}: {far}' if far else f'{len(gaps)} of his years within'))

    losing = {y: r for y, r in years.items() if r is None or not np.isfinite(r) or r < 0}
    out.append(('nonnegative', bool(years) and not losing, f'negative / missing years: {losing}'))
    return out


def passed(rows):
    return all(ok for _, ok, _ in rows)


def drop_top(A, entries, trades, k=2):
    """Diagnostic only: remove the k best closed trades' entries (same name and entry day)."""
    best = sorted((t for t in trades if t['why'] != 'end'), key=lambda t: -t['ret'])[:k]
    di = {str(d): i for i, d in enumerate(A['days'])}
    ci = {str(c): j for j, c in enumerate(A['codes'])}
    gone = {(di[t['entry']], ci[t['code']]) for t in best}
    return [[e for e in lst if (d, e[1]) not in gone] for d, lst in enumerate(entries)]
