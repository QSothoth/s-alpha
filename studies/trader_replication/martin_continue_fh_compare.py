"""Compare FC1 snapshots, including pending exit instructions and precision."""
import json
from pathlib import Path

from studies.trader_replication import martin_continue_du as du
from studies.trader_replication import martin_continue_ei as ei
from studies.trader_replication import martin_continue_fh as fh
from studies.trader_replication.martin_continue_dq import sha


def main():
    root = du.REPORTS
    path = root / 'strong_continue_fh_full.json'
    full = json.loads(path.read_text())
    if full['script_sha256'] != sha(Path(fh.__file__)):
        raise ValueError('FH source differs')
    out = {'full_sha256': sha(path), 'script_sha256': sha(Path(__file__)), 'cutoffs': {}}
    for cutoff in fh.CUTS:
        cut_path = root / f'strong_continue_fh_{cutoff}.json'
        cut = json.loads(cut_path.read_text())
        if (cut['actual_last'] != cutoff or cut['dataset_digest'] != full['dataset_digest'] or
                cut['script_sha256'] != full['script_sha256'] or cut['system_sha256'] != full['system_sha256']):
            raise ValueError('cutoff inputs differ')
        a, b = full['snapshots'][cutoff], cut['snapshots'][cutoff]
        result = ei.compare(a, b)
        result['trail_pending_equal'] = a['trail_pending'] == b['trail_pending']
        result['trail_pending_full'] = a['trail_pending']
        result['trail_pending_cut'] = b['trail_pending']
        result['precision_unknown_full'] = a['precision_unknown']
        result['precision_unknown_cut'] = b['precision_unknown']
        result['passes'] = not (result['identity_days'] or result['price_days'] or
                                not result['trade_identity_equal'] or not result['trail_pending_equal'] or
                                a['precision_unknown'] or b['precision_unknown'])
        out['cutoffs'][cutoff] = {'cut_sha256': sha(cut_path), 'comparison': result}
    target = root / 'strong_continue_fh_compare.json'
    target.write_text(json.dumps(out, ensure_ascii=False, indent=2, allow_nan=False) + '\n')
    print('wrote', target, flush=True)


if __name__ == '__main__':
    main()
