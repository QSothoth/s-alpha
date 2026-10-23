"""Corrected, descriptive intraday replay; notes/INTRADAY_RECHECK_PREREG_CN.md.

prepare <market>; run <market> selection; choose; run <market> validation; summary.
One process, full indicator history, one day of minute aggregates at a time. Existing
validation dates have been studied before; these results are not a new blind test.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from contextlib import ExitStack
import csv
import gc
import gzip
import hashlib
import json
from pathlib import Path
import shutil
import resource
import time

import numpy as np

from studies import trader_data as TD
from studies.trader_data import panel as TP
from . import confidence as CF, intraday as I, intraday_study as IS, minute as MN

WORK = TD.ROOT / 'data' / 'trader-screens' / 'intraday-recheck'
MARKETS = ('us', 'hk', 'cn')
FIELDS = TP.FIELDS


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=1, default=float) + '\n', encoding='utf-8')


def prepare(market):
    path = WORK / f'{market}_plan.json'
    if path.exists():
        raise FileExistsError(f'{path}: keep the frozen plan')
    source = TD.dataset(market, 'live')
    folder = WORK / 'live' / market
    folder.mkdir(parents=True, exist_ok=True)
    for item in source.dir.glob('*.gz'):
        shutil.copy2(item, folder / item.name)
    ds = prepared_dataset(market)
    cov = MN.coverage(market, ds=ds)
    days = cov['days_all_active_complete'][-20:]
    if len(days) < 2:
        raise ValueError(f'{market}: need two complete days')
    half = len(days) // 2
    write(path, dict(coverage=cov, selection=days[:half], validation=days[half:],
                     data_digest=ds.digest(), rule='V1-V3 must reduce selection order errors by >=10% vs V0'))
    print(market, 'selection', days[:half], 'validation', days[half:], flush=True)


def prepared_dataset(market):
    from studies.trader_data.live import LiveDataset
    return LiveDataset(TD.frozen(market), WORK / 'live')


def partition(market, plan):
    """Read each source once into bounded daily files, rather than decompress the whole market every day."""
    days = plan['coverage']['days_all_active_complete']
    for source in plan['coverage']['sources']:
        folder = WORK / 'minutes' / market / source['sha256']
        if (folder / 'complete').exists():
            continue
        folder.mkdir(parents=True, exist_ok=True)
        with ExitStack() as stack:
            writers = {}
            for day in days:
                f = stack.enter_context(gzip.open(folder / f'{day}.csv.gz', 'wt', newline='', compresslevel=1))
                writers[day] = csv.writer(f)
                writers[day].writerow(MN.HEADER)
            for code, day, hh, *values in MN.stream(MN.K5 / source['file'], days=set(days)):
                writers[day].writerow((code, f'{day} {hh}:00', *values))
        (folder / 'complete').write_text(source['sha256'])


def day_bars(market, day, sources, codes):
    """Prefer the newest complete source for a stock-day; never stitch overlapping volumes twice."""
    bars = {}
    for source in sources:
        cache = WORK / 'minutes' / market / source['sha256']
        path = cache / f'{day}.csv.gz' if (cache / 'complete').exists() else MN.K5 / source['file']
        agg = MN.aggregate(MN.stream(path, days={day}, codes=codes), IS.CUTS[market])
        for (code, _), item in agg.items():
            if (item['first'] == '09:35' and item['last'] == MN.LAST_BAR[market]
                    and item['count'] == CF.total(market) // 5):
                bars[code] = item['parts']
    return bars


def reconcile(market):
    """Daily OHLCV comparisons precede signal replay; the daily total is a reference, never a cutoff input."""
    plan = read(WORK / f'{market}_plan.json')
    partition(market, plan)
    P = TP.build(prepared_dataset(market), write_cache=False)
    col = {str(c): j for j, c in enumerate(P['codes'])}
    di = {str(d): i for i, d in enumerate(P['days'])}
    values = defaultdict(list)
    pairs = 0
    for day in plan['selection'] + plan['validation']:
        bars = day_bars(market, day, plan['coverage']['sources'], set(col))
        d = di[day]
        for code, parts in bars.items():
            j = col[code]
            k = P['close'][d, j] / P['raw_close'][d, j]
            for key, value in zip(('open', 'high', 'low', 'close', 'volume', 'turnover'), parts['full']):
                expected = P[key][d, j] * k if key == 'volume' else P[key][d, j] if key == 'turnover' else P[key][d, j] / k
                if np.isfinite(expected) and expected > 0:
                    values[key].append(value / expected - 1)
            pairs += 1
    result = dict(pairs=pairs, fields={})
    for key, data in values.items():
        a = np.asarray(data)
        result['fields'][key] = dict(n=len(a), median=float(np.median(a)), p90_abs=float(np.quantile(abs(a), .9)),
                                     within_0_1pct=float(np.mean(abs(a) <= .001)))
    if result['fields']['close']['within_0_1pct'] < .95:
        raise ValueError(f'{market}: minute closes fail daily reconciliation: {result}')
    write(WORK / f'{market}_reconcile.json', result)
    print(market, 'reconciled', result, flush=True)


def fractions(P, d, bars, cut):
    out = {}
    for j, code in enumerate(map(str, P['codes'])):
        if code not in bars or cut not in bars[code]:
            continue
        k = P['close'][d, j] / P['raw_close'][d, j]
        total = P['volume'][d, j] * k
        value = bars[code][cut][4] / total if total > 0 else np.nan
        if np.isfinite(value) and value > 0:
            out[code] = min(float(value), 1.)
    return out


def scale_row(row, scheme, fm, history, codes):
    """Only volume and optionally turnover change; V2 reads strictly earlier sessions."""
    if scheme == 'V0':
        return row
    f = np.full(len(codes), fm)
    if scheme == 'V2':
        for j, code in enumerate(map(str, codes)):
            values = history.get(code, [])[-20:]
            if len(values) >= 5:
                f[j] = np.mean(values)
    out = {k: v.copy() for k, v in row.items()}
    out['volume'] /= f
    if scheme != 'V3':
        out['turnover'] /= f
    return out


def skip_limits(decisions, P, d, row, names):
    col = {str(c): j for j, c in enumerate(P['codes'])}
    for result in decisions.values():
        keep = []
        for buy in result['buys']:
            j = col[buy[0]]
            k = P['close'][d, j] / P['raw_close'][d, j]
            prev = P['close'][d - 1, j] / k
            if buy[1] > 0 and I.at_limit_up(buy[0], names.get(buy[0], ''), row['raw_close'][j], prev, str(P['days'][d])):
                continue
            keep.append(buy)
        result['buys'] = keep


def records(market, segment):
    path = WORK / f'{market}_{segment}.jsonl'
    if path.exists():
        with path.open(encoding='utf-8') as f:
            for line in f:
                yield json.loads(line)


def run(market, segment):
    plan = read(WORK / f'{market}_plan.json')
    if not (WORK / f'{market}_reconcile.json').exists():
        raise ValueError('reconcile minute OHLCV against daily bars before running signals')
    partition(market, plan)
    ds = prepared_dataset(market)
    if ds.digest() != plan['data_digest']:
        raise ValueError('daily inputs changed since prepare; keep the original inputs')
    for source in plan['coverage']['sources']:
        h = hashlib.sha256()
        with (MN.K5 / source['file']).open('rb') as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b''):
                h.update(chunk)
        if h.hexdigest() != source['sha256']:
            raise ValueError(f"minute input changed: {source['file']}")
    P = TP.build(ds, write_cache=False)
    codes, col = set(map(str, P['codes'])), {str(d): i for i, d in enumerate(P['days'])}
    done = {r['day'] for r in records(market, segment)}
    chosen = read(WORK / 'choice.json')['chosen'] if segment == 'validation' else None
    fm_path = WORK / f'{market}_fractions.json'
    if fm_path.exists():
        fm = read(fm_path)
    else:
        training = defaultdict(list)
        for day in plan['selection']:
            bars = day_bars(market, day, plan['coverage']['sources'], codes)
            for cut in IS.CUTS[market]:
                training[cut].extend(fractions(P, col[day], bars, cut).values())
        fm = {cut: float(np.median(values)) for cut, values in training.items()}
        if set(fm) != set(IS.CUTS[market]) or not all(0 < f <= 1 for f in fm.values()):
            raise ValueError('missing training volume fractions')
        write(fm_path, fm)
    history = defaultdict(lambda: defaultdict(list))
    eligible = plan['coverage']['days_all_active_complete']
    for day in eligible:
        if day > max(plan[segment]):
            break
        bars = day_bars(market, day, plan['coverage']['sources'], codes)
        d = col[day]
        active = {str(c) for j, c in enumerate(P['codes']) if P['volume'][d, j] > 0 and P['close'][d, j] > 0}
        if active - bars.keys():
            raise ValueError(f'{market} {day}: incomplete active minute names: {sorted(active - bars.keys())}')
        if day in plan[segment] and day not in done:
            started = time.perf_counter()
            rows = {'true': {k: P[k][d].astype(float).copy() for k in FIELDS}}
            for cut in IS.CUTS[market]:
                row, covered = IS.provisional_row(P, d, bars, cut)
                rows[f'{cut}/V0'] = row
                schemes = ('V1', 'V2', 'V3') if segment == 'selection' and cut == IS.MAIN[market] else ()
                if segment == 'validation' and chosen != 'V0':
                    schemes = (chosen,)
                for scheme in schemes:
                    rows[f'{cut}/{scheme}'] = scale_row(row, scheme, fm[cut], history[cut], P['codes'])
            for cause in ('close', 'range', 'volume'):
                rows[f'{IS.MAIN[market]}/{cause}'], _ = IS.provisional_row(P, d, bars, IS.MAIN[market], cause=cause)
            # Full history preserves every registered indicator and gate, without a truncated-window approximation.
            decisions = CF.decide_many(P, d, rows, market, L=d + 1)
            if segment == 'selection' and day == plan['selection'][0]:
                for case in ('true', f'{IS.MAIN[market]}/V0'):
                    full = IS.decide(IS.cut_at(P, d, rows[case]), market, day)
                    for sid in full:
                        for key, n in (('buys', 5), ('sells', 4)):
                            a = sorted(json.dumps(x[:n]) for x in decisions[case][sid][key])
                            b = sorted(json.dumps(x[:n]) for x in full[sid][key])
                            if a != b:
                                raise ValueError(f'{market} {day} {sid} {case} {key}: full replay differs')
                write(WORK / f'{market}_equivalence.json', dict(day=day, systems=7, rows=2, ok=True))
                print(market, 'full-runner equivalence passed', day, flush=True)
            if market == 'cn':
                for case, dec in decisions.items():
                    skip_limits(dec, P, d, rows[case], ds.names())
            result = dict(day=day, segment=segment, covered=len(bars), systems=decisions,
                          seconds=round(time.perf_counter() - started, 2),
                          peak_rss_mb=round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1))
            with (WORK / f'{market}_{segment}.jsonl').open('a', encoding='utf-8') as f:
                f.write(json.dumps(result, ensure_ascii=False, default=float) + '\n')
            print(market, segment, day, result['seconds'], 'seconds', flush=True)
            del rows, decisions, result
            gc.collect()
        for cut in IS.CUTS[market]:
            for code, value in fractions(P, d, bars, cut).items():
                history[cut][code].append(value)
                history[cut][code] = history[cut][code][-20:]


def comparisons(record):
    truth = dict(systems=record['systems']['true'])
    out = {}
    for case, dec in record['systems'].items():
        if case == 'true':
            continue
        out[case] = IS.compare(truth, dict(systems=dec))
        for sid, stats in out[case].items():
            for key, field in (('buys', 'buy_setup'), ('sells', 'sell_reason')):
                a = {(x[0], x[1], x[5] if key == 'buys' else x[3]) for x in dec[sid][key]}
                b = {(x[0], x[1], x[5] if key == 'buys' else x[3]) for x in truth['systems'][sid][key]}
                counts = defaultdict(lambda: [0, 0, 0])
                for i, group in enumerate((a & b, a - b, b - a)):
                    for _, _, kind in group:
                        counts[kind][i] += 1
                stats[field] = dict(counts)
    return out


def choose():
    errors = dict.fromkeys(('V0', 'V1', 'V2', 'V3'), 0)
    for market in MARKETS:
        plan = read(WORK / f'{market}_plan.json')
        got = list(records(market, 'selection'))
        if {r['day'] for r in got} != set(plan['selection']):
            raise ValueError(f'{market}: selection incomplete')
        for r in got:
            comparisons_ = comparisons(r)
            for scheme in errors:
                for stats in comparisons_[f'{IS.MAIN[market]}/{scheme}'].values():
                    errors[scheme] += sum(sum(stats[what][1:]) for what in ('buys', 'sells'))
    chosen = min(errors, key=errors.get)
    if errors['V0'] == 0 or errors[chosen] > .9 * errors['V0']:
        chosen = 'V0'
    path = WORK / 'choice.json'
    if path.exists():
        raise FileExistsError(f'{path}: selection is already locked')
    write(path, dict(chosen=chosen, errors=errors))
    print(chosen, errors, flush=True)


def summary():
    out = dict(choice=read(WORK / 'choice.json'), markets={}, limitation='Previously studied dates; descriptive replay, not new blind validation.')
    for market in MARKETS:
        out['markets'][market] = market_out = dict(plan=read(WORK / f'{market}_plan.json'), segments={})
        market_out['reconcile'] = read(WORK / f'{market}_reconcile.json')
        market_out['volume_fractions'] = read(WORK / f'{market}_fractions.json')
        for segment in ('selection', 'validation'):
            totals = {}
            ran = list(records(market, segment))
            if {r['day'] for r in ran} != set(market_out['plan'][segment]):
                raise ValueError(f'{market} {segment}: incomplete; do not publish summary')
            for r in ran:
                for case, systems in comparisons(r).items():
                    case_out = totals.setdefault(case, {})
                    for sid, stats in systems.items():
                        target = case_out.setdefault(sid, dict(sig=[0, 0, 0], buys=[0, 0, 0], sells=[0, 0, 0],
                                                               setup={}, buy_setup={}, sell_reason={}, gaps=[]))
                        for what in ('sig', 'buys', 'sells'):
                            target[what] = [a + b for a, b in zip(target[what], stats[what])]
                        for field in ('setup', 'buy_setup', 'sell_reason'):
                            for setup, counts in stats[field].items():
                                target[field][setup] = [a + b for a, b in zip(target[field].get(setup, [0, 0, 0]), counts)]
                        target['gaps'].extend(stats['gaps'])
            market_out['segments'][segment] = totals
    path = Path(__file__).with_name('reports') / 'intraday_recheck_summary.json'
    write(path, out)
    print(path, flush=True)


def partial():
    """Summarize saved selection rows only, without loading bars or replaying any system."""
    out = dict(status='stopped_at_user_request', validation_run=False, chosen=None, markets={})
    for market in MARKETS:
        rows = list(records(market, 'selection'))
        if not rows:
            continue
        plan = read(WORK / f'{market}_plan.json')
        target = out['markets'][market] = dict(days=[r['day'] for r in rows], cases={}, attribution={},
            pool=plan['coverage']['names'], covered=[r['covered'] for r in rows],
            reconcile=read(WORK / f'{market}_reconcile.json'),
            sources=plan['coverage']['sources'],
            include_in_conclusions=market != 'cn',
            limitation='CN pilot used the earlier limit-up marker; not rerun after the user stopped the study.' if market == 'cn' else '')
        for r in rows:
            for case, systems in comparisons(r).items():
                dst = target['cases'].setdefault(case, {})
                for sid, stats in systems.items():
                    t = dst.setdefault(sid, dict(sig=[0, 0, 0], buys=[0, 0, 0], sells=[0, 0, 0],
                                                 setup={}, buy_setup={}, sell_reason={}, gaps=[]))
                    for key in ('sig', 'buys', 'sells'):
                        t[key] = [a + b for a, b in zip(t[key], stats[key])]
                    for field in ('setup', 'buy_setup', 'sell_reason'):
                        for kind, values in stats[field].items():
                            t[field][kind] = [a + b for a, b in zip(t[field].get(kind, [0, 0, 0]), values)]
                    t['gaps'].extend(stats['gaps'])
            for key in ('sig', 'buys', 'sells'):
                t = target['attribution'].setdefault(key, dict(total=0, close=0, range=0, volume=0, combined=0))
                for sid, truth in r['systems']['true'].items():
                    expected = IS.keys(truth, key)
                    bad = IS.keys(r['systems'][f'{IS.MAIN[market]}/V0'][sid], key) ^ expected
                    t['total'] += len(bad)
                    resolved = set()
                    for cause in ('close', 'range', 'volume'):
                        fixed = bad - (IS.keys(r['systems'][f'{IS.MAIN[market]}/{cause}'][sid], key) ^ expected)
                        t[cause] += len(fixed)
                        resolved |= fixed
                    t['combined'] += len(bad - resolved)
    path = Path(__file__).with_name('reports') / 'intraday_recheck_partial.json'
    write(path, out)
    print(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('prepare', 'reconcile', 'run', 'choose', 'summary', 'partial'))
    parser.add_argument('market', nargs='?', choices=MARKETS)
    parser.add_argument('segment', nargs='?', choices=('selection', 'validation'))
    args = parser.parse_args()
    if args.action == 'prepare':
        prepare(args.market)
    elif args.action == 'reconcile':
        reconcile(args.market)
    elif args.action == 'run':
        if not args.segment:
            parser.error('run requires selection or validation')
        run(args.market, args.segment)
    elif args.action == 'choose':
        choose()
    elif args.action == 'partial':
        partial()
    else:
        summary()


if __name__ == '__main__':
    main()
