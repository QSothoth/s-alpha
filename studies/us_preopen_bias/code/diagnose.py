"""Break one candidate down by symbol, half-year, and a few conditioning features (selection segment only).

    python3 studies/us_preopen_bias/code/diagnose.py D1_pcr_fear_long --data data/preopen-us-train-v1 \
        --start 2023-08-01 --end 2025-06-30
"""
import argparse
import sys
from collections import defaultdict
from pathlib import Path
from statistics import mean

sys.path.insert(0, str(Path(__file__).resolve().parent))
import evaluate as ev  # noqa: E402
import preopen  # noqa: E402
import signals  # noqa: E402

CONDITIONS = {
    'own r1 < 0': lambda f: f['r1'] < 0,
    'own r1 >= 0': lambda f: f['r1'] >= 0,
    'spy r1 < 0': lambda f: f['spy_r1'] is not None and f['spy_r1'] < 0,
    'spy r1 >= 0': lambda f: f['spy_r1'] is not None and f['spy_r1'] >= 0,
    'gap < 0': lambda f: f['gap'] < 0,
    'gap >= 0': lambda f: f['gap'] >= 0,
    'pvol_ratio >= 1': lambda f: f['pvol_ratio'] is not None and f['pvol_ratio'] >= 1,
    'pvol_ratio < 1': lambda f: f['pvol_ratio'] is not None and f['pvol_ratio'] < 1,
    'cvol_ratio < 1': lambda f: f['cvol_ratio'] is not None and f['cvol_ratio'] < 1,
    'cvol_ratio >= 1': lambda f: f['cvol_ratio'] is not None and f['cvol_ratio'] >= 1,
    'mkt_pcr_z >= 0': lambda f: f['mkt_pcr_z'] is not None and f['mkt_pcr_z'] >= 0,
    'mkt_pcr_z < 0': lambda f: f['mkt_pcr_z'] is not None and f['mkt_pcr_z'] < 0,
}


def table(title, groups):
    print('\n-- ' + title)
    for k in sorted(groups):
        xs = groups[k]
        print('  %-18s n=%5d hit=%5.1f%% mean=%+6.1fbp' % (k, len(xs), 100 * mean(w for w, _ in xs),
                                                           1e4 * mean(r for _, r in xs)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('candidate')
    ap.add_argument('--data', action='append', required=True)
    ap.add_argument('--start', required=True)
    ap.add_argument('--end', required=True)
    a = ap.parse_args()
    fn = {k: v for r in signals.ROUNDS.values() for k, v in r.items()}[a.candidate]
    rows = preopen.build(preopen.load(a.data), a.start, a.end)
    sig = ev.signals(rows, fn)
    by_sym, by_half, by_cond, by_n = defaultdict(list), defaultdict(list), defaultdict(list), defaultdict(list)
    per_day = defaultdict(int)
    for r, side in sig:
        per_day[r['date']] += 1
    for r, side in sig:
        item = (ev._win(r, side), side * r['y']['ret_oc'])
        by_sym[r['symbol']].append(item)
        by_half[r['date'][:4] + ('H1' if r['date'][5:7] < '07' else 'H2')].append(item)
        for name, cond in CONDITIONS.items():
            if cond(r['f']):
                by_cond[name].append(item)
        n = per_day[r['date']]
        by_n['signals that day ' + ('1' if n == 1 else '2-3' if n <= 3 else '4+')].append(item)
    print(a.candidate, 'n', len(sig))
    table('symbol', by_sym)
    table('half-year', by_half)
    table('condition', by_cond)
    table('breadth', by_n)


if __name__ == '__main__':
    main()
