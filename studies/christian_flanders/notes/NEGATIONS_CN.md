# Christian Flanders 否定登记表

每个没被带入的候选一行（自动写入）；“当时的配置”一列是那一轮的基础配置报告。下游大改后，用 `negations` 动作列出依赖旧配置的行，在新配置上重测。

| 轮次 | 环节 | 候选 | 改了什么 | 当时的配置 | 带入 | 否定依据 | 状态 |
|---|---|---|---|---|---|---|---|
| R1 | setups | C2 | `{"setups": ["brk52", "ep"]}` | :base | C1 | gates: width<=30；全区间 +173%（带入 +208%） | open |
| R1 | setups | C3 | `{"setups": ["brk52", "ep", "pp", "vcp"]}` | :base | C1 | gates: width<=30；全区间 +89%（带入 +208%） | open |
| R1 | setups | C4 | `{"setups": ["brk52", "ep", "pp", "vcp"], "ep": {"near": 0.15}}` | :base | C1 | gates: width<=30；全区间 +55%（带入 +208%） | open |
| R2 | pool | P1 | `{"ep_pool": {"turnover": 5000000.0, "price": 5.0}}` | r1.json:chosen | P2 | objective below P2；全区间 +453%（带入 +628%） | open |
| R2 | pool | P3 | `{"ep_pool": {"turnover": 5000000.0, "price": 2.0}, "pool": {"turnover": 10000000.0, "price": 2.0, "adr": 3.0}}` | r1.json:chosen | P2 | objective below P2；全区间 +628%（带入 +628%） | open |
| R2 | pool | P4 | `{"setups": ["brk52", "ep"], "pool": {"adr": 5.0}, "ep_pool": {"turnover": 5000000.0, "price": 2.0}}` | r1.json:chosen | P2 | objective below P2；全区间 +307%（带入 +628%） | open |
| R2 | pool | P5 | `{"setups": ["brk52", "ep"], "pool": {"adr": 5.0}, "strength": "rs90", "ep_pool": {"turnover": 5000000.0, "price": 2.0}}` | r1.json:chosen | P2 | objective below P2；全区间 +269%（带入 +628%） | open |
| R3 | entry_stop | E1 | `{"entry": "level_pess"}` | r2.json:chosen | E2 | objective below E2；全区间 +419%（带入 +261%） | open |
| R3 | entry_stop | E3 | `{"entry_by_kind": {"ep": "open_pct"}, "open_pct": 0.06}` | r2.json:chosen | E2 | gates: placebo；全区间 -40%（带入 +261%） | open |
| R3 | entry_stop | E4 | `{"entry": "close"}` | r2.json:chosen | E2 | gates: placebo；全区间 -18%（带入 +261%） | open |
| R3 | entry_stop | E5 | `{"entry": "level_pess", "stop_cap": 0.06}` | r2.json:chosen | E2 | objective below E2；全区间 +486%（带入 +261%） | open |
| R4 | daily_choice | K2 | `{"ep_first": true}` | r3.json:chosen | K1 | objective below K1；全区间 +1039%（带入 +351%） | open |
| R4 | daily_choice | K3 | `{"max_new": 3}` | r3.json:chosen | K1 | objective below K1；全区间 +296%（带入 +351%） | open |
| R4 | daily_choice | K4 | `{"rule_opts": {"max_open": 12}}` | r3.json:chosen | K1 | objective below K1；全区间 +242%（带入 +351%） | open |
| R4 | daily_choice | K5 | `{"ep_first": true, "rule_opts": {"max_open": 12}}` | r3.json:chosen | K1 | objective below K1；全区间 +899%（带入 +351%） | open |
| R5 | exits | X2 | `{"rule_opts": {"trail": "ema21"}}` | r4.json:chosen | X1 | gates: bought；全区间 +218%（带入 +463%） | open |
| R5 | exits | X3 | `{"rule_opts": {"trail": "sma20"}}` | r4.json:chosen | X1 | gates: bought；全区间 +139%（带入 +463%） | open |
| R5 | exits | X4 | `{"rule_opts": {"trail": "sma50"}}` | r4.json:chosen | X1 | gates: placebo, bought；全区间 -1%（带入 +463%） | open |
| R5 | exits | X5 | `{"rule_opts": {"trail": "ema21", "trim_signal": "ext200_120", "trim_signal_frac": 0.5}}` | r4.json:chosen | X1 | objective below X1；全区间 +434%（带入 +463%） | open |
| R6 | sizing | S1 | `{"rule_opts": {"feedback": 4, "risk_low": 0.0025, "risk_high": 0.0075}}` | r5.json:chosen | R5 | objective below R5；全区间 +354%（带入 +463%） | open |
| R6 | sizing | S2 | `{"rule_opts": {"feedback": 4, "risk_low": 0.0025, "risk_high": 0.0075, "month_loss_cap": 0.05, "month_cap_ladder": [0.03, 0.02, 0.01, 0.005]}}` | r5.json:chosen | R5 | gates: bought；全区间 +114%（带入 +463%） | open |
| R6 | sizing | S3 | `{"rule_opts": {"feedback": 4, "risk_low": 0.0025, "risk_high": 0.0075, "month_loss_cap": 0.05, "month_cap_ladder": [0.03, 0.02, 0.01, 0.005], "max_gross": 2.0, "max_position": 0.5}}` | r5.json:chosen | R5 | gates: bought；全区间 +207%（带入 +463%） | open |
| R6 | sizing | S4 | `{"rule_opts": {"risk": 0.005, "feedback": 4, "risk_low": 0.0025, "risk_high": 0.01, "month_loss_cap": 0.05, "month_cap_ladder": [0.03, 0.02, 0.01, 0.005], "max_gross": 2.0, "max_position": 0.5}}` | r5.json:chosen | R5 | gates: bought；全区间 +187%（带入 +463%） | open |
| R6 | sizing | S5 | `{"rule_opts": {"risk": 0.005, "feedback": 4, "risk_low": 0.0025, "risk_high": 0.015, "month_loss_cap": 0.05, "month_cap_ladder": [0.03, 0.02, 0.01, 0.005], "max_gross": 2.0, "max_position": 0.5}}` | r5.json:chosen | R5 | gates: bought；全区间 +34%（带入 +463%） | open |
| R7 | exact_entry | W1 | `{"ep": {"rvol": 3.0}}` | r6.json:chosen | W2 | objective below W2；全区间 +39%（带入 +54%） | open |
| R7 | exact_entry | W3 | `{"rule_opts": {"trail": "ema21", "trim_signal": "ext200_120", "trim_signal_frac": 0.5}}` | r6.json:chosen | W2 | gates: bought；全区间 +43%（带入 +54%） | open |
| R7 | exact_entry | W4 | `{"stop_cap": 0.0}` | r6.json:chosen | W2 | gates: placebo, bought；全区间 +4%（带入 +54%） | open |
| R7 | exact_entry | W5 | `{"ep_first": true}` | r6.json:chosen | W2 | gates: placebo, bought；全区间 +3%（带入 +54%） | open |
| R8 | phase2 | U1 | `{"rule_opts": {"trail": "ema21"}}` | r7.json:chosen | R7 | gates: bought；全区间 +73%（带入 +54%） | open |
| R8 | phase2 | U2 | `{"setups": ["brk52", "ep"], "pool": {"adr": 5.0}}` | r7.json:chosen | R7 | gates: bought；全区间 +44%（带入 +54%） | open |
| R8 | phase2 | U3 | `{"rule_opts": {"trim_day": 5}}` | r7.json:chosen | R7 | objective below R7；全区间 +47%（带入 +54%） | open |
| R8 | phase2 | U4 | `{"rule_opts": {"add_signal": "sig_all", "add_signal_frac": 0.5, "add_signal_max": 2, "add_signal_stop": "low"}}` | r7.json:chosen | R7 | objective below R7；全区间 +42%（带入 +54%） | open |
| R8 | phase2 | U5 | `{"setups": ["hi52", "ep", "pp", "vcp"]}` | r7.json:chosen | R7 | gates: placebo；全区间 -17%（带入 +54%） | open |
| R9 | phase2 | V2 | `{"rule_opts": {"feedback": 4, "risk_low": 0.0025, "risk_high": 0.0075}}` | r8.json:chosen | V1 | objective below V1；全区间 +35%（带入 +31%） | open |
| R9 | phase2 | V3 | `{"rule_opts": {"max_gross": 2.0, "max_position": 0.5}}` | r8.json:chosen | V1 | objective below V1；全区间 +54%（带入 +31%） | open |
| R9 | phase2 | V4 | `{"rule_opts": {"risk": 0.005, "month_loss_cap": 0.05, "month_cap_ladder": [0.03, 0.02, 0.01, 0.005], "month_cap_basis": "opened"}}` | r8.json:chosen | V1 | gates: bought；全区间 +78%（带入 +31%） | open |
| R9 | phase2 | V5 | `{"max_new": 3}` | r8.json:chosen | V1 | gates: bought；全区间 +53%（带入 +31%） | open |
| R10 | selection | X2 | `{"ep": {"near": null, "far_low": 0.5}, "setups": ["hi52", "ep", "pb"]}` | r9.json:chosen | X1 | gates: placebo, bought, width<=30；全区间 -6%（带入 +77%） | open |
| R10 | selection | X3 | `{"ep": {"near": null, "far_low": 0.5}, "rule_opts": {"max_open": 12}}` | r9.json:chosen | X1 | objective below X1；全区间 +14%（带入 +77%） | open |
| R10 | selection | X4 | `{"ep": {"near": null, "far_low": 0.5}, "setups": ["hi52", "ep", "pb"], "rule_opts": {"max_open": 12}}` | r9.json:chosen | X1 | gates: placebo, bought, width<=30；全区间 -1%（带入 +77%） | open |
| R10 | selection | X5 | `{"ep": {"near": null, "far_low": 1.0}, "setups": ["hi52", "ep", "pb"], "rule_opts": {"max_open": 12}}` | r9.json:chosen | X1 | gates: placebo, bought, width<=30；全区间 -5%（带入 +77%） | open |
| R11 | capacity_order | Y1 | `{"max_new": 4, "rule_opts": {"max_open": 12, "max_gross": 2.0}}` | r10.json:chosen | R10 | gates: placebo；全区间 -18%（带入 +77%） | open |
| R11 | capacity_order | Y2 | `{"max_new": 4, "rule_opts": {"max_open": 12, "max_gross": 2.0}, "priority": "rvol"}` | r10.json:chosen | R10 | gates: placebo；全区间 +1%（带入 +77%） | open |
| R11 | capacity_order | Y3 | `{"max_new": 3, "rule_opts": {"max_open": 12, "max_gross": 2.0}}` | r10.json:chosen | R10 | gates: placebo；全区间 -12%（带入 +77%） | open |
| R11 | capacity_order | Y4 | `{"max_new": 4, "rule_opts": {"max_open": 12, "max_gross": 2.0, "risk": 0.0025}}` | r10.json:chosen | R10 | gates: placebo；全区间 -5%（带入 +77%） | open |
| R11 | capacity_order | Y5 | `{"max_new": 4, "rule_opts": {"max_open": 12, "max_gross": 2.0}, "priority": "rvol", "ep_first": true}` | r10.json:chosen | R10 | gates: bought；全区间 +20%（带入 +77%） | open |
| R12 | selection | Z1 | `{"setups": ["hi52", "ep", "pb"], "kind_order": ["ep", "hi52", "pb"]}` | r11.json:chosen | Z5 | gates: placebo, bought, width<=30；全区间 -6%（带入 +77%） | open |
| R12 | selection | Z2 | `{"setups": ["hi52", "ep", "vcp"], "kind_order": ["ep", "hi52", "vcp"]}` | r11.json:chosen | Z5 | gates: bought；全区间 +10%（带入 +77%） | open |
| R12 | selection | Z3 | `{"setups": ["hi52", "ep", "vcp", "pb"], "kind_order": ["ep", "hi52", "vcp", "pb"]}` | r11.json:chosen | Z5 | gates: placebo, bought, width<=30；全区间 +3%（带入 +77%） | open |
| R12 | selection | Z4 | `{"setups": ["hi52", "ep", "pb"], "kind_order": ["ep", "hi52", "pb"], "pb": {"up": 1.0}}` | r11.json:chosen | Z5 | gates: placebo, bought, width<=30；全区间 -5%（带入 +77%） | open |
| R13 | order | A1 | `{"priority": "turnover"}` | r12.json:chosen | R12 | gates: placebo；全区间 -22%（带入 +77%） | open |
| R13 | order | A2 | `{"priority": "turnover", "setups": ["hi52", "ep", "pb"], "kind_order": ["ep", "hi52", "pb"]}` | r12.json:chosen | R12 | gates: bought, width<=30；全区间 +77%（带入 +77%） | open |
| R13 | order | A3 | `{"priority": "turnover", "rule_opts": {"max_open": 12}}` | r12.json:chosen | R12 | gates: placebo；全区间 -14%（带入 +77%） | open |
| R13 | order | A4 | `{"priority": "turnover", "max_new": 3}` | r12.json:chosen | R12 | gates: placebo；全区间 -18%（带入 +77%） | open |
| R13 | order | A5 | `{"priority": "turnover", "kind_order": ["ep", "hi52"]}` | r12.json:chosen | R12 | gates: placebo；全区间 -22%（带入 +77%） | open |
