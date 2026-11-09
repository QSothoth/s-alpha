"""Recompute every FJ summary from its saved rows and the frozen market calendar."""
import json
from pathlib import Path

import numpy as np
from studies import trader_data
from studies.trader_replication import martin_continue_du as du
from studies.trader_replication import martin_continue_fj as fj
from studies.trader_replication import panels
from studies.trader_replication.martin_continue_dq import sha


def main():
    root = du.REPORTS
    path = root / 'strong_continue_fj.json'
    data = json.loads(path.read_text())
    if data['script_sha256'] != sha(Path(fj.__file__)):
        raise ValueError('FJ source differs')
    dataset = trader_data.dataset('us', mode='frozen', version='trader-data-v1')
    if dataset.digest() != data['dataset_digest']:
        raise ValueError('dataset differs')
    codes = {s['code'] for s in dataset.stocks()}
    days = sorted({day for code, day, _ in dataset.rows() if code in codes and day <= panels.WINDOW[1]})
    rows = data['rows']
    for row in rows:
        i = row['day_index']
        if days[i] != row['signal_day'] or days[i + 1] != row['entry_day']:
            raise AssertionError('market calendar differs')
    if len(rows) != data['width']['candidates'] or sum(r['selected'] for r in rows) != data['width']['selected']:
        raise AssertionError('candidate counts differ')
    rng = np.random.default_rng(fj.SEED)
    for year in ('2024', '2025', '2026'):
        year_days = [i for i in range(len(days) - 1) if panels.WINDOW[0] <= days[i + 1] <= panels.WINDOW[1]
                     and days[i + 1].startswith(year)]
        for sample in ('all', 'spaced'):
            subset = [r for r in rows if r['year'] == year and (sample == 'all' or r['spaced'])]
            for mode, conditional in (('per_filled', True), ('per_preselected', False)):
                actual = {'groups': fj.group_summary(subset, conditional),
                          'matched': {m: fj.matched(subset, year_days, m, conditional, rng) for m in ('hit3', 'hit5')}}
                if actual != data['results'][year][sample][mode]:
                    raise AssertionError('summary differs ' + year + ' ' + sample + ' ' + mode)
    out = {'fj_sha256': sha(path), 'script_sha256': sha(Path(__file__)),
           'dataset_digest': data['dataset_digest'], 'rows': len(rows), 'all_summaries_reproduced': True}
    target = root / 'strong_continue_fj_verify.json'
    target.write_text(json.dumps(out, ensure_ascii=False, indent=2, allow_nan=False) + '\n')
    print('wrote', target, flush=True)


if __name__ == '__main__':
    main()
