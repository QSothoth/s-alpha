# Sam Miesse R11 预登记（2026-10-26，他的止损与他的股票，按他的单日最大亏损定风险）

- 主线 R9 G25S5（trader-data-v2）：风险 8% 时 2024 +54.1%、2025 +15.1%、回撤 58% / 64%；仓位报告（`trader_replication/reports/SIZING_20261026_CN.md`）里风险 4%（由他“单日最大亏损约 50 万、账户 220 万–380 万、每天约 5 笔”推出）2024 +41.2%、2025 +29.0%、2026 +33.4%，回撤约减半。本轮把风险 4%、单只 ≤ 30% 作为声明的基线更正（更接近原话），参照 G25S5R4。
- 依据（原话）：“I do use hard stop … the data should tell you where that is”；“stay away from stocks that have heavy institutional involvement”；“five and under on average”。
- 候选（≤ 5）：ATR2 / ATR3（止损 = 入场上方 2 / 3 个 14 日 ATR，按前一日收盘的比例，至少 10%，代替固定 30%）、TO20（20 日成交额上限 5000 万 → 2000 万）、ATR3TO20、MX3（每天最多 3 笔）。
- 未测并记为缺口：盘中止盈（日 K 无法判断最低价是否在冲高入场之后，会高估）；收购单剔除（开盘后冲高 5% 的入场已基本排除收购单）。
- 选择规则同 R6 起（`goal`，placebo / years / behav 门），50 次同池随机。
