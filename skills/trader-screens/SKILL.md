---
name: trader-screens
description: 交易员看板：假设研究过的交易员此刻在美股 / 港股 / A 股里交易，按各自的规则和仓位限制，每人今天买了什么（只有他按自己的节奏真会下单的几笔）、卖了什么、手里拿着什么、明天关注什么，以及几个人之间的交集（同一天都买、同时持有、明天都在关注、持仓集中的行业）。目前有 Martin Luk（已复刻冻结）和 Qullamaggie、Clement Ang、Christian Flanders、Oliver Kell、Mark Minervini（按原话初版）。用于“看看这些交易员今天在做什么”“更新看板”“这周他们买了什么”“几个人都在拿哪些票”；研究、逼近和冻结新交易员用 trader-replication；不做单股技术判断、不下单、不接 custody。
---

# 交易员看板（trader-screens）

工程为 `/opt/opend-us-options`，沿用根及 `studies/AGENTS.md`。代码在 `studies/trader_screens/`；每位交易员的规则、账户怎么取舍、出处和研究者取值见 [SCREENS_CN](references/SCREENS_CN.md)。

看板回答一个问题：如果这些人现在就在这个市场里交易，今天各自会做什么。一个人一天的买点可能有几十上百个，看板不列这些，只列他按自己的仓位规则真会下单的那几笔：每天最多开几笔、同时拿几只、单只多大、先买哪个。

输出是“按这些规则此刻会怎么做”，不是投资建议或订单；按研究约定只做模拟或小资金跟踪。

## 两个等级

| 等级 | 现在有谁 | 账户怎么来 | 能信到什么程度 |
|---|---|---|---|
| 已复刻冻结 | Martin Luk（R74 配置，冻结日 2026-10-16） | trader-replication 逐环节逼近后冻结的规则账户，从 2024-01-02 回放 | 研究数字全是样本内；冻结日之后的表现是唯一的样本外 |
| 按原话初版 | Qullamaggie、Clement Ang、Christian Flanders、Oliver Kell、Mark Minervini | 按档案里本人公开的规则写买点和账户规则，从最近约半年（126 个交易日）前开始回放；档案没给的数字是研究者取值 | 没对照过他们的真实交易，也没检验过收益，只能当“他的思路大致会怎么做” |

初版就是 trader-replication 第 4 步里“每个环节都按原话的端到端粗版本”。要升级成已复刻：先收集他的交易台账、做三层对照、逐环节逼近，再冻结登记到 `frozen.py`。不要在这里改规则来“让账户好看”；规则改动属于研究，要预登记。

## 运行

```bash
cd /opt/opend-us-options
PY="nice -n 19 env OPENBLAS_NUM_THREADS=1 PYTHONUTF8=1 /opt/futu-opend/venv/bin/python"
$PY -m studies.trader_screens.scan refresh us                # 按需取数：us / hk / cn
$PY -m studies.trader_screens.scan run us                    # 某个市场今天的看板（终端 + Markdown）
$PY -m studies.trader_screens.scan run hk
$PY -m studies.trader_screens.scan run cn
$PY -m studies.trader_screens.scan board                     # 把三个市场最新一次 run 合成 board.md
$PY -m studies.trader_screens.scan run us --days 5           # 这周的买卖（持仓仍是最新一天）
$PY -m studies.trader_screens.scan industry hk               # 补行业名（OpenD，不扣额度）
$PY -m studies.trader_screens.scan run us --folder data/martin-luk-universe-us   # 研究数据（截至 2026-10-16）
```

**取数**
- `refresh` 是前台按需取数，走 OpenD `get_cur_kline`，不扣历史 K 线额度，需要 OpenD 在线；写入 `data/trader-screens/<市场当地日期>/<市场>`，中断后重跑会续传，收盘前取的、收盘后重跑会重取。
- 美股用自己的宽名单（现价 ≥ 1 美元、日均成交额 ≥ 200 万美元，约 3400 只），和 Martin 研究的股票面板同口径；按趋势扫描约 1400 只 30 分钟估算，要一个多小时。
- 港股、A 股用趋势扫描的名单（港股约 500 只，A 股约 1700 只）；当天 trend-market-scan 已经取过的，`run` 直接用它的数据。
- 用户要看板即视为同意这次取数；不启动后台或定时采集；不和 trend-market-scan 的取数同时跑（OpenD 订阅上限 300）；取数期间 OpenD 日志增长很快，注意磁盘。

**运行与发布**
- 第一次 `run` 会把日 K 建成面板缓存（`data/trader-screens/cache/`），之后美股约 10 秒，港股、A 股几秒，单进程即可。
- 结果写 `data/trader-screens/out/`：`<市场>_<日期>_<天数>d.json` 和单市场的 `board_<市场>_<日期>_<天数>d.md`。
- 交付物是 Markdown 文档：`board` 把三个市场最新一次的日看板合成 `data/trader-screens/out/board.md`（每次覆盖），并另存 `board_<日期>.md` 留档。每天收盘后依次 `refresh` → `run us` / `run hk` / `run cn` → `board`，把 `board.md` 交给用户。不另做网页。

## 怎样读看板

**一览表**：每个市场先给数据日期、股票池等权指数在 20 / 50 EMA 上方还是下方，再用一张表列出每人的仓位、今天买 / 卖几只、持仓几只和市况，一眼就能看出谁在进攻、谁空仓。

**交集**
- 今天被两人以上买入的、被两人以上同时持有的、明天两人以上都在关注的（明天关注只有初版有）。
- 持仓集中在哪些行业，谁在空仓。
- 这几个人的规则本来就相近（都看强势、收缩、新高），重合高有一部分是规则相似造成的，不等于多份独立的看好。

**每位交易员一节**
- **仓位与市况**：Martin 指数在 50 EMA 下方就不开新多；Kell 指数在 20 EMA 下方时风险减半。
- **账户成绩**：回放期间的收益、回撤、平仓笔数和胜率，只用来判断账户规则是否离谱，不是收益证据。
- **今天买入**：买点、买价、止损、仓位。“另有 N 个买点没做”是当天的其他信号，因为每天笔数、持仓数或仓位已满没有下单。
- **今天卖出**：原因有跌破止损、跳空跌破止损、分批、收盘跌破跟踪线，以及 Martin 的 +10R 卖 30%。
- **持仓**：买入日、成本到现价、盈亏、仓位，以及离场线（止损、跟踪线；Martin 另有分批价）。
- **明天关注**：待触发的买点按强度列前 5 个，带触发价。
- 每节末尾是他的账户规则；Martin 另有回放核对（到冻结日为止的分年收益应和研究报告一致，研究数据上完全一致）和冻结后的表现。

**日 K 近似**：几位初版交易员都在盘中按开盘区间或分钟线入场，看板用“越过触发价”或收盘价代替，止损用当日低点（至少离买价 1%）。所以“今天买入”是收盘后才知道的，只能记作模拟。

## 不做的事

- 不在这里改规则、调门槛、加主观过滤；想改按 trader-replication 预登记。
- 不把初版账户的回放收益当成他们方法的检验，也不把“多人同时持有”当成更高胜率的结论。要评估，就把每天的 `out/*.json` 留着（只在用户运行时写入，不做定时采集），攒够后按 trader-replication 的口径评估。
- 不做空：几个人的空头形态（Qullamaggie 的 parabolic short、Kell 的 Wedge Drop 和反向 EMA Crossback）初版没有写；Martin 的研究里五轮空头都不如不做。

## 新增一位交易员

- **初版**：在 `screens.py` 写一个 `Screen` 子类，包括买点（逐条注明档案出处，档案没给的数字标 `researcher`）和账户规则 `book`（每笔风险、每天笔数、持仓数、单只上限、离场），加进 `DRAFTS`。`tests/test_screens.py` 的“不看未来”检验会自动覆盖他；另外给他的主要买点写一个人造价格路径的触发日单测，最后在 SCREENS_CN 加规则卡。资料不足以写出可执行规则的，不造初版。
- **已复刻**：由 trader-replication 冻结后，在 `frozen.py` 加适配类（只调用该研究自己的函数），用研究数据回放，确认分年收益和报告完全一致，再加进 `REPLICATED`。持仓价位的回推（`position_state`）目前覆盖止损、按 R 分批、加码和一条收盘跟踪线，用了其他离场规则的系统会直接报错，要先扩展它和单测。
