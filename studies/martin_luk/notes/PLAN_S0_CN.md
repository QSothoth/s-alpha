# S0 任务书（给 Codex）：定义"信号覆盖"标准，并量出历史各轮的水位

工作目录 /opt/opend-us-options/.claude/worktrees/gap-review。先读根 AGENTS.md、studies/AGENTS.md、`skills/trader-replication/references/METHOD_CN.md` 第 11 节、`studies/martin_luk/reports/REVIEW_ALL_ATTEMPTS_20261108_CN.md`（第 7–8 节）、`notes/YARDSTICK_BUDGET_CN.md`、`studies/trader_replication/mainleg.py`、`martin_budget_metric.py`、`reports/d1_work/funnel.json` 的生成代码 `d1_analyze.py`。

约束：
- 用 .venv 的 python；`systemd-run --scope -p CPUQuota=60% -p MemoryMax=900M -q`，单进程单线程。
- **只读评测**：不改任何选股或执行逻辑，不改已发布报告的数字，不改登记版和看板。
- 不联网、不拉新数据、不提交 git。只用日 K。
- 本轮不做执行、仓位、账户的任何研究（用户 11-08 明确：先把信号找齐找准）。

## 为什么要新标准

旧口径（METHOD §11.2 的 `C_signal`、IE 系列的"主升浪覆盖约 80%"、"名单里有他的票"）只问"合格的夜里有没有点到他"，不管每晚点了多少只，也不区分是不是拟合用过的数据。后果：

- master 每晚取前 4 之前有 67–166 个信号，一年 700–1100 只不同票，早期覆盖 9/9、16/16、15/17，看起来完美，其实是撒网；
- IE47 的 2024–25 是拟合数据，样本内数字被当成了成绩。

结果是连续几周都没意识到真正的卡点在信号收窄。新标准要让这个问题一眼可见。

## 标准定义（S 口径）

1. **分母**：冻结段表 `notes/legs_frozen.json` 的 48 段（9/22/17），引用 SHA256。
2. **合格夜**（沿用 §11.2）：t 晚的信号，t+1 开盘买；t+1 在 [first−3, peak−1] 内，且 t+1 开盘时仍剩首锚点涨幅 ≥ 1/2。
3. **宽度预算（新增，核心）**：每晚只认系统**自己排序的前 K 只新点名**。10 个交易日内点过的同一只不占名额，也不算新命中（沿用 YARDSTICK_BUDGET）。系统点名不足 K 只时照实，不补。
   - 主口径 K = 3（他每个交易日约 3–4 笔，同时拿 3–4 只）。
   - 同时报 K = 1、5，以及"不限宽度"。不限宽度这一列必须同时写出每晚平均点名数，不能单独引用。
4. **主数字 = 留出段的 K=3 早期覆盖**。拟合或调参用过的年份一律标"样本内"，不能作为结论里的主数字。没有留出段的系统，写明"无留出"。
5. **随同报告**（每行都要有）：
   - 每晚平均新点名数、每年不同票数；
   - 首次合格点名时剩余涨幅比例的中位数（早晚程度）；
   - 精度：点名中落在他任一段合格夜的比例（只作参照）。
6. **达标线**：留出段 K=3 早期覆盖 ≥ 80%（用户 11-08 的 B 口径：和他差距不超过 20%）。
7. **报警规则**（写进 METHOD 与报告模板）：凡是覆盖数字没有同时给出宽度和样本内/外标记的，不能出现在结论里。

## 要做的

1. 在 `studies/trader_replication/mainleg.py` 增加评测函数（例如 `signal_coverage_budget(picks_by_night, ranks, legs, calendar, opens, K, cooldown=10)`），只作评测，不接入决策；补单测，至少覆盖：宽度截断、10 晚冷却、名额不足、合格夜边界（first−3、peak−1、剩一半）、跨年段。
2. 更新 `skills/trader-replication/references/METHOD_CN.md` §11.2：把 S 口径写成选股层的**主尺子**，旧 `C_signal` 降为"不限宽度"诊断列，写清报警规则。只写已经实现的内容。
3. **历史水位表**：对每一轮能恢复每晚点名的系统，按 S 口径重算。至少包括：
   - 登记 master（取前 4 之前和之后两种）、M1B / M2A / M3B 的名单层；
   - IE9、IE26、IE30、IE33、IE40、IE43、IE47（能找到的都算）；
   - E12 名单、E16–E21 名单变体、F1–F4、U1 画像、H1、H2 的点名。
   优先用已保存的工件（`reports/*_work/`、`studies/trader_replication/` 下各脚本的输出）。没有保存但脚本还在、且能在内存约束下重跑选股部分的，只重跑选股；都不行的，列为"不可复算"并写原因。**不得为了复算去改原脚本逻辑。**
   系统没有自带排序的，用它实际成交/发信号的顺序；规则写清，不自己发明排序。
4. 每个系统标明：哪些年份参与过拟合或调参（查各轮 PREREG / 报告），哪些是留出。

## 输出

- 报告 `studies/martin_luk/reports/S0_CN.md`：中文，先写结论，白话。主表一行一个系统，列为：K=3 早期覆盖（2024 / 2025 / 2026，每格标样本内或留出）、K=1、K=5、不限宽度（附每晚点名数）、每年不同票、剩余涨幅中位、精度、是否达标。另附"当前水位"一句话：留出段的最好水平是多少、离 80% 还差多少。
- 工件放 `reports/s0_work/`，包含 completion.json 和三组测试结果（custody、trader_replication、martin_luk）。
- 终端最后用不超过 10 行写摘要。
