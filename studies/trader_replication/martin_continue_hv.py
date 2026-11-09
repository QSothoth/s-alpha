"""HV: retain winners without fixed-R partial exits."""
from dataclasses import replace
import gc
import json
from pathlib import Path
import statistics
import sys

from studies import trader_data
from studies.trader_replication import preopen, system
from studies.trader_replication import martin_continue_du as du
from studies.trader_replication import martin_continue_hc as hc
from studies.trader_replication import martin_continue_hd as hd
from studies.trader_replication import martin_continue_hn as hn
from studies.trader_replication import martin_continue_hp as hp
from studies.trader_replication import martin_continue_ht as ht
from studies.trader_replication.martin_continue_cr import json_default
from studies.trader_replication.martin_continue_dq import sha
from studies.trader_replication.martin_strong_scan import f1_rules, nl_rules


def paths():
    return {'HN': du.REPORTS / 'strong_continue_hn.json', 'HN_inputs': du.REPORTS / 'strong_continue_hn_inputs.json',
            'HP': du.REPORTS / 'strong_continue_hp.json', 'HP_inputs': du.REPORTS / 'strong_continue_hp_inputs.json',
            'HT': du.REPORTS / 'strong_continue_ht.json', 'HT_inputs': du.REPORTS / 'strong_continue_ht_inputs.json',
            'system': Path(system.__file__), 'planner': Path(preopen.__file__),
            'hn_script': Path(hn.__file__), 'hp_script': Path(hp.__file__),
            'ht_script': Path(ht.__file__), 'script': Path(__file__)}


def without_partial(rules):
    if (rules.trims != (10,) or rules.trail != 'e21' or rules.unit_adr or rules.trail_after_trim or
            rules.trim_signal or rules.trim_signal2 or rules.trim_day or
            any('trims' in override or 'trim_frac' in override for override in rules.management_by_kind.values())):
        raise ValueError('unexpected partial or trailing policy')
    return replace(rules, trims=())


def duration_stats(trades):
    result = {}
    for year in ('2024', '2025', '2026'):
        rows = [t for t in trades if t['entry'].startswith(year) and t['why'] != 'end']
        result[year] = {}
        for label, predicate in (('big30', lambda t: t['ret_invested'] >= .3),
                                 ('big50', lambda t: t['ret_invested'] >= .5),
                                 ('loss', lambda t: t['ret_invested'] < 0)):
            days = [t['days'] for t in rows if predicate(t)]
            result[year][label] = {'n': len(days), 'median_days': statistics.median(days) if days else None}
    return result


def prepare():
    p = paths()
    ds = trader_data.dataset('us', mode='frozen', version='trader-data-v1')
    payload = {'dataset_digest': ds.digest(), 'source_sha256': {k: sha(v) for k, v in p.items()}, 'cases': {}}
    specs = [('cash_h4', 'HN', 'HN_inputs', 'hn_script', 'cash6', True),
             ('lever_ht', 'HT', 'HT_inputs', 'ht_script', 'lever', False),
             ('lever_hp', 'HP', 'HP_inputs', 'hp_script', 'lever', False)]
    for label, report_key, input_key, script_key, account, is_hn in specs:
        report = json.loads(p[report_key].read_text())
        if (report['dataset_digest'] != ds.digest() or report['inputs_sha256'] != sha(p[input_key]) or
                report['source_sha256']['system'] != sha(p['system']) or
                report['source_sha256']['planner'] != sha(p['planner']) or
                report['source_sha256']['script'] != sha(p[script_key])):
            raise ValueError('reference differs: ' + label)
        references = {s: hd.compact_reference(report['results'][f'low:{account}:both:{s}' if is_hn else f'{account}:{s}'])
                      for s in ('hit', 'nohit')}
        if report_key == 'HT':
            orders, observations = report['orders'], report['observations']
        else:
            orders = observations = None
        del report
        gc.collect()
        if report_key != 'HT':
            source = json.loads(p[input_key].read_text())
            if is_hn:
                orders, observations = source['orders'], source['observations']
            else:
                orders = source['blend_orders']
            del source
            gc.collect()
        payload['cases'][label] = {'orders': orders, 'observations': observations, 'references': references}
    target = du.REPORTS / 'strong_continue_hv_inputs.json'
    with target.open('w', encoding='utf-8') as fh:
        json.dump(payload, fh, ensure_ascii=False, separators=(',', ':'), allow_nan=False, default=json_default)
        fh.write('\n')
    print('prepared', target, flush=True)


def run():
    ip = du.REPORTS / 'strong_continue_hv_inputs.json'
    data = json.loads(ip.read_text())
    ds = trader_data.dataset('us', mode='frozen', version='trader-data-v1')
    p = paths()
    if data['dataset_digest'] != ds.digest() or any(data['source_sha256'][k] != sha(v) for k, v in p.items()):
        raise ValueError('prepared inputs differ')
    cases = data['cases']
    del data
    gc.collect()
    d = du.make_data(ds)
    del d.fp, d.fwd, d.raw
    gc.collect()
    from studies.trader_replication import martin_continue_hh as hh
    cash = replace(nl_rules(d, 6), gross_cost=True, trail_next_open=True, no_rebuy_day=True)
    cash = replace(cash, intraday_kinds=tuple(sorted(set(cash.intraday_kinds) | {'n1', 'list'})))
    lever = f1_rules(d, 6, (1, 3))
    lever = replace(lever, intraday_kinds=tuple(lever.intraday_kinds) + ('n1', 'list'),
                    trail_next_open=True, add_next_open=True, no_rebuy_day=True, feedback_prior_close=True)
    fixed, results = {'n1': .025, 'list': .025}, {}
    for label, rules in (('cash_h4', cash), ('lever_ht', lever), ('lever_hp', lever)):
        src = cases[label]
        observations = src['observations'] if src['observations'] is not None else hh.observations(d, src['orders'])
        candidate_rules = without_partial(rules)
        for hit, scenario in ((True, 'hit'), (False, 'nohit')):
            book, _, _ = hc.make_books(d, src['orders'], observations, hit)
            print(label, scenario, 'reference', flush=True)
            baseline = hn.account(d, book, rules, fixed, hit)
            if hd.compact_reference(baseline) != src['references'][scenario]:
                raise AssertionError('baseline differs: ' + label + ':' + scenario)
            print(label, scenario, 'no partial', flush=True)
            result = hn.account(d, book, candidate_rules, fixed, hit)
            if any(e['action'] == 'trim' for t in result['trades'] for e in t['executions']):
                raise AssertionError('unexpected fixed partial')
            result['duration_stats'] = duration_stats(result['trades'])
            results[label + ':' + scenario] = result
    out = {'dataset_digest': ds.digest(), 'inputs_sha256': sha(ip),
           'source_sha256': {k: sha(v) for k, v in p.items()}, 'results': results}
    target = du.REPORTS / 'strong_continue_hv.json'
    with target.open('w', encoding='utf-8') as fh:
        json.dump(out, fh, ensure_ascii=False, separators=(',', ':'), allow_nan=False, default=json_default)
        fh.write('\n')
    print('wrote', target, flush=True)


if __name__ == '__main__':
    if sys.argv[1:] == ['prepare']:
        prepare()
    elif sys.argv[1:] == ['run']:
        run()
    else:
        raise SystemExit('expected prepare or run')
