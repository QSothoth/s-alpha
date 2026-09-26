"""One-shot, read-only OpenD scan for the preregistered opening-range study."""
from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime, timedelta
import json
import math
import time

from custody.dataset import parse_option_code
from custody.marketdata import Bar
from custody.models import ET, symbol as normalize_symbol
from custody.opend import OpenDMarket, OpenDTradingCalendar, _et, _records
from .signals import CANDIDATES, exit_signal, find_signal


def completed_bars(rows, code, session, boundary):
    """Preserve provider order/duplicates so the signal validator can reject them."""
    bars = []
    previous = None
    for row in rows:
        stamp = _et(row.get('time_key'))
        if stamp is None:
            raise ValueError('invalid OpenD bar timestamp')
        if not session.opens < stamp <= min(boundary, session.closes):
            continue
        if row.get('code') != code:
            raise ValueError('unexpected symbol in OpenD bars')
        if previous is not None and stamp <= previous:
            raise ValueError('duplicate or unordered OpenD bars')
        previous = stamp
        bars.append(Bar(code, stamp, *(float(row[key]) for key in ('open', 'high', 'low', 'close', 'volume'))))
    return bars


def atm_pair(chain, symbol, day, open_price):
    """Fix the nearest listed standard strike before requiring its usable pair."""
    strikes = {}
    for row in chain:
        code = str(row.get('code', ''))
        try:
            owner, expiry, right, strike = parse_option_code(code)
        except ValueError:
            continue
        if ('US.' + owner != symbol or expiry != day or strike <= 0
                or row.get('option_standard_type') != 'STANDARD'):
            continue
        strikes.setdefault(strike, []).append((right, code, row))
    if not strikes:
        return None
    nearest = min(strikes, key=lambda strike: (abs(strike - open_price), strike))
    rows = strikes[nearest]
    if (len(rows) != 2 or {right for right, _, _ in rows} != {'CALL', 'PUT'}
            or any(row.get('suspension') not in (False, 0)
                   or row.get('option_settlement_mode') == 'AM' for _, _, row in rows)):
        return None
    return {right: code for right, code, _ in rows}


def quote_check(row, now):
    """Fail closed on absent, stale, nonstandard or untradeable snapshots."""
    try:
        bid, ask = float(row['bid_price']), float(row['ask_price'])
        bid_size, ask_size = float(row['bid_vol']), float(row['ask_vol'])
        contract_size = float(row['option_contract_size'])
        if not all(math.isfinite(x) for x in (bid, ask, bid_size, ask_size, contract_size)):
            raise ValueError('nonfinite quote')
    except (KeyError, TypeError, ValueError):
        return None, 'missing_quote_fields'
    # Equity/ETF option size is the share multiplier; OpenD's separate
    # option_contract_multiplier is an index-only field and is normally N/A.
    if (not row.get('option_valid') or contract_size != 100
            or row.get('suspension') not in (False, 0)
            or row.get('sec_status') != 'NORMAL'):
        return None, 'invalid_contract'
    if bid <= 0 or ask < bid or min(bid_size, ask_size) <= 0:
        return None, 'invalid_bid_ask'
    stamp = _et(row.get('update_time'))
    if stamp is None or not 0 <= (now - stamp).total_seconds() <= 60:
        return None, 'stale_quote'
    spread = (ask - bid) / ((ask + bid) / 2)
    if spread > 0.10 + 1e-12:
        return None, 'wide_spread'
    return {'bid': bid, 'ask': ask, 'spread_fraction': spread,
            'snapshot_time': stamp.isoformat()}, None


def assess(bars, session, candidate, now):
    """Replay the observed prefix only; old or already-exited signals are historical."""
    if not bars:
        return {'status': 'WAIT', 'reason': 'no_completed_bars'}
    if not 0 <= (now - bars[-1].close_time).total_seconds() <= 120:
        return {'status': 'SKIP', 'reason': 'stale_underlying'}
    signal = find_signal(bars, session, candidate)
    if signal is None:
        reason = 'entry_window_closed' if now.hour >= 11 else 'no_confirmation'
        return {'status': 'WAIT', 'reason': reason}
    result = {'signal': asdict(signal)}
    exited = exit_signal(bars, session, signal)
    if exited:
        return dict(result, status='HISTORICAL', reason='exit_' + exited[1], exit_time=exited[0])
    if not 0 <= (now - signal.time).total_seconds() <= 300:
        return dict(result, status='HISTORICAL', reason='signal_older_than_5m')
    if now >= session.closes - timedelta(minutes=15) or now.hour >= 11:
        return dict(result, status='HISTORICAL', reason='entry_window_closed')
    # The reference signal may be recent while the market has already moved away.
    side = 1 if signal.direction == 'LONG' else -1
    edge = signal.range_high if side == 1 else signal.range_low
    distance = side * (bars[-1].close - edge)
    if not 0 < distance <= (signal.range_high - signal.range_low) / 4:
        return dict(result, status='SKIP', reason='price_left_entry_zone')
    return dict(result, status='SIGNAL', reason='quote_check_required')


def scan(symbols, candidate, market, now_fn=lambda: datetime.now(ET), pause=time.sleep):
    """Finite scan. Uses subscribed current bars, never history-kline requests."""
    import futu as ft

    now = now_fn().astimezone(ET)
    day = now.date().isoformat()
    session = OpenDTradingCalendar(market).session(day)
    if not session.opens < now < session.closes:
        raise ValueError('scan requires the current regular trading session')
    rows = []
    for index, code in enumerate(symbols):
        # Each limited endpoint stays below 10 calls/30 seconds, including errors.
        if index:
            pause(3.1)
        row = {'symbol': code, 'candidate': candidate, 'status': 'SKIP'}
        try:
            ret, data = market.context.get_option_expiration_date(code)
            if ret != 0:
                raise RuntimeError('expiration lookup failed: ' + str(data))
            expiries = {str(r.get('strike_time', ''))[:10] for r in _records(data)}
            if day not in expiries:
                row['reason'] = 'no_0dte_today'
                rows.append(row)
                continue
            # No subscription to option streams and no background receiver.
            ret, msg = market.context.subscribe([code], [ft.SubType.K_1M],
                                                subscribe_push=False, session=ft.Session.RTH)
            if ret != 0:
                raise RuntimeError('subscribe failed: ' + str(msg))
            ret, raw = market.context.get_cur_kline(code, 1000, ktype=ft.KLType.K_1M,
                                                   autype=ft.AuType.NONE)
            if ret != 0:
                raise RuntimeError('current kline failed: ' + str(raw))
            observed = now_fn().astimezone(ET)
            boundary = observed.replace(second=0, microsecond=0)
            bars = completed_bars(_records(raw), code, session, boundary)
            row.update(assess(bars, session, candidate, observed))
            row['observed_at'] = observed
            if row['status'] != 'SIGNAL':
                rows.append(row)
                continue
            pair = atm_pair(market.option_chain(code, day), code, day, bars[0].open)
            if pair is None:
                row.update(status='SKIP', reason='no_standard_atm_pair')
                rows.append(row)
                continue
            right = 'CALL' if row['signal']['direction'] == 'LONG' else 'PUT'
            contract = pair[right]
            quote_row = market.snapshot([contract]).get(contract, {})
            checked_at = now_fn().astimezone(ET)
            quote, reason = quote_check(quote_row, checked_at)
            # Network requests may cross a bar/window boundary; retain honest timing.
            fresh = assess(bars, session, candidate, checked_at)
            row.update(contract=contract, paired_contract=pair['PUT' if right == 'CALL' else 'CALL'],
                       contract_basis='atm_at_open', observed_at=checked_at)
            if fresh['status'] != 'SIGNAL':
                row.update(status=fresh['status'], reason=fresh['reason'])
            elif quote is None:
                row.update(status='SKIP', reason=reason)
            else:
                row.update(status='OBSERVE', reason='research_only', **quote)
        except (RuntimeError, ValueError, KeyError, TypeError) as exc:
            row.update(status='ERROR', reason=str(exc))
        rows.append(row)
    rows.sort(key=lambda r: (r['status'] != 'OBSERVE', r.get('spread_fraction', float('inf')), r['symbol']))
    return {'study': 'OR1', 'status': 'UNVALIDATED', 'candidate': candidate,
            'trade_date': day, 'source': 'OpenD', 'rows': rows,
            'note': 'One-shot observation, no orders. Spread sorting is not an estimated win rate. '
                    'Snapshot update time is not an independent timestamp for each quote side.'}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--symbols', required=True, help='comma-separated US stocks/ETFs; maximum 20')
    parser.add_argument('--candidate', choices=CANDIDATES, required=True)
    parser.add_argument('--host', default=None)
    parser.add_argument('--port', type=int, default=None)
    args = parser.parse_args(argv)
    try:
        symbols = list(dict.fromkeys('US.' + normalize_symbol(x.strip()) for x in args.symbols.split(',')))
    except ValueError as exc:
        parser.error(str(exc))
    if not 1 <= len(symbols) <= 20:
        parser.error('provide between 1 and 20 symbols')
    try:
        with OpenDMarket(host=args.host, port=args.port) as market:
            result = scan(symbols, args.candidate, market)
    except (RuntimeError, ValueError) as exc:
        parser.exit(1, str(exc) + '\n')
    print(json.dumps(result, ensure_ascii=False, indent=2, default=lambda x: x.isoformat(), allow_nan=False))
    return 1 if any(row['status'] == 'ERROR' for row in result['rows']) else 0


if __name__ == '__main__':
    raise SystemExit(main())
