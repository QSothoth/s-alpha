# WF00f：版本总表、统一杠杆、修状态生成器

先读当前版本的 `skills/trader-replication/references/WORKFLOW_CN.md`：第二节新增了“资金与杠杆”和“版本号”，第一节用户节变为七节。再读 `config.json` 的 `bar`、`base`、`capital` 三节，流程问题账 WF-016，以及本目录 REPORT_CN.md 末尾的“基线（底座 IE47 + C062）”。

约束同 PLAN_CN 第 6 节：不开候选，不改登记版和看板，不拉新数据，不改数据集，不改规则文件和 config 用户节，不提交。

**计算上限 30 分钟**；超了停下，写明卡在哪一步。

## 1. 统一杠杆

- **查配置**：查 v0（master）、v1（IE47 + C062）及注册表里每个系统实际用的 `max_gross`、`margin_rate`。从它们的 Rules 或配置源码取，不要猜。
- **查实际用量**：从逐日台账算每年实际的最高总敞口和平均总敞口。
- **重算**：v0 或 v1 配置的 `max_gross` 超过 `capital.max_gross`，或者 `margin_rate` 和 `capital` 不一致时，在上限内重算该系统，并报告和原数字的差别。都一致就不重算，写明依据。
- **以后轮次的检查**：候选的 Rules 必须从 `capital` 读这两个值。
  - 在 adapter 或 verify 里加一个检查：`max_gross` 超过上限，或 `margin_rate` 不一致，就判失败；
  - 补一个单测。
  - 单只仓位上限和同时持仓数不做限制，它们是可优化的配置。

## 2. 修状态生成器（WF-016）

`adapter.status()` 等状态生成代码要分开计算两条线：
- 主线用 `components.merge`，也就是 v1 或之后的版本；
- 底线用 `bar`。

另外三点：
- 选择年末还没走完的跨年段单独列出，不参与定格；
- 选股可达上限分两列，一列是结构性上限（E1 候选池），一列是名单内的观测上限；
- 用修好的生成器重出 `STATUS.json`，结果必须和 REPORT 末尾基线一节的手工复算一致。

## 3. 版本总表

- 新建 `workflow/versions.json`，只追加，一个版本一行：
  - 版本号、名称、角色（底线 / 底座 / 合并通过）、组件明细、来源账户、日期、记分卡。
  - 首批两行：v0（master，底线）和 v1（上周最佳，IE47 + C062，底座）。
- 记分卡按年列 2024、2025，以及 2026（标“留出*”）。每年的项目：
  - 他的段峰前持有 / 段数、早买 / 段数；
  - 收益、胜率、盈亏比、笔数、平均持有天数；
  - 最高总敞口；
  - 行为记分卡在 ±20% 内的项数。
- 再放一行“他本人”，只写 `notes/SOURCES.md` 里有出处的数字，没有的写“—”。
- 由 versions.json 生成 `workflow/VERSIONS_CN.md`：一张总表，白话列名，写给用户看。
- 提供 CLI，以后合并验收通过时追加新版本并重出总表。

## 4. 收尾

- **测试**：只跑 `custody/tests`、`studies/trader_replication/tests`、`studies/martin_luk/tests`。
- **缓存**：确认当前登记的冻结缓存都能用 `frozen_cache.load` 读取；没登记的 IE9 旧缓存不要求能读，在 manifest 旁注明“已退役”。
- **能否开轮**：`can_start_round` 在 G1 通过、白名单已批、datasets check 通过、杠杆检查通过、状态生成器修好之后才设为 true。
- **记录**：completion.json 追加 `versions_capital` 小节；流程问题账追加 WF-016 的状态行和本轮发现的问题。
