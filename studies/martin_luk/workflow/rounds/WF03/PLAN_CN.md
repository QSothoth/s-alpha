# WF03 任务书：交易线（line=trading，scope=common）——确认加仓后的止损与买点

> **状态（2026-11-09，第二次运行）**：上一次运行经三次独立审查（`work/preflight_1.json`–`preflight_3.json`）后停在检查点，没有交给 Codex。之后规则按检查点裁定更新（WORKFLOW_CN 第四节交易线：留出只报告；起点与比较对象每笔风险不同时补已平仓对照票 R 之和护栏、只更严；轮次中不改共享引擎、用副本并先证明逐位一致）。本版已按新规则核对（第 4 节第 1 条、第 6 节第 1 条、1 节引擎副本），重新审查记录见 `work/preflight_4*.json`（第 4 次审查的 2 条致命问题已改：2.1 市场与执行路径、3.2.3 全账本核对；第 5 次审查无致命问题，7 条次要意见已并入 2.1、3.2.1、3.2.3、3.2.4、3.3、3.4、6.3）。审查已通过，交给 Codex。

> 本文件就是全部要求。规则以 `skills/trader-replication/references/WORKFLOW_CN.md` 为准，先读它；本书与它冲突时以它为准，并把冲突写进 completion.json 的 `workflow_issues`。工作区 `/opt/opend-us-options/.claude/worktrees/gap-review`，不提交、不推送。交易员 martin_luk，流程目录 `studies/martin_luk/workflow`，本轮目录 `rounds/WF03`。本次运行参数 `line=trading, rounds=3`，本轮是第 1/3 轮（规则指纹 `a83dcddf5effc4be+6e2a56ea1e06ff47+81889204d1728986+af4618772ad79596`，见 `rules_pin.txt`）。冻结版本仍为 v1（选股 IE47、交易 C062、衔接 C062、行情 B4_PCT2）；WF01、WF02 判 branch；`rounds/WF02/STATUS.json` 照抄 WF00。

## 0. 定格结论

### 0.1 全局

- v1 合并漏斗（选择年已完成 28 段）：L0 1 / L1 4 / L2 1 / L3 5 / **L4 买晚 10 / L5 被洗 2** / L6 峰前持有 11（含晚买）。最好的分支 W1E 峰前持有 13，剩下的丢失里 L4 4 段、L5 2 段归交易线；WF01–WF02 已证明“名额给谁”这一层挖到头了。
- 交易线测试台（每晚把他的票当作已点名，`frozen/trading/C062`）：C062 峰前持有 (5, 10) = 15 / 28；W1E 的交易组件 C3（每笔风险 0.5%）在测试台上是 (6, 10) = 16（`rounds/WF02/work/trading_bench.json`）。**即使直接喂他的票，也有 12–13 段拿不到峰前**，所以交易线本身有大缺口，不只是合并时的名额问题。
- Plan 步骤只读了 `rounds/WF00/bench.json` 的 C062 测试台台账（他的票加对照票，2024–2025 入场，约 720 笔）：
  - **“试单 → 第二天确认加仓 → 第三天盘中扫掉”是最常见的离场路径**：有加仓后又被止损（stop / gap_stop / close_stop）的 368 笔，平均 −3.43R；他的段上也一样（OKLO、TSLA、RIVN、LMND、ONDS、CRCL 等反复出现 entry→add→stop，R ≈ −4）。
  - 机制（`system.py::try_proof`，C062 的 `proof_stop='fill'`、`proof_target_mult=4`、`proof_risk=True`）：第一次收盘高于成交价就算“证实”，按“止损放在原成交价、整笔亏损 ≤ 2 倍初始风险”反解股数。收盘只比成交价高 1% 时，止损距离只有约 1%，于是一次加到约 4 倍 K2 股数（OKLO 2025-02-13：试单 0.0010 → 加 0.0070，止损 54.38 = 成交价），**而且确认后止损改成盘中触发**。ADR 5% 以上的票第二天盘中回到成交价很常见，于是被扫。
  - 测试台上另有一批他的段整段没有成交或首次成交很晚（2025 年 SMR、IONQ-05、AMPX、ACHR、ASTS 无成交；TEM、SOUN、AMD、UPST、TSLA 首次成交晚 10–33 个交易日）。原因还不知道（没有突破？名额被对照票占满？观察期到期？），要由 D0 逐晚查清。
- 他的原话与日 K 翻译（`notes/RULES_CN.md` ⑥、`notes/TRANSLATION_CN.md`“听一半”）：止损放在**入场日低点或 21 EMA 下方，以收盘价判断**；“新仓顺利才继续加”；2025 年主力形态是**回调到 9/21 EMA 后收回**（④ 回调），日 K 换成“收盘收回 9/21 EMA”。C062 的证实止损（原价、盘中）比这两句都紧，而且 C062 没有开回调买点（测试台成交全是 `ie47_close_pdh`）。这正是检查点说的老坑 P5“止损只有约半个 ADR、盘中被扫”在 C062 里的新形态：试单阶段已经是收盘判、2 倍硬止损，**证实以后**反而回到了约 1% 的盘中止损。

结论：损失落在交易线一层（测试台上直接喂票仍丢），本轮做**单线轮** `line=trading, scope=common`。行情层已冻结，但档案 `behaviour_card.by_state` 仍是“未观测”，分状态修正判不了“更像他”，所以只改 `common`。

### 0.2 scope 与起点

| 项 | 本轮 |
|---|---|
| 改的格 | 交易 × common |
| 不改 | 选股 IE47、衔接 C062 分配、行情 B4_PCT2、任何 by_state |
| 比较对象（写死） | 冻结交易版本 C062 的测试台，`frozen_cache.bench_score()['training']`：峰前持有 (5, 10) = 15，`his_mean_r` 22.309355，`control_pnl` 1.471790，`behaviour_within` 1 |
| 诊断起点 B0 | C062 + C3（`risk=0.005`，其余同 C062），即 W1E 的交易组件（规则第四节“诊断起点”，2026-11-09 裁定）。C2 换仓属于衔接线，测试台不用 |
| 参照账户 | 不跑整账户；v0 master 只在报告里引用已有数字 |

候选全部在 B0 上改。**接受仍和 C062 比**；B0 本身不是底座、不是版本。

### 0.3 同线同机制的旧轮次，以及这次差在哪

| 旧轮次 | 当时做了什么 | 这次的差别 |
|---|---|---|
| E5、E6 | 入场收盘确认；试单止损收到 min(5%, ADR/2) | 本轮不动试单止损和入场确认；改的是**证实之后**的止损 |
| E13–E15（C 层 W / CF / CU） | 证实止损三选一：W = max(L0, 证实当天最低价)、CF = 原成交价、CU = max(L0, 预算价)；三者都是**盘中**触发。E15 用 128 组合按**账户收益**选中 CF；同下游下 W→CF 较差年配对差中位 +6.92 个百分点（W 输了） | Q1 = max(L0, 已生效止损)，比 W 更宽、方向和输掉的 W 一致，所以 Q1 单独（T1）预计难过，预登记要写明这一预期；本轮的新东西是 **Q2 收盘判 + 与之分开的 2 倍硬止损**（E13–E15 没测过），以及尺子换成测试台峰前持有、起点加了 C3。D0 要从 E15 已有结果（只读）摘出 C:W 组合的“他的段中点持有”作先验写进报告 |
| E7、E8d、E12 C4（回调买点） | 在 E6c + E3 管理上加回调收回，未被选中；E12 C4（+回调）2024 −6.8% / 2025 −5.0% | 下游已换成 C062 的试单 / 证实 / 0.5% 风险；规则要求下游大改后重测；只有先过全账本放行才上场 |
| P5（S2_CLOSESTOP、S3_BOTH） | 在 master 上把**试单**止损改为收盘判（5 天）并取消冷却，合并账户评 | C062 的试单已经收盘判；本轮改的是证实后的止损，在交易测试台上评，不碰冷却 |
| M3、E11（再上车） | 被洗后再买 | 本轮不加再买；测试台上他的票每晚都在名单里，冷却不起作用 |
| WF01、WF02 | 衔接线名额 + C3 风险 | 本轮不动衔接；C3 只作起点 |
| E14 H21A、C062 的 H21（proof_trail e21） | 证实后改用收盘跌破 21 EMA 跟踪离场 | 它们只换跟踪均线，保护止损仍盘中触发；Q2 是把止损线本身改为收盘判，另设与之分开的灾难止损 H |

### 0.4 触及的档案项（规则第九节）

- `capital`：不改档位、`max_position=0.5`、`max_gross=2.8`、`max_open=11`、`max_new_long=4`、追保与减仓方式。每笔风险 0.5%（C3）对应原话“每笔风险约 0.5%”。Q1、Q2 放宽或推迟止损但**证实股数照 B0**（2.3），所以实际亏损可能超过 `risk_budget`（2 倍初始风险）：这是“每笔风险约 0.5%”只听一半的代价，逐笔报告，不作门槛。
- `behaviour_card`：胜率（他 24.6% / 22.2%）、盈亏比（5.00 / 6.79）、笔数按年对照；测试台账户现在胜率约 12%、盈亏比约 12，本轮的止损改动预计会让胜率上升、盈亏比下降，即向他靠近，但要实测。
- `regime`：只用 B4_PCT2 分状态拆账，不用于执行。
- `hard_lines`：胜率上限、每年笔数、对数收益差只报告（规则第五节“底线项只报告”）。
- `goal`：第 7 节逐条对照。

## 1. 硬约束（违反就停，写进 completion.json）

> **执行环境说明（第一次启动因误读此节中止后补，2026-11-09）**：Codex 单元启动时已用 `systemd-run -E PYTHONUTF8=1 -E LC_ALL=C.UTF-8` 设好环境，**单元里的每条命令都已带这两个变量**，命令行里再写一遍只是冗余；漏写不算违规，不停。“违反就停”只指本节列的实质约束：读台账/段表、拉数据或用白名单外数据、改受保护文件或 `system.py`、用留出年选择、超计算上限等。先读任务书再读 WORKFLOW_CN.md 也不算违规。上一次中止的记录在 `work/abort_run1/`，它没有跑任何计算，本次从头执行即可。

- 只用日 K 与冻结数据，不拉数据；只读 config `datasets` 白名单和经 `studies.trader_data` 派生的缓存；不新增、不修改数据集或 schema。
- 策略代码不读他的台账、票名、日期、段表：新策略模块里不得出现 `legs_frozen`、`trades.csv`、`labels(`、`notes/`。段表只在测试台的输入构建（`funnel.bench_nominations` / 冻结的 `frozen/trading/C062/inputs.json`）和评测里用。
- 受保护、不得改的文件：`WORKFLOW_CN.md`、`config.json`、`.claude/workflows/`、`pipeline.py`、`funnel.py`、`mainleg.py`、`allocation.py`、`regime.py`、`ie47_e1.py`、`e15_research.py`、`e14_research.py`、`e10_research.py`、`p3_research.py`、`p4_policy.py`、`p5_policy.py`、`replicate.py`、`trader_data/`、`workflow/*.py`、已有 `frozen/` 缓存、`state.json`、`attempts.jsonl`、`versions.json`、`VERSIONS_CN.md`、`wf01_joint.py`、`wf02_joint.py` 及其测试、登记版与看板。
- **不改 `studies/trader_replication/system.py`**（规则第四节“改执行引擎”，WF-062/068；它的 SHA 在所有冻结缓存的代码指纹里，改一个字节就让全部缓存失效、后续轮次开不了；登记版和看板也用它）。Q1、Q2 的新字段放在**引擎副本** `studies/martin_luk/wf03_engine.py` 里：把 `system.py` 的 `Rules` 与 `simulate` 复制过去，只在副本中新增可选字段，默认值保持原行为。3.1 第 1 条先证明副本在新字段全关时与 `system.simulate` 逐位一致。新版本缓存的规则与 manifest 要写明引擎模块（`studies.martin_luk.wf03_engine`）和新字段，免得 `D.load_rules` 悄悄丢掉未知字段。
- 2024、2025 只用于选择；2026（留出*）只对最终选中者跑一次。
- **所有命令都加 `PYTHONUTF8=1 LC_ALL=C.UTF-8`**；测试再加 `TMPDIR=$PWD/studies/martin_luk/workflow/rounds/WF03/work/tmp`。`test_standard_indicators_v1_1` 读旧回归缓存属于既有回归测试（规则第一节），照跑。
- 一次只跑一个重计算进程：`systemd-run --scope -p CPUQuota=60% -p MemoryMax=900M`，`OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1`。**全部计算合计不超过 15 分钟墙钟**（规则第五节交易轮上限；一次测试台约 3.5 秒，单票回放计入；轮末三套测试与 datasets/profile 检查不计入）。超了就停，写明停在哪。
- 候选跑完后若又改了代码（含修 bug），受影响的候选全部重跑，旧结果保留并作废；报告列出改动时间、内容和重跑清单。
- 文档中文；代码英文；中间文件只放 `rounds/WF03/work/`。

## 2. 输入、组件、候选

### 2.1 输入（只读）

- 测试台输入：`frozen/trading/C062/inputs.json`、`prices.json`（按 manifest 核对 SHA），点名为 IE47（与 `frozen/selection/IE47/manifest.json` 一致）。
- 行情状态：`frozen/regime/B4_PCT2/states.json`，只拆账。
- **市场与执行路径写死为冻结缓存的建库路径**（第 4 次审查致命 1）：`frozen/trading/C062` 由 `rounds/WF00/work/base_c062_build.py` 用 `adapter.market()`（float64 价格与指标）+ `adapter.execution_inputs(A)` + `adapter.execution` 建成（该脚本当时没传 `profile`，照原样已不能重跑；冻结 account.json 的 rules 是 `maintenance=None`、没有 deleverage 字段）。本轮用 `adapter.execution(A, offered, 'C062', profile='L2.8', end=...)` 同法的路径：要求与冻结缓存的**成交和曲线逐位一致**（追保 0 次时成立，审查实测已平仓 768 笔相同），不要求 rules 字典与 account.rules 相同。本轮一切重放（等价性、D0、全账本、单票回放、候选、消融、留出）都用同一个 `A = adapter.market()`，**不得用 `run_wf01.prepare` / `run_wf02.prepared` / `trading_bench.py` 的 float32 面板**（实测会让 GME 2024-06-03 的离场翻转、73 笔 r 差超过 1e-9）。测试台点名 `offered` 读冻结 `frozen/trading/C062/inputs.json` 的 combined（与 base_c062_build 同法还原，核对 SHA）。
- **simulate 包装**：`run_wf03.py` 照抄 `adapter.execution` 的函数体（book 构建、`P3.px(A)`、ema 键 `e9/e21/idx_pb16/e8_scale` 与 `always`、起点 `2024-01-02`、`audit=True`、`track`），只把 `system.simulate` 换成 `wf03_engine.simulate`，并允许传入已构建的 book 和 rules（rules 先过 `capital.check_rules(rules, cfg['capital'], 'L2.8')`；B0 = `capital.candidate_rules(replace(adapter.rules_for('C062'), risk=0.005), cfg['capital'], 'L2.8')`）。不得 import `run_wf02.simulate` 或 `adapter.execution` 来跑候选（它们内部调 `system.simulate`，Q1、Q2 会悄悄失效）；`system.Rules` 先 `dataclasses.asdict` 再构造副本的 `Rules`。Q4 的 book 在同一个 A 上按 `adapter.execution` 的 C062 分支同法构建，只把 `M.entry_book(..., **M.E6['E6c'])` 换成加 `pullback=True` 的调用，后续 `retry_book` 与元组后处理照抄；Q4 关闭时 book 必须与 `adapter.execution` 的 C062 book 逐项相同（单测）。
- 可参照 `rounds/WF02/work/trading_bench.py`、`wf01_joint.build` 理解 C3 与测试台构建，但只借逻辑、不借它们的市场加载。报告里凡引用 `trading_bench.json` 的数字，只能引用整数项（峰前持有、早买），R 与 pnl 类数字一律用本轮 adapter 路径重出的值，并注明路径。
- **评分口径写死**：候选和比较对象都用 `frozen_cache.bench_score()` 里 `training` 块的同一套计算（截至 2025-12-31；跨年未决段 `peak_unknown` 不计入峰前持有；2025-12-31 仍持有的按当天收盘计 `why='end'`，`his_mean_r` 只算已平仓）。候选只跑到 2025-12-31，在自己的记录上调用同一套计算（把这段逻辑抽成本轮 `work/` 下的函数，或直接 import 后套用；不改 `frozen_cache.py`）。

### 2.2 新代码放哪

- 策略：`studies/martin_luk/wf03_trading.py`。在 2.1 写死的 `adapter.market()` 同一个 A 上，以 `adapter.execution` C062 分支同法构建的 book 与 2.1 的 B0 rules（与 `wf01_joint.build(..., c1=False, c2=False, c3=True)` 等价，单测核对 rules 字段相同）为起点加 Q1–Q4；Q1、Q2 由引擎副本 `studies/martin_luk/wf03_engine.py` 执行。
- 评测：`rounds/WF03/work/run_wf03.py`。
- 单测：`studies/martin_luk/tests/test_wf03_trading.py`。

### 2.3 组件（参数现在写死）

记号：L0 = 试单的初始止损 `stop0`（入场日低点，收到 min(5%, ADR/2)，即 C062 现状）；“证实” = C062 的第一次 proof 加仓（`try_proof` 的 `first`）。

- **股数与止损分开（Q1、Q2 共同的写死规定，第 2 次审查）**：引擎里交易的 R 以“试单股数 × w”为分母，证实股数变了 R 就等比变。为了只测止损机制、不把老坑 H1（宽止损配固定风险导致仓位太小）混进来，**Q1、Q2 只改离场，不改股数**：证实时的加仓股数严格照 B0（C062 的 `proof_stop='fill'` 反解：在原成交价处整笔亏损 ≤ `risk_budget`，目标 4×K2，单只 50%、总敞口 2.8）。副本引擎里把“定股数用的价位”和“写进 `q.stop` 的止损线”分成两个变量。代价是实际亏损可能超过 `risk_budget`：每个候选报告超出预算的笔数、超出幅度分布和最大值（按权益 %），如实写进报告。按 H 定股数（缩仓）的版本本轮不测，留作以后单独的仓位组件。
- **Q1 证实后止损留在结构位**：证实时整只票的止损线 = max(L0, 证实时的 `q.stop`)，**不再抬到原成交价**；这里 `q.stop` 包含试单期间 X1 每天抬到的 e9×0.99（写死：计入，与 C062 现有 `max(stop0, q.stop, floor)` 去掉 floor 一致）。不开 Q2 时这条止损线照 C062 盘中触发。实现为副本里 `proof_stop` 的新取值（例如 `'stop0'`，同时扩展合法值校验）。以后的加仓和 9 EMA 跟踪不变。只开 Q1 时盘中止损仍可能在 L0 附近（≤ ADR/2），本身就是老坑 P5，预计 T1 难过；它的失败不能读成“结构位止损没用”。
  - 原话：⑥“当日低点或突破 K 线 / 前一根 K 线低点”；TRANSLATION“放在入场日低点……”。
  - 预见的代价：股数照 B0，止损线变宽后单笔实际亏损可能超过 `risk_budget`；报告超预算笔数与幅度、他的段峰前仓位中位与 B0、C062 对比。
- **Q2 证实后的止损按收盘判，硬止损与止损线分开**：证实以后，整只票的止损线（包括证实止损和 X1 用 `e9×0.99` 抬起来的 9 EMA 止损线——这与他“收盘第一次跌破 9 EMA 清仓”一致）只在**收盘**低于它时于当天收盘离场。开盘和盘中只认**硬止损 H = 成交价 − 2 × w**，w = 成交价 − L0，与试单阶段完全相同（C062 的 `probe_hard_mult=2`，走 `live_stop` 的试单分支，不是 `close_stop_days` 分支的 `min(q.stop, H)`），证实后不随止损线移动。副本里两处要分开写：`close_window` 对已证实仓位也返回真；收盘比较对已证实仓位用 `q.stop`，试单期仍用 `stop0`；开盘低于 H 按开盘价离场，盘中触及 H 按 H 离场。H 只作灾难止损，**不参与定股数**（股数照 B0，见上）。3R/5R 减仓与其他离场规则不变。实现为副本里的新可选字段（例如 `confirmed_close_stop: bool`）。
  - 原话：TRANSLATION“听一半”行“以收盘价判断”；⑥ 离场“收盘第一次跌破 9 EMA 清仓”。
- **Q3 证实要等“顺利”**：第一次证实除了收盘高于成交价，还要求当天收盘高于前一日最高价。用现有字段 `proof_confirm_signal`，信号数组只用当天及以前的完成 K 线计算（`close[d] > high[d-1]`），放进 `ema` 字典。止损语义同 C062（原价）。
  - 原话：⑦“新仓顺利才继续加”。
- **Q4 回调收回买点**：在 IE47 的入场 book 里加入 E7 的回调收回入场（`IE.entry_book(..., **IE.E6['E6c'], pullback=True)`：9 EMA > 21 EMA，当天最低价触及 9 EMA、收盘在 9 EMA 上方且收阳，收盘买），止损规则与突破入场相同（入场日低点，收到 min(5%, ADR/2)）；之后走与 C062 相同的 `retry_book` 和元组后处理（照 `wf02_joint.build` 中 C5 分支的做法重建，但在 2.1 的 A 上，不从旧 book 删改条目）。
  - 原话：④ 回调（2025 年主力）“回调至少到日线 9 EMA……21 EMA 回调胜率更高”；TRANSLATION“换成日 K 动作：收盘收回 9/21 EMA”。

### 2.4 候选（5 个）

| 候选 | 组件 | 说明 |
|---|---|---|
| T1 | B0 + Q1 | 证实止损留在结构位 |
| T2 | B0 + Q2 | 证实后收盘判止损 |
| T3 | B0 + Q1 + Q2 | 原话完整版：结构位、收盘判 |
| T4 | B0 + Q3 | 证实要等顺利 |
| T5 | B0 + Q4 + （Q1、Q2 中放行的那些） | 加回调买点；Q1、Q2 都不放行时就是 B0 + Q4 |

含某组件的候选是否运行，由 3.2 第 4 条的放行规则决定；不放行就删掉，在预登记中写明数字。不得新增候选或改参数。

## 3. 步骤

### 3.0 轮前

`df -B1 /`、`free -m`；核对六个规则指纹与 `state.json.rule_fingerprints` 一致，以及 `rounds/WF03/rules_pin.txt`；datasets check、profile check（带 UTF-8 环境）都返回 0。确认没有别的 `codex-*` 单元在跑。

### 3.1 先写执行时点单测（任何候选运行之前，先全部通过）

1. 引擎副本 `wf03_engine.simulate` 在新字段全部关闭时，与 `system.simulate` 对 B0 和 C062 测试台的结果逐位相同（先用小的合成面板，再用 3.2 第 1 条的真实重放）。
2. Q1：证实当天止损线 = max(L0, 已生效止损)，不等于成交价（当成交价高于 L0 时）；证实加仓的股数与 B0 逐位相同（开不开 Q1、Q2 都一样），而 `q.stop` 写入的是 Q1 的止损线；两个值分别断言。加一种情形：证实当天 X1 已把 e9×0.99 抬到成交价以上时，Q1 与 B0 逐位相同。
3. Q2：已证实仓位某天盘中最低价低于止损线、收盘高于止损线 → 不离场；收盘低于止损线 → 当天收盘离场；开盘低于 H = 成交价 − 2w → 开盘价离场；开盘价在 H 与止损线之间 → 不离场；盘中触及 H → H 价离场；H 在证实后、9 EMA 抬高止损线后都不变；X1 抬起的 9 EMA 止损线同样收盘判；证实股数与 B0 逐位相同。证实**当天**之前仍走 C062 的试单规则。
4. Q3：收盘高于成交价但不高于前一日最高价的那天不证实；修改 d 之后的 K 线，d 及以前的证实不变。
5. Q4：回调入场只用第 d 天及以前的完成 K 线；修改 d 之后的 K 线，d 及以前的入场不变；Q4 关闭时 book 与 B0 逐项相同。
6. 策略模块扫描：`wf03_trading.py` 源码里不出现 `legs_frozen`、`trades.csv`、`labels(`、`notes/`。

### 3.2 等价性、只读诊断 D0 与放行（计入 15 分钟）

1. **等价性**（不算候选、不算留出）：
   - C062 测试台只跑到 2025-12-31，按 2.1 的评分口径得到的 `training` 块与 `frozen_cache.bench_score()['training']` 一致：整数项（峰前持有 (5,10)、`peak_unknown`、`behaviour_within`）逐位相同；`his_mean_r`、`control_pnl` 绝对差 ≤ 1e-9（跨年持仓的 `end` pnl 一律套用 `bench_score` 的 executions 重算法）。成交比对沿用 WF01 的投影法：已平仓逐笔相同，跨年持仓只比入场字段和 2025-12-31 及以前的 executions。
   - B0 测试台跑到 2025-12-31，段数/早买/峰前持有必须与 `rounds/WF02/work/trading_bench.json` 的整数项一致（2024 9/3/6、2025 19/9/10）。**段数与早买只算 `peak_eve ≤ 2025-12-31` 的段**（trading_bench 的 known 口径；按 bench_score 的 annual 全部段算，2025 年会变成 22 段、早买 12，误触发停止）；C062 同口径应为 (9/3/5, 19/9/10)。3.4 与报告里候选的早买也用这个口径。
   - 同路径按 2.1 评分口径出 C062 与 B0 的完整 `training` 块，以及 4.1 护栏用的数：**选择年已平仓对照票 `r` 之和**（入场在 2024–2025、跑到 2025-12-31 时 `why != 'end'`、按 `frozen_cache.bench_score` 的 `leg_at` 归属判为对照）与对照 pnl。审查时的只读实测参考：C062 r 之和 1193.012（721 笔）、B0 1311.874（704 笔）、B0 对照 pnl 3.0805；本轮复现值与参考差异较大（>0.01）时停下查原因。复现值写进 PREREG 后才跑候选。
   - 任何一项不一致就停。
2. **逐段诊断**（B0 测试台，选择年已完成且未峰前持有的段，约 12 段）：每段按最早的损失分类，并列出证据：
   - 窗口 [首锚点−3, 峰前1日] 内没有成交：逐晚写原因（没有收盘突破前高 / 观察到期 / chase / 名额 `max_open` 或 `max_new_long` 或总敞口被占 / 其他），名额被占时列出占着名额的持仓是他的票还是对照票、是否已证实；
   - 首次成交晚：首次成交之前有没有出现过 Q4 定义的回调收回日（只计数，不据此改参数）；
   - 早买后在峰前离场：每次离场的原因、离场时是否已证实、证实时止损离收盘多远（% 和 ADR 倍数）、离场当天收盘是否仍高于止损、离场后 10 个交易日内收盘是否回到离场价上方。
3. **全账本机制统计**（只用 IE47 自己的点名 book 与行情，不读段表；**只用入场在 2024-01-02 至 2025-12-31 的入场**，审查实测 1124 条，2026 年 445 条一律排除；离场后 10/20 个交易日等观察窗截到 2025-12-31，截断处如实标注，不读 2026 年 K 线）：`frozen/merge/C062/account.json` 只有 curve 和 trades，没有 entry book，所以在 2.1 的同一个 A 上用冻结 IE47 点名（`adapter.indexed(A, ROOT/cfg["systems"]["C062"]["picks"])`，与冻结 selection 缓存核对）按 `adapter.execution` C062 分支的同一路径重建（`IE.entry_book(**IE.E6['E6c'])` + `E15.P.retry_book(SPECS['C062'])` + 元组后处理），并核对重建出的 book 包含 C062 测试台的**全部对照票成交**（归类写死为“**入场前最近一次点名那一晚**（会重置观察窗的那晚）在冻结 `inputs.json` 的 control 里”，只在这条核对里用；审查实测按此口径 722 笔全部包含、喂票 49 笔中 39 笔不在 book。不要用 leg_at 归属或“观察窗内任一晚”判：COIN 2024-03-25 按 leg_at 算对照、按点名夜算喂票，QUBT 2024-12-17 反之。4.1 的 R 之和护栏仍按 leg_at 归属，两套口径分开用，不混）；测试台喂他的票产生、而 IE47 自己没点名的成交不要求包含，只报告条数（审查实测 39 笔）。这条核对之外，全账本统计不得读 inputs.json 的 his 部分或段表（第 4 次审查致命 2）；在这本 book 的全部入场（含被挡的）上，统计证实后离场的路径：证实时止损距离分布、证实后 1–3 天内被止损的比例与 R、这些被止损的票离场后 10/20 个交易日的收盘变化。
4. **组件放行（规则第五节；放行规则现在写死，跑完不改）**。单票回放：对 3 中的全部入场逐条单独回放（无名额、无组合约束：`max_open`、`max_new_long` 设 0 即不限，`max_gross` 放大到不约束，`maintenance=None`；起始权益 1；回放到 2025-12-31，未平按 `end` 计 R；R 与 ≥5R 用引擎 trades 的 `r`）。可合并成一次模拟，但要按同票持有期不重叠拆批，并断言计划回放条数 = 实际开出条数且每条都有 `r`，不满足就逐条回放。回放代码不读段表，只作诊断，不进任何账户、判定或版本条目。
   - 单票回放是诊断，**规则不过 `capital.check_rules`**（`max_gross` 放大、`maintenance=None`、`margin_rate=0` 必然通不过），只断言权益始终为正；后备的 mechanism.py 法只借它的单列切片方法，价格与指标用 2.1 同一个 A 的切片（`A[k][d:, j:j+1]` 及 `e8_scale[d:]`、`always`），不用它的 float32 面板与 screens.ema；另报与股数无关的诊断（只报告、不作门槛）：每笔离场的每股收益按 w 计、离场后 10/20 个交易日收盘是否回到离场价上方、触及单只 50% 上限的比例；拆批写死为**按同票序号**：每只票的第 k 次入场放进第 k 批，每批每只票最多一笔，任何分支都不重叠；先报批数与墙钟估计（每批约 3 秒 × 分支数）。断言失败时改用 `rounds/WF02/work/mechanism.py` 的单列逐条回放法（WF02 实测 1124 条共 5.4 秒）作后备，两种方法只要有一种通过条数断言即可；都不通过才停下报告。
   - **Q1、Q2、Q3**：同一批入场分别在 B0 与 B0+Qi 下单票回放。T3 的组合 Q1+Q2 也单独回放报告（只作参考，放行按单个组件判）。放行条件：两年合计平均 R ≥ B0，**且** ≥5R 占比 ≥ B0，**且至少一项严格大于**（持平不放行）。分年、分状态报告，但按两年合计判。
   - **Q4**：回调收回一触发就结束该观察，会替换掉同一观察里稍后的突破入场，所以按**整本 book** 比：B0+Q4 的整本 book 与 B0 的整本 book 分别单票回放。放行条件：B0+Q4 整本平均 R ≥ B0，**且** ≥5R 占比 ≥ B0，**且至少一项严格大于**。另报回调入场笔数（每年）以及被它替换掉的突破入场的成对 R。
   - 不放行的组件，含它的候选全部删除；T5 按 2.4 的规则改组成（Q4 不放行则删 T5）。全部不放行：本轮不跑候选，decision 记 branch，原因 `no_component_released`，STATUS 照抄。
5. **可达上限先算**（只对放行的组件，静态，分年、分状态）：
   - U_Q1Q2：B0 测试台上未峰前持有的段里，至少有一次在峰前、于证实后被盘中止损或 `gap_stop` 扫掉的段中，按候选的止损线（Q1：max(L0, 证实时 q.stop)，此后随 X1 上移，盘中判；Q2：B0 的止损线随 X1 上移，收盘判，盘中只认 H；Q1+Q2 同理组合）静态推演到峰前1日仍不离场的段数；
   - U_Q3：至少一次在峰前、证实后 3 天内被止损，而证实当天收盘不高于前一日最高价的段数；
   - U_Q4：窗口内没有成交或首次成交晚、而在首次成交前出现过回调收回日、且那天名额未满的段数。
   - Q2 的 U 用 2.3 的硬止损 H 计：峰前任何一天盘中跌穿 H 的段仍算丢失。
   - 反向风险：B0 已峰前持有的段里，在所放行组件下可能丢掉的段（Q1：峰前某天盘中跌穿 L0 而 B0 没有；Q2：峰前某天收盘低于止损线而 B0 的盘中止损没被触发；Q3：证实推迟或取消；Q4：首次入场被替换），以及 Q3 下证实股数 < B0 一半的段。
   - 并集 U，**净 U = U − 反向风险段数**。同时以 C062 测试台为基准再算一遍 U 与净 U（规则第五节：可达上限以冻结主线为基准，分支只作诊断），两者都报告。需要补的段数 = `config.accept.trading.min_extra_legs − (B0 峰前持有合计 − C062 峰前持有合计)`，两个合计用 3.2 第 1 条复现出的数，不写死。**以 B0 为基准的净 U** 小于需要补的段数就**不跑候选**，decision 记 branch，原因 `reachable_upper_below_threshold`，STATUS 照抄。
6. D0 写进 `work/d0_diagnosis.json` 和报告第 1 节。

### 3.3 预登记 `rounds/WF03/PREREG_CN.md`

在任何候选运行之前写好，记 SHA256，跑完不改。内容：假设、原话、组件参数、D0 摘要、放行结果与数字、U、比较对象数字、选择与回退规则、留出规则、计算上限；可预见的约束（Q1、Q2 股数照 B0、止损变宽或收盘才走 → 单笔实际亏损可能超过 `risk_budget`，Q2 的上限由灾难止损 H 与跳空决定；Q3 推迟证实 → 峰前仓位可能下降；T1 预计难过的理由）。另写明现实预期：Q1、Q2 股数照 B0（约 8 倍试单股数）而 R 分母仍是试单股数×w，证实后失败的笔会从约 −2R～−4R 变成约 −8R（Q1）到 −16R（Q2 打到 H）；B0 的 his_mean_r 只比 C062 多约 0.16、对照 R 之和余量约 119R，通过与否主要看被救回的大赢家能否抵消放大的失败笔，报告逐笔列出他的段上证实后失败的 R 变化，失败不得读成“结构位止损没用”。另写死三条**只标注、不否决**的规定：（0）Q1、Q2 股数照 B0 而止损变宽或收盘才走，是**有意留下的老坑 H2“加仓后止损没跟上”**：单笔亏损占权益的中位数或最大值超过原话“每笔约 0.5%”的 4 倍（即 2%）的候选，在报告和 completion 标注“风险超原话，待合并验收”，并写进下一轮合并建议；峰前仓位中位低于 C062 的候选，即使通过 accept 也在报告和 completion 标注“峰前仓位下降，待合并验收”；每个候选报告他的票因 `max_open`、`max_new_long`、总敞口被挡的次数，以及挡住它的持仓是试单还是已证实、是他的票还是对照票（老坑 H2）。

### 3.4 跑候选（只到 2025-12-31）

串行跑放行的候选。每个候选的规则先过 `capital.check_rules(policy, cfg['capital'], 'L2.8')`（同 WF02 的 evaluate），不过就不跑并报告。每个候选报告追保（margin call）次数；任一候选大于 0 时，另报该候选在 `maintenance=None`（不追保）下的峰前持有差多少段（只报告；C062 在 2.1 路径下已是 maintenance=0.3，追保 0 次）。每个候选另报超出 `risk_budget` 的亏损笔数与幅度（见 2.3）。每个都按 2.1 的评分口径出 accept 输入（`annual.<年>.peak_held`、`selection.his_mean_r/control_pnl/behaviour_within`），另出报告用的：早买、他的段平均 R 和盈亏比、对照票笔数与 pnl、测试台账户每年收益与最大回撤、行为记分卡（胜率、盈亏比、笔数）、他的段峰前仓位中位、证实次数与证实时股数分布，全部分状态（up、weak；pullback 写“未观测”）。他的段平均 R 被单笔主导（C062 中 SMCI 一笔 678R 占均值 22.31 的约 14.4，中位数 −2.2R），所以每个候选另报他的段 R 的中位数、去掉最大一笔后的均值、前三笔 R 的变化（只报告，不作门槛；Q4 替换入场时尤其要看）。B0 的 `his_mean_r` 只比 C062 多约 0.16，而 SMCI 一笔约 678R：每个候选逐笔写出 SMCI 那一段的路径（证实日、止损线、离场日与原因、R），并报告“去掉 SMCI 那一段后 accept 的 his_mean_r 一项是否同向”，便于判断通过或失败是否由单笔决定（只报告）。记下墙钟与峰值内存。比较对象 record 用 3.2 第 1 条复现的 C062 `training` 块。所有 record 原样存进 `rounds/WF03/accept_inputs.json`，列入 keep。

## 4. 选择规则（预登记，跑完不改）

1. 合格要同时满足：
   - `pipeline.accept('trading', 候选, C062, cfg)['status'] == 'accepted'`，阈值只读 config，返回原样记录；
   - **与仓位规模无关的对照护栏**（规则第四节“起点和比较对象每笔风险不同时”，WF-070/067；第 3 次审查：accept 的 `control_pnl` 是绝对 pnl，B0 每笔风险 0.5%、C062 是 0.25%，起点就高约一倍，候选对照 pnl 掉一半也能过）：选择年已平仓对照票 `r` 之和 ≥ C062 同口径的值，**且** 对照 pnl ≥ B0 的对照 pnl（同为 0.5% 风险）。
   只过 accept、没过这条护栏的候选不当选，completion 写明原因；它不改 accept 的判定，只是更严的选择条件。
2. 合格者中取峰前持有合计最多的；与最多者相差不到 3 段视为并列。并列时先取组件少的，再取 `control_pnl` 高的，再按编号。
3. 无人合格：decision 为 branch，不跑留出，STATUS 照抄。峰前持有更多但护栏没过的，记作探索分支并写明差在哪条护栏。

## 5. 消融与回退

交易线单线轮规则上不强制消融，但本轮候选多为组合，**选中者含两个及以上组件时必须做**（每次约 1–3.5 秒）：对选中者的每个组件（含 C3），**逐个去掉一个**各跑一次（T3 的消融是 T1、T2 与“C062 + Q1 + Q2”；T5 在 Q1、Q2 都放行时有 Q1、Q2、Q4 三个组件，各去掉一个共三次，再加去掉 C3 的一次）。去掉 C3 的那支即“C062 + 选中的 Q 组件”，用来报告 C3 的贡献（C3 与 Q1/Q2 有交互）。报告每个组件对峰前持有（分年、分状态）、他的段平均 R、对照 pnl、对照票 r 之和、行为项、峰前仓位中位的贡献。

去留规则（预登记，跑完不改）：去掉某组件后峰前持有不少、他的段平均 R 不降、对照票 r 之和不降（不用绝对 pnl，去掉 C3 后绝对 pnl 机械减半）、行为项不少，该组件可去。

- 只有一个组件可去：去掉它的组合就是已经跑过的那支，它必须**同时满足第 4 节第 1 条全部条件**（accept 通过，且已平仓对照 r 之和 ≥ C062、对照 pnl ≥ B0；去掉 C3 时“对照 pnl ≥ B0”改为“对照 r 之和 ≥ B0 同口径”），满足即为最终版，否则回退到选中的整体候选。
- 两个及以上组件都可去：不再加跑新组合，回退到选中的整体候选，报告里写明哪些组件单独看可去（下一轮合并时再议）。
- 消融得出的组件集只能是选中者的子集；不得据消融结果新增组件或改参数。

## 6. 留出、判定、STATUS、缓存

1. **留出一次，只报告**（规则第四节交易线“留出年”，WF-063）：只对最终版跑测试台到 2026-10-16，报告 2026 的峰前持有（2026 已完成段）、早买、他的段平均 R、对照 pnl、对照票 R 之和、测试台账户 2026 收益；同时引用 C062 测试台 2026 的已有数（`base_c062_bench_score.json`，峰前持有 10/17）。测试台每晚被喂他的票，收益含喂票偏差，判不出“每年不亏”，所以 **`holdout_loss` 一律写 `false`**，另写 `holdout_report_only: true` 和 `holdout_return`；每年亏不亏留到合并验收用完整账户判。报告主要看 2026 峰前持有对 C062 的 10/17、他的段平均 R、对照票 pnl 与 R 之和。留出结果不改判定、不进入下一轮设计。
2. **判定**：`completion.json.decision` 原样保留 `accept('trading', 最终版, C062, cfg)` 的返回；顶层写 `line: "trading"`、`scope: "common"`、`final_components`、`candidates`、`released`、`selection_rule_trace`、`ablation`。
3. **被接受时**：
   - 新交易版本名 `WF03_<候选号>`。按 `rounds/WF00/work/base_c062_build.py` 与 `frozen_cache.py` 的 schema（但按 2.1 路径传 `profile='L2.8'`，account.json 写 `candidate_rules`/`check_rules` 之后的完整 rules）建 `frozen/trading/WF03_<候选号>/`（`inputs.json` 与 C062 相同的测试台输入、`account.json` 为到 2026-10-16 的测试台记录与规则全量 `dataclasses.asdict(rules)`、`prices.json`、`manifest.json` 带代码与数据指纹、实际命令和脚本 SHA256，并写明 `engine: studies.martin_luk.wf03_engine` 及其 SHA256、策略模块 `wf03_trading.py` 的 SHA256——`frozen_cache.identity()` 的代码清单不含这两个文件，必须单独记）。读回自检：`frozen_cache.bench_score()` 固定读真正的 state.json，不能直接用；在 `work/` 里写一份与 `bench_score` 同算法的读回函数，直接读新缓存文件（核对 manifest 里各文件 SHA），`training` 块与本轮候选记录按 3.2 第 1 条的容差一致。不得为读回去改 `frozen_cache.py`、`adapter.py` 或 state.json。
   - 重出 `rounds/WF03/STATUS.json`：trading 格（common、up、pullback、weak）用新版本的测试台数，`frozen_version` 写新版本；selection、conversion、merge、regime 格照抄 `rounds/WF02/STATUS.json`；`pending_merge: true`，`pending_merge_note` 写“交易线 WF03_<候选号> 待合并（本次运行 line=trading，合并推迟到下一次不带 line 的运行）”；更新指纹。
   - 写 `rounds/WF03/state_patch.json`（记账步骤照抄用）：`components.trading` 新条目（version、status `frozen_component`、rules_source、rules_sha256、engine 模块与 SHA256、策略模块 SHA256、bench_selection IE47、accepted_on、accept 原样）、`frozen_caches.trading.<新版本>`（path、`manifest_sha256`、bytes，与现有条目字段相同；`frozen_cache.load` 会核对 manifest_sha256）。不改真正的 state.json、versions.json。
4. **未被接受时**：STATUS 照抄 `rounds/WF02/STATUS.json`，`round` 改为 WF03，更新指纹；不建缓存。

## 7. 报告 `rounds/WF03/REPORT_CN.md`

先写白话结论，再写细节：

1. D0：等价性、逐段诊断表、全账本机制统计、放行结果、U、反向风险。
2. 主尺与护栏（分状态）：每个候选与 C062、B0 的峰前持有（分年）、早买、他的段平均 R 与盈亏比、对照笔数与 pnl、行为记分卡、峰前仓位中位、测试台账户每年收益与最大回撤、证实次数与股数。
3. 逐段变化：每段从哪类损失变成哪类（相对 B0 与 C062）。
4. 合并漏斗变化：本轮不跑整账户，写“推迟到合并验收”；只列测试台上峰前持有变化的段，供下一轮合并参考。
5. 消融表（如有）。
6. 留出*（只最终版）。
7. 目标逐条对照（config.goal 全部 8 条），写明不改尺子、不放宽阈值、不以 master 为底座、不混评两条线。
8. 档案对齐表（capital 各项、逐笔亏损占权益比例的分布与原话“每笔风险约 0.5%”并排、behaviour_card、regime 未用于执行、hard_lines 只报告项逐年列出、选择年、留出年、段表 SHA）。
9. 与旧轮次的差别（0.3 表），失败时差在哪一层。
10. 下一轮建议（只写不跑）：D0 里属于名额或没有触发的段归哪条线；被接受时写明“合并轮必须用副本引擎 `wf03_engine.simulate` 重放，并先核对 manifest 里引擎与策略模块的 SHA256，不能走 `adapter.rules_for` + `system.simulate`（`D.load_rules` 会丢掉 Q 字段）”。

## 8. 测试与扫描（轮末都要过，日志放 `rounds/WF03/logs/`）

```bash
cd /opt/opend-us-options/.claude/worktrees/gap-review
mkdir -p studies/martin_luk/workflow/rounds/WF03/work/tmp
export PYTHONUTF8=1 LC_ALL=C.UTF-8 TMPDIR=$PWD/studies/martin_luk/workflow/rounds/WF03/work/tmp
python3 -m unittest discover -s custody/tests
.venv/bin/python -m unittest discover -s studies/trader_replication/tests
.venv/bin/python -m unittest discover -s studies/martin_luk/tests
.venv/bin/python -m studies.trader_replication.datasets check --config studies/martin_luk/workflow/config.json
.venv/bin/python -m studies.trader_replication.datasets scan --config studies/martin_luk/workflow/config.json --git-diff
.venv/bin/python -m studies.trader_replication.profile check --config studies/martin_luk/workflow/config.json
```

（`.venv` 指 `/opt/opend-us-options/.venv`。）还要核对：受保护文件轮后 SHA 与轮前相同（含 `system.py`）；`wf03_engine.py` 与 `system.py` 的差异只有新增可选字段与其分支（报告里附 diff 摘要）；测试跑完后 `TMPDIR` 以外没有新写的临时文件。

## 9. completion.json 与收尾

至少包含：`task`；`round: "WF03"`；`line: "trading"`；`scope: "common"`；`decision`（原样）；`equivalence_check`；`mechanism_release`（Q1–Q4 的回放数字、是否放行、被删候选）；`reachable_upper`；`accept_inputs`；`final_components`；`ablation`；`holdout`（`label: "留出*"`、`holdout_return`、`holdout_loss: false`、`holdout_report_only: true`）；`new_caches`、`state_patch`（被接受时）；`prereg_sha256`；各步墙钟与峰值内存；`code_changes_after_runs` 与重跑清单；`engine_copy_diff_summary`；`tests`；`datasets_check`；`datasets_scan`；`profile_check`；`protected_files_unchanged`；`rule_fingerprints`（轮前、轮后）；`workflow_issues`；`keep`（合计 ≤100MB）；`disk_free_before`；`disk_free_after`。

轮末删掉 `work/` 里不在 keep 中的文件（含 `work/tmp`）。磁盘剩余低于 800MB 时先清本轮中间文件，还不够就停下报告。
