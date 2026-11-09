"""PREREG_E9_CN.md: E8c's execution with the names (pool draws) and the day (a random close in the watch) swapped."""
from __future__ import annotations

import argparse
from contextlib import ExitStack
import json
from pathlib import Path
import resource
import subprocess
import sys
from unittest.mock import patch

import numpy as np

from studies import trader_data as TD
from studies.trader_data import panel as TP, supplemental as SP
from studies.trader_replication import gate as G, panels, system as Y
from . import e1_research as E, ie47_e1 as M
from .e1_board_smoke import offline
from .ie47_audit import progress, write

ROOT = Path(__file__).resolve().parents[2]
OUT = M.STUDY.reports
WORK = OUT/'e9_work'
PREREG = M.STUDY.root/'notes/PREREG_E9_CN.md'
RESULT = OUT/'e9_arms.json'
SPANS = {'2024-25': E.TRAIN, '2026': E.VALIDATE}
ARMS = ('B', 'C1', 'C2', 'D')
DRAWS = 100
QUESTIONS = (('排序（收盘突破下）', 'A', 'B'), ('排序（随机买点下）', 'C1', 'D'), ('触发（挑观察期 + 哪天）', 'A', 'C1'),
             ('只看哪天买', 'A', 'C2'), ('触发（随机票上）', 'B', 'D'))


def fingerprints():
    paths = (PREREG, M.PROFILE, Path(M.__file__), Path(__file__), Path(Y.__file__))
    return {str(p.relative_to(ROOT)): SP.sha(p) for p in paths}


def measure(curve, trades):
    closed = G.closed(trades)
    ret = np.array([t['ret_invested'] for t in closed])
    r = np.array([t['r'] for t in closed])
    return dict(total=float(curve[-1]-1), maxdd=float(np.max(1-curve/np.maximum.accumulate(np.r_[1., curve])[1:])),
                n=len(closed), win=float(np.mean(ret > 0)) if len(ret) else None,
                avg_win=float(ret[ret > 0].mean()) if (ret > 0).any() else None,
                avg_loss=float(ret[ret <= 0].mean()) if (ret <= 0).any() else None,
                mean_r=float(r.mean()) if len(r) else None, r5=int((r >= 5).sum()))


def above(x, ys):
    """Share of draws below x (x scalar) or of pairs x_i > y_j (x a list); ties count half."""
    x, ys = np.atleast_1d(np.asarray(x, float))[:, None], np.asarray(ys, float)[None, :]
    return float(((x > ys) + .5*(x == ys)).mean())


def verdict(share):
    return '有贡献' if share >= .7 else '拖累' if share <= .3 else '分不清'


def books(A, result, base_events, arm, rng):
    picks = result['picks']
    if arm in ('B', 'D'):
        picks = M.random_picks(picks, result['pool'], A['days'], A['codes'], rng)
    if arm == 'B':
        return M.entry_book(A, picks, **M.E6['E6c'])[0]
    keep = M.triggered_watches(base_events) if arm == 'C2' else None
    return M.random_day_book(A, picks, rng, keep=keep)[0]


def run():
    if RESULT.exists():
        raise ValueError('E9 already recorded; read it without rerunning')
    write(WORK/'started.json', fingerprints())
    st = M.IE47Study()
    st.progress = progress
    A = st.arrays('us')
    cfg = dict(candidate='E8c', profile_sha256=SP.sha(M.PROFILE), frozen_inputs_sha256=M.inputs_digest(st.selected(A)['sources']))
    trace = {}
    entries, rules, _, pool = st.build(A, cfg, trace)
    result = st.selected(A)
    px, ema = st.px(A), st.ema_inputs(A, pool, rules)

    def sim(book):
        out = {}
        for name, span in SPANS.items():
            curve, _, trades = Y.simulate(px, ema, rules, book, *span, audit=True)
            out[name] = measure(curve, trades)
        return out
    rows = dict(A=sim(entries))
    progress('A: '+json.dumps({k: round(v['total'], 4) for k, v in rows['A'].items()}))
    for arm in ARMS:
        rng, draws = np.random.default_rng(1), []
        for i in range(DRAWS):
            draws.append(sim(books(A, result, trace['observations'], arm, rng)))
            if i % 20 == 19:
                progress(f'{arm}: {i+1}/{DRAWS} peak={resource.getrusage(resource.RUSAGE_SELF).ru_maxrss//1024} MiB')
        rows[arm] = draws
        write(WORK/f'{arm}_draws.json', draws)
    out = dict(preregistered_sha256=SP.sha(PREREG), source_sha256=fingerprints(), config=cfg, draws=DRAWS, seed=1,
               spans={k: list(v) for k, v in SPANS.items()}, A=rows['A'], arms={}, questions={})
    keys = ('total', 'n', 'win', 'avg_win', 'avg_loss', 'mean_r', 'r5', 'maxdd')
    for arm in ARMS:
        out['arms'][arm] = {span: {k: dict(zip(('p10', 'median', 'p90'), map(float, np.percentile(v, (10, 50, 90)))))
                                   for k in keys for v in [[d[span][k] for d in rows[arm] if d[span][k] is not None]] if v}
                            for span in SPANS}
    for title, x, y in QUESTIONS:
        out['questions'][title] = {}
        for span in SPANS:
            pair = {}
            for k in ('total', 'r5'):
                xs = rows['A'][span][k] if x == 'A' else [d[span][k] for d in rows[x]]
                share = above(xs, [d[span][k] for d in rows[y]])
                pair[k] = dict(share=share, verdict=verdict(share))
            out['questions'][title][span] = dict(compare=f'{x} vs {y}', **pair)
    write(RESULT, out)
    for title, v in out['questions'].items():
        progress(title+': '+'; '.join(f"{s} {p['compare']} total={p['total']['share']:.2f}({p['total']['verdict']}) "
                                      f"r5={p['r5']['share']:.2f}" for s, p in v.items()))


def checks():
    results = {}
    for name, args in (('custody', ['discover', '-s', 'custody/tests']),
                       ('martin_luk', ['discover', '-s', 'studies/martin_luk/tests'])):
        path = WORK/f'test_{name}.log'
        with path.open('w', encoding='utf-8') as stream:
            rc = subprocess.run([sys.executable, '-m', 'unittest', *args], stdout=stream,
                                stderr=subprocess.STDOUT).returncode
        results[name] = dict(ok=rc == 0, summary=path.read_text().splitlines()[-3:])
        progress(name+' tests: '+('passed' if rc == 0 else 'failed'))
    write(OUT/'e9_checks.json', results)
    if not all(r['ok'] for r in results.values()):
        raise SystemExit('E9 required tests failed')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('stage', choices=('run', 'checks'))
    stage = parser.parse_args().stage
    WORK.mkdir(exist_ok=True)
    if stage == 'checks':
        checks()
    else:
        resource.setrlimit(resource.RLIMIT_AS, (1_500_000_000, 1_500_000_000))
        offline()
        original = TP.build
        def existing_load(market, mode=None, version=None, upto=None, **kwargs):
            return original(TD.dataset(market, mode, version), upto=upto, write_cache=False)
        def read_only_build(ds, upto=None, cache=True, write_cache=True):
            return original(ds, upto=upto, cache=cache, write_cache=False)
        with ExitStack() as stack:
            stack.enter_context(patch.object(TD, 'load', existing_load))
            stack.enter_context(patch.object(TP, 'build', read_only_build))
            run()
