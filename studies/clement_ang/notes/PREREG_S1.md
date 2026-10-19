# S1 预登记：晚期失败底部（Gil Morales）按原话的端到端版本

2026-10-19 写于看任何 Clement 空头结果之前，跑完不改。口径与选择规则见 [TRADER_PROTOCOL_CN 第 5 节](../../../docs/TRADER_PROTOCOL_CN.md)；运行 `python -m studies.trader_replication.shorts round clement_ang S1`。

## 原话（RULES ⑧；本地字幕 zw96qkUn9_g）

- @00:57:46：“on the short side it's 100% Gil Morales … late stage failed bases … watching a stock violate that 20-day exponential moving average … a wedging type of price action on low volume into the moving average and I'm timing that intraday as it reverses”；2025 年利润 70–80% 来自多头。
- @01:21:40–01:24:00：个股大跌是“very aggressively short”的信号；Weinstein 第三阶段之后进第四阶段；“when the market turns negative, the former big stocks or former leading [names]”不用另外筛选。反向杠杆 ETF（SQQQ / SOXS）暂不考虑（数据里没有）。

## 翻译（`replicate.py` 的 `short_setups`）

- 前一天就确定（t−1 数据）：前领涨股（看板强度 ≥ 0.9 出现在过去 60 天里）、过去 10 天内收破过 20 EMA 且昨天仍在其下方、最近 3 天平均成交量低于 50 日均量（缩量反抽）。
- **fb20**：当天限价卖空在前一日的 20 EMA（反抽到均线），止损在上方 min(5%, 半个 ADR)（至少 1%），当天到止损按止损价出。
- **fb20c**：收盘确认版——当天最高价碰到前一日 20 EMA、收红且收在其下方（“日内转弱”的日线近似），收盘卖空，止损当日最高价（他说的“止损当日高点”）。
- 股票池：多头池下限（20 日成交额 ≥ 5000 万、价格 ≥ 5、ADR ≥ 3%），前一天确定。
- 离场：沿用他多头的管理翻过来（+2R 回补 1/3 并保本、余下收盘站上 20 EMA 回补），即引擎对空头同样适用的 R15 AA3 设置。每天最多 3 笔空（他“不顺时每天最多 3 笔”），先开多再开空；风险 0.5%，借券年化 3%。

## 候选

- **CA** fb20，指数前收在 20 EMA 下方（他多头开关 IDX20 翻过来：市况转负）。
- **CB** fb20c，同上。
- **CC** fb20，不看指数。
- **CD** fb20，指数 < EMA50（更明确的“转负”）。

## 选择

按协议第 5 节。
