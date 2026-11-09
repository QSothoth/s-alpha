"""Evaluation-only holding funnel and execution bench; no labels reach execution."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from contextvars import ContextVar
import importlib
import hashlib
import json
import os
from pathlib import Path
import sys

import numpy as np

from . import mainleg

LAYERS = dict(L0='不在池', L1='未点名', L2='未触发', L3='未成交',
              L4='买晚', L5='早买后被洗', L6='早买且峰前持有')
_EXECUTING = ContextVar('funnel_executing', default=False)


def load_frozen(directory, version, code_fingerprints, data_fingerprint, *, line=None):
    """Read a frozen cache only after checking identity and every payload SHA."""
    directory = Path(directory)
    with (directory / 'manifest.json').open() as stream:
        manifest = json.load(stream)
    if (manifest.get('version') != version or (line is not None and manifest.get('line') != line) or
            manifest.get('code_fingerprints') != code_fingerprints or
            manifest.get('data_fingerprint') != data_fingerprint):
        raise ValueError('frozen cache version or fingerprint mismatch')
    files = manifest.get('files')
    if not isinstance(files, dict) or not files:
        raise ValueError('frozen cache has no payload files')
    result = {}
    for name, expected in files.items():
        if Path(name).name != name or not name.endswith('.json'):
            raise ValueError('invalid frozen cache filename')
        path = directory / name
        digest = hashlib.sha256()
        with path.open('rb') as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                digest.update(chunk)
        if digest.hexdigest() != expected:
            raise ValueError('frozen cache payload SHA mismatch: '+name)
        with path.open() as stream:
            result[name] = json.load(stream)
    return result


def _label_guard(event, args):
    if _EXECUTING.get() and event == 'open' and not isinstance(args[0], int):
        name = os.fsdecode(args[0])
        if any(word in name for word in ('trades.csv', 'legs_frozen', 'scorecard', 'labels', 'targets')):
            raise PermissionError('evaluation input requested by execution')


sys.addaudithook(_label_guard)


class Prices:
    def __init__(self, A):
        self.A, self.ci = A, {str(c): j for j, c in enumerate(A['codes'])}

    def __getitem__(self, code):
        return {short: self.A[key][:, self.ci[code]] for short, key in
                (('o', 'open'), ('h', 'high'), ('l', 'low'), ('c', 'close'))}


def holding_coverage(A, record, rules, legs):
    """Exact H1 first-lot clock and P5 peak-eve shares, including late holdings."""
    calendar = list(map(str, A['days']))
    di, normalized = {d: t for t, d in enumerate(calendar)}, []
    for tid, trade in enumerate(record['trades']):
        if trade['side'] < 0:
            continue
        fills = []
        for event in trade['executions']:
            buy = event['action'] in ('entry', 'add')
            fills.append(dict(index=di[event['time']], quantity=event['shares']*(1 if buy else -1),
                price=event['price'], fee=event['shares']*event['price']*(rules.buy_cost if buy else rules.sell_cost),
                open=event['action'] == 'end'))
        normalized.append(dict(id=tid, code=trade['code'], entry=di[trade['entry']],
            closed=trade['why'] != 'end', pnl=trade['pnl'], lots=mainleg.lots(fills, trade['pnl'])))
    rows = mainleg.attribute_lots(normalized, legs, Prices(A), calendar)
    coverage = mainleg.account_coverage(rows, legs, calendar)
    equity = dict(zip(record['curve']['days'], record['curve']['equity']))
    last = record['curve']['days'][-1]
    ci = {str(c): j for j, c in enumerate(A['codes'])}
    for g, row in zip(legs, coverage):
        eve = calendar[g['peak']-1]
        shares = None
        if eve <= last:
            shares = sum(e['shares']*(1 if e['action'] in ('entry', 'add') else -1)
                for t in record['trades'] if t['side'] > 0 and t['code'] == g['code'] and t['entry'] <= eve
                for e in t['executions'] if e['time'] <= eve and e['action'] != 'end')
        weight = None
        if shares is not None and shares > 1e-10 and equity.get(eve, 0) > 0:
            weight = max(0., shares)*float(A['close'][g['peak']-1, ci[g['code']]])/equity[eve]
        row.update(peak_eve=eve, peak_shares=max(0., shares) if shares is not None else None,
            peak_held=shares > 1e-10 if shares is not None else None, peak_weight=weight)
    return coverage


def trade_stats(trades):
    closed = [t for t in trades if t['why'] != 'end']
    wins, losses = [t['ret'] for t in closed if t['ret'] > 0], [t['ret'] for t in closed if t['ret'] <= 0]
    return dict(n=len(trades), closed=len(closed), win=len(wins)/len(closed) if closed else None,
        payoff=float(np.mean(wins)/-np.mean(losses)) if wins and losses and np.mean(losses) < 0 else None,
        days=float(np.mean([t['days'] for t in closed])) if closed else None,
        mean_r=float(np.mean([t['r'] for t in closed])) if closed else None,
        pnl=sum(t['pnl'] for t in trades))


def behaviour_gap(stats, card, tolerance):
    gaps = {}
    for key in ('win', 'payoff', 'days', 'n'):
        target = card.get(key)
        value = stats.get(key)
        if target is None or not card.get('sources', {}).get(key):
            continue
        relative = abs(value/target-1) if value is not None and target else None
        gaps[key] = dict(value=value, target=target, relative_gap=relative,
                         within=relative is not None and relative <= tolerance+1e-12,
                         source=card['sources'][key])
    return dict(items=gaps, within=sum(v['within'] for v in gaps.values()), sourced=len(gaps))


def _counts(rows):
    weights = [r['coverage']['peak_weight'] for r in rows if r['coverage']['peak_weight'] is not None]
    return dict(n=len(rows), layers={k: sum(r['layer'] == k for r in rows) for k in LAYERS},
        named=sum(r['signal_hit'] for r in rows), early=sum(r['coverage']['covered'] for r in rows),
        peak_held=sum(r['coverage']['peak_held'] is True for r in rows),
        early_peak_held=sum(r['layer'] == 'L6' for r in rows),
        peak_unknown=sum(r['coverage']['peak_held'] is None for r in rows),
        peak_weight_median=float(np.median(weights)) if weights else None,
        peak_weight_sum=sum(weights), blockers=dict(Counter(r['reason'] for r in rows)))


def measure(A, record, rules, picks, legs, *, pool=None, raw=None, filtered=None,
            offered=None, states=None, cards=None, tolerance=.2, entry_delay=0,
            same_night_only=False, raw_picks=None):
    """A segment is assigned its first failed stage exactly once.

    Historical actual fills are retained even when a diagnostic K=3 projection
    did not nominate them. L6 is the intersection of early and peak-eve holding;
    peak_held separately reproduces P5, which also counts late peak holdings.
    """
    calendar, ci = list(map(str, A['days'])), {str(c): j for j, c in enumerate(A['codes'])}
    di = {d: t for t, d in enumerate(calendar)}
    opens = {g['code']: A['open'][:, ci[g['code']]] for g in legs if g['code'] in ci}
    budget = mainleg.signal_coverage_budget(picks, None, legs, calendar, opens, 3)
    selected = budget['picks']
    coverage = holding_coverage(A, record, rules, legs)
    attempts = defaultdict(list)
    for row in record.get('attempts', []):
        attempts[(di[row['day']], row['code'])].append(row)
    books = []
    for book in (raw, filtered, offered):
        indexed = defaultdict(list)
        for d, row in enumerate(book or []):
            for e in row:
                if e[2] > 0:
                    indexed[(d, e[1])].append(e)
        books.append(indexed)
    per_leg = []
    for g, cov, signal in zip(legs, coverage, budget['per_leg']):
        j, nights = ci.get(g['code']), []
        for t in range(max(0, g['first']-4), min(g['peak']-1, len(calendar)-1)):
            price = float(A['open'][t+1, j]) if j is not None else np.nan
            share = (g['top']/price-1)/g['gain'] if np.isfinite(price) and price > 0 else None
            if share is None or share < .5-1e-12:
                continue
            checks = []
            for d in range(t+entry_delay, min(t+4, len(calendar))):
                tries = attempts.get((d, g['code']), [])
                rs, fs, os = (b.get((d, j), []) for b in books)
                if tries and raw is None:
                    rs, fs, os = rs or tries, fs or tries, os or tries
                reason = ('no_shape' if not rs else 'IDX50' if not fs else 'offer_cap' if not os else
                          ','.join(dict.fromkeys(r['reason'] for r in tries)) if tries else 'no_admission_trace')
                if rs and fs and not os and same_night_only and g['code'] not in picks.get(d, ()):
                    rs, reason = [], 'nomination_not_retained'
                checks.append(dict(day=calendar[d], trigger=bool(rs), filtered=bool(fs), offered=bool(os),
                                   reasons=reason, attempts=tries))
            source_names = (raw_picks or picks).get(t, ())
            raw_rank = source_names.index(g['code'])+1 if g['code'] in source_names else None
            nomination_block = ('named' if g['code'] in selected.get(t, ()) else
                'S_projection_cooldown_or_cap' if g['code'] in picks.get(t, ()) else
                'source_cooldown_or_cap' if raw_rank else 'outside_signal')
            nights.append(dict(night=calendar[t], remaining_share=share, raw_rank=raw_rank,
                nomination_block=nomination_block,
                in_pool=bool(j is not None and (pool is None or pool[t+1, j])),
                nominated=g['code'] in selected.get(t, ()), checks=checks))
        named = [r for r in nights if r['nominated']]
        checks = [c for r in named for c in r['checks']]
        if cov['any']:
            layer = 'L4' if not cov['covered'] else 'L6' if cov['peak_held'] else 'L5'
            reason = LAYERS[layer]
        elif not any(r['in_pool'] for r in nights):
            layer, reason = 'L0', 'pool_or_prices'
        elif not named:
            layer, reason = 'L1', 'not_nominated'
        elif not any(r['trigger'] for r in checks):
            layer, reason = 'L2', 'no_executable_shape'
        else:
            layer = 'L3'
            furthest = max(checks, key=lambda c: (c['offered'], c['filtered'], c['trigger']))
            reason = furthest['reasons']
        state = str(states[g['first']]) if states is not None else 'common'
        first = next((t for t in record['trades'] if t['side'] > 0 and t['code'] == g['code']
                      and cov['first_fill'] and t['entry'] == calendar[cov['first_fill']['index']]), None)
        rapid = bool(first and cov['covered'] and first['why'] in ('stop', 'gap_stop', 'stop_day0') and first['days'] <= 3)
        returned = bool(rapid and any(t['side'] > 0 and t['code'] == g['code']
            and first['exit'] < t['entry'] < calendar[g['peak']] for t in record['trades']))
        per_leg.append(dict(key=g['key'], code=g['code'], year=calendar[g['first']][:4], state=state,
            layer=layer, reason=reason, signal_hit=signal['covered'], coverage=cov, nights=nights,
            rapid_stop=rapid, returned_after_rapid_stop=returned,
            first_trade=None if first is None else {k: first[k] for k in ('entry', 'exit', 'why', 'days', 'fill', 'stop')},
            actual_bypasses_projection=cov['any'] and not signal['covered']))
    annual = {}
    previous = 1.
    for year in sorted({d[:4] for d in record['curve']['days']}):
        eq = [v for d, v in zip(record['curve']['days'], record['curve']['equity']) if d.startswith(year)]
        facts = trade_stats([t for t in record['trades'] if t['entry'].startswith(year)])
        facts['return'], previous = eq[-1]/previous-1, eq[-1]
        annual[year] = dict(_counts([r for r in per_leg if r['year'] == year]), account=facts,
            behaviour_gap=behaviour_gap(facts, (cards or {}).get(year, {}), tolerance),
            by_state={state: _counts([r for r in per_leg if r['year'] == year and r['state'] == state])
                      for state in sorted(set(map(str, states)) if states is not None else {'common'})})
    prior, daily_returns = 1., {}
    for day, value in zip(record['curve']['days'], record['curve']['equity']):
        daily_returns[day], prior = value/prior, value
    for year, summary in annual.items():
        for state, part in summary['by_state'].items():
            selected_days = [d for d in daily_returns if d.startswith(year)
                             and (states is None or str(states[di[d]]) == state)]
            trades = [t for t in record['trades'] if t['entry'].startswith(year)
                      and (states is None or str(states[di[t['entry']]]) == state)]
            part['account'] = dict(trade_stats(trades),
                **{'return': float(np.prod([daily_returns[d] for d in selected_days])-1) if selected_days else None})
    return dict(total=_counts(per_leg), annual=annual, per_leg=per_leg,
        convention='L6=早买且峰前持有；peak_held含晚买，逐位复现P5。实际成交优先于K3诊断投影。',
        layer_lines=dict(selection=['L0', 'L1'], conversion=['L2', 'L3'], trading=['L4', 'L5']))


def bench_nominations(calendar, legs, own_picks):
    """Labels construct test inputs here, never inside the execution callable."""
    his = defaultdict(list)
    for g in legs:
        for t in range(max(0, g['first']-3), min(g['peak'], len(calendar)-1)):
            if g['code'] not in his[t]:
                his[t].append(g['code'])
    combined, controls = {}, {}
    for t in range(len(calendar)-1):
        controls[t] = [c for c in own_picks.get(t, ()) if c not in his[t]]
        # The strategy's frozen order ranks simultaneous nominations; no leg rank is supplied.
        combined[t] = list(dict.fromkeys(list(own_picks.get(t, ()))+sorted(his[t])))
        combined[t] = [c for c in combined[t] if c in his[t] or c in controls[t]]
    return combined, dict(his), controls


def execution_bench(A, legs, own_picks, execute):
    picks, his, control = bench_nominations(A['days'], legs, own_picks)
    # Only known market keys and ordinary ordered nominations cross this boundary.
    market = {k: A[k] for k in ('days', 'codes', 'open', 'high', 'low', 'close', 'e9', 'e21',
                               'e50', 'adr', 'to20', 'idx_pb16', 'index_ok', 'e8_scale',
                               'master_filtered') if k in A}
    token = _EXECUTING.set(True)
    try:
        record, rules = execute(market, picks)
    finally:
        _EXECUTING.reset(token)
    return record, rules, dict(picks=picks, his=his, control=control)


def main(argv=None):
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('command', choices=('status', 'cache'), nargs='?')
    parser.add_argument('--study', required=True)
    parser.add_argument('--system')
    parser.add_argument('--line', choices=('regime', 'selection', 'trading', 'conversion', 'reference'))
    parser.add_argument('--version')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args(argv)
    if not args.study.replace('_', '').isalnum():
        parser.error('invalid study identifier')
    adapter = importlib.import_module('studies.'+args.study+'.workflow.adapter')
    if args.command == 'cache':
        if not args.line or not args.version:
            parser.error('cache requires --line and --version')
        result = adapter.cached(args.line, args.version)
    else:
        result = adapter.status() if args.command == 'status' else adapter.run(args.system)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=1, allow_nan=False)+'\n')
    print(str(args.out))


if __name__ == '__main__':
    main()
