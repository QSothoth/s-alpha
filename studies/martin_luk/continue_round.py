"""R76+: carry only candidates that improve preregistered goals without worsening behavior gates."""
import hashlib
import json
import math
import sys

from . import measure as M, replicate as R


def objective(st, name='bought_fraction_sum'):
    if name == 'winner_holding_distance':
        return -holding_distance(st)
    if name == '2025_count_distance':
        return -abs(st['behavior']['2025']['n']-940)
    if name == '2025_short_profit_share':
        profit = st['profit_by_calendar_year']['2025']
        share = 0. if profit.get('short_profit') == 0 else profit['short_net_profit_share']
        return -max(.10-share, share-.30, 0.) if share is not None else -math.inf
    if name == '2025_log_distance':
        return -abs(math.log1p(st['by_year']['2025'])-math.log(10.7)) if st['by_year']['2025'] > -1 else -math.inf
    return sum(hits / n for hits, n in st['bought'].values())


def holding_distance(st):
    return sum(abs(st['behavior'][year]['days_win'] - target) for year, target in (('2024', 5), ('2025', 3)))


def failures(st, ref):
    bad = []
    if st['total'] <= st['placebo']['median']:
        bad.append('random_median')
    for metric in ('bought', 'bought_entry_date'):
        for segment in ('select', 'validate'):
            if st[metric][segment][0] < ref[metric][segment][0]:
                bad.append(f'{metric}_{segment}')
    if abs(st['behavior']['2025']['n'] - 940) > abs(ref['behavior']['2025']['n'] - 940):
        bad.append('2025_count_distance')
    for year, target in (('2024', 5), ('2025', 3)):
        h = st['behavior'][year]['days_win']
        ref_h = ref['behavior'][year]['days_win']
        if h is None or abs(h - target) > (abs(ref_h - target) if ref_h is not None else math.inf) + 1e-10:
            bad.append(f'{year}_holding_distance')
    if st['march_start']['2024'] < ref['march_start']['2024'] - 1e-10:
        bad.append('march_start')
    return bad


def run(name):
    path = R.ROUNDS / f'{name}.json'
    spec = json.loads(path.read_text())
    for file, expected in spec.get('data_files', {}).items():
        assert hashlib.sha256((R.luk.ROOT / file).read_bytes()).hexdigest() == expected, file
    assert len(spec['candidates']) <= 5
    assert spec['objective'] in ('bought_fraction_sum', '2025_log_distance', '2025_short_profit_share',
                                '2025_count_distance', 'winner_holding_distance')
    cfg = R.system_config_after(spec['base'][0])
    cfgs = {spec['ref']: cfg, **{k: R.merged(cfg, v) for k, v in spec['candidates'].items()}}
    A = R.us_arrays()
    ledger = R.L.load(R.LEDGER)
    located = {k: [x for x in R.located_longs(A, part) if x[0].dated]
               for k, part in zip(('select', 'validate'), R.L.split(ledger, R.CUTOFF))}
    short_located = {k:R.F.locate([t for t in part if t.side=='short' and t.dated],
                                A['days'],A['codes'],has=A['has'])
                     for k,part in zip(('select','validate'),R.L.split(ledger,R.CUTOFF))}
    out = dict(configs=cfgs, full={}, price_audit={}, objective=spec['objective'],
               spec_sha256=hashlib.sha256(path.read_bytes()).hexdigest(), rejected={})
    if 'data_files' in spec:
        out['data_files'] = spec['data_files']
    for key, config in cfgs.items():
        entries, rules, _, pool = R.build_system(A, config)
        px, ema = M.context(A, pool, rules)
        st, trades = M.summarize(A, px, ema, rules, entries, located, spec['draws'], pool)
        if config.get('trend_phase_groups'):
            st['behavior_by_entry_kind'] = {
                kind:M.behavior([t for t in trades if t['kind'] == kind])
                for kind in sorted({t['kind'] for t in trades})}
        short_actual = {(t['code'],t['entry']) for t in trades if t['side'] < 0}
        st['short_bought_entry_date'] = {
            k:[sum((str(A['codes'][j]),t.entry_date) in short_actual for t,j,_,_ in rows),len(rows)]
            for k,(rows,_) in short_located.items()}
        st['short_missing_panel'] = {k:missing for k,(_,missing) in short_located.items()}
        out['full'][key] = st
        out['price_audit'][key] = M.price_audit(A, trades)
        print(name, key, json.dumps({k: st[k] for k in ('by_year', '2026_jan_jul', 'bought', 'march_start', 'placebo')}),
              'behavior', st['behavior']['2025'], flush=True)
    ref = out['full'][spec['ref']]
    passing = []
    for key, st in out['full'].items():
        if key == spec['ref']:
            continue
        bad = failures(st, ref)
        if objective(st, spec['objective']) <= objective(ref, spec['objective']):
            bad.append('objective_not_improved')
        out['rejected'][key] = bad
        if not bad:
            passing.append(key)
    best = max(passing, key=lambda k: (objective(out['full'][k], spec['objective']), -holding_distance(out['full'][k]),
                                      -abs(math.log1p(out['full'][k]['by_year']['2025']) - math.log(10.7)))) \
        if passing else spec['ref']
    out.update(chosen=best, chosen_config=cfgs[best])
    (R.I.OUT / f'{name.lower()}.json').write_text(json.dumps(out, indent=1, default=float))
    print(name, 'chosen', best, 'rejections', out['rejected'], flush=True)


if __name__ == '__main__':
    run(sys.argv[1])
