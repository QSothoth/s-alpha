"""After the single validation: the carried configuration over the whole common window in all three markets
(study.final with full = WINDOW; HK / A-shares run untuned), reported only.

    PY="nice -n 19 env OPENBLAS_NUM_THREADS=1 PYTHONUTF8=1 /opt/futu-opend/venv/bin/python"
    $PY -m studies.sean_ryan.final_window r8.json
"""
import sys

from studies.sean_ryan import replicate as R

if __name__ == '__main__':
    R.STUDY.full = R.WINDOW
    R.STUDY.final(sys.argv[1])
