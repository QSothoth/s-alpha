"""EK: compare fixed EJ quarter-end snapshots."""
import json
from pathlib import Path

from studies.trader_replication import martin_continue_du as du
from studies.trader_replication import martin_continue_ei as ei
from studies.trader_replication import martin_continue_ej as ej
from studies.trader_replication.martin_continue_dq import sha


def main():
    full_path = du.REPORTS / 'strong_continue_ej_full.json'
    full = json.loads(full_path.read_text())
    if full['script_sha256'] != sha(Path(ej.__file__)):
        raise ValueError('EJ source differs')
    cuts = {}
    for day in ej.CUTS:
        path = du.REPORTS / f'strong_continue_ej_{day}.json'
        cut = json.loads(path.read_text())
        if (cut['dataset_digest'] != full['dataset_digest'] or cut['script_sha256'] != full['script_sha256']
                or cut['ef_sha256'] != full['ef_sha256'] or cut['actual_last'] != day):
            raise ValueError('EJ cutoff inputs differ')
        cuts[day] = {'cut_sha256': sha(path), 'systems': {name: ei.compare(full['snapshots'][name][day],
                                                                           cut['snapshots'][name][day])
                                                          for name in ('U1', 'SAT6')}}
    out = {'ej_full_sha256': sha(full_path), 'script_sha256': sha(Path(__file__)), 'cutoffs': cuts}
    target = du.REPORTS / 'strong_continue_ek.json'
    with target.open('w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=2, allow_nan=False)
        f.write('\n')
    print('wrote', target, flush=True)


if __name__ == '__main__':
    main()
