"""BY: isolate v2's long market gate on unchanged v1 candidates and prices."""
from collections import Counter
from contextlib import ExitStack
import hashlib
import json
import os
from pathlib import Path
from unittest.mock import patch

import numpy as np

from . import compare, panels, shorts, system, systems
from .martin_continue_bv import martin_rules, selected_shorts
from .martin_continue_bw import positions
from .martin_continue_bx import compact_families


def gate_book(raw, gate, cap, short_book, short_last):
    longs = [sorted(row, key=lambda e: e[0])[:cap] if gate[d] else [] for d, row in enumerate(raw)]
    return shorts.combine(longs, short_book, short_last)


def main():
    tag = os.environ.get('TRADER_DATA_TAG')
    if os.environ.get('TRADER_DATA_MODE') != 'frozen' or tag not in ('trader-data-v1', 'trader-data-v2'):
        raise ValueError('explicit frozen mode and existing v1 or v2 tag required')
    root = Path(__file__).resolve().parents[2]
    reports = root / 'studies/trader_replication/reports/gap_review'
    pins = json.loads((root / 'studies/trader_replication/DATA_PIN.json').read_text())
    W, cfg = systems.get('martin_luk').load()
    if (cfg.get('setup') != 'E11+E10+E2+EW1' or cfg.get('short', {}).get('setups') != ['Z15'] or
        cfg.get('priority') or cfg.get('max_new') != 4 or cfg.get('filter') != 'IDX50'):
        raise ValueError('configuration changed; re-audit the gate construction')
    _, sc = shorts.split_cfg(cfg)
    base = getattr(W, 'base', W)
    A = base.arrays('us')
    old = json.loads((reports / f'strong_continue_bw_{tag}.json').read_text())
    if A['digest'] != pins[tag]['us'] or list(map(str, A['days'])) != old['dates']:
        raise ValueError('frozen digest or dates differ from BW')
    captured = []
    original = martin_rules.market_ok
    def market_gate(*args, **kwargs):
        result = original(*args, **kwargs)
        captured.append(result.copy())
        return result
    trace = {}
    with ExitStack() as stack:
        for name, value in (('setup_families', compact_families), ('short_setups', selected_shorts),
                            ('market_ok', market_gate)):
            stack.enter_context(patch.object(martin_rules, name, value))
        book, rules, mask, pool = W.build(A, cfg, trace=trace)
    del mask
    if len(captured) != 1 or len(captured[0]) != len(A['days']):
        raise AssertionError('expected exactly one market gate vector')
    gate = captured[0]
    if positions(A, book) != old['candidates']:
        raise AssertionError('original candidate list differs from BW')
    if gate_book(trace['raw'], gate, cfg['max_new'], trace['short_entries'], sc.get('short_last', True)) != book:
        raise AssertionError('v1 gate reconstruction differs from original book')
    out = {'tag': tag, 'dataset_digest': A['digest'], 'dates': list(map(str, A['days'])),
           'gate': gate.astype(bool).tolist()}
    if tag == 'trader-data-v1':
        other = json.loads((reports / 'strong_continue_by_trader-data-v2.json').read_text())
        if other['dataset_digest'] != pins['trader-data-v2']['us'] or other['dates'] != out['dates']:
            raise ValueError('v2 gate digest or dates differ')
        alt = np.asarray(other['gate'], dtype=bool)
        altered = gate_book(trace['raw'], alt, cfg['max_new'], trace['short_entries'], sc.get('short_last', True))
        out['gate_comparison'] = {}
        out['candidate_comparison'] = {}
        k1 = {tuple(x[:4]) for x in positions(A, book)}
        k2 = {tuple(x[:4]) for x in positions(A, altered)}
        for year in ('2024', '2025', '2026'):
            inside = np.array([str(d).startswith(year) for d in A['days']])
            changed = inside & (gate != alt)
            out['gate_comparison'][year] = {'sessions': int(inside.sum()), 'changed': int(changed.sum()),
                                             'v1_allowed_v2_denied': int(np.sum(changed & gate)),
                                             'v1_denied_v2_allowed': int(np.sum(changed & alt))}
            a = {x for x in k1 if x[0].startswith(year)}
            b = {x for x in k2 if x[0].startswith(year)}
            out['candidate_comparison'][year] = {'common': len(a & b), 'v1_only': len(a - b),
                                                  'counterfactual_only': len(b - a)}
        for key in ('pr21', 'pr63', 'pr126', 'rank_pool', 'stack', 'tight', 'raw', 'turnover', 'to20', 'e50'):
            A.pop(key, None)
        px, em = base.px(A), base.ema_inputs(A, pool, rules)
        i0 = int(np.searchsorted(A['days'], panels.WINDOW[0]))
        i1 = int(np.searchsorted(A['days'], panels.WINDOW[1], side='right'))
        out['accounts'] = {}
        for name, candidates in (('v1', book), ('v1_with_v2_long_gate', altered)):
            curve, dates, trades = system.simulate(px, em, rules, candidates, *panels.WINDOW, audit=True)
            metric = compare.metrics(curve, dates, trades, candidates, i0, i1)
            metric['entries_by_year'] = {y: sum(t['entry'].startswith(y) for t in trades)
                                         for y in ('2024', '2025', '2026')}
            out['accounts'][name] = metric
        reference = old['own']
        baseline = out['accounts']['v1']
        if baseline['entries_by_year'] != reference['entries_by_year'] or any(abs(baseline['by_year'][y] - reference['by_year'][y]) > 1e-10 for y in baseline['by_year']):
            raise AssertionError('v1 account does not reproduce BW')
    paths = ('studies/trader_replication/martin_continue_by.py', 'studies/trader_replication/martin_continue_bx.py',
             'studies/trader_replication/martin_continue_bw.py', 'studies/trader_replication/martin_continue_bv.py',
             'studies/martin_luk/replicate.py', 'studies/trader_replication/shorts.py',
             'studies/trader_replication/system.py')
    out['code_sha256'] = {p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in paths}
    target = reports / f'strong_continue_by_{tag}.json'
    target.write_text(json.dumps(out, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    print(json.dumps({k: v for k, v in out.items() if k not in ('dates', 'gate')}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
