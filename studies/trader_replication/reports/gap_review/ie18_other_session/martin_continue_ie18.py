"""IE18: a premier pool union and causal launch ordering; IE14 execution is fixed."""
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

from studies.trader_replication import martin_continue_ie17 as previous

old = previous.old
selection = previous.previous
ROOT, REPORTS, FIXED = previous.ROOT, previous.REPORTS, previous.FIXED
WORK = REPORTS / 'ie18_work'
PLAN = ROOT / 'studies/martin_luk/notes/PLAN_IE18_CN.md'
PREREG = ROOT / 'studies/martin_luk/notes/PREREG_IE18_CN.md'
PREFIX = 'strong_continue_ie18_'
SEEDS = previous.SEEDS
REFERENCE = old.read(REPORTS / (previous.PREFIX + 'final.json'))
BASE = dict(REFERENCE['retained_config'], premier=0, launch_shape='plateau')
TYPE_INTERVALS = dict(pullback=[0, 1.5], breakout=[.5, 2], ep=[0, 3])
BLOCKS = ('被别的信号抢先', '股票池', '触发', '市况', '没仓位', '买点', '领涨状态')

_spec = importlib.util.spec_from_file_location(__name__ + '_shared', selection.previous.__file__)
shared = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(shared)
_diagnosis, _metrics = shared.diagnosis, shared.metrics


def output(name, value):
    old.save(REPORTS / (PREFIX + name + '.json'), value)


def offline():
    def denied(*args, **kwargs):
        raise RuntimeError('IE18 uses cached inputs only')
    socket.socket = denied
    socket.create_connection = denied


def quiet_fields(close, volume, benchmark):
    """Trailing close-known observations for one bounded security block."""
    returns = np.full(close.shape, np.nan)
    returns[1:] = old.lib.divide(close[1:], close[:-1]) - 1
    index = np.full(len(benchmark), np.nan)
    index[1:] = old.lib.divide(benchmark[1:], benchmark[:-1]) - 1
    relative = returns - index[:, None]
    ratio = np.full(close.shape, np.nan)
    for j in range(close.shape[1]):
        ratio[:, j] = old.lib.divide(volume[:, j], old.lag(old.lib.roll(volume[:, j], 3)))
    return dict(quiet_return=-relative, quiet_volume=-ratio)


def prepare():
    if not (WORK / 'initial_inputs.json').exists():
        raise RuntimeError('record existing inputs before IE18')
    if (WORK / 'prepared.json').exists():
        return
    (WORK / 'tmp').mkdir(exist_ok=True)
    d = previous.Data()
    names = ('quiet_return', 'quiet_volume', 'history')
    arrays = {n: np.lib.format.open_memmap(WORK / (n + '.npy'), mode='w+', dtype='float32',
                                         shape=d.px['close'].shape) for n in names}
    arrays['history'][:] = np.nan
    volume = np.load(old.WORK / 'volume.npy', mmap_mode='r')
    benchmark = np.load(old.OLD / 'qqq.npy', mmap_mode='r')
    for start in range(0, len(d.codes), 32):
        sl = slice(start, start + 32)
        fields = quiet_fields(np.asarray(d.px['close'][:, sl], float),
                              np.asarray(volume[:, sl], float), benchmark)
        for n, values in fields.items():
            arrays[n][:, sl] = values
    inputs = {}
    for j, code in enumerate(d.codes):
        path = old.OLD / 'stocks' / (code + '.npz')
        if path.exists():
            with np.load(path) as z:
                values = z['extra_h4_history']
                if len(values) != len(d.days):
                    raise AssertionError('cached history row alignment changed')
                arrays['history'][:, j] = values
            inputs[str(path.relative_to(ROOT))] = old.sha(path)
        if j % 500 == 0:
            print('prepare history', j, '/', len(d.codes), flush=True)
    for a in arrays.values():
        a.flush()
    paths = [old.OLD / 'qqq.npy', old.WORK / 'prepared.json', selection.previous.WORK / 'prepared.json',
             previous.WORK / 'prepared.json', REPORTS / (previous.PREFIX + 'final.json'),
             *old.WORK.glob('*.npy'), *selection.previous.WORK.glob('*.npy'),
             *previous.WORK.glob('*.npy'),
             *(old.OLD / 'panel' / (n + '.npy') for n in ('open', 'high', 'low', 'close'))]
    inputs.update({str(p.relative_to(ROOT)): old.sha(p) for p in paths})
    old.save(WORK / 'prepared.json', dict(shape=d.px['close'].shape, inputs=inputs,
        features={n: old.sha(WORK / (n + '.npy')) for n in names}, source=old.sha(__file__)))


class Data(previous.Data):
    def __init__(self):
        super().__init__()
        self.ie18 = {n: np.load(WORK / (n + '.npy'), mmap_mode='r')
                     for n in ('quiet_return', 'quiet_volume', 'history')}
        if not all((old.WORK / ('phase_' + n + '.npy')).exists() for n in self.px):
            raise RuntimeError('IE18 requires the existing read-only execution cache')


def pool_union(money, adr, cfg):
    minimum_money, minimum_adr = selection.POOLS[cfg['pool']]
    pool = (money >= minimum_money) & (adr > minimum_adr)
    if cfg['premier']:
        pool |= money >= cfg['premier']
    return pool


def selection_arrays(d, cfg):
    b = selection.selection_arrays(d, cfg)
    b['pool'] = pool_union(d.f['money'], d.f['adr'], cfg)
    signal = b['pool'] & b['trend'] & b['setup']
    if cfg['watch']:
        signal &= b['watched']
    b['signals'] = dict(long=signal, short=np.zeros_like(signal))
    return b


def launch_values(s, d, cfg):
    interval = cfg['interval']
    if isinstance(interval, dict):
        types = np.where(d.f['ep'][s] == 1, 'ep',
                         np.where(d.f['pullback'][s] == 1, 'pullback', 'breakout'))
        lo = np.array([interval[k][0] for k in types])
        hi = np.array([interval[k][1] for k in types])
    else:
        lo, hi = interval
    x = d.strength['extension'][s]
    shape = cfg['launch_shape']
    if shape == 'plateau':
        return -np.maximum(np.maximum(lo - x, x - hi), 0)
    target = (lo + hi) / 2 if shape == 'center' else lo if shape == 'lower' else hi
    return -abs(x - target)


def strength_scores(s, d, cfg, signals):
    candidates = np.flatnonzero(signals)
    if not len(candidates):
        return np.array([], float)
    raw = dict(launch=launch_values(s, d, cfg), money=d.f['money'][s], history=d.ie18['history'][s])
    ranks = {n: previous.percentile(a[candidates]) for n, a in raw.items()}
    ranks['quiet'] = (previous.percentile(d.ie18['quiet_return'][s, candidates]) +
                      previous.percentile(d.ie18['quiet_volume'][s, candidates])) / 2
    return np.mean([ranks[n] for n in cfg['components']], axis=0)


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
        signals = b['signals']['long'][s]
        candidates = np.flatnonzero(signals)
        scores = strength_scores(s, d, cfg, signals)
        for k, j in enumerate(candidates):
            event = selection.order(t, int(j), d, cfg)
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


def proposals(cfg, counts, seen, number):
    if number == 1:
        layer, values = 'premier', (100e6, 500e6, 1000e6)
    elif number == 2:
        layer, values = 'interval', ([0, 1.5], [.5, 2], [0, 3], TYPE_INTERVALS)
    elif number == 3:
        layer, values = 'components', ([*cfg['components'], 'quiet'], [*cfg['components'], 'history'])
    elif number == 4:
        block = max(BLOCKS, key=lambda k: counts.get(k, 0))
        layer, values = {
            '被别的信号抢先': ('launch_shape', ('center', 'lower', 'upper')),
            '没仓位': ('launch_shape', ('center', 'lower', 'upper')),
            '股票池': ('pool', ('soft_adr', 'soft_both', 'soft_middle', 'liquid')),
            '触发': ('setup', ('retest', 'support', 'wick', 'reclaim', 'high20')),
            '买点': ('setup', ('retest', 'support', 'wick', 'reclaim', 'high20')),
            '市况': ('market', ('either21', 'either50', 'feedback', 'both21')),
            '领涨状态': ('trend', ('early', 'medium', 'stack', 'graded', 'all')),
        }[block]
    else:
        return 'exhausted', []
    choices = [dict(cfg, **{layer: value}) for value in values]
    return layer, [c for c in choices if c != cfg and old.key(c) not in seen][:5]


def source_functions():
    paths = dict(source=Path(__file__), previous=Path(previous.__file__), selection=Path(selection.__file__),
                 orchestration=Path(shared.__file__), prior=Path(old.__file__),
                 engine=Path(old.system.__file__), features=Path(old.lib.__file__), ledger=old.LEDGER)
    return {name: old.sha(path) for name, path in paths.items()}


def seal():
    state = dict(functions=source_functions(), prereg=old.sha(PREREG), plan=old.sha(PLAN), fixed=FIXED,
                 baseline=BASE, prepared=old.sha(WORK / 'prepared.json'))
    path = WORK / 'run_source.json'
    if path.exists():
        if old.read(path)['state'] != state:
            raise AssertionError('IE18 registered logic changed; do not reuse evaluated results')
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
    for number in range(1, 5):
        layer, candidates = proposals(branch, branch_metrics['blocks'], seen, number)
        if not candidates:
            continue
        registration = dict(tag=tag, heldout=held, round=number, layer=layer, counts=branch_metrics['blocks'],
            training_ids=sorted(r['id'] for r in training), candidates=candidates,
            incumbent=chosen, branch=branch, prereg=old.sha(PREREG), logic=source_functions())
        regpath = WORK / 'registrations' / (tag + '_r' + str(number) + '.json')
        if regpath.exists() and old.read(regpath) != registration:
            raise AssertionError('IE18 round registration changed')
        if not regpath.exists():
            old.save(regpath, registration)
        results = []
        for cfg in candidates:
            seen.add(old.key(cfg))
            account = run_account(d, cfg)
            measure = metrics(d, cfg, account, training)
            card = score(d, cfg, account, training)
            eligible = measure['bought'] >= floor['bought'] and \
                measure['weighted_coverage'] + 1e-12 >= floor['weighted_coverage']
            results.append(dict(config=cfg, metrics=measure, admissible=eligible, account_id=account['id'],
                                account=account['summary'], card=card))
            if eligible and tuple(measure['rank']) > tuple(chosen_metrics['rank']):
                chosen, chosen_metrics = cfg, measure
            print(tag, 'round', number, layer, old.key(cfg), 'bought', measure['bought'],
                  'weighted', round(measure['weighted_coverage'], 4), 'eligible', eligible, flush=True)
        best = max([dict(config=branch, metrics=branch_metrics), *results], key=lambda r: tuple(r['metrics']['rank']))
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
        raise AssertionError('fixed IE17 account changed')
    result = diagnosis(d, BASE, account, labels)
    if result['counts'] != REFERENCE['remaining']:
        raise AssertionError('IE17 baseline diagnosis changed')
    result['baseline_identical'] = True
    output('diagnosis', result)
    print('baseline', old.card_summary(result['card']['rows']), 'blocks', result['counts'], flush=True)


def pool_attribution(d, cfg, before, after):
    added = pool_union(d.f['money'], d.f['adr'], cfg) & ~pool_union(d.f['money'], d.f['adr'], BASE)
    b = build(d, cfg)
    additions = added & b['signals']['long']
    span = slice(d.start - 1, d.end - 1)
    previous_rows = {r['id']: r for r in before}
    gained = [r['id'] for r in after if r['bought'] and not previous_rows[r['id']]['bought']]
    lost = [r['id'] for r in after if not r['bought'] and previous_rows[r['id']]['bought']]
    pool_rescued = [r['id'] for r in after if r['bought'] and
                    previous_rows[r['id']]['selection_block'] == '股票池']
    return dict(config=cfg, pool_security_nights=int(added[span].sum()),
        pool_unique=int(added[span].any(axis=0).sum()), new_signals=int(additions[span].sum()),
        new_signal_unique=int(additions[span].any(axis=0).sum()),
        new_triggers=int((additions & b['triggers'])[span].sum()), gained=gained, lost=lost,
        pool_rescued=pool_rescued)


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
                          passed=real['weighted_coverage'] > best_weight)
    anti['passed'] = anti['cv']['passed']
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
    cohorts = {}
    for block in ('被别的信号抢先', '股票池'):
        cohort = [r for r in before if r['selection_block'] == block]
        rescue = [dict(id=r['id'], code=r['code'], bought=lookup[r['id']]['bought'],
            entry=lookup[r['id']]['actual_entry'], remaining=lookup[r['id']]['selection_block']) for r in cohort]
        cohorts[block] = dict(total=len(rescue), bought=sum(r['bought'] for r in rescue), rows=rescue)
    attribution = []
    for candidate in fitted['fit']['rounds'][0]['candidates']:
        c = candidate['config']
        rows = diagnosis(d, c, run_account(d, c), longs)['card']['rows']
        attribution.append(pool_attribution(d, c, before, rows))
    output('premier', attribution)
    counter_cfg = dict(cfg, premier=0)
    counter = run_account(d, counter_cfg)
    counter_diag = diagnosis(d, counter_cfg, counter, longs)
    counter_rows = {r['id']: r for r in counter_diag['card']['rows']}
    premier_effect = dict(config=counter_cfg, account_id=counter['id'],
        summary=old.card_summary(counter_diag['card']['rows']),
        gained=[r['id'] for r in diag['card']['rows'] if r['bought'] and not counter_rows[r['id']]['bought']],
        lost=[r['id'] for r in diag['card']['rows'] if not r['bought'] and counter_rows[r['id']]['bought']])
    improved = true['bought'] >= baseline_long['bought'] and \
        true['weighted_coverage'] >= baseline_long['weighted_coverage'] and \
        (true['bought'] > baseline_long['bought'] or true['weighted_coverage'] > baseline_long['weighted_coverage'])
    result = dict(config=cfg, fixed=FIXED, account_id=account['id'], account=account['summary'], card=card,
        long=true, baseline=dict(account=baseline_account['summary'], card=baseline_card, long=baseline_long,
            fixed_cv=old.card_summary(held_rows), historical_cv=REFERENCE['cv']['summary']), controls=controls,
        signal=dict(**sig, widths=widths, lift=true['signal'] / sig['expected'] if sig['expected'] else 0., matched=matched),
        cv=fitted['cv'], shuffled=[dict(seed=s, full=r['fit']['metrics'], cv=r['cv']['summary'])
                                   for s, r in zip(SEEDS, shuffled)], anti=anti,
        drop2=dict(removed=best, account_id=drop['id'], summary=drop['summary'],
                   beats_random=drop['summary']['total'] > controls['placebo_median']),
        human=REFERENCE['human'], human_source=REFERENCE['human_source'], remaining=diag['counts'],
        cohorts=cohorts, premier=attribution, premier_effect=premier_effect,
        selection_improved=improved, qualified_improvement=improved and anti['passed'],
        retained_config=cfg if improved and anti['passed'] else BASE,
        ie17_reference=old.sha(REPORTS / (previous.PREFIX + 'final.json')),
        exploratory_config=fitted['fit']['branch'], exploratory_metrics=fitted['fit']['branch_metrics'])
    output('final', result)
    for round_ in fitted['fit']['rounds']:
        output('round' + str(round_['round']), round_)
    print('final', true, 'anti', anti['passed'], flush=True)


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
