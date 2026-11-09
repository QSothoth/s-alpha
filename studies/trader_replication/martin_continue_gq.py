"""GQ: reconcile monthly-strength opportunity strata with account selections."""
from collections import Counter
import json
from pathlib import Path

import numpy as np
from studies import trader_data
from studies.trader_replication import panels, system
from studies.trader_replication import martin_continue_fj as fj
from studies.trader_replication import martin_continue_gc as gc
from studies.trader_replication import martin_continue_go as go
from studies.trader_replication import martin_continue_gp as gp
from studies.trader_replication.martin_continue_dq import sha
from studies.trader_replication.martin_continue_du import REPORTS

SEED = 20261108


def summary(rows):
    result = {'orders': len(rows), 'status': dict(Counter(r['status'] for r in rows)),
              'leader': sum(r['leader'] is True for r in rows),
              'leader_unknown': sum(r['leader'] is None for r in rows)}
    for metric in ('hit3', 'hit5', 'hit30'):
        values = [r[metric] for r in rows if r[metric] is not None]
        result[metric] = {'known': len(values), 'unknown': len(rows) - len(values),
                          'hits': sum(values), 'rate': sum(values) / len(values) if values else None}
    return result


def sets_for_year(rows, first, second):
    first_keys = {key for key, row in rows.items() if first(row)}
    second_keys = {key for key, row in rows.items() if second(row)}
    return {name: summary([rows[k] for k in keys]) for name, keys in (
        ('shared', first_keys & second_keys), ('original_only', first_keys - second_keys),
        ('gp_only', second_keys - first_keys))}


def main():
    paths = {name: REPORTS / ('strong_continue_' + name + '.json')
             for name in ('fj', 'gc', 'go', 'gp', 'gp_selection')}
    refs = {name: json.loads(path.read_text()) for name, path in paths.items()}
    for name, module in (('fj', fj), ('gc', gc), ('go', go), ('gp', gp), ('gp_selection', gp)):
        if refs[name]['script_sha256'] != sha(Path(module.__file__)):
            raise ValueError('source differs: ' + name)
    if (refs['gc']['fj_sha256'] != sha(paths['fj']) or refs['go']['fj_sha256'] != sha(paths['fj']) or
            refs['go']['gc_sha256'] != sha(paths['gc']) or refs['gp']['go_sha256'] != sha(paths['go']) or
            refs['gp']['selection_sha256'] != sha(paths['gp_selection']) or
            refs['gp']['system_sha256'] != sha(Path(system.__file__))):
        raise ValueError('report provenance differs')
    ds = trader_data.dataset('us', mode='frozen', version='trader-data-v1')
    data_digest = ds.digest()
    if any(ref['dataset_digest'] != data_digest for ref in refs.values()):
        raise ValueError('dataset differs')
    stocks = {s['code'] for s in ds.stocks()}
    calendar = sorted({day for code, day, _ in ds.rows() if code in stocks and day <= panels.WINDOW[1]})
    index = {day: i for i, day in enumerate(calendar)}
    selected = {(r['day'], r['code']) for r in refs['gp_selection']['signals']}
    if len(selected) != refs['gp_selection']['selection']['selected']:
        raise AssertionError('duplicate GP selection')
    source, outcome, features = (refs[n]['rows'] for n in ('fj', 'gc', 'go'))
    if not len(source) == len(outcome) == len(features) == 57269:
        raise AssertionError('candidate count differs')
    rows, entry_rows = {}, {}
    for old, result, feature in zip(source, outcome, features):
        key = old['signal_day'], old['code']
        if key != (result['signal_day'], result['code']) or key != (feature['signal_day'], feature['code']):
            raise AssertionError('candidate keys differ')
        if index.get(old['signal_day']) != old['day_index'] or index.get(old['entry_day']) != old['day_index'] + 1:
            raise AssertionError('calendar differs')
        row = dict(old, leader=feature['leader'], hit30=result['hit30'], gp_selected=key in selected)
        entry = row['entry_day'], row['code']
        if key in rows or entry in entry_rows:
            raise AssertionError('duplicate candidate')
        rows[key], entry_rows[entry] = row, row
    if not selected <= set(rows):
        raise AssertionError('GP selected non-candidate')
    original_by_day = Counter(r['signal_day'] for r in source if r['selected'])
    selected_by_day = Counter(day for day, _ in selected)
    if original_by_day != selected_by_day:
        raise AssertionError('daily original / GP selected count differs')
    output, rng = {}, np.random.default_rng(SEED)
    for year in ('2024', '2025', '2026'):
        year_days = [i for i in range(len(calendar) - 1) if panels.WINDOW[0] <= calendar[i + 1] <= panels.WINDOW[1]
                     and calendar[i + 1].startswith(year)]
        annual = {k: r for k, r in rows.items() if r['year'] == year}
        yearly = {'strata': {}, 'selection': sets_for_year(annual, lambda r: r['selected'],
                                                           lambda r: r['gp_selected']), 'accounts': {}}
        for sample in ('all', 'spaced'):
            yearly['strata'][sample] = {}
            for original, label in ((True, 'original_top4'), (False, 'others')):
                chosen = []
                for row in annual.values():
                    if row['selected'] != original or row['leader'] is None or (sample == 'spaced' and not row['spaced']):
                        continue
                    chosen.append({**row, 'selected': row['leader']})
                matches = {metric: fj.matched(chosen, year_days, metric, False, rng)
                           for metric in ('hit3', 'hit5', 'hit30')}
                yearly['strata'][sample][label] = {'leader': summary([r for r in chosen if r['leader']]),
                                                    'other': summary([r for r in chosen if not r['leader']]),
                                                    'matched': matches}
            for metric in ('hit3', 'hit5', 'hit30'):
                parts = [yearly['strata'][sample][label]['matched'][metric] for label in ('original_top4', 'others')]
                denom = sum(p['top4_weight'] for p in parts)
                numerator = sum((p['difference'] or 0) * p['top4_weight'] for p in parts)
                expected = refs['go']['results'][year]['samples'][sample]['per_preselected']['matched'][metric]
                if denom != expected['leader_weight'] or (denom and abs(numerator / denom - expected['difference']) > 1e-12):
                    raise AssertionError('GO pooled matched result differs')
        for left, right in (('C0', 'GP-C'), ('L0', 'GP-L')):
            keys = []
            for name in (left, right):
                trades = [t for t in refs['gp']['results'][name]['trade_keys']
                          if t[2] == 'n1' and t[3].startswith(year)]
                ks = {(t[3], t[0]) for t in trades}
                if len(ks) != len(trades) or not ks <= set(entry_rows):
                    raise AssertionError('account trade does not join candidate')
                if any(not (entry_rows[k]['selected'] if name == left else entry_rows[k]['gp_selected']) for k in ks):
                    raise AssertionError('trade does not belong to correct selection')
                keys.append(ks)
            entry_year_rows = {k: entry_rows[k] for k in keys[0] | keys[1]}
            yearly['accounts'][left + '_' + right] = sets_for_year(
                entry_year_rows, lambda r: (r['entry_day'], r['code']) in keys[0],
                lambda r: (r['entry_day'], r['code']) in keys[1])
        output[year] = yearly
    result = {'dataset_digest': data_digest, 'script_sha256': sha(Path(__file__)), 'seed': SEED,
              'sources': {name: sha(path) for name, path in paths.items()}, 'candidate_count': len(rows),
              'results': output}
    target = REPORTS / 'strong_continue_gq.json'
    target.write_text(json.dumps(result, ensure_ascii=False, separators=(',', ':'), allow_nan=False) + '\n')
    print('wrote', target, flush=True)


if __name__ == '__main__':
    main()
