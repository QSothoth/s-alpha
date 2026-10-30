---
name: near-expiry-session
description: 在 opend-us-options 中协同用户完成美股最近到期期权的筛选、入场审视、mock 观察、持仓跟踪、异常恢复和盘后复盘。用于“今天运行”“准备买什么”“怎么样了”“今天不交易”“mock 跑下”“搞完反思”和交易流程改进；沿用现有 custody 执行工具。
---

# 最近到期期权：筛选 → 许可 → 一分钟择时 → 持仓退出

工程根目录 `/opt/opend-us-options`；连接 OpenD 用 `/opt/opend-us-options/.venv/bin/python`。先读根 `AGENTS.md`，再读涉及的 `studies/AGENTS.md`、`custody/AGENTS.md`。安装入口是仓库符号链接，相对链接按 `realpath` 解析。

## 两层策略

1. **日线筛选**：`prepare_watch` 在盘前冻结昨收、ATR、财报反应日及放量宽幅背景，从固定11只科技股池形成候选。当前排序是研究启发式，尚无验证通过的严格日线门槛；没有合格输入则停止。选股与择时研究尚无通过交易版本（[失败记录](../../studies/archive/us_0dte_picks/FAILED_TRIALS.md)）；VR1仅波动预测通过，股票R不能替代真实期权收益。
2. **日内择时**：当前为 `zero_dte_timing_v6.6`，每只 CALL/PUT 独立看已完成的正股1m，哪边先出有效信号才交接；无信号不买，无兜底入场。持仓由 custody 管止损、保本、跟踪、无进展、模型止盈/锁盈和尾盘退出。该版本是 candidate，仅 dryrun/mock；更早入场与趋势持有版本通过正股和真实期权验证后再接入。

## 一次明确许可，串起流程

每次进入或恢复先读实际美东时间，并执行 `python3 -m studies.us_0dte_picks.session status --session SESSION`；核对扫描、卡片、mock、任务、成交及仓位。扫描停止不等于已平仓。已有会话沿用原 DB、ledger 和 job，禁止换库绕过去重。

- 盘前：按 [WORKFLOW_CN](references/WORKFLOW_CN.md) 运行 `prepare_watch`、`launch_watch --check-only`，冻结输入并预检。先只准备，再让人类选标的；`launch_watch --symbols AAPL,NVDA` 将扫描限制在所选范围，未知或空范围直接拒绝。
- 向人类给出几只候选、筛选理由、策略验证状态及预算，让其选择标的，并明确当日模式、账户、预算、截止时间及买卖权限。用 `session authorize` 先预览，取得明确许可后加 `--execute` 固定标的、模式、账户、策略SHA及截止时间；`auto_watch` 在该范围接受后续有效信号，不逐卡重复提问。研究授权不等于下单授权，新的交易日不沿用昨日实盘许可。
- 人工已有观点时用 `--plan-json` 固定每只股票的 `directions`（CALL/PUT，空列表只观察）、`thesis`、`invalidation`；全部所选股票都要覆盖。程序检查方向，文字失效条件由人判断，变化先撤销新增入场。`accept/mock_watch` 也遵守已有许可；自动跳过留原卡片与 `SKIPPED_TRADE_PLAN`，用于后续对照。具体JSON见 [WORKFLOW_CN](references/WORKFLOW_CN.md)。
- 有新鲜信号：`auto_watch` 沿用 `session accept` 的预检与交接；人工单卡仍可先预览再显式模式接受，paper/live 必须明确账户。报价过时、价差、预算、权限或用户限制不合格则跳过并记原因；过期卡不延长追单。程序拒绝不可由 agent 绕过。方向由信号确定，agent 不凭图形审美否决。
- 成交后：核对同库订单实际成交，记录信号→报价→接受→任务→成交时刻。round_trip 的观察截止不停止持仓管理；当前 bid 损益与进程运行状态分开汇报，异常先对账再恢复原任务。
- 收盘：按 [TRADING_OBSERVATION_CN](references/TRADING_OBSERVATION_CN.md) 复盘交易、耗时、错过信号、退出、错误与数据缺口；模拟、实际成交和未成交反事实分别记录。不按单日峰值调参数。

## 执行边界

当前工程固定每笔1张、每天每模式最多2个不同标的、300美元预算减20预留后权利金总上限280；明确选1只上限280，选至少2只各140，信号分开出现也保持分配；实际花得少不释放预留。不同预算先改工程约束。`mock=dryrun` 是本地模拟；paper 会发券商模拟委托，live 会花真钱，不能自行切换。

不从工程预算推断账户本金。人明确金额后，`authorize` 可加 `--max-loss-usd`（仅dryrun/paper round_trip真实成本/bid亏损退出）及 `--loss-budget-start-date/--loss-budget-usd`（跨日共享交接账本亏损预算），两者均需显式 `--estimated-round-trip-fee-per-contract-usd`。预算按累计估计净亏损和完整未结束权利金预留检查，不把计划止损当最大可能损失；不覆盖外部手工交易。金额、范围与CLI见运行细则，缺金额不自行猜。

`round_trip` 允许当日买卖；`buy_only` 只买，止损/stop也不能卖，`HELD` 为留仓；`sell_only` 直接走 custody，需核实平均成本及持仓，首版仅 dryrun/paper。用户取消新入场时用 `session revoke --execute` 撤销后续自动交接，再停止本会话扫描；已有委托和仓位仍走 custody 受控处理。

启动后台前须说明 unit、任务与截止时间、agent 实际跟进能力及通知方式；当前会话 worker 无主动推送。未获许可不启动持续采集。当前 v6.6 为低胜率、依赖少数大单的结构，原模型保护不等于实际成本/bid保护；可选金额退出未获收益验证且不保证成交价。最近到期执行也不证明非0DTE收益。

不走策略、按人工指令在一个时间段内买入或卖出（只卖已有多头），用 custody 的 `--manual` 智能买 / 智能卖（到点必成交、同合约可挂多张、可选场景剧本、中间价追价、每日权利金上限），见 [RUNTIME 1b](../../docs/RUNTIME.md)；它不受本会话 1 张 / 280 美元的工程约束，也不是验证过的策略。

准确 CLI、预算/权限细节、后台检查、mock/取消、故障恢复和证据口径见 [运行细则](references/SESSION_OPERATIONS_CN.md) 与 [RUNTIME](../../docs/RUNTIME.md)。遇到异常先读对应章节，不能靠简化本文删去恢复和授权要求。
