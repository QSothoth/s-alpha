"""Freeze market-only v1 representatives from a bounded sample, without labels.

Run: OPENBLAS_NUM_THREADS=1 .venv/bin/python -m
     studies.trader_replication.standard_indicators_dedup
"""
import argparse
from collections import OrderedDict
import hashlib
import json
import os
from pathlib import Path
import resource
import shutil
import time

import numpy as np

from studies.trader_replication import standard_indicators as lib

ROOT = Path(__file__).resolve().parents[2]
GAP = ROOT / "studies/trader_replication/reports/gap_review"
WORK = GAP / "ie38_work"
SOURCE = GAP / "ie5_work"
OUTPUT = GAP / "standard_indicators_v1_dedup.json"
SPECIFICATION = ROOT / "skills/trader-replication/references/STANDARD_INDICATORS_CN.md"
SEED = 2026110438
SAMPLE_SIZE = 300_000
T0 = time.monotonic()
VERSION = 'v1'
SPECS = lib.V1_SPEC
REPAIRED_NEW_SERIES = frozenset(('bollinger_width_percentile252',
                               'volume_profile_poc_distance_adr', 'volume_profile_value_position', 'chip_concentration90'))


def configure_version(version):
    global VERSION, WORK, OUTPUT, SPECS
    if version not in ('v1', 'v1.1'):
        raise ValueError('unknown library version')
    VERSION = version
    WORK = GAP / ('ie39_work' if version == 'v1.1' else 'ie38_work')
    OUTPUT = GAP / ('standard_indicators_v1_1_dedup.json' if version == 'v1.1' else 'standard_indicators_v1_dedup.json')
    SPECS = lib.SPEC if version == 'v1.1' else lib.V1_SPEC


def library_hash():
    code = Path(lib.__file__).read_text()
    for name in ('V1_NAMES', 'V1_1_NAMES'):
        start = code.index(name+' = ')
        end = code.index('\n\n', start)
        code = code[:start]+code[end:]
    return hashlib.sha256(code.encode()).hexdigest()


def stock_sample_values(arrays, q, extras):
    if VERSION == 'v1.1':
        values = lib.legacy_per_stock(arrays, q, extras)
        c = np.asarray(arrays['c'], float)
        values['bollinger_width_percentile252'] = lib.own_percentile(
            lib.divide(4*lib.roll(c, 20, 'std'), lib.roll(c, 20)), relative_ties=1e-12)
        adr = lib.roll(lib.divide(arrays['h'], arrays['l'])-1, 20)
        values['volume_profile_poc_distance_adr'], values['volume_profile_value_position'] = lib._volume_profile(
            arrays['h'], arrays['l'], c, arrays['v'], adr, stable_ties=True)
        values['chip_concentration90'] = lib._chips(arrays['h'], arrays['l'], c, arrays['v'], stable_ties=True)['chip_concentration90']
        return {name: np.where(np.isfinite(c), value, np.nan) for name, value in values.items()}
    return lib.per_stock(arrays, q, extras, version='v1')


def cross_sample_values(close, high, low, wanted):
    if VERSION == 'v1.1':
        return lib.legacy_cross_section(close, wanted)
    return lib.cross_section(close, high, low, wanted, version='v1')


def log(*values):
    print(f"[{time.monotonic()-T0:.0f}s]", *values, flush=True)


def capacity(stage):
    size = 0
    for path in WORK.rglob('*'):
        try:
            if path.is_file():
                size += path.stat().st_size
        except FileNotFoundError:
            pass  # Another worker atomically renamed its own checkpoint.
    free = shutil.disk_usage(WORK).free
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024
    if size > 800_000_000 or free < 1_000_000_000 or rss > 900_000_000:
        raise RuntimeError(f"{stage}: resource limit: work={size}, free={free}, peak_rss={rss}")
    return dict(stage=stage, work_bytes=size, free_bytes=free, peak_rss_bytes=rss)


def market_panel():
    """Only three small market x session panels, never a correlation matrix."""
    files = sorted((SOURCE / "stocks").glob("*.npz"))
    days = json.loads((SOURCE / "prepared.json").read_text())["days"]
    panels = [np.full((len(files), len(days)), np.nan, np.float64 if VERSION == 'v1.1' else np.float32) for _ in range(3)]
    for i, path in enumerate(files):
        with np.load(path) as z:
            for panel, field in zip(panels, ("c", "h", "l")):
                panel[i] = z[field]
    return files, days, panels


def load_stock(path, days):
    with np.load(path) as z:
        arrays = {key: z[key] for key in ("o", "h", "l", "c", "v", "t", "raw_c") if key in z.files}
        extras = {key[6:]: z[key] for key in z.files if key.startswith("extra_")}
    arrays["days"] = days
    return arrays, extras


def _save_json(path, value):
    temporary = path.with_suffix(path.suffix+'.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n')
    temporary.replace(path)


def _dedup_worker(kind, start, stop, source_hash, version='v1'):
    """A worker owns disjoint sample rows and its own integer-count checkpoint."""
    configure_version(version)
    path = WORK / f'parallel_{kind}_{start}_{stop}.json'
    state = json.loads(path.read_text()) if path.exists() else dict(
        kind=kind, start=start, stop=stop, next=start, library_sha256=source_hash,
        finite_count=[0]*len(SPECS), nonzero_count=[0]*len(SPECS), complete=False)
    if state['library_sha256'] != source_hash:
        raise ValueError('parallel checkpoint source changed')
    if state['complete']:
        return
    if any(os.environ.get(name) != '1' for name in ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS')):
        raise ValueError('each worker must be single-threaded')
    sample = np.load(WORK/'dedup_sample.npy', mmap_mode='r+' if kind != 'pairs' else 'r')
    if kind == 'pairs':
        def progress(next_index, pairs):
            state.update(next=next_index, pairs=pairs, resources=capacity('pairs'))
            _save_json(path, state)
        state['pairs'] = pair_correlations(sample, state['next'], stop, progress, state.get('pairs'))
    else:
        with np.load(WORK/'dedup_sample_rows.npz') as z:
            stock_rows, day_rows = z['stock'], z['day']
        index = {s['name']: k for k, s in enumerate(SPECS)}
        count, nonzero = np.array(state['finite_count'], np.int64), np.array(state['nonzero_count'], np.int64)
        calendar = json.loads((SOURCE/'prepared.json').read_text())['days']
        nightly = np.array([i for i, day in enumerate(calendar) if '2024-01-01' <= day <= '2025-12-31'])
        if kind == 'stocks':
            files = sorted((SOURCE/'stocks').glob('*.npz'))
            q = np.load(SOURCE/'qqq.npy')
            end = int(nightly[-1])+1
        else:
            _, _, (close, high, low) = market_panel()
        for i in range(state['next'], stop):
            if kind == 'stocks':
                arrays, extras = load_stock(files[i], calendar)
                arrays = {key: value[:end] for key, value in arrays.items()}
                extras = {key: value[:end] for key, value in extras.items()}
                values = stock_sample_values(arrays, q[:end], extras)
                slots = np.flatnonzero(stock_rows == i)
                for name, values_ in values.items():
                    k = index[name]
                    sample[slots, k] = values_[day_rows[slots]]
                    full = values_[nightly]
                    count[k] += np.isfinite(full).sum()
                    nonzero[k] += np.sum(np.isfinite(full) & (full != 0))
            else:
                t = nightly[i]
                slots = np.flatnonzero(day_rows == t)
                a = max(0, t-252)
                values = cross_sample_values(close[:, a:t+1], high[:, a:t+1], low[:, a:t+1], stock_rows[slots])
                for name, values_ in values.items():
                    sample[slots, index[name]] = values_
            if (i+1-start) % (100 if kind == 'stocks' else 50) == 0:
                sample.flush()
                state.update(next=i+1, finite_count=count.tolist(), nonzero_count=nonzero.tolist(), resources=capacity(kind))
                _save_json(path, state)
                log('worker', kind, start, stop, 'next', i+1, state['resources'])
        sample.flush()
        state.update(finite_count=count.tolist(), nonzero_count=nonzero.tolist())
    state.update(next=stop, complete=True, resources=capacity(kind+'_complete'))
    _save_json(path, state)


def process_rss(pid):
    try:
        for line in Path(f'/proc/{pid}/status').read_text().splitlines():
            if line.startswith('VmRSS:'):
                return int(line.split()[1])*1024
    except FileNotFoundError:
        pass
    return 0


def parallel_jobs(kind, start, stop, source_hash):
    """Two workers; the parent only monitors and combines ordered results."""
    from multiprocessing import get_context
    if start >= stop:
        return []
    if kind == 'pairs':
        weights = np.array([len(SPECS)-i-1 for i in range(start, stop)])
        cut = start+int(np.searchsorted(np.cumsum(weights), weights.sum()/2))+1
    else:
        cut = (start+stop)//2
    ranges = [(a, b) for a, b in ((start, cut), (cut, stop)) if a < b]
    context = get_context('spawn')
    processes = [context.Process(target=_dedup_worker, args=(kind, a, b, source_hash, VERSION)) for a, b in ranges]
    peak_sum = 0
    try:
        for process in processes:
            process.start()
        while any(process.is_alive() for process in processes):
            rss = [process_rss(os.getpid())]+[process_rss(process.pid) for process in processes]
            peak_sum = max(peak_sum, sum(rss))
            if any(value > 900_000_000 for value in rss) or sum(rss) > 1_800_000_000:
                raise RuntimeError('parallel memory limit exceeded')
            if any(process.exitcode not in (None, 0) for process in processes):
                raise RuntimeError('dedup worker failed; checkpoints retained')
            capacity('parallel_'+kind)
            time.sleep(1)
        for process in processes:
            process.join()
            if process.exitcode:
                raise RuntimeError('dedup worker failed; checkpoints retained')
    finally:
        for process in processes:
            if process.is_alive():
                process.terminate()
                process.join()
    results = [json.loads((WORK/f'parallel_{kind}_{a}_{b}.json').read_text()) for a, b in ranges]
    upper = capacity('parallel_done')['peak_rss_bytes']+sum(row['resources']['peak_rss_bytes'] for row in results)
    if upper > 1_800_000_000:
        raise RuntimeError('sum of individual peak RSS exceeds parallel budget')
    _save_json(WORK/f'parallel_{kind}_resources.json', dict(
        workers=len(processes), monitored_aggregate_peak_bytes=peak_sum, aggregate_upper_bound_bytes=upper,
        ranges=ranges, process_peak_bytes=[row['resources']['peak_rss_bytes'] for row in results]))
    log('parallel complete', kind, 'aggregate_upper_bound_MB', upper/1e6)
    return results


def sample_values(workers=1):
    source_hash = library_hash()
    checkpoint = WORK / "dedup_sample.json"
    previous = None
    if checkpoint.exists():
        previous = json.loads(checkpoint.read_text())
        if previous["library_sha256"] != source_hash:
            raise RuntimeError("sample belongs to different source; inspect before replacing")
        if previous.get("complete"):
            log("reuse verified sample", previous["sample_size"])
            return np.load(WORK / "dedup_sample.npy", mmap_mode="r"), previous
    files, days, (close, high, low) = market_panel()
    if len(files) != 2277:
        raise ValueError(f"expected all 2277 cached stocks, found {len(files)}")
    nightly = np.array([i for i, day in enumerate(days) if "2024-01-01" <= day <= "2025-12-31"])
    valid = np.isfinite(close[:, nightly]) & (close[:, nightly] > 0)
    eligible = np.flatnonzero(valid.ravel())
    chosen = np.random.default_rng(SEED).choice(eligible, SAMPLE_SIZE, replace=False)
    stock_rows, day_rows = chosen//len(nightly), nightly[chosen % len(nightly)]
    np.savez(WORK / "dedup_sample_rows.npz", stock=stock_rows.astype(np.int32), day=day_rows.astype(np.int32))
    names = [s["name"] for s in SPECS]
    index = {name: j for j, name in enumerate(names)}
    sample = np.lib.format.open_memmap(WORK / "dedup_sample.npy", mode="r+" if previous else "w+", dtype=np.float32, shape=(SAMPLE_SIZE, len(names)))
    if not previous:
        sample[:] = np.nan
    count = np.array(previous["finite_count"], np.int64) if previous else np.zeros(len(names), np.int64)
    positive = np.array(previous["nonzero_count"], np.int64) if previous else np.zeros(len(names), np.int64)
    if VERSION == 'v1.1' and not previous:
        old_work = GAP/'ie38_work'
        old_meta = json.loads((old_work/'dedup_sample.json').read_text())
        old_freeze = json.loads((GAP/'standard_indicators_v1_dedup.json').read_text())
        if not old_meta['complete'] or old_meta['library_sha256'] != old_freeze['library_sha256']:
            raise ValueError('v1 sample does not match its frozen provenance')
        with np.load(old_work/'dedup_sample_rows.npz') as old_rows:
            np.testing.assert_array_equal(stock_rows, old_rows['stock'])
            np.testing.assert_array_equal(day_rows, old_rows['day'])
        old_sample = np.load(old_work/'dedup_sample.npy', mmap_mode='r')
        for k, spec in enumerate(SPECS):
            if spec['origin'] == 'legacy' or spec['name'] in REPAIRED_NEW_SERIES:
                continue
            old_k = old_meta['names'].index(spec['name'])
            sample[:, k] = old_sample[:, old_k]
            count[k], positive[k] = old_meta['finite_count'][old_k], old_meta['nonzero_count'][old_k]
        del old_sample
        log('reused unchanged v1 values on identical market sample; legacy values recomputed')
    meta = dict(complete=False, library_sha256=source_hash, seed=SEED, sample_size=SAMPLE_SIZE,
                stocks=len(files), nights=len(nightly), period=[days[nightly[0]], days[nightly[-1]]],
                universe_stock_nights=int(len(files)*len(nightly)), eligible_stock_nights=int(len(eligible)),
                sampling="uniform without replacement among market stock-nights with valid close", names=names,
                next_stock=previous.get("next_stock", 0) if previous else 0,
                next_night=previous.get("next_night", 0) if previous else 0)

    def save_progress():
        sample.flush()
        meta.update(finite_count=count.tolist(), nonzero_count=positive.tolist())
        temp = checkpoint.with_suffix(".json.tmp")
        temp.write_text(json.dumps(meta, ensure_ascii=False, indent=2)+"\n")
        temp.replace(checkpoint)

    save_progress()
    if workers == 2 and meta['next_stock'] < len(files):
        results = parallel_jobs('stocks', meta['next_stock'], len(files), source_hash)
        for result in results:
            count += np.array(result['finite_count'], np.int64)
            positive += np.array(result['nonzero_count'], np.int64)
        meta['next_stock'] = len(files)
        save_progress()
    q = np.load(SOURCE / "qqq.npy")
    # Only fitting-year history is passed; later years cannot affect the freeze.
    end = int(nightly[-1])+1
    for i, path in enumerate(files):
        if i < meta["next_stock"]:
            continue
        arrays, extras = load_stock(path, days)
        arrays = {key: value[:end] for key, value in arrays.items()}
        extras = {key: value[:end] for key, value in extras.items()}
        values = stock_sample_values(arrays, q[:end], extras)
        slots = np.flatnonzero(stock_rows == i)
        for name, x in values.items():
            k = index[name]
            sample[slots, k] = x[day_rows[slots]]
            value = x[nightly]
            count[k] += np.isfinite(value).sum()
            positive[k] += np.sum(np.isfinite(value) & (value != 0))
        if i % 100 == 0:
            meta["next_stock"] = i+1
            save_progress()
            log("single-stock", i, len(files), capacity("per_stock"))
    meta["next_stock"] = len(files)
    save_progress()
    # Sampling 300k rows leaves only about 600 requested stocks per evening.
    if workers == 2 and meta['next_night'] < len(nightly):
        parallel_jobs('nights', meta['next_night'], len(nightly), source_hash)
        meta['next_night'] = len(nightly)
        save_progress()
    for j, t in enumerate(nightly):
        if j < meta["next_night"]:
            continue
        slots = np.flatnonzero(day_rows == t)
        wanted = stock_rows[slots]
        a = max(0, t-252)
        values = cross_sample_values(close[:, a:t+1], high[:, a:t+1], low[:, a:t+1], wanted)
        for name, value in values.items():
            sample[slots, index[name]] = value
        if j % 50 == 0:
            meta["next_night"] = j+1
            save_progress()
            log("market cross-section", j, len(nightly), capacity("cross_section"))
    meta.update(complete=True, next_night=len(nightly), resources=capacity("sample_complete"))
    save_progress()
    return sample, meta


def ranks(x):
    """Average ranks, including ties; callers pass only finite observations."""
    order = np.argsort(x, kind="stable")
    starts = np.r_[0, np.flatnonzero(np.diff(x[order]) != 0)+1]
    stops = np.r_[starts[1:], len(x)]
    out = np.empty(len(x), float)
    out[order] = np.repeat((starts+stops-1)/2, stops-starts)
    return out


def pair_correlations(sample, start=0, stop=None, progress=None, initial=None, changed_indices=None):
    """Exact pairwise-complete Spearman; bounded LRU avoids an unbounded rank cache."""
    cache = OrderedDict()
    masks = [np.isfinite(sample[:, k]) for k in range(sample.shape[1])]
    hashes = [hashlib.sha256(np.packbits(mask).tobytes()).digest() for mask in masks]

    def ranked(k, mask, signature):
        key = (k, signature)
        if key not in cache:
            value = ranks(sample[mask, k])
            value -= value.mean()
            sd = np.linalg.norm(value)
            cache[key] = value/sd if sd > 0 else np.zeros_like(value)
            if len(cache) > 128:
                cache.popitem(last=False)
        cache.move_to_end(key)
        return cache[key]

    pairs = list(initial or [])
    for i in range(start, sample.shape[1] if stop is None else stop):
        for j in range(i+1, sample.shape[1]):
            if changed_indices is not None and not ({i, j} & changed_indices):
                continue
            mask = masks[i] & masks[j]
            n = int(mask.sum())
            if n < 3:
                continue
            signature = hashes[i] if hashes[i] == hashes[j] else hashlib.sha256(np.packbits(mask).tobytes()).digest()
            a, b = ranked(i, mask, signature), ranked(j, mask, signature)
            rho = float(a @ b)
            if abs(rho) >= .8:
                pairs.append(dict(left=SPECS[i]["name"], right=SPECS[j]["name"], rho=rho, common_sample=n))
        if i % 10 == 0:
            log("pairwise ranks", i, len(SPECS), "pairs>=.8", len(pairs), capacity("correlations"))
        if progress is not None:
            progress(i+1, pairs)
    return pairs


TRADINGVIEW_NAMES = frozenset((
    'rsi14', 'rsi2', 'stochastic_k', 'stochastic_rsi', 'macd_hist_pct', 'macd_hist_change5',
    'bollinger_percent_b', 'bollinger_width_percentile252', 'cci20', 'adx14', 'di_spread14',
    'supertrend_distance', 'supertrend_flip_days', 'ichimoku_cloud_position', 'cmf20', 'mfi14',
    'obv_high20_distance', 'donchian20_position', 'breakout55',
    'volume_profile_poc_distance_adr', 'volume_profile_value_position', 'weekly_pivot_position',
    'weekly_rsi14', 'weekly_macd_hist_pct'))


def retention_order(specs, version):
    if version == 'v1':
        return list(range(len(specs)))
    return sorted(range(len(specs)), key=lambda i: (
        0 if specs[i]['origin'] == 'legacy' else 1 if specs[i]['name'] in TRADINGVIEW_NAMES else 2, i))


def legacy_coverage(retained, pairs):
    pair_index = {frozenset((p['left'], p['right'])): p for p in pairs}
    rows = []
    for name in lib.LEGACY_NAMES:
        if name in retained:
            row = dict(name=name, retained=name, original=True, rho=1.)
            if name == 'price':
                row.update(definition_changed=True, reason='v1.1 uses raw_c instead of future-adjusted c')
            rows.append(row)
            continue
        alternatives = [(other, pair_index.get(frozenset((name, other)))) for other in retained]
        match = next(((other, pair) for other, pair in alternatives if pair and abs(pair['rho']) >= .9), None)
        if match is None:
            raise ValueError('legacy indicator is not represented: '+name)
        other, pair = match
        rows.append(dict(name=name, retained=other, original=False, rho=pair['rho']))
    return rows


def freeze(workers=1, *, refreeze=False):
    WORK.mkdir(exist_ok=True)
    heading = '\n## '+('八、v1.1' if VERSION == 'v1.1' else '七、v1')+' 冻结清单与合并记录\n'
    text = SPECIFICATION.read_text()
    previous = None
    if refreeze:
        backup = OUTPUT.with_name(OUTPUT.stem+'_pre_rawprice.json')
        if VERSION != 'v1.1' or not OUTPUT.exists() or not backup.exists() or heading not in text:
            raise RuntimeError('refreeze requires v1.1 and its pre_rawprice backup')
        if hashlib.sha256(OUTPUT.read_bytes()).digest() != hashlib.sha256(backup.read_bytes()).digest():
            raise RuntimeError('current freeze differs from backup; refuse another overwrite')
        previous = json.loads(backup.read_text())
        text = text.split(heading)[0]
    elif OUTPUT.exists() or heading in text:
        raise RuntimeError(VERSION+" already frozen; do not overwrite its record")
    capacity("start")
    sample, meta = sample_values(workers)
    changed_names = []
    if refreeze:
        old_work = WORK/'pre_rawprice'
        old_meta = json.loads((old_work/'dedup_sample.json').read_text())
        if old_meta['library_sha256'] != previous['library_sha256'] or old_meta['names'] != meta['names']:
            raise ValueError('prior sample does not match the backed-up freeze')
        with np.load(old_work/'dedup_sample_rows.npz') as old_rows, np.load(WORK/'dedup_sample_rows.npz') as new_rows:
            for key in ('stock', 'day'):
                np.testing.assert_array_equal(old_rows[key], new_rows[key])
        old_sample = np.load(old_work/'dedup_sample.npy', mmap_mode='r')
        changed = {i for i in range(sample.shape[1]) if not np.array_equal(
            sample[:, i].view(np.uint32), old_sample[:, i].view(np.uint32))}
        del old_sample
        changed_names = [SPECS[i]['name'] for i in sorted(changed)]
        untouched = [pair for pair in previous['pairs_abs_rho_at_least_0_8']
                     if pair['left'] not in changed_names and pair['right'] not in changed_names]
        log('refreeze changed sample columns', changed_names)
        pairs = untouched+pair_correlations(sample, changed_indices=changed)
        order = {spec['name']: i for i, spec in enumerate(SPECS)}
        pairs.sort(key=lambda pair: (order[pair['left']], order[pair['right']]))
    elif workers == 2:
        results = parallel_jobs('pairs', 0, len(SPECS), meta['library_sha256'])
        pairs = [pair for result in results for pair in result['pairs']]
    else:
        pairs = pair_correlations(sample)
    rates, dropped, retained = {}, [], []
    pair_index = {frozenset((p["left"], p["right"])): p for p in pairs}
    for i in retention_order(SPECS, VERSION):
        spec = SPECS[i]
        name = spec["name"]
        count, positive = meta["finite_count"][i], meta["nonzero_count"][i]
        rates[name] = dict(finite_stock_nights=count if spec["layer"] == "per_stock" else None,
                           nonzero_stock_nights=positive if spec["layer"] == "per_stock" else None,
                           full_market_occurrence=positive/count if count else None,
                           sample_finite=int(np.isfinite(sample[:, i]).sum()),
                           sample_occurrence=float(np.mean(sample[np.isfinite(sample[:, i]), i] != 0)) if np.isfinite(sample[:, i]).any() else None,
                           binary=spec["binary"])
        if spec["binary"] and count and positive/count < .01 and spec.get('origin') != 'legacy':
            dropped.append(dict(name=name, reason="binary_occurrence_below_1pct", occurrence=positive/count))
            continue
        similar = next((keep for keep in retained if frozenset((name, keep)) in pair_index
                        and abs(pair_index[frozenset((name, keep))]["rho"]) >= .9), None)
        if similar:
            pair = pair_index[frozenset((name, similar))]
            dropped.append(dict(name=name, reason="absolute_spearman_at_least_0.9", retained=similar, rho=pair["rho"]))
        else:
            retained.append(name)
    result = dict(version="std_"+VERSION.replace('.', '_'), **meta, pairs_abs_rho_at_least_0_8=pairs, occurrence=rates,
                  dropped=dropped, retained=retained,
                  priority="SPEC family order, then within-family row order; greedy retain and remove later neighbors",
                  correlation="exact pairwise-complete average-tie Spearman; constants have rho=0",
                  aliases_caveat="CMO alias is exact only with the same Wilder smoothing as RSI; rolling-sum CMO is not algebraically identical",
                  freeze_resources=capacity("freeze"))
    if VERSION == 'v1.1':
        result['priority'] = 'legacy first; then added TradingView built-ins; then other additions; SPEC order within each tier'
        result['legacy_coverage'] = legacy_coverage(retained, pairs)
        result['unchanged_v1_sample_reused'] = True
        if refreeze:
            result['rawprice_repair'] = dict(
                backup=backup.name, backup_sha256=hashlib.sha256(backup.read_bytes()).hexdigest(),
                price='raw_c; missing stays NaN; old adjusted price is exempt from legacy equality',
                changed_sample_columns=changed_names, unchanged_columns_verified_bitwise=True,
                correlation_reuse='only pairs whose two sample columns are bitwise unchanged')
    result['parallel_resources'] = {kind: json.loads((WORK/f'parallel_{kind}_resources.json').read_text())
                                    for kind in ('stocks', 'nights', 'pairs')
                                    if (WORK/f'parallel_{kind}_resources.json').exists()}
    _save_json(OUTPUT, result)
    path = Path(lib.__file__)
    source = path.read_text()
    constant = 'V1_1_NAMES' if VERSION == 'v1.1' else 'V1_NAMES'
    start = source.index(constant+" = ")
    end = source.index("\n\n", start)
    literal = constant+" = (\n"+"".join(f'    "{name}",\n' for name in retained)+")"
    path.write_text(source[:start]+literal+source[end:])
    lines = [heading, f"\n{len(SPECS)} 项代表全部实现；在 2277 只缓存股票、{meta['period'][0]} 至 {meta['period'][1]} 的全市场有效收盘股票 × 夜晚中，固定种子 {SEED} 不放回抽取 300,000 行，只使用指标值。最终保留 **{len(retained)} 项**。\n",
             "\n相关性用两项都有值的抽样行，计算含并列值平均秩的精确 Spearman；按上表流派顺序及流派内列出顺序，保留先列者。0/1 出现率在全部市场拟合年有效指标行上计算。缺少期权、财报或 4 小时输入的行保留 NaN。\n",
             "\n| 去掉的项 | 保留的项 / 原因 | ρ / 出现率 |\n|---|---|---|\n"]
    for row in dropped:
        if "retained" in row:
            lines.append(f"| `{row['name']}` | `{row['retained']}` | {row['rho']:.6f} |\n")
        else:
            lines.append(f"| `{row['name']}` | 全市场出现率低于 1% | {row['occurrence']:.4%} |\n")
    if VERSION == 'v1.1':
        lines[2] = '\n秩相关与 v1 使用完全相同的 300,000 个全市场抽样行，按两项共同有效行计算精确 Spearman（并列值取平均秩）；不使用交易标签。旧库优先；新增项先保留 TradingView 内置指标，再按规格表内顺序。旧库的 0/1 项不受低于 1% 的剔除规则影响。未变的新项复用 v1 同行冻结值，旧库项及修复数值稳定性的新增项重新计算。\n'
        if refreeze:
            lines.append('\n复核修复：旧缓存 `price` 使用复权收盘 `c`，含未来拆合股信息；v1.1 起使用 t 日真实未复权收盘 `raw_c`，缺失记 NaN，不回退到 `c`。旧库一致性对 `price` 豁免，并另与缓存 `raw_c` 逐行核对，其余 44 项继续按原标准核对。EMA 恒值更新、NR7 等振幅、布林带宽分位并列、成交量分布等量并列与筹码分位点使用稳定处理，避免缩放引发浮点分支变化。\n')
            lines.append(f"\n原冻结记录已另存 `{backup.name}`，SHA256 `{result['rawprice_repair']['backup_sha256']}`。按原抽样、保留顺序和 |ρ| ≥ 0.9 规则重新冻结；仅两个抽样列均逐位未变的相关对复用原值。\n")
        coverage = result['legacy_coverage']
        lines.append(f"\n旧库 45 项全部被包含：同名直接保留 {sum(row['original'] for row in coverage)} 项（`price` 已作上述安全修正），靠 |ρ| ≥ 0.9 的保留项替代 {sum(not row['original'] for row in coverage)} 项；同义新名已并入旧名。`ema_stack` 按旧库取 0–2；旧窗口的最少样本数、缺失比较、跳空锚点和封顶值保持不变。题材旧定义在调用者的当晚可见范围计算；本次去重范围为全市场，Martin 一致性核对使用原范围。\n")
        lines.append('\n| 旧库合并项 | 保留的替身 | ρ |\n|---|---|---|\n')
        for row in coverage:
            if not row['original']:
                lines.append(f"| `{row['name']}` | `{row['retained']}` | {row['rho']:.6f} |\n")
    lines.append(f"\n完整保留清单（代码常量 `standard_indicators.{constant}`）：\n\n"+"、".join(f"`{name}`" for name in retained)+"。\n")
    lines.append(f"\n完整的 |ρ| ≥ 0.8 成对及出现率见 `studies/trader_replication/reports/gap_review/{OUTPUT.name}`。CMO 与 RSI 的别名恒等使用相同 Wilder 平滑；滚动求和版 CMO 不满足恒等，本版不把两者数值混称。筹码采用日线成交量换手代理，并非真实逐笔持仓。\n")
    SPECIFICATION.write_text(text+"".join(lines))
    log("frozen", len(retained), "dropped", len(dropped), capacity("done"))


def legacy_pool_matrix(codes, row_day, days, scopes):
    """Recompute all 45 earlier columns; the caller supplies observable scan scopes."""
    if VERSION != 'v1.1':
        raise ValueError('legacy verification belongs to v1.1')
    WORK.mkdir(exist_ok=True)
    path = WORK/'pool_legacy.npz'
    signature = hashlib.sha256(json.dumps([library_hash(), list(codes), list(map(int, row_day)), scopes],
                                        separators=(',', ':'), sort_keys=True).encode()).hexdigest()
    if path.exists():
        with np.load(path) as z:
            if str(z['signature']) != signature:
                raise ValueError('legacy verification cache source or scope changed')
            return list(z['names']), z['x']
    names = list(lib.LEGACY_NAMES)
    x = np.full((len(names), len(codes)), np.nan, np.float32)
    index = {name: j for j, name in enumerate(names)}
    q = np.load(SOURCE/'qqq.npy')
    codes_array = np.asarray(codes)
    for k, code in enumerate(dict.fromkeys(codes)):
        rows = np.flatnonzero(codes_array == code)
        arrays, extras = load_stock(SOURCE/'stocks'/(code+'.npz'), days)
        for name, values in lib.legacy_per_stock(arrays, q, extras).items():
            x[index[name], rows] = values[row_day[rows]]
        if k % 100 == 0:
            log('legacy pool single-stock', k, capacity('legacy_series'))
    files, _, (close, _, _) = market_panel()
    market_index = {p.stem: j for j, p in enumerate(files)}
    for k, t in enumerate(np.unique(row_day)):
        rows = np.flatnonzero(row_day == t)
        scope = [code for code in scopes[days[t]] if code in market_index]
        scope_index = {code: j for j, code in enumerate(scope)}
        if any(codes[r] not in scope_index for r in rows):
            raise ValueError('pool row not in its observable scope')
        selected = np.array([market_index[code] for code in scope], int)
        wanted = np.array([scope_index[codes[r]] for r in rows], int)
        values = lib.legacy_cross_section(close[selected, max(0, t-60):t+1], wanted)
        for name, values_ in values.items():
            x[index[name], rows] = values_
        if k % 100 == 0:
            log('legacy pool scope', k, capacity('legacy_peers'))
    temporary = path.with_name(path.stem+'.tmp.npz')
    np.savez(temporary, names=names, x=x, signature=signature)
    temporary.replace(path)
    return names, x


def verify_legacy():
    """Reconstruct scan rows from cached scopes and gates, without loading entry labels."""
    configure_version('v1.1')
    gates = json.loads((GAP/'strong_continue_ie8_frozen_gates.json').read_text())['final']['scheme']['gates']
    metadata = json.loads((SOURCE/'prepared.json').read_text())
    scopes, days = metadata['scope'], metadata['days']
    first, last = metadata['first_signal'], metadata['prepared_last']
    del metadata
    gate_names = json.loads((GAP/'strong_continue_ie4_frozen.json').read_text())['raw_feature_names']
    percentiles = np.load(GAP/'ie7_work/full_pct.npy', mmap_mode='r')
    codes, row_day, offset = [], [], 0
    day_index = {day: j for j, day in enumerate(days)}
    for day, scope in sorted(scopes.items()):
        width = len(scope)
        if first <= day <= last:
            values = percentiles[offset:offset+width]
            passed = np.ones(width, bool)
            for gate in gates:
                column = values[:, gate_names.index(gate['name'])]
                passed &= np.where(np.isfinite(column), column >= gate['cutoff'], gate['name'] == 'h4_history')
            kept = [code for code, keep in zip(scope, passed) if keep]
            codes.extend(kept)
            row_day.extend([day_index[day]]*len(kept))
        offset += width
    row_day = np.asarray(row_day)
    names, computed = legacy_pool_matrix(codes, row_day, days, scopes)
    np.savez(WORK/'legacy_rows.npz', codes=np.asarray(codes), day=row_day)
    with np.load(GAP/'ie29_work/indicators_h4nan_v2.npz') as z:
        old_names, old = list(z['names']), z['x']
    expected_names = [name for name in old_names if name not in ('listed_days', 'theme_peers_pool', 'theme_rank_rs21')]
    if set(expected_names) != set(names) or len(names) != 45 or old.shape[1] != len(codes):
        raise ValueError('earlier library names or pool rows differ')
    details = []
    for j, name in enumerate(names):
        actual, expected = computed[j], old[old_names.index(name)]
        mask_equal = bool(np.array_equal(np.isnan(actual), np.isnan(expected)))
        finite = np.isfinite(actual) & np.isfinite(expected)
        difference = float(np.max(abs(actual[finite].astype(float)-expected[finite].astype(float)))) if finite.any() else 0.
        exempt = name == 'price'
        details.append(dict(name=name, rows=len(actual), finite=int(finite.sum()), nan_mask_equal=mask_equal,
                            max_abs_difference=difference, exempt=exempt,
                            exemption='Old adjusted c contains future split information; v1.1 price uses raw_c.' if exempt else None,
                            passed=exempt or (mask_equal and difference <= 1e-6)))
    expected_price = np.full(len(codes), np.nan)
    code_array = np.asarray(codes)
    for code in dict.fromkeys(codes):
        rows = np.flatnonzero(code_array == code)
        with np.load(SOURCE/'stocks'/(code+'.npz')) as z:
            if 'raw_c' in z.files:
                expected_price[rows] = z['raw_c'][row_day[rows]]
    np.testing.assert_allclose(computed[names.index('price')], expected_price, rtol=0, atol=1e-9, equal_nan=True)
    result = dict(indicators=len(details), pool_rows=len(codes), passed=all(row['passed'] for row in details),
                  compared_indicators=44, exempt_indicators=['price'], price_matches_raw_c=True,
                  details=details, library_sha256=library_hash(), resources=capacity('legacy_verified'))
    _save_json(WORK/'legacy_consistency.json', result)
    log('legacy consistency', result['passed'], 'failed', [row for row in details if not row['passed']])
    if not result['passed']:
        raise ValueError('legacy consistency failed; original cache is read-only')
    return result


def pool_matrix(codes, row_day, days, *, own_scan=False, pool_counts=None):
    """Causal v1 values on a caller's scan rows; market peers stay market-wide."""
    WORK.mkdir(exist_ok=True)
    suffix = "own" if own_scan else "standard"
    path = WORK / f"pool_{suffix}.npz"
    names = list(lib.V1_NAMES)+(["pool_nights_20", "theme_peers_pool"] if own_scan else [])
    source_hash = hashlib.sha256(Path(lib.__file__).read_bytes()).hexdigest()
    signature = hashlib.sha256(json.dumps([source_hash, names, list(codes), list(map(int, row_day))], separators=(",", ":")).encode()).hexdigest()
    if path.exists():
        with np.load(path) as z:
            if str(z["signature"]) != signature:
                frozen = json.loads((WORK/'h2_fit.json').read_text())
                old_hash = frozen['fingerprints']['studies/trader_replication/standard_indicators.py']
                old_signature = hashlib.sha256(json.dumps([old_hash, names, list(codes), list(map(int, row_day))],
                                                          separators=(',', ':')).encode()).hexdigest()
                if str(z['signature']) != old_signature or names[:len(lib.V1_NAMES)] != list(lib.V1_NAMES):
                    raise ValueError("pool cache row order or indicator freeze changed")
            return list(z["names"]), z["x"]
    if own_scan:
        if pool_counts is None:
            raise ValueError("own scan requires causal pool_nights_20 counts")
        _, base = pool_matrix(codes, row_day, days, own_scan=False)
        with np.load(WORK / "pool_standard.npz") as z:
            peers = z["own_peers"]
        x = np.vstack((base, np.asarray(pool_counts, np.float32)[None], peers[None]))
        temporary = path.with_name(path.stem+'.tmp.npz')
        np.savez(temporary, names=names, x=x, signature=signature)
        temporary.replace(path)
        capacity("own_scan_cached")
        return names, x
    files, calendar, (close, high, low) = market_panel()
    code_index = {p.stem: i for i, p in enumerate(files)}
    market_rows = np.array([code_index[c] for c in codes], int)
    index = {name: k for k, name in enumerate(names)}
    x = np.full((len(names), len(codes)), np.nan, np.float32)
    own_peers = np.full(len(codes), np.nan, np.float32)
    q = np.load(SOURCE / "qqq.npy")
    for k, code in enumerate(dict.fromkeys(codes)):
        rows = np.flatnonzero(np.asarray(codes) == code)
        arrays, extras = load_stock(SOURCE / "stocks" / (code+".npz"), calendar)
        values = lib.per_stock(arrays, q, extras, version='v1')
        for name in lib.V1_PER_STOCK_NAMES:
            if name in index:
                x[index[name], rows] = values[name][row_day[rows]]
        if k % 100 == 0:
            log("pool single-stock", k, capacity("pool_series"))
    for j, t in enumerate(np.unique(row_day)):
        rows = np.flatnonzero(row_day == t)
        mask = np.zeros(len(files), bool)
        mask[market_rows[rows]] = True
        start = max(0, t-252)
        values = lib.cross_section(close[:, start:t+1], high[:, start:t+1], low[:, start:t+1],
                                   market_rows[rows], pool_mask=mask, version='v1')
        own_peers[rows] = values["theme_peers_pool"]
        for name, values_ in values.items():
            if name in index:
                x[index[name], rows] = values_
        if j % 100 == 0:
            log("pool market peers", j, capacity("pool_cross_section"))
    temporary = path.with_name(path.stem+'.tmp.npz')
    np.savez(temporary, names=names, x=x, signature=signature, own_peers=own_peers)
    temporary.replace(path)
    capacity("pool_cached")
    return names, x


def verify_parallel():
    """Recompute deterministic boundary cases serially, without any trader labels."""
    meta = json.loads((WORK/'dedup_sample.json').read_text())
    if not meta['complete']:
        raise ValueError('sample is incomplete')
    sample = np.load(WORK/'dedup_sample.npy', mmap_mode='r')
    with np.load(WORK/'dedup_sample_rows.npz') as z:
        stock_rows, day_rows = z['stock'], z['day']
    files, days, (close, high, low) = market_panel()
    nightly = np.array([i for i, day in enumerate(days) if '2024-01-01' <= day <= '2025-12-31'])
    eligible = np.flatnonzero((np.isfinite(close[:, nightly]) & (close[:, nightly] > 0)).ravel())
    chosen = np.random.default_rng(SEED).choice(eligible, SAMPLE_SIZE, replace=False)
    np.testing.assert_array_equal(stock_rows, chosen//len(nightly))
    np.testing.assert_array_equal(day_rows, nightly[chosen % len(nightly)])
    index = {s['name']: k for k, s in enumerate(SPECS)}
    series_names = [s['name'] for s in SPECS if s['layer'] == 'per_stock']
    cross_names = [s['name'] for s in SPECS if s['layer'] == 'cross_section']
    series_columns = [index[name] for name in series_names]
    cross_columns = [index[name] for name in cross_names]
    stocks = {0, len(files)//2}
    resource_path = WORK/'parallel_stocks_resources.json'
    if resource_path.exists():
        for start, stop in json.loads(resource_path.read_text())['ranges']:
            stocks.update((start, stop-1))
    q = np.load(SOURCE/'qqq.npy')
    end = int(nightly[-1])+1
    checked = 0
    for i in sorted(stocks):
        slots = np.flatnonzero(stock_rows == i)
        arrays, extras = load_stock(files[i], days)
        values = lib.per_stock({k: v[:end] for k, v in arrays.items()}, q[:end],
                               {k: v[:end] for k, v in extras.items()}, version=VERSION)
        expected = np.column_stack([values[name][day_rows[slots]] for name in series_names]).astype(np.float32)
        actual = np.asarray(sample[np.ix_(slots, series_columns)])
        np.testing.assert_array_equal(actual.view(np.uint32), expected.view(np.uint32))
        checked += actual.size
    nights = [0, len(nightly)//2, len(nightly)-1]
    for j in nights:
        t = nightly[j]
        slots = np.flatnonzero(day_rows == t)
        start = max(0, t-252)
        values = lib.cross_section(close[:, start:t+1].astype(np.float32), high[:, start:t+1].astype(np.float32),
                                   low[:, start:t+1].astype(np.float32), stock_rows[slots], version='v1')
        if VERSION == 'v1.1':
            values.update(lib.legacy_cross_section(close[:, start:t+1], stock_rows[slots]))
        expected = np.column_stack([values[name] for name in cross_names]).astype(np.float32)
        actual = np.asarray(sample[np.ix_(slots, cross_columns)])
        np.testing.assert_array_equal(actual.view(np.uint32), expected.view(np.uint32))
        checked += actual.size
    frozen = json.loads(OUTPUT.read_text())
    stored = {(pair['left'], pair['right']): pair for pair in frozen['pairs_abs_rho_at_least_0_8']}
    pairs = [(0, 1), (0, 26), (26, 27), (36, 37), (37, 38), (63, 126), (0, 126)]
    for i, j in pairs:
        valid = np.isfinite(sample[:, i]) & np.isfinite(sample[:, j])
        a, b = ranks(sample[valid, i]), ranks(sample[valid, j])
        a -= a.mean()
        b -= b.mean()
        aa, bb = np.linalg.norm(a), np.linalg.norm(b)
        rho = float((a/aa if aa else np.zeros_like(a)) @ (b/bb if bb else np.zeros_like(b)))
        key = (SPECS[i]['name'], SPECS[j]['name'])
        if abs(rho) >= .8:
            assert stored[key]['rho'] == rho, key
        else:
            assert key not in stored, key
    _save_json(WORK/'parallel_consistency.json', dict(
        sampling_identical=True, sample_seed=SEED, sample_size=SAMPLE_SIZE,
        serial_stock_indices=sorted(stocks), serial_night_indices=nights,
        bitwise_float32_cells_checked=checked, bitwise_equal=True,
        exact_float64_rank_pairs_checked=pairs, rank_pairs_equal=True,
        merge_order='fixed ascending stock ranges and indicator-pair ranges; integer counters only',
        resources=capacity('parallel_verified')))
    log('parallel consistency verified', checked, 'bitwise cells', len(pairs), 'exact correlations')


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--version', choices=('v1', 'v1.1'), default='v1')
    parser.add_argument('--workers', type=int, choices=(1, 2), default=1)
    parser.add_argument('--verify-parallel', action='store_true')
    parser.add_argument('--verify-legacy', action='store_true')
    parser.add_argument('--refreeze', action='store_true', help='v1.1 raw-price repair; requires matching pre_rawprice backup')
    arguments = parser.parse_args()
    configure_version(arguments.version)
    if arguments.verify_legacy:
        verify_legacy()
    elif arguments.verify_parallel:
        verify_parallel()
    else:
        freeze(arguments.workers, refreeze=arguments.refreeze)
