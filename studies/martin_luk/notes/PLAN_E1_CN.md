# 任务书 E1：IE47 选股 + 按 Martin 原话的执行，登记为看板可跑的研究版

本文件是唯一任务书。工作区 `/opt/opend-us-options/.claude/worktrees/gap-review`（gap-review 分支，未提交的研究都在这里）；冻结数据在主目录 `/opt/opend-us-options/data/`（`trader-data-v1` 等，路径按 `studies/trader_data` 的约定读取；工作区里没有 `data/`，需要时用软链接或环境变量指向主目录的数据，不复制、不改数据）。Python 一律用 `/opt/opend-us-options/.venv/bin/python`，`nice -n 10`、`OPENBLAS_NUM_THREADS=1`。

## 0. 先读

- 根 `AGENTS.md`、`studies/AGENTS.md`、`docs/TRADER_PROTOCOL_CN.md`（数据层、门禁、live、看板）
- `skills/trader-replication/SKILL.md`、`references/METHOD_CN.md`（第 9、10、11 节）、`references/MARTIN_LUK_CN.md`
- `studies/martin_luk/notes/RULES_CN.md`（他的原话，执行规则的唯一依据）
- `studies/trader_replication/systems.py`、`runner.py`、`study.py`、`system.py`（`Rules`、入场元组、盘中成交约定）、`gate.py`、`compare.py`、`success.py`
- `studies/trader_screens/README.md`、`scan.py`、`screens.py`（`triggered_from` 等买点写法）
- IE47 选股：`studies/trader_replication/martin_profile_ie42.py`（`--ie42-stage` 各阶段；IE43 起的主升浪口径与 `mainleg.py`）、`martin_profile_ie29.py`（拟合器、过滤池 h4nan、`bin_table`、`--unimodal` 等开关）、`standard_indicators.py`（v1.1 指标定义）、`martin_continue_ie9.py`（过滤条件 `GATES`）；结果 `studies/trader_replication/reports/gap_review/ie47_work/`（`fit.json` 画像、`agree.json` 保留指标、`scorecard.json` 含每晚名单）、报告 `strong_continue_ie47_CN.md`、`strong_continue_ie47_execution_CN.md`
- 已冻结的 master 系统 R74 + S7（`studies/martin_luk/replicate.py` 的 `build_system`），只作对照，不改

## 1. 目标

做出 Martin 的一个新版本“IE47 + E1”：

- **选股**沿用 IE47 已拟合好的画像（不重新拟合）：每晚从过滤池里按画像打分挑最多 3 只；
- **执行**按他的原话（第 3 节）；
- 只有一份实现：研究、横向比对（frozen）和交易员看板（live）都通过 `systems.py` + `runner.py` 跑同一份代码；
- 在 `systems.py` 里登记为 `martin_luk` 的**研究版**，不替换已冻结的 `R74 + S7`；冻结要用户同意，本任务不冻结。

## 2. 选股移植到统一数据层（先做，做完才做执行）

IE47 现在跑在研究缓存 `reports/gap_review/ie5_work/` 上，看板和 live 读不到。要做到：

1. **冻结画像参数**：把 IE47 的画像（共同 5 项、上升期 2 项、回调期 2 项，各自的档边界与每档分数、权重、行情划分规则）导出成一个只读 JSON（例如 `studies/martin_luk/reports/ie47_profile.json`），live 只读它、不再拟合。档边界只来自 2024–25（现有实现已如此），导出时保留来源与源码指纹。
2. **指标改从 `studies/trader_data` 面板计算**：画像用到的 7 个指标（`low252_distance_pct`、`perf5_pct`、`weekly_rsi14`、`weinstein_stage`、`chan_weekly_buy`、`avwap_big_gap_adr`、`smc_low_sweep`）和 QQQ 行情划分，只用当晚及以前的数据，复用 `standard_indicators.py` 的定义，不另写一套。
3. **过滤池**：IE9 的 4 个条件 `h4_history`、`adr20`、`option_volume`、`low20`（当晚比较范围内的分位，h4nan：`h4_history` 缺失算通过）以及“比较范围”本身（`prepared.json` 的 `scope`，每晚约 1045 只）都要在统一数据层上重建。**先查清来源**：`h4_history` 与 `option_volume` 在研究缓存里从哪来（`ie5_work/stocks/*.npz` 的 `extra_*` 字段的生成代码与原始数据）；统一数据层目前只有 `trader-hourly-v1`（81 只）与 `trader-options-v1`（约 72 个标的）。对不上的条件**不许悄悄换掉或删掉**，也**不许拉新数据、不许扣历史 K 线额度**（根 AGENTS）；写清缺什么、能用什么替代，替代方案作为单独标注的变体，量出它对名单的影响，交回用户决定。
4. **一致性核对（门槛）**：在 frozen 数据上，新实现每晚挑出的 3 只与研究结果（`ie47_work/scorecard.json` 的 `profile.picks`）逐晚比对，报告完全一致的晚数比例、不一致的原因分类；同时用 `mainleg.py` 重算三把尺子（主升浪覆盖、撒网比例、信号后续涨幅），与 IE47 报告的数应一致。差异 > 5% 的晚上不一致，先修实现或写清原因，再往下做。
5. **不看未来**：按 `gate.py` 的截断检查（截到 2024-09-30、2025-09-30，之前的名单必须与全量一致）。

## 3. 执行 E1（按 RULES_CN 原话）

每条规则写明对应的原话条目；日 K 看不到盘中先后时一律取保守口径；每条执行时点**先写单测**（根 AGENTS、METHOD 第 10 节）。

| 环节 | 规则 | 原话依据 |
|---|---|---|
| 观察 | 第 t 晚被 IE47 挑中，进入观察名单，有效到第 t+5 个交易日 | ③ 观察名单；⑤ 次日 PDH |
| 买点 | 有效期内第一个“当天最高价越过前一天最高价”的交易日买入；成交价 = max(开盘价, 前一天最高价)；只买一次 | ④ 突破前一日高点；⑤ 越过前一根 K 线高点即买 |
| 不追 | 成交价比当天开盘价高 3% 以上不买（日 K 上近似“离当日低点超过 3% 不追”） | ⑤ 离当日低点超过 3% 不追 |
| 止损 | max(前一天最低价, 成交价 × (1 − min(3%, 半个 ADR)))，止损宽度不少于 1% | ⑥ 前一根 K 线低点；不超过 ADR 一半；现在基本不超过 2.5–3% |
| 同日 | 买入当天最低价碰到止损，按当天止损出场（先止损） | METHOD 第 10 节补充约定 |
| 分批 | 到 3R、5R 各卖原始仓位的 15% | ⑥ 3R 或 5R 卖 15% |
| 离场 | 收盘第一次跌破 9 EMA 全部卖出 | ⑥ 收盘第一次跌破 9 EMA 清仓 |
| 仓位 | 每笔风险 0.5% 权益；单只 ≤ 25%；总仓位 ≤ 280%；同时最多 11 只；每天最多新开 4 笔（按当晚名次） | ⑦ 0.5%、25–30%、最多 11 只、最大约 280% |
| 成本 | 用现有 `COSTS['us']` | 统一口径 |

用引擎现有能力表达（`Rules` 的 `trims`、`trim_frac`、`trail='e9'`、`max_open`、`max_new_long`、`max_position`、`max_gross`、盘中成交的 `intraday_kinds` / `day_exit`）。引擎缺的能力先写单测再加，默认关闭，不改其他交易员的结果（全量测试为证）。

**候选（预登记，≤ 5 个，跑完不改）**：

- E1：上表原样（不加市况过滤）。
- E2：E1 + QQQ 收盘低于 50 EMA 时不开新多（⑦ 看 QQQ 是否在均线上方）。
- E3：E1，观察有效期改为 t+3。
- E4：E1 + 新仓反馈：最近 5 笔已平仓合计 < 0R 时每笔风险降为 0.25%（⑦ 最看重自己新仓的反馈；引擎 `feedback`）。

挑选只用 2024–25，按成功标准（SKILL.md“复刻成功标准”）里能在 2024–25 判的项和“更像他”（笔数、胜率、平均赚亏、持有天数与他公开数的差距 `study.gap`）挑一个；**2026 只对挑中的那个测一次**，其余写“未测”。挑选规则写进预登记 `studies/martin_luk/notes/PREREG_E1_CN.md` 后再跑。

## 4. 登记、门禁与看板

1. 新建一个 `Study` 子类（放在 `studies/martin_luk/` 下，例如 `ie47_e1.py`，或按现有约定放在 `studies/trader_replication/`），实现 `arrays` / `build`，数据只经 `studies/trader_data`（frozen / live 由 `TRADER_DATA_MODE` 切换）。
2. 在 `systems.py` 登记为研究版（参照已有研究版条目，如 Dan Zanger NOCAP_SLEEP10、Evan / Holguin），不动冻结的 `R74 + S7`；`STRATEGY` / 看板说明里写清这是研究版。
3. 门禁：`compare run us martin_luk`（只在 frozen 下）跑新版本，四项门禁（数据、不看未来、成交价在当日区间内、胜率 ≤ 35%）都要过；不过的照实报告原因。
4. 看板：live 模式下 `python -m studies.trader_screens.scan run us`（或只跑该系统的等效入口）能出今天的买卖、持仓与离场线；收盘模式与盘中 `--provisional` 都要能跑（不发布、不推送 QQ）。看板回放截到数据最后一天与比对表逐年核对一致。
5. 不改主目录（`/opt/opend-us-options` 是生产，QQ 推送定时任务从那里跑），所有改动只在 gap-review 工作区。

## 5. 要报的数（中文、先结论、少术语）

1. 选股移植：逐晚一致比例、不一致原因；三把尺子是否与 IE47 一致；`h4_history`、`option_volume` 的来源与缺口。
2. E1–E4 在 2024–25 的：分年收益、最大回撤、每年笔数、胜率、平均赚 / 亏、平均持有天数，与他本人（2024 +283%、423 笔、胜率约 25%、+15% / −3%；2025 +970%、940 笔、22%、+14.1% / −2.1%）和 master R74 多头（+326% / +239%）并列；挑中者的 2026（只测一次）。
3. 三层对照（METHOD 第 0 节）：他的票 + E1 执行（台账有确切日期的买入直接按 E1 买点与离场跑）、IE47 的票 + E1 执行、IE47 的票 + master 执行（已有：−72%），差距落在哪层。
4. 挑中版本的成功标准逐条结果（`success.judge`），门禁结果，看板 live 冒烟结果。
5. 列出所有新增 / 修改的文件与测试。

## 6. 规范与资源

- 只用现有数据；不拉新数据、不连 OpenD 取历史、不扣额度；live 看板冒烟如需补数，只在 TRADER_PROTOCOL 第 4 节允许的“按需补数”范围内，且先确认不会扣额度，否则跳过并报告。
- 4GB 内存、两核：单个重计算进程，峰值 < 1.5GB；磁盘余量 < 3GB 立即停。
- 测试：`.venv/bin/python -m unittest discover -s custody/tests`、`studies/trader_replication/tests`、`studies/trader_screens/tests -t .`、改到的研究切片测试，全部通过才算完成；`PYTHONUTF8=1`。
- 文档中文，代码与标识符英文；不提交、不推送、不改 main；不写密钥。
- 预登记写好再跑，跑完不改；失败照记。
