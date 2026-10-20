# Oliver Kell 否定登记表

每个没被带入的候选一行（自动写入）；“当时的配置”一列是那一轮的基础配置报告。下游大改后，用 `negations` 动作列出依赖旧配置的行，在新配置上重测。

| 轮次 | 环节 | 候选 | 改了什么 | 当时的配置 | 带入 | 否定依据 | 状态 |
|---|---|---|---|---|---|---|---|
| H1 | human sizing | H1A | `{"rule_opts": {"max_position": 0.15}}` | H:0 | H1B | H gates: drawdown；全区间 +98%（带入 +0%） | open |
| H1 | human sizing | H1C | `{"rule_opts": {"max_position": 0.15, "add_r": 1.0, "add_frac": 1.0}}` | H:0 | H1B | H gates: drawdown, bought 2 < 3, avg_win 0.257 vs H0 0.207；全区间 +106%（带入 +0%） | open |
| H1 | human sizing | H1D | `{"rule_opts": {"max_position": 0.3, "add_r": 1.0, "add_frac": 1.0}}` | H:0 | H1B | H gates: drawdown, bought 2 < 3, avg_win 0.239 vs H0 0.207；全区间 +109%（带入 +0%） | open |
| H1 | human sizing | H1E | `{"rule_opts": {"max_open": 7}}` | H:0 | H1B | H gates: segment not above H0, avg_win 0.176 vs H0 0.207；全区间 +33%（带入 +0%） | open |
| R1 | end_to_end | V1 | `{"priority": "turnover"}` | :base | D0c | gates: placebo；全区间 -13%（带入 -2%） | open |
| R1 | end_to_end | V2 | `{"rule_opts": {"trim_signal": "below_ema10", "trim_signal_frac": 0.5}}` | :base | D0c | gates: placebo；全区间 -17%（带入 -2%） | open |
| R1 | end_to_end | V3 | `{"filter": "IDX20", "rule_opts": {"risk_scale": "", "max_position": 0.15, "max_open": 7, "max_gross": 1.5}}` | :base | D0c | gates: placebo；全区间 -0%（带入 -2%） | open |
| R1 | end_to_end | V4 | `{"rule_opts": {"trim_signal": "ext10_30", "trim_signal_frac": 0.3333}}` | :base | D0c | gates: placebo；全区间 +14%（带入 -2%） | open |
| R1 | end_to_end | V5 | `{"priority": "turnover", "filter": "IDX20", "rule_opts": {"risk_scale": "", "max_position": 0.15, "max_open": 7, "max_gross": 1.5, "trim_signal": "ext10_30", "trim_signal_frac": 0.3333}}` | :base | D0c | gates: placebo；全区间 +12%（带入 -2%） | open |
| S1 | short: Wedge Drop and Downside EMA Crossback end-to-end (RULES 9, OK6, OK7) | KA | `{"setups": ["drop"], "gate": "below20", "max_new": 2, "trail": "ema20", "trims": [], "max_days": 0}` | :chosen | none | gates: short_placebo, total, years, down | open |
| S1 | short: Wedge Drop and Downside EMA Crossback end-to-end (RULES 9, OK6, OK7) | KB | `{"setups": ["dcross"], "gate": "below20", "max_new": 2, "trail": "ema20", "trims": [], "max_days": 0}` | :chosen | none | gates: short_placebo, total, years, down | open |
| S1 | short: Wedge Drop and Downside EMA Crossback end-to-end (RULES 9, OK6, OK7) | KC | `{"setups": ["drop", "dcross"], "gate": "below20", "max_new": 2, "trail": "ema20", "trims": [], "max_days": 0}` | :chosen | none | gates: short_placebo, total, years, maxdd, down | open |
| S1 | short: Wedge Drop and Downside EMA Crossback end-to-end (RULES 9, OK6, OK7) | KD | `{"setups": ["drop", "dcross"], "gate": "", "max_new": 2, "trail": "ema20", "trims": [], "max_days": 0}` | :chosen | none | gates: short_placebo, total, years, maxdd, down | open |
| S1 | short: Wedge Drop and Downside EMA Crossback end-to-end (RULES 9, OK6, OK7) | KE | `{"setups": ["drop", "dcross"], "gate": "below20", "max_new": 2, "trail": "ema10", "trims": [], "max_days": 0}` | :chosen | none | gates: short_placebo, total, years, down | open |
| R2 | setups | W1 | `{"setups": ["pop", "cross", "pb"]}` | r1.json:chosen | R1 | gates: placebo, width<=30；全区间 -63%（带入 -2%） | open |
| R2 | setups | W2 | `{"setups": ["pop", "cross", "vcp", "brk52"]}` | r1.json:chosen | R1 | gates: placebo, width<=30；全区间 -28%（带入 -2%） | open |
| R2 | setups | W3 | `{"setups": ["pop", "cross", "ib2"]}` | r1.json:chosen | R1 | gates: placebo；全区间 -8%（带入 -2%） | open |
| R2 | setups | W4 | `{"setups": ["pop", "cross", "ur"]}` | r1.json:chosen | R1 | gates: placebo；全区间 -38%（带入 -2%） | open |
| R2 | setups | W5 | `{"setups": ["pop", "cross", "pb", "vcp", "brk52", "ib2", "ur"], "priority": "turnover"}` | r1.json:chosen | R1 | gates: placebo, width<=30；全区间 +9%（带入 -2%） | open |
| S2 | short: the rally into the falling line after a Wedge Drop as a limit (his CAVA short) | KF | `{"setups": ["lim20"], "gate": "below20", "max_new": 2, "stop_w": "cap", "trail": "ema20", "trims": [], "max_days": 0}` | :chosen | none | gates: total, years | open |
| S2 | short: the rally into the falling line after a Wedge Drop as a limit (his CAVA short) | KG | `{"setups": ["lim10"], "gate": "below20", "max_new": 2, "stop_w": "cap", "trail": "ema20", "trims": [], "max_days": 0}` | :chosen | none | gates: short_placebo, total, years, maxdd, down | open |
| S2 | short: the rally into the falling line after a Wedge Drop as a limit (his CAVA short) | KH | `{"setups": ["lim50"], "gate": "below20", "max_new": 2, "stop_w": "cap", "trail": "ema20", "trims": [], "max_days": 0}` | :chosen | none | gates: short_placebo, total, down | open |
| S2 | short: the rally into the falling line after a Wedge Drop as a limit (his CAVA short) | KI | `{"setups": ["lim20", "lim10", "lim50"], "gate": "", "max_new": 2, "stop_w": "cap", "trail": "ema20", "trims": [], "max_days": 0}` | :chosen | none | gates: total, years | open |
| S2 | short: the rally into the falling line after a Wedge Drop as a limit (his CAVA short) | KJ | `{"setups": ["lim20", "lim10", "lim50"], "gate": "below20", "max_new": 2, "stop_w": "cap", "trail": "ema10", "trims": [], "max_days": 0}` | :chosen | none | gates: total, years | open |
| R3 | end_to_end_pairs | X1 | `{"setups": ["pop", "cross", "pb", "vcp", "brk52", "ib2", "ur"], "priority": "turnover", "rule_opts": {"trim_signal": "below_ema10", "trim_signal_frac": 0.5}}` | r2.json:chosen | R2 | gates: width<=30；全区间 +47%（带入 -2%） | open |
| R3 | end_to_end_pairs | X2 | `{"setups": ["pop", "cross", "pb", "vcp", "brk52", "ib2", "ur"], "priority": "turnover", "rule_opts": {"trim_day": 11, "trim_day_frac": 0.3333}}` | r2.json:chosen | R2 | gates: width<=30；全区间 +31%（带入 -2%） | open |
| R3 | end_to_end_pairs | X3 | `{"setups": ["pop", "cross", "pb", "vcp", "brk52", "ib2", "ur"], "priority": "turnover", "filter": "IDX20", "rule_opts": {"risk_scale": "", "max_position": 0.15, "max_open": 7, "max_gross": 1.5}}` | r2.json:chosen | R2 | gates: width<=30；全区间 +25%（带入 -2%） | open |
| R3 | end_to_end_pairs | X4 | `{"setups": ["pop", "cross", "pb", "vcp", "brk52", "ib2", "ur"], "priority": "turnover", "strength": "rs80"}` | r2.json:chosen | R2 | gates: placebo, width<=30；全区间 +13%（带入 -2%） | open |
| R3 | end_to_end_pairs | X5 | `{"setups": ["pop", "cross", "pb", "vcp", "brk52", "ib2", "ur"], "priority": "turnover", "strength": "rs80", "filter": "IDX20", "rule_opts": {"risk_scale": "", "max_position": 0.15, "max_open": 7, "max_gross": 1.5}}` | r2.json:chosen | R2 | gates: width<=30；全区间 +36%（带入 -2%） | open |
| S3 | short: on S2 KJ, when and how much (market switch, room left to the longs, his next-day cover) | KM | `{"setups": ["lim20", "lim10", "lim50"], "gate": "below20", "max_new": 2, "stop_w": "cap", "trail": "ema10", "trims": [], "max_days": 0, "max_open": 1}` | :chosen | KK | gates: total, years | open |
| S3 | short: on S2 KJ, when and how much (market switch, room left to the longs, his next-day cover) | KO | `{"setups": ["lim20", "lim10", "lim50"], "gate": "below20", "max_new": 2, "stop_w": "cap", "trail": "ema10", "trims": [], "max_days": 0, "trim_day": 1, "trim_day_frac": 0.5}` | :chosen | KK | gates: total, years | open |
| S3 | short: on S2 KJ, when and how much (market switch, room left to the longs, his next-day cover) | KP | `{"setups": ["lim20", "lim10", "lim50"], "gate": "below50", "max_new": 2, "stop_w": "cap", "trail": "ema10", "trims": [], "max_days": 0, "max_open": 1}` | :chosen | KK | objective below KK | open |
| R4 | narrow | Y1 | `{"setups": ["pop", "cross", "pb", "vcp", "brk52", "ib2", "ur"], "priority": "turnover", "strength": "rs90", "rule_opts": {"trim_signal": "below_ema10", "trim_signal_frac": 0.5}}` | r3.json:chosen | Y5 | gates: width<=30；全区间 +75%（带入 +61%） | open |
| R4 | narrow | Y2 | `{"setups": ["pop", "cross", "pb", "vcp", "brk52", "ib2", "ur"], "priority": "turnover", "strength": "rs95", "rule_opts": {"trim_signal": "below_ema10", "trim_signal_frac": 0.5}}` | r3.json:chosen | Y5 | objective below Y5；全区间 +2%（带入 +61%） | open |
| R4 | narrow | Y3 | `{"setups": ["pop", "cross", "pb", "vcp", "brk52", "ib2", "ur"], "priority": "turnover", "pool": {"turnover": 100000000.0, "adr": 3.0, "above50": false}, "rule_opts": {"trim_signal": "below_ema10", "trim_signal_frac": 0.5}}` | r3.json:chosen | Y5 | gates: width<=30；全区间 +44%（带入 +61%） | open |
| R4 | narrow | Y4 | `{"setups": ["pop", "cross", "pb", "vcp", "brk52", "ib2", "ur"], "priority": "turnover", "strength": "rs90", "pool": {"turnover": 100000000.0, "adr": 3.0, "above50": false}, "rule_opts": {"trim_signal": "below_ema10", "trim_signal_frac": 0.5}}` | r3.json:chosen | Y5 | objective below Y5；全区间 +65%（带入 +61%） | open |
| S4 | short, gate v2: the S2/S3 limit shorts after a Wedge Drop, capped at 10 days | K4B | `{"setups": ["lim20", "lim10", "lim50"], "gate": "below50", "max_new": 2, "max_open": 1, "stop_w": "cap", "trail": "ema10", "trims": [], "max_days": 10}` | :chosen | K4A | objective below K4A | open |
| S4 | short, gate v2: the S2/S3 limit shorts after a Wedge Drop, capped at 10 days | K4C | `{"setups": ["lim20", "lim10", "lim50"], "gate": "below20", "max_new": 2, "stop_w": "cap", "trail": "ema10", "trims": [], "max_days": 10}` | :chosen | K4A | objective below K4A | open |
| S4 | short, gate v2: the S2/S3 limit shorts after a Wedge Drop, capped at 10 days | K4D | `{"setups": ["lim20", "lim10", "lim50"], "gate": "below50", "max_new": 2, "stop_w": "cap", "trail": "ema10", "trims": [], "max_days": 5}` | :chosen | K4A | gates: alpha | open |
| S4 | short, gate v2: the S2/S3 limit shorts after a Wedge Drop, capped at 10 days | K4E | `{"setups": ["lim20", "lim10", "lim50"], "gate": "below50", "max_new": 2, "stop_w": "cap", "trail": "ema10", "trims": [], "max_days": 10, "trim_day": 1, "trim_day_frac": 0.5}` | :chosen | K4A | objective below K4A | open |
| R5 | entry | Z1 | `{"close_any": ["pb", "ib2", "cross", "vcp", "brk52"]}` | r4.json:chosen | Z5 | objective below Z5；全区间 +118%（带入 +173%） | open |
| R5 | entry | Z2 | `{"close_any": ["pb", "ib2", "cross", "vcp", "brk52"], "max_new": 3}` | r4.json:chosen | Z5 | objective below Z5；全区间 +116%（带入 +173%） | open |
| R5 | entry | Z3 | `{"close_any": ["pb", "ib2", "cross", "vcp", "brk52"], "strength": "rs80"}` | r4.json:chosen | Z5 | objective below Z5；全区间 +61%（带入 +173%） | open |
| R5 | entry | Z4 | `{"close_any": ["pb", "ib2", "cross", "vcp", "brk52"], "rule_opts": {"trim_day": 11, "trim_day_frac": 0.3333}}` | r4.json:chosen | Z5 | objective below Z5；全区间 +103%（带入 +173%） | open |
| S5 | short, gate v2: on S4 K4A (his 10 or 20 EMA, his EMA lines only, a shorter cap) | K5A | `{"setups": ["lim20", "lim10", "lim50"], "gate": "below50", "max_new": 2, "stop_w": "cap", "trail": "ema20", "trims": [], "max_days": 10}` | s4.json:chosen | K5B | gates: alpha | open |
| S5 | short, gate v2: on S4 K4A (his 10 or 20 EMA, his EMA lines only, a shorter cap) | K5C | `{"setups": ["lim20", "lim10", "lim50"], "gate": "below50", "max_new": 2, "stop_w": "cap", "trail": "ema10", "trims": [], "max_days": 7}` | s4.json:chosen | K5B | objective below K5B | open |
| R6 | capacity | A1 | `{"max_new": 4}` | r5.json:chosen | A5 | objective below A5；全区间 +83%（带入 +116%） | open |
| R6 | capacity | A2 | `{"rule_opts": {"max_open": 10}}` | r5.json:chosen | A5 | objective below A5；全区间 +144%（带入 +116%） | open |
| R6 | capacity | A3 | `{"max_new": 4, "rule_opts": {"max_open": 10}}` | r5.json:chosen | A5 | objective below A5；全区间 +134%（带入 +116%） | open |
| R6 | capacity | A4 | `{"max_new": 4, "rule_opts": {"max_open": 10, "max_gross": 2.0}}` | r5.json:chosen | A5 | objective below A5；全区间 +132%（带入 +116%） | open |
| R7 | upstream | B1 | `{"strength": "st90"}` | r6.json:chosen | R6 | objective below R6；全区间 +118%（带入 +116%） | open |
| R7 | upstream | B2 | `{"pool": {"turnover": 100000000.0, "adr": 2.0, "above50": false}}` | r6.json:chosen | R6 | objective below R6；全区间 +127%（带入 +116%） | open |
| R7 | upstream | B3 | `{"strength": "st90", "pool": {"turnover": 100000000.0, "adr": 2.0, "above50": false}}` | r6.json:chosen | R6 | gates: width<=30；全区间 +127%（带入 +116%） | open |
| R7 | upstream | B4 | `{"strength": "st90", "pool": {"turnover": 50000000.0, "adr": 2.0, "above50": false}}` | r6.json:chosen | R6 | gates: width<=30；全区间 +130%（带入 +116%） | open |
| R8 | order | C1 | `{"priority": "strength"}` | r7.json:chosen | R7 | gates: placebo；全区间 -11%（带入 +116%） | open |
| R8 | order | C2 | `{"priority": "rs"}` | r7.json:chosen | R7 | objective below R7；全区间 +65%（带入 +116%） | open |
| R8 | order | C3 | `{"strength": "st90", "rule_opts": {"max_open": 14}}` | r7.json:chosen | R7 | objective below R7；全区间 +112%（带入 +116%） | open |
| R8 | order | C4 | `{"strength": "st90", "max_new": 6}` | r7.json:chosen | R7 | objective below R7；全区间 +146%（带入 +116%） | open |
| R8 | order | C5 | `{"strength": "st90", "priority": "rs"}` | r7.json:chosen | R7 | objective below R7；全区间 +51%（带入 +116%） | open |
| R9 | exits | E1 | `{"rule_opts": {"trim_signal2": "below_ema10", "trim_signal2_frac": 0.5}}` | r8.json:chosen | R8 | objective below R8；全区间 +75%（带入 +116%） | open |
| R9 | exits | E2 | `{"rule_opts": {"trim_signal2": "below_ema10", "trim_signal2_frac": 0.5, "trim_day": 11, "trim_day_frac": 0.3333}}` | r8.json:chosen | R8 | objective below R8；全区间 +50%（带入 +116%） | open |
| R9 | exits | E3 | `{"strength": "st90", "rule_opts": {"trim_signal2": "below_ema10", "trim_signal2_frac": 0.5}}` | r8.json:chosen | R8 | objective below R8；全区间 +80%（带入 +116%） | open |
| R9 | exits | E4 | `{"rule_opts": {"trim_signal2": "below_ema10", "trim_signal2_frac": 0.5, "max_open": 10}}` | r8.json:chosen | R8 | objective below R8；全区间 +76%（带入 +116%） | open |
| R9 | exits | E5 | `{"strength": "st90", "rule_opts": {"trim_signal2": "below_ema10", "trim_signal2_frac": 0.5, "trim_day": 11, "trim_day_frac": 0.3333}}` | r8.json:chosen | R8 | objective below R8；全区间 +57%（带入 +116%） | open |
