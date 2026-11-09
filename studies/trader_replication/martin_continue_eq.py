"""EQ: compare fixed EP raw-row cutoff account snapshots."""
import json
from pathlib import Path

from studies.trader_replication import martin_continue_du as du
from studies.trader_replication import martin_continue_ei as ei
from studies.trader_replication import martin_continue_ep as ep
from studies.trader_replication.martin_continue_dq import sha


def main():
    full_path = du.REPORTS / 'strong_continue_ep_full.json'
    full = json.loads(full_path.read_text())
    if full['script_sha256'] != sha(Path(ep.__file__)) or not full['original_peer_replayed']:
        raise ValueError('EP source differs or original peer replay failed')
    out = {'ep_full_sha256': sha(full_path), 'script_sha256': sha(Path(__file__)), 'cutoffs': {}}
    for day in ep.CUTS:
        path = du.REPORTS / f'strong_continue_ep_{day}.json'
        cut = json.loads(path.read_text())
        if (cut['dataset_digest'] != full['dataset_digest'] or cut['script_sha256'] != full['script_sha256']
                or cut['ef_sha256'] != full['ef_sha256'] or cut['actual_last'] != day or not cut['original_peer_replayed']):
            raise ValueError('EP cutoff input differs')
        out['cutoffs'][day] = {'cut_sha256': sha(path), 'ash_adr': cut['ash_adr'],
                               'systems': {name: ei.compare(full['snapshots'][name][day], cut['snapshots'][name][day])
                                           for name in ('U1', 'SAT6')}}
    target = du.REPORTS / 'strong_continue_eq.json'
    with target.open('w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=2, allow_nan=False)
        f.write('\n')
    print('wrote', target, flush=True)


if __name__ == '__main__':
    main()
