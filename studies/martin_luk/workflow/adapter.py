"""Martin's frozen WF00 inputs; shared metrics live in trader_replication.funnel."""
from __future__ import annotations

from dataclasses import fields, replace
import gzip
import json
from pathlib import Path

import numpy as np

from studies.trader_replication import allocation, funnel, mainleg, regime, system
from studies.trader_replication.datasets import sha

ROOT = Path(__file__).resolve().parents[3]
HOME = ROOT/'studies/martin_luk'
FLOW = HOME/'workflow'
OUT = FLOW/'rounds/WF00'
REPORTS = HOME/'reports'


def read(path):
    path = Path(path)
    if not path.exists() and Path(str(path)+'.gz').exists():
        path = Path(str(path)+'.gz')
    with gzip.open(path, 'rt') if path.suffix == '.gz' else path.open() as stream:
        return json.load(stream)


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(clean(value), ensure_ascii=False, indent=1, allow_nan=False)+'\n')


def clean(value):
    if isinstance(value, dict):
        return {str(k): clean(v) for k, v in value.items()}
    if isinstance(value, (tuple, list, np.ndarray)):
        return [clean(v) for v in value]
    if isinstance(value, np.generic):
        return clean(value.item())
    return None if isinstance(value, float) and not np.isfinite(value) else value


def market():
    from .. import p3_research as P3
    return P3.market()


def indexed(A, path):
    picks = read(path)
    return {t: picks.get(str(d), []) for t, d in enumerate(A['days'][:-1])}


class CandidatePool:
    """Trade-day lookup of the preceding night's frozen eligible candidates."""
    def __init__(self, codes, by_night):
        self.codes = codes
        self.nights = {int(t): set(names) for t, names in by_night.items()}

    def __getitem__(self, key):
        day, column = key
        return str(self.codes[column]) in self.nights.get(day-1, ())


def labels():
    cfg = read(FLOW/'config.json')
    path = ROOT/cfg['legs']['path']
    if sha(path) != cfg['legs']['sha256']:
        raise ValueError('frozen leg SHA mismatch')
    return read(path)['legs']


def load_rules(value):
    known = {f.name for f in fields(system.Rules)}
    return system.Rules(**{k: v for k, v in value.items() if k in known})


def rules_for(name):
    if name == 'M3B':
        return load_rules(read(REPORTS/'m3_work/validation/continuous/rules.json'))
    if name == 'C062':
        return load_rules(read(REPORTS/'m3_work/compatibility/C062/rules.json'))
    if name == 'K2':
        from .. import ie47_e1 as M, e10_research as E10
        return E10.rule_layers(M.e8_rules('E8c'), ('AS', 'X1'))
    value = read(REPORTS/'d1_work/master_metadata.json')['rules']
    rules = load_rules(value)
    if name in ('X1_OPEN', 'S1_NOBLOCK', 'S2_CLOSESTOP', 'S3_BOTH'):
        from ..p4_policy import KINDS
        rules = replace(rules, intraday_kinds=tuple(rules.intraday_kinds)+KINDS,
            close_stop_days=5 if name in ('S2_CLOSESTOP', 'S3_BOTH') else 0,
            hard_stop_mult=2., no_rebuy_day=name in ('S1_NOBLOCK', 'S3_BOTH'))
    return rules


def load_account(name):
    cfg = read(FLOW/'config.json')['systems'][name]
    path = ROOT/cfg['account']
    if cfg.get('prefix'):
        return dict(curve=read(Path(str(path)+'_curve.json')), trades=read(Path(str(path)+'_trades.json')))
    result = {k: read(path/(k+'.json')) for k in ('curve', 'trades')}
    for key in ('attempts',):
        p = path/(key+'.json')
        if p.exists() or Path(str(p)+'.gz').exists():
            result[key] = read(p)
        elif (path/(key+'.jsonl')).exists():
            with (path/(key+'.jsonl')).open() as stream:
                result[key] = [json.loads(s) for s in stream]
    return result


def master_books(A):
    from .. import p3_research as P3
    return {k: P3.decode_book(read(REPORTS/f'd1_work/master_{k}.json'), A)
            for k in ('raw', 'filtered', 'book', 'short_entries')}


def execution_inputs(A):
    """Causal market inputs of the existing executions, no evaluation tables."""
    from .. import replicate as MR, ie47_e1 as M
    from studies.trader_data import supplemental
    liquidity = np.load(REPORTS/'d1_work/master_liquidity.npy', mmap_mode='r')
    short_pool = MR.pool_for(A, 'U7')
    A['idx_pb16'] = MR.index_risk_scale(A, liquidity | short_pool)
    A['index_ok'] = MR.ew_index_up(A, liquidity, 50)
    qqq, sources = supplemental.benchmark('US.QQQ', A['days'], 'frozen')
    with np.load(REPORTS/'e1_work/selection.npz') as z:
        counts = np.bincount(z['row_t'], minlength=len(A['days']))
    A['e8_scale'] = M.regime_scale(qqq, counts, M.E8['E8c'])
    return sources


def execution(A, picks, name, *, profile, end='2026-10-16', rules=None):
    """Only bars, rules and ordered picks; evaluation tables are inaccessible."""
    from .. import p3_research as P3, p4_policy as P4, p5_policy as P5, ie47_e1 as M
    from .. import e15_research as E15
    from .capital import candidate_rules, check_rules
    capital = read(FLOW/'config.json')['capital']
    rules = candidate_rules(rules_for(name), capital, profile) if rules is None else check_rules(rules, capital, profile)
    if name in ('X1_OPEN', 'S3_BOTH'):
        parts = P5.entries(A, picks, A['index_ok'], soft=name == 'S3_BOTH')
        book = parts['offered']
    elif name in ('C062', 'K2'):
        dated = {str(A['days'][t]): cs for t, cs in picks.items()}
        book = M.entry_book(A, dated, **M.E6['E6c'])[0]
        if name == 'C062':
            spec = E15.SPECS['C062']
            book = E15.P.retry_book(A, book, {}, spec)[0]  # T0: no retries or extra signal arrays
            book = [[tuple(e[:7])+(None, .30)+tuple(e[9:]) for e in row] for row in book]
    else:
        # Native master triggers gated by this test's nominations, retaining the original order.
        book = P3.candidate_book(A, {str(A['days'][t]): cs for t, cs in picks.items()},
                                A['master_filtered'], [[] for _ in A['days']], None, False)
    ema = {k: A[k] for k in ('e9', 'e21', 'idx_pb16', 'e8_scale') if k in A}
    if name in ('C062', 'K2'):
        ema['always'] = np.broadcast_to(True, A['close'].shape)
    track = dict(entry_attempts=[])
    curve, dates, trades = system.simulate(P3.px(A), ema, rules, book, '2024-01-02', end,
        audit=True, track=track, entry_close_stops=name == 'S3_BOTH')
    return dict(curve=dict(days=list(dates), equity=list(curve)), trades=trades,
                attempts=track['entry_attempts']), rules


def state_labels(A):
    """Use the full saved B4 definition; bootstrap separately replays it exactly."""
    saved = read(REPORTS/'p5_work/regimes/B4_PCT2.json')
    if len(saved['full_label']) != len(A['days']):
        raise ValueError('state calendar differs from market panel')
    return np.array([regime.NAMES[s] for s in saved['full_label']])


def run(name, A=None):
    cfg = read(FLOW/'config.json')
    if name not in cfg['systems']:
        raise ValueError('unregistered WF00 system: '+str(name))
    A = market() if A is None else A
    legs, record, rules = labels(), load_account(name), rules_for(name)
    B = master_books(A)
    picks = indexed(A, ROOT/cfg['systems'][name]['picks'])
    raw, filtered, offered = B['raw'], B['filtered'], B['book']
    if name in ('X1_OPEN', 'S1_NOBLOCK', 'S2_CLOSESTOP', 'S3_BOTH'):
        from .. import p4_policy as P4, p5_policy as P5, replicate as MR
        liquid = np.load(REPORTS/'d1_work/master_liquidity.npy', mmap_mode='r')
        ok = MR.ew_index_up(A, liquid, 50)
        if name != 'X1_OPEN':
            picks = P5.nominations(A, name)
        parts = P5.entries(A, picks, ok, soft=name in ('S2_CLOSESTOP', 'S3_BOTH'))
        raw, filtered, offered = (parts[k] for k in ('raw', 'filtered', 'offered'))
    elif name == 'IE9_master':
        from .. import p3_research as P3
        offered = P3.candidate_book(A, {str(A['days'][t]): cs for t, cs in picks.items()},
                                  B['filtered'], B['short_entries'], None, False)
    elif name in ('C062', 'K2'):
        from .. import ie47_e1 as M
        raw = M.entry_book(A, {str(A['days'][t]): cs for t, cs in picks.items()}, **M.E6['E6c'])[0]
        filtered = offered = raw
    if name in ('master', 'M3B'):
        pool = np.load(REPORTS/'d1_work/master_liquidity.npy', mmap_mode='r')
    elif name in ('C062', 'K2'):
        possible = {}
        with np.load(REPORTS/'e1_work/selection.npz') as z:
            for t, j in zip(z['row_t'], z['row_j']):
                possible.setdefault(int(t), []).append(str(A['codes'][j]))
        pool = CandidatePool(A['codes'], possible)
    else:
        pool = CandidatePool(A['codes'], {t: A['ordered'].get(str(d), []) for t, d in enumerate(A['days'][:-1])})
    value = funnel.measure(A, record, rules, picks, legs, pool=pool, raw=raw, filtered=filtered,
        offered=offered, states=state_labels(A), cards=cfg['behaviour_card'],
        tolerance=cfg['hard_lines']['behaviour_tolerance'],
        entry_delay=1 if name in ('X1_OPEN', 'S1_NOBLOCK', 'S2_CLOSESTOP', 'S3_BOTH', 'C062', 'K2') else 0,
        same_night_only=name == 'IE9_master',
        raw_picks={t: A['ordered'].get(str(d), []) for t, d in enumerate(A['days'][:-1])}
                  if name in ('IE9_master', 'X1_OPEN', 'S1_NOBLOCK', 'S2_CLOSESTOP', 'S3_BOTH') else None)
    value.update(system=name, record_source=cfg['systems'][name], fingerprints=dict(
        legs=cfg['legs']['sha256'], config=sha(FLOW/'config.json'), code=sha(Path(funnel.__file__))))
    return clean(value)


def fingerprints():
    names = ('studies/trader_replication/funnel.py', 'studies/trader_replication/mainleg.py',
             'studies/trader_replication/pipeline.py', 'studies/trader_replication/config.py',
             'studies/trader_replication/regime.py', 'studies/trader_replication/datasets.py',
             'studies/trader_replication/system.py', 'studies/martin_luk/workflow/adapter.py',
             'studies/martin_luk/workflow/bootstrap.py', 'studies/martin_luk/workflow/history.py',
             'studies/martin_luk/workflow/verify.py', 'studies/martin_luk/workflow/frozen_cache.py',
             'studies/martin_luk/workflow/capital.py', 'studies/martin_luk/workflow/status.py',
             '.claude/workflows/trader-replication-loop.js', 'skills/trader-replication/references/WORKFLOW_CN.md',
             'studies/martin_luk/workflow/config.json')
    cfg = read(FLOW/'config.json')
    return dict(code={p: sha(ROOT/p) for p in names},
        data={i['name']: i.get('checksums_sha256') for i in cfg['datasets']['items']},
        replay_artifacts={i['path']: i['sha256'] for i in cfg['datasets'].get('artifacts', [])},
        evaluation={i['path']: sha(ROOT/i['path']) for i in cfg['datasets']['evaluation']})


def status():
    from .status import generate
    return generate()


def cached(line, version):
    from . import frozen_cache
    state = read(FLOW/'state.json')
    expected = (read(FLOW/'config.json')['reference_accounts'] if line == 'reference' else
                [state['components'][line]['version']])
    if version not in expected:
        raise ValueError('version is not the frozen component')
    if line == 'selection':
        return frozen_cache.selection_score()
    if line == 'trading':
        return frozen_cache.bench_score()
    files = frozen_cache.load(line, version)
    if line == 'conversion' and files['allocation.json'] != state['components']['conversion']:
        raise ValueError('frozen allocation differs from state')
    if line == 'regime' and files['states.json']['spec_sha'] != state['components']['regime']['spec_sha']:
        raise ValueError('frozen regime definition differs from state')
    return files
