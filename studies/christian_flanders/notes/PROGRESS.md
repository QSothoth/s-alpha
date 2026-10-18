# 进度（中断后从这里恢复）

- 台账：`trades.csv` 66 笔，已在 5350fbd 冻结；切分点 2025-06-01。
- 已完成：R1（形态，带入 C1 = 初版 + EP）、R2（股票池，带入 P2 = EP 池 500 万 / 2 美元）。
- 进行中：R3 入场与止损（`rounds/R3.json`）。
- 运行：`$PY -m studies.christian_flanders.replicate round R<n>`；诊断 `diagnose r<n>.json`、三层对照 `three r<n>.json`。
