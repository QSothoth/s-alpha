"""Causal, trader-independent indicator values; numpy and the standard library only.

OHLCV arrays share a session axis; ``t`` is traded amount. Supply ISO session
dates as ``arrays['days']`` (or ``extras['days']``) for calendar-week indicators.
Optional extras use the cached names without ``extra_``. Missing inputs stay NaN.
Cross-sectional inputs contain the entire market, including names outside a scan.
"""
from datetime import date
import math

import numpy as np


def _specs():
    rows = []

    def add(family, name, params, formula, aliases=(), source="existing", binary=False, layer="per_stock"):
        rows.append(dict(name=name, family=family, parameters=params, formula=formula,
                         aliases=list(aliases), source=source, binary=binary, layer=layer))

    for n in (9, 21, 50):
        add("trend", f"ema{n}_distance_adr", {"length": n, "adr": 20}, "(close / EMA - 1) / ADR20",
            ("sma10_distance", "kama_distance", "elder_ray") if n == 9 else ())
    for n in (150, 200):
        add("trend", f"sma{n}_distance_pct", {"length": n}, "100 * (close / SMA - 1)",
            ("sma30_week_distance",) if n == 150 else ("ema200_distance", "sma40_week_distance"))
    for kind, n in (("ema", 21), ("sma", 50), ("sma", 200)):
        add("trend", f"{kind}{n}_slope10_pct", {"length": n, "change": 10},
            "100 * (moving_average / moving_average[10 bars ago] - 1)", source="new")
    add("trend", "ema_stack", {"lengths": [9, 21, 50]}, "1(EMA9 > EMA21 > EMA50)", binary=True)
    add("trend", "above_ema21_days20", {"ema": 21, "window": 20}, "sum(close > EMA21, 20)")
    add("trend", "supertrend_distance", {"atr": 10, "multiplier": 3}, "(close - Supertrend10,3) / ATR10", ("parabolic_sar",))
    add("trend", "supertrend_flip_days", {"atr": 10, "multiplier": 3}, "sessions since latest Supertrend direction change")
    add("trend", "ichimoku_cloud_position", {"tenkan": 9, "kijun": 26, "span_b": 52, "shift": 26},
        "(close - min(displayed spans)) / abs(displayed span A - span B)", ("ichimoku_tenkan", "ichimoku_kijun"))
    add("trend", "adx14", {"length": 14}, "100 * Wilder14(abs(DI+ - DI-) / (DI+ + DI-))")
    add("trend", "di_spread14", {"length": 14}, "DI+14 - DI-14")
    add("trend", "choppiness14", {"length": 14}, "100 * log10(sum(TR,14) / (highest(high,14)-lowest(low,14))) / log10(14)")
    add("momentum", "rsi14", {"length": 14}, "100 * Wilder(up,14) / (Wilder(up,14)+Wilder(down,14))",
        ("cmo", "cmo_wilder_same_smoothing"))
    add("momentum", "stochastic_k", {"length": 14, "smooth_k": 1, "smooth_d": 3},
        "100 * (close-lowest(low,14)) / (highest(high,14)-lowest(low,14))", ("williams_r",))
    add("momentum", "stochastic_rsi", {"rsi": 14, "length": 14, "smooth_k": 3, "smooth_d": 3},
        "SMA(100*(RSI14-lowest(RSI14,14))/(highest(RSI14,14)-lowest(RSI14,14)),3)")
    add("momentum", "macd_hist_pct", {"fast": 12, "slow": 26, "signal": 9},
        "100 * (EMA12-EMA26-EMA(EMA12-EMA26,9)) / close", ("ppo", "elder_impulse"))
    add("momentum", "macd_hist_change5", {"fast": 12, "slow": 26, "signal": 9, "change": 5}, "macd_hist_pct - macd_hist_pct[5 bars ago]")
    add("momentum", "cci20", {"length": 20, "constant": .015}, "(typical-SMA(typical,20)) / (.015 * mean absolute deviation)")
    for n in (1, 5, 21, 63):
        add("relative_strength", f"return{n}_pct", {"length": n}, f"100 * (close / close[{n} bars ago] - 1)",
            ("roc", "momentum", "trix", "kst") if n == 21 else ())
    add("relative_strength", "excess21_pct", {"length": 21}, "return21_pct - benchmark return21_pct", ("excess5", "excess63"))
    add("relative_strength", "ibd_rs_percentile", {"lengths": [63, 126, 189, 252], "weights": [.4, .2, .2, .2]},
        "market midrank percentile of .4*r63+.2*r126+.2*r189+.2*r252", ("return126", "return252"), layer="cross_section")
    add("relative_strength", "rs_line_high63_pct", {"length": 63}, "100*(close/benchmark / highest(close/benchmark,63)-1)")
    add("relative_strength", "outperform_days20", {"window": 20, "return": 21}, "sum(return21_pct > benchmark return21_pct,20)")
    add("relative_strength", "up_days20", {"window": 20}, "sum(close > previous close,20)")
    add("relative_strength", "beta60", {"length": 60}, "cov(stock log return,benchmark log return,60) / var(benchmark log return,60)")
    add("mean_reversion", "rsi2", {"length": 2}, "100 * Wilder(up,2) / (Wilder(up,2)+Wilder(down,2))")
    add("mean_reversion", "close_position", {}, "(close-low)/(high-low)", ("ibs",))
    add("mean_reversion", "signed_streak", {}, "positive consecutive up closes; negative consecutive down closes")
    add("mean_reversion", "sma5_distance_atr", {"sma": 5, "atr": 14}, "(close-SMA5)/ATR14")
    add("mean_reversion", "bollinger_percent_b", {"length": 20, "std": 2}, "(close-(SMA20-2*population_std20))/(4*population_std20)", ("zscore20", "keltner_position"))
    add("volatility", "adr20_pct", {"length": 20}, "100 * mean(high/low-1,20)", ("atr14_pct", "hv20", "ulcer"))
    add("volatility", "range_adr", {"length": 20}, "(high/low-1)/ADR20")
    add("volatility", "range3_adr", {"short": 3, "length": 20}, "mean(high/low-1,3)/ADR20")
    add("volatility", "bollinger_width_percentile252", {"length": 20, "std": 2, "history": 252}, "own trailing-252 midrank percentile of 4*std20/SMA20")
    add("volatility", "ttm_squeeze_days", {"length": 20, "bb": 2, "kc": 1.5}, "consecutive days 2*std20 < 1.5*ATR20")
    add("volatility", "donchian20_position", {"length": 20}, "(close-lowest(low,20))/(highest(high,20)-lowest(low,20))", ("smc_premium_discount",))
    add("volatility", "breakout55", {"length": 55}, "1(close > highest(previous high,55))", binary=True)
    for name, formula in (("inside_day", "1(high<=previous high and low>=previous low)"),
                          ("nr7", "1(high-low <= lowest(high-low,7))"),
                          ("outside_day", "1(high>previous high and low<previous low)")):
        add("volatility", name, {"length": 7} if name == "nr7" else {}, formula, binary=True)
    add("volume", "dollar_volume20", {"length": 20}, "mean(traded amount,20)")
    add("volume", "relative_volume", {"length": 20}, "volume / mean(volume,20)", ("dollar_volume_today_vs20",))
    add("volume", "relative_volume3", {"short": 3, "length": 20}, "mean(volume,3) / mean(volume,20)")
    add("volume", "obv_high20_distance", {"length": 20}, "(OBV-highest(OBV,20))/sum(volume,20)", ("pvt", "ad", "chaikin_oscillator", "force_index", "eom", "nvi", "amihud"))
    add("volume", "cmf20", {"length": 20}, "sum(((2*close-high-low)/(high-low))*volume,20)/sum(volume,20)")
    add("volume", "mfi14", {"length": 14}, "100*sum(typical*volume on up typical days,14)/sum(directional money flow,14)")
    add("volume", "up_down_volume50", {"length": 50}, "sum(volume on up closes,50)/sum(volume on down closes,50)", source="new")
    add("volume", "pvi_sma255_distance_pct", {"length": 255}, "100*(positive-volume index / SMA(PVI,255)-1)")
    for anchor in ("high252", "low252", "high50", "low50", "gap", "earnings"):
        add("anchored_volume", f"avwap_{anchor}_distance_adr", {"gap": .10} if anchor == "gap" else {},
            "(close / volume-weighted typical price since " + anchor + " - 1)/ADR20")
    add("anchored_volume", "volume_profile_poc_distance_adr", {"window": 100, "bins": 50, "value_area": .7},
        "uniform daily volume on log-price intervals; 100-day/50-bin POC; (close/POC-1)/ADR20", source="new")
    add("anchored_volume", "volume_profile_value_position", {"window": 100, "bins": 50, "value_area": .7},
        "expand contiguously from POC towards higher adjacent volume until >=70%; (close-VA_low)/(VA_high-VA_low)", source="new")
    for name, formula in (("high252_distance_pct", "100*(close/highest(high,252)-1)"),
                          ("high50_distance_pct", "100*(close/highest(high,50)-1)"),
                          ("low252_distance_pct", "100*(close/lowest(low,252)-1)")):
        add("structure", name, {}, formula)
    for n in (252, 50):
        add("structure", f"new_high{n}", {"length": n}, f"1(close>=highest(previous high,{n}))", binary=True)
    add("structure", "over_previous_high_adr", {}, "(close/previous high-1)/ADR20")
    add("structure", "gap_adr", {}, "(open/previous close-1)/previous ADR20")
    add("structure", "large_gap_days", {"threshold": .10}, "sessions since most recent positive opening gap >=10%; NaN until observed")
    add("structure", "unfilled_gap_above_distance_adr", {"window": 252},
        "latest downward high<previous low gap above close, upper edge never retouched since; (upper/close-1)/ADR20", source="new")
    add("structure", "rising_swing_lows", {"left": 2, "right": 2, "pivots": 3},
        "consecutive increases (0..2) among last three strict low fractals, visible two bars after pivot", source="new")
    add("structure", "base_length", {"window": 252}, "sessions since most recent trailing-252 highest high", ("aroon",), source="new")
    add("structure", "base_depth_pct", {"window": 252}, "100*(1-lowest low since that high / that high)", source="new")
    add("structure", "darvas_breakout", {"window": 20, "confirmation": 3}, "1(close>box high confirmed by three later lower highs)", binary=True)
    add("structure", "vcp_contractions", {"windows": [5, 10, 20, 40]}, "count of decreasing adjacent nonoverlapping 5/5/10/20-session percentage ranges")
    add("structure", "high20_days", {"window": 20}, "sessions since high>=highest(previous high,20)")
    add("structure", "pullback_depth_adr", {"window": 20}, "(highest(high,20)/close-1)/ADR20")
    add("structure", "ema21_retest_count", {"ema": 21, "reset_ema": 50},
        "since last close crossing above EMA50, count low<=EMA21 after a prior close>=EMA21*(1+ADR20); rearm only after a later such close", source="new")
    candle_formulas = {
        "bullish_engulfing": "previous bearish body engulfed by current bullish body",
        "pin_bar": "lower wick>=2*body and >=.6*range, close>=midpoint, range>0",
        "upper_pin_bar": "upper wick>=2*body and >=.6*range, close<=midpoint, range>0",
        "doji": "body<=.1*mean(previous range,10)",
        "bullish_marubozu": "bullish body>mean(previous body,10), each wick<=.1*mean(previous range,10)",
        "morning_star": "bearish candle, short gapped-down middle body, bullish close above first body midpoint",
    }
    for name, formula in candle_formulas.items():
        add("candles", name, {"reference": 10}, formula, source="new" if name == "pin_bar" else "existing", binary=True)
    for name, formula in (("chan_bottom_fractal", "bottom fractal after causal inclusion merging; confirmed by next merged bar"),
                          ("chan_buy2", "confirmed higher bottom after lowest low in 52 bars; merged stroke gap>=4"),
                          ("chan_buy3", "confirmed pullback above overlapping prior stroke pivot"),
                          ("chan_weekly_buy", "buy2 or buy3 on last complete observed calendar week"),
                          ("chan_pivot_distance_adr", "(close/latest confirmed stroke pivot upper edge-1)/ADR20")):
        add("chan", name, {"lookback": 52, "min_gap": 4}, formula, binary=name != "chan_pivot_distance_adr")
    for name, formula in (("smc_bos", "signed structural breaks over 20 bars, strict 2+2 confirmed pivots"),
                          ("smc_choch", "signed changes of break direction over 20 bars"),
                          ("smc_fvg_distance_adr", "distance to nearest unfilled bullish three-bar fair-value-gap midpoint / (close*ADR20), age<=60"),
                          ("smc_order_block_distance_adr", "(close/low of last bearish candle before confirmed up-break-1)/ADR20"),
                          ("smc_low_sweep", "low<confirmed swing low<close, previous close>=swing low")):
        add("smc", name, {"pivot": 2, "window": 20, "fvg_age": 60}, formula, binary=name == "smc_low_sweep")
    add("chips", "chip_profit_share", {"step": .02, "turnover_proxy": 20}, "turnover-decayed log-grid mass at or below close; turnover proxy volume/(20*mean(volume,20))")
    add("chips", "chip_concentration90", {"step": .02}, "(95th-5th chip cost quantile)/median chip cost", ("average_cost_distance",))
    add("chips", "chip_overhang_share", {"step": .02}, "turnover-decayed log-grid mass strictly above close", ("dense_support",))
    add("templates", "minervini_score", {}, "count of seven price/SMA/52-week conditions plus market RS percentile>=70", layer="cross_section")
    add("templates", "weinstein_stage", {"weekly_sma": 30, "slope": 4}, "2 above rising weekly SMA30; 4 below falling SMA30; 1 below nonfalling; 3 otherwise")
    add("templates", "weekly_pivot_position", {}, "previous complete week's P=(H+L+C)/3, R1=2P-L,S1=2P-H; (close-S1)/(R1-S1)", source="new")
    for name, params, formula in (
            ("weekly_rsi14", {"length": 14}, "RSI14 on completed weeks plus current week through tonight"),
            ("weekly_macd_hist_pct", {"fast": 12, "slow": 26, "signal": 9}, "100*MACD12,26,9 histogram/current close on provisional weekly bars"),
            ("inside_week", {}, "current high<=previous week high and current low>=previous week low"),
            ("weekly_pin_bar", {}, "same pin-bar rule on current week through tonight"),
            ("weekly_close_position", {}, "(tonight close-current week low)/(current week high-current week low)")):
        add("multi_timeframe", name, params, formula, source="new", binary=name in ("inside_week", "weekly_pin_bar"))
    for name, key in (("h4_momentum", "h4_momentum"), ("h4_stack", "h4_stack"), ("h4_coil", "h4_coil"), ("h4_history", "h4_history")):
        add("multi_timeframe", name, {}, "optional already-causal extra " + key)
    for name, formula in (("theme_peers", "count other market stocks with 60-session log-return correlation>=.5, >=40 common observations"),
                          ("theme_moving_peers", "count peers with 5-session return>=10%"),
                          ("theme_peer_return5_pct", "mean peer 5-session percentage return"),
                          ("theme_peer_return1_pct", "mean peer 1-session percentage return"),
                          ("theme_strength_percentile", "midrank of own 21-session return among own peers and self")):
        add("theme", name, {"correlation_window": 60, "correlation": .5, "min_observations": 40}, formula, layer="cross_section")
    for name, params, formula in (("iv", {}, "optional historical implied volatility"),
                                  ("iv_percentile252", {"length": 252}, "own trailing-252 IV midrank percentile"),
                                  ("iv_minus_hv", {}, "optional IV-HV"),
                                  ("option_relative_volume20", {"length": 20}, "option volume/mean(option volume,20)"),
                                  ("put_call_volume_ratio", {}, "put volume/call volume"),
                                  ("put_call_oi_ratio", {}, "put open interest/call open interest"),
                                  ("option_oi_change5_pct", {"length": 5}, "100*(option open interest/option open interest[5 bars ago]-1)")):
        add("options", name, params, formula, ("iv_rank",) if name == "iv_percentile252" else ())
    add("events", "earnings_days", {}, "optional calendar days since last known earnings")
    add("events", "earnings_gap_pct", {}, "100*(open/previous close-1) on last observable post-earnings session, carried forward")
    add("events", "potent_days20", {"length": 20}, "sum(optional cached causal potent-day flag,20)")
    add("price", "price", {}, "close")
    return tuple(rows)


V1_SPEC = _specs()
V1_PER_STOCK_NAMES = tuple(s["name"] for s in V1_SPEC if s["layer"] == "per_stock")
V1_CROSS_SECTION_NAMES = tuple(s["name"] for s in V1_SPEC if s["layer"] == "cross_section")

# Canonical v1.1 names retain the earlier library's units and warm-up rules.
LEGACY_ALIASES = dict(
    dollar_volume20="dollar_vol20_M", range_adr="range_today_adr",
    ema9_distance_adr="ext_ema9_adr", ema21_distance_adr="ext_ema21_adr",
    ema50_distance_adr="ext_ema50_adr", high252_distance_pct="from_high252_pct",
    over_previous_high_adr="over_prior_high_adr", return1_pct="perf1_pct",
    return5_pct="perf5_pct", return21_pct="perf21_pct", return63_pct="perf63_pct",
    excess21_pct="rs21_vs_qqq_pct", rs_line_high63_pct="rs_line_from_high63_pct",
    close_position="close_pos", relative_volume="rvol20", relative_volume3="rvol3_20",
    gap_adr="gap_today_adr", large_gap_days="days_since_10pct_gap",
    range3_adr="contract3_adr", avwap_low50_distance_adr="avwap_base_low_adr",
    avwap_high50_distance_adr="avwap_base_high_adr",
    option_relative_volume20="option_rvol20", iv="iv_pct", earnings_days="earn_days")


def _legacy_specs():
    rows = []
    def add(name, family, formula, parameters=None, binary=False, layer="per_stock"):
        rows.append(dict(name=name, family=family, formula=formula,
                         parameters=parameters or {}, aliases=[], source="existing",
                         origin="legacy", binary=binary, layer=layer))
    add("dollar_vol20_M", "volume", "mean(amount,20,min=15)/1e6")
    add("price", "price", "raw_c, actual session close; NaN when absent; older cache used adjusted close and leaked future splits")
    add("adr20_pct", "volatility", "100*mean(high/low-1,20,min=15)")
    add("range_today_adr", "volatility", "(high/low-1)/ADR20(min=15)")
    add("lod_stop_pct", "mean_reversion", "100*(close/low-1)")
    for k in (9, 21, 50):
        add(f"ext_ema{k}_adr", "trend", f"(close/EMA{k}-1)/ADR20(min=15)", {"length": k})
    add("ema_stack", "trend", "1(EMA9>EMA21)+1(EMA21>EMA50); 0..2")
    add("ema9_21_gap_adr", "trend", "(EMA9/EMA21-1)/ADR20(min=15)")
    add("from_high252_pct", "structure", "100*(close/highest(high,252,min=60)-1)")
    add("from_high20_pct", "structure", "100*(close/highest(high,20)-1)")
    add("over_prior_high_adr", "structure", "(close/previous high-1)/ADR20(min=15)")
    for k in (1, 5, 21, 63):
        add(f"perf{k}_pct", "relative_strength", f"100*(close/close[{k}]-1)", {"length": k})
    for k in (21, 5):
        add(f"rs{k}_vs_qqq_pct", "relative_strength", f"100*(close/close[{k}]-benchmark/benchmark[{k}])")
    add("rs_line_from_high63_pct", "relative_strength", "100*(close/benchmark / highest(close/benchmark,63)-1)")
    add("close_pos", "mean_reversion", "(close-low)/(high-low)")
    add("rvol20", "volume", "volume/mean(volume,20,min=15)")
    add("rvol3_20", "volume", "mean(volume,3)/mean(volume,20,min=15)")
    add("dollar_vol_today_vs20", "volume", "amount/mean(amount,20,min=15)")
    add("gap_today_adr", "structure", "(open/previous close-1)/previous ADR20(min=15)")
    add("days_since_10pct_gap", "structure", "min(120,sessions since latest positive opening gap>=10%); 120 before first")
    add("inside_day", "volatility", "1(high<=previous high and low>=previous low); missing comparison=0", binary=True)
    add("nr7", "volatility", "1(range<=lowest(range,7)); missing comparison=0", binary=True)
    add("contract3_adr", "volatility", "mean(high/low-1,3)/ADR20(min=15)")
    for anchor in ("low", "high"):
        add(f"avwap_base_{anchor}_adr", "anchored_volume", f"(close/AVWAP(first {anchor} in trailing 50)-1)/ADR20; starts at row 50")
    add("avwap_big_gap_adr", "anchored_volume", "(close/AVWAP(first largest opening gap in trailing 60)-1)/ADR20; starts at row 60")
    add("option_rvol20", "options", "option_volume/mean(option_volume,20,min=10)")
    add("iv_pct", "options", "optional historical IV, unchanged cached units")
    add("earn_days", "events", "min(optional days since earnings,120)")
    add("new_high252", "structure", "1(close>=highest(previous high,252,min=60)); missing comparison=0", binary=True)
    add("new_high50", "structure", "1(close>=highest(previous high,50)); missing comparison=0", binary=True)
    add("from_high50_adr", "structure", "(close/highest(high,50)-1)/ADR20(min=15)")
    add("above_ema21_days20", "trend", "sum(1(close>EMA21),20,min=15); missing comparison=0")
    add("rs_pos_days20", "relative_strength", "sum(1(stock return21>benchmark return21),20,min=15); missing comparison=0")
    add("up_days20", "relative_strength", "sum(1(close>previous close),20,min=15); missing comparison=0")
    for name, formula in (
            ("theme_peers_scope", "other scope members with centered float32 60-session log-return cosine>=.5; each >=40 observed returns, missing centered returns=0"),
            ("theme_peers_moving", "count such peers with sum(last five log returns)>=log(1.10)"),
            ("theme_peer_ret5", "100*mean(peer sum of last five log returns), ignoring missing"),
            ("theme_peer_ret1", "100*mean(peer latest log return), ignoring missing")):
        add(name, "theme", formula, {"window": 60, "correlation": .5, "min_observations": 40}, layer="cross_section")
    return tuple(rows)


LEGACY_SPEC = _legacy_specs()
LEGACY_NAMES = tuple(s["name"] for s in LEGACY_SPEC)


def _v1_1_specs():
    legacy = {s["name"]: s for s in LEGACY_SPEC}
    rows = []
    for original in V1_SPEC:
        name = LEGACY_ALIASES.get(original["name"], original["name"])
        row = {**original, "origin": "standard_v1"}
        if name in legacy:
            row = {**legacy[name], "aliases": list(original["aliases"])}
            if name != original["name"]:
                row["aliases"].append(original["name"])
        rows.append(row)
    existing = {s["name"] for s in rows}
    rows.extend(s for s in LEGACY_SPEC if s["name"] not in existing)
    for row in rows:
        if row['name'] == 'price':
            row['legacy_compatibility_exception'] = 'Older cache price used adjusted c with future split information; v1.1 uses raw_c without fallback.'
        if row['name'] == 'bollinger_width_percentile252':
            row['parameters'] = {**row['parameters'], 'tie_rtol': 1e-12, 'tie_atol': 1e-12}
        if row['name'] == 'nr7':
            row['parameters'] = {'length': 7, 'equality_rtol': 1e-12}
        if row['name'].startswith('volume_profile_'):
            row['parameters'] = {**row['parameters'], 'mass_tie_rtol': 1e-12}
        if row['name'] == 'chip_concentration90':
            row['parameters'] = {**row['parameters'], 'quantile_probability_tolerance': 1e-12}
    return tuple(rows)


SPEC = _v1_1_specs()
PER_STOCK_NAMES = tuple(s["name"] for s in SPEC if s["layer"] == "per_stock")
CROSS_SECTION_NAMES = tuple(s["name"] for s in SPEC if s["layer"] == "cross_section")
# Replaced once by the market-only freeze command; never learned from labels.
V1_NAMES = (
    "ema9_distance_adr",
    "ema50_distance_adr",
    "sma150_distance_pct",
    "ema21_slope10_pct",
    "sma50_slope10_pct",
    "sma200_slope10_pct",
    "ema_stack",
    "above_ema21_days20",
    "supertrend_distance",
    "supertrend_flip_days",
    "ichimoku_cloud_position",
    "adx14",
    "di_spread14",
    "choppiness14",
    "stochastic_rsi",
    "macd_hist_pct",
    "macd_hist_change5",
    "cci20",
    "return1_pct",
    "return5_pct",
    "return21_pct",
    "return63_pct",
    "ibd_rs_percentile",
    "rs_line_high63_pct",
    "outperform_days20",
    "up_days20",
    "beta60",
    "rsi2",
    "close_position",
    "signed_streak",
    "adr20_pct",
    "range_adr",
    "range3_adr",
    "bollinger_width_percentile252",
    "ttm_squeeze_days",
    "breakout55",
    "inside_day",
    "nr7",
    "outside_day",
    "dollar_volume20",
    "relative_volume",
    "relative_volume3",
    "obv_high20_distance",
    "cmf20",
    "mfi14",
    "up_down_volume50",
    "pvi_sma255_distance_pct",
    "avwap_high252_distance_adr",
    "avwap_low252_distance_adr",
    "avwap_high50_distance_adr",
    "avwap_low50_distance_adr",
    "avwap_gap_distance_adr",
    "avwap_earnings_distance_adr",
    "volume_profile_poc_distance_adr",
    "high252_distance_pct",
    "high50_distance_pct",
    "low252_distance_pct",
    "new_high252",
    "over_previous_high_adr",
    "gap_adr",
    "large_gap_days",
    "unfilled_gap_above_distance_adr",
    "rising_swing_lows",
    "base_length",
    "darvas_breakout",
    "vcp_contractions",
    "high20_days",
    "pullback_depth_adr",
    "ema21_retest_count",
    "bullish_engulfing",
    "pin_bar",
    "upper_pin_bar",
    "doji",
    "bullish_marubozu",
    "morning_star",
    "chan_bottom_fractal",
    "chan_buy2",
    "chan_weekly_buy",
    "chan_pivot_distance_adr",
    "smc_bos",
    "smc_choch",
    "smc_fvg_distance_adr",
    "smc_order_block_distance_adr",
    "smc_low_sweep",
    "chip_profit_share",
    "chip_concentration90",
    "minervini_score",
    "weinstein_stage",
    "weekly_pivot_position",
    "weekly_macd_hist_pct",
    "inside_week",
    "weekly_pin_bar",
    "weekly_close_position",
    "h4_momentum",
    "h4_stack",
    "h4_coil",
    "h4_history",
    "theme_peers",
    "theme_moving_peers",
    "theme_peer_return5_pct",
    "theme_peer_return1_pct",
    "theme_strength_percentile",
    "iv",
    "iv_percentile252",
    "iv_minus_hv",
    "option_relative_volume20",
    "put_call_volume_ratio",
    "put_call_oi_ratio",
    "option_oi_change5_pct",
    "earnings_days",
    "earnings_gap_pct",
    "potent_days20",
    "price",
)

V1_1_NAMES = (
    "ext_ema9_adr",
    "ext_ema50_adr",
    "ema_stack",
    "above_ema21_days20",
    "perf1_pct",
    "perf5_pct",
    "perf21_pct",
    "perf63_pct",
    "rs_line_from_high63_pct",
    "up_days20",
    "close_pos",
    "adr20_pct",
    "range_today_adr",
    "contract3_adr",
    "inside_day",
    "nr7",
    "dollar_vol20_M",
    "rvol20",
    "rvol3_20",
    "avwap_base_high_adr",
    "avwap_base_low_adr",
    "from_high252_pct",
    "new_high252",
    "new_high50",
    "over_prior_high_adr",
    "gap_today_adr",
    "days_since_10pct_gap",
    "iv_pct",
    "option_rvol20",
    "earn_days",
    "price",
    "lod_stop_pct",
    "from_high20_pct",
    "rs5_vs_qqq_pct",
    "avwap_big_gap_adr",
    "from_high50_adr",
    "rs_pos_days20",
    "theme_peers_scope",
    "theme_peers_moving",
    "theme_peer_ret5",
    "theme_peer_ret1",
    "supertrend_distance",
    "supertrend_flip_days",
    "ichimoku_cloud_position",
    "adx14",
    "di_spread14",
    "stochastic_rsi",
    "macd_hist_pct",
    "macd_hist_change5",
    "cci20",
    "rsi2",
    "bollinger_width_percentile252",
    "obv_high20_distance",
    "cmf20",
    "mfi14",
    "volume_profile_poc_distance_adr",
    "weekly_pivot_position",
    "weekly_rsi14",
    "weekly_macd_hist_pct",
    "ema21_slope10_pct",
    "sma50_slope10_pct",
    "sma200_slope10_pct",
    "choppiness14",
    "ibd_rs_percentile",
    "beta60",
    "signed_streak",
    "ttm_squeeze_days",
    "outside_day",
    "up_down_volume50",
    "pvi_sma255_distance_pct",
    "avwap_high252_distance_adr",
    "avwap_low252_distance_adr",
    "avwap_gap_distance_adr",
    "avwap_earnings_distance_adr",
    "high50_distance_pct",
    "low252_distance_pct",
    "unfilled_gap_above_distance_adr",
    "rising_swing_lows",
    "base_length",
    "darvas_breakout",
    "vcp_contractions",
    "high20_days",
    "pullback_depth_adr",
    "ema21_retest_count",
    "bullish_engulfing",
    "pin_bar",
    "upper_pin_bar",
    "doji",
    "bullish_marubozu",
    "morning_star",
    "chan_bottom_fractal",
    "chan_buy2",
    "chan_weekly_buy",
    "chan_pivot_distance_adr",
    "smc_bos",
    "smc_choch",
    "smc_fvg_distance_adr",
    "smc_order_block_distance_adr",
    "smc_low_sweep",
    "chip_profit_share",
    "chip_concentration90",
    "weinstein_stage",
    "inside_week",
    "weekly_pin_bar",
    "weekly_close_position",
    "h4_momentum",
    "h4_stack",
    "h4_coil",
    "h4_history",
    "theme_strength_percentile",
    "iv_percentile252",
    "iv_minus_hv",
    "put_call_volume_ratio",
    "put_call_oi_ratio",
    "option_oi_change5_pct",
    "earnings_gap_pct",
    "potent_days20",
)


def legacy_per_stock(arrays, benchmark, extras=None):
    """Earlier library's exact units, warm-up and first-extremum anchors."""
    extras = extras or {}
    o, h, l, c, v, amount = (np.asarray(arrays[k], float) for k in ("o", "h", "l", "c", "v", "t"))
    q = np.asarray(benchmark["c"] if isinstance(benchmark, dict) else benchmark, float)
    n = len(c)
    raw_c = np.asarray(arrays.get('raw_c', np.full(n, np.nan)), float)
    if raw_c.shape != (n,):
        raise ValueError('raw_c must share the one-dimensional session axis')
    def rolling(x, window, minimum=None, kind="mean"):
        minimum = window if minimum is None else minimum
        if not n:
            return np.empty(0)
        blocks = np.lib.stride_tricks.sliding_window_view(np.pad(x, (window-1, 0), constant_values=np.nan), window)
        good = np.isfinite(blocks)
        count = good.sum(1)
        if kind in ("mean", "sum"):
            value = np.where(good, blocks, 0).sum(1)
            if kind == "mean":
                value = divide(value, count)
        else:
            value = getattr(np, kind)(np.where(good, blocks, -np.inf if kind == "max" else np.inf), axis=1)
        return np.where(count >= minimum, value, np.nan)
    def moving_average(x, length):
        alpha, current, weight = 2/(length+1), np.nan, 1.
        out = np.full(n, np.nan)
        for t, value in enumerate(x):
            if np.isfinite(current):
                weight *= 1-alpha
                if np.isfinite(value):
                    if value != current:
                        current = (weight*current+alpha*value)/(weight+alpha)
                    weight = 1.
            elif np.isfinite(value):
                current = value
            out[t] = current
        return out
    adr = rolling(divide(h, l)-1, 20, 15)
    e9, e21, e50 = (moving_average(c, length) for length in (9, 21, 50))
    pc, ph = lag(c), lag(h)
    gap = divide(o, pc)-1
    pv = np.r_[0., np.cumsum(np.nan_to_num((h+l+c)/3)*np.nan_to_num(v))]
    vv = np.r_[0., np.cumsum(np.nan_to_num(v))]
    def anchor(window, values, highest=False):
        out = np.full(n, np.nan)
        values = np.where(np.isfinite(values), values, -np.inf if highest else np.inf)
        for t in range(window, n):
            start = t-window+1
            start += int((np.argmax if highest else np.argmin)(values[start:t+1]))
            if vv[t+1]-vv[start] > 0:
                out[t] = (pv[t+1]-pv[start])/(vv[t+1]-vv[start])
        return divide(divide(c, out)-1, adr)
    since, last = np.full(n, 120.), -n-120
    for t in range(n):
        if gap[t] >= .10:
            last = t
        since[t] = min(120, t-last)
    rs21 = 100*(divide(c, lag(c, 21))-divide(q, lag(q, 21)))
    relative = divide(c, q)
    avg_volume, avg_amount = rolling(v, 20, 15), rolling(amount, 20, 15)
    option = np.asarray(extras.get("option_volume", np.full(n, np.nan)), float)
    minimum_range7 = rolling(h-l, 7, kind='min')
    out = dict(dollar_vol20_M=avg_amount/1e6, price=raw_c.copy(), adr20_pct=adr*100,
        range_today_adr=divide(divide(h, l)-1, adr), lod_stop_pct=100*(divide(c, l)-1),
        ema_stack=(e9 > e21).astype(float)+(e21 > e50).astype(float),
        ema9_21_gap_adr=divide(divide(e9, e21)-1, adr),
        from_high252_pct=100*(divide(c, rolling(h, 252, 60, "max"))-1),
        from_high20_pct=100*(divide(c, rolling(h, 20, kind="max"))-1),
        over_prior_high_adr=divide(divide(c, ph)-1, adr), rs21_vs_qqq_pct=rs21,
        rs5_vs_qqq_pct=100*(divide(c, lag(c, 5))-divide(q, lag(q, 5))),
        rs_line_from_high63_pct=100*(divide(relative, rolling(relative, 63, kind="max"))-1),
        close_pos=divide(c-l, h-l), rvol20=divide(v, avg_volume),
        rvol3_20=divide(rolling(v, 3), avg_volume), dollar_vol_today_vs20=divide(amount, avg_amount),
        gap_today_adr=divide(gap, lag(adr)), days_since_10pct_gap=since,
        inside_day=((h <= ph) & (l >= lag(l))).astype(float),
        nr7=(((h-l) <= minimum_range7) | np.isclose(h-l, minimum_range7, rtol=1e-12, atol=0)).astype(float),
        contract3_adr=divide(rolling(divide(h, l)-1, 3), adr),
        avwap_base_low_adr=anchor(50, l), avwap_base_high_adr=anchor(50, h, True),
        avwap_big_gap_adr=anchor(60, gap, True), option_rvol20=divide(option, rolling(option, 20, 10)),
        iv_pct=np.asarray(extras.get("iv", np.full(n, np.nan)), float),
        earn_days=np.minimum(np.asarray(extras.get("earn_days", np.full(n, np.nan)), float), 120),
        new_high252=(c >= rolling(ph, 252, 60, "max")).astype(float),
        new_high50=(c >= rolling(ph, 50, kind="max")).astype(float),
        from_high50_adr=divide(divide(c, rolling(h, 50, kind="max"))-1, adr),
        above_ema21_days20=rolling((c > e21).astype(float), 20, 15, "sum"),
        rs_pos_days20=rolling((rs21 > 0).astype(float), 20, 15, "sum"),
        up_days20=rolling((c > pc).astype(float), 20, 15, "sum"))
    for length, ma in ((9, e9), (21, e21), (50, e50)):
        out[f"ext_ema{length}_adr"] = divide(divide(c, ma)-1, adr)
    for length in (1, 5, 21, 63):
        out[f"perf{length}_pct"] = 100*(divide(c, lag(c, length))-1)
    return out


def legacy_cross_section(close, rows=None, *, scope_mask=None, block_size=128):
    """Earlier scope-peer definition, in bounded row blocks; default scope=market."""
    close = np.asarray(close, float)
    rows = np.arange(len(close)) if rows is None else np.asarray(rows, int)
    names = [s["name"] for s in LEGACY_SPEC if s["layer"] == "cross_section"]
    out = {name: np.full(len(rows), np.nan) for name in names}
    if close.shape[1] < 61:
        return out
    with np.errstate(divide="ignore", invalid="ignore"):
        returns = np.log(close[:, -60:]/close[:, -61:-1]).astype(np.float32)
    valid = np.isfinite(returns).sum(1) >= 40
    z = returns-np.nanmean(returns, axis=1, keepdims=True)
    z = np.nan_to_num(z)
    sd = np.sqrt((z*z).sum(1))
    z = np.where(sd[:, None] > 0, z/np.where(sd[:, None] > 0, sd[:, None], 1), 0)
    ret5, ret1 = np.nansum(returns[:, -5:], axis=1), returns[:, -1]
    scope = np.ones(len(close), bool) if scope_mask is None else np.asarray(scope_mask, bool)
    for start in range(0, len(rows), block_size):
        chosen = rows[start:start+block_size]
        peers = (z[chosen] @ z.T >= .5) & (valid & scope)[None, :]
        peers[np.arange(len(chosen)), chosen] = False
        for j, row in enumerate(chosen):
            if not valid[row] or not scope[row]:
                continue
            peer, dest = peers[j], start+j
            count = int(peer.sum())
            out["theme_peers_scope"][dest] = count
            out["theme_peers_moving"][dest] = np.sum(peer & (ret5 >= np.log(1.10)))
            if count:
                out["theme_peer_ret5"][dest] = float(np.nanmean(ret5[peer]))*100
                out["theme_peer_ret1"][dest] = float(np.nanmean(ret1[peer]))*100
    return out


def lag(x, n=1):
    out = np.full(len(x), np.nan)
    if n < len(x):
        out[n:] = x[:-n]
    return out


def divide(a, b):
    with np.errstate(all="ignore"):
        out = np.asarray(a) / np.asarray(b)
    return np.where(np.isfinite(out) & (np.asarray(b) != 0), out, np.nan)


def roll(x, n, kind="mean"):
    x = np.asarray(x, float)
    out = np.full(len(x), np.nan)
    if len(x) < n:
        return out
    windows = np.lib.stride_tricks.sliding_window_view(x, n)
    valid = np.isfinite(windows).all(1)
    if kind in ("sum", "mean"):
        cs = np.r_[0., np.cumsum(np.nan_to_num(x))]
        value = cs[n:] - cs[:-n]
        if kind == "mean":
            value /= n
    else:
        value = getattr(np, kind)(windows, axis=1)
    out[n-1:] = np.where(valid, value, np.nan)
    return out


def ema(x, n):
    out = np.full(len(x), np.nan)
    current = np.nan
    for i, value in enumerate(x):
        if math.isfinite(value):
            current = value if not math.isfinite(current) else current + 2/(n+1)*(value-current)
            out[i] = current
    return out


def rma(x, n):
    """Wilder smoothing, seeded with the first n consecutive valid observations."""
    out = np.full(len(x), np.nan)
    current = np.nan
    total, count = 0., 0
    for i, value in enumerate(x):
        if not math.isfinite(value):
            total, count = 0., 0
            continue
        if math.isfinite(current):
            current += (value-current)/n
        else:
            total += value
            count += 1
            if count == n:
                current = total/n
        out[i] = current
    return out


def rsi(x, n):
    change = x-lag(x)
    up, down = rma(np.maximum(change, 0), n), rma(np.maximum(-change, 0), n)
    result = 100*divide(up, up+down)
    return np.where((up == 0) & (down == 0), 50., result)


def age(flag):
    out = np.full(len(flag), np.nan)
    last = None
    for i, value in enumerate(flag):
        if value:
            last = i
        if last is not None:
            out[i] = i-last
    return out


def _rolling_anchor(values, window, high=True):
    """Latest trailing extremum; only one stock x <=252 bars is materialized."""
    n = len(values)
    if not n:
        return np.empty(0, int)
    padded = np.pad(values, (window-1, 0), constant_values=np.nan)
    w = np.lib.stride_tricks.sliding_window_view(padded, window)[:, ::-1]
    finite = np.isfinite(w)
    filled = np.where(finite, w, -np.inf if high else np.inf)
    offset = np.argmax(filled, axis=1) if high else np.argmin(filled, axis=1)
    return np.where(finite.any(axis=1), np.arange(n)-offset, -1)


def own_percentile(x, window=252, *, relative_ties=0.):
    out = np.full(len(x), np.nan)
    for i, value in enumerate(x):
        w = x[max(0, i-window+1):i+1]
        count = np.isfinite(w).sum()
        if np.isfinite(value) and count >= 2:
            tied = np.isclose(w, value, rtol=relative_ties, atol=relative_ties) if relative_ties else w == value
            out[i] = (((w < value) & ~tied).sum() + (tied.sum()-1)/2)/(count-1)*100
    return out


def supertrend(h, l, c):
    previous = lag(c)
    tr = np.fmax(h-l, np.fmax(abs(h-previous), abs(l-previous)))
    atr = rma(tr, 10)
    upper, lower = (h+l)/2+3*atr, (h+l)/2-3*atr
    line, direction = np.full(len(c), np.nan), np.full(len(c), np.nan)
    for i in range(len(c)):
        if not np.isfinite(atr[i]+c[i]):
            continue
        if i and np.isfinite(line[i-1]):
            upper[i] = upper[i] if upper[i] < upper[i-1] or c[i-1] > upper[i-1] else upper[i-1]
            lower[i] = lower[i] if lower[i] > lower[i-1] or c[i-1] < lower[i-1] else lower[i-1]
            if line[i-1] == upper[i-1]:
                direction[i] = 1 if c[i] > upper[i] else -1
            else:
                direction[i] = -1 if c[i] < lower[i] else 1
        else:
            direction[i] = -1
        line[i] = lower[i] if direction[i] > 0 else upper[i]
    return divide(c-line, atr), age(np.isfinite(lag(direction)) & (direction != lag(direction)))


def pin_bar(o, h, l, c):
    body, span, lower = abs(c-o), h-l, np.minimum(o, c)-l
    return (span > 0) & (lower >= 2*body) & (lower >= .6*span) & (c >= (h+l)/2)


def _volume_profile(h, l, c, v, adr, *, stable_ties=False):
    poc, position = np.full(len(c), np.nan), np.full(len(c), np.nan)
    logh, logl = np.log(h), np.log(l)
    for t in range(99, len(c)):
        a = t-99
        high, low, vol = logh[a:t+1], logl[a:t+1], v[a:t+1]
        if not np.isfinite(high+low+vol).all() or vol.sum() <= 0:
            continue
        bottom, top = low.min(), high.max()
        if top <= bottom:
            continue
        step = (top-bottom)/50
        left = np.clip(((low-bottom)/step).astype(int), 0, 49)
        right = np.clip(((high-bottom)/step).astype(int), 0, 49)
        mass = np.zeros(50)
        same = left == right
        mass += np.bincount(left[same], weights=vol[same], minlength=50)
        different = ~same
        ll, rr = left[different], right[different]
        rate = vol[different]/(high[different]-low[different])
        mass += np.bincount(ll, weights=rate*(bottom+(ll+1)*step-low[different]), minlength=50)
        mass += np.bincount(rr, weights=rate*(high[different]-(bottom+rr*step)), minlength=50)
        delta = np.bincount(ll+1, weights=rate*step, minlength=51)
        delta -= np.bincount(rr, weights=rate*step, minlength=51)
        mass += np.cumsum(delta)[:50]
        center = int(np.flatnonzero(np.isclose(mass, mass.max(), rtol=1e-12, atol=0))[0]) if stable_ties else int(np.argmax(mass))
        lo = hi = center
        total = mass[center]
        target = .7*mass.sum()
        while total < target*(1-1e-12 if stable_ties else 1) and (lo > 0 or hi < 49):
            if hi == 49 or (lo > 0 and mass[lo-1] >= mass[hi+1]*(1-1e-12 if stable_ties else 1)):
                lo -= 1
                total += mass[lo]
            else:
                hi += 1
                total += mass[hi]
        point = np.exp(bottom+(center+.5)*step)
        va_low, va_high = np.exp(bottom+lo*step), np.exp(bottom+(hi+1)*step)
        poc[t] = divide(c[t]/point-1, adr[t])
        position[t] = divide(c[t]-va_low, va_high-va_low)
    return poc, position


def _chan(h, l):
    """Causal inclusion merging and confirmed strokes, lookback 52/min gap 4."""
    n = len(h)
    bottom, buy2, buy3 = (np.zeros(n) for _ in range(3))
    pivot = np.full(n, np.nan)
    mh, ml, ends = [], [], []
    current = np.nan
    for t, (high, low) in enumerate(zip(h, l)):
        if not np.isfinite(high+low):
            continue
        if mh and ((high <= mh[-1] and low >= ml[-1]) or (high >= mh[-1] and low <= ml[-1])):
            op = max if len(mh) < 2 or mh[-1] > mh[-2] else min
            mh[-1], ml[-1] = op(mh[-1], high), op(ml[-1], low)
        else:
            mh.append(high)
            ml.append(low)
            k = len(mh)-2
            f = None
            if k >= 1:
                if mh[k] > mh[k-1] and mh[k] > mh[k+1]:
                    f = (1, mh[k], k)
                elif ml[k] < ml[k-1] and ml[k] < ml[k+1]:
                    f = (-1, ml[k], k)
                    bottom[t] = 1
            if f is not None:
                appended = False
                if not ends:
                    ends.append(f)
                    appended = True
                elif f[0] == ends[-1][0]:
                    if f[0]*(f[1]-ends[-1][1]) > 0:
                        ends[-1] = f
                elif f[2]-ends[-1][2] >= 4 and f[0]*(f[1]-ends[-1][1]) > 0:
                    ends.append(f)
                    appended = True
                if len(ends) >= 6:
                    e = ends[-6:]
                    if e[-1][0] < 0:
                        upper, lower = min(e[-6][1], e[-4][1]), max(e[-5][1], e[-3][1])
                        if upper > lower:
                            current = upper
                            if appended and e[-2][1] > upper and e[-1][1] > upper:
                                buy3[t] = 1
                if appended and f[0] < 0 and len(ends) >= 3:
                    floor = np.nanmin(l[max(0, t-51):t+1])
                    buy2[t] = float(ends[-1][1] > ends[-3][1] and ends[-3][1] <= floor+1e-12)
        pivot[t] = current
    return bottom, buy2, buy3, pivot


def _smc(o, h, l, c, adr):
    out = {name: np.full(len(c), np.nan) for name in
           ("smc_bos", "smc_choch", "smc_fvg_distance_adr", "smc_order_block_distance_adr", "smc_low_sweep")}
    bos, choch = np.zeros(len(c)), np.zeros(len(c))
    high = low = ob = np.nan
    hip = lop = -1
    bias, used, gaps = 0, set(), []
    for t in range(len(c)):
        if not np.isfinite(h[t]+l[t]+c[t]):
            continue
        p = t-2
        if p >= 2:
            if h[p] > max(h[p-2:p]) and h[p] > max(h[p+1:p+3]):
                high, hip = h[p], p
            if l[p] < min(l[p-2:p]) and l[p] < min(l[p+1:p+3]):
                low, lop = l[p], p
        out["smc_low_sweep"][t] = float(t > 0 and l[t] < low < c[t] and c[t-1] >= low)
        if t:
            for level, direction, pivot in ((high, 1, hip), (low, -1, lop)):
                cross = c[t-1] <= level < c[t] if direction > 0 else c[t-1] >= level > c[t]
                if cross and (direction, pivot) not in used:
                    (choch if bias and bias != direction else bos)[t] += direction
                    bias = direction
                    used.add((direction, pivot))
                    if direction > 0:
                        bears = np.flatnonzero(c[max(0, t-20):t] < o[max(0, t-20):t])
                        if len(bears):
                            ob = l[max(0, t-20)+bears[-1]]
        gaps = [(a, lower, min(upper, l[t])) for a, lower, upper in gaps if t-a <= 60 and l[t] > lower]
        if t >= 2 and l[t] > h[t-2]:
            gaps.append((t, h[t-2], l[t]))
        if gaps:
            out["smc_fvg_distance_adr"][t] = divide(min(abs((lo+hi)/2-c[t]) for _, lo, hi in gaps), c[t]*adr[t])
        out["smc_order_block_distance_adr"][t] = divide(divide(c[t], ob)-1, adr[t])
    out["smc_bos"], out["smc_choch"] = roll(bos, 20, "sum"), roll(choch, 20, "sum")
    return out


def _chips(h, l, c, v, *, stable_ties=False):
    out = {key: np.full(len(c), np.nan) for key in ("chip_profit_share", "chip_concentration90", "chip_overhang_share")}
    first = np.flatnonzero(np.isfinite(c) & (c > 0))
    if not len(first):
        return out
    scale = 100/c[first[0]]
    edges = np.exp(np.arange(math.log(.0001), math.log(1e6)+.02, .02))
    state = np.zeros(len(edges))
    turnover = np.clip(divide(v, 20*roll(v, 20)), 0, 1)
    for i in range(len(c)):
        if not np.isfinite(c[i]+h[i]+l[i]+turnover[i]) or l[i] <= 0:
            continue
        state *= 1-turnover[i]
        lo, hi = np.clip(np.searchsorted(edges, [l[i]*scale, h[i]*scale], side="right")-1, 0, len(edges)-1)
        state[lo:hi+1] += turnover[i]/(hi-lo+1)
        cum = np.cumsum(state)
        if cum[-1] <= 0:
            continue
        k = np.searchsorted(edges, c[i]*scale, side="right")-1
        profit = cum[min(k, len(edges)-1)]/cum[-1] if k >= 0 else 0.
        q5, q50, q95 = np.searchsorted(cum, cum[-1]*(np.array([.05, .5, .95])-(1e-12 if stable_ties else 0)))
        out["chip_profit_share"][i], out["chip_overhang_share"][i] = profit, 1-profit
        out["chip_concentration90"][i] = (edges[q95]-edges[q5])/edges[q50]
    return out


def _weekly(o, h, l, c, days):
    names = ("weekly_rsi14", "weekly_macd_hist_pct", "inside_week", "weekly_pin_bar",
             "weekly_close_position", "weekly_pivot_position", "weinstein_stage", "chan_weekly_buy")
    out = {name: np.full(len(c), np.nan) for name in names}
    if days is None or not len(c):
        return out
    keys = [date.fromisoformat(str(d)).isocalendar()[:2] for d in days]
    starts = np.r_[0, np.flatnonzero([a != b for a, b in zip(keys[1:], keys[:-1])])+1]
    stops = np.r_[starts[1:], len(c)]
    wc = c[stops-1]
    wh, wl = np.full(len(starts), np.nan), np.full(len(starts), np.nan)
    for k, (a, b) in enumerate(zip(starts, stops)):
        if np.isfinite(h[a:b]).any():
            wh[k], wl[k] = np.nanmax(h[a:b]), np.nanmin(l[a:b])
    change = wc-lag(wc)
    up, down = rma(np.maximum(change, 0), 14), rma(np.maximum(-change, 0), 14)
    e12, e26 = ema(wc, 12), ema(wc, 26)
    signal = ema(e12-e26, 9)
    wma = roll(wc, 30)
    _, wb2, wb3, _ = _chan(wh, wl)
    for k, (a, b) in enumerate(zip(starts, stops)):
        high = low = opening = np.nan
        for t in range(a, b):
            if not np.isfinite(c[t]+h[t]+l[t]+o[t]):
                continue
            opening = o[t] if not np.isfinite(opening) else opening
            high, low = np.fmax(high, h[t]), np.fmin(low, l[t])
            out["weekly_close_position"][t] = divide(c[t]-low, high-low)
            out["weekly_pin_bar"][t] = float(pin_bar(opening, high, low, c[t]))
            if not k:
                out["weekly_macd_hist_pct"][t] = 0.
                continue
            out["inside_week"][t] = float(high <= wh[k-1] and low >= wl[k-1]) if np.isfinite(wh[k-1]+wl[k-1]) else np.nan
            d = c[t]-wc[k-1]
            seed = change[max(1, k-13):k]
            if not np.isfinite(up[k-1]) and len(seed) == 13 and np.isfinite(seed).all():
                u, dn = (np.maximum(seed, 0).sum()+max(d, 0))/14, (np.maximum(-seed, 0).sum()+max(-d, 0))/14
            else:
                u, dn = (up[k-1]*13+max(d, 0))/14, (down[k-1]*13+max(-d, 0))/14
            out["weekly_rsi14"][t] = 50 if u == dn == 0 else 100*divide(u, u+dn)
            fast = e12[k-1]+2/13*(c[t]-e12[k-1]) if np.isfinite(e12[k-1]) else c[t]
            slow = e26[k-1]+2/27*(c[t]-e26[k-1]) if np.isfinite(e26[k-1]) else c[t]
            sig = signal[k-1]+2/10*(fast-slow-signal[k-1]) if np.isfinite(signal[k-1]) else fast-slow
            out["weekly_macd_hist_pct"][t] = 100*divide(fast-slow-sig, c[t])
            p = (wh[k-1]+wl[k-1]+wc[k-1])/3
            s1, r1 = 2*p-wh[k-1], 2*p-wl[k-1]
            out["weekly_pivot_position"][t] = divide(c[t]-s1, r1-s1)
            out["chan_weekly_buy"][t] = float(wb2[k-1] or wb3[k-1])
            if k >= 33:
                ma = (wc[k-29:k].sum()+c[t])/30
                slope = ma-wma[k-4]
                if np.isfinite(ma+slope):
                    out["weinstein_stage"][t] = 2 if c[t] > ma and slope > 0 else 4 if c[t] < ma and slope < 0 else 1 if c[t] <= ma else 3
    return out


def price_extremes(c, h, l):
    return {name+"_distance_pct": 100*(divide(c, values)-1)
            for name, values in (("high252", roll(h, 252, "max")),
                                 ("high50", roll(h, 50, "max")), ("low252", roll(l, 252, "min")))}


def per_stock(arrays, benchmark, extras=None, *, version="v1.1", names=None):
    """Return all time-series representatives in SPEC order, never cross-sectional proxies."""
    extras = extras or {}
    o, h, l, c, v, amount = (np.asarray(arrays[k], float) for k in ("o", "h", "l", "c", "v", "t"))
    n = len(c)
    q = np.asarray(benchmark["c"] if isinstance(benchmark, dict) else benchmark, float)
    if any(x.shape != (n,) for x in (o, h, l, c, v, amount, q)):
        raise ValueError("all arrays and benchmark must share a one-dimensional session axis")
    if names is not None:
        # IE47 only needs these existing groups; avoid volume-profile/chip work for every live stock.
        names = tuple(names)
        supported = set(LEGACY_NAMES) | {"low252_distance_pct", "weekly_rsi14", "weinstein_stage",
                                         "chan_weekly_buy", "smc_low_sweep"}
        if version != 'v1.1' or not set(names) <= supported:
            raise ValueError('unsupported indicator subset')
        selected = {}
        if set(names) & set(LEGACY_NAMES):
            selected.update(legacy_per_stock(arrays, benchmark, extras))
        if 'low252_distance_pct' in names:
            selected.update(price_extremes(c, h, l))
        if set(names) & {'weekly_rsi14', 'weinstein_stage', 'chan_weekly_buy'}:
            selected.update(_weekly(o, h, l, c, arrays.get('days', extras.get('days'))))
        if 'smc_low_sweep' in names:
            selected.update(_smc(o, h, l, c, roll(divide(h, l)-1, 20)))
        return {name: np.where(np.isfinite(c) & np.isfinite(selected[name]), selected[name], np.nan)
                for name in names}
    nan = np.full(n, np.nan)

    def extra(key):
        value = np.asarray(extras.get(key, nan), float)
        if value.shape != (n,):
            raise ValueError("extra shape differs: " + key)
        return value

    out = {}
    pc, ph, pl = lag(c), lag(h), lag(l)
    change = c-pc
    adr = roll(divide(h, l)-1, 20)
    tr = np.fmax(h-l, np.fmax(abs(h-pc), abs(l-pc)))
    atr14, atr20 = rma(tr, 14), rma(tr, 20)
    e9, e21, e50 = (ema(c, k) for k in (9, 21, 50))
    ma50, ma150, ma200 = (roll(c, k) for k in (50, 150, 200))
    for k, e in ((9, e9), (21, e21), (50, e50)):
        out[f"ema{k}_distance_adr"] = divide(divide(c, e)-1, adr)
    out["sma150_distance_pct"], out["sma200_distance_pct"] = 100*(divide(c, ma150)-1), 100*(divide(c, ma200)-1)
    for name, ma in (("ema21", e21), ("sma50", ma50), ("sma200", ma200)):
        out[name+"_slope10_pct"] = 100*(divide(ma, lag(ma, 10))-1)
    out["ema_stack"] = ((e9 > e21) & (e21 > e50)).astype(float)
    out["above_ema21_days20"] = roll(np.where(np.isfinite(c+e21), (c > e21).astype(float), np.nan), 20, "sum")
    out["supertrend_distance"], out["supertrend_flip_days"] = supertrend(h, l, c)
    mid = lambda k: (roll(h, k, "max")+roll(l, k, "min"))/2
    sa, sb = lag((mid(9)+mid(26))/2, 26), lag(mid(52), 26)
    out["ichimoku_cloud_position"] = divide(c-np.minimum(sa, sb), abs(sa-sb))
    dh, dl = h-ph, pl-l
    plus = 100*divide(rma(np.where(np.isfinite(dh+dl), np.where((dh > dl) & (dh > 0), dh, 0), np.nan), 14), atr14)
    minus = 100*divide(rma(np.where(np.isfinite(dh+dl), np.where((dl > dh) & (dl > 0), dl, 0), np.nan), 14), atr14)
    dx = 100*divide(abs(plus-minus), plus+minus)
    dx = np.where((plus == 0) & (minus == 0), 0, dx)
    out["adx14"], out["di_spread14"] = rma(dx, 14), plus-minus
    out["choppiness14"] = 100*np.log10(divide(roll(tr, 14, "sum"), roll(h, 14, "max")-roll(l, 14, "min")))/np.log10(14)
    out["rsi14"], out["rsi2"] = rsi(c, 14), rsi(c, 2)
    out["stochastic_k"] = 100*divide(c-roll(l, 14, "min"), roll(h, 14, "max")-roll(l, 14, "min"))
    r = out["rsi14"]
    out["stochastic_rsi"] = roll(100*divide(r-roll(r, 14, "min"), roll(r, 14, "max")-roll(r, 14, "min")), 3)
    macd = ema(c, 12)-ema(c, 26)
    out["macd_hist_pct"] = 100*divide(macd-ema(macd, 9), c)
    out["macd_hist_change5"] = out["macd_hist_pct"]-lag(out["macd_hist_pct"], 5)
    tp = (h+l+c)/3
    mean = roll(tp, 20)
    mad = nan.copy()
    if n >= 20:
        mad[19:] = np.mean(abs(np.lib.stride_tricks.sliding_window_view(tp, 20)-mean[19:, None]), axis=1)
    out["cci20"] = divide(tp-mean, .015*mad)
    for k in (1, 5, 21, 63):
        out[f"return{k}_pct"] = 100*(divide(c, lag(c, k))-1)
    out["excess21_pct"] = out["return21_pct"]-100*(divide(q, lag(q, 21))-1)
    relative = divide(c, q)
    out["rs_line_high63_pct"] = 100*(divide(relative, roll(relative, 63, "max"))-1)
    out["outperform_days20"] = roll(np.where(np.isfinite(out["excess21_pct"]), (out["excess21_pct"] > 0).astype(float), np.nan), 20, "sum")
    out["up_days20"] = roll(np.where(np.isfinite(change), (change > 0).astype(float), np.nan), 20, "sum")
    lr, qr = np.log(divide(c, pc)), np.log(divide(q, lag(q)))
    out["beta60"] = divide(roll(lr*qr, 60)-roll(lr, 60)*roll(qr, 60), roll(qr, 60, "std")**2)
    out["close_position"] = divide(c-l, h-l)
    streak = np.zeros(n)
    for i in range(1, n):
        s = np.sign(change[i])
        streak[i] = streak[i-1]+s if np.sign(streak[i-1]) == s else s
    out["signed_streak"] = streak
    out["sma5_distance_atr"] = divide(c-roll(c, 5), atr14)
    ma20, sd20 = roll(c, 20), roll(c, 20, "std")
    out["bollinger_percent_b"] = divide(c-ma20+2*sd20, 4*sd20)
    out["adr20_pct"] = adr*100
    out["range_adr"], out["range3_adr"] = divide(divide(h, l)-1, adr), divide(roll(divide(h, l)-1, 3), adr)
    out["bollinger_width_percentile252"] = own_percentile(divide(4*sd20, ma20), relative_ties=1e-12 if version == 'v1.1' else 0)
    squeeze = (2*sd20 < 1.5*atr20) & np.isfinite(sd20+atr20)
    out["ttm_squeeze_days"] = np.zeros(n)
    for i in range(n):
        if squeeze[i]:
            out["ttm_squeeze_days"][i] = (out["ttm_squeeze_days"][i-1] if i else 0)+1
    out["ttm_squeeze_days"] = np.where(np.isfinite(sd20+atr20), out["ttm_squeeze_days"], np.nan)
    hi20, lo20 = roll(h, 20, "max"), roll(l, 20, "min")
    out["donchian20_position"] = divide(c-lo20, hi20-lo20)
    for name, condition, valid in (
            ("breakout55", c > roll(ph, 55, "max"), roll(ph, 55, "max")),
            ("inside_day", (h <= ph) & (l >= pl), ph+pl),
            ("nr7", h-l <= roll(h-l, 7, "min"), roll(h-l, 7, "min")),
            ("outside_day", (h > ph) & (l < pl), ph+pl)):
        out[name] = np.where(np.isfinite(valid), condition.astype(float), np.nan)
    out["dollar_volume20"] = roll(amount, 20)
    out["relative_volume"], out["relative_volume3"] = divide(v, roll(v, 20)), divide(roll(v, 3), roll(v, 20))
    obv = np.cumsum(np.nan_to_num(np.sign(change)*v))
    out["obv_high20_distance"] = divide(obv-roll(obv, 20, "max"), roll(v, 20, "sum"))
    multiplier = np.where(h == l, 0., divide(2*c-h-l, h-l))
    out["cmf20"] = divide(roll(multiplier*v, 20, "sum"), roll(v, 20, "sum"))
    flow = tp*v
    flow_valid = np.isfinite(tp+lag(tp)+v)
    pos = roll(np.where(flow_valid, np.where(tp > lag(tp), flow, 0), np.nan), 14, "sum")
    neg = roll(np.where(flow_valid, np.where(tp < lag(tp), flow, 0), np.nan), 14, "sum")
    out["mfi14"] = 100*divide(pos, pos+neg)
    out["up_down_volume50"] = divide(roll(np.where(change > 0, v, 0), 50, "sum"), roll(np.where(change < 0, v, 0), 50, "sum"))
    pvi = np.cumprod(1+np.where(v > lag(v), np.nan_to_num(divide(c, pc)-1), 0))*1000
    pvi = np.where(np.isfinite(c), pvi, np.nan)
    out["pvi_sma255_distance_pct"] = 100*(divide(pvi, roll(pvi, 255))-1)
    pv, vv = np.r_[0., np.cumsum(np.nan_to_num(tp*v))], np.r_[0., np.cumsum(np.nan_to_num(v))]
    anchors = {key: np.full(n, -1, int) for key in ("high252", "low252", "high50", "low50", "gap", "earnings")}
    gap = divide(o, pc)-1
    big = age(gap >= .10)
    for key, values, window, high in (("high252", h, 252, True), ("low252", l, 252, False),
                                      ("high50", h, 50, True), ("low50", l, 50, False)):
        anchors[key] = _rolling_anchor(values, window, high)
    anchors["gap"] = np.where(np.isfinite(big), np.arange(n)-np.nan_to_num(big), -1).astype(int)
    earn = extra("earn_index")
    anchors["earnings"] = np.where(np.isfinite(earn) & (earn >= 0) & (earn <= np.arange(n)), earn, -1).astype(int)
    for key, anchor in anchors.items():
        start = np.maximum(anchor, 0)
        value = divide(pv[1:]-pv[start], vv[1:]-vv[start])
        out[f"avwap_{key}_distance_adr"] = np.where(anchor >= 0, divide(divide(c, value)-1, adr), np.nan)
    out["volume_profile_poc_distance_adr"], out["volume_profile_value_position"] = _volume_profile(h, l, c, v, adr, stable_ties=version == 'v1.1')
    out.update(price_extremes(c, h, l))
    for k in (252, 50):
        prev = roll(ph, k, "max")
        out[f"new_high{k}"] = np.where(np.isfinite(prev), (c >= prev).astype(float), np.nan)
    out["over_previous_high_adr"], out["gap_adr"] = divide(divide(c, ph)-1, adr), divide(gap, lag(adr))
    out["large_gap_days"] = big
    for name in ("unfilled_gap_above_distance_adr", "rising_swing_lows", "base_length", "base_depth_pct", "darvas_breakout", "ema21_retest_count"):
        out[name] = nan.copy()
    gaps, lows, box = [], [], np.nan
    count, armed, started = 0, False, False
    for t in range(n):
        if not np.isfinite(c[t]+h[t]+l[t]):
            continue
        gaps = [(a, upper) for a, upper in gaps if t-a < 252 and h[t] < upper]
        if t and h[t] < l[t-1]:
            gaps.append((t, l[t-1]))
        above = [(a, upper) for a, upper in gaps if upper > c[t]]
        if above:
            out["unfilled_gap_above_distance_adr"][t] = divide(above[-1][1]/c[t]-1, adr[t])
        p = t-2
        if p >= 2 and l[p] < min(l[p-2:p]) and l[p] < min(l[p+1:p+3]):
            lows.append(l[p])
        rising = 0
        for j in range(len(lows)-1, max(0, len(lows)-3), -1):
            if lows[j] > lows[j-1]:
                rising += 1
            else:
                break
        out["rising_swing_lows"][t] = rising
        a = anchors["high252"][t]
        if a >= 0:
            out["base_length"][t] = t-a
            out["base_depth_pct"][t] = 100*(1-np.nanmin(l[a:t+1])/h[a])
        p = t-3
        if p >= 19 and np.isfinite(h[p-19:t+1]).all() and h[p] >= max(h[p-19:p+1]) and np.all(h[p+1:t+1] < h[p]):
            box = h[p]
        out["darvas_breakout"][t] = float(c[t] > box) if np.isfinite(box) else np.nan
        if t and c[t] > e50[t] and c[t-1] <= e50[t-1]:
            count, armed, started = 0, False, True
        if started:
            if armed and l[t] <= e21[t]:
                count += 1
                armed = False
            if c[t] > e21[t]*(1+adr[t]):
                armed = True
            out["ema21_retest_count"][t] = count
    ranges = []
    for window, shift in ((5, 0), (5, 5), (10, 10), (20, 20)):
        high, low = roll(h, window, "max"), roll(l, window, "min")
        value = divide(high, low)-1
        ranges.append(lag(value, shift) if shift else value)
    out["vcp_contractions"] = np.where(np.isfinite(sum(ranges)), sum((a < b).astype(float) for a, b in zip(ranges, ranges[1:])), np.nan)
    out["high20_days"] = age(h >= roll(ph, 20, "max"))
    out["pullback_depth_adr"] = divide(divide(hi20, c)-1, adr)
    body, span = abs(c-o), h-l
    upper, lower = h-np.maximum(o, c), np.minimum(o, c)-l
    avg, rng = roll(lag(body), 10), roll(lag(span), 10)
    flags = dict(bullish_engulfing=(c > o) & (pc < lag(o)) & (o <= pc) & (c >= lag(o)),
                 pin_bar=pin_bar(o, h, l, c),
                 upper_pin_bar=(span > 0) & (upper >= 2*body) & (upper >= .6*span) & (c <= (h+l)/2),
                 doji=body <= .1*rng,
                 bullish_marubozu=(c > o) & (body > avg) & (upper <= .1*rng) & (lower <= .1*rng),
                 morning_star=(lag(c, 2) < lag(o, 2)) & (lag(body) < lag(avg)) & (lag(o) < lag(c, 2)) & (c > o) & (c > (lag(o, 2)+lag(c, 2))/2))
    for name, flag in flags.items():
        valid = np.isfinite(rng) if name in ("doji", "bullish_marubozu", "morning_star") else np.isfinite(pc) if name == "bullish_engulfing" else np.isfinite(span)
        out[name] = np.where(valid, flag.astype(float), np.nan)
    out["chan_bottom_fractal"], out["chan_buy2"], out["chan_buy3"], pivot = _chan(h, l)
    out["chan_pivot_distance_adr"] = divide(divide(c, pivot)-1, adr)
    out.update(_smc(o, h, l, c, adr))
    out.update(_chips(h, l, c, v, stable_ties=version == 'v1.1'))
    out.update(_weekly(o, h, l, c, arrays.get("days", extras.get("days"))))
    for key in ("h4_momentum", "h4_stack", "h4_coil", "h4_history"):
        out[key] = extra(key)
    iv, hv, ov = extra("iv"), extra("hv"), extra("option_volume")
    out["iv"], out["iv_percentile252"], out["iv_minus_hv"] = iv, own_percentile(iv), iv-hv
    out["option_relative_volume20"] = divide(ov, roll(ov, 20))
    out["put_call_volume_ratio"] = divide(extra("put_volume"), extra("call_volume"))
    out["put_call_oi_ratio"] = divide(extra("put_open_interest"), extra("call_open_interest"))
    oi = extra("option_open_interest")
    out["option_oi_change5_pct"] = 100*(divide(oi, lag(oi, 5))-1)
    out["earnings_days"], out["earnings_gap_pct"] = extra("earn_days"), nan.copy()
    for t, a in enumerate(anchors["earnings"]):
        if a >= 0:
            out["earnings_gap_pct"][t] = gap[a]*100
    out["potent_days20"] = roll(extra("pot"), 20, "sum")
    out["price"] = c.copy()
    assert set(out) == set(V1_PER_STOCK_NAMES)
    if version == "v1.1":
        out = {LEGACY_ALIASES.get(name, name): value for name, value in out.items()}
        out.update(legacy_per_stock(arrays, benchmark, extras))
        names = PER_STOCK_NAMES
    elif version == "v1":
        names = V1_PER_STOCK_NAMES
    else:
        raise ValueError("unknown indicator version: " + version)
    return {name: np.where(np.isfinite(c) & np.isfinite(out[name]), out[name], np.nan) for name in names}


def midrank(x):
    out = np.full(len(x), np.nan)
    valid = np.flatnonzero(np.isfinite(x))
    order = valid[np.argsort(x[valid], kind="stable")]
    if not len(order):
        return out
    starts = np.r_[0, np.flatnonzero(np.diff(x[order]) != 0)+1]
    stops = np.r_[starts[1:], len(order)]
    out[order] = np.repeat((starts+stops-1)/2/max(len(order)-1, 1)*100, stops-starts) if len(order) > 1 else 50
    return out


def cross_section(close, high, low, rows=None, *, pool_mask=None, block_size=128,
                  version="v1.1", scope_mask=None):
    """One evening: market x trailing sessions (at least 253 for RS/template).

    Only requested market row indices are emitted. Correlations use pairwise
    common valid observations, in <=block_size by market temporary blocks.
    ``pool_mask`` requests the separate own-scan peer count (outside SPEC).
    """
    close, high, low = (np.asarray(x, float) for x in (close, high, low))
    if close.ndim != 2 or high.shape != close.shape or low.shape != close.shape:
        raise ValueError("close/high/low must be aligned market x session matrices")
    m, t = close.shape
    rows = np.arange(m) if rows is None else np.asarray(rows, int)
    out = {name: np.full(len(rows), np.nan) for name in V1_CROSS_SECTION_NAMES}
    if version == "v1.1":
        out.update(legacy_cross_section(close, rows, scope_mask=scope_mask, block_size=block_size))
    elif version != "v1":
        raise ValueError("unknown indicator version: " + version)
    if pool_mask is not None:
        if np.asarray(pool_mask).shape != (m,):
            raise ValueError("pool mask must have one item per market stock")
        out["theme_peers_pool"] = np.full(len(rows), np.nan)
    if not t:
        return out
    now = close[:, -1]
    rs = np.zeros(m)
    if t >= 253:
        for k, weight in ((63, .4), (126, .2), (189, .2), (252, .2)):
            rs += weight*(divide(now, close[:, -1-k])-1)
        pct = midrank(rs)
        out["ibd_rs_percentile"] = pct[rows]
        ma50, ma150, ma200 = (np.mean(close[:, -k:], axis=1) for k in (50, 150, 200))
        old200 = np.mean(close[:, -220:-20], axis=1)
        floor, cap = np.min(low[:, -252:], axis=1), np.max(high[:, -252:], axis=1)
        conditions = (now > ma50, now > ma150, now > ma200, (ma50 > ma150) & (ma150 > ma200),
                      ma200 > old200, now >= 1.3*floor, now >= .75*cap, pct >= 70)
        score = sum(x.astype(float) for x in conditions)
        out["minervini_score"] = np.where(np.isfinite(ma200+old200+floor+cap+pct), score, np.nan)[rows]
    if t < 61:
        return out
    returns = np.log(divide(close[:, -60:], close[:, -61:-1]))
    finite = np.isfinite(returns)
    mask = finite.astype(float)
    raw = np.where(finite, returns, 0.)
    squared = raw*raw
    r1, r5, r21 = (100*(divide(now, close[:, -1-k])-1) for k in (1, 5, 21))
    for a in range(0, len(rows), block_size):
        chosen = rows[a:a+block_size]
        common = mask[chosen] @ mask.T
        sx, sy = raw[chosen] @ mask.T, mask[chosen] @ raw.T
        xx, yy = squared[chosen] @ mask.T, mask[chosen] @ squared.T
        xy = raw[chosen] @ raw.T
        covariance = xy-divide(sx*sy, common)
        denominator = np.sqrt(np.maximum(0, xx-divide(sx*sx, common))*np.maximum(0, yy-divide(sy*sy, common)))
        corr = divide(covariance, denominator)
        peers = (corr >= .5) & (common >= 40) & np.isfinite(now)[None, :]
        peers[np.arange(len(chosen)), chosen] = False
        for j, row in enumerate(chosen):
            dest = a+j
            if not np.isfinite(now[row]) or finite[row].sum() < 40:
                continue
            peer = peers[j]
            out["theme_peers"][dest] = peer.sum()
            out["theme_moving_peers"][dest] = np.sum(peer & (r5 >= 10))
            for name, values in (("theme_peer_return5_pct", r5), ("theme_peer_return1_pct", r1)):
                good = peer & np.isfinite(values)
                if good.any():
                    out[name][dest] = values[good].mean()
            members = np.flatnonzero(peer & np.isfinite(r21))
            if np.isfinite(r21[row]):
                out["theme_strength_percentile"][dest] = ((r21[members] < r21[row]).sum()+.5*(r21[members] == r21[row]).sum())/len(members)*100 if len(members) else 50
            if pool_mask is not None:
                out["theme_peers_pool"][dest] = np.sum(peer & pool_mask)
    return out
