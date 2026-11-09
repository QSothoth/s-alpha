"""IE16 selection research on cached inputs, reusing the fixed IE14 account."""
from __future__ import annotations

import argparse
from collections import Counter
import gc
import importlib.util
from pathlib import Path
import resource
import socket
import time

import numpy as np

from studies.trader_replication import martin_continue_ie15 as previous

old = previous.old
ROOT, REPORTS, FIXED = previous.ROOT, previous.REPORTS, previous.FIXED
WORK = REPORTS / 'ie16_work'
PLAN = ROOT / 'studies/martin_luk/notes/PLAN_IE16_CN.md'
PREREG = ROOT / 'studies/martin_luk/notes/PREREG_IE16_CN.md'
PREFIX = 'strong_continue_ie16_'
SEEDS = (160101, 160103, 160107, 160109, 160111)
BASE = dict(previous.BASE, market=FIXED['market'], trigger=FIXED['trigger'])
Data = previous.Data

# Load a private namespace so shared orchestration can use IE16 hooks without
# changing the IE15 module, its caches, or another test's imported functions.
_spec = importlib.util.spec_from_file_location(__name__ + '_shared', previous.__file__)
shared = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(shared)
_diagnosis, _metrics = shared.diagnosis, shared.metrics

MARKETS = ('both21', 'either21', 'either9', 'either50', 'feedback')
POOLS = dict(liquid=(20e6, 5), soft_adr=(20e6, 3), soft_money=(2e6, 5),
             soft_both=(2e6, 3), soft_middle=(10e6, 4))
TRIGGERS = ('high', 'pull_body', 'pull_close', 'pull_ema9', 'pull_ema21')
WATCHES = (1, 'premier', 'fresh', 'premier_fresh')
PRIORITIES = {
    'money': (),
    'upgrade_cluster': ('upgrade', 'cluster', 'premier', 'adr'),
    'cluster_upgrade': ('cluster', 'upgrade', 'premier', 'adr'),
    'premier_upgrade': ('premier', 'upgrade', 'cluster', 'adr'),
    'adr_upgrade': ('fast', 'upgrade', 'cluster', 'premier', 'adr'),
    'upgrade_premier': ('upgrade', 'premier', 'cluster', 'adr'),
}


def output(name, value):
    old.save(REPORTS / (PREFIX + name + '.json'), value)


def offline():
    def denied(*args, **kwargs):
        raise RuntimeError('IE16 uses cached inputs only')
    socket.socket = denied
    socket.create_connection = denied


def prepare():
    if not (WORK / 'initial_inputs.json').exists():
        raise RuntimeError('record the existing workspace before starting IE16')
    path = WORK / 'prepared.json'
    if not path.exists():
        old.save(path, dict(inputs={str(p.relative_to(ROOT)): old.sha(p) for p in (
            old.WORK / 'prepared.json', previous.WORK / 'prepared.json',
            *previous.WORK.glob('*.npy'))}, note='Read-only reuse of IE14 and IE15 caches.'))
    (WORK / 'tmp').mkdir(exist_ok=True)


def source_functions():
    return {name: old.sha(path) for name, path in dict(
        source=Path(__file__), previous=Path(previous.__file__), prior=Path(old.__file__),
        engine=Path(old.system.__file__)).items()}


def seal():
    state = dict(functions=source_functions(), prereg=old.sha(PREREG), plan=old.sha(PLAN),
                 fixed=FIXED, prepared=old.sha(WORK / 'prepared.json'))
    path = WORK / 'run_source.json'
    if path.exists():
        if old.read(path)['state'] != state:
            raise AssertionError('registered IE16 logic changed; evaluated caches cannot be reused')
    else:
        (WORK / 'research_source.txt').write_text(Path(__file__).read_text())
        old.save(path, dict(state=state))


def market_mask(benchmarks, mode):
    if mode == 'feedback':
        return np.ones(len(benchmarks[0]['close']), bool)
    line = 'e9' if mode == 'either9' else 'e21'
    states = []
    for b in benchmarks:
        close = np.asarray(b['close'], float)
        ema = old.lib.smooth(close, 50) if mode == 'either50' else np.asarray(b[line], float)
        states.append(close >= ema)
    return np.logical_and.reduce(states) if mode == 'both21' else np.logical_or.reduce(states)


def selection_arrays(d, cfg):
    b = previous.selection_arrays(d, dict(cfg, pool='liquid', watch=bool(cfg['watch'])))
    money, adr = POOLS[cfg['pool']]
    b['pool'] = (d.f['money'] >= money) & (d.f['adr'] > adr)
    b['market'] = market_mask(d.meta['benchmark'], cfg['market'])
    watched = b['watched']
    if cfg['watch'] in ('fresh', 'premier_fresh'):
        watched = b['scanned'].copy()
    if cfg['watch'] in ('premier', 'premier_fresh'):
        watched = watched & (d.f['money'] >= 100e6)
    b['watched'] = watched
    signal = b['pool'] & b['trend'] & b['setup']
    if cfg['watch']:
        signal &= watched
    b['signals'] = dict(long=signal, short=np.zeros_like(signal))
    return b


def priorities(cfg, upgraded, cluster, money, adr):
    fields = dict(upgrade=upgraded, cluster=cluster, premier=money >= 100e6,
                  adr=adr, fast=adr > 5, liquid=money >= 20e6)
    sequence = PRIORITIES[cfg['priority']]
    if cfg['pool'].startswith('soft_'):
        sequence += ('fast', 'liquid')
    if not sequence:
        return [-float(value) for value in money]
    return [tuple(-float(fields[k][j]) for k in sequence) + (-float(money[j]),)
            for j in range(len(money))]


def entry_level(t, j, d, trigger):
    s, p = t - 1, d.px
    level = float(p['high'][s, j])
    if trigger == 'high' or d.f['pullback'][s, j] != 1:
        return level
    if trigger == 'pull_body':
        alternative = max(p['open'][s, j], p['close'][s, j])
    elif trigger == 'pull_close':
        alternative = p['close'][s, j]
    else:
        alternative = d.f['e9' if trigger == 'pull_ema9' else 'e21'][s, j]
    return min(level, float(alternative)) if np.isfinite(alternative) else level


def order(t, j, d, cfg):
    if cfg['trigger'] == 'high' or d.f['pullback'][t - 1, j] != 1:
        return old.order(t, j, 1, d, FIXED)
    s, p, f = t - 1, d.px, d.f
    level = entry_level(t, j, d, cfg['trigger'])
    if not np.isfinite(p['high'][t, j]) or p['high'][t, j] <= level:
        return None
    fill = max(p['open'][t, j], level)
    if not np.isfinite(fill) or fill <= 0 or not np.isfinite(f['adr'][s, j]):
        return None
    width = min(max((fill - p['low'][s, j]) / fill, .005), FIXED['stop_cap'] / 100, f['adr'][s, j] / 200)
    stop = fill * (1 - width)
    day_stop = stop if np.isfinite(p['low'][t, j]) and p['low'][t, j] <= stop else None
    cap = .2 if f['money'][s, j] < 500e6 else .25
    return (-float(f['money'][s, j]), j, 1, float(fill), float(stop), 'long', day_stop, None, cap)


def build(d, cfg):
    ident = old.key(cfg)
    cachekey = old.key(dict(cfg=cfg, short=None))
    if d.latest is not None and d.latest[0] == ident:
        d.built[cachekey] = d.latest[1]
        return d.latest[1]
    d.latest = None
    d.built.clear()
    b = selection_arrays(d, cfg)
    book = [[] for _ in range(2 * len(d.days))]
    triggers = np.zeros_like(b['signals']['long'])
    for t in range(d.start, d.end):
        s = t - 1
        candidates = np.flatnonzero(b['signals']['long'][s])
        cluster = np.zeros(len(candidates), int)
        if cfg['priority'] != 'money':
            scanned, upgraded = previous.cluster_counts(d.extra['peers'][s, candidates],
                                                        b['scanned'][s], b['upgraded'][s])
            cluster = np.maximum(scanned, upgraded)
        priority = priorities(cfg, b['upgraded'][s, candidates], cluster,
                              d.f['money'][s, candidates], d.f['adr'][s, candidates])
        for k, j in enumerate(candidates):
            e = order(t, int(j), d, cfg)
            if e is not None:
                triggers[s, j] = True
                if b['market'][s]:
                    book[2 * t].append((priority[k], *e[1:]))
    b.update(book=book, triggers=triggers, short_market=np.ones(len(d.days), bool))
    d.built[cachekey] = b
    d.latest = ident, b
    return b


def score(d, cfg, account, labels):
    build(d, cfg)
    return old.score(d, cfg, account, labels)


def diagnosis(d, cfg, account, labels):
    result = _diagnosis(d, cfg, account, labels)
    b = build(d, cfg)
    for r in result['card']['rows']:
        if r['bought'] or not r['signal'] or r['code'] not in d.ci:
            continue
        offers = r.get('offered', [])
        if not offers:
            j = d.ci[r['code']]
            nights = [t - 1 for t in range(r['lo'], r['hi'] + 1) if t >= d.start]
            signaled = [s for s in nights if b['signals']['long'][s, j]]
            blocked = bool(signaled) and not any(b['market'][s] for s in signaled)
            r['selection_block'] = '市况' if blocked else '触发'
            r['selection_detail'] = '前晚市况未放行' if blocked else '窗口内没有可成交报价或独立尝试不足'
        elif r['selection_block'] == '被别的信号抢先' and not any(
                v['earlier'] and v['morning'] < FIXED['max_open'] and not v['same_held']
                and not v['actual_same_day'] for v in offers):
            r['selection_block'] = '没仓位'
    result['counts'] = dict(Counter(r['selection_block'] for r in result['card']['rows'] if not r['bought']))
    return result


def metrics(d, cfg, account, labels):
    result = _metrics(d, cfg, account, labels)
    result['rank'] = [result['weighted_coverage'], result['bought'], result['lift']]
    sig = build(d, cfg)['signals']['long']
    result['widths'] = {}
    for h in old.HALVES:
        ix = [t for t in range(d.start, len(d.days)) if old.half(d.days[t]) == h]
        values = sig[ix].sum(axis=1)
        result['widths'][h] = dict(median=float(np.median(values)), mean=float(values.mean()),
                                    maximum=int(values.max()), total=int(values.sum()))
    return result


def proposals(cfg, counts, seen, number):
    banks = dict(market=MARKETS, pool=tuple(POOLS), trigger=TRIGGERS,
                 watch=WATCHES, priority=tuple(PRIORITIES))
    if number < 6:
        layers = [('market', 'pool', 'trigger', 'watch', 'priority')[number - 1]]
    else:
        weights = dict(priority=counts.get('被别的信号抢先', 0) + counts.get('没仓位', 0),
                       pool=counts.get('股票池', 0), market=counts.get('市况', 0),
                       trigger=counts.get('触发', 0) + counts.get('买点', 0))
        layers = sorted(weights, key=lambda k: -weights[k])
    for layer in layers:
        choices = [dict(cfg, **{layer: value}) for value in banks[layer]]
        choices = [c for c in choices if old.key(c) not in seen and c != cfg]
        if choices:
            return layer, choices[:5]
    return 'exhausted', []


def search(d, labels, tag, held=None):
    path = WORK / 'searches' / (tag + '.json')
    if path.exists():
        return old.read(path)
    training = old.training_rows(labels, held)
    floor = metrics(d, BASE, run_account(d, BASE), training)
    chosen, chosen_metrics = dict(BASE), floor
    branch, branch_metrics = dict(BASE), floor
    seen, rounds = {old.key(BASE)}, []
    for number in range(1, 7):
        layer, candidates = proposals(branch, branch_metrics['blocks'], seen, number)
        if not candidates:
            break
        registration = dict(tag=tag, heldout=held, round=number, layer=layer,
            counts=branch_metrics['blocks'], training_ids=sorted(r['id'] for r in training),
            candidates=candidates, incumbent=chosen, branch=branch,
            prereg=old.sha(PREREG), logic=source_functions())
        regpath = WORK / 'registrations' / (tag + '_r' + str(number) + '.json')
        if regpath.exists() and old.read(regpath) != registration:
            raise AssertionError('IE16 round registration changed')
        if not regpath.exists():
            old.save(regpath, registration)
        results = []
        for cfg in candidates:
            seen.add(old.key(cfg))
            account = run_account(d, cfg)
            card = score(d, cfg, account, training)
            measure = metrics(d, cfg, account, training)
            eligible = measure['bought'] >= floor['bought'] and \
                measure['weighted_coverage'] + 1e-12 >= floor['weighted_coverage']
            results.append(dict(config=cfg, metrics=measure, admissible=eligible,
                                account_id=account['id'], account=account['summary'], card=card))
            if eligible and tuple(measure['rank']) > tuple(chosen_metrics['rank']):
                chosen, chosen_metrics = cfg, measure
            print(tag, 'round', number, layer, old.key(cfg), 'bought', measure['bought'],
                  'weighted', round(measure['weighted_coverage'], 4), 'eligible', eligible, flush=True)
        options = results if number == 4 else [dict(config=branch, metrics=branch_metrics), *results]
        exploration = max(options, key=lambda r: tuple(r['metrics']['rank']))
        branch, branch_metrics = exploration['config'], exploration['metrics']
        rounds.append(dict(round=number, layer=layer, registration=str(regpath.relative_to(ROOT)),
                      candidates=results, selected=chosen, metrics=chosen_metrics,
                      branch=branch, branch_metrics=branch_metrics))
        old.save(WORK / 'rounds' / (tag + '_r' + str(number) + '.json'), rounds[-1])
        gc.collect()
    result = dict(tag=tag, heldout=held, config=chosen, metrics=chosen_metrics, floor=floor, rounds=rounds)
    old.save(path, result)
    return old.clean(result)


for _name in ('WORK', 'PLAN', 'PREREG', 'PREFIX', 'SEEDS', 'BASE', 'FIXED', 'Data',
              'build', 'score', 'diagnosis', 'metrics', 'search', 'source_functions', 'seal'):
    setattr(shared, _name, globals()[_name])
run_account = shared.run_account
initial_diagnosis = shared.initial_diagnosis
signal_reference = shared.signal_reference
cross_validation = shared.cross_validation
run_search = shared.run_search
finalize = shared.finalize


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=('prepare', 'diagnose', 'search', 'finalize'))
    parser.add_argument('--tag')
    args = parser.parse_args()
    offline()
    if args.command == 'prepare':
        prepare()
    elif args.command == 'diagnose':
        initial_diagnosis()
    elif args.command == 'finalize':
        finalize()
    else:
        for tag in ([args.tag] if args.tag else ['true', *('shuffle_' + str(s) for s in SEEDS)]):
            start = time.monotonic()
            run_search(tag)
            print('finished', tag, 'seconds', round(time.monotonic() - start, 1), flush=True)
            gc.collect()
    print('RSS MiB', resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, flush=True)


if __name__ == '__main__':
    main()
