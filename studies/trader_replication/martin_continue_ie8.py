"""IE8: freeze a retention gate before testing small-pool equal-rank scores."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import resource
import sys

import numpy as np

from studies.trader_replication import martin_continue_ie7 as ie7

prior, old = ie7.prior, ie7.old
ROOT, REPORTS = ie7.ROOT, ie7.REPORTS
WORK = REPORTS / 'ie8_work'
PREFIX = 'strong_continue_ie8_'
PLAN = ROOT / 'studies/martin_luk/notes/PLAN_IE8_CN.md'
PREREG = ROOT / 'studies/martin_luk/notes/PREREG_IE8_CN.md'
YEARS, HALVES, TOPS = ie7.YEARS, ie7.HALVES, ie7.TOPS
SEED = 20261108
CUTOFFS = (.5, .6, .7, .8, .9)


def read(name):
    return ie7.read(REPORTS / (PREFIX + name + '.json'))


def write(name, value):
    old.prior.write_json(REPORTS / (PREFIX + name + '.json'), value)


def stable_features():
    return ie7.stable_rows(ie7.read(REPORTS / (ie7.PREFIX + 'true_description.json'))['primary'])


def validate(scheme):
    directions = {r['name']: r['direction'] for r in stable_features()}
    if len(scheme['gates']) > 4 or len(scheme['factors']) > 5:
        raise ValueError('IE8 complexity limit')
    for field in ('gates', 'factors'):
        if len({r['name'] for r in scheme[field]}) != len(scheme[field]):
            raise ValueError('duplicate feature in ' + field)
        for item in scheme[field]:
            if directions.get(item['name']) != item['direction']:
                raise ValueError('feature or direction outside the IE7 stable whitelist')
            if field == 'gates' and item['cutoff'] not in CUTOFFS:
                raise ValueError('gate threshold must be a registered common percentile')


def gate_mask(pct, names, gates):
    passed = np.ones(len(pct), bool)
    for gate in gates:
        p = pct[:, names.index(gate['name'])]
        oriented = p if gate['direction'] > 0 else 1 - p
        passed &= np.isfinite(p) & (oriented + 1e-7 >= gate['cutoff'])
    return passed


def rank_night(raw, pct, names, scheme):
    """The only inputs are the current night's cached numerical observations."""
    passed = gate_mask(pct, names, scheme['gates'])
    kept = np.flatnonzero(passed)
    score = np.zeros(len(kept), np.float32)
    for factor in scheme['factors']:
        j = names.index(factor['name'])
        p = (ie7.night_percentiles(raw[kept, j:j + 1])[:, 0]
             if scheme.get('rank_scope', 'small') == 'small' else pct[kept, j])
        p = np.where(np.isfinite(p), p, .5)
        score += p if factor['direction'] > 0 else 1 - p
    if scheme['factors']:
        score /= len(scheme['factors'])
    order = kept[np.argsort(-score, kind='stable')]
    ranks = np.full(len(raw), old.prior.SENTINEL, np.int32)
    ranks[order] = np.arange(1, len(order) + 1)
    return order, ranks, passed


def width_summary(widths):
    result = {}
    for year in (*YEARS, '2026', 'combined'):
        values = [v for day, v in widths.items()
                  if day[:4] in YEARS] if year == 'combined' else [v for day, v in widths.items() if day.startswith(year)]
        if values:
            result[year] = dict(n=len(values), minimum=min(values), q25=float(np.percentile(values, 25)),
                median=float(np.median(values)), q75=float(np.percentile(values, 75)), maximum=max(values),
                empty=sum(v == 0 for v in values), top5_fraction=5 / float(np.median(values)) if np.median(values) else None)
    return result


def retention(entries, query, passed, widths):
    rows = []
    for e, qs in zip(entries, query):
        if e['target']['tier'] != 'primary':
            continue
        valid = [q for q in qs if q >= 0]
        rows.append(dict(id=e['id'], entry_date=e['entry_date'], in_scope=bool(valid),
                         retained=any(passed[q] for q in valid)))
    annual = {}
    for year in YEARS:
        sample = [r for r in rows if r['entry_date'].startswith(year)]
        scope, kept = sum(r['in_scope'] for r in sample), sum(r['retained'] for r in sample)
        annual[year] = dict(n=len(sample), scope=scope, kept=kept,
                           in_scope_rate=kept / scope if scope else 0., full_rate=kept / len(sample) if sample else 0.)
    minimum = min(r['in_scope_rate'] for r in annual.values())
    return dict(annual=annual, rows=rows, minimum_retention=minimum, feasible=minimum >= .9,
                width=width_summary(widths))


def gate_key(result):
    r = result['retention']
    width = r['width']
    return (r['feasible'], 0 if r['feasible'] else r['minimum_retention'],
            -width['combined']['median'], -max(width[y]['median'] for y in YEARS),
            -len(result['scheme']['gates']))


def ranking_winner(results):
    allowed = [r for r in results if r['eligible']]
    if not allowed:
        raise ValueError('no scheme passes the fixed account vetoes')
    return max(allowed, key=ie7.coverage_key)


class Data(ie7.Data):
    def __init__(self, full=False, shuffled=False):
        super().__init__(full=full)
        self.label = 'shuffle' if shuffled else 'true'
        if shuffled:
            rng = np.random.default_rng(SEED)
            mapping = {day: rng.permutation(sl.stop - sl.start) for day, sl in self.slices.items()}
            self.query = [[self.slices[event['date']].start + int(mapping[event['date']][q - self.slices[event['date']].start])
                           if q >= 0 else -1 for event, q in zip(e['systems']['h4'], qs)]
                          for e, qs in zip(self.entries, self.query)]

    def select(self, scheme):
        pct = self.percentiles()
        ranks = np.full(self.n, old.prior.SENTINEL, np.int32)
        passed = np.zeros(self.n, bool)
        selected, widths = {}, {}
        for day, sl in self.slices.items():
            if day < self.meta['first_signal']:
                continue
            order, ranks[sl], passed[sl] = rank_night(self.raw[sl], pct[sl], self.names, scheme)
            selected[day] = [self.meta['scope'][day][k] for k in order[:5]]
            widths[day] = len(order)
        return selected, widths, ie7.coverage(self.entries, self.query, ranks, passed)

    def gate_evaluate(self, scheme):
        pct = self.percentiles()
        passed = gate_mask(pct[:self.n], self.names, scheme['gates'])
        widths = {day: int(np.count_nonzero(passed[sl])) for day, sl in self.slices.items()
                  if day >= self.meta['first_signal']}
        return dict(scheme=scheme, retention=retention(self.entries, self.query, passed, widths))

    def evaluate(self, scheme, label=None):
        key = prior.digest(dict(scheme=scheme, end=self.end, label=self.label))
        path = WORK / 'evaluations' / (key + '.json')
        if path.exists():
            return ie7.read(path)
        selected, widths, c = self.select(scheme)
        account_key = prior.digest(dict(selected=selected, end=self.end))
        cache = WORK / 'accounts' / (account_key + '.json')
        accounts = ie7.read(cache) if cache.exists() else self.accounts(selected)
        if not cache.exists():
            old.prior.write_json(cache, accounts)
        ok, failures = ie7.eligible(accounts)
        result = dict(scheme=scheme, coverage=c, accounts=accounts, eligible=ok, failures=failures,
                      selection_hash=account_key, selected=selected, nightly_widths=widths, width=width_summary(widths))
        result['score'] = list(ie7.coverage_key(result))
        result['losses'] = ie7.losses(result)
        old.prior.write_json(path, result)
        return result


def description_stage(d=None, name='gate_description'):
    d = d or Data()
    rows = []
    for feature in stable_features():
        for cutoff in CUTOFFS:
            gate = dict(name=feature['name'], direction=feature['direction'], cutoff=cutoff)
            result = d.gate_evaluate(dict(id=feature['name'] + ':' + str(cutoff), gates=[gate], factors=[]))
            rows.append(result)
    baseline = d.gate_evaluate(dict(id='scope_upper_bound', gates=[], factors=[]))
    result = dict(features=len(stable_features()), rows=rows, baseline=baseline,
                  note='范围内留住率衡量门禁误伤；全主目标留住率同时报告，不隐去范围损失。')
    write(name, result)
    for row in rows:
        r = row['retention']
        print(row['scheme']['id'], [(y, a['kept'], a['scope'], r['width'][y]['median']) for y, a in r['annual'].items()], flush=True)
    return result


def registration(layer, number):
    path = WORK / f'{layer}_round{number}.json'
    spec = ie7.read(path)
    if not 1 <= number <= 3 or not 1 <= len(spec['schemes']) <= 5:
        raise ValueError('round budget exceeded')
    if layer == 'rank':
        frozen = read('frozen_gates')
        for scheme in spec['schemes']:
            if scheme['gates'] != frozen['final']['scheme']['gates'] or scheme.get('rank_scope') != 'small':
                raise ValueError('ranking must use frozen gates and small-pool percentiles')
        if number > 1:
            previous = read(f'rank_round{number - 1}')
            if spec['target_layer'] != previous['winner']['losses']['largest']:
                raise ValueError('next round must address the largest funnel loss')
    for scheme in spec['schemes']:
        validate(scheme)
        if layer == 'gate' and scheme['factors']:
            raise ValueError('first-layer selection cannot use ranking')
    value = dict(spec=spec, spec_sha256=prior.file_sha(path), prereg_sha256=prior.file_sha(PREREG),
                 prereg_text=PREREG.read_text(encoding='utf-8'), plan_sha256=prior.file_sha(PLAN),
                 utc=datetime.now(timezone.utc).isoformat())
    write(f'{layer}_round{number}_registration', value)
    return value


def run_round(layer, number):
    reg = registration(layer, number)
    d = Data()
    results = []
    for scheme in reg['spec']['schemes']:
        result = d.gate_evaluate(scheme) if layer == 'gate' else d.evaluate(scheme)
        results.append(result)
        print(scheme['id'], result.get('score', result.get('retention')), flush=True)
    best = max(results, key=gate_key) if layer == 'gate' else ranking_winner(results)
    write(f'{layer}_round{number}', dict(registration=reg, results=results, winner=best))
    print('WINNER', best['scheme']['id'], flush=True)


def freeze_gates():
    rounds = [ie7.read(p) for p in sorted(REPORTS.glob(PREFIX + 'gate_round[123].json'))]
    best = max((r for rd in rounds for r in rd['results']), key=gate_key)
    write('frozen_gates', dict(final=best, utc=datetime.now(timezone.utc).isoformat(),
                              plan_sha256=prior.file_sha(PLAN), prereg_sha256=prior.file_sha(PREREG)))
    print('GATES FROZEN', best['scheme'], best['retention'], flush=True)


def ablate(d, start):
    current, rounds = start, []
    while True:
        trials, removed = [], False
        for field in ('gates', 'factors'):
            for k, item in enumerate(current['scheme'][field]):
                scheme = json.loads(json.dumps(current['scheme']))
                del scheme[field][k]
                scheme['id'] = current['scheme']['id'] + '-' + field + str(k)
                after = d.evaluate(scheme)
                accept = after['eligible'] and after['score'][0] >= current['score'][0]
                trials.append(dict(field=field, removed=item, result=after, accepted=accept))
                if accept:
                    current, removed = after, True
                    break
            if removed:
                break
        rounds.append(dict(trials=trials))
        if not removed:
            break
    return dict(initial=start, rounds=rounds, final=current)


def ablation_stage():
    rounds = [ie7.read(p) for p in sorted(REPORTS.glob(PREFIX + 'rank_round[123].json'))]
    result = ablate(Data(), ranking_winner([r for rd in rounds for r in rd['results']]))
    write('ablation', result)
    print('ABLATION', result['final']['scheme'], result['final']['score'], flush=True)


def shuffle_stage():
    d = Data(shuffled=True)
    description = description_stage(d, 'shuffle_gate_description')
    gate_results = [d.gate_evaluate(s) for p in sorted(WORK.glob('gate_round[123].json'))
                    for s in ie7.read(p)['schemes']]
    gate_best = max(gate_results, key=gate_key)
    rank_results = []
    for path in sorted(WORK.glob('rank_round[123].json')):
        for original in ie7.read(path)['schemes']:
            scheme = dict(original, gates=gate_best['scheme']['gates'])
            rank_results.append(d.evaluate(scheme))
    result = ablate(d, ranking_winner(rank_results))
    write('shuffle', dict(seed=SEED, gate_description_rows=len(description['rows']),
        gate_results=gate_results, frozen_gates=gate_best, rank_results=rank_results, ablation=result,
        final=result['final'], gate_feasible=gate_best['retention']['feasible'],
        note='沿用任务书限定的IE7稳定白名单及真标签登记结构；不按打乱结果新增结构。无90%可行门禁时按预登记最高留住率回退并标明失败。'))
    print('SHUFFLE', gate_best['retention']['feasible'], result['final']['score'], flush=True)


def freeze():
    final = read('ablation')['final']
    write('frozen_selection', dict(final=final, selection_years=list(YEARS),
        freeze_utc=datetime.now(timezone.utc).isoformat(), exam_used_for_selection=False,
        plan_sha256=prior.file_sha(PLAN), prereg_sha256=prior.file_sha(PREREG),
        source_sha256=prior.file_sha(Path(__file__))))


def final_stage():
    if (REPORTS / (PREFIX + 'final.json')).exists():
        raise ValueError('final already evaluated; reuse the saved artifact')
    frozen = read('frozen_selection')
    d = Data(full=True)
    result = d.evaluate(frozen['final']['scheme'])
    full_scheme = dict(frozen['final']['scheme'], rank_scope='full')
    selected, widths, coverage = d.select(full_scheme)
    result['pre_gate_rank_comparison'] = dict(scheme=full_scheme, coverage=coverage, nightly_widths=widths,
                                             selected=selected, note='只比较排名，不重跑或选择账户。')
    if frozen['final']['selected'] != {day: codes for day, codes in result['selected'].items() if day <= prior.TRAIN_END}:
        raise AssertionError('future rows changed historical selections')
    result['note'] = '2026已看过三次，不是干净的考试；冻结后仅报告一次，不用于选择。'
    result['frozen_sha256'] = prior.file_sha(REPORTS / (PREFIX + 'frozen_selection.json'))
    write('final', result)
    print('FINAL', result['coverage']['annual']['2026']['primary'], flush=True)


def guard():
    def allowed(path):
        p = Path(os.fsdecode(path)).resolve()
        return p.is_relative_to(WORK.resolve()) or (p.parent == REPORTS.resolve() and p.name.startswith(PREFIX))

    def audit(event, args):
        if event == 'open':
            path, _, flags = args
            if not isinstance(path, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND) and not allowed(path):
                raise PermissionError('IE8 output boundary: ' + os.fsdecode(path))
        if event in ('socket.connect', 'socket.bind', 'os.system', 'subprocess.Popen'):
            raise PermissionError('IE8 offline single process')
        if event in ('os.remove', 'os.rename', 'os.rmdir', 'os.mkdir'):
            paths = args[:2] if event == 'os.rename' else args[:1]
            if any(not allowed(p) for p in paths):
                raise PermissionError('IE8 output boundary')
    sys.addaudithook(audit)


def main(stage):
    WORK.mkdir(exist_ok=True)
    for name in ('evaluations', 'accounts'):
        (WORK / name).mkdir(exist_ok=True)
    guard()
    if stage == 'describe':
        description_stage()
    elif stage[:4] in ('gate', 'rank') and stage[-1].isdigit():
        run_round(stage[:-1], int(stage[-1]))
    else:
        dict(freeze_gates=freeze_gates, ablate=ablation_stage, shuffle=shuffle_stage,
             freeze=freeze, final=final_stage)[stage]()
    write('runtime_' + stage, dict(completed_utc=datetime.now(timezone.utc).isoformat(),
        plan_sha256=prior.file_sha(PLAN), prereg_sha256=prior.file_sha(PREREG),
        source_sha256=prior.file_sha(Path(__file__)), peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('stage', choices=('describe', 'gate1', 'gate2', 'gate3', 'freeze_gates',
        'rank1', 'rank2', 'rank3', 'ablate', 'shuffle', 'freeze', 'final'))
    main(parser.parse_args().stage)
