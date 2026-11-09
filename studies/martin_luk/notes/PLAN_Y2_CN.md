# Y2 任务书（给 Codex，A 线）：按“主升浪生命周期”口径并列重算纯度（只读对照）

工作目录 /opt/opend-us-options/.claude/worktrees/gap-review。先读根 AGENTS.md、`studies/martin_luk/notes/PI_METRIC_BRIEF_20261107_CN.md`、`reports/Y1_CN.md`（现行 H 窗口 = 他入场前 3 个交易日 → 峰值，lot 按成交日归段）、`reports/U1_CN.md`（统一起点中位比 Y1 的 H 窗口早 16 个交易日，45 个同峰段中 33 个首次可买早于 H 窗口）、`skills/trader-replication/references/METHOD_CN.md` 第 11 节、`studies/trader_replication/mainleg.py`、`studies/martin_luk/reports/funnel_work/leg_position.py`。

约束：.venv python；`systemd-run --scope -p CPUQuota=60% -p MemoryMax=900M -q`、单进程单线程。另一条 Codex 线 F3 同时在跑（`studies/martin_luk/f3_*`、`reports/f3_work/`），不要改它们。**本轮只读，不改 Y1 现行函数的默认行为和已有报告**；如需新函数，以新参数/新函数加入 mainleg.py（默认不变）并补单测。不联网、不拉新数据、不提交 git。

## 背景

用户 2026-11-06 的指导：“你又没交割单，怎么知道他买的时间……我们自己的信号选的就要早，从个股主升浪的生命周期来看。”生命周期：起点 = 峰值前 60 个交易日内最低点，终点 = 峰值。Y1 的 H 窗口从“他入场前 3 天”开始，lot 按成交日归段：我们在他入场前更早买入并一路持有穿过他的整段行情，这部分钱和利润目前全部算成“不是他的段”。

## 要做的

1. 在 mainleg 增加生命周期口径（新参数，默认关）：H 窗口 = [生命周期起点, 峰值]；**持仓按时间切片**归段——任何 lot（不论何时买入）在窗口内的持有天数、名义与 pnl 切片计入 H，窗口外部分计入 O（与现行 post_peak 切片同法）。早买判定仍为“首个窗口内持有日的成本价处剩他涨幅 ≥ 一半”（写清公式）。补单测（时间切片、跨窗口 lot、同票多段不重复、现金进分母）。
2. 用两种口径并列重算：IE47+C062、master+C062、登记 master、M1B、M2A、M3B（2024/2025/2026 连续账户；有单开的也报）。五条目标线、H、O、资金/毛利纯度、早买、吃到、前 10 赢单。
3. 解释两种口径差在哪些段、哪些 lot（列出差额最大的 10 个段），并判断：生命周期口径是否会把“与他无关的早期仓位”也算进来（例如在段起点前很久买、窗口内只是顺带持有）——给出审计数（窗口内持有但首次买入早于起点 > 20 个交易日的 pnl 占比）。

## 输出

报告 `studies/martin_luk/reports/Y2_CN.md`（中文、先结论、白话表格），工件 `reports/y2_work/`（含 completion.json，三组测试结果）。终端最后 10 行以内摘要。不得改动 Y1 已发布数字。
