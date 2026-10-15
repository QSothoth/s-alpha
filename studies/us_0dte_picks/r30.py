"""Run R30's frozen three overlays in both modes through the official CLI."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

from .r27 import ROOT, write_json

BASES = {'selective': 'zero_dte_timing_v6.6', 'required': 'open_hold_v3'}
POLICIES = ('H', 'X', 'HX')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    study = ROOT / 'studies/us_0dte_picks'
    sources = [Path(__file__).resolve(), study / 'position_confirmation.py', study / 'notes/R30_PREREG.md']
    sources += list((ROOT / 'custody').glob('*.py')) + list((ROOT / 'custody/engines').glob('*.py'))
    hashes = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
    write_json(out / 'source_sha256.json', hashes)
    with tempfile.TemporaryDirectory(prefix='custody-r30-') as temporary:
        work = Path(temporary)
        shutil.copytree(ROOT / 'custody', work / 'custody', ignore=shutil.ignore_patterns('__pycache__'))
        engines = work / 'custody/engines'
        shutil.copyfile(study / 'position_confirmation.py', engines / 'r30_position.py')
        with (engines / '__init__.py').open('a') as stream:
            stream.write("\nfrom .r30_position import PositionConfirmation\nENGINES['r30_position'] = PositionConfirmation\n")
        registry = work / 'custody/strategies'
        index = json.loads((registry / 'index.json').read_text())
        jobs = []
        for mode, base in BASES.items():
            jobs.append((mode + '_base', ['--strategy-version', 'V6.6', '--strategy-mode', mode]))
            for policy in POLICIES:
                config = json.loads((registry / (base + '.json')).read_text())
                sid = 'r30_' + mode + '_' + policy.lower()
                config.update(strategy_id=sid, engine='r30_position', description='R30 持仓组合研究 ' + mode + ' ' + policy)
                config['developed_on']['sessions_through'] = '2026-10-14'
                config['params'].update(combo_policy=policy, combo_period=3)
                write_json(registry / (sid + '.json'), config)
                index['strategies'][sid] = {'file': sid + '.json', 'status': 'candidate',
                    'sha256': hashlib.sha256((registry / (sid + '.json')).read_bytes()).hexdigest()}
                write_json(out / (mode + '_' + policy + '_config.json'), config)
                jobs.append((mode + '_' + policy, ['--strategy', sid]))
        write_json(registry / 'index.json', index)
        for key, flags in jobs:
            began = time.monotonic()
            command = [sys.executable, '-m', 'custody', 'evaluate', *flags,
                       '--dataset', str(ROOT / 'data/custody-0dte-v6.1'), '--out', str(out / key)]
            print('Evaluating ' + key, flush=True)
            with (out / (key + '_cli.log')).open('w') as log:
                completed = subprocess.run(command, cwd=work, stdout=log, stderr=subprocess.STDOUT)
            path = out / key / 'report.json'
            if completed.returncode not in (0, 1) or not path.exists():
                raise RuntimeError('evaluation failed: ' + str(out / (key + '_cli.log')))
            report = json.loads(path.read_text())
            if key.endswith('_base'):
                baseline = dict(report)
                baseline.pop('release')
                old = ROOT / 'reports' / BASES[key[:-5]] / 'custody-0dte-v6.1/report.json'
                if baseline != json.loads(old.read_text()):
                    raise AssertionError('legacy baseline report changed: ' + key)
            write_json(out / (key + '_command.json'), dict(argv=command, returncode=completed.returncode,
                       isolated_registry=True, elapsed_seconds=time.monotonic() - began))
            print(key + ': ' + report['verdict'] + ' (%.1fs)' % (time.monotonic() - began), flush=True)
    for relative, digest in hashes.items():
        if hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() != digest:
            raise AssertionError('source changed during evaluation: ' + relative)
    write_json(out / 'run_complete.json', {'baseline_reports_unchanged': True, 'source_hashes_unchanged': True})


if __name__ == '__main__':
    main()
