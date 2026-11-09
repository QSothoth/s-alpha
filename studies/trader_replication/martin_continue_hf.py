"""HF: trace each located Martin trade through the saved HB and HE accounts."""
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path

import numpy as np

from studies import trader_data
from studies.trader_data import panel
from studies.trader_replication import fidelity, ledger, panels

ROOT = Path(__file__).resolve().parents[2]
REPORTS = ROOT / 'studies/trader_replication/reports/gap_review'
LEDGER = ROOT / 'studies/martin_luk/notes/trades.csv'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def classify(candidates, plans, fills):
    """A submitted or filled event must belong to the very same candidate key."""
    events = []
    for candidate in candidates:
        key = (candidate['day'], candidate['code'], candidate['kind'])
        plan = plans.get(key)
        stage = 'candidate'
        if plan and plan['status'] == 'submitted':
            stage = 'submitted'
            if plan.get('execution') in ('filled', 'gap_moc'):
                if key not in fills:
                    raise AssertionError(f'filled plan lacks matching trade: {key}')
                stage = 'filled'
        if key in fills and stage != 'filled':
            raise AssertionError(f'trade lacks matching submitted plan: {key}')
        events.append({'day': key[0], 'kind': key[2], 'stage': stage,
                       'status': plan.get('status') if plan else 'not_in_plan',
                       'reason': plan.get('reason') if plan else None,
                       'execution': plan.get('execution') if plan else None})
    rank = {'no_candidate': 0, 'candidate': 1, 'submitted': 2, 'filled': 3}
    return max((e['stage'] for e in events), key=rank.get, default='no_candidate'), events


def main():
    hb_path, he_path = (REPORTS / f'strong_continue_{n}.json' for n in ('hb', 'he'))
    hb, he = (json.loads(p.read_text()) for p in (hb_path, he_path))
    ds = trader_data.dataset('us', mode='frozen', version='trader-data-v1')
    if ds.digest() != he['dataset_digest'] or ds.digest() != hb['dataset_digest']:
        raise ValueError('frozen dataset differs')
    if he['hb_sha256'] != sha(hb_path):
        raise ValueError('HB input differs from HE')
    p = panel.build(ds, cache=True, write_cache=False)
    trades = [t for t in ledger.load(LEDGER) if t.side == 'long']
    located, missing = fidelity.locate(trades, p['days'], p['codes'], has=np.isfinite(p['close']))
    located = [row for row in located if row[0].dated and row[0].entry_date >= panels.WINDOW[0]]
    codes, days = p['codes'], p['days']
    code_set = set(map(str, codes))
    missing_rows = [{'id': t.id, 'code': 'US.' + t.ticker, 'entry_date': t.entry_date,
                     'reason': 'code_absent' if 'US.' + t.ticker not in code_set else 'no_bar_in_window'}
                    for t in trades if t.id in missing and t.dated and t.entry_date >= panels.WINDOW[0]]
    overlaps = []
    for i, (t, j, a, b) in enumerate(located):
        for u, k, c, e in located[i + 1:]:
            if j == k and max(a, c) <= min(b, e):
                overlaps.append([t.id, u.id])
    candidates = defaultdict(list)
    for order in hb['orders']:
        candidates[(order['day'], order['code'])].append(order)
    results = {}
    for name, account in he['market_close'].items():
        kinds = {'n1'} if name.startswith('cash:') else {'n1', 'list'}
        plans = {}
        for plan in account['plans']:
            for order in plan['orders']:
                if order['type'] == 'entry':
                    key = plan['day'], order['code'], order['kind']
                    if key in plans:
                        raise AssertionError(f'duplicate planned entry: {key}')
                    plans[key] = order
        fills = {(t['entry'], t['code'], t['kind']) for t in account['trades'] if t['side'] > 0}
        rows = []
        for t, j, a, b in located:
            code = str(codes[j])
            window = [str(day) for day in days[a:b + 1]]
            orders = [o for day in window for o in candidates[(day, code)] if o['kind'] in kinds]
            stage, events = classify(orders, plans, fills)
            hits = [day for day in window if any((day, code, kind) in fills for kind in kinds)]
            if bool(hits) != (stage == 'filled'):
                raise AssertionError(f'candidate funnel and actual fill differ: {name}, {t.id}')
            held_prior = [day for day in window if any(tr['code'] == code and tr['side'] > 0 and
                           tr['entry'] < day <= tr['exit'] for tr in account['trades'])]
            rows.append({'id': t.id, 'code': code, 'entry_date': t.entry_date,
                         'precision': t.precision, 'window': [t.window_lo, t.window_hi],
                         'setup': t.setup, 'stage': stage, 'events': events,
                         'filled_days': hits, 'held_prior_close_days': held_prior})
        summary = {}
        for label, subset in (('2024_2025', [r for r in rows if r['entry_date'] <= '2025-12-31']),
                              ('2026', [r for r in rows if r['entry_date'] > '2025-12-31'])):
            counts = Counter(r['stage'] for r in subset)
            summary[label] = {'n': len(subset), 'stages': dict(counts),
                              'held_prior_close': sum(bool(r['held_prior_close_days']) for r in subset)}
            f = account['fidelity']
            expected = (f['of'], f['strict']) if label == '2024_2025' else (f['of26'], f['strict26'])
            if (len(subset), counts['filled']) != expected:
                raise AssertionError(f'fidelity does not match {name} {label}')
        results[name] = {'summary': summary, 'rows': rows}
    output = {'dataset_digest': ds.digest(), 'hb_sha256': sha(hb_path), 'he_sha256': sha(he_path),
              'ledger_sha256': sha(LEDGER), 'script_sha256': sha(Path(__file__)),
              'unlocated_dated_longs': missing_rows, 'overlapping_ledger_windows': overlaps, 'results': results}
    target = REPORTS / 'strong_continue_hf.json'
    target.write_text(json.dumps(output, ensure_ascii=False, separators=(',', ':'), allow_nan=False) + '\n')
    for name, result in results.items():
        print(name, result['summary'])
    print('unlocated dated longs:', missing_rows)
    print('overlapping ledger windows:', overlaps)
    print('wrote', target)


if __name__ == '__main__':
    main()
