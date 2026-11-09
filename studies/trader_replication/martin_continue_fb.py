"""FB: compare the registered DG1 full and raw-row-cutoff snapshots."""
import json
from pathlib import Path

from studies.trader_replication import martin_continue_du as du
from studies.trader_replication import martin_continue_ei as ei
from studies.trader_replication import martin_continue_fa as fa
from studies.trader_replication.martin_continue_dq import sha


def main():
    root = du.REPORTS
    full_path = root / 'strong_continue_fa_full.json'
    full = json.loads(full_path.read_text())
    if full['script_sha256'] != sha(Path(fa.__file__)):
        raise ValueError('FA source differs')
    out = {'full_sha256': sha(full_path), 'script_sha256': sha(Path(__file__)), 'cutoffs': {}}
    for cutoff in fa.CUTS:
        cut_path = root / f'strong_continue_fa_{cutoff}.json'
        cut = json.loads(cut_path.read_text())
        if (cut['actual_last'] != cutoff or cut['dataset_digest'] != full['dataset_digest'] or
                cut['script_sha256'] != full['script_sha256'] or cut['system_sha256'] != full['system_sha256']):
            raise ValueError('cutoff inputs differ')
        out['cutoffs'][cutoff] = {'cut_sha256': sha(cut_path),
                                  'comparison': ei.compare(full['snapshots'][cutoff], cut['snapshots'][cutoff])}
    target = root / 'strong_continue_fb.json'
    target.write_text(json.dumps(out, ensure_ascii=False, indent=2, allow_nan=False) + '\n')
    print('wrote', target, flush=True)


if __name__ == '__main__':
    main()
