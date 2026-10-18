# 进度（中断后从这里恢复）

- 台账：`trades.csv` 66 笔，已在 5350fbd 冻结；切分点 2025-06-01。
- 已完成：R1–R6（旧入场，结果在 ROUNDS_CN.md）；R7–R11（收盘买、当日低点止损）。当前带入 = R10 的 X1（全段 +78%，2024 +78% / 2025 +11% / 2026 −10%，买到他 10 笔）。
- R12 带入池 ADR 2%（与 R10 逐笔相同），R13 全部否定。
- R14 全部否定。
- 下一步：R15（`rounds/R15.json`，2025 年离场：7 ATR 卖 70%、余仓 21 EMA / 50 日线、EP 量比、月度上限）。
- 轮次统计：已用 14 / 40。
- 运行：后台队列 `python -m studies.trader_replication.queue`（`TR_QUEUE_DIR` 指定队列目录），或单独 `$PY -m studies.christian_flanders.replicate round R<n>`；诊断 `diagnose r<n>.json`、三层对照 `three r<n>.json`。
