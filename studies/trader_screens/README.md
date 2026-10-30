# trader_screens：交易员看板

使用说明见 [skills/trader-screens](../../skills/trader-screens/SKILL.md)。只读，不接 custody。看板上每位交易员就是 [`studies/trader_replication/systems.py`](../trader_replication/systems.py) 登记的系统，由 [`runner.py`](../trader_replication/runner.py) 运行，和横向比对表是同一份实现；数据经 [`studies/trader_data`](../trader_data/README.md)（默认 live）。

当前七套策略的方法论、执行及证据审查见 [2026-10-25 审查报告](reports/STRATEGY_REVIEW_20261025_CN.md)，附可复跑的微型用例与冻结美股候选核查；报告记录问题，不代表已修复。

| 文件 | 内容 |
|---|---|
| `scan.py` | 命令行 `list` / `refresh` / `run` / `board` / `industry` / `diff`：每个登记系统在一个市场上今天的买卖、持仓与离场线，交集与行业；结果写 `data/trader-screens/out/`；`run --provisional` 是盘中模式 |
| `intraday.py` | 盘中模式：只取一次快照，接成今天的临时日 K（不写盘），7 个系统共用；各种拒绝检查；A 股涨停跳过；`diff` 对照收盘后的正式结果 |
| `minute.py` | 全名单 5 分钟线一次性取数（OpenD `get_cur_kline` / 新浪，不扣额度）与截点汇总，供 `intraday_study.py` 使用 |
| `intraday_study.py` | 临时日 K 与收盘日 K 的信号差异研究 I1-lite 与开盘后截点（预登记 `notes/INTRADAY_PREREG_CN.md`，报告 `reports/INTRADAY_CN.md`） |
| `intraday_i2.py` | I2：每市场 20 个交易日（含 A 股、本地子集日）与截点时已知信息的全天成交量估算 E0–E4（预登记 `notes/INTRADAY_I2_PREREG_CN.md`） |
| `confidence.py` | I3 盘中置信度（共用，研究与实时）：交易时间换算、以时间为输入的全天量模型 VG / VQ、情景 K 线、多情景快速重算 `decide_many`、候选特征、成立概率模型 PL / PG、两栏阈值、`live`；模型 `reports/confidence_model.json`（判定未启用：`integrate: false`） |
| `intraday_i3.py` | I3 研究：分钟线会话、训练 / 选择 / 验证日、全天量拟合与选择、按天续跑的情景重算、概率模型与验证（预登记 `notes/INTRADAY_I3_PREREG_CN.md`） |
| `intraday_recheck.py` | 2026-10-23 修复后的描述复测：固定输入副本与 SHA256、全名单逐日覆盖、日 K 核对、完整历史回放、V0–V3 前后半段比较；已有日期不算全新盲测 |
| `focus.py` | Markdown、本机 HTML 和图片共用的逐股聚合：以已有持仓和成交记录计算共同持有、同日多人新开、新开加入老持仓、退出与持有并存、多空分歧；不取数、不改策略 |
| `aggregation.py` | 跨股票行业、概念、入场形态、量价与风险特征的关系判定；两人两股门槛、阶段与方向分列、成员去重、证据与覆盖率 |
| `context.py` | 复用已有面板的有界窗口特征；日报用收盘，盘中用原始快照；补充旧日报仅允许数据摘要一致的本地面板，不取数 |
| `board.py` | 把一个或多个市场的结果写成 Markdown 看板（`board.md`）：先按股票比较，再展开交易员账户与持仓明细；盘中价格与执行时点单独折叠 |
| `screens.py` | 共用日 K 特征（只用当天及以前）和按原话写的买点定义（研究模块引用），以及档案里的账户规则记录 `book` |
| `data.py` | OpenD 行业名缓存；旧的按目录取数与面板函数（委托给 `studies/trader_data`） |

日报 JSON 同时提供图表输入。每位交易员的 `equity_history` 是同一次账户回放的日净值；`presentation.market_curve` 是与市况判断相同的股票池等权指数；`presentation.stocks` 按代码提供相关标的的收盘价和现有名称、行业简介。曲线只保留截至日报日期的最近 61 个收盘点，用于计算近 60 个交易日变化；窗口内缺价时返回空曲线。展示程序直接消费这些字段，无需另行回放账户或维护标的名单。

本机图片入口 `research/trader_board_cards.py` 读取同一份日报，生成逐股摘要与明细图片，并输出可折叠的 `board.html`、`board.md` 和逐股聚合结果 `comparison.json`。聚合结果保留对应交易员、原始持仓 / 动作和标签，方便逐项核对；不把未执行候选当作新开仓。HTML 和 Markdown 内的“共性怎么筛选”列明判定条件与排序口径。

跨股票共性同时展示在日报和美股开盘后 1 小时的单图中，共用 `aggregation.py`。行情标量与覆盖率保存在 `presentation.aggregation`，本机日报另输出完整的 `aggregation.json`。盘中累计量不与全天量混算，旧快照未保存的成交量保持缺失。门槛、分母、首页选择和缺失处理见[聚合口径](../../skills/trader-screens/references/AGGREGATION_CN.md)。

```bash
nice -n 19 env OPENBLAS_NUM_THREADS=1 /opt/futu-opend/venv/bin/python -m unittest discover -s studies/trader_screens/tests -t .
```
