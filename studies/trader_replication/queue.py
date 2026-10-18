"""One background process that runs every trader's rounds in order, loading the home panel once.

    PY="nice -n 19 env OPENBLAS_NUM_THREADS=1 PYTHONUTF8=1 /opt/futu-opend/venv/bin/python"
    $PY -m studies.trader_replication.queue            # runs until the queue stays empty for `idle` minutes

The queue is $TR_QUEUE_DIR/queue.txt (default data/trader-replication-queue), one job a line: `<study id> <action> <args...>`, the same
arguments as `python -m studies.<id>.replicate` (`christian_flanders round R7`, `clement_ang diagnose r1.json D0c`).
Lines may be appended while it runs; finished lines go to done.txt (with ok / error), each job's output to
logs/<job>.log.  A file named `stop` in the queue directory ends the runner at the next job boundary.  The US panel
is cached (each job gets a shallow copy, so named arrays a study adds do not leak into the next study); other
markets load per call and are dropped.
"""
from __future__ import annotations

import contextlib
import importlib
import os
import sys
import time
import traceback
from pathlib import Path

from . import panels, study

ROOT = Path(__file__).resolve().parents[2]
DIR = Path(os.environ.get('TR_QUEUE_DIR', ROOT / 'data' / 'trader-replication-queue'))
MAX_FEATURES = 60                    # rebuild the cached panel when its lazy feature cache grows past this


class Cache:
    def __init__(self):
        self.A = None

    def arrays(self, market):
        if market != 'us':
            return panels.arrays(market)
        if self.A is None or len(self.A['F']._c) > MAX_FEATURES:
            self.A = None
            self.A = panels.arrays('us')
        return dict(self.A)


def pending():
    lines = [x.strip() for x in (DIR / 'queue.txt').read_text(encoding='utf-8').splitlines()] \
        if (DIR / 'queue.txt').exists() else []
    done = {x.split('\t')[0] for x in (DIR / 'done.txt').read_text(encoding='utf-8').splitlines()} \
        if (DIR / 'done.txt').exists() else set()
    return [x for x in lines if x and not x.startswith('#') and x not in done]


def run(job, cache):
    sid, *argv = job.split()
    st = importlib.import_module(f'studies.{sid}.replicate').STUDY
    st.arrays = cache.arrays
    log = DIR / 'logs' / (job.replace(' ', '_').replace('/', '-') + '.log')
    t0 = time.time()
    with open(log, 'w', encoding='utf-8') as f, contextlib.redirect_stdout(f):
        try:
            study.main(st, ['replicate'] + argv)
            status = 'ok'
        except Exception:
            traceback.print_exc(file=f)
            status = 'error'
    with open(DIR / 'done.txt', 'a', encoding='utf-8') as f:
        f.write(f'{job}\t{status}\t{time.strftime("%Y-%m-%d %H:%M")}\t{(time.time() - t0) / 60:.1f} min\n')
    print(job, status, f'{(time.time() - t0) / 60:.1f} min', flush=True)


def main(idle=30):
    (DIR / 'logs').mkdir(parents=True, exist_ok=True)
    cache, waited = Cache(), 0
    while not (DIR / 'stop').exists():
        jobs = pending()
        if not jobs:
            if waited >= idle:
                break
            time.sleep(60)
            waited += 1
            continue
        waited = 0
        run(jobs[0], cache)
    print('queue runner exits', flush=True)


if __name__ == '__main__':
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 30)
