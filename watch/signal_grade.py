"""W27 B/S strength grade 1-5: fixed scales, no fitted tables, any market.

Each part is normalized by daily data only, so Hong Kong, A-share and US marks
read on one scale (studies/watch_signal/notes/W27_PREREG.md):

    volume  log2(bar volume / prior 20-bar mean), clipped to [-1, 2]
    market  side x index move vs yesterday's close / index ATR20%, [-1, 1]
    stock   side x stock move vs yesterday's close / stock ATR20%, [-1, 1]

Each is mapped to 0..1 and averaged. W31 cut that mean where Hong Kong marks
fall about 30 / 30 / 25 / 10 / 5 percent into grades 1-5, so 4 and 5 are rare;
the cuts are fixed and shared by every market. Descriptive: how hard the mark
pushed, not a win rate.
"""
from bisect import bisect_right
from math import log2

CUTS = (0.40, 0.57, 0.73, 0.86)   # W31, from HK 2025-12..2026-08 marks


def _clip(x, lo, hi):
    return max(lo, min(hi, x))


def grade(side, vol_ratio, index_ret, index_atr, stock_ret, stock_atr):
    """1-5, or None when any input is missing. Returns and ATRs are fractions."""
    if (None in (vol_ratio, index_ret, index_atr, stock_ret, stock_atr)
            or vol_ratio <= 0 or index_atr <= 0 or stock_atr <= 0):
        return None
    sign = 1 if side == 'BUY' else -1
    v = (_clip(log2(vol_ratio), -1, 2) + 1) / 3
    m = (_clip(sign * index_ret / index_atr, -1, 1) + 1) / 2
    p = (_clip(sign * stock_ret / stock_atr, -1, 1) + 1) / 2
    return 1 + bisect_right(CUTS, (v + m + p) / 3)
