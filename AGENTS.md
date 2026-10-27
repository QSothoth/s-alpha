# 项目规范

> 先读本文件，再读要改的目录的 `AGENTS.md`；使用细节在各 skill 的 `references/`，共用规范在 `docs/`，代码目录 README 指路。每个 `CLAUDE.md` 只有一行 `@AGENTS.md`（测试强制）。

## 按 skill 组织

入口统一放 `skills/<名称>/SKILL.md`，使用说明与外部资料放各自 `references/`；共享代码保留原模块路径，待完成研究留在 `studies/`，已结束研究在 `studies/archive/` 保留结论与固定 Git 版本。使用资料不在代码目录重复维护，跨技能规范留在 `docs/`。新增能力优先扩展所属 skill，不为每个脚本或失败研究单建 skill。

| 任务入口 | 实现规范 |
|---|---|
| [opportunity-research](skills/opportunity-research/SKILL.md)：机会与反证研究 | [studies/AGENTS.md](studies/AGENTS.md) |
| [daily-technical-review](skills/daily-technical-review/SKILL.md)：单股日 K 多头评估 | [studies/AGENTS.md](studies/AGENTS.md) |
| [trend-market-scan](skills/trend-market-scan/SKILL.md)：全市场周线规则扫描 | [studies/AGENTS.md](studies/AGENTS.md) |
| [trader-replication](skills/trader-replication/SKILL.md)：按环节逼近一位公开交易员 | [studies/AGENTS.md](studies/AGENTS.md) |
| [trader-screens](skills/trader-screens/SKILL.md)：交易员看板，各人今天的买卖、持仓与交集 | [studies/AGENTS.md](studies/AGENTS.md) |
| [market-watch](skills/market-watch/SKILL.md)：盘中只读盯盘 | [watch/AGENTS.md](watch/AGENTS.md) |
| [near-expiry-session](skills/near-expiry-session/SKILL.md)：近到期期权会话 | [custody/AGENTS.md](custody/AGENTS.md)、[studies/AGENTS.md](studies/AGENTS.md) |

Skill 是任务入口，不改变实现的成熟度、策略资格或交易权限。研究切片不当生产能力用；交易接口仍只属于 custody。

## 安全

- 交易接口（`OpenSecTradeContext`、`place_order`、`unlock_trade`、`modify_order`）只允许 `custody/broker.py` 使用（测试扫描全仓库）。
- 密码、交易密码（`FUTU_TRADE_PASSWORD` / `FUTU_TRADE_PASSWORD_MD5`）、WxPusher SPT 等只放环境变量或未跟踪文件，不提交、不作命令行参数。
- 首次使用 checkout 运行 `python3 scripts/install_secret_guard.py` 安装密钥检查；不绕过提交或推送钩子。检查失败先修复，诊断不得输出密钥原文。安装、误报处理与发布包检查见 [密钥提交保护](docs/SECRET_PROTECTION.md)。

## 数据

- 只用真实行情；合成数据只用于单元测试。
- 数据不进 git，只发 GitHub Release（tag + zip + SHA256），发布后不改、新数据发新 tag，按用途分类登记在 [docs/DATA.md](docs/DATA.md)。
- 历史 K 线额度优先留给 custody 每日 `freeze`；研究只重拉已扣费标的，扣新额度要先问用户。
- 后台、定时或长期的数据采集，未经用户同意不启动。

## 研究方法

- 先预登记：假设、结构性理由、每轮 ≤ 5 个候选、选择规则与门槛；跑完不改。参数取整数或常见值，不做网格搜索。
- 选择段与验证段分开，验证段只评测一次、不调参；看完结果才想到的改动，换没用过的数据再验。
- 不为单个 case 拟合；失败照记，不改写历史结果。

### 挖掘与复刻策略的立场

别人公开做到的结果（审计过的成绩、真实交易）和用户描述的策略形态，先当作能做到，研究的任务是找出我们的版本差在哪。不要从“市场有效、技术分析无用、极端成绩多半是运气”这类大众先验出发，一开始就否定。立场不改变报告：做不到照实写。细节与例子见 [trader-replication 方法](skills/trader-replication/references/METHOD_CN.md) 第 0 节。

- **否定的是版本，不是人**：一次失败只说明“规则 X × 数据 Y × 配置 Z 下不成立”。每个否定都要指出差在哪一层（数据缺口、执行方式、规则本身、运气），不写“在公开描述之外”“无法机械化”这类全称结论。某类规则失败，先按原话换形态，再下结论；轮次预算没用完、差距没定位之前不停。
- **先保真再判效**：评价别人的方法前，先在最终决策层（实际买到的票、日子、笔数、持有期）量我们像不像他。像得少时，收益结论无论正负都不归他。有真实交易时做三层对照：他的票 + 他的执行、他的票 + 我们的执行、我们的票 + 我们的执行，差距落在哪层就改哪层。
- **尺子匹配收益结构**：先量他的胜率、盈亏比、利润集中度、持有期，再定指标。低胜率高盈亏比的策略，看账户增长相对同池随机入场的排位和大赢家出现的频率；平均 N 日收益、每笔 R 显著性、去头部检验不作否决门槛。每个环节按它在系统里的作用评：选股提供波动和大赢家，买点提供窄止损，离场拿住大赢家，仓位放大大赢家。
- **先整体后局部**：先搭一个每个环节都按原话的端到端版本，再逐环替换或去掉；不要让粗糙的占位环节把被测环节判死。每个否定都记下是在什么配置下做的，下游大改后重测；互相牵连的环节成对改。
- **证据不足时偏向原话**：样本短、收益靠少数大赢家时，“不显著”不等于“没用”。预登记的回退项设为更接近原话的版本；否掉他明确说过的规则，要有显著有害的证据。
- **对称审查**：好结果查未来函数、事后选股、极窄止损；坏结果同样查实现错误、规则之间互相挡、输入分布不对（例如把他的规则用在他不会选的股票上）。他做了并赚钱、我们却做不了的交易，在整份台账上查机制，不为单笔加例外。
- **追行为，不只追数字**：以收益为目标时，行为约束（实际买到、笔数、持有期、赢家大小）要当门槛，否则会优化出另一种赚钱方式。“收益像、交易不像”的结果标成另一种策略，不算复刻。
- **方向服从证据，不能只在旧框架里加轮次**：带入同时对照用户原始基线与整体目标，行为改善不能自动抵消收益退步；有代价的探索分支不称“最好”。先算数据、资格与触发的可达上限，上游上限不足时优先改上游，不能期待下游名额、排序或退出补齐。检查点必须审查方向，而非只复现报表。具体失败链与执行要求见 [R75–R108 复盘](studies/martin_luk/reports/POSTMORTEM_R75_R108_CN.md)及 METHOD_CN 第 9 节；这些是流程要求，不代表现有选择器已自动保证。

## 修改与验证

- 本机是 4GB VPS；大规模回测、因子研究和回归前先查内存，按标的 / 日期分块处理，不构造大规模 N×N 矩阵或无界加载全量数据。
- 文档中文；代码、标识符、提交信息英文。运行时只用标准库（连 OpenD 的入口需 `futu-api`；研究脚本可用 numpy）。
- 改哪里跑哪里的测试，`custody/tests` 每次都跑（含规范结构检查）：
  `python3 -m unittest discover -s custody/tests` · `python3 watch/test_watch.py` ·
  `python3 -m unittest discover -s studies/<切片>/tests`（有 `tests/` 的切片：us_0dte_picks、auction_strength；trend_breakout、martin_luk、trader_replication 需要 numpy，用 `/opt/futu-opend/venv/bin/python`）
- 改文档前核对代码、CLI 和已提交报告；不把约定写成尚未实现的自动保证。
- 其余文档：[README.md](README.md)（概览）、[docs/OPEND_SETUP.md](docs/OPEND_SETUP.md)（OpenD 环境）。
