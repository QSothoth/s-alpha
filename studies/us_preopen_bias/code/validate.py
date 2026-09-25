"""One-time validation runs.  Defaults reproduce notes/VALIDATION_PLAN.md (S1-S5 finalists).

    python3 studies/us_preopen_bias/code/validate.py --data data/preopen-us-train-v1 --data data/preopen-us-valid-v1
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import evaluate as ev  # noqa: E402
import preopen  # noqa: E402
import signals  # noqa: E402

START, END, SPLIT = '2025-07-01', '2026-09-23', '2026-01-01'
FINALISTS = ('E4_daily_top_fear', 'G2_daily_top_fear_0dte', 'C1_call_chase_fade')


def verdict(m):
    g = {'hit>=53': m['hit'] >= 0.53, 'lo90>50': m['hit_lo90'] > 0.5, 'excess>0': m['excess'] > 0}
    return g, all(g.values())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--data', action='append', required=True)
    ap.add_argument('--start', default=START)
    ap.add_argument('--end', default=END)
    ap.add_argument('--split', default=SPLIT)
    ap.add_argument('--finalists', default=','.join(FINALISTS))
    a = ap.parse_args()
    rows = preopen.build(preopen.load(a.data), a.start, a.end)
    print('rows %d  days %d  symbols %d  %s -> %s' % (len(rows), len({r['date'] for r in rows}),
                                                      len({r['symbol'] for r in rows}), rows[0]['date'], rows[-1]['date']))
    fns = {k: v for r in signals.ROUNDS.values() for k, v in r.items()}
    for name in ('ref_always_long', 'ref_always_short'):
        print(ev.fmt(name, ev.score(rows, fns[name], a.split)))
    for name in a.finalists.split(','):
        m = ev.score(rows, fns[name], a.split)
        g, ok = verdict(m)
        print(ev.fmt(name, m) + '  lo90=%.1f  %s  => %s' % (100 * m['hit_lo90'], ' '.join(
            '%s=%s' % (k, 'Y' if v else 'n') for k, v in g.items()), 'HOLDS' if ok else 'FAILS'))


if __name__ == '__main__':
    main()
