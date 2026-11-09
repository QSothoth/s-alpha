"""Offline P4 evaluation; strategy inputs and public evaluation labels stay separate."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import asdict, replace
from datetime import datetime, timezone
import fcntl
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import resource
import shutil
import sys

import numpy as np

from . import p3_research as P3, p4_policy as S
from .p2_research import strategy_only
from studies.trader_replication import allocation, mainleg, system as Y

ROOT, HOME = P3.ROOT, P3.HOME
OUT = HOME / 'reports/p4_work'
PREREG = HOME / 'notes/PREREG_P4_CN.md'
YEARS = P3.YEARS
SOURCES = {}
LAYERS = {1: '没被点名', 2: '没有可执行买点', 3: '每日队列挤掉', 4: '仓位或资金挡住',
          5: 'IDX50挡住', 6: '同票或冷却挡住', 7: '首笔太晚', 8: '早买后很快止损未回来', 9: '早买成功'}


def sha(path):
    return P3.sha(path)


def read(path):
    path = Path(path)
    if not path.exists() and Path(str(path) + '.gz').exists():
        path = Path(str(path) + '.gz')
        SOURCES[str(path.relative_to(ROOT))] = sha(path)
        with gzip.open(path, 'rt') as stream:
            return json.load(stream)
    SOURCES[str(path.relative_to(ROOT))] = sha(path)
    return json.loads(path.read_text())


def write(path, value):
    P3.write(OUT / path, value, exclusive=True)


def log(phase, decision, evidence, result):
    path = OUT / 'decisions.tsv'
    if not path.exists():
        path.write_text('ts\tphase\tdecision\twhy\tevidence\tresult\n')
    cells = (datetime.now(timezone.utc).isoformat(), phase, decision, '按PLAN_P4_CN执行', evidence, result)
    with path.open('a') as stream:
        stream.write('\t'.join(str(c).replace('\t', ' ').replace('\n', ' ') for c in cells) + '\n')


def freeze():
    protected = {}
    for directory in ('studies', 'skills/trader-replication', 'watch', 'custody'):
        for path in (ROOT / directory).rglob('*'):
            if not path.is_file() or path.suffix not in ('.py', '.json', '.csv', '.md'):
                continue
            if path.is_relative_to(OUT) or path.name.startswith(('p4_', 'test_p4')) or path in (
                    PREREG, HOME / 'reports/P4_CN.md'):
                continue
            protected[str(path.relative_to(ROOT))] = sha(path)
    write('protocol.json', dict(task='PLAN_P4_CN', started=datetime.now(timezone.utc).isoformat(),
        plan_sha256=sha(HOME / 'notes/PLAN_P4_CN.md'), protected=protected,
        git_head=(ROOT / '.git').read_text().strip(), resources=P3.resources(),
        memory_before=Path('/proc/meminfo').read_text(), disk_free_bytes=shutil.disk_usage(ROOT).free,
        constraints=dict(offline=True, downloads=False, git_commits=0, single_process=True, single_thread=True),
        secret_guard='installer refused existing hooksPath; both existing hooks invoke secret_guard.py'))
    log('start', '冻结现有源码、报告和登记输入；本轮只新增P4文件', 'protocol.json', f'{len(protected)} files')
    print('protected inputs frozen', len(protected), flush=True)


def frozen(require_prereg=False):
    protocol = read(OUT / 'protocol.json')
    assert sha(HOME / 'notes/PLAN_P4_CN.md') == protocol['plan_sha256']
    if require_prereg:
        manifest = read(OUT / 'preregistered.json')
        assert sha(PREREG) == manifest['prereg_sha256'], 'P4 prereg changed'
        assert sha(OUT / 'a1_summary.json') == manifest['a1_sha256']
    return protocol


def snapshot(frame):
    """Read the engine's real admission state; no decision or engine source changes."""
    v = frame.f_locals
    d, early = v['d'], v.get('early', False)
    pos, px = v['pos'], v['px']
    c, o = px['close'], px['open']
    held = []
    for q in pos.values():
        mark = float(o[d, q.j] if early else c[d, q.j])
        if not np.isfinite(mark):
            k = d - 1
            while k > 0 and not np.isfinite(c[k, q.j]):
                k -= 1
            mark = float(c[k, q.j])
        held.append(dict(code=str(px['codes'][q.j]), side=q.side, entry=str(px['dates'][q.d0]),
                         shares=float(q.size), value=float(q.size * mark), stop=float(q.stop)))
    equity = float(v.get('eq_now', v['cash'] + sum(p['side'] * p['value'] for p in held)))
    gross = sum(p['value'] for p in held)
    return dict(day=str(px['dates'][d]), timing='open' if early else 'close', equity=equity,
                cash=float(v['cash']), gross_value=gross, gross_fraction=gross / equity if equity > 0 else None,
                positions=held, gross_room=2.8 * equity - gross)


class Observations(list):
    def __init__(self, daily=False):
        super().__init__()
        self.daily, self.states = daily, []

    def append(self, row):
        state = snapshot(sys._getframe(1))
        if self.daily:
            self.states.append(state)
        else:
            row['account_before'] = state
        super().append(row)


def simulate(A, rules, book, end='2026-10-16'):
    attempts, daily = Observations(), Observations(daily=True)
    track = dict(entry_attempts=attempts, gross=daily)
    curve, dates, trades = Y.simulate(P3.px(A), {k: A[k] for k in ('e9', 'e21', 'idx_pb16', 'p4_risk') if k in A},
        rules, book, '2024-01-02', end, audit=True, track=track)
    return dict(curve=dict(days=list(dates), equity=curve), trades=trades,
                attempts=list(attempts), daily=daily.states)


def market():
    return P3.market()


def books(A, own_short_rows):
    result = {name: P3.decode_book(read(HOME / f'reports/d1_work/master_{name}.json'), A)
              for name in ('raw', 'filtered', 'capped', 'book')}
    result['short_entries'] = P3.decode_book(own_short_rows, A)
    return result


def project(A, picks, K=3):
    indexed = {t: picks.get(str(d), []) for t, d in enumerate(A['days'][:-1])}
    return allocation.nominations(indexed, maximum=K, cooldown=10)


def indexed_book(book):
    return {(d, j): [e for e in row if e[1] == j and e[2] > 0]
            for d, row in enumerate(book) for j in dict.fromkeys(e[1] for e in row if e[2] > 0)}


def funnel(A, records, rules, picks, raw_book, filtered_book, offered_book, legs, *, same_night_only=False):
    """Actual fills keep the H1 clock; a failed path retains every night and gate."""
    coverage = P3.actual_coverage(records['trades'], rules, legs, A)
    raw, filtered, offered = map(indexed_book, (raw_book, filtered_book, offered_book))
    ci = {str(c): j for j, c in enumerate(A['codes'])}
    di = {str(d): t for t, d in enumerate(A['days'])}
    attempts, daily = defaultdict(list), {r['day']: r for r in records['daily']}
    for row in records['attempts']:
        attempts[(di[row['day']], row['code'])].append(row)
    result = []
    for g, cov in zip(legs, coverage['per_leg']):
        j, nights = ci[g['code']], []
        for t in range(max(0, g['first'] - 4), min(g['peak'] - 1, len(A['days']) - 1)):
            opening = float(A['open'][t + 1, j])
            share = (g['top'] / opening - 1) / g['gain'] if np.isfinite(opening) and opening > 0 else None
            qualified = share is not None and share >= .5 - 1e-12
            named = g['code'] in picks.get(t, [])
            checks = []
            for d in range(t, min(t + 4, len(A['days']))):
                key = d, j
                rows = attempts.get((d, g['code']), [])
                actual_queue = [str(A['codes'][e[1]]) for e in sorted(offered_book[d], key=lambda e: e[0]) if e[2] > 0]
                raw_rows, allowed, queued = raw.get(key, []), filtered.get(key, []), offered.get(key, [])
                if not raw_rows:
                    gate, detail = 2, 'no_shape'
                elif not allowed:
                    gate, detail = 5, 'IDX50'
                elif not queued:
                    # A fixed-night projection can expire before a later shape arrives.
                    current_named = g['code'] in picks.get(d, [])
                    gate, detail = (3, 'offer_cap') if current_named or not same_night_only else (2, 'nomination_not_retained')
                elif not rows:
                    gate, detail = 2, 'outside_account_window'
                elif any(r['reason'] == 'filled' for r in rows):
                    gate, detail = 9, 'filled'
                elif all(r['reason'] in ('same_code', 'no_rebuy_day', 'episode_limit') for r in rows):
                    gate, detail = 6, rows[0]['reason']
                elif any(r['reason'] in ('daily_long', 'daily_all', 'daily_kind') for r in rows):
                    gate, detail = 3, 'successful_daily_cap'
                else:
                    gate, detail = 4, ','.join(dict.fromkeys(r['reason'] for r in rows))
                checks.append(dict(day=str(A['days'][d]), night_offset=d - t, shape=bool(raw_rows),
                    passes_IDX50=bool(allowed), offered=bool(queued), gate=gate, detail=detail,
                    displaced_by=actual_queue[:4] if gate == 3 else [], queue=actual_queue,
                    attempts=rows, account_at_close=daily.get(str(A['days'][d]))))
            nights.append(dict(night=str(A['days'][t]), index=t, qualified=qualified,
                remaining_share=share, nominated=named, nominations=picks.get(t, []), checks=checks))
        nominated = [r for r in nights if r['qualified'] and r['nominated']]
        first = cov['first_fill']
        rapid = False
        first_trade = None
        if first:
            relevant = [r for r in records['trades'] if r['side'] > 0 and r['code'] == g['code']
                        and r['entry'] == str(A['days'][first['index']])]
            first_trade = relevant[0] if relevant else None
            if first_trade and cov['covered']:
                exited = di[first_trade['exit']]
                again = any(r['side'] > 0 and r['code'] == g['code'] and
                            first_trade['exit'] < r['entry'] < str(A['days'][g['peak']])
                            for r in records['trades'])
                rapid = (first_trade['why'] in ('stop', 'gap_stop', 'stop_day0') and
                         exited - first['index'] <= 3 and not again)
        if cov['covered']:
            layer = 8 if rapid else 9
        elif cov['any']:
            layer = 7
        elif not nominated:
            layer = 1
        else:
            checks = [c for r in nominated for c in r['checks']]
            # Diagnose the path that reached furthest, rather than an earlier night's missing shape.
            if any(c['gate'] == 4 for c in checks):
                layer = 4
            elif any(c['gate'] == 6 for c in checks):
                layer = 6
            elif any(c['gate'] == 3 for c in checks):
                layer = 3
            elif any(c['gate'] == 5 for c in checks):
                layer = 5
            else:
                layer = 2
        result.append(dict(key=g['key'], code=g['code'], year=str(A['days'][g['first']])[:4],
            first=str(A['days'][g['first']]), peak=str(A['days'][g['peak']]), layer=layer,
            layer_name=LAYERS[layer], coverage=cov, signal_hit=bool(nominated),
            rapid_stop_without_return=rapid, first_trade=first_trade, nights=nights))
    return dict(coverage=coverage, per_leg=result,
        annual={y: dict(n=sum(r['year'] == y for r in result),
            layers={str(k): sum(r['year'] == y and r['layer'] == k for r in result) for k in LAYERS},
            early=sum(r['year'] == y and r['coverage']['covered'] for r in result),
            any=sum(r['year'] == y and r['coverage']['any'] for r in result)) for y in YEARS},
        layers={str(k): sum(r['layer'] == k for r in result) for k in LAYERS},
        optimistic_upper={str(k): dict(extra_early=sum(r['layer'] == k for r in result) if k < 8 else 0,
            extra_surviving_early=sum(r['layer'] == k for r in result) if k == 8 else None,
            note='单层失败数的乐观必要上限，不是反事实回放；各层不可相加') for k in range(2, 9)},
        convention='层8已计入H1/P3早买；层9为其余早买。原账户实际早买优先于K3诊断，允许绕过K3。')


def save_account(folder, records):
    for key, value in records.items():
        write(f'{folder}/{key}.json', value)


def a1():
    frozen()
    assert not PREREG.exists(), 'A1 must precede preregistration'
    own_short_rows = read(HOME / 'reports/d1_work/master_short_entries.json')
    with strategy_only():
        A = market()
        _, rules, _ = P3.account_inputs(A)
        B = books(A, own_short_rows)
        master = simulate(A, rules, B['book'])
        old = read(HOME / 'reports/d1_work/master_curve.json')
        trades = read(HOME / 'reports/d1_work/master_trades.json')
        assert P3.clean(master['curve']) == old and P3.clean(master['trades']) == trades
        picks_c2 = read(HOME / 'reports/p3_work/picks/C2_NEAR21.json')
        c2_book = P3.candidate_book(A, picks_c2, B['filtered'], B['short_entries'], None, False)
        c2 = simulate(A, rules, c2_book)
        assert P3.clean(c2['trades']) == read(HOME / 'reports/p3_work/accounts/C2_NEAR21/A/trades.json')
        assert P3.clean(c2['curve']) == read(HOME / 'reports/p3_work/accounts/C2_NEAR21/A/curve.json')
        ie9 = read(HOME / 'reports/s0_work/picks/IE9.json')
        ie9_new = project(A, ie9)
        assert all(cs == ie9.get(str(A['days'][t]), []) for t, cs in ie9_new.items())
        ie9_book = P3.candidate_book(A, ie9, B['filtered'], B['short_entries'], None, False)
        ie9_account = simulate(A, rules, ie9_book)
        master_picks = project(A, read(HOME / 'reports/s0_work/picks/master_filtered.json'))
        c2_new = project(A, picks_c2)
    legs = read(HOME / 'notes/legs_frozen.json')['legs']
    summary = {}
    for name, record, picks, offered in (
            ('master', master, master_picks, B['book']),
            ('C2_NEAR21_A', c2, c2_new, c2_book),
            ('IE9_master', ie9_account, ie9_new, ie9_book)):
        save_account(f'a1/{name}', record)
        diagnostic = funnel(A, record, rules, picks, B['raw'], B['filtered'], offered, legs,
                            same_night_only=name != 'master')
        write(f'a1/{name}/funnel.json', diagnostic)
        summary[name] = {k: diagnostic[k] for k in ('annual', 'layers', 'optimistic_upper', 'convention')}
        print(name, 'layers', diagnostic['layers'], 'early', diagnostic['coverage']['covered'], flush=True)
    write('master_replay.json', dict(curve_exact=True, ledger_exact=True, c2_curve_exact=True, c2_ledger_exact=True))
    write('a1_summary.json', summary)
    lines = ['# P4 A1：冻结诊断（先于A2/B预登记）', '',
        '早买沿用H1/P3，层8也算早买；层8只解释买到后很快止损且未再买。登记master和P3按各自真实执行，K=3投影只诊断点名，不追溯限制原账户。', '',
        '| 系统 | 年 | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 早买 | 任意成交 |',
        '|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|']
    for name, row in summary.items():
        for y, r in row['annual'].items():
            lines.append('| ' + ' | '.join([name, y] + [str(r['layers'][str(k)]) for k in LAYERS] +
                [f"{r['early']}/{r['n']}", f"{r['any']}/{r['n']}"]) + ' |')
    lines += ['', '层2包含点名夜后3晚有形态、但原同晚点名已失效的情况，逐夜detail=nomination_not_retained。',
              '每层乐观上限见a1_summary.json；逐夜、队列挤出票与真实准入仓位见a1/*/funnel.json。',
              '首笔太晚和实际早买用真实成交价；分配失败在多晚路径中取走得最远的路径，不把先前一晚没形态当作全部原因。']
    (OUT / 'A1_CN.md').write_text('\n'.join(lines) + '\n')
    log('A1', '完成三条老系统逐段逐夜漏斗；真实账逐位复放一致', 'A1_CN.md', 'ready for preregistration')


def preregister():
    frozen()
    assert (OUT / 'A1_CN.md').exists() and PREREG.exists()
    assert not (OUT / 'train').exists() and not (OUT / 'regimes').exists()
    write('preregistered.json', dict(prereg_sha256=sha(PREREG), a1_sha256=sha(OUT / 'a1_summary.json'),
        a1_report_sha256=sha(OUT / 'A1_CN.md'), fixed_signal_sha256=sha(HOME / 'reports/s0_work/picks/IE9.json'),
        strategy_sha256=sha(HOME / 'p4_policy.py'), candidates=list(S.CANDIDATES) + list(S.REGIMES),
        layer='trade/allocate', paired=False, candidate_count=5,
        selection_years=['2024', '2025'], holdout='2026 historical holdout*',
        timestamp=datetime.now(timezone.utc).isoformat()))
    log('preregister', 'A1完成后冻结三种入场及两种事后行情定义；参数不再更改', 'preregistered.json', 'frozen')
    print('P4 preregistration frozen', sha(PREREG), flush=True)


def strategy_inputs():
    from . import replicate as MR
    own_short_rows = read(HOME / 'reports/d1_work/master_short_entries.json')
    with strategy_only():
        A = market()
        metadata, rules, spool = P3.account_inputs(A)
        B = books(A, own_short_rows)
        picks = read(HOME / 'reports/s0_work/picks/IE9.json')
        nominations = project(A, picks)
        manifest = read(OUT / 'preregistered.json')
        assert sha(HOME / 'reports/s0_work/picks/IE9.json') == manifest['fixed_signal_sha256']
        assert sha(HOME / 'p4_policy.py') == manifest['strategy_sha256']
        assert all(cs == picks.get(str(A['days'][t]), []) for t, cs in nominations.items())
        index_ok = MR.ew_index_up(A, P3.array(HOME / 'reports/d1_work/master_liquidity.npy'), 50)
        assert all([e for e in row if index_ok[d]] == B['filtered'][d] for d, row in enumerate(B['raw']))
    return A, metadata, rules, spool, B, nominations, index_ok


def summarize(record):
    from .replicate import HIS
    facts = P3.P.account_facts(record['curve']['equity'], record['curve']['days'], record['trades'])
    annual = {}
    for y, ret in facts['years'].items():
        part = [t for t in record['trades'] if t['entry'].startswith(y)]
        closed = [t for t in part if t['why'] != 'end']
        wins, losses = [t for t in closed if t['ret'] > 0], [t for t in closed if t['ret'] <= 0]
        mean_win = float(np.mean([t['ret'] for t in wins])) if wins else None
        mean_loss = float(np.mean([t['ret'] for t in losses])) if losses else None
        win = len(wins) / len(closed) if closed else None
        payoff = mean_win / abs(mean_loss) if mean_win is not None and mean_loss else None
        reference = HIS.get(y, {})
        his_n = reference.get('wins', 0) + reference.get('losses', 0) or None
        his_win = reference.get('wins', 0) / his_n if his_n else None
        his_payoff = abs(reference['avg_win'] / reference['avg_loss']) if reference.get('avg_loss') else None
        annual[y] = dict(ret=ret, n=len(part), closed=len(closed), win=win, payoff=payoff,
            avg_win=mean_win, avg_loss=mean_loss,
            days=float(np.mean([t['days'] for t in closed])) if closed else None,
            days_win=float(np.mean([t['days'] for t in wins])) if wins else None,
            days_loss=float(np.mean([t['days'] for t in losses])) if losses else None,
            longs=sum(t['side'] > 0 for t in part), shorts=sum(t['side'] < 0 for t in part),
            his=dict(ret=reference.get('ret'), n=his_n, win=his_win, payoff=his_payoff, days=None),
            gaps=dict(return_percentage_points=100 * (ret - reference['ret']) if 'ret' in reference else None,
                log_wealth=abs(float(np.log((1 + ret) / (1 + reference['ret']))))
                    if ret > -1 and 'ret' in reference else None,
                win_percentage_points=100 * (win - his_win) if win is not None and his_win is not None else None,
                count=len(part) - his_n if his_n else None,
                payoff=payoff - his_payoff if payoff is not None and his_payoff is not None else None, days=None))
    dates, equity = np.array(record['curve']['days']), np.array(record['curve']['equity'])
    if '2026' in annual:
        prior = np.flatnonzero(dates <= '2025-12-31')[-1]
        july = np.flatnonzero(dates <= '2026-07-31')[-1]
        ret = float(equity[july] / equity[prior] - 1)
        annual['2026']['matched_public_period'] = dict(end=str(dates[july]), ours=ret, his=8.69,
            difference_percentage_points=100 * (ret - 8.69))
    return dict(annual=annual, facts=facts)


def combined(longs, shorts):
    from studies.trader_replication.shorts import combine
    return combine(longs, [sorted(row, key=lambda e: e[0])[:1] for row in shorts])


def run_candidate(name, end, A, rules, B, nominations, index_ok, *, states=None, new_shorts=None):
    paired = states is not None
    with strategy_only():
        entries = S.entries(A, nominations, name, B['raw'], index_ok, use_index=not paired)
        long_book = entries['offered']
        if paired:
            long_book = [row if states[d] == P3.R.UP else [] for d, row in enumerate(long_book)]
            short_book = [row if states[d] == P3.R.WEAK else [] for d, row in enumerate(new_shorts)]
            A['p4_risk'] = np.where(states == P3.R.UP, 1.6, 1.)
        else:
            short_book = B['short_entries']
        policy = replace(rules, intraday_kinds=tuple(rules.intraday_kinds) + S.KINDS,
                         **(dict(risk_scale='p4_risk') if paired else {}))
        offered = combined(long_book, short_book)
        record = simulate(A, policy, offered, end)
    return record, policy, entries, offered


def train():
    frozen(True)
    write('training_started.json', dict(prereg_sha256=sha(PREREG), timestamp=datetime.now(timezone.utc).isoformat()))
    A, _, rules, _, B, nominations, index_ok = strategy_inputs()
    legs = [g for g in read(HOME / 'notes/legs_frozen.json')['legs'] if str(A['days'][g['first']])[:4] in YEARS[:2]]
    results = {}
    for name in S.CANDIDATES:
        record, policy, entries, offered = run_candidate(name, '2025-12-31', A, rules, B, nominations, index_ok)
        save_account(f'train/{name}', record)
        coverage = P3.actual_coverage(record['trades'], policy, legs, A)
        summary = dict(summarize(record), holding_coverage=coverage, paired=False,
                       layer='trade/allocate', timing_assumption=entries['timing_assumption'])
        results[name] = summary
        write(f'train/{name}/summary.json', summary)
        # Do not evaluate or disclose a 2026 trigger before the selection file exists.
        write(f'train/{name}/triggers.json', [r for r in entries['triggers'] if r['day'] <= '2025-12-31'])
        print('train', name, {y: (coverage['annual'][y]['covered'], round(summary['annual'][y]['ret'], 5))
                               for y in YEARS[:2]}, flush=True)
    eligible = [name for name, row in results.items() if all(row['annual'][y]['ret'] >= 0 for y in YEARS[:2])]
    all_failed = not eligible
    if all_failed:
        eligible = list(S.CANDIDATES)
    def key(name):
        r = results[name]
        return (-min(r['holding_coverage']['annual'][y]['covered'] / r['holding_coverage']['annual'][y]['n']
                     for y in YEARS[:2]), sum(r['annual'][y]['n'] for y in YEARS[:2]), S.CANDIDATES.index(name))
    chosen = min(eligible, key=key)
    write('chosen_a.json', dict(chosen=chosen, eligible=eligible, all_failed_return_floor=all_failed,
        keys={n: key(n) for n in S.CANDIDATES}, used_2026=False, returns_used='veto only',
        summary_sha256={n: sha(OUT / f'train/{n}/summary.json') for n in S.CANDIDATES},
        prereg_sha256=sha(PREREG), timestamp=datetime.now(timezone.utc).isoformat()))
    log('A2 selection', '按2024/2025较差年真实早买选定后落盘，尚未运行2026', 'chosen_a.json', chosen)
    print('chosen A before holdout', chosen, 'all failed floor', all_failed, flush=True)


def validate():
    frozen(True)
    chosen = read(OUT / 'chosen_a.json')
    write('holdout_started.json', dict(chosen_a_sha256=sha(OUT / 'chosen_a.json'),
        timestamp=datetime.now(timezone.utc).isoformat()))
    A, _, rules, _, B, nominations, index_ok = strategy_inputs()
    legs = read(HOME / 'notes/legs_frozen.json')['legs']
    from studies.trader_replication import ledger
    public = ledger.load(HOME / 'notes/trades.csv')
    for name in S.CANDIDATES:
        record, policy, entries, offered = run_candidate(name, '2026-10-16', A, rules, B, nominations, index_ok)
        save_account(f'accounts/{name}', record)
        training_curve = read(OUT / f'train/{name}/curve.json')
        assert record['curve']['days'][:len(training_curve['days'])] == training_curve['days']
        assert list(record['curve']['equity'][:len(training_curve['days'])]) == training_curve['equity']
        diagnostic = funnel(A, record, policy, nominations, entries['raw'], entries['filtered'], offered, legs)
        write(f'accounts/{name}/funnel.json', diagnostic)
        summary = dict(summarize(record), holding_coverage=diagnostic['coverage'],
            short_coverage=P3.short_coverage(record['trades'], public, A), rules=asdict(policy), paired=False,
            timing_assumption=entries['timing_assumption'], training_curve_prefix_exact=True)
        for y in YEARS:
            summary['holding_coverage']['annual'][y]['any'] = diagnostic['annual'][y]['any']
        write(f'accounts/{name}/summary.json', summary)
        write(f'accounts/{name}/triggers.json', entries['triggers'])
        if name == 'X3_UNION':
            affected = [r for r in entries['triggers'] if r['reason'] == 'trigger' and index_ok[
                int(np.searchsorted(A['days'], r['day']))] and
                len(B['filtered'][int(np.searchsorted(A['days'], r['day']))]) > 0]
            write('x3_timing_assumption.json', dict(causal_intraday_execution_proven=False,
                affected_trigger_quotes=affected,
                note='全日master收盘触发优先预截，会影响更早的盘中报价；仅按任务书的日线同时排序假设报告'))
        print('holdout', name, {y: (summary['holding_coverage']['annual'][y]['covered'],
            round(summary['annual'][y]['ret'], 5)) for y in YEARS}, flush=True)
    assert chosen['chosen'] == read(OUT / 'chosen_a.json')['chosen']
    log('A2 holdout', '三候选完整2026一次评测；选择段权益前缀逐位不变', 'accounts/', 'complete')


def regimes():
    frozen(True)
    write('regimes_started.json', dict(timestamp=datetime.now(timezone.utc).isoformat()))
    results, bases = {}, {}
    with strategy_only():
        A = market()
        nominations = project(A, read(HOME / 'reports/s0_work/picks/IE9.json'))
        mask = (A['days'] >= '2024-01-02') & (A['days'] <= '2026-10-16')
        for name in S.REGIMES:
            noadr = name == 'B2_NOADR'
            width = S.breadth(A, noadr)
            if not noadr:
                old = P3.S.breadth(A)
                assert all(np.array_equal(v, old[k], equal_nan=True) for k, v in width.items())
            base = S.timeline(A, nominations, width['state'])
            variants = []
            for label, change in S.perturbations(noadr):
                w = width if set(change) == {'feedback'} else S.breadth(A, noadr, change)
                other = S.timeline(A, nominations, w['state'], change.get('feedback', .5))
                a, b = base['label'][mask], other['label'][mask]
                variants.append(dict(variant=label, agreement=float(np.mean(a == b)),
                    annual={y: float(np.mean(a[np.char.startswith(A['days'][mask], y)] ==
                        b[np.char.startswith(A['days'][mask], y)])) for y in YEARS},
                    by_state={s: float(np.sum((a == k) & (b == k))) / int(np.sum((a == k) | (b == k)))
                        if np.any((a == k) | (b == k)) else None for k, s in enumerate(P3.R.NAMES)},
                    label=other['label'][mask]))
                print(name, label, round(variants[-1]['agreement'], 6), flush=True)
            prefix = []
            for cut in ('2024-09-30', '2025-09-30', '2026-06-30', '2026-10-16'):
                n = int(np.searchsorted(A['days'], cut, side='right'))
                view = {k: v[:n] if isinstance(v, np.ndarray) and k != 'codes' else v for k, v in A.items()}
                w = S.breadth(view, noadr)
                short = S.timeline(view, {t: cs for t, cs in nominations.items() if t < n}, w['state'])
                assert all(np.array_equal(v, width[k][:n], equal_nan=True) for k, v in w.items())
                assert all(np.array_equal(short[k], base[k][:n]) for k in ('label', 'feedback', 'raw'))
                assert short['outcomes'] == base['outcomes'][:n]
                prefix.append(dict(cut=cut, nights=n, width=True, feedback=True, final_state=True))
            n = int(np.searchsorted(A['days'], '2026-06-30', side='right'))
            changed = dict(A)
            for key in ('close', 'low', 'to20', 'adr'):
                values = np.array(A[key], copy=True)
                values[n:] *= 10 if key in ('close', 'low') else .01
                changed[key] = values
            new_picks = {t: cs if t < n else [] for t, cs in nominations.items()}
            w = S.breadth(changed, noadr)
            other = S.timeline(changed, new_picks, w['state'])
            assert np.array_equal(w['state'][:n], width['state'][:n])
            assert np.array_equal(other['label'][:n], base['label'][:n])
            assert other['outcomes'][:n] == base['outcomes'][:n]
            del changed, other, values
            assert all(r['latest_known'] is None or r['latest_known'] < r['day'] for r in base['outcomes'])
            assert set(base['label']) <= {P3.R.UP, P3.R.WEAK}
            for t in range(1, len(base['label'])):
                if base['label'][t] != base['label'][t - 1]:
                    assert t >= 2 and np.all(base['raw'][t - 2:t + 1] == base['label'][t])
            minimum = min(r['agreement'] for r in variants)
            record = dict(P3.state_record(base, A), full_label=base['label'], feedback=base['feedback'],
                outcomes=base['outcomes'], width=width, stability=dict(minimum=minimum, ok=minimum >= .9,
                variants=variants, worst=min(variants, key=lambda r: r['agreement'])['variant']),
                lookahead=dict(ok=True, prefixes=prefix, future_perturbation=True,
                    latest_feedback_before_session=True, final_state_three_day_confirmation=True),
                post_hoc_revision=True, signal_sha256=sha(HOME / 'reports/s0_work/picks/IE9.json'))
            write(f'regimes/{name}.json', record)
            results[name] = record
            bases[name] = base
        def key(name):
            row = results[name]
            return (-row['stability']['minimum'], -row['counts']['weak']['days'], S.REGIMES.index(name))
        chosen = min(S.REGIMES, key=key)
        write('chosen_b.json', dict(chosen=chosen, enabled=results[chosen]['stability']['ok'],
            minimum=results[chosen]['stability']['minimum'], threshold=.9, keys={n: key(n) for n in S.REGIMES},
            used_accounts=False, used_public_trader=False, post_hoc_revision=True,
            prereg_sha256=sha(PREREG), timestamp=datetime.now(timezone.utc).isoformat(),
            definition_sha256={n: sha(OUT / f'regimes/{n}.json') for n in S.REGIMES}))
        header = 'day,' + ','.join(f'{name}_{field}' for name in S.REGIMES for field in ('state', 'W', 'F', 'rate'))
        lines = [header]
        for t, d in enumerate(A['days']):
            if not '2026-07-01' <= d <= '2026-08-31':
                continue
            cells = [str(d)]
            for name in S.REGIMES:
                base, width = bases[name], results[name]['width']
                cells += [P3.R.NAMES[int(base['label'][t])], str(width['state'][t]),
                          str(base['feedback'][t]), str(base['outcomes'][t]['rate'])]
            lines.append(','.join(cells))
        (OUT / 'july_august_states.csv').write_text('\n'.join(lines) + '\n')
    log('B selection', '只按扰动稳定性、其次防守天数选定，未打开账户或本人评测', 'chosen_b.json', chosen)
    print('chosen B', chosen, results[chosen]['stability']['minimum'], flush=True)


def behaviour():
    frozen(True)
    selected = read(OUT / 'chosen_b.json')
    labels = read(OUT / f"regimes/{selected['chosen']}.json")
    # The saved P3 evaluation portraits are the frozen public observations, never strategy inputs.
    public = read(HOME / 'reports/p3_work/G2.json')
    from studies.trader_replication import ledger
    trades = ledger.load(HOME / 'notes/trades.csv')
    A = market()
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
    master = read(HOME / 'reports/d1_work/master_curve.json')
    m3 = read(HOME / 'reports/m3_work/validation/continuous/curve.json')
    m3_train = read(HOME / 'reports/m3_work/candidates/M3B/curve.json')
    assert m3['days'][:len(m3_train['days'])] == m3_train['days']
    assert m3['equity'][:len(m3_train['equity'])] == m3_train['equity']
    result = dict(chosen=selected['chosen'], enabled=selected['enabled'], scopes=scopes,
        old_accounts={name: P3.curve_description(curve, labels) for name, curve in (('master', master), ('M3B', m3))},
        first_anchor_portraits=portraits, missing_portraits=public['missing_portraits'],
        excluded=excluded, window_only=public['window_only'], dated_counts=dict(Counter(r['date'][:4] for r in dated)),
        density_test=False, selection_used_public=False,
        note='事后修订；票档仍用P3评测池；逐年留一只分解既有曲线，不重新择优或配资')
    write('G2.json', result)
    log('B description', '按选中两态重算方向、票档G2及老账户按年留一', 'G2.json', P3.g2_conclusion(scopes))
    print('G2', P3.g2_conclusion(scopes), flush=True)


def baccount():
    frozen(True)
    selected, chosen_a = read(OUT / 'chosen_b.json'), read(OUT / 'chosen_a.json')
    if not selected['enabled']:
        write('b_account_not_enabled.json', dict(reason='stability below 90%', chosen=selected['chosen']))
        print('B account not enabled: stability below 90%', flush=True)
        return
    write('b_account_started.json', dict(chosen_a_sha256=sha(OUT / 'chosen_a.json'),
        chosen_b_sha256=sha(OUT / 'chosen_b.json'), timestamp=datetime.now(timezone.utc).isoformat()))
    A, metadata, rules, spool, B, nominations, index_ok = strategy_inputs()
    with strategy_only():
        # Reuse the original Z15 generator; route its audit into P4 without touching any P3 file.
        original_out = P3.OUT
        try:
            P3.OUT = OUT
            new_shorts = P3.paired_shorts(A, spool, metadata['config']['short'])
        finally:
            P3.OUT = original_out
        states = np.array(read(OUT / f"regimes/{selected['chosen']}.json")['full_label'])
    record, policy, entries, offered = run_candidate(chosen_a['chosen'], '2026-10-16', A, rules, B,
        nominations, index_ok, states=states, new_shorts=new_shorts)
    save_account('b_account', record)
    legs = read(HOME / 'notes/legs_frozen.json')['legs']
    from studies.trader_replication import ledger
    public = ledger.load(HOME / 'notes/trades.csv')
    diagnostic = funnel(A, record, policy, nominations, entries['raw'], entries['raw'], offered, legs)
    write('b_account/funnel.json', diagnostic)
    summary = dict(summarize(record), holding_coverage=diagnostic['coverage'],
        short_coverage=P3.short_coverage(record['trades'], public, A), rules=asdict(policy),
        selected_a=chosen_a['chosen'], selected_b=selected['chosen'], used_for_selection=False)
    for y in YEARS:
        summary['holding_coverage']['annual'][y]['any'] = diagnostic['annual'][y]['any']
    write('b_account/summary.json', summary)
    log('B account', '在A2首选套用P3 B账户，只报告不再选择', 'b_account/summary.json',
        str({y: summary['annual'][y]['ret'] for y in YEARS}))
    print('B account', {y: (summary['holding_coverage']['annual'][y]['covered'], summary['annual'][y]['ret'])
                        for y in YEARS}, 'short', summary['short_coverage']['covered'], flush=True)


def audit():
    frozen(True)
    from studies.trader_replication import gate
    A, _, rules, _, B, nominations, index_ok = strategy_inputs()
    checks = {}
    with strategy_only():
        for name in S.CANDIDATES:
            full = S.entries(A, nominations, name, B['raw'], index_ok)
            prefixes = []
            for cut in ('2024-09-30', '2025-09-30', '2026-06-30'):
                n = int(np.searchsorted(A['days'], cut, side='right'))
                view = {k: v[:n] if isinstance(v, np.ndarray) and k != 'codes' else v for k, v in A.items()}
                short = S.entries(view, {t: cs for t, cs in nominations.items() if t < n}, name,
                                  B['raw'][:n], index_ok[:n])
                for key in ('raw', 'filtered', 'offered'):
                    assert short[key] == full[key][:n], (name, cut, key)
                prefixes.append(dict(cut=cut, completed_bar_prefix=True))
            record = read(OUT / f'accounts/{name}/trades.json')
            fills, win = gate.check_fills(A, record), gate.check_win(record)
            assert fills['ok'], (name, fills)
            assert win['ok'], (name, win)
            checks[name] = dict(fills=fills, win=win, prefix=prefixes,
                intraday_causality='unproven full-day priority for X3' if name == 'X3_UNION' else
                    'entry and initial stop use prior bars and observed open/level; day0 stop ordering conservative')
    # Determine whether the X3 timing assumption ever changed a real admission in this dataset.
    original = read(HOME / 'reports/d1_work/master_trades.json')
    union = read(OUT / 'accounts/X3_UNION/trades.json')
    x3_fills = [t for t in union if t['kind'] in S.KINDS]
    extras = dict(actual_supplemental_entries=len(x3_fills),
        master_full_ledger_equal=union == original,
        master_curve_equal=read(OUT / 'accounts/X3_UNION/curve.json') == read(HOME / 'reports/d1_work/master_curve.json'))
    if (OUT / 'b_account/summary.json').exists():
        rows = read(OUT / 'b_account/trades.json')
        fills = gate.check_fills(A, rows)
        assert fills['ok'], fills
        checks['B_account'] = dict(fills=fills, win=gate.check_win(rows))
    write('execution_checks.json', dict(accounts=checks, X3=extras,
        prereg_unchanged=True, policy_unchanged=True,
        note='Completed-bar truncation alone cannot validate intrabar X3 priority; disclosed separately.'))
    log('execution audit', '核实全部实际成交价格、胜率、已完成日截断及X3实际补单数', 'execution_checks.json',
        str(extras))
    print('executions audited', extras, flush=True)


def compact():
    """Remove redundant JSON representation, retaining every diagnostic byte in gzip."""
    frozen(True)
    rows = []
    for path in OUT.rglob('funnel.json'):
        before, size = sha(path), path.stat().st_size
        target = Path(str(path) + '.gz')
        assert not target.exists()
        with path.open('rb') as source, gzip.open(target, 'xb') as destination:
            shutil.copyfileobj(source, destination, 1 << 20)
        with gzip.open(target, 'rb') as stream:
            assert hashlib.file_digest(stream, 'sha256').hexdigest() == before
        rows.append(dict(path=str(path.relative_to(OUT)), original_sha256=before,
            compressed_sha256=sha(target), original_bytes=size, compressed_bytes=target.stat().st_size))
        path.unlink()
    write('lossless_compaction.json', dict(files=rows, reclaimed_bytes=sum(
        r['original_bytes'] - r['compressed_bytes'] for r in rows),
        evaluations_changed=False, original_inputs_changed=False))
    log('disk', '仅压缩本轮重复仓位快照多的漏斗JSON，解压后SHA逐位一致', 'lossless_compaction.json',
        f"reclaimed {sum(r['original_bytes'] - r['compressed_bytes'] for r in rows) / 1024**2:.1f} MiB")
    print('losslessly compacted', len(rows), 'funnel artifacts', flush=True)


def report():
    frozen(True)
    a1 = read(OUT / 'a1_summary.json')
    chosen = read(OUT / 'chosen_a.json')
    chosen_b = read(OUT / 'chosen_b.json')
    accounts = {n: read(OUT / f'accounts/{n}/summary.json') for n in S.CANDIDATES}
    funnels = {n: read(OUT / f'accounts/{n}/funnel.json') for n in S.CANDIDATES}
    definitions = {n: read(OUT / f'regimes/{n}.json') for n in S.REGIMES}
    description = read(OUT / 'G2.json')
    checks = read(OUT / 'execution_checks.json')
    name, bname = chosen['chosen'], chosen_b['chosen']
    first, state = accounts[name], definitions[bname]
    baccount_row = read(OUT / 'b_account/summary.json') if chosen_b['enabled'] else None
    def pct(x):
        return '缺失' if x is None else f'{x:+.1%}'
    def number(x, places=2):
        return '缺失' if x is None else f'{x:.{places}f}'
    def holdings(row):
        return '、'.join(f"{row['holding_coverage']['annual'][y]['covered']}/{row['holding_coverage']['annual'][y]['n']}"
                        for y in YEARS)
    july = [label for day, label in zip(state['calendar'], state['label']) if day.startswith('2026-07')]
    july_counts = Counter(P3.R.NAMES[k] for k in july)
    lines = ['# P4：点名以后怎么买，以及两态行情的事后修订', '',
        f"**没有找到比原master覆盖更多、又通过两年不亏底线的入场版本。** 按任务书选中{name}，"
        f"2024/2025/2026早买依次为{holdings(first)}，收益为"
        + '、'.join(pct(first['annual'][y]['ret']) for y in YEARS) + '。', '',
        'X1和X2把2025早买提高到9/22，但选择段都亏损，已按任务书剔除；'
        f"X3实际新增补单{checks['X3']['actual_supplemental_entries']}笔，完整账户与master"
        + ('逐位相同，补充通道没有改变实际持仓。' if checks['X3']['master_full_ledger_equal'] else '有差异，明细见执行核查。'), '',
        f"**行情选中{bname}，最低扰动重合{chosen_b['minimum']:.2%}，"
        + ('通过90%稳定线。**' if chosen_b['enabled'] else '未过90%，不启用。**')
        + f"2026年7月进攻{july_counts['up']}天、防守{july_counts['weak']}天，大部分时间仍在进攻。"
        '这只是定义稳定，不能据此说已经复刻本人的行情判断。', '',
        '**B是看过P3以后的事后修订。** 2024/2025用于A2选择；2026已被反复查看，只能叫历史留出*。'
        '登记版、看板和旧结果全部保留，本轮未联网、未拉数据、未提交git。', '']
    if baccount_row:
        lines += [f"套用P3 B账户后，三年早买为{holdings(baccount_row)}，收益为"
            + '、'.join(pct(baccount_row['annual'][y]['ret']) for y in YEARS)
            + f"，空头覆盖{baccount_row['short_coverage']['covered']}/37。它只作报告，不据此重选A或行情。", '']
    lines += ['## A1：损失集中在哪里', '',
        '主尺子完全沿用H1/P3：首实际lot在首锚点前3日至峰前1日入场、剩余涨幅至少一半；后续加仓或重试不重置。'
        '早买后3个交易日内止损、峰前未再入的情况单列层8，它仍计入主覆盖，所以层8+9等于早买。'
        '原master、C2/A的真实成交不被诊断用K=3投影追溯删掉，故某段可以未被K=3点名而仍实际早买。', '',
        '层序：1没被点名；2没有可执行买点；3被每日预截队列挤掉；4仓位/资金挡住；5 IDX50；'
        '6同票/冷却；7首笔太晚；8早买后很快止损未回；9其余早买。逐夜先记录所有路径，段级取走得最远的路径。', '',
        'master允许融资，现金为负不会独立拒单；单票50%首先限制买入大小，总敞口空间不足才可能拒单。'
        '逐点保留现金、总仓占用和剩余额度，不把缩小成交误写成没买到。master没有额外交易冷却，'
        '已有同票不能重复首开；10日冷却属于K=3点名投影。', '',
        '| 系统 | 年 | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 早买 | 任意成交 |',
        '|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|']
    for system, row in a1.items():
        for y, r in row['annual'].items():
            lines.append('| ' + ' | '.join([system, y] + [str(r['layers'][str(k)]) for k in LAYERS] +
                [f"{r['early']}/{r['n']}", f"{r['any']}/{r['n']}"]) + ' |')
    lines += ['', '层1以外，单层解除后能补回早买的乐观上限如下。这里只数失败段，假定后续障碍全部消失；'
        '不是实际反事实收益，不能相加。层8已覆盖，解除它对早买数的增量为0，但可能改善持有。', '',
        '| 系统 | 层2 | 层3 | 层4 | 层5 | 层6 | 层7 | 层8增量/可改善持有 |',
        '|---|---:|---:|---:|---:|---:|---:|---:|']
    for system, row in a1.items():
        cells = [system] + [str(row['optimistic_upper'][str(k)]['extra_early']) for k in range(2, 8)]
        cells.append('0/' + str(row['optimistic_upper']['8']['extra_surviving_early']))
        lines.append('| ' + ' | '.join(cells) + ' |')
    lines += ['', 'IE9这条线上，没有早期点名占18段；有点名后还漏20段：11段没有可执行买点（含点名不续留）、'
        '3段被IDX50挡住、6段首笔太晚。只有改变成交层，无法补齐上游未点名的缺口。'
        '逐段的全部夜晚、被谁挤掉、每个真实准入点的权益/现金/总敞口/持仓票在 '
        '[A1工件](p4_work/a1/)；[A1冻结诊断](p4_work/A1_CN.md)先于预登记生成。', '',
        '## A2：点名不变，换入场', '',
        '全部固定S0保存的IE9原顺序K=3新名，10日冷却已经在输入中完成。三个候选均为paired:false，'
        '只动trade/allocate。逐字原话及完整公式在[预登记](../notes/PREREG_P4_CN.md)：'
        'X1为次日开盘；X2为后三天首次越点名夜高点；X3为master原触发优先后补X2。'
        '止损、退出、加仓、50%单票/2.8倍总仓、0.5%/0.8%反馈和S7均延续master。'
        'master实际多头21EMA、空头9EMA，未借“9/21”概括换规则。', '',
        '先剔除2024或2025亏损者，再比两年较差早买比例，平手取两年笔数较少者。'
        f"选择段合格者为{chosen['eligible']}；全体失败回退={chosen['all_failed_return_floor']}。"
        'chosen_a.json先写，之后只运行一次2026；三条账户2024/2025权益前缀逐位一致。', '',
        '| 候选 | 年 | 早买/分母 | 任意成交 | 收益 | 胜率 | 盈亏比 | 开仓（多/空） | 持有均天（赢/亏） |',
        '|---|---|---:|---:|---:|---:|---:|---:|---:|']
    for candidate, row in accounts.items():
        for y, r in row['annual'].items():
            c = row['holding_coverage']['annual'][y]
            lines.append(f"| {candidate} | {y} | {c['covered']}/{c['n']} | {c['any']}/{c['n']} | {pct(r['ret'])} | "
                f"{r['win']:.1%} | {number(r['payoff'])} | {r['n']}（{r['longs']}/{r['shorts']}） | "
                f"{number(r['days'])}（{number(r['days_win'])}/{number(r['days_loss'])}） |")
    lines += ['', '每年按首锚点归属覆盖，笔数按开仓年；胜率和平均赚亏剔除期末估值。'
        '本人2024公开104胜319负、+283%、平均赚15%/亏3%；2025为209胜731负、+969.8%、平均赚14.1%/亏2.1%。'
        '2026只有至7月+869%的既有资料，完整年参照及本人结构化持有天数缺失。', '',
        '| 候选/年 | 收益差（百分点） | 财富比对数差 | 胜率差（百分点） | 笔数差 | 盈亏比差 | 持有期差 |',
        '|---|---:|---:|---:|---:|---:|---:|']
    for candidate, row in accounts.items():
        for y, r in row['annual'].items():
            g = r['gaps']
            lines.append('| ' + ' | '.join([candidate + '/' + y] + [number(g[k], 3) for k in (
                'return_percentage_points', 'log_wealth', 'win_percentage_points', 'count', 'payoff', 'days')]) + ' |')
    lines += ['', '2026至7月底的同期收益对照保存在每个summary.json的matched_public_period；'
        '未把10月末收益和本人7月收益强行当同期限。每个候选完整逐夜九层漏斗如下，路径见accounts/*/funnel.json。', '',
        '| 候选 | 年 | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 |',
        '|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|']
    for candidate, row in funnels.items():
        for y, r in row['annual'].items():
            lines.append('| ' + ' | '.join([candidate, y] + [str(r['layers'][str(k)]) for k in LAYERS]) + ' |')
    lines += ['', '**执行边界。** X1用前夜低点；若其不低于实际买价，按原公式拒绝，不偷偷挪止损。'
        'X2严格越前高才触发，价格第一次触发后即消费，即使被指数/队列/仓位挡住也不追认重试。'
        '同根日K既越前高又触止损时，保守按先止损处理；无法证明日内先后。', '',
        'X3按任务书全日master优先、再补盘中报价，存在收盘触发在盘中尚未知的时序假设。'
        f"本次实际补单{checks['X3']['actual_supplemental_entries']}笔，"
        f"与master台账逐位相同={checks['X3']['master_full_ledger_equal']}，"
        '因此不能把X3的基线成绩当成补单有效的证据。受排序假设影响的报价保留在x3_timing_assumption.json；'
        '完成日截断一致也不能证明这种盘中优先关系。', '',
        '## B：行情改成两态，属于事后修订', '',
        'B1防守=变窄或反馈差，进攻=变宽且反馈好；B2在此基础上彻底删去宽度池ADR条件，只留1亿美元成交额与有效价格。'
        '宽度L−G及10/30EMA、自己的前10晚K=3反馈定义沿用P3，分量与最终状态均3日确认。'
        '没有常态；暖机从防守开始。状态t只用t−1及以前。只按最差扰动重合率选，平手取防守日多者，未使用老曲线或本人标签。', '',
        '| 定义 | 最低重合 | 最差扰动 | 扰动数 | 进攻天/段 | 防守天/段 | 截断/未来扰动 |',
        '|---|---:|---|---:|---:|---:|---|']
    for candidate, row in definitions.items():
        st = row['stability']
        lines.append(f"| {candidate} | {st['minimum']:.2%} | {st['worst']} | {len(st['variants'])} | "
            f"{row['counts']['up']['days']}/{row['counts']['up']['episodes']} | "
            f"{row['counts']['weak']['days']}/{row['counts']['weak']['episodes']} | 通过 |")
    lines += ['', '| 定义/年 | 进攻天/段 | 防守天/段 |', '|---|---:|---:|']
    for candidate, row in definitions.items():
        for y, r in row['annual'].items():
            lines.append(f"| {candidate}/{y} | {r['up']['days']}/{r['up']['episodes']} | {r['weak']['days']}/{r['weak']['episodes']} |")
    lines += ['', '以下为2026年7–8月逐日最终状态（进=进攻，防=防守）。W、F及反馈比例另保存在 '
        '[逐日CSV](p4_work/july_august_states.csv)。两态稳定线不保证会捕捉整个亏损月，也不保证G2过关。', '',
        '| 交易日 | B1_OR | B2_NOADR |', '|---|---|---|']
    for day, a, b in zip(state['calendar'], definitions['B1_OR']['label'], definitions['B2_NOADR']['label']):
        if '2026-07-01' <= day <= '2026-08-31':
            lines.append(f"| {day} | {'进' if a == P3.R.UP else '防'} | {'进' if b == P3.R.UP else '防'} |")
    lines += ['', '## 老账户分状态：只描述，不重配资金', '',
        f"用选中{bname}对两条旧账户的实际日收益复合，按年留一的其余两年/留出年完整保存在G2.json。"
        '未按收益挑定义，不能把这些分组收益当成重新择时后的收益。', '',
        '| 旧账户/年 | 进攻日收益 | 防守日收益 |', '|---|---:|---:|']
    for system, row in description['old_accounts'].items():
        for y, r in row['annual'].items():
            lines.append(f"| {system}/{y} | {pct(r['up']['ret'])} | {pct(r['weak']['ret'])} |")
    lines += ['', '## 本人的方向与票档G2', '', P3.g2_conclusion(description['scopes']), '',
        '方法保持P3：方向用有可靠日期的exact/chart交易，window另列；成交额和ADR票档用48段首锚点当晚在P3原流动池的分位，'
        '不随着B2删ADR而换评测池。整episode置换999次、种子0、双侧p；至少15笔/3个有交易段、p<0.1且至少2个留一同向才pass。'
        f"有日期样本{description['dated_counts']}；票档缺输入{len(description['missing_portraits'])}段保留。"
        '不检验记录密度，不把样本不足写成行为与行情无关。', '',
        '| 范围/指标 | 状态 | 笔/段 | 均值 | 段效应 | p | 留一同向 | 判定 |',
        '|---|---|---:|---:|---:|---:|---:|---|']
    for scope, r in description['scopes'].items():
        for metric, values in r['metrics'].items():
            for stname in ('up', 'weak'):
                v = values['states'][stname]
                lines.append(f"| {scope}/{metric} | {stname} | {v['n']}/{v['observed_episodes']} | {number(v['mean'], 3)} | "
                    f"{number(v['effect'], 3)} | {number(v['p'], 3)} | {v['leave_one_same_direction']} | {v['status']} |")
    if baccount_row:
        lines += ['', '## 在A2首选上套用B账户（只报告）', '',
            '按P3 B规则用两态替换IDX50和idx_pb16；进攻多头×1.6，防守不开新多，已有多头继续原管理。'
            '空头只在防守开，原Z15加首次50EMA反抽和已完成周线条件；每日仍一名，首反抽无成交也消费。'
            '原Z15成交位须已经不低于前夜50EMA，不能用更晚的日高追认条件。', '',
            '| 年 | 早买 | 任意成交 | 收益 | 开仓（多/空） | 胜率 | 盈亏比 |',
            '|---|---:|---:|---:|---:|---:|---:|']
        for y, r in baccount_row['annual'].items():
            h = baccount_row['holding_coverage']['annual'][y]
            lines.append(f"| {y} | {h['covered']}/{h['n']} | {h['any']}/{h['n']} | {pct(r['ret'])} | "
                f"{r['n']}（{r['longs']}/{r['shorts']}） | {r['win']:.1%} | {number(r['payoff'])} |")
        lines += ['', f"有日期空单覆盖{baccount_row['short_coverage']['covered']}/37；股票面板没有的ETF也保留在分母，"
            '逐单前3至后1交易日窗口与缺行情标记保存在b_account/summary.json。']
    else:
        lines += ['', '选中定义未过90%，按任务书未启用B账户。']
    lines += ['', '## 验证与复算', '',
        '入口：`python -m studies.martin_luk.p4_research`，阶段为freeze → a1 → preregister → train → validate → '
        'regimes → behaviour → baccount → audit → report → finish。正式评测工件使用独占创建，拒绝无记录覆盖。'
        '预登记在A1之后冻结，chosen_a在2026之前、chosen_b在旧曲线和本人G2之前落盘。'
        '策略运行使用标签读入拦截，入口拒绝网络、子进程和P4目录外写入；全轮单进程单线程、60% CPU、900MiB scope。'
        '市场面板只读memmap，宽度按日期流式计算，未复制全量面板或构造N×N。', '',
        '原master、C2/A完整账及曲线逐位复放；三候选选择期权益前缀一致；每笔实际成交均核对在当日高低区间内。'
        'B四个截断点、未来价格/流动性/点名扰动、反馈成熟时点和最终3日确认均通过。'
        'X3盘中优先的日K限制单列，未拿普通截断检查掩盖。', '',
        '| 测试组 | 项数 | 结果 |', '|---|---:|---|']
    for suite in ('custody', 'trader_replication', 'martin_luk', 'trader_screens'):
        text = (OUT / f'tests/{suite}.log').read_text()
        match = re.search(r'Ran (\d+) tests? in ([\d.]+)s', text)
        passed = (OUT / f'tests/{suite}.exit').read_text().strip() == '0'
        details = [label + m[1] for pattern, label in ((r'expected failures=(\d+)', '预期失败'),
                   (r'skipped=(\d+)', '跳过')) if (m := re.search(pattern, text))]
        status = ('通过' if passed else '失败') + ('（' + '、'.join(details) + '）' if details else '')
        lines.append(f"| {suite} | {match[1] if match else '缺失'} | {status} |")
    lines += ['', '看板跳过的1项需要指定日期的港股分钟K，本地该日没有数据；单独以verbose核对跳过原因，'
        '没有为补测试联网。trader_replication的1项预期失败沿用既有测试，未改断言。']
    lines += ['', '资源峰值、保护清单核对、所有输入和工件SHA与完成状态保存在 '
        '[completion.json](p4_work/completion.json)。重复仓位快照较多的funnel.json无损保存为funnel.json.gz，'
        '解压后SHA与原字节相同，压缩清单在lossless_compaction.json；原输入和所有评测结果未变。'
        '没有登记采用；只否定本轮日K版本，不能据此否定本人方法。']
    (HOME / 'reports/P4_CN.md').write_text('\n'.join(lines) + '\n')
    log('report', '按先结论、全候选、全部年份和执行边界生成中文报告', 'P4_CN.md', 'written')
    print('P4 report written', flush=True)


def finish():
    protocol = frozen(True)
    manifest = read(OUT / 'preregistered.json')
    assert sha(HOME / 'p4_policy.py') == manifest['strategy_sha256']
    tests = {}
    for name in ('custody', 'trader_replication', 'martin_luk', 'trader_screens'):
        path = OUT / f'tests/{name}.log'
        text = path.read_text()
        match = re.search(r'Ran (\d+) tests? in ([\d.]+)s', text)
        code = int((OUT / f'tests/{name}.exit').read_text())
        assert code == 0 and match and re.search(r'^OK(?:\s|$)', text, re.M), (name, text[-1500:])
        skips, expected = re.search(r'skipped=(\d+)', text), re.search(r'expected failures=(\d+)', text)
        tests[name] = dict(n=int(match[1]), seconds=float(match[2]), exit_code=code, sha256=sha(path),
                          skipped=int(skips[1]) if skips else 0,
                          expected_failures=int(expected[1]) if expected else 0)
    changed = [p for p, h in protocol['protected'].items() if not (ROOT / p).is_file() or sha(ROOT / p) != h]
    write('protected_verification.json', dict(ok=not changed, files=len(protocol['protected']), changes=changed))
    assert not changed, changed[:10]
    chosen, chosen_b = read(OUT / 'chosen_a.json'), read(OUT / 'chosen_b.json')
    holdout = read(OUT / 'holdout_started.json')
    assert holdout['chosen_a_sha256'] == sha(OUT / 'chosen_a.json')
    assert chosen['timestamp'] < holdout['timestamp']
    for name, h in chosen['summary_sha256'].items():
        assert sha(OUT / f'train/{name}/summary.json') == h
    for name, h in chosen_b['definition_sha256'].items():
        assert sha(OUT / f'regimes/{name}.json') == h
    execution = read(OUT / 'execution_checks.json')
    runs = {p.stem: read(p) for p in (OUT / 'runs').glob('*.json')}
    a = read(OUT / f"accounts/{chosen['chosen']}/summary.json")
    b = read(OUT / 'b_account/summary.json') if chosen_b['enabled'] else None
    description = read(OUT / 'G2.json')
    state = read(OUT / f"regimes/{chosen_b['chosen']}.json")
    a1 = read(OUT / 'a1_summary.json')
    sources = dict(P3.SOURCES, **SOURCES)
    for run in runs.values():
        sources.update(run['sources'])
    write('sources.json', sources)
    artifacts = {str(p.relative_to(OUT)): sha(p) for p in OUT.rglob('*') if p.is_file()
                 and p.name not in ('run.lock', 'artifact_manifest.json', 'completion.json', 'decisions.tsv')}
    write('artifact_manifest.json', artifacts)
    complete = dict(task='PLAN_P4_CN', status='complete', prereg_sha256=sha(PREREG),
        strategy_sha256=sha(HOME / 'p4_policy.py'), runner_sha256=sha(HOME / 'p4_research.py'),
        report_sha256=sha(HOME / 'reports/P4_CN.md'), artifact_manifest_sha256=sha(OUT / 'artifact_manifest.json'),
        chosen_a=chosen, a=dict(annual=a['annual'], holding=a['holding_coverage']['annual'],
            short=a['short_coverage']['covered']), chosen_b=chosen_b,
        b=dict(annual=b['annual'], holding=b['holding_coverage']['annual'], short=b['short_coverage']['covered']) if b else None,
        A1={n: row['layers'] for n, row in a1.items()},
        G2={scope: {metric: {s: dict(status=v['status'], p=v['p']) for s, v in row['states'].items()}
                   for metric, row in data['metrics'].items()} for scope, data in description['scopes'].items()},
        old_accounts=description['old_accounts'], tests=tests, execution=execution,
        protected=dict(ok=True, files=len(protocol['protected']), changes=[]),
        selected_before_holdout=True, post_hoc_revision=True, offline=True, downloaded_data=False,
        workspace_git_commits=0, registry_or_board_modified=False,
        maximum_recorded_rss_mib=max(r['resources']['peak_rss_mib'] for r in runs.values()),
        resources=P3.resources(), disk_free_bytes=shutil.disk_usage(ROOT).free)
    write('completion.json', complete)
    lines = []
    for name, row in a1.items():
        lines.append(f"A1 {name}：1–9层=" + '/'.join(str(row['layers'][str(k)]) for k in LAYERS)
                     + '（8+9为早买）。')
    lines.append(f"A2选中{chosen['chosen']}：2024/25/26早买="
        + '/'.join(str(a['holding_coverage']['annual'][y]['covered']) for y in YEARS) + '段（分母9/22/17），收益='
        + '/'.join(f"{a['annual'][y]['ret']:+.2%}" for y in YEARS) + '。')
    july = Counter(P3.R.NAMES[k] for d, k in zip(state['calendar'], state['label']) if d.startswith('2026-07'))
    lines.append(f"B选中{chosen_b['chosen']}：稳定性{chosen_b['minimum']:.2%}，"
                 + ('通过' if chosen_b['enabled'] else '未通过')
                 + f"90%；2026年7月进攻{july['up']}天、防守{july['weak']}天。")
    for name, data in description['old_accounts'].items():
        lines.append(f"老{name}进攻/防守收益（2024/25/26）：" + '；'.join(
            f"{data['annual'][y]['up']['ret']:+.1%}/{data['annual'][y]['weak']['ret']:+.1%}" for y in YEARS) + '。')
    if b:
        lines.append('套B账户2024/25/26：早买=' + '/'.join(str(b['holding_coverage']['annual'][y]['covered']) for y in YEARS)
            + '，收益=' + '/'.join(f"{b['annual'][y]['ret']:+.2%}" for y in YEARS)
            + f"；空头{b['short_coverage']['covered']}/37（只报告）。")
    lines.append('四组测试全部通过；P4_CN.md、p4_work/completion.json完成，登记/看板未变。')
    assert len(lines) <= 10
    (OUT / 'terminal_summary.txt').write_text('\n'.join(lines) + '\n')
    log('finish', '四组测试、受保护文件及选择时序全部核验后完成', 'completion.json', 'complete')
    print('\n'.join(lines), flush=True)


def offline():
    sys.dont_write_bytecode = True
    def guard(event, args):
        if event in ('socket.connect', 'socket.bind', 'socket.getaddrinfo', 'subprocess.Popen', 'os.system'):
            raise PermissionError('P4 offline single-process boundary')
        if event == 'open' and not isinstance(args[0], int) and args[2] & (
                os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND):
            path = Path(os.fsdecode(args[0])).resolve()
            if not path.is_relative_to(OUT.resolve()) and path not in (PREREG, HOME / 'reports/P4_CN.md'):
                raise PermissionError('P4 output boundary: ' + str(path))
    sys.addaudithook(guard)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=('freeze', 'a1', 'preregister', 'train', 'validate',
                                         'regimes', 'behaviour', 'baccount', 'audit', 'compact', 'report', 'finish'))
    args = parser.parse_args()
    offline()
    OUT.mkdir(parents=True, exist_ok=True)
    with (OUT / 'run.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        r = P3.resources()
        assert r['cpu_max'] == '60000 100000' and r['memory_max'] == str(900 * 1024 * 1024) and r['threads'] == '1', r
        assert shutil.disk_usage(ROOT).free >= 1024**3, 'clean only duplicate P4 intermediates before proceeding'
        print('start', args.stage, r, flush=True)
        globals()[args.stage]()
        run_path = f'runs/{args.stage}.json'
        if args.stage == 'report' and (OUT / run_path).exists():
            run_path = f'runs/report_{len(list((OUT / "runs").glob("report*.json"))) + 1}.json'
        write(run_path, dict(stage=args.stage, sources=dict(P3.SOURCES, **SOURCES),
            resources=P3.resources(), disk_free_bytes=shutil.disk_usage(ROOT).free))


if __name__ == '__main__':
    main()
