# Evan Medeiros 否定登记表

每个没被带入的候选一行（自动写入）；“当时的配置”一列是那一轮的基础配置报告。下游大改后，用 `negations` 动作列出依赖旧配置的行，在新配置上重测。

| 轮次 | 环节 | 候选 | 改了什么 | 当时的配置 | 带入 | 否定依据 | 状态 |
|---|---|---|---|---|---|---|---|
| R1 | pool / entry / exit | L5 | `{"long": {"limit": 0.05}, "short": {"limit": 0.05}}` | :base | DROP | objective below DROP；全区间 +59%（带入 +72%） | open |
| R1 | pool / entry / exit | MID | `{"pool": {"turnover": 50000000.0}}` | :base | DROP | gates: placebo；全区间 -13%（带入 +72%） | open |
| R1 | pool / entry / exit | MIDL5 | `{"pool": {"turnover": 50000000.0}, "long": {"limit": 0.05}, "short": {"limit": 0.05}}` | :base | DROP | gates: behaviour+0.15；全区间 -4%（带入 +72%） | open |
| R1 | pool / entry / exit | X5 | `{"exit_long": "xsma5", "exit_short": "xsma5s"}` | :base | DROP | objective below DROP；全区间 +8%（带入 +72%） | open |
| R2 | entry / exit / short | DL5 | `{"long": {"limit": 0.05}, "short": {"limit": 0.05}}` | r1.json:chosen | EITHER | objective below EITHER；全区间 +16%（带入 +27%） | open |
| R2 | entry / exit / short | EL4 | `{"long": {"rsi": 5, "either": true, "limit": 0.04}, "short": {"limit": 0.04}}` | r1.json:chosen | EITHER | objective below EITHER；全区间 +20%（带入 +27%） | open |
| R2 | entry / exit / short | SNT | `{"short": {"trend": false}}` | r1.json:chosen | EITHER | objective below EITHER；全区间 +83%（带入 +27%） | open |
| R2 | entry / exit / short | XUP | `{"exit_long": "xup", "exit_short": "xdn"}` | r1.json:chosen | EITHER | gates: placebo；全区间 -27%（带入 +27%） | open |
| R3 | short / exit / size | G100 | `{"rule_opts": {"max_open": 10, "max_gross": 1.0}}` | r2.json:chosen | SNT | objective below SNT；全区间 +6%（带入 +35%） | open |
| R3 | short / exit / size | L4 | `{"long": {"limit": 0.04}, "short": {"limit": 0.04}}` | r2.json:chosen | SNT | objective below SNT；全区间 +20%（带入 +35%） | open |
| R3 | short / exit / size | SNTX70 | `{"short": {"trend": false}, "exit_long": "xrsi70", "exit_short": "xrsis70"}` | r2.json:chosen | SNT | objective below SNT；全区间 -11%（带入 +35%） | open |
| R3 | short / exit / size | X70 | `{"exit_long": "xrsi70", "exit_short": "xrsis70"}` | r2.json:chosen | SNT | objective below SNT；全区间 -13%（带入 +35%） | open |
| R4 | pool / volatility | HV4060 | `{"long": {"hv": 40, "hv_max": 60}, "short": {"hv": 40, "hv_max": 60}}` | r3.json:chosen | HV3050 | objective below HV3050；全区间 +39%（带入 +6%） | open |
| R4 | pool / volatility | LC | `{"pool": {"turnover": 100000000.0, "price": 20.0}, "long": {"hv": 25}, "short": {"hv": 25}}` | r3.json:chosen | HV3050 | objective below HV3050；全区间 +12%（带入 +6%） | open |
| R4 | pool / volatility | LC15 | `{"pool": {"turnover": 100000000.0, "price": 20.0}, "long": {"hv": 25}, "short": {"hv": 25}, "rule_opts": {"max_position": 0.15}}` | r3.json:chosen | HV3050 | objective below HV3050；全区间 +8%（带入 +6%） | open |
| R4 | pool / volatility | LCL2 | `{"pool": {"turnover": 100000000.0, "price": 20.0}, "long": {"hv": 25, "limit": 0.02}, "short": {"hv": 25, "limit": 0.02}}` | r3.json:chosen | HV3050 | objective below HV3050；全区间 +6%（带入 +6%） | open |
| R5 | exit / size | B2550 | `{"long": {"hv": 25}, "short": {"hv": 25}}` | r4.json:chosen | B2550T5P15 | objective below B2550T5P15；全区间 +5%（带入 -7%） | open |
| R5 | exit / size | P15 | `{"rule_opts": {"max_position": 0.15}}` | r4.json:chosen | B2550T5P15 | objective below B2550T5P15；全区间 -2%（带入 -7%） | open |
| R5 | exit / size | T5 | `{"rule_opts": {"max_days": 5, "short_max_days": 5}}` | r4.json:chosen | B2550T5P15 | objective below B2550T5P15；全区间 +2%（带入 -7%） | open |
| R5 | exit / size | T5P15 | `{"rule_opts": {"max_days": 5, "short_max_days": 5, "max_position": 0.15}}` | r4.json:chosen | B2550T5P15 | objective below B2550T5P15；全区间 -5%（带入 -7%） | open |
| R6 | pool / entry / exit | B2040 | `{"long": {"hv": 20, "hv_max": 40}, "short": {"hv": 20, "hv_max": 40}}` | r5.json:chosen | T3 | objective below T3；全区间 +20%（带入 -8%） | open |
| R6 | pool / entry / exit | B2540 | `{"long": {"hv": 25, "hv_max": 40}, "short": {"hv": 25, "hv_max": 40}}` | r5.json:chosen | T3 | objective below T3；全区间 +14%（带入 -8%） | open |
| R6 | pool / entry / exit | LATR | `{"long": {"limit_atr": 0.5}, "short": {"limit_atr": 0.5}}` | r5.json:chosen | T3 | objective below T3；全区间 -16%（带入 -8%） | open |
| R6 | pool / entry / exit | X5 | `{"exit_long": "xsma5", "exit_short": "xsma5s"}` | r5.json:chosen | T3 | gates: behav；全区间 -10%（带入 -8%） | open |
| R7 | entry depth x volatility | B2040L0T5 | `{"long": {"hv": 20, "hv_max": 40, "limit": 0.0}, "short": {"hv": 20, "hv_max": 40, "limit": 0.0}, "rule_opts": {"max_days": 5, "short_max_days": 5}}` | r6.json:chosen | B1535L1T5 | gates: behav；全区间 +10%（带入 +23%） | open |
| R7 | entry depth x volatility | B2040L1 | `{"long": {"hv": 20, "hv_max": 40, "limit": 0.01}, "short": {"hv": 20, "hv_max": 40, "limit": 0.01}}` | r6.json:chosen | B1535L1T5 | gates: behav；全区间 +3%（带入 +23%） | open |
| R7 | entry depth x volatility | B2040L1T5 | `{"long": {"hv": 20, "hv_max": 40, "limit": 0.01}, "short": {"hv": 20, "hv_max": 40, "limit": 0.01}, "rule_opts": {"max_days": 5, "short_max_days": 5}}` | r6.json:chosen | B1535L1T5 | objective below B1535L1T5；全区间 -7%（带入 +23%） | open |
| R7 | entry depth x volatility | L1 | `{"long": {"limit": 0.01}, "short": {"limit": 0.01}}` | r6.json:chosen | B1535L1T5 | gates: behav；全区间 -5%（带入 +23%） | open |
| R8 | count / holding | L15 | `{"long": {"limit": 0.015}, "short": {"limit": 0.015}}` | r7.json:chosen | L2 | objective below L2；全区间 +33%（带入 +38%） | open |
| R8 | count / holding | L2T10 | `{"long": {"limit": 0.02}, "short": {"limit": 0.02}, "rule_opts": {"max_days": 10, "short_max_days": 10}}` | r7.json:chosen | L2 | objective below L2；全区间 +25%（带入 +38%） | open |
| R8 | count / holding | O10 | `{"rule_opts": {"max_open": 10}}` | r7.json:chosen | L2 | objective below L2；全区间 +23%（带入 +38%） | open |
| R8 | count / holding | T10 | `{"rule_opts": {"max_days": 10, "short_max_days": 10}}` | r7.json:chosen | L2 | objective below L2；全区间 +17%（带入 +38%） | open |
