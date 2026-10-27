# W34 结果：转折第一笔 B/S（TURN）

预登记：[W34_PREREG.md](../notes/W34_PREREG.md)。脚本：`code/w34_turn.py`，一次评测，运行 1010 秒。

## 结论

通过线未全部满足，**保持现行规则**：不改 `watch/smc_watch.py` 默认行为、不改看板说明、不加测试。

| 通过线 | SELL | BUY |
|---|---|---|
| 1. 早出来的笔净收益日聚类 t > −2 | **未过**（t=-3.26） | **未过**（t=-4.27） |
| 2. 相对同日基线转折笔的差 t > −2 | 过（32 天，差 1.83bp，t=0.72） | 过（32 天，差 5.93bp，t=3.30） |
| 3. 等待根数中位数低于基线转折笔 | 过（3.0 vs 10.0） | 过（2.0 vs 10.0） |
| 4. `python3 watch/test_watch.py` | 过 | |

## 数据与计数

`old1m.csv.gz`，按预登记修订抽样：恒指当日涨跌四档 × 8 天 = 32 天（2025-12-03、2025-12-09、2025-12-19、2026-01-07、2026-01-08、2026-01-09、2026-01-12、2026-01-13、2026-01-14、2026-01-16、2026-01-21、2026-01-22、2026-01-29、2026-02-02、2026-02-03、2026-02-09、2026-02-16、2026-03-03、2026-03-10、2026-03-16、2026-03-19、2026-03-24、2026-04-09、2026-04-13、2026-04-21、2026-04-23、2026-05-08、2026-05-11、2026-05-12、2026-05-14、2026-05-15、2026-05-22），剔除 HK.800000 后 4383 个 (code, 日期)。关掉 TURN 的候选循环与现行 `marks()` 在抽查的 877 个 stock-day 逐条一致。

| | SELL | BUY |
|---|---:|---:|
| 基线标注 | 35320 | 30780 |
| 候选标注 | 36581 | 32877 |
| 候选中含 TURN | 1868 | 2801 |
| 早出来的笔（含不满 30 根被丢弃） | 1500 | 2416 |
| 基线转折笔（同上） | 11095 | 10784 |

TURN 与现行规则同根反向而作废：15 次；多空 TURN 同根同时触发而作废：0 次。

## 收益与等待

入场第 i+1 根收盘、出场第 i+31 根收盘，净 = 毛 − 10bp；t 按日历交易日聚类（先取每日所有标的平均）。等待根数 = 本段极端点到标注根。

| 组 | 笔数 | 交易日 | 净均值 bp | 日聚类 t | 等待 p50 | 等待 p75 |
|---|---:|---:|---:|---:|---:|---:|
| 早出来的SELL | 1322 | 32 | -10.90 | -3.26 | 3.0 | 5.8 |
| 早出来的SELL tpb≥2 | 642 | 32 | -10.72 | -1.46 | 3.0 | 5.0 |
| 早出来的SELL tpb<2 | 680 | 32 | -11.08 | -4.77 | 3.0 | 6.0 |
| 基线转折SELL | 10344 | 32 | -9.63 | -4.11 | 10.0 | 23.0 |
| 基线转折SELL tpb≥2 | 5114 | 32 | -7.02 | -2.03 | 13.0 | 24.0 |
| 基线转折SELL tpb<2 | 5230 | 32 | -12.19 | -8.07 | 8.0 | 17.0 |
| 早出来的BUY | 2159 | 32 | -11.61 | -4.27 | 2.0 | 5.0 |
| 早出来的BUY tpb≥2 | 1027 | 32 | -11.24 | -3.03 | 2.0 | 5.0 |
| 早出来的BUY tpb<2 | 1132 | 32 | -11.94 | -4.82 | 3.0 | 6.0 |
| 基线转折BUY | 10051 | 32 | -14.19 | -7.38 | 10.0 | 21.0 |
| 基线转折BUY tpb≥2 | 4795 | 32 | -13.23 | -4.80 | 12.0 | 24.0 |
| 基线转折BUY tpb<2 | 5256 | 32 | -15.06 | -11.39 | 8.0 | 17.0 |

早出来的笔比基线同方向下一条标注提前的根数（之后基线当天没有同向标注的不计）：

| | 有对照 / 全部 | 提前 p50 | 提前 p75 |
|---|---:|---:|---:|
| SELL | 842 / 1322 | 18.0 | 51.0 |
| BUY | 1319 / 2159 | 23.0 | 60.5 |

按恒指当日涨跌分档（不作门槛）：

| 档 | 组 | 笔数 | 交易日 | 净均值 bp | 日聚类 t |
|---|---|---:|---:|---:|---:|
| 大跌 | 早出来的SELL | 220 | 8 | -4.32 | -0.79 |
| 大跌 | 基线转折SELL | 2578 | 8 | -0.47 | 0.17 |
| 大跌 | 早出来的BUY | 731 | 8 | -16.04 | -5.41 |
| 大跌 | 基线转折BUY | 2230 | 8 | -22.60 | -6.38 |
| 小跌 | 早出来的SELL | 310 | 8 | -6.91 | -1.29 |
| 小跌 | 基线转折SELL | 2539 | 8 | -5.71 | -2.25 |
| 小跌 | 早出来的BUY | 586 | 8 | -16.09 | -7.10 |
| 小跌 | 基线转折BUY | 2395 | 8 | -16.28 | -9.63 |
| 小涨 | 早出来的SELL | 346 | 8 | -8.39 | -2.69 |
| 小涨 | 基线转折SELL | 2529 | 8 | -13.26 | -2.73 |
| 小涨 | 早出来的BUY | 421 | 8 | -4.17 | -0.93 |
| 小涨 | 基线转折BUY | 2671 | 8 | -12.39 | -4.81 |
| 大涨 | 早出来的SELL | 446 | 8 | -18.87 | -2.13 |
| 大涨 | 基线转折SELL | 2698 | 8 | -18.67 | -4.72 |
| 大涨 | 早出来的BUY | 421 | 8 | -5.10 | -0.34 |
| 大涨 | 基线转折BUY | 2755 | 8 | -7.30 | -1.40 |

## 单测

```
nd_missing_safe
ok test_hk_tick_table_and_a_share_tick
ok test_hsi_session_uses_closed_minutes_and_previous_close
ok test_marks_carry_their_tick_density
ok test_no_bold_marks_only_tick_bound_ones_are_dim
ok test_no_marks_during_the_opening_warmup
ok test_range_left_uses_latest_checkpoint_and_is_gated
ok test_restart_midday_reproduces_the_same_list
ok test_rsi_matches_wilder_on_a_known_series
ok test_run_counter_marks_repeats_on_one_side
ok test_same_side_same_tier_waits_fifteen_bars
ok test_session_bars_drops_the_minute_still_forming
ok test_session_bars_keeps_today_and_drops_the_auction
ok test_signal_strength_is_joint_and_missing_safe
ok test_structure_detects_bos_fvg_and_sweep
ok test_swing_ignores_unconfirmed_right_edge
ok test_swing_needs_both_sides_confirmed
ok test_swing_reference_on_the_wrong_side_is_flagged_not_hidden
ok test_tencent_daily_maps_close_high_low
ok test_tencent_m1_maps_ohlc_and_a_share_codes
ok test_the_fixture_breakout_is_marked_as_volume_confirmed
ok test_tick_bound_tape_is_shown_but_tagged
ok test_tick_density_uses_the_bar_date_not_the_replay_date
ok test_ticks_per_bar_skips_the_auction_print_and_is_causal
ok test_two_column_rows_fit_their_column
ok test_us_session_uses_new_york_clock
ok test_volume_only_decides_the_tier_not_the_trigger
ok test_volume_ratio_uses_only_the_previous_twenty_bars
ok test_watch_never_touches_the_trade_api
38 passed
...........
----------------------------------------------------------------------
Ran 11 tests in 0.079s

OK
```
