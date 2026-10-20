# Christian Flanders 否定登记表

每个没被带入的候选一行（自动写入）；“当时的配置”一列是那一轮的基础配置报告。下游大改后，用 `negations` 动作列出依赖旧配置的行，在新配置上重测。

| 轮次 | 环节 | 候选 | 改了什么 | 当时的配置 | 带入 | 否定依据 | 状态 |
|---|---|---|---|---|---|---|---|
| R1 | setups | C2 | `{"setups": ["brk52", "ep"]}` | :base | C1 | gates: width<=30；全区间 +173%（带入 +208%） | open |
| R1 | setups | C3 | `{"setups": ["brk52", "ep", "pp", "vcp"]}` | :base | C1 | gates: width<=30；全区间 +89%（带入 +208%） | open |
| R1 | setups | C4 | `{"setups": ["brk52", "ep", "pp", "vcp"], "ep": {"near": 0.15}}` | :base | C1 | gates: width<=30；全区间 +55%（带入 +208%） | open |
| S1 | short: rallies into the declining 200-day and earnings gaps away from it (RULES 8, transcripts) | FA | `{"setups": ["r200"], "gate": "below50", "max_new": 2, "stop_w": "cap", "trail": "", "trims": [], "trim_day": 1, "trim_day_frac": 1.0, "max_days": 3}` | :chosen | none | gates: total, years, maxdd, down | open |
| S1 | short: rallies into the declining 200-day and earnings gaps away from it (RULES 8, transcripts) | FB | `{"setups": ["r200"], "gate": "below200", "max_new": 2, "stop_w": "cap", "trail": "", "trims": [], "trim_day": 1, "trim_day_frac": 1.0, "max_days": 3}` | :chosen | none | gates: years | open |
| S1 | short: rallies into the declining 200-day and earnings gaps away from it (RULES 8, transcripts) | FC | `{"setups": ["gap200"], "gate": "below50", "max_new": 2, "stop_w": "cap", "trail": "", "trims": [], "trim_day": 1, "trim_day_frac": 1.0, "max_days": 3}` | :chosen | none | gates: short_placebo, total, years, down | open |
| S1 | short: rallies into the declining 200-day and earnings gaps away from it (RULES 8, transcripts) | FD | `{"setups": ["r200", "gap200"], "gate": "", "max_new": 2, "stop_w": "cap", "trail": "", "trims": [], "trim_day": 1, "trim_day_frac": 1.0, "max_days": 3}` | :chosen | none | gates: total, down | open |
| S1 | short: rallies into the declining 200-day and earnings gaps away from it (RULES 8, transcripts) | FE | `{"setups": ["r200", "gap200"], "gate": "below50", "max_new": 2, "stop_w": "cap", "trail": "sma10", "trims": [], "trim_day": 3, "trim_day_frac": 0.5, "max_days": 0}` | :chosen | none | gates: total, years, maxdd, down | open |
| R2 | pool | P1 | `{"ep_pool": {"turnover": 5000000.0, "price": 5.0}}` | r1.json:chosen | P2 | objective below P2；全区间 +453%（带入 +628%） | open |
| R2 | pool | P3 | `{"ep_pool": {"turnover": 5000000.0, "price": 2.0}, "pool": {"turnover": 10000000.0, "price": 2.0, "adr": 3.0}}` | r1.json:chosen | P2 | objective below P2；全区间 +628%（带入 +628%） | open |
| R2 | pool | P4 | `{"setups": ["brk52", "ep"], "pool": {"adr": 5.0}, "ep_pool": {"turnover": 5000000.0, "price": 2.0}}` | r1.json:chosen | P2 | objective below P2；全区间 +307%（带入 +628%） | open |
| R2 | pool | P5 | `{"setups": ["brk52", "ep"], "pool": {"adr": 5.0}, "strength": "rs90", "ep_pool": {"turnover": 5000000.0, "price": 2.0}}` | r1.json:chosen | P2 | objective below P2；全区间 +269%（带入 +628%） | open |
| S2 | short: his gap-short stop above the 150-day; keeping part of the 200-day short | FF | `{"setups": ["r200"], "gate": "below200", "max_new": 2, "stop_w": "cap", "trail": "sma10", "trims": [], "trim_day": 1, "trim_day_frac": 0.5, "max_days": 0}` | :chosen | none | gates: total, down | open |
| S2 | short: his gap-short stop above the 150-day; keeping part of the 200-day short | FG | `{"setups": ["gap200"], "gap_stop": "sma150", "gate": "below50", "max_new": 2, "trail": "", "trims": [], "trim_day": 1, "trim_day_frac": 1.0, "max_days": 3}` | :chosen | none | gates: short_placebo, total, years, maxdd, down | open |
| S2 | short: his gap-short stop above the 150-day; keeping part of the 200-day short | FH | `{"setups": ["r200", "gap200"], "gap_stop": "sma150", "gate": "below200", "max_new": 2, "stop_w": "cap", "trail": "", "trims": [], "trim_day": 1, "trim_day_frac": 1.0, "max_days": 3}` | :chosen | none | gates: years | open |
| S2 | short: his gap-short stop above the 150-day; keeping part of the 200-day short | FI | `{"setups": ["gap200"], "gap_stop": "sma150", "gate": "below50", "max_new": 2, "trail": "sma10", "trims": [], "trim_day": 1, "trim_day_frac": 0.5, "max_days": 0}` | :chosen | none | gates: short_placebo, total, years, maxdd, down | open |
| R3 | entry_stop | E1 | `{"entry": "level_pess"}` | r2.json:chosen | E2 | objective below E2；全区间 +419%（带入 +261%） | open |
| R3 | entry_stop | E3 | `{"entry_by_kind": {"ep": "open_pct"}, "open_pct": 0.06}` | r2.json:chosen | E2 | gates: placebo；全区间 -40%（带入 +261%） | open |
| R3 | entry_stop | E4 | `{"entry": "close"}` | r2.json:chosen | E2 | gates: placebo；全区间 -18%（带入 +261%） | open |
| R3 | entry_stop | E5 | `{"entry": "level_pess", "stop_cap": 0.06}` | r2.json:chosen | E2 | objective below E2；全区间 +486%（带入 +261%） | open |
| S3 | short, gate v2: the 200-day limit only after the line already turned rallies back ('rejected four times') | F3A | `{"setups": ["r200"], "r200_rej": 1, "gate": "below200", "max_new": 2, "stop_w": "cap", "trail": "", "trims": [], "trim_day": 1, "trim_day_frac": 1.0, "max_days": 3}` | :chosen | none | gates: alpha | open |
| S3 | short, gate v2: the 200-day limit only after the line already turned rallies back ('rejected four times') | F3B | `{"setups": ["r200"], "r200_rej": 2, "gate": "below200", "max_new": 2, "stop_w": "cap", "trail": "", "trims": [], "trim_day": 1, "trim_day_frac": 1.0, "max_days": 3}` | :chosen | none | gates: alpha | open |
| S3 | short, gate v2: the 200-day limit only after the line already turned rallies back ('rejected four times') | F3C | `{"setups": ["r200"], "r200_rej": 1, "gate": "below50", "max_new": 2, "stop_w": "cap", "trail": "", "trims": [], "trim_day": 1, "trim_day_frac": 1.0, "max_days": 3}` | :chosen | none | gates: count, maxdd | open |
| S3 | short, gate v2: the 200-day limit only after the line already turned rallies back ('rejected four times') | F3D | `{"setups": ["r200"], "r200_rej": 1, "gate": "below200", "max_new": 2, "stop_w": "cap", "trail": "sma10", "trims": [], "trim_day": 1, "trim_day_frac": 0.5, "max_days": 10}` | :chosen | none | gates: alpha, down | open |
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
| R14 | pyramid_exposure | B1 | `{"rule_opts": {"add_signal": "sig_all", "add_signal_frac": 0.5, "add_signal_max": 2, "add_signal_stop": "low", "feedback": 4, "risk_low": 0.0025, "risk_high": 0.01}}` | r13.json:chosen | R13 | objective below R13；全区间 +61%（带入 +77%） | open |
| R14 | pyramid_exposure | B2 | `{"rule_opts": {"add_signal": "sig_all", "add_signal_frac": 0.5, "add_signal_max": 2, "add_signal_stop": "low", "max_gross": 2.0, "max_position": 0.5}}` | r13.json:chosen | R13 | objective below R13；全区间 +42%（带入 +77%） | open |
| R14 | pyramid_exposure | B3 | `{"rule_opts": {"add_signal": "sig_all", "add_signal_frac": 0.5, "add_signal_max": 2, "add_signal_stop": "low", "feedback": 4, "risk_low": 0.0025, "risk_high": 0.01, "max_gross": 2.0, "max_position": 0.5}}` | r13.json:chosen | R13 | objective below R13；全区间 -1%（带入 +77%） | open |
| R14 | pyramid_exposure | B4 | `{"rule_opts": {"add_levels": [1.0, 2.0], "add_frac": 0.5, "max_gross": 2.0, "max_position": 0.5}}` | r13.json:chosen | R13 | gates: placebo；全区间 -36%（带入 +77%） | open |
| R14 | pyramid_exposure | B5 | `{"rule_opts": {"add_levels": [1.0, 2.0], "add_frac": 0.5, "max_gross": 2.0, "max_position": 0.5, "feedback": 4, "risk_low": 0.0025, "risk_high": 0.01}}` | r13.json:chosen | R13 | gates: placebo；全区间 -51%（带入 +77%） | open |
| R15 | exits_2025 | C1 | `{"rule_opts": {"trim_signal": "atr50x7", "trim_signal_frac": 0.7}}` | r14.json:chosen | C4 | gates: bought；全区间 +56%（带入 +48%） | open |
| R15 | exits_2025 | C2 | `{"rule_opts": {"trim_signal": "atr50x7", "trim_signal_frac": 0.7, "trail": "ema21"}}` | r14.json:chosen | C4 | objective below C4；全区间 +22%（带入 +48%） | open |
| R15 | exits_2025 | C3 | `{"rule_opts": {"trim_signal": "atr50x7", "trim_signal_frac": 0.7, "trail": "sma50"}}` | r14.json:chosen | C4 | gates: placebo, bought；全区间 -1%（带入 +48%） | open |
| R15 | exits_2025 | C5 | `{"rule_opts": {"month_loss_cap": 0.05, "month_cap_ladder": [0.03, 0.02, 0.01, 0.005], "month_cap_basis": "opened"}}` | r14.json:chosen | C4 | gates: placebo, bought；全区间 -21%（带入 +48%） | open |
| R16 | exits_2025 | D1 | `{"rule_opts": {"trim_signal": "atr50x7", "trim_signal_frac": 0.7}}` | r15.json:chosen | R15 | gates: bought；全区间 +50%（带入 +48%） | open |
| R16 | exits_2025 | D2 | `{"rule_opts": {"trim_signal": "atr50x7", "trim_signal_frac": 0.5}}` | r15.json:chosen | R15 | gates: bought；全区间 +44%（带入 +48%） | open |
| R16 | exits_2025 | D3 | `{"rule_opts": {"trim_signal": "atr50x5", "trim_signal_frac": 0.7}}` | r15.json:chosen | R15 | objective below R15；全区间 +42%（带入 +48%） | open |
| R16 | exits_2025 | D4 | `{"rule_opts": {"trim_signal": "atr50x7", "trim_signal_frac": 0.7, "trail": "ema21"}}` | r15.json:chosen | R15 | gates: bought；全区间 +34%（带入 +48%） | open |
| R16 | exits_2025 | D5 | `{"rule_opts": {"trim_signal": "atr50x7", "trim_signal_frac": 0.7}, "ep": {"far_low": 1.0}}` | r15.json:chosen | R15 | objective below R15；全区间 +49%（带入 +48%） | open |
| R17 | retest_exposure | E1 | `{"setups": ["hi52", "ep", "pp"], "kind_order": ["ep", "hi52", "pp"]}` | r16.json:chosen | R16 | gates: bought；全区间 +123%（带入 +48%） | open |
| R17 | retest_exposure | E2 | `{"rule_opts": {"risk": 0.0075}}` | r16.json:chosen | R16 | gates: bought；全区间 +25%（带入 +48%） | open |
| R17 | retest_exposure | E3 | `{"rule_opts": {"max_gross": 2.0, "max_open": 12}}` | r16.json:chosen | R16 | gates: placebo；全区间 -8%（带入 +48%） | open |
| R17 | retest_exposure | E4 | `{"rule_opts": {"max_gross": 2.0, "max_open": 12, "risk": 0.0075}}` | r16.json:chosen | R16 | gates: placebo；全区间 -28%（带入 +48%） | open |
| R17 | retest_exposure | E5 | `{"rule_opts": {"trim_day": 5}}` | r16.json:chosen | R16 | objective below R16；全区间 +26%（带入 +48%） | open |
| R18 | pairs | F1 | `{"setups": ["hi52", "ep", "pp"], "kind_order": ["ep", "hi52", "pp"], "max_new": 3}` | r17.json:chosen | R17 | gates: bought；全区间 +99%（带入 +48%） | open |
| R18 | pairs | F2 | `{"setups": ["hi52", "ep", "pp"], "kind_order": ["ep", "hi52", "pp"], "rule_opts": {"max_open": 10}}` | r17.json:chosen | R17 | gates: bought；全区间 +89%（带入 +48%） | open |
| R18 | pairs | F3 | `{"close_any": ["hi52"]}` | r17.json:chosen | R17 | gates: bought；全区间 +180%（带入 +48%） | open |
| R18 | pairs | F4 | `{"setups": ["hi52", "ep", "pp"], "kind_order": ["ep", "hi52", "pp"], "close_any": ["hi52", "pp"]}` | r17.json:chosen | R17 | gates: bought；全区间 +109%（带入 +48%） | open |
| R18 | pairs | F5 | `{"setups": ["hi52", "ep", "pp"], "kind_order": ["ep", "hi52", "pp"], "close_any": ["hi52", "pp"], "rule_opts": {"max_open": 10}}` | r17.json:chosen | R17 | gates: bought；全区间 +84%（带入 +48%） | open |
| R19 | pairs | G1 | `{"close_any": ["hi52"], "rule_opts": {"max_open": 10}}` | r18.json:chosen | R18 | gates: bought；全区间 +176%（带入 +48%） | open |
| R19 | pairs | G2 | `{"close_any": ["hi52"], "max_new": 3}` | r18.json:chosen | R18 | gates: bought；全区间 +103%（带入 +48%） | open |
| R19 | pairs | G3 | `{"close_any": ["hi52"], "max_new": 3, "rule_opts": {"max_open": 10}}` | r18.json:chosen | R18 | objective below R18；全区间 +132%（带入 +48%） | open |
| R19 | pairs | G4 | `{"close_any": ["hi52"], "kind_order": ["ep", "hi52"]}` | r18.json:chosen | R18 | gates: bought；全区间 +120%（带入 +48%） | open |
| R19 | pairs | G5 | `{"close_any": ["hi52"], "rule_opts": {"max_open": 10, "max_gross": 1.5}}` | r18.json:chosen | R18 | gates: bought；全区间 +146%（带入 +48%） | open |
| R20 | slots_by_kind | H1 | `{"setups": ["hi52", "ep", "pb"], "kind_order": ["ep", "hi52", "pb"], "rule_opts": {"max_open_by_kind": {"pb": 3}}}` | r19.json:chosen | R19 | gates: bought, width<=30；全区间 +115%（带入 +48%） | open |
| R20 | slots_by_kind | H2 | `{"setups": ["hi52", "ep", "pb", "vcp"], "kind_order": ["ep", "hi52", "vcp", "pb"], "rule_opts": {"max_open_by_kind": {"pb": 2, "vcp": 2}}}` | r19.json:chosen | R19 | gates: bought, width<=30；全区间 +135%（带入 +48%） | open |
| R20 | slots_by_kind | H3 | `{"setups": ["hi52", "ep", "pb"], "kind_order": ["ep", "hi52", "pb"], "close_any": ["hi52"], "rule_opts": {"max_open_by_kind": {"pb": 3}}}` | r19.json:chosen | R19 | gates: bought, width<=30；全区间 +128%（带入 +48%） | open |
| R20 | slots_by_kind | H4 | `{"setups": ["hi52", "ep", "pp"], "kind_order": ["ep", "hi52", "pp"], "rule_opts": {"max_open_by_kind": {"pp": 2}}}` | r19.json:chosen | R19 | gates: bought；全区间 +123%（带入 +48%） | open |
| R20 | slots_by_kind | H5 | `{"setups": ["hi52", "ep", "pp", "pb"], "kind_order": ["ep", "hi52", "pp", "pb"], "close_any": ["hi52"], "rule_opts": {"max_open_by_kind": {"pp": 2, "pb": 2}}}` | r19.json:chosen | R19 | gates: bought, width<=30；全区间 +128%（带入 +48%） | open |
