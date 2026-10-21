# G1 预登记：共享机制轮（七人各在当前带入版本上）

2026-10-21 写，在跑任何 G1 结果之前。用户要求：继续优化，但每个优化都应用到所有交易员身上，只停留在日 K 层面。规则沿用 [HUMAN_PREREG_CN](HUMAN_PREREG_CN.md)（硬约束、门禁、与 H0 比的接受规则、带入时 100 次安慰剂与不看未来复核），每人的轮次文件在 `studies/<id>/notes/rounds/G1.json`，结果在 `studies/<id>/reports/g1.json`。

## 为什么不再改止损宽度

H 轮把 Qulla、Marios、Kell 的差距定位在止损宽度上（我们收盘买、止损中位 6–7%，他们约 3%）。日 K 实测（Qulla 选择段 532 个突破信号）：挂前 10 日高点买、止损前一日低点（开盘前已知）的宽度中位 7.3%，比现在的 6.4% 还宽；只做前一日很窄（≤ 0.5 ADR）的也有 5.6%，且 27% 入场当天先后不明。窄止损只能来自盘中，日 K 层面不再在这一层花轮次。

## 基础版本

Flanders H5A、Clement H4B、Martin H1A、Kell H1B、Qullamaggie H3A、Marios H3B、Minervini H0。

## 候选（同一机制用到每个人；参数取常见值，不调）

| 键 | 改什么 | 原话 | 不适用 |
|---|---|---|---|
| GA | 当天的多头信号按强度排序后再截名额：强度 = 1 / 3 / 6 个月涨幅在全面板的分位取最高，用前一日（`common.rank: strength`）；原来 EP 优先的人（Flanders C1C、Qullamaggie kind_order）保留 EP 在前（`ep_strength`） | 七人都只做领涨股：Flanders RS ≥ 90、Qullamaggie 1 / 3 / 6 月涨幅榜前列、Clement 1 / 3 / 6 月涨幅榜、Martin 领涨名单、Minervini RS、Marios 强势股 | — |
| GB | 全面板等权指数前一日收在 20 日均线下方时，多头每笔风险 ×0.5（`human.regime`；与仓位档相乘，空头不变） | Kell “指数在 20 EMA 下方风险减半”；Qullamaggie “half size in a market that's bad”、QQQ 均线绿灯；Martin 看 QQQ / IWM 是否在均线上方；Minervini 差市况突破只有 20%–30% 成功 | — |
| GC | 领涨档：强度 ≥ 0.98（前 2%）的多头风险 ×2、单只 ≤ 50%（`cap_above`），排在已有档位之前，合计 ≤ 3 档 | Flanders H5A 的龙头档；Qullamaggie “按信心调整仓位”；Minervini 渐进加大；Martin 领涨股重仓 | Flanders（已有两档，其中一档就是它） |
| GD | 最近 5 笔已平仓合计亏 → 下一笔风险减半（各自基础风险的一半） | Martin “最看重自己新仓的反馈”；Marios “一再止损就收缩”；Minervini “胜率掉到 20%–30% 说明市况不好”；Kell “trade smaller and smaller” | Qullamaggie（H3A 已带入） |

GB 与 GD 是整个账户随市况 / 战绩缩放，不是按个股分档，不计入“≤ 3 档”。

## 判定

逐人：按 `human.accept` 与 H0 比、并好于自己的基础版本才带入（[逐人接受口径](../../../studies/trader_replication/notes/HUMAN_PREREG_CN.md)）；同时报告每个候选让几个人变好（选择段收益或对他的对数差）、几个人通过。港股、A 股与 2026 段只报告。
