"""EA: original v1 universe, next-open outcomes in fee-inclusive initial risk."""
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import sys

import numpy as np
from studies import trader_data
from studies.trader_data.dataset import Dataset
from studies.trader_replication import martin_continue_du as du
from studies.trader_replication import martin_continue_dw as dw
from studies.trader_replication import martin_continue_dx as dx
from studies.trader_replication import martin_continue_dy as dy
from studies.trader_replication import martin_continue_dz as dz
from studies.trader_replication.martin_continue_dk import next_open_outcome
from studies.trader_replication.martin_continue_dq import ROOT, sha
from studies.trader_replication.martin_list import ema

START, END, CUT = '2024-01-02', '2026-10-15', '2025-09-30'


class LimitedDataset(Dataset):
    market = 'us'

    def __init__(self, base, cutoff):
        self.base, self.cutoff = base, cutoff
        self.base_digest = base.digest()

    @property
    def id(self):
        return self.base.id + '-research-cut-' + self.cutoff

    def stocks(self):
        return self.base.stocks()

    def rule(self):
        return self.base.rule()

    def rows(self):
        for code, day, values in self.base.rows():
            if day <= self.cutoff:
                yield code, day, values

    def actions(self):
        return self.base.actions()

    def digest(self):
        return hashlib.sha256((self.base_digest + ':' + self.cutoff).encode()).hexdigest()


def raw_positions(dataset, days, codes):
    di, ci = {day: i for i, day in enumerate(days)}, {code: j for j, code in enumerate(codes)}
    out = np.full((len(days), len(codes)), np.nan, np.float64)
    for code, day, values in dataset.rows():
        if code in ci and day in di:
            out[di[day], ci[code]] = dw.raw_position(values)
    return out


def main(mode):
    if mode not in ('full', 'cut'):
        raise ValueError('expected full or cut')
    base = trader_data.dataset('us', mode='frozen', version='trader-data-v1')
    ct_path = du.REPORTS / 'strong_continue_ct.json'
    ct = json.loads(ct_path.read_text())
    base_digest = base.digest()
    if base_digest != ct['dataset_digest']:
        raise ValueError('v1 differs from CT')
    ref = {(r['day'], r['code']): r for r in ct['candidates'] if START <= r['day'] <= END}
    if len(ref) != sum(START <= r['day'] <= END for r in ct['candidates']):
        raise ValueError('duplicate CT candidate')
    dataset = LimitedDataset(base, CUT) if mode == 'cut' else base
    d = du.make_data(dataset)
    f, mask, holding = du.compute_fields(d)
    codes = list(map(str, d.A['codes']))
    f_raw = dict(f)
    f_raw['cpos'] = raw_positions(dataset, d.days, codes)
    if mode == 'cut' and d.days[-1] != CUT:
        raise ValueError('not a true cutoff')
    e21 = np.empty(d.c.shape, dtype=np.float32) if mode == 'full' else None
    if e21 is not None:
        for j in range(0, d.c.shape[1], 64):
            sl = slice(j, j + 64)
            e21[:, sl] = ema(d.c[:, sl].astype(float), 21).astype(np.float32)
    last, daily, seen, audit, ambiguous, selected_history = {}, [], set(), {}, [], []
    summaries = defaultdict(lambda: {'risk': [], 'r': []})
    names = defaultdict(set)
    changes = Counter()
    for i in range(1, len(d.days)):
        day = d.days[i]
        sig = du.signature(d, f_raw, mask, holding, i)
        kept = dx.spaced(sig['candidates'], i, last)
        selected_history.extend((int(row[0]), i) for row in kept)
        if START <= day <= CUT:
            audit[day] = {'all': sig, 'spaced': {'active': sig['active'], 'holding': sig['holding'], 'candidates': kept}}
        if mode == 'cut' or not START <= day <= END or i + 1 >= len(d.days):
            continue
        original = du.signature(d, f, mask, holding, i)
        old = {row[0]: row[1] for row in original['candidates']}
        new = {row[0]: row[1] for row in sig['candidates']}
        for j in old.keys() | new.keys():
            if old.get(j) != new.get(j):
                changes['h3' if holding[i, j] else 'other'] += 1
        for j, _, ratio in original['candidates']:
            if not holding[i, j]:
                continue
            key = (day, codes[j])
            entry = ref.get(key)
            if entry is None or entry['fill'] != float(d.c[i, j]) or abs(entry['stop'] - ratio * float(d.c[i, j])) > 1e-10:
                raise AssertionError('CT candidate differs ' + str(key))
            seen.add(key)
        adr = d.adr[i - 1]
        pool = adr[mask[i] & np.isfinite(adr) & (adr > 0)]
        bounds = np.quantile(pool, [1 / 3, 2 / 3]) if len(pool) else None
        cells = {sample: defaultdict(lambda: {'h3': [], 'other': []}) for sample in ('all', 'spaced')}
        totals = {sample: {'h3': Counter(), 'other': Counter()} for sample in ('all', 'spaced')}
        ids = {row[0] for row in kept}
        for j, kind, stop_ratio in sig['candidates']:
            side = 'h3' if holding[i, j] else 'other'
            stop, opening = stop_ratio * float(d.c[i, j]), float(d.A['open'][i + 1, j])
            outcome = next_open_outcome(d.A['open'][:, j], d.A['high'][:, j], d.A['low'][:, j],
                                        d.A['close'][:, j], e21[:, j], i + 1, stop)
            risk, _ = dy.risk_return(opening, stop, outcome)
            uncertain = dz.precision_unknown(opening, stop, outcome)
            cost_risk = dz.fee_risk(opening, stop) if risk is not None else None
            net_r = outcome['ret'] / cost_risk if outcome['ret'] is not None and cost_risk is not None else None
            samples = ('all', 'spaced') if j in ids else ('all',)
            if uncertain:
                ambiguous.append({'day': day, 'code': codes[j], 'side': side, 'opening': opening,
                                  'stop': stop, 'spaced': j in ids, 'status': outcome['status']})
            for sample in samples:
                t = totals[sample][side]
                t['candidates'] += 1
                names[(day[:4], sample, side)].add(codes[j])
                t[outcome['status']] += 1
                t['precision_unknown'] += int(uncertain)
                if not uncertain:
                    obs = summaries[(day[:4], sample, side)]
                    if cost_risk is not None:
                        obs['risk'].append(cost_risk)
                    if net_r is not None:
                        obs['r'].append(net_r)
            if (uncertain or net_r is None or bounds is None or not np.isfinite(adr[j]) or adr[j] <= 0):
                continue
            cell = (kind, int(np.searchsorted(bounds, adr[j], side='right')))
            for sample in samples:
                cells[sample][cell][side].append(net_r)
        daily.append({'date': day, 'entry_date': d.days[i + 1],
                      **{s: {'totals': {side: dict(t) for side, t in totals[s].items()},
                             'matched': dy.compare_r(cells[s])} for s in ('all', 'spaced')}})
        if len(daily) % 100 == 0:
            print('completed signal days', len(daily), flush=True)
    prev = {}
    for j, i in selected_history:
        if j in prev and i - prev[j] < 21:
            raise AssertionError('spacing violation ' + codes[j])
        prev[j] = i
    out = {'dataset_digest': base_digest, 'ct_sha256': sha(ct_path), 'script_sha256': sha(Path(__file__)),
           'codes': codes, 'audit': audit, 'selection_history': selected_history}
    if mode == 'cut':
        full_path = du.REPORTS / 'strong_continue_ea_full.json'
        full = json.loads(full_path.read_text())
        if full['script_sha256'] != out['script_sha256'] or full['dataset_digest'] != out['dataset_digest'] or full['codes'] != codes:
            raise ValueError('full run inputs differ')
        if set(audit) != set(full['audit']):
            raise AssertionError('audit dates differ')
        out['cutoff_differences'] = {sample: dw.compare_signals({k: v[sample] for k, v in full['audit'].items()},
                                                               {k: v[sample] for k, v in audit.items()})
                                     for sample in ('all', 'spaced')}
        out['full_sha256'] = sha(full_path)
        target = du.REPORTS / 'strong_continue_ea_cut.json'
    else:
        if seen != set(ref):
            raise AssertionError('CT reference identities differ: ' + str(len(set(ref) - seen)))
        rng, years = np.random.default_rng(20261101), {}
        for year in ('2024', '2025', '2026'):
            rows = [r for r in daily if r['date'].startswith(year)]
            state = rng.bit_generator.state
            years[year] = {}
            for sample in ('all', 'spaced'):
                counts = {}
                for side in ('h3', 'other'):
                    t = Counter()
                    for row in rows:
                        t.update(row[sample]['totals'][side])
                    counts[side] = dict(t)
                    counts[side]['unique_codes'] = len(names[(year, sample, side)])
                rng.bit_generator.state = state
                years[year][sample] = {'totals': counts, 'groups': {side: dy.describe(**summaries[(year, sample, side)])
                                                                    for side in ('h3', 'other')},
                                       'matched': du.blocks([{'matched': r[sample]['matched']} for r in rows], rng)}
        out.update({'ct_candidates_verified': len(seen), 'source_position_changes': dict(changes),
                    'ambiguities': ambiguous, 'daily': daily, 'years': years})
        target = du.REPORTS / 'strong_continue_ea_full.json'
    with target.open('w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
        f.write('\n')
    print('wrote', target, flush=True)


if __name__ == '__main__':
    main(sys.argv[1])
