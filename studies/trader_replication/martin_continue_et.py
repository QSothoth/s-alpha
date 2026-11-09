"""ET: compare pre-existing six- and eight-slot unlevered next-open accounts."""
from dataclasses import replace
import gc
import json
from pathlib import Path

import numpy as np
from studies import trader_data
from studies.trader_replication import compare, panels, system
from studies.trader_replication import martin_continue_ah as ah
from studies.trader_replication import martin_continue_du as du
from studies.trader_replication import martin_continue_ef as ef
from studies.trader_replication import martin_continue_ep as ep
from studies.trader_replication import martin_continue_er as er
from studies.trader_replication.martin_continue_bm import describe
from studies.trader_replication.martin_continue_bt import fidelity
from studies.trader_replication.martin_continue_dq import sha
from studies.trader_replication.martin_strong_scan import nl_rules


def account(d, book, rules):
    px = d.base.px(d.A)
    em = d.base.ema_inputs(d.A, d.pool, rules)
    track = {}
    curve, dates, trades = system.simulate(px, em, rules, book, *panels.WINDOW, audit=True, track=track)
    lo = int(np.searchsorted(d.A['days'], panels.WINDOW[0]))
    hi = int(np.searchsorted(d.A['days'], panels.WINDOW[1], side='right'))
    m = compare.metrics(curve, dates, trades, book, lo, hi)
    m['entries_by_year'] = {y: sum(t['entry'].startswith(y) for t in trades) for y in ('2024', '2025', '2026')}
    m['average_close_positions'] = float(np.mean(track['open']))
    m['max_close_positions'] = max(track['open'])
    m['max_close_gross'] = float(max(track['gross']))
    m['close_days_gross_over_one'] = int(sum(g > 1 + 1e-9 for g in track['gross']))
    m['invested_basis'] = describe([t for t in trades if t['why'] != 'end'], 'ret_invested')
    keys = [[t['code'], int(t['side']), t['kind'], t['entry'], t['exit'], t['why']] for t in trades]
    return {'metrics': m, 'fidelity': fidelity(d, trades), 'trade_keys': keys}


def main():
    root = du.REPORTS
    er_path = root / 'strong_continue_er.json'
    ref = json.loads(er_path.read_text())
    if ref['script_sha256'] != sha(Path(er.__file__)):
        raise ValueError('ER source differs')
    digest, expected = ref['dataset_digest'], ref['results']['SAT6_open']
    counts_expected = ref['candidate_counts']['SAT6']
    dataset = trader_data.dataset('us', mode='frozen', version='trader-data-v1')
    if dataset.digest() != digest:
        raise ValueError('dataset differs')
    d = du.make_data(dataset)
    fields, mask, _ = du.compute_fields(d)
    original_eligible = ep.original_eligibility(d)
    replay, old_pot = ep.peer_potential(d, original_eligible)
    for i, day in enumerate(d.days):
        if not np.array_equal(replay[i], fields['peer_pot'][i], equal_nan=True):
            raise AssertionError('original peer_pot mismatch ' + day)
    del replay, old_pot, original_eligible
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
    _, sat = ef.books(d, fields, mask)
    sat_open, counts = ah.delayed_list(d, sat)
    if counts != counts_expected:
        raise AssertionError('ER candidate counts differ')
    del fields, mask, sat
    gc.collect()
    result = {}
    for n in (6, 8):
        rules = nl_rules(d, n)
        if 'list' in rules.intraday_kinds:
            raise ValueError('registered list timing changed')
        rules = replace(rules, intraday_kinds=tuple(rules.intraday_kinds) + ('list',))
        print('account SAT' + str(n), flush=True)
        result['SAT' + str(n)] = account(d, sat_open, rules)
        if result['SAT' + str(n)]['metrics']['max_close_positions'] > n:
            raise AssertionError('max positions exceeded')
    baseline = result['SAT6']
    if baseline['trade_keys'] != expected['trade_keys'] or baseline['fidelity'] != expected['fidelity']:
        raise AssertionError('ER baseline trade keys / fidelity differ')
    for year in ('2024', '2025', '2026'):
        actual, prior = baseline['metrics'], expected['metrics']
        if (abs(actual['by_year'][year] - prior['by_year'][year]) > 1e-10 or
                actual['entries_by_year'][year] != prior['entries_by_year'][year]):
            raise AssertionError('ER baseline metrics differ ' + year)
    out = {'dataset_digest': digest, 'er_sha256': sha(er_path), 'script_sha256': sha(Path(__file__)),
           'candidate_counts': counts, 'results': result,
           'trade_differences': ef.differences(result['SAT6']['trade_keys'], result['SAT8']['trade_keys'])}
    target = root / 'strong_continue_et.json'
    with target.open('w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
        f.write('\n')
    print('wrote', target, flush=True)


if __name__ == '__main__':
    main()
