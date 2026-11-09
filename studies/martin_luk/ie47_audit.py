"""Export IE47's existing parameters and audit its common-data selection, without refitting."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import resource
import shutil
import time

import numpy as np

from studies import trader_data as TD
from studies.trader_data import panel, supplemental as SP
from studies.trader_replication import mainleg
from . import ie47_e1 as M

ROOT = Path(__file__).resolve().parents[2]
GAP = ROOT / 'studies/trader_replication/reports/gap_review'
WORK = Path(__file__).resolve().parent / 'reports/e1_work'
REPORT = WORK.parent / 'e1_selection.json'
T0 = time.monotonic()


def progress(message):
    free = shutil.disk_usage(ROOT).free
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024
    if free < 3_000_000_000 or rss >= 1_500_000_000:
        raise RuntimeError(f'resource limit: disk_free={free}, peak_rss={rss}')
    print(f'[{time.monotonic()-T0:.0f}s] {message}; peak={rss//1024//1024} MiB', flush=True)


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=1, default=lambda x: x.item())+'\n', encoding='utf-8')


def legacy():
    """Read only the existing research row layout and labels, for parameter recovery and audit."""
    meta = json.loads((GAP / 'ie5_work/prepared.json').read_text())
    frozen = json.loads((GAP / 'strong_continue_ie4_frozen.json').read_text())
    names = frozen['raw_feature_names']
    pct = np.load(GAP / 'ie7_work/full_pct.npy', mmap_mode='r')
    gate_columns = [names.index(name) for name, _ in M.GATES]
    cal = meta['days']
    di = {d: t for t, d in enumerate(cal)}
    rows, row_t, keys, offset, slices = [], [], [], 0, {}
    for day, codes in sorted(meta['scope'].items()):
        sl = slice(offset, offset+len(codes))
        slices[day] = sl
        offset = sl.stop
        if day < meta['first_signal']:
            continue
        values = pct[sl][:, gate_columns]
        passed = np.ones(len(codes), bool)
        for k, (_, cutoff) in enumerate(M.GATES):
            passed &= np.where(np.isfinite(values[:, k]), values[:, k] >= cutoff, k == 0)
        selected = [codes[k] for k in np.flatnonzero(passed)]
        rows.append((day, selected))
        row_t.extend([di[day]] * len(selected))
        keys.extend((code, di[day]) for code in selected)
    with np.load(GAP / 'ie40_work/pool_standard_v1_1.npz') as z:
        indicator_names, x = z['names'].tolist(), z['x']
        signature = str(z['signature'])
    if x.shape[1] != len(keys):
        raise ValueError('legacy row layout differs from IE47 training matrix')
    prices = {}
    for code in {e['code'] for e in meta['entries']}:
        with np.load(GAP / 'ie5_work/stocks' / (code+'.npz')) as z:
            prices[code] = {k: z[k].astype(float) for k in ('o', 'h', 'l', 'c')}
    entries = [(e['code'], di[e['entry_date']], e['id']) for e in meta['entries']]
    legs = mainleg.legs(entries, prices)
    return dict(meta=meta, keys=keys, row_t=np.array(row_t), rows=rows, names=names, slices=slices,
                indicator_names=indicator_names, x=x, signature=signature, prices=prices, legs=legs)


def export_profile():
    """Recover precise tables for the already chosen nine terms; never run a model search."""
    old = legacy()
    fit = json.loads((GAP / 'ie47_work/fit.json').read_text())
    if fit['config']['unimodal']:
        raise ValueError('this IE47 export expects its saved non-unimodal tables')
    days = old['meta']['days']
    mask = np.array([days[t][:4] in ('2024', '2025') for t in old['row_t']])
    lookup = {key: r for r, key in enumerate(old['keys'])}
    qqq = np.load(GAP / 'ie5_work/qqq.npy')
    regime = M.regimes(qqq)[old['row_t']]
    train = [leg for leg in old['legs'] if days[leg['entries'][0]['index']][:4] in ('2024', '2025')]
    tables = {}
    for part, model in (('shared', fit['model']['shared']), *fit['model']['corrections'].items()):
        pool_mask = mask & (True if part == 'shared' else regime == (0 if part == 'up' else 1))
        groups = []
        for leg in train:
            first = leg['entries'][0]['index']
            group = [lookup[(leg['code'], first+w)] for w in (0, 1, 2)
                     if (leg['code'], first+w) in lookup and pool_mask[lookup[(leg['code'], first+w)]]]
            if group:
                groups.append(group)
        tables[part] = []
        for item in model:
            x = old['x'][old['indicator_names'].index(item['name'])]
            source = x[mask]
            unique = np.unique(source[np.isfinite(source)])
            edges = ((unique[:-1]+unique[1:])/2 if len(unique) <= 3 else
                     np.unique(np.nanquantile(source, np.linspace(0, 1, item['bins']+1)[1:-1])))
            bins = np.where(np.isfinite(x), np.searchsorted(edges, x, side='right'), len(edges)+1)
            nb = len(edges)+2
            pool = np.bincount(bins[pool_mask], minlength=nb).astype(float)
            his = np.zeros(nb)
            for group in groups:
                np.add.at(his, bins[group], 1/len(group))
            pool[-1] = his[-1] = 0
            ps = pool/pool.sum()
            prior = his.sum()/(nb-1)
            hs = (his+prior*ps)/(his.sum()+prior)
            scores = np.where(pool > 0, np.log(np.where(pool > 0, hs, 1)/np.where(pool > 0, ps, 1)), 0).astype(np.float32)
            displayed = [r['score'] for r in fit['profile'][part][item['name']]['bins']]
            # fit.json omits empty bins, including missing; check every displayed score.
            counts = np.bincount(bins[pool_mask], minlength=nb)
            restored = [round(float(scores[k]), 2) for k in range(nb) if counts[k]]
            if restored != displayed:
                raise AssertionError((part, item['name'], restored, displayed))
            tables[part].append(dict(item, edges=edges.tolist(), scores=scores.tolist(), targets=len(groups)))
    sources = ['studies/trader_replication/martin_profile_ie29.py',
               'studies/trader_replication/martin_profile_ie42.py',
               'studies/trader_replication/standard_indicators.py',
               'studies/trader_replication/martin_continue_ie5.py',
               'studies/trader_replication/martin_continue_ie9.py',
               'studies/trader_replication/mainleg.py',
               'studies/trader_replication/reports/gap_review/ie47_work/fit.json',
               'studies/trader_replication/reports/gap_review/ie47_work/agree.json',
               'studies/trader_replication/reports/gap_review/ie47_work/scorecard.json',
               'studies/trader_replication/reports/gap_review/ie5_work/prepared.json',
               'studies/trader_replication/reports/gap_review/ie40_work/pool_standard_v1_1.npz']
    out = dict(version='IE47', fit_years=['2024', '2025'], library='standard_indicators v1.1',
               first_signal=old['meta']['first_signal'], cooldown=fit['config']['cooldown'], max_picks=3,
               gates=[dict(name=n, cutoff=c, missing_pass=n == 'h4_history') for n, c in M.GATES],
               regime_rule=fit['regime_rule'], missing_score=0, stable_ties='code ascending', tables=tables,
               source_sha256={p: SP.sha(ROOT/p) for p in sources}, matrix_signature=old['signature'],
               original_library_sha256=json.loads((WORK/'before.json').read_text())[
                   'studies/trader_replication/standard_indicators.py'], dataset_digest=old['meta']['dataset_digest'])
    if M.PROFILE.exists():
        if json.loads(M.PROFILE.read_text()) != out:
            raise ValueError('profile already exists with different provenance or parameters; do not overwrite')
    else:
        write(M.PROFILE, out)
        M.PROFILE.chmod(0o444)
    progress('exported existing profile; all nine rounded tables match fit.json')
    return out


def scorecard(result, p, old):
    """The exact three existing yardsticks; selection research's 2026 is only reproduced here."""
    days, codes = list(map(str, p['days'])), list(map(str, p['codes']))
    di = {d: t for t, d in enumerate(days)}
    prices = {code: {k: p[v][:, j] for k, v in (('o', 'open'), ('h', 'high'), ('l', 'low'), ('c', 'close'))}
              for j, code in enumerate(codes)}
    entries = [(e['code'], di[e['entry_date']], e['id']) for e in old['meta']['entries'] if e['entry_date'] in di]
    legs = mainleg.legs(entries, prices)
    buys = {di[day]: names for day, names in result['picks'].items()}
    pool = {(str(codes[j]), t) for t, kept in zip(result['night_indices'], result['kept']) for j in kept}
    rows = mainleg.coverage(buys, legs, prices, pool=pool)
    nets = mainleg.net_share(buys, mainleg.windows(legs, prices), pool)
    out = {}
    for year in ('2024', '2025', '2026'):
        indices = [i for i, leg in enumerate(legs) if days[leg['entries'][0]['index']][:4] == year]
        if not indices:
            continue
        fw = mainleg.forward({t: v for t, v in buys.items() if days[t][:4] == year}, prices)
        net = [nets[i] for i in indices if nets[i] is not None]
        out[year] = dict(covered=f"{sum(rows[i]['covered'] for i in indices)}/{len(indices)}",
                         net=round(float(np.median(net))*100), run_median=round(fw['median']*100, 1),
                         ge100=round(fw['ge100']*100, 1), runs=fw['n'])
    return out


def audit(cut=None):
    old = legacy()
    ds = TD.dataset('us', 'frozen')
    p = panel.build(ds, upto=cut, write_cache=False)
    result = M.selection(p, ds, profile=json.loads(M.PROFILE.read_text()), progress=progress)
    cal = list(map(str, p['days']))
    codes = list(map(str, p['codes']))
    expected = json.loads((GAP/'ie47_work/scorecard.json').read_text())['profile']
    raw = np.load(GAP/'ie5_work/raw.npy', mmap_mode='r')
    columns = [old['names'].index(name) for name, _ in M.GATES]
    row_lookup = {key: r for r, key in enumerate(old['keys'])}
    source_kept = dict(old['rows'])
    reasons, differences, raw_diff = {}, [], {name: 0 for name, _ in M.GATES}
    for t, scope, kept, actual_raw in zip(result['night_indices'], result['scopes'], result['kept'], result['raw']):
        day = cal[t]
        want = expected['picks'].get(day, [])
        actual = result['picks'][day]
        problems = []
        if [codes[j] for j in scope] != old['meta']['scope'].get(day, []):
            problems.append('scope')
        if [codes[j] for j in kept] != source_kept.get(day, []):
            problems.append('filter')
        reference_raw = raw[old['slices'][day]][:, columns]
        if reference_raw.shape == actual_raw.shape:
            for k, (name, _) in enumerate(M.GATES):
                raw_diff[name] += int(np.count_nonzero(~np.isclose(actual_raw[:, k], reference_raw[:, k],
                                                                  rtol=1e-6, atol=1e-8, equal_nan=True)))
        if actual != want:
            if not problems:
                problems.append('indicators_score_or_cooldown')
            differences.append(dict(day=day, expected=want, actual=actual, causes=problems))
        for problem in problems:
            reasons[problem] = reasons.get(problem, 0)+1
    feature_diff = {}
    for name, value in result['values'].items():
        expected_values = old['x'][old['indicator_names'].index(name)]
        pairs = [(r, row_lookup[(codes[j], t)]) for r, (t, j) in enumerate(zip(result['row_t'], result['row_j']))
                 if (codes[j], t) in row_lookup]
        a, b = np.array(pairs, int).T
        mismatch = ~np.isclose(value[a], expected_values[b], rtol=1e-6, atol=1e-7, equal_nan=True)
        feature_diff[name] = dict(compared=len(a), different=int(mismatch.sum()))
    nights = len(result['picks'])
    out = dict(cut=cut, nights=nights, exact_nights=nights-len(differences),
               ordered_exact_rate=1-len(differences)/nights,
               set_exact_rate=float(np.mean([set(v) == set(expected['picks'].get(d, [])) for d, v in result['picks'].items()])),
               reasons=reasons, differences=differences, raw_differences=raw_diff, indicator_differences=feature_diff,
               data_digest=p['digest'], profile_sha256=SP.sha(M.PROFILE), sources=result['sources'])
    if cut is None:
        out['scorecard'] = scorecard(result, p, old)
        out['reference_scorecard'] = {y: expected[y] for y in ('2024', '2025', '2026')}
        out['scorecard_equal'] = out['scorecard'] == out['reference_scorecard']
        write(REPORT, out)
        write(WORK/'picks.json', result['picks'])
        np.savez_compressed(WORK/'selection.npz', row_t=result['row_t'], row_j=result['row_j'],
                            **result['values'], scores=result['scores'])
    else:
        full_picks = json.loads((WORK/'picks.json').read_text())
        out['prefix_equal'] = result['picks'] == {d: v for d, v in full_picks.items() if d <= cut}
        write(WORK/f'selection_cut_{cut}.json', out)
    progress(f"audit complete: {out['exact_nights']}/{nights} nights; {out['reasons']}")
    return out


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('stage', choices=('export', 'audit'))
    parser.add_argument('--cut')
    args = parser.parse_args()
    WORK.mkdir(exist_ok=True)
    resource.setrlimit(resource.RLIMIT_AS, (1_500_000_000, 1_500_000_000))
    if args.stage == 'export':
        export_profile()
    else:
        audit(args.cut)
