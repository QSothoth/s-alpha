"""Continuation AF: count immature labels in S61's historical training windows."""
from collections import Counter
import hashlib
import json
from pathlib import Path

import numpy as np

from .martin_list import ema
from .martin_strong import Data
from .martin_strong_scan import active, candidates, walk


def main():
    D = Data()
    c, h, l = D.c, D.h, D.l
    with np.errstate(all='ignore'):
        D.e9 = ema(c.astype(float), 9).astype(np.float32)
        e21 = ema(c.astype(float), 21).astype(np.float32)
        fields = {'act20': np.log(D.to20 * D.adr), 'lowe9': (l / D.e9 - 1) / D.adr,
                  'ext21': (c / e21 - 1) / D.adr, 'cpos': (c - l) / (h - l)}
    M = active(D, fields)
    d, j, fill, stop = candidates(D, fields, M)
    years = {}
    for cutoff in ('2025-01-01', '2025-07-01', '2026-01-01', '2026-07-01'):
        start = int(np.searchsorted(D.A['days'], cutoff))
        indexes = np.flatnonzero((d >= start - 120) & (d < start - 60))
        counts = Counter()
        for i in indexes:
            day, code = int(d[i]), int(j[i])
            ret, days, fast = walk(D, e21, day, code, float(fill[i]), float(stop[i]))
            if not np.isfinite(ret) or day + days >= len(c) - 1 and days < 120:
                counts['censored_or_missing'] += 1
                continue
            positive = ret >= .30 or 0 < fast <= 20
            matured = day + days < start or (0 < fast <= 20 and day + fast < start)
            counts['mature' if matured else 'immature'] += 1
            if not matured:
                counts['immature_positive' if positive else 'immature_negative'] += 1
        years[cutoff] = dict(at_risk_candidates=int(len(indexes)), **counts)
    root = Path(__file__).resolve().parents[2]
    paths = ('studies/trader_replication/martin_continue_af.py', 'studies/trader_replication/martin_strong_scan.py',
             'studies/trader_replication/martin_strong.py', 'studies/trader_replication/system.py')
    out = dict(dataset_digest=D.A['digest'], by_fit_start=years,
               code_sha256={p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in paths})
    target = root / 'studies/trader_replication/reports/gap_review/strong_continue_af.json'
    target.write_text(json.dumps(out, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(out, ensure_ascii=False, indent=2), flush=True)


if __name__ == '__main__':
    main()
