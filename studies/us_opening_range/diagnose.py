"""Attribute the existing OR1 trades without rerunning or selecting any signals."""
from __future__ import annotations

import argparse
import json
import math
import statistics
from collections import Counter, defaultdict
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from custody.dataset import Dataset, DatasetError, default_session, sha256_file
from custody.evaluate import FillModel
from custody.models import instant

from .replay import paired_sessions, session_bars


def _equal(actual, expected, field):
    if not math.isclose(actual, expected, rel_tol=1e-10, abs_tol=1e-9):
        raise DatasetError('fixed-report reconciliation failed: ' + field)


def _bar(bars, when):
    try:
        return bars[instant(when)]
    except KeyError as exc:
        raise DatasetError('no exact observed bar at ' + str(when)) from exc


def decompose(trade, underlying, option, fill, direction):
    """Only COMPLETED trades have observable same-time option return attribution."""
    result = {'outcome': trade['outcome'], 'original_net_pnl': trade['net_pnl'],
              'original_net_return': trade['net_return'], 'observed': None,
              'missing_exit_assumption': None}
    if trade['entry'] is None:
        if trade['outcome'] not in ('NO_SIGNAL', 'UNFILLED'):
            raise DatasetError('unexpected unentered outcome')
        _equal(trade['net_pnl'], 0, 'unentered net pnl')
        _equal(trade['net_return'], 0, 'unentered net return')
        return result
    entry = trade['entry']
    entry_bar = _bar(option, entry['time'])
    _equal(entry['price'], fill.buy(entry_bar), 'entry price')
    denominator = entry['price'] * fill.multiplier
    result.update(entry_time=entry['time'], denominator_dollars=denominator,
                  option_entry_close=entry_bar.close)
    if trade['outcome'] == 'MISSING_EXIT':
        if trade['exit']['time'] is not None or not trade['exit']['assumed_zero_value']:
            raise DatasetError('missing exit must be explicitly unobserved')
        assumed_pnl = -denominator - fill.fee_per_contract
        _equal(trade['net_pnl'], assumed_pnl, 'assumed missing-exit pnl')
        _equal(trade['net_return'], assumed_pnl / denominator, 'assumed missing-exit return')
        result['missing_exit_assumption'] = {
            'observed_exit_price': None, 'observed_option_return': None,
            'assumed_net_pnl': assumed_pnl, 'assumed_net_return': assumed_pnl / denominator,
            'note': '既有报告的归零压力假设，不是观察到的成交或最终价值。'}
        return result
    if trade['outcome'] != 'COMPLETED' or trade['exit']['assumed_zero_value']:
        raise DatasetError('unexpected entered outcome')
    exit_ = trade['exit']
    exit_bar = _bar(option, exit_['time'])
    if instant(exit_['time']) <= instant(entry['time']):
        raise DatasetError('exit must follow entry')
    _equal(exit_['price'], fill.sell(exit_bar), 'exit price')
    stock_entry, stock_exit = _bar(underlying, entry['time']), _bar(underlying, exit_['time'])
    sign = 1 if direction == 'LONG' else -1
    stock_return = sign * (stock_exit.close / stock_entry.close - 1)
    option_return = exit_bar.close / entry_bar.close - 1
    components = {
        'price_movement': (exit_bar.close - entry_bar.close) * fill.multiplier,
        'slippage': ((exit_['price'] - exit_bar.close)
                     - (entry['price'] - entry_bar.close)) * fill.multiplier,
        'fees': -2 * fill.fee_per_contract,
    }
    reconstructed = sum(components.values())
    _equal(trade['net_pnl'], reconstructed, 'completed net pnl')
    _equal(trade['net_return'], reconstructed / denominator, 'completed net return')
    category = ('underlying_negative' if stock_return < 0 else
                'underlying_flat' if stock_return == 0 else
                'underlying_positive_option_negative' if option_return < 0 else
                'underlying_positive_option_flat' if option_return == 0 else
                'underlying_positive_option_positive')
    result['observed'] = {
        'entry_time': entry['time'], 'exit_time': exit_['time'],
        'underlying_entry_close': stock_entry.close, 'underlying_exit_close': stock_exit.close,
        'underlying_signed_return': stock_return,
        'option_entry_close': entry_bar.close, 'option_exit_close': exit_bar.close,
        'option_close_to_close_return': option_return, 'category': category,
        'components_dollars': components,
        'components_original_denominator': {key: value / denominator for key, value in components.items()},
        'reconciliation_error_dollars': reconstructed - trade['net_pnl'],
    }
    return result


def _mean(values):
    return statistics.mean(values) if values else None


def summarize(rows, cost, original):
    trades = [row[cost] for row in rows]
    observed = [trade['observed'] for trade in trades if trade['observed'] is not None]
    missing = [trade for trade in trades if trade['outcome'] == 'MISSING_EXIT']
    components = {key: sum(row['components_dollars'][key] for row in observed)
                  for key in ('price_movement', 'slippage', 'fees')}
    missing_pnl = sum(trade['original_net_pnl'] for trade in missing)
    all_pnl = sum(trade['original_net_pnl'] for trade in trades)
    _equal(sum(components.values()) + missing_pnl, all_pnl, 'all-session pnl')
    _equal(_mean([trade['original_net_return'] for trade in trades]),
           original['mean_net_return'], 'all-session mean return')
    _equal(sum(trade['outcome'] in ('COMPLETED', 'MISSING_EXIT') for trade in trades),
           original['n_trades'], 'original trade count')
    return {
        'original_all_session_summary': original,
        'outcome_counts': dict(Counter(trade['outcome'] for trade in trades)),
        'completed_same_times_descriptive_only': {
            'n': len(observed),
            'mean_underlying_signed_return': _mean([row['underlying_signed_return'] for row in observed]),
            'mean_option_close_to_close_return': _mean([row['option_close_to_close_return'] for row in observed]),
            'mean_original_net_return': _mean([trade['original_net_return'] for trade in trades
                                              if trade['observed'] is not None]),
            'category_counts': dict(Counter(row['category'] for row in observed)),
            'sum_components_dollars': components,
            'mean_components_original_denominator': {
                key: _mean([row['components_original_denominator'][key] for row in observed])
                for key in components},
        },
        'all_session_reconciliation': {
            'completed_observed_components_dollars': components,
            'missing_exit_n': len(missing), 'missing_exit_assumed_net_pnl': missing_pnl,
            'original_net_pnl': all_pnl,
            'error_dollars': sum(components.values()) + missing_pnl - all_pnl,
            'max_completed_trade_error_dollars': max(
                (abs(row['reconciliation_error_dollars']) for row in observed), default=0.0),
        },
    }


def diagnose(report_path, dataset_paths):
    report_path = Path(report_path)
    source = json.loads(report_path.read_text(encoding='utf-8'))
    if source['verdict'] != 'DIAGNOSTIC':
        raise DatasetError('an existing diagnostic report is required')
    fills = {cost: FillModel(**values) for cost, values in source['cost_models'].items()}
    pinned = {item['dataset']: item for item in source['inputs']}
    datasets = {}
    for path in dataset_paths:
        dataset = Dataset(path)
        if dataset.name not in pinned or dataset.name in datasets:
            raise DatasetError('unexpected or duplicate dataset: ' + dataset.name)
        reference = pinned[dataset.name]
        for field, actual in (('fingerprint', dataset.fingerprint),
                              ('manifest_sha256', sha256_file(dataset.root / 'manifest.json')),
                              ('cases_sha256', sha256_file(dataset.root / 'cases.json'))):
            if actual != reference[field]:
                raise DatasetError('report input mismatch: ' + dataset.name + ' ' + field)
        datasets[dataset.name] = dataset
    if set(datasets) != set(pinned):
        raise DatasetError('all original datasets are required')
    groups = defaultdict(list)
    expected = {(dataset.name, symbol, day) for dataset in datasets.values()
                for (symbol, day), _ in paired_sessions(dataset)}
    for candidate, data in source['candidates'].items():
        keys = [(row['dataset'], row['symbol'], row['trade_date']) for row in data['sessions']]
        if len(keys) != len(set(keys)) or set(keys) != expected:
            raise DatasetError('fixed report must retain every source session exactly once')
        for key, row in zip(keys, data['sessions']):
            groups[key].append((candidate, row))
    results = {candidate: [] for candidate in source['candidates']}
    for name, dataset in datasets.items():
        for (symbol, day), cases in paired_sessions(dataset):
            session = default_session(day, cases['LONG'].session_close)
            underlying = {bar.close_time: bar for bar in session_bars(dataset, 'underlying', symbol, session)}
            options = {case.contract: {bar.close_time: bar for bar in
                                      session_bars(dataset, 'option', case.contract, session)}
                       for case in cases.values()}
            for candidate, record in groups[(name, symbol, day)]:
                signal = record['signal']
                item = {key: record[key] for key in ('dataset', 'symbol', 'trade_date', 'contract')}
                item['signal_to_exit_decision'] = None
                if signal:
                    if signal['direction'] not in cases or record['contract'] != cases[signal['direction']].contract:
                        raise DatasetError('signal direction and fixed contract disagree')
                    start = _bar(underlying, signal['time'])
                    end = _bar(underlying, record['exit_decision']['time'])
                    _equal(start.close, signal['price'], 'signal reference price')
                    sign = 1 if signal['direction'] == 'LONG' else -1
                    item['signal_to_exit_decision'] = {
                        'signal_time': signal['time'], 'exit_decision_time': record['exit_decision']['time'],
                        'direction': signal['direction'], 'underlying_entry_close': start.close,
                        'underlying_exit_close': end.close, 'signed_return': sign * (end.close / start.close - 1)}
                for cost, fill in fills.items():
                    item[cost] = decompose(record[cost], underlying, options.get(record['contract'], {}),
                                           fill, signal['direction'] if signal else None)
                results[candidate].append(item)
    candidates = {}
    for candidate, rows in results.items():
        values = [row['signal_to_exit_decision']['signed_return'] for row in rows
                  if row['signal_to_exit_decision'] is not None]
        candidates[candidate] = {
            'signal_to_exit_decision': {'n': len(values), 'mean_signed_return': _mean(values),
                                        'positive': sum(value > 0 for value in values),
                                        'flat': sum(value == 0 for value in values),
                                        'negative': sum(value < 0 for value in values)},
            **{cost: summarize(rows, cost, source['candidates'][candidate][cost]) for cost in fills},
            'sessions': rows,
        }
    root = Path(__file__).resolve().parents[2]
    code = ['studies/us_opening_range/diagnose.py', 'studies/us_opening_range/replay.py',
            'custody/dataset.py', 'custody/evaluate.py', 'custody/marketdata.py', 'custody/models.py']
    return {
        'verdict': 'FIXED_TRADE_DIAGNOSTIC', 'created_at': datetime.now(timezone.utc).isoformat(),
        'source_report': {'path': str(report_path), 'sha256': sha256_file(report_path)},
        'inputs': source['inputs'], 'source_code_sha256': source['code_sha256'],
        'code_sha256': {path: sha256_file(root / path) for path in code},
        'cost_models': {cost: asdict(fill) for cost, fill in fills.items()},
        'limitations': [
            '信号、合约、成交及退出时刻全部固定；没有重新选择策略或参数。',
            '仅完整成交交易具有同时间窗口的可观察正股及期权毛收益；该子集仅作描述。',
            'close/close 毛收益以期权入场分钟收盘价为分母；分解各项以原不利滑点入场权利金为分母。',
            '缺退出仍计入原全部净统计；其归零损失只是原报告的保守假设，不是观察到的实际归零。',
            '没有历史 Greeks、IV 或可执行双边报价，不能把正股方向正确而期权下跌归因于 theta 或 IV。'],
        'candidates': candidates,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', required=True, type=Path)
    parser.add_argument('--dataset', action='append', required=True)
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args(argv)
    if args.out.exists():
        parser.error('refusing to overwrite report: ' + str(args.out))
    report = diagnose(args.report, args.dataset)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open('x', encoding='utf-8') as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2, allow_nan=False)
        handle.write('\n')
    print(json.dumps({'verdict': report['verdict'], 'out': str(args.out)}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
