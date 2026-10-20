# C2 预登记：收盘买的止损宽度上限（入场与止损）

2026-10-20，C1 跑完之前写定（写时只看过 C1 的 Martin 与 Flanders C1A 两行），跑完不改。

## 机制与依据

收盘买时“收盘到当日低点”的止损常比他本人盘中入场宽得多：他交易日的宽度中位数 Marios 1.9 个 ADR、Qullamaggie 1.6、Flanders 1.5、Minervini 1.4；EP 日大多超过 1 个 ADR（[COMMON_GAPS_CN](COMMON_GAPS_CN.md) 第 4 节）。固定风险定仓下，宽止损让他最好的那些交易只有很小的仓位；“宽了就跳过”又会跳过他的大日子（METHOD 第 9 节）。各人处理不一：Martin、Flanders 宽了上移到上限照做，Qullamaggie、Marios 跳过，Clement、Kell、Minervini 不封顶。机制：**止损宽于本人原话的上限时，上移到上限照做**（C2A），对照“宽了就不做”（C2B）和原话里较紧的一端（C2C）。

上限 = min(百分比, k × 前一日 ADR)。ATR 用 ADR 代替（同量级，Marios 研究的先例）。他的 EP 用各人自己的 EP 定义（kind `ep`；Martin 用 `ep_signal`）。开关打开时，各人原有的“宽了跳过”（`stop_adr`）和上限（`stop_cap`）由它取代；止损下限 1% 不变；空头不动。执行时点单测 `tests/test_common.py`（只用前一日 ADR）。

## 每人取值（原话）

| | 原话 | C2A 上移照做 | C2B 宽了不做 | C2C 较紧一端、上移照做 |
|---|---|---|---|---|
| Martin | 不超过 ADR 一半、最多 5%；现在基本不超过 2.5%–3% | 不变（登记版本已是 min(5%, 0.5 ADR) 上移） | min(5%, 0.5 ADR) 跳过 | min(3%, 0.5 ADR) |
| Flanders | 当日低点；“开盘就买、6% 止损也行” | 不变（已是 6% 上移） | 6% 跳过 | 不变（原话只有 6%） |
| Clement | 当日低点；不买离当日低点超过 0.6 ATR 的位置 | 0.6 ADR | 0.6 ADR 跳过 | 0.6 ADR |
| Qullamaggie | 止损不宽于 ADR；“no more than 1x, or maximum 1.5x” | 突破 1 ADR、EP 1.5 ADR | 同左，跳过 | 都是 1 ADR |
| Kell | “15% position with a 1-2% stop” | 2% | 2% 跳过 | 1% |
| Minervini | 平均亏损 3%–4%（紧时）、硬上限 8% | 8% | 8% 跳过 | 4% |
| Marios | 止损宽度 ≤ 1 个 ATR | 1 ADR | 1 ADR 跳过 | 1 ADR |

C2C 里 Clement、Marios 与 C2A 相同（原话只有一个数）。

## 评测与接受规则

同 [C1](COMMON_PREREG_C1.md)：7 人、美股、选择段 2024-01-02 → 2025-12-31，以登记版本为基线；≥ 4 / 7 人变好（全段更高、两年都不低 1 个百分点以上、各去最大一笔后仍更高），没有人回撤高 2 个百分点以上，没有人行为差距高 0.02 以上（Kell、Minervini 不适用）。多个通过选变好人数最多的，并列看对数增益中位数。C1 若有通过的候选，C2 仍以登记版本为基线（每轮只验证一个机制）；组合留到落到个人时再定。
