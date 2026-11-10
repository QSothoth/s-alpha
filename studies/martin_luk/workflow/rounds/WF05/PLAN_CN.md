# WF05 任务书：联动轮（line=joint）——证实后收盘判止损 × 满仓换仓

> 本文件就是全部要求。规则以 `skills/trader-replication/references/WORKFLOW_CN.md` 为准，先完整读它；本书与它冲突时以它为准，并把冲突写进 completion.json 的 `workflow_issues`。
>
> 工作区 `/opt/opend-us-options/.claude/worktrees/gap-review`，不提交、不推送。交易员 martin_luk，流程目录 `studies/martin_luk/workflow`（下称 DIR），本轮目录 `DIR/rounds/WF05`。规则指纹见 `rules_pin.txt`（`79e4f1f282656d5e+6e2a56ea1e06ff47+81889204d1728986+af4618772ad79596`），本轮开头已重跑 datasets check、profile check，均通过（`measure.json`）。WF04 只有任务书和审查、没有运行，不进总账；为保留它的记录，本轮编号跳到 WF05。
>
> **执行环境**：Codex 单元由 `systemd-run -E PYTHONUTF8=1 -E LC_ALL=C.UTF-8 -E PYTHONDONTWRITEBYTECODE=1` 启动，环境已经设好（WF-074）。单元里的命令不必再写这三个变量，漏写也不算违规、不必停下。但自己另起的 python 子进程（含 `systemd-run --scope`）要带上 `PYTHONDONTWRITEBYTECODE=1`（见第 1 节）。第 1 节的“违反就停”只指实质约束。
>
> **版本说明**：
> - 第一版（只读诊断后建议进检查点）另存为 `work/PLAN_v1_checkpoint_before_review.md`。独立审查（`work/review1/`）推翻了它的静态口径，leader 决定开跑；第 0.2 节写了第一版错在哪。
> - 第二版另存为 `work/PLAN_v2_before_minor.md`。审查 1（`work/preflight_1.json`）没有致命问题，本版按它的 12 条次要意见 M1–M12 修改，格子、候选和参数都没有变。

## 0. 定格结论

### 0.1 先看全局：比较对象写死为当前合并主线 v1（IE47 选股 + C062 执行与分配）

来源：`DIR/rounds/WF00/funnels/C062.json` 与 `DIR/rounds/WF02/work/v1_funnel.json`（同一账户，WF02 `work/equivalence.json` 证明逐位一致）。accept 输入取 `DIR/rounds/WF01/accept_inputs.json` 的 `v1`：峰前持有 2024/2025 为 4/7，合计 11；行为达标 1 项；峰前仓位中位 0.10168106447651955；收益 +61.31%/+57.37%；`uses_bar_turnover_selection=false`。验收档 L2.8。

选择年已完成 28 段的持仓漏斗：

| 年 | L0 | L1 | L2 | L3 | L4 | L5 | L6 | 峰前持有（含晚买） |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 2024（9 段） | 0 | 1 | 1 | 2 | 2 | 1 | 2 | 4 |
| 2025（19 段） | 1 | 3 | 0 | 3 | 8 | 1 | 3 | 7 |

行为记分卡（±20% 内才算达标）：
- 2024：胜率 12.0%（他 24.6%）、盈亏比 8.55（他 5.00）、笔数 382（他 423，达标）；
- 2025：胜率 14.1%（他 22.2%）、盈亏比 12.58（他 6.71）、笔数 373（他 940）。

分状态账户收益：2024 年 up +79.2%、weak −10.0%；2025 年 up +60.5%、weak −1.9%；pullback 在选择年没有他的段，记“未观测”。

17 段没拿到峰前，按最早丢失的层：
- 选股线：L0 的 CRCL，L1 的 AMC、SMR、TSLA、ACHR；
- 衔接线：L2 的 QUBT；L3 的 GME（被每日新开上限挡）、SOUN、RGTI、AMPX、ASTS（被 max_open 挡）；
- 交易线：L4 买晚而且没拿到峰前的 TEM、UPST、FUTU、PL；L5 早买后被洗的 SMCI-2024-01、OKLO。

L4 共 10 段，其中 6 段的峰前持有已经计入。

### 0.2 损失落在哪几层，为什么做联动轮（按名额模拟器口径）

**名额模拟器**：`work/review1/slotsim.py`，只读，每次几秒，以下简称“模拟器”。
- 做法：按引擎顺序，把 v1 的 1124 次入场尝试（`DIR/rounds/WF02/work/v1_replay.json` 的 `entry_attempts`，即 IE47 的固定入场账本）逐次走一遍，只套三条准入规则：每天新开多头不超过 4（daily_long=4）、同票不重复（same_code）、同时持仓不超过 11（max_open=11）。
- 离场：每笔用 WF03 逐笔独立单票回放的离场日（`DIR/rounds/WF03/work/mechanism_replays.json`）。B0 那一组就是 C062 的离场；Q2 那一组是证实后收盘判止损。
- 不含权益、总敞口和追保。
- **复现**：用 B0 离场、不加别的规则时，逐笔复现 v1 的 755 笔成交（集合完全相等），峰前持有 4/7 也一样。本轮复核时又重跑了一次，结果相同。
- **局限**：用 W1E（C2 + 每笔风险 0.5%）校验时，模拟器多出 13 笔、少 6 笔成交，峰前持有是 5/7，实际是 5/8，差在 2025-10-13 的 RGTI。原因是 W1E 每笔风险 0.5%，有 12 次被总敞口挡住（`risk_or_gross`），模拟器没有总敞口这一层。所以本轮所有候选都用 C062 的每笔风险 0.25%（v1 的总敞口挡住次数是 0）。

模拟器算出来的关键数（`work/review1/scen1.py`、`scen4.py`）：

| 方案 | 峰前持有 2024/2025 = 合计 | 相对 v1 多的 / 少的段 | 行为达标 | 2024 笔数 | 总敞口代理最大值 |
|---|---|---|---:|---:|---:|
| v1（复现） | 4/7 = 11 | — | 1 | 382 | 2.05 |
| 只上 Q2 | 4/10 = 14 | 多 SMCI-01、TEM、FUTU、PL；少 LMND | **0**（2024 笔数 306 < 338.4） | 306 | 2.39 |
| Q2 + C2（换涨幅 <2%、持有 ≥3 天的仓位） | 5/10 = 15 | 多 SMCI-01、TEM、FUTU、PL；少 无 | 2（2024 笔数 341、2024 盈亏比 4.35） | 341 | 2.43 |
| Q2 + 只换从没到过 3R 的 | 4/10 = 14 | 多 SMCI-01、TEM、FUTU、PL、RGTI；少 IONQ-09、LMND | 5 | 361 | **3.06** |
| 只上 C2（C062 离场） | 5/7 = 12 | 多 QUBT | 1 | 388 | — |
| 只换从没到过 3R 的（C062 离场） | 5/8 = 13 | 多 QUBT、RGTI | 2 | 405 | — |
| 不限名额（诊断用，越出原话 11 只） | Q2 下 7/12 = 19；B0 下 6/9 = 15 | — | — | — | — |
| 每天新开上限 4 → 5、6、不限（Q2 下） | 都是 14 | 不是瓶颈 | — | — | — |

扰动检验（`work/review1/robust.py`）：随机去掉 2% 不属于他的段的入场尝试，种子 0–39，共 40 次。
- Q2 + C2：多出的段数平均 3.4，最少 2；95% 的扰动 ≥+3 且每年不少；97.5% 的扰动行为项不少于 v1；2024 笔数最少 316。
- Q2 + 只换从没到过 3R 的：平均 3.0，82.5% 的扰动 ≥+3 且每年不少；行为项全部不少于 v1。
- 只上 Q2：平均 2.8，75% ≥+3，但行为项每次都少于 v1。

所以损失落在交易（L4/L5）和名额（L3）两层，而且互相牵连：
- Q2 让 4 段（SMCI-01、TEM、FUTU、PL）拿到峰前；
- 但它拉长持有、减少笔数，会挤掉 LMND，并让 2024 笔数掉出行为范围；
- 换仓把名额让出来，同时把笔数补回来。

两边要一起改。这正是规则第二节的联动轮（line=joint）。

**第一版诊断错在哪（已作废）**：
- `work/diag_q2_congestion.py` 把本来因满仓进不了场的后续成交也算成占位，得出同时 12–16 只持仓。这超过了 max_open=11，不可能发生。
- 第一版还拿 WF03 测试台 T2 当名额占位的代表。但测试台每晚都喂他的票，占位里他的票有 92–156 次，而 v1 整账户只有 17 次，不能代表整账户的名额效应。
- 第一版的换仓“可得段 / 反向风险”是静态、不连锁的估计：被换出后还能再买回、后续名额会重排，它都没算。

上述文件只作错误记录保留，不作本轮依据。第一版里仍然成立的事实：
- 挡住他的票的 121 次占位里，106 次是已证实的仓位，101 次当晚已经 ≥+1R；
- 所以“试单、已证实分开占名额”没有用；
- 占位约 85% 是点名名次 0、1 的票，所以“每晚少点一只”是负的。

**占位持仓的状态（规则第五节，preflight M9）**：这些数来自模拟器，不加换仓；只统计他的票因 max_open 被挡的那些晚上、当晚占着名额的持仓（`work/wf05diag/occupancy_sim.py` → `occupancy_sim.json`）。B0 离场这一行与第一版 `diag_occupancy.json` 的 v1 数逐项相同，可作核对。

| 离场 | 他的票被挡（晚 / 段） | 占位次数 | 已证实 | 其中他的票 | 当晚 R 四分位 | 入场以来最高 R 四分位 | 持有天数四分位 | 当晚 ≥+1R | 最高 R ≥3 | 持有 <3 天 | C2 可换（其中他的票） | M3 可换（其中他的票） |
|---|---|---:|---:|---:|---|---|---|---:|---:|---:|---|---|
| B0（= v1） | 11 / 9 | 121 | 106 | 17 | 1.8 / 7.4 / 19.4 | 2.2 / 8.1 / 19.4 | 2 / 6 / 18 | 101 | 82 | 41 | 2（0） | 6（1） |
| Q2 | 15 / 13 | 165 | 149 | 21 | 2.6 / 8.7 / 21.5 | 2.8 / 9.1 / 22.7 | 3 / 11 / 25 | 140 | 123 | 40 | 4（0） | 12（0） |

可以看出：Q2 下占位拿得更久（持有中位 6→11 天）、更强。在他被挡的那些晚上，C2 和 M3 当晚能换的对象都很少（4 次、12 次）。所以换仓多出来的段，主要不是靠“在他被挡的那晚当场腾位”，而是靠平日持续换掉弱仓，让后来几晚的名额不再满——这是连锁效应，只有模拟器和整账户量得出来。

### 0.3 scope（改了哪些“线 × 状态”）

| 格 | 本轮 | 说明 |
|---|---|---|
| 交易 × common | Q2：证实后的止损线只在收盘判，开盘和盘中只认 2 倍硬止损 H = 成交价 − 2×(成交价 − stop0)；证实股数照原样 | WF03 已在全账本单票回放上放行（平均 R 1.73→3.02、≥5R 99→142 笔，`DIR/rounds/WF03/work/mechanism_release.json`） |
| 衔接 × common | 满仓换仓：C2，或“只换从没到过 3R 的”；J3 另加单只上限 0.30 | `capital.optimizable` 里的换仓、单只仓位上限；max_open=11、max_new_long=4、L2.8 档、追保时点和减仓方式（weakest_first）都不变 |
| 选股 × common | 不改，读冻结 IE47 | 不重算点名 |
| 行情层 | B4_PCT2 已冻结，只拆账 | 不用于执行，没有 by_state 修正（Q2 的得失在 up、weak 两种状态里都有，找不到逐字对应原话的拆分） |

每笔风险保持 C062 的 0.25%，不加 C3（W1E 证明 0.5% 会卡总敞口）。

### 0.4 对应的原话

出处是 `studies/martin_luk/notes/RULES_CN.md` ⑥⑦ 与 `TRANSLATION_CN.md`。

- Q2：“止损放在入场日低点……以收盘价判断”“收盘第一次跌破 9 EMA 清仓”，属全听或听一半的日 K 翻译。
- 换仓：“同时持仓设上限，新票要顶掉最弱的仓位才能进”（TRANSLATION 全听项“单只 25–30%，同时 3–4 只，最多 11 只”的做法栏）。“只换从没到过 3R 的”里的 3R，是他第一档减仓线（“3R/5R 或过度伸展时先卖 15%”）：到过第一档的仓位已经是赢家，不当作“最弱”。
- 单只上限：⑦“单只 25%–30%，小盘 20% 以下”。本轮只取上限端 30%，理由只有两条：对上原话，以及 J2 校准后的总敞口约 3.39，有碰追保的风险。它能不能降低这个风险，模拟器量不出来（见 0.7 节）。

### 0.5 同线同机制的旧轮次（读 `DIR/attempts.jsonl`），以及这次差在哪

| 旧轮次 | 当时 | 这次的差别 |
|---|---|---|
| IE21（11 只快砍） | 旧 master 系，未加仓试单 2/3/5 日没到 +0.5R 就砍，腾名额作用小 | 本轮不按时间砍。名额满时才换，而且和 Q2 成对 |
| WF01 W1E、WF02 W2A（C2 + C3） | C062 离场 + 换仓 + 每笔风险 0.5%：W1E 5/8=13、W2A 12；结论“名额给谁已到头” | 当时离场是 C062，换仓几乎没有对象（两年只换 13 次），新增段只靠名额。本轮的离场是 Q2：它把 4 段拿住了，同时多出一批涨幅 <2% 的已证实仓位，C2 正好把这些换掉（模拟器显示换 34 次），名额和笔数才回来。每笔风险回到 0.25%，避开 W1E 卡总敞口的问题 |
| WF03（Q2，交易线） | 测试台峰前 16→14，原因是名额 | 测试台每晚喂他的票，不评名额效应；本轮用整账户和名额模拟器评 |
| WF04（5 天没到 +1R 就走，未运行） | 审查否掉：占位的是赢家 | 本轮不按绝对门槛砍：C2 只在满仓时换；新规则保护到过 3R 的赢家 |
| WF02 C4（同日新点名优先） | 两年方向相反 | 本轮不改排序 |
| R39、R26（单只上限、总仓位） | 旧系统下的仓位档位研究 | 本轮单只上限只为控制 J2 的总敞口，不追求收益 |

### 0.6 触及的档案项（规则第九节，config.json 用户节）

- `capital`：只动可优化项，即换仓和单只仓位上限（0.50→0.30，只在 J3）。档位 L2.8、验收档、追保时点、max_open=11、max_new_long=4、减仓方式都不变。每个候选的规则都要过 `capital.check_rules(rules, cfg['capital'], 'L2.8')`。
- `behaviour_card`：逐年对照他的胜率、盈亏比、笔数（±20%）。
- `regime`：只拆账。
- `hard_lines`：胜率上限、每年笔数、对数收益差只报告。
- `goal`：第 7 节逐条对照。

没有越出档案范围的做法。同时持仓超过 11 只越出原话，不作候选。

### 0.7 可达上限与 accept 各项的起点差距（全部先于预登记，数字来自模拟器）

门槛一律由 config 和 v1 的值算出（preflight M8），本书不写死数字：
- 合计门槛 = v1 合计 + `cfg['accept']['merge']['min_extra_legs']`，当前为 11 + 3 = 14；
- 每年下限 = v1 的分年值（4 / 7）；
- 收益下限 = `cfg['hard_lines']['annual_return_min']`；
- 行为容差 = `cfg['hard_lines']['behaviour_tolerance']`。

| accept 项（`pipeline.accept('merge')`） | v1 起点 | 门槛（由 config 算） | J1 模拟预测 | J2 模拟预测（预筛后） |
|---|---|---|---|---|
| 选择年峰前持有合计 | 11 | v1 合计 + min_extra_legs | 15（扰动 95% 达门槛） | 14（扰动 82.5% 达门槛） |
| 每年不少 | 4 / 7 | ≥ v1 分年值 | 5 / 10 | 4 / 10（2024 年正好等于 v1，贴边） |
| 行为达标项不减 | 1 | ≥ v1 | 2：2024 笔数 341 只比下限 338.4 多 3 笔；2024 盈亏比 4.35，下限 4.0，模拟器对 v1 的盈亏比偏低约 4%。两项都贴边；行为项按两年合计，只剩一项也仍 ≥1 | 5 |
| 每年收益 ≥ annual_return_min | +61%/+57% | ≥ 0 | R 和代理两年都为正（305.6R / 1431.7R） | 正（855.5R / 1131.9R） |
| 峰前仓位中位不降 | 0.10168 | ≥ v1 | 代理值与 v1 代理值之比 = 1.00（0.1259/0.1259），边界风险。代理的绝对水平与实测不同（v1 代理 0.1259，实测 0.1017），只能看比值 | 比值 1.02 |
| 不用底线参照的成交额排序 | false | false | false | false |

总敞口：模拟器没有权益和总敞口。按 v1 校准，实测最大 2.264、代理 2.046，倍数约 1.107。J1 代理 2.43，校准后约 2.68，低于开仓上限 2.8。J2 代理 3.06，校准后约 3.39，高于追保线 1/0.30 ≈ 3.33，**碰追保的风险是真的**。

J3 的单只 30% 上限只在买入和加仓时起作用（引擎 `open_pos` 与加仓股数；账本条目本来就带 0.30），不会把已经涨上去的市值压回 30%。第二版的 `work/wf05diag/cap_gross.py` 按每日市值封顶算出“3.06→2.27”，**这是错误依据，已作废**。在买入和加仓时截断后重算（`work/preflight1/cap_buytime.py` → `cap_buytime.json`），J2 的总敞口代理最大值仍是 3.062，超过 2.8 的天数仍是 1，与不封顶完全相同。原因是代理用的是 0.5% 风险单票回放的一半仓位，买入时本来就到不了 0.25。**所以模拟器量不出 P30 的作用**：J3 的总敞口和追保没有预测值，只看整账户实测和消融（J2 对 J3）。

## 1. 硬约束（违反就停，写进 completion.json）

- 只用日 K 与冻结数据，不拉数据；只读 config `datasets` 白名单和经 `studies.trader_data` 派生的缓存；不新增、不修改数据集或 schema，也不引用未登记的数据路径。轮末跑 `datasets check` 和 `datasets scan --git-diff`。
- 策略代码不读他的台账、票名、日期、段表：新策略模块（`wf05_engine.py`、`wf05_joint.py`）里不得出现 `legs_frozen`、`trades.csv`、`labels(`、`notes/`、`legs`。段表只在评测里用（`funnel.measure`、`mainleg.leg_at`、模拟器的统计）。
- 受保护、不得改的文件：
  - 规则与判定：`WORKFLOW_CN.md`、`config.json`、`.claude/workflows/`、`studies/trader_replication/` 下全部代码（含 `pipeline.py`、`funnel.py`、`mainleg.py`、`allocation.py`、`system.py`、`regime.py`）、`trader_data/`；
  - Martin 的既有模块：`ie47_e1.py`、`e15_research.py`、`replicate.py`、`p3_research.py`、`wf01_joint.py`、`wf02_joint.py`、`wf03_engine.py`、`wf03_trading.py`，以及它们的测试；
  - workflow 目录：`DIR/*.py`、`state.json`、`attempts.jsonl`、已有 `frozen/` 缓存；
  - 其他：`DIR/rounds/WF00`–`WF04` 下全部文件、`DIR/rounds/WF05/work/review1/`、`work/wf05diag/`、第一版诊断文件，以及登记版与看板。
- **不得写 WF03、WF04 目录**。只许用 `importlib`（`spec_from_file_location`）按文件路径导入：
  - `DIR/rounds/WF02/work/run_wf02.py` 的 `prepared`、`measure`，和它模块里的 `R.accept_record`（`run_wf01.accept_record`）；
  - `DIR/rounds/WF03/work/run_wf03.py` 的 `prepare`、`score`（只用于第 6 节交易线测试台）。
  
  禁止调用 `equivalence()`、`export_book()`、`evaluate()`、`diagnose()`、`main()`、`measure_baseline()`，以及任何写 `WORK` 的函数（见 WF04 preflight M4）。
- **不写字节码**（preflight M10）：按路径导入旧轮次模块时，Python 默认会在 `WF01/work`、`WF02/work`、`WF03/work` 下写 `__pycache__`，这会违反受保护规定。因此：
  - 所有 python 进程都设 `PYTHONDONTWRITEBYTECODE=1`（或加 `-B`）；
  - `run_wf05.py` 等脚本在导入任何东西之前，先设 `sys.dont_write_bytecode = True`；
  - 轮前记下 `DIR/rounds/WF00`–`WF04` 的完整文件清单（`WF00/work/__pycache__` 原本就有，是在本轮之前生成的）；轮末核对：这五个目录没有新增、删除或修改任何文件，包括 `__pycache__`。
- **引擎**（规则第四节“改执行引擎”）：不改共享引擎，也不改 `wf03_engine.py`。新建 `studies/martin_luk/wf05_engine.py`：复制 `wf03_engine.py`，只新增“从没到过 3R”换仓的一个可选字段（2.2 节），默认关闭。先证明默认参数下与 `wf03_engine` 和 `system` 逐位一致（3.2 节）。
- 2024、2025 只用于选择；2026（留出*）只对最终版跑一次、只报告。
- 一次只跑一个重计算进程：`systemd-run --scope -p CPUQuota=60% -p MemoryMax=900M`，加 `OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1`。**全部计算合计不超过 60 分钟墙钟**，各步预算见第 3 节；轮末测试与检查不计。超了就停，写明停在哪、已完成什么。
- 候选跑完后又改了代码（含修 bug），受影响的候选全部重跑，旧结果保留并作废；报告列出改动与重跑清单。
- 中间文件只放 `DIR/rounds/WF05/work/`。测试设 `TMPDIR=$PWD/studies/martin_luk/workflow/rounds/WF05/work/tmp`，日志放 `DIR/rounds/WF05/logs/`。文档中文，代码英文。
- 磁盘剩余低于 800MB：先清本轮中间文件；还不够就停下报告，不碰本轮以外的东西。

## 2. 输入、组件、候选

### 2.1 整账户路径（写死；它在 WF02 里与 v1 逐位一致）

- `A, picks, policy = run_wf02.prepared()`：IE47 冻结点名，SHA 已在函数内核对；`policy` = `capital.candidate_rules(rules_for('C062'), cfg['capital'], 'L2.8', 'weakest_first')`。
- 入场账本：`book, _, policy, meta = wf02_joint.build(A, picks, policy, c2=False, c3=False, c4=False, c5=False)`。C2 不走 `build` 的开关，而在第 2.2 节的规则里设。账本与账户状态无关，各候选共用同一份。
- 模拟：本轮的 `work/run_wf05.py` 照 `run_wf02.simulate` 的写法（ema 键 `e9/e21/e8_scale/always`、起点 2024-01-02、`audit=True`、`track` 收 `entry_attempts`、成交补 `meta`），只把 `system.simulate` 换成 `wf05_engine.simulate`。选择年截止 `2025-12-31`；留出与版本总表截止 `2026-10-16`（与 `DIR/rounds/WF00/work/leverage_replay.py` 相同；留出前用 `run_wf01.prepare('2026-10-16')` 取面板，并先核对截至 2025-12-31 的部分与选择年面板逐位相同）。
- 量：`run_wf02.measure(A, picks, policy, book, record)` → `run_wf01.accept_record(measured, cfg)`。比较对象的 accept 记录必须等于 `DIR/rounds/WF01/accept_inputs.json` 的 `v1`。

### 2.2 组件（参数现在写死，跑完不改）

记号：w = 成交价 − stop0（stop0 为试单初始止损）。“当晚 R” = (当晚收盘 − 成交价)/w。“入场以来最高收盘 R” = (入场日到当晚的最高收盘 − 成交价)/w。持有天数 = 当晚交易日序号 − 入场日序号。

- **Q2**：`wf03_trading.trading_rules(base, q2=True)` 的输出，即 `confirmed_close_stop=True`；先 `dataclasses.asdict`，再构造 `wf05_engine.Rules`。WF03 已放行，本轮不重新放行。
- **C2**：引擎已有字段 `rotate_below=0.02, rotate_min_days=3`，和 WF01、WF02 相同。规则是：收盘有新多头要进场、但名额已满（或总敞口剩余不足 5%）时，在当晚收盘卖掉持有 ≥3 天、收盘涨幅 <2% 的多头中“收盘/成交价”最低的一只，再开新仓。
- **M3（新）**：只换从没到过 3R 的。`wf05_engine.Rules` 新增 `rotate_rmax_r: float = 0.0`；大于 0 时，与 C2 用同一触发点、同一成交时点（当晚收盘卖出、当晚收盘开新仓）。
  - 候选被换出的仓位：持有 ≥ `rotate_min_days`（=3）天，且入场以来最高收盘 R < `rotate_rmax_r`（=3）的多头；
  - 在其中选当晚 R 最低的一只；并列时先取入场早的，再按代码排序；
  - 与 `rotate_below` 互斥，两个都大于 0 就报错；
  - 只用当晚及以前的收盘；不看名额以外的信息，不看他的台账。
- **P30**：单只仓位上限 `max_position=0.30`（C062 为 0.50），只在 J3 用。

### 2.3 候选（3 个，不得新增候选或改参数）

| 候选 | 组件 | 用意 | 证据强弱 |
|---|---|---|---|
| J1 | C062 + Q2 + C2 | 收盘止损拿住赢家；C2 把多出来的、涨幅 <2% 的已证实仓位换掉，让名额和笔数回来 | C2 的形态和参数在 WF01 已写死，不是本轮预筛出来的 |
| J2 | C062 + Q2 + M3 | 同上，换仓对象改为“从没到过 3R、当晚最弱”的仓位 | **预筛后**：在选择年段表上试过 12 种换仓形态、13 组邻近参数后才选定，证据比 J1 弱 |
| J3 | C062 + Q2 + M3 + P30 | 按原话“单只 25–30%”加单只上限；J2 有碰追保的风险 | **预筛后**；总敞口和追保没有预测值（0.7 节） |

只上 Q2 的版本（A2）作为消融项，不作候选：模拟器显示它把行为项掉到 0，过不了 accept。

### 2.4 组件放行依据（规则第五节；规则现在写死）

- Q2：WF03 已在全账本单票回放上放行。
- C2：作为已有组件上场，不重做放行。理由有三条，**必须原样写进预登记**（preflight M2）：
  1. 规则第五节的放行适用于“从少数几段的准入或成交记录里想出来的组件”。C2 的形态来自原话“新票顶掉最弱”，参数 `rotate_below=0.02`、`rotate_min_days=3` 在 WF01（2026-11-09）就写死了，早于放行规则（WF-048 在 WF02 才有）；WF02 也把它当已有组件，没有重新放行。
  2. 在 C062 离场下，它按本轮同一口径勉强能过：新进入场 −23.1R，放弃的收益 −25.0R；≥5R 净 0 对 0（`work/wf05diag/release_preview.json` 的 `B0|C2_pct2`）。
  3. 在 J1 里，C2 的定位是“像他、但伤 R”的组件：它让 2024 笔数从 306 回到 341，并保住 LMND-2024-11，不是为了 R。对应 goal 原话“可以放入单看是负向、但更像他的人性条件”（2026-11-08）。
  
  预登记同时写明：**它在 Q2 下按同口径不通过**。数字是新进入场 −212.5R，放弃的收益 −106.6R，合计约 −106R；≥5R 净 2 对 3。报告要给出它在整账户上的 R 代价（3.5 节换仓那一项、消融 A2 对 J1），并按 goal 逐条对照。这个不对称写进 workflow_issues。
- M3（新组件）：在**对齐同一组入场的带名额回放**上放行。工具是名额模拟器：先复制 `work/review1/slotsim.py` 的逻辑到 `work/slotsim_wf05.py`，并先断言 B0 离场逐笔复现 v1 的 755 笔。
  - 同一份 IE47 入场账本、同一组 Q2 单票离场，对比“Q2 不换仓”与“Q2 + M3”两次回放，只计入场日 ≤2025-12-31 的成交。
  - 分两部分算，不用总笔数、总和这类门槛：
    - (1) 被换出仓位放弃的收益：每只被换出的仓位，单票全程的 R 减去在换出当晚收盘卖出时的 R（含加仓，按它自己的 R 单位）；以及其中原本 ≥5R、卖出时 <5R 的笔数；
    - (2) 新进入场的净效果：“Q2 + M3”比基准多出的成交的 R 之和，减去被连锁挤掉的成交的 R 之和；≥5R 的笔数同样相减。
  - **通过条件**：(2) 的 R > (1) 的 R，且 (2) 的 ≥5R 净数 ≥ (1) 的 ≥5R 笔数。两年合计判定，分年报告。持平（R 相等）不算通过。
  - 预览值（本书写作时已算出）：(2) +1031.8R、≥5R 净 25；(1) 放弃 635.1R、14 笔。按 Q2 判，通过。另报告 C062 离场下的同一预览，只作信息：+40.4R 对 208.6R，不通过——M3 只在 Q2 下有用。
  - Codex 用复制后的工具重算。结果与预览不一致时，以重算为准，并写明差异；M3 不通过，就删掉 J2、J3，只跑 J1。
  - M3 是预筛出来的（preflight M3），预登记必须披露：`work/review1/scen3.json`（24 行：B0、Q2 两种离场 × 12 种换仓形态）和 `scen4.json`（19 行：C2、M3 附近的邻近参数与组合）的完整列表，每行写峰前持有分年与合计、多出与少掉的段、行为项代理、2024 笔数。还要写明邻近参数并不稳：只换没到过 2R 的是 16 段，没到过 5R 的只有 10 段。不改参数，也不加候选。
- P30：理由只有原话“单只 25–30%”和 J2 碰追保的风险。它只限制买入、证实加仓和信号加仓，不改离场、不改准入。**模拟器量不出它的作用**：在买入和加仓时截断后，J2 的总敞口代理不变（`work/preflight1/cap_buytime.json`）；第二版引用的 `cap_gross.json`（按每日市值封顶）是错误依据，不得写进预登记。预登记写明“J3 的总敞口与追保没有预测值”，J3 的实际作用只看整账户和消融（J2 对 J3）。

## 3. 步骤与计算预算（合计 ≤60 分钟）

### 3.0 轮前（不计时）

- 记下 `df -B1 /` 与 `free -m`；
- 核对规则指纹与 `state.json.rule_fingerprints`、`rules_pin.txt` 一致；datasets check、profile check 返回 0；
- 确认没有别的重计算在跑（`systemctl list-units 'codex-*'` 等）；
- 记下受保护文件的 SHA256，轮后再核一次。

### 3.1 先写执行时点单测（任何候选运行之前，先全部通过；不计时）

单测放在 `studies/martin_luk/tests/test_wf05_joint.py`，用合成小面板：

1. `wf05_engine.simulate` 在 `rotate_rmax_r=0` 时，与 `wf03_engine.simulate` 逐位一致（含 Q2 开、C2 开的组合）。
2. M3：
   - 满仓且有新收盘入场时，在当晚收盘卖出被选中的仓位，成交价为当晚收盘；新仓也在当晚收盘成交；
   - 持有 <3 天的仓位不被选中；
   - 入场以来某天收盘到过 +3R 的仓位，即使当晚回落到 <3R 也不被选中；
   - 只有盘中最高价到过 3R、收盘没到的，仍可被选中；
   - 多个候选时选当晚 R 最低的，并列先取入场早的；
   - 修改当晚之后的 K 线，当晚及以前的决策不变（无未来函数）；
   - 当天已达每日新开上限，或该票已持有（same_code）时，不触发换仓、不卖出任何仓位（不白卖）；
   - `rotate_below` 与 `rotate_rmax_r` 同时大于 0 时报错。
3. C2 与 Q2 同时开：同一收盘某仓位既触发 Q2 的收盘止损又是换仓候选时，先按止损离场（离场循环先于收盘入场）；名额因此空出时，不再换别的仓位。
4. P30：加仓股数不让单只市值超过权益的 30%。
5. M3 与 Q2 同时开、同一收盘（preflight M7）：某仓位按 Q2 收盘止损离场后，名额已经不满，就不换仓；名额仍满时，才从剩下的仓位里按 M3 选对象。离场循环先于收盘入场。
6. M3 由总敞口剩余不足 5%（`short_room`）触发：名额没满、但总敞口剩余不足权益的 5% 时，与 C2 一样触发换仓，选对象的口径不变。
7. 换出之后新仓没开成（风险无效、总敞口不足等）：照引擎现有 C2 的行为实现，不另改。单测要写明并断言实际行为（被换出的仓位是否已卖出），在 `completion.json` 的 `engine_copy_diff_summary` 里说明。
8. 扫描策略模块：`wf05_engine.py`、`wf05_joint.py` 不出现第 1 节列的禁用串。

### 3.2 等价性与工具复现（预算 6 分钟，不算候选）

任何一项不一致就停。所有逐位对照都比完整的 `track`（`entry_attempts`、`proof_orders`、`margin`、`gross`、`open`、`new`），外加曲线和成交（preflight M7）：

1. 按 2.1 路径，`wf05_engine` 默认参数跑 C062，与 `system.simulate` 的结果逐位相同，并与 `DIR/rounds/WF02/work/v1_replay.json` 逐位相同（record 和 track）。`measure` 后的 accept 记录等于 `WF01/accept_inputs.json` 的 `v1`，漏斗 L0–L6 等于 `WF02/work/v1_funnel.json`。
2. `wf05_engine` 跑 C2+C3（`risk=0.005`），与 `DIR/rounds/WF02/work/w1e_replay.json` 逐位相同，检查 C2 路径。
3. `wf05_engine` 与 `wf03_engine` 开 Q2，在**交易线测试台输入**上逐位相同：输入用 `run_wf03.prepare()` 返回的 `A`、`offered` 和 B0 规则，**不用整账户**，以免在预登记前看到消融 A2 的整账户结果。
4. **J1 规则**（Q2 + C2，不含新代码）在 `wf03_engine` 与 `wf05_engine` 上，用同一份真实测试台输入（同第 3 条）跑，结果逐位相同。
5. 名额模拟器 `work/slotsim_wf05.py` 用 B0 离场复现 v1 的 755 笔与峰前持有 4/7。
6. 记下 `wf05_engine.py` 与 `wf03_engine.py` 的 diff 摘要，只许有 M3 字段与它的分支。

### 3.3 诊断与放行（预算 5 分钟）

- 用 `slotsim_wf05.py` 重算 0.2 节表（v1、只上 Q2、J1、J2）的模拟预测：峰前持有分年、多出与少掉的段、换仓次数、行为项代理、总敞口代理（× 1.107 校准值一并写出）。J3 只写“总敞口无预测值”，不用模拟器算它的总敞口（0.7 节）。另重算 0.2 节的占位状态表（B0、Q2 两种离场）。写进 `work/d0_sim.json`。
- 按 2.4 节算 M3 的放行和 C2 的预览，写进 `work/release.json`。
- 可达上限写进 `work/reachable.json`，包括三部分：
  - 模拟预测的峰前持有；
  - 40 次扰动的分布（照 `review1/robust.py`，随机去掉 2% 不属于他的段的入场尝试，种子 0–39 写死）；
  - 另一组只读扰动（preflight M11，只报告，不作门槛）：每次随机挡掉 1%–2% 的成交，不分是不是他的票，比例在 [0.01, 0.02] 均匀抽取，种子 100–139 写死，用来近似整账户特有的摩擦（总敞口挡入场、证实加仓被挡后离场改变）。
- **某候选的模拟预测合计 < v1 合计 + `cfg['accept']['merge']['min_extra_legs']`，或任何一年低于 v1 的分年值，就不跑该候选**；门槛在代码里从 config 和 v1 accept 记录算出，不写死数字（preflight M8），并写明数字。全部候选都不跑：decision 记 branch，原因写 `reachable_upper_below_threshold`，STATUS 照抄。

### 3.4 预登记 `DIR/rounds/WF05/PREREG_CN.md`（不计时）

在任何候选的整账户结果出来之前写好，记 SHA256 写进 `work/prereg.sha256`，跑完不改。内容包括：
- 假设：Q2 拿住 4 段，换仓腾回名额和笔数；
- 原话、组件参数、0.7 节的起点差距；
- 放行结果与数字、可达上限；
- 比较对象 v1 的 accept 记录（原样贴）；
- 第 4 节的选择规则、第 5 节的消融规则、留出规则、计算预算；
- 可预见的代价：
  - J1 的 2024 笔数只比下限多 3 笔，峰前仓位中位与 v1 的代理值相等，两项都是边界风险；
  - Q2 的证实后失败笔会放大到约 −8R 至 −16R（WF03 已标注）；
  - J2 的总敞口可能碰到 2.8、触发追保。
- 只标注、不否决的规定：单笔亏损占权益的中位数或最大值超过 2%，标“风险超原话”；追保次数 >0，标“碰追保”。
- C2 的三条豁免理由和它在 Q2 下不通过的数字（2.4 节，preflight M2）。
- 全部预筛结果：`review1/scen3.json`、`scen4.json` 的完整列表；J2、J3 标为“预筛后”，接受时证据比 J1 弱（2.4 节，preflight M3）。
- J3 的总敞口与追保没有预测值；第二版引用的 `cap_gross.json` 是错误依据，作废（0.7 节，preflight M1）。
- 已知的预测不确定性，不作门槛（preflight M11）：
  - 模拟器没有总敞口挡入场，也没有“证实加仓被挡导致离场改变”（W1E 校验最早的差异是 2024-01-19 的 NCLH、SNAP 被总敞口挡，另有 TDS、RKLB 两笔离场不同）；
  - 单票回放按 0.5% 风险跑，账户是 0.25%，`max_position` 卡住的范围不同（前者在 w<4% 时卡住，后者在 w<2% 时），R 和收益代理在这些票上有偏差；
  - 2% 去入场的扰动是单向的，只会减少拥挤；
  - J2 在不加摩擦时只有 82.5% 的扰动达到门槛。

### 3.5 跑候选（预算 12 分钟；每个候选整账户到 2025-12-31 加量漏斗，约 1–3 分钟）

串行跑通过 3.3 的候选。每个候选：
- 过 `capital.check_rules`；
- 出 accept 记录与 `pipeline.accept('merge', 候选, v1, cfg)` 的原样返回；
- 另出：漏斗 L0–L6（分年、分状态）、逐段层变化（相对 v1）、他的段平均 R 与盈亏比、峰前仓位中位与合计、行为记分卡（分年、分状态）、每年收益与最大回撤；
- 分状态收益（B4_PCT2，up、weak；pullback 写“未观测”）、最高与平均总敞口、追保次数；
- 换仓次数（他的票被换出、对照票被换出分开计），被换出仓位放弃的 R 与新进入场的 R（同 2.4 节口径，但用整账户的实际成交）；
- 准入原因计数（filled、max_open、daily_long、same_code、risk_or_gross），他的票被名额挡的次数；
- 资金纯度（他的段占用资金比例，只报告）、超预算亏损分布；
- **模拟器预测与整账户实测逐段对照**：哪些段预测拿到、实际没拿到，或反过来；差在哪一层；
- **逐项“预测 / 实测 / 差”表**（preflight M6）：每个候选和每个消融各一行，存进 `work/sim_vs_account.json`，列如下：

  | 列 | 内容 |
  |---|---|
  | 峰前持有 | 2024、2025、合计，各写模拟预测、整账户实测、v1 实测、差 |
  | 行为 | 达标项数；2024、2025 的胜率、盈亏比、笔数，各写预测、实测、他本人、是否在 ±容差内 |
  | 每年收益 | 预测（R 和代理，只看符号）、实测 |
  | 峰前仓位中位 | **只比“候选 ÷ v1”**：代理比（候选代理 ÷ v1 代理 0.1259）与实测比（候选实测 ÷ 0.10168）各一列，不比绝对值 |
  | 总敞口 | 代理 × 1.107 与实测最大值、追保次数（J3 写“无预测”） |
  | 换仓 | 模拟换仓次数与实测换仓次数 |

- 墙钟与峰值内存。

所有记录原样存进 `DIR/rounds/WF05/accept_inputs.json`。

## 4. 选择规则（预登记，跑完不改）

1. 合格：`pipeline.accept('merge', 候选, v1, cfg)['status'] == 'accepted'`，阈值只读 config，返回原样记录。合格条件就是 accept 的全部检查，不另加门槛，也不放宽。
2. 并列组的定义（preflight M4）：先找合格者中峰前持有合计最多的值 M；凡与 M 相差不到 3 段的合格者，组成并列组（3 = `cfg['accept']['merge']['min_extra_legs']`，代码里从 config 读）。组内依次比：行为达标项多的 → 组件少的 → 两年中较低一年收益高的 → 按编号 J1、J2、J3。
3. 无人合格：decision 为 branch，不跑消融、不跑留出，不建缓存，STATUS 照抄。峰前持有更多但没过某一项 accept 的，记作探索分支，写明差在哪一项。

## 5. 消融与回退（预算 10 分钟）

选中者必须做消融，逐个去掉一个组件各跑一次整账户（到 2025-12-31，同口径量）：

| 选中者 | 消融 |
|---|---|
| J1 | A1 = C062 + C2（去 Q2）；A2 = C062 + Q2（去 C2） |
| J2 | A3 = C062 + M3（去 Q2）；A2（去 M3） |
| J3 | A4 = C062 + M3 + P30（去 Q2）；A5 = C062 + Q2 + P30（去 M3）；J2（去 P30，已跑过则复用，并核对规则 SHA） |

报告每个组件对以下各项的贡献：峰前持有（分年、分状态）、行为记分卡、峰前仓位中位、每年收益、总敞口与追保。

去留规则（与规则第四节“去掉后不变差的组件不进入新版本”一致，preflight M5）：

- 去掉某组件后，以下全部不变差，该组件“可去”：峰前持有合计不少、每年不少、行为达标项不少、峰前仓位中位不降、每年收益不降。
- 没有可去组件：最终版 = 选中者。
- 有可去组件：从已经跑过的“去掉一个”组合里，取去掉的是可去组件的那些，按第 4 节第 2 条的并列比较取一个，作为最终版。不加跑新组合，不整体回退。它的 accept 每一项都不比选中者差，所以必然也过 accept；但仍原样记录它的 `accept('merge', ·, v1)` 返回。
- 两个及以上组件各自可去时，最终版只去掉其中一个（按上一条取），并报告组件之间的交互：同时去掉会怎样没有跑过，不作推断。这个情况写进 workflow_issues。
- 消融得出的组件集只能是选中者的子集。

## 6. 留出、判定、版本、缓存、STATUS（预算 20 分钟）

1. **留出一次**：只对最终版，跑整账户到 2026-10-16。报告 2026 的峰前持有、早买、收益、最大回撤、胜率、盈亏比、笔数、追保，并引用 v1 的 2026 数（`DIR/VERSIONS_CN.md`：峰前 1/17、收益 −14.3%）。
   - **2026 的量法写死**（preflight M12）：`run_wf02.measure` 把 CUTOFF 写死为 2025-12-31、段只取选择年，不能直接复用。在 `work/run_wf05.py` 里写 `measure_holdout`：照 `run_wf02.measure` 的写法调用 `funnel.measure`，`pool`、`cards`、`tolerance`、`entry_delay=1`、`raw/filtered/offered=book` 都不变；段只换成“首锚点在 2026、且峰前一日 ≤ 2026-10-16”的那些。
   - 先用这个函数重算 v1 在 2026 的数（C062 整账户到 2026-10-16），应得峰前 1/17；一致了才量最终版，不一致就停下并写明。
   - J2、J3 是预筛后的候选；若最终版是它们之一，报告的留出*一节单列它们的表现，并注明“预筛后，证据较弱”（preflight M3）。
   - 留出结果不改判定、不进入下一轮设计。
   - 2026 收益 <0 时，在 completion 的 `checkpoint` 写 `holdout_loss`（规则第五节检查点）。
   - `holdout` 字段写 `label: "留出*"`、`holdout_return`、`holdout_loss`。
2. **判定**：`completion.json.decision` 原样保留 `pipeline.accept('merge', 最终版, v1, cfg)` 的返回。无人当选时写 `{"status": "branch", ...}`，并另存每个候选原样的 accept 返回到 `candidate_decisions`。顶层写 `line: "joint"`、`scope`（照 0.3 节）、`final_components`、`candidates`、`released`、`selection_rule_trace`、`ablation`。
3. **被接受时**（新版本号 **v2**）：
   - **L1、L2 对照**：最终版在 L1、L2 档各跑一次到 2026-10-16（`capital.candidate_rules(rules, cfg['capital'], 档, 'weakest_first')`），与 L2.8 一起组成版本记分卡。
   - **交易线测试台**（若最终版含 Q2）：照 `run_wf03.prepare()` 加 `execute` 的写法，在 WF03 的 float64 路径上把引擎换成 `wf05_engine`，跑最终版的交易规则（不含换仓与 P30），到 2026-10-16。用 `run_wf03.score` 出选择年的 `training` 块，作为 STATUS 交易格。
   - **冻结缓存**：用 `frozen_cache.save`（只调用，不改模块）建 `frozen/<线>/WF05_<候选号>/`：
     - 交易线（含 Q2 时）：`inputs.json`、`prices.json` 与 C062 相同，`account.json` 为测试台记录与 `check_rules` 之后的完整 rules；
     - 衔接线（含换仓或 P30 时）：`allocation.json`，结构照 `frozen/conversion/C062`；
     - 合并：`account.json` 为 L2.8 到 2026-10-16 的整账户记录，`funnel.json` 为选择年漏斗。
     
     metadata 写明 `engine: studies.martin_luk.wf05_engine` 及其 SHA256、`wf05_joint.py` 与 `wf03_trading.py` 的 SHA256、实际命令、脚本 SHA256。在 `work/` 里写读回函数直接读新缓存，核对 manifest 里各文件的 SHA，accept 记录与候选记录一致。不得为读回而改 `frozen_cache.py`、`adapter.py` 或 `state.json`。
   - **版本总表**：按 `versions.py` 的 schema 写 `work/version_entry_v2.json`：`version: "v2"`、`role: "合并通过"`、`components`（regime B4_PCT2、selection IE47、trading、conversion 各写新冻结版本名或沿用 C062）、`capital_profile: "L2.8"`、L1/L2/L2.8 × 2024/2025/2026 的完整记分卡、`source_account`、`date`。然后运行 `python -m studies.martin_luk.workflow.versions append --entry … --completion … --rules …`，它会追加 `versions.json` 并重出 `VERSIONS_CN.md`。这是本书授权的写入，不算违反受保护文件规定。
   - **state_patch**：写 `DIR/rounds/WF05/state_patch.json`，包括：`components.trading`、`components.conversion`、`components.merge` 的新条目（version、status、rules_source、rules_sha256、engine 模块与 SHA256、accepted_on、accept 原样），以及 `frozen_caches` 的新条目（path、`manifest_sha256`、bytes）。**不改真正的 `state.json`**，由记账步骤写入。
4. **STATUS**：重出 `DIR/rounds/WF05/STATUS.json`。
   - 被接受时：交易格（common、up、pullback、weak）用新测试台；衔接格与合并格用新整账户漏斗。口径与 `DIR/status.py` 和 `DIR/rounds/WF03/STATUS.json` 相同；`frozen_version` 写新版本；`round` 写 WF05。
   - 选股格、行情格照抄 WF03 STATUS，保留指纹；`pending_merge: false`。
   - 未被接受时：全表照抄 `DIR/rounds/WF03/STATUS.json`，`round` 改为 WF05，更新规则指纹。

## 7. 报告 `DIR/rounds/WF05/REPORT_CN.md`

先写白话结论，再写细节：

1. 诊断：模拟器复现证明，第一版静态口径作废的原因，放行（M3 两种离场下的数字，C2 的预览与不对称），可达上限与扰动分布。
2. 合并验收各项：逐条照抄 accept 的 checks，分状态（up、weak；pullback 未观测）列出峰前持有、行为、收益与回撤。
3. 合并漏斗 L0–L6：每个候选和消融相对 v1 的变化，逐段层变化表。
4. 每年收益：L2.8 为准，另列 L1、L2（只对最终版）。总敞口、追保、资金纯度。
5. 各线主尺与护栏（只作参考，不作否决）：交易线测试台的峰前持有、他的段平均 R、已平仓对照票 R 之和（若跑了）；衔接线“点到 → 早买 → 峰前持有”的转化；选股线照抄冻结值。
6. 模拟器预测与整账户实测的差：照 3.5 节的逐项“预测 / 实测 / 差”表和逐段对照，每条偏差归到下面某一类摩擦：总敞口挡住入场、证实加仓被挡导致离场改变、权益复利、`short_room` 触发的额外换仓、0.5% 与 0.25% 风险下 `max_position` 卡住范围不同；归不进去的单列。并报告 1%–2% 挡成交扰动的分布（preflight M6、M11）。
7. 消融表。
8. 留出*（只最终版）。
9. hard_lines 底线项逐年报告：胜率上限、每年笔数、对数收益差（“收益不能差太多，尤其 2025”），只报告。
10. 档案对齐表：capital 各项、逐笔亏损占权益比例的分布与原话“每笔约 0.5%”并排、behaviour_card、regime 未用于执行、hard_lines、选择年、留出年、段表 SHA。
11. 用户目标逐条对照：config.goal 全部 8 条，说明本轮怎样更接近；写明没有改尺子、没有放宽阈值、没有把 master 当底座、没有混评两条线、W1E 只作诊断。
12. 与旧轮次的差别（0.5 节表）；失败时差在哪一层。
13. 下一轮建议，只写不跑。

## 8. 已知流程问题（Codex 原样写进 completion.json 的 `workflow_issues`，执行中新发现的追加在后）

1. **工具缺失（通用）**：名额排队模拟器（按引擎顺序走固定入场账本，只套准入规则，离场用单票回放）应成为正式工具，并写进规则第五节“腾名额类方案先量占位”：可达上限用它的连锁结果算，禁用静态占位叠加。证据：本轮第一版静态口径得出 12–16 只同时持仓，误判进检查点；模拟器逐笔复现 v1 的 755 笔。
2. **尺子缺陷（通用）**：任何占位估计都要做合理性检查：同时持仓数不得超过 `max_open`，超过就判工具错误。
3. **规则不清（通用）**：交易线测试台每晚喂他的票，他的票占位次数（92–156 次）远高于整账户（17 次），不能用来评名额效应。规则第四节交易线应写明“测试台不评名额”。
4. **尺子缺陷（通用）**：换仓的反向风险不能当作整段丢失。被换出后还可能再买回，名额也会重排，要以模拟器的连锁结果为准。
5. **规则不清（通用）**：进检查点的否定结论，也要做一次独立、对称的复核（同样查实现错误和口径错误），再停下。WF05 第一版就是因为口径错误差点误停。
6. **规则不清（通用）**：已有组件（C2）在下游换了离场（Q2）后，按新组件的放行口径不通过（新进入场 −212.5R 对放弃收益 −106.6R，≥5R 净 2 对 3），但按“已有组件”不重做放行。规则应写明已有组件换搭配时是否要重新放行。
7. **工具缺失（通用）**：模拟器没有权益、总敞口和追保。用 W1E 校验时差 13/6 笔、少 1 段（RGTI），因为 0.5% 风险会卡总敞口。工具化时应加总敞口代理，并在每笔风险 >0.25% 的方案上先校验。

以下来自审查 1（`work/preflight_1.json`）的 workflow_issues，原样写入：

8. **规则不清（通用）**：第五节“组件放行”只写了单票回放，换仓、名额这类组件没法单票回放。WF05 用的是对齐同一组入场的带名额回放，并把“换出放弃的 R”和“新进入场的净 R”分开算。规则应写明名额类组件的放行口径、门槛和工具（名额模拟器）。
9. **规则不清（通用）**：已有组件换了搭配（C2 从 C062 离场换到 Q2 离场）后要不要重新放行；放行规则生效之前设计的组件算不算“从少数几段想出来的”；按 goal“单看是负向、但更像他”放进来的组件能不能免于 R 口径的放行。（与第 6 条同一问题，记账时引用同一 id。）
10. **规则不清（通用）**：用模拟器在选择年段表上预筛多少种形态，不计入“每轮 ≤5 个候选”。WF05 预筛了 12 种换仓形态和 13 组邻近参数才定下 M3。应要求预登记披露预筛过的形态数和结果，并对预筛选出的候选另设余量（与 WF-048 一致）。
11. **规则不清（通用）**：消融规则“去掉后不变差的组件不进入新版本”没有说明两个及以上组件各自可去（有交互）时怎么办，也没有说明可去组合是否要再过 accept。本轮按第 5 节处理：只去掉一个，按并列比较取，报告交互。
12. **工具缺失（通用）**：名额模拟器的仓位和总敞口代理建立在 0.5% 风险的单票回放乘 0.5 上，量不出单只上限（`max_position`）只在买入时起作用的效果；第二版的 `cap_gross.py` 又错误地按每日市值封顶。工具化时应按账户实际的每笔风险重放单票，并在买入或加仓时套用上限。
13. **任务书老坑（通用）**：轮次脚本按文件路径导入旧轮次模块时，会在受保护的旧轮次目录写 `__pycache__`。第七节的 Codex 启动命令应统一加 `-E PYTHONDONTWRITEBYTECODE=1`。
14. **任务书老坑（通用）**：任务书把门槛直接写成数字（WF05 第二版 3.3 节的 14），违反“阈值只写在 config”。审查清单应加一条：任务书里所有门槛都写成 config 键加比较对象的值。

## 9. 测试与扫描（轮末都要过；日志放 `DIR/rounds/WF05/logs/`）

```bash
cd /opt/opend-us-options/.claude/worktrees/gap-review
mkdir -p studies/martin_luk/workflow/rounds/WF05/work/tmp studies/martin_luk/workflow/rounds/WF05/logs
export TMPDIR=$PWD/studies/martin_luk/workflow/rounds/WF05/work/tmp
export PYTHONDONTWRITEBYTECODE=1
python3 -m unittest discover -s custody/tests
/opt/opend-us-options/.venv/bin/python -m unittest discover -s studies/trader_replication/tests
/opt/opend-us-options/.venv/bin/python -m unittest discover -s studies/martin_luk/tests
/opt/opend-us-options/.venv/bin/python -m studies.trader_replication.datasets check --config studies/martin_luk/workflow/config.json
/opt/opend-us-options/.venv/bin/python -m studies.trader_replication.datasets scan --config studies/martin_luk/workflow/config.json --git-diff
/opt/opend-us-options/.venv/bin/python -m studies.trader_replication.profile check --config studies/martin_luk/workflow/config.json
```

只跑这三组测试。还要核对：
- 受保护文件轮后的 SHA 与轮前相同（含 `system.py`、`wf03_engine.py`、`wf03_trading.py`）；
- `DIR/rounds/WF00`–`WF04` 的文件清单与轮前完全相同，没有新增 `__pycache__`（第 1 节）；
- 被接受时，`versions.json` 只在末尾追加了一行；
- `TMPDIR` 以外没有新写的临时文件。

## 10. completion.json 与收尾

`DIR/rounds/WF05/completion.json` 至少包含：
- 基本：`task`；`round: "WF05"`；`line: "joint"`；`scope`；
- 判定：`decision`；`candidate_decisions`；`equivalence_check`；`sim_reproduction`；`mechanism_release`（M3 放行与 C2 预览）；`reachable_upper`（模拟预测与扰动）；`accept_inputs`；`selection_rule_trace`；`final_components`；`ablation`；`holdout`；`checkpoint`；
- 风险与对照：`risk_flags`（超预算亏损、追保、总敞口）；`sim_vs_account`（逐段的模拟预测与实测）；
- 被接受时：`new_caches`、`version_entry_selfcheck`、`state_patch`；
- 过程：`prereg_sha256`；各步墙钟与峰值内存（`resource_usage`）；`code_changes_after_runs` 与重跑清单；`engine_copy_diff_summary`；
- 检查：`tests`；`datasets_check`；`datasets_scan`；`profile_check`；`protected_files_unchanged`；`rule_fingerprints`（轮前、轮后）；
- 收尾：`workflow_issues`（第 8 节全部加执行中新增）；`keep`（合计 ≤100MB，只列下一轮或报告复算真正要用的文件）；`disk_free_before`；`disk_free_after`。

轮末删掉 `work/` 里不在 keep 中的文件（含 `work/tmp`）。但 `work/review1/`、`work/preflight1/`、`work/preflight_1.json`、`work/wf05diag/`、`work/PLAN_v1_checkpoint_before_review.md`、`work/PLAN_v2_before_minor.md` 与第一版诊断文件要列进 keep：它们是审查记录，合计约 1.3MB。
