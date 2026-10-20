# Sean Ryan 否定登记表

每个没被带入的候选一行（自动写入）；“当时的配置”一列是那一轮的基础配置报告。下游大改后，用 `negations` 动作列出依赖旧配置的行，在新配置上重测。

| 轮次 | 环节 | 候选 | 改了什么 | 当时的配置 | 带入 | 否定依据 | 状态 |
|---|---|---|---|---|---|---|---|
| R1 | execution | E1 | `{"entry": "close", "stop_from": "prev"}` | r0.json:chosen | E4 | gates: placebo；全区间 +5%（带入 +53%） | open |
| R1 | execution | E2 | `{"entry": "close", "stop_from": "day"}` | r0.json:chosen | E4 | objective below E4；全区间 +29%（带入 +53%） | open |
| R1 | execution | E3 | `{"entry": "pivot_close"}` | r0.json:chosen | E4 | gates: placebo；全区间 +2%（带入 +53%） | open |
| R2 | exit_behaviour | X1 | `{"rule_opts": {"nft_days": 3}}` | r1.json:chosen | X5 | gates: placebo；全区间 +0%（带入 +31%） | open |
| R2 | exit_behaviour | X2 | `{"rule_opts": {"nft_days": 5}}` | r1.json:chosen | X5 | objective below X5；全区间 +32%（带入 +31%） | open |
| R2 | exit_behaviour | X3 | `{"rule_opts": {"breakeven_r": 0.5}}` | r1.json:chosen | X5 | gates: placebo；全区间 +23%（带入 +31%） | open |
| R2 | exit_behaviour | X4 | `{"rule_opts": {"trims": [2], "trim_frac": 0.5}}` | r1.json:chosen | X5 | gates: placebo；全区间 +22%（带入 +31%） | open |
| R3 | return_exit_entry | P1 | `{"rule_opts": {"trims": [2], "trim_frac": 0.5}}` | r2.json:chosen | P4 | objective below P4；全区间 +50%（带入 +75%） | open |
| R3 | return_exit_entry | P2 | `{"rule_opts": {"trims": [3], "trim_frac": 0.5}}` | r2.json:chosen | P4 | objective below P4；全区间 +40%（带入 +75%） | open |
| R3 | return_exit_entry | P3 | `{"setups": ["wave2", "shake"]}` | r2.json:chosen | P4 | gates: behaviour；全区间 +54%（带入 +75%） | open |
