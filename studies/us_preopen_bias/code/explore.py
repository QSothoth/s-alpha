"""Disclosed exploration on the selection segment only: P(close > open) by feature quintile.

    python3 studies/us_preopen_bias/code/explore.py --data data/preopen-us-train-v1 --start 2023-08-01 --end 2025-06-30
"""
import argparse
import sys
from collections import defaultdict
from pathlib import Path
from statistics import mean

sys.path.insert(0, str(Path(__file__).resolve().parent))
import preopen  # noqa: E402

FEATURES = ('gap', 'gap_z', 'gap_iv', 'r1_z', 'oc1', 'on1', 'r5_z', 'dist_ma20_z', 'clv1', 'range1_z', 'turn_ratio1',
            'up_days5', 'on_sum20', 'id_sum20', 'ovol_ratio', 'cvol_ratio', 'pvol_ratio', 'pcr1', 'pcr_z', 'pcr_chg',
            'opt_to_stock', 'iv_hv', 'iv_chg1', 'iv_z60', 'short_pct', 'short_z', 'spy_gap', 'spy_r1', 'mkt_pcr',
            'mkt_pcr_z', 'weekday')


def quintiles(rows, key, groups=5):
    xs = [(r['f'][key], r) for r in rows if r['f'].get(key) is not None]
    if len(xs) < groups * 30:
        return None
    xs.sort(key=lambda t: t[0])
    out = []
    for g in range(groups):
        part = xs[g * len(xs) // groups:(g + 1) * len(xs) // groups]
        days = defaultdict(list)
        for _, r in part:
            days[r['date']].append(r['y']['up'])
        out.append((part[0][0], part[-1][0], len(part), mean(r['y']['up'] for _, r in part),
                    1e4 * mean(r['y']['ret_oc'] for _, r in part)))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--data', action='append', required=True)
    ap.add_argument('--start', required=True)
    ap.add_argument('--end', required=True)
    a = ap.parse_args()
    rows = preopen.build(preopen.load(a.data), a.start, a.end)
    print('rows', len(rows), 'P(up)=%.3f' % mean(r['y']['up'] for r in rows))
    for label, sub in (('ALL', rows), ('INDEX', [r for r in rows if r['f']['is_index']]),
                       ('SINGLE', [r for r in rows if not r['f']['is_index']])):
        print('\n==== %s  n=%d  P(up)=%.3f  mean=%+.1fbp' % (label, len(sub), mean(r['y']['up'] for r in sub),
                                                         1e4 * mean(r['y']['ret_oc'] for r in sub)))
        for k in FEATURES:
            q = quintiles(sub, k)
            if not q:
                continue
            cells = ' | '.join('%s %4.1f%% %+5.1fbp' % (('[%.3g,%.3g]' % (lo, hi)).ljust(17), 100 * p, bp)
                               for lo, hi, n, p, bp in q)
            spread = 100 * (q[-1][3] - q[0][3])
            print('%-12s spread %+5.1f  %s' % (k, spread, cells))


if __name__ == '__main__':
    main()
