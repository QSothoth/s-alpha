"""EX: preserve every traced order to reconcile the first negative cash close."""
from dataclasses import replace
import gc
import json
import sys
from pathlib import Path

import numpy as np
from studies import trader_data
from studies.trader_replication import compare, panels, system
from studies.trader_replication import martin_continue_ah as ah
from studies.trader_replication import martin_continue_du as du
from studies.trader_replication import martin_continue_ef as ef
from studies.trader_replication import martin_continue_ep as ep
from studies.trader_replication import martin_continue_er as er
from studies.trader_replication import martin_continue_et as et
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
    et_path = root / 'strong_continue_et.json'
    et_ref = json.loads(et_path.read_text())
    if et_ref['script_sha256'] != sha(Path(et.__file__)):
        raise ValueError('ET source differs')
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
    eu_path = root / 'strong_continue_eu.json'
    eu_ref = json.loads(eu_path.read_text())
    rules = replace(nl_rules(d, 6), gross_cost=True)
    rules = replace(rules, intraday_kinds=tuple(rules.intraday_kinds) + ('list',))
    px, em = d.base.px(d.A), d.base.ema_inputs(d.A, d.pool, rules)
    records, before, track = [], {}, {}
    source = str(Path(system.__file__).resolve())

    def trace(frame, event, arg):
        if event == 'call' and frame.f_code.co_name == 'open_pos' and str(Path(frame.f_code.co_filename).resolve()) == source:
            loc = frame.f_locals
            before[id(frame)] = (float(loc['cash']), float(loc['gross_open'](loc['d'])))
            frame.f_trace_lines = False
            return trace
        if event == 'call':
            return None
        if event == 'return' and id(frame) in before:
            cash_before, gross_before = before.pop(id(frame))
            if arg:
                loc = frame.f_locals
                day, j = loc['d'], loc['j']
                records.append({'day': d.days[day], 'code': str(d.A['codes'][j]),
                                'early': bool(loc['early']), 'batch_equity': float(loc['equity']),
                                'cash_before': cash_before, 'gross_before': gross_before,
                                'cash_after': float(loc['cash']), 'gross_after': float(loc['gross_open'](day)),
                                'notional': float(loc['val']), 'buy_fee': float(loc['val'] * rules.buy_cost)})
        return trace

    try:
        sys.settrace(trace)
        curve, dates, trades = system.simulate(px, em, rules, sat_open, *panels.WINDOW, audit=True, track=track)
    finally:
        sys.settrace(None)
    keys = [[t['code'], int(t['side']), t['kind'], t['entry'], t['exit'], t['why']] for t in trades]
    if keys != eu_ref['results']['SAT6_cash']['trade_keys']:
        raise AssertionError('traced trade keys differ from EU')
    transition = next((r for r in records if r['cash_before'] >= -1e-12 and r['cash_after'] < -1e-12), None)
    closes = [{'day': str(date), 'cash': float(eq * (1 - gross)), 'equity': float(eq), 'gross': float(gross)}
              for date, eq, gross in zip(dates, curve, track['gross']) if gross > 1 + 1e-9]
    same_day = [r for r in records if transition and r['day'] == transition['day']]
    target = root / 'strong_continue_ex.json'
    out = {'dataset_digest': digest, 'eu_sha256': sha(eu_path), 'script_sha256': sha(Path(__file__)),
           'opening_count': len(records), 'transition': transition, 'transition_day_opens': same_day,
           'negative_closes': closes, 'orders': records}
    target.write_text(json.dumps(out, ensure_ascii=False, separators=(',', ':'), allow_nan=False) + '\n')
    print('wrote', target, flush=True)


if __name__ == '__main__':
    main()
