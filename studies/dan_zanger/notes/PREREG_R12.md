# Dan Zanger R12 预登记：每日上限与“最强的拿最久”（2026-10-30，跑之前写定）

## R11 照记

- 五个候选都没过“选择段总收益不低于 PAT_EMA10（+67.7%）”，沿用 PAT_EMA10。
- GRP80 −10.0%（75 笔 / 年）、GRP70 −6.5%（91）、GRP70_NOIDX −11.2%（104）、GRP70_EMA21 +27.8%（73）、RS70 +36.5%（94，胜率 31%，平均赚 +8.0% / 亏 −2.5%）。
- 我们这版“最强板块”（OpenD 行业当前快照、成员 RS 中位数排位）不如个股 RS；否定的是这个近似，不是他的原话（缺按当时时点的行业 / 板块指数数据）。
- RS70 只作诊断跑 `success`（未带入）：过 1、2（93 笔 / 年，差 11%）、3（四项全在范围内）、5（全段 +16% vs −8%）；不过 6（2026 −15%）、7（去掉最好两笔 −17% vs −8%）。放宽选股带来的笔数靠更弱的票，赢家变小、收益更集中。

## 本轮（看过 R11 后挑的）

- 基础与参照：r10.json PAT_EMA10。lost.py 诊断：选择段每年约 12 个候选因“每天最多 2 只新开仓”丢掉、约 5 个因 4 个名额满；`max_new = 2` 是沿用 Flanders 的默认，不是他的原话。
- 候选（≤ 5）：
  - NOCAP：去掉每日新开仓上限（`max_new = 0`）；“When the explosion of volume comes … I will add to, or initiate, a position”，没有每日只数的说法
  - HOLDSTRONG：+15% 卖 25% 之后，剩余仓位改跟 21 EMA（“Hold your strongest stocks the longest”；R8 的 SPLIT 是另一方向：先 10 EMA 后 50 日线）
  - NOCAP_HOLDSTRONG：两者同时（笔数与赢家持有成对改）
  - RS70_HOLDSTRONG：RS ≥ 70 + HOLDSTRONG（看过 R11 RS70 后定：笔数够但赢家小，试让强者拿久）
- 门槛（不改）：同池随机中位、胜率 ≤ 35%、选择段总收益不低于 PAT_EMA10。
- 选择：过门槛者中每年笔数最多；都不过沿用 PAT_EMA10。带入者跑 `success`。
