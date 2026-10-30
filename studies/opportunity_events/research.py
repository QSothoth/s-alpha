"""One-shot OpenD discovery and the fixed EP0 descriptive pilot."""

import argparse
import csv
from datetime import datetime, time, timezone
import hashlib
import json
import math
from pathlib import Path
import random
import statistics
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[2]
SYMBOLS = ('AAPL', 'AMD', 'AMZN', 'AVGO', 'GOOGL', 'INTC', 'META', 'MSFT', 'MU', 'NVDA', 'TSLA')
START, END = '2020-02-03', '2023-07-31'


def number(value):
    try:
        value = float(value)
        return value if math.isfinite(value) else None
    except (ValueError, TypeError):
        return None


def positive(value):
    value = number(value)
    return value if value is not None and value > 0 else None


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(65536), b''):
            h.update(chunk)
    return h.hexdigest()


def quantile(values, p):
    values = sorted(values)
    i = (len(values) - 1) * p
    lo, hi = math.floor(i), math.ceil(i)
    return values[lo] + (values[hi] - values[lo]) * (i - lo)


def cap_group(value):
    value = positive(value)
    if value is None:
        return 'unknown'
    return 'under_2b' if value < 2e9 else '2b_to_10b' if value < 10e9 else '10b_plus'


def premarket_window(state, now):
    et = now.astimezone(ZoneInfo('America/New_York'))
    return (state in ('PRE_MARKET_BEGIN', 'PRE_MARKET_END') and et.weekday() < 5
            and time(4) <= et.time() < time(9, 30))


def candidate(row, snapshot, now):
    """Keep source discrepancies visible; last_price is the regular-session reference."""
    code = row['security']
    price, base = positive(row.get('pre_market_price')), positive(row.get('close_price'))
    change = number(row.get('pre_market_change_ratio'))
    flags = []
    if price is None or base is None or change is None:
        flags.append('invalid_rank_price')
    elif abs(100 * (price / base - 1) - change) > 0.2:
        flags.append('rank_reference_mismatch')
    if not snapshot:
        flags.append('missing_snapshot')
    elif not snapshot.get('equity_valid'):
        flags.append('not_equity_snapshot')
    stamp = snapshot.get('update_time', '')
    try:
        dt = datetime.fromisoformat(stamp).replace(tzinfo=ZoneInfo('America/New_York'))
        if dt.date() != now.astimezone(ZoneInfo('America/New_York')).date():
            flags.append('snapshot_wrong_date')
        elif not 0 <= (now - dt).total_seconds() <= 900:
            flags.append('snapshot_stale_or_future')
    except ValueError:
        flags.append('missing_snapshot_time')
    pre = positive(snapshot.get('pre_price'))
    last = positive(snapshot.get('last_price'))
    if base and last and abs(base / last - 1) > 0.005:
        flags.append('rank_snapshot_reference_mismatch')
    snap_change = number(snapshot.get('pre_change_rate'))
    if pre is not None and last is not None and snap_change is not None:
        if abs(100 * (pre / last - 1) - snap_change) > 0.2:
            flags.append('snapshot_reference_mismatch')
    else:
        flags.append('missing_snapshot_premarket_price')
    bid, ask = positive(snapshot.get('bid_price')), positive(snapshot.get('ask_price'))
    spread = 100 * (ask - bid) / ((ask + bid) / 2) if bid and ask and ask >= bid else None
    if spread is None:
        flags.append('missing_or_crossed_quote')
    elif spread >= 1:
        flags.append('spread_at_least_1pct')
    if price is not None and price < 1:
        flags.append('price_under_1usd')
    if positive(row.get('pre_market_turnover')) is None or positive(row.get('pre_market_volume')) is None:
        flags.append('no_premarket_activity')
    cap = positive(snapshot.get('total_market_val'))
    if cap is None:
        flags.append('missing_market_cap')
    return dict(code=code, name=row.get('name'), pre_price=price, pre_change_pct=change,
                pre_turnover=number(row.get('pre_market_turnover')), pre_volume=number(row.get('pre_market_volume')),
                rank_reference_price=base, snapshot_time=stamp, market_cap=cap, cap_group=cap_group(cap),
                float_shares=positive(snapshot.get('outstanding_shares')), bid=bid, ask=ask, spread_pct=spread,
                quality_flags=flags, evidence_status='UNVALIDATED', direction=None)


def discover(count=10, news_count=0):
    import futu as ft
    q = ft.OpenQuoteContext(host='127.0.0.1', port=11111)
    raw, ranks = {}, []

    def call(name, **kwargs):
        ret, value = getattr(q, name)(**kwargs)
        if ret != ft.RET_OK:
            raise RuntimeError(f'{name}: {value}')
        return value

    try:
        started = datetime.now(timezone.utc)
        state = call('get_global_state')
        if not premarket_window(state.get('market_us'), started):
            raise ValueError('US premarket is not active; refusing an undated or previous-session rank.')
        before = call('get_history_kl_quota')
        for side, direction in (('up', ft.RankSortDir.DESCENDING), ('down', ft.RankSortDir.ASCENDING)):
            total, frame = call('get_us_pre_market_rank', sort_dir=direction, count=count, offset=0)
            rows = json.loads(frame.to_json(orient='records'))
            raw[side] = dict(total=total, rows=rows)
            ranks.extend(r for r in rows if (number(r.get('pre_market_change_ratio')) or 0) *
                         (1 if side == 'up' else -1) > 0)
        unique = {r['security']: r for r in ranks}
        if not unique:
            raise ValueError('Both rank sides contain no directional premarket activity.')
        frame = call('get_market_snapshot', code_list=list(unique))
        snapshots = json.loads(frame.to_json(orient='records'))
        by_code = {r['code']: r for r in snapshots}
        now = datetime.now(timezone.utc)
        items = [candidate(r, by_code.get(c, {}), now) for c, r in unique.items()]
        news = {}
        for item in sorted(items, key=lambda x: x['pre_turnover'] or 0, reverse=True)[:news_count]:
            frame = call('get_search_news', keyword=item['code'], max_count=3)
            news[item['code']] = json.loads(frame.to_json(orient='records'))
        after = call('get_history_kl_quota')
        if before[:2] != after[:2]:
            raise RuntimeError('Historical quota changed during discovery; concurrent usage must be audited.')
        return dict(schema='event-discovery-v1', started_at=started.isoformat(), observed_at=now.isoformat(),
                    market_state=state.get('market_us'), sdk=ft.__version__, server=state.get('server_ver'),
                    quota_before=list(before[:2]), quota_after=list(after[:2]),
                    scope=f'top {count} per side; not a complete threshold universe',
                    snapshot_time_is_not_last_premarket_trade_time=True,
                    code_sha256=digest(Path(__file__)),
                    raw_ranks=raw, raw_snapshots=snapshots, news=news, candidates=items)
    finally:
        q.close()


def daily(root, symbol, fingerprints):
    result = {}
    for source in ('preopen-us-holdout-2016-v1', 'preopen-us-train-v1'):
        path = root / source / 'daily' / f'{symbol}.csv'
        fingerprints[str(path)] = digest(path)
        with path.open() as f:
            for r in csv.DictReader(f):
                day = r['date']
                if not '2019-12-01' <= day <= END:
                    continue
                values = {k: positive(r[k]) for k in ('open', 'high', 'low', 'close')}
                if any(v is None for v in values.values()):
                    raise ValueError(f'Invalid daily price: {symbol} {day}')
                if not values['low'] <= min(values['open'], values['close']) <= max(values['open'], values['close']) <= values['high']:
                    raise ValueError(f'Invalid daily range: {symbol} {day}')
                if day in result and result[day] != values:
                    raise ValueError(f'Conflicting daily sources: {symbol} {day}')
                result[day] = values
    return result


def summarize(events, calendar, draws=2000):
    if not events:
        return dict(n=0, dates=0)
    values = [e['follow'] for e in events]
    by_date = {}
    for e in events:
        by_date.setdefault(e['date'], []).append(e['follow'])
    grid = [(sum(by_date.get(d, ())), len(by_date.get(d, ()))) for d in calendar]
    rng, means = random.Random(20261027), []
    for _ in range(draws):
        total, n, added = 0.0, 0, 0
        while added < len(grid):
            start = rng.randrange(len(grid))
            for j in range(min(5, len(grid) - added)):
                s, size = grid[(start + j) % len(grid)]
                total += s
                n += size
            added += min(5, len(grid) - added)
        if n:
            means.append(total / n)
    ci = [quantile(means, p) for p in (0.025, 0.975)] if means else None
    result = dict(n=len(events), dates=len(by_date), symbols=len({e['symbol'] for e in events}))
    for name, sign in (('follow', 1), ('fade', -1)):
        v = [sign * x for x in values]
        mean = statistics.mean(v)
        result[name] = dict(mean=mean, median=statistics.median(v), win_rate=sum(x > 0 for x in v) / len(v),
                            q10=quantile(v, 0.1), q90=quantile(v, 0.9),
                            mean_ci95=ci if sign == 1 else [-ci[1], -ci[0]] if ci else None,
                            excess_spy=statistics.mean(sign * e['excess_spy'] for e in events),
                            after_20bp=mean - 0.002, after_50bp=mean - 0.005)
    return result


def price_audit(root, symbol, bars, fingerprints):
    path = root / 'preopen-us-k5-select-v1' / 'k5' / f'{symbol}.csv'
    fingerprints[str(path)] = digest(path)
    checked, maximum, differences = 0, 0.0, []
    with path.open() as f:
        for r in csv.DictReader(f):
            day, clock = r['time_key'][:10], r['time_key'][11:19]
            if not START <= day <= END or day not in bars or clock not in ('09:35:00', '16:00:00'):
                continue
            field = 'open' if clock == '09:35:00' else 'close'
            delta = abs(float(r[field]) / bars[day][field] - 1)
            checked += 1
            maximum = max(maximum, delta)
            if delta > 1e-5:
                differences.append(dict(date=day, field=field, relative_difference=delta))
            if delta > 0.001:
                raise ValueError(f'Daily/K5 scale mismatch: {symbol} {day}')
    if not checked:
        raise ValueError(f'No overlapping daily/K5 prices: {symbol}')
    return dict(checked=checked, max_relative_difference=maximum, differences=differences)


def pilot(root):
    fingerprints, events, coverage, audits = {}, [], {}, {}
    spy = daily(root, 'SPY', fingerprints)
    calendar = sorted(d for d in spy if START <= d <= END)
    for symbol in SYMBOLS:
        bars = daily(root, symbol, fingerprints)
        audits[symbol] = price_audit(root, symbol, bars, fingerprints)
        days = sorted(bars)
        previous = {b: a for a, b in zip(days, days[1:])}
        ext = root / 'preopen-us-ext30-holdout-v1' / 'ext30' / f'{symbol}.csv'
        fingerprints[str(ext)] = digest(ext)
        seen, valid, missing, inactive = set(), 0, 0, 0
        with ext.open() as f:
            for r in csv.DictReader(f):
                stamp = r['time_key']
                day = stamp[:10]
                if not START <= day <= END or stamp[11:19] != '09:00:00':
                    continue
                if day in seen:
                    raise ValueError(f'Duplicate premarket observation: {symbol} {day}')
                seen.add(day)
                if day not in previous or day not in spy:
                    missing += 1
                    continue
                price, volume = positive(r['close']), positive(r['volume'])
                if price is None or volume is None:
                    inactive += 1
                    continue
                valid += 1
                gap = price / bars[previous[day]]['close'] - 1
                if abs(gap) < 0.05:
                    continue
                sign = 1 if gap > 0 else -1
                ret = bars[day]['close'] / bars[day]['open'] - 1
                benchmark = spy[day]['close'] / spy[day]['open'] - 1
                events.append(dict(symbol=symbol, date=day, gap=gap, follow=sign * ret,
                                   excess_spy=sign * (ret - benchmark)))
        coverage[symbol] = dict(observed=len(seen), valid=valid, missing_daily=missing, inactive=inactive,
                                calendar_missing=len(set(calendar) - seen))
    return dict(schema='EP0', status='DESCRIPTIVE_ALREADY_USED_DATES', start=START, end=END,
                threshold=0.05, signal_time='09:00 bar close America/New_York', coverage=coverage,
                daily_k5_audit=audits,
                input_sha256=fingerprints, code_sha256=digest(Path(__file__)),
                plan_sha256=digest(Path(__file__).parent / 'notes/EP0_PLAN_CN.md'),
                limitations=['fixed surviving stocks', 'no historical cap or news grouping',
                             'opening-auction proxy', 'shorts assume borrow', 'cost scenarios only'],
                groups={name: summarize(selected, calendar) for name, selected in (
                    ('all', events), ('up', [e for e in events if e['gap'] > 0]),
                    ('down', [e for e in events if e['gap'] < 0]))}, events=events)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('command', choices=('discover', 'pilot'))
    p.add_argument('--count', type=int, default=10)
    p.add_argument('--news', type=int, default=0)
    p.add_argument('--data', type=Path, default=ROOT / 'data')
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    if not 1 <= args.count <= 200 or not 0 <= args.news <= 3:
        p.error('--count must be 1..200; --news must be 0..3')
    if args.output.exists():
        p.error('--output must be a new path')
    result = discover(args.count, args.news) if args.command == 'discover' else pilot(args.data)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2, allow_nan=False)
        f.write('\n')
    if args.command == 'pilot':
        print(json.dumps(result['groups'], ensure_ascii=False, indent=2))
    else:
        print(json.dumps(dict(output=str(args.output), candidates=len(result['candidates']),
                              clean=sum(not x['quality_flags'] for x in result['candidates']),
                              quota_unchanged=result['quota_before'] == result['quota_after']), ensure_ascii=False))


if __name__ == '__main__':
    main()
