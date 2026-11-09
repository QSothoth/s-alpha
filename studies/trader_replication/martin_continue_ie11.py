"""IE11: relaxed upstream filters and causal, static-membership plate factors."""
import argparse
from collections import defaultdict
from datetime import datetime, timezone
import csv
import gc
import gzip
import logging.handlers
import os
from pathlib import Path
import resource
import socket
import sys
import time
from unittest.mock import patch

import numpy as np

from studies.trader_replication import martin_continue_ie10 as ie10

ie9, ie8, ie7, prior, old = ie10.ie9, ie10.ie8, ie10.ie7, ie10.prior, ie10.old
ROOT, REPORTS = ie10.ROOT, ie10.REPORTS
WORK = REPORTS / 'ie11_work'
PREFIX = 'strong_continue_ie11_'
PLAN = ROOT / 'studies/martin_luk/notes/PLAN_IE11_CN.md'
PREREG = ROOT / 'studies/martin_luk/notes/PREREG_IE11_CN.md'
YEARS, HALVES, TOPS = ie10.YEARS, ie10.HALVES, ie10.TOPS
SEED, RANDOM_SEED = 20261111, 2026111100
KINDS = ('industry', 'concept')
METRICS = ('heat5', 'heat20', 'heat60', 'diffusion_pot', 'diffusion_history',
           'leader20', 'leader60', 'heat_change5', 'hot_count')
NAMES = tuple(k + '.' + m for k in KINDS for m in METRICS) + ie10.FACTORS
CUTOFFS = ie10.CUTOFFS


def read(name):
    return ie7.read(REPORTS / (PREFIX + name + '.json'))


def write(name, value):
    path = REPORTS / (PREFIX + name + '.json')
    if path.exists():
        raise ValueError('saved IE11 stage is immutable: ' + name)
    old.prior.write_json(path, value)


def cached_codes():
    codes = set(ie7.read(ROOT / 'data/trader-screens/cache/industry_us.json'))
    for version in ('v1', 'v2'):
        u = ie7.read(ROOT / ('data/trader-data-' + version + '/us/universe.json'))
        codes.update(r['code'] for r in u['stocks'])
    codes.update(p.stem for p in (old.WORK / 'stocks').glob('*.npz'))
    return sorted(c for c in codes if c.startswith('US.'))


def fetch_plates():
    directory = WORK / 'plates'
    codes = cached_codes()
    receipt = directory / 'started.json'
    with receipt.open('x', encoding='utf-8') as stream:
        import json
        json.dump(dict(utc=datetime.now(timezone.utc).isoformat(), codes=codes,
                       batch_size=200, spacing_seconds=3.5, plan_sha256=prior.file_sha(PLAN)), stream)
    batches, error, q = [], None, None
    try:
        with socket.create_connection(('127.0.0.1', 11111), timeout=3):
            pass
        # The SDK constructs its logger at import; redirect its path without changing HOME.
        join = os.path.join
        def log_join(*parts):
            if len(parts) == 2 and parts[1] == '.com.futunn.FutuOpenD/Log':
                return str(directory / 'logs')
            return join(*parts)
        with patch('os.path.join', log_join):
            import futu as ft
        ft.SysConfig.enable_console_log(False)
        q = ft.OpenQuoteContext(host='127.0.0.1', port=11111)
        for start in range(0, len(codes), 200):
            if batches:
                time.sleep(3.5)
            batch = codes[start:start + 200]
            stamp = datetime.now(timezone.utc).isoformat()
            ret, frame = q.get_owner_plate(batch)
            rows = frame.to_dict('records') if ret == ft.RET_OK else []
            got = {r['code'] for r in rows}
            record = dict(batch=len(batches), utc=stamp, codes=batch, ret=int(ret), rows=rows,
                          error=None if ret == ft.RET_OK else str(frame),
                          missing_codes=[c for c in batch if c not in got])
            old.prior.write_json(directory / f'batch_{len(batches):03d}.json', record)
            batches.append(dict(batch=record['batch'], utc=stamp, size=len(batch), ret=int(ret),
                                rows=len(rows), missing=len(record['missing_codes'])))
            print('plate batch', len(batches), 'rows', len(rows), 'ret', ret, flush=True)
            if ret != ft.RET_OK and any(s in str(frame).lower() for s in ('权限', 'permission', 'login', '登录')):
                error = str(frame)
                break
    except Exception as exc:
        error = type(exc).__name__ + ': ' + str(exc)
    finally:
        if q is not None:
            q.close()
    members = {k: defaultdict(set) for k in KINDS}
    covered = {k: set() for k in KINDS}
    industry_names = {}
    for path in sorted(directory.glob('batch_*.json')):
        for row in ie7.read(path)['rows']:
            kind = str(row['plate_type']).lower()
            if kind in KINDS:
                members[kind][str(row['plate_code'])].add(row['code'])
                covered[kind].add(row['code'])
                if kind == 'industry':
                    industry_names[row['plate_name']] = str(row['plate_code'])
    fallback = ie7.read(ROOT / 'data/trader-screens/cache/industry_us.json')
    supplemented = 0
    for code, name in fallback.items():
        if code in codes and code not in covered['industry'] and name:
            members['industry'][industry_names.get(name, 'cached:' + name)].add(code)
            covered['industry'].add(code)
            supplemented += 1
    result = dict(utc=datetime.now(timezone.utc).isoformat(), requested=len(codes), codes=codes,
                  batches=batches, error=error, requested_batches=(len(codes) + 199) // 200,
                  fallback_industry_codes=supplemented,
                  summary={k: dict(plates=len(members[k]), securities=len(covered[k])) for k in KINDS},
                  members={k: {g: sorted(v) for g, v in sorted(members[k].items())} for k in KINDS})
    old.prior.write_json(directory / 'membership.json', result)
    write('plates', {k: v for k, v in result.items() if k not in ('members', 'codes')})


def member_factors(close, pot, history, groups, minimum=5):
    """Bounded date-by-security arrays; every operation is prefix causal."""
    close = np.asarray(close)
    shape = close.shape
    returns, means = {}, {}
    valid_close = np.isfinite(close) & (close > 0)
    for n in (5, 20, 60):
        r = np.full(shape, np.nan, np.float32)
        valid = valid_close[n:] & valid_close[:-n]
        np.divide(close[n:], close[:-n], out=r[n:], where=valid)
        r[n:] -= 1
        returns[n] = r
        means[n] = np.full((shape[0], len(groups)), np.nan, np.float32)
    out = {m: np.full(shape, np.nan, np.float32) for m in METRICS}
    for g, indices in enumerate(groups):
        indices = np.asarray(indices, int)
        for n in returns:
            values = returns[n][:, indices]
            counts = np.isfinite(values).sum(axis=1)
            np.divide(np.nansum(values, axis=1), counts, out=means[n][:, g], where=counts >= minimum)
            if n in (20, 60):
                ranks = ie7.night_percentiles(values.T).T
                ranks[counts < minimum] = np.nan
                key = 'leader' + str(n)
                out[key][:, indices] = np.fmax(out[key][:, indices], ranks)
        counts = valid_close[:, indices].sum(axis=1)
        for key, strong in (('diffusion_pot', pot), ('diffusion_history', history)):
            values = np.full(shape[0], np.nan, np.float32)
            np.divide((strong[:, indices] & valid_close[:, indices]).sum(axis=1), counts,
                      out=values, where=counts >= minimum)
            out[key][:, indices] = np.fmax(out[key][:, indices], values[:, None])
    heat = {n: ie7.night_percentiles(values.T).T for n, values in means.items()}
    change = np.full(heat[20].shape, np.nan, np.float32)
    change[5:] = heat[20][5:] - heat[20][:-5]
    count_hot = np.zeros(shape, np.float32)
    known = np.zeros(shape, bool)
    for g, indices in enumerate(groups):
        for n in heat:
            key = 'heat' + str(n)
            out[key][:, indices] = np.fmax(out[key][:, indices], heat[n][:, g, None])
        out['heat_change5'][:, indices] = np.fmax(out['heat_change5'][:, indices], change[:, g, None])
        known[:, indices] |= np.isfinite(heat[20][:, g, None])
        count_hot[:, indices] += (heat[20][:, g, None] >= .8)
    out['hot_count'] = np.where(known, count_hot, np.nan)
    return out


def upstream_mask(d, filters):
    pct = np.load(ie7.WORK / ('full_pct.npy' if d.end > prior.TRAIN_END else 'train_pct.npy'), mmap_mode='r')
    passed = np.zeros(d.n, bool)
    widths = {}
    for day, sl in d.slices.items():
        if day >= d.meta['first_signal']:
            passed[sl] = ie8.gate_mask(pct[sl], d.names, filters)
            widths[day] = int(passed[sl].sum())
    return passed, widths


def upstream_result(d, scheme, diagnostic=False):
    filters = scheme['filters']
    valid = {c['name']: {c['cutoff'], round(c['cutoff'] - .1, 1)} for c in ie9.GATES}
    if not diagnostic and (not 3 <= len(filters) <= 4 or len({c['name'] for c in filters}) != len(filters)):
        raise ValueError('only one original condition may be removed')
    if any(c['name'] not in valid or c['cutoff'] not in valid[c['name']] or c['direction'] != 1 for c in filters):
        raise ValueError('upstream threshold outside the registered two levels')
    passed, widths = upstream_mask(d, filters)
    c = ie7.coverage(d.entries, d.query, np.full(d.n, old.prior.SENTINEL), passed)
    halves = {h: dict(n=s['n'], scope=s['scope'], retained=s['gated'],
                      in_scope_rate=s['gated'] / s['scope'] if s['scope'] else 0.,
                      full_rate=s['gated'] / s['n'] if s['n'] else 0.) for h, s in c['halfyear'].items()}
    minimum = min(r['in_scope_rate'] for r in halves.values())
    return dict(scheme=scheme, halves=halves, coverage=c, width=ie10.width_summary(widths),
                minimum_retention=minimum, feasible=minimum >= .9)


def upstream_key(r):
    return (r['feasible'], 0 if r['feasible'] else r['minimum_retention'],
            -r['width']['combined']['median'], -max(r['width'][y]['median'] for y in YEARS),
            -len(r['scheme']['filters']))


def registration(path):
    return dict(spec=ie7.read(path), utc=datetime.now(timezone.utc).isoformat(),
                spec_sha256=prior.file_sha(path), prereg_sha256=prior.file_sha(PREREG),
                prereg_text=PREREG.read_text(), plan_sha256=prior.file_sha(PLAN))


def upstream_round(number):
    if number not in (1, 2):
        raise ValueError('upstream round budget')
    reg = registration(WORK / f'upstream{number}.json')
    if not 1 <= len(reg['spec']['schemes']) <= 5:
        raise ValueError('upstream scheme budget')
    write(f'upstream{number}_registration', reg)
    d = ie7.Data()
    results = [upstream_result(d, s) for s in reg['spec']['schemes']]
    write(f'upstream{number}', dict(registration=reg, results=results, winner=max(results, key=upstream_key)))
    for r in results:
        print(r['scheme']['id'], 'retention', r['minimum_retention'], 'width',
              r['width']['combined']['median'], r['halves'], flush=True)


def freeze_upstream():
    results = [r for p in sorted(REPORTS.glob(PREFIX + 'upstream[12].json')) for r in ie7.read(p)['results']]
    write('upstream_frozen', dict(final=max(results, key=upstream_key),
                                  utc=datetime.now(timezone.utc).isoformat(), plan_sha256=prior.file_sha(PLAN)))


def prepare_features():
    if (WORK / 'features.json').exists():
        raise ValueError('features already saved')
    d = ie7.Data(full=True)
    member = ie7.read(WORK / 'plates/membership.json')
    codes = member['codes']
    ci = {c: j for j, c in enumerate(codes)}
    di = {day: t for t, day in enumerate(d.meta['days'])}
    shape = len(di), len(codes)
    close = np.full(shape, np.nan, np.float32)
    original_codes = list(map(str, np.load(old.WORK / 'panel/codes.npy', mmap_mode='r')))
    original_close = np.load(old.WORK / 'panel/close.npy', mmap_mode='r')
    for j, code in enumerate(original_codes):
        close[:, ci[code]] = original_close[:, j]
    original_set = set(original_codes)
    source = ROOT / 'data/trader-data-v2/us/bars_qfq.csv.gz'
    added_rows = 0
    with gzip.open(source, 'rt') as stream:
        for row in csv.DictReader(stream):
            code, day = row['code'], row['date']
            if code in ci and code not in original_set and day in di:
                value = float(row['close'])
                if np.isfinite(value) and value > 0:
                    close[di[day], ci[code]] = value
                    added_rows += 1
    print('price matrix', shape, 'additional rows', added_rows, flush=True)
    pot, history = np.zeros(shape, bool), np.zeros(shape, bool)
    pct = np.load(ie7.WORK / 'full_pct.npy', mmap_mode='r')
    for day, sl in d.slices.items():
        js = [ci[c] for c in d.meta['scope'][day]]
        pot[di[day], js] = pct[sl, d.names.index('pot_count20')] >= .7 - 1e-7
        history[di[day], js] = pct[sl, d.names.index('h4_history')] >= .6 - 1e-7
    for name, values in (('member_close', close), ('member_pot', pot), ('member_history', history)):
        np.save(WORK / (name + '.npy'), values)
    dest = np.lib.format.open_memmap(WORK / 'features.npy', mode='w+', dtype=np.float32, shape=(d.n, len(NAMES)))
    dest[:] = np.nan
    inventories = {}
    for kind in KINDS:
        groups = [[ci[c] for c in members if c in ci] for members in member['members'][kind].values()]
        print('compute', kind, 'groups', len(groups), flush=True)
        values = member_factors(close, pot, history, groups)
        for day, sl in d.slices.items():
            t, js = di[day], [ci[c] for c in d.meta['scope'][day]]
            for metric in METRICS:
                dest[sl, NAMES.index(kind + '.' + metric)] = values[metric][t, js]
        inventories[kind] = dict(groups=len(groups), total_memberships=sum(map(len, groups)),
            usable_memberships=sum(len(g) for g in groups if len(g) >= 5))
        del values
        gc.collect()
        dest.flush()
    high = np.load(old.WORK / 'panel/high.npy', mmap_mode='r')
    low = np.load(old.WORK / 'panel/low.npy', mmap_mode='r')
    after = np.full(high.shape, np.nan, np.float32)
    valid = np.isfinite(high[1:-1]) & np.isfinite(high[:-2]) & np.isfinite(low[1:-1]) & np.isfinite(low[:-2])
    after[2:] = np.where(valid, (high[1:-1] <= high[:-2]) & (low[1:-1] >= low[:-2]), np.nan)
    original_ci = {c: j for j, c in enumerate(original_codes)}
    for day, sl in d.slices.items():
        dest[sl, NAMES.index('after_inside')] = after[di[day], [original_ci[c] for c in d.meta['scope'][day]]]
        dest[sl, NAMES.index('near_ema9')] = d.raw[sl, d.names.index('near_ema9')]
    dest.flush()
    passed, widths = upstream_mask(d, read('upstream_frozen')['final']['scheme']['filters'])
    filtered = np.lib.format.open_memmap(WORK / 'filter_pct.npy', mode='w+', dtype=np.float32,
                                        shape=(d.n, len(NAMES) - len(ie10.FACTORS)))
    filtered[:] = np.nan
    for sl in d.slices.values():
        rows = np.flatnonzero(passed[sl]) + sl.start
        filtered[rows] = ie7.night_percentiles(dest[rows, :len(METRICS) * len(KINDS)])
    filtered.flush()
    coverage = []
    for j, name in enumerate(NAMES):
        annual = {}
        for year in (*YEARS, '2026'):
            total = finite = 0
            for day, sl in d.slices.items():
                if day.startswith(year):
                    rows = np.flatnonzero(passed[sl]) + sl.start
                    total += len(rows)
                    finite += int(np.isfinite(dest[rows, j]).sum())
            annual[year] = dict(valid=finite, total=total, fraction=finite / total if total else 0.)
        coverage.append(dict(name=name, annual=annual))
    del dest, filtered, close, pot, history, after
    sources = [source, PLAN, WORK / 'plates/membership.json', old.WORK / 'prepared.json',
               old.WORK / 'raw.npy', ie7.WORK / 'full_pct.npy', ie7.WORK / 'train_pct.npy',
               ROOT / 'data/trader-screens/cache/industry_us.json']
    sources.extend(sorted((old.WORK / 'panel').glob('*.npy')))
    inputs = {str(p.relative_to(ROOT)): prior.file_sha(p) for p in sources}
    old.prior.write_json(WORK / 'features.json', dict(names=list(NAMES), rows=d.n,
        input_sha256=inputs, feature_sha256=prior.file_sha(WORK / 'features.npy'),
        percentile_sha256=prior.file_sha(WORK / 'filter_pct.npy'), source_sha256=prior.file_sha(Path(__file__)),
        inventory=inventories, annual_coverage=coverage, prices=shape, additional_rows=added_rows,
        dataset_digest=d.meta['dataset_digest']))
    write('inventory', dict(rows=coverage, plates=inventories, prices=shape, additional_rows=added_rows))


def rank_night(values, passed, factors):
    kept = np.flatnonzero(passed)
    score = np.zeros(len(kept), float)
    for factor in factors:
        name, direction = factor['name'], factor['direction']
        a = values[kept, list(NAMES).index(name)]
        pct = a if name == 'after_inside' else ie7.night_percentiles(a[:, None])[:, 0]
        pct = np.nan_to_num(pct, nan=.5)
        score += pct if direction > 0 else 1 - pct
    if factors:
        score /= len(factors)
    order = kept[np.argsort(-score, kind='stable')]
    ranks = np.full(len(passed), old.prior.SENTINEL, np.int32)
    ranks[order] = np.arange(1, len(order) + 1)
    return order, ranks


def score_key(r):
    return (min(ie7.rate(r['coverage']['halfyear'][h]) for h in HALVES),
            -len(r['scheme']['filters']), ie7.rate(r['coverage']['all_entries']))


def winner(results):
    return max([r for r in results if r['eligible']] or results, key=score_key)


class Data(ie7.Data):
    def __init__(self, full=False, shuffled=False):
        super().__init__(full=full)
        self.base_passed, self.base_widths = upstream_mask(self, read('upstream_frozen')['final']['scheme']['filters'])
        self.values = np.load(WORK / 'features.npy', mmap_mode='r')[:self.n]
        self.filter_values = np.load(WORK / 'filter_pct.npy', mmap_mode='r')[:self.n]
        self.label = 'shuffle' if shuffled else 'true'
        if shuffled:
            rng = np.random.default_rng(SEED)
            mapping = np.arange(self.n)
            for sl in self.slices.values():
                kept = np.flatnonzero(self.base_passed[sl]) + sl.start
                mapping[kept] = rng.permutation(kept)
            self.query = [[int(mapping[q]) if q >= 0 else -1 for q in qs] for qs in self.query]
        self.row_width = np.zeros(self.n, np.int32)

    def select(self, scheme):
        self.passed = self.base_passed.copy()
        for c in scheme['filters']:
            self.passed &= ie10.filter_mask(self.filter_values[:, NAMES.index(c['name'])], c)
        ranks = np.full(self.n, old.prior.SENTINEL, np.int32)
        selected, self.widths = {}, {}
        for day, sl in self.slices.items():
            if day not in self.base_widths:
                continue
            self.widths[day] = int(self.passed[sl].sum())
            self.row_width[sl] = self.widths[day]
            order, ranks[sl] = rank_night(self.values[sl], self.passed[sl], scheme['factors'])
            selected[day] = [self.meta['scope'][day][k] for k in order[:5]]
        self.expected = ie9.random_expectation(self.entries, self.query, self.passed, self.row_width)
        coverage = ie7.coverage(self.entries, self.query, ranks, self.passed)
        base = ie7.coverage(self.entries, self.query, ranks, self.base_passed)
        for a, b in zip(coverage['rows'], base['rows']):
            a['upstream_retained'] = b['passed_gate']
        return selected, coverage

    def evaluate(self, scheme):
        key = prior.digest(dict(scheme=scheme, end=self.end, label=self.label,
            source=prior.file_sha(Path(__file__)), features=ie7.read(WORK / 'features.json')['feature_sha256']))
        path = WORK / 'evaluations' / (key + '.json')
        if path.exists():
            return ie7.read(path)
        selected, coverage = self.select(scheme)
        account_key = prior.digest(dict(selected=selected, end=self.end))
        paths = [w / 'accounts' / (account_key + '.json') for w in (WORK, ie10.WORK, ie9.WORK, ie8.WORK, ie7.WORK)]
        cached = next((p for p in paths if p.exists()), None)
        accounts = ie7.read(cached) if cached else self.accounts(selected)
        if cached is None:
            old.prior.write_json(paths[0], accounts)
        eligible, failures = ie10.qualify(coverage, self.expected, accounts)
        primary = [r for r in coverage['rows'] if r['primary']]
        groups = dict(combined=primary)
        groups.update({h: [r for r in primary if ie7.half(r['entry_date']) == h] for h in HALVES})
        groups.update({y: [r for r in primary if r['entry_date'].startswith(y)] for y in (*YEARS, '2026')})
        funnel = {k: dict(n=len(rows), scope=sum(r['in_scope'] for r in rows),
            upstream=sum(r['upstream_retained'] for r in rows), filtered=sum(r['passed_gate'] for r in rows),
            top5=sum(r['best_rank'] <= 5 for r in rows)) for k, rows in groups.items()}
        f = funnel['combined']
        losses = dict(scope=f['n'] - f['scope'], upstream=f['scope'] - f['upstream'],
                      filters=f['upstream'] - f['filtered'], ranking=f['filtered'] - f['top5'])
        result = dict(scheme=scheme, coverage=coverage, accounts=accounts, eligible=eligible, failures=failures,
            expected=self.expected, selected=selected, selection_hash=account_key, nightly_widths=self.widths,
            width=ie10.width_summary(self.widths), funnel=funnel,
            losses=dict(counts=losses, largest=max(losses, key=losses.get)))
        result['score'] = list(score_key(result))
        old.prior.write_json(path, result)
        return result


def describe(d):
    rows = []
    for kind in KINDS:
        for metric in METRICS:
            name = kind + '.' + metric
            for direction in (1, -1):
                for cutoff in CUTOFFS:
                    condition = dict(name=name, kind='percentile', direction=direction, cutoff=cutoff)
                    passed = d.base_passed & ie10.filter_mask(d.filter_values[:, NAMES.index(name)], condition)
                    halves = {}
                    for h in HALVES:
                        indices = [i for i, e in enumerate(d.entries) if e['target']['tier'] == 'primary'
                                   and ie7.half(e['entry_date']) == h]
                        baseline = sum(any(q >= 0 and d.base_passed[q] for q in d.query[i]) for i in indices)
                        retained = sum(any(q >= 0 and passed[q] for q in d.query[i]) for i in indices)
                        days = [day for day in d.base_widths if ie7.half(day) == h]
                        widths = [int(passed[d.slices[day]].sum()) for day in days]
                        ratios = [w / d.base_widths[day] for day, w in zip(days, widths) if d.base_widths[day]]
                        ratio = float(np.median(ratios)) if ratios else 0.
                        rate = retained / baseline if baseline else 0.
                        halves[h] = dict(n=len(indices), upstream_retained=baseline, retained=retained,
                            retention=rate, full_retention=retained / len(indices) if indices else 0.,
                            width_ratio=ratio, median_width=float(np.median(widths)), advantage=rate - ratio)
                    rows.append(dict(condition=condition, halves=halves,
                        stable=all(r['advantage'] > 1e-10 for r in halves.values()),
                        min_advantage=min(r['advantage'] for r in halves.values())))
    return dict(rows=rows, stable=[r['condition'] for r in rows if r['stable']], selection_years=list(YEARS),
                label=d.label, prereg_sha256=prior.file_sha(PREREG))


def ranking_names(allowed, kind):
    return list(dict.fromkeys((c['name'], c['direction']) for c in allowed if c['name'].startswith(kind + '.')))


def validate(scheme, allowed):
    if scheme['kind'] not in (*KINDS, 'reference'):
        raise ValueError('unknown plate branch')
    filters, factors = scheme['filters'], scheme['factors']
    if len(filters) > 3 or len({c['name'] for c in filters}) != len(filters):
        raise ValueError('new filtering condition budget')
    if not 1 <= len(factors) <= 4 or len({c['name'] for c in factors}) != len(factors):
        raise ValueError('ranking factor budget')
    if any(c not in allowed or not c['name'].startswith(scheme['kind'] + '.') for c in filters):
        raise ValueError('filter did not qualify in this branch')
    ranks = set(ranking_names(allowed, scheme['kind'])) | {(n, 1) for n in ie10.FACTORS}
    if any((f['name'], f['direction']) not in ranks for f in factors):
        raise ValueError('ranking direction did not qualify')
    if scheme['kind'] == 'reference' and (filters or any(f['name'] not in ie10.FACTORS for f in factors)):
        raise ValueError('reference must use only the fixed anchors')


def run_round(number):
    if number not in (1, 2, 3):
        raise ValueError('plate round budget')
    reg = registration(WORK / f'round{number}.json')
    if not 1 <= len(reg['spec']['schemes']) <= 5:
        raise ValueError('combined branch scheme budget')
    allowed = read('description')['stable']
    for scheme in reg['spec']['schemes']:
        validate(scheme, allowed)
    write(f'round{number}_registration', reg)
    d, results = Data(), []
    for scheme in reg['spec']['schemes']:
        r = d.evaluate(scheme)
        results.append(r)
        print(scheme['id'], r['score'], r['eligible'], r['failures'], r['funnel']['combined'], flush=True)
    write(f'round{number}', dict(registration=reg, results=results, winner=winner(results)))


def ablate(d, start):
    current, rounds = start, []
    while True:
        trials, accepted = [], False
        for field in ('filters', 'factors'):
            for k, item in enumerate(current['scheme'][field]):
                if field == 'factors' and len(current['scheme'][field]) == 1:
                    continue
                scheme = dict(current['scheme'], **{field: current['scheme'][field][:k] + current['scheme'][field][k + 1:]},
                              id=current['scheme']['id'] + '-' + field + '-drop' + str(k))
                after = d.evaluate(scheme)
                accept = after['eligible'] and after['score'][0] >= current['score'][0]
                trials.append(dict(field=field, removed=item, result=after, accepted=bool(accept)))
                if accept:
                    current, accepted = after, True
                    break
            if accepted:
                break
        rounds.append(dict(trials=trials))
        if not accepted:
            return dict(initial=start, rounds=rounds, final=current)


def all_results():
    return [r for p in sorted(REPORTS.glob(PREFIX + 'round[123].json')) for r in ie7.read(p)['results']]


def ablation_stage():
    d, results = Data(), all_results()
    branches = {k: ablate(d, winner([r for r in results if r['scheme']['kind'] in (k, 'reference')])) for k in KINDS}
    write('ablation', branches)
    # Frozen upstream remains fixed; removing its conditions is a separate diagnostic.
    base = read('upstream_frozen')['final']['scheme']
    diagnostic = [upstream_result(d, dict(id='diagnostic-drop' + str(i), filters=base['filters'][:i] + base['filters'][i + 1:]), diagnostic=True)
                  for i in range(len(base['filters']))]
    write('upstream_ablation', dict(trials=diagnostic, selection_use=False,
                                  note='只量去掉上游条件的保留率和宽度，不据此改已冻结上游。'))
    for k, a in branches.items():
        print(k, 'ABLATION', a['final']['scheme'], a['final']['score'], flush=True)


def random_controls(d, actual):
    with patch.object(ie9, 'RANDOM_SEED', RANDOM_SEED):
        return ie9.random_controls(d, actual)


def random_stage():
    d = Data()
    output = {}
    for kind, a in read('ablation').items():
        d.select(a['final']['scheme'])
        output[kind] = random_controls(d, a['final'])
    write('random', output)


def shuffle_stage():
    d = Data(shuffled=True)
    description = describe(d)
    write('shuffle_description', description)
    real, shuffled = read('description')['stable'], description['stable']
    results, unavailable = [], []
    for original in (s for p in sorted(WORK.glob('round[123].json')) for s in ie7.read(p)['schemes']):
        kind = original['kind']
        a = [c for c in real if c['name'].startswith(kind + '.')]
        b = [c for c in shuffled if c['name'].startswith(kind + '.')]
        ar, br = ranking_names(real, kind), ranking_names(shuffled, kind)
        try:
            filters = [b[a.index(c)] for c in original['filters']]
            factors = [dict(zip(('name', 'direction'), br[ar.index((f['name'], f['direction']))]))
                       if f['name'] not in ie10.FACTORS else f for f in original['factors']]
            scheme = dict(original, filters=filters, factors=factors)
            validate(scheme, shuffled)
        except (IndexError, ValueError):
            unavailable.append(original['id'])
            continue
        results.append(d.evaluate(scheme))
    branches = {}
    for kind in KINDS:
        usable = [r for r in results if r['scheme']['kind'] in (kind, 'reference')]
        if not usable:
            raise ValueError('the registered common reference is required for a shuffle fallback')
        a = ablate(d, winner(usable))
        branches[kind] = dict(ablation=a, final=a['final'],
                              plate_structures=sum(r['scheme']['kind'] == kind for r in usable))
    write('shuffle', dict(seed=SEED, results=results, unavailable=unavailable, branches=branches,
        stable=len(shuffled), note='冻结上游内共享置换；只检验上游之后的同结构搜索，不是完整人工搜索p值。'))


def freeze():
    write('frozen_selection', dict(branches={k: dict(a['final'], score=list(score_key(a['final'])))
                                           for k, a in read('ablation').items()},
        freeze_utc=datetime.now(timezone.utc).isoformat(), selection_years=list(YEARS), exam_used_for_selection=False,
        plan_sha256=prior.file_sha(PLAN), prereg_sha256=prior.file_sha(PREREG),
        source_sha256=prior.file_sha(Path(__file__)), feature_sha256=prior.file_sha(WORK / 'features.npy'),
        percentile_sha256=prior.file_sha(WORK / 'filter_pct.npy')))


def final_stage():
    if (REPORTS / (PREFIX + 'final.json')).exists():
        raise ValueError('the final evaluation has already run')
    frozen = read('frozen_selection')
    if frozen['source_sha256'] != prior.file_sha(Path(__file__)):
        raise ValueError('source changed after freeze')
    d, branches, controls = Data(full=True), {}, {}
    for kind, trained in frozen['branches'].items():
        final = d.evaluate(trained['scheme'])
        historical = {day: codes for day, codes in final['selected'].items() if day <= prior.TRAIN_END}
        if historical != trained['selected']:
            raise AssertionError('future rows changed the historical selections')
        d.select(final['scheme'])
        controls[kind] = random_controls(d, final)
        branches[kind] = final
        print('FINAL', kind, final['coverage']['annual']['2026']['primary'], flush=True)
    write('final', dict(branches=branches, note='2026已看过六次，不是干净考试；行业、概念分列，静态概念成员含未来信息风险。'))
    write('random_final', controls)


def guard(network=False):
    def allowed(path):
        p = Path(os.fsdecode(path)).resolve()
        return p.is_relative_to(WORK.resolve()) or (p.parent == REPORTS.resolve() and p.name.startswith(PREFIX))
    def audit(event, args):
        if event == 'open':
            path, _, flags = args
            if not isinstance(path, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND) and not allowed(path):
                raise PermissionError('IE11 output boundary: ' + os.fsdecode(path))
        if event == 'socket.connect':
            if not network or args[1] != ('127.0.0.1', 11111):
                raise PermissionError('IE11 only permits the authorized local plate connection')
        if event in ('socket.bind', 'os.system', 'subprocess.Popen'):
            raise PermissionError('IE11 single process')
        if event in ('os.remove', 'os.rename', 'os.rmdir', 'os.mkdir'):
            paths = args[:2] if event == 'os.rename' else args[:1]
            if any(not allowed(p) for p in paths):
                raise PermissionError('IE11 output boundary')
    sys.addaudithook(audit)


def main(stage):
    import tempfile
    os.environ['TMPDIR'] = str(WORK / 'tmp')
    tempfile.tempdir = str(WORK / 'tmp')
    guard(network=stage == 'plates')
    if stage.startswith('upstream') and stage[-1].isdigit():
        upstream_round(int(stage[-1]))
    elif stage.startswith('round'):
        run_round(int(stage[-1]))
    elif stage == 'describe':
        result = describe(Data())
        write('description', result)
        print('stable plate conditions', len(result['stable']), flush=True)
    else:
        dict(plates=fetch_plates, upstream_freeze=freeze_upstream, features=prepare_features,
             ablate=ablation_stage, random=random_stage, shuffle=shuffle_stage, freeze=freeze, final=final_stage)[stage]()
    write('runtime_' + stage, dict(utc=datetime.now(timezone.utc).isoformat(),
        source_sha256=prior.file_sha(Path(__file__)), plan_sha256=prior.file_sha(PLAN),
        prereg_sha256=prior.file_sha(PREREG), peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('stage', choices=('plates', 'upstream1', 'upstream2', 'upstream_freeze', 'features', 'describe',
                                          'round1', 'round2', 'round3', 'ablate', 'random', 'shuffle', 'freeze', 'final'))
    main(parser.parse_args().stage)
