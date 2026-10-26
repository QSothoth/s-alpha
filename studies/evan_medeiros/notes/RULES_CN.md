# Evan Medeiros（Trade Risk / Lamorak）规则摘录

来源：
- [E1] 本人网站文章《Mean Reversion Trading》（thetraderisk.com/mean-reversion-trading-tips-strategy，规则引自 Cesar Alvarez），2026-10-25 读取。
- [E2] 本人网站绩效页（thetraderisk.com/performance）：Lamorak 2021 +10.04%、2022 −6.29%、2023 +7.91%、2024 +20.45%；年均 328 笔，胜率 63.76%，平均盈利 2.29%，盈亏比 0.81，平均持有 4 个交易日，杠杆“有时到 150%”，最大三次回撤 −18.80% / −14.34% / −13.01%。
- [E3] 2025 年 8 月月报：Lamorak 8 月 +2.91%，年内 +5.03%；描述为“短期均值回归系统，追求不相关收益”。
- [E4] Talking with Traders S10E06（2025-03）：Merlin / Lamorak / Galahad 三套自动系统；节目页没有规则，未取得逐字稿。

| 环节 | 原话 / 数字 | 出处 | 实现 |
|---|---|---|---|
| 趋势 | “upsloping 200-day moving average and the stock being above it” | E1 | 收盘在 200 日线上方，且 200 日线高于 20 天前 |
| 极端 | “2-day RSI with a value under 5, and the stock is down 3+ days”；另一种：“down 10%+ over the last 3 days and the stock down 3+ days” | E1 | RSI2 < 5 且连跌 ≥ 3 天；备选 3 日跌 ≥ 10% |
| 只在第一天 | “only look to enter a stock on the day RSI2 crosses under 5” | E1 | 前一日 RSI2 ≥ 5 |
| 波动 | “100-day historical volatility over 40. The higher the better” | E1 | HV100 ≥ 40；同日按 HV100 从高到低排序 |
| 价格流动性 | 更喜欢“high volatility, low price, and low liquidity” | E1 | 研究者取值：价格 ≥ 5、20 日成交额 ≥ 500 万（名单本身 ≥ 200 万）；Lamorak 档案写大中盘，作为候选 |
| 入场 | “next open or waiting for a further sell-off intraday … limit order … normally between 2%-10% below the previous close” | E1 | 次日限价：前收 × (1 − k)，k 起点 3%；开盘已低于限价按开盘成交 |
| 离场 | “wait for a bounce before exiting” | E1 | 研究者解释：收盘高于前一日最高（备选：收在 5 日线上方、RSI2 > 70、第一根阳线） |
| 时间止损 | “gets us out of losing trades after 10 days” | E1 | 持有满 10 个交易日收盘离场 |
| 止损 | 止损“significant degradation”；可以用大止损“e.g., 20% maximum loss” | E1 | 入场价下方 20% 灾难止损 |
| 仓位 | “size all positions the same size”；“$50,000 portfolio with a maximum of 10 positions … $5,000 per position” | E1 | 每只 10% 净值，最多 15 只、总敞口 150%（E2 杠杆） |
| 空头 | “RSI2 to be above 99”；空头“use three”个指标 | E1 | RSI2 > 99 首日、连涨 ≥ 3 天、3 日涨 ≥ 10%；在下行 200 日线下方（研究者对称） |
| 市况 | “200-day moving average works well” | E1 | 股票池等权指数在 200 日线上方才开多、下方才开空 |
