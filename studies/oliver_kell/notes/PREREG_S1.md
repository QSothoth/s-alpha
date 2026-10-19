# S1 预登记：Wedge Drop 与 Downside EMA Crossback（按原话的端到端版本）

2026-10-19 写于看任何 Kell 空头结果之前，跑完不改。口径与选择规则见 [TRADER_PROTOCOL_CN 第 5 节](../../../docs/TRADER_PROTOCOL_CN.md)；运行 `python -m studies.trader_replication.shorts round oliver_kell S1`。

## 原话（RULES ⑨；档案 OK6 2024-06、OK7 2024-07，TraderLion 署名教学页，当前直接访问 403，用档案里已读的摘录）

- 价格循环的下半段：过度延伸后跌破均线（Wedge Drop）——多头退出，满足条件再考虑做空。
- Downside EMA Crossback：弱势中反抽到下降的 10 / 20 EMA 阻力，失效（重新站上）就退出；“不是无条件看空”。
- 用 10 还是 20 EMA 依价格行为而定；指数低于 20 EMA 时多头更谨慎（R6 A5 的多头市况开关就是指数在 20 EMA 上方）。

## 翻译（`replicate.py` 的 `short_setups`，看板 Wedge Pop / EMA Crossback 翻过来）

- **drop**：前 10 天内某天收盘高出 10 日线 ≥ 30%（他多头“高出 10 日线 30% 卖 1/3”的延伸口径），昨天收在 10 / 20 EMA 较低者之上，今天收在其下方；收盘卖空，止损当日最高价（至少 1%）。
- **dcross**：Wedge Drop 后 2–20 天、还没收回 20 EMA，第一次反抽最高价碰到下降的 10 EMA 且收在 20 EMA 下方（准备日），之后 5 天内收盘跌破准备日低点时卖空（看板“越过准备日高点买”翻过来，收盘确认），止损当日最高价。
- 股票池：20 日成交额 ≥ 1 亿美元、价格 ≥ 5、ADR ≥ 3%（R6 A5 多头池），前一天确定。
- 离场：收盘站上 20 EMA 回补（多头“收盘跌破 20 EMA”翻过来；KE 用 10 EMA）；不按 R 分批。每天最多 2 笔空，先开多再开空；风险与多头相同（每笔 0.5%、单只 ≤ 9%），借券年化 3%。

## 候选

- **KA** 只做 drop，指数前收在 20 EMA 下方才开。
- **KB** 只做 dcross，同上。
- **KC** drop ∪ dcross，同上。
- **KD** drop ∪ dcross，不看指数。
- **KE** 同 KC，跟踪线换 10 EMA。

## 选择

按协议第 5 节。
