# studies：共享实现、待完成验证与研究归档

> 全仓库规则见 [../AGENTS.md](../AGENTS.md)。用户任务从顶层 [skill 入口](../README.md) 进入；本目录的实现不因提供 skill 入口而自动获得生产或交易资格。

## 当前保留

| 目录 | 归属与保留理由 |
|---|---|
| [daily_technical/](daily_technical/README.md) | `daily-technical-review` 的日 K 计算实现 |
| [us_0dte_picks/](us_0dte_picks/README.md) | `near-expiry-session` 的会话及共享计算；SV1/SV2 验证尚未完成，不能按日历推定通过 |
| [trend_breakout/](trend_breakout/README.md) | `trend-market-scan` 的最终方案、扫描、复算与测试；同段择优、无独立样本外资格 |
| [us_opening_range/](us_opening_range/README.md) | SV1 的兼容采集路径，被已登记定时任务引用，保留模块名 |
| [auction_strength/](auction_strength/README.md) | 既有竞价例程接口；仅 3 天样本、门槛未校准，不新增独立 skill 或宣传为已验证能力 |

## 归档与新研究

已结束研究的结论、失败经验与固定版本入口见 [archive/](archive/README.md)。W 系列、P/TS/FD、R27–R30 已归档；历史 TF/PB 已收敛。新研究前先查这些记录，归档不重置数据是否已使用，也不改写预登记、源码指纹或失败结论。

- 使用手册放 `skills/<名称>/references/`，跨 skill 规则放 `docs/`，研究实现可以共享。
- 待完成研究按主题放预登记 `notes/` 与结果 `reports/`；归档前查调用者，保留运行、测试、冻结输入和定时任务所依赖的文件。
- 已结束研究在 `archive/` 保留结论与可恢复的固定 Git 版本；一次性脚本、逐 case 输出与对应研究测试退出当前目录，不保留第二套可误用的运行入口。
- 切片升级为核心能力由用户决定；目录归档与 skill 注册均不改变资格。
