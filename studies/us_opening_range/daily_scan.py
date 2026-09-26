"""One-shot DS1 observations with reusable raw OpenD records; never trading advice."""
from __future__ import annotations

import argparse
from datetime import date, datetime, time as dtime, timedelta
import hashlib
from html import escape
import json
import math
from pathlib import Path
import time

from custody.dataset import parse_option_code, write_checksums
from custody.marketdata import Bar, _et, _num
from custody.models import ET, symbol as normalize_symbol
from custody.opend import OpenDMarket, _records
from .daily_signals import CANDIDATES, daily_levels, detect_signals


def _plain(value):
    if hasattr(value, 'to_dict'):
        value = _records(value)
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _write(path, value):
    path.write_text(json.dumps(_plain(value), ensure_ascii=False, indent=2,
                               default=str, allow_nan=False) + '\n', encoding='utf-8')


def _within_window(now):
    return dtime(9) <= now.timetz().replace(tzinfo=None) <= dtime(10, 5)


def _symbols(values):
    codes = list(dict.fromkeys('US.' + normalize_symbol(value.strip()) for value in values))
    if not 1 <= len(codes) <= 10:
        raise ValueError('provide between 1 and 10 US stocks/ETFs')
    return codes


def _bar(row, code, stamp, interval):
    if row.get('code') != code:
        raise ValueError('unexpected symbol in current bars')
    fields = ('open', 'high', 'low', 'close', 'volume')
    if any(isinstance(row.get(k), bool) for k in fields):
        raise ValueError('boolean bar value')
    values = [float(row[k]) for k in fields]
    if min(values[:4]) <= 0:
        raise ValueError('nonpositive bar price')
    return Bar(code, stamp, *values, interval=interval, source='opend_current_qfq')


def daily_history(rows, code, today, calendar):
    """Require the exchange's actual last 20 sessions; never skip a missing day."""
    prior = sorted(day for day in calendar if day < today)[-20:]
    if len(prior) != 20:
        raise ValueError('calendar has fewer than 20 prior trading days')
    found, previous = {}, None
    for row in rows:
        stamp = _et(row.get('time_key'))
        if stamp is None:
            raise ValueError('invalid daily timestamp')
        day = stamp.date().isoformat()
        if day >= today:
            continue  # Today's daily candle is unfinished, even if already returned.
        if previous is not None and day <= previous:
            raise ValueError('duplicate or unordered daily bars')
        previous = day
        if row.get('code') != code:
            raise ValueError('unexpected daily symbol')
        if day in prior:
            close = datetime.combine(date.fromisoformat(day), calendar[day], ET)
            found[day] = _bar(row, code, close, '1d')
    if set(found) != set(prior):
        raise ValueError('missing prior trading day: ' + ','.join(sorted(set(prior) - set(found))))
    return [found[day] for day in prior]


def intraday_prefix(rows, code, observed):
    """Preserve valid prefixes and disclose later corruption, without sorting/deduping."""
    regular, premarket, errors = [], [], []
    previous = None
    for row in rows:
        try:
            stamp = _et(row.get('time_key'))
            if stamp is None:
                raise ValueError('invalid 5m timestamp')
            if stamp.date() != observed.date() or stamp > observed:
                continue
            if stamp.hour < 4:
                continue
            if previous is not None and stamp <= previous:
                raise ValueError('duplicate or unordered 5m bars')
            previous = stamp
            if stamp.second or stamp.microsecond or stamp.minute % 5:
                raise ValueError('5m timestamp off the completed-close grid')
            bar = _bar(row, code, stamp, '5m')
            if stamp.time() <= dtime(9, 30):
                premarket.append(bar)
            elif stamp.time() <= dtime(10, 5):
                regular.append(bar)
        except (ValueError, KeyError, TypeError) as exc:
            errors.append(str(exc))
            break  # Existing earlier signals must survive a later malformed row.
    facts = {'available': bool(premarket), 'as_of': None, 'high': None, 'low': None,
             'last': None, 'bar_count': len(premarket), 'volume_ratio': None,
             'basis': 'observed completed QFQ 5m bars only; not a DS1 gate'}
    if premarket:
        facts.update(as_of=premarket[-1].close_time.isoformat(),
                     high=max(b.high for b in premarket), low=min(b.low for b in premarket),
                     last=premarket[-1].close)
    return regular, facts, errors


def option_eligibility(expiries, chain, code, today):
    """Listed standard same-day contracts, not contract selection or liquidity approval."""
    listed = today in {str(row.get('strike_time', ''))[:10] for row in expiries}
    rights, codes = set(), set()
    for row in chain:
        contract = str(row.get('code', ''))
        try:
            owner, expiry, right, strike = parse_option_code(contract)
            if ('US.' + owner != code or expiry != today or strike <= 0
                    or row.get('stock_owner') != code
                    or str(row.get('strike_time', ''))[:10] != today
                    or row.get('option_type') != right
                    or float(row.get('strike_price', 0)) != strike
                    or row.get('option_standard_type') != 'STANDARD'
                    or row.get('suspension') not in (False, 0)
                    or row.get('option_settlement_mode') == 'AM'):
                continue
        except (ValueError, TypeError):
            continue
        rights.add(right)
        codes.add(contract)
    return {'status': 'LISTED_STANDARD_0DTE' if listed and codes else 'NO_STANDARD_0DTE',
            'expiration_lists_today': listed, 'eligible': bool(listed and codes),
            'standard_contract_count': len(codes), 'available_rights': sorted(rights),
            'liquidity_verified': False, 'contract_selected': None}


def format_observation(result):
    """Render saved facts only; presentation must never create or filter signals."""
    def text(value):
        if value is None or isinstance(value, float) and not math.isfinite(value):
            return '未知'
        raw = format(value, '.6g') if isinstance(value, float) else str(value)
        raw = escape(' '.join(raw.split()), quote=False).replace('\\', '\\\\')
        for char in ('|', '`', '*', '_', '[', ']', '#', '~'):
            raw = raw.replace(char, '\\' + char)
        return raw or '未知'

    yes_no = lambda value: '是' if value is True else '否' if value is False else '未知'
    states = {'SETUP_ONLY': '仅形态／价位观察，未确认方向', 'STALE': '行情过时；保留的提示仅作历史观察',
              'MISSING_DATA': '数据缺失', 'NO_CONFIRMATION': '尚无确认', 'SIGNAL_RECORDED': '已有历史提示记录'}
    rooms = {'room_to_20d_boundary': '到已观测20日边界满足原空间门槛',
             'beyond_observed_20d_range': '已越过20日范围，外侧空间未知'}
    lines = ['# DS1 研究观察 · UNVALIDATED', '',
             '交易日：' + text(result.get('trade_date')) + '；完成时间：' + text(result.get('completed_at')), '',
             '仅供观察，不是买入建议。盘前不猜方向；有当日合约链不代表0DTE成交量或流动性通过。',
             '日线与回放来源等价性：' + text(result.get('source_equivalence')) + '。']
    for error in result.get('errors') or []:
        lines.extend(['', '采集错误：' + text(error)])
    for row in result.get('rows') or []:
        setup, option = row.get('setup') or {}, row.get('option_eligibility') or {}
        bands = row.get('trigger_band') or {}
        state = row.get('observation_status')
        rights = option.get('available_rights')
        rights_text = '未知' if rights is None else '／'.join(text(right) for right in rights) or '无'
        lines.extend(['', '## ' + text(row.get('symbol')) + ' · UNVALIDATED', '', '| 项目 | 已知事实 |', '|---|---|',
            '| 状态 | ' + text(state) + '；' + text(states.get(state)) + ' |',
            '| 观察时间 | ' + text(row.get('observed_at', result.get('created_at'))) + ' |',
            '| 完成5m／预期5m | ' + text(row.get('last_completed_bar_at')) + '／' + text(row.get('expected_completed_bar_at')) + ' |',
            '| 昨高／昨低 | ' + text(setup.get('yesterday_high')) + '／' + text(setup.get('yesterday_low')) + ' |',
            '| 20日高／低 | ' + text(setup.get('range_high20')) + '／' + text(setup.get('range_low20')) + ' |',
            '| 双向观察带（非确认） | 上：' + text(bands.get('LONG')) + '；下：' + text(bands.get('SHORT')) + ' |',
            '| 日K背景 | NR7：' + yes_no(setup.get('nr7')) + '；内包：' + yes_no(setup.get('inside')) + ' |',
            '| 实际0DTE链资格 | ' + text(option.get('status')) + '；合格：' + yes_no(option.get('eligible')) + ' |',
            '| 可用rights／标准合约数 | ' + rights_text + '／' + text(option.get('standard_contract_count')) + ' |'])
        signals = [(name, signal) for name, signal in (row.get('signals') or {}).items() if signal is not None]
        if signals:
            lines.extend(['', '已记录提示（不是当前购买指令；测量线不是自动退出规则；2R测量线不代表期权盈亏比）：', '',
                          '| 候选 | 观察方向 | 提示时间 | 当时参考价 | 结构失效参考 | 2R测量线 | 空间状态 | 状态 |', '|---|---|---|---|---|---|---|---|'])
            for name, signal in signals:
                lines.append('| ' + ' | '.join(text(value) for value in (name, signal.get('direction'), signal.get('time'),
                             signal.get('reference'), signal.get('invalidation'), signal.get('target'),
                             rooms.get(signal.get('room_state')))) + ' | UNVALIDATED |')
        else:
            lines.extend(['', '无已记录确认；盘前仅观察形态和价位，不预测方向。' if state == 'SETUP_ONLY' else '无已记录提示。'])
        for key, error in (row.get('errors') or {}).items():
            lines.extend(['', '数据错误（' + text(key) + '）：' + text(error)])
    if not result.get('rows'):
        lines.extend(['', '暂无标的记录；不能据此推断没有信号或没有0DTE。'])
    return '\n'.join(lines)


def scan(symbols, out, market, now_fn=lambda: datetime.now(ET), pause=time.sleep,
         clock=time.monotonic):
    """Finite capture; caller must own and close a private OpenD quote connection."""
    import futu as ft

    symbols = _symbols(symbols)
    started = now_fn().astimezone(ET)
    if not _within_window(started):
        raise ValueError('DS1 scan requires 09:00 through 10:05 US/Eastern today')
    root = Path(out)
    root.mkdir(parents=True, exist_ok=False)
    (root / 'raw').mkdir()
    today = started.date().isoformat()
    prereg = Path(__file__).with_name('notes') / 'DS1_PREREG.md'
    result = {'study': 'DS1', 'status': 'UNVALIDATED', 'trade_date': today, 'out': str(root),
              'created_at': started.isoformat(), 'rows': [], 'errors': [], 'requests': [],
              'source': 'OpenD get_cur_kline QFQ', 'history_requests': 0,
              'daily_source': 'K_DAY QFQ; research replay aggregates QFQ K_5M',
              'source_equivalence': 'unverified', 'role': 'research/signal-observation',
              'bar_time_convention': 'provider time_key interpreted as bar close, ET; raw retained',
              'nonfinite_metadata': 'Provider nonfinite floats stored as null, not zero.',
              'preregistration_sha256': hashlib.sha256(prereg.read_bytes()).hexdigest(),
              'note': 'Observed setups and historical signals only; no orders, buy advice or exit state machine.'}
    last_call, last_subscription, subscribed = None, None, False
    subtypes = [ft.SubType.K_DAY, ft.SubType.K_5M]

    def request(endpoint, *args, **kwargs):
        nonlocal last_call
        if last_call is not None:
            wait = max(0.0, 3.1 - (clock() - last_call))
            if wait:
                pause(wait)
        requested = now_fn().astimezone(ET)
        path = 'raw/%04d_%s.json' % (len(result['requests']), endpoint)
        record = {'endpoint': endpoint, 'args': args, 'kwargs': kwargs,
                  'requested_at': requested.isoformat()}
        last_call = clock()
        try:
            if endpoint != 'unsubscribe' and (requested.date().isoformat() != today
                                              or not _within_window(requested)):
                raise RuntimeError('observation window ended')
            ret, raw = getattr(market.context, endpoint)(*args, **kwargs)
            record.update(return_code=ret, data=_plain(raw))
            if ret != 0:
                raise RuntimeError(endpoint + ' failed: ' + str(raw))
            return raw
        except Exception as exc:
            record['error'] = str(exc)
            raise
        finally:
            record['received_at'] = now_fn().astimezone(ET).isoformat()
            _write(root / path, record)
            result['requests'].append({'path': path, 'endpoint': endpoint,
                                       'requested_at': record['requested_at'],
                                       'received_at': record['received_at'],
                                       'ok': 'error' not in record})

    try:
        calendar_rows = _records(request('request_trading_days', market='US',
            start=(started.date() - timedelta(days=90)).isoformat(), end=today))
        calendar = {}
        for row in calendar_rows:
            kind = row.get('trade_date_type')
            if kind not in ('WHOLE', 'MORNING'):
                raise ValueError('unknown US trading-session type: ' + str(kind))
            day = date.fromisoformat(str(row['time'])[:10]).isoformat()
            if day in calendar:
                raise ValueError('duplicate calendar day')
            calendar[day] = dtime(16) if kind == 'WHOLE' else dtime(13)
        if today not in calendar:
            raise ValueError('today is not a US trading day per OpenD')
        quota = request('query_subscription', is_all_conn=False)
        result['initial_subscription_quota'] = _plain(quota)
        if ('own_used' not in quota or quota['own_used'] != 0
                or quota.get('own_option_used_quota', 0) != 0):
            raise ValueError('private connection with zero existing subscriptions required')
        requested_session = getattr(ft.Session, 'ALL', ft.Session.RTH)
        def subscribe(session):
            nonlocal subscribed, last_subscription
            try:
                request('subscribe', symbols, subtypes, subscribe_push=False, session=session)
            finally:
                # Even a failed response may follow a partial subscription; the
                # private-connection check makes these exact codes/types ours.
                subscribed, last_subscription = True, clock()

        try:
            subscribe(requested_session)
        except (RuntimeError, TypeError):
            if requested_session == ft.Session.RTH:
                raise
            result['extended_hours_unavailable'] = True
            subscribe(ft.Session.RTH)
            requested_session = ft.Session.RTH
        result['subscription_session'] = requested_session
        for code in symbols:
            row = {'symbol': code, 'status': 'UNVALIDATED', 'setup': None, 'trigger_band': None,
                   'signals': dict.fromkeys(CANDIDATES), 'filter_counts': {}, 'errors': {},
                   'structure_signal_overlap': False, 'premarket': {'available': False,
                   'as_of': None, 'high': None, 'low': None, 'last': None, 'volume_ratio': None},
                   'last_completed_bar_at': None, 'observation_status': 'MISSING_DATA',
                   'option_eligibility': {'status': 'UNKNOWN', 'eligible': None},
                   'option_activity': {'option_volume': None, 'as_of': None, 'available': False,
                                       'scope': 'underlying_all_expiries_not_0dte'}}
            result['rows'].append(row)
            try:
                raw = request('get_cur_kline', code, 40, ktype=ft.KLType.K_DAY, autype=ft.AuType.QFQ)
                history = daily_history(_records(raw), code, today, calendar)
                levels = daily_levels(history, started.date())
                atr = levels['atr']
                row.update(setup=levels, trigger_band={
                    'LONG': [levels['yesterday_high'] + .05 * atr, levels['yesterday_high'] + .25 * atr],
                    'SHORT': [levels['yesterday_low'] - .25 * atr, levels['yesterday_low'] - .05 * atr]})
            except (RuntimeError, ValueError, KeyError, TypeError) as exc:
                row['errors']['daily'] = str(exc)
            try:
                raw = request('get_cur_kline', code, 1000, ktype=ft.KLType.K_5M, autype=ft.AuType.QFQ)
                observed = now_fn().astimezone(ET)
                bars, facts, errors = intraday_prefix(_records(raw), code, observed)
                row.update(premarket=facts, observed_at=observed.isoformat(),
                           last_completed_bar_at=bars[-1].close_time.isoformat() if bars else None)
                if errors:
                    row['errors']['5m_prefix'] = errors
                if row['setup'] is not None:
                    signals, counts = detect_signals(bars, row['setup'])
                    row.update(signals=signals, filter_counts=dict(counts), structure_signal_overlap=
                               bool(signals.get('NR7_BREAK') and signals.get('INSIDE_BREAK')))
                    row['observation_status'] = ('SETUP_ONLY' if observed.time() < dtime(9, 35)
                        else 'SIGNAL_RECORDED' if any(signals.values()) else 'NO_CONFIRMATION')
                if bars:
                    opening = bars[-1].close_time.replace(hour=9, minute=30, second=0, microsecond=0)
                    present = {bar.close_time for bar in bars}
                    missing = [opening + timedelta(minutes=5 * index) for index in
                               range(1, int((bars[-1].close_time - opening).total_seconds()) // 300 + 1)
                               if opening + timedelta(minutes=5 * index) not in present]
                    if missing:
                        row['errors']['5m_grid'] = '已完成5m序列缺根：' + ', '.join(stamp.strftime('%H:%M') for stamp in missing)
                        row['observation_status'] = 'MISSING_DATA'  # Disclosure only: preserve bars and any earlier signals.
            except (RuntimeError, ValueError, KeyError, TypeError) as exc:
                row['errors']['5m'] = str(exc)
            try:
                expiries = _records(request('get_option_expiration_date', code))
                chain = []
                if today in {str(r.get('strike_time', ''))[:10] for r in expiries}:
                    chain = _records(request('get_option_chain', code=code, start=today, end=today,
                                             option_type=ft.OptionType.ALL,
                                             option_cond_type=ft.OptionCondType.ALL))
                row['option_eligibility'] = option_eligibility(expiries, chain, code, today)
            except (RuntimeError, ValueError, KeyError, TypeError) as exc:
                row['errors']['option_eligibility'] = str(exc)
            try:
                snapshots = _records(request('get_market_snapshot', [code]))
                snapshot = next((r for r in snapshots if r.get('code') == code), {})
                volume = _num(snapshot.get('option_volume'))
                if volume is not None and volume >= 0:
                    row['option_activity'].update(option_volume=volume,
                        as_of=snapshot.get('update_time'), available=True)
                row['underlying_state'] = {key: snapshot.get(key) for key in ('suspension', 'sec_status')}
            except (RuntimeError, ValueError, KeyError, TypeError) as exc:
                row['errors']['snapshot'] = str(exc)
    except (RuntimeError, ValueError, KeyError, TypeError) as exc:
        result['errors'].append(str(exc))
    finally:
        if subscribed:
            remaining = max(0.0, 61.0 - (clock() - last_subscription))
            while remaining > 0:
                seconds = min(30.0, remaining)
                pause(seconds)
                remaining -= seconds
            try:
                request('unsubscribe', symbols, subtypes)
            except Exception as exc:
                result['errors'].append('unsubscribe: ' + str(exc))
        finished = now_fn().astimezone(ET)
        result['completed_at'] = finished.isoformat()
        expected_bar = finished.replace(minute=finished.minute // 5 * 5, second=0, microsecond=0)
        for row in result['rows']:
            stamp = _et(row['last_completed_bar_at'])
            row['bar_age_seconds'] = (finished - stamp).total_seconds() if stamp else None
            row['expected_completed_bar_at'] = expected_bar.isoformat() if finished.time() >= dtime(9, 35) else None
            if stamp is not None and stamp < expected_bar:
                row['observation_status'] = 'STALE'
            elif stamp is None and finished.time() >= dtime(9, 35):
                row['observation_status'] = 'MISSING_DATA'
        result['ok'] = not result['errors'] and all(not r['errors'] for r in result['rows'])
        result['signal_overlap_count'] = sum(r['structure_signal_overlap'] for r in result['rows'])
        _write(root / 'manifest.json', result)
        write_checksums(root)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--symbols', required=True, help='comma-separated US stocks/ETFs; maximum 10')
    parser.add_argument('--out', required=True, type=Path, help='new raw observation directory; never overwritten')
    parser.add_argument('--host', default=None)
    parser.add_argument('--port', type=int, default=None)
    parser.add_argument('--format', choices=('json', 'markdown'), default='json', help='stdout only; raw files and manifest are unchanged')
    args = parser.parse_args(argv)
    try:
        symbols = _symbols(args.symbols.split(','))
        if args.out.exists():
            raise FileExistsError('refusing to overwrite: ' + str(args.out))
        if not _within_window(datetime.now(ET)):
            raise ValueError('DS1 scan requires 09:00 through 10:05 US/Eastern today')
        with OpenDMarket(host=args.host, port=args.port) as market:
            result = scan(symbols, args.out, market)
    except (RuntimeError, ValueError, OSError) as exc:
        parser.exit(1, str(exc) + '\n')
    print(format_observation(result) if args.format == 'markdown' else
          json.dumps(result, ensure_ascii=False, indent=2, default=str, allow_nan=False))
    return 0 if result['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
