"""Offline H2 daily-tolerance experiment and frozen stage runner."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from contextlib import contextmanager
from dataclasses import asdict
import gc
import hashlib
import json
import os
from pathlib import Path
import sys
import time

import numpy as np

from . import h1_research as H1, m1_research as M, t1_research as T
from studies.trader_replication import system as Y

ROOT, HOME = M.ROOT, M.HOME
OUT = HOME/'reports/h2_work'
PREREG = HOME/'notes/PREREG_H2_CN.md'
TRAIN, VALID, CUT, PREP, FULL = H1.TRAIN, H1.VALID, H1.CUT, H1.PREP, H1.FULL
read, sha, clean, log, resources = M.read, M.sha, M.clean, M.log, H1.resources
CANDIDATES = {'H2A': dict(buffer=.5, disaster=2.), 'H2B': dict(buffer=1., disaster=3.)}
BASELINES = ('registered_master', 'M1B', 'M2A', 'M3B', 'H1A', 'H1B')
STRATEGY_ACTIVE, STRATEGY_READS = False, set()


def write(path, value):
    M.write(path if isinstance(path, Path) else OUT/path, value)


def offline():
    sys.dont_write_bytecode = True
    def guard(event, args):
        if event in ('socket.connect', 'socket.bind', 'socket.getaddrinfo', 'subprocess.Popen', 'os.system'):
            raise PermissionError('H2 is offline and single-process')
        if event == 'open' and not isinstance(args[0], int):
            p = Path(os.fsdecode(args[0])).resolve()
            if args[2] & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND):
                if not (p.is_relative_to(OUT.resolve()) or p == (HOME/'reports/H2_CN.md').resolve()):
                    raise PermissionError('H2 output boundary: '+str(p))
            elif STRATEGY_ACTIVE and p.is_relative_to(ROOT):
                roots = (PREP, FULL, HOME/'reports/m1_work/prefix_cut', HOME/'reports/m1_work/prefix_perturbed',
                         T.PANEL, ROOT/'data/martin-luk-benchmarks-v1', OUT/'features')
                if not (any(p.is_relative_to(q.resolve()) for q in roots) or p.suffix in ('.py', '.pyc')):
                    raise PermissionError('H2 strategy cannot read evaluation labels: '+str(p))
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
        json.dump(dict(time=time.time(), resources=resources(), source=sha(Path(__file__))), stream)


def freeze():
    once('freeze')
    paths = [p for p in (HOME/'reports').glob('*.md')]
    for folder in ('m1_work', 'm2_work', 'm3_work', 'h1_work', 'd1_work', 't1_work', 'u1_work'):
        paths += [p for p in (HOME/'reports'/folder).rglob('*') if p.is_file() and '__pycache__' not in str(p)]
    paths += [p for p in HOME.glob('*.py') if not p.name.startswith('h2_')]
    paths += list((ROOT/'studies/trader_screens').glob('*.py'))
    paths += [ROOT/'studies/trader_replication'/n for n in ('mainleg.py', 'systems.py', 'martin.py')]
    paths += [HOME/'notes'/n for n in ('PLAN_H2_CN.md', 'TRANSLATION_CN.md', 'RULES_CN.md', 'trades.csv', 'legs_frozen.json')]
    paths += list((ROOT/'data/martin-luk-benchmarks-v1').glob('*.csv'))
    write('protocol.json', dict(task='PLAN_H2_CN', train=TRAIN, validation=VALID, cutoff=CUT,
        protected={str(p.relative_to(ROOT)): sha(p) for p in sorted(set(paths))},
        prereg_sha256=sha(PREREG), resources=resources(), independent_out_of_sample=False))
    (OUT/'original_system.py.txt').write_text(Path(Y.__file__).read_text())
    log('H2 inputs and prior accounts frozen')


def arrays(directory):
    A = H1.arrays(directory)
    from . import luk
    A['native_e50'] = luk.ema(A['close'].astype(float), 50)
    return A


def feature_set(A, variant):
    from . import h2_policy as H
    folder = OUT/'features'/variant
    if (folder/'complete.json').exists():
        return {p.stem: np.load(p, mmap_mode='r') for p in folder.glob('*.npy')} | \
            {n: read(folder/(n+'.json')) for n in ('groups', 'stats')}
    with strategy_only():
        p = H1.market_panel(A, variant)
        from studies.trader_data import supplemental as SP
        qqq, sources = SP.benchmark('US.QQQ', A['days'], 'frozen')
        if variant == 'perturbed':
            qqq[np.searchsorted(A['days'], CUT, side='right'):] *= 3
        f = H.features(A, p, qqq)
    folder.mkdir(parents=True, exist_ok=True)
    for n, value in f.items():
        if isinstance(value, np.ndarray):
            np.save(folder/(n+'.npy'), value)
        else:
            write(folder/(n+'.json'), value)
    write(folder/'complete.json', dict(resources=resources(), sources=sources, days=len(A['days']),
        files={p.name: sha(p) for p in folder.iterdir() if p.is_file()}))
    log('H2 market features: '+variant)
    return f


def book_statistics(A, trades, curve, rules, memberships):
    """Reconstruct real closing holdings and long/short calendar-year PnL from executions."""
    ci = {str(c): j for j, c in enumerate(A['codes'])}
    di = {str(d): i for i, d in enumerate(A['days'])}
    events, cohorts = defaultdict(list), defaultdict(list)
    entries = sorted((t for t in trades if t['side'] > 0), key=lambda t: (t['entry'], t['code']))
    previous, repeats = {}, Counter()
    for t in entries:
        d, j = di[t['entry']], ci[t['code']]
        prior = previous.get(t['code'])
        if prior is not None and d-prior <= 30:
            repeats[t['entry'][:4]] += 1
        previous[t['code']] = d
        if j in memberships[d]:
            cohorts[(t['entry'], memberships[d][j])].append(t['code'])
    for t in trades:
        for e in t['executions']:
            if e['action'] != 'end':
                events[e['time']].append((ci[t['code']], t['side'], e))
    holdings, cash, prior_equity = {}, 1., 1.
    years, daily, max_error = {}, [], 0.
    for day, expected in zip(curve['days'], curve['equity']):
        d, year = di[day], day[:4]
        row = years.setdefault(year, dict(sessions=0, long_count=0, top3=0., long_value=0.,
            long_pnl=0., short_pnl=0., financing=0., year_open_equity=prior_equity, max_long=0))
        def mark(j, t):
            while t > 0 and not np.isfinite(A['close'][t, j]):
                t -= 1
            return float(A['close'][t, j])
        long_prev = sum(qty*mark(j, d-1) for j, (side, qty) in holdings.items() if side > 0)
        margin = rules.margin_rate/252*max(0., long_prev-prior_equity)
        cash -= margin
        row['financing'] += margin
        for j, (side, qty) in holdings.items():
            change = qty*(mark(j, d)-mark(j, d-1))*side
            if side < 0:
                borrow = qty*mark(j, d-1)*rules.borrow_rate/252
                cash -= borrow
                change -= borrow
            row['long_pnl' if side > 0 else 'short_pnl'] += change
        for j, side, e in events[day]:
            buy = e['action'] in ('entry', 'add')
            qty, price = e['shares'], e['price']
            delta = qty if buy else -qty
            rate = rules.buy_cost if (buy == (side > 0)) else rules.sell_cost
            fee = qty*price*rate
            cash -= side*delta*price+fee
            row['long_pnl' if side > 0 else 'short_pnl'] += side*delta*(mark(j, d)-price)-fee
            old = holdings.get(j, (side, 0.))
            assert old[0] == side or abs(old[1]) < 1e-12
            size = old[1]+delta
            if abs(size) < 1e-12:
                holdings.pop(j, None)
            else:
                holdings[j] = (side, size)
        values = sorted((qty*mark(j, d) for j, (side, qty) in holdings.items() if side > 0), reverse=True)
        equity = cash+sum(side*qty*mark(j, d) for j, (side, qty) in holdings.items())
        max_error = max(max_error, abs(equity-expected))
        assert abs(equity-expected) < 1e-8, (day, equity, expected)
        row['sessions'] += 1
        row['long_count'] += len(values)
        row['max_long'] = max(row['max_long'], len(values))
        row['top3'] += sum(values[:3])
        row['long_value'] += sum(values)
        daily.append(dict(day=day, long_count=len(values), long_value=sum(values), top3=sum(values[:3])))
        prior_equity = expected
    for y, row in years.items():
        ts = [t for t in entries if t['entry'][:4] == y]
        closed = [t for t in ts if t['why'] != 'end']
        wins, losses = [t for t in closed if t['pnl'] > 0], [t for t in closed if t['pnl'] <= 0]
        grouped = sum(len(v) for (day, _), v in cohorts.items() if day[:4] == y and len(v) >= 2)
        row.update(avg_long=row['long_count']/row['sessions'],
            top3_share=row['top3']/row['long_value'] if row['long_value'] else None,
            repeat_share=repeats[y]/len(ts) if ts else None,
            grouped_share=grouped/len(ts) if ts else None, long_entries=len(ts),
            long_win=len(wins)/len(closed) if closed else None,
            long_avg_win=float(np.mean([t['ret'] for t in wins])) if wins else None,
            long_avg_loss=float(np.mean([t['ret'] for t in losses])) if losses else None,
            long_contribution=row['long_pnl']/row['year_open_equity'],
            short_contribution=row['short_pnl']/row['year_open_equity'],
            financing_contribution=row['financing']/row['year_open_equity'])
    return dict(years=years, daily=daily, max_equity_error=max_error)


def scorecard(A, trades, curve, rules, f, span, original=None):
    card, rows = H1.scorecard(A, trades, curve, rules, span) if original is None else original
    memberships = [{j: k for k, g in enumerate(row) for j in g['members']} for row in f['groups']]
    habits = book_statistics(A, trades, curve, rules, memberships)
    for y, r in card['years'].items():
        r['habits'] = habits['years'][y]
        closed = [t for t in trades if t['entry'][:4] == y and t['why'] != 'end']
        wins = [t for t in closed if t['pnl'] > 0]
        losses = [t for t in closed if t['pnl'] <= 0]
        holding = float(np.median([t['days'] for t in wins])) if wins else None
        h = r['habits']
        values = dict(payoff=r['checks']['payoff']['ours'], avg_win=r['checks']['avg_win']['ours'],
            avg_long=h['avg_long'], top3_share=h['top3_share'], repeat_share=h['repeat_share'], holding_win=holding)
        passes = dict(payoff=values['payoff'] is not None and values['payoff'] >= 4,
            avg_win=values['avg_win'] is not None and values['avg_win'] >= .1,
            avg_long=h['avg_long'] <= 5, top3_share=h['top3_share'] is not None and h['top3_share'] >= .6,
            repeat_share=h['repeat_share'] is not None and .1 <= h['repeat_share'] <= .3,
            holding_win=holding is not None and 5 <= holding <= 30)
        hard = dict(nonnegative=r['nonnegative'], win=r['checks']['win']['ours'] is not None and r['checks']['win']['ours'] <= .35,
                    trades=r['checks']['trades']['ours'] >= 52)
        legs = [g for g in card['legs'] if g['year'] == y]
        potential = sum(g['potential_total'] for g in legs)
        r.update(b_values=values, b_checks=passes, b_score=sum(passes.values()), hard=hard,
            capture_total=sum(g['pnl'] for g in legs)/potential if potential else None,
            avg_win_invested=float(np.mean([t['ret_invested'] for t in wins])) if wins else None,
            avg_loss_invested=float(np.mean([t['ret_invested'] for t in losses])) if losses else None)
    card['holdings_reconstruction_error'] = habits['max_equity_error']
    return card, rows, habits


def baseline():
    once('baseline')
    with strategy_only():
        A = arrays(PREP)
    f, results = feature_set(A, 'train'), {}
    for name in BASELINES:
        source = H1.OUT/('baseline/train' if name in H1.BASELINES else 'candidates')/name
        folder = OUT/'baseline/train'/name
        trades, curve, rules = (read(source/(n+'.json')) for n in ('trades', 'curve', 'rules'))
        for n, v in dict(trades=trades, curve=curve, rules=rules).items():
            write(folder/(n+'.json'), v)
        original = read(source/'scorecard.json'), read(source/'lots.json')
        result, rows, habits = scorecard(A, trades, curve, Y.Rules(**rules), f, TRAIN, original)
        for n, v in dict(scorecard=result, lots=rows, habits=habits).items():
            write(folder/(n+'.json'), v)
        results[name] = result
        log('H2 common scorecard: '+name)
    write('baseline_scorecards.json', results)
    write('baseline_complete.json', dict(resources=resources(), account_simulations=0))


def compatibility():
    once('compatibility')
    A, checks = H1.arrays(FULL), {}
    specs = read(HOME/'reports/m3_work/candidates.json')['specs']
    for name in BASELINES:
        if name == 'registered_master':
            book, rules = M.load_book(FULL, 'native'), Y.Rules(**read(FULL/'master_rules.json'))
            ema = dict(e9=A['native_e9'], e21=A['native_e21'], idx_pb16=A['idx_pb16'])
        elif name == 'M1B':
            book, rules, ema = M.build(A, FULL, H1.M2.BASE)
        elif name == 'M2A':
            book, rules, ema = H1.M2.build(A, FULL, H1.M3.BASE)
        elif name == 'M3B':
            book, rules, ema = H1.M3.build(A, FULL, specs['M3B'])
        else:
            from . import h1_policy as H
            f = H1.feature_set(A, 'train')
            # H1's original training features and ledger stop before 2026.
            Atrain = H1.arrays(PREP)
            book, rules, ema, groups = H.build(Atrain, PREP, f, H1.CANDIDATES[name])
        actual_A = Atrain if name.startswith('H1') else A
        span = TRAIN if name.startswith('H1') else (TRAIN[0], VALID[1])
        px = dict(dates=actual_A['days'], codes=actual_A['codes'],
            **{n: actual_A[n].astype(float) for n in ('open', 'high', 'low', 'close')})
        if name.startswith('H1'):
            px['entry_groups'] = groups
        curve, dates, trades = Y.simulate(px, ema, rules, book, *span, audit=True)
        ref = H1.OUT/('candidates/'+name if name.startswith('H1') else 'baseline/continuous/'+name)
        actual = dict(trades=clean(trades), curve=clean(dict(days=dates, equity=curve)))
        checks[name] = {}
        for field, value in actual.items():
            expected = read(ref/(field+'.json'))
            assert value == expected, (name, field)
            canonical = json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)
            checks[name][field] = dict(exact=True, canonical_sha256=hashlib.sha256(canonical.encode()).hexdigest())
            write(OUT/'compatibility'/name/(field+'.json'), value)
        log('original full ledger exact: '+name)
        del px, book, ema, trades, curve
        if name.startswith('H1'):
            del Atrain, f
        gc.collect()
    write('compatibility.json', dict(ok=True, checks=checks, resources=resources()))


def register():
    once('register')
    assert read(OUT/'compatibility.json')['ok']
    paths = [HOME/'h2_policy.py', Path(__file__), Path(Y.__file__), HOME/'tests/test_h2.py',
             HOME/'notes/H2_THEME_CAP_CORRECTION_CN.md']
    write('candidates.json', dict(specs=CANDIDATES, prereg_sha256=sha(PREREG),
        execution_correction_sha256=sha(HOME/'notes/H2_EXECUTION_CORRECTION_CN.md'),
        code_sha256={str(p.relative_to(ROOT)): sha(p) for p in paths}))


def registry_check():
    r = read(OUT/'candidates.json')
    assert sha(PREREG) == r['prereg_sha256']
    assert sha(HOME/'notes/H2_EXECUTION_CORRECTION_CN.md') == r['execution_correction_sha256']
    assert all(sha(ROOT/p) == h for p, h in r['code_sha256'].items()), 'H2 frozen implementation changed'


def simulate(A, directory, f, spec, span, destination=None):
    from . import h2_policy as H
    with strategy_only():
        book, rules, ema, tolerance = H.build(A, directory, f, spec)
        px = dict(dates=A['days'], codes=A['codes'], **{n: A[n].astype(float) for n in ('open', 'high', 'low', 'close')})
        track = {'daily_margin': []}
        attempts = None
        if destination:
            destination.mkdir(parents=True, exist_ok=True)
            class Attempts(M.AttemptStream):
                def flush(self):
                    if self.pending is not None:
                        self.counts[self.pending['reason']] += 1
                        self.stream.write(json.dumps(clean(self.pending), ensure_ascii=False)+'\n')
                        self.pending = None
            attempts = Attempts(destination/'attempts.jsonl')
            track['entry_attempts'] = attempts
        try:
            curve, dates, trades = Y.simulate(px, ema, rules, book, *span, audit=True, track=track,
                                            daily_tolerance=tolerance)
        finally:
            if attempts:
                attempts.close()
    result_curve = dict(days=dates, equity=curve)
    if destination:
        for n, v in dict(trades=trades, curve=result_curve, rules=asdict(rules), policy=spec,
            management={k: v for k, v in track.items() if k != 'entry_attempts'}, attempt_counts=attempts.counts).items():
            write(destination/(n+'.json'), v)
        terminal = sum(e['shares']*e['price']*(rules.sell_cost if t['side'] > 0 else rules.buy_cost)
                       for t in trades for e in t['executions'] if e['action'] == 'end')
        error = sum(t['pnl'] for t in trades)+terminal-track['margin']-(curve[-1]-1)
        assert abs(error) < 1e-9
        write(destination/'reconciliation.json', dict(error=error, financing=track['margin'], terminal_fee=terminal))
    return trades, result_curve, rules, book


def run(A, directory, f, name, spec, span=TRAIN):
    destination = OUT/name
    trades, curve, rules, _ = simulate(A, directory, f, spec, span, destination)
    result, rows, habits = scorecard(A, trades, curve, rules, f, span)
    for n, v in dict(scorecard=result, lots=rows, habits=habits).items():
        write(destination/(n+'.json'), v)
    log(name+': '+str({y: dict(return_=round(r['checks']['return']['ours'], 4), early=r['early'],
        capital=round(r['strict']['cap_equity'], 4), score=r['b_score']) for y, r in result['years'].items()}))
    return result


def select(results, baseline):
    failures = {}
    for n, value in results.items():
        failed = []
        for y in ('2024', '2025'):
            r, base = value['years'][y], baseline['years'][y]
            failed += [y+'_'+k for k, v in r['hard'].items() if not v]
            if r['early'] < base['early']:
                failed.append(y+'_early')
            if r['strict']['cap_equity']+1e-12 < base['strict']['cap_equity']:
                failed.append(y+'_capital')
        failures[n] = failed
    def key(n):
        rs = [results[n]['years'][y] for y in ('2024', '2025')]
        return (-min(r['early']/r['leg_count'] for r in rs),
                -min(r['strict']['purity_gross'] or 0. for r in rs), -min(r['b_score'] for r in rs),
                -min(r['checks']['payoff']['ours'] or 0. for r in rs), n)
    ranked = sorted(results, key=key)
    eligible = [n for n in ranked if not failures[n]]
    return dict(chosen=next(iter(eligible), None), eligible=eligible, failures=failures,
        ranking={n: key(n) for n in ranked}, diagnostic_first=ranked[0], only_training_used=True)


def candidates():
    once('candidates')
    registry_check()
    with strategy_only():
        A = arrays(PREP)
    f, results = feature_set(A, 'train'), {}
    for n, spec in CANDIDATES.items():
        results[n] = run(A, PREP, f, 'candidates/'+n, spec)
        write('candidates_train.json', results)
    write('selection.json', select(results, read(OUT/'baseline_scorecards.json')['registered_master']))
    write('strategy_reads.json', sorted(STRATEGY_READS))
    write('candidates_complete.json', dict(resources=resources(), accounts=len(results)))


def ablate():
    once('ablation')
    registry_check()
    choice = read(OUT/'selection.json')
    base = choice['chosen'] or choice['diagnostic_first']
    with strategy_only():
        A = arrays(PREP)
    f, results = feature_set(A, 'train'), {}
    arms = {'without_'+k: dict(CANDIDATES[base], **{k: False}) for k in ('theme', 'probe', 'limits', 'retry', 'feedback')}
    for n, spec in arms.items():
        results[n] = run(A, PREP, f, 'ablation/'+n, spec)
        write('ablation.json', dict(base=base, diagnostics_only=True, specs=arms, results=results))
        gc.collect()
    write('ablation_complete.json', dict(resources=resources(), accounts=len(results)))


def prefix():
    once('prefix')
    registry_check()
    choice = read(OUT/'selection.json')
    tested = choice['chosen'] or choice['diagnostic_first']
    values = {}
    for variant, directory in (('train', PREP), ('cut', HOME/'reports/m1_work/prefix_cut'),
                               ('perturbed', HOME/'reports/m1_work/prefix_perturbed')):
        with strategy_only():
            A = arrays(directory)
        f = feature_set(A, variant)
        trades, curve, _, book = simulate(A, directory, f, CANDIDATES[tested], TRAIN)
        k = int(np.searchsorted(A['days'], CUT, side='right'))
        hashes = {n: hashlib.sha256(np.ascontiguousarray(v[:k]).tobytes()).hexdigest()
                  for n, v in f.items() if isinstance(v, np.ndarray)}
        hashes.update({n: hashlib.sha256(np.ascontiguousarray(A[n][:k]).tobytes()).hexdigest()
                       for n in ('native_e9', 'native_e21', 'native_e50')})
        values[variant] = clean(dict(features=hashes, groups=f['groups'][:k], book=book[:k],
            events=M.E15.B.execution_events(trades, CUT),
            curve=[v for d, v in zip(curve['days'], curve['equity']) if d <= CUT]))
        write('prefix_'+variant+'.json', values[variant])
        del A, f, trades, curve, book
        gc.collect()
    checks = {v: {k: values[v][k] == values['train'][k] for k in values['train']} for v in ('cut', 'perturbed')}
    assert values['train']['events'] == clean(M.E15.B.execution_events(read(OUT/f'candidates/{tested}/trades.json'), CUT))
    assert all(all(r.values()) for r in checks.values()), checks
    write('prefix.json', dict(ok=True, selected=choice['chosen'], tested=tested, checks=checks, cutoff=CUT,
        executions=len(values['train']['events']), strategy_reads=sorted(STRATEGY_READS), resources=resources(),
        independent_rebuild=True))


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
    write('validation_complete.json', dict(chosen=selected, standalone_evaluations=1, continuous_evaluations=1,
        independent_out_of_sample=False, resources=resources(), strategy_reads=sorted(STRATEGY_READS)))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=('freeze', 'baseline', 'compatibility', 'register', 'candidates', 'ablate', 'prefix', 'validate'))
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    offline()
    globals()[args.stage]()


if __name__ == '__main__':
    main()
