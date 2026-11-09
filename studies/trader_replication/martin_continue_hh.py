"""HH: refresh the original H3 at the last close before submitting orders."""
from dataclasses import replace
import gc
import json
from pathlib import Path
import sys

import numpy as np

from studies import trader_data
from studies.trader_replication import preopen, system
from studies.trader_replication import martin_continue_du as du
from studies.trader_replication import martin_continue_ea as ea
from studies.trader_replication import martin_continue_ep as ep
from studies.trader_replication import martin_continue_hb as hb
from studies.trader_replication import martin_continue_hc as hc
from studies.trader_replication import martin_continue_hd as hd
from studies.trader_replication import martin_continue_he as he
from studies.trader_replication.martin_continue_bv import daily_name_score
from studies.trader_replication.martin_continue_cr import json_default
from studies.trader_replication.martin_continue_dq import sha
from studies.trader_replication.martin_strong_scan import HOLD, f1_rules, hold_sim, u1_entries

CUT = '2025-09-30'


class AsOfDataset(ea.LimitedDataset):
    def actions(self):
        return {code: [a for a in actions if a[0] <= self.cutoff]
                for code, actions in self.base.actions().items()}


def latest_for_signal(values, empty):
    """Row d+1 of the original prior-close feature is available after close d."""
    values[:-1] = values[1:]
    values[-1] = empty
    return values


def construct(dataset):
    d = du.make_data(dataset)
    fields, mask, unused = du.compute_fields(d)
    del unused
    gc.collect()
    events, eligible, _ = ep.causal_inputs(dataset, d, list(map(str, d.A['codes'])))
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
    score = daily_name_score(fields, mask, HOLD['H3'])
    holding = hold_sim(score, 12, 36)
    original = u1_entries(d, fields, holding, score)
    latest = u1_entries(d, fields, latest_for_signal(holding, False), latest_for_signal(score, np.nan))
    previous_orders = hb.freeze_orders(d.days, d.A['codes'], original, d.A['close'])
    next_orders = hb.freeze_orders(d.days, d.A['codes'], latest, d.A['close'])
    if [r for r in previous_orders if r['kind'] == 'n1'] != [r for r in next_orders if r['kind'] == 'n1']:
        raise AssertionError('core orders changed')
    del original, latest, fields, mask, score, holding
    gc.collect()
    return d, previous_orders, next_orders


def observations(d, orders):
    codes = {str(c): j for j, c in enumerate(d.A['codes'])}
    result = []
    for order in orders:
        i, j = d.di[order['day']], codes[order['code']]
        result.append({'day': order['day'], 'code': order['code'], 'kind': order['kind'],
                       **hb.observe(order, d.A['open'][i, j], d.A['low'][i, j])})
    return result


def full(ds):
    hb_path, he_path = (du.REPORTS / f'strong_continue_{x}.json' for x in ('hb', 'he'))
    original, reference = (json.loads(p.read_text()) for p in (hb_path, he_path))
    if (ds.digest() != original['dataset_digest'] or ds.digest() != reference['dataset_digest'] or
            reference['hb_sha256'] != sha(hb_path) or reference['script_sha256'] != sha(Path(he.__file__)) or
            reference['system_sha256'] != sha(Path(system.__file__)) or
            reference['planner_sha256'] != sha(Path(preopen.__file__))):
        raise ValueError('original input or engine differs')
    expected = {s: hd.compact_reference(reference['market_close']['lever:' + s]) for s in ('hit', 'nohit')}
    expected_orders, old_observations = original['orders'], original['observations']
    digest = original['preorders_digest']
    del original, reference
    gc.collect()
    d, prev, candidate = construct(ds)
    if prev != expected_orders or hb.sha_bytes(prev) != digest:
        raise AssertionError('full HB orders differ')
    if observations(d, prev) != old_observations:
        raise AssertionError('HB price observations differ')
    obs = observations(d, candidate)
    del prev, expected_orders
    gc.collect()
    rules = f1_rules(d, 6, (1, 3))
    rules = replace(rules, intraday_kinds=tuple(rules.intraday_kinds) + ('n1', 'list'),
                    trail_next_open=True, add_next_open=True, no_rebuy_day=True, feedback_prior_close=True)
    results, precision = {}, {}
    for hit, scenario in ((True, 'hit'), (False, 'nohit')):
        print('account', scenario, 'original', flush=True)
        old_book, _, _ = hc.make_books(d, json.loads(hb_path.read_text())['orders'], old_observations, hit)
        old_book, _ = he.at_close_proxy(d, old_book)
        original_result = he.account(d, old_book, rules)
        if hd.compact_reference(original_result) != expected[scenario]:
            raise AssertionError('HE account differs: ' + scenario)
        del old_book, original_result
        gc.collect()
        print('account', scenario, 'latest H3', flush=True)
        book, _, precision[scenario] = hc.make_books(d, candidate, obs, hit)
        book, _ = he.at_close_proxy(d, book)
        results[scenario] = he.account(d, book, rules)
        del book
        gc.collect()
    out = {'dataset_digest': ds.digest(), 'hb_sha256': sha(hb_path), 'he_sha256': sha(he_path),
           'system_sha256': sha(Path(system.__file__)), 'planner_sha256': sha(Path(preopen.__file__)),
           'script_sha256': sha(Path(__file__)), 'orders': candidate, 'observations': obs,
           'unknown_low': precision, 'results': results}
    target = du.REPORTS / 'strong_continue_hh_full.json'
    target.write_text(json.dumps(out, ensure_ascii=False, separators=(',', ':'), allow_nan=False,
                                 default=json_default) + '\n')
    print('wrote', target, flush=True)


def cut(ds):
    full_path = du.REPORTS / 'strong_continue_hh_full.json'
    reference = json.loads(full_path.read_text())
    if reference['dataset_digest'] != ds.digest() or reference['script_sha256'] != sha(Path(__file__)):
        raise ValueError('full reference differs')
    expected = [r for r in reference['orders'] if r['day'] <= CUT]
    del reference
    gc.collect()
    truncated = AsOfDataset(ds, CUT)
    d, _, actual = construct(truncated)
    if d.days[-1] != CUT:
        raise AssertionError('raw data did not end at registered cutoff')
    def identities(rows):
        return [(r['day'], r['code'], r['kind']) for r in rows]
    exact = identities(expected) == identities(actual)
    max_stop_ratio = max((abs(a['stop'] / a['close'] - b['stop'] / b['close'])
                          for a, b in zip(expected, actual)), default=0.) if exact else None
    result = {'cutoff': CUT, 'full_sha256': sha(full_path), 'script_sha256': sha(Path(__file__)),
              'n_full': len(expected), 'n_cut': len(actual), 'same_order_identity_and_sequence': exact,
              'max_stop_over_close_difference': max_stop_ratio,
              'passes': bool(exact and max_stop_ratio is not None and max_stop_ratio <= 1e-6)}
    target = du.REPORTS / 'strong_continue_hh_cut.json'
    target.write_text(json.dumps(result, ensure_ascii=False, separators=(',', ':'), allow_nan=False) + '\n')
    print(result, flush=True)
    if not result['passes']:
        raise AssertionError('latest H3 cutoff mismatch')


if __name__ == '__main__':
    dataset = trader_data.dataset('us', mode='frozen', version='trader-data-v1')
    if sys.argv[1:] == ['full']:
        full(dataset)
    elif sys.argv[1:] == ['cut']:
        cut(dataset)
    else:
        raise SystemExit('expected full or cut')
