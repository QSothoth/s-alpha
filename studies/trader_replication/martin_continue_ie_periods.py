"""IE stage one: retrospective price periods, independent of every trading system."""
from collections import Counter, defaultdict
import csv
from dataclasses import asdict
import gzip
import hashlib
from itertools import groupby
import json
import math
from pathlib import Path

import numpy as np

from studies.trader_data.dataset import COLUMNS, FolderDataset
from studies.trader_data.panel import VERSION
from studies.trader_replication import ledger
from studies.trend_breakout.panel import factors

ROOT = Path(__file__).resolve().parents[2]
CUTOFF = '2026-10-16'
LEDGER = ROOT / 'studies/martin_luk/notes/trades.csv'
OUTPUT = ROOT / 'studies/trader_replication/reports/gap_review/strong_continue_ie_periods.json'
SPOT_CHECKS = ('I01', 'I03', 'I05', 'I08', 'I11', 'I27', 'I29', 'I35', 'S11', 'V35')


def file_sha(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def calendar_from_raw(path, listed, cutoff=CUTOFF):
    """Only the small set of session dates survives this first streaming pass."""
    days = set()
    with gzip.open(path, 'rt', encoding='utf-8', newline='') as stream:
        rows = csv.reader(stream)
        if tuple(next(rows)) != COLUMNS:
            raise ValueError('unexpected raw daily-bar header')
        for row in rows:
            if row and row[0] in listed and row[1] <= cutoff:
                days.add(row[1])
    return sorted(days)


def adjusted_bars(records, actions, cutoff=CUTOFF):
    """Use the shared multiplicative adjustment on one symbol, never a full panel."""
    days, values = [], []
    for _, day, row in records:
        if day > cutoff:
            continue
        if days and day <= days[-1]:
            raise ValueError(f'repeated or unordered daily bar: {day}')
        days.append(day)
        values.append(row[:4])
    if not days:
        return {}, []
    raw = np.asarray(values, dtype=float)
    scale = factors(raw[:, 3], np.asarray(days), actions)
    prices = raw * scale[:, None]
    prices[:, 1] = np.fmax(prices[:, 1], np.fmax(prices[:, 0], prices[:, 3]))
    prices[:, 2] = np.fmin(prices[:, 2], np.fmin(prices[:, 0], prices[:, 3]))
    bars, invalid = {}, []
    for day, row in zip(days, prices):
        if not all(math.isfinite(x) and x > 0 for x in row):
            invalid.append(day)
        else:
            bars[day] = dict(zip(('open', 'high', 'low', 'close'), map(float, row)))
    return bars, invalid


def entry_position(entry_day, start, end, calendar, bars):
    start_close, end_high = bars[start]['close'], bars[end]['high']
    span = calendar.index(end) - calendar.index(start)
    elapsed = calendar.index(entry_day) - calendar.index(start)
    gain = end_high / start_close - 1
    entry = bars[entry_day]
    return {
        'elapsed_sessions': elapsed,
        'time_fraction': elapsed / span,
        'entry_close': entry['close'],
        'gain_at_entry_close': entry['close'] / start_close - 1,
        'rise_fraction_close_proxy': (entry['close'] - start_close) / (end_high - start_close) if gain else None,
        'rise_fraction_daily_low_high': [(entry[k] - start_close) / (end_high - start_close)
                                         for k in ('low', 'high')] if gain else None,
        'after_peak': entry_day > end,
    }


def label_entry(trade, calendar, bars):
    """Fixed 60 sessions before entry and at most 60 sessions after entry."""
    result = dict(asdict(trade), code='US.' + trade.ticker)
    if not trade.dated:
        return dict(result, status='window_only')
    if trade.entry_date not in calendar or trade.entry_date not in bars:
        return dict(result, status='missing_data', reason='no_bar_on_entry_date',
                    available_bars_in_ledger_window=[d for d in bars if trade.window_lo <= d <= trade.window_hi])
    entry = calendar.index(trade.entry_date)
    before = calendar[max(0, entry - 60):entry]
    valid_before = [d for d in before if d in bars]
    if not valid_before:
        return dict(result, status='insufficient_history')
    start = min(valid_before, key=lambda d: bars[d]['close'])
    stop = min(entry + 60, len(calendar) - 1)
    peak_window = calendar[calendar.index(start) + 1:stop + 1]
    peak = max((d for d in peak_window if d in bars), key=lambda d: bars[d]['high'])
    gain = bars[peak]['high'] / bars[start]['close'] - 1
    missing = [d for d in peak_window if d not in bars]
    unfinished = stop < entry + 60 or bool(missing)
    flags = []
    if len(valid_before) < 60:
        flags.append('fewer_than_60_prior_bars')
    if peak < trade.entry_date:
        flags.append('peak_before_entry')
    if peak == calendar[stop]:
        flags.append('peak_on_search_boundary')
    if unfinished:
        flags.append('unconfirmed_peak')
    return dict(result, status='strong' if bars[peak]['high'] >= bars[start]['close'] * 1.3
                else 'no_obvious_strong_period', start=start, end=peak,
                start_close=bars[start]['close'], end_high=bars[peak]['high'], gain=gain,
                duration_sessions=calendar.index(peak) - calendar.index(start),
                start_search=[before[0], before[-1]], peak_search=[peak_window[0], peak_window[-1]],
                available_prior_bars=len(valid_before), available_future_sessions=stop - entry,
                missing_peak_window_dates=missing, unfinished=unfinished, flags=flags,
                raw_position=entry_position(trade.entry_date, start, peak, calendar, bars))


def merge_periods(rows, calendar, bars):
    """Merge overlapping closed intervals; retain each original endpoint and gain."""
    groups = []
    for row in sorted((r for r in rows if r['status'] == 'strong'), key=lambda r: (r['start'], r['end'], r['id'])):
        if groups and row['start'] <= max(r['end'] for r in groups[-1]):
            groups[-1].append(row)
        else:
            groups.append([row])
    periods = []
    for group in groups:
        start, end = min(r['start'] for r in group), max(r['end'] for r in group)
        peak = max((d for d in calendar if start < d <= end and d in bars), key=lambda d: bars[d]['high'])
        flags = []
        if peak != end:
            flags.append('merged_end_is_not_highest_high')
        for row in group:
            row['period_id'] = f'{row["code"]}:{start}:{end}'
            row['merged_position'] = entry_position(row['entry_date'], start, end, calendar, bars)
        periods.append(dict(
            id=group[0]['period_id'], code=group[0]['code'], start=start, end=end,
            start_close=bars[start]['close'], end_high=bars[end]['high'],
            gain=bars[end]['high'] / bars[start]['close'] - 1,
            duration_sessions=calendar.index(end) - calendar.index(start),
            highest_high_day=peak, highest_high=bars[peak]['high'],
            unfinished=any(r['unfinished'] for r in group), flags=flags,
            first_entry=min(r['entry_date'] for r in group),
            entries=sorted(group, key=lambda r: (r['entry_date'], r['id'])),
        ))
    return periods


def distribution(values):
    if not values:
        return {'n': 0}
    quantiles = np.percentile(values, (0, 25, 50, 75, 100))
    return dict(n=len(values), **dict(zip(('min', 'p25', 'median', 'p75', 'max'), map(float, quantiles))))


def summarize(rows, periods):
    summary = {}
    for label, lo, hi in (('2024_2025', '2024-01-01', '2025-12-31'), ('2026', '2026-01-01', CUTOFF)):
        dated = [r for r in rows if r['precision'] in ('exact', 'chart') and lo <= r['entry_date'] <= hi]
        strong = [r for r in dated if r['status'] == 'strong']
        owned = [p for p in periods if lo <= p['first_entry'] <= hi]
        touching = [p for p in periods if any(lo <= r['entry_date'] <= hi for r in p['entries'])]
        summary[label] = dict(
            dated_longs=len(dated), precision=dict(Counter(r['precision'] for r in dated)),
            status=dict(Counter(r['status'] for r in dated)),
            window_only=sum(r['status'] == 'window_only' and lo <= r['window_lo'] <= hi for r in rows),
            periods_by_first_entry=len(owned), periods_with_entries=len(touching),
            unfinished_periods_by_first_entry=sum(p['unfinished'] for p in owned),
            gains=distribution([p['gain'] for p in owned]),
            duration_sessions=distribution([p['duration_sessions'] for p in owned]),
            entry_time_fraction=distribution([r['merged_position']['time_fraction'] for r in strong]),
            entry_rise_fraction_close_proxy=distribution([r['merged_position']['rise_fraction_close_proxy'] for r in strong]),
            raw_entry_time_fraction=distribution([r['raw_position']['time_fraction'] for r in strong]),
            raw_entry_rise_fraction_close_proxy=distribution([r['raw_position']['rise_fraction_close_proxy'] for r in strong]),
            entries_after_raw_peak=sum(r['raw_position']['after_peak'] for r in strong),
            entries_after_merged_end=sum(r['merged_position']['after_peak'] for r in strong),
            entry_time_buckets=dict(Counter('after_peak' if r['merged_position']['after_peak'] else
                                           'first_third' if r['merged_position']['time_fraction'] <= 1 / 3 else
                                           'middle_third' if r['merged_position']['time_fraction'] <= 2 / 3 else
                                           'last_third' for r in strong)),
        )
    return summary


def spot_check(row, calendar, bars):
    """Expose raw price evidence for the fixed, preselected manual review sample."""
    if row['status'] != 'strong':
        return dict(id=row['id'], status=row['status'], note=row['note'], trigger=row['trigger'])
    start, end = row['start'], row['end']
    before = [d for d in calendar if row['start_search'][0] <= d <= row['start_search'][1] and d in bars]
    after = [d for d in calendar if row['peak_search'][0] <= d <= row['peak_search'][1] and d in bars]
    # Independent sorted extrema check, rather than another call to the labeller.
    low = sorted((bars[d]['close'], d) for d in before)[0]
    high = sorted((-bars[d]['high'], d) for d in after)[0]
    points = {start, end, row['entry_date']}
    span = [d for d in calendar if start <= d <= end and d in bars]
    points.update(span[i * (len(span) - 1) // 6] for i in range(7))
    return dict(id=row['id'], period_id=row['period_id'], code=row['code'],
                setup=row['setup'], outcome=row['outcome'], trigger=row['trigger'], note=row['note'],
                source=row['source'], precision=row['precision'], entry_date=row['entry_date'],
                start=start, end=end, gain=row['gain'], raw_position=row['raw_position'],
                unfinished=row['unfinished'], flags=row['flags'],
                minimum_close_verified=low[1] == start, maximum_high_verified=high[1] == end,
                price_checkpoints=[dict(date=d, **bars[d]) for d in sorted(points)])


def main():
    if OUTPUT.exists():
        raise FileExistsError(f'refusing to overwrite an existing result: {OUTPUT}')
    ds = FolderDataset(ROOT / 'data/trader-data-v1', 'us')
    inputs = [ds.sub / name for name in ('bars_raw.csv.gz', 'actions.csv.gz', 'universe.json')]
    sources = [LEDGER, Path(__file__), Path(__file__).parent / 'tests/test_martin_continue_ie_periods.py',
               ROOT / 'studies/martin_luk/notes/PLAN_IE_CN.md',
               ROOT / 'studies/martin_luk/notes/PREREG_STRONG.md',
               ROOT / 'studies/trader_data/dataset.py', ROOT / 'studies/trend_breakout/panel.py',
               ROOT / 'studies/trader_replication/ledger.py']
    hashes = {str(p.relative_to(ROOT)): file_sha(p) for p in inputs + sources}
    digest = hashlib.sha256(f'panel v{VERSION}'.encode())
    for path in inputs:
        with path.open('rb') as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                digest.update(chunk)
    listed = {s['code'] for s in ds.stocks()}
    longs = [t for t in ledger.load(LEDGER) if t.side == 'long']
    by_code = defaultdict(list)
    rows, periods, audits, data_issues = [], [], [], []
    for trade in longs:
        by_code['US.' + trade.ticker].append(trade)
    calendar = calendar_from_raw(inputs[0], listed)
    if not calendar or calendar[-1] != CUTOFF:
        raise ValueError('frozen daily data does not end on the required cutoff')
    actions = ds.actions()
    seen, max_bars = set(), 0
    print(f'calendar={len(calendar)} sessions; long trades={len(longs)}; processing one symbol at a time', flush=True)
    for code, records in groupby(ds.rows(), key=lambda row: row[0]):
        if code not in by_code or code not in listed:
            continue
        if code in seen:
            raise ValueError(f'non-contiguous symbol in frozen daily data: {code}')
        seen.add(code)
        bars, invalid = adjusted_bars(records, actions.get(code, []))
        max_bars = max(max_bars, len(bars))
        symbol_rows = [label_entry(t, calendar, bars) for t in by_code[code]]
        periods.extend(merge_periods(symbol_rows, calendar, bars))
        rows.extend(symbol_rows)
        audits.extend(spot_check(r, calendar, bars) for r in symbol_rows if r['id'] in SPOT_CHECKS)
        if invalid or any(r['status'] in ('missing_data', 'insufficient_history') for r in symbol_rows):
            data_issues.append(dict(code=code, first_valid_bar=min(bars, default=None),
                                    last_valid_bar=max(bars, default=None), invalid_dates=invalid))
    for code in sorted(by_code.keys() - seen):
        for trade in by_code[code]:
            row = label_entry(trade, calendar, {})
            if row['status'] == 'missing_data':
                row['reason'] = 'code_absent_from_frozen_universe' if code not in listed else 'code_without_daily_bars'
            rows.append(row)
    if len(rows) != len(longs) or len({r['id'] for r in rows}) != len(longs):
        raise AssertionError('long-trade partition lost or duplicated a ledger row')
    if {str(p.relative_to(ROOT)): file_sha(p) for p in inputs + sources} != hashes:
        raise ValueError('an input changed during the run')
    rows.sort(key=lambda r: r['id'])
    periods.sort(key=lambda p: (p['first_entry'], p['code'], p['start']))
    anomalies = defaultdict(list)
    for row in rows:
        for flag in row.get('flags', []):
            anomalies[flag].append(row['id'])
    for period in periods:
        for flag in period['flags']:
            anomalies[flag].append(period['id'])
    cross_year = [p['id'] for p in periods if len({r['entry_date'][:4] for r in p['entries']}) > 1]
    output = dict(
        stage=1, evaluation_only=True, cutoff=CUTOFF, dataset='trader-data-v1/us',
        dataset_digest=digest.hexdigest(), input_sha256=hashes,
        conventions={
            'start': '入场日前第60至第1个市场交易日，取最低复权收盘；并列取最早日。',
            'peak': '起点次日起，至入场后第60个市场交易日（含）取最高复权日高；并列取最早日。',
            'threshold': '原始段最高价/起点收盘-1 >= 30%；不足的逐笔保留，不并入强势段。',
            'merge': '同股合格原始段按闭区间重叠的传递并集合并，起点取最早、终点取最晚原始峰日。',
            'merged_peak_conflict': '若并集终点不是段内最高价日，明确报警并保留原始段，不另改定义。',
            'duration': '市场交易日下标差，不含起点当天；起点和终点均有日K。',
            'entry_position': '时间比例=起点至入场交易日数/段长；涨幅比例=(入场日收盘-起点收盘)/(终点日高-起点收盘)。',
            'entry_price': '台账无统一成交价字段，涨幅位置用入场日收盘代理，另给当日日低/日高范围；不是本人实际成交价。',
            'precision': 'exact/chart只用原entry_date，不在chart窗口里择日；window逐笔单列，包括已有名义entry_date者。',
            'unfinished': '数据截止使入场后60日搜索未满，或峰值搜索缺日K，标未结束；不宣称已观察峰值必为最终峰值。',
            'summary': '段数及段涨幅按最早挂接入场年分组；另给各年有入场的段数，跨年段可重复。入场位置按笔、只统计强势段。',
            'limits': '事后评价标签，不进入选股；日K不包含盘前/盘后，chart日期有窗口误差，未检验任何系统或排序因子。',
        },
        processing=dict(max_symbol_bars_in_memory=max_bars, full_market_panel_built=False, cache_written=False),
        partition=dict(all_longs=len(rows), status=dict(Counter(r['status'] for r in rows))),
        summary=summarize(rows, periods), periods=periods,
        no_obvious_strong_period=[r for r in rows if r['status'] == 'no_obvious_strong_period'],
        missing_data=[r for r in rows if r['status'] in ('missing_data', 'insufficient_history')],
        window_only=[r for r in rows if r['status'] == 'window_only'],
        data_issues=data_issues, anomalies=dict(anomalies), cross_year_periods=cross_year,
        spot_checks=sorted(audits, key=lambda r: SPOT_CHECKS.index(r['id'])),
    )
    OUTPUT.write_text(json.dumps(output, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    print(json.dumps(output['partition'], ensure_ascii=False), flush=True)
    print(json.dumps(output['summary'], ensure_ascii=False), flush=True)
    print('wrote', OUTPUT, flush=True)


if __name__ == '__main__':
    main()
