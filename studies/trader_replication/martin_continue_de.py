"""DE: test existing Z15 short rules on the verified GLD/SLV daily slice."""
import gc
import hashlib
import json
import os
from pathlib import Path

import numpy as np

from studies.trader_data import panel
from . import compare, panels, shorts, system, ticket_t4, watchlist
from .martin_continue_a import required_fields
from .martin_continue_bm import describe
from .martin_continue_bq import _ROLL_MEAN, activity_ranks, chunked_roll_mean
from .martin_continue_bv import daily_name_score, daily_pool_book, martin_rules
from .martin_continue_cr import json_default
from .martin_continue_dd import END, START, SYMBOLS, VerifiedPair, read_daily, sha
from .martin_strong import Data
from .martin_strong_scan import HOLD, active, f1_rules, hold_sim, merge, sized


def reference_strength(stock_close, stock_rank, stock_pool, etf_close, etf_rank, etf_pool):
    """K9 on ETFs ranked against the fixed stock pool plus both ETF names."""
    n, k = etf_close.shape
    k1, top1 = np.zeros((n, k), dtype=bool), np.zeros((n, k), dtype=bool)
    for d in range(n):
        if d >= 21:
            with np.errstate(divide='ignore', invalid='ignore'):
                r_stock = stock_close[d] / stock_close[d - 21] - 1
                r_etf = etf_close[d] / etf_close[d - 21] - 1
            values = np.concatenate((r_stock, r_etf))
            pool = np.concatenate((stock_rank[d], etf_rank[d]))
            valid = pool & np.isfinite(values)
            if valid.sum() >= 20:
                ranks = (np.argsort(np.argsort(values[valid])) + .5) / valid.sum()
                full = np.full(len(values), np.nan)
                full[valid] = ranks
                k1[d] = full[-k:] >= .9
        if d:
            with np.errstate(divide='ignore', invalid='ignore'):
                r_stock = stock_close[d] / stock_close[d - 1] - 1
                r_etf = etf_close[d] / etf_close[d - 1] - 1
            values = np.concatenate((np.where(stock_pool[d], r_stock, np.nan),
                                     np.where(etf_pool[d], r_etf, np.nan)))
            if np.isfinite(values).any():
                threshold = np.nanquantile(values, .98)
                top1[d] = etf_pool[d] & (r_etf >= threshold)
    k9 = martin_rules.S._past_any((k1 & etf_rank) | top1, 5)
    return martin_rules.S._past_any(k9, 40)


def etf_panel(root, reference, sessions):
    xsec, original = root / 'data/preopen-us-xsec-v1', root / 'data/preopen-s23-raw/daily_none'
    hashes = {'CHECKSUMS.sha256': sha(xsec / 'CHECKSUMS.sha256'), 'manifest.json': sha(xsec / 'manifest.json')}
    raw, adjusted = {}, {}
    for sym in SYMBOLS:
        a, b = xsec / f'daily/{sym}.csv', original / f'{sym}.csv'
        hashes[f'xsec/daily/{sym}.csv'], hashes[f's23-raw/daily_none/{sym}.csv'] = sha(a), sha(b)
        adjusted[sym], raw[sym] = read_daily(a), read_daily(b)
    if hashes != reference['files_sha256'] or sha(Path(__file__).with_name('martin_continue_dd.py')) != reference['script_sha256']:
        raise ValueError('DD data or adapter source differs')
    ds = VerifiedPair(raw, adjusted, sessions, hashes)
    if ds.digest() != reference['dataset_adapter']['digest']:
        raise ValueError('DD adapter digest differs')
    out = panel.build(ds, cache=False, write_cache=False)
    if list(map(str, out['days'])) != sessions or out['digest'] != ds.digest():
        raise AssertionError('ETF time axis or digest differs')
    return out


def combine_book(reg, etf_candidates, codes_offset, sessions):
    """Only ETF shorts compete with the original capped stock short by the existing priority."""
    out, selected = [], set()
    for d, original in enumerate(reg):
        longs = [e for e in original if e[2] > 0]
        old = [e for e in original if e[2] < 0]
        if len(old) > 1:
            raise AssertionError('original short daily limit is not one')
        etf = []
        if d < sessions:
            for e in etf_candidates[d]:
                etf.append((((1, e[0])), e[1] + codes_offset) + tuple(e[2:]))
        winner = sorted(old + etf, key=lambda e: e[0])[:1]
        if winner and winner[0][1] >= codes_offset:
            selected.add((d, winner[0][1] - codes_offset))
        out.append(longs + winner)
    return out, selected


def short_summary(trades, year):
    rows = [t for t in trades if t['side'] < 0 and t['code'] in ('US.GLD', 'US.SLV') and t['entry'].startswith(year)]
    closed = [t for t in rows if t['why'] != 'end']
    return {'entries': len(rows), 'closed': len(closed), 'end_marked': len(rows) - len(closed),
            'closed_basis': describe(closed, 'ret_invested'), 'positions': rows}


def cutoff_fidelity(D, trades, n, cutoff):
    actual = {(t['code'], t['entry']) for t in trades if t['side'] > 0}
    his = [x for x in D.base.located(D.A, D.base.trades()) if x[0].side == 'long' and x[0].dated
           and panels.WINDOW[0] <= x[0].entry_date <= cutoff]
    def hits(rows):
        return sum(any((str(D.A['codes'][j]), str(D.A['days'][d])) in actual
                       for d in range(a, min(z, n - 1) + 1)) for t, j, a, z in rows)
    early = [x for x in his if x[0].entry_date <= '2025-12-31']
    later = [x for x in his if x[0].entry_date > '2025-12-31']
    windows = [x for x in D.big if x[0] + 20 < n]
    wide, narrow = 0, {}
    for day, j, _, _, date in windows:
        peak = day + 1 + int(np.nanargmax(D.h[day + 1:day + 21, j]))
        end = min(day + 10, peak - 1)
        positions = [t for t in trades if t['side'] > 0 and t['code'] == str(D.A['codes'][j])]
        wide += any(D.di[t['entry']] <= peak and D.di[t['exit']] >= day for t in positions)
        held = any(D.di[t['entry']] <= end and D.di[t['exit']] >= day for t in positions)
        row = narrow.setdefault(date[:4], {'held': 0, 'windows': 0})
        row['held'] += int(held)
        row['windows'] += 1
    return {'strict': hits(early), 'of': len(early), 'strict26': hits(later), 'of26': len(later),
            'board': wide, 'board_total': len(windows), 'prepeak_ten_day': narrow}


def account(D, px, inputs, book, rules, n, cutoff):
    track = {}
    curve, dates, trades = system.simulate(px, inputs, rules, book, panels.WINDOW[0], cutoff, audit=True, track=track)
    start = int(np.searchsorted(D.A['days'], panels.WINDOW[0]))
    metrics = compare.metrics(curve, dates, trades, book, start, n)
    metrics['entries_by_year'] = {y: sum(t['entry'].startswith(y) for t in trades) for y in ('2024', '2025', '2026')}
    metrics['invested_basis'] = describe([t for t in trades if t['why'] != 'end'], 'ret_invested')
    trade_pnl = sum(t['pnl'] for t in trades)
    end_fee = sum(e['price'] * e['shares'] * (rules.sell_cost if t['side'] > 0 else rules.buy_cost)
                  for t in trades if t['why'] == 'end' for e in t['executions'] if e['action'] == 'end')
    if abs((curve[-1] - 1) - (trade_pnl - track['margin'] + end_fee)) > 1e-8:
        raise AssertionError('account equity does not reconcile with trade PnL and costs')
    return {'metrics': metrics, 'fidelity': cutoff_fidelity(D, trades, n, cutoff),
            'curve_sha256': hashlib.sha256(np.asarray(curve).tobytes()).hexdigest(),
            'reconciliation': {'equity_change': float(curve[-1] - 1), 'trade_pnl': float(trade_pnl),
                               'margin': float(track['margin']), 'assumed_end_exit_fee': float(end_fee)},
            'etf_positions': {y: short_summary(trades, y) for y in ('2024', '2025', '2026')}}, trades


def entry_comparison(a, b, year):
    def indexed(trades):
        chosen = [t for t in trades if t['entry'].startswith(year)]
        result = {(t['entry'], t['code'], t['side'], t['kind']): t for t in chosen}
        if len(result) != len(chosen):
            raise AssertionError('duplicate trade identity')
        return result
    aa, bb = indexed(a), indexed(b)
    common = aa.keys() & bb.keys()
    def describe_group(index, keys):
        rows = [index[k] for k in sorted(keys)]
        return {'positions': len(rows), 'closed': sum(t['why'] != 'end' for t in rows),
                'marked': sum(t['why'] == 'end' for t in rows),
                'closed_pnl': float(sum(t['pnl'] for t in rows if t['why'] != 'end')),
                'marked_pnl': float(sum(t['pnl'] for t in rows if t['why'] == 'end'))}
    return {'u1_common': describe_group(aa, common), 'candidate_common': describe_group(bb, common),
            'u1_only': describe_group(aa, aa.keys() - bb.keys()),
            'candidate_only': describe_group(bb, bb.keys() - aa.keys())}


def original_short_hits(ledger, trades, cutoff):
    actual = {(t['entry'], t['code']) for t in trades if t['side'] < 0}
    rows = [r for r in ledger if r['entry_date'] <= cutoff]
    hits = [r['id'] for r in rows if any(d['day'] <= cutoff and
            (d['day'], 'US.' + r['ticker']) in actual for d in r['days'])]
    return {'located_records': len(rows), 'hits': len(hits), 'hit_ids': hits}


def main():
    if os.environ.get('TRADER_DATA_MODE') != 'frozen' or os.environ.get('TRADER_DATA_TAG') != 'trader-data-v1':
        raise ValueError('explicitly select frozen v1')
    root = Path(__file__).resolve().parents[2]
    reports = root / 'studies/trader_replication/reports/gap_review'
    ref_paths = {name: reports / f'strong_continue_{name}.json' for name in ('bz', 'dc', 'dd')}
    prior = {name: json.loads(p.read_text()) for name, p in ref_paths.items()}
    old = ticket_t4.ranks
    try:
        ticket_t4.ranks = activity_ranks
        D = Data()
    finally:
        ticket_t4.ranks = old
    pin = json.loads((root / 'studies/trader_replication/DATA_PIN.json').read_text())['trader-data-v1']['us']
    if D.A['digest'] != pin or any(p['dataset_digest'] != pin for p in prior.values()):
        raise ValueError('registered data mismatch')
    sc = D.cfg.get('short', {})
    if sc.get('setups') != ['Z15'] or sc.get('pool') != 'U7' or sc.get('gate') != 'below50' or sc.get('max_new') != 1:
        raise ValueError('short configuration changed')
    sessions = [d for d in D.days if START <= d <= END]
    n = len(sessions)
    if D.days[:n] != sessions or len(sessions) != prior['dd']['dataset_adapter']['days']:
        raise AssertionError('ETF dates do not align with the stock panel')
    p = etf_panel(root, prior['dd'], sessions)
    ep = martin_rules.market_arrays('us', p)
    del p, D.fp, D.fwd, D.raw
    for key in ('pr63', 'pr126', 'stack', 'tight'):
        D.A.pop(key, None)
    D.rk = D.rk.astype(np.int32)
    gc.collect()
    stock_pool, etf_pool = martin_rules.pool_for(D.A, 'U7'), martin_rules.pool_for(ep, 'U7')
    leader = reference_strength(D.A['close'][:n], D.A['rank_pool'][:n], stock_pool[:n],
                                ep['close'], ep['rank_pool'], etf_pool)
    under = np.zeros(etf_pool.shape, dtype=bool)
    under[2:] = (ep['close'][1:-1] < ep['e21'][1:-1]) & (ep['e21'][1:-1] < ep['e21'][:-2])
    armed = etf_pool & leader & under
    gate = shorts.gate_days(D.A, sc['gate'])[:n]
    level = martin_rules.prev(ep['e21'])
    gated = armed & gate[:, None]
    fired = shorts.fired(ep, {'armed': gated, 'level': level})
    etf_raw = shorts.short_entries(ep, {'Z15': {'armed': gated, 'level': level}}, sc)
    reg_etf, capped = combine_book(D.reg, etf_raw, len(D.A['codes']), n)
    raw_keys = {(d, e[1]) for d, entries in enumerate(etf_raw) for e in entries}
    stages = {}
    for year in ('2024', '2025', '2026'):
        days = np.array([d.startswith(year) for d in sessions])
        stages[year] = {'pool': int(etf_pool[days].sum()), 'leader_and_pool': int((etf_pool & leader)[days].sum()),
                        'armed': int(armed[days].sum()), 'gate': int(gated[days].sum()),
                        'touched': int(fired[days].sum()),
                        'raw_candidate': sum(sessions[d].startswith(year) for d, j in raw_keys),
                        'after_daily_cap': sum(sessions[d].startswith(year) for d, j in capped)}
    if set(prior['dd']['dataset_adapter']['symbols']) & set(map(str, D.A['codes'])):
        raise AssertionError('ETF already exists in stock panel')
    missing_records = [r for r in prior['dc']['years']['all']['missing_details'] if r['ticker'] in SYMBOLS]
    di = {d: i for i, d in enumerate(sessions)}
    ledger = []
    for r in missing_records:
        d, j = di[r['entry_date']], SYMBOLS.index(r['ticker'])
        ledger.append({**r, 'pool': bool(etf_pool[d, j]), 'leader': bool(leader[d, j]),
                       'armed': bool(armed[d, j]), 'gate': bool(gated[d, j]),
                       'touched': bool(fired[d, j]), 'raw_candidate': (d, j) in raw_keys,
                       'daily_cap': (d, j) in capped})
    del stock_pool, etf_pool, leader, under, armed, gated, fired, etf_raw
    for key in ('pr21', 'rank_pool'):
        D.A.pop(key, None)
    gc.collect()
    try:
        watchlist.roll_mean = chunked_roll_mean
        fields = required_fields(D)
    finally:
        watchlist.roll_mean = _ROLL_MEAN
    mask = active(D, fields)
    score = daily_name_score(fields, mask, HOLD['H3'])
    holding = hold_sim(score, 12, 36)
    raw = daily_pool_book(D, fields, holding, score)
    u1 = merge(D.reg, sized(raw, .5))
    candidate = merge(reg_etf, sized(raw, .5))
    del fields, mask, score, holding, raw, reg_etf
    gc.collect()
    cutoff = END
    rules = f1_rules(D, 6, (1, 3))
    px = D.base.px(D.A)
    em = D.base.ema_inputs(D.A, D.pool, rules)
    baseline, baseline_trades = account(D, px, em, u1, rules, n, cutoff)
    for year in ('2024', '2025'):
        ref, actual = prior['bz']['results']['U1']['metrics'], baseline['metrics']
        if abs(ref['by_year'][year] - actual['by_year'][year]) > 1e-10 or ref['entries_by_year'][year] != actual['entries_by_year'][year]:
            raise AssertionError('U1 baseline differs from BZ in ' + year)
    r74_rules = D.rules
    r74, _ = account(D, px, D.base.ema_inputs(D.A, D.pool, r74_rules), D.reg, r74_rules, n, cutoff)
    results = {'U1': baseline, 'R74': r74}
    baseline['original_short_fidelity'] = original_short_hits(prior['dc']['ledger'], baseline_trades, cutoff)
    comparison = None
    if capped:
        extended_px = {key: np.concatenate((px[key][:n], ep[key]), axis=1) for key in ('open', 'high', 'low', 'close')}
        extended_px.update(dates=px['dates'][:n], codes=np.concatenate((px['codes'], ep['codes'])))
        extended_em = {}
        for key, value in em.items():
            if value.ndim == 1:
                extended_em[key] = value[:n]
            elif key in ep:
                extended_em[key] = np.concatenate((value[:n], ep[key]), axis=1)
            else:
                raise ValueError('cannot extend required EMA input: ' + key)
        # The empty-overlay replay proves the added columns alone change no baseline trades or equity.
        old_overlay, old_trades = account(D, extended_px, extended_em, u1, rules, n, cutoff)
        if old_overlay['curve_sha256'] != baseline['curve_sha256'] or old_trades != baseline_trades:
            raise AssertionError('adding unused ETF columns changed U1')
        results['DE1'], candidate_trades = account(D, extended_px, extended_em, candidate, rules, n, cutoff)
        results['DE1']['original_short_fidelity'] = original_short_hits(prior['dc']['ledger'], candidate_trades, cutoff)
        comparison = {y: entry_comparison(baseline_trades, candidate_trades, y) for y in ('2024', '2025', '2026')}
        actual = {(t['entry'], t['code']) for t in candidate_trades if t['side'] < 0}
        for row in ledger:
            row['actual_entry'] = (row['entry_date'], 'US.' + row['ticker']) in actual
    else:
        if u1 != candidate:
            raise AssertionError('empty ETF addition changed account book')
        for row in ledger:
            row['actual_entry'] = False
    source_files = ('studies/trader_replication/martin_continue_de.py', 'studies/trader_replication/martin_continue_dd.py',
                    'studies/trader_replication/martin_continue_bv.py', 'studies/trader_replication/martin_continue_bq.py',
                    'studies/trader_replication/martin_continue_bm.py', 'studies/trader_replication/martin_continue_bt.py',
                    'studies/trader_replication/shorts.py', 'studies/trader_replication/system.py',
                    'studies/martin_luk/replicate.py')
    out = {'dataset_digest': pin, 'etf_digest': prior['dd']['dataset_adapter']['digest'], 'window': [panels.WINDOW[0], cutoff],
           'stages': stages, 'etf_candidate_days': sorted([sessions[d], SYMBOLS[j]] for d, j in raw_keys),
           'etf_capped_days': sorted([sessions[d], SYMBOLS[j]] for d, j in capped), 'ledger': ledger, 'results': results,
           'entry_comparison': comparison,
           'no_overlay_reason': None if capped else 'no ETF candidates survive the existing daily cap',
           'references_sha256': {p.name: sha(p) for p in ref_paths.values()},
           'code_sha256': {p: sha(root / p) for p in source_files}}
    target = reports / 'strong_continue_de.json'
    target.write_text(json.dumps(out, ensure_ascii=False, indent=2, allow_nan=False, default=json_default) + '\n')
    print('wrote', target, flush=True)


if __name__ == '__main__':
    main()
