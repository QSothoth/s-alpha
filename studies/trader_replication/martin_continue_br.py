"""BR: compare full-panel H3 fields before and after memory reduction."""
import gc
import hashlib
import json
from pathlib import Path
import types

import numpy as np

from . import ticket_t4, watchlist
from .martin_continue_a import required_fields
from .martin_continue_bq import _ROLL_MEAN, activity_ranks, chunked_roll_mean
from .martin_strong import Data


def digest_fields(fields):
    return {key: hashlib.sha256(memoryview(np.ascontiguousarray(value))).hexdigest()
            for key, value in fields.items()}


def main():
    root = Path(__file__).resolve().parents[2]
    old_path = root / 'studies/trader_replication/reports/gap_review/source_pins/martin_continue_a_pre_weekly_stream.py.txt'
    old_source = old_path.read_bytes()
    old_hash = hashlib.sha256(old_source).hexdigest()
    if old_hash != '7e7fa2d00ffd12d79d1fa790d5b19703bfc01947ee025c50d1ab273863cbfdfe':
        raise ValueError('archived source digest differs from the historical report')
    old = types.ModuleType('studies.trader_replication._old_a')
    old.__package__ = 'studies.trader_replication'
    exec(compile(old_source, str(old_path), 'exec'), old.__dict__)
    original_ranks = ticket_t4.ranks
    try:
        ticket_t4.ranks = activity_ranks
        D = Data()
    finally:
        ticket_t4.ranks = original_ranks
    del D.fp, D.fwd, D.raw
    for key in ('pr21', 'pr63', 'pr126', 'rank_pool', 'stack', 'tight'):
        D.A.pop(key, None)
    D.rk = D.rk.astype(np.int32)
    gc.collect()
    try:
        watchlist.roll_mean = chunked_roll_mean
        before = old.required_fields(D)
        before_hashes = digest_fields(before)
        del before
        gc.collect()
        after = required_fields(D)
        after_hashes = digest_fields(after)
    finally:
        watchlist.roll_mean = _ROLL_MEAN
    keys = sorted(set(before_hashes) | set(after_hashes))
    comparison = {k: {'before': before_hashes.get(k), 'after': after_hashes.get(k),
                      'identical': before_hashes.get(k) == after_hashes.get(k)} for k in keys}
    out = dict(dataset_digest=D.A['digest'], shape=list(D.c.shape), old_sha256=old_hash,
               new_sha256=hashlib.sha256((root / 'studies/trader_replication/martin_continue_a.py').read_bytes()).hexdigest(),
               comparison=comparison, all_identical=all(v['identical'] for v in comparison.values()))
    target = root / 'studies/trader_replication/reports/gap_review/strong_continue_br.json'
    target.write_text(json.dumps(out, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(out, ensure_ascii=False, indent=2), flush=True)
    if not out['all_identical']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
