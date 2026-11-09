"""IE19: successful daily entry limits and primary/secondary queue shapes."""
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import replace
import gc
import importlib.util
from pathlib import Path
import resource
import time

import numpy as np

from studies.trader_replication import martin_continue_ie18 as previous

old = previous.old
ROOT, REPORTS, FIXED = previous.ROOT, previous.REPORTS, previous.FIXED
WORK = REPORTS / 'ie19_work'
PREFIX = 'strong_continue_ie19_'
PLAN = ROOT / 'studies/martin_luk/notes/PLAN_IE19_CN.md'
PREREG = ROOT / 'studies/martin_luk/notes/PREREG_IE19_CN.md'
SEEDS, REFERENCE = previous.SEEDS, previous.REFERENCE
BASE = dict(previous.BASE, daily=0, shape='flat', combine='primary', secondary='')
Data = previous.Data
admissible, better = previous.admissible, previous.better

# Isolate the reused orchestration and diagnostics from all earlier modules.
_spec = importlib.util.spec_from_file_location(__name__ + '_shared', previous.__file__)
shared = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(shared)


def output(name, value):
    old.save(REPORTS / (PREFIX + name + '.json'), value)


def prepare():
    path = WORK / 'prepared.json'
    if path.exists():
        return
    d = Data()
    inputs = set()
    for group in (d.px, d.f, d.extra, d.strength, d.wave):
        for a in group.values():
            if isinstance(a, np.memmap):
                inputs.add(Path(a.filename))
    inputs.update((previous.WORK / 'prepared.json', previous.previous.WORK / 'prepared.json',
                   REPORTS / (previous.previous.PREFIX + 'final.json'), old.LEDGER))
    old.save(path, dict(source=old.sha(__file__), shape=d.px['close'].shape,
        inputs={str(p.relative_to(ROOT)): old.sha(p) for p in sorted(inputs)},
        input_snapshot=old.sha(WORK / 'initial_inputs.json')))
    print('reused cached inputs', len(inputs), 'shape', d.px['close'].shape, flush=True)


def queue_scores(s, d, cfg, signals):
    """Percentiles use every completed-night signal, before next-day triggers."""
    indices = np.flatnonzero(signals)
    x = d.strength['extension'][s, indices]
    launch = -np.maximum(np.maximum(-x, x - 2), 0) if cfg['shape'] == 'flat' else 1 - np.abs(x - 1)
    rank = previous.previous.percentile
    primary = (rank(launch) + rank(d.f['money'][s, indices])) / 2
    fields = dict(stage=previous.STAGES['pullback'], flow=previous.FLOWS['peer'])
    secondary = np.mean([rank(d.wave[n][s, indices]) for n in fields[cfg['secondary']]], axis=0) \
        if cfg['secondary'] else np.full(len(indices), .5)
    return indices, primary, secondary


def queue_keys(primary, secondary, codes, combine):
    if combine == 'lex':
        bands = np.floor(10 * primary + 1e-12).astype(int)
        return [(-int(b), -float(s), -float(p), str(c)) for b, s, p, c in zip(bands, secondary, primary, codes)]
    score = primary * (.5 + .5 * secondary) if combine == 'multiply' else primary
    return [(-float(v), str(c)) for v, c in zip(score, codes)]


def build(d, cfg):
    ident = old.key(cfg)
    cachekey = old.key(dict(cfg=cfg, short=None))
    if d.latest is not None and d.latest[0] == ident:
        d.built[cachekey] = d.latest[1]
        return d.latest[1]
    if d.template is None:
        d.template = previous.previous.build(d, REFERENCE['retained_config'])
    b = dict(d.template)
    book = [[] for _ in b['book']]
    for t in range(d.start, d.end):
        s = t - 1
        indices, primary, secondary = queue_scores(s, d, cfg, b['signals']['long'][s])
        keys = dict(zip(indices, queue_keys(primary, secondary, np.asarray(d.codes)[indices], cfg['combine'])))
        book[2 * t] = [(keys[e[1]], *e[1:]) for e in b['book'][2 * t]]
    b.update(book=book)
    d.built.clear()
    d.built[cachekey] = b
    d.latest = ident, b
    return b


def run_account(d, cfg, random_order=None, placebo=None, drop=None, human=None, fresh=False):
    ident = old.key(dict(cfg=cfg, fixed=FIXED, random_order=random_order, placebo=placebo, drop=drop, human=human))
    path = WORK / 'accounts' / (ident + '.json')
    if path.exists() and not fresh:
        return old.read(path)
    b = build(d, cfg)
    book = b['book']
    rules = replace(old.policy(FIXED), max_new_long=cfg['daily'])
    if human is not None:
        book = [[] for _ in book]
        for label in human:
            if label['code'] in d.ci:
                t, j = label['anchor'], d.ci[label['code']]
                event = old.order(t, j, 1, d, FIXED, direct=True)
                if event is not None:
                    book[2 * t + 1].append(event)
        rules = replace(rules, intraday_kinds=())
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
        pool[2:] = np.repeat(b['pool'][:-1], 2, axis=0)
    track = {}
    curve, days, trades = old.system.simulate(d.phase_px(), d.management, rules, book, *old.panels.WINDOW,
        audit=True, track=track, placebo=np.random.default_rng(placebo) if placebo is not None else None, pool=pool)
    curve, days = curve[1::2], days[1::2]
    counts = Counter(tr['entry'] for tr in trades if tr['side'] > 0)
    if cfg['daily'] and any(n > cfg['daily'] for n in counts.values()):
        raise AssertionError('successful daily entry limit exceeded')
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
                raise AssertionError('execution outside the real daily range')
    result = old.clean(dict(id=ident, config=cfg, fixed=FIXED, curve=curve, dates=days, trades=trades,
        summary=old.summarize_account(curve, days, trades, track), rotations=[], fills_valid=True,
        daily_entries=dict(counts)))
    if not fresh:
        old.save(path, result)
    return result


def score(d, cfg, account, labels, supplied=False):
    build(d, cfg)
    return old.score(d, cfg, account, labels, supplied=supplied)


def diagnosis(d, cfg, account, labels):
    result = shared._diagnose(d, cfg, account, labels)
    b = build(d, cfg)
    for row in result['card']['rows']:
        if row['bought'] or not row['signal'] or row['code'] not in d.ci:
            continue
        offers = row.get('offered', [])
        if not offers:
            j = d.ci[row['code']]
            nights = [t - 1 for t in range(row['lo'], row['hi'] + 1) if t >= d.start]
            signaled = [s for s in nights if b['signals']['long'][s, j]]
            row['selection_block'] = '市况' if signaled and not any(b['market'][s] for s in signaled) else '触发'
        else:
            actionable = [v for v in offers if not v['same_held'] and not v['actual_same_day']]
            for v in offers:
                v['daily_limit'] = cfg['daily']
                v['daily_limit_reached'] = bool(cfg['daily'] and len(v['earlier']) >= cfg['daily'])
            if actionable and all(v['daily_limit_reached'] for v in actionable):
                row['selection_block'] = '每日新仓上限'
                row['selection_detail'] = '每次可独立尝试时，排在前面的成功新仓已用完当日次数'
            elif row['selection_block'] == '被别的信号抢先' and not any(
                    v['earlier'] and v['morning'] < FIXED['max_open'] for v in actionable):
                row['selection_block'] = '没仓位'
    result['counts'] = dict(Counter(r['selection_block'] for r in result['card']['rows'] if not r['bought']))
    return result


def proposals(number, pace, shapes):
    if number == 1:
        return [dict(BASE, daily=n) for n in (1, 2, 3, 4)] + [dict(BASE)]
    if number in (2, 3):
        cfg = dict(BASE, shape='triangle' if number == 3 else 'flat')
        choices = [dict(cfg, combine=c, secondary=s) for c in ('lex', 'multiply') for s in ('stage', 'flow')]
        return [cfg, *choices] if number == 3 else [*choices, dict(BASE)]
    if pace is None:
        return []
    ordered = sorted(shapes, key=lambda r: (-r['metrics']['weighted_coverage'], -r['metrics']['bought']))
    choices = [dict(r['config'], daily=pace['config']['daily']) for r in ordered]
    return choices[:5] if number == 4 else choices[5:10]


def source_functions():
    paths = {Path(__file__), Path(previous.__file__), Path(previous.previous.__file__),
             Path(previous.previous.previous.__file__), Path(shared.shared.__file__),
             Path(old.__file__), Path(old.system.__file__), Path(old.lib.__file__)}
    return {str(p.relative_to(ROOT)): old.sha(p) for p in sorted(paths)}


def seal():
    state = dict(source=source_functions(), plan=old.sha(PLAN), prereg=old.sha(PREREG),
        prepared=old.sha(WORK / 'prepared.json'), baseline=BASE, fixed=FIXED)
    path = WORK / 'run_source.json'
    if path.exists():
        if old.read(path) != state:
            raise AssertionError('IE19 frozen implementation or inputs changed')
    else:
        old.save(path, state)
        (WORK / 'research_source.txt').write_text(Path(__file__).read_text())


def search(d, labels, tag, held=None):
    path = WORK / 'searches' / (tag + '.json')
    if path.exists():
        return old.read(path)
    training = old.training_rows(labels, held)
    floor = shared.measure(d, BASE, training)
    chosen, exploration = floor, floor
    pace, shapes, rounds = None, [], []
    for number in range(1, 6):
        choices = proposals(number, pace, shapes)
        if not choices:
            continue
        registration = dict(tag=tag, heldout=held, round=number, candidates=choices,
            training_ids=sorted(r['id'] for r in training), incumbent=chosen['config'],
            pace=pace['config'] if pace else None, shapes=[r['config'] for r in shapes],
            logic=source_functions(), prereg=old.sha(PREREG))
        regpath = WORK / 'registrations' / (tag + '_r' + str(number) + '.json')
        if regpath.exists() and old.read(regpath) != registration:
            raise AssertionError('IE19 candidate registration changed')
        if not regpath.exists():
            old.save(regpath, registration)
        results = []
        for cfg in choices:
            result = shared.measure(d, cfg, training)
            eligible = admissible(result['metrics'], floor['metrics'])
            effective = eligible and better(result['metrics'], floor['metrics'])
            result.update(admissible=eligible, effective=effective)
            results.append(result)
            if eligible and better(result['metrics'], chosen['metrics']):
                chosen = result
            if better(result['metrics'], exploration['metrics']):
                exploration = result
            if number == 1 and effective and (pace is None or better(result['metrics'], pace['metrics'])):
                pace = result
            if number in (2, 3) and effective:
                shapes.append(result)
            print(tag, 'round', number, cfg['daily'], cfg['shape'], cfg['combine'], cfg['secondary'],
                  'bought', result['metrics']['bought'], 'weight', round(result['metrics']['weighted_coverage'], 5), flush=True)
        round_ = dict(round=number, registration=str(regpath.relative_to(ROOT)), candidates=results,
                      selected=chosen['config'], metrics=chosen['metrics'])
        rounds.append(round_)
        old.save(WORK / 'rounds' / (tag + '_r' + str(number) + '.json'), round_)
        gc.collect()
    result = dict(tag=tag, heldout=held, config=chosen['config'], metrics=chosen['metrics'], floor=floor['metrics'],
        pace=pace['config'] if pace else None, effective_shapes=[r['config'] for r in shapes], rounds=rounds,
        exploratory_config=exploration['config'], exploratory_metrics=exploration['metrics'])
    old.save(path, result)
    return old.clean(result)


for _name in ('WORK', 'PREFIX', 'PLAN', 'PREREG', 'BASE', 'FIXED', 'Data', 'build', 'run_account',
              'score', 'diagnosis', 'proposals', 'source_functions', 'seal', 'search', 'output'):
    setattr(shared, _name, globals()[_name])
for _name in ('WORK', 'PREFIX', 'BASE', 'FIXED', 'Data', 'build', 'score', 'run_account'):
    setattr(shared.shared, _name, globals()[_name])
cross_validation, run_search = shared.cross_validation, shared.run_search
initial_diagnosis, finalize = shared.initial_diagnosis, shared.finalize
offline = shared.offline


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
