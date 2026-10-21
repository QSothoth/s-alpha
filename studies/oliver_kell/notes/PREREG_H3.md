# H3 预登记（Oliver Kell）

2026-10-21 写，看过 H2 之后、跑 H3 之前。规则同 [HUMAN_PREREG_CN](../../trader_replication/notes/HUMAN_PREREG_CN.md)；基础 = H1B（ADR ≤ 5% 的票单只 ≤ 15%，其余 ≤ 9%）：选择段 +82%（2024 +30% / 2025 +40%），回撤 28.2%（H0 27.1%，上限 29.1%）。

## H2 看到的

10 EMA 先卖一半（H2A）收益低于 H0；流动票 30% + 加仓（H2B）+76% 但买到他的 2 < 3、平均赢 +24% 偏离 H0 超 10%；亏后减半（H2C）+70% 过了所有门槛但不如 H1B。都不带入。

## 之前的加仓没有按原话做

他的原话是“15% 核心仓 + 1–2% 止损”，“涨一点就加、提高止损”，理想是“仓位变成两倍、而且没有风险”。H1C / H1D / H2B 的实现是：初始就开到 15% / 30%，加仓后止损只提到原始成交价（加的那部分仍有风险）。本轮改成原话的形态：初始仍按 H1B 的 15% / 9%，收盘浮盈 +1R 时加原仓位一倍，加仓可把仓位放大到自身上限的 2 倍（流动票 30%、其余 18%，引擎新开关 `add_cap_mult`，单测 `test_add_cap_mult_lets_the_add_grow_the_position_past_its_cap`）。

| 键 | 改什么 | 原话 |
|---|---|---|
| H3A | 加仓后整笔止损提到平均成本（`add_stop: cost`，单测 `test_free_roll_add_moves_the_whole_stop_to_the_average_cost`） | “twice as big of a position and I actually have no risk on it”（CMR） |
| H3B | 同 H3A，但止损只提到原始成交价 | “if it moves up a little I will add and raise my stop”（CMR）；回退项 |

+1R、一倍、两倍都是他的数字或最常见值。都不过就沿用 H1B。
