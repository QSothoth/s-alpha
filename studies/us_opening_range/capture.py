"""One-shot same-day 0DTE capture using current bars only, without history quota."""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timedelta
import json
import math
from pathlib import Path
import time

from custody.dataset import check, parse_option_code, write_bars, write_checksums
from custody.marketdata import normalize_daily_rows
from custody.models import ET, symbol as normalize_symbol
from custody.opend import OpenDMarket, OpenDTradingCalendar, _records
from .scan import atm_pair, completed_bars


def _json_safe(value):
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _write_json(path, value):
    path.write_text(json.dumps(_json_safe(value), ensure_ascii=False, indent=2,
                               default=str, allow_nan=False) + '\n', encoding='utf-8')


def capture(symbols, out, market, day=None, now_fn=lambda: datetime.now(ET),
            pause=time.sleep, clock=time.monotonic):
    """Capture a finite symbol list; the caller owns and closes this private connection."""
    import futu as ft

    now = now_fn().astimezone(ET)
    today = now.date().isoformat()
    day = day or today
    if day != today:
        raise ValueError('capture date must be the current US/Eastern date')
    root = Path(out)
    if root.exists():
        raise FileExistsError('refusing to overwrite dataset: ' + str(root))
    session = OpenDTradingCalendar(market).session(day)
    if now < session.closes + timedelta(minutes=20):
        raise ValueError('capture requires the session close plus 20 minutes')
    expected = int((session.closes - session.opens).total_seconds() // 60)
    if expected not in (210, 390):
        raise ValueError('unexpected US equity session length')
    ret, subscription = market.context.query_subscription(is_all_conn=False)
    if ret != 0:
        raise RuntimeError('subscription quota lookup failed: ' + str(subscription))
    if subscription.get('own_used', 0) or subscription.get('own_option_used_quota', 0):
        raise ValueError('capture requires a private connection with no existing subscriptions')
    root.mkdir(parents=True, exist_ok=False)
    manifest = {'dataset': root.name, 'role': 'validation/custody', 'schema': 'custody-0dte/1',
                'source': 'OpenD get_cur_kline; no request_history_kline and no fallback',
                'selection_policy': 'both_sides_atm_at_open', 'max_dte': 0,
                'created_at': now.isoformat(), 'requested_symbols': list(symbols),
                'sessions': [], 'case_count': 0, 'skipped': [], 'errors': [],
                'history_requests': 0, 'chain_metadata': 'chain/<SYMBOL>.json',
                'nonfinite_metadata': 'Non-finite provider metadata is stored as null.',
                'initial_subscription_quota': {key: subscription.get(key) for key in
                    ('total_used', 'remain', 'option_used_quota', 'option_remain_quota')}}
    cases, subscribed = [], defaultdict(set)
    last_subscription = None

    def subscribe(codes, subtypes):
        nonlocal last_subscription
        ret, result = market.context.subscribe(codes, subtypes, subscribe_push=False,
                                               session=ft.Session.RTH)
        if ret != 0:
            raise RuntimeError('current-bar subscription failed: ' + str(result))
        subscribed[tuple(subtypes)].update(codes)
        last_subscription = clock()

    def current(code, ktype, count=1000):
        ret, rows = market.context.get_cur_kline(code, count, ktype=ktype, autype=ft.AuType.NONE)
        if ret != 0:
            raise RuntimeError('current bars unavailable for %s: %s' % (code, rows))
        return _records(rows)

    try:
        for index, symbol in enumerate(symbols):
            if index:
                pause(3.1)
            try:
                subscribe([symbol], [ft.SubType.K_1M, ft.SubType.K_DAY])
                bars = completed_bars(current(symbol, ft.KLType.K_1M), symbol, session, session.closes)
                if len(bars) != expected or any(
                        bar.close_time != session.opens + timedelta(minutes=minute)
                        or min(bar.open, bar.high, bar.low, bar.close) <= 0
                        for minute, bar in enumerate(bars, 1)):
                    raise ValueError('incomplete underlying 1m session (%d/%d)' % (len(bars), expected))
                chain = market.option_chain(symbol, day)
                pair = atm_pair(chain, symbol, day, bars[0].open)
                (root / 'chain').mkdir(exist_ok=True)
                metadata = {'symbol': symbol, 'trade_date': day, 'observed_at': now_fn().isoformat(),
                            'opening_reference': bars[0].open, 'chain': chain,
                            'selected_pair': pair, 'selected_snapshots': {}}
                _write_json(root / 'chain' / (symbol + '.json'), metadata)
                if pair is None:
                    manifest['skipped'].append({'symbol': symbol, 'reason': 'no_standard_same_day_pair'})
                    continue
                snapshots = market.snapshot(list(pair.values()))
                for right, code in pair.items():
                    owner, expiry, parsed_right, strike = parse_option_code(code)
                    snapshot = snapshots.get(code, {})
                    rows = [row for row in chain if row.get('code') == code]
                    if (owner != symbol.removeprefix('US.') or expiry != day or parsed_right != right
                            or len(rows) != 1 or str(rows[0].get('strike_time', ''))[:10] != day
                            or rows[0].get('option_type') != right
                            or float(rows[0].get('strike_price', 0)) != strike
                            or float(snapshot.get('option_contract_size', 0)) != 100):
                        raise ValueError('invalid expiry, strike or non-100-share contract: ' + code)
                metadata['selected_snapshots'] = snapshots
                _write_json(root / 'chain' / (symbol + '.json'), metadata)
                prior = [row for row in normalize_daily_rows(current(symbol, ft.KLType.K_DAY, 20))
                         if row['date'] < day]
                if not prior:
                    raise ValueError('previous completed daily close unavailable')
                subscribe(list(pair.values()), [ft.SubType.K_1M])
                options = {}
                for right, code in pair.items():
                    option = completed_bars(current(code, ft.KLType.K_1M), code, session, session.closes)
                    if (not any(bar.volume > 0 and bar.close > 0 for bar in option)
                            or any(min(bar.open, bar.high, bar.low, bar.close) < 0 for bar in option)):
                        raise ValueError('no valid traded option bars: ' + code)
                    options[right] = option
                write_bars(root / 'underlying' / (symbol + '.csv'), bars)
                for right, code in pair.items():
                    write_bars(root / 'option' / (code + '.csv'), options[right])
                    cases.append({'symbol': symbol, 'contract': code, 'trade_date': day, 'expiry': day,
                                  'right': right, 'direction': 'LONG' if right == 'CALL' else 'SHORT',
                                  'strike': parse_option_code(code)[3], 'reference_open': bars[0].open,
                                  'prev_close': prior[-1]['close'], 'session_close': session.closes.isoformat(),
                                  'selection': 'both_sides_atm_at_open',
                                  'call_contract': pair['CALL'], 'put_contract': pair['PUT']})
            except (RuntimeError, ValueError, KeyError, TypeError) as exc:
                manifest['errors'].append({'symbol': symbol, 'reason': str(exc)})
    finally:
        if last_subscription is not None:
            # OpenD permits unsubscribing after one minute; only release our own codes/types.
            remaining = max(0.0, 61.0 - (clock() - last_subscription))
            while remaining > 0:
                seconds = min(30.0, remaining)
                pause(seconds)
                remaining -= seconds
            for subtypes, codes in subscribed.items():
                try:
                    ret, result = market.context.unsubscribe(sorted(codes), list(subtypes))
                    if ret != 0:
                        raise RuntimeError(str(result))
                except Exception as exc:
                    manifest['errors'].append({'stage': 'unsubscribe', 'reason': str(exc)})
        cases.sort(key=lambda case: (case['symbol'], case['contract']))
        manifest.update(case_count=len(cases), sessions=[day] if cases else [],
                        completed_at=now_fn().isoformat())
        _write_json(root / 'cases.json', {'cases': cases})
        _write_json(root / 'manifest.json', manifest)
        write_checksums(root)
    checked = check(root)
    return {'out': str(root), 'role': manifest['role'], 'history_requests': 0,
            'check': checked, 'skipped': manifest['skipped'], 'errors': manifest['errors'],
            'ok': checked['ok'] and not manifest['errors']}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--symbols', required=True, help='comma-separated US stocks/ETFs; maximum 30')
    parser.add_argument('--out', required=True, type=Path, help='new unpublished working directory')
    parser.add_argument('--date', default=None, help='current US/Eastern date only')
    parser.add_argument('--host', default=None)
    parser.add_argument('--port', type=int, default=None)
    args = parser.parse_args(argv)
    try:
        symbols = list(dict.fromkeys('US.' + normalize_symbol(value.strip())
                                    for value in args.symbols.split(',')))
        if not 1 <= len(symbols) <= 30:
            raise ValueError('provide between 1 and 30 symbols')
        if args.out.exists():
            raise FileExistsError('refusing to overwrite dataset: ' + str(args.out))
        with OpenDMarket(host=args.host, port=args.port) as market:
            result = capture(symbols, args.out, market, args.date)
    except (RuntimeError, ValueError, OSError) as exc:
        parser.exit(1, str(exc) + '\n')
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    return 0 if result['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
