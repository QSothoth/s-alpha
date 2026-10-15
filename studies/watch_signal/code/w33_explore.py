"""W33 exploration: what happens after each strength grade (used segments only).

usage: w33_explore.py selection|check OUT.json
Exploration on already-used HK segments; anything adopted must be confirmed
once on the untouched 2024H1 data (no W33 preregistration; descriptive only).
"""
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

import w12_audit as w12
import w15_market_score as w15
import w16_validate as w16
import w22_trade as w22
import w27_fixed_grade as w27
import w32_guidance as w32

SEGMENTS = {'selection': w32.SEGMENTS['selection'],
            'check': dict(w22.SEGMENTS['validation'], daily='file'),
            'validation': w32.SEGMENTS['validation']}
HORIZONS = (5, 15, 30)


def path_stats(bars, i, side, atr):
    """Direction moves after entry (close of bar i + 1), in ATR14 units."""
    entry = bars[i + 1][4]
    out = {}
    for h in HORIZONS:
        j = i + 1 + h
        if j < len(bars):
            out['f%d' % h] = side * (bars[j][4] - entry) / atr
    seg = bars[i + 2:i + 32]
    if len(seg) == 30:
        hi, lo = max(b[2] for b in seg), min(b[3] for b in seg)
        out['mfe30'] = ((hi - entry) if side > 0 else (entry - lo)) / atr
        out['mae30'] = ((entry - lo) if side > 0 else (hi - entry)) / atr
        out['abs30'] = abs(seg[-1][4] - entry) / atr
        first = None
        for b in seg:
            up = (b[2] - entry) if side > 0 else (entry - b[3])
            down = (entry - b[3]) if side > 0 else (b[2] - entry)
            if down >= atr:
                first = 0
                break
            if up >= atr:
                first = 1
                break
        out['first_up'] = first
    return out


def collect(segment):
    cfg = SEGMENTS[segment]
    daily = w27.load_daily() if cfg['daily'] == 'file' else w32.derived_daily(cfg['bars'])
    excluded = set(w16.quality_scan(cfg['bars']))
    hsi, refs = w15.load_hsi(cfg['hsi'])
    rows = []
    for code, day, previous, bars in w22.sessions(cfg['bars'], cfg['start'], cfg['end'], excluded):
        sa, ia = w27.atr20(daily, code, day), w27.atr20(daily, 'HK.800000', day)
        if not previous or sa is None or ia is None:
            continue
        f = w12.corrected_features(bars)
        for m in w12.replica(bars, f, None, 'B0'):
            i = m['i']
            atr = float(f['atr'][i])
            if i + 2 >= len(bars) or atr <= 0:
                continue
            side = 1 if m['side'] == 'BUY' else -1
            vr = f['vr'][i]
            h = hsi.get(day, {}).get(m['t'])
            g = w32.signal_grade.grade(m['side'], vr if math.isfinite(vr) else None,
                                       (h / refs[day] - 1) if h and day in refs else None, ia,
                                       m['close'] / previous - 1, sa)
            if g is None:
                continue
            row = dict(day=day, g=g, fine=m['tpb'] >= 2, side=m['side'], atr_bp=atr / m['close'] * 1e4)
            row.update(path_stats(bars, i, side, atr))
            rows.append(row)
    return rows


def summarize(rows):
    out = {}
    keys = ['f5', 'f15', 'f30', 'mfe30', 'mae30', 'abs30', 'atr_bp']
    for scope, keep in (('all', lambda r: True), ('tpb>=2', lambda r: r['fine'])):
        out[scope] = {}
        for k in range(1, 6):
            part = [r for r in rows if r['g'] == k and keep(r)]
            stats = dict(n=len(part))
            for key in keys:
                vals = [r[key] for r in part if r.get(key) is not None]
                stats[key] = sum(vals) / len(vals) if vals else None
                if key in ('f15', 'f30'):
                    stats[key + '_t'] = w32.clustered([r for r in part if r.get(key) is not None],
                                                      lambda r, key=key: r[key])[1]
            firsts = [r['first_up'] for r in part if r.get('first_up') is not None]
            stats['up_first'] = sum(firsts) / len(firsts) if firsts else None
            stats['neither'] = sum(1 for r in part if 'mfe30' in r and r.get('first_up') is None) / max(1, len(part))
            out[scope][k] = stats
    return out


if __name__ == '__main__':
    rows = collect(sys.argv[1])
    json.dump(w12.clean(summarize(rows)), open(sys.argv[2], 'w'), indent=2)
    print('rows', len(rows))
