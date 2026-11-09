"""IE5: apply immutable numeric selectors offline and reuse the H4 account engine."""
from collections import Counter, defaultdict
from dataclasses import asdict, replace
from datetime import datetime, timezone
import argparse
import csv
import gc
import json
import os
from pathlib import Path
import resource
import sys
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from studies.trader_replication import ie_factor_library as lib
from studies.trader_replication import martin_continue_ie4 as ie4
from studies.trader_replication import martin_continue_ie_factors as prior
from studies.trader_replication import panels, system
from studies.trader_replication import martin_continue_du as du, martin_continue_ep as ep
from studies.trader_replication import martin_continue_hb as hb, martin_continue_hc as hc
from studies.trader_replication import martin_continue_hh as hh, martin_continue_hj as hj
from studies.trader_replication import martin_continue_hv as hv
from studies.trader_replication.martin_continue_ie_periods import distribution, file_sha
from studies.trader_replication.martin_strong_scan import HOLD, f1_rules, nl_rules
from studies.trader_replication.martin_strong import pct

ROOT, REPORTS = prior.ROOT, prior.REPORTS
WORK = REPORTS / 'ie5_work'
PREFIX = 'strong_continue_ie5_'
FROZEN = REPORTS / 'strong_continue_ie4_frozen.json'
EXPLANATIONS = REPORTS / (PREFIX + 'gate_explanations.json')
PLAN = ROOT / 'studies/martin_luk/notes/PLAN_IE5_CN.md'


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8'))


def output(name, value):
    prior.write_json(REPORTS / (PREFIX + name + '.json'), value)


def offline_guard():
    def allowed(path):
        p = Path(os.fsdecode(path)).resolve()
        return p.is_relative_to(WORK.resolve()) or (p.parent == REPORTS.resolve() and p.name.startswith(PREFIX))

    def audit(event, args):
        if event == 'open':
            path, _, flags = args
            if not isinstance(path, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND):
                if not allowed(path):
                    raise PermissionError('IE5 output boundary: ' + os.fsdecode(path))
        if event in ('socket.connect', 'socket.bind', 'os.system', 'subprocess.Popen'):
            raise PermissionError('IE5 is offline in one process')
        if event in ('os.remove', 'os.rename', 'os.rmdir', 'os.mkdir'):
            paths = args[:2] if event == 'os.rename' else args[:1]
            if any(not allowed(p) for p in paths):
                raise PermissionError('IE5 output boundary')
    sys.addaudithook(audit)


def models_and_specs():
    frozen = read_json(FROZEN)
    null = read_json(ie4.WORK / 'd1.leader_weekend.True.-1.json')['candidates']['G3']
    inventory = {prior.factor_name(s, t): (s, t) for s, t in prior.factor_specs()}
    names = list(dict.fromkeys(frozen['model']['features'] + null['model']['features']))
    return frozen, null, [inventory[name] for name in names]


def account_rules(d):
    cash = replace(nl_rules(d, 6), gross_cost=True, trail_next_open=True, no_rebuy_day=True)
    cash = replace(cash, intraday_kinds=tuple(sorted(set(cash.intraday_kinds) | {'n1', 'list'})))
    lever = f1_rules(d, 6, (1, 3))
    lever = replace(lever, intraday_kinds=tuple(lever.intraday_kinds) + ('n1', 'list'),
                    trail_next_open=True, add_next_open=True, no_rebuy_day=True, feedback_prior_close=True)
    return {'cash6': hv.without_partial(cash), 'lever': hv.without_partial(lever)}


def selected_orders(d, selections, window=panels.WINDOW):
    """Only selected signal-day closes enter the existing preopen order adapter."""
    ci = {str(c): j for j, c in enumerate(d.A['codes'])}
    book = [[] for _ in d.days]
    for day, codes in selections.items():
        t = d.di[day]
        for rank, code in enumerate(codes):
            j = ci[code]
            close = float(d.A['close'][t, j])
            if not np.isfinite(close) or close <= 0:
                raise ValueError('selected signal lacks valid close')
            book[t].append(((2., rank), j, 1, close, close * .975, 'list', None, None, None, .5))
    return hb.freeze_orders(d.days, d.A['codes'], book, d.A['close'], window=window)


def layout(meta):
    keys, slices, bycode = [], {}, defaultdict(list)
    di = {day: i for i, day in enumerate(meta['days'])}
    for day, codes in sorted(meta['scope'].items()):
        start = len(keys)
        for code in codes:
            bycode[code].append((di[day], len(keys)))
            keys.append((day, code))
        slices[day] = slice(start, len(keys))
    return keys, slices, bycode


def transform(raw, meta, slices, kind):
    p = np.full(raw.shape, .5, np.float32)
    for sl in slices.values():
        p[sl] = prior.percentile(raw[sl])
    if kind != 'delta5':
        return p
    di = {d: i for i, d in enumerate(meta['days'])}
    out = np.full_like(p, .5)
    for day, sl in slices.items():
        t = di[day]
        previous = meta['days'][t - 5] if t >= 5 else None
        old = np.full((sl.stop - sl.start, raw.shape[1]), .5, np.float32)
        if previous in slices:
            ps = slices[previous]
            lookup = {c: ps.start + k for k, c in enumerate(meta['scope'][previous])}
            for k, code in enumerate(meta['scope'][day]):
                if code in lookup:
                    old[k] = p[lookup[code]]
        out[sl] = prior.percentile(p[sl] - old)
    return out


def random_selection(pools, seed):
    rng = np.random.default_rng(seed)
    return {day: [codes[k] for k in rng.choice(len(codes), min(5, len(codes)), replace=False)]
            for day, codes in sorted(pools.items())}


def indicator_values(stock, family, n, wanted):
    """Evaluate requested independent branches with the original reductions."""
    if family == 'complexity' and wanted <= {'fractal', 'permutation', 'runs'}:
        from itertools import permutations
        c, x = stock.c, stock.lr
        valid = lib.roll((np.isfinite(c) & np.isfinite(x)).astype(float), n, 'sum') == n
        valid[:n] = False
        out = {key: np.full(len(c), np.nan) for key in wanted}
        if 'runs' in wanted:
            changes = np.r_[0., (np.sign(x[1:]) != np.sign(x[:-1])).astype(float)]
            count = lib.roll(changes, n - 1, 'sum')
            out['runs'][valid] = -count[valid].astype(np.int64) / n
        if 'fractal' in wanted:
            span = lib.roll(c, n, 'max') - lib.roll(c, n, 'min')
            path = lib.roll(np.r_[np.nan, np.abs(np.diff(c))], n - 1, 'sum')
            good = valid & (span > 0)
            out['fractal'][good] = -1 - np.log(path[good] / span[good]) / np.log(n)
        if 'permutation' in wanted and len(c) >= 3:
            weights = np.array([1, 3, 9])
            possible = np.sort(np.asarray(list(permutations(range(3)))) @ weights)
            keys = np.full(len(c), -1, int)
            triples = np.lib.stride_tricks.sliding_window_view(x, 3)
            keys[2:] = np.argsort(triples, axis=1, kind='stable') @ weights
            counts = np.column_stack([lib.roll((keys == k).astype(float), n - 2, 'sum') for k in possible])
            bits = 2 ** np.arange(len(possible))
            masks = ((counts > 0) * bits).sum(1)
            for mask in np.unique(masks[valid]):
                rows = np.flatnonzero(valid & (masks == mask))
                cols = np.flatnonzero(mask & bits)
                group = counts[np.ix_(rows, cols)]
                freq = group / group.sum(1, keepdims=True)
                out['permutation'][rows] = np.sum(freq * np.log(freq), 1) / np.log(6)
        return out
    if family == 'chips' and wanted <= {'cost', 'concentration'}:
        out = {}
        v, c, tp = stock.v, stock.c, stock.tp
        if 'cost' in wanted:
            from studies.trend_breakout.chips import cost_line
            turn = np.clip(lib.divide(v, 20 * lib.roll(v, n)), 0, 1)
            price = lib.divide(stock.t, v)
            price = np.where((price >= stock.l * .98) & (price <= stock.h * 1.02), price, tp)
            cost = cost_line(c[:, None], price[:, None], turn[:, None])[:, 0]
            out['cost'] = lib.divide(c, cost) - 1
        if 'concentration' in wanted:
            mean = lib.divide(lib.roll(v * tp, n, 'sum'), lib.roll(v, n, 'sum'))
            std = np.sqrt(np.maximum(0, lib.divide(lib.roll(v * tp ** 2, n, 'sum'),
                                                  lib.roll(v, n, 'sum')) - mean ** 2))
            out['concentration'] = -lib.divide(std, mean)
        return out
    if family != 'avwap':
        return stock.evaluate(family, n)
    length = len(stock.c)
    out = {key: np.full(length, np.nan) for key in wanted}
    if length < n:
        return out
    starts = np.arange(length - n + 1)
    window_v = np.lib.stride_tricks.sliding_window_view(stock.v, n)
    window_p = np.lib.stride_tricks.sliding_window_view(stock.tp, n)
    for key in wanted:
        if key == 'earnings':
            offset = stock.extras['earn_index'][n - 1:].astype(float) - starts
        elif key == 'breakout':
            breakout = stock.h >= lib.roll(lib.lag(stock.h), n, 'max')
            last = np.maximum.accumulate(np.where(breakout, np.arange(length), -1))
            offset = last[n - 1:].astype(float) - starts
        else:
            series = dict(high=stock.h, low=stock.l, volume=stock.v,
                          gap=lib.divide(stock.o, stock.pc) - 1)[key]
            offset = lib.roll(series, n, 'argmin' if key == 'low' else 'argmax')[n - 1:]
        valid = np.isfinite(offset) & (offset >= 0) & (offset < n)
        for anchor in np.unique(offset[valid]).astype(int):
            rows = np.flatnonzero(valid & (offset == anchor))
            w, p = window_v[rows, anchor:], window_p[rows, anchor:]
            good = np.isfinite(w + p).all(1)
            rows, w, p = rows[good], w[good], p[good]
            target = rows + n - 1
            # Equal-length contiguous rows retain exactly the reference's
            # per-window multiplication and numpy sum order, without padding.
            out[key][target] = lib.divide(stock.c[target], lib.divide(np.sum(w * p, 1), np.sum(w, 1))) - 1
    return out


def prepare():
    path = WORK / 'prepared.json'
    if path.exists():
        print('reuse completed preparation', flush=True)
        return
    from studies import trader_data
    frozen, null, specs = models_and_specs()
    ds = trader_data.dataset('us', mode='frozen', version='trader-data-v1')
    timeline = read_json(prior.ie.TIMELINE)
    if ds.digest() != timeline['dataset_digest']:
        raise ValueError('frozen dataset differs')
    entries = sorted(timeline['entries'], key=lambda r: (r['entry_date'], r['id']))
    expected_active = {day: [r[0] for r in item['rows']] for day, item in timeline['nightly_candidates'].items()}
    del timeline
    periods = read_json(prior.ie.PERIODS)
    missing, window_only = periods['missing_data'], periods['window_only']
    del periods
    d = du.make_data(ds)
    fields, mask, unused = du.compute_fields(d)
    del unused
    gc.collect()
    codes, days = list(map(str, d.A['codes'])), d.days
    ci = {c: j for j, c in enumerate(codes)}
    print('panel and original support', d.c.shape, days[-1], flush=True)
    d.A['volume'] = np.full(d.c.shape, np.nan, np.float32)
    d.A['raw_close'] = np.full(d.c.shape, np.nan, np.float32)
    for code, day, row in ds.rows():
        if code in ci and day in d.di:
            t, j = d.di[day], ci[code]
            d.A['raw_close'][t, j] = row[3]
            if np.isfinite(d.c[t, j]) and d.c[t, j] > 0:
                d.A['volume'][t, j] = row[4] * row[3] / d.c[t, j]
    events, eligible, _ = ep.causal_inputs(ds, d, codes)
    fast = np.empty(events.shape, np.float32)
    for start in range(0, len(codes), 64):
        sl = slice(start, start + 64)
        fast[:, sl] = du._ROLL_MEAN(events[:, sl].astype(np.float32), 250)
    fields['fast250'] = fast
    del events, fast
    fields['peer_pot'], pot = ep.peer_potential(d, eligible)
    del eligible
    fields.update(hj.coil_fields_chunked(d))
    baseline, _ = hj.freeze(d, fields, mask, 'H4')
    expected = read_json(REPORTS / 'strong_continue_ia_inputs.json')['orders']
    if baseline != expected:
        raise AssertionError('IA original H4 orders differ')
    prior.write_json(WORK / 'baseline_orders.json', baseline)
    del expected, baseline
    rules = account_rules(d)
    prior.write_json(WORK / 'account_rules.json', {k: asdict(v) for k, v in rules.items()})
    for name in ('open', 'high', 'low', 'close', 'codes', 'days'):
        np.save(WORK / 'panel' / (name + '.npy'), d.A[name])
    for label, rule in rules.items():
        for name, value in d.base.ema_inputs(d.A, d.pool, rule).items():
            np.save(WORK / 'panel' / (label + '.' + name + '.npy'), value)
    first = min(e['date'] for r in entries for e in r['systems']['h4'])
    begin = d.di[first] - 5
    scope = {}
    for t in range(begin, len(days)):
        a, b = prior.ie.completed_week(days, t)
        with np.errstate(all='ignore'):
            weekly_dollar = d.c[b] * d.A['volume'][a:b + 1].sum(0)
            gain = d.c[b] / d.c[b - 21] - 1
        ix = np.flatnonzero((weekly_dollar > 3e8) & np.isfinite(gain) & np.isfinite(d.c[t]) & (d.c[t] > 0))
        scope[days[t]] = sorted(codes[j] for j in ix)
    differences = []
    for day, original in expected_active.items():
        current = {codes[j] for j in np.flatnonzero(mask[d.di[day]])}
        if current != set(original):
            differences.append(day)
    if differences:
        raise AssertionError(('active membership differs', differences[:5]))
    del expected_active
    groups = np.full((len(days), len(codes), 6), np.nan, np.float32)
    for t in range(1, len(days)):
        for k, group in enumerate(HOLD['H4']):
            value = np.zeros(len(codes), np.float32)
            for field in group:
                value += np.nan_to_num(pct(fields[field][t - 1:t], mask[t:t + 1])[0] - .5) / len(group)
            groups[t, mask[t], k] = value[mask[t]] + .5
    peer_g5 = np.full(d.c.shape, np.nan, np.float32)
    rr = np.empty(d.c.shape, np.float32)
    for t in range(len(days)):
        r = d.c[t] / d.c[t - 1] - 1 if t else np.full(len(codes), np.nan)
        rr[t] = np.nan_to_num(r - np.nanmedian(np.where(d.rk[t] < 300, r, np.nan)))
    graphs, near, names = {}, None, None
    for t in range(60, len(days)):
        cur = np.flatnonzero(d.rk[t] < 300)
        if len(cur) < 30:
            continue
        if near is None or t % 5 == 0:
            w = rr[t - 39:t + 1][:, cur]
            w = w - w.mean(0)
            sd = w.std(0) + 1e-6
            near = (w.T @ w / len(w) / np.outer(sd, sd)) >= .5
            names = cur
            graphs[t] = (names.copy(), near.copy())
        g = d.c[t, names] / d.c[t - 5, names] - 1
        peer_g5[t, names] = (near * np.where(np.isfinite(g), g, 0)).sum(1) / near.sum(1)
    del rr
    wanted = sorted({c for v in scope.values() for c in v})
    earnings = defaultdict(list)
    with (ROOT / 'data/trader-options-v1/us/earnings.csv').open() as f:
        for row in csv.DictReader(f):
            if row['earnings_date'][:10] <= days[-1]:
                earnings[row['security']].append(row)
    with patch.object(prior, 'CUTOFF', days[-1]):
        for k, code in enumerate(wanted):
            j = ci[code]
            age, ei = prior.earnings_arrays(days, earnings[code])
            extras = dict(pot=pot[:, j], peer_g5=peer_g5[:, j], peer_rank=fields['peer_rank'][:, j],
                          earn_days=age, earn_index=ei)
            extras.update({f'h4_{name}': groups[:, j, q] for q, name in enumerate(
                ('activity', 'momentum', 'history', 'stack', 'peers', 'coil'))})
            extras.update(prior.option_arrays(code, days))
            arrays = {k: d.A[v][:, j] for k, v in dict(o='open', h='high', l='low', c='close', v='volume',
                                                      t='turnover', raw_c='raw_close').items()}
            prior.save_npz(WORK / 'stocks' / (code + '.npz'), **arrays,
                           **{'extra_' + k: v for k, v in extras.items()})
            if k % 300 == 0:
                print('prepared stocks', k, '/', len(wanted), flush=True)
    del groups, peer_g5, fields, mask
    gc.collect()
    group_specs = [s for s, _ in specs if s.family == 'group']
    for n in sorted({s.parameter for s in group_specs}):
        group = np.lib.format.open_memmap(WORK / 'group_scratch.npy', mode='w+', dtype=np.float32,
                                          shape=(len(days), len(codes), 8))
        group[:] = np.nan
        near = names = None
        gain = np.full(d.c.shape, np.nan, np.float32)
        gain[n:] = d.c[n:] / d.c[:-n] - 1
        rv = np.full(d.c.shape, np.nan, np.float32)
        pp = rv.copy()
        for start in range(0, len(codes), 64):
            sl = slice(start, start + 64)
            rv[:, sl] = d.A['volume'][:, sl] / du._ROLL_MEAN(d.A['volume'][:, sl], n)
            pp[:, sl] = du._ROLL_MEAN(pot[:, sl].astype(float), n)
        for t in range(60, len(days)):
            if t in graphs:
                names, near = graphs[t]
            if names is None:
                continue
            g = gain[t, names]
            weight = near * np.isfinite(g)[None, :]
            den = weight.sum(1)
            mean = lib.divide(weight @ np.nan_to_num(g), den)
            second = lib.divide(weight @ np.nan_to_num(g * g), den)
            values = [mean, g - mean, lib.divide((weight & (g[None, :] > 0)).sum(1), den),
                      lib.divide(near @ np.nan_to_num(rv[t, names]), (near * np.isfinite(rv[t, names])[None, :]).sum(1)),
                      lib.divide(near @ np.nan_to_num(pp[t, names]), (near * np.isfinite(pp[t, names])[None, :]).sum(1)),
                      -np.sqrt(np.maximum(0, second - mean ** 2)),
                      lib.divide(((g[None, :] <= g[:, None]) & weight).sum(1), den)]
            for q, value in enumerate(values):
                group[t, names, q] = value
            cur = np.flatnonzero(d.rk[t] < 300)
            gg = gain[t, cur]
            good = np.isfinite(gg)
            if good.any():
                group[t, :, 7] = np.mean(gg[good] > 0)
        keys = ('peer_return', 'peer_excess', 'peer_positive', 'peer_volume', 'peer_potent',
                'peer_dispersion', 'peer_rank', 'breadth')
        for code in wanted:
            prior.save_npz(WORK / 'group' / (code + f'.{n}.npz'),
                           **{key: group[:, ci[code], q] for q, key in enumerate(keys)})
        group.flush()
        del group, gain, rv, pp
        gc.collect()
        (WORK / 'group_scratch.npy').unlink()
        print('group window complete', n, flush=True)
    benchmark_paths = [p for p in read_json(prior.WORK / 'prepared.json')['source_sha256']
                       if Path(p).parent == Path('data/martin-luk-benchmarks-v1')]
    if len(benchmark_paths) != 1:
        raise ValueError('expected the single frozen benchmark configuration')
    benchmark = Path(benchmark_paths[0]).stem.split('.', 1)[1]
    np.save(WORK / 'qqq.npy', du.required_fields.__globals__['bench'](days, benchmark))
    meta = dict(days=days, codes=wanted, scope=scope, entries=entries, missing=missing,
                window_only=window_only, dataset_digest=ds.digest(), first_signal=first,
                prepared_last=days[-1], baseline_orders_verified=True,
                peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    prior.write_json(path, meta)
    print('preparation complete', len(wanted), 'stocks', len(scope), 'nights', flush=True)


def calculate():
    meta = read_json(WORK / 'prepared.json')
    keys, slices, bycode = layout(meta)
    frozen, null, specs = models_and_specs()
    qqq = np.load(WORK / 'qqq.npy')
    raw_path = WORK / 'raw.npy'
    if not (WORK / 'raw_complete.json').exists():
        raw = np.lib.format.open_memmap(raw_path, mode='w+', dtype=np.float32,
                                        shape=(len(keys), len(frozen['raw_feature_names'])))
        raw[:] = np.nan
        for k, (code, positions) in enumerate(bycode.items()):
            with np.load(WORK / 'stocks' / (code + '.npz')) as z:
                arrays = {n: z[n] for n in z.files if not n.startswith('extra_')}
                extras = {n[6:]: z[n] for n in z.files if n.startswith('extra_')}
            values = ie4.raw_factors(arrays, meta['days'], qqq, extras)
            ts, rows = map(np.asarray, zip(*positions))
            raw[rows] = np.column_stack([values[n][ts] for n in frozen['raw_feature_names']])
            if k % 300 == 0:
                print('raw factors', k, '/', len(bycode), flush=True)
        raw.flush()
        del raw
        prior.write_json(WORK / 'raw_complete.json', dict(rows=len(keys)))
    for family in dict.fromkeys(s.family for s, _ in specs):
        done = WORK / ('factor_' + family + '.json')
        if done.exists():
            continue
        subset = list(dict.fromkeys(s for s, _ in specs if s.family == family))
        raw = np.lib.format.open_memmap(WORK / 'factor_raw.npy', mode='w+', dtype=np.float32,
                                        shape=(len(keys), len(subset)))
        raw[:] = np.nan
        hist = np.lib.format.open_memmap(WORK / 'factor_hist.npy', mode='w+', dtype=np.float32, shape=raw.shape)
        hist[:] = np.nan
        needs_history = any(t == 'history250' and s.family == family for s, t in specs)
        for k, (code, positions) in enumerate(bycode.items()):
            with np.load(WORK / 'stocks' / (code + '.npz')) as z:
                arrays = {n: z[n] for n in z.files if not n.startswith('extra_')}
                extras = {n[6:]: z[n] for n in z.files if n.startswith('extra_')}
            if family == 'group':
                for n in {s.parameter for s in subset}:
                    with np.load(WORK / 'group' / (code + f'.{n}.npz')) as z:
                        extras.update({f'group.{key}.{n}': z[key] for key in z.files})
            stock = lib.Stock(arrays, meta['days'], qqq, extras)
            values = {n: indicator_values(stock, family, n, {s.metric for s in subset if s.parameter == n})
                      for n in {s.parameter for s in subset}}
            x = np.column_stack([values[s.parameter][s.metric] for s in subset])
            ts, rows = map(np.asarray, zip(*positions))
            raw[rows] = x[ts]
            if needs_history:
                hist[rows] = lib.history_rank(x, ts)
            stock.ema.cache_clear()
            stock.f_hilbert.cache_clear()
            if k % 400 == 0:
                print('family', family, k, '/', len(bycode), flush=True)
        for kind in lib.TRANSFORMS:
            wanted = [(s, t) for s, t in specs if s.family == family and t == kind]
            if not wanted:
                continue
            value = transform(hist if kind == 'history250' else raw, meta, slices, kind)
            for s, t in wanted:
                np.save(WORK / 'design' / (prior.factor_name(s, t) + '.npy'), value[:, subset.index(s)])
            del value
        raw.flush()
        hist.flush()
        del raw, hist, stock, arrays, extras, values, x
        gc.collect()
        (WORK / 'factor_raw.npy').unlink()
        (WORK / 'factor_hist.npy').unlink()
        prior.write_json(done, dict(features=[prior.factor_name(s, t) for s, t in specs if s.family == family]))
        print('family complete', family, flush=True)
    for label, model in (('frozen', frozen['model']), ('shuffle_fit', null['model'])):
        score = np.zeros(len(keys), np.float64)
        for name, weight in zip(model['features'], model['weights']):
            column = np.load(WORK / 'design' / (name + '.npy'), mmap_mode='r')
            score += (column - np.float32(.5)).astype(float) * weight
        np.save(WORK / (label + '_scores.npy'), score)
    prior.write_json(WORK / 'calculated.json', dict(rows=len(keys), features=len(specs),
                     peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss))
    print('numeric factors complete', len(keys), flush=True)


def night_ranks(meta, slices, mask, scores):
    result = np.full(len(scores), prior.SENTINEL, np.int32)
    for sl in slices.values():
        rows = np.flatnonzero(mask[sl]) + sl.start
        order = rows[np.argsort(-scores[rows], kind='stable')]
        result[order] = np.arange(1, len(order) + 1)
    return result


def coverage(rows, year, tier='all', include_missing=False):
    sample = [r for r in rows if (r['entry_date'][:4] in ('2024', '2025') if year == '2024_2025'
                                 else r['entry_date'].startswith(year))]
    if tier == 'primary':
        sample = [r for r in sample if r.get('target', {}).get('tier') == 'primary']
    elif not include_missing:
        sample = [r for r in sample if not r.get('missing_data')]
    return dict(n=len(sample), hits={str(k): sum(r['best_rank'] <= k for r in sample) for k in prior.TOPS},
                reasons=dict(Counter(r['reason'] for r in sample if r['best_rank'] > 5)),
                unique_n=len({(r['code'], r['entry_date']) for r in sample}),
                unique_top5=len({(r['code'], r['entry_date']) for r in sample if r['best_rank'] <= 5}))


def coverage_table(rows):
    return {year: dict(primary=coverage(rows, year, 'primary'), located_all=coverage(rows, year),
                       disclosed_all=coverage(rows, year, include_missing=True))
            for year in ('2024_2025', '2024', '2025', '2026')}


def evaluate_rows(meta, keys, slices, raw, gates, scores, shuffle=False):
    mask = ie4.apply_gates(raw, dict(gates=gates))
    rank = night_ranks(meta, slices, mask, scores)
    index = {key: i for i, key in enumerate(keys)}
    first = np.full(len(keys), -1, np.int16)
    for order, gate in enumerate(gates):
        passed = ie4.apply_gates(raw, dict(gates=[gate]))
        first[(first < 0) & ~passed] = order
    mapping = {}
    if shuffle:
        # Preserve the old training-label permutation; exam labels use a new
        # stream with the same registered seed, never changing training labels.
        for is_training in (True, False):
            sample = [r for r in meta['entries'] if (r['entry_date'] <= prior.CUTOFF) == is_training]
            rng = np.random.default_rng(20261103)
            evaluation = sorted({e['date'] for r in sample for e in r['systems']['h4']})
            for day in evaluation:
                names = meta['scope'][day]
                mapping[day] = dict(zip(names, rng.permutation(names).tolist()))
            for entry in sample:
                for event in entry['systems']['h4']:
                    day, code = event['date'], entry['code']
                    names = meta['scope'][day]
                    if code not in mapping[day] and names:
                        mapping[day][code] = names[int(rng.integers(len(names)))]
    rows = []
    for entry in meta['entries']:
        events = []
        for event in entry['systems']['h4']:
            day, code = event['date'], entry['code']
            if shuffle:
                code = mapping[day].get(code)
            q = index.get((day, code))
            row = dict(date=day, evaluated_code=code, in_scope=q is not None, rank=None, first_gate=None)
            if q is not None:
                if mask[q]:
                    row['rank'] = int(rank[q])
                else:
                    g = gates[first[q]]
                    row['first_gate'] = dict(order=int(first[q]) + 1, name=g['name'],
                                             value=float(raw[q, g['feature']]), lower=g['lower'], upper=g['upper'])
            events.append(row)
        best = min((e['rank'] for e in events if e['rank'] is not None), default=prior.SENTINEL)
        reason = ('hit' if best <= 5 else 'rank_below_top5' if best < prior.SENTINEL else
                  'gated' if any(e['in_scope'] for e in events) else 'outside_scope')
        rows.append({k: entry[k] for k in ('id', 'code', 'entry_date', 'setup', 'precision', 'target')} |
                    dict(best_rank=int(best), reason=reason, nights=events))
    for entry in meta['missing']:
        rows.append({k: entry[k] for k in ('id', 'code', 'entry_date', 'setup', 'precision')} |
                    dict(best_rank=prior.SENTINEL, reason='missing_data', missing_data=entry['reason'], nights=[]))
    return rows, mask, rank


def width_summary(meta, slices, mask):
    values = {day: int(mask[sl].sum()) for day, sl in slices.items() if day >= meta['first_signal']}
    evaluation = {e['date'] for r in meta['entries'] for e in r['systems']['h4']}
    return {year: {label: dict(distribution=distribution([v for d, v in values.items()
                                  if d.startswith(year) and (label == 'all_nights' or d in evaluation)]),
                              empty=sum(v == 0 for d, v in values.items()
                                  if d.startswith(year) and (label == 'all_nights' or d in evaluation)))
                   for label in ('all_nights', 'label_nights')}
            for year in ('2024', '2025', '2026')} | dict(daily=values)


def selections_from_rank(meta, keys, slices, rank, mask, top=5):
    selected, pools = {}, {}
    for day, sl in slices.items():
        if day < meta['first_signal']:
            continue
        rows = np.flatnonzero(mask[sl]) + sl.start
        pools[day] = [keys[i][1] for i in rows]
        chosen = rows[rank[rows] <= top]
        selected[day] = [keys[i][1] for i in chosen[np.argsort(rank[chosen])]]
    return selected, pools


def exam():
    target = REPORTS / (PREFIX + 'exam.json')
    if target.exists():
        print('2026 exam is already final; reading without rescoring', flush=True)
        return
    meta = read_json(WORK / 'prepared.json')
    keys, slices, _ = layout(meta)
    frozen, null, specs = models_and_specs()
    raw = np.load(WORK / 'raw.npy', mmap_mode='r')
    score = np.load(WORK / 'frozen_scores.npy', mmap_mode='r')
    # Check the old fit on its exact old nights before opening the exam result.
    old_meta = ie4.load_meta()
    old_design = ie4.Design(old_meta, frozen['scope'])
    old_score = np.load(ie4.WORK / 'd1.leader_weekend.False.G3.scores.npy')
    lookup = {k: i for i, k in enumerate(keys)}
    selected_rows = np.array([lookup[key] for key in old_design.keys])
    old_raw = np.load(ie4.WORK / (frozen['scope'] + '.raw.npy'), mmap_mode='r')
    old_mask = ie4.apply_gates(old_raw, dict(gates=frozen['gates']))
    old_design.mask = old_mask
    expected = old_design.best(old_score, range(len(old_meta['entries']))).tolist()
    actual_mask = ie4.apply_gates(raw[selected_rows], dict(gates=frozen['gates']))
    old_design.mask = actual_mask
    actual = old_design.best(np.asarray(score[selected_rows]), range(len(old_meta['entries']))).tolist()
    replay = dict(expected_ranks=expected, actual_ranks=actual,
                  max_score_difference=float(np.max(np.abs(score[selected_rows] - old_score))),
                  gate_membership_differences=int(np.count_nonzero(actual_mask != old_mask)))
    output('training_replay', replay)
    if actual != expected:
        raise AssertionError('frozen training rankings differ before exam')
    prior.write_json(WORK / 'exam_started.json', dict(frozen_sha256=file_sha(FROZEN),
                     started_utc=datetime.now(timezone.utc).isoformat(), policy='immutable; no retraining'))
    rows, mask, ranks = evaluate_rows(meta, keys, slices, raw, frozen['gates'], score)
    shuffled, _, _ = evaluate_rows(meta, keys, slices, raw, frozen['gates'], score, shuffle=True)
    null_rows, null_mask, _ = evaluate_rows(meta, keys, slices, raw, null['gate']['gates'],
                                          np.load(WORK / 'shuffle_fit_scores.npy', mmap_mode='r'), shuffle=True)
    selected, pools = selections_from_rank(meta, keys, slices, ranks, mask)
    result = dict(frozen_sha256=file_sha(FROZEN), task_sha256=file_sha(PLAN), final_exam=True,
                  no_refit=True, cutoff=meta['prepared_last'], dataset_digest=meta['dataset_digest'],
                  coverage=coverage_table(rows), rows=rows, widths=width_summary(meta, slices, mask),
                  shuffled_labels=dict(coverage=coverage_table(shuffled), rows=shuffled,
                                       note='冻结原版，标签在完整原范围内同日置换'),
                  shuffled_fit=dict(coverage=coverage_table(null_rows), rows=null_rows,
                                    widths=width_summary(meta, slices, null_mask),
                                    note='第四段已在2024–25打乱标签训练的G3；本次不重训'),
                  training_replay=replay, window_only=meta['window_only'])
    output('exam', result)
    prior.write_json(WORK / 'selections_frozen.json', selected)
    prior.write_json(WORK / 'pools_frozen.json', pools)
    np.save(WORK / 'frozen_ranks.npy', ranks)
    print('FINAL 2026 EXAM', result['coverage']['2026'], flush=True)


def ablations():
    if (REPORTS / (PREFIX + 'ablations.json')).exists():
        return
    meta = read_json(WORK / 'prepared.json')
    keys, slices, _ = layout(meta)
    frozen = read_json(FROZEN)
    raw = np.load(WORK / 'raw.npy', mmap_mode='r')
    score = np.load(WORK / 'frozen_scores.npy', mmap_mode='r')
    explanations = read_json(EXPLANATIONS)['gates']
    variants = {}
    for label, categories in (('class1', (1,)), ('class12', (1, 2))):
        gates = [g for g, e in zip(frozen['gates'], explanations) if e['category'] in categories]
        rows, mask, rank = evaluate_rows(meta, keys, slices, raw, gates, score)
        selected, _ = selections_from_rank(meta, keys, slices, rank, mask)
        prior.write_json(WORK / ('selections_' + label + '.json'), selected)
        variants[label] = dict(gates=len(gates), coverage=coverage_table(rows),
                               rows=rows, widths=width_summary(meta, slices, mask),
                               evaluation_2026='描述参考，不用于选择；原版考试结果保持不变')
    # Leave one out on training rows only. Do not even rank 2026 in this loop.
    train_slices = {day: sl for day, sl in slices.items() if day <= prior.CUTOFF}
    original = np.load(WORK / 'frozen_ranks.npy')
    index = {key: i for i, key in enumerate(keys)}
    training = [r for r in meta['entries'] if r['entry_date'][:4] in ('2024', '2025')]
    base_hit = {}
    for r in training:
        base_hit[r['id']] = any(original[index.get((e['date'], r['code']), len(original))] <= 5
                                for e in r['systems']['h4'] if (e['date'], r['code']) in index)
    removed = []
    for order, gate in enumerate(frozen['gates']):
        gates = frozen['gates'][:order] + frozen['gates'][order + 1:]
        mask = ie4.apply_gates(raw, dict(gates=gates))
        ranks = night_ranks(meta, train_slices, mask, score)
        hits = {r['id']: any(ranks[index[(e['date'], r['code'])]] <= 5
                            for e in r['systems']['h4'] if (e['date'], r['code']) in index) for r in training}
        primary = {r['id'] for r in training if r['target']['tier'] == 'primary'}
        lost = [i for i in hits if base_hit[i] and not hits[i]]
        gained = [i for i in hits if not base_hit[i] and hits[i]]
        widths = [int(mask[sl].sum()) for day, sl in train_slices.items() if day >= meta['first_signal']]
        removed.append(dict(order=order + 1, name=gate['name'],
                            primary_top5=sum(v for i, v in hits.items() if i in primary),
                            all_top5=sum(hits.values()),
                            primary_delta=sum(hits[i] - base_hit[i] for i in primary),
                            lost_ids=lost, gained_ids=gained, coverage_redundant=not lost and not gained,
                            pool_width=distribution(widths)))
    output('ablations', dict(variants=variants, leave_one_out=removed,
                            redundant_definition='只指样本内逐笔前5覆盖不变，不表示账户或未来冗余'))
    print('gate ablations complete', flush=True)


def annual_statistics(curve, dates, trades):
    years = sorted({str(d)[:4] for d in dates})
    out = {}
    for year in years:
        ix = np.flatnonzero(np.char.startswith(np.asarray(dates, str), year))
        base = float(curve[ix[0] - 1]) if ix[0] else 1.
        values = np.r_[base, np.asarray(curve)[ix]]
        sample = [t for t in trades if t['entry'].startswith(year)]
        closed = [t for t in sample if t['why'] != 'end']
        wins = [t['ret'] for t in closed if t['ret'] > 0]
        losses = [t['ret'] for t in closed if t['ret'] <= 0]
        aw = float(np.mean(wins)) if wins else None
        al = float(np.mean(losses)) if losses else None
        out[year] = dict(return_=float(values[-1] / base - 1),
                         maxdd=float(np.max(1 - values / np.maximum.accumulate(values))),
                         entries=len(sample), closed=len(closed), open_at_end=len(sample) - len(closed),
                         win=len(wins) / len(closed) if closed else None, avg_win=aw, avg_loss=al,
                         payoff=aw / -al if aw is not None and al is not None and al < 0 else None,
                         mean_hold_days=float(np.mean([t['days'] for t in closed])) if closed else None)
        out[year]['return'] = out[year].pop('return_')
        wins_invested = [t.get('ret_invested', t['ret']) for t in closed if t['ret'] > 0]
        losses_invested = [t.get('ret_invested', t['ret']) for t in closed if t['ret'] <= 0]
        wi = float(np.mean(wins_invested)) if wins_invested else None
        li = float(np.mean(losses_invested)) if losses_invested else None
        out[year].update(avg_win_invested=wi, avg_loss_invested=li,
                         payoff_invested=wi / -li if wi is not None and li is not None and li < 0 else None,
                         mean_winner_days=float(np.mean([t['days'] for t in closed if t['ret'] > 0])) if wins else None,
                         mean_loser_days=float(np.mean([t['days'] for t in closed if t['ret'] <= 0])) if losses else None)
    return out


def fill_fidelity(trades, meta):
    di = {day: i for i, day in enumerate(meta['days'])}
    rows = []
    for entry in meta['entries']:
        code, day = entry['code'], entry['entry_date']
        signal_days = [e['date'] for e in entry['systems']['h4']]
        execution_days = {meta['days'][di[s] + 1] for s in signal_days if di[s] + 1 < len(meta['days'])}
        relevant = [t for t in trades if t['code'] == code and t['side'] > 0]
        matched = [t for t in relevant if t['entry'] in execution_days]
        rows.append(dict(id=entry['id'], code=code, entry_date=day, primary=entry['target']['tier'] == 'primary',
                         bought=bool(matched), same_day=any(t['entry'] == day for t in relevant),
                         held_on_day=any(t['entry'] <= day <= t['exit'] for t in relevant),
                         fill_days=sorted({t['entry'] for t in matched})))
    annual = {}
    for year in ('2024', '2025', '2026'):
        sample = [r for r in rows if r['entry_date'].startswith(year)]
        primary = [r for r in sample if r['primary']]
        annual[year] = dict(n=len(sample), primary_n=len(primary), bought=sum(r['bought'] for r in sample),
                             primary_bought=sum(r['bought'] for r in primary),
                             same_day=sum(r['same_day'] for r in sample), held_on_day=sum(r['held_on_day'] for r in sample),
                             unique_bought=len({(r['code'], r['entry_date']) for r in sample if r['bought']}))
    return dict(annual=annual, rows=rows)


def load_account_inputs():
    a = {name: np.load(WORK / 'panel' / (name + '.npy'), mmap_mode='r')
         for name in ('open', 'high', 'low', 'close', 'codes', 'days')}
    days = list(map(str, a['days']))
    d = SimpleNamespace(A=a, days=days, di={day: i for i, day in enumerate(days)})
    px = dict(open=a['open'], high=a['high'], low=a['low'], close=a['close'], dates=a['days'], codes=a['codes'])
    rules = {}
    for label, record in read_json(WORK / 'account_rules.json').items():
        for key, value in record.items():
            if isinstance(getattr(system.Rules(), key), tuple) and isinstance(value, list):
                record[key] = tuple(value)
        for overrides in record['management_by_kind'].values():
            for name in ('add_levels', 'trims'):
                if name in overrides:
                    overrides[name] = tuple(overrides[name])
        rules[label] = system.Rules(**record)
    ema = {label: {p.name[len(label) + 1:-4]: np.load(p, mmap_mode='r')
                   for p in (WORK / 'panel').glob(label + '.*.npy')} for label in rules}
    return d, px, rules, ema


def run_account(d, px, ema, rules, orders, meta, detail=True):
    book, _, _ = hc.make_books(d, orders, hh.observations(d, orders), True)
    track = {}
    curve, dates, trades = system.simulate(px, ema, rules, book, *panels.WINDOW, audit=True, track=track,
                                           preopen=True, preopen_fill_stop_pct_by_kind={'n1': .025, 'list': .025},
                                           preopen_fill_stop_hit=True)
    if any(t['kind'] not in ('n1', 'list') or t['side'] != 1 for t in trades):
        raise AssertionError('unexpected execution kind or side')
    for t in trades:
        if abs(t['stop'] - .975 * t['fill']) > 1e-9:
            raise AssertionError('fill relative protection differs')
        if any(e['action'].startswith('trim') for e in t['executions']):
            raise AssertionError('partial exit present')
    for day in track['preopen_plans']:
        for row in day['orders']:
            if row['type'] == 'entry' and row['status'] == 'submitted':
                if row['shares'] * row['planned_loss_per_share'] > row['risk_fraction'] * day['equity'] + 1e-10:
                    raise AssertionError('prior risk reservation exceeded')
            if rules.gross_cost and row.get('cash_after', 0) < -1e-10:
                raise AssertionError('cash account borrowed')
    if rules.max_open and max(track['open']) > rules.max_open:
        raise AssertionError('position cap exceeded')
    values = np.r_[1., curve]
    result = dict(total=float(curve[-1] - 1), maxdd=float(np.max(1 - values / np.maximum.accumulate(values))),
                  annual=annual_statistics(curve, dates, trades), fidelity=fill_fidelity(trades, meta),
                  max_close_positions=max(track['open']), max_close_gross=float(max(track['gross'])),
                  margin_paid=float(track['margin']), trades_digest=hb.sha_bytes(trades))
    if detail:
        result.update(curve=curve.tolist(), dates=list(map(str, dates)), trades=trades,
                      order_counts={year: len([r for r in orders if r['day'].startswith(year)])
                                    for year in ('2024', '2025', '2026')})
        counts = {}
        for year in ('2024', '2025', '2026'):
            rows = [r for day in track['preopen_plans'] if day['day'].startswith(year)
                    for r in day['orders'] if r['type'] == 'entry']
            counts[year] = dict(status=dict(Counter(r['status'] for r in rows)),
                                execution=dict(Counter(r.get('execution', 'not_attempted') for r in rows)))
        result['order_disposition'] = counts
    else:
        result['fidelity'] = result['fidelity']['annual']
    return result


def accounts():
    meta = read_json(WORK / 'prepared.json')
    d, px, rules, ema = load_account_inputs()
    for variant in ('baseline', 'frozen', 'class1', 'class12'):
        orders = (read_json(WORK / 'baseline_orders.json') if variant == 'baseline' else
                  selected_orders(d, read_json(WORK / ('selections_' + variant + '.json'))))
        for label, rule in rules.items():
            target = REPORTS / (PREFIX + 'account_' + variant + '_' + label + '.json')
            if target.exists():
                continue
            value = run_account(d, px, ema[label], rule, orders, meta)
            if variant == 'baseline':
                source = read_json(REPORTS / ('strong_continue_id_inputs.json' if label == 'lever'
                                             else 'strong_continue_ia_inputs.json'))
                reference = source['reference'] if label == 'lever' else source['references']['cash6:hit']
                if value['trades_digest'] != reference['trades_digest']:
                    raise AssertionError('original H4 account differs from IA/ID')
                value['original_baseline_verified'] = True
                del source
            prior.write_json(target, value)
            print('account', variant, label, {y: (v['entries'], round(v['return'], 4))
                                             for y, v in value['annual'].items()}, flush=True)
            del value
            gc.collect()
    pools = read_json(WORK / 'pools_frozen.json')
    for seed in range(1, 31):
        selected = random_selection(pools, seed)
        orders = selected_orders(d, selected)
        for label, rule in rules.items():
            target = WORK / f'random_{seed}_{label}.json'
            if target.exists():
                continue
            value = run_account(d, px, ema[label], rule, orders, meta, detail=False)
            value['seed'] = seed
            value['selection_digest'] = hb.sha_bytes(selected)
            prior.write_json(target, value)
            print('random', seed, label, round(value['total'], 4), flush=True)
            del value
            gc.collect()
    draws = {label: [read_json(WORK / f'random_{seed}_{label}.json') for seed in range(1, 31)] for label in rules}
    ranking = {}
    for label in rules:
        real = read_json(REPORTS / (PREFIX + 'account_frozen_' + label + '.json'))
        ranking[label] = {}
        for year in ('all', '2024', '2025', '2026'):
            value = real['total'] if year == 'all' else real['annual'][year]['return']
            values = [r['total'] if year == 'all' else r['annual'][year]['return'] for r in draws[label]]
            better = sum(x > value for x in values)
            tied = sum(x == value for x in values)
            ranking[label][year] = dict(real=value, random_distribution=distribution(values),
                                       rank_of_31=1 + better, strictly_beats=sum(value > x for x in values),
                                       ties=tied, percentile=(sum(value > x for x in values) + .5 * tied) / 30)
    output('random', dict(draws=draws, ranking=ranking, seeds=list(range(1, 31)),
                          policy='每晚完整门禁后池随机无放回五只，沿用同一账户执行'))


def manifest():
    from studies.trader_replication import preopen
    paths = [Path(__file__), PLAN, FROZEN, EXPLANATIONS, Path(system.__file__), Path(preopen.__file__),
             Path(lib.__file__), Path(prior.__file__), Path(ie4.__file__), prior.ie.TIMELINE,
             prior.ie.PERIODS, ROOT / 'studies/martin_luk/notes/trades.csv',
             ROOT / 'studies/martin_luk/notes/PREREG_IE5_CN.md',
             ie4.WORK / 'd1.leader_weekend.True.-1.json']
    return {str(p.relative_to(ROOT)): file_sha(p) for p in paths}


def main(stage):
    WORK.mkdir(exist_ok=True)
    for folder in ('panel', 'stocks', 'group', 'design'):
        (WORK / folder).mkdir(exist_ok=True)
    offline_guard()
    current = manifest()
    manifest_path = WORK / 'evaluation_manifest.json'
    if manifest_path.exists():
        previous = read_json(manifest_path)
        changed = [p for p in current if previous.get(p) != current[p]]
        source = str(Path(__file__).relative_to(ROOT))
        if changed:
            revision = WORK / ('pre_exam_implementation_' + current[source][:12] + '.json')
            if changed != [source] or ((REPORTS / (PREFIX + 'exam.json')).exists() and not revision.exists()):
                raise ValueError('IE5 pinned inputs or post-exam implementation changed')
            if not revision.exists():
                prior.write_json(revision, dict(source_sha256=current, prior_source_sha256=previous[source],
                    reason='Before exam: bitwise-equivalent requested indicator branches; no model or threshold change'))
            elif read_json(revision)['source_sha256'] != current:
                raise ValueError('pre-exam implementation pin differs')
    else:
        prior.write_json(manifest_path, current)
    actions = dict(prepare=prepare, calculate=calculate, exam=exam, ablations=ablations, accounts=accounts)
    actions[stage]()
    if current != manifest():
        raise ValueError('source changed during execution')
    output('runtime_' + stage, dict(stage=stage, source_sha256=current,
                                   peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                                   completed_utc=datetime.now(timezone.utc).isoformat()))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('stage', choices=('prepare', 'calculate', 'exam', 'ablations', 'accounts'))
    main(parser.parse_args().stage)
