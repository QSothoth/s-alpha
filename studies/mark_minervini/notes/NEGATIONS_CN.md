# Mark Minervini 否定登记表

每个没被带入的候选一行（自动写入）；“当时的配置”一列是那一轮的基础配置报告。下游大改后，用 `negations` 动作列出依赖旧配置的行，在新配置上重测。

| 轮次 | 环节 | 候选 | 改了什么 | 当时的配置 | 带入 | 否定依据 | 状态 |
|---|---|---|---|---|---|---|---|
| G1 | human sizing | GA | `{"common": {"rank": "strength"}}` | H:0 | None | H gates: segment not above H0；全区间 +114%（带入 +0%） | open |
| G1 | human sizing | GB | `{"human": {"regime": {"risk": 0.5, "sma": 20}}}` | H:0 | None | H gates: segment not above H0；全区间 +105%（带入 +0%） | open |
| G1 | human sizing | GC | `{"human": {"cap_above": true, "tiers": [{"when": ["strength>=0.98"], "risk": 2, "cap": 0.5}]}}` | H:0 | None | H gates: segment not above H0；全区间 +62%（带入 +0%） | open |
| G1 | human sizing | GD | `{"human": {"rule_opts": {"feedback": 5, "risk_low": 0.0025}}}` | H:0 | None | H gates: segment not above H0, avg_win 0.266 vs H0 0.304；全区间 +94%（带入 +0%） | open |
| S1 | short: B-grade baseline (stage-4 template turned over, breakdown, stop above the recent high) | MA | `{"setups": ["s4"], "gate": "below50", "max_new": 2, "trail": "sma50", "trims": [], "max_days": 0}` | :chosen | none | gates: long_behaviour, down | open |
| S1 | short: B-grade baseline (stage-4 template turned over, breakdown, stop above the recent high) | MB | `{"setups": ["s4"], "gate": "", "max_new": 2, "trail": "sma50", "trims": [], "max_days": 0}` | :chosen | none | gates: long_behaviour, total, years, down | open |
| G2 | human sizing | G2A | `{"human": {"regime": {"risk": 0.5, "sma": 20}, "cap_above": true, "tiers": [{"when": ["strength>=0.98"], "risk": 2, "cap": 0.5}]}}` | H:0 | None | H gates: segment not above H0；全区间 +54%（带入 +0%） | open |
| G2 | human sizing | G2B | `{"human": {"regime": {"kind": "breadth", "sma": 50, "below": 0.5, "risk": 0.5}}}` | H:0 | None | H gates: segment not above H0, win 0.118 < H0 0.143 - 0.02；全区间 +102%（带入 +0%） | open |
| G2 | human sizing | G2C | `{"human": {"regime": {"kind": "index", "sma": 50, "risk": 0}}}` | H:0 | None | H gates: segment not above H0, avg_win 0.260 vs H0 0.304；全区间 +84%（带入 +0%） | open |
| S2 | short, gate v2: the stage-4 baseline made few and short-lived | M2A | `{"setups": ["s4"], "gate": "below50", "max_new": 1, "trail": "sma50", "trims": [], "max_days": 10}` | :chosen | none | gates: long_behaviour, alpha, count, maxdd, down | open |
| S2 | short, gate v2: the stage-4 baseline made few and short-lived | M2B | `{"setups": ["s4"], "gate": "below50", "max_new": 1, "max_open": 1, "trail": "sma50", "trims": [], "max_days": 10}` | :chosen | none | gates: long_behaviour, alpha, maxdd, down | open |
| S2 | short, gate v2: the stage-4 baseline made few and short-lived | M2C | `{"setups": ["s4"], "gate": "below200", "max_new": 1, "trail": "sma50", "trims": [], "max_days": 10}` | :chosen | none | gates: long_behaviour, maxdd, down | open |
| S2 | short, gate v2: the stage-4 baseline made few and short-lived | M2D | `{"setups": ["s4"], "gate": "below50", "max_new": 1, "trail": "sma20", "trims": [], "max_days": 10}` | :chosen | none | gates: long_behaviour, alpha, count, maxdd, down | open |
| G3 | human sizing | G3A | `{"human": {"rule_opts": {"feedback": 5, "risk_low": 0.0025, "risk_high": 0.0075}}}` | H:0 | None | H gates: segment not above H0；全区间 +48%（带入 +0%） | open |
| G3 | human sizing | G3B | `{"human": {"rule_opts": {"dd_risk": 0.1, "dd_risk_mult": 0.5}}}` | H:0 | None | H gates: segment not above H0；全区间 +99%（带入 +0%） | open |
