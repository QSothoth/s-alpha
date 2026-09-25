"""Pre-registered direction candidates.  Each takes the feature dict of (symbol, T) and returns +1 / -1 / 0."""
import math

LONG, SHORT, NONE = 1, -1, 0


def _sgn(x):
    return LONG if x > 0 else SHORT if x < 0 else NONE


# ---- S1 (notes/S1_PREREG.md) ----

def c1_call_chase_fade(f):
    cr, pr, z = f['cvol_ratio'], f['pvol_ratio'], f['pcr_z']
    if None in (cr, pr, z):
        return NONE
    if cr >= 2 and z <= -1:
        return SHORT
    if pr >= 2 and z >= 1:
        return LONG
    return NONE


def c2_short_share_fade(f):
    z = f['short_z']
    if z is None:
        return NONE
    return SHORT if z >= 1.5 else LONG if z <= -1.5 else NONE


def c3_attention_gap_fade(f):
    g, t = f['gap_z'], f['turn_ratio1']
    if None in (g, t):
        return NONE
    return -_sgn(g) if abs(g) >= 1 and t >= 1.5 else NONE


def c4_extreme_reversal(f):
    z = f['r1_z']
    if z is None:
        return NONE
    return -_sgn(z) if abs(z) >= 2 else NONE


def c5_overnight_tug(f):
    if f['atr20'] is None:
        return NONE
    x = (f['on_sum20'] - f['id_sum20']) / (f['atr20'] * math.sqrt(20))
    return SHORT if x >= 1.5 else LONG if x <= -1.5 else NONE


S1 = {'C1_call_chase_fade': c1_call_chase_fade, 'C2_short_share_fade': c2_short_share_fade,
      'C3_attention_gap_fade': c3_attention_gap_fade, 'C4_extreme_reversal': c4_extreme_reversal,
      'C5_overnight_tug': c5_overnight_tug}

# ---- S2 (notes/S2_PREREG.md) ----

def d1_pcr_fear_long(f):
    z = f['pcr_z']
    return LONG if z is not None and z >= 1 else NONE


def d2_spy_reversal(f):
    z = f['spy_r1_z']
    if z is None:
        return NONE
    return LONG if z <= -1 else SHORT if z >= 1 else NONE


def d3_iv_jump_long(f):
    iv, chg = f['iv'], f['iv_chg1']
    if iv is None or chg is None or iv - chg <= 0:
        return NONE
    return LONG if chg / (iv - chg) >= 0.05 else NONE


def _vote(x, lo, hi, contrarian=True):
    if x is None:
        return 0
    v = 1 if x >= hi else -1 if x <= lo else 0
    return -v if contrarian else v


def d4_contrarian_vote(f):
    votes = (_vote(f['pcr_z'], -1, 1, contrarian=False) + _vote(f['spy_r1_z'], -1, 1) + _vote(f['r1_z'], -1, 1)
             + _vote(f['mkt_pcr_z'], -1, 1, contrarian=False))
    return _sgn(votes) if abs(votes) >= 2 else NONE


def d5_call_chase_or_fear(f):
    if c1_call_chase_fade(f) == SHORT:
        return SHORT
    return d1_pcr_fear_long(f)


S2 = {'D1_pcr_fear_long': d1_pcr_fear_long, 'D2_spy_reversal': d2_spy_reversal, 'D3_iv_jump_long': d3_iv_jump_long,
      'D4_contrarian_vote': d4_contrarian_vote, 'D5_call_chase_or_fear': d5_call_chase_or_fear}

# ---- S3 (notes/S3_PREREG.md) ----

def e1_pcr_fear_strong(f):
    z = f['pcr_z']
    return LONG if z is not None and z >= 2 else NONE


def e2_pcr_fear_gap_down(f):
    return LONG if d1_pcr_fear_long(f) == LONG and f['gap'] < 0 else NONE


def e3_fear_and_iv_jump(f):
    return LONG if d1_pcr_fear_long(f) == LONG and d3_iv_jump_long(f) == LONG else NONE


def e4_daily_top_fear(f):
    z = f['pcr_z']
    return LONG if z is not None and z >= 1.5 and f['pcr_z_rank'] == 1 else NONE


def e5_call_chase_short(f):
    cr, z = f['cvol_ratio'], f['pcr_z']
    if None in (cr, z):
        return NONE
    return SHORT if cr >= 1.5 and z <= -1 else NONE


S3 = {'E1_pcr_fear_strong': e1_pcr_fear_strong, 'E2_pcr_fear_gap_down': e2_pcr_fear_gap_down,
      'E3_fear_and_iv_jump': e3_fear_and_iv_jump, 'E4_daily_top_fear': e4_daily_top_fear,
      'E5_call_chase_short': e5_call_chase_short}

# ---- S4 (notes/S4_PREREG.md): the short side ----

def _greed(f, z_max):
    z = f['pcr_z']
    return z is not None and z <= z_max


def f1_greed_short(f):
    return SHORT if _greed(f, -1.5) else NONE


def f2_greed_after_up(f):
    return SHORT if _greed(f, -1) and f['r1_z'] is not None and f['r1_z'] >= 1 else NONE


def f3_daily_top_greed(f):
    return SHORT if _greed(f, -1.5) and f['pcr_z_rank_low'] == 1 else NONE


def f4_greed_gap_up(f):
    return SHORT if _greed(f, -1) and f['gap'] > 0 else NONE


def f5_greed_market_up(f):
    return SHORT if _greed(f, -1) and f['spy_r1_z'] is not None and f['spy_r1_z'] >= 1 else NONE


S4 = {'F1_greed_short': f1_greed_short, 'F2_greed_after_up': f2_greed_after_up, 'F3_daily_top_greed': f3_daily_top_greed,
      'F4_greed_gap_up': f4_greed_gap_up, 'F5_greed_market_up': f5_greed_market_up}

# ---- S5 (notes/S5_PREREG.md): tradable product forms ----

def g1_index_fear_long(f):
    return d1_pcr_fear_long(f) if f['is_index'] else NONE


def g2_daily_top_fear_0dte(f):
    z = f['pcr_z']
    return LONG if z is not None and z >= 1.5 and f['pcr_z_rank_0dte'] == 1 else NONE


def g3_daily_top2_fear(f):
    z = f['pcr_z']
    return LONG if z is not None and z >= 1.5 and f['pcr_z_rank'] is not None and f['pcr_z_rank'] <= 2 else NONE


S5 = {'G1_index_fear_long': g1_index_fear_long, 'G2_daily_top_fear_0dte': g2_daily_top_fear_0dte,
      'G3_daily_top2_fear': g3_daily_top2_fear}

# ---- S6 (notes/S6_PREREG.md): price only, validated on the older holdout ----

def h2_own_reversal(f):
    z = f['r1_z']
    if z is None:
        return NONE
    return LONG if z <= -1 else SHORT if z >= 1 else NONE


def h4_oversold_long(f):
    z = f['dist_ma20_z']
    return LONG if z is not None and z <= -2 else NONE


def h5_gap_fade(f):
    g = f['gap_z']
    return -_sgn(g) if g is not None and abs(g) >= 1 else NONE


S6 = {'H1_spy_reversal': d2_spy_reversal, 'H2_own_reversal': h2_own_reversal, 'H3_attention_gap_fade': c3_attention_gap_fade,
      'H4_oversold_long': h4_oversold_long, 'H5_gap_fade': h5_gap_fade}

# ---- S7 (notes/S7_PREREG.md): extended hours are the retail session ----

def p1_pm_frenzy_fade(f):
    r, g = f['pm_ratio'], f['gap_z']
    return -_sgn(g) if None not in (r, g) and r >= 3 and abs(g) >= 0.5 else NONE


def p2_pm_late_push_fade(f):
    z = f['pm_late_z']
    return -_sgn(z) if z is not None and abs(z) >= 0.25 else NONE


def p3_ah_move_fade(f):
    z = f['ah_z']
    return -_sgn(z) if z is not None and abs(z) >= 0.5 else NONE


def p4_pm_share_fade(f):
    sh, g = f['pm_share'], f['gap_z']
    return -_sgn(g) if None not in (sh, g) and sh >= 0.05 and abs(g) >= 0.5 else NONE


S7 = {'P1_pm_frenzy_fade': p1_pm_frenzy_fade, 'P2_pm_late_push_fade': p2_pm_late_push_fade,
      'P3_ah_move_fade': p3_ah_move_fade, 'P4_pm_share_fade': p4_pm_share_fade}

# ---- S8 (notes/S8_PREREG.md): small-order flow, one-shot ----

def k1_retail_flow_fade(f):
    z = f['sml_share_z']
    if z is None:
        return NONE
    return SHORT if z >= 1.5 else LONG if z <= -1.5 else NONE


def k2_retail_vs_main(f):
    s, m = f['sml_share_z'], f['main_share_z']
    if None in (s, m):
        return NONE
    if s >= 1 and m <= -1:
        return SHORT
    if s <= -1 and m >= 1:
        return LONG
    return NONE


def k3_main_flow_follow(f):
    z = f['main_share_z']
    if z is None:
        return NONE
    return LONG if z >= 1.5 else SHORT if z <= -1.5 else NONE


S8 = {'K1_retail_flow_fade': k1_retail_flow_fade, 'K2_retail_vs_main': k2_retail_vs_main,
      'K3_main_flow_follow': k3_main_flow_follow}

# ---- S9 (notes/S9_PREREG.md): a big after-hours move draws retail buyers -> intraday decline ----

def _ah_big(f, thr):
    z = f['ah_z']
    return z is not None and abs(z) >= thr


def q1_ah_attention_short(f):
    return SHORT if not f['is_index'] and _ah_big(f, 0.5) else NONE


def q2_ah_attention_short_strong(f):
    return SHORT if not f['is_index'] and _ah_big(f, 1) else NONE


def q3_ah_attention_short_all(f):
    return SHORT if _ah_big(f, 0.5) else NONE


S9 = {'Q1_ah_attention_short': q1_ah_attention_short, 'Q2_ah_attention_short_strong': q2_ah_attention_short_strong,
      'Q3_ah_attention_short_all': q3_ah_attention_short_all}

# Reference rules, not candidates: always long / always short.
REFERENCE = {'ref_always_long': lambda f: LONG, 'ref_always_short': lambda f: SHORT}

ROUNDS = {'S1': S1, 'S2': S2, 'S3': S3, 'S4': S4, 'S5': S5, 'S6': S6, 'S7': S7, 'S8': S8, 'S9': S9, 'REF': REFERENCE}
