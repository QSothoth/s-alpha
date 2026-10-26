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
