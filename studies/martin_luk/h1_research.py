"""H1 offline experiment, account scorecard, and reproducible acceptance stages."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from contextlib import contextmanager
from dataclasses import asdict, replace
import gc
import hashlib
import json
import os
from pathlib import Path
import resource
import sys
import time

import numpy as np

from . import m1_research as M, m2_research as M2, m3_research as M3, t1_research as T
from studies.trader_replication import mainleg, system as Y

ROOT, HOME = M.ROOT, M.HOME
OUT = HOME/'reports/h1_work'
PREREG = HOME/'notes/PREREG_H1_CN.md'
TRAIN, VALID, CUT = M.TRAIN, M.VALID, M.CUT
PREP = HOME/'reports/m1_work/prepared'
FULL = HOME/'reports/m1_work/validation_prepared'
read, sha, clean, log = M.read, M.sha, M.clean, M.log
CANDIDATES = {'H1A': dict(a=True, b=True, c=True, d=True, e=True, holding='R74'),
              'H1B': dict(a=True, b=True, c=True, d=True, e=True, holding='M3B')}
BASELINES = ('registered_master', 'M1B', 'M2A', 'M3B')
STRATEGY_ACTIVE = False
STRATEGY_READS = set()


def write(path, value):
    M.write(path if isinstance(path, Path) else OUT/path, value)


def resources():
    r = T.resources()
    assert r['cpu_max'] == '60000 100000' and r['memory_max'] == str(900*1024**2) and r['threads'] == 1, r
    return r


def offline():
    sys.dont_write_bytecode = True
    def guard(event, args):
        if event in ('socket.connect', 'socket.bind', 'socket.getaddrinfo', 'subprocess.Popen', 'os.system'):
            raise PermissionError('H1 is offline and single-process')
        if event == 'open' and not isinstance(args[0], int):
            p = Path(os.fsdecode(args[0])).resolve()
            if args[2] & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND):
                if not (p.is_relative_to(OUT.resolve()) or p == (HOME/'reports/H1_CN.md').resolve()):
                    raise PermissionError('H1 output boundary: '+str(p))
            elif STRATEGY_ACTIVE and p.is_relative_to(ROOT):
                safe = any(p.is_relative_to(q.resolve()) for q in (PREP, FULL,
                    HOME/'reports/m1_work/prefix_cut', HOME/'reports/m1_work/prefix_perturbed', T.PANEL))
                safe |= p.is_relative_to((OUT/'features').resolve()) or p.suffix in ('.py', '.pyc')
                if not safe:
                    raise PermissionError('H1 strategy cannot read labels or evaluation results: '+str(p))
                STRATEGY_READS.add(str(p.relative_to(ROOT)))
    sys.addaudithook(guard)


@contextmanager
def strategy_only():
    global STRATEGY_ACTIVE
    STRATEGY_ACTIVE = True
    try:
        yield
    finally:
        STRATEGY_ACTIVE = False


def once(stage):
    with (OUT/(stage+'_started.json')).open('x') as stream:
        json.dump(dict(time=time.time(), resources=resources(), source=sha(Path(__file__)),
                       memory=Path('/proc/meminfo').read_text()), stream)


def freeze():
    once('freeze')
    paths = [HOME/'notes/PLAN_H1_CN.md', HOME/'notes/legs_frozen.json', HOME/'notes/trades.csv',
             HOME/'replicate.py', HOME/'m1_research.py', HOME/'m2_research.py', HOME/'m3_research.py',
             HOME/'t1_research.py', ROOT/'skills/trader-replication/references/METHOD_CN.md']
    paths += list((ROOT/'studies/trader_screens').glob('*.py'))
    paths += [ROOT/'studies/trader_replication'/n for n in ('systems.py', 'mainleg.py', 'martin.py')]
    paths += list((HOME/'reports').glob('*.md'))
    for name in ('m1_work', 'm2_work', 'm3_work', 't1_work', 'd1_work', 'u1_work'):
        paths += [p for p in (HOME/'reports'/name).rglob('*') if p.is_file() and '__pycache__' not in str(p)]
    write('protocol.json', dict(task='PLAN_H1_CN', train=TRAIN, validation=VALID, cutoff=CUT,
          protected={str(p.relative_to(ROOT)): sha(p) for p in sorted(set(paths))}, resources=resources(),
          original_engine_sha256=sha(Path(Y.__file__)), independent_out_of_sample=False))
    (OUT/'original_system.py.txt').write_text(Path(Y.__file__).read_text())
    log('H1 protected inputs frozen')


def comparison(value, reference, scored=True):
    gap = (value/reference-1) if value is not None and reference not in (None, 0) else None
    return dict(his=reference, ours=value, relative_gap=gap,
                within20=abs(gap) <= .2+1e-12 if gap is not None else None, scored=scored)


def profit_overlap(rows, own_ids, year):
    """Nested sets use one positive-PnL denominator on the identical FIFO/time partition."""
    part = [r for r in rows if r['year'] == year]
    denominator = sum(max(0., r['pnl']) for r in part)
    own = sum(max(0., r['pnl']) for r in part if r['trade'] in own_ids)
    peers = sum(max(0., r['pnl']) for r in part if r.get('peer_h') and r['trade'] not in own_ids)
    assert -1e-12 <= own <= own+peers <= denominator+1e-12
    return own, peers, denominator


def evaluation_labels():
    """Called only after account simulation; never by policy construction or the engine."""
    frozen = read(HOME/'notes/legs_frozen.json')
    public = defaultdict(set)
    for r in frozen['audit']:
        if r['anchor']:
            public[r['anchor'][:4]].add(r['code'])
    broad = {g['key'] for g in read(HOME/'reports/t1_work/groups_summary.json')['legs'] if g['overwide_nights']}
    records = T.load_groups()
    for r in records.values():
        r['groups'] = [g for g in r['groups'] if g['key'] not in broad]
    return frozen, public, records, broad


def scorecard(A, trades, curve, rules, span, labels=None):
    frozen, public, records, broad = labels or evaluation_labels()
    calendar, prices = list(map(str, A['days'])), M.Prices(A)
    normalized, residual = M.adapt(trades, calendar, rules, prices)
    equity = np.ones(len(calendar))
    di = {d: t for t, d in enumerate(calendar)}
    for d, e in zip(curve['days'], curve['equity']):
        equity[di[d]] = e
    available = [g for g in frozen['legs'] if g['first'] < len(calendar)]
    other = [g for g in frozen['other_legs'] if g['first'] < len(calendar)]
    rows = mainleg.attribute_lots(normalized, available, prices, calendar, other,
        {(r['code'], r['anchor'][:4]) for r in frozen['audit'] if r['anchor']})
    coverage = mainleg.account_coverage(rows, available, calendar)
    strict, daily = mainleg.account_purity(rows, normalized, calendar, prices, equity)
    cutoffs = T.peer_cutoffs(rows, records, {g['key']: g for g in frozen['legs']}, prices.ci, 'correlation')
    peer_rows = T.relabel(rows, prices, cutoffs)
    theme, _ = mainleg.account_purity(peer_rows, normalized, calendar, prices, equity)
    # Every piece is counted once; the public ticker definition intentionally includes off-leg trades.
    # Capital uses calendar-year public names and entry-frozen narrow peers, including cash days.
    capital = {y: [0., 0., 0.] for y in public}
    ci = prices.ci
    for t, day in enumerate(calendar):
        if not span[0] <= day <= span[1]:
            continue
        own_value = peer_value = 0.
        for r in rows:
            if r['entry'] <= t < r['exit'] or (r['open'] and r['entry'] <= t <= r['exit']):
                if not r['code'].startswith('SHORT:') and r['code'] in public[day[:4]]:
                    own_value += r['shares']*float(prices[r['code']]['c'][t])
        for r, cutoff in zip(rows, cutoffs):
            if (not r['code'].startswith('SHORT:') and r['code'] not in public[day[:4]] and
                    r['entry'] <= t <= cutoff and (t < r['exit'] or r['open'])):
                peer_value += r['shares']*float(prices[r['code']]['c'][t])
        capital[day[:4]][0] += own_value
        capital[day[:4]][1] += own_value+peer_value
        capital[day[:4]][2] += float(daily['gross'][t])
    years = {}
    yearly_returns = Y.stats(np.array(curve['equity']), np.array(curve['days']), trades)['by_year']
    for year in sorted(yearly_returns):
        part = [t for t in trades if t['entry'][:4] == year]
        closed = [t for t in part if t['why'] != 'end']
        wins, losses = [t for t in closed if t['pnl'] > 0], [t for t in closed if t['pnl'] <= 0]
        avgwin = float(np.mean([t['ret'] for t in wins])) if wins else None
        avgloss = float(np.mean([t['ret'] for t in losses])) if losses else None
        references = dict(win=104/423 if year == '2024' else 209/940 if year == '2025' else None,
                          avg_win=.15, avg_loss=-.03, payoff=5., trades=420 if year == '2024' else 940 if year == '2025' else None)
        values = dict(win=len(wins)/len(closed) if closed else None, avg_win=avgwin, avg_loss=avgloss,
                      payoff=avgwin/abs(avgloss) if avgwin is not None and avgloss else None, trades=len(part))
        checks = {k: comparison(v, references[k]) for k, v in values.items()}
        checks['holding_win'] = comparison(float(np.mean([t['days'] for t in wins])) if wins else None, None, False)
        checks['holding_loss'] = comparison(float(np.mean([t['days'] for t in losses])) if losses else None, None, False)
        own_ids = {i for i, t in enumerate(trades) if t['side'] > 0 and t['entry'][:4] == year and t['code'] in public[year]}
        peer_ids = {r['trade'] for r, cutoff in zip(rows, cutoffs) if r['year'] == year and cutoff >= r['entry']}
        ids = own_ids | peer_ids
        own_gp, peer_gp, gp = profit_overlap(peer_rows, own_ids, year)
        cap = capital[year]
        shares = dict(public_trades=len(own_ids)/len(part) if part else None,
            public_capital=cap[0]/cap[2] if cap[2] else None, public_profit=own_gp/gp if gp else None,
            narrow_trades=len(ids)/len(part) if part else None,
            narrow_capital=cap[1]/cap[2] if cap[2] else None,
            narrow_profit=(own_gp+peer_gp)/gp if gp else None)
        # These are descriptive public-sample overlaps, not observed full-book statistics for him.
        checks.update({k: comparison(v, 1., False) for k, v in shares.items()})
        legs = [g for g in coverage if g['year'] == year]
        early, any_ = sum(g['covered'] for g in legs), sum(g['any'] for g in legs)
        pnl = sum(g['pnl'] for g in legs)
        checks['early_legs'] = comparison(early/len(legs) if legs else None, 1., False)
        checks['any_legs'] = comparison(any_/len(legs) if legs else None, 1., False)
        checks['leg_pnl'] = comparison(pnl, None, False)
        his_return = {'2024': 2.83, '2025': 9.70, '2026': 8.69}[year]
        checks['return'] = comparison(yearly_returns[year], his_return, False)
        years[year] = dict(checks=checks, score=sum(v['within20'] is True for v in checks.values() if v['scored']),
            scored_items=sum(v['scored'] and v['his'] is not None for v in checks.values()),
            nonnegative=yearly_returns[year] >= 0, closed=len(closed), wins=len(wins), losses=len(losses),
            early=early, any=any_, leg_count=len(legs), positive_legs=sum(g['pnl'] > 0 for g in legs),
            strict=strict[year], narrow=theme[year], narrow_profit_share=shares['narrow_profit'],
            public_names=sorted(public[year]), long_trades=sum(t['side'] > 0 for t in part),
            gross_profit=gp, public_gross_profit=own_gp, peer_gross_profit=peer_gp,
            return_ratio=yearly_returns[year]/his_return)
    return dict(years=years, legs=coverage, adapter_residual=residual, excluded_peer_legs=sorted(broad)), rows


def baseline():
    once('baseline')
    A, result = M.load_arrays(FULL), {}
    labels = evaluation_labels()
    train_paths = dict(registered_master='m1_work/baseline/native_master', M1B='m1_work/candidates/M1B',
                       M2A='m2_work/candidates/M2A', M3B='m3_work/candidates/M3B')
    for horizon in ('train', 'continuous'):
        result[horizon] = {}
        for name in BASELINES:
            paths = T.book_paths(T.BOOKS[name][0]) if horizon == 'continuous' else {
                s: HOME/'reports'/train_paths[name]/(s+'.json') for s in ('trades', 'curve')}
            trades, curve = read(paths['trades']), read(paths['curve'])
            rule_path = HOME/'reports/d1_work/master_metadata.json' if name == 'registered_master' else paths['trades'].parent/'rules.json'
            raw = read(rule_path)
            rules = Y.Rules(**(raw['rules'] if name == 'registered_master' else raw))
            folder = OUT/'baseline'/horizon/name
            write(folder/'trades.json', trades)
            write(folder/'curve.json', curve)
            write(folder/'rules.json', asdict(rules))
            span = TRAIN if horizon == 'train' else (TRAIN[0], VALID[1])
            result[horizon][name], rows = scorecard(A, trades, curve, rules, span, labels)
            write(folder/'scorecard.json', result[horizon][name])
            write(folder/'lots.json', rows)
            log('scorecard B baseline: '+horizon+'/'+name)
    write('baseline_scorecards.json', result)
    write('baseline_complete.json', dict(resources=resources(), account_simulations=0))


def register():
    once('register')
    assert read(OUT/'baseline_complete.json')
    paths = [HOME/'h1_policy.py', Path(Y.__file__), Path(__file__), HOME/'tests/test_h1.py']
    write('candidates.json', dict(specs=CANDIDATES, prereg_sha256=sha(PREREG),
          code_sha256={str(p.relative_to(ROOT)): sha(p) for p in paths}))


def registry_check():
    r = read(OUT/'candidates.json')
    assert sha(PREREG) == r['prereg_sha256'], 'preregistration changed'
    current = {p: sha(ROOT/p) for p in r['code_sha256']}
    if current != r['code_sha256']:
        correction = read(OUT/'source_compatibility.json')
        assert correction['registered_code_sha256'] == r['code_sha256']
        assert correction['corrected_code_sha256'] == current
        assert correction['registry_sha256'] == sha(OUT/'candidates.json')
        assert correction['prereg_sha256'] == sha(PREREG)
        assert [p for p in current if current[p] != r['code_sha256'][p]] == [str(Path(__file__).relative_to(ROOT))]
    return r


def arrays(directory):
    A = M.load_arrays(directory)
    from . import luk
    for name, n in (('e9', 9), ('e21', 21)):
        A['native_'+name] = luk.ema(A['close'].astype(float), n)
    return A


class Future:
    """Perturb only requested future slices, keeping the source mmap read-only."""
    def __init__(self, a, multiplier, cutoff):
        self.a, self.multiplier, self.cutoff = a, multiplier, cutoff

    def __getitem__(self, key):
        value = np.array(self.a[key], copy=True)
        first = key[0] if isinstance(key, tuple) else key
        if isinstance(first, slice):
            start, stop, step = first.indices(len(self.a))
            value[np.arange(start, stop, step) >= self.cutoff] *= self.multiplier
        elif first >= self.cutoff:
            value *= self.multiplier
        return value


def market_panel(A, variant):
    result = {n: np.load(T.PANEL/(n+'.npy'), mmap_mode='r')[:len(A['days'])]
              for n in ('close', 'high', 'low', 'raw_close', 'turnover', 'volume')}
    if variant == 'perturbed':
        cutoff = int(np.searchsorted(A['days'], CUT, side='right'))
        result = {n: Future(v, 2 if n == 'volume' else 6 if n == 'turnover' else 3, cutoff)
                  for n, v in result.items()}
    return result


def feature_set(A, variant):
    from . import h1_policy as H
    folder = OUT/'features'/variant
    if (folder/'complete.json').exists():
        return {n: np.load(folder/(n+'.npy'), mmap_mode='r') for n in
                ('attention', 'familiar', 'events', 'episodes', 'score', 'pool')} | {
                    n: read(folder/(n+'.json')) for n in ('groups', 'stats')}
    with strategy_only():
        result = H.features(A, market_panel(A, variant))
    folder.mkdir(parents=True, exist_ok=True)
    for n, v in result.items():
        if isinstance(v, np.ndarray):
            np.save(folder/(n+'.npy'), v)
        else:
            write(folder/(n+'.json'), v)
    write(folder/'complete.json', dict(resources=resources(), days=len(A['days']), variant=variant,
          hashes={p.name: sha(p) for p in folder.iterdir() if p.is_file()}))
    log('market-only features prepared: '+variant)
    return result


def compatibility():
    once('compatibility')
    A, checks = arrays(FULL), {}
    specs = read(HOME/'reports/m3_work/candidates.json')['specs']
    for name in BASELINES:
        if name == 'registered_master':
            book = M.load_book(FULL, 'native')
            rules = Y.Rules(**read(FULL/'master_rules.json'))
            ema = dict(e9=A['native_e9'], e21=A['native_e21'], idx_pb16=A['idx_pb16'])
        elif name == 'M1B':
            book, rules, ema = M.build(A, FULL, M2.BASE)
        elif name == 'M2A':
            book, rules, ema = M2.build(A, FULL, M3.BASE)
        else:
            book, rules, ema = M3.build(A, FULL, specs['M3B'])
        px = dict(dates=A['days'], codes=A['codes'], **{n: A[n].astype(float) for n in ('open', 'high', 'low', 'close')})
        curve, dates, trades = Y.simulate(px, ema, rules, book, TRAIN[0], VALID[1], audit=True)
        expected = OUT/'baseline/continuous'/name
        checks[name] = dict(trades=clean(trades) == read(expected/'trades.json'),
            curve=clean(dict(days=dates, equity=curve)) == read(expected/'curve.json'),
            executions=sum(len(t['executions']) for t in trades))
        write('compatibility/'+name+'/trades.json', trades)
        write('compatibility/'+name+'/curve.json', dict(days=dates, equity=curve))
        assert checks[name]['trades'] and checks[name]['curve'], (name, checks[name])
        log('complete original ledger exact: '+name)
        del px, book, ema, curve, trades
        gc.collect()
    write('compatibility.json', dict(ok=True, checks=checks, resources=resources()))


def simulate(A, directory, f, spec, span, destination=None):
    from . import h1_policy as H
    with strategy_only():
        book, rules, ema, groups = H.build(A, directory, f, spec)
        px = dict(dates=A['days'], codes=A['codes'], entry_groups=groups,
                  **{n: A[n].astype(float) for n in ('open', 'high', 'low', 'close')})
        attempts = None
        track = {}
        if destination:
            destination.mkdir(parents=True, exist_ok=True)
            # Preserve complete held-name snapshots for the requested crowding diagnosis.
            class Attempts(M.AttemptStream):
                def flush(self):
                    if self.pending is not None:
                        self.counts[self.pending['reason']] += 1
                        self.stream.write(json.dumps(clean(self.pending), ensure_ascii=False)+'\n')
                        self.pending = None
            attempts = Attempts(destination/'attempts.jsonl')
            track['entry_attempts'] = attempts
        try:
            curve, dates, trades = Y.simulate(px, ema, rules, book, *span, audit=True, track=track)
        finally:
            if attempts:
                attempts.close()
    result_curve = dict(days=dates, equity=curve)
    if destination:
        write(destination/'trades.json', trades)
        write(destination/'curve.json', result_curve)
        write(destination/'rules.json', asdict(rules))
        write(destination/'attempt_counts.json', attempts.counts)
        write(destination/'management.json', {k: v for k, v in track.items() if k != 'entry_attempts'})
        terminal = sum(e['shares']*e['price']*(rules.sell_cost if t['side'] > 0 else rules.buy_cost)
                       for t in trades for e in t['executions'] if e['action'] == 'end')
        error = sum(t['pnl'] for t in trades)+terminal-track['margin']-(curve[-1]-1)
        assert abs(error) < 1e-9, error
        write(destination/'reconciliation.json', dict(error=error, financing=track['margin'], terminal_fee=terminal))
    return trades, result_curve, rules, book


def run(A, directory, f, name, spec, span=TRAIN):
    destination = OUT/name
    trades, curve, rules, _ = simulate(A, directory, f, spec, span, destination)
    result, rows = scorecard(A, trades, curve, rules, span)
    write(destination/'scorecard.json', result)
    write(destination/'lots.json', rows)
    log(name+': '+str({y: dict(return_=round(v['checks']['return']['ours'], 4), trades=v['checks']['trades']['ours'],
        score=v['score'], narrow_profit=round(v['narrow_profit_share'] or 0., 4)) for y, v in result['years'].items()}))
    return result


def select(results):
    def key(name):
        rows = [results[name]['years'][y] for y in ('2024', '2025')]
        return (-min(r['score'] for r in rows), -min(r['narrow_profit_share'] or 0. for r in rows), name)
    eligible = sorted((n for n in results if all(results[n]['years'][y]['nonnegative'] for y in ('2024', '2025'))), key=key)
    return dict(chosen=next(iter(eligible), None), eligible=eligible,
                diagnostic_first=sorted(results, key=key)[0],
                ranking={n: key(n) for n in results}, only_training_used=True)


def candidates():
    once('candidates')
    registry_check()
    assert read(OUT/'compatibility.json')['ok']
    with strategy_only():
        A = arrays(PREP)
    f, results = feature_set(A, 'train'), {}
    for name, spec in CANDIDATES.items():
        results[name] = run(A, PREP, f, 'candidates/'+name, spec)
    write('candidates_train.json', results)
    write('selection.json', select(results))
    write('strategy_reads.json', sorted(STRATEGY_READS))
    write('candidates_complete.json', dict(resources=resources(), candidate_accounts=len(results)))


def ablate():
    once('ablation')
    registry_check()
    choice = read(OUT/'selection.json')
    selected = choice['chosen'] or choice['diagnostic_first']
    spec = CANDIDATES[selected]
    with strategy_only():
        A = arrays(PREP)
    f, results = feature_set(A, 'train'), {}
    arms = {'without_'+k: dict(spec, **{k: False}) for k in 'abcde'}
    arms['only_ab'] = dict(spec, c=False, d=False, e=False)
    for name, arm in arms.items():
        results[name] = run(A, PREP, f, 'ablation/'+name, arm)
        gc.collect()
    write('ablation.json', dict(base=selected, diagnostics_only=True, specs=arms, results=results))
    write('ablation_complete.json', dict(resources=resources(), arms=len(arms)))


def prefix_value(A, directory, variant, spec):
    f = feature_set(A, variant)
    trades, curve, _, book = simulate(A, directory, f, spec, TRAIN)
    k = int(np.searchsorted(A['days'], CUT, side='right'))
    features = {n: hashlib.sha256(np.ascontiguousarray(f[n][:k]).tobytes()).hexdigest()
                for n in ('attention', 'familiar', 'events', 'episodes', 'score', 'pool')}
    return clean(dict(book=book[:k], groups=f['groups'][:k], features=features,
        events=M.E15.B.execution_events(trades, CUT),
        curve=[float(v) for d, v in zip(curve['days'], curve['equity']) if d <= CUT]))


def prefix():
    once('prefix')
    registry_check()
    selected = read(OUT/'selection.json')['chosen']
    if not selected:
        write('prefix.json', dict(skipped=True, reason='no nonnegative candidate'))
        return
    values = {}
    for variant, directory in (('train', PREP), ('cut', HOME/'reports/m1_work/prefix_cut'),
                               ('perturbed', HOME/'reports/m1_work/prefix_perturbed')):
        with strategy_only():
            A = arrays(directory)
        values[variant] = prefix_value(A, directory, variant, CANDIDATES[selected])
        write('prefix_'+variant+'.json', values[variant])
        del A
        gc.collect()
    checks = {v: {k: values[v][k] == values['train'][k] for k in values['train']} for v in ('cut', 'perturbed')}
    original = read(OUT/f'candidates/{selected}/trades.json')
    assert values['train']['events'] == clean(M.E15.B.execution_events(original, CUT))
    assert all(all(r.values()) for r in checks.values()), checks
    write('prefix.json', dict(ok=True, chosen=selected, cutoff=CUT, checks=checks,
        executions=len(values['train']['events']), resources=resources(),
        strategy_reads=sorted(STRATEGY_READS), new_features_independently_rebuilt=True))


def validate():
    registry_check()
    selected = read(OUT/'selection.json')['chosen']
    if not selected:
        write('validation_complete.json', dict(skipped=True, standalone_evaluations=0, continuous_evaluations=0))
        return
    assert read(OUT/'prefix.json')['ok']
    once('validation')
    with strategy_only():
        A = arrays(FULL)
    f, results = feature_set(A, 'full'), {}
    for label, span in (('standalone', VALID), ('continuous', (TRAIN[0], VALID[1]))):
        results[label] = run(A, FULL, f, 'validation/'+label, CANDIDATES[selected], span)
        write('validation.json', results)
    write('validation_complete.json', dict(chosen=selected, standalone_evaluations=1,
          continuous_evaluations=1, independent_out_of_sample=False, resources=resources(),
          strategy_reads=sorted(STRATEGY_READS)))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=('freeze', 'baseline', 'register', 'compatibility', 'candidates',
                                        'ablate', 'prefix', 'validate'))
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    offline()
    globals()[args.stage]()


if __name__ == '__main__':
    main()
