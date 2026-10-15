#!/usr/bin/env python3
"""Temporary descriptive scan of named candidates via OpenD + signals.evaluate.

RESEARCH STATUS: studies/trend_breakout TF1–TF14 concluded REJECT (no out-of-sample
tradable alpha). notes/ONLINE.md online list is NOT implemented. This script only
applies the same entry/line rules as a composite filter for description — it is
NOT validated alpha and must not be treated as a trading signal.

Usage (repo root):
  PYTHONUTF8=1 /home/box/futu/venv/bin/python -m studies.trend_breakout.scan_candidates
"""
from __future__ import annotations

import json
import sys
import traceback
from datetime import date, timedelta
from pathlib import Path

import numpy as np

from studies.trend_breakout import panel, signals, sources

# --- hard-coded composite filter (printed at run start) ---
FILTER_RULES = """
复合过滤规则（写死；研究结论为负，仅描述性过滤）:
  1. 买入候选(buy): 面板最后交易日至少 2 条入场规则同时为 True
  2. 弱信号(weak): 恰好 1 条入场规则为 True（观察，不进买卖清单）
  3. 破线(sell_break): 近 LOOKBACK 根内曾触发某条入场，且按该规则跟踪线
     （ratchet 则只上移）推演后，当日收盘跌破止损线
  4. 其余(none)
  评估规则: TF1 T1–T5 + TF2 U1–U5（U1/U5 需池内≥20只排名，小池通常不触发）
  数据: sources.OpenDSource.bars = get_cur_kline 订阅，不扣历史K额度
"""

US_CODES = [
    'US.MU', 'US.MRVL', 'US.BKH', 'US.CEG', 'US.GOOGL',
    'US.ORCL', 'US.BE', 'US.ILMN', 'US.NVDA',
]
HK_CODES = [
    'HK.09976', 'HK.01347', 'HK.00981', 'HK.03696', 'HK.00600',
]
# TF1 + cheap TF2; pool-rank rules U1/U5 need >=20 liquid names to fire
RULES = ('T1', 'T2', 'T3', 'T4', 'T5', 'U1', 'U2', 'U3', 'U4', 'U5')
LOOKBACK = 60  # trading bars to search for a prior entry when checking break
MIN_BARS_WANT = 260
OUT_JSON = Path('reports/scan_daily_candidates_2026-10-14.json')
OUT_MD = Path('reports/scan_daily_candidates_2026-10-14.md')


def _rows_to_map(raw_rows):
    """[(code,date,o,h,l,c,v,t), ...] -> {date: [o,h,l,c,v,t]}"""
    out = {}
    for _c, d, o, h, l, cl, v, t in raw_rows:
        out[d] = [float(o), float(h), float(l), float(cl), float(v), float(t)]
    return out


def fetch_market(market, codes, start, end, log):
    """Pull bars+actions via sources; return (raw_dict, actions_dict, gaps)."""
    src = sources.get(market)
    raw, acts, gaps = {}, {}, []
    try:
        log(f'[{market}] OpenDSource.describe={src.describe()}')
        log(f'[{market}] history_quota(snapshot, not used for bars)={src.history_quota()}')
        log(f'[{market}] bars({len(codes)} codes, {start}..{end}) via get_cur_kline…')
        for code, raw_rows, _qfq in src.bars(codes, start, end):
            if not raw_rows:
                gaps.append({'code': code, 'reason': 'bars empty or get_cur_kline failed'})
                log(f'  GAP {code}: no bars')
                continue
            raw[code] = _rows_to_map(raw_rows)
            n = len(raw[code])
            log(f'  {code}: {n} raw bars, last={max(raw[code])}')
            if n < MIN_BARS_WANT:
                log(f'  WARN {code}: only {n} bars (<{MIN_BARS_WANT}); indicators may not be ready')
            try:
                act_rows = src.actions(code, raw_rows, _qfq)
                acts[code] = [(ex, float(a), float(b)) for _c, ex, a, b in act_rows]
                log(f'  {code}: {len(acts[code])} rehab actions')
            except Exception as exc:
                gaps.append({'code': code, 'reason': f'actions failed: {exc}'})
                log(f'  GAP {code}: actions: {exc}')
                # still keep bars; factors() with no actions = all 1.0
                acts.setdefault(code, [])
    except Exception as exc:
        log(f'[{market}] FATAL fetch: {exc}')
        traceback.print_exc()
        for c in codes:
            if c not in raw:
                gaps.append({'code': c, 'reason': f'market fetch failed: {exc}'})
    finally:
        src.close()
    return raw, acts, gaps


def last_valid_row(close_col):
    """Index of last non-NaN close; -1 if none."""
    idx = np.flatnonzero(~np.isnan(close_col))
    return int(idx[-1]) if len(idx) else -1


def simulate_stop(entry_col, line_col, close_col, ratchet, end_t, lookback):
    """From most recent entry in (end_t-lookback, end_t], ratchet/follow stop; return
    (entry_t, stop_before_end, broken_at_end) or (None, None, False).
    broken = close[end_t] < stop as known at end_t-1 (backtest exit rule), or if
    we never armed a stop yet False.
    """
    lo = max(0, end_t - lookback)
    entries = np.flatnonzero(np.nan_to_num(entry_col[lo:end_t + 1]) > 0)
    if len(entries) == 0:
        return None, None, False
    # most recent entry index relative to full series
    t0 = lo + int(entries[-1])
    if t0 >= end_t:
        # entry today: not yet a hold to break; treat as not broken
        return t0, float(line_col[t0]) if not np.isnan(line_col[t0]) else None, False
    stop = float(line_col[t0])
    if np.isnan(stop):
        return t0, None, False
    # walk t0+1 .. end_t-1 updating stop after each close decision (mirror backtest)
    # exit decided when close[t] < stop (stop is as-of prior update = start-of-day stop)
    for t in range(t0 + 1, end_t + 1):
        if np.isnan(close_col[t]):
            continue
        if close_col[t] < stop:
            if t == end_t:
                return t0, stop, True
            # broke earlier inside lookback: no longer "holding"; ignore that entry
            # search for a later entry after this break
            return simulate_stop_after(entry_col, line_col, close_col, ratchet, end_t, t + 1)
        # update stop with today's line
        if not np.isnan(line_col[t]):
            stop = max(stop, float(line_col[t])) if ratchet else float(line_col[t])
    return t0, stop, False


def simulate_stop_after(entry_col, line_col, close_col, ratchet, end_t, start_search):
    """Re-find entry at/after start_search up to end_t."""
    if start_search > end_t:
        return None, None, False
    entries = np.flatnonzero(np.nan_to_num(entry_col[start_search:end_t + 1]) > 0)
    if len(entries) == 0:
        return None, None, False
    t0 = start_search + int(entries[-1])
    # recurse via the same function by temporarily zeroing older entries — simpler: inline
    if t0 >= end_t:
        return t0, float(line_col[t0]) if not np.isnan(line_col[t0]) else None, False
    stop = float(line_col[t0])
    if np.isnan(stop):
        return t0, None, False
    for t in range(t0 + 1, end_t + 1):
        if np.isnan(close_col[t]):
            continue
        if close_col[t] < stop:
            if t == end_t:
                return t0, stop, True
            return simulate_stop_after(entry_col, line_col, close_col, ratchet, end_t, t + 1)
        if not np.isnan(line_col[t]):
            stop = max(stop, float(line_col[t])) if ratchet else float(line_col[t])
    return t0, stop, False


def analyze_panel(p, market, log):
    """Return list of per-code result dicts."""
    ind = signals.indicators(p)
    pool = ~np.isnan(ind['close'])
    # precompute entry/line per rule
    evals = {}
    for rule in RULES:
        entry, line, ratchet = signals.evaluate(ind, rule, pool=pool)
        evals[rule] = (entry, line, ratchet)

    results = []
    for j, code in enumerate(p['codes']):
        code = str(code)
        t = last_valid_row(p['close'][:, j])
        if t < 0:
            results.append({
                'code': code, 'market': market, 'conclusion': 'none',
                'fail': 'no close bars after adjust', 'triggered': [],
            })
            continue
        asof = str(p['dates'][t])
        close = float(p['close'][t, j])
        raw_close = float(p['raw_close'][t, j])
        ready = bool(np.nan_to_num(ind['ready'][t, j]) > 0)
        trend_ok = bool(np.nan_to_num(ind['trend_ok'][t, j]) > 0)
        n_bars = int(np.sum(~np.isnan(p['close'][:t + 1, j])))

        triggered = []
        rule_detail = {}
        for rule in RULES:
            entry, line, ratchet = evals[rule]
            on = bool(np.nan_to_num(entry[t, j]) > 0)
            lv = line[t, j]
            lv_f = None if np.isnan(lv) else float(lv)
            rule_detail[rule] = {
                'entry_today': on,
                'line_name': signals.LINES[rule],
                'line': lv_f,
                'ratchet': bool(ratchet),
            }
            if on:
                triggered.append(rule)

        # trail lines of interest for report
        trails = {}
        for name in ('chandelier', 'donchian20', 'supertrend', 'atr_trail'):
            v = ind[name][t, j]
            trails[name] = None if np.isnan(v) else float(v)

        # break detection across rules that had a recent entry
        breaks = []
        for rule in RULES:
            entry, line, ratchet = evals[rule]
            et, stop, broken = simulate_stop(
                entry[:, j], line[:, j], ind['close'][:, j], ratchet, t, LOOKBACK)
            if et is not None:
                rule_detail[rule]['prior_entry_date'] = str(p['dates'][et])
                rule_detail[rule]['stop_before_close'] = stop
                rule_detail[rule]['broken_today'] = broken
            if broken:
                breaks.append({
                    'rule': rule,
                    'entry_date': str(p['dates'][et]),
                    'stop': stop,
                    'line_name': signals.LINES[rule],
                })

        if len(triggered) >= 2:
            conclusion = 'buy'
        elif breaks:
            conclusion = 'sell_break'
        elif len(triggered) == 1:
            conclusion = 'weak'
        else:
            conclusion = 'none'

        row = {
            'code': code,
            'market': market,
            'asof': asof,
            'n_bars': n_bars,
            'ready': ready,
            'trend_ok': trend_ok,
            'close_adj': close,
            'raw_close': raw_close,
            'triggered': triggered,
            'n_triggered': len(triggered),
            'trails': trails,
            'breaks': breaks,
            'rules': rule_detail,
            'conclusion': conclusion,
            'fail': None,
        }
        results.append(row)
        log(f'  {code} asof={asof} close={close:.4f} trig={triggered} '
            f'breaks={[b["rule"] for b in breaks]} => {conclusion}')
    return results


def write_reports(payload, log):
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    log(f'wrote {OUT_JSON}')

    buy = [r for r in payload['results'] if r.get('conclusion') == 'buy']
    weak = [r for r in payload['results'] if r.get('conclusion') == 'weak']
    sell = [r for r in payload['results'] if r.get('conclusion') == 'sell_break']
    none = [r for r in payload['results'] if r.get('conclusion') == 'none']
    fails = payload.get('gaps', [])

    lines = []
    lines.append('# 日K候选扫描 2026-10-14（描述性过滤）')
    lines.append('')
    lines.append('> **声明**：`studies/trend_breakout` TF1–TF14 研究结论为 **REJECT**（无样本外可交易 alpha）；'
                 '`notes/ONLINE.md` 在线名单未实现。本结果仅为同一套入场/跟踪线规则的复合过滤，'
                 '**不是**已验证 alpha，不可当作交易信号。')
    lines.append('')
    lines.append('## 复合过滤规则')
    lines.append('```')
    lines.append(FILTER_RULES.strip())
    lines.append('```')
    lines.append('')
    lines.append(f'- 扫描日（文件日）: 2026-10-14')
    lines.append(f'- Python: {payload.get("python")}')
    lines.append(f'- 命令: `{payload.get("command")}`')
    lines.append(f'- 规则集: {", ".join(RULES)}')
    lines.append('')

    def table(title, rows, extra_cols=None):
        lines.append(f'## {title}')
        if not rows:
            lines.append('（无）')
            lines.append('')
            return
        lines.append('| 代码 | 市场 | 数据截止 | 收盘(复权) | 触发规则 | 跟踪线/破线 | 结论 |')
        lines.append('|---|---|---|---:|---|---|---|')
        for r in rows:
            trig = ','.join(r.get('triggered') or []) or '-'
            if r.get('conclusion') == 'sell_break' and r.get('breaks'):
                br = '; '.join(f"{b['rule']}@{b['entry_date']} stop={b['stop']:.4f}" for b in r['breaks'])
            else:
                ch = (r.get('trails') or {}).get('chandelier')
                br = f"chandelier={ch:.4f}" if isinstance(ch, float) else '-'
            lines.append(
                f"| {r['code']} | {r.get('market','')} | {r.get('asof','')} | "
                f"{r.get('close_adj', float('nan')):.4f} | {trig} | {br} | {r.get('conclusion')} |"
            )
        lines.append('')

    table('买入清单（≥2 条入场）', buy)
    table('破线卖出清单', sell)
    table('弱信号 / 观察（单规则）', weak)
    table('无信号', none)

    lines.append('## 失败 / 缺口标的')
    if not fails:
        lines.append('（无）')
    else:
        lines.append('| 代码 | 原因 |')
        lines.append('|---|---|')
        for g in fails:
            lines.append(f"| {g.get('code')} | {g.get('reason')} |")
    lines.append('')

    lines.append('## 运行日志（stdout 摘录）')
    lines.append('```')
    lines.append('\n'.join(payload.get('log_lines', [])[-80:]))
    lines.append('```')
    lines.append('')
    lines.append('## 复现')
    lines.append('```bash')
    lines.append(payload.get('command', ''))
    lines.append('```')
    lines.append('')

    OUT_MD.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    log(f'wrote {OUT_MD}')


def main():
    log_lines = []

    def log(msg):
        print(msg, flush=True)
        log_lines.append(str(msg))

    print(FILTER_RULES, flush=True)
    log_lines.append(FILTER_RULES.strip())

    # wide window; get_cur_kline caps ~1000 bars
    end = date.today().isoformat()
    # Keep OpenD's full get_cur_kline window (~1000 bars); do not clip with a late start.
    start = (date.today() - timedelta(days=1600)).isoformat()
    py = sys.executable
    cmd = f'PYTHONUTF8=1 {py} -m studies.trend_breakout.scan_candidates'
    log(f'python={py}')
    log(f'command={cmd}')
    log(f'bar window {start} .. {end}')
    log('DISCLAIMER: trend_breakout REJECT; descriptive filter only.')

    all_results = []
    gaps = []

    for market, codes in (('us', US_CODES), ('hk', HK_CODES)):
        raw, acts, g = fetch_market(market, codes, start, end, log)
        gaps.extend(g)
        if not raw:
            log(f'[{market}] no raw data; skip analyze')
            continue
        # actions map: panel.build expects {code: [(ex_date,a,b),...]}
        p = panel.build(raw, acts)
        log(f'[{market}] panel dates={len(p["dates"])} codes={list(p["codes"])} '
            f'range={p["dates"][0]}..{p["dates"][-1]}')
        all_results.extend(analyze_panel(p, market, log))

    payload = {
        'disclaimer': (
            'trend_breakout TF1–TF14 REJECT (no OOS tradable alpha); '
            'ONLINE.md not implemented; this scan is a descriptive composite filter only.'
        ),
        'filter_rules': FILTER_RULES.strip(),
        'date_file': '2026-10-14',
        'rules': list(RULES),
        'lookback_hold': LOOKBACK,
        'python': py,
        'command': cmd,
        'bar_window': {'start': start, 'end': end},
        'candidates': {'us': US_CODES, 'hk': HK_CODES},
        'results': all_results,
        'gaps': gaps,
        'log_lines': log_lines,
        'summary': {
            'buy': [r['code'] for r in all_results if r.get('conclusion') == 'buy'],
            'sell_break': [r['code'] for r in all_results if r.get('conclusion') == 'sell_break'],
            'weak': [r['code'] for r in all_results if r.get('conclusion') == 'weak'],
            'none': [r['code'] for r in all_results if r.get('conclusion') == 'none'],
            'failed': [g['code'] for g in gaps],
        },
    }
    write_reports(payload, log)
    log('SUMMARY buy=' + str(payload['summary']['buy']))
    log('SUMMARY sell_break=' + str(payload['summary']['sell_break']))
    log('SUMMARY weak=' + str(payload['summary']['weak']))
    log('SUMMARY none=' + str(payload['summary']['none']))
    log('SUMMARY failed=' + str(payload['summary']['failed']))
    return 0 if all_results or gaps else 2


if __name__ == '__main__':
    sys.exit(main())
