"""W34: first turn B/S (TURN) vs the current marks(), on old1m.csv.gz only.

Preregistration: ../notes/W34_PREREG.md. Baseline is watch/smc_watch.marks()
called as is; the candidate re-runs the same loop with the TURN rule added and,
with TURN switched off, must reproduce the baseline mark for mark. Streams one
(code, day) at a time; no network, no OpenD.

    /opt/futu-opend/venv/bin/python studies/watch_signal/code/w34_turn.py
"""
import csv
import gzip
import itertools
import math
import subprocess
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'watch'))
import smc_watch as w  # noqa: E402

DATA = ROOT / 'studies/watch_signal/data/old1m.csv.gz'
REPORT = ROOT / 'studies/watch_signal/reports/W34_RESULTS_CN.md'
COST = 0.001
HOLD = 30
INDEX_CODE = 'HK.800000'
BANDS, PER_BAND = 4, 8      # W34 amendment: 4 HSI day-return bands x 8 days
CHECK_EVERY = 5             # compare the TURN-off loop with marks() on every 5th stock-day
BAND_NAMES = ('大跌', '小跌', '小涨', '大涨')


def swing_at(highs, lows, end, left=w.SWING_LEFT):
    """last_swing() over the 24 bars ending at `end`, with absolute positions."""
    s = max(0, end - 24)
    sh = sl = jh = jl = None
    for j in range(s + left, end - left):
        if highs[j] == max(highs[j - left:j + left + 1]):
            sh, jh = highs[j], j
        if lows[j] == min(lows[j - left:j + left + 1]):
            sl, jl = lows[j], j
    return sh, jh, sl, jl


def candidate(bars, ds, tpb, turn=True, stats=None):
    """marks() with the W34 TURN rule; `ds[i]` is read(bars[:i + 1])."""
    highs = [b[2] for b in bars]
    lows = [b[3] for b in bars]
    closes = [b[4] for b in bars]
    out, last = [], {}
    arm = {'SELL': None, 'BUY': None}
    prev = {'SELL': None, 'BUY': None}     # index of the last emitted mark per side
    for i, d in enumerate(ds):
        fired = {}
        if turn and i >= w.WARMUP_BARS:
            for side, a in list(arm.items()):
                if a is None:
                    continue
                if (highs[i] > a['ext']) if side == 'SELL' else (lows[i] < a['ext']):
                    arm[side] = None
                elif (closes[i] < a['trig']) if side == 'SELL' else (closes[i] > a['trig']):
                    fired[side] = a
                    arm[side] = None
            sh, jh, sl, jl = swing_at(highs, lows, i + 1)
            if sh is not None and highs[i] > sh >= closes[i] and jh + 1 <= i - 1:
                s = prev['BUY'] if prev['BUY'] is not None else 0
                if max(highs[s:i]) == sh:
                    arm['SELL'] = {'ext': highs[i], 'trig': min(lows[jh + 1:i])}
            if sl is not None and lows[i] < sl <= closes[i] and jl + 1 <= i - 1:
                s = prev['SELL'] if prev['SELL'] is not None else 0
                if min(lows[s:i]) == sl:
                    arm['BUY'] = {'ext': lows[i], 'trig': max(highs[jl + 1:i])}
        tside = tstop = None
        if len(fired) == 2:
            if stats is not None:
                stats['both_turns'] += 1
        elif fired:
            tside, a = next(iter(fired.items()))
            tstop = a['ext']
        side = trig = None
        if None not in (d['vwap'], d['ema9'], d['ema21'], d['rsi']) and i >= w.WARMUP_BARS:
            bull, bear = w.structure(bars[:i + 1], d)
            long_bias = d['close'] > d['vwap'] and d['ema9'] > d['ema21'] and d['rsi'] >= 50
            short_bias = d['close'] < d['vwap'] and d['ema9'] < d['ema21'] and d['rsi'] <= 50
            if long_bias and bull:
                side, trig = 'BUY', '+'.join(bull)
            elif short_bias and bear:
                side, trig = 'SELL', '+'.join(bear)
        stop = None
        if tside is not None:
            if side is not None and side != tside:
                if stats is not None:
                    stats['opposite_conflicts'] += 1
            else:
                trig = 'TURN+' + trig if side else 'TURN'
                side, stop = tside, tstop
        if side is None:
            continue
        ok_zone = d['pos'] <= w.PREMIUM if side == 'BUY' else d['pos'] >= 1 - w.PREMIUM
        vr = d['vol_ratio']
        tier = 'vol' if (vr is not None and vr >= w.VOL_MULT and ok_zone) else 'plain'
        if not w._emit_ok('repeat15', i, side, tier, d, last, None):
            continue
        last[(side, tier)] = i
        prev[side] = i
        if stop is None:
            stop = d['swing_low'] if side == 'BUY' else d['swing_high']
        out.append({'i': i, 't': bars[i][0][11:16], 'side': side, 'tier': tier,
                    'tpb': round(tpb[i], 2), 'fine': tpb[i] >= w.FINE_TPB,
                    'coarse': tpb[i] < w.GATE_TPB,
                    'trigger': trig, 'close': d['close'],
                    'rsi': round(d['rsi'], 1) if d['rsi'] is not None else None,
                    'vwap': round(d['vwap'], 3) if d['vwap'] is not None else None,
                    'vol_ratio': round(vr, 2) if vr is not None else None,
                    'pos': round(d['pos'], 2), 'stop': stop})
    return out


def sampled_days(per_band=PER_BAND, bands=BANDS):
    """{day: band} -- HSI day-return rank split into `bands`, `per_band` evenly spaced days each."""
    first, last = {}, {}
    with gzip.open(DATA, 'rt', newline='') as fh:
        for r in csv.DictReader(fh):
            if r['code'] != INDEX_CODE:
                continue
            day, hm = r['time_key'][:10], r['time_key'][11:16]
            if hm == '09:30':
                first[day] = float(r['last_close'])
            if hm < '16:00':
                last[day] = float(r['close'])
    ranked = sorted((last[d] / first[d] - 1, d) for d in last if first.get(d))
    out = {}
    for b in range(bands):
        part = ranked[len(ranked) * b // bands:len(ranked) * (b + 1) // bands]
        for k in range(per_band):
            out[part[int((k + 0.5) * len(part) / per_band)][1]] = b
    return out


def sessions(days=None):
    """(code, day, bars) per stock-day; bars before 16:00 like closed_session()."""
    seen = set()
    with gzip.open(DATA, 'rt', newline='') as fh:
        for key, rows in itertools.groupby(csv.DictReader(fh), lambda r: (r['code'], r['time_key'][:10])):
            if key in seen:
                raise ValueError('non-contiguous stock-day %r' % (key,))
            seen.add(key)
            if key[0] == INDEX_CODE or (days is not None and key[1] not in days):
                continue
            bars = sorted((r['time_key'], float(r['open']), float(r['high']), float(r['low']),
                           float(r['close']), float(r['volume'] or 0))
                          for r in rows if r['time_key'][11:16] < '16:00')
            if len({b[0] for b in bars}) != len(bars):
                raise ValueError('duplicate minute %r' % (key,))
            if bars:
                yield key[0], key[1], bars


def wait_bars(bars, ms, k):
    """Bars from the leg's extreme (since the previous opposite mark) to mark k."""
    m = ms[k]
    p = next((x['i'] for x in reversed(ms[:k]) if x['side'] != m['side']), None)
    s = 0 if p is None else p + 1
    i = m['i']
    if m['side'] == 'SELL':
        ext = max(b[2] for b in bars[s:i + 1])
        j = max(x for x in range(s, i + 1) if bars[x][2] == ext)
    else:
        ext = min(b[3] for b in bars[s:i + 1])
        j = max(x for x in range(s, i + 1) if bars[x][3] == ext)
    return i - j


def net(bars, m):
    i = m['i']
    if i + 1 + HOLD >= len(bars):
        return None
    entry, exit_ = bars[i + 1][4], bars[i + 1 + HOLD][4]
    gross = (exit_ - entry) / entry if m['side'] == 'BUY' else (entry - exit_) / entry
    return gross - COST


def day_t(rows):
    """(n, days, mean, t) with the t of calendar-day means."""
    by = defaultdict(list)
    for r in rows:
        by[r['day']].append(r['net'])
    means = [sum(v) / len(v) for v in by.values()]
    n, k = len(rows), len(means)
    mean = sum(r['net'] for r in rows) / n if n else math.nan
    if k < 2:
        return n, k, mean, math.nan
    mu = sum(means) / k
    sd = math.sqrt(sum((x - mu) ** 2 for x in means) / (k - 1))
    return n, k, mean, (mu / (sd / math.sqrt(k)) if sd > 0 else math.nan)


def paired_t(early, base):
    a, b = defaultdict(list), defaultdict(list)
    for r in early:
        a[r['day']].append(r['net'])
    for r in base:
        b[r['day']].append(r['net'])
    diffs = [sum(a[d]) / len(a[d]) - sum(b[d]) / len(b[d]) for d in a if d in b]
    k = len(diffs)
    if k < 2:
        return k, math.nan, math.nan
    mu = sum(diffs) / k
    sd = math.sqrt(sum((x - mu) ** 2 for x in diffs) / (k - 1))
    return k, mu, (mu / (sd / math.sqrt(k)) if sd > 0 else math.nan)


def pct(xs, q):
    xs = sorted(xs)
    if not xs:
        return math.nan
    pos = (len(xs) - 1) * q
    lo = int(math.floor(pos))
    hi = min(lo + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (pos - lo)


def main():
    t0 = time.time()
    stats = defaultdict(int)
    rows = []          # group early/base, side, day, net, wait, tpb, lead
    count = defaultdict(int)
    days = sampled_days()
    for n_day, (code, day, bars) in enumerate(sessions(days), 1):
        ds = [w.read(bars[:end]) for end in range(1, len(bars) + 1)]
        tpb = w.ticks_per_bar(bars)
        base = candidate(bars, ds, tpb, turn=False)
        if n_day % CHECK_EVERY == 1:
            if w.marks(bars)[0] != base:
                raise SystemExit('replica mismatch on %s %s' % (code, day))
            stats['checked'] += 1
        cand = candidate(bars, ds, tpb, turn=True, stats=stats)
        stats['stock_days'] += 1
        for m in base:
            count[('base', m['side'])] += 1
        for m in cand:
            count[('cand', m['side'])] += 1
            if 'TURN' in m['trigger']:
                count[('turn', m['side'])] += 1
        for k, m in enumerate(cand):
            if 'TURN' not in m['trigger']:
                continue
            before = [x for x in base if x['i'] <= m['i']]
            if before and before[-1]['side'] == m['side']:
                continue
            count[('early', m['side'])] += 1
            nxt = next((x['i'] for x in base if x['i'] > m['i'] and x['side'] == m['side']), None)
            r = net(bars, m)
            if r is not None:
                rows.append(dict(g='early', side=m['side'], day=day, band=days[day], net=r, tpb=m['tpb'],
                                 wait=wait_bars(bars, cand, k),
                                 lead=None if nxt is None else nxt - m['i']))
        for k, m in enumerate(base):
            if k and base[k - 1]['side'] == m['side']:
                continue
            count[('baseturn', m['side'])] += 1
            r = net(bars, m)
            if r is not None:
                rows.append(dict(g='base', side=m['side'], day=day, band=days[day], net=r, tpb=m['tpb'],
                                 wait=wait_bars(bars, base, k), lead=None))
        if n_day % 1000 == 0:
            print('%d stock-days, %.0fs' % (n_day, time.time() - t0), flush=True)
    test = subprocess.run([sys.executable, str(ROOT / 'watch/test_watch.py')],
                          capture_output=True, text=True, cwd=str(ROOT))
    write_report(rows, stats, count, test, time.time() - t0, days)


def block(rows, label):
    n, k, mean, t = day_t(rows)
    waits = [r['wait'] for r in rows]
    return '| %s | %d | %d | %.2f | %.2f | %.1f | %.1f |' % (
        label, n, k, mean * 1e4, t, pct(waits, 0.5), pct(waits, 0.75))


def write_report(rows, stats, count, test, secs, days):
    lines, gates = [], {}
    sel = lambda g, s, f=lambda r: True: [r for r in rows if r['g'] == g and r['side'] == s and f(r)]  # noqa: E731
    hdr = ['| 组 | 笔数 | 交易日 | 净均值 bp | 日聚类 t | 等待 p50 | 等待 p75 |', '|---|---:|---:|---:|---:|---:|---:|']
    table = list(hdr)
    for side in ('SELL', 'BUY'):
        for g, name in (('early', '早出来的'), ('base', '基线转折')):
            for lab, f in (('', lambda r: True), (' tpb≥2', lambda r: r['tpb'] >= 2), (' tpb<2', lambda r: r['tpb'] < 2)):
                table.append(block(sel(g, side, f), name + side + lab))
    for side in ('SELL', 'BUY'):
        e, b = sel('early', side), sel('base', side)
        _, _, _, te = day_t(e)
        kd, dmu, tp = paired_t(e, b)
        we, wb = pct([r['wait'] for r in e], 0.5), pct([r['wait'] for r in b], 0.5)
        gates[side] = dict(g1=te > -2, te=te, g2=tp > -2, tp=tp, kd=kd, dmu=dmu,
                           g3=we < wb, we=we, wb=wb)
        leads = [r['lead'] for r in e if r['lead'] is not None]
        gates[side]['lead'] = (len(leads), len(e), pct(leads, 0.5), pct(leads, 0.75))
    g4 = test.returncode == 0
    ok = all(g['g1'] and g['g2'] and g['g3'] for g in gates.values()) and g4
    yes = lambda b: '过' if b else '**未过**'  # noqa: E731
    lines += ['# W34 结果：转折第一笔 B/S（TURN）', '',
              '预登记：[W34_PREREG.md](../notes/W34_PREREG.md)。脚本：`code/w34_turn.py`，一次评测，运行 %.0f 秒。' % secs, '',
              '## 结论', '',
              ('四条通过线都满足，按预登记把 TURN 接进 `marks()` 默认路径。' if ok else
               '通过线未全部满足，**保持现行规则**：不改 `watch/smc_watch.py` 默认行为、不改看板说明、不加测试。'), '',
              '| 通过线 | SELL | BUY |', '|---|---|---|',
              '| 1. 早出来的笔净收益日聚类 t > −2 | %s（t=%.2f） | %s（t=%.2f） |' % (
                  yes(gates['SELL']['g1']), gates['SELL']['te'], yes(gates['BUY']['g1']), gates['BUY']['te']),
              '| 2. 相对同日基线转折笔的差 t > −2 | %s（%d 天，差 %.2fbp，t=%.2f） | %s（%d 天，差 %.2fbp，t=%.2f） |' % (
                  yes(gates['SELL']['g2']), gates['SELL']['kd'], gates['SELL']['dmu'] * 1e4, gates['SELL']['tp'],
                  yes(gates['BUY']['g2']), gates['BUY']['kd'], gates['BUY']['dmu'] * 1e4, gates['BUY']['tp']),
              '| 3. 等待根数中位数低于基线转折笔 | %s（%.1f vs %.1f） | %s（%.1f vs %.1f） |' % (
                  yes(gates['SELL']['g3']), gates['SELL']['we'], gates['SELL']['wb'],
                  yes(gates['BUY']['g3']), gates['BUY']['we'], gates['BUY']['wb']),
              '| 4. `python3 watch/test_watch.py` | %s | |' % yes(g4), '',
              '## 数据与计数', '',
              '`old1m.csv.gz`，按预登记修订抽样：恒指当日涨跌四档 × 8 天 = %d 天（%s），剔除 HK.800000 后 %d 个 (code, 日期)。关掉 TURN 的候选循环与现行 `marks()` 在抽查的 %d 个 stock-day 逐条一致。' % (len(days), '、'.join(sorted(days)), stats['stock_days'], stats['checked']), '',
              '| | SELL | BUY |', '|---|---:|---:|',
              '| 基线标注 | %d | %d |' % (count[('base', 'SELL')], count[('base', 'BUY')]),
              '| 候选标注 | %d | %d |' % (count[('cand', 'SELL')], count[('cand', 'BUY')]),
              '| 候选中含 TURN | %d | %d |' % (count[('turn', 'SELL')], count[('turn', 'BUY')]),
              '| 早出来的笔（含不满 30 根被丢弃） | %d | %d |' % (count[('early', 'SELL')], count[('early', 'BUY')]),
              '| 基线转折笔（同上） | %d | %d |' % (count[('baseturn', 'SELL')], count[('baseturn', 'BUY')]), '',
              'TURN 与现行规则同根反向而作废：%d 次；多空 TURN 同根同时触发而作废：%d 次。' % (
                  stats['opposite_conflicts'], stats['both_turns']), '',
              '## 收益与等待', '',
              '入场第 i+1 根收盘、出场第 i+31 根收盘，净 = 毛 − 10bp；t 按日历交易日聚类（先取每日所有标的平均）。等待根数 = 本段极端点到标注根。', '']
    lines += table
    lines += ['', '早出来的笔比基线同方向下一条标注提前的根数（之后基线当天没有同向标注的不计）：', '',
              '| | 有对照 / 全部 | 提前 p50 | 提前 p75 |', '|---|---:|---:|---:|']
    for side in ('SELL', 'BUY'):
        n, tot, p50, p75 = gates[side]['lead']
        lines.append('| %s | %d / %d | %.1f | %.1f |' % (side, n, tot, p50, p75))
    lines += ['', '按恒指当日涨跌分档（不作门槛）：', '',
              '| 档 | 组 | 笔数 | 交易日 | 净均值 bp | 日聚类 t |', '|---|---|---:|---:|---:|---:|']
    for b, bn in enumerate(BAND_NAMES):
        for side in ('SELL', 'BUY'):
            for g, name in (('early', '早出来的'), ('base', '基线转折')):
                n, k, mean, t = day_t(sel(g, side, lambda r: r['band'] == b))
                lines.append('| %s | %s%s | %d | %d | %.2f | %.2f |' % (bn, name, side, n, k, mean * 1e4, t))
    lines += ['', '## 单测', '', '```', (test.stdout + test.stderr).strip()[-1500:], '```', '']
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text('\n'.join(lines), encoding='utf-8')
    print('wrote %s' % REPORT)


if __name__ == '__main__':
    main()
