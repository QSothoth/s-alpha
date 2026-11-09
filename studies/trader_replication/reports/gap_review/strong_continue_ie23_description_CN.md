# IE23 全六半年描述：只描述，不从这份全段表选留出因子

全部 1847 规格 × 三种变换 = 5541 列；过滤后 35,533 个股票晚。真实六半年同侧 437 列，20 次同晚置换为 59–487 列，均值 164.6。真实数没有严格超过全部 20 次，不能把同侧列数本身当成可靠信号。

按全部池内行的精确 Spearman 秩相关、阈值严格大于 0.7 做代表式去重，共 1532 组，其中 89 组代表六半年同侧。代表按展开公式长度最短确定；缺失中性 0.5。这里不是相关传递闭包。

每笔在四个有效夜晚内先平均，再在半年内按笔等权；缺失不混成 50，观测不足的半年留空，覆盖分母则始终保留全部目标。完整 5541 列（含同侧数、平均偏离、有效笔数、成对差异）另存 factor_description.csv；全部分组及组内相关保留 groups JSON。

## 六半年同侧的因子组代表

| 代表（展开公式见 JSON） | 组内列数 | 2024H1 | 2024H2 | 2025H1 | 2025H2 | 2026H1 | 2026H2 | 同侧数 | 平均偏离/百分点 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| volume.rvol.3 | 11 | 45.7 | 42.0 | 41.4 | 46.3 | 44.4 | 35.3 | 6 | 7.5 |
| candles.hammer.20 | 1 | 49.8 | 49.9 | 49.6 | 49.5 | 49.6 | 49.8 | 6 | 0.3 |
| group.peer_excess.200 | 2 | 57.7 | 52.6 | 68.4 | 53.4 | 52.5 | 62.1 | 6 | 7.8 |
| momentum.aroon_up.3 | 5 | 35.7 | 36.1 | 36.7 | 39.9 | 48.0 | 45.9 | 6 | 9.6 |
| momentum.aroon_up.5 | 9 | 25.2 | 37.3 | 33.3 | 41.3 | 36.9 | 43.9 | 6 | 13.7 |
| statistics.maxindex.5 | 5 | 27.4 | 40.0 | 35.7 | 36.9 | 45.4 | 39.7 | 6 | 12.5 |
| candles.invertedhammer.20 | 1 | 49.7 | 49.5 | 49.2 | 49.7 | 49.4 | 48.5 | 6 | 0.7 |
| channels.squeeze.50 | 1 | 49.9 | 49.9 | 49.3 | 49.9 | 49.3 | 49.7 | 6 | 0.3 |
| price_transform.typprice.3 | 34 | 37.3 | 44.8 | 45.7 | 37.7 | 45.4 | 48.2 | 6 | 6.8 |
| group.peer_positive.3 | 5 | 47.3 | 40.5 | 32.4 | 46.0 | 43.3 | 49.0 | 6 | 6.9 |
| events.gap_count.3 | 2 | 48.9 | 47.3 | 49.6 | 49.1 | 49.0 | 48.9 | 6 | 1.2 |
| volume.nvi.10 | 5 | 13.7 | 45.5 | 31.4 | 36.8 | 49.4 | 34.4 | 6 | 14.8 |
| options.volume_change.5 | 11 | 46.5 | 41.4 | 47.9 | 47.7 | 35.8 | 42.2 | 6 | 6.4 |
| volume.price_volume_corr.100 | 2 | 51.8 | 73.5 | 64.5 | 62.7 | 50.3 | 55.8 | 6 | 9.8 |
| volume.price_volume_corr.20 | 3 | 61.4 | 64.3 | 55.3 | 60.8 | 62.3 | 87.0 | 6 | 15.2 |
| h4_history | 1 | 63.7 | 51.8 | 61.4 | 62.5 | 50.6 | 58.6 | 6 | 8.1 |
| h4_peers | 2 | 68.6 | 67.2 | 55.6 | 53.1 | 50.6 | 52.0 | 6 | 7.8 |
| options.iv.200__history250 | 1 | 36.0 | 17.7 | 37.1 | 37.6 | 44.6 | 36.1 | 6 | 15.1 |
| supertrend.direction.10 | 4 | 52.9 | 50.6 | 57.7 | 50.6 | 53.0 | 60.5 | 6 | 4.2 |
| volume.rvol.5__delta5 | 5 | 45.7 | 43.8 | 49.5 | 42.9 | 46.2 | 35.4 | 6 | 6.1 |
| channels.squeeze.50__history250 | 1 | 19.1 | 20.9 | 47.1 | 34.9 | 48.8 | 29.7 | 6 | 16.6 |
| momentum.adx.10__delta5 | 3 | 24.5 | 42.0 | 48.8 | 42.4 | 41.5 | 49.1 | 6 | 8.6 |
| momentum.adx.5__delta5 | 2 | 26.6 | 32.0 | 36.5 | 34.0 | 42.2 | 44.1 | 6 | 14.1 |
| overlap.ema.200__delta5 | 57 | 34.1 | 45.6 | 49.1 | 47.0 | 37.0 | 35.8 | 6 | 8.6 |
| momentum.dx.10 | 6 | 49.5 | 47.9 | 45.9 | 43.7 | 44.0 | 43.9 | 6 | 4.2 |
| momentum.plus_di.3__history250 | 8 | 31.8 | 36.2 | 44.5 | 34.3 | 41.8 | 46.7 | 6 | 10.8 |
| momentum.stoch_d.10__delta5 | 11 | 37.0 | 41.0 | 43.5 | 47.8 | 39.9 | 36.4 | 6 | 9.1 |
| momentum.stoch_d.200__delta5 | 7 | 23.7 | 49.4 | 43.7 | 49.2 | 41.5 | 33.2 | 6 | 9.9 |
| ichimoku.cross.0__delta5 | 3 | 50.3 | 55.9 | 50.6 | 56.6 | 54.2 | 65.0 | 6 | 5.4 |
| momentum.macd_hist.10__delta5 | 36 | 49.6 | 33.0 | 46.8 | 44.7 | 42.6 | 33.1 | 6 | 8.3 |
| statistics.correl.100 | 3 | 39.0 | 38.3 | 36.9 | 41.4 | 43.6 | 45.5 | 6 | 9.2 |
| statistics.correl.5 | 5 | 37.8 | 41.2 | 32.0 | 38.0 | 43.6 | 49.1 | 6 | 9.7 |
| smc.support_near.3__history250 | 1 | 78.5 | 62.0 | 66.3 | 56.1 | 57.1 | 58.1 | 6 | 13.0 |
| chips.cost_near.100__delta5 | 5 | 57.3 | 62.6 | 60.2 | 56.2 | 57.4 | 56.7 | 6 | 8.4 |
| group.peer_dispersion.10__delta5 | 1 | 52.4 | 68.0 | 64.7 | 55.4 | 53.2 | 73.4 | 6 | 11.2 |
| vcp.higher_low.10__delta5 | 1 | 55.7 | 56.8 | 57.5 | 60.1 | 54.5 | 71.6 | 6 | 9.4 |
| options.volume.100__delta5 | 2 | 83.6 | 54.7 | 53.3 | 61.4 | 53.6 | 62.0 | 6 | 11.4 |
| options.volume.200__delta5 | 1 | 98.7 | 51.2 | 59.6 | 59.7 | 50.8 | 55.8 | 6 | 12.6 |
| volume.nvi.20__history250 | 1 | 27.8 | 39.7 | 47.0 | 48.4 | 41.6 | 36.8 | 6 | 9.8 |
| candles.takuri.20 | 1 | 49.8 | 49.9 | 49.9 | 49.8 | 49.9 | 49.9 | 6 | 0.1 |
| candles.onneck.10 | 3 | 50.1 | 50.2 | 50.7 | 50.7 | 50.4 | 50.9 | 6 | 0.5 |
| events.high_count.3__delta5 | 2 | 32.7 | 37.1 | 28.6 | 48.6 | 47.0 | 43.6 | 6 | 10.4 |
| volume.price_volume_corr.100__history250 | 1 | 56.2 | 64.2 | 52.6 | 54.9 | 57.4 | 58.1 | 6 | 7.2 |
| overlap.sar.10__history250 | 6 | 41.7 | 33.7 | 31.3 | 48.1 | 36.5 | 48.8 | 6 | 10.0 |
| channels.high_age.5__delta5 | 1 | 28.3 | 44.3 | 24.7 | 42.3 | 38.5 | 40.7 | 6 | 13.5 |
| complexity.runs.20__delta5 | 1 | 16.2 | 48.3 | 42.9 | 47.3 | 43.0 | 42.7 | 6 | 9.9 |
| ichimoku.cloud.2__delta5 | 10 | 24.1 | 48.2 | 48.6 | 45.1 | 43.5 | 46.7 | 6 | 7.3 |
| events.gap_size.10__delta5 | 1 | 20.5 | 27.4 | 41.0 | 48.8 | 44.2 | 48.5 | 6 | 11.6 |
| smc.support_near.3__delta5 | 1 | 72.3 | 72.8 | 54.8 | 58.6 | 56.2 | 62.8 | 6 | 12.9 |
| momentum.stochrsi.10__history250 | 4 | 47.6 | 32.9 | 46.0 | 46.1 | 38.6 | 46.8 | 6 | 7.0 |
| complexity.efficiency.20__delta5 | 2 | 49.9 | 42.8 | 35.0 | 37.0 | 41.3 | 41.6 | 6 | 8.7 |
| group.peer_potent.5__history250 | 1 | 42.9 | 48.6 | 33.9 | 45.4 | 48.6 | 36.4 | 6 | 7.3 |
| avwap.volume.100__delta5 | 3 | 24.9 | 41.7 | 40.6 | 49.9 | 37.2 | 49.4 | 6 | 9.4 |
| avwap.volume.14__delta5 | 2 | 33.0 | 25.9 | 48.3 | 41.7 | 49.8 | 32.9 | 6 | 11.4 |
| volume.obv.10__delta5 | 2 | 27.2 | 39.0 | 40.3 | 49.2 | 36.1 | 40.9 | 6 | 11.2 |
| volume.obv.200__delta5 | 2 | 30.2 | 47.1 | 46.7 | 47.4 | 32.3 | 36.5 | 6 | 10.0 |
| volume.obv.3__delta5 | 3 | 37.0 | 36.7 | 40.6 | 42.9 | 42.0 | 34.1 | 6 | 11.1 |
| h4_coil__delta5 | 1 | 75.8 | 75.0 | 64.0 | 62.0 | 54.6 | 63.8 | 6 | 15.9 |
| candles.takuri.20__history250 | 1 | 33.9 | 44.0 | 37.3 | 42.6 | 39.6 | 45.3 | 6 | 9.6 |
| momentum.dx.10__delta5 | 3 | 49.0 | 34.7 | 38.1 | 49.3 | 43.4 | 40.8 | 6 | 7.5 |
| group.peer_return.100__delta5 | 1 | 38.1 | 45.2 | 48.6 | 45.4 | 47.5 | 28.1 | 6 | 7.9 |
| statistics.correl.100__delta5 | 1 | 30.0 | 38.9 | 34.9 | 41.2 | 37.7 | 30.9 | 6 | 14.4 |
| statistics.correl.200__delta5 | 1 | 22.5 | 44.6 | 41.9 | 40.6 | 41.1 | 33.7 | 6 | 12.6 |
| statistics.correl.20__delta5 | 1 | 18.6 | 45.8 | 41.3 | 42.2 | 30.9 | 23.5 | 6 | 16.3 |
| options.turnover.50__delta5 | 1 | 83.2 | 77.6 | 63.1 | 59.9 | 56.7 | 53.1 | 6 | 15.6 |
| volatility.choppiness.14__delta5 | 1 | 24.9 | 17.7 | 25.3 | 46.8 | 41.7 | 37.9 | 6 | 17.6 |
| candles.morningdojistar.10 | 3 | 49.6 | 49.6 | 49.8 | 49.4 | 49.7 | 49.5 | 6 | 0.4 |
| candles.thrusting.10__history250 | 3 | 40.1 | 46.4 | 30.6 | 43.2 | 31.6 | 43.2 | 6 | 10.8 |
| smc.range_position.3__delta5 | 3 | 27.5 | 38.8 | 41.8 | 45.7 | 46.3 | 38.9 | 6 | 10.2 |
| candles.belthold.5 | 1 | 50.7 | 55.1 | 54.3 | 50.6 | 53.5 | 50.6 | 6 | 2.5 |
| candles.eveningdojistar.10 | 3 | 51.6 | 50.2 | 50.3 | 50.3 | 50.3 | 50.9 | 6 | 0.6 |
| smc.order_block.5__delta5 | 1 | 27.7 | 45.9 | 49.8 | 43.0 | 40.1 | 48.3 | 6 | 7.5 |
| price_cycle.extended.10 | 1 | 48.6 | 48.2 | 49.6 | 49.0 | 48.6 | 49.7 | 6 | 1.0 |
| price_cycle.extended.20 | 1 | 49.9 | 44.0 | 48.0 | 46.3 | 47.2 | 49.0 | 6 | 2.6 |
| price_cycle.base_break.10 | 1 | 48.9 | 49.6 | 49.0 | 48.3 | 49.8 | 49.8 | 6 | 0.8 |
| price_cycle.wedge_drop.10 | 1 | 52.5 | 50.0 | 50.1 | 50.9 | 50.4 | 51.2 | 6 | 0.9 |
| candles.2crows.10 | 3 | 50.2 | 50.1 | 50.1 | 50.2 | 50.4 | 50.1 | 6 | 0.2 |
| statistics.beta.5__delta5 | 1 | 40.8 | 32.6 | 36.8 | 39.2 | 39.4 | 41.7 | 6 | 11.6 |
| candles.morningdojistar.10__history250 | 3 | 63.4 | 63.0 | 67.0 | 51.6 | 75.5 | 75.8 | 6 | 16.1 |
| momentum.mfi.5__delta5 | 1 | 40.6 | 31.8 | 49.1 | 43.7 | 42.5 | 33.9 | 6 | 9.7 |
| candles.mathold.10 | 3 | 48.3 | 48.9 | 49.1 | 47.4 | 48.2 | 47.4 | 6 | 1.8 |
| candles.belthold.5__delta5 | 1 | 71.1 | 54.6 | 51.2 | 58.9 | 54.0 | 54.3 | 6 | 7.4 |
| hilbert.dcperiod.16__delta5 | 1 | 65.3 | 50.5 | 51.6 | 53.2 | 52.2 | 50.8 | 6 | 3.9 |
| hilbert.trendmode.16__delta5 | 1 | 43.9 | 46.7 | 49.8 | 48.6 | 46.5 | 29.7 | 6 | 5.8 |
| hilbert.trendmode.4__delta5 | 2 | 43.5 | 49.3 | 31.9 | 48.1 | 49.0 | 40.8 | 6 | 6.2 |
| candles.ladderbottom.10 | 3 | 49.2 | 49.7 | 49.9 | 49.8 | 49.8 | 49.5 | 6 | 0.4 |
| candles.hikkake.10__delta5 | 3 | 47.0 | 37.9 | 45.0 | 40.0 | 48.9 | 44.1 | 6 | 6.2 |
| candles.counterattack.20__delta5 | 1 | 49.9 | 49.9 | 49.8 | 49.5 | 49.5 | 49.9 | 6 | 0.2 |
| candles.breakaway.10__delta5 | 3 | 53.6 | 52.0 | 60.2 | 57.7 | 51.3 | 51.1 | 6 | 4.3 |

## 20 次偶然基准

| 序号 | 六半年同侧列数 |
| --- | --- |
| 1 | 219 |
| 2 | 487 |
| 3 | 122 |
| 4 | 142 |
| 5 | 108 |
| 6 | 218 |
| 7 | 109 |
| 8 | 83 |
| 9 | 215 |
| 10 | 185 |
| 11 | 114 |
| 12 | 59 |
| 13 | 127 |
| 14 | 136 |
| 15 | 115 |
| 16 | 198 |
| 17 | 212 |
| 18 | 180 |
| 19 | 138 |
| 20 | 124 |

## IE9 被挤出目标的成对比较

22 笔目标、320 对股票晚比较；每个目标与它当晚 IE9 前五逐一配对，先笔内再半年等权。重复披露保留 IE9 的原分母，不把配对条数当独立交易。

| 代表 | 2024H1胜率%（有效笔） | 2024H2胜率%（有效笔） | 2025H1胜率%（有效笔） | 2025H2胜率%（有效笔） | 2026H1胜率%（有效笔） | 2026H2胜率%（有效笔） | 平均百分位差/百分点 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| statistics.r_squared.20 | 26.7（3） | 32.5（2） | 13.3（1） | 15.0（2） | 37.8（10） | 47.5（4） | -18.8 |
| momentum.aroon_down.20 | 96.7（3） | 67.5（2） | 63.3（1） | 53.8（2） | 61.5（10） | 62.9（4） | 15.6 |
| vcp.higher_low.10 | 76.7（3） | 57.5（2） | 93.3（1） | 52.5（2） | 71.0（10） | 79.2（4） | 20.1 |
| statistics.minindex.20__history250 | 98.3（3） | 75.0（2） | 60.0（1） | 67.5（2） | 67.3（10） | 80.8（4） | 24.0 |
| statistics.efficiency.3 | 66.7（3） | 52.5（2） | 86.7（1） | 68.8（2） | 66.0（10） | 80.0（4） | 19.3 |
| channels.width.3__history250 | 40.8（3） | 35.0（2） | 40.0（1） | 37.5（2） | 35.7（10） | 26.7（4） | -14.2 |
| momentum.adx.10__delta5 | 31.7（3） | 32.5（2） | 26.7（1） | 15.0（2） | 35.2（10） | 42.5（4） | -17.2 |
| momentum.adx.5__delta5 | 45.0（3） | 47.5（2） | 13.3（1） | 25.0（2） | 49.0（10） | 34.2（4） | -17.8 |
| price_transform.cos.10 | 73.3（3） | 65.0（2） | 73.3（1） | 60.0（2） | 54.2（10） | 80.8（4） | 16.5 |
| statistics.r_squared.20__delta5 | 23.3（3） | 45.0（2） | 26.7（1） | 35.0（2） | 36.0（10） | 23.3（4） | -14.0 |
| events.gap_count.100__delta5 | 6.7（3） | 42.5（2） | 20.0（1） | 20.0（2） | 43.5（10） | 32.9（4） | -19.6 |
| h4_coil__delta5 | 68.3（3） | 62.5（2） | 86.7（1） | 87.5（2） | 63.3（10） | 77.5（4） | 19.6 |
| candles.takuri.20__history250 | 15.0（3） | 33.7（2） | 20.0（1） | 46.2（2） | 50.0（10） | 25.4（4） | -20.8 |
| complexity.fractal.20__delta5 | 46.7（3） | 20.0（2） | 13.3（1） | 17.5（2） | 47.5（10） | 32.5（4） | -16.3 |
| hilbert.dcphase.16 | 30.0（3） | 47.5（2） | 0.0（1） | 40.0（2） | 26.3（10） | 20.0（4） | -21.1 |
| eom.value.200__delta5 | 0.0（3） | 35.0（2） | 33.3（1） | 35.0（2） | 42.6（10） | 31.7（4） | -19.8 |
| candles.belthold.5__delta5 | 85.8（3） | 61.2（2） | 80.0（1） | 66.3（2） | 50.6（10） | 58.7（4） | 17.6 |
| candles.ladderbottom.10__history250 | 50.8（3） | 65.0（2） | 60.0（1） | 65.0（2） | 61.1（10） | 81.3（4） | 13.8 |
| candles.breakaway.10 | 50.8（3） | 51.2（2） | 66.7（1） | 52.5（2） | 50.2（10） | 57.5（4） | 4.9 |

## 只用于诊断的入场日开盘

IE9 过滤后仍漏掉 22 笔，其中 4 笔入场日开盘跳空至少 2 个前日 ADR；0 笔同时满足‘紧邻前夜未检出本轮稳定代表的有向差异’；6 笔因紧邻前夜不在池或没有有效稳定组而无法判断。标签不是‘确定只能开盘看见’，不改变前夜前五尺子；前夜存在某个描述差异也不代表排序能选中。

| 股票 | 入场 | 前夜在池 | 前夜检出差异 | 开盘跳空/ADR | 前夜未检出且大跳空 |
| --- | --- | --- | --- | --- | --- |
| US.GME | 2024-05-13 | 是 | 是 | 4.5 | 否 |
| US.AMC | 2024-05-13 | 是 | 是 | 2.1 | 否 |
| US.AMC | 2024-05-13 | 是 | 是 | 2.1 | 否 |
| US.COIN | 2024-11-06 | 是 | 是 | 2.3 | 否 |
| US.SOUN | 2024-11-21 | 是 | 是 | 0.2 | 否 |
| US.BBAI | 2025-02-04 | 是 | 是 | 0.5 | 否 |
| US.AMD | 2025-10-01 | 否 | 无法判断 | -0.2 | 否 |
| US.ONDS | 2025-12-01 | 是 | 是 | -0.0 | 否 |
| US.MRVL | 2026-03-31 | 是 | 是 | 1.8 | 否 |
| US.MRVL | 2026-04-30 | 是 | 是 | 0.5 | 否 |
| US.NBIS | 2026-05-01 | 是 | 是 | 0.3 | 否 |
| US.IONQ | 2026-05-01 | 是 | 是 | -0.1 | 否 |
| US.QBTS | 2026-05-01 | 是 | 是 | -0.1 | 否 |
| US.ARM | 2026-05-18 | 是 | 是 | 0.0 | 否 |
| US.IONQ | 2026-05-20 | 是 | 是 | 0.2 | 否 |
| US.CRWD | 2026-06-18 | 否 | 无法判断 | 0.1 | 否 |
| US.GLW | 2026-06-18 | 否 | 无法判断 | 0.6 | 否 |
| US.NET | 2026-06-26 | 否 | 无法判断 | -0.1 | 否 |
| US.NET | 2026-07-21 | 是 | 是 | 0.0 | 否 |
| US.NET | 2026-07-29 | 否 | 无法判断 | 0.0 | 否 |
| US.PANW | 2026-07-29 | 否 | 无法判断 | 0.0 | 否 |
| US.CRCL | 2026-08-11 | 是 | 是 | 0.4 | 否 |

## 每组的最短公式

| 代表 | 公式 | 组内列数 |
| --- | --- | --- |
| candles.doji.10 | pool_pct(B(doji)) | 3 |
| momentum.rocr.10 | pool_pct(c/c[-n]) | 100 |
| momentum.rocr.100 | pool_pct(c/c[-n]) | 77 |
| momentum.rocr.20 | pool_pct(c/c[-n]) | 70 |
| momentum.rocr.200 | pool_pct(c/c[-n]) | 50 |
| momentum.rocr.3 | pool_pct(c/c[-n]) | 107 |
| momentum.rocr.5 | pool_pct(c/c[-n]) | 118 |
| momentum.rocr.50 | pool_pct(c/c[-n]) | 96 |
| g1 | pool_pct(c/c[-1]-1) | 32 |
| volume.dollar_volume.10 | pool_pct(mean(T,n)) | 18 |
| kst.hist.1 | pool_pct(KST-signal) | 2 |
| kst.hist.2 | pool_pct(KST-signal) | 3 |
| kst.hist.3 | pool_pct(KST-signal) | 2 |
| minervini.above50.100 | pool_pct(1(c>SMA50)) | 4 |
| close_position | pool_pct((c-l)/(h-l)) | 3 |
| eom.change.10 | pool_pct(EOM-EOM[-5]) | 3 |
| eom.change.100 | pool_pct(EOM-EOM[-5]) | 3 |
| eom.change.14 | pool_pct(EOM-EOM[-5]) | 3 |
| eom.change.20 | pool_pct(EOM-EOM[-5]) | 3 |
| eom.change.200 | pool_pct(EOM-EOM[-5]) | 3 |
| eom.change.3 | pool_pct(EOM-EOM[-5]) | 9 |
| eom.change.50 | pool_pct(EOM-EOM[-5]) | 3 |
| minervini.above150.100 | pool_pct(1(c>SMA150)) | 8 |
| options.iv_change.10 | pool_pct(iv/iv[-n]-1) | 8 |
| options.iv_change.100 | pool_pct(iv/iv[-n]-1) | 2 |
| options.iv_change.20 | pool_pct(iv/iv[-n]-1) | 2 |
| options.iv_change.200 | pool_pct(iv/iv[-n]-1) | 1 |
| options.iv_change.3 | pool_pct(iv/iv[-n]-1) | 3 |
| options.iv_change.5 | pool_pct(iv/iv[-n]-1) | 8 |
| options.iv_change.50 | pool_pct(iv/iv[-n]-1) | 2 |
| volume.rvol.10 | pool_pct(v/mean(v,n)) | 17 |
| volume.rvol.100 | pool_pct(v/mean(v,n)) | 12 |
| volume.rvol.3 | pool_pct(v/mean(v,n)) | 11 |
| momentum.adx.10 | pool_pct(Wilder(DX,n)) | 11 |
| momentum.adx.200 | pool_pct(Wilder(DX,n)) | 3 |
| momentum.adx.3 | pool_pct(Wilder(DX,n)) | 11 |
| momentum.adx.50 | pool_pct(Wilder(DX,n)) | 3 |
| price_transform.max.10 | pool_pct(c/max(c,n)-1) | 38 |
| price_transform.max.100 | pool_pct(c/max(c,n)-1) | 36 |
| price_transform.min.10 | pool_pct(c/min(c,n)-1) | 8 |
| volatility.natr.10 | pool_pct(100*ATR(n)/c) | 82 |
| volatility.natr.100 | pool_pct(100*ATR(n)/c) | 8 |
| options.iv_hv.10 | pool_pct(mean(iv/hv,n)) | 20 |
| options.iv_hv.100 | pool_pct(mean(iv/hv,n)) | 3 |
| options.iv_hv.200 | pool_pct(mean(iv/hv,n)) | 2 |
| options.iv_spread.50 | pool_pct(mean(iv-hv,n)) | 1 |
| price_transform.div.14 | pool_pct(mean(c/o-1,n)) | 7 |
| momentum.stoch_d.20 | pool_pct(SMA(stoch_k,3)) | 37 |
| force.change.3 | pool_pct(force-force[-5]) | 41 |
| candles.hammer.10 | pool_pct(B(hammer&~trend)) | 1 |
| candles.hammer.20 | pool_pct(B(hammer&~trend)) | 1 |
| candles.hammer.5 | pool_pct(B(hammer&~trend)) | 1 |
| candles.hangingman.10 | pool_pct(-B(hammer&trend)) | 3 |
| channels.keltner_width.10 | pool_pct(-4*ATRn/EMA(c,n)) | 13 |
| group.peer_excess.10 | pool_pct(g(n)-peer_return) | 5 |
| group.peer_excess.100 | pool_pct(g(n)-peer_return) | 3 |
| group.peer_excess.20 | pool_pct(g(n)-peer_return) | 2 |
| group.peer_excess.200 | pool_pct(g(n)-peer_return) | 2 |
| group.peer_excess.3 | pool_pct(g(n)-peer_return) | 6 |
| group.peer_excess.50 | pool_pct(g(n)-peer_return) | 3 |
| ichimoku.cross.2 | pool_pct((tenkan-kijun)/c) | 9 |
| momentum.macd_hist.14 | pool_pct(macd-macd_signal) | 26 |
| statistics.r_squared.10 | pool_pct(corr(c,time,n)^2) | 3 |
| statistics.r_squared.100 | pool_pct(corr(c,time,n)^2) | 2 |
| statistics.r_squared.14 | pool_pct(corr(c,time,n)^2) | 3 |
| statistics.r_squared.20 | pool_pct(corr(c,time,n)^2) | 2 |
| statistics.r_squared.200 | pool_pct(corr(c,time,n)^2) | 1 |
| statistics.r_squared.3 | pool_pct(corr(c,time,n)^2) | 3 |
| statistics.r_squared.5 | pool_pct(corr(c,time,n)^2) | 3 |
| statistics.r_squared.50 | pool_pct(corr(c,time,n)^2) | 2 |
| elder.bear.3 | pool_pct((l-EMA(c,n))/ATRn) | 6 |
| elder.bull.3 | pool_pct((h-EMA(c,n))/ATRn) | 7 |
| momentum.aroon_up.10 | pool_pct(argmax(h,n)/(n-1)) | 9 |
| momentum.aroon_up.100 | pool_pct(argmax(h,n)/(n-1)) | 6 |
| momentum.aroon_up.20 | pool_pct(argmax(h,n)/(n-1)) | 15 |
| momentum.aroon_up.200 | pool_pct(argmax(h,n)/(n-1)) | 4 |
| momentum.aroon_up.3 | pool_pct(argmax(h,n)/(n-1)) | 5 |
| momentum.aroon_up.5 | pool_pct(argmax(h,n)/(n-1)) | 9 |
| momentum.aroon_up.50 | pool_pct(argmax(h,n)/(n-1)) | 8 |
| peer_rank | pool_pct(original peer_rank) | 5 |
| price_transform.add.10 | pool_pct(mean((h+l)/c-2,n)) | 4 |
| price_transform.add.100 | pool_pct(mean((h+l)/c-2,n)) | 3 |
| price_transform.add.20 | pool_pct(mean((h+l)/c-2,n)) | 2 |
| price_transform.add.3 | pool_pct(mean((h+l)/c-2,n)) | 4 |
| statistics.maxindex.14 | pool_pct(argmax(c,n)/(n-1)) | 3 |
| statistics.maxindex.3 | pool_pct(argmax(c,n)/(n-1)) | 6 |
| statistics.maxindex.5 | pool_pct(argmax(c,n)/(n-1)) | 5 |
| candles.invertedhammer.10 | pool_pct(B(inverted&~trend)) | 1 |
| candles.invertedhammer.20 | pool_pct(B(inverted&~trend)) | 1 |
| candles.invertedhammer.5 | pool_pct(B(inverted&~trend)) | 1 |
| candles.shootingstar.10 | pool_pct(-B(inverted&trend)) | 3 |
| momentum.aroon_down.10 | pool_pct(-argmin(l,n)/(n-1)) | 3 |
| momentum.aroon_down.100 | pool_pct(-argmin(l,n)/(n-1)) | 3 |
| momentum.aroon_down.14 | pool_pct(-argmin(l,n)/(n-1)) | 5 |
| momentum.aroon_down.20 | pool_pct(-argmin(l,n)/(n-1)) | 3 |
| momentum.aroon_down.200 | pool_pct(-argmin(l,n)/(n-1)) | 2 |
| momentum.aroon_down.3 | pool_pct(-argmin(l,n)/(n-1)) | 3 |
| momentum.aroon_down.5 | pool_pct(-argmin(l,n)/(n-1)) | 3 |
| momentum.aroon_down.50 | pool_pct(-argmin(l,n)/(n-1)) | 3 |
| momentum.bop.10 | pool_pct(SMA((c-o)/(h-l),n)) | 5 |
| momentum.bop.100 | pool_pct(SMA((c-o)/(h-l),n)) | 4 |
| momentum.bop.20 | pool_pct(SMA((c-o)/(h-l),n)) | 4 |
| momentum.bop.5 | pool_pct(SMA((c-o)/(h-l),n)) | 8 |
| smc.resistance.3 | pool_pct(c/confirmed_high-1) | 4 |
| statistics.minindex.10 | pool_pct(-argmin(c,n)/(n-1)) | 3 |
| statistics.minindex.3 | pool_pct(-argmin(c,n)/(n-1)) | 3 |
| statistics.minindex.5 | pool_pct(-argmin(c,n)/(n-1)) | 3 |
| statistics.stddev.10 | pool_pct(std(c,n)/mean(c,n)) | 6 |
| statistics.stddev.100 | pool_pct(std(c,n)/mean(c,n)) | 4 |
| statistics.stddev.20 | pool_pct(std(c,n)/mean(c,n)) | 2 |
| statistics.stddev.3 | pool_pct(std(c,n)/mean(c,n)) | 7 |
| statistics.stddev.5 | pool_pct(std(c,n)/mean(c,n)) | 6 |
| statistics.stddev.50 | pool_pct(std(c,n)/mean(c,n)) | 2 |
| darvas.width.10 | pool_pct(-box_high/box_low+1) | 2 |
| darvas.width.50 | pool_pct(-box_high/box_low+1) | 1 |
| vcp.range.10 | pool_pct(-range(n)/range(2n)) | 3 |
| vcp.range.20 | pool_pct(-range(n)/range(2n)) | 2 |
| vcp.range.50 | pool_pct(-range(n)/range(2n)) | 2 |
| candles.doji.10__history250 | pool_pct(own_rank250(B(doji))) | 3 |
| chips.cost_near.100 | pool_pct(-abs(c/cost-1)/ADR20) | 8 |
| contract5 | pool_pct(-mean(h/l-1,5)/ADR20) | 5 |
| group.peer_dispersion.10 | pool_pct(-std(g(n) among peers)) | 4 |
| group.peer_dispersion.100 | pool_pct(-std(g(n) among peers)) | 3 |
| group.peer_dispersion.3 | pool_pct(-std(g(n) among peers)) | 3 |
| momentum.rocr.100__history250 | pool_pct(own_rank250(c/c[-n])) | 82 |
| momentum.rocr.14__history250 | pool_pct(own_rank250(c/c[-n])) | 69 |
| momentum.rocr.200__history250 | pool_pct(own_rank250(c/c[-n])) | 32 |
| overlap.bb_width.10 | pool_pct(-4*std(c,n)/SMA(c,n)) | 3 |
| overlap.bb_width.100 | pool_pct(-4*std(c,n)/SMA(c,n)) | 4 |
| overlap.bb_width.20 | pool_pct(-4*std(c,n)/SMA(c,n)) | 4 |
| overlap.bb_width.3 | pool_pct(-4*std(c,n)/SMA(c,n)) | 3 |
| overlap.bb_width.5 | pool_pct(-4*std(c,n)/SMA(c,n)) | 5 |
| overlap.bb_width.50 | pool_pct(-4*std(c,n)/SMA(c,n)) | 3 |
| rvol3 | pool_pct(mean(v,3)/mean(v,20)) | 9 |
| statistics.linearreg.10 | pool_pct((LINEARREG(c,n)-c)/c) | 16 |
| statistics.linearreg.100 | pool_pct((LINEARREG(c,n)-c)/c) | 5 |
| statistics.linearreg.20 | pool_pct((LINEARREG(c,n)-c)/c) | 8 |
| statistics.linearreg.200 | pool_pct((LINEARREG(c,n)-c)/c) | 6 |
| statistics.linearreg.3 | pool_pct((LINEARREG(c,n)-c)/c) | 3 |
| statistics.linearreg.5 | pool_pct((LINEARREG(c,n)-c)/c) | 4 |
| statistics.linearreg.50 | pool_pct((LINEARREG(c,n)-c)/c) | 4 |
| vcp.higher_low.10 | pool_pct(min(l,n)/min(l,2n)-1) | 2 |
| vcp.higher_low.20 | pool_pct(min(l,n)/min(l,2n)-1) | 2 |
| minervini.quality.50 | pool_pct(score*efficiency(c,n)) | 3 |
| momentum.macd_signal.200 | pool_pct(EMA(macd,max(2,n//3))) | 7 |
| options.volume.10 | pool_pct(mean(option_volume,n)) | 8 |
| vcp.volume.10 | pool_pct(-mean(v,n)/mean(v,2n)) | 4 |
| vcp.volume.20 | pool_pct(-mean(v,n)/mean(v,2n)) | 3 |
| vcp.volume.50 | pool_pct(-mean(v,n)/mean(v,2n)) | 2 |
| channels.squeeze.10 | pool_pct(1(2*std(c,n)<1.5*ATRn)) | 3 |
| channels.squeeze.100 | pool_pct(1(2*std(c,n)<1.5*ATRn)) | 1 |
| channels.squeeze.14 | pool_pct(1(2*std(c,n)<1.5*ATRn)) | 2 |
| channels.squeeze.20 | pool_pct(1(2*std(c,n)<1.5*ATRn)) | 1 |
| channels.squeeze.200 | pool_pct(1(2*std(c,n)<1.5*ATRn)) | 1 |
| channels.squeeze.3 | pool_pct(1(2*std(c,n)<1.5*ATRn)) | 1 |
| channels.squeeze.5 | pool_pct(1(2*std(c,n)<1.5*ATRn)) | 1 |
| channels.squeeze.50 | pool_pct(1(2*std(c,n)<1.5*ATRn)) | 1 |
| ichimoku.lagging.2__history250 | pool_pct(own_rank250(c/c[-b]-1)) | 61 |
| minervini.stack.100 | pool_pct(1(SMA50>SMA150>SMA200)) | 9 |
| volume.dollar_volume.100__history250 | pool_pct(own_rank250(mean(T,n))) | 3 |
| volume.dollar_volume.10__history250 | pool_pct(own_rank250(mean(T,n))) | 10 |
| volume.dollar_volume.200__history250 | pool_pct(own_rank250(mean(T,n))) | 2 |
| events.high_count.14 | pool_pct(sum(h>=max(h[-1],20),n)) | 5 |
| events.potent_count.10 | pool_pct(sum(corrected_potent,n)) | 5 |
| events.potent_count.100 | pool_pct(sum(corrected_potent,n)) | 4 |
| events.potent_count.3 | pool_pct(sum(corrected_potent,n)) | 15 |
| ichimoku.thickness.0 | pool_pct((spanA[-b]-spanB[-b])/c) | 4 |
| minervini.above50.100__history250 | pool_pct(own_rank250(1(c>SMA50))) | 5 |
| momentum.plus_di.10 | pool_pct(Wilder(DMplus,n)/ATR(n)) | 16 |
| momentum.plus_di.100 | pool_pct(Wilder(DMplus,n)/ATR(n)) | 6 |
| price_transform.typprice.3 | pool_pct(((h+l+c)/3)/mean(c,n)-1) | 34 |
| eom.change.5__history250 | pool_pct(own_rank250(EOM-EOM[-5])) | 4 |
| minervini.above150.100__history250 | pool_pct(own_rank250(1(c>SMA150))) | 7 |
| near_ema9 | pool_pct(-abs(c/EMA(c,9)-1)/ADR20) | 3 |
| options.iv_change.200__history250 | pool_pct(own_rank250(iv/iv[-n]-1)) | 1 |
| smc.bos.2 | pool_pct(signed break count in 20 days) | 3 |
| smc.bos.5 | pool_pct(signed break count in 20 days) | 2 |
| chan.buy3.13 | pool_pct(daily causal chan_stock buy3) | 3 |
| darvas.breakout.10 | pool_pct(1(c>last confirmed box high)) | 3 |
| group.peer_positive.10 | pool_pct(fraction of peers with g(n)>0) | 3 |
| group.peer_positive.100 | pool_pct(fraction of peers with g(n)>0) | 1 |
| group.peer_positive.14 | pool_pct(fraction of peers with g(n)>0) | 3 |
| group.peer_positive.20 | pool_pct(fraction of peers with g(n)>0) | 2 |
| group.peer_positive.200 | pool_pct(fraction of peers with g(n)>0) | 1 |
| group.peer_positive.3 | pool_pct(fraction of peers with g(n)>0) | 5 |
| group.peer_positive.5 | pool_pct(fraction of peers with g(n)>0) | 7 |
| group.peer_positive.50 | pool_pct(fraction of peers with g(n)>0) | 2 |
| group.peer_rank.5 | pool_pct(fraction peer g(n)<=own g(n)) | 3 |
| momentum.adx.100__history250 | pool_pct(own_rank250(Wilder(DX,n))) | 4 |
| momentum.adx.200__history250 | pool_pct(own_rank250(Wilder(DX,n))) | 1 |
| momentum.minus_di.10 | pool_pct(-Wilder(DMminus,n)/ATR(n)) | 16 |
| momentum.minus_di.100 | pool_pct(-Wilder(DMminus,n)/ATR(n)) | 8 |
| options.divergence.10 | pool_pct((iv/iv[-n]-1)-(c/c[-n]-1)) | 4 |
| options.divergence.100 | pool_pct((iv/iv[-n]-1)-(c/c[-n]-1)) | 2 |
| options.divergence.20 | pool_pct((iv/iv[-n]-1)-(c/c[-n]-1)) | 2 |
| options.divergence.200 | pool_pct((iv/iv[-n]-1)-(c/c[-n]-1)) | 2 |
| options.divergence.3 | pool_pct((iv/iv[-n]-1)-(c/c[-n]-1)) | 3 |
| options.divergence.5 | pool_pct((iv/iv[-n]-1)-(c/c[-n]-1)) | 3 |
| options.divergence.50 | pool_pct((iv/iv[-n]-1)-(c/c[-n]-1)) | 3 |
| options.iv_percentile.100 | pool_pct(own trailing-n IV percentile) | 10 |
| options.iv_percentile.3 | pool_pct(own trailing-n IV percentile) | 9 |
| price_transform.max.100__history250 | pool_pct(own_rank250(c/max(c,n)-1)) | 43 |
| price_transform.max.20__history250 | pool_pct(own_rank250(c/max(c,n)-1)) | 31 |
| statistics.autocorr.10 | pool_pct(corr(return,return[-1],n)) | 4 |
| statistics.autocorr.100 | pool_pct(corr(return,return[-1],n)) | 2 |
| statistics.autocorr.20 | pool_pct(corr(return,return[-1],n)) | 3 |
| statistics.autocorr.200 | pool_pct(corr(return,return[-1],n)) | 1 |
| statistics.autocorr.3 | pool_pct(corr(return,return[-1],n)) | 3 |
| statistics.autocorr.5 | pool_pct(corr(return,return[-1],n)) | 3 |
| statistics.autocorr.50 | pool_pct(corr(return,return[-1],n)) | 2 |
| statistics.linearreg_intercept.10 | pool_pct(linear_intercept(c,n)/c-1) | 6 |
| volatility.natr.100__history250 | pool_pct(own_rank250(100*ATR(n)/c)) | 8 |
| volatility.natr.10__history250 | pool_pct(own_rank250(100*ATR(n)/c)) | 28 |
| volatility.trange.3__history250 | pool_pct(own_rank250(mean(TR,n)/c)) | 13 |
| volatility.trange.50__history250 | pool_pct(own_rank250(mean(TR,n)/c)) | 1 |
| chan.support.13 | pool_pct(c/last_confirmed_support-1) | 6 |
| options.iv_hv.100__history250 | pool_pct(own_rank250(mean(iv/hv,n))) | 2 |
| options.iv_hv.200__history250 | pool_pct(own_rank250(mean(iv/hv,n))) | 2 |
| options.iv_hv.50__history250 | pool_pct(own_rank250(mean(iv/hv,n))) | 2 |
| overlap.kama.10 | pool_pct(c/KAMA(n,fast=2,slow=30)-1) | 12 |
| price_transform.div.50__history250 | pool_pct(own_rank250(mean(c/o-1,n))) | 6 |
| volatility.adr.100__history250 | pool_pct(own_rank250(mean(h/l-1,n))) | 13 |
| volatility.adr.200__history250 | pool_pct(own_rank250(mean(h/l-1,n))) | 8 |
| candles.marubozu.10 | pool_pct((B(white)-B(black))*B(maru)) | 3 |
| group.breadth.10 | pool_pct(fraction active300 with g(n)>0) | 1 |
| group.breadth.100 | pool_pct(fraction active300 with g(n)>0) | 1 |
| group.breadth.14 | pool_pct(fraction active300 with g(n)>0) | 1 |
| group.breadth.20 | pool_pct(fraction active300 with g(n)>0) | 1 |
| group.breadth.200 | pool_pct(fraction active300 with g(n)>0) | 1 |
| group.breadth.3 | pool_pct(fraction active300 with g(n)>0) | 1 |
| group.breadth.5 | pool_pct(fraction active300 with g(n)>0) | 1 |
| group.breadth.50 | pool_pct(fraction active300 with g(n)>0) | 1 |
| group.peer_volume.10 | pool_pct(mean(v/mean(v,n) among peers)) | 8 |
| group.peer_volume.100 | pool_pct(mean(v/mean(v,n) among peers)) | 6 |
| group.peer_volume.3 | pool_pct(mean(v/mean(v,n) among peers)) | 5 |
| volume.volume_trend.100 | pool_pct(linear_slope(v,n)/mean(v,n)) | 2 |
| volume.volume_trend.20 | pool_pct(linear_slope(v,n)/mean(v,n)) | 2 |
| volume.volume_trend.200 | pool_pct(linear_slope(v,n)/mean(v,n)) | 1 |
| volume.volume_trend.50 | pool_pct(linear_slope(v,n)/mean(v,n)) | 2 |
| weinstein.stage4.10 | pool_pct(-1(week_c<SMA and SMA falling)) | 1 |
| weinstein.stage4.40 | pool_pct(-1(week_c<SMA and SMA falling)) | 1 |
| chan.weekly_buy3.13 | pool_pct(completed-week chan_stock buy3) | 3 |
| complexity.runs.100 | pool_pct(-number of return sign changes/n) | 2 |
| complexity.runs.20 | pool_pct(-number of return sign changes/n) | 2 |
| complexity.runs.200 | pool_pct(-number of return sign changes/n) | 1 |
| complexity.runs.50 | pool_pct(-number of return sign changes/n) | 2 |
| force.change.20__history250 | pool_pct(own_rank250(force-force[-5])) | 7 |
| momentum.adxr.14__history250 | pool_pct(own_rank250((ADX+ADX[-n])/2)) | 2 |
| momentum.adxr.200__history250 | pool_pct(own_rank250((ADX+ADX[-n])/2)) | 1 |
| candles.hammer.10__history250 | pool_pct(own_rank250(B(hammer&~trend))) | 1 |
| candles.hammer.20__history250 | pool_pct(own_rank250(B(hammer&~trend))) | 1 |
| candles.hammer.5__history250 | pool_pct(own_rank250(B(hammer&~trend))) | 1 |
| candles.hangingman.10__history250 | pool_pct(own_rank250(-B(hammer&trend))) | 3 |
| channels.breakout.3__history250 | pool_pct(own_rank250(c/max(h[-1],n)-1)) | 27 |
| channels.keltner_width.100__history250 | pool_pct(own_rank250(-4*ATRn/EMA(c,n))) | 3 |
| channels.keltner_width.10__history250 | pool_pct(own_rank250(-4*ATRn/EMA(c,n))) | 5 |
| events.gap_count.10 | pool_pct(sum(o/c[-1]-1>=2*ADR20[-1],n)) | 2 |
| events.gap_count.100 | pool_pct(sum(o/c[-1]-1>=2*ADR20[-1],n)) | 5 |
| events.gap_count.20 | pool_pct(sum(o/c[-1]-1>=2*ADR20[-1],n)) | 1 |
| events.gap_count.200 | pool_pct(sum(o/c[-1]-1>=2*ADR20[-1],n)) | 2 |
| events.gap_count.3 | pool_pct(sum(o/c[-1]-1>=2*ADR20[-1],n)) | 2 |
| events.gap_size.10 | pool_pct(max(positive_gap/ADR20[-1],n)) | 4 |
| events.gap_size.20 | pool_pct(max(positive_gap/ADR20[-1],n)) | 4 |
| events.gap_size.3 | pool_pct(max(positive_gap/ADR20[-1],n)) | 4 |
| events.gap_size.50 | pool_pct(max(positive_gap/ADR20[-1],n)) | 2 |
| group.peer_excess.200__history250 | pool_pct(own_rank250(g(n)-peer_return)) | 1 |
| group.peer_excess.5__history250 | pool_pct(own_rank250(g(n)-peer_return)) | 2 |
| ichimoku.cross.1__history250 | pool_pct(own_rank250((tenkan-kijun)/c)) | 4 |
| momentum.macd_hist.100__history250 | pool_pct(own_rank250(macd-macd_signal)) | 21 |
| smc.support_near.2 | pool_pct(-abs(c/confirmed_low-1)/ADR20) | 4 |
| smc.support_near.5 | pool_pct(-abs(c/confirmed_low-1)/ADR20) | 2 |
| statistics.r_squared.200__history250 | pool_pct(own_rank250(corr(c,time,n)^2)) | 1 |
| volatility.hv.3 | pool_pct(std(log(c/c[-1]),n)*sqrt(252)) | 4 |
| volatility.range_compression.100 | pool_pct(-mean(h/l-1,n)/mean(h/l-1,2n)) | 2 |
| volatility.range_compression.14 | pool_pct(-mean(h/l-1,n)/mean(h/l-1,2n)) | 2 |
| volatility.range_compression.200 | pool_pct(-mean(h/l-1,n)/mean(h/l-1,2n)) | 2 |
| volatility.range_compression.3 | pool_pct(-mean(h/l-1,n)/mean(h/l-1,2n)) | 3 |
| volatility.range_compression.50 | pool_pct(-mean(h/l-1,n)/mean(h/l-1,2n)) | 3 |
| volume.pvt.200 | pool_pct(sum((c/c[-1]-1)*v,n)/sum(v,n)) | 3 |
| vortex.positive.3 | pool_pct(sum(abs(h-l[-1]),n)/sum(TR,n)) | 6 |
| candles.doji.10__delta5 | pool_pct(pool_pct(B(doji))-pool_pct[-5]) | 5 |
| force.value.100 | pool_pct(EMA((c-c[-1])*v,n)/mean(v*c,n)) | 3 |
| force.value.20 | pool_pct(EMA((c-c[-1])*v,n)/mean(v*c,n)) | 4 |
| momentum.aroon_up.200__history250 | pool_pct(own_rank250(argmax(h,n)/(n-1))) | 4 |
| momentum.rocr.100__delta5 | pool_pct(pool_pct(c/c[-n])-pool_pct[-5]) | 13 |
| momentum.rocr.10__delta5 | pool_pct(pool_pct(c/c[-n])-pool_pct[-5]) | 38 |
| momentum.rocr.14__delta5 | pool_pct(pool_pct(c/c[-n])-pool_pct[-5]) | 19 |
| momentum.rocr.200__delta5 | pool_pct(pool_pct(c/c[-n])-pool_pct[-5]) | 11 |
| momentum.rocr.20__delta5 | pool_pct(pool_pct(c/c[-n])-pool_pct[-5]) | 22 |
| momentum.rocr.50__delta5 | pool_pct(pool_pct(c/c[-n])-pool_pct[-5]) | 16 |
| price_transform.add.100__history250 | pool_pct(own_rank250(mean((h+l)/c-2,n))) | 1 |
| price_transform.add.200__history250 | pool_pct(own_rank250(mean((h+l)/c-2,n))) | 1 |
| price_transform.add.50__history250 | pool_pct(own_rank250(mean((h+l)/c-2,n))) | 1 |
| price_transform.add.5__history250 | pool_pct(own_rank250(mean((h+l)/c-2,n))) | 2 |
| range10 | pool_pct(-(max(h,10)/min(l,10)-1)/ADR20) | 4 |
| statistics.maxindex.100__history250 | pool_pct(own_rank250(argmax(c,n)/(n-1))) | 3 |
| statistics.maxindex.10__history250 | pool_pct(own_rank250(argmax(c,n)/(n-1))) | 1 |
| supertrend.flip.10 | pool_pct(-age(bullish Supertrend flip,60)) | 6 |
| candles.invertedhammer.10__history250 | pool_pct(own_rank250(B(inverted&~trend))) | 1 |
| candles.invertedhammer.20__history250 | pool_pct(own_rank250(B(inverted&~trend))) | 1 |
| candles.invertedhammer.5__history250 | pool_pct(own_rank250(B(inverted&~trend))) | 1 |
| candles.shootingstar.10__history250 | pool_pct(own_rank250(-B(inverted&trend))) | 1 |
| candles.shootingstar.20__history250 | pool_pct(own_rank250(-B(inverted&trend))) | 1 |
| candles.shootingstar.5__history250 | pool_pct(own_rank250(-B(inverted&trend))) | 1 |
| complexity.efficiency.100 | pool_pct(abs(c-c[-n])/sum(abs(change),n)) | 4 |
| complexity.efficiency.20 | pool_pct(abs(c-c[-n])/sum(abs(change),n)) | 4 |
| complexity.efficiency.200 | pool_pct(abs(c-c[-n])/sum(abs(change),n)) | 3 |
| momentum.aroon_down.100__history250 | pool_pct(own_rank250(-argmin(l,n)/(n-1))) | 2 |
| momentum.aroon_down.200__history250 | pool_pct(own_rank250(-argmin(l,n)/(n-1))) | 2 |
| momentum.bop.100__history250 | pool_pct(own_rank250(SMA((c-o)/(h-l),n))) | 1 |
| momentum.bop.200__history250 | pool_pct(own_rank250(SMA((c-o)/(h-l),n))) | 1 |
| momentum.bop.3__history250 | pool_pct(own_rank250(SMA((c-o)/(h-l),n))) | 7 |
| options.pcr.10 | pool_pct(-mean(put_volume/call_volume,n)) | 15 |
| options.pcr.200 | pool_pct(-mean(put_volume/call_volume,n)) | 4 |
| smc.resistance.2__history250 | pool_pct(own_rank250(c/confirmed_high-1)) | 3 |
| smc.resistance.5__history250 | pool_pct(own_rank250(c/confirmed_high-1)) | 4 |
| statistics.minindex.14__history250 | pool_pct(own_rank250(-argmin(c,n)/(n-1))) | 1 |
| statistics.minindex.20__history250 | pool_pct(own_rank250(-argmin(c,n)/(n-1))) | 1 |
| statistics.minindex.50__history250 | pool_pct(own_rank250(-argmin(c,n)/(n-1))) | 1 |
| statistics.stddev.100__history250 | pool_pct(own_rank250(std(c,n)/mean(c,n))) | 6 |
| statistics.stddev.14__history250 | pool_pct(own_rank250(std(c,n)/mean(c,n))) | 7 |
| statistics.stddev.200__history250 | pool_pct(own_rank250(std(c,n)/mean(c,n))) | 4 |
| statistics.stddev.50__history250 | pool_pct(own_rank250(std(c,n)/mean(c,n))) | 6 |
| volatility.ulcer.10 | pool_pct(-sqrt(mean((c/max(c,n)-1)^2,n))) | 5 |
| volatility.ulcer.100 | pool_pct(-sqrt(mean((c/max(c,n)-1)^2,n))) | 2 |
| volatility.ulcer.20 | pool_pct(-sqrt(mean((c/max(c,n)-1)^2,n))) | 1 |
| volatility.ulcer.200 | pool_pct(-sqrt(mean((c/max(c,n)-1)^2,n))) | 1 |
| volatility.ulcer.3 | pool_pct(-sqrt(mean((c/max(c,n)-1)^2,n))) | 6 |
| volume.nvi.10 | pool_pct(sum(log(c/c[-1]) where v<v[-1],n)) | 5 |
| volume.nvi.100 | pool_pct(sum(log(c/c[-1]) where v<v[-1],n)) | 3 |
| volume.nvi.3 | pool_pct(sum(log(c/c[-1]) where v<v[-1],n)) | 4 |
| volume.pvi.14 | pool_pct(sum(log(c/c[-1]) where v>v[-1],n)) | 3 |
| avwap.low.100 | pool_pct(c/VWAP since trailing-n lowest low-1) | 8 |
| avwap.volume.10 | pool_pct(c/VWAP since trailing-n max volume-1) | 7 |
| avwap.volume.100 | pool_pct(c/VWAP since trailing-n max volume-1) | 4 |
| avwap.volume.3 | pool_pct(c/VWAP since trailing-n max volume-1) | 12 |
| darvas.width.10__history250 | pool_pct(own_rank250(-box_high/box_low+1)) | 1 |
| darvas.width.20__history250 | pool_pct(own_rank250(-box_high/box_low+1)) | 1 |
| darvas.width.50__history250 | pool_pct(own_rank250(-box_high/box_low+1)) | 1 |
| ichimoku.lagging.0__delta5 | pool_pct(pool_pct(c/c[-b]-1)-pool_pct[-5]) | 1 |
| ichimoku.lagging.2__delta5 | pool_pct(pool_pct(c/c[-b]-1)-pool_pct[-5]) | 1 |
| momentum.aroonosc.14__history250 | pool_pct(own_rank250(aroon_up+aroon_down)) | 1 |
| momentum.aroonosc.50__history250 | pool_pct(own_rank250(aroon_up+aroon_down)) | 1 |
| volume.dollar_volume.100__delta5 | pool_pct(pool_pct(mean(T,n))-pool_pct[-5]) | 3 |
| volume.dollar_volume.10__delta5 | pool_pct(pool_pct(mean(T,n))-pool_pct[-5]) | 4 |
| volume.dollar_volume.3__delta5 | pool_pct(pool_pct(mean(T,n))-pool_pct[-5]) | 2 |
| g63__delta5 | pool_pct(pool_pct(c/c[-63]-1)-pool_pct[-5]) | 4 |
| group.peer_dispersion.100__history250 | pool_pct(own_rank250(-std(g(n) among peers))) | 1 |
| group.peer_dispersion.14__history250 | pool_pct(own_rank250(-std(g(n) among peers))) | 2 |
| group.peer_dispersion.200__history250 | pool_pct(own_rank250(-std(g(n) among peers))) | 1 |
| group.peer_dispersion.50__history250 | pool_pct(own_rank250(-std(g(n) among peers))) | 1 |
| group.peer_dispersion.5__history250 | pool_pct(own_rank250(-std(g(n) among peers))) | 1 |
| kst.hist.1__delta5 | pool_pct(pool_pct(KST-signal)-pool_pct[-5]) | 1 |
| kst.hist.2__delta5 | pool_pct(pool_pct(KST-signal)-pool_pct[-5]) | 1 |
| kst.hist.3__delta5 | pool_pct(pool_pct(KST-signal)-pool_pct[-5]) | 1 |
| minervini.above50.100__delta5 | pool_pct(pool_pct(1(c>SMA50))-pool_pct[-5]) | 3 |
| options.volume_change.10 | pool_pct(option_volume/option_volume[-n]-1) | 5 |
| options.volume_change.100 | pool_pct(option_volume/option_volume[-n]-1) | 2 |
| options.volume_change.14 | pool_pct(option_volume/option_volume[-n]-1) | 3 |
| options.volume_change.20 | pool_pct(option_volume/option_volume[-n]-1) | 4 |
| options.volume_change.200 | pool_pct(option_volume/option_volume[-n]-1) | 2 |
| options.volume_change.3 | pool_pct(option_volume/option_volume[-n]-1) | 3 |
| options.volume_change.5 | pool_pct(option_volume/option_volume[-n]-1) | 11 |
| options.volume_change.50 | pool_pct(option_volume/option_volume[-n]-1) | 3 |
| overlap.bb_width.100__history250 | pool_pct(own_rank250(-4*std(c,n)/SMA(c,n))) | 3 |
| overlap.bb_width.14__history250 | pool_pct(own_rank250(-4*std(c,n)/SMA(c,n))) | 5 |
| overlap.bb_width.200__history250 | pool_pct(own_rank250(-4*std(c,n)/SMA(c,n))) | 2 |
| overlap.bb_width.50__history250 | pool_pct(own_rank250(-4*std(c,n)/SMA(c,n))) | 3 |
| vcp.higher_low.50__history250 | pool_pct(own_rank250(min(l,n)/min(l,2n)-1)) | 1 |
| volume.obv.10 | pool_pct(sum(sign(change(c))*v,n)/sum(v,n)) | 8 |
| volume.obv.20 | pool_pct(sum(sign(change(c))*v,n)/sum(v,n)) | 4 |
| volume.price_volume_corr.10 | pool_pct(corr(log(c/c[-1]),log(v/v[-1]),n)) | 5 |
| volume.price_volume_corr.100 | pool_pct(corr(log(c/c[-1]),log(v/v[-1]),n)) | 2 |
| volume.price_volume_corr.20 | pool_pct(corr(log(c/c[-1]),log(v/v[-1]),n)) | 3 |
| volume.price_volume_corr.3 | pool_pct(corr(log(c/c[-1]),log(v/v[-1]),n)) | 3 |
| volume.price_volume_corr.5 | pool_pct(corr(log(c/c[-1]),log(v/v[-1]),n)) | 3 |
| avwap.high.10 | pool_pct(c/VWAP since trailing-n highest high-1) | 12 |
| avwap.high.100 | pool_pct(c/VWAP since trailing-n highest high-1) | 6 |
| cross9 | pool_pct(-age(c>EMA9 and c[-1]<=EMA9[-1],120)) | 2 |
| g126__delta5 | pool_pct(pool_pct(c/c[-126]-1)-pool_pct[-5]) | 3 |
| h4_coil | pool_pct(original H4 group percentile; t-1 clock) | 2 |
| h4_history | pool_pct(original H4 group percentile; t-1 clock) | 1 |
| h4_peers | pool_pct(original H4 group percentile; t-1 clock) | 2 |
| h4_stack | pool_pct(original H4 group percentile; t-1 clock) | 1 |
| minervini.above150.100__delta5 | pool_pct(pool_pct(1(c>SMA150))-pool_pct[-5]) | 6 |
| minervini.quality.100__history250 | pool_pct(own_rank250(score*efficiency(c,n))) | 5 |
| minervini.quality.50__history250 | pool_pct(own_rank250(score*efficiency(c,n))) | 1 |
| momentum.macd_signal.100__history250 | pool_pct(own_rank250(EMA(macd,max(2,n//3)))) | 8 |
| options.hv.10__history250 | pool_pct(own_rank250(mean(historical_hv,n))) | 6 |
| options.hv.50__history250 | pool_pct(own_rank250(mean(historical_hv,n))) | 2 |
| options.iv.10__history250 | pool_pct(own_rank250(mean(historical_iv,n))) | 5 |
| options.iv.200__history250 | pool_pct(own_rank250(mean(historical_iv,n))) | 1 |
| options.iv.50__history250 | pool_pct(own_rank250(mean(historical_iv,n))) | 1 |
| options.iv_change.100__delta5 | pool_pct(pool_pct(iv/iv[-n]-1)-pool_pct[-5]) | 1 |
| options.iv_change.10__delta5 | pool_pct(pool_pct(iv/iv[-n]-1)-pool_pct[-5]) | 1 |
| options.iv_change.14__delta5 | pool_pct(pool_pct(iv/iv[-n]-1)-pool_pct[-5]) | 1 |
| options.iv_change.200__delta5 | pool_pct(pool_pct(iv/iv[-n]-1)-pool_pct[-5]) | 1 |
| options.iv_change.20__delta5 | pool_pct(pool_pct(iv/iv[-n]-1)-pool_pct[-5]) | 1 |
| options.iv_change.50__delta5 | pool_pct(pool_pct(iv/iv[-n]-1)-pool_pct[-5]) | 1 |
| options.volume.100__history250 | pool_pct(own_rank250(mean(option_volume,n))) | 3 |
| options.volume.3__history250 | pool_pct(own_rank250(mean(option_volume,n))) | 5 |
| overlap.sar.100 | pool_pct((c-PSAR(step=2/(n+1)*.1,max=.2))/c) | 4 |
| overlap.sarext.50 | pool_pct((c-PSAR(step=2/(n+1)*.2,max=.4))/c) | 3 |
| smc.sweep.2 | pool_pct(low_sweep-high_sweep counts in 20 days) | 2 |
| smc.sweep.3 | pool_pct(low_sweep-high_sweep counts in 20 days) | 2 |
| smc.sweep.5 | pool_pct(low_sweep-high_sweep counts in 20 days) | 2 |
| statistics.efficiency.10 | pool_pct(abs(c-c[-n])/sum(abs(change(c)),n)) | 3 |
| statistics.efficiency.14 | pool_pct(abs(c-c[-n])/sum(abs(change(c)),n)) | 2 |
| statistics.efficiency.3 | pool_pct(abs(c-c[-n])/sum(abs(change(c)),n)) | 3 |
| statistics.efficiency.5 | pool_pct(abs(c-c[-n])/sum(abs(change(c)),n)) | 3 |
| supertrend.direction.10 | pool_pct(Supertrend ATRn multiplier3 trend sign) | 4 |
| volume.ad.14 | pool_pct(sum(((2c-h-l)/(h-l))*v,n)/sum(v,n)) | 15 |
| volume.ad.200 | pool_pct(sum(((2c-h-l)/(h-l))*v,n)/sum(v,n)) | 6 |
| volume.ad.50 | pool_pct(sum(((2c-h-l)/(h-l))*v,n)/sum(v,n)) | 8 |
| volume.rvol.100__delta5 | pool_pct(pool_pct(v/mean(v,n))-pool_pct[-5]) | 12 |
| volume.rvol.5__delta5 | pool_pct(pool_pct(v/mean(v,n))-pool_pct[-5]) | 5 |
| channels.squeeze.100__history250 | pool_pct(own_rank250(1(2*std(c,n)<1.5*ATRn))) | 1 |
| channels.squeeze.200__history250 | pool_pct(own_rank250(1(2*std(c,n)<1.5*ATRn))) | 1 |
| channels.squeeze.20__history250 | pool_pct(own_rank250(1(2*std(c,n)<1.5*ATRn))) | 1 |
| channels.squeeze.3__history250 | pool_pct(own_rank250(1(2*std(c,n)<1.5*ATRn))) | 1 |
| channels.squeeze.50__history250 | pool_pct(own_rank250(1(2*std(c,n)<1.5*ATRn))) | 1 |
| channels.squeeze.5__history250 | pool_pct(own_rank250(1(2*std(c,n)<1.5*ATRn))) | 1 |
| channels.width.3__history250 | pool_pct(own_rank250(-(max(h,n)/min(l,n)-1))) | 2 |
| ibd_rs.improving.126 | pool_pct((g(n)-QQQ_g(n))-(g(n)-QQQ_g(n))[-5]) | 3 |
| ibd_rs.improving.252 | pool_pct((g(n)-QQQ_g(n))-(g(n)-QQQ_g(n))[-5]) | 3 |
| ibd_rs.improving.63 | pool_pct((g(n)-QQQ_g(n))-(g(n)-QQQ_g(n))[-5]) | 3 |
| ichimoku.kijun.0__delta5 | pool_pct(pool_pct(c/midHL(b)-1)-pool_pct[-5]) | 81 |
| momentum.adx.100__delta5 | pool_pct(pool_pct(Wilder(DX,n))-pool_pct[-5]) | 1 |
| momentum.adx.10__delta5 | pool_pct(pool_pct(Wilder(DX,n))-pool_pct[-5]) | 3 |
| momentum.adx.200__delta5 | pool_pct(pool_pct(Wilder(DX,n))-pool_pct[-5]) | 1 |
| momentum.adx.20__delta5 | pool_pct(pool_pct(Wilder(DX,n))-pool_pct[-5]) | 2 |
| momentum.adx.50__delta5 | pool_pct(pool_pct(Wilder(DX,n))-pool_pct[-5]) | 1 |
| momentum.adx.5__delta5 | pool_pct(pool_pct(Wilder(DX,n))-pool_pct[-5]) | 2 |
| momentum.apo.200__history250 | pool_pct(own_rank250((EMA(c,n)-EMA(c,2n))/c)) | 2 |
| options.relative_volume.3 | pool_pct(option_volume/mean(option_volume,n)) | 5 |
| overlap.ema.200__delta5 | pool_pct(pool_pct(c/EMA(c,n)-1)-pool_pct[-5]) | 57 |
| price_transform.max.100__delta5 | pool_pct(pool_pct(c/max(c,n)-1)-pool_pct[-5]) | 25 |
| price_transform.max.14__delta5 | pool_pct(pool_pct(c/max(c,n)-1)-pool_pct[-5]) | 23 |
| price_transform.max.3__delta5 | pool_pct(pool_pct(c/max(c,n)-1)-pool_pct[-5]) | 19 |
| price_transform.min.14__delta5 | pool_pct(pool_pct(c/min(c,n)-1)-pool_pct[-5]) | 5 |
| price_transform.min.50__delta5 | pool_pct(pool_pct(c/min(c,n)-1)-pool_pct[-5]) | 4 |
| volatility.natr.100__delta5 | pool_pct(pool_pct(100*ATR(n)/c)-pool_pct[-5]) | 9 |
| volatility.natr.10__delta5 | pool_pct(pool_pct(100*ATR(n)/c)-pool_pct[-5]) | 19 |
| volatility.trange.3__delta5 | pool_pct(pool_pct(mean(TR,n)/c)-pool_pct[-5]) | 12 |
| volatility.upside.14 | pool_pct(sqrt(mean(max(log(c/c[-1]),0)^2,n))) | 2 |
| volatility.upside.5 | pool_pct(sqrt(mean(max(log(c/c[-1]),0)^2,n))) | 3 |
| candles.matchinglow.10 | pool_pct(B(black&(P(black)>0)&within(c,P(c)))) | 3 |
| cross21 | pool_pct(-age(c>EMA21 and c[-1]<=EMA21[-1],120)) | 2 |
| cross50 | pool_pct(-age(c>EMA50 and c[-1]<=EMA50[-1],120)) | 2 |
| events.high_count.200__history250 | pool_pct(own_rank250(sum(h>=max(h[-1],20),n))) | 1 |
| events.high_count.3__history250 | pool_pct(own_rank250(sum(h>=max(h[-1],20),n))) | 4 |
| events.high_count.50__history250 | pool_pct(own_rank250(sum(h>=max(h[-1],20),n))) | 1 |
| events.potent_count.100__history250 | pool_pct(own_rank250(sum(corrected_potent,n))) | 3 |
| events.potent_count.14__history250 | pool_pct(own_rank250(sum(corrected_potent,n))) | 3 |
| events.potent_count.5__history250 | pool_pct(own_rank250(sum(corrected_potent,n))) | 9 |
| ibd_rs.recent.252__delta5 | pool_pct(pool_pct(g(n)-QQQ_g(n))-pool_pct[-5]) | 1 |
| ichimoku.thickness.1__history250 | pool_pct(own_rank250((spanA[-b]-spanB[-b])/c)) | 1 |
| ichimoku.thickness.2__history250 | pool_pct(own_rank250((spanA[-b]-spanB[-b])/c)) | 1 |
| momentum.dx.10 | pool_pct(abs(DIplus-DIminus)/(DIplus+DIminus)) | 6 |
| momentum.dx.50 | pool_pct(abs(DIplus-DIminus)/(DIplus+DIminus)) | 4 |
| momentum.plus_di.100__history250 | pool_pct(own_rank250(Wilder(DMplus,n)/ATR(n))) | 6 |
| momentum.plus_di.3__history250 | pool_pct(own_rank250(Wilder(DMplus,n)/ATR(n))) | 8 |
| momentum.ultosc.100 | pool_pct((4*BP/TR(n)+2*BP/TR(2n)+BP/TR(4n))/7) | 1 |
| momentum.ultosc.200 | pool_pct((4*BP/TR(n)+2*BP/TR(2n)+BP/TR(4n))/7) | 1 |
| options.iv_hv.100__delta5 | pool_pct(pool_pct(mean(iv/hv,n))-pool_pct[-5]) | 2 |
| options.iv_hv.10__delta5 | pool_pct(pool_pct(mean(iv/hv,n))-pool_pct[-5]) | 4 |
| options.iv_hv.200__delta5 | pool_pct(pool_pct(mean(iv/hv,n))-pool_pct[-5]) | 1 |
| options.iv_hv.20__delta5 | pool_pct(pool_pct(mean(iv/hv,n))-pool_pct[-5]) | 2 |
| options.iv_hv.3__delta5 | pool_pct(pool_pct(mean(iv/hv,n))-pool_pct[-5]) | 4 |
| options.iv_hv.50__delta5 | pool_pct(pool_pct(mean(iv/hv,n))-pool_pct[-5]) | 2 |
| options.iv_rank.200 | pool_pct((iv-min(iv,n))/(max(iv,n)-min(iv,n))) | 1 |
| options.iv_spread.200__delta5 | pool_pct(pool_pct(mean(iv-hv,n))-pool_pct[-5]) | 1 |
| overlap.tema.100__history250 | pool_pct(own_rank250(c/(3*EMA-3*EMA2+EMA3)-1)) | 3 |
| price_transform.cos.10 | pool_pct(-cos(clip(c/mean(c,n)-1,-pi/2,pi/2))) | 5 |
| price_transform.cos.20 | pool_pct(-cos(clip(c/mean(c,n)-1,-pi/2,pi/2))) | 2 |
| price_transform.cos.200 | pool_pct(-cos(clip(c/mean(c,n)-1,-pi/2,pi/2))) | 2 |
| price_transform.cos.5 | pool_pct(-cos(clip(c/mean(c,n)-1,-pi/2,pi/2))) | 3 |
| price_transform.cos.50 | pool_pct(-cos(clip(c/mean(c,n)-1,-pi/2,pi/2))) | 2 |
| price_transform.div.100__delta5 | pool_pct(pool_pct(mean(c/o-1,n))-pool_pct[-5]) | 1 |
| price_transform.div.200__delta5 | pool_pct(pool_pct(mean(c/o-1,n))-pool_pct[-5]) | 1 |
| price_transform.div.3__delta5 | pool_pct(pool_pct(mean(c/o-1,n))-pool_pct[-5]) | 10 |
| price_transform.div.5__delta5 | pool_pct(pool_pct(mean(c/o-1,n))-pool_pct[-5]) | 5 |
| volatility.adr.100__delta5 | pool_pct(pool_pct(mean(h/l-1,n))-pool_pct[-5]) | 16 |
| minervini.offlow.100__delta5 | pool_pct(pool_pct(c/min(l,252)-1)-pool_pct[-5]) | 3 |
| momentum.stoch_d.10__delta5 | pool_pct(pool_pct(SMA(stoch_k,3))-pool_pct[-5]) | 11 |
| momentum.stoch_d.200__delta5 | pool_pct(pool_pct(SMA(stoch_k,3))-pool_pct[-5]) | 7 |
| momentum.stoch_d.50__delta5 | pool_pct(pool_pct(SMA(stoch_k,3))-pool_pct[-5]) | 10 |
| smc.bias.2 | pool_pct(last confirmed structural break direction) | 1 |
| smc.bias.3 | pool_pct(last confirmed structural break direction) | 1 |
| smc.bias.5 | pool_pct(last confirmed structural break direction) | 1 |
| smc.bos.3__history250 | pool_pct(own_rank250(signed break count in 20 days)) | 1 |
| candles.longline.10 | pool_pct((B(white)-B(black))*B(long&(span>rng))) | 5 |
| chan.buy3.13__history250 | pool_pct(own_rank250(daily causal chan_stock buy3)) | 3 |
| chan.weekly_buy2.13 | pool_pct(completed-week chan_stock lookback=n buy2) | 3 |
| chips.support.100 | pool_pct(sum(v where .95c<=typical<=c,n)/sum(v,n)) | 4 |
| chips.support.20 | pool_pct(sum(v where .95c<=typical<=c,n)/sum(v,n)) | 3 |
| complexity.fractal.20 | pool_pct(-1-log(path_length/price_range)/log(n)) | 4 |
| darvas.breakout.50__history250 | pool_pct(own_rank250(1(c>last confirmed box high))) | 1 |
| group.peer_positive.100__history250 | pool_pct(own_rank250(fraction of peers with g(n)>0)) | 1 |
| group.peer_positive.200__history250 | pool_pct(own_rank250(fraction of peers with g(n)>0)) | 1 |
| group.peer_rank.100__history250 | pool_pct(own_rank250(fraction peer g(n)<=own g(n))) | 1 |
| group.peer_rank.10__history250 | pool_pct(own_rank250(fraction peer g(n)<=own g(n))) | 2 |
| group.peer_rank.200__history250 | pool_pct(own_rank250(fraction peer g(n)<=own g(n))) | 1 |
| group.peer_rank.50__history250 | pool_pct(own_rank250(fraction peer g(n)<=own g(n))) | 1 |
| momentum.adxr.100__delta5 | pool_pct(pool_pct((ADX+ADX[-n])/2)-pool_pct[-5]) | 1 |
| momentum.adxr.10__delta5 | pool_pct(pool_pct((ADX+ADX[-n])/2)-pool_pct[-5]) | 1 |
| momentum.adxr.200__delta5 | pool_pct(pool_pct((ADX+ADX[-n])/2)-pool_pct[-5]) | 1 |
| momentum.adxr.20__delta5 | pool_pct(pool_pct((ADX+ADX[-n])/2)-pool_pct[-5]) | 1 |
| momentum.adxr.50__delta5 | pool_pct(pool_pct((ADX+ADX[-n])/2)-pool_pct[-5]) | 1 |
| momentum.minus_di.100__history250 | pool_pct(own_rank250(-Wilder(DMminus,n)/ATR(n))) | 6 |
| momentum.minus_di.3__history250 | pool_pct(own_rank250(-Wilder(DMminus,n)/ATR(n))) | 4 |
| near_ema21__history250 | pool_pct(own_rank250(-abs(c/EMA(c,21)-1)/ADR20)) | 2 |
| options.divergence.100__history250 | pool_pct(own_rank250((iv/iv[-n]-1)-(c/c[-n]-1))) | 1 |
| options.divergence.200__history250 | pool_pct(own_rank250((iv/iv[-n]-1)-(c/c[-n]-1))) | 1 |
| smc.choch.2 | pool_pct(signed change-of-character count in 20 days) | 2 |
| smc.choch.3 | pool_pct(signed change-of-character count in 20 days) | 2 |
| smc.choch.5 | pool_pct(signed change-of-character count in 20 days) | 2 |
| statistics.autocorr.200__history250 | pool_pct(own_rank250(corr(return,return[-1],n))) | 1 |
| statistics.linearreg_intercept.200__history250 | pool_pct(own_rank250(linear_intercept(c,n)/c-1)) | 1 |
| statistics.linearreg_intercept.20__history250 | pool_pct(own_rank250(linear_intercept(c,n)/c-1)) | 1 |
| volume.amihud.10__history250 | pool_pct(own_rank250(-mean(abs(c/c[-1]-1)/T,n))) | 6 |
| candles.dragonflydoji.10 | pool_pct(B(doji&(upper<=.1*rng)&(lower>.6*span))) | 3 |
| candles.hammer.10__delta5 | pool_pct(pool_pct(B(hammer&~trend))-pool_pct[-5]) | 1 |
| candles.hammer.20__delta5 | pool_pct(pool_pct(B(hammer&~trend))-pool_pct[-5]) | 1 |
| candles.hammer.5__delta5 | pool_pct(pool_pct(B(hammer&~trend))-pool_pct[-5]) | 1 |
| candles.hangingman.10__delta5 | pool_pct(pool_pct(-B(hammer&trend))-pool_pct[-5]) | 3 |
| candles.longleggeddoji.10 | pool_pct(B(doji&(upper>.3*span)&(lower>.3*span))) | 6 |
| candles.shortline.10 | pool_pct((B(white)-B(black))*B(short&(span<rng))) | 7 |
| channels.breakout.5__delta5 | pool_pct(pool_pct(c/max(h[-1],n)-1)-pool_pct[-5]) | 16 |
| channels.keltner_width.100__delta5 | pool_pct(pool_pct(-4*ATRn/EMA(c,n))-pool_pct[-5]) | 3 |
| channels.keltner_width.10__delta5 | pool_pct(pool_pct(-4*ATRn/EMA(c,n))-pool_pct[-5]) | 5 |
| fresh_high60__history250 | pool_pct(own_rank250(-age(h>=max(h[-1],60),120))) | 3 |
| group.peer_excess.100__delta5 | pool_pct(pool_pct(g(n)-peer_return)-pool_pct[-5]) | 1 |
| group.peer_excess.10__delta5 | pool_pct(pool_pct(g(n)-peer_return)-pool_pct[-5]) | 2 |
| group.peer_excess.14__delta5 | pool_pct(pool_pct(g(n)-peer_return)-pool_pct[-5]) | 1 |
| group.peer_excess.200__delta5 | pool_pct(pool_pct(g(n)-peer_return)-pool_pct[-5]) | 1 |
| group.peer_excess.20__delta5 | pool_pct(pool_pct(g(n)-peer_return)-pool_pct[-5]) | 1 |
| group.peer_excess.50__delta5 | pool_pct(pool_pct(g(n)-peer_return)-pool_pct[-5]) | 1 |
| ichimoku.cross.0__delta5 | pool_pct(pool_pct((tenkan-kijun)/c)-pool_pct[-5]) | 3 |
| kst.signal.1__delta5 | pool_pct(pool_pct(SMA(KST,9*scale))-pool_pct[-5]) | 5 |
| kst.signal.2__delta5 | pool_pct(pool_pct(SMA(KST,9*scale))-pool_pct[-5]) | 4 |
| kst.signal.3__delta5 | pool_pct(pool_pct(SMA(KST,9*scale))-pool_pct[-5]) | 2 |
| momentum.macd_hist.100__delta5 | pool_pct(pool_pct(macd-macd_signal)-pool_pct[-5]) | 1 |
| momentum.macd_hist.10__delta5 | pool_pct(pool_pct(macd-macd_signal)-pool_pct[-5]) | 36 |
| momentum.macd_hist.200__delta5 | pool_pct(pool_pct(macd-macd_signal)-pool_pct[-5]) | 1 |
| momentum.macd_hist.50__delta5 | pool_pct(pool_pct(macd-macd_signal)-pool_pct[-5]) | 1 |
| overlap.kama.3__history250 | pool_pct(own_rank250(c/KAMA(n,fast=2,slow=30)-1)) | 18 |
| statistics.correl.10 | pool_pct(corr(stock_log_return,QQQ_log_return,n)) | 5 |
| statistics.correl.100 | pool_pct(corr(stock_log_return,QQQ_log_return,n)) | 3 |
| statistics.correl.3 | pool_pct(corr(stock_log_return,QQQ_log_return,n)) | 5 |
| statistics.correl.5 | pool_pct(corr(stock_log_return,QQQ_log_return,n)) | 5 |
| statistics.r_squared.100__delta5 | pool_pct(pool_pct(corr(c,time,n)^2)-pool_pct[-5]) | 1 |
| statistics.r_squared.200__delta5 | pool_pct(pool_pct(corr(c,time,n)^2)-pool_pct[-5]) | 1 |
| statistics.r_squared.20__delta5 | pool_pct(pool_pct(corr(c,time,n)^2)-pool_pct[-5]) | 1 |
| statistics.r_squared.50__delta5 | pool_pct(pool_pct(corr(c,time,n)^2)-pool_pct[-5]) | 1 |
| candles.gravestonedoji.10 | pool_pct(-B(doji&(lower<=.1*rng)&(upper>.6*span))) | 3 |
| candles.marubozu.10__history250 | pool_pct(own_rank250((B(white)-B(black))*B(maru))) | 3 |
| group.breadth.100__history250 | pool_pct(own_rank250(fraction active300 with g(n)>0)) | 1 |
| group.breadth.10__history250 | pool_pct(own_rank250(fraction active300 with g(n)>0)) | 1 |
| group.breadth.14__history250 | pool_pct(own_rank250(fraction active300 with g(n)>0)) | 1 |
| group.breadth.200__history250 | pool_pct(own_rank250(fraction active300 with g(n)>0)) | 1 |
| group.breadth.20__history250 | pool_pct(own_rank250(fraction active300 with g(n)>0)) | 1 |
| group.breadth.3__history250 | pool_pct(own_rank250(fraction active300 with g(n)>0)) | 1 |
| group.breadth.50__history250 | pool_pct(own_rank250(fraction active300 with g(n)>0)) | 1 |
| group.breadth.5__history250 | pool_pct(own_rank250(fraction active300 with g(n)>0)) | 1 |
| momentum.aroon_up.100__delta5 | pool_pct(pool_pct(argmax(h,n)/(n-1))-pool_pct[-5]) | 4 |
| momentum.aroon_up.14__delta5 | pool_pct(pool_pct(argmax(h,n)/(n-1))-pool_pct[-5]) | 5 |
| momentum.aroon_up.200__delta5 | pool_pct(pool_pct(argmax(h,n)/(n-1))-pool_pct[-5]) | 3 |
| momentum.aroon_up.20__delta5 | pool_pct(pool_pct(argmax(h,n)/(n-1))-pool_pct[-5]) | 5 |
| momentum.aroon_up.50__delta5 | pool_pct(pool_pct(argmax(h,n)/(n-1))-pool_pct[-5]) | 4 |
| momentum.stochrsi.200 | pool_pct((RSI-min(RSI,n))/(max(RSI,n)-min(RSI,n))) | 3 |
| peer_rank__delta5 | pool_pct(pool_pct(original peer_rank)-pool_pct[-5]) | 2 |
| price_transform.add.100__delta5 | pool_pct(pool_pct(mean((h+l)/c-2,n))-pool_pct[-5]) | 1 |
| price_transform.add.10__delta5 | pool_pct(pool_pct(mean((h+l)/c-2,n))-pool_pct[-5]) | 1 |
| price_transform.add.14__delta5 | pool_pct(pool_pct(mean((h+l)/c-2,n))-pool_pct[-5]) | 1 |
| price_transform.add.200__delta5 | pool_pct(pool_pct(mean((h+l)/c-2,n))-pool_pct[-5]) | 1 |
| price_transform.add.20__delta5 | pool_pct(pool_pct(mean((h+l)/c-2,n))-pool_pct[-5]) | 1 |
| price_transform.add.50__delta5 | pool_pct(pool_pct(mean((h+l)/c-2,n))-pool_pct[-5]) | 1 |
| statistics.maxindex.10__delta5 | pool_pct(pool_pct(argmax(c,n)/(n-1))-pool_pct[-5]) | 1 |
| volume.volume_trend.200__history250 | pool_pct(own_rank250(linear_slope(v,n)/mean(v,n))) | 1 |
| weinstein.stage4.40__history250 | pool_pct(own_rank250(-1(week_c<SMA and SMA falling))) | 1 |
| avwap.gap.100 | pool_pct(c/VWAP since trailing-n largest positive gap-1) | 4 |
| avwap.gap.14 | pool_pct(c/VWAP since trailing-n largest positive gap-1) | 6 |
| candles.invertedhammer.10__delta5 | pool_pct(pool_pct(B(inverted&~trend))-pool_pct[-5]) | 1 |
| candles.invertedhammer.20__delta5 | pool_pct(pool_pct(B(inverted&~trend))-pool_pct[-5]) | 1 |
| candles.invertedhammer.5__delta5 | pool_pct(pool_pct(B(inverted&~trend))-pool_pct[-5]) | 1 |
| candles.shootingstar.10__delta5 | pool_pct(pool_pct(-B(inverted&trend))-pool_pct[-5]) | 3 |
| chan.weekly_buy3.13__history250 | pool_pct(own_rank250(completed-week chan_stock buy3)) | 3 |
| chan.weekly_support.13__history250 | pool_pct(own_rank250(c/confirmed_weekly_support-1)) | 3 |
| complexity.runs.200__history250 | pool_pct(own_rank250(-number of return sign changes/n)) | 1 |
| events.earn_age.10 | pool_pct(-min(n,calendar days since occurred earnings)) | 3 |
| events.earn_age.100 | pool_pct(-min(n,calendar days since occurred earnings)) | 8 |
| events.earn_age.3 | pool_pct(-min(n,calendar days since occurred earnings)) | 2 |
| group.peer_potent.10 | pool_pct(mean(sum(corrected_potent,n)/n among peers)) | 3 |
| group.peer_potent.200 | pool_pct(mean(sum(corrected_potent,n)/n among peers)) | 2 |
| group.peer_potent.3 | pool_pct(mean(sum(corrected_potent,n)/n among peers)) | 4 |
| momentum.aroon_down.100__delta5 | pool_pct(pool_pct(-argmin(l,n)/(n-1))-pool_pct[-5]) | 2 |
| momentum.aroon_down.200__delta5 | pool_pct(pool_pct(-argmin(l,n)/(n-1))-pool_pct[-5]) | 2 |
| momentum.aroon_down.20__delta5 | pool_pct(pool_pct(-argmin(l,n)/(n-1))-pool_pct[-5]) | 2 |
| momentum.aroon_down.50__delta5 | pool_pct(pool_pct(-argmin(l,n)/(n-1))-pool_pct[-5]) | 1 |
| momentum.bop.100__delta5 | pool_pct(pool_pct(SMA((c-o)/(h-l),n))-pool_pct[-5]) | 1 |
| momentum.bop.10__delta5 | pool_pct(pool_pct(SMA((c-o)/(h-l),n))-pool_pct[-5]) | 1 |
| momentum.bop.14__delta5 | pool_pct(pool_pct(SMA((c-o)/(h-l),n))-pool_pct[-5]) | 1 |
| momentum.bop.200__delta5 | pool_pct(pool_pct(SMA((c-o)/(h-l),n))-pool_pct[-5]) | 1 |
| momentum.bop.20__delta5 | pool_pct(pool_pct(SMA((c-o)/(h-l),n))-pool_pct[-5]) | 1 |
| momentum.bop.50__delta5 | pool_pct(pool_pct(SMA((c-o)/(h-l),n))-pool_pct[-5]) | 1 |
| smc.resistance.2__delta5 | pool_pct(pool_pct(c/confirmed_high-1)-pool_pct[-5]) | 3 |
| smc.resistance.5__delta5 | pool_pct(pool_pct(c/confirmed_high-1)-pool_pct[-5]) | 2 |
| statistics.minindex.14__delta5 | pool_pct(pool_pct(-argmin(c,n)/(n-1))-pool_pct[-5]) | 1 |
| statistics.minindex.50__delta5 | pool_pct(pool_pct(-argmin(c,n)/(n-1))-pool_pct[-5]) | 1 |
| statistics.stddev.100__delta5 | pool_pct(pool_pct(std(c,n)/mean(c,n))-pool_pct[-5]) | 2 |
| statistics.stddev.10__delta5 | pool_pct(pool_pct(std(c,n)/mean(c,n))-pool_pct[-5]) | 2 |
| statistics.stddev.14__delta5 | pool_pct(pool_pct(std(c,n)/mean(c,n))-pool_pct[-5]) | 2 |
| statistics.stddev.200__delta5 | pool_pct(pool_pct(std(c,n)/mean(c,n))-pool_pct[-5]) | 2 |
| statistics.stddev.20__delta5 | pool_pct(pool_pct(std(c,n)/mean(c,n))-pool_pct[-5]) | 2 |
| statistics.stddev.50__delta5 | pool_pct(pool_pct(std(c,n)/mean(c,n))-pool_pct[-5]) | 2 |
| volatility.compression.10 | pool_pct(-std(log(c/c[-1]),n)/std(log(c/c[-1]),2n)) | 3 |
| volatility.compression.14 | pool_pct(-std(log(c/c[-1]),n)/std(log(c/c[-1]),2n)) | 2 |
| volatility.compression.20 | pool_pct(-std(log(c/c[-1]),n)/std(log(c/c[-1]),2n)) | 2 |
| volatility.compression.3 | pool_pct(-std(log(c/c[-1]),n)/std(log(c/c[-1]),2n)) | 3 |
| volatility.compression.5 | pool_pct(-std(log(c/c[-1]),n)/std(log(c/c[-1]),2n)) | 3 |
| volume.up_down.3 | pool_pct(sum(v where c>c[-1],n)/sum(v where c<c[-1],n)) | 4 |
| volume.up_down.5 | pool_pct(sum(v where c>c[-1],n)/sum(v where c<c[-1],n)) | 5 |
| darvas.width.10__delta5 | pool_pct(pool_pct(-box_high/box_low+1)-pool_pct[-5]) | 1 |
| darvas.width.20__delta5 | pool_pct(pool_pct(-box_high/box_low+1)-pool_pct[-5]) | 1 |
| darvas.width.50__delta5 | pool_pct(pool_pct(-box_high/box_low+1)-pool_pct[-5]) | 1 |
| events.gap_count.10__history250 | pool_pct(own_rank250(sum(o/c[-1]-1>=2*ADR20[-1],n))) | 5 |
| events.gap_count.200__history250 | pool_pct(own_rank250(sum(o/c[-1]-1>=2*ADR20[-1],n))) | 1 |
| events.gap_count.50__history250 | pool_pct(own_rank250(sum(o/c[-1]-1>=2*ADR20[-1],n))) | 2 |
| events.gap_size.100__history250 | pool_pct(own_rank250(max(positive_gap/ADR20[-1],n))) | 1 |
| events.gap_size.200__history250 | pool_pct(own_rank250(max(positive_gap/ADR20[-1],n))) | 1 |
| events.gap_size.5__history250 | pool_pct(own_rank250(max(positive_gap/ADR20[-1],n))) | 2 |
| momentum.aroonosc.100__delta5 | pool_pct(pool_pct(aroon_up+aroon_down)-pool_pct[-5]) | 1 |
| momentum.aroonosc.10__delta5 | pool_pct(pool_pct(aroon_up+aroon_down)-pool_pct[-5]) | 1 |
| momentum.aroonosc.200__delta5 | pool_pct(pool_pct(aroon_up+aroon_down)-pool_pct[-5]) | 1 |
| momentum.aroonosc.3__delta5 | pool_pct(pool_pct(aroon_up+aroon_down)-pool_pct[-5]) | 1 |
| momentum.aroonosc.5__delta5 | pool_pct(pool_pct(aroon_up+aroon_down)-pool_pct[-5]) | 2 |
| momentum.rsi.200 | pool_pct(Wilder(up,n)/(Wilder(up,n)+Wilder(down,n))) | 1 |
| options.turnover.10 | pool_pct(mean(option_volume/option_open_interest,n)) | 7 |
| options.turnover.200 | pool_pct(mean(option_volume/option_open_interest,n)) | 1 |
| smc.support_near.3__history250 | pool_pct(own_rank250(-abs(c/confirmed_low-1)/ADR20)) | 1 |
| vcp.range.20__delta5 | pool_pct(pool_pct(-range(n)/range(2n))-pool_pct[-5]) | 1 |
| vcp.range.50__delta5 | pool_pct(pool_pct(-range(n)/range(2n))-pool_pct[-5]) | 1 |
| volatility.hv.10__history250 | pool_pct(own_rank250(std(log(c/c[-1]),n)*sqrt(252))) | 3 |
| volatility.hv.5__history250 | pool_pct(own_rank250(std(log(c/c[-1]),n)*sqrt(252))) | 1 |
| volatility.range_compression.100__history250 | pool_pct(own_rank250(-mean(h/l-1,n)/mean(h/l-1,2n))) | 2 |
| volatility.range_compression.200__history250 | pool_pct(own_rank250(-mean(h/l-1,n)/mean(h/l-1,2n))) | 2 |
| volatility.range_compression.20__history250 | pool_pct(own_rank250(-mean(h/l-1,n)/mean(h/l-1,2n))) | 1 |
| volume.pvt.50__history250 | pool_pct(own_rank250(sum((c/c[-1]-1)*v,n)/sum(v,n))) | 7 |
| chips.cost_near.100__delta5 | pool_pct(pool_pct(-abs(c/cost-1)/ADR20)-pool_pct[-5]) | 5 |
| group.peer_dispersion.100__delta5 | pool_pct(pool_pct(-std(g(n) among peers))-pool_pct[-5]) | 1 |
| group.peer_dispersion.10__delta5 | pool_pct(pool_pct(-std(g(n) among peers))-pool_pct[-5]) | 1 |
| group.peer_dispersion.14__delta5 | pool_pct(pool_pct(-std(g(n) among peers))-pool_pct[-5]) | 1 |
| group.peer_dispersion.200__delta5 | pool_pct(pool_pct(-std(g(n) among peers))-pool_pct[-5]) | 1 |
| group.peer_dispersion.20__delta5 | pool_pct(pool_pct(-std(g(n) among peers))-pool_pct[-5]) | 1 |
| group.peer_dispersion.3__delta5 | pool_pct(pool_pct(-std(g(n) among peers))-pool_pct[-5]) | 1 |
| group.peer_dispersion.50__delta5 | pool_pct(pool_pct(-std(g(n) among peers))-pool_pct[-5]) | 1 |
| group.peer_dispersion.5__delta5 | pool_pct(pool_pct(-std(g(n) among peers))-pool_pct[-5]) | 1 |
| minervini.slope.100__delta5 | pool_pct(pool_pct(SMA200/SMA200[-20]-1)-pool_pct[-5]) | 5 |
| momentum.ppo.14__delta5 | pool_pct(pool_pct(EMA(c,n)/EMA(c,2n)-1)-pool_pct[-5]) | 22 |
| momentum.ppo.200__delta5 | pool_pct(pool_pct(EMA(c,n)/EMA(c,2n)-1)-pool_pct[-5]) | 2 |
| momentum.ppo.50__delta5 | pool_pct(pool_pct(EMA(c,n)/EMA(c,2n)-1)-pool_pct[-5]) | 4 |
| overlap.bb_width.100__delta5 | pool_pct(pool_pct(-4*std(c,n)/SMA(c,n))-pool_pct[-5]) | 3 |
| overlap.bb_width.10__delta5 | pool_pct(pool_pct(-4*std(c,n)/SMA(c,n))-pool_pct[-5]) | 3 |
| overlap.bb_width.14__delta5 | pool_pct(pool_pct(-4*std(c,n)/SMA(c,n))-pool_pct[-5]) | 2 |
| overlap.bb_width.200__delta5 | pool_pct(pool_pct(-4*std(c,n)/SMA(c,n))-pool_pct[-5]) | 1 |
| overlap.bb_width.20__delta5 | pool_pct(pool_pct(-4*std(c,n)/SMA(c,n))-pool_pct[-5]) | 3 |
| overlap.bb_width.50__delta5 | pool_pct(pool_pct(-4*std(c,n)/SMA(c,n))-pool_pct[-5]) | 3 |
| rvol5__delta5 | pool_pct(pool_pct(mean(v,5)/mean(v,20))-pool_pct[-5]) | 4 |
| statistics.linearreg.100__delta5 | pool_pct(pool_pct((LINEARREG(c,n)-c)/c)-pool_pct[-5]) | 3 |
| statistics.linearreg.200__delta5 | pool_pct(pool_pct((LINEARREG(c,n)-c)/c)-pool_pct[-5]) | 2 |
| statistics.linearreg.50__delta5 | pool_pct(pool_pct((LINEARREG(c,n)-c)/c)-pool_pct[-5]) | 2 |
| vcp.higher_low.10__delta5 | pool_pct(pool_pct(min(l,n)/min(l,2n)-1)-pool_pct[-5]) | 1 |
| vcp.higher_low.20__delta5 | pool_pct(pool_pct(min(l,n)/min(l,2n)-1)-pool_pct[-5]) | 1 |
| vcp.higher_low.50__delta5 | pool_pct(pool_pct(min(l,n)/min(l,2n)-1)-pool_pct[-5]) | 1 |
| complexity.efficiency.200__history250 | pool_pct(own_rank250(abs(c-c[-n])/sum(abs(change),n))) | 2 |
| complexity.efficiency.50__history250 | pool_pct(own_rank250(abs(c-c[-n])/sum(abs(change),n))) | 3 |
| minervini.quality.100__delta5 | pool_pct(pool_pct(score*efficiency(c,n))-pool_pct[-5]) | 3 |
| minervini.quality.200__delta5 | pool_pct(pool_pct(score*efficiency(c,n))-pool_pct[-5]) | 3 |
| minervini.quality.50__delta5 | pool_pct(pool_pct(score*efficiency(c,n))-pool_pct[-5]) | 3 |
| momentum.macd_signal.100__delta5 | pool_pct(pool_pct(EMA(macd,max(2,n//3)))-pool_pct[-5]) | 2 |
| momentum.macd_signal.200__delta5 | pool_pct(pool_pct(EMA(macd,max(2,n//3)))-pool_pct[-5]) | 2 |
| options.hv.100__delta5 | pool_pct(pool_pct(mean(historical_hv,n))-pool_pct[-5]) | 2 |
| options.hv.10__delta5 | pool_pct(pool_pct(mean(historical_hv,n))-pool_pct[-5]) | 5 |
| options.hv.200__delta5 | pool_pct(pool_pct(mean(historical_hv,n))-pool_pct[-5]) | 2 |
| options.hv.50__delta5 | pool_pct(pool_pct(mean(historical_hv,n))-pool_pct[-5]) | 1 |
| options.iv.10__delta5 | pool_pct(pool_pct(mean(historical_iv,n))-pool_pct[-5]) | 5 |
| options.iv.200__delta5 | pool_pct(pool_pct(mean(historical_iv,n))-pool_pct[-5]) | 1 |
| options.iv.50__delta5 | pool_pct(pool_pct(mean(historical_iv,n))-pool_pct[-5]) | 1 |
| options.pcr.100__history250 | pool_pct(own_rank250(-mean(put_volume/call_volume,n))) | 4 |
| options.pcr.10__history250 | pool_pct(own_rank250(-mean(put_volume/call_volume,n))) | 10 |
| options.pcr.200__history250 | pool_pct(own_rank250(-mean(put_volume/call_volume,n))) | 2 |
| options.volume.100__delta5 | pool_pct(pool_pct(mean(option_volume,n))-pool_pct[-5]) | 2 |
| options.volume.10__delta5 | pool_pct(pool_pct(mean(option_volume,n))-pool_pct[-5]) | 3 |
| options.volume.200__delta5 | pool_pct(pool_pct(mean(option_volume,n))-pool_pct[-5]) | 1 |
| options.volume.3__delta5 | pool_pct(pool_pct(mean(option_volume,n))-pool_pct[-5]) | 2 |
| vcp.volume.10__delta5 | pool_pct(pool_pct(-mean(v,n)/mean(v,2n))-pool_pct[-5]) | 1 |
| vcp.volume.20__delta5 | pool_pct(pool_pct(-mean(v,n)/mean(v,2n))-pool_pct[-5]) | 1 |
| vcp.volume.50__delta5 | pool_pct(pool_pct(-mean(v,n)/mean(v,2n))-pool_pct[-5]) | 1 |
| volatility.ulcer.100__history250 | pool_pct(own_rank250(-sqrt(mean((c/max(c,n)-1)^2,n)))) | 1 |
| volatility.ulcer.14__history250 | pool_pct(own_rank250(-sqrt(mean((c/max(c,n)-1)^2,n)))) | 2 |
| volatility.ulcer.200__history250 | pool_pct(own_rank250(-sqrt(mean((c/max(c,n)-1)^2,n)))) | 1 |
| volatility.ulcer.50__history250 | pool_pct(own_rank250(-sqrt(mean((c/max(c,n)-1)^2,n)))) | 1 |
| volatility.ulcer.5__history250 | pool_pct(own_rank250(-sqrt(mean((c/max(c,n)-1)^2,n)))) | 2 |
| volume.nvi.100__history250 | pool_pct(own_rank250(sum(log(c/c[-1]) where v<v[-1],n))) | 2 |
| volume.nvi.200__history250 | pool_pct(own_rank250(sum(log(c/c[-1]) where v<v[-1],n))) | 1 |
| volume.nvi.20__history250 | pool_pct(own_rank250(sum(log(c/c[-1]) where v<v[-1],n))) | 1 |
| volume.nvi.5__history250 | pool_pct(own_rank250(sum(log(c/c[-1]) where v<v[-1],n))) | 2 |
| avwap.low.200__history250 | pool_pct(own_rank250(c/VWAP since trailing-n lowest low-1)) | 3 |
| avwap.low.50__history250 | pool_pct(own_rank250(c/VWAP since trailing-n lowest low-1)) | 4 |
| avwap.volume.200__history250 | pool_pct(own_rank250(c/VWAP since trailing-n max volume-1)) | 1 |
| avwap.volume.20__history250 | pool_pct(own_rank250(c/VWAP since trailing-n max volume-1)) | 1 |
| avwap.volume.50__history250 | pool_pct(own_rank250(c/VWAP since trailing-n max volume-1)) | 1 |
| candles.homingpigeon.10 | pool_pct(B(black&(P(black)>0)&(o<P(o))&(c>P(c))&short)) | 3 |
| candles.takuri.10 | pool_pct(B(doji&(lower>3*body)&(upper<=.1*rng)&~trend)) | 1 |
| candles.takuri.20 | pool_pct(B(doji&(lower>3*body)&(upper<=.1*rng)&~trend)) | 1 |
| candles.takuri.5 | pool_pct(B(doji&(lower>3*body)&(upper<=.1*rng)&~trend)) | 1 |
| chan.buy2.13 | pool_pct(daily causal chan_stock lookback=n,min_gap=4 buy2) | 3 |
| channels.squeeze.100__delta5 | pool_pct(pool_pct(1(2*std(c,n)<1.5*ATRn))-pool_pct[-5]) | 1 |
| channels.squeeze.14__delta5 | pool_pct(pool_pct(1(2*std(c,n)<1.5*ATRn))-pool_pct[-5]) | 1 |
| channels.squeeze.200__delta5 | pool_pct(pool_pct(1(2*std(c,n)<1.5*ATRn))-pool_pct[-5]) | 1 |
| channels.squeeze.20__delta5 | pool_pct(pool_pct(1(2*std(c,n)<1.5*ATRn))-pool_pct[-5]) | 1 |
| channels.squeeze.3__delta5 | pool_pct(pool_pct(1(2*std(c,n)<1.5*ATRn))-pool_pct[-5]) | 1 |
| channels.squeeze.50__delta5 | pool_pct(pool_pct(1(2*std(c,n)<1.5*ATRn))-pool_pct[-5]) | 1 |
| channels.squeeze.5__delta5 | pool_pct(pool_pct(1(2*std(c,n)<1.5*ATRn))-pool_pct[-5]) | 1 |
| channels.width.200__delta5 | pool_pct(pool_pct(-(max(h,n)/min(l,n)-1))-pool_pct[-5]) | 1 |
| channels.width.3__delta5 | pool_pct(pool_pct(-(max(h,n)/min(l,n)-1))-pool_pct[-5]) | 2 |
| complexity.entropy.100 | pool_pct(-binary_entropy(fraction_positive_returns(n))) | 2 |
| complexity.entropy.20 | pool_pct(-binary_entropy(fraction_positive_returns(n))) | 2 |
| complexity.entropy.200 | pool_pct(-binary_entropy(fraction_positive_returns(n))) | 1 |
| complexity.entropy.50 | pool_pct(-binary_entropy(fraction_positive_returns(n))) | 2 |
| complexity.permutation.100 | pool_pct(-entropy of 6 ordinal triples over trailing n / log(6)) | 2 |
| complexity.permutation.20 | pool_pct(-entropy of 6 ordinal triples over trailing n / log(6)) | 2 |
| complexity.permutation.200 | pool_pct(-entropy of 6 ordinal triples over trailing n / log(6)) | 2 |
| complexity.permutation.50 | pool_pct(-entropy of 6 ordinal triples over trailing n / log(6)) | 2 |
| elder.impulse.10 | pool_pct(sign(EMA-EMA[-1])+sign(MACDhist-MACDhist[-1])) | 5 |
| elder.impulse.100 | pool_pct(sign(EMA-EMA[-1])+sign(MACDhist-MACDhist[-1])) | 2 |
| elder.impulse.20 | pool_pct(sign(EMA-EMA[-1])+sign(MACDhist-MACDhist[-1])) | 3 |
| elder.impulse.200 | pool_pct(sign(EMA-EMA[-1])+sign(MACDhist-MACDhist[-1])) | 2 |
| elder.impulse.5 | pool_pct(sign(EMA-EMA[-1])+sign(MACDhist-MACDhist[-1])) | 2 |
| elder.impulse.50 | pool_pct(sign(EMA-EMA[-1])+sign(MACDhist-MACDhist[-1])) | 3 |
| minervini.stack.100__delta5 | pool_pct(pool_pct(1(SMA50>SMA150>SMA200))-pool_pct[-5]) | 3 |
| momentum.apo.100__delta5 | pool_pct(pool_pct((EMA(c,n)-EMA(c,2n))/c)-pool_pct[-5]) | 2 |
| momentum.apo.200__delta5 | pool_pct(pool_pct((EMA(c,n)-EMA(c,2n))/c)-pool_pct[-5]) | 1 |
| options.oi_pcr.20 | pool_pct(-mean(put_open_interest/call_open_interest,n)) | 5 |
| smc.fvg_near.2 | pool_pct(negative distance to nearest live bullish gap / ATR20) | 9 |
| weinstein.stage2.10 | pool_pct(1(completed_week_c>SMA(week_c,n) and SMA rising)) | 2 |
| candles.dojistar.10 | pool_pct(B(doji&~trend&(h<P(l)))-B(doji&trend&(l>P(h)))) | 3 |
| candles.onneck.10 | pool_pct(-B((P(black)>0)&white&(o<P(l))&within(c,P(l)))) | 3 |
| events.high_count.100__delta5 | pool_pct(pool_pct(sum(h>=max(h[-1],20),n))-pool_pct[-5]) | 1 |
| events.high_count.10__delta5 | pool_pct(pool_pct(sum(h>=max(h[-1],20),n))-pool_pct[-5]) | 2 |
| events.high_count.200__delta5 | pool_pct(pool_pct(sum(h>=max(h[-1],20),n))-pool_pct[-5]) | 1 |
| events.high_count.20__delta5 | pool_pct(pool_pct(sum(h>=max(h[-1],20),n))-pool_pct[-5]) | 1 |
| events.high_count.3__delta5 | pool_pct(pool_pct(sum(h>=max(h[-1],20),n))-pool_pct[-5]) | 2 |
| events.high_count.50__delta5 | pool_pct(pool_pct(sum(h>=max(h[-1],20),n))-pool_pct[-5]) | 1 |
| events.potent_count.100__delta5 | pool_pct(pool_pct(sum(corrected_potent,n))-pool_pct[-5]) | 1 |
| events.potent_count.10__delta5 | pool_pct(pool_pct(sum(corrected_potent,n))-pool_pct[-5]) | 1 |
| events.potent_count.14__delta5 | pool_pct(pool_pct(sum(corrected_potent,n))-pool_pct[-5]) | 1 |
| events.potent_count.200__delta5 | pool_pct(pool_pct(sum(corrected_potent,n))-pool_pct[-5]) | 1 |
| events.potent_count.20__delta5 | pool_pct(pool_pct(sum(corrected_potent,n))-pool_pct[-5]) | 2 |
| events.potent_count.50__delta5 | pool_pct(pool_pct(sum(corrected_potent,n))-pool_pct[-5]) | 1 |
| events.potent_count.5__delta5 | pool_pct(pool_pct(sum(corrected_potent,n))-pool_pct[-5]) | 6 |
| ichimoku.thickness.0__delta5 | pool_pct(pool_pct((spanA[-b]-spanB[-b])/c)-pool_pct[-5]) | 1 |
| ichimoku.thickness.1__delta5 | pool_pct(pool_pct((spanA[-b]-spanB[-b])/c)-pool_pct[-5]) | 1 |
| ichimoku.thickness.2__delta5 | pool_pct(pool_pct((spanA[-b]-spanB[-b])/c)-pool_pct[-5]) | 1 |
| momentum.plus_di.100__delta5 | pool_pct(pool_pct(Wilder(DMplus,n)/ATR(n))-pool_pct[-5]) | 6 |
| momentum.plus_di.14__delta5 | pool_pct(pool_pct(Wilder(DMplus,n)/ATR(n))-pool_pct[-5]) | 7 |
| options.volume_change.200__history250 | pool_pct(own_rank250(option_volume/option_volume[-n]-1)) | 1 |
| overlap.tema.3__delta5 | pool_pct(pool_pct(c/(3*EMA-3*EMA2+EMA3)-1)-pool_pct[-5]) | 2 |
| volatility.choppiness.10 | pool_pct(-log10(sum(TR,n)/(max(h,n)-min(l,n)))/log10(n)) | 3 |
| volatility.choppiness.200 | pool_pct(-log10(sum(TR,n)/(max(h,n)-min(l,n)))/log10(n)) | 1 |
| volatility.choppiness.3 | pool_pct(-log10(sum(TR,n)/(max(h,n)-min(l,n)))/log10(n)) | 3 |
| volatility.choppiness.5 | pool_pct(-log10(sum(TR,n)/(max(h,n)-min(l,n)))/log10(n)) | 3 |
| volume.obv.200__history250 | pool_pct(own_rank250(sum(sign(change(c))*v,n)/sum(v,n))) | 3 |
| volume.obv.50__history250 | pool_pct(own_rank250(sum(sign(change(c))*v,n)/sum(v,n))) | 3 |
| volume.price_volume_corr.100__history250 | pool_pct(own_rank250(corr(log(c/c[-1]),log(v/v[-1]),n))) | 1 |
| volume.price_volume_corr.200__history250 | pool_pct(own_rank250(corr(log(c/c[-1]),log(v/v[-1]),n))) | 1 |
| avwap.high.200__history250 | pool_pct(own_rank250(c/VWAP since trailing-n highest high-1)) | 2 |
| avwap.high.20__history250 | pool_pct(own_rank250(c/VWAP since trailing-n highest high-1)) | 3 |
| avwap.high.50__history250 | pool_pct(own_rank250(c/VWAP since trailing-n highest high-1)) | 1 |
| events.potent_age.3__delta5 | pool_pct(pool_pct(-age(corrected_potent,n))-pool_pct[-5]) | 4 |
| h4_history__history250 | pool_pct(own_rank250(original H4 group percentile; t-1 clock)) | 1 |
| h4_stack__history250 | pool_pct(own_rank250(original H4 group percentile; t-1 clock)) | 1 |
| options.oi_change.10 | pool_pct(option_open_interest/option_open_interest[-n]-1) | 3 |
| options.oi_change.100 | pool_pct(option_open_interest/option_open_interest[-n]-1) | 1 |
| options.oi_change.20 | pool_pct(option_open_interest/option_open_interest[-n]-1) | 2 |
| options.oi_change.200 | pool_pct(option_open_interest/option_open_interest[-n]-1) | 1 |
| options.oi_change.3 | pool_pct(option_open_interest/option_open_interest[-n]-1) | 3 |
| options.oi_change.5 | pool_pct(option_open_interest/option_open_interest[-n]-1) | 3 |
| options.oi_change.50 | pool_pct(option_open_interest/option_open_interest[-n]-1) | 2 |
| overlap.sar.10__history250 | pool_pct(own_rank250((c-PSAR(step=2/(n+1)*.1,max=.2))/c)) | 6 |
| overlap.sar.50__history250 | pool_pct(own_rank250((c-PSAR(step=2/(n+1)*.1,max=.2))/c)) | 2 |
| smc.bos.2__delta5 | pool_pct(pool_pct(signed break count in 20 days)-pool_pct[-5]) | 1 |
| smc.bos.3__delta5 | pool_pct(pool_pct(signed break count in 20 days)-pool_pct[-5]) | 1 |
| smc.bos.5__delta5 | pool_pct(pool_pct(signed break count in 20 days)-pool_pct[-5]) | 1 |
| supertrend.direction.14__history250 | pool_pct(own_rank250(Supertrend ATRn multiplier3 trend sign)) | 2 |
| volume.ad.100__history250 | pool_pct(own_rank250(sum(((2c-h-l)/(h-l))*v,n)/sum(v,n))) | 2 |
| volume.ad.200__history250 | pool_pct(own_rank250(sum(((2c-h-l)/(h-l))*v,n)/sum(v,n))) | 2 |
| avwap.earnings.10 | pool_pct(c/VWAP since last occurred earnings within n sessions-1) | 4 |
| avwap.earnings.100 | pool_pct(c/VWAP since last occurred earnings within n sessions-1) | 8 |
| avwap.earnings.20 | pool_pct(c/VWAP since last occurred earnings within n sessions-1) | 2 |
| avwap.earnings.3 | pool_pct(c/VWAP since last occurred earnings within n sessions-1) | 2 |
| avwap.earnings.5 | pool_pct(c/VWAP since last occurred earnings within n sessions-1) | 2 |
| chan.buy3.13__delta5 | pool_pct(pool_pct(daily causal chan_stock buy3)-pool_pct[-5]) | 3 |
| channels.high_age.5__delta5 | pool_pct(pool_pct(-age(h>=max(h[-1],n),120))-pool_pct[-5]) | 1 |
| darvas.breakout.10__delta5 | pool_pct(pool_pct(1(c>last confirmed box high))-pool_pct[-5]) | 3 |
| group.peer_positive.100__delta5 | pool_pct(pool_pct(fraction of peers with g(n)>0)-pool_pct[-5]) | 1 |
| group.peer_positive.14__delta5 | pool_pct(pool_pct(fraction of peers with g(n)>0)-pool_pct[-5]) | 1 |
| group.peer_positive.200__delta5 | pool_pct(pool_pct(fraction of peers with g(n)>0)-pool_pct[-5]) | 1 |
| group.peer_positive.20__delta5 | pool_pct(pool_pct(fraction of peers with g(n)>0)-pool_pct[-5]) | 1 |
| group.peer_positive.50__delta5 | pool_pct(pool_pct(fraction of peers with g(n)>0)-pool_pct[-5]) | 1 |
| group.peer_rank.100__delta5 | pool_pct(pool_pct(fraction peer g(n)<=own g(n))-pool_pct[-5]) | 1 |
| group.peer_rank.14__delta5 | pool_pct(pool_pct(fraction peer g(n)<=own g(n))-pool_pct[-5]) | 1 |
| group.peer_rank.200__delta5 | pool_pct(pool_pct(fraction peer g(n)<=own g(n))-pool_pct[-5]) | 1 |
| group.peer_rank.3__delta5 | pool_pct(pool_pct(fraction peer g(n)<=own g(n))-pool_pct[-5]) | 1 |
| group.peer_rank.50__delta5 | pool_pct(pool_pct(fraction peer g(n)<=own g(n))-pool_pct[-5]) | 1 |
| momentum.minus_di.100__delta5 | pool_pct(pool_pct(-Wilder(DMminus,n)/ATR(n))-pool_pct[-5]) | 6 |
| momentum.minus_di.10__delta5 | pool_pct(pool_pct(-Wilder(DMminus,n)/ATR(n))-pool_pct[-5]) | 10 |
| options.divergence.100__delta5 | pool_pct(pool_pct((iv/iv[-n]-1)-(c/c[-n]-1))-pool_pct[-5]) | 1 |
| options.divergence.10__delta5 | pool_pct(pool_pct((iv/iv[-n]-1)-(c/c[-n]-1))-pool_pct[-5]) | 1 |
| options.divergence.14__delta5 | pool_pct(pool_pct((iv/iv[-n]-1)-(c/c[-n]-1))-pool_pct[-5]) | 1 |
| options.divergence.200__delta5 | pool_pct(pool_pct((iv/iv[-n]-1)-(c/c[-n]-1))-pool_pct[-5]) | 1 |
| options.divergence.20__delta5 | pool_pct(pool_pct((iv/iv[-n]-1)-(c/c[-n]-1))-pool_pct[-5]) | 1 |
| options.divergence.50__delta5 | pool_pct(pool_pct((iv/iv[-n]-1)-(c/c[-n]-1))-pool_pct[-5]) | 1 |
| options.iv_percentile.100__delta5 | pool_pct(pool_pct(own trailing-n IV percentile)-pool_pct[-5]) | 5 |
| options.iv_percentile.10__delta5 | pool_pct(pool_pct(own trailing-n IV percentile)-pool_pct[-5]) | 8 |
| options.relative_volume.100__history250 | pool_pct(own_rank250(option_volume/mean(option_volume,n))) | 5 |
| statistics.autocorr.100__delta5 | pool_pct(pool_pct(corr(return,return[-1],n))-pool_pct[-5]) | 1 |
| statistics.autocorr.10__delta5 | pool_pct(pool_pct(corr(return,return[-1],n))-pool_pct[-5]) | 1 |
| statistics.autocorr.14__delta5 | pool_pct(pool_pct(corr(return,return[-1],n))-pool_pct[-5]) | 1 |
| statistics.autocorr.200__delta5 | pool_pct(pool_pct(corr(return,return[-1],n))-pool_pct[-5]) | 1 |
| statistics.autocorr.20__delta5 | pool_pct(pool_pct(corr(return,return[-1],n))-pool_pct[-5]) | 1 |
| statistics.autocorr.50__delta5 | pool_pct(pool_pct(corr(return,return[-1],n))-pool_pct[-5]) | 1 |
| statistics.linearreg_intercept.100__delta5 | pool_pct(pool_pct(linear_intercept(c,n)/c-1)-pool_pct[-5]) | 1 |
| statistics.linearreg_intercept.200__delta5 | pool_pct(pool_pct(linear_intercept(c,n)/c-1)-pool_pct[-5]) | 1 |
| statistics.linearreg_intercept.50__delta5 | pool_pct(pool_pct(linear_intercept(c,n)/c-1)-pool_pct[-5]) | 1 |
| statistics.tsf.5__history250 | pool_pct(own_rank250(linear_prediction(c,n,one_step)/c-1)) | 2 |
| volatility.upside.100__history250 | pool_pct(own_rank250(sqrt(mean(max(log(c/c[-1]),0)^2,n)))) | 2 |
| volatility.upside.14__history250 | pool_pct(own_rank250(sqrt(mean(max(log(c/c[-1]),0)^2,n)))) | 2 |
| volume.amihud.100__delta5 | pool_pct(pool_pct(-mean(abs(c/c[-1]-1)/T,n))-pool_pct[-5]) | 3 |
| volume.amihud.10__delta5 | pool_pct(pool_pct(-mean(abs(c/c[-1]-1)/T,n))-pool_pct[-5]) | 3 |
| volume.amihud.3__delta5 | pool_pct(pool_pct(-mean(abs(c/c[-1]-1)/T,n))-pool_pct[-5]) | 2 |
| candles.matchinglow.10__history250 | pool_pct(own_rank250(B(black&(P(black)>0)&within(c,P(c))))) | 3 |
| chan.support.13__delta5 | pool_pct(pool_pct(c/last_confirmed_support-1)-pool_pct[-5]) | 3 |
| momentum.dx.200__history250 | pool_pct(own_rank250(abs(DIplus-DIminus)/(DIplus+DIminus))) | 1 |
| momentum.ultosc.100__history250 | pool_pct(own_rank250((4*BP/TR(n)+2*BP/TR(2n)+BP/TR(4n))/7)) | 1 |
| momentum.ultosc.10__history250 | pool_pct(own_rank250((4*BP/TR(n)+2*BP/TR(2n)+BP/TR(4n))/7)) | 5 |
| momentum.ultosc.200__history250 | pool_pct(own_rank250((4*BP/TR(n)+2*BP/TR(2n)+BP/TR(4n))/7)) | 1 |
| momentum.ultosc.50__history250 | pool_pct(own_rank250((4*BP/TR(n)+2*BP/TR(2n)+BP/TR(4n))/7)) | 1 |
| options.iv_rank.10__history250 | pool_pct(own_rank250((iv-min(iv,n))/(max(iv,n)-min(iv,n)))) | 4 |
| options.iv_rank.200__history250 | pool_pct(own_rank250((iv-min(iv,n))/(max(iv,n)-min(iv,n)))) | 1 |
| price_transform.cos.3__history250 | pool_pct(own_rank250(-cos(clip(c/mean(c,n)-1,-pi/2,pi/2)))) | 2 |
| statistics.skew.10 | pool_pct(mean((return-mean(return,n))^3,n)/std(return,n)^3) | 4 |
| statistics.skew.100 | pool_pct(mean((return-mean(return,n))^3,n)/std(return,n)^3) | 1 |
| statistics.skew.20 | pool_pct(mean((return-mean(return,n))^3,n)/std(return,n)^3) | 2 |
| statistics.skew.200 | pool_pct(mean((return-mean(return,n))^3,n)/std(return,n)^3) | 1 |
| statistics.skew.3 | pool_pct(mean((return-mean(return,n))^3,n)/std(return,n)^3) | 3 |
| statistics.skew.5 | pool_pct(mean((return-mean(return,n))^3,n)/std(return,n)^3) | 3 |
| statistics.skew.50 | pool_pct(mean((return-mean(return,n))^3,n)/std(return,n)^3) | 2 |
| volatility.downside.100__history250 | pool_pct(own_rank250(-sqrt(mean(min(log(c/c[-1]),0)^2,n)))) | 2 |
| volatility.downside.10__history250 | pool_pct(own_rank250(-sqrt(mean(min(log(c/c[-1]),0)^2,n)))) | 2 |
| volatility.downside.200__history250 | pool_pct(own_rank250(-sqrt(mean(min(log(c/c[-1]),0)^2,n)))) | 1 |
| volatility.downside.20__history250 | pool_pct(own_rank250(-sqrt(mean(min(log(c/c[-1]),0)^2,n)))) | 1 |
| candles.marubozu.10__delta5 | pool_pct(pool_pct((B(white)-B(black))*B(maru))-pool_pct[-5]) | 3 |
| group.breadth.100__delta5 | pool_pct(pool_pct(fraction active300 with g(n)>0)-pool_pct[-5]) | 1 |
| group.breadth.10__delta5 | pool_pct(pool_pct(fraction active300 with g(n)>0)-pool_pct[-5]) | 1 |
| group.breadth.14__delta5 | pool_pct(pool_pct(fraction active300 with g(n)>0)-pool_pct[-5]) | 1 |
| group.breadth.200__delta5 | pool_pct(pool_pct(fraction active300 with g(n)>0)-pool_pct[-5]) | 1 |
| group.breadth.20__delta5 | pool_pct(pool_pct(fraction active300 with g(n)>0)-pool_pct[-5]) | 1 |
| group.breadth.3__delta5 | pool_pct(pool_pct(fraction active300 with g(n)>0)-pool_pct[-5]) | 1 |
| group.breadth.50__delta5 | pool_pct(pool_pct(fraction active300 with g(n)>0)-pool_pct[-5]) | 1 |
| group.breadth.5__delta5 | pool_pct(pool_pct(fraction active300 with g(n)>0)-pool_pct[-5]) | 1 |
| group.peer_volume.100__delta5 | pool_pct(pool_pct(mean(v/mean(v,n) among peers))-pool_pct[-5]) | 4 |
| group.peer_volume.5__delta5 | pool_pct(pool_pct(mean(v/mean(v,n) among peers))-pool_pct[-5]) | 1 |
| smc.bias.2__history250 | pool_pct(own_rank250(last confirmed structural break direction)) | 2 |
| smc.bias.5__history250 | pool_pct(own_rank250(last confirmed structural break direction)) | 1 |
| statistics.linearreg_slope.200__delta5 | pool_pct(pool_pct(linear_slope(c,n)/mean(c,n))-pool_pct[-5]) | 2 |
| volume.volume_trend.100__delta5 | pool_pct(pool_pct(linear_slope(v,n)/mean(v,n))-pool_pct[-5]) | 1 |
| volume.volume_trend.200__delta5 | pool_pct(pool_pct(linear_slope(v,n)/mean(v,n))-pool_pct[-5]) | 1 |
| volume.volume_trend.50__delta5 | pool_pct(pool_pct(linear_slope(v,n)/mean(v,n))-pool_pct[-5]) | 1 |
| weinstein.slope.10__delta5 | pool_pct(pool_pct(weekly_SMA/weekly_SMA[-4]-1)-pool_pct[-5]) | 2 |
| weinstein.slope.30__delta5 | pool_pct(pool_pct(weekly_SMA/weekly_SMA[-4]-1)-pool_pct[-5]) | 1 |
| weinstein.stage4.10__delta5 | pool_pct(pool_pct(-1(week_c<SMA and SMA falling))-pool_pct[-5]) | 1 |
| weinstein.stage4.30__delta5 | pool_pct(pool_pct(-1(week_c<SMA and SMA falling))-pool_pct[-5]) | 2 |
| candles.longline.20__history250 | pool_pct(own_rank250((B(white)-B(black))*B(long&(span>rng)))) | 2 |
| chan.weekly_buy2.13__history250 | pool_pct(own_rank250(completed-week chan_stock lookback=n buy2)) | 2 |
| chan.weekly_buy2.52__history250 | pool_pct(own_rank250(completed-week chan_stock lookback=n buy2)) | 1 |
| chan.weekly_buy3.13__delta5 | pool_pct(pool_pct(completed-week chan_stock buy3)-pool_pct[-5]) | 3 |
| chan.weekly_support.13__delta5 | pool_pct(pool_pct(c/confirmed_weekly_support-1)-pool_pct[-5]) | 3 |
| complexity.runs.100__delta5 | pool_pct(pool_pct(-number of return sign changes/n)-pool_pct[-5]) | 1 |
| complexity.runs.200__delta5 | pool_pct(pool_pct(-number of return sign changes/n)-pool_pct[-5]) | 1 |
| complexity.runs.20__delta5 | pool_pct(pool_pct(-number of return sign changes/n)-pool_pct[-5]) | 1 |
| complexity.runs.50__delta5 | pool_pct(pool_pct(-number of return sign changes/n)-pool_pct[-5]) | 1 |
| ema_stack__delta5 | pool_pct(pool_pct(1(EMA9>EMA21)+1(EMA21>EMA50))-pool_pct[-5]) | 1 |
| group.peer_return.100__history250 | pool_pct(own_rank250(mean(g(n) among fixed <=300 original peers))) | 1 |
| group.peer_return.10__history250 | pool_pct(own_rank250(mean(g(n) among fixed <=300 original peers))) | 2 |
| group.peer_return.200__history250 | pool_pct(own_rank250(mean(g(n) among fixed <=300 original peers))) | 1 |
| group.peer_return.20__history250 | pool_pct(own_rank250(mean(g(n) among fixed <=300 original peers))) | 1 |
| group.peer_return.50__history250 | pool_pct(own_rank250(mean(g(n) among fixed <=300 original peers))) | 1 |
| ichimoku.cloud.2__delta5 | pool_pct(pool_pct(c/max(spanA[-b],spanB[-b])-1)-pool_pct[-5]) | 10 |
| minervini.score.100__delta5 | pool_pct(pool_pct(sum(trend template conditions))-pool_pct[-5]) | 3 |
| overlap.fama.100__delta5 | pool_pct(pool_pct(c/FAMA(alpha=MAMA_alpha/2)-1)-pool_pct[-5]) | 5 |
| statistics.kurtosis.10 | pool_pct(mean((return-mean(return,n))^4,n)/std(return,n)^4-3) | 3 |
| statistics.kurtosis.100 | pool_pct(mean((return-mean(return,n))^4,n)/std(return,n)^4-3) | 1 |
| statistics.kurtosis.14 | pool_pct(mean((return-mean(return,n))^4,n)/std(return,n)^4-3) | 3 |
| statistics.kurtosis.200 | pool_pct(mean((return-mean(return,n))^4,n)/std(return,n)^4-3) | 1 |
| statistics.kurtosis.3 | pool_pct(mean((return-mean(return,n))^4,n)/std(return,n)^4-3) | 1 |
| statistics.kurtosis.5 | pool_pct(mean((return-mean(return,n))^4,n)/std(return,n)^4-3) | 3 |
| statistics.kurtosis.50 | pool_pct(mean((return-mean(return,n))^4,n)/std(return,n)^4-3) | 2 |
| avwap.breakout.3 | pool_pct(c/VWAP since most recent n-high breakout within n sessions-1) | 5 |
| avwap.breakout.50 | pool_pct(c/VWAP since most recent n-high breakout within n sessions-1) | 2 |
| candles.dragonflydoji.10__history250 | pool_pct(own_rank250(B(doji&(upper<=.1*rng)&(lower>.6*span)))) | 3 |
| candles.longleggeddoji.10__history250 | pool_pct(own_rank250(B(doji&(upper>.3*span)&(lower>.3*span)))) | 4 |
| events.gap_count.100__delta5 | pool_pct(pool_pct(sum(o/c[-1]-1>=2*ADR20[-1],n))-pool_pct[-5]) | 1 |
| events.gap_count.10__delta5 | pool_pct(pool_pct(sum(o/c[-1]-1>=2*ADR20[-1],n))-pool_pct[-5]) | 3 |
| events.gap_count.200__delta5 | pool_pct(pool_pct(sum(o/c[-1]-1>=2*ADR20[-1],n))-pool_pct[-5]) | 1 |
| events.gap_count.3__delta5 | pool_pct(pool_pct(sum(o/c[-1]-1>=2*ADR20[-1],n))-pool_pct[-5]) | 2 |
| events.gap_count.50__delta5 | pool_pct(pool_pct(sum(o/c[-1]-1>=2*ADR20[-1],n))-pool_pct[-5]) | 1 |
| events.gap_size.100__delta5 | pool_pct(pool_pct(max(positive_gap/ADR20[-1],n))-pool_pct[-5]) | 1 |
| events.gap_size.10__delta5 | pool_pct(pool_pct(max(positive_gap/ADR20[-1],n))-pool_pct[-5]) | 1 |
| events.gap_size.14__delta5 | pool_pct(pool_pct(max(positive_gap/ADR20[-1],n))-pool_pct[-5]) | 1 |
| events.gap_size.200__delta5 | pool_pct(pool_pct(max(positive_gap/ADR20[-1],n))-pool_pct[-5]) | 1 |
| events.gap_size.20__delta5 | pool_pct(pool_pct(max(positive_gap/ADR20[-1],n))-pool_pct[-5]) | 2 |
| events.gap_size.50__delta5 | pool_pct(pool_pct(max(positive_gap/ADR20[-1],n))-pool_pct[-5]) | 1 |
| smc.order_block.2 | pool_pct(c/last bearish-candle-low preceding confirmed up-break-1) | 3 |
| smc.order_block.5 | pool_pct(c/last bearish-candle-low preceding confirmed up-break-1) | 2 |
| smc.support_near.3__delta5 | pool_pct(pool_pct(-abs(c/confirmed_low-1)/ADR20)-pool_pct[-5]) | 1 |
| smc.support_near.5__delta5 | pool_pct(pool_pct(-abs(c/confirmed_low-1)/ADR20)-pool_pct[-5]) | 1 |
| statistics.correl.100__history250 | pool_pct(own_rank250(corr(stock_log_return,QQQ_log_return,n))) | 1 |
| statistics.correl.14__history250 | pool_pct(own_rank250(corr(stock_log_return,QQQ_log_return,n))) | 2 |
| statistics.correl.200__history250 | pool_pct(own_rank250(corr(stock_log_return,QQQ_log_return,n))) | 1 |
| statistics.correl.50__history250 | pool_pct(own_rank250(corr(stock_log_return,QQQ_log_return,n))) | 1 |
| volatility.hv.10__delta5 | pool_pct(pool_pct(std(log(c/c[-1]),n)*sqrt(252))-pool_pct[-5]) | 2 |
| volatility.hv.14__delta5 | pool_pct(pool_pct(std(log(c/c[-1]),n)*sqrt(252))-pool_pct[-5]) | 2 |
| volatility.hv.20__delta5 | pool_pct(pool_pct(std(log(c/c[-1]),n)*sqrt(252))-pool_pct[-5]) | 2 |
| volatility.hv.50__delta5 | pool_pct(pool_pct(std(log(c/c[-1]),n)*sqrt(252))-pool_pct[-5]) | 2 |
| volatility.hv.5__delta5 | pool_pct(pool_pct(std(log(c/c[-1]),n)*sqrt(252))-pool_pct[-5]) | 1 |
| volatility.range_compression.100__delta5 | pool_pct(pool_pct(-mean(h/l-1,n)/mean(h/l-1,2n))-pool_pct[-5]) | 1 |
| volatility.range_compression.10__delta5 | pool_pct(pool_pct(-mean(h/l-1,n)/mean(h/l-1,2n))-pool_pct[-5]) | 1 |
| volatility.range_compression.14__delta5 | pool_pct(pool_pct(-mean(h/l-1,n)/mean(h/l-1,2n))-pool_pct[-5]) | 1 |
| volatility.range_compression.200__delta5 | pool_pct(pool_pct(-mean(h/l-1,n)/mean(h/l-1,2n))-pool_pct[-5]) | 1 |
| volatility.range_compression.20__delta5 | pool_pct(pool_pct(-mean(h/l-1,n)/mean(h/l-1,2n))-pool_pct[-5]) | 1 |
| volatility.range_compression.50__delta5 | pool_pct(pool_pct(-mean(h/l-1,n)/mean(h/l-1,2n))-pool_pct[-5]) | 1 |
| volatility.range_compression.5__delta5 | pool_pct(pool_pct(-mean(h/l-1,n)/mean(h/l-1,2n))-pool_pct[-5]) | 1 |
| volume.pvt.100__delta5 | pool_pct(pool_pct(sum((c/c[-1]-1)*v,n)/sum(v,n))-pool_pct[-5]) | 1 |
| volume.pvt.200__delta5 | pool_pct(pool_pct(sum((c/c[-1]-1)*v,n)/sum(v,n))-pool_pct[-5]) | 1 |
| vortex.positive.200__delta5 | pool_pct(pool_pct(sum(abs(h-l[-1]),n)/sum(TR,n))-pool_pct[-5]) | 1 |
| candles.gravestonedoji.10__history250 | pool_pct(own_rank250(-B(doji&(lower<=.1*rng)&(upper>.6*span)))) | 3 |
| force.value.100__delta5 | pool_pct(pool_pct(EMA((c-c[-1])*v,n)/mean(v*c,n))-pool_pct[-5]) | 3 |
| momentum.stochrsi.100__history250 | pool_pct(own_rank250((RSI-min(RSI,n))/(max(RSI,n)-min(RSI,n)))) | 1 |
| momentum.stochrsi.10__history250 | pool_pct(own_rank250((RSI-min(RSI,n))/(max(RSI,n)-min(RSI,n)))) | 4 |
| momentum.stochrsi.200__history250 | pool_pct(own_rank250((RSI-min(RSI,n))/(max(RSI,n)-min(RSI,n)))) | 1 |
| momentum.stochrsi.3__history250 | pool_pct(own_rank250((RSI-min(RSI,n))/(max(RSI,n)-min(RSI,n)))) | 2 |
| supertrend.flip.10__delta5 | pool_pct(pool_pct(-age(bullish Supertrend flip,60))-pool_pct[-5]) | 3 |
| vortex.negative.200__delta5 | pool_pct(pool_pct(-sum(abs(l-h[-1]),n)/sum(TR,n))-pool_pct[-5]) | 1 |
| vortex.negative.3__delta5 | pool_pct(pool_pct(-sum(abs(l-h[-1]),n)/sum(TR,n))-pool_pct[-5]) | 2 |
| avwap.gap.200__history250 | pool_pct(own_rank250(c/VWAP since trailing-n largest positive gap-1)) | 1 |
| avwap.gap.50__history250 | pool_pct(own_rank250(c/VWAP since trailing-n largest positive gap-1)) | 1 |
| candles.highwave.10 | pool_pct((B(white)-B(black))*B(short&(upper>body)&(lower>body))) | 3 |
| complexity.efficiency.20__delta5 | pool_pct(pool_pct(abs(c-c[-n])/sum(abs(change),n))-pool_pct[-5]) | 2 |
| events.earn_age.10__history250 | pool_pct(own_rank250(-min(n,calendar days since occurred earnings))) | 2 |
| events.earn_age.14__history250 | pool_pct(own_rank250(-min(n,calendar days since occurred earnings))) | 2 |
| events.earn_age.5__history250 | pool_pct(own_rank250(-min(n,calendar days since occurred earnings))) | 1 |
| fresh_gap__delta5 | pool_pct(pool_pct(-age(o/c[-1]-1>=2*ADR20[-1],60))-pool_pct[-5]) | 1 |
| group.peer_potent.100__history250 | pool_pct(own_rank250(mean(sum(corrected_potent,n)/n among peers))) | 3 |
| group.peer_potent.10__history250 | pool_pct(own_rank250(mean(sum(corrected_potent,n)/n among peers))) | 2 |
| group.peer_potent.20__history250 | pool_pct(own_rank250(mean(sum(corrected_potent,n)/n among peers))) | 1 |
| group.peer_potent.5__history250 | pool_pct(own_rank250(mean(sum(corrected_potent,n)/n among peers))) | 1 |
| options.pcr.100__delta5 | pool_pct(pool_pct(-mean(put_volume/call_volume,n))-pool_pct[-5]) | 2 |
| options.pcr.10__delta5 | pool_pct(pool_pct(-mean(put_volume/call_volume,n))-pool_pct[-5]) | 4 |
| options.pcr.200__delta5 | pool_pct(pool_pct(-mean(put_volume/call_volume,n))-pool_pct[-5]) | 2 |
| options.pcr.20__delta5 | pool_pct(pool_pct(-mean(put_volume/call_volume,n))-pool_pct[-5]) | 2 |
| options.pcr.3__delta5 | pool_pct(pool_pct(-mean(put_volume/call_volume,n))-pool_pct[-5]) | 4 |
| options.pcr.50__delta5 | pool_pct(pool_pct(-mean(put_volume/call_volume,n))-pool_pct[-5]) | 2 |
| volatility.compression.50__history250 | pool_pct(own_rank250(-std(log(c/c[-1]),n)/std(log(c/c[-1]),2n))) | 1 |
| volatility.ulcer.100__delta5 | pool_pct(pool_pct(-sqrt(mean((c/max(c,n)-1)^2,n)))-pool_pct[-5]) | 1 |
| volatility.ulcer.10__delta5 | pool_pct(pool_pct(-sqrt(mean((c/max(c,n)-1)^2,n)))-pool_pct[-5]) | 1 |
| volatility.ulcer.14__delta5 | pool_pct(pool_pct(-sqrt(mean((c/max(c,n)-1)^2,n)))-pool_pct[-5]) | 1 |
| volatility.ulcer.200__delta5 | pool_pct(pool_pct(-sqrt(mean((c/max(c,n)-1)^2,n)))-pool_pct[-5]) | 1 |
| volatility.ulcer.20__delta5 | pool_pct(pool_pct(-sqrt(mean((c/max(c,n)-1)^2,n)))-pool_pct[-5]) | 1 |
| volatility.ulcer.50__delta5 | pool_pct(pool_pct(-sqrt(mean((c/max(c,n)-1)^2,n)))-pool_pct[-5]) | 1 |
| volatility.ulcer.5__delta5 | pool_pct(pool_pct(-sqrt(mean((c/max(c,n)-1)^2,n)))-pool_pct[-5]) | 2 |
| volume.nvi.100__delta5 | pool_pct(pool_pct(sum(log(c/c[-1]) where v<v[-1],n))-pool_pct[-5]) | 1 |
| volume.nvi.10__delta5 | pool_pct(pool_pct(sum(log(c/c[-1]) where v<v[-1],n))-pool_pct[-5]) | 1 |
| volume.nvi.14__delta5 | pool_pct(pool_pct(sum(log(c/c[-1]) where v<v[-1],n))-pool_pct[-5]) | 1 |
| volume.nvi.200__delta5 | pool_pct(pool_pct(sum(log(c/c[-1]) where v<v[-1],n))-pool_pct[-5]) | 1 |
| volume.nvi.20__delta5 | pool_pct(pool_pct(sum(log(c/c[-1]) where v<v[-1],n))-pool_pct[-5]) | 1 |
| volume.nvi.50__delta5 | pool_pct(pool_pct(sum(log(c/c[-1]) where v<v[-1],n))-pool_pct[-5]) | 1 |
| volume.pvi.100__delta5 | pool_pct(pool_pct(sum(log(c/c[-1]) where v>v[-1],n))-pool_pct[-5]) | 1 |
| volume.pvi.200__delta5 | pool_pct(pool_pct(sum(log(c/c[-1]) where v>v[-1],n))-pool_pct[-5]) | 1 |
| volume.pvi.3__delta5 | pool_pct(pool_pct(sum(log(c/c[-1]) where v>v[-1],n))-pool_pct[-5]) | 1 |
| volume.pvi.50__delta5 | pool_pct(pool_pct(sum(log(c/c[-1]) where v>v[-1],n))-pool_pct[-5]) | 2 |
| volume.pvi.5__delta5 | pool_pct(pool_pct(sum(log(c/c[-1]) where v>v[-1],n))-pool_pct[-5]) | 1 |
| volume.up_down.100__history250 | pool_pct(own_rank250(sum(v where c>c[-1],n)/sum(v where c<c[-1],n))) | 2 |
| avwap.low.10__delta5 | pool_pct(pool_pct(c/VWAP since trailing-n lowest low-1)-pool_pct[-5]) | 5 |
| avwap.low.3__delta5 | pool_pct(pool_pct(c/VWAP since trailing-n lowest low-1)-pool_pct[-5]) | 11 |
| avwap.volume.100__delta5 | pool_pct(pool_pct(c/VWAP since trailing-n max volume-1)-pool_pct[-5]) | 3 |
| avwap.volume.14__delta5 | pool_pct(pool_pct(c/VWAP since trailing-n max volume-1)-pool_pct[-5]) | 2 |
| avwap.volume.5__delta5 | pool_pct(pool_pct(c/VWAP since trailing-n max volume-1)-pool_pct[-5]) | 3 |
| complexity.roughness.100 | pool_pct(-sum(abs(second_difference(c)),n)/sum(abs(change(c)),n)) | 4 |
| darvas.age.10 | pool_pct(-age(breakout,120); box extremum confirmed by 3 following bars) | 3 |
| eom.value.200 | pool_pct(mean(((h+l)/2-(h[-1]+l[-1])/2)*(h-l)/v,n)*mean(v,n)/c^2) | 1 |
| options.turnover.100__history250 | pool_pct(own_rank250(mean(option_volume/option_open_interest,n))) | 2 |
| options.turnover.14__history250 | pool_pct(own_rank250(mean(option_volume/option_open_interest,n))) | 2 |
| options.turnover.200__history250 | pool_pct(own_rank250(mean(option_volume/option_open_interest,n))) | 1 |
| candles.inneck.10 | pool_pct(-B((P(black)>0)&white&(o<P(l))&(c>P(c))&(c<P(c)+.1*rng))) | 3 |
| options.volume_change.100__delta5 | pool_pct(pool_pct(option_volume/option_volume[-n]-1)-pool_pct[-5]) | 1 |
| options.volume_change.200__delta5 | pool_pct(pool_pct(option_volume/option_volume[-n]-1)-pool_pct[-5]) | 1 |
| options.volume_change.50__delta5 | pool_pct(pool_pct(option_volume/option_volume[-n]-1)-pool_pct[-5]) | 1 |
| volume.obv.100__delta5 | pool_pct(pool_pct(sum(sign(change(c))*v,n)/sum(v,n))-pool_pct[-5]) | 2 |
| volume.obv.10__delta5 | pool_pct(pool_pct(sum(sign(change(c))*v,n)/sum(v,n))-pool_pct[-5]) | 2 |
| volume.obv.14__delta5 | pool_pct(pool_pct(sum(sign(change(c))*v,n)/sum(v,n))-pool_pct[-5]) | 2 |
| volume.obv.200__delta5 | pool_pct(pool_pct(sum(sign(change(c))*v,n)/sum(v,n))-pool_pct[-5]) | 2 |
| volume.obv.20__delta5 | pool_pct(pool_pct(sum(sign(change(c))*v,n)/sum(v,n))-pool_pct[-5]) | 2 |
| volume.obv.3__delta5 | pool_pct(pool_pct(sum(sign(change(c))*v,n)/sum(v,n))-pool_pct[-5]) | 3 |
| volume.obv.50__delta5 | pool_pct(pool_pct(sum(sign(change(c))*v,n)/sum(v,n))-pool_pct[-5]) | 2 |
| volume.price_volume_corr.100__delta5 | pool_pct(pool_pct(corr(log(c/c[-1]),log(v/v[-1]),n))-pool_pct[-5]) | 1 |
| volume.price_volume_corr.10__delta5 | pool_pct(pool_pct(corr(log(c/c[-1]),log(v/v[-1]),n))-pool_pct[-5]) | 1 |
| volume.price_volume_corr.14__delta5 | pool_pct(pool_pct(corr(log(c/c[-1]),log(v/v[-1]),n))-pool_pct[-5]) | 1 |
| volume.price_volume_corr.200__delta5 | pool_pct(pool_pct(corr(log(c/c[-1]),log(v/v[-1]),n))-pool_pct[-5]) | 1 |
| volume.price_volume_corr.20__delta5 | pool_pct(pool_pct(corr(log(c/c[-1]),log(v/v[-1]),n))-pool_pct[-5]) | 1 |
| avwap.high.100__delta5 | pool_pct(pool_pct(c/VWAP since trailing-n highest high-1)-pool_pct[-5]) | 6 |
| avwap.high.14__delta5 | pool_pct(pool_pct(c/VWAP since trailing-n highest high-1)-pool_pct[-5]) | 5 |
| candles.piercing.10 | pool_pct(B((P(black)>0)&white&(o<P(l))&(c>(P(o)+P(c))/2)&(c<P(o)))) | 3 |
| cross9__delta5 | pool_pct(pool_pct(-age(c>EMA9 and c[-1]<=EMA9[-1],120))-pool_pct[-5]) | 1 |
| h4_activity__delta5 | pool_pct(pool_pct(original H4 group percentile; t-1 clock)-pool_pct[-5]) | 1 |
| h4_coil__delta5 | pool_pct(pool_pct(original H4 group percentile; t-1 clock)-pool_pct[-5]) | 1 |
| h4_history__delta5 | pool_pct(pool_pct(original H4 group percentile; t-1 clock)-pool_pct[-5]) | 1 |
| h4_peers__delta5 | pool_pct(pool_pct(original H4 group percentile; t-1 clock)-pool_pct[-5]) | 1 |
| h4_stack__delta5 | pool_pct(pool_pct(original H4 group percentile; t-1 clock)-pool_pct[-5]) | 1 |
| overlap.sar.100__delta5 | pool_pct(pool_pct((c-PSAR(step=2/(n+1)*.1,max=.2))/c)-pool_pct[-5]) | 2 |
| overlap.sar.10__delta5 | pool_pct(pool_pct((c-PSAR(step=2/(n+1)*.1,max=.2))/c)-pool_pct[-5]) | 5 |
| overlap.sar.3__delta5 | pool_pct(pool_pct((c-PSAR(step=2/(n+1)*.1,max=.2))/c)-pool_pct[-5]) | 5 |
| smc.sweep.2__delta5 | pool_pct(pool_pct(low_sweep-high_sweep counts in 20 days)-pool_pct[-5]) | 1 |
| smc.sweep.3__delta5 | pool_pct(pool_pct(low_sweep-high_sweep counts in 20 days)-pool_pct[-5]) | 1 |
| smc.sweep.5__delta5 | pool_pct(pool_pct(low_sweep-high_sweep counts in 20 days)-pool_pct[-5]) | 1 |
| statistics.alpha.3__history250 | pool_pct(own_rank250(mean(stock_return,n)-beta*mean(QQQ_return,n))) | 2 |
| statistics.efficiency.14__delta5 | pool_pct(pool_pct(abs(c-c[-n])/sum(abs(change(c)),n))-pool_pct[-5]) | 1 |
| supertrend.direction.10__delta5 | pool_pct(pool_pct(Supertrend ATRn multiplier3 trend sign)-pool_pct[-5]) | 3 |
| volatility.parkinson.10__delta5 | pool_pct(pool_pct(sqrt(mean(log(h/l)^2,n)/(4log(2))))-pool_pct[-5]) | 5 |
| volatility.parkinson.20__delta5 | pool_pct(pool_pct(sqrt(mean(log(h/l)^2,n)/(4log(2))))-pool_pct[-5]) | 3 |
| volume.ad.100__delta5 | pool_pct(pool_pct(sum(((2c-h-l)/(h-l))*v,n)/sum(v,n))-pool_pct[-5]) | 2 |
| volume.ad.10__delta5 | pool_pct(pool_pct(sum(((2c-h-l)/(h-l))*v,n)/sum(v,n))-pool_pct[-5]) | 4 |
| volume.ad.14__delta5 | pool_pct(pool_pct(sum(((2c-h-l)/(h-l))*v,n)/sum(v,n))-pool_pct[-5]) | 4 |
| volume.ad.200__delta5 | pool_pct(pool_pct(sum(((2c-h-l)/(h-l))*v,n)/sum(v,n))-pool_pct[-5]) | 2 |
| volume.ad.20__delta5 | pool_pct(pool_pct(sum(((2c-h-l)/(h-l))*v,n)/sum(v,n))-pool_pct[-5]) | 3 |
| volume.ad.50__delta5 | pool_pct(pool_pct(sum(((2c-h-l)/(h-l))*v,n)/sum(v,n))-pool_pct[-5]) | 3 |
| candles.darkcloudcover.10 | pool_pct(-B((P(white)>0)&black&(o>P(h))&(c<(P(o)+P(c))/2)&(c>P(o)))) | 3 |
| candles.homingpigeon.10__history250 | pool_pct(own_rank250(B(black&(P(black)>0)&(o<P(o))&(c>P(c))&short))) | 3 |
| candles.takuri.10__history250 | pool_pct(own_rank250(B(doji&(lower>3*body)&(upper<=.1*rng)&~trend))) | 1 |
| candles.takuri.20__history250 | pool_pct(own_rank250(B(doji&(lower>3*body)&(upper<=.1*rng)&~trend))) | 1 |
| candles.takuri.5__history250 | pool_pct(own_rank250(B(doji&(lower>3*body)&(upper<=.1*rng)&~trend))) | 1 |
| candles.thrusting.10 | pool_pct(-B((P(black)>0)&white&(o<P(l))&(c>P(c))&(c<(P(o)+P(c))/2))) | 3 |
| chan.buy2.13__history250 | pool_pct(own_rank250(daily causal chan_stock lookback=n,min_gap=4 buy2)) | 2 |
| chan.buy2.52__history250 | pool_pct(own_rank250(daily causal chan_stock lookback=n,min_gap=4 buy2)) | 1 |
| complexity.entropy.200__history250 | pool_pct(own_rank250(-binary_entropy(fraction_positive_returns(n)))) | 1 |
| elder.impulse.3__history250 | pool_pct(own_rank250(sign(EMA-EMA[-1])+sign(MACDhist-MACDhist[-1]))) | 1 |
| events.earn_drift.10 | pool_pct(c/close_at_first_observable_post_earnings_session-1, age<=n) | 4 |
| events.earn_drift.20 | pool_pct(c/close_at_first_observable_post_earnings_session-1, age<=n) | 1 |
| events.earn_drift.3 | pool_pct(c/close_at_first_observable_post_earnings_session-1, age<=n) | 3 |
| events.earn_drift.5 | pool_pct(c/close_at_first_observable_post_earnings_session-1, age<=n) | 3 |
| events.earn_drift.50 | pool_pct(c/close_at_first_observable_post_earnings_session-1, age<=n) | 1 |
| options.oi_pcr.100__history250 | pool_pct(own_rank250(-mean(put_open_interest/call_open_interest,n))) | 8 |
| options.relative_volume.5__delta5 | pool_pct(pool_pct(option_volume/mean(option_volume,n))-pool_pct[-5]) | 1 |
| statistics.tsf.3__delta5 | pool_pct(pool_pct(linear_prediction(c,n,one_step)/c-1)-pool_pct[-5]) | 1 |
| volatility.upside.100__delta5 | pool_pct(pool_pct(sqrt(mean(max(log(c/c[-1]),0)^2,n)))-pool_pct[-5]) | 1 |
| volatility.upside.200__delta5 | pool_pct(pool_pct(sqrt(mean(max(log(c/c[-1]),0)^2,n)))-pool_pct[-5]) | 1 |
| volatility.upside.3__delta5 | pool_pct(pool_pct(sqrt(mean(max(log(c/c[-1]),0)^2,n)))-pool_pct[-5]) | 1 |
| weinstein.stage2.30__history250 | pool_pct(own_rank250(1(completed_week_c>SMA(week_c,n) and SMA rising))) | 1 |
| weinstein.stage2.40__history250 | pool_pct(own_rank250(1(completed_week_c>SMA(week_c,n) and SMA rising))) | 1 |
| candles.closingmarubozu.10 | pool_pct(B(white&long&(upper<=.1*rng))-B(black&long&(lower<=.1*rng))) | 3 |
| candles.dojistar.10__history250 | pool_pct(own_rank250(B(doji&~trend&(h<P(l)))-B(doji&trend&(l>P(h))))) | 3 |
| candles.matchinglow.10__delta5 | pool_pct(pool_pct(B(black&(P(black)>0)&within(c,P(c))))-pool_pct[-5]) | 3 |
| candles.onneck.10__history250 | pool_pct(own_rank250(-B((P(black)>0)&white&(o<P(l))&within(c,P(l))))) | 3 |
| cross21__delta5 | pool_pct(pool_pct(-age(c>EMA21 and c[-1]<=EMA21[-1],120))-pool_pct[-5]) | 1 |
| cross50__delta5 | pool_pct(pool_pct(-age(c>EMA50 and c[-1]<=EMA50[-1],120))-pool_pct[-5]) | 1 |
| momentum.dx.100__delta5 | pool_pct(pool_pct(abs(DIplus-DIminus)/(DIplus+DIminus))-pool_pct[-5]) | 3 |
| momentum.dx.10__delta5 | pool_pct(pool_pct(abs(DIplus-DIminus)/(DIplus+DIminus))-pool_pct[-5]) | 3 |
| momentum.dx.3__delta5 | pool_pct(pool_pct(abs(DIplus-DIminus)/(DIplus+DIminus))-pool_pct[-5]) | 2 |
| momentum.ultosc.100__delta5 | pool_pct(pool_pct((4*BP/TR(n)+2*BP/TR(2n)+BP/TR(4n))/7)-pool_pct[-5]) | 1 |
| momentum.ultosc.200__delta5 | pool_pct(pool_pct((4*BP/TR(n)+2*BP/TR(2n)+BP/TR(4n))/7)-pool_pct[-5]) | 1 |
| options.iv_rank.200__delta5 | pool_pct(pool_pct((iv-min(iv,n))/(max(iv,n)-min(iv,n)))-pool_pct[-5]) | 1 |
| price_transform.cos.100__delta5 | pool_pct(pool_pct(-cos(clip(c/mean(c,n)-1,-pi/2,pi/2)))-pool_pct[-5]) | 1 |
| price_transform.cos.14__delta5 | pool_pct(pool_pct(-cos(clip(c/mean(c,n)-1,-pi/2,pi/2)))-pool_pct[-5]) | 2 |
| price_transform.cos.200__delta5 | pool_pct(pool_pct(-cos(clip(c/mean(c,n)-1,-pi/2,pi/2)))-pool_pct[-5]) | 1 |
| price_transform.cos.50__delta5 | pool_pct(pool_pct(-cos(clip(c/mean(c,n)-1,-pi/2,pi/2)))-pool_pct[-5]) | 1 |
| volatility.downside.100__delta5 | pool_pct(pool_pct(-sqrt(mean(min(log(c/c[-1]),0)^2,n)))-pool_pct[-5]) | 1 |
| volatility.downside.10__delta5 | pool_pct(pool_pct(-sqrt(mean(min(log(c/c[-1]),0)^2,n)))-pool_pct[-5]) | 1 |
| volatility.downside.14__delta5 | pool_pct(pool_pct(-sqrt(mean(min(log(c/c[-1]),0)^2,n)))-pool_pct[-5]) | 1 |
| volatility.downside.200__delta5 | pool_pct(pool_pct(-sqrt(mean(min(log(c/c[-1]),0)^2,n)))-pool_pct[-5]) | 1 |
| volatility.downside.20__delta5 | pool_pct(pool_pct(-sqrt(mean(min(log(c/c[-1]),0)^2,n)))-pool_pct[-5]) | 1 |
| volatility.downside.3__delta5 | pool_pct(pool_pct(-sqrt(mean(min(log(c/c[-1]),0)^2,n)))-pool_pct[-5]) | 1 |
| volatility.downside.50__delta5 | pool_pct(pool_pct(-sqrt(mean(min(log(c/c[-1]),0)^2,n)))-pool_pct[-5]) | 1 |
| candles.spinningtop.10 | pool_pct((B(white)-B(black))*B(short&(upper>body)&(lower>body)&~doji)) | 3 |
| options.oi_change.100__history250 | pool_pct(own_rank250(option_open_interest/option_open_interest[-n]-1)) | 1 |
| options.oi_change.14__history250 | pool_pct(own_rank250(option_open_interest/option_open_interest[-n]-1)) | 1 |
| options.oi_change.200__history250 | pool_pct(own_rank250(option_open_interest/option_open_interest[-n]-1)) | 1 |
| smc.bias.2__delta5 | pool_pct(pool_pct(last confirmed structural break direction)-pool_pct[-5]) | 1 |
| smc.bias.3__delta5 | pool_pct(pool_pct(last confirmed structural break direction)-pool_pct[-5]) | 1 |
| smc.bias.5__delta5 | pool_pct(pool_pct(last confirmed structural break direction)-pool_pct[-5]) | 1 |
| statistics.beta.100 | pool_pct(cov(stock_log_return,QQQ_log_return,n)/var(QQQ_log_return,n)) | 3 |
| statistics.beta.14 | pool_pct(cov(stock_log_return,QQQ_log_return,n)/var(QQQ_log_return,n)) | 3 |
| vcp.score.10 | pool_pct(count(contracting ranges,falling volume,higher low,close>EMA50)) | 2 |
| vcp.score.20 | pool_pct(count(contracting ranges,falling volume,higher low,close>EMA50)) | 2 |
| vcp.score.50 | pool_pct(count(contracting ranges,falling volume,higher low,close>EMA50)) | 2 |
| avwap.earnings.14__history250 | pool_pct(own_rank250(c/VWAP since last occurred earnings within n sessions-1)) | 1 |
| avwap.earnings.3__history250 | pool_pct(own_rank250(c/VWAP since last occurred earnings within n sessions-1)) | 1 |
| avwap.earnings.5__history250 | pool_pct(own_rank250(c/VWAP since last occurred earnings within n sessions-1)) | 1 |
| candles.longline.20__delta5 | pool_pct(pool_pct((B(white)-B(black))*B(long&(span>rng)))-pool_pct[-5]) | 2 |
| chan.weekly_buy2.13__delta5 | pool_pct(pool_pct(completed-week chan_stock lookback=n buy2)-pool_pct[-5]) | 3 |
| chips.support.100__delta5 | pool_pct(pool_pct(sum(v where .95c<=typical<=c,n)/sum(v,n))-pool_pct[-5]) | 2 |
| complexity.fractal.100__delta5 | pool_pct(pool_pct(-1-log(path_length/price_range)/log(n))-pool_pct[-5]) | 2 |
| complexity.fractal.200__delta5 | pool_pct(pool_pct(-1-log(path_length/price_range)/log(n))-pool_pct[-5]) | 2 |
| complexity.fractal.20__delta5 | pool_pct(pool_pct(-1-log(path_length/price_range)/log(n))-pool_pct[-5]) | 2 |
| complexity.fractal.50__delta5 | pool_pct(pool_pct(-1-log(path_length/price_range)/log(n))-pool_pct[-5]) | 2 |
| group.peer_return.100__delta5 | pool_pct(pool_pct(mean(g(n) among fixed <=300 original peers))-pool_pct[-5]) | 1 |
| group.peer_return.200__delta5 | pool_pct(pool_pct(mean(g(n) among fixed <=300 original peers))-pool_pct[-5]) | 1 |
| group.peer_return.20__delta5 | pool_pct(pool_pct(mean(g(n) among fixed <=300 original peers))-pool_pct[-5]) | 1 |
| group.peer_return.3__delta5 | pool_pct(pool_pct(mean(g(n) among fixed <=300 original peers))-pool_pct[-5]) | 1 |
| group.peer_return.50__delta5 | pool_pct(pool_pct(mean(g(n) among fixed <=300 original peers))-pool_pct[-5]) | 1 |
| group.peer_return.5__delta5 | pool_pct(pool_pct(mean(g(n) among fixed <=300 original peers))-pool_pct[-5]) | 2 |
| momentum.mfi.14 | pool_pct(sum(typical*v where typical rises,n)/sum(directional typical*v,n)) | 5 |
| smc.choch.2__delta5 | pool_pct(pool_pct(signed change-of-character count in 20 days)-pool_pct[-5]) | 1 |
| smc.choch.3__delta5 | pool_pct(pool_pct(signed change-of-character count in 20 days)-pool_pct[-5]) | 1 |
| smc.choch.5__delta5 | pool_pct(pool_pct(signed change-of-character count in 20 days)-pool_pct[-5]) | 1 |
| candles.dragonflydoji.10__delta5 | pool_pct(pool_pct(B(doji&(upper<=.1*rng)&(lower>.6*span)))-pool_pct[-5]) | 3 |
| candles.longleggeddoji.5__delta5 | pool_pct(pool_pct(B(doji&(upper>.3*span)&(lower>.3*span)))-pool_pct[-5]) | 4 |
| candles.shortline.20__delta5 | pool_pct(pool_pct((B(white)-B(black))*B(short&(span<rng)))-pool_pct[-5]) | 2 |
| statistics.correl.100__delta5 | pool_pct(pool_pct(corr(stock_log_return,QQQ_log_return,n))-pool_pct[-5]) | 1 |
| statistics.correl.10__delta5 | pool_pct(pool_pct(corr(stock_log_return,QQQ_log_return,n))-pool_pct[-5]) | 2 |
| statistics.correl.14__delta5 | pool_pct(pool_pct(corr(stock_log_return,QQQ_log_return,n))-pool_pct[-5]) | 1 |
| statistics.correl.200__delta5 | pool_pct(pool_pct(corr(stock_log_return,QQQ_log_return,n))-pool_pct[-5]) | 1 |
| statistics.correl.20__delta5 | pool_pct(pool_pct(corr(stock_log_return,QQQ_log_return,n))-pool_pct[-5]) | 1 |
| statistics.correl.50__delta5 | pool_pct(pool_pct(corr(stock_log_return,QQQ_log_return,n))-pool_pct[-5]) | 1 |
| statistics.skew.100__history250 | pool_pct(own_rank250(mean((return-mean(return,n))^3,n)/std(return,n)^3)) | 1 |
| statistics.skew.200__history250 | pool_pct(own_rank250(mean((return-mean(return,n))^3,n)/std(return,n)^3)) | 1 |
| candles.gravestonedoji.10__delta5 | pool_pct(pool_pct(-B(doji&(lower<=.1*rng)&(upper>.6*span)))-pool_pct[-5]) | 3 |
| momentum.stochrsi.200__delta5 | pool_pct(pool_pct((RSI-min(RSI,n))/(max(RSI,n)-min(RSI,n)))-pool_pct[-5]) | 1 |
| avwap.gap.100__delta5 | pool_pct(pool_pct(c/VWAP since trailing-n largest positive gap-1)-pool_pct[-5]) | 3 |
| avwap.gap.20__delta5 | pool_pct(pool_pct(c/VWAP since trailing-n largest positive gap-1)-pool_pct[-5]) | 1 |
| complexity.hurst.100 | pool_pct(log((max(cumsum(centered returns))-min(...))/std(returns))/log(n)) | 2 |
| complexity.hurst.20 | pool_pct(log((max(cumsum(centered returns))-min(...))/std(returns))/log(n)) | 2 |
| complexity.hurst.200 | pool_pct(log((max(cumsum(centered returns))-min(...))/std(returns))/log(n)) | 1 |
| complexity.hurst.50 | pool_pct(log((max(cumsum(centered returns))-min(...))/std(returns))/log(n)) | 2 |
| events.earn_age.100__delta5 | pool_pct(pool_pct(-min(n,calendar days since occurred earnings))-pool_pct[-5]) | 4 |
| events.earn_age.10__delta5 | pool_pct(pool_pct(-min(n,calendar days since occurred earnings))-pool_pct[-5]) | 2 |
| events.earn_age.20__delta5 | pool_pct(pool_pct(-min(n,calendar days since occurred earnings))-pool_pct[-5]) | 1 |
| events.earn_age.3__delta5 | pool_pct(pool_pct(-min(n,calendar days since occurred earnings))-pool_pct[-5]) | 2 |
| group.peer_potent.100__delta5 | pool_pct(pool_pct(mean(sum(corrected_potent,n)/n among peers))-pool_pct[-5]) | 3 |
| group.peer_potent.10__delta5 | pool_pct(pool_pct(mean(sum(corrected_potent,n)/n among peers))-pool_pct[-5]) | 2 |
| group.peer_potent.20__delta5 | pool_pct(pool_pct(mean(sum(corrected_potent,n)/n among peers))-pool_pct[-5]) | 1 |
| group.peer_potent.5__delta5 | pool_pct(pool_pct(mean(sum(corrected_potent,n)/n among peers))-pool_pct[-5]) | 1 |
| statistics.kurtosis.100__history250 | pool_pct(own_rank250(mean((return-mean(return,n))^4,n)/std(return,n)^4-3)) | 1 |
| statistics.kurtosis.200__history250 | pool_pct(own_rank250(mean((return-mean(return,n))^4,n)/std(return,n)^4-3)) | 1 |
| statistics.kurtosis.20__history250 | pool_pct(own_rank250(mean((return-mean(return,n))^4,n)/std(return,n)^4-3)) | 1 |
| statistics.kurtosis.3__history250 | pool_pct(own_rank250(mean((return-mean(return,n))^4,n)/std(return,n)^4-3)) | 1 |
| volatility.compression.100__delta5 | pool_pct(pool_pct(-std(log(c/c[-1]),n)/std(log(c/c[-1]),2n))-pool_pct[-5]) | 1 |
| volatility.compression.14__delta5 | pool_pct(pool_pct(-std(log(c/c[-1]),n)/std(log(c/c[-1]),2n))-pool_pct[-5]) | 1 |
| volatility.compression.200__delta5 | pool_pct(pool_pct(-std(log(c/c[-1]),n)/std(log(c/c[-1]),2n))-pool_pct[-5]) | 1 |
| volatility.compression.20__delta5 | pool_pct(pool_pct(-std(log(c/c[-1]),n)/std(log(c/c[-1]),2n))-pool_pct[-5]) | 1 |
| volatility.compression.50__delta5 | pool_pct(pool_pct(-std(log(c/c[-1]),n)/std(log(c/c[-1]),2n))-pool_pct[-5]) | 1 |
| avwap.breakout.100__history250 | pool_pct(own_rank250(c/VWAP since most recent n-high breakout within n sessions-1)) | 1 |
| momentum.rsi.200__delta5 | pool_pct(pool_pct(Wilder(up,n)/(Wilder(up,n)+Wilder(down,n)))-pool_pct[-5]) | 1 |
| options.turnover.100__delta5 | pool_pct(pool_pct(mean(option_volume/option_open_interest,n))-pool_pct[-5]) | 1 |
| options.turnover.10__delta5 | pool_pct(pool_pct(mean(option_volume/option_open_interest,n))-pool_pct[-5]) | 2 |
| options.turnover.200__delta5 | pool_pct(pool_pct(mean(option_volume/option_open_interest,n))-pool_pct[-5]) | 1 |
| options.turnover.20__delta5 | pool_pct(pool_pct(mean(option_volume/option_open_interest,n))-pool_pct[-5]) | 1 |
| options.turnover.3__delta5 | pool_pct(pool_pct(mean(option_volume/option_open_interest,n))-pool_pct[-5]) | 2 |
| options.turnover.50__delta5 | pool_pct(pool_pct(mean(option_volume/option_open_interest,n))-pool_pct[-5]) | 1 |
| smc.order_block.3__history250 | pool_pct(own_rank250(c/last bearish-candle-low preceding confirmed up-break-1)) | 1 |
| candles.highwave.10__history250 | pool_pct(own_rank250((B(white)-B(black))*B(short&(upper>body)&(lower>body)))) | 3 |
| candles.sticksandwich.10 | pool_pct(B((P(black,2)>0)&(P(white)>0)&black&within(c,P(c,2))&(P(l)>P(c,2)))) | 3 |
| hilbert.inphase.4 | pool_pct(causal Ehlers quadrature FIR (.0962,.5769,-.5769,-.0962), lag 0/2/4/6; I/c) | 3 |
| hilbert.inphase.8 | pool_pct(causal Ehlers quadrature FIR (.0962,.5769,-.5769,-.0962), lag 0/2/4/6; I/c) | 3 |
| hilbert.quadrature.16 | pool_pct(causal Ehlers quadrature FIR (.0962,.5769,-.5769,-.0962), lag 0/2/4/6; Q/c) | 5 |
| hilbert.quadrature.4 | pool_pct(causal Ehlers quadrature FIR (.0962,.5769,-.5769,-.0962), lag 0/2/4/6; Q/c) | 6 |
| hilbert.quadrature.8 | pool_pct(causal Ehlers quadrature FIR (.0962,.5769,-.5769,-.0962), lag 0/2/4/6; Q/c) | 5 |
| ichimoku.future_cloud.0__delta5 | pool_pct(pool_pct((spanA-spanB)/c; known now, not shifted backwards)-pool_pct[-5]) | 2 |
| ichimoku.future_cloud.1__delta5 | pool_pct(pool_pct((spanA-spanB)/c; known now, not shifted backwards)-pool_pct[-5]) | 1 |
| statistics.alpha.5__delta5 | pool_pct(pool_pct(mean(stock_return,n)-beta*mean(QQQ_return,n))-pool_pct[-5]) | 1 |
| volume.adosc.100__history250 | pool_pct(own_rank250((EMA(cumulative_AD,n)-EMA(cumulative_AD,3n))/mean(v,n))) | 3 |
| volume.adosc.10__history250 | pool_pct(own_rank250((EMA(cumulative_AD,n)-EMA(cumulative_AD,3n))/mean(v,n))) | 4 |
| candles.homingpigeon.10__delta5 | pool_pct(pool_pct(B(black&(P(black)>0)&(o<P(o))&(c>P(c))&short))-pool_pct[-5]) | 3 |
| candles.takuri.10__delta5 | pool_pct(pool_pct(B(doji&(lower>3*body)&(upper<=.1*rng)&~trend))-pool_pct[-5]) | 1 |
| candles.takuri.20__delta5 | pool_pct(pool_pct(B(doji&(lower>3*body)&(upper<=.1*rng)&~trend))-pool_pct[-5]) | 1 |
| candles.takuri.5__delta5 | pool_pct(pool_pct(B(doji&(lower>3*body)&(upper<=.1*rng)&~trend))-pool_pct[-5]) | 1 |
| chan.buy2.13__delta5 | pool_pct(pool_pct(daily causal chan_stock lookback=n,min_gap=4 buy2)-pool_pct[-5]) | 3 |
| complexity.entropy.100__delta5 | pool_pct(pool_pct(-binary_entropy(fraction_positive_returns(n)))-pool_pct[-5]) | 1 |
| complexity.entropy.200__delta5 | pool_pct(pool_pct(-binary_entropy(fraction_positive_returns(n)))-pool_pct[-5]) | 1 |
| complexity.entropy.20__delta5 | pool_pct(pool_pct(-binary_entropy(fraction_positive_returns(n)))-pool_pct[-5]) | 1 |
| complexity.entropy.50__delta5 | pool_pct(pool_pct(-binary_entropy(fraction_positive_returns(n)))-pool_pct[-5]) | 1 |
| complexity.permutation.100__delta5 | pool_pct(pool_pct(-entropy of 6 ordinal triples over trailing n / log(6))-pool_pct[-5]) | 1 |
| complexity.permutation.200__delta5 | pool_pct(pool_pct(-entropy of 6 ordinal triples over trailing n / log(6))-pool_pct[-5]) | 1 |
| complexity.permutation.20__delta5 | pool_pct(pool_pct(-entropy of 6 ordinal triples over trailing n / log(6))-pool_pct[-5]) | 1 |
| complexity.permutation.50__delta5 | pool_pct(pool_pct(-entropy of 6 ordinal triples over trailing n / log(6))-pool_pct[-5]) | 1 |
| complexity.roughness.200__history250 | pool_pct(own_rank250(-sum(abs(second_difference(c)),n)/sum(abs(change(c)),n))) | 1 |
| complexity.roughness.20__history250 | pool_pct(own_rank250(-sum(abs(second_difference(c)),n)/sum(abs(change(c)),n))) | 1 |
| complexity.roughness.50__history250 | pool_pct(own_rank250(-sum(abs(second_difference(c)),n)/sum(abs(change(c)),n))) | 1 |
| elder.impulse.100__delta5 | pool_pct(pool_pct(sign(EMA-EMA[-1])+sign(MACDhist-MACDhist[-1]))-pool_pct[-5]) | 1 |
| elder.impulse.14__delta5 | pool_pct(pool_pct(sign(EMA-EMA[-1])+sign(MACDhist-MACDhist[-1]))-pool_pct[-5]) | 1 |
| elder.impulse.200__delta5 | pool_pct(pool_pct(sign(EMA-EMA[-1])+sign(MACDhist-MACDhist[-1]))-pool_pct[-5]) | 1 |
| elder.impulse.3__delta5 | pool_pct(pool_pct(sign(EMA-EMA[-1])+sign(MACDhist-MACDhist[-1]))-pool_pct[-5]) | 2 |
| eom.value.200__history250 | pool_pct(own_rank250(mean(((h+l)/2-(h[-1]+l[-1])/2)*(h-l)/v,n)*mean(v,n)/c^2)) | 1 |
| events.earn_gap.10 | pool_pct(last occurred earnings first-next-session gap; only when session has occurred) | 2 |
| events.earn_gap.100 | pool_pct(last occurred earnings first-next-session gap; only when session has occurred) | 5 |
| events.earn_gap.20 | pool_pct(last occurred earnings first-next-session gap; only when session has occurred) | 1 |
| events.earn_gap.3 | pool_pct(last occurred earnings first-next-session gap; only when session has occurred) | 4 |
| options.oi_pcr.100__delta5 | pool_pct(pool_pct(-mean(put_open_interest/call_open_interest,n))-pool_pct[-5]) | 2 |
| options.oi_pcr.10__delta5 | pool_pct(pool_pct(-mean(put_open_interest/call_open_interest,n))-pool_pct[-5]) | 5 |
| options.oi_pcr.200__delta5 | pool_pct(pool_pct(-mean(put_open_interest/call_open_interest,n))-pool_pct[-5]) | 1 |
| weinstein.stage2.10__delta5 | pool_pct(pool_pct(1(completed_week_c>SMA(week_c,n) and SMA rising))-pool_pct[-5]) | 1 |
| weinstein.stage2.30__delta5 | pool_pct(pool_pct(1(completed_week_c>SMA(week_c,n) and SMA rising))-pool_pct[-5]) | 1 |
| weinstein.stage2.40__delta5 | pool_pct(pool_pct(1(completed_week_c>SMA(week_c,n) and SMA rising))-pool_pct[-5]) | 1 |
| candles.dojistar.10__delta5 | pool_pct(pool_pct(B(doji&~trend&(h<P(l)))-B(doji&trend&(l>P(h))))-pool_pct[-5]) | 3 |
| candles.inneck.10__history250 | pool_pct(own_rank250(-B((P(black)>0)&white&(o<P(l))&(c>P(c))&(c<P(c)+.1*rng)))) | 3 |
| candles.onneck.10__delta5 | pool_pct(pool_pct(-B((P(black)>0)&white&(o<P(l))&within(c,P(l))))-pool_pct[-5]) | 3 |
| volatility.choppiness.14__delta5 | pool_pct(pool_pct(-log10(sum(TR,n)/(max(h,n)-min(l,n)))/log10(n))-pool_pct[-5]) | 1 |
| candles.piercing.10__history250 | pool_pct(own_rank250(B((P(black)>0)&white&(o<P(l))&(c>(P(o)+P(c))/2)&(c<P(o))))) | 3 |
| options.oi_change.100__delta5 | pool_pct(pool_pct(option_open_interest/option_open_interest[-n]-1)-pool_pct[-5]) | 1 |
| options.oi_change.10__delta5 | pool_pct(pool_pct(option_open_interest/option_open_interest[-n]-1)-pool_pct[-5]) | 1 |
| options.oi_change.14__delta5 | pool_pct(pool_pct(option_open_interest/option_open_interest[-n]-1)-pool_pct[-5]) | 1 |
| options.oi_change.200__delta5 | pool_pct(pool_pct(option_open_interest/option_open_interest[-n]-1)-pool_pct[-5]) | 1 |
| options.oi_change.20__delta5 | pool_pct(pool_pct(option_open_interest/option_open_interest[-n]-1)-pool_pct[-5]) | 1 |
| options.oi_change.50__delta5 | pool_pct(pool_pct(option_open_interest/option_open_interest[-n]-1)-pool_pct[-5]) | 1 |
| avwap.earnings.100__delta5 | pool_pct(pool_pct(c/VWAP since last occurred earnings within n sessions-1)-pool_pct[-5]) | 5 |
| avwap.earnings.14__delta5 | pool_pct(pool_pct(c/VWAP since last occurred earnings within n sessions-1)-pool_pct[-5]) | 2 |
| candles.darkcloudcover.10__history250 | pool_pct(own_rank250(-B((P(white)>0)&black&(o>P(h))&(c<(P(o)+P(c))/2)&(c>P(o))))) | 3 |
| candles.morningdojistar.10 | pool_pct(B((P(black,2)>0)&(P(doji)>0)&white&(P(o)<P(c,2))&(c>(P(o,2)+P(c,2))/2))) | 3 |
| candles.thrusting.10__history250 | pool_pct(own_rank250(-B((P(black)>0)&white&(o<P(l))&(c>P(c))&(c<(P(o)+P(c))/2)))) | 3 |
| events.earn_drift.100__history250 | pool_pct(own_rank250(c/close_at_first_observable_post_earnings_session-1, age<=n)) | 3 |
| events.earn_drift.14__history250 | pool_pct(own_rank250(c/close_at_first_observable_post_earnings_session-1, age<=n)) | 2 |
| smc.range_position.3__delta5 | pool_pct(pool_pct((c-confirmed_low)/(confirmed_high-confirmed_low))-pool_pct[-5]) | 3 |
| candles.belthold.10 | pool_pct(B(white&long&(lower<=.1*rng)&~trend)-B(black&long&(upper<=.1*rng)&trend)) | 1 |
| candles.belthold.20 | pool_pct(B(white&long&(lower<=.1*rng)&~trend)-B(black&long&(upper<=.1*rng)&trend)) | 1 |
| candles.belthold.5 | pool_pct(B(white&long&(lower<=.1*rng)&~trend)-B(black&long&(upper<=.1*rng)&trend)) | 1 |
| candles.closingmarubozu.10__history250 | pool_pct(own_rank250(B(white&long&(upper<=.1*rng))-B(black&long&(lower<=.1*rng)))) | 3 |
| candles.eveningdojistar.10 | pool_pct(-B((P(white,2)>0)&(P(doji)>0)&black&(P(o)>P(c,2))&(c<(P(o,2)+P(c,2))/2))) | 3 |
| candles.morningstar.10 | pool_pct(B((P(black,2)>0)&(P(short)>0)&white&(P(o)<P(c,2))&(c>(P(o,2)+P(c,2))/2))) | 3 |
| smc.fvg_balance.2__delta5 | pool_pct(pool_pct(unfilled bullish minus bearish three-bar gaps, max age60)-pool_pct[-5]) | 3 |
| statistics.skew.100__delta5 | pool_pct(pool_pct(mean((return-mean(return,n))^3,n)/std(return,n)^3)-pool_pct[-5]) | 1 |
| statistics.skew.10__delta5 | pool_pct(pool_pct(mean((return-mean(return,n))^3,n)/std(return,n)^3)-pool_pct[-5]) | 1 |
| statistics.skew.14__delta5 | pool_pct(pool_pct(mean((return-mean(return,n))^3,n)/std(return,n)^3)-pool_pct[-5]) | 1 |
| statistics.skew.200__delta5 | pool_pct(pool_pct(mean((return-mean(return,n))^3,n)/std(return,n)^3)-pool_pct[-5]) | 1 |
| statistics.skew.20__delta5 | pool_pct(pool_pct(mean((return-mean(return,n))^3,n)/std(return,n)^3)-pool_pct[-5]) | 1 |
| statistics.skew.50__delta5 | pool_pct(pool_pct(mean((return-mean(return,n))^3,n)/std(return,n)^3)-pool_pct[-5]) | 1 |
| candles.eveningstar.10 | pool_pct(-B((P(white,2)>0)&(P(short)>0)&black&(P(o)>P(c,2))&(c<(P(o,2)+P(c,2))/2))) | 3 |
| candles.spinningtop.10__history250 | pool_pct(own_rank250((B(white)-B(black))*B(short&(upper>body)&(lower>body)&~doji))) | 3 |
| statistics.beta.100__history250 | pool_pct(own_rank250(cov(stock_log_return,QQQ_log_return,n)/var(QQQ_log_return,n))) | 2 |
| statistics.beta.10__history250 | pool_pct(own_rank250(cov(stock_log_return,QQQ_log_return,n)/var(QQQ_log_return,n))) | 1 |
| statistics.beta.200__history250 | pool_pct(own_rank250(cov(stock_log_return,QQQ_log_return,n)/var(QQQ_log_return,n))) | 1 |
| statistics.beta.20__history250 | pool_pct(own_rank250(cov(stock_log_return,QQQ_log_return,n)/var(QQQ_log_return,n))) | 1 |
| hilbert.dcphase.16 | pool_pct(causal Ehlers quadrature FIR (.0962,.5769,-.5769,-.0962), lag 0/2/4/6; atan2(Q,I)) | 3 |
| hilbert.dcphase.4 | pool_pct(causal Ehlers quadrature FIR (.0962,.5769,-.5769,-.0962), lag 0/2/4/6; atan2(Q,I)) | 3 |
| hilbert.dcphase.8 | pool_pct(causal Ehlers quadrature FIR (.0962,.5769,-.5769,-.0962), lag 0/2/4/6; atan2(Q,I)) | 3 |
| momentum.mfi.3__history250 | pool_pct(own_rank250(sum(typical*v where typical rises,n)/sum(directional typical*v,n))) | 3 |
| statistics.kurtosis.100__delta5 | pool_pct(pool_pct(mean((return-mean(return,n))^4,n)/std(return,n)^4-3)-pool_pct[-5]) | 1 |
| statistics.kurtosis.14__delta5 | pool_pct(pool_pct(mean((return-mean(return,n))^4,n)/std(return,n)^4-3)-pool_pct[-5]) | 1 |
| statistics.kurtosis.200__delta5 | pool_pct(pool_pct(mean((return-mean(return,n))^4,n)/std(return,n)^4-3)-pool_pct[-5]) | 1 |
| statistics.kurtosis.20__delta5 | pool_pct(pool_pct(mean((return-mean(return,n))^4,n)/std(return,n)^4-3)-pool_pct[-5]) | 1 |
| statistics.kurtosis.3__delta5 | pool_pct(pool_pct(mean((return-mean(return,n))^4,n)/std(return,n)^4-3)-pool_pct[-5]) | 1 |
| statistics.kurtosis.50__delta5 | pool_pct(pool_pct(mean((return-mean(return,n))^4,n)/std(return,n)^4-3)-pool_pct[-5]) | 1 |
| avwap.breakout.5__delta5 | pool_pct(pool_pct(c/VWAP since most recent n-high breakout within n sessions-1)-pool_pct[-5]) | 1 |
| smc.order_block.2__delta5 | pool_pct(pool_pct(c/last bearish-candle-low preceding confirmed up-break-1)-pool_pct[-5]) | 2 |
| smc.order_block.5__delta5 | pool_pct(pool_pct(c/last bearish-candle-low preceding confirmed up-break-1)-pool_pct[-5]) | 1 |
| candles.3whitesoldiers.10 | pool_pct(B(white&(P(white)>0)&(P(white,2)>0)&(c>P(c))&(P(c)>P(c,2))&(o<P(c))&(o>P(o)))) | 3 |
| candles.haramicross.10 | pool_pct(B((P(black)>0)&doji&(h<P(o))&(l>P(c)))-B((P(white)>0)&doji&(h<P(c))&(l>P(o)))) | 3 |
| candles.highwave.10__delta5 | pool_pct(pool_pct((B(white)-B(black))*B(short&(upper>body)&(lower>body)))-pool_pct[-5]) | 3 |
| candles.rickshawman.20__history250 | pool_pct(own_rank250(B(doji&(upper>.3*span)&(lower>.3*span)&(abs(c-(h+l)/2)<.1*span)))) | 2 |
| complexity.hurst.200__history250 | pool_pct(own_rank250(log((max(cumsum(centered returns))-min(...))/std(returns))/log(n))) | 1 |
| price_cycle.extended.10 | pool_pct(daily_technical.cycle rules generalized with fast=n,slow=2n,prior range=n; extended) | 1 |
| price_cycle.extended.20 | pool_pct(daily_technical.cycle rules generalized with fast=n,slow=2n,prior range=n; extended) | 1 |
| price_cycle.extended.5 | pool_pct(daily_technical.cycle rules generalized with fast=n,slow=2n,prior range=n; extended) | 1 |
| price_cycle.reversal.10 | pool_pct(daily_technical.cycle rules generalized with fast=n,slow=2n,prior range=n; reversal) | 1 |
| price_cycle.reversal.20 | pool_pct(daily_technical.cycle rules generalized with fast=n,slow=2n,prior range=n; reversal) | 1 |
| price_cycle.reversal.5 | pool_pct(daily_technical.cycle rules generalized with fast=n,slow=2n,prior range=n; reversal) | 1 |
| volume.adosc.100__delta5 | pool_pct(pool_pct((EMA(cumulative_AD,n)-EMA(cumulative_AD,3n))/mean(v,n))-pool_pct[-5]) | 1 |
| volume.adosc.10__delta5 | pool_pct(pool_pct((EMA(cumulative_AD,n)-EMA(cumulative_AD,3n))/mean(v,n))-pool_pct[-5]) | 3 |
| volume.adosc.200__delta5 | pool_pct(pool_pct((EMA(cumulative_AD,n)-EMA(cumulative_AD,3n))/mean(v,n))-pool_pct[-5]) | 1 |
| volume.adosc.50__delta5 | pool_pct(pool_pct((EMA(cumulative_AD,n)-EMA(cumulative_AD,3n))/mean(v,n))-pool_pct[-5]) | 1 |
| candles.3blackcrows.10 | pool_pct(-B(black&(P(black)>0)&(P(black,2)>0)&(c<P(c))&(P(c)<P(c,2))&(o>P(c))&(o<P(o)))) | 3 |
| complexity.roughness.100__delta5 | pool_pct(pool_pct(-sum(abs(second_difference(c)),n)/sum(abs(change(c)),n))-pool_pct[-5]) | 1 |
| complexity.roughness.200__delta5 | pool_pct(pool_pct(-sum(abs(second_difference(c)),n)/sum(abs(change(c)),n))-pool_pct[-5]) | 1 |
| complexity.roughness.20__delta5 | pool_pct(pool_pct(-sum(abs(second_difference(c)),n)/sum(abs(change(c)),n))-pool_pct[-5]) | 1 |
| complexity.roughness.50__delta5 | pool_pct(pool_pct(-sum(abs(second_difference(c)),n)/sum(abs(change(c)),n))-pool_pct[-5]) | 1 |
| darvas.age.10__delta5 | pool_pct(pool_pct(-age(breakout,120); box extremum confirmed by 3 following bars)-pool_pct[-5]) | 2 |
| darvas.age.50__delta5 | pool_pct(pool_pct(-age(breakout,120); box extremum confirmed by 3 following bars)-pool_pct[-5]) | 1 |
| eom.value.100__delta5 | pool_pct(pool_pct(mean(((h+l)/2-(h[-1]+l[-1])/2)*(h-l)/v,n)*mean(v,n)/c^2)-pool_pct[-5]) | 1 |
| eom.value.200__delta5 | pool_pct(pool_pct(mean(((h+l)/2-(h[-1]+l[-1])/2)*(h-l)/v,n)*mean(v,n)/c^2)-pool_pct[-5]) | 1 |
| price_cycle.advancing.10 | pool_pct(daily_technical.cycle rules generalized with fast=n,slow=2n,prior range=n; advancing) | 2 |
| price_cycle.advancing.20 | pool_pct(daily_technical.cycle rules generalized with fast=n,slow=2n,prior range=n; advancing) | 2 |
| price_cycle.advancing.5 | pool_pct(daily_technical.cycle rules generalized with fast=n,slow=2n,prior range=n; advancing) | 1 |
| price_cycle.crossback.10 | pool_pct(daily_technical.cycle rules generalized with fast=n,slow=2n,prior range=n; crossback) | 1 |
| price_cycle.crossback.20 | pool_pct(daily_technical.cycle rules generalized with fast=n,slow=2n,prior range=n; crossback) | 1 |
| price_cycle.crossback.5 | pool_pct(daily_technical.cycle rules generalized with fast=n,slow=2n,prior range=n; crossback) | 1 |
| price_cycle.declining.10 | pool_pct(daily_technical.cycle rules generalized with fast=n,slow=2n,prior range=n; declining) | 1 |
| price_cycle.declining.20 | pool_pct(daily_technical.cycle rules generalized with fast=n,slow=2n,prior range=n; declining) | 1 |
| price_cycle.declining.5 | pool_pct(daily_technical.cycle rules generalized with fast=n,slow=2n,prior range=n; declining) | 1 |
| price_cycle.wedge_pop.10 | pool_pct(daily_technical.cycle rules generalized with fast=n,slow=2n,prior range=n; wedge_pop) | 1 |
| price_cycle.wedge_pop.20 | pool_pct(daily_technical.cycle rules generalized with fast=n,slow=2n,prior range=n; wedge_pop) | 1 |
| price_cycle.wedge_pop.5 | pool_pct(daily_technical.cycle rules generalized with fast=n,slow=2n,prior range=n; wedge_pop) | 1 |
| candles.harami.10 | pool_pct(B((P(black)>0)&white&(c<P(o))&(o>P(c)))-B((P(white)>0)&black&(o<P(c))&(c>P(o)))) | 3 |
| candles.inneck.10__delta5 | pool_pct(pool_pct(-B((P(black)>0)&white&(o<P(l))&(c>P(c))&(c<P(c)+.1*rng)))-pool_pct[-5]) | 3 |
| candles.stalledpattern.10 | pool_pct(-B(white&(P(white)>0)&(P(white,2)>0)&(c>P(c))&(P(c)>P(c,2))&short&(upper>body))) | 6 |
| candles.unique3river.10 | pool_pct(B((P(black,2)>0)&(P(black)>0)&(P(l)<P(l,2))&(P(c)>P(c,2))&white&short&(c<P(c)))) | 3 |
| hilbert.leadsine.16 | pool_pct(causal Ehlers quadrature FIR (.0962,.5769,-.5769,-.0962), lag 0/2/4/6; sin(phase+pi/4)) | 3 |
| hilbert.leadsine.4 | pool_pct(causal Ehlers quadrature FIR (.0962,.5769,-.5769,-.0962), lag 0/2/4/6; sin(phase+pi/4)) | 3 |
| hilbert.leadsine.8 | pool_pct(causal Ehlers quadrature FIR (.0962,.5769,-.5769,-.0962), lag 0/2/4/6; sin(phase+pi/4)) | 3 |
| price_cycle.base_break.10 | pool_pct(daily_technical.cycle rules generalized with fast=n,slow=2n,prior range=n; base_break) | 1 |
| price_cycle.base_break.20 | pool_pct(daily_technical.cycle rules generalized with fast=n,slow=2n,prior range=n; base_break) | 1 |
| price_cycle.base_break.5 | pool_pct(daily_technical.cycle rules generalized with fast=n,slow=2n,prior range=n; base_break) | 1 |
| price_cycle.wedge_drop.10 | pool_pct(daily_technical.cycle rules generalized with fast=n,slow=2n,prior range=n; wedge_drop) | 1 |
| price_cycle.wedge_drop.20 | pool_pct(daily_technical.cycle rules generalized with fast=n,slow=2n,prior range=n; wedge_drop) | 1 |
| price_cycle.wedge_drop.5 | pool_pct(daily_technical.cycle rules generalized with fast=n,slow=2n,prior range=n; wedge_drop) | 1 |
| volatility.rogers_satchell.14__delta5 | pool_pct(pool_pct(sqrt(max(0,mean(log(h/o)*log(h/c)+log(l/o)*log(l/c),n))))-pool_pct[-5]) | 1 |
| volatility.rogers_satchell.5__delta5 | pool_pct(pool_pct(sqrt(max(0,mean(log(h/o)*log(h/c)+log(l/o)*log(l/c),n))))-pool_pct[-5]) | 1 |
| candles.2crows.10 | pool_pct(-B((P(white,2)>0)&(P(black)>0)&black&(P(o)>P(c,2))&(o<P(o))&(c>P(c,2))&(c<P(c)))) | 3 |
| candles.piercing.10__delta5 | pool_pct(pool_pct(B((P(black)>0)&white&(o<P(l))&(c>(P(o)+P(c))/2)&(c<P(o))))-pool_pct[-5]) | 3 |
| candles.sticksandwich.10__history250 | pool_pct(own_rank250(B((P(black,2)>0)&(P(white)>0)&black&within(c,P(c,2))&(P(l)>P(c,2))))) | 3 |
| candles.upsidegap2crows.10 | pool_pct(-B((P(white,2)>0)&(P(black)>0)&black&(P(c)>P(c,2))&(o>P(o))&(c<P(c))&(c>P(c,2)))) | 3 |
| candles.darkcloudcover.10__delta5 | pool_pct(pool_pct(-B((P(white)>0)&black&(o>P(h))&(c<(P(o)+P(c))/2)&(c>P(o))))-pool_pct[-5]) | 3 |
| candles.thrusting.10__delta5 | pool_pct(pool_pct(-B((P(black)>0)&white&(o<P(l))&(c>P(c))&(c<(P(o)+P(c))/2)))-pool_pct[-5]) | 3 |
| events.earn_drift.14__delta5 | pool_pct(pool_pct(c/close_at_first_observable_post_earnings_session-1, age<=n)-pool_pct[-5]) | 2 |
| events.earn_drift.50__delta5 | pool_pct(pool_pct(c/close_at_first_observable_post_earnings_session-1, age<=n)-pool_pct[-5]) | 1 |
| events.earn_gap.10__history250 | pool_pct(own_rank250(last occurred earnings first-next-session gap; only when session has occurred)) | 2 |
| events.earn_gap.20__history250 | pool_pct(own_rank250(last occurred earnings first-next-session gap; only when session has occurred)) | 1 |
| events.earn_gap.3__history250 | pool_pct(own_rank250(last occurred earnings first-next-session gap; only when session has occurred)) | 2 |
| events.earn_gap.50__history250 | pool_pct(own_rank250(last occurred earnings first-next-session gap; only when session has occurred)) | 1 |
| candles.closingmarubozu.10__delta5 | pool_pct(pool_pct(B(white&long&(upper<=.1*rng))-B(black&long&(lower<=.1*rng)))-pool_pct[-5]) | 3 |
| candles.engulfing.10 | pool_pct(B(white&(P(black)>0)&(o<=P(c))&(c>=P(o)))-B(black&(P(white)>0)&(o>=P(c))&(c<=P(o)))) | 3 |
| candles.spinningtop.10__delta5 | pool_pct(pool_pct((B(white)-B(black))*B(short&(upper>body)&(lower>body)&~doji))-pool_pct[-5]) | 3 |
| darvas.position.50__delta5 | pool_pct(pool_pct((c-confirmed_box_low)/(confirmed_box_high-confirmed_box_low))-pool_pct[-5]) | 1 |
| hilbert.dcperiod.16 | pool_pct(causal Ehlers quadrature FIR (.0962,.5769,-.5769,-.0962), lag 0/2/4/6; smoothed period 6..50) | 2 |
| hilbert.dcperiod.4 | pool_pct(causal Ehlers quadrature FIR (.0962,.5769,-.5769,-.0962), lag 0/2/4/6; smoothed period 6..50) | 4 |
| statistics.beta.100__delta5 | pool_pct(pool_pct(cov(stock_log_return,QQQ_log_return,n)/var(QQQ_log_return,n))-pool_pct[-5]) | 1 |
| statistics.beta.14__delta5 | pool_pct(pool_pct(cov(stock_log_return,QQQ_log_return,n)/var(QQQ_log_return,n))-pool_pct[-5]) | 1 |
| statistics.beta.200__delta5 | pool_pct(pool_pct(cov(stock_log_return,QQQ_log_return,n)/var(QQQ_log_return,n))-pool_pct[-5]) | 1 |
| statistics.beta.20__delta5 | pool_pct(pool_pct(cov(stock_log_return,QQQ_log_return,n)/var(QQQ_log_return,n))-pool_pct[-5]) | 1 |
| statistics.beta.3__delta5 | pool_pct(pool_pct(cov(stock_log_return,QQQ_log_return,n)/var(QQQ_log_return,n))-pool_pct[-5]) | 1 |
| statistics.beta.50__delta5 | pool_pct(pool_pct(cov(stock_log_return,QQQ_log_return,n)/var(QQQ_log_return,n))-pool_pct[-5]) | 1 |
| statistics.beta.5__delta5 | pool_pct(pool_pct(cov(stock_log_return,QQQ_log_return,n)/var(QQQ_log_return,n))-pool_pct[-5]) | 1 |
| vcp.score.10__delta5 | pool_pct(pool_pct(count(contracting ranges,falling volume,higher low,close>EMA50))-pool_pct[-5]) | 1 |
| vcp.score.20__delta5 | pool_pct(pool_pct(count(contracting ranges,falling volume,higher low,close>EMA50))-pool_pct[-5]) | 1 |
| vcp.score.50__delta5 | pool_pct(pool_pct(count(contracting ranges,falling volume,higher low,close>EMA50))-pool_pct[-5]) | 1 |
| candles.morningdojistar.10__history250 | pool_pct(own_rank250(B((P(black,2)>0)&(P(doji)>0)&white&(P(o)<P(c,2))&(c>(P(o,2)+P(c,2))/2)))) | 3 |
| momentum.mfi.100__delta5 | pool_pct(pool_pct(sum(typical*v where typical rises,n)/sum(directional typical*v,n))-pool_pct[-5]) | 1 |
| momentum.mfi.200__delta5 | pool_pct(pool_pct(sum(typical*v where typical rises,n)/sum(directional typical*v,n))-pool_pct[-5]) | 1 |
| momentum.mfi.50__delta5 | pool_pct(pool_pct(sum(typical*v where typical rises,n)/sum(directional typical*v,n))-pool_pct[-5]) | 1 |
| momentum.mfi.5__delta5 | pool_pct(pool_pct(sum(typical*v where typical rises,n)/sum(directional typical*v,n))-pool_pct[-5]) | 1 |
| candles.belthold.10__history250 | pool_pct(own_rank250(B(white&long&(lower<=.1*rng)&~trend)-B(black&long&(upper<=.1*rng)&trend))) | 1 |
| candles.belthold.20__history250 | pool_pct(own_rank250(B(white&long&(lower<=.1*rng)&~trend)-B(black&long&(upper<=.1*rng)&trend))) | 1 |
| candles.belthold.5__history250 | pool_pct(own_rank250(B(white&long&(lower<=.1*rng)&~trend)-B(black&long&(upper<=.1*rng)&trend))) | 1 |
| candles.eveningdojistar.10__history250 | pool_pct(own_rank250(-B((P(white,2)>0)&(P(doji)>0)&black&(P(o)>P(c,2))&(c<(P(o,2)+P(c,2))/2)))) | 3 |
| candles.morningstar.10__history250 | pool_pct(own_rank250(B((P(black,2)>0)&(P(short)>0)&white&(P(o)<P(c,2))&(c>(P(o,2)+P(c,2))/2)))) | 3 |
| candles.eveningstar.10__history250 | pool_pct(own_rank250(-B((P(white,2)>0)&(P(short)>0)&black&(P(o)>P(c,2))&(c<(P(o,2)+P(c,2))/2)))) | 3 |
| candles.separatinglines.10 | pool_pct(B(white&(P(black)>0)&within(o,P(o))&trend)-B(black&(P(white)>0)&within(o,P(o))&~trend)) | 3 |
| complexity.hurst.100__delta5 | pool_pct(pool_pct(log((max(cumsum(centered returns))-min(...))/std(returns))/log(n))-pool_pct[-5]) | 1 |
| complexity.hurst.200__delta5 | pool_pct(pool_pct(log((max(cumsum(centered returns))-min(...))/std(returns))/log(n))-pool_pct[-5]) | 1 |
| complexity.hurst.20__delta5 | pool_pct(pool_pct(log((max(cumsum(centered returns))-min(...))/std(returns))/log(n))-pool_pct[-5]) | 1 |
| complexity.hurst.50__delta5 | pool_pct(pool_pct(log((max(cumsum(centered returns))-min(...))/std(returns))/log(n))-pool_pct[-5]) | 1 |
| hilbert.trendmode.16 | pool_pct(causal Ehlers quadrature FIR (.0962,.5769,-.5769,-.0962), lag 0/2/4/6; 1(abs(c-trendline)>ATR14)) | 2 |
| hilbert.trendmode.4 | pool_pct(causal Ehlers quadrature FIR (.0962,.5769,-.5769,-.0962), lag 0/2/4/6; 1(abs(c-trendline)>ATR14)) | 3 |
| candles.3whitesoldiers.10__history250 | pool_pct(own_rank250(B(white&(P(white)>0)&(P(white,2)>0)&(c>P(c))&(P(c)>P(c,2))&(o<P(c))&(o>P(o))))) | 3 |
| candles.haramicross.10__history250 | pool_pct(own_rank250(B((P(black)>0)&doji&(h<P(o))&(l>P(c)))-B((P(white)>0)&doji&(h<P(c))&(l>P(o))))) | 3 |
| candles.sticksandwich.10__delta5 | pool_pct(pool_pct(B((P(black,2)>0)&(P(white)>0)&black&within(c,P(c,2))&(P(l)>P(c,2))))-pool_pct[-5]) | 3 |
| hilbert.inphase.16__delta5 | pool_pct(pool_pct(causal Ehlers quadrature FIR (.0962,.5769,-.5769,-.0962), lag 0/2/4/6; I/c)-pool_pct[-5]) | 1 |
| price_cycle.extended.10__history250 | pool_pct(own_rank250(daily_technical.cycle rules generalized with fast=n,slow=2n,prior range=n; extended)) | 1 |
| price_cycle.extended.20__history250 | pool_pct(own_rank250(daily_technical.cycle rules generalized with fast=n,slow=2n,prior range=n; extended)) | 1 |
| price_cycle.extended.5__history250 | pool_pct(own_rank250(daily_technical.cycle rules generalized with fast=n,slow=2n,prior range=n; extended)) | 1 |
| price_cycle.reversal.10__history250 | pool_pct(own_rank250(daily_technical.cycle rules generalized with fast=n,slow=2n,prior range=n; reversal)) | 1 |
| price_cycle.reversal.20__history250 | pool_pct(own_rank250(daily_technical.cycle rules generalized with fast=n,slow=2n,prior range=n; reversal)) | 1 |
| price_cycle.reversal.5__history250 | pool_pct(own_rank250(daily_technical.cycle rules generalized with fast=n,slow=2n,prior range=n; reversal)) | 1 |
| candles.3blackcrows.10__history250 | pool_pct(own_rank250(-B(black&(P(black)>0)&(P(black,2)>0)&(c<P(c))&(P(c)<P(c,2))&(o>P(c))&(o<P(o))))) | 3 |
| events.earn_gap.100__delta5 | pool_pct(pool_pct(last occurred earnings first-next-session gap; only when session has occurred)-pool_pct[-5]) | 3 |
| events.earn_gap.10__delta5 | pool_pct(pool_pct(last occurred earnings first-next-session gap; only when session has occurred)-pool_pct[-5]) | 2 |
| events.earn_gap.20__delta5 | pool_pct(pool_pct(last occurred earnings first-next-session gap; only when session has occurred)-pool_pct[-5]) | 1 |
| price_cycle.advancing.5__history250 | pool_pct(own_rank250(daily_technical.cycle rules generalized with fast=n,slow=2n,prior range=n; advancing)) | 1 |
| price_cycle.crossback.10__history250 | pool_pct(own_rank250(daily_technical.cycle rules generalized with fast=n,slow=2n,prior range=n; crossback)) | 1 |
| price_cycle.crossback.20__history250 | pool_pct(own_rank250(daily_technical.cycle rules generalized with fast=n,slow=2n,prior range=n; crossback)) | 1 |
| price_cycle.crossback.5__history250 | pool_pct(own_rank250(daily_technical.cycle rules generalized with fast=n,slow=2n,prior range=n; crossback)) | 1 |
| price_cycle.declining.10__history250 | pool_pct(own_rank250(daily_technical.cycle rules generalized with fast=n,slow=2n,prior range=n; declining)) | 3 |
| price_cycle.wedge_pop.10__history250 | pool_pct(own_rank250(daily_technical.cycle rules generalized with fast=n,slow=2n,prior range=n; wedge_pop)) | 1 |
| price_cycle.wedge_pop.20__history250 | pool_pct(own_rank250(daily_technical.cycle rules generalized with fast=n,slow=2n,prior range=n; wedge_pop)) | 1 |
| price_cycle.wedge_pop.5__history250 | pool_pct(own_rank250(daily_technical.cycle rules generalized with fast=n,slow=2n,prior range=n; wedge_pop)) | 1 |
| candles.harami.10__history250 | pool_pct(own_rank250(B((P(black)>0)&white&(c<P(o))&(o>P(c)))-B((P(white)>0)&black&(o<P(c))&(c>P(o))))) | 3 |
| candles.stalledpattern.10__history250 | pool_pct(own_rank250(-B(white&(P(white)>0)&(P(white,2)>0)&(c>P(c))&(P(c)>P(c,2))&short&(upper>body)))) | 3 |
| candles.unique3river.10__history250 | pool_pct(own_rank250(B((P(black,2)>0)&(P(black)>0)&(P(l)<P(l,2))&(P(c)>P(c,2))&white&short&(c<P(c))))) | 3 |
| price_cycle.base_break.10__history250 | pool_pct(own_rank250(daily_technical.cycle rules generalized with fast=n,slow=2n,prior range=n; base_break)) | 1 |
| price_cycle.base_break.20__history250 | pool_pct(own_rank250(daily_technical.cycle rules generalized with fast=n,slow=2n,prior range=n; base_break)) | 1 |
| price_cycle.base_break.5__history250 | pool_pct(own_rank250(daily_technical.cycle rules generalized with fast=n,slow=2n,prior range=n; base_break)) | 1 |
| price_cycle.wedge_drop.10__history250 | pool_pct(own_rank250(daily_technical.cycle rules generalized with fast=n,slow=2n,prior range=n; wedge_drop)) | 1 |
| price_cycle.wedge_drop.20__history250 | pool_pct(own_rank250(daily_technical.cycle rules generalized with fast=n,slow=2n,prior range=n; wedge_drop)) | 1 |
| price_cycle.wedge_drop.5__history250 | pool_pct(own_rank250(daily_technical.cycle rules generalized with fast=n,slow=2n,prior range=n; wedge_drop)) | 1 |
| candles.2crows.10__history250 | pool_pct(own_rank250(-B((P(white,2)>0)&(P(black)>0)&black&(P(o)>P(c,2))&(o<P(o))&(c>P(c,2))&(c<P(c))))) | 3 |
| candles.upsidegap2crows.10__history250 | pool_pct(own_rank250(-B((P(white,2)>0)&(P(black)>0)&black&(P(c)>P(c,2))&(o>P(o))&(c<P(c))&(c>P(c,2))))) | 3 |
| candles.mathold.10 | pool_pct(B((P(white,4)>0)&(P(long,4)>0)&(P(o,3)>P(c,4))&(P(l,2)>P(o,4))&(P(l)>P(o,4))&white&(c>P(h,4)))) | 3 |
| candles.morningdojistar.10__delta5 | pool_pct(pool_pct(B((P(black,2)>0)&(P(doji)>0)&white&(P(o)<P(c,2))&(c>(P(o,2)+P(c,2))/2)))-pool_pct[-5]) | 3 |
| candles.belthold.10__delta5 | pool_pct(pool_pct(B(white&long&(lower<=.1*rng)&~trend)-B(black&long&(upper<=.1*rng)&trend))-pool_pct[-5]) | 1 |
| candles.belthold.20__delta5 | pool_pct(pool_pct(B(white&long&(lower<=.1*rng)&~trend)-B(black&long&(upper<=.1*rng)&trend))-pool_pct[-5]) | 1 |
| candles.belthold.5__delta5 | pool_pct(pool_pct(B(white&long&(lower<=.1*rng)&~trend)-B(black&long&(upper<=.1*rng)&trend))-pool_pct[-5]) | 1 |
| candles.eveningdojistar.10__delta5 | pool_pct(pool_pct(-B((P(white,2)>0)&(P(doji)>0)&black&(P(o)>P(c,2))&(c<(P(o,2)+P(c,2))/2)))-pool_pct[-5]) | 3 |
| candles.identical3crows.10 | pool_pct(-B(black&(P(black)>0)&(P(black,2)>0)&within(o,P(c))&within(P(o),P(c,2))&(c<P(c))&(P(c)<P(c,2)))) | 3 |
| candles.kicking.10 | pool_pct(B(white&maru&(P(black)>0)&(P(maru)>0)&(l>P(h)))-B(black&maru&(P(white)>0)&(P(maru)>0)&(h<P(l)))) | 2 |
| candles.kicking.20 | pool_pct(B(white&maru&(P(black)>0)&(P(maru)>0)&(l>P(h)))-B(black&maru&(P(white)>0)&(P(maru)>0)&(h<P(l)))) | 2 |
| candles.kicking.5 | pool_pct(B(white&maru&(P(black)>0)&(P(maru)>0)&(l>P(h)))-B(black&maru&(P(white)>0)&(P(maru)>0)&(h<P(l)))) | 1 |
| candles.morningstar.10__delta5 | pool_pct(pool_pct(B((P(black,2)>0)&(P(short)>0)&white&(P(o)<P(c,2))&(c>(P(o,2)+P(c,2))/2)))-pool_pct[-5]) | 3 |
| candles.engulfing.10__history250 | pool_pct(own_rank250(B(white&(P(black)>0)&(o<=P(c))&(c>=P(o)))-B(black&(P(white)>0)&(o>=P(c))&(c<=P(o))))) | 3 |
| candles.eveningstar.10__delta5 | pool_pct(pool_pct(-B((P(white,2)>0)&(P(short)>0)&black&(P(o)>P(c,2))&(c<(P(o,2)+P(c,2))/2)))-pool_pct[-5]) | 3 |
| candles.hikkake.10 | pool_pct(B((P(h)<P(h,2))&(P(l)>P(l,2))&(h>P(h))&(l>P(l)))-B((P(h)<P(h,2))&(P(l)>P(l,2))&(h<P(h))&(l<P(l)))) | 3 |
| hilbert.sine.16__delta5 | pool_pct(pool_pct(causal Ehlers quadrature FIR (.0962,.5769,-.5769,-.0962), lag 0/2/4/6; sin(phase))-pool_pct[-5]) | 1 |
| hilbert.sine.8__delta5 | pool_pct(pool_pct(causal Ehlers quadrature FIR (.0962,.5769,-.5769,-.0962), lag 0/2/4/6; sin(phase))-pool_pct[-5]) | 1 |
| candles.separatinglines.10__history250 | pool_pct(own_rank250(B(white&(P(black)>0)&within(o,P(o))&trend)-B(black&(P(white)>0)&within(o,P(o))&~trend))) | 1 |
| candles.separatinglines.20__history250 | pool_pct(own_rank250(B(white&(P(black)>0)&within(o,P(o))&trend)-B(black&(P(white)>0)&within(o,P(o))&~trend))) | 1 |
| candles.separatinglines.5__history250 | pool_pct(own_rank250(B(white&(P(black)>0)&within(o,P(o))&trend)-B(black&(P(white)>0)&within(o,P(o))&~trend))) | 1 |
| candles.3whitesoldiers.10__delta5 | pool_pct(pool_pct(B(white&(P(white)>0)&(P(white,2)>0)&(c>P(c))&(P(c)>P(c,2))&(o<P(c))&(o>P(o))))-pool_pct[-5]) | 3 |
| candles.haramicross.10__delta5 | pool_pct(pool_pct(B((P(black)>0)&doji&(h<P(o))&(l>P(c)))-B((P(white)>0)&doji&(h<P(c))&(l>P(o))))-pool_pct[-5]) | 3 |
| price_cycle.extended.10__delta5 | pool_pct(pool_pct(daily_technical.cycle rules generalized with fast=n,slow=2n,prior range=n; extended)-pool_pct[-5]) | 1 |
| price_cycle.extended.20__delta5 | pool_pct(pool_pct(daily_technical.cycle rules generalized with fast=n,slow=2n,prior range=n; extended)-pool_pct[-5]) | 1 |
| price_cycle.extended.5__delta5 | pool_pct(pool_pct(daily_technical.cycle rules generalized with fast=n,slow=2n,prior range=n; extended)-pool_pct[-5]) | 1 |
| price_cycle.reversal.10__delta5 | pool_pct(pool_pct(daily_technical.cycle rules generalized with fast=n,slow=2n,prior range=n; reversal)-pool_pct[-5]) | 1 |
| price_cycle.reversal.20__delta5 | pool_pct(pool_pct(daily_technical.cycle rules generalized with fast=n,slow=2n,prior range=n; reversal)-pool_pct[-5]) | 1 |
| price_cycle.reversal.5__delta5 | pool_pct(pool_pct(daily_technical.cycle rules generalized with fast=n,slow=2n,prior range=n; reversal)-pool_pct[-5]) | 1 |
| candles.3blackcrows.10__delta5 | pool_pct(pool_pct(-B(black&(P(black)>0)&(P(black,2)>0)&(c<P(c))&(P(c)<P(c,2))&(o>P(c))&(o<P(o))))-pool_pct[-5]) | 3 |
| price_cycle.advancing.10__delta5 | pool_pct(pool_pct(daily_technical.cycle rules generalized with fast=n,slow=2n,prior range=n; advancing)-pool_pct[-5]) | 1 |
| price_cycle.advancing.20__delta5 | pool_pct(pool_pct(daily_technical.cycle rules generalized with fast=n,slow=2n,prior range=n; advancing)-pool_pct[-5]) | 1 |
| price_cycle.advancing.5__delta5 | pool_pct(pool_pct(daily_technical.cycle rules generalized with fast=n,slow=2n,prior range=n; advancing)-pool_pct[-5]) | 1 |
| price_cycle.crossback.10__delta5 | pool_pct(pool_pct(daily_technical.cycle rules generalized with fast=n,slow=2n,prior range=n; crossback)-pool_pct[-5]) | 1 |
| price_cycle.crossback.20__delta5 | pool_pct(pool_pct(daily_technical.cycle rules generalized with fast=n,slow=2n,prior range=n; crossback)-pool_pct[-5]) | 1 |
| price_cycle.crossback.5__delta5 | pool_pct(pool_pct(daily_technical.cycle rules generalized with fast=n,slow=2n,prior range=n; crossback)-pool_pct[-5]) | 1 |
| price_cycle.declining.10__delta5 | pool_pct(pool_pct(daily_technical.cycle rules generalized with fast=n,slow=2n,prior range=n; declining)-pool_pct[-5]) | 1 |
| price_cycle.declining.20__delta5 | pool_pct(pool_pct(daily_technical.cycle rules generalized with fast=n,slow=2n,prior range=n; declining)-pool_pct[-5]) | 1 |
| price_cycle.declining.5__delta5 | pool_pct(pool_pct(daily_technical.cycle rules generalized with fast=n,slow=2n,prior range=n; declining)-pool_pct[-5]) | 1 |
| price_cycle.wedge_pop.10__delta5 | pool_pct(pool_pct(daily_technical.cycle rules generalized with fast=n,slow=2n,prior range=n; wedge_pop)-pool_pct[-5]) | 1 |
| price_cycle.wedge_pop.20__delta5 | pool_pct(pool_pct(daily_technical.cycle rules generalized with fast=n,slow=2n,prior range=n; wedge_pop)-pool_pct[-5]) | 1 |
| price_cycle.wedge_pop.5__delta5 | pool_pct(pool_pct(daily_technical.cycle rules generalized with fast=n,slow=2n,prior range=n; wedge_pop)-pool_pct[-5]) | 1 |
| candles.harami.10__delta5 | pool_pct(pool_pct(B((P(black)>0)&white&(c<P(o))&(o>P(c)))-B((P(white)>0)&black&(o<P(c))&(c>P(o))))-pool_pct[-5]) | 3 |
| candles.stalledpattern.10__delta5 | pool_pct(pool_pct(-B(white&(P(white)>0)&(P(white,2)>0)&(c>P(c))&(P(c)>P(c,2))&short&(upper>body)))-pool_pct[-5]) | 6 |
| candles.unique3river.10__delta5 | pool_pct(pool_pct(B((P(black,2)>0)&(P(black)>0)&(P(l)<P(l,2))&(P(c)>P(c,2))&white&short&(c<P(c))))-pool_pct[-5]) | 3 |
| hilbert.trendmode.8__history250 | pool_pct(own_rank250(causal Ehlers quadrature FIR (.0962,.5769,-.5769,-.0962), lag 0/2/4/6; 1(abs(c-trendline)>ATR14))) | 1 |
| price_cycle.base_break.10__delta5 | pool_pct(pool_pct(daily_technical.cycle rules generalized with fast=n,slow=2n,prior range=n; base_break)-pool_pct[-5]) | 1 |
| price_cycle.base_break.20__delta5 | pool_pct(pool_pct(daily_technical.cycle rules generalized with fast=n,slow=2n,prior range=n; base_break)-pool_pct[-5]) | 1 |
| price_cycle.base_break.5__delta5 | pool_pct(pool_pct(daily_technical.cycle rules generalized with fast=n,slow=2n,prior range=n; base_break)-pool_pct[-5]) | 1 |
| price_cycle.wedge_drop.10__delta5 | pool_pct(pool_pct(daily_technical.cycle rules generalized with fast=n,slow=2n,prior range=n; wedge_drop)-pool_pct[-5]) | 1 |
| price_cycle.wedge_drop.20__delta5 | pool_pct(pool_pct(daily_technical.cycle rules generalized with fast=n,slow=2n,prior range=n; wedge_drop)-pool_pct[-5]) | 1 |
| price_cycle.wedge_drop.5__delta5 | pool_pct(pool_pct(daily_technical.cycle rules generalized with fast=n,slow=2n,prior range=n; wedge_drop)-pool_pct[-5]) | 1 |
| candles.2crows.10__delta5 | pool_pct(pool_pct(-B((P(white,2)>0)&(P(black)>0)&black&(P(o)>P(c,2))&(o<P(o))&(c>P(c,2))&(c<P(c))))-pool_pct[-5]) | 3 |
| candles.3starsinsouth.10 | pool_pct(B(black&(P(black)>0)&(P(black,2)>0)&(l>P(l))&(P(l)>P(l,2))&(h<P(h))&(P(body)<P(body,2))&(body<P(body)))) | 6 |
| candles.upsidegap2crows.10__delta5 | pool_pct(pool_pct(-B((P(white,2)>0)&(P(black)>0)&black&(P(c)>P(c,2))&(o>P(o))&(c<P(c))&(c>P(c,2))))-pool_pct[-5]) | 3 |
| candles.advanceblock.10__history250 | pool_pct(own_rank250(-B(white&(P(white)>0)&(P(white,2)>0)&(c>P(c))&(P(c)>P(c,2))&(body<P(body))&(upper>P(upper))))) | 3 |
| candles.engulfing.10__delta5 | pool_pct(pool_pct(B(white&(P(black)>0)&(o<=P(c))&(c>=P(o)))-B(black&(P(white)>0)&(o>=P(c))&(c<=P(o))))-pool_pct[-5]) | 3 |
| hilbert.dcperiod.16__delta5 | pool_pct(pool_pct(causal Ehlers quadrature FIR (.0962,.5769,-.5769,-.0962), lag 0/2/4/6; smoothed period 6..50)-pool_pct[-5]) | 1 |
| hilbert.dcperiod.4__delta5 | pool_pct(pool_pct(causal Ehlers quadrature FIR (.0962,.5769,-.5769,-.0962), lag 0/2/4/6; smoothed period 6..50)-pool_pct[-5]) | 1 |
| hilbert.dcperiod.8__delta5 | pool_pct(pool_pct(causal Ehlers quadrature FIR (.0962,.5769,-.5769,-.0962), lag 0/2/4/6; smoothed period 6..50)-pool_pct[-5]) | 1 |
| candles.counterattack.10 | pool_pct(B((P(black)>0)&white&long&(P(long)>0)&within(c,P(c)))-B((P(white)>0)&black&long&(P(long)>0)&within(c,P(c)))) | 1 |
| candles.counterattack.20 | pool_pct(B((P(black)>0)&white&long&(P(long)>0)&within(c,P(c)))-B((P(white)>0)&black&long&(P(long)>0)&within(c,P(c)))) | 1 |
| candles.counterattack.5 | pool_pct(B((P(black)>0)&white&long&(P(long)>0)&within(c,P(c)))-B((P(white)>0)&black&long&(P(long)>0)&within(c,P(c)))) | 1 |
| candles.mathold.10__history250 | pool_pct(own_rank250(B((P(white,4)>0)&(P(long,4)>0)&(P(o,3)>P(c,4))&(P(l,2)>P(o,4))&(P(l)>P(o,4))&white&(c>P(h,4))))) | 3 |
| candles.identical3crows.10__history250 | pool_pct(own_rank250(-B(black&(P(black)>0)&(P(black,2)>0)&within(o,P(c))&within(P(o),P(c,2))&(c<P(c))&(P(c)<P(c,2))))) | 3 |
| candles.kicking.10__history250 | pool_pct(own_rank250(B(white&maru&(P(black)>0)&(P(maru)>0)&(l>P(h)))-B(black&maru&(P(white)>0)&(P(maru)>0)&(h<P(l))))) | 1 |
| candles.kicking.20__history250 | pool_pct(own_rank250(B(white&maru&(P(black)>0)&(P(maru)>0)&(l>P(h)))-B(black&maru&(P(white)>0)&(P(maru)>0)&(h<P(l))))) | 1 |
| candles.kicking.5__history250 | pool_pct(own_rank250(B(white&maru&(P(black)>0)&(P(maru)>0)&(l>P(h)))-B(black&maru&(P(white)>0)&(P(maru)>0)&(h<P(l))))) | 1 |
| candles.separatinglines.10__delta5 | pool_pct(pool_pct(B(white&(P(black)>0)&within(o,P(o))&trend)-B(black&(P(white)>0)&within(o,P(o))&~trend))-pool_pct[-5]) | 1 |
| candles.separatinglines.20__delta5 | pool_pct(pool_pct(B(white&(P(black)>0)&within(o,P(o))&trend)-B(black&(P(white)>0)&within(o,P(o))&~trend))-pool_pct[-5]) | 1 |
| candles.separatinglines.5__delta5 | pool_pct(pool_pct(B(white&(P(black)>0)&within(o,P(o))&trend)-B(black&(P(white)>0)&within(o,P(o))&~trend))-pool_pct[-5]) | 1 |
| candles.hikkake.10__history250 | pool_pct(own_rank250(B((P(h)<P(h,2))&(P(l)>P(l,2))&(h>P(h))&(l>P(l)))-B((P(h)<P(h,2))&(P(l)>P(l,2))&(h<P(h))&(l<P(l))))) | 3 |
| hilbert.trendmode.16__delta5 | pool_pct(pool_pct(causal Ehlers quadrature FIR (.0962,.5769,-.5769,-.0962), lag 0/2/4/6; 1(abs(c-trendline)>ATR14))-pool_pct[-5]) | 1 |
| hilbert.trendmode.4__delta5 | pool_pct(pool_pct(causal Ehlers quadrature FIR (.0962,.5769,-.5769,-.0962), lag 0/2/4/6; 1(abs(c-trendline)>ATR14))-pool_pct[-5]) | 2 |
| candles.ladderbottom.10 | pool_pct(B((P(black,4)>0)&(P(black,3)>0)&(P(black,2)>0)&(P(c,3)<P(c,4))&(P(c,2)<P(c,3))&(P(upper)>P(body))&white&(c>P(h)))) | 3 |
| candles.tristar.10 | pool_pct(B(doji&(P(doji)>0)&(P(doji,2)>0)&(P(h)<P(l,2))&(l>P(h)))-B(doji&(P(doji)>0)&(P(doji,2)>0)&(P(l)>P(h,2))&(h<P(l)))) | 1 |
| candles.tristar.20 | pool_pct(B(doji&(P(doji)>0)&(P(doji,2)>0)&(P(h)<P(l,2))&(l>P(h)))-B(doji&(P(doji)>0)&(P(doji,2)>0)&(P(l)>P(h,2))&(h<P(l)))) | 1 |
| candles.tristar.5 | pool_pct(B(doji&(P(doji)>0)&(P(doji,2)>0)&(P(h)<P(l,2))&(l>P(h)))-B(doji&(P(doji)>0)&(P(doji,2)>0)&(P(l)>P(h,2))&(h<P(l)))) | 1 |
| candles.concealbabyswall.10 | pool_pct(B((P(black,3)>0)&(P(black,2)>0)&(P(maru,3)>0)&(P(maru,2)>0)&(P(black)>0)&(P(upper)>.2*rng)&black&(h>P(h))&(l<P(l)))) | 1 |
| candles.concealbabyswall.20 | pool_pct(B((P(black,3)>0)&(P(black,2)>0)&(P(maru,3)>0)&(P(maru,2)>0)&(P(black)>0)&(P(upper)>.2*rng)&black&(h>P(h))&(l<P(l)))) | 1 |
| candles.concealbabyswall.5 | pool_pct(B((P(black,3)>0)&(P(black,2)>0)&(P(maru,3)>0)&(P(maru,2)>0)&(P(black)>0)&(P(upper)>.2*rng)&black&(h>P(h))&(l<P(l)))) | 1 |
| candles.3starsinsouth.10__history250 | pool_pct(own_rank250(B(black&(P(black)>0)&(P(black,2)>0)&(l>P(l))&(P(l)>P(l,2))&(h<P(h))&(P(body)<P(body,2))&(body<P(body))))) | 3 |
| candles.abandonedbaby.10 | pool_pct(B((P(black,2)>0)&(P(doji)>0)&white&(P(h)<P(l,2))&(l>P(h)))-B((P(white,2)>0)&(P(doji)>0)&black&(P(l)>P(h,2))&(h<P(l)))) | 3 |
| candles.mathold.10__delta5 | pool_pct(pool_pct(B((P(white,4)>0)&(P(long,4)>0)&(P(o,3)>P(c,4))&(P(l,2)>P(o,4))&(P(l)>P(o,4))&white&(c>P(h,4))))-pool_pct[-5]) | 3 |
| candles.identical3crows.10__delta5 | pool_pct(pool_pct(-B(black&(P(black)>0)&(P(black,2)>0)&within(o,P(c))&within(P(o),P(c,2))&(c<P(c))&(P(c)<P(c,2))))-pool_pct[-5]) | 3 |
| candles.kicking.10__delta5 | pool_pct(pool_pct(B(white&maru&(P(black)>0)&(P(maru)>0)&(l>P(h)))-B(black&maru&(P(white)>0)&(P(maru)>0)&(h<P(l))))-pool_pct[-5]) | 2 |
| candles.kicking.20__delta5 | pool_pct(pool_pct(B(white&maru&(P(black)>0)&(P(maru)>0)&(l>P(h)))-B(black&maru&(P(white)>0)&(P(maru)>0)&(h<P(l))))-pool_pct[-5]) | 2 |
| candles.kicking.5__delta5 | pool_pct(pool_pct(B(white&maru&(P(black)>0)&(P(maru)>0)&(l>P(h)))-B(black&maru&(P(white)>0)&(P(maru)>0)&(h<P(l))))-pool_pct[-5]) | 1 |
| candles.hikkakemod.10 | pool_pct(B((P(h,2)<P(h,3))&(P(l,2)>P(l,3))&(P(h)<P(h,2))&(c>P(h,2)))-B((P(h,2)<P(h,3))&(P(l,2)>P(l,3))&(P(l)>P(l,2))&(c<P(l,2)))) | 3 |
| candles.counterattack.10__history250 | pool_pct(own_rank250(B((P(black)>0)&white&long&(P(long)>0)&within(c,P(c)))-B((P(white)>0)&black&long&(P(long)>0)&within(c,P(c))))) | 1 |
| candles.counterattack.20__history250 | pool_pct(own_rank250(B((P(black)>0)&white&long&(P(long)>0)&within(c,P(c)))-B((P(white)>0)&black&long&(P(long)>0)&within(c,P(c))))) | 1 |
| candles.counterattack.5__history250 | pool_pct(own_rank250(B((P(black)>0)&white&long&(P(long)>0)&within(c,P(c)))-B((P(white)>0)&black&long&(P(long)>0)&within(c,P(c))))) | 1 |
| candles.hikkake.10__delta5 | pool_pct(pool_pct(B((P(h)<P(h,2))&(P(l)>P(l,2))&(h>P(h))&(l>P(l)))-B((P(h)<P(h,2))&(P(l)>P(l,2))&(h<P(h))&(l<P(l))))-pool_pct[-5]) | 3 |
| candles.ladderbottom.10__history250 | pool_pct(own_rank250(B((P(black,4)>0)&(P(black,3)>0)&(P(black,2)>0)&(P(c,3)<P(c,4))&(P(c,2)<P(c,3))&(P(upper)>P(body))&white&(c>P(h))))) | 3 |
| candles.tristar.10__history250 | pool_pct(own_rank250(B(doji&(P(doji)>0)&(P(doji,2)>0)&(P(h)<P(l,2))&(l>P(h)))-B(doji&(P(doji)>0)&(P(doji,2)>0)&(P(l)>P(h,2))&(h<P(l))))) | 3 |
| candles.kickingbylength.5 | pool_pct((B(white&maru&(P(black)>0)&(P(maru)>0)&(l>P(h)))-B(black&maru&(P(white)>0)&(P(maru)>0)&(h<P(l))))*np.where(body>P(body),1.,-1.)) | 1 |
| candles.concealbabyswall.10__history250 | pool_pct(own_rank250(B((P(black,3)>0)&(P(black,2)>0)&(P(maru,3)>0)&(P(maru,2)>0)&(P(black)>0)&(P(upper)>.2*rng)&black&(h>P(h))&(l<P(l))))) | 2 |
| candles.concealbabyswall.5__history250 | pool_pct(own_rank250(B((P(black,3)>0)&(P(black,2)>0)&(P(maru,3)>0)&(P(maru,2)>0)&(P(black)>0)&(P(upper)>.2*rng)&black&(h>P(h))&(l<P(l))))) | 1 |
| candles.abandonedbaby.10__history250 | pool_pct(own_rank250(B((P(black,2)>0)&(P(doji)>0)&white&(P(h)<P(l,2))&(l>P(h)))-B((P(white,2)>0)&(P(doji)>0)&black&(P(l)>P(h,2))&(h<P(l))))) | 3 |
| candles.counterattack.10__delta5 | pool_pct(pool_pct(B((P(black)>0)&white&long&(P(long)>0)&within(c,P(c)))-B((P(white)>0)&black&long&(P(long)>0)&within(c,P(c))))-pool_pct[-5]) | 1 |
| candles.counterattack.20__delta5 | pool_pct(pool_pct(B((P(black)>0)&white&long&(P(long)>0)&within(c,P(c)))-B((P(white)>0)&black&long&(P(long)>0)&within(c,P(c))))-pool_pct[-5]) | 1 |
| candles.counterattack.5__delta5 | pool_pct(pool_pct(B((P(black)>0)&white&long&(P(long)>0)&within(c,P(c)))-B((P(white)>0)&black&long&(P(long)>0)&within(c,P(c))))-pool_pct[-5]) | 1 |
| candles.hikkakemod.10__history250 | pool_pct(own_rank250(B((P(h,2)<P(h,3))&(P(l,2)>P(l,3))&(P(h)<P(h,2))&(c>P(h,2)))-B((P(h,2)<P(h,3))&(P(l,2)>P(l,3))&(P(l)>P(l,2))&(c<P(l,2))))) | 3 |
| candles.ladderbottom.10__delta5 | pool_pct(pool_pct(B((P(black,4)>0)&(P(black,3)>0)&(P(black,2)>0)&(P(c,3)<P(c,4))&(P(c,2)<P(c,3))&(P(upper)>P(body))&white&(c>P(h))))-pool_pct[-5]) | 3 |
| candles.tristar.10__delta5 | pool_pct(pool_pct(B(doji&(P(doji)>0)&(P(doji,2)>0)&(P(h)<P(l,2))&(l>P(h)))-B(doji&(P(doji)>0)&(P(doji,2)>0)&(P(l)>P(h,2))&(h<P(l))))-pool_pct[-5]) | 1 |
| candles.tristar.20__delta5 | pool_pct(pool_pct(B(doji&(P(doji)>0)&(P(doji,2)>0)&(P(h)<P(l,2))&(l>P(h)))-B(doji&(P(doji)>0)&(P(doji,2)>0)&(P(l)>P(h,2))&(h<P(l))))-pool_pct[-5]) | 1 |
| candles.tristar.5__delta5 | pool_pct(pool_pct(B(doji&(P(doji)>0)&(P(doji,2)>0)&(P(h)<P(l,2))&(l>P(h)))-B(doji&(P(doji)>0)&(P(doji,2)>0)&(P(l)>P(h,2))&(h<P(l))))-pool_pct[-5]) | 1 |
| candles.gapsidesidewhite.10 | pool_pct(B(white&(P(white)>0)&within(o,P(o))&within(body,P(body))&(l>P(h,2)))-B(white&(P(white)>0)&within(o,P(o))&within(body,P(body))&(h<P(l,2)))) | 5 |
| candles.concealbabyswall.10__delta5 | pool_pct(pool_pct(B((P(black,3)>0)&(P(black,2)>0)&(P(maru,3)>0)&(P(maru,2)>0)&(P(black)>0)&(P(upper)>.2*rng)&black&(h>P(h))&(l<P(l))))-pool_pct[-5]) | 1 |
| candles.concealbabyswall.20__delta5 | pool_pct(pool_pct(B((P(black,3)>0)&(P(black,2)>0)&(P(maru,3)>0)&(P(maru,2)>0)&(P(black)>0)&(P(upper)>.2*rng)&black&(h>P(h))&(l<P(l))))-pool_pct[-5]) | 1 |
| candles.concealbabyswall.5__delta5 | pool_pct(pool_pct(B((P(black,3)>0)&(P(black,2)>0)&(P(maru,3)>0)&(P(maru,2)>0)&(P(black)>0)&(P(upper)>.2*rng)&black&(h>P(h))&(l<P(l))))-pool_pct[-5]) | 1 |
| candles.abandonedbaby.10__delta5 | pool_pct(pool_pct(B((P(black,2)>0)&(P(doji)>0)&white&(P(h)<P(l,2))&(l>P(h)))-B((P(white,2)>0)&(P(doji)>0)&black&(P(l)>P(h,2))&(h<P(l))))-pool_pct[-5]) | 3 |
| candles.kickingbylength.10__history250 | pool_pct(own_rank250((B(white&maru&(P(black)>0)&(P(maru)>0)&(l>P(h)))-B(black&maru&(P(white)>0)&(P(maru)>0)&(h<P(l))))*np.where(body>P(body),1.,-1.))) | 1 |
| candles.kickingbylength.20__history250 | pool_pct(own_rank250((B(white&maru&(P(black)>0)&(P(maru)>0)&(l>P(h)))-B(black&maru&(P(white)>0)&(P(maru)>0)&(h<P(l))))*np.where(body>P(body),1.,-1.))) | 1 |
| candles.kickingbylength.5__history250 | pool_pct(own_rank250((B(white&maru&(P(black)>0)&(P(maru)>0)&(l>P(h)))-B(black&maru&(P(white)>0)&(P(maru)>0)&(h<P(l))))*np.where(body>P(body),1.,-1.))) | 1 |
| candles.xsidegap3methods.10 | pool_pct(B((P(white,2)>0)&(P(white)>0)&(P(l)>P(h,2))&black&(o>P(o))&(c<P(c,2)))-B((P(black,2)>0)&(P(black)>0)&(P(h)<P(l,2))&white&(o<P(o))&(c>P(c,2)))) | 3 |
| candles.hikkakemod.10__delta5 | pool_pct(pool_pct(B((P(h,2)<P(h,3))&(P(l,2)>P(l,3))&(P(h)<P(h,2))&(c>P(h,2)))-B((P(h,2)<P(h,3))&(P(l,2)>P(l,3))&(P(l)>P(l,2))&(c<P(l,2))))-pool_pct[-5]) | 3 |
| candles.3outside.10 | pool_pct(B((P(black,2)>0)&(P(white)>0)&white&(P(o)<P(c,2))&(P(c)>P(o,2))&(c>P(c)))-B((P(white,2)>0)&(P(black)>0)&black&(P(o)>P(c,2))&(P(c)<P(o,2))&(c<P(c)))) | 3 |
| candles.gapsidesidewhite.10__history250 | pool_pct(own_rank250(B(white&(P(white)>0)&within(o,P(o))&within(body,P(body))&(l>P(h,2)))-B(white&(P(white)>0)&within(o,P(o))&within(body,P(body))&(h<P(l,2))))) | 3 |
| candles.kickingbylength.5__delta5 | pool_pct(pool_pct((B(white&maru&(P(black)>0)&(P(maru)>0)&(l>P(h)))-B(black&maru&(P(white)>0)&(P(maru)>0)&(h<P(l))))*np.where(body>P(body),1.,-1.))-pool_pct[-5]) | 1 |
| candles.3inside.10 | pool_pct(B((P(black,2)>0)&(P(white)>0)&white&(P(o)>P(c,2))&(P(c)<P(o,2))&(c>P(o,2)))-B((P(white,2)>0)&(P(black)>0)&black&(P(o)<P(c,2))&(P(c)>P(o,2))&(c<P(o,2)))) | 3 |
| candles.breakaway.10 | pool_pct(B((P(black,4)>0)&(P(o,3)<P(c,4))&(P(c)<P(c,3))&white&(c>P(o,3))&(c<P(c,4)))-B((P(white,4)>0)&(P(o,3)>P(c,4))&(P(c)>P(c,3))&black&(c<P(o,3))&(c>P(c,4)))) | 3 |
| candles.xsidegap3methods.10__history250 | pool_pct(own_rank250(B((P(white,2)>0)&(P(white)>0)&(P(l)>P(h,2))&black&(o>P(o))&(c<P(c,2)))-B((P(black,2)>0)&(P(black)>0)&(P(h)<P(l,2))&white&(o<P(o))&(c>P(c,2))))) | 3 |
| candles.3outside.10__history250 | pool_pct(own_rank250(B((P(black,2)>0)&(P(white)>0)&white&(P(o)<P(c,2))&(P(c)>P(o,2))&(c>P(c)))-B((P(white,2)>0)&(P(black)>0)&black&(P(o)>P(c,2))&(P(c)<P(o,2))&(c<P(c))))) | 3 |
| candles.gapsidesidewhite.5__delta5 | pool_pct(pool_pct(B(white&(P(white)>0)&within(o,P(o))&within(body,P(body))&(l>P(h,2)))-B(white&(P(white)>0)&within(o,P(o))&within(body,P(body))&(h<P(l,2))))-pool_pct[-5]) | 1 |
| candles.3inside.10__history250 | pool_pct(own_rank250(B((P(black,2)>0)&(P(white)>0)&white&(P(o)>P(c,2))&(P(c)<P(o,2))&(c>P(o,2)))-B((P(white,2)>0)&(P(black)>0)&black&(P(o)<P(c,2))&(P(c)>P(o,2))&(c<P(o,2))))) | 3 |
| candles.breakaway.10__history250 | pool_pct(own_rank250(B((P(black,4)>0)&(P(o,3)<P(c,4))&(P(c)<P(c,3))&white&(c>P(o,3))&(c<P(c,4)))-B((P(white,4)>0)&(P(o,3)>P(c,4))&(P(c)>P(c,3))&black&(c<P(o,3))&(c>P(c,4))))) | 3 |
| candles.xsidegap3methods.10__delta5 | pool_pct(pool_pct(B((P(white,2)>0)&(P(white)>0)&(P(l)>P(h,2))&black&(o>P(o))&(c<P(c,2)))-B((P(black,2)>0)&(P(black)>0)&(P(h)<P(l,2))&white&(o<P(o))&(c>P(c,2))))-pool_pct[-5]) | 3 |
| candles.3outside.10__delta5 | pool_pct(pool_pct(B((P(black,2)>0)&(P(white)>0)&white&(P(o)<P(c,2))&(P(c)>P(o,2))&(c>P(c)))-B((P(white,2)>0)&(P(black)>0)&black&(P(o)>P(c,2))&(P(c)<P(o,2))&(c<P(c))))-pool_pct[-5]) | 3 |
| candles.3inside.10__delta5 | pool_pct(pool_pct(B((P(black,2)>0)&(P(white)>0)&white&(P(o)>P(c,2))&(P(c)<P(o,2))&(c>P(o,2)))-B((P(white,2)>0)&(P(black)>0)&black&(P(o)<P(c,2))&(P(c)>P(o,2))&(c<P(o,2))))-pool_pct[-5]) | 3 |
| candles.breakaway.10__delta5 | pool_pct(pool_pct(B((P(black,4)>0)&(P(o,3)<P(c,4))&(P(c)<P(c,3))&white&(c>P(o,3))&(c<P(c,4)))-B((P(white,4)>0)&(P(o,3)>P(c,4))&(P(c)>P(c,3))&black&(c<P(o,3))&(c>P(c,4))))-pool_pct[-5]) | 3 |
| candles.tasukigap.10 | pool_pct(B((P(white,2)>0)&(P(white)>0)&(P(l)>P(h,2))&black&(o<P(c))&(o>P(o))&(c<P(o))&(c>P(h,2)))-B((P(black,2)>0)&(P(black)>0)&(P(h)<P(l,2))&white&(o>P(c))&(o<P(o))&(c>P(o))&(c<P(l,2)))) | 3 |
| candles.tasukigap.10__history250 | pool_pct(own_rank250(B((P(white,2)>0)&(P(white)>0)&(P(l)>P(h,2))&black&(o<P(c))&(o>P(o))&(c<P(o))&(c>P(h,2)))-B((P(black,2)>0)&(P(black)>0)&(P(h)<P(l,2))&white&(o>P(c))&(o<P(o))&(c>P(o))&(c<P(l,2))))) | 3 |
| candles.tasukigap.10__delta5 | pool_pct(pool_pct(B((P(white,2)>0)&(P(white)>0)&(P(l)>P(h,2))&black&(o<P(c))&(o>P(o))&(c<P(o))&(c>P(h,2)))-B((P(black,2)>0)&(P(black)>0)&(P(h)<P(l,2))&white&(o>P(c))&(o<P(o))&(c>P(o))&(c<P(l,2))))-pool_pct[-5]) | 3 |
| candles.3linestrike.10 | pool_pct(B(white&(P(black)>0)&(P(black,2)>0)&(P(black,3)>0)&(P(c)<P(c,2))&(P(c,2)<P(c,3))&(o<P(c))&(c>P(o,3)))-B(black&(P(white)>0)&(P(white,2)>0)&(P(white,3)>0)&(P(c)>P(c,2))&(P(c,2)>P(c,3))&(o>P(c))&(c<P(o,3)))) | 3 |
| candles.risefall3methods.10 | pool_pct(B((P(white,4)>0)&(P(black,3)>0)&(P(black,2)>0)&(P(black)>0)&(P(h,2)<P(h,4))&(P(l)>P(l,4))&white&(c>P(c,4)))-B((P(black,4)>0)&(P(white,3)>0)&(P(white,2)>0)&(P(white)>0)&(P(l,2)>P(l,4))&(P(h)<P(h,4))&black&(c<P(c,4)))) | 3 |
| candles.3linestrike.10__history250 | pool_pct(own_rank250(B(white&(P(black)>0)&(P(black,2)>0)&(P(black,3)>0)&(P(c)<P(c,2))&(P(c,2)<P(c,3))&(o<P(c))&(c>P(o,3)))-B(black&(P(white)>0)&(P(white,2)>0)&(P(white,3)>0)&(P(c)>P(c,2))&(P(c,2)>P(c,3))&(o>P(c))&(c<P(o,3))))) | 3 |
| candles.3linestrike.10__delta5 | pool_pct(pool_pct(B(white&(P(black)>0)&(P(black,2)>0)&(P(black,3)>0)&(P(c)<P(c,2))&(P(c,2)<P(c,3))&(o<P(c))&(c>P(o,3)))-B(black&(P(white)>0)&(P(white,2)>0)&(P(white,3)>0)&(P(c)>P(c,2))&(P(c,2)>P(c,3))&(o>P(c))&(c<P(o,3))))-pool_pct[-5]) | 3 |
| candles.risefall3methods.10__history250 | pool_pct(own_rank250(B((P(white,4)>0)&(P(black,3)>0)&(P(black,2)>0)&(P(black)>0)&(P(h,2)<P(h,4))&(P(l)>P(l,4))&white&(c>P(c,4)))-B((P(black,4)>0)&(P(white,3)>0)&(P(white,2)>0)&(P(white)>0)&(P(l,2)>P(l,4))&(P(h)<P(h,4))&black&(c<P(c,4))))) | 3 |
| candles.risefall3methods.10__delta5 | pool_pct(pool_pct(B((P(white,4)>0)&(P(black,3)>0)&(P(black,2)>0)&(P(black)>0)&(P(h,2)<P(h,4))&(P(l)>P(l,4))&white&(c>P(c,4)))-B((P(black,4)>0)&(P(white,3)>0)&(P(white,2)>0)&(P(white)>0)&(P(l,2)>P(l,4))&(P(h)<P(h,4))&black&(c<P(c,4))))-pool_pct[-5]) | 3 |
