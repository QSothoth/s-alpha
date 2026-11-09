# WF04 任务书：交易线（line=trading，scope=common）——不顺利就走，给收盘止损腾名额

> **状态（2026-11-09）**：第 1 次独立审查（`work/preflight_1.json`）用 WF03 已有记录只读复算，否定了本书 0.1 的核心假设：挡住他的票的占位持仓 84.5%（T2）/78.7%（B0）当晚已 ≥ +1R、持有中位 13 天，是已经走出来的赢家，S 几乎砍不到（B0+S5 5 笔、S10 0 笔、T2+S5 13 笔）；按当晚优先级算的可达上限低于门槛，行为项也到不了。交易线单独已到可达上限（WF03 已救回静态上限内的 COIN、TEM），剩余缺口在名额数（衔接线），本次运行 line=trading 改不了。按规则停在检查点，**本任务书没有交给 Codex**，不进总账。

> 本文件就是全部要求。规则以 `skills/trader-replication/references/WORKFLOW_CN.md` 为准，先读它；本书与它冲突时以它为准，并把冲突写进 completion.json 的 `workflow_issues`。工作区 `/opt/opend-us-options/.claude/worktrees/gap-review`，不提交、不推送。交易员 martin_luk，流程目录 `studies/martin_luk/workflow`，本轮目录 `rounds/WF04`。本次运行参数 `line=trading, rounds=3`，本轮是第 2/3 轮（规则指纹 `a83dcddf5effc4be+6e2a56ea1e06ff47+81889204d1728986+af4618772ad79596`，见 `rules_pin.txt`）。冻结版本仍为 v1（选股 IE47、交易 C062、衔接 C062、行情 B4_PCT2）；WF03 判 branch，`rounds/WF03/STATUS.json` 照抄 WF02。

> **执行环境**：Codex 单元启动时已用 `systemd-run -E PYTHONUTF8=1 -E LC_ALL=C.UTF-8` 设好环境，单元里每条命令都已带这两个变量，命令行再写一遍只是冗余，漏写不算违规、不停。第 1 节“违反就停”只指实质约束（读台账/段表、拉数据或用白名单外数据、改受保护文件、用留出年选择、超计算上限等）。

## 0. 定格结论

### 0.1 上一轮（WF03）教给我们的

WF03 在 B0（C062 + 每笔风险 0.5%，即 W1E 的交易组件）上测了证实后止损的四个组件。全账本单票回放（IE47 自己的 1124 条选择年入场，无名额约束，`rounds/WF03/work/mechanism_release.json`）：

| 组件 | 平均 R | ≥5R 笔数 | 放行 |
|---|---:|---:|---|
| B0 | 1.73 | 99 | 基准 |
| Q1 证实止损留结构位 | 2.02 | 125 | 是 |
| **Q2 证实后收盘判止损、盘中只认 2 倍硬止损** | **3.02** | **142** | 是 |
| Q3 证实要收盘过前高 | 1.61 | 104 | 否 |
| Q4 回调收回买点 | 1.65 | 111/1240 | 否 |

单票看 Q2 是明显的改进：平均 R 接近翻倍、大赢家多四成，而且来自他的原话（“以收盘价判断”“收盘第一次跌破 9 EMA 清仓”）。但上了 11 只名额的测试台，T2（B0+Q2）峰前持有反而从 B0 的 16 段降到 14 段（`rounds/WF03/REPORT_CN.md` 第 2、3 节）：

- 救回了被盘中扫掉的 COIN-2024-02、TEM-2025-01（正是静态可达上限算出的 2 段）；
- 却丢了 LMND-2024-11、QUBT-2024-12、PL-2025-09、QBTS-2025-09——都是**窗口内没成交**或成交变晚；
- 原因在名额：收盘才止损让仓位拿得更久（全部交易平均持有 5.0 → 6.5 天），`max_open=11` 挡住他的票的次数从 119 升到 147，挡住它的持仓绝大多数是**已证实的对照票**（证实/对照 1032 → 1404 次）。
- B0 本身也有 7 段（AMC、GME、RGTI、AMPX、ACHR、AMD、ASTS）整段没成交，逐晚原因里大量是“持仓名额已满”，占位的同样主要是已证实、但没走出来的对照票（`rounds/WF03/REPORT_CN.md` 1.1 节）。

所以交易线现在的瓶颈不是“拿不住”，而是“**不顺利的仓位不走，占着名额，他的新票进不来**”。Q2 让拿得住的更多，同时也让拿着不动的更多。

### 0.2 本轮做什么

在交易线内加一条**停滞离场 S**：买进后第 N 个交易日收盘时，如果从入场以来的收盘价从没到过成交价 +1R（R = 成交价 − 初始止损 L0），就在当天收盘离场。到过 +1R 的仓位以后不再检查。它不看名额、不看他的票还是对照票，只看这一笔自己顺不顺利。

- 原话：⑦“最看重自己新仓的反馈”“新仓顺利才继续加”；TRANSLATION“和止损宽窄无关的部分要全听：……什么时候认错”；用户对他风格的概括（中短周期不是日内）：“多票试单、错了快砍、对了拿几天到几周”。
- 和 Q2 配对：Q2 让好仓位不被盘中扫掉，S 让不动的仓位按时让位。两者互相牵连（WF03 已证明单上 Q2 会挤名额），按 AGENTS“互相牵连的环节成对改”，本轮候选以 Q2+S 为主，另跑 S 单独的版本看 S 自己的作用。

损失仍落在交易线（测试台直接喂他的票仍丢、丢在交易执行带来的占位上），本轮做**单线轮** `line=trading, scope=common`。名额数 `max_open`、`max_new_long`、换仓 `rotate_*` 属于衔接线，本轮不动。

### 0.3 scope 与起点

| 项 | 本轮 |
|---|---|
| 改的格 | 交易 × common |
| 不改 | 选股 IE47、衔接 C062 分配（含 `max_open=11`、`max_new_long=4`、不换仓）、行情 B4_PCT2、任何 by_state |
| 比较对象（写死） | 冻结交易版本 C062 的测试台，`frozen_cache.bench_score()['training']`：峰前持有 (5, 10) = 15，`his_mean_r` 22.309355，`control_pnl` 1.471790，`behaviour_within` 1；已平仓对照 r 之和 1193.012（WF03 复现值） |
| 诊断起点 B0 | C062 + C3（`risk=0.005`），与 WF03 相同；峰前持有 (6,10)，对照 pnl 3.0805，已平仓对照 r 之和 1311.874（WF03 复现值） |
| 参照 | WF03 的 T2（B0+Q2）：峰前持有 (5,9)，`his_mean_r` 32.02，对照 pnl 2.7836，r 之和 1470.95 |

候选全部在 B0 上改，**接受仍和 C062 比**；B0、T2 都不是底座、不是版本。

### 0.4 同线同机制的旧轮次，以及这次差在哪

| 旧轮次 | 当时做了什么 | 这次的差别 |
|---|---|---|
| IE21（gap_review 第二十一段） | 在旧 master 系下，**未加仓试单**第 2/3/5 个完成日收盘低于 +0.5R 就下一开盘卖；已加仓的免检。买到 38→39/96，“腾名额只有小幅作用”，账户仍 −89% | 本轮下游是 C062 的试单/证实/0.5% 风险 + Q2 收盘止损；占位的主要是**已证实**的仓位（WF03 实测），所以 S **不豁免已证实仓位**；阈值 +1R、看收盘最高；尺子是测试台峰前持有 |
| H1（人性化仓位 H 轮） | 3 天时间止损，与其他人性条件成组，因不更贴近宣称成绩否决 | 不同下游、不同尺子；本轮只在交易测试台上量峰前持有，S 的放行先过全账本带名额回放 |
| C062 `nft_days`（引擎已有） | 第 N 日收盘仍低于成交价就走 | Q2 下低于成交价本来就收盘止损，`nft_days` 加不出东西；S 量的是“没走出来”（没到 +1R），不是“亏着” |
| WF03 T2 | B0 + Q2，峰前持有 14 | 本轮 V1 = T2 + S5，S 的作用就是 V1 对 T2 的差；T2 在本轮作消融重跑并与 WF03 逐位核对 |
| WF01、WF02 | 衔接线名额与换仓 | 本轮不动衔接；S 是单笔自身的离场规则，不看名额满不满 |

### 0.5 触及的档案项（规则第九节）

- `capital`：不改档位与上限；S 只会让仓位更早离场，不加仓、不放大风险。Q2 的“股数照 B0、止损收盘判”沿用 WF03，超出 `risk_budget` 的亏损照 WF03 逐笔报告、标注（老坑 H2，只标注不否决）。
- `behaviour_card`：S 预计缩短亏损和平局仓位的持有、让胜率略降或持平、笔数上升；逐年对照他的胜率（24.6%/22.2%）、盈亏比（5.00/6.71）、笔数。
- `regime`：只用 B4_PCT2 拆账，不用于执行。
- `hard_lines`：胜率上限、每年笔数、对数收益差只报告。
- `goal`：第 7 节逐条对照。

## 1. 硬约束（违反就停，写进 completion.json）

- 只用日 K 与冻结数据，不拉数据；只读 config `datasets` 白名单和经 `studies.trader_data` 派生的缓存；不新增、不修改数据集或 schema。
- 策略代码不读他的台账、票名、日期、段表：新策略模块里不得出现 `legs_frozen`、`trades.csv`、`labels(`、`notes/`。段表只在测试台的输入（冻结 `frozen/trading/C062/inputs.json`）和评测里用。
- 受保护、不得改的文件：`WORKFLOW_CN.md`、`config.json`、`.claude/workflows/`、`pipeline.py`、`funnel.py`、`mainleg.py`、`allocation.py`、`regime.py`、`studies/trader_replication/system.py`、`ie47_e1.py`、`e15_research.py`、`replicate.py`、`trader_data/`、`workflow/*.py`、已有 `frozen/` 缓存、`state.json`、`attempts.jsonl`、`versions.json`、`VERSIONS_CN.md`、`wf01_joint.py`、`wf02_joint.py`、**`wf03_engine.py`、`wf03_trading.py`、`tests/test_wf03_trading.py`、`rounds/WF03/` 下全部文件**、登记版与看板。
- **引擎**（规则第四节“改执行引擎”）：不改共享引擎，也不改 WF03 的副本。新建 `studies/martin_luk/wf04_engine.py`：复制 `wf03_engine.py`，只新增 S 的可选字段（例如 `stall_days: int = 0`、`stall_r: float = 1.0`），默认关闭。先证明 S 关闭时 `wf04_engine.simulate` 与 `wf03_engine.simulate` 对 C062、B0、T1、T2 的测试台逐位一致（成交、曲线、跟踪记录），且 C062、B0 与 `system.simulate` 逐位一致。
- 2024、2025 只用于选择；2026（留出*）只对最终版跑一次、只报告。
- 一次只跑一个重计算进程：`systemd-run --scope -p CPUQuota=60% -p MemoryMax=900M`，`OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1`。**全部计算合计不超过 15 分钟墙钟**（交易轮上限；一次测试台约 1 秒；轮末测试与检查不计）。超了就停，写明停在哪。
- 候选跑完后若又改了代码（含修 bug），受影响的候选全部重跑，旧结果保留并作废；报告列出改动与重跑清单。
- 测试设 `TMPDIR=$PWD/studies/martin_luk/workflow/rounds/WF04/work/tmp`。文档中文；代码英文；中间文件只放 `rounds/WF04/work/`。

## 2. 输入、组件、候选

### 2.1 输入与执行路径（照 WF03，已验证）

- 市场与执行路径写死为冻结缓存的建库路径：`A = adapter.market()`（float64），`adapter.execution_inputs(A)`；测试台点名 `offered` 读冻结 `frozen/trading/C062/inputs.json` 的 combined（核对 SHA）。不得用 `run_wf01.prepare` / `run_wf02.prepared` / `trading_bench.py` 的 float32 面板。
- 可以 import `rounds/WF03/work/run_wf03.py` 的 `prepare`、`score` 等评分与核对函数（只读，不改），但 simulate 包装必须调用 `wf04_engine.simulate`：本轮 `rounds/WF04/work/run_wf04.py` 照 `run_wf03.execute` 的写法（book 构建、`P3.px(A)`、ema 键 `e9/e21/idx_pb16/e8_scale/always`、起点 2024-01-02、`audit=True`、`track`）只把引擎换成 `wf04_engine`。`system.Rules` / `wf03_engine.Rules` 先 `dataclasses.asdict` 再构造 `wf04_engine.Rules`。
- 规则：B0 = `capital.candidate_rules(replace(adapter.rules_for('C062'), risk=0.005), cfg['capital'], 'L2.8')`；Q2 的字段与 WF03 相同（`wf03_trading.trading_rules(base, q2=True)` 的输出，转成 wf04 Rules）。每个候选的规则过 `capital.check_rules(rules, cfg['capital'], 'L2.8')`。
- 评分口径写死：与 WF03 相同，用 `run_wf03.score`（即 `frozen_cache.bench_score()` 的 `training` 算法，截至 2025-12-31；`peak_unknown` 不计入峰前持有；早买与段数只算 `peak_eve ≤ 2025-12-31` 的段）。4.1 护栏的“选择年已平仓对照票 r 之和”口径与 WF03 相同（入场 2024–2025、`why != 'end'`、按 `leg_at` 归属判为对照）。
- 行情状态：`frozen/regime/B4_PCT2/states.json`，只拆账。

### 2.2 新代码放哪

- 引擎副本：`studies/martin_luk/wf04_engine.py`。
- 策略：`studies/martin_luk/wf04_trading.py`（在 `wf03_trading.trading_rules` 的输出上加 S 字段；不改 wf03_trading）。
- 评测：`rounds/WF04/work/run_wf04.py`。
- 单测：`studies/martin_luk/tests/test_wf04_trading.py`。

### 2.3 组件（参数现在写死）

记号：w = 成交价 − L0（L0 为试单初始止损 `stop0`，即 C062 现状：入场日低点，收到 min(5%, ADR/2)）；`session[d] − session[d0]` 为入场后第几个交易日（入场日为 0）。

- **S_N 停滞离场**：对每一笔多头（试单或已证实都算），在入场后第 N 个交易日的收盘检查一次：若入场日（含）到当天（含）的所有收盘价都 < 成交价 + 1·w，就在当天收盘按收盘价全部离场，`why='stall'`。检查前任何一天收盘已达到 ≥ 成交价 + 1·w 的，免检，以后也不再检查。只检查一次（第 N 日），不是滚动窗口。同一天如果先触发了止损、跳空止损或其他离场，以先发生的为准（开盘、盘中先于收盘）；与 Q2 的收盘止损同一收盘触发时记为止损。S 离场后的再买规则照 C062 原样（不加冷却，也不额外放宽）。
  - N 取常见整数：**N=5（一周）**、**N=10（两周）**，不做其他取值。
  - 1R 的阈值固定，不调。
  - 原话：⑦“最看重自己新仓的反馈”“新仓顺利才继续加”；TRANSLATION 全听项“什么时候认错”；他的风格“错了快砍、对了拿几天到几周”。
- **Q2**（WF03 已放行，本轮不重新放行，引用 WF03 的数字）：证实后的止损线（含 X1 的 e9×0.99 抬升）只在收盘判；开盘和盘中只认硬止损 H = 成交价 − 2w；证实股数照 B0。

### 2.4 候选（4 个）

| 候选 | 组件 | 说明 |
|---|---|---|
| V1 | B0 + Q2 + S5 | 主方案：收盘止损拿住，一周没走出来就让位 |
| V2 | B0 + Q2 + S10 | 同上，给两周 |
| V3 | B0 + S5 | 不加 Q2，看 S 自己腾名额的作用 |
| V4 | B0 + Q1 + Q2 + S5 | WF03 的 T3 加 S，看结构位止损在腾名额后能否站住 |

含 S 的候选是否运行，由 3.2 第 3 条的放行与第 4 条的可达上限决定；不放行就删掉，在预登记中写明数字。不得新增候选或改参数。

## 3. 步骤

### 3.0 轮前

`df -B1 /`、`free -m`；核对六个规则指纹与 `state.json.rule_fingerprints` 一致、`rounds/WF04/rules_pin.txt`；datasets check、profile check 返回 0；确认没有别的重计算在跑；记下受保护文件的 SHA256（轮后再核一次）。

### 3.1 先写执行时点单测（任何候选运行之前，先全部通过）

1. `wf04_engine.simulate` 在 S 关闭时与 `wf03_engine.simulate` 逐位一致（合成小面板 + 3.2 第 1 条的真实重放）。
2. S：入场后第 N 日收盘前所有收盘都 < 成交价 + w → 当天收盘离场、`why='stall'`、成交价为当天收盘；第 k<N 日某天收盘 ≥ 成交价 + w → 第 N 日不离场，之后也不再检查；只有盘中最高价碰到 +1R、收盘没到 → 仍算没到；第 N 日开盘或盘中先触发止损 → 按止损离场、不再记 stall；修改第 N 日之后的 K 线，第 N 日及以前的决策不变（无未来函数）；S 对已证实仓位同样生效（证实后股数按全部持仓离场）。
3. Q2 + S 同一收盘：收盘既低于止损线又满足 S → 记为 Q2 的收盘止损。
4. 策略模块扫描：`wf04_trading.py`、`wf04_engine.py` 新增部分不出现 `legs_frozen`、`trades.csv`、`labels(`、`notes/`。

### 3.2 等价性、诊断与放行（计入 15 分钟）

1. **等价性**（不算候选）：按 2.1 路径重放 C062、B0、T1、T2 到 2025-12-31，`training` 块与 WF03 的 `accept_inputs.json` / `work/baseline_*.json` / `work/candidate_T*.json` 一致：整数项逐位相同，`his_mean_r`、`control_pnl`、对照 r 之和绝对差 ≤ 1e-9；C062 的 `training` 块与 `frozen_cache.bench_score()['training']` 一致。任何一项不一致就停。
2. **诊断 D0**（只读，用 T2 与 B0 的测试台记录）：
   - 他的段里未峰前持有、且窗口内至少有一晚因 `max_open` 或 `max_new_long` 被挡的段（B0、T2 分别列）：逐晚列占位持仓，每个占位持仓标出“到那晚为止已持有几个交易日、入场以来最高收盘达没达到 +1R”，即在 S5 / S10 下它那晚是否已经让位。
   - 测试台全部仓位（他的票 + 对照票）的持有天数分布，按“入场后第 5、10 日收盘前是否到过 +1R”分组，报告各组最终 R 的分布（中位、均值、≥5R 笔数），分年、分状态。这是 S 的代价预估：到第 N 日还没到 +1R、最后却成了大赢家的有多少。
3. **组件放行（规则第五节；规则现在写死，跑完不改）**。S 的作用是腾名额，单票回放量不出来，所以放行用**全账本带名额回放**：只用 IE47 自己的点名（`adapter.indexed(A, ROOT/cfg['systems']['C062']['picks'])`，不喂他的票、不读段表），按 2.1 的同一路径与 C062 衔接约束（`max_open=11`、`max_new_long=4`、L2.8）跑到 2025-12-31，诊断用，不进判定。成对比较：
   - S5 在 Q2 上：`B0+Q2` 对 `B0+Q2+S5`；S10 在 Q2 上：`B0+Q2` 对 `B0+Q2+S10`；S5 单独：`B0` 对 `B0+S5`。
   - 放行条件（三条同时满足）：① 实际开仓的入场笔数严格增加（名额真被腾出来了）；② 选择年已平仓交易的 ≥5R 笔数不减；③ 选择年已平仓交易的 r 之和不减。分年报告，但按两年合计判。
   - 另报（只报告）：S 离场笔数、其中离场后 10/20 个交易日内收盘回到离场价上方 +2w 的笔数（“砍后大行情”，观察窗截到 2025-12-31）、被挡入场次数的变化、账户每年收益与最大回撤。
   - V4 用 S5 的放行结果（Q1 在 WF03 已放行）。
4. **可达上限先算**（只对放行的组合，静态，分年、分状态）：
   - U_S（以该候选去掉 S 的版本为起点，即 V1/V2/V4 用 T2/T2/T3，V3 用 B0）：起点上未峰前持有的段中，窗口内至少有一晚因名额被挡、且那晚至少有一个占位持仓在 S_N 下已经离场（D0 第 1 条）、且那晚有收盘突破信号的段数；
   - 反向风险：起点上已峰前持有的段中，他的那笔仓位在入场后第 N 日收盘前从没收盘到过 +1R（S 会砍掉它）而峰前一日仍持有的段数；
   - 净 U = U_S − 反向风险。需要补的段数 = 3 −（起点峰前持有合计 − C062 峰前持有合计）。某候选的净 U 小于需要补的段数，就不跑这个候选，写明数字。全部候选都不跑：decision 记 branch，原因 `reachable_upper_below_threshold`，STATUS 照抄。
5. D0、放行、U 写进 `work/d0_diagnosis.json`、`work/release.json`、`work/reachable.json` 和报告第 1 节。

### 3.3 预登记 `rounds/WF04/PREREG_CN.md`

在任何候选运行之前写好，记 SHA256，跑完不改。内容：假设（S 腾出名额，让他的票进得来；Q2 让进来的拿得住）、原话、组件参数、D0 摘要、放行结果与数字、U、比较对象与 B0、T2 的数字、选择与回退规则、留出规则、计算上限；可预见的代价（S 会砍掉一部分慢热的大赢家，D0 第 2 条给出预估；Q2 的大额亏损沿用 WF03 的标注）。只标注、不否决的规定沿用 WF03：单笔亏损占权益中位数或最大值超过 2% 标“风险超原话，待合并验收”；峰前仓位中位低于 C062 标“峰前仓位下降，待合并验收”；每个候选报告他的票被名额挡住的次数与占位持仓分类。

### 3.4 跑候选（只到 2025-12-31）

串行跑放行且通过 U 的候选。每个都按 2.1 的评分口径出 accept 输入（`annual.<年>.peak_held`、`selection.his_mean_r/control_pnl/behaviour_within`），另出：已平仓对照 r 之和、早买、他的段平均 R 的中位数与去掉最大一笔后的均值、**他的已平仓笔数与他的 R 之和**（WF03 核对：改离场后已平本人笔数 47→29–34，均值不可比，必须并列）、对照笔数与 pnl、测试台账户每年收益与最大回撤、行为记分卡（胜率、盈亏比、笔数、持有天数）、峰前仓位中位、证实次数、S 离场笔数（他的票 / 对照票分开）、他的票被名额挡住的次数及占位持仓分类、追保次数、超预算亏损，全部分状态（up、weak；pullback 写“未观测”）。逐段列出相对 T2、B0、C062 的变化（峰前持有 / 早买后离场 / 无成交 / 买晚）。记下墙钟与峰值内存。所有 record 原样存进 `rounds/WF04/accept_inputs.json`。

## 4. 选择规则（预登记，跑完不改）

1. 合格要同时满足：
   - `pipeline.accept('trading', 候选, C062, cfg)['status'] == 'accepted'`，阈值只读 config，返回原样记录；
   - 与仓位规模无关的对照护栏（规则第四节，WF-070/067；只更严）：选择年已平仓对照票 `r` 之和 ≥ C062 同口径的值（1193.012），**且**对照 pnl ≥ B0 的对照 pnl（3.0805，同为 0.5% 风险）。
   只过 accept、没过护栏的不当选，completion 写明原因。
2. 合格者中取峰前持有合计最多的；相差不到 3 段视为并列。并列时先取组件少的，再取对照票 r 之和高的，再按编号。
3. 无人合格：decision 为 branch，不跑留出，STATUS 照抄。峰前持有更多但护栏没过的，记作探索分支并写明差在哪条护栏。

## 5. 消融与回退

选中者含两个及以上组件（含 C3）时必须做：逐个去掉一个组件各跑一次（V1 的消融是 T2、V3 与“C062 + Q2 + S5”；V2 同理；V4 的消融是 T3、“B0+Q2+S5”即 V1、“B0+Q1+S5”与“C062+Q1+Q2+S5”）。报告每个组件对峰前持有（分年、分状态）、他的段平均 R、对照 pnl、对照票 r 之和、行为项、峰前仓位中位的贡献。

去留规则：去掉某组件后峰前持有不少、他的段平均 R 不降、对照票 r 之和不降、行为项不少，该组件可去。

- 只有一个组件可去：去掉它的组合必须同时满足第 4 节第 1 条全部条件（去掉 C3 时“对照 pnl ≥ B0”改为“对照 r 之和 ≥ B0 同口径”），满足即为最终版，否则回退到选中的整体候选。
- 两个及以上组件都可去：不再加跑新组合，回退到选中的整体候选，报告写明哪些组件单独看可去。
- 消融得出的组件集只能是选中者的子集。

## 6. 留出、判定、STATUS、缓存

1. **留出一次，只报告**（规则第四节交易线“留出年”）：只对最终版跑测试台到 2026-10-16，报告 2026 的峰前持有（已完成段）、早买、他的段平均 R、对照 pnl、对照票 R 之和、测试台账户 2026 收益；引用 C062 测试台 2026 的已有数（`rounds/WF00/work/base_c062_bench_score.json`，峰前持有 10/17）。**`holdout_loss` 一律写 `false`**，另写 `holdout_report_only: true` 和 `holdout_return`。留出结果不改判定、不进入下一轮设计。
2. **判定**：`completion.json.decision` 原样保留 `accept('trading', 最终版, C062, cfg)` 的返回；无人当选时 `decision` 写 `{"status": "branch", ...}` 并另存每个候选原样的 accept 返回到 `candidate_decisions`。顶层写 `line: "trading"`、`scope: "common"`、`final_components`、`candidates`、`released`、`selection_rule_trace`、`ablation`。
3. **被接受时**：
   - 新交易版本名 `WF04_<候选号>`。按 `frozen_cache.py` 的 schema 建 `frozen/trading/WF04_<候选号>/`（`inputs.json` 与 C062 相同、`account.json` 为到 2026-10-16 的测试台记录与 `check_rules` 之后的完整 rules、`prices.json`、`manifest.json` 带代码与数据指纹、实际命令和脚本 SHA256，写明 `engine: studies.martin_luk.wf04_engine` 及其 SHA256、策略模块 `wf04_trading.py` 与 `wf03_trading.py` 的 SHA256）。在 `work/` 里写与 `bench_score` 同算法的读回函数直接读新缓存（核对 manifest 里各文件 SHA），`training` 块与候选记录按 3.2 第 1 条容差一致。不得为读回改 `frozen_cache.py`、`adapter.py` 或 state.json。
   - 重出 `rounds/WF04/STATUS.json`：trading 格（common、up、pullback、weak）用新版本的测试台数，`frozen_version` 写新版本；其余格照抄 `rounds/WF03/STATUS.json`；`pending_merge: true`，`pending_merge_note` 写“交易线 WF04_<候选号> 待合并（本次运行 line=trading，合并推迟到下一次不带 line 的运行）”；更新指纹。
   - 写 `rounds/WF04/state_patch.json`：`components.trading` 新条目（version、status `frozen_component`、rules_source、rules_sha256、engine 模块与 SHA256、策略模块 SHA256、bench_selection IE47、accepted_on、accept 原样）、`frozen_caches.trading.<新版本>`（path、`manifest_sha256`、bytes）。不改真正的 state.json、versions.json。
4. **未被接受时**：STATUS 照抄 `rounds/WF03/STATUS.json`，`round` 改为 WF04，更新指纹；不建缓存。

## 7. 报告 `rounds/WF04/REPORT_CN.md`

先写白话结论，再写细节：

1. D0：等价性、名额占位诊断、S 代价预估、放行结果、U、反向风险。
2. 主尺与护栏（分状态）：每个候选与 C062、B0、T2 的峰前持有（分年）、早买、他的段平均 R（含中位数、去最大一笔）、对照笔数与 pnl、对照 r 之和、行为记分卡、峰前仓位中位、测试台账户每年收益与最大回撤、S 离场笔数、名额挡住他的票的次数。
3. 逐段变化（相对 T2、B0、C062）。
4. 合并漏斗：本轮不跑整账户，写“推迟到合并验收”；列出测试台上峰前持有变化的段，以及 3.2 第 3 条全账本带名额回放的账户结果，供下一次合并参考。
5. 消融表（如有）。
6. 留出*（只最终版，只报告）。
7. 目标逐条对照（config.goal 全部 8 条），写明不改尺子、不放宽阈值、不以 master 为底座、不混评两条线。
8. 档案对齐表（capital 各项、逐笔亏损占权益比例的分布与原话“每笔风险约 0.5%”并排、behaviour_card、regime 未用于执行、hard_lines 只报告项逐年列出、选择年、留出年、段表 SHA）。
9. 与旧轮次的差别（0.4 表），失败时差在哪一层。
10. 下一轮建议（只写不跑）：仍被名额挡的段归衔接线（名额数、换仓）还是交易线；被接受时写明“合并轮必须用副本引擎 `wf04_engine.simulate` 重放，并先核对 manifest 里引擎与策略模块的 SHA256”。

## 8. 测试与扫描（轮末都要过，日志放 `rounds/WF04/logs/`）

```bash
cd /opt/opend-us-options/.claude/worktrees/gap-review
mkdir -p studies/martin_luk/workflow/rounds/WF04/work/tmp
export TMPDIR=$PWD/studies/martin_luk/workflow/rounds/WF04/work/tmp
python3 -m unittest discover -s custody/tests
/opt/opend-us-options/.venv/bin/python -m unittest discover -s studies/trader_replication/tests
/opt/opend-us-options/.venv/bin/python -m unittest discover -s studies/martin_luk/tests
/opt/opend-us-options/.venv/bin/python -m studies.trader_replication.datasets check --config studies/martin_luk/workflow/config.json
/opt/opend-us-options/.venv/bin/python -m studies.trader_replication.datasets scan --config studies/martin_luk/workflow/config.json --git-diff
/opt/opend-us-options/.venv/bin/python -m studies.trader_replication.profile check --config studies/martin_luk/workflow/config.json
```

还要核对：受保护文件轮后 SHA 与轮前相同（含 `system.py`、`wf03_engine.py`）；`wf04_engine.py` 与 `wf03_engine.py` 的差异只有 S 字段与其分支（报告附 diff 摘要）；`TMPDIR` 以外没有新写的临时文件。

## 9. completion.json 与收尾

至少包含：`task`；`round: "WF04"`；`line: "trading"`；`scope: "common"`；`decision`；`candidate_decisions`；`equivalence_check`；`d0`；`mechanism_release`；`reachable_upper`；`accept_inputs`；`final_components`；`ablation`；`holdout`（`label: "留出*"`、`holdout_return`、`holdout_loss: false`、`holdout_report_only: true`）；`risk_flags`；`new_caches`、`state_patch`（被接受时）；`prereg_sha256`；各步墙钟与峰值内存；`code_changes_after_runs` 与重跑清单；`engine_copy_diff_summary`；`tests`；`datasets_check`；`datasets_scan`；`profile_check`；`protected_files_unchanged`；`rule_fingerprints`（轮前、轮后）；`workflow_issues`；`keep`（合计 ≤100MB）；`disk_free_before`；`disk_free_after`。

轮末删掉 `work/` 里不在 keep 中的文件（含 `work/tmp`）。磁盘剩余低于 800MB 时先清本轮中间文件，还不够就停下报告。
