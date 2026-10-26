# Emanuela Elias 规则摘录

来源：本人通讯 The Trader Reset（thetraderreset.com）2026 年 8–10 月各期：《Containing Losses》（09-20）、《Commit to Something》（10-04）、《Managing an Open Trade》（10-18）、《Almost Eight Years In!》（10-11）；USIC 官方：2025 年 +259.9%，2026 年截至 9 月 +190.3%；扩展研究报告中的风险复盘（单笔 AAPL +360% 是合约涨幅，不是账户收益）。通讯只讲框架，具体数字是研究者取值。

| 环节 | 原话 | 实现（研究者取值） |
|---|---|---|
| 名单 | “trade from a very small list of names”；“I trade a small list of stocks, use a handful of indicators, and trade simple setups” | 前一日 20 日成交额最大的 15 只（价格 ≥ 5） |
| 关键价位 | 指数与个股的支撑 / 阻力；小时线、日线 | 前 20 个交易日的最低 / 最高价 |
| 形态 | 等买盘出现（buyers show up），再回踩，用回踩处管理风险 | 跌破 20 日低点后 5 天内收回上方；收回后 10 天内回踩（低点进入价位上方 1% 以内或跌穿）并收在价位上方，收盘买入；做空对称 |
| 止损 | “cutting losses at our defined stops” | 回踩当天最低价下方（至少 1%）；候选：关键价位下方 |
| 管理 | 接近下一个关键价位时决定持有 / 止盈；“moving sideways or isn't making progress after a few sessions” | 收盘到达前 20 日高点（空头：低点）离场；最多 5 天 |
| 工具 | 买 Call / Put；“even if the stock recovers … my option may not recover to the same value” | 股票信号用共用引擎；`options` 用约 30 天的平值 Call / Put 重放同一批交易 |
| 仓位 | 未披露 | 每笔风险 2%，最多 6 只，每天最多 3 笔 |

## 第二部分：她本人周报里的做法（2026-10-26 通读 90 篇，2025-02-23 → 2026-10-25）

原文存本机 `data/new-styles-sources-20261025/emanuela/`（html、text、sitemap，未进 git、未发 Release）。出处按文章 slug（发布日期）。

| 环节 | 原话 | 出处 |
|---|---|---|
| 周期 | “Focusing on the daily chart, since that's where I base my trades.”；“Because I trade the daily chart swings, I'll sometimes give a trade some room intraday (or a few days)” | breakout-or-breakdown（2025-04-20）；spx-breakdown-or-breakout-dc0a（2025-07-13） |
| 入场细化 | 小时线找入场：“I'd look for an entry on the hourly chart in the $74-$74.5 area”；后来加 5 分钟线：“folding in the 5-minute chart to work toward a more precise entry” | spx-outlook-1962（2025-07-06）；spx-early-distribution-signs（2025-11-16） |
| 名单 | 熟悉的少量股票反复做，每月一只重点股（CVNA、HIMS、RDDT、PYPL）；每天早上扫一遍，看日线是否守住关键价位 / EMA、SRSI 是否重置，进短名单 | the-quiet-before-the-storm（2025-03-30）；spx-early-distribution-signs（2025-11-16） |
| 趋势前提 | “I become interested in trading a stock when it closes above its weekly 40SMA or 50SMA and starts to build above it.”；突破买点：“The stock has to already be in an uptrend, well above its daily 150/200 SMA or 30/40-week SMAs.”；日线 200 SMA“I treat as a filter when lining up weekly setups” | spx-outlook-1962（2025-07-06）；spx-pushes-higher（2025-09-14）；june-drift（2025-06-15） |
| 回调形态 | “For my pullback setup, I wait for the breakout to establish the new trend and then get in once the candles tighten against the moving averages.”；“I typically wait for the price to reclaim the daily 10 EMA to confirm the swing and get in.”；“contraction comes before expansion” | a-strong-single-day-rise（2025-08-24） |
| 底部突破 | “A base after a decline … buyers defending the 153–148 zone”；“Stop: Placed at the bottom of the base” | spx-pushes-higher（2025-09-14，PLTR） |
| 离场 | “close trades that are becoming extended (significant space between the price and the 10EMA) because that usually means the end of a leg of movement for my trading style”；“two exits max, first target and second target … No more extra residual portion”；“a break of the 20EMA with volume, would be the first sign to reassess” | spx-outlook-1962（2025-07-06）；i-made-22k…（2026-07-05） |
| 期权 | “with short-term options, you don't have much room to sit through two or three days of pullback”；“I had bought enough time for both trades” | spx-ends-in-indecision（2025-09-28）；emotional-residue（2026-04-26） |
| 做空 | “I don't trade much to the downside in a rising market, and I typically skip the first few pullbacks along the daily uptrend.” | follow-the-price（2026-06-14） |
| 风险 | “the risk had already exceeded my cap … I had to cut it” | spx-breakdown-or-breakout-dc0a（2025-07-13） |

带日期的交易见 `notes/trades.csv`（20 笔）。第一部分（2026-10-25 首轮）的“跌破 20 日低点后收回再回踩、最多 3 天”是研究者对“buyers show up”的解读，与她本人描述的日线波段方法不同。
