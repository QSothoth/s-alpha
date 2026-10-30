# Dan Zanger R5 预登记：持仓（2026-10-29，跑之前写定）

- R4 照记：按预登记规则（`min_year` 最高）选中 EP（2024 +0.1%、2025 −6.2%、总 −6.1%、回撤 46%、每年 154 笔），但它的总收益、回撤、笔数都明显差于 ADD2（+22.0%、19%、61 笔），选择规则在这里偏离了任务（POSTMORTEM 第 4 条）。**主线不带 EP，改为 ADD2 + IDX50**（R4 的 IDX50：总 +26.2%、2024 +39.5%、2025 −9.5%、回撤 15%、排位 0.96，每项都不差于 ADD2）。R4 的 `r4.json` 原样保留。
- 本轮基础 MAIN = ADD2 + IDX50（`base_change`）。目标仍是 `min_year`；**新增门槛**：选择段总收益不低于 MAIN、回撤不超过 MAIN + 5 个百分点（防止重演 R4）。其余门槛不变。
- 候选（≤ 5，各改一处或成对改；方向取自以前其他交易员）：
  - EMA21：趋势线破位改用收盘跌破 21 EMA（Martin R31），“睡着”保留（“When the [trendline] break occurs, I am a seller”：上升趋势线在日 K 上的近似；他说不用跟踪止损，这里是收盘信号不是盘中止损）
  - EMA10：同上，用 10 EMA（Kell、Martin 的快线）
  - EPSLOT：加财报跳空 EP，但同时最多持有 1 只 EP（Qullamaggie / Marios 的 EP 单独名额；R4 的 EP 不限名额，笔数涨到 154、回撤 46%）
  - TRIM2：+15% 卖 25%，+30% 再卖 25%（“I sell all or part of my stock's position as it moves up strongly and then roll that money into new stocks”）
  - REV：重测 R3 的放量反转离场（R3 在 BASE25 上 +20.0% 未带入，基础已变，按否定登记表规则重测）
- 选择：过全部门槛者中 `min_year` 最高；不如 MAIN 就沿用 MAIN。
