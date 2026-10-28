# david_trullas：纳指期货日内（World Cup 季度赛）复刻

`trader-replication` 的第一个日内例子，2026-10-28。结论见 [reports/REPLICATION_CN.md](reports/REPLICATION_CN.md)，原话见 [notes/RULES_CN.md](notes/RULES_CN.md)，台账 [notes/trades.csv](notes/trades.csv)，预登记 `notes/PREREG_R1–R8.md` 与 `notes/rounds/`，否定记录 [notes/NEGATIONS_CN.md](notes/NEGATIONS_CN.md)。区间内研究结论，不接 custody、不当生产能力。

| 文件 | 内容 |
|---|---|
| `fetch.py` | QQQ 1 分钟（含盘前盘后）取数；只在 QQQ 30 天内已扣过历史额度时运行，输出 `data/trullas-qqq-k1/` |
| `data.py` | 读成按 ET 交易日分组的 numpy 数组（缓存 `k1.npz`） |
| `engine.py` | 分钟引擎：MACD 背离 + 斐波那契触发（及量能触发对照）、管理、按季度 $2,500 起步的复利账户、官方季度成绩表 |
| `replicate.py` | `round`（预登记轮次 + 同日随机入场安慰剂）、`validate`（验证段只评一次）、`three`（三层对照）、`robust` |
| `diag_r7.py` | R7 / R7+季初 300 倍 / 成本加倍的逐季诊断 |
| `tests/` | 执行时点与不看未来的单测（合成数据） |

```sh
/opt/futu-opend/venv/bin/python -m unittest discover -s studies/david_trullas/tests -t .
```
