"""HM: retain complementary leaders and give cash accounts room for winners."""
from collections import defaultdict
from dataclasses import replace
import gc
import json
from pathlib import Path

from studies import trader_data
from studies.trader_replication import preopen, system
from studies.trader_replication import martin_continue_du as du
from studies.trader_replication import martin_continue_hc as hc
from studies.trader_replication import martin_continue_hd as hd
from studies.trader_replication import martin_continue_hh as hh
from studies.trader_replication import martin_continue_hj as hj
from studies.trader_replication import martin_continue_hl as hl
from studies.trader_replication.martin_continue_cr import json_default
from studies.trader_replication.martin_continue_dq import sha
from studies.trader_replication.martin_strong_scan import f1_rules, nl_rules


def blend(h3, h4):
    """Interleave the previously selected H4 and H3 trials without duplicating a stock."""
    def groups(rows):
        out = defaultdict(lambda: {'core': [], 'list': []})
        for order in rows:
            out[order['day']]['list' if order['kind'] == 'list' else 'core'].append(order)
        return out
    a, b = groups(h3), groups(h4)
    result = []
    for day in sorted(set(a) | set(b)):
        if a[day]['core'] != b[day]['core']:
            raise AssertionError('core orders differ on ' + day)
        result.extend(b[day]['core'])
        trial, seen = [], {}
        for idx in range(6):
            for source in (b[day]['list'], a[day]['list']):
                if idx >= len(source):
                    continue
                order = source[idx]
                previous = seen.get(order['code'])
                if previous is not None:
                    if {k: v for k, v in order.items() if k != 'priority'} != previous:
                        raise AssertionError('same-day same-stock order fields differ')
                    continue
                seen[order['code']] = {k: v for k, v in order.items() if k != 'priority'}
                if len(trial) < 6:
                    trial.append({**order, 'priority': [2.0, 1.0, float(len(trial))]})
        result.extend(trial)
    return result


def max_trial_count(result):
    trials = [t for t in result['trades'] if t['kind'] == 'list']
    return max((sum(t['entry'] <= p['day'] <= t['exit'] for t in trials)
                for p in result['plans']), default=0)


def main():
    jp, lp = (du.REPORTS / f'strong_continue_{n}.json' for n in ('hj', 'hl'))
    j, l = (json.loads(p.read_text()) for p in (jp, lp))
    ds = trader_data.dataset('us', mode='frozen', version='trader-data-v1')
    if (ds.digest() != j['dataset_digest'] or ds.digest() != l['dataset_digest'] or
            l['hj_sha256'] != sha(jp) or j['source_sha256']['script'] != sha(Path(hj.__file__)) or
            l['script_sha256'] != sha(Path(hl.__file__)) or
            l['system_sha256'] != sha(Path(system.__file__)) or
            l['planner_sha256'] != sha(Path(preopen.__file__))):
        raise ValueError('frozen data or HJ/HL source differs')
    orders, obs = j['orders'], j['observations']
    baseline = {key: {k: value[k] for k in ('metrics', 'fidelity', 'winner_loss_stats')}
                for key, value in l['results'].items()}
    combined = blend(orders['H3'], orders['H4'])
    del j, l
    gc.collect()
    d = du.make_data(ds)
    del d.fp, d.fwd, d.raw
    gc.collect()
    obs['blend'] = hh.observations(d, combined)
    orders['blend'] = combined
    cash = replace(nl_rules(d, 6), gross_cost=True, trail_next_open=True, no_rebuy_day=True)
    cash = replace(cash, intraday_kinds=tuple(sorted(set(cash.intraday_kinds) | {'n1', 'list'})))
    cash11 = replace(cash, max_open=11, max_position=1 / 11)
    cash3 = replace(cash, max_open_by_kind={**cash.max_open_by_kind, 'list': 3})
    lever = f1_rules(d, 6, (1, 3))
    lever = replace(lever, intraday_kinds=tuple(lever.intraday_kinds) + ('n1', 'list'),
                    trail_next_open=True, add_next_open=True, no_rebuy_day=True, feedback_prior_close=True)
    results, unknown = {}, {}
    for hit, scenario in ((True, 'hit'), (False, 'nohit')):
        for name in ('H4', 'blend'):
            book, _, unknown[name + ':' + scenario] = hc.make_books(d, orders[name], obs[name], hit)
            for mode, fn in (('low', hc.account), ('fast', hd.account)):
                source = book if mode == 'low' else hd.at_open_proxy(book)[0]
                variants = ([('cash11', cash11), ('cash3', cash3)] if name == 'H4' else
                            [('cashblend', cash), ('leverblend', lever)])
                for label, rules in variants:
                    print(scenario, mode, label, flush=True)
                    result = fn(d, source, rules)
                    if label == 'cash3' and max_trial_count(result) > 3:
                        raise AssertionError('more than three H4 trial holdings')
                    result['winner_loss_stats'] = hl.trade_stats(result['trades'])
                    results[':'.join((mode, label, scenario))] = result
    out = {'dataset_digest': ds.digest(), 'hj_sha256': sha(jp), 'hl_sha256': sha(lp),
           'system_sha256': sha(Path(system.__file__)), 'planner_sha256': sha(Path(preopen.__file__)),
           'script_sha256': sha(Path(__file__)), 'blend_orders': combined, 'baseline': baseline,
           'unknown_low': unknown, 'results': results}
    target = du.REPORTS / 'strong_continue_hm.json'
    target.write_text(json.dumps(out, ensure_ascii=False, separators=(',', ':'), allow_nan=False,
                                 default=json_default) + '\n')
    print('wrote', target, flush=True)


if __name__ == '__main__':
    main()
