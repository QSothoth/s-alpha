# martin_luk：复刻 Martin Luk 的动量波段体系

2026-10-16 用户要求在现有数据上复刻 Martin Luk（USIC 2024 +283%、2025 +969.8%）的超额收益；R1–R18 的结论与对照见 [FINAL_CN](reports/FINAL_CN.md)。2026-10-17 起作为 [trader-replication](../../skills/trader-replication/SKILL.md) 的第一个例子，用他公开的 137 笔真实交易逐环节逼近（R19–R28），过程与结论见 [REPLICATION_CN](reports/REPLICATION_CN.md)。各轮预登记在 `notes/`，结果在 `reports/`。

| 文件 | 内容 |
|---|---|
| `notes/trades.csv`、`notes/RULES_CN.md` | 他的交易台账（访谈逐笔复盘 + 本人直播，2026-10-17 冻结）、按环节整理的原话与出处 |
| `replicate.py` | R19–R28：股票池、强度、名单、形态、入场（含 5 分钟随机样本）、离场、仓位市况、空头、三市场完整系统；通用部分在 `studies/trader_replication/` |
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

```bash
PY="nice -n 19 /opt/futu-opend/venv/bin/python"
$PY -m unittest studies.martin_luk.tests.test_luk studies.martin_luk.tests.test_intraday studies.martin_luk.tests.test_replicate
$PY -m studies.martin_luk.replicate r19   # 之后按顺序：r20 r21 r21b r22 r22b r23 r23b r23c r24 r24b r25 r26 r27 r27b r28
$PY -m studies.martin_luk.r3 J4            # 区间内检验（单进程约 50 分钟）
```

后一轮读取前一轮报告里的 `chosen` / `passed`，所以要按顺序跑；每轮几分钟，R24/R24b（5 分钟样本）和 R28（三个市场）各约 10–20 分钟。
