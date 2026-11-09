"""Offline P2 stages. All writes stay in the two P2 artifact directories."""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import contextmanager
import csv
import fcntl
import hashlib
import json
import os
from pathlib import Path
import resource
import re
import sys

import numpy as np

from . import p2_signal as S
from studies.trader_replication import regime, pipeline, mainleg, ledger

ROOT, HOME = S.ROOT, S.HOME
AOUT, BOUT = (HOME/f'reports/p2{part}_work' for part in ('a', 'b'))
SOURCES = {}
YEARS = ('2024', '2025', '2026')
GAP = ROOT/'studies/trader_replication/reports/gap_review'
PANEL = HOME/'reports/u1_work/panel'


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def source(path):
    path = Path(path)
    SOURCES[str(path.relative_to(ROOT))] = sha(path)
    return path


def read(path):
    return json.loads(source(path).read_text())


def write(path, value, exclusive=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x' if exclusive else 'w') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=1, allow_nan=False)
        stream.write('\n')


def resources():
    cg = next(r.split(':', 2)[2] for r in Path('/proc/self/cgroup').read_text().splitlines() if r.startswith('0:'))
    folder = Path('/sys/fs/cgroup')/cg.lstrip('/')
    return dict(python=sys.executable, cpu_max=(folder/'cpu.max').read_text().strip(),
        memory_max=(folder/'memory.max').read_text().strip(),
        threads=next(r.split(':')[1].strip() for r in Path('/proc/self/status').read_text().splitlines()
                     if r.startswith('Threads:')), peak_rss_mib=resource.getrusage(0).ru_maxrss/1024)


def offline():
    sys.dont_write_bytecode = True
    def guard(event, args):
        if event in ('socket.connect', 'socket.bind', 'socket.getaddrinfo', 'subprocess.Popen', 'os.system'):
            raise PermissionError('P2 offline single-process boundary')
        if event == 'open' and not isinstance(args[0], int) and args[2] & (
                os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND):
            path = Path(os.fsdecode(args[0])).resolve()
            if not any(path.is_relative_to(p.resolve()) for p in (AOUT, BOUT)) and path not in (
                    HOME/'reports/P2A_CN.md', HOME/'reports/P2B_CN.md'):
                raise PermissionError('P2 output boundary: '+str(path))
    sys.addaudithook(guard)
    from studies.trader_replication import system
    def forbidden(*args, **kwargs):
        raise AssertionError('P2 cannot run build, allocation, trading or accounts')
    system.simulate = forbidden
    for name in ('build', 'allocate', 'trade', 'run', 'evaluate'):
        setattr(S.Study, name, forbidden)


@contextmanager
def strategy_only():
    """Fail even on a read attempt; use around signal generation, not scoring."""
    from unittest.mock import patch
    import builtins
    original = builtins.open
    def guarded(path, *args, **kwargs):
        if not isinstance(path, int) and any(s in os.fsdecode(path) for s in (
                'trades.csv', 'legs_frozen', 'scorecard', 'entries.json', 'labels', 'targets')):
            raise PermissionError('evaluation input requested by strategy')
        return original(path, *args, **kwargs)
    # Path.open uses io.open rather than builtins.open.
    import io
    with patch.object(builtins, 'open', guarded), patch.object(io, 'open', guarded):
        yield


def freeze():
    protected = {}
    for directory in ('studies/trader_replication', 'studies/trader_screens', 'studies/martin_luk',
                      'skills/trader-replication'):
        for path in (ROOT/directory).rglob('*'):
            if path.suffix not in ('.py', '.md') or not path.is_file() or path.name.startswith('p2_'):
                continue
            if path.name in ('P2A_CN.md', 'P2B_CN.md', 'PREREG_P2A_CN.md', 'PREREG_P2B_CN.md'):
                continue
            if path.is_relative_to(AOUT) or path.is_relative_to(BOUT):
                continue
            protected[str(path.relative_to(ROOT))] = sha(path)
    for path in (HOME/'notes/trades.csv', HOME/'notes/legs_frozen.json',
                 ROOT/'studies/trader_replication/systems.py', ROOT/'studies/trader_replication/DATA_PIN.json'):
        protected[str(path.relative_to(ROOT))] = sha(path)
    write(AOUT/'protocol.json', dict(task='PLAN_P2_CN', protected=protected, memory_before=Path('/proc/meminfo').read_text(),
        plan_sha256=sha(HOME/'notes/PLAN_P2_CN.md'), prereg_sha256=sha(HOME/'notes/PREREG_P2A_CN.md'),
        resources=resources(), constraints=dict(offline=True, no_downloads=True, no_git_commits=True,
        no_accounts=True, no_allocation_research=True, no_registry_or_board_changes=True),
        secret_guard='existing pre-commit/pre-push already exec scripts/secret_guard.py; installer did not overwrite hooks'), True)


def clipped_episodes(labels, days):
    out = regime.episodes(labels, days)
    return out


def regimes():
    protocol = read(AOUT/'protocol.json')
    assert protocol['prereg_sha256'] == sha(HOME/'notes/PREREG_P2A_CN.md')
    for code in ('US.QQQ', 'US.IWM'):
        source(ROOT/'data/martin-luk-benchmarks-v1'/f'{code}.csv')
    with strategy_only():
        A = S.benchmarks()
    days = A['days']
    mask = (days >= '2024-01-02') & (days <= '2026-10-16')
    assert mask.sum() == 701
    result = {}
    for producer in ('idx_ema', 'smc'):
        with strategy_only():
            full = S.market_states(A, producer)
            variants = []
            for name, spec in regime.perturbations(dict(producer=producer, source='US.QQQ')):
                spec = {k: spec[k] for k in ('fast', 'slow', 'band', 'fractal')}
                variants.append((name, S.market_states(A, producer, **spec)['label']))
            variants += [(f'confirmation={c}', S.market_states(A, producer, c)['label']) for c in (2, 4)]
        stability = []
        base = full['label']
        for name, labels in variants:
            stability.append(dict(variant=name, agreement=float(np.mean(base[mask] == labels[mask])),
                by_state={s: (float(np.sum(mask & (base == k) & (labels == k)))/
                    int(np.sum(mask & ((base == k) | (labels == k))))
                    if np.any(mask & ((base == k) | (labels == k))) else None) for k, s in enumerate(regime.NAMES)}))
        # Exhaustive prefix check, not just a handful of convenient cutoffs.
        cuts = []
        with strategy_only():
            for n in np.flatnonzero(mask)+1:
                prefix = dict(days=days[:n], indices={c: {k: v[:n] for k, v in bars.items()}
                                                      for c, bars in A['indices'].items()})
                short = S.market_states(prefix, producer)
                cuts.append(dict(end=str(days[n-1]), ok=bool(np.array_equal(short['label'], base[:n]) and
                    np.array_equal(short['iwm_strong'], full['iwm_strong'][:n]))))
        eps = clipped_episodes(base[mask], days[mask])
        minimum = min(r['agreement'] for r in stability)
        row = dict(spec=full['spec'], spec_sha=full['spec_sha'], calendar=days[mask].tolist(),
            label=base[mask].tolist(), iwm_strong=full['iwm_strong'][mask].tolist(), episodes=eps,
            stability=dict(variants=stability, minimum=minimum, ok=minimum >= .9),
            lookahead=dict(ok=all(r['ok'] for r in cuts), prefix_checks=cuts),
            total_episodes=len(eps), counts={s: dict(days=int(np.sum(base[mask] == k)),
                episodes=sum(e['state'] == s for e in eps)) for k, s in enumerate(regime.NAMES)})
        result[producer] = row
        write(AOUT/f'regimes/{producer}.json', row, True)
    valid = [k for k, r in result.items() if r['stability']['ok'] and r['lookahead']['ok']]
    chosen = min(valid, key=lambda k: (-result[k]['stability']['minimum'], result[k]['total_episodes'],
                                      ('idx_ema', 'smc').index(k))) if valid else None
    selection = dict(chosen=chosen, mode='three_states' if chosen else 'single_state',
        reason='stability descending, episodes ascending, preregistered order; no behaviour/account input',
        summaries={k: dict(minimum=r['stability']['minimum'], episodes=r['total_episodes'],
                          lookahead=r['lookahead']['ok']) for k, r in result.items()},
        prereg_sha256=sha(HOME/'notes/PREREG_P2A_CN.md'), strategy_read_labels=False)
    write(AOUT/'selection.json', selection, True)
    print(json.dumps(selection, ensure_ascii=False), flush=True)


def family(setup):
    text = setup.lower()
    if any(s in text for s in ('pullback', 'reclaim', 'touch', 'bounce')):
        return 'pullback'
    if re.search(r'\bep\b|episodic|gap', text):
        return 'ep'
    if any(s in text for s in ('breakout', 'break', 'inside', 'wick', 'flag')):
        return 'breakout'
    return 'unknown'


def controls():
    quotes = [
        '回调至少到日线 9 EMA；最好是底部里的第一次回调、有更高的低点；9 > 21 且两者靠近；锚定 VWAP（从底部的高点 / 低点或大跳空日锚定）、未补缺口、前高几条支撑重合处最好；21 EMA 回调胜率高于 9 EMA；不买远离均线的、21/50 下行的、在阻力下方的',
        '最看重自己新仓的反馈；其次看 QQQ、IWM 是否在均线上方、是否过度伸展；指数回调到 9/21 EMA 时最该进攻；IWM 跑赢 QQQ 时不容易深跌，少做空']
    return [dict(field='setups', quote=quotes[0], values=dict(up=['breakout', 'ep'], pullback=['pullback'], weak=['pullback'])),
            dict(field='sides', quote=quotes[1], values=dict(up=[1], pullback=[1], weak=[1, -1]))]


def behaviour():
    selection = read(AOUT/'selection.json')  # must precede the first ledger read
    public = ledger.load(source(HOME/'notes/trades.csv'))
    frozen = read(HOME/'notes/legs_frozen.json')
    rules = source(HOME/'notes/RULES_CN.md').read_text()
    output = dict(selected=selection['chosen'], primary_metric='pullback share among classified exact/chart trades',
                  diagnostic_only=selection['chosen'] is None, definitions={})
    for name in ('idx_ema', 'smc'):
        labels = read(AOUT/f'regimes/{name}.json')
        days = labels['calendar']
        observations, rows, window_rows = [], [], []
        for t in public:
            date = t.entry_date or t.window_lo
            if not days[0] <= date <= days[-1]:
                continue
            d = int(np.searchsorted(days, date))
            row = dict(id=t.id, date=date, aligned=days[d], day=d, precision=t.precision, side=t.side,
                       setup=t.setup, family=family(t.setup), state=regime.NAMES[labels['label'][d]], source=t.source)
            if t.dated:
                rows.append(row)
                if row['family'] != 'unknown':
                    observations.append(dict(day=d, value=float(row['family'] == 'pullback')))
            else:
                window_rows.append(row)
        card = pipeline.g2(labels, observations, controls=controls(), rules_text=rules,
            stable=labels['stability'], lookahead=labels['lookahead'], metric=output['primary_metric'], draws=999)
        episodes = []
        for e in labels['episodes']:
            part = [r for r in rows if e['first'] <= r['day'] <= e['last']]
            episodes.append(dict(e, days=e['last']-e['first']+1, trades=len(part),
                density=len(part)/(e['last']-e['first']+1),
                setups=dict(Counter(r['family'] for r in part)), sides=dict(Counter(r['side'] for r in part))))
        stats = {}
        for state in regime.NAMES:
            part = [r for r in rows if r['state'] == state]
            eps = [e for e in episodes if e['state'] == state]
            n_days = sum(e['days'] for e in eps)
            exact = [r for r in part if r['precision'] == 'exact']
            stats[state] = dict(days=n_days, episodes=len(eps), observed_episodes=sum(e['trades'] > 0 for e in eps),
                trades=len(part), density=len(part)/n_days if n_days else None,
                setups=dict(Counter(r['family'] for r in part)), sides=dict(Counter(r['side'] for r in part)),
                exact=dict(n=len(exact), setups=dict(Counter(r['family'] for r in exact)),
                           sides=dict(Counter(r['side'] for r in exact))),
                annual={y: dict(n=sum(r['date'].startswith(y) for r in part),
                    exact=sum(r['date'].startswith(y) for r in exact)) for y in YEARS},
                density_permutation=pipeline.block_permutation([dict(e, value=e['density']) for e in episodes], state, 999),
                holding=dict(status='unobserved', n=0, reason='ledger has no structured trader exit/holding field'),
                g2=card['numbers']['states'][state])
        # Leg exits may be structured, but cannot fill the holding of all ledger trades.
        known = [g for g in frozen['legs'] if g.get('exit_known') is not None]
        output['definitions'][name] = dict(gate=card, states=stats, episodes=episodes, trades=rows,
            window_only=window_rows, structured_leg_exits=len(known),
            holding_note='no trader holding series; do not substitute time-to-peak')
    write(AOUT/'behaviour.json', output, True)
    print('behaviour', {k: {s: r['g2']['status'] for s, r in v['states'].items()}
                         for k, v in output['definitions'].items()}, flush=True)


def array(path):
    return np.load(source(path), mmap_mode='r')


def select_internal(ordered, cooldown=10, maximum=3):
    """The historical IE9 signal's own budget, separate from the S scoring budget."""
    recent, result = [], {}
    for day, codes in ordered.items():
        held = set().union(*recent[-cooldown:]) if recent else set()
        chosen = [c for c in codes if c not in held][:maximum]
        result[day] = chosen
        recent.append(set(chosen))
    return result


def prepare_sources():
    """Sanitize mixed historical metadata in evaluation before market-only replay."""
    read(AOUT/'selection.json')
    mixed = read(GAP/'ie5_work/prepared.json')
    names = read(GAP/'strong_continue_ie4_frozen.json')['raw_feature_names']
    meta = {k: mixed[k] for k in ('days', 'scope', 'first_signal')}
    del mixed
    write(AOUT/'market/ie9_scope.json', meta, True)
    # Raw cached rows are market observations. No Data() constructor is used:
    # those legacy constructors also read the trader's label queries.
    pct = array(GAP/'ie7_work/full_pct.npy')
    features = array(GAP/'ie9_work/full_features.npy')
    feature_names = read(GAP/'ie9_work/full_features.json')['names']
    offset, ordered = 0, {}
    with strategy_only():
        for day, codes in sorted(meta['scope'].items()):
            sl = slice(offset, offset+len(codes))
            offset += len(codes)
            if day < meta['first_signal']:
                continue
            passed = np.ones(len(codes), bool)
            for name, cutoff in (('h4_history', .6), ('adr20', .7), ('option_volume', .8), ('low20', .5)):
                x = pct[sl, names.index(name)]
                passed &= np.where(np.isfinite(x), x >= cutoff, name == 'h4_history')
            kept = np.flatnonzero(passed)
            score = np.nan_to_num(features[sl, feature_names.index('after_inside')][kept], nan=.5) + \
                    np.nan_to_num(features[sl, feature_names.index('near_ema9')][kept], nan=.5)
            order = kept[np.argsort(-score, kind='stable')]
            ordered[day] = [codes[k] for k in order]
        emitted = select_internal(ordered)
    saved = read(HOME/'reports/s0_work/picks/IE9.json')
    comparable = [d for d in emitted if d in saved]
    mismatch = [d for d in comparable if emitted[d] != saved[d]]
    if mismatch:
        write(AOUT/'ie9_replay_mismatch.json', dict(n=len(mismatch), examples=[dict(day=d,
            replay=emitted[d], saved=saved[d], raw=ordered[d][:10]) for d in mismatch[:6]]))
        raise AssertionError('IE9 raw-order replay differs: '+str(len(mismatch)))
    write(AOUT/'market/IE9_order.json', ordered, True)
    # Eligibility/attention uses the original H1 scan, known before the signal day.
    p = {k: array(PANEL/f'{k}.npy') for k in ('raw_close', 'turnover', 'high', 'low')}
    days = array(PANEL/'days.npy')
    codes = array(PANEL/'codes.npy')
    from .t1_research import night_pool
    hpool, attention = {}, {}
    with strategy_only():
        for d in range(len(days)):
            t = d-1
            ix = night_pool(p, t)
            hpool[str(days[d])] = [str(codes[j]) for j in ix]
            money = p['turnover'][t, ix]
            valid = np.isfinite(money)
            ix = ix[valid & (money >= np.quantile(money[valid], .85))] if valid.any() else []
            attention[str(days[d])] = [str(codes[j]) for j in ix]
    write(AOUT/'market/H1A_pool.json', hpool, True)
    write(AOUT/'market/H1A_attention.json', attention, True)
    write(AOUT/'source_replay.json', dict(IE9=dict(exact_saved_order=True, nights=len(comparable),
        internal_cooldown=10, raw_order='after_inside + near_ema9; h4nan gates; stable source order'),
        H1A=dict(order='unchanged S0 raw nominations', pool='original T1 pool with lag1; attention at 85th percentile'),
        strategy_label_reads=False), True)
    print('sources prepared', len(comparable), resources(), flush=True)


def evaluation_inputs():
    frozen = read(HOME/'notes/legs_frozen.json')
    days, codes = array(PANEL/'days.npy'), array(PANEL/'codes.npy')
    assert days.tolist() == frozen['calendar']
    opening = array(PANEL/'open.npy')
    ci = {str(c): j for j, c in enumerate(codes)}
    opens = {c: opening[:, ci[c]] for c in {g['code'] for g in frozen['legs']} if c in ci}
    return frozen, opens


def budget(picks, frozen, opens, K):
    calendar = frozen['calendar']
    indexed = {t: picks.get(day, []) for t, day in enumerate(calendar[:-1])}
    return mainleg.signal_coverage_budget(indexed, None, frozen['legs'], calendar, opens, K)


def diagnostics():
    selected = read(AOUT/'selection.json')
    frozen, opens = evaluation_inputs()
    days, legs = frozen['calendar'], frozen['legs']
    pool_ie = read(AOUT/'market/IE9_order.json')
    pool_h1 = read(AOUT/'market/H1A_pool.json')
    attention = read(AOUT/'market/H1A_attention.json')
    regime_rows = {name: read(AOUT/f'regimes/{name}.json') for name in ('idx_ema', 'smc')}
    by_date = {name: dict(zip(row['calendar'], row['label'])) for name, row in regime_rows.items()}
    output = dict(selected=selected['chosen'], grouping='single state' if not selected['chosen'] else selected['chosen'], sources={})
    for name, pool in (('IE9', pool_ie), ('H1A_signals', pool_h1)):
        picks = read(HOME/f'reports/s0_work/picks/{name}.json')
        result = budget(picks, frozen, opens, 3)
        expected = read(HOME/f'reports/s0_work/systems/{name}.json')['results']['3']
        assert {y: result['annual'][y] for y in YEARS} == expected['annual']
        assert result['per_leg'] == expected['per_leg']
        misses, last = [], {}
        history = {}
        for t, cs in result['picks'].items():
            history[t] = dict(last)
            for c in cs:
                last[c] = t
        for g, covered in zip(legs, result['per_leg']):
            if covered['covered']:
                continue
            code, rows = g['code'], []
            for t in range(max(0, g['first']-4), min(g['peak']-1, len(days)-1)):
                day = days[t]
                price = float(opens[code][t+1]) if code in opens else np.nan
                share = (g['top']/price-1)/g['gain'] if np.isfinite(price) and price > 0 else None
                qualified = share is not None and share >= .5-1e-12
                order = picks.get(day, []) if name != 'IE9' else pool.get(day, [])
                inpool, emitted = code in pool.get(day, []), code in picks.get(day, [])
                before = history[t].get(code)
                cooling = before is not None and t-before <= 10
                internal_last = max((u for u in range(max(0, t-10), t)
                                     if code in picks.get(days[u], [])), default=None)
                internal = name == 'IE9' and inpool and not emitted and internal_last is not None
                actual = result['picks'].get(t, [])
                if not qualified:
                    reason = 'missing_open' if share is None else 'too_late'
                elif not inpool:
                    reason = 'out_of_pool'
                elif emitted and cooling:
                    reason = 'S_cooldown'
                elif internal:
                    reason = 'source_cooldown'
                elif code not in order:
                    reason = 'no_native_signal'
                else:
                    reason = 'ranking'
                rows.append(dict(night=t, day=day, next_day=days[t+1], qualified=qualified, share=share,
                    state='single' if not selected['chosen'] else regime.NAMES[by_date[selected['chosen']].get(day, 1)],
                    diagnostic_states={n: regime.NAMES[m.get(day, 1)] for n, m in by_date.items()},
                    in_pool=inpool, attention=(code in attention.get(day, [])) if name != 'IE9' else None,
                    raw_rank=order.index(code)+1 if code in order else None,
                    native_rank=picks.get(day, []).index(code)+1 if emitted else None,
                    selected=actual, displaced_by=actual if code not in actual else [],
                    S_last=before, source_last=internal_last, source_cooldown=internal,
                    S_cooldown=cooling, reason=reason))
            q = [r for r in rows if r['qualified']]
            reasons = Counter(r['reason'] for r in q)
            if not q:
                main = 'window_unreachable'
            elif any(r['reason'] in ('ranking', 'S_cooldown', 'source_cooldown') for r in q):
                candidates = {k: reasons[k] for k in ('ranking', 'S_cooldown', 'source_cooldown') if reasons[k]}
                main = max(candidates, key=candidates.get)
            elif reasons['no_native_signal']:
                main = 'no_native_signal'
            else:
                main = 'out_of_pool'
            past = [days[t] for t in result['picks'] if t < max(0, g['first']-4) and code in result['picks'][t]]
            late = [r['day'] for r in rows if not r['qualified'] and code in picks.get(r['day'], [])]
            misses.append(dict(key=g['key'], code=code, year=days[g['first']][:4], first=days[g['first']],
                peak=days[g['peak']], precision=g.get('precision'), censored=g.get('censored'), main_layer=main,
                group_state=q[0]['state'] if q else 'unreachable', qualified_nights=len(q), reasons=dict(reasons),
                last_premature=next(reversed(past), None), first_late=next(iter(late), None), nights=rows))
        grouping = {}
        for state in ('single', 'up', 'pullback', 'weak', 'unreachable'):
            part = [g for g in misses if g['group_state'] == state]
            if part:
                grouping[state] = dict(n=len(part), layers=dict(Counter(g['main_layer'] for g in part)))
        output['sources'][name] = dict(exact_s0=True, coverage={y: result['annual'][y] for y in YEARS},
            missing=len(misses), main_layers=dict(Counter(g['main_layer'] for g in misses)),
            by_state=grouping, nightly_states={n: dict(Counter(r['diagnostic_states'][n] for g in misses
                for r in g['nights'] if r['qualified'])) for n in by_date}, misses=misses)
    miss_sets = {n: {g['key'] for g in r['misses']} for n, r in output['sources'].items()}
    ie, h = miss_sets['IE9'], miss_sets['H1A_signals']
    output['overlap'] = dict(both=sorted(ie & h), IE9_only=sorted(ie-h), H1A_only=sorted(h-ie),
                             either=sorted(ie|h), union_K3_covered=48-len(ie & h))
    raw = {n: read(HOME/f'reports/s0_work/picks/{n}.json') for n in ('IE9', 'H1A_signals')}
    bounds = {n: [] for n in ('data_window', 'IE9_pool', 'H1A_pool', 'IE9_native', 'H1A_native', 'native_union', 'raw_union')}
    for g in legs:
        code = g['code']
        nights = [t for t in range(max(0, g['first']-4), min(g['peak']-1, len(days)-1))
                  if code in opens and np.isfinite(opens[code][t+1]) and opens[code][t+1] > 0 and
                  (g['top']/opens[code][t+1]-1)/g['gain'] >= .5-1e-12]
        ip = any(code in pool_ie.get(days[t], []) for t in nights)
        hp = any(code in pool_h1.get(days[t], []) for t in nights)
        a = any(code in raw['IE9'].get(days[t], []) for t in nights)
        b = any(code in raw['H1A_signals'].get(days[t], []) for t in nights)
        for name, possible in dict(data_window=bool(nights), IE9_pool=ip, H1A_pool=hp,
                                  IE9_native=a, H1A_native=b, native_union=a or b, raw_union=ip or b).items():
            bounds[name].append(dict(key=g['key'], year=days[g['first']][:4], possible=possible))
    output['upper_bounds'] = {n: dict(total=sum(r['possible'] for r in rows), n=48,
        annual={y: dict(n=sum(r['year'] == y for r in rows), possible=sum(r['possible'] for r in rows if r['year'] == y))
                for y in YEARS}, per_leg=rows, note='optimistic, unlimited width and no cooldown; not a feasible K=3 schedule')
        for n, rows in bounds.items()}
    write(AOUT/'diagnostics.json', output, True)
    print('diagnostics', {n: r['main_layers'] for n, r in output['sources'].items()},
          'joint_misses', len(ie & h), flush=True)


LAYER_CN = dict(out_of_pool='资格池外', no_native_signal='池内无原生信号', source_cooldown='源内部10日冷却',
                S_cooldown='S口径10日冷却', ranking='排序/原生截断', window_unreachable='时窗不可达')


def pct(value):
    return '缺失' if value is None else f'{value:.1%}'


def protected_check():
    manifest = read(AOUT/'protocol.json')['protected']
    changed = [p for p, h in manifest.items() if not (ROOT/p).is_file() or sha(ROOT/p) != h]
    assert not changed, changed[:10]
    return dict(ok=True, files=len(manifest), changed=[])


def report_a():
    selection = read(AOUT/'selection.json')
    b, d = read(AOUT/'behaviour.json'), read(AOUT/'diagnostics.json')
    lines = ['# P2A：行情定义与信号漏点', '',
        '两种真实 QQQ＋3 日确认的定义都未通过90%稳定性线，不能启用为合格 Switch。'
        'QQQ-EMA 最低87.45%，QQQ-SMC 最低85.59%；逐日截断一致，但参数稍变仍会换态。'
        'B段据任务书按单一状态继续。此结论先于读取本人行为写入 selection.json，之后没有换定义。', '',
        'IE9的20个漏段，主要停在排序/原生前三截断（14段），另有源内部冷却5段、资格池外1段；'
        'H1A的25个漏段，主要是池内没有原生信号（16段），另有排序7段、S冷却2段。'
        '两源共同漏14段，并非完全互补。这里按合格夜走到的最远环节归类，不能当作单独修改该层必能补回的因果结论。', '',
        '本段只读信号。没有运行分配、交易、账户研究；没有改登记版、看板或旧结果。', '',
        '## 行情定义', '',
        '指数来自本地登记的 martin-luk-benchmarks-v1，QQQ真实收盘/高低价，IWM/QQQ过去21日相对强弱为辅助。'
        '2022起暖机，统计2024-01-02至2026-10-16共701日。状态用于交易日t，只读至t−1；新态连续3日才生效，不回填。', '',
        '| 定义 | up天/段 | pullback天/段 | weak天/段 | 总段 | 最低日重合 | 截断 |',
        '|---|---:|---:|---:|---:|---:|---|']
    for n in ('idx_ema', 'smc'):
        r = read(AOUT/f'regimes/{n}.json')
        lines.append('| '+n+'+c3 | '+' | '.join(f"{r['counts'][s]['days']}/{r['counts'][s]['episodes']}" for s in regime.NAMES)+
                     f" | {r['total_episodes']} | {pct(r['stability']['minimum'])} | 701个前缀全部一致 |")
    lines += ['', 'EMA：低于EMA50为weak，否则高于EMA21×1.01为up，其余pullback。SMC沿用P1左右各10根分形与确认后的BOS/CHoCH。'
        '确认期虽减少段数，但EMA的带宽0.5%扰动仍只有87.87%重合，单凭P1扰动口径也不过；'
        '纳入预登记的确认期2/4日后最低87.45%。SMC分形12根为85.59%。没有因失败补试第三个版本。', '',
        '全部日标签、episode、逐项扰动及SHA见 regimes/；IWM辅助也逐日前缀一致。因无合格定义，'
        '正式漏点分组只有single；两种失败定义的逐夜状态另留作诊断，不据此开关或排序。', '',
        '## G2逐状态行为', '',
        '以下全是失败定义上的描述，不能冒充已通过G2。主指标在看行为前固定为已分类exact/chart交易的回调比例，'
        '其余形态、方向、密度及exact分列；999次整段置换、全部episode留一。样本不足标未观测。', '',
        '| 定义/状态 | 全部交易/有交易段 | 已分类/有分类段 | 突破/回调/EP/未知 | 多/空 | 每日密度 | 主检验p | 同向留一段 | 行为判定 |',
        '|---|---:|---:|---:|---:|---:|---:|---:|---|']
    for n, definition in b['definitions'].items():
        for state, r in definition['states'].items():
            g = r['g2']; v = g['numbers']
            lines.append(f"| {n}/{state} | {r['trades']}/{r['observed_episodes']} | {v['trades']}/{v['observed_episodes']} | "+
                '/'.join(str(r['setups'].get(k, 0)) for k in ('breakout', 'pullback', 'ep', 'unknown'))+' | '+
                '/'.join(str(r['sides'].get(k, 0)) for k in ('long', 'short'))+
                f" | {r['density']:.3f} | {v.get('p', '—')} | {v['leave_one_same_direction']} | {g['status']} |")
    lines += ['', 'EMA三态的主行为检验均fail，回调态的回调比例反而低于其他态；SMC上升/回调态均fail，'
        'weak只有9笔已分类交易、2个有分类交易段，标未观测。未观测不是通过，定义稳定性未过仍不能启用。', '',
        '台账没有结构化本人退出或持有天数字段，持有期逐状态均缺失；没有用到峰值的天数代填。'
        '原始setup、透明分类、精度、分年方向与形态、窗口记录、密度置换、每个episode的训练/留出数字见 behaviour.json。'
        '2024–25弱态也照实报：EMA为0/7笔，SMC为0/1笔，未把缺样本写成稳定行为。', '',
        '无样本状态保留的规则仅为待验证解释，最多两个开关：形态家族与方向，逐字原话、来源和映射见 PREREG_P2A_CN.md。'
        '其中「不买远离均线的、21/50 下行的、在阻力下方的」约束弱态多头背景；'
        '「IWM 跑赢 QQQ 时不容易深跌，少做空」保留弱态方向解释。它们没有被执行或宣称已复刻。', '',
        '## 逐段、逐晚漏点', '',
        'S0年度各格与逐段记录精确一致，IE9的K=3覆盖为3/9、14/22、11/17；H1A为4/9、8/22、11/17。'
        '2024/2025为历史样本内，2026为留出*；宽度为K=3，原生点名与S评分均保持原顺序。', '',
        '| 源 | 年份 | 股票/首锚点 | 主层 | 合格夜数 |', '|---|---|---|---|---:|']
    for name, r in d['sources'].items():
        for g in r['misses']:
            lines.append(f"| {name} | {g['year']} | {g['code']} / {g['first']} | {LAYER_CN[g['main_layer']]} | {g['qualified_nights']} |")
    lines += ['', '每一晚的池内/池外、完整原排名、原生排名、实际新名（至多3只）、挤出票、'
        '源内部及S冷却上次点名日、是否已经太晚和失败行情标签，均在 diagnostics.json 与 miss_nights.csv。'
        'first−3至peak−1之间不够一半剩余幅度的夜也保留。IE9原生名额最多3只，没有为诊断扩充第四只。', '',
        'H1A「池内无原生信号」可能同时涉及注意力门槛、形态、市场过滤或原止损有效性，'
        '本段不把它擅自归成单一新特征，也没有据漏段拟合。逐夜attention布尔另存，可复核其与资格池的区别。', '',
        '两源K=3共同覆盖的并集为34/48，这只是两个原系统命中集合的并集，不能作为新合并系统的覆盖或可达上限。'
        '共同漏的14段，以及IE9独漏6段、H1A独漏11段，完整键见 overlap。', '',
        '## 开B前的上限', '',
        '以下均忽略排序预算与冷却，是必要条件的乐观上限，不能当作K=3可实现成绩。', '',
        '| 层 | 2024 | 2025 | 2026 | 三年 |', '|---|---:|---:|---:|---:|']
    for name, r in d['upper_bounds'].items():
        lines.append('| '+name+' | '+' | '.join(f"{r['annual'][y]['possible']}/{r['annual'][y]['n']}" for y in YEARS)+
                     f" | {r['total']}/48 |")
    lines += ['', 'native_union只合并两源实际原生点名；raw_union允许IE9原资格池内的完整原排名（未加其内部名额/冷却），'
        '并合并H1A原生信号；两者不能互换。事件、不可达和截断段都保留在48段分母。', '',
        '## 工件与复算', '',
        '入口：`p2_research.py freeze → regimes → behaviour → prepare_sources → diagnostics → report_a`。'
        '每一步使用任务书指定systemd scope和单线程.venv。source_replay核对IE9的701晚实际顺序；'
        'S0两源年度与逐段记录精确复核通过。完整测试在B结束后统一执行，日志和最终结果登记于两段completion.json。', '',
        '预登记未改；未联网、未拉新数据、未提交Git。来源SHA、资源、保护检查和阶段完成记录在本工件目录。']
    (HOME/'reports/P2A_CN.md').write_text('\n'.join(lines)+'\n')
    fields = ('source', 'leg', 'day', 'next_day', 'qualified', 'state', 'reason', 'in_pool',
              'raw_rank', 'native_rank', 'selected', 'displaced_by', 'source_last', 'S_last', 'share')
    with (AOUT/'miss_nights.csv').open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fields)
        writer.writeheader()
        for name, record in d['sources'].items():
            for g in record['misses']:
                for r in g['nights']:
                    row = {k: r[k] for k in fields if k not in ('source', 'leg')}
                    for k in ('selected', 'displaced_by'):
                        row[k] = ' '.join(row[k])
                    writer.writerow(dict(source=name, leg=g['key'], **row))
    write(AOUT/'protected_check.json', protected_check())
    write(AOUT/'completion.json', dict(task='PLAN_P2_CN/A', status='complete', research_complete=True,
        tests='pending final three-suite verification after B', producer=None, G2='fail: no stable definition',
        report_sha256=sha(HOME/'reports/P2A_CN.md'), prereg_sha256=sha(HOME/'notes/PREREG_P2A_CN.md'),
        diagnostics_complete=True, S0_exact=True, no_accounts=True, no_allocation_research=True,
        offline=True, downloaded_data=False, workspace_git_commits=0, registry_or_board_modified=False,
        resources=resources()), True)
    print('P2A report and completion written', flush=True)


def freeze_b():
    a = read(AOUT/'completion.json')
    assert a['status'] == 'complete' and a['report_sha256'] == sha(HOME/'reports/P2A_CN.md')
    assert read(AOUT/'selection.json')['chosen'] is None
    spec = read(HOME/'notes/rounds/P2B.json')
    validation = pipeline.validate_round(spec, spec['base'])
    files = [HOME/'notes/PREREG_P2B_CN.md', HOME/'notes/rounds/P2B.json',
        HOME/'p2_signal.py', HOME/'p2_research.py', HOME/'reports/P2A_CN.md', AOUT/'selection.json',
        BOUT/'A_completion_at_start.json', AOUT/'diagnostics.json', AOUT/'source_replay.json',
        AOUT/'market/IE9_order.json', AOUT/'market/H1A_pool.json',
        HOME/'reports/s0_work/picks/IE9.json', HOME/'reports/s0_work/picks/H1A_signals.json',
        HOME/'notes/legs_frozen.json', ROOT/'studies/trader_replication/mainleg.py']
    files += [PANEL/f'{name}.npy' for name in ('days', 'codes', 'close', 'open')]
    write(BOUT/'A_completion_at_start.json', a, True)
    write(BOUT/'protocol.json', dict(task='PLAN_P2_CN/B', A_completed_before_B=True, phase_validation=validation,
        A_completion_sha256_at_start=sha(AOUT/'completion.json'),
        frozen={str(p.relative_to(ROOT)): sha(p) for p in files}, state_mode='single', layer='signal',
        selection_years=['2024', '2025'], holdout='2026 historical holdout*',
        source_only=True, no_accounts=True, resources=resources()), True)
    print('B protocol frozen', validation, flush=True)


def frozen_b():
    protocol = read(BOUT/'protocol.json')
    for p, h in protocol['frozen'].items():
        assert sha(ROOT/p) == h, 'B frozen input changed: '+p
    return read(HOME/'notes/rounds/P2B.json')


def score_signals(picks, frozen, opens, years=YEARS):
    out = {}
    for K in (1, 3, 5, None):
        r = budget(picks, frozen, opens, K)
        r.pop('picks')
        r['annual'] = {y: r['annual'][y] for y in years}
        rows = r['annual'].values()
        total_n, hits = sum(r['n'] for r in rows), sum(r['covered'] for r in rows)
        new_names, nights = sum(r['new_names'] for r in rows), sum(r['nights'] for r in rows)
        shares = [g['first_hit']['share'] for g in r['per_leg'] if g['covered']]
        r['total'] = dict(n=total_n, covered=hits, coverage=hits/total_n if total_n else None,
            mean_new_names=new_names/nights if nights else None,
            precision=sum(r['precision_hits'] for r in rows)/new_names if new_names else None,
            remaining_share_median=float(np.median(shares)) if shares else None)
        out['unlimited' if K is None else str(K)] = r
    return out


def train_b():
    spec = frozen_b()
    # Freeze one signal artifact per candidate before opening any 2026 leg outcomes.
    st = S.P2Signals()
    with strategy_only():
        A = st.arrays()
        from studies.trader_replication.config import Config
        signals, prefix = {}, {}
        for name, change in spec['candidates'].items():
            cfg = Config(pipeline._merge(spec['base'], change))
            pool = st.universe(A, cfg)
            picks = st.signal(A, pool, cfg)
            assert set(picks) == set(range(len(A['days'])))
            assert all(len(cs) == len(set(cs)) <= 5 for cs in picks.values())
            signals[name] = {str(A['days'][t]): cs for t, cs in picks.items() if t < len(A['days'])-1}
            checks = []
            for cut in ('2024-09-30', '2025-09-30', '2026-06-30'):
                n = int(np.searchsorted(A['days'], cut, side='right'))
                view = dict(A, days=A['days'][:n], eligible=pool[:n], close=A['close'][:n])
                short = st.signal(view, st.universe(view, cfg), cfg)
                checks.append(dict(cut=cut, ok=all(short[t] == picks[t] for t in range(n-1))))
            assert all(r['ok'] for r in checks)
            prefix[name] = checks
    for name, picks in signals.items():
        write(BOUT/f'picks/{name}.json', picks, True)
    write(BOUT/'signal_checks.json', dict(prefix=prefix, unknown_source_names=A['unknown_source_names'],
        native_max=5, no_strategy_labels=True, no_trade_calls=True), True)
    frozen, opens = evaluation_inputs()
    train = dict(frozen, legs=[g for g in frozen['legs'] if frozen['calendar'][g['first']][:4] in YEARS[:2]])
    results = {}
    for name, picks in signals.items():
        results[name] = score_signals(picks, train, opens, YEARS[:2])
        write(BOUT/f'train/{name}.json', results[name], True)
    def key(name):
        r = results[name]
        coverage = min(r['3']['annual'][y]['coverage'] for y in YEARS[:2])
        good_width = all(r['unlimited']['annual'][y]['mean_new_names'] <= 5 for y in YEARS[:2])
        return (not good_width, -coverage, r['unlimited']['total']['mean_new_names'], list(results).index(name))
    chosen = min(results, key=key)
    write(BOUT/'chosen.json', dict(chosen=chosen, keys={name: key(name) for name in results},
        selection_years=list(YEARS[:2]), used_2026_leg_metrics=False,
        signal_sha={name: sha(BOUT/f'picks/{name}.json') for name in results},
        prereg_sha256=sha(HOME/'notes/PREREG_P2B_CN.md'), source_sha256=sha(HOME/'p2_signal.py')), True)
    print('B chosen before holdout', chosen, {n: key(n) for n in results}, flush=True)


def validate_b():
    spec = frozen_b()
    selected = read(BOUT/'chosen.json')
    write(BOUT/'validation_started.json', dict(chosen_sha256=sha(BOUT/'chosen.json'),
        source_sha256=sha(HOME/'p2_signal.py'), prereg_sha256=sha(HOME/'notes/PREREG_P2B_CN.md')), True)
    frozen, opens = evaluation_inputs()
    results = {}
    for name in spec['candidates']:
        assert sha(BOUT/f'picks/{name}.json') == selected['signal_sha'][name]
        picks = read(BOUT/f'picks/{name}.json')
        r = score_signals(picks, frozen, opens)
        trained = read(BOUT/f'train/{name}.json')
        for K in ('1', '3', '5', 'unlimited'):
            for y in YEARS[:2]:
                # Precision groups by signal year, so December names can gain
                # correct labels when next year's legs are revealed. Coverage
                # and the width used for selection must remain exactly equal.
                for field, value in trained[K]['annual'][y].items():
                    if field not in ('precision', 'precision_hits'):
                        assert r[K]['annual'][y][field] == value, (name, K, y, field)
            assert [g for g in r[K]['per_leg'] if g['year'] in YEARS[:2]] == trained[K]['per_leg']
        results[name] = r
        write(BOUT/f'results/{name}.json', r, True)
    name = selected['chosen']
    picks = read(BOUT/f'picks/{name}.json')
    indexed = {t: picks.get(day, []) for t, day in enumerate(frozen['calendar'][:-1])}
    gate = pipeline.g3({'2026': dict(picks=indexed, trained_years=['2024', '2025'],
        model_sha=selected['signal_sha'][name], sample='留出*；历史反复查看，非独立样本外')},
        frozen['legs'], frozen['calendar'], opens, upper_bound=1.)
    write(BOUT/'G3.json', dict(gate=gate, three_year_fixed_replay={n: {y: r['3']['annual'][y] for y in YEARS}
        for n, r in results.items()}, missing_year_models=['2024', '2025'],
        no_new_fits=True, note='Fixed yearly replay is not three separately held-out fitted models'), True)
    # Optimistic reachability before cooldown is a bound. The realized K=None
    # result is NOT a bound on K=3: a different K changes its cooldown history.
    diag = read(AOUT/'diagnostics.json')
    raw_ie = read(AOUT/'market/IE9_order.json')
    hpool = read(AOUT/'market/H1A_pool.json')
    actual = budget(picks, frozen, opens, 3)
    per_leg = []
    for g, row in zip(frozen['legs'], actual['per_leg']):
        code, days = g['code'], frozen['calendar']
        nights = [t for t in range(max(0, g['first']-4), min(g['peak']-1, len(days)-1))
            if code in opens and np.isfinite(opens[code][t+1]) and opens[code][t+1] > 0 and
            (g['top']/opens[code][t+1]-1)/g['gain'] >= .5-1e-12]
        pool = any(code in raw_ie.get(days[t], []) or code in hpool.get(days[t], []) for t in nights)
        native = any(code in picks.get(days[t], []) for t in nights)
        before = [t for t in actual['picks'] if code in actual['picks'][t] and t < max(0, g['first']-4)]
        cooling, displaced = [], []
        for t in nights:
            if code not in picks.get(days[t], []):
                continue
            earlier = [u for u in actual['picks'] if u < t and code in actual['picks'][u]]
            prev = max(earlier, default=None)
            if prev is not None and t-prev <= 10:
                cooling.append(dict(day=days[t], previous=days[prev]))
            elif code not in actual['picks'][t]:
                displaced.append(dict(day=days[t], rank=picks[days[t]].index(code)+1,
                                      by=actual['picks'][t]))
        reason = 'covered' if row['covered'] else 'data_window' if not nights else 'out_of_pool' if not pool else (
            'native_five' if not native else 'S_cooldown' if cooling and not displaced else 'K3_ranking')
        per_leg.append(dict(row, first=days[g['first']], peak=days[g['peak']], precision=g['precision'],
            duration=g['duration'], data_window=bool(nights), universe=pool, native_no_cooldown=native,
            reason=reason, cooldown=cooling, displaced=displaced, last_premature=days[max(before)] if before else None))
    upper = {}
    for y in YEARS:
        rows = [g for g in per_leg if g['year'] == y]
        upper[y] = dict(n=len(rows), data_window=sum(g['data_window'] for g in rows),
            universe=sum(g['universe'] for g in rows), native_no_cooldown=sum(g['native_no_cooldown'] for g in rows),
            K3=sum(g['covered'] for g in rows), misses=dict(Counter(g['reason'] for g in rows if not g['covered'])))
    write(BOUT/'selected_diagnosis.json', dict(chosen=name, upper_bounds=upper, per_leg=per_leg,
        source_ceiling=diag['upper_bounds']['IE9_pool' if name == 'B2_RAW_IE9' else
            'native_union' if name == 'B1_NATIVE_ZIP' else 'raw_union'],
        note='native_no_cooldown is optimistic; unlimited-with-cooldown is a separate realized schedule'), True)
    print('B validation', selected['chosen'], {n: {y: r['3']['annual'][y]['covered'] for y in YEARS}
                                              for n, r in results.items()}, flush=True)


def report_b():
    frozen_b()
    selected = read(BOUT/'chosen.json')
    name = selected['chosen']
    records = {n: read(BOUT/f'results/{n}.json') for n in read(HOME/'notes/rounds/P2B.json')['candidates']}
    chosen = records[name]
    diagnosis = read(BOUT/'selected_diagnosis.json')
    gate = read(BOUT/'G3.json')['gate']
    main = chosen['3']['annual']['2026']
    gap = max(0., .8-main['coverage'])
    def cell(row):
        return f"{row['covered']}/{row['n']}（{pct(row['coverage'])}）"
    lines = ['# P2B：五个固定信号候选', '',
        f"按预登记2024/2025较差年覆盖选中 **{name}**。2026留出*的K=3早期覆盖为{cell(main)}，"
        f"距80%还差{gap*100:.1f}个百分点；同冷却不限K的每晚新名均数为"
        f"{chosen['unlimited']['annual']['2026']['mean_new_names']:.2f}。"
        +('信号主留出覆盖未达标，不能进入交易期。' if main['coverage'] < .8 else
          '主留出数值达到80%；外折证据缺口与G2失败仍须单独报告，本轮没有进入交易期。'), '',
        'A段没有合格行情定义，五个候选全部用单一状态。只通过facade的universe/signal生成点名，'
        '没有调用build、allocate、trade或账户；运行入口会拒绝这些调用。没有新增特征、拟合分数或改候选。', '',
        '2024/2025为历史样本内，2026为留出*：此年份早已被多轮查看，A段也只读诊断过，不能称独立样本外。'
        '首选先写入chosen.json，再一次性揭示五个冻结候选的2026；没有按2026结果换首选。', '',
        '## 三年全表', '',
        '每个候选每晚原生最多5只；S先剔除过去10交易日实际点过的名字，再取K。'
        '2023暖机、空夜、跨年冷却及跨年合格夜保留；分母固定48段（9/22/17）。'
        '2025末段可在2026初命中，归首锚点年，这不构成全新独立留出。', '',
        '| 候选 | K=3：2024样本内 | K=3：2025样本内 | K=3：2026留出* | 较差选择年 |',
        '|---|---:|---:|---:|---:|']
    for n, r in records.items():
        annual = r['3']['annual']
        lines.append('| '+n+('（首选）' if n == name else '')+' | '+' | '.join(cell(annual[y]) for y in YEARS)+
                     ' | '+pct(min(annual[y]['coverage'] for y in YEARS[:2]))+' |')
    lines += ['', '以下所有三项并列数依次为2024、2025、2026，样本标记与上表相同。'
        '精度为点名落在任一合格段夜的比例，仅作诊断。剩余为首次合格点名相对首锚点总幅的比例，不是账户收益。', '',
        '| 候选 | K=1覆盖 | K=5覆盖 | 不限K覆盖 | 不限K新名/夜 | K=3新名/夜 | K=3精度 | 剩余比例中位 | 不同票K=3 |',
        '|---|---|---|---|---|---|---|---|---|']
    for n, r in records.items():
        cells = [n]
        for k in ('1', '5', 'unlimited'):
            cells.append(' · '.join(f"{r[k]['annual'][y]['covered']}/{r[k]['annual'][y]['n']}" for y in YEARS))
        for k, field in (('unlimited', 'mean_new_names'), ('3', 'mean_new_names'), ('3', 'precision'),
                         ('3', 'remaining_share_median'), ('3', 'unique_names')):
            values = [r[k]['annual'][y][field] for y in YEARS]
            cells.append(' · '.join('缺失' if v is None else pct(v) if field in ('precision', 'remaining_share_median')
                                   else str(v) if field == 'unique_names' else f'{v:.2f}' for v in values))
        lines.append('| '+' | '.join(cells)+' |')
    lines += ['', '不限K也保留10日冷却。K不同会改变后续冷却，K=5及不限K不能当作K=3成绩的单调上限。'
        '原生最多5只是冻结的信号宽度，未改S评测K。各年原始名单均数与精度分母、首次合格夜、全部段和四种预算在results/。', '',
        '## 候选与选择约束', '',
        'B1只交错原生两源，属于已知2024上限不足的对照。B2去掉IE9源内部名额/冷却，用原资格池中的原排序；'
        'B3把它与H1A成组信号交错；B4题材先点；B5把当晚共同出现的票先按H1A顺序点。'
        '只有合并顺序和源内部截断发生变化，没有读本人台账或段标签来点名。', '',
        '选择键为：两年不限K宽度均≤5；2024/2025较差年K=3覆盖最高；再比两年合并不限K新名均数更低；'
        '最后按预登记列序。精度、剩余幅度与2026都不参与。原生/完整源点名、源码和A段报告在跑B前以SHA冻结。', '',
        '三年固定信号重放数字不等于三套完整留年模型。pipeline.G3的2024/2025外折模型缺失，标未观测，'
        f"2026为{gate['numbers']['folds']['2026']['status']}，整体G3为{gate['status']}；没有重拟合填格子。"
        '这不改写A段G2失败，也不把本轮探索当作可登记系统。', '',
        '## 首选的可达上限与卡点', '',
        'data_window、universe、原生5只（无S冷却）是乐观可达上限；不限K另按真实冷却评测，不能替换上限。', '',
        '| 首锚点年 | 数据/时窗 | 资格池 | 原生5只无冷却 | 实际K=3 | 距80% |',
        '|---|---:|---:|---:|---:|---:|']
    for y, r in diagnosis['upper_bounds'].items():
        lines.append(f"| {y} | {r['data_window']}/{r['n']} | {r['universe']}/{r['n']} | "
            f"{r['native_no_cooldown']}/{r['n']} | {r['K3']}/{r['n']} | {max(0., .8-r['K3']/r['n'])*100:.1f}个百分点 |")
    lines += ['', '原资格池的乐观上限见A段：IE9为47/48，H1A扫描池为48/48；'
        '只合并原生两源的上限为37/48，2024仅5/9。解除源截断打开上限，并不保证原前5的排序已找到这些段。'
        '若原生5只无冷却也低于80%，继续改交易名额、止损或离场补不回这层遗漏。', '',
        '| 未覆盖段 | 年份 | 层 |', '|---|---|---|']
    for row in diagnosis['per_leg']:
        if not row['covered']:
            lines.append(f"| {row['code']} / {row['first']} | {row['year']} | {row['reason']} |")
    lines += ['', 'native_five表示当晚排序截到5只之后已没有合格早期点名；S_cooldown表示有点名却因过去10日已点而跳过；'
        'K3_ranking表示合格原生点名被前三预算挤掉（逐夜也保留混合冷却原因）。'
        'selected_diagnosis.json给出上次过早点名、冷却日与挤出票，不为单段加例外。', '',
        '## 分母检查', '', '| 年份/分组 | K=3覆盖 |', '|---|---:|']
    for y in YEARS:
        rows = [r for r in diagnosis['per_leg'] if r['year'] == y]
        groups = dict(all=rows, uncensored=[r for r in rows if not r['censored']],
            event=[r for r in rows if r['duration'] < 5], swing=[r for r in rows if r['duration'] >= 5])
        groups.update({p: [r for r in rows if r['precision'] == p] for p in ('exact', 'chart', 'window')})
        for group, part in groups.items():
            lines.append(f"| {y}/{group} | {sum(r['covered'] for r in part)}/{len(part)} |")
    lines += ['', '主表保留事件与截断段。2026被截断的PANW、CRCL没有被静默删除；无独立退出信息不代填持有期。', '',
        '## 复算与验证', '',
        'A完成 → 冻结PREREG_P2B/round → freeze_b → train_b（先落盘首选）→ validate_b（一次历史留出*）→ report_b。'
        '统一入口为 `p2_research.py`，信号实现为 `p2_signal.P2Signals`，各阶段通过规定systemd scope运行。'
        '三组完整测试、源码与数据SHA、无标签读取、前缀一致及保护检查写入completion.json与tests/。', '',
        '报告至此没有交易期研究、账户模拟、网络访问、下载、登记或看板修改，也没有Git提交。']
    (HOME/'reports/P2B_CN.md').write_text('\n'.join(lines)+'\n')
    write(BOUT/'completion.json', dict(task='PLAN_P2_CN/B', status='research_complete', chosen=name,
        yearly_K3={y: chosen['3']['annual'][y] for y in YEARS}, G3=gate['status'],
        report_sha256=sha(HOME/'reports/P2B_CN.md'), tests='pending final three suites',
        no_accounts=True, no_allocation_research=True, offline=True, downloaded_data=False,
        workspace_git_commits=0, registry_or_board_modified=False, resources=resources()), True)
    print('P2B research report written', name, flush=True)


def finish():
    frozen_b()
    tests = {}
    for suite in ('custody', 'trader_replication', 'martin_luk'):
        path = BOUT/f'tests/{suite}.log'
        text = path.read_text()
        match = re.search(r'Ran (\d+) tests? in ([\d.]+)s', text)
        code = int((BOUT/f'tests/{suite}.exit').read_text().strip())
        assert code == 0 and match and re.search(r'^OK(?:\s|$)', text, re.M), (suite, code, text[-1000:])
        tests[suite] = dict(tests=int(match[1]), seconds=float(match[2]), exit_code=code,
                            log=str(path.relative_to(ROOT)), sha256=sha(path))
    check = protected_check()
    assert sha(HOME/'notes/PREREG_P2A_CN.md') == read(AOUT/'protocol.json')['prereg_sha256']
    initial = read(AOUT/'diagnostics_initial.json')
    final = read(AOUT/'diagnostics.json')
    assert initial['sources'] == final['sources']
    comparable = {k: v for k, v in initial['overlap'].items() if k != 'union_source_ceiling'}
    assert comparable == {k: v for k, v in final['overlap'].items() if k != 'union_K3_covered'}
    # Record the names corrected in our own preliminary diagnostic artifact;
    # no candidate, source order or coverage was changed by this correction.
    correction = dict(initial_sha256=sha(AOUT/'diagnostics_initial.json'),
        final_sha256=sha(AOUT/'diagnostics.json'), same_source_rows=True,
        clarification='union of K=3 hit sets renamed union_K3_covered; real no-cooldown bounds added before B')
    write(AOUT/'diagnostic_clarification.json', correction)
    source_hashes = {str(p.relative_to(ROOT)): sha(p) for p in
        (HOME/'p2_signal.py', HOME/'p2_research.py', HOME/'tests/test_p2_signal.py')}
    for destination in (AOUT, BOUT):
        record = read(destination/'completion.json')
        record.update(status='complete', tests=tests, protected=check, sources=source_hashes,
                      resources_final=resources())
        write(destination/'completion.json', record)
        write(destination/'sources.json', {k: v for run in (destination/'runs').glob('*.json')
            for k, v in read(run).get('sources', {}).items()})
    selected = read(BOUT/'chosen.json')['chosen']
    stats = read(BOUT/f'results/{selected}.json')
    cover = [stats['3']['annual'][y] for y in YEARS]
    print('A、B已完成；未联网、未下载、未提交Git、未进入交易期。')
    print('行情定义：EMA 87.45%、SMC 85.59%，均未过90%；B用单一状态。')
    print('G2：EMA三态fail；SMC up/pullback fail、weak未观测；整体未通过。')
    print('漏点：IE9主要排序/原生截断；H1A主要池内无信号；共同漏14段。')
    print('B段首选：'+selected+'（按2024/2025较差年选择）。')
    print('2024/2025/2026 K=3：'+'；'.join(f"{r['covered']}/{r['n']}（{r['coverage']:.1%}）" for r in cover)+'；2026为留出*。')
    print('距80%：'+'；'.join(f"{max(0., .8-r['coverage'])*100:.1f}个百分点" for r in cover)+'。')
    print('三组测试通过；报告：studies/martin_luk/reports/P2A_CN.md、P2B_CN.md。')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=('freeze', 'regimes', 'behaviour', 'prepare_sources', 'diagnostics', 'report_a',
                                         'freeze_b', 'train_b', 'validate_b', 'report_b', 'finish'))
    args = parser.parse_args()
    offline()
    AOUT.mkdir(parents=True, exist_ok=True)
    with (AOUT/'run.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        r = resources()
        assert r['cpu_max'] == '60000 100000' and r['memory_max'] == str(900*1024*1024) and r['threads'] == '1', r
        print('start', args.stage, r, flush=True)
        globals()[args.stage]()
        destination = BOUT if args.stage.endswith('_b') or args.stage == 'finish' else AOUT
        write(destination/f'runs/{args.stage}.json', dict(stage=args.stage, sources=SOURCES, resources=resources()))


if __name__ == '__main__':
    main()
