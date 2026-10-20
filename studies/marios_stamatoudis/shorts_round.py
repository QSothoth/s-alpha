"""Short rounds (S*) for Marios Stamatoudis before his system is registered: studies.trader_replication.shorts on the
research module with the longs of a research report, on the selection segment only (the 2026 segment stays unopened
until the single validation); nothing is written to systems.py.  Same runner as studies/sean_ryan/shorts_round.py.

    PY="nice -n 19 env OPENBLAS_NUM_THREADS=1 PYTHONUTF8=1 /opt/futu-opend/venv/bin/python"
    $PY -m studies.marios_stamatoudis.shorts_round S1 r1.json
"""
from __future__ import annotations

import sys
from dataclasses import dataclass

from studies.marios_stamatoudis import replicate as R
from studies.trader_replication import panels, shorts


@dataclass
class Research:
    """What shorts.round_ reads from a registered system."""
    version: str
    long_report: str

    @property
    def study(self):
        return R.STUDY

    @property
    def config(self):
        return R.STUDY.config(self.long_report)


def main(name, long_report='r1.json', window=R.SELECT):
    sysx = Research(f'{long_report} (research, not registered)', long_report)
    shorts.study_of = lambda trader: (sysx, shorts.wrap(sysx.study), sysx.config)
    panels.WINDOW = window
    return shorts.round_(R.STUDY.id, name)


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else 'r1.json')
