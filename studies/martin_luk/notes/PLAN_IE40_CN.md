# IE 第四十段任务书：用标准指标库 v1.1 跑 Martin，分年报覆盖率

工作目录：`/opt/opend-us-options/.claude/worktrees/gap-review`。本文件是第四十段唯一任务书，运行期间不改。

先读：根 `AGENTS.md`、`studies/AGENTS.md`、`skills/trader-replication/references/STANDARD_INDICATORS_CN.md`（全文）、`studies/trader_replication/reports/gap_review/strong_continue_ie39_CN.md`、`strong_continue_ie38_CN.md`，代码 `standard_indicators.py`、`martin_profile_ie29.py`、`martin_profile_ie38.py`。不要读 `RULES*.md`、访谈、字幕、台账 setup 和备注。

## 用户要求（2026-11-05）

“修完，跑一下最新的版本，看看 24、25、26 年的覆盖率。”只跑一个配置，不做候选比较。

## 配置（先原样写成 `PREREG_IE40_CN.md`，再开跑，跑完不改）

- 指标：`standard_indicators.V1_1_NAMES` 全部 117 项（`price` 已用真实收盘价）。新增 `--library std_v1_1`，在 Martin 池行上计算，缓存到 `ie40_work/`。截面类指标（IBD 式 RS 分位、题材同伴等）的比较范围必须是**当晚可观察的范围**（`b.meta['scope'][day]`，与旧库题材口径相同），不能用 2277 只并集。不加“他自己扫描”的量。
- 拟合：与 IE38 H1 相同的拟合器与搜索；`--train-edges`（档边界和池占比只用拟合段的行）；最多 7 项；分档 3/5/10；权重 (0, 0.5, 1, 1.5, 2, 3)；h4nan 过滤。
- 尺子：主尺子每晚 3 只新票、持有 3 晚、冷却 10 晚、窗口 −4..+2；副尺子约 4 只（2 新 / 晚、持有 2 晚）只报告。目标 51 笔主目标。
- 时间：2024–25 拟合（28 笔），2026 留出只测一次（23 笔）；2024–25 内部留一半年交叉验证（4 折）。

## 要报的数（分年）

| | 2024（11 笔） | 2025（17 笔） | 2026（23 笔） |
|---|---|---|---|
| 全段拟合模型命中（2024–25 为拟合内，2026 为留出） | | | |
| 内部交叉验证命中（2024、2025 各由两个半年折合计） | | | — |
| IE9 底版同口径 | | | |
| 同预算随机 30 次（均值、范围） | | | |
| 副尺子（约 4 只） | | | |

另报：全段模型选了哪几项、他偏好的区间（画像，一句话说明在看什么）；打乱标签 5 次（新种子）的完整流程结果；逐项与按流派消融（2026 只报告）；漏掉的票分类（不在池；在池没挑中；晚几晚才挑中）。

## 汇报（给用户，要白话）

`strong_continue_ie40_CN.md` 开头三五句：2024、2025、2026 各覆盖几笔 / 几成，2026 是留出；和 IE9、随机比；选了哪些指标、他偏好什么样的票。然后上表和其余内容。

## 约束

- 只用已缓存数据，不取数，不连 OpenD；不提交、不推送；不改登记版、custody、工作目录以外的文件；不改 IE30–IE39 的结果和 v1 / v1.1 冻结输出。
- 最多 2 个研究进程并行，每个进程单线程，每进程峰值内存 ≤ 900 MB、合计 ≤ 1.8 GB；`ie40_work/` ≤ 800 MB；剩余磁盘不足 1 GB 就停下回报。CPU 由外层控制。并行不能改变结果。
- 代码里不能出现他的股票代码、日期或“他买过”类特征。跑 `custody/tests`、`studies/trader_replication/tests`、`studies/martin_luk/tests` 和 `git diff --check`。
- 无需用户确认，继续直到完成。用中文回报，先结论。
