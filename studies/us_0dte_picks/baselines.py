"""R29 audit registered strategies against existing official evaluation reports."""
from collections import Counter
from dataclasses import asdict
import json
from pathlib import Path
import resource
import statistics
import time

from custody.dataset import Dataset, sha256_file
from custody.evaluate import (_plain, case_value, composite_score, guaranteed_entry,
                              PRIMARY_FILL, run_strategy, summarize)
from custody.registry import Registry
from custody.strategy import session_minute

ROOT = Path(__file__).resolve().parents[2]
STUDY = ROOT / 'studies/us_0dte_picks'
DATASET = 'custody-0dte-v6.1'


def median(values):
    values = [v for v in values if v is not None]
    return statistics.median(values) if values else None


def residual_values(data, trade):
    """Observed premium less intrinsic; NOT pure theta and not subtracted from P&L."""
    values = {}
    closes = {session_minute(data.session, b.close_time): b.close for b in data.underlying}
    sign = 1 if data.case.direction == 'LONG' else -1
    for name in ('entry', 'exit'):
        fill = trade[name]
        if fill is not None and fill['bar_close'] is not None:
            intrinsic = max(0, sign * (closes[fill['fill_minute']] - data.case.strike))
            values[name] = fill['bar_close'] - intrinsic
    return values


def details(trades):
    summary = summarize(trades, trades)
    low = summarize(trades, trades, 0)['balanced']['expectancy']
    high = summarize(trades, trades, 1)['balanced']['expectancy']
    breakeven = -low / (high - low) if low is not None and high is not None and high != low else None
    residuals = [t['residual_value'] for t in trades if len(t.get('residual_value', {})) == 2]
    entered = [t for t in trades if t['entry']]
    sold = [t for t in entered if t['exit'] and not t['exit'].get('settled_at_expiry')]
    return dict(cases=len(trades), outcomes=summary['outcomes'], completed=summary['completed'],
                entered=len(entered), sold=len(sold), expired_settlement=sum(
                    bool(t['exit'] and t['exit'].get('settled_at_expiry')) for t in trades),
                balanced=summary['balanced'], raw=summary['raw'], traded_raw=summary['traded_raw'],
                coverage_gaps=summary['coverage_gaps'],
                score=composite_score(summary)['score'],
                expectations_by_direction_hit_rate={str(p): summarize(trades, trades, p)['balanced']['expectancy']
                                                   for p in (.5, .6, .75, .85)},
                break_even_direction_hit_rate=breakeven,
                entry_reasons=summary['entry_reasons'], exit_reasons=summary['exit_reasons'],
                entry_decision_minute_median=median(t['entry']['minute'] for t in entered),
                entry_fill_minute_median=median(t['entry']['fill_minute'] for t in entered),
                exit_fill_minute_median=median(t['exit']['fill_minute'] for t in sold),
                hold_minutes_median=summary['hold_minutes_median'],
                worst_return=min((t['net_return'] for t in entered if t['net_return'] is not None), default=None),
                residual_value=dict(n=len(residuals),
                    negative_entry=sum(v['entry'] < 0 for v in residuals),
                    negative_exit=sum(v['exit'] < 0 for v in residuals),
                    entry_median=median(v['entry'] for v in residuals),
                    exit_median=median(v['exit'] for v in residuals),
                    change_median=median(v['exit'] - v['entry'] for v in residuals)))


def main():
    began = time.monotonic()
    output = STUDY / 'reports/R29_BASELINES.json'
    registry, dataset = Registry(), Dataset(ROOT / 'data' / DATASET)
    items = {meta['strategy_id']: registry.get(meta['strategy_id']) for meta in registry.list()}
    sources = [Path(__file__).resolve(), STUDY / 'notes/R29_BASELINE_PROTOCOL.md',
               ROOT / 'custody/evaluate.py', ROOT / 'custody/engines/zero_dte_timing.py',
               ROOT / 'custody/engines/open_hold.py', ROOT / 'custody/strategies/index.json']
    reports, original = {}, {}
    for sid, item in items.items():
        path = ROOT / 'reports' / sid / DATASET / 'report.json'
        reports[sid] = json.loads(path.read_text())
        assert reports[sid]['strategy']['sha256'] == item['sha256']
        assert reports[sid]['dataset']['checksums_sha256'] == dataset.fingerprint
        assert reports[sid]['fill_model'] == asdict(PRIMARY_FILL)
        original[sid] = {(t['contract'], t['trade_date']): t for t in reports[sid]['cases']}
        sources += [path, ROOT / 'custody/strategies' / (sid + '.json')]
    hashes = {str(p.relative_to(ROOT)): sha256_file(p) for p in sources}
    trades = {sid: [] for sid in items}
    for case in dataset.cases:
        data = dataset.load(case)
        for sid, item in items.items():
            old = original[sid][case.key]
            trade = run_strategy(data, item)
            trade['decisions'] = None
            actual = _plain(trade)
            assert all(value == old[key] for key, value in actual.items()), (sid, case.key)
            trade['scenario'] = old['scenario']
            trade['residual_value'] = residual_values(data, trade)
            trades[sid].append(trade)
        # Dataset caches complete multi-day files; bound this audit to one case.
        dataset._tapes.clear()
    rows = []
    for sid, values in trades.items():
        report = reports[sid]
        assert _plain(summarize(values, values)) == report['summary'], sid
        row = dict(strategy=sid, mode='required' if guaranteed_entry(items[sid]) else 'selective',
                   strategy_sha256=items[sid]['sha256'], prior_verdict=report['verdict'],
                   overall=details(values),
                   sides={side: details([t for t in values if t['direction'] == direction])
                          for side, direction in (('CALL', 'LONG'), ('PUT', 'SHORT'))},
                   entry_groups={kind: details([t for t in values if t['entry'] and
                       ('fallback' if t['entry']['reason'] in ('deadline_entry', 'open_entry') else 'signal') == kind])
                       for kind in ('signal', 'fallback')},
                   days_with_completed_case=len({t['trade_date'] for t in values if t['outcome'] == 'COMPLETED'}),
                   all_primary_trades_match=True, original_summary_matches=True)
        rows.append(row)
    assert all(sha256_file(ROOT / name) == digest for name, digest in hashes.items())
    result = dict(dataset=DATASET, fingerprint=dataset.fingerprint,
                  verified_files=dataset.checksums_verified, sessions=len(dataset.sessions()),
                  cases=len(dataset.cases), sides=dataset.sides_report(), fill_model=asdict(PRIMARY_FILL),
                  source_sha256=hashes, rows=rows, evaluated_new_candidates=False,
                  replayed_primary_trades=sum(len(v) for v in trades.values()),
                  elapsed_seconds=time.monotonic() - began,
                  max_rss_mb=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + '\n')
    for row in rows:
        s = row['overall']
        print(row['strategy'], row['mode'], '%d/%d' % (s['completed'], s['cases']),
              'balanced=%.4f%%' % (s['balanced']['expectancy'] * 100),
              'CALL=%.4f%% PUT=%.4f%%' % tuple(row['sides'][side]['balanced']['expectancy'] * 100
                                             for side in ('CALL', 'PUT')), flush=True)


if __name__ == '__main__':
    main()
