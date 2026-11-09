"""One preregistered daily-close E5 candidate; existing E1-E4 artifacts stay read-only."""
from __future__ import annotations

import argparse
from collections import Counter
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
from studies.trader_replication import compare, gate as G, panels, runner, success, systems, system as Y
from studies.trader_screens import board, scan
from . import e1_research as E, ie47_e1 as M
from .e1_board_smoke import inventory, offline
from .ie47_audit import progress, write

ROOT = Path(__file__).resolve().parents[2]
OUT = M.STUDY.reports
WORK = OUT/'e5_work'
PREREG = M.STUDY.root/'notes/PREREG_E5_CN.md'
SELECTED = OUT/'e5_selected.json'


def fingerprints():
    paths = (PREREG, M.PROFILE, Path(M.__file__), Path(__file__), Path(E.__file__), Path(Y.__file__))
    return dict(files={str(p.relative_to(ROOT)): SP.sha(p) for p in paths}, code_digest=compare.code_digest())


def start(name):
    with (WORK/f'{name}_started.json').open('x', encoding='utf-8') as stream:
        json.dump(fingerprints(), stream, indent=1)


def details(stats, trades, events=()):
    for year, row in [('all', stats), *stats['annual'].items()]:
        closed = [t for t in G.closed(trades) if year == 'all' or t['entry'].startswith(year)]
        row['exit_reasons'] = dict(Counter(t['why'] for t in closed))
        row['median_days'] = float(np.median([t['days'] for t in closed])) if closed else None
        row['mean_r'] = float(np.mean([t['r'] for t in closed])) if closed else None
        row['observation_events'] = dict(Counter(e['why'] for e in events
                                                 if year == 'all' or e['day'].startswith(year)))


def his_tickers(st, A, rules, pool):
    entries = [[] for _ in A['days']]
    di, ci = ({str(v): i for i, v in enumerate(A[k])} for k in ('days', 'codes'))
    rows, seen = [], set()
    for t in st.trades():
        if t.side != 'long' or t.precision != 'exact' or not E.TRAIN[0] <= t.entry_date <= E.TRAIN[1]:
            continue
        code = t.ticker if t.ticker.startswith('US.') else 'US.'+t.ticker
        d, j = di.get(t.entry_date), ci.get(code)
        row = dict(id=t.id, code=code, day=t.entry_date, his_outcome=t.outcome, his_r=t.r_multiple)
        if d is None or j is None or not d or not A['has'][d, j]:
            row['status'] = 'missing_data'
        elif (d, j) in seen:
            row['status'] = 'duplicate_same_stock_day'
        else:
            seen.add((d, j))
            book, _, events = M.entry_book(A, {str(A['days'][d-1]): [code]}, 1, close_confirmed=True)
            if book[d]:
                entries[d].append(book[d][0])
                row['status'] = 'triggered'
            else:
                row['status'] = 'wide_stop' if any(e['why'] == 'wide_stop' for e in events) else 'no_close_break_or_invalid_bar'
        rows.append(row)
    stats, trades, _, _ = E.summary(st, A, entries, rules, pool, E.TRAIN)
    details(stats, trades)
    bought = {(t['code'], t['entry']): t for t in trades}
    for row in rows:
        if row['status'] == 'triggered':
            trade = bought.get((row['code'], row['day']))
            row['status'] = 'bought' if trade else 'account_rejected'
            if trade:
                row.update(our_ret=trade['ret'], our_r=trade['r'], days=trade['days'], why=trade['why'])
    write(WORK/'his_exact_trades.json', trades)
    return dict(span=list(E.TRAIN), his_public=st.his, his_tickers_e5=stats, per_trade=rows,
                exact=dict(all=len(rows), bought=sum(r['status'] == 'bought' for r in rows),
                           statuses=dict(Counter(r['status'] for r in rows))), same_account_rules=True)


def train():
    if (OUT/'e5_train.json').exists() or SELECTED.exists():
        raise ValueError('E5 training/configuration already recorded; do not overwrite')
    start('train')
    migration = json.loads((OUT/'e1_selection.json').read_text())
    if migration['ordered_exact_rate'] != 1 or not migration['scorecard_equal']:
        raise ValueError('existing selection migration is not identical')
    st = M.IE47Study()
    st.progress = progress
    A = st.arrays('us', upto=E.TRAIN[1])
    selected = st.selected(A)
    cfg = dict(candidate='E5', profile_sha256=SP.sha(M.PROFILE),
               frozen_inputs_sha256=M.inputs_digest(selected['sources']))
    trace = {}
    entries, rules, _, pool = st.build(A, cfg, trace)
    stats, trades, curve, dates = E.summary(st, A, entries, rules, pool, E.TRAIN, draws=100)
    details(stats, trades, trace['observations'])
    stats['gate_partial'] = dict(data=E.data_gate(A, E.TRAIN), fills=G.check_fills(A, trades),
                                 win_rate=G.check_win(trades))
    write(OUT/'e5_train.json', dict(config=cfg, stats=stats, preregistered_sha256=SP.sha(PREREG),
                                   source_sha256=fingerprints()))
    write(WORK/'train_trades.json', trades)
    write(WORK/'train_curve.json', dict(days=dates.tolist(), equity=curve.tolist()))
    exact = his_tickers(st, A, rules, pool)
    exact['ie47_e5'] = stats
    write(OUT/'e5_three.json', exact)
    with SELECTED.open('x', encoding='utf-8') as stream:
        json.dump(dict(chosen='E5', config=cfg, preregistered_sha256=SP.sha(PREREG),
                       source_sha256=fingerprints(), fixed_by_task=True), stream, ensure_ascii=False, indent=1)
        stream.write('\n')
    progress(f"E5 training={stats['total']:+.4f}, closed={stats['trades']}; 2026 unmeasured")


def validate():
    if (OUT/'e5_validation.json').exists():
        raise ValueError('E5 validation already recorded; read it without reevaluation')
    selected = json.loads(SELECTED.read_text())
    if selected['preregistered_sha256'] != SP.sha(PREREG) or selected['source_sha256'] != fingerprints():
        raise ValueError('E5 preregistration or source changed after training')
    start('validation')
    st, cfg = M.IE47Study(), selected['config']
    st.progress = progress
    A = st.arrays('us')
    trace = {}
    entries, rules, _, pool = st.build(A, cfg, trace)
    full, trades, curve, dates = E.summary(st, A, entries, rules, pool, panels.WINDOW, draws=100)
    heldout, held_trades, _, _ = E.summary(st, A, entries, rules, pool, E.VALIDATE, draws=100)
    details(full, trades, trace['observations'])
    details(heldout, held_trades, [e for e in trace['observations'] if e['day'] >= E.VALIDATE[0]])
    dropped = success.drop_top(A, entries, trades)
    full['drop2'] = float(Y.simulate(st.px(A), st.ema_inputs(A, pool, rules), rules, dropped, *panels.WINDOW)[0][-1]-1)
    write(WORK/'full_trades.json', trades)
    write(WORK/'validation_trades.json', held_trades)
    write(WORK/'full_curve.json', dict(days=dates.tolist(), equity=curve.tolist()))
    # Deterministic compare replay of the fixed candidate; the two cut panels are genuinely rebuilt.
    load = st.arrays
    with patch.object(st, 'arrays', side_effect=lambda market, upto=None, mode=None:
                      load(market, upto, mode) if upto else A):
        compared = compare.one(st.id, st, cfg, 'us', 'IE47 + E5（研究版）')
    if compared['by_year'] != full['by_year'] or compared['total'] != full['total'] or \
            compared['trades'] != full['trades'] or compared['placebo'] != full['placebo']:
        raise AssertionError('fixed-configuration compare replay differs from the single validation result')
    gate = compared['gate']
    raw, judged = E.judge_years(st, full, gate, full['placebo']['median'], full['drop2'], heldout)
    result = dict(config=cfg, full=full, validate=heldout, gate=gate, judgements=raw, success=judged,
                  preregistered_sha256=SP.sha(PREREG), source_sha256=fingerprints(),
                  selection_scope='one fixed E5 candidate; IE47 and E3 already used 2026',
                  compare_replay_equal=True)
    write(OUT/'e5_validation.json', result)
    record = {'_meta': dict(data=panels.TAG, window=list(panels.WINDOW), draws=100,
                           gate=dict(max_win=G.MAX_WIN, min_trades=G.MIN_TRADES, cuts=G.CUTS)),
              st.id: dict(name=st.name, his=st.his, his_behaviour=st.his_behaviour, markets={'us': compared})}
    write(OUT/'e5_compare.json', record)
    with patch.object(compare, 'OUT', WORK):
        compare.render(record)
    progress(f"E5 2026={full['by_year']['2026']:+.4f}; gate={gate['ok']}; success={sum(ok for _,ok,_ in judged)}/7")


def board_check():
    start('board')
    sys_ = systems.get('martin_luk_ie47')
    result = scan.run('us', mode='frozen', only={sys_.id})
    trader = result['traders'][0]
    ref = json.loads((OUT/'e5_validation.json').read_text())['full']
    equal = trader['check']['ok'] is True and trader['account']['ret'] == ref['total'] \
        and trader['account']['trades'] == ref['trades']
    if not equal or sys_.version != 'IE47 + E5':
        raise AssertionError('registered board does not reproduce E5 comparison')
    write(WORK/'board_frozen.json', result)
    (WORK/'board_frozen.md').write_text(board.render(result), encoding='utf-8')
    output = dict(frozen=dict(status='passed', check=trader['check'], account_equal=True,
                              last_day=result['last_day'], buys=trader['buys'], sells=trader['sells'],
                              holdings=trader['holdings']), network=False, published=False)
    info = inventory('live')
    try:
        scan.run('us', mode='live', only={sys_.id})
        output['live'] = dict(status='passed', inventory=info)
    except (ValueError, RuntimeError) as error:
        output['live'] = dict(status='unavailable', error=str(error), inventory=info)
    output['provisional'] = dict(status='skipped', reason='禁止取新数据；没有完整当日盘中日 K 快照，既存 live 补充输入也有缺口',
                                  inventory=info)
    write(OUT/'e5_board_smoke.json', output)
    progress('E5 frozen board equal; live='+output['live']['status'])


def checks():
    results = {}
    suites = [('custody', ['discover', '-s', 'custody/tests']),
              ('trader_replication', ['discover', '-s', 'studies/trader_replication/tests']),
              ('trader_screens', ['discover', '-s', 'studies/trader_screens/tests', '-t', '.']),
              ('martin_luk', ['discover', '-s', 'studies/martin_luk/tests']),
              ('watch', ['watch/test_watch.py'])]
    for name, args in suites:
        path = WORK/f'test_{name}.log'
        command = [sys.executable, *args] if name == 'watch' else [sys.executable, '-m', 'unittest', *args]
        with path.open('w', encoding='utf-8') as stream:
            rc = subprocess.run(command, stdout=stream, stderr=subprocess.STDOUT).returncode
        results[name] = dict(ok=rc == 0, returncode=rc, log=str(path.relative_to(ROOT)),
                             summary=path.read_text().splitlines()[-5:],
                             peak_child_rss_mib=resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss/1024)
        write(OUT/'e5_checks.json', results)
        progress(name+' tests: '+('passed' if rc == 0 else 'failed'))
    if not all(r['ok'] for r in results.values()):
        raise SystemExit('E5 required tests failed')


def preserved():
    before = json.loads((WORK/'before.json').read_text())['protected_sha256']
    changed = [p for p, digest in before.items() if SP.sha(ROOT/p) != digest]
    write(OUT/'e5_preserved.json', dict(ok=not changed, checked=len(before), changed=changed,
                                      peak_rss_mib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024))
    if changed:
        raise AssertionError('protected prior artifacts changed: '+', '.join(changed))
    progress(f'{len(before)} prior artifacts unchanged')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('stage', choices=('train', 'validate', 'board', 'checks', 'preserved'))
    stage = parser.parse_args().stage
    WORK.mkdir(exist_ok=True)
    if stage == 'checks':
        checks()  # Go secret scanning reserves virtual memory; tests record resident peaks separately.
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
            {'train': train, 'validate': validate, 'board': board_check, 'preserved': preserved}[stage]()
