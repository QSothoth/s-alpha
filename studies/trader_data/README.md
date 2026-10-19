# trader_data：交易员系统的统一数据接口

复刻研究（`studies/trader_replication`、各交易员的 `replicate.py`、横向比对）和实际运行（`studies/trader_screens` 看板、冻结系统）只通过这个包取日 K。规范见 [TRADER_PROTOCOL_CN](../../docs/TRADER_PROTOCOL_CN.md)。

| 文件 | 内容 |
|---|---|
| `__init__.py` | 入口：`load(market, mode=…)` 返回面板，`dataset(market, mode=…)` 返回数据集；开关 `TRADER_DATA_MODE=frozen\|live`（默认 frozen）、版本 `TRADER_DATA_TAG`（默认 `trader-data-v1`） |
| `dataset.py` | `Dataset` 抽象：固定名单与规则、不复权日 K、复权因子、摘要；`FolderDataset` 读 fetch 格式的目录（冻结 Release） |
| `live.py` | `LiveDataset`：冻结底座 + `data/trader-live/<版本>/<市场>/` 只追加的增量；`update()` 只补缺的已收盘交易日（缺一天且今天未开盘：一次快照；否则重读历史）；`Provisional`：盘中快照当临时收盘，不写盘 |
| `providers.py` | `Provider` 抽象：交易日历、全名单快照（含交易所昨收价）、历史重读；`OpenDProvider`（美股、港股）、`SinaProvider`（A 股）。新数据源加一个子类 |
| `panel.py` | 唯一的面板构建：按复权因子前复权、修正开收盘落在高低之外的坏 K 线；按数据集摘要缓存在 `data/trader-data/cache/` |

```bash
PY="nice -n 19 env OPENBLAS_NUM_THREADS=1 PYTHONUTF8=1 /opt/futu-opend/venv/bin/python"
$PY -c "from studies import trader_data as TD; print(TD.dataset('cn', 'live').update())"   # 补到最新收盘
$PY -m unittest discover -s studies/trader_data/tests -t .
```

live 增量的检查：快照的昨收价要和我们存的最后收盘价对得上（≥ 95% 的股票，否则说明快照不是预期那一天，停止）；重读历史时与已存最后一天的不复权收盘价比较（不一致超过 1% 的股票就停止）。对不上的昨收价记为当天的复权比例（2026-10-19 A 股 9 个除息，6 个与新浪复权因子相同，3 个差约万分之三，来自交易所参考价取整）。
