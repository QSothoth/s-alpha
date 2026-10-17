# trader_replication：逼近一位交易员的通用代码

使用说明见 [skills/trader-replication](../../skills/trader-replication/SKILL.md)，第一个例子在 [martin_luk/](../martin_luk/README.md)。只读研究，不接 custody。

| 文件 | 内容 |
|---|---|
| `ledger.py` | 交易台账 CSV 的读取、校验（日期精度 exact / chart / window）、按日期切选择段 / 验证段 |
| `fidelity.py` | 某环节的输出（天 × 股票的布尔掩码）命中台账交易的比例、同宽随机命中率、提升倍数、名单宽度、累积漏斗 |
| `edge.py` | 同一天、同一波动分组里选中 vs 没选中的同类事件的结果差（按日重抽样区间）；次日开盘起的远期收益 |
| `system.py` | 多空日 K 组合：收盘确认入场、固定风险定仓、分批、EMA 跟踪、次日无延续离场、反馈降风险、当天盘中止损；安慰剂（同一天同一名单随机换股、同样止损宽度） |

```bash
/opt/futu-opend/venv/bin/python -m unittest discover -s studies/trader_replication/tests -t .
```
