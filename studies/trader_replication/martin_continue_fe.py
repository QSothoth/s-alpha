"""FE: preselect random names in the prior-known pool and replay fixed account rules."""
from collections import Counter
from dataclasses import replace
import gc
import json
from pathlib import Path

import numpy as np
from studies import trader_data
from studies.trader_replication import compare, panels, system
from studies.trader_replication import martin_continue_dg as dg
from studies.trader_replication import martin_continue_du as du
from studies.trader_replication import martin_continue_fc as fc
from studies.trader_replication.martin_continue_b_check import digest
from studies.trader_replication.martin_continue_dq import sha
from studies.trader_replication.martin_strong_scan import longs, nl_rules

DRAWS, SEED = 100, 20261101


def eligible_rows(reg, pool, close, days):
    rows = []
    original_outside = 0
    for day in range(len(days) - 1):
        if not panels.WINDOW[0] <= days[day + 1] <= panels.WINDOW[1] or not reg[day]:
            continue
        eligible = np.flatnonzero(pool[day] & np.isfinite(close[day]) & (close[day] > 0))
        orders = sorted(reg[day], key=lambda e: e[0])
        original_outside += sum(not pool[day, e[1]] for e in orders)
        rows.append((day, eligible, orders))
    return rows, original_outside


def random_book(rows, close, n_days, rng):
    book = [[] for _ in range(n_days)]
    shortages, chosen = [], []
    for day, eligible, orders in rows:
        n = min(len(eligible), len(orders))
        if n < len(orders):
            shortages.append([day, len(orders), n])
        if not n:
            continue
        picks = rng.choice(eligible, size=n, replace=False)
        for order, j in zip(orders, picks):
            ratio = float(order[4]) / float(order[3])
            price = float(close[day, j])
            if not 0 < ratio < 1:
                raise ValueError('invalid original stop ratio')
            book[day].append((order[0], int(j), order[2], price, price * ratio, order[5]))
        chosen.append([day, list(map(int, picks))])
    return book, shortages, chosen


def remove_precision_unknown(book, days, codes):
    clean, unknown = [], []
    for day, row in enumerate(book):
        accepted = []
        for entry in row:
            if np.float32(entry[3]) == np.float32(entry[4]):
                unknown.append([days[day], str(codes[entry[1]]), float(entry[3]), float(entry[4])])
            else:
                accepted.append(entry)
        clean.append(accepted)
    return clean, unknown


def summary(d, book, rules, px, em, start, end, audit=False):
    track = {}
    curve, dates, trades = system.simulate(px, em, rules, book, *panels.WINDOW, audit=audit, track=track)
    m = compare.metrics(curve, dates, trades, book, start, end)
    return {'total': m['total'], 'by_year': m['by_year'], 'maxdd': m['maxdd'], 'win': m['win'],
            'payoff': m['payoff'], 'entries_by_year': {y: sum(t['entry'].startswith(y) for t in trades)
                                                       for y in ('2024', '2025', '2026')},
            'close_days_gross_over_one': int(sum(g > 1 + 1e-9 for g in track['gross'])),
            'trades_digest': digest(trades) if audit else None}


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
    actual, real_unknown = remove_precision_unknown(actual, d.days, d.A['codes'])
    if real_unknown:
        raise ValueError('FC baseline has indistinguishable opening and stop: ' + str(real_unknown))
    rows, original_outside = eligible_rows(reg, d.pool, d.A['close'], d.days)
    kinds = sorted({e[5] for row in actual for e in row})
    rules = replace(nl_rules(d, 6), gross_cost=True, trail_next_open=True)
    rules = replace(rules, intraday_kinds=tuple(sorted(set(rules.intraday_kinds) | set(kinds))))
    del d.fp, d.fwd, d.raw
    for k in ('pr21', 'pr63', 'pr126', 'rank_pool', 'stack', 'tight'):
        d.A.pop(k, None)
    d.rk = d.rk.astype(np.int32)
    gc.collect()
    px, em = d.base.px(d.A), d.base.ema_inputs(d.A, d.pool, rules)
    start = int(np.searchsorted(d.A['days'], panels.WINDOW[0]))
    end = int(np.searchsorted(d.A['days'], panels.WINDOW[1], side='right'))
    real = summary(d, actual, rules, px, em, start, end, audit=True)
    if real['trades_digest'] != ref['results']['FC1']['trades_digest']:
        raise AssertionError('FC1 trades differ')
    rng, draws, sample = np.random.default_rng(SEED), [], []
    for draw in range(DRAWS):
        random_signals, shortages, choices = random_book(rows, d.A['close'], len(d.days), rng)
        random_open, random_counts = dg.next_open(random_signals, d.A['open'], d.A['low'], d.days)
        random_open, unknown = remove_precision_unknown(random_open, d.days, d.A['codes'])
        item = summary(d, random_open, rules, px, em, start, end)
        item.update(candidate_counts=random_counts, shortages=[[d.days[i], want, got] for i, want, got in shortages],
                    precision_unknown=unknown)
        draws.append(item)
        if draw == 0:
            sample = [{'signal_day': d.days[i], 'codes': [str(d.A['codes'][j]) for j in selected]}
                      for i, selected in choices[:6]]
        if (draw + 1) % 10 == 0:
            print('draw', draw + 1, flush=True)
    out = {'dataset_digest': ref['dataset_digest'], 'fc_sha256': sha(path),
           'system_sha256': sha(Path(system.__file__)), 'script_sha256': sha(Path(__file__)),
           'seed': SEED, 'draws': DRAWS, 'original_outside_signal_pool': int(original_outside),
           'real_precision_unknown': real_unknown, 'first_draw_sample': sample, 'real': real, 'random': draws}
    target = root / 'strong_continue_fe.json'
    with target.open('w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
        f.write('\n')
    print('wrote', target, flush=True)


if __name__ == '__main__':
    main()
