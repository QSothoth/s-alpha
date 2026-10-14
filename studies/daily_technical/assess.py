"""Bounded, read-only daily OHLCV context for human opportunity review."""
from __future__ import annotations

import argparse
import contextlib
import csv
import json
import math
import os
import re
import socket
import sys
import time
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from statistics import mean
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class Bar:
    day: str
    open: float
    high: float
    low: float
    close: float
    volume: float


def symbol(value):
    value = value.strip().upper()
    if not re.fullmatch(r'(US\.[A-Z][A-Z0-9.-]{0,14}|HK\.\d{5}|(?:SH|SZ)\.\d{6})', value):
        raise ValueError('Use US.AAPL / HK.00700 / SH.600519 / SZ.000001; other markets are unsupported')
    return value


def closed_through(code, now):
    """Conservative local close + 30 minutes; early closes wait until normal close."""
    local = now.astimezone(ZoneInfo('America/New_York' if code.startswith('US.') else 'Asia/Shanghai'))
    cutoff = (15, 30) if code.startswith(('SH.', 'SZ.')) else (16, 30)
    return local.date() - timedelta(days=(local.hour, local.minute) < cutoff)


def clean(rows, code, now, as_of=None):
    cutoff = min(closed_through(code, now), as_of or date.max)
    kept, ignored, zero_volume = {}, 0, 0
    for row in rows:
        day = date.fromisoformat(str(row.get('date', row.get('time_key', '')))[:10])
        if day > cutoff:
            ignored += 1
            continue
        values = [float(row[k]) for k in ('open', 'high', 'low', 'close', 'volume')]
        o, h, l, c, v = values
        if not all(math.isfinite(x) for x in values) or min(o, h, l, c) <= 0 or v < 0:
            raise ValueError(f'Invalid OHLCV on {day}')
        if not l <= min(o, c) <= max(o, c) <= h:
            raise ValueError(f'Inconsistent OHLC on {day}')
        bar = Bar(day.isoformat(), *values)
        if bar.day in kept and kept[bar.day] != bar:
            raise ValueError(f'Conflicting duplicate date: {day}')
        kept[bar.day] = bar
    bars = []
    for day in sorted(kept):
        if kept[day].volume == 0:
            zero_volume += 1
        else:
            bars.append(kept[day])
    if len(bars) < 60:
        raise ValueError(f'Need 60 completed positive-volume daily bars; received {len(bars)}')
    return bars, dict(cutoff=cutoff.isoformat(), ignored_after_cutoff=ignored,
                      omitted_zero_volume=zero_volume,
                      calendar_days_since_bar=(cutoff - date.fromisoformat(bars[-1].day)).days)


def ema(values, period):
    result = [values[0]]
    alpha = 2 / (period + 1)
    for value in values[1:]:
        result.append(result[-1] + alpha * (value - result[-1]))
    return result


def atr_series(bars):
    tr = [b.high - b.low if i == 0 else max(b.high - b.low,
          abs(b.high - bars[i - 1].close), abs(b.low - bars[i - 1].close)) for i, b in enumerate(bars)]
    atr = [None] * len(bars)
    atr[13] = mean(tr[:14])
    for i in range(14, len(bars)):
        atr[i] = (13 * atr[i - 1] + tr[i]) / 14
    return atr


def money_flow(bars):
    window = bars[-21:]
    cmf = sum((2 * b.close - b.high - b.low) / (b.high - b.low) * b.volume
              if b.high > b.low else 0 for b in window) / sum(b.volume for b in window)
    pos = neg = 0.0
    for before, b in zip(bars[-15:-1], bars[-14:]):
        typical = (b.high + b.low + b.close) / 3
        previous = (before.high + before.low + before.close) / 3
        if typical > previous:
            pos += typical * b.volume
        elif typical < previous:
            neg += typical * b.volume
    mfi = 100 * pos / (pos + neg) if pos + neg else None
    return dict(cmf21=cmf, mfi14=mfi,
                cmf_bias='positive' if cmf > 0 else 'negative' if cmf < 0 else 'neutral',
                mfi_state='unavailable' if mfi is None else 'overbought' if mfi > 80
                else 'oversold' if mfi < 20 else 'middle',
                meaning='量价代理，不是实际资金净流入；超买/超卖不能单独触发买卖。')


def smc(bars):
    """2-left/2-right confirmed pivots; close breaks, wick sweeps and live 3-bar gaps."""
    high = low = None
    bias = 'unknown'
    broken = set()
    events, gaps = [], []
    for i, b in enumerate(bars):
        if i >= 4:
            p = i - 2
            peers = bars[p - 2:p] + bars[p + 1:p + 3]
            if all(bars[p].high > x.high for x in peers):
                high = dict(price=bars[p].high, pivot_date=bars[p].day, confirmed_date=b.day)
            if all(bars[p].low < x.low for x in peers):
                low = dict(price=bars[p].low, pivot_date=bars[p].day, confirmed_date=b.day)
        for pivot, direction in ((high, 'up'), (low, 'down')):
            if pivot is None or i == 0:
                continue
            level = pivot['price']
            key = (direction, pivot['pivot_date'])
            crossed = (bars[i - 1].close <= level < b.close if direction == 'up'
                       else bars[i - 1].close >= level > b.close)
            if crossed and key not in broken:
                kind = 'CHoCH' if bias not in ('unknown', direction) else 'BOS' if bias == direction else 'structure_break'
                events.append(dict(date=b.day, kind=kind, direction=direction, level=level,
                                   pivot_date=pivot['pivot_date'], confirmed_date=pivot['confirmed_date']))
                bias = direction
                broken.add(key)
            swept = (b.high > level and b.close < level and bars[i - 1].close <= level if direction == 'up'
                     else b.low < level and b.close > level and bars[i - 1].close >= level)
            if swept and key not in broken:
                events.append(dict(date=b.day, kind='high_sweep' if direction == 'up' else 'low_sweep',
                                   level=level, pivot_date=pivot['pivot_date']))
        live = []
        for gap in gaps:
            if i - gap['index'] > 60:
                continue
            if gap['direction'] == 'up':
                if b.low <= gap['lower']:
                    continue
                gap['upper'] = min(gap['upper'], b.low)
            else:
                if b.high >= gap['upper']:
                    continue
                gap['lower'] = max(gap['lower'], b.high)
            live.append(gap)
        gaps = live
        if i >= 2:
            if b.low > bars[i - 2].high:
                gaps.append(dict(date=b.day, direction='up', lower=bars[i - 2].high, upper=b.low, index=i))
            elif b.high < bars[i - 2].low:
                gaps.append(dict(date=b.day, direction='down', lower=b.high, upper=bars[i - 2].low, index=i))
    range_position = None
    if high and low and high['price'] > low['price']:
        range_position = (bars[-1].close - low['price']) / (high['price'] - low['price'])
    closest = sorted(gaps, key=lambda g: abs((g['lower'] + g['upper']) / 2 - bars[-1].close))[:3]
    return dict(structure_bias=bias, swing_high=high, swing_low=low,
                range_position=range_position,
                range_zone='unknown' if range_position is None else 'above_range' if range_position > 1
                else 'below_range' if range_position < 0 else 'premium' if range_position > .5 else 'discount',
                events_last_20_bars=[e for e in events if e['date'] >= bars[max(0, len(bars) - 20)].day],
                unfilled_fvg=[{k: v for k, v in g.items() if k != 'index'} for g in closest],
                meaning='SMC 简化量价标注；摆动点延迟两根日 K 确认，FVG 不是估值缺口或机构订单证据。')


def cycle(bars, e10, e20, atr):
    b, previous = bars[-1], bars[-2]
    hi = max(x.high for x in bars[-11:-1])
    lo = min(x.low for x in bars[-11:-1])
    extension = (b.close - e10[-1]) / atr if atr else None
    up = b.close > e10[-1] > e20[-1] and e20[-1] > e20[-6]
    down = b.close < e10[-1] < e20[-1] and e20[-1] < e20[-6]
    had_uptrend = any(bars[j].close > e10[j] > e20[j] for j in range(len(bars) - 11, len(bars) - 1))
    had_weakness = any(bars[j].close < e20[j] for j in range(len(bars) - 11, len(bars) - 1))
    stage, evidence = 'consolidation_or_unclear', ['当前没有清晰的简化阶段条件']
    if b.close < min(e10[-1], e20[-1], lo) and had_uptrend:
        stage, evidence = 'wedge_drop_candidate', ['跌破此前十日低点及两条 EMA，近期曾处于上升排列']
    elif extension is not None and extension >= 2.5:
        stage, evidence = 'extended', ['收盘高于 EMA10 至少 2.5 ATR；只能说明延伸，不能确认见顶']
    elif up and b.close > hi and had_weakness:
        stage, evidence = 'wedge_pop_candidate', ['近期曾低于 EMA20，现重回上升排列并突破此前十日高点']
    elif up and b.close > hi and atr and hi - lo <= 4 * atr:
        stage, evidence = 'base_break_candidate', ['上升排列中突破此前十日高点，整理宽度不超过 4 ATR']
    elif up and had_uptrend and b.low <= max(e10[-2], e20[-2]) and b.close > max(b.open, previous.close):
        stage, evidence = 'ema_crossback_candidate', ['上升背景中触及昨日 EMA 区域，收盘回到 EMA10 上方并转强']
    elif up:
        stage, evidence = 'advancing', ['价格、EMA10、EMA20 上升排列，EMA20 高于五日前']
    elif down:
        stage, evidence = 'declining', ['价格、EMA10、EMA20 下降排列，EMA20 低于五日前']
    elif had_weakness and b.close > max(b.open, previous.close) and b.close > e10[-1]:
        stage, evidence = 'reversal_attempt', ['近期偏弱，今日反弹收回 EMA10；尚未确认趋势反转']
    return dict(stage=stage, evidence=evidence, extension_atr=extension,
                meaning='Oliver Kell Cycle of Price Action 的日 K 启发式近似，不是原版完整多周期方法。')


def assess(bars, code, metadata):
    closes = [b.close for b in bars]
    e10, e20 = ema(closes, 10), ema(closes, 20)
    atr = atr_series(bars)[-1]
    flow, structure = money_flow(bars), smc(bars)
    price_cycle = cycle(bars, e10, e20, atr)
    b = bars[-1]
    warnings = list(metadata.get('warnings', []))
    if metadata.get('calendar_days_since_bar', 0) > 7:
        warnings.append('最新日 K 距截止日超过七个自然日；先核对停牌、假期或源数据过期。')
    if metadata.get('omitted_zero_volume'):
        warnings.append('已剔除零成交量行；窗口按有交易的日 K 计算，注意停牌或成交量缺失。')
    if len(bars) < 200:
        warnings.append('不足 200 根有效日 K，长期均线缺失；短样本 EMA 热身也较短。')
    if any(abs(bars[i].close / bars[i - 1].close - 1) > .3 for i in range(max(1, len(bars) - 20), len(bars))):
        warnings.append('最近二十根出现单日超过 30% 的变化；核对事件及复权，不能自动归因为趋势。')
    if not atr:
        warnings.append('ATR 为零，无法判断波动距离。')
    conflicts = []
    if b.close > e20[-1] and flow['cmf21'] < 0:
        conflicts.append('收盘在 EMA20 上方，但 CMF 为负；价格与量价代理不一致。')
    if b.close < e20[-1] and flow['cmf21'] > 0:
        conflicts.append('CMF 为正，但收盘仍在 EMA20 下方；不能用资金流代理代替价格确认。')
    if structure['structure_bias'] == 'down' and b.close > e20[-1]:
        conflicts.append('价格已回到 EMA20 上方，但最近确认的结构方向仍向下。')
    stance = 'wait_for_structure'
    stage = price_cycle['stage']
    if stage in ('declining', 'wedge_drop_candidate'):
        stance = 'avoid_new_entry_for_now'
    elif stage == 'extended':
        stance = 'avoid_chasing'
    elif stage in ('wedge_pop_candidate', 'base_break_candidate', 'ema_crossback_candidate'):
        stance = 'review_entry_conditions'
    elif stage == 'advancing':
        stance = 'wait_for_pullback_or_base'
    if metadata.get('calendar_days_since_bar', 0) > 7 or metadata.get('adjustment') != 'qfq' or not atr:
        stance = 'check_data_first'
    levels = dict(ema_band=[min(e10[-1], e20[-1]), max(e10[-1], e20[-1])],
                  prior20_high=max(x.high for x in bars[-21:-1]),
                  prior20_low=min(x.low for x in bars[-21:-1]))
    return dict(schema_version=1, symbol=code, currency='USD' if code.startswith('US.') else 'HKD' if code.startswith('HK.') else 'CNY',
                data=dict(metadata, first_date=bars[0].day, last_date=b.day, bars=len(bars)),
                latest=dict(close=b.close, ema10=e10[-1], ema20=e20[-1], sma50=mean(closes[-50:]),
                            sma200=mean(closes[-200:]) if len(bars) >= 200 else None, atr14=atr,
                            relative_volume20=b.volume / mean(x.volume for x in bars[-21:-1]),
                            returns_pct={str(n): 100 * (b.close / closes[-n - 1] - 1)
                                         for n in (5, 20, 60) if len(bars) > n}),
                cycle=price_cycle, smc=structure, money_flow=flow, reference_levels=levels,
                recent_bars=[dict(date=x.day, open=x.open, high=x.high, low=x.low, close=x.close,
                                  volume=x.volume) for x in bars[-5:]],
                review=dict(direction='long_only', stance=stance, conflicts=conflicts, warnings=warnings,
                            model_reminder='仅评估做多：明确现在可考虑买、条件成立才买或暂不买；下行信号只用于不买或多头退出。'
                            '给出触发条件、入场范围和追价上限、初始止损及执行方式、最近上方阻力与收益风险比、取消条件。'
                            '区分已确认信号与未来计划；未形成买点就明确没有，不能编造未来确认 K 的价格。'
                            '收盘确认后最早下一交易时段介入；不能跳过近处阻力美化收益风险比。'
                            '结合机会逻辑与持有期限，解释支持和反证；同源指标不能独立投票，EMA/FVG 不是自动买区。'
                            '脚本只提供测量，条件计划由模型判断，最终由人决定。'))


def fetch_tencent(code, count):
    if code.startswith('US.'):
        raise ValueError('Tencent adapter supports SH/SZ/HK only')
    ticker = code[:2].lower() + code[3:]
    endpoint = 'hkfqkline' if code.startswith('HK.') else 'fqkline'
    url = f'https://web.ifzq.gtimg.cn/appstock/app/{endpoint}/get?param={ticker},day,,,{count},qfq'
    request = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0', 'Referer': 'https://gu.qq.com/'})
    with urllib.request.urlopen(request, timeout=15) as response:
        payload = json.loads(response.read(2_000_001))
    node = (payload.get('data') or {}).get(ticker) or {}
    rows = node.get('qfqday')
    if not rows:
        raise ValueError('Tencent returned no explicit qfqday; raw day data is not silently substituted')
    return [dict(date=r[0], open=r[1], close=r[2], high=r[3], low=r[4], volume=r[5])
            for r in rows[-count:]], dict(source='tencent_qfqday', adjustment='qfq',
                                        volume_unit='provider_native_consistent_within_symbol',
                                        warnings=['腾讯公开接口没有服务保证；量比/CMF/MFI 只比较本标的，成交量不跨源混合。'])


def fetch_opend(code, count, host, port):
    # Bound the SDK's reconnect path before constructing a context.
    with socket.create_connection((host, port), timeout=3):
        pass
    import futu as ft
    ctx = ft.OpenQuoteContext(host=host, port=port)
    try:
        ret, error = ctx.subscribe([code], [ft.SubType.K_DAY], subscribe_push=False,
                                   session=ft.Session.RTH if code.startswith('US.') else ft.Session.NONE)
        if ret != ft.RET_OK:
            raise RuntimeError(f'OpenD subscription failed: {error}')
        frame = None
        for delay in (2, 6):
            time.sleep(delay)
            ret, frame = ctx.get_cur_kline(code, count, ft.KLType.K_DAY, ft.AuType.QFQ)
            if ret == ft.RET_OK and len(frame) >= count:
                break
        if ret != ft.RET_OK:
            raise RuntimeError(f'OpenD daily bars failed: {frame}')
        return frame.to_dict('records'), dict(source='opend_get_cur_kline', adjustment='qfq',
                                             volume_unit='shares', warnings=[])
    finally:
        # Own connection only. OpenD releases its subscriptions after the one-minute minimum.
        ctx.close()


def fetch(code, count, source, host, port):
    choices = [source] if source != 'auto' else (['tencent', 'opend'] if code.startswith(('SH.', 'SZ.'))
                                               else ['opend', 'tencent'] if code.startswith('HK.') else ['opend'])
    errors = []
    for choice in choices:
        try:
            rows, metadata = fetch_tencent(code, count) if choice == 'tencent' else fetch_opend(code, count, host, port)
            metadata['warnings'].extend(errors)
            return rows, metadata
        except (OSError, ValueError, RuntimeError, ImportError, KeyError, TypeError, IndexError) as exc:
            errors.append(f'{choice}: {exc}')
    raise RuntimeError('; '.join(errors))


def read_csv(path, code, count):
    # Bounded single-symbol input, no full-universe file ingestion.
    if path.stat().st_size > 2_000_000:
        raise ValueError('CSV must be a single-symbol file under 2 MB')
    with path.open(encoding='utf-8-sig', newline='') as handle:
        rows = list(csv.DictReader(handle))
    if len(rows) > 1000:
        raise ValueError('CSV must have at most 1000 rows')
    if any(r.get('code', r.get('symbol', code)) != code for r in rows):
        raise ValueError('CSV contains a different symbol')
    return sorted(rows, key=lambda r: r.get('date', r.get('time_key', '')))[-count:]


def main(argv=None):
    parser = argparse.ArgumentParser(description='纯多头日 K 技术面参考：Cycle / SMC / CMF / MFI；不下单。')
    parser.add_argument('symbols', nargs='+', type=symbol, help='最多五只，代码需带市场前缀')
    parser.add_argument('--source', choices=('auto', 'opend', 'tencent'), default='auto')
    parser.add_argument('--bars', type=int, default=300, help='60–1000，默认 300')
    parser.add_argument('--as-of', type=date.fromisoformat, help='截断日期；当前前复权序列不是历史点时数据')
    parser.add_argument('--csv', type=Path, help='单只标的本地 OHLCV 文件，不联网')
    parser.add_argument('--csv-adjustment', choices=('qfq', 'raw', 'unknown'), default='unknown')
    parser.add_argument('--host', default=os.environ.get('FUTU_HOST', os.environ.get('FUTU_OPEND_HOST', '127.0.0.1')))
    parser.add_argument('--port', type=int, default=int(os.environ.get('FUTU_PORT', os.environ.get('FUTU_OPEND_PORT', '11111'))))
    args = parser.parse_args(argv)
    if not 60 <= args.bars <= 1000 or not 1 <= len(args.symbols) <= 5:
        parser.error('Use 60–1000 bars and 1–5 symbols')
    if args.csv and len(args.symbols) != 1:
        parser.error('--csv requires exactly one symbol')
    results = []
    for code in dict.fromkeys(args.symbols):
        try:
            if args.csv:
                rows = read_csv(args.csv, code, args.bars)
                metadata = dict(source='local_csv', adjustment=args.csv_adjustment,
                                volume_unit='caller_supplied', warnings=[])
            else:
                with contextlib.redirect_stdout(sys.stderr):
                    rows, metadata = fetch(code, args.bars, args.source, args.host, args.port)
            now = datetime.now(timezone.utc)
            bars, quality = clean(rows, code, now, args.as_of)
            metadata.update(quality, fetched_at=now.isoformat())
            if metadata['adjustment'] != 'qfq':
                metadata['warnings'].append('复权口径不是已声明前复权；先核对拆股/分红，不能直接采用阶段和价位。')
            if args.as_of:
                metadata['warnings'].append('--as-of 仅截断当前序列，含当前复权信息，不能当历史点时回测。')
            results.append(assess(bars, code, metadata))
        except (OSError, ValueError, RuntimeError, ImportError, KeyError, TypeError, IndexError) as exc:
            results.append(dict(symbol=code, error=str(exc), review=dict(stance='check_data_first')))
    print(json.dumps(dict(results=results), ensure_ascii=False, indent=2, allow_nan=False))
    return int(any('error' in r for r in results))


if __name__ == '__main__':
    sys.exit(main())
