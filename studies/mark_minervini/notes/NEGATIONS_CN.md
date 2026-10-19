# Mark Minervini 否定登记表

每个没被带入的候选一行（自动写入）；“当时的配置”一列是那一轮的基础配置报告。下游大改后，用 `negations` 动作列出依赖旧配置的行，在新配置上重测。

| 轮次 | 环节 | 候选 | 改了什么 | 当时的配置 | 带入 | 否定依据 | 状态 |
|---|---|---|---|---|---|---|---|
| S1 | short: B-grade baseline (stage-4 template turned over, breakdown, stop above the recent high) | MA | `{"setups": ["s4"], "gate": "below50", "max_new": 2, "trail": "sma50", "trims": [], "max_days": 0}` | :chosen | none | gates: long_behaviour, down | open |
| S1 | short: B-grade baseline (stage-4 template turned over, breakdown, stop above the recent high) | MB | `{"setups": ["s4"], "gate": "", "max_new": 2, "trail": "sma50", "trims": [], "max_days": 0}` | :chosen | none | gates: long_behaviour, total, years, down | open |
