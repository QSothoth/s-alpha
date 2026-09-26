# 真实0DTE合约身份与覆盖范围

2026-09-26只读审计。只使用本地manifest、cases、保存的chain／合约身份字段及官方接口文档；未调用新的行情接口、历史接口或账户接口，不使用期权价格、收益或事后标签。此文是证据目录，不修改旧Release、custody准入或已登记研究结论。

## 可复用范围与暴露状态

“标的日”指一个 `symbol × trade_date`，双腿不是两个独立日期。每个下表双边标的日均为同一strike的CALL＋PUT；代码中解析的owner、到期日、right、strike与case身份一致。

| 数据及原始路径 | 日期／标的日／腿数 | 身份证据 | 当前研究用途 |
|---|---|---|---|
| [custody-0dte-v5](https://github.com/QSothoth/s-alpha/releases/tag/custody-0dte-v5)，`data/custody-0dte-v5/` | 2026-08-18→09-15，20日／63／126 | 全部case有 `selection=both_sides_atm_at_open`、`session_close`；未保存完整chain或标准乘数快照 | 已暴露开发数据；不是新留出 |
| [custody-0dte-v6.1](https://github.com/QSothoth/s-alpha/releases/tag/custody-0dte-v6.1)，同名data目录 | 2026-08-18→09-16，21日／73／146 | 包含V5的126腿；新增09-16的20腿缺上述selection及session_close | 已暴露；09-16不能追认为同等开盘ATM证据 |
| [custody-eval-2026-09-18-v2](https://github.com/QSothoth/s-alpha/releases/tag/custody-eval-2026-09-18-v2)，同名data目录 | 2026-09-18，1日／14／28 | 全部case有开盘ATM声明及session_close；无完整chain快照 | 原manifest为validation，但已用于旧研究，不能重新封为未见验证 |
| [or-alpha-20260925-v1](https://github.com/QSothoth/s-alpha/releases/tag/or-alpha-20260925-v1)，`data/or-alpha-2026-09-25-holdout-work/` | 2026-09-25，1日／26／52 | 保存26份chain及双腿身份快照；52腿均STANDARD、100股；本次仅审元数据 | 策略收益仍sealed；只有1个日期，不等于26个独立验证日 |
| [or-option-history-pilot-20260918-v1](https://github.com/QSothoth/s-alpha/releases/tag/or-option-history-pilot-20260918-v1)，`data/or-option-history-pilot-20260918-work/` | 09-18已有SPY一对 | 已知真实代码的过期历史可取性试验 | 重复旧样本，不增加日期或未见机会 |

V5＋09-18共 **77标的日、21日期、15标的**，是OR1修正后的旧数据诊断范围。V6.1＋09-18共87标的日、22日期，但多出的10个09-16标的日缺少相同ATM准入证据。此次明确沿用先前更正，不能重新把V6.1全部146腿称为已核实开盘最近ATM。

旧 `custody-train-0dte`（V4，36个单腿case）、旧 `custody-eval-2026-09-16`（10个单腿CALL）有偏置和附件被替换历史，已停用；`custody-eval-2026-09-16-v2` 的20腿已并入V6.1，不能重复计数。详情仍以[数据登记](../../../docs/DATA.md)及[OR1运行前更正](OR1_PREREG.md#运行前数据审计更正同日收益计算前)为准。

## 标的与日期索引

V5的SPY覆盖全部20个日期：08-18、19、20、21、24、25、26、27、28、31；09-01、02、03、04、08、09、10、11、14、15。下表其余日期均在2026年，不意味着缺失日期没有上市0DTE。

| V5标的 | 已冻结日期 |
|---|---|
| AAPL、META、MSFT | 08-21、08-28、09-04、09-11、09-14 |
| AMD、NVDA、TSLA | 08-21、09-11、09-14 |
| AMZN、AVGO | 09-11、09-14 |
| GOOGL | 09-11 |
| MU | 08-21、09-14 |
| IWM | 08-21、09-10、09-11、09-14、09-15 |
| QQQ | 08-21、08-28、09-04、09-10、09-11、09-14、09-15 |

09-16新增10只：AMD、AMZN、AVGO、GOOGL、INTC、META、MSFT、MU、NVDA、TSLA。09-18的14只：AAPL、AMD、AMZN、GOOGL、INTC、IWM、META、MSFT、MU、NVDA、QQQ、SNDK、SPY、TSLA。

09-25 sealed的26只：AAPL、AMD、AMZN、AVGO、DIA、EEM、GLD、GOOGL、INTC、IWM、META、MSFT、MU、NVDA、QQQ、SLV、SMH、SPY、TLT、TSLA、XLE、XLF、XLI、XLU、XLV、XLY。

### 星期不是合约存在性查询

V5原始 `cases.json` 中已有以下真实反例，合约到期日等于交易日：

| 日期／星期 | 标的 | CALL | PUT |
|---|---|---|---|
| 2026-08-18／周二 | SPY | `US.SPY260818C769000` | `US.SPY260818P769000` |
| 2026-09-10／周四 | IWM | `US.IWM260910C288000` | `US.IWM260910P288000` |
| 2026-09-15／周二 | QQQ | `US.QQQ260915C709000` | `US.QQQ260915P709000` |

V5＋09-18按标的日计数为周一14、周二7、周三4、周四6、周五46。此分布只描述已冻结样本，不是逐标的的挂牌频率估计。上述ETF反例也不能反过来证明任意个股在任意周二／周四都有0DTE。

旧归档[RESULTS_CN](../../archive/us_preopen_bias/reports/RESULTS_CN.md)中“选择段147次里只有52%当天有0DTE”的措辞不够严格：对应 `code/s9_describe.py` 只是按weekday计数，并假定个股2026年周一／三／五挂牌，没有逐历史日chain证据。因此 **52%是星期代理比例，不是已核验的0DTE可交易比例**。同样，代码打印 `no 0DTE case frozen` 只表示本地没有冻结case，不能改写成“交易所当日不存在合约”。不能用2026年的挂牌习惯或今天的链倒推2020年。

## 原文件与证据字段

重复利用时先校验Release，不只看manifest的总数。V6.1的 `window.end`、`underlyings` 存在已登记的旧字段未更新问题，实际覆盖以 `cases.json`／`sessions` 为准。以下是本地原文件指纹，未改原数据：

| 目录 | `CHECKSUMS.sha256`文件本身的SHA256 | `cases.json` SHA256 |
|---|---|---|
| custody-0dte-v5 | `35875e44318c78ab5b09cd53cac3b22ce26a8a12cb468aeed5efd72e43e97c69` | `8871b611e28a94ed1b4348031ae720c658b7b50b7c57620448f20a0b10b1fd81` |
| custody-0dte-v6.1 | `38b2d5d8b852deae9bc1aa599b41fb57410274c283834ea86367177960656206` | `c6dee807844a4e35bc066443b051d3d644f87bd70a83600e14478c05ba3ab85f` |
| custody-eval-2026-09-18-v2 | `fba36ab960189e6fe80660629455774627915d1b8982361a324ec203892fc2c0` | `5e341b917c29e646d1686b1ee0a7190f25e742c8e3eb60ffa68751b5a9db838a` |
| or-alpha-2026-09-25-holdout-work | `e729dd3c11f61328e2cf996bd2eb0592baed733ad35a89c75ce20a5a67fbf1af` | `d1b2e1ff40e0140f64c85a74523cd8580d93c2894d1cdb976f4ce2eefd583a1b` |

身份只需要读取以下白名单，不把case中的 `labels` 或行情字段导入身份判断：

- `cases.json`：`symbol, trade_date, contract, expiry, right, direction, strike, selection, reference_open, session_close, call_contract, put_contract`。代码解析结果应与存储字段交叉核对；`reference_open`是标的开盘参照，不是期权价格。
- `manifest.json`：role、来源／采集方法、sessions、selection_policy、请求标的与跳过／错误记录。`role=validation`本身不代表研究上仍未暴露。
- 09-25的 `chain/<SYMBOL>.json`：`symbol, trade_date, observed_at, opening_reference, selected_pair`；chain行的 `code, stock_owner, strike_time, strike_price, option_type, option_standard_type, option_settlement_mode, lot_size, suspension`；选中snapshot的 `option_contract_size, option_valid, sec_status`。不需要bid/ask、最新价或希腊值。
- 每条索引如有需要只记录原文件路径与SHA、证据等级及暴露状态即可，不必建立新通用索引框架，也不得凭代码格式补造未获供应商确认的合约。

### 09-25盘后链的时点限制

manifest记录采集为2026-09-25 22:03:07→22:06:18 ET；例如SPY的chain观察时点为22:03:07.977466 ET。26个文件共5742条chain静态行，52个选中合约均核对到正确owner／expiry／right、`STANDARD`、`lot_size=100`及 `option_contract_size=100`；26个最近strike双边均可由保存chain和opening_reference复算。SPY例为 `US.SPY260925C769000/P769000`。

这证明的是“**盘后接口返回的链，以当日标的开盘价选择最近标准strike**”。盘中可能新挂牌strike、暂停或恢复交易；这里没有09:30独立链快照，所以不能进一步断言09:30时strike全集／状态完全相同，也不独立认证供应商返回已覆盖交易所全部挂牌。盘后snapshot中的 `sec_status=EXPIRED`不等于当日没有此合约，也不是盘中可成交证明；本次只作身份核验。下一轮若需要严格的开盘或信号时点最近ATM，须在相应时点留存真实链及观察时间，不能事后用盘后数据补写成当时已知。

## 代码可靠性与官方API边界

当前研究 [scan.py](../scan.py) 先查当天实际到期日，再检查真实chain；`atm_pair`先选最近标准strike（等距取低），再要求该strike唯一且完整CALL／PUT、未停牌、非AM结算，缺腿不换更远strike。盘中quote检查再要求100股及正常状态。[capture.py](../capture.py)还交叉核对chain的日期／right／strike及snapshot合约股数，不以weekday白名单筛选。

旧 [custody/freeze.py](../../../custody/freeze.py) 的 `_nearest_strike`／`_code_for`没有显式要求STANDARD、100股或唯一双腿，也未保存原始chain；[custody/dataset.py](../../../custody/dataset.py)保证代码解析的到期日等于交易日、owner／方向匹配，但允许selection、session_close缺省。故 `custody check`通过不是全部ATM／标准乘数证据已齐全的证明。本轮只记录，不修custody、不追改旧manifest。

官方证据与推断必须分开：

1. [期权链文档](https://openapi.futunn.com/futu-api-doc/quote/get-option-chain.html)明确不支持已过期链；`start/end`筛的是到期日，不是历史观察时点；30天限制是请求跨度，不是行情保留期。本机SDK `open_quote_context.py:1709`签名同样没有as-of参数。
2. [到期日接口](https://openapi.futunn.com/futu-api-doc/quote/get-option-expiration-date.html)只有标的及指数类型参数，没有历史观察日期。输出允许负到期距离，不构成历史到期日全集可回溯的保证。SDK对应 `open_quote_context.py:3364`。
3. [静态资料接口](https://openapi.futunn.com/futu-api-doc/quote/get-static-info.html)支持已知期权 `code_list`，不支持用 `SecurityType.DRVT`枚举整个市场。已知代码即便能返回expiry／owner／strike，也不能证明当时没有更近的其他strike，更不是完整历史chain。文档也未保证所有已过期代码的长期可用范围；SDK对应 `open_quote_context.py:190`。
4. [已完成pilot](OPTION_HISTORY_PILOT.md)只证明已知SPY 09-18双腿在一周后能取历史分钟，不证明全部过期美股期权、30／60天或更长保留范围，也不生成新的未见验证日。本轮没有新增请求。

以上SDK路径均位于 `/opt/futu-opend/venv/lib/python3.11/site-packages/futu/quote/`，核对版本10.11.7108。未找到Yahoo／腾讯官方公开接口可还原逐历史日完整已过期美股期权链的证据，因此不能把它们写成已实现的补齐途径。

## KNOWN与UNKNOWN不可互换

- `KNOWN_PRESENT`：有真实来源的该日合约身份，且expiry确等于交易日；是否标准、是否最近ATM、是否有可执行盘口分别记录，不能互相替代。
- `KNOWN_ABSENT`：需要当时完整且成功的到期日／链查询及明确范围；不能仅凭一个API失败或本地缺case推断。现存缺样本的大多数历史日期不满足此项证据。
- `UNKNOWN`：没有冻结记录、查询失败、历史接口不支持或证据缺字段。UNKNOWN不是无0DTE，也不是默认有0DTE。

因此2020年以来的日K／早盘信号研究可在正股层做因果评估，但尚不能把所有历史信号声称为当日确有可买末日期权。真实期权映射以以上已冻结身份或今后在正确时点留下的记录为界；不按星期、今日挂牌习惯或近似代码猜测填空。
