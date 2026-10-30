# Dan Zanger R4 预登记：入场、止损、形态（2026-10-29，跑之前写定）

- 基础：R3 带入的 ADD2。选择段 2024–2025；2026 只作“已用”参考。
- **目标改动（看过 R1–R3 后改，照记）**：R1–R3 所有候选 2025 年都亏，按总收益选会被 2024 带偏（METHOD 第 9 节 Martin R31–R40 的教训）。从本轮起目标改为选择段两年里较差的一年（`min_year`），门槛不变（高于同池随机中位、胜率 ≤ 35%）。
- 方向取自以前其他交易员的优化，每个都对得上他的原话（≤ 5，各改一处）：
  - STOPLOW：止损放在入场当天低点、最宽 5%（老版规则“约 1 美元、最多 2 美元”；EXEC X1 / COMMON C2 发现收盘买 + 当天低点窄止损是登记系统的主要优势来源）
  - EP：加财报跳空形态：开盘高于前收 ≥ 10%、全天成交额 ≥ 20 日均值 3 倍，收盘买、止损当天低点（“Looks for gap-ups on earnings”；Flanders / Qullamaggie / Marios 的 EP；10% 沿用 Flanders 的值，没有财报日期，跳空不一定是财报）
  - ADR3：股票池加 ADR ≥ 3%（“biggest movers”；Clement +ADR 修复）
  - IDX50：同池等权指数前一日收在 EMA50 上方才开新仓（他“趋势破了就转现金”；各人的 IDX 开关）
  - ADDSIG：持仓再次出现买点（新的放量突破）时，若收盘高于成本，加原仓位一半（“When the explosion of volume comes and the stock crosses the breakout point, I will add to, or initiate”；Flanders H 轮的新买点加仓）
- 选择：过门槛者中 `min_year` 最高；不如 ADD2 就沿用。
