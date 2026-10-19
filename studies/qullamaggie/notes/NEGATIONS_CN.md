# Qullamaggie 否定登记表

每个没被带入的候选一行（自动写入）；“当时的配置”一列是那一轮的基础配置报告。下游大改后，用 `negations` 动作列出依赖旧配置的行，在新配置上重测。

| 轮次 | 环节 | 候选 | 改了什么 | 当时的配置 | 带入 | 否定依据 | 状态 |
|---|---|---|---|---|---|---|---|
| R1 | end_to_end | Q1 | `{"setups": ["ep"]}` | r0.json:chosen | Q5 | gates: placebo；全区间 -20%（带入 +33%） | open |
| R1 | end_to_end | Q2 | `{"stop_adr": {"brk": 1.0, "ep": 3.0}}` | r0.json:chosen | Q5 | gates: placebo；全区间 -32%（带入 +33%） | open |
| R1 | end_to_end | Q3 | `{"setups": ["ep"], "stop_adr": {"ep": 3.0}}` | r0.json:chosen | Q5 | gates: placebo；全区间 -34%（带入 +33%） | open |
| R1 | end_to_end | Q4 | `{"setups": ["ep"], "stop_adr": {"ep": 3.0}, "rule_opts": {"trail": "ema20", "trim_day_breakeven": true}}` | r0.json:chosen | Q5 | gates: placebo；全区间 -28%（带入 +33%） | open |
| R2 | ep_market | S1 | `{"filter": "", "rule_opts": {"risk_scale": "lighthalf"}}` | r1.json:chosen | R1 | gates: placebo；全区间 -19%（带入 +33%） | open |
| R2 | ep_market | S2 | `{"ep": {"min_gap": 0.08}}` | r1.json:chosen | R1 | objective below R1；全区间 +18%（带入 +33%） | open |
| R2 | ep_market | S3 | `{"ep": {"liquid": 5000000.0}}` | r1.json:chosen | R1 | gates: placebo；全区间 +3%（带入 +33%） | open |
| R2 | ep_market | S4 | `{"filter": "", "rule_opts": {"risk_scale": "lighthalf"}, "ep": {"min_gap": 0.08}}` | r1.json:chosen | R1 | gates: placebo；全区间 -39%（带入 +33%） | open |
| R2 | ep_market | S5 | `{"filter": "", "rule_opts": {"risk_scale": "lighthalf"}, "ep": {"min_gap": 0.08, "liquid": 5000000.0}}` | r1.json:chosen | R1 | objective below R1；全区间 +26%（带入 +33%） | open |
| R3 | capacity_setups | T1 | `{"setups": ["ep", "brk"], "kind_order": ["ep", "brk"]}` | r2.json:chosen | T3 | objective below T3；全区间 +42%（带入 +20%） | open |
| R3 | capacity_setups | T2 | `{"max_new": 5, "rule_opts": {"max_open": 15}}` | r2.json:chosen | T3 | objective below T3；全区间 +46%（带入 +20%） | open |
| R3 | capacity_setups | T4 | `{"rule_opts": {"trim_day": 5}}` | r2.json:chosen | T3 | objective below T3；全区间 +18%（带入 +20%） | open |
| R3 | capacity_setups | T5 | `{"setups": ["ep", "brk"], "kind_order": ["ep", "brk"], "max_new": 5, "rule_opts": {"max_open": 15}}` | r2.json:chosen | T3 | objective below T3；全区间 +69%（带入 +20%） | open |
