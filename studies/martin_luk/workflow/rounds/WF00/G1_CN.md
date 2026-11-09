# WF00d：补 master 的 G1 凭据（流程问题账 WF-013）

先读 `skills/trader-replication/references/WORKFLOW_CN.md`，以及本目录的 `completion.json`（`switch_ie47` 小节）和 `STATUS.json`。约束同 PLAN_CN 第 6 节：不开候选，不改登记版和看板，不拉新数据，不改数据集，不改规则文件和 config 用户节，不提交。

**计算上限 30 分钟**；超了停下，写明卡在哪一步。

## 任务

1. **对参照系统 master 跑 G1 四项检查**：用 `studies.trader_replication.gate` 的 `check_data`、`check_fills`、`check_lookahead`、`check_win`，在真实冻结数据上跑，调用方式参照 `studies/martin_luk/e1_research.py` 已有的写法。
   - 范围：选择年 2024–2025。`check_lookahead` 用截断历史重放，按标的或日期分块，峰值内存不超过 900MB。
   - 结果交给 `pipeline.g1(..., is_reference=True)`，带代码与数据指纹，写进 `rounds/WF00/G1_master.json`。
2. **改 `workflow/bootstrap.py` 的 fixed_cards**：G1 只读 `G1_master.json` 的 `pipeline.g1` 结果。
   - 缺凭据就是 `unverified`，不能仅凭 datasets check 判通过；
   - 补一个单测覆盖“缺凭据 → unverified”。
3. **重出 `STATUS.json`**：只改 hard_gates.G1 和 `can_start_round`，其余照抄。
   - `can_start_round` 为 true 的条件：G1 通过、`datasets.approved_by_user` 有日期、datasets check 通过。
   - G1 不通过，就写明是哪一项、哪几笔或哪几天出的问题，不去修引擎。
4. **测试**：只跑 `custody/tests`、`studies/trader_replication/tests`、`studies/martin_luk/tests`。
5. **记录**：
   - completion.json 追加 `g1_master` 小节：结果、耗时、峰值内存、测试数；
   - 流程问题账追加 WF-013 的状态行。
