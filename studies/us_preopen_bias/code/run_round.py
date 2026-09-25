"""Run one pre-registered round on a segment.

    python3 studies/us_preopen_bias/code/run_round.py S1 --data data/preopen-us-train-v1 \
        --start 2023-08-01 --end 2025-06-30 --split 2024-07-01
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import evaluate as ev  # noqa: E402
import preopen  # noqa: E402
import signals  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('rounds', help='comma list of round ids in signals.ROUNDS')
    ap.add_argument('--data', action='append', required=True, help='raw dir(s); repeat for train + validation')
    ap.add_argument('--start', required=True)
    ap.add_argument('--end', required=True)
    ap.add_argument('--split', default=None)
    ap.add_argument('--only', default=None, help='comma list of candidate ids')
    ap.add_argument('--oneshot', action='store_true', help='S8 one-shot gates instead of the selection gates')
    a = ap.parse_args()
    rows = preopen.build(preopen.load(a.data), a.start, a.end)
    print('rows %d  days %d  symbols %d  %s -> %s' % (len(rows), len({r['date'] for r in rows}),
                                                      len({r['symbol'] for r in rows}), rows[0]['date'], rows[-1]['date']))
    only = set(a.only.split(',')) if a.only else None
    for rid in a.rounds.split(','):
        for name, fn in signals.ROUNDS[rid].items():
            if only and name not in only:
                continue
            m = ev.score(rows, fn, a.split)
            g = None if rid == 'REF' else ev.oneshot_gates(m) if a.oneshot else ev.gates(m)
            print(ev.fmt(name, m, g))


if __name__ == '__main__':
    main()
