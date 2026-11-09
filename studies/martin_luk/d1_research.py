"""Offline D1 descriptive diagnostics. Trader labels never enter system decisions."""
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import resource
import sys
import time
from unittest.mock import patch

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
HOME = Path(__file__).resolve().parent
OUT = HOME / 'reports/d1_work'
GAP = ROOT / 'studies/trader_replication/reports/gap_review'
PYTHON = '/opt/opend-us-options/.venv/bin/python'
STARTED = time.monotonic()


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def clean(value):
    if isinstance(value, dict):
        return {str(k): clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(v) for v in value]
    if isinstance(value, np.ndarray):
        return clean(value.tolist())
    if isinstance(value, np.generic):
        return clean(value.item())
    if isinstance(value, float) and not np.isfinite(value):
        return None
    return value


def write(name, value):
    path = OUT / name
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(clean(value), ensure_ascii=False, indent=1, allow_nan=False) + '\n', encoding='utf-8')
    tmp.replace(path)


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def log(message):
    print(f'[{time.monotonic()-STARTED:.0f}s; '
          f'{resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024:.0f} MiB] {message}', flush=True)


def offline():
    sys.dont_write_bytecode = True
    def guard(event, values):
        if event in ('socket.connect', 'socket.bind', 'socket.getaddrinfo'):
            raise PermissionError('D1 is offline')
        if event == 'open' and not isinstance(values[0], int):
            flags = values[2]
            if flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND):
                path = Path(os.fsdecode(values[0])).resolve()
                if not path.is_relative_to(OUT.resolve()) and path != (HOME/'reports/D1_CN.md').resolve():
                    raise PermissionError(f'D1 writes only under {OUT}: {path}')
    sys.addaudithook(guard)


def panel():
    from studies import trader_data as TD
    from studies.trader_data import panel as TP
    return TP.build(TD.dataset('us', 'frozen'), write_cache=False)


def signals(A, book):
    return [dict(day=str(A['days'][d]), code=str(A['codes'][e[1]]), side=int(e[2]),
                 fill=float(e[3]), stop=float(e[4]), kind=e[5], priority=clean(e[0]))
            for d, row in enumerate(book) for e in row]


def freeze():
    """Fix the descriptive protocol and legacy 42-leg denominator before measurement."""
    from studies.trader_replication import mainleg
    meta = read(GAP / 'ie5_work/prepared.json')
    days = meta['days']
    di = {d: i for i, d in enumerate(days)}
    prices = {}
    for code in sorted({e['code'] for e in meta['entries']}):
        with np.load(GAP / 'ie5_work/stocks' / (code+'.npz')) as z:
            prices[code] = {k: z[k].astype(float) for k in ('o', 'h', 'l', 'c')}
    legs = mainleg.legs([(e['code'], di[e['entry_date']], e['id']) for e in meta['entries']], prices)
    lookup = {e['id']: e for e in meta['entries']}
    for i, leg in enumerate(legs):
        first, peak = leg['entries'][0]['index'], leg['peak']
        p = prices[leg['code']]
        trough = max(0, peak-60) + int(np.nanargmin(p['l'][max(0, peak-60):peak+1]))
        leg.update(id=f'L{i+1:02d}', first=first, first_date=days[first], peak_date=days[peak],
                   trough=trough, trough_date=days[trough], low=float(p['l'][trough]),
                   base=float(p['c'][first]), duration=peak-first, year=days[first][:4],
                   precisions=[lookup[e['label']]['precision'] for e in leg['entries']])
    counts = Counter(x['year'] for x in legs)
    assert counts == {'2024': 9, '2025': 16, '2026': 17}, counts
    write('legs_legacy42.json', dict(days=days, legs=legs, entry_count=len(meta['entries']),
          generator='mainleg.legs on ie5_work/prepared.json entries; defaults 60 sessions / 30%',
          mainleg_sha256=sha(mainleg.__file__)))
    sources = [HOME/'notes/PLAN_D1_CN.md', HOME/'notes/PI_METRIC_BRIEF_20261107_CN.md',
               HOME/'notes/PI_METRIC_ADVICE_20261107_CN.md', HOME/'notes/RULES_CN.md',
               HOME/'reports/final_system_r74.json', HOME/'reports/s7.json',
               GAP/'ie5_work/prepared.json', HOME/'reports/ie47_profile.json',
               ROOT/'studies/trader_replication/systems.py', Path(mainleg.__file__),
               HOME/'ie47_e1.py', HOME/'replicate.py', ROOT/'studies/trader_replication/system.py',
               ROOT/'studies/trader_replication/standard_indicators.py', Path(__file__)]
    protocol = dict(task='D1 descriptive decomposition; no parameter fitting or candidate selection',
        accounts='2024-01-02 through 2026-10-16 continuous accounts for every main comparison',
        legacy_pi_bridge='master C062 train plus standalone 2026 reported separately',
        segment='entry/add lot timestamp in [first-3,peak); mark remaining shares at peak close',
        allocation='overlapping segments: greatest remaining percentage upside, then earliest first',
        sales='pro rata across the open lots of that trade; proportional buy/sell fees; no financing attribution',
        early='actual fill keeps >= half of at least one eligible anchor gain',
        lifecycle='(fill - minimum low in peak-60..peak)/(peak high - that minimum low)',
        portrait='first three eligible close nights, from first-3 through peak-1 while >= half remains; '
                 'one vote per segment; all opportunity nights supplied separately',
        peers='same-night whole liquid range raw>=1 and to20>=2M; master pool and momentum list as known that night; IE47 kept pool',
        year_policy='2024-25 description and 2026 fixed-configuration diagnostic; no new validation selection',
        resources=dict(python=PYTHON, CPUQuota='60%', MemoryMax='900M', threads=1),
        prohibited=['network', 'new data', 'git commit', 'registration/board changes', 'A-line shared file writes'],
        memory_before=Path('/proc/meminfo').read_text(),
        sources={str(p.relative_to(ROOT)): sha(p) for p in sources})
    write('protocol.json', protocol)
    log(f'fixed legacy denominator {dict(counts)}')


def master():
    from studies.trader_replication import systems, system as Y
    from studies.martin_luk import replicate as R
    s = next(s for s in systems.all_() if s.id == 'martin_luk')
    st, cfg = s.load()
    p = panel()
    log(f'loaded frozen panel {p["close"].shape}')
    A = R.market_arrays('us', p)
    A['digest'] = p['digest']
    del p
    log('master arrays built')
    original = R.system_signals
    def capture(A, cfg):
        pool, watch, families = original(A, cfg)
        np.save(OUT/'master_liquidity.npy', pool)
        np.save(OUT/'master_momentum.npy', watch)
        # Arrays are trade-day indexed and use the preceding close for pool/watch.
        for name, value in families.items():
            np.save(OUT/('master_family_'+name.replace(':', '_')+'.npy'), value)
        return pool, watch, families
    trace = {}
    with patch.object(R, 'system_signals', capture):
        entries, rules, mask, pool = st.build(A, cfg, trace)
    log('registered R74 + S7 book built')
    for name in ('raw', 'filtered', 'capped', 'short_entries'):
        write('master_'+name+'.json', signals(A, trace.get(name, [[] for _ in entries])))
    write('master_book.json', signals(A, entries))
    np.save(OUT/'master_mask.npy', mask)
    track = {'entry_attempts': []}
    curve, dates, trades = Y.simulate(st.px(A), st.ema_inputs(A, pool, rules), rules, entries,
                                      *st.full, audit=True, track=track)
    write('master_trades.json', trades)
    write('master_curve.json', dict(days=dates, equity=curve))
    write('master_attempts.json', track['entry_attempts'])
    write('master_metadata.json', dict(version=s.version, config=cfg, rules=asdict(rules),
          stats=Y.stats(curve, dates, trades), digest=A['digest'], days=A['days'], codes=A['codes'],
          source='systems.all_()[martin_luk].load(); registered long and short account',
          peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss))
    log(f'master replay done: {len(trades)} trades; total={curve[-1]-1:+.4f}')


def selection():
    from studies import trader_data as TD
    from studies.martin_luk import ie47_e1 as M
    p = panel()
    log('rebuilding fixed IE47 selection')
    R = M.selection(p, TD.dataset('us', 'frozen'), 'frozen', progress=log)
    np.save(OUT/'ie_pool.npy', R['pool'])
    total = sum(map(len, R['scopes']))
    scope_j = np.lib.format.open_memmap(OUT/'ie_scope_j.npy', mode='w+', dtype='int32', shape=(total,))
    gate_raw = np.lib.format.open_memmap(OUT/'ie_gate_raw.npy', mode='w+', dtype='float32', shape=(total, 4))
    gate_pct = np.lib.format.open_memmap(OUT/'ie_gate_pct.npy', mode='w+', dtype='float32', shape=(total, 4))
    rows = []
    offset, scope_offset = 0, 0
    for t, scope, kept, raw in zip(R['night_indices'], R['scopes'], R['kept'], R['raw']):
        _, percentiles = M.filter_night(raw)
        sl = slice(scope_offset, scope_offset+len(scope))
        scope_j[sl], gate_raw[sl], gate_pct[sl] = scope, raw, percentiles
        scope_offset = sl.stop
        score = R['scores'][offset:offset+len(kept)]
        offset += len(kept)
        order = np.argsort(-score, kind='stable')
        ranks = {int(kept[k]): r+1 for r, k in enumerate(order)}
        scores = dict(zip(map(int, kept), map(float, score)))
        rows.append(dict(day=str(p['days'][t]), index=int(t), scope_start=sl.start, scope_end=sl.stop, kept=kept,
                         ranks={str(p['codes'][j]): ranks[int(j)] for j in kept},
                         scores={str(p['codes'][j]): scores[int(j)] for j in kept}))
    scope_j.flush()
    gate_raw.flush()
    gate_pct.flush()
    write('ie_selection.json', dict(picks=R['picks'], nights=rows, gates=M.GATES,
                                    codes=p['codes'], days=p['days'], sources=R['sources']))
    reference = read(HOME/'reports/e21_work/inputs.json')['picks']
    assert R['picks'] == reference, 'IE47 selection differs from E21 frozen account inputs'
    write('selection_check.json', dict(exact_e21_picks=True, nights=len(rows),
                                     peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss))
    log(f'IE47 selection matches {len(reference)} E21 nights exactly')


def trace():
    """Read-only account/observation instrumentation, with exact ledger replay checks."""
    from studies.trader_replication import system as Y
    from studies.trader_data import supplemental as SP
    from studies.trader_screens import screens as S
    from studies.martin_luk import ie47_e1 as M, e15_research as E15
    p = panel()
    days, codes = list(map(str, p['days'])), list(map(str, p['codes']))
    ci, di = {c: j for j, c in enumerate(codes)}, {d: i for i, d in enumerate(days)}
    A = dict(p, market='us', mode='frozen', raw=p['raw_close'])
    A['adr'] = np.full(p['close'].shape, np.nan)
    for start in range(0, len(codes), 64):
        sl = slice(start, start+64)
        A['adr'][:, sl] = S.rolling(A['high'][:, sl].astype(float)/A['low'][:, sl].astype(float)-1, 20, 'mean')*100
    picks = read(OUT/'ie_selection.json')['picks']
    ie_book, _, events = M.entry_book(A, picks, **M.E6['E6c'])
    actual_ie = read(HOME/'reports/e21_work/BASE_signals.json')
    rebuilt = sorted((s['day'], s['code'], s['fill'], s['stop'], s['kind']) for s in signals(A, ie_book))
    expected = sorted((s['day'], s['code'], s['fill'], s['stop'], s['kind']) for s in actual_ie)
    assert rebuilt == expected, (len(rebuilt), len(expected), [(a, b) for a, b in zip(rebuilt, expected) if a != b][:2])
    write('ie_observations.json', events)
    log('IE47 five-night observations match complete E21 BASE book')
    book = [[] for _ in days]
    master_picks = read(HOME/'reports/e21_work/master/picks.json')
    current_picks = {days[d]: [] for d in range(len(days))}
    current = read(OUT/'master_capped.json')
    for s in current:
        if s['side'] > 0:
            current_picks[s['day']].append(s['code'])
    assert all(current_picks.get(d, []) == names for d, names in master_picks.items()), 'master signal drift'
    for s in current:
        if s['side'] > 0:
            d, j = di[s['day']], ci[s['code']]
            rank = len(book[d])
            book[d].append(((rank, d, s['code']), j, 1, s['fill'], s['stop'], 'master_close', None))
    pool = np.load(OUT/'ie_pool.npy', mmap_mode='r')
    qqq, _ = SP.benchmark('US.QQQ', days, 'frozen')
    A['e8_scale'] = M.regime_scale(qqq, pool.sum(1), M.E8['E8c'])
    for name, length in (('e9', 9), ('e21', 21)):
        A[name] = S.ema(A['close'], length)
    A['_e14_base'] = book, M.e8_rules('E8c'), np.zeros_like(pool), pool
    st = E15.E15Study()
    built, rules, _, used_pool = st.build(A, dict(candidate='C062'))
    track = {'entry_attempts': []}
    curve, dates, trades = Y.simulate(st.px(A), st.ema_inputs(A, used_pool, rules), rules, built,
                                    '2024-01-02', '2026-10-16', audit=True, track=track)
    old = read(HOME/'reports/e15_work/master_swap/full/C062_2024_trades.json')
    ignored = {'origin', 'observed', 'attempt'}
    assert [{k: v for k, v in t.items() if k not in ignored} for t in old] == trades, 'C062 ledger replay differs'
    assert read(HOME/'reports/e15_work/master_swap/full/C062_2024_curve.json') == clean(dict(days=dates, equity=curve))
    write('master_c062_attempts.json', track['entry_attempts'])
    write('trace_checks.json', dict(master_capped_matches_e21=True, ie_base_book_matches_e21=True,
          master_c062_trades_exact=True, master_c062_curve_exact=True, rules=asdict(rules),
          peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss))
    log(f'master+C062 exact replay: {len(trades)} trades; attempts recovered')


def paths():
    """Identify all simultaneous entry routes; do not pretend a union has a unique cause."""
    from studies.martin_luk import replicate as R
    A = R.market_arrays('us', panel())
    cfg = read(OUT/'master_metadata.json')['config']
    pool = R.pool_for(A, cfg.get('pool'))
    ep = R.ep_signal(A, pool, **cfg.get('ep_opts', {}))
    base = R.base_path(A, pool, cfg['bpath'], **cfg.get('bopts', {}))
    np.save(OUT/'master_ep.npy', ep)
    np.save(OUT/'master_bpath.npy', base)
    combined = ep | base
    for file in OUT.glob('master_family_*.npy'):
        combined |= np.load(file, mmap_mode='r')
    assert np.array_equal(combined, np.load(OUT/'master_mask.npy', mmap_mode='r'))
    pool_name = cfg.get('pool') or R.chosen('r20_pool.json', 'U0')
    watch = cfg.get('watch') or R.watch_choice()
    names = ('r20_pool.json', 'r22b_watchlist.json', 'r22_watchlist.json')
    write('master_paths.json', dict(routes_exact=True, pool=pool_name, pool_thresholds=R.POOLS[pool_name],
          watch=watch, strength=cfg.get('strength') or R.strength_choice(), exits=R.EXITS[cfg['exits']],
          sources={str((HOME/'reports'/n).relative_to(ROOT)): sha(HOME/'reports'/n)
                   for n in names if (HOME/'reports'/n).exists()},
          peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss))
    log('master entry-route union matches exactly')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('stage', choices=('freeze', 'master', 'selection', 'trace', 'paths'))
    args = parser.parse_args()
    OUT.mkdir(exist_ok=True)
    offline()
    globals()[args.stage]()
