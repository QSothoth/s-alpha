# 新会话：用最新 workflow 把 Martin 从 v1 优化出 v2

工作区 `/opt/opend-us-options/.claude/worktrees/gap-review`。规则只看 `skills/trader-replication/references/WORKFLOW_CN.md`，其他细节都在 workflow 和规则里，不在这里重复。

## 目标

在底座 v1 之上，按 workflow 做出一个通过合并验收的 v2。v2 好不好只看 `config.json` 的 `goal`：更像他（各项差距不超过 20%、覆盖他的持仓），每年不亏，收益不能差太多（尤其 2025）。跑的过程中发现的流程问题，记进流程问题账，在检查点提给用户。

## 现状

看 `studies/martin_luk/workflow/VERSIONS_CN.md`。一句话：v1 选股已经能提前点到他的 22/31 段，但买晚、仓位小，峰前持有只有 13/31；钱都在进攻态赚，防守态亏；2026 年亏 14%。

## 开轮前

1. **核对 WF00h 的结果**（单元 `codex-martin-luk-wf00h`）：档案检查、行为画像草稿、B4 重判、关掉 v1 里 QQQ 开关后的对照。
2. **请用户定**：底座要不要去掉 QQQ 开关、画像草稿是否并入档案、B4 重判结论。用户没定之前，不动 config 用户节。
3. **补脚本两处缺口**，先给用户看，同意后在没有 Codex 运行时改：
   - 每轮“量”要跑 `profile check`；
   - 规则指纹要补上 `bar`、选择年、留出年、段表。

   改完运行 `bash studies/martin_luk/workflow/tools/run_mocks.sh`。
4. **确认能开轮**：`STATUS.json` 的 `can_start_round=true`，指纹和当前文件一致，然后问用户要不要先在本地提交一次。

## 运行

在终端 claude 里运行：`ultracode 运行 trader-replication-loop，trader=martin_luk，line=trading，rounds=3`。被接受后，再跑一次不带 `line` 的运行做合并验收，通过就记为 v2。

## 容易踩的坑

- master 只作底线比较，不能作任何一条线的起点；它的执行可以当线索，但不能整体照搬。
- v1 本身 2026 年就亏钱，所以 workflow 很可能停在“留出年亏钱”。这是规则生效，照实汇报，不要为 2026 去设计方案。
- 有 Codex 在跑时不要改规则文件或 config，否则会触发漂移停机。
- 汇报用中文白话，先出版本总表，只说 v0 / v1 / v2。
