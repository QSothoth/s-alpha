# WF02 任务书：联动轮（line=joint），在 W1E 方向上补准入顺序

> 本文件就是全部要求。规则以 `skills/trader-replication/references/WORKFLOW_CN.md` 为准，先读它；本书与它冲突时以它为准，并把冲突写进 completion.json 的 `workflow_issues`。工作区 `/opt/opend-us-options/.claude/worktrees/gap-review`，不提交、不推送。交易员 martin_luk，流程目录 `studies/martin_luk/workflow`，本轮目录 `rounds/WF02`。本次运行第 2/3 轮，不带 line。WF01 已记账，判定 branch；冻结版本仍为 v1（IE47 + C062 + C062，B4_PCT2），`rounds/WF01/STATUS.json` 照抄 WF00。

## 0. 定格结论

### 0.1 全局（先全局后局部）

- v1：28 段已完成的选择年段，峰前持有 4 + 7 = 11；漏斗 L0 1 / L1 4 / L2 1 / L3 5 / L4 10 / L5 2 / L6 5；收益 +61.3% / +57.4%；峰前仓位中位 10.2%；行为项 1。
- WF01 最好的是 W1E（C2 满仓顶掉最弱 + C3 风险 0.5%，不含 C1）：峰前持有 5 + 8 = 13（+2，门槛 +3），收益 +113.9% / +64.4%，峰前仓位中位 16.9%，行为项 1，其余各项都过。C1 放出约 120 笔后续突破，全不是他的段，反而挤掉首破，2025 年下降，**本轮不再用 C1**。
- Plan 步骤逐段读了 `rounds/WF01/work/W1E.json`（只读诊断）：W1E 仍有 15 段没峰前持有——L1 4、L0 1（选股线）；L5 2（早买后被洗）；L4 4（买晚）；**L3 4（3 段 `max_open`、1 段 `daily_long`）**，另有 1 段 L4（FUTU 2025-07）也是首破被 `max_open` 挡住才变晚。
- 这 5 段被挡里，4 段的最后名额（或每日第 4 个名额）被同一天、点名夜更早的入场拿走，这些入场之后 1–5 个交易日内被止损或换出：
  - 2024-11-29：QBTS（点名夜序号 476）拿到第 11 个名额，SOUN（479）被挡。
  - 2025-10-08：DPRO（690）、WOLF（688）、HUT（690）拿走最后三个名额，ASTS（691）被挡。
  - 2025-07-09：SEDG（626）拿走最后一个名额，FUTU（628）被挡。
  - 2024-05-09：每日 4 只名额被 DKNG（334）、CVNA（336）、APP（338）、DJT（336）用完，GME（338，名次 2）被挡；按 `(-born, rank, code)` 重排后 GME 仍排在同为 338、名次 0 的 APP 之后，能否进入要逐例实际重排判断。
  - 第 5 段 AMPX（2025-09-18）满仓的 11 只都是已证实仓位，同日没有竞争者，属于名额容量问题，本轮不处理。
- 引擎的同日排序：C062 的入场优先级是 `(nightly rank, born, code)`，先比名次、再比点名夜**从旧到新**，5 晚观察里第 4、5 天才突破的旧点名可以排在昨晚刚点名的新票前面。
- **上面 4 段只是线索，不是依据**（不为单个 case 拟合）。审查只读 W1E 全账本发现：两年 `max_open` + `daily_long` 被挡 284 次，其中 171 次同日前面已有点名更早的入场成交，这些成交 316 笔，平均 +1.97R、胜率 17.4%、32 笔 ≥5R——旧点名的后期突破整体并不差。所以 C4、C5 能不能上场，要先过 3.2 第 4 条的**全账本机制检验**和事先写死的放行规则（只用账本与行情，不用段表标签）；不放行就删掉相应候选，照实报告。

结论：剩下可修的损失仍在衔接线（同日名额分给谁）。它和 W1E 的换仓、仓位成对起作用：换仓腾出名额，仓位决定钱花在谁身上，C4/C5 决定名额给谁。所以仍做联动轮；但 C4/C5 的方向要先由全账本证据放行。C4、C5 都不放行时本轮不跑候选，completion 记 branch（未运行候选），这同样会触发同格两轮无进步检查点。

### 0.2 scope

| 线 × 状态 | 本轮 | 冻结版本 |
|---|---|---|
| 衔接 × common | C2（同 WF01，参数不变）+ 新的 C4 或 C5 | C062 分配 |
| 交易 × common | C3（同 WF01，参数不变） | C062 执行 |
| 选股、行情层、任何 by_state | 不改 | IE47、B4_PCT2 |

**规则提醒**：本轮和 WF01 是同一格（joint × 衔接 common + 交易 common）。按规则第五节，同一格连续 2 轮没有进步就进检查点。本轮如果不被接受，运行会在本轮后停下，交给用户，这是预期行为。和 WF01 的实质差别：新增的是准入顺序（C4）或观察期长度（C5），WF01 没有动过这两项；去掉了已证伪的 C1。

不做 by_state 的理由同 WF01：档案 `behaviour_card.by_state` 的胜率、盈亏比、笔数、收益都是“未观测”，仓位或名额开关算不出“更像他”；弱势态空头对应 regime.words 第 2 句，B4 没有覆盖这句。

### 0.3 触及的档案项（规则第九节）

- `capital`：C3 在 L2.8 档内改每笔风险，依据是规则第三节交易线“做多大”；`max_open=11`、`max_new_long=4`、`max_gross=2.8`、维持线、追保时点、`weakest_first` 都不变。C2、C4、C5 属于衔接线的“名额分给哪档、换仓”。
- `behaviour_card`：胜率、盈亏比、笔数按年对照；持有天数只说明。
- `regime`：不用于执行。
- `goal`：第 7 节逐条对照。

## 1. 硬约束（违反就停，写进 completion.json）

- 与 WF01 任务书第 1 节相同，全部照搬：只用日 K 与冻结数据、不拉数据；只读 `datasets` 白名单；策略侧不读台账、票名、日期、段表；同样一组受保护文件不改（`WORKFLOW_CN.md`、`config.json`、`.claude/workflows/`、`pipeline.py`、`funnel.py`、`mainleg.py`、`system.py`、`allocation.py`、`regime.py`、`ie47_e1.py`、`e15_research.py`、`e10_research.py`、`p3_research.py`、`p4_policy.py`、`p5_policy.py`、`replicate.py`、`trader_data/supplemental.py`、`workflow/*.py`、已有 `frozen/` 缓存、`state.json`、`attempts.jsonl`、`versions.json`、`VERSIONS_CN.md`、登记版与看板）。另外**不改** `studies/martin_luk/wf01_joint.py` 和 `studies/martin_luk/tests/test_wf01_joint.py`，只 import。
- 2024、2025 只用于选择；2026（留出*）只对最终选中版本跑一次。等价性检查不算留出，见 3.2。
- **所有命令都加 `PYTHONUTF8=1 LC_ALL=C.UTF-8`**（流程问题 WF-043）；测试再加 `TMPDIR=$PWD/studies/martin_luk/workflow/rounds/WF02/work/tmp`（先 `mkdir -p`）。`studies/trader_replication/tests` 里的 `test_standard_indicators_v1_1` 读旧回归缓存，leader 已裁定它属于既有回归测试，不算轮次数据使用：照跑，不要因此停下。
- 一个时间只跑一个重计算进程：`systemd-run --scope -p CPUQuota=60% -p MemoryMax=900M`，`OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1`。全部重计算合计不超过 60 分钟（墙钟），超了就停，写明停在哪。
- **候选跑完后如果又改了代码**（包括修 bug），受影响的候选和消融要全部重跑，旧结果作废但保留；报告里列出改动时间、改动内容和重跑清单（流程问题 WF-046）。
- 文档中文；代码英文；中间文件只放 `rounds/WF02/work/`。

## 2. 输入、比较对象、组件、候选

### 2.1 输入（只读）

同 WF01 任务书 2.1：IE47 点名用 `reports/s0_work/picks/IE47.json`，按 `frozen/selection/IE47/manifest.json` 核对 SHA；v1 用 `frozen/merge/C062/`（通过 `funnel.load_frozen` / `frozen_cache.load` 读）；B4 只用于拆账；v0 master 只用于报告；行情准备照 `rounds/WF00/work/leverage_replay.py::run` 与 `rounds/WF01/work/run_wf01.py::prepare`（可以 import，不改原文件）。

**比较对象写死**：v1。选择年峰前持有 (4, 7) = 11，收益 +61.3095% / +57.3669%，峰前仓位中位 0.101681，行为项 1（`rounds/WF01/accept_inputs.json` 的 v1 record）。参照账户：v0 master 只作报告。W1E 只作为消融参照，不是比较对象。

### 2.2 新代码放哪

- 策略：`studies/martin_luk/wf02_joint.py`。复用 `wf01_joint.build(..., c1=False, c2=..., c3=...)`，在它返回的 book 上加 C4 或 C5；不读 `notes/`，不调用 `labels(`。
- 评测：`rounds/WF02/work/run_wf02.py`。
- 单测：`studies/martin_luk/tests/test_wf02_joint.py`。

### 2.3 组件（参数现在写死）

- **C2**、**C3**：与 WF01 完全相同（`rotate_below=0.02, rotate_min_days=3`；`risk=0.005`）。
- **C4 同日新点名优先**（衔接 × common）。只改同一天、同一成交时点内的入场顺序：优先级从 `(rank, born, code)` 改为 `(-born, rank, code)`，即点名夜越新越先，再按当晚名次，再按代码。入场集合、价格、止损都不变。在 `retry_book` 和元组后处理之后再改键；先 grep 确认引擎和 C062 规则里没有别的代码按位置读取这个优先级（`entry_priority` 只在 `make_room_kind` 开启时使用，本轮不开）。如果发现有，就放弃 C4，并在预登记里写明。
  - 原话：③ 观察名单“扫描里新出现的、从中等升级到领涨的要重点看”；TRANSLATION 全听“盯的是刚变强的票”。
  - 与 E9 的差别：E9 的结论是建议按 IE47 名单内的**排位**（名次/分数）决定哪几只真下单、给多少风险，方向是“名次高者先”；C4 按**点名夜新旧**排，名次只在同一夜内起作用，方向是“新点名先”，并且只在同日争用名额时生效。
- **C5 观察 3 晚**（衔接 × common）。实现方式写死为**重建法**：直接调用 `IE.entry_book(A, picks, **IE.E6['E6a'])`（观察 3 晚，其余与 E6c 相同：收盘确认、宽止损收到上限、上限 5%），再走与 C062 相同的 `retry_book` 和元组后处理，retry metadata 由这次调用重新生成，不从 E6c 的 book 里删条目。旧点名第 4、5 天才出现的突破不再生成入场，也就不再和新点名抢名额。与 C4 检验同一个假设：一个是软办法（排序），一个是硬办法（缩短窗口）。
  - 与 E6 的差别：E6 在 E5 底座上比较 E6a（3 晚）与 E6c（5 晚），当时的执行是 E3 管理，没有 C062 的证实加仓、2 倍硬止损、`e8_scale`，也没有换仓和 0.5% 风险；E6c 按行为差距被选中（E6a 2024 +32.1% / 2025 −25.9%，E6c +22.2% / −20.8%），不是按合并漏斗。本轮在 C062 执行和 W1E 方向上，按合并验收重测；规则要求下游大改后重测。
  - 原话同 C4；另有 ⑤“越过前一根 K 线高点即买”：他买的是刚出现的突破，不是一周前那次扫描留下的旧票。

### 2.4 候选（5 个）

| 候选 | 组件 | 用途 |
|---|---|---|
| W2A | C2 + C3 + C4 | 主候选 |
| W2B | C2 + C3 + C5 | 同一假设的另一种做法 |
| W2C | C3 + C4 | W2A 去掉 C2 |
| W2D | C2 + C4 | W2A 去掉 C3 |
| W2E | C4 | 只开 C4，看它单独的作用 |

**参与选择的只有 W2A、W2B**（底座都是 W1E 的 C2+C3，可达上限按 3.2 计算）。W2C、W2D、W2E 的底座不是 W1E，**只作消融或参照，不参与选择**。含 C4 或 C5 的候选是否运行，由 3.2 第 4 条的放行规则决定。

W2A 去掉 C4 就是 W1E。本轮按同一代码重跑 W1E 一次，必须与 `rounds/WF01/work/W1E.json` 的逐笔记录和权益曲线逐位相同（这是等价性检查，不是候选）；不同就停。W2B 去掉 C5 也是 W1E；W2B 去掉 C2、去掉 C3 的两种组合只在第 5 节消融需要时补跑。

### 2.5 计算范围

只跑：候选和消融的 entry book 与执行、完整账户（只到 2025-12-31）、漏斗；W1E 与 v1 的等价性重放；W2_FINAL 的一次留出。不跑：选股点名、行情状态、v0 和其他已登记系统的重放、任何参数扫描、交易测试台缓存。

## 3. 步骤

### 3.0 轮前

`df -B1 /`、`free -m`；核对六个规则指纹与 `state.json.rule_fingerprints`；运行 datasets check 和 profile check（带 UTF-8 环境），都要返回 0。

### 3.1 先写执行时点单测（任何候选运行之前，先让它们通过）

1. C4 关闭时，book 与 `wf01_joint.build(c1=False, ...)` 逐项相同。
2. C4：同一天两只收盘入场，点名夜更新的那只先占最后一个名额，或先占每日第 4 个名额；点名夜相同时按名次；两只的成交价和止损不变。
3. C4：排序只在同一天、同一成交时点内起作用，不改变哪一天能入场；修改 d 之后的 K 线，d 及以前的入场不变。
4. C5：点名夜 t 只观察 t+1…t+3；t+4 的突破不生成入场；C5 关闭时与 E6c 相同；C5 的 book 与 `IE.entry_book(A, picks, **IE.E6['E6a'])` 经同一后处理的结果逐项相同，retry metadata 也一致。
5. C2 与 C4 一起：满仓时，先按 C4 的顺序处理入场，再按 C2 换仓；涨 ≥2% 或持有不到 3 天的仓位不会被卖。换仓卖掉旧仓、新仓却没开成的情况，要计数并和引擎语义一致。
6. 策略模块扫描：`wf02_joint.py` 的源码里不出现 `legs_frozen`、`trades.csv`、`labels(`、`notes/`。

### 3.2 等价性检查与只读诊断 D0（计入 60 分钟）

1. **v1 等价性**：口径与 WF01 3.2 第 1 条相同（权益曲线逐位比到 2025-12-31；`exit ≤ 2025-12-31` 的成交逐笔比；跨年成交只比入场字段和 2025 年及以前的 executions；先把 retry metadata 补回再比）。可以直接调用 `run_wf01.py` 的同一函数。另外重跑 W1E，与 `rounds/WF01/work/W1E.json` 逐位比对。这两项在 completion 里都记作 `equivalence_check`，不算留出、不算候选。
2. **STATUS 复现**：用 v1 按 `status.py` 的口径复现 `rounds/WF01/STATUS.json` 的 merge 格（峰前持有 (4,7)、L0–L6 为 1/4/1/5/10/2/5）。复现不了就停。
3. **逐段诊断**：在 W1E 的准入记录上，对 15 段未峰前持有的段，列出每次被挡的日期、原因、同一天排在它前面并拿到名额的入场（点名夜、名次、当天结果），以及当时占着名额的持仓（是否已证实、浮动 R、持有天数）。
4. **全账本机制检验与放行**（只用 W1E 账本、准入记录与行情，不读段表、台账、票名清单；选择年 2024-01-02…2025-12-31，2025 年末未平的按 2025-12-31 收盘计 R 并标 `end`）：
   - (a) **同日争用**：逐日找出 W1E 中“新点名被 `max_open` 或 `daily_long` 挡住、而同日有点名夜更早的入场已成交”的情形。按 C4 的 `(-born, rank, code)` 对当天该成交时点的全部入场实际重排，确定哪些旧点名会让出名额、哪些新点名会进来（成对或成组）。报告次数，以及双方结果：旧点名用 W1E 实际成交的 R；被挡新点名用**同一 C062 执行规则的单票回放** R（回放只喂这一条入场与行情，无名额、无组合约束；回放代码不读段表）。另报旧点名的单票回放 R 作对称参照。每组给笔数、平均 R、胜率、≥5R 笔数与占比，分年、分状态。
   - (b) **观察日分组**：W1E 全部成交按“入场日距点名夜第几天”（1–5）分组，给笔数、平均 R、胜率、≥5R 占比，分年、分状态。
   - **放行规则（现在写死，跑完不改）**：
     - C4 放行：(a) 中被换入的新点名单票回放平均 R ≥ 被换出的旧点名实际平均 R，**且** 新点名 ≥5R 占比 ≥ 旧点名 ≥5R 占比。两年合计判，同时报告分年。
     - C5 放行：(b) 中第 4–5 天入场的平均 R ≤ 第 1–3 天入场的平均 R，**且** 第 4–5 天 ≥5R 占比 ≤ 第 1–3 天。两年合计判，同时报告分年。
     - 不放行的组件，含它的候选全部删除（C4 不放行删 W2A、W2C、W2D、W2E；C5 不放行删 W2B），在预登记中写明数字。两者都不放行：本轮不跑候选，completion 的 decision 记 branch，原因 `no_component_released`（未运行候选），STATUS 照抄，照实报告。
5. **可达上限先算**（只对放行的组件，静态增量，按年、按状态报）：
   - U_C4：W1E 中未峰前持有的段里，被 `max_open` 或 `daily_long` 挡住、且按 `(-born, rank, code)` 对当天入场**实际重排**后会拿到名额的段数（如 GME 2024-05-09 与 APP 同为 338，须按名次实际判断）。
   - U_C5：W1E 中被挡、且挡它的同日成交或满仓持仓里，有来自观察第 4、5 天的入场，去掉它们后会拿到名额的段数。
   - 并集 U。需要补的段数 = `config.accept.merge.min_extra_legs − (W1E 峰前持有合计 − v1 峰前持有合计)`，两个合计都从 `rounds/WF01/accept_inputs.json` 的 W1E 与 v1 record 读出，不写死。若 U 小于需要补的段数，**不跑候选**，decision 记 branch，原因 `reachable_upper_below_threshold`，STATUS 照抄。
   - 同时报告反向风险：v1 和 W1E 中已经峰前持有的他的段，有多少段的首次成交在 C4 下会因为“点名更早”被挤到后面，或在 C5 下因为发生在第 4、5 天而消失（静态计数）。
6. D0 写进 `work/d0_diagnosis.json`，并写进报告第 1 节。D0 只用来检验机制、决定跑不跑；若显示某组件的前提完全不存在，可以在预登记里删掉含它的候选并写明数字。不得新增候选，不得改参数。

### 3.3 预登记 `rounds/WF02/PREREG_CN.md`

在任何候选运行之前写好，记下 SHA256，跑完不改。内容：

- 假设、原话、候选参数、D0 摘要和 U、比较对象数字、判定与选择规则、消融规则与回退、留出规则、计算上限；
- 可预见的约束：C4/C5 不增加笔数，但会换掉一批同日入场，胜率、盈亏比可能离开 ±20%，使行为项掉项；
- 跨年未决段从分母和 `peak_held` 剔除并单列；
- 每个候选都要报告（只报告，不作门槛）：各准入原因被挡次数相对 v1 和 W1E 的变化；被 C4 推后和换入的入场、被 C5 少掉的入场，做**全账本统计**（相对 W1E：笔数、R 分布、平均 R、胜率、≥5R 笔数，分年分状态；推后的入场后来是另一天成交还是没成交）；换仓逐笔（是否已证实、腾仓后 20 个交易日的收盘变化，尾部不足标“截断”）；换仓卖了旧仓、新仓没开成的次数；名额满的天数和持仓构成。

### 3.4 跑候选（只到 2025-12-31）

串行跑 W2A…W2E，每个都出账户（L2.8、先减最弱）、带准入原因的漏斗和记分卡，记下墙钟和峰值内存。`accept` 的输入格式与 WF01 相同（`annual.<年>.peak_held/return`、`selection.behaviour_within/peak_weight_median`、`uses_bar_turnover_selection=False`）。v1 record 直接用 `rounds/WF01/accept_inputs.json` 里的，并核对它和本轮 v1 重放算出的完全一致。每个候选和 v1 的 record 原样存进 `rounds/WF02/accept_inputs.json`，列入 keep。

## 4. 选择规则（预登记，跑完不改）

1. 只在 W2A、W2B 中（放行且运行了的）选择；W2C、W2D、W2E 只作消融或参照。合格条件：`pipeline.accept('merge', 候选, v1, cfg)['status'] == 'accepted'`，阈值只读 config。
2. 合格者中取选择年峰前持有合计最多的；与最多者相差不到 3 段的都视为并列。并列时先取组件少的，再取两年里较差一年收益更高的，再按编号。
3. 无人合格：decision 为 branch，不跑留出，STATUS 照抄。收益更好、但峰前持有或行为没过的候选，记作探索分支。

## 5. 消融（联动轮必做）

对选中者逐个去掉一个组件：W2A 的消融正好是 W1E、W2C、W2D；W2B 的消融是 W1E，以及补跑的“C3+C5”“C2+C5”。若去掉组件后的新组合是“只 C3”或“只 C2”等没跑过的配置，同样补跑。补跑都只到 2025-12-31，计入 60 分钟。报告每个组件对峰前持有（按年、按状态）、行为项、峰前仓位中位、每年收益的贡献。

如果去掉某个组件后这四项都不变差（峰前持有合计不少、行为项不少、峰前仓位中位不降、两年收益都不降），该组件不进入新版本。回退规则事先写死，与 WF01 第 5 节相同：

- 新组合已经整体跑过，就直接用它的 accept 结果；通过则它就是 W2_FINAL，不通过就回退到被选中的整体候选。
- 新组合没有整体跑过，就整体再跑一次（只到 2025-12-31，计入 60 分钟）。通过则它是 W2_FINAL；不通过或时间不够，就回退到被选中的整体候选。

## 6. 留出、判定、STATUS、缓存、版本条目

与 WF01 任务书第 6 节相同，并吸收 WF01 审查的经验：

1. **留出一次**：只对 W2_FINAL 跑 2024-01-02…2026-10-16。被接受时，这一次同时按 `leverage_replay` 的 `annual` 口径出 L1、L2、L2.8 三档，外加 L2.8 `pro_rata`。L1、L2、pro_rata 只作对照。2026 收益低于 `hard_lines.annual_return_min` 时，写 `holdout_return`，并标 `holdout_loss=true`。
2. **判定**：`completion.json.decision` 原样保留 `accept('merge', W2_FINAL, v1, cfg)` 的返回（`line` 保持 `'merge'`）；轮次类型写在顶层：`line: "joint"`、`scope`、`final_components`、`candidates`、`selection_rule_trace`、`ablation`。
3. **被接受时**：
   - 新缓存逐文件照 `rounds/WF00/work/base_c062_build.py` 的 schema：`frozen/conversion/W2_FINAL/allocation.json` 与 `state.components.conversion` 字段相同，`options` 里写出 `rotate_below`、`rotate_min_days`，加一个说明同日排序的字段，`entry_observation` 写明 C4 或 C5 的语义；`frozen/merge/W2_FINAL/account.json`（`dict(record, rules)`）和 `funnel.json`。**不建交易测试台缓存**：含 C3 时，测试台只按 `bench_score` 的同样口径跑到 2025-12-31，只写进报告，并沿用流程问题 WF-041。metadata 里记实际命令、脚本路径和 SHA256。
   - **读回自检用 `funnel.load_frozen(folder, version, code, data, line=line)`**，code 和 data 用 `frozen_cache.identity()` 的返回值，不经过 state；逐项核对 allocation 与将写入 state 的组件一致。
   - 重出 `rounds/WF02/STATUS.json`：先用 v1 逐格复现 `rounds/WF01/STATUS.json`，复现不了就停；再用新版本出 merge、conversion 两格（common、up、weak）；trading 格写新执行版本，`current` 用本轮到 2025-12-31 的测试台数，并标 `cache: "待建（交易线下一轮先建）"`；selection 格照抄。
   - 完整的 `rounds/WF02/version_entry.json`（字段照 `versions.py::initial_entries` 和 `append` 的校验，scorecard 含 L1/L2/L2.8 × 2024/2025/2026 全部 `FIELDS`）和 `rounds/WF02/version_rules.json`：**规则写全 `dataclasses.asdict(rules)`**，再加上 `capital_profile`、`max_gross`、`margin_rate`、`maintenance`、`deleverage`。然后把 `versions.json`、`VERSIONS_CN.md` 复制到 `work/`，在副本上调用 `versions.append` 自检通过，自检结果写进 completion。不改真正的账本。
4. **未被接受时**：STATUS 照抄 `rounds/WF01/STATUS.json`，`round` 改为 WF02，更新指纹，核对缓存 manifest 没有变化。不建缓存，不写 version_entry。

## 7. 报告 `rounds/WF02/REPORT_CN.md`

先写结论（白话），再写细节：

1. D0：全账本机制检验 (a)(b) 与放行结果、同日排序的逐段证据、U、反向风险。
2. 合并漏斗：每个候选相对 v1 和 W1E 的 L0–L6，以及逐段从哪层变到哪层。
3. 主尺与护栏（分状态 up / weak，pullback 写“未观测”）：峰前持有、早买、他的段平均 R 和盈亏比、峰前仓位中位、行为记分卡、每年收益、最大回撤、平均和最高总敞口、追保次数、笔数、不同票数。
4. 各线自己的尺子（只作参考）：衔接线“点到 → 早买 → 峰前持有”的转化；含 C3 时附交易测试台（到 2025-12-31）；选股照抄。
5. 消融表。
6. 准入与名额报告（3.3 列出的各项）。
7. 留出*（只 W2_FINAL）。
8. 目标逐条对照（config.goal 全部 8 条），写明不改尺子、不放宽阈值、不以 master 为底座、不混评两条线。
9. 档案对齐表（capital 各项，C3 的依据是“做多大”；regime 未用于执行；behaviour_card；hard_lines；选择年、留出年、段表 SHA）。
10. 与旧轮次的差别（WF01、E6、E9、E18、IE48、M2），以及失败时差在哪一层。
11. 写明本轮未处理的层：P5 的点名冷却层（10 晚冷却挡住再买）没有动；AMPX 那类“满仓全是已证实仓位”的容量问题也没有动。
12. 下一轮建议：只写建议，不跑。剩下的 L1（选股）、L5（早买后被洗）、AMPX 那类“满仓全是已证实仓位”的容量问题，各自属于哪条线。

## 8. 测试与扫描（轮末都要过，日志放 `rounds/WF02/logs/`）

```bash
cd /opt/opend-us-options/.claude/worktrees/gap-review
mkdir -p studies/martin_luk/workflow/rounds/WF02/work/tmp
export PYTHONUTF8=1 LC_ALL=C.UTF-8 TMPDIR=$PWD/studies/martin_luk/workflow/rounds/WF02/work/tmp
python3 -m unittest discover -s custody/tests
.venv/bin/python -m unittest discover -s studies/trader_replication/tests
.venv/bin/python -m unittest discover -s studies/martin_luk/tests
.venv/bin/python -m studies.trader_replication.datasets check --config studies/martin_luk/workflow/config.json
.venv/bin/python -m studies.trader_replication.datasets scan --config studies/martin_luk/workflow/config.json --git-diff
.venv/bin/python -m studies.trader_replication.profile check --config studies/martin_luk/workflow/config.json
```

还要核对：轮后受保护文件的 SHA 与轮前相同；测试套件跑完后，`TMPDIR` 以外没有新写的临时文件。

## 9. completion.json 与收尾

至少包含：`task`；`round: "WF02"`；顶层 `line: "joint"`；`scope`；`decision`（原样）；`equivalence_check`（v1 与 W1E）；`mechanism_release`（3.2 第 4 条 (a)(b) 的汇总数字、C4/C5 是否放行、被删候选）；`accept_inputs`；`final_components`；`holdout`（有就写，含 `label: "留出*"`、`holdout_return`、`holdout_loss`）；`new_caches`、`version_entry_selfcheck`（被接受时）；`prereg_sha256`；各步的墙钟和峰值内存；`code_changes_after_runs` 与重跑清单；`tests`；`datasets_check`；`datasets_scan`；`profile_check`；`protected_files_unchanged`；`rule_fingerprints`（轮前、轮后）；`workflow_issues`；`keep`（合计 ≤100MB）；`disk_free_before`；`disk_free_after`。

轮末删掉 `work/` 里不在 keep 中的文件（含 `work/tmp`）。磁盘剩余低于 800MB 时先清本轮中间文件，还不够就停下报告。

## 附：第 2 次审查后的覆盖条款（与上文冲突时以本节为准，预登记前生效、跑完不改）

1. **放行比较同口径**（覆盖 3.2 第 4 条及 C5 放行）：C4 放行时，被换入的新点名和被换出的旧点名**两边都用同一单票回放 R**；C5 放行时，第 4–5 天与第 1–3 天入场也都用单票回放 R。旧点名在 W1E 的实际成交 R 只作报告，不进放行判定。
2. **单票回放规则写死**：W1E 的规则（C062 + rotate_below=0.02、rotate_min_days=3 + risk=0.005，带 e8_scale），起始权益 1；无名额、无组合约束（max_open、max_new_long 放开，max_gross 放大到不约束，单票下 C2 自然不触发）；回放区间从入场日到 2025-12-31；R 与 ≥5R 直接用引擎 trades 的 `r` 字段，2025 年末未平的按 `end` 计。可把全部回放入场放进一次模拟。回放代码不读段表。回放计算时间计入 60 分钟。
3. **等号不放行**：C4 要求新点名平均 R ≥ 旧点名且 ≥5R 占比 ≥ 旧点名，并且至少一项严格大于；C5 要求第 4–5 天平均 R ≤ 第 1–3 天且 ≥5R 占比 ≤ 第 1–3 天，并且至少一项严格小于。
4. **先跑参与选择的**：先跑 W2A、W2B（放行的那些），按选择规则选出后，只补跑选中者需要的消融配置；W2C/W2D/W2E 只在作为消融需要时跑，报告标“不参与选择”。W1E 等价性重跑照做。
5. **路径依赖**：(a) 的同日争用按当天静态重排判定，报告里说明未计换入后占名额的后续影响。
6. **合并回放的防护**：若把回放合成一次模拟，按同票持有期不重叠拆成多批；maintenance=None；max_open、max_new_long 设 0（不限）；断言计划回放条数等于实际开出条数且每条都有 `r`，不满足就改为逐条单独回放。
7. **C5 回放样本**：用 W1E 的 book 全部入场（含被挡的），按观察第几天（入场日交易日序号减点名夜序号）分组。
8. **回放规则只作诊断**：不调用 capital.check_rules，不出现在任何账户、判定或版本条目里，不算违反档案。
