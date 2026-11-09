"""IE13: bounded, explainable ranking with identical period and label controls."""
import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import csv
import gc
import html
import json
import os
from pathlib import Path
import re
import resource
import socket
import time
from unittest.mock import patch

import numpy as np

from studies.trader_replication import martin_continue_ie12 as ie12
from studies.trader_replication import martin_continue_ie11 as ie11

prior, ie7, old, lib = ie12.prior, ie12.prior.ie7, ie12.prior.old, ie12.prior.lib
ROOT, REPORTS = prior.ROOT, prior.REPORTS
WORK = REPORTS / 'ie13_work'
PREFIX = 'strong_continue_ie13_'
PLAN = ROOT / 'studies/martin_luk/notes/PLAN_IE13_CN.md'
LEDGER = ROOT / 'studies/martin_luk/notes/trades.csv'
SEEDS = (130101, 130103, 130107, 130109, 130111)
FILTERS = (('h4_history', .5), ('adr20', .7), ('option_volume', .8), ('low20', .5))
BASE = ('h4_history', 'option_volume', 'near_ema9', 'peer_rank', 'h4_peers', 'high20',
        'g21', 'h4_momentum')
PROCESS = ('after_inside', 'volume_rebound', 'rs1', 'prior_run63', 'pool_visits20',
           'pool_streak', 'range_contract5', 'volume_dry3', 'ema9_gap_adr',
           'state_pullback', 'state_breakout', 'state_ep', 'call_surge5', 'ep_hold', 'near_ema21')
PLATE = tuple(k + '.' + n for k in ie11.KINDS for n in ie11.METRICS)
NAMES = BASE + PROCESS + PLATE
EVENTS = {'after_inside', 'state_pullback', 'state_breakout', 'state_ep', 'ep_hold'}
TERMS = {
    'history': dict(name='h4_history', direction=1, text='过去反复进入强势扫描的股票加分，对应反复强势的龙头。'),
    'options': dict(name='option_volume', direction=1, text='当晚期权成交更活跃的股票加分，对应关注度和交易流动性。'),
    'quiet_volume': dict(name='volume_rebound', direction=-1, text='当日量相对前三日均量更安静的股票加分，对应回调时缩量。'),
    'quiet_return': dict(name='rs1', direction=-1, text='当日相对基准涨幅较低的股票加分，对应强势票整理时买弱。'),
    'near9': dict(name='near_ema9', direction=1, text='按自身日均振幅衡量更靠近9日线的股票加分，对应9日线回调。'),
    'near21': dict(name='near_ema21', direction=1, text='按自身日均振幅衡量更靠近21日线的股票加分，对应21日线回调。'),
    'contraction': dict(name='range_contract5', direction=-1, text='近五日振幅相对20日更收窄的股票加分，对应整理收窄后突破。'),
    'prior_run': dict(name='prior_run63', direction=1, text='此前63晚出现过更大21日涨幅的股票加分，对应做过大行情的龙头。'),
    'visits': dict(name='pool_visits20', direction=1, text='过去20晚更多次留在过滤后池子的股票加分，对应持续关注反复强势股。'),
    'dry3': dict(name='volume_dry3', direction=-1, text='近三日均量相对20日更低的股票加分，对应缩量整理。'),
    'peer': dict(name='peer_rank', direction=1, text='在历史价格同伙中的强度位置更高的股票加分，对应同伙中的龙头。'),
    'inside': dict(name='after_inside', direction=1, text='前一日是内包日则加分，对应内包整理后的突破窗口。'),
    'near_high': dict(name='high20', direction=1, text='收盘更靠近20日高点的股票加分，对应高位整理后再突破。'),
    'pullback_quiet': dict(name='volume_rebound', direction=-1, state='state_pullback',
        text='处于可观察回调状态且当日缩量的股票加分，对应强势股回调买点。'),
    'breakout_coil': dict(name='range_contract5', direction=-1, state='state_breakout',
        text='处于近前高整理状态且振幅收窄的股票加分，对应收窄后突破。'),
    'ep': dict(name='ep_hold', direction=1, text='近五晚有放量跳空、已公布财报在五晚内且守在9日线上则加分，对应EP后的延续。'),
    'industry_leader': dict(name='industry.leader20', direction=1, text='在所属行业内20日收益位置更高则加分，对应行业龙头。'),
    'industry_heat': dict(name='industry.heat20', direction=1, text='所属行业20日整体涨幅排位更高则加分，对应强行业。'),
    'concept_leader': dict(name='concept.leader20', direction=1, text='在所属题材内20日收益位置更高则加分，对应题材龙头。'),
    'concept_heat': dict(name='concept.heat20', direction=1, text='所属题材20日整体涨幅排位更高则加分，对应强题材。'),
}
FAMILIES = (
    dict(id='quiet', terms=['history', 'quiet_volume', 'quiet_return', 'near9', 'contraction', 'options'], eligible=True),
    dict(id='persistent', terms=['history', 'prior_run', 'visits', 'near21', 'dry3', 'options'], eligible=True),
    dict(id='breakout', terms=['history', 'peer', 'inside', 'near_high', 'contraction', 'options'], eligible=True),
    dict(id='states', terms=['history', 'peer', 'pullback_quiet', 'breakout_coil', 'ep', 'options'], eligible=True),
    dict(id='plates', terms=['history', 'industry_leader', 'industry_heat', 'concept_leader', 'concept_heat', 'options'],
         eligible=False, reason='当前板块成员快照没有历史点时版本，不能通过禁止未来信息的要求。'),
)


def initialize():
    protected = {}
    for directory in ('data', 'custody', 'studies/martin_luk', 'skills'):
        for base, _, files in os.walk(ROOT / directory):
            for name in files:
                path = Path(base) / name
                if '__pycache__' not in path.parts:
                    stat = path.stat()
                    protected[str(path.relative_to(ROOT))] = [stat.st_size, stat.st_mtime_ns]
    sources = [PLAN, LEDGER, old.WORK / 'prepared.json', old.FROZEN,
        ie12.WORK / 'features.json', prior.WORK / 'features.json', ie11.WORK / 'features.json',
        old.WORK / 'account_rules.json']
    sources += [p for p in REPORTS.glob('strong_continue_ie*') if p.is_file() and not p.name.startswith(PREFIX)]
    save(WORK / 'protected_inputs.json', dict(utc=stamp(), metadata=protected,
        hashes={str(p.relative_to(ROOT)): prior.prior.file_sha(p) for p in sources}))


def finalize_dates():
    initial = read(WORK / 'date_audit_initial.json')
    review = read(WORK / 'date_review.json')
    reviews = {r['id']: r for r in review['chart_review']}
    corrections = {r['id']: r for r in review['corrections']}
    rows, findings = [], []
    for row in initial['rows']:
        finding = dict(row)
        clean = {name: row[name] for name in initial['fields']}
        if row['precision'] == 'chart':
            finding['review'] = reviews[row['id']]
        else:
            finding['review'] = dict(status=row['status'], reason='核对交易日、原窗口、备注与所引字幕；未找到能确证需要改日的材料。')
        if row['id'] in corrections:
            correction = corrections[row['id']]
            clean['entry_date'] = correction['entry_date']
            clean['window_lo'] = clean['window_hi'] = correction['entry_date']
            clean['precision'] = correction['precision']
            clean['note'] += '; IE13 date correction: ' + correction['reason']
        finding['revised_entry_date'] = clean['entry_date']
        findings.append(finding)
        rows.append(clean)
    if set(reviews) != {r['id'] for r in initial['rows'] if r['precision'] == 'chart'}:
        raise ValueError('every chart record must be reviewed exactly once')
    ledger = WORK / 'trades_ie13_v1.csv'
    with ledger.open('x', newline='', encoding='utf-8') as stream:
        writer = csv.DictWriter(stream, initial['fields'])
        writer.writeheader()
        writer.writerows(rows)
    output('dates', dict(utc=stamp(), method=review['method'], original_sha256=initial['ledger_sha256'],
        version=str(ledger.relative_to(ROOT)), version_sha256=prior.prior.file_sha(ledger),
        corrections=review['corrections'], rows=findings, precision=initial['precision'],
        uncertain=sum(r.get('review', {}).get('status') == 'uncertain' for r in findings)))


def queries(entries, days, slices, codes):
    positions = {day: t for t, day in enumerate(days)}
    result = []
    for entry in entries:
        t = positions[entry['entry_date']]
        qs = []
        for day in days[max(0, t - 4):t]:
            names = codes.get(day, [])
            k = names.index(entry['code']) if entry['code'] in names else -1
            qs.append(slices[day][0] + k if k >= 0 else -1)
        result.append(qs)
    return result


def process_values(arrays, extras):
    values = ie12.path_values(arrays)
    values.update(prior.ie9.trigger_values(arrays))
    values.update(prior.derived_values(extras))
    c, h, l = (arrays[k] for k in ('c', 'h', 'l'))
    adr = lib.roll(lib.divide(h, l) - 1, 20)
    e9 = lib.smooth(c, 9)
    values['near_ema21'] = -lib.divide(abs(lib.divide(c, lib.smooth(c, 21)) - 1), adr)
    age = extras['earn_days']
    valid = np.isfinite(age) & np.isfinite(values['state_ep']) & np.isfinite(c) & np.isfinite(e9)
    values['ep_hold'] = np.where(valid,
        (values['state_ep'] == 1) & (age >= 0) & (age <= 5) & (c >= e9), np.nan)
    return values


def prepare():
    d = ie7.Data(full=True)
    pct = np.load(ie7.WORK / 'full_pct.npy', mmap_mode='r')
    passed = np.zeros(d.n, bool)
    for day, sl in d.slices.items():
        if day >= d.meta['first_signal']:
            passed[sl] = prior.ie8.gate_mask(pct[sl], d.names,
                [dict(name=n, direction=1, cutoff=c) for n, c in FILTERS])
    indices = np.flatnonzero(passed)
    np.save(WORK / 'indices.npy', indices)
    dest = np.lib.format.open_memmap(WORK / 'features.npy', mode='w+', dtype=np.float32,
                                    shape=(len(indices), len(NAMES)))
    dest[:] = np.nan
    for a in range(0, len(indices), 2048):
        for name in BASE:
            dest[a:a + 2048, NAMES.index(name)] = d.raw[indices[a:a + 2048], d.names.index(name)]
    days, slices, codes, bycode = d.meta['days'], {}, {}, defaultdict(list)
    di = {day: t for t, day in enumerate(days)}
    for day, sl in d.slices.items():
        a, b = map(int, np.searchsorted(indices, (sl.start, sl.stop)))
        slices[day] = [a, b]
        codes[day] = [d.meta['scope'][day][int(q - sl.start)] for q in indices[a:b]]
        if codes[day] != sorted(codes[day]):
            raise ValueError('night rows must follow the documented security tie order')
        for row, code in zip(range(a, b), codes[day]):
            bycode[code].append((di[day], row))
    source_hashes = {}
    for number, (code, positions) in enumerate(bycode.items()):
        path = old.WORK / 'stocks' / (code + '.npz')
        source_hashes[str(path.relative_to(ROOT))] = prior.prior.file_sha(path)
        with np.load(path) as z:
            arrays = {k: z[k] for k in ('o', 'h', 'l', 'c', 'v')}
            extra = {k[6:]: z[k] for k in z.files if k.startswith('extra_')}
        path_values = process_values(arrays, extra)
        membership = np.zeros(len(days), bool)
        ts, rows = map(np.asarray, zip(*positions))
        membership[ts] = True
        path_values.update(ie12.sequence_values(membership))
        for name in PROCESS:
            if name == 'rs1':
                dest[rows, NAMES.index(name)] = d.raw[indices[rows], d.names.index(name)]
            else:
                dest[rows, NAMES.index(name)] = path_values[name][ts]
        if number % 200 == 0:
            print('process securities', number, '/', len(bycode), flush=True)
    membership = read(WORK / 'plates/membership.json')
    all_codes = membership['codes']
    ci = {c: j for j, c in enumerate(all_codes)}
    close, pot, history = (np.load(ie11.WORK / (name + '.npy'), mmap_mode='r')
                           for name in ('member_close', 'member_pot', 'member_history'))
    if close.shape != (len(days), len(all_codes)):
        raise ValueError('IE11 member panel alignment differs')
    for kind in ie11.KINDS:
        groups = [[ci[c] for c in cs if c in ci] for cs in membership['members'][kind].values()]
        values = ie11.member_factors(close, pot, history, groups)
        for day, (a, b) in slices.items():
            js = [ci[c] for c in codes[day]]
            for name in ie11.METRICS:
                dest[a:b, NAMES.index(kind + '.' + name)] = values[name][di[day], js]
        del values
        gc.collect()
        print('plates calculated', kind, flush=True)
    for a, b in slices.values():
        for j, name in enumerate(NAMES):
            if name not in EVENTS:
                dest[a:b, j] = ie7.night_percentiles(dest[a:b, j:j + 1])[:, 0]
    dest.flush()
    revised = {r['id']: r for r in csv.DictReader((WORK / 'trades_ie13_v1.csv').open())}
    entries, date_changes = [], []
    for original in d.entries:
        entry = dict(original)
        row = revised[entry['id']]
        if row['entry_date'] != original['entry_date']:
            entry.update(entry_date=row['entry_date'], precision=row['precision'])
            with np.load(old.WORK / 'stocks' / (entry['code'] + '.npz')) as z:
                entry['target'] = old.prior.ie.target_label(z['c'], z['h'], di[entry['entry_date']])
            date_changes.append(dict(id=entry['id'], old_target=original['target'], new_target=entry['target']))
        t = di[entry['entry_date']]
        entry['systems'] = dict(h4=[dict(date=day) for day in days[t - 4:t]])
        entries.append(entry)
    query = queries(entries, days, slices, codes)
    meta = dict(utc=stamp(), names=list(NAMES), days=days, slices=slices, codes=codes,
        entries=entries, query=query, filters=FILTERS, date_changes=date_changes,
        plan_sha256=prior.prior.file_sha(PLAN), dataset_digest=d.meta['dataset_digest'],
        feature_sha256=prior.prior.file_sha(WORK / 'features.npy'), source_hashes=source_hashes,
        plate_point_in_time=False, plate_eligibility='diagnostic_only_no_historical_membership_versions')
    save(WORK / 'features.json', meta)
    print('prepared', dest.shape, flush=True)


class Data:
    def __init__(self, seed=None):
        self.meta = read(WORK / 'features.json')
        self.x = np.load(WORK / 'features.npy', mmap_mode='r')
        self.names = self.meta['names']
        self.entries = self.meta['entries']
        self.query = self.meta['query']
        self.slices = {day: slice(*ab) for day, ab in self.meta['slices'].items()}
        self.halves = sorted({ie7.half(e['entry_date']) for e in self.entries})
        if seed is not None:
            self.query = shuffled_queries(self.query, self.slices, len(self.x), seed)


def shuffled_queries(query, slices, size, seed):
    rng = np.random.default_rng(seed)
    mapping = np.arange(size)
    for sl in slices.values():
        mapping[sl] = rng.permutation(mapping[sl])
    return [[int(mapping[q]) if q >= 0 else -1 for q in qs] for qs in query]


def observe():
    d = Data()
    scores = (np.nan_to_num(d.x[:, d.names.index('after_inside')], nan=.5) +
              np.nan_to_num(d.x[:, d.names.index('near_ema9')], nan=.5)) / 2
    ranks, selected = rank_scores(d, scores)
    rows = []
    for entry, qs in zip(d.entries, d.query):
        nights = []
        for signal, q in zip(entry['systems']['h4'], qs):
            day = signal['date']
            sl = d.slices[day]
            top = np.argsort(ranks[sl], kind='stable')[:5] + sl.start
            own = {n: float(d.x[q, j]) if q >= 0 and np.isfinite(d.x[q, j]) else None for j, n in enumerate(d.names)}
            median = {n: float(np.nanmedian(d.x[top, j])) if len(top) and np.isfinite(d.x[top, j]).any()
                      else None for j, n in enumerate(d.names)}
            nights.append(dict(date=day, row=q, rank=int(ranks[q]) if q >= 0 else None,
                own=own, top5=selected[day], top5_median=median))
        rows.append(dict(id=entry['id'], code=entry['code'], entry_date=entry['entry_date'],
            precision=entry['precision'], setup=entry['setup'], primary=entry['target']['tier'] == 'primary',
            best_rank=min((int(ranks[q]) for q in qs if q >= 0), default=10**6), nights=nights))
    output('observation', dict(rows=rows, baseline='IE9 formula recomputed inside the IE13 pool'))


def rank_scores(d, scores):
    ranks = np.full(len(d.x), 10**6, np.int32)
    selected = {}
    for day, sl in d.slices.items():
        order = np.argsort(-scores[sl], kind='stable')
        ranks[sl.start + order] = np.arange(1, len(order) + 1)
        selected[day] = [d.meta['codes'][day][k] for k in order[:5]]
    return ranks, selected


def register():
    d = Data()
    spec = dict(utc=stamp(), plan_sha256=prior.prior.file_sha(PLAN),
        features_sha256=d.meta['feature_sha256'], periods=d.halves, filters=FILTERS,
        terms=TERMS, families=FAMILIES, weights=[.5, 1., 2.], coordinate_passes=2,
        fit_key=['worst_training_period', 'median_training_period', 'training_total',
                 'negative_log_rank_loss', 'smaller_weight_sum', 'registered_order'],
        selection=['worst_heldout_period', 'median_heldout_period', 'heldout_total', 'fewer_terms', 'registered_order'],
        ablation='对选中的规则族逐项删加分项并重做六折拟合，留一合计覆盖不降即删，重新从头直到不能删。',
        shuffle_seeds=list(SEEDS), shuffle_margin_percentage_points=10., shuffle_minimum_extra_hits=3,
        shuffle_test='真标签最终留一合计命中至少比五次同流程打乱最好结果多max(3,ceil(0.10*N))笔。',
        random_test='六个留出时段分别严格高于同池四晚并集理论期望。',
        heldout_boundary='训练剔除与留出时段任一评价前夜相交的交易，且不使用留出半年内的训练前夜。',
        accounts='冻结后现金六仓和既有杠杆账户仅报告，不据收益反选。',
        no_regime_or_quota_search=True, no_midbands_or_interactions_search=True,
        membership_snapshots_diagnostic_only=True)
    save(WORK / 'registration.json', spec)
    output('registration', spec)


def basis(x, names, term_names):
    out = np.zeros((len(x), len(term_names)), np.float32)
    for j, key in enumerate(term_names):
        term = TERMS[key]
        a = x[:, names.index(term['name'])]
        valid = np.isfinite(a)
        values = a if term['direction'] > 0 else 1 - a
        if 'state' in term:
            state = x[:, names.index(term['state'])]
            valid &= np.isfinite(state)
            values = values * np.nan_to_num(state)
        out[:, j] = np.where(valid, values, 0.)
    return out


def training_bundle(d, heldout):
    blocked = {s['date'] for e in d.entries if ie7.half(e['entry_date']) == heldout
               for s in e['systems']['h4']}
    ids, purged = [], []
    for i, entry in enumerate(d.entries):
        if entry['target']['tier'] != 'primary' or ie7.half(entry['entry_date']) == heldout:
            continue
        dates = [s['date'] for s in entry['systems']['h4']]
        if heldout is not None and any(day in blocked or ie7.half(day) == heldout for day in dates):
            purged.append(entry['id'])
        else:
            ids.append(i)
    days = sorted({s['date'] for i in ids for s, q in zip(d.entries[i]['systems']['h4'], d.query[i]) if q >= 0})
    rows = np.concatenate([np.arange(d.slices[day].start, d.slices[day].stop) for day in days]) if days else np.array([], int)
    remap = np.full(len(d.x), -1, np.int32)
    remap[rows] = np.arange(len(rows))
    nights = {day: remap[np.arange(d.slices[day].start, d.slices[day].stop)] for day in days}
    bags = [[(nights[s['date']], int(remap[q])) for s, q in zip(d.entries[i]['systems']['h4'], d.query[i]) if q >= 0]
            for i in ids]
    return dict(x=np.asarray(d.x[rows]), bags=bags, periods=[ie7.half(d.entries[i]['entry_date']) for i in ids],
                ids=[d.entries[i]['id'] for i in ids], purged=purged, rows=rows)


def ranks_for_scores(bundle, scores):
    if scores.ndim == 1:
        scores = scores[:, None]
    return ie12.candidate_ranks(bundle, np.zeros(len(scores)), scores, 1.)


def fit_keys(bundle, ranks):
    groups = sorted(set(bundle['periods']))
    rates = np.array([(ranks[np.array(bundle['periods']) == h] <= 5).mean(axis=0) for h in groups])
    if not len(groups):
        return [(0., 0., 0, 0.) for _ in range(ranks.shape[1])]
    return list(zip(rates.min(0), np.median(rates, axis=0), (ranks <= 5).sum(0),
                    -np.log1p(np.minimum(ranks, 100) / 5).sum(0)))


def fit_model(d, terms, heldout=None, registration=None):
    registration = registration or read(WORK / 'registration.json')
    bundle = training_bundle(d, heldout)
    x = basis(bundle['x'], d.names, terms)
    weights = np.full(len(terms), .5)
    scores = x @ weights
    ranks = ranks_for_scores(bundle, scores)
    current = (*fit_keys(bundle, ranks)[0], -weights.sum())
    for _ in range(registration['coordinate_passes']):
        changed = False
        for j in range(len(terms)):
            candidates = np.asarray(registration['weights'])
            trial = scores[:, None] + x[:, j, None] * (candidates - weights[j])
            trial_ranks = ranks_for_scores(bundle, trial)
            keys = [(*key, -(weights.sum() - weights[j] + weight))
                    for key, weight in zip(fit_keys(bundle, trial_ranks), candidates)]
            winner = max(range(len(keys)), key=lambda k: keys[k])
            if keys[winner] > current:
                weights[j] = candidates[winner]
                scores = trial[:, winner]
                current = keys[winner]
                changed = True
        if not changed:
            break
    return dict(terms=list(terms), weights=weights.tolist(), training_ids=bundle['ids'],
                purged_ids=bundle['purged'], training_score=list(current[:-1]))


def model_scores(d, model):
    return basis(d.x, d.names, model['terms']) @ np.asarray(model['weights'])


def coverage_rows(d, ranks, ids=None):
    rows = []
    for i in range(len(d.entries)) if ids is None else ids:
        entry, qs = d.entries[i], d.query[i]
        rows.append(dict(id=entry['id'], code=entry['code'], entry_date=entry['entry_date'],
            primary=entry['target']['tier'] == 'primary', in_scope=any(q >= 0 for q in qs),
            passed_gate=any(q >= 0 for q in qs),
            best_rank=min((int(ranks[q]) for q in qs if q >= 0), default=10**6)))
    return rows


def summarize(rows):
    return dict(primary=ie7.summarize([r for r in rows if r['primary']]), all_entries=ie7.summarize(rows),
        periods={h: ie7.summarize([r for r in rows if r['primary'] and ie7.half(r['entry_date']) == h])
                 for h in sorted({ie7.half(r['entry_date']) for r in rows})})


def cv_key(result):
    summaries = list(result['coverage']['periods'].values())
    rates = [ie7.rate(s) for s in summaries]
    return min(rates), float(np.median(rates)), result['coverage']['primary']['hits']['5'], -len(result['terms'])


def crossvalidate(d, terms, seed, registration):
    source_hash = prior.prior.file_sha(Path(__file__))
    key = prior.prior.digest(dict(terms=terms, seed=seed, registration=registration, source_hash=source_hash))
    path = WORK / 'evaluations' / (key + '.json')
    if path.exists():
        return read(path)
    folds, rows = {}, []
    for half in d.halves:
        model = fit_model(d, terms, half, registration)
        ranks, _ = rank_scores(d, model_scores(d, model))
        ids = [i for i, entry in enumerate(d.entries) if ie7.half(entry['entry_date']) == half]
        fold_rows = coverage_rows(d, ranks, ids)
        folds[half] = dict(model=model, coverage=summarize(fold_rows), rows=fold_rows)
        rows.extend(fold_rows)
    result = dict(terms=list(terms), folds=folds, coverage=summarize(rows), rows=rows, fit_source_sha256=source_hash)
    result['score'] = list(cv_key(result))
    save(path, result)
    return result


def run_pipeline(seed=None):
    registration = read(WORK / 'registration.json')
    d = Data(seed)
    families = []
    for family in registration['families']:
        result = crossvalidate(d, family['terms'], seed, registration)
        families.append(dict(id=family['id'], eligible=family['eligible'], result=result,
                             reason=family.get('reason')))
        print('label', seed, family['id'], result['score'], flush=True)
    selected = max((r for r in families if r['eligible']), key=lambda r: cv_key(r['result']))
    current, log = selected['result'], []
    while current['terms']:
        accepted = False
        for term in current['terms']:
            remaining = [t for t in current['terms'] if t != term]
            trial = crossvalidate(d, remaining, seed, registration)
            keep_deletion = trial['coverage']['primary']['hits']['5'] >= current['coverage']['primary']['hits']['5']
            log.append(dict(removed=term, before=current['coverage'], after=trial['coverage'], accepted=keep_deletion))
            if keep_deletion:
                current = trial
                accepted = True
                break
        if not accepted:
            break
    final_model = fit_model(d, current['terms'], registration=registration)
    result = dict(seed=seed, families=families, selected_family=selected['id'], cv=current,
                  ablation=log, model=final_model)
    label = 'true' if seed is None else 'shuffle_' + str(seed)
    output(label, result)
    print('pipeline', label, current['score'], final_model['terms'], flush=True)


def fit():
    (WORK / 'evaluations').mkdir(exist_ok=True)
    for seed in (None, *SEEDS):
        label = 'true' if seed is None else 'shuffle_' + str(seed)
        if not (REPORTS / (PREFIX + label + '.json')).exists():
            run_pipeline(seed)


def random_expectation(d):
    widths = np.zeros(len(d.x), int)
    for sl in d.slices.values():
        widths[sl] = sl.stop - sl.start
    rows = []
    for entry, qs in zip(d.entries, d.query):
        p = [min(1., 5 / widths[q]) for q in qs if q >= 0]
        rows.append(dict(id=entry['id'], entry_date=entry['entry_date'], primary=entry['target']['tier'] == 'primary',
                         union=1 - float(np.prod(1 - np.asarray(p)))))
    def summary(sample):
        return dict(n=len(sample), union=sum(r['union'] for r in sample))
    return dict(rows=rows, primary=summary([r for r in rows if r['primary']]),
        periods={h: summary([r for r in rows if r['primary'] and ie7.half(r['entry_date']) == h]) for h in d.halves})


def freeze():
    d = Data()
    true = read(REPORTS / (PREFIX + 'true.json'))
    controls = [read(REPORTS / (PREFIX + 'shuffle_' + str(seed) + '.json')) for seed in SEEDS]
    hits = true['cv']['coverage']['primary']['hits']['5']
    best_shuffle = max(c['cv']['coverage']['primary']['hits']['5'] for c in controls)
    margin = max(3, int(np.ceil(.1 * true['cv']['coverage']['primary']['n'])))
    expected = random_expectation(d)
    random_pass = {h: true['cv']['coverage']['periods'][h]['hits']['5'] > expected['periods'][h]['union'] for h in d.halves}
    shuffled = [dict(seed=c['seed'], family=c['selected_family'], coverage=c['cv']['coverage'],
        initial_family_best_hits=max(f['result']['coverage']['primary']['hits']['5'] for f in c['families'] if f['eligible']))
        for c in controls]
    output('frozen', dict(utc=stamp(), plan_sha256=prior.prior.file_sha(PLAN),
        registration_sha256=prior.prior.file_sha(WORK / 'registration.json'),
        feature_sha256=d.meta['feature_sha256'], fit_source_sha256=true['cv']['fit_source_sha256'],
        filters=FILTERS, family=true['selected_family'], model=true['model'],
        rules={t: TERMS[t] for t in true['model']['terms']}, cv=true['cv']['coverage'], expected=expected,
        shuffle=dict(results=shuffled, best=best_shuffle, required_extra_hits=margin,
            extra_hits=hits - best_shuffle, passed=hits >= best_shuffle + margin),
        random_pass=random_pass, qualified=hits >= best_shuffle + margin and all(random_pass.values()),
        target_80_reached=cv_key(true['cv'])[0] >= .8,
        note='六折是同一拟合流程的跨时段稳定性，包含反向训练；冻结权重用全部六段，账户是同段拟合后的回放。'))


def period_accounts(result, fidelity, entries, halves):
    curve, dates, trades = np.asarray(result['curve']), np.asarray(result['dates']), result['trades']
    out = {}
    for half in halves:
        ix = np.flatnonzero([ie7.half(day) == half for day in dates])
        base = curve[ix[0] - 1] if ix[0] else 1.
        values = np.r_[base, curve[ix]]
        sample = [t for t in trades if ie7.half(t['entry']) == half]
        closed = [t for t in sample if t['why'] != 'end']
        wins = [t.get('ret_invested', t['ret']) for t in closed if t['ret'] > 0]
        losses = [t.get('ret_invested', t['ret']) for t in closed if t['ret'] <= 0]
        matched = [r for r in fidelity if ie7.half(r['entry_date']) == half]
        own = [e for e in entries if ie7.half(e['entry_date']) == half]
        out[half] = dict(entries=len(sample), closed=len(closed), win=len(wins) / len(closed) if closed else None,
            payoff=float(np.mean(wins) / -np.mean(losses)) if wins and losses and np.mean(losses) < 0 else None,
            return_=float(values[-1] / base - 1), maxdd=float(np.max(1 - values / np.maximum.accumulate(values))),
            bought=sum(r['bought'] for r in matched), primary_bought=sum(r['bought'] for r in matched if r['primary']),
            primary_n=sum(r['primary'] for r in matched), n=len(matched),
            unique_bought=len({(r['code'], r['entry_date']) for r in matched if r['bought']}),
            same_day=sum(r['same_day'] for r in matched), held_on_day=sum(r['held_on_day'] for r in matched),
            human_outcomes=dict(Counter(e['outcome'] for e in own)))
        out[half]['return'] = out[half].pop('return_')
    return out


def accounts(selected, d):
    account_data, px, rules, ema = old.load_account_inputs()
    end = max(d.slices)
    orders = old.selected_orders(account_data, selected, window=(old.panels.WINDOW[0], end))
    book, _, _ = old.hc.make_books(account_data, orders, old.hh.observations(account_data, orders), True)
    meta = dict(days=d.meta['days'], entries=d.entries)
    summaries = {}
    for label, rule in rules.items():
        result = ie7.prior.account(account_data, px, ema[label], rule, book, meta, end=end, detail=True)
        fidelity = old.fill_fidelity(result['trades'], meta)['rows']
        summaries[label] = dict(total=result['total'], maxdd=result['maxdd'],
            periods=period_accounts(result, fidelity, d.entries, d.halves), annual=result['annual'],
            max_close_gross=result['max_close_gross'], max_close_positions=result['max_close_positions'],
            margin_paid=result['margin_paid'], fidelity=fidelity)
        save(WORK / ('account_' + label + '.json'), {k: result[k] for k in ('curve', 'dates', 'trades', 'trade_digest')})
        del result
        gc.collect()
        print('account', label, summaries[label]['total'], flush=True)
    output('accounts', summaries)


def date_sensitivity(d, frozen_ranks):
    audit = read(REPORTS / (PREFIX + 'dates.json'))
    cv = read(REPORTS / (PREFIX + 'true.json'))['cv']
    old_meta = read(ie12.WORK / 'features.json')
    old_ranks = np.load(ie12.WORK / 'final_ranks.npy', mmap_mode='r')
    entries = {e['id']: e for e in d.entries}
    positions = {day: t for t, day in enumerate(d.meta['days'])}
    rows = []
    for row in audit['rows']:
        if row['precision'] != 'chart':
            continue
        own = entries.get(row['id'])
        dates = {row['entry_date'], row['revised_entry_date']}
        t = positions[row['entry_date']]
        for shift in row['review'].get('shifts', []):
            if 0 <= t + shift < len(d.meta['days']):
                dates.add(d.meta['days'][t + shift])
        model = cv['folds'][ie7.half(own['entry_date'])]['model'] if own else None
        fold_ranks = rank_scores(d, model_scores(d, model))[0] if model else None
        cases = []
        for day in sorted(dates):
            entry = dict(code='US.' + row['ticker'], entry_date=day)
            qs = queries([entry], d.meta['days'], d.meta['slices'], d.meta['codes'])[0]
            oq = queries([entry], d.meta['days'], old_meta['slices'], old_meta['codes'])[0]
            rank = min((int(fold_ranks[q]) for q in qs if q >= 0), default=10**6) if model else None
            cases.append(dict(date=day, original=day == row['entry_date'], revised=day == row['revised_entry_date'],
                ie12_rank=min((int(old_ranks[q]) for q in oq if q >= 0), default=10**6),
                ie13_heldout_rank=rank,
                ie13_frozen_rank=min((int(frozen_ranks[q]) for q in qs if q >= 0), default=10**6) if model else None))
        rows.append(dict(id=row['id'], code='US.' + row['ticker'], side=row['side'],
            primary=own['target']['tier'] == 'primary' if own else None,
            status=row['review']['status'], reason=row['review']['reason'], cases=cases))
    output('date_sensitivity', dict(rows=rows, no_refitting=True,
        note='日期敏感性保持原笔目标分层及该笔所属留出折模型不变；只移动评价前四晚，未据命中改日期。空头不进入本段多头覆盖。'))


def final():
    d = Data()
    frozen = read(REPORTS / (PREFIX + 'frozen.json'))
    ranks, selected = rank_scores(d, model_scores(d, frozen['model']))
    np.save(WORK / 'final_ranks.npy', ranks)
    output('final', dict(model=frozen['model'], selected=selected, coverage=summarize(coverage_rows(d, ranks)),
        rows=coverage_rows(d, ranks), nightly_widths={day: sl.stop - sl.start for day, sl in d.slices.items()},
        latest=dict(date=max(d.slices), selected=selected[max(d.slices)])))
    date_sensitivity(d, ranks)
    rng_results = []
    for seed in range(130200, 130230):
        rng = np.random.default_rng(seed)
        random_ranks, _ = rank_scores(d, rng.random(len(d.x)))
        rng_results.append(dict(seed=seed, coverage=summarize(coverage_rows(d, random_ranks))))
    output('random', dict(expected=random_expectation(d), repetitions=rng_results))
    accounts(selected, d)


def read(path):
    return ie7.read(path)


def save(path, value):
    """Stage receipts are immutable; reruns must reuse the saved inputs."""
    if path.exists():
        raise ValueError('IE13 artifact already exists: ' + str(path))
    ie12.prior.old.prior.write_json(path, value)


def output(name, value):
    save(REPORTS / (PREFIX + name + '.json'), value)


def stamp():
    return datetime.now(timezone.utc).isoformat()


def seconds(value):
    parts = value.replace(',', '.').split(':')
    return sum(float(part) * 60 ** i for i, part in enumerate(reversed(parts)))


def source_excerpt(source):
    excerpts = []
    for video, offset in re.findall(r'([\w-]+)@(\d+:\d+:\d+)', source):
        files = sorted((ROOT / 'data/martin-luk-subs').glob(video + '*.vtt'))
        if not files:
            files = sorted((ROOT / 'data/martin-luk-subs').glob(video + '*.txt'))
        if not files:
            excerpts.append(dict(source=video + '@' + offset, missing=True))
            continue
        path, target = files[0], seconds(offset)
        lines, clock, previous = [], -1., None
        for line in path.read_text().splitlines():
            match = re.match(r'\[?(\d+:\d+:\d+[.,]\d+) -->', line)
            text_match = re.match(r'\[(\d+:\d+:\d+)\]\s*(.*)', line)
            if match:
                clock = seconds(match[1])
            elif text_match:
                clock = seconds(text_match[1])
                line = text_match[2]
            elif not line or line.isdigit() or line.startswith(('WEBVTT', 'Kind:', 'Language:')):
                continue
            if match or not target - 45 <= clock <= target + 100:
                continue
            text = html.unescape(re.sub(r'<[^>]+>', '', line)).strip()
            if text and text != previous:
                lines.append(dict(seconds=clock, text=text))
                previous = text
        excerpts.append(dict(source=video + '@' + offset, path=str(path.relative_to(ROOT)), lines=lines))
    return excerpts


def date_audit():
    meta = read(old.WORK / 'prepared.json')
    days = meta['days']
    di = {day: t for t, day in enumerate(days)}
    with LEDGER.open() as stream:
        rows = list(csv.DictReader(stream))
    fields = list(rows[0])
    findings = []
    for row in rows:
        path = old.WORK / 'stocks' / ('US.' + row['ticker'] + '.npz')
        bars = []
        if path.exists() and row['entry_date'] in di:
            with np.load(path) as z:
                c, o, h, l, v = (z[k].astype(float) for k in ('c', 'o', 'h', 'l', 'v'))
            e9, e21 = lib.smooth(c, 9), lib.smooth(c, 21)
            vol = lib.lag(lib.roll(v, 20))
            t = di[row['entry_date']]
            for k in range(max(1, t - 2), min(len(days), t + 3)):
                if not np.isfinite(c[k]):
                    continue
                bars.append(dict(date=days[k], shift=k - t, open=float(o[k]), high=float(h[k]),
                    low=float(l[k]), close=float(c[k]), ema9=float(e9[k]), ema21=float(e21[k]),
                    gain=float(c[k] / c[k - 1] - 1), gap=float(o[k] / c[k - 1] - 1),
                    volume_ratio=float(v[k] / vol[k]) if vol[k] > 0 else None,
                    pdh_break=bool(h[k] > h[k - 1]),
                    inside=bool(h[k] <= h[k - 1] and l[k] >= l[k - 1]),
                    touch9=bool(l[k] <= e9[k] <= h[k]), touch21=bool(l[k] <= e21[k] <= h[k])))
        finding = dict(**row, trading_day=row['entry_date'] in di, bars=bars,
            source_excerpt=source_excerpt(row['source']),
            status='pending_manual_review' if row['precision'] == 'chart' else
                   'window_separate' if row['precision'] == 'window' else 'exact_preserved')
        findings.append(finding)
    save(WORK / 'date_audit_initial.json', dict(utc=stamp(), ledger_sha256=prior.prior.file_sha(LEDGER),
        fields=fields, precision=dict(Counter(r['precision'] for r in rows)), rows=findings))
    print('date audit', len(findings), 'rows', flush=True)


def unknown_code(error, codes):
    tokens = re.findall(r'[A-Za-z][A-Za-z0-9_.\-]*', error)
    return next((code for code in codes if code in tokens or code.removeprefix('US.') in tokens), None)


def fetch_plates():
    directory = WORK / 'plates'
    directory.mkdir(exist_ok=True)
    failed = [read(p) for p in sorted((ie11.WORK / 'plates').glob('batch_*.json')) if read(p)['ret'] != 0]
    if len(failed) != 4:
        raise ValueError('expected exactly the four previously failed batches')
    excluded = {c for batch in failed if (c := unknown_code(batch['error'], batch['codes']))}
    save(directory / 'started.json', dict(utc=stamp(), plan_sha256=prior.prior.file_sha(PLAN),
        previous_batches=[b['batch'] for b in failed], requested=sum(len(b['codes']) for b in failed),
        excluded=sorted(excluded), batch_size=40, spacing_seconds=3.5))
    calls, q, error, last_call = [], None, None, None
    try:
        with socket.create_connection(('127.0.0.1', 11111), timeout=3):
            pass
        join = os.path.join
        def log_join(*parts):
            return str(directory / 'logs') if len(parts) == 2 and parts[1] == '.com.futunn.FutuOpenD/Log' else join(*parts)
        with patch('os.path.join', log_join):
            import futu as ft
        ft.SysConfig.enable_console_log(False)
        q = ft.OpenQuoteContext(host='127.0.0.1', port=11111)
        for original in failed:
            eligible = [c for c in original['codes'] if c not in excluded]
            for a in range(0, len(eligible), 40):
                batch = eligible[a:a + 40]
                while batch:
                    if last_call is not None:
                        time.sleep(max(0., 3.5 - (time.monotonic() - last_call)))
                    last_call = time.monotonic()
                    utc = stamp()
                    ret, frame = q.get_owner_plate(batch)
                    rows = frame.to_dict('records') if ret == ft.RET_OK else []
                    message = None if ret == ft.RET_OK else str(frame)
                    record = dict(call=len(calls), original_batch=original['batch'], utc=utc,
                        codes=batch.copy(), ret=int(ret), rows=rows, error=message)
                    save(directory / f'call_{len(calls):03d}.json', record)
                    calls.append(record)
                    print('plate call', len(calls), 'size', len(batch), 'ret', ret, 'rows', len(rows), flush=True)
                    if ret == ft.RET_OK:
                        break
                    bad = unknown_code(message, batch)
                    if bad is None or not any(word in message.lower() for word in ('未知', 'unknown')):
                        raise RuntimeError(message)
                    excluded.add(bad)
                    batch = [c for c in batch if c != bad]
    except Exception as exc:
        error = type(exc).__name__ + ': ' + str(exc)
    finally:
        if q is not None:
            q.close()
    previous = read(ie11.WORK / 'plates/membership.json')
    members = {k: {g: set(cs) for g, cs in groups.items()} for k, groups in previous['members'].items()}
    for call in calls:
        for row in call['rows']:
            kind = str(row['plate_type']).lower()
            if kind in members:
                members[kind].setdefault(str(row['plate_code']), set()).add(row['code'])
    summary = {}
    for kind, groups in members.items():
        covered = set().union(*groups.values()) if groups else set()
        before = set().union(*map(set, previous['members'][kind].values()))
        summary[kind] = dict(plates=len(groups), securities=len(covered), new_securities=len(covered - before),
            new_memberships=sum(len(cs - set(previous['members'][kind].get(g, []))) for g, cs in groups.items()))
    result = dict(utc=stamp(), error=error, excluded=sorted(excluded), calls=len(calls), summary=summary,
        codes=previous['codes'], members={k: {g: sorted(cs) for g, cs in groups.items()} for k, groups in members.items()})
    save(directory / 'membership.json', result)
    output('plates', {k: v for k, v in result.items() if k not in ('codes', 'members')})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=('init', 'audit', 'dates', 'plates', 'prepare', 'observe', 'register', 'fit', 'freeze', 'final'))
    args = parser.parse_args()
    WORK.mkdir(exist_ok=True)
    dict(init=initialize, audit=date_audit, dates=finalize_dates, plates=fetch_plates,
         prepare=prepare, observe=observe, register=register, fit=fit, freeze=freeze, final=final)[args.stage]()
    print('RSS MiB', resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, flush=True)


if __name__ == '__main__':
    main()
