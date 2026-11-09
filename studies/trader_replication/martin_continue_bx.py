"""BX: trace all R74 candidates that differ between frozen v1 and v2."""
from collections import Counter
from contextlib import ExitStack
import hashlib
import json
import os
from pathlib import Path
import sys
from unittest.mock import patch

import numpy as np

from . import shorts, systems
from .martin_continue_bv import martin_rules, selected_shorts
from .martin_continue_bw import positions

LONG_STAGES = ('long_pool', 'long_mask', 'long_raw', 'long_filtered', 'long_capped')
SHORT_STAGES = ('short_pool', 'short_armed', 'short_gated', 'short_fired', 'short_raw', 'short_capped')


def compact_families(A, w):
    o, h, low, c = A['open'], A['high'], A['low'], A['close']
    ph, pc = martin_rules.prev(h), martin_rules.prev(c)
    e9p, e21p = martin_rules.prev(A['e9']), martin_rules.prev(A['e21'])
    with np.errstate(invalid='ignore', divide='ignore'):
        e1 = h > ph
        e2 = martin_rules.prev(A['tight']) & e1
        e4 = (e9p > e21p) & (low <= e9p) & (h >= e9p)
        near = martin_rules.prev(np.abs(c / A['e9'] - 1) <= .03)
        handshake = (o > pc * 1.01) & (low <= np.fmax(ph, e9p)) & (c > np.fmin(ph, e9p))
    return {'E11': {'E11': handshake}, 'E10': {'E2': e1 & near, 'E4': e4 & near},
            'E2': {'E2': e2}, 'EW1': {'E2': martin_rules.weekly_cached(A)['EW1']}}


def first_persistent(a, b, stages):
    if any(k not in a or k not in b or a[k] is None or b[k] is None for k in stages):
        return 'unobserved'
    final = (a[stages[-1]], b[stages[-1]])
    if final[0] == final[1]:
        return 'not_divergent'
    for i, stage in enumerate(stages):
        if all((a[k], b[k]) == final for k in stages[i:]):
            return stage
    return 'unobserved'


def main():
    tag = os.environ.get('TRADER_DATA_TAG')
    if os.environ.get('TRADER_DATA_MODE') != 'frozen' or tag not in ('trader-data-v1', 'trader-data-v2'):
        raise ValueError('explicit frozen mode and existing v1 or v2 tag are required')
    root = Path(__file__).resolve().parents[2]
    reports = root / 'studies/trader_replication/reports/gap_review'
    prev = {t: json.loads((reports / f'strong_continue_bw_{t}.json').read_text())
            for t in ('trader-data-v1', 'trader-data-v2')}
    keys = {t: {tuple(x[:4]) for x in prev[t]['candidates']} for t in prev}
    targets = sorted(keys['trader-data-v1'] ^ keys['trader-data-v2'])
    pins = json.loads((root / 'studies/trader_replication/DATA_PIN.json').read_text())
    W, cfg = systems.get('martin_luk').load()
    if cfg.get('setup') != 'E11+E10+E2+EW1' or cfg.get('short', {}).get('setups') != ['Z15']:
        raise ValueError('configured setup changed')
    base = getattr(W, 'base', W)
    A = base.arrays('us')
    if A['digest'] != pins[tag]['us'] or list(map(str, A['days'])) != prev[tag]['dates']:
        raise ValueError('frozen digest or dates differ from BW')
    di = {str(x): i for i, x in enumerate(A['days'])}
    ci = {str(x): i for i, x in enumerate(A['codes'])}
    if any(k[0] not in di or k[1] not in ci for k in targets):
        raise ValueError('a target is missing in this data version')
    rows = {k: {} for k in targets}
    long_keys = [k for k in targets if k[2] > 0]
    short_keys = [k for k in targets if k[2] < 0]

    def sample(label, matrix, subset):
        for k in subset:
            rows[k][label] = bool(matrix[di[k[0]], ci[k[1]]])

    def by_day(label, vector, subset):
        for k in subset:
            rows[k][label] = bool(vector[di[k[0]]])

    def membership(label, book, subset):
        for k in subset:
            day, j = di[k[0]], ci[k[1]]
            rows[k][label] = any(e[1] == j and e[2] == k[2] and e[5] == k[3] for e in book[day])

    orig_system, orig_strength = martin_rules.system_signals, martin_rules.strength_lists
    orig_watch, orig_ep = martin_rules.watch_lists, martin_rules.ep_signal
    orig_base, orig_market = martin_rules.base_path, martin_rules.market_ok
    orig_gate, orig_entries = shorts.gate_days, shorts.short_entries
    strength_name = cfg.get('strength') or martin_rules.strength_choice()
    watch_name = cfg.get('watch') or martin_rules.watch_choice()

    def get_strength(a, pool):
        values = orig_strength(a, pool)
        if sys._getframe(1).f_code is orig_system.__code__:
            sample('strength', values[strength_name], long_keys)
        return values

    def get_watch(a):
        values = orig_watch(a)
        if sys._getframe(1).f_code is orig_system.__code__:
            sample('watch_condition', values[watch_name], long_keys)
        return values

    def get_system(a, config=None):
        pool, w, sig = orig_system(a, config)
        sample('long_pool', pool, long_keys)
        sample('long_watchlist', w, long_keys)
        for name, value in sig.items():
            sample('shape:' + name, value, long_keys)
        return pool, w, sig

    def get_ep(*args, **kwargs):
        value = orig_ep(*args, **kwargs)
        if sys._getframe(1).f_code.co_name == 'build_system':
            sample('ep_branch', value, long_keys)
        return value

    def get_base(*args, **kwargs):
        value = orig_base(*args, **kwargs)
        if sys._getframe(1).f_code.co_name == 'build_system':
            sample('base_path', value, long_keys)
        return value

    def get_market(*args, **kwargs):
        value = orig_market(*args, **kwargs)
        if sys._getframe(1).f_code.co_name == 'build_system':
            by_day('long_market_gate', value, long_keys)
        return value

    def get_short(a, sc):
        masks, pool = selected_shorts(a, sc)
        sample('short_pool', pool, short_keys)
        sample('short_armed', masks['Z15']['armed'], short_keys)
        return masks, pool

    def get_gate(a, spec):
        value = orig_gate(a, spec)
        by_day('short_market_gate', value, short_keys)
        return value

    def get_entries(a, masks, sc):
        m = masks['Z15']
        for k in short_keys:
            d, j = di[k[0]], ci[k[1]]
            rows[k]['short_gated'] = bool(m['armed'][d, j])
            rows[k]['short_fired'] = bool(m['armed'][d, j] and a['open'][d, j] < m['level'][d, j] <= a['high'][d, j])
        value = orig_entries(a, masks, sc)
        membership('short_raw', value, short_keys)
        return value

    trace = {}
    with ExitStack() as stack:
        for obj, name, value in ((martin_rules, 'setup_families', compact_families),
                                 (martin_rules, 'strength_lists', get_strength),
                                 (martin_rules, 'watch_lists', get_watch),
                                 (martin_rules, 'system_signals', get_system),
                                 (martin_rules, 'ep_signal', get_ep),
                                 (martin_rules, 'base_path', get_base),
                                 (martin_rules, 'market_ok', get_market),
                                 (martin_rules, 'short_setups', get_short),
                                 (shorts, 'gate_days', get_gate),
                                 (shorts, 'short_entries', get_entries)):
            stack.enter_context(patch.object(obj, name, value))
        book, _, mask, _ = W.build(A, cfg, trace=trace)
    observed = positions(A, book)
    if observed != prev[tag]['candidates']:
        raise AssertionError('trace changed the complete candidate list from BW')
    sample('long_mask', mask, long_keys)
    for label, key in (('long_raw', 'raw'), ('long_filtered', 'filtered'), ('long_capped', 'capped')):
        membership(label, trace[key], long_keys)
    membership('short_capped', trace['short_entries'], short_keys)
    for k in targets:
        final = 'long_capped' if k[2] > 0 else 'short_capped'
        if rows[k].get(final) != (k in keys[tag]):
            raise AssertionError('trace final membership differs from BW')
    out = {'tag': tag, 'dataset_digest': A['digest'], 'targets': [{'key': list(k), 'states': rows[k]} for k in targets]}
    if tag == 'trader-data-v1':
        other = json.loads((reports / 'strong_continue_bx_trader-data-v2.json').read_text())
        if other['dataset_digest'] != pins['trader-data-v2']['us']:
            raise ValueError('v2 trace digest differs')
        other_rows = {tuple(x['key']): x['states'] for x in other['targets']}
        if set(other_rows) != set(targets):
            raise ValueError('v2 trace targets differ')
        summary = {}
        for year in ('2024', '2025', '2026'):
            summary[year] = {}
            for side, name in ((1, 'long'), (-1, 'short')):
                selected = [k for k in targets if k[0].startswith(year) and k[2] == side]
                stages = LONG_STAGES if side == 1 else SHORT_STAGES
                stages_count = Counter(first_persistent(rows[k], other_rows[k], stages) for k in selected)
                if stages_count.get('unobserved') or stages_count.get('not_divergent'):
                    raise ValueError(f'cannot classify {year} {name}: {stages_count}')
                gate = 'long_market_gate' if side == 1 else 'short_market_gate'
                if any(gate not in rows[k] or gate not in other_rows[k] for k in selected):
                    raise ValueError('missing market-gate observation')
                diff_dates = {k[0] for k in selected if rows[k][gate] != other_rows[k][gate]}
                summary[year][name] = {'v1_only': sum(k in keys[tag] for k in selected),
                                       'v2_only': sum(k in keys['trader-data-v2'] for k in selected),
                                       'first_persistent': dict(stages_count),
                                       'target_dates_gate_differs': len(diff_dates)}
        out['summary'] = summary
    paths = ('studies/trader_replication/martin_continue_bx.py', 'studies/trader_replication/martin_continue_bv.py',
             'studies/trader_replication/martin_continue_bw.py', 'studies/martin_luk/replicate.py',
             'studies/trader_replication/shorts.py')
    out['code_sha256'] = {p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in paths}
    target = reports / f'strong_continue_bx_{tag}.json'
    target.write_text(json.dumps(out, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'tag': tag, 'targets': len(targets), 'summary': out.get('summary')}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
