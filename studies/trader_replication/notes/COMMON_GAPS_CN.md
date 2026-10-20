# 七套登记系统的共同缺口（横向诊断，2026-10-20）

不改系统，只诊断。对象是 `systems.py` 登记的 7 套：Martin R74 + S7、Flanders R15 C4 + S4、Clement R15 AA3 + S5、Qullamaggie R11 N3 + S7、Kell R6 A5 + S5、Minervini R0b、Marios R1 L4 + S1 P4。数据 `trader-data-v1`（frozen），只看美股。

## 口径

- 命令：`python -m studies.trader_replication.common funnel`，结果 [`reports/common_funnel.json`](../reports/common_funnel.json)。
- 他的交易：各人台账里有日期（exact / chart）的多头，入场日 2023-02-01 → 2025-12-31，共 212 笔。2023 年计入，否则 Qullamaggie、Marios 几乎没有样本；**2026 年的不看**（验证段要干净）。为此账户从 2023-02-01 起跑，与登记的 2024-01-02 起跑路径不同，只作诊断。
- 每笔取窗口内走得最远的一步：不在面板 → 股票池门槛（该系统自己的价格 / 成交额 / ADR / 50 日线 / 强度名单，按前一日）→ 形态定义（池内但没信号）→ 入场与止损（有信号但被止损宽度或收盘确认挡掉）→ 市况 → 名额与排序（每天名额 / 已持有同票 / 持仓上限）→ 仓位（总敞口、单只上限、现金）→ 买到。
- “漏掉的 R”= 三层对照第二层：他的票、他的日子、我们的执行（收盘买、当日低点止损、该系统自己的离场，每笔单独定仓）。R 对止损宽度很敏感（例如 QBTS 止损 1.2% 时 +191R、CRWV 止损抬到 1% 后 +141R），所以同时给出把每笔截在 [−1.5R, +10R] 的合计。

## 漏斗（笔数 / 第二层 R 合计）

| | 不在面板 | 股票池 | 形态 | 入场止损 | 市况 | 每天名额 | 已持有 | 持仓上限 | 仓位 | 买到 | 合计 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Flanders | 1 | 7 / 18 | 21 / 232 | 2 / 9 | | 7 / 12 | | 4 / 5 | 2 / 0 | 11 | 55 |
| Martin | 1 | 2 / 7 | 5 / −3 | | 3 / 61 | 14 / 257 | 2 / 58 | | | 5 | 32 |
| Clement | 7 | 2 / −2 | 4 / 14 | | | | | | 2 / 1 | 4 | 19 |
| Qullamaggie | 2 | 4 / 96 | 8 / 2 | | 10 / 99 | | | 1 / 0 | 1 / 0 | 4 | 30 |
| Kell | | 17 / 71 | 10 / −6 | | 1 / −1 | | 1 / −1 | | | 6 | 35 |
| Minervini | 4 | 2 / 6 | 14 / 23 | 1 / −1 | | | | | 2 / −1 | 0 | 23 |
| Marios | | 2 / 2 | 3 / 0 | 2 / 5 | | 4 / 7 | | 1 / 1 | | 6 | 18 |

| 环节 | 涉及人数 | 笔数 | 第二层 R 合计 | 截到 [−1.5, 10] |
|---|---|---|---|---|
| 名额与排序（每天名额 + 已持有 + 持仓上限） | 5（主要是 Flanders、Martin、Marios） | 34 | 339 | 103 |
| 形态定义 | 7 | 65 | 262 | 74 |
| 股票池门槛 | 7 | 36 | 198 | 77 |
| 市况 | 3（主要是 Qullamaggie） | 14 | 160 | 27 |
| 入场与止损 | 3 | 5 | 13 | 13 |
| 仓位 | 4 | 7 | 0 | 0 |

## 各环节里是什么

**1. 名额与排序：他的大跳空 EP 日被同一天别的票挤掉。** 34 笔里 25 笔是每天名额。逐日看这些天的入场排序（`trace['filtered']`）：

- 他的票几乎都是当天的放量跳空：Flanders 的 RDDT 10-30、CRNC、LEU、CELH 02-21、INSM、QS、DAVE；Martin 的 GME / AMC 2024-05-13、SMTC、QUBT、LMND；Marios 的 DUOL、WAL、AI、PATH。
- 现有排序（Flanders 综合 RS、Martin 前 20 日成交额、Marios 1 / 3 / 6 月强度）把它们排在第 3 到第 56 位；**按当天量比（当日成交额 / 前 20 日均成交额，收盘时已知）排序，25 笔里 15 笔排进当天名额以内、18 笔进前 3**（名额以内：Flanders 4 / 7、Martin 8 / 14、Marios 3 / 4）。Martin 2025 年 9 月的量子股（IONQ、RGTI、QBTS）量比不突出，这一段不是排序能解决的。
- 原话：Qullamaggie “volume always trumps numbers”、EP “massive volume near the open”；Flanders EP “盘前量巨大，第一根 5 分钟 K 线就看得出巨大买盘”；Martin 每天先看“盘前放量跳空”扫描；Marios 自建“放量”扫描、EP 要放量。Qullamaggie 的系统已经是“当天先 EP”（kind_order），其余人没有。
- 旧记录：Flanders R11 Y2 / Y5（量比排序，但同时改了名额、持仓数和总仓位）因安慰剂或“买到他的”门槛没带入；METHOD 第 9 节记 Martin 早期“按当天涨幅、题材、放量排序”收益大跌。两者都和别的改动捆在一起，不是单独检验。

**2. 形态定义（各人不同，只有一部分共通）。** 65 笔里：底部内的回踩 / VCP / 50 日线反弹（Flanders NVDA 01-05、CELH、RDDT 10-17，Kell 的 20 EMA 支撑、break-and-recapture，Minervini 的大多数）是各人自己的形态，不共通；**EP 的跳空门槛**是共通的一小块：他的 EP 有 8 笔跳空只有 6%–8%（Flanders CAVA、ORCL、PONY；Qullamaggie LI、AI、ABNB；Martin BBAI、RCAT），被“≥ 10%”或“≥ 1 个 ADR”挡掉，第二层合计约 +5R。

**3. 股票池门槛。** 36 笔分三类：

- 价格 / 成交额门槛（5 人 14 笔，第二层合计约 +115R，其中 Qullamaggie ALT 2023-12 一笔 +90R）：Qullamaggie 的 RGTI、ALT、CCCC（< 5 美元；他原话 50 美分的票也做、扫描用 5 日均成交额 ≥ 100 万美元）；Minervini MMYT（1830 万 < 2000 万）、TATT；Martin PL、AMPX（4300 万 < 5000 万）；Clement CRNC、RR；Flanders SGMT、NKTR（EP 池 500 万以下），以及 **CRWV 上市不到 20 天没有 20 日均成交额**。2000 万 / 5 美元是看板的研究者取值；Clement 的 5000 万是他本人 2026 年的宽筛，不算。
- 强度名单（Kell 综合 RS ≥ 90，2024–2025 年挡掉 9 笔：CAVA、STX、ARM、RDDT、TSLA ×2、COIN、SBUX……；2023 年的是 RS 需要一年数据）；Marios 2 笔。
- ADR ≥ 3%（Kell 的 NVDA、MU、CRWD、ZS）；50 日线上方（Flanders 2025-04 暴跌里的 PLTR、HOOD 和 NVDA 2024-05 回踩）。

**4. 收盘买的止损宽度。** 他交易日的“收盘到当日低点”宽度中位数：Marios 1.9 个 ADR、Qullamaggie 1.6、Flanders 1.5、Minervini 1.4、Martin 0.85、Clement 0.84、Kell 0.64；EP 日大多超过 1 个 ADR（Qullamaggie 20 / 23、Marios 11 / 12、Flanders 21 / 34）。它直接挡掉的只有 5 笔（Qullamaggie、Marios 的“宽于 1 ADR 不做”），但对所有人都是定仓问题：固定风险下，宽止损让他最好的那些 EP 只有很小的仓位。处理方式各人不一：Martin 宽了上移到 min(5%, 0.5 ADR)（METHOD 第 9 节：“跳过”会正好跳过他的大日子），Flanders 上移到 6%，Qullamaggie / Marios 跳过，Clement、Kell、Minervini 不封顶。

**5. 市况。** 主要是 Qullamaggie 2023 年 2–8 月的 10 笔 EP（同池指数“绿灯”关着时他照做 EP），Martin 3 笔。只涉及 2 人，暂不做。

## 共同缺口排序与计划

| 排名 | 缺口 | 人数 × 漏掉的 R | 计划 |
|---|---|---|---|
| 1 | 当天排序没按量比，EP 日被挤掉 | 5 人、34 笔、R 339（截后 103） | C1：排序开关（按量比 / EP 先 + 量比 / EP 先 + 原排序） |
| 2 | 收盘买的止损宽度：跳过或不封顶，宽止损让大赢家仓位很小 | 全部 7 人（定仓），直接挡掉 5 笔 | C2：止损宽了上移到上限照做，上限取各人原话 |
| 3 | 看板的价格 / 成交额门槛，以及新股没有 20 日均值 | 5 人、14 笔、R 约 115 | C3：门槛换成各人原话（没有原话的保持） |
| 4 | EP 跳空门槛高于原话的下限 | 3 人、8 笔、R 约 5 | 视 C1–C3 结果再定 |

每轮 ≤ 3 个候选，预登记在 `notes/COMMON_PREREG_C*.md`，结果在 `reports/COMMON_RESULTS_CN.md`；每 3 轮写检查点。
