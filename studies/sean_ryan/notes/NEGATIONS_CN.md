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
| R4 | market_selection | M1 | `{"filter": "RSIDIV"}` | r3.json:chosen | P4 | gates: behaviour；全区间 +9%（带入 +75%） | open |
| R4 | market_selection | M2 | `{"priority": "wave"}` | r3.json:chosen | P4 | gates: behaviour；全区间 +125%（带入 +75%） | open |
| R4 | market_selection | M3 | `{"wave": {"gain": 1.0}}` | r3.json:chosen | P4 | gates: behaviour；全区间 +67%（带入 +75%） | open |
| R4 | market_selection | M4 | `{"max_new": 5}` | r3.json:chosen | P4 | gates: behaviour；全区间 +83%（带入 +75%） | open |
| R5 | selection_paired | Q1 | `{"priority": "wave", "max_new": 5}` | r4.json:chosen | Q2 | gates: behaviour；全区间 +116%（带入 +77%） | open |
| R5 | selection_paired | Q3 | `{"priority": "wave", "max_new": 5, "rule_opts": {"trims": [2, 4], "trim_frac": 0.33}}` | r4.json:chosen | Q2 | gates: behaviour；全区间 +112%（带入 +77%） | open |
| R5 | selection_paired | Q4 | `{"priority": "wave", "max_new": 5, "rule_opts": {"trims": [2], "trim_frac": 0.67}}` | r4.json:chosen | Q2 | objective below Q2；全区间 +64%（带入 +77%） | open |
| R6 | adds_divergence | A1 | `{"rule_opts": {"add_signal": "sig_all", "add_signal_frac": 0.33, "add_signal_max": 1, "add_signal_stop": "low"}}` | r5.json:chosen | Q2 | gates: behaviour；全区间 +195%（带入 +77%） | open |
| R6 | adds_divergence | A2 | `{"rule_opts": {"add_signal": "sig_all", "add_signal_frac": 0.25, "add_signal_max": 2, "add_signal_stop": "low"}}` | r5.json:chosen | Q2 | gates: behaviour；全区间 +156%（带入 +77%） | open |
| R6 | adds_divergence | A3 | `{"rule_opts": {"trim_signal": "rsidiv", "trim_signal_frac": 0.5}}` | r5.json:chosen | Q2 | gates: win<=0.35；全区间 +136%（带入 +77%） | open |
| R6 | adds_divergence | A4 | `{"rule_opts": {"trims": [2, 4], "trim_frac": 0.33}}` | r5.json:chosen | Q2 | gates: behaviour；全区间 +107%（带入 +77%） | open |
| R6 | adds_divergence | A5 | `{"rule_opts": {"add_signal": "sig_all", "add_signal_frac": 0.33, "add_signal_max": 1, "add_signal_stop": "low", "trim_signal": "rsidiv", "trim_signal_frac": 0.5}}` | r5.json:chosen | Q2 | gates: win<=0.35, behaviour；全区间 +225%（带入 +77%） | open |
| R7 | adds_tolerance | B2 | `{"rule_opts": {"add_signal": "sig_all", "add_signal_frac": 0.25, "add_signal_max": 2, "add_signal_stop": "low"}}` | r6.json:chosen | B1 | objective below B1；全区间 +156%（带入 +195%） | open |
| R7 | adds_tolerance | B3 | `{"max_new": 5, "rule_opts": {"add_signal": "sig_all", "add_signal_frac": 0.33, "add_signal_max": 1, "add_signal_stop": "low"}}` | r6.json:chosen | B1 | gates: behaviour+0.02；全区间 +253%（带入 +195%） | open |
| R7 | adds_tolerance | B4 | `{"rule_opts": {"add_signal": "sig_all", "add_signal_frac": 0.33, "add_signal_max": 1, "add_signal_stop": "low", "trims": [2, 4], "trim_frac": 0.33}}` | r6.json:chosen | B1 | gates: behaviour+0.02；全区间 +159%（带入 +195%） | open |
| R8 | stop_width | W1 | `{"stop_max": 0.05}` | r7.json:chosen | W2 | objective below W2；全区间 +63%（带入 +207%） | open |
