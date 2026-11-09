# P2 任务书（给 Codex）：Martin 按新流水线过 G2（行情 Switch）和 G3（信号覆盖）

工作目录 /opt/opend-us-options/.claude/worktrees/gap-review。先读：

- 根 AGENTS.md、studies/AGENTS.md
- `skills/trader-replication/SKILL.md`、`references/METHOD_CN.md`（P1 改过的版本）
- `studies/martin_luk/reports/P1_CN.md`、`reports/S0_CN.md`
- `notes/RULES_CN.md`、`notes/TRANSLATION_CN.md`
- `studies/trader_replication/{regime,pipeline,allocation,config,study,mainleg}.py`

约束：
- 用 .venv 的 python；`systemd-run --scope -p CPUQuota=60% -p MemoryMax=900M -q`，单进程单线程。
- 不联网、不拉新数据、不提交 git；不改登记版和看板。
- **本轮不碰交易期**：不做 allocate / trade / 账户的任何研究，信号覆盖达到 80% 之前都不碰（用户 11-08 定）。
- 策略侧不得读他的台账和段表，只在评测侧用。

本轮分两段，**一次做完**（用户 11-08 指示 A、B 都由 Codex 完成）。A 段完成后先写 `reports/P2A_CN.md`，再进入 B 段。B 段的候选必须先写进 `notes/PREREG_P2B_CN.md` 再评测，写完不改。

## A 段：行情 Switch 定义与 G2，以及信号漏点诊断

1. **改用真实指数**：P1 用的是池等权指数代理。本地已有登记数据 `data/martin-luk-benchmarks-v1/US.QQQ.csv`、`US.IWM.csv`，他的原话说的是 QQQ / IWM。按原话重做 `idx_ema`：QQQ 相对 EMA21 / 50，IWM 相对 QQQ 作为辅助。
2. **P1 的三种定义都没过 90% 扰动稳定性**，原因是状态来回跳：idx_ema 三年 144 段，平均每段约 5 天。允许在看他行为之前做一次预登记修订：加入状态确认期（新状态连续 3 个交易日才生效，这是常见做法），最多 2 个修订版本（例如 QQQ-idx_ema+3 日确认、QQQ-smc+3 日确认），参数只用常见值。先过稳定性（≥90%）和无未来函数检查。**挑选 producer 时只能看稳定性和段数，不能看他的行为和任何账户。**写进 `notes/PREREG_P2A_CN.md` 后再看他的行为。
3. **G2 有效性**：用通过稳定性的定义，按 SKILL 的 G2 逐状态检验他的行为差异：
   - 看什么：每个状态下他的笔数密度、形态类别（breakout / pullback / ep，来自台账 setup 字段）、方向、持有；
   - 怎么检验：整段置换，至少两段同向。
   - 有样本的状态给出 pass / fail；没有样本的状态（例如 2024–25 的 weak）标"未观测"，按 RULES 原话写出该状态的规则，最多 2 个开关，每个逐字引用原话。
4. **信号漏点诊断（只读）**：拿 S0 中留出最好的两个点名源（IE9、H1A 的信号），对 48 段里在 K=3 下没有早期覆盖的每一段，逐晚列出他的票卡在哪：
   - 不在池；
   - 在池但当晚排第几、被哪 3 只挤掉；
   - 10 日冷却挡住；
   - 点到时已经太晚。
   
   并按 A 段选出的行情状态分组统计漏点；同时报两源漏的段重不重合。**只分类，不据此设计新特征。**
5. 输出 `reports/P2A_CN.md`（中文、先写结论、白话）和 `reports/p2a_work/`，然后进入 B 段。

## B 段：G3 信号候选

预先说明范围，以免 A 段的结论诱导事后设计：

- 候选最多 5 个，全部用 facade 的 `signal()` 实现，只改 universe / signal 两层，layer 字段写 `signal`。
- 候选来源只有三类：
  1. 他的原话按状态启用形态家族（例如上升期突破 / EP、回调期首次回调、弱势期只看比大盘强的领涨）；
  2. 题材同动（H1A 的成组思路）与个股强势（IE9）两个点名源的合并方式；
  3. A 段漏点分类指出的那一层（池、排序、冷却、时效）的修正。
- 参数只取常见值，不网格，不拟合打分模型。
- 评测：S 口径 K=3 早期覆盖，2024 / 2025 / 2026 各年分别报，三年全报；选择规则是"较差年覆盖"最高，2026 标留出*。达标线 80%。同时报 K=1 / 5、每晚新名均数（不限 K 时 ≤5）、精度、剩余涨幅中位。
- 不达标就写清可达上限和卡在哪一层，不碰交易期。

- B 段的候选要用 A 段选定的行情定义；如果 A 段没有定义通过稳定性，B 段按单一状态做，这件事写进预登记。

## 最终输出

- `reports/P2A_CN.md`、`reports/P2B_CN.md`：中文、先写结论、白话。
- 工件放 `reports/p2a_work/`、`reports/p2b_work/`，各含 completion.json。
- 测试：custody、trader_replication、martin_luk。
- 终端最后用不超过 10 行写摘要，内容包括：行情定义是否通过、G2 各状态的结论、漏点主要卡在哪一层、B 段选中的候选、三年 K=3 覆盖，以及离 80% 还差多少。
