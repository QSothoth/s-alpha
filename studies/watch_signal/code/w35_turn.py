"""W35: TURN sensitivity vs accuracy relative to the current marks().

Preregistration: ../notes/W35_PREREG.md. The rule is W34's `candidate()`
unchanged; only the days (32 not used by W34) and the gates differ.

    /opt/opend-us-options/.venv/bin/python studies/watch_signal/code/w35_turn.py
"""
import csv
import gzip
import math
import subprocess
import sys
import time
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import w34_turn as t34  # noqa: E402

w = t34.w
ROOT = t34.ROOT
REPORT = ROOT / 'studies/watch_signal/reports/W35_RESULTS_CN.md'


def hsi_ranked():
    """[(HSI day return, day)] ascending, from HK.800000 in the same file."""
    first, last = {}, {}
    with gzip.open(t34.DATA, 'rt', newline='') as fh:
        for r in csv.DictReader(fh):
            if r['code'] != t34.INDEX_CODE:
                continue
            day, hm = r['time_key'][:10], r['time_key'][11:16]
            if hm == '09:30':
                first[day] = float(r['last_close'])
            if hm < '16:00':
                last[day] = float(r['close'])
    return sorted((last[d] / first[d] - 1, d) for d in last if first.get(d))


def fresh_days():
    """W34's band sampling, applied to the days W34 did not use."""
    used = t34.sampled_days()
    ranked = [x for x in hsi_ranked() if x[1] not in used]
    out = {}
    for b in range(t34.BANDS):
        part = ranked[len(ranked) * b // t34.BANDS:len(ranked) * (b + 1) // t34.BANDS]
        for k in range(t34.PER_BAND):
            out[part[int((k + 0.5) * len(part) / t34.PER_BAND)][1]] = b
    assert not set(out) & set(used)
    return out


def paired(a_rows, b_rows, key):
    a, b = defaultdict(list), defaultdict(list)
    for r in a_rows:
        a[r['day']].append(r[key])
    for r in b_rows:
        b[r['day']].append(r[key])
    diffs = [sum(a[d]) / len(a[d]) - sum(b[d]) / len(b[d]) for d in a if d in b]
    k = len(diffs)
    if k < 2:
        return k, math.nan, math.nan
    mu = sum(diffs) / k
    sd = math.sqrt(sum((x - mu) ** 2 for x in diffs) / (k - 1))
    return k, mu, (mu / (sd / math.sqrt(k)) if sd > 0 else math.nan)


def row(g, m, day, band, r, wait=None):
    return dict(g=g, side=m['side'], day=day, band=band, net=r, hit=1.0 if r + t34.COST > 0 else 0.0,
                tpb=m['tpb'], wait=wait)


def main():
    t0 = time.time()
    days = fresh_days()
    stats, count, rows = defaultdict(int), defaultdict(int), []
    for n_day, (code, day, bars) in enumerate(t34.sessions(days), 1):
        ds = [w.read(bars[:end]) for end in range(1, len(bars) + 1)]
        tpb = w.ticks_per_bar(bars)
        base = t34.candidate(bars, ds, tpb, turn=False)
        if n_day % t34.CHECK_EVERY == 1:
            if w.marks(bars)[0] != base:
                raise SystemExit('replica mismatch on %s %s' % (code, day))
            stats['checked'] += 1
        cand = t34.candidate(bars, ds, tpb, turn=True, stats=stats)
        stats['stock_days'] += 1
        band = days[day]
        for g, ms in (('all_c', cand), ('all_b', base)):
            for m in ms:
                count[(g, m['side'])] += 1
                r = t34.net(bars, m)
                if r is not None:
                    rows.append(row(g, m, day, band, r))
        for k, m in enumerate(cand):
            if 'TURN' not in m['trigger']:
                continue
            count[('turn', m['side'])] += 1
            before = [x for x in base if x['i'] <= m['i']]
            if before and before[-1]['side'] == m['side']:
                continue
            count[('early', m['side'])] += 1
            r = t34.net(bars, m)
            if r is not None:
                rows.append(row('early', m, day, band, r, t34.wait_bars(bars, cand, k)))
        for k, m in enumerate(base):
            if k and base[k - 1]['side'] == m['side']:
                continue
            count[('base', m['side'])] += 1
            r = t34.net(bars, m)
            if r is not None:
                rows.append(row('base', m, day, band, r, t34.wait_bars(bars, base, k)))
        if n_day % 1000 == 0:
            print('%d stock-days, %.0fs' % (n_day, time.time() - t0), flush=True)
    test = subprocess.run([sys.executable, str(ROOT / 'watch/test_watch.py')],
                          capture_output=True, text=True, cwd=str(ROOT))
    write_report(rows, stats, count, test, time.time() - t0, days)
    print('wrote %s' % REPORT)


def write_report(rows, stats, count, test, secs, days):
    def sel(g, s, f=lambda r: True):
        return [r for r in rows if r['g'] == g and r['side'] == s and f(r)]

    def hit(rs):
        return sum(r['hit'] for r in rs) / len(rs) * 100 if rs else math.nan

    yes = lambda b: '过' if b else '**未过**'  # noqa: E731
    gates = {}
    for s in ('SELL', 'BUY'):
        e, b = sel('early', s), sel('base', s)
        gates[s] = dict(hit=paired(e, b, 'hit'), net=paired(e, b, 'net'),
                        board=paired(sel('all_c', s), sel('all_b', s), 'net'),
                        we=t34.pct([r['wait'] for r in e], 0.5), wb=t34.pct([r['wait'] for r in b], 0.5))
        g = gates[s]
        g['ok'] = [g['hit'][2] > -2, g['net'][2] > -2, g['board'][2] > -2, g['we'] < g['wb']]
    g5 = test.returncode == 0
    ok = all(all(g['ok']) for g in gates.values()) and g5
    S, B = gates['SELL'], gates['BUY']
    lines = ['# W35 结果：TURN 灵敏度与准确性（相对现行 B/S）', '',
             '预登记：[W35_PREREG.md](../notes/W35_PREREG.md)。脚本：`code/w35_turn.py`，一次评测，运行 %.0f 秒。' % secs, '',
             '## 结论', '',
             ('五条通过线都满足，按预登记把 TURN 接进 `marks()` 默认路径。' if ok else
              '通过线未全部满足，**保持现行规则**：不改 `watch/smc_watch.py`、不改看板说明、不加测试。'), '',
             '| 通过线 | SELL | BUY |', '|---|---|---|',
             '| 1. 方向对比例，早出来 − 同日基线转折，配对 t > −2 | %s（%d 天，%+.1f 个百分点，t=%.2f） | %s（%d 天，%+.1f 个百分点，t=%.2f） |' % (
                 yes(S['ok'][0]), S['hit'][0], S['hit'][1] * 100, S['hit'][2],
                 yes(B['ok'][0]), B['hit'][0], B['hit'][1] * 100, B['hit'][2]),
             '| 2. 净收益，早出来 − 同日基线转折，配对 t > −2 | %s（%+.2fbp，t=%.2f） | %s（%+.2fbp，t=%.2f） |' % (
                 yes(S['ok'][1]), S['net'][1] * 1e4, S['net'][2], yes(B['ok'][1]), B['net'][1] * 1e4, B['net'][2]),
             '| 3. 看板全部标注，候选 − 基线，配对 t > −2 | %s（%+.2fbp，t=%.2f） | %s（%+.2fbp，t=%.2f） |' % (
                 yes(S['ok'][2]), S['board'][1] * 1e4, S['board'][2], yes(B['ok'][2]), B['board'][1] * 1e4, B['board'][2]),
             '| 4. 等待根数中位数低于基线转折笔 | %s（%.1f vs %.1f） | %s（%.1f vs %.1f） |' % (
                 yes(S['ok'][3]), S['we'], S['wb'], yes(B['ok'][3]), B['we'], B['wb']),
             '| 5. `python3 watch/test_watch.py` | %s | |' % yes(g5), '',
             '## 数据与计数', '',
             '`old1m.csv.gz`，W34 未用的 87 天里按恒指当日涨跌四档 × 8 天抽 %d 天（%s），剔除 HK.800000 后 %d 个 (code, 日期)。关掉 TURN 的候选循环与现行 `marks()` 在抽查的 %d 个 stock-day 逐条一致。' % (
                 len(days), '、'.join(sorted(days)), stats['stock_days'], stats['checked']), '',
             '| | SELL | BUY |', '|---|---:|---:|',
             '| 基线标注 | %d | %d |' % (count[('all_b', 'SELL')], count[('all_b', 'BUY')]),
             '| 候选标注 | %d | %d |' % (count[('all_c', 'SELL')], count[('all_c', 'BUY')]),
             '| 候选中含 TURN | %d | %d |' % (count[('turn', 'SELL')], count[('turn', 'BUY')]),
             '| 早出来的笔（含不满 30 根被丢弃） | %d | %d |' % (count[('early', 'SELL')], count[('early', 'BUY')]),
             '| 基线转折笔（同上） | %d | %d |' % (count[('base', 'SELL')], count[('base', 'BUY')]), '',
             'TURN 与现行规则同根反向而作废：%d 次；多空 TURN 同根同时触发而作废：%d 次。' % (
                 stats['opposite_conflicts'], stats['both_turns']), '',
             '## 明细（参考，不作门槛）', '',
             '入场第 i+1 根收盘、出场第 i+31 根收盘，净 = 毛 − 10bp；t 按日历交易日聚类。', '',
             '| 组 | 笔数 | 交易日 | 方向对 % | 净均值 bp | 日聚类 t | 等待 p50 | 等待 p75 |',
             '|---|---:|---:|---:|---:|---:|---:|---:|']
    names = (('early', '早出来的'), ('base', '基线转折'), ('all_c', '候选全部'), ('all_b', '基线全部'))
    for s in ('SELL', 'BUY'):
        for g, name in names:
            for lab, f in (('', lambda r: True), (' tpb≥2', lambda r: r['tpb'] >= 2), (' tpb<2', lambda r: r['tpb'] < 2)):
                rs = sel(g, s, f)
                n, k, mean, tt = t34.day_t(rs)
                waits = [r['wait'] for r in rs if r['wait'] is not None]
                lines.append('| %s%s%s | %d | %d | %.1f | %.2f | %.2f | %s | %s |' % (
                    name, s, lab, n, k, hit(rs), mean * 1e4, tt,
                    '%.1f' % t34.pct(waits, 0.5) if waits else '-', '%.1f' % t34.pct(waits, 0.75) if waits else '-'))
    lines += ['', '按恒指当日涨跌分档：', '',
              '| 档 | 组 | 笔数 | 方向对 % | 净均值 bp | 日聚类 t |', '|---|---|---:|---:|---:|---:|']
    for b, bn in enumerate(t34.BAND_NAMES):
        for s in ('SELL', 'BUY'):
            for g, name in names[:2]:
                rs = sel(g, s, lambda r: r['band'] == b)
                n, k, mean, tt = t34.day_t(rs)
                lines.append('| %s | %s%s | %d | %.1f | %.2f | %.2f |' % (bn, name, s, n, hit(rs), mean * 1e4, tt))
    lines += ['', '## 单测', '', '```', (test.stdout + test.stderr).strip()[-600:], '```', '']
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text('\n'.join(lines), encoding='utf-8')


if __name__ == '__main__':
    main()
