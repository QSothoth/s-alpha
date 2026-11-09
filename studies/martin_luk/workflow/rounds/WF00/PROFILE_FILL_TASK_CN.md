# WF00i：按用户决定补齐档案，刷新审计，使开轮条件成立（用户 2026-11-09）

先读 `skills/trader-replication/references/WORKFLOW_CN.md`（第一、三、四、九节）、`studies/trader_replication/profile.py`、本目录 `PROFILE_TASK_CN.md`、`REPORT_CN.md` 末节、`profile_draft.json`、`regime_rejudge.json`、`work/profile_check.txt`（86 条缺项）。

本任务是用户批准的档案修改，在两次运行之间落盘。**计算上限 30 分钟**；超了停下，写明卡在哪一步。不开候选、不改登记版和看板、不拉新数据、不改数据集和 schema、不改判定代码（pipeline.py、funnel.py、mainleg.py）、不提交。

## 用户决定（2026-11-09，本会话）

1. **档案补齐方案已批准**：各节来源和日期按用户 11-08（`rounds/WF00/APPROVED`）、11-09 的决定填；他的多空、形态从画像草稿并入并标“证据弱”；成交额、ADR 分位来源中没有，标为未观测并写理由；2026 年度胜率、盈亏比、笔数无出处，标为未观测。检查器只认“不适用”“证据弱，按原话”两种状态，未观测写在 reason 里，状态取其一并说明为什么。
2. **B4_PCT2 重判接受为“证据弱（按原话可用）”**：`regime.calendar.status` 由“待重判”改为冻结，注明证据弱、依据 `rounds/WF00/regime_rejudge.json`、用户 2026-11-09 接受；只对应 `regime.words` 第 0、1 句。
3. **QQQ 开关**：用户原话“你自己决定，通过尝试和验证之后决定是按什么开关来，可能针对这个交易员需要单独写一个类似的门禁功能”。v1 定义不变（C062 自带 e8_scale 保留）。把这句原话作为 `goal` 的一条追加（date 2026-11-09，source 写“用户 2026-11-09 会话回答（QQQ 开关）”），供后续交易线把执行开关作为候选、按第三节第 8 条接受。
4. **脚本补丁已落盘**（用户批准）：`.claude/workflows/trader-replication-loop.js` 每轮“量”跑 `profile check`，规则指纹加入 `bar`、`selection_years`、`holdout`、`legs` 与段表文件；`tools/mock2.js`、`mock3.js` 同步，`run_mocks.sh` 已通过。

## 要做

1. **改 config**：
   - 元数据尽量放 `profile_meta`（按点路径），或放在各项旁边的 source/date 字段里。
   - 不改变任何现有衡量结果：`funnel.behaviour_gap` 现在只读数值字段 win/payoff/days/n 及其 `sources`，这些数值和 sources 保持原样。2024 约 5 天、2025 赢 3 天/亏 1 天只作带状态的档案说明，不写进数值 `days`（WF-025 未决）。版本总表里已有的数字应逐位不变。
   - `behaviour_card.by_state` 按草稿并入，去掉 draft 标记。凡是会遍历 `behaviour_card` 全部键的代码（例如 `bootstrap.py` G0 manifest），改成只取年份键，并补单测。
   - 追加 `change_log`：日期、改了哪些路径、依据（用户决定 1–3）。
2. **刷新依赖 config 指纹的审计与状态**：
   - 重跑 datasets check；
   - 资金审计（`work/leverage_profiles/capital_audit.json`）：先确认 `capital` 节和回放没有变，再只更新指纹，不重放；
   - 更新 `state.json` 的 `rule_fingerprints`，纳入新的 loop.js；
   - 用 `status.py` 重出 `STATUS.json`；
   - `versions render` 重出 `VERSIONS_CN.md`，核对数字不变；
   - `profile render` 重出 `PROFILE_CN.md`。
3. **门槛**：`profile check` 返回 0；`STATUS.json` 里 `can_start_round=true`，`readiness_checks` 全部为 true。哪一项做不到，如实写明原因，不要绕过检查。
4. **流程问题账**：按第八节追加 `applied` 行，引用 WF-027（脚本补丁），以及本任务解决的 WF-025、WF-026 中涉及的部分。
5. **测试**：`custody/tests`、`studies/trader_replication/tests`、`studies/martin_luk/tests`，再跑 `bash studies/martin_luk/workflow/tools/run_mocks.sh`。
6. **记录**：`completion.json` 追加 `profile_fill` 小节，写明前后 config sha、profile check 结果、can_start_round、测试结果和 workflow_issues；`REPORT_CN.md` 末尾追加一节白话说明。
