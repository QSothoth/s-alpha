"""IE15 selection-only research; IE14 fills and account management stay fixed."""
from __future__ import annotations

import argparse
import ast
from collections import Counter
import csv
import gc
import json
from pathlib import Path
import resource
import socket
import time

import numpy as np

from studies.trader_replication import martin_continue_ie14 as old

ROOT = old.ROOT
REPORTS = old.REPORTS
WORK = REPORTS / 'ie15_work'
PLAN = ROOT / 'studies/martin_luk/notes/PLAN_IE15_CN.md'
PREREG = ROOT / 'studies/martin_luk/notes/PREREG_IE15_CN.md'
PREFIX = 'strong_continue_ie15_'
SEEDS = (150101, 150103, 150107, 150109, 150111)
FIXED = old.read(REPORTS / (old.PREFIX + 'long.json'))['config']
BASE = dict(watch=0, depth=20, leaders=50, recent=20, upgrade=5,
            pool='liquid', trend='reclaim', setup='three', priority='money')
REBUILT = dict(BASE, watch=1, priority='upgrade')


def save(path, value):
    old.save(path, value)


def output(name, value):
    save(REPORTS / (PREFIX + name + '.json'), value)


def offline():
    def denied(*args, **kwargs):
        raise RuntimeError('IE15 uses cached inputs only')
    socket.socket = denied
    socket.create_connection = denied


def snapshot():
    """Protect every existing workspace file without loading file contents together."""
    import os
    WORK.mkdir(parents=True, exist_ok=True)
    path = WORK / 'initial_inputs.json'
    if path.exists():
        return
    metadata = {}
    for directory, dirs, names in os.walk(ROOT, followlinks=False):
        dirs[:] = [n for n in dirs if n not in ('.git', '.venv', '__pycache__')
                   and not Path(directory, n).is_symlink()]
        for name in names:
            p = Path(directory, name)
            if p.is_symlink() or WORK in p.parents or 'ie15' in p.name.lower():
                continue
            st = p.stat()
            metadata[str(p.relative_to(ROOT))] = [st.st_size, st.st_mtime_ns]
    prior = old.read(old.WORK / 'initial_inputs.json')['hashes']
    paths = {p for p in prior if (ROOT / p).is_file()}
    paths.update(str(p.relative_to(ROOT)) for p in old.WORK.glob('*.npy'))
    paths.update(str(p.relative_to(ROOT)) for p in REPORTS.glob(old.PREFIX + '*') if p.is_file())
    paths.update(('studies/trader_replication/martin_continue_ie14.py',
                  'studies/trader_replication/system.py', str(PLAN.relative_to(ROOT))))
    save(path, dict(metadata=metadata, hashes={p: old.sha(ROOT / p) for p in sorted(paths)}))


def rolling_any(a, n):
    """Inclusive, trailing membership; no centered or forward window."""
    sums = np.cumsum(np.asarray(a, np.int16), axis=0, dtype=np.int32)
    out = sums.copy()
    out[n:] -= sums[:-n]
    return out > 0


def grades(close, e9, e21, e50, weekly21):
    leader = (e9 > e21) & (e21 > e50)
    medium = ~leader & (close >= weekly21)
    grade = np.where(leader, 2, np.where(medium, 1, 0)).astype(np.int8)
    valid = np.isfinite(close) & np.isfinite(e50) & np.isfinite(weekly21)
    grade[~valid] = -1
    upgrade = np.zeros_like(leader)
    upgrade[1:] = (grade[1:] == 2) & (grade[:-1] == 1)
    return grade, upgrade


def weekly_line(close, days):
    """Last completed weekly EMA; Friday's close is available on Friday night."""
    from datetime import date
    result = np.full(len(close), np.nan)
    value = np.nan
    previous = None
    finished = False
    def add(price):
        nonlocal value
        if np.isfinite(price):
            value = value + (price - value) / 11 if np.isfinite(value) else price
    for t, text in enumerate(days):
        day = date.fromisoformat(str(text))
        week = day.isocalendar()[:2]
        if previous is not None and previous != week and not finished:
            add(close[t - 1])
        if week != previous:
            finished = False
        if day.weekday() == 4:
            add(close[t])
            finished = True
        result[t] = value
        previous = week
    return result


def scan_ranks(close, opening, volume, money, adr, days):
    """Daily potent/gap ranks and the latest completed weekly leader scan."""
    from datetime import date
    shape = close.shape
    rank = {name: np.zeros(shape, np.int16) for name in ('potent', 'gap', 'leader')}
    volmean = np.empty(shape, np.float32)
    for j in range(shape[1]):
        volmean[:, j] = old.lib.roll(volume[:, j], 20)
    previous_week = None
    last_leaders = np.zeros(shape[1], np.int16)
    for t, text in enumerate(days):
        if t < 20:
            continue
        day = date.fromisoformat(str(text))
        week = day.isocalendar()[:2]
        eligible = (money[t] >= 2e6) & (adr[t] > 3) & np.isfinite(close[t])
        def assign(values, allowed):
            indices = np.flatnonzero(allowed & np.isfinite(values) & (values > 0))
            indices = indices[np.argsort(-values[indices], kind='stable')]
            out = np.zeros(shape[1], np.int16)
            out[indices] = np.arange(1, len(indices) + 1)
            return out
        rank['potent'][t] = assign(close[t] / close[t - 1] - 1, eligible)
        # Cached daily volume is a close-known proxy, never premarket volume.
        rank['gap'][t] = assign(opening[t] / close[t - 1] - 1,
                                 eligible & (volume[t] >= volmean[t]))
        if previous_week is not None and week != previous_week and not completed:
            s = t - 1
            allowed = (money[s] >= 2e6) & (adr[s] > 3) & np.isfinite(close[s])
            last_leaders = assign(close[s] / close[s - 20] - 1, allowed)
        if week != previous_week:
            completed = False
        if day.weekday() == 4:
            last_leaders = assign(close[t] / close[t - 20] - 1, eligible)
            completed = True
        rank['leader'][t] = last_leaders
        previous_week = week
    return rank


def peer_block(history, indices, anchors, minimum=30):
    """A small target block against <=300 anchors, excluding each name itself."""
    h = np.asarray(history, float)
    ok = np.isfinite(h)
    means = np.where(ok, h, 0).sum(axis=0) / np.maximum(ok.sum(axis=0), 1)
    centered = np.where(ok, h - means, 0.)
    norm = np.sqrt((centered * centered).sum(axis=0))
    centered /= np.maximum(norm, 1e-12)
    corr = centered[:, indices].T @ centered[:, anchors]
    corr[(ok[:, indices].sum(axis=0) < minimum), :] = -2
    corr[:, ok[:, anchors].sum(axis=0) < minimum] = -2
    corr[np.asarray(indices)[:, None] == np.asarray(anchors)[None, :]] = -2
    out = np.full((len(indices), 5), -1, np.int16)
    for k, row in enumerate(corr):
        nearest = np.argsort(-row, kind='stable')[:5]
        nearest = nearest[row[nearest] >= .5]
        out[k, :len(nearest)] = np.asarray(anchors)[nearest]
    return out


def cluster_counts(peers, scanned, upgraded):
    valid = peers >= 0
    indices = np.maximum(peers, 0)
    return ((scanned[indices] & valid).sum(axis=1),
            (upgraded[indices] & valid).sum(axis=1))


def prepare():
    snapshot()
    if (WORK / 'prepared.json').exists():
        return
    d = old.Data()
    shape = len(d.days), len(d.codes)
    weekly = np.lib.format.open_memmap(WORK / 'weekly21.npy', mode='w+', dtype='float32', shape=shape)
    for j in range(len(d.codes)):
        weekly[:, j] = weekly_line(d.px['close'][:, j], d.days)
    grade, upgrade = grades(d.px['close'], d.f['e9'], d.f['e21'], d.f['e50'], weekly)
    for name, a in dict(grade=grade, upgrade=upgrade).items():
        np.save(WORK / (name + '.npy'), a)
    ranks = scan_ranks(d.px['close'], d.px['open'], np.load(old.WORK / 'volume.npy', mmap_mode='r'),
                      d.f['money'], d.f['adr'], d.days)
    for name, a in ranks.items():
        np.save(WORK / (name + '.npy'), a)
    del ranks, grade, upgrade
    returns = np.lib.format.open_memmap(WORK / 'returns.npy', mode='w+', dtype='float32', shape=shape)
    returns[:] = np.nan
    for t in range(1, len(d.days)):
        row = old.lib.divide(d.px['close'][t], d.px['close'][t - 1]) - 1
        valid = np.isfinite(row) & (d.f['money'][t - 1] >= 20e6)
        returns[t] = row - (np.median(row[valid]) if valid.any() else 0.)
    peers = np.lib.format.open_memmap(WORK / 'peers.npy', mode='w+', dtype='int16', shape=(*shape, 5))
    peers[:] = -1
    current = np.full((shape[1], 5), -1, np.int16)
    for t in range(40, len(d.days)):
        if t % 5 == 0:
            eligible = np.flatnonzero((d.f['money'][t] >= 20e6) & (d.f['adr'][t] > 3))
            anchors = eligible[np.argsort(-d.f['money'][t, eligible], kind='stable')[:300]]
            current[:] = -1
            if len(anchors):
                history = returns[t - 39:t + 1]
                for start in range(0, shape[1], 64):
                    indices = np.arange(start, min(start + 64, shape[1]))
                    current[indices] = peer_block(history, indices, anchors)
        peers[t] = current
        if t % 100 == 0:
            print('prepare peers', t, '/', len(d.days), flush=True)
    for a in (weekly, returns, peers):
        a.flush()
    save(WORK / 'prepared.json', dict(shape=shape, source=old.sha(__file__), plan=old.sha(PLAN),
          inputs={p.name: old.sha(p) for p in old.WORK.glob('*.npy')},
          note='Close-known daily gap/volume proxy; 40-session residual-return peers, refreshed every five sessions.'))


class Data(old.Data):
    def __init__(self):
        super().__init__()
        self.extra = {n: np.load(WORK / (n + '.npy'), mmap_mode='r')
                      for n in ('weekly21', 'grade', 'upgrade', 'potent', 'gap', 'leader', 'peers')}
        self.management = old.management(self, FIXED)
        self.latest = None


def selection_arrays(d, cfg):
    f, x, c = d.f, d.extra, d.px['close']
    merged = dict(FIXED, pool=cfg['pool'], trend='all' if cfg['trend'] == 'graded' else cfg['trend'], setup=cfg['setup'])
    pool, trend, setup, market = old.masks(d, merged)
    if cfg['trend'] == 'graded':
        trend &= x['grade'] >= 1
    hits = ((x['potent'] > 0) & (x['potent'] <= cfg['depth'])) \
        | ((x['gap'] > 0) & (x['gap'] <= cfg['depth'])) \
        | ((x['leader'] > 0) & (x['leader'] <= cfg['leaders']))
    watched = rolling_any(hits, cfg['recent'])
    fresh = hits & ~np.vstack((np.zeros((1, len(d.codes)), bool), watched[:-1]))
    upgraded = rolling_any(x['upgrade'], cfg['upgrade'])
    newscan = rolling_any(fresh, cfg['upgrade'])
    if cfg['setup'] == 'wick':
        setup |= (c >= d.px['low'] + .75 * (d.px['high'] - d.px['low'])) & (c >= f['e9'])
    elif cfg['setup'] == 'reclaim':
        previous = np.vstack((np.zeros((1, len(d.codes)), bool), (c >= f['e9'])[:-1]))
        setup |= (c >= f['e9']) & ~previous
    elif cfg['setup'] == 'high20':
        for j in range(len(d.codes)):
            setup[:, j] |= c[:, j] >= old.lib.roll(d.px['high'][:, j], 20, 'max')
    signal = pool & trend & setup
    if cfg['watch']:
        signal &= watched
    return dict(pool=pool, trend=trend, setup=setup, market=market, watched=watched,
                scanned=rolling_any(hits, cfg['upgrade']), upgraded=upgraded, newscan=newscan,
                signals=dict(long=signal, short=np.zeros_like(signal)))


def priorities(cfg, upgraded, newscan, cluster, premier, money, grade):
    """Tuple ordering is the literal stated sequence; liquidity breaks final ties."""
    fields = dict(upgrade=upgraded, scan=newscan, cluster=cluster, premier=premier,
                  leader=grade == 2)
    sequence = {'upgrade': ('upgrade', 'cluster', 'premier'),
                'cluster': ('cluster', 'upgrade', 'premier'),
                'scan': ('scan', 'upgrade', 'cluster', 'premier'),
                'premier': ('premier', 'upgrade', 'cluster'),
                'leader': ('leader', 'premier', 'upgrade', 'cluster'), 'money': ()}[cfg['priority']]
    return [tuple(-float(fields[k][j]) for k in sequence) + (-float(money[j]),)
            for j in range(len(money))]


def build(d, cfg):
    ident = old.key(cfg)
    if d.latest is not None and d.latest[0] == ident:
        return d.latest[1]
    b = selection_arrays(d, cfg)
    book = [[] for _ in range(2 * len(d.days))]
    triggers = np.zeros_like(b['signals']['long'])
    for t in range(d.start, d.end):
        s = t - 1
        candidates = np.flatnonzero(b['signals']['long'][s])
        if cfg['priority'] != 'money':
            scanned, upgraded = cluster_counts(d.extra['peers'][s, candidates], b['scanned'][s], b['upgraded'][s])
            priority = priorities(cfg, b['upgraded'][s, candidates], b['newscan'][s, candidates],
                                  np.maximum(scanned, upgraded), d.f['money'][s, candidates] >= 100e6,
                                  d.f['money'][s, candidates], d.extra['grade'][s, candidates])
        for k, j in enumerate(candidates):
            e = old.order(t, int(j), 1, d, FIXED)
            if e is not None:
                triggers[s, j] = True
                if b['market'][s]:
                    # The execution tuple is unchanged except its selection priority.
                    pr = e[0] if cfg['priority'] == 'money' else priority[k]
                    book[2 * t].append((pr, *e[1:]))
    b.update(book=book, triggers=triggers, short_market=np.ones(len(d.days), bool))
    d.built.clear()
    d.built[old.key(dict(cfg=cfg, short=None))] = b
    d.latest = ident, b
    return b


def run_account(d, cfg, random_order=None, placebo=None, drop=None, audit=False):
    ident = old.key(dict(cfg=cfg, fixed=FIXED, random_order=random_order, placebo=placebo, drop=drop))
    path = WORK / 'accounts' / (ident + '.json')
    if path.exists():
        return old.read(path)
    b = build(d, cfg)
    book = b['book']
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
    curve, days, trades = old.system.simulate(d.phase_px(), d.management, old.policy(FIXED), book,
                    *old.panels.WINDOW, audit=True, track=track,
                    placebo=np.random.default_rng(placebo) if placebo is not None else None, pool=pool)
    curve, days = curve[1::2], days[1::2]
    invalid = 0
    for trade in trades:
        if trade['why'] == 'trail_open':
            s = d.di[trade.get('trail_signal', trade['exit'])]
            trade['sell_reason'] = 'climax' if d.f['climax'][s, d.ci[trade['code']]] == 1 else 'ema' + str(FIXED['trail'])
        else:
            trade['sell_reason'] = trade['why']
        for x in trade['executions']:
            t, j = d.di[x['time']], d.ci[trade['code']]
            invalid += x['action'] != 'end' and not d.px['low'][t, j] - 1e-8 <= x['price'] <= d.px['high'][t, j] + 1e-8
    if invalid:
        raise AssertionError('an execution left its real daily price range')
    result = dict(id=ident, config=cfg, fixed=FIXED, curve=curve, dates=days, trades=trades,
                  summary=old.summarize_account(curve, days, trades, track), fills_valid=True)
    save(path, result)
    return old.clean(result)


def score(d, cfg, account, labels):
    build(d, cfg)
    return old.score(d, cfg, account, labels)


def diagnosis(d, cfg, account, labels):
    card = score(d, cfg, account, labels)
    b = build(d, cfg)
    for r in card['rows']:
        if r['bought']:
            r['selection_block'] = '已买到'
            continue
        j = d.ci.get(r['code'])
        r['offered'] = []
        if j is None:
            r['selection_block'] = '股票池'
            r['selection_detail'] = '缺缓存，保留分母'
            continue
        sl = slice(r['lo'], r['hi'] + 1)
        if not r['signal']:
            available = b['pool'][sl, j].copy()
            watched = available & b['watched'][sl, j] if cfg['watch'] else available
            if not available.any():
                block = '股票池'
            elif not watched.any():
                block = '观察名单'
            elif not (watched & b['trend'][sl, j]).any():
                block = '领涨状态'
            else:
                block = '买点'
            r['selection_block'] = block
            r['selection_detail'] = '独立信号尝试不足' if b['signals']['long'][sl, j].any() else block
            continue
        offers = []
        for t in range(r['lo'], r['hi'] + 1):
            candidates = sorted(b['book'][2 * t], key=lambda e: e[0])
            for rank, e in enumerate(candidates):
                if e[1] != j:
                    continue
                day = d.days[t]
                morning = [tr for tr in account['trades'] if tr['entry'] < day and
                           (tr['exit'] > day or (tr['exit'] == day and tr['why'] not in ('gap_stop', 'trail_open', 'time_open')))]
                earlier = [tr for tr in account['trades'] if tr['entry'] == day and
                           any(v[1] == d.ci[tr['code']] for v in candidates[:rank])]
                offers.append(dict(day=day, rank=rank + 1, signals=len(candidates),
                                   morning=len(morning), earlier=[tr['code'] for tr in earlier],
                                   same_held=any(tr['code'] == r['code'] for tr in morning),
                                   actual_same_day=any(tr['code'] == r['code'] and tr['entry'] == day
                                                       for tr in account['trades'])))
        r['offered'] = offers
        if not offers:
            nights = b['signals']['long'][sl, j]
            r['selection_block'] = '市况（固定）' if not (nights & b['market'][sl]).any() else '买点'
            r['selection_detail'] = '市况过滤条件未放行' if r['selection_block'].startswith('市况') else '次日未越触发价或落在窗口外'
        elif all(v['same_held'] or v['actual_same_day'] for v in offers):
            r['selection_block'] = '没仓位'
            r['selection_detail'] = '已持同票或一次成交已配给另一笔台账'
        elif any(v['earlier'] and v['morning'] < FIXED['max_open'] for v in offers):
            r['selection_block'] = '被别的信号抢先'
            r['selection_detail'] = '同日更早顺序开仓占用容量，见逐日明细'
        else:
            r['selection_block'] = '没仓位'
            r['selection_detail'] = '既有持仓、敞口或单票限制，见逐日明细'
    counts = Counter(r['selection_block'] for r in card['rows'] if not r['bought'])
    return dict(card=card, counts=dict(counts))


def initial_diagnosis():
    d = Data()
    labels = [r for r in old.labels(d) if r['side'] > 0]
    account = run_account(d, BASE)
    reference = old.read(old.WORK / 'accounts' / (old.read(REPORTS / (old.PREFIX + 'long.json'))['account_id'] + '.json'))
    if account['trades'] != reference['trades'] or account['curve'] != reference['curve']:
        raise AssertionError('IE14 baseline execution changed')
    result = diagnosis(d, BASE, account, labels)
    result['baseline_identical'] = True
    output('diagnosis', result)
    print('baseline', old.card_summary(result['card']['rows']), 'diagnosis', result['counts'], flush=True)


def signal_reference(d, cfg, labels):
    b = build(d, cfg)
    widths = b['signals']['long'].sum(axis=1)
    sizes = b['pool'].sum(axis=1)
    expected = 0.
    probabilities = []
    for r in labels:
        j = d.ci.get(r['code'])
        remain = 1.
        if j is not None and r['side'] > 0:
            for t in range(r['lo'], r['hi'] + 1):
                if sizes[t] and b['pool'][t, j]:
                    remain *= 1 - min(1., widths[t] / sizes[t])
        expected += 1 - remain
        probabilities.append(dict(id=r['id'], probability=1 - remain))
    return dict(expected=float(expected), rows=probabilities)


def metrics(d, cfg, account, labels):
    diag = diagnosis(d, cfg, account, labels)
    summary = old.card_summary(diag['card']['rows'])
    chance = signal_reference(d, cfg, labels)
    lift = summary['signal'] / chance['expected'] if chance['expected'] else 0.
    return old.clean(dict(**summary, lift=lift, chance=chance['expected'],
                          blocks=diag['counts'], rank=[summary['weighted_coverage'], lift]))


def proposals(cfg, counts, seen, initial=False):
    if initial:
        return '重建扫描名单和按原话排序', [dict(REBUILT, priority=p) for p in ('upgrade', 'cluster', 'scan', 'premier', 'money')]
    banks = {
        'priority': [('priority', p) for p in ('upgrade', 'cluster', 'scan', 'premier', 'money', 'leader')],
        'watch': [('recent', n) for n in (60, 120, 10)] + [('depth', 50), ('leaders', 100)],
        'pool': [('pool', p) for p in ('fast', 'broad', 'premier')],
        'trend': [('trend', p) for p in ('stack', 'early', 'medium', 'graded', 'all')],
        'setup': [('setup', p) for p in ('retest', 'support', 'wick', 'reclaim', 'high20')],
    }
    weights = dict(priority=counts.get('被别的信号抢先', 0) + counts.get('没仓位', 0),
                   watch=counts.get('观察名单', 0), pool=counts.get('股票池', 0),
                   trend=counts.get('领涨状态', 0), setup=counts.get('买点', 0))
    for layer in sorted(weights, key=lambda n: -weights[n]):
        choices = [dict(cfg, **{field: value}) for field, value in banks[layer]]
        choices = [c for c in choices if old.key(c) not in seen and c != cfg]
        if choices:
            return layer, choices[:5]
    return '候选库用完', []


def source_functions():
    names = ('rolling_any', 'grades', 'weekly_line', 'scan_ranks', 'peer_block', 'cluster_counts',
             'selection_arrays', 'priorities', 'build', 'run_account', 'score', 'diagnosis',
             'signal_reference', 'metrics', 'proposals', 'search', 'cross_validation', 'run_search')
    tree = ast.parse(Path(__file__).read_text())
    return {n.name: old.key(ast.dump(n, include_attributes=False)) for n in tree.body
            if isinstance(n, ast.FunctionDef) and n.name in names}


def seal():
    path = WORK / 'run_source.json'
    state = dict(functions=source_functions(), prereg=old.sha(PREREG), plan=old.sha(PLAN),
                 fixed=FIXED, engine=old.sha(Path(old.system.__file__)), prior=old.sha(Path(old.__file__)))
    if path.exists():
        if old.read(path)['state'] != state:
            raise AssertionError('registered research logic or inputs changed; do not reuse evaluated caches')
    else:
        (WORK / 'research_source.txt').write_text(Path(__file__).read_text())
        save(path, dict(state=state, source_sha256=old.sha(__file__), prepared=old.sha(WORK / 'prepared.json')))


def search(d, labels, tag, held=None):
    path = WORK / 'searches' / (tag + '.json')
    if path.exists():
        return old.read(path)
    training = old.training_rows(labels, held)
    baseline = run_account(d, BASE)
    floor = metrics(d, BASE, baseline, training)
    chosen, chosen_metrics = dict(BASE), floor
    branch, branch_metrics = dict(REBUILT), None
    seen = {old.key(BASE)}
    rounds = []
    for number in range(1, 7):
        counts = floor['blocks'] if number == 1 else branch_metrics['blocks']
        layer, candidates = proposals(branch, counts, seen, initial=number == 1)
        if not candidates:
            break
        registration = dict(tag=tag, heldout=held, round=number, layer=layer, counts=counts,
                    training_ids=sorted(r['id'] for r in training), candidates=candidates,
                    incumbent=chosen, branch=branch, prereg=old.sha(PREREG), logic=source_functions())
        regpath = WORK / 'registrations' / (tag + '_r' + str(number) + '.json')
        if regpath.exists():
            if old.read(regpath) != registration:
                raise AssertionError('a round registration changed')
        else:
            save(regpath, registration)
        results = []
        for cfg in candidates:
            seen.add(old.key(cfg))
            account = run_account(d, cfg)
            card = score(d, cfg, account, training)
            measure = metrics(d, cfg, account, training)
            admissible = measure['bought'] >= floor['bought'] and measure['weighted_coverage'] + 1e-12 >= floor['weighted_coverage']
            results.append(dict(config=cfg, metrics=measure, admissible=admissible,
                                account_id=account['id'], account=account['summary'], card=card))
            if admissible and tuple(measure['rank']) > tuple(chosen_metrics['rank']):
                chosen, chosen_metrics = cfg, measure
            print(tag, 'round', number, layer, old.key(cfg), 'bought', measure['bought'],
                  'weighted', round(measure['weighted_coverage'], 4), 'eligible', admissible, flush=True)
        # Continue the most informative observed branch even when it is not adoptable.
        branch_candidates = results
        if branch_metrics is not None:
            branch_candidates = results + [dict(config=branch, metrics=branch_metrics)]
        exploration = max(branch_candidates, key=lambda r: tuple(r['metrics']['rank']))
        branch, branch_metrics = exploration['config'], exploration['metrics']
        rounds.append(dict(round=number, layer=layer, registration=str(regpath.relative_to(ROOT)),
                      candidates=results, selected=chosen, metrics=chosen_metrics,
                      branch=branch, branch_metrics=branch_metrics))
        save(WORK / 'rounds' / (tag + '_r' + str(number) + '.json'), rounds[-1])
        gc.collect()
    result = dict(tag=tag, heldout=held, config=chosen, metrics=chosen_metrics, floor=floor, rounds=rounds)
    save(path, result)
    return old.clean(result)


def cross_validation(d, labels, tag):
    path = WORK / (tag + '_cv.json')
    if path.exists():
        return old.read(path)
    folds, rows = {}, []
    for h in old.HALVES:
        fitted = search(d, labels, tag + '_' + h, held=h)
        held = [r for r in labels if r['half'] == h and r['side'] > 0]
        account = run_account(d, fitted['config'])
        card = score(d, fitted['config'], account, held)
        rows.extend(card['rows'])
        folds[h] = dict(config=fitted['config'], training_ids=sorted(r['id'] for r in old.training_rows(labels, h)),
                        score=card, account_id=account['id'])
    result = dict(folds=folds, summary=old.card_summary(rows), rows=rows)
    save(path, result)
    return old.clean(result)


def run_search(tag):
    seal()
    d = Data()
    labels = [r for r in old.labels(d) if r['side'] > 0]
    if tag != 'true':
        labels = old.shuffle_labels(d, labels, int(tag.rsplit('_', 1)[1]))
    fitted = search(d, labels, tag)
    result = dict(fit=fitted, cv=cross_validation(d, labels, tag))
    output(tag, result)


def search_all():
    for tag in ('true', *('shuffle_' + str(s) for s in SEEDS)):
        start = time.monotonic()
        run_search(tag)
        print('finished', tag, 'elapsed seconds', round(time.monotonic() - start, 1), flush=True)
        gc.collect()


def finalize():
    seal()
    d = Data()
    labels = old.labels(d)
    longs = [r for r in labels if r['side'] > 0]
    fitted = old.read(REPORTS / (PREFIX + 'true.json'))
    cfg = fitted['fit']['config']
    account = run_account(d, cfg)
    card = score(d, cfg, account, labels)
    random_order, random_entries = [], []
    for seed in range(20):
        random = run_account(d, cfg, random_order=150000 + seed)
        random_order.append(dict(seed=150000 + seed, account_id=random['id'],
                            summary=old.card_summary(score(d, cfg, random, longs)['rows']),
                            account=random['summary']))
        random = run_account(d, cfg, placebo=151000 + seed)
        random_entries.append(dict(seed=151000 + seed, account_id=random['id'], account=random['summary']))
        print('controls', seed + 1, '/ 20', flush=True)
    buy_expectation = float(np.mean([r['summary']['bought'] for r in random_order]))
    weight_expectation = float(np.mean([r['summary']['weighted_coverage'] for r in random_order]))
    true = old.card_summary([r for r in card['rows'] if r['side'] > 0])
    controls = dict(order_random=random_order, entry_random=random_entries,
                    buy_expectation=buy_expectation, weight_expectation=weight_expectation,
                    buy_ratio=true['bought'] / buy_expectation if buy_expectation else None,
                    clearly_better=true['bought'] >= buy_expectation + 3 and true['weighted_coverage'] >= weight_expectation + .05,
                    placebo_median=float(np.median([r['account']['total'] for r in random_entries])),
                    placebo_p90=float(np.percentile([r['account']['total'] for r in random_entries], 90)))
    output('random', controls)
    baseline = old.read(REPORTS / (old.PREFIX + 'long.json'))
    shuffled = [old.read(REPORTS / (PREFIX + 'shuffle_' + str(s) + '.json')) for s in SEEDS]
    def anti(kind):
        real = fitted['cv']['summary'] if kind == 'cv' else fitted['fit']['metrics']
        samples = [r['cv']['summary'] if kind == 'cv' else r['fit']['metrics'] for r in shuffled]
        best_count = max(r['bought'] for r in samples)
        best_weight = max(r['weighted_coverage'] for r in samples)
        return dict(true=real, best_count=best_count, best_weight=best_weight,
                    passed=real['bought'] >= best_count + 3 and real['weighted_coverage'] >= best_weight + .05)
    best = sorted((tr for tr in account['trades'] if tr['why'] != 'end'), key=lambda tr: -tr['ret'])[:2]
    drop = run_account(d, cfg, drop=[(tr['entry'], tr['code']) for tr in best])
    signal = signal_reference(d, cfg, longs)
    build(d, cfg)
    widths = old.signal_baseline(d, cfg, longs)['widths']
    matched = old.matched_signal_random(d, cfg, longs)
    final_diagnosis = diagnosis(d, cfg, account, longs)
    output('final_diagnosis', final_diagnosis)
    baseline_account = run_account(d, BASE)
    baseline_held_rows = []
    for h in old.HALVES:
        held = [r for r in longs if r['half'] == h]
        baseline_held_rows.extend(score(d, BASE, baseline_account, held)['rows'])
    result = dict(config=cfg, fixed=FIXED, account_id=account['id'], account=account['summary'], card=card,
                    long=true, baseline=dict(account=baseline['account'],
                        long=old.card_summary([r for r in baseline['card']['rows'] if r['side'] > 0]),
                        fixed_cv=old.card_summary(baseline_held_rows)),
                    controls=controls, signal=dict(**signal, widths=widths,
                        lift=true['signal'] / signal['expected'] if signal['expected'] else 0., matched=matched),
                    cv=fitted['cv'], shuffled=[dict(seed=s, full=r['fit']['metrics'], cv=r['cv']['summary'])
                                              for s, r in zip(SEEDS, shuffled)],
                    anti=dict(full=anti('full'), cv=anti('cv')),
                    drop2=dict(removed=best, account_id=drop['id'], summary=drop['summary'],
                               beats_random=drop['summary']['total'] > controls['placebo_median']),
                    human=baseline['human'], human_source=old.sha(REPORTS / (old.PREFIX + 'long.json')),
                    remaining=final_diagnosis['counts'])
    result['selection_improved'] = cfg != BASE and true['bought'] >= result['baseline']['long']['bought'] \
        and true['weighted_coverage'] >= result['baseline']['long']['weighted_coverage']
    result['anti']['passed'] = result['anti']['full']['passed'] and result['anti']['cv']['passed']
    output('final', result)
    fields = sorted({key for r in card['rows'] for key in r})
    with (REPORTS / (PREFIX + 'trades.csv')).open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for r in card['rows']:
            writer.writerow({k: json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v for k, v in r.items()})
    for round_ in fitted['fit']['rounds']:
        output('round' + str(round_['round']), round_)
    print('final long', true, 'anti', result['anti']['passed'], flush=True)


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
    elif args.tag:
        run_search(args.tag)
    else:
        search_all()
    print('RSS MiB', resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, flush=True)


if __name__ == '__main__':
    main()
