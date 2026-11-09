"""HI: replay H3/core cash competition under the preopen reservation model."""
from dataclasses import replace
import gc
import json
from pathlib import Path

from studies import trader_data
from studies.trader_replication import preopen, system
from studies.trader_replication import martin_continue_du as du
from studies.trader_replication import martin_continue_hb as hb
from studies.trader_replication import martin_continue_hc as hc
from studies.trader_replication import martin_continue_hd as hd
from studies.trader_replication import martin_continue_he as he
from studies.trader_replication.martin_continue_cr import json_default
from studies.trader_replication.martin_continue_dq import sha
from studies.trader_replication.martin_strong_scan import nl_rules


def check_one_trial(result):
    trials = [t for t in result['trades'] if t['kind'] == 'list']
    for plan in result['plans']:
        day = plan['day']
        if sum(t['entry'] <= day <= t['exit'] for t in trials) > 1:
            raise AssertionError('more than one trial is open on ' + day)


def main():
    hp, ep, bp = (du.REPORTS / f'strong_continue_{n}.json' for n in ('hc', 'he', 'hb'))
    h, e, b = (json.loads(p.read_text()) for p in (hp, ep, bp))
    ds = trader_data.dataset('us', mode='frozen', version='trader-data-v1')
    if (any(x['dataset_digest'] != ds.digest() for x in (h, e, b)) or
            e['hc_sha256'] != sha(hp) or e['hb_sha256'] != sha(bp) or
            e['system_sha256'] != sha(Path(system.__file__)) or
            e['planner_sha256'] != sha(Path(preopen.__file__)) or
            e['script_sha256'] != sha(Path(he.__file__)) or
            h['script_sha256'] != sha(Path(hc.__file__)) or
            hb.sha_bytes(b['orders']) != b['preorders_digest']):
        raise ValueError('saved data or source does not match')
    reference = {'low': {s: hd.compact_reference(h['results']['cash:' + s]) for s in ('hit', 'nohit')},
                 'close': {s: hd.compact_reference(e['market_close']['cash:' + s]) for s in ('hit', 'nohit')}}
    orders, obs, expected_unknown = b['orders'], b['observations'], h['unknown_low']
    del h, e, b
    gc.collect()
    d = du.make_data(ds)
    del d.fp, d.fwd, d.raw
    gc.collect()
    rules = replace(nl_rules(d, 6), gross_cost=True, trail_next_open=True, no_rebuy_day=True)
    rules = replace(rules, intraday_kinds=tuple(sorted(set(rules.intraday_kinds) | {'n1', 'list'})))
    one = replace(rules, max_open_by_kind={**rules.max_open_by_kind, 'list': 1})
    results = {}
    for hit, scenario in ((True, 'hit'), (False, 'nohit')):
        book, _, unknown = hc.make_books(d, orders, obs, hit)
        if unknown != expected_unknown[scenario]:
            raise AssertionError('prior precision list differs')
        core = [[x for x in row if x[5] == 'n1'] for row in book]
        for mode, account in (('low', hc.account), ('close', he.account)):
            source = book if mode == 'low' else he.at_close_proxy(d, book)[0]
            core_source = core if mode == 'low' else he.at_close_proxy(d, core)[0]
            for name, entries, chosen_rules in (('core', core_source, rules), ('mixed', source, rules),
                                                ('one', source, one)):
                print(scenario, mode, name, flush=True)
                result = account(d, entries, chosen_rules)
                if name == 'core' and hd.compact_reference(result) != reference[mode][scenario]:
                    raise AssertionError('cash reference differs: ' + mode + ':' + scenario)
                if name == 'one':
                    check_one_trial(result)
                results[f'{mode}:{scenario}:{name}'] = result
    output = {'dataset_digest': ds.digest(), 'hc_sha256': sha(hp), 'he_sha256': sha(ep), 'hb_sha256': sha(bp),
              'system_sha256': sha(Path(system.__file__)), 'planner_sha256': sha(Path(preopen.__file__)),
              'script_sha256': sha(Path(__file__)), 'results': results}
    target = du.REPORTS / 'strong_continue_hi.json'
    target.write_text(json.dumps(output, ensure_ascii=False, separators=(',', ':'), allow_nan=False,
                                 default=json_default) + '\n')
    print('wrote', target, flush=True)


if __name__ == '__main__':
    main()
