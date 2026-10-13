# 日 K 突破趋势跟随（美股 / 港股 / A 股）：已结束，结论为负

研究「日 K 级别突破入场 + ATR 跟踪离场」能否在正股上做到胜率 30–49%、靠盈亏比赚钱，持有期几天到几周，**不用于 0DTE**。2026-10-12～13 共做了 TF1–TF14 十四轮、约 40 个候选，全部预登记、选择段与验证段分开。

## 结论

**没有找到经得起样本外检验的 alpha。** 能确认的只有两条描述性事实：

1. **追新高 / 突破确实更会挑到后来的大牛股，但抓牛股的成本太高。** A 股点时股票池里，55 日突破 + 大盘在 200 日线上（TF12 的 K1）在开发段（2019-03 → 2022-06）和验证段（2022-07 → 2026-10）都稳定跑赢同日、同数量的随机入场（平均 R +0.05 / +0.10，随机第 95 百分位 +0.02 / +0.05），抓到 ≥ 5R 的比例也更高（2.6% / 3.1%，随机第 95 百分位 1.9% / 2.2%）。但它只在牛市年份赚钱（验证段 5 年中 2 年为正），弱市里持续亏损；用均线、市场宽度、新高扎堆、成交额来判断「何时不做」都没有改善（TF13、TF14）。
2. **趋势跟随在宽基指数上能明显降低回撤，但不提高收益。** 海龟 55/20 通道在 2016–2026 的 5 个指数中有 4 个最大回撤显著更小（如沪深 300 −25% 对 −46%），但夏普没有提高（TF9）。

此前看起来最好的 A 股「动量 + 动量平静择时」（W4），用点时股票池修正幸存者偏差后在 train 段归零，2019–2023 时段外也不成立（TF5–TF7）。

## 全部尝试

| 机制 | 轮次 | 市场 / 数据 | 结果 |
|---|---|---|---|
| 突破入场：52 周新高、55 日突破、离低点 20% + 20 日新高、Supertrend、放量突破 | [TF1](reports/TF1_TRAIN.md) | 美 / 港 / A，train | 不比同日随机入场选股更好；利润来自跟踪离场和牛市 |
| 横截面动量、波动收缩突破、趋势中回调、放量大阳、动量 + 市场状态（统一 3 ATR 跟踪） | [TF2](reports/TF2_TRAIN.md) | 美 / 港 / A，train | 全部未过；美股动量、港股收缩突破只差季度集中度，港股后者扣市场后为负 |
| 动量家族 5 种（126 日、12−1、平滑动量、加市场状态），集中度改按扣市场后的超额 | [TF3](reports/TF3_TRAIN.md) | 美 / 港 / A，train | 全部未过；美、港动量扣市场后超额为正，A 股没有 |
| 短期反转、反转 + 低异常换手、动量 + 低换手、动量 + 动量平静择时（W4） | [TF4](reports/TF4_TRAIN.md) | 美 / 港 / A，train | 门槛全败；W4 的入场事件研究三个市场都显著为正 |
| W4 冻结，test 段一次性验证 | [TF5](reports/TF5_TEST.md) | 美 / 港 / A，test | A 股按原口径通过，独立审查发现股票池前视偏差，修正后可交易性不成立；美、港未通过 |
| 点时股票池修正 + 2019–2023 时段外 | [TF6](reports/TF6_TF7.md) | A 股点时 | W4 在 train 段归零（+2.27% → +0.05%），时段外不成立（t = 0.16） |
| W4 改离场（持有 20 日 / 最长 60 日） | [TF7](reports/TF6_TF7.md) | A 股点时 | 救不回来 |
| 反投机异象：低波动、低 MAX、低异常换手、合成 | [TF8](reports/TF8_TF9.md) | A 股点时，2019–2022 | 大中盘里没有信号 |
| 宽基指数持有 / 空仓：200 日线、12 个月动量、海龟 55/20 | [TF9](reports/TF8_TF9.md) | 5 个指数，2005–2026 | 开发段 4/4 有效，留出段 2/5，不成立；只剩回撤控制 |
| 长假前效应、春节前效应 | [TF10 / TF11](reports/TF10_TF11.md) | 5 个指数 | 开发段不显著；春节前效应 2016–2026 一次性验证不成立 |
| 追涨买卖点：大盘过滤、假突破快速止损 | [TF12](reports/TF12.md) | A 股点时 | 突破 + 大盘过滤两段都跑赢随机，但只在牛市年份赚钱，不成立；假突破止损有害（砍掉洗盘后的大牛股） |
| 追涨的「何时不做」：双均线、市场宽度、新高扎堆；全市场成交额 | [TF13](notes/TF13_PREREG.md) / [TF14](notes/TF14_PREREG.md)（探索性） | A 股点时 | 都没减少弱市年份的亏损；成交额放大时追涨反而为负 |

每轮的预登记在 [notes/](notes/)（`TF*_PREREG.md`，变更记录里有结果），报告与数字在 [reports/](reports/)。训练 / 测试切分见 [notes/SPLITS.md](notes/SPLITS.md)。

## 教训

- **只用当前上市、按当前市值或成交额选出的股票池，会系统性抬高动量 / 追涨的成绩**（今天还在池里的，正是后来涨上去的）。下结论之前必须用点时股票池（[pit.py](pit.py)）。
- **在 A 股大中盘里，看起来的个股 alpha 基本是市场方向（β）或幸存者偏差。** 必须和同日随机入场、同期等权股票池比较，而不是只看绝对收益。
- **「抓少数牛股」的打法要看大赢家的捕获率和其余交易的成本，而不是胜率。** 去头 5% 为负是这种打法的特点；真正的问题是弱市里的累计小亏。
- 一年的选择段只有 4 个季度，季度集中度这类门槛主要在量行情；事后分组看到的「很一致」（如春节前效应），换一段数据就会消失。
- 已用过、以后不能再当样本外的数据：test 段 2025-10 → 2026-10；A 股 2019-03 → 2023-08（W4）；A 股点时 2022-07 → 2026-10（K1）；指数 2016–2026（Z3、春节前效应）。

## 代码结构

| 文件 | 作用 |
|---|---|
| [sources.py](sources.py) | 三个市场同一个接口：`universe()`、`bars(codes, start, end)`、`actions(code, raw, qfq)`；代码统一为 OpenD 格式（`US.AAPL`、`HK.00700`、`SH.600519`） |
| [fetch.py](fetch.py) | 用 sources 一次性建数据集，可断点续传，每只股票写完立即记进度 |
| [panel.py](panel.py) | 读成「日期 × 股票」numpy 面板，用不复权价 + 除权系数重建乘法复权；含固定的训练 / 测试切分 |
| [signals.py](signals.py) | 全部候选的指标、入场与跟踪线；只吃面板，不按市场或来源分支，停牌日跳过；回测与在线扫描共用 |
| [backtest.py](backtest.py) | 矩阵引擎：按日循环、对所有股票做向量运算；T+1 开盘成交、收盘确认离场、涨跌停、停牌、段末结算 |
| [reference.py](reference.py) | 逐笔参考实现，只供测试和矩阵引擎逐笔对齐 |
| [pit.py](pit.py) | A 股点时面板：多个数据目录合并，按当日总股本算点时市值（两遍流式读入，省内存） |
| [run_tf6.py](run_tf6.py) … [run_tf14.py](run_tf14.py) | TF6–TF14 的运行入口（复现命令见各轮报告或文件开头） |
| [run_tf1.py](run_tf1.py) | 跑一轮（`--round tf1` … `tf5`）一个段：两种股票池口径、100 次随机对照、等权基准、门槛与选择，写 `reports/<轮次>_<段>.json` |

在线运行的设计见 [notes/ONLINE.md](notes/ONLINE.md)（未实现；没有规则晋级到需要在线运行）。

## 数据

全部发布在 `QSothoth/s-alpha` 的 Release，tag、内容和 SHA256 登记在 [docs/DATA.md](../../docs/DATA.md)；解压到仓库的 `data/` 下即可直接运行：

| Release / 本机目录 | 内容 |
|---|---|
| `trend-breakout-v1` | 美股 1,439 只、港股 504 只、A 股 1,773 只日 K（2023-09 → 2026-10），A 股另有历史总股本 |
| `trend-breakout-cn-pit-v1` | A 股点时补充：2018 年起的历史日 K、当前市值 30 亿～100 亿的补充股票及其复权和股本 |
| `index-cn-daily-v1` | 上证综指、沪深 300、中证 500、创业板指、中证 1000 日线（2005 → 2026） |

每个市场目录的格式相同：
- `universe.json`：来源、筛选条件、快照时间、股票名单；
- `bars_raw*.csv.gz`：`code,date,open,high,low,close,volume,turnover`，不复权；
- `bars_qfq.csv.gz`：源前复权，只用于审计；
- `actions*.csv.gz`：`code,ex_date,factor_a,factor_b`，除权日前的价格 p 换算为 `a × p + b`；
- `shares*.csv.gz`：A 股历史总股本。

股票池都按 2026-10-12 的当前流动性 / 市值粗筛，有幸存者偏差；A 股点时研究用补充数据做了部分修正，但仍缺退市股。

## 复现

全部用 `/opt/futu-opend/venv/bin/python`（面板需要 numpy，美股、港股需要 futu-api）：

```bash
PY="env PYTHONUTF8=1 /opt/futu-opend/venv/bin/python"
$PY -m studies.trend_breakout.fetch hk --out data/trend-breakout-v1
$PY -m studies.trend_breakout.fetch us --out data/trend-breakout-v1
$PY -m studies.trend_breakout.fetch cn --out data/trend-breakout-v1
$PY -m studies.trend_breakout.fetch cn --actions-only --redo-actions --out data/trend-breakout-v1  # 改了 A 股反推后离线重算
$PY -m studies.trend_breakout.fetch checksums --out data/trend-breakout-v1
# A 股点时补充（TF6 起）：历史股本、补充股票池、历史日 K，见 fetch.py 的 --shares-only / --band / --history-from / --part
```

中断后重跑同一条命令会从 `progress.json` 续传（已完成的代码跳过，失败的重试）；重复写入的行和除权在读取时去重。

## 回测口径（细节见各轮预登记）

- 信号 T 日收盘确认，T+1 开盘成交；离场按收盘确认、次日开盘成交，不模拟盘中止损。
- 股票池每天按截至信号日的 20 日成交额筛（美股 ≥ 5000 万美元且股价 ≥ 5 美元；港股 ≥ 2000 万港元；A 股 ≥ 1 亿元），另报告取数时的全部股票作偏差对照。
- 成本（单边）：美股 0.05%；港股 0.16%；A 股买入 0.076%、卖出 0.126%。
- A 股：ST 直接排除；涨停开盘买不到；封死跌停卖不出、顺延；涨跌幅主板 10%、创业板 / 科创板 20%。
- 每个市场各自从同一组候选里选，不做迁移检验。

```bash
PY="env PYTHONUTF8=1 /opt/futu-opend/venv/bin/python"
$PY -m studies.trend_breakout.run_tf1 train --round tf1   # 每轮约 6 分钟；逐笔交易写到 data/trend-breakout-v1-results/
```

## 测试

`PYTHONUTF8=1 /opt/futu-opend/venv/bin/python -m unittest discover -s studies/trend_breakout/tests`
