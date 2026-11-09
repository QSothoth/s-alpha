"""Continuation AW: prior ADR coverage of Martin's trade ledger."""
from collections import Counter
import hashlib
import json
from pathlib import Path

import numpy as np

from .martin_strong import Data


def main():
    D = Data()
    big = {(x[0], x[1]) for x in D.big}
    years = {}
    records = []
    for d, j, ticker, setup, date in D.his:
        value = D.adr[d - 1, j] if d else float('nan')
        status = 'missing' if not np.isfinite(value) else ('eligible' if value > .05 else 'ineligible')
        records.append({'date': date, 'ticker': ticker, 'setup': setup, 'group': status,
                        'big': (d, j) in big, 'prior_adr': float(value) if np.isfinite(value) else None})
    for year in ('2024', '2025', '2026'):
        rows = [r for r in records if r['date'].startswith(year)]
        years[year] = {'all': dict(Counter(r['group'] for r in rows)),
                       'big': dict(Counter(r['group'] for r in rows if r['big']))}
    root = Path(__file__).resolve().parents[2]
    paths = ('studies/trader_replication/martin_continue_aw.py', 'studies/trader_replication/martin_strong.py',
             'studies/trader_replication/system.py', 'studies/martin_luk/notes/trades.csv')
    out = dict(dataset_digest=D.A['digest'], by_entry_year=years, records=records,
               code_sha256={p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in paths})
    target = root / 'studies/trader_replication/reports/gap_review/strong_continue_aw.json'
    target.write_text(json.dumps(out, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(years, ensure_ascii=False, indent=2), flush=True)


if __name__ == '__main__':
    main()
