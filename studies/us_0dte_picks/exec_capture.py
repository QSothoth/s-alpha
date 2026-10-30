"""Same-day capture of option 1m bars across expiries for the smart buy / sell test set (notes/EXEC_TESTSET_CN.md).

User approval 2026-10-26 (option A): after each close, capture both sides of the at-the-open ATM strike for
four expiry buckets per symbol, using subscribed current bars only (no history-kline quota, which is
60 option contracts a week). OpenD allows 60 option subscriptions at a time and unsubscribing only after a
minute, so options go in batches. Selection uses only the expiry list, the chain and the first 1m open -
never same-day outcomes.

    nice -n 19 env PYTHONUTF8=1 /opt/opend-us-options/.venv/bin/python -m studies.us_0dte_picks.exec_capture \\
        --out data/exec-capture-$(date +%F)
"""
from __future__ import annotations

import argparse
import json
import math
import time
from datetime import date, datetime, timedelta
from pathlib import Path

from custody.dataset import check, parse_option_code, write_bars, write_checksums
from custody.freeze import DEFAULT_SYMBOLS
from custody.marketdata import normalize_bar_rows, normalize_daily_rows
from custody.models import ET
from custody.opend import OpenDMarket, OpenDTradingCalendar, _futu, _records

# bucket -> (lowest DTE, highest DTE, target DTE); the listed expiry closest to the target wins, ties to the nearer
BUCKETS = {'0': (0, 0, 0), '1-4': (1, 4, 2), '5-30': (5, 30, 14), '31-75': (31, 75, 45)}
SELECTION = 'both_sides_atm_at_open_per_expiry_bucket'
OPTION_BATCH = 50          # below OpenD's 60 option subscriptions, leaving room for other sessions
CHAIN_PAUSE = 3.1          # get_option_chain is rate limited (about 10 per 30 s)


def choose_expiries(expiries, day):
    """bucket -> expiry date, from the listed expiries only."""
    today = date.fromisoformat(day)
    out = {}
    for bucket, (low, high, target) in BUCKETS.items():
        fits = [(abs((date.fromisoformat(e) - today).days - target), e) for e in expiries
                if low <= (date.fromisoformat(e) - today).days <= high]
        if fits:
            out[bucket] = min(fits)[1]
    return out


def atm_pair(chain, symbol, expiry, reference):
    """CALL and PUT codes on the standard strike nearest ``reference``; None unless both exist."""
    rows = [r for r in chain if str(r.get('strike_time', ''))[:10] == expiry]
    by_strike = {}
    for row in rows:
        try:
            owner, row_expiry, right, strike = parse_option_code(row.get('code', ''))
        except ValueError:
            continue
        if 'US.' + owner == symbol and row_expiry == expiry and row.get('option_type') == right:
            by_strike.setdefault(strike, {})[right] = str(row['code']).upper()
    pairs = [(abs(k - reference), k) for k, v in by_strike.items() if set(v) == {'CALL', 'PUT'}]
    if not pairs:
        return None
    return by_strike[min(pairs)[1]]


def session_bars(rows, code, session):
    bars = normalize_bar_rows(rows, code, interval='1m', boundary=session.closes, source='opend_stream')
    return [b for b in bars if session.opens < b.close_time <= session.closes]


def _json_safe(value):
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    return None if isinstance(value, float) and not math.isfinite(value) else value


def _write_json(path, value):
    path.write_text(json.dumps(_json_safe(value), ensure_ascii=False, indent=2, default=str) + '\n', encoding='utf-8')


def capture(symbols, out, market, now_fn=lambda: datetime.now(ET), pause=time.sleep):
    ft = _futu()
    now = now_fn().astimezone(ET)
    day = now.date().isoformat()
    root = Path(out)
    if root.exists():
        raise FileExistsError('refusing to overwrite: %s' % root)
    session = OpenDTradingCalendar(market).session(day)
    if now < session.closes + timedelta(minutes=20):
        raise ValueError('capture after the close + 20 minutes so every 1m bar is final')
    expected = int((session.closes - session.opens).total_seconds() // 60)
    ret, quota = market.context.query_subscription(is_all_conn=True)
    if ret != 0:
        raise RuntimeError('subscription quota lookup failed: %s' % quota)
    batch = min(OPTION_BATCH, int(quota.get('option_remain_quota', 0)))
    if batch < 2:
        raise ValueError('no option subscription quota left: %s' % quota)
    root.mkdir(parents=True)
    (root / 'chain').mkdir()
    manifest = {'dataset': root.name, 'role': 'validation/custody', 'schema': 'exec-capture/1',
                'source': 'OpenD get_cur_kline after the close; no request_history_kline', 'history_requests': 0,
                'selection_policy': SELECTION, 'buckets': BUCKETS, 'created_at': now.isoformat(),
                'requested_symbols': list(symbols), 'initial_subscription_quota': quota,
                'sessions': [], 'case_count': 0, 'skipped': [], 'errors': []}
    subscribed = []

    def subscribe(codes, subtypes):
        ret, msg = market.context.subscribe(codes, subtypes, subscribe_push=False, session=ft.Session.RTH)
        if ret != 0:
            raise RuntimeError('subscribe failed: %s' % msg)
        subscribed.append((list(codes), list(subtypes), time.monotonic()))

    def release():
        while subscribed:
            codes, subtypes, at = subscribed.pop()
            pause(max(0.0, 61.0 - (time.monotonic() - at)))
            ret, msg = market.context.unsubscribe(codes, subtypes)
            if ret != 0:
                manifest['errors'].append({'stage': 'unsubscribe', 'reason': str(msg)})

    def current(code, ktype, count=1000):
        ret, rows = market.context.get_cur_kline(code, count, ktype=ktype, autype=ft.AuType.NONE)
        if ret != 0:
            raise RuntimeError('current bars unavailable for %s: %s' % (code, rows))
        return _records(rows)

    plan, underlying, prior = [], {}, {}
    try:
        subscribe(list(symbols), [ft.SubType.K_1M, ft.SubType.K_DAY])
        for symbol in symbols:
            try:
                bars = session_bars(current(symbol, ft.KLType.K_1M), symbol, session)
                if len(bars) != expected:
                    raise ValueError('incomplete underlying 1m session (%d/%d)' % (len(bars), expected))
                days = [r for r in normalize_daily_rows(current(symbol, ft.KLType.K_DAY, 20)) if r['date'] < day]
                underlying[symbol], prior[symbol] = bars, (days[-1]['close'] if days else None)
                ret, listed = market.context.get_option_expiration_date(symbol)
                if ret != 0:
                    raise RuntimeError('expiry list failed: %s' % listed)
                expiries = sorted({str(r.get('strike_time'))[:10] for r in _records(listed)})
                chosen = choose_expiries(expiries, day)
                meta = {'symbol': symbol, 'opening_reference': bars[0].open, 'expiries': expiries,
                        'chosen': chosen, 'pairs': {}}
                for bucket, expiry in chosen.items():
                    pause(CHAIN_PAUSE)
                    pair = atm_pair(market.option_chain(symbol, expiry), symbol, expiry, bars[0].open)
                    meta['pairs'][bucket] = pair
                    if pair is None:
                        manifest['skipped'].append({'symbol': symbol, 'bucket': bucket, 'reason': 'no CALL+PUT pair'})
                        continue
                    plan.append((symbol, bucket, expiry, pair))
                for bucket in set(BUCKETS) - set(chosen):
                    manifest['skipped'].append({'symbol': symbol, 'bucket': bucket, 'reason': 'no listed expiry'})
                _write_json(root / 'chain' / (symbol.removeprefix('US.') + '.json'), meta)
            except (RuntimeError, ValueError, KeyError, TypeError) as exc:
                manifest['errors'].append({'symbol': symbol, 'reason': str(exc)})
        release()
        cases = []
        codes = [(symbol, bucket, expiry, right, code) for symbol, bucket, expiry, pair in plan
                 for right, code in sorted(pair.items())]
        for start in range(0, len(codes), batch):
            group = codes[start:start + batch]
            subscribe([c[-1] for c in group], [ft.SubType.K_1M])
            got = {}
            for symbol, bucket, expiry, right, code in group:
                try:
                    bars = session_bars(current(code, ft.KLType.K_1M), code, session)
                    if not any(b.volume > 0 and b.close > 0 for b in bars):
                        raise ValueError('no traded bars')
                    got[code] = bars
                except (RuntimeError, ValueError) as exc:
                    manifest['errors'].append({'contract': code, 'reason': str(exc)})
            release()
            for symbol, bucket, expiry, right, code in group:
                other = [c for c in group if c[0] == symbol and c[1] == bucket and c[3] != right]
                if code not in got or (other and other[0][-1] not in got):
                    continue  # keep only complete CALL + PUT pairs
                write_bars(root / 'option' / (code + '.csv'), got[code])
                strike = parse_option_code(code)[3]
                cases.append({'symbol': symbol, 'contract': code, 'trade_date': day, 'expiry': expiry,
                              'dte': (date.fromisoformat(expiry) - date.fromisoformat(day)).days, 'bucket': bucket,
                              'right': right, 'direction': 'LONG' if right == 'CALL' else 'SHORT', 'strike': strike,
                              'reference_open': underlying[symbol][0].open, 'prev_close': prior[symbol],
                              'session_close': session.closes.isoformat(), 'selection': SELECTION})
        for symbol in {c['symbol'] for c in cases}:
            write_bars(root / 'underlying' / (symbol + '.csv'), underlying[symbol])
    finally:
        release()
        cases = locals().get('cases', [])
        cases.sort(key=lambda c: (c['symbol'], c['expiry'], c['contract']))
        manifest.update(case_count=len(cases), sessions=[day] if cases else [], completed_at=now_fn().isoformat())
        _write_json(root / 'cases.json', {'cases': cases})
        _write_json(root / 'manifest.json', manifest)
        write_checksums(root)
    checked = check(root, require_0dte=False)
    return {'out': str(root), 'cases': len(cases), 'check_ok': checked['ok'], 'skipped': manifest['skipped'],
            'errors': manifest['errors'], 'ok': checked['ok'] and not manifest['errors']}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--out', required=True, type=Path, help='new working directory for today')
    parser.add_argument('--symbols', default=','.join(DEFAULT_SYMBOLS))
    parser.add_argument('--host', default=None)
    parser.add_argument('--port', type=int, default=None)
    args = parser.parse_args(argv)
    symbols = list(dict.fromkeys(s.strip().upper() for s in args.symbols.split(',') if s.strip()))
    with OpenDMarket(host=args.host, port=args.port) as market:
        result = capture(symbols, args.out, market)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
