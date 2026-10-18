# trader_screens：交易员看板

使用说明见 [skills/trader-screens](../../skills/trader-screens/SKILL.md)，逐人规则、账户与出处见 [SCREENS_CN](../../skills/trader-screens/references/SCREENS_CN.md)。只读，不接 custody。初版规则没有对照过交易员的真实交易，也没有检验过收益；升级走 [trader-replication](../../skills/trader-replication/SKILL.md)。

| 文件 | 内容 |
|---|---|
| `data.py` | 按需取数（美股自己的宽名单，港股 / A 股沿用趋势扫描名单并复用它当天的数据）、最新数据目录、稠密面板缓存（`data/trader-screens/cache/`）、OpenD 行业名 |
| `screens.py` | 共用日 K 特征（只用当天及以前）和按原话初版的交易员：买点（待触发 / 已触发）与账户规则 `book` |
| `book.py` | 初版账户：每天按强度取前几笔、按风险定仓、止损 / 分批 / 跟踪线离场，回放最近约半年 |
| `frozen.py` | 已复刻冻结的系统（Martin Luk R74）：调用 `studies/martin_luk` 自己的函数在新数据上重建规则账户 |
| `scan.py` | 命令行 `list` / `refresh` / `run` / `board` / `industry`：每人今天的买卖、持仓、明天关注，交集与行业；结果写 `data/trader-screens/out/` |
| `board.py` | 把一个或多个市场的结果写成 Markdown 看板（`board.md`） |

```bash
nice -n 19 env OPENBLAS_NUM_THREADS=1 /opt/futu-opend/venv/bin/python -m unittest discover -s studies/trader_screens/tests -t .
```
