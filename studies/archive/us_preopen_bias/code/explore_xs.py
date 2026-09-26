"""Disclosed exploration (selection segment only): cross-sectional decile spreads of each feature, next open -> close.

Each day: rank the active pool by a feature, mean open -> close of the top decile minus the bottom decile (gross).
Day-bootstrap 95% interval and a t-like ratio; quintile means show monotonicity.

    python3 studies/us_preopen_bias/code/explore_xs.py --data data/preopen-s24-select-v1 --start 2022-11-01 --end 2024-12-31
"""
import argparse
import random
import sys
from collections import defaultdict
from pathlib import Path
from statistics import mean, pstdev

sys.path.insert(0, str(Path(__file__).resolve().parent))
import topn  # noqa: E402

FEATURES = ('r1_z', 'gap_z', 'oc1', 'on1', 'r5_z', 'r20', 'dist_ma20_z', 'clv1', 'range1_z', 'turn_ratio1', 'up_days5',
            'on_sum20', 'id_sum20', 'atr20', 'ovol_ratio', 'cvol_ratio', 'pvol_ratio', 'pcr1', 'pcr_z', 'pcr_chg',
            'opt_to_stock', 'iv_hv', 'iv_chg1', 'iv_z60', 'implied_move', 'gap_iv', 'coi_chg', 'poi_chg', 'oi_net')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--data', action='append', required=True)
    ap.add_argument('--start', required=True)
    ap.add_argument('--end', required=True)
    ap.add_argument('--exclude', default='US.BRK,US.SPCX,US.B')
    a = ap.parse_args()
    rows, gate = topn.load(a.data, a.start, a.end, set(a.exclude.split(',')))
    pools = topn.active_pools(rows, gate)
    print('days %d, mean pool %.1f' % (len(pools), mean(len(v) for v in pools.values())))
    rng = random.Random(20260925)
    out = []
    for feat in FEATURES:
        daily, quint = [], defaultdict(list)
        for d in sorted(pools):
            xs = sorted([(r['f'][feat], r['y']['ret_oc']) for r in pools[d] if r['f'].get(feat) is not None],
                        key=lambda t: t[0])
            if len(xs) < 50:
                continue
            k = len(xs) // 10
            daily.append(1e4 * (mean(y for _, y in xs[-k:]) - mean(y for _, y in xs[:k])))
            for q in range(5):
                part = xs[q * len(xs) // 5:(q + 1) * len(xs) // 5]
                quint[q].append(1e4 * mean(y for _, y in part))
        if len(daily) < 60:
            continue
        boots = sorted(mean(daily[rng.randrange(len(daily))] for _ in daily) for _ in range(1000))
        t = mean(daily) / (pstdev(daily) / len(daily) ** 0.5)
        out.append((abs(t), feat, len(daily), mean(daily), boots[25], boots[974], t, [mean(quint[q]) for q in range(5)],
                    mean(1.0 if x > 0 else 0.0 for x in daily)))
    for _, feat, n, m, lo, hi, t, q, pos in sorted(out, reverse=True):
        print('%-14s days=%3d  top-bottom decile %+6.1fbp [%+6.1f, %+6.1f] t=%+5.2f  positive days %4.1f%%  quintiles %s' % (
            feat, n, m, lo, hi, t, 100 * pos, ' '.join('%+5.1f' % x for x in q)))


if __name__ == '__main__':
    main()
