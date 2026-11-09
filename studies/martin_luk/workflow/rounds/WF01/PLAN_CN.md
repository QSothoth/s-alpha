# WF01 任务书：联动轮（line=joint）

> 本文件就是全部要求。规则以 `skills/trader-replication/references/WORKFLOW_CN.md` 为准，先读它；本书与它冲突时以它为准，并把冲突写进 completion.json 的 `workflow_issues`。工作区 `/opt/opend-us-options/.claude/worktrees/gap-review`，不提交、不推送。交易员 martin_luk，流程目录 `studies/martin_luk/workflow`，本轮目录 `rounds/WF01`。

## 0. 定格结论（为什么做联动轮、改哪几格）

### 0.1 全局

截至 2025-12-31 已完成的 28 段（选择年，跨年 3 段不参与定格），v1（IE47 + C062 + C062，L2.8）的合并漏斗：L0 1 / L1 4 / L2 1 / L3 5 / L4 10 / L5 2 / L6 5，峰前持有（含晚买）11 段（2024 4、2025 7）。行为记分卡 0–1/3 项在 ±20% 内；收益 2024 +61.3%、2025 +57.4%（他 +283% / +970%）；平均总敞口只有 0.82–1.05 倍（验收档 L2.8 上限 2.8 倍）；分状态收益 2024 上升 +79.2% / 弱 −10.0%，2025 上升 +60.5% / 弱 −1.9%。

### 0.2 损失落在几层：L3 与 L4 是同一个机制，跨衔接线和交易线

Plan 步骤逐段读了 `rounds/WF00/funnels/C062.json` 与 `rounds/WF00/bench.json`（只读诊断，不是策略输入）：

- L3 的 5 段全部、L4 的 10 段中 6 段（另 L5 的 2 段）都是：**当晚已被 IE47 点名 → 次日形成收盘突破 → 账户没成交**。登记账户没有准入记录，漏斗只能写 `no_admission_trace`，真实原因未知。
- 同一批段在交易测试台（从首锚点前 3 晚起每晚喂他的票，执行仍是 C062）上：L3+L4 共 15 段中 7 段早买且峰前持有、9 段峰前持有。所以 L4 的“买晚”主要不是执行的买点或止损问题，而是“点到了却没进去”，之后要等很久才再买到。
- `studies/martin_luk/ie47_e1.py` 的 `entry_book` 文档写明：**“第一次突破即使被账户规则拒绝，也会用掉这次观察。”** 叠加 IE47 的 10 晚冷却，一次被挡就等于这一轮点名作废。这是 L3、L4 共同的机制候选。
- 账户在挡什么：测试台 C062 的 2099 次准入里 `max_open` 568 次、`daily_long` 198 次；合并账户按逐笔台账粗算，2024、2025 各约 72、75 个交易日持仓数达到 11 只上限（平均约 7.6–8 只）。持仓多而小：首仓中位只占权益 2.3%–2.8%，证实加仓后的最大仓位中位 10%–16%，证实单约八成最终 R<0。这正是老坑 H1（宽止损配固定风险导致仓位太小）和 H2（小仓占满名额）的组合：名额被小仓占着，他的票进不来；进来的又太小，“大资金花在他的票上”做不到。

结论：损失落在几层且互相牵连（衔接线的准入与名额 × 交易线的仓位），按规则第二节做**联动轮 line=joint**，按合并验收判定并做消融。

### 0.3 scope（改了哪些“线 × 状态”）

| 线 × 状态 | 本轮改动 | 冻结版本 |
|---|---|---|
| 衔接 × common | C1 被账户挡掉的突破不算用掉观察；C2 满仓时顶掉最弱 | 原 C062 分配 |
| 交易 × common | C3 每笔风险 0.25% → 0.5% | 原 C062 执行 |
| 选股 × common | 不改，用冻结 IE47 | IE47 |
| 行情层 | 不改，B4_PCT2 只用于分状态拆账，不进执行 | B4_PCT2 |
| 任何 by_state | 本轮不做 | — |

本轮不做 by_state 修正的理由：仓位类开关（例如用 B4 替换 C062 自带的 `e8_scale`）按规则第三节第 8 条要证明“该状态下行为更接近他”，而档案 `behaviour_card.by_state` 的胜率、盈亏比、笔数、收益都是“未观测”，仓位开关又不改变多空和形态，接受条件算不出来；弱势态的真正差别是他有空头（regime.words 第 2 句），而 B4 冻结时只对应第 0、1 句。两者都留给后续轮次（见第 9 节“下一轮”），本轮只做第 6.4 节的开关对照报告。

### 0.4 触及的档案项（规则第九节）

- `capital`：只在 L2.8 档内改每笔风险（可优化项“档位内用多少杠杆、单只仓位上限”）；`max_open=11`、`max_gross=2.8`、维持线 30%、追保次日开盘、减仓 `weakest_first` 都不变。换仓（C2）属于衔接线“换仓”可优化项，不是追保减仓方式。
- `behaviour_card`：胜率、盈亏比、笔数按年对照（±20%）；持有天数只说明。
- `regime`：不用于执行；开关数 0 → 0。
- `goal` 第 1、2、3、4、7、8 条：见第 7 节逐条对照。
- 不越出：不加杠杆档、不改追保时点、同时持仓仍 ≤11 只（他的原话“最多 11 只”）。

## 1. 硬约束（违反任何一条就停下，写进 completion.json）

- 只用日 K 与已冻结数据，不拉新数据、不联网取行情。只读 `config.json` 的 `datasets` 白名单（含 `artifacts` 与 `evaluation`）以及经 `studies.trader_data` 派生的缓存；不新增、修改、替换数据集或 schema；新代码里不出现白名单以外的数据路径。
- **策略侧不读他的台账、票名、日期、段表**：`notes/trades.csv`、`notes/legs_frozen.json`、`adapter.labels()` 只能在评测代码里出现。新策略模块（见 2.2）里出现这些就是失败，单测要扫。
- 不改：`WORKFLOW_CN.md`、`config.json`、`.claude/workflows/` 下任何文件；`studies/trader_replication/pipeline.py`、`funnel.py`、`mainleg.py`（尺子与判定）；以及冻结缓存指纹覆盖的代码（`studies/trader_replication/system.py`、`allocation.py`、`regime.py`，`studies/martin_luk/ie47_e1.py`、`e15_research.py`、`e10_research.py`、`p3_research.py`、`p4_policy.py`、`p5_policy.py`、`replicate.py`，`studies/trader_data/supplemental.py`，`studies/martin_luk/workflow/*.py`）；`frozen/` 下已有缓存；`state.json`、`attempts.jsonl`、`versions.json`、`VERSIONS_CN.md`（记账步骤负责）；登记版与看板（`studies/trader_screens/`、`studies/trader_replication/systems.py`）。需要改这些才能做的候选，直接放弃并在报告里写原因。
- 选择年 2024、2025 只用于选择；2026（标“留出*”）只对最终选中版本跑一次，结果不进入任何选择、消融或参数。
- 同一时间只跑一个重计算进程；每个进程 `systemd-run --scope -p CPUQuota=60% -p MemoryMax=900M`，`OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1`；先查 `free -m`，不构造 N×N 大矩阵。
- 计算上限：本轮全部重计算（诊断 + 候选 + 消融 + 留出 + 缓存）合计 60 分钟（墙钟，以日志时间为准）。超了就停，报告写明停在哪一步、为什么，不加跑。
- 文档中文；代码、标识符英文。中间文件只放 `rounds/WF01/work/`。

## 2. 输入、比较对象与新代码

### 2.1 冻结输入（只读，不重算）

| 用途 | 来源 |
|---|---|
| 选股（冻结 IE47 每晚点名，K=3、10 晚冷却原样） | `config.systems.C062.picks` = `studies/martin_luk/reports/s0_work/picks/IE47.json`（白名单 artifact）；先核对它与 `frozen/selection/IE47/manifest.json` 登记的来源 SHA 一致 |
| 比较对象 v1 的账户与漏斗 | `frozen/merge/C062/account.json`、`frozen/merge/C062/funnel.json`（经 `frozen_cache.load('merge','C062')` 读，指纹不符即停） |
| 交易测试台 v1 | `frozen/trading/C062/`（经 `adapter.cached('trading','C062')`） |
| 状态日历 | `frozen/regime/B4_PCT2/states.json`（只用于拆账） |
| 底线 v0（只作报告） | `frozen/reference/master/account.json`；不作底座、不作比较对象 |
| C062 规则 | `studies/martin_luk/reports/m3_work/compatibility/C062/rules.json`，经 `adapter.rules_for('C062')` 与 `capital.candidate_rules(..., 'L2.8', 'weakest_first')` |
| 行情面板与 `e8_scale` 等输入 | 照 `rounds/WF00/work/leverage_profiles` 所用 `rounds/WF00/work/leverage_replay.py::run('C062', ...)` 的准备方式（`u1_work/panel`、`e1_work/selection.npz`、`US.QQQ` 冻结基准，都是白名单 artifact）；可 import 或复制它的准备代码，不改原文件 |

**比较对象写死**：v1 = 冻结合并主线 C062（IE47 + C062 + C062，L2.8，先减最弱）。选择年数值以 `rounds/WF00/STATUS.json` merge × common 格为准：峰前持有（截至选择年末已知，含晚买）2024 4、2025 7，合计 11；收益 2024 +61.3095%、2025 +57.3669%。第 3.1 节的重放必须逐位复现这些数，否则停。**参照账户**：v0 master 只在报告里并列，不参与判定。

### 2.2 新代码放哪里

- 策略：`studies/martin_luk/wf01_joint.py`。只接收行情数组、冻结点名与规则，产出 entry book、episode 数组和 `Rules`；不 import `adapter.labels`、不读 `notes/`。
- 评测与运行脚本：`studies/martin_luk/workflow/rounds/WF01/work/run_wf01.py`（可读段表，只做评测）。
- 单测：`studies/martin_luk/tests/test_wf01_joint.py`。

### 2.3 三个组件（参数现在写死，跑完不改）

- **C1 挡掉不算用掉**（衔接 × common）。在 `ie47_e1.entry_book(..., **E6['E6c'])` 的规则之上只改一处：某只票这轮观察（点名夜 t，观察 t+1…t+5）里，第一次突破照原规则生成入场；之后观察**不结束**，同一观察窗口内后续每个符合同一原规则的突破也生成入场（各自用当天的收盘、低点和前一日 ADR 定止损，宽度上限照旧 min(5%, ADR/2)）。每个入场带上本轮观察的编号（点名夜序号），通过引擎已有的 `entry_episode` / `entry_episode_max=1`：同一轮观察**最多成交一次**；成交过（含当天被止损）就不再买；只有之前的突破被账户挡掉（满仓、每日上限、仓位太小等）时，后面的突破才可能成交。窗口长度 5、10 晚冷却、名次与原规则一样；第一次突破若被 book 自己的规则拒绝（原规则里会结束观察的情况），照原规则结束观察。C062 后续处理照旧：`E15.P.retry_book(A, book, {}, E15.SPECS['C062'])`（T0，无再试），再把每个入场改成 `tuple(e[:7])+(None, .30)+tuple(e[9:])`。
  - 原话：③ 观察名单“扫描里新出现的要重点看”；⑤ 入场“越过前一根 K 线高点即买”。账户忙不是市场事件，不该让他放弃一只还在观察中的票。
  - 和旧轮次的差别：E16 L 系列把 5 晚观察换成 12 只持续名单（实际 4 晚就被挤出），且可多次试、止损后可再买；E17 Q 系列是止损后老票再试，挤占名额。C1 窗口不变、每轮观察最多成交一次、不允许止损后再买。
- **C2 满了顶掉最弱**（衔接 × common）。打开引擎已有的 `rotate_below=0.02, rotate_min_days=3`：收盘入场遇到 11 只已满或总敞口剩余 <5% 时，卖掉持有 ≥3 个交易日、当日收盘相对成交价涨幅 <2% 的多头里最弱的一只（按收盘/成交价最低），在该收盘成交后再开新仓；没有符合条件的就不开。这两个数沿用过去研究用过的常见值，本轮不调。
  - 原话：⑦“同时 3–4 只，最多 11 只”；TRANSLATION 全听“同时持仓设上限，新票要顶掉最弱的仓位才能进”。
  - 和旧轮次的差别：E19 只在 R2 的两只再试格子之间腾仓，按点名先后而非强弱，S2 因腾掉已证实赢家（HOOD、RKLB）变差；本轮不加再试单，对全部多头按强弱腾，涨 ≥2% 的一律不动，并和 C1 成对（E19 没有 C1，被挡的突破仍用掉观察）。PREREG_STRONG 的 BH1/BI1 在 U1 底座（master 系）上用过同样两个数，底座和名额构成不同（下游大改后重测）。
- **C3 每笔风险按原话 0.5%**（交易 × common）。`risk: 0.0025 → 0.005`，其余（`probe_hard_mult=2`、`proof_risk`、`proof_target_mult=4`、`max_position=0.5`、每笔元组上限 0.30、`e8_scale`）不变；`capital.check_rules` 必须通过。按 C062 的试仓公式，5% 止损时试仓约从 2.5% 升到 5%，证实后目标随之加倍，仍受 0.30 单只上限约束。
  - 原话：⑦“每笔风险约 0.5% 权益；单只 25%–30%”；TRANSLATION 听一半“试仓 8–10%……证实后加到 25–30%”。日 K 宽止损下照搬 0.25% 正是老坑 H1。
  - 和旧轮次的差别：E8/E13 改的是按市况、按证实程度的风险倍数，没改基础风险；H2 在 master 底座上用 `daily_tolerance` 试仓 10% 加到上限，没有 C062 的证实加仓与 2 倍硬止损，也没有 C1/C2。

### 2.4 五个候选（不超过 5 个）

| 候选 | 组件 | 改动的“线 × 状态” |
|---|---|---|
| W1A | C1 | 衔接 × common |
| W1B | C1 + C2 | 衔接 × common |
| W1C | C1 + C3 | 衔接 × common、交易 × common |
| W1D | C1 + C2 + C3 | 衔接 × common、交易 × common |
| W1E | C2 + C3 | 衔接 × common、交易 × common |

五个候选同时就是 W1D 的全部单项消融（去 C1 = W1E，去 C2 = W1C，去 C3 = W1B）。其他组合只在第 5 节消融需要时作为消融配置补跑，不参与选择。

### 2.5 计算范围（规则第五节“联动”行）

| 只跑 | 不跑 |
|---|---|
| 候选的 entry book（衔接）与执行（交易），完整账户（只到 2025-12-31）、漏斗、消融；W1_FINAL 的一次留出；被接受且含 C3 时，新执行规则下的交易测试台一次（建缓存用） | 选股点名（读冻结 IE47，不重算）；行情层状态（读 B4_PCT2 缓存）；v0 master 与其他已登记系统（只读缓存与 WF00 漏斗，不重放）；任何网格或参数扫描 |

## 3. 步骤

### 3.0 轮前

1. `df -B1 /` 记下轮前磁盘剩余；`free -m`。
2. 核对规则指纹与 `state.json.rule_fingerprints` 一致（六个文件）；不一致就写“规则漂移”停下。
3. 运行 `.venv/bin/python -m studies.trader_replication.datasets check --config studies/martin_luk/workflow/config.json` 与 `.venv/bin/python -m studies.trader_replication.profile check --config studies/martin_luk/workflow/config.json`，都要返回 0。

### 3.1 先写执行时点单测（在任何候选运行之前，先让它们通过）

`studies/martin_luk/tests/test_wf01_joint.py` 至少覆盖（用合成数据）：

1. C1 关闭时，新 book 与 `ie47_e1.entry_book(..., **E6['E6c'])` 加 C062 后处理的输出逐项相同。
2. C1：点名夜 t，第一次突破 d1 与同窗后续突破 d2（d1<d2≤t+5）都生成入场且观察编号相同；t+5 之后不生成；止损只用 ≤d 的低点与 d−1 的 ADR；改动 d 之后的 K 线不改变 d 及以前的入场（无未来函数）。
3. C1 + 引擎：d1 成交 → d2 被 `episode_limit` 挡掉；d1 因 `max_open` 被挡 → d2 成交；d1 因 `daily_long` 被挡 → 次日 d2 成交；d1 成交后当天被止损 → d2 不成交（不是止损后再买）。
4. C1：第一次突破被 book 原规则拒绝的情况，观察照原规则结束。
5. C2：满仓时收盘入场卖掉持有 ≥3 日、涨幅 <2% 中最弱的一只，以当日收盘价含卖出费用成交后再开新仓；涨 ≥2% 或持有 <3 日的不被卖；没有可卖的就不开新仓；不突破 11 只上限。
6. C3：试仓市值 = min(risk × scale × 权益 / (2 × 止损宽度), 上限, 敞口余量)，risk=0.005 时比 0.0025 时正好加倍（未触上限时）；证实加仓后整笔止损风险不超过引擎的 `risk_budget`（老坑“加仓后止损没跟上”）。
7. 策略模块扫描：`wf01_joint.py` 源码不含 `legs_frozen`、`trades.csv`、`labels(`、`notes/`。
8. 三个组件全关时，新路径产出的账户与 v1 等价（比较口径同 3.2 第 1 条；单测里至少测小样本，完整比对放在 3.2）。
9. `entry_episode` 数组：不在任何观察窗口内的格子填 −1 哨兵；同一只票冷却后被再次点名，新一轮观察的编号与上一轮不同、成交计数重新开始。
10. “d1 因 `max_open` 被挡 → d2 成交”在 C2 关闭时测（否则会被换仓掩盖）。
11. 换仓已经卖掉旧仓、新仓却因其他原因没开成（仓位过小、敞口不足等）的情形：单测构造一次，断言行为与引擎现有语义一致；运行中逐次计数并在报告里列出（不改引擎）。
12. C1 后续突破的排序：同一天同一只票只有一个入场；后续突破的同晚优先级沿用该轮点名的 `(rank, born, code)`，与当天新点名的票一起按引擎原排序处理；单测断言排序键。

### 3.2 只读诊断 D0（不跑候选；计入 60 分钟）

1. **v1 等价性检查（带准入记录重放）**：照 `leverage_replay.run('C062','L2.8','weakest_first')` 的准备方式，加 `track=dict(entry_attempts=[])`，区间 2024-01-02…2025-12-31；和 leverage_replay 一样，先把 `retry_book` 返回的 metadata（`attempt`、`origin`）按 `(code, entry)` 补回 trades，再比。比较口径写死：
   - 权益曲线：2024-01-02…2025-12-31 每天逐位相同；
   - `exit ≤ 2025-12-31` 的成交：逐笔全部字段逐位相同；
   - 冻结账户里 2025 年入场、2026 年才退出的跨年成交（约 3 笔）：只比 `code`、`entry`、`kind`、`fill`、`stop` 以及日期 ≤ 2025-12-31 的 `executions`；截断重放中它们的 `why='end'` 与估值不比。
   - 若上述口径仍有差异，允许另跑一次到 2026-10-16 的同配置重放，只做与冻结账户的逐位比对（返回布尔与首个差异位置），**不读取、不报告任何 2026 数值**。
   不同就停。completion.json 中这一步标为 `equivalence_check`，不是候选。
2. 用 `funnel.measure` 按 `adapter.run('C062')` 的同样参数（pool、raw/filtered/offered = 本次 book、B4 状态、`entry_delay=1`）出带准入原因的漏斗；按 `status.py` 同口径（选择年、`peak_eve ≤ 2025-12-31`）复现 STATUS 的 v1 数：峰前持有 (4,7)、L0–L6 (1,4,1,5,10,2,5)。复现不了就停。
3. 逐段表（28 段，分年、分状态）：每个点名夜、观察窗口内每次突破、准入原因（`filled`/`max_open`/`daily_long`/`same_code`/仓位过小/敞口不足/观察已结束/冷却中）、被挡当天占着名额的持仓（证实与否、浮动 R、持有天数）、首仓与峰前仓位占权益比例、和测试台同段的对照（他的票 + 我们的执行 vs 我们的票 + 我们的执行，三层对照第二、三层）。
4. 全账户：名额满的天数与当时持仓构成；首仓、证实后最大仓位、峰前仓位分布；平均与最高总敞口；`e8_scale` 各档天数。
5. **可达上限先算**（静态、只算增量）：v1 中非峰前持有的已完成段里，满足“被点名 + 窗口内有一次被账户挡掉的突破”且
   - U_C1：C1 的 book 在同一窗口、峰前一日之前还有后续突破；
   - U_C2：被挡原因是 `max_open` 或敞口余量 <5%（`daily_long` 等其他原因不计），且被挡那一刻存在符合 C2 条件的可卖持仓；
   - 报 U_C1、U_C2、二者并集 U，按年、按状态。
   **若 U < `config.accept.merge.min_extra_legs`（读 config，当前为 3），不跑候选**：直接写报告和 completion.json（decision 用第 6 节的 branch 格式，原因 `reachable_upper_below_threshold`），STATUS 照抄。
6. D0 的结果写进 `rounds/WF01/work/d0_diagnosis.json` 与报告第 1 节；**这些结果只用来验证机制和决定是否跑，不改任何候选参数**。若 D0 显示某个组件的前提完全不存在（例如 U_C2 = 0 且名额从未在他的段上挡过），可以在预登记里**删去**含该组件的候选并写明数字，不能新增或改参数。

### 3.3 预登记 `rounds/WF01/PREREG_CN.md`（写在任何候选运行之前，写完记 SHA256，跑完不改）

内容：假设（第 0.2 节机制）、三个组件的原话与结构性理由、五个候选的完整参数、D0 摘要与可达上限、比较对象 v1 的全部数、判定函数与选择规则（第 4 节）、消融规则（第 5 节）、留出规则、计算上限、每个候选预计哪些段会变（只写机制，不写票名预期）。另须写明：

- 可预见的约束：C1/C2 会增加成交笔数，胜率、盈亏比可能因此离开 ±20%，使 `behaviour_items` 掉项而不通过；这是事先知道的风险，不因结果改口径。
- 跨年未决段（峰前一日在 2025-12-31 之后）从分母与 `peak_held` 剔除并单列，候选与 v1 同样处理。
- 每个候选都要报告（只报告，不作门槛）：各准入原因（`filled`/`max_open`/`daily_long`/`same_code`/`episode_limit`/仓位过小/敞口不足）被挡次数相对 v1 的变化；C1 后续突破成交的笔数、占用的每日名额，以及因此被挡的“首次突破”（含他的段）；每笔被 C2 腾掉的仓位是否已证实、腾仓后 20 个交易日的收盘变化（只用 ≤2025-12-31 数据，尾部不足标“截断”）；换仓已卖、新仓未开的次数。

### 3.4 跑候选（只到 2025-12-31）

逐个串行跑 W1A…W1E（预登记删掉的除外）：账户（L2.8、先减最弱）、带准入原因的漏斗、记分卡，记下每个的墙钟与峰值内存。全部区间 `'2024-01-02'…'2025-12-31'`，不跑 2026。

每个候选按下面的方式组织 `pipeline.accept` 的输入（v1 用同一段代码从 3.2 的重放生成）：

```python
record = dict(
    annual={'2024': dict(peak_held=..., **{'return': ...}),
            '2025': dict(peak_held=..., **{'return': ...})},
    selection=dict(behaviour_within=...,      # 两个选择年在 ±20% 内的有出处行为项数之和（funnel.behaviour_gap，容差读 config.hard_lines）
                   peak_weight_median=...),   # 选择年、peak_eve ≤ 2025-12-31、峰前持有段的峰前仓位/权益中位数
    uses_bar_turnover_selection=False)        # 选股仍是冻结 IE47
from studies.trader_replication.pipeline import accept
decision = accept('merge', record, v1_record, cfg)   # cfg = config.json 原样读入
```

`peak_held` 用截至 2025-12-31 已知的段（含晚买，与 STATUS merge 格同口径）；跨年 3 段单列、不计入。交易统计中 2025-12-31 仍持有的记为 `end`。传给 `accept` 的每个候选 record 和 v1 record 原样存进 `rounds/WF01/accept_inputs.json`（列入 `keep`），核对步骤据此重算。

## 4. 选择规则（预登记，跑完不改）

1. 合格：`accept('merge', 候选, v1, cfg)['status'] == 'accepted'`（即：选择年每年不亏；峰前持有合计比 v1 多 ≥3 段且每年不少；峰前持仓占比中位不降；行为项数不减；选股非 master 成交额排序）。阈值只从 config 读。
2. 合格者中取选择年峰前持有合计最多的；与最多者相差 <3 段（规则：+3 段以内是噪音）的都视为并列，并列时取组件数最少的，再取两年中较差一年收益较高的，再按编号。
3. 无人合格：decision 为 `branch`，不跑留出，STATUS 照抄（第 6 节）。“收益更好但峰前持有或行为没过”的候选只记作探索分支，报告里照写。

## 5. 消融（联动轮必做）

对选中者，逐个去掉其中一个组件各跑一次（已在 W1A–W1E 里的直接引用，缺的如“只 C2”“只 C3”补跑，只到 2025-12-31，不参与选择）。逐个报告该组件对选择年峰前持有（按年、按状态）、行为项数、峰前仓位中位、每年收益的贡献。

去掉某组件后以上四项**都不变差**（峰前持有合计不少、行为项数不少、峰前仓位中位不降、两年收益都不降），这个组件不进入新版本；新版本 = 选中者去掉这些组件。事先写死的回退：

- 新组合若已作为整体跑过（W1A–W1E 之一或已跑的消融配置），直接用它的 `accept` 判定；通过则它是 `W1_FINAL`，不通过则回退到被选中的整体候选。
- 新组合若没有作为整体跑过，整体再跑一次（只到 2025-12-31，计入 60 分钟）；通过则它是 `W1_FINAL`，不通过或时间不够则回退到被选中的整体候选，并在报告里写明。

最终版本记为 `W1_FINAL`，写明组件。

## 6. 留出、判定、STATUS

1. **留出一次**：只对 `W1_FINAL` 跑 2024-01-02…2026-10-16 连续账户，报告 2026（标“留出*”，并注明已多次查看、非独立样本外）的收益、峰前持有、行为；同时核对其 2024–2025 段与 3.4 的结果按 3.2 第 1 条的口径一致。留出结果不改变判定；若 2026 收益 < `hard_lines.annual_return_min`，在 completion.json 写 `holdout_return` 并标 `holdout_loss=true`（触发检查点）。
   - **只在 `W1_FINAL` 被接受时**，这一次留出同时按 `leverage_replay` 的 `annual` 口径出 L1、L2、L2.8 三档（同一 book、同一规则，只换 `capital.candidate_rules(..., profile, 'weakest_first')`），另加 L2.8 `pro_rata` 一档对照（与 v0/v1 的版本表一致）。L1、L2、pro_rata 只作对照，不进判定；三档都算同一次留出，不再另看。
2. **判定**：`completion.json.decision` = `accept('merge', W1_FINAL, v1, cfg)` 的返回**原样**（其中 `line` 保持 `'merge'`，不得覆盖；`versions.append` 要求 `decision.line == 'merge'` 且 `status == 'accepted'`）。轮次类型写在 completion 顶层：`line: "joint"`、`scope`（第 0.3 节表的“线 × 状态”列表）、`final_components`、`candidates`（每个候选的 accept 返回）、`selection_rule_trace`、`ablation`。
3. **被接受时**：
   - **新冻结缓存**，逐文件照 `rounds/WF00/work/base_c062_build.py` 的 schema 复刻，保证现有读取代码不改就能读：
     - `frozen/conversion/W1_FINAL/allocation.json`：与 `state.json.components.conversion` 同字段（`version`、`status`、`evaluation_system`、`options`、`source`、`source_date`、`rules_source`、`nomination`、`entry_observation`）；`options` 含全部原键并写出新值（`rotate_below`、`rotate_min_days` 等），`entry_observation` 写明 C1 的语义（5 晚观察、被账户挡掉不结束、每轮观察最多成交一次、`entry_episode_max=1`）。
     - `frozen/merge/W1_FINAL/account.json`（`dict(record=..., rules=...)`，与 C062 缓存同结构，record 为第 6.1 条的 L2.8 连续账户）+ `funnel.json`（`funnel.measure` 输出，同 C062 缓存结构）。
     - `frozen/trading/`：交易测试台若要建缓存，`frozen_cache.bench_score` 会逐年取 2024/2025/2026 的 `eq[-1]`，必须跑到 2026-10-16，这会多看一次留出。**本轮不建新的 trading 缓存**：含 C3 时，测试台只按 WF00 `bench_score` 同口径跑到 2025-12-31，结果只写进报告第 7.4 节；在 `workflow_issues` 记“交易线版本变化但测试台缓存需含留出年才能被 `bench_score` 读取，按规则第五节由交易线下一轮先建”。
     - 每个新缓存的 metadata 记实际生成命令（含 `systemd-run` 参数）、生成脚本路径与 SHA256、来源文件 SHA；不动已有缓存。
     - 建完后用 `frozen_cache.load(line, 'W1_FINAL')` 与 `adapter.cached(...)` 的同等校验路径实际读一次（`adapter.cached` 只认 state 中的版本，记账前读不了时，用 `frozen_cache.load` 读并逐项核对 `allocation.json` 与将写入 state 的组件内容一致），结果写进 completion。
   - 重出 `rounds/WF01/STATUS.json`：写一个只在本轮目录的生成脚本，**先用 v1 的冻结版本跑一遍，必须逐格复现 `rounds/WF00/STATUS.json`**（回归检查），再用新版本出 merge、conversion 各格（common 与 up/weak 状态格）；trading 格的 `frozen_version` 写新执行版本，`current` 用本轮到 2025-12-31 的测试台数，并标 `cache: "待建（交易线下一轮先建）"`；selection 格照抄 WF00 并保留指纹；`next_cell` 按规则第五节同一公式重算。
   - **完整 `rounds/WF01/version_entry.json`**：字段照 `versions.py::initial_entries` 与 `append` 的校验——`version`（下一个 v 号）、`name`、`role: "合并通过"`、`components`（regime、selection、trading、conversion 四项）、`capital_profile`（= config 的验收档）、`date`、`source_account`、`scorecard`（L1、L2、L2.8 三档 × 2024/2025/2026，`versions.FIELDS` 全部字段，来自第 6.1 条）、`deleverage_comparison`（L2.8 pro_rata）、`replay_source`、开关说明；另存 `rounds/WF01/version_rules.json`（含 `capital_profile`、`max_gross`、`margin_rate`、`maintenance`、`deleverage`）。生成后把 `versions.json`、`VERSIONS_CN.md` 复制到 `work/`，对副本调用 `versions.append(entry, completion, rules, ledger=副本, table=副本)` 自检通过（只改副本），自检结果写进 completion。不得留给记账步骤补算；本轮不改真正的 `versions.json`、`state.json`。
4. **未被接受时**：`rounds/WF01/STATUS.json` = WF00 的 cells 原样，`round` 改为 WF01，更新代码与数据指纹并核对冻结缓存 manifest 未变；`next_cell` 照抄。不建缓存、不写 version_entry。

## 7. 报告 `rounds/WF01/REPORT_CN.md`

先结论（白话、少数字），再细节：

1. D0：L3/L4 的真实准入原因逐段表、名额与仓位画像、可达上限 U。
2. 合并漏斗变化：每个候选与 v1 的 L0–L6（选择年、已知段），以及逐段“从哪层到哪层”。
3. 主尺与护栏（分状态 up / weak，pullback 写“未观测”）：峰前持有、早买、他的段平均 R 与盈亏比、峰前仓位中位、行为记分卡（胜率、盈亏比、笔数；持有天数只说明）、每年收益、最大回撤、平均与最高总敞口、追保次数、交易笔数、不同票数（“不能撒网”的参照）。
4. 各线自己的尺子（只参考，不否决）：衔接线“点到 → 早买 → 峰前持有”转化；（含 C3 时）交易测试台峰前持有、他的段平均 R、对照票合计（只到 2025-12-31）；选股线照抄 IE47。
5. 消融表（第 5 节）。
6. 开关对照（只报告，不选择，只到 2025-12-31）：对 `W1_FINAL`（无人合格时对 W1D）分别跑 `e8_scale` 开、关、以及“B4 弱势态风险 ×0.5、上升态 ×1”三种，列按年、按状态的收益、回撤、峰前持有、敞口差值，回应目标第 8 条“按什么开关来”。这三次计入 60 分钟；时间不够就只跑开/关两种并写明。
7. 留出*（只 W1_FINAL）。
8. 目标逐条对照（config.goal 全部 8 条）：本轮怎样更接近、哪条没动、哪条更远；明确不改尺子、不放宽阈值、不以 master 为底座、不混评两条线。
9. 档案对齐表：capital（档位、杠杆上限、维持线、减仓方式、单只上限、同时持仓数；C3 的依据是规则第三节交易线“做多大”，在 L2.8 档内）、regime（未用于执行）、behaviour_card 各项、hard_lines 各项、选择年/留出年/段表 SHA，逐项写“在范围 / 不在范围 / 无法判定”和依据。
10. 与旧轮次的差别（E16、E17、E19、H2、E8/E13、BH1/BI1），以及本轮失败时差在哪一层（数据、执行方式、规则、运气），不写全称否定。
11. 下一轮建议（只建议，不跑）。

## 8. 测试与扫描（轮末都要过，日志放 `rounds/WF01/logs/`）

```bash
cd /opt/opend-us-options/.claude/worktrees/gap-review
python3 -m unittest discover -s custody/tests
.venv/bin/python -m unittest discover -s studies/trader_replication/tests
.venv/bin/python -m unittest discover -s studies/martin_luk/tests
.venv/bin/python -m studies.trader_replication.datasets check --config studies/martin_luk/workflow/config.json
.venv/bin/python -m studies.trader_replication.datasets scan --config studies/martin_luk/workflow/config.json --git-diff
.venv/bin/python -m studies.trader_replication.profile check --config studies/martin_luk/workflow/config.json
```

另核对轮后受保护文件（第 1 节列表）的 SHA 与轮前相同，写进 completion.json。

## 9. completion.json 与收尾

`rounds/WF01/completion.json` 至少包含：`task`、`round: "WF01"`、`line: "joint"`（顶层）、`scope`、`decision`（第 6 节，`accept('merge')` 原样）、`equivalence_check`（3.2 第 1 条）、`accept_inputs`（文件路径）、`new_caches`（被接受时：路径、manifest SHA、读回自检）、`version_entry_selfcheck`（被接受时）、`final_components`、`holdout`（有则含 `label: "留出*"`、`holdout_return`、`holdout_loss`）、`prereg_sha256`、各步墙钟与峰值内存、`tests`（每套通过数、返回码、日志路径）、`datasets_check`、`datasets_scan`、`profile_check`、`protected_files_unchanged`、`rule_fingerprints`（轮前、轮后）、`workflow_issues`（规则第七节：任务书写错或含糊、缺工具、规则冲突、尺子算不出；没有就空数组）、`keep`（下一轮或复算真正要用的文件，合计 ≤100MB）、`disk_free_before`、`disk_free_after`。

- 本轮可能出现、应写进 `workflow_issues` 的已知问题：联动轮判定借用 `accept('merge')`，`pipeline.accept` 没有 `joint` 分支；by_state 仓位开关在档案分状态行为“未观测”时接受条件算不出；`status.py` 只按 `state.json` 的冻结版本出表，联动轮需在记账前出新 STATUS。交易线版本变化时测试台缓存须含留出年才能被 `bench_score` 读取（本轮不建，见 6.3）；`adapter.cached` 只认 state 中的版本，记账前无法用它读新缓存。实际遇到才写，写清证据。
- 轮末删掉 `work/` 中不在 `keep` 里的文件；磁盘剩余低于 800MB 时先清本轮中间文件，还不够就停下报告，不碰本轮以外的东西。

下一轮建议（写进报告，不跑）：若本轮接受，下一轮回到漏斗里剩下最多的一层再定格（候选方向：选股线 L1 的 4 段“点名晚 / 未点名”；交易测试台 2025 上升态只有 2/7 峰前持有）；弱势态空头（regime.words 第 2 句）需要一份对应第 2 句的状态定义，属于行情层与档案的变更，应在检查点提给用户。

## 10. 审查补充（第 2 次审查通过后追加，与上文冲突时以本节为准）

1. **新缓存读回自检**（6.3）：不用 `frozen_cache.load`（它要求 `state.json.frozen_caches` 已有条目，记账前一定没有）。直接调用 `funnel.load_frozen(folder, 'W1_FINAL', *frozen_cache.identity(), line=line)` 校验指纹和各文件 SHA。
2. **version_rules.json**（6.3）：写 `dataclasses.asdict(最终 Rules)` 的全部字段，再加 `capital_profile`；不得只写资金字段，否则 `adapter.load_rules` 会补默认值（risk=0.0025、rotate_below=0 等），存下的规则就不是 W1_FINAL。
3. **等价性检查不算留出**：3.2 第 1 条的兜底（v1 另跑到 2026-10-16 只做比对）是第 1 节“2026 只对最终选中版本跑一次”的唯一例外：只返回布尔值和首个差异位置，不读、不写、不报 2026 的任何数字，completion 里标为 `equivalence_check`。
4. 第 2.1 节末“第 3.1 节的重放”应为“第 3.2 节的重放”。
5. **STATUS 回归**（6.3）：要求逐格复现 WF00 STATUS；复现不了就停下，把差异写进 completion.json，不出新 STATUS。
6. **P5 冷却层未动**：报告第 7 节写明本轮保留“同一轮观察内止损后不再买、10 晚冷却”；D0 顺带统计 L5（早买后被洗、之后没再买到）段数，供下一轮定格。
7. **后续突破占名额**：报告里把 C1 后续突破占用的每日名额、挡掉的首破笔数（含他的段），与 E17/E18 的“再试挤占名额”并排对照。
