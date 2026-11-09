# E18 任务书（给 Codex）

工作目录：/opt/opend-us-options/.claude/worktrees/gap-review。先读根 AGENTS.md、studies/AGENTS.md，再读：
- notes/PREREG_E16_CN.md、PREREG_E17_CN.md、PREREG_E18_CN.md（预登记，不得修改）
- reports/E16_CN.md（E16、E17 结果与诊断）
- e16_research.py（E16–E18 共用实现，Claude 写的）、tests/test_ie47_e16.py

所有 python 用 /opt/opend-us-options/.venv/bin/python；长任务加 `systemd-run --scope -p CPUQuota=80% -q`；不拉新数据、不联网、不提交 git、不改登记版和看板。4GB 内存，同时只跑一个回测进程。

## 1. 等 E18 跑完

E18 已在后台运行（命令 `python -m studies.martin_luk.e16_research BASE R1 R2 R3 R4 R5`，日志 studies/martin_luk/reports/e16_work/train_e18.log，结果写入 e16_work/summary.json，键 `R1_train` 等；E16/E17 的旧汇总备份在 summary_e16.json、summary_e17.json）。用 `pgrep -f e16_research` 循环等待它结束（sleep 30），不要重启它。若日志有 Traceback，修复后只重跑失败的候选。

## 2. 复核实现（先于看结论）

- 逐行审 e16_research.py 的 persistent_book / overlay_book / arm_rules，与三份预登记对照，列出任何不一致或未来函数（信号只能用当日收盘及以前；出名单用前一日收盘；Q4 用前一晚过滤池）。
- 核对 BASE 与 E16 逐位一致（summary_e16.json）。
- 核对 R 系列的 max_open_by_kind / max_new_by_kind 实际生效：在 R1 台账里统计每天同时持有的再试单（kind = ie47_close_retry）只数，最大值必须 ≤ 3（R2 ≤ 2、R3 ≤ 5），R5 每天新开再试 ≤ 1。
- 跑单测：`.venv/bin/python -m unittest studies.martin_luk.tests.test_ie47_e16` 和 `.venv/bin/python -m unittest discover -s custody/tests`。

若发现实现错误：照实记录，修复后重跑受影响的候选，修复前后的结果都保留。

## 3. 按 PREREG_E18_CN.md 选择

资格与选择规则以预登记原文为准，不改门槛。

- 有人合格：对选中者做截断检查——用 `upto='2025-06-30'` 重建面板与入场簿（参考 e15_research.py 的截断做法），确认截断日前的入场簿和成交逐笔一致；然后按预登记测 2026 一次（`--span=2026`，以及 `--span=full`）。看完不改规则。
- 无人合格：不测 2026。

## 4. 逐笔诊断（不论是否合格）

对每个 R 候选，与 BASE 和 Q1 对照，分年给出：
- 再试单 / 底版单的笔数、平均 R、pnl 合计；
- 相对 BASE 缺失的底版交易（按 pnl 排前 10），以及缺失当天的持仓数、其中再试单数——判断格子问题是否已解决；
- 他 2024–25 多头交易（notes/trades.csv）的买到并赚钱笔数、他的段中点持有；
- 收益是否被一两笔主导：去掉 pnl 最大 1 / 3 笔后的 pnl 合计。

## 5. 输出

在 reports/E16_CN.md 末尾追加“## 6. E18”一节（中文，先结论、表格、白话，和前文风格一致），写清：是否有人合格、选中者（若有）的 2024 / 2025 / 2026 / 全段、第 2 节的复核结果、第 4 节的诊断，以及你认为差距现在落在哪一层（名单、格子、执行、选股），给出下一轮 ≤5 个候选的建议（只建议，不跑）。最后在终端输出 10 行以内的摘要。
