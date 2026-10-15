# 项目规范

> 先读本文件，再读要改的目录的 `AGENTS.md`；使用细节在各 skill 的 `references/`，共用规范在 `docs/`，代码目录 README 指路。每个 `CLAUDE.md` 只有一行 `@AGENTS.md`（测试强制）。

## 按 skill 组织

入口统一放 `skills/<名称>/SKILL.md`，使用说明与外部资料放各自 `references/`；共享代码保留原模块路径，研究预登记与结果保留在 `studies/`。使用资料不在代码目录重复维护，跨技能规范留在 `docs/`。新增能力优先扩展所属 skill，不为每个脚本或失败研究单建 skill。

| 任务入口 | 实现规范 |
|---|---|
| [opportunity-research](skills/opportunity-research/SKILL.md)：机会与反证研究 | [studies/AGENTS.md](studies/AGENTS.md) |
| [daily-technical-review](skills/daily-technical-review/SKILL.md)：单股日 K 多头评估 | [studies/AGENTS.md](studies/AGENTS.md) |
| [trend-market-scan](skills/trend-market-scan/SKILL.md)：全市场周线规则扫描 | [studies/AGENTS.md](studies/AGENTS.md) |
| [market-watch](skills/market-watch/SKILL.md)：盘中只读盯盘 | [watch/AGENTS.md](watch/AGENTS.md) |
| [near-expiry-session](skills/near-expiry-session/SKILL.md)：近到期期权会话 | [custody/AGENTS.md](custody/AGENTS.md)、[studies/AGENTS.md](studies/AGENTS.md) |

Skill 是任务入口，不改变实现的成熟度、策略资格或交易权限。研究切片不当生产能力用；交易接口仍只属于 custody。

## 安全

- 交易接口（`OpenSecTradeContext`、`place_order`、`unlock_trade`、`modify_order`）只允许 `custody/broker.py` 使用（测试扫描全仓库）。
- 密码、交易密码（`FUTU_TRADE_PASSWORD` / `FUTU_TRADE_PASSWORD_MD5`）、WxPusher SPT 等只放环境变量或未跟踪文件，不提交、不作命令行参数。

## 数据

- 只用真实行情；合成数据只用于单元测试。
- 数据不进 git，只发 GitHub Release（tag + zip + SHA256），发布后不改、新数据发新 tag，按用途分类登记在 [docs/DATA.md](docs/DATA.md)。
- 历史 K 线额度优先留给 custody 每日 `freeze`；研究只重拉已扣费标的，扣新额度要先问用户。
- 后台、定时或长期的数据采集，未经用户同意不启动。

## 研究方法

- 先预登记：假设、结构性理由、每轮 ≤ 5 个候选、选择规则与门槛；跑完不改。参数取整数或常见值，不做网格搜索。
- 选择段与验证段分开，验证段只评测一次、不调参；看完结果才想到的改动，换没用过的数据再验。
- 不为单个 case 拟合；失败照记，不改写历史结果。

## 修改与验证

- 本机是 4GB VPS；大规模回测、因子研究和回归前先查内存，按标的 / 日期分块处理，不构造大规模 N×N 矩阵或无界加载全量数据。
- 文档中文；代码、标识符、提交信息英文。运行时只用标准库（连 OpenD 的入口需 `futu-api`；研究脚本可用 numpy）。
- 改哪里跑哪里的测试，`custody/tests` 每次都跑（含规范结构检查）：
  `python3 -m unittest discover -s custody/tests` · `python3 watch/test_watch.py` ·
  `python3 -m unittest discover -s studies/<切片>/tests`（有 `tests/` 的切片：us_0dte_picks、auction_strength、us_opening_range；trend_breakout 需要 numpy，用 `/opt/futu-opend/venv/bin/python`）
- 改文档前核对代码、CLI 和已提交报告；不把约定写成尚未实现的自动保证。
- 其余文档：[README.md](README.md)（概览）、[docs/OPEND_SETUP.md](docs/OPEND_SETUP.md)（OpenD 环境）。
