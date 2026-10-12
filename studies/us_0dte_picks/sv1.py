"""SV1 scoring (notes/SV1_PREREG.md): the new session flow against the old one on one validation slice.

    python3 -m studies.us_0dte_picks.sv1 merge --out data/sv1-session-validation \
        --sources data/sv1-session-validation-work data/or-alpha-2026-09-25-holdout-work data/sv1-capture-2026-10-02 ...
    python3 -m studies.us_0dte_picks.sv1 score --dataset data/sv1-session-validation --out studies/us_0dte_picks/reports/sv1.json

New flow N: zero_dte_timing_v6.6 on the CALL and the PUT of every (symbol, day), each side on its own signal.
Old flow O: open_hold_v3 on the opening-gap side only (first 1m open above the previous close = CALL,
below = PUT, equal = no trade). Both at the custody fill model and 100 USD premium per trade.
"""
from __future__ import annotations

import argparse
import json
import random
import shutil
from pathlib import Path

from custody.dataset import Dataset, check, write_checksums
from custody.evaluate import ACCOUNT_BUDGET_USD, account_view, evaluate, run_strategy
from custody.registry import Registry

from .fetch_sv1 import POOL, append_csv as _append_csv

NEW, OLD = 'zero_dte_timing_v6.6', 'open_hold_v3'
FIRST_SYMBOLS = 2
BOOTSTRAP_DRAWS = 2000
PASSING_VERDICTS = ('PROVISIONAL', 'ACCEPT')
VALIDATION_DAYS = ('2026-09-21', '2026-09-23', '2026-09-25', '2026-10-02',
                   '2026-10-05', '2026-10-07', '2026-10-09', '2026-10-12')


def validate_scope(dataset):
    """Check the preregistered eight-day scope before loading tapes or scoring."""
    if dataset.manifest.get('role') != 'validation/custody':
        raise ValueError('SV1 requires a validation/custody dataset')
    days = {case.trade_date for case in dataset.cases}
    expected = set(VALIDATION_DAYS)
    if days != expected:
        raise ValueError('SV1 must wait for all eight preregistered days; missing=%s unexpected=%s' %
                         (sorted(expected - days), sorted(days - expected)))
    if any(case.symbol not in POOL for case in dataset.cases):
        raise ValueError('SV1 contains a symbol outside the preregistered pool')


def merge(sources, out, symbols=POOL):
    """Copy the pool symbols' cases from several validation datasets into one new dataset."""
    out = Path(out)
    out.mkdir(parents=True, exist_ok=False)
    cases, origin = [], []
    for source in sources:
        src = Dataset(source)
        if src.manifest.get('role') != 'validation/custody':
            raise ValueError('not a validation dataset: %s' % source)
        raw = json.loads((src.root / 'cases.json').read_text(encoding='utf-8'))['cases']
        picked = [c for c in raw if c['symbol'] in symbols]
        for case in picked:
            for rel in ('underlying/%s.csv' % case['symbol'], 'option/%s.csv' % case['contract']):
                target = out / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                if rel.startswith('underlying/') and target.exists():
                    _append_csv(src.root / rel, target)
                else:
                    shutil.copyfile(src.root / rel, target)
        cases += picked
        origin.append({'dataset': src.name, 'checksums_sha256': src.fingerprint, 'cases': len(picked),
                       'sessions': sorted({c['trade_date'] for c in picked})})
    cases.sort(key=lambda c: (c['trade_date'], c['symbol'], c['contract']))
    manifest = {'dataset': out.name, 'role': 'validation/custody', 'schema': 'custody-0dte/1', 'max_dte': 0,
                'selection_policy': 'both_sides_atm_at_open', 'preregistration': 'studies/us_0dte_picks/notes/SV1_PREREG.md',
                'sources': origin, 'sessions': sorted({c['trade_date'] for c in cases}), 'case_count': len(cases)}
    (out / 'cases.json').write_text(json.dumps({'cases': cases}, indent=2) + '\n', encoding='utf-8')
    (out / 'manifest.json').write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    write_checksums(out)
    return check(out)


def gap_side(data):
    """LONG / SHORT / None from the first 1m open against the previous close."""
    prev, first = data.case.prev_close, data.underlying[0].open
    if prev is None:
        return None
    return 'LONG' if first > prev else 'SHORT' if first < prev else None


def first_symbols(datas, trades, limit=FIRST_SYMBOLS):
    """Keep only the trades of the first ``limit`` symbols per day, ordered by first entry fill."""
    first = {}
    for d, t in zip(datas, trades):
        if t['entry'] is not None:
            key = (d.case.trade_date, d.case.symbol)
            first[key] = min(first.get(key, 10**6), t['entry']['fill_minute'])
    keep = set()
    for day in {k[0] for k in first}:
        ranked = sorted((m, s) for (dd, s), m in first.items() if dd == day)
        keep |= {(day, s) for _, s in ranked[:limit]}
    return [t if (d.case.trade_date, d.case.symbol) in keep else dict(t, entry=None, net_return=None)
            for d, t in zip(datas, trades)]


def by_day(datas, trades, budget=ACCOUNT_BUDGET_USD):
    out = {d.case.trade_date: 0.0 for d in datas}
    for d, t in zip(datas, trades):
        if t['entry'] is not None and t['net_return'] is not None:
            out[d.case.trade_date] += t['net_return'] * budget
    return out


def diff_bootstrap(new_days, old_days, draws=BOOTSTRAP_DRAWS, seed=20261002):
    days = sorted(new_days)
    diffs = [new_days[d] - old_days.get(d, 0.0) for d in days]
    if len(days) < 2:
        return None
    rng = random.Random(seed)
    totals = sorted(sum(rng.choice(diffs) for _ in days) for _ in range(draws))
    return {'draws': draws, 'low_95': totals[int(0.025 * draws)], 'high_95': totals[int(0.975 * draws) - 1],
            'share_above_zero': sum(x > 0 for x in totals) / draws}


def score(dataset_dir, registry=None, null_draws=None):
    dataset = Dataset(dataset_dir)
    validate_scope(dataset)
    registry = registry or Registry()
    new, old = registry.get(NEW), registry.get(OLD)
    datas = [dataset.load(c) for c in dataset.cases]
    new_trades = [run_strategy(d, new) for d in datas]
    old_datas = [d for d in datas if gap_side(d) == d.case.direction]
    old_trades = [run_strategy(d, old) for d in old_datas]
    new_first = first_symbols(datas, new_trades)
    kwargs = {} if null_draws is None else {'null_draws': null_draws, 'random_entry_draws': null_draws}
    report_new = evaluate(dataset_dir, NEW, registry, **kwargs)
    n, o = account_view(datas, new_trades), account_view(old_datas, old_trades)
    new_days, old_days = by_day(datas, new_trades), by_day(old_datas, old_trades)
    checks = {'1_v6.6_custody_verdict_not_reject': report_new['verdict'] in PASSING_VERDICTS,
              '2_new_total_above_zero': n['total_usd'] > 0,
              '3_new_minus_old_above_zero': n['total_usd'] - o['total_usd'] > 0}
    return {
        'preregistration': 'studies/us_0dte_picks/notes/SV1_PREREG.md',
        'dataset': {'name': dataset.name, 'checksums_sha256': dataset.fingerprint, 'cases': len(datas),
                    'sessions': dataset.sessions(), 'symbols': sorted({d.case.symbol for d in datas})},
        'strategies': {'new': {k: new[k] for k in ('strategy_id', 'sha256')}, 'old': {k: old[k] for k in ('strategy_id', 'sha256')}},
        'old_flow_cases': len(old_datas),
        'cases_without_prev_close': sum(d.case.prev_close is None for d in datas),
        'new': n, 'old': o, 'new_first_two_symbols': account_view(datas, new_first),
        'by_day': {d: {'new': new_days[d], 'old': old_days.get(d, 0.0)} for d in sorted(new_days)},
        'new_minus_old_usd': n['total_usd'] - o['total_usd'],
        'new_minus_old_bootstrap': diff_bootstrap(new_days, old_days),
        'v6.6_custody': {'verdict': report_new['verdict'], 'gates': report_new['gates_in_sample'],
                         'random_entry': report_new['random_entry']},
        'checks': checks, 'passed': all(checks.values()),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest='command', required=True)
    m = sub.add_parser('merge')
    m.add_argument('--out', required=True, type=Path)
    m.add_argument('--sources', required=True, nargs='+', type=Path)
    s = sub.add_parser('score')
    s.add_argument('--dataset', required=True, type=Path)
    s.add_argument('--out', required=True, type=Path)
    args = parser.parse_args(argv)
    if args.command == 'merge':
        print(json.dumps(merge(args.sources, args.out), indent=2, ensure_ascii=False))
        return 0
    if args.out.exists():
        raise SystemExit('refuse: SV1 is scored once; %s exists' % args.out)
    result = score(args.dataset)
    args.out.write_text(json.dumps(result, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    print(json.dumps({k: result[k] for k in ('checks', 'passed', 'new_minus_old_usd')}, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
