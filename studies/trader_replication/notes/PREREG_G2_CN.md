# G2 预登记：共享机制轮（七人各在 G1 之后的带入版本上）

2026-10-21 写，看过 G1 之后、跑 G2 之前。规则同 [PREREG_G1_CN](PREREG_G1_CN.md)。基础：Flanders H5A、Clement H4B、Martin / Kell / Qullamaggie G1 GB（指数在 20 日线下方风险减半）、Marios H3B、Minervini H0。

## G1 看到的

弱市减半（GB）4 / 7 变好、3 人带入；领涨档 ×2（GC）收益大（Marios +269%、Qulla +97%）但卡回撤；按强度排序、亏后减半都不行。见 [SHARED_ROUNDS_CN](SHARED_ROUNDS_CN.md)。

## 候选（同一机制用到每个人；`human.regime` 只有一条，G2B / G2C 替换掉基础里已有的 GB）

| 键 | 改什么 | 原话 | 不适用 |
|---|---|---|---|
| G2A | 领涨档（强度 ≥ 0.98 → 风险 ×2、≤ 50%）+ 弱市减半（指数 20 日线），成对：减半管回撤 | G1 的 GB、GC 两条原话 | Flanders（已有领涨档；成对等于 G1 GB） |
| G2B | 宽度定市况：全面板站上自己 50 日线的比例前一日 < 50% 时多头风险减半（`regime.kind: breadth`） | Martin “领涨名单只数越来越少、落后名单越来越多就是市况变差”；Flanders 看短线宽度 | — |
| G2C | 指数前一日在 50 日线下方时不开新多头（`regime.risk: 0`；空头照常） | Minervini “熊市或修正之后，领涨股多在跟进日后出现”、只在确认的上升趋势里买；O'Neil 的 M | — |

50 日、50% 是常见值，不调。判定同 G1。
