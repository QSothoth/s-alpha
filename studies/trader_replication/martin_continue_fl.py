"""FL: decompose winner price opportunity and realized capture for fixed FG accounts."""
from dataclasses import replace
import gc
import json
from pathlib import Path

import numpy as np
from studies import trader_data
from studies.trader_replication import compare, panels, system
from studies.trader_replication import martin_continue_dg as dg
from studies.trader_replication import martin_continue_du as du
from studies.trader_replication import martin_continue_fe as fe
from studies.trader_replication import martin_continue_fg as fg
from studies.trader_replication import martin_continue_fk as fk
from studies.trader_replication.martin_continue_b_check import digest
from studies.trader_replication.martin_continue_dq import sha
from studies.trader_replication.martin_strong_scan import longs, nl_rules


def winner_capture(trade, high, start, end, buy_cost, sell_cost):
    """Use only highs before the exit day, plus actual executed sale prices."""
    if trade['add_tries']:
        raise ValueError('capture assumes no adds')
    prior_highs = high[start:end]
    sales = [e['price'] for e in trade['executions'] if e['action'] not in ('entry', 'add')]
    if (not sales or any(not np.isfinite(x) or x <= 0 for x in sales) or
            np.any(~np.isfinite(prior_highs)) or np.any(prior_highs <= 0)):
        return None
    peak = max(max(sales), float(np.max(prior_highs)) if len(prior_highs) else 0.)
    upper = (peak * (1 - sell_cost) - trade['fill'] * (1 + buy_cost)) / trade['fill']
    if upper <= 0 or trade['ret'] <= 0:
        raise ValueError('winner has invalid net upper bound')
    capture = trade['ret'] / upper
    if capture > 1 + 1e-8:
        raise ValueError('realized gain exceeds observed price bound')
    return {'upper': float(upper), 'realized': float(trade['ret']), 'capture': float(capture),
            'trimmed': any(e['action'] == 'trim' for e in trade['executions'])}


def capture_stats(d, trades, year, rules, codes):
    winners = [t for t in trades if t['entry'].startswith(year) and t['why'] != 'end' and t['ret'] > 0]
    known = []
    for t in winners:
        row = winner_capture(t, d.A['high'][:, codes[t['code']]], d.di[t['entry']], d.di[t['exit']],
                             rules.buy_cost, rules.sell_cost)
        if row is not None:
            known.append(row)
    out = {'winners': len(winners), 'known': len(known), 'unknown': len(winners) - len(known)}
    for key in ('upper', 'realized', 'capture'):
        values = [r[key] for r in known]
        out[key + '_mean'] = float(np.mean(values)) if values else None
        out[key + '_median'] = float(np.median(values)) if values else None
    out['trim_fraction'] = sum(r['trimmed'] for r in known) / len(known) if known else None
    return out


def account(d, book, rules, px, em, start, end, real, codes):
    track = {}
    curve, dates, trades = system.simulate(px, em, rules, book, *panels.WINDOW, audit=True, track=track)
    m = compare.metrics(curve, dates, trades, book, start, end)
    summary = {'total': m['total'], 'by_year': m['by_year'], 'maxdd': m['maxdd'], 'win': m['win'],
               'payoff': m['payoff'], 'entries_by_year': {y: sum(t['entry'].startswith(y) for t in trades)
                                                          for y in ('2024', '2025', '2026')},
               'close_days_gross_over_one': int(sum(g > 1 + 1e-9 for g in track['gross'])),
               'trades_digest': digest(trades) if real else None}
    capture = {y: capture_stats(d, trades, y, rules, codes) for y in ('2024', '2025', '2026')}
    stats = {y: fk.trade_stats(trades, y, rules.buy_cost, rules.sell_cost) for y in ('2024', '2025', '2026')}
    return summary, capture, stats


def main():
    root = du.REPORTS
    fg_path, fk_path = root / 'strong_continue_fg.json', root / 'strong_continue_fk.json'
    ref, decomposition = json.loads(fg_path.read_text()), json.loads(fk_path.read_text())
    if (ref['script_sha256'] != sha(Path(fg.__file__)) or decomposition['script_sha256'] != sha(Path(fk.__file__)) or
            decomposition['fg_sha256'] != sha(fg_path) or ref['system_sha256'] != sha(Path(system.__file__))):
        raise ValueError('FG / FK source differs')
    dataset = trader_data.dataset('us', mode='frozen', version='trader-data-v1')
    if dataset.digest() != ref['dataset_digest']:
        raise ValueError('dataset differs')
    d = du.make_data(dataset)
    reg = [[((1.0,) + (e[0] if isinstance(e[0], tuple) else (e[0],)),) + tuple(e[1:6])
            for e in row] for row in longs(d.reg)]
    actual, counts = dg.next_open(reg, d.A['open'], d.A['low'], d.days)
    actual, unknown = fe.remove_precision_unknown(actual, d.days, d.A['codes'])
    if unknown:
        raise ValueError('FC precision unknown')
    for name in ('fp', 'fwd', 'raw', 'o', 'h', 'l', 'c', 't', 'adr', 'to20', 'U', 'rk'):
        if hasattr(d, name):
            delattr(d, name)
    gc.collect()
    trace = {}
    cfg = {k: v for k, v in d.cfg.items() if k != 'short'}
    _, _, mask, long_pool = d.base.build(d.A, cfg, trace)
    if int(np.count_nonzero(d.pool != long_pool)) != ref['pool_difference_stock_days']:
        raise AssertionError('FG pool differs')
    rows = fg.candidate_rows(reg, trace['filtered'], trace['capped'], d.days)
    width = {'signal_days': len(rows), 'over_cap_days': sum(len(c) > n for _, c, n in rows),
             'all_fit_days': sum(len(c) == n for _, c, n in rows),
             'candidates': sum(len(c) for _, c, _ in rows), 'selected': sum(n for _, _, n in rows)}
    if width != ref['width']:
        raise AssertionError('FG candidate widths differ')
    del mask, long_pool, trace
    for key in ('pr21', 'pr63', 'pr126', 'rank_pool', 'stack', 'tight'):
        d.A.pop(key, None)
    gc.collect()
    kinds = sorted({e[5] for row in actual for e in row})
    rules = replace(nl_rules(d, 6), gross_cost=True, trail_next_open=True)
    rules = replace(rules, intraday_kinds=tuple(sorted(set(rules.intraday_kinds) | set(kinds))))
    px, em = d.base.px(d.A), d.base.ema_inputs(d.A, d.pool, rules)
    start = int(np.searchsorted(d.A['days'], panels.WINDOW[0]))
    end = int(np.searchsorted(d.A['days'], panels.WINDOW[1], side='right'))
    codes = {str(code): j for j, code in enumerate(d.A['codes'])}
    real, real_capture, real_stats = account(d, actual, rules, px, em, start, end, True, codes)
    if real != ref['real'] or real_stats != decomposition['real']:
        raise AssertionError('FG / FK real account differs')
    rng, random_capture = np.random.default_rng(fg.SEED), []
    for draw in range(fg.DRAWS):
        signals, _ = fg.random_book(rows, len(d.days), rng)
        book, counts = dg.next_open(signals, d.A['open'], d.A['low'], d.days)
        book, unknown = fe.remove_precision_unknown(book, d.days, d.A['codes'])
        result, capture, stats = account(d, book, rules, px, em, start, end, False, codes)
        expected = ref['random'][draw]
        if counts != expected['candidate_counts'] or unknown != expected['precision_unknown']:
            raise AssertionError('FG order stream differs ' + str(draw + 1))
        if any(result[k] != expected[k] for k in result) or stats != decomposition['random'][draw]:
            raise AssertionError('FG / FK account differs ' + str(draw + 1))
        random_capture.append(capture)
        if (draw + 1) % 10 == 0:
            print('draw', draw + 1, flush=True)
    out = {'dataset_digest': ref['dataset_digest'], 'fg_sha256': sha(fg_path), 'fk_sha256': sha(fk_path),
           'script_sha256': sha(Path(__file__)), 'system_sha256': sha(Path(system.__file__)),
           'seed': fg.SEED, 'draws': fg.DRAWS, 'real': real_capture, 'random': random_capture,
           'quantiles': fk.quantiles(real_capture, random_capture)}
    target = root / 'strong_continue_fl.json'
    with target.open('w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
        f.write('\n')
    print('wrote', target, flush=True)


if __name__ == '__main__':
    main()
