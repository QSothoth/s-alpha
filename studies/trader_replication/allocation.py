"""Shared nomination budgets and account admission; never changes signal ranking."""
from dataclasses import replace

import numpy as np

from .config import ALLOCATION_RULES
from .regime import NAMES


def nominations(picks, maximum=0, cooldown=10):
    """Ordered nights including empty ones; only emitted names start cooldown."""
    if not isinstance(maximum, int) or isinstance(maximum, bool) or maximum < 0:
        raise ValueError('maximum must be a nonnegative integer (0 = unlimited)')
    if not isinstance(cooldown, int) or isinstance(cooldown, bool) or cooldown < 0:
        raise ValueError('cooldown must be a nonnegative integer')
    out, last = {}, {}
    for night in sorted(picks):
        if isinstance(picks[night], (set, frozenset)):
            raise ValueError('nominations must be ordered')
        chosen = []
        for code in dict.fromkeys(picks[night]):
            if night-last.get(code, -cooldown-1) <= cooldown:
                continue
            chosen.append(code)
            last[code] = night
            if maximum and len(chosen) >= maximum:
                break
        out[night] = chosen
    return out


def offers(entries, maximum=0):
    """Historical offer cap: truncate priority order before account admission."""
    return [sorted(row, key=lambda e: e[0])[:maximum] for row in entries] if maximum else entries


def switch_entries(A, entries, controls):
    """The same sourced state controls apply to longs and optional appended shorts."""
    for control in controls:
        name, values = control['field'], control['values']
        daily = [values[NAMES[int(s)]] for s in A['regime']]
        if name in ('max_open', 'rotate'):
            A['allocation_'+name] = np.asarray(daily)
            continue
        kept = []
        for d, row in enumerate(entries):
            if name == 'sides':
                row = [e for e in row if e[2] in daily[d]]
            elif name == 'setups':
                row = [e for e in row if e[5] in daily[d]]
            else:
                row = [tuple(e[:9])+(None,)*max(0, 9-len(e))+
                       ((e[9] if len(e) > 9 and e[9] is not None else 1.)*daily[d],)+tuple(e[10:])
                       for e in row] if daily[d] > 0 else []
            kept.append(row)
        entries = kept
    return entries


def policy(rules, options):
    """Successful-fill caps, open slots and rotation all belong to allocate."""
    for key in ('max_new', 'max_open', 'max_new_long', 'max_new_all', 'max_new_year', 'rotate_min_days'):
        if key in options and (not isinstance(options[key], int) or isinstance(options[key], bool) or options[key] < 0):
            raise ValueError(key+' must be a nonnegative integer')
    changes = {k: v for k, v in options.items() if k in ALLOCATION_RULES}
    mode = options.get('daily_cap', 'fills')
    if mode not in ('fills', 'offers'):
        raise ValueError('daily_cap must be fills or offers')
    if mode == 'fills' and 'max_new' in options:
        changes['max_new_long'] = options['max_new']
    return replace(rules, **changes)


def daily_reason(rules, side, kind, by_kind, longs, total, year):
    own = side > 0 and kind in rules.max_new_by_kind
    if own and by_kind.get(kind, 0) >= rules.max_new_by_kind[kind]:
        return 'daily_kind'
    if side > 0 and not own and rules.max_new_long and longs >= rules.max_new_long:
        return 'daily_long'
    if rules.max_new_all and total >= rules.max_new_all:
        return 'daily_all'
    if rules.max_new_year and year >= rules.max_new_year:
        return 'year'
    return ''


def slots_full(limit, positions, day=0, limits=None):
    limit = int(limits[day]) if limits is not None else limit
    return bool(limit and len(positions) >= limit)


def rotation_victim(rules, positions, close, day):
    held = [q for q in positions.values() if q.side > 0 and day-q.d0 >= max(1, rules.rotate_min_days)
            and np.isfinite(close[day, q.j]) and close[day, q.j]/q.fill-1 < rules.rotate_below]
    return min(held, key=lambda q: close[day, q.j]/q.fill) if held else None
