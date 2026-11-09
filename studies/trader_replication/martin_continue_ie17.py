"""IE17: equal-weight, close-known strength ordering on the fixed IE16 pool."""
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

from studies.trader_replication import martin_continue_ie16 as previous

old = previous.old
ROOT, REPORTS, FIXED = previous.ROOT, previous.REPORTS, previous.FIXED
WORK = REPORTS / 'ie17_work'
PLAN = ROOT / 'studies/martin_luk/notes/PLAN_IE17_CN.md'
PREREG = ROOT / 'studies/martin_luk/notes/PREREG_IE17_CN.md'
PREFIX = 'strong_continue_ie17_'
SEEDS = previous.SEEDS
REFERENCE = old.read(REPORTS / (previous.PREFIX + 'final.json'))
COMPONENTS = ('strength', 'peer', 'launch', 'tight', 'money', 'high')
BASE = dict(REFERENCE['config'], components=[], interval=[.5, 2.], scope='signals')

# Keep the shared account and diagnostics in a private namespace. Older research
# modules and their imported hooks must retain their original behavior.
_spec = importlib.util.spec_from_file_location(__name__ + '_shared', previous.previous.__file__)
shared = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(shared)
_diagnosis, _metrics = shared.diagnosis, shared.metrics


def output(name, value):
    old.save(REPORTS / (PREFIX + name + '.json'), value)


def offline():
    def denied(*args, **kwargs):
        raise RuntimeError('IE17 uses cached inputs only')
    socket.socket = denied
    socket.create_connection = denied


def percentile(values):
    """Average tied ranks; missing, singleton and constant values are neutral."""
    values = np.asarray(values, float)
    out = np.full(values.shape, .5)
    indices = np.flatnonzero(np.isfinite(values))
    if len(indices) < 2:
        return out
    indices = indices[np.argsort(values[indices], kind='stable')]
    starts = np.r_[0, np.flatnonzero(np.diff(values[indices]) != 0) + 1]
    ends = np.r_[starts[1:], len(indices)]
    ranks = (starts + ends - 1) / (2 * (len(indices) - 1))
    out[indices] = np.repeat(ranks, ends - starts)
    return out


def security_fields(close, high, low, ema, adr):
    """Trailing calculations on one bounded security block, never future rows."""
    result = {}
    for n in (20, 60):
        a = np.full(close.shape, np.nan)
        a[n:] = old.lib.divide(close[n:], close[:-n]) - 1
        result['g' + str(n)] = a
    result['extension'] = old.lib.divide(old.lib.divide(close, ema) - 1, adr / 100)
    tight, near = np.full(close.shape, np.nan), np.full(close.shape, np.nan)
    for j in range(close.shape[1]):
        ranges = old.lib.divide(high[:, j], low[:, j]) - 1
        tight[:, j] = -old.lib.divide(old.lib.roll(ranges, 3), adr[:, j] / 100)
        near[:, j] = old.lib.divide(close[:, j], old.lib.roll(high[:, j], 250, 'max'))
    result.update(tight=tight, high=near)
    return result


def peer_lead(growth, peers):
    """Rank against the cached close-known neighbors plus the security itself."""
    neighbors = growth[np.maximum(peers, 0)]
    valid = (peers >= 0) & (peers != np.arange(len(growth))[:, None])
    valid &= np.isfinite(neighbors) & np.isfinite(growth[:, None])
    less = ((neighbors < growth[:, None]) & valid).sum(axis=1)
    ties = ((neighbors == growth[:, None]) & valid).sum(axis=1)
    # Missing peers stay missing until the final percentile assigns neutral 0.5.
    return old.lib.divide(less + .5 * ties, valid.sum(axis=1))


def prepare():
    if not (WORK / 'initial_inputs.json').exists():
        raise RuntimeError('record existing inputs before IE17')
    if (WORK / 'prepared.json').exists():
        return
    d = previous.Data()
    shape = d.px['close'].shape
    names = ('g20', 'g60', 'extension', 'tight', 'high', 'strength', 'peer')
    arrays = {name: np.lib.format.open_memmap(WORK / (name + '.npy'), mode='w+',
                                            dtype='float32', shape=shape) for name in names}
    for start in range(0, shape[1], 32):
        sl = slice(start, start + 32)
        fields = security_fields(*(np.asarray(d.px[n][:, sl], float) for n in ('close', 'high', 'low')),
                                 np.asarray(d.f['e21'][:, sl], float), np.asarray(d.f['adr'][:, sl], float))
        for name, values in fields.items():
            arrays[name][:, sl] = values
        del fields
    for s in range(shape[0]):
        arrays['strength'][s] = (percentile(arrays['g20'][s]) + percentile(arrays['g60'][s])) / 2
        arrays['peer'][s] = peer_lead(arrays['g20'][s], d.extra['peers'][s])
        if s % 250 == 0:
            print('prepare strength night', s, '/', shape[0], flush=True)
    for a in arrays.values():
        a.flush()
    paths = [old.WORK / 'prepared.json', previous.previous.WORK / 'prepared.json',
             *old.WORK.glob('*.npy'), *previous.previous.WORK.glob('*.npy'),
             *(old.OLD / 'panel' / (n + '.npy') for n in ('open', 'high', 'low', 'close')),
             REPORTS / (previous.PREFIX + 'final.json')]
    old.save(WORK / 'prepared.json', dict(shape=shape, inputs={str(p.relative_to(ROOT)): old.sha(p) for p in paths},
             features={n: old.sha(WORK / (n + '.npy')) for n in names}, source=old.sha(__file__)))


class Data(previous.Data):
    def __init__(self):
        super().__init__()
        self.strength = {n: np.load(WORK / (n + '.npy'), mmap_mode='r')
                         for n in ('strength', 'peer', 'extension', 'tight', 'high')}


def strength_scores(s, d, cfg, signals):
    """Freeze ranks across all signal names before any next-day trigger is read."""
    candidates = np.flatnonzero(signals)
    reference = candidates if cfg['scope'] == 'signals' else np.flatnonzero(np.isfinite(d.px['close'][s]))
    positions = np.searchsorted(reference, candidates)
    raw = {n: d.strength[n][s] for n in ('strength', 'peer', 'tight', 'high')}
    x = d.strength['extension'][s]
    lo, hi = cfg['interval']
    raw['launch'] = -np.maximum(np.maximum(lo - x, x - hi), 0)
    raw['money'] = d.f['money'][s]
    return np.mean([percentile(raw[n][reference])[positions] for n in cfg['components']], axis=0) \
        if len(candidates) else np.array([], float)


def build(d, cfg):
    ident = old.key(cfg)
    cachekey = old.key(dict(cfg=cfg, short=None))
    if d.latest is not None and d.latest[0] == ident:
        d.built[cachekey] = d.latest[1]
        return d.latest[1]
    d.latest = None
    d.built.clear()
    if cfg['priority'] == 'money':
        b = previous.build(d, cfg)
    else:
        b = previous.selection_arrays(d, cfg)
        book = [[] for _ in range(2 * len(d.days))]
        triggers = np.zeros_like(b['signals']['long'])
        for t in range(d.start, d.end):
            s = t - 1
            signals = b['signals']['long'][s]
            candidates = np.flatnonzero(signals)
            scores = strength_scores(s, d, cfg, signals)
            for k, j in enumerate(candidates):
                event = previous.order(t, int(j), d, cfg)
                if event is not None:
                    triggers[s, j] = True
                    if b['market'][s]:
                        book[2 * t].append(((-float(scores[k]), d.codes[j]), *event[1:]))
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
    for row in result['card']['rows']:
        if row['bought'] or not row['signal'] or row['code'] not in d.ci:
            continue
        offers = row.get('offered', [])
        if not offers:
            j = d.ci[row['code']]
            nights = [t - 1 for t in range(row['lo'], row['hi'] + 1) if t >= d.start]
            signaled = [s for s in nights if b['signals']['long'][s, j]]
            blocked = bool(signaled) and not any(b['market'][s] for s in signaled)
            row['selection_block'] = '市况' if blocked else '触发'
            row['selection_detail'] = '前晚市况未放行' if blocked else '窗口内没有可成交报价或独立尝试不足'
        elif row['selection_block'] == '被别的信号抢先' and not any(
                v['earlier'] and v['morning'] < FIXED['max_open'] and not v['same_held']
                and not v['actual_same_day'] for v in offers):
            row['selection_block'] = '没仓位'
    result['counts'] = dict(Counter(r['selection_block'] for r in result['card']['rows'] if not r['bought']))
    return result


def metrics(d, cfg, account, labels):
    result = _metrics(d, cfg, account, labels)
    result['rank'] = [result['weighted_coverage'], result['bought']]
    return result


def proposals(cfg, seen, number):
    if number == 1:
        groups = [COMPONENTS, tuple(n for n in COMPONENTS if n != 'peer'),
                  tuple(n for n in COMPONENTS if n != 'tight'), ('strength', 'launch', 'money')]
        return 'components', [dict(BASE, priority='continuous', components=list(g)) for g in groups] + [dict(BASE)]
    if number == 2:
        order = ('strength', 'launch', 'money', 'high', 'peer', 'tight')
        choices = [dict(cfg, components=[n for n in cfg['components'] if n != name])
                   for name in order if name in cfg['components'] and len(cfg['components']) > 1]
        layer = 'components'
    elif number == 3 and 'launch' in cfg['components']:
        layer = 'interval'
        choices = [dict(cfg, interval=list(x)) for x in ((0, 1), (0, 2), (1, 2), (.5, 1), (1, 3))]
    elif number == 3:
        layer = 'components'
        choices = [dict(cfg, components=[n for n in COMPONENTS if n in cfg['components'] or n == 'launch'])]
    elif number == 4:
        layer = 'scope'
        choices = [dict(cfg, scope='panel' if cfg['scope'] == 'signals' else 'signals')]
    else:
        layer = 'components'
        choices = [dict(cfg, components=[n for n in COMPONENTS if n in cfg['components'] or n == name])
                   for name in COMPONENTS if name not in cfg['components']]
        choices += [dict(cfg, components=[n for n in cfg['components'] if n != name])
                    for name in COMPONENTS if name in cfg['components'] and len(cfg['components']) > 1]
    return layer, [c for c in choices if old.key(c) not in seen and c != cfg][:5]


def source_functions():
    paths = dict(source=Path(__file__), previous=Path(previous.__file__),
                 orchestration=Path(previous.previous.__file__), prior=Path(old.__file__),
                 engine=Path(old.system.__file__), features=Path(old.lib.__file__))
    return {name: old.sha(path) for name, path in paths.items()}


def seal():
    state = dict(functions=source_functions(), prereg=old.sha(PREREG), plan=old.sha(PLAN), fixed=FIXED,
                 baseline=BASE, prepared=old.sha(WORK / 'prepared.json'))
    path = WORK / 'run_source.json'
    if path.exists():
        if old.read(path)['state'] != state:
            raise AssertionError('IE17 registered logic changed; do not reuse evaluated results')
    else:
        (WORK / 'research_source.txt').write_text(Path(__file__).read_text())
        old.save(path, dict(state=state))


def search(d, labels, tag, held=None):
    path = WORK / 'searches' / (tag + '.json')
    if path.exists():
        return old.read(path)
    training = old.training_rows(labels, held)
    floor = metrics(d, BASE, run_account(d, BASE), training)
    chosen, chosen_metrics = dict(BASE), floor
    branch, branch_metrics = dict(BASE), floor
    seen, rounds = {old.key(BASE)}, []
    for number in range(1, 6):
        layer, candidates = proposals(branch, seen, number)
        if not candidates:
            continue
        registration = dict(tag=tag, heldout=held, round=number, layer=layer,
            training_ids=sorted(r['id'] for r in training), candidates=candidates,
            incumbent=chosen, branch=branch, prereg=old.sha(PREREG), logic=source_functions())
        regpath = WORK / 'registrations' / (tag + '_r' + str(number) + '.json')
        if regpath.exists() and old.read(regpath) != registration:
            raise AssertionError('IE17 round registration changed')
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
            results.append(dict(config=cfg, metrics=measure, admissible=eligible, account_id=account['id'],
                                account=account['summary'], card=card))
            if eligible and tuple(measure['rank']) > tuple(chosen_metrics['rank']):
                chosen, chosen_metrics = cfg, measure
            print(tag, 'round', number, layer, old.key(cfg), 'bought', measure['bought'],
                  'weighted', round(measure['weighted_coverage'], 4), 'eligible', eligible, flush=True)
        options = [r for r in results if r['config']['priority'] == 'continuous'] if number == 1 else \
            [dict(config=branch, metrics=branch_metrics), *results]
        best = max(options, key=lambda r: tuple(r['metrics']['rank']))
        branch, branch_metrics = best['config'], best['metrics']
        rounds.append(dict(round=number, layer=layer, registration=str(regpath.relative_to(ROOT)),
            candidates=results, selected=chosen, metrics=chosen_metrics, branch=branch, branch_metrics=branch_metrics))
        old.save(WORK / 'rounds' / (tag + '_r' + str(number) + '.json'), rounds[-1])
        gc.collect()
    result = dict(tag=tag, heldout=held, config=chosen, metrics=chosen_metrics, floor=floor,
                  branch=branch, branch_metrics=branch_metrics, rounds=rounds)
    old.save(path, result)
    return old.clean(result)


for _name in ('WORK', 'PLAN', 'PREREG', 'PREFIX', 'SEEDS', 'BASE', 'FIXED', 'Data',
              'build', 'score', 'diagnosis', 'metrics', 'search', 'source_functions', 'seal'):
    setattr(shared, _name, globals()[_name])
run_account = shared.run_account
signal_reference = shared.signal_reference
cross_validation = shared.cross_validation
run_search = shared.run_search


def initial_diagnosis():
    seal()
    d = Data()
    labels = [r for r in old.labels(d) if r['side'] > 0]
    account = run_account(d, BASE)
    reference = old.read(previous.WORK / 'accounts' / (REFERENCE['account_id'] + '.json'))
    if account['trades'] != reference['trades'] or account['curve'] != reference['curve']:
        raise AssertionError('fixed IE16 account changed')
    result = diagnosis(d, BASE, account, labels)
    if result['counts'] != REFERENCE['remaining']:
        raise AssertionError('IE16 baseline diagnosis changed')
    result['baseline_identical'] = True
    output('diagnosis', result)
    print('baseline', old.card_summary(result['card']['rows']), 'blocks', result['counts'], flush=True)


def finalize():
    seal()
    d = Data()
    labels = old.labels(d)
    longs = [r for r in labels if r['side'] > 0]
    fitted = old.read(REPORTS / (PREFIX + 'true.json'))
    cfg = fitted['fit']['config']
    account = run_account(d, cfg)
    card = score(d, cfg, account, labels)
    true = old.card_summary([r for r in card['rows'] if r['side'] > 0])
    random_order, random_entries = [], []
    for k in range(20):
        random = run_account(d, cfg, random_order=150000 + k)
        random_order.append(dict(seed=150000 + k, account_id=random['id'],
            summary=old.card_summary(score(d, cfg, random, longs)['rows']), account=random['summary']))
        random = run_account(d, cfg, placebo=151000 + k)
        random_entries.append(dict(seed=151000 + k, account_id=random['id'], account=random['summary']))
        print('controls', k + 1, '/ 20', flush=True)
    bought_mean = float(np.mean([r['summary']['bought'] for r in random_order]))
    weight_mean = float(np.mean([r['summary']['weighted_coverage'] for r in random_order]))
    controls = dict(order_random=random_order, entry_random=random_entries,
        buy_expectation=bought_mean, weight_expectation=weight_mean,
        buy_ratio=true['bought'] / bought_mean if bought_mean else None,
        clearly_better=true['bought'] >= bought_mean + 3 and true['weighted_coverage'] >= weight_mean + .05,
        placebo_median=float(np.median([r['account']['total'] for r in random_entries])),
        placebo_p90=float(np.percentile([r['account']['total'] for r in random_entries], 90)))
    output('random', controls)
    shuffled = [old.read(REPORTS / (PREFIX + 'shuffle_' + str(s) + '.json')) for s in SEEDS]
    anti = {}
    for kind in ('full', 'cv'):
        real = fitted['cv']['summary'] if kind == 'cv' else fitted['fit']['metrics']
        samples = [r['cv']['summary'] if kind == 'cv' else r['fit']['metrics'] for r in shuffled]
        best_count, best_weight = max(r['bought'] for r in samples), max(r['weighted_coverage'] for r in samples)
        anti[kind] = dict(true=real, best_count=best_count, best_weight=best_weight,
            passed=real['weighted_coverage'] > best_weight,
            ie16_strict=real['bought'] >= best_count + 3 and real['weighted_coverage'] >= best_weight + .05)
    anti['passed'] = anti['cv']['passed']
    anti['ie16_strict'] = anti['full']['ie16_strict'] and anti['cv']['ie16_strict']
    baseline_account = run_account(d, BASE)
    baseline_card = score(d, BASE, baseline_account, labels)
    baseline_long = old.card_summary([r for r in baseline_card['rows'] if r['side'] > 0])
    held_rows = []
    for h in old.HALVES:
        held_rows.extend(score(d, BASE, baseline_account, [r for r in longs if r['half'] == h])['rows'])
    best = sorted((r for r in account['trades'] if r['why'] != 'end'), key=lambda tr: -tr['ret'])[:2]
    drop = run_account(d, cfg, drop=[(r['entry'], r['code']) for r in best])
    sig = signal_reference(d, cfg, longs)
    build(d, cfg)
    widths = old.signal_baseline(d, cfg, longs)['widths']
    matched = old.matched_signal_random(d, cfg, longs)
    diag = diagnosis(d, cfg, account, longs)
    output('final_diagnosis', diag)
    before = old.read(REPORTS / (PREFIX + 'diagnosis.json'))['card']['rows']
    lookup = {r['id']: r for r in diag['card']['rows']}
    competing = [r for r in before if r['selection_block'] == '被别的信号抢先']
    rescue = [dict(id=r['id'], code=r['code'], bought=lookup[r['id']]['bought'],
        entry=lookup[r['id']]['actual_entry'], remaining=lookup[r['id']]['selection_block']) for r in competing]
    improved = true['bought'] >= baseline_long['bought'] and \
        true['weighted_coverage'] >= baseline_long['weighted_coverage'] and \
        (true['bought'] > baseline_long['bought'] or true['weighted_coverage'] > baseline_long['weighted_coverage'])
    human_reference = old.read(REPORTS / (old.PREFIX + 'long.json'))
    result = dict(config=cfg, fixed=FIXED, account_id=account['id'], account=account['summary'], card=card,
        long=true, baseline=dict(account=baseline_account['summary'], card=baseline_card, long=baseline_long,
            fixed_cv=old.card_summary(held_rows)), controls=controls,
        signal=dict(**sig, widths=widths, lift=true['signal'] / sig['expected'] if sig['expected'] else 0., matched=matched),
        cv=fitted['cv'], shuffled=[dict(seed=s, full=r['fit']['metrics'], cv=r['cv']['summary'])
                                   for s, r in zip(SEEDS, shuffled)], anti=anti,
        drop2=dict(removed=best, account_id=drop['id'], summary=drop['summary'],
                   beats_random=drop['summary']['total'] > controls['placebo_median']),
        human=human_reference['human'], human_source=old.sha(REPORTS / (old.PREFIX + 'long.json')),
        remaining=diag['counts'], rescued=dict(total=len(rescue), bought=sum(r['bought'] for r in rescue), rows=rescue),
        selection_improved=improved, qualified_improvement=improved and anti['passed'],
        retained_config=cfg if improved and anti['passed'] else BASE,
        ie16_reference=old.sha(REPORTS / (previous.PREFIX + 'final.json')),
        exploratory_config=fitted['fit']['branch'], exploratory_metrics=fitted['fit']['branch_metrics'])
    output('final', result)
    for round_ in fitted['fit']['rounds']:
        output('round' + str(round_['round']), round_)
    print('final', true, 'rescued', result['rescued']['bought'], 'anti', anti['passed'], flush=True)


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
