"""HJ: full cash and leveraged accounts for two documented selection ideas."""
from dataclasses import replace
import gc
import json
from pathlib import Path
import warnings

import numpy as np

from studies import trader_data
from studies.trader_replication import preopen, system
from studies.trader_replication import martin_continue_ax as ax
from studies.trader_replication import martin_continue_ca as ca
from studies.trader_replication import martin_continue_du as du
from studies.trader_replication import martin_continue_ep as ep
from studies.trader_replication import martin_continue_hb as hb
from studies.trader_replication import martin_continue_hc as hc
from studies.trader_replication import martin_continue_hd as hd
from studies.trader_replication import martin_continue_he as he
from studies.trader_replication import martin_continue_hh as hh
from studies.trader_replication.martin_continue_bv import daily_name_score, daily_pool_book
from studies.trader_replication.martin_continue_cr import json_default
from studies.trader_replication.martin_continue_dq import sha
from studies.trader_replication.martin_list import ema
from studies.trader_replication.martin_strong import roll_ext
from studies.trader_replication.martin_strong_scan import HOLD, f1_rules, hold_sim, merge, nl_rules, sized, u1_entries


def coil_fields_chunked(d, width=64):
    """The existing H4 features, using bounded column batches."""
    nsq = np.empty(d.c.shape, np.float32)
    nr10 = np.empty(d.c.shape, np.float32)
    with warnings.catch_warnings(), np.errstate(all='ignore'):
        warnings.simplefilter('ignore', RuntimeWarning)
        for start in range(0, d.c.shape[1], width):
            sl = slice(start, start + width)
            e21 = ema(d.c[:, sl].astype(float), 21).astype(np.float32)
            nsq[:, sl] = -(np.abs(d.e9[:, sl] / e21 - 1) / d.adr[:, sl])
            hi = roll_ext(d.h[:, sl], 10, np.nanmax)
            lo = roll_ext(d.l[:, sl], 10, np.nanmin)
            nr10[:, sl] = -((hi / lo - 1) / d.adr[:, sl])
    return {'nsq': nsq, 'nr10': nr10}


def freeze(d, fields, mask, group):
    score = daily_name_score(fields, mask, HOLD[group])
    holding = hold_sim(score, 12, 36)
    book = (u1_entries(d, fields, holding, score) if group == 'H3' else
            merge(d.reg, sized(daily_pool_book(d, fields, holding, score), .5)))
    orders = hb.freeze_orders(d.days, d.A['codes'], book, d.A['close'])
    return orders, book


def main():
    hb_path, he_path = (du.REPORTS / f'strong_continue_{n}.json' for n in ('hb', 'he'))
    original, reference = (json.loads(p.read_text()) for p in (hb_path, he_path))
    ds = trader_data.dataset('us', mode='frozen', version='trader-data-v1')
    if (ds.digest() != original['dataset_digest'] or ds.digest() != reference['dataset_digest'] or
            reference['hb_sha256'] != sha(hb_path) or reference['system_sha256'] != sha(Path(system.__file__)) or
            reference['planner_sha256'] != sha(Path(preopen.__file__)) or
            reference['script_sha256'] != sha(Path(he.__file__)) or
            hb.sha_bytes(original['orders']) != original['preorders_digest']):
        raise ValueError('HB, HE, engine or data differs')
    expected = {name: hd.compact_reference(reference['market_close'][name])
                for name in ('cash:hit', 'cash:nohit', 'lever:hit', 'lever:nohit')}
    prior_orders, prior_observations = original['orders'], original['observations']
    del original, reference
    gc.collect()
    d = du.make_data(ds)
    fields, mask, unused = du.compute_fields(d)
    del unused
    gc.collect()
    events, eligible, _ = ep.causal_inputs(ds, d, list(map(str, d.A['codes'])))
    fast = np.empty(events.shape, np.float32)
    for start in range(0, events.shape[1], 64):
        sl = slice(start, start + 64)
        fast[:, sl] = du._ROLL_MEAN(events[:, sl].astype(np.float32), 250)
    fields['fast250'] = fast
    del events, fast
    peer, pot = ep.peer_potential(d, eligible)
    fields['peer_pot'] = peer
    del peer, pot, eligible
    gc.collect()
    h3, book = freeze(d, fields, mask, 'H3')
    if h3 != prior_orders or hh.observations(d, h3) != prior_observations:
        raise AssertionError('original HB reconstruction differs')
    hard, priority, ax_counts = ax.fast_books(d, book)
    fast_orders = hb.freeze_orders(d.days, d.A['codes'], priority, d.A['close'])
    del hard, priority, book
    gc.collect()
    fields.update(coil_fields_chunked(d))
    h4, book = freeze(d, fields, mask, 'H4')
    del fields, mask, book
    gc.collect()
    all_orders = {'H3': h3, 'H4': h4, 'AX2': fast_orders}
    core = [o for o in h3 if o['kind'] == 'n1']
    if any([o for o in book if o['kind'] == 'n1'] != core for book in all_orders.values()):
        raise AssertionError('original core changed')
    all_obs = {name: hh.observations(d, book) for name, book in all_orders.items()}
    cash = replace(nl_rules(d, 6), gross_cost=True, trail_next_open=True, no_rebuy_day=True)
    cash = replace(cash, intraday_kinds=tuple(sorted(set(cash.intraday_kinds) | {'n1', 'list'})))
    lever = f1_rules(d, 6, (1, 3))
    lever = replace(lever, intraday_kinds=tuple(lever.intraday_kinds) + ('n1', 'list'),
                    trail_next_open=True, add_next_open=True, no_rebuy_day=True, feedback_prior_close=True)
    results, unknown = {}, {}
    for hit, scenario in ((True, 'hit'), (False, 'nohit')):
        for name, orders in all_orders.items():
            book, _, unknown[name + ':' + scenario] = hc.make_books(d, orders, all_obs[name], hit)
            book, _ = he.at_close_proxy(d, book)
            if name == 'H3':
                core_book = [[e for e in row if e[5] == 'n1'] for row in book]
                print(scenario, 'cash core', flush=True)
                baseline = he.account(d, core_book, cash)
                if hd.compact_reference(baseline) != expected['cash:' + scenario]:
                    raise AssertionError('original cash account differs')
                results['cash:core:' + scenario] = baseline
            for account_name, rules in (('cash', cash), ('lever', lever)):
                print(scenario, account_name, name, flush=True)
                result = he.account(d, book, rules)
                if name == 'H3' and account_name == 'lever' and hd.compact_reference(result) != expected['lever:' + scenario]:
                    raise AssertionError('original lever account differs')
                results[account_name + ':' + name + ':' + scenario] = result
    paths = {'HB': hb_path, 'HE': he_path, 'system': Path(system.__file__), 'planner': Path(preopen.__file__),
             'AX': Path(ax.__file__), 'CA': Path(ca.__file__), 'script': Path(__file__)}
    out = {'dataset_digest': ds.digest(), 'source_sha256': {k: sha(p) for k, p in paths.items()},
           'orders': all_orders, 'observations': all_obs, 'unknown_low': unknown,
           'ax_candidate_counts': ax_counts, 'results': results}
    target = du.REPORTS / 'strong_continue_hj.json'
    target.write_text(json.dumps(out, ensure_ascii=False, separators=(',', ':'), allow_nan=False,
                                 default=json_default) + '\n')
    print('wrote', target, flush=True)


if __name__ == '__main__':
    main()
