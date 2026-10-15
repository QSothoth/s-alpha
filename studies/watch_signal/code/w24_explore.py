"""W24 exploration: one pass of checkpoint features and outcomes (selection data only).

Writes a compact .npz; analysis lives in w24_analyze.py. Exploration only --
anything found here must be preregistered and validated on unused data.
"""
import argparse
import math
import time

import numpy as np

import w12_audit as w12
import w15_market_score as w15
import w16_validate as w16
import w22_trade as w22

CHECKPOINTS = ('10:00', '10:30', '11:00', '11:30', '13:30', '14:00', '14:30', '15:00', '15:30')
FIELDS = ('day', 'code', 'cp', 'tpb', 'price', 'atr_pct', 'gap', 'r_open', 'r_30', 'vwap_dev', 'vwap_pct',
          'pos', 'tally', 'all_same', 'last_side', 'last_age', 'hsi_open', 'hsi_30', 'hsi_prev',
          'range_so_far', 'rv_so_far', 'prev_range', 'rvol', 'f30', 'f60', 'fclose',
          'fut_range', 'fut_rv', 'mins_left')


def realized(bars, a, b):
    """Sum of absolute 1m close-to-close log returns over bars[a..b]."""
    s = 0.0
    for k in range(a + 1, b + 1):
        s += abs(math.log(bars[k][4] / bars[k - 1][4]))
    return s


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('segment', choices=sorted(w22.SEGMENTS))
    parser.add_argument('out')
    args = parser.parse_args()
    cfg = w22.SEGMENTS[args.segment]
    started = time.monotonic()
    excluded = set(w16.quality_scan(cfg['bars']))
    hsi, refs = w15.load_hsi(cfg['hsi'])
    hsi_open = {d: m.get('09:30') for d, m in hsi.items()}
    rows, codes, days = [], {}, {}
    prev = {}
    for code, day, previous, bars in w22.sessions(cfg['bars'], cfg['start'], cfg['end'], excluded):
        f = w12.corrected_features(bars)
        marks = [(m['i'], 1 if m['side'] == 'BUY' else -1)
                 for m in w12.replica(bars, f, None, 'B0') if not m['coarse']]
        minutes = {b[0][11:16]: i for i, b in enumerate(bars)}
        last = len(bars) - 1
        open_ = bars[0][1]
        day_vol = sum(b[5] for b in bars)
        day_range = (max(b[2] for b in bars) - min(b[3] for b in bars)) / open_
        p = prev.get(code)
        cum_vol, cum = [], 0.0
        for b in bars:
            cum += b[5]
            cum_vol.append(cum)
        for cp in CHECKPOINTS:
            i = minutes.get(cp)
            if i is None or i + 31 > last or i < 30:
                continue
            c = bars[i][4]
            sides = [s for j, s in marks if j <= i]
            hs = hsi.get(day, {})
            h_now, h_30 = hs.get(cp), hs.get(bars[i - 30][0][11:16])
            entry = bars[i + 1][4]
            hi_so = max(b[2] for b in bars[:i + 1]); lo_so = min(b[3] for b in bars[:i + 1])
            hi_f = max(b[2] for b in bars[i + 1:]); lo_f = min(b[3] for b in bars[i + 1:])
            atr = float(f['atr'][i])
            vw = float(f['vwap'][i])
            rows.append((
                days.setdefault(day, len(days)), codes.setdefault(code, len(codes)),
                CHECKPOINTS.index(cp), f['tpb'][i], c, atr / c,
                (open_ / previous - 1) if previous else np.nan, c / open_ - 1, c / bars[i - 30][4] - 1,
                (c - vw) / atr if atr > 0 else np.nan, c / vw - 1, float(f['pos'][i]),
                sides.count(1) - sides.count(-1),
                (sides[0] if len(sides) >= 2 and len(set(sides)) == 1 else 0),
                sides[-1] if sides else 0,
                (i - max(j for j, _ in marks if j <= i)) if sides else -1,
                (h_now / hsi_open[day] - 1) if h_now and hsi_open.get(day) else np.nan,
                (h_now / h_30 - 1) if h_now and h_30 else np.nan,
                (h_now / refs[day] - 1) if h_now and day in refs else np.nan,
                (hi_so - lo_so) / open_, realized(bars, 0, i),
                p['range'] if p else np.nan,
                (cum_vol[i] / p['vol']) if p and p['vol'] > 0 else np.nan,
                bars[i + 31][4] / entry - 1, bars[min(i + 61, last)][4] / entry - 1,
                bars[last][4] / entry - 1,
                (hi_f - lo_f) / entry, realized(bars, i + 1, last), last - i))
        prev[code] = dict(range=day_range, vol=day_vol)
    arr = np.array(rows, dtype=float)
    np.savez_compressed(args.out, data=arr, fields=np.array(FIELDS),
                        days=np.array(sorted(days, key=days.get)), codes=np.array(sorted(codes, key=codes.get)))
    print('rows', len(rows), 'days', len(days), 'codes', len(codes),
          'seconds', round(time.monotonic() - started, 1))


if __name__ == '__main__':
    main()
