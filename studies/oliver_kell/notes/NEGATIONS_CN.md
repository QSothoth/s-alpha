# Oliver Kell 否定登记表

每个没被带入的候选一行（自动写入）；“当时的配置”一列是那一轮的基础配置报告。下游大改后，用 `negations` 动作列出依赖旧配置的行，在新配置上重测。

| 轮次 | 环节 | 候选 | 改了什么 | 当时的配置 | 带入 | 否定依据 | 状态 |
|---|---|---|---|---|---|---|---|
| R1 | end_to_end | V1 | `{"priority": "turnover"}` | :base | D0c | gates: placebo；全区间 -13%（带入 -2%） | open |
| R1 | end_to_end | V2 | `{"rule_opts": {"trim_signal": "below_ema10", "trim_signal_frac": 0.5}}` | :base | D0c | gates: placebo；全区间 -17%（带入 -2%） | open |
| R1 | end_to_end | V3 | `{"filter": "IDX20", "rule_opts": {"risk_scale": "", "max_position": 0.15, "max_open": 7, "max_gross": 1.5}}` | :base | D0c | gates: placebo；全区间 -0%（带入 -2%） | open |
| R1 | end_to_end | V4 | `{"rule_opts": {"trim_signal": "ext10_30", "trim_signal_frac": 0.3333}}` | :base | D0c | gates: placebo；全区间 +14%（带入 -2%） | open |
| R1 | end_to_end | V5 | `{"priority": "turnover", "filter": "IDX20", "rule_opts": {"risk_scale": "", "max_position": 0.15, "max_open": 7, "max_gross": 1.5, "trim_signal": "ext10_30", "trim_signal_frac": 0.3333}}` | :base | D0c | gates: placebo；全区间 +12%（带入 -2%） | open |
| R2 | setups | W1 | `{"setups": ["pop", "cross", "pb"]}` | r1.json:chosen | R1 | gates: placebo, width<=30；全区间 -63%（带入 -2%） | open |
| R2 | setups | W2 | `{"setups": ["pop", "cross", "vcp", "brk52"]}` | r1.json:chosen | R1 | gates: placebo, width<=30；全区间 -28%（带入 -2%） | open |
| R2 | setups | W3 | `{"setups": ["pop", "cross", "ib2"]}` | r1.json:chosen | R1 | gates: placebo；全区间 -8%（带入 -2%） | open |
| R2 | setups | W4 | `{"setups": ["pop", "cross", "ur"]}` | r1.json:chosen | R1 | gates: placebo；全区间 -38%（带入 -2%） | open |
| R2 | setups | W5 | `{"setups": ["pop", "cross", "pb", "vcp", "brk52", "ib2", "ur"], "priority": "turnover"}` | r1.json:chosen | R1 | gates: placebo, width<=30；全区间 +9%（带入 -2%） | open |
| R3 | end_to_end_pairs | X1 | `{"setups": ["pop", "cross", "pb", "vcp", "brk52", "ib2", "ur"], "priority": "turnover", "rule_opts": {"trim_signal": "below_ema10", "trim_signal_frac": 0.5}}` | r2.json:chosen | R2 | gates: width<=30；全区间 +47%（带入 -2%） | open |
| R3 | end_to_end_pairs | X2 | `{"setups": ["pop", "cross", "pb", "vcp", "brk52", "ib2", "ur"], "priority": "turnover", "rule_opts": {"trim_day": 11, "trim_day_frac": 0.3333}}` | r2.json:chosen | R2 | gates: width<=30；全区间 +31%（带入 -2%） | open |
| R3 | end_to_end_pairs | X3 | `{"setups": ["pop", "cross", "pb", "vcp", "brk52", "ib2", "ur"], "priority": "turnover", "filter": "IDX20", "rule_opts": {"risk_scale": "", "max_position": 0.15, "max_open": 7, "max_gross": 1.5}}` | r2.json:chosen | R2 | gates: width<=30；全区间 +25%（带入 -2%） | open |
| R3 | end_to_end_pairs | X4 | `{"setups": ["pop", "cross", "pb", "vcp", "brk52", "ib2", "ur"], "priority": "turnover", "strength": "rs80"}` | r2.json:chosen | R2 | gates: placebo, width<=30；全区间 +13%（带入 -2%） | open |
| R3 | end_to_end_pairs | X5 | `{"setups": ["pop", "cross", "pb", "vcp", "brk52", "ib2", "ur"], "priority": "turnover", "strength": "rs80", "filter": "IDX20", "rule_opts": {"risk_scale": "", "max_position": 0.15, "max_open": 7, "max_gross": 1.5}}` | r2.json:chosen | R2 | gates: width<=30；全区间 +36%（带入 -2%） | open |
| R4 | narrow | Y1 | `{"setups": ["pop", "cross", "pb", "vcp", "brk52", "ib2", "ur"], "priority": "turnover", "strength": "rs90", "rule_opts": {"trim_signal": "below_ema10", "trim_signal_frac": 0.5}}` | r3.json:chosen | Y5 | gates: width<=30；全区间 +75%（带入 +61%） | open |
| R4 | narrow | Y2 | `{"setups": ["pop", "cross", "pb", "vcp", "brk52", "ib2", "ur"], "priority": "turnover", "strength": "rs95", "rule_opts": {"trim_signal": "below_ema10", "trim_signal_frac": 0.5}}` | r3.json:chosen | Y5 | objective below Y5；全区间 +2%（带入 +61%） | open |
| R4 | narrow | Y3 | `{"setups": ["pop", "cross", "pb", "vcp", "brk52", "ib2", "ur"], "priority": "turnover", "pool": {"turnover": 100000000.0, "adr": 3.0, "above50": false}, "rule_opts": {"trim_signal": "below_ema10", "trim_signal_frac": 0.5}}` | r3.json:chosen | Y5 | gates: width<=30；全区间 +44%（带入 +61%） | open |
| R4 | narrow | Y4 | `{"setups": ["pop", "cross", "pb", "vcp", "brk52", "ib2", "ur"], "priority": "turnover", "strength": "rs90", "pool": {"turnover": 100000000.0, "adr": 3.0, "above50": false}, "rule_opts": {"trim_signal": "below_ema10", "trim_signal_frac": 0.5}}` | r3.json:chosen | Y5 | objective below Y5；全区间 +65%（带入 +61%） | open |
| R5 | entry | Z1 | `{"close_any": ["pb", "ib2", "cross", "vcp", "brk52"]}` | r4.json:chosen | Z5 | objective below Z5；全区间 +118%（带入 +173%） | open |
| R5 | entry | Z2 | `{"close_any": ["pb", "ib2", "cross", "vcp", "brk52"], "max_new": 3}` | r4.json:chosen | Z5 | objective below Z5；全区间 +116%（带入 +173%） | open |
| R5 | entry | Z3 | `{"close_any": ["pb", "ib2", "cross", "vcp", "brk52"], "strength": "rs80"}` | r4.json:chosen | Z5 | objective below Z5；全区间 +61%（带入 +173%） | open |
| R5 | entry | Z4 | `{"close_any": ["pb", "ib2", "cross", "vcp", "brk52"], "rule_opts": {"trim_day": 11, "trim_day_frac": 0.3333}}` | r4.json:chosen | Z5 | objective below Z5；全区间 +103%（带入 +173%） | open |
