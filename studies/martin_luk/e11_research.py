"""PREREG_E11_CN.md: re-entry joined to the end-to-end execution; five candidates selected on 2024-25, 2026 once."""
from __future__ import annotations

import argparse
from contextlib import ExitStack
import json
from pathlib import Path
import resource
from unittest.mock import patch

import numpy as np

from studies import trader_data as TD
from studies.trader_data import panel as TP, supplemental as SP
from studies.trader_replication import gate as G, panels, system as Y
from . import e1_research as E, e8_research as E8, e10_research as X, ie47_e1 as M
from .e1_board_smoke import offline
from .ie47_audit import progress, write

ROOT = Path(__file__).resolve().parents[2]
OUT = M.STUDY.reports
WORK = OUT/'e11_work'
PREREG = M.STUDY.root/'notes/PREREG_E11_CN.md'
RESULT = OUT/'e11_train.json'
SELECTED = OUT/'e11_selected.json'
VALIDATION = OUT/'e11_validation.json'
RE2_KIND = 'ie47_reentry2'
REFERENCES = ('ref', 'K2', 'RE')
CANDIDATES = ('L1', 'L2', 'L3', 'L4', 'L5')            # preregistered tie order
LAYERS = dict(ref=(), K2=('AS', 'X1'), RE=('RE',), L1=('AS', 'X1', 'RE'), L2=('AF', 'X1', 'RE'), L3=('AF', 'RE'),
              L4=('AF', 'X1'), L5=('AS', 'X1', 'RE'))


def fingerprints():
    paths = (PREREG, M.PROFILE, Path(M.__file__), Path(X.__file__), Path(__file__), Path(Y.__file__), Path(E.__file__))
    return {str(p.relative_to(ROOT)): SP.sha(p) for p in paths}


def reentry_rounds(A, entries, e9, rounds=2):
    """M.reentry_book, then the same rule once more on each re-buy only (RE2_KIND): at most `rounds` re-buys a signal."""
    out = M.reentry_book(A, entries, e9)
    last = [row[len(entries[d]):] for d, row in enumerate(out)]
    for _ in range(rounds-1):
        more = M.reentry_book(A, last, e9)
        last = [[e[:5]+(RE2_KIND,)+e[6:] for e in row[len(last[d]):]] for d, row in enumerate(more)]
        out = [row+last[d] for d, row in enumerate(out)]
    return out


def configs(A, ref_book, ref_rules):
    """name -> (book, rules); every book is ref's close breaks, plus re-buys where RE is a layer."""
    out = {}
    for name, layers in LAYERS.items():
        book = ref_book
        if 'RE' in layers:
            book = reentry_rounds(A, ref_book, A['e9'], 2 if name == 'L5' else 1)
        out[name] = (book, X.rule_layers(ref_rules, layers))
    return out


def evaluate(st, A, pool, name, book, rules, span, ref_r):
    stats, trades, _, _ = E.summary(st, A, book, rules, pool, span)
    E8.invested(st, stats, trades)
    track = {}
    Y.simulate(st.px(A), st.ema_inputs(A, pool, rules), rules, book, *span, track=track)
    stats['mechanism'] = X.mechanism(A, book, [], trades, track, None, ref_r)
    stats['his_exact'] = X.his_exact(st, A, trades, span)
    write(WORK/f'{name}_{span[0][:4]}_trades.json', trades)
    progress(f"{name}: {span[0][:4]} total={stats['total']:+.4f} closed={stats['trades']} win={stats['win']:.3f} "
             f"big+={stats['mechanism']['big_capture']['share_positive']} w20={stats['mechanism']['winners20']}")
    return stats


def setup():
    st = M.IE47Study()
    st.progress = progress
    A = st.arrays('us')
    cfg = dict(candidate='E8c', profile_sha256=SP.sha(M.PROFILE), frozen_inputs_sha256=M.inputs_digest(st.selected(A)['sources']))
    ref_book, ref_rules, _, pool = st.build(A, cfg, {})
    return st, A, cfg, ref_book, ref_rules, pool, configs(A, ref_book, ref_rules)


def ref_rs(st, A, ref_book, ref_rules, pool, span):
    _, trades, _, _ = E.summary(st, A, ref_book, ref_rules, pool, span)
    keys = X.keyed(A, ref_book)
    return {keys[(t['code'], t['entry'])]: t['r'] for t in G.closed(trades)}


def train():
    if RESULT.exists() or SELECTED.exists():
        raise ValueError('E11 training already recorded; do not rerun or select again')
    write(WORK/'train_started.json', fingerprints())
    st, A, cfg, ref_book, ref_rules, pool, todo = setup()
    ref_r = ref_rs(st, A, ref_book, ref_rules, pool, E.TRAIN)
    out = dict(preregistered_sha256=SP.sha(PREREG), source_sha256=fingerprints(), span=list(E.TRAIN), base=cfg, runs={})
    for name in REFERENCES + CANDIDATES:
        out['runs'][name] = evaluate(st, A, pool, name, *todo[name], E.TRAIN, ref_r)
        write(RESULT.with_suffix('.partial.json'), out)
    ref = out['runs']['ref']
    def eligible(k):
        s = out['runs'][k]
        return s['trades'] >= .7*ref['trades'] and s['mechanism']['winners20'] >= .9*ref['mechanism']['winners20']
    ok, chosen = [k for k in CANDIDATES if eligible(k)], None
    if ok:
        best = max(out['runs'][k]['total'] for k in ok)
        near = [k for k in ok if best-out['runs'][k]['total'] < .02]
        chosen = min(near, key=lambda k: (out['runs'][k]['behaviour_gap'], CANDIDATES.index(k)))
    out.update(eligible=ok, chosen=chosen)
    write(RESULT, out)
    with SELECTED.open('x', encoding='utf-8') as stream:
        json.dump(dict(chosen=chosen, eligible=ok, preregistered_sha256=SP.sha(PREREG), source_sha256=fingerprints()),
                  stream, ensure_ascii=False, indent=1)
    progress(f'eligible={ok}; selected {chosen} on 2024-25 only; 2026 unmeasured')


def validate():
    if VALIDATION.exists():
        raise ValueError('E11 validation already recorded')
    selected = json.loads(SELECTED.read_text())
    if selected['preregistered_sha256'] != SP.sha(PREREG) or selected['source_sha256'] != fingerprints():
        raise ValueError('E11 preregistration or source changed after selection')
    if selected['chosen'] is None:
        raise ValueError('E11 selected nothing; 2026 is not measured')
    with (WORK/'validation_started.json').open('x', encoding='utf-8') as stream:
        json.dump(dict(selected_sha256=SP.sha(SELECTED)), stream)
    st, A, cfg, ref_book, ref_rules, pool, todo = setup()
    ref_r = ref_rs(st, A, ref_book, ref_rules, pool, E.VALIDATE)
    name = selected['chosen']
    held = evaluate(st, A, pool, name, *todo[name], E.VALIDATE, ref_r)
    full = evaluate(st, A, pool, name+'_full', *todo[name], panels.WINDOW, ref_r)
    write(VALIDATION, dict(chosen=name, validate=held, full=full, preregistered_sha256=SP.sha(PREREG),
                           scope='one chosen E11 candidate; 2026 already used by IE47 and E3-E10'))
    progress(f"{name} 2026={held['total']:+.4f}; full={full['total']:+.4f}")


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('stage', choices=('train', 'validate'))
    stage = parser.parse_args().stage
    WORK.mkdir(exist_ok=True)
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
        {'train': train, 'validate': validate}[stage]()
