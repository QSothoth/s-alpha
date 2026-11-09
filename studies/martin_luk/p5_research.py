"""Bounded offline P5 diagnostics and preregistered evaluation."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import asdict, replace
from datetime import datetime, timezone
import fcntl
import gc
import gzip
import hashlib
import itertools
import json
import os
from pathlib import Path
import re
import shutil
import sys

import numpy as np

from . import p3_research as P3, p4_research as P4, p4_policy as P4S, p5_policy as S
from .p2_research import select_internal, strategy_only
from studies.trader_replication import allocation, mainleg, system as Y

ROOT, HOME = P3.ROOT, P3.HOME
OUT = HOME / 'reports/p5_work'
PREREG = HOME / 'notes/PREREG_P5_CN.md'
YEARS = P3.YEARS
SOURCES = {}
STOPS = ('stop', 'gap_stop', 'stop_day0', 'close_stop')


def now():
    return datetime.now(timezone.utc).isoformat()


def read(path):
    path = Path(path)
    if not path.exists():
        path = Path(str(path) + '.gz')
    SOURCES[str(path.relative_to(ROOT))] = P3.sha(path)
    if path.suffix == '.gz':
        with gzip.open(path, 'rt') as stream:
            return json.load(stream)
    return json.loads(path.read_text())


def write(relative, value):
    path = OUT / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix == '.gz':
        with gzip.open(path, 'xt', compresslevel=6) as stream:
            json.dump(P3.clean(value), stream, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
            stream.write('\n')
    else:
        P3.write(path, value, exclusive=True)


def log(phase, decision, evidence, result):
    path = OUT / 'decisions.tsv'
    if not path.exists():
        path.write_text('ts\tphase\tdecision\tevidence\tresult\n')
    with path.open('a') as stream:
        stream.write('\t'.join(str(x).replace('\t', ' ').replace('\n', ' ')
            for x in (now(), phase, decision, evidence, result)) + '\n')


def freeze():
    protected = {}
    for directory in ('studies', 'skills/trader-replication', 'watch', 'custody'):
        for path in (ROOT / directory).rglob('*'):
            if not path.is_file() or path.suffix not in ('.py', '.json', '.csv', '.md', '.gz'):
                continue
            if path.is_relative_to(OUT) or path.name.startswith(('p5_', 'test_p5')) or path in (
                    PREREG, HOME / 'reports/P5_CN.md'):
                continue
            protected[str(path.relative_to(ROOT))] = P3.sha(path)
    write('protocol.json', dict(task='PLAN_P5_CN', started=now(), protected=protected,
        plan_sha256=P3.sha(HOME / 'notes/PLAN_P5_CN.md'), resources=P3.resources(),
        memory_before=Path('/proc/meminfo').read_text(), disk_free_bytes=shutil.disk_usage(ROOT).free,
        constraints=dict(offline=True, downloads=False, git_commits=0, single_process=True, single_thread=True),
        secret_guard='installer refused existing hooksPath; existing pre-commit/pre-push both exec secret_guard.py'))
    log('freeze', '冻结既有源码和工件', 'protocol.json', len(protected))
    print('protected inputs frozen', len(protected), flush=True)


def frozen(preregistered=False):
    protocol = read(OUT / 'protocol.json')
    assert P3.sha(HOME / 'notes/PLAN_P5_CN.md') == protocol['plan_sha256']
    if preregistered:
        manifest = read(OUT / 'preregistered.json')
        assert P3.sha(PREREG) == manifest['prereg_sha256'], 'P5 prereg changed'
        assert P3.sha(OUT / 'a0_summary.json') == manifest['a0_sha256']
    return protocol


def describe(values):
    x = np.asarray([v for v in values if v is not None and np.isfinite(v)], float)
    return dict(n=len(x), median=float(np.median(x)) if len(x) else None,
        p25=float(np.quantile(x, .25)) if len(x) else None,
        p75=float(np.quantile(x, .75)) if len(x) else None,
        mean=float(np.mean(x)) if len(x) else None)


def stop_rows(A, trades, labelled_codes):
    ci, di = {str(c): j for j, c in enumerate(A['codes'])}, {str(d): t for t, d in enumerate(A['days'])}
    rows = []
    for tid, trade in enumerate(trades):
        if trade['side'] < 0 or trade['why'] not in STOPS:
            continue
        j, entry, exit_ = ci[trade['code']], di[trade['entry']], di[trade['exit']]
        adr = float(A['adr'][entry - 1, j]) / 100
        # X1/master's successful R adds lift the whole stop to the original fill.
        stop = max(trade['stop'], trade['fill']) if any(e['action'] == 'add' for e in trade['executions']) else trade['stop']
        low, close = float(A['low'][exit_, j]), float(A['close'][exit_, j])
        exit_price = trade['executions'][-1]['price']
        future = {}
        for horizon in (5, 10, 20):
            values = np.asarray(A['high'][exit_ + 1:exit_ + horizon + 1, j], float)
            valid = values[np.isfinite(values) & (values > 0)]
            high = float(valid.max()) if len(valid) else None
            future[str(horizon)] = dict(complete=len(values) == horizon and len(valid) == horizon,
                observed=len(valid), high=high,
                from_exit=high / exit_price - 1 if high else None,
                from_stop=high / stop - 1 if high else None,
                from_entry=high / trade['fill'] - 1 if high else None)
        rows.append(dict(id=tid, code=trade['code'], entry=trade['entry'], exit=trade['exit'],
            year=trade['entry'][:4], days=trade['days'], why=trade['why'], labelled=trade['code'] in labelled_codes,
            fill=trade['fill'], initial_stop=trade['stop'], effective_stop=stop, exit_price=exit_price,
            risk_pct=trade['risk_pct'], adr_pct=adr,
            stop_adr=trade['risk_pct'] / adr if adr > 0 else None,
            stop_day_low=low, stop_day_close=close, low_below_stop=stop - low,
            low_below_stop_pct=(stop - low) / stop, low_below_stop_adr=(stop - low) / (trade['fill'] * adr),
            close_recovered=close >= stop, day0=entry == exit_, future=future))
    return rows


def stop_statistics(rows):
    return dict(n=len(rows), day0=sum(r['day0'] for r in rows),
        close_recovered=sum(r['close_recovered'] for r in rows),
        close_recovered_rate=sum(r['close_recovered'] for r in rows) / len(rows) if rows else None,
        stop_adr=describe(r['stop_adr'] for r in rows),
        low_below_stop_pct=describe(r['low_below_stop_pct'] for r in rows),
        low_below_stop_adr=describe(r['low_below_stop_adr'] for r in rows),
        future={str(h): dict(complete=describe(r['future'][str(h)]['from_exit'] for r in rows
            if r['future'][str(h)]['complete']),
            partial=sum(not r['future'][str(h)]['complete'] for r in rows),
            ge10=sum(r['future'][str(h)]['from_exit'] >= .1 for r in rows
                if r['future'][str(h)]['complete'])) for h in (5, 10, 20)})


def a0():
    frozen()
    assert not PREREG.exists(), 'A0 must precede preregistration'
    with strategy_only():
        A = P3.market()
        ordered = {str(d): A['ordered'].get(str(d), []) for d in A['days'][:-1]}
        internal = select_internal(ordered)
        saved = read(HOME / 'reports/s0_work/picks/IE9.json')
        assert all(codes == saved.get(day, []) for day, codes in internal.items())
        projected = allocation.nominations({t: internal[str(d)] for t, d in enumerate(A['days'][:-1])}, maximum=3)
        assert all(codes == internal[str(A['days'][t])] for t, codes in projected.items())
    trades = read(HOME / 'reports/p4_work/accounts/X1_OPEN/trades.json')
    attempts = read(HOME / 'reports/p4_work/accounts/X1_OPEN/attempts.json')
    triggers = read(HOME / 'reports/p4_work/accounts/X1_OPEN/triggers.json')
    diagnostic = read(HOME / 'reports/p4_work/accounts/X1_OPEN/funnel.json')
    legs = read(HOME / 'notes/legs_frozen.json')['legs']
    labelled_codes = {g['code'] for g in legs}
    stops = stop_rows(A, trades, labelled_codes)
    di = {str(d): t for t, d in enumerate(A['days'])}
    by_code, by_attempt, by_trigger = defaultdict(list), {}, {}
    for trade in trades:
        if trade['side'] > 0:
            by_code[trade['code']].append(trade)
    for row in attempts:
        by_attempt[(row['day'], row['code'])] = row
    for row in triggers:
        by_trigger[(row['day'], row['code'])] = row
    rules = read(HOME / 'reports/p4_work/accounts/X1_OPEN/summary.json')['rules']
    for rows in by_code.values():
        rows.sort(key=lambda t: t['entry'])
    events = []
    for stop in stops:
        code, exit_ = stop['code'], di[stop['exit']]
        next_trade = next((r for r in by_code[code] if r['entry'] > stop['exit']), None)
        last = di[next_trade['entry']] - 1 if next_trade else len(A['days']) - 2
        for t in range(exit_, last + 1):
            day, fill_day = str(A['days'][t]), str(A['days'][t + 1])
            raw = ordered.get(day, [])
            if code not in raw:
                continue
            cooling = any(code in internal.get(str(A['days'][s]), []) for s in range(max(0, t - 10), t))
            internal_pass = code in internal[day]
            selected = code in projected[t]
            trigger = by_trigger.get((fill_day, code))
            attempt = by_attempt.get((fill_day, code))
            reason = ('IE9_cooldown' if cooling else 'IE9_cap3' if not internal_pass else
                'S_cooldown' if not selected else 'invalid_stop' if trigger and trigger['reason'] != 'trigger' else
                'IDX50' if not attempt else attempt['reason'])
            keys = [g['key'] for g in legs if g['code'] == code and
                max(0, g['first'] - 3) <= exit_ < t + 1 < g['peak']]
            events.append(dict(stop_id=stop['id'], code=code, stopped=stop['exit'], night=day,
                fill_day=fill_day, raw_rank=raw.index(code) + 1, top3_without_cooldown=code in raw[:3],
                internal_cooling=cooling, internal_pass=internal_pass, S_pass=selected,
                reason=reason, legs=keys, trigger=trigger, attempt_reason=attempt['reason'] if attempt else None))
    reasons = {}
    for reason in ('IE9_cooldown', 'IE9_cap3', 'S_cooldown', 'same_code', 'no_rebuy_day',
                   'daily_long', 'daily_all', 'daily_kind', 'risk_or_gross', 'IDX50', 'invalid_stop', 'filled'):
        part = [r for r in events if r['reason'] == reason]
        reasons[reason] = dict(events=len(part), stopped_positions=len({r['stop_id'] for r in part}),
            legs=len({key for r in part for key in r['legs']}),
            top3_events=sum(r['top3_without_cooldown'] for r in part),
            top3_legs=len({key for r in part if r['top3_without_cooldown'] for key in r['legs']}))
    rapid = []
    for row in diagnostic['per_leg']:
        if row['layer'] != 8:
            continue
        trade = row['first_trade']
        stopped = next(r for r in stops if r['code'] == row['code'] and r['entry'] == trade['entry'])
        related = [r for r in events if r['stop_id'] == stopped['id'] and row['key'] in r['legs']]
        rapid.append(dict(key=row['key'], first=row['first'], peak=row['peak'], stop=stopped,
            blocker_counts=dict(Counter(r['reason'] for r in related)),
            raw_top3_nights=[r['night'] for r in related if r['top3_without_cooldown']], events=related))
    assert len(rapid) == 13
    grouped = {name: stop_statistics([r for r in stops if r['labelled'] == labelled])
               for name, labelled in (('48_leg_symbols', True), ('other_symbols', False))}
    summary = dict(timestamp=now(), stopped_longs=len(stops), groups=grouped, blockers=reasons,
        rapid_legs=len(rapid), rapid_day0=sum(r['stop']['day0'] for r in rapid),
        rapid_close_recovered=sum(r['stop']['close_recovered'] for r in rapid),
        account_rules={k: rules[k] for k in ('no_rebuy_day', 'max_open', 'max_new_long', 'max_new_all',
            'max_new_year', 'entry_episode_max', 'reentry_days')},
        source_replay_exact=True, S_projection_additional_suppression=0,
        convention='每个止损仓到下次实际首开之间的原始IE9夜晚；同票/同夜唯一，原因按实际流水线先后归属，段数不可相加')
    write('a0_stops.json.gz', stops)
    write('a0_blockers.json.gz', events)
    write('a0_rapid13.json', rapid)
    write('a0_summary.json', summary)
    lines = ['# P5 A0：先于预登记的只读诊断', '',
        '读取P4 X1_OPEN既有实盘式回放，不评测新候选。48段票指这些段的股票代码，全年同代码的止损都计入；其他票另列。', '',
        '| 分组 | 止损多单 | 入场日止损 | 距离/ADR中位 | 低点低于止损中位 | 收盘收回 | 后5/10/20日最高涨幅中位 |',
        '|---|---:|---:|---:|---:|---:|---:|']
    for name, r in grouped.items():
        lines.append(f"| {name} | {r['n']} | {r['day0']} | {r['stop_adr']['median']:.3f} | "
            f"{r['low_below_stop_pct']['median']:.2%} | {r['close_recovered']}/{r['n']} | "
            + '/'.join(f"{r['future'][str(h)]['complete']['median']:.2%}" for h in (5, 10, 20)) + ' |')
    lines += ['', '后续涨幅从实际止损成交价计，排除止损当天；主汇总只用完整5/10/20根有效日K。'
        '逐笔同时保留原止损价、实际成交价、原入场价三种分母及缺失/截尾。止损距离用前夜ADR，低点比较用实际有效止损线（加仓后为原买价）。', '',
        '| 原因 | 次数 | 涉及止损仓 | 48段数 | 原始前三次数 | 原始前三段数 |', '|---|---:|---:|---:|---:|---:|']
    for reason, r in reasons.items():
        lines.append('| ' + ' | '.join([reason] + [str(r[k]) for k in ('events', 'stopped_positions', 'legs', 'top3_events', 'top3_legs')]) + ' |')
    lines += ['', 'IE9内部先按前10晚冷却、再截3只；S投影也有10日冷却，但对已冷却的IE9输入新增阻挡0次，不能重复计数。'
        '账户no_rebuy_day=False，每日成功名额与同时持仓上限均未启用；同票仍有仓位时不能再首开，已平仓的次日可正常再买。'
        'P4每晚最多3名、每日offer上限4，因此X1的offer预截不另挡票。IDX50、无有效止损和总仓空间属于正常准入，保留。', '',
        '| 层8段 | 入场/止损 | 天数 | 距离/ADR | 低点穿线 | 收盘收回 | 后5/10/20日最高涨幅 | 后续原始前三夜数 |',
        '|---|---|---:|---:|---:|---|---|---:|']
    for r in rapid:
        s = r['stop']
        lines.append(f"| {r['key']} | {s['entry']}/{s['exit']} | {s['days']} | {s['stop_adr']:.3f} | "
            f"{s['low_below_stop_pct']:.2%} | {s['close_recovered']} | "
            + '/'.join(f"{s['future'][str(h)]['from_exit']:.2%}" if s['future'][str(h)]['from_exit'] is not None
                       else '缺失' for h in (5, 10, 20)) + f" | {len(r['raw_top3_nights'])} |")
    lines += ['', f"13段中{summary['rapid_day0']}段入场当天止损、{summary['rapid_close_recovered']}段当天收盘收回。",
        '逐笔止损、完整逐夜原因和13段明细保存在a0_stops.json.gz、a0_blockers.json.gz、a0_rapid13.json。']
    (OUT / 'A0_CN.md').write_text('\n'.join(lines) + '\n')
    log('A0', '只读诊断完成，尚未写预登记', 'a0_summary.json', grouped)
    print('A0', P3.clean(summary), flush=True)


def preregister():
    protocol = frozen()
    assert PREREG.exists() and (OUT / 'A0_CN.md').exists()
    assert not (OUT / 'train').exists() and not (OUT / 'regimes').exists()
    engine = ROOT / 'studies/trader_replication/system.py'
    write('preregistered.json', dict(timestamp=now(), prereg_sha256=P3.sha(PREREG),
        a0_sha256=P3.sha(OUT / 'a0_summary.json'), a0_report_sha256=P3.sha(OUT / 'A0_CN.md'),
        strategy_sha256=P3.sha(HOME / 'p5_policy.py'), engine_sha256=P3.sha(engine),
        engine_before_sha256=protocol['protected'][str(engine.relative_to(ROOT))],
        engine_change='default-off entry_close_stops; opening session included in five-session window',
        candidates=list(S.CANDIDATES) + list(S.REGIMES), count=5, layer='signal+trade', paired=True,
        selection_metric='worst 2024/2025 peak-eve holding coverage', returns='veto only for A',
        selection_years=YEARS[:2], holdout='2026 historical holdout*',
        raw_signal_sha256=P3.sha(HOME / 'reports/p2a_work/market/IE9_order.json')))
    log('preregister', 'A0后冻结5个候选、止损首日执行与跨年段上下界选择', 'preregistered.json', 'frozen')
    print('P5 preregistration frozen', P3.sha(PREREG), flush=True)


def strategy_inputs():
    from . import replicate as MR
    short_rows = read(HOME / 'reports/d1_work/master_short_entries.json')
    with strategy_only():
        A = P3.market()
        metadata, rules, spool = P3.account_inputs(A)
        B = P4.books(A, short_rows)
        index_ok = MR.ew_index_up(A, P3.array(HOME / 'reports/d1_work/master_liquidity.npy'), 50)
        assert all([e for e in row if index_ok[d]] == B['filtered'][d] for d, row in enumerate(B['raw']))
        manifest = read(OUT / 'preregistered.json')
        assert P3.sha(HOME / 'p5_policy.py') == manifest['strategy_sha256']
        assert P3.sha(ROOT / 'studies/trader_replication/system.py') == manifest['engine_sha256']
        assert P3.sha(HOME / 'reports/p2a_work/market/IE9_order.json') == manifest['raw_signal_sha256']
    return A, metadata, rules, spool, B, index_ok


def simulate(A, rules, book, end, *, soft=False):
    attempts, daily = P4.Observations(), P4.Observations(daily=True)
    curve, days, trades = Y.simulate(P3.px(A),
        {k: A[k] for k in ('e9', 'e21', 'idx_pb16', 'p5_risk') if k in A},
        rules, book, '2024-01-02', end, audit=True,
        track=dict(entry_attempts=attempts, gross=daily), entry_close_stops=soft)
    return dict(curve=dict(days=list(days), equity=curve), trades=trades,
                attempts=list(attempts), daily=daily.states)


def run_candidate(A, rules, B, index_ok, name, end, *, states=None, new_shorts=None):
    with strategy_only():
        soft = name in ('S2_CLOSESTOP', 'S3_BOTH')
        picks = S.nominations(A, name)
        entries = S.entries(A, picks, index_ok, soft=soft, use_index=states is None)
        longs, shorts = entries['offered'], B['short_entries']
        changes = dict(intraday_kinds=tuple(rules.intraday_kinds) + P4S.KINDS,
            close_stop_days=5 if soft else 0, hard_stop_mult=2.,
            no_rebuy_day=True if name != 'S2_CLOSESTOP' else rules.no_rebuy_day)
        if states is not None:
            longs = [row if states[d] != P3.R.WEAK else [] for d, row in enumerate(longs)]
            shorts = [row if states[d] == P3.R.WEAK else [] for d, row in enumerate(new_shorts)]
            A['p5_risk'] = np.where(states == P3.R.UP, 1.6, 1.)
            changes['risk_scale'] = 'p5_risk'
        policy = replace(rules, **changes)
        offered = P4.combined(longs, shorts)
        record = simulate(A, policy, offered, end, soft=soft)
    return record, policy, picks, entries, offered


def coverage(A, record, rules, legs):
    result = P3.actual_coverage(record['trades'], rules, legs, A)
    last = record['curve']['days'][-1]
    di = {str(d): t for t, d in enumerate(A['days'])}
    for g, row in zip(legs, result['per_leg']):
        eve = str(A['days'][g['peak'] - 1])
        row['peak_eve'] = eve
        row['peak_held'] = None
        row['peak_shares'] = None
        if eve <= last:
            shares = 0.
            for trade in record['trades']:
                if trade['side'] < 0 or trade['code'] != g['code'] or trade['entry'] > eve:
                    continue
                for e in trade['executions']:
                    if e['time'] <= eve and e['action'] != 'end':
                        shares += e['shares'] * (1 if e['action'] in ('entry', 'add') else -1)
            row['peak_shares'] = max(0., shares)
            row['peak_held'] = shares > 1e-10
        # A first late fill cannot be made early by a future new position.
        row['early_unknown'] = not row['any'] and g['peak'] > di[last] + 1
    for y, row in result['annual'].items():
        part = [r for r in result['per_leg'] if r['year'] == y]
        row.update(peak_held=sum(r['peak_held'] is True for r in part),
            peak_unknown=sum(r['peak_held'] is None for r in part),
            early_unknown=sum(r['early_unknown'] for r in part),
            capture_median=describe(r['capture_total'] if r['capture_total'] is not None else 0. for r in part),
            capture_funded_median=describe(r['capture_total'] for r in part))
    result['peak_held'] = sum(r['peak_held'] is True for r in result['per_leg'])
    result['capture_median'] = describe(r['capture_total'] if r['capture_total'] is not None else 0.
        for r in result['per_leg'])
    return result


def rebuys(trades, calendar):
    by_code, rows = defaultdict(list), []
    di = {str(d): t for t, d in enumerate(calendar)}
    for trade in trades:
        if trade['side'] > 0:
            by_code[trade['code']].append(trade)
    for code, part in by_code.items():
        part.sort(key=lambda t: t['entry'])
        for before, trade in zip(part, part[1:]):
            if before['why'] in STOPS and trade['entry'] > before['exit']:
                rows.append(dict(code=code, stopped=before['exit'], entry=trade['entry'],
                    exit=trade['exit'], why=trade['why'], pnl=trade['pnl'], ret=trade['ret'],
                    days=trade['days'], sessions_since_stop=di[trade['entry']] - di[before['exit']],
                    previous_entry=before['entry']))
    def stats(part):
        closed = [r for r in part if r['why'] != 'end']
        return dict(n=len(part), closed=len(closed), pnl=sum(r['pnl'] for r in part),
            win=sum(r['ret'] > 0 for r in closed) / len(closed) if closed else None,
            return_stats=describe(r['ret'] for r in closed))
    return dict(total=stats(rows), annual={y: stats([r for r in rows if r['entry'].startswith(y)]) for y in YEARS}, rows=rows)


def summary(A, record, rules, legs):
    return dict(P4.summarize(record), holding_coverage=coverage(A, record, rules, legs),
                rebuys=rebuys(record['trades'], A['days']), rules=asdict(rules))


def save_account(folder, record):
    for key, value in record.items():
        write(f'{folder}/{key}.json.gz', value)


def selection_key(name, results, peak_extra=0, early_extra=0):
    row = results[name]
    cov = row['holding_coverage']['annual']
    return (-min((cov[y]['peak_held'] + (peak_extra if y == '2025' else 0)) / cov[y]['n'] for y in YEARS[:2]),
        -min((cov[y]['covered'] + (early_extra if y == '2025' else 0)) / cov[y]['n'] for y in YEARS[:2]),
        sum(row['annual'][y]['n'] for y in YEARS[:2]), S.CANDIDATES.index(name))


def train():
    frozen(True)
    write('training_started.json', dict(timestamp=now(), prereg_sha256=P3.sha(PREREG)))
    A, _, rules, _, B, index_ok = strategy_inputs()
    legs = [g for g in read(HOME / 'notes/legs_frozen.json')['legs']
            if str(A['days'][g['first']])[:4] in YEARS[:2]]
    results = {}
    for name in S.CANDIDATES:
        record, policy, picks, _, _ = run_candidate(A, rules, B, index_ok, name, '2025-12-31')
        result = summary(A, record, policy, legs)
        save_account(f'train/{name}', record)
        write(f'train/{name}/summary.json', result)
        results[name] = result
        print('train', name, {y: dict(early=result['holding_coverage']['annual'][y]['covered'],
            peak=result['holding_coverage']['annual'][y]['peak_held'],
            unknown=result['holding_coverage']['annual'][y]['peak_unknown'], ret=result['annual'][y]['ret'])
            for y in YEARS[:2]}, flush=True)
        del record
        gc.collect()
    eligible = [n for n in S.CANDIDATES if all(results[n]['annual'][y]['ret'] >= 0 for y in YEARS[:2])]
    all_failed = not eligible
    eligible = eligible or list(S.CANDIDATES)
    choices = {}
    for name in eligible:
        cov = results[name]['holding_coverage']['annual']
        assert cov['2024']['peak_unknown'] == cov['2024']['early_unknown'] == 0
        choices[name] = sorted(set(selection_key(name, results, p, e)
            for p in range(cov['2025']['peak_unknown'] + 1)
            for e in range(cov['2025']['early_unknown'] + 1)))
    winners = Counter()
    for combination in itertools.product(*(choices[n] for n in eligible)):
        winners[min(zip(eligible, combination), key=lambda item: item[1])[0]] += 1
    proof = dict(possible_keys=choices, winners=dict(winners),
        combinations=sum(winners.values()), unknowns={n: results[n]['holding_coverage']['annual']['2025'] for n in eligible},
        horizon='2025-12-31', used_2026_candidate_execution=False)
    write('cross_year_selection_bounds.json', proof)
    assert len(winners) == 1, 'cross-year selection unresolved; no 2026 candidate evaluation permitted'
    chosen = next(iter(winners))
    write('chosen_a.json', dict(chosen=chosen, eligible=eligible, all_failed_return_floor=all_failed,
        keys={n: selection_key(n, results) for n in S.CANDIDATES}, cross_year_choice_invariant=True,
        bounds_sha256=P3.sha(OUT / 'cross_year_selection_bounds.json'), timestamp=now(), used_2026=False,
        summary_sha256={n: P3.sha(OUT / f'train/{n}/summary.json') for n in S.CANDIDATES},
        prereg_sha256=P3.sha(PREREG)))
    log('A selection', '2024/25选择；跨年段所有上下界组合首选相同，未运行2026候选', 'chosen_a.json', chosen)
    print('chosen A before 2026', chosen, 'bounds combinations', sum(winners.values()), flush=True)


def funnel(A, record, rules, picks, entries, offered, legs):
    result = P4.funnel(A, record, rules, picks, entries['raw'], entries['filtered'], offered, legs)
    return split_funnel(result, record['trades'])


def split_funnel(result, trades):
    for row in result['per_leg']:
        first = row['first_trade']
        rapid = bool(first and row['coverage']['covered'] and first['why'] in STOPS and first['days'] <= 3)
        again = bool(rapid and any(t['side'] > 0 and t['code'] == row['code'] and
            first['exit'] < t['entry'] < row['peak'] for t in trades))
        row['rapid_stop'] = rapid
        row['returned_after_rapid_stop'] = again
        if rapid:
            row['layer'] = 8
            row['layer_name'] = '早买后很快止损又买回' if again else '早买后很快止损未买回'
    for y, values in result['annual'].items():
        part = [r for r in result['per_leg'] if r['year'] == y]
        values['layers'] = {str(k): sum(r['layer'] == k for r in part) for k in range(1, 10)}
        values['layer8_returned'] = sum(r['rapid_stop'] and r['returned_after_rapid_stop'] for r in part)
        values['layer8_no_return'] = sum(r['rapid_stop'] and not r['returned_after_rapid_stop'] for r in part)
        assert values['layers']['8'] + values['layers']['9'] == values['early']
    result['layers'] = {str(k): sum(r['layer'] == k for r in result['per_leg']) for k in range(1, 10)}
    result['convention'] = '8R+8N+9=早买；8R为首早买3日内止损、峰前又正常入场'
    return result


def validate():
    frozen(True)
    chosen = read(OUT / 'chosen_a.json')
    write('holdout_started.json', dict(timestamp=now(), chosen_a_sha256=P3.sha(OUT / 'chosen_a.json')))
    A, _, rules, _, B, index_ok = strategy_inputs()
    legs = read(HOME / 'notes/legs_frozen.json')['legs']
    from studies.trader_replication import ledger
    public = ledger.load(HOME / 'notes/trades.csv')
    replay = {}
    # Defaults must preserve complete old ledgers and equity, including 2026.
    for name, book, destination in (
            ('master', B['book'], HOME / 'reports/d1_work'),
            ('X1_OPEN', P4.combined(P4S.entries(A, P4.project(A,
                read(HOME / 'reports/s0_work/picks/IE9.json')), 'X1_OPEN', B['raw'], index_ok)['offered'],
                B['short_entries']), HOME / 'reports/p4_work/accounts/X1_OPEN')):
        policy = replace(rules, intraday_kinds=tuple(rules.intraday_kinds) + P4S.KINDS) if name == 'X1_OPEN' else rules
        with strategy_only():
            record = simulate(A, policy, book, '2026-10-16')
        old_curve = read(destination / ('master_curve.json' if name == 'master' else 'curve.json'))
        old_trades = read(destination / ('master_trades.json' if name == 'master' else 'trades.json'))
        assert P3.clean(record['curve']) == old_curve and P3.clean(record['trades']) == old_trades, name
        replay[name] = dict(curve_exact=True, ledger_exact=True)
        write(f'controls/{name}/summary.json', summary(A, record, policy, legs))
        del record
        gc.collect()
    write('control_replay.json', replay)
    for name in S.CANDIDATES:
        record, policy, picks, entries, offered = run_candidate(A, rules, B, index_ok, name, '2026-10-16')
        training = read(OUT / f'train/{name}/curve.json')
        assert list(record['curve']['equity'][:len(training['days'])]) == training['equity']
        result = summary(A, record, policy, legs)
        result.update(short_coverage=P3.short_coverage(record['trades'], public, A),
            training_curve_prefix_exact=True, selected=chosen['chosen'] == name)
        save_account(f'accounts/{name}', record)
        write(f'accounts/{name}/summary.json', result)
        diagnostic = funnel(A, record, policy, picks, entries, offered, legs)
        write(f'accounts/{name}/funnel.json.gz', diagnostic)
        write(f'accounts/{name}/nominations.json.gz', {str(A['days'][t]): cs for t, cs in picks.items()})
        with strategy_only():
            scored_picks = allocation.nominations(picks, maximum=3, cooldown=10)
        ci = {str(c): j for j, c in enumerate(A['codes'])}
        scores = mainleg.signal_coverage_budget(picks, None, legs, list(A['days']),
            {g['code']: A['open'][:, ci[g['code']]] for g in legs}, 3)
        assert scores['picks'] == scored_picks
        scores.pop('picks')
        write(f'accounts/{name}/S_coverage.json', scores)
        print('holdout', name, {y: (result['holding_coverage']['annual'][y]['covered'],
            result['holding_coverage']['annual'][y]['peak_held'], result['annual'][y]['ret']) for y in YEARS}, flush=True)
        del record, diagnostic
        gc.collect()
    full = {n: read(OUT / f'accounts/{n}/summary.json') for n in S.CANDIDATES}
    full_keys = {n: selection_key(n, full) for n in chosen['eligible']}
    assert min(full_keys, key=full_keys.get) == chosen['chosen']
    write('selection_reconciliation.json', dict(chosen=chosen['chosen'], full_keys=full_keys,
        cross_year_bounds_confirmed=True, selection_unchanged=True))
    log('A holdout', '2026一次评测、训练权益前缀完全一致、旧master/X1逐位复放', 'selection_reconciliation.json', chosen['chosen'])


def view_until(A, n):
    return {k: v[:n] if isinstance(v, np.ndarray) and k != 'codes' else v for k, v in A.items()}


def regime_record(A, picks, name):
    width = S.breadth(A)
    base = S.timeline(A, picks, width['state'], name)
    mask = A['days'] >= '2024-01-02'
    variants = []
    for label, change in S.perturbations():
        w = width if set(change) == {'feedback'} else S.breadth(A, change)
        other = S.timeline(A, picks, w['state'], name, change.get('feedback', .5))
        a, b = base['label'][mask], other['label'][mask]
        variants.append(dict(variant=label, agreement=float(np.mean(a == b)),
            annual={y: float(np.mean((a == b)[np.char.startswith(A['days'][mask], y)]))
                    for y in YEARS if np.any(np.char.startswith(A['days'][mask], y))},
            label=other['label'][mask]))
        print(name, label, round(variants[-1]['agreement'], 6), flush=True)
    prefixes = []
    cuts = ('2024-06-28', '2024-12-31', '2025-06-30', '2025-12-31')
    if str(A['days'][-1]) > '2025-12-31':
        cuts += ('2026-06-30', '2026-10-16')
    for cut in cuts:
        n = int(np.searchsorted(A['days'], cut, side='right'))
        shortA = view_until(A, n)
        w = S.breadth(shortA)
        short = S.timeline(shortA, {t: cs for t, cs in picks.items() if t < n - 1}, w['state'], name)
        assert all(np.array_equal(v, width[k][:n], equal_nan=True) for k, v in w.items())
        assert all(np.array_equal(short[k], base[k][:n]) for k in ('label', 'raw', 'feedback'))
        assert short['outcomes'] == base['outcomes'][:n]
        prefixes.append(dict(cut=cut, width=True, feedback=True, final_state=True))
    assert all(r['latest_known'] is None or r['latest_known'] < r['day'] for r in base['outcomes'])
    for t in range(1, len(base['label'])):
        if base['label'][t] != base['label'][t - 1]:
            assert t >= 2 and np.all(base['raw'][t - 2:t + 1] == base['label'][t])
    minimum = min(r['agreement'] for r in variants)
    return dict(P3.state_record(base, A), full_label=base['label'], raw=base['raw'],
        feedback=base['feedback'], outcomes=base['outcomes'], width=width,
        stability=dict(minimum=minimum, worst=min(variants, key=lambda r: r['agreement'])['variant'],
            variants=variants, ok=minimum >= .9),
        lookahead=dict(ok=True, prefixes=prefixes, latest_feedback_before_session=True,
                       final_state_three_day_confirmation=True))


def regimes():
    frozen(True)
    selected_a = read(OUT / 'chosen_a.json')['chosen']
    write('regimes_started.json', dict(timestamp=now(), chosen_a=selected_a))
    with strategy_only():
        A = P3.market()
        n = int(np.searchsorted(A['days'], '2025-12-31', side='right'))
        A = view_until(A, n)
        picks = S.nominations(A, selected_a)
        definitions = {}
        for name in S.REGIMES:
            definitions[name] = regime_record(A, picks, name)
            write(f'regimes/train/{name}.json', definitions[name])
    # Only this fixed control curve is allowed to enter the B selector.
    original = read(HOME / 'reports/p4_work/accounts/X1_OPEN/curve.json')
    original = {k: [v for day, v in zip(original['days'], values) if day <= '2025-12-31']
                for k, values in original.items()}
    scores = {}
    for name, row in definitions.items():
        description = P3.curve_description(original, row)
        annual = {y: description['annual'][y]['up']['ret'] - description['annual'][y]['weak']['ret'] for y in YEARS[:2]}
        scores[name] = dict(worst_year=min(annual.values()), annual=annual,
            X1_state_returns=description, minimum=row['stability']['minimum'])
    eligible = [n for n in S.REGIMES if definitions[n]['stability']['ok'] and definitions[n]['lookahead']['ok']]
    chosen = min(eligible, key=lambda n: (-scores[n]['worst_year'], S.REGIMES.index(n))) if eligible else None
    write('chosen_b.json', dict(chosen=chosen, enabled=bool(eligible), eligible=eligible,
        scores=scores, threshold=.9, used_accounts=['X1_OPEN'], used_public_trader=False,
        used_2026=False, post_hoc_revision=True, timestamp=now(), prereg_sha256=P3.sha(PREREG),
        definition_sha256={n: P3.sha(OUT / f'regimes/train/{n}.json') for n in S.REGIMES}))
    log('B selection', '先过90%稳定及截断，再比X1两年较差进攻减防守收益；事后修订', 'chosen_b.json', chosen)
    print('chosen B before 2026', chosen, scores, flush=True)


def regime_holdout():
    frozen(True)
    selected = read(OUT / 'chosen_b.json')
    chosen_a = read(OUT / 'chosen_a.json')['chosen']
    write('regime_holdout_started.json', dict(timestamp=now(), chosen_b_sha256=P3.sha(OUT / 'chosen_b.json')))
    with strategy_only():
        A = P3.market()
        picks = S.nominations(A, chosen_a)
        definitions = {}
        for name in S.REGIMES:
            row = regime_record(A, picks, name)
            training = read(OUT / f'regimes/train/{name}.json')
            n = len(training['full_label'])
            assert row['full_label'][:n].tolist() == training['full_label']
            for key in row['width']:
                assert np.array_equal(row['width'][key][:n], np.array(training['width'][key], float), equal_nan=True)
            row['training_prefix_exact'] = True
            write(f'regimes/{name}.json', row)
            definitions[name] = row
        n = int(np.searchsorted(A['days'], '2026-06-30', side='right'))
        changed = dict(A)
        for key in ('close', 'low', 'to20', 'adr'):
            changed[key] = np.array(A[key], copy=True)
            changed[key][n:] *= 10 if key in ('close', 'low') else .01
        future_picks = {t: cs if t < n else [] for t, cs in picks.items()}
        width = S.breadth(changed)
        for name in S.REGIMES:
            other = S.timeline(changed, future_picks, width['state'], name)
            assert np.array_equal(other['label'][:n], definitions[name]['full_label'][:n])
            assert other['outcomes'][:n] == definitions[name]['outcomes'][:n]
        write('regime_future_perturbation.json', dict(ok=True, cut='2026-06-30',
            changed=['future prices', 'future liquidity', 'future ADR', 'future nominations']))
        lines = ['day,' + ','.join(f'{name}_{k}' for name in S.REGIMES for k in ('state', 'W', 'F', 'rate'))]
        for t, day in enumerate(A['days']):
            if not '2026-07-01' <= day <= '2026-08-31':
                continue
            cells = [str(day)]
            for name, row in definitions.items():
                cells += [P3.R.NAMES[int(row['full_label'][t])], str(row['width']['state'][t]),
                    str(row['feedback'][t]), str(row['outcomes'][t]['rate'])]
            lines.append(','.join(cells))
        (OUT / 'july_august_states.csv').write_text('\n'.join(lines) + '\n')
    assert selected == read(OUT / 'chosen_b.json')
    log('B holdout', '2026定义及扰动只作报告，不重选；训练前缀、未来扰动一致', 'regimes/', 'complete')


def behaviour():
    frozen(True)
    selected = read(OUT / 'chosen_b.json')
    public = read(HOME / 'reports/p3_work/G2.json')
    from studies.trader_replication import ledger
    trades = ledger.load(HOME / 'notes/trades.csv')
    A = P3.market()
    days = list(map(str, A['days']))
    start = int(np.searchsorted(days, '2024-01-02'))
    dated, excluded = [], []
    for trade in trades:
        if not trade.dated:
            continue
        t = int(np.searchsorted(days, trade.entry_date))
        if t < start or t >= len(days):
            excluded.append(dict(id=trade.id, date=trade.entry_date, reason='outside frozen calendar'))
            continue
        dated.append(dict(id=trade.id, date=trade.entry_date, day=t - start,
            value=float(trade.side == 'short'), precision=trade.precision))
    portraits = public['first_anchor_portraits']
    curves = dict(master=read(HOME / 'reports/d1_work/master_curve.json'),
        M3B=read(HOME / 'reports/m3_work/validation/continuous/curve.json'),
        X1_OPEN=read(HOME / 'reports/p4_work/accounts/X1_OPEN/curve.json'))
    train = read(HOME / 'reports/m3_work/candidates/M3B/curve.json')
    assert curves['M3B']['equity'][:len(train['equity'])] == train['equity']
    results = {}
    for name in S.REGIMES:
        labels = read(OUT / f'regimes/{name}.json')
        scopes = {}
        for scope in ('2026', 'pooled'):
            direction = [r for r in dated if scope == 'pooled' or r['date'].startswith(scope)]
            tiers = [r for r in portraits if scope == 'pooled' or r['first'].startswith(scope)]
            metrics = dict(direction=direction,
                turnover=[dict(day=r['day'], value=r['percentiles']['to20']) for r in tiers if r['percentiles']['to20'] is not None],
                adr=[dict(day=r['day'], value=r['percentiles']['adr']) for r in tiers if r['percentiles']['adr'] is not None])
            scopes[scope] = dict(metrics={k: P3.metric_test(labels, v) for k, v in metrics.items()},
                exact_direction=P3.metric_test(labels, [r for r in direction if r['precision'] == 'exact']),
                correlations={k: P3.correlations(v, labels) for k, v in metrics.items() if k != 'direction'})
        results[name] = dict(scopes=scopes,
            old_accounts={n: P3.curve_description(curve, labels) for n, curve in curves.items()})
    write('G2.json', dict(chosen=selected['chosen'], enabled=selected['enabled'], definitions=results,
        first_anchor_portraits=portraits, missing_portraits=public['missing_portraits'],
        excluded=excluded, window_only=public['window_only'], dated_counts=dict(Counter(r['date'][:4] for r in dated)),
        density_test=False, note='B事后修订；只用X1的2024/25收益选择；G2不入选择；按年留一为固定曲线分解'))
    log('G2', '两个定义、三个旧账户、方向与票档逐段留一全部报告', 'G2.json', 'complete')
    print('G2 completed', {n: P3.g2_conclusion(r['scopes']) for n, r in results.items()}, flush=True)


def baccount():
    frozen(True)
    chosen_b, chosen_a = read(OUT / 'chosen_b.json'), read(OUT / 'chosen_a.json')
    if not chosen_b['enabled']:
        write('paired_not_enabled.json', dict(reason='neither definition passes training stability and prefix criteria'))
        print('paired account not enabled', flush=True)
        return
    write('paired_started.json', dict(timestamp=now(), chosen_a_sha256=P3.sha(OUT / 'chosen_a.json'),
                                    chosen_b_sha256=P3.sha(OUT / 'chosen_b.json')))
    A, metadata, rules, spool, B, index_ok = strategy_inputs()
    with strategy_only():
        original = P3.OUT
        try:
            P3.OUT = OUT
            new_shorts = P3.paired_shorts(A, spool, metadata['config']['short'])
        finally:
            P3.OUT = original
        states = np.array(read(OUT / f"regimes/{chosen_b['chosen']}.json")['full_label'])
    record, policy, picks, entries, offered = run_candidate(A, rules, B, index_ok,
        chosen_a['chosen'], '2026-10-16', states=states, new_shorts=new_shorts)
    legs = read(HOME / 'notes/legs_frozen.json')['legs']
    from studies.trader_replication import ledger
    public = ledger.load(HOME / 'notes/trades.csv')
    result = summary(A, record, policy, legs)
    result.update(short_coverage=P3.short_coverage(record['trades'], public, A),
        selected_a=chosen_a['chosen'], selected_b=chosen_b['chosen'], used_for_selection=False)
    save_account('paired', record)
    write('paired/summary.json', result)
    diagnostic = funnel(A, record, policy, picks, dict(entries, filtered=entries['raw']), offered, legs)
    write('paired/funnel.json.gz', diagnostic)
    log('paired', '只报告成对应用，不改变A/B选择', 'paired/summary.json', result['annual'])
    print('paired', {y: (result['holding_coverage']['annual'][y]['covered'],
        result['holding_coverage']['annual'][y]['peak_held'], result['annual'][y]['ret']) for y in YEARS},
        'short', result['short_coverage']['covered'], flush=True)


def comparisons():
    frozen(True)
    systems = {n: read(OUT / f'accounts/{n}/summary.json') for n in S.CANDIDATES}
    systems['X1_OPEN'] = read(OUT / 'controls/X1_OPEN/summary.json')
    rapid = read(OUT / 'a0_rapid13.json')
    rapid_keys = {r['key'] for r in rapid}
    pairs = (('S1_NOBLOCK', 'X1_OPEN'), ('S2_CLOSESTOP', 'X1_OPEN'), ('S3_BOTH', 'X1_OPEN'),
             ('S3_BOTH', 'S1_NOBLOCK'), ('S3_BOTH', 'S2_CLOSESTOP'))
    effects = {}
    for name, base in pairs:
        current = {r['key']: r for r in systems[name]['holding_coverage']['per_leg']}
        previous = {r['key']: r for r in systems[base]['holding_coverage']['per_leg']}
        years = {}
        for y in (*YEARS, 'all'):
            keys = [k for k, v in current.items() if y == 'all' or v['year'] == y]
            changes = {}
            for field in ('covered', 'peak_held'):
                gained = [k for k in keys if current[k][field] and not previous[k][field]]
                lost = [k for k in keys if previous[k][field] and not current[k][field]]
                changes[field] = dict(gained=gained, lost=lost, net=len(gained) - len(lost))
            years[y] = changes
        effects[f'{name}_vs_{base}'] = years
    recovery = {name: dict(peak_held=[r['key'] for r in summary['holding_coverage']['per_leg']
                    if r['key'] in rapid_keys and r['peak_held']],
                early=[r['key'] for r in summary['holding_coverage']['per_leg'] if r['key'] in rapid_keys and r['covered']])
                for name, summary in systems.items()}
    write('effects.json', dict(comparisons=effects, original_rapid13=recovery,
        note='补回与丢失同时报告；交互效应不能相加，不把原生排序变化全部归因于再次入场'))
    A = P3.market()
    ci = {str(c): j for j, c in enumerate(A['codes'])}
    di = {str(d): t for t, d in enumerate(A['days'])}
    selected_a = read(OUT / 'chosen_a.json')['chosen']
    selected_b = read(OUT / 'chosen_b.json')
    portraits = {}
    for name in (*S.CANDIDATES, 'master', 'X1_OPEN', *(['paired'] if selected_b['enabled'] else [])):
        if name == 'master':
            daily = read(HOME / 'reports/p4_work/a1/master/daily.json')
            curve = read(HOME / 'reports/d1_work/master_curve.json')
            trades = read(HOME / 'reports/d1_work/master_trades.json')
        else:
            folder = (HOME / 'reports/p4_work/accounts/X1_OPEN') if name == 'X1_OPEN' else (
                OUT / ('paired' if name == 'paired' else f'accounts/{name}'))
            daily, curve, trades = (read(folder / f'{k}.json') for k in ('daily', 'curve', 'trades'))
        equity = dict(zip(curve['days'], curve['equity']))
        days = []
        for row in daily:
            values = [p['shares'] * float(A['close'][di[row['day']], ci[p['code']]])
                      for p in row['positions'] if p['side'] > 0]
            days.append(dict(day=row['day'], longs=len(values),
                largest=max(values, default=0.) / equity[row['day']],
                top4=sum(sorted(values, reverse=True)[:4]) / sum(values) if values else None))
        repeat = rebuys(trades, A['days'])
        within10 = [r for r in repeat['rows'] if r['sessions_since_stop'] <= 10]
        portraits[name] = dict(annual={y: dict(
            long_count=describe(r['longs'] for r in days if r['day'].startswith(y)),
            largest_fraction=describe(r['largest'] for r in days if r['day'].startswith(y)),
            top4_share=describe(r['top4'] for r in days if r['day'].startswith(y)),
            rebuy_within10=sum(r['entry'].startswith(y) for r in within10),
            stopped_within5=sum(t['entry'].startswith(y) and t['side'] > 0 and t['why'] in STOPS and t['days'] <= 5 for t in trades))
            for y in YEARS}, rebuys=repeat, rebuy_within10=len(within10))
    write('behaviour.json', dict(accounts=portraits, selected_a=selected_a,
        note='收盘股数×当日收盘价/实际账户权益；再入盈亏为连续账户初始权益单位，不是独立收益率'))
    log('effects', '分开记录补回、丢失和两处改动的交互', 'effects.json', recovery)
    print('peak coverage effects', {n: v['all']['peak_held'] for n, v in effects.items()}, flush=True)


def audit():
    frozen(True)
    from studies.trader_replication import gate
    A, _, rules, _, B, index_ok = strategy_inputs()
    selected = read(OUT / 'chosen_b.json')
    names = list(S.CANDIDATES) + (['paired'] if selected['enabled'] else [])
    checks = {}
    for name in names:
        folder = 'paired' if name == 'paired' else f'accounts/{name}'
        trades = read(OUT / f'{folder}/trades.json')
        fills = gate.check_fills(A, trades)
        assert fills['ok'], (name, fills)
        summary_row = read(OUT / f'{folder}/summary.json')
        daily = {r['day']: r for r in read(OUT / f'{folder}/daily.json')}
        for row in summary_row['holding_coverage']['per_leg']:
            actual = any(p['code'] == row['code'] and p['side'] > 0 and p['shares'] > 1e-10
                         for p in daily[row['peak_eve']]['positions'])
            assert actual == row['peak_held'], (name, row['key'])
        checks[name] = dict(fills=fills, win=gate.check_win(trades),
            peak_eve_inventory_independently_reconciled=True,
            new_longs=len([r for r in trades if r['side'] > 0]))
    for name in ('master', 'X1_OPEN'):
        folder = HOME / ('reports/p4_work/a1/master' if name == 'master' else 'reports/p4_work/accounts/X1_OPEN')
        diagnostic = split_funnel(read(folder / 'funnel.json'), read(folder / 'trades.json'))
        write(f'controls/{name}/funnel.json.gz', diagnostic)
    with strategy_only():
        old = P4.project(A, read(HOME / 'reports/s0_work/picks/IE9.json'))
        assert old == S.nominations(A, 'S2_CLOSESTOP')
        for name in S.CANDIDATES:
            picks = S.nominations(A, name)
            soft = name != 'S1_NOBLOCK'
            full = S.entries(A, picks, index_ok, soft=soft)
            prefixes = []
            for cut in ('2024-09-30', '2025-12-31', '2026-06-30'):
                n = int(np.searchsorted(A['days'], cut, side='right'))
                smallA = view_until(A, n)
                small_picks = S.nominations(smallA, name)
                assert small_picks == {t: cs for t, cs in picks.items() if t < n - 1}
                short = S.entries(smallA, small_picks, index_ok[:n], soft=soft)
                for key in ('raw', 'filtered', 'offered'):
                    assert short[key] == full[key][:n], (name, key, cut)
                prefixes.append(dict(cut=cut, nominations=True, entry_quotes=True))
            checks[name]['prefixes'] = prefixes
    # Prove the only shared-code edit is the declared default-off execution option.
    engine = ROOT / 'studies/trader_replication/system.py'
    current = engine.read_text()
    before = current
    replacements = [
        ('daily_tolerance=None, entry_close_stops=False):', 'daily_tolerance=None):'),
        ("    entry_close_stops: count an opening entry's session as the first close-stop session; ordinary\n"
         '    day-zero management stays disabled except for its hard stop and close stop.\n', ''),
        ("    if entry_close_stops and (not rules.close_stop_days or preopen or rules.probe_hard_mult):\n"
         "        raise ValueError('entry close stops require ordinary close-stop management')\n", ''),
        ("        age = session[d] - session[q.d0]\n"
         '        within = 0 <= age < rules.close_stop_days if entry_close_stops else 0 < age <= rules.close_stop_days\n'
         '        return bool(rules.close_stop_days) and q.side > 0 and within',
         '        return bool(rules.close_stop_days) and q.side > 0 and 0 < session[d] - session[q.d0] <= rules.close_stop_days'),
        ("            if entry_close_stops and side > 0 and len(e) > 6 and e[6] is not None:\n"
         "                raise ValueError('entry close stops must not carry a precomputed day-zero exit')\n", ''),
        ("            if q.d0 == d and entry_close_stops and s > 0:\n"
         '                hard = live_stop(q, d)\n'
         '                if l[d, j] <= hard:\n'
         "                    close_part(q, q.size, hard, d, 'stop_day0')\n"
         '                elif c[d, j] < q.stop:\n'
         "                    close_part(q, q.size, c[d, j], d, 'close_stop')\n"
         '                continue\n', '')]
    for new, old in replacements:
        assert before.count(new) == 1
        before = before.replace(new, old, 1)
    manifest = read(OUT / 'preregistered.json')
    assert hashlib.sha256(before.encode()).hexdigest() == manifest['engine_before_sha256']
    import difflib
    (OUT / 'engine_delta.patch').write_text(''.join(difflib.unified_diff(before.splitlines(True), current.splitlines(True),
        fromfile='before/studies/trader_replication/system.py', tofile='after/studies/trader_replication/system.py')))
    write('execution_checks.json', dict(accounts=checks, S2_signal_identical_to_X1=True,
        engine_change_exactly_declared=True, engine_before_sha256=manifest['engine_before_sha256'],
        engine_after_sha256=P3.sha(engine), controls=read(OUT / 'control_replay.json'),
        strategy_label_read_guard=True, offline_audit_guard=True))
    log('audit', '成交价格、独立库存、信号/报价截断与默认执行复放通过', 'execution_checks.json', 'pass')
    print('execution audit passed', flush=True)


def diagnostics():
    """Revalue inherited diagnostic snapshots at the close; never rerun trading."""
    frozen(True)
    A = P3.market()
    ci = {str(c): j for j, c in enumerate(A['codes'])}
    di = {str(d): t for t, d in enumerate(A['days'])}
    changed = {}
    for name in ('master', 'X1_OPEN', *S.CANDIDATES, *(['paired'] if read(OUT / 'chosen_b.json')['enabled'] else [])):
        if name in ('master', 'X1_OPEN'):
            source = HOME / ('reports/p4_work/a1/master' if name == 'master' else 'reports/p4_work/accounts/X1_OPEN')
            destination = f'controls/{name}'
        else:
            destination = 'paired' if name == 'paired' else f'accounts/{name}'
            source = OUT / destination
        daily = read(source / 'daily.json')
        curve = read(source / 'curve.json')
        equity = dict(zip(curve['days'], curve['equity']))
        rows, differences = [], 0
        for row in daily:
            holdings = []
            for p in row['positions']:
                d, j = di[row['day']], ci[p['code']]
                while d > 0 and not np.isfinite(A['close'][d, j]):
                    d -= 1
                value = p['shares'] * float(A['close'][d, j])
                holdings.append(dict(p, value=value))
            eq = equity[row['day']]
            gross = sum(p['value'] for p in holdings)
            assert abs(row['cash'] + sum(p['side'] * p['value'] for p in holdings) - eq) < 1e-10 * max(1, abs(eq))
            differences += row['timing'] != 'close' or abs(row['equity'] - eq) > 1e-10
            rows.append(dict(row, positions=holdings, timing='close', equity=eq,
                             gross_value=gross, gross_fraction=gross / eq, gross_room=2.8 * eq - gross))
        write(f'{destination}/daily_close.json.gz', rows)
        changed[name] = dict(days=len(rows), inherited_mixed_mark_snapshots=differences,
            cash_plus_net_close_value_equals_equity=True)
    stops = read(OUT / 'a0_stops.json')
    strict = {name: dict(at_or_above=sum(r['stop_day_close'] >= r['effective_stop'] for r in stops if r['labelled'] == flag),
                        strictly_above=sum(r['stop_day_close'] > r['effective_stop'] for r in stops if r['labelled'] == flag))
              for name, flag in (('48_leg_symbols', True), ('other_symbols', False))}
    blocked_shorts = {}
    for name in ('S1_NOBLOCK', 'S3_BOTH'):
        rows = read(OUT / f'accounts/{name}/attempts.json')
        blocked_shorts[name] = sum(r['kind'] == 's_Z15' and r['reason'] == 'no_rebuy_day' for r in rows)
    write('diagnostic_reconciliation.json', dict(timestamp=now(), daily=changed,
        close_recovery_strict_check=strict, no_rebuy_day_blocked_S7=blocked_shorts,
        trades_curves_and_selection_unchanged=True,
        note='P4通用快照读取early变量，开盘队列非空的日期混入开盘估值；另按股数、收盘价、实际曲线核对并保存daily_close，原工件保留'))
    print('diagnostics reconciled', changed, strict, 'blocked S7', blocked_shorts, flush=True)


def test_results():
    result = {}
    for name in ('custody', 'trader_replication', 'martin_luk', 'trader_screens'):
        path = OUT / f'tests/{name}.log'
        data = path.read_text()
        match = re.search(r'Ran (\d+) tests? in ([\d.]+)s', data)
        code = int((OUT / f'tests/{name}.exit').read_text())
        assert code == 0 and match and re.search(r'^OK(?:\s|$)', data, re.M), (name, data[-2000:])
        skips = re.search(r'skipped=(\d+)', data)
        expected = re.search(r'expected failures=(\d+)', data)
        result[name] = dict(n=int(match[1]), seconds=float(match[2]), exit_code=code,
            skipped=int(skips[1]) if skips else 0, expected_failures=int(expected[1]) if expected else 0,
            sha256=P3.sha(path))
    return result


def pct(value):
    return '缺失' if value is None else f'{value:+.1%}'


def num(value, digits=2):
    return '缺失' if value is None else f'{value:.{digits}f}'


def table(headers, rows):
    return ['| ' + ' | '.join(headers) + ' |', '|' + '|'.join('---' for _ in headers) + '|'] + [
        '| ' + ' | '.join(map(str, row)) + ' |' for row in rows]


def report():
    frozen(True)
    selected_a, selected_b = read(OUT / 'chosen_a.json'), read(OUT / 'chosen_b.json')
    accounts = {n: read(OUT / f'controls/{n}/summary.json') for n in ('master', 'X1_OPEN')}
    accounts.update({n: read(OUT / f'accounts/{n}/summary.json') for n in S.CANDIDATES})
    if selected_b['enabled']:
        accounts['paired'] = read(OUT / 'paired/summary.json')
    definitions = {n: read(OUT / f'regimes/{n}.json') for n in S.REGIMES}
    effects, portrait = read(OUT / 'effects.json'), read(OUT / 'behaviour.json')
    diagnostic_fix = read(OUT / 'diagnostic_reconciliation.json')
    G2 = read(OUT / 'G2.json')
    tests = test_results()
    rapid13 = read(OUT / 'a0_rapid13.json')
    strict_rapid = sum(r['stop']['stop_day_close'] > r['stop']['effective_stop'] for r in rapid13)
    write('close_recovery_boundary_check.json', dict(
        rapid13=dict(at_or_above=sum(r['stop']['close_recovered'] for r in rapid13), strictly_above=strict_rapid),
        all_stops=diagnostic_fix['close_recovery_strict_check'],
        note='原A0按不低于线统计，和收盘跌破的严格触发对称；补充严格高于线，原预登记不改'))
    chosen = accounts[selected_a['chosen']]
    def sequence(row, field):
        return '、'.join(f"{row['holding_coverage']['annual'][y][field]}/{row['holding_coverage']['annual'][y]['n']}" for y in YEARS)
    returns = '、'.join(pct(chosen['annual'][y]['ret']) for y in YEARS)
    lines = ['# P5：盘中止损扫掉了不少早买，但放开再买仍没解决亏损', '',
        f"**按任务书选中{selected_a['chosen']}。** 2024/2025/2026早买为{sequence(chosen, 'covered')}，"
        f"峰前一日收盘仍持有为{sequence(chosen, 'peak_held')}，收益{returns}。"
        '**三个候选在选择期都有亏损年**，因此按预登记全保留、再比持仓覆盖；这不代表通过了不亏底线，也不能替换登记master。', '',
        f'A0的13个“早买后3天内止损、峰前没再入”段里，10个入场当天止损、12个当天收盘不低于止损线（其中{strict_rapid}个严格高于）。'
        '这支持检验收盘止损，但不说明这些票都能被拿到峰前；把止损移到收盘也可能亏得更大。'
        '账户原本没有跨日禁买期，主要点名阻挡来自IE9的10晚冷却。', '',
        f"**B选中{selected_b['chosen'] or '无'}。** "
        + ('只有它通过选择期90%稳定线，按固定规则入选。' if len(selected_b['eligible']) == 1 else
           '按稳定性及X1两年收益关联的固定顺序选择。')
        + '状态对X1收益的区分在2024、2025方向相反，尚不能据此称为可靠的赚钱行情开关。'
        '收益关联选择是看过P4后的**事后修订**，2026只作历史留出*，不重选。', '']
    if selected_b['enabled']:
        paired = accounts['paired']
        lines += [f"成对应用后的三年早买为{sequence(paired, 'covered')}，峰前持有为{sequence(paired, 'peak_held')}，收益"
            + '、'.join(pct(paired['annual'][y]['ret']) for y in YEARS)
            + f"，空头覆盖{paired['short_coverage']['covered']}/37；只报告，不据此回选A/B。", '']
    lines += ['## A0：止损与再次点名的只读诊断', '']
    lines += (OUT / 'A0_CN.md').read_text().splitlines()[2:]
    lines += ['', '上表“收盘收回”定义为不低于止损线，与“收盘跌破才止损”对称。按严格高于线统计，'
        '48段股票为100/212，其他票282/617；13个层8段为' + str(strict_rapid) + '/13。'
        '严格边界复核见close_recovery_boundary_check.json，原A0与预登记未改。']
    lines += ['', '“冷却挡住20段”和“其中原始前三也被冷却挡住7段”是不同范围：前者含低排名票，后者才在本轮每晚前三预算内。'
        '逐夜原因按流水线最早阻挡归属；多种原因可能发生在同一段，段数不可相加。'
        '内部3名截断属于正常预算，不能把取消冷却之后的所有变化都称为“再次买入补回”。'
        '13段里仍有多段在止损后根本没有进入原始前三，解除冷却也无法凭空造出后续点名。', '',
        '## A：实际覆盖与账户', '',
        '三个候选的预登记、原话和完整边界见[PREREG_P5_CN.md](../notes/PREREG_P5_CN.md)。'
        'S1取消点名冷却；S2保留X1名单，只改首5日收盘止损；S3预先固定为两者同时改。'
        '全部从IE9原始完整排序出发，每晚最多3名；S2冷却后前三与旧X1逐位相同。'
        'S评测仍另作10交易日冷却，但不追溯删除S1/S3账户点名。', '',
        '首5日包括入场当天；硬止损为原始R的2倍，盘中越线先止损，跳空按开盘。第6个交易日起恢复原止损。'
        '默认关闭的引擎选项`entry_close_stops`仅补齐首日执行和5根日K边界，未启用首日加仓/减仓。'
        'S1/S3仅禁止止损当天再次首开，次日起按新票；持仓中同票不重复首开。'
        '原止损线和风险仓位公式未放宽，故硬止损可损失超过原0.5%/0.8%风险预算。'
        '原多头21EMA离场、10R减30%、10R/20R加仓、单票50%准入上限、总仓2.8倍、反馈和S7均保留。', '',
        '早买完全沿用H1/P4首实际lot口径；后续加仓和再次入场不重置首笔时钟。'
        '新增主口径“峰前持有”按峰前一日收盘股数判断，当天已卖完不算，期末估值仍算持有。'
        '吃到为mainleg既有段内已实现加浮动盈利/首锚点涨幅的资金加权潜力；48段无资金记0，另列有资金段中位数。'
        '峰前持有只判断有无，不代表覆盖了足够仓位。', '']
    rows = []
    for name, account in accounts.items():
        for y in YEARS:
            r, cov = account['annual'][y], account['holding_coverage']['annual'][y]
            rows.append([name, y, f"{cov['covered']}/{cov['n']}", f"{cov['peak_held']}/{cov['n']}",
                f"{pct(cov['capture_median']['median'])}/{pct(cov['capture_funded_median']['median'])}"
                f"（{cov['capture_funded_median']['n']}）", pct(r['ret']), pct(r['win']), num(r['payoff']),
                f"{r['n']}（{r['longs']}/{r['shorts']}）", f"{num(r['days'])}（{num(r['days_win'])}/{num(r['days_loss'])}）"])
    lines += table(['账户', '年', '早买', '峰前持有', '吃到中位全段/有资金段（n）', '收益', '胜率', '盈亏比', '笔数（多/空）', '平均持有日（赢/亏）'], rows)
    lines += ['', '年度收益按连续账户年末权益计算；胜率、盈亏比和持有日按开仓年分组，剔除期末估值。'
        '2026截至冻结日2026-10-16，不能把它写成完整年或独立样本外。', '',
        '选择只使用截至2025-12-31的候选执行。3个2025跨年段未到峰前日，按[0,1]枚举上下界；'
        '32种计数组合都选S3，chosen_a先落盘才跑2026，随后完整结果也核实首选未变。'
        '各候选的2024/2025权益与完整回放前缀逐位一致；没有把年末持仓冒充峰前持仓。', '',
        '## 去掉阻挡、换止损分别补回多少段', '',
        '以下为实际账户相对原X1的变化。先报补回与丢失，再报净增，避免把交互项相加。', '']
    rows = []
    for name in S.CANDIDATES:
        data = effects['comparisons'][f'{name}_vs_X1_OPEN']
        for y in (*YEARS, 'all'):
            def change(field):
                r = data[y][field]
                return f"补{len(r['gained'])}/丢{len(r['lost'])}/净{r['net']:+d}"
            rows.append([name, y, change('covered'), change('peak_held')])
    lines += table(['改动', '年', '早买段', '峰前持有段'], rows)
    rows = []
    for pair in ('S3_BOTH_vs_S1_NOBLOCK', 'S3_BOTH_vs_S2_CLOSESTOP'):
        r = effects['comparisons'][pair]['all']['peak_held']
        rows.append([pair, len(r['gained']), len(r['lost']), r['net']])
    lines += ['', '下面两行单列成对改动的边际作用；它们不等于各自相对X1的作用。', '']
    lines += table(['成对版本相对单改版本', '补回峰持', '丢失峰持', '净增'], rows)
    lines += ['', '原13个层8段中，各版本最终峰前持有数：'
        + '；'.join(f"{n} {len(r['peak_held'])}/13" for n, r in effects['original_rapid13'].items()) + '。'
        '具体补回与丢失的段名在effects.json。', '', '## 止损后正常再次买入及本人差距', '']
    rows = []
    for name in (*S.CANDIDATES, *(['paired'] if selected_b['enabled'] else [])):
        account = portrait['accounts'][name]
        for y in YEARS:
            r = account['rebuys']['annual'][y]
            rows.append([name, y, r['n'], account['annual'][y]['rebuy_within10'],
                         pct(r['win']), num(r['pnl'], 4), pct(r['return_stats']['median'])])
    lines += table(['账户', '年', '止损后再入笔数', '其中10日以内', '再入已平仓胜率', '再入盈亏/初始账户权益', '再入单笔收益中位'], rows)
    lines += ['', '只数同票上一笔多头以止损全平、后续交易日重新正常首开的交易，不限定专属重试窗口。'
        '盈亏包含本账户该笔的加减仓与期末浮动，按连续账户初始权益单位加总，融资利息仍记账户；'
        '不能把这个数当作另一条独立复合收益率。', '',
        '本人2024：+283%、104胜319负、胜率24.6%、盈亏比5；2025：+969.8%、209胜731负、胜率22.2%、盈亏比6.71。'
        '2026只有截至7月+869%的既有资料，全年目标、结构化持有期序列缺失。'
        '以下对照沿用replicate.HIS与RULES，不拿分时940笔强行要求日K完全相同。', '']
    rows = []
    for name in (*S.CANDIDATES, *(['paired'] if selected_b['enabled'] else [])):
        for y, r in accounts[name]['annual'].items():
            g = r['gaps']
            rows.append([name, y] + [num(g[k], 3) for k in ('return_percentage_points', 'log_wealth',
                'win_percentage_points', 'count', 'payoff')] + ['缺失'])
    lines += table(['账户', '年', '收益差百分点', '财富比对数差', '胜率差百分点', '笔数差', '盈亏比差', '持有期差'], rows)
    lines += ['', '2026与本人截至7月的同期限收益：'
        + '；'.join(f"{n} {pct(r['annual']['2026']['matched_public_period']['ours'])}"
                   for n, r in accounts.items() if n in (*S.CANDIDATES, 'paired')) + '，本人+869%。', '']
    rows = []
    for name in (selected_a['chosen'], *(['paired'] if selected_b['enabled'] else [])):
        for y, r in portrait['accounts'][name]['annual'].items():
            rows.append([name, y, num(r['long_count']['median']), num(r['largest_fraction']['median']),
                pct(r['top4_share']['median']), r['stopped_within5']])
    lines += table(['账户', '年', '收盘多头只数中位', '最大多头/权益中位', '前4只占多头仓位中位', '5日内止损多单'], rows)
    lines += ['', '本人原话偏集中3–4只；上表衡量实际持仓，不把50%买入上限写成全程市值上限。'
        '再买更多、持有更久或胜率变高本身都不等于更像本人，覆盖、亏损和集中度需一起看。', '',
        '## 九层漏斗', '',
        '1未点名，2无可执行买点，3每日队列，4仓位/总仓，5 IDX50，6同票/当日限制，7首笔太晚，'
        '8早买3日内止损，9其余早买。8R为峰前又正常买回，8N为未买回；8R+8N+9=早买。'
        '账户原始成交优先，不能按S冷却投影追溯抹掉实际买到。', '']
    rows = []
    for name in accounts:
        folder = (f'controls/{name}' if name in ('master', 'X1_OPEN') else
                  'paired' if name == 'paired' else f'accounts/{name}')
        data = read(OUT / f'{folder}/funnel.json')
        for y, r in data['annual'].items():
            rows.append([name, y] + [r['layers'][str(k)] for k in range(1, 8)]
                + [r['layer8_returned'], r['layer8_no_return'], r['layers']['9']])
    lines += table(['账户', '年', '1', '2', '3', '4', '5', '6', '7', '8R', '8N', '9'], rows)
    lines += ['', '逐段逐夜的原生点名、报价、队列、账户权益/现金/仓位和拒单原因保存在压缩funnel工件；'
        '层8买回仍可能在峰前再次退出，不能把8R直接当作峰前持有。', '',
        '## B：按当晚波动分位数宽度（事后修订）', '',
        '宽度池为当晚日均成交额≥1亿美元、ADR20位于当晚流动池前30%；70%分位边界同值纳入。'
        'L=9>21>50，G=9<21<50，比较L−G的EMA10/30。W、F、最终状态均确认3日。'
        f"F用A首选{selected_a['chosen']}的实际前10晚K=3点名，满两根已完成收盘才成熟，不读台账或账户。"
        'B3其余常态，B4其余一律防守；不足5笔反馈维持旧F，暖机B3常态、B4防守。', '',
        '固定16项单项扰动为五个EMA各±2、前25%/35%、成交额±25%、反馈40%/60%。'
        '选择期只用2024/2025：先过最低重合90%及截断，再比较原X1两年较差的进攻日复合收益−防守日复合收益。'
        '先写chosen_b，再评测2026；2026稳定性也单列，未借它重选。', '']
    rows = []
    for name, r in definitions.items():
        train = selected_b['scores'][name]
        annual26 = min(v['annual']['2026'] for v in r['stability']['variants'])
        rows.append([name, f"{train['minimum']:.2%}", f"{r['stability']['minimum']:.2%}",
            f"{annual26:.2%}", r['stability']['worst'], pct(train['annual']['2024']),
            pct(train['annual']['2025']), '通过' if name in selected_b['eligible'] else '未过稳定线'])
    lines += table(['定义', '选择期最低重合', '全期最低重合', '2026最低重合', '全期最差扰动', 'X1进攻−防守2024', '2025', '选择期资格'], rows)
    lines += ['', '收益差为百分点口径，各状态内实际日收益复合后相减；状态天数不相同，也未匹配敞口。'
        '只有B4合格时直接选B4，即使其收益关联方向不一致，也不擅自增加否决条件。'
        'B3即使某一年的关联数字更好，也不能越过稳定线。', '']
    rows = []
    for name, r in definitions.items():
        for y, values in r['annual'].items():
            rows.append([name, y] + [f"{values[s]['days']}/{values[s]['episodes']}" for s in P3.R.NAMES])
    lines += table(['定义', '年', '进攻天/段', '常态天/段', '防守天/段'], rows)
    lines += ['', '2026年7–8月逐日状态如下（进/常/防）；W、F与成熟反馈比例在[CSV](p5_work/july_august_states.csv)。', '']
    rows = []
    translate = ('进', '常', '防')
    for i, day in enumerate(definitions[S.REGIMES[0]]['calendar']):
        if '2026-07-01' <= day <= '2026-08-31':
            rows.append([day] + [translate[int(definitions[n]['label'][i])] for n in S.REGIMES])
    lines += table(['交易日', *S.REGIMES], rows)
    lines += ['', '## 三条旧账户按状态收益与按年留一', '',
        '全部为固定曲线的实际日收益分组，不是重新运行的择时账户。两个定义、三条账户、三个年份及全部按年留一的其余两年/留出年均在G2.json。'
        '没有重新拟合；B选择只读X1的2024/2025，master/M3B与本人G2不入选择。', '']
    rows = []
    for name, output in G2['definitions'].items():
        for account, data in output['old_accounts'].items():
            for y, values in data['annual'].items():
                rows.append([name, account, y] + [pct(values[s]['ret']) for s in P3.R.NAMES])
    lines += table(['定义', '旧账户', '年', '进攻日收益', '常态日收益', '防守日收益'], rows)
    lines += ['', '## 本人方向、票档G2', '',
        '方法沿用P3：方向只用可靠日期exact/chart，window另列；成交额/ADR票档用P3冻结的首锚点当晚画像及其评测流动池。'
        '整episode等权置换999次、种子0、双侧p<0.1，至少15笔/3个有观测段、至少2个留一同向。'
        f"有日期计数{G2['dated_counts']}，票档缺输入{len(G2['missing_portraits'])}段；不比较记录密度。", '']
    rows = []
    for name, data in G2['definitions'].items():
        lines += [name + '：' + P3.g2_conclusion(data['scopes']), '']
        for scope, scope_data in data['scopes'].items():
            for metric, values in scope_data['metrics'].items():
                for state, r in values['states'].items():
                    rows.append([name, scope, metric, state, f"{r['n']}/{r['observed_episodes']}",
                        num(r['mean'], 3), num(r['effect'], 3), num(r['p'], 3), r['leave_one_same_direction'], r['status']])
    lines += table(['定义', '范围', '指标', '状态', '笔/段', '均值', '段效应', 'p', '留一同向', '结果'], rows)
    lines += ['', '未检出差异只针对本轮定义与现有记录；未观测不等于行为与行情无关。'
        'exact单独结果、全部逐episode留一、窗口记录及票档时间相关性保存在G2.json。', '',
        '## 成对应用（只报告）', '']
    if selected_b['enabled']:
        r = accounts['paired']
        lines += ['在A首选上用B首选替换IDX50和idx_pb16：进攻多头风险×1.6、常态×1、防守不新开多。'
            '已有多头继续原管理；空头只在防守，沿用原Z15、首次跌破50后首次反抽、已完成周线不好才做，每日最多1名。'
            '反抽条件必须在原成交位已可知，不能用更晚日高追认。', '']
        lines += table(['年', '早买', '峰前持有', '段内吃到中位', '收益', '空头覆盖'], [
            [y, f"{r['holding_coverage']['annual'][y]['covered']}/{r['holding_coverage']['annual'][y]['n']}",
             f"{r['holding_coverage']['annual'][y]['peak_held']}/{r['holding_coverage']['annual'][y]['n']}",
             pct(r['holding_coverage']['annual'][y]['capture_median']['median']), pct(r['annual'][y]['ret']),
             sum(t['covered'] for t in r['short_coverage']['per_trade'] if t['date'].startswith(y))]
            for y in YEARS])
        lines += ['', f"总空头覆盖{r['short_coverage']['covered']}/37；ETF缺行情仍在分母，逐单窗口为本人入场前3至后1交易日。"
            '行为与本人差距已在上表逐年报告，未因成对结果改变首选。']
    else:
        lines += ['没有通过稳定性与截断的定义，未启用成对账户。']
    lines += ['', '## 验证、资源与复算', '',
        '全部运行.venv、单线程、60%CPU/900MiB scope；研究入口拒绝网络与子进程，写入限定P5目录与报告。'
        '市场数组只读memmap，宽度按日期处理，无N×N矩阵。大工件直接gzip无损保存，没有删除其他研究文件。'
        '策略侧在标签读入拦截中运行，台账、段表只在评测侧读。', '',
        '默认路径的master与旧X1完整台账、权益曲线逐位相同；唯一共享引擎改动是预登记的默认关闭执行选项，'
        'engine_delta.patch可核对其全部增量。实际成交价均在有效当日区间内；峰前股数另与每日库存独立核对。'
        '信号、报价、宽度、反馈、最终状态截断一致，未来价格/流动性/ADR/点名扰动不影响此前状态。', '']
    lines += table(['测试组', '项数', '结果', '跳过', '预期失败'],
        [[n, r['n'], '通过', r['skipped'], r['expected_failures']] for n, r in tests.items()])
    lines += ['', '看板缺指定日期港股分钟K的本地数据项按原测试跳过，未联网补数据；预期失败沿用既有测试。'
        '新增库存测试首跑的合成场景先触及了普通止损，未形成预期的期末估值；修正初始低点、增加期末类型断言后重跑整组通过。'
        '初跑日志保存在tests/martin_luk_initial.log，策略、实际账户与选择未改。', '',
        '另核对继承的P4诊断快照：开盘队列非空时，通用快照混入开盘估值。'
        '本轮另存daily_close.json.gz，按实有股数×当日收盘重新估值，逐日核对现金加净持仓等于实际权益曲线；'
        '原始快照保留，交易、曲线、覆盖、选择和上文收盘仓位统计均未变。'
        f"当日禁买没有额外挡住S7空头（次数{diagnostic_fix['no_rebuy_day_blocked_S7']}）。"
        '止损收回用不低于止损线，严格高于的边界复核另存diagnostic_reconciliation.json。', '',
        '复算入口：`python -m studies.martin_luk.p5_research`，阶段依次为freeze、a0、preregister、train、validate、'
        'regimes、regime_holdout、behaviour、baccount、comparisons、audit、diagnostics、report、finish。'
        '需在任务书scope和单线程环境中运行；正式评测工件独占创建，防止无记录覆盖。'
        '不要在现有完成目录重跑正式评测。', '',
        '预登记和选择时序、每项工件SHA、代码输入指纹、四组测试、资源峰值、保护清单核验及完成状态见'
        '[completion.json](p5_work/completion.json)。登记配置、看板和旧报告未变；没有Git提交或新增数据。'
        '本轮结论只评价这些日K翻译，不否定本人方法。']
    (HOME / 'reports/P5_CN.md').write_text('\n'.join(lines) + '\n')
    log('report', '完整中文结论、全部候选、全部年份及局限已写入', 'P5_CN.md', 'written')
    print('P5 report written', flush=True)


def finish():
    protocol = frozen(True)
    manifest = read(OUT / 'preregistered.json')
    assert P3.sha(HOME / 'p5_policy.py') == manifest['strategy_sha256']
    assert P3.sha(ROOT / 'studies/trader_replication/system.py') == manifest['engine_sha256']
    tests = test_results()
    engine_path = 'studies/trader_replication/system.py'
    changed = [p for p, h in protocol['protected'].items()
               if not (ROOT / p).is_file() or P3.sha(ROOT / p) != h]
    assert changed == [engine_path] or set(changed) == {engine_path}, changed[:20]
    execution = read(OUT / 'execution_checks.json')
    assert execution['engine_change_exactly_declared'] and execution['engine_before_sha256'] == protocol['protected'][engine_path]
    write('protected_verification.json', dict(ok=True, files=len(protocol['protected']),
        changes=changed, declared_default_off_engine_extension=True,
        registry_board_and_old_reports_unchanged=True, control_replay=read(OUT / 'control_replay.json')))
    selected_a, selected_b = read(OUT / 'chosen_a.json'), read(OUT / 'chosen_b.json')
    holdout, bholdout = read(OUT / 'holdout_started.json'), read(OUT / 'regime_holdout_started.json')
    assert selected_a['timestamp'] < holdout['timestamp']
    assert selected_b['timestamp'] < bholdout['timestamp']
    assert P3.sha(OUT / 'chosen_a.json') == holdout['chosen_a_sha256']
    assert P3.sha(OUT / 'chosen_b.json') == bholdout['chosen_b_sha256']
    for name, h in selected_a['summary_sha256'].items():
        assert P3.sha(OUT / f'train/{name}/summary.json') == h
    for name, h in selected_b['definition_sha256'].items():
        assert P3.sha(OUT / f'regimes/train/{name}.json') == h
    assert read(OUT / 'selection_reconciliation.json')['cross_year_bounds_confirmed']
    runs = {p.stem: read(p) for p in (OUT / 'runs').glob('*.json')}
    sources = dict(P3.SOURCES, **P4.SOURCES, **SOURCES)
    for run in runs.values():
        sources.update(run['sources'])
    for path, h in sources.items():
        assert (ROOT / path).is_file() and P3.sha(ROOT / path) == h, ('source changed', path)
    write('sources.json', sources)
    write('runs/finish.json', dict(stage='finish', timestamp=now(), resources=P3.resources(),
        disk_free_bytes=shutil.disk_usage(ROOT).free))
    a = read(OUT / f"accounts/{selected_a['chosen']}/summary.json")
    b = read(OUT / 'paired/summary.json') if selected_b['enabled'] else None
    states = read(OUT / f"regimes/{selected_b['chosen']}.json") if selected_b['enabled'] else None
    effects = read(OUT / 'effects.json')
    G2 = read(OUT / 'G2.json')
    resource_rows = [r['resources'] for r in runs.values()] + [P3.resources()]
    complete = dict(task='PLAN_P5_CN', status='complete', timestamp=now(),
        prereg_sha256=P3.sha(PREREG), runner_sha256=P3.sha(Path(__file__)),
        strategy_sha256=manifest['strategy_sha256'], engine_sha256=manifest['engine_sha256'],
        report_sha256=P3.sha(HOME / 'reports/P5_CN.md'),
        chosen_a=selected_a, chosen_b=selected_b,
        a=dict(annual=a['annual'], holding=a['holding_coverage']['annual']),
        paired=dict(annual=b['annual'], holding=b['holding_coverage']['annual'], short=b['short_coverage']['covered']) if b else None,
        A0=read(OUT / 'a0_summary.json'), effects=effects, execution=execution, tests=tests,
        diagnostic_reconciliation=read(OUT / 'diagnostic_reconciliation.json'),
        G2={n: P3.g2_conclusion(r['scopes']) for n, r in G2['definitions'].items()},
        protected=dict(ok=True, files=len(protocol['protected']), changes=changed,
                       declared_default_off_engine_extension=True),
        selected_before_holdout=True, cross_year_selection_bounds_invariant=True,
        post_hoc_B_selection=True, independent_out_of_sample=False, offline=True,
        downloaded_data=False, workspace_git_commits=0, registry_or_board_modified=False,
        maximum_recorded_rss_mib=max(r['peak_rss_mib'] for r in resource_rows),
        resources=P3.resources(), disk_free_bytes=shutil.disk_usage(ROOT).free)
    lines = [f"A选中{selected_a['chosen']}；三候选都有亏损年，按覆盖回退选择。"]
    for y in YEARS:
        cov = a['holding_coverage']['annual'][y]
        lines.append(f"{y}：早买{cov['covered']}/{cov['n']}，峰前持有{cov['peak_held']}/{cov['n']}，收益{a['annual'][y]['ret']:+.2%}。")
    r1 = effects['comparisons']['S1_NOBLOCK_vs_X1_OPEN']['all']['peak_held']
    r2 = effects['comparisons']['S2_CLOSESTOP_vs_X1_OPEN']['all']['peak_held']
    lines.append(f"相对X1峰前持有：去冷却补{len(r1['gained'])}/丢{len(r1['lost'])}/净{r1['net']:+d}段；"
                 f"收盘止损补{len(r2['gained'])}/丢{len(r2['lost'])}/净{r2['net']:+d}段。")
    if states:
        july = Counter(P3.R.NAMES[k] for day, k in zip(states['calendar'], states['label']) if day.startswith('2026-07'))
        lines.append(f"B={selected_b['chosen']}，选择期稳定{selected_b['scores'][selected_b['chosen']]['minimum']:.2%}；"
            f"7月进/常/防={july['up']}/{july['pullback']}/{july['weak']}天，X1收益区分2024/25方向相反。")
    else:
        lines.append('B没有合格定义，不启用。')
    if b:
        lines.append('成对2024/25/26：早买=' + '/'.join(str(b['holding_coverage']['annual'][y]['covered']) for y in YEARS)
            + '，峰持=' + '/'.join(str(b['holding_coverage']['annual'][y]['peak_held']) for y in YEARS)
            + '，收益=' + '/'.join(f"{b['annual'][y]['ret']:+.2%}" for y in YEARS) + f"，空头{b['short_coverage']['covered']}/37。")
    lines.append('四组测试通过；P5_CN.md与p5_work/completion.json完成，登记/看板未变。')
    assert len(lines) <= 10
    (OUT / 'terminal_summary.txt').write_text('\n'.join(lines) + '\n')
    artifacts = {str(p.relative_to(OUT)): P3.sha(p) for p in OUT.rglob('*') if p.is_file()
        and p.name not in ('run.lock', 'artifact_manifest.json', 'completion.json', 'decisions.tsv')}
    write('artifact_manifest.json', artifacts)
    complete['artifact_manifest_sha256'] = P3.sha(OUT / 'artifact_manifest.json')
    write('completion.json', complete)
    log('finish', '预登记、输入、保护清单、执行与四组测试核验完成', 'completion.json', 'complete')
    print('\n'.join(lines), flush=True)


def offline():
    sys.dont_write_bytecode = True
    def guard(event, args):
        if event in ('socket.connect', 'socket.bind', 'socket.getaddrinfo', 'subprocess.Popen', 'os.system'):
            raise PermissionError('P5 offline single-process boundary')
        if event == 'open' and not isinstance(args[0], int) and args[2] & (
                os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND):
            path = Path(os.fsdecode(args[0])).resolve()
            if not path.is_relative_to(OUT.resolve()) and path not in (PREREG, HOME / 'reports/P5_CN.md'):
                raise PermissionError('P5 output boundary: ' + str(path))
    sys.addaudithook(guard)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage')
    args = parser.parse_args()
    offline()
    OUT.mkdir(parents=True, exist_ok=True)
    with (OUT / 'run.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        r = P3.resources()
        assert r['cpu_max'] == '60000 100000' and r['memory_max'] == str(900 * 1024 * 1024) and r['threads'] == '1', r
        assert shutil.disk_usage(ROOT).free >= 1024**3, 'compact only this round own duplicate intermediates'
        print('start', args.stage, r, flush=True)
        globals()[args.stage]()
        if args.stage != 'finish':
            write(f'runs/{args.stage}.json', dict(stage=args.stage, sources=dict(P3.SOURCES, **P4.SOURCES, **SOURCES),
                resources=P3.resources(), disk_free_bytes=shutil.disk_usage(ROOT).free, timestamp=now(),
                runner_sha256=P3.sha(Path(__file__))))


if __name__ == '__main__':
    main()
