"""IE14: causal daily plans, the shared account engine, and transaction-level replication."""
from __future__ import annotations

import argparse
import ast
from collections import Counter, defaultdict
import csv
from dataclasses import asdict, replace
from datetime import date
import gc
import hashlib
import json
import math
import os
from pathlib import Path
import resource
import sys

import numpy as np

from studies import trader_data as TD
from studies.trader_replication import ie_factor_library as lib, ledger, panels, system

ROOT = Path(__file__).resolve().parents[2]
REPORTS = ROOT / 'studies/trader_replication/reports/gap_review'
WORK = REPORTS / 'ie14_work'
OLD = REPORTS / 'ie5_work'
PLAN = ROOT / 'studies/martin_luk/notes/PLAN_IE14_CN.md'
PREREG = ROOT / 'studies/martin_luk/notes/PREREG_IE14_CN.md'
LEDGER = ROOT / 'studies/martin_luk/notes/trades.csv'
PREFIX = 'strong_continue_ie14_'
HALVES = tuple(str(y) + 'H' + str(h) for y in range(2024, 2027) for h in (1, 2))
SEEDS = (140101, 140103, 140107, 140109, 140111)
NAMES = ('adr', 'money', 'e9', 'e21', 'e50', 'pullback', 'inside', 'narrow', 'ep',
         'reentry', 'climax', 'peer', 'ie8', 'short50', 'short21', 'short9', 'weekly_weak')
BASE = dict(pool='premier', hot=True, trend='stack', setup='three', market='both21',
            trigger='high', stop_cap=3, max_open=4, trail=9, priority='money', feedback=True)
GOALS = {'2024': dict(count=423, win=104 / 423, payoff=5., return_=2.83),
         '2025': dict(count=940, win=209 / 940, payoff=6.7, return_=9.698)}


def read(path):
    return json.loads(Path(path).read_text())


def clean(value):
    if isinstance(value, dict):
        return {str(k): clean(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [clean(v) for v in value]
    if isinstance(value, np.ndarray):
        return clean(value.tolist())
    if isinstance(value, np.generic):
        return clean(value.item())
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(clean(value), ensure_ascii=False, separators=(',', ':'), allow_nan=False) + '\n')
    temp.replace(path)


def output(name, value):
    save(REPORTS / (PREFIX + name + '.json'), value)


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        while block := f.read(1024 * 1024):
            h.update(block)
    return h.hexdigest()


def key(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()[:24]


def half(day):
    return day[:4] + ('H1' if day[5:7] <= '06' else 'H2')


def lag(a, n=1):
    out = np.full_like(np.asarray(a, float), np.nan)
    out[n:] = a[:-n]
    return out


def features(a, days=None):
    """One security at a time. Every value at t uses observations through t."""
    o, h, l, c, v, money = (np.asarray(a[k], float) for k in ('o', 'h', 'l', 'c', 'v', 't'))
    adr = 100 * lib.roll(lib.divide(h, l) - 1, 20)
    e9, e21, e50 = (lib.smooth(c, n) for n in (9, 21, 50))
    hi60, hi20 = lag(lib.roll(h, 60, 'max')), lag(lib.roll(h, 20, 'max'))
    width = h - l
    pull = ((l <= e9) & (c >= e9)) | ((l <= e21) & (c >= e21))
    inside = (h < lag(h)) & (l > lag(l))
    narrow = width <= lib.roll(width, 7, 'min')
    ep = (o >= lag(c) * 1.10) & (c >= hi60 * .9)
    climax = (money > lag(lib.roll(money, 252, 'max'))) & (h >= hi60 * .98) \
        & (lib.divide(c, e9) - 1 >= adr / 100)
    first_break = (c < e50) & (lag(c) >= lag(e50))
    seen = np.zeros(len(c), bool)
    active = False
    for t in range(len(c)):
        if first_break[t]:
            active = True
        elif c[t] > e50[t]:
            active = False
        seen[t] = active
    short = {}
    for n, line in ((50, e50), (21, e21), (9, e9)):
        touch = (h >= line * .99) & (c < line) & (line < lag(line, 3))
        touch &= (e9 <= e21 * 1.03) & (abs(lib.divide(e9, e21) - 1) <= .05)
        if n == 50:
            touch &= lag(seen.astype(float)) == 1
            # The first retest since a causal break; a new break resets the episode.
            used = False
            for t in range(len(c)):
                if first_break[t]:
                    used = False
                if touch[t] and used:
                    touch[t] = False
                elif touch[t]:
                    used = True
        short['short' + str(n)] = touch
    weekly_weak = np.zeros(len(c), bool)
    w9 = w21 = previous9 = np.nan
    last_week = None
    completed = False
    def finish(value):
        nonlocal w9, w21, previous9
        if np.isfinite(value):
            previous9 = w9
            w9 = w9 + .2 * (value - w9) if np.isfinite(w9) else value
            w21 = w21 + (value - w21) / 11 if np.isfinite(w21) else value
    for t in range(len(c)):
        day = date.fromisoformat(str(days[t])) if days is not None else None
        week = day.isocalendar()[:2] if day else t // 5
        if last_week is not None and week != last_week and not completed:
            finish(c[t - 1])
        if week != last_week:
            completed = False
        if (day.weekday() == 4 if day else t % 5 == 4):
            finish(c[t])
            completed = True
        weekly_weak[t] = c[t] < w9 and (w9 < previous9 or w9 < w21)
        last_week = week
    return dict(adr=adr, money=lib.roll(money, 20), e9=e9, e21=e21, e50=e50,
                pullback=pull, inside=inside, narrow=narrow, ep=ep,
                reentry=((l <= e9) & (c >= e9)) | (c > hi20), climax=climax,
                weekly_weak=weekly_weak, **short)


def prepare():
    """Read only the frozen Dataset; stream raw volume/turnover and stock-level features."""
    days = np.load(OLD / 'panel/days.npy').astype(str)
    codes = np.load(OLD / 'panel/codes.npy').astype(str)
    di, ci = {d: t for t, d in enumerate(days)}, {c: j for j, c in enumerate(codes)}
    ds = TD.dataset('us', mode='frozen', version=panels.DEFAULT)
    digest = ds.digest()
    if digest != read(ROOT / 'studies/trader_replication/DATA_PIN.json')[panels.DEFAULT]['us']:
        raise ValueError('frozen source digest changed')
    shape = len(days), len(codes)
    raw_close = np.lib.format.open_memmap(WORK / 'raw_close.npy', mode='w+', dtype='float32', shape=shape)
    raw_close[:] = np.nan
    volume = np.lib.format.open_memmap(WORK / 'volume.npy', mode='w+', dtype='float32', shape=shape)
    turnover = np.lib.format.open_memmap(WORK / 'turnover.npy', mode='w+', dtype='float32', shape=shape)
    volume[:] = turnover[:] = np.nan
    for code, day, values in ds.rows():
        if code in ci and day in di:
            t, j = di[day], ci[code]
            volume[t, j], turnover[t, j] = values[4:6]
            raw_close[t, j] = values[3]
    volume.flush()
    turnover.flush()
    px = {k: np.load(OLD / 'panel' / (v + '.npy'), mmap_mode='r')
          for k, v in (('o', 'open'), ('h', 'high'), ('l', 'low'), ('c', 'close'))}
    dest = {n: np.lib.format.open_memmap(WORK / (n + '.npy'), mode='w+', dtype='float32', shape=shape)
            for n in NAMES}
    for x in dest.values():
        x[:] = np.nan
    stock_hashes = {}
    for j, code in enumerate(codes):
        a = {k: x[:, j] for k, x in px.items()}
        a.update(v=volume[:, j], t=turnover[:, j])
        vals = features(a, days)
        path = OLD / 'stocks' / (code + '.npz')
        if path.exists():
            with np.load(path) as z:
                vals['peer'] = z['extra_peer_g5']
            stock_hashes[str(path.relative_to(ROOT))] = sha(path)
        for n, x in vals.items():
            dest[n][:, j] = x
        if j % 400 == 0:
            print('features', j, '/', len(codes), flush=True)
    # IE8's exact historical comparison scope and four filters, never a top-k selection.
    previous = read(REPORTS / 'ie5_work/prepared.json')
    raw = np.load(OLD / 'raw.npy', mmap_mode='r')
    pct = np.load(REPORTS / 'ie7_work/full_pct.npy', mmap_mode='r')
    names = read(REPORTS / 'strong_continue_ie4_frozen.json')['raw_feature_names']
    cursor = 0
    dest['ie8'][:] = 0
    for day, scope in previous['scope'].items():
        end = cursor + len(scope)
        rows = pct[cursor:end]
        keep = np.ones(len(scope), bool)
        for n, cut in (('h4_history', .6), ('adr20', .7), ('option_volume', .8), ('low20', .5)):
            keep &= np.isfinite(rows[:, names.index(n)]) & (rows[:, names.index(n)] + 1e-7 >= cut)
        dest['ie8'][di[day], [ci[c] for c, k in zip(scope, keep) if k]] = 1
        cursor = end
    if cursor != len(raw) or cursor != len(pct):
        raise ValueError('historical IE8 row alignment differs')
    for x in dest.values():
        x.flush()
    ew = np.ones(len(days))
    for t in range(1, len(days)):
        valid = (raw_close[t - 1] >= 5) & (dest['money'][t - 1] >= 20e6)
        returns = lib.divide(px['c'][t], px['c'][t - 1]) - 1
        valid &= np.isfinite(returns)
        ew[t] = ew[t - 1] * (1 + float(returns[valid].mean()) if valid.any() else 1)
    benchmark = []
    for path in sorted((ROOT / 'data/martin-luk-benchmarks-v1').glob('*.csv')):
        rows = {r['time_key'][:10]: r for r in csv.DictReader(path.open())}
        a = {k: np.array([float(rows[d][long]) if d in rows else np.nan for d in days])
             for k, long in (('o', 'open'), ('h', 'high'), ('l', 'low'), ('c', 'close'), ('v', 'volume'), ('t', 'turnover'))}
        vals = features(a, days)
        benchmark.append(dict(path=str(path.relative_to(ROOT)), sha256=sha(path),
                              close=a['c'], low=a['l'], e9=vals['e9'], e21=vals['e21'], e50=vals['e50']))
    if len(benchmark) != 2:
        raise ValueError('two cached benchmark indices required')
    meta = dict(days=days.tolist(), codes=codes.tolist(), digest=digest, names=NAMES,
                benchmark=benchmark, equal_index=ew, stocks=stock_hashes, plan_sha256=sha(PLAN), prereg_sha256=sha(PREREG))
    save(WORK / 'prepared.json', meta)
    print('prepared', shape, 'RSS MiB', resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, flush=True)


class Data:
    def __init__(self):
        self.meta = read(WORK / 'prepared.json')
        self.days, self.codes = self.meta['days'], self.meta['codes']
        self.di, self.ci = {d: i for i, d in enumerate(self.days)}, {c: j for j, c in enumerate(self.codes)}
        self.px = {k: np.load(OLD / 'panel' / (k + '.npy'), mmap_mode='r') for k in ('open', 'high', 'low', 'close')}
        self.f = {n: np.load(WORK / (n + '.npy'), mmap_mode='r') for n in NAMES}
        self.start = int(np.searchsorted(self.days, panels.WINDOW[0]))
        self.end = len(self.days)
        self._phase_px = None
        self.built = {}

    def phase_px(self):
        if self._phase_px is not None:
            return self._phase_px
        out = {}
        for name, a in self.px.items():
            path = WORK / ('phase_' + name + '.npy')
            if not path.exists():
                target = np.lib.format.open_memmap(path, mode='w+', dtype='float64', shape=(2 * len(self.days), len(self.codes)))
                for j in range(0, len(self.codes), 64):
                    target[::2, j:j + 64] = (self.px['open'] if name == 'close' else a)[:, j:j + 64]
                    target[1::2, j:j + 64] = a[:, j:j + 64]
                target.flush()
                del target
            out[name] = np.load(path, mmap_mode='r')
        out.update(dates=np.repeat(np.array(self.days), 2), codes=np.array(self.codes),
                   session=np.repeat(np.arange(len(self.days)), 2), daily_close=np.tile([False, True], len(self.days)))
        self._phase_px = out
        return out


def masks(d, cfg):
    f, c = d.f, d.px['close']
    if cfg['pool'] == 'ie8':
        pool = f['ie8'] == 1
    else:
        money, adr = {'premier': (100e6, 5), 'liquid': (20e6, 5), 'broad': (20e6, 3),
                      'fast': (2e6, 5)}[cfg['pool']]
        pool = (f['money'] >= money) & (f['adr'] > adr)
    if cfg['hot']:
        pool &= f['peer'] > 0
    trend = {'stack': (f['e9'] > f['e21']) & (f['e21'] > f['e50']),
             'early': f['e9'] > f['e21'], 'reclaim': c >= f['e9'],
             'medium': c >= f['e21'], 'all': np.isfinite(c)}[cfg['trend']]
    setups = (f['pullback'] == 1) | (f['inside'] == 1) | (f['narrow'] == 1) | (f['ep'] == 1)
    if cfg['setup'] in ('retest', 'support'):
        setups |= (d.px['low'] <= f['e9'] * 1.02) & (c >= f['e21'])
    if cfg['setup'] == 'support':
        setups |= (d.px['low'] <= f['e21'] * 1.02) & (c >= f['e21'] * .98)
    if cfg['setup'] == 'all':
        setups = np.isfinite(c)
    market = np.ones(len(d.days), bool)
    indices = d.meta['benchmark']
    if cfg['market'] != 'all':
        n = 'e9' if cfg['market'] == 'either9' else 'e21'
        states = [np.array(b['close']) >= np.array(b[n]) for b in indices]
        market = np.logical_and.reduce(states) if cfg['market'] == 'both21' else np.logical_or.reduce(states)
    return pool, trend, setups, market


def order(t, j, side, d, cfg, kind='long', direct=False):
    p, f = d.px, d.f
    s = t - 1
    level = p['high' if side > 0 else 'low'][s, j]
    if direct:
        fill = p['close'][t, j]
    elif cfg['trigger'] == 'open':
        fill = p['open'][t, j]
    else:
        if cfg['trigger'] == 'body':
            level = max(p['open'][s, j], p['close'][s, j]) if side > 0 else min(p['open'][s, j], p['close'][s, j])
        best = p['high' if side > 0 else 'low'][t, j]
        if not np.isfinite(best) or (best - level) * side <= 0:
            return None
        fill = max(p['open'][t, j], level) if side > 0 else min(p['open'][t, j], level)
    if not np.isfinite(fill) or fill <= 0 or not np.isfinite(f['adr'][s, j]):
        return None
    if side > 0:
        width = min(max((fill - p['low'][s, j]) / fill, .005), cfg['stop_cap'] / 100, f['adr'][s, j] / 200)
    else:
        width = max(.01, (p['high'][s, j] - fill) / fill)
    stop = fill * (1 - side * width)
    worst = p['low' if side > 0 else 'high'][t, j]
    day_stop = stop if not direct and np.isfinite(worst) and (worst - stop) * side <= 0 else None
    cap = .2 if f['money'][s, j] < 500e6 else .25
    priority = -float(f['money'][s, j])
    if cfg['priority'] == 'quiet':
        priority = float(abs(p['close'][s, j] / f['e9'][s, j] - 1))
    elif cfg['priority'] == 'strength':
        priority = -float(p['close'][s, j] / p['close'][max(0, s - 20), j] - 1)
    return (priority, j, side, float(fill), float(stop), kind, day_stop, None, cap)


def build(d, cfg, short=None):
    ident = key(dict(cfg=cfg, short=short))
    if ident in d.built:
        return d.built[ident]
    pool, trend, setup, market = masks(d, cfg)
    signal = pool & trend & setup
    short_signal = np.zeros_like(signal)
    short_market = np.ones(len(d.days), bool)
    if short:
        short_signal = (d.f['money'] >= 20e6) & (d.f['adr'] > 3) & (d.f['short' + str(short['line'])] == 1)
        if short['weekly']:
            short_signal &= d.f['weekly_weak'] == 1
        if short['market']:
            equal = np.array(d.meta['equal_index'])
            short_market = equal < lib.smooth(equal, 50)
    book = [[] for _ in range(2 * len(d.days))]
    triggers = np.zeros_like(signal)
    for t in range(d.start, d.end):
        s = t - 1
        for side, sig, gate, kind in ((1, signal, market, 'long'), (-1, short_signal, short_market, 'short')):
            for j in np.flatnonzero(sig[s]):
                e = order(t, int(j), side, d, cfg, kind)
                if e is not None:
                    if side > 0:
                        triggers[s, j] = True
                    if gate[s]:
                        book[2 * t].append(e)
    signals = dict(long=signal, short=short_signal)
    built = dict(book=book, signals=signals, pool=pool, market=market, short_market=short_market,
                 trend=trend, setup=setup, triggers=triggers)
    # Bounded reuse across fits: at most eight date-by-security diagnostic blocks.
    if len(d.built) >= 8:
        d.built.pop(next(iter(d.built)))
    d.built[ident] = built
    return built


def policy(cfg, short=None):
    return system.Rules(risk=.005, max_position=.25, max_gross=2.8, max_open=cfg['max_open'],
                        trims=(3, 5), trim_frac=.15, trail='longtrail', arm_trail_on_entry=True,
                        trail_next_open=True, add_r=1, add_frac=.5, add_filter='fresh_setup',
                        add_next_open=True, cap_adds_entry=True, feedback=3 if cfg['feedback'] else 0,
                        feedback_opened=True, risk_low=.0025, risk_high=.005,
                        intraday_kinds=('long', 'short'), short_trims=(3, 5), short_max_days=10,
                        max_days_next_open=short is not None,
                        short_trim_day=short['trim_day'] if short else 2, short_trim_day_frac=.5,
                        short_trim_next_open=True,
                        borrow_rate=.03 if short else 0,
                        management_by_kind={'short': dict(trail='shorttrail')})


def management(d, cfg):
    result = {}
    for name, field in (('longtrail', 'e' + str(cfg['trail'])), ('shorttrail', 'e9'), ('fresh_setup', 'reentry')):
        dtype = bool if name == 'fresh_setup' else float
        a = np.zeros((2 * len(d.days), len(d.codes)), dtype=dtype) if dtype is bool \
            else np.full((2 * len(d.days), len(d.codes)), np.nan)
        a[1::2] = d.f[field] == 1 if dtype is bool else d.f[field]
        if dtype is not bool:
            a[2::2] = d.f[field][:-1]
        if name == 'longtrail':
            # An additional close-confirmed sell schedules the same next-open trail path.
            high_volume = d.f['climax'] == 1
            a[1::2] = np.where(high_volume, d.px['close'] * 2, a[1::2])
        result[name] = a
    return result


def summarize_account(curve, dates, trades, track):
    closed = [t for t in trades if t['why'] != 'end']
    def sample_stats(rows):
        ended = [t for t in rows if t['why'] != 'end']
        win = [t for t in ended if t['ret'] > 0]
        loss = [t for t in ended if t['ret'] <= 0]
        aw = np.mean([t['ret'] for t in win]) if win else None
        al = np.mean([t['ret'] for t in loss]) if loss else None
        profit = sum(max(0, t['pnl']) for t in rows)
        top = sorted((max(0, t['pnl']) for t in rows), reverse=True)
        return dict(entries=len(rows), closed=len(ended), open=len(rows) - len(ended),
                    win=len(win) / len(ended) if ended else None, payoff=aw / -al if aw and al and al < 0 else None,
                    avg_win=aw, avg_loss=al, days_win=np.mean([t['days'] for t in win]) if win else None,
                    days_loss=np.mean([t['days'] for t in loss]) if loss else None,
                    profit=profit, tuition=-sum(min(0, t['pnl']) for t in rows),
                    top2=sum(top[:2]) / profit if profit else None,
                    top10=sum(top[:max(1, len(rows) // 10)]) / profit if profit else None,
                    adds=sum(x['action'] == 'add' for t in rows for x in t['executions']),
                    partials=sum(x['action'] in ('trim', 'day_trim', 'day_trim_open') for t in rows for x in t['executions']))
    result = dict(total=float(curve[-1] - 1), maxdd=float(np.max(1 - np.r_[1., curve] / np.maximum.accumulate(np.r_[1., curve]))),
                  overall=sample_stats(trades), annual={}, halfyear={}, quarterly={},
                  max_open=max(track.get('open', [0])), max_gross=max(track.get('gross', [0])))
    for period in (*GOALS, '2026', *HALVES):
        mask = np.array([s.startswith(period) if 'H' not in period else half(s) == period for s in dates])
        ix = np.flatnonzero(mask)
        rows = [t for t in trades if t['entry'].startswith(period) if 'H' not in period] if 'H' not in period \
            else [t for t in trades if half(t['entry']) == period]
        st = sample_stats(rows)
        if len(ix):
            base = curve[ix[0] - 1] if ix[0] else 1.
            st['return'] = float(curve[ix[-1]] / base - 1)
        if period in GOALS:
            goal = GOALS[period]
            st['count_ok'] = .7 * goal['count'] <= st['entries'] <= 1.3 * goal['count']
            st['win_ok'] = st['win'] is not None and st['win'] <= .35 and .7 * goal['win'] <= st['win'] <= 1.3 * goal['win']
            st['payoff_ok'] = st['payoff'] is not None and .7 * goal['payoff'] <= st['payoff'] <= 1.3 * goal['payoff']
            st['log_gap'] = abs(math.log((1 + st['return']) / (1 + goal['return_']))) if st.get('return', -1) > -1 else 99.
        result['halfyear' if 'H' in period else 'annual'][period] = st
    for year in range(2024, 2027):
        for q in range(1, 5):
            rows = [t for t in trades if t['entry'][:4] == str(year) and (int(t['entry'][5:7]) - 1) // 3 + 1 == q]
            winners = [t for t in rows if t['ret'] >= .3 or t['r'] >= 5]
            result['quarterly'][str(year) + 'Q' + str(q)] = dict(big_winners=len(winners),
                names=len({t['code'] for t in winners}), winner_profit=sum(t['pnl'] for t in winners), **sample_stats(rows))
    return clean(result)


def run_account(d, cfg, short=None, random_order=None, placebo=None, only=None, drop=None, human=None):
    ident = key(dict(cfg=cfg, short=short, random_order=random_order, placebo=placebo, only=only, drop=drop, human=human))
    path = WORK / 'accounts' / (ident + '.json')
    if path.exists():
        return read(path)
    b = build(d, cfg, short)
    book = b['book']
    if only or drop or random_order is not None or human is not None:
        book = [list(rows) for rows in book]
    if human is not None:
        book = [[] for _ in book]
        for label in human:
            if label['code'] not in d.ci:
                continue
            t, j = label['anchor'], d.ci[label['code']]
            e = order(t, j, label['side'], d, cfg, 'long' if label['side'] > 0 else 'short', direct=True)
            if e is not None:
                book[2 * t + 1].append(e)
    if only:
        side = 1 if only == 'long' else -1
        book = [[e for e in rows if e[2] == side] for rows in book]
    if drop:
        removed = {tuple(x) for x in drop}
        book = [[e for e in rows if (str(d.days[t // 2]), d.codes[e[1]]) not in removed] for t, rows in enumerate(book)]
    if random_order is not None:
        rng = np.random.default_rng(random_order)
        book = [[(float(rng.random()), *e[1:]) for e in rows] for rows in book]
    ema = management(d, cfg)
    rules = policy(cfg, short)
    if human is not None:
        rules = replace(rules, intraday_kinds=())
    px = d.phase_px()
    track = {}
    pool = None
    if placebo is not None:
        pool = np.zeros((2 * len(d.days), len(d.codes)), bool)
        pool[2:] = np.repeat(b['pool'][:-1], 2, axis=0)
        if short:
            short_pool = (d.f['money'] >= 20e6) & (d.f['adr'] > 3)
            short_phase = np.zeros_like(pool)
            short_phase[2:] = np.repeat(short_pool[:-1], 2, axis=0)
            px = dict(px, kind_pools={'long': pool, 'short': short_phase})
    rng = np.random.default_rng(placebo) if placebo is not None else None
    curve, dates, trades = system.simulate(px, ema, rules, book, *panels.WINDOW,
                                          audit=True, track=track, placebo=rng, pool=pool)
    curve, dates = curve[1::2], dates[1::2]
    for t in trades:
        if t['why'] == 'trail_open':
            s = d.di[t.get('trail_signal', t['exit'])]
            if t['side'] > 0 and d.f['climax'][s, d.ci[t['code']]] == 1:
                t['sell_reason'] = 'climax'
            else:
                t['sell_reason'] = 'ema' + str(cfg['trail'] if t['side'] > 0 else 9)
        else:
            t['sell_reason'] = t['why']
    result = dict(id=ident, config=cfg, short=short, summary=summarize_account(curve, dates, trades, track),
                  curve=curve, dates=dates, trades=trades)
    # Check actual daily prices, including every add, partial, and stop. End marks are valuations.
    invalid = []
    for trade in trades:
        j = d.ci[trade['code']]
        for x in trade['executions']:
            t = d.di[x['time']]
            if x['action'] != 'end' and not d.px['low'][t, j] - 1e-8 <= x['price'] <= d.px['high'][t, j] + 1e-8:
                invalid.append(dict(code=trade['code'], **x))
    if invalid:
        raise AssertionError(('executions outside real daily range', invalid[:3]))
    result['fills_valid'] = True
    save(path, result)
    del ema, pool
    return clean(result)


def labels(d):
    result = []
    for row in ledger.load(LEDGER):
        lo = max(d.start, int(np.searchsorted(d.days, row.window_lo)) - 2)
        hi = min(len(d.days) - 1, int(np.searchsorted(d.days, row.window_hi, side='right')) + 1)
        anchor = int(np.searchsorted(d.days, row.entry_date)) if row.entry_date else \
            (int(np.searchsorted(d.days, row.window_lo)) + int(np.searchsorted(d.days, row.window_hi, side='right')) - 1) // 2
        anchor = min(max(anchor, d.start), len(d.days) - 1)
        code = 'US.' + row.ticker
        side = 1 if row.side == 'long' else -1
        value = dict(id=row.id, code=code, side=side, precision=row.precision, outcome=row.outcome,
                     entry_date=row.entry_date, note=row.note, source=row.source, anchor=anchor, lo=lo, hi=hi,
                     half=half(d.days[anchor]), r=row.r_multiple, space=None, peak=None, right_censored=False)
        if code in d.ci:
            j, end = d.ci[code], min(len(d.days), anchor + 61)
            prices = d.px['high' if side > 0 else 'low'][anchor:end, j]
            fill = d.px['close'][anchor, j]
            good = np.isfinite(prices)
            if np.isfinite(fill) and fill > 0 and good.any():
                k = int(np.nanargmax(prices) if side > 0 else np.nanargmin(prices))
                value.update(space=max(0., side * (float(prices[k]) / fill - 1)), peak=anchor + k,
                             right_censored=end - anchor < 61)
        loss = row.outcome == 'loss' or (row.r_multiple is not None and row.r_multiple < 0)
        if loss:
            weight = 0.
        elif row.r_multiple is not None:
            weight = max(0., row.r_multiple)
        else:
            weight = (value['space'] or 0) / ((row.stop_pct or 3.) / 100)
        value['weight'] = weight
        value['weight_kind'] = 'published_r' if row.r_multiple is not None else 'price_proxy'
        value['group'] = 'loss' if loss else ('big' if (row.r_multiple or 0) >= 5 or (value['space'] or 0) >= .3 else 'other')
        value['mistake'] = any(s in row.note.lower() for s in ('panic-sold', 'exited early by mistake', 'ignored stop', 'no hard stop'))
        result.append(value)
    return result


def match(rows, events):
    """Maximum one-to-one matching; narrow windows first and nearest fills preferred."""
    available = defaultdict(list)
    for i, e in enumerate(events):
        available[(e['code'], e['side'])].append(i)
    neighbors = {r['id']: sorted((i for i in available[(r['code'], r['side'])] if r['lo'] <= events[i]['t'] <= r['hi']),
                                key=lambda i: (abs(events[i]['t'] - r['anchor']), events[i]['t'], i)) for r in rows}
    assigned = {}
    def visit(label, seen):
        for i in neighbors[label]:
            if i in seen:
                continue
            seen.add(i)
            if i not in assigned or visit(assigned[i], seen):
                assigned[i] = label
                return True
        return False
    for row in sorted(rows, key=lambda r: (r['hi'] - r['lo'], r['anchor'], r['id'])):
        visit(row['id'], set())
    return {label: i for i, label in assigned.items()}


def sell_comparison(row, trade, d):
    note = row['note'].lower()
    stated_dates = sorted(set(__import__('re').findall(r'\b\d{4}-\d{2}-\d{2}\b', note)))
    expected = []
    if 'stop' in note:
        expected.append('stop')
    if '9 ema' in note or '9ema' in note:
        expected.append('ema9')
    if 'climax' in note or 'high-volume' in note:
        expected.append('climax')
    if any(s in note for s in ('half', 'trim', 'chunks', 'partials', 'some at', 'sold some')):
        expected.append('partial')
    date_ok = None
    reason_ok = None
    if trade and stated_dates:
        actual_dates = [x['time'] for x in trade['executions'] if x['action'] not in ('entry', 'add', 'end')]
        date_ok = all(any(abs(int(np.searchsorted(d.days, a)) - int(np.searchsorted(d.days, b))) <= 2
                          for a in actual_dates) for b in stated_dates)
    if trade and expected:
        actions = [x['action'] for x in trade['executions']]
        actual = trade.get('sell_reason', trade['why'])
        reason_ok = all(('stop' in actual if e == 'stop' else
                         any(x in ('trim', 'day_trim', 'day_trim_open') for x in actions) if e == 'partial' else actual == e) for e in expected)
    return dict(stated_dates=stated_dates, expected=expected, date_ok=date_ok, reason_ok=reason_ok,
                reproduction_target=not row['mistake'])


def card_summary(rows):
    n = len(rows)
    weight = sum(r['weight'] for r in rows)
    bought = [r for r in rows if r['bought']]
    bought_weight = sum(r['weight'] for r in bought)
    positive = [r for r in bought if (r['space'] or 0) > 0]
    capture = sum(r['weight'] * (r['capture_raw'] or 0.) for r in bought) / bought_weight if bought_weight else 0.
    clipped = sum(r['weight'] * r['capture_clip'] for r in bought) / bought_weight if bought_weight else 0.
    return dict(n=n, signal=sum(r['signal'] for r in rows), bought=len(bought),
                closed=sum(r['closed'] for r in bought), weight=weight, bought_weight=bought_weight,
                weighted_coverage=bought_weight / weight if weight else 0., capture=capture, capture_clipped=clipped,
                product=(bought_weight / weight * capture) if weight else 0.,
                capture_raw=np.mean([r['capture_raw'] for r in positive]) if positive else None,
                washed=sum(r['washed'] for r in bought), washed_denominator=len(positive),
                wash_rate=sum(r['washed'] for r in bought) / len(positive) if positive else None,
                funnel=dict(Counter(r['stage'] for r in rows)),
                no_signal=dict(Counter(r.get('no_signal') for r in rows if r['stage'] == '没信号')),
                weights={kind: dict(weight=sum(r['weight'] for r in rows if r['weight_kind'] == kind),
                                   bought_weight=sum(r['weight'] for r in bought if r['weight_kind'] == kind))
                         for kind in ('published_r', 'price_proxy')})


def score(d, cfg, account, lab, short=None, supplied=False):
    b = build(d, cfg, short)
    events = []
    columns = sorted({d.ci[r['code']] for r in lab if r['code'] in d.ci})
    for side, name in ((1, 'long'), (-1, 'short')):
        for t in range(d.start - 1, len(d.days)):
            events.extend(dict(t=t, code=d.codes[j], side=side) for j in columns if b['signals'][name][t, j])
    sm = match(lab, events)
    trades = account['trades']
    actual = [dict(t=d.di[t['entry']], code=t['code'], side=t['side']) for t in trades]
    bm = match(lab, actual)
    rows = []
    for label in lab:
        r = dict(label)
        trade = trades[bm[r['id']]] if r['id'] in bm else None
        r.update(signal=r['id'] in sm or supplied, bought=trade is not None, closed=False,
                 washed=False, capture_raw=None, capture_clip=0., actual_entry=None, actual_exit=None,
                 sell_reason=None, pnl=None, return_=None, trade_index=bm.get(r['id']))
        if trade:
            end = d.di[trade['exit']]
            r.update(actual_entry=trade['entry'], actual_exit=trade['exit'], sell_reason=trade['sell_reason'],
                     pnl=trade['pnl'], return_=trade['ret'], closed=trade['why'] != 'end')
            if (r['space'] or 0) > 0:
                r['capture_raw'] = trade['ret'] / r['space']
                r['capture_clip'] = min(1., max(0., r['capture_raw']))
                r['washed'] = r['peak'] is not None and end < r['peak'] and 'stop' in trade['why']
        r['sell_comparison'] = sell_comparison(r, trade, d)
        if trade:
            if r['washed']:
                r['stage'] = '买到被洗出'
            elif r['closed'] and ((r['space'] or 0) <= 0 or r['capture_clip'] >= .5) \
                    and (r['mistake'] or not (r['sell_comparison']['date_ok'] is False or r['sell_comparison']['reason_ok'] is False)):
                r['stage'] = '对上'
            else:
                r['stage'] = '卖早卖晚'
        elif supplied:
            r['stage'] = '没仓位'
            r['capacity_detail'] = '指定本人机会未成交：数据不足、同票重复或账户容量'
        elif not r['signal']:
            r['stage'] = '没信号'
            if r['code'] not in d.ci:
                r['no_signal'] = '缺缓存'
            else:
                j, sl = d.ci[r['code']], slice(max(d.start - 1, r['lo'] - 1), r['hi'] + 1)
                if not np.any(b['pool'][sl, j]):
                    r['no_signal'] = '股票池'
                elif not np.any(b['pool'][sl, j] & b['trend'][sl, j]):
                    r['no_signal'] = '领涨'
                else:
                    r['no_signal'] = '买点或独立尝试不足'
        else:
            sig = events[sm[r['id']]] if r['id'] in sm else None
            gate = b['market'] if r['side'] > 0 else b['short_market']
            j = d.ci.get(r['code'])
            signame = 'long' if r['side'] > 0 else 'short'
            window = slice(r['lo'], r['hi'] + 1)
            allowed = j is not None and np.any(b['signals'][signame][window, j] & gate[window])
            r['stage'] = '被市况挡' if sig is not None and not allowed else '没仓位'
            if r['stage'] == '没仓位':
                j = d.ci.get(r['code'])
                offered = any(e[1] == j and e[2] == r['side'] for t in range(r['lo'], r['hi'] + 1) for e in b['book'][2 * t])
                r['capacity_detail'] = '账户容量或已持同票' if offered else '次日未越触发价'
        rows.append(r)
    groups = {'all': card_summary(rows)}
    for period in HALVES:
        sample = [r for r in rows if r['half'] == period]
        groups[period] = dict(all=card_summary(sample),
            **{name: card_summary([r for r in sample if r['side'] == side]) for side, name in ((1, 'long'), (-1, 'short'))},
            **{name: card_summary([r for r in sample if r['group'] == name]) for name in ('big', 'loss', 'other')},
            intersections={name + ':' + group: card_summary([r for r in sample if r['side'] == side and r['group'] == group])
                           for side, name in ((1, 'long'), (-1, 'short')) for group in ('big', 'loss', 'other')})
    groups['exact'] = card_summary([r for r in rows if r['precision'] == 'exact'])
    groups['window'] = card_summary([r for r in rows if r['precision'] == 'window'])
    return clean(dict(groups=groups, rows=rows, account_id=account['id']))


def training_rows(lab, held=None):
    if held is None:
        return list(lab)
    days = read(WORK / 'prepared.json')['days']
    return [r for r in lab if r['half'] != held and all(half(days[t]) != held
            for t in range(r['lo'], min(len(days), max(r['hi'] + 1, r['anchor'] + 61))))]


def selection(card, account, lab, held=None):
    use = {r['id'] for r in training_rows(lab, held)}
    rows = [r for r in card['rows'] if r['id'] in use and r['side'] > 0]
    summary = card_summary(rows)
    annual = account['summary']['annual']
    behavior = sum(int(row[field]) for y, row in annual.items() if y in GOALS
                   and (held is None or not held.startswith(y)) for field in ('count_ok', 'win_ok', 'payoff_ok'))
    # Equity attribution uses only training dates, never a held-out semester's returns.
    curve = np.r_[1., account['curve']]
    returns = curve[1:] / curve[:-1]
    logs = 0.
    for y, goal in GOALS.items():
        ix = [i for i, day in enumerate(account['dates']) if day.startswith(y) and (held is None or half(day) != held)]
        if ix:
            ours = float(np.prod(returns[ix]))
            target = (1 + goal['return_']) ** (len(ix) / sum(day.startswith(y) for day in account['dates']))
            logs += abs(math.log(max(ours, 1e-30) / target))
    return dict(**summary, behavior=behavior, year_distance=logs,
                rank=[summary['product'], behavior, -logs], ids=sorted(use))


def proposals(cfg, metrics, round_number, seen=()):
    """Bounded alternatives from the largest current funnel layer, registered before execution."""
    funnel = metrics['funnel']
    changes = []
    if round_number == 2:
        changes.append(dict(pool='ie8', hot=False))
    pool = [dict(hot=False), dict(pool='liquid'), dict(pool='broad'), dict(pool='fast')]
    pool += [dict(pool=n, hot=False) for n in ('liquid', 'broad', 'fast')]
    menus = {'没信号': [],
             '被市况挡': [dict(market=n) for n in ('either21', 'either9', 'all')],
             '没仓位': [dict(max_open=n) for n in (6, 8, 11)] + [dict(priority=n) for n in ('quiet', 'strength')],
             '买到被洗出': [dict(stop_cap=n) for n in (2, 3, 5)] + [dict(trigger='body'), dict(setup='support')],
             '卖早卖晚': [dict(trail=21), dict(feedback=False), dict(priority='quiet')]}
    submenus = {'股票池': pool, '领涨': [dict(trend=n) for n in ('early', 'reclaim', 'medium', 'all')],
                '买点或独立尝试不足': [dict(setup=n) for n in ('retest', 'support', 'all')]
                + [dict(trigger='body'), dict(trigger='open')]}
    for sub in sorted(submenus, key=lambda n: -metrics['no_signal'].get(n, 0)):
        menus['没信号'].extend(submenus[sub])
    for largest in sorted(menus, key=lambda n: -funnel.get(n, 0)):
        candidates = []
        for change in changes + menus[largest]:
            candidate = dict(cfg, **change)
            if candidate != cfg and key(candidate) not in seen and candidate not in candidates:
                candidates.append(candidate)
        if candidates:
            return largest, candidates[:5]
    return '候选已尽', []


def preserves_replication(reference, candidate):
    return candidate['bought'] >= reference['bought'] and candidate['closed'] >= reference['closed'] \
        and candidate['weighted_coverage'] + 1e-12 >= reference['weighted_coverage'] \
        and candidate['capture'] + 1e-12 >= reference['capture']


def search(d, lab, tag, held=None):
    path = WORK / 'searches' / (tag + '.json')
    if path.exists():
        return read(path)
    cfg = dict(BASE)
    train_lab = training_rows(lab, held)
    account = run_account(d, cfg)
    card = score(d, cfg, account, train_lab)
    chosen = selection(card, account, lab, held)
    if tag == 'true' and held is None:
        output('round1', dict(config=cfg, account=account['summary'], card=card,
                             signal_baseline=signal_baseline(d, cfg, lab)))
    rounds = [dict(round=1, config=cfg, account_id=account['id'], metrics=chosen, initial_only=True)]
    seen = {key(cfg)}
    for number in range(2, 8):
        layer, candidates = proposals(cfg, chosen, number, seen)
        registration = dict(round=number, reference=cfg, layer=layer, candidates=candidates,
                            heldout=held, training_ids=chosen['ids'], reference_metrics=chosen)
        reg_path = WORK / 'registrations' / (tag + '_r' + str(number) + '.json')
        if reg_path.exists() and read(reg_path) != clean(registration):
            raise ValueError('round registration changed')
        save(reg_path, registration)
        results = []
        for candidate in candidates:
            seen.add(key(candidate))
            metric_path = WORK / 'metrics' / (key(dict(config=candidate, tag=tag, held=held)) + '.json')
            if metric_path.exists():
                evaluated = read(metric_path)
            else:
                ac = run_account(d, candidate)
                sc = score(d, candidate, ac, train_lab)
                evaluated = dict(config=candidate, account_id=ac['id'], metrics=selection(sc, ac, lab, held))
                save(metric_path, evaluated)
            metric = evaluated['metrics']
            results.append(dict(evaluated, eligible=preserves_replication(chosen, metric)))
        winners = [r for r in results if r['eligible'] and r['metrics']['rank'] > chosen['rank']]
        if winners:
            best = max(winners, key=lambda r: r['metrics']['rank'])
            cfg, chosen = best['config'], best['metrics']
        rounds.append(dict(round=number, layer=layer, candidates=results, adopted=cfg, metrics=chosen))
        save(WORK / 'searches' / (tag + '_progress.json'), dict(rounds=rounds))
        print(tag, 'round', number, 'buy', chosen['bought'], '/', chosen['n'],
              'weighted', round(chosen['weighted_coverage'], 4), 'capture', round(chosen['capture'], 4), flush=True)
    result = dict(tag=tag, heldout=held, rounds=rounds, config=cfg, metrics=chosen)
    save(path, result)
    return result


def shuffle_labels(d, lab, seed):
    rng = np.random.default_rng(seed)
    out = []
    for label in lab:
        r = dict(label)
        width, offset = r['hi'] - r['lo'], r['anchor'] - r['lo']
        possible = [t for t in range(d.start, len(d.days) - width) if half(d.days[t + offset]) == r['half']
                    and (t + width < r['lo'] or t > r['hi'])]
        if not possible:
            possible = [t for t in range(d.start, len(d.days) - width)
                        if half(d.days[t + offset]) == r['half'] and t != r['lo']]
        if possible:
            start = int(rng.choice(possible))
            r.update(lo=start, hi=start + width, anchor=start + offset)
        if r['code'] in d.ci:
            j, anchor = d.ci[r['code']], r['anchor']
            prices = d.px['high' if r['side'] > 0 else 'low'][anchor:anchor + 61, j]
            fill = d.px['close'][anchor, j]
            if np.isfinite(fill) and fill > 0 and np.isfinite(prices).any():
                k = int(np.nanargmax(prices) if r['side'] > 0 else np.nanargmin(prices))
                r.update(space=max(0., r['side'] * (float(prices[k]) / fill - 1)), peak=anchor + k,
                         right_censored=len(prices) < 61)
            else:
                r.update(space=None, peak=None)
        # Weights/outcomes remain the same label; only its same-security time window moves.
        out.append(r)
    return out


def cv(d, lab, tag):
    folds, rows = {}, []
    for h in HALVES:
        fit = search(d, lab, tag + '_' + h, h)
        account = run_account(d, fit['config'])
        held = [r for r in lab if r['half'] == h and r['side'] > 0]
        result = score(d, fit['config'], account, held)
        rows.extend(result['rows'])
        folds[h] = dict(config=fit['config'], training_ids=fit['metrics']['ids'], score=result,
                        account_id=account['id'])
    result = dict(folds=folds, summary=card_summary(rows), rows=rows)
    save(WORK / (tag + '_cv.json'), result)
    return clean(result)


def run_search(tag):
    d = Data()
    lab = labels(d)
    seed = None if tag == 'true' else int(tag.rsplit('_', 1)[1])
    if seed is not None:
        lab = shuffle_labels(d, lab, seed)
    fit = search(d, lab, tag)
    result = dict(fit=fit, cv=cv(d, lab, tag))
    output(tag, result)


def signal_baseline(d, cfg, lab, short=None):
    b = build(d, cfg, short)
    out = []
    for row in lab:
        remain = 1.
        j = d.ci.get(row['code'])
        for t in range(row['lo'], row['hi'] + 1):
            if j is None:
                continue
            sig = b['signals']['long' if row['side'] > 0 else 'short'][t]
            universe = b['pool'][t] if row['side'] > 0 else np.isfinite(d.px['close'][t]) & (d.f['money'][t] >= 20e6)
            n = int(universe.sum())
            if n and universe[j]:
                remain *= 1 - min(1., int(sig.sum()) / n)
        out.append(dict(id=row['id'], probability=1 - remain))
    widths = {}
    for h in HALVES:
        ix = [t for t in range(d.start, len(d.days)) if half(d.days[t]) == h]
        widths[h] = {name: dict(median=float(np.median(sig[ix].sum(1))), mean=float(sig[ix].sum(1).mean()),
                               maximum=int(sig[ix].sum(1).max()), total=int(sig[ix].sum()))
                     for name, sig in b['signals'].items()}
    return dict(expected=sum(r['probability'] for r in out), rows=out, widths=widths,
                note='Analytic union before one-to-one matching; long overlapping windows may share chance events.')


def matched_signal_random(d, cfg, lab, short=None):
    b = build(d, cfg, short)
    draws = []
    for seed in range(20):
        rng = np.random.default_rng(143000 + seed)
        events = []
        for t in range(d.start - 1, len(d.days)):
            for side, name in ((1, 'long'), (-1, 'short')):
                width = int(b['signals'][name][t].sum())
                if not width:
                    continue
                universe = b['pool'][t] if side > 0 else (d.f['money'][t] >= 20e6) & (d.f['adr'][t] > 3)
                candidates = np.flatnonzero(universe)
                for j in rng.choice(candidates, min(width, len(candidates)), replace=False):
                    events.append(dict(t=t, code=d.codes[j], side=side))
        matches = match(lab, events)
        draws.append(dict(seed=143000 + seed, hits=len(matches), ids=sorted(matches)))
    return dict(draws=draws, expectation=float(np.mean([r['hits'] for r in draws])))


def controls(d, cfg, lab, short=None, label='long'):
    random_rows = []
    for seed in range(20):
        ac = run_account(d, cfg, short, random_order=140000 + seed, only='short' if label == 'short' else None)
        sc = score(d, cfg, ac, lab, short)
        random_rows.append(dict(seed=140000 + seed, summary=sc['groups']['all'], account_id=ac['id'],
                                total=ac['summary']['total']))
    placebo_rows = []
    for seed in range(100):
        ac = run_account(d, cfg, short, placebo=141000 + seed, only='short' if label == 'short' else None)
        placebo_rows.append(dict(seed=141000 + seed, total=ac['summary']['total'], account_id=ac['id'],
                                 annual={y: r.get('return') for y, r in ac['summary']['annual'].items()}))
        if seed % 20 == 0:
            print(label, 'placebo', seed, flush=True)
    result = dict(order_random=random_rows, buy_expectation=float(np.mean([r['summary']['bought'] for r in random_rows])),
                  weight_expectation=float(np.mean([r['summary']['weighted_coverage'] for r in random_rows])),
                  placebo=placebo_rows, placebo_median=float(np.median([r['total'] for r in placebo_rows])),
                  placebo_p90=float(np.percentile([r['total'] for r in placebo_rows], 90)))
    output('random_' + label, result)
    return result


def finalize_long():
    d = Data()
    lab = labels(d)
    fit = read(REPORTS / (PREFIX + 'true.json'))
    cfg = fit['fit']['config']
    ac = run_account(d, cfg)
    sc = score(d, cfg, ac, lab)
    human = run_account(d, cfg, human=[r for r in lab if r['side'] > 0])
    human_sc = score(d, cfg, human, [r for r in lab if r['side'] > 0], supplied=True)
    random = controls(d, cfg, [r for r in lab if r['side'] > 0])
    best = sorted((t for t in ac['trades'] if t['why'] != 'end'), key=lambda t: -t['ret'])[:2]
    drop = run_account(d, cfg, drop=[(t['entry'], t['code']) for t in best])
    shuffled = [read(REPORTS / (PREFIX + 'shuffle_' + str(seed) + '.json')) for seed in SEEDS]
    cv_true = fit['cv']['summary']
    cv_best = dict(bought=max(r['cv']['summary']['bought'] for r in shuffled),
                   product=max(r['cv']['summary']['product'] for r in shuffled))
    baseline = run_account(d, BASE)
    compare = dict(BASE, pool='ie8', hot=False)
    compare_ac = run_account(d, compare)
    result = dict(config=cfg, account_id=ac['id'], account=ac['summary'], card=sc,
                  initial=dict(account=baseline['summary'], card=score(d, BASE, baseline, lab)),
                  ie8=dict(account=compare_ac['summary'], card=score(d, compare, compare_ac, lab)),
                  human=dict(account=human['summary'], card=human_sc, account_id=human['id']),
                  drop2=dict(removed=best, account_id=drop['id'], summary=drop['summary'],
                             beats_random=drop['summary']['total'] > random['placebo_median']),
                  signal_baseline=signal_baseline(d, cfg, lab),
                  matched_signal_random=matched_signal_random(d, cfg, lab), cv=fit['cv'],
                  shuffled=[dict(seed=seed, full=r['fit']['metrics'], cv=r['cv']['summary']) for seed, r in zip(SEEDS, shuffled)],
                  anti_memorization=dict(true=cv_true, best_shuffle=cv_best,
                      passed=cv_true['bought'] >= cv_best['bought'] + 3 and cv_true['product'] > cv_best['product']))
    output('long', result)


def short_round():
    d = Data()
    lab = labels(d)
    cfg = read(REPORTS / (PREFIX + 'long.json'))['config']
    base = run_account(d, cfg)
    long_labels = [r for r in lab if r['side'] > 0]
    base_fidelity = score(d, cfg, base, long_labels)['groups']['all']
    candidates = [dict(line=50, weekly=True, market=True, trim_day=2),
                  dict(line=50, weekly=True, market=False, trim_day=2),
                  dict(line=21, weekly=True, market=False, trim_day=2),
                  dict(line=9, weekly=True, market=False, trim_day=2),
                  dict(line=50, weekly=False, market=False, trim_day=2)]
    reg = dict(round=8, long=cfg, candidates=candidates, protocol='short_v2')
    save(WORK / 'registrations/short_r8.json', reg)
    results = []
    for candidate in candidates:
        ac = run_account(d, cfg, candidate)
        so = run_account(d, cfg, candidate, only='short')
        random = []
        for seed in range(100):
            rp = run_account(d, cfg, candidate, only='short', placebo=142000 + seed)
            random.append(rp['summary']['total'])
        long_trades = [t for t in ac['trades'] if t['side'] > 0 and t['why'] != 'end']
        base_trades = [t for t in base['trades'] if t['why'] != 'end']
        short_trades = [t for t in ac['trades'] if t['side'] < 0 and t['why'] != 'end']
        def behavior(rows):
            return len(rows), np.mean([t['ret'] > 0 for t in rows]) if rows else 0., np.mean([t['days'] for t in rows]) if rows else 0.
        n, win, days = behavior(long_trades)
        bn, bw, bd = behavior(base_trades)
        # The protocol's bearish-session return uses only the prior-close equal-weight-index proxy.
        equal = np.array(d.meta['equal_index'])
        below = equal < lib.smooth(equal, 50)
        mask = below[d.start - 1:-1]
        def bear(account):
            a = np.r_[1., account['curve']]
            return float(np.prod((a[1:] / a[:-1])[mask]) - 1)
        failures = []
        if ac['summary']['overall']['win'] is None or ac['summary']['overall']['win'] > .35:
            failures.append('combined_win')
        if so['summary']['overall']['win'] is None or so['summary']['overall']['win'] > .35 \
                or so['summary']['overall']['closed'] < 30:
            failures.append('short_win_or_sample')
        long_fidelity = score(d, cfg, ac, long_labels, candidate)['groups']['all']
        if not preserves_replication(base_fidelity, long_fidelity):
            failures.append('long_fidelity_declined')
        if abs(n / max(1, bn) - 1) > .03 or abs(win - bw) > .01 or abs(days / max(bd, 1e-9) - 1) > .1:
            failures.append('long_behavior_changed')
        if any(t['days'] > 10 for t in short_trades):
            failures.append('short_hold')
        if len(short_trades) > len(base_trades) / 4:
            failures.append('short_count')
        if not (so['summary']['total'] > np.median(random) and np.mean(np.array(random) < so['summary']['total']) >= .9):
            failures.append('short_alpha')
        if ac['summary']['maxdd'] > base['summary']['maxdd'] + .02 or bear(ac) < bear(base):
            failures.append('backfire')
        results.append(dict(config=candidate, account=ac['summary'], account_id=ac['id'],
                            short_account=so['summary'], short_id=so['id'], random=random,
                            placebo_rank=float(np.mean(np.array(random) < so['summary']['total'])),
                            failures=failures, bear_combined=bear(ac), bear_long=bear(base),
                            card=score(d, cfg, ac, lab, candidate),
                            short_card=score(d, cfg, so, [r for r in lab if r['side'] < 0], candidate)))
        print('short', candidate['line'], candidate['market'], failures, flush=True)
    allowed = [r for r in results if not r['failures']]
    winner = max(allowed, key=lambda r: r['account']['total']) if allowed else None
    diagnostic = max(results, key=lambda r: r['short_card']['groups']['all']['product'])
    human = run_account(d, cfg, diagnostic['config'], human=[r for r in lab if r['side'] < 0])
    result = dict(round=8, adopted=winner, candidates=results, diagnostic=diagnostic,
                  human=dict(account=human['summary'], account_id=human['id'],
                             card=score(d, cfg, human, [r for r in lab if r['side'] < 0], diagnostic['config'], supplied=True)),
                  final_account_id=winner['account_id'] if winner else base['id'])
    output('short', result)


def verify():
    initial = read(WORK / 'initial_inputs.json')
    changed = []
    for relative, old in initial['metadata'].items():
        s = (ROOT / relative).stat()
        if [s.st_size, s.st_mtime_ns] != old:
            changed.append(relative)
    for relative, digest in initial['hashes'].items():
        if relative == 'studies/trader_replication/system.py':
            continue
        if sha(ROOT / relative) != digest:
            changed.append(relative)
    if changed:
        raise AssertionError(('protected inputs changed', changed[:10]))
    forbidden = {t.ticker for t in ledger.load(LEDGER)}
    forbidden |= {'US.' + s for s in forbidden}
    forbidden |= {t.entry_date for t in ledger.load(LEDGER) if t.entry_date}
    for path in (Path(__file__), ROOT / 'studies/trader_replication/tests/test_martin_continue_ie14.py'):
        constants = {n.value for n in ast.walk(ast.parse(path.read_text())) if isinstance(n, ast.Constant) and isinstance(n.value, str)}
        if constants & forbidden:
            raise AssertionError(('human literal in source', path.name, constants & forbidden))
    d = Data()
    lab = labels(d)
    for tag in ('true', *('shuffle_' + str(s) for s in SEEDS)):
        fit = read(REPORTS / (PREFIX + tag + '.json'))
        for h, fold in fit['cv']['folds'].items():
            data = lab if tag == 'true' else shuffle_labels(d, lab, int(tag.rsplit('_', 1)[1]))
            expected = sorted(r['id'] for r in training_rows(data, h))
            if fold['training_ids'] != expected:
                raise AssertionError('held-out labels entered training')
            search_result = read(WORK / 'searches' / (tag + '_' + h + '.json'))
            for row in search_result['rounds'][1:]:
                if len(row['candidates']) > 5:
                    raise AssertionError('candidate budget')
                for candidate in row['candidates']:
                    m = candidate['metrics']
                    if any(i not in expected for i in m['ids']):
                        raise AssertionError('held-out identity entered a candidate metric')
    output('verification', dict(protected_files=len(initial['metadata']), input_hashes=len(initial['hashes']) - 1,
                                 labels=len(lab), sides=dict(Counter(r['side'] for r in lab)),
                                 source_sha256=sha(__file__), plan_sha256=sha(PLAN), prereg_sha256=sha(PREREG),
                                 system_sha256=sha(ROOT / 'studies/trader_replication/system.py'),
                                 protected_unchanged=True, no_human_literals=True, folds_reselected=True))


def offline():
    def audit(event, args):
        if event in ('socket.connect', 'socket.bind', 'subprocess.Popen', 'os.system'):
            raise PermissionError('IE14 uses existing caches in one process')
        if event == 'open' and not isinstance(args[0], int):
            path, mode, flags = args
            if flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND):
                p = Path(os.fsdecode(path)).resolve()
                if not p.is_relative_to(WORK.resolve()) and not (p.parent == REPORTS and p.name.startswith(PREFIX)):
                    raise PermissionError('IE14 outputs must remain within the authorized paths')
    sys.addaudithook(audit)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=('prepare', 'search', 'long', 'short', 'verify'))
    parser.add_argument('--tag', default='true')
    args = parser.parse_args()
    offline()
    if args.stage == 'prepare':
        prepare()
    elif args.stage == 'search':
        run_search(args.tag)
    elif args.stage == 'long':
        finalize_long()
    elif args.stage == 'short':
        short_round()
    else:
        verify()
    print('RSS MiB', resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, flush=True)


if __name__ == '__main__':
    main()
