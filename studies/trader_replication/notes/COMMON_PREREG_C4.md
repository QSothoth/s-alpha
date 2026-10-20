# C4 预登记：他的 EP 单独计名额（名额，只增加）

2026-10-20，C1–C3 检查点之后写定，跑完不改。

## 机制与依据

诊断：每天名额挤掉他的 25 笔，其中约 15 笔是各人自己定义下的 EP（Flanders 6、Marios 4、Martin 的 GME / AMC / SMTC 等）。C1 证明换排序把它们排进来会挤掉现有交易、账户变差。本轮只增加：**他的 EP 另有每天的名额，不占其他形态的名额**；其余形态、排序、资金、持仓上限、总敞口都照旧（EP 仍要有资金和持仓空间）。Flanders、Kell 的 FINAL 都建议过“按形态分开计名额”；原话：EP 是 Qullamaggie、Flanders、Marios 的主要买点之一，Martin 每天先看盘前跳空扫描。

实现：引擎新字段 `max_new_by_kind`（默认空，登记系统不变）；Martin 这种在 build 里截断的，保留当天前 4 笔非 EP + 前 k 笔 EP。EP 用各人自己的定义（kind `ep`；Martin `ep_signal`）。Kell、Minervini 没有 EP，不适用。执行时点单测 `tests/test_common.py`（EpSlotTests）。

## 候选

| 候选 | EP 每天名额（各自原排序） |
|---|---|
| C4A | 1 |
| C4B | 2 |
| C4C | 与他其他形态的每天名额相同（Martin 4、Flanders 2、Clement 10、Qullamaggie 5、Marios 3） |

## 评测与接受规则

同 [C1](COMMON_PREREG_C1.md)（固定）。适用的是 5 人，仍要 ≥ 4 / 7 人变好。
