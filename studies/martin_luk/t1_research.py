"""T1: opt-in offline theme attribution of existing continuous account ledgers."""
from __future__ import annotations

import argparse
from collections import defaultdict
from functools import lru_cache
import hashlib
import json
import math
import os
from pathlib import Path
import random
import resource
import sys
import time
from types import SimpleNamespace

import numpy as np

from studies.trader_replication import mainleg as M
from . import y1_research as Y1

ROOT = Path(__file__).resolve().parents[2]
HOME = ROOT/'studies/martin_luk'
OUT = HOME/'reports/t1_work'
REPORT = HOME/'reports/T1_CN.md'
PANEL = HOME/'reports/u1_work/panel'
INDUSTRY = ROOT/'data/trader-screens/cache/industry_us.json'
YEARS = ('2024', '2025', '2026')
MODES = ('correlation', 'industry_snapshot')
REPEATS, SEED = 100, 20261108
STARTED = time.monotonic()
BOOKS = {
    'IE47_C062': ('e21_work/BASE_full/C062_2024', 'y1_work/IE47_C062.json'),
    'master_C062': ('e15_work/master_swap/full/C062_2024', 'y1_work/master_C062.json'),
    'registered_master': ('d1_work/master', None),
    'M1B': ('m1_work/validation/continuous/', 'm1_work/validation/continuous/metrics.json'),
    'M2A': ('m2_work/validation/continuous/', 'm2_work/validation/continuous/metrics.json'),
    'M3B': ('m3_work/validation/continuous/', 'm3_work/validation/continuous/metrics.json'),
}

read, sha = Y1.read, Y1.sha


def clean(v):
    if isinstance(v, dict):
        return {str(k): clean(x) for k, x in v.items()}
    if isinstance(v, (tuple, list, np.ndarray)):
        return [clean(x) for x in v]
    if isinstance(v, np.generic):
        return clean(v.item())
    return None if isinstance(v, float) and not math.isfinite(v) else v


def write(name, value):
    p = OUT/name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(clean(value), ensure_ascii=False, indent=1, allow_nan=False)+'\n')


def resources():
    cg = next(s.split(':', 2)[2] for s in Path('/proc/self/cgroup').read_text().splitlines()
              if s.startswith('0::'))
    folder = Path('/sys/fs/cgroup')/cg.lstrip('/')
    return dict(python=sys.executable, cpu_max=(folder/'cpu.max').read_text().strip(),
                memory_max=(folder/'memory.max').read_text().strip(),
                memory_peak=(folder/'memory.peak').read_text().strip(),
                threads=int(next(s.split()[1] for s in Path('/proc/self/status').read_text().splitlines()
                                 if s.startswith('Threads:'))),
                peak_rss_mib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024,
                elapsed_seconds=time.monotonic()-STARTED, meminfo=Path('/proc/meminfo').read_text(), cgroup=cg)


def offline():
    sys.dont_write_bytecode = True
    def guard(event, args):
        if event in ('socket.connect', 'socket.bind', 'socket.getaddrinfo', 'subprocess.Popen', 'os.system'):
            raise PermissionError('T1 is offline and single-process')
        if event == 'open' and not isinstance(args[0], int) and args[2] & (
                os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND):
            p = Path(os.fsdecode(args[0])).resolve()
            if not p.is_relative_to(OUT.resolve()) and p != REPORT.resolve():
                raise PermissionError('T1 output boundary: '+str(p))
    sys.addaudithook(guard)


def once(stage):
    r = resources()
    assert r['cpu_max'] == '60000 100000' and r['memory_max'] == str(900*1024**2) and r['threads'] == 1, r
    with (OUT/(stage+'_started.json')).open('x') as f:
        json.dump(dict(resources=r, code_sha256=sha(Path(__file__)), protocol_sha256=sha(OUT/'protocol.md')), f)


def book_paths(prefix):
    base = HOME/'reports'/prefix
    return {s: base/(s+'.json') if prefix.endswith('/') else Path(str(base)+'_'+s+'.json')
            for s in ('trades', 'curve')}


def freeze():
    once('freeze')
    paths = [HOME/'notes/legs_frozen.json', HOME/'notes/trades.csv', HOME/'notes/PLAN_T1_CN.md',
             HOME/'notes/PI_METRIC_BRIEF_20261107_CN.md', Path(__file__),
             HOME/'m1_research.py', Path(Y1.__file__), HOME/'t1_report.py', INDUSTRY, OUT/'protocol.md',
             HOME/'tests/test_t1.py', OUT/'run_tests.py']
    paths += [PANEL/(n+'.npy') for n in ('days', 'codes', 'digest', 'close', 'high', 'low', 'raw_close', 'turnover')]
    paths += [HOME/'reports/u1_work/liquid.npy', HOME/'reports/u1_work/native_master_capture.json']
    for prefix, ref in BOOKS.values():
        paths += list(book_paths(prefix).values())
        if ref:
            paths.append(HOME/'reports'/ref)
        if prefix.endswith('/'):
            paths.append(HOME/'reports'/prefix/'rules.json')
    paths.append(HOME/'reports/d1_work/master_metadata.json')
    protected = list((HOME/'reports').glob('*.md'))
    protected += list((ROOT/'studies/trader_screens').glob('*.py'))
    protected += list((ROOT/'studies/trader_replication').glob('*.py'))
    protected += [HOME/'reports/final_system_r74.json', HOME/'reports/ie47_profile.json']
    write('protocol.json', dict(inputs={str(p.relative_to(ROOT)): sha(p) for p in paths},
          protected={str(p.relative_to(ROOT)): sha(p) for p in protected}, resources=resources(),
          industry_point_in_time_available=False, panel_industry_fields=[], repeats=REPEATS, seed=SEED,
          accounts=BOOKS, account_simulations=0, independent_out_of_sample=False))


def panel():
    return {k: np.load(PANEL/(k+'.npy'), mmap_mode='r')
            for k in ('days', 'codes', 'digest', 'close', 'high', 'low', 'raw_close', 'turnover')}


def night_pool(p, night):
    if night < 19:
        return np.array([], dtype=int)
    s = slice(night-19, night+1)
    with np.errstate(all='ignore'):
        amount = np.asarray(p['turnover'][s], float).mean(axis=0)
        adr = 100*(np.asarray(p['high'][s], float)/p['low'][s]-1).mean(axis=0)
    return np.flatnonzero((p['raw_close'][night] >= 2) & (amount >= 50e6) & (adr >= 3))


def peer_groups(close, pool, night, centers):
    """Only past closes and a supplied point-in-time pool; no trader labels."""
    empty = {int(j): np.array([], dtype=int) for j in centers}
    if night < 60 or not len(pool):
        return empty, np.array([], dtype=int), {}
    history = np.asarray(close[night-60:night+1, pool], float)
    with np.errstate(all='ignore'):
        returns = history[1:]/history[:-1]-1
    valid = np.isfinite(returns).all(axis=0) & (history > 0).all(axis=0)
    centered = np.where(valid, returns, 0.)
    centered -= centered.mean(axis=0)
    norm = np.linalg.norm(centered, axis=0)
    valid &= norm > 1e-12
    usable, z = pool[valid], (centered[:, valid]/norm[valid]).T
    positions = {int(j): k for k, j in enumerate(usable)}
    out, correlations = {}, {}
    for j in centers:
        if j not in positions:
            out[int(j)] = np.array([], dtype=int)
            continue
        corr = z @ z[positions[j]]
        keep = (corr >= .6) & (usable != j)
        out[int(j)] = usable[keep]
        correlations[int(j)] = corr[keep]
    return out, usable, correlations


def industry_peers(labels, pool, center):
    label = labels[center]
    if center not in pool or not label or label == '未分类':
        return np.array([], dtype=int)
    return pool[(labels[pool] == label) & (pool != center)]


def spread(values):
    a = np.asarray(values, float)
    return dict(n=len(a), minimum=float(a.min()) if len(a) else None,
                maximum=float(a.max()) if len(a) else None,
                **{name: float(np.quantile(a, q)) if len(a) else None
                   for name, q in (('q05', .05), ('q25', .25), ('median', .5), ('q75', .75), ('q90', .9), ('q95', .95))})


def groups():
    once('groups')
    p, frozen = panel(), read(HOME/'notes/legs_frozen.json')
    days, codes = p['days'].tolist(), p['codes'].tolist()
    assert days == frozen['calendar'] and len(frozen['legs']) == 48
    ci = {c: j for j, c in enumerate(codes)}
    labels = read(INDUSTRY)
    labels = np.array([labels.get(c, '') for c in codes])
    cached_pool = np.load(HOME/'reports/u1_work/liquid.npy', mmap_mode='r')
    stats = {g['key']: dict(leg=g, nights=[], correlation=[], industry_snapshot=[], pool=[], usable=[], overwide=[]) for g in frozen['legs']}
    unions = []
    with (OUT/'groups.jsonl').open('x') as stream:
        for t, day in enumerate(days):
            if day[:4] not in YEARS:
                continue
            pool = night_pool(p, t)
            np.testing.assert_array_equal(pool, np.flatnonzero(cached_pool[t]))
            active = [g for g in frozen['legs'] if max(0, g['first']-3) <= t < min(g['peak'], g.get('exit_known') or g['peak'])]
            if not active:
                unions.append(dict(day=day, correlation=0., industry_snapshot=0., active=0))
                continue
            centers = sorted({ci[g['code']] for g in active})
            peers, usable, correlations = peer_groups(p['close'], pool, t, centers)
            record = dict(night=t, day=day, pool=pool, usable=usable,
                          known_industry=pool[(labels[pool] != '') & (labels[pool] != '未分类')], groups=[])
            joined = {mode: set() for mode in MODES}
            for g in active:
                j, key = ci[g['code']], g['key']
                members = dict(correlation=peers[j], industry_snapshot=industry_peers(labels, pool, j))
                row = dict(key=key, center=j, center_in_pool=bool(j in pool),
                           center_usable=bool(j in usable), industry=labels[j], correlations=correlations.get(j, []), **members)
                record['groups'].append(row)
                s = stats[key]
                s['nights'].append(t)
                s['pool'].append(len(pool))
                s['usable'].append(bool(j in usable))
                s['overwide'].append(bool(len(pool) and len(peers[j]) > .2*len(pool)))
                for mode in MODES:
                    s[mode].append(len(members[mode]))
                    joined[mode].update(map(int, members[mode]))
                if j in pool:
                    for mode in MODES:
                        joined[mode].add(j)
            stream.write(json.dumps(clean(record), ensure_ascii=False)+'\n')
            unions.append(dict(day=day, active=len(active), **{m: len(joined[m])/len(pool) if len(pool) else 0. for m in MODES}))
    output = []
    for s in stats.values():
        g = s['leg']
        output.append(dict(key=g['key'], code=g['code'], year=g['first_date'][:4],
             censored=g['censored'], precision=g['precision'], nights=len(s['nights']),
             usable_nights=sum(s['usable']), overwide_nights=sum(s['overwide']),
             correlation=spread(s['correlation']), industry_snapshot=spread(s['industry_snapshot']),
             max_pool_fraction=max((n/pool for n, pool in zip(s['correlation'], s['pool']) if pool), default=0.)))
    write('groups_summary.json', dict(legs=output, nightly_union=unions,
          correlation_peer_counts=spread([n for s in stats.values() for n in s['correlation']]),
          overwide_legs=sum(s['overwide_nights'] > 0 for s in output),
          unknown_industry_centers=[g['key'] for g in frozen['legs'] if not labels[ci[g['code']]] or labels[ci[g['code']]] == '未分类'],
          causal_pool_matches_u1_all_sessions=True, resources=resources()))
    print('T1 nightly peer groups saved', flush=True)


def load_groups():
    result = {}
    with (OUT/'groups.jsonl').open() as stream:
        for line in stream:
            r = json.loads(line)
            for key in ('pool', 'usable', 'known_industry'):
                r[key] = np.asarray(r[key], dtype=np.int32)
            for g in r['groups']:
                for mode in MODES:
                    g[mode] = np.asarray(g[mode], dtype=np.int32)
            result[r['night']] = r
    assert len(result) <= 701
    return result


class Prices:
    def __init__(self, p):
        self.p, self.ci = p, {c: j for j, c in enumerate(p['codes'].tolist())}

    def __getitem__(self, code):
        j = self.ci[code.removeprefix('SHORT:')]
        return {k: self.p[v][:, j] for k, v in (('h', 'high'), ('l', 'low'), ('c', 'close'))}


def load_account(name, calendar, prices):
    prefix, reference = BOOKS[name]
    paths = book_paths(prefix)
    if name == 'registered_master':
        from .m1_research import adapt
        trades, residual = adapt(read(paths['trades']), calendar,
               SimpleNamespace(**read(HOME/'reports/d1_work/master_metadata.json')['rules']), prices)
    else:
        trades, check = Y1.adapt(paths['trades'], calendar)
        residual = check['max_residual']
    curve = read(paths['curve'])
    equity = np.ones(len(calendar))
    di = {d: i for i, d in enumerate(calendar)}
    for d, e in zip(curve['days'], curve['equity']):
        equity[di[d]] = e
    assert curve['days'][0] == '2024-01-02' and curve['days'][-1] == '2026-10-16'
    return trades, equity, reference, residual


def peer_cutoffs(rows, records, legs, ci, mode, repeat=None):
    """One cutoff per matched FIFO piece; same random draw for every account."""
    @lru_cache(maxsize=128)
    def members(night, key):
        record = records[night]
        group = next(g for g in record['groups'] if g['key'] == key)
        if repeat is None:
            return group[mode]
        pool = record['usable' if mode == 'correlation' else 'known_industry']
        pool = pool[pool != group['center']]
        seed = int.from_bytes(hashlib.sha256(f'{SEED}:{mode}:{night}:{key}:{repeat}'.encode()).digest()[:8], 'big')
        return np.array(sorted(random.Random(seed).sample(pool.tolist(), len(group[mode]))), dtype=np.int32)
    result = []
    for row in rows:
        cutoff = -1
        j = ci.get(row['code'])
        if j is not None:
            record = records.get(row['entry'])
            for group in record['groups'] if record else ():
                g = legs[group['key']]
                if j != group['center'] and row['exit'] >= g['first'] and j in members(row['entry'], group['key']):
                    cutoff = max(cutoff, min(row['exit'], g['peak'], g.get('exit_known') or g['peak']))
        result.append(cutoff)
    return result


def relabel(rows, prices, cutoffs=None):
    """Default off: leave Y1 rows intact. Explicit cutoffs only broaden H."""
    if cutoffs is None:
        return rows
    if len(rows) != len(cutoffs):
        raise ValueError('one cutoff is required per FIFO piece')
    output = []
    for number, (row, peer_end) in enumerate(zip(rows, cutoffs)):
        own_end = row['h_end'] if row['bucket'] == 'T1' else -1
        theme_end = max(own_end, peer_end)
        old_end = row['h_end'] if row['bucket'] in ('T1', 'T2') else -1
        begin, after = row['entry'], row['exit']+1
        cuts = sorted({begin, after} | {d+1 for d in (old_end, theme_end) if begin <= d < row['exit']})
        for start, stop in zip(cuts, cuts[1:]):
            first, last = start == begin, stop == after
            basis = row['price'] if first else float(prices[row['code']]['c'][start-1])
            mark = row['exit_price'] if last else float(prices[row['code']]['c'][stop-1])
            if not all(math.isfinite(v) and v > 0 for v in (basis, mark)):
                raise ValueError('invalid theme boundary mark')
            pnl = (row['pnl'] if first and last else row['shares']*(mark-basis)
                   - (row['buy_fee'] if first else 0.) - (row['sell_fee'] if last else 0.)
                   + (row['residual'] if last else 0.))
            his, strict = start <= theme_end, start <= own_end
            bucket = 'T1' if his else ('post_peak' if old_end >= begin and start > old_end else row['bucket'])
            output.append(dict(row, entry=start, exit=row['exit'] if last else stop,
                open=row['open'] if last else False, pnl=pnl, bucket=bucket,
                basis_price=basis, exit_price=mark, original_exit_price=row['exit_price'],
                buy_fee=row['buy_fee'] if first else 0., sell_fee=row['sell_fee'] if last else 0.,
                residual=row['residual'] if last else 0.,
                h_end=stop-1 if his else (old_end if bucket == 'T2' else None),
                h_pnl=pnl if his or bucket == 'T2' else 0., post_pnl=0.,
                h_exit_price=mark if his or bucket == 'T2' else None, peer_cutoff=peer_end,
                original_entry=begin, original_exit=row['exit'], original_piece=number,
                strict_h=strict, peer_h=his and not strict,
                unseen_peer_h=his and not strict and not (row['bucket'] == 'T2' and start <= old_end)))
    return output


def metrics(rows, trades, days, prices, equity):
    years, daily = M.account_purity(rows, trades, days, prices, equity)
    for year, value in years.items():
        part = [r for r in rows if r['year'] == year]
        for kind in ('peer_h', 'unseen_peer_h'):
            value[kind+'_pnl'] = sum(r['pnl'] for r in part if r.get(kind))
            value[kind+'_gross'] = sum(max(0., r['pnl']) for r in part if r.get(kind))
        value['unseen_peer_pnl_share_H'] = value['unseen_peer_h_pnl']/value['H'] if value['H'] > 0 else None
        value['unseen_peer_pnl_share_all'] = value['unseen_peer_h_pnl']/value['total_pnl'] if value['total_pnl'] > 0 else None
        value['unseen_peer_gross_share_H'] = value['unseen_peer_h_gross']/value['buckets']['T1']['gross'] if value['buckets']['T1']['gross'] > 0 else None
        value['distance_capital_pp'] = 100*(.5-value['cap_equity'])
        value['distance_gross_pp'] = 100*(.6-value['purity_gross']) if value['purity_gross'] is not None else None
    return {y: years[y] for y in YEARS}, daily


def evaluate():
    once('evaluate')
    p, frozen, records = panel(), read(HOME/'notes/legs_frozen.json'), load_groups()
    days, prices = p['days'].tolist(), Prices(p)
    legs = {g['key']: g for g in frozen['legs']}
    ticker_years = {(r['code'], r['anchor'][:4]) for r in frozen['audit'] if r['anchor']}
    summaries, compatibility = {}, {}
    for name in BOOKS:
        trades, equity, ref, residual = load_account(name, days, prices)
        rows = M.attribute_lots(trades, frozen['legs'], prices, days, frozen['other_legs'], ticker_years)
        base, original_daily = metrics(rows, trades, days, prices, equity)
        if ref:
            saved = read(HOME/'reports'/ref)['years']
            diffs = {y: {k: base[y][k]-saved[y][k] for k in ('cap_equity', 'purity_gross', 'H', 'gross', 'total_pnl', 'top10_his_leg')} for y in YEARS}
            assert all(abs(v) < 1e-9 for d in diffs.values() for v in d.values()), (name, diffs)
            compatibility[name] = dict(max_difference=max(abs(v) for d in diffs.values() for v in d.values()), residual=residual)
        else:
            expected = read(HOME/'reports/u1_work/native_master_capture.json')['legs']
            actual = M.account_coverage(rows, frozen['legs'], days)
            assert {r['key']: r['pnl'] for r in expected} == {r['key']: r['pnl'] for r in actual}
            compatibility[name] = dict(u1_all_48_leg_H_exact=True, short_trades=sum(t['code'].startswith('SHORT:') for t in trades), residual=residual)
        account = dict(strict=base, modes={}, random={}, adapter_residual=residual)
        for mode in MODES:
            cutoffs = peer_cutoffs(rows, records, legs, prices.ci, mode)
            attributed = relabel(rows, prices, cutoffs)
            result, daily = metrics(attributed, trades, days, prices, equity)
            assert np.all(daily['his'] >= original_daily['his']-1e-10)
            np.testing.assert_allclose(daily['gross'], original_daily['gross'], rtol=0, atol=1e-10)
            for y in YEARS:
                assert math.isclose(result[y]['H'], base[y]['H']+result[y]['peer_h_pnl'], abs_tol=1e-9)
            write(name+'_'+mode+'_lots.json', attributed)
            account['modes'][mode] = result
            draws = []
            for repeat in range(REPEATS):
                shuffled = relabel(rows, prices, peer_cutoffs(rows, records, legs, prices.ci, mode, repeat))
                value, _ = metrics(shuffled, trades, days, prices, equity)
                draws.append({y: {k: value[y][k] for k in ('cap_equity', 'purity_gross', 'H', 'top10_his_leg')} for y in YEARS})
            write(name+'_'+mode+'_random_draws.json', draws)
            account['random'][mode] = {y: {k: spread([d[y][k] for d in draws]) for k in draws[0][y]} for y in YEARS}
            print(f'T1 {name} {mode} and {REPEATS} matched random groups complete', flush=True)
        write(name+'.json', account)
        summaries[name] = account
    write('accounts.json', summaries)
    write('compatibility.json', compatibility)
    write('evaluate_complete.json', dict(resources=resources(), accounts=6, theme_attributions_per_account=2,
          random_definition_audits_per_mode=REPEATS, strategy_runs=0, label_table_sha256=sha(HOME/'notes/legs_frozen.json')))


def prefix():
    once('prefix')
    p, records = panel(), load_groups()
    cut = int(np.searchsorted(p['days'], '2025-06-30', side='right'))
    class Future:
        def __init__(self, a, multiplier):
            self.a, self.multiplier = a, multiplier
        def __getitem__(self, key):
            value = np.array(self.a[key], copy=True)
            selection = key[0] if isinstance(key, tuple) else key
            if isinstance(selection, slice):
                first, stop, step = selection.indices(len(self.a))
                changed = np.arange(first, stop, step) >= cut
                value[changed] *= self.multiplier
            elif selection >= cut:
                value *= self.multiplier
            return value
    altered = {k: Future(v, 6 if k == 'turnover' else 3) for k, v in p.items() if k not in ('days', 'codes', 'digest')}
    observations = 0
    for t, r in records.items():
        if t >= cut:
            continue
        centers = sorted({g['center'] for g in r['groups']})
        truncated = {k: v[:cut] for k, v in p.items() if k not in ('days', 'codes', 'digest')}
        for other in (truncated, altered):
            pool = night_pool(other, t)
            np.testing.assert_array_equal(pool, r['pool'])
            actual, _, corr = peer_groups(other['close'], pool, t, centers)
            for g in r['groups']:
                np.testing.assert_array_equal(actual[g['center']], g['correlation'])
                np.testing.assert_array_equal(corr.get(g['center'], []), g['correlations'])
                observations += 1
    write('prefix.json', dict(ok=True, cutoff='2025-06-30', real_truncated_and_future_perturbed=True,
          group_comparisons=observations, resources=resources()))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=('freeze', 'groups', 'evaluate', 'prefix'))
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    offline()
    globals()[args.stage]()


if __name__ == '__main__':
    main()
