# Clement Ang 否定登记表

每个没被带入的候选一行（自动写入）；“当时的配置”一列是那一轮的基础配置报告。下游大改后，用 `negations` 动作列出依赖旧配置的行，在新配置上重测。

| 轮次 | 环节 | 候选 | 改了什么 | 当时的配置 | 带入 | 否定依据 | 状态 |
|---|---|---|---|---|---|---|---|
| R1 | setups | C1 | `{"setups": ["fine", "pb"]}` | :base | D0c | gates: placebo, width<=30；全区间 +2%（带入 -2%） | open |
| R1 | setups | C2 | `{"setups": ["fine", "ep"], "ep_pool": {"turnover": 5000000.0, "price": 2.0}}` | :base | D0c | gates: placebo；全区间 -28%（带入 -2%） | open |
| R1 | setups | C3 | `{"setups": ["fine", "pb", "ep"], "ep_pool": {"turnover": 5000000.0, "price": 2.0}}` | :base | D0c | gates: placebo, width<=30；全区间 -49%（带入 -2%） | open |
| R1 | setups | C4 | `{"setups": ["pb"]}` | :base | D0c | gates: placebo, width<=30；全区间 -2%（带入 -2%） | open |
| R1 | setups | C5 | `{"setups": ["fine", "pb"], "pool": {"turnover": 20000000.0, "adr": 3.0, "above50": true}}` | :base | D0c | gates: placebo, width<=30；全区间 -18%（带入 -2%） | open |
