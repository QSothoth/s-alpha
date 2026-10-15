"""Frozen W28 H3 transfer study; one stock-day in memory, no quote API calls."""
import json
import resource
import sys
import time
from pathlib import Path

import w12_audit as w12
import w16_validate as w16
from w22_trade import sessions

ROOT = Path(__file__).resolve().parents[3]
STUDY = ROOT / 'studies/watch_signal'
LAYERS = ('all', 'tpb>=2', 'tpb<2', '2<=tpb<5', 'tpb>=5')
SEGMENTS = {
    'selection': (ROOT / 'data/watch-hk1m-train-v1/bars_1m.csv.gz',
                  '2025-12-01', '2026-08-14'),
    'validation': (STUDY / 'data/w19_2024h1_1m.csv.gz', '2024-01-02', '2024-05-31'),
}


def confirmations(bars, vwap, ema9, ema21):
    """Return causal signs (1/-1/0), using only completed HK three-minute blocks."""
    out, votes, block = [], [], []
    previous = segment = None
    for i, bar in enumerate(bars):
        stamp = bar[0]
        minute = int(stamp[11:13]) * 60 + int(stamp[14:16])
        opening = 570 if 570 <= minute < 720 else 780 if 780 <= minute < 960 else None
        current = (stamp[:10], opening)
        if current != segment or previous is None or minute != previous + 1 or opening is None:
            votes.clear()
            block.clear()
        segment, previous = current, minute
        if opening is None:
            out.append(0)
            continue
        offset = (minute - opening) % 3
        if offset == 0:
            block = [bar]
        elif block:
            block.append(bar)
        if offset == 2 and len(block) == 3:
            close = bar[4]
            sign = (1 if close > block[0][1] and close > vwap[i] and ema9[i] > ema21[i]
                    else -1 if close < block[0][1] and close < vwap[i] and ema9[i] < ema21[i]
                    else 0)
            votes.append((close, sign))
            votes = votes[-2:]
        sign = votes[-1][1] if len(votes) == 2 else 0
        out.append(sign if sign and votes[0][1] == sign
                   and sign * (votes[1][0] - votes[0][0]) > 0 else 0)
    return out


def summarize(groups):
    summaries = {key: value.summary() for key, value in groups.items()}
    rows = []
    for (variant, layer), (summary, influence) in sorted(summaries.items()):
        base, bi = summaries[('B0', layer)]
        delta = (summary['mean_bp'] - base['mean_bp']) / 10000
        differences = {d: influence.get(d, 0) - bi.get(d, 0) for d in set(influence) | set(bi)}
        rows.append(dict(variant=variant, layer=layer, **summary,
                         delta_bp=delta * 10000, delta_t=w12.cluster_t(delta, differences),
                         coverage=summary['notifications'] / base['notifications']
                         if base['notifications'] else None,
                         net_10bp=summary['mean_bp'] - 10,
                         net_25bp=summary['mean_bp'] - 25))
    candidate = next(r for r in rows if r['variant'] == 'H3' and r['layer'] == 'tpb>=2')
    base = summaries[('B0', 'tpb>=2')][0]
    gates = dict(sample=min(candidate['n_buy'], candidate['n_sell']) >= 200
                 and min(candidate['days_buy'], candidate['days_sell']) >= 60,
                 positive=candidate['mean_bp'] > 0 and candidate['t_day'] >= 2,
                 improvement=candidate['delta_bp'] > 0 and candidate['delta_t'] >= 2,
                 both_sides=candidate['buy_bp'] >= base['buy_bp']
                 and candidate['sell_bp'] >= base['sell_bp'])
    return rows, gates


def evaluate(segment):
    path, start, end = SEGMENTS[segment]
    began = time.monotonic()
    digest = w16.sha256(path)
    print(segment + ': scanning input quality', file=sys.stderr, flush=True)
    excluded = w16.quality_scan(path)
    groups = {(variant, layer): w12.Totals()
              for variant in ('B0', 'H3', 'not_H3') for layer in LAYERS}
    sys.path.insert(0, str(ROOT / 'watch'))
    watcher = w12.watcher()
    processed = audited_marks = 0
    for code, day, _, bars in sessions(path, start, end, set(excluded)):
        f = w12.corrected_features(bars)
        marks = w12.replica(bars, f, None, 'B0')
        flags = confirmations(bars, f['vwap'], f['ema9'], f['ema21'])
        if processed < 40:
            audited_marks += w12.check_replica(watcher, (code, day), bars, f, None, marks)
            cut = len(bars) // 2
            small = w12.corrected_features(bars[:cut])
            assert flags[:cut] == confirmations(bars[:cut], small['vwap'], small['ema9'], small['ema21'])
        for mark in marks:
            i, side = mark['i'], mark['side']
            sign = 1 if side == 'BUY' else -1
            ret = sign * (bars[i + 31][4] / bars[i + 1][4] - 1) if i + 31 < len(bars) else None
            tpb = f['tpb'][i]
            density = 'tpb<2' if tpb < 2 else '2<=tpb<5' if tpb < 5 else 'tpb>=5'
            layers = ['all', density] + (['tpb>=2'] if tpb >= 2 else [])
            variant = 'H3' if flags[i] == sign else 'not_H3'
            for layer in layers:
                for name in ('B0', variant):
                    groups[(name, layer)].add(day, side, ret)
        processed += 1
        if processed % 2000 == 0:
            print('%s stock_days=%d elapsed=%.1fs rss=%.1fMB' % (
                segment, processed, time.monotonic() - began,
                resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024), file=sys.stderr, flush=True)
    assert processed >= 40
    for layer in LAYERS:
        assert groups[('B0', layer)].notifications == sum(
            groups[(v, layer)].notifications for v in ('H3', 'not_H3'))
    rows, gates = summarize(groups)
    assert w16.sha256(path) == digest, 'input changed during evaluation'
    return dict(segment=segment, window=[start, end], input=str(path.relative_to(ROOT)),
                sha256=digest, excluded=excluded, stock_days=processed,
                replica_days=40, replica_marks=audited_marks, replica_mismatches=0,
                rows=rows, gates=gates, pass_all=all(gates.values()),
                elapsed_seconds=time.monotonic() - began,
                max_rss_mb=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024)


def main():
    output = STUDY / 'reports/w28_raw.json'
    if output.exists():
        raise SystemExit('W28 is already evaluated; do not rerun a frozen study.')
    w12.check_statistics()
    sources = [Path(__file__), STUDY / 'notes/W28_PREREG.md',
               *(STUDY / 'code' / name for name in
                 ('w12_audit.py', 'w16_validate.py', 'w22_trade.py', 'feat.py', 'lab.py')),
               ROOT / 'watch/smc_watch.py']
    hashes = {str(p.relative_to(ROOT)): w16.sha256(p) for p in sources}
    result = dict(candidate='H3', source_sha256=hashes, selection=evaluate('selection'),
                  validation=None, deployment_allowed=False)
    # Persist selection before consuming the single validation opportunity.
    output.write_text(json.dumps(w12.clean(result), ensure_ascii=False, indent=2, allow_nan=False) + '\n')
    if result['selection']['pass_all']:
        result['validation'] = evaluate('validation')
        result['deployment_allowed'] = result['validation']['pass_all']
    assert all(w16.sha256(ROOT / path) == digest for path, digest in hashes.items())
    output.write_text(json.dumps(w12.clean(result), ensure_ascii=False, indent=2, allow_nan=False) + '\n')
    print(json.dumps(dict(output=str(output), selection=result['selection']['gates'],
                          validation_read=result['validation'] is not None,
                          deployment_allowed=result['deployment_allowed']), ensure_ascii=False))


if __name__ == '__main__':
    main()
