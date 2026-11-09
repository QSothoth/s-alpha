"""Offline P1 compatibility replay; one registered system / market per process.

Run under the scope specified in PLAN_P1_CN.md. No fitting or candidate search.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import resource
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent/'reports/p1_work'


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1 << 20), b''):
            h.update(block)
    return h.hexdigest()


def digest(value):
    def default(x):
        return x.tolist() if isinstance(x, np.ndarray) else x.item()
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=default,
                                     ensure_ascii=False).encode()).hexdigest()


def array_sha(value):
    h = hashlib.sha256(str((value.shape, value.dtype.str)).encode())
    for row in value:
        h.update(np.ascontiguousarray(row).tobytes())
    return h.hexdigest()


def write(name, value):
    path = OUT/name
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x' if name.startswith('before/') else 'w', encoding='utf-8') as stream:
        stream.write(json.dumps(value, ensure_ascii=False, indent=2)+'\n')


def resources():
    cg = next(x.split(':', 2)[2] for x in Path('/proc/self/cgroup').read_text().splitlines()
              if x.startswith('0:'))
    folder = Path('/sys/fs/cgroup')/cg.lstrip('/')
    return dict(python=sys.executable, cpu_max=(folder/'cpu.max').read_text().strip(),
                memory_max=(folder/'memory.max').read_text().strip(),
                threads=next(x for x in Path('/proc/self/status').read_text().splitlines()
                             if x.startswith('Threads:')), peak_rss_mib=resource.getrusage(0).ru_maxrss/1024)


def freeze():
    if (OUT/'protocol.json').exists():
        raise FileExistsError('P1 protocol already frozen')
    paths = [p for p in (ROOT/'studies').rglob('*') if p.is_file() and 'reports' in p.parts
             and not p.is_relative_to(OUT) and '__pycache__' not in p.parts]
    paths += list((ROOT/'studies/trader_screens').glob('*.py'))
    paths += [ROOT/'studies/trader_replication'/p for p in ('systems.py', 'DATA_PIN.json', 'mainleg.py')]
    paths += [ROOT/'studies/martin_luk/notes'/p for p in ('trades.csv', 'legs_frozen.json')]
    protected = {str(p.relative_to(ROOT)): sha(p) for p in paths}
    write('protocol.json', dict(task='PLAN_P1_CN', protected=protected,
        resources=resources(), memory_before=Path('/proc/meminfo').read_text(),
        policy='offline, no fitting, no new candidates, no git commits; exact before/after replay'))


def registered(phase, name, market):
    from studies.trader_replication import systems, runner, system as Y
    s = systems.get(name)
    st, cfg = s.load()
    A = st.arrays(market, mode='frozen') if not s.board_run else None
    result = {}
    if not s.board_run:
        trace = {}
        entries, rules, mask, pool = st.build(A, cfg, trace)
        curve, days, trades = Y.simulate(st.px(A), st.ema_inputs(A, pool, rules), rules, entries,
                                         systems.START, str(A['days'][-1]), audit=True)
        result.update(entries=digest(entries), rules=digest(asdict(rules)), mask=array_sha(mask),
                      pool=array_sha(pool), ledger=digest(trades), curve=array_sha(curve),
                      trades=len(trades), days=len(days))
        del entries, mask, pool, trace, curve, trades
    board = runner.run(s, market, mode='frozen', days=5, A=A)
    if s.board_run:
        curve, days, trades = st.simulate(cfg, systems.START, board['last_day'])
        result.update(ledger=digest(trades), curve=array_sha(np.asarray(curve)), trades=len(trades), days=len(days))
    result.update(board=digest(board), runner_check=board.get('check'), resources=resources())
    write(f'{phase}/{name}_{market}.json', result)
    if phase == 'after':
        before = json.loads((OUT/f'before/{name}_{market}.json').read_text())
        checks = {k: result[k] == v for k, v in before.items() if k != 'resources'}
        write(f'checks/{name}_{market}.json', dict(ok=all(checks.values()), checks=checks))
        assert all(checks.values()), checks
    print(phase, name, market, result.get('trades'), 'ok', flush=True)


def history(phase, name, horizon):
    from studies.martin_luk import m1_research as M1, m2_research as M2, m3_research as M3
    from studies.trader_replication import system as Y
    directory = M2.PREP if horizon == 'train' else M1.OUT/'validation_prepared'
    span = M1.TRAIN if horizon == 'train' else ('2024-01-02', '2026-10-16')
    A = M2.arrays(directory)
    if name == 'M1B':
        book, rules, ema = M1.build(A, directory, M2.BASE)
        reference = M1.OUT/('candidates/M1B' if horizon == 'train' else 'validation/continuous')
    elif name == 'M2A':
        book, rules, ema = M2.build(A, directory, M2.CANDIDATES[name])
        reference = M2.OUT/('candidates/M2A' if horizon == 'train' else 'validation/continuous')
    else:
        book, rules, ema = M3.build(A, directory, M3.candidate_specs()[name])
        reference = M3.OUT/('candidates/'+name if horizon == 'train' else 'validation/continuous')
    px = dict(dates=A['days'], **{k: A[k].astype(float) if k != 'codes' else A[k]
              for k in ('open', 'high', 'low', 'close', 'codes')})
    curve, dates, trades = Y.simulate(px, ema, rules, book, *span, audit=True)
    old_trades, old_curve = M1.read(reference/'trades.json'), M1.read(reference/'curve.json')
    result = dict(entries=digest(book), rules=digest(asdict(rules)), ledger=digest(trades), curve=array_sha(curve),
        original_ledger=M1.clean(trades) == old_trades,
        original_curve=M1.clean(dict(days=dates, equity=curve)) == old_curve, resources=resources())
    write(f'{phase}/{name}_{horizon}.json', result)
    assert result['original_ledger'] and result['original_curve'], result
    if phase == 'after':
        path = OUT/f'before/{name}_{horizon}.json'
        before = json.loads(path.read_text()) if path.exists() else {}
        checks = {k: result[k] == v for k, v in before.items() if k != 'resources'}
        checks.update(original_ledger=result['original_ledger'], original_curve=result['original_curve'])
        write(f'checks/{name}_{horizon}.json', dict(ok=all(checks.values()), checks=checks))
        assert all(checks.values()), checks
    print(phase, name, horizon, 'original ledger / curve identical', flush=True)


def describe_regimes():
    from studies.trader_replication import panels, regime, pipeline
    from studies.trader_replication import mainleg
    specs = {name: regime.spec(dict(producer=name)) for name in ('idx_ema', 'breadth', 'smc')}
    write('regime_specs.json', {name: dict(spec=value, sha256=regime.spec_sha(value))
                              for name, value in specs.items()})
    source = panels.arrays('us', mode='frozen')
    A = {k: source[k] for k in ('days', 'codes', 'open', 'high', 'low', 'close', 'raw', 'to20')}
    data_sha = source['digest']
    del source
    window = ('2024-01-02', '2026-10-16')
    mask = (A['days'] >= window[0]) & (A['days'] <= window[1])
    for name, spec in specs.items():
        out = regime.states(A, spec)
        clipped = regime.episodes(out['label'][mask], A['days'][mask])
        counts = {state: dict(days=int(np.sum(out['label'][mask] == k)),
            episodes=sum(e['state'] == state for e in clipped)) for k, state in enumerate(regime.NAMES)}
        by_year = {}
        for year in ('2024', '2025', '2026'):
            sub = mask & np.array([str(d).startswith(year) for d in A['days']])
            episodes = regime.episodes(out['label'][sub], A['days'][sub])
            by_year[year] = {state: dict(days=int(np.sum(out['label'][sub] == k)),
                episodes=sum(e['state'] == state for e in episodes)) for k, state in enumerate(regime.NAMES)}
        cuts = []
        for cut in ('2024-09-30', '2025-09-30'):
            n = int(np.searchsorted(A['days'], cut, side='right'))
            cut_A = {k: v[:n] if k != 'codes' else v for k, v in A.items()}
            short = regime.states(cut_A, spec)
            cuts.append(dict(cut=cut, ok=bool(np.array_equal(out['label'][:n], short['label']))))
        stable = regime.stability(A, spec, window)
        write(f'regimes/{name}.json', dict(spec=spec, spec_sha=out['spec_sha'], data_sha=data_sha,
            window=window, counts=counts, total_episodes=len(clipped), episodes=clipped, annual=by_year,
            calendar=list(map(str, A['days'][mask])), label=out['label'][mask].tolist(),
            lookahead=cuts, stability=stable, resources=resources()))
        print(name, counts, flush=True)
    # Re-evaluate an EXISTING signal artifact only, never train missing year folds.
    home = Path(__file__).resolve().parent
    frozen = json.loads((home/'notes/legs_frozen.json').read_text())
    path = home/'reports/s0_work/picks/IE9.json'
    saved = json.loads(path.read_text())
    calendar = frozen['calendar']
    assert list(map(str, A['days'])) == calendar
    picks = {t: saved.get(day, []) for t, day in enumerate(calendar[:-1]) if day >= '2023-12-29'}
    panel = home/'reports/u1_work/panel'
    codes = np.load(panel/'codes.npy', mmap_mode='r')
    opening = np.load(panel/'open.npy', mmap_mode='r')
    ci = {str(code): j for j, code in enumerate(codes)}
    opens = {g['code']: opening[:, ci[g['code']]] for g in frozen['legs'] if g['code'] in ci}
    stats = mainleg.signal_coverage_budget(picks, None, frozen['legs'], calendar, opens, 3)
    expected = json.loads((home/'reports/s0_work/systems/IE9.json').read_text())['results']['3']
    assert {y: stats['annual'][y] for y in ('2024', '2025', '2026')} == expected['annual'], 'S0 IE9 annual cells changed'
    assert stats['per_leg'] == expected['per_leg'], 'S0 IE9 leg records changed'
    card = pipeline.g3({'2026': dict(picks=picks, trained_years=['2024', '2025'], model_sha=sha(path),
        sample='历史留出*；2026已被反复查看')}, frozen['legs'], calendar, opens, upper_bound=1.)
    write('g3_ie9_existing.json', dict(gate=card, exact_s0=True, original_picks_sha=sha(path),
        upper_bound_note='1 is a conservative ceiling, not a newly estimated pool upper bound',
        fitted_models_added=0, candidates_run=0))


def offline():
    sys.dont_write_bytecode = True
    def guard(event, args):
        if event in ('socket.connect', 'socket.bind', 'socket.getaddrinfo', 'subprocess.Popen', 'os.system'):
            raise PermissionError('P1 replay is offline and single-process')
        if event == 'open' and not isinstance(args[0], int) and args[2] & (
                os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND):
            path = Path(os.fsdecode(args[0])).resolve()
            if not path.is_relative_to(OUT.resolve()):
                raise PermissionError('P1 replay writes only p1_work: '+str(path))
    sys.addaudithook(guard)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=('freeze', 'before', 'after', 'regimes'))
    parser.add_argument('name', nargs='?')
    parser.add_argument('market', nargs='?', default='us')
    args = parser.parse_args()
    offline()
    if args.phase == 'freeze':
        freeze()
    elif args.phase == 'regimes':
        describe_regimes()
    elif args.name in ('M1B', 'M2A', 'M3B'):
        history(args.phase, args.name, args.market)
    else:
        registered(args.phase, args.name, args.market)


if __name__ == '__main__':
    main()
