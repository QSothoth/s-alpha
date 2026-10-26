# Emanuela Elias 否定登记表

每个没被带入的候选一行（自动写入）；“当时的配置”一列是那一轮的基础配置报告。下游大改后，用 `negations` 动作列出依赖旧配置的行，在新配置上重测。

| 轮次 | 环节 | 候选 | 改了什么 | 当时的配置 | 带入 | 否定依据 | 状态 |
|---|---|---|---|---|---|---|---|
| R1 | short gate / stop / hold | H10 | `{"rule_opts": {"max_days": 10, "short_max_days": 10}}` | :base | SL1 | objective below SL1；全区间 -6%（带入 -22%） | open |
| R1 | short gate / stop / hold | SG50 | `{"short_gate": 50}` | :base | SL1 | gates: placebo；全区间 +5%（带入 -22%） | open |
| R1 | short gate / stop / hold | SG50SL1 | `{"short_gate": 50, "stop_level": 0.01}` | :base | SL1 | objective below SL1；全区间 +13%（带入 -22%） | open |
| R1 | short gate / stop / hold | TOP10 | `{"top": 10}` | :base | SL1 | gates: placebo；全区间 -16%（带入 -22%） | open |
| R2 | level / hold / list | B2 | `{"band": 0.02}` | r1.json:chosen | H10 | objective below H10；全区间 +6%（带入 +29%） | open |
| R2 | level / hold / list | LV50 | `{"level": 50}` | r1.json:chosen | H10 | objective below H10；全区间 +21%（带入 +29%） | open |
| R2 | level / hold / list | LV50H10 | `{"level": 50, "rule_opts": {"max_days": 10, "short_max_days": 10}}` | r1.json:chosen | H10 | objective below H10；全区间 +25%（带入 +29%） | open |
| R2 | level / hold / list | TOP20 | `{"top": 20}` | r1.json:chosen | H10 | objective below H10；全区间 +5%（带入 +29%） | open |
