# G3 预登记：渐进暴露（七人各在 G2 之后的带入版本上）

2026-10-21 写，看过 G2 之后、跑 G3 之前。规则同 [PREREG_G1_CN](PREREG_G1_CN.md)。基础：Flanders H5A、Clement H4B、Martin G2B、Kell G1 GB、Qullamaggie G1 GB、Marios G2B、Minervini H0。

七人原话里最一致的仓位主张是渐进暴露：Flanders “做对了加到 0.75%–2.5%，连亏 2–4 笔就降”；Clement “顺利才加，连亏一笔就把下一笔风险减半，离权益高点最多回撤 15%”；Martin “新仓顺利才继续加”；Marios “用上一笔的利润给下一笔”；Kell “trade smaller and smaller until you get a couple trades going”，2022 最大回撤约 25%；Minervini 先试水、亏损超过 10% 后回本代价按几何级数变大。G1 只试过“亏后减半”一边（GD，不行）。

| 键 | 改什么 | 不适用 |
|---|---|---|
| G3A | 两边：最近 5 笔已平仓合计赚 → 风险 ×1.5，合计亏 → ×0.5（各自基础风险；`feedback` / `risk_high` / `risk_low`） | — |
| G3B | 回撤刹车：前一收盘净值比高点低 10% 以上时，新仓风险 ×0.5（引擎新字段 `dd_risk` / `dd_risk_mult`，单测 `test_risk_scales_down_while_equity_at_the_previous_close_is_far_below_its_peak`） | — |

5 笔、1.5、10% 都是常见值，不调。判定同 G1。
