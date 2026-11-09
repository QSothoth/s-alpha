# F1 任务书（给 Codex，B 线）：对着他的行情段拟合选股——点到、能触发、早买

工作目录 /opt/opend-us-options/.claude/worktrees/gap-review。先读根 AGENTS.md、studies/AGENTS.md、`studies/martin_luk/notes/PI_METRIC_BRIEF_20261107_CN.md`（用户需求）、`studies/martin_luk/notes/PI_METRIC_ADVICE_20261107_CN.md` 第 3 节（选股层目标 C_trig / P_opp / E）、`studies/martin_luk/reports/Y1_CN.md`（新尺子，`notes/legs_frozen.json` 48 段）、`studies/martin_luk/reports/D1_CN.md`（第 2 节 master 与 IE47 池/触发差异，第 3 节他的段起涨时的日 K 画像），以及现有拟合器 `studies/trader_replication/martin_profile_ie29.py`、`martin_profile_ie42.py`（IE42–IE47 的做法、`--mainleg-objective`、`--quality-objective`、收缩先验、缺失当特征）、指标库 v1.1（`standard_indicators`）。

约束：一律 /opt/opend-us-options/.venv/bin/python；重计算用 `systemd-run --scope -p CPUQuota=60% -p MemoryMax=900M -q`、单进程单线程（OPENBLAS_NUM_THREADS=1）；4GB 机器，按日期/标的分块，不建大矩阵。另一条 Codex 线（A 线 M1）同时在跑并可能改共享模拟引擎，**你不要改模拟引擎和 `studies/martin_luk/m1_*`、`reports/m1_work/`**；拟合器改动放新文件 `studies/trader_replication/martin_profile_f1.py`（可 import 旧拟合器），旧拟合器不动，旧结果可复现。不联网、不拉新数据、不提交 git、不改登记版和看板。代码里禁止写入他买过的票、日期或“他买过”类特征（台账/段只作拟合标签）。不得有未来函数（档边界只用拟合段数据；复权用 raw_c 规则）。只用日 K。

## 目标（用户 2026-11-07）

“对着他选股的那些票来，尽可能把它们筛选出来”，并且要在账户里能买到、早买。拟合只用 2024–25（legs_frozen 中 2024 9 段、2025 22 段），2026 只测一次。

## 要做的

1. **候选池**：不再固定用 IE47 的四项过滤（期权量、H4 历史、离 20 日低点等挡掉过他的段）。按 D1 第 3 节，候选池改为流动性范围（与 master U4 同级：价≥2、20 日成交额≥5000 万、ADR≥3%）+ 当晚可见的趋势条件；报告新池对 48 段的可达上限（合格夜里进池的段数）和每晚池宽。
2. **拟合目标**：按 pi §3.2 实现触发感知目标，字典序 `(C_trig, P_opp, E)`：
   - C_trig：段被点名，且点名后 5 晚内出现**任一** M1/D1 认可的日 K 触发（收盘越前高、E10 贴线日内跨 9 EMA、E11 跳空后握手、B 路径越前高或收回 9/21 EMA），触发价处仍剩他涨幅 ≥ 一半。
   - P_opp：有机会的晚上（至少一个段的合格触发夜、且该票在池）点中他的段的比例；没机会的晚上点别的不罚。
   - E：覆盖段的早买比例中位。
   同时报 K=1/2/3（每晚点名只数）的结果，以及点名的不同票数/年。
3. **画像**：沿 IE42–IE47 的做法（共同画像 ≤ 7 项 + 上升/回调期各 ≤ 3 项修正，收缩先验，缺失当特征，档边界只用拟合段），特征用 v1.1 + D1 画像里出现的项（成交额分位、ADR、1/3/6 月涨幅、距一年高/低点、EMA 顺序、离 9/21 EMA、9/21 间距、量比、三日振幅/ADR、跳空、收盘位置、长期强势记忆=过去 120 日曾进 6 月强势前 20%）。可以同时拟合“新出现”和“长期强势回调再起”两类入口的画像（D1：2025 他的段 1 月涨幅中位仅 4%、6 月 87%），由当晚状态决定用哪套，不要用他的原话三类分类硬切。
4. **至多 5 个候选**（写 `studies/martin_luk/notes/PREREG_F1_CN.md`，写完不改）：例如 ① 新池 + 单一画像 ② 新池 + 两入口画像 ③ ② + K=2 ④ IE47 池 + 新目标（对照） ⑤ 你根据可达上限认为最有结构理由的一个。选择规则：2024–25 拟合 C_trig（合计）→ P_opp → E；要求每年点名能支撑 ≥52 笔。选中者测 2026 一次。另报每个画像项的区间、对应他哪句原话、按“不随大流 / 散户对手盘 / 小资金 / 盈亏比 / 复利”为何能赚钱，讲不通的标出。
5. **输出给 A 线用的点名文件**：选中者（及第二名）的逐晚点名序列（2024-01 至 2026-10，含分数、入口类型），格式与 IE47 的点名输入一致或给出适配说明，放 `reports/f1_work/picks_*.json`，以便下一轮接入 M1 的执行。

## 输出

报告 `studies/martin_luk/reports/F1_CN.md`（中文、先结论、白话表格；拟合段逐年逐段“点到/能触发/早买”，2026 一次），工件 `reports/f1_work/`（含 completion.json，三组测试结果）。终端最后 10 行以内摘要。
