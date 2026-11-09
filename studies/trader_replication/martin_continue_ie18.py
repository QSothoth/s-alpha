"""IE18: causal wave progress, changing peer activity, and opening rotation."""
from __future__ import annotations

import argparse
from dataclasses import replace
import gc
import importlib.util
import inspect
from pathlib import Path
import resource
import socket
import time

import numpy as np

from studies.trader_replication import martin_continue_ie17 as previous

old = previous.old
ROOT, REPORTS, FIXED = previous.ROOT, previous.REPORTS, previous.FIXED
WORK = REPORTS / 'ie18_work'
PREFIX = 'strong_continue_ie18_'
PLAN = ROOT / 'studies/martin_luk/notes/PLAN_IE18_CN.md'
PREREG = ROOT / 'studies/martin_luk/notes/PREREG_IE18_CN.md'
SEEDS = previous.SEEDS
REFERENCE = old.read(REPORTS / (previous.PREFIX + 'final.json'))
BASE = dict(REFERENCE['retained_config'], stage='', flow='', rotation='', interaction=False)
STAGES = dict(full=('count', 'advance', 'higher'), pullback=('count', 'higher'),
              progress=('advance',), age=('age',))
FLOWS = dict(peer=('peer_money', 'peer_return'), own=('own_money',), lead=('lead',),
             full=('peer_money', 'peer_return', 'own_money', 'lead'))
FIELDS = ('origin', 'count', 'advance', 'higher', 'age', 'own_money', 'acceleration',
          'flow_age', 'peer_money', 'peer_return', 'lead')


def output(name, value):
    old.save(REPORTS / (PREFIX + name + '.json'), value)


def offline():
    def denied(*args, **kwargs):
        raise RuntimeError('IE18 uses cached inputs only')
    socket.socket = denied
    socket.create_connection = denied


def wave_fields(close, high, low, e9, e21, adr):
    """A wave owns its first breakout and distinct, completed pullback episodes."""
    out = {n: np.full(close.shape, np.nan) for n in ('origin', 'count', 'advance', 'higher', 'age')}
    for j in range(close.shape[1]):
        c, h, l = close[:, j], high[:, j], low[:, j]
        upper = old.lag(old.lib.roll(h, 20, 'max'))
        lower = old.lag(old.lib.roll(l, 20, 'min'))
        wide_h = old.lag(old.lib.roll(h, 60, 'max'))
        wide_l = old.lag(old.lib.roll(l, 60, 'min'))
        start, count, below = -1, 0, 0
        pivot = floor = unit = trough = prior = np.nan
        pulling = False
        for s in range(1, len(c)):
            if not all(np.isfinite(v) and v > 0 for v in (c[s], h[s], l[s], e9[s, j], e21[s, j], adr[s, j])):
                continue
            below = below + 1 if c[s] < e21[s, j] else 0
            if start >= 0 and (c[s] < floor or below >= 3):
                start, pulling = -1, False
            compact = (upper[s] / lower[s] - 1 <= .75 * (wide_h[s] / wide_l[s] - 1)
                       or upper[s] / lower[s] - 1 <= 2 * adr[s - 1, j] / 100)
            crossed = c[s] > upper[s] and np.isfinite(upper[s - 1]) and c[s - 1] <= upper[s - 1]
            if start < 0 and compact and crossed:
                start, count, pulling, below = s, 0, False, 0
                pivot, floor, unit = upper[s], lower[s], adr[s, j] / 100
                trough = prior = np.nan
            if start < 0:
                continue
            line = max(e9[s, j], e21[s, j])
            if s > start:
                if not pulling and l[s] <= line and c[s - 1] > max(e9[s - 1, j], e21[s - 1, j]):
                    count, pulling, trough = count + 1, True, l[s]
                elif pulling:
                    trough = min(trough, l[s])
                if pulling and l[s] > line:
                    prior, pulling = trough, False
            out['origin'][s, j] = start
            out['count'][s, j] = -max(count - 1, 0)
            out['advance'][s, j] = -max(c[s] / pivot - 1, 0) / unit
            out['age'][s, j] = -(s - start)
            if pulling and np.isfinite(prior):
                out['higher'][s, j] = (trough / prior - 1) / (adr[s, j] / 100)
    return out


def flow_fields(close, turnover, adr):
    """Nonoverlapping 5/20 windows and already-observed inflow onset."""
    own, acceleration, ages = (np.full(close.shape, np.nan) for _ in range(3))
    for j in range(close.shape[1]):
        recent = old.lib.roll(turnover[:, j], 5)
        prior = old.lag(old.lib.roll(turnover[:, j], 20), 5)
        ratio = old.lib.divide(recent, prior)
        good = ratio > 0
        own[good, j] = np.log(ratio[good])
        c = close[:, j]
        for s in range(25, len(c)):
            if min(c[s], c[s - 5], c[s - 25], adr[s, j]) > 0 and \
                    np.isfinite([c[s], c[s - 5], c[s - 25], adr[s, j]]).all():
                acceleration[s, j] = (np.log(c[s] / c[s - 5]) / 5 -
                                      np.log(c[s - 5] / c[s - 25]) / 20) / (adr[s, j] / 100)
        onset = -1
        for s in range(1, len(c)):
            if own[s, j] > 0 and np.isfinite(own[s - 1, j]) and own[s - 1, j] <= 0:
                onset = s
            if own[s, j] > 0 and onset >= 0 and s - onset < 20:
                ages[s, j] = s - onset
    return dict(own_money=own, acceleration=acceleration, flow_age=ages)


def peer_mean(values, peers):
    neighbors = values[np.maximum(peers, 0)]
    valid = (peers >= 0) & (peers != np.arange(len(values))[:, None]) & np.isfinite(neighbors)
    return old.lib.divide(np.where(valid, neighbors, 0).sum(axis=1), valid.sum(axis=1))


def prepare():
    if not (WORK / 'initial_inputs.json').exists():
        raise RuntimeError('record the existing workspace before preparing IE18')
    if (WORK / 'prepared.json').exists():
        return
    d = previous.Data()
    raw_turnover = np.load(old.WORK / 'turnover.npy', mmap_mode='r')
    shape = d.px['close'].shape
    arrays = {n: np.lib.format.open_memmap(WORK / (n + '.npy'), mode='w+', dtype='float32', shape=shape)
              for n in FIELDS}
    for start in range(0, shape[1], 32):
        sl = slice(start, start + 32)
        c, h, l = (np.asarray(d.px[n][:, sl], float) for n in ('close', 'high', 'low'))
        e9, e21, adr = (np.asarray(d.f[n][:, sl], float) for n in ('e9', 'e21', 'adr'))
        turnover = np.asarray(raw_turnover[:, sl], float)
        for n, a in wave_fields(c, h, l, e9, e21, adr).items():
            arrays[n][:, sl] = a
        for n, a in flow_fields(c, turnover, adr).items():
            arrays[n][:, sl] = a
        for a in arrays.values():
            a.flush()
        if start % 320 == 0:
            print('prepare securities', start, '/', shape[1], flush=True)
    for s in range(shape[0]):
        peers = d.extra['peers'][s]
        arrays['peer_money'][s] = peer_mean(arrays['own_money'][s], peers)
        arrays['peer_return'][s] = peer_mean(arrays['acceleration'][s], peers)
        arrays['lead'][s] = previous.peer_lead(arrays['flow_age'][s], peers)
    for a in arrays.values():
        a.flush()
    old.save(WORK / 'prepared.json', dict(shape=shape, source=old.sha(__file__),
        features={n: old.sha(WORK / (n + '.npy')) for n in FIELDS},
        input_snapshot=old.sha(WORK / 'initial_inputs.json')))


class Data(previous.Data):
    def __init__(self):
        super().__init__()
        self.wave = {n: np.load(WORK / (n + '.npy'), mmap_mode='r') for n in FIELDS}
        self.template = None


def rank_against(values, reference):
    """Keep signal ranks exact; interpolate holdings without changing the denominator."""
    values = np.asarray(values, float)
    ref = values[np.asarray(reference, int)]
    ref = np.sort(ref[np.isfinite(ref)])
    out = np.full(len(values), .5)
    if len(ref) < 2 or ref[0] == ref[-1]:
        return out
    unique, starts, counts = np.unique(ref, return_index=True, return_counts=True)
    ranks = (starts + (counts - 1) / 2) / (len(ref) - 1)
    good = np.isfinite(values)
    out[good] = np.interp(values[good], unique, ranks)
    return out


def scores(s, d, cfg, signals):
    indices = np.flatnonzero(signals)
    extension = d.strength['extension'][s]
    lo, hi = cfg['interval']
    launch = -np.maximum(np.maximum(lo - extension, extension - hi), 0)
    base = (rank_against(launch, indices) + rank_against(d.f['money'][s], indices)) / 2
    parts = [base]
    phase = np.mean([rank_against(d.wave[n][s], indices) for n in STAGES[cfg['stage']]], axis=0) \
        if cfg['stage'] else None
    flow = np.mean([rank_against(d.wave[n][s], indices) for n in FLOWS[cfg['flow']]], axis=0) \
        if cfg['flow'] else None
    if cfg['interaction']:
        parts.append(phase * (.5 + .5 * flow))
    else:
        if phase is not None:
            parts.append(phase)
        if flow is not None:
            parts.append(flow)
    return np.mean(parts, axis=0)


def build(d, cfg):
    ident = old.key(cfg)
    if d.latest is not None and d.latest[0] == ident:
        return d.latest[1]
    if d.template is None:
        d.template = previous.build(d, REFERENCE['retained_config'])
    b = dict(d.template)
    ranked = np.full(d.px['close'].shape, .5)
    book = [[] for _ in b['book']]
    for t in range(d.start, d.end):
        s = t - 1
        ranked[s] = scores(s, d, cfg, b['signals']['long'][s])
        book[2 * t] = [((-float(ranked[s, e[1]]), d.codes[e[1]]), *e[1:]) for e in b['book'][2 * t]]
    b.update(book=book, scores=ranked)
    d.built.clear()
    d.built[old.key(dict(cfg=cfg, short=None))] = b
    d.latest = ident, b
    return b


def rotation_choice(s, d, cfg, signals, ranks, positions, openings, equity, gross):
    """The decision sees the previous completed session and current opening quotes."""
    if not cfg['rotation'] or s < 0:
        return None
    full = FIXED['max_open'] and len(positions) >= FIXED['max_open']
    if not full and 2.8 * equity - gross >= .05 * equity:
        return None
    candidates = [int(j) for j in np.flatnonzero(signals[s]) if j not in positions
                  and np.isfinite(openings[j]) and openings[j] > 0]
    if not candidates:
        return None
    target = min(candidates, key=lambda j: (-ranks[s, j], d.codes[j]))
    held = []
    for q in positions.values():
        first = q.d0 // 2
        if q.side < 0 or first > s or not np.isfinite(openings[q.j]) or openings[q.j] <= 0:
            continue
        unit = abs(q.fill - q.stop0)
        highs = d.px['high'][first:s + 1, q.j]
        if unit <= 0 or not np.isfinite(highs).any():
            continue
        best_r = (float(np.nanmax(highs)) - q.fill) / unit
        threshold = .5 if cfg['rotation'] == 'stall3' else 1.
        gap = {'gap25': .25, 'gap50': .5, 'stall3': 0.}[cfg['rotation']]
        difference = float(ranks[s, target] - ranks[s, q.j])
        if best_r >= threshold or difference <= 0 or difference < gap:
            continue
        if cfg['rotation'] == 'stall3' and s - first + 1 < 3:
            continue
        prior_r = (d.px['close'][s, q.j] - q.fill) / unit
        held.append((float(ranks[s, q.j]), float(prior_r), d.codes[q.j], q.j, best_r))
    if not held:
        return None
    weakest = min(held)
    return dict(sold=int(weakest[3]), target=target, signal_day=str(d.days[s]),
                old_score=weakest[0], new_score=float(ranks[s, target]), best_r=weakest[4],
                capacity='slots' if full else 'gross')


def rotation_simulator(callback):
    """Add one isolated opening hook; the fixed engine's other statements are unchanged."""
    source = inspect.getsource(old.system.simulate)
    anchor = "        tagged = [(intraday(e, d), e) for e in (entries[d] if d < len(entries) else [])]"
    inserted = """        if rotation_callback is not None and (daily_close is None or not daily_close[d]):
            chosen = rotation_callback(d, pos, o[d],
                cash + sum(q.side * q.size * at_open(q.j, d) for q in pos.values()), gross_open(d))
            if chosen is not None:
                q = pos[chosen['sold']]
                close_part(q, q.size, float(o[d, q.j]), d, 'rotate_open')
                if track is not None:
                    track.setdefault('rotations', []).append(dict(chosen, day=str(dates[d])))
"""
    if source.count(anchor) != 1:
        raise AssertionError('fixed engine opening hook moved')
    scope = dict(vars(old.system), rotation_callback=callback)
    exec(compile(source.replace(anchor, inserted + anchor), str(WORK / 'opening_hook'), 'exec'), scope)
    return scope['simulate']


def run_account(d, cfg, random_order=None, placebo=None, drop=None, human=None, fresh=False):
    ident = old.key(dict(cfg=cfg, fixed=FIXED, random_order=random_order, placebo=placebo, drop=drop, human=human))
    path = WORK / 'accounts' / (ident + '.json')
    if path.exists() and not fresh:
        return old.read(path)
    b = build(d, cfg)
    book, signal = b['book'], b['signals']['long']
    rules = old.policy(FIXED)
    if human is not None:
        book = [[] for _ in book]
        signal = np.zeros_like(signal)
        for label in human:
            if label['code'] not in d.ci:
                continue
            t, j = label['anchor'], d.ci[label['code']]
            signal[t, j] = True
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
    def callback(t, positions, openings, equity, gross):
        s = t // 2 - 1
        if not b['market'][s]:
            return None
        return rotation_choice(s, d, cfg, signal, b['scores'], positions, openings, equity, gross)
    simulate = rotation_simulator(callback) if cfg['rotation'] else old.system.simulate
    track = {}
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
                raise AssertionError('execution outside the real daily range')
    result = old.clean(dict(id=ident, config=cfg, fixed=FIXED, curve=curve, dates=days, trades=trades,
        summary=old.summarize_account(curve, days, trades, track), rotations=track.get('rotations', []), fills_valid=True))
    if not fresh:
        old.save(path, result)
    return result


def score(d, cfg, account, labels, supplied=False):
    build(d, cfg)
    return old.score(d, cfg, account, labels, supplied=supplied)


_spec = importlib.util.spec_from_file_location(__name__ + '_diagnostics', previous.previous.previous.__file__)
shared = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(shared)
for _name in ('WORK', 'PREFIX', 'BASE', 'FIXED', 'Data', 'build', 'score', 'run_account'):
    setattr(shared, _name, globals()[_name])
_diagnose = shared.diagnosis


def diagnosis(d, cfg, account, labels):
    result = _diagnose(d, cfg, account, labels)
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
        elif row['selection_block'] == '被别的信号抢先' and not any(
                v['earlier'] and v['morning'] < FIXED['max_open'] and not v['same_held']
                and not v['actual_same_day'] for v in offers):
            row['selection_block'] = '没仓位'
    from collections import Counter
    result['counts'] = dict(Counter(r['selection_block'] for r in result['card']['rows'] if not r['bought']))
    return result


def measure(d, cfg, labels):
    account = run_account(d, cfg)
    card = score(d, cfg, account, labels)
    metrics = old.card_summary(card['rows'])
    metrics['rank'] = [metrics['weighted_coverage'], metrics['bought']]
    return dict(config=cfg, metrics=metrics, account_id=account['id'], account=account['summary'],
                rotations=len(account['rotations']), card=card)


def admissible(metrics, floor):
    return metrics['bought'] >= floor['bought'] and metrics['weighted_coverage'] + 1e-12 >= floor['weighted_coverage']


def better(a, b):
    return (a['weighted_coverage'], a['bought']) > (b['weighted_coverage'], b['bought'])


def proposals(number, effective):
    if number == 1:
        return [dict(BASE, stage=n) for n in STAGES] + [dict(BASE)]
    if number == 2:
        return [dict(BASE, flow=n) for n in FLOWS] + [dict(BASE)]
    if number == 3:
        return [dict(BASE, rotation=n) for n in ('gap25', 'gap50', 'stall3')] + [dict(BASE)]
    out = []
    if number == 4:
        for group in ('AB', 'AC', 'BC', 'ABC'):
            if all(n in effective for n in group):
                cfg = dict(BASE)
                for n in group:
                    field = dict(A='stage', B='flow', C='rotation')[n]
                    cfg[field] = effective[n]['config'][field]
                out.append(cfg)
    elif all(n in effective for n in 'AB'):
        cfg = dict(BASE, stage=effective['A']['config']['stage'], flow=effective['B']['config']['flow'], interaction=True)
        out.append(cfg)
        if 'C' in effective:
            out.append(dict(cfg, rotation=effective['C']['config']['rotation']))
    return out


def source_functions():
    paths = [Path(__file__), Path(previous.__file__), Path(previous.previous.__file__),
             Path(shared.__file__), Path(old.__file__), Path(old.system.__file__), Path(old.lib.__file__)]
    return {str(p.relative_to(ROOT)): old.sha(p) for p in paths}


def seal():
    state = dict(source=source_functions(), plan=old.sha(PLAN), prereg=old.sha(PREREG),
                 prepared=old.sha(WORK / 'prepared.json'), baseline=BASE, fixed=FIXED)
    path = WORK / 'run_source.json'
    if path.exists():
        if old.read(path) != state:
            raise AssertionError('IE18 frozen implementation or inputs changed')
    else:
        old.save(path, state)
        (WORK / 'research_source.txt').write_text(Path(__file__).read_text())


def search(d, labels, tag, held=None):
    path = WORK / 'searches' / (tag + '.json')
    if path.exists():
        return old.read(path)
    training = old.training_rows(labels, held)
    floor = measure(d, BASE, training)
    chosen, exploration = floor, floor
    effective, rounds = {}, []
    for number in range(1, 6):
        choices = proposals(number, effective)
        if not choices:
            continue
        registration = dict(tag=tag, heldout=held, round=number, candidates=choices,
            training_ids=sorted(r['id'] for r in training), effective={n: r['config'] for n, r in effective.items()},
            incumbent=chosen['config'], logic=source_functions(), prereg=old.sha(PREREG))
        regpath = WORK / 'registrations' / (tag + '_r' + str(number) + '.json')
        if regpath.exists() and old.read(regpath) != registration:
            raise AssertionError('IE18 candidate registration changed')
        if not regpath.exists():
            old.save(regpath, registration)
        results = []
        best_group = floor
        for cfg in choices:
            result = measure(d, cfg, training)
            result['admissible'] = admissible(result['metrics'], floor['metrics'])
            results.append(result)
            if result['admissible'] and better(result['metrics'], chosen['metrics']):
                chosen = result
            if result['admissible'] and better(result['metrics'], best_group['metrics']):
                best_group = result
            if better(result['metrics'], exploration['metrics']):
                exploration = result
            print(tag, 'round', number, cfg['stage'], cfg['flow'], cfg['rotation'], cfg['interaction'],
                  'bought', result['metrics']['bought'], 'weight', round(result['metrics']['weighted_coverage'], 5), flush=True)
        if number <= 3 and best_group is not floor:
            effective['ABC'[number - 1]] = best_group
        round_ = dict(round=number, registration=str(regpath.relative_to(ROOT)), candidates=results,
                      selected=chosen['config'], metrics=chosen['metrics'])
        rounds.append(round_)
        old.save(WORK / 'rounds' / (tag + '_r' + str(number) + '.json'), round_)
        gc.collect()
    result = dict(tag=tag, heldout=held, config=chosen['config'], metrics=chosen['metrics'], floor=floor['metrics'],
        effective={n: r['config'] for n, r in effective.items()}, rounds=rounds,
        exploratory_config=exploration['config'], exploratory_metrics=exploration['metrics'])
    old.save(path, result)
    return old.clean(result)


def cross_validation(d, labels, tag):
    path = WORK / (tag + '_cv.json')
    if path.exists():
        return old.read(path)
    folds, rows = {}, []
    for h in old.HALVES:
        fitted = search(d, labels, tag + '_' + h, h)
        held = [r for r in labels if r['half'] == h]
        account = run_account(d, fitted['config'])
        card = score(d, fitted['config'], account, held)
        rows.extend(card['rows'])
        folds[h] = dict(config=fitted['config'], training_ids=sorted(r['id'] for r in old.training_rows(labels, h)),
                        score=card, account_id=account['id'])
    result = dict(folds=folds, summary=old.card_summary(rows), rows=rows)
    old.save(path, result)
    return old.clean(result)


def run_search(tag):
    seal()
    d = Data()
    labels = [r for r in old.labels(d) if r['side'] > 0]
    if tag != 'true':
        labels = old.shuffle_labels(d, labels, int(tag.rsplit('_', 1)[1]))
    fitted = search(d, labels, tag)
    output(tag, dict(fit=fitted, cv=cross_validation(d, labels, tag)))


def initial_diagnosis():
    seal()
    d = Data()
    labels = [r for r in old.labels(d) if r['side'] > 0]
    account = run_account(d, BASE)
    ref = old.read(previous.WORK / 'accounts' / (REFERENCE['account_id'] + '.json'))
    if account['trades'] != ref['trades'] or account['curve'] != ref['curve']:
        raise AssertionError('IE17 baseline changed')
    result = diagnosis(d, BASE, account, labels)
    if result['counts'] != REFERENCE['remaining']:
        raise AssertionError('IE17 baseline classification changed')
    result['baseline_identical'] = True
    output('diagnosis', result)
    print('baseline identical', old.card_summary(result['card']['rows'])['weighted_coverage'], flush=True)


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
    orders, entries = [], []
    for k in range(20):
        random = run_account(d, cfg, random_order=150000 + k)
        orders.append(dict(seed=150000 + k, account_id=random['id'],
            summary=old.card_summary(score(d, cfg, random, longs)['rows']), account=random['summary']))
        random = run_account(d, cfg, placebo=151000 + k)
        entries.append(dict(seed=151000 + k, account_id=random['id'], account=random['summary']))
        print('controls', k + 1, '/ 20', flush=True)
    controls = dict(order_random=orders, entry_random=entries,
        buy_expectation=float(np.mean([r['summary']['bought'] for r in orders])),
        weight_expectation=float(np.mean([r['summary']['weighted_coverage'] for r in orders])),
        placebo_median=float(np.median([r['account']['total'] for r in entries])),
        placebo_p90=float(np.percentile([r['account']['total'] for r in entries], 90)))
    shuffled = [old.read(REPORTS / (PREFIX + 'shuffle_' + str(s) + '.json')) for s in SEEDS]
    anti = {}
    for kind in ('full', 'cv'):
        real = fitted['cv']['summary'] if kind == 'cv' else fitted['fit']['metrics']
        samples = [r['cv']['summary'] if kind == 'cv' else r['fit']['metrics'] for r in shuffled]
        anti[kind] = dict(true=real, best_count=max(r['bought'] for r in samples),
            best_weight=max(r['weighted_coverage'] for r in samples))
        anti[kind]['passed'] = real['weighted_coverage'] > anti[kind]['best_weight']
    anti['passed'] = anti['cv']['passed']
    baseline = run_account(d, BASE)
    basecard = score(d, BASE, baseline, labels)
    base_long = old.card_summary([r for r in basecard['rows'] if r['side'] > 0])
    best = sorted((tr for tr in account['trades'] if tr['why'] != 'end'), key=lambda tr: -tr['ret'])[:2]
    drop = run_account(d, cfg, drop=[(r['entry'], r['code']) for r in best])
    human = run_account(d, cfg, human=longs)
    human_card = score(d, cfg, human, longs, supplied=True)
    build(d, cfg)
    sig = shared.signal_reference(d, cfg, longs)
    widths = old.signal_baseline(d, cfg, longs)['widths']
    matched = old.matched_signal_random(d, cfg, longs)
    diag = diagnosis(d, cfg, account, longs)
    output('final_diagnosis', diag)
    before = old.read(REPORTS / (PREFIX + 'diagnosis.json'))['card']['rows']
    lookup = {r['id']: r for r in diag['card']['rows']}
    rescue = [dict(id=r['id'], code=r['code'], bought=lookup[r['id']]['bought'],
        entry=lookup[r['id']]['actual_entry'], remaining=lookup[r['id']]['selection_block'])
        for r in before if r['selection_block'] == '被别的信号抢先']
    improved = admissible(true, base_long) and better(true, base_long)
    result = dict(config=cfg, fixed=FIXED, account_id=account['id'], account=account['summary'], card=card, long=true,
        rotations=account['rotations'], baseline=dict(account=baseline['summary'], card=basecard, long=base_long),
        controls=controls, cv=fitted['cv'], shuffled=[dict(seed=s, full=r['fit']['metrics'], cv=r['cv']['summary'])
        for s, r in zip(SEEDS, shuffled)], anti=anti, remaining=diag['counts'],
        signal=dict(**sig, widths=widths, matched=matched, lift=true['signal'] / sig['expected']),
        rescued=dict(total=len(rescue), bought=sum(r['bought'] for r in rescue), rows=rescue),
        drop2=dict(removed=best, account_id=drop['id'], summary=drop['summary'],
                   beats_random=drop['summary']['total'] > controls['placebo_median']),
        human=dict(account=human['summary'], card=human_card, account_id=human['id'], rotations=human['rotations']),
        selection_improved=improved, qualified_improvement=improved and anti['passed'],
        retained_config=cfg if improved and anti['passed'] else BASE,
        exploratory_config=fitted['fit']['exploratory_config'], exploratory_metrics=fitted['fit']['exploratory_metrics'])
    output('random', controls)
    output('final', result)
    for round_ in fitted['fit']['rounds']:
        output('round' + str(round_['round']), round_)
    print('final', true['bought'], true['weighted_coverage'], 'anti', anti['passed'], flush=True)


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
