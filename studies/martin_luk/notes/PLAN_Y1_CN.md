# Y1 任务书（给 Codex，A 线）：账户层新尺子 + 新基准

工作目录 /opt/opend-us-options/.claude/worktrees/gap-review。先读根 AGENTS.md、studies/AGENTS.md、`studies/martin_luk/notes/PI_METRIC_BRIEF_20261107_CN.md`（背景与用户需求）、`studies/martin_luk/notes/PI_METRIC_ADVICE_20261107_CN.md`（pi 的完整设计，第 1–5 节和附录是本任务的规格来源）、`skills/trader-replication/references/METHOD_CN.md` 第 11 节、`studies/trader_replication/mainleg.py` 与 `tests/test_mainleg.py`、`studies/martin_luk/reports/E16_CN.md` 第 9 节。

约束：一律 /opt/opend-us-options/.venv/bin/python；重计算用 `systemd-run --scope -p CPUQuota=60% -p MemoryMax=900M -q`、单进程单线程（OPENBLAS_NUM_THREADS=1）；另一条 Codex 线（B 线 D1）同时在跑，**不要改 B 线的文件**（`studies/martin_luk/d1_*`、`reports/d1_work/`），B 线也不改你的。不联网、不拉新数据、不提交 git、不改登记版（R74+S7）和看板。不得有未来函数（评测标签可以用未来峰值，但账户决策代码不得读取）。

## 用户已确认的口径（2026-11-07）

- **按结果复刻**：目标是“大资金花在他的行情段上、靠他的行情段赚大钱”。利润集中在少数大单是目标，问题只在大单是否在他的段上。master 登记版选股作为正式基准，不排除。
- 一切按**账户真实成交**算；“他的票”按**他的行情段窗口**（他入场前 3 个交易日 → 峰值，持仓只算到 min(exit, peak)），ticker-year 只作上限诊断。
- 五条目标线（分年报，2026 只测一次）：① 资金占用纯度（他的段敞口 / 权益日，现金进分母）≥ 50%；② 毛利纯度（段窗口）≥ 60%；③ 早买段（真实成交、剩他涨幅 ≥ 一半）≥ 一半段数；④ 段吃到（capture_total，lot 加权）≥ 50%；⑤ 前 10 赢单中他的段 ≥ 5 笔。底线：每年 ≥ 52 笔、胜率 ≤ 35%。过程指标（synced、offset）只报告。
- 另报：净纯度（总 pnl ≤ 0 时为 None）、他的段绝对 pnl（H 书）、其他票净贡献（O 书）、T1/T2/T3 分桶、确认仓资金纯度、capture_rem、截断段含/不含两行、事件段（duration < 5）分层。

## 要做的

1. **冻结段表**：按 pi §1.2(3) 解决 42 vs 46 段分母不一致，产出唯一段表 `studies/martin_luk/notes/legs_frozen.json`（code、锚点、precision、first、peak、top、gain、duration、censored、可达性与原因）。说明选择理由，所有后续报告引用它。
2. **`studies/trader_replication/mainleg.py`**：按 pi §5.1 新增账户层函数（lots / capital_days / leg_at / account_coverage / account_purity / summary_account 或你认为更好的等价设计），不依赖台账 JSON schema（适配层放研究脚本）。旧 `coverage` 等保留、文档标为“选股层信号诊断”，旧报告数字不变。pi 指出的 `room` 用加仓价重置的问题：新函数用首笔 gain，旧函数不改。
3. **单测**：pi §5.2 的 18 条（可合并或补充），放 `studies/trader_replication/tests/test_mainleg.py` 或新文件。
4. **METHOD_CN §11 改写**：按 pi §5.3，写明信号覆盖不是成绩、新公式、目标线、禁止事项；旧内容保留为历史小节。同步 `skills/trader-replication/references/MARTIN_LUK_CN.md` 中引用 §11 的地方。
5. **新基准表**（同一段表、同一公式）：IE47+C062、IE47+S1、IE47+K2、master+C062、master+S1、master+K2（有台账的都算，缺的标明），master 自己的 R74 执行（若有台账），以及“只保留他的段（H 书）”反事实。台账位置：`reports/e21_work/`（BASE_*、S1_*、master/）、`reports/e15_work/`（含 master_swap）。分年 2024/2025/2026。
6. 选股层诊断（不拟合）：对 IE47 与 master 的点名/信号，报 C_signal、C_trig（点名后 5 晚内收盘突破前高且仍剩一半）、P_opp、E、K=1/2/3 覆盖（pi §3.2）。

## 输出

报告 `studies/martin_luk/reports/Y1_CN.md`（中文、先结论、白话表格），工件 `reports/y1_work/`（含 completion.json：三组测试 martin_luk、trader_replication、custody 的结果）。终端最后 10 行以内摘要。
