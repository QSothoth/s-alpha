# WF05c 修补任务书：判定代码加“保真接受”后刷新开轮证据（不是轮次）

工作区 `/opt/opend-us-options/.claude/worktrees/gap-review`（git worktree，不提交、不推送）。流程目录 `studies/martin_luk/workflow`（下称 DIR）。规则 `skills/trader-replication/references/WORKFLOW_CN.md` 先读，特别是合并验收里新加的“保真接受”。运行环境由启动命令设好。**计算上限 30 分钟。**

## 背景（leader 已做，2026-11-09，用户授权 leader 裁定）

WF06 定格后会话中断，leader 按任务书 0.4 节裁定：
- 名额不超过 11；
- 合并验收加“保真接受”，并批准 WF06 第 1–10 节的探索轮。

已落盘的改动：
1. `studies/trader_replication/pipeline.py`：`accept('merge')` 在标准方式没过时，再按保真接受算一遍（`_fidelity`），返回 `mode`。标准方式的检查和结果不变。
2. `config.json` 的 `accept.merge` 加两个阈值：`fidelity_min_log_gap_gain=0.1`、`fidelity_max_year_gap_loss=0.1`，并追加 `change_log`。
3. 新增测试 `studies/trader_replication/tests/test_workflow.py::test_merge_fidelity_accepts_closer_returns_without_extra_segments`。
4. WF05 的 J1、J2、J3 用新代码复算，判定不变（J3 仍是 standard 方式 accepted）。
5. 改了 `pipeline.py` 会让冻结缓存的代码指纹失效。leader 已用 `frozen_cache.refresh_manifest` 刷新全部 13 个缓存：内容文件和不可变来源都核对过没变，`state.frozen_caches` 记的清单 SHA 已同步，已登记的缓存全部能加载。刷新前的清单备份在 `/root/.claude/jobs/902f9f8b/tmp/frozen_manifests_before.tgz`。
6. `state.rule_fingerprints` 已重钉，并在 `state.rule_changes` 追加了记录。

## 现在的问题

`status.generate()` 返回 `can_start_round=False`，其中 `datasets`、`capital_rules`、`registered_unchanged` 三项为 false。原因是这三份证据里记的是改动前的 config SHA 和代码 SHA。

## 要做

1. **数据集证据**：按 `status._dataset_evidence` 读取的现有格式，重跑 datasets check，写一份新的证据。
2. **资金审计**：仿照 WF05b（`DIR/rounds/WF05b/`）的做法。先证明 `capital` 节、`versions.json`、各回放文件都没变（本次只改了 `accept.merge` 两个阈值和 `change_log`），然后只更新指纹，不重放。审计链里的 `previous_audit` 照规矩处理。
3. **测试证据**：按 `status._test_evidence` 要求的格式，跑 `custody/tests`、`studies/trader_replication/tests`、`studies/martin_luk/tests`、`studies/trader_screens/tests`，写 `DIR/rounds/WF05c/logs/tests.json`。
4. **重出 STATUS**：用 `status.generate()` 重出 `DIR/rounds/WF05/STATUS.json`（`metrics_round` 是 WF05）。门槛是 `can_start_round=true`、所有 `readiness_checks` 为 true、`profile check` 返回 0。
5. **不许动的东西**：任何判定、`versions.json`、`VERSIONS_CN.md` 的数字、冻结缓存的内容、登记版和看板。WF06 的任务书不改。
6. **记录**：写 `DIR/rounds/WF05c/completion.json`，包括前后 SHA、三项证据的路径、测试结果、can_start_round、`workflow_issues`；再写一页白话 `REPORT_CN.md`。哪一项做不到就如实写明，不要绕过检查。
