# Marios Stamatoudis 否定登记表

每个没被带入的候选一行（自动写入）；“当时的配置”一列是那一轮的基础配置报告。下游大改后，用 `negations` 动作列出依赖旧配置的行，在新配置上重测。

| 轮次 | 环节 | 候选 | 改了什么 | 当时的配置 | 带入 | 否定依据 | 状态 |
|---|---|---|---|---|---|---|---|
| R1 | selection_floors | L1 | `{"ep": {"escape": 0}}` | r0.json:chosen | L4 | gates: placebo；全区间 -29%（带入 +405%） | open |
| R1 | selection_floors | L2 | `{"stop_adr": {"brk": 1.0, "ep": 3.0}}` | r0.json:chosen | L4 | gates: win<=0.35；全区间 +13%（带入 +405%） | open |
| R1 | selection_floors | L3 | `{"ep": {"price": 1.0, "liquid": 2000000.0}, "brk": {"turnover": 2000000.0, "price": 1.0, "adr": 4.0, "top": 0.02}}` | r0.json:chosen | L4 | objective below L4；全区间 +238%（带入 +405%） | open |
