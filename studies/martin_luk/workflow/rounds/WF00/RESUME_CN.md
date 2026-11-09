# WF00 收尾（接 completion.json 的 stopped_rule_drift）

先读 `skills/trader-replication/references/WORKFLOW_CN.md` 当前版本和本目录的 `PLAN_CN.md`、`REPORT_CN.md`、`completion.json`、`rule_drift.json`。约束与 PLAN_CN 第 6 节相同：不开策略候选，不改登记版和看板，不拉新数据，不改数据集，不提交。

## 0. 规则基线

- 本次漂移是用户 2026-11-09 要求的规则改动（Codex 模型参数、单线迭代、每类轮次计算范围与冻结缓存、流程问题账字段），由 Claude 在你运行时写入，见流程问题账 WF-010a。
- 以当前 WORKFLOW_CN.md、编排脚本和判定代码为新基线，重新记录指纹。在 `rule_drift.json` 追加 `resolved` 记录（新旧指纹、原因、日期），原记录不删。
- 已产出的工具和基线不重算，除非第 2 节的核对要求重算。

## 1. 补冻结缓存（WORKFLOW 第五节“每类轮次的计算范围”）

在 `studies/martin_luk/workflow/frozen/<线>/<版本>/` 下，为 `state.json` 里的冻结版本各建一份：

| 线 | 版本 | 内容 |
|---|---|---|
| regime | B4_PCT2 | 全日历逐日状态 |
| selection | IE9 | 每晚有序点名：K=3 新点名、10 晚冷却，以及不限 K 两种口径 |
| trading | master 执行 | 测试台输入：他的段窗口和同晚对照名单；master 执行在测试台上的逐笔台账 |
| conversion | master 分配 | 分配配置 |
| reference | master、M3B | 参照账户逐日权益与逐笔台账，供行情层分状态收益用 |

- 每份带 `manifest.json`：版本、生成命令、代码指纹、数据集指纹、文件 SHA。
- 给 `funnel.py` 加读取缓存的入口；版本或指纹不符时报错，不悄悄重算。
- 体积报告实测值；超过 200MB 停下说明。

### 证明单线轮次能在上限内跑完

- 只读缓存，复算 IE9 的选股主尺和护栏，结果必须与 `selection.json` 逐位一致。
- 只读缓存，复算 master 执行的测试台主尺，结果必须与 `bench.json` 逐位一致。
- 两项分别计时，写进报告。目标是各自不超过 15 分钟。

## 2. 补完中断的核对

- 完成 completion.json 里 `new_tests_pending` 的两项检查。
- 全套测试重跑，范围同 PLAN_CN 第 6 节，加上 `studies/trader_data/tests`、`studies/trader_screens/tests` 和 `watch/test_watch.py`。
- datasets check 与 datasets scan --git-diff 重跑。
  - `martin-luk-benchmarks-v1` 缺 CHECKSUMS 照实失败，不补写，等用户决定；
  - 这一项只阻断开轮，不阻断 bootstrap_done。
- 按选择年，用 `pipeline.accept('selection', …)` 比较 IE47 与 IE9（冻结组件），把判定和逐条原因写进报告。只报告，不改冻结组件，交用户定。

## 3. 收尾

- 重出 `STATUS.json`，带上缓存路径与新指纹。
- 更新 REPORT_CN.md 开头的结论，以及第 8 节，补一节“收尾”。
- 本轮的流程问题追加进流程问题账。
- completion.json 改写：
  - `status`；
  - `bootstrap_done`：全部完成、测试全过才设为 true；
  - `can_start_round`：仍取决于用户确认白名单；
  - 单测数、缓存清单、两项计时、磁盘剩余。
- `state.json` 的 `bootstrap_done` 同步。
