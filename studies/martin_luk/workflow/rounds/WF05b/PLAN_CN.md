# WF05b 修补任务书：v2 接受后的缓存、审计与版本表补齐（不是轮次）

工作区 `/opt/opend-us-options/.claude/worktrees/gap-review`（git worktree，不提交、不推送）。流程目录 `studies/martin_luk/workflow`（下称 DIR）。规则 `skills/trader-replication/references/WORKFLOW_CN.md` 先读。运行环境（PYTHONUTF8、LC_ALL、PYTHONDONTWRITEBYTECODE、TMPDIR=DIR/rounds/WF05b/work/tmp）已由启动命令设好。python 用 `/opt/opend-us-options/.venv/bin/python`。4GB 内存，同一时间只跑一个重计算。

## 背景

WF05 联动轮被接受，记为 v2（`DIR/rounds/WF05/REPORT_CN.md`、`DECISION_CN.md`、`VERIFY.json`；state.json 已由记账步骤更新为 v2 组件，`can_start_round=false`）。WF05 的 completion.json 与 STATUS.json 列出三处阻断，导致下一轮（WF06）不能开始：

1. 新交易缓存 `DIR/frozen/trading/WF05_J3` 沿用 C062 的 inputs，`selection_end_marks` 缺跨选择年末持仓 `US.PL` 的收盘价；`frozen_cache.bench_score` 读不出，也不认 `studies.martin_luk.wf05_engine`。
2. `versions.json` 追加 v2 后，`DIR/rounds/WF00/work/leverage_profiles/capital_audit.json` 绑定的 `versions_sha256` 失效，`status.readiness` 的 `capital_rules`、`registered_unchanged` 变 false。
3. `VERSIONS_CN.md` 中 v2 的分状态与“档案对齐”显示“未提供”（版本生成器只读 WF00 的 v0/v1 证据）。

## 要做的

1. **缓存**：让冻结缓存记录各版本自己的期末标记（从该版本账户的选择年末收盘价取，只用 ≤2025-12-31 的数据），`bench_score` 按缓存 manifest 记的引擎（system 或 wf05_engine）重放。重建 `DIR/frozen/trading/WF05_J3`（及受影响的 merge/conversion 缓存，如需要），更新 `state.json.frozen_caches` 的 manifest SHA。证明：v1（C062）缓存的 bench_score 结果与改前逐位一致；WF05_J3 的 bench_score 能复现 `DIR/rounds/WF05/work/bench_final.json`（或 J3 测试台记录）的峰前持有与成交。
2. **审计**：让资本审计可按版本追加重建，不改写 WF00 目录：新审计写到 `DIR/rounds/WF05b/capital_audit.json`（或在 status.py 里改为读取“最新有效审计”的位置，旧审计保留），覆盖 v0、v1、v2 三档（L1/L2/L2.8）原生重放，v0、v1 的数字必须与 WF00 审计逐位一致，v2 与 WF05 的 holdout_*/J3 记录一致。`registered_unchanged` 所需的测试证据按 status.py 现有要求重跑。
3. **版本表**：v2 附带自己的分状态证据（按冻结 B4_PCT2 日历拆账：行为离他多远、他的段峰前持有、收益与回撤）与档案对齐逐项表（config 用户节每项是否在范围内），版本生成器读取各版本自己的证据，重出 `VERSIONS_CN.md`。v0、v1 行必须逐字不变（先存 `work/VERSIONS_before.md` 对比）。
4. **STATUS**：按 v2 冻结版本重出 `DIR/rounds/WF05/STATUS.json`（先另存 `work/STATUS_WF05_before.json`），`can_start_round` 由 readiness 真实计算；成功时应为 true。阻断原因若仍存在照实写。

## 不许做

- 不改 `studies/trader_replication/pipeline.py`、`funnel.py`、`mainleg.py`、规则文件、`config.json`、`attempts.jsonl`、任何判定结果；不改 WF00–WF05 已有结果文件（除上面明确允许的 WF05/STATUS.json 与 VERSIONS_CN.md、state.json.frozen_caches / can_start_round / blocked_reasons）。
- 不改登记版与看板（`studies/trader_screens`、`studies/trader_replication/systems.py` 的登记系统）。
- 不跑任何新候选、不做任何选择；不读 2026 年数据做任何判断（v2 的 2026 列照抄 WF05 留出记录）。
- 只读 config 中 datasets 白名单数据。

## 测试与收尾

- 改了哪些代码就补哪些单测（studies/martin_luk/tests 下）；跑 `custody/tests`、`studies/trader_replication/tests`、`studies/martin_luk/tests`、`studies/trader_screens/tests`（status.py 证据要求），日志写 `DIR/rounds/WF05b/logs/`。
- `datasets check` 与 `datasets scan --config DIR/config.json --git-diff` 都通过。
- 写 `DIR/rounds/WF05b/REPORT_CN.md`（中文，白话：改了什么、怎么证明没改动旧结果、阻断是否解除）和 `completion.json`（含 `ok`、`can_start_round`、改动文件清单与 SHA、测试结果、`workflow_issues`、`keep`、轮前轮后磁盘剩余）。中间文件只放 `DIR/rounds/WF05b/work/`，收尾删掉不需要的。
- 计算上限 60 分钟；超了就停下写原因。
