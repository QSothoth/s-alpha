# 进度（中断后从这里恢复）

- 台账：`trades.csv` 66 笔，已在 5350fbd 冻结；切分点 2025-06-01。
- 已完成：R1–R6（旧入场：越过触发价 / 开盘买、当日最终低点止损；结果在 ROUNDS_CN.md）。
- 更正：5 分钟复核（`checks/ep_minutes.py`、`reports/ep_minutes.json`）显示旧入场高估 EP（10 天 +5.8% 对分钟执行 +1.3%）；收盘买与分钟执行一致（+1.3%）。
- 下一步：R7（`rounds/R7.json`，`base_change` 把入场改为 close），R8、R9 已预登记，都还没跑出结果（2026-10-18 中途停下）。
- 运行：`$PY -m studies.christian_flanders.replicate round R<n>`；诊断 `diagnose r<n>.json`、三层对照 `three r<n>.json`。
