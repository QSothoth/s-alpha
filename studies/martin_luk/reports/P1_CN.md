# P1：复刻流水线框架

P1 框架已实现。Martin 已接上 facade，七道卡子、三种行情标签和分层 round 校验都有可运行检查。27 个登记系统与市场组合的入场、账户、完整台账及近五日看板 JSON 与修改前一致；M1B、M2A、M3B 的选择段和全期原台账、净值也精确一致。没有运行新候选、拟合模型、联网、下载行情或提交当前工作树。旧报告与登记、看板受保护文件共 67433 份，SHA256 全部未变。

## 新交易员填什么

继承 `Study`，提供统一行情适配 `arrays`、池 `universe`、有序点名 `signal`、账户规则 `trade`。`signal` 返回每个日历夜的代码列表，空夜也保留。S 与共享 `allocate` 共读它；特殊入场才覆盖 `entries`。默认次日开盘、前夜低点止损；默认10日冷却。行情 `regime` 可选，只读市场行情，不接台账或段表。

`build()` 组合这些块，继续返回 `(entries, Rules, mask, pool)`。配置分 universe、signal、allocate、trade、switch 五节，`Config` 提供旧扁平键的只读别名。覆盖旧 build 的研究仍标 legacy，未迁移前不算 S 门禁通过。dummy 交易员及一致性检查在 `tests/test_facade.py`。

Martin 的 `system_nominations` 保留 priority 顺序，`allocate` 保留候选前四截断。R74 明确保留原有零冷却，不把新默认塞进登记版。成功开仓上限、持仓上限与换仓在共享分配和原账户引擎之间衔接，`Rules` 没有增加字段。仓库没有独立的 simulate.py，实际模拟入口仍是 system.py 的 simulate。

## 七道卡子

| 卡子 | 查什么与通过线 | 不过时允许动作 |
|---|---|---|
| G0 | 本人原话、来源与时间戳；至少30笔带日期台账，exact 单报；台账、段表与切分的 SHA | 补资料；台账不足只作按原话的规则评测 |
| G1 | 数据、成交价、不看未来、已平仓≥30且胜率≤35%；指纹齐；先核参照 | 修数据或引擎 |
| G2 | 有样本的状态≥3个有交易 episode、≥15笔；整段置换 p<0.1、至少两段同向；定义扰动重合率≥90%；截断一致 | 只动 switch；无样本状态按原话冻结并标未观测 |
| G3 | S0 早期合格夜，10日冷却，K=3 主留出覆盖≥80%；同冷却不限K平均新名≤5；按年留一三折全报 | 只动 universe 或 signal，先报可达上限 |
| G4 | 已平仓≥30且胜率≤35%，每年实际开仓≥52；有出处的盈亏比、持有天数、每年笔数差在±20%内；买到与三层对照齐 | 用漏斗定位，只动 allocate 或 trade |
| G5 | 每年不亏；本人在数据期内有出处的每一年财富比对数距离≤0.3 | 先诊断，回到对应 G3/G4，不换尺子 |
| G6 | 指纹、三市场与 robust 报告、登记、forward 日期一致；冻结日为数据末日，用户同意 | 保留原登记，补齐交接 |

G2、G4、G5 全报 episode 留一。G4 按开仓所属段拆交易，G5 按实际日历段拆账户回报；剔除段的回报只是描述，不假装重新分配了资金。资金纯度、毛利纯度、段吃到、随机入场、去掉两笔及10天超额均只报告。

新 round 要声明 layer、sections_changed、upper_bound，并提供卡子证据 JSON。跨层配对还要 paired 与机制，不能越过上游卡子。261 份已有 round 按开始时的路径与 SHA 兼容。SKILL 只保留七行流程，接口、留一和历史口径放 METHOD，旧覆盖定义移到单独的历史附录。

## 三种行情定义的固定描述

区间为2024-01-02至2026-10-16，共701个美股交易日，2023只暖机。三种定义分别计算，互不叠加。本次均用前日价格≥5、20日均成交额≥2000万的市场池等权指数或名单宽度，没有下载 QQQ/IWM。

idx_ema：指数低于 EMA50 为 weak，其余高于 EMA21 的1%带为 up，余下 pullback。breadth：领涨与落后只数比1.5，均线为21、50。smc：左右各10根分形，右半完成才确认；向上、向下 BOS 或 CHoCH 分别映射到 up、weak，收回突破位内为 pullback。等权篮子高低点是指数代理，不是真实指数的逐笔高低。所有标签用于当天时只读前一日及以前。

| 定义 | up 天 / 段 | pullback 天 / 段 | weak 天 / 段 | 总段数 |
|---|---:|---:|---:|---:|
| idx_ema | 318 / 51 | 213 / 69 | 170 / 24 | 144 |
| breadth | 424 / 30 | 159 / 39 | 118 / 10 | 79 |
| smc | 425 / 38 | 216 / 46 | 60 / 9 | 93 |

| 定义 / 年 | up 天 / 段 | pullback 天 / 段 | weak 天 / 段 |
|---|---:|---:|---:|
| idx_ema / 2024 | 113 / 18 | 90 / 31 | 49 / 15 |
| idx_ema / 2025 | 121 / 19 | 60 / 23 | 69 / 6 |
| idx_ema / 2026 | 84 / 14 | 63 / 16 | 52 / 4 |
| breadth / 2024 | 175 / 6 | 59 / 9 | 18 / 4 |
| breadth / 2025 | 138 / 12 | 58 / 16 | 54 / 5 |
| breadth / 2026 | 111 / 12 | 42 / 14 | 46 / 2 |
| smc / 2024 | 182 / 12 | 68 / 14 | 2 / 2 |
| smc / 2025 | 148 / 8 | 57 / 11 | 45 / 3 |
| smc / 2026 | 95 / 18 | 91 / 23 | 13 / 4 |

分年段数在年度边界截开，不能相加当作独立 episode 总数。完整 episode、每日日状态、定义 SHA 在 `p1_work/regimes/` 与 `regime_specs.json`。两截点2024-09-30、2025-09-30均一致。定义扰动最低日重合率为 idx_ema 88.7%；breadth 83.7%；smc 80.5%，三者按冻结扰动口径均未到90%。这些是标签描述，本轮不启用新 Switch，也没有改参数去过线，没有用本人行为或候选账户挑选 producer。

每个交易员最多两个状态开关，每个必须逐字引用 RULES_CN。只控制方向、规模、形态启用、持仓数或换仓，不能改同类票的排序与止损宽度。无本人样本的状态保留有出处规则，标未观测，冻结后由前向记录验证。

只复核已有 IE9 点名时，S0 的年度各格及逐段记录完全一致，2026仍为11/17。2024、2025的外折模型缺失照报，没有新增拟合；工件将1注明为保守覆盖天花板，未把它冒充本轮新估的池上限。历史留出仍带星号，不重置2026已被查看的事实。

## 一致性与测试

27个登记与市场组合覆盖 systems.all_(versions=True) 及 new_styles 的全部系统。入场、规则、台账与看板按完整规范 JSON 编码比较 SHA；净值、掩码与池按形状、dtype 和原始字节比较。渲染源码与登记配置也在受保护 SHA 中。M1B、M2A、M3B 分别对选择段及2024起连续全期的原 trades.json、curve.json 逐值比较，六项全过；M2 的冻结评分推断也核对了原逐晚点名。

`martin check` 对已有 diagnose、final、robust 三份 R74 工件均报 identical。本轮新复放的完整33条核对在 `p1_work/checks/`。原工作区的 runner.check 因源码指纹已不同于 compare.json 而是 missing，修改后仍是 missing，没有把它算作 passed；本轮以修改前快照的精确核对补齐证据。

| 测试组 | 项数 | 结果 |
|---|---:|---|
| custody/tests | 237 | 通过 |
| studies/trader_replication/tests | 1144 | 通过 |
| studies/martin_luk/tests | 269 | 通过 |
| studies/trader_screens/tests | 102 | 通过 |
| studies/trader_data/tests | 37 | 通过 |
| studies/christian_flanders/tests | 18 | 通过 |
| studies/clement_ang/tests | 7 | 通过 |
| studies/dan_zanger/tests | 27 | 通过 |
| studies/marios_stamatoudis/tests | 7 | 通过 |
| studies/mark_minervini/tests | 4 | 通过 |
| studies/oliver_kell/tests | 11 | 通过 |
| studies/qullamaggie/tests | 8 | 通过 |
| studies/sean_ryan/tests | 15 | 通过 |
| studies/auction_strength/tests | 19 | 通过 |
| studies/daily_technical/tests | 10 | 通过 |
| studies/opportunity_events/tests | 4 | 通过 |
| studies/trader_registry/tests | 9 | 额外检查：既有索引漂移 |
| studies/trend_breakout/tests | 60 | 通过 |
| studies/us_0dte_picks/tests | 154 | 通过 |
| watch/test_watch.py | 11 | 通过 |

所需19组共2144项通过，trader_replication 保留1项既有预期失败，trader_screens 保留1项既有跳过。最终补充的48项定向检查也全部通过，覆盖分节同名参数、G0文件对应关系、G4开仓与平仓分母、可选空头 Switch 及加载行情前阻止跨层 round。额外 registry 的生成索引一致性失败在 HEAD 已存在，四个输入文件均与 HEAD 相同，未扩大修改范围去重写导航资料。证据在 `preexisting_registry_index.json`。

首轮曾发现旧 AST 诊断条件文本不识别抽出的持仓检查，以及 Dan 成功卡仍传年均数、要求随机胜出；现已修正并重跑。成功判定的三个调用适配器补了逐年真实开仓数，不改变它们的交易构造。首轮失败日志保留，最终结果取 `_final.log`。Holguin 使用自己的期权引擎，核对脚本已按原 board_run 入口适配。

所有重算均在 CPUQuota=60%、MemoryMax=900M 的 scope 中运行，NumPy 单线程，按系统与市场顺序单进程核对。已记录复放的最大 RSS 为914.9 MiB。原密钥钩子已调用 secret_guard，安装器没有覆盖现有配置；没有跳过钩子或作当前工作树提交。

原保护清单还误含当前任务自身不断追加的 `p1_logs/codex_p1.log`。它单列为本轮运行日志，冻结时的523847字节前缀 SHA 已验证未变。原 protocol 保留，范围澄清在 `protected_scope_clarification.json`，没有放行其他文件变化。

## P1 改动文件

- `studies/trader_replication/config.py`
- `studies/trader_replication/allocation.py`
- `studies/trader_replication/regime.py`
- `studies/trader_replication/pipeline.py`
- `studies/trader_replication/legacy_rounds.json`
- `studies/trader_replication/study.py`
- `studies/trader_replication/martin.py`
- `studies/trader_replication/system.py`
- `studies/trader_replication/gate.py`
- `studies/trader_replication/success.py`
- `studies/trader_replication/shorts.py`
- `studies/trader_replication/review.py`
- `studies/trader_replication/README.md`
- `studies/trader_replication/tests/test_facade.py`
- `studies/trader_replication/tests/test_regime.py`
- `studies/trader_replication/tests/test_pipeline.py`
- `studies/trader_replication/tests/test_success.py`
- `studies/martin_luk/replicate.py`
- `studies/martin_luk/e1_research.py`
- `studies/martin_luk/p1_verify.py`
- `studies/martin_luk/p1_report.py`
- `studies/dan_zanger/replicate.py`
- `studies/dan_zanger/tests/test_success.py`
- `skills/trader-replication/SKILL.md`
- `skills/trader-replication/references/METHOD_CN.md`
- `skills/trader-replication/references/METHOD_LEGACY_COVERAGE_CN.md`
- `docs/TRADER_PROTOCOL_CN.md`

报告为 `reports/P1_CN.md`，全部工件在 `reports/p1_work/`；入口、测试与受保护核对见 `completion.json`、`sources.json`、`protected_check.json` 及各日志。
