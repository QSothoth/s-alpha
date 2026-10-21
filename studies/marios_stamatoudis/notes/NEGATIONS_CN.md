# Marios Stamatoudis 否定登记表

每个没被带入的候选一行（自动写入）；“当时的配置”一列是那一轮的基础配置报告。下游大改后，用 `negations` 动作列出依赖旧配置的行，在新配置上重测。

| 轮次 | 环节 | 候选 | 改了什么 | 当时的配置 | 带入 | 否定依据 | 状态 |
|---|---|---|---|---|---|---|---|
| G1 | human sizing | GA | `{"common": {"ep_slots": 1, "rank": "strength"}}` | h3.json:H3B | None | objective not above the base / None；全区间 +165%（带入 +0%） | open |
| G1 | human sizing | GB | `{"human": {"regime": {"risk": 0.5, "sma": 20}}}` | h3.json:H3B | None | objective not above the base / None；全区间 +190%（带入 +0%） | open |
| G1 | human sizing | GC | `{"human": {"cap_above": true, "tiers": [{"when": ["strength>=0.98"], "risk": 2, "cap": 0.5}]}}` | h3.json:H3B | None | H gates: drawdown；全区间 +269%（带入 +0%） | open |
| G1 | human sizing | GD | `{"human": {"rule_opts": {"feedback": 5, "risk_low": 0.002}}}` | h3.json:H3B | None | objective not above the base / None；全区间 +161%（带入 +0%） | open |
| H1 | human sizing | H1A | `{"max_new": 1}` | H:0 | H1C | H gates: segment not above H0, drawdown；全区间 +134%（带入 +0%） | open |
| H1 | human sizing | H1B | `{"human": {"rule_opts": {"feedback": 5, "risk_low": 0.003, "risk_high": 0.005}}}` | H:0 | H1C | H gates: drawdown；全区间 +153%（带入 +0%） | open |
| H1 | human sizing | H1D | `{"human": {"rule_opts": {"max_open": 8}}}` | H:0 | H1C | H gates: drawdown；全区间 +194%（带入 +0%） | open |
| R1 | selection_floors | L1 | `{"ep": {"escape": 0}}` | r0.json:chosen | L4 | gates: placebo；全区间 -29%（带入 +405%） | open |
| R1 | selection_floors | L2 | `{"stop_adr": {"brk": 1.0, "ep": 3.0}}` | r0.json:chosen | L4 | gates: win<=0.35；全区间 +13%（带入 +405%） | open |
| R1 | selection_floors | L3 | `{"ep": {"price": 1.0, "liquid": 2000000.0}, "brk": {"turnover": 2000000.0, "price": 1.0, "adr": 4.0, "top": 0.02}}` | r0.json:chosen | L4 | objective below L4；全区间 +238%（带入 +405%） | open |
| S1 | shorts_v2 | P1 | `{"setups": ["para"], "trigger": "red", "max_days": 5, "max_new": 1}` | :chosen | P4 | objective below P4 | open |
| S1 | shorts_v2 | P2 | `{"setups": ["para"], "trigger": "pdl", "max_days": 5, "max_new": 1}` | :chosen | P4 | gates: down | open |
| S1 | shorts_v2 | P3 | `{"setups": ["ptop"], "max_days": 5, "max_new": 1}` | :chosen | P4 | objective below P4 | open |
| S1 | shorts_v2 | P5 | `{"setups": ["para"], "trigger": "red", "max_days": 3, "max_new": 1, "small": 4.0}` | :chosen | P4 | gates: alpha, down | open |
| G2 | human sizing | G2A | `{"human": {"regime": {"risk": 0.5, "sma": 20}, "cap_above": true, "tiers": [{"when": ["strength>=0.98"], "risk": 2, "cap": 0.5}]}}` | h3.json:H3B | G2B | H gates: drawdown；全区间 +276%（带入 +0%） | open |
| G2 | human sizing | G2C | `{"human": {"regime": {"kind": "index", "sma": 50, "risk": 0}}}` | h3.json:H3B | G2B | H gates: behaviour gap 0.142 > 0.018 + 0.02, avg_win 0.237 vs H0 0.206；全区间 +177%（带入 +0%） | open |
| H2 | human sizing | H2A | `{"human": {"rule_opts": {"max_open": 8}}}` | h1.json:H1C | None | H gates: avg_win 0.228 vs H0 0.206；全区间 +190%（带入 +0%） | open |
| H2 | human sizing | H2B | `{"human": {"rule_opts": {"feedback": 5, "risk_low": 0.003, "risk_high": 0.005}}}` | h1.json:H1C | None | objective not above the base / None；全区间 +164%（带入 +0%） | open |
| R2 | exits_sizing | T1 | `{"rule_opts": {"trail": "sma20"}}` | r1.json:chosen | L4 | gates: behaviour+0.02；全区间 +454%（带入 +405%） | open |
| R2 | exits_sizing | T2 | `{"rule_opts": {"add_signal": "sig_all", "add_signal_frac": 0.33, "add_signal_max": 1, "add_signal_stop": "fill"}}` | r1.json:chosen | L4 | gates: behaviour+0.02；全区间 +331%（带入 +405%） | open |
| R2 | exits_sizing | T3 | `{"stop_adr": {"brk": 2.0, "ep": 3.0}}` | r1.json:chosen | L4 | objective below L4；全区间 +325%（带入 +405%） | open |
| R2 | exits_sizing | T4 | `{"rule_opts": {"trims": [3, 8], "trim_frac": 0.25}}` | r1.json:chosen | L4 | objective below L4；全区间 +342%（带入 +405%） | open |
| R2 | exits_sizing | T5 | `{"rule_opts": {"risk": 0.004}}` | r1.json:chosen | L4 | objective below L4；全区间 +390%（带入 +405%） | open |
| H3 | human sizing | H3A | `{"rule_opts": {"add_r": 2.0, "add_frac": 1.0, "add_cap_mult": 1.2, "add_stop": "cost"}}` | h1.json:H1C | H3B | H gates: drawdown, behaviour gap 0.151 > 0.018 + 0.02, avg_win 0.229 vs H0 0.206, days_win 9.868 vs H0 11.310；全区间 +148%（带入 +0%） | open |
| H3 | human sizing | H3C | `{"rule_opts": {"risk": 0.004, "add_r": 2.0, "add_frac": 1.0, "add_cap_mult": 1.2, "add_stop": "cost"}}` | h1.json:H1C | H3B | H gates: drawdown, behaviour gap 0.161 > 0.018 + 0.02, avg_win 0.231 vs H0 0.206, days_win 10.049 vs H0 11.310；全区间 +154%（带入 +0%） | open |
