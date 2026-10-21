# H4 预登记（Oliver Kell）

2026-10-21 写，看过 H3 之后、跑 H4 之前。规则同 [HUMAN_PREREG_CN](../../trader_replication/notes/HUMAN_PREREG_CN.md)；基础 = H1B：选择段 +82%（2024 +30% / 2025 +40%），回撤 28.2%。

## H3 看到的

按原话加仓（+1R 加一倍、可到自身上限两倍）收益大幅提高：止损到平均成本（H3A）+142%（2024 +79% / 2025 +35%），止损到成交价（H3B）+128%，回撤都在线内、安慰剂排位 1.00。都因行为门槛不带入：买到他的有日期多头 2 < 3；H3A 胜率 14.1% < H0 19.9% − 2；平均赚、平均亏与 H0 的对数差超过 0.10。头部交易已核对：SMCI（2024-01-05 回踩，29.21，ADR > 5% 的次级仓 9% 加到 18%）、APP、HOOD 都是同样的赢家加仓后变大。

H3 让 9% 的次级仓也加到 18%，头部的 SMCI 正是他说“never going to have as big of a position”的那一类。本轮按原话：只有流动核心仓（ADR ≤ 5%，15%）能加到 30%，次级仓不加（仓位档新字段 `add_mult`，单测 `test_add_cap_mult_lets_the_add_grow_the_position_past_its_cap`、`test_a_tier_cap_stays_under_the_study_cap_unless_cap_above`）。

| 键 | 改什么 | 原话 |
|---|---|---|
| H4A | 只有流动核心仓 +1R 加一倍到 ≤ 30%，止损到平均成本 | “15% position”“twice as big of a position and I actually have no risk on it”（OK2、CMR）；SMCI 类 “never going to have as big of a position”（RAY 1:16:43） |
| H4B | 同 H4A，止损只提到成交价 | “I will add and raise my stop”（CMR）；回退项 |

都不过就沿用 H1B，并把 H3A 作为“只差行为门槛”的候选交用户判断。
