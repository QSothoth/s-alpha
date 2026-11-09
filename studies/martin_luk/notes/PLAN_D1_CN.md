# D1 任务书（给 Codex，B 线）：master 为什么能买到他的行情——逐段拆解，找可移植机制

工作目录 /opt/opend-us-options/.claude/worktrees/gap-review。先读根 AGENTS.md、studies/AGENTS.md、`studies/martin_luk/notes/PI_METRIC_BRIEF_20261107_CN.md`（背景与用户需求）、`studies/martin_luk/notes/PI_METRIC_ADVICE_20261107_CN.md`（尤其 §1.3、§5.5、§6.2 master 悖论、附录）、`studies/martin_luk/reports/E16_CN.md` 第 9 节、`reports/e15_work/master_swap/README_CN.md`、`studies/trader_replication/systems.py`（master = Martin 登记版 R74 + S7）、`studies/martin_luk/ie47_e1.py`（IE47 选股）、`studies/martin_luk/notes/RULES_CN.md`（他的原话）。

约束：一律 /opt/opend-us-options/.venv/bin/python；重计算用 `systemd-run --scope -p CPUQuota=60% -p MemoryMax=900M -q`、单进程单线程（OPENBLAS_NUM_THREADS=1）。另一条 Codex 线（A 线 Y1）同时在改 `studies/trader_replication/mainleg.py`、测试、METHOD_CN 并建 `notes/legs_frozen.json`——**你不要改这些共享文件**；你的代码放 `studies/martin_luk/d1_*.py`，工件放 `reports/d1_work/`。段的划分先用现有 `mainleg.legs`（与 pi 附录相同的 42 段：2024/25/26 = 9/16/17）；若 A 线的 `notes/legs_frozen.json` 已出现，报告里注明两者差异。不联网、不拉新数据、不提交 git、不改登记版和看板。代码里禁止写入他买过的票、日期或“他买过”类特征（台账只用于评测）。

## 用户目标（2026-11-07 确认）

按结果复刻：大资金花在他的行情段上、靠他的段赚大钱。“现在不可能比 master 还差”——pi 试算 master+C062 在他的段上：2025 早买 2/16 但段内 pnl +1.33；2026 早买 7/17、段内 +0.24、毛纯度约 24%；IE47+C062 是 2026 早买 3/17、段内 −0.03、毛纯度 0%。我们要知道 master 靠什么买到、拿住、压仓他的段，再把这些机制和“对着他的票筛选”结合。

## 要做的

1. **逐段漏斗（42 段 × 三个系统：master 自身 R74+S7 执行、master+C062、IE47+C062；有 S1 台账的也加）**：在不在面板 → 进没进各自的过滤池/股票池 → 首次被选中/出信号日期 → 首次成交日期、生命周期位置 (买价−起点)/(峰值−起点)、相对他入场早晚 → 仓位（名义占权益、是否证实加仓、峰值前最大持仓）→ 持有到哪天、为什么出场 → 段内 pnl、capture。段内口径同 pi：成交落在他入场前 3 个交易日到峰值，持仓只算到 min(exit, peak)。
2. **机制归因**：master 买到而 IE47 没买到（或买晚、拿短、仓位小）的段，逐段说清是哪一层造成：股票池（master 的大成交额动量池 vs IE47 的过滤池）、排名、触发方式（master 收盘信号 vs IE47 观察 5 晚的收盘突破）、观察期过期、格子/每日名额、仓位规则、离场规则。反过来 IE47 赢 master 的段也列出。
3. **他的段在起涨时的日 K 画像**：在每段合格买入窗口的头几晚（他入场前 3 天到剩一半涨幅为止），这些票相对同晚 master 池 / IE47 过滤池 / 全流动性范围的分位（成交额、ADR、1/3/6 个月涨幅、离 52 周高、EMA 排列、量比、内包/窄幅、跳空等现有指标库 v1.1 的项）。目的：找“能把他的票筛出来”的稳定差异，并检查 master 的过滤与 IE47 的过滤各漏掉了他的哪些段。只做描述，不拟合、不选参数。
4. **可移植机制清单**：基于 1–3，列出 ≤ 8 条具体、可实现、无未来函数的改动建议（选股池、点名时机、触发、观察期、仓位分配给“像他的段”、离场），每条写：机制、证据（哪些段、多少 pnl）、预计影响哪个目标指标（资金占用纯度、毛利纯度、早买段、吃到、前 10 赢单）、和他原话的对应。

## 输出

报告 `studies/martin_luk/reports/D1_CN.md`（中文、先结论、白话表格），工件 `reports/d1_work/`。终端最后 10 行以内摘要。
