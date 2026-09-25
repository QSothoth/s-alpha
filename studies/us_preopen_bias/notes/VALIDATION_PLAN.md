# 验证段评测计划（2026-09-24，运行前写定）

按 [S5](S5_PREREG.md) 的入围规则，从 S1–S5 的选择段结果中入围：

| 槽 | 入围 | 选择段胜率 | 来源 |
|---|---|---|---|
| 恐慌做多一族最高 | `E4_daily_top_fear` | 62.8%（n=290） | [S3](S3_PREREG.md) |
| 可交易槽 | `G2_daily_top_fear_0dte` | 62.7%（n=228） | [S5](S5_PREREG.md) |
| 其他机制 | `C1_call_chase_fade` | 57.3%（n=225） | [S1](S1_PREREG.md) |
| 做空侧 | 空缺（S4 全部失败） | | [S4](S4_PREREG.md) |

验证段 2025-07-01 → 2026-09-23，加载 `preopen-us-train-v1` + `preopen-us-valid-v1`（前者只用于特征热身），**只运行一次**（`code/validate.py`），
每个入围者三项都满足才算成立：胜率 ≥ 53%、按交易日重抽的 90% 区间下限 > 50%、超额 > 0。
只评测这三个；其他候选不在验证段上看。结论最高 PROVISIONAL。
