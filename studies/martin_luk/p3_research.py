"""Offline, bounded P3 stages; frozen selection precedes holdout and accounts."""
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict, fields, replace
from datetime import date
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import resource
import sys

import numpy as np

from . import p3_signal as S, p2_signal as P2, luk
from .p2_research import strategy_only
from studies.trader_replication import regime as R, pipeline as P, mainleg, ledger, system as Y

ROOT = Path(__file__).resolve().parents[2]
HOME = Path(__file__).resolve().parent
OUT = HOME/'reports/p3_work'
PANEL = HOME/'reports/u1_work/panel'
GAP = ROOT/'studies/trader_replication/reports/gap_review'
PREREG = HOME/'notes/PREREG_P3_CN.md'
YEARS = ('2024', '2025', '2026')
SOURCES = {}


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def source(path):
    path = Path(path)
    SOURCES[str(path.relative_to(ROOT))] = sha(path)
    return path


def read(path):
    return json.loads(source(path).read_text())


def clean(x):
    if isinstance(x, dict):
        return {str(k): clean(v) for k, v in x.items()}
    if isinstance(x, (list, tuple, np.ndarray)):
        return [clean(v) for v in x]
    if isinstance(x, np.generic):
        return clean(x.item())
    return None if isinstance(x, float) and not np.isfinite(x) else x


def write(path, value, exclusive=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x' if exclusive else 'w') as stream:
        json.dump(clean(value), stream, ensure_ascii=False, indent=1, allow_nan=False)
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
            raise PermissionError('P3 offline single-process boundary')
        if event == 'open' and not isinstance(args[0], int) and args[2] & (
                os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND):
            path = Path(os.fsdecode(args[0])).resolve()
            if not path.is_relative_to(OUT.resolve()) and path != HOME/'reports/P3_CN.md':
                raise PermissionError('P3 output boundary: '+str(path))
    sys.addaudithook(guard)


def array(path):
    return np.load(source(path), mmap_mode='r')


def freeze():
    mutable = {'studies/trader_replication/pipeline.py',
        'studies/trader_replication/tests/test_pipeline.py'}
    protected = {}
    for directory in ('studies/trader_replication', 'studies/trader_screens', 'studies/trader_data',
                      'studies/trader_registry', 'studies/martin_luk'):
        for path in (ROOT/directory).rglob('*.py'):
            relative = str(path.relative_to(ROOT))
            if relative not in mutable and not path.name.startswith('p3_') and path.name != 'test_p3.py':
                protected[relative] = sha(path)
        # Registered versions read these frozen report/config/round files.
        for sub in ('notes', 'reports'):
            directory_path = ROOT/directory/sub
            for path in directory_path.glob('*.json'):
                protected[str(path.relative_to(ROOT))] = sha(path)
    for path in (HOME/'notes/trades.csv', HOME/'notes/legs_frozen.json',
                 ROOT/'studies/trader_replication/DATA_PIN.json'):
        protected[str(path.relative_to(ROOT))] = sha(path)
    old = HOME/'reports/P2A_CN.md'
    write(OUT/'P2A_before.json', dict(text=old.read_text(), sha256=sha(old)), True)
    write(OUT/'protocol.json', dict(task='PLAN_P3_CN', plan_sha256=sha(HOME/'notes/PLAN_P3_CN.md'),
        prereg_sha256=sha(PREREG), protected=protected,
        memory_before=Path('/proc/meminfo').read_text(), resources=resources(),
        constraints=dict(offline=True, downloads=False, git_commits=0, registered_changes=False,
                         board_changes=False, single_process=True, single_thread=True),
        secret_guard='installer refused existing hooksPath; both hooks already exec secret_guard.py'), True)
    print('P3 prereg and protected inputs frozen', len(protected), flush=True)


def frozen():
    protocol = read(OUT/'protocol.json')
    assert sha(PREREG) == protocol['prereg_sha256'], 'preregistration changed'
    return protocol


def derive(A, destination):
    """Market features, O(stocks) working memory per session/stock."""
    destination.mkdir(parents=True, exist_ok=True)
    shape = A['close'].shape
    result = {key: np.lib.format.open_memmap(destination/f'{key}.npy', mode='w+',
        dtype='bool' if key in ('upgrade', 'weekly_bad') else 'float64', shape=shape)
        for key in ('e9', 'e21', 'e50', 'to20', 'adr', 'upgrade', 'weekly_bad')}
    for j in range(shape[1]):
        money = np.asarray(A['turnover'][:, j], float)[:, None]
        with np.errstate(invalid='ignore', divide='ignore'):
            spread = np.asarray(A['high'][:, j], float)/np.asarray(A['low'][:, j], float)-1
        result['to20'][:, j] = luk.rolling_mean(money, 20)[:, 0]
        result['adr'][:, j] = luk.rolling_mean(spread[:, None], 20)[:, 0]*100
    means = {n: np.full(shape[1], np.nan) for n in (9, 21, 50)}
    previous, events, upgrades = np.zeros(shape[1], bool), [], np.zeros(shape[1], int)
    weekly_ema, last_close = np.full(shape[1], np.nan), np.full(shape[1], np.nan)
    week, bad_week = None, np.zeros(shape[1], bool)
    for t, day in enumerate(A['days']):
        c = np.asarray(A['close'][t], float)
        valid = np.isfinite(c)
        for length, values in means.items():
            fresh = valid & ~np.isfinite(values)
            values[fresh] = c[fresh]
            update, alpha = valid & ~fresh, 2/(length+1)
            values[update] = alpha*c[update]+(1-alpha)*values[update]
            result[f'e{length}'][t] = values
        stack = valid & (means[9] > means[21]) & (means[21] > means[50])
        event = stack & ~previous
        events.append(event)
        upgrades += event
        if len(events) > 5:
            upgrades -= events.pop(0)
        result['upgrade'][t] = stack & (upgrades > 0)
        previous = stack
        this_week = date.fromisoformat(str(day)).isocalendar()[:2]
        if week is not None and this_week != week:
            valid_week = np.isfinite(last_close)
            fresh = valid_week & ~np.isfinite(weekly_ema)
            weekly_ema[fresh] = last_close[fresh]
            update = valid_week & ~fresh
            weekly_ema[update] = (2/11)*last_close[update]+(9/11)*weekly_ema[update]
            bad_week = valid_week & (last_close <= weekly_ema)
            last_close[:] = np.nan
        last_close[valid] = c[valid]
        week = this_week
        result['weekly_bad'][t] = bad_week
    for value in result.values():
        value.flush()
    return result


def market(stop=None):
    A = {key: array(PANEL/f'{key}.npy') for key in
         ('days', 'codes', 'open', 'high', 'low', 'close', 'turnover', 'raw_close')}
    if stop is not None:
        A = {k: v if k == 'codes' else v[:stop] for k, v in A.items()}
    for key in ('open', 'high', 'low', 'close'):
        path = OUT/f'market/{key}.npy'
        if path.exists():
            A[key] = array(path)[:len(A['days'])]
    for key in ('e9', 'e21', 'e50', 'to20', 'adr', 'upgrade', 'weekly_bad'):
        path = OUT/f'market/{key}.npy'
        if path.exists():
            A[key] = array(path)[:len(A['days'])]
    A['ordered'] = read(HOME/'reports/p2a_work/market/IE9_order.json')
    path = OUT/'market/inside.json'
    if path.exists():
        A['inside'] = read(path)
    A.update(market='us', raw=A['raw_close'])
    return A


def features():
    frozen()
    (OUT/'market').mkdir(parents=True, exist_ok=True)
    with strategy_only():
        A = market()
        for key in ('open', 'high', 'low', 'close'):
            target = np.lib.format.open_memmap(OUT/f'market/{key}.npy', mode='w+',
                                              dtype='float64', shape=A[key].shape)
            for t in range(len(target)):
                target[t] = A[key][t]
            target.flush()
            A[key] = target
        derive(A, OUT/'market')
        meta = read(HOME/'reports/p2a_work/market/ie9_scope.json')
        values = array(GAP/'ie9_work/full_features.npy')
        names = read(GAP/'ie9_work/full_features.json')['names']
        offset, inside, checks = 0, {}, []
        for day, codes in sorted(meta['scope'].items()):
            mapping = {c: k for k, c in enumerate(codes)}
            order = A['ordered'].get(day, [])
            sl = slice(offset, offset+len(codes))
            offset = sl.stop
            raw = values[sl]
            inside[day] = {c: float(raw[mapping[c], names.index('after_inside')]) for c in order}
            score = np.array([np.nan_to_num(raw[mapping[c], names.index('after_inside')], nan=.5)+
                              np.nan_to_num(raw[mapping[c], names.index('near_ema9')], nan=.5) for c in order])
            checks.append(bool(np.all(score[:-1] >= score[1:])))
        assert offset == len(values) and all(checks)
        write(OUT/'market/inside.json', inside, True)
    write(OUT/'feature_checks.json', dict(IE9_original_score_order=True, nights=len(checks),
        source_scope_rows=offset, chunking='per stock rolling means; per date EMAs; no NxN',
        resources=resources()), True)
    print('P3 market-only features prepared', resources(), flush=True)


def state_record(result, A):
    mask = (A['days'] >= '2024-01-02') & (A['days'] <= '2026-10-16')
    days, labels = A['days'][mask], result['label'][mask]
    episodes = R.episodes(labels, days)
    def counts(use):
        parts = R.episodes(labels[use], days[use])
        return {s: dict(days=int(np.sum(labels[use] == k)), episodes=sum(e['state'] == s for e in parts))
                for k, s in enumerate(R.NAMES)}
    return dict(calendar=days, label=labels, episodes=episodes,
                counts=counts(np.ones(len(days), bool)),
                annual={y: counts(np.char.startswith(days.astype(str), y)) for y in YEARS})


def regimes():
    frozen()
    round_spec = read(HOME/'notes/rounds/P3.json')
    write(OUT/'round_validation.json', P.validate_round(round_spec, round_spec['base']), True)
    code_paths = (HOME/'p3_signal.py', HOME/'p3_research.py', HOME/'notes/rounds/P3.json',
                  ROOT/'studies/trader_replication/pipeline.py')
    write(OUT/'strategy_frozen.json', {str(p.relative_to(ROOT)): sha(p) for p in code_paths}, True)
    with strategy_only():
        A = market()
        width = S.breadth(A)
        base = {name: S.timeline(A, name, width['state']) for name in S.CANDIDATES}
        mask = (A['days'] >= '2024-01-02') & (A['days'] <= '2026-10-16')
        variants = {name: [] for name in S.CANDIDATES}
        for label, change in S.perturbations():
            w = width if set(change) == {'feedback'} else S.breadth(A, change)
            for name in S.CANDIDATES:
                other = S.timeline(A, name, w['state'], threshold=change.get('feedback', .5))
                a, b = base[name]['label'][mask], other['label'][mask]
                variants[name].append(dict(variant=label, agreement=float(np.mean(a == b)),
                    W_agreement=float(np.mean(width['state'][mask] == w['state'][mask])),
                    F_agreement=float(np.mean(base[name]['feedback'][mask] == other['feedback'][mask])),
                    by_state={s: float(np.sum((a == k) & (b == k)))/int(np.sum((a == k) | (b == k)))
                              if np.any((a == k) | (b == k)) else None for k, s in enumerate(R.NAMES)},
                    label=other['label']))
            print('stability', label, flush=True)
        prefix = []
        for cut in ('2024-09-30', '2025-09-30', '2026-06-30', '2026-10-16'):
            n = int(np.searchsorted(A['days'], cut, side='right'))
            view = {k: v[:n] if isinstance(v, np.ndarray) and k != 'codes' else v for k, v in A.items()}
            rebuilt = derive(view, OUT/f'prefix/{cut}')
            for key, value in rebuilt.items():
                assert np.array_equal(value, A[key][:n], equal_nan=True), (cut, key)
                view[key] = value
            w = S.breadth(view)
            assert np.array_equal(w['state'], width['state'][:n])
            for name in S.CANDIDATES:
                short = S.timeline(view, name, w['state'])
                assert short['picks'] == {t: base[name]['picks'][t] for t in range(n)}
                assert np.array_equal(short['label'], base[name]['label'][:n])
                assert short['outcomes'] == base[name]['outcomes'][:n]
            prefix.append(dict(cut=cut, nights=n, features=True, states=True, nominations=True, feedback=True))
        for name, value in base.items():
            assert all(r['latest_known'] is None or r['latest_known'] < r['day'] for r in value['outcomes'])
            assert all(r['latest_nomination'] is None or r['latest_nomination'] < r['day'] for r in value['outcomes'])
        minimum = min(v['agreement'] for rows in variants.values() for v in rows)
        enabled = minimum >= .9
        # This choice is final before any trader labels or account curves open.
        write(OUT/'regime_selection.json', dict(enabled=enabled, mode='three_states' if enabled else 'single',
            minimum=minimum, threshold=.9, selection_inputs='stability and prefix checks only',
            definitions=1, candidates=list(S.CANDIDATES), prereg_sha256=sha(PREREG)), True)
        bench = P2.benchmarks()
        index = P2.market_states(bench)
        index_by_day = dict(zip(map(str, bench['days']), index['label'].tolist()))
        write(OUT/'index_auxiliary.json', dict(calendar=A['days'], label=[index_by_day[str(d)] for d in A['days']],
            spec=index['spec'], spec_sha=index['spec_sha'], used_in_synthesis=False), True)
        write(OUT/'breadth.json', dict(calendar=A['days'], **width), True)
        for name in S.CANDIDATES:
            raw = base[name]
            write(OUT/f'raw_regimes/{name}.json', dict(state_record(raw, A),
                full_label=raw['label'], feedback=raw['feedback'], outcomes=raw['outcomes'],
                stability=dict(variants=variants[name], minimum=min(v['agreement'] for v in variants[name]),
                               ok=all(v['agreement'] >= .9 for v in variants[name]))), True)
            used = raw if enabled else S.timeline(A, name, width['state'], single=True)
            write(OUT/f'picks/{name}.json', {str(A['days'][t]): cs for t, cs in used['picks'].items()}, True)
            write(OUT/f'regimes/{name}.json', dict(state_record(used, A), full_label=used['label'],
                canonical_new={str(A['days'][t]): cs for t, cs in used['new'].items()}, fallback=not enabled), True)
    write(OUT/'lookahead.json', dict(ok=True, prefixes=prefix, daily_known_before_session=True,
        strategy_reads_labels=False, state_feedback_is_candidate_specific=True), True)
    print('regime fixed before evaluation', enabled, minimum, resources(), flush=True)


def evaluation_inputs():
    frozen_legs = read(HOME/'notes/legs_frozen.json')
    A = market()
    assert frozen_legs['calendar'] == list(A['days'])
    ci = {str(c): j for j, c in enumerate(A['codes'])}
    opens = {g['code']: A['open'][:, ci[g['code']]] for g in frozen_legs['legs'] if g['code'] in ci}
    return frozen_legs, opens, A


def score(picks, frozen_legs, opens, years):
    calendar = frozen_legs['calendar']
    indexed = {t: picks.get(d, []) for t, d in enumerate(calendar[:-1])}
    result = {}
    for K in (1, 3, 5, None):
        row = mainleg.signal_coverage_budget(indexed, None, frozen_legs['legs'], calendar, opens, K)
        row.pop('picks')
        row['annual'] = {y: row['annual'][y] for y in years}
        row.pop('total')
        result['unlimited' if K is None else str(K)] = row
    return result


def train():
    frozen()
    read(OUT/'regime_selection.json')
    legs, opens, _ = evaluation_inputs()
    train_legs = dict(legs, legs=[g for g in legs['legs'] if legs['calendar'][g['first']][:4] in YEARS[:2]])
    results = {}
    for name in S.CANDIDATES:
        results[name] = score(read(OUT/f'picks/{name}.json'), train_legs, opens, YEARS[:2])
        write(OUT/f'train/{name}.json', results[name], True)
    def key(name):
        r = results[name]
        good = all(r['unlimited']['annual'][y]['mean_new_names'] <= 5 for y in YEARS[:2])
        return (not good, -min(r['3']['annual'][y]['coverage'] for y in YEARS[:2]), S.CANDIDATES.index(name))
    chosen = min(S.CANDIDATES, key=key)
    write(OUT/'chosen.json', dict(chosen=chosen, keys={n: key(n) for n in S.CANDIDATES},
        selection_years=list(YEARS[:2]), used_2026_coverage=False, used_accounts=False,
        picks_sha={n: sha(OUT/f'picks/{n}.json') for n in S.CANDIDATES},
        prereg_sha256=sha(PREREG), strategy_sha256=sha(HOME/'p3_signal.py')), True)
    print('chosen before 2026 and accounts', chosen, {n: key(n) for n in S.CANDIDATES}, flush=True)


def diagnose(picks, result, legs, opens, A):
    indexed = {t: picks.get(str(d), []) for t, d in enumerate(A['days'][:-1])}
    selected = mainleg.signal_coverage_budget(indexed, None, legs, list(A['days']), opens, 3)['picks']
    ci = {str(c): j for j, c in enumerate(A['codes'])}
    per_leg = []
    for g, scored in zip(legs, result['3']['per_leg']):
        code, rows = g['code'], []
        last = None
        for t in selected:
            if t >= g['peak']-1:
                break
            if t >= max(0, g['first']-4):
                price = float(opens[code][t+1]) if code in opens else np.nan
                share = (g['top']/price-1)/g['gain'] if np.isfinite(price) and price > 0 else None
                in_pool = code in A['ordered'].get(str(A['days'][t]), [])
                nominated = code in picks.get(str(A['days'][t]), [])
                cooling = last is not None and t-last <= 10
                reason = 'too_late' if share is None or share < .5-1e-12 else (
                    'pool' if not in_pool else 'cooldown' if nominated and cooling else
                    'covered' if code in selected[t] else 'ranking')
                rows.append(dict(night=t, day=str(A['days'][t]), share=share, qualified=share is not None and share >= .5-1e-12,
                    pool=in_pool, nominated=nominated, cooling=cooling,
                    previous=str(A['days'][last]) if last is not None else None, selected=selected[t], reason=reason))
            if code in selected[t]:
                last = t
        q = [r for r in rows if r['qualified']]
        reason = 'covered' if scored['covered'] else 'too_late' if not q else (
            'pool' if not any(r['pool'] for r in q) else
            'cooldown' if any(r['reason'] == 'cooldown' for r in q) else 'ranking')
        first = g['first']
        large = code in ci and A['to20'][first, ci[code]] >= 1e9
        per_leg.append(dict(scored, first=str(A['days'][g['first']]), peak=str(A['days'][g['peak']]),
            large=bool(large), precision=g['precision'], duration=g['duration'], reason=reason,
            pool_bound=any(r['pool'] for r in q), native_bound=any(r['nominated'] for r in q), nights=rows))
    return dict(per_leg=per_leg, annual={y: dict(n=sum(g['year'] == y for g in per_leg),
        misses=dict(Counter(g['reason'] for g in per_leg if g['year'] == y and not g['covered'])),
        pool_bound=sum(g['pool_bound'] for g in per_leg if g['year'] == y),
        native_bound=sum(g['native_bound'] for g in per_leg if g['year'] == y),
        large_n=sum(g['large'] for g in per_leg if g['year'] == y),
        large_covered=sum(g['large'] and g['covered'] for g in per_leg if g['year'] == y)) for y in YEARS})


def validate():
    frozen()
    chosen = read(OUT/'chosen.json')
    write(OUT/'validation_started.json', dict(chosen_sha256=sha(OUT/'chosen.json'),
        picks_sha=chosen['picks_sha'], prereg_sha256=sha(PREREG)), True)
    legs, opens, A = evaluation_inputs()
    for name in S.CANDIDATES:
        assert sha(OUT/f'picks/{name}.json') == chosen['picks_sha'][name]
        picks = read(OUT/f'picks/{name}.json')
        result = score(picks, legs, opens, YEARS)
        training = read(OUT/f'train/{name}.json')
        for K in result:
            for y in YEARS[:2]:
                for field, value in training[K]['annual'][y].items():
                    if field not in ('precision', 'precision_hits'):
                        assert value == result[K]['annual'][y][field], (name, K, y, field)
        write(OUT/f'results/{name}.json', result, True)
        write(OUT/f'diagnostics/{name}.json', diagnose(picks, result, legs['legs'], opens, A), True)
        print('holdout', name, {y: result['3']['annual'][y]['covered'] for y in YEARS}, flush=True)


def metric_test(labels, observations):
    rows = P._episode_rows(labels['episodes'], observations)
    states = {}
    for state in R.NAMES:
        inside = [r for r in rows if r['state'] == state]
        count = sum(r['trades'] for r in inside)
        observed = sum(r['trades'] > 0 for r in inside)
        test = P.block_permutation(rows, state, 999)
        folds = []
        for held in rows:
            rest = [r for r in rows if r['id'] != held['id'] and r['value'] is not None]
            own = [r['value'] for r in rest if r['state'] == state]
            other = [r['value'] for r in rest if r['state'] != state]
            effect = float(np.mean(own)-np.mean(other)) if own and other else None
            test_effect = held['value']-float(np.mean(other)) if held['state'] == state and other and held['value'] is not None else None
            folds.append(dict(held_out=held['id'], train_effect=effect, test_value=held['value'],
                test_effect=test_effect, same_direction=effect*test_effect > 0
                if effect is not None and test_effect is not None else None))
        same = sum(f['same_direction'] is True for f in folds)
        enough = count >= 15 and observed >= 3
        status = 'unobserved' if not enough else 'pass' if test['p'] is not None and test['p'] < .1 and same >= 2 else 'fail'
        values = [r['value'] for r in observations if any(
            e['state'] == state and e['first'] <= r['day'] <= e['last'] for e in labels['episodes'])]
        states[state] = dict(status=status, n=count, observed_episodes=observed,
            mean=float(np.mean(values)) if values else None, median=float(np.median(values)) if values else None,
            **test, leave_one_same_direction=same, folds=folds)
    return dict(states=states, episodes=rows)


def correlations(rows, labels):
    if len(rows) < 3:
        return dict(n=len(rows), time_spearman=None, state_eta=None, state_spearman=None)
    values = np.array([r['value'] for r in rows])
    times = np.array([r['day'] for r in rows])
    states = np.array([labels['label'][r['day']] for r in rows])
    def corr(a, b):
        a, b = S.percentile(a), S.percentile(b)
        return float(np.corrcoef(a, b)[0, 1]) if np.std(a) > 0 and np.std(b) > 0 else None
    total = np.sum((values-values.mean())**2)
    between = sum(np.sum(states == k)*(values[states == k].mean()-values.mean())**2
                  for k in range(3) if np.any(states == k))
    # Category IDs are not ordinal. Eta uses categories; the signed coding is a separate diagnostic.
    signed = np.choose(states, [1, 0, -1])
    return dict(n=len(rows), time_spearman=corr(times, values),
                state_eta=float(np.sqrt(between/total)) if total > 0 else None,
                state_spearman=corr(signed, values))


def curve_description(curve, labels):
    days, equity = np.array(curve['days']), np.array(curve['equity'], float)
    returns = equity/np.r_[1., equity[:-1]]-1
    by_day = dict(zip(labels['calendar'], labels['label']))
    state = np.array([by_day[str(d)] for d in days])
    def measure(years):
        selected = np.isin(np.array([str(d)[:4] for d in days]), list(years))
        return {name: dict(days=int(np.sum(selected & (state == k))),
            ret=float(np.prod(1+returns[selected & (state == k)])-1)) for k, name in enumerate(R.NAMES)}
    return dict(all=measure(YEARS), annual={y: measure([y]) for y in YEARS},
        leave_year_out={y: dict(train=measure(set(YEARS)-{y}), test=measure([y])) for y in YEARS},
        note='actual calendar-day returns grouped; no exposure matching, refit, or capital reallocation')


def behaviour():
    frozen()
    selected = read(OUT/'regime_selection.json')
    public = ledger.load(source(HOME/'notes/trades.csv'))
    legs, _, A = evaluation_inputs()
    ci = {str(c): j for j, c in enumerate(A['codes'])}
    days = list(map(str, A['days']))
    start = int(np.searchsorted(days, '2024-01-02'))
    dated, excluded = [], []
    for trade in public:
        if not trade.dated:
            continue
        t = int(np.searchsorted(days, trade.entry_date))
        if t < start or t >= len(days):
            excluded.append(dict(id=trade.id, date=trade.entry_date, side=trade.side, reason='outside frozen calendar'))
            continue
        dated.append(dict(id=trade.id, date=trade.entry_date, aligned=days[t], day=t-start,
                          value=float(trade.side == 'short'), precision=trade.precision))
    portraits, missing = [], []
    for g in legs['legs']:
        t, j = g['first'], ci.get(g['code'])
        if j is None or t < 0 or not np.isfinite(A['to20'][t, j]) or not np.isfinite(A['adr'][t, j]):
            missing.append(dict(key=g['key'], reason='missing first-anchor-night market inputs'))
            continue
        pool = (A['to20'][t] >= 100e6) & (A['adr'][t] >= 4) & np.isfinite(A['close'][t]) & (A['close'][t] > 0)
        values = {}
        for key in ('to20', 'adr'):
            peers = np.sort(A[key][t, pool])
            x = float(A[key][t, j])
            values[key] = (np.searchsorted(peers, x, 'left')+np.searchsorted(peers, x, 'right'))/(2*len(peers)) if len(peers) else None
        portraits.append(dict(key=g['key'], code=g['code'], day=g['first']-start,
            first=days[g['first']], known=days[t], precision=g['precision'], money=float(A['to20'][t, j]),
            adr=float(A['adr'][t, j]), in_pool=bool(pool[j]), peers=int(pool.sum()), percentiles=values))
    master = read(HOME/'reports/d1_work/master_curve.json')
    m3 = read(HOME/'reports/m3_work/validation/continuous/curve.json')
    m3_train = read(HOME/'reports/m3_work/candidates/M3B/curve.json')
    assert m3['days'][:len(m3_train['days'])] == m3_train['days']
    assert m3['equity'][:len(m3_train['equity'])] == m3_train['equity']
    result = dict(definition_enabled=selected['enabled'], diagnostic_only=not selected['enabled'],
        ledger_record_counts=dict(Counter((t.entry_date or t.window_lo)[:4] for t in public)),
        entry_date_record_counts=dict(Counter(t.entry_date[:4] for t in public if t.entry_date)),
        public_dated_counts=dict(Counter(t.entry_date[:4] for t in public if t.dated)),
        window_only=[dict(id=t.id, date=t.entry_date, lo=t.window_lo, hi=t.window_hi, side=t.side,
                         reason='window precision cannot reliably assign one entry-session state')
                     for t in public if not t.dated],
        classified_direction_counts=dict(Counter(r['date'][:4] for r in dated)),
        excluded=excluded, first_anchor_portraits=portraits, missing_portraits=missing,
        M3B_continuous_prefix_exact=True, candidates={})
    for name in S.CANDIDATES:
        labels = read(OUT/f'raw_regimes/{name}.json')
        scopes = {}
        for scope in ('2026', 'pooled'):
            direction = [r for r in dated if scope == 'pooled' or r['date'].startswith(scope)]
            tiers = [r for r in portraits if scope == 'pooled' or r['first'].startswith(scope)]
            metrics = dict(direction=direction,
                turnover=[dict(day=r['day'], value=r['percentiles']['to20']) for r in tiers if r['percentiles']['to20'] is not None],
                adr=[dict(day=r['day'], value=r['percentiles']['adr']) for r in tiers if r['percentiles']['adr'] is not None])
            scopes[scope] = dict(metrics={k: metric_test(labels, v) for k, v in metrics.items()},
                exact_direction=metric_test(labels, [r for r in direction if r['precision'] == 'exact']),
                correlations={k: correlations(v, labels) for k, v in metrics.items() if k != 'direction'})
        result['candidates'][name] = dict(scopes=scopes,
            old_accounts={key: curve_description(curve, labels) for key, curve in (('master', master), ('M3B', m3))})
    write(OUT/'G2.json', result, True)
    print('G2 directions and tiers evaluated; no density test', resources(), flush=True)


def decode_book(rows, A):
    di, ci = ({str(d): t for t, d in enumerate(A['days'])}, {str(c): j for j, c in enumerate(A['codes'])})
    book = [[] for _ in A['days']]
    def priority(x):
        return tuple(priority(v) for v in x) if isinstance(x, list) else x
    for row in rows:
        d, j = di[row['day']], ci[row['code']]
        stop = row['stop']
        day_exit = stop if row['side'] < 0 and A['high'][d, j] >= stop else None
        book[d].append((priority(row['priority']), j, row['side'], row['fill'], stop, row['kind'], day_exit))
    return book


def account_inputs(A):
    from . import replicate as MR
    metadata = read(HOME/'reports/d1_work/master_metadata.json')
    assert metadata['days'] == list(A['days']) and metadata['codes'] == list(A['codes'])
    known = {f.name for f in fields(Y.Rules)}
    rules = Y.Rules(**{k: v for k, v in metadata['rules'].items() if k in known})
    long_pool = array(HOME/'reports/d1_work/master_liquidity.npy')
    short_pool = MR.pool_for(A, 'U7')
    A['idx_pb16'] = MR.index_risk_scale(A, long_pool | short_pool)
    return metadata, rules, short_pool


def px(A):
    return dict(dates=A['days'], codes=A['codes'], **{k: A[k] for k in ('open', 'high', 'low', 'close')})


def baseline(A, rules):
    book = decode_book(read(HOME/'reports/d1_work/master_book.json'), A)
    ema = {k: A[k] for k in ('e9', 'e21', 'idx_pb16')}
    curve, dates, trades = Y.simulate(px(A), ema, rules, book, '2024-01-02', '2026-10-16', audit=True)
    old_curve = read(HOME/'reports/d1_work/master_curve.json')
    old_trades = read(HOME/'reports/d1_work/master_trades.json')
    checks = dict(dates=list(dates) == old_curve['days'], curve=curve.tolist() == old_curve['equity'],
                  complete_ledger=clean(trades) == old_trades, n=len(trades))
    if not all(checks[k] for k in ('dates', 'curve', 'complete_ledger')):
        from studies.trader_replication.martin import compare
        write(OUT/'master_replay_mismatch.json', dict(checks=checks,
            curve=compare(curve.tolist(), old_curve['equity'], tol=0)[:8],
            ledger=compare(clean(trades), old_trades, tol=0)[:8]))
        raise AssertionError('master replay mismatch; inspect artifact')
    record = clean(dict(checks, registered_config_unchanged=True, rules=asdict(rules)))
    path = OUT/'master_replay.json'
    if path.exists():
        assert read(path) == record
    else:
        write(path, record, True)
    print('master ledger and curve exactly reproduced', checks, flush=True)


def first_short_entries(A, entries, first):
    """At the Z15 fill, the first 50-EMA touch must already be observable."""
    return [[e for e in row if d > 0 and first[d, e[1]] and A['weekly_bad'][d, e[1]]
             and e[3] >= A['e50'][d-1, e[1]]] for d, row in enumerate(entries)]


def paired_shorts(A, short_pool, config):
    """Original Z15 before the old index/cap, then first-retest and weekly filters."""
    from . import replicate as MR
    from studies.trader_replication import shorts
    A['rank_pool'] = (A['raw'] >= 1) & (A['to20'] >= 2e6)
    for hz in (21, 63, 126):
        with np.errstate(invalid='ignore', divide='ignore'):
            A[f'pr{hz}'] = MR.pct_rank(A['close']/luk.lag(A['close'], hz)-1, A['rank_pool'])
    mask = MR.level_shorts(A, short_pool)['Z15']
    entries = shorts.short_entries(A, {'Z15': mask}, config)
    first = np.zeros(A['close'].shape, bool)
    for j in range(len(A['codes'])):
        first[:, j] = S.first_retests(A['close'][:, j], A['high'][:, j], A['e50'][:, j])
    filtered = first_short_entries(A, entries, first)
    write(OUT/'short_filter_audit.json', dict(original_Z15=sum(map(len, entries)),
        first_retest=sum(bool(first[d, e[1]]) for d, row in enumerate(entries) for e in row),
        first_and_weekly_bad=sum(map(len, filtered)), consumed_retests=int(first.sum()),
        filtering_before_cap=True, weekly='last completed week only',
        causal_fill='Z15 level at/above prior EMA50; cannot use a later high to validate an earlier lower fill'), True)
    for key in ('rank_pool', 'pr21', 'pr63', 'pr126'):
        del A[key]
    return filtered


def candidate_book(A, picks, long_book, short_book, labels, paired):
    longs, shorts = [], []
    for d, day in enumerate(A['days']):
        positions = {c: k for k, c in enumerate(picks.get(str(day), []))}
        eligible = [((positions[str(A['codes'][e[1]])],),)+e[1:] for e in long_book[d]
                    if str(A['codes'][e[1]]) in positions and (not paired or labels[d] != R.WEAK)]
        longs.append(sorted(eligible, key=lambda e: e[0])[:4])
        shorts.append(sorted(short_book[d], key=lambda e: e[0])[:1]
                      if not paired or labels[d] == R.WEAK else [])
    from studies.trader_replication.shorts import combine
    return combine(longs, shorts)


class Prices:
    def __init__(self, A):
        self.A, self.ci = A, {str(c): j for j, c in enumerate(A['codes'])}

    def __getitem__(self, code):
        j = self.ci[code]
        return {k: self.A[v][:, j] for k, v in (('c', 'close'), ('o', 'open'), ('h', 'high'), ('l', 'low'))}


def actual_coverage(trades, rules, legs, A):
    di = {str(d): t for t, d in enumerate(A['days'])}
    normalized = []
    for tid, trade in enumerate(trades):
        if trade['side'] < 0:
            continue
        fills = []
        for event in trade['executions']:
            buy = event['action'] in ('entry', 'add')
            fills.append(dict(index=di[event['time']], quantity=event['shares']*(1 if buy else -1),
                price=event['price'], fee=event['shares']*event['price']*(rules.buy_cost if buy else rules.sell_cost),
                open=event['action'] == 'end'))
        normalized.append(dict(id=tid, code=trade['code'], entry=di[trade['entry']],
            closed=trade['why'] != 'end', pnl=trade['pnl'], lots=mainleg.lots(fills, trade['pnl'])))
    rows = mainleg.attribute_lots(normalized, legs, Prices(A), list(A['days']))
    coverage = mainleg.account_coverage(rows, legs, list(A['days']))
    return dict(n=len(coverage), covered=sum(r['covered'] for r in coverage),
        annual={y: dict(n=sum(r['year'] == y for r in coverage),
            covered=sum(r['covered'] for r in coverage if r['year'] == y)) for y in YEARS}, per_leg=coverage)


def short_coverage(trades, public, A):
    rows = []
    for t in public:
        if not t.dated or t.side != 'short':
            continue
        index = int(np.searchsorted(A['days'], t.entry_date))
        code = 'US.'+t.ticker.removeprefix('US.')
        lo, hi = max(0, index-3), min(len(A['days'])-1, index+1)
        hits = [dict(entry=r['entry'], exit=r['exit']) for r in trades if r['side'] < 0 and r['code'] == code
                and str(A['days'][lo]) <= r['entry'] <= str(A['days'][hi])]
        rows.append(dict(id=t.id, code=code, date=t.entry_date, precision=t.precision,
            covered=bool(hits), hits=hits, market_available=code in set(map(str, A['codes'])),
            window=[str(A['days'][lo]), str(A['days'][hi])]))
    assert len(rows) == 37, len(rows)
    return dict(n=len(rows), covered=sum(r['covered'] for r in rows), per_trade=rows)


def account_summary(curve, dates, trades):
    from .replicate import HIS
    facts = P.account_facts(curve, dates, trades)
    annual = {}
    for year in YEARS:
        part = [t for t in trades if t['entry'].startswith(year)]
        closed = [t for t in part if t['why'] != 'end']
        wins, losses = [t for t in closed if t['ret'] > 0], [t for t in closed if t['ret'] <= 0]
        avg_win = float(np.mean([t['ret'] for t in wins])) if wins else None
        avg_loss = float(np.mean([t['ret'] for t in losses])) if losses else None
        reference = HIS.get(year, {})
        his_count = reference.get('wins', 0)+reference.get('losses', 0) or None
        his_win = reference.get('wins', 0)/his_count if his_count else None
        ret = facts['years'][year]
        win = len(wins)/len(closed) if closed else None
        payoff = avg_win/abs(avg_loss) if avg_win is not None and avg_loss else None
        annual[year] = dict(ret=ret, losing=ret < 0, n=len(part), closed=len(closed), win=win,
            payoff=payoff, avg_win=avg_win, avg_loss=avg_loss,
            days=float(np.mean([t['days'] for t in closed])) if closed else None,
            days_win=float(np.mean([t['days'] for t in wins])) if wins else None,
            days_loss=float(np.mean([t['days'] for t in losses])) if losses else None,
            longs=sum(t['side'] > 0 for t in part), shorts=sum(t['side'] < 0 for t in part),
            his=dict(ret=reference.get('ret'), n=his_count, win=his_win,
                payoff=abs(reference['avg_win']/reference['avg_loss']) if reference.get('avg_loss') else None,
                days=None, source='replicate.HIS / RULES_CN; holding not published'),
            gaps=dict(return_percentage_points=100*(ret-reference['ret']) if 'ret' in reference else None,
                log_wealth=abs(float(np.log((1+ret)/(1+reference['ret'])))) if ret > -1 and 'ret' in reference else None,
                win_percentage_points=100*(win-his_win) if win is not None and his_win is not None else None,
                count=len(part)-his_count if his_count else None,
                payoff=payoff-abs(reference['avg_win']/reference['avg_loss'])
                    if payoff is not None and reference.get('avg_loss') else None, days=None))
    source(HOME/'reports/H1_CN.md')
    dates_ = np.asarray(dates)
    prior = np.flatnonzero(dates_ <= '2025-12-31')[-1]
    july = np.flatnonzero(dates_ <= '2026-07-31')[-1]
    matched_return = float(curve[july]/curve[prior]-1)
    annual['2026']['matched_public_period'] = dict(end=str(dates_[july]), ours=matched_return,
        his=8.69, difference_percentage_points=100*(matched_return-8.69),
        source='H1_CN.md: public 2026 return through July; full 2026 target missing')
    return dict(annual=annual, facts=facts, stats=Y.stats(curve, dates, trades),
        veto=dict(losing_years=[y for y in YEARS if annual[y]['losing']],
            behaviour_ok=facts['closed'] >= 30 and facts['win'] is not None and facts['win'] <= .35
            and all(annual[y]['n'] >= 52 for y in YEARS)), selection_uses_accounts=False)


def accounts():
    frozen()
    chosen = read(OUT/'chosen.json')
    assert (OUT/'validation_started.json').exists()
    # This is the original system's own entry cache, not the trader's labels.
    # P2's broad filename guard also rejects its '*entries.json' suffix.
    own_short_rows = read(HOME/'reports/d1_work/master_short_entries.json')
    with strategy_only():
        A = market()
        metadata, original_rules, spool = account_inputs(A)
        baseline(A, original_rules)
        original_longs = decode_book(read(HOME/'reports/d1_work/master_filtered.json'), A)
        raw_longs = decode_book(read(HOME/'reports/d1_work/master_raw.json'), A)
        old_shorts = decode_book(own_short_rows, A)
        new_shorts = paired_shorts(A, spool, metadata['config']['short'])
    frozen_legs = read(HOME/'notes/legs_frozen.json')
    public = ledger.load(source(HOME/'notes/trades.csv'))
    for name in S.CANDIDATES:
        assert sha(OUT/f'picks/{name}.json') == chosen['picks_sha'][name]
        with strategy_only():
            picks = read(OUT/f'picks/{name}.json')
            states = np.array(read(OUT/f'regimes/{name}.json')['full_label'])
            A['p3_risk'] = np.where(states == R.UP, 1.6, 1.)
        for mode in ('A', 'B'):
            with strategy_only():
                paired = mode == 'B'
                rules = replace(original_rules, risk_scale='p3_risk') if paired else original_rules
                entries = candidate_book(A, picks, raw_longs if paired else original_longs,
                                         new_shorts if paired else old_shorts, states, paired)
                ema = {k: A[k] for k in ('e9', 'e21', 'idx_pb16', 'p3_risk')}
                track = {'entry_attempts': []}
                curve, dates, trades = Y.simulate(px(A), ema, rules, entries,
                    '2024-01-02', '2026-10-16', audit=True, track=track)
            destination = OUT/f'accounts/{name}/{mode}'
            write(destination/'trades.json', trades, True)
            write(destination/'curve.json', dict(days=dates, equity=curve), True)
            write(destination/'attempts.json', track, True)
            summary = account_summary(curve, dates, trades)
            summary['holding_coverage'] = actual_coverage(trades, rules, frozen_legs['legs'], A)
            summary['short_coverage'] = short_coverage(trades, public, A)
            summary['rules'] = asdict(rules)
            summary['paired'] = paired
            write(destination/'summary.json', summary, True)
            print('account', name, mode, {y: round(summary['annual'][y]['ret'], 4) for y in YEARS},
                  'holding', summary['holding_coverage']['covered'], 'short', summary['short_coverage']['covered'],
                  resources(), flush=True)


def fmt(value, percent=False, signed=False):
    if value is None:
        return '缺失'
    return (f'{value:+.1%}' if signed else f'{value:.1%}') if percent else f'{value:.3f}'


def g2_conclusion(scopes):
    names = dict(direction='方向', turnover='成交额档', adr='ADR档')
    states = dict(up='进攻', pullback='常态', weak='防守')
    pieces = []
    for scope, data in scopes.items():
        metrics = []
        for metric, row in data['metrics'].items():
            passed = [states[s] for s, v in row['states'].items() if v['status'] == 'pass']
            text = '/'.join(passed)+'有差异' if passed else '未检出可靠差异'
            if not passed and all(v['status'] == 'unobserved' for v in row['states'].values()):
                text = '样本不足'
            metrics.append(names[metric]+text)
        pieces.append(('合并' if scope == 'pooled' else scope)+'：'+'、'.join(metrics))
    return '；'.join(pieces)+'。'


def report():
    frozen()
    selected = read(OUT/'regime_selection.json')
    name = read(OUT/'chosen.json')['chosen']
    results = {n: read(OUT/f'results/{n}.json') for n in S.CANDIDATES}
    diagnoses = {n: read(OUT/f'diagnostics/{n}.json') for n in S.CANDIDATES}
    behaviour_ = read(OUT/'G2.json')
    raw_states = read(OUT/f'raw_regimes/{name}.json')
    g2 = behaviour_['candidates'][name]
    accounts_ = {n: {m: read(OUT/f'accounts/{n}/{m}/summary.json') for m in ('A', 'B')} for n in S.CANDIDATES}
    master_years = read(HOME/'reports/d1_work/master_metadata.json')['stats']['by_year']
    chosen = results[name]
    annual = chosen['3']['annual']
    def cell(r):
        return f"{r['covered']}/{r['n']}（{r['coverage']:.1%}）"
    lines = ['# P3：三层行情、五种点名与成对仓位', '',
        f"按2024/2025较差年K=3早期覆盖，首选 **{name}**。三年分别为"+
        '、'.join(cell(annual[y]) for y in YEARS)+
        f"；2026为留出*，距80%还差{max(0., .8-annual['2026']['coverage'])*100:.1f}个百分点。"
        f"2026同冷却不限K新名均数{chosen['unlimited']['annual']['2026']['mean_new_names']:.2f}只/晚。", '',
        f"固定三层定义最低日重合率{selected['minimum']:.2%}，"+
        ('达到90%，候选使用三态。' if selected['enabled'] else
         '未到90%，全体候选按任务书用单一常态继续。下面三态的G2和旧账户描述只是诊断，不是合格Switch。'), '',
        g2_conclusion(g2['scopes']), '',
        '首选账户的亏损年：'+'；'.join(m+' '+(','.join(accounts_[name][m]['veto']['losing_years']) or '无') for m in ('A', 'B'))+
        '。这些亏损不取消覆盖选择，但该版本不能据此登记为已复刻。', '',
        '登记master原完整账户的2024/2025/2026收益为'+
        '、'.join(fmt(master_years[y], True, True) for y in YEARS)+
        '。本轮A/B已经换成候选点名，两套首选账户都明显退步；“本轮首选”只指固定覆盖选择，不是可替换master的新主线。', '',
        '这次仍只否定当前日K翻译，不能据此否定他的三层行情判断。方向和票档分别检验，不比较台账交易密度。'
        '账户收益没有用于选择；亏损年和行为差距照报。登记版与看板不改。', '',
        '2024/2025是历史选择段，2026早已被反复查看，标“留出*”，没有新的独立样本外。'
        '五个候选的点名及首选先落盘，再一次性评测2026，之后才运行十套账户。', '',
        '## 行情定义与稳定性', '',
        'W在日均成交额≥1亿美元且ADR20≥4%的统一流动池中，计9>21>50领涨L、9<21<50落后G，'
        '比较L−G的EMA10/EMA30。F只用各候选自己的前10晚K=3新点名，满两根日K才判断，'
        '两根收盘都未低于入场日低点算跟上；不足5笔维持原状态。W和F各确认3日，进攻=变宽且反馈好，'
        '防守=变窄且反馈差，其余常态。QQQ idx_ema＋3日确认只作辅助，不进入合成或选择。', '',
        '状态用于交易日t，只读t−1及以前；t晚信号用当日可知市场特征和已公布状态。'
        'REGIME_RETHINK看过的是IE9池只数，本轮改用L−G，仍明确属于受既有观察启发的研究。', '',
        '| 候选自己的反馈 | 最低扰动重合 | 最差扰动 | 进攻天/段 | 常态天/段 | 防守天/段 |',
        '|---|---:|---|---:|---:|---:|']
    for n in S.CANDIDATES:
        r = read(OUT/f'raw_regimes/{n}.json')
        worst = min(r['stability']['variants'], key=lambda v: v['agreement'])
        lines.append(f"| {n} | {r['stability']['minimum']:.2%} | {worst['variant']} | "+
            ' | '.join(f"{r['counts'][s]['days']}/{r['counts'][s]['episodes']}" for s in R.NAMES)+' |')
    lines += ['', '逐项扰动包括五个EMA窗口各±2、成交额及ADR门槛各±25%、反馈40%/60%，共16项；'
        '不做网格，不因失败改参数。完整每日日态、各态交并比及按年天/段数在raw_regimes/。'
        '四个截断点从头重建全部市场指标、逐夜点名和反馈均一致，逐日最新反馈行情均早于状态日。', '',
        '## G2：方向与票档', '',
        '以下正文用覆盖首选自己的反馈状态，其余四套完整数字也在G2.json。'
        '方向是有日期且多空已知的交易中空头占比，不因形态缺分类而删除。'
        '票档是48段首锚点当晚，成交额/ADR在同一流动池中的分位；不使用峰值或未来票档。'
        '整段置换999次、种子0、双侧p，episode等权；表中均值为观测等权，效应为段均值差。'
        '至少3个有观测段、15笔才作有样本判定，全部逐段留一数字在工件。', '',
        '| 范围/指标 | 状态 | 笔/段 | 均值 | 整段效应 | p | 同向留一段 | 证据 |',
        '|---|---|---:|---:|---:|---:|---:|---|']
    for scope, data in g2['scopes'].items():
        for metric, output in data['metrics'].items():
            for state, r in output['states'].items():
                lines.append(f"| {scope}/{metric} | {state} | {r['n']}/{r['observed_episodes']} | "+
                    ' | '.join(fmt(r[k]) for k in ('mean', 'effect', 'p'))+
                    f" | {r['leave_one_same_direction']} | {r['status']} |")
    lines += ['', f"全部台账记录数（含只知窗口）：{behaviour_['ledger_record_counts']}；有entry_date字段的记录数："
        f"{behaviour_['entry_date_record_counts']}；exact/chart有日期笔数：{behaviour_['public_dated_counts']}；冻结日历内可评测："
        f"{behaviour_['classified_direction_counts']}；排除日历外{len(behaviour_['excluded'])}笔，原因逐笔保留。"
        f"票档缺输入{len(behaviour_['missing_portraits'])}段。exact方向单列于G2.json。", '',
        '任务书的13/24/87对应有entry_date字段的记录。2024其中CLSK一条仍标window（6月1–28日），'
        '方向已知但入场状态不可靠；2025另有17条没有entry_date、只知窗口的记录。'
        '这些记录全部保留并单列，不假装成精确日期，也不拿窗口起点估计交易密度。', '',
        '有样本指标的pass只表示此定义下观察到差异；未观测和fail不等于行为与整体行情无关。'
        '若定义稳定性失败，即使行为p很小也不能把它说成合格行情开关。', '',
        '| 票档诊断 | 样本 | 与时间Spearman | 与状态η | 状态有序编码Spearman |', '|---|---:|---:|---:|---:|']
    for scope, data in g2['scopes'].items():
        for metric, r in data['correlations'].items():
            lines.append(f"| {scope}/{metric} | {r['n']} | {fmt(r['time_spearman'])} | {fmt(r['state_eta'])} | {fmt(r['state_spearman'])} |")
    lines += ['', '状态η按名义类别计算；另列进攻=1、常态=0、防守=−1的相关。'
        '这些相关不能区分行情和账户变大的因果，不作结论。', '',
        '| 旧账户/年份 | 进攻日收益 | 常态日收益 | 防守日收益 |', '|---|---:|---:|---:|']
    for book, values in g2['old_accounts'].items():
        for y in YEARS:
            lines.append(f'| {book}/{y} | '+' | '.join(fmt(values['annual'][y][s]['ret'], True, True) for s in R.NAMES)+' |')
    lines += ['', '这里只把既有账户的实际日收益按当日状态复合，不能解释成新账户可实现的收益。'
        '每年留一的其余两年/留出年在G2.json，未重配资金，也未据它选定义。M3B连续曲线的2024/2025前缀与原选择段逐值一致。', '',
        '## 所有信号候选', '',
        '每晚原生最多5只；候选内部无冷却，S统一先剔除过去10交易日实际点过的名字，再取K。'
        'F固定用K=3投影，不因评测预算改策略。C1按升级比例分票档；C2只替换near_ema9为21EMA四个ADR内不扣分；'
        'C3升级优先；C4按状态选固定家族/票档；C5预先固定为C1＋C4。逐字原话、平手及缺额规则见预登记。', '',
        '| 候选 | 2024 K=3（选择） | 2025 K=3（选择） | 2026 K=3（留出*） | 较差选择年 |', '|---|---:|---:|---:|---:|']
    for n, r in results.items():
        a = r['3']['annual']
        lines.append('| '+n+('（首选）' if n == name else '')+' | '+' | '.join(cell(a[y]) for y in YEARS)+
                     f" | {min(a[y]['coverage'] for y in YEARS[:2]):.1%} |")
    lines += ['', '以下每格三项依次为2024/2025/2026，样本属性沿用上表。剩余幅度是首次合格点名至峰值涨幅除以首锚点总涨幅，不是账户收益。', '',
        '| 候选 | K=1覆盖 | K=5覆盖 | 不限K覆盖 | 不限K新名/晚 | K=3新名/晚 | 精度 | 剩余幅度中位 |',
        '|---|---|---|---|---|---|---|---|']
    for n, r in results.items():
        cells = [n]
        for k in ('1', '5', 'unlimited'):
            cells.append(' · '.join(f"{r[k]['annual'][y]['covered']}/{r[k]['annual'][y]['n']}" for y in YEARS))
        for k, field in (('unlimited', 'mean_new_names'), ('3', 'mean_new_names'), ('3', 'precision'), ('3', 'remaining_share_median')):
            cells.append(' · '.join(fmt(r[k]['annual'][y][field], field in ('precision', 'remaining_share_median')) for y in YEARS))
        lines.append('| '+' | '.join(cells)+' |')
    lines += ['', 'K各自有冷却历史，覆盖不保证随K单调；不限K仍受原生5只限制。'
        '选择仅最大化2024/2025中较差年的K=3覆盖，平手按C1至C5列序，不按2026或账户换首选。'
        'S0原IE9同口径为3/9、14/22、11/17，供直接比较。固定逐年重放不等于三套重新留年拟合模型；G3主留出不足80%即未通过。', '',
        '| 候选/年份 | 池可达上限 | 原生5只无冷却上限 | ≥1B段命中 | 漏段原因 |', '|---|---:|---:|---:|---|']
    for n, output in diagnoses.items():
        for y, r in output['annual'].items():
            lines.append(f"| {n}/{y} | {r['pool_bound']}/{r['n']} | {r['native_bound']}/{r['n']} | "
                         f"{r['large_covered']}/{r['large_n']} | {r['misses']} |")
    lines += ['', '池及原生无冷却上限是乐观必要条件，不是实际K=3成绩。票档按首锚点当晚固定。'
        '逐段和逐夜保留池外、排序、冷却、太晚，冷却上次点名与挤出票均在diagnostics/；事件、截断及精度分层保留在结果和段明细。', '',
        '## A/B账户：真正买到与行为', '',
        'A保留master的IDX50、idx_pb16和原S7；B仅替换行情：进攻多头风险×1.6、常态×1、防守不新开多，'
        '空头仅防守开，需原Z15、首次破50后首次反抽、已完成周线不在周EMA10之上。'
        '候选在同晚原master有触发的队列中替换排序，仍最多4个多头候选、1个空头；未触发不补别的票。'
        '原止损、退出、加仓、仓位上限和0.5%/0.8%账户反馈保留，已有多头仍按原规则管理。', '',
        '原master完整台账与曲线逐值复放一致，才运行候选。点名仍按S的次日开盘评价，账户多头继续master收盘确认入场；'
        '二者时点不同，信号命中不能当作实际买到。若退回单一常态，B不开空并取消指数风险倍数，不再使用失败的三态。', '',
        '| 候选/账户/年 | 收益 | 开仓（多/空） | 已平仓 | 胜率 | 盈亏比 | 持有均天（赢/亏） | 亏损年 |',
        '|---|---:|---:|---:|---:|---:|---:|---|']
    for n, modes in accounts_.items():
        for mode, output in modes.items():
            for y, r in output['annual'].items():
                lines.append(f"| {n}/{mode}/{y} | {fmt(r['ret'], True, True)} | {r['n']}（{r['longs']}/{r['shorts']}） | "
                    f"{r['closed']} | {fmt(r['win'], True)} | {fmt(r['payoff'])} | {fmt(r['days'])}（"
                    f"{fmt(r['days_win'])}/{fmt(r['days_loss'])}） | {'是' if r['losing'] else '否'} |")
    lines += ['', '本人参照：2024收益+283%、104胜319负（423笔，24.6%）、平均赚15%/亏3%（盈亏比5）；'
        '2025收益+969.8%、209胜731负（940笔，22.2%）、平均赚14.1%/亏2.1%（盈亏比6.71）。'
        '2026只有截至7月+869%的既有资料，完整年目标缺失；summary另用本系统至7月底收益对照，不把10-16与7月底当作同期限。'
        '没有可核对的本人持有日序列，差距写缺失，不用到峰值的天数代填。以上数值沿用replicate.HIS与RULES_CN。'
        '每个候选逐年收益百分点差、财富比对数差、胜率百分点差、笔数差、盈亏比差均在accounts/*/*/summary.json；不以日K笔数强行匹配分时940次。', '',
        '| 首选/年 | 收益百分点差 | 财富比对数差 | 胜率百分点差 | 开仓笔数差 | 盈亏比差 |',
        '|---|---:|---:|---:|---:|---:|']
    for mode in ('A', 'B'):
        for y in YEARS:
            gap = accounts_[name][mode]['annual'][y]['gaps']
            lines.append(f'| {mode}/{y} | '+' | '.join(fmt(gap[k]) for k in
                ('return_percentage_points', 'log_wealth', 'win_percentage_points', 'count', 'payoff'))+' |')
    lines += ['', '2026整年差距缺失，7月底同期限收益对照在各账户的matched_public_period；持有天差距均为缺失。', '',
        '| 候选/账户 | 实际早买段/48 | 分年早买段 | 空头/37 | 亏损年份 |', '|---|---:|---|---:|---|']
    for n, modes in accounts_.items():
        for mode, output in modes.items():
            c, s = output['holding_coverage'], output['short_coverage']
            lines.append(f"| {n}/{mode} | {c['covered']}/{c['n']} | "+
                ' · '.join(f"{c['annual'][y]['covered']}/{c['annual'][y]['n']}" for y in YEARS)+
                f" | {s['covered']}/{s['n']} | {','.join(output['veto']['losing_years']) or '无'} |")
    lines += ['', '持仓覆盖沿用H1：段窗内首实际lot必须还剩首锚点涨幅的一半，后来的加仓/重试不重置首笔时钟。'
        '空头只看37笔有日期空单的入场前3至后1个交易日同票真实开仓；ETF不在股票面板也保留分母并列缺数据。'
        '这两项只报告，不用于覆盖选择。每套账户均保存完整逐笔、实际lot归属、逐段首fill及逐空单窗口。', '',
        '## 验证、边界与复算', '',
        '入口为 `python -m studies.martin_luk.p3_research`：freeze → features → regimes → train → validate → behaviour → accounts → report → finish。'
        '每步均在任务书指定scope中、NumPy单线程运行，程序拒绝网络连接、子进程和工件目录外写入。'
        '截断重建、未来扰动、状态确认、反馈成熟、分档名额、首反抽消费和paired门禁有可运行检查。', '',
        'pipeline允许G3未过时成对研究signal＋allocate/trade，但必须声明selection_layer与selection_metric仍在上游。'
        '这验证的是轮次声明，不声称所有旧选择器自动按S排序；本轮以chosen.json先于账户、2026揭示的顺序保证。'
        '其他上游资料/工程卡未过仍不允许越过。SKILL/METHOD只补充已实现的自己池子/点名输入、票档/家族名额及paired覆盖主尺。', '',
        '完整四组测试和资源结果由finish核验后登记completion.json。既有登记/看板运行源码、配置及冻结结果保护清单逐项核SHA；'
        'P2A仅追加11-08更正，原文前缀逐字不变，原completion保留为当时快照。没有联网、拉数据、Git提交或登记采用。']
    used_states = read(OUT/f'regimes/{name}.json')
    lines += ['', '## 最终核验记录', '',
        '实际用于信号/账户的状态天数与段数：'+str(used_states['counts'])+'。'
        '单一常态与上文保留的失败三态诊断区分保存。', '',
        '预登记原文未改。`evaluation_fix.json`记录首锚点当晚票档的任务书对齐修正；'
        '只修评测标签与报告时点，信号源码、五套点名、首选及四预算成绩SHA均未变。'
        '修正发生在首次G2评测之前，原诊断的改前副本保留。'
        '另核对首次50EMA反抽的成交先后：原Z15成交位必须不低于前夜50EMA，才可在原成交位保留“已首次反抽50”的条件；'
        '不能用随后更高的日高追认早先较低的21EMA成交。此因果修正只涉及未启用的防守空头分支，'
        '五套B实际均为常态、空头为零，原账户工件未重跑或改写。', '',
        '| 测试组 | 项数 | 结果 |', '|---|---:|---|']
    for suite in ('custody', 'trader_replication', 'martin_luk', 'trader_screens'):
        path = OUT/f'tests/{suite}.log'
        match = re.search(r'Ran (\d+) tests? in ([\d.]+)s', path.read_text()) if path.exists() else None
        passed = (OUT/f'tests/{suite}.exit').exists() and (OUT/f'tests/{suite}.exit').read_text().strip() == '0'
        lines.append(f"| {suite} | {match[1] if match else '待核'} | {'通过' if passed and match else '待核'} |")
    if (OUT/'prefix_cleanup.json').exists():
        cleanup = read(OUT/'prefix_cleanup.json')
        lines += ['', f"首轮共享测试因磁盘空闲低于既有1GB保护线失败。清理本轮{cleanup['reclaimed_bytes']/1024**2:.1f} MiB"
            '重复截断校验数组后重跑；原始输入、校验结果和逐文件SHA保留，保护线未改。'
            '清单在prefix_cleanup.json，失败日志保留为trader_replication_initial.log。']
    (HOME/'reports/P3_CN.md').write_text('\n'.join(lines)+'\n')
    print('P3 report written', name, flush=True)


def finish():
    protocol = frozen()
    tests = {}
    for name in ('custody', 'trader_replication', 'martin_luk', 'trader_screens'):
        log = OUT/f'tests/{name}.log'
        text = log.read_text()
        match = re.search(r'Ran (\d+) tests? in ([\d.]+)s', text)
        code = int((OUT/f'tests/{name}.exit').read_text())
        assert code == 0 and match and re.search(r'^OK(?:\s|$)', text, re.M), (name, text[-1000:])
        tests[name] = dict(n=int(match[1]), seconds=float(match[2]), exit_code=code, sha256=sha(log))
    changed = [p for p, h in protocol['protected'].items() if not (ROOT/p).is_file() or sha(ROOT/p) != h]
    assert not changed, changed[:10]
    before = read(OUT/'P2A_before.json')
    after = (HOME/'reports/P2A_CN.md').read_text()
    assert after.startswith(before['text']) and '## 更正（11-08）' in after[len(before['text']):]
    fixes = read(OUT/'evaluation_fix.json')
    for p, h in read(OUT/'strategy_frozen.json').items():
        if p == 'studies/martin_luk/p3_research.py':
            assert fixes['runner_before'] == h and fixes['runner_after'] == sha(ROOT/p)
        else:
            assert sha(ROOT/p) == h, ('strategy source changed after running', p)
    for p, h in fixes['frozen_results'].items():
        assert sha(ROOT/p) == h, ('evaluation fix changed a frozen result', p)
    selected = read(OUT/'chosen.json')
    name = selected['chosen']
    result = read(OUT/f'results/{name}.json')
    modes = {m: read(OUT/f'accounts/{name}/{m}/summary.json') for m in ('A', 'B')}
    for candidate in S.CANDIDATES:
        assert sha(OUT/f'picks/{candidate}.json') == selected['picks_sha'][candidate]
    state = read(OUT/'regime_selection.json')
    evidence = read(OUT/'G2.json')['candidates'][name]['scopes']
    notes = {}
    for scope, data in evidence.items():
        notes[scope] = {metric: {s: dict(status=v['status'], p=v['p'], effect=v['effect'])
            for s, v in row['states'].items()} for metric, row in data['metrics'].items()}
    runs = {p.stem: read(p) for p in (OUT/'runs').glob('*.json')}
    complete = dict(task='PLAN_P3_CN', status='complete', chosen=name, tests=tests,
        prereg_sha256=sha(PREREG), report_sha256=sha(HOME/'reports/P3_CN.md'),
        regime=state, G2=notes, G3_pass=result['3']['annual']['2026']['coverage'] >= .8,
        yearly_K3=result['3']['annual'], accounts={m: dict(annual=v['annual'],
            holding=v['holding_coverage']['covered'], short=v['short_coverage']['covered']) for m, v in modes.items()},
        protected=dict(ok=True, files=len(protocol['protected']), changes=[]),
        P2A_original_prefix_unchanged=True, offline=True, downloaded_data=False,
        workspace_git_commits=0, registry_or_board_modified=False,
        maximum_recorded_rss_mib=max(r['resources']['peak_rss_mib'] for r in runs.values()), resources=resources())
    write(OUT/'sources.json', {p: h for r in runs.values() for p, h in r['sources'].items()})
    write(OUT/'completion.json', complete, True)
    lines = [f"行情稳定性：{state['minimum']:.2%}，"+('使用三态。' if state['enabled'] else '未过90%，使用单一常态。'),
        'G2：'+g2_conclusion(evidence),
        f'覆盖首选：{name}（2024/2025较差年，收益未参与选择）。',
        '2024/2025/2026 K=3：'+'；'.join(f"{result['3']['annual'][y]['covered']}/{result['3']['annual'][y]['n']}"
            f"（{result['3']['annual'][y]['coverage']:.1%}）" for y in YEARS)+'；2026留出*。',
        '距80%：'+'；'.join(f"{max(0., .8-result['3']['annual'][y]['coverage'])*100:.1f}个百分点" for y in YEARS)+'。',
        '持仓/空头覆盖：'+'；'.join(f"{m} {v['holding_coverage']['covered']}/48、{v['short_coverage']['covered']}/37" for m, v in modes.items())+'。']
    for m, v in modes.items():
        lines.append(m+'账户分年收益：'+'；'.join(f"{y} {v['annual'][y]['ret']:+.2%}" for y in YEARS)+'。')
    lines.append('四组测试通过；P3_CN.md及p3_work/completion.json已完成。')
    (OUT/'terminal_summary.txt').write_text('\n'.join(lines)+'\n')
    print('\n'.join(lines), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=('freeze', 'features', 'regimes', 'train', 'validate',
                                         'behaviour', 'accounts', 'report', 'finish'))
    args = parser.parse_args()
    offline()
    OUT.mkdir(parents=True, exist_ok=True)
    with (OUT/'run.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        r = resources()
        assert r['cpu_max'] == '60000 100000' and r['memory_max'] == str(900*1024*1024) and r['threads'] == '1', r
        print('start', args.stage, r, flush=True)
        globals()[args.stage]()
        write(OUT/f'runs/{args.stage}.json', dict(stage=args.stage, sources=SOURCES, resources=resources()))


if __name__ == '__main__':
    main()
