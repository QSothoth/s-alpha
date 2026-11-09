"""CK: audit known source-publication dates for historical training rows."""
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import re

from . import ticket_t4
from .martin_continue_bq import activity_ranks
from .martin_continue_ch import fold_counts
from .martin_strong import Data
from .martin_words import FOLDS
from .pick_model import K


AVAILABLE = {'lS9zbnLi1Gg': '2025-05-01', 'VKNEJA5r8zw': '2026-02-01',
             '56ECvN_79n0': '2025-11-26'}


def availability(source, cutoff):
    ids = re.findall(r'([A-Za-z0-9_-]{11})@', source)
    known = [(name, AVAILABLE[name]) for name in ids if name in AVAILABLE]
    usable = [(name, day) for name, day in known if day <= cutoff]
    if usable:
        name, day = min(usable, key=lambda x: x[1])
        return {'status': 'confirmed_available', 'source': name, 'available_from': day}
    if any(name not in AVAILABLE for name in ids) or not ids:
        return {'status': 'unknown_publication', 'source': None, 'available_from': None}
    return {'status': 'known_sources_not_yet_available', 'source': None, 'available_from': None}


def main():
    if os.environ.get('TRADER_DATA_MODE') != 'frozen' or os.environ.get('TRADER_DATA_TAG') != 'trader-data-v1':
        raise ValueError('explicitly select the registered frozen v1 dataset')
    root = Path(__file__).resolve().parents[2]
    old = ticket_t4.ranks
    try:
        ticket_t4.ranks = activity_ranks
        D = Data()
    finally:
        ticket_t4.ranks = old
    pin = json.loads((root / 'studies/trader_replication/DATA_PIN.json').read_text())['trader-data-v1']['us']
    if D.A['digest'] != pin:
        raise ValueError('dataset digest differs from registered v1')
    trades = [t for t, j, _, _ in D.base.located(D.A, D.base.trades())
              if t.side == 'long' and t.dated and t.entry_date >= '2024-01-02'
              and t.entry_date in D.di and D.rk[D.di[t.entry_date], j] < K]
    prior = json.loads((root / 'studies/trader_replication/reports/gap_review/strong_continue_ch.json').read_text())
    if len(trades) != prior['qualified_trade_rows'] or fold_counts([t.entry_date for t in trades]) != prior['folds']:
        raise AssertionError('qualified rows or fold counts differ from CH')
    folds = []
    for start, end in FOLDS:
        rows = []
        for t in trades:
            if t.entry_date < start:
                rows.append({'id': t.id, 'entry_date': t.entry_date, 'precision': t.precision,
                             'source_raw': t.source, **availability(t.source, start)})
        counts = Counter(row['status'] for row in rows)
        folds.append({'start': start, 'end': end, 'prior_entries': len(rows),
                      'confirmed_available': counts['confirmed_available'],
                      'known_sources_not_yet_available': counts['known_sources_not_yet_available'],
                      'unknown_publication': counts['unknown_publication'], 'rows': rows})
    paths = ('studies/trader_replication/martin_continue_ck.py', 'studies/trader_replication/martin_continue_ch.py',
             'studies/trader_replication/martin_continue_bq.py', 'studies/martin_luk/notes/trades.csv',
             'studies/martin_luk/notes/SOURCES.md', 'studies/martin_luk/notes/RULES_CN.md')
    out = {'dataset_digest': D.A['digest'], 'qualified_rows': len(trades), 'known_sources': AVAILABLE,
           'folds': folds, 'code_sha256': {p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in paths}}
    target = root / 'studies/trader_replication/reports/gap_review/strong_continue_ck.json'
    target.write_text(json.dumps(out, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    print('wrote', target, flush=True)


if __name__ == '__main__':
    main()
