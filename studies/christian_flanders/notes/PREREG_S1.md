# S1 预登记：熊市反抽到下行 200 日线、财报跳空远离 200 日线（按原话的端到端版本）

2026-10-19 写于看任何 Flanders 空头结果之前，跑完不改。口径与选择规则见 [TRADER_PROTOCOL_CN 第 5 节](../../../docs/TRADER_PROTOCOL_CN.md)；运行 `python -m studies.trader_replication.shorts round christian_flanders S1`。

## 原话（RULES ⑧；本地字幕 `data/christian-flanders-subs`）

- 6aOnCK1gv2w@01:24:20–01:26:00：“my experience when shorting in bull markets is not positive … if I have some profits, I'm just going to take it right away”；“when I'm looking to short in a bear market … I would look for these kinds of rallies into a declining 200 day moving averages, like low-risk short points”；Micron “I did short on the gap down … on earnings … when it gapped away from the 200 day moving average”。
- 8vX0kp766aA@00:31:00–00:33:00：Micron 的 200 日线“literally got rejected four times”，然后财报跳空就做空；FTI “breakdown day … covered that like the next day”；“it would be different if we were entering what I thought was a prolonged bear market”。

## 翻译（`replicate.py` 的 `short_setups`）

- **r200**：前一日收在下行的 200 日线下方（200 日线低于 20 天前）→ 当天限价卖空在前一日的 200 日线（开盘在下方、最高价到过才成交），止损在上方 min(5%, 半个 ADR)（至少 1%），当天到止损按止损价出。
- **gap200**：开盘相对前收跳空下跌 ≥ 10%（他 EP 的 10% 翻过来），前一日收在下行 200 日线下方，过去 60 天至少一次“最高价碰到 200 日线、收在其下方”（被拒）；开盘卖空，止损同上（开盘价是当天第一个价格，精确）。
- 股票池：多头池下限（20 日成交额 ≥ 2000 万、价格 ≥ 5、ADR ≥ 2%），前一天确定。
- 离场（FA–FD）：“有利润就马上了结”——第 1 个交易日收盘若盈利全部回补，否则止损或最多持 3 天；FE 是“若是漫长熊市就不同”的版本：沿用多头离场翻过来（第 3 天盈利回补一半、余下收盘站上 10 日线回补）。
- 每天最多 2 笔空，先开多再开空；风险与多头相同（0.5%），借券年化 3%。“熊市”用等权指数前收在 50 / 200 EMA 下方表示。

## 候选

- **FA** r200，指数 < EMA50。
- **FB** r200，指数 < EMA200（更严格的“熊市”）。
- **FC** gap200，指数 < EMA50。
- **FD** r200 ∪ gap200，不看指数（检验“牛市里做空不顺”）。
- **FE** r200 ∪ gap200，指数 < EMA50，多头式离场。

## 选择

按协议第 5 节。
