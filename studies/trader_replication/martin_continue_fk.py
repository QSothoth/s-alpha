"""FK: decompose actual closed-trade outcomes across fixed FG random accounts."""
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
from studies.trader_replication import martin_continue_fe as fe
from studies.trader_replication import martin_continue_fg as fg
from studies.trader_replication.martin_continue_b_check import digest
from studies.trader_replication.martin_continue_dq import sha
from studies.trader_replication.martin_strong_scan import longs, nl_rules


def trade_stats(trades, year, buy_cost, sell_cost):
    entered = [t for t in trades if t['entry'].startswith(year)]
    closed = [t for t in entered if t['why'] != 'end']
    if any(t['add_tries'] for t in entered):
        raise ValueError('initial-capital R requires no adds')
    returns = np.array([t['ret'] for t in closed], dtype=float)
    wins, losses = returns[returns > 0], returns[returns <= 0]
    risk = np.array([(t['fill'] * (1 + buy_cost) - t['stop'] * (1 - sell_cost)) / t['fill'] for t in closed])
    if len(risk) and np.any(risk <= 0):
        raise ValueError('invalid initial risk')
    net_r = returns / risk
    profits = sorted((float(t['pnl']) for t in closed if t['pnl'] > 0), reverse=True)
    days_win = [t['days'] for t in closed if t['ret'] > 0]
    avg_win = float(np.mean(wins)) if len(wins) else None
    avg_loss = float(np.mean(losses)) if len(losses) else None
    return {'entries': len(entered), 'closed': len(closed), 'open_end': len(entered) - len(closed),
            'win_rate': float(np.mean(returns > 0)) if len(returns) else None,
            'avg_win': avg_win, 'avg_loss': avg_loss,
            'payoff': avg_win / -avg_loss if avg_win is not None and avg_loss is not None and avg_loss < 0 else None,
            'median_stop_width': float(np.median([t['risk_pct'] for t in closed])) if closed else None,
            'winner_days_mean': float(np.mean(days_win)) if days_win else None,
            'winner_days_median': float(np.median(days_win)) if days_win else None,
            'final_r3': float(np.mean(net_r >= 3)) if len(net_r) else None,
            'final_r5': float(np.mean(net_r >= 5)) if len(net_r) else None,
            'positive_pnl_top10_share': sum(profits[:10]) / sum(profits) if profits else None}


def account(d, book, rules, px, em, start, end, audit):
    track = {}
    curve, dates, trades = system.simulate(px, em, rules, book, *panels.WINDOW, audit=audit, track=track)
    m = compare.metrics(curve, dates, trades, book, start, end)
    summary = {'total': m['total'], 'by_year': m['by_year'], 'maxdd': m['maxdd'], 'win': m['win'],
               'payoff': m['payoff'], 'entries_by_year': {y: sum(t['entry'].startswith(y) for t in trades)
                                                          for y in ('2024', '2025', '2026')},
               'close_days_gross_over_one': int(sum(g > 1 + 1e-9 for g in track['gross'])),
               'trades_digest': digest(trades) if audit else None}
    stats = {y: trade_stats(trades, y, rules.buy_cost, rules.sell_cost) for y in ('2024', '2025', '2026')}
    return summary, stats


def quantiles(real, random):
    out = {}
    for year in ('2024', '2025', '2026'):
        out[year] = {}
        for key, value in real[year].items():
            vals = [x[year][key] for x in random if x[year][key] is not None]
            out[year][key] = {'real': value, 'known': len(vals),
                              'p10': float(np.percentile(vals, 10)) if vals else None,
                              'median': float(np.median(vals)) if vals else None,
                              'p90': float(np.percentile(vals, 90)) if vals else None}
    return out


def main():
    root = du.REPORTS
    fg_path, fc_path = root / 'strong_continue_fg.json', root / 'strong_continue_fc.json'
    ref, ref_fc = json.loads(fg_path.read_text()), json.loads(fc_path.read_text())
    if (ref['script_sha256'] != sha(Path(fg.__file__)) or ref_fc['script_sha256'] != sha(Path(fc.__file__)) or
            ref['system_sha256'] != sha(Path(system.__file__)) or ref['fc_sha256'] != sha(fc_path)):
        raise ValueError('FG / FC source differs')
    dataset = trader_data.dataset('us', mode='frozen', version='trader-data-v1')
    if dataset.digest() != ref['dataset_digest']:
        raise ValueError('dataset differs')
    d = du.make_data(dataset)
    reg = [[((1.0,) + (e[0] if isinstance(e[0], tuple) else (e[0],)),) + tuple(e[1:6])
            for e in row] for row in longs(d.reg)]
    actual, counts = dg.next_open(reg, d.A['open'], d.A['low'], d.days)
    if counts != ref_fc['candidates']:
        raise AssertionError('FC candidate counts differ')
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
    pool_diff = int(np.count_nonzero(d.pool != long_pool))
    if pool_diff != ref['pool_difference_stock_days']:
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
    real, real_stats = account(d, actual, rules, px, em, start, end, audit=True)
    if real != ref['real']:
        raise AssertionError('FG real account differs')
    rng, random_stats = np.random.default_rng(fg.SEED), []
    for draw in range(fg.DRAWS):
        signals, _ = fg.random_book(rows, len(d.days), rng)
        book, counts = dg.next_open(signals, d.A['open'], d.A['low'], d.days)
        book, unknown = fe.remove_precision_unknown(book, d.days, d.A['codes'])
        result, stats = account(d, book, rules, px, em, start, end, audit=False)
        expected = ref['random'][draw]
        if counts != expected['candidate_counts'] or unknown != expected['precision_unknown']:
            raise AssertionError('FG order stream differs ' + str(draw + 1))
        if any(result[k] != expected[k] for k in result):
            raise AssertionError('FG account differs ' + str(draw + 1))
        random_stats.append(stats)
        if (draw + 1) % 10 == 0:
            print('draw', draw + 1, flush=True)
    out = {'dataset_digest': ref['dataset_digest'], 'fg_sha256': sha(fg_path),
           'script_sha256': sha(Path(__file__)), 'system_sha256': sha(Path(system.__file__)),
           'seed': fg.SEED, 'draws': fg.DRAWS, 'real': real_stats, 'random': random_stats,
           'quantiles': quantiles(real_stats, random_stats)}
    target = root / 'strong_continue_fk.json'
    with target.open('w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
        f.write('\n')
    print('wrote', target, flush=True)


if __name__ == '__main__':
    main()
