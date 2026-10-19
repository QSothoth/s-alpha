# Martin Luk 否定登记表

每个没被带入的候选一行（自动写入）；“当时的配置”一列是那一轮的基础配置报告。下游大改后，用 `negations` 动作列出依赖旧配置的行，在新配置上重测。

| 轮次 | 环节 | 候选 | 改了什么 | 当时的配置 | 带入 | 否定依据 | 状态 |
|---|---|---|---|---|---|---|---|
| S1 | short: end-to-end from his words (setup choice) | SA | `{"setups": ["Z1"], "gate": "below50", "max_new": 1, "trail": "e9", "trims": [3], "trim_frac": 0.15, "max_days": 3}` | :chosen | none | gates: total, years, down | open |
| S1 | short: end-to-end from his words (setup choice) | SB | `{"setups": ["Z2"], "gate": "below50", "max_new": 1, "trail": "e9", "trims": [3], "trim_frac": 0.15, "max_days": 3}` | :chosen | none | gates: short_placebo, total, years, maxdd, down | open |
| S1 | short: end-to-end from his words (setup choice) | SC | `{"setups": ["Z6"], "gate": "below50", "max_new": 1, "trail": "e9", "trims": [3], "trim_frac": 0.15, "max_days": 3}` | :chosen | none | gates: total, maxdd, down | open |
| S1 | short: end-to-end from his words (setup choice) | SD | `{"setups": ["Z1", "Z2", "Z6"], "gate": "below50", "max_new": 1, "trail": "e9", "trims": [3], "trim_frac": 0.15, "max_days": 3}` | :chosen | none | gates: short_placebo, total, years, maxdd, down | open |
| S1 | short: end-to-end from his words (setup choice) | SE | `{"setups": ["Z1", "Z2", "Z6"], "gate": "", "max_new": 1, "trail": "e9", "trims": [3], "trim_frac": 0.15, "max_days": 3}` | :chosen | none | gates: total, years, maxdd, down | open |
| S2 | short: trigger and exits from the per-trade check (S1 diagnosis) | SF | `{"setups": ["Z11"], "gate": "", "max_new": 1, "trail": "e9", "trims": [], "trim_day": 2, "trim_day_frac": 0.5, "max_days": 0}` | :chosen | none | gates: short_placebo, total, years, maxdd, down | open |
| S2 | short: trigger and exits from the per-trade check (S1 diagnosis) | SG | `{"setups": ["Z11"], "gate": "below21", "max_new": 1, "trail": "e9", "trims": [], "trim_day": 2, "trim_day_frac": 0.5, "max_days": 0}` | :chosen | none | gates: short_placebo, maxdd, down | open |
| S2 | short: trigger and exits from the per-trade check (S1 diagnosis) | SH | `{"setups": ["Z12"], "gate": "", "max_new": 1, "trail": "e9", "trims": [], "trim_day": 2, "trim_day_frac": 0.5, "max_days": 0}` | :chosen | none | gates: short_placebo, total, years, down | open |
| S2 | short: trigger and exits from the per-trade check (S1 diagnosis) | SI | `{"setups": ["Z13"], "gate": "", "max_new": 1, "trail": "e9", "trims": [], "trim_day": 2, "trim_day_frac": 0.5, "max_days": 0}` | :chosen | none | gates: total, years, maxdd, down | open |
| S2 | short: trigger and exits from the per-trade check (S1 diagnosis) | SJ | `{"setups": ["Z1", "Z2", "Z6"], "gate": "", "max_new": 1, "trail": "e9", "trims": [], "trim_day": 2, "trim_day_frac": 0.5, "max_days": 0}` | :chosen | none | gates: total, years, maxdd, down | open |
