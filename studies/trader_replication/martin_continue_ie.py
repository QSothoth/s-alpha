"""IE stage two: replay H4 timelines and four preregistered reference frames.

Offline diagnosis only. No training, new factors, accounts, or cache writes.
"""
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
import gc
from itertools import groupby
import json
import os
from pathlib import Path
import resource
from statistics import median
import sys
from types import SimpleNamespace
import warnings

import numpy as np

from studies import trader_data
from studies.trader_replication import martin_continue_du as du
from studies.trader_replication import martin_continue_ep as ep
from studies.trader_replication import martin_continue_hj as hj
from studies.trader_replication import martin_continue_ia as ia
from studies.trader_replication.martin_continue_bv import daily_name_score, daily_pool_book
from studies.trader_replication.martin_continue_cr import json_default
from studies.trader_replication.martin_continue_ie_periods import distribution, file_sha
from studies.trader_replication.martin_list import ema
from studies.trader_replication.martin_strong import pct
from studies.trader_replication.martin_strong_scan import HOLD, hold_sim, merge, sized
from studies.trend_breakout.panel import factors

ROOT = Path(__file__).resolve().parents[2]
REPORTS = ROOT / 'studies/trader_replication/reports/gap_review'
PERIODS = REPORTS / 'strong_continue_ie_periods.json'
TIMELINE = REPORTS / 'strong_continue_ie_timeline.json'
FRAMES = REPORTS / 'strong_continue_ie_frames.json'
PREREG = ROOT / 'studies/martin_luk/notes/PREREG_STRONG.md'
FRAME_IDS = ('potent_day', 'leader_weekend', 'premier_ema_leader', 'premier_liquidity')
TOPS = (1, 3, 5, 10)
GROUPS = tuple('+'.join(g) for g in HOLD['H4'])
CATEGORIES = ('全程没进 active', '进 active 没进名单', '进名单但晚于他', '进过又被挤出',
              '在名单但形态不合格', '形态合格但前六没选上', '已跟上')


def number(value):
    return float(value) if np.isfinite(value) else None


def entry_nights(entry_index):
    """Prior evening and three earlier evenings; never include entry day."""
    return list(range(max(0, entry_index - 4), entry_index))


def ranks(values, mask, codes=None):
    eligible = np.flatnonzero(mask & np.isfinite(values))
    if codes is None:
        full_order = np.argsort(-np.nan_to_num(values, nan=-1e9))
        order = full_order[mask[full_order] & np.isfinite(values[full_order])]
    else:
        order = eligible[np.lexsort((np.asarray(codes)[eligible], -values[eligible]))]
    result = np.zeros(len(values), np.int32)
    result[order] = np.arange(1, len(order) + 1)
    return result, order


def group_percentiles(fields, mask, day):
    """Match the existing score's lag, ordinal ties and missing-neutral rule."""
    out = np.zeros((len(HOLD['H4']), mask.shape[1]), np.float32)
    for i, group in enumerate(HOLD['H4']):
        for key in group:
            value = fields[key][day - 1:day] if day else np.full((1, mask.shape[1]), np.nan, np.float32)
            out[i] += np.nan_to_num(pct(value, mask[day:day + 1])[0] - .5) / len(group)
    return out + .5


def forward_outcome(close, high, start, horizon):
    """Evaluation only; exclude the entry day's high."""
    future = np.asarray(high[start + 1:start + horizon + 1])
    valid = np.flatnonzero(np.isfinite(future) & (future > 0))
    base = close[start]
    if not np.isfinite(base) or base <= 0 or not len(valid):
        return dict(gain=None, observed_bars=len(valid), complete=False, peak_index=None)
    peak = int(valid[np.argmax(future[valid])])
    return dict(gain=float(future[peak]) / float(base) - 1, observed_bars=len(valid),
                complete=len(future) == horizon and len(valid) == horizon, peak_index=start + 1 + peak)


def target_label(close, high, start):
    result = forward_outcome(close, high, start, 60)
    primary = result['gain'] is not None and result['gain'] >= .3
    return dict(result, tier='primary' if primary else 'secondary', censored=not result['complete'],
                provisional=not primary and not result['complete'])


def completed_week(days, evening):
    weeks = [date.fromisoformat(d).isocalendar()[:2] for d in days]
    ends = [i for i in range(evening + 1)
            if ((i + 1 < len(days) and weeks[i + 1] != weeks[i]) or
                (i + 1 == len(days) and date.fromisoformat(days[i]).weekday() == 4))]
    if not ends:
        return None, None
    end = start = ends[-1]
    while start and weeks[start - 1] == weeks[end]:
        start -= 1
    return start, end


def reference_snapshot(data, evening):
    """All price and volume reads stop at evening; calendar dates contain no prices."""
    if data.days[evening] > '2025-12-31':
        raise ValueError('2026 reference-frame computation is forbidden')
    c = np.asarray(data.c[:evening + 1], dtype=float)
    turnover = np.asarray(data.t[:evening + 1], dtype=float)
    volume = np.asarray(data.volume[:evening + 1], dtype=float)
    raw_v5 = np.asarray(data.raw_v5[:evening + 1], dtype=float)
    current = c[-1]
    valid = np.isfinite(current) & (current > 0)
    with np.errstate(all='ignore'):
        g1 = current / c[-2] - 1 if len(c) >= 2 else np.full(len(current), np.nan)
        g21 = current / c[-22] - 1 if len(c) >= 22 else np.full(len(current), np.nan)
        m20 = turnover[-20:].mean(0) if len(c) >= 20 else np.full(len(current), np.nan)
    e9, e21, e50 = (ema(c, n)[-1].copy() for n in (9, 21, 50))
    stack = (e9 > e21) & (e21 > e50)
    week_start, week_end = completed_week(data.days, evening)
    weekly_dollar = np.full(len(current), np.nan)
    weekly_gain = np.full(len(current), np.nan)
    if week_end is not None and week_end >= 21:
        weekly_dollar = c[week_end] * volume[week_start:week_end + 1].sum(0)
        with np.errstate(all='ignore'):
            weekly_gain = c[week_end] / c[week_end - 21] - 1
    definitions = {
        'potent_day': (g1, {'valid_close': valid, 'turnover_ge_50m': turnover[-1] >= 5e7,
                            'weekly_volatility_proxy_ge_035': raw_v5[-1] >= .035, 'above_ema21': current > e21}),
        'leader_weekend': (weekly_gain, {'valid_close': valid, 'weekly_dollar_gt_300m': weekly_dollar > 3e8}),
        'premier_ema_leader': (g21, {'valid_close': valid, 'm20_ge_100m': m20 >= 1e8,
                                    'ema9_gt_ema21_gt_ema50': stack}),
        'premier_liquidity': (m20, {'valid_close': valid, 'm20_ge_100m': m20 >= 1e8}),
    }
    frames = {}
    for name, (value, conditions) in definitions.items():
        mask = np.isfinite(value)
        for condition in conditions.values():
            mask &= condition
        rank, order = ranks(value, mask, data.codes)
        frames[name] = dict(rank=rank, order=order, width=len(order), value=value, conditions=conditions)
    return dict(frames=frames, metrics=dict(g1=g1, g21=g21, m20=m20, raw_v5=raw_v5[-1],
                                           weekly_dollar=weekly_dollar, weekly_gain=weekly_gain),
                week_end=None if week_end is None else data.days[week_end])


def frame_event(snapshot, name, column, day):
    item = snapshot['frames'][name]
    reasons = [key for key, condition in item['conditions'].items() if not condition[column]]
    if not np.isfinite(item['value'][column]):
        reasons.append('missing_strength_input')
    return dict(date=day, rank=int(item['rank'][column]) or None, width=item['width'],
                strength=number(item['value'][column]), exclusion_reasons=reasons,
                week_end=snapshot['week_end'] if name == 'leader_weekend' else None,
                metrics={key: number(values[column]) for key, values in snapshot['metrics'].items()})


def random_probability(events, top, rank_key='rank', width_key='width'):
    miss = 1.
    for row in events:
        if row[rank_key] is not None and row[width_key]:
            miss *= 1 - min(top, row[width_key]) / row[width_key]
    return 1 - miss


def coverage(rows, name, rank_key='rank', width_key='width'):
    events = [r['systems'][name] for r in rows]
    best = [min((e[rank_key] for e in es if e[rank_key] is not None), default=None) for es in events]
    prior = [es[-1][rank_key] if es else None for es in events]
    result = dict(n=len(rows), in_scope_any=sum(x is not None for x in best),
                  best_rank_distribution=distribution([x for x in best if x is not None]),
                  prior_evening_rank_distribution=distribution([x for x in prior if x is not None]),
                  primary_censored=sum(r['target']['censored'] for r in rows if r['target']['tier'] == 'primary'),
                  secondary_provisional=sum(r['target']['provisional'] for r in rows), top={})
    for top in TOPS:
        hits = sum(x is not None and x <= top for x in best)
        expected = sum(random_probability(es, top, rank_key, width_key) for es in events)
        result['top'][str(top)] = dict(hits=hits, rate=hits / len(rows) if rows else None,
             random_expected_hits=expected, random_expected_rate=expected / len(rows) if rows else None,
             prior_evening_hits=sum(x is not None and x <= top for x in prior),
             prior_evening_random_expected_hits=sum(random_probability(es[-1:], top, rank_key, width_key) for es in events))
    return result


def year_sample(rows, year):
    return [r for r in rows if year == 'all' or (r['entry_date'][:4] in ('2024', '2025')
            if year == '2024_2025' else r['entry_date'].startswith(year))]


def coverage_strata(rows, names, rank_key='rank', width_key='width'):
    result = {}
    for year in ('2024_2025', '2026', '2024', '2025'):
        sample = year_sample(rows, year)
        if sample:
            result[year] = {tier: {name: coverage([r for r in sample if tier == 'all' or r['target']['tier'] == tier],
                                                name, rank_key, width_key) for name in names}
                            for tier in ('all', 'primary', 'secondary')}
    return result


def category(history, nights):
    if any(r['selected'] or r['core'] for r in nights):
        return CATEGORIES[6]
    if any(r['qualified'] for r in nights):
        return CATEGORIES[5]
    if any(r['held'] for r in nights):
        return CATEGORIES[4]
    first, last = nights[0]['date'], nights[-1]['date']
    if any(r['held'] and r['date'] < first for r in history):
        return CATEGORIES[3]
    if any(r['held'] and r['date'] > last for r in history):
        return CATEGORIES[2]
    return CATEGORIES[1] if any(r['active'] for r in history + nights) else CATEGORIES[0]


def group_summary(rows):
    values, gaps = {k: [] for k in GROUPS}, {k: [] for k in GROUPS}
    for row in rows:
        for event in row['systems']['h4']:
            if event['active']:
                for k in GROUPS:
                    values[k].append(event['group_percentiles'][k])
                    reference = event['held_group_median'][k]
                    if reference is not None:
                        gaps[k].append(event['group_percentiles'][k] - reference)
    centers = {k: median(v) if v else None for k, v in values.items()}
    available = [k for k in centers if centers[k] is not None]
    return dict(weakest_group=min(available, key=centers.get) if available else None, group_medians=centers,
                gap_to_same_evening_held={k: median(v) if v else None for k, v in gaps.items()})


def category_summary(rows):
    return {name: dict(n=len(sample), **group_summary(sample)) for name in CATEGORIES
            for sample in ([r for r in rows if r['category'] == name],)}


def classification_strata(rows):
    result = {}
    for year in ('all', '2024_2025', '2026', '2024', '2025'):
        result[year] = {}
        for tier in ('all', 'primary', 'secondary'):
            group = [r for r in year_sample(rows, year) if tier == 'all' or r['target']['tier'] == tier]
            result[year][tier] = dict(n=len(group), categories=category_summary(group),
                by_setup={key: category_summary([r for r in group if r['setup'] == key])
                          for key in sorted({r['setup'] for r in group})},
                by_period_gain={key: category_summary([r for r in group if r['gain_bucket'] == key])
                                for key in ('30_to_100', '100_to_300', 'ge_300')})
    return result


def reference_inputs(dataset, data):
    """Read one symbol at a time; retain only two bounded T x N input arrays."""
    volume = np.full(data.c.shape, np.nan, np.float32)
    raw_v5 = np.full(data.c.shape, np.nan, np.float32)
    columns = {code: j for j, code in enumerate(data.A['codes'])}
    actions = dataset.actions()
    for code, records in groupby(dataset.rows(), key=lambda r: r[0]):
        if code not in columns:
            continue
        rows = [(day, values) for _, day, values in records if day in data.di]
        days = [day for day, _ in rows]
        if not days:
            continue
        raw = np.asarray([values for _, values in rows], float)
        idx, j = [data.di[day] for day in days], columns[code]
        scale = factors(raw[:, 3], np.asarray(days), actions.get(code, []))
        volume[idx, j] = raw[:, 4] / scale
        ranges = np.full((len(data.days), 1), np.nan)
        ranges[idx, 0] = [ep.raw_ranges(values) for _, values in rows]
        known = np.isfinite(ranges[:, 0])
        count = np.convolve(known.astype(int), np.ones(5, int), mode='valid')
        total = np.convolve(np.nan_to_num(ranges[:, 0]), np.ones(5), mode='valid')
        raw_v5[4:, j] = np.where(count == 5, total / 5, np.nan)
    return volume, raw_v5


def build_h4(dataset, reference):
    d = du.make_data(dataset)
    print('H4 panel', d.c.shape, flush=True)
    fields, active, unused = du.compute_fields(d)
    del unused
    gc.collect()
    events, eligible, _ = ep.causal_inputs(dataset, d, list(map(str, d.A['codes'])))
    fast = np.empty(events.shape, np.float32)
    for start in range(0, events.shape[1], 64):
        sl = slice(start, start + 64)
        fast[:, sl] = du._ROLL_MEAN(events[:, sl].astype(np.float32), 250)
    fields['fast250'] = fast
    del events, fast
    fields['peer_pot'], unused = ep.peer_potential(d, eligible)
    del unused, eligible
    fields.update(hj.coil_fields_chunked(d))
    score = daily_name_score(fields, active, HOLD['H4'])
    held = hold_sim(score, 12, 36)
    book = merge(d.reg, sized(daily_pool_book(d, fields, held, score), .5))
    replay = ia.collect_funnel(d, active, held, book, reference['rows'])
    for label, count in (('2024_2025', 15), ('2026', 20)):
        if replay['summary'][label]['held'] != count:
            raise AssertionError('IA held baseline differs: ' + label)
    if replay['summary'] != reference['summary']:
        raise AssertionError('IA funnel summary differs')
    for a, b in zip(replay['rows'], reference['rows']):
        if a['id'] != b['id'] or a['upstream_days'] != b['upstream_days'] or a['reached'] != b['reached']:
            raise AssertionError('IA daily funnel differs: ' + a['id'])
    print('IA gate passed: 15/32, 20/51; all five daily states identical', flush=True)
    return d, fields, active, score, held, book, replay


def night_record(d, fields, active, held, score, book, day, wanted):
    rank, order = ranks(score[day], active[day])
    groups = group_percentiles(fields, active, day)
    if not np.allclose(score[day, active[day]], (groups[:, active[day]] - .5).sum(0), atol=1e-6):
        raise AssertionError('H4 group decomposition differs')
    held_centers = {k: number(np.median(groups[i, held[day]])) if held[day].any() else None
                    for i, k in enumerate(GROUPS)}
    trials = sorted((e for e in book[day] if e[2] > 0 and e[5] == 'list'), key=lambda e: e[0])
    trial_rank = {int(e[1]): i + 1 for i, e in enumerate(trials)}
    selected = {int(e[1]) for e in trials[:6]}
    core = {int(e[1]) for e in book[day] if e[2] > 0 and e[5] == 'n1'}
    result = {}
    for j in wanted:
        close, low = d.c[day, j], d.l[day, j]
        touch = fields['lowe9'][day, j] <= .1 and close > d.e9[day, j]
        breakout = day > 0 and close > d.h[day - 1, j] and fields['cpos'][day, j] >= .5
        extension = np.isfinite(fields['ext21'][day, j]) and fields['ext21'][day, j] <= 8
        valid_price = np.isfinite(close) and np.isfinite(low)
        qualified = bool(held[day, j] and (touch or breakout) and extension and valid_price)
        if qualified != (j in trial_rank):
            raise AssertionError('shape qualification differs')
        result[j] = dict(date=d.days[day], feature_date=d.days[day - 1] if day else None,
             active=bool(active[day, j]), rank=int(rank[j]) or None, width=len(order), score=number(score[day, j]),
             held=bool(held[day, j]), shape=bool(touch or breakout), extension_ok=bool(extension),
             valid_price=bool(valid_price), qualified=qualified, qualified_rank=trial_rank.get(j),
             qualified_width=len(trials), selected=j in selected, core=j in core,
             group_percentiles={k: number(groups[i, j]) if active[day, j] else None for i, k in enumerate(GROUPS)},
             held_group_median=held_centers, ahead_count=int(rank[j]) - 1 if rank[j] else None, close=number(close))
    stop = min(day + 20, len(d.days) - 1)
    future = d.h[day + 1:stop + 1, order]
    with warnings.catch_warnings(), np.errstate(all='ignore'):
        warnings.simplefilter('ignore', RuntimeWarning)
        gain = np.nanmax(future, axis=0) / d.c[day, order] - 1 if len(future) else np.full(len(order), np.nan)
        close_gain = d.c[stop, order] / d.c[day, order] - 1 if stop > day else np.full(len(order), np.nan)
    observations = np.isfinite(future).sum(0)
    candidates = [[str(d.A['codes'][j]), number(score[day, j]), number(g), number(cg), int(n)]
                  for j, g, cg, n in zip(order, gain, close_gain, observations)]
    return result, dict(active_width=len(order), held_width=int(held[day].sum()), qualified_width=len(trials),
        selected_width=len(selected), core_width=len(core), observed_market_sessions=stop - day,
        evaluation_end=d.days[stop], rows=candidates)


def first_seen(history, key, start_index, entry_index, di, start_close):
    row = next((r for r in history if r[key]), None)
    if row is None:
        return None
    return dict(date=row['date'], relative_to_start=di[row['date']] - start_index,
                relative_to_entry=di[row['date']] - entry_index,
                gain_from_start=row['close'] / start_close - 1 if row['close'] is not None else None,
                left_censored=row is history[0])


def active_control(d, active, entry_index):
    columns = np.flatnonzero(active[entry_index - 1])
    counts, gains = Counter(n=len(columns)), []
    stop = min(entry_index + 60, len(d.days) - 1)
    for j in columns:
        label = target_label(d.c[:, j], d.h[:, j], entry_index)
        counts[label['tier']] += 1
        counts['complete'] += int(label['complete'])
        counts['censored'] += int(label['censored'])
        if label['complete']:
            counts['complete_primary'] += int(label['tier'] == 'primary')
        if label['gain'] is not None:
            gains.append(label['gain'])
        before = d.c[max(0, entry_index - 60):entry_index, j]
        finite = np.flatnonzero(np.isfinite(before))
        if len(finite):
            start = max(0, entry_index - 60) + int(finite[np.argmin(before[finite])])
            future = d.h[start + 1:stop + 1, j]
            if np.isfinite(future).any():
                counts['stage1_label_available'] += 1
                counts['stage1_ge30'] += int(np.nanmax(future) / d.c[start, j] >= 1.3)
    return dict(counts=dict(counts), future60_gain=distribution(gains),
        primary_rate=counts['primary'] / len(columns) if len(columns) else None,
        complete_primary_rate=counts['complete_primary'] / counts['complete'] if counts['complete'] else None,
        stage1_ge30_rate=counts['stage1_ge30'] / counts['stage1_label_available'] if counts['stage1_label_available'] else None)


def control_summary(rows):
    out = {}
    for year in ('2024_2025', '2026'):
        sample = year_sample(rows, year)
        if not sample:
            continue
        out[year] = {}
        for tier in ('all', 'primary', 'secondary'):
            group = [r for r in sample if tier == 'all' or r['target']['tier'] == tier]
            out[year][tier] = dict(n=len(group),
                same_day_active_primary_rate_mean=float(np.mean([r['same_day_active']['primary_rate'] for r in group])) if group else None,
                same_day_active_stage1_ge30_rate_mean=float(np.mean([r['same_day_active']['stage1_ge30_rate'] for r in group])) if group else None,
                control_counts=dict(sum((Counter(r['same_day_active']['counts']) for r in group), Counter())))
    return out


def protect_outputs():
    allowed = {TIMELINE.resolve(), FRAMES.resolve()}

    def audit(event, args):
        if event == 'open':
            path, mode, flags = args
            writing = flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND)
            if writing and not isinstance(path, int) and Path(os.fsdecode(path)).resolve() not in allowed:
                raise PermissionError('IE permits writes only to its two new reports')
        if event in ('socket.connect', 'socket.bind', 'os.system', 'subprocess.Popen'):
            raise PermissionError('IE is offline and runs in one research process')
        if event in ('os.remove', 'os.rename', 'os.rmdir', 'os.mkdir'):
            raise PermissionError('IE may not mutate input files or directories')

    sys.addaudithook(audit)


def input_paths(dataset):
    source = [Path(__file__), Path(__file__).parent / 'tests/test_martin_continue_ie.py', PREREG,
        ROOT / 'studies/martin_luk/notes/PLAN_IE_CN.md', ROOT / 'studies/martin_luk/notes/trades.csv',
        ROOT / 'studies/martin_luk/notes/RULES_CN.md', ROOT / 'studies/martin_luk/notes/SOURCES.md',
        ROOT / 'studies/trader_registry/dossiers/swing/martin_luk.md', PERIODS, REPORTS / 'strong_continue_ia.json']
    source.extend(dataset.sub / name for name in ('bars_raw.csv.gz', 'actions.csv.gz', 'universe.json'))
    source.extend(ROOT / 'data/martin-luk-subs' / name for name in ('INTERVIEWS_CORE_CN.md', 'lS9zbnLi1Gg.txt',
        'VKNEJA5r8zw.txt', 'xVXB5AIg9dk.transcript.zh-Hant.txt'))
    source.extend(Path(module.__file__) for name, module in list(sys.modules.items())
                  if name.startswith('studies.') and getattr(module, '__file__', None))
    return sorted(set(source))


def main():
    if TIMELINE.exists() or FRAMES.exists():
        raise FileExistsError('refusing to overwrite an existing IE stage-two result')
    if '### IE 第二段计算登记' not in PREREG.read_text(encoding='utf-8'):
        raise ValueError('reference formulas must be preregistered first')
    protect_outputs()
    ds = trader_data.dataset('us', mode='frozen', version='trader-data-v1')
    first = json.loads(PERIODS.read_text(encoding='utf-8'))
    if len(first['periods']) != 58 or sum(len(p['entries']) for p in first['periods']) != 81:
        raise ValueError('stage-one partition differs')
    ledger_path = ROOT / 'studies/martin_luk/notes/trades.csv'
    if first['input_sha256'][str(ledger_path.relative_to(ROOT))] != file_sha(ledger_path):
        raise ValueError('stage-one ledger differs')
    reference = json.loads((REPORTS / 'strong_continue_ia.json').read_text(encoding='utf-8'))
    digest = ds.digest()
    if digest != first['dataset_digest'] or digest != reference['dataset_digest']:
        raise ValueError('frozen dataset differs from stage one or IA')
    reference = reference['funnel']['base']
    paths = input_paths(ds)
    hashes = {str(p.relative_to(ROOT)): file_sha(p) for p in paths}
    d, fields, active, score, held, book, replay = build_h4(ds, reference)
    del reference
    codes = list(map(str, d.A['codes']))
    ci = {code: j for j, code in enumerate(codes)}
    wanted = defaultdict(set)
    for period in first['periods']:
        j = ci[period['code']]
        start, end = d.di[period['start']], d.di[period['end']]
        for i in range(max(0, start - 20), end + 1):
            wanted[i].add(j)
        for entry in period['entries']:
            for i in entry_nights(d.di[entry['entry_date']]):
                wanted[i].add(j)
    records, nights = {}, {}
    for count, i in enumerate(sorted(wanted)):
        records[i], nights[d.days[i]] = night_record(d, fields, active, held, score, book, i, wanted[i])
        if count % 150 == 0:
            print('H4 diagnostic nights', count, '/', len(wanted), flush=True)
    del fields, score, held, book
    gc.collect()
    volume, raw_v5 = reference_inputs(ds, d)
    frame_data = SimpleNamespace(days=d.days, codes=codes, c=d.c, t=d.t, volume=volume, raw_v5=raw_v5)
    needed_frames = defaultdict(set)
    for period in first['periods']:
        j = ci[period['code']]
        for entry in period['entries']:
            if entry['entry_date'] <= '2025-12-31':
                for i in entry_nights(d.di[entry['entry_date']]):
                    needed_frames[i].add(j)
    frame_events, frame_nights = {}, {}
    for count, i in enumerate(sorted(needed_frames)):
        snapshot = reference_snapshot(frame_data, i)
        frame_events[i] = {j: {name: frame_event(snapshot, name, j, d.days[i]) for name in FRAME_IDS}
                           for j in needed_frames[i]}
        frame_nights[d.days[i]] = {name: dict(width=snapshot['frames'][name]['width'],
            top10=[dict(code=codes[j], strength=number(snapshot['frames'][name]['value'][j]))
                   for j in snapshot['frames'][name]['order'][:10]]) for name in FRAME_IDS}
        if count % 20 == 0:
            print('reference nights', count, '/', len(needed_frames), flush=True)
    del volume, raw_v5, frame_data, snapshot
    gc.collect()
    entries, periods, controls = [], [], {}
    for period in first['periods']:
        j = ci[period['code']]
        start, end = d.di[period['start']], d.di[period['end']]
        history = []
        for i in range(max(0, start - 20), end + 1):
            item = records[i][j].copy()
            item['gain_from_start'] = item['close'] / period['start_close'] - 1 if item['close'] is not None else None
            history.append(item)
        attached = []
        for entry in period['entries']:
            index = d.di[entry['entry_date']]
            window = [records[i][j] for i in entry_nights(index)]
            target = target_label(d.c[:, j], d.h[:, j], index)
            if target['peak_index'] is not None:
                target['peak_date'] = d.days[target['peak_index']]
            systems = {'h4': window}
            if entry['entry_date'] <= '2025-12-31':
                systems.update({name: [frame_events[i][j][name] for i in entry_nights(index)] for name in FRAME_IDS})
            if index not in controls:
                controls[index] = active_control(d, active, index)
            row = dict(id=entry['id'], code=entry['code'], entry_date=entry['entry_date'], setup=entry['setup'],
                precision=entry['precision'], source=entry['source'], note=entry['note'], outcome=entry['outcome'],
                period_id=period['id'], period_gain=period['gain'],
                gain_bucket='ge_300' if period['gain'] >= 3 else '100_to_300' if period['gain'] >= 1 else '30_to_100',
                target=target, category=category(history, window), systems=systems,
                first_active=first_seen(history, 'active', start, index, d.di, period['start_close']),
                first_held=first_seen(history, 'held', start, index, d.di, period['start_close']),
                entry_after_period_end=index > end, same_day_active=controls[index],
                core_rescue=any(e['core'] for e in window) and not any(e['selected'] for e in window))
            entries.append(row)
            attached.append(row)
        within = [r for r in history if period['start'] <= r['date'] <= period['end']]
        periods.append(dict(id=period['id'], code=period['code'], start=period['start'], end=period['end'],
            gain=period['gain'], unfinished=period['unfinished'], flags=period['flags'],
            anchor_entry_id=attached[0]['id'], category=attached[0]['category'],
            target_tiers=sorted({r['target']['tier'] for r in attached}), entry_ids=[r['id'] for r in attached],
            first_active=attached[0]['first_active'], first_held=attached[0]['first_held'],
            held_fraction=sum(r['held'] for r in within) / len(within), period_sessions_inclusive=len(within),
            trace_start=history[0]['date'], timeline=history))
    selected_rows = year_sample(entries, '2024_2025')
    frame_coverage = coverage_strata(selected_rows, FRAME_IDS + ('h4',))
    frame_diagnosis = {}
    for name in FRAME_IDS:
        detail = []
        for row in selected_rows:
            events = row['systems'][name]
            best = min((e for e in events if e['rank'] is not None), key=lambda e: (e['rank'], e['date']), default=None)
            detail.append(dict(id=row['id'], code=row['code'], tier=row['target']['tier'],
                reason='scope_excluded_all_four_nights' if best is None else 'top5' if best['rank'] <= 5 else
                       'ranked_6_to_10' if best['rank'] <= 10 else 'strength_below_top10',
                best=best, prior_evening=events[-1], nights=events))
        frame_diagnosis[name] = dict(reason_counts={tier: dict(Counter(r['reason'] for r in detail
            if tier == 'all' or r['tier'] == tier)) for tier in ('all', 'primary', 'secondary')}, rows=detail)
    period_counts = {}
    for year in ('all', '2024_2025', '2026'):
        anchors = {r['id'] for r in year_sample(entries, year)}
        period_counts[year] = {}
        for tier in ('all', 'primary', 'secondary'):
            sample = [p for p in periods if p['anchor_entry_id'] in anchors and (tier == 'all' or tier in p['target_tiers'])]
            period_counts[year][tier] = dict(n=len(sample), categories=dict(Counter(p['category'] for p in sample)))
    for p in input_paths(ds):
        key = str(p.relative_to(ROOT))
        value = file_sha(p)
        if key in hashes and value != hashes[key]:
            raise ValueError('an input changed during computation: ' + key)
        hashes[key] = value
    common = dict(stage=2, diagnostic_only=True, third_stage_executed=False, cutoff=d.days[-1],
        generated_utc=datetime.now(timezone.utc).isoformat(), dataset_digest=digest, input_sha256=hashes,
        preregistration='studies/martin_luk/notes/PREREG_STRONG.md#ie-第二段计算登记',
        processing=dict(single_research_process=True, cache_written=False, fetched=False,
                        max_correlation_width=300, panel_shape=list(d.c.shape),
                        peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss),
        conventions=dict(window='入场前第1、2、3、4个市场交易日晚；chart只用名义日，不扩窗口',
            h4_clock='IA原样：t晚评分/active使用t-1特征，形态使用t；不是实际成交',
            frame_clock='t晚只用截至t的数据；周末扫描冻结到下次周末',
            rank='1起；H4保留原np.argsort并列；参照系同分按代码',
            primary='入场后第1至60日最高价/入场日收盘-1>=30%，评价专用',
            random='同一范围每日独立均匀前K的四晚精确期望，不是显著性检验',
            period_category='按最早入场分类；主/次段数按挂接笔分类，混合段可重复',
            history='首次仅指起点前20日起的诊断窗口；边界可见标左删失',
            future_returns='20日最高价与第20日收盘均从次日起算，截断和缺K显式保留，评价专用'),
        limitations=['冻结名单不是完整历史点时证券池，包含生存及选样偏差',
            '台账为选择性披露，重复股票/同日再入按笔计数，非独立样本',
            '未使用2026参照系结果；2026的H4也不是新的样本外评测',
            '字幕/译稿未逐句听校音频；档案较旧的未读状态不覆盖后续已存字幕',
            '右删失目标未达30%者只是暂列次要，不能当最终失败',
            '弱分组为描述关联，不是因果归因或第三段新增因子'])
    core_summary = {}
    for year in ('2024_2025', '2026'):
        core_summary[year] = {}
        for tier in ('all', 'primary', 'secondary'):
            sample = [r for r in year_sample(entries, year) if tier == 'all' or r['target']['tier'] == tier]
            core_summary[year][tier] = dict(n=len(sample), hits=sum(r['category'] == CATEGORIES[6] for r in sample),
                                           core_rescues=sum(r['core_rescue'] for r in sample))
    timeline = dict(common, baseline=dict(passed=True, ia_summary=replay['summary'],
        compared_rows=len(replay['rows']), exact_daily_states_identical=True, all_located_ia_rows=replay['rows']),
        partition=dict(periods=len(periods), entries=len(entries), target_tiers=dict(Counter(r['target']['tier'] for r in entries))),
        h4_coverage=coverage_strata(entries, ('h4',)),
        h4_qualified_signal_coverage=coverage_strata(entries, ('h4',), 'qualified_rank', 'qualified_width'),
        h4_core_or_top6=core_summary, entry_classification=classification_strata(entries),
        period_classification=period_counts, active_controls=control_summary(entries),
        anomalies=dict(entries_after_period_end=[r['id'] for r in entries if r['entry_after_period_end']],
            inherited_stage1=first['anomalies'], provisional_secondary=[r['id'] for r in entries if r['target']['provisional']],
            censored_primary=[r['id'] for r in entries if r['target']['censored'] and r['target']['tier'] == 'primary'],
            stage1_exclusions={key: first[key] for key in ('no_obvious_strong_period', 'missing_data', 'window_only')}),
        candidate_table_columns=['code', 'h4_score', 'future20_max_high_gain', 'future20_end_close_gain', 'valid_high_bars'],
        ahead_lookup='timeline的date对应nightly_candidates；前ahead_count行就是排在该股前面的全部股票；非active则没有可比名次',
        nightly_candidates=nights, periods=periods,
        entries=[{**r, 'systems': {'h4': r['systems']['h4']}} for r in entries])
    frames = dict(common, evaluation_years=['2024', '2025'], no_2026_frame_results=True,
        formulas={'potent_day': 'T>=50M & raw V5>=.035 & c>EMA21; sort g1 descending',
            'leader_weekend': 'last completed week c*sum(adjusted volume)>300M; sort g21 at week end, freeze until next week end',
            'premier_ema_leader': 'M20>=100M & EMA9>EMA21>EMA50; sort g21 descending',
            'premier_liquidity': 'M20>=100M; sort M20 descending'},
        source_evidence=[dict(path='studies/martin_luk/notes/RULES_CN.md', section='①②③'),
            dict(path='studies/trader_registry/dossiers/swing/martin_luk.md', section='ML4, 2025-02-02 edited',
                 url='https://tradingresourcehub.substack.com/p/martin-luk-283-usic-2024-key-lessons/comment/90457733'),
            dict(path='data/martin-luk-subs/lS9zbnLi1Gg.txt', section='01:30:37–01:40:22',
                 url='https://www.youtube.com/watch?v=lS9zbnLi1Gg&t=5437'),
            dict(path='data/martin-luk-subs/VKNEJA5r8zw.txt', section='02:31:03–02:33:06; 03:18:30',
                 url='https://www.youtube.com/watch?v=VKNEJA5r8zw&t=9063'),
            dict(path='data/martin-luk-subs/INTERVIEWS_CORE_CN.md', section='3、4、8',
                 url='https://www.youtube.com/watch?v=xVXB5AIg9dk&t=2382')],
        gaps=['无盘前跳空与同时段量能，不能用次日开盘代替前夜输入',
            '无历史人工观察名单、升级/降级和最终裁量名次',
            '无点时题材/行业标签，相关系数不能冒充他看到的题材',
            '无点时市值与收购排除字段，potent范围只能近似',
            '未核验TV周volatility精确定义；V5是固定研究代理',
            'premier均值窗口、EMA组内次序原话未给；20日和g21为研究者约定',
            '多个访谈版本和字段可能随时间改变，不能追认为2024统一硬规则',
            '缺最终把背景/形态/流动性合并为前五的规则'],
        coverage=frame_coverage, diagnosis=frame_diagnosis, nightly_frames=frame_nights,
        active_controls=control_summary(selected_rows),
        entries=[dict(id=r['id'], code=r['code'], entry_date=r['entry_date'], setup=r['setup'],
                      precision=r['precision'], target=r['target'], systems=r['systems']) for r in selected_rows])
    for path, result in ((TIMELINE, timeline), (FRAMES, frames)):
        with path.open('x', encoding='utf-8') as stream:
            json.dump(result, stream, ensure_ascii=False, separators=(',', ':'), allow_nan=False, default=json_default)
            stream.write('\n')
        print('wrote', path.name, path.stat().st_size, flush=True)
    print('target tiers', timeline['partition'], 'period classes', period_counts['all']['all'], flush=True)
    for year in ('2024_2025', '2026'):
        print('H4', year, timeline['h4_coverage'][year], flush=True)
    for name in FRAME_IDS:
        print('frame', name, {tier: frame_coverage['2024_2025'][tier][name]
                             for tier in ('all', 'primary', 'secondary')}, flush=True)


if __name__ == '__main__':
    main()
