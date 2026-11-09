"""IE21: close-confirmed trial expiry and half-size probes on the cached IE20 queue."""
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict, replace
import gc
import importlib.util
import inspect
from pathlib import Path
import resource
import time

import numpy as np

from studies.trader_replication import martin_continue_ie20 as previous

old = previous.old
ROOT, REPORTS, FIXED = previous.ROOT, previous.REPORTS, previous.FIXED
WORK = REPORTS / 'ie21_work'
PREFIX = 'strong_continue_ie21_'
PLAN = ROOT / 'studies/martin_luk/notes/PLAN_IE21_CN.md'
PREREG = ROOT / 'studies/martin_luk/notes/PREREG_IE21_CN.md'
REFERENCE = old.read(REPORTS / (previous.PREFIX + 'final.json'))
BASE = dict(REFERENCE['retained_config'], trial_days=0, trial_r=.5, probe=False, slots=11)
Data = previous.Data
SEEDS = previous.SEEDS
offline, admissible, better = previous.offline, previous.admissible, previous.better

# Earlier experiments keep their namespaces and read-only account files.
_spec = importlib.util.spec_from_file_location(__name__ + '_engine', previous.__file__)
engine = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(engine)
shared = engine.shared
_diagnose = engine.diagnosis
NAMESPACES = (engine, engine.engine, shared, shared.shared)


def output(name, value):
    old.save(REPORTS / (PREFIX + name + '.json'), value)


def build(d, cfg):
    """All trials use exactly one fixed, label-independent signal book."""
    if not hasattr(d, 'ie21_book'):
        d.ie21_book = previous.build(d, REFERENCE['retained_config'])
    d.built[old.key(dict(cfg=cfg, short=None))] = d.ie21_book
    return d.ie21_book


def policy(cfg):
    rules = replace(old.policy(FIXED), max_open=cfg['slots'])
    if cfg['probe']:
        rules = replace(rules, risk=rules.risk / 2, risk_low=rules.risk_low / 2,
            risk_high=rules.risk_high / 2, max_position=rules.max_position / 2,
            add_frac=1., add_cap_mult=2., add_cap_limit=rules.max_position)
    return rules


def trial_decision(q, completed, close, cfg):
    """Check one completed close, never a later high or a rejected add attempt."""
    if not cfg['trial_days'] or q.side < 0 or completed < cfg['trial_days'] \
            or getattr(q, 'trial_checked', False) or not np.isfinite(close) or close <= 0:
        return None
    q.trial_checked = True
    if q.invested > q.size0 * q.fill * (1 + 1e-10):
        return None
    unit = abs(q.fill - q.stop0)
    progress = (close - q.fill) / unit
    if progress >= cfg['trial_r']:
        return None
    return dict(completed=int(completed), progress=float(progress), threshold=cfg['trial_r'])


def trial_simulator(cfg):
    """Insert two lifecycle actions into a private copy of the unchanged engine."""
    source = inspect.getsource(old.system.simulate)
    opening = "        for q in list(pos.values()):\n            opening = o[d, q.j]\n            if q.short_trim_pending"
    opening_hook = """        if daily_close is None or not daily_close[d]:
            for q in list(pos.values()):
                pending = getattr(q, 'trial_order', None)
                opening = o[d, q.j]
                if pending is not None and np.isfinite(opening) and opening > 0:
                    if track is not None:
                        track.setdefault('trial_orders', []).append(dict(pending, status='filled',
                            day=str(dates[d]), opening=float(opening)))
                    close_part(q, q.size, float(opening), d, 'trial_open')
"""
    closing = '            if rules.nft_days and session[d] - session[q.d0] == rules.nft_days'
    closing_hook = """            decision = trial_decision(q, session[d] - session[q.d0] + 1, c[d, j], trial_config)
            if decision is not None:
                q.trial_order = dict(decision, code=str(px['codes'][j]), entry=str(dates[q.d0]),
                    signal_day=str(dates[d]), close=float(c[d, j]), fill=float(q.fill), stop=float(q.stop0))
                if track is not None:
                    track.setdefault('trial_orders', []).append(dict(q.trial_order, status='confirmed'))
"""
    skip = 'if q.d0 == d or q.trail_pending or q.add_pending is not None or np.isnan(o[d, j]):'
    changes = ((opening, opening_hook + opening), (closing, closing_hook + closing),
               (skip, "if getattr(q, 'trial_order', None) is not None or " + skip[3:]))
    for anchor, replacement in changes:
        if source.count(anchor) != 1:
            raise AssertionError('fixed engine lifecycle anchor moved')
        source = source.replace(anchor, replacement)
    scope = dict(vars(old.system), trial_decision=trial_decision, trial_config=cfg)
    exec(compile(source, str(WORK / 'trial_hook'), 'exec'), scope)
    return scope['simulate']


def run_account(d, cfg, random_order=None, placebo=None, drop=None, human=None, fresh=False):
    ident = old.key(dict(cfg=cfg, fixed=FIXED, random_order=random_order, placebo=placebo, drop=drop, human=human))
    path = WORK / 'accounts' / (ident + '.json')
    if path.exists() and not fresh:
        return old.read(path)
    b = build(d, cfg)
    rules, book = policy(cfg), b['book']
    if human is not None:
        book = [[] for _ in book]
        for label in human:
            if label['code'] in d.ci:
                t, j = label['anchor'], d.ci[label['code']]
                event = old.order(t, j, 1, d, FIXED, direct=True)
                if event is not None:
                    book[2 * t + 1].append(event)
        rules = replace(rules, intraday_kinds=())
    if cfg['probe']:
        book = [[(*e[:8], e[8] / 2, *e[9:]) if len(e) > 8 and e[8] is not None else e
                 for e in rows] for rows in book]
    if random_order is not None:
        rng = np.random.default_rng(random_order)
        book = [[(float(rng.random()), *e[1:]) for e in rows] for rows in book]
    if drop:
        removed = {tuple(x) for x in drop}
        book = [[e for e in rows if (d.days[t // 2], d.codes[e[1]]) not in removed]
                for t, rows in enumerate(book)]
    pool = None
    if placebo is not None:
        pool = np.zeros((2 * len(d.days), len(d.codes)), bool)
        for t in range(1, len(d.days)):
            pool[2 * t:2 * t + 2] = b['pool'][t - 1]
    track = {}
    simulate = trial_simulator(cfg) if cfg['trial_days'] else old.system.simulate
    curve, days, trades = simulate(d.phase_px(), d.management, rules, book, *old.panels.WINDOW,
        audit=True, track=track, placebo=np.random.default_rng(placebo) if placebo is not None else None, pool=pool)
    curve, days = curve[1::2], days[1::2]
    for trade in trades:
        if trade['why'] == 'trail_open':
            s = d.di[trade.get('trail_signal', trade['exit'])]
            trade['sell_reason'] = 'climax' if d.f['climax'][s, d.ci[trade['code']]] == 1 else 'ema' + str(FIXED['trail'])
        else:
            trade['sell_reason'] = trade['why']
        for execution in trade['executions']:
            t, j = d.di[execution['time']], d.ci[trade['code']]
            if execution['action'] != 'end' and not \
                    d.px['low'][t, j] - 1e-8 <= execution['price'] <= d.px['high'][t, j] + 1e-8:
                raise AssertionError('execution outside real daily range')
    result = old.clean(dict(id=ident, config=cfg, fixed=FIXED, policy=asdict(rules),
        curve=curve, dates=days, trades=trades, summary=old.summarize_account(curve, days, trades, track),
        rotations=[], trial_orders=track.get('trial_orders', []), add_orders=track.get('add_orders', []),
        fills_valid=True, daily_entries=dict(Counter(tr['entry'] for tr in trades))))
    if not fresh:
        old.save(path, result)
    return result


def score(d, cfg, account, labels, supplied=False):
    build(d, cfg)
    return old.score(d, cfg, account, labels, supplied=supplied)


def diagnosis(d, cfg, account, labels):
    # The old diagnostic uses FIXED for capacity, including its nested namespace.
    for namespace in NAMESPACES:
        namespace.FIXED = dict(FIXED, max_open=cfg['slots'])
    try:
        return _diagnose(d, cfg, account, labels)
    finally:
        for namespace in NAMESPACES:
            namespace.FIXED = FIXED


def proposals(number, winners):
    if number in (1, 2):
        return [dict(BASE, trial_days=n, trial_r=.5 if number == 1 else 0.) for n in (2, 3, 5)] + [dict(BASE)]
    if number == 3:
        return [dict(BASE, probe=True, slots=n) for n in (11, 16)] + [dict(BASE)]
    if number == 4:
        return [dict(winners[n]['config'], probe=True, slots=slots) for n in ('A', 'B') for slots in (11, 16)] + [dict(BASE)]
    return []


def source_functions():
    paths = {Path(__file__), *(ROOT / n for n in previous.source_functions())}
    paths.discard(previous.WORK / 'observe.py')
    return {str(p.relative_to(ROOT)): old.sha(p) for p in sorted(paths)}


def prepare():
    path = WORK / 'prepared.json'
    if path.exists():
        return
    prior = old.read(previous.WORK / 'prepared.json')
    paths = {ROOT / p for p in prior['inputs']}
    paths.update((previous.WORK / 'prepared.json', REPORTS / (previous.PREFIX + 'final.json'),
                  REPORTS / (previous.PREFIX + 'final_diagnosis.json'), old.LEDGER))
    old.save(path, dict(source=old.sha(__file__), shape=prior['shape'],
        inputs={str(p.relative_to(ROOT)): old.sha(p) for p in sorted(paths)},
        input_snapshot=old.sha(WORK / 'initial_inputs.json')))


def seal():
    state = dict(source=source_functions(), plan=old.sha(PLAN), prereg=old.sha(PREREG),
        prepared=old.sha(WORK / 'prepared.json'), baseline=BASE, fixed=FIXED)
    path = WORK / 'run_source.json'
    if path.exists():
        if old.read(path) != state:
            raise AssertionError('IE21 registered implementation or inputs changed')
    else:
        old.save(path, state)
        (WORK / 'research_source.txt').write_text(Path(__file__).read_text())


def search(d, labels, tag, held=None):
    path = WORK / 'searches' / (tag + '.json')
    if path.exists():
        return old.read(path)
    training = old.training_rows(labels, held)
    floor = shared.measure(d, BASE, training)
    chosen = exploration = best_eleven = floor
    winners, rounds = {}, []
    for number in range(1, 5):
        choices = proposals(number, winners)
        regpath = WORK / 'registrations' / (tag + '_r' + str(number) + '.json')
        registration = dict(tag=tag, heldout=held, round=number, candidates=choices,
            training_ids=sorted(r['id'] for r in training), incumbent=chosen['config'],
            winners={n: r['config'] for n, r in winners.items()}, logic=source_functions(), prereg=old.sha(PREREG))
        if regpath.exists() and old.read(regpath) != registration:
            raise AssertionError('IE21 candidate registration changed')
        if not regpath.exists():
            old.save(regpath, registration)
        results, group_best = [], None
        for cfg in choices:
            result = shared.measure(d, cfg, training)
            eligible = admissible(result['metrics'], floor['metrics'])
            result.update(admissible=eligible, effective=eligible and better(result['metrics'], floor['metrics']))
            results.append(result)
            if eligible and better(result['metrics'], chosen['metrics']):
                chosen = result
            if eligible and cfg['slots'] == 11 and better(result['metrics'], best_eleven['metrics']):
                best_eleven = result
            if better(result['metrics'], exploration['metrics']):
                exploration = result
            if number <= 2 and cfg['trial_days'] and (group_best is None or better(result['metrics'], group_best['metrics'])):
                group_best = result
            print(tag, 'round', number, cfg['trial_days'], cfg['trial_r'], cfg['probe'], cfg['slots'],
                'bought', result['metrics']['bought'], 'weight', round(result['metrics']['weighted_coverage'], 5), flush=True)
        if number <= 2:
            winners['AB'[number - 1]] = group_best
        round_ = dict(round=number, registration=str(regpath.relative_to(ROOT)), candidates=results,
                      selected=chosen['config'], metrics=chosen['metrics'])
        rounds.append(round_)
        old.save(WORK / 'rounds' / (tag + '_r' + str(number) + '.json'), round_)
        gc.collect()
    result = dict(tag=tag, heldout=held, config=chosen['config'], metrics=chosen['metrics'], floor=floor['metrics'],
        winners={n: r['config'] for n, r in winners.items()}, rounds=rounds,
        best_eleven=dict(config=best_eleven['config'], metrics=best_eleven['metrics']),
        exploratory_config=exploration['config'], exploratory_metrics=exploration['metrics'])
    old.save(path, result)
    return old.clean(result)


def initial_diagnosis():
    seal()
    d = Data()
    labels = [r for r in old.labels(d) if r['side'] > 0]
    account = run_account(d, BASE)
    ref = old.read(previous.WORK / 'accounts' / (REFERENCE['account_id'] + '.json'))
    if account['trades'] != ref['trades'] or account['curve'] != ref['curve']:
        raise AssertionError('IE20 baseline changed')
    result = diagnosis(d, BASE, account, labels)
    if result['counts'] != REFERENCE['remaining']:
        raise AssertionError('IE20 baseline classification changed')
    result['baseline_identical'] = True
    output('diagnosis', result)
    print('baseline identical', old.card_summary(result['card']['rows'])['weighted_coverage'], flush=True)


for namespace in NAMESPACES:
    for name in ('WORK', 'PREFIX', 'PLAN', 'PREREG', 'BASE', 'FIXED', 'Data', 'build', 'run_account',
                 'score', 'diagnosis', 'proposals', 'source_functions', 'seal', 'search', 'output'):
        setattr(namespace, name, globals()[name])
cross_validation, run_search, finalize = shared.cross_validation, shared.run_search, shared.finalize


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=('prepare', 'diagnose', 'search', 'finalize'))
    parser.add_argument('--tag')
    args = parser.parse_args()
    offline()
    start = time.monotonic()
    if args.command == 'prepare':
        prepare()
    elif args.command == 'diagnose':
        initial_diagnosis()
    elif args.command == 'finalize':
        finalize()
    else:
        for tag in ([args.tag] if args.tag else ['true', *('shuffle_' + str(s) for s in SEEDS)]):
            run_search(tag)
            gc.collect()
    print('seconds', round(time.monotonic() - start, 1), 'RSS MiB',
          round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1), flush=True)


if __name__ == '__main__':
    main()
