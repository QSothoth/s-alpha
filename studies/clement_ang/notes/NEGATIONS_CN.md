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
