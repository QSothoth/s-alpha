# s-alpha

按 skill 使用的股票研究、盯盘与美股期权协作工具。先按任务选入口，再读取该 skill 所需的资料和实现。

| Skill | 用途 | 实现与研究 |
|---|---|---|
| [opportunity-research](skills/opportunity-research/SKILL.md) | 从涨价、缺货、需求变化等线索研究机会，保留证据与反证 | 资料随 skill 保存 |
| [daily-technical-review](skills/daily-technical-review/SKILL.md) | 指定股票的日 K 技术面、条件买点与多头退出计划 | `studies/daily_technical/` |
| [trend-market-scan](skills/trend-market-scan/SKILL.md) | 三个市场的周线趋势候选、规则账户和持仓检查 | `studies/trend_breakout/` |
| [trader-replication](skills/trader-replication/SKILL.md) | 按环节逼近一位公开交易员：选人准入、交易台账、命中率、三层对照、同股票随机入场对照、三市场完整系统 | `studies/trader_replication/`、`studies/martin_luk/` |
| [trader-screens](skills/trader-screens/SKILL.md) | 交易员看板：假设研究过的交易员此刻在美股 / 港股 / A 股交易，各人今天买了什么、卖了什么、持有什么，以及彼此的交集 | `studies/trader_screens/` |
| [market-watch](skills/market-watch/SKILL.md) | 港股 / A 股 / 美股盘中只读盯盘与信号解释 | `watch/`；历史研究见归档 |
| [near-expiry-session](skills/near-expiry-session/SKILL.md) | 最近到期期权的筛选、许可、mock、持仓跟踪与复盘 | `studies/us_0dte_picks/`、`custody/` |

## 目录归属

- `skills/<名称>/SKILL.md`：任务入口；使用说明和外部参考资料放同目录的 `references/`，按需读取。
- `custody/`、`watch/`：共享执行与行情代码，保留现有 Python 模块和 CLI 路径。
- `studies/`：共享实现与待完成验证；已结束研究的结论和固定 Git 版本统一见 [归档](studies/archive/README.md)。一次性研究脚本和逐 case 输出退出当前目录。见 [实现索引](studies/AGENTS.md)。
- `docs/`：跨 skill 的执行、数据、评测与环境规范；`reports/` 保留注册策略的评测报告。
- `data/`：本地行情和运行状态，不进 Git；数据发布见 [DATA](docs/DATA.md)。

使用资料只维护一份，代码目录 README 指向所属 skill；研究记录保留原结论，不因目录整理重新评测或改变资格。项目规范见 [AGENTS.md](AGENTS.md)。

## 本机使用

首次使用先安装提交与推送前的密钥检查。新 clone 也需安装，详见 [密钥提交保护](docs/SECRET_PROTECTION.md)。

```bash
python3 scripts/install_secret_guard.py
```

本仓库的 skill 依赖同一 checkout 的代码和资料；安装时链接整个 skill 目录，相对引用按真实路径解析。已有技能链接迁移到 `skills/`，不要复制出第二份。单个技能的链接示例：

```bash
mkdir -p ~/.codex/skills
ln -s /opt/opend-us-options/skills/market-watch ~/.codex/skills/market-watch
```

命令从仓库根目录运行；连接 OpenD 使用 `/opt/opend-us-options/.venv/bin/python`。只查看策略、不连接交易账户：

```bash
python3 -m custody strategies
```

`custody/broker.py` 是唯一会下单的部分。默认策略 `zero_dte_timing_v6.6` 为 `candidate`，只能 dryrun/mock；`run --mode live` 只接受注册表中的 `accepted`。注册状态不等于评测结论 ACCEPT，当前状态和历史报告见 [注册表](custody/strategies/index.json) 与 [策略记录](docs/STRATEGY.md)。

跨技能细则：[执行](docs/RUNTIME.md)、[评测](docs/STANDARD.md)、[OpenD 环境](docs/OPEND_SETUP.md)。测试命令见 [AGENTS.md](AGENTS.md)「修改与验证」。代码采用 MIT 许可；Release 行情小样本用于个人研究和离线复现。
