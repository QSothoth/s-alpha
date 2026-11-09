# WF00c：选股冻结版本换成 IE47（用户 2026-11-09 决定）

先读 `skills/trader-replication/references/WORKFLOW_CN.md` 当前版本（第四节选股护栏、第七节测试范围刚改过，以此为准），以及本目录的 `selection_decision_IE47_vs_IE9.json`。约束同 PLAN_CN 第 6 节：不开候选，不改登记版和看板，不拉新数据，不改数据集，不提交。

**计算上限 20 分钟；超了停下说明。**

## 背景与已定事项

- 用户 2026-11-09 定了三件事：
  - 数据白名单已确认（`approved_by_user` 已填）；
  - 选股护栏按方案实际输出的名单算（WF-011a）；
  - 选股冻结版本由 IE9 换成 IE47。IE47 在选择年 2024、2025 按 `pipeline.accept('selection')` 判定为接受。
- 规则文件和 config 用户节在你启动前已改好，以当前文件为基线。不要改它们。

## 任务

1. **缓存身份去掉规则文件**：`studies/martin_luk/workflow/frozen_cache.py` 的 `CODE` 去掉 `WORKFLOW_CN.md` 和编排脚本（规则另有 pin）。原因见流程问题账 WF-012。
2. **按冻结版本建缓存**：`build` 改为按 `state.json` 里的冻结版本建，不写死 IE9。
   - 选股缓存的来源取 `config.systems` 或注册表里该版本的 picks（IE47 是 `s0_work/picks/IE47.json`）；
   - 没有原始排序的版本，`upstream_order` 用它自己的名单，并在 manifest 里注明。
3. **改冻结状态**：
   - `state.json` 中 `components.selection` 改为 IE47，附 accept 判定与日期；
   - `pending_merge=true`。合并按单线迭代规则推迟到运行结束，本任务不做合并。
4. **重建全部缓存**：
   - 选股：IE47；
   - 交易测试台：master 执行，同晚对照名单换成 IE47 的非他的票，在测试台上重跑 master 执行；
   - 行情、衔接、参照账户：只因缓存身份变化重写 manifest，内容应逐字节不变，请核对。
5. **只读缓存复算**：
   - IE47 的选股主尺和护栏，须与 `selection.json` 中 IE47 逐位一致；
   - master 执行在新对照下的测试台，报告与旧对照的差别。
   - 两项各自计时。
6. **重出 `STATUS.json`**（selection 与 trading 两格，其余照抄），在 REPORT_CN.md 末尾追加“选股换成 IE47”一节，白话，先结论。
7. **测试**：只跑 `custody/tests`、`studies/trader_replication/tests`、`studies/martin_luk/tests`。
8. **completion.json** 追加 `switch_ie47` 小节：完成项、测试数、两项计时、`can_start_round`。本轮的流程问题追加进流程问题账。
