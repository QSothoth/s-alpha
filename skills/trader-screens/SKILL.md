---
name: trader-screens
description: 交易员看板：假设研究过的交易员此刻在美股 / 港股 / A 股里交易，每人用研究里登记的同一套系统（与横向比对表相同），今天买了什么（只有他按自己的节奏真会下单的几笔）、卖了什么、手里拿着什么、持仓的离场线在哪，以及几个人之间的交集（同一天都买、同时持有、持仓集中的行业）。目前有 Martin Luk、Christian Flanders、Clement Ang、Qullamaggie、Oliver Kell（多空一体，已冻结）、Mark Minervini（B 级基线）和 Marios Stamatoudis（研究版）。用于“看看这些交易员今天在做什么”“更新看板”“这周他们买了什么”“几个人都在拿哪些票”；研究、逼近和冻结新交易员用 trader-replication；不做单股技术判断、不下单、不接 custody。
---

# 交易员看板（trader-screens）

工程为 `/opt/opend-us-options`，沿用根及 `studies/AGENTS.md`。代码在 `studies/trader_screens/`；每位交易员的规则、账户怎么取舍、出处和研究者取值见 [SCREENS_CN](references/SCREENS_CN.md)。

数据层、门禁与横向比对统一按 [TRADER_PROTOCOL_CN](../../docs/TRADER_PROTOCOL_CN.md)：所有交易员用同一份数据集 `trader-data-v1`、同一评测区间和同一引擎，结果先过工程门禁（数据版本、不看未来、成交价在当日区间内、胜率 ≤ 35%），好坏由人对照比对表判断。

看板回答一个问题：如果这些人现在就在这个市场里交易，今天各自会做什么。一个人一天的买点可能有几十上百个，看板不列这些，只列他按自己的仓位规则真会下单的那几笔：每天最多开几笔、同时拿几只、单只多大、先买哪个。

输出是“按这些规则此刻会怎么做”，不是投资建议或订单；按研究约定只做模拟或小资金跟踪。

## 每位交易员只有一份系统

看板上的每位交易员，就是 `studies/trader_replication/systems.py` 登记的那个版本：和横向比对表同一份配置、同一个引擎、同一套账户规则，由 `studies/trader_replication/runner.py` 从 2024-01-02 回放到最新收盘。看板自己不再有买点或账户逻辑。

| 状态 | 现在有谁 | 能信到什么程度 |
|---|---|---|
| 已冻结（多空一体，2026-10-20 用户认可） | Martin Luk（R74 + S7）、Christian Flanders（R15 C4 + C1C + S4）、Clement Ang（R15 AA3 + C4A + S5）、Qullamaggie（R11 N3 + S7 + P1B：2026-10-21 加他的每笔 0.5% 风险、亏后与弱市减半）、Oliver Kell（R6 A5 + S5） | 到冻结日 2026-10-16 为止全是样本内，之后是唯一的样本外；空头只在美股（港股、A 股不适用，只跑多头），按 [TRADER_PROTOCOL_CN 第 5 节](../../docs/TRADER_PROTOCOL_CN.md) 的门禁 v2 选出；Qullamaggie 的多头同时换成了 R11 N3（+2R 才保本，偏离原话）；Flanders 的合计改善偏弱。各人结论在 `studies/<id>/notes/SHORTS_CONCLUSION_CN.md`；2026-10-20 起 Flanders 加 C1C（当天 EP 先买）、Clement 加 C4A（EP 另计每天 1 笔），见 `studies/trader_replication/reports/COMMON_RESULTS_CN.md`（2026 段是看过结果后放宽门槛才通过的，不再是独立检验） |
| B 级基线 | Mark Minervini（R0b，只做多） | 台账不够，按原话的基线系统；空头基线没通过 |
| 研究版（2026-10-20 用户同意放进看板，未冻结） | Marios Stamatoudis（R1 L4 + C4B + S1 P4） | B 级台账（有日期 19 笔）；只在选择段 2024–2025 逐轮选择，2026 验证段 R1 L4 + P4 −4.3%、未跑赢同池随机入场（排位 0.33），2026-10-20 加 C4B（EP 另计每天 2 笔）后 −0.4%（排位 0.52）；选择段利润约九成来自 ABVX、INBX 两笔；结论在 `studies/marios_stamatoudis/reports/FINAL_CN.md` |

空单在看板上写成“卖空 X 价格，涨破 Y 回补”，持仓表的方向列标“空”，离场线写成“涨破 X 回补 · 收盘站上某线回补”。live 数据遇到除权会把冻结日以前的价格重新复权，回放核对可能出现 1e-9 量级的浮点差，被标成“不一致”，这不是行为变化（冻结数据上回放完全一致）。

研究里改出更好的配置，就在 `systems.py` 登记新版本，看板自动跟着变；冻结要用户同意，前向记录从新版本的冻结日重算。不要在看板里改规则来“让账户好看”。每次运行都把回放截到冻结日，与比对表逐年核对，不一致会在看板上标出。

## 运行

```bash
cd /opt/opend-us-options
PY="nice -n 19 env OPENBLAS_NUM_THREADS=1 PYTHONUTF8=1 /opt/futu-opend/venv/bin/python"
$PY -m studies.trader_screens.scan refresh us                # 把数据补到最新收盘：us / hk / cn
$PY -m studies.trader_screens.scan run us                    # 某个市场今天的看板（终端 + Markdown；会先补数据）
$PY -m studies.trader_screens.scan run hk
$PY -m studies.trader_screens.scan run cn
$PY -m studies.trader_screens.scan board                     # 把三个市场最新一次 run 合成 board.md
$PY -m studies.trader_screens.scan run us --days 5           # 这周的买卖（持仓仍是最新一天）
$PY -m studies.trader_screens.scan industry hk               # 补行业名（OpenD，不扣额度）
$PY -m studies.trader_screens.scan run us --mode frozen      # 只用冻结的研究数据（截至 2026-10-16）
$PY -m studies.trader_screens.scan run us --provisional      # 盘中临时：收盘前约 10 分钟，给出尾盘要买、要卖的单子
$PY -m studies.trader_screens.scan diff us 2026-10-21        # 收盘后：盘中临时结果对照正式结果
```

**盘中模式**（`studies/trader_screens/intraday.py`，报告 [INTRADAY_CN](../../studies/trader_screens/reports/INTRADAY_CN.md)）
- 为什么：所有系统都在 T 日收盘确认、按收盘价成交、止损在 T 日低点；改成次日开盘买，收益大幅退化（X1 轮）。所以要在收盘前跑、尾盘执行。
- 怎么跑：先在开盘前用 `refresh` 把数据补到上一交易日，收盘前约 10 分钟运行 `run <市场> --provisional`。它只取一次快照，7 个系统共用；把快照当作今天的临时日 K 接在已存数据后面，不写数据，也不进面板缓存。结果单独存成 `out/<市场>_<日期>_provisional_<HHMM>.json` 和 `board_<市场>_<日期>_provisional_<HHMM>.md`，看板顶部标“盘中临时”，并列出尾盘单子：买入、卖空、加码、卖出、回补，卖出包括破跟踪线。
- 拒绝运行的情况：
  - 非交易日、开盘前、已收盘（半日市按提前收盘算）；
  - 已存数据不是到上一交易日为止（先 `refresh`）；
  - 快照不是今天的（OpenD 的报价时间；新浪只有时刻，要在 15 分钟内，午休除外）；
  - 快照的昨收与我们存的收盘对不上（< 95%）。
- A 股：收盘价在涨停价的买单标“涨停，收盘买不到，跳过”。系统本身不改，名额不顺延。
- 收盘后照常 `run <市场>`，再用 `diff` 分成一致、收盘后消失、尾盘漏掉三类，给出成交价差和止损宽度差。
- 实测合计耗时：美股约 51 秒、港股约 10 秒、A 股约 148 秒（新浪快照占 2 分钟）。建议开始运行的时点：美股 15:45 ET（收盘竞价单的收单截止：NYSE 约 15:50）、港股 15:50、A 股 14:50（不晚于 14:52）。
- 快照的价格、成交量都按原值用，不放大。I1-lite 测试中，美股 15:50 的买入一致 81%、卖出一致 94%，差异几乎都来自收盘价还在动；按市场占比补齐成交量对买卖没有改善。A 股没测信号差异。详见 INTRADAY_CN。
- `board` 只合成正式的日看板，不收盘中临时结果。

**数据**（统一接口 `studies/trader_data`，见 [TRADER_PROTOCOL_CN](../../docs/TRADER_PROTOCOL_CN.md) 第 4 节）
- 看板默认 live：冻结的 Release `trader-data-v1` 加本地增量缓存 `data/trader-live/trader-data-v1/<市场>/`，和复刻研究用同一份底座、同一个面板构建、同一份名单（美股 3433、港股 505、A 股 1697 只）。
- `run` / `refresh` 只补缺的交易日：只缺一个已收盘的交易日时，对整份名单取一次快照（美股、港股 OpenD `get_market_snapshot`，A 股新浪列表），几十秒；缺好几天或今天已开盘时，按名单重读这段历史（美股约 20–30 分钟）。都不扣历史 K 线额度，需要 OpenD 在线（A 股的交易日历也来自 OpenD）。复权比例由交易所的昨收价推出。增量只追加，不改底座。
- 用户要看板即视为同意这次补数；不启动后台或定时采集；不和 trend-market-scan 的取数同时跑（OpenD 订阅上限 300）。
- `--folder` 仍可读其他按 fetch 格式存放的目录（原样读取，不补数）。

**运行与发布**
- 面板按数据摘要缓存在 `data/trader-data/cache/`，数据变了自动重建；之后美股约 10 秒，港股、A 股几秒，单进程即可。
- 结果写 `data/trader-screens/out/`：`<市场>_<日期>_<天数>d.json` 和单市场的 `board_<市场>_<日期>_<天数>d.md`。
- 交付物是 Markdown 文档：`board` 把三个市场最新一次的日看板合成 `data/trader-screens/out/board.md`（每次覆盖），并另存 `board_<日期>.md` 留档。收盘后依次 `run us` / `run hk` / `run cn`（会先补数据）→ `board`，把 `board.md` 交给用户。不另做网页。

## 怎样读看板

**每个市场一节**
- 一句市况：股票池等权指数在 20 / 50 EMA 上方还是下方。
- **一览表**：每人一行，版本（已冻结 / 研究中 / B 级基线）、仓位、今天市况（可开新仓 / 不开新仓 / 无过滤）、账户收益与回撤（自 2024-01-02）、冻结日后的收益、今天的买卖。
- **交集**：只在有时列出多人同一天买入、多人同时持有的票。这几个人的规则本来相近，重合高有一部分是规则相似造成的。
- **各人明细**：只给今天有买卖或有持仓的人。买卖各一行（买点、价格、止损、仓位 / 卖出原因、价格、盈亏），“另有 N 个买点没做”是当天因名额、持仓数、仓位或市况没买的信号；持仓表列出盈亏、仓位和**明天的离场线**：止损 · 破跟踪线（已激活时）· 下一个分批价 · 第 N 天分批（还剩几天）· 加码价，由引擎直接给出。

**末尾**：回放核对一句（到冻结日的分年收益与比对表一致；不一致的会在对应市场里标出），以及折叠的各系统规则（选股与形态｜入场与止损｜离场｜仓位与市况）。

**执行时点**：所有系统都是收盘价买卖，“今天买入 / 卖出”是收盘那一刻的操作；收盘后才看到时实际只能次日处理，而次日开盘买会让收益大幅退化（X1 轮）。要按系统执行，用盘中模式（`run --provisional`）在收盘前拿到单子、尾盘下单。

## 不做的事

- 不在这里改规则、调门槛、加主观过滤；想改按 trader-replication 预登记。
- 不把看板上的回放收益当成他们方法的检验（样本内），也不把“多人同时持有”当成更高胜率的结论。要评估，就把每天的 `out/*.json` 留着（只在用户运行时写入，不做定时采集），攒够后按 trader-replication 的口径评估。
- 不做空：几个人的空头形态（Qullamaggie 的 parabolic short、Kell 的 Wedge Drop 和反向 EMA Crossback）没有写；Martin 的研究里五轮空头都不如不做。

## 新增一位交易员

按 trader-replication 建研究模块（`studies/<名字>/replicate.py`），在 `studies/trader_replication/systems.py` 登记版本即可，看板和比对表会同时出现他。`screens.py` 里的 `Screen` 子类是按原话的买点定义，研究模块可以直接引用；`tests/test_screens.py` 的“不看未来”检验会自动覆盖它们。
