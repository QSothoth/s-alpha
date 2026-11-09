# IE 第三十九段任务书：标准指标库 v1.1（以旧库为底扩展）+ 当晚池内分位分档

工作目录：`/opt/opend-us-options/.claude/worktrees/gap-review`。本文件是第三十九段唯一任务书，运行期间不改。

先读：根 `AGENTS.md`、`studies/AGENTS.md`、`skills/trader-replication/references/STANDARD_INDICATORS_CN.md`（v1.1，全文，尤其开头的 v1.1 改动、第一节第一条、第二节、第四节“分档方式”）、`studies/martin_luk/notes/PLAN_IE38_CN.md`、`PREREG_IE38_CN.md`、`studies/trader_replication/reports/gap_review/strong_continue_ie38_CN.md`，代码 `standard_indicators.py`、`standard_indicators_dedup.py`、`martin_profile_ie29.py`、`martin_profile_ie38.py`。不要读 `RULES*.md`、访谈、字幕、台账 setup 和备注。

## 用户要求（2026-11-05，必须遵守）

- 新库的目的是**扩展旧库的范围**，再去掉重复度太高的指标。v1 漏了旧库项，不是扩展；v1.1 必须包含旧库。
- 选票拟合可以激进，但留出段不参与拟合、只测一次，拟合后做消融。代码里不能出现他的股票代码、日期或“他买过”类特征。

## Claude 复核 IE38 的结论（已核实，作为本段前提）

- 改过的 `martin_profile_ie29.py` 不加新开关时原样复现 IE33 C1（内部交叉验证 18/28、2026 10/23），日志 `ie38_logs/review_r0.log`。
- 只加 `--train-edges`、权重保留 0.5：14/28、8/23，与 H1 完全相同（`ie38_logs/review_r1.log`）。18 → 14 全部来自档边界改为只用拟合段；0.5 权重未起作用。最受影响的是 2025H2（5 → 2）。

## 第一部分：标准指标库 v1.1

1. `standard_indicators.py`：
   - 把旧库 45 项（`martin_profile_ie29.py` 的 `indicators()` 与题材四项，去掉 listed_days、pool_run_nights、pool_nights_20、theme_peers_pool、theme_rank_rs21）全部加入 `SPEC`，名称沿用旧名，`origin="legacy"`，定义与旧代码数值一致；与已有新项同义的（如 range3 与 contract3_adr）在 SPEC 里记为同一项并保留旧名。
   - `ema_stack` 改回规格的 0–2（(EMA9>EMA21) + (EMA21>EMA50)），与旧库一致。
   - 新增 `V1_1_NAMES`；`V1_NAMES` 与 IE38 冻结结果保持不变，便于复现。
2. 一致性测试：在 Martin 池行上，`standard_indicators` 算出的旧库 45 项与 `ie29_work/indicators_h4nan_v2.npz` 缓存值逐项一致（有限值差 ≤ 1e-6、NaN 位置相同）；不一致的先修实现，不改旧缓存。
3. 去重（`standard_indicators_dedup.py` 加 `--version v1.1`，输出 `standard_indicators_v1_1_dedup.json`，不覆盖 v1 输出）：同样的全市场抽样与 |ρ| ≥ 0.9 规则；保留顺序：旧库项优先；都为新增时，TradingView 内置指标优先（RSI、MACD、布林、随机、CCI、ADX/DMI、Supertrend、一目、CMF、MFI、OBV、ATR、唐奇安、肯特纳、成交量分布、轴心点），再按规格表内顺序。出现率 < 1% 的规则不适用于旧库项。
4. 包含测试：读冻结的 v1.1 去重结果，旧库 45 项逐项“在 `V1_1_NAMES`”或“`V1_1_NAMES` 里有 |ρ| ≥ 0.9 的替身”，否则测试失败。
5. 规格末尾追加“八、v1.1 冻结清单与合并记录”（格式同第七节），其余部分不改。

## 第二部分：分档方式与 IE39

在 `martin_profile_ie29.py` / `martin_profile_ie38.py` 上加（不改默认行为、不影响 IE30–IE38 复现）：

- `--library std_v1_1`。
- `--night-rank`：打分前把每项换成当晚候选池内分位（平均秩 / 当晚有效个数，NaN 保持 NaN，0/1 项保持原值），再按训练段行切档；须与 `--train-edges` 同用。
- 权重菜单：本段全部候选用 (0, 0.5, 1, 1.5, 2, 3)，与旧拟合器一致。

### 预登记（先原样写成 `PREREG_IE39_CN.md`，再开跑，跑完不改）

共同设置：与 IE38 相同（主尺子 3 新 / 晚、持有 3 晚、冷却 10 晚、窗口 −4..+2；2024–25 拟合 28 笔、2026 留出 23 笔；最多 7 项、分档 3/5/10；h4nan；全部 `--train-edges`），权重 (0, 0.5, 1, 1.5, 2, 3)。

候选（5 个）：
- J1：旧库 45 项（对照；即 IE38 H1 / 复核 R1，指纹一致可复用其结果）
- J2：v1.1
- J3：旧库 45 项 + `--night-rank`
- J4：v1.1 + `--night-rank`
- J5：v1.1 + `--night-rank` + `--one-per-family`

选择与判定：
- 只按 2024–25 内部留一半年交叉验证命中（4 折合计 28 笔）挑；同分取项数少者，再同分按 J1→J5 顺序。
- 选中者的 2026 为正式结果；其他候选的 2026 照记，不参与选择。
- 选中者另做：打乱标签 5 次（新种子）完整流程；同预算随机 30 次；逐项与按流派成组消融（2026 只报告）；约 4 只口径只报告。
- 前进：选中者内部交叉验证 > 14/28，且 2026 ≥ 10/23。另与 IE9（14/28、7/23）比。

## 汇报（给用户，要白话）

`strong_continue_ie39_CN.md` 开头三五句：v1.1 最终多少项、旧库是否全部被包含（原样几项、靠替身几项）；挑中哪个候选，内部交叉验证与 2026，与 J1、IE9、随机比；两种分档方式哪个好；是否前进；画像（选中的指标、他偏好的区间、一句话说明在看什么）。然后五候选表、四折明细、消融、漏掉的票分类。结尾列已试 / 未试。

## 约束

- 只用已缓存数据，不取数，不连 OpenD；不提交、不推送；不改登记版、custody、工作目录以外的文件；data/ 只读；不改 IE30–IE38 的结果文件和 v1 冻结输出。
- 最多 2 个研究进程并行，每个进程单线程（OPENBLAS_NUM_THREADS=1、OMP_NUM_THREADS=1），每进程峰值内存 ≤ 900 MB、合计 ≤ 1.8 GB；`ie39_work/` ≤ 800 MB；剩余磁盘不足 1 GB 就停下回报。CPU 由外层控制（2 核合计 120%）。并行不能改变任何结果。
- 跑 `custody/tests`、`studies/trader_replication/tests`、`studies/martin_luk/tests` 和 `git diff --check`；已有的失败单独列出。
- 无需用户确认，继续直到任务书全部完成。用中文回报，先结论。

## 补记：第二部分取消（2026-11-05，用户，在任何拟合运行之前）

用户：“不用对照了，因子库只要复核没问题就行，只要没有未来函数。”本段只做第一部分（v1.1 指标库、一致性测试、去重、包含测试、规格第八节）；第二部分的五候选拟合、打乱、随机与消融全部不跑，`--night-rank` 等拟合选项不实现。上面的候选与判定作废，不产生结果。
