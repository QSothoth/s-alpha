"""PLAN_Y2: sealed, offline comparison of saved accounts, without strategy reruns."""
from __future__ import annotations

import argparse
from collections import defaultdict
from functools import lru_cache
import json
import math
import os
from pathlib import Path
import resource
import sys
from types import SimpleNamespace

import numpy as np

from . import y1_research as Y1
from studies.trader_replication import mainleg as M

ROOT, HOME = Y1.ROOT, Y1.STUDY
WORK = HOME/'reports/y2_work'
REPORT = HOME/'reports/Y2_CN.md'
read, sha = Y1.read, Y1.sha
YEARS = ('2024', '2025', '2026')
NAMES = ('IE47_C062', 'master_C062', 'registered_master', 'M1B', 'M2A', 'M3B')


def write(name, value):
    Y1.write(WORK/name, value)


def offline():
    def audit(event, args):
        if event in ('socket.connect', 'socket.bind', 'socket.getaddrinfo', 'subprocess.Popen', 'os.system'):
            raise PermissionError('Y2 is offline and single-process')
        if event == 'open' and not isinstance(args[0], int):
            if args[2] & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND):
                path = Path(os.fsdecode(args[0])).resolve()
                if not path.is_relative_to(WORK.resolve()) and path != REPORT.resolve():
                    raise PermissionError('Y2 writes only its own artifacts and report')
    sys.addaudithook(audit)


def resources():
    group = next(s.split(':', 2)[2] for s in Path('/proc/self/cgroup').read_text().splitlines() if s.startswith('0::'))
    base = Path('/sys/fs/cgroup')/group.lstrip('/')
    cpu, memory = (base/'cpu.max').read_text().strip(), int((base/'memory.max').read_text())
    threads = int(next(s.split()[1] for s in Path('/proc/self/status').read_text().splitlines() if s.startswith('Threads:')))
    quota, period = map(int, cpu.split())
    assert quota/period <= .6 and memory <= 900*1024*1024 and threads == 1
    return dict(cpu_max=cpu, memory_max=memory, threads=threads, cgroup=group,
                peak_rss_mib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024,
                memory=Path('/proc/meminfo').read_text())


class Prices:
    """Cached stock files, with read-only U1 mmap fallback for native master names."""
    def __init__(self):
        self.panel = {}
        self.sources = set()

    @lru_cache(maxsize=16)
    def __getitem__(self, code):
        code = code.removeprefix('SHORT:')
        path = Y1.DATA/'stocks'/f'{code}.npz'
        if path.exists():
            self.sources.add(path)
            with np.load(path) as z:
                return {k: z[k].astype(float) for k in ('o', 'h', 'l', 'c')}
        directory = HOME/'reports/u1_work/panel'
        if not self.panel:
            self.panel = {k: np.load(directory/(v+'.npy'), mmap_mode='r')
                          for k, v in dict(o='open', h='high', l='low', c='close', codes='codes', days='days').items()}
            self.ci = {str(c): i for i, c in enumerate(self.panel['codes'])}
            assert list(map(str, self.panel['days'])) == read(Y1.FROZEN)['calendar']
            self.sources.update(directory/(v+'.npy') for v in ('open', 'high', 'low', 'close', 'codes', 'days', 'digest'))
        return {k: np.asarray(self.panel[k][:, self.ci[code]], float) for k in ('o', 'h', 'l', 'c')}


def accounts():
    out = {}
    for name in NAMES:
        if name in Y1.ACCOUNTS:
            directory, prefix = Y1.ACCOUNTS[name]
            for vintage, directory, prefix in (
                ('continuous', directory, prefix),
                ('standalone', 'e21_work/BASE_2026' if name == 'IE47_C062' else 'e15_work/master_swap/2026', 'C062_2026')):
                paths = Y1.account_paths(directory, prefix)
                out[name+'__'+vintage] = dict(name=name, vintage=vintage, schema='Y1',
                    trades=paths[0], curve=paths[1], stats=paths[2],
                    saved=HOME/'reports/y1_work'/f'{name}.json' if vintage == 'continuous' else None)
        elif name == 'registered_master':
            d = HOME/'reports/d1_work'
            out[name+'__continuous'] = dict(name=name, vintage='continuous', schema='native',
                trades=d/'master_trades.json', curve=d/'master_curve.json', metadata=d/'master_metadata.json', saved=None)
        else:
            work = 'm1_work' if name == 'M1B' else ('m2_work' if name == 'M2A' else 'm3_work')
            for vintage in ('continuous', 'standalone'):
                d = HOME/'reports'/work/'validation'/vintage
                out[name+'__'+vintage] = dict(name=name, vintage=vintage, schema='M',
                    trades=d/'trades.json', curve=d/'curve.json', rules=d/'rules.json',
                    reconciliation=d/'reconciliation.json', saved=d/'metrics.json')
    return out


def load_account(spec, calendar, prices):
    raw, curve = read(spec['trades']), read(spec['curve'])
    if spec['schema'] == 'Y1':
        trades, adapter = Y1.adapt(spec['trades'], calendar)
        stats = read(spec['stats'])
        financing = stats['margin']
        if isinstance(financing, dict):
            financing = financing.get('interest', financing.get('cost'))
    else:
        from .m1_research import adapt
        metadata = read(spec['metadata']) if spec['schema'] == 'native' else None
        rules = SimpleNamespace(**(metadata['rules'] if metadata else read(spec['rules'])))
        trades, residual = adapt(raw, calendar, rules, prices)
        adapter = dict(max_residual=residual, borrow_fee=sum(r.get('borrow_fee', 0.) for t in trades for r in t['lots']))
        stats = metadata['stats'] if metadata else read(spec['saved'])['stats']
        financing = None if metadata else read(spec['reconciliation'])['financing']
    days, values = curve['days'], curve['equity']
    assert days == [d for d in calendar if days[0] <= d <= days[-1]]
    equity = np.ones(len(calendar))
    di = {d: i for i, d in enumerate(calendar)}
    for d, value in zip(days, values):
        equity[di[d]] = value
    terminal = sum(r['sell_fee'] for t in trades for r in t['lots'] if r['open'])
    implied = sum(t['pnl'] for t in trades)+terminal-(values[-1]-1)
    if financing is not None:
        assert abs(implied-financing) < 1e-9, (spec['name'], implied, financing)
    reconciliation = dict(trade_pnl=sum(t['pnl'] for t in trades), account_pnl=values[-1]-1,
        terminal_fee=terminal, financing_implied=implied, financing_stored=financing,
        financing_independently_stored=financing is not None,
        error=implied-financing if financing is not None else None,
        shorts=sum(t['side'] < 0 for t in raw), adapter=adapter)
    return trades, equity, stats, reconciliation


def freeze():
    assert not (WORK/'protocol.json').exists()
    resources()
    specs = accounts()
    paths = {Y1.FROZEN, Path(__file__), Path(M.__file__), Path(Y1.__file__),
             HOME/'m1_research.py', HOME/'notes/PLAN_Y2_CN.md',
             ROOT/'studies/trader_replication/tests/test_mainleg_lifecycle.py'}
    for spec in specs.values():
        paths.update(v for v in spec.values() if isinstance(v, Path))
    protocol = dict(task='PLAN_Y2_CN', no_fitting=True, no_strategy_rerun=True,
        formulas=dict(window='s=first argmin(low[max(0,peak-60):peak+1]); inclusive [s,peak]',
            labels='same frozen 48 T1 legs, original anchor gain and year; no redefinition of winners',
            time_slice='boundary before b uses close[b-1]; actual fill on actual entry/exit; sale day zero EOD inventory',
            fees='buy fee only on first slice; sell fee and disclosed residual only on final slice',
            early='first assigned holding day h=max(actual lot entry,s); FIFO oldest actual entry breaks ties; top/actual_cost-1 >= 0.5*original_anchor_gain',
            potential='original shares*actual_cost*original_anchor_gain, each matched piece once per leg',
            overlap='at each holding interval: maximum top/actual_cost-1, earliest anchor then key; one owner',
            O='all outside H, including short trades; lifecycle does not reclassify O into T2',
            capital='same EOD close marked shares; mean(H/equity) includes every cash session',
            gross='positive parts of same FIFO/time slices in both numerator and denominator; not daily positive clipping',
            audit='H slice whose actual lot buy precedes s by >20 sessions; net/H and gross/GP_H; separately trade first buy >20',
            years='pnl by original trade entry year, capital by calendar year, coverage/capture by frozen anchor year'),
        targets=dict(cap_equity=.5, purity_gross=.6, early_fraction=.5, capture_total=.5, top10=5,
                     trades=52, win_max=.35),
        years=YEARS, cohorts={k:{a:str(v.relative_to(ROOT)) if isinstance(v, Path) else v for a,v in s.items()} for k,s in specs.items()},
        standalone_missing=dict(registered_master='No separately opened 2026 ledger/curve found in the registered saved account'),
        input_sha256={str(p.relative_to(ROOT)):sha(p) for p in sorted(paths)}, resources=resources(),
        data_reused=True, independent_out_of_sample=False)
    write('protocol.json', protocol)
    print('Y2 formulas and eleven saved account cohorts sealed', flush=True)


def check_inputs(protocol):
    assert all(sha(ROOT/p) == digest for p, digest in protocol['input_sha256'].items()), 'Y2 sealed source changed'


def preflight():
    protocol = read(WORK/'protocol.json')
    check_inputs(protocol)
    assert not (WORK/'preflight.json').exists()
    frozen, prices = read(Y1.FROZEN), Prices()
    calendar, checks = frozen['calendar'], {}
    windows = M.lifecycle_windows(frozen['legs'], prices)
    for key, spec in accounts().items():
        trades, equity, stats, reconcile = load_account(spec, calendar, prices)
        for t in trades:
            p = prices[t['code']]
            for row in t['lots']:
                assert np.isfinite(p['c'][row['entry']:row['exit']+int(row['open'])]).all()
                for g in windows:
                    if g['code'] == t['code']:
                        for boundary in (g['window_start'], g['peak']+1):
                            if row['entry'] < boundary <= row['exit']:
                                assert np.isfinite(p['c'][boundary-1])
            assert math.isclose(sum(r['pnl'] for r in t['lots']), t['pnl'], abs_tol=1e-9)
        checks[key] = dict(trades=len(trades), reconciliation=reconcile, years=list(stats['by_year']))
    for g in windows:
        assert g['window_start'] <= g['peak'] and g['peak']-g['window_start'] <= 60
    write('windows.json', [dict(g, start_date=calendar[g['window_start']],
        y1_start_date=calendar[max(0, g['first']-3)], start_minus_y1=g['window_start']-(g['first']-3)) for g in windows])
    write('preflight.json', dict(accounts=checks, frozen_sha256=sha(Y1.FROZEN),
        price_sha256={str(p.relative_to(ROOT)):sha(p) for p in sorted(prices.sources)}, resources=resources()))
    print('Y2 preflight passed: FIFO, held closes, curves and lifecycle boundaries', flush=True)


def close_enough(a, b):
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(close_enough(a[k], b[k]) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(close_enough(x, y) for x, y in zip(a, b))
    if isinstance(a, (float, int)) and isinstance(b, (float, int)):
        return math.isclose(a, b, rel_tol=1e-10, abs_tol=1e-10)
    return a == b


def stale_audit(rows, years):
    out = {}
    for year in years:
        part = [r for r in rows if r['bucket'] == 'T1' and r['year'] == year]
        h, gross = sum(r['h_pnl'] for r in part), sum(max(r['h_pnl'], 0.) for r in part)
        out[year] = dict(H=h, gross_H=gross)
        for name, entry in (('lot', 'original_entry'), ('trade', 'trade_entry')):
            old = [r for r in part if r['window_start']-r[entry] > 20]
            pnl = sum(r['h_pnl'] for r in old)
            gp = sum(max(r['h_pnl'], 0.) for r in old)
            out[year][name] = dict(pnl=pnl, net_share=pnl/h if h > 0 else None,
                gross=gp, gross_share=gp/gross if gross > 0 else None,
                matched_pieces=len({(r['trade'],r['lot_piece']) for r in old}),
                trades=len({r['trade'] for r in old}), legs=sorted({r['leg'] for r in old}))
    return out


def differences(old, new, trades, calendar):
    oldlegs = {g['key']:g for g in old['legs']}
    rows, pieces = [], defaultdict(list)
    for row in new['lots']:
        pieces[(row['trade'],row['lot_piece'])].append(row)
    oldrows = iter(old['lots'])
    piece_differences = []
    for t in trades:
        for number, piece in enumerate(t['lots']):
            before = next(oldrows)
            after = pieces[(t['id'],number)]
            assert math.isclose(piece['pnl'], sum(r['pnl'] for r in after), abs_tol=1e-9)
            h0 = before['h_pnl'] if before['bucket'] == 'T1' else 0.
            h1 = sum(r['h_pnl'] for r in after if r['bucket'] == 'T1')
            if abs(h1-h0) > 1e-12 or {r['leg'] for r in after if r['leg']} != ({before['leg']} if before['bucket']=='T1' else set()):
                piece_differences.append(dict(trade=t['id'], piece=number, code=t['code'], source=piece['source'],
                    entry=calendar[piece['entry']], exit=calendar[piece['exit']], cost=piece['price'], shares=piece['shares'],
                    y1_leg=before['leg'], y1_bucket=before['bucket'], y1_H=h0, lifecycle_H=h1, delta=h1-h0,
                    lifecycle_slices=[dict(leg=r['leg'], start=calendar[r['entry']],
                        end=calendar[r['h_end']] if r['h_end'] is not None else None,
                        pnl=r['pnl'], bucket=r['bucket'], basis=r['basis_price']) for r in after]))
    for g in new['legs']:
        before = oldlegs[g['key']]
        rows.append(dict(key=g['key'], code=g['code'], year=g['year'], anchor=calendar[g['first']],
            peak=calendar[g['peak']], start=calendar[g['window_start']], y1_H=before['pnl'],
            lifecycle_H=g['pnl'], delta=g['pnl']-before['pnl'], y1_early=before['covered'],
            lifecycle_early=g['covered'], lots_y1=before['lots'], lots_lifecycle=g['lots']))
    return rows, sorted(piece_differences, key=lambda r: -abs(r['delta']))


def evaluate():
    protocol, pre = read(WORK/'protocol.json'), read(WORK/'preflight.json')
    check_inputs(protocol)
    assert all(sha(ROOT/p) == v for p,v in pre['price_sha256'].items())
    assert not (WORK/'evaluation_started.json').exists(), 'Y2 already evaluated; render saved results instead'
    write('evaluation_started.json', dict(protocol_sha256=sha(WORK/'protocol.json'), resources=resources()))
    frozen, prices = read(Y1.FROZEN), Prices()
    calendar = frozen['calendar']
    ticker_years = {(r['code'],r['anchor'][:4]) for r in frozen['audit'] if r['anchor']}
    summaries, all_legs = {}, []
    for key, spec in accounts().items():
        trades, equity, stats, reconcile = load_account(spec, calendar, prices)
        runs = {}
        for label, lifecycle in (('Y1', False), ('lifecycle', True)):
            run = M.summary_account(trades, frozen['legs'], prices, calendar, equity,
                                    frozen['other_legs'], ticker_years, lifecycle=lifecycle)
            run['years'] = {y:r for y,r in run['years'].items() if y in stats['by_year']}
            run['legs'] = [g for g in run['legs'] if g['year'] in stats['by_year']]
            for year, row in run['years'].items():
                row['account_return'] = stats['by_year'][year]
                row['targets'] = Y1.targets(row, row['coverage']['including_censored'])
                row['excluding_censored']['targets'] = Y1.targets(row['excluding_censored'], row['excluding_censored']['coverage'])
            write(key+'__'+label+'.json', run)
            runs[label] = run
        if spec['saved']:
            saved = read(spec['saved'])
            for year, row in runs['Y1']['years'].items():
                assert all(close_enough(value, saved['years'][year][k]) for k,value in row.items()
                           if k not in ('excluding_censored',)), (key, year, 'default Y1 differs')
            assert close_enough(runs['Y1']['legs'], saved['legs']), (key, 'default leg results differ')
        np.testing.assert_allclose(runs['Y1']['daily']['gross'], runs['lifecycle']['daily']['gross'], rtol=1e-12, atol=1e-12)
        np.testing.assert_allclose(runs['Y1']['daily']['confirmed'], runs['lifecycle']['daily']['confirmed'], rtol=1e-12, atol=1e-12)
        assert np.all(runs['lifecycle']['daily']['his'] <= runs['lifecycle']['daily']['gross']+1e-12)
        legdiff, lotdiff = differences(runs['Y1'], runs['lifecycle'], trades, calendar)
        audit = stale_audit(runs['lifecycle']['lots'], runs['lifecycle']['years'])
        write(key+'__differences.json', dict(legs=legdiff, lots=lotdiff, old_position_audit=audit))
        summaries[key] = dict(name=spec['name'], vintage=spec['vintage'], reconciliation=reconcile,
            default_matches_saved=True if spec['saved'] else None,
            years={label:run['years'] for label,run in runs.items()}, old_position_audit=audit)
        if spec['vintage'] == 'continuous':
            all_legs.extend(dict(r, account=spec['name']) for r in legdiff)
        write('accounts.json', summaries)
        print('Evaluated '+key, flush=True)
    # Rank unique legs by total absolute reclassification across the six continuous books.
    grouped = defaultdict(list)
    for r in all_legs:
        grouped[r['key']].append(r)
    biggest = sorted(grouped, key=lambda k: -sum(abs(r['delta']) for r in grouped[k]))[:10]
    write('top10_leg_differences.json', [dict(key=k, absolute_delta=sum(abs(r['delta']) for r in grouped[k]),
        signed_delta=sum(r['delta'] for r in grouped[k]), accounts=grouped[k]) for k in biggest])
    write('evaluation_complete.json', dict(accounts=len(summaries),
        evaluations={k:dict(Y1=1,lifecycle=1) for k in summaries}, resources=resources(),
        price_sha256={str(p.relative_to(ROOT)):sha(p) for p in sorted(prices.sources)}))


def verify():
    from . import y2_report
    protocol = read(WORK/'protocol.json')
    check_inputs(protocol)
    before = read(WORK/'before.json')['protected_sha256']
    protected = {p:sha(ROOT/p)==s for p,s in before.items() if '/f3_work/' not in p and '/f3_' not in p}
    assert all(protected.values()), 'Y1/frozen reports changed'
    tests = y2_report.tests()
    assert len(tests) == 3 and all(t['ok'] for t in tests.values()), tests
    evaluation = read(WORK/'evaluation_complete.json')
    assert all(sha(ROOT/p)==s for p,s in evaluation['price_sha256'].items())
    files = sorted(p for p in WORK.rglob('*') if p.is_file() and p.name != 'completion.json')
    write('completion.json', dict(complete=True, task='PLAN_Y2_CN', report=str(REPORT.relative_to(ROOT)),
        report_sha256=sha(REPORT), tests=tests, evaluations=evaluation, protected_unchanged=protected,
        source_sha256={str(p.relative_to(ROOT)):sha(p) for p in (Path(__file__), Path(y2_report.__file__),Path(M.__file__))},
        artifacts={str(p.relative_to(WORK)):sha(p) for p in files}, resources=resources(),
        no_network=True, no_new_data=True, no_strategy_rerun=True, no_git_commit=True,
        F3_files_written=False, independent_out_of_sample=False))
    print('Y2 complete: two definitions, eleven accounts, three passing test groups; Y1 unchanged')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('stage', choices=('freeze','preflight','evaluate','verify'))
    args = parser.parse_args()
    offline()
    globals()[args.stage]()
