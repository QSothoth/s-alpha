# 进度（中断后从这里恢复）

- 台账：`trades.csv` 49 笔（有日期 30 笔），已冻结；切分点 2026-01-01。
- 已完成：R1（形态，全部否定，基线 D0c）、R2（离场与容量，带入 K2）。结果在 ROUNDS_CN.md。
- 下一步：R3（`rounds/R3.json`，精选里的研究者取值：离年高 25%、5 日振幅 3 ADR、回踩、指数过滤）。
- 轮次统计：已用 2 / 40。
- 运行：后台队列 `python -m studies.trader_replication.queue`（`TR_QUEUE_DIR` 指定队列目录），或 `$PY -m studies.clement_ang.replicate round R<n>`。
