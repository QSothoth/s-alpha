# 研究测试集与暴露记录（2026-09-28 本机核对）

本清单区分「文件里有哪些标的」「满足入池条件的标的」和「某规则最后选出的信号」。用于判断能否再作新验证，不改变原预登记、原报告或 custody 的数据角色。只读本机数据，没有新增行情请求，也没有重新计算策略结果。

机器清单：[test_sets_inventory.json](test_sets_inventory.json)，SHA256 `418646c358fb7ddec307f905f1fe9ca9c9cadc631efcdb1c2788a1e447371cb3`。包含：900 只排名名单及来源哈希；各包 CHECKSUMS 哈希、逐文件校验数量与实有日期范围；168 个主要分钟文件各自的 SHA256、行数与窗口；P3/P4 逐只入池数量；全仓库已有分钟文件的代码／目录；P5 可行性筛选的逐只元数据。路径均相对仓库根目录。

2026-09-28 已逐一核验下列 20 个目录的 **8,910 个 CHECKSUMS 成员，全部一致**。哈希按 1 MiB 分块读取，CSV 只流式统计日期范围；入池核对每次只保留一只股票的分钟数据，跳过 `first_touch`，没有重跑验证收益。日线、期权事件等非分钟表的逐文件哈希保留在被固定哈希的原 `CHECKSUMS.sha256` 中。文件时间窗是原始覆盖范围，不能当成所有标的都有全窗数据或允许重新使用留出段的声明。

## P1：23 只的出单时点研究

- 个股 11 只：AAPL、MSFT、NVDA、TSLA、META、AMZN、GOOGL、AMD、MU、INTC、AVGO。
- ETF 12 只：SPY、QQQ、IWM、DIA、EEM、GLD、SLV、SMH、TLT、XLE、XLF、XLU。P1 历史问题允许 ETF，当前日常个股名单不允许 ETF。
- 核心 14 只的 5m：`data/preopen-us-k5-select-v1/k5/<SYM>.csv` 与 `data/preopen-us-k5-valid-v1/k5/<SYM>.csv`；另外 9 只 ETF：`data/or-context-etf-k5-2018-2026-retry1-work/US.<SYM>.csv`。IV 取 `preopen-s23-select-v1/iv` 与 `preopen-s23-valid-v1/iv`。
- 选择窗 2023-06-26 → 2024-05-31；原验证窗 2024-06-03 → 2026-09-24。两段均已用，不能再作为新的干净验证。核心分钟数据还用于旧 S11–S20、S28/S29、OR/DS 研究；ETF 的这段在 P1 后也已暴露。
- ETF 原文件还含 2018 年起的数据和 2026-09-25；本次仅核验字节与时间范围，不评测那些未用窗口，其他研究保留的边界照旧。XLI、XLV、XLY 不在 P1 池内，曾用于 RG1，仍须纳入全仓库暴露核对。
- P1 真实跨式描述使用 `data/custody-0dte-v5`（2026-08-18 → 09-15）与 `data/custody-eval-2026-09-18-v2`（09-18）的 `cases.json`、`option/` 和 `underlying/`。两包代码并集：AAPL、AMD、AMZN、AVGO、GOOGL、INTC、IWM、META、MSFT、MU、NVDA、QQQ、SNDK、SPY、TSLA；P1 再按上述 23 只池子过滤，因此 SNDK 不进跨式统计。只能作已暴露的描述性对照；不改变 custody 原训练／验证隔离要求。

## P3/P4 选择段：48 个输入代码，44 个实际入池

`p3.universe('select', 'a')` 是 **13 + 35 = 48** 个互不重复代码，不是 44 个输入文件：

| 来源 | 代码 |
|---|---|
| 核心 13 只 | AAPL、MSFT、NVDA、TSLA、META、AMZN、GOOGL、AMD、MU、INTC、AVGO、SNDK、SKHY |
| S20 的 35 只 | AA、AAOI、ABVX、ACAD、AG、ALB、APLD、AVTX、CDE、CLF、CRML、FSLY、HIMS、HL、IBRX、IONQ、IOVA、IREN、KGC、KOD、LQDA、MP、QBTS、RARE、RGTI、RIOT、SLS、SMCI、SVRA、TTD、U、UEC、USAR、UUUU、VKTX |

- 核心路径：`data/preopen-us-k5-select-v1/k5/<SYM>.csv` 加 `data/preopen-us-k5-valid-v1/k5/<SYM>.csv`；S20 路径：`data/preopen-s20-select-v1/k5/<SYM>.csv` 加 `data/preopen-s20-valid-v1/k5/<SYM>.csv`。
- 两组原始完整旧窗分别为 2020-01-02 → 2024-05-31 和 2024-06-03 → 2026-09-24；新上市股票更短。SNDK 只有 valid 文件，始于 2025-02-13；SKHY 只有 valid 文件，始于 2026-07-10。
- **ACAD、AVTX、KOD、SVRA 被剔除**：2026-09-26 到期快照不满足周度周五／周一三的到期门槛，因此四只均为 0 个入池标的日。48 − 4 = **44**；不是数据丢了，也不是另外四只验证股。
- 逐只入池核对与原报告一致：P3a/P4 选择 **9,199 个标的日、44 只**；P3b **2,991 个标的日、44 只**。这是符合基础池子门槛的标的日，不是 A4 信号数。
- P3a/P4 预登记选择窗截至 2026-09-24；代码及 P3 JSON 形式上写到 09-25，源 5m 实际只到 09-24，因此没有额外的 09-25 选择数据。P3b 起于 2025-09-29，其余相同。真实有效日期按星期／到期过滤后更短，逐只见机器清单 `membership.select`。
- **TEM 不在这 48 只里**：S20 select 没有 TEM 文件，valid 有（2024-06-14 起）；P3 按 select 目录文件名枚举 S20，故没读入 TEM。但 TEM 早前已有分钟数据，下一轮不能把它当「从未用过分钟数据」的新股票。
- 这些分钟数据曾用于 S11–S20、S28/S29、OR1–OR4、DS1/DS2；随后 P3a、P3b、P4 又用于选择。**只能选择／诊断，不能恢复为新验证。** 四个旧 k5/S20 Release 已撤下，当前复现依赖本机副本；不能宣称远端仍可下载。

## P4 验证段：35 只，已经使用一次

名单由 [p3_validation_names.json](p3_validation_names.json) 固定：ORCL、MSTR、SOFI、PLTR、GME、CRWV、NBIS、NFLX、HOOD、RKLB、MRNA、NKE、ARM、BE、WBD、BB、PFE、MARA、F、ONDS、BAC、NVO、COIN、BMNR、WMT、DELL、WULF、PCG、MRVL、BA、EOSE、RIVN、APO、ASTS、NOK。

分钟文件：`data/p3-k5-validation-raw/k5/<SYM>.csv`，QFQ、常规时段 5m；原始总体窗 2023-05-01 → 2026-09-25，评测窗 2023-06-26 → 2026-09-25。CRWV 始于 2025-03-28、NBIS 始于 2024-10-21、ARM 始于 2023-09-14、BMNR 始于 2023-10-16；其余 31 只文件从 2023-05-01 起，均截至 2026-09-25。每个文件的完整时标、SHA256 与行数见机器清单。

这 35 只在 P3 原门槛下没有开启策略验证（P3a/P3b 全部失败），但后来 **P4 已一次性评测 A1/A4**，不能再当新留出。基础池子 **5,009 个标的日、35 只**；A4 最终信号是 **44 个标的日**，这里的 44 和上一节的「44 只选择股」无关。验证股日线更早用于 S24–S26/P2，且与选择段共享市场日期；它原来是分钟截面验证，并非全信息、全时间都独立的验证。

| 个股 | 有效入池标的日 | 实际入池首日 |
|---|---:|---|
| ORCL | 159 | 2023-06-30 |
| MSTR | 159 | 2023-06-30 |
| SOFI | 159 | 2023-06-30 |
| PLTR | 159 | 2023-06-30 |
| GME | 159 | 2023-06-30 |
| CRWV | 67 | 2025-05-09 |
| NBIS | 88 | 2024-12-06 |
| NFLX | 159 | 2023-06-30 |
| HOOD | 159 | 2023-06-30 |
| RKLB | 158 | 2023-06-30 |
| MRNA | 159 | 2023-06-30 |
| NKE | 159 | 2023-06-30 |
| ARM | 143 | 2023-10-20 |
| BE | 154 | 2023-06-30 |
| WBD | 159 | 2023-06-30 |
| BB | 117 | 2023-06-30 |
| PFE | 159 | 2023-06-30 |
| MARA | 159 | 2023-06-30 |
| F | 159 | 2023-06-30 |
| ONDS | 55 | 2025-08-08 |
| BAC | 159 | 2023-06-30 |
| NVO | 159 | 2023-06-30 |
| COIN | 159 | 2023-06-30 |
| BMNR | 57 | 2025-07-25 |
| WMT | 159 | 2023-06-30 |
| DELL | 159 | 2023-06-30 |
| WULF | 112 | 2023-07-14 |
| PCG | 159 | 2023-06-30 |
| MRVL | 159 | 2023-06-30 |
| BA | 159 | 2023-06-30 |
| EOSE | 98 | 2023-06-30 |
| RIVN | 159 | 2023-06-30 |
| APO | 159 | 2023-06-30 |
| ASTS | 146 | 2023-06-30 |
| NOK | 157 | 2023-06-30 |

所有上述入池末日均为 2026-09-25。计数仅为审计基础资格，不重新判定 P4 成败。

## P2：900 只日线与公共辅助表

900 只名单完整列在三个来源 JSON 及机器清单 `universes` 中，不用「有几百只」代替具体代码。每组排名都是固定 2026-09-24 排名，不是历史逐日排名，实际每日入池还受数据／成交额／期权量／到期门槛影响。

| 样本 | 个股名单 | 路径、评测窗 | 已用轮次；能否新验证 |
|---|---|---|---|
| 排名 1–300 选择 | [universe_stocks300.json](../../archive/us_preopen_bias/notes/universe_stocks300.json) | `data/preopen-s24-select-v1`；2023-06-26 → 2024-12-31 | S24–S26 选择、P2 选择；否 |
| 排名 1–300 后段 | 同上 | `data/preopen-s24-valid-v1`；2025-01-02 → 2026-09-24（热身接 select） | S26 验证已用、P2 描述；否 |
| 排名 301–600 | [universe_stocks301_600.json](../../archive/us_preopen_bias/notes/universe_stocks301_600.json) | `data/preopen-s27-holdout-v1`；2023-06-26 → 2026-09-24 | S27 验证已用、P2 描述；否 |
| 排名 601–900 | [universe_stocks601_900.json](universe_stocks601_900.json) | `data/p2-601-900-raw`；2023-06-26 → 2026-09-25 | P2/P2 补登验证已用；否 |

每个目录按 `daily/<SYM>.csv`、`daily_none/<SYM>.csv`、`iv/<SYM>.csv`、`option_stats/<SYM>.csv` 存表；日线不是分钟聚合。源日线多数始于 2022 年 9 月，少数不同；上表是评测窗，逐表实有范围见机器清单。排名股 BRK.B 的历史文件存在代码映射／缺失问题，不能仅按「300 只」假定每只可用。

P3/P4 辅助表由 `p3.SIDE_DIRS` 顺序合并，同日期先读值优先：s24 select、s24 valid、s27、s23 select、s23 valid、s21 select、s21 valid、s20 select、s20 valid、p2 601–900。它们提供不复权收盘、期权量、IV；P3/P4 的信号日线本身来自 5m 聚合。S21 的 34 只主题股用于 S21/S22；S23 的 114 只股票／ETF 在 S23 使用选择部分，部分 valid IV 随后被 P1/P3/P4 使用，因此不能笼统称整包所有字段都仍未暴露，也不能据此宣称未读取的其他字段已正式验证。

| 公共数据 | 名单与覆盖 | 使用情况 |
|---|---|---|
| `data/p2-rank-20260924-raw` | 31 页原始排名＋ETF 表；重建 900 只，排名日期 2026-09-24 | 名单定义；不是行情验证样本 |
| `data/p2-events-raw/earnings`、`expiry` | 900 只；财报 16 期，到期日为 2026-09-26 当前快照 | P2/P3/P4 的事件／资格；当前快照不能证明历史逐日有 0DTE |
| `data/p3-option-events-raw/<SYM>.json` | 505 只周度／周一三到期股；文件原始时间最早 2025-09-26，研究统一从 2025-09-29 起 | P3b 选择时只结合旧 44 只分钟池评测；其余原始事件已采集，不因此变成新分钟验证。逐代码为目录 JSON 与固定 CHECKSUMS |
| `data/p5-parity-raw` | ORCL、PLTR、SOFI、NFLX、COIN、F、PFE、RKLB、WMT、MARA；每只 `K_5M.json` / `K_30M.json` 各 1000 根 | 仅跨周期口径核对，均属已经暴露的 P4 股；不是 P5 验证 |

parity 的 30m 原始窗为 2026-06-08 10:30 → 2026-09-25 16:00（首日不完整），5m 为 2026-09-09 10:45 → 2026-09-25 16:00。完整天必须再按交易时标筛选，不把不足一天的数据补齐。跨周期比较结果与采纳的近似边界见本切片的分母口径说明。

## 全仓库分钟暴露与 P5 可行性

截至本次盘点，扫描 `data/` 中美股 `k5`、`k1`、`ext30`、`underlying` 及 OR ETF 原文件，合计 **99 个代码：84 只个股＋15 只 ETF**。个股正好是上文 48 个选择输入＋35 个 P4 股＋TEM；ETF 是 P1 的 12 只再加 XLI、XLV、XLY。每个代码对应的本机目录在 `existing_minute_files_by_symbol`。这里把盘前盘后 30m、custody 正股 1m、未参与 P3 的 TEM 都纳入排除，不能只减掉报告中的 44＋35。

这是以现存文件和已登记历史为依据的保守排除清单，不声称扫描本机即可证明任何已删除、未登记外部数据从未使用。OR 09/25 等另有留出约束的文件只核对存在性，不打开其行情结果。具体日期边界仍遵守对应研究登记。

以下只做已有日线／元数据的选样可行性核对，**不是 P5 预登记或验证结果，不读取新分钟收益**：

1. 900 只排名里，排除上述全部分钟代码，按既有到期快照要求 2026-10-02、10-09 两个周五都有到期，剩 **425 只**。
2. 排除 GOOG（与已用 GOOGL 同公司另一股类）、SPCX、B（旧数据质量排除）；再要求 2026-03-01 → 05-31 至少 40 个有效日线观测，剩 **419 只**。BRK.B 缺匹配日线，CBRS 仅 10 日，XE 仅 24 日；SPCX 也无可用日线。股票排名和历史数据存在幸存者／时点限制，保持披露。
3. 每日真实波幅 `max(H, Cprev) − min(L, Cprev)` 除以当日收盘，对上述窗口取算术均值；419 只的中位数为 **4.6356958063%**，大于等于中位数者 **210 只**。窗口截止 05-31，早于现有 30m 首个完整日 06-09；交接草案的「3–6 月」会与 30m 样本早期重叠，不能照搬。
4. 已存期权异动的 `industry_plate_list` 可以提取行业**代码**：210 只中 **155 只有单一非空代码、55 只缺失，无多代码冲突**；155 只涉及 55 个细行业。现有代码全取、每行业最多 10 只，按固定期权排名裁剪，可留 **140 只**。逐只值及缺行业名单在机器清单 `p5_feasibility_only`；这是调查产物，不是正式锁定样本。
5. 本机没有完整官方行业名称／层级字典，期权异动元数据不能代替完整行业快照。下一步可在预登记允许的元数据阶段一次性补候选 owner plate，保留缺失处理和排序规则。细行业限 10 只仍可能集中于广义科技、成长股；须另外报告行业／市值档／月份分布，不能把 55 个板块代码直接当作充分分散的证明。

这 419/210 只已用过日线研究；可争取的是新个股的分钟路径检验，不是完全未见过的公司或独立时间样本。是否进入 P5、最终选股算法和行业补全规则以随后冻结的预登记为准。不得因为后续信号太少更改此筛选、窗口或凑数。

## 本机校验和索引

下表哈希均指目录内 **`CHECKSUMS.sha256` 文件自身的 SHA256**，不是 ZIP 哈希。逐文件复核可在对应目录执行 `sha256sum -c CHECKSUMS.sha256`。本机 raw 包尚未发布 Release；旧已发布或撤回状态以 [docs/DATA.md](../../../docs/DATA.md) 为准。

| 本机目录（均在 `data/`） | 成员核验数 | CHECKSUMS SHA256 |
|---|---:|---|
| `preopen-us-k5-select-v1` | 15 | `5531f0ccff46be6135b9c87457bebf79fd2ad1703182918ea2dbcb784bc6468d` |
| `preopen-us-k5-valid-v1` | 17 | `992ad5f444b9eb36de05a15cd882e28e68466eca1769f5917e9704e673f73da0` |
| `preopen-s20-select-v1` | 131 | `9a310566039ff271c56312f5772a90ab7f2d243b1326024d131c9bc932c21c21` |
| `preopen-s20-valid-v1` | 109 | `4f54cc3f4a6b880b04aa366f4ef50c4b8b64b3ede118cb6865dc984a10eea5a4` |
| `or-context-etf-k5-2018-2026-retry1-work` | 25 | `5ac28d322f91c5877349a2d1021bfabecce98c74e09f83cb45192d1f35cc66ee` |
| `preopen-s23-select-v1` | 419 | `49fb68958ce4bd72d025dd624308c9ac62ddb4435d215d80877ff84c1a59098c` |
| `preopen-s23-valid-v1` | 457 | `397771322a5b3c2d901b3c2313d4165e86548cd5e7e4f2132cb971672fb263cd` |
| `preopen-s21-select-v1` | 203 | `9fd9ece38757cfe115512b7c94d78ee7da2930ef3cdbf1448072484587e7f1a0` |
| `preopen-s21-valid-v1` | 244 | `42b8a0b53c69cac1152696de25e61660ff79f036b4e1534b343ec2b88c55e677` |
| `preopen-s24-select-v1` | 1105 | `79a7a4830c9aa924ac7dacb4ce39b2a2461eeda1e70c2bb0271c00716ef9b2bf` |
| `preopen-s24-valid-v1` | 1201 | `1ee2292985bce9d407203d151126b0015c38dc0c380fd57666224670897191c3` |
| `preopen-s27-holdout-v1` | 1201 | `4cfaa0ca3f19599a8eb08e34e5ddb80a9d20de72989b6e8dc382eed97ee4e4f6` |
| `p2-601-900-raw` | 1201 | `a213d60bce299fb2366cb2fde93adb2e9d6a06a3240238f313b88a551a0b6e87` |
| `p2-events-raw` | 1802 | `b3fefef0e1e28c3cbdf745fc258f887ee0c70573ff8d433bd3546eebda459869` |
| `p2-rank-20260924-raw` | 32 | `5f0f839377f20b14106e2ca06b78ef174bb06897664be7b1bace7ce65b724777` |
| `p3-option-events-raw` | 506 | `829e7d1affc0ae2f2bac569246b646b9eff6321afc0e06ac8550a85347f8dd59` |
| `p3-k5-validation-raw` | 36 | `dd2eba4e353aba90d7e52877f3b9016cf36a228c02198de8c39e7dc1ccc2f506` |
| `p5-parity-raw` | 20 | `1981ad1a712f73e702cd32a9543e0fdf6f9a0ef547daaf84678de15656e843f6` |
| `custody-0dte-v5` | 141 | `35875e44318c78ab5b09cd53cac3b22ce26a8a12cb468aeed5efd72e43e97c69` |
| `custody-eval-2026-09-18-v2` | 45 | `fba36ab960189e6fe80660629455774627915d1b8982361a324ec203892fc2c0` |

登记依据：[P1](P1_PREREG.md)、[P2](P2_PREREG.md)、[P2 补登](P2_ADDENDUM.md)、[P3](P3_PREREG.md)、[P4](P4_PREREG.md)，以及 [p3.py](../p3.py)、[p4.py](../p4.py)、[timing.py](../timing.py)、[daily_k.py](../daily_k.py) 的实际读数路径与已保存报告。文中“已用”是研究暴露事实，不把不同粒度／不同目标的复用包装成新独立验证。


## P5 冻结新截面（本次续接）

预登记 [P5_PREREG.md](P5_PREREG.md) 的 SHA256 为 `99d4f1ec0523be9c7f7510460dd2a50cf0522a4aec471c42a0c04489bf815ea3`。原 inventory 保持字节不变，是取数前暴露快照。

本轮名单按登记算法冻结为 145 只、53 个 OpenD 细行业，完整代码与行业名在 `data/p5-k30-validation-raw/selection.json`，SHA256 `f9edf0a335a49240b5001fbf088bba0198abc3e8cc753182082940dadfedff67`。行业元数据两批均查询成功；210 活跃候选中 47 只没有 INDUSTRY 分类、18 只超过每行业 10 只上限；没有替补。名单写盘并验签后才请求分钟数据。

这 145 只都具备保存快照里的周度资格，但没有周一／三到期资格，因此本轮实际 0DTE 子集只涉及周五。分钟输入为每股 1000 根原生 RTH 30 分钟 K、76 个完整日，评测截止 2026-09-25；完整日与热身规则见预登记。原始 CHECKSUMS 文件 SHA256 为 `f5f8541994749f63708e000e2d0eb941bb2d624c0ad8f3649c6c04be81ba7f0b`，全部 158 个成员核验通过。

**P5 已完成唯一评测且失败，此样本不能再当新验证。** 基础池 7,081 个标的日，40 次信号目标率 7.5%、平均收益 −0.251 σ_rem；实际周五子集 11 次，目标先到 0 次。完整记录见 [P5_RESULTS_CN.md](../reports/P5_RESULTS_CN.md) 与机器报告；行业、市值分档、每日母池、逐股排除原因及全部 40 个信号均保存。
