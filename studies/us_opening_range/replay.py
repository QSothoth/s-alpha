"""Offline, session-bounded diagnostic replay of the four registered OR1 rules."""
from __future__ import annotations

import argparse
import csv
import json
import statistics
from collections import defaultdict
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from custody.dataset import Dataset, DatasetError, default_session, sha256_file
from custody.evaluate import FillModel
from custody.marketdata import Bar
from custody.models import instant

from .signals import CANDIDATES, exit_signal, find_signal


def paired_sessions(dataset):
    """Require exactly the preselected opening-ATM CALL and PUT per session."""
    groups = defaultdict(list)
    for case in dataset.cases:
        groups[(case.symbol, case.trade_date)].append(case)
    for key, cases in sorted(groups.items(), key=lambda item: (item[0][1], item[0][0])):
        if (len(cases) != 2 or {case.direction for case in cases} != {'LONG', 'SHORT'}
                or len({case.strike for case in cases}) != 1
                or any(case.strike <= 0 or case.selection != 'both_sides_atm_at_open' for case in cases)
                or any(not case.session_close for case in cases)
                or len({case.session_close for case in cases}) != 1):
            raise DatasetError('expected one opening-ATM CALL/PUT pair at one strike: %s %s' % key)
        yield key, {case.direction: case for case in cases}


def session_bars(dataset, kind, code, session):
    """Stream a pinned CSV, retaining only one regular session; never use _tape."""
    path = (dataset.root / kind / (code + '.csv')).resolve()
    if path not in dataset._pinned:
        raise DatasetError('series is not pinned: ' + str(path))
    bars = []
    with path.open(newline='', encoding='utf-8') as handle:
        for row in csv.DictReader(handle):
            try:
                when = instant(row['close_time'])
                if not session.opens < when <= session.closes:
                    continue
                if row['code'] != code or row['interval'] != '1m':
                    raise ValueError('wrong code or interval')
                if (when - session.opens).total_seconds() % 60:
                    raise ValueError('not a minute boundary')
                if bars and when <= bars[-1].close_time:
                    raise ValueError('duplicate or unordered timestamp')
                bar = Bar(code, when, *(float(row[field]) for field in
                          ('open', 'high', 'low', 'close', 'volume')), source='frozen')
                if min(bar.open, bar.high, bar.low, bar.close) < 0:
                    raise ValueError('negative price')
                bars.append(bar)
            except (KeyError, TypeError, ValueError) as exc:
                raise DatasetError('invalid session row in %s: %s' % (path, exc)) from exc
    if kind == 'underlying':
        expected = int((session.closes - session.opens).total_seconds() // 60)
        if (len(bars) != expected or any(
                bar.close_time != session.opens + timedelta(minutes=minute)
                or min(bar.open, bar.high, bar.low, bar.close) <= 0
                for minute, bar in enumerate(bars, 1))):
            raise DatasetError('incomplete or invalid underlying session: %s %s' % (code, session.day))
    else:
        bars = [bar for bar in bars if bar.volume > 0 and bar.close > 0]
        if not bars:
            raise DatasetError('no traded option bars: %s %s' % (code, session.day))
    return bars


def option_trade(option_bars, session, signal, exit_decision, fill):
    """Use only post-decision option prints, with the registered two-minute limit."""
    result = {'outcome': 'NO_SIGNAL', 'direction': None, 'entry': None, 'exit': None,
              'net_return': 0.0, 'net_pnl': 0.0}
    if signal is None:
        return result
    result.update(outcome='UNFILLED', direction=signal.direction)
    exit_time = exit_decision[0] if exit_decision else session.closes
    # A pending entry fills before processing an exit decision at the same close.
    entry_bar = next((bar for bar in option_bars
                      if signal.time + timedelta(minutes=1) <= bar.close_time
                      <= signal.time + timedelta(minutes=2)
                      and bar.close_time <= exit_time and bar.close_time < session.closes
                      and bar.volume > 0 and bar.close > 0), None)
    if entry_bar is None:
        return result
    entry_price = fill.buy(entry_bar)
    result['entry'] = {'time': entry_bar.close_time.isoformat(), 'price': entry_price}
    exit_bar = next((bar for bar in option_bars
                     if exit_decision and exit_time + timedelta(minutes=1) <= bar.close_time
                     <= min(exit_time + timedelta(minutes=2), session.closes)
                     and bar.volume > 0 and bar.close > 0), None)
    exit_price = fill.sell(exit_bar) if exit_bar else 0.0
    fees = fill.fee_per_contract * (2 if exit_bar else 1)
    pnl = (exit_price - entry_price) * fill.multiplier - fees
    result.update(outcome='COMPLETED' if exit_bar else 'MISSING_EXIT', net_pnl=pnl,
                  net_return=pnl / (entry_price * fill.multiplier))
    result['exit'] = {'time': exit_bar.close_time.isoformat() if exit_bar else None,
                      'price': exit_price, 'reason': exit_decision[1] if exit_decision else None,
                      'assumed_zero_value': exit_bar is None}
    return result


def summarize(records, cost):
    """Show session-equal and date-equal results, retaining every zero-trade day."""
    days = defaultdict(lambda: {'n_sessions': 0, 'n_signals': 0, 'n_trades': 0,
                                'sum_net_return': 0.0})
    returns, trade_returns = [], []
    directions = {'LONG': 0, 'SHORT': 0}
    signal_directions = {'LONG': 0, 'SHORT': 0}
    unfilled = missing_exits = 0
    for record in records:
        trade = record[cost]
        day = days[record['trade_date']]
        day['n_sessions'] += 1
        day['sum_net_return'] += trade['net_return']
        returns.append(trade['net_return'])
        if trade['direction']:
            day['n_signals'] += 1
            signal_directions[trade['direction']] += 1
        if trade['entry']:
            day['n_trades'] += 1
            trade_returns.append(trade['net_return'])
            directions[trade['direction']] += 1
        unfilled += trade['outcome'] == 'UNFILLED'
        missing_exits += trade['outcome'] == 'MISSING_EXIT'
    wins = [value for value in trade_returns if value > 0]
    losses = [value for value in trade_returns if value < 0]
    daily = {day: dict(values, mean_net_return=values['sum_net_return'] / values['n_sessions'])
             for day, values in sorted(days.items())}
    day_returns = [values['mean_net_return'] for values in daily.values()]
    return {'n_sessions': len(returns), 'n_days': len(days),
            'n_signals': sum(signal_directions.values()), 'n_trades': len(trade_returns),
            'unfilled': unfilled, 'missing_exits': missing_exits,
            'win_rate': len(wins) / len(trade_returns) if trade_returns else None,
            'payoff_ratio': statistics.mean(wins) / -statistics.mean(losses) if wins and losses else None,
            'profit_factor': sum(wins) / -sum(losses) if losses else None,
            'mean_net_return': statistics.mean(returns) if returns else None,
            'mean_trade_return': statistics.mean(trade_returns) if trade_returns else None,
            'trading_day_mean_return': statistics.mean(day_returns) if day_returns else None,
            'worst_day': min(day_returns) if day_returns else None,
            'direction_counts': directions, 'signal_direction_counts': signal_directions,
            'by_day': daily}


def replay(dataset_paths):
    datasets, inputs, seen = [], [], set()
    for root in dataset_paths:
        dataset = Dataset(root)
        pairs = list(paired_sessions(dataset))
        for key, _ in pairs:
            if key in seen:
                raise DatasetError('duplicate symbol/session across datasets: %s %s' % key)
            seen.add(key)
        if not pairs:
            raise DatasetError('dataset has no paired sessions: ' + str(root))
        datasets.append((dataset, pairs))
        inputs.append({'dataset': dataset.name, 'role': dataset.manifest.get('role'),
                       'pinned_by': dataset.pinned_by, 'fingerprint': dataset.fingerprint,
                       'manifest_sha256': sha256_file(dataset.root / 'manifest.json'),
                       'cases_sha256': sha256_file(dataset.root / 'cases.json'),
                       'n_sessions': len(pairs), 'n_cases': len(dataset.cases)})
    if not datasets:
        raise ValueError('at least one dataset is required')
    fills = {'primary': FillModel(), 'stress': FillModel(slippage_fraction=0.5)}
    records = {candidate: [] for candidate in CANDIDATES}
    for dataset, pairs in datasets:
        for (symbol, day), cases in pairs:
            session = default_session(day, cases['LONG'].session_close)
            underlying = session_bars(dataset, 'underlying', symbol, session)
            options = {direction: session_bars(dataset, 'option', case.contract, session)
                       for direction, case in cases.items()}
            for candidate in CANDIDATES:
                signal = find_signal(underlying, session, candidate)
                exit_decision = exit_signal(underlying, session, signal) if signal else None
                record = {'dataset': dataset.name, 'symbol': symbol, 'trade_date': day,
                          'contract': cases[signal.direction].contract if signal else None,
                          'signal': {key: value.isoformat() if isinstance(value, datetime) else value
                                     for key, value in asdict(signal).items()} if signal else None,
                          'exit_decision': {'time': exit_decision[0].isoformat(), 'reason': exit_decision[1]}
                                           if exit_decision else None}
                for cost, fill in fills.items():
                    record[cost] = option_trade(options[signal.direction] if signal else [],
                                                session, signal, exit_decision, fill)
                records[candidate].append(record)
    root = Path(__file__).resolve().parents[2]
    code_paths = [Path(__file__).resolve(), Path(__file__).with_name('signals.py').resolve(),
                  root / 'custody' / 'dataset.py', root / 'custody' / 'evaluate.py',
                  root / 'custody' / 'marketdata.py', root / 'custody' / 'models.py']
    prereg = Path(__file__).with_name('notes') / 'OR1_PREREG.md'
    return {'verdict': 'DIAGNOSTIC', 'created_at': datetime.now(timezone.utc).isoformat(),
            'inputs': inputs, 'code_sha256': {str(path.relative_to(root)): sha256_file(path)
                                           for path in code_paths},
            'preregistration_sha256': sha256_file(prereg),
            'cost_models': {cost: asdict(fill) for cost, fill in fills.items()},
            'limitations': [
                '全部本地数据已用于历史研究；本报告不是新的样本外证据。',
                '成交使用真实期权 OHLCV 的不利滑点估计，不是历史 bid/ask；入场与退出最多等 2 分钟。',
                '缺退出计零期权价值、收取已执行入场手续费，并保留在全部收益统计中。',
                'mean_net_return 为全部标的日等权；trading_day_mean_return 为先按日平均、再对日期等权。',
                '未实现未来选择/验证的样本门槛、重抽置信区间或验证锁，不能据本轮排名授予 ACCEPT。'],
            'candidates': {candidate: {'verdict': 'DIAGNOSTIC',
                                        **{cost: summarize(rows, cost) for cost in fills},
                                        'sessions': rows}
                           for candidate, rows in records.items()}}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset', action='append', required=True)
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args(argv)
    if args.out.exists():
        parser.error('refusing to overwrite report: ' + str(args.out))
    report = replay(args.dataset)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open('x', encoding='utf-8') as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2, allow_nan=False)
        handle.write('\n')
    print(json.dumps({'verdict': report['verdict'], 'out': str(args.out)}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
