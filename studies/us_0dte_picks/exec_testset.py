"""Smart buy / smart sell test set (notes/EXEC_TESTSET_CN.md): deterministic cases, baselines and labels.

Any expiry: a 0DTE contract must be filled by 15:45 (custody's flatten), any other by the 16:00 close.
Window lengths are a parameter (``--length``, minutes or ``close``); the default grid is "until the end" and 60 minutes.

    PYTHONUTF8=1 python3 -m studies.us_0dte_picks.exec_testset --dataset <dir> [--dataset <dir>] [--length close --length 60] [--out cases.json]
"""
from __future__ import annotations

import argparse
import json
import statistics
from collections import Counter

from datetime import date

from custody.dataset import Dataset, parse_option_code
from custody.evaluate import PRIMARY_FILL
from custody.strategy import session_minute

STARTS = [0] + list(range(15, 376, 30))   # 09:30, 09:45, 10:15, ..., 15:45 (minutes after the open)
DEFAULT_LENGTHS = ('close', 60)
SIDES = ('BUY', 'SELL')
ZERO_DTE_END, CLOSE_END = 375, 390        # 0DTE must be done by 15:45; other expiries by the close
MIN_WINDOW = 15                           # an 'until the end' window shorter than this is not generated
FORCE_LOOKBACK = 2   # the forced fill uses the last trade within 2 minutes before the end; later is 'end_late'


def dte(data):
    return (date.fromisoformat(parse_option_code(data.case.contract)[1]) - date.fromisoformat(data.case.trade_date)).days


def session_end(data):
    full = int((data.session.closes - data.session.opens).total_seconds() // 60)
    return full - (CLOSE_END - ZERO_DTE_END) if dte(data) == 0 else full


def cases_for(data, lengths=DEFAULT_LENGTHS):
    """Every (side, start, length) of one contract day that fits before its end (15:45 for 0DTE, close otherwise)."""
    end, out = session_end(data), []
    for start in STARTS:
        for length in lengths:
            n = end - start if length == 'close' else int(length)
            if (length == 'close' and n >= MIN_WINDOW) or (length != 'close' and start + n <= end):
                out += [(side, start, n, str(length)) for side in SIDES]
    return out


def baselines(data, side, start, length, fill=PRIMARY_FILL):
    """Arrival, TWAP, end-of-window and hindsight-best prices; None when the window has no trade at all."""
    options = {session_minute(data.session, b.close_time): b for b in data.option}
    price = fill.buy if side == 'BUY' else fill.sell
    window = [(m, options[m]) for m in range(start + fill.delay_minutes, start + length + 1) if m in options]
    if not window:
        return None
    end = start + length
    near = [m for m in range(end - FORCE_LOOKBACK, end + 1) if m in options and m > start]
    after = [m for m in sorted(options) if m > end]
    forced_minute = near[-1] if near else (after[0] if after else None)
    prices = [price(b) for _, b in window]
    best = min(prices) if side == 'BUY' else max(prices)
    worst = max(prices) if side == 'BUY' else min(prices)
    return {'arrival': prices[0], 'arrival_minute': window[0][0], 'twap': statistics.mean(prices),
            'end': price(options[forced_minute]) if forced_minute is not None else None,
            'end_late': forced_minute is not None and forced_minute > end,
            'best': best, 'worst': worst}


def labels(data, start, length):
    """Ex-post strata for reports only."""
    s = data.session
    under = {session_minute(s, b.close_time): b for b in data.underlying}
    options = [b for b in data.option if start < session_minute(s, b.close_time) <= start + length]
    spot = under[max(start, 1)].close
    strike, sign = data.case.strike, 1 if data.case.direction == 'LONG' else -1
    moneyness = sign * (spot - strike) / spot
    premium = options[0].close if options else None
    move = (options[-1].close / options[0].close - 1) if len(options) > 1 and options[0].close else 0.0
    traded = len(options) / length
    days = dte(data)
    return {'dte': days, 'dte_bucket': '0' if days == 0 else '1-4' if days <= 4 else '5-30' if days <= 30 else '>30',
            'selection': data.case.selection or 'unspecified',
            'liquidity': 'thin' if traded < .5 else 'normal',
            'session_part': 'open' if start < 75 else 'late' if start >= 285 else 'midday',
            'moneyness': 'itm' if moneyness > .002 else 'otm' if moneyness < -.002 else 'atm',
            'premium': None if premium is None else '<0.5' if premium < .5 else '>2' if premium > 2 else '0.5-2',
            'option_path': 'up' if move > .1 else 'down' if move < -.1 else 'flat'}


def build(dirs, lengths=DEFAULT_LENGTHS):
    rows, missing = [], 0
    for root in dirs:
        dataset = Dataset(root, require_0dte=False)
        for case in dataset.cases:
            data = dataset.load(case)
            for side, start, length, kind in cases_for(data, lengths):
                base = baselines(data, side, start, length)
                if base is None:
                    missing += 1
                    continue
                rows.append({'dataset': dataset.name, 'contract': case.contract, 'trade_date': case.trade_date,
                             'right': 'CALL' if case.direction == 'LONG' else 'PUT', 'side': side, 'start': start,
                             'length': length, 'window': kind, **base, **labels(data, start, length)})
    return rows, missing


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--dataset', action='append', required=True)
    parser.add_argument('--length', action='append', help="window length in minutes, or 'close' (repeatable)")
    parser.add_argument('--out')
    args = parser.parse_args(argv)
    lengths = tuple(args.length) if args.length else DEFAULT_LENGTHS
    rows, missing = build(args.dataset, lengths)
    summary = {'cases': len(rows), 'skipped_no_trade_in_window': missing,
               'contract_days': len({(r['contract'], r['trade_date']) for r in rows}),
               'sessions': len({r['trade_date'] for r in rows}),
               'by_side': Counter(r['side'] for r in rows), 'by_window': Counter(r['window'] for r in rows),
               'by_dte_bucket': Counter(r['dte_bucket'] for r in rows), 'by_selection': Counter(r['selection'] for r in rows),
               'by_session_part': Counter(r['session_part'] for r in rows),
               'by_moneyness': Counter(r['moneyness'] for r in rows), 'by_premium': Counter(r['premium'] for r in rows),
               'by_option_path': Counter(r['option_path'] for r in rows),
               'by_liquidity': Counter(r['liquidity'] for r in rows),
               'end_late_share_by_liquidity': {k: sum(r['end_late'] for r in rows if r['liquidity'] == k)
                                               / max(1, sum(r['liquidity'] == k for r in rows)) for k in ('thin', 'normal')},
               'end_late_share': sum(r['end_late'] for r in rows) / len(rows) if rows else None}
    print(json.dumps(summary, ensure_ascii=False, indent=1, default=dict))
    if args.out:
        with open(args.out, 'w') as fh:
            json.dump(rows, fh)


if __name__ == '__main__':
    main()
