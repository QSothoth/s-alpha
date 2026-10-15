"""R28: evaluate five preregistered signal-memory mechanisms with the official CLI.

python3 -m studies.us_0dte_picks.r28 --out studies/us_0dte_picks/reports/R28
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from .r27 import BASE, ROOT, selection, write_json

ENGINE = 'r28_confirmation'
CHANGES = {
    'W2': {'confirmation_mode': 'window', 'confirmation_count': 2, 'confirmation_window_minutes': 5},
    'W3': {'confirmation_mode': 'window', 'confirmation_count': 3, 'confirmation_window_minutes': 10},
    'E2': {'confirmation_mode': 'episode', 'confirmation_count': 2, 'confirmation_window_minutes': 15},
    'H3': {'confirmation_mode': 'higher', 'confirmation_count': 2, 'confirmation_bar_minutes': 3},
    'H5': {'confirmation_mode': 'higher', 'confirmation_count': 2, 'confirmation_bar_minutes': 5},
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    study = ROOT / 'studies/us_0dte_picks'
    sources = [Path(__file__).resolve(), study / 'confirmation.py', study / 'r27.py',
               study / 'notes/R28_PREREG.md', ROOT / 'custody/engines/zero_dte_timing.py']
    source_hashes = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
    base_config = json.loads((ROOT / 'custody/strategies' / (BASE + '.json')).read_text())
    reports = {}
    with tempfile.TemporaryDirectory(prefix='custody-r28-') as temporary:
        work = Path(temporary)
        shutil.copytree(ROOT / 'custody', work / 'custody', ignore=shutil.ignore_patterns('__pycache__'))
        engines = work / 'custody/engines'
        shutil.copyfile(study / 'confirmation.py', engines / 'r28_confirmation.py')
        with (engines / '__init__.py').open('a') as stream:
            stream.write("\nfrom .r28_confirmation import MultiConfirmation\nENGINES['r28_confirmation'] = MultiConfirmation\n")
        registry = work / 'custody/strategies'
        index = json.loads((registry / 'index.json').read_text())
        ids = {'V6.6': BASE}
        for key, changes in CHANGES.items():
            config = json.loads(json.dumps(base_config))
            sid = 'zero_dte_timing_r28_' + key.lower()
            config.update(strategy_id=sid, engine=ENGINE, description='R28 ' + key + '：间隔信号与较大周期确认')
            config['developed_on']['sessions_through'] = '2026-10-14'
            config['params'].update(changes)
            write_json(registry / (sid + '.json'), config)
            digest = hashlib.sha256((registry / (sid + '.json')).read_bytes()).hexdigest()
            index['strategies'][sid] = {'file': sid + '.json', 'sha256': digest, 'status': 'candidate'}
            write_json(out / (key + '_config.json'), config)
            ids[key] = sid
        write_json(registry / 'index.json', index)
        for key, sid in ids.items():
            dest = out / key
            command = [sys.executable, '-m', 'custody', 'evaluate', '--strategy', sid,
                       '--dataset', str(ROOT / 'data/custody-0dte-v6.1'), '--out', str(dest)]
            print('Evaluating ' + key, flush=True)
            with (out / (key + '_cli.log')).open('w') as log:
                completed = subprocess.run(command, cwd=work, stdout=log, stderr=subprocess.STDOUT)
            if completed.returncode not in (0, 1) or not (dest / 'report.json').exists():
                raise RuntimeError('evaluation failed: ' + str(out / (key + '_cli.log')))
            reports[key] = json.loads((dest / 'report.json').read_text())
            write_json(out / (key + '_command.json'), {'argv': command, 'isolated_registry': True,
                                                       'returncode': completed.returncode})
            print(key + ': ' + reports[key]['verdict'], flush=True)
    old = json.loads((ROOT / 'reports' / BASE / 'custody-0dte-v6.1/report.json').read_text())
    if reports['V6.6'] != old:
        raise AssertionError('V6.6 report changed')
    result = selection(reports, CHANGES, 'R28')
    result.update(baseline_report_unchanged=True, source_sha256=source_hashes)
    for relative, digest in source_hashes.items():
        if hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() != digest:
            raise AssertionError('research source changed during evaluation: ' + relative)
    write_json(out / 'selection.json', result)
    print(json.dumps({'winner': result['winner'], 'candidates': result['candidates']}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
