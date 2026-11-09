"""E21 descriptive measurements. Trader labels enter here, never the account's decision code."""
from __future__ import annotations

from collections import Counter
import csv

import numpy as np

from studies.trader_replication import mainleg
from . import e19_research as E19, e20_research as E20

E15, M = E19.E15, E19.E16.M
read, write = E19.read, E15.write
CATEGORIES = ('not_in_pool', 'pool_not_named', 'named_outside_window',
              'triggered_blocked', 'bought_lost', 'bought_won')


def prices(A):
    # coverage reads its fill prices from 'o'. These systems actually fill at the completed close.
    return {str(code): dict(o=A['close'][:, j], c=A['close'][:, j], h=A['high'][:, j], l=A['low'][:, j])
            for j, code in enumerate(A['codes'])}


def raw_leg(code, index, label, p):
    found = mainleg.legs([(code, index, label)], p, big=-np.inf)
    if not found:
        return None
    leg = found[0]
    lo0 = max(0, leg['peak']-60)
    lows = p[code]['l'][lo0:leg['peak']+1]
    trough = lo0+int(np.nanargmin(lows))
    leg.update(trough=trough, low=float(p[code]['l'][trough]))
    return leg


def qualified_days(leg, days, p):
    buys = {int(d)-1: [leg['code']] for d in days}
    measured = mainleg.coverage(buys, [leg], p)[0]
    return {r['fill'] for r in measured['buys'] if r['ok']}


def position(price, leg):
    return (price-leg['low'])/(leg['top']-leg['low']) if leg['top'] > leg['low'] else None


def missing_label(h, code, anchor):
    return dict(id=h['id'], code=code, entry=h['entry_date'], anchor=anchor, precision=h['precision'],
        original_window=[h['window_lo'], h['window_hi']], missing_label='no frozen-panel price label',
        category='not_in_pool', signal_stage='not_in_pool', leg_key=None, trough=None, peak=None,
        his_position=None, first_pick=None, first_trigger=None, first_qualified_trigger=None,
        first_buy=None, first_time_buy=None, matches=[], triggers=[], rejection_counts={},
        simple_bought=False, simple_won=False)


def stage(pool, named, signals, matches):
    if matches:
        return 'bought_won' if any(t['pnl'] > 0 and t['why'] != 'end' for t in matches) else 'bought_lost'
    return ('triggered_blocked' if signals else 'named_outside_window' if named else
            'pool_not_named' if pool else 'not_in_pool')


def no_trigger(A, j, leg, valid, stream, observations, named):
    """Describe the missing signal without treating an expired watch as an account rejection."""
    d0, peak = leg['entries'][0]['index'], leg['peak']
    within = [s for s in stream if d0-3 <= s['index'] < peak]
    late = [s['day'] for s in within if s['index'] not in valid]
    raw = []
    for d in sorted(valid):
        if d > 0 and A['close'][d, j] > A['high'][d-1, j]:
            inputs = (A['open'][d, j], A['high'][d, j], A['low'][d, j], A['close'][d, j],
                      A['high'][d-1, j], A['low'][d-1, j], A['adr'][d-1, j])
            stop = (M.capped_stop(float(A['close'][d, j]), float(A['low'][d, j]), A['adr'][d-1, j])
                    if np.isfinite(inputs).all() and min(inputs) > 0 else None)
            raw.append(dict(day=str(A['days'][d]), index=d, valid_stop=stop is not None))
    possible = [r for r in raw if r['valid_stop']]
    if possible:
        ages = [r['index']-max((d for d in named if d < r['index']), default=-10000) for r in possible]
        why = 'observation_expired' if all(age > 5 for age in ages) else 'observation_consumed'
    else:
        why = 'too_late_half_gone' if late else 'invalid_stop' if raw else 'no_breakout'
    removed = []
    if 'e21' in A:
        for r in possible:
            born = max((d for d in named if d < r['index']), default=None)
            if born is not None:
                breaks = np.flatnonzero(A['close'][born+1:r['index'], j] < A['e21'][born+1:r['index'], j])
                if len(breaks):
                    removed.append(str(A['days'][born+1+int(breaks[-1])]))
    return dict(reason=why, late_signals=late, qualified_price_breaks=raw,
                persistent_list_removed=sorted(set(removed)),
                observation_events=[e for e in observations if d0-8 <= e['index'] <= peak])


def funnel(A, R, streams, observations, work):
    days = list(map(str, A['days']))
    di, ci = {d: i for i, d in enumerate(days)}, {str(c): j for j, c in enumerate(A['codes'])}
    p = prices(A)
    his = E19.ledger()
    assert len(his) == 43
    all_picks = {}
    for day, names in R['picks'].items():
        for code in names:
            all_picks.setdefault(code, []).append(di[day])
    result = dict(runs={}, denominator=43)
    for name in ('BASE', 'S1'):
        directory = work/f'{name}_full'
        trades = read(directory/'C062_2024_trades.json')
        attempts = read(directory/'attempts.json')
        signal_by_code, trade_by_code, attempt_by_key, observed_by_code = {}, {}, {}, {}
        for s in streams[name]:
            assert s['fill'] == float(p[s['code']]['c'][di[s['day']]])
            signal_by_code.setdefault(s['code'], []).append(dict(s, index=di[s['day']]))
        for t in trades:
            assert t['fill'] == float(p[t['code']]['c'][di[t['entry']]])
            trade_by_code.setdefault(t['code'], []).append(t)
        for a in attempts:
            attempt_by_key[a['code'], a['day'], a['kind']] = a
        for o in observations:
            observed_by_code.setdefault(o['code'], []).append(dict(o, index=di[o['day']]))
        records = []
        for h in his:
            code, anchor = 'US.'+h['ticker'], h['entry_date'] or h['window_lo']
            d0 = int(np.searchsorted(A['days'], anchor))
            leg = raw_leg(code, d0, h['id'], p)
            if leg is None:
                records.append(missing_label(h, code, anchor))
                continue
            j, peak = ci[code], leg['peak']
            valid = qualified_days(leg, range(max(0, d0-3), peak), p)
            stop = max(valid, default=peak-1)
            pool = [days[d] for d in np.flatnonzero(R['pool'][:max(0, stop), j])]
            named = [d for d in all_picks.get(code, []) if d < stop]
            stream = signal_by_code.get(code, [])
            eligible = [s for s in stream if s['index'] in valid]
            matches = [t for t in trade_by_code.get(code, []) if di[t['entry']] in valid]
            matches.sort(key=lambda t: t['entry'])
            triggered = [dict(s, attempt=attempt_by_key.get((code, s['day'], s['kind']))) for s in eligible]
            assert all(s['attempt'] is not None for s in triggered), 'Every valid signal needs an actual account reason'
            first = matches[0] if matches else None
            time_matches = [t for t in trade_by_code.get(code, []) if d0-3 <= di[t['entry']] < peak]
            first_time = min(time_matches, key=lambda t: t['entry']) if time_matches else None
            simple = [t for t in trade_by_code.get(code, []) if 0 <= di[t['entry']]-d0 <= 3]
            rejected = Counter(s['attempt']['reason'] for s in triggered if s['attempt']['reason'] != 'filled')
            record = dict(id=h['id'], code=code, entry=h['entry_date'], anchor=anchor, anchor_session=days[d0],
                precision=h['precision'], original_window=[h['window_lo'], h['window_hi']],
                leg_key=code+'@'+days[peak], trough=days[leg['trough']], peak=days[peak],
                low=leg['low'], top=leg['top'], his_gain=leg['entries'][0]['gain'], censored=leg['censored'],
                his_position=position(float(p[code]['c'][d0]), leg),
                category=stage(pool, named, eligible, matches),
                signal_stage='triggered' if eligible else stage(pool, named, [], []),
                qualified_sessions=[days[d] for d in sorted(valid)], pool_nights=pool,
                pick_nights=[days[d] for d in named], first_pick=days[named[0]] if named else None,
                first_trigger=stream[0]['day'] if stream and stream[0]['index'] <= stop else None,
                first_qualified_trigger=eligible[0]['day'] if eligible else None,
                first_buy=first['entry'] if first else None, first_buy_position=position(first['fill'], leg) if first else None,
                first_buy_offset=di[first['entry']]-d0 if first else None,
                first_time_buy=first_time['entry'] if first_time else None,
                first_time_position=position(first_time['fill'], leg) if first_time else None,
                first_time_offset=di[first_time['entry']]-d0 if first_time else None,
                matches=matches, triggers=triggered, rejection_counts=dict(rejected),
                simple_bought=bool(simple), simple_won=any(t['pnl'] > 0 and t['why'] != 'end' for t in simple))
            if not eligible:
                record['no_trigger'] = no_trigger(A, j, leg, valid, stream, observed_by_code.get(code, []),
                                                  all_picks.get(code, []))
            records.append(record)
        old = E20.funnel(A, R, R['picks'], trades, attempts)
        old_saved = read(M.STUDY.root/f'reports/e20_work/{name}_train/funnel.json')
        result['runs'][name] = dict(records=records, counts=dict(Counter(r['category'] for r in records)),
            signal_counts=dict(Counter(r['signal_stage'] for r in records)),
            old_window_counts=old['counts'], old_saved_counts=old_saved['counts'],
            blocked_reasons=dict(Counter(a['attempt']['reason'] for r in records
                if r['category'] == 'triggered_blocked' for a in r['triggers'])),
            simple_bought=sum(r['simple_bought'] for r in records), simple_won=sum(r['simple_won'] for r in records),
            missing_labels=sum(bool(r.get('missing_label')) for r in records),
            merged_legs=len({r['leg_key'] for r in records if r['leg_key'] is not None}),
            merged_bought=len({r['leg_key'] for r in records if r['matches']}))
    target = [r['id'] for r in read(E19.WORK/'funnel.json')['R2']['records']
              if r['category'] == 'named_outside_window']
    assert len(target) == 20
    result['e20_twenty_ids'] = target
    result['e20_twenty'] = {name: [r for r in result['runs'][name]['records'] if r['id'] in target]
                           for name in ('BASE', 'S1')}
    write(work/'funnel.json', result)


def his_2026(A, work):
    p = prices(A)
    days = list(map(str, A['days']))
    di = {d: i for i, d in enumerate(days)}
    with M.STUDY.ledger.open(encoding='utf-8', newline='') as stream:
        his = [h for h in csv.DictReader(stream) if h['side'] == 'long'
               and (h['entry_date'] or h['window_lo']).startswith('2026')]
    anchors = [('US.'+h['ticker'], int(np.searchsorted(A['days'], h['entry_date'] or h['window_lo'])), h['id']) for h in his]
    legs = mainleg.legs(anchors, p)
    missing = [label for code, d, label in anchors if code not in p or not np.isfinite(p[code]['c'][d])]
    result = dict(raw_entries=len(his), big_legs=len(legs), censored=sum(l['censored'] for l in legs), missing=missing, runs={})
    for name in ('BASE', 'S1'):
        result['runs'][name] = {}
        for span, year in (('2026', '2026'), ('full', '2024')):
            trades = read(work/f'{name}_{span}/C062_{year}_trades.json')
            records = []
            for leg in legs:
                code, peak = leg['code'], leg['peak']
                lo0 = max(0, peak-60)
                trough = lo0+int(np.nanargmin(p[code]['l'][lo0:peak+1]))
                low = float(p[code]['l'][trough])
                ix = np.flatnonzero(p[code]['c'][trough:peak+1] >= low+.5*(leg['top']-low))
                midpoint = days[trough+int(ix[0])] if len(ix) else None
                mine = [t for t in trades if t['code'] == code]
                covered = bool(qualified_days(leg, [di[t['entry']] for t in mine], p))
                held = midpoint is not None and any(t['entry'] <= midpoint and
                    (t['exit'] > midpoint or t['exit'] == midpoint and t['why'] == 'end') for t in mine)
                records.append(dict(code=code, peak=days[peak], trough=days[trough],
                    anchors=[days[e['index']] for e in leg['entries']], censored=leg['censored'],
                    midpoint=midpoint, covered=covered, midpoint_held=held))
            result['runs'][name][span] = dict(covered=sum(r['covered'] for r in records),
                midpoint_held=sum(r['midpoint_held'] for r in records), records=records)
    write(work/'his_2026.json', result)


def big_winners(A, trades):
    di, ci = {str(d): i for i, d in enumerate(A['days'])}, {str(c): j for j, c in enumerate(A['codes'])}
    rows = []
    for t in trades:
        d, j = di[t['entry']], ci[t['code']]
        run = float(np.nanmax(A['high'][d:d+61, j])/t['fill']-1)
        rows.append(dict(code=t['code'], entry=t['entry'], run60=run, big=run >= .33,
                         censored=d+60 >= len(A['days']), pnl=t['pnl'], end=t['why'] == 'end'))
    def measure(part):
        big = [r for r in part if r['big']]
        other = [r for r in part if not r['big']]
        return dict(trades=len(part), tickers=len({r['code'] for r in part}),
            big_trades=len(big), big_tickers=len({r['code'] for r in big}), big_pnl=sum(r['pnl'] for r in big),
            other_pnl=sum(r['pnl'] for r in other), other_gross_losses=sum(min(0., r['pnl']) for r in other),
            big_realized=sum(r['pnl'] for r in big if not r['end']), other_realized=sum(r['pnl'] for r in other if not r['end']),
            end_mark=sum(r['pnl'] for r in part if r['end']),
            censored=len([r for r in part if r['censored']]), unknown=len([r for r in other if r['censored']]))
    return dict(all=measure(rows), annual={y: measure([r for r in rows if r['entry'].startswith(y)])
            for y in sorted({r['entry'][:4] for r in rows})}, records=rows)


def diagnose(A, R, signals, observations, work):
    funnel(A, R, signals, observations, work)
    his_2026(A, work)
    result = {}
    for name in ('BASE', 'S1'):
        result[name] = {}
        for span, year in (('train', '2024'), ('2026', '2026'), ('full', '2024')):
            directory = work/f'{name}_{span}'
            trades = read(directory/f'C062_{year}_trades.json')
            stats = read(directory/f'C062_{year}_stats.json')
            days = read(directory/f'C062_{year}_curve.json')['days']
            daily = E19.daily_positions(trades, days)
            maximum = lambda field: max(v[field] for v in daily.values())
            caps = dict(total=max(maximum('at_open'), maximum('at_close')),
                        retry=max(maximum('retry_at_open'), maximum('retry_at_close')),
                        new=max(v['new_base']+v['new_retry'] for v in daily.values()))
            assert caps['total'] <= 11 and caps['new'] <= 4 and caps['retry'] <= (2 if name == 'S1' else 0)
            attempts = read(directory/'attempts.json')
            evictions = read(directory/'make_room.json')
            for e in evictions:
                t = next(t for t in trades if t['code'] == e['evicted'] and t['entry'] == e['entry'] and t['why'] == 'make_room')
                assert not t['confirmed'] and t['kind'] == E19.RETRY
                assert t['executions'][-1]['price'] == float(A['close'][np.searchsorted(A['days'], t['exit']),
                                                                 list(map(str, A['codes'])).index(t['code'])])
                assert any(a['code'] == e['incoming'] and a['day'] == e['day'] and a['reason'] == 'filled' for a in attempts)
            result[name][span] = dict(annual=stats['annual'], account=stats['account'], total=stats['total'],
                maxdd=stats['maxdd'], periods=stats['periods'], caps=caps, evictions=len(evictions),
                winners=big_winners(A, trades))
    write(work/'diagnostics.json', result)
