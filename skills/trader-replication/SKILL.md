---
name: trader-replication
description: 把一位公开过做法和交易记录的主观交易员（第一个例子 Martin Luk）拆成股票池、强度扫描、观察名单、形态、入场、止损离场、仓位市况、空头几个环节，逐环节对照他的原话和真实交易去逼近：先收集交易台账，再用“命中他真实交易的比例”和“相对同一批股票随机入场的超额”两把尺子逐轮预登记、选择、验证，最后组合成三市场完整系统并写清逼近程度和差距。用于“复刻 / 逼近某个交易员”“看我们的流程能不能选中他买的股票”“换个交易员再做一遍”；不产生交易许可、不下单、不接 custody。
---

# 逼近一个交易员（trader-replication）

工程为 `/opt/opend-us-options`，沿用根及 `studies/AGENTS.md` 的研究规范（预登记、每轮 ≤ 5 个候选、选择段与验证段分开、失败照记、不为单个 case 拟合）。方法和口径见 [METHOD_CN](references/METHOD_CN.md)；Martin Luk 这个例子的过程、结论和差距见 [MARTIN_LUK_CN](references/MARTIN_LUK_CN.md)。

结论都是区间内的研究结论，不是投资建议；本 skill 不碰交易接口。

## 步骤

1. **找资料、按环节摘原话**：长访谈逐笔复盘、本人直播 / 复盘视频（只下字幕）、帖子。原话按环节整理成 `studies/<交易员>/notes/RULES_CN.md`，每条带出处（视频 id + 时间戳）。二手摘要只当线索。
2. **建交易台账** `studies/<交易员>/notes/trades.csv`（格式见 `studies/trader_replication/ledger.py`）：至少 30 笔，标日期精度（exact / chart / window），能用价格核对的都核对。台账冻结后再跑检验；按时间切选择段 / 验证段，切分点写进第一轮预登记。
3. **准备按当时条件的数据**：全市场日 K（含后来冷掉的股票），名单只用 t−1 及以前的数据；分钟线只用按当时条件随机抽样的子集比较入场。历史 K 线额度至少给 custody 留 80，扣新额度先问用户；一晚最多新拉 150 只；磁盘保持 5GB 以上。
4. **基线漏斗**：用现有最好的流程给他的选择段交易打分，看每笔丢在哪一环（Martin Luk 的 R19）。
5. **逐环节优化**：每环一轮或多轮，候选来自他的原话；选择段按“宽度上限内命中率最高、超额不为负”选，验证段只评一次；“更像他”和“有超额”分开记。
6. **完整系统**：组合各环节选择，美股、港股、A 股都跑（港股、A 股没有他的交易，只量超额），和同一名单随机入场的安慰剂、等权持有比较；与他公开的统计对照。
7. **写结论**：逼近到什么程度（每环命中率、信号命中他买入日的比例、交易统计）、还差在哪（缺数据、无法机械化、规则本身没有超额）。

## 运行（以 Martin Luk 为例）

```bash
cd /opt/opend-us-options
PY="nice -n 19 env OPENBLAS_NUM_THREADS=1 PYTHONUTF8=1 /opt/futu-opend/venv/bin/python"
$PY -m studies.martin_luk.replicate r19      # 基线漏斗；之后 r20 … r28 按预登记顺序逐轮跑
$PY -m unittest discover -s studies/trader_replication/tests -t .
$PY -m unittest studies.martin_luk.tests.test_replicate
```

每轮读 `studies/martin_luk/notes/PREREG_R*.md`，结果写 `studies/martin_luk/reports/r*_*.json`，汇总在 `reports/REPLICATION_CN.md`。轮次有先后依赖：后一轮读取前一轮报告里的 `chosen` / `passed`。

## 换一个交易员

新建 `studies/<名字>/`：`notes/RULES_CN.md`、`notes/trades.csv`、`notes/PREREG_R1.md`，再写一个像 `studies/martin_luk/replicate.py` 的环节模块（股票池、名单、形态、入场、离场的掩码函数）；台账、命中率、超额、组合模拟与安慰剂直接用 `studies/trader_replication/` 的 `ledger`、`fidelity`、`edge`、`system`。新环节规则先写执行时点单测。
