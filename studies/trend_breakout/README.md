# 日 K / 周 K 趋势研究（已收敛）

2026-10-12～15 的趋势研究已经收敛。结论、三个市场的最终方案、局限和经验见 [reports/CONCLUSIONS_CN.md](reports/CONCLUSIONS_CN.md)；历史各轮的预登记、报告、脚本和中间数据已移到仓库外 `/root/opend-us-options-archive-20261015/`。全部是同一段历史上的研究结果，不用于实盘。

## 最终方案一句话

- **A 股**：周线二买/三买，股票池指数站上 120 日线后第 1 周内买，52 周涨幅排序，5 只按风险定仓，跌破结构或大盘线就卖。
- **美股**：同样买点，站上 120 日线后 13 周内买，26 周涨幅排序，20 只等权。
- **港股**：波段；买点距 52 周高 ≤20%、越近越先买，5 只等权，跌破持有以来最高周低点或满 8 周就卖，不看大盘。

## 代码

| 文件 | 作用 |
|---|---|
| [final.py](final.py) | 三个市场的最终方案：取本地数据、股票池、周 K 买点、排序、仓位、回放、Alpha、数据末端的持仓与候选 |
| [scan.py](scan.py) | 全市场周扫描：按需取最新日 K，列下周候选、规则账户持仓、用户持仓止损/离场；技能 [trend-market-scan](../../skills/trend-market-scan/SKILL.md) |
| [run_final.py](run_final.py) | 回放一个市场并写 `reports/final_<market>.json`，与研究结果核对 |
| [chan.py](chan.py) | 周 K 聚合与简化缠论（包含、分型、笔、中枢、二买/三买），不追高账户 |
| [chips.py](chips.py) | 换手率、成本线、筹码分布获利盘（A 股，研究中未入选，保留为工具） |
| [backtest.py](backtest.py) / [portfolio.py](portfolio.py) | 逐行回测引擎（T+1 开盘成交、涨跌停、停牌、`exit_rows` 大盘离场、`max_hold`）与资金账户 |
| [signals.py](signals.py) / [panel.py](panel.py) / [pit.py](pit.py) | 指标、面板、A 股点时股票池 |
| [sources.py](sources.py) / [fetch.py](fetch.py) | 三个市场统一取数与数据集构建 |
| [reference.py](reference.py) | 逐笔参考实现，只供引擎测试对齐 |

## 运行与测试

```bash
OPENBLAS_NUM_THREADS=1 PYTHONUTF8=1 /opt/futu-opend/venv/bin/python -m studies.trend_breakout.run_final cn   # 或 us / hk
PYTHONUTF8=1 /opt/futu-opend/venv/bin/python -m unittest discover -s studies/trend_breakout/tests
```

全市场扫描见 [trend-market-scan](../../skills/trend-market-scan/SKILL.md)：`-m studies.trend_breakout.scan refresh|run cn|hk|us|all`，`refresh` 前台按需取数（美港 OpenD 不扣历史额度，A 股新浪），不做后台采集。

A 股一次约 2–3 分钟、峰值内存约 1.2 GB；港美各约 1 分钟。数据在 GitHub Release（见 [docs/DATA.md](../../docs/DATA.md)），解压到 `data/` 即可，只读本地文件，不连 OpenD、不下单。
