"""FG: compare fixed FC1 ranking with random order inside the same daily setups."""
from dataclasses import replace
import gc
import json
from pathlib import Path

import numpy as np
from studies import trader_data
from studies.trader_replication import panels, system
from studies.trader_replication import martin_continue_dg as dg
from studies.trader_replication import martin_continue_du as du
from studies.trader_replication import martin_continue_fc as fc
from studies.trader_replication import martin_continue_fe as fe
from studies.trader_replication.martin_continue_dq import sha
from studies.trader_replication.martin_strong_scan import longs, nl_rules

DRAWS, SEED = 100, 20261102


def candidate_rows(reg, filtered, capped, days):
    rows = []
    for day in range(len(days) - 1):
        if not panels.WINDOW[0] <= days[day + 1] <= panels.WINDOW[1]:
            continue
        original = sorted(reg[day], key=lambda e: e[0])
        selected = sorted(capped[day], key=lambda e: e[0])
        signature = lambda e: tuple(e[1:6])
        if [signature(e) for e in original] != [signature(e) for e in selected]:
            raise AssertionError('capped candidates differ ' + days[day])
        candidates = filtered[day]
        if len({e[1] for e in candidates}) != len(candidates):
            raise AssertionError('duplicate candidate names ' + days[day])
        all_signatures = {signature(e) for e in candidates}
        if any(signature(e) not in all_signatures for e in original):
            raise AssertionError('selected candidate absent ' + days[day])
        if original:
            rows.append((day, candidates, len(original)))
    return rows


def random_book(rows, n_days, rng):
    book, choices = [[] for _ in range(n_days)], []
    for day, candidates, n in rows:
        indexes = rng.choice(len(candidates), size=n, replace=False)
        selected = [candidates[i] for i in indexes]
        book[day] = [((1.0, 0, rank),) + tuple(e[1:6]) for rank, e in enumerate(selected)]
        choices.append([day, [int(e[1]) for e in selected]])
    return book, choices


def main():
    root = du.REPORTS
    path = root / 'strong_continue_fc.json'
    ref = json.loads(path.read_text())
    if ref['script_sha256'] != sha(Path(fc.__file__)) or ref['system_sha256'] != sha(Path(system.__file__)):
        raise ValueError('FC source differs')
    dataset = trader_data.dataset('us', mode='frozen', version='trader-data-v1')
    if dataset.digest() != ref['dataset_digest']:
        raise ValueError('dataset differs')
    d = du.make_data(dataset)
    reg = [[((1.0,) + (e[0] if isinstance(e[0], tuple) else (e[0],)),) + tuple(e[1:6])
            for e in row] for row in longs(d.reg)]
    actual, counts = dg.next_open(reg, d.A['open'], d.A['low'], d.days)
    if counts != ref['candidates']:
        raise AssertionError('FC candidate counts differ')
    actual, unknown = fe.remove_precision_unknown(actual, d.days, d.A['codes'])
    if unknown:
        raise ValueError('FC precision unknown: ' + str(unknown))
    for name in ('fp', 'fwd', 'raw', 'o', 'h', 'l', 'c', 't', 'adr', 'to20', 'U', 'rk'):
        if hasattr(d, name):
            delattr(d, name)
    gc.collect()
    trace = {}
    cfg = {k: v for k, v in d.cfg.items() if k != 'short'}
    long_entries, _, mask, long_pool = d.base.build(d.A, cfg, trace)
    pool_diff = int(np.count_nonzero(d.pool != long_pool))
    rows = candidate_rows(reg, trace['filtered'], trace['capped'], d.days)
    width = {'signal_days': len(rows), 'over_cap_days': sum(len(c) > n for _, c, n in rows),
             'all_fit_days': sum(len(c) == n for _, c, n in rows),
             'candidates': sum(len(c) for _, c, _ in rows), 'selected': sum(n for _, _, n in rows)}
    del mask, long_pool, long_entries, trace
    for key in ('pr21', 'pr63', 'pr126', 'rank_pool', 'stack', 'tight'):
        d.A.pop(key, None)
    gc.collect()
    kinds = sorted({e[5] for row in actual for e in row})
    rules = replace(nl_rules(d, 6), gross_cost=True, trail_next_open=True)
    rules = replace(rules, intraday_kinds=tuple(sorted(set(rules.intraday_kinds) | set(kinds))))
    px, em = d.base.px(d.A), d.base.ema_inputs(d.A, d.pool, rules)
    start = int(np.searchsorted(d.A['days'], panels.WINDOW[0]))
    end = int(np.searchsorted(d.A['days'], panels.WINDOW[1], side='right'))
    real = fe.summary(d, actual, rules, px, em, start, end, audit=True)
    if real['trades_digest'] != ref['results']['FC1']['trades_digest']:
        raise AssertionError('FC1 trades differ')
    rng, draws, sample = np.random.default_rng(SEED), [], []
    for draw in range(DRAWS):
        random_signals, choices = random_book(rows, len(d.days), rng)
        random_open, random_counts = dg.next_open(random_signals, d.A['open'], d.A['low'], d.days)
        random_open, unknown = fe.remove_precision_unknown(random_open, d.days, d.A['codes'])
        item = fe.summary(d, random_open, rules, px, em, start, end)
        item.update(candidate_counts=random_counts, precision_unknown=unknown)
        draws.append(item)
        if draw == 0:
            sample = [{'signal_day': d.days[i], 'codes': [str(d.A['codes'][j]) for j in selected]}
                      for i, selected in choices[:6]]
        if (draw + 1) % 10 == 0:
            print('draw', draw + 1, flush=True)
    out = {'dataset_digest': ref['dataset_digest'], 'fc_sha256': sha(path),
           'system_sha256': sha(Path(system.__file__)), 'script_sha256': sha(Path(__file__)),
           'seed': SEED, 'draws': DRAWS, 'pool_difference_stock_days': pool_diff,
           'width': width, 'first_draw_sample': sample, 'real': real, 'random': draws}
    target = root / 'strong_continue_fg.json'
    with target.open('w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
        f.write('\n')
    print('wrote', target, flush=True)


if __name__ == '__main__':
    main()
