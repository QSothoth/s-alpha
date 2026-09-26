"""OR4: fixed-input, independent-leg OHLC accounting diagnostic; never a combo quote."""
from collections import Counter, defaultdict, deque
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
import argparse
import json
from math import fsum
from pathlib import Path
import resource
from statistics import mean
import time
from types import SimpleNamespace

from custody.dataset import Dataset, DatasetError, default_session, sha256_file
from custody.evaluate import FillModel
from .context_replay import iter_days
from .context_stats import _bootstrap
from .replay import option_trade, paired_sessions, session_bars

REPO = Path(__file__).resolve().parents[2]
DATA = REPO / 'data'
PREREG_SHA256 = 'aa643cc0339a904f29d0877907910ff36d46066f01319dc281e21d421376d750'
PINS = {
    'custody-0dte-v5': ('CHECKSUMS.sha256', '35875e44318c78ab5b09cd53cac3b22ce26a8a12cb468aeed5efd72e43e97c69'),
    'custody-eval-2026-09-18-v2': ('manifest.json', 'ac1091d4eddf18505668b1651709b1c9a4a7aa248fda495de272bfaf7a363736'),
    'preopen-us-k5-valid-v1': ('CHECKSUMS.sha256', '992ad5f444b9eb36de05a15cd882e28e68466eca1769f5917e9704e673f73da0'),
}
V2_TAPE_PIN = ('CHECKSUMS.sha256', 'fba36ab960189e6fe80660629455774627915d1b8982361a324ec203892fc2c0')
CANDIDATES = ('S10_CONTROL', 'P20_125')
EXPECTED_COUNTS = (77, 21, 15)
FILLS = {'primary': FillModel(), 'stress': FillModel(slippage_fraction=0.5)}


def load_inputs():
    inputs, sessions, seen = [], [], set()
    for name, (pin, digest) in PINS.items():
        if sha256_file(DATA / name / pin) != digest:
            raise ValueError('unregistered input fingerprint: ' + name)
        inputs.append({'dataset': name, 'pinned_by': pin, 'fingerprint': digest})
        if name == 'preopen-us-k5-valid-v1':
            continue
        tape_pin, tape_digest = V2_TAPE_PIN if name == 'custody-eval-2026-09-18-v2' else (pin, digest)
        if sha256_file(DATA / name / tape_pin) != tape_digest:
            raise ValueError('unregistered option tape fingerprint: ' + name)
        dataset = Dataset(DATA / name)
        if dataset.pinned_by != tape_pin or dataset.fingerprint != tape_digest:
            raise ValueError('option dataset changed its registered pin mechanism')
        inputs[-1].update(tape_pinned_by=tape_pin, tape_fingerprint=tape_digest,
                          manifest_sha256=sha256_file(dataset.root / 'manifest.json'),
                          cases_sha256=sha256_file(dataset.root / 'cases.json'))
        for key, pair in paired_sessions(dataset):
            if key in seen:
                raise ValueError('duplicate symbol/session across datasets')
            seen.add(key)
            sessions.append((key, dataset, pair))
    if (len(seen), len({d for s, d in seen}), len({s for s, d in seen})) != EXPECTED_COUNTS:
        raise ValueError('OR4 requires the fixed 77 sessions / 21 dates / 15 symbols')
    root = DATA / 'preopen-us-k5-valid-v1'
    pins = {}
    for line in (root / 'CHECKSUMS.sha256').read_text().splitlines():
        digest, name = line.split(maxsplit=1)
        name = name.strip().lstrip('*')
        if name in pins or not (root / name).resolve().is_relative_to(root.resolve()):
            raise ValueError('invalid history checksum entry')
        pins[name] = digest
    required = ['manifest.json'] + ['k5/' + s.removeprefix('US.') + '.csv' for s in sorted({s for s, d in seen})]
    for name in required:
        if name not in pins or sha256_file(root / name) != pins[name]:
            raise ValueError('history checksum mismatch: ' + name)
    inputs[-1]['files_sha256'] = {name: pins[name] for name in required}
    return sorted(sessions, key=lambda row: (row[0][1], row[0][0])), inputs


def prior_histories(keys, root):
    """One file/day at a time, twenty scalars per rolling window; never use today's r."""
    requested, result, coverage = defaultdict(list), {}, {}
    for symbol, day in keys:
        requested[symbol].append(day)
    for symbol, target_dates in sorted(requested.items()):
        targets = deque(sorted(set(target_dates)))
        window, counts = deque(maxlen=20), Counter()
        path = Path(root) / 'k5' / (symbol.removeprefix('US.') + '.csv')
        for day, _, bars, reason in iter_days(path, symbol.removeprefix('US.')):
            while targets and targets[0] <= day:
                result[(symbol, targets.popleft())] = list(window)
            if not targets:
                break
            if reason:
                counts[reason] += 1
                continue
            window.append((day, bars[74].close / bars[5].close - 1))
            counts['complete_days'] += 1
        for day in targets:
            result[(symbol, day)] = list(window)
        coverage[symbol] = dict(counts)
    return result, coverage


def observe(underlying, options, history, session, strike):
    at = session.opens.replace(hour=10, minute=0)
    reasons = []
    if session.closes != session.opens.replace(hour=16, minute=0):
        reasons.append('NON_REGULAR_SESSION')
    if len(history) != 20:
        reasons.append('INSUFFICIENT_HISTORY')
    if any(day >= session.day for day, _ in history) or len({day for day, _ in history}) != len(history):
        raise ValueError('history must be distinct days strictly before today')
    spot = next((b.close for b in underlying if b.close_time == at), None)
    if spot is None:
        reasons.append('MISSING_UNDERLYING')
    quotes = {d: next((b.close for b in options[d] if b.close_time == at and b.volume > 0 and b.close > 0), None)
              for d in ('LONG', 'SHORT')}
    reasons += ['MISSING_1000_' + ('CALL' if d == 'LONG' else 'PUT') for d, price in quotes.items() if price is None]
    scale = fsum(abs(spot * (1 + r) - strike) for _, r in history) / 20 if not reasons else None
    price = sum(quotes.values()) + 4 * FILLS['primary'].fee_per_contract / FILLS['primary'].multiplier if not reasons else None
    return {'eligible': not reasons, 'reasons': reasons, 'decision_time': at.isoformat(),
            'history_dates': [day for day, _ in history], 'spot': spot, 'strike': strike,
            'leg_closes_1000': quotes, 'M': scale, 'P': price,
            'passes_price_filter': not reasons and scale > 1.25 * price}


def group_trade(options, session, emit, fill):
    at = session.opens.replace(hour=10, minute=0)
    entries = sum(any(at + timedelta(minutes=1) <= b.close_time <= at + timedelta(minutes=2)
                      and b.volume > 0 and b.close > 0 for b in options[d]) for d in ('LONG', 'SHORT')) if emit else 0
    exit_at = at + timedelta(minutes=2) if entries == 1 else at.replace(hour=15, minute=45)
    legs = {}
    for direction, right in (('LONG', 'CALL'), ('SHORT', 'PUT')):
        signal = SimpleNamespace(time=at, direction=direction) if emit else None
        leg = option_trade(options[direction], session, signal,
                           (exit_at, 'partial_entry_unwind' if entries == 1 else 'fixed_1545'), fill)
        leg.pop('direction')
        leg.update(right=right, position='BOUGHT_OPTION')
        leg['proxy_net_pnl'] = leg.pop('net_pnl')
        leg['proxy_net_return'] = leg.pop('net_return')
        missing = leg['outcome'] == 'MISSING_EXIT'
        leg['observed_net_pnl'] = None if missing else leg['proxy_net_pnl']
        leg['observed_net_return'] = None if missing else leg['proxy_net_return']
        legs[right] = leg
    missing = sum(leg['outcome'] == 'MISSING_EXIT' for leg in legs.values())
    paid = fsum(leg['entry']['price'] * fill.multiplier for leg in legs.values() if leg['entry'])
    pnl = fsum(leg['proxy_net_pnl'] for leg in legs.values())
    outcome = ('NO_SIGNAL' if not emit else 'UNFILLED' if not entries else 'PARTIAL_ENTRY'
               if entries == 1 else 'MISSING_EXIT' if missing else 'COMPLETED')
    return {'outcome': outcome, 'signal': emit, 'entered_legs': entries, 'missing_exit_legs': missing,
            'exit_decision_time': exit_at.isoformat() if entries else None,
            'cancel_unfilled_leg_at': (at + timedelta(minutes=2)).isoformat() if entries == 1 else None,
            'paid_premium': paid, 'proxy_net_pnl': pnl, 'proxy_net_return': pnl / paid if paid else 0.0,
            'observed_net_pnl': None if missing else pnl,
            'observed_net_return': None if missing else pnl / paid if paid else 0.0, 'legs': legs}


def _metrics(values):
    wins, losses = [v for v in values if v > 0], [v for v in values if v < 0]
    profit, loss = fsum(wins), -fsum(losses)
    return {'n_trades': len(values), 'mean_trade_return': mean(values) if values else None,
            'win_rate': len(wins) / len(values) if values else None,
            'payoff_ratio': mean(wins) / -mean(losses) if wins and losses else None,
            'profit_factor': profit / loss if loss else None,
            'positive_profit_without_losses': profit > 0 and loss == 0}


def summarize(records, cost):
    by_day, reasons = {}, Counter()
    counts = Counter(dict.fromkeys(('INELIGIBLE', 'FILTERED', 'UNFILLED', 'PARTIAL_ENTRY',
                                     'MISSING_EXIT', 'COMPLETED', 'eligible', 'signals',
                                     'missing_exit_legs', 'missing_exit_groups'), 0))
    for record in records:
        trade = record[cost]
        day = by_day.setdefault(record['trade_date'], {'n_sessions': 0, 'trades': 0, 'net_sum': 0.0, 'returns': []})
        day['n_sessions'] += 1
        day['net_sum'] += trade['proxy_net_return']
        counts[trade['outcome']] += 1
        counts['eligible'] += record['observation']['eligible']
        counts['signals'] += trade['signal']
        counts['missing_exit_legs'] += trade['missing_exit_legs']
        counts['missing_exit_groups'] += trade['missing_exit_legs'] > 0
        reasons.update(record['observation']['reasons'])
        if trade['entered_legs']:
            day['trades'] += 1
            day['returns'].append(trade['proxy_net_return'])
    dates = sorted(by_day)
    for day in by_day.values():
        day['day_mean'] = day['net_sum'] / day['n_sessions']
    values = [value for day in dates for value in by_day[day]['returns']]
    observed = [r[cost]['observed_net_return'] for r in records
                if r[cost]['entered_legs'] and r[cost]['observed_net_return'] is not None]
    summary = _metrics(values)
    summary.update(n_sessions=len(records), n_days=len(dates), counts=dict(counts),
                   ineligibility_reasons=dict(reasons), trading_days=sum(by_day[d]['trades'] > 0 for d in dates),
                   coverage=len(values) / len(records) if records else 0.0,
                   mean_all_sessions_return=fsum(values) / len(records) if records else None,
                   day_equal_mean_return=mean(by_day[d]['day_mean'] for d in dates) if dates else None,
                   by_day=by_day, observed_complete_groups_descriptive=_metrics(observed),
                   halves={name: {'dates': subset, **_metrics([v for d in subset for v in by_day[d]['returns']])}
                           for name, subset in (('early', dates[:len(dates)//2]), ('late', dates[len(dates)//2:]))},
                   **_bootstrap([by_day[d] for d in dates]))
    return summary


def candidate_status(primary, stress):
    positive = lambda value: value is not None and value > 0
    pf_ok = primary['positive_profit_without_losses'] or (
        primary['profit_factor'] is not None and primary['profit_factor'] >= 1.2)
    gates = {'at_least_60_trading_days': primary['trading_days'] >= 60,
             'at_least_100_trades': primary['n_trades'] >= 100,
             'positive_net_mean': positive(primary['mean_trade_return']),
             'positive_lower_95': positive(primary['net_mean_lower_95_bp']),
             'primary_profit_factor_at_least_1_2': pf_ok,
             'positive_early_half': positive(primary['halves']['early']['mean_trade_return']),
             'positive_late_half': positive(primary['halves']['late']['mean_trade_return']),
             'positive_stress_mean': positive(stress['mean_trade_return'])}
    status = ('NO_EVIDENCE' if not primary['n_trades'] else 'FAILED_PROXY'
              if not (gates['positive_net_mean'] and pf_ok and gates['positive_stress_mean']) else 'UNCONFIRMED_PROXY')
    return status, gates


def replay():
    started = time.monotonic()
    prereg = Path(__file__).with_name('notes') / 'OR4_PREREG.md'
    if sha256_file(prereg) != PREREG_SHA256:
        raise ValueError('OR4 preregistration changed')
    code = ['studies/us_opening_range/' + name for name in
            ('pricing_replay.py', 'replay.py', 'signals.py', 'context_replay.py', 'context_signals.py', 'context_stats.py')]
    code += ['custody/' + name for name in ('__init__.py', 'dataset.py', 'evaluate.py', 'marketdata.py', 'models.py', 'registry.py', 'strategy.py')]
    hashes = {name: sha256_file(REPO / name) for name in code}
    sessions, inputs = load_inputs()
    histories, coverage = prior_histories([key for key, _, _ in sessions], DATA / 'preopen-us-k5-valid-v1')
    records = {candidate: [] for candidate in CANDIDATES}
    for (symbol, day), dataset, pair in sessions:
        session = default_session(day, pair['LONG'].session_close)
        errors, options = [], {}
        underlying = session_bars(dataset, 'underlying', symbol, session)
        for direction, case in pair.items():
            try:
                options[direction] = session_bars(dataset, 'option', case.contract, session)
            except DatasetError as exc:
                if not str(exc).startswith('no traded option bars: '):
                    raise
                options[direction] = []
                errors.append(str(exc))
        observation = observe(underlying, options, histories[(symbol, day)], session, pair['LONG'].strike)
        for candidate in CANDIDATES:
            emit = observation['eligible'] and (candidate == 'S10_CONTROL' or observation['passes_price_filter'])
            record = {'dataset': dataset.name, 'symbol': symbol, 'trade_date': day,
                      'contracts': {d: c.contract for d, c in pair.items()}, 'observation': observation, 'data_errors': errors}
            for cost, fill in FILLS.items():
                record[cost] = group_trade(options, session, emit, fill)
                if not emit:
                    record[cost]['outcome'] = 'FILTERED' if observation['eligible'] else 'INELIGIBLE'
            records[candidate].append(record)
    candidates = {name: {cost: summarize(rows, cost) for cost in FILLS} | {'sessions': rows}
                  for name, rows in records.items()}
    for result in candidates.values():
        result['proxy_status'], result['formal_gates_descriptive'] = candidate_status(result['primary'], result['stress'])
    return {'verdict': 'DIAGNOSTIC_ONLY', 'selected_for_further_testing': None,
            'P20_125_status': candidates['P20_125']['proxy_status'],
            'created_at': datetime.now(timezone.utc).isoformat(), 'preregistration_sha256': PREREG_SHA256,
            'inputs': inputs, 'code_sha256': hashes, 'cost_models': {k: asdict(v) for k, v in FILLS.items()},
            'history_coverage': coverage, 'candidates': candidates,
            'limitations': ['旧21天/77标的日，仅否证诊断；非独立验证，无胜出策略，不启用新留出。',
                            '双腿独立成交K线会计代理，不是组合盘口、原子成交或可实现收益保证。',
                            'M是历史终点内在价值尺度，非校准分布/公允价；不包含退出时剩余时间价值。',
                            'proxy收益含缺出口零残值假设；observed仅表示出口K线可用，仍是FillModel代理而非真实执行。',
                            '缺出口的observed记null，完整观察子集只作描述，不能替代全会话统计。',
                            '100乘数与每边0.65美元是既有模型假设，未逐合约核实乘数或券商全包收费。',
                            '旧K5导出时间标签缺独立溯源；完整日排除为事后数据质量条件。',
                            '日期重抽未校正跨日依赖、多轮研究搜索；21天先天不满足60天/100笔门槛。'],
            'resources': {'elapsed_seconds': time.monotonic() - started,
                          'peak_rss_kib': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss}}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args(argv)
    if args.out.exists():
        parser.error('refusing to overwrite report: ' + str(args.out))
    report = replay()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open('x', encoding='utf-8') as handle:
        json.dump(report, handle, indent=2, ensure_ascii=False, allow_nan=False)
        handle.write('\n')
    print(json.dumps({key: report[key] for key in ('verdict', 'P20_125_status', 'resources')}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
