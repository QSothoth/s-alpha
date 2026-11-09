"""The 2026-10-30 gap review (reports/GAP_REVIEW_20261030_CN.md): the seven success rules (success.judge) and the
dated-trade funnel of every registered system, on the registered configuration, nothing chosen here.

    PY="systemd-run --scope -q -p CPUQuota=40% taskset -c 0 ionice -c3 nice -n 19 env OPENBLAS_NUM_THREADS=1 \
        PYTHONUTF8=1 /opt/futu-opend/venv/bin/python"
    $PY -m studies.trader_replication.review success <id>     # reports/gap_review/success_<id>.json
    $PY -m studies.trader_replication.review funnel <id>      # reports/gap_review/funnel_<id>.json

With TRADER_LISTING=1 (panels.arrays: new listings measured since listing) the same files get a _listing suffix.

His cards: numbers he published with a source (each study's notes/RULES_CN.md); where he published two years the
count and behaviour targets are the mean of those years (study.his_targets' convention) and the per-year rows are
reported beside the verdict.  A measure he never published is left out (rule 3) or fails (rule 2: no sourced count).
"""
from __future__ import annotations

import gc
import json
import os
import sys
from pathlib import Path

import numpy as np

from . import gate as G, panels, success as SU, system as Y, systems as SY

OUT = Path(__file__).resolve().parent / 'reports' / 'gap_review'
WINDOW = panels.WINDOW                         # 2024-01-02 -> 2026-10-16
VALIDATE = ('2026-01-02', '2026-10-16')         # already evaluated many times: rule 6 is a reference only
FUNNEL = ('2023-02-01', '2026-10-16')           # his 2023 trades (Qullamaggie, Marios) count too
DRAWS, SEED = 100, 1                            # as compare.py


def _mean(*v):
    return float(np.mean(v))


CARDS = {
    'martin_luk': dict(
        per_year=_mean(423, 940), per_year_by={'2024': 423, '2025': 940},
        source='2025: 209 wins 731 losses (VKNE@0:20:24, his own words); 2024: 104 wins 319 losses (youtubesummary '
               'of lS9zbnLi1Gg, a second-hand summary, notes/SOURCES.md)',
        behaviour=dict(win=_mean(104 / 423, 209 / 940), avg_win=_mean(.15, .141), avg_loss=_mean(-.03, -.021)),
        years={'2024': 2.83, '2025': 9.698}),
    'christian_flanders': dict(
        per_year=_mean(400, 489), per_year_by={'2024': 400, '2025': 489},
        source='about 400 in 2024, 489 in 2025 (Lot25@00:33:07, 01:15:13; 6aOn@00:12:26, 01:23:31)',
        behaviour=dict(win=_mean(.308, .305), avg_win=_mean(.118, .1744), avg_loss=_mean(-.0335, -.0455),
                       days_win=_mean(11, 17), days_loss=_mean(1.9, 2.1)),
        years={'2024': 4.335, '2025': 1.675}),
    'clement_ang': dict(
        per_year=_mean(800, 1294), per_year_by={'2024': 800, '2025': 1294},
        source='about 800 in 2024, about 1294 in 2025 (zw96@00:36:19, 00:37:30)',
        behaviour=dict(win=.30, avg_win=.054, avg_loss=-.021, days_win=3, days_loss=.8),
        years={'2024': .793, '2025': 1.404}),
    'qullamaggie': dict(per_year=None, source='', behaviour=dict(win=.25), years={},
                        note='no trade count published; 25% win rate is his 2019 (S03), outside the data'),
    'oliver_kell': dict(per_year=None, source='', behaviour={}, years={},
                        note='win rate, count and holding never published (RULES_CN, OK3)'),
    'mark_minervini': dict(per_year=None, source='', behaviour={}, years={},
                           note='only teaching examples (200 trades a year, 40-50% win), no audited statistics'),
    'marios_stamatoudis': dict(
        per_year=500, per_year_by={'2023': 500}, source='close to 500 trades in 2023 (7UfHg8PpDZk@02:07:10)',
        behaviour=dict(win=(.32, .34)), years={},
        note='his numbers are 2023, the year before the window; his USIC year 2023 is outside it'),
    'evan_medeiros': dict(
        per_year=328, source='Lamorak performance page: 328 trades a year on average (E2)',
        behaviour=dict(win=.6376, avg_win=.0229, avg_loss=-.0229 / .81, days_mean=4), years={'2024': .2045},
        note='fund statistics, not a dated ledger; 2025 only to August (+5.03%), left out'),
    'alfredo_holguin': dict(
        per_year=1417 / ((np.datetime64('2026-05-28') - np.datetime64('2024-12-23')).astype(int) / 365.25),
        source='his trade-history page: 1417 trades 2024-12-23 -> 2026-05-28 (notes/trades_holguin.csv)',
        behaviour=dict(win=.918), years={'2025': .560},
        note='2025 is his weekly-summary compounding (+56.0%); the USIC account (+100.2%) is another account'),
}


def card(id_):
    if id_ == 'dan_zanger':
        from studies.dan_zanger.replicate import CARD
        return dict(CARD, per_year_by={}, note='"at least 200 trades" in 23 months of 1998-2000: a floor')
    return CARDS[id_]


def _placebo(st, A, entries, rules, pool, seg):
    px, ema = st.px(A), st.ema_inputs(A, pool, rules)
    return Y.placebo_rank(px, ema, rules, entries, *seg, pool, draws=DRAWS, seed=SEED)


def facts_stock(system, c):
    """What success.judge reads, for a system on the stock engine (study.Study, wrapped or not), US only."""
    st, cfg = system.load()
    A = st.arrays('us')
    entries, rules, mask, pool = st.build(A, cfg)
    res, tr = st.run(A, entries, WINDOW, pool, rules, placebo=0, audit=True)
    curve = res.pop('_curve')
    pl = _placebo(st, A, entries, rules, pool, WINDOW)
    days = A['days'][(A['days'] >= WINDOW[0]) & (A['days'] <= WINDOW[1])]
    span = [str(days[0]), str(days[-1])] if len(curve) == len(days) else ['?', '?']
    pin = panels.pinned()
    checks = dict(data=G.check_data(panels.TAG, A.get('digest'), span, pin['tag'], pin['markets'].get('us'),
                                    WINDOW, A['days']),
                  fills=G.check_fills(A, tr), lookahead=G.check_lookahead(st, cfg, 'us', full=A))
    val, _ = st.run(A, entries, VALIDATE, pool, rules, placebo=0)
    vpl = _placebo(st, A, entries, rules, pool, VALIDATE)
    kept = SU.drop_top(A, entries, tr)
    dropped = sum(map(len, entries)) - sum(map(len, kept))      # 0: the best two's entries were not found
    drop, _ = st.run(A, kept, WINDOW, pool, rules, placebo=0)
    closed = [t for t in tr if t['why'] != 'end']
    ret = np.array([t['ret'] for t in closed], float)
    b = dict(res['behaviour'])
    b['days_mean'] = float(np.mean([t['days'] for t in closed])) if closed else None
    b['max_days'] = float(max(t['days'] for t in closed)) if closed else None
    ours = dict(gate={k: v['ok'] for k, v in checks.items()}, win=float((ret > 0).mean()) if len(ret) else None,
                closed=len(closed), per_year=b['per_year'], behaviour={k: b.get(k) for k in c.get('behaviour', {})},
                years=res['by_year'], counts={y: sum(t['entry'].startswith(y) for t in tr) for y in res['by_year']},
                total=res['total'],
                placebo_median=pl['median'], validate_total=val['total'], validate_placebo_median=vpl['median'],
                total_drop2=drop['total'] if dropped else None)
    longs = [t for t in tr if t.get('side', 1) > 0]
    extra = dict(gate=checks, by_year=res['by_year'], maxdd=res['maxdd'], behaviour=b, placebo=pl,
                 validate_placebo=vpl, drop2_by_year=drop['by_year'], drop2_entries_removed=dropped,
                 per_year_by={y: sum(t['entry'][:4] == y for t in tr) for y in sorted(res['by_year'])},
                 shorts=len(tr) - len(longs),
                 top=sorted(({k: t[k] for k in ('code', 'entry', 'exit', 'ret', 'days', 'why')} for t in closed),
                            key=lambda t: -t['ret'])[:10],
                 config=cfg)
    del A, entries, mask, pool
    gc.collect()
    return ours, extra


def facts_holguin(system, c):
    """Holguin's option engine: no look-ahead or fill check and no drop-the-best-two rerun exist for it (missing)."""
    st, cfg = system.load()
    res, tr = st.evaluate(cfg, WINDOW, draws=DRAWS)
    val, _ = st.evaluate(cfg, VALIDATE, draws=DRAWS)
    closed = [t for t in tr if t['ret'] is not None]
    years = (np.datetime64(WINDOW[1]) - np.datetime64(WINDOW[0])).astype(int) / 365.25
    ours = dict(gate=dict(data=None, lookahead=None, fills=None), win=res['win'], closed=len(closed),
                per_year=len(closed) / years, behaviour=dict(win=res['win']),
                years=res['by_year'], counts={y: sum(t['entry'].startswith(y) for t in tr) for y in res['by_year']},
                total=res['total'],
                placebo_median=res['placebo']['median'], validate_total=val['total'],
                validate_placebo_median=val['placebo']['median'], total_drop2=None)
    extra = dict(by_year=res['by_year'], maxdd=res['maxdd'], placebo=res['placebo'], fidelity=res.get('fidelity'),
                 validate_placebo=val['placebo'], config=cfg,
                 missing='gate data / look-ahead / fills and rule 7 have no implementation on the option engine')
    return ours, extra


def success(id_):
    system = SY.get(id_)
    c = card(id_)
    ours, extra = (facts_holguin if id_ == 'alfredo_holguin' else facts_stock)(system, c)
    rows = SU.judge({k: v for k, v in c.items() if k in ('per_year', 'counts', 'source', 'sources', 'behaviour', 'years')}, ours)
    out = dict(id=id_, version=system.version, status=system.status, card=c, ours=ours,
               rules=[dict(rule=r, ok=ok, why=why) for r, ok, why in rows], passed=SU.passed(rows),
               window=WINDOW, validate=VALIDATE, draws=DRAWS, seed=SEED, **extra)
    for r, ok, why in rows:
        print('SUCCESS', id_, r, 'pass' if ok else 'FAIL', why, flush=True)
    write(f'success_{id_}.json', out)
    return out


def funnel(id_):
    from . import common
    out = common.funnel_one(SY.get(id_), FUNNEL)
    print('FUNNEL', id_, {s: v['n'] for s, v in out['by_stage'].items() if v['n']}, flush=True)
    write(f'funnel_{id_}.json', out)
    return out


SCREEN = 50                                     # placebo draws while screening a round's candidates
WIDTH = 30


def _year_gap(by_year, years):
    v = [abs(float(np.log((1 + by_year[y]) / (1 + h)))) if 1 + by_year.get(y, -1) > 0 else 9.0
         for y, h in years.items()]
    return float(np.mean(v)) if v else None


def evaluate(system, A, cfg, his, draws):
    """One configuration of a registered system (its study wrapped as on the board), on the US window: returns,
    same-pool placebo, his dated longs bought (his years 2024-2025, and 2026 apart), width, count, win."""
    from . import fidelity as FI, study
    W, base = system.study, system.study
    base = getattr(W, 'base', W)
    entries, rules, mask, pool = W.build(A, cfg)
    st, tr = base.run(A, entries, WINDOW, pool, rules, placebo=0, audit=True)
    st.pop('_curve', None)
    st['placebo'] = _placebo(base, A, entries, rules, pool, WINDOW) if draws == DRAWS else \
        dict(Y.placebo_rank(base.px(A), base.ema_inputs(A, pool, rules), rules, entries, *WINDOW, pool, draws=draws,
                            seed=SEED))
    sel = [x for x in his if x[0].entry_date <= '2025-12-31']
    later = [x for x in his if x[0].entry_date > '2025-12-31']
    st['bought'] = dict(sel=[study.bought(A, tr, sel), len(sel)], y2026=[study.bought(A, tr, later), len(later)])
    st['signals_per_day'] = FI.width(mask, A['days'], *WINDOW)
    closed = [t for t in tr if t['why'] != 'end']
    st['win'] = float(np.mean([t['ret'] > 0 for t in closed])) if closed else None
    st['per_year_sel'] = sum('2024' <= t['entry'][:4] <= '2025' for t in tr) / 2
    st['bought_codes'] = sorted({(t['code'], t['entry']) for t in tr} & {(str(A['codes'][j]), x.entry_date)
                                                                         for x, j, *_ in his})
    return st


def gap_round(id_, name):
    """studies/<id>/notes/rounds/<name>.json on the registered configuration (notes/PREREG_<name>.md has the rule):
    every candidate screened with SCREEN draws, the chosen one again with DRAWS; reports/<name lower>.json."""
    system = SY.get(id_)
    c = card(id_)
    root = Path(__file__).resolve().parents[2] / 'studies' / id_
    spec = json.loads((root / 'notes' / 'rounds' / f'{name}.json').read_text(encoding='utf-8'))
    from .study import merged
    base_cfg = system.config
    cfgs = {spec['ref']: base_cfg, **{k: merged(base_cfg, v) for k, v in spec['candidates'].items()}}
    st0 = getattr(system.study, 'base', system.study)
    A = st0.arrays('us')
    his = [x for x in st0.located(A, st0.trades()) if WINDOW[0] <= x[0].entry_date <= WINDOW[1]
           and x[0].side == 'long']
    lo, hi = ((1 - .3) * c['per_year'], (1 + .3) * c['per_year']) if c['per_year'] else (0, float('inf'))
    res, fails = {}, {}
    for k, cfg in cfgs.items():
        st = evaluate(system, A, cfg, his, SCREEN)
        st['year_gap'] = _year_gap(st['by_year'], c['years'])
        res[k] = st
        print(name, k, f"total {st['total']:+.3f} years", {y: round(v, 3) for y, v in st['by_year'].items()},
              f"placebo {st['placebo']['median']:+.3f} win {st['win']:.3f} per_year {st['per_year_sel']:.0f}",
              f"bought {st['bought']} width {st['signals_per_day']['median']} year_gap {st['year_gap']}",
              flush=True)
    ref = res[spec['ref']]

    def gates(st):
        f = []
        if not st['total'] > st['placebo']['median']:
            f.append('placebo')
        if not (st['win'] is not None and st['win'] <= G.MAX_WIN):
            f.append('win')
        if not lo <= st['per_year_sel'] <= hi:
            f.append('count')
        if st['bought']['sel'][0] < ref['bought']['sel'][0] + 1:
            f.append('bought')
        if st['year_gap'] is not None and st['year_gap'] > ref['year_gap'] + 1e-12:
            f.append('years')
        if st['signals_per_day']['median'] > WIDTH:
            f.append('width')
        return f
    order = lambda k: (res[k]['bought']['sel'][0], -(res[k]['year_gap'] or 0))
    pending = [k for k in spec['candidates'] if not gates(res[k])]
    chosen = spec['ref']
    while pending:
        k = max(pending, key=order)
        st = evaluate(system, A, cfgs[k], his, DRAWS)      # the full placebo for the one to carry
        st['year_gap'], st['placebo_screen'] = _year_gap(st['by_year'], c['years']), res[k]['placebo']
        res[k] = st
        if not gates(st):
            chosen = k
            break
        pending.remove(k)
    for k in spec['candidates']:
        fails[k] = gates(res[k])
    out = dict(name=name, id=id_, version=system.version, configs=cfgs, results=res, failed_gates=fails,
               chosen=chosen, count_range=[lo, hi], card_years=c['years'])
    (root / 'reports').mkdir(exist_ok=True)
    (root / 'reports' / f'{name.lower()}.json').write_text(json.dumps(out, indent=1, default=float), encoding='utf-8')
    print(name, 'chosen', chosen, 'fails', fails, flush=True)
    return out


def write(name, out):
    OUT.mkdir(parents=True, exist_ok=True)
    if os.environ.get('TRADER_LISTING') == '1':
        name = name.replace('.json', '_listing.json')
    (OUT / name).write_text(json.dumps(out, indent=1, default=float, ensure_ascii=False), encoding='utf-8')


if __name__ == '__main__':
    {'success': success, 'funnel': funnel, 'round': gap_round}[sys.argv[1]](*sys.argv[2:])
