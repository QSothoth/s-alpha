# 进度（中断后从这里恢复）

- 台账：`trades.csv` 49 笔（有日期 30 笔），已冻结；切分点 2026-01-01。
- 已完成：R1（基线 D0c）、R2（带入 K2 离场与容量）、R3（带入 F1 离年高 25%：全段 +57%）、R4（全部否定，宽度）、R5（全部否定）、R6（带入 I3 成交额排序 + 精选内回踩 + 每天 5 笔：全段 +117%，买到 3 笔）。结果在 ROUNDS_CN.md。
- 下一步：R7（`rounds/R7.json`，回踩不要求收盘站上、每天 8 笔）。
- 轮次统计：已用 6 / 40。
- 运行：后台队列 `python -m studies.trader_replication.queue`（`TR_QUEUE_DIR` 指定队列目录），或 `$PY -m studies.clement_ang.replicate round R<n>`。
