# Clement Ang 否定登记表

每个没被带入的候选一行（自动写入）；“当时的配置”一列是那一轮的基础配置报告。下游大改后，用 `negations` 动作列出依赖旧配置的行，在新配置上重测。

| 轮次 | 环节 | 候选 | 改了什么 | 当时的配置 | 带入 | 否定依据 | 状态 |
|---|---|---|---|---|---|---|---|
| R1 | setups | C1 | `{"setups": ["fine", "pb"]}` | :base | D0c | gates: placebo, width<=30；全区间 +2%（带入 -2%） | open |
| R1 | setups | C2 | `{"setups": ["fine", "ep"], "ep_pool": {"turnover": 5000000.0, "price": 2.0}}` | :base | D0c | gates: placebo；全区间 -28%（带入 -2%） | open |
| R1 | setups | C3 | `{"setups": ["fine", "pb", "ep"], "ep_pool": {"turnover": 5000000.0, "price": 2.0}}` | :base | D0c | gates: placebo, width<=30；全区间 -49%（带入 -2%） | open |
| R1 | setups | C4 | `{"setups": ["pb"]}` | :base | D0c | gates: placebo, width<=30；全区间 -2%（带入 -2%） | open |
| R1 | setups | C5 | `{"setups": ["fine", "pb"], "pool": {"turnover": 20000000.0, "adr": 3.0, "above50": true}}` | :base | D0c | gates: placebo, width<=30；全区间 -18%（带入 -2%） | open |
| R2 | exits_capacity | K1 | `{"rule_opts": {"trims": [2], "trim_frac": 0.3333, "breakeven_r": 2.0, "trail": "ema10", "trim_signal": "atr50x8", "trim_signal_frac": 0.3333}}` | r1.json:chosen | K2 | objective below K2；全区间 +1%（带入 +2%） | open |
| R2 | exits_capacity | K3 | `{"rule_opts": {"trims": [2], "trim_frac": 0.3333, "breakeven_r": 2.0, "trail": "ema10", "trim_signal": "atr50x8", "trim_signal_frac": 0.3333, "max_open": 20}, "max_new": 3, "setups": ["fine", "pb"]}` | r1.json:chosen | K2 | gates: width<=30；全区间 +13%（带入 +2%） | open |
| R2 | exits_capacity | K4 | `{"rule_opts": {"trims": [2], "trim_frac": 0.3333, "breakeven_r": 2.0, "trail": "ema10", "trim_signal": "atr50x8", "trim_signal_frac": 0.3333, "max_open": 20}, "max_new": 3, "setups": ["fine", "pb", "ep"], "ep_pool": {"turnover": 5000000.0, "price": 2.0}}` | r1.json:chosen | K2 | gates: placebo, width<=30；全区间 -19%（带入 +2%） | open |
| R2 | exits_capacity | K5 | `{"rule_opts": {"trims": [2], "trim_frac": 0.3333, "breakeven_r": 2.0, "trail": "ema10", "trim_signal": "atr50x8", "trim_signal_frac": 0.3333, "max_open": 20}, "max_new": 3, "setups": ["fine", "pb"], "filter": "IDX20"}` | r1.json:chosen | K2 | gates: width<=30；全区间 +20%（带入 +2%） | open |
| R3 | selection | F2 | `{"fine": {"tight": 3.0}}` | r2.json:chosen | F1 | gates: placebo；全区间 -13%（带入 +57%） | open |
| R3 | selection | F3 | `{"fine": {"near": 0.25, "tight": 3.0}}` | r2.json:chosen | F1 | objective below F1；全区间 +43%（带入 +57%） | open |
| R3 | selection | F4 | `{"fine": {"near": 0.25, "tight": 3.0}, "setups": ["fine", "pb"]}` | r2.json:chosen | F1 | gates: width<=30；全区间 +15%（带入 +57%） | open |
| R3 | selection | F5 | `{"fine": {"near": 0.25, "tight": 3.0}, "setups": ["fine", "pb"], "filter": "IDX20"}` | r2.json:chosen | F1 | gates: width<=30；全区间 +15%（带入 +57%） | open |
| R4 | selection_order | G1 | `{"setups": ["fine", "pb"], "fine": {"near": 0.25, "tight": 3.0}, "priority": "rs"}` | r3.json:chosen | R3 | gates: placebo, width<=30；全区间 -10%（带入 +57%） | open |
| R4 | selection_order | G2 | `{"setups": ["fine", "pb"], "fine": {"near": 0.25, "tight": 3.0}, "max_new": 5}` | r3.json:chosen | R3 | gates: width<=30；全区间 +26%（带入 +57%） | open |
| R4 | selection_order | G3 | `{"setups": ["fine", "pb"], "fine": {"near": 0.25, "tight": 3.0}, "priority": "rs", "max_new": 5}` | r3.json:chosen | R3 | gates: width<=30；全区间 +6%（带入 +57%） | open |
| R4 | selection_order | G4 | `{"setups": ["fine", "pb", "ep"], "fine": {"near": 0.25, "tight": 3.0}, "priority": "rs", "max_new": 5}` | r3.json:chosen | R3 | gates: placebo, width<=30；全区间 -1%（带入 +57%） | open |
| R4 | selection_order | G5 | `{"setups": ["fine", "pb"], "fine": {"near": 0.25, "tight": 3.0}, "priority": "rs", "max_new": 5, "filter": "IDX20"}` | r3.json:chosen | R3 | gates: width<=30；全区间 +27%（带入 +57%） | open |
| R5 | selection | H1 | `{"setups": ["fine", "pb"], "pb": {"fine": true}}` | r4.json:chosen | R4 | objective below R4；全区间 +19%（带入 +57%） | open |
| R5 | selection | H2 | `{"setups": ["fine", "pb"], "pb": {"fine": true, "rs": 80}}` | r4.json:chosen | R4 | objective below R4；全区间 +33%（带入 +57%） | open |
| R5 | selection | H3 | `{"setups": ["fine", "pb"], "pb": {"fine": true}, "max_new": 5}` | r4.json:chosen | R4 | objective below R4；全区间 +13%（带入 +57%） | open |
| R5 | selection | H4 | `{"setups": ["fine", "pb", "ep"], "pb": {"fine": true}}` | r4.json:chosen | R4 | gates: placebo；全区间 -2%（带入 +57%） | open |
| R5 | selection | H5 | `{"setups": ["fine", "pb"], "pb": {"fine": true}, "fine": {"near": 0.25, "tight": 3.0}}` | r4.json:chosen | R4 | objective below R4；全区间 +26%（带入 +57%） | open |
| R6 | order | I1 | `{"priority": "turnover"}` | r5.json:chosen | I3 | objective below I3；全区间 +26%（带入 +117%） | open |
| R6 | order | I2 | `{"priority": "turnover", "setups": ["fine", "pb"], "pb": {"fine": true}}` | r5.json:chosen | I3 | objective below I3；全区间 +73%（带入 +117%） | open |
| R6 | order | I4 | `{"priority": "turnover", "fine": {"near": 0.25, "tight": 3.0}}` | r5.json:chosen | I3 | objective below I3；全区间 +59%（带入 +117%） | open |
| R6 | order | I5 | `{"priority": "turnover", "setups": ["fine", "pb"], "pb": {"fine": true}, "filter": "IDX20"}` | r5.json:chosen | I3 | objective below I3；全区间 +60%（带入 +117%） | open |
| R7 | entry_capacity | J1 | `{"max_new": 8}` | r6.json:chosen | J4 | objective below J4；全区间 +104%（带入 +73%） | open |
| R7 | entry_capacity | J2 | `{"close_any": ["pb"]}` | r6.json:chosen | J4 | objective below J4；全区间 +106%（带入 +73%） | open |
| R7 | entry_capacity | J3 | `{"max_new": 8, "close_any": ["pb"]}` | r6.json:chosen | J4 | objective below J4；全区间 +114%（带入 +73%） | open |
| R7 | entry_capacity | J5 | `{"max_new": 8, "close_any": ["pb"], "rule_opts": {"max_open": 30}}` | r6.json:chosen | J4 | objective below J4；全区间 +115%（带入 +73%） | open |
