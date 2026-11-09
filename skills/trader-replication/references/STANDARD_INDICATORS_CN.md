# 统一选票拟合：标准指标库与拟合设置（草案 v1.1）

日期：2026-11-04，2026-11-05 改为 v1.1。用途：所有交易员复刻的“选票偏好拟合”共用同一套指标和同一套拟合设置；每个人只换自己的台账、过滤条件和持仓宽度。冻结后改动发新版本，旧结果注明所用版本，不混比。

v1.1 改动（用户 11-05 纠正：新库的目的是扩展旧库的范围，再去掉重复度太高的）：v1 是按流派重列的，漏了旧库的“收盘离当日低点”“EMA 9−21 间距”，不是旧库的扩展；拟合权重漏了 0.5 档；均线排列写成了 0/1。v1 的 IE38 结果照记，但不算对“扩展库”的检验。

## 一、原则

- **以旧库为底扩展**：IE32 用的 45 项（`martin_profile_ie29.py` 的旧指标，去掉依赖我们强势池的 5 项）全部纳入、定义和数值不变，再加各流派新指标。旧库每一项要么原样保留，要么在新库里有 |ρ| ≥ 0.9 的替身（测试强制）。
- **常见指标都覆盖，不只一个流派**：趋势、动量震荡、均值回归、波动通道、成交量资金流、锚定 VWAP 与成交量分布、价格结构、K 线形态、缠论、SMC、筹码、体系模板、多周期、题材、期权情绪、事件。
- **覆盖 ≠ 每个都单独放**：测的是同一件事的指标只留一个代表，其余记为“别名”。拟合按分位切档，同类指标切出来的档几乎一样，多放只会增加碰巧拟合上的机会、让消融失灵（去掉一个，它的同类顶上）。
- **参数用通用默认值**：TradingView 默认参数为主（如 RSI 14、MACD 12/26/9、布林 20/2）；不做参数网格。
- **单位是交易员屏幕上看得到的原值，且能跨股票比较**：RSI 就是 RSI 值；离均线用 % 或 ADR 倍数；MACD、OBV、A/D 这类原始值随股价和股本变化的，一律换成按价格归一或“离自身近期高点”的写法。
- **只用已有数据**：日 K（OHLCV、成交额）、本市场基准指数、4 小时线衍生量、美股期权（IV、HV、成交、持仓）、财报日期。没有基本面、盘前、资金流明细。
- **只看当晚收盘前已知的**；**不放任何“他买过”的信息**（代码、日期、上市天数这类日期代理）。

## 二、精简规则（冻结前执行一次，结果写进本文件）

1. **按定义合并**：同一公式的线性或单调变换只留一个（见下表“别名”列），例如 CMO = 2×RSI − 100、威廉 %R = 随机 %K − 100、布林 %B 与 20 日 z 分数、IBS 与收盘位置、PPO 与按价格归一的 MACD。
2. **按数据合并**：实现后在全市场（不是某个交易员的池）拟合段年份的全部股票 × 夜晚上算秩相关，|ρ| ≥ 0.9 的成对只留一个：旧库已有的优先；都是新增的，按“TradingView 内置指标优先 → 表内先列的优先”保留。只用指标值，不用任何人的交易。
3. **去掉太稀的 0/1 指标**：全市场出现率 < 1% 的形态类指标不放（分档打分没有样本）；旧库的 0/1 项不受这条影响。
4. **包含检查**：旧库 45 项逐项核对“原样在新库”或“新库有 |ρ| ≥ 0.9 的替身”，任何一项不满足即不能冻结。

现有 48 项实测（Martin 池，秩相关）：当日成交额 / 20 日 与相对成交量 0.98、21 日涨幅与 21 日跑赢 QQQ 0.97、5 日涨幅与 5 日跑赢 QQQ 0.96、离 EMA50 与 EMA9−21 间距 0.91，均达到合并线。

## 三、指标清单（按定义合并后约 125 项，按数据合并后预计约 100–110 项）

“现有”指已在 `studies/trader_replication/ie_factor_library.py` 或 `martin_profile_ie29.py` 实现，只需按默认参数取一组；“需补”要新写。

| 流派 | 保留的代表（默认参数） | 项数 | 别名（不单独放） | 现有 / 需补 |
|---|---|---|---|---|
| 趋势 / 均线 | 离 EMA 9 / 21 / 50（ADR 倍数）；离 SMA 150 / 200（%）；EMA21、SMA50、SMA200 的 10 日斜率；EMA 9>21>50 排列；近 20 天站上 EMA21 天数；Supertrend (10, 3) 方向距离、翻转天数；一目均衡云位置；ADX 14、DI 差；震荡指数 14 | 16 | SMA 10/20/50、EMA 200、KAMA、一目转换 / 基准线、Elder 多空力量、线性回归斜率 / R²、30 / 40 周线、抛物线 SAR（按数据定） | 现有，均线斜率需补 |
| 动量 / 震荡 | RSI 14；随机 %K (14, 1, 3)；随机 RSI (14, 14, 3, 3)；MACD 柱（按价格归一）及其 5 日变化；CCI 20 | 6 | CMO、威廉 %R、PPO、ROC、动量、TRIX、KST、终极振荡、Elder 脉冲 | 现有 |
| 涨幅与相对强弱 | 1 / 5 / 21 / 63 日涨幅；21 日相对基准超额（美股 QQQ、港股恒指、A 股沪深 300）；IBD 式加权 RS 全市场百分位；RS 线离 63 日高点；近 20 天跑赢基准天数；近 20 天上涨天数；β 60 | 10 | 5 / 63 日超额、126 / 252 日涨幅（并入 IBD RS） | 现有 |
| 均值回归 | RSI 2；收盘位置（IBS）；连涨 / 连跌天数；离 SMA 5（ATR 倍数）；布林 %B (20, 2) | 5 | 20 日 z 分数、肯特纳位置 | 现有 |
| 波动与通道 | ADR 20；当天振幅 / ADR；近 3 天振幅 / ADR；布林带宽一年分位；TTM 挤压持续天数；唐奇安 20 位置；55 日突破；内包日；NR7；外包日 | 10 | ATR 14 %、HV 20、Ulcer、离 20 日高 / 低点、SMC 溢价 / 折价区、孕线 | 现有 |
| 成交量 / 资金流 | 20 日成交额；相对成交量 1 日、3 日；OBV 离 20 日高点；CMF 20；MFI 14；50 日上涨日 / 下跌日成交量比；PVI 离 255 日均 | 8 | 当日成交额 / 20 日、PVT、A/D、Chaikin 振荡、强力指数、EOM、NVI、Amihud | 现有，上涨/下跌量比需补 |
| 锚定 VWAP / 成交量分布 | 收盘离 AVWAP（ADR 倍数），锚点：52 周高点、52 周低点、50 日高点、50 日低点、最近大跳空日、最近财报日；近 100 日成交量分布离 POC、价值区位置 | 8 | 底部高点 / 低点锚（即 50 日锚） | AVWAP 现有，成交量分布需补 |
| 价格结构 | 离 52 周高点、离 50 日高点、离 52 周低点；创 52 周 / 50 日新高；越过前一日高点；当天跳空（ADR）；离上次 ≥10% 跳空天数；上方未补缺口距离；摆动低点抬高计数；底部长度、深度；达瓦斯箱体突破；VCP 收缩次数；离上次 20 日高点天数；回调深度（ADR）；底部里第几次回到 EMA21 | 17 | Aroon、达瓦斯箱体位置（≈ 唐奇安位置）、HH 计数 | 部分现有；未补缺口、摆动计数、底部长度 / 深度、第几次回调需补 |
| K 线形态 | 多头吞没；锤子 / 长下影 pin bar；倒锤 / 流星（长上影）；十字星；光头光脚大阳线；晨星 | 6 | 三白兵、三只乌鸦、刺透、乌云盖顶、暮星（出现率 ≥ 1% 才补回） | 现有，pin bar 需补 |
| 缠论 | 日底分型；日二买；日三买；周线买点；离最近中枢上沿 | 5 | 顶分型、周分型 | 现有 |
| SMC | BOS；CHoCH；离多头 FVG；离订单块；流动性扫荡（扫前低后收回） | 5 | 溢价 / 折价区（并入唐奇安位置） | 现有 |
| 筹码分布 | 获利盘比例；90% 筹码集中度；上方套牢盘 | 3 | 平均成本距离、离密集支撑 | 现有 |
| 体系模板 | Minervini 趋势模板满足条数（含 SMA 50>150>200）；Weinstein 阶段；在上周经典轴心点区间的位置 | 3 | 30 周线距离（= 离 SMA150）、R1 / S1 单独距离 | 轴心点需补 |
| 多周期 | 周 RSI 14、周 MACD 柱、内包周、周 pin bar、周收盘位置；4 小时动量、排列、收敛、强势历史 | 9 | 10 / 30 周线（= SMA 50 / 150） | 4 小时现有，周线需补 |
| 题材 / 板块 | 按全市场 60 日收益相关性 ≥ 0.5 定同伴：同伴只数、近 5 天涨 10% 以上的同伴数、同伴 5 日 / 1 日平均涨幅、在同伴里的强度排名 | 5 | — | 现有 |
| 期权 / 情绪（仅美股） | IV；IV 百分位 252；IV − HV；期权相对成交量 20；Put/Call 成交比；Put/Call 持仓比；持仓 5 日变化 | 7 | IV rank、Call 成交占比 | 现有 |
| 事件 | 离上次财报天数；财报跳空幅度；近 20 日大涨日（potent）次数 | 3 | — | 现有 |
| 价格 | 股价 | 1 | — | 现有 |

**单列，不算通用指标**：“近 20 天进入他自己扫描的天数”“同题材在他扫描里的只数”。每人用自己的过滤条件算；用了就必须同时报告去掉它的对照。

## 四、统一拟合设置

| 环节 | 设置 |
|---|---|
| 打分 | 每项按候选池（拟合段全部夜晚合在一起）分位切档，档边界只用拟合段的数据定；档分 = log((他的占比 + 平滑) / (池占比 + 平滑))，平滑 2；总分 = 各项档分 × 权重之和，当晚按总分排序 |
| 分档方式 | 两种，每轮作为候选按内部交叉验证挑：①拟合段边界（按指标原值切，边界只用拟合段的行定）；②当晚池内分位（先把每项换成当晚候选池里的分位 0–1，再切档；只用当晚收盘已知的信息，不受整体行情偏移影响）。IE38 复核发现：以前（IE29–IE37）档边界用了全部年份含留出段的指标值，改成①后 IE32 从 18/28、10/23 降到 14/28、8/23 |
| 可调 | 选哪几项（最多 7 项）、每项分档（3 / 5 / 10）、权重（0.5 / 1 / 1.5 / 2 / 3） |
| 搜索 | 逐项加入 → 逐项替换 → 逐项去掉，按拟合段命中数，同分看他的票的平均名次 |
| 时间切分 | 最近一年留出，不参与任何拟合，只测一次；之前按半年轮流留出做内部交叉验证 |
| 挑版本 | 每轮 ≤ 5 个版本，只按内部交叉验证挑；留出段只算挑中的那个，其他版本的留出数照记、不参与挑选 |
| 必报 | 拟合段命中、内部交叉验证、留出命中；同预算随机 30 次、打乱标签对照；逐项去掉的消融，以及按流派成组去掉的消融；画像（每项他偏好的区间） |

现有代码（IE29–IE37）的档边界用了全部行（含留出段的指标值，不含标签），v1 实现时改为只用拟合段。

## 五、每个人自己的设置（不在统一集里）

- 过滤条件：他自己说的选股范围（如 Martin 的 ADR、成交额、强势历史）。
- 宽度：每晚新挑几只、持有几晚、冷却几晚，按他自己说的同时持仓数定。
- 目标：用他哪些入场来学（如 60 日内最高涨 30% 以上的大赢家）、命中窗口（入场前几晚到后几晚）。
- 留出段：按他台账覆盖的年份定“最近一年”。

## 六、已知风险

- 候选从约 50 项扩到约 100 项，搜索容量仍变大。IE35 已经显示拟合越紧留出越差，所以项数上限、分档选项和“只按内部交叉验证挑版本”都不放宽。
- 合并线 0.9 以下的同类指标（如离 EMA21 与离 EMA50 约 0.88）仍会同时在库里，消融时要按流派成组去掉再看。

## 七、v1 冻结清单与合并记录

127 项代表全部实现；在 2277 只缓存股票、2024-01-02 至 2025-12-31 的全市场有效收盘股票 × 夜晚中，固定种子 2026110438 不放回抽取 300,000 行，只使用指标值。最终保留 **113 项**。

相关性用两项都有值的抽样行，计算含并列值平均秩的精确 Spearman；按上表流派顺序及流派内列出顺序，保留先列者。0/1 出现率在全部市场拟合年有效指标行上计算。缺少期权、财报或 4 小时输入的行保留 NaN。

| 去掉的项 | 保留的项 / 原因 | ρ / 出现率 |
|---|---|---|
| `ema21_distance_adr` | `ema9_distance_adr` | 0.903546 |
| `sma200_distance_pct` | `sma150_distance_pct` | 0.965448 |
| `rsi14` | `ema50_distance_adr` | 0.945084 |
| `stochastic_k` | `ema9_distance_adr` | 0.915757 |
| `excess21_pct` | `return21_pct` | 0.901232 |
| `sma5_distance_atr` | `rsi2` | 0.941486 |
| `bollinger_percent_b` | `ema9_distance_adr` | 0.918820 |
| `donchian20_position` | `cci20` | 0.923589 |
| `volume_profile_value_position` | `volume_profile_poc_distance_adr` | 0.918702 |
| `new_high50` | `breakout55` | 0.971330 |
| `base_depth_pct` | `high252_distance_pct` | -0.915135 |
| `chan_buy3` | 全市场出现率低于 1% | 0.8435% |
| `chip_overhang_share` | `chip_profit_share` | -0.999995 |
| `weekly_rsi14` | `sma150_distance_pct` | 0.932019 |

完整保留清单（代码常量 `standard_indicators.V1_NAMES`）：

`ema9_distance_adr`、`ema50_distance_adr`、`sma150_distance_pct`、`ema21_slope10_pct`、`sma50_slope10_pct`、`sma200_slope10_pct`、`ema_stack`、`above_ema21_days20`、`supertrend_distance`、`supertrend_flip_days`、`ichimoku_cloud_position`、`adx14`、`di_spread14`、`choppiness14`、`stochastic_rsi`、`macd_hist_pct`、`macd_hist_change5`、`cci20`、`return1_pct`、`return5_pct`、`return21_pct`、`return63_pct`、`ibd_rs_percentile`、`rs_line_high63_pct`、`outperform_days20`、`up_days20`、`beta60`、`rsi2`、`close_position`、`signed_streak`、`adr20_pct`、`range_adr`、`range3_adr`、`bollinger_width_percentile252`、`ttm_squeeze_days`、`breakout55`、`inside_day`、`nr7`、`outside_day`、`dollar_volume20`、`relative_volume`、`relative_volume3`、`obv_high20_distance`、`cmf20`、`mfi14`、`up_down_volume50`、`pvi_sma255_distance_pct`、`avwap_high252_distance_adr`、`avwap_low252_distance_adr`、`avwap_high50_distance_adr`、`avwap_low50_distance_adr`、`avwap_gap_distance_adr`、`avwap_earnings_distance_adr`、`volume_profile_poc_distance_adr`、`high252_distance_pct`、`high50_distance_pct`、`low252_distance_pct`、`new_high252`、`over_previous_high_adr`、`gap_adr`、`large_gap_days`、`unfilled_gap_above_distance_adr`、`rising_swing_lows`、`base_length`、`darvas_breakout`、`vcp_contractions`、`high20_days`、`pullback_depth_adr`、`ema21_retest_count`、`bullish_engulfing`、`pin_bar`、`upper_pin_bar`、`doji`、`bullish_marubozu`、`morning_star`、`chan_bottom_fractal`、`chan_buy2`、`chan_weekly_buy`、`chan_pivot_distance_adr`、`smc_bos`、`smc_choch`、`smc_fvg_distance_adr`、`smc_order_block_distance_adr`、`smc_low_sweep`、`chip_profit_share`、`chip_concentration90`、`minervini_score`、`weinstein_stage`、`weekly_pivot_position`、`weekly_macd_hist_pct`、`inside_week`、`weekly_pin_bar`、`weekly_close_position`、`h4_momentum`、`h4_stack`、`h4_coil`、`h4_history`、`theme_peers`、`theme_moving_peers`、`theme_peer_return5_pct`、`theme_peer_return1_pct`、`theme_strength_percentile`、`iv`、`iv_percentile252`、`iv_minus_hv`、`option_relative_volume20`、`put_call_volume_ratio`、`put_call_oi_ratio`、`option_oi_change5_pct`、`earnings_days`、`earnings_gap_pct`、`potent_days20`、`price`。

完整的 |ρ| ≥ 0.8 成对及出现率见 `studies/trader_replication/reports/gap_review/standard_indicators_v1_dedup.json`。CMO 与 RSI 的别名恒等使用相同 Wilder 平滑；滚动求和版 CMO 不满足恒等，本版不把两者数值混称。筹码采用日线成交量换手代理，并非真实逐笔持仓。

## 八、v1.1 冻结清单与合并记录

139 项代表全部实现；在 2277 只缓存股票、2024-01-02 至 2025-12-31 的全市场有效收盘股票 × 夜晚中，固定种子 2026110438 不放回抽取 300,000 行，只使用指标值。最终保留 **117 项**。

秩相关与 v1 使用完全相同的 300,000 个全市场抽样行，按两项共同有效行计算精确 Spearman（并列值取平均秩）；不使用交易标签。旧库优先；新增项先保留 TradingView 内置指标，再按规格表内顺序。旧库的 0/1 项不受低于 1% 的剔除规则影响。未变的新项复用 v1 同行冻结值，旧库项及修复数值稳定性的新增项重新计算。

| 去掉的项 | 保留的项 / 原因 | ρ / 出现率 |
|---|---|---|
| `ext_ema21_adr` | `ext_ema9_adr` | 0.903564 |
| `rs21_vs_qqq_pct` | `perf21_pct` | 0.901232 |
| `ema9_21_gap_adr` | `ext_ema50_adr` | 0.931783 |
| `dollar_vol_today_vs20` | `rvol20` | 0.984882 |
| `rsi14` | `ext_ema50_adr` | 0.944866 |
| `stochastic_k` | `ext_ema9_adr` | 0.915688 |
| `bollinger_percent_b` | `ext_ema9_adr` | 0.918820 |
| `donchian20_position` | `cci20` | 0.923589 |
| `breakout55` | `new_high50` | 0.971330 |
| `volume_profile_value_position` | `volume_profile_poc_distance_adr` | 0.918700 |
| `sma150_distance_pct` | `weekly_rsi14` | 0.932019 |
| `sma200_distance_pct` | `weekly_rsi14` | 0.917788 |
| `outperform_days20` | `rs_pos_days20` | 1.000000 |
| `sma5_distance_atr` | `rsi2` | 0.941486 |
| `base_depth_pct` | `from_high252_pct` | -0.916601 |
| `chan_buy3` | 全市场出现率低于 1% | 0.8435% |
| `chip_overhang_share` | `chip_profit_share` | -0.999995 |
| `minervini_score` | `weekly_rsi14` | 0.901396 |
| `theme_peers` | `theme_peers_scope` | 0.999825 |
| `theme_moving_peers` | `theme_peers_moving` | 0.999400 |
| `theme_peer_return5_pct` | `theme_peer_ret5` | 0.998893 |
| `theme_peer_return1_pct` | `theme_peer_ret1` | 0.999256 |

复核修复：旧缓存 `price` 使用复权收盘 `c`，含未来拆合股信息；v1.1 起使用 t 日真实未复权收盘 `raw_c`，缺失记 NaN，不回退到 `c`。旧库一致性对 `price` 豁免，并另与缓存 `raw_c` 逐行核对，其余 44 项继续按原标准核对。EMA 恒值更新、NR7 等振幅、布林带宽分位并列、成交量分布等量并列与筹码分位点使用稳定处理，避免缩放引发浮点分支变化。

原冻结记录已另存 `standard_indicators_v1_1_dedup_pre_rawprice.json`，SHA256 `c1e27f473d300a3dd4205182c929a007c8f31a17a055d9e13ff777a84bda07bf`。按原抽样、保留顺序和 |ρ| ≥ 0.9 规则重新冻结；仅两个抽样列均逐位未变的相关对复用原值。

旧库 45 项全部被包含：同名直接保留 41 项（`price` 已作上述安全修正），靠 |ρ| ≥ 0.9 的保留项替代 4 项；同义新名已并入旧名。`ema_stack` 按旧库取 0–2；旧窗口的最少样本数、缺失比较、跳空锚点和封顶值保持不变。题材旧定义在调用者的当晚可见范围计算；本次去重范围为全市场，Martin 一致性核对使用原范围。

| 旧库合并项 | 保留的替身 | ρ |
|---|---|---|
| `ext_ema21_adr` | `ext_ema9_adr` | 0.903564 |
| `ema9_21_gap_adr` | `ext_ema50_adr` | 0.931783 |
| `rs21_vs_qqq_pct` | `perf21_pct` | 0.901232 |
| `dollar_vol_today_vs20` | `rvol20` | 0.984882 |

完整保留清单（代码常量 `standard_indicators.V1_1_NAMES`）：

`ext_ema9_adr`、`ext_ema50_adr`、`ema_stack`、`above_ema21_days20`、`perf1_pct`、`perf5_pct`、`perf21_pct`、`perf63_pct`、`rs_line_from_high63_pct`、`up_days20`、`close_pos`、`adr20_pct`、`range_today_adr`、`contract3_adr`、`inside_day`、`nr7`、`dollar_vol20_M`、`rvol20`、`rvol3_20`、`avwap_base_high_adr`、`avwap_base_low_adr`、`from_high252_pct`、`new_high252`、`new_high50`、`over_prior_high_adr`、`gap_today_adr`、`days_since_10pct_gap`、`iv_pct`、`option_rvol20`、`earn_days`、`price`、`lod_stop_pct`、`from_high20_pct`、`rs5_vs_qqq_pct`、`avwap_big_gap_adr`、`from_high50_adr`、`rs_pos_days20`、`theme_peers_scope`、`theme_peers_moving`、`theme_peer_ret5`、`theme_peer_ret1`、`supertrend_distance`、`supertrend_flip_days`、`ichimoku_cloud_position`、`adx14`、`di_spread14`、`stochastic_rsi`、`macd_hist_pct`、`macd_hist_change5`、`cci20`、`rsi2`、`bollinger_width_percentile252`、`obv_high20_distance`、`cmf20`、`mfi14`、`volume_profile_poc_distance_adr`、`weekly_pivot_position`、`weekly_rsi14`、`weekly_macd_hist_pct`、`ema21_slope10_pct`、`sma50_slope10_pct`、`sma200_slope10_pct`、`choppiness14`、`ibd_rs_percentile`、`beta60`、`signed_streak`、`ttm_squeeze_days`、`outside_day`、`up_down_volume50`、`pvi_sma255_distance_pct`、`avwap_high252_distance_adr`、`avwap_low252_distance_adr`、`avwap_gap_distance_adr`、`avwap_earnings_distance_adr`、`high50_distance_pct`、`low252_distance_pct`、`unfilled_gap_above_distance_adr`、`rising_swing_lows`、`base_length`、`darvas_breakout`、`vcp_contractions`、`high20_days`、`pullback_depth_adr`、`ema21_retest_count`、`bullish_engulfing`、`pin_bar`、`upper_pin_bar`、`doji`、`bullish_marubozu`、`morning_star`、`chan_bottom_fractal`、`chan_buy2`、`chan_weekly_buy`、`chan_pivot_distance_adr`、`smc_bos`、`smc_choch`、`smc_fvg_distance_adr`、`smc_order_block_distance_adr`、`smc_low_sweep`、`chip_profit_share`、`chip_concentration90`、`weinstein_stage`、`inside_week`、`weekly_pin_bar`、`weekly_close_position`、`h4_momentum`、`h4_stack`、`h4_coil`、`h4_history`、`theme_strength_percentile`、`iv_percentile252`、`iv_minus_hv`、`put_call_volume_ratio`、`put_call_oi_ratio`、`option_oi_change5_pct`、`earnings_gap_pct`、`potent_days20`。

完整的 |ρ| ≥ 0.8 成对及出现率见 `studies/trader_replication/reports/gap_review/standard_indicators_v1_1_dedup.json`。CMO 与 RSI 的别名恒等使用相同 Wilder 平滑；滚动求和版 CMO 不满足恒等，本版不把两者数值混称。筹码采用日线成交量换手代理，并非真实逐笔持仓。
