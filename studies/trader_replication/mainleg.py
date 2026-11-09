"""Main-leg evaluation. Legacy helpers below measure selection signals, not account results.

A leg is one stock's run from the trader's entry to the highest high within `horizon` sessions after it; his entries
of the same stock that reach the same peak are one leg (re-entries, duplicates). A leg is a big winner when the run
from his entry-day close to that high is at least `big`. We cover a leg when we buy it (signal on night t, fill at the
open of t+1) no earlier than `lead` sessions before one of his entries and before the peak day, at a price that still
leaves at least `keep` of his move from that entry. Two stricter readings are reported next to it: `synced` (the fill
is also within `lag` sessions after that entry, i.e. the same trade as his) and `held` (a stop `stop` below our fill
is never touched from the fill day through the peak). There is no random baseline: compare against a real reference
system, and keep legs we could not reach (not in our pool, data cut short) in the denominator, listed separately.
"""
from __future__ import annotations

from collections import deque
import math

import numpy as np


def legs(entries, prices, horizon=60, big=0.30):
    """entries: iterable of (code, entry_index, label). prices: code -> dict of 'o', 'h', 'l', 'c' arrays on one
    calendar.

    Returns big-winner legs: dict(code, peak, top, censored, entries=[dict(index, label, gain)]), ordered by first
    entry. The peak is searched from the entry day through `horizon` sessions after it; `censored` marks windows cut
    short by the end of the data.
    """
    grouped = {}
    for code, i0, label in entries:
        p = prices.get(code)
        if p is None or not np.isfinite(p['c'][i0]):
            continue
        h = p['h'][i0:i0 + horizon + 1]
        if not np.isfinite(h).any():
            continue
        peak = i0 + int(np.nanargmax(h))
        top = float(p['h'][peak])
        gain = top / float(p['c'][i0]) - 1
        if gain < big:
            continue
        leg = grouped.setdefault((code, peak), dict(code=code, peak=peak, top=top, entries=[],
                                                    censored=i0 + horizon >= len(p['h'])))
        if all(e['index'] != i0 for e in leg['entries']):
            leg['entries'].append(dict(index=int(i0), label=label, gain=gain))
    return sorted(grouped.values(), key=lambda x: (x['entries'][0]['index'], x['code']))


def coverage(buys, legs_, prices, lead=3, keep=0.5, lag=2, stop=0.03, pool=None):
    """buys: night index -> iterable of codes newly bought on the next session's open.
    pool: optional set of (code, night) we could have picked from; marks legs we could never reach.

    Per leg: covered / synced / held, the first qualifying buy (offset from his first entry, share of his move still
    ahead) and every buy that filled between `lead` sessions before his first entry and the day before the peak.
    """
    nights = {}
    for night, codes in buys.items():
        for code in codes:
            nights.setdefault(code, []).append(night)
    out = []
    for leg in legs_:
        p = prices[leg['code']]
        first = leg['entries'][0]['index']
        rows = []
        for night in sorted(nights.get(leg['code'], ())):
            fill = night + 1
            price = float(p['o'][fill]) if fill < len(p['o']) else np.nan
            if fill < first - lead or fill >= leg['peak'] or not (np.isfinite(price) and price > 0):
                continue
            ahead = leg['top'] / price - 1
            room = [e for e in leg['entries'] if fill >= e['index'] - lead and ahead >= keep * e['gain']]
            rows.append(dict(fill=fill, offset=fill - first, share=round(max(ahead / e['gain'] for e in leg['entries']), 3),
                             ok=bool(room), synced=any(fill <= e['index'] + lag for e in room),
                             held=bool(np.nanmin(p['l'][fill:leg['peak'] + 1]) > price * (1 - stop))))
        best = next((r for r in rows if r['ok']), None)
        reach = None if pool is None else any((leg['code'], t) in pool for t in range(first - lead - 1, leg['peak']))
        out.append(dict(code=leg['code'], first=first, peak=leg['peak'], gain=leg['entries'][0]['gain'],
                        entries=[e['label'] for e in leg['entries']], censored=leg['censored'], reachable=reach,
                        covered=best is not None, synced=any(r['ok'] and r['synced'] for r in rows),
                        held=any(r['ok'] and r['held'] for r in rows), buy=best, buys=rows))
    return out


def entry_hits(buys, entries, lead=3, lag=2):
    """His other entries (not big winners): did we buy the same stock from `lead` before to `lag` after his day?"""
    nights = {}
    for night, codes in buys.items():
        for code in codes:
            nights.setdefault(code, set()).add(night + 1)
    return [any(i0 - lead <= f <= i0 + lag for f in nights.get(code, ())) for code, i0, _ in entries]


def precision(buys, prices, horizon=60, big=0.30):
    """Share of our buys whose highest high within `horizon` sessions is at least `big` above the fill open."""
    hits = n = 0
    for night, codes in buys.items():
        for code in codes:
            p = prices.get(code)
            fill = night + 1
            if p is None or fill + horizon >= len(p['o']) or not (np.isfinite(p['o'][fill]) and p['o'][fill] > 0):
                continue
            n += 1
            hits += bool(np.nanmax(p['h'][fill:fill + horizon + 1]) / p['o'][fill] - 1 >= big)
    return dict(n=n, big=hits, rate=round(hits / n, 3) if n else None)


def summary(per_leg, groups):
    """groups: per-leg labels (e.g. year). Counts per reading and median timing of the covered legs."""
    out = {}
    for g in dict.fromkeys(groups):
        part = [r for r, x in zip(per_leg, groups) if x == g]
        hit = [r for r in part if r['covered']]
        out[g] = dict(n=len(part), covered=len(hit), synced=sum(r['synced'] for r in part),
                      held=sum(r['held'] for r in part), unreachable=sum(r['reachable'] is False for r in part),
                      censored=sum(r['censored'] for r in part),
                      offset=float(np.median([r['buy']['offset'] for r in hit])) if hit else None,
                      share=float(np.median([r['buy']['share'] for r in hit])) if hit else None)
    return out


def windows(legs_, prices, lead=3, keep=0.5):
    """Per leg: the signal nights whose next-open buy would cover it (same rule as `coverage`)."""
    out = []
    for leg in legs_:
        first = leg['entries'][0]['index']
        rows = coverage({t: {leg['code']} for t in range(first - lead - 1, leg['peak'] - 1)}, [leg], prices,
                        lead=lead, keep=keep)[0]['buys']
        out.append([r['fill'] - 1 for r in rows if r['ok']])
    return out


def net_share(buys, windows_, pool):
    """How wide the net is: per leg, distinct names we bought over its covering nights / names in the pool then.
    pool: set of (code, night)."""
    by_night = {}
    for code, night in pool:
        by_night.setdefault(night, set()).add(code)
    out = []
    for nights in windows_:
        if not nights:
            out.append(None)
            continue
        span = range(min(nights), max(nights) + 1)
        seen = set().union(*(by_night.get(t, set()) for t in span))
        picked = set().union(*(set(buys.get(t, ())) for t in span)) & seen
        out.append(len(picked) / len(seen) if seen else None)
    return out


def forward(buys, prices, horizon=60):
    """Highest high within `horizon` sessions after each next-open buy: median run, share ≥ 30% and ≥ 100%."""
    runs = []
    for night, codes in buys.items():
        for code in codes:
            p, fill = prices.get(code), night + 1
            if p is None or fill + horizon >= len(p['o']) or not (np.isfinite(p['o'][fill]) and p['o'][fill] > 0):
                continue
            runs.append(np.nanmax(p['h'][fill:fill + horizon + 1]) / p['o'][fill] - 1)
    runs = np.asarray(runs)
    return dict(n=len(runs), median=float(np.median(runs)) if len(runs) else None,
                ge30=float(np.mean(runs >= .3)) if len(runs) else None,
                ge100=float(np.mean(runs >= 1)) if len(runs) else None)


def lots(fills, pnl=None):
    """FIFO long fills, independent of a broker/ledger schema.

    A fill has integer `index`, signed `quantity` (buy > 0), `price`, and optional
    nonnegative `fee`. A terminal valuation sale has `open=True`. Unmatched buys
    are rejected: the adapter must supply a terminal mark. Partial sales produce
    separate matched pieces. Any supplied pnl residual is allocated by entry
    notional and exposed, never hidden.
    """
    queue, out, previous = deque(), [], -1
    for number, fill in enumerate(fills):
        index, quantity, price, fee = (fill['index'], float(fill['quantity']),
                                        float(fill['price']), float(fill.get('fee', 0.)))
        if (not isinstance(index, (int, np.integer)) or index < previous or index < 0 or
                not all(map(math.isfinite, (quantity, price, fee))) or
                quantity == 0 or price <= 0 or fee < 0):
            raise ValueError('invalid or unordered normalized fill')
        previous = int(index)
        if quantity > 0:
            queue.append(dict(entry=int(index), shares=quantity, price=price,
                              fee_share=fee/quantity, source=number))
            continue
        remaining = -quantity
        if remaining > sum(x['shares'] for x in queue) + 1e-10:
            raise ValueError('sale exceeds FIFO inventory')
        while remaining > 1e-12 and queue:
            buy = queue[0]
            size = min(remaining, buy['shares'])
            buy_fee, sell_fee = size*buy['fee_share'], fee*size/(-quantity)
            out.append(dict(entry=buy['entry'], exit=int(index), shares=size,
                            price=buy['price'], exit_price=price, buy_fee=buy_fee,
                            sell_fee=sell_fee, source=buy['source'], open=bool(fill.get('open', False)),
                            pnl=size*(price-buy['price'])-buy_fee-sell_fee, residual=0.))
            buy['shares'] -= size
            remaining -= size
            if buy['shares'] <= 1e-12:
                queue.popleft()
    if queue:
        raise ValueError('unmarked FIFO inventory')
    if pnl is not None:
        if not math.isfinite(pnl) or not out:
            raise ValueError('invalid expected pnl')
        residual = float(pnl)-sum(x['pnl'] for x in out)
        notional = sum(x['shares']*x['price'] for x in out)
        for row in out:
            row['residual'] = residual*row['shares']*row['price']/notional
            row['pnl'] += row['residual']
    return out


def _first(leg):
    return leg['first'] if 'first' in leg else min(e['index'] for e in leg['entries'])


def _gain(leg):
    return leg['gain'] if 'gain' in leg else min(leg['entries'], key=lambda e: e['index'])['gain']


def _key(leg):
    return leg.get('key', f"{leg['code']}:{_first(leg)}:{leg['peak']}")


def signal_coverage_budget(picks_by_night, ranks, legs_, calendar, opens, K, cooldown=10):
    """S signal yardstick; evaluation only, with no execution or account assumptions.

    Nights and leg anchors are indices on `calendar`. Picks are ordered codes;
    optional `ranks[night][code]` sort ascending, stably in the original order.
    K=None means unlimited width. Only emitted new names start the cooldown:
    the previous `cooldown` calendar sessions cannot emit that code again.
    Supply empty nights too, so mean width includes nights without signals.
    Opens need only contain labelled codes. Missing label prices never hit.
    Coverage groups by first-anchor year; precision groups by signal-night year.
    """
    if K is not None and (not isinstance(K, int) or isinstance(K, bool) or K < 1):
        raise ValueError('K must be a positive integer or None')
    if not isinstance(cooldown, int) or cooldown < 0:
        raise ValueError('cooldown must be a nonnegative integer')
    selected, last, raw = {}, {}, {}
    for t in sorted(picks_by_night):
        if not isinstance(t, (int, np.integer)) or not 0 <= t < len(calendar)-1:
            raise ValueError('signal night must have a next calendar session')
        codes = picks_by_night[t]
        if isinstance(codes, (set, frozenset)):
            raise ValueError('picks must preserve the system order')
        codes = list(dict.fromkeys(codes))
        if ranks is not None:
            codes.sort(key=lambda code: ranks[t][code])
        raw[t] = len(codes)
        chosen = []
        for code in codes:
            if t-last.get(code, -cooldown-1) <= cooldown:
                continue
            chosen.append(code)
            last[code] = t
            if K is not None and len(chosen) == K:
                break
        selected[t] = chosen

    per_leg, correct = [], set()
    for g in legs_:
        first_hit = None
        code, first, peak, gain = g['code'], _first(g), g['peak'], _gain(g)
        price_series = opens.get(code)
        if price_series is not None:
            for t in range(max(0, first-4), min(peak-1, len(calendar)-1)):
                if code not in selected.get(t, ()):
                    continue
                price = float(price_series[t+1])
                if not math.isfinite(price) or price <= 0:
                    continue
                share = (g['top']/price-1)/gain
                if share < .5-1e-12:
                    continue
                correct.add((t, code))
                if first_hit is None:
                    first_hit = dict(night=t, day=str(calendar[t]), fill=t+1,
                                     fill_day=str(calendar[t+1]), share=share)
        per_leg.append(dict(key=_key(g), code=code, year=str(calendar[first])[:4],
                            censored=bool(g.get('censored', False)), covered=first_hit is not None,
                            first_hit=first_hit))

    def summarize(year=None):
        rows = [r for r in per_leg if year is None or r['year'] == year]
        nights = [t for t in selected if year is None or str(calendar[t])[:4] == year]
        names = [code for t in nights for code in selected[t]]
        hit = [r['first_hit']['share'] for r in rows if r['covered']]
        hits = sum((t, code) in correct for t in nights for code in selected[t])
        return dict(n=len(rows), covered=len(hit), coverage=len(hit)/len(rows) if rows else None,
                    nights=len(nights), new_names=len(names), unique_names=len(set(names)),
                    mean_new_names=len(names)/len(nights) if nights else None,
                    mean_raw_names=sum(raw[t] for t in nights)/len(nights) if nights else None,
                    remaining_share_median=float(np.median(hit)) if hit else None,
                    precision_hits=hits, precision=hits/len(names) if names else None)

    years = sorted({r['year'] for r in per_leg} | {str(calendar[t])[:4] for t in selected})
    return dict(K=K, cooldown=cooldown, annual={y: summarize(y) for y in years},
                total=summarize(), per_leg=per_leg, picks=selected)


def leg_at(code, index, legs_, price, lead=3, keep=None):
    """Evaluation label only. One assignment; most remaining return, then earliest anchor.

    `keep` always uses the first anchor's gain, never a later add's smaller gain.
    The peak session itself cannot open a lot in this leg.
    """
    if not math.isfinite(price) or price <= 0:
        raise ValueError('invalid actual fill price')
    candidates = [g for g in legs_ if g['code'] == code and
                  max(0, _first(g)-lead) <= index < min(g['peak'], g.get('exit_known') or g['peak']) and
                  (keep is None or g['top']/price-1 >= keep*_gain(g)-1e-12)]
    return min(candidates, key=lambda g: (-(g['top']/price-1), _first(g), _key(g))) if candidates else None


def attribute_lots(trades, legs_, prices, calendar, other_legs=(), ticker_years=(), lead=3, keep=.5):
    """Normalize attribution, without changing any account decision.

    Each trade supplies `id`, `code`, `entry` (calendar index), matched `lots`,
    `closed`, `pnl`, and optional `confirmed` (first confirmation index).
    Prices may be a lazy mapping; only each lot's own stock is accessed.
    """
    result = []
    for trade in trades:
        code, year = trade['code'], str(calendar[trade['entry']])[:4]
        for piece in trade['lots']:
            g = leg_at(code, piece['entry'], legs_, piece['price'], lead)
            small = None if g else leg_at(code, piece['entry'], other_legs, piece['price'], lead)
            row = dict(piece, code=code, trade=trade['id'], year=year,
                       confirmed=trade.get('confirmed'), closed=trade['closed'],
                       leg=_key(g) if g else None, early=False, h_pnl=0., post_pnl=0.,
                       h_end=None, h_exit_price=None,
                       bucket='T3' if (code, year) in ticker_years else 'other')
            label = g or small
            # Pre-entry probes sold before his entry can cover a signal, but did not fund his move.
            if label is not None and piece['exit'] >= _first(label):
                end = min(piece['exit'], label['peak'], label.get('exit_known') or label['peak'])
                if piece['exit'] <= end:
                    inside = piece['pnl']
                    close = piece['exit_price']
                else:
                    close = float(prices[code]['c'][end])
                    if not math.isfinite(close) or close <= 0:
                        raise ValueError(f'missing cutoff close: {code} index {end}')
                    inside = piece['shares']*(close-piece['price'])-piece['buy_fee']
                row.update(bucket='T1' if g else 'T2', h_end=end,
                           h_pnl=inside, post_pnl=piece['pnl']-inside, h_exit_price=close)
            if g:
                row['early'] = g['top']/piece['price']-1 >= keep*_gain(g)-1e-12
                row['remaining'] = g['top']/piece['price']-1
            result.append(row)
    return result


def lifecycle_windows(legs_, prices, lookback=60):
    """Evaluation labels only: lowest low in [peak-lookback, peak], first low on ties.

    Keep the frozen anchor, gain, peak and leg identity. Only H's start changes.
    """
    result = []
    for g in legs_:
        begin = max(0, g['peak']-lookback)
        low = np.asarray(prices[g['code']]['l'][begin:g['peak']+1], float)
        if not np.isfinite(low).any():
            raise ValueError(f"missing lifecycle lows: {_key(g)}")
        start = begin+int(np.nanargmin(low))
        result.append(dict(g, window_start=start))
    return result


def _attribute_lifecycle_lots(trades, legs_, prices, calendar, ticker_years=(), keep=.5):
    """Partition each matched FIFO piece into disjoint H/O holding intervals.

    A boundary before session b is marked at close[b-1], like the existing
    post-peak boundary. Actual fills/fees remain at their actual sessions;
    entry cost, not the boundary mark, determines early buying and potential.
    Overlaps choose highest remaining return, then earliest frozen anchor.
    """
    result = []
    for trade in trades:
        code, year = trade['code'], str(calendar[trade['entry']])[:4]
        gs = [g for g in legs_ if g['code'] == code]
        for number, piece in enumerate(trade['lots']):
            begin, after = piece['entry'], piece['exit']+1
            cuts = sorted({begin, after} | {b for g in gs for b in (g['window_start'], g['peak']+1)
                                            if begin < b < after})
            intervals = []
            for start, stop in zip(cuts, cuts[1:]):
                candidates = [g for g in gs if g['window_start'] <= start <= g['peak']]
                g = min(candidates, key=lambda g: (-(g['top']/piece['price']-1), _first(g), _key(g))) if candidates else None
                if intervals and intervals[-1][2] is g:
                    intervals[-1] = (intervals[-1][0], stop, g)
                else:
                    intervals.append((start, stop, g))
            for start, stop, g in intervals:
                first, last = start == begin, stop == after
                basis = piece['price'] if first else float(prices[code]['c'][start-1])
                mark = piece['exit_price'] if last else float(prices[code]['c'][stop-1])
                if not all(math.isfinite(p) and p > 0 for p in (basis, mark)):
                    raise ValueError(f'missing lifecycle boundary close: {code} index {start}:{stop}')
                buy_fee = piece['buy_fee'] if first else 0.
                sell_fee = piece['sell_fee'] if last else 0.
                residual = piece['residual'] if last else 0.
                pnl = (piece['pnl'] if first and last else
                       piece['shares']*(mark-basis)-buy_fee-sell_fee+residual)
                result.append(dict(piece, code=code, trade=trade['id'], year=year,
                    entry=start, exit=piece['exit'] if last else stop, open=piece['open'] if last else False,
                    original_entry=piece['entry'], original_exit=piece['exit'], lot_piece=number,
                    trade_entry=trade['entry'], basis_price=basis, exit_price=mark,
                    buy_fee=buy_fee, sell_fee=sell_fee, residual=residual, pnl=pnl,
                    confirmed=trade.get('confirmed'), closed=trade['closed'], leg=_key(g) if g else None,
                    bucket='T1' if g else ('T3' if (code, year) in ticker_years else 'other'),
                    early=bool(g and g['top']/piece['price']-1 >= keep*_gain(g)-1e-12),
                    remaining=g['top']/piece['price']-1 if g else None,
                    h_pnl=pnl if g else 0., post_pnl=0., h_end=min(stop-1, piece['exit']) if g else None,
                    h_exit_price=mark if g else None, window_start=g['window_start'] if g else None))
    return result


def capital_days(rows, calendar, prices=None, equity=None):
    """Daily EOD exposure, O(days + lots*holding days) memory bounded to the calendar.

    The sale session has zero EOD inventory. A terminal valuation keeps the lot
    on that final close. H exposure ends at the peak close, confirmation starts
    on its actual day, never retroactively. Without prices use entry cost.
    """
    out = {name: np.zeros(len(calendar)) for name in ('gross', 'his', 'confirmed', 'his_confirmed')}
    for row in rows:
        start, stop = row['entry'], row['exit']+int(row['open'])
        sl = slice(start, stop)
        values = (np.full(max(0, stop-start), row['price']) if prices is None else
                  np.asarray(prices[row['code']]['c'][sl], float)) * row['shares']
        if not np.isfinite(values).all() or (values < 0).any():
            raise ValueError('missing or negative held close')
        out['gross'][sl] += values
        hstop = min(stop, row['h_end']+1) if row['bucket'] == 'T1' else start
        out['his'][start:hstop] += values[:max(0, hstop-start)]
        conf = row.get('confirmed')
        if conf is not None:
            begin = max(start, conf)
            if begin < stop:
                out['confirmed'][begin:stop] += values[begin-start:]
            if begin < hstop:
                out['his_confirmed'][begin:hstop] += values[begin-start:hstop-start]
    if equity is not None:
        eq = np.asarray(equity, float)
        if eq.shape != (len(calendar),) or not np.isfinite(eq).all() or (eq <= 0).any():
            raise ValueError('equity must be positive on every evaluation session, including cash days')
        out['his_equity'] = out['his']/eq
    return out


def account_coverage(rows, legs_, calendar, lag=2, *, lifecycle=False):
    """Actual first lot fill per leg; FIFO sale pieces never multiply coverage.

    A later add/retry cannot reset the first-fill clock. Ratios aggregate pnl
    and lot potentials; they are never averages of per-trade ratios.
    """
    result = []
    for g in legs_:
        part = [r for r in rows if r['leg'] == _key(g)]
        inside = [r for r in part if r['bucket'] == 'T1']
        first = min(part, key=lambda r: (r['entry'], str(r['trade']), r['source'])) if part else None
        potential = inside
        if lifecycle:
            # A competing window can split one piece twice in this leg; count its size once.
            potential = list({(r['trade'], r['lot_piece']): r for r in inside}.values())
            first = min(part, key=lambda r: (r['entry'], r['original_entry'], str(r['trade']), r['source'])) if part else None
        total = sum(r['shares']*r['price']*_gain(g) for r in potential)
        remaining = sum(r['shares']*r['price']*r['remaining'] for r in potential)
        pnl = sum(r['h_pnl'] for r in inside)
        size = sum(r['shares'] for r in potential)
        result.append(dict(key=_key(g), code=g['code'], first=_first(g), peak=g['peak'],
            year=str(calendar[_first(g)])[:4], precision=g.get('precision', 'unknown'),
            duration=g['peak']-_first(g), censored=g.get('censored', False),
            reachable=g.get('reachable'), any=bool(part), covered=bool(first and first['early']),
            synced=any(any(e['index']-3 <= r.get('original_entry', r['entry']) <= e['index']+lag for e in
                           g.get('entries', [{'index': _first(g)}])) for r in part),
            offset=first['entry']-_first(g) if first else None,
            first_fill=None if first is None else dict(index=first['entry'], price=first['price']),
            pnl=pnl, potential_total=total, potential_rem=remaining,
            capture_total=pnl/total if total > 0 else None,
            capture_rem=pnl/remaining if remaining > 0 else None,
            avg_entry=sum(r['shares']*r['price'] for r in potential)/size if size else None,
            avg_exit=sum(r['shares']*r['h_exit_price'] for r in potential)/size if size else None,
            lots=len({(r['trade'], r['source']) for r in part}), n_trades=len({r['trade'] for r in part})))
        if lifecycle:
            result[-1]['window_start'] = g['window_start']
            result[-1]['first_fill'] = (dict(index=first['entry'], price=first['price'],
                                           actual_entry=first['original_entry']) if first else None)
    return result


def account_purity(rows, trades, calendar, prices=None, equity=None, ticker_years=()):
    """Pnl by first trade-entry year; capital by calendar year, including carry-in.

    T1 + T2 + T3 + other + post_peak reconciles exactly. Gross is calculated on
    the same FIFO/time-sliced pieces in numerator and denominator.
    """
    daily = capital_days(rows, calendar, prices, equity)
    result = {}
    for year in dict.fromkeys(str(day)[:4] for day in calendar):
        part = [r for r in rows if r['year'] == year]
        ts = [t for t in trades if str(calendar[t['entry']])[:4] == year]
        buckets = {b: dict(pnl=0., gross=0., loss=0.) for b in ('T1', 'T2', 'T3', 'other', 'post_peak')}
        h_by_trade = {}
        for row in part:
            slices = [(row['bucket'], row['h_pnl']), ('post_peak', row['post_pnl'])] if row['bucket'] in ('T1', 'T2') else [(row['bucket'], row['pnl'])]
            for bucket, pnl in slices:
                b = buckets[bucket]
                b['pnl'] += pnl
                b['gross'] += max(0., pnl)
                b['loss'] += min(0., pnl)
            if row['bucket'] == 'T1':
                h_by_trade[row['trade']] = h_by_trade.get(row['trade'], 0.)+row['h_pnl']
        total = sum(t['pnl'] for t in ts)
        if not math.isclose(total, sum(b['pnl'] for b in buckets.values()), abs_tol=1e-9):
            raise ValueError('attributed lots do not reconcile to account trade pnl')
        gross = sum(b['gross'] for b in buckets.values())
        loss = sum(b['loss'] for b in buckets.values())
        top = sorted((t for t in ts if t['closed'] and t['pnl'] > 0), key=lambda t: (-t['pnl'], str(t['id'])))[:10]
        mask = np.array([str(day)[:4] == year for day in calendar])
        sums = {k: float(v[mask].sum()) for k, v in daily.items()}
        closed = [t for t in ts if t['closed']]
        h = buckets['T1']['pnl']
        ticker_pnl = sum(t['pnl'] for t in ts if (t['code'], year) in ticker_years)
        trade_gross = sum(max(t['pnl'], 0.) for t in ts)
        ticker_gross = sum(max(t['pnl'], 0.) for t in ts if (t['code'], year) in ticker_years)
        result[year] = dict(buckets=buckets, total_pnl=total, gross=gross, gross_loss=loss,
            H=h, O=total-h, tuition=total-h, tuition_loss=sum(b['loss'] for k, b in buckets.items() if k != 'T1'),
            early_pnl=sum(r['h_pnl'] for r in part if r['bucket'] == 'T1' and r['early']),
            purity_gross=buckets['T1']['gross']/gross if gross > 0 else None,
            purity_net=h/total if total > 0 else None,
            profit_factor=gross/(-loss) if loss < 0 else None,
            cap_share=sums['his']/sums['gross'] if sums['gross'] > 0 else None,
            cap_equity=sums['his_equity']/int(mask.sum()) if equity is not None else None,
            cap_conf=sums['his_confirmed']/sums['confirmed'] if sums['confirmed'] > 0 else None,
            capital_days=sums, sessions=int(mask.sum()), n_trades=len(ts), closed=len(closed),
            win=sum(t['pnl'] > 0 for t in closed)/len(closed) if closed else None,
            n_tickers=len({t['code'] for t in ts}), ticker_year_pnl=ticker_pnl,
            ticker_year_gross=ticker_gross,
            ticker_year_purity_gross=ticker_gross/trade_gross if trade_gross > 0 else None,
            top10_his_leg=sum(h_by_trade.get(t['id'], 0.) > 0 for t in top),
            top10=[dict(id=t['id'], code=t['code'], pnl=t['pnl'], H=h_by_trade.get(t['id'], 0.)) for t in top])
    return result, daily


def summary_account(trades, legs_, prices, calendar, equity=None, other_legs=(), ticker_years=(), *, lifecycle=False):
    """Account evaluation entry point. No strategy module calls this function.

    Both censor views retain identical assignment; excluding censored labels
    never reassigns their lots to a different leg.
    lifecycle=True opts into trough-to-peak time slicing; default Y1 is unchanged.
    """
    if lifecycle:
        legs_ = lifecycle_windows(legs_, prices)
        rows = _attribute_lifecycle_lots(trades, legs_, prices, calendar, ticker_years)
    else:
        rows = attribute_lots(trades, legs_, prices, calendar, other_legs, ticker_years)
    per_leg = account_coverage(rows, legs_, calendar, lifecycle=lifecycle)
    years, daily = account_purity(rows, trades, calendar, prices, equity, ticker_years)
    censored = {_key(g) for g in legs_ if g.get('censored')}
    uncensored_rows = [dict(r, bucket='other', h_end=None) if r['leg'] in censored else r for r in rows]
    uncensored, _ = account_purity(uncensored_rows, trades, calendar, prices, equity, ticker_years)
    for year, result in years.items():
        subsets = {
            'including_censored': [g for g in per_leg if g['year'] == year],
            'excluding_censored': [g for g in per_leg if g['year'] == year and not g['censored']],
            'event': [g for g in per_leg if g['year'] == year and g['duration'] < 5],
            'swing': [g for g in per_leg if g['year'] == year and g['duration'] >= 5],
            **{p: [g for g in per_leg if g['year'] == year and g['precision'] == p] for p in ('exact', 'chart', 'window')}}
        result['coverage'] = {}
        for name, part in subsets.items():
            denominator = sum(g['potential_total'] for g in part)
            rem = sum(g['potential_rem'] for g in part)
            pnl = sum(g['pnl'] for g in part)
            offsets = [g['offset'] for g in part if g['covered']]
            result['coverage'][name] = dict(n=len(part), any=sum(g['any'] for g in part),
                covered=sum(g['covered'] for g in part), synced=sum(g['synced'] for g in part),
                unreachable=sum(g['reachable'] is False for g in part),
                censored=sum(g['censored'] for g in part),
                censored_uncovered=sum(g['censored'] and not g['covered'] for g in part),
                pnl=pnl, potential_total=denominator, potential_rem=rem,
                capture_total=pnl/denominator if denominator > 0 else None,
                capture_rem=pnl/rem if rem > 0 else None,
                offset=float(np.median(offsets)) if offsets else None)
        result['capture_total'] = result['coverage']['including_censored']['capture_total']
        result['capture_rem'] = result['coverage']['including_censored']['capture_rem']
        result['excluding_censored'] = dict(uncensored[year],
            coverage=result['coverage']['excluding_censored'],
            capture_total=result['coverage']['excluding_censored']['capture_total'],
            capture_rem=result['coverage']['excluding_censored']['capture_rem'])
    return dict(years=years, legs=per_leg, lots=rows, daily=daily)


def selection_diagnostics(picks, legs_, prices, calendar, pool, years=('2024', '2025'), k=3, observe=5,
                          training=True):
    """Evaluation-only trigger labels and a training-only lexicographic objective.

    `picks` and `pool` map integer nights to ordered codes and eligible codes.
    Years group legs by their first anchor, including signal nights across a
    year boundary. Training excludes labels whose peak exceeds the final year
    and cannot read a subsequent year's picks or trigger closes.
    Memory is O(label windows + picks); no market-wide future-return matrix.
    """
    years = set(map(str, years))
    cutoff = max(years)+'-12-31'
    selected = {t: list(cs)[:k] for t, cs in picks.items() if not training or str(calendar[t]) <= cutoff}
    targets = [g for g in legs_ if str(calendar[_first(g)])[:4] in years]
    unavailable = [g for g in targets if training and str(calendar[g['peak']]) > cutoff]
    gs = [g for g in targets if not training or str(calendar[g['peak']]) <= cutoff]
    qualified, trigger, gains = {}, {}, {}
    for g in gs:
        code, p = g['code'], prices[g['code']]
        for t in range(max(0, _first(g)-4), g['peak']-1):
            if training and str(calendar[t]) > cutoff:
                continue
            fill = float(p['o'][t+1])
            if not math.isfinite(fill) or fill <= 0 or g['top']/fill-1 < .5*_gain(g)-1e-12:
                continue
            qualified.setdefault(_key(g), set()).add(t)
            for u in range(t+1, min(t+observe+1, g['peak'])):
                if training and str(calendar[u]) > cutoff:
                    break
                close, high = float(p['c'][u]), float(p['h'][u-1])
                if (math.isfinite(close) and math.isfinite(high) and close > high and
                        g['top']/close-1 >= .5*_gain(g)-1e-12):
                    trigger.setdefault(_key(g), {})[t] = u
                    gains[(_key(g), t)] = (g['top']/close-1)/_gain(g)
                    break
    signal_hits, trigger_hits, early, opportunity = [], [], [], {}
    for g in gs:
        key, code = _key(g), g['code']
        signal_hits.append(any(code in selected.get(t, ()) for t in qualified.get(key, ())))
        hit = [t for t in trigger.get(key, {}) if code in selected.get(t, ())]
        trigger_hits.append(bool(hit))
        if hit:
            first = min(hit, key=lambda t: (trigger[key][t], t))
            early.append(gains[(key, first)])
        for t in trigger.get(key, {}):
            if code in pool.get(t, ()):
                opportunity.setdefault(t, set()).add(code)
    n_picks = sum(len(selected.get(t, ())) for t in opportunity)
    hits = sum(len(set(selected.get(t, ())) & codes) for t, codes in opportunity.items())
    base_hits = sum(len(selected.get(t, ()))*len(codes)/len(pool[t]) for t, codes in opportunity.items())
    n = len(gs)
    p_opp = hits/n_picks if n_picks else None
    e = float(np.median(early)) if early else None
    return dict(n=n, signal=sum(signal_hits), trigger=sum(trigger_hits),
        C_signal=sum(signal_hits)/n if n else None, C_trig=sum(trigger_hits)/n if n else None,
        P_opp=p_opp, E=e, opportunity_nights=len(opportunity), opportunity_picks=n_picks,
        hits=hits, picks=sum(len(cs) for t, cs in selected.items() if str(calendar[t])[:4] in years),
        unavailable_training_labels=len(unavailable), training=training,
        pool_precision=base_hits/n_picks if n_picks else None,
        lift=hits/base_hits if base_hits else None,
        objective=(sum(trigger_hits)/n if n else 0., p_opp or 0., e or 0.),
        per_leg=[dict(key=_key(g), signal=a, trigger=b) for g, a, b in zip(gs, signal_hits, trigger_hits)])
