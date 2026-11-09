"""HG: reconstruct HB and trace the fixed H3 path before next-open orders."""
from collections import Counter
import gc
import json
from pathlib import Path
from statistics import mean, median

import numpy as np

from studies import trader_data
from studies.trader_replication import martin_continue_du as du
from studies.trader_replication import martin_continue_ep as ep
from studies.trader_replication import martin_continue_hb as hb
from studies.trader_replication.martin_continue_bv import daily_name_score
from studies.trader_replication.martin_continue_hf import LEDGER, REPORTS, sha
from studies.trader_replication.martin_strong_scan import HOLD, hold_sim, u1_entries


def event(active, held, qualified, selected, core):
    if not (selected <= qualified <= held <= active):
        raise AssertionError('H3 stages are not cumulative')
    return {'active': bool(active), 'held': bool(held), 'qualified': bool(qualified),
            'selected': bool(selected), 'core': bool(core)}


def main():
    hb_path, hf_path = (REPORTS / f'strong_continue_{n}.json' for n in ('hb', 'hf'))
    original, hf = (json.loads(p.read_text()) for p in (hb_path, hf_path))
    ds = trader_data.dataset('us', mode='frozen', version='trader-data-v1')
    if (ds.digest() != original['dataset_digest'] or ds.digest() != hf['dataset_digest'] or
            hf['hb_sha256'] != sha(hb_path) or hf['ledger_sha256'] != sha(LEDGER) or
            original['script_sha256'] != sha(Path(hb.__file__))):
        raise ValueError('HB, HF, ledger or frozen data differs')
    prior_orders = original['orders']
    expected_digest = original['preorders_digest']
    if hb.sha_bytes(prior_orders) != expected_digest:
        raise ValueError('saved HB orders differ from digest')
    targets = hf['results']['lever:hit']['rows']
    del original, hf
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
    score = daily_name_score(fields, mask, HOLD['H3'])
    holding = hold_sim(score, 12, 36)
    book = u1_entries(d, fields, holding, score)
    rebuilt = hb.freeze_orders(d.days, d.A['codes'], book, d.A['close'])
    if hb.sha_bytes(rebuilt) != expected_digest or rebuilt != prior_orders:
        raise AssertionError('reconstructed HB preorders differ')
    del rebuilt, prior_orders, score
    gc.collect()
    cols = {str(code): j for j, code in enumerate(d.A['codes'])}
    wanted = {}
    for row in targets:
        for day in d.days:
            if row['window'][0] <= day <= row['window'][1] and day in d.di:
                wanted.setdefault(day, []).append(row)
    per_id = {row['id']: [] for row in targets}
    widths = {}
    for day in range(1, len(d.days) - 1):
        next_day = d.days[day + 1]
        if not '2024-01-02' <= next_day <= '2026-10-16':
            continue
        close, low, previous_high = d.c[day], d.l[day], d.h[day - 1]
        shape = ((fields['lowe9'][day] <= .1) & (close > d.e9[day])) | (
                 (close > previous_high) & (fields['cpos'][day] >= .5))
        extension = np.nan_to_num(fields['ext21'][day], nan=99) <= 8.0
        price = np.isfinite(close) & np.isfinite(low)
        qual = holding[day] & extension & shape & price
        raw_list = [e for e in book[day] if e[2] > 0 and e[5] == 'list']
        if set(np.flatnonzero(qual)) != {e[1] for e in raw_list}:
            raise AssertionError('list shape reconstruction differs on ' + next_day)
        selected = {e[1] for e in sorted(raw_list, key=lambda e: e[0])[:6]}
        core = {e[1] for e in book[day] if e[2] > 0 and e[5] != 'list'}
        if any(e[5] != 'n1' for e in book[day] if e[2] > 0 and e[5] != 'list'):
            raise AssertionError('unexpected core kind')
        if np.any(holding[day] & ~mask[day]):
            raise AssertionError('held H3 name outside active set')
        widths.setdefault(next_day[:4], []).append([int(mask[day].sum()), int(holding[day].sum()),
                                                   int(qual.sum()), len(selected), len(core)])
        for target in wanted.get(next_day, []):
            j = cols[target['code']]
            item = event(mask[day, j], holding[day, j], qual[j], j in selected, j in core)
            item.update(day=next_day, signal_day=d.days[day], shape=bool(shape[j]),
                        extension=bool(extension[j]), valid_price=bool(price[j]))
            per_id[target['id']].append(item)
    output_rows = []
    for target in targets:
        items = per_id[target['id']]
        reached = {k: any(e[k] for e in items) for k in ('active', 'held', 'qualified', 'selected', 'core')}
        if (reached['selected'] or reached['core']) != (target['stage'] != 'no_candidate'):
            raise AssertionError('HF candidate mismatch: ' + target['id'])
        output_rows.append({**target, 'upstream_days': items, 'reached': reached})
    summary = {}
    for label, rows in (('2024_2025', [r for r in output_rows if r['entry_date'] <= '2025-12-31']),
                        ('2026', [r for r in output_rows if r['entry_date'] > '2025-12-31'])):
        summary[label] = {'n': len(rows), **{k: sum(r['reached'][k] for r in rows)
                          for k in ('active', 'held', 'qualified', 'selected', 'core')},
                          'union': sum(r['reached']['selected'] or r['reached']['core'] for r in rows),
                          'filled': sum(r['stage'] == 'filled' for r in rows)}
    width_summary = {year: {key: {'mean': mean(row[i] for row in values),
                                      'median': median(row[i] for row in values)}
                            for i, key in enumerate(('active', 'held', 'qualified', 'selected', 'core'))}
                     for year, values in widths.items()}
    out = {'dataset_digest': ds.digest(), 'hb_sha256': sha(hb_path), 'hf_sha256': sha(hf_path),
           'ledger_sha256': sha(LEDGER), 'script_sha256': sha(Path(__file__)),
           'summary': summary, 'daily_width': width_summary, 'rows': output_rows}
    target = REPORTS / 'strong_continue_hg.json'
    target.write_text(json.dumps(out, ensure_ascii=False, separators=(',', ':'), allow_nan=False) + '\n')
    print('summary', summary, flush=True)
    print('daily width', width_summary, flush=True)
    print('wrote', target, flush=True)


if __name__ == '__main__':
    main()
