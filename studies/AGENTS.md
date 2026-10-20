# studies：共享实现、待完成验证与研究归档

> 全仓库规则见 [../AGENTS.md](../AGENTS.md)。用户任务从顶层 [skill 入口](../README.md) 进入；本目录的实现不因提供 skill 入口而自动获得生产或交易资格。

## 当前保留

| 目录 | 归属与保留理由 |
|---|---|
| [daily_technical/](daily_technical/README.md) | `daily-technical-review` 的日 K 计算实现 |
| [us_0dte_picks/](us_0dte_picks/README.md) | `near-expiry-session` 的会话及共享计算 |
| [trend_breakout/](trend_breakout/README.md) | `trend-market-scan` 的最终方案、扫描、复算与测试；同段择优、无独立样本外资格 |
| [martin_luk/](martin_luk/README.md) | 复刻 Martin Luk 动量波段的研究（2026-10-16）及 `trader-replication` 的第一个例子（R19–R74）；区间内同段择优结论、无样本外，不接 custody、不当生产能力 |
| [trader_data/](trader_data/README.md) | `trader-replication` 与 `trader-screens` 共用的日 K 数据接口：冻结 Release 与 live 增量（frozen / live 开关）、唯一的面板构建 |
| [trader_replication/](trader_replication/README.md) | `trader-replication` 的通用代码：交易台账、命中率、同日同波动组超额、多空日 K 组合与安慰剂 |
| [trader_screens/](trader_screens/README.md) | `trader-screens`（交易员看板）的实现：运行 `trader_replication/systems.py` 登记的各交易员系统（与横向比对同一实现），看板模板与交集；按原话的买点定义（研究模块引用） |
| [auction_strength/](auction_strength/README.md) | 既有竞价例程接口；仅 3 天样本、门槛未校准，不新增独立 skill 或宣传为已验证能力 |

## 交易员资料索引

[trader_registry/README.md](trader_registry/README.md) 提供35份来源档案、风格索引和只读代码注册表。实现状态以 main 的实际代码为准，历史研究分支单独注明；资料覆盖不是策略实现或验证资格。

## 归档与新研究

已结束研究的结论、失败经验与固定版本入口见 [archive/](archive/README.md)。W 系列、P/TS/FD、R27–R30 已归档；历史 TF/PB 已收敛。新研究前先查这些记录，归档不重置数据是否已使用，也不改写预登记、源码指纹或失败结论。

- 使用手册放 `skills/<名称>/references/`，跨 skill 规则放 `docs/`，研究实现可以共享。
- 待完成研究按主题放预登记 `notes/` 与结果 `reports/`；归档前查调用者，保留运行、测试、冻结输入和定时任务所依赖的文件。
- 已结束研究在 `archive/` 保留结论与可恢复的固定 Git 版本；一次性脚本、逐 case 输出与对应研究测试退出当前目录，不保留第二套可误用的运行入口。
- 切片升级为核心能力由用户决定；目录归档与 skill 注册均不改变资格。
