"""Prior-close reservation for long opening-limit orders; no current-session data."""
from collections import Counter
from math import isfinite
from struct import pack


def plan(candidates, holdings, close, equity, cash, rules, risk_fraction, year_new, limit_fraction=.05,
         fill_stop_pct_by_kind=None):
    """Reserve adds then entries, using only a previous-close account snapshot.

    Candidate tuples are (priority, column, side, stop, kind, size_risk, max_position,
    risk_multiplier, add_multiplier). Holdings are immutable snapshots. No opening or
    later prices are accepted here. Returned quantities are fixed shares.
    """
    fill_stop_pct_by_kind = fill_stop_pct_by_kind or {}
    if (equity <= 0 or limit_fraction <= 0 or rules.feedback_opened or
            any(not isfinite(p) or not 0 < p < 1 for p in fill_stop_pct_by_kind.values())):
        raise ValueError('unsupported preopen account or feedback')
    if any(h['side'] != 1 for h in holdings) or any(e[2] != 1 for e in candidates):
        raise ValueError('preopen planner only supports long positions')
    if any(not isfinite(h['mark']) or h['mark'] <= 0 for h in holdings):
        raise ValueError('a held position has no valid prior mark')
    gross = sum(h['shares'] * h['mark'] for h in holdings)
    room = max(0., rules.max_gross * equity - gross)
    cash_room = max(0., cash) if rules.gross_cost else float('inf')
    held = {h['j'] for h in holdings}
    kinds = Counter(h['kind'] for h in holdings)
    new_kinds, new_long, planned_new = Counter(), 0, 0
    entries, adds, trace = {}, {}, []

    def available(limit):
        return min(room / limit, cash_room / (limit * (1 + rules.buy_cost)))

    def reserve(quantity, limit):
        nonlocal room, cash_room
        room -= quantity * limit
        if rules.gross_cost:
            cash_room -= quantity * limit * (1 + rules.buy_cost)

    for h in sorted(holdings, key=lambda x: (x['entry_index'], x['code'])):
        if h['pending'] is None:
            continue
        j, prev = h['j'], close[h['j']]
        rec = {'type': 'add', 'j': j, 'kind': h['kind'], 'status': 'not_submitted'}
        if h['trail_pending'] or not isfinite(prev) or prev <= 0:
            rec['reason'] = 'pending_exit_or_missing_previous'
        else:
            limit = float(prev) * (1 + limit_fraction)
            policy = h['management']
            cap = min(policy.max_position, h['cap']) if rules.cap_adds_entry else policy.max_position
            mult = rules.add_cap_mult if h['add_mult'] is None else h['add_mult']
            if mult > 0:
                cap = min(cap * mult, rules.add_cap_limit)
            per_name = max(0., cap * equity - h['shares'] * prev) / limit
            quantity = min(rules.add_frac * h['shares0'], per_name, available(limit))
            if quantity * limit > .001 * equity:
                reserve(quantity, limit)
                adds[j] = {'shares': quantity, 'limit': limit}
                rec.update(status='submitted', shares=quantity, limit=limit, level=h['pending'])
            else:
                rec['reason'] = 'risk_or_budget'
        trace.append(rec)

    for pr, j, side, stop, kind, size_risk, max_pos, mult, add_mult in sorted(candidates, key=lambda e: e[0]):
        rec = {'type': 'entry', 'j': j, 'kind': kind, 'status': 'not_submitted'}
        own = kind in rules.max_new_by_kind
        prev = close[j]
        if j in held:
            rec['reason'] = 'already_held_or_reserved'
        elif rules.max_open and len(held) >= rules.max_open:
            rec['reason'] = 'position_limit'
        elif kind in rules.max_open_by_kind and kinds[kind] >= rules.max_open_by_kind[kind]:
            rec['reason'] = 'kind_position_limit'
        elif own and new_kinds[kind] >= rules.max_new_by_kind[kind]:
            rec['reason'] = 'kind_daily_limit'
        elif not own and rules.max_new_long and new_long >= rules.max_new_long:
            rec['reason'] = 'long_daily_limit'
        elif rules.max_new_all and planned_new >= rules.max_new_all:
            rec['reason'] = 'daily_limit'
        elif rules.max_new_year and year_new + planned_new >= rules.max_new_year:
            rec['reason'] = 'year_limit'
        elif (not isfinite(prev) or prev <= 0 or not isfinite(stop) or not 0 < stop < prev
              or pack('f', prev) == pack('f', stop)):
            rec['reason'] = 'invalid_previous_or_stop'
        elif size_risk is not None:
            raise ValueError('size-risk override is not known to be preopen')
        else:
            limit = float(prev) * (1 + limit_fraction)
            policy = rules.management_by_kind.get(kind, {})
            cap = policy.get('max_position', rules.max_position)
            if max_pos is not None:
                cap = min(cap, max_pos)
            fraction = risk_fraction * (mult if mult is not None else 1.)
            pct = fill_stop_pct_by_kind.get(kind)
            risk_per_share = (limit - stop if pct is None else
                              limit * ((1 + rules.buy_cost) - (1 - pct) * (1 - rules.sell_cost)))
            quantity = min(fraction * equity / risk_per_share, cap * equity / limit, available(limit))
            if quantity * limit > .001 * equity:
                reserve(quantity, limit)
                entries[(kind, j)] = {'shares': quantity, 'limit': limit, 'risk_unit': risk_per_share}
                held.add(j)
                kinds[kind] += 1
                planned_new += 1
                if own:
                    new_kinds[kind] += 1
                else:
                    new_long += 1
                rec.update(status='submitted', shares=quantity, limit=limit, stop=stop,
                           risk_fraction=fraction, priority=pr)
                if pct is not None:
                    rec.update(fill_stop_pct=pct, planned_loss_per_share=risk_per_share)
            else:
                rec['reason'] = 'risk_or_budget'
        trace.append(rec)
    return {'entries': entries, 'adds': adds, 'trace': trace,
            'unreserved_gross': room, 'unreserved_cash': cash_room if rules.gross_cost else None}
