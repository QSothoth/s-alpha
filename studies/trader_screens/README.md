# trader_screens：交易员看板

使用说明见 [skills/trader-screens](../../skills/trader-screens/SKILL.md)。只读，不接 custody。看板上每位交易员就是 [`studies/trader_replication/systems.py`](../trader_replication/systems.py) 登记的系统，由 [`runner.py`](../trader_replication/runner.py) 运行，和横向比对表是同一份实现；数据经 [`studies/trader_data`](../trader_data/README.md)（默认 live）。

| 文件 | 内容 |
|---|---|
| `scan.py` | 命令行 `list` / `refresh` / `run` / `board` / `industry` / `diff`：每个登记系统在一个市场上今天的买卖、持仓与离场线，交集与行业；结果写 `data/trader-screens/out/`；`run --provisional` 是盘中模式 |
| `intraday.py` | 盘中模式：只取一次快照，接成今天的临时日 K（不写盘），7 个系统共用；各种拒绝检查；A 股涨停跳过；`diff` 对照收盘后的正式结果 |
| `minute.py` | 全名单 5 分钟线一次性取数（OpenD `get_cur_kline` / 新浪，不扣额度）与截点汇总，供 `intraday_study.py` 使用 |
| `intraday_study.py` | 临时日 K 与收盘日 K 的信号差异研究 I1-lite 与开盘后截点（预登记 `notes/INTRADAY_PREREG_CN.md`，报告 `reports/INTRADAY_CN.md`） |
| `intraday_i2.py` | I2：每市场 20 个交易日（含 A 股、本地子集日）与截点时已知信息的全天成交量估算 E0–E4（预登记 `notes/INTRADAY_I2_PREREG_CN.md`） |
| `confidence.py` | I3 盘中置信度（共用，研究与实时）：交易时间换算、以时间为输入的全天量模型 VG / VQ、情景 K 线、多情景快速重算 `decide_many`、候选特征、成立概率模型 PL / PG、两栏阈值、`live`；模型 `reports/confidence_model.json`（判定未启用：`integrate: false`） |
| `intraday_i3.py` | I3 研究：分钟线会话、训练 / 选择 / 验证日、全天量拟合与选择、按天续跑的情景重算、概率模型与验证（预登记 `notes/INTRADAY_I3_PREREG_CN.md`） |
| `board.py` | 把一个或多个市场的结果写成 Markdown 看板（`board.md`）的模板；盘中结果顶部标“盘中临时”并列尾盘单子（有启用的置信度模型时另列“下单 / 观察”两栏） |
| `screens.py` | 共用日 K 特征（只用当天及以前）和按原话写的买点定义（研究模块引用），以及档案里的账户规则记录 `book` |
| `data.py` | OpenD 行业名缓存；旧的按目录取数与面板函数（委托给 `studies/trader_data`） |

```bash
nice -n 19 env OPENBLAS_NUM_THREADS=1 /opt/futu-opend/venv/bin/python -m unittest discover -s studies/trader_screens/tests -t .
```
