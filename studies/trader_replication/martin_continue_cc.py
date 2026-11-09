"""CC: rerun U1 open timing after eliminating same-batch future stops."""
from dataclasses import replace
import gc
import hashlib
import json
import os
from pathlib import Path
import sys
import types

import numpy as np

from . import panels, ticket_t4, watchlist
from .martin_continue_a import required_fields
from .martin_continue_ah import delayed_list
from .martin_continue_aj import fixed_six
from .martin_continue_bq import _ROLL_MEAN, activity_ranks, chunked_roll_mean
from . import martin_continue_bz as bz
from .martin_continue_bz import run
from .martin_continue_ca import books
from .martin_strong import Data
from .martin_strong_scan import active, f1_rules


def previous_engine(path, expected_hash):
    """Recover the exact previously pinned engine; reject any other source."""
    source = path.read_text()
    source = source.replace(
        'day still count). Same-day stops of new intraday entries run only after all intraday entries have been admitted;\n'
        'daily bars cannot establish the ordering of fills across different names. Close entries come after the day\'s\n'
        'management, on the equity at the close. The placebo keeps each entry\'s fill time: an intraday\n',
        "day still count); close entries come after the day's management, on the equity at the close.  The placebo keeps each entry's fill time: an intraday\n")
    source = source.replace('        day_stops = []\n', '', 1)
    source = source.replace("            if len(e) > 6 and e[6] is not None and not early:\n"
                            "                raise ValueError('same-day stop requires a declared or identifiable intraday entry')\n", '', 1)
    source = source.replace(
        "            if len(e) > 6 and e[6] is not None and j in pos and not had:\n"
        "                day_stops.append((j, e[6]))\n"
        "        for j, price in day_stops:\n            close_part(pos[j], pos[j].size, price, d, 'stop_day0')\n",
        "            if len(e) > 6 and e[6] is not None and j in pos and not had:     # intraday entry stopped the same day\n"
        "                close_part(pos[j], pos[j].size, e[6], d, 'stop_day0')\n")
    if hashlib.sha256(source.encode()).hexdigest() != expected_hash:
        raise ValueError('reconstructed old engine does not match the old report pin')
    name = 'studies.trader_replication._cc_previous_engine'
    module = types.ModuleType(name)
    sys.modules[name] = module
    exec(compile(source, str(path), 'exec'), module.__dict__)
    return module


def main():
    if os.environ.get('TRADER_DATA_MODE') != 'frozen' or os.environ.get('TRADER_DATA_TAG') != 'trader-data-v1':
        raise ValueError('explicitly select the registered frozen v1 dataset')
    root = Path(__file__).resolve().parents[2]
    old = ticket_t4.ranks
    try:
        ticket_t4.ranks = activity_ranks
        D = Data()
    finally:
        ticket_t4.ranks = old
    pin = json.loads((root / 'studies/trader_replication/DATA_PIN.json').read_text())['trader-data-v1']['us']
    if D.A['digest'] != pin:
        raise ValueError('dataset digest differs from registered v1')
    del D.fp, D.fwd, D.raw
    for key in ('pr21', 'pr63', 'pr126', 'rank_pool', 'stack', 'tight'):
        D.A.pop(key, None)
    D.rk = D.rk.astype(np.int32)
    gc.collect()
    try:
        watchlist.roll_mean = chunked_roll_mean
        fields = required_fields(D)
    finally:
        watchlist.roll_mean = _ROLL_MEAN
    mask = active(D, fields)
    book, _ = books(D, fields, mask, 'H3')
    delayed, counts = delayed_list(D, book)
    del fields, mask
    gc.collect()
    rules = f1_rules(D, 6, (1, 3))
    early_rules = replace(rules, intraday_kinds=tuple(rules.intraday_kinds) + ('list',))
    cases = {'U1': (book, rules), 'AJ1': (fixed_six(book), rules), 'AH1_fixed': (delayed, early_rules),
             'R74_fixed': (D.reg, D.rules)}
    results = {}
    for name, (entries, ru) in cases.items():
        print('account', name, flush=True)
        results[name] = run(D, entries, ru)
    previous_ah = json.loads((root / 'studies/trader_replication/reports/gap_review/strong_continue_ah.json').read_text())
    previous_aj = json.loads((root / 'studies/trader_replication/reports/gap_review/strong_continue_aj.json').read_text())
    old_hash = previous_ah['code_sha256']['studies/trader_replication/system.py']
    old_system = bz.system
    try:
        bz.system = previous_engine(root / 'studies/trader_replication/system.py', old_hash)
        print('account AH1_old', flush=True)
        results['AH1_old'] = run(D, delayed, early_rules)
        print('account R74_old', flush=True)
        results['R74_old'] = run(D, D.reg, D.rules)
    finally:
        bz.system = old_system
    if counts != previous_ah['candidate_counts']:
        raise AssertionError('AH candidate counts differ from previous report')
    for name, prior in (('U1', previous_ah['results']['U1']['metrics']), ('AJ1', previous_aj['metrics']),
                        ('AH1_old', previous_ah['results']['AH1']['metrics'])):
        actual = results[name]['metrics']
        for year in ('2024', '2025', '2026'):
            if abs(actual['by_year'][year] - prior['by_year'][year]) > 1e-10:
                raise AssertionError(f'{name} {year} annual return differs from prior report')
            if actual['entries_by_year'][year] != prior['entries_by_year'][year]:
                raise AssertionError(f'{name} {year} entries differ from prior report')
    old_r74 = json.loads((root / 'studies/trader_replication/reports/gap_review/strong_continue_bv_trader-data-v1.json').read_text())['results']['R74']['metrics']
    old_s7 = json.loads((root / 'studies/trader_replication/reports/gap_review/strong_s7.json').read_text())['REG']['by_year']
    for year in ('2024', '2025', '2026'):
        r74 = results['R74_old']['metrics']
        if abs(r74['by_year'][year] - old_s7[year]) > 1e-10 or r74['entries_by_year'][year] != old_r74['entries_by_year'][year]:
            raise AssertionError(f'R74 {year} baseline differs from S7 / BV')
    paths = ('studies/trader_replication/martin_continue_cc.py', 'studies/trader_replication/martin_continue_ca.py',
             'studies/trader_replication/martin_continue_ah.py', 'studies/trader_replication/martin_continue_aj.py',
             'studies/trader_replication/martin_continue_bz.py', 'studies/trader_replication/system.py')
    out = {'dataset_digest': D.A['digest'], 'window': list(panels.WINDOW), 'candidate_counts': counts,
           'results': results, 'old_ah_system_sha256': old_hash,
           'code_sha256': {p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in paths}}
    target = root / 'studies/trader_replication/reports/gap_review/strong_continue_cc.json'
    target.write_text(json.dumps(out, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    print('wrote', target, flush=True)


if __name__ == '__main__':
    main()
