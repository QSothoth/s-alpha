# trader_replication：逼近一位交易员的通用代码

使用说明见 [skills/trader-replication](../../skills/trader-replication/SKILL.md)（研究过程）；冻结后的系统和各交易员的筛选在 [skills/trader-screens](../../skills/trader-screens/SKILL.md)（代码 `studies/trader_screens/`），第一个例子在 [martin_luk/](../martin_luk/README.md)。只读研究，不接 custody。

| 文件 | 内容 |
|---|---|
| `ledger.py` | 交易台账 CSV 的读取、校验（日期精度 exact / chart / window）、按日期切选择段 / 验证段 |
| `fidelity.py` | 某环节的输出（天 × 股票的布尔掩码）命中台账交易的比例、同宽随机命中率、提升倍数、名单宽度、累积漏斗 |
| `edge.py` | 同一天、同一波动分组里选中 vs 没选中的同类事件的结果差（按日重抽样区间）；次日开盘起的远期收益 |
| `study.py` | 复刻 facade：新交易员填 `arrays / universe / signal / trade`，特殊入场覆盖 `entries`；共享 `build` 组合并调用 `allocate`。旧 build 覆盖实现标 legacy；研究入口仍有 round、diagnose、robust、final、three |
| `config.py` / `allocation.py` | 五节配置与只读旧键别名；共享冷却、候选或成功开仓名额、持仓上限、换仓和状态映射 |
| `regime.py` | 只读行情的三态标签：idx_ema、breadth、smc 三选一，episode、冻结 spec SHA、截断与扰动检查 |
| `pipeline.py` | G0–G6、按年及 episode 留一、允许动作表、新 round 分层校验；细节见 [METHOD](../../skills/trader-replication/references/METHOD_CN.md) |
| `negations.py` | 否定登记表 `notes/NEGATIONS.json` / `NEGATIONS_CN.md`：没带入的候选连同当时的基础配置；`stale` 列出基础配置已变、需要重测的行 |
| `martin.py` | 用 Martin Luk 的 `replicate.py` 走通用流程的适配和自测：只读 `studies/martin_luk`，输出写 `data/trader-replication-selftest/`；`check` 与已提交的 R74 报告逐项比较 |
| `panels.py` | 研究用的日 K 数组，经统一数据接口 [`studies/trader_data`](../trader_data/README.md) 取得（默认冻结 Release `trader-data-v1`）；公共评测区间 `WINDOW`；`upto` 裁去已复权面板的后续行，供检查决策是否读取后续面板行；它不能检查截止日后公司行动是否改变历史复权尺度；`DATA_PIN.json` 固定各版本的数据摘要（`python -m studies.trader_replication.panels pin`）。规范见 [TRADER_PROTOCOL_CN](../../docs/TRADER_PROTOCOL_CN.md) |
| `systems.py` | 登记的交易员系统：每人一份（研究模块 + 带入配置 + 版本 + 状态 + 冻结日），比对、看板、实际运行都只读这里 |
| `runner.py` | 一个系统在一个市场上回放到最新一天：账户、当天买卖、没做的买点、持仓与引擎给出的离场线；回放截到冻结日与比对表核对。`python -m studies.trader_replication.runner us live` |
| `success.py` | P1 的 G4/G5：已平仓≥30且胜率≤35%，每年实际开仓≥52且不亏；有出处的盈亏比、持有与笔数±20%，有出处的年度财富比对数差≤0.3。随机对照与 drop_top 只作诊断，旧报告不回改 |
| `gate.py` | 工程门禁：数据版本与区间、不看未来（截面板前后决定一致）、成交价在当日区间内、胜率 ≤ 35%；单测 `tests/test_gate.py` |
| `compare.py` | 各交易员当前配置在统一数据层上的三市场横向比对与门禁，写 `reports/compare.json`、`reports/COMPARISON_CN.md`：`python -m studies.trader_replication.compare run [us,hk,cn] [交易员 ...]` |
| `shorts.py` | 空头（多空一体，[TRADER_PROTOCOL_CN 第 5 节](../../docs/TRADER_PROTOCOL_CN.md)）：`LongShort` 包住各人的研究模块，配置没有 `short` 时原样调用其 build（`systems.py` 一律包上）；各人的 `short_setups` 给出收盘卖空掩码，或前一日决定的限价（反抽到线）/ 开盘 / 卖空止损单（跌破），止损在上方；同一天先开多再开空；`round <交易员> S1` 跑预登记轮次（只做多 / 多空合计 / 只做空 + 同池随机做空、下跌时段按月、小盘空单单列、门禁），`gate` 跑不看未来，`render` 写 `studies/<id>/reports/SHORTS_CN.md` |
| `common.py` | 7 套登记系统的共同缺口（2026-10-20）：`funnel` 统一漏斗与第二层 R，`round C<n>` 共享机制在 7 人选择段上的横向表与接受规则，`validate V1` 落到个人后的一次性验证。配置里的 `common` 开关（`rank` / `stop` / `add` / `ep_slots` / `floor` / `small`）默认关闭，`shorts.LongShort` 才调用；结论在 `reports/COMMON_RESULTS_CN.md`（没有通过的共享机制） |
| `shorts_robust.py` | 带入的多空版本的稳健性（借券 6%、空单风险减半、只在指数 < EMA50 做空、成本加倍），只报告 |
| `system.py` | 多空日 K 组合：收盘确认入场、固定风险定仓、分批（按 R / 按信号）、EMA 跟踪（分批后或回撤 / 指定市场日换另一条）、保本、信号全卖、加码（一档或多档，止损提到成本价）、次日无延续离场、新仓反馈调风险、按日风险倍数、同时持仓上限、当天盘中止损；安慰剂（同一天同一名单随机换股、同样止损宽度）。新规则都在 `Rules` 里、默认关闭 |

`simulate` 可接收真实分钟 OHLC：`px['session']` 是交易日编号，`px['daily_close']` 标记每日最后一根，止损和分批逐根运行，日线跟踪/加码/持有期限在日末执行，融资费用每日一次。省略这些字段仍按原日线模式，R74 数值已精确复现。`px['mark']` 只用于以前一已知收盘估值，不能用作可成交 OHLC。调用者必须提供因果入场和当时可知的指标，不会自动消除输入中的未来信息。

2026-11-01 时点修正：同一根 K 线的盘中候选先按既有优先级批量检查资金与持仓上限，再处理这批新仓的当根止损；不能用第一笔后来止损释放的资金或名额回头开同批下一笔。仅盘中成交可携带当根止损；若盘中成交价恰好等于该根收盘价，调用者须将该 kind 列入 `intraday_kinds`，否则会报错。对于不同时间触发的限价单，这只是保守的批次资金占用近似，日 K 不能证明跨股票成交先后。修正前含多个同根盘中候选的历史账户和看板回放可能受影响，须在原数据及配置下重算；Martin AH 的对照见 [续研 CC](../martin_luk/notes/PREREG_STRONG.md)。修正后已核对 Martin U1 / AJ1 / R74 的逐年收益与开仓数，不能据此推断其他交易员未受影响。

`audit=True` 返回逐笔入场、加码、退出的时间/价格/股数。`ret` 保留除以初始名义本金的历史口径；`ret_invested` 改除以初始及加码累计投入，仅为统计补充，不改变交易或账户收益。交易接口仍不属于本模块。

可选`Rules.max_new_long`按交易日统计成功新开多头，不按输入信号数统计；已有持仓、非法止损或资金不足不占名额，入场当天止损仍占一次，空头不受此参数限制。默认0不设此限制；旧调用者的信号截断仍由调用者自己决定。

`arm_trail_on_entry=True`允许用入场当根已知的均线和完成收盘激活均线跟踪，次日首次跌破即可退出；不改变初始止损，缺失均线不取未来值。默认False保留旧行为。

`stop_ema_only=True` 是默认关闭的研究选项：须指定存在的 `trail` 和 `[0,1)` 内的 `stop_ema_buffer`，只按保护止损退出，不额外在收盘穿越均线时退出。均线保护线在已完成收盘后更新，从后续 K 线生效；配合 `arm_trail_on_entry=True` 时，收盘入场可在入场收盘后设置首条线。当前此模式只支持收盘入场，盘中入场会报错。两项和缓冲均可按 `management_by_kind` 设置；看板显示实际止损，不把均线误报为收盘退出线。现有登记配置没有启用此选项。

可选`feedback_opened`将风险反馈改为最近成功开仓（含已平仓）的前日已实现/未实现R值，每交易日开头冻结；默认仍用旧的平仓序列。只保留固定长度队列，不加载额外行情。

`exit_signal_cancel_add=True` 是默认关闭的研究选项：多头在已安排信号收盘全退出的当日，不再执行普通 R 档或信号式收盘加仓，既有止损、盘中分批及退出顺序保持原样。调用者必须自行确保退出信号在加仓决策前已知；该开关不会将当日收盘才知道的信号变成可提前执行的指令。新增字段会改变 `Rules` 序列化摘要，即使默认关闭也不能将新旧摘要差异直接当作成交行为变化。

`add_after_entries=True` 是默认关闭的研究选项：收盘新仓先于仍在持有的旧仓收盘加仓使用资金；当日已退出的旧仓不会再加仓。它改变同日资金竞争，不保证收盘信号可在该收盘成交。当前登记配置未启用；新增字段会改变 `Rules` 序列化摘要。

可选`management_by_kind`按入场kind固定单仓的仓位上限、分批、均线和加仓政策；账户现金、反馈、总杠杆仍共享。随机入场保留原执行政策后换股票，是给定政策的选股对照。

空头新增的默认关闭字段（单测 `tests/test_borrow.py`、`tests/test_short_targets.py`、`tests/test_shorts.py`）：`borrow_rate`（年化借券费，按前一收盘的空单市值每个交易日计提一次，计入该笔盈亏）、`short_targets` / `short_target_frac`（空单跌到前一日的某条线回补，开盘就在下方按开盘价；止损日先止损，除非开盘已在目标下方）、`short_trim_day` / `short_trim_day_frac`（入场后第 N 天收盘有盈利回补一部分）。默认关闭时所有已登记系统的结果逐位不变（2026-10-19 `compare run us,hk` 前后核对）。

```bash
/opt/opend-us-options/.venv/bin/python -m unittest discover -s studies/trader_replication/tests -t .
```

2026-10-18 通用版自测（`martin.py`，R74 配置，引擎已含下面两组新字段）：`diagnose`、三市场 `final`、`robust` 的输出与已提交的 `diagnose_r74.json`、`final_system_r74.json`、`robust_r74.json` 逐项一致（数值相对误差 < 1e−9）。

新增默认关闭的 `Rules` 字段（执行时点单测 `tests/test_day_trim_signal_add.py`）：`trim_day` / `trim_day_frac` / `trim_day_profit` / `trim_day_breakeven`（入场后第 N 个交易日收盘减仓，可只在盈利时、可随后把止损提到成本；Qullamaggie“3–5 天卖 1/3–1/2”）；`add_signal` / `add_signal_frac` / `add_signal_max` / `add_signal_stop`（持仓出现新的买点信号时在收盘加仓，入场当天不加，止损可不动 / 提到成本 / 提到加仓日低点；Flanders“新买点加仓”）。

```bash
PY="nice -n 19 env OPENBLAS_NUM_THREADS=1 PYTHONUTF8=1 /opt/opend-us-options/.venv/bin/python"
$PY -m studies.trader_replication.martin diagnose r74.json && $PY -m studies.trader_replication.martin final r74.json
$PY -m studies.trader_replication.martin robust r74.json && $PY -m studies.trader_replication.martin check
```

2026-10-20 新增默认关闭的 `Rules` 字段（单测 `tests/test_day_trim_signal_add.py`、`tests/test_common.py`）：`add_signal_profit`（新买点加仓只在收盘高于成本时做）、`max_new_by_kind`（某些形态单独计每天成功新开多头数，不占 `max_new_long`）。`trader_screens.screens.Feat.floor`（只在 `common` 的 `floor` 开关的那次 build 里设上）。默认关闭时已登记 7 套在美股、港股的结果逐位不变（`compare run us,hk` 前后核对）。
