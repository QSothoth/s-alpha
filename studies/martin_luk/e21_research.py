"""E21: the unchanged E19 S1, one 2026 check, and read-only main-leg diagnostics."""
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import replace
import gc
import json
from pathlib import Path
import resource
from unittest.mock import patch

import numpy as np

from . import e19_research as E19
from . import e21_review as REVIEW

E15, E16, M = E19.E15, E19.E16, E19.E16.M
ROOT = E15.ROOT
WORK = M.STUDY.root/'reports/e21_work'
PREREG = M.STUDY.root/'notes/PREREG_E21_CN.md'
CUT = E19.D.CUT
read, write = E19.read, E15.write


def provenance():
    paths = [PREREG, Path(__file__), Path(REVIEW.__file__), M.STUDY.root/'tests/test_ie47_e21.py',
             M.STUDY.ledger, ROOT/'studies/trader_replication/mainleg.py',
             M.STUDY.root/'reports/e15_work/master_swap/master_swap.py',
             M.STUDY.root/'reports/final_system_r74.json', E19.WORK/'summary.json']
    return dict(E15.fingerprints(), **E19.provenance(),
                **{str(p.relative_to(ROOT)): E19.sha(p) for p in paths})


def once(stage):
    frozen = read(WORK/'preregistered.json')
    assert frozen['source_sha256'] == provenance(), 'E21 frozen source or inputs changed'
    with (WORK/f'{stage}_started.json').open('x', encoding='utf-8') as stream:
        json.dump(dict(source_sha256=provenance(), memory=E15.B.memory()), stream, indent=1)


def freeze():
    WORK.mkdir(exist_ok=True)
    report = M.STUDY.root/'reports/E16_CN.md'
    with (WORK/'E16_before.md').open('xb') as stream:
        stream.write(report.read_bytes())
    # Preserve existing code, registration, reports and prior experiments without copying their data.
    paths = {ROOT/p for p in read(M.STUDY.root/'reports/e20_work/before.json')}
    paths.update(p for p in (M.STUDY.root/'reports').rglob('*')
                 if p.is_file() and WORK not in p.parents and p.suffix in ('.json', '.md', '.py'))
    protected = {str(p.relative_to(ROOT)): E19.sha(p) for p in sorted(paths) if p != report}
    write(WORK/'protected.json', protected)
    write(WORK/'preregistered.json', dict(source_sha256=provenance(), memory=E15.B.memory(),
          report_before_sha256=E19.sha(WORK/'E16_before.md'), approved_exception='midpoint_only',
          independent_out_of_sample=False))
    print('E21 preregistration and protected files frozen', flush=True)


def configure(st, A, cfg, original, R, name):
    E19.configure(A, original, R, name)
    return st.build(A, dict(cfg, candidate='C062'))


def signal_rows(A, book):
    return [dict(day=str(A['days'][d]), code=str(A['codes'][e[1]]), fill=float(e[3]),
                 stop=float(e[4]), kind=e[5], priority=list(e[0]))
            for d, row in enumerate(book) for e in row]


def prefix_value(st, A, cfg, original, R, end):
    book, rules, _, pool = configure(st, A, cfg, original, R, 'S1')
    trades = E15.Y.simulate(st.px(A), st.ema_inputs(A, pool, rules), rules, book,
                           E15.E.TRAIN[0], end, audit=True)[2]
    k = int(np.searchsorted(A['days'], CUT, side='right'))
    return dict(picks={d: v for d, v in R['picks'].items() if d <= CUT},
                entries=signal_rows(A, book[:k]), events=E15.B.execution_events(trades, CUT))


def evaluate(st, A, cfg, original, R, name, span, directory=WORK, master=False):
    original_configure = E19.configure
    def adapter(A, original, R, name):
        result = original_configure(A, original, R, name)
        if master and name == 'S1':
            book, rules, mask, pool = A['_e14_base']
            A['_e14_base'] = book, replace(rules, make_room_kind={'master_close': E19.RETRY}), mask, pool
        return result
    with patch.object(E19, 'WORK', directory), patch.object(E19, 'configure', adapter):
        return E19.evaluate(st, A, cfg, original, R, name, span)


def defaults(directory, reference, names=('BASE', 'S1')):
    result = {}
    for name in names:
        result[name] = {suffix: read(directory/f'{name}_train/C062_2024_{suffix}.json') ==
                       read(reference/f'{name}_train/C062_2024_{suffix}.json')
                       for suffix in ('trades', 'curve', 'legs', 'stats')}
        result[name]['summary'] = (read(directory/'summary.json')[name+'_train'] ==
                                   read(reference/'summary.json')[name+'_train'])
    write(directory/'defaults.json', result)
    assert all(all(r.values()) for r in result.values()), result


def prefix():
    once('prefix')
    st, A, cfg, original, R = E19.prepare()
    write(WORK/'inputs.json', dict(cfg=cfg, picks=R['picks']))
    for name in ('BASE', 'S1'):
        evaluate(st, A, cfg, original, R, name, 'train')
    defaults(WORK, E19.WORK)
    base, s1 = [read(WORK/'summary.json')[n+'_train'] for n in ('BASE', 'S1')]
    assert all(s1['by_year'][y] >= base['by_year'][y] for y in ('2024', '2025')) and s1['maxdd'] <= .5
    full = prefix_value(st, A, cfg, original, R, E15.E.TRAIN[1])
    write(WORK/'prefix_full.json', full)
    del st, A, original, R
    gc.collect()
    st, A, cfg, original, R = E19.prepare(CUT)
    cut = prefix_value(st, A, cfg, original, R, CUT)
    write(WORK/'prefix_cut.json', cut)
    comparisons = dict(cut={key: full[key] == cut[key] for key in full})
    del st, A, original, R, cut
    gc.collect()
    # Alter real future bars in memory before selection, ADR, EMAs, books and account inputs are rebuilt.
    load = M.panels.load
    def future_changed(*args, **kwargs):
        p = load(*args, **kwargs)
        k = int(np.searchsorted(p['days'], CUT, side='right'))
        for key in ('open', 'high', 'low', 'close', 'raw_close'):
            p[key][k:] *= 3
        p['volume'][k:] *= 2
        p['turnover'][k:] *= 6
        return p
    with patch.object(M.panels, 'load', future_changed):
        st, A, cfg, original, R = E19.prepare()
        changed = prefix_value(st, A, cfg, original, R, E15.E.TRAIN[1])
    write(WORK/'prefix_perturbed.json', changed)
    comparisons['future_perturbation'] = {key: full[key] == changed[key] for key in full}
    ok = all(all(v.values()) for v in comparisons.values())
    write(WORK/'truncation.json', dict(ok=ok, cut=CUT, comparisons=comparisons,
          event_count=len(full['events']), source_sha256=provenance(), memory=E15.B.memory()))
    assert ok, comparisons
    print('E21 cutoff and future perturbation passed:', comparisons, flush=True)


def validate():
    assert read(WORK/'truncation.json')['ok'], 'Prefix check required before 2026'
    once('validation')
    st, A, cfg, original, R = E19.prepare()
    for name in ('BASE', 'S1'):
        for span in ('2026', 'full'):
            evaluate(st, A, cfg, original, R, name, span)
    signals = {}
    for name in ('BASE', 'S1'):
        book, _, _, _ = configure(st, A, cfg, original, R, name)
        signals[name] = signal_rows(A, book)
        write(WORK/f'{name}_signals.json', signals[name])
    observations = M.entry_book(A, R['picks'], **M.E6['E6c'])[2]
    REVIEW.diagnose(A, R, signals, observations, WORK)
    write(WORK/'validation_complete.json', dict(source_sha256=provenance(), memory=E15.B.memory(),
          independent_out_of_sample=False, s1_2026_evaluations=1, s1_full_evaluations=1))


def master():
    assert read(WORK/'validation_complete.json')['source_sha256'] == provenance()
    once('master')
    from studies.trader_replication.martin import Martin
    m = Martin()
    m.unified = True
    Am = m.arrays('us')
    em = m.build(Am, read(M.STUDY.root/'reports/final_system_r74.json')['config'])[0]
    days, codes = list(map(str, Am['days'])), list(map(str, Am['codes']))
    book = [[] for _ in em]
    for d, row in enumerate(em):
        for rank, e in enumerate(sorted(row, key=lambda x: x[0])):
            if e[2] == 1:
                book[d].append(((rank, d, codes[e[1]]), e[1], 1, float(e[3]), float(e[4]), 'master_close', None))
    del Am, m, em
    gc.collect()
    st, A, cfg, original, R = E19.prepare()
    assert days == list(map(str, A['days'])) and codes == list(map(str, A['codes']))
    original = book, original[1], original[2], original[3]
    Rm = dict(R, picks={days[d]: [codes[e[1]] for e in row] for d, row in enumerate(book)})
    directory = WORK/'master'
    directory.mkdir(exist_ok=True)
    # The unchanged master+C062 train account proves that the book adapter matches the E15 swap.
    evaluate(st, A, cfg, original, R, 'BASE', 'train', directory)
    previous = M.STUDY.root/'reports/e15_work/master_swap/train'
    proof = {s: read(directory/f'BASE_train/C062_2024_{s}.json') == read(previous/f'C062_2024_{s}.json')
             for s in ('trades', 'curve', 'legs', 'stats')}
    write(directory/'defaults.json', proof)
    assert all(proof.values()), proof
    write(directory/'picks.json', Rm['picks'])
    for span in ('train', '2026', 'full'):
        evaluate(st, A, cfg, original, Rm, 'S1', span, directory, master=True)
    write(WORK/'master_complete.json', dict(source_sha256=provenance(), memory=E15.B.memory(),
          nomination_source='master long close signal on its known day, effective next session',
          kind_adapter={'master_close': E19.RETRY}))


def checks():
    frozen = read(WORK/'preregistered.json')
    assert frozen['source_sha256'] == provenance()
    protected = {p: E19.sha(ROOT/p) == digest for p, digest in read(WORK/'protected.json').items()}
    report = (M.STUDY.root/'reports/E16_CN.md').read_bytes()
    prefix = (WORK/'E16_before.md').read_bytes()
    result = dict(ok=all(protected.values()) and report.startswith(prefix), protected=protected,
                  report_prefix_preserved=report.startswith(prefix), memory=E15.B.memory())
    write(WORK/'checks.json', result)
    assert result['ok'], [p for p, ok in protected.items() if not ok]
    print('E21 protected files and report prefix:', result['ok'], flush=True)


if __name__ == '__main__':
    from .e1_board_smoke import offline
    offline()
    parser = argparse.ArgumentParser()
    parser.add_argument('stage', choices=('freeze', 'prefix', 'validate', 'master', 'checks'))
    stage = parser.parse_args().stage
    resource.setrlimit(resource.RLIMIT_AS, (E15.LIMIT, E15.LIMIT))
    with E19.runtime():
        globals()[stage]()
