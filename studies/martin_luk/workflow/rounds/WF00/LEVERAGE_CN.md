# WF00g：杠杆档位、追保减仓、v0/v1 三档重算（用户 2026-11-09）

先读当前版本的 `skills/trader-replication/references/WORKFLOW_CN.md` 第二节“资金与杠杆”和“版本号”，以及 `config.json` 新的 `capital` 节（三档 L1、L2、L2.8，验收档为 L2.8，减仓方式三选一，默认 weakest_first）。

约束同 PLAN_CN 第 6 节：不开候选，不改登记版和看板，不拉新数据，不改数据集，不改规则文件和 config 用户节，不提交。

**计算上限 45 分钟**；超了停下，写明卡在哪一步。

## 1. 引擎支持维持线与减仓

在 `studies/trader_replication/system.py` 的 `Rules` 里加选项：
- `maintenance`：默认 `None`，表示不检查；
- `deleverage`：`weakest_first`、`pro_rata`、`largest_first` 三选一。

规则如下：
- **检查时点**：每天收盘检查。杠杆超过 1/maintenance 时，第二天开盘按开盘价减仓。
- **减仓幅度**：减到 `max_gross`（即 initial）以内，跳空照实计入。
- **三种减仓方式**：
  - `weakest_first`：按浮动 R 从低到高整只卖出，最后一只可以部分卖；
  - `pro_rata`：所有持仓按同一比例卖；
  - `largest_first`：按市值从大到小卖。
- **夹在中间时**：杠杆在 initial 和维持线之间，不开新仓、不加仓（沿用现有入场检查），也不强制卖。
- **空头**：市值按绝对值计入杠杆。
- 减仓产生的成交单独标记 `why='margin_call'`。

要求：
- **默认值逐位不变**：`maintenance=None` 时，所有登记系统（R74、看板各交易员等）的结果必须逐位不变，跑现有回放单测证明。
- **先写执行时点单测**，用合成数据覆盖以下情况：收盘超线 → 次日开盘才卖；三种减仓方式各自卖哪只、卖多少；跳空；在两条线之间不卖；空头。

## 2. 杠杆检查

`workflow/capital.py` 按新 `capital` 节改写：
- 候选和版本必须声明使用哪一档；
- `max_gross` 等于该档的 initial，`margin_rate` 等于该档的利率，`maintenance` 等于该档的维持线；
- 不符就判失败；
- 补单测。

## 3. 重算 v0、v1

- 用原生规则回放：v0 是 master，v1 是 IE47 + C062。不要用存档台账代替；回放代码和指纹写进报告。
- 在三档下各跑一次，减仓方式用默认 weakest_first。
- 另外在验收档 L2.8 下，对 v0、v1 各加跑一次 `pro_rata` 作对照。
- 回放前先确认：在原 `max_gross=2.8` 且无维持线时，原生回放与登记台账逐位一致，然后才加档位。
- 每次回放报告：
  - 每年的收益、胜率、盈亏比、笔数、平均持有；
  - 峰前持有 / 早买；
  - 最高杠杆和平均杠杆；
  - 追保次数与追保卖出的笔数、金额和盈亏。
- 年份为 2024、2025，以及 2026（标“留出*”）。
- 峰值内存不超过 900MB，同时只跑一个回放。

## 4. 版本总表与状态

- `versions.json` 的每个版本记分卡改为按档位分组。
- `VERSIONS_CN.md` 重新生成：
  - 主表只放验收档 L2.8，列他本人、v0、v1；
  - 下面加一张“杠杆对照”表：同一版本在 L1、L2、L2.8 下的收益、最高杠杆、峰前持有，以及 L2.8 下两种减仓方式的差别。
  - 白话列名。
- 若 v1 在 L2.8 下的数字变了，按新数字重出 `STATUS.json` 和 `next_cell`。
- 在 REPORT_CN.md 末尾追加“杠杆档位重算”一节：先结论，说明重算前后的差别。

## 5. 收尾

- **测试**：只跑 `custody/tests`、`studies/trader_replication/tests`、`studies/martin_luk/tests`；改了 system.py，再加跑 `studies/trader_screens/tests`。
- **能否开轮**：`can_start_round` 在以下都满足后才设为 true：G1 通过、白名单已批、datasets check 通过、杠杆检查通过、登记系统逐位不变。
- **记录**：completion.json 追加 `leverage_profiles` 小节；流程问题账追加 WF-017 的状态行和本轮发现的问题。
