# martin_luk：复刻 Martin Luk 的动量波段体系

2026-10-16 用户要求在现有数据上复刻 Martin Luk（USIC 2024 +283%、2025 +969.8%）的超额收益。结论与对照见 [FINAL_CN](reports/FINAL_CN.md)，各轮预登记在 `notes/`，结果在 `reports/`。

| 文件 | 内容 |
|---|---|
| `luk.py` | 日 K 引擎与 R1 / R4-B 规则（三市场） |
| `r1.py`、`checks.py` | R1 选择 / 验证与安慰剂 |
| `intraday.py` | 5 分钟引擎：美股 84 只（本地 5 分钟数据）与港股 138 只（本地 1 分钟聚合），R2–R7 候选（含 145 只 30 分钟名单 `prepare_k30`） |
| `r3.py` | 区间内五项检验（安慰剂、名单对半、分段、去头部、重抽样）；默认单进程，`LUK_WORKERS` 可改，但本机两核满载会被外部停机 |
| `onemin_check.py` | 用 1 分钟数据核对 5 分钟入场假设 |
| `fetch_r8.py`、`r8.py`、`r8_checks.py` | R8：新取 200 只随机抽样股票的 5 分钟数据、样本外检验与止损下限敏感性 |
| `scale.py` | 股票池宽度的影响，以及把单笔优势放大到他的笔数后的量级对账 |

数据缓存在 `data/martin-luk-cache/`（不进 git，可由原始数据重建）。只读研究，不接 custody、不产生交易许可。

```bash
/opt/futu-opend/venv/bin/python -m unittest studies.martin_luk.tests.test_luk studies.martin_luk.tests.test_intraday
nice -n 19 /opt/futu-opend/venv/bin/python -m studies.martin_luk.r3 J4   # 区间内检验（单进程约 50 分钟）
```
