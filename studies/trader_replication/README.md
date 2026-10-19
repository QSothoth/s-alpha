# trader_replication：逼近一位交易员的通用代码

使用说明见 [skills/trader-replication](../../skills/trader-replication/SKILL.md)（研究过程）；冻结后的系统和各交易员的筛选在 [skills/trader-screens](../../skills/trader-screens/SKILL.md)（代码 `studies/trader_screens/`），第一个例子在 [martin_luk/](../martin_luk/README.md)。只读研究，不接 custody。

| 文件 | 内容 |
|---|---|
| `ledger.py` | 交易台账 CSV 的读取、校验（日期精度 exact / chart / window）、按日期切选择段 / 验证段 |
| `fidelity.py` | 某环节的输出（天 × 股票的布尔掩码）命中台账交易的比例、同宽随机命中率、提升倍数、名单宽度、累积漏斗 |
| `edge.py` | 同一天、同一波动分组里选中 vs 没选中的同类事件的结果差（按日重抽样区间）；次日开盘起的远期收益 |
| `study.py` | 通用复刻流程（`Study` 基类）：新交易员只写自己的 `arrays` / `build`（环节掩码）和 `notes/rounds/R*.json`；`round`（候选 + 门槛 + 目标，从不带入更差的配置，自动写否定登记表和记分板）、`diagnose`（他的每笔卡在哪一步）、`robust`、`final`（三市场）、`three`（三层对照）。命令：`python -m studies.<id>.replicate round R3` 等 |
| `negations.py` | 否定登记表 `notes/NEGATIONS.json` / `NEGATIONS_CN.md`：没带入的候选连同当时的基础配置；`stale` 列出基础配置已变、需要重测的行 |
| `martin.py` | 用 Martin Luk 的 `replicate.py` 走通用流程的适配和自测：只读 `studies/martin_luk`，输出写 `data/trader-replication-selftest/`；`check` 与已提交的 R74 报告逐项比较 |
| `panels.py` | 研究用的日 K 数组，经统一数据接口 [`studies/trader_data`](../trader_data/README.md) 取得（默认冻结 Release `trader-data-v1`）；公共评测区间 `WINDOW`；`upto` 截面板供不看未来检查；`DATA_PIN.json` 固定各版本的数据摘要（`python -m studies.trader_replication.panels pin`）。规范见 [TRADER_PROTOCOL_CN](../../docs/TRADER_PROTOCOL_CN.md) |
| `systems.py` | 登记的交易员系统：每人一份（研究模块 + 带入配置 + 版本 + 状态 + 冻结日），比对、看板、实际运行都只读这里 |
| `runner.py` | 一个系统在一个市场上回放到最新一天：账户、当天买卖、没做的买点、持仓与引擎给出的离场线；回放截到冻结日与比对表核对。`python -m studies.trader_replication.runner us live` |
| `gate.py` | 工程门禁：数据版本与区间、不看未来（截面板前后决定一致）、成交价在当日区间内、胜率 ≤ 35%；单测 `tests/test_gate.py` |
| `compare.py` | 各交易员当前配置在统一数据层上的三市场横向比对与门禁，写 `reports/compare.json`、`reports/COMPARISON_CN.md`：`python -m studies.trader_replication.compare run [us,hk,cn] [交易员 ...]` |
| `system.py` | 多空日 K 组合：收盘确认入场、固定风险定仓、分批（按 R / 按信号）、EMA 跟踪（分批后或回撤 / 指定市场日换另一条）、保本、信号全卖、加码（一档或多档，止损提到成本价）、次日无延续离场、新仓反馈调风险、按日风险倍数、同时持仓上限、当天盘中止损；安慰剂（同一天同一名单随机换股、同样止损宽度）。新规则都在 `Rules` 里、默认关闭 |

`simulate` 可接收真实分钟 OHLC：`px['session']` 是交易日编号，`px['daily_close']` 标记每日最后一根，止损和分批逐根运行，日线跟踪/加码/持有期限在日末执行，融资费用每日一次。省略这些字段仍按原日线模式，R74 数值已精确复现。`px['mark']` 只用于以前一已知收盘估值，不能用作可成交 OHLC。调用者必须提供因果入场和当时可知的指标，不会自动消除输入中的未来信息。

`audit=True` 返回逐笔入场、加码、退出的时间/价格/股数。`ret` 保留除以初始名义本金的历史口径；`ret_invested` 改除以初始及加码累计投入，仅为统计补充，不改变交易或账户收益。交易接口仍不属于本模块。

可选`Rules.max_new_long`按交易日统计成功新开多头，不按输入信号数统计；已有持仓、非法止损或资金不足不占名额，入场当天止损仍占一次，空头不受此参数限制。默认0不设此限制；旧调用者的信号截断仍由调用者自己决定。

`arm_trail_on_entry=True`允许用入场当根已知的均线和完成收盘激活均线跟踪，次日首次跌破即可退出；不改变初始止损，缺失均线不取未来值。默认False保留旧行为。

可选`feedback_opened`将风险反馈改为最近成功开仓（含已平仓）的前日已实现/未实现R值，每交易日开头冻结；默认仍用旧的平仓序列。只保留固定长度队列，不加载额外行情。

可选`management_by_kind`按入场kind固定单仓的仓位上限、分批、均线和加仓政策；账户现金、反馈、总杠杆仍共享。随机入场保留原执行政策后换股票，是给定政策的选股对照。

```bash
/opt/futu-opend/venv/bin/python -m unittest discover -s studies/trader_replication/tests -t .
```

2026-10-18 通用版自测（`martin.py`，R74 配置，引擎已含下面两组新字段）：`diagnose`、三市场 `final`、`robust` 的输出与已提交的 `diagnose_r74.json`、`final_system_r74.json`、`robust_r74.json` 逐项一致（数值相对误差 < 1e−9）。

新增默认关闭的 `Rules` 字段（执行时点单测 `tests/test_day_trim_signal_add.py`）：`trim_day` / `trim_day_frac` / `trim_day_profit` / `trim_day_breakeven`（入场后第 N 个交易日收盘减仓，可只在盈利时、可随后把止损提到成本；Qullamaggie“3–5 天卖 1/3–1/2”）；`add_signal` / `add_signal_frac` / `add_signal_max` / `add_signal_stop`（持仓出现新的买点信号时在收盘加仓，入场当天不加，止损可不动 / 提到成本 / 提到加仓日低点；Flanders“新买点加仓”）。

```bash
PY="nice -n 19 env OPENBLAS_NUM_THREADS=1 PYTHONUTF8=1 /opt/futu-opend/venv/bin/python"
$PY -m studies.trader_replication.martin diagnose r74.json && $PY -m studies.trader_replication.martin final r74.json
$PY -m studies.trader_replication.martin robust r74.json && $PY -m studies.trader_replication.martin check
```
