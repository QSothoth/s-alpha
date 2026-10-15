"""W29 independent strong events; preserve the entire original B/S stream."""
from collections import deque
import json
import resource
import sys
import time

import feat
import w12_audit as w12
import w16_validate as w16
from w22_trade import sessions
from w28_confirmation import ROOT, STUDY, SEGMENTS, LAYERS

CANDIDATES = ('W2', 'W3', 'E2', 'M2', 'S2')


def raw_signals(f):
    out = {}
    for i, sign, _ in feat.watcher_marks(f, dedup=0):
        c, h, low, atr = (f[k][i] for k in ('c', 'h', 'l', 'atr'))
        types = set()
        if (c > f['sh'][i]) if sign == 1 else (c < f['sl'][i]):
            types.add('BOS')
        bull_gap = low - f['h'][i - 2] > .25 * atr
        bear_gap = not bull_gap and f['l'][i - 2] - h > .25 * atr
        if (bull_gap if sign == 1 else bear_gap):
            types.add('FVG')
        if (low < f['sl'][i] <= c) if sign == 1 else (h > f['sh'][i] >= c):
            types.add('SWEEP')
        assert types
        out[i] = (sign, types)
    return out


def strong_events(bars, f, raw):
    out = {name: [] for name in CANDIDATES}
    history = {s: deque() for s in (1, -1)}
    episodes = {s: deque() for s in (1, -1)}
    qualified, emitted = {}, {}
    previous = segment = None
    previous_sign = 0
    for i, bar in enumerate(bars):
        minute = int(bar[0][11:13]) * 60 + int(bar[0][14:16])
        opening = 570 if 570 <= minute < 720 else 780 if 780 <= minute < 960 else None
        current = (bar[0][:10], opening)
        if current != segment or previous is None or minute != previous + 1 or opening is None:
            for queue in (*history.values(), *episodes.values()):
                queue.clear()
            qualified.clear()
            # Lunch/gaps invalidate evidence, but not the same-day emission cooldown.
            if segment is None or current[0] != segment[0]:
                emitted.clear()
            previous_sign = 0
        segment, previous = current, minute
        if opening is None:
            continue
        sign, types = raw.get(i, (0, set()))
        for side in (1, -1):
            supportive = side * (bar[4] - f['vwap'][i]) > 0 and side * (f['ema9'][i] - f['ema21'][i]) > 0
            if not supportive:
                history[side].clear()
                episodes[side].clear()
            for queue in (history[side], episodes[side]):
                while queue and minute - queue[0][0] >= 15:
                    queue.popleft()
        if sign:
            history[sign].append((minute, types))
            if sign != previous_sign:
                episodes[sign].append((minute, types))
        previous_sign = sign
        recent = [x for x in history[sign] if minute - x[0] < 10] if sign else []
        short = sum(minute - t < 5 for t, _ in recent)
        span = bar[2] - bar[3]
        location = ((bar[4] - bar[3]) if sign == 1 else (bar[2] - bar[4])) / span if span > 0 else 0
        conditions = dict(W2=short >= 2, W3=len(recent) >= 3,
                          E2=len(episodes[sign]) >= 2 if sign else False,
                          M2=len(recent) >= 2 and len(set().union(*(ts for _, ts in recent))) >= 2,
                          S2=short >= 2 and f['vr'][i] >= 1.5 and location >= .75)
        for name in CANDIDATES:
            for side in (1, -1):
                key = (name, side)
                now = side == sign and conditions[name]
                if now and not qualified.get(key, False) and minute - emitted.get(key, -10000) >= 15:
                    out[name].append((i, side))
                    emitted[key] = minute
                qualified[key] = now
    return out


def summarize(groups):
    totals = {key: value.summary() for key, value in groups.items()}
    rows, decisions = [], {}
    for (name, layer), (summary, influence) in sorted(totals.items()):
        base, bi = totals[('B0', layer)]
        delta = (summary['mean_bp'] - base['mean_bp']) / 10000
        diff = {d: influence.get(d, 0) - bi.get(d, 0) for d in set(influence) | set(bi)}
        row = dict(variant=name, layer=layer, **summary, delta_bp=delta * 10000,
                   delta_t=w12.cluster_t(delta, diff), net_10bp=summary['mean_bp'] - 10,
                   net_25bp=summary['mean_bp'] - 25)
        rows.append(row)
        if name != 'B0' and layer == 'tpb>=2':
            gates = dict(sample=min(row['n_buy'], row['n_sell']) >= 200
                         and min(row['days_buy'], row['days_sell']) >= 60,
                         positive=row['mean_bp'] > 0 and row['t_day'] >= 2,
                         improvement=row['delta_bp'] > 0 and row['delta_t'] >= 2,
                         both_sides=row['buy_bp'] >= base['buy_bp'] and row['sell_bp'] >= base['sell_bp'])
            decisions[name] = dict(gates=gates, passed=all(gates.values()))
    return rows, decisions


def evaluate(segment, candidates):
    path, start, end = SEGMENTS[segment]
    began = time.monotonic()
    digest = w16.sha256(path)
    print(segment + ': quality scan', file=sys.stderr, flush=True)
    excluded = w16.quality_scan(path)
    groups = {(v, layer): w12.Totals() for v in ('B0', *candidates) for layer in LAYERS}
    extra = {v: 0 for v in candidates}
    sys.path.insert(0, str(ROOT / 'watch'))
    watcher = w12.watcher()
    processed = audited = 0
    for code, day, _, bars in sessions(path, start, end, set(excluded)):
        f = w12.corrected_features(bars)
        base = w12.replica(bars, f, None, 'B0')
        emitted = feat.watcher_marks(f)
        assert emitted == [(m['i'], 1 if m['side'] == 'BUY' else -1, m['tier']) for m in base]
        original = [(i, s) for i, s, _ in emitted]
        strong = strong_events(bars, f, raw_signals(f))
        if processed < 40:
            audited += w12.check_replica(watcher, (code, day), bars, f, None, base)
            cut = len(bars) // 2
            small = w12.corrected_features(bars[:cut])
            assert strong_events(bars[:cut], small, raw_signals(small)) == {
                k: [(i, s) for i, s in rows if i < cut] for k, rows in strong.items()}
        for name, events in [('B0', original)] + [(v, strong[v]) for v in candidates]:
            if name != 'B0':
                extra[name] += len(set(events) - set(original))
            for i, sign in events:
                tpb = f['tpb'][i]
                density = 'tpb<2' if tpb < 2 else '2<=tpb<5' if tpb < 5 else 'tpb>=5'
                ret = sign * (bars[i + 31][4] / bars[i + 1][4] - 1) if i + 31 < len(bars) else None
                for layer in ['all', density] + (['tpb>=2'] if tpb >= 2 else []):
                    groups[(name, layer)].add(day, 'BUY' if sign == 1 else 'SELL', ret)
        processed += 1
        if processed % 2000 == 0:
            print('%s stock_days=%d elapsed=%.1fs rss=%.1fMB' % (
                segment, processed, time.monotonic() - began,
                resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024), file=sys.stderr, flush=True)
    assert processed >= 40 and w16.sha256(path) == digest
    rows, decisions = summarize(groups)
    return dict(window=[start, end], input=str(path.relative_to(ROOT)), sha256=digest,
                excluded=excluded, stock_days=processed, replica_days=40, replica_marks=audited,
                replica_mismatches=0, extra_event_times=extra, rows=rows, decisions=decisions,
                elapsed_seconds=time.monotonic() - began,
                max_rss_mb=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024)


def main():
    output = STUDY / 'reports/w29_raw.json'
    if output.exists():
        raise SystemExit('W29 already evaluated; keep the frozen result.')
    sources = [STUDY / 'code' / n for n in ('w29_strong.py', 'feat.py', 'lab.py', 'w12_audit.py',
               'w16_validate.py', 'w22_trade.py', 'w28_confirmation.py', 'test_w29_strong.py')]
    sources += [STUDY / 'notes/W29_PREREG.md', ROOT / 'watch/smc_watch.py']
    hashes = {str(p.relative_to(ROOT)): w16.sha256(p) for p in sources}
    w12.check_statistics()
    selection = evaluate('selection', CANDIDATES)
    passed = [r for r in selection['rows'] if r['variant'] != 'B0' and r['layer'] == 'tpb>=2'
              and selection['decisions'][r['variant']]['passed']]
    passed.sort(key=lambda r: (-r['mean_bp'], CANDIDATES.index(r['variant'])))
    winner = passed[0]['variant'] if passed else None
    result = dict(source_sha256=hashes, selection=selection, winner=winner,
                  validation=None, deployment_allowed=False)
    output.write_text(json.dumps(w12.clean(result), ensure_ascii=False, indent=2, allow_nan=False) + '\n')
    if winner:
        result['validation'] = evaluate('validation', (winner,))
        result['deployment_allowed'] = result['validation']['decisions'][winner]['passed']
    assert all(w16.sha256(ROOT / name) == digest for name, digest in hashes.items())
    output.write_text(json.dumps(w12.clean(result), ensure_ascii=False, indent=2, allow_nan=False) + '\n')
    print(json.dumps(dict(winner=winner, deployment_allowed=result['deployment_allowed'],
                         decisions=selection['decisions']), ensure_ascii=False))


if __name__ == '__main__':
    main()
