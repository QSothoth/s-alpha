# martin_luk：复刻 Martin Luk 的动量波段体系

2026-10-16 用户要求在现有数据上复刻 Martin Luk（USIC 2024 +283%、2025 +969.8%）的超额收益；R1–R18 的结论与对照见 [FINAL_CN](reports/FINAL_CN.md)。2026-10-17 起作为 [trader-replication](../../skills/trader-replication/SKILL.md) 的第一个例子，用他公开的 137 笔真实交易逐环节逼近（第一阶段 R19–R28 按像不像与超额；第二阶段 R29–R74 直接逼近他的收益），过程与结论见 [REPLICATION_CN](reports/REPLICATION_CN.md)，逐轮记录见 [ROUNDS_CN](notes/ROUNDS_CN.md)。各轮预登记在 `notes/`（R42 起候选在 `notes/rounds/R*.json`），结果在 `reports/`。

R74检查点（样本内、同段择优）：美股 2024 +288%（他 +283%）、2025 +221%（他 +970%）、2026 至 10-16 +95%，回撤 61%，同池随机入场中位 −48%；同一配置港股 −67%、A 股 −41%。系统实际买到他的有日期买入只有 5/42、0/40；2024 年主要来自 1–2 月开的三笔，晚两三个月开始跑只剩 +6%～+25%。不是对他交易的复刻，也不是交易依据。

| 文件 | 内容 |
|---|---|
| `notes/trades.csv`、`notes/RULES_CN.md` | 他的交易台账（访谈逐笔复盘 + 本人直播，2026-10-17 冻结）、按环节整理的原话与出处 |
| `replicate.py` | R19–R74：股票池、强度、名单、形态、入场（含 5 分钟随机样本）、离场、仓位市况、空头、三市场完整系统；`round R42`… 运行 `notes/rounds/` 里的轮次，`diagnose` / `robust` / `final` 做逐笔诊断、稳健性和三市场复算；通用部分在 `studies/trader_replication/` |
| `luk.py` | 日 K 引擎与 R1 / R4-B 规则（三市场） |
| `r1.py`、`checks.py` | R1 选择 / 验证与安慰剂 |
| `intraday.py` | 5 分钟引擎：美股 84 只（本地 5 分钟数据）与港股 138 只（本地 1 分钟聚合），R2–R7 候选（含 145 只 30 分钟名单 `prepare_k30`）；`prepare_r8` 读 R8 随机抽样的 200 只 |
| `r3.py` | 区间内五项检验（安慰剂、名单对半、分段、去头部、重抽样）；默认单进程，`LUK_WORKERS` 可改，但本机两核满载会被外部停机 |
| `onemin_check.py` | 用 1 分钟数据核对 5 分钟入场假设 |
| `fetch_r8.py`、`r8.py`、`r8_checks.py` | R8：新取 200 只随机抽样股票的 5 分钟数据、样本外检验与止损下限敏感性 |
| `selection.py`、`r10.py`、`r12.py` | R9/R11 全市场日 K 按当时条件的选股检验，R10/R12 选股 + 交易规则 |
| `strength.py`、`r16.py`、`r17.py` | R13–R18 逐环节优化（强度定义、名单、形态、题材、止损、收盘确认完整系统） |
| `scale.py` | 股票池宽度的影响，以及把单笔优势放大到他的笔数后的量级对账 |

数据缓存在 `data/martin-luk-cache/`（不进 git，可由原始数据重建）。只读研究，不接 custody、不产生交易许可。

2026-10-18 起继续研究，无轮次上限，完成标准为用户指定的收益与行为记分板，见 `notes/ROUNDS_CN.md` 的 R75 起章节。R75、R76、R78–R81已有报告；R81按持有期目标带入EMA9_STOP，行为改善但2025亏损−11.20%，下一轮修复收益。R77分钟执行因源数据价格差异尚未评测，R75分钟配对亦保留此限制。当前配置/运行状态以PROGRESS为准，历史失败不删除。

- `measure.py`：R75 三层对照、逐文件分钟覆盖与配对执行诊断、完整记分板和头部价格核对。
- `continue_round.py`：R76 起行为门槛轮次入口，额外约束分段实际买到、指定日期买到、笔数/持有目标偏差、3 月起跑。
- `minute_retest.py`：按真实分钟顺序执行、核对价格/覆盖及日线/分钟管理；R77严格模式在价格异常时停止。R91起显式登记的供应商条件诊断保留异常与持仓暴露，不能据此带入全市场；R97比较原始信号名额与实际成交名额，零值代表不限额；R98测试失败后新日内区间重入，并按台账日期记录引擎实际拒绝原因；R99比较当时可知排名与流动性分组；R100增加已完成小时支撑及前根K突破的条件诊断；R101比较当日低点与短K结构止损、实际名额，并逐成交回放初始止损。R102只读重放补齐窗口成交/拒绝原因、原始触发来源及真实重入时间轴；measurement_only不选配置，精确复现后才可复用冻结随机汇总。R103在首次触发不变的前提下，比较重入时重新满足原入场条件或收回首根五分钟高点，并配对实际名额政策。
- `tests/test_measure.py`：完成 K 线时点、跳空止损、小仓位分批和离场、行为门槛检查。

新入口：`nice -n 19 env OPENBLAS_NUM_THREADS=1 /opt/futu-opend/venv/bin/python -m studies.martin_luk.measure`（R75）、同样前缀下 `-m studies.martin_luk.continue_round R76`。原 `replicate round` 仍保留旧目标，不用于 R75 起的新行为门槛。每次运行前查 PROGRESS，避免重复已完成轮次。

```bash
PY="nice -n 19 /opt/futu-opend/venv/bin/python"
$PY -m unittest studies.martin_luk.tests.test_luk studies.martin_luk.tests.test_intraday studies.martin_luk.tests.test_replicate
$PY -m studies.martin_luk.replicate r19   # 之后按顺序：r20 … r28（第一阶段）、r29 … r41（第二阶段前半）
$PY -m studies.martin_luk.replicate round R42   # R42 … R74：读 notes/rounds/R*.json，写 reports/r42.json …
$PY -m studies.martin_luk.replicate diagnose r74.json   # 他的每笔有日期多头卡在哪一步、头部交易
$PY -m studies.martin_luk.replicate robust r74.json     # 稳健性（只报告）
$PY -m studies.martin_luk.replicate final r74.json      # 美 / 港 / A 股完整结果
$PY -m studies.martin_luk.r3 J4            # 区间内检验（单进程约 50 分钟）
```

后一轮读取前一轮报告里的 `chosen` / `passed`，所以要按顺序跑；第一阶段每轮几分钟，R24/R24b（5 分钟样本）和 R28（三个市场）各约 10–20 分钟；第二阶段每轮（5 个候选 + 参照，各 100 次安慰剂）约 20 分钟。

R104检查点见 [CHECKPOINT_R104_CN](reports/CHECKPOINT_R104_CN.md)：固定三市场结果与R94一致，R95–R104全市场无新带入；分钟条件参照R98，完整窗口诊断定位资格/首次触发/市场门槛上限。当前状态与下一轮编号见PROGRESS。
