# Clement Ang 否定登记表

每个没被带入的候选一行（自动写入）；“当时的配置”一列是那一轮的基础配置报告。下游大改后，用 `negations` 动作列出依赖旧配置的行，在新配置上重测。

| 轮次 | 环节 | 候选 | 改了什么 | 当时的配置 | 带入 | 否定依据 | 状态 |
|---|---|---|---|---|---|---|---|
| H1 | human sizing | H1A | `{"human": {"tiers": [{"when": ["kind=fine"], "risk": 2, "cap": 0.5}]}}` | H:0 | None | H gates: gate, his years not closer: 2024,2025；全区间 +105%（带入 +0%） | open |
| H1 | human sizing | H1B | `{"human": {"rule_opts": {"feedback": 1, "risk_low": 0.0025}}}` | H:0 | None | H gates: gate, his years not closer: 2024,2025, bought 2 < 3；全区间 +48%（带入 +0%） | open |
| H1 | human sizing | H1C | `{"rule_opts": {"trail": "ema10"}}` | H:0 | None | H gates: his years not closer: 2024, bought 2 < 3；全区间 +56%（带入 +0%） | open |
| H1 | human sizing | H1D | `{"rule_opts": {"max_days": 3}}` | H:0 | None | H gates: gate, his years not closer: 2024,2025, bought 2 < 3；全区间 +22%（带入 +0%） | open |
| H1 | human sizing | H1E | `{"common": {"add": {"frac": 0.5, "max": 1, "stop": "keep", "profit": true}}}` | H:0 | None | H gates: his years not closer: 2024,2025, behaviour gap 0.816 > 0.766 + 0.02；全区间 +81%（带入 +0%） | open |
| R1 | setups | C1 | `{"setups": ["fine", "pb"]}` | :base | D0c | gates: placebo, width<=30；全区间 +2%（带入 -2%） | open |
| R1 | setups | C2 | `{"setups": ["fine", "ep"], "ep_pool": {"turnover": 5000000.0, "price": 2.0}}` | :base | D0c | gates: placebo；全区间 -28%（带入 -2%） | open |
| R1 | setups | C3 | `{"setups": ["fine", "pb", "ep"], "ep_pool": {"turnover": 5000000.0, "price": 2.0}}` | :base | D0c | gates: placebo, width<=30；全区间 -49%（带入 -2%） | open |
| R1 | setups | C4 | `{"setups": ["pb"]}` | :base | D0c | gates: placebo, width<=30；全区间 -2%（带入 -2%） | open |
| R1 | setups | C5 | `{"setups": ["fine", "pb"], "pool": {"turnover": 20000000.0, "adr": 3.0, "above50": true}}` | :base | D0c | gates: placebo, width<=30；全区间 -18%（带入 -2%） | open |
| S1 | short: late-stage failed base into the 20 EMA (Gil Morales; RULES 8, zw96) | CA | `{"setups": ["fb20"], "gate": "below20", "max_new": 3, "stop_w": "cap"}` | :chosen | none | gates: long_behaviour, short_placebo, total, years, maxdd, down | open |
| S1 | short: late-stage failed base into the 20 EMA (Gil Morales; RULES 8, zw96) | CB | `{"setups": ["fb20c"], "gate": "below20", "max_new": 3}` | :chosen | none | gates: long_behaviour, short_placebo, total, years, maxdd, down | open |
| S1 | short: late-stage failed base into the 20 EMA (Gil Morales; RULES 8, zw96) | CC | `{"setups": ["fb20"], "gate": "", "max_new": 3, "stop_w": "cap"}` | :chosen | none | gates: long_behaviour, total, years, maxdd, down | open |
| S1 | short: late-stage failed base into the 20 EMA (Gil Morales; RULES 8, zw96) | CD | `{"setups": ["fb20"], "gate": "below50", "max_new": 3, "stop_w": "cap"}` | :chosen | none | gates: total, years, maxdd, down | open |
| R2 | exits_capacity | K1 | `{"rule_opts": {"trims": [2], "trim_frac": 0.3333, "breakeven_r": 2.0, "trail": "ema10", "trim_signal": "atr50x8", "trim_signal_frac": 0.3333}}` | r1.json:chosen | K2 | objective below K2；全区间 +1%（带入 +2%） | open |
| R2 | exits_capacity | K3 | `{"rule_opts": {"trims": [2], "trim_frac": 0.3333, "breakeven_r": 2.0, "trail": "ema10", "trim_signal": "atr50x8", "trim_signal_frac": 0.3333, "max_open": 20}, "max_new": 3, "setups": ["fine", "pb"]}` | r1.json:chosen | K2 | gates: width<=30；全区间 +13%（带入 +2%） | open |
| R2 | exits_capacity | K4 | `{"rule_opts": {"trims": [2], "trim_frac": 0.3333, "breakeven_r": 2.0, "trail": "ema10", "trim_signal": "atr50x8", "trim_signal_frac": 0.3333, "max_open": 20}, "max_new": 3, "setups": ["fine", "pb", "ep"], "ep_pool": {"turnover": 5000000.0, "price": 2.0}}` | r1.json:chosen | K2 | gates: placebo, width<=30；全区间 -19%（带入 +2%） | open |
| R2 | exits_capacity | K5 | `{"rule_opts": {"trims": [2], "trim_frac": 0.3333, "breakeven_r": 2.0, "trail": "ema10", "trim_signal": "atr50x8", "trim_signal_frac": 0.3333, "max_open": 20}, "max_new": 3, "setups": ["fine", "pb"], "filter": "IDX20"}` | r1.json:chosen | K2 | gates: width<=30；全区间 +20%（带入 +2%） | open |
| S2 | short: only the former big leaders, only once the market has turned (his words at 01:24) | CE | `{"setups": ["fb20"], "turnover": 500000000.0, "gate": "below50", "max_new": 3, "stop_w": "cap"}` | :chosen | none | gates: short_placebo, total, years, maxdd, down | open |
| S2 | short: only the former big leaders, only once the market has turned (his words at 01:24) | CF | `{"setups": ["fb20"], "turnover": 500000000.0, "gate": "below200", "max_new": 3, "stop_w": "cap"}` | :chosen | none | gates: short_placebo, total, years, down | open |
| S2 | short: only the former big leaders, only once the market has turned (his words at 01:24) | CG | `{"setups": ["fb20c"], "turnover": 500000000.0, "gate": "below50", "max_new": 3}` | :chosen | none | gates: short_placebo, total, years, maxdd, down | open |
| S2 | short: only the former big leaders, only once the market has turned (his words at 01:24) | CH | `{"setups": ["fb20"], "turnover": 500000000.0, "gate": "below50", "max_new": 1, "stop_w": "cap"}` | :chosen | none | gates: total, years, maxdd, down | open |
| R3 | selection | F2 | `{"fine": {"tight": 3.0}}` | r2.json:chosen | F1 | gates: placebo；全区间 -13%（带入 +57%） | open |
| R3 | selection | F3 | `{"fine": {"near": 0.25, "tight": 3.0}}` | r2.json:chosen | F1 | objective below F1；全区间 +43%（带入 +57%） | open |
| R3 | selection | F4 | `{"fine": {"near": 0.25, "tight": 3.0}, "setups": ["fine", "pb"]}` | r2.json:chosen | F1 | gates: width<=30；全区间 +15%（带入 +57%） | open |
| R3 | selection | F5 | `{"fine": {"near": 0.25, "tight": 3.0}, "setups": ["fine", "pb"], "filter": "IDX20"}` | r2.json:chosen | F1 | gates: width<=30；全区间 +15%（带入 +57%） | open |
| S3 | short, gate v2: late-stage failed bases of big former leaders (a big advance behind them), short-lived | C3A | `{"setups": ["fb20"], "turnover": 500000000.0, "run": 1.0, "gate": "below50", "max_new": 1, "stop_w": "cap", "max_days": 10}` | :chosen | none | gates: alpha, maxdd | open |
| S3 | short, gate v2: late-stage failed bases of big former leaders (a big advance behind them), short-lived | C3B | `{"setups": ["fb20"], "turnover": 500000000.0, "run": 0.5, "gate": "below50", "max_new": 1, "stop_w": "cap", "max_days": 10}` | :chosen | none | gates: maxdd | open |
| S3 | short, gate v2: late-stage failed bases of big former leaders (a big advance behind them), short-lived | C3C | `{"setups": ["fb20"], "turnover": 500000000.0, "run": 1.0, "gate": "below200", "max_new": 1, "stop_w": "cap", "max_days": 10}` | :chosen | none | gates: alpha, down | open |
| S3 | short, gate v2: late-stage failed bases of big former leaders (a big advance behind them), short-lived | C3D | `{"setups": ["fb20"], "turnover": 500000000.0, "run": 1.0, "gate": "below50", "max_new": 1, "stop_w": "cap", "max_days": 10, "trail": "ema10"}` | :chosen | none | gates: maxdd | open |
| R4 | selection_order | G1 | `{"setups": ["fine", "pb"], "fine": {"near": 0.25, "tight": 3.0}, "priority": "rs"}` | r3.json:chosen | R3 | gates: placebo, width<=30；全区间 -10%（带入 +57%） | open |
| R4 | selection_order | G2 | `{"setups": ["fine", "pb"], "fine": {"near": 0.25, "tight": 3.0}, "max_new": 5}` | r3.json:chosen | R3 | gates: width<=30；全区间 +26%（带入 +57%） | open |
| R4 | selection_order | G3 | `{"setups": ["fine", "pb"], "fine": {"near": 0.25, "tight": 3.0}, "priority": "rs", "max_new": 5}` | r3.json:chosen | R3 | gates: width<=30；全区间 +6%（带入 +57%） | open |
| R4 | selection_order | G4 | `{"setups": ["fine", "pb", "ep"], "fine": {"near": 0.25, "tight": 3.0}, "priority": "rs", "max_new": 5}` | r3.json:chosen | R3 | gates: placebo, width<=30；全区间 -1%（带入 +57%） | open |
| R4 | selection_order | G5 | `{"setups": ["fine", "pb"], "fine": {"near": 0.25, "tight": 3.0}, "priority": "rs", "max_new": 5, "filter": "IDX20"}` | r3.json:chosen | R3 | gates: width<=30；全区间 +27%（带入 +57%） | open |
| S4 | short, gate v2: C3D (late-stage failed base, fast cover) with less drawdown | C4A | `{"setups": ["fb20"], "turnover": 500000000.0, "run": 1.0, "gate": "below50", "max_new": 1, "stop_w": "cap", "max_days": 10, "trail": "ema10", "risk_mult": 0.5}` | :chosen | none | gates: maxdd | open |
| S4 | short, gate v2: C3D (late-stage failed base, fast cover) with less drawdown | C4B | `{"setups": ["fb20"], "turnover": 500000000.0, "run": 1.0, "gate": "below50", "max_new": 1, "max_open": 1, "stop_w": "cap", "max_days": 10, "trail": "ema10"}` | :chosen | none | gates: alpha, maxdd, down | open |
| S4 | short, gate v2: C3D (late-stage failed base, fast cover) with less drawdown | C4C | `{"setups": ["fb20"], "turnover": 500000000.0, "run": 1.0, "gate": "below50", "max_new": 1, "stop_w": "cap", "max_days": 5, "trail": "ema10"}` | :chosen | none | gates: maxdd | open |
| S4 | short, gate v2: C3D (late-stage failed base, fast cover) with less drawdown | C4D | `{"setups": ["fb20"], "turnover": 500000000.0, "run": 1.0, "gate": "below50", "max_new": 1, "stop_w": "cap", "max_days": 5, "trail": "ema10", "risk_mult": 0.5}` | :chosen | none | gates: maxdd | open |
| R5 | selection | H1 | `{"setups": ["fine", "pb"], "pb": {"fine": true}}` | r4.json:chosen | R4 | objective below R4；全区间 +19%（带入 +57%） | open |
| R5 | selection | H2 | `{"setups": ["fine", "pb"], "pb": {"fine": true, "rs": 80}}` | r4.json:chosen | R4 | objective below R4；全区间 +33%（带入 +57%） | open |
| R5 | selection | H3 | `{"setups": ["fine", "pb"], "pb": {"fine": true}, "max_new": 5}` | r4.json:chosen | R4 | objective below R4；全区间 +13%（带入 +57%） | open |
| R5 | selection | H4 | `{"setups": ["fine", "pb", "ep"], "pb": {"fine": true}}` | r4.json:chosen | R4 | gates: placebo；全区间 -2%（带入 +57%） | open |
| R5 | selection | H5 | `{"setups": ["fine", "pb"], "pb": {"fine": true}, "fine": {"near": 0.25, "tight": 3.0}}` | r4.json:chosen | R4 | objective below R4；全区间 +26%（带入 +57%） | open |
| S5 | short, gate v2: C4C / C4A only once the market has turned (index under EMA50 for several closes) | C5B | `{"setups": ["fb20"], "turnover": 500000000.0, "run": 1.0, "gate": "below50x10", "max_new": 1, "stop_w": "cap", "max_days": 5, "trail": "ema10"}` | :chosen | C5A | gates: alpha | open |
| S5 | short, gate v2: C4C / C4A only once the market has turned (index under EMA50 for several closes) | C5C | `{"setups": ["fb20"], "turnover": 500000000.0, "run": 1.0, "gate": "below50x5", "max_new": 1, "stop_w": "cap", "max_days": 10, "trail": "ema10", "risk_mult": 0.5}` | :chosen | C5A | objective below C5A | open |
| S5 | short, gate v2: C4C / C4A only once the market has turned (index under EMA50 for several closes) | C5D | `{"setups": ["fb20"], "turnover": 500000000.0, "run": 1.0, "gate": "below50x10", "max_new": 1, "stop_w": "cap", "max_days": 10, "trail": "ema10", "risk_mult": 0.5}` | :chosen | C5A | gates: alpha | open |
| R6 | order | I1 | `{"priority": "turnover"}` | r5.json:chosen | I3 | objective below I3；全区间 +26%（带入 +117%） | open |
| R6 | order | I2 | `{"priority": "turnover", "setups": ["fine", "pb"], "pb": {"fine": true}}` | r5.json:chosen | I3 | objective below I3；全区间 +73%（带入 +117%） | open |
| R6 | order | I4 | `{"priority": "turnover", "fine": {"near": 0.25, "tight": 3.0}}` | r5.json:chosen | I3 | objective below I3；全区间 +59%（带入 +117%） | open |
| R6 | order | I5 | `{"priority": "turnover", "setups": ["fine", "pb"], "pb": {"fine": true}, "filter": "IDX20"}` | r5.json:chosen | I3 | objective below I3；全区间 +60%（带入 +117%） | open |
| R7 | entry_capacity | J1 | `{"max_new": 8}` | r6.json:chosen | J4 | objective below J4；全区间 +104%（带入 +73%） | open |
| R7 | entry_capacity | J2 | `{"close_any": ["pb"]}` | r6.json:chosen | J4 | objective below J4；全区间 +106%（带入 +73%） | open |
| R7 | entry_capacity | J3 | `{"max_new": 8, "close_any": ["pb"]}` | r6.json:chosen | J4 | objective below J4；全区间 +114%（带入 +73%） | open |
| R7 | entry_capacity | J5 | `{"max_new": 8, "close_any": ["pb"], "rule_opts": {"max_open": 30}}` | r6.json:chosen | J4 | objective below J4；全区间 +115%（带入 +73%） | open |
| R8 | rs_sizing | L1 | `{"rs_phase": true}` | r7.json:chosen | R7 | gates: bought；全区间 +29%（带入 +73%） | open |
| R8 | rs_sizing | L2 | `{"rule_opts": {"risk": 0.005}}` | r7.json:chosen | R7 | objective below R7；全区间 +63%（带入 +73%） | open |
| R8 | rs_sizing | L3 | `{"rule_opts": {"feedback": 1, "risk_low": 0.0015}}` | r7.json:chosen | R7 | objective below R7；全区间 +48%（带入 +73%） | open |
| R8 | rs_sizing | L4 | `{"rule_opts": {"month_loss_cap": 0.05, "month_cap_ladder": [0.025], "month_cap_basis": "opened"}}` | r7.json:chosen | R7 | gates: bought；全区间 +5%（带入 +73%） | open |
| R8 | rs_sizing | L5 | `{"rule_opts": {"risk": 0.005, "feedback": 1, "risk_low": 0.0025}}` | r7.json:chosen | R7 | objective below R7；全区间 +68%（带入 +73%） | open |
| R9 | exposure_exits | M1 | `{"rule_opts": {"max_gross": 1.5}}` | r8.json:chosen | M3 | objective below M3；全区间 +81%（带入 +184%） | open |
| R9 | exposure_exits | M2 | `{"rule_opts": {"max_gross": 2.0}}` | r8.json:chosen | M3 | objective below M3；全区间 +72%（带入 +184%） | open |
| R9 | exposure_exits | M4 | `{"rule_opts": {"trim_signal": "atr50x7", "trim_signal_frac": 0.1}}` | r8.json:chosen | M3 | objective below M3；全区间 +80%（带入 +184%） | open |
| R9 | exposure_exits | M5 | `{"rule_opts": {"max_gross": 2.0, "trim_signal": "atr50x7", "trim_signal_frac": 0.1}}` | r8.json:chosen | M3 | objective below M3；全区间 +81%（带入 +184%） | open |
| R10 | retest_after_exposure | N1 | `{"rule_opts": {"trail": "ema20"}}` | r9.json:chosen | R9 | gates: bought；全区间 +180%（带入 +184%） | open |
| R10 | retest_after_exposure | N2 | `{"pool": {"turnover": 20000000.0, "adr": 3.0, "above50": true}}` | r9.json:chosen | R9 | gates: bought；全区间 +120%（带入 +184%） | open |
| R10 | retest_after_exposure | N3 | `{"filter": "IDX20"}` | r9.json:chosen | R9 | gates: bought；全区间 +97%（带入 +184%） | open |
| R10 | retest_after_exposure | N4 | `{"rule_opts": {"max_open": 30}}` | r9.json:chosen | R9 | objective below R9；全区间 +154%（带入 +184%） | open |
| R10 | retest_after_exposure | N5 | `{"rule_opts": {"risk": 0.0075}}` | r9.json:chosen | R9 | gates: bought；全区间 +211%（带入 +184%） | open |
| R11 | pairs | P1 | `{"rule_opts": {"trail": "ema20", "max_open": 30}}` | r10.json:chosen | R10 | objective below R10；全区间 +222%（带入 +184%） | open |
| R11 | pairs | P2 | `{"rule_opts": {"risk": 0.0075, "max_open": 30}}` | r10.json:chosen | R10 | objective below R10；全区间 +209%（带入 +184%） | open |
| R11 | pairs | P3 | `{"rule_opts": {"trail": "ema20", "risk": 0.0075, "max_open": 30}}` | r10.json:chosen | R10 | gates: bought；全区间 +130%（带入 +184%） | open |
| R11 | pairs | P4 | `{"close_any": ["pb", "fine"]}` | r10.json:chosen | R10 | objective below R10；全区间 +124%（带入 +184%） | open |
| R11 | pairs | P5 | `{"close_any": ["pb", "fine"], "rule_opts": {"max_open": 30}}` | r10.json:chosen | R10 | objective below R10；全区间 +115%（带入 +184%） | open |
| R12 | pairs | Q1 | `{"rule_opts": {"trail": "ema20", "max_open": 30, "risk": 0.0075}}` | r11.json:chosen | Q2 | gates: bought；全区间 +130%（带入 +239%） | open |
| R12 | pairs | Q3 | `{"rule_opts": {"trail": "ema20", "max_open": 30}, "pool": {"turnover": 20000000.0, "adr": 3.0, "above50": true}}` | r11.json:chosen | Q2 | objective below Q2；全区间 +229%（带入 +239%） | open |
| R12 | pairs | Q4 | `{"rule_opts": {"trail": "ema20", "max_open": 30, "max_position": 0.5}}` | r11.json:chosen | Q2 | gates: bought；全区间 +134%（带入 +239%） | open |
| R12 | pairs | Q5 | `{"rule_opts": {"trail": "ema20", "max_open": 30, "risk": 0.0075}, "pool": {"turnover": 20000000.0, "adr": 3.0, "above50": true}}` | r11.json:chosen | Q2 | gates: bought；全区间 +148%（带入 +239%） | open |
| R13 | pairs | S1 | `{"pool": {"turnover": 20000000.0, "adr": 3.0, "above50": true}}` | r12.json:chosen | R12 | objective below R12；全区间 +228%（带入 +239%） | open |
| R13 | pairs | S2 | `{"rule_opts": {"risk": 0.0075}}` | r12.json:chosen | R12 | gates: bought；全区间 +128%（带入 +239%） | open |
| R13 | pairs | S3 | `{"rule_opts": {"max_gross": 3.0}}` | r12.json:chosen | R12 | gates: bought；全区间 +122%（带入 +239%） | open |
| R13 | pairs | S4 | `{"setups": ["fine", "pb", "ep", "brk52"]}` | r12.json:chosen | R12 | gates: bought, width<=30；全区间 +97%（带入 +239%） | open |
| R13 | pairs | S5 | `{"pool": {"turnover": 20000000.0, "adr": 3.0, "above50": true}, "rule_opts": {"risk": 0.0075}}` | r12.json:chosen | R12 | gates: bought；全区间 +136%（带入 +239%） | open |
| R14 | retest | T1 | `{"rule_opts": {"trail_after_trim": "ema10"}}` | r13.json:chosen | R13 | gates: bought；全区间 +173%（带入 +239%） | open |
| R14 | retest | T2 | `{"rule_opts": {"month_loss_cap": 0.05, "month_cap_ladder": [0.025], "month_cap_basis": "opened"}}` | r13.json:chosen | R13 | gates: bought；全区间 +51%（带入 +239%） | open |
| R14 | retest | T3 | `{"rule_opts": {"feedback": 1, "risk_low": 0.0025}}` | r13.json:chosen | R13 | gates: bought；全区间 +94%（带入 +239%） | open |
| R14 | retest | T4 | `{"rule_opts": {"trail_after_trim": "ema10", "feedback": 1, "risk_low": 0.0025}}` | r13.json:chosen | R13 | objective below R13；全区间 +54%（带入 +239%） | open |
| R15 | retest | AA1 | `{"rs_phase": true}` | r14.json:chosen | AA3 | gates: bought；全区间 +59%（带入 +270%） | open |
| R15 | retest | AA2 | `{"rs_phase": true, "pool": {"turnover": 20000000.0, "adr": 3.0, "above50": true}}` | r14.json:chosen | AA3 | gates: bought；全区间 +62%（带入 +270%） | open |
| R15 | retest | AA4 | `{"rule_opts": {"feedback": 3, "risk_low": 0.003}}` | r14.json:chosen | AA3 | gates: bought；全区间 +171%（带入 +270%） | open |
