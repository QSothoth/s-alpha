# 美股日内选股：每日多空名单（us_preopen_bias）

给用户的日内期权策略选标的：每天开盘时，从期权流动性好的标的里挑出当天**可能大幅波动**的一批，给出做多 / 做空名单；
日内怎么买卖由用户已有的策略负责。决策时点 T 日 09:30（已知 T−1 及更早的全部数据、T−1 盘后与 T 日盘前、T 日开盘价），标签是 T 日开盘 → 收盘。
只用技术面 / 交易数据（正股日 K、延长时段 30 分钟 K、单标的期权成交量与 Put/Call、IV / HV、每日卖空量、资金流），不用财报、宏观日历等基本面。
只读行情，不下单，不进 `custody` 策略注册表。

## 一句话结论

**「今天谁会大动」可以在开盘时挑出来，「往哪边动」用开盘前的日线级信息判断不了。**

- **个股每日做多 Top 3 / 做空 Top 3（最终交付，S24–S26）**：300 只期权活跃个股，前置筛选 T−1 期权量 ≥ 2,000 张（另标期权异动），再按技术指标 / 期权统计排序。
  约 15 个排序规则里只有合成打分 z(Put/Call z) − z(IV − HV) + z(收盘位置) 在选择段过关（多空篮子 +63bp / 天、55% 的天为正），
  **验证段 2025–2026 只剩 +17bp / 天、54% 的天为正，扣成本后为负、不显著——未成立**。
  S27 放宽流动性（期权量 ≥ 1,000 张），在从未用过的第 301–600 名个股上一次性验证：Put/Call 反向**方向反了**（−9 ~ −16bp / 天），
  合成分 +11bp / 天、51% 的天为正，仍低于成本——**未成立**。
  S28 把决策时点移到 09:45（开盘 15 分钟的相对放量与方向，44 只有 5 分钟数据的票）：5 个规则在选择段全部失败，延续与回吐都不成立；事后提出的 O3 篮子口径（S29）在未用过的验证段一次性检验也失败（毛 +8bp / 天、49% 的天为正）。`code/daily_top.py` 每天按合成分出 Top 3（另附只看高隐含波动一半的视图），并如实附上这些数字。

- **大波动名单（S22，验证段成立）**：34 只热门中小盘（AI / 创新药 / 资源）里，按开盘跳空大小（向上、向下各取前 3）或盘前放量（≥ 2 倍，按方向各取前 3）挑出的票，
  当天 |开→收| 是同日准入池平均的 **1.25x / 1.32x**（验证段 2025-01 → 2026-09，95% 区间 1.18–1.32 / 1.26–1.39），振幅也大 26% / 32%。
  每天开盘后用 `code/daily_list.py` 出名单。
- **方向**：同一批票上 5 种方向规则（跳空顺势 / 反做、盘前放量顺势、在场股看 Put/Call、盘后大动做空 + 恐慌做多）命中率 48%–52%，全部未过门槛；
  验证段里跳空顺势只有 46%（反做约 54%），但与选择段不一致，不能据此定方向。
- **全市场均衡名单（S23，期权活跃前 120 中的 114 个，大中小盘与 ETF）**：兼顾成交量、波动与期权盈亏比的打分（B4）选出的票，
  「当天实际波动 / 期权隐含日波动」是同日在场池的 1.16 倍（95% 1.12–1.21）、波动 1.24 倍、期权流动性 4.9 倍；未达预登记的 1.2 倍，验证段未用。
  整个池子当天 |开→收| 平均只有隐含日波动的 56%，即使每天拿到当日极值也只有约 1.0 倍——期权的盈亏比只能来自日内执行。
- 更早在 16 只大盘标的上的开盘方向研究（S1–S10）：

  - **Q2（PROVISIONAL）**：个股前一天盘后（16:00–20:00）涨跌 ≥ 1 个 ATR（不论方向）→ T 日做空。选择段 2023-08 → 2026-09 胜率 66.7%（147 次），
    留出段 2020-02 → 2023-07 **60.7%**（117 次，90% 下限 51.8%）。依据是注意力假说（散户是引人注目股票的净买方，开盘被推高、日内回落）。
    但预登记的主结论（≥ 0.5 ATR）在留出段失败，Q2 是三个变体之一；**2026 年以来 30 次只有 50%**；约一周一次、集中在财报后的第一个交易日，一半落在没有个股 0DTE 的周四。
  - **做多一侧没有成立的信号**：「单标的 Put/Call 偏高（恐慌买 put）→ 做多」在 2023-08 → 2025-06 胜率 58%–63%，验证段 2025-07 → 2026-09 掉到 51.5%，失败，2025 年中之后基本消失。
  - 在选择段就失败的：「贪婪」做空、卖空占比、纯价格反转 / 跳空回吐、盘前放量 / 盘前推动回吐。资金流「小单净买入 → 反向」在原 16 只上一次性检验 54.4%（95% 下限 49.8%），换 40 只从未看过的标的只有 49.4%，不成立。

详见 [reports/RESULTS_CN.md](reports/RESULTS_CN.md)，每轮的预登记在 [notes/](notes/)。

## 口径

- 决策时点 T 日 09:30：已知 T−1 及更早的全部数据和 T 日开盘价；标签是 T 日开盘 → 收盘（0DTE 开盘后持有的窗口）。
- 胜 = LONG 时收 > 开、SHORT 时收 < 开；超额 = 胜率 − 同标的同方向在同一段内的无条件胜率；区间按交易日整块重抽（同一天各标的一起动）。
- 每轮 ≤ 5 个候选、运行前预登记；选择段门槛：≥ 150 个信号且 ≥ 60 天、95% 区间下限 > 50%、超额 ≥ 2 个百分点、两半都 > 51%；
  验证 / 留出段只跑一次：胜率 ≥ 53%、90% 区间下限 > 50%、超额 > 0。
- 防前视：特征只读 T−1 及更早的行和 T 日开盘价，单元测试改动 T 日收盘 / 高低 / 期权 / IV / 卖空 / 盘后之后，T 日的特征必须不变；
  期权统计 / IV / 卖空量的日期对齐已逐行核对（D 行标的价格 = D 日收盘）。

## 数据

十二个 GitHub Release，全部来自本机 OpenD，一次性拉取（`code/fetch.py`），**不需要逐日采集**；K 线只拉 30 天内已扣费的标的，历史 K 线额度前后都是 180 已用 / 120 剩余。
登记与哈希见 [docs/DATA.md](../../docs/DATA.md) 附录。

| tag | 角色 | 内容 |
|---|---|---|
| `preopen-us-train-v1` | 选择段 | 16 只，日 K 2022-06 起，期权统计 / IV 2023-06 起，卖空量 2022-05 起，全部截止 2025-06-30 |
| `preopen-us-valid-v1` | 验证段（S1–S5 已用过一次，之后只作选择） | 同样的表 2025-07-01 → 2026-09-23，另含日级资金流（2025-09-24 起）；特征要热身，与训练 Release 一起加载 |
| `preopen-us-holdout-2016-v1` | 日 K 留出段 | 14 只日 K 2015-06 → 2022-05（S9 的留出段用到 2020-02 起） |
| `preopen-us-ext30-select-v1` | 选择段 | 16 只延长时段 30 分钟 K（只含盘前 ≤ 09:30、盘后 > 16:00），2023-06 → 2026-09-23 |
| `preopen-us-ext30-holdout-v1` | 留出段（S9 已用一次） | 同上，2019-12 → 2023-07（盘前成交量 2020-01 起才有） |
| `preopen-s21-select-v1` / `preopen-s21-valid-v1` | 每日名单选择段 / 验证段（S22 已用一次） | 34 只热门中小盘的日 K、期权统计、IV、卖空量、资金流、盘前盘后 30 分钟 K、不复权日 K，以 2025-01-01 切开 |
| `preopen-s23-select-v1` / `preopen-s23-valid-v1` | 全市场名单选择段 / 验证段（未用） | 期权活跃前 120 中的 114 个：日 K（订阅接口）、期权统计、IV / HV，以 2025-01-01 切开 |
| `preopen-s24-select-v1` / `preopen-s24-valid-v1` | 个股多空 Top N 选择段 / 验证段（S26 已用一次） | 300 只期权活跃个股：日 K（订阅接口）、期权统计、IV / HV，以 2025-01-01 切开 |
| `preopen-s27-holdout-v1` | 截面留出（S27 已用一次） | 第 301–600 名期权活跃个股，同样的表，不切段 |
| `preopen-us-xsec-v1` | 截面新检验（S10 已用一次） | 期权成交量排行里原 16 只以外的前 40 只：日 K（订阅接口，最近 1000 根，不扣历史 K 线额度）+ 资金流 |

标的：SPY QQQ IWM AAPL MSFT NVDA TSLA META AMZN GOOGL AMD MU INTC AVGO SNDK SKHY（SNDK 2025-02 起，SKHY 2026-07 起）。

## 目录

| 文件 | 内容 |
|---|---|
| `code/fetch.py` | 一次性拉取（遇到未扣费标的直接拒绝） |
| `code/package_release.py` | 按日期拆分、写 manifest 与 CHECKSUMS |
| `code/preopen.py` | 读表、构造时点正确的特征与标签（标准库） |
| `code/signals.py` | S1–S10 的开盘方向候选 |
| `code/evaluate.py` | 胜率、基准、按交易日重抽、门槛 |
| `code/run_round.py` / `code/validate.py` | 跑一轮选择 / 一次性验证 |
| `code/explore.py` / `code/diagnose.py` / `code/s9_describe.py` | 明示的选择段探索、分组诊断、S9 / S10 的描述 |
| `code/universe_smallmid.py` | 中小盘标的池规则（OpenD 期权成交量排行 + 板块，先于任何价格定死；结果 `notes/universe_smallmid.json`） |
| `code/picks.py` | S21 / S22：每日多空名单的评测（方向命中、超额、幅度倍数、顺向空间） |
| `code/broad.py` / `code/verify_daily.py` | S23 全市场均衡名单评测；日线与 Yahoo / 腾讯的共识核对 |
| `code/topn.py` / `code/explore_xs.py` | S24–S26：个股多空 Top N 回测（每只与篮子两种口径）、横截面十分位探索 |
| `code/open15.py` | S28：09:45 用开盘 15 分钟出多空 Top 3 的回测（选择段全部失败） |
| `code/daily_top.py` | **每日做多 Top 3 / 做空 Top 3**（只读；与回测同一套代码，测试核对） |
| `code/daily_list.py` | 每日大波动名单（只读；与回测共用公式，测试核对两者一致） |
| `code/plan.py` | Q2 盘前扫描（只读，与回测共用 `preopen.atr20` / `preopen.ah_z`，测试核对两者一致） |
| `notes/S1_PREREG.md` … `S10_PREREG.md`、`S21_PREREG.md`–`S29_PREREG.md`、`VALIDATION_PLAN.md` | 运行前预登记（`s10_security_types.json` 是 S10 新标的的股票 / ETF 分类） |
| `reports/RESULTS_CN.md` 与 `reports/*_raw.txt` | 结果与原始输出 |

## 复现

```bash
# 一次性拉取（需要 OpenD；已拉过就不必）
PY=/opt/futu-opend/venv/bin/python
$PY studies/us_preopen_bias/code/fetch.py --out data/preopen-us-raw
$PY studies/us_preopen_bias/code/fetch.py --out data/preopen-us-holdout-raw --daily-only-from 2015-06-01 --end 2022-05-31 \
  --symbols US.SPY,US.QQQ,US.IWM,US.AAPL,US.MSFT,US.NVDA,US.TSLA,US.META,US.AMZN,US.GOOGL,US.AMD,US.MU,US.INTC,US.AVGO
$PY studies/us_preopen_bias/code/fetch.py --out data/preopen-us-ext30-raw --ext30-from 2019-12-01
python3 studies/us_preopen_bias/code/package_release.py data/preopen-us-raw data
python3 studies/us_preopen_bias/code/package_release.py --holdout data/preopen-us-holdout-raw data/preopen-us-holdout-2016-v1
python3 studies/us_preopen_bias/code/package_release.py --ext30 data/preopen-us-ext30-raw data

# S1–S5 选择段（只加载训练 Release）与验证段（一次）
python3 studies/us_preopen_bias/code/run_round.py REF,S1,S2,S3,S4,S5 --data data/preopen-us-train-v1 \
  --start 2023-08-01 --end 2025-06-30 --split 2024-07-01
python3 studies/us_preopen_bias/code/validate.py --data data/preopen-us-train-v1 --data data/preopen-us-valid-v1

# S6 / S7 / S9 选择段（2023-08 → 2026-09）与 S8 一次性检验
python3 studies/us_preopen_bias/code/run_round.py S6,S7,S9 --data data/preopen-us-train-v1 --data data/preopen-us-valid-v1 \
  --data data/preopen-us-ext30-select-v1 --start 2023-08-01 --end 2026-09-23 --split 2025-02-01
python3 studies/us_preopen_bias/code/run_round.py S8 --oneshot --data data/preopen-us-train-v1 --data data/preopen-us-valid-v1 \
  --start 2025-10-22 --end 2026-09-23 --split 2026-04-01

# S9 留出段（一次）
python3 studies/us_preopen_bias/code/validate.py --data data/preopen-us-holdout-2016-v1 --data data/preopen-us-train-v1 \
  --data data/preopen-us-ext30-holdout-v1 --start 2020-02-03 --end 2023-07-31 --split 2021-11-01 \
  --finalists Q1_ah_attention_short,Q2_ah_attention_short_strong,Q3_ah_attention_short_all

# S10 截面检验（一次）
$PY studies/us_preopen_bias/code/fetch.py --xsec --out data/preopen-us-xsec-raw --symbols <S10_PREREG 规则得到的 40 只>
python3 studies/us_preopen_bias/code/package_release.py --xsec data/preopen-us-xsec-raw data/preopen-us-xsec-v1
python3 studies/us_preopen_bias/code/run_round.py REF,S8 --oneshot --only ref_always_long,ref_always_short,K1_retail_flow_fade \
  --data data/preopen-us-xsec-v1 --start 2025-10-22 --end 2026-09-23 --split 2026-04-01
python3 studies/us_preopen_bias/code/s9_describe.py s10

# S21 / S22 每日多空名单（选择段只加载选择段 Release；验证段只跑了一次）
python3 studies/us_preopen_bias/code/picks.py --data data/preopen-s21-select-v1 --daily-none data/preopen-s21-select-v1 \
  --start 2023-08-01 --end 2024-12-31 --split 2024-05-01 --n 3,1,5
python3 studies/us_preopen_bias/code/picks.py --magnitude --data data/preopen-s21-select-v1 --data data/preopen-s21-valid-v1 \
  --daily-none data/preopen-s21-select-v1 --daily-none data/preopen-s21-valid-v1 --start 2025-01-02 --end 2026-09-24

# S23 全市场均衡名单（选择段）
python3 studies/us_preopen_bias/code/verify_daily.py --data data/preopen-s23-raw > studies/us_preopen_bias/reports/s23_verify_raw.txt
python3 studies/us_preopen_bias/code/broad.py --data data/preopen-s23-select-v1 --start 2023-08-01 --end 2024-12-31
python3 studies/us_preopen_bias/code/broad.py --payoff --data data/preopen-s23-select-v1 --start 2023-08-01 --end 2024-12-31

# S24–S26 个股多空 Top N（选择段；S26 验证段只跑了一次）
X=US.BRK,US.SPCX,US.B
python3 studies/us_preopen_bias/code/topn.py --data data/preopen-s24-select-v1 --start 2023-08-01 --end 2024-12-31 --split 2024-05-01 --exclude $X
python3 studies/us_preopen_bias/code/explore_xs.py --data data/preopen-s24-select-v1 --start 2023-08-01 --end 2024-12-31
python3 studies/us_preopen_bias/code/topn.py --round S26 --data data/preopen-s24-select-v1 --start 2023-08-01 --end 2024-12-31 --split 2024-05-01 --exclude $X
python3 studies/us_preopen_bias/code/topn.py --round S26 --final --only W5 --data data/preopen-s24-select-v1 --data data/preopen-s24-valid-v1 \
  --start 2025-01-02 --end 2026-09-24 --split 2025-11-01 --exclude $X
# S27 截面留出（只跑了一次）
python3 studies/us_preopen_bias/code/topn.py --round S27 --data data/preopen-s27-holdout-v1 --start 2023-08-01 --end 2026-09-24 --exclude $X

# 测试
python3 -m unittest discover -s studies/us_preopen_bias/tests
```

## 每日做多 Top 3 / 做空 Top 3

```bash
/opt/futu-opend/venv/bin/python studies/us_preopen_bias/code/daily_top.py --n 3     # T−1 收盘后至 T 日开盘前任意时刻，约 10 分钟
```

全部输入来自 T−1 及更早（Put/Call、IV / HV、收盘位置、期权量），所以前一晚或盘前都能跑；日 K 走订阅接口分批（每批 100、随后释放），不扣历史 K 线额度。
输出里附着这个排序的真实记录：选择段多空篮子 +63bp / 天，**验证段只有 +17bp / 天（54% 的天为正），扣成本后为负、不显著**。

## 每日大波动名单

```bash
/opt/futu-opend/venv/bin/python studies/us_preopen_bias/code/daily_list.py          # 09:30 ET 之后运行；--all 列出全部合格标的
```

按验证过的口径（开盘价、完整盘前）需在 09:30 之后运行；开盘前运行用最新盘前价与截至当时的盘前成交额，只作参考（输出里标 `pre-market estimate`）。
名单给出的是**会大动的票**和它的跳空方向，方向未经验证。只读，不扣新额度。

## 盘前扫描（Q2）

```bash
/opt/futu-opend/venv/bin/python studies/us_preopen_bias/code/plan.py            # 前一交易日 20:00 ET 之后任意时刻
```

列出 13 只个股前一交易日的盘后涨跌（ATR 单位），≥ 1 个 ATR 的标 `SHORT`，并标出当天是否有 0DTE。这是研究输出，不是下单指令；
2026-09-24 实跑无触发（周四，个股无 0DTE），额度不变；用 `--date 2026-08-27` 复核得到 NVDA +1.59 ATR，与回测一致。

## 下一步（都不需要逐日采集）

- **前向检验 Q2**：OpenD 的日 K、延长时段 K 线都能按需重拉，过几个月直接重拉新交易日评测即可；`code/plan.py` 每天盘前可看当天触发。
- **Q2 的截面新检验**：S10 那 20 只新个股是现成的截面样本，但 Q2 需要它们的延长时段 30 分钟 K 线，只能走历史 K 线接口，要为新标的扣额度，需要用户同意。
- Q2 若要进 custody：一半触发日（周四）没有个股 0DTE，需要决定是否允许次日到期的合约，这超出 custody 现有边界，由用户决定。
