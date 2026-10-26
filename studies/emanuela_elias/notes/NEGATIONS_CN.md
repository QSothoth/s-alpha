# Emanuela Elias 否定登记表

每个没被带入的候选一行（自动写入）；“当时的配置”一列是那一轮的基础配置报告。下游大改后，用 `negations` 动作列出依赖旧配置的行，在新配置上重测。

| 轮次 | 环节 | 候选 | 改了什么 | 当时的配置 | 带入 | 否定依据 | 状态 |
|---|---|---|---|---|---|---|---|
| R1 | short gate / stop / hold | H10 | `{"rule_opts": {"max_days": 10, "short_max_days": 10}}` | :base | SL1 | objective below SL1；全区间 -6%（带入 -22%） | open |
| R1 | short gate / stop / hold | SG50 | `{"short_gate": 50}` | :base | SL1 | gates: placebo；全区间 +5%（带入 -22%） | open |
| R1 | short gate / stop / hold | SG50SL1 | `{"short_gate": 50, "stop_level": 0.01}` | :base | SL1 | objective below SL1；全区间 +13%（带入 -22%） | open |
| R1 | short gate / stop / hold | TOP10 | `{"top": 10}` | :base | SL1 | gates: placebo；全区间 -16%（带入 -22%） | open |
| R2 | level / hold / list | B2 | `{"band": 0.02}` | r1.json:chosen | H10 | objective below H10；全区间 +6%（带入 +29%） | open |
| R2 | level / hold / list | LV50 | `{"level": 50}` | r1.json:chosen | H10 | objective below H10；全区间 +21%（带入 +29%） | open |
| R2 | level / hold / list | LV50H10 | `{"level": 50, "rule_opts": {"max_days": 10, "short_max_days": 10}}` | r1.json:chosen | H10 | objective below H10；全区间 +25%（带入 +29%） | open |
| R2 | level / hold / list | TOP20 | `{"top": 20}` | r1.json:chosen | H10 | objective below H10；全区间 +5%（带入 +29%） | open |
| R3 | instrument: option account | O14S1G | `{"opt": {"dte": 14, "mny": 0.02, "frac": 0.1, "spread": 0.01}, "long_gate": 20, "short_gate": 20}` | r2.json:chosen | H10 | gates: placebo, years；全区间 -95%（带入 +29%） | open |
| R3 | instrument: option account | O30 | `{"opt": {"dte": 30, "mny": 0.0, "frac": 0.1, "spread": 0.03}}` | r2.json:chosen | H10 | gates: placebo, years；全区间 -67%（带入 +29%） | open |
| R3 | instrument: option account | O30S1 | `{"opt": {"dte": 30, "mny": 0.0, "frac": 0.1, "spread": 0.01}}` | r2.json:chosen | H10 | gates: placebo, years；全区间 -41%（带入 +29%） | open |
| R3 | instrument: option account | O30S1G | `{"opt": {"dte": 30, "mny": 0.0, "frac": 0.1, "spread": 0.01}, "long_gate": 20, "short_gate": 20}` | r2.json:chosen | H10 | gates: placebo, years；全区间 -63%（带入 +29%） | open |
| R3 | instrument: option account | O60S1G | `{"opt": {"dte": 60, "mny": 0.0, "frac": 0.1, "spread": 0.01}, "long_gate": 20, "short_gate": 20}` | r2.json:chosen | H10 | gates: placebo, years；全区间 -44%（带入 +29%） | open |
| R4 | option exits / size | T3R2 | `{"rule_opts": {"max_days": 3, "short_max_days": 3, "trims": [2], "trim_frac": 1.0}}` | r3.json:chosen | T3R2F25L10 | objective below T3R2F25L10；全区间 +51%（带入 +101%） | open |
| R4 | option exits / size | T3R2F25 | `{"rule_opts": {"max_days": 3, "short_max_days": 3, "trims": [2], "trim_frac": 1.0}, "opt": {"dte": 30, "mny": 0.0, "frac": 0.25, "spread": 0.01}}` | r3.json:chosen | T3R2F25L10 | objective below T3R2F25L10；全区间 +32%（带入 +101%） | open |
| R4 | option exits / size | T3R2F25T30 | `{"top": 30, "rule_opts": {"max_days": 3, "short_max_days": 3, "trims": [2], "trim_frac": 1.0}, "opt": {"dte": 30, "mny": 0.0, "frac": 0.25, "spread": 0.01}}` | r3.json:chosen | T3R2F25L10 | objective below T3R2F25L10；全区间 -1%（带入 +101%） | open |
| R4 | option exits / size | T3R2L10 | `{"level": 10, "rule_opts": {"max_days": 3, "short_max_days": 3, "trims": [2], "trim_frac": 1.0}}` | r3.json:chosen | T3R2F25L10 | objective below T3R2F25L10；全区间 +192%（带入 +101%） | open |
| R5 | option size / tenor | F15 | `{"opt": {"frac": 0.15}}` | r4.json:chosen | F15D14 | gates: years；全区间 +222%（带入 +278%） | open |
| R5 | option size / tenor | F15C15 | `{"opt": {"frac": 0.15, "cap": 1.5}}` | r4.json:chosen | F15D14 | gates: years；全区间 +222%（带入 +278%） | open |
| R5 | option size / tenor | F15T2 | `{"opt": {"frac": 0.15}, "rule_opts": {"max_days": 2, "short_max_days": 2}}` | r4.json:chosen | F15D14 | gates: years；全区间 -21%（带入 +278%） | open |
| R5 | option size / tenor | F20C15 | `{"opt": {"frac": 0.2, "cap": 1.5}}` | r4.json:chosen | F15D14 | objective below F15D14；全区间 +192%（带入 +278%） | open |
| R6 | option contract / size | D14F20 | `{"opt": {"frac": 0.2, "cap": 1.5}}` | r5.json:chosen | D10 | objective below D10；全区间 +149%（带入 +243%） | open |
| R6 | option contract / size | D14F20M2 | `{"opt": {"frac": 0.2, "cap": 1.5, "mny": 0.02}}` | r5.json:chosen | D10 | gates: years；全区间 +39%（带入 +243%） | open |
| R6 | option contract / size | D14M2 | `{"opt": {"mny": 0.02}}` | r5.json:chosen | D10 | gates: years；全区间 +184%（带入 +243%） | open |
| R6 | option contract / size | D7 | `{"opt": {"dte": 7}}` | r5.json:chosen | D10 | gates: years；全区间 +140%（带入 +243%） | open |
| R7 | rule layer under the option exits | BOTH | `{"mode": "both"}` | r6.json:chosen | B2 | gates: years；全区间 -97%（带入 +151%） | open |
| R7 | rule layer under the option exits | LV5 | `{"level": 5}` | r6.json:chosen | B2 | gates: years；全区间 -77%（带入 +151%） | open |
| R7 | rule layer under the option exits | MX5 | `{"max_new": 5}` | r6.json:chosen | B2 | objective below B2；全区间 +188%（带入 +151%） | open |
| R7 | rule layer under the option exits | RCL | `{"at_reclaim": true}` | r6.json:chosen | B2 | gates: placebo, years；全区间 -99%（带入 +151%） | open |
| R8 | re-score under exit-price option pricing | B15 | `{"band": 0.015}` | r6.json:chosen | B2 | gates: years；全区间 +380%（带入 +328%） | open |
| R8 | re-score under exit-price option pricing | B25 | `{"band": 0.025}` | r6.json:chosen | B2 | objective below B2；全区间 +326%（带入 +328%） | open |
| R8 | re-score under exit-price option pricing | B2F12 | `{"band": 0.02, "opt": {"frac": 0.12}}` | r6.json:chosen | B2 | objective below B2；全区间 +466%（带入 +328%） | open |
| R8 | re-score under exit-price option pricing | MX5 | `{"max_new": 5}` | r6.json:chosen | B2 | objective below B2；全区间 +529%（带入 +328%） | open |
