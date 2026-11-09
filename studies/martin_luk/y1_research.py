"""PLAN_Y1: frozen labels and read-only account evaluation; never run a strategy."""
from __future__ import annotations

import argparse
from collections import Counter
import csv
from functools import lru_cache
import hashlib
import json
import os
from pathlib import Path
import resource
import sys

import numpy as np

from studies.trader_replication import mainleg as M

ROOT = Path(__file__).resolve().parents[2]
STUDY = ROOT/'studies/martin_luk'
WORK = STUDY/'reports/y1_work'
GAP = ROOT/'studies/trader_replication/reports/gap_review'
DATA = GAP/'ie5_work'
FROZEN = STUDY/'notes/legs_frozen.json'
YEARS = ('2024', '2025', '2026')
# All six cells use the same continuous 2024-2026 account, not a mix of account vintages.
ACCOUNTS = {
    'IE47_C062': ('e21_work/BASE_full', 'C062_2024'),
    'IE47_S1': ('e21_work/S1_full', 'C062_2024'),
    'IE47_K2': ('e15_work/full', 'K2_2024'),
    'master_C062': ('e15_work/master_swap/full', 'C062_2024'),
    'master_S1': ('e21_work/master/S1_full', 'C062_2024'),
    'master_K2': ('e15_work/master_swap/full', 'K2_2024'),
}


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def write(path, value):
    path.parent.mkdir(exist_ok=True, parents=True)
    text = json.dumps(value, ensure_ascii=False, indent=1, allow_nan=False,
                      default=lambda v: v.tolist() if isinstance(v, np.ndarray) else v.item())+'\n'
    path.write_text(text, encoding='utf-8')


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024*1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


class Prices:
    """Only sixteen stocks in memory; no all-market OHLCV panel."""
    @lru_cache(maxsize=16)
    def __getitem__(self, code):
        with np.load(DATA/'stocks'/f'{code}.npz') as z:
            return {k: z[k].astype(float) for k in ('o', 'h', 'l', 'c')}

    def get(self, code):
        return self[code] if (DATA/'stocks'/f'{code}.npz').exists() else None


def filtering_pool(meta):
    """Replay only the existing four causal filters, one night at a time."""
    from .ie47_e1 import filter_night
    names = read(GAP/'strong_continue_ie4_frozen.json')['raw_feature_names']
    columns = [names.index(k) for k in ('h4_history', 'adr20', 'option_volume', 'low20')]
    raw = np.load(DATA/'raw.npy', mmap_mode='r')
    pool, offset = {}, 0
    for day, codes in sorted(meta['scope'].items()):
        end = offset+len(codes)
        if day >= meta['first_signal']:
            passed, _ = filter_night(raw[offset:end, columns])
            pool[day] = [c for c, ok in zip(codes, passed) if ok]
        offset = end
    assert offset == raw.shape[0]
    return pool


def account_paths(directory, prefix):
    return [STUDY/'reports'/directory/f'{prefix}_{suffix}.json' for suffix in ('trades', 'curve', 'stats')]


def adapt(path, calendar):
    """The only dependency on the E15/E21 JSON execution schema."""
    di = {day: i for i, day in enumerate(calendar)}
    result, residuals = [], []
    for number, t in enumerate(read(path)):
        if t['side'] != 1:
            raise ValueError('Y1 is a long-only evaluation; mixed ledger requires a separate book')
        if not t.get('executions'):
            raise ValueError('no executions: cannot invent FIFO lots from a trade-level return')
        fills = [dict(index=di[e['time']], quantity=e['shares']*(1 if e['action'] in ('entry', 'add') else -1),
                      price=e['price'], fee=e['shares']*e['price']*.0005, open=e['action'] == 'end')
                 for e in t['executions']]
        pieces = M.lots(fills, pnl=t['pnl'])
        residuals.append(dict(trade=number, residual=sum(r['residual'] for r in pieces)))
        result.append(dict(id=number, code=t['code'], entry=di[t['entry']], pnl=t['pnl'],
                           closed=t['why'] != 'end', lots=pieces,
                           confirmed=di[t['confirmed_day']] if t.get('confirmed_day') else None))
    return result, dict(n_trades=len(result), max_residual=max((abs(r['residual']) for r in residuals), default=0.),
                        total_residual=sum(r['residual'] for r in residuals), residuals=residuals)


def freeze():
    if FROZEN.exists() or (WORK/'preregistered.json').exists():
        raise FileExistsError('Y1 freeze already exists; do not silently replace labels')
    WORK.mkdir(parents=True, exist_ok=True)
    meta, prices = read(DATA/'prepared.json'), Prices()
    calendar, rows = meta['days'], list(csv.DictReader((STUDY/'notes/trades.csv').open()))
    pool = filtering_pool(meta)
    write(WORK/'pool.json', pool)
    anchors, audit, missing, short = [], [], [], []
    for row in rows:
        if row['side'] != 'long':
            short.append(dict(id=row['id'], ticker=row['ticker'], anchor=row['entry_date'] or row['window_lo']))
            continue
        code, anchor = 'US.'+row['ticker'], row['entry_date'] or row['window_lo']
        i = int(np.searchsorted(calendar, anchor)) if anchor else len(calendar)
        p = prices.get(code)
        reason = ('missing_anchor' if not anchor else 'missing_frozen_stock' if p is None else
                  'anchor_outside_calendar' if i >= len(calendar) else
                  'missing_anchor_close' if not np.isfinite(p['c'][i]) or p['c'][i] <= 0 else None)
        a = dict(id=row['id'], code=code, anchor=anchor, anchor_kind='entry_date' if row['entry_date'] else 'window_lo',
                 precision=row['precision'], index=i if i < len(calendar) else None,
                 first=calendar[i] if i < len(calendar) else None, reason=reason)
        audit.append(a)
        if reason:
            missing.append(a)
        else:
            anchors.append((code, i, row['id']))
    anchors.sort(key=lambda x: (x[1], x[0], x[2]))
    by_id = {r['id']: r for r in audit}
    old_entries = [(r['code'], calendar.index(r['entry_date']), r['id']) for r in meta['entries']]
    old = M.legs(old_entries, prices)
    old_keys = {(g['code'], g['peak']) for g in old}
    all_legs = M.legs(anchors, prices, big=-np.inf)
    large, small = [], []
    for g in all_legs:
        first, gain = g['entries'][0]['index'], g['entries'][0]['gain']
        code, p = g['code'], prices[g['code']]
        entries = [dict(e, precision=by_id[e['label']]['precision'], anchor=by_id[e['label']]['anchor']) for e in g['entries']]
        qualified = []
        for t in range(max(0, first-4), g['peak']-1):
            fill = p['o'][t+1]
            if np.isfinite(fill) and fill > 0 and g['top']/fill-1 >= .5*gain-1e-12:
                qualified.append(t)
        reachable = any(code in pool.get(calendar[t], ()) for t in qualified)
        label = dict(g, key=f"{code}:{calendar[first]}:{calendar[g['peak']]}", first=first, gain=gain,
            anchor=by_id[entries[0]['label']]['anchor'], precision=entries[0]['precision'], entries=entries,
            first_date=calendar[first], peak_date=calendar[g['peak']], duration=g['peak']-first,
            exit_known=None, reachable=reachable,
            reach_reason='eligible_pool_night_exists' if reachable else 'no_pool_membership_on_half_remaining_nights',
            legacy_42=(code, g['peak']) in old_keys)
        (large if gain >= .30 else small).append(label)
    frozen = dict(version='Y1-20261107', calendar=calendar, calendar_sha256=sha(DATA/'prepared.json'),
        source_sha256=sha(STUDY/'notes/trades.csv'), anchor_rule='entry_date else window_lo; first session on/after anchor',
        reason='完整使用原始多头行；不再因 window 精度被旧 prepared 清单漏掉。旧 42 段只作历史对照。',
        horizon=60, big=.30, lead=3, keep=.5, legs=large, other_legs=small,
        audit=audit, missing=missing, shorts=short,
        counts=dict(raw_long=len(audit), valid_anchors=len(anchors), missing=len(missing),
                    old_legs=len(old), new_legs=len(large),
                    by_year=dict(Counter(calendar[g['first']][:4] for g in large))),
        added_vs_42=[g['key'] for g in large if not g['legacy_42']],
        removed_vs_42=[dict(code=g['code'], peak=calendar[g['peak']]) for g in old if not any(
                        g['code'] == n['code'] and g['peak'] == n['peak'] for n in large)])
    write(FROZEN, frozen)
    protected = [STUDY/'reports/final_system_r74.json', STUDY/'reports/ie47_profile.json',
                 STUDY/'ie47_e1.py', ROOT/'studies/trader_replication/martin.py',
                 ROOT/'studies/trader_replication/system.py', STUDY/'reports/E16_CN.md']
    protected += sorted((ROOT/'studies/trader_screens').glob('*.py'))
    inputs = [DATA/'prepared.json', DATA/'raw.npy', GAP/'strong_continue_ie4_frozen.json',
              STUDY/'notes/trades.csv', STUDY/'notes/PLAN_Y1_CN.md',
              STUDY/'notes/PI_METRIC_ADVICE_20261107_CN.md',
              STUDY/'reports/e21_work/inputs.json', STUDY/'reports/e21_work/master/picks.json']
    codes = {a['code'] for a in audit}
    availability = {}
    for name, (directory, prefix) in ACCOUNTS.items():
        paths = account_paths(directory, prefix)
        availability[name] = dict(available=all(p.exists() for p in paths), paths=[str(p.relative_to(ROOT)) for p in paths])
        inputs += [p for p in paths if p.exists()]
        if availability[name]['available']:
            trades, check = adapt(paths[0], calendar)
            assert check['max_residual'] < 1e-9, (name, check['max_residual'])
            write(WORK/f'{name}_adapter.json', check)
            codes.update(t['code'] for t in trades)
    inputs += [DATA/'stocks'/f'{code}.npz' for code in sorted(codes) if (DATA/'stocks'/f'{code}.npz').exists()]
    write(WORK/'preregistered.json', dict(
        frozen_sha256=sha(FROZEN), formula='FIFO, first-anchor gain, first actual lot per leg, cutoff close, EOD capital',
        account_mode='continuous 2024-2026; no strategy rerun, refit, new data, or new account simulation',
        targets=dict(cap_equity=.50, purity_gross=.60, early=.50, capture_total=.50, top10=5, trades=52, win_max=.35),
        capital_year='calendar year', pnl_year='first trade-entry year', capture_year='leg first-anchor year',
        top10_rule='top ten actual closed winning trades, count only positive T1 net contribution',
        h_book='same fixed historical lot sizes, H only; no reinvestment/resizing, no financing allocation',
        missing_legs='retain unresolved source rows; cannot infer gain/merge/denominator without data',
        native_R74=dict(available=False, reason='未找到原生 R74 的逐笔 executions 和权益曲线；r74/final_system/diagnose 只有汇总或诊断行'),
        availability=availability, input_sha256={str(p.relative_to(ROOT)): sha(p) for p in inputs},
        protected_sha256={str(p.relative_to(ROOT)): sha(p) for p in protected},
        code_sha256={str(p.relative_to(ROOT)): sha(p) for p in (Path(__file__), Path(M.__file__))},
        new_2026_evaluations_per_account=1, independent_out_of_sample=False,
        secret_guard='existing shared hooks call scripts/secret_guard.py; installer preserved existing core.hooksPath'))
    print(f"Frozen {len(large)} legs, old {len(old)}, missing source rows {len(missing)}", flush=True)


def h_book(rows, calendar, prices):
    """Descriptive oracle filter of historical lots, never a tradable selector."""
    pnl = np.zeros(len(calendar))
    events = Counter()
    for row in rows:
        if row['bucket'] != 'T1':
            continue
        start, end = row['entry'], row['h_end']
        close = prices[row['code']]['c'][start:end]
        pnl[start:end] += row['shares']*(close-row['price'])-row['buy_fee']
        pnl[end:] += row['h_pnl']
        events[(row['trade'], row['source'])] = start
    equity = 1.+pnl
    years = {}
    for year in YEARS:
        indices = [i for i, d in enumerate(calendar) if d[:4] == year]
        before = float(equity[indices[0]-1]) if indices[0] else 1.
        values = np.r_[before, equity[indices]]
        running = np.maximum.accumulate(values)
        years[year] = dict(return_=float(values[-1]/before-1), pnl=float(values[-1]-before),
            maxdd=float(np.max(1-values/running)),
            lots=sum(calendar[start][:4] == year for start in events.values()),
            trades=len({r['trade'] for r in rows if r['bucket'] == 'T1' and r['year'] == year}),
            profitable=before > 0 and values[-1] > before)
    return dict(equity=equity.tolist(), years=years, final=float(equity[-1]),
                fixed_historical_sizes=True, future_label_filter=True, financing_included=False)


def targets(row, coverage):
    checks = dict(capital=row['cap_equity'] is not None and row['cap_equity'] >= .5,
        gross=row['purity_gross'] is not None and row['purity_gross'] >= .6,
        early=bool(coverage['n'] and coverage['covered']/coverage['n'] >= .5),
        capture=coverage['capture_total'] is not None and coverage['capture_total'] >= .5,
        top10=row['top10_his_leg'] >= 5,
        trades=row['n_trades'] >= 52, win=row['win'] is not None and row['win'] <= .35)
    return dict(checks=checks, passed=all(checks.values()),
                unresolved_censored=coverage.get('censored_uncovered', 0))


def evaluate():
    frozen, prereg = read(FROZEN), read(WORK/'preregistered.json')
    assert sha(FROZEN) == prereg['frozen_sha256']
    assert all(sha(ROOT/p) == s for p, s in prereg['input_sha256'].items()), 'frozen input changed'
    assert all(sha(ROOT/p) == s for p, s in prereg['code_sha256'].items()), 'freeze formulas again before evaluation'
    with (WORK/'evaluation_started.json').open('x') as stream:
        json.dump(dict(frozen_sha256=sha(FROZEN), evaluations_per_account=1), stream)
    calendar, prices = frozen['calendar'], Prices()
    pool = {calendar.index(d): cs for d, cs in read(WORK/'pool.json').items()}
    ticker_years = {(r['code'], r['anchor'][:4]) for r in frozen['audit'] if r['anchor']}
    summary = {}
    for name, (directory, prefix) in ACCOUNTS.items():
        if not prereg['availability'][name]['available']:
            summary[name] = dict(available=False)
            continue
        paths = account_paths(directory, prefix)
        trades, adapter = adapt(paths[0], calendar)
        curve, stats = read(paths[1]), read(paths[2])
        eq = np.ones(len(calendar))
        for day, value in zip(curve['days'], curve['equity']):
            eq[calendar.index(day)] = value
        assert curve['days'] == [d for d in calendar if curve['days'][0] <= d <= curve['days'][-1]]
        result = M.summary_account(trades, frozen['legs'], prices, calendar, eq,
                                   frozen['other_legs'], ticker_years)
        result['years'] = {y: result['years'][y] for y in YEARS}
        result['H_book'] = h_book(result['lots'], calendar, prices)
        assert abs(result['H_book']['final']-1-sum(r['h_pnl'] for r in result['lots']
                   if r['bucket'] == 'T1')) < 1e-9, 'H book does not reconcile to attributed lot pnl'
        h_equity = np.asarray(result['H_book']['equity'])
        for year, row in result['H_book']['years'].items():
            mask = np.array([d[:4] == year for d in calendar])
            row['cap_equity'] = float(np.mean(result['daily']['his'][mask]/h_equity[mask])) if (h_equity[mask] > 0).all() else None
            gp = sum(max(r['h_pnl'], 0.) for r in result['lots'] if r['bucket'] == 'T1' and r['year'] == year)
            row['purity_gross'] = 1. if gp > 0 else None
        for year, row in result['years'].items():
            row['account_return'] = stats['by_year'][year]
            row['targets'] = targets(row, row['coverage']['including_censored'])
            excl = row['excluding_censored']
            excl['targets'] = targets(excl, excl['coverage'])
        # Reconcile to the stored continuous account, including terminal sell-fee convention and financing.
        terminal_fee = sum(r['sell_fee'] for t in trades for r in t['lots'] if r['open'])
        margin = stats.get('margin', {})
        financing = margin.get('interest', margin.get('cost', None)) if isinstance(margin, dict) else float(margin)
        implied = sum(t['pnl'] for t in trades)+terminal_fee-(curve['equity'][-1]-1)
        assert financing is not None and abs(implied-financing) < 1e-9, 'account curve/pnl/financing mismatch'
        result['adapter'] = adapter
        result['reconciliation'] = dict(lot_pnl=sum(r['pnl'] for r in result['lots']),
            trade_pnl=sum(t['pnl'] for t in trades), account_pnl=curve['equity'][-1]-1,
            terminal_fee=terminal_fee,
            implied_financing=implied, stored_margin=margin, stored_financing=financing,
            residual=implied-financing)
        write(WORK/f'{name}.json', result)
        summary[name] = dict(available=True, years=result['years'], H_book=result['H_book']['years'])
        print(f"Evaluated {name}: {len(trades)} trades", flush=True)
    write(WORK/'accounts.json', summary)
    diagnostics = {}
    pick_sources = {'IE47': read(STUDY/'reports/e21_work/inputs.json')['picks'],
                    'master': read(STUDY/'reports/e21_work/master/picks.json')}
    for name, source in pick_sources.items():
        picks = {calendar.index(d): cs for d, cs in source.items()}
        diagnostics[name] = {}
        for year in YEARS:
            full_k = max(3, max(map(len, picks.values()))) if name == 'master' else 3
            full = M.selection_diagnostics(picks, frozen['legs'], prices, calendar, pool, (year,), k=full_k, training=False)
            full['K'] = {str(k): M.selection_diagnostics(picks, frozen['legs'], prices, calendar, pool, (year,), k=k, training=False)
                         for k in (1, 2, 3)}
            full['nomination_counts'] = dict(Counter(len(cs) for t, cs in picks.items() if calendar[t][:4] == year))
            diagnostics[name][year] = full
    write(WORK/'selection.json', diagnostics)
    write(WORK/'evaluation_complete.json', dict(evaluations={n: 1 for n in summary},
        selection_evaluations={n: 1 for n in diagnostics}, frozen_sha256=sha(FROZEN),
        peak_rss_mib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024))


def offline():
    """Enforce this task's output boundary even when reusing existing read helpers."""
    sys.dont_write_bytecode = True
    allowed = (WORK.resolve(), FROZEN.resolve(), (STUDY/'reports/Y1_CN.md').resolve())
    def audit(event, args):
        if event in ('socket.connect', 'socket.bind', 'socket.getaddrinfo', 'subprocess.Popen', 'os.system'):
            raise PermissionError('Y1 is offline and single-process')
        if event == 'open':
            path, _, flags = args
            if isinstance(path, int) or not flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND):
                return
            resolved = Path(path).resolve()
            if not any(resolved == p or resolved.is_relative_to(p) for p in allowed):
                raise PermissionError('Y1 output boundary')
    sys.addaudithook(audit)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('stage', choices=('freeze', 'evaluate'))
    args = parser.parse_args()
    offline()
    globals()[args.stage]()
