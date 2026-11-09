# IE 第三十八段任务书：统一标准指标库 v1 + 用 Martin 跑第一次拟合

工作目录：`/opt/opend-us-options/.claude/worktrees/gap-review`。本文件是第三十八段唯一任务书，运行期间不改。

先读：根 `AGENTS.md`、`studies/AGENTS.md`、**`skills/trader-replication/references/STANDARD_INDICATORS_CN.md`（全文，这是要实现的规格）**、`studies/martin_luk/notes/PREREG_IE32_CN.md`、`PREREG_IE33_CN.md`、`PREREG_IE37_CN.md`，代码 `studies/trader_replication/martin_profile_ie29.py`（现行拟合器，IE30–IE37 都用它）、`studies/trader_replication/ie_factor_library.py`（已有指标实现，可参考和移植）。不要读 `RULES*.md`、访谈、字幕、台账 setup 和备注。

## 用户要求（2026-11-04，必须遵守）

- 后续所有交易员复刻共用一套统一的“拟合”指标与参数集；常见指标（TradingView 那些）都要覆盖，不能只做一个流派。
- 同类、差异不大的指标要收敛：只留代表，其余记为别名。
- 选票拟合可以激进，但留出段不参与拟合、只测一次，拟合后做消融。代码里不能出现他的股票代码、日期或“他买过”类特征。

## 第一部分：标准指标库 v1（可复用代码，之后要单独提 PR）

1. 新建 `studies/trader_replication/standard_indicators.py`，按规格第三节实现“保留的代表”全部指标，名称用英文 snake_case，参数取规格里的默认值。
   - **自包含**：只依赖标准库和 numpy；不 import `ie_factor_library` 或其他未跟踪模块（需要的实现复制改写进来）。
   - 两层接口：`per_stock(arrays, benchmark, extras=None) -> dict[name, np.ndarray]`（单股时间序列，输入 o/h/l/c/v/t 日线数组，`extras` 可选给 IV、HV、期权成交 / 持仓、财报天数、4 小时衍生量，缺了就输出 NaN）；`cross_section(...)` 处理每晚截面类指标（IBD 式 RS 百分位、题材同伴、Minervini 模板里的 RS 条件）。
   - 一个 `SPEC` 常量列出每项：名称、流派、默认参数、一句话公式、别名列表、现有 / 新写。
   - 规格里标“需补”的按下面定义实现，写进 `SPEC` 的公式说明：
     - 均线斜率：均线 10 日变化 %。
     - 上涨日 / 下跌日成交量比：近 50 日上涨日成交量之和 / 下跌日成交量之和。
     - 成交量分布：近 100 日，每日成交量均匀摊到当日 [低, 高] 的对数价格网格（50 格）；POC = 量最大格；价值区 = 以 POC 为中心扩到 70% 量；输出离 POC（ADR 倍数）和 (收盘 − 价值区下沿) / (上沿 − 下沿)。
     - 上方未补缺口：近 252 日内、收盘价上方、之后最高价从未回到缺口上沿的向下跳空，取最近的一个，输出距离（ADR 倍数）；没有记 NaN。
     - 摆动低点抬高计数：低点左右各 2 根的分型低点（右侧 2 根确认后才可见），最近 3 个里连续抬高的个数（0–2）。
     - 底部长度 / 深度：自近 252 日最高点以来的天数；该高点以来最低点的回撤 %。
     - 第几次回到 EMA21：最近一次收盘上穿 EMA50 以来，最低价触及 EMA21（之前至少有一天收盘高于 EMA21 一个 ADR）的次数。
     - pin bar：下影 ≥ 2 倍实体且 ≥ 当日振幅 60%，收盘在上半部。
     - 轴心点：上一个完整周的 H/L/C 算经典 P、R1、S1，输出 (收盘 − S1) / (R1 − S1)。
     - 周线：用每周到当天为止的日线合成本周 K 线（交易员当天看到的周线），在其上算 RSI 14、MACD 柱（按价格归一）、内包周、周 pin bar、周收盘位置。
   - 所有指标只用到 t 日收盘为止的数据。
2. 新建 `studies/trader_replication/tests/test_standard_indicators.py`，只用合成数据：
   - 因果：截断到 t 的序列与完整序列在 t 处结果相同（逐项检查，含周线、摆动低点、成交量分布）。
   - 默认参数核对：RSI 14、MACD 12/26/9、布林 20/2、随机 14/1/3、Supertrend 10/3、CMF 20、MFI 14 与手写参考公式一致。
   - 别名恒等：CMO 与 RSI、威廉 %R 与随机 %K、布林 %B 与 z 分数在合成数据上秩相同（证明合并有据）。
   - `SPEC` 名称与 `per_stock`/`cross_section` 输出一一对应；没有任何代码、日期类特征。
3. 新建 `studies/trader_replication/standard_indicators_dedup.py`，执行规格第二节第 2、3 步：
   - 数据：`studies/trader_replication/reports/gap_review/ie5_work/stocks/*.npz` 全部 2277 只（不是 Martin 的池），基准 QQQ 按现有拟合器的取法；夜晚只取 2024-01-01 至 2025-12-31。
   - 秩相关用随机抽样的 30 万个“股票 × 夜晚”（固定种子）算，分块读，峰值内存 ≤ 1.3 GB。
   - |ρ| ≥ 0.9 的成对只留一个，保留顺序：规格表里先列的流派优先，同流派内先列的优先。0/1 形态类指标全样本出现率 < 1% 的去掉。
   - 输出 `studies/trader_replication/reports/gap_review/standard_indicators_v1_dedup.json`（全部 ρ ≥ 0.8 的成对、每项出现率、去掉的项与原因），并把最终保留清单写成代码常量 `V1_NAMES`。
   - 在规格文件末尾追加一节“v1 冻结清单与合并记录”：最终项数、按数据合并掉的成对（ρ 值）、因出现率去掉的项。规格其他部分不改。

## 第二部分：IE38，用 Martin 跑第一次拟合

在 `martin_profile_ie29.py` 上加选项（不改默认行为、不影响 IE30–IE37 复现）：

- `--library std_v1`：指标矩阵改用 `standard_indicators` 的 `V1_NAMES` 在池行上计算（缓存到 `ie38_work/`）。
- `--train-edges`：分档边界只用拟合段的行定（规格第四节）。IE38 全部候选都开。
- `--own-scan`：额外加入 pool_nights_20、theme_peers_pool 两项（规格里单列的“他自己扫描”量）。
- `--one-per-family`：每个流派最多选 1 项。

### 预登记（先原样写成 `PREREG_IE38_CN.md`，再开跑，跑完不改）

共同设置：主尺子与 IE32 相同（3 新 / 晚、持有 3 晚、冷却 10 晚、窗口 −4..+2，51 笔主目标中 2024–25 拟合 28 笔、2026 留出 23 笔）；最多 7 项、分档 3/5/10、权重 1/1.5/2/3；h4nan 过滤；全部开 `--train-edges`。

候选（5 个）：
- H1：IE32 的 48 项库（对照，只多了 `--train-edges`）
- H2：std_v1
- H3：std_v1 + `--own-scan`
- H4：std_v1 + `--one-per-family`
- H5：std_v1，分档只用 3/5

选择与判定：
- 只按 2024–25 内部留一半年交叉验证命中（4 折合计 28 笔）挑；同分取项数少者，再同分按 H1→H5 顺序。
- 选中者的 2026 为正式结果；其他候选的 2026 照记，不参与选择。
- 选中者另做：打乱标签 5 次（新种子）的完整流程；同预算随机 30 次；逐项去掉和按流派成组去掉的消融（2026 消融只报告）；约 4 只口径（2 新 / 晚、持有 2 晚）只报告。
- 前进：选中者内部交叉验证 > H1，且 2026 ≥ 11/23。

## 汇报（给用户，要白话）

`studies/trader_replication/reports/gap_review/strong_continue_ie38_CN.md` 开头三五句：v1 最终多少项、合并掉了哪些大类；挑中哪个候选，它的内部交叉验证和 2026 命中，与 IE32（18/28、10/23）、IE9（14/28、7/23）、随机比；是否前进；画像（选中的指标和他偏好的区间，一句话说明在看什么）。然后五个候选的表、消融、漏掉的票分类（不在池；在池没挑中；晚几晚才挑中）。结尾列已试 / 未试。

## 约束

- 只用已缓存数据，不取数，不连 OpenD；不提交、不推送；不改登记版、custody、工作目录以外的文件；data/ 只读；不改 IE30–IE37 的结果文件。
- 一次一个研究进程，不用多进程；峰值内存 ≤ 1.3 GB，分块读；`ie38_work/` ≤ 800 MB；剩余磁盘不足 1 GB 就停下回报。CPU 由外层控制。
- 跑 `.venv/bin/python -m unittest discover -s custody/tests`、`-s studies/trader_replication/tests`、`-s studies/martin_luk/tests` 和 `git diff --check`；已有的失败单独列出，不算本段引入。
- 无需用户确认，继续直到任务书全部完成。用中文回报，先结论。
