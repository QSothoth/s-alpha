"""Research-only A4 list: the P4 signal failed its P5 cross-sectional retest.

Read-only OpenD; no orders, no history-kline quota.  Three steps for trading day T (Mon/Wed/Fri):

    # any time after T-1's close and before 09:25 ET on T (~8 minutes)
    /opt/futu-opend/venv/bin/python -m studies.us_0dte_picks.daily_list premarket --date T --out data/list-T-pre
    # 10:00-10:25 ET on T (~2 minutes)
    /opt/futu-opend/venv/bin/python -m studies.us_0dte_picks.daily_list confirm --watchlist data/list-T-pre/watchlist.json --out data/list-T
    # after 16:05 ET on T: record the real outcome (5m first touch, contract close) for forward validation
    /opt/futu-opend/venv/bin/python -m studies.us_0dte_picks.daily_list review --list data/list-T/list.json --out data/list-T-review

Rules remain p3.thrust_side and p3.signal('A4_THRUST_FOLLOW'); see reports/P5_RESULTS_CN.md.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, time as dtime, timedelta
import hashlib
import json
from math import isfinite, sqrt
from pathlib import Path
import time
from zoneinfo import ZoneInfo

from . import p3

ET = ZoneInfo('America/New_York')
TOP_STOCKS, BATCH, HOLD = 600, 100, 61.0
MAX_SPREAD, MIN_OPTION_VOLUME = .10, 100
GRID30 = p3.GRID[5::6]
DATA_BASIS = 'RTH_K_30M_QFQ_V1'


class Client:
    """Paced read-only calls; every response is kept for the manifest."""

    def __init__(self, ctx, ft, pause=time.sleep, clock=time.monotonic):
        self.ctx, self.ft, self.pause, self.clock, self.log = ctx, ft, pause, clock, []

    def call(self, name, *args, **kwargs):
        for attempt in range(5):
            self.pause(.7)
            result = getattr(self.ctx, name)(*args, **kwargs)
            self.log.append({'endpoint': name, 'args': [str(a) for a in args][:2], 'ok': result[0] == self.ft.RET_OK})
            if result[0] == self.ft.RET_OK:
                return result
            message = str(result[1])
            if 'freq' in message.lower() or '频率' in message:
                self.pause(10 * (attempt + 1))
                continue
            raise RuntimeError('%s %s: %s' % (name, args[:1], message))
        raise RuntimeError('%s rate limited' % name)

    def subscribed(self, codes, subtype, fetch, **options):
        """Subscribe in batches, fetch, and unsubscribe after OpenD's one-minute minimum."""
        out = {}
        for start in range(0, len(codes), BATCH):
            part = codes[start:start + BATCH]
            self.call('subscribe', part, [subtype], subscribe_push=False, **options)
            began = self.clock()
            try:
                for code in part:
                    try:
                        out[code] = fetch(code)
                    except (RuntimeError, ValueError, KeyError, TypeError) as exc:
                        out[code] = exc
            finally:
                self.pause(max(0.0, HOLD - (self.clock() - began)))
                self.call('unsubscribe', part, [subtype])
        return out


def records(frame):
    return frame.to_dict('records') if hasattr(frame, 'to_dict') else list(frame)


def trading_days(client, day):
    rows = records(client.call('request_trading_days', market='US', start=(day - timedelta(days=60)).isoformat(),
                               end=day.isoformat())[1])
    if any(str(row['time'])[:10] == day.isoformat() and str(row.get('trade_date_type', 'WHOLE')).upper() != 'WHOLE'
           for row in rows):
        raise ValueError('half-day sessions are excluded, as in the backtest')
    return sorted(str(row['time'])[:10] for row in rows)


def stock_universe(client, previous):
    """Top option-volume stocks on T-1 (no ETFs, price >= 3), the P2 / P3 universe rule."""
    ft = client.ft
    etfs = {row['code'] for row in records(client.call('get_stock_basicinfo', ft.Market.US, ft.SecurityType.ETF)[1])}
    codes, page = [], None
    while len(codes) < TOP_STOCKS:
        _, frame, page, _ = client.call('get_option_underlying_rank', ft.OptionMarket.US_SECURITY,
                                        ft.UnderlyingRankSortType.VOLUME, count=200, trading_date=previous, page=page)
        for row in records(frame):
            if row['code'] not in etfs and (row.get('price') or 0) >= 3 and row['code'] not in codes:
                codes.append(row['code'])
        if not page:
            break
    return codes[:TOP_STOCKS]


def complete_sessions(rows, before):
    """Keep only complete, valid 13-bar RTH days; never include today's partial day."""
    sessions = {}
    for row in rows:
        stamp = str(row['time_key'])
        day = stamp[:10]
        if day < before:
            sessions.setdefault(day, []).append((stamp[11:19], *(float(row[k]) for k in ('open', 'high', 'low', 'close', 'volume'))))
    return {day: sorted(bars) for day, bars in sessions.items()
            if tuple(b[0] for b in sorted(bars)) == GRID30
            and all(all(isfinite(v) for v in b[1:]) and 0 < b[3] <= min(b[1], b[4])
                    <= max(b[1], b[4]) <= b[2] and b[5] >= 0 for b in bars)}


def thrust_on(bars, today):
    """(side, T-1 close, 20-day turnover) using p3.thrust_side on the daily history before `today`."""
    days = sorted(bars)
    if len(days) < 25:
        return 0, None, 0.0
    turnover = sum(bars[d][3] * bars[d][4] for d in days[-20:]) / 20
    return p3.thrust_side(bars, days + [today], len(days)), bars[days[-1]][3], turnover


def premarket_record(rows, today, calendar):
    sessions = complete_sessions(rows, today)
    days = sorted(sessions)
    index = calendar.index(today)
    if len(days) < 25:
        raise ValueError('fewer than 25 complete RTH sessions')
    if not index or days[-1] != calendar[index - 1]:
        raise ValueError('T-1 complete RTH session missing')
    prior = days[-14:]
    recent = set(calendar[max(0, index - 20):index])
    if not all(day in recent for day in prior):
        raise ValueError('14-session opening-volume baseline extends beyond 20 market days')
    opening = [sessions[day][0][5] for day in prior]
    base = sum(opening) / 14
    if base <= 0:
        raise ValueError('opening-volume baseline is zero')
    bars = {day: p3.daily_bar(values) for day, values in sessions.items()}
    side, close, turnover = thrust_on(bars, today)
    return {'side': side, 'close_t1': close, 'turnover20': turnover,
            'rvol30_base': base, 'rvol30_days': prior, 'opening_volumes': opening,
            'complete_sessions': len(days), 'daily_window': [days[0], days[-1]]}


def latest_before(rows, field, day):
    rows = [row for row in rows if str(row['time'])[:10] < day and row.get(field) not in (None, '', 'N/A')]
    return float(max(rows, key=lambda row: str(row['time']))[field]) if rows else None


def premarket(client, day):
    ft = client.ft
    if day.weekday() not in (0, 2, 4):
        raise ValueError('single-stock 0DTE lists are for Monday, Wednesday and Friday only')
    calendar = trading_days(client, day)
    if day.isoformat() not in calendar:
        raise ValueError('not a US trading day per OpenD')
    previous = calendar[calendar.index(day.isoformat()) - 1]
    codes = stock_universe(client, previous)
    history = client.subscribed(codes, ft.SubType.K_30M, lambda code: premarket_record(records(
        client.call('get_cur_kline', code, 1000, ft.SubType.K_30M, ft.AuType.QFQ)[1]), day.isoformat(), calendar),
        session=ft.Session.RTH)
    watch, skipped = [], {}
    for code in codes:
        candidate = history.get(code)
        if isinstance(candidate, Exception) or not candidate:
            skipped[code] = str(candidate) if isinstance(candidate, Exception) else 'RTH bars unavailable'
            continue
        side, close, turnover = (candidate[k] for k in ('side', 'close_t1', 'turnover20'))
        if not side:
            continue
        expiries = {str(r['strike_time'])[:10] for r in records(client.call('get_option_expiration_date', code)[1])}
        if day.isoformat() not in expiries:
            skipped[code] = 'no expiry on T'
            continue
        stats = records(client.call('get_option_underlying_his_statistic', code, begin_time=previous, end_time=previous)[1])
        option_volume = latest_before(stats, 'option_volume', day.isoformat())
        vols = records(client.call('get_option_underlying_his_volatility', code,
                                   begin_time=(day - timedelta(days=p3.daily_k.IV_MAX_AGE)).isoformat(), end_time=previous)[1])
        vols = [r for r in vols if str(r['time'])[:10] >= (day - timedelta(days=p3.daily_k.IV_MAX_AGE)).isoformat()
                and r.get('iv') not in (None, '', 'N/A') and isfinite(float(r['iv'])) and float(r['iv']) > 0]
        iv = latest_before(vols, 'iv', day.isoformat())
        reasons = [text for text, bad in (('close < 3', close < 3), ('turnover20 < 5M', turnover < 5e6),
                                          ('T-1 option volume < 1000', option_volume is None or not isfinite(option_volume)
                                           or option_volume < 1000), ('no IV', not iv)) if bad]
        if reasons:
            skipped[code] = '; '.join(reasons)
            continue
        watch.append(dict(candidate, code=code, iv_t1=iv, option_volume_t1=option_volume))
    return {'kind': 'premarket', 'trade_date': day.isoformat(), 'previous': previous, 'universe': len(codes),
            'data_basis': DATA_BASIS, 'research_status': 'P5_FAILED', 'watchlist': watch, 'skipped': skipped}


def opening_record(rows, day, candidate):
    """Today's 10:00 close-stamped 30m bar, divided by the frozen 14-session baseline."""
    opening = [r for r in rows if str(r['time_key']) == day + ' 10:00:00']
    if len(opening) != 1:
        raise ValueError('today needs exactly one opening 30m bar ending at 10:00')
    prior = candidate.get('rvol30_days', [])
    base = float(candidate.get('rvol30_base') or 0)
    if len(prior) != 14 or prior != sorted(set(prior)) or prior[-1] >= day or not isfinite(base) or base <= 0:
        raise ValueError('missing or invalid frozen 14-session baseline; rerun premarket')
    row = opening[0]
    o, high, low, p10, volume = (float(row[k]) for k in ('open', 'high', 'low', 'close', 'volume'))
    if not all(isfinite(v) for v in (o, high, low, p10, volume)) or not 0 < low <= min(o, p10) <= max(o, p10) <= high or volume < 0:
        raise ValueError('invalid opening 30m OHLCV')
    iv, c1 = float(candidate['iv_t1']), float(candidate['close_t1'])
    if not all(isfinite(v) and v > 0 for v in (iv, c1)) or candidate['side'] not in (-1, 1):
        raise ValueError('invalid watchlist IV, prior close or direction; rerun premarket')
    sigma = iv / 100 / sqrt(252)
    return {'thrust': candidate['side'], 'rvol30': volume / base,
            'drive_z': (p10 / o - 1) / sigma, 'above_c1': 1 if p10 > c1 else -1 if p10 < c1 else 0,
            'p10': p10, 'open': o, 'sigma_rem': sigma * sqrt(p3.REMAINING / 390), 'prior_sessions': 14,
            'rvol30_base': base, 'rvol30_days': prior, 'opening_volume': volume}


def atm_quote(client, code, day, price, side):
    ft = client.ft
    chain = [row for row in records(client.call('get_option_chain', code, start=day, end=day)[1])
             if str(row.get('strike_time', ''))[:10] == day and row.get('option_type') == ('CALL' if side > 0 else 'PUT')
             and row.get('option_standard_type', 'STANDARD') == 'STANDARD']
    if not chain:
        return {'status': 'NO_CONTRACT'}
    best = min(chain, key=lambda row: (abs(float(row['strike_price']) - price), float(row['strike_price'])))
    snap = records(client.call('get_market_snapshot', [best['code']])[1])[0]
    bid, ask = float(snap.get('bid_price') or 0), float(snap.get('ask_price') or 0)
    mid = (bid + ask) / 2
    spread = (ask - bid) / mid if mid > 0 and ask >= bid > 0 else None
    volume = float(snap.get('volume') or 0)
    flags = [text for text, bad in (('价差过大', spread is None or spread > MAX_SPREAD),
                                    ('成交过少', volume < MIN_OPTION_VOLUME)) if bad]
    return {'status': 'OK' if not flags else 'CAUTION', 'contract': best['code'], 'strike': float(best['strike_price']),
            'bid': bid, 'ask': ask, 'spread': spread, 'volume': volume, 'flags': flags}


def confirm(client, watchlist, now):
    ft, day = client.ft, watchlist['trade_date']
    now = now.astimezone(ET)
    if now.date().isoformat() != day or not dtime(10, 0) <= now.timetz().replace(tzinfo=None) <= dtime(10, 25):
        raise ValueError('confirm runs on the trade date from 10:00 to 10:25 ET')
    if watchlist.get('data_basis') != DATA_BASIS:
        raise ValueError('watchlist predates the RTH 30m baseline; rerun premarket')
    candidates = {row['code']: row for row in watchlist['watchlist']}
    fetched = client.subscribed(list(candidates), ft.SubType.K_30M, lambda code: records(
        client.call('get_cur_kline', code, 13, ft.SubType.K_30M, ft.AuType.QFQ)[1]), session=ft.Session.RTH)
    signals, rejected = [], {}
    for code, rows in fetched.items():
        try:
            if isinstance(rows, Exception):
                raise rows
            record = opening_record(rows, day, candidates[code])
        except (RuntimeError, ValueError, KeyError, TypeError) as exc:
            rejected[code] = str(exc)
            continue
        hit = p3.signal(record, 'A4_THRUST_FOLLOW')
        if not hit:
            rejected[code] = 'A4 not confirmed at 10:00'
            continue
        side = hit[0]
        record.update(code=code, side=side,
                      target=record['p10'] * (1 + side * p3.TARGET * record['sigma_rem']),
                      stop=record['p10'] * (1 - side * p3.STOP * record['sigma_rem']))
        signals.append(record)
    signals.sort(key=lambda r: (-r['rvol30'], r['code']))
    for record in signals[:p3.TOP]:
        try:
            record['option'] = atm_quote(client, record['code'], day, record['p10'], record['side'])
        except RuntimeError as exc:
            record['option'] = {'status': 'ERROR', 'error': str(exc)}
    return {'kind': 'confirm', 'trade_date': day, 'confirmed_at': now.isoformat(), 'data_basis': DATA_BASIS, 'list': signals[:p3.TOP],
            'research_status': 'P5_FAILED', 'more_signals': [r['code'] for r in signals[p3.TOP:]], 'rejected': rejected}


def review(client, listed, now):
    """After the close: 5m first touch as in P3, and the listed contract's real close vs the 10:00 ask."""
    ft, day = client.ft, listed['trade_date']
    if now.date().isoformat() != day or now.timetz().replace(tzinfo=None) < dtime(16, 5):
        raise ValueError('review runs on the trade date after 16:05 ET')
    picks = {row['code']: row for row in listed['list']}
    fetched = client.subscribed(list(picks), ft.SubType.K_5M, lambda code: records(
        client.call('get_cur_kline', code, 100, ft.SubType.K_5M, ft.AuType.QFQ)[1]), session=ft.Session.RTH)
    out = []
    for code, pick in picks.items():
        row = {'code': code, 'side': pick['side']}
        rows = fetched.get(code)
        bars = sorted((str(r['time_key'])[11:19], float(r['open']), float(r['high']), float(r['low']), float(r['close']), float(r['volume']))
                      for r in ([] if isinstance(rows, Exception) or rows is None else rows) if str(r['time_key'])[:10] == day)
        if tuple(b[0] for b in bars) != p3.GRID:
            row['status'] = 'INCOMPLETE_BARS'
        else:
            result, target, stop, best, index, price = p3.first_touch(bars, pick['p10'], pick['sigma_rem'], pick['side'])
            row.update(status='OK', payoff=result, target_first=target, stop_first=stop, best_sigma_rem=best,
                       exit_time=bars[index][0], close=bars[-1][4])
            option = pick.get('option', {})
            if option.get('contract') and option.get('ask'):
                intrinsic = max(0.0, pick['side'] * (bars[-1][4] - option['strike']))
                row['option'] = {'contract': option['contract'], 'entry_ask': option['ask'], 'settle_intrinsic': intrinsic,
                                 'hold_to_close_return': intrinsic / option['ask'] - 1}
                try:
                    snap = records(client.call('get_market_snapshot', [option['contract']])[1])[0]
                    row['option'].update(day_high=snap.get('high_price'), last=snap.get('last_price'))
                except RuntimeError as exc:
                    row['option']['snapshot_error'] = str(exc)
        out.append(row)
    return {'kind': 'review', 'trade_date': day, 'reviewed_at': now.isoformat(), 'rows': out,
            'note': 'day_high includes trading before 10:00; hold_to_close uses intrinsic at the 16:00 close'}


def render(result):
    lines = ['# %s 末日期权研究观察（A4，P5 未通过）' % result['trade_date'], '',
             'P5 新截面 40 次信号：先到目标 7.5%、先碰止损 72.5%；周五可交易子集 11 次，先到目标 0 次。'
             'A4 未获稳定方向验证，仅保留研究观察。'
             '价格为正股；目标 = +1 个隐含剩余波动，止损 = −0.5 个；不构成下单指令。', '']
    if not result['list']:
        lines.append('今天没有满足 A4 的标的。')
        return '\n'.join(lines)
    lines += ['| 标的 | 方向 | 10:00 价 | 目标价 | 止损价 | 开盘相对量 | 合约 | 买 / 卖 | 价差 | 成交量 | 提示 |',
              '|---|---|---:|---:|---:|---:|---|---|---:|---:|---|']
    for r in result['list']:
        o = r.get('option', {})
        lines.append('| %s | %s | %.2f | %.2f | %.2f | %.1f | %s | %s | %s | %s | %s |' % (
            r['code'], '做多' if r['side'] > 0 else '做空', r['p10'], r['target'], r['stop'], r['rvol30'],
            o.get('contract', o.get('status', '')), '%.2f / %.2f' % (o['bid'], o['ask']) if 'bid' in o else '',
            '%.0f%%' % (100 * o['spread']) if o.get('spread') is not None else '', '%.0f' % o['volume'] if 'volume' in o else '',
            '、'.join(o.get('flags', [])) or ''))
    if result['more_signals']:
        lines += ['', '超出 5 只未列出：' + '、'.join(result['more_signals'])]
    return '\n'.join(lines)


def save(out, result, client):
    out.mkdir(parents=True, exist_ok=False)
    result = dict(result, requests=client.log)
    name = {'premarket': 'watchlist.json', 'confirm': 'list.json', 'review': 'review.json'}[result['kind']]
    (out / name).write_text(json.dumps(result, ensure_ascii=False, indent=1, default=str) + '\n', encoding='utf-8')
    (out / 'CHECKSUMS.sha256').write_text('%s  %s\n' % (hashlib.sha256((out / name).read_bytes()).hexdigest(), name),
                                          encoding='utf-8')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('step', choices=('premarket', 'confirm', 'review'))
    parser.add_argument('--list', type=Path, help='confirm output (review)')
    parser.add_argument('--date', type=date.fromisoformat, help='trade date T (premarket)')
    parser.add_argument('--watchlist', type=Path, help='premarket output (confirm)')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args(argv)
    if args.out.exists():
        parser.error('refusing to overwrite ' + str(args.out))
    import futu as ft
    ctx = ft.OpenQuoteContext(host='127.0.0.1', port=11111)
    client = Client(ctx, ft)
    try:
        if args.step == 'premarket':
            if args.date is None:
                parser.error('premarket needs --date')
            result = premarket(client, args.date)
            print('%s: %d thrust names with 0DTE on the watchlist (universe %d)' % (
                result['trade_date'], len(result['watchlist']), result['universe']))
        elif args.step == 'review':
            if args.list is None:
                parser.error('review needs --list')
            result = review(client, json.loads(args.list.read_text(encoding='utf-8')), datetime.now(ET))
            for row in result['rows']:
                print(json.dumps(row, ensure_ascii=False, default=str))
        else:
            if args.watchlist is None:
                parser.error('confirm needs --watchlist')
            result = confirm(client, json.loads(args.watchlist.read_text(encoding='utf-8')), datetime.now(ET))
            print(render(result))
    finally:
        ctx.close()
    save(args.out, result, client)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
