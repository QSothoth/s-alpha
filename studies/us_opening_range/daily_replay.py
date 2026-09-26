"""Stream DS1 daily-structure signal quality; no orders, fills or option P&L."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict, deque
import csv
from datetime import datetime, timedelta, timezone
import heapq
from itertools import groupby
import json
from math import fsum
from pathlib import Path
import random
import resource
import time

from custody.dataset import sha256_file
from custody.marketdata import Bar
from custody.models import ET
from .context_replay import SYMBOLS, verify_inputs
from .context_stats import _lower
from .daily_signals import daily_levels, detect_signals, evaluate_signal_quality


CANDIDATES = ('PD_BREAK', 'NR7_BREAK', 'INSIDE_BREAK')
PREREG_SHA256 = 'e9e0cf57f95587cbd70e8729bb428733e375950a0b1cbe739140157f7f56cbac'
INPUT_SHA256 = '5531f0ccff46be6135b9c87457bebf79fd2ad1703182918ea2dbcb784bc6468d'
CALENDAR_SHA256 = '501c508b69124b1da76c0b986c997ae3a89106eb59e865847637043f21eb72b8'
CALENDAR_PATH = Path('data/or-context-etf-k5-2018-2026-retry1-work/US.DIA.coverage.csv')


def complete_session(bars, expected_bars=78):
    """Full RTH is required for tomorrow's daily history, not today's signal."""
    if expected_bars not in (42, 78) or len(bars) != expected_bars:
        return False
    opening = bars[0].close_time.replace(hour=9, minute=30, second=0, microsecond=0)
    return all(bar.close_time == opening + timedelta(minutes=5 * index)
               and bar.interval == '5m' and bar.code == bars[0].code
               and min(bar.open, bar.high, bar.low, bar.close) > 0
               for index, bar in enumerate(bars, 1))


def iter_sessions(path, symbol, calendar=None):
    """Keep a bounded day, retaining good prefixes even when later bars are absent."""
    previous = None
    with Path(path).open(newline='', encoding='utf-8') as handle:
        for day, rows in groupby(csv.DictReader(handle), key=lambda row: row['time_key'][:10]):
            bars, invalid, count = [], False, 0
            for row in rows:
                stamp = datetime.fromisoformat(row['time_key'])
                if stamp.tzinfo is not None:
                    raise ValueError('expected OpenD local ET timestamp')
                stamp = stamp.replace(tzinfo=ET)
                if previous is not None and stamp <= previous:
                    raise ValueError('duplicate or unordered timestamp')
                previous = stamp
                count += 1
                if count > 78:
                    invalid = True
                    continue
                try:
                    bar = Bar('US.' + symbol, stamp, *(float(row[key]) for key in
                              ('open', 'high', 'low', 'close', 'volume')), interval='5m')
                    if min(bar.open, bar.high, bar.low, bar.close) <= 0:
                        raise ValueError('nonpositive price')
                    bars.append(bar)
                except (KeyError, TypeError, ValueError):
                    invalid = True
            expected = calendar.get(day) if calendar is not None else 78
            yield day, symbol, bars, not invalid and complete_session(bars, expected)


def aggregate_daily(bars, expected_bars=78):
    if not complete_session(bars, expected_bars):
        raise ValueError('cannot create daily history from an incomplete RTH session')
    return Bar(bars[0].code, bars[-1].close_time, bars[0].open,
               max(bar.high for bar in bars), min(bar.low for bar in bars),
               bars[-1].close, fsum(bar.volume for bar in bars), interval='1d',
               source='opend_qfq_5m_aggregate')


def metrics(values):
    wins = [value for value in values if value > 0]
    losses = [-value for value in values if value < 0]
    profit, loss = fsum(wins), fsum(losses)
    return {'labeled_signals': len(values), 'wins': len(wins), 'losses': len(losses),
            'zeros': len(values) - len(wins) - len(losses),
            'mean_bp': 10000 * fsum(values) / len(values) if values else None,
            'win_rate': len(wins) / len(values) if values else None,
            'average_win_bp': 10000 * profit / len(wins) if wins else None,
            'average_loss_bp': 10000 * loss / len(losses) if losses else None,
            'payoff_ratio': (profit / len(wins)) / (loss / len(losses)) if wins and losses else None,
            'profit_factor': profit / loss if loss else None}


def summarize(days, controls, draws=2000):
    keys = sorted(days)
    values = [value for day in keys for value in days[day]['returns']]
    result = metrics(values)
    result.update(n_dates=len(keys), eligible_sessions=sum(days[day]['n_sessions'] for day in keys),
                  signals=sum(days[day]['signals'] for day in keys),
                  active_dates=sum(days[day]['signals'] > 0 for day in keys),
                  labeled_dates=sum(bool(days[day]['returns']) for day in keys))
    result['missing_labels'] = result['signals'] - result['labeled_signals']
    result['signals_per_100_sessions'] = (100 * result['signals'] / result['eligible_sessions']
                                         if result['eligible_sessions'] else 0.0)
    result['halves'] = {name: metrics([value for day in keys if test(day)
                                      for value in days[day]['returns']]) for name, test in
                        (('before_2022_06_01', lambda day: day < '2022-06-01'),
                         ('from_2022_06_01', lambda day: day >= '2022-06-01'))}
    rows = [(fsum(days[day]['returns']), len(days[day]['returns'])) for day in keys]
    rng, boot = random.Random(20260925), []
    for _ in range(draws if rows else 0):
        total, count = 0.0, 0
        for _ in rows:
            day_sum, day_count = rng.choice(rows)
            total += day_sum
            count += day_count
        if count:
            boot.append(10000 * total / count)
    result['mean_lower_95_bp'] = _lower(boot)
    result['bootstrap'] = {'draws': draws if rows else 0, 'seed': 20260925, 'unit': 'date',
                           'undefined_draws': (draws - len(boot)) if rows else 0,
                           'quantile': 0.05, 'zero_signal_dates_included': True}
    lifts = []
    for day in keys:
        selected, control = days[day]['returns'], controls[day]['returns']
        if selected:
            if not control:
                raise ValueError('candidate signal without its PD control')
            lifts.append(fsum(selected) / len(selected) - fsum(control) / len(control))
    result['same_date_control_lift_bp'] = 10000 * fsum(lifts) / len(lifts) if lifts else None
    pf = result['profit_factor']
    positive = lambda value: value is not None and value > 0
    result['gates'] = {
        '100_labeled_signals': len(values) >= 100,
        '60_active_dates': result['active_dates'] >= 60,
        'mean_at_least_5bp': result['mean_bp'] is not None and result['mean_bp'] >= 5,
        'mean_lower_positive': positive(result['mean_lower_95_bp']),
        'profit_factor_at_least_1_2': pf >= 1.2 if pf is not None else result['wins'] > 0 and not result['losses'],
        'both_halves_positive': all(positive(row['mean_bp']) for row in result['halves'].values()),
        'same_date_control_lift_positive': positive(result['same_date_control_lift_bp']),
    }
    result['development_eligible'] = all(result['gates'].values())
    return result


def _day_record():
    return {'n_sessions': 0, 'signals': 0, 'returns': []}


def read_calendar(path):
    """Use only the already calendar-audited date grid, never ETF price rows."""
    if sha256_file(path) != CALENDAR_SHA256:
        raise ValueError('DS1 calendar metadata checksum mismatch')
    calendar = {}
    with Path(path).open(newline='', encoding='utf-8') as handle:
        for row in csv.DictReader(handle):
            day = row['date']
            if not '2020-01-02' <= day <= '2024-05-31':
                continue
            count = int(row['rows'])
            if (day in calendar or count not in (42, 78) or row['first_close'] != '09:35:00'
                    or row['last_close'] != ('13:00:00' if count == 42 else '16:00:00')
                    or int(row['missing_before_or_between']) != 0):
                raise ValueError('invalid calendar metadata')
            calendar[day] = count
    if not calendar:
        raise ValueError('empty calendar')
    return calendar


def replay(root, calendar_path=CALENDAR_PATH, emit=None):
    started = time.monotonic()
    root = Path(root)
    prereg = Path(__file__).with_name('notes') / 'DS1_PREREG.md'
    if sha256_file(prereg) != PREREG_SHA256:
        raise ValueError('DS1 preregistration checksum mismatch')
    if sha256_file(root / 'CHECKSUMS.sha256') != INPUT_SHA256:
        raise ValueError('DS1 permits only the pinned development input')
    inputs = verify_inputs(root)
    calendar = read_calendar(calendar_path)
    inputs['calendar_metadata_sha256'] = CALENDAR_SHA256
    history = {symbol: deque(maxlen=20) for symbol in SYMBOLS}
    days = {name: defaultdict(_day_record) for name in CANDIDATES}
    coverage, rejected = {symbol: Counter() for symbol in SYMBOLS}, Counter()
    paths = {name: Counter() for name in CANDIDATES}
    totals = {name: Counter() for name in CANDIDATES}
    groups = {name: {'ETF': [], 'STOCK': []} for name in CANDIDATES}
    overlaps = 0
    streams = [iter_sessions(root / 'k5' / (symbol + '.csv'), symbol, calendar) for symbol in SYMBOLS]
    streams.append(((day, '', None, None) for day in sorted(calendar)))
    merged = heapq.merge(*streams, key=lambda row: (row[0], row[1]))
    for day, records in groupby(merged, key=lambda row: row[0]):
        if day not in calendar:
            raise ValueError('date outside DS1 calendar')
        current = {symbol: (bars, complete) for _, symbol, bars, complete in records if symbol}
        for symbol in SYMBOLS:
            if symbol not in current:
                coverage[symbol]['missing_day'] += 1
                history[symbol].clear()
                continue
            bars, complete = current[symbol]
            coverage[symbol]['observed_days'] += 1
            coverage[symbol]['complete_days' if complete else 'incomplete_days'] += 1
            if len(history[symbol]) == 20:
                coverage[symbol]['history_eligible_days'] += 1
                levels = daily_levels(list(history[symbol]), datetime.fromisoformat(day).date())
                signals, blocked = detect_signals(bars, levels)
                rejected.update(blocked)
                overlaps += bool(signals['NR7_BREAK'] and signals['INSIDE_BREAK'])
                for name in CANDIDATES:
                    record = days[name][day]
                    record['n_sessions'] += 1
                    signal = signals[name]
                    if signal is None:
                        continue
                    record['signals'] += 1
                    coverage[symbol][name + '_signals'] += 1
                    quality = evaluate_signal_quality(bars, signal)
                    if emit is not None:
                        emit(dict(signal, **quality))
                    if quality['label_status'] != 'complete':
                        paths[name]['missing_future'] += 1
                        continue
                    record['returns'].append(quality['return_30m'])
                    groups[name]['ETF' if symbol in ('SPY', 'QQQ', 'IWM') else 'STOCK'].append(quality['return_30m'])
                    paths[name][quality['path_status']] += 1
                    for key in ('return_atr', 'mfe_r', 'mae_r'):
                        totals[name][key] += quality[key]
                    totals[name]['labels'] += 1
            else:
                coverage[symbol]['warmup_days'] += 1
            if complete:
                history[symbol].append(aggregate_daily(bars, calendar[day]))
            else:
                history[symbol].clear()
    results = {name: summarize(days[name], days['PD_BREAK']) for name in CANDIDATES}
    for name, result in results.items():
        result['path_counts'] = dict(paths[name])
        result['mean_auxiliary'] = {key: totals[name][key] / totals[name]['labels']
                                    if totals[name]['labels'] else None
                                    for key in ('return_atr', 'mfe_r', 'mae_r')}
        result['conservative_target_first_rate'] = (paths[name]['target_first'] / result['signals']
                                                   if result['signals'] else None)
        result['groups_descriptive_only'] = {key: metrics(values) for key, values in groups[name].items()}
    eligible = [name for name in ('NR7_BREAK', 'INSIDE_BREAK') if results[name]['development_eligible']]
    selected = min(eligible, key=lambda name: (-results[name]['mean_lower_95_bp'], name)) if eligible else None
    repo = Path(__file__).resolve().parents[2]
    files = [Path(__file__), Path(__file__).with_name('daily_signals.py'),
             Path(__file__).with_name('context_replay.py'), Path(__file__).with_name('context_signals.py'),
             Path(__file__).with_name('context_stats.py'), repo / 'custody' / 'marketdata.py',
             repo / 'custody' / 'models.py', repo / 'custody' / 'dataset.py']
    return {'study': 'DS1', 'status': 'DEVELOPMENT_SIGNAL_QUALITY_ONLY',
            'selected_for_migration': selected, 'created_at': datetime.now(timezone.utc).isoformat(),
            'inputs': inputs, 'preregistration_sha256': PREREG_SHA256,
            'code_sha256': {str(path.relative_to(repo)): sha256_file(path) for path in files},
            'candidates': results, 'coverage_by_symbol': coverage,
            'checkpoint_rejections': rejected, 'nr7_inside_overlap_signals': overlaps,
            'by_day': days,
            'limitations': ['多次已用开发数据，未校正历次研究搜索；不是独立验证。',
                            '这是信号参考价标签，不是成交收益、期权胜率或期权2R。',
                            '没有历史逐日0DTE链准入；当前存活标的池。',
                            '同源QFQ事后数据不是逐时点复权因子档案；盘前信号未在本轮评测。',
                            '正股与ETF分组仅描述，不因结果产生新候选或调整参数。'],
            'resources': {'elapsed_seconds': time.monotonic() - started,
                          'peak_rss_kib': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss}}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset', type=Path, default=Path('data/preopen-us-k5-select-v1'))
    parser.add_argument('--calendar', type=Path, default=CALENDAR_PATH)
    parser.add_argument('--signals-out', type=Path, help='optional new JSONL file retaining every signal and label')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args(argv)
    if args.out.exists():
        parser.error('refusing to overwrite report: ' + str(args.out))
    if args.signals_out is not None:
        if args.signals_out.exists() or args.signals_out.resolve() == args.out.resolve():
            parser.error('signals output must be a separate new file')
        args.signals_out.parent.mkdir(parents=True, exist_ok=True)
        with args.signals_out.open('x', encoding='utf-8') as events:
            result = replay(args.dataset, args.calendar,
                            lambda event: events.write(json.dumps(event, ensure_ascii=False, allow_nan=False) + '\n'))
        result['signal_events'] = {'path': str(args.signals_out), 'sha256': sha256_file(args.signals_out)}
    else:
        result = replay(args.dataset, args.calendar)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open('x', encoding='utf-8') as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2, allow_nan=False)
        handle.write('\n')
    print(json.dumps({key: result[key] for key in ('study', 'status', 'selected_for_migration', 'resources')}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
