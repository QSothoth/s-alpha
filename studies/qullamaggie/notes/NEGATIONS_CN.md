# Qullamaggie 否定登记表

每个没被带入的候选一行（自动写入）；“当时的配置”一列是那一轮的基础配置报告。下游大改后，用 `negations` 动作列出依赖旧配置的行，在新配置上重测。

| 轮次 | 环节 | 候选 | 改了什么 | 当时的配置 | 带入 | 否定依据 | 状态 |
|---|---|---|---|---|---|---|---|
| R1 | end_to_end | Q1 | `{"setups": ["ep"]}` | r0.json:chosen | Q5 | gates: placebo；全区间 -20%（带入 +33%） | open |
| R1 | end_to_end | Q2 | `{"stop_adr": {"brk": 1.0, "ep": 3.0}}` | r0.json:chosen | Q5 | gates: placebo；全区间 -32%（带入 +33%） | open |
| R1 | end_to_end | Q3 | `{"setups": ["ep"], "stop_adr": {"ep": 3.0}}` | r0.json:chosen | Q5 | gates: placebo；全区间 -34%（带入 +33%） | open |
| R1 | end_to_end | Q4 | `{"setups": ["ep"], "stop_adr": {"ep": 3.0}, "rule_opts": {"trail": "ema20", "trim_day_breakeven": true}}` | r0.json:chosen | Q5 | gates: placebo；全区间 -28%（带入 +33%） | open |
