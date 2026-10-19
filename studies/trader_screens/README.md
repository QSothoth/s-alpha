# trader_screens：交易员看板

使用说明见 [skills/trader-screens](../../skills/trader-screens/SKILL.md)。只读，不接 custody。看板上每位交易员就是 [`studies/trader_replication/systems.py`](../trader_replication/systems.py) 登记的系统，由 [`runner.py`](../trader_replication/runner.py) 运行，和横向比对表是同一份实现；数据经 [`studies/trader_data`](../trader_data/README.md)（默认 live）。

| 文件 | 内容 |
|---|---|
| `scan.py` | 命令行 `list` / `refresh` / `run` / `board` / `industry`：每个登记系统在一个市场上今天的买卖、持仓与离场线，交集与行业；结果写 `data/trader-screens/out/` |
| `board.py` | 把一个或多个市场的结果写成 Markdown 看板（`board.md`）的模板 |
| `screens.py` | 共用日 K 特征（只用当天及以前）和按原话写的买点定义（研究模块引用），以及档案里的账户规则记录 `book` |
| `data.py` | OpenD 行业名缓存；旧的按目录取数与面板函数（委托给 `studies/trader_data`） |

```bash
nice -n 19 env OPENBLAS_NUM_THREADS=1 /opt/futu-opend/venv/bin/python -m unittest discover -s studies/trader_screens/tests -t .
```
