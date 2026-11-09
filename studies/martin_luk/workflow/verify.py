"""Run WF00's affected test suites sequentially inside the caller's scope."""
import json
import os
from pathlib import Path
import re
import resource
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT/'studies/martin_luk/workflow/rounds/WF00'
SUITES = ('custody/tests', 'studies/trader_replication/tests', 'studies/martin_luk/tests',
          'studies/dan_zanger/tests', 'studies/trader_data/tests', 'studies/trader_screens/tests')


def main():
    selected = sys.argv[1:] or [*SUITES, 'watch/test_watch.py']
    if any(s not in (*SUITES, 'watch/test_watch.py') for s in selected):
        raise ValueError('unknown WF00 test suite')
    results = json.loads((OUT/'test_results.json').read_text()) if sys.argv[1:] else {}
    for suite in selected:
        command = ([sys.executable, suite] if suite.endswith('.py') else
                   [sys.executable, '-m', 'unittest', 'discover', '-s', suite])
        name = suite.replace('/', '_').removesuffix('.py')
        path = OUT/'logs'/(name+'.log')
        with path.open('w') as stream:
            code = subprocess.run(command, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT,
                                  env=dict(os.environ, PYTHONDONTWRITEBYTECODE='1', TMPDIR=str(OUT/'work'))).returncode
        log = path.read_text()
        count = re.search(r'Ran (\d+) tests?', log)
        expected = re.search(r'expected failures=(\d+)', log)
        results[suite] = dict(passed=code == 0 and count is not None, count=int(count.group(1)) if count else 0,
            expected_failures=int(expected.group(1)) if expected else 0, returncode=code,
            log=str(path.relative_to(ROOT)), cumulative_child_peak_rss_mib=resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss/1024)
        (OUT/'test_results.json').write_text(json.dumps(results, ensure_ascii=False, indent=1)+'\n')
        print(suite, results[suite]['count'], 'passed' if results[suite]['passed'] else 'FAILED', flush=True)
        if not results[suite]['passed']:
            print(log[-6000:], flush=True)
            return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
