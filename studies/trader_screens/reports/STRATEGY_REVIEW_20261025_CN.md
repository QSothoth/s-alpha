# 交易员看板策略审查：方法论、执行与证据（2026-10-25）

> 2026-10-25 已按本文逐项修复，修复内容、修复前后对比见 [STRATEGY_REVIEW_20261025_FIXES_CN.md](STRATEGY_REVIEW_20261025_FIXES_CN.md)。本文和三个 characterization 脚本记录的是修复前 `7f943e7` 的行为：在修复后的代码上，断言“缺陷存在”的用例按预期会失败；修复后的回归测试在各目录 `tests/test_review_fixes.py`。

审查版本：`7f943e7c67c73d305bd5d3ba03f65fc71291fd95`。覆盖 `systems.all_()` 当前登记的七套策略，以及它们共用的数据、账户引擎、随机对照、研究诊断和看板。本文行号均对应这个提交，后续修改请以提交版本定位。

**结论：目前有足以影响研究解释和看板操作含义的问题。优先级最高的是盘中空单的账户时序、随机对照的执行时点与股票池、三层对照的执行不一致。现有收益不能据此全部否定，也不能继续只凭“门禁通过、与旧表一致”证明策略复刻和执行正确。**

这次只审查并保存证据，没有修改策略、参数、历史结论或行情文件，没有下单、拉取行情、启动采集，也没有重跑全市场收益或调参。新增脚本中的合成数据仅是软件行为单元夹具；真实数据核查只读取已有冻结美股数据，统计候选，不评价新策略。

## 1. 如何读这份审查

证据按三种强度区分：**机制已复现**指极小输入能够稳定触发；**真实数据已计数**指在指定冻结数据上观察到相应候选或已有报告行；**资格或契约问题**指实现、说明、原话或实验设计不同，不自动等于运行错误。P1 表示会改变账户行为、对照解释或操作含义，建议优先处理；P2 表示数据边界、展示、追溯或证据资格缺口。优先级不是收益影响大小的测量结果。

| 编号 | 主要问题 | 性质 / 优先级 | 证据入口 |
|---|---|---|---|
| R01 | 盘中空单使用当天收盘后的净值和名额 | 机制已复现，P1 | `repro` 的两项开盘空单用例 |
| R02 | 随机空单被改成收盘入场，首日止损也被清除 | 机制已复现，P1 | `repro` 单股票对照；源码 |
| R03 | 配置池、真实通道池、随机池不一致 | 真实候选已计数，P1 | `real` 三个系统 |
| R04 | 延伸减仓每日重复，不能保证保留跟踪余仓 | 策略接线与说明冲突，P1 | `repro` 当前 Clement / Kell 配置 |
| R05 | 开盘已触发保本，之后穿过保本价仍持仓 | 机制已复现，P1 | `boundaries.breakeven_after_open_already_above_trigger` |
| R06 | A 股标为“涨停跳过”，模拟账户却仍持有 | 机制已复现，P1 | `repro` 经 runner 与 scan 的用例 |
| R07 | 行情日期、年龄及重叠核验存在放行路径 | 边界已复现，P2；正式数据写入应优先修 | `boundaries` 三个数据用例 |
| R08 | 单股缺价导致持仓与总敞口 NaN | 机制已复现，P2 | `boundaries.missing_latest_holding` |
| R09 | 尾盘表混合全天事件，明日计划漏管理条件 | 源码与渲染证据，P1 / P2 | runner、board、持仓输出 |
| R10 | 旧代码参考与缺失核对仍可显示“全部一致” | 元数据与渲染已复现，P2 | `boundaries.reference_*` |
| R11 | 空头隐式继承多头分批 / 保本 | 配置已复现，P2 | `boundaries.short_inheritance` |
| R12 | 多日交集丢弃交易日期 | 契约与追溯问题，P2 | `boundaries.overlap_between_different_days` |
| M01 | 三层对照第二层漏掉实际止损上限 | 机制与已有报告已证实，P1 | `boundaries.second_layer_stop`；既有漏斗 |
| M02 | ADR、ATR 与止损 R 的替换未保持规则保真 | 原话资料与实现对照，P1 / 研究代理 | 个人 RULES、配置和引擎 |
| M03 | 验证数据使用历史、forward 的资格需重新标注 | Git 历史与元数据，P2 | 四个历史提交；freeze 定义 |
| M04 | 行为覆盖、指标及固定名单限制收益外推 | 已披露研究边界 | 既有比对表、协议与门禁 |

证据文件均与本文同目录：[`strategy_review_20261025_evidence.json`](strategy_review_20261025_evidence.json) 保存输出、配置、摘要和测试结果；[`repro`](strategy_review_20261025_repro.py) 是五项行为复现；[`boundaries`](strategy_review_20261025_boundaries.py) 是数据、显示、保本、继承和分层执行夹具；[`real`](strategy_review_20261025_real.py) 是冻结美股候选核查。下文简写沿用这些名字。

## 2. 系统实际上怎样运行

七位交易员共用账户引擎。注册统一解决“运行哪个研究模块和配置”，不自动保证规则忠于原话、拥有独立验证资格或现实可成交。

```mermaid
flowchart LR
    A[冻结数据或 live 增量] --> B[共享面板与特征]
    C[systems 登记配置] --> D[各人 Study 和 LongShort]
    B --> D
    D --> E[候选 entries 与 Rules]
    D --> F[随机股票池]
    E --> G[统一 simulate 账户]
    F --> H[随机替换 entries]
    H --> G
    G --> I[compare 研究报表]
    G --> J[runner 近期交易与持仓]
    J --> K[scan 交集与 board 展示]
    I --> J
```

必须分开四个概念：**资格池**是哪些股票可考虑；**形态 mask**是何时满足形态；**entries**是带价格、止损和优先级的候选；**Rules**结合账户状态决定真正成交。候选数不等于成交数。`build()` 返回的随机池另行计算，不天然等于所有通道可交易总体。

每次看板从 2024-01-02 回放到最新日，`runner` 从执行记录提取近 N 日买卖，从 `why=end` 的期末未平状态生成持仓。它不是从昨日已保存的实盘账户接着撮合。研究和看板共用实现是优点，也意味着同一错误会同时进入两端，互相一致不能独立证明正确。

| 位置 | 职责与本次重点 |
|---|---|
| [`trader_data`](../../trader_data/README.md) | 冻结 / live、公司行动、前复权面板与覆盖校验 |
| [`systems.py`](../../trader_replication/systems.py)，L18–38、99–164 | 版本、配置加载、状态和手写规则卡 |
| 各人 `replicate.py`、[`screens.py`](../screens.py) | 个人通道；部分初版 Screen 仍被当前研究调用 |
| [`shorts.py`](../../trader_replication/shorts.py)，L125–155、215–276 | 日 K 空头成交代理、规则继承、多空组合 |
| [`system.py`](../../trader_replication/system.py)，L133–530 | 现金、名额、仓位、止损、分批、随机替换 |
| [`study.py`](../../trader_replication/study.py)、[`common.py`](../../trader_replication/common.py) | 轮次选择、本人台账和三层诊断 |
| [`gate.py`](../../trader_replication/gate.py)、[`compare.py`](../../trader_replication/compare.py) | 工程检查、比对指标和源码指纹 |
| [`runner.py`](../../trader_replication/runner.py)、[`scan.py`](../scan.py)、[`board.py`](../board.py) | 回放结果、交集、持仓计划与展示 |

## 3. 技术实现与策略接线

### R01 · 盘中空单读取收盘后的账户状态（P1）

**证据链。** [`shorts.level_entries`](../../trader_replication/shorts.py) L125–155 为开盘或预先已知限价生成空单；[`system.simulate`](../../trader_replication/system.py) L385–468 却先处理已有仓位整天的止损、收盘跟踪与时间退出，L469 计算 `cash + value(d)`，L484–500 才处理这些新单。`open_pos` L246 检查此时的名额，L272–278 用当天估值计算毛敞口、仓位和股数。

**复现。** `repro.test_open_short_size_reads_later_close_of_existing_position` 保持开盘时可知信息相同，只把已有多头当天收盘由 100 改成 200，盘初空单股数从 **0.1 变成 0.12**。另一用例设 `max_open=1`，已有多头直到收盘才按时间退出，但当天盘初空单仍获准使用这个名额。

**影响。** 当前美股 Martin S7、Flanders S4、Clement S5、Qullamaggie S7、Kell S5 的盘初 / 触线空头。Marios 当前空头是收盘型，Mark 无空头，不直接套用本项。仓位大小、能否成交、随后反馈和净值均可能受影响，方向与总幅度尚未测量。

**反证与边界。** 收盘确认多头按收盘净值开仓是既有模型；问题是把更早发生的空单放进相同批次。截断面板的未来检查比较跨日输入，不能发现同一天内的账户状态偷看，协议也承认局部时点需单测。

**修复验收。** 为成交明确开盘、触线、收盘时点，按当时已有现金、持仓和已发生事件分配资源。修改当天尚未来到的收盘价，不应改变盘初订单的股数或准入；不能只改信号 mask。

### R02 · 安慰剂同时改变了空头执行（P1）

**证据链。** [`system.py`](../../trader_replication/system.py) L471–482 随机换股时强制使用替换股票当日 `close`，按原百分比重建止损，并把第七字段 `day_exit` 设为 `None`。真实开盘 / 限价空单可能在日内成交并当日止损，L508–509 会执行该字段。

**复现。** `repro.test_same_name_placebo_changes_short_fill_time` 的股票池只有一只股票，已排除换股差异。真实空单开盘 10 卖出，当天收盘 8，期末净值 **1.01**；随机对照在同一只股票收盘 8 才入场，净值 **1.00**。源码还直接证明首日止损字段被删除。

**影响。** R01 中五位美股空头的随机排位不再单独衡量选股贡献。S v2 在 [`shorts.py`](../../trader_replication/shorts.py) L403–409、433–435 把此排位用于 Alpha 门槛。旧比对中的 Martin 0.93、Flanders 1.00、Clement 0.94、Qullamaggie 1.00、Kell 0.98 是旧实现的经验排位，不能预测修正后一定通过或失败。Marios 收盘空头不直接受此入场时点差异影响。

**反证与边界。** 引擎 docstring 明写随机对照按收盘成交。它可以是一种另行命名的基准，但当前“同池随机入场的选股 Alpha”解释混合了执行差异。100 次随机排位也不是经多轮选参校正的 p 值。

**修复验收。** 同一股票、同一信号的恒等对照必须保持执行时点和首日风险；限价未触发的处理需预先定义。复核旧候选应保留旧结果，不借机调参，也不把旧数据复测称为新独立验证。

### R03 · 三套策略的池定义存在实质错配（P1）

共同根源在 [`Flanders.build`](../../christian_flanders/replicate.py) L254–279：每个 setup 自带池，`cfg.pool` 不统一相交到所有 mask；随机池则由另算的 `pool | ep_pool` 派生。**不能直接把缺少统一相交判错**，不同通道允许不同池；问题是有效门槛没有一致传给规则卡与对照组。

| 系统与通道 | 当前实际路径 | 冻结美股核查 |
|---|---|---|
| Flanders `hi52` | [`replicate.py`](../../christian_flanders/replicate.py) L121–124 调旧 Screen；[`screens.py`](../screens.py) L292–297 固定 ADR ≥ 3%。配置与规则卡写 ≥ 2% | 把 `pool.adr` 从 2 改成不可能的 999，`hi52` mask **逐位相同**；全输入日期 3,801 个信号 |
| Kell `pop/cross` | [`replicate.py`](../../oliver_kell/replicate.py) L66–74 调旧 Screen；[`screens.py`](../screens.py) L326–337 固定成交额 ≥ 2,000 万。登记配置 / 规则卡写 ≥ 1 亿，其他通道读该配置 | 窗口内 15,109 个多头候选中，**683 个** `pop/cross` 的前一日 20 日均成交额低于 1 亿 |
| Marios `ep/brk` | [`replicate.py`](../../marios_stamatoudis/replicate.py) L67–89 允许 200 万 / 1 美元；继承的 `pool/ep_pool` 仍按旧配置 2,000 万 / 默认 5 美元建立随机池 | 窗口内 6,535 个多头候选，**3,549 个不在 build 返回的随机池**，占 54.3% |

核查窗口是 2024-01-02 至 2026-10-16；Flanders 的 3,801 特别是包含暖机期的全部输入 mask 数，不与另外两行的窗口候选数量直接比较。候选按 entry 元组计数，同股同日不同通道可能分别计数；均非实际成交数。Flanders 窗口内多头候选另为 4,171。

**具体例子。** Marios 的 US.DYN，2024-01-03 EP，前一日均成交额约 913.9 万；US.LAES 同日约 528.8 万、前一日价格约 1.17；它们属于实际候选，却不在随机池。Kell 的 US.IRON，2024-01-08 `pop`，前一日均成交额约 2,159.8 万；US.APLD，2024-01-09 `cross`，约 2,375.4 万。精确浮点数与其余样例见 evidence 的 `frozen_us_signal_audits`。

**影响与边界。** Flanders 的 ADR 配置变化没有产生所声称的 `hi52` 策略变化；Kell 的门槛因通道不同；Marios 的同池解释不成立。对照池不应被要求满足当天真实形态，这里审查的是基本可选总体。多空包装最终使用池并集，以上 Marios 计数已经检查包装后的返回值。当前 Qullamaggie / Minervini 某些通道也有硬编码，但有效数值与配置碰巧一致，本次不算当前数值错配。

只量化了美股，未量化收益、成交或港股 / A 股影响。Marios 自定义 `to20` / `raw` 下限也未沿用 `F.liquid()` 的非美股分支，跨市场币种和有效门槛需另核，不能直接沿用通用文案。

**修复验收。** 每个 setup 输出实际资格池、有效门槛及单位，由它派生该通道的对照总体。配置维度要有消费者证据；改变一个宣称有效的阈值必须改变对应资格，或者明确标为不适用。先恢复描述和实验的可比性，再谈哪个阈值收益好。

### R04 · 延伸减仓每天重复，余仓可能在趋势仍强时卖光（P1）

**证据链。** [`systems.py`](../../trader_replication/systems.py) L138、150 把 Clement / Kell 写成延伸后卖三分之一、余下跟踪 20 EMA。当前配置均使用 `trim_signal_frac=.3333`。Clement 的 `atr50x8` 和 Kell 的 `ext10_30` 是每日持续条件，见 [`Flanders.named`](../../christian_flanders/replicate.py) L76–79、[`Kell.named`](../../oliver_kell/replicate.py) L56–58。引擎 [`system.py`](../../trader_replication/system.py) L430–433 每个满足日都卖初始仓位 `size0` 的这个比例，没有每仓一次状态。

**复现。** `repro.test_active_extension_trim_repeats_until_position_is_gone` 使用两套当前登记的 `rule_opts`，使延伸连续成立、跟踪线未破。Kell 连续四次 `signal_trim` 后清仓；Clement 已先按 2R 减过一次，随后又连续三次信号减仓而清仓。`.3333` 是近似三分之一，所以不能写成“恰好三次归零”。

**归类。** `Rules.trim_signal` L55–57 明确允许每天最多一次，引擎符合自身契约。这是策略接线和“保留余仓”描述不一致，不能把通用字段全局改成一次性来修复。它会改变长尾赢家的持有期与利润集中度；真实影响未重算。

**修复验收。** 在策略层明确每仓一次、每日重复或跨新档位再卖；按选定方式校验持续信号，并在规则卡准确显示。若改行为，要登记新版本并保留旧结果。

### R05 · 开盘已触发保本，随后穿价仍未退出（P1）

**证据链。** [`system.py`](../../trader_replication/system.py) L391–405 先按旧止损检查全天最差价；L416–417 才根据当天最好价把止损提到成本，此后不重查同日价格。

**复现。** `boundaries.breakeven_after_open_already_above_trigger`：入场 10、旧止损 9、`breakeven_r=2`；次日 O=13、H=13、L=9.5、C=9.8。开盘已经超过触发价 12，随后确定穿过 10，日内先高后低的歧义已被排除。输出却是 `why=end`，仍以 9.8 持有，`state.stop=10`，没有止损成交。

**影响与边界。** 当前 Clement / Qullamaggie 的 2R、Marios 的 3R 保本，以及 R11 中继承该规则的空头。用例的 2R 是最小证明，3R 同一分支需对应开盘超过阈值。若产品本意是收盘后更新、次日才生效，应明确写出；当前字段注释是最好价达到阈值后保本。普通日内高低先后未知的情形不能直接按本例判断。

**修复验收。** 至少让“开盘已越过保本门槛”先于后续止损处理；其余日内顺序选择保守模型并记录，不凭日 K 虚构最有利路径。

### R06 · “涨停跳过”没有回到模拟账户（P1）

**证据链。** [`scan.py`](../scan.py) L112、122–127 在 `runner.run()` 回放完成后才给买单加 `limit_up=True`；[`intraday.py`](../intraday.py) L305–311 同样作事后注记。注记不撤销持仓、不释放名额、不重选替补。盘中 orders 可显示跳过，正式 [`board.trader`](../board.py) L104–108 未消费这个字段。

**复现。** `repro.test_limit_up_skipped_label_keeps_simulated_holding` 通过真实 runner 与 scan，以昨收 10、当日 11 的 A 股单元夹具运行。结果同时出现 `buy.limit_up=True`、该股仍在 holdings、账户敞口 **27.5038%**。这是同一个输出中的矛盾，不是只检查函数注释。

**边界。** 这里按系统自己的“跳过”规则核验，不主张所有收盘涨停股现实都绝不可能成交。Martin 的 [`build_system`](../../martin_luk/replicate.py) L1338–1339 已有上游涨停过滤；不能说七位当前所有通道都同样受影响。其他系统是否已有独立过滤需逐通道确认。未量化真实历史中的触发次数，也未证明当前真实持仓含此问题。

**修复验收。** 对被产品定义为不执行的买单，在账户准入前剔除；候选、跳过原因、实际虚拟持仓要分别表达。持仓、后续卖出与敞口应和同一执行规则一致。

### R07 · 行情边界可接受过时快照或零重叠核验（P2）

| 路径 | 源码证据 | 已复现结果 |
|---|---|---|
| US / HK 盘中报价年龄 | [`intraday.check_time`](../intraday.py) L85–103：带日期分支检查同日与非未来后返回；年龄限制在 L115 的另一分支 | 15:50 检查当天 09:30 报价，仍接受，未隔离任何股票 |
| 正式 live 快照补日 | [`LiveDataset.from_snapshot`](../../trader_data/live.py) L255–277：比较昨收，但忽略报价 `time`，L274 直接贴参数 `day` | 输入时间 2026-10-15 16:00、昨收恰好匹配，目标 2026-10-19，成功生成标为 10-19 的旧 bar |
| 历史重读 | [`LiveDataset.from_history`](../../trader_data/live.py) L280–298：仅在 `checked` 非零时检查失配比例 | 只返回新增日、未交回锚点日，也返回成功：`overlap_checked=0`、`failed=[]` |

证据键依次为 `stale_us_snapshot_accepted`、`wrong_day_official_snapshot_relabelled`、`zero_overlap_history_accepted`。已检查 `live.update` L205–243 的后续校验：它检查已经重新贴日的行、数值及新增日覆盖，不重新核对报价原始日期，也不要求历史重叠有足够样本。

**影响与边界。** 正式快照路径可能把旧行情写成新日期；盘中路径可能把数小时前的行情作为当前快照。这里证明可达的放行路径，没有调用真实 provider 验证发生频率，更没有声称当前存量数据已经污染。数据源“返回最新 regular session”的接口意图不是边界检查。停牌 / 稀疏成交股票可合理缺报价，不能简单要求每只股票每分钟更新。

**修复验收。** 正式 bar 保留并核对来源交易日；按市场、交易时段和停牌状态定义年龄政策；历史重叠记录分母、覆盖并在无可比样本时明确拒绝或降级，不能把零样本当成功。先修写入边界，再按日志抽查是否需要修复数据；本次不擅自改历史文件。

### R08 · 缺价估值和持仓展示使用不同规则（P2）

**证据链。** 引擎 [`system.py`](../../trader_replication/system.py) L177–189、388–389 在缺价时不虚构成交，用最后有效收盘估值；[`runner.py`](../../trader_replication/runner.py) L120–135 却直接使用面板最后一行 close 算持仓收益和权重，L147–148 汇总敞口。

**复现。** `boundaries.missing_latest_holding`：第一天买入 10，第二天该股 OHLC 缺失。账户收益仍为有限值 0，持仓 close / ret / weight 和总 exposure 为 NaN；`json.dumps` 默认还会输出非标准 JSON 的 `NaN`。证据文件为保持严格 JSON，把这些非有限值序列化成字符串 `"nan"`，另以 `json_has_nan=true` 记录原始输出行为。

**边界。** 停牌或少量个股缺失可在 95% 覆盖检查下合法存在，相关支持见 [`test_trader_data.py`](../../trader_data/tests/test_trader_data.py) L239–247。本例不证明当前实仓停牌，且引擎本身没有按零价格清仓。

**修复验收。** 估值价、估值日期、当日可交易报价分别输出；账户与持仓采用同一估值。缺报价不能冒充今天可执行价格，机器输出拒绝非有限 JSON 数值。

### R09 · 全天回放事件被显示成尾盘操作，离场计划不完整（P1 / P2）

**证据链。** [`runner.py`](../../trader_replication/runner.py) L93–111 收集当天所有执行；[`board.orders`](../board.py) L125–145 把它们放进尾盘表，没有成交阶段或是否仍待执行的状态。`board.render` L216–218 仍写所有买卖按收盘价、“今天”就是收盘那一刻。这与盘初卖空、盘中限价、跳空止损和 R 分批的实现矛盾。当前 [skill](../../../skills/trader-screens/SKILL.md) L50、95、101 也保留“所有收盘”“不做空”等过期描述。

**影响。** 当日模拟已经发生的卖空、止损或分批，不能原样解释为现在还能执行的尾盘意图。表内已有“信号价 / 快照价”和非订单声明，是部分缓解；仍没有解决动作发生时点。看板没有连接 custody，本次没有证据表明实际发生重复下单。

**计划遗漏。** [`system.py`](../../trader_replication/system.py) L201–211 只把多头日分批状态放入 `state`；[`runner.py`](../../trader_replication/runner.py) L131 还限定 `sd > 0`。[`board.exit_text`](../board.py) L59–67 不呈现 `short_trim_day`、`short_max_days`。Martin 空头第 1 天盈利回补一半、Flanders 第 1 天盈利全部回补，以及六位空头的最长持有期限，均没有完整传入具体持仓计划。Clement / Kell 的信号减仓也不属于 `next_trim` 的 R 阈值，计划缺少该条件。`boundaries.short_exit_text_omits_time_and_daytrim` 只渲染“涨破 11.00 回补”，源码证明缺少对应状态字段。

**修复验收。** 执行记录包含阶段、原因、来源时点与当前可执行性；当天历史事件和待执行意图分别呈现。用同一管理规则生成模拟与下一日计划，覆盖日期触发、收益条件、到期和一次性状态。当前均线值只能作为参考，明日收盘线会随明日价格变化。

### R10 · 核对覆盖与源码指纹不足（P2）

**证据链。** [`runner.reference`](../../trader_replication/runner.py) L64–73 只比较 `config_digest`；L150–154 仅在参考存在时核对各年收益。它不校验代码、数据摘要、窗口或依赖版本，也不比较逐笔交易、持仓和年内路径。[`board.render`](../board.py) L221–223 只遍历存在 `check` 的系统。

**当前元数据。** `boundaries.reference_provenance` 实读 21 个系统市场组合：15 格被接受，代码摘要都不同于当前摘要 `22502bb9…`；其中 Q 的三个市场为 `f91cf65f…`，其余 12 格为 `13cad2bd…`。A 股除 Q 外六位无参考。摘要不同不证明收益已经变化，只证明不能把它们称为同代码基准。

**渲染复现。** 两位交易员只有一位带 `check.ok=True`，另一位完全没有 `check`，仍输出“到冻结日的分年收益与比对表全部一致”。见 `boundaries.reference_coverage_assertion`。

**指纹漏项。** [`compare.SOURCES`](../../trader_replication/compare.py) L43–48 没有 `trader_screens/scan.py`；但 [`Flanders.market_ok`](../../christian_flanders/replicate.py) L248–249 直接调用其中的 `index_above`，它读取 `pool_index`。当前 Clement / Kell 的市场过滤实际依赖这段源码，改指数算法可不改变所谓运行源码指纹。

**边界。** 有参考且分年收益不一致时，现有核对会报错，不能说完全没检查。协议已明确 live 历史决定不变门禁尚未实现，本项不把该未实现能力误写成既有保证。

**修复验收。** 显式区分通过、失败、缺参考；“全部”要求预期集合完整。比较基准先核对配置、代码依赖闭包、数据和窗口；年度收益一致与决策路径一致分开报告。

### R11 · 空头规则隐式继承多头分批与保本（P2）

**证据链。** [`shorts.short_rules`](../../trader_replication/shorts.py) L215–224 只在空头配置有 `trims` 时覆盖；否则 `short_trims=None`，引擎 L394 采用多头 trims。`breakeven_r` 仍为全局账户字段。

| 当前系统 | 空头实际继承 | 已登记空头说明遗漏 |
|---|---|---|
| Clement | 2R 分批、2R 保本 | 说明主要列 10 EMA 与 5 天退出 |
| Marios | 3R 分批、3R 保本 | 说明列收盘卖空、当日高点止损与 5 天期限 |
| Qullamaggie | 显式无 R 分批，但保留 2R 保本 | 说明列 10 日线与 10 天期限 |

`boundaries.short_inheritance` 加载当前注册配置核验这些值；`clement_short_trim_observed` 用 10 卖空、止损 11、次日低点 7 / 收盘 8，实际观察到价格 8 的 `trim`。

**边界与验收。** `Rules.short_trims` 明确 `None` 代表沿用多头，因此不是引擎违约。尚未找到足够原话证据决定这些继承应该保留还是取消，不能声称本人没有这些规则。应先把完整空头管理策略显式展开并对应来源，规则卡覆盖所有有效字段，再决定新版本。

### R12 · 多日交集不证明同日共振（P2）

[`scan.overlaps`](../scan.py) L64–75 的 docstring 写 same day，但只用 `code` 分组，不读 `day`。`boundaries.overlap_between_different_days` 中 A 在 10 月 19 日买 US.X、B 在 10 月 23 日买 US.X，仍列为多人买入交集，输出不保留各自日期。

影响 `--days > 1` 的买入 / 卖空交集；当前持仓是同一末日，不受此日期混合问题影响。**反证：** `scan.show` L185–186 实际写“近 N 个交易日被多人买入”，这个标题可以成立，不应指控它显示了错误的同日标题。应明确提供“窗口内均买过”和“同日买入”两种口径，保留事件日期；不能把前者解释成同日共振。

## 4. 方法论与规则保真

### M01 · 第二层和第三层并非相同执行（P1）

**方法契约。** [复刻方法](../../../skills/trader-replication/references/METHOD_CN.md) 的三层分别为本人股票和执行、本人股票和我们的执行、我们股票和我们的执行。要把第二层到第三层的差主要定位到选股，至少入场止损规则要相同。

**实现差异。** Flanders 真实 [`entries`](../../christian_flanders/replicate.py) L209–211 应用当前 `stop_cap=.06`，但同文件 `his_entry` L315–320 只应用 `stop_min`，不封顶。[`Study.three`](../../trader_replication/study.py) L637 与 [`common.funnel`](../../trader_replication/common.py) L370 都调用后者。

**微型证明。** `boundaries.second_layer_stop` 令收盘 100、日低 80、最小止损 1%、封顶 6%。真实路径止损 **94**，第二层止损 **80**。相同后续上涨 10%，无成本时真实路径 **1.6667R**，第二层 **0.5R**；百分比涨幅相同，风险单位、仓位及潜在止损存活路径不同。

**已有报告中的发生证据。** [`common_funnel.json`](../../trader_replication/reports/common_funnel.json) 的 `christian_flanders.rows` 有 **27 行、26 个唯一股票日期**，`l2_r` 非空且原始 `stop_width > .06`。F03：SMCI，2024-01-19，宽度 19.9546%，`l2_r=2.11`、`our_r=7.02`，两层 `ret` 同为 .421；F19：CRNC，2025-01-03，宽度 46.2488%。这是已有诊断输出，本次没有重算市场收益。

**解释影响。** [`Flanders FINAL`](../../christian_flanders/reports/FINAL_CN.md) L38–46 把第二层平均 +6.4R 与第三层 +0.21R 的差归到选股，这一归因需要降格。它不能反向证明执行解释全部差距。

**反证与修复验收。** 第二层解除名额、总敞口、反馈限制是 `study.py` L624、640–641 明确的诊断设计，不另算 bug。但“同执行”和“放宽执行”要分别输出。复用正式止损转换，并保留 setup kind；检查 Q / Marios 的 ADR 跳过条件是否也被强制本人交易绕过。先验证同票同日 fill / stop / kind / 风险单位一致，再重估归因，不静默覆盖旧报告。

### M02 · ADR、ATR 与 R 不是可直接替换的单位

**Clement：P1 保真问题。** [`RULES_CN.md`](../../clement_ang/notes/RULES_CN.md) L25、37 记录到 2 倍 ADR 分批并保本；当前 `r15.json.chosen_config.rule_opts` 是 `trims=[2]`、`breakeven_r=2`。[`system.py`](../../trader_replication/system.py) L390、395、407–417 的 R 为初始入场至止损的距离。ADR 则在 [`screens.py`](../screens.py) L122–124 为高低比的滚动百分比，两者没有恒等关系。窄止损时 2R 提前，宽止损时延后。

当前规则卡准确写 2R，因此这是原话到实现的差异，不是配置加载错。问题是 [`Clement FINAL`](../../clement_ang/reports/FINAL_CN.md) L71 又把 2R 描述成“他的离场”，证据不足。应把 ADR / ATR / 初始止损 R 的单位、取值日和来源分别保存，核查整份台账后再决定替换。

**Marios：已披露代理，不另判隐藏缺陷。** [`RULES_CN.md`](../../marios_stamatoudis/notes/RULES_CN.md) L30 写 2.5–3 ADR；L43–44 明确承认以 ADR 近似 ATR、在止损约 1 ADR 时以 3R 近似 3ADR。当前配置允许 EP 止损至 3ADR，因而在最宽情形 3R 可对应约 9ADR，原代理前提不总成立。这里是单位代数和配置允许上限，不代表已观察到全部交易都在上限。另有催化剂、跳出几个月区间、生物股次日执行 / 10% 仓位等原话与当前日 K 版不同，见 RULES L25–31 及当前 `ep.escape=0`、统一 `max_position=.25`；需要逐环保真，不据此否定本人方法。

**Qullamaggie：已知研究偏离应显式呈现。** 当前 [P1B 配置](../../qullamaggie/reports/p1.json) L120–134 的 `stop_adr={'brk':1,'ep':5}`，突破和 EP 的上限不相同。本人 EP 教程要求开盘区间突破、日低止损，并限制止损宽度到约 1–1.5 ADR / ATR；来源：[本人 EP 教程](https://qullamaggie.com/how-to-master-a-setup-episodic-pivots/)（本次联网核对）。本人通用教程描述 3–5 天分批后提至保本；来源：[本人三种形态教程](https://qullamaggie.com/my-3-timeless-setups-that-have-made-me-tens-of-millions/)。当前规则卡已承认改为 +2R 才保本，属于登记研究选择，不能未经新研究就恢复原值并声称更好。

本次重新打开了上述 Q 的两篇原始文章；Clement / Marios 依据仓库带访谈时间戳的规则记录，未逐段重听原视频。来源核验强度不同，后续若争议在原话，应回到对应片段。

### M03 · 验证使用历史和 forward 口径需区分（P2）

**“此前没用过”不准确。** [`COMMON_RESULTS_CN.md`](../../trader_replication/reports/COMMON_RESULTS_CN.md) L307 称 Clement / Marios 的 2026 验证段此前没用过。但 Clement R15 已用包含 2026-10-16 的整段选择，`r15.json.full.AA3.by_year.2026=.6732415`；Marios 已有 `validate_r1.json` 的 2026 结果约 −4.2898%。Git 历史如下，时间均为 `-04:00`，不是文件修改时间：

| 提交 | 时间 | 已存在的证据 |
|---|---|---|
| `04a70da853f0f75167098c160eca46ce69d70112` | 2026-10-19 02:04:16 | Clement R15 及最终报告 |
| `93c77cbb36d11fe73db6cd84ba76fe34b05cc58a` | 2026-10-20 04:01:48 | Marios 单次 2026 验证 |
| `603a51c8466c0a8be96912e9376148d27ed27e46` | 2026-10-20 07:06:26 | V2 预登记 |
| `c26d9c9fcf5594cc804646166ce57983ec5a5782` | 2026-10-20 07:23:26 | 看过结果后按用户决定移除下跌时段条件 |

**重要反证。** [V2 预登记补记](../../trader_replication/notes/COMMON_PERSONAL_V2_CN.md) L28–30 和 COMMON_RESULTS L323–336 明确记录用户事后放宽及 2026 不再独立；总体比对也写全部样本内。这不是未授权改门槛的指控。旧 JSON 的 `passed=False` 保留历史是正确做法，不应擦掉。尚未在“本轮”跑过的增量候选，也不能把继承基线已使用的数据恢复为未见数据。

**forward 的实际含义。** [`systems.py`](../../trader_replication/systems.py) L3–5 将 freeze 定义为最后选择数据日，L14、24 默认为 2026-10-16；登记注释记批准时间分别在 10-19、10-20、10-21。[`runner.forward`](../../trader_replication/runner.py) L53–61、149 从样本截止日切回放，research / baseline 也有相同输出。

因此它能证明“数据切分之后的连续账户表现”，仅凭该字段不足以证明“批准后逐日预先留存的观察”。没有证据证明研究者选择时已经看过 10-19 至 10-21 行情，**不能把这里写成已证实的数据泄漏**。现有持仓延续到切分之后是合理连续账户口径。

**验收。** 保存研究数据末日、批准时间、版本 / 源码摘要、首次观察时间；区分截止后延伸回放和批准后逐日留存。为数据使用历史加可追溯记录，归档和改名不重置独立验证资格。

### M04 · 行为、指标与样本边界限制怎样评价策略

**最终买到的交易仍不够像。** 既有 [`COMPARISON_CN.md`](../../trader_replication/reports/COMPARISON_CN.md) L108–116 的美股 exact 对照如下；本次读取既有报告，未用当前源码重跑成交统计。窗口为 2024-01-02 至 2026-10-16，口径是同票同日实际买到，不是宽信号覆盖。

| 交易员 | 窗口内有精确日期台账 | 数据能找到 | 系统实际买到 | 能支持的判断 |
|---|---:|---:|---:|---|
| Martin | 63 | 60 | 2 | 对这份可用公开台账，最终行为覆盖低 |
| Flanders | 32 | 31 | 6 | 仍有较大选择 / 执行差距，M01 影响归因 |
| Clement | 12 | 8 | 2 | 样本小且缺票，不足以由收益相近证明复刻 |
| Qullamaggie | 1 | 0 | 0 | 没有可用分母，不能报“命中率 0%” |
| Kell | 28 | 28 | 6 | 当前行为覆盖不足，另有 R03 / R04 |
| Minervini | 24 | 22 | 0 | 当前只是 R0b 基线，不能代表完整方法 |
| Marios | 0 | 0 | 0 | 窗口内无 exact 台账，不能据此评价命中率 |

这些公开交易可能偏向展示案例，不代表全部私有交易。正确下一步是定位数据缺票、候选资格、触发、排序 / 名额、执行和持有分别损失多少，不能把差距一概归到选股，也不能用总体收益像来替代行为证据。

**门禁不是统计有效性的同义词。** [`协议`](../../../docs/TRADER_PROTOCOL_CN.md) L24–33 明定胜率 ≤ 35%，这是项目现有约定；`gate.check_win` 忠实执行，不能当成代码错误。但它并非市场普遍定律，不能仅因更高胜率就认定实现有问题。分层时应匹配各人胜率、盈亏比、持有期和利润集中度；100 次随机排位不能抵消同段反复选参。对低胜率、高盈亏比系统，去头部失败也不能单独否定原方法。共享轮次曾把去最大交易结果作为门槛，见 [`common.py`](../../trader_replication/common.py) L504–511；应结合当轮用户目标与预登记审查，不能据一般原则重判全部历史。

**固定名单与成本边界已有披露。** 协议 L14、72 明确名单来自 2026-10 快照、期间退市股缺失。逐日筛选与同名单随机对照不能恢复当时上市总体，收益适用于这个固定存续池。协议 L83–88 也披露借券可得性和年化 3% 的简化；没有动态难借券费用、实际可借数量。本文不把这些已披露假设重复包装成新发现，也不把模拟收益当实际可成交净收益。

## 5. 七位当前版本分别应怎样看

| 交易员 / 当前版本 | 当前最需要处理的环节 | 本次不作的推断 |
|---|---|---|
| Martin `R74 + S7`，已冻结 | R01 / R02 空头时序和对照；R09 计划；exact 2/60 的行为差距 | 高回测收益不证明真实复刻，也不因高回撤就否定本人 |
| Flanders `R15 C4 + C1C + S4`，已冻结 | R03 ADR 无效配置；M01 三层执行；R01 / R02 空头 | 修复后收益或选股结论的方向未知 |
| Clement `R15 AA3 + C4A + S5`，已冻结 | M02 ADR→R；R04 重复减仓；R05 保本；R11 空头继承 | 已批准版本不等于规则保真已完成 |
| Qullamaggie `R11 N3 + S7 + P1B`，已冻结 | R01 / R02；R05；EP 5ADR 与原话差距；首日目标管理简化 | 可用 exact 分母为零，不作命中率或本人有效性结论 |
| Kell `R6 A5 + S5`，已冻结 | R03 分通道流动性门槛；R04 重复减仓；R01 / R02 空头 | 683 是候选数，不是错误成交或亏损笔数 |
| Minervini `R0b`，基线 | 保持 B 级 / 基线定位；数据、展示、参考核对等共享问题 | 没有空头，不归入 R01 / R02；当前版本不代表完整方法 |
| Marios `R1 L4 + C4B + S1 P4`，研究版 | R03 异池；M02 单位代理 / EP 保真；R05 / R11 | 较差旧验证不能据异池问题直接翻成好结果；仍是研究版 |

所有系统还共享 R07 / R08 / R10 等基础设施问题；R06 的实际 A 股影响需按通道过滤核实。登记状态来自 systems L99–115，不在本次自行升级或降级。

## 6. 应保留的模型边界与本次纠偏

1. **首日普通管理从次日开始是明示模型。** `system.py` L4–6 已写明。`boundaries.day0_target_not_managed` 通过真实 `level_entries(at_open=True)` 生成 10 卖空、止损 12；当日跌至 8、目标线 9，仍无 target 回补。这限制 Q 的盘初空头及其他首日管理保真，但不是引擎违反自身约定。补首日管理不保证改善收益。
2. **毛敞口上限主要约束开仓 / 加码，不是每时刻归位。** `gross_close` 默认关闭；费用和价格变动可使权重漂移。已有比对报 Martin 最大毛敞口 324%，与规则卡 280% 的关系应解释为限额时点，不能凭漂移本身判撮合算错。具体机制见 `system.py` L97–100、272–278、510–520。
3. **期末 end 不是实际平仓。** 净值先估值，end 用来导出未平状态；已平仓统计排除它。不能把 end 行当真实成交或直接当同一清算口径相加。
4. **涨停、原话、交集结论均收窄到已证明范围。** Martin 存在上游涨停过滤；Clement / Kell 重复减仓是接线与描述冲突；Marios ADR→R 已披露；多日“窗口内均买过”标题成立；freeze 不是批准时刻但没有证实泄漏。
5. **通过现有测试不推翻这些发现。** 既有测试验证已覆盖契约；本次夹具证明另一些契约缺口。新增 characterization 断言“当前缺陷存在”，它们通过绝不表示缺陷已修复，修复后应更新为正确行为的回归测试。

## 7. 复现、数据版本与验证

### 7.1 输入与资源

| 项 | 本次值 |
|---|---|
| Git HEAD | `7f943e7c67c73d305bd5d3ba03f65fc71291fd95` |
| `compare.code_digest()` | `22502bb9bc031a866d11ee64ae8bdfc4849eec88f57c8f59c2e4f261e2c1e26e`，注意 R10 的依赖漏项 |
| 已有数据 | `trader-data-v1`，美股 3433 只的冻结输入 |
| 美股数据摘要 | `920f88c4c039149473552f095c24052261d7e74d2d12e363490746d3ea745158`，脚本校验 DATA_PIN |
| Python / numpy | `/opt/futu-opend/venv/bin/python` / `2.4.6` |
| 资源方式 | 检查可用内存约 2.2 GiB 后，三个系统逐进程串行；单线程 BLAS；地址空间上限 1800 MiB；不写面板缓存 |
| 观测峰值 RSS | Marios 969 MiB、Kell 1144 MiB、Flanders 914 MiB；仅用于本次资源约束，不是性能基准 |

冻结数据核查只重建面板及候选，不运行新的收益比较、安慰剂批次或参数搜索。只改变 ADR 到 999 的检查用于证明配置是否被消费，不作为候选策略研究。

### 7.2 从仓库根目录复现

```bash
cd /opt/opend-us-options
nice -n 19 env OPENBLAS_NUM_THREADS=1 /opt/futu-opend/venv/bin/python -m studies.trader_screens.reports.strategy_review_20261025_repro
nice -n 19 env OPENBLAS_NUM_THREADS=1 /opt/futu-opend/venv/bin/python -m studies.trader_screens.reports.strategy_review_20261025_boundaries
free -m
```

以下三条依次执行，不并行；需要已经存在且摘要匹配的冻结数据，不会自动拉数。

```bash
nice -n 19 env OPENBLAS_NUM_THREADS=1 /opt/futu-opend/venv/bin/python -m studies.trader_screens.reports.strategy_review_20261025_real marios_stamatoudis
nice -n 19 env OPENBLAS_NUM_THREADS=1 /opt/futu-opend/venv/bin/python -m studies.trader_screens.reports.strategy_review_20261025_real oliver_kell
nice -n 19 env OPENBLAS_NUM_THREADS=1 /opt/futu-opend/venv/bin/python -m studies.trader_screens.reports.strategy_review_20261025_real christian_flanders
```

`real.outside` 对 Marios 表示不在随机池，对 Kell 表示 pop/cross 的前日均成交额未达 1 亿；Flanders 不使用此字段，以 `adr_2_vs_999_masks_equal` 为证。三个输出带完整当前配置、配置摘要、数据摘要和峰值内存，已经收入 evidence JSON。

Git 时间链可用下列命令复核；要进一步核验当时内容，使用 `git show <提交>:<路径>`，不依赖当前文件时间戳。

```bash
git show -s --format='%H %aI %s' 04a70da853f0f75167098c160eca46ce69d70112 93c77cbb36d11fe73db6cd84ba76fe34b05cc58a 603a51c8466c0a8be96912e9376148d27ed27e46 c26d9c9fcf5594cc804646166ce57983ec5a5782
```

### 7.3 本次实际执行的检查

| 检查 | 结果 | 证明范围 |
|---|---:|---|
| `unittest discover -s studies/trader_replication/tests -t .` | 163 通过 | 现有复制 / 引擎测试 |
| `unittest discover -s studies/trader_screens/tests -t .` | 57 通过 | 现有看板测试 |
| `unittest discover -s studies/trader_data/tests -t .` | 25 通过 | 现有数据边界测试 |
| `python3 -m unittest discover -s custody/tests` | 194 通过 | 项目结构及 custody 回归 |
| `strategy_review_20261025_repro` | 5 通过 | 五项当前行为复现 |
| `strategy_review_20261025_boundaries` | 全部断言通过 | 本文所列微型边界与分层执行 |
| 三个 `strategy_review_20261025_real` 进程 | 均退出 0 | 冻结美股候选统计 / 无效字段 |

现有测试共 **439 项**；新增五项与边界脚本单列。测试日志的计数、运行时间、脚本 SHA-256 收入 evidence。没有重算修复后的收益，因为本轮未修策略，也未申请新的研究方案。

## 8. 后续处理顺序与完成标准

| 顺序 | 要完成的事 | 可审核的完成标准 |
|---|---|---|
| 1 | 固定执行阶段与账户状态：R01、R05；同时收紧 R07 正式数据写入边界 | 未来收盘不改变盘初资源；开盘已触发保本按定义执行；旧日期 / 零核验不能伪装成功 |
| 2 | 恢复实验可比性：R02、R03、M01 | 同股恒等对照；每通道资格可追踪；两层相同股票日期保持执行规则 |
| 3 | 明确策略单位与次数：R04、R11、M02 | 每项有效规则有单位、来源、方向和重复次数；规则卡准确表达，不静默改原版本 |
| 4 | 对齐账户和交付：R06、R08、R09、R10、R12 | 跳过不持仓；缺价有估值日期；待执行意图可辨；缺参考不称全部通过；交集保留日期 |
| 5 | 按已登记旧候选有限复核，再安排新数据观察 | 保留旧结果，报告影响笔数和净值差；独立验证只使用未参与选择的数据，行为约束一起评 |

这次没有预判修复后哪位收益更高，也不建议从若干缺陷直接推出“技术分析无效”或“这些交易员的方法做不到”。已经定位的是当前版本在数据、执行、规则保真和实验归因上的具体差距。

审查使用 poteto-mode 的 investigation 流程：三个独立切片审查后由新的综合角色核对共同根因，主审复跑最小证据与冻结候选。采用 Build the Lever 保存可复跑脚本，Explain the Number 明确候选 / 成交 / 台账分母，Prove It Works 以实际输出校验结论，Model the Domain 将执行阶段、单位及重复状态作为后续结构性修复方向。具体证据比角色数量更重要；最终交付附独立复核的剩余注意项。

## 9. 交付复核与剩余注意项

reviewed by gpt-5.6-sol

对决策记录、本次会话中的真实命令与输出、报告及源码作交叉复核，结果为 **No flags**：没有发现记录失实、跳过验证却声称通过，或把候选 / 旧结果扩大解释的问题。复核角色没有重复运行全量测试或行情面板，不能算第二份独立实验。所有角色均来自 OpenAI / GPT 平台的不同型号与上下文，不是跨厂商或外部第三方审计。

完整测试日志和复核原文已收入 evidence JSON；主审在文档落盘后又运行 custody 194 项，全部通过。后续仍需量化受影响真实成交、收益与随机排位，核查港股 / A 股各通道，以及对有争议的访谈规则回听原始片段。本文完成的是现版本审查与证据留存，问题本身尚未修复。
