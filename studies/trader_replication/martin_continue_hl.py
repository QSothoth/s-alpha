"""HL: compare big-winner capture and early-stop price proxies."""
from dataclasses import replace
import gc
import json
from pathlib import Path
from statistics import median

import numpy as np

from studies import trader_data
from studies.trader_replication import preopen, system
from studies.trader_replication import martin_continue_du as du
from studies.trader_replication import martin_continue_hc as hc
from studies.trader_replication import martin_continue_hd as hd
from studies.trader_replication import martin_continue_hj as hj
from studies.trader_replication.martin_continue_cr import json_default
from studies.trader_replication.martin_continue_dq import sha
from studies.trader_replication.martin_strong_scan import f1_rules, nl_rules


def trade_stats(trades):
    out = {}
    for year in ('2024', '2025', '2026'):
        cohort = [t for t in trades if t['entry'].startswith(year)]
        closed = [t for t in cohort if t['why'] != 'end']
        losses = [t for t in closed if t['ret_invested'] < 0]
        large = [t for t in closed if t['ret_invested'] >= .30]
        out[year] = {'closed': len(closed), 'open_at_end': len(cohort) - len(closed),
                     'wins': sum(t['ret_invested'] > 0 for t in closed),
                     'return_30': len(large), 'return_30_names': len({t['code'] for t in large}),
                     'return_50': sum(t['ret_invested'] >= .50 for t in closed),
                     'return_50_names': len({t['code'] for t in closed if t['ret_invested'] >= .50}),
                     'r5': sum(t['r'] >= 5 for t in closed), 'r10': sum(t['r'] >= 10 for t in closed),
                     'loss_count': len(losses),
                     'loss_median': median([-t['ret_invested'] for t in losses]) if losses else None,
                     'loss_p90': float(np.percentile([-t['ret_invested'] for t in losses], 90)) if losses else None,
                     'loss_max': max([-t['ret_invested'] for t in losses]) if losses else None,
                     'loss_days_median': median(t['days'] for t in losses) if losses else None,
                     'same_day_stop_loss': sum(t['days'] == 0 and t['why'] in ('stop', 'stop_day0', 'gap_stop')
                                               for t in losses)}
    return out


def main():
    jp, cp, dp = (du.REPORTS / f'strong_continue_{n}.json' for n in ('hj', 'hc', 'hd'))
    j, c, d0 = (json.loads(p.read_text()) for p in (jp, cp, dp))
    ds = trader_data.dataset('us', mode='frozen', version='trader-data-v1')
    if (any(x['dataset_digest'] != ds.digest() for x in (j, c, d0)) or
            j['source_sha256']['script'] != sha(Path(hj.__file__)) or
            j['source_sha256']['system'] != sha(Path(system.__file__)) or
            j['source_sha256']['planner'] != sha(Path(preopen.__file__)) or
            d0['hc_sha256'] != sha(cp)):
        raise ValueError('reference data or source differs')
    reference = {'low': {n: hd.compact_reference(c['results'][n]) for n in
                         ('cash:hit', 'cash:nohit', 'lever:hit', 'lever:nohit')},
                 'fast': {n: hd.compact_reference(d0['same_open'][n]) for n in
                          ('cash:hit', 'cash:nohit', 'lever:hit', 'lever:nohit')}}
    orders, observations = j['orders'], j['observations']
    del j, c, d0
    gc.collect()
    d = du.make_data(ds)
    del d.fp, d.fwd, d.raw
    gc.collect()
    cash = replace(nl_rules(d, 6), gross_cost=True, trail_next_open=True, no_rebuy_day=True)
    cash = replace(cash, intraday_kinds=tuple(sorted(set(cash.intraday_kinds) | {'n1', 'list'})))
    lever = f1_rules(d, 6, (1, 3))
    lever = replace(lever, intraday_kinds=tuple(lever.intraday_kinds) + ('n1', 'list'),
                    trail_next_open=True, add_next_open=True, no_rebuy_day=True, feedback_prior_close=True)
    results = {}
    for hit, scenario in ((True, 'hit'), (False, 'nohit')):
        for variant in ('H3', 'H4'):
            book, _, _ = hc.make_books(d, orders[variant], observations[variant], hit)
            for mode, fn in (('low', hc.account), ('fast', hd.account)):
                source = book if mode == 'low' else hd.at_open_proxy(book)[0]
                specs = [('cash', variant, source, cash), ('lever', variant, source, lever)]
                if variant == 'H3':
                    specs.insert(0, ('cash', 'core', [[e for e in row if e[5] == 'n1'] for row in source], cash))
                for name, label, entries, rules in specs:
                    print(scenario, mode, name, label, flush=True)
                    result = fn(d, entries, rules)
                    if (name == 'cash' and label == 'core') or (name == 'lever' and label == 'H3'):
                        if hd.compact_reference(result) != reference[mode][name + ':' + scenario]:
                            raise AssertionError('reference account differs: ' + mode + ':' + name + ':' + scenario)
                    result['winner_loss_stats'] = trade_stats(result['trades'])
                    results[':'.join((mode, name, label, scenario))] = result
    out = {'dataset_digest': ds.digest(), 'hj_sha256': sha(jp), 'hc_sha256': sha(cp), 'hd_sha256': sha(dp),
           'system_sha256': sha(Path(system.__file__)), 'planner_sha256': sha(Path(preopen.__file__)),
           'script_sha256': sha(Path(__file__)), 'results': results}
    target = du.REPORTS / 'strong_continue_hl.json'
    target.write_text(json.dumps(out, ensure_ascii=False, separators=(',', ':'), allow_nan=False,
                                 default=json_default) + '\n')
    print('wrote', target, flush=True)


if __name__ == '__main__':
    main()
