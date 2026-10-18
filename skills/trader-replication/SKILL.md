---
name: trader-replication
description: 把一位公开过做法和交易记录的主观交易员（第一个例子 Martin Luk）拆成股票池、强度扫描、观察名单、形态、入场、止损离场、仓位市况、空头几个环节，逐环节对照他的原话和真实交易去逼近：先从访谈和直播字幕收集交易台账，再用“命中他真实交易的比例”和“相对同一批股票随机入场的超额”两把尺子逐轮预登记、选择、验证，最后组合成 A 股 / 港股 / 美股完整系统并写清逼近程度和差距。用于“复刻 / 逼近某个交易员”“看我们的流程能不能选中他买的股票、在他买的那天出信号”“换个交易员再做一遍”；不产生交易许可、不下单、不接 custody。
---

# 逼近一个交易员（trader-replication）

工程为 `/opt/opend-us-options`，沿用根及 `studies/AGENTS.md` 的研究规范（预登记、每轮 ≤ 5 个候选、选择段与验证段分开、失败照记、不为单个 case 拟合）。方法、口径与常见坑见 [METHOD_CN](references/METHOD_CN.md)；Martin Luk 这个例子做了什么、学到什么见 [MARTIN_LUK_CN](references/MARTIN_LUK_CN.md)，完整数字在 `studies/martin_luk/reports/REPLICATION_CN.md`。

结论都是区间内的研究结论，不是投资建议；本 skill 不碰交易接口。

## 步骤

1. **找资料、按环节摘原话**：长访谈的逐笔复盘、本人直播 / 复盘视频（只下字幕：`yt-dlp -6 --skip-download --write-auto-subs --sub-langs en-orig`，视频间隔 60 秒以上，遇到 HTTP 429 退避 20 分钟）、帖子。原话按环节整理成 `studies/<交易员>/notes/RULES_CN.md`，每条带出处（视频 id + 时间戳）。二手摘要只当线索。
2. **建交易台账** `studies/<交易员>/notes/trades.csv`（格式与校验见 `studies/trader_replication/ledger.py`）：至少 30 笔，标日期精度（exact / chart / window），能用成交价、事件日核对的都核对；直播里“今天 / 昨天 / 周四买的”换算成交易日。台账冻结、提交后再跑检验；按时间切选择段 / 验证段，切分点写进第一轮预登记。
3. **准备按当时条件的数据**：全市场日 K（含后来冷掉的股票），名单只用 t−1 及以前的数据；分钟线只在按当时条件随机抽样的子集上比较入场。历史 K 线额度至少给 custody 留 80，扣新额度先问用户；一晚最多新拉 150 只；磁盘保持 5GB 以上。
4. **基线漏斗**：用现有最好的流程给他的选择段交易打分，看每笔丢在哪一环。
5. **逐环节优化**：每环一轮或多轮（每环最多 20 轮），候选来自他的原话；选择段按“宽度上限内命中率最高、超额不为负”选，验证段只评一次；“更像他”和“有超额”分开记。某环怎么都过不了就如实记下，进入下一环。
6. **完整系统**：组合各环节选择，美股、港股、A 股都跑（港股、A 股没有他的交易，只量超额），和同一名单随机入场的安慰剂、等权持有比较，按年拆开；美股另报验证段命中他交易的比例；与他公开的统计对照。
7. **逼近他的收益**（第二阶段，见 METHOD_CN 第 9 节）：在完整系统上逐轮只改一处，按目标（例子里是“两个冠军年里较差的一年”）带入，要求跑赢同池安慰剂、命中不降，绝不带入更差的配置；每几轮做一次逐笔诊断（他的每笔交易卡在哪一步），“命中”和“实际买到”一起报。用户要求用满轮次时，每个环节最多 20 轮，候选仍须来自他的原话或诊断，不做网格搜索。
8. **写结论**：逼近到什么程度、还差在哪（缺数据、无法机械化、规则本身没有超额、像他和赚钱是否背离）。

## 运行（以 Martin Luk 为例）

```bash
cd /opt/opend-us-options
PY="nice -n 19 env OPENBLAS_NUM_THREADS=1 PYTHONUTF8=1 /opt/futu-opend/venv/bin/python"
# 第一阶段（逐环节像不像 + 超额）与第二阶段前半（带入规则）：按顺序，后一轮读前一轮报告里的 chosen
for r in r19 r20 r21 r21b r22 r22b r23 r23b r23c r24 r24b r25 r26 r27 r27b r28 \
         r29 r30 r31 r32 r33 r34 r35 r36 r37 r38 r39 r40 r41; do
  $PY -m studies.martin_luk.replicate $r
done
# R42 起每轮写成 notes/rounds/R*.json（基础配置 + 候选改动），结果在 reports/r42.json 等
for n in $(seq 42 74); do
  $PY -m studies.martin_luk.replicate round R$n
done
$PY -m studies.martin_luk.replicate diagnose r74.json   # 他的每笔有日期多头卡在哪一步、头部交易
$PY -m studies.martin_luk.replicate robust r74.json     # 邻近参数、起始日期、成本加倍（只报告）
$PY -m studies.martin_luk.replicate final r74.json      # 带入配置在美 / 港 / A 股的完整结果
$PY -m unittest discover -s studies/trader_replication/tests -t .
$PY -m unittest studies.martin_luk.tests.test_replicate
```

每轮的预登记在 `studies/martin_luk/notes/PREREG_R*.md`，逐轮记录见 `notes/ROUNDS_CN.md`，结果写 `studies/martin_luk/reports/`。一次只跑一个进程（两核机器满载会被外部停机）；R24 系列读 5 分钟样本，第二阶段每轮（5 个候选 + 参照，各 100 次安慰剂）约 20 分钟。

## 换一个交易员

先查 [35人档案与风格注册表](../../studies/trader_registry/README.md)，读取个人档案、来源账本与缺失规则。注册表只是研究导航；历史分支中的实现不代表当前 main 已有同一实现，未知字段不可用相似交易员代填。


新建 `studies/<名字>/`：`notes/RULES_CN.md`、`notes/trades.csv`、`notes/PREREG_R*.md`，再写一个像 `studies/martin_luk/replicate.py` 的环节模块（股票池、强度、名单、形态、入场、离场的掩码函数和各轮入口）；台账、命中率与漏斗、同日同波动组超额、多空组合与安慰剂直接用 `studies/trader_replication/` 的 `ledger`、`fidelity`、`edge`、`system`。新环节规则先写执行时点单测；分钟线入场只用触发前可知的条件。
