# 看板接入任务书：Martin 候选池（研究观察版）

工作目录：`/opt/opend-us-options/.claude/worktrees/gap-review`。先读根 `AGENTS.md`、`studies/AGENTS.md`、`skills/trader-screens/SKILL.md` 及其 `references/`、`studies/trader_screens/README.md`、`studies/trader_data/README.md`，以及 IE8–IE11 报告 `studies/trader_replication/reports/gap_review/strong_continue_ie8/9/10/11_report_CN.md`。本文件是本任务唯一任务书，运行期间不改。用词：称“过滤条件”，不称“门禁”。

## 目标（用户 2026-11-03 同意）

在交易员看板里给 Martin Luk 加一个**研究观察版候选池**：每晚列出通过过滤条件的候选（约 50 只），并按排名标出前 5 作参考。它只是观察名单：

- 不替换、不修改 Martin 已登记的系统、持仓、买卖记录和横向比对表；
- 不计入他“今天的买卖”，单独一节，标题和每条都写明“研究观察版、未验证”；
- 不接 custody、不下单。

## 要接入的规则（固定，不再调）

- 过滤条件 = IE8 冻结的 4 条（同晚完整 leader 比较范围内的百分位，缺失不通过）：`h4_history ≥ 60%`、`adr20 ≥ 70%`、`option_volume ≥ 80%`、`low20 ≥ 50%`。选它而不选 IE11 放松版，是因为两者在 2026 都留住 21/23 笔大赢家，IE8 池子更窄（2026 中位约 56 只，IE11 约 91 只）。
- 排名参考 = IE9 冻结的等权排名：`after_inside`（前一天是内包日）+ `near_ema9`（靠近 9 日均线），在过滤后池子内重排百分位，缺失中性 0.5，同分代码升序。
- 计算必须和研究代码 `martin_continue_ie8.py` / `martin_continue_ie9.py` 的定义逐值一致：写一个对照测试，在 2026 某几个交易晚用研究代码和看板代码各算一次，名单与排名完全相同。

## 数据要求

- 只用看板 live 模式已有的数据通路（`studies/trader_data` 的 frozen / live 开关、`TD.load` 等）。先核对这 4 个过滤条件和 2 个排名因子需要的输入（尤其 `option_volume` 和 `h4_history`）在 live 模式下能否每天拿到。
- 拿不到的，不新增后台、定时或前向采集，也不改定时任务。如实写出缺哪个输入，并给出最小的接入办法，等用户决定；能拿到的部分先做完。
- 不扣 K 线额度，不调用交易接口。

## 展示要求

- 名字在前，不出裸代码；美股没有中文名的用英文名 + 中文行业（参考看板现有格式）。
- 每只股票给一句话说明为什么在池子里（例如“期权活跃、振幅大、离 20 日低点已涨起来”），前 5 另标“排名参考”及原因（内包日次日 / 靠近 9 日线）。
- 池子大时 Markdown 里只展开前 5 和一行总数；完整名单写入附带的 JSON 或折叠段。
- QQ 日报：主目录 `/opt/opend-us-options` 是生产环境，定时 QQ 推送从那里运行。本任务**不改主目录、不改定时任务、不推送**；只在本工作树里改代码，并用 QQ 推送脚本的 dry-run 或本地渲染核对新一节不会破坏现有日报格式。

## 测试与交付

- 补单测：过滤条件和排名只用当晚及以前的数据；与研究代码逐值一致的对照测试；无数据 / 部分缺失时的展示。
- 跑 `python3 -m unittest discover -s custody/tests`、trader_screens 测试、trader_replication 测试（numpy 用 `.venv/bin/python`）、`python3 watch/test_watch.py` 和 `git diff --check`。
- 不提交、不推送。完成后写 `studies/trader_screens/notes/BOARD_IE_CANDIDATES_CN.md`：改了哪些文件、live 输入是否齐、示例输出（用最近一个交易晚生成一次），以及合进 main 前还要用户确认的事。用中文回报，先结论。
