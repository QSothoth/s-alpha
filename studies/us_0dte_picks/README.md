# 近到期期权会话的共享实现

使用入口：[near-expiry-session](../../skills/near-expiry-session/SKILL.md)。操作流程、许可、预算、异常恢复和复盘统一维护在 skill 的 [运行资料](../../skills/near-expiry-session/references/WORKFLOW_CN.md)。当前会话使用 v6.6，只做 mock；代码能力不等于收益验证或实盘许可。

## 保留的实现

- `prepare_watch.py`、`launch_watch.py`、`live_watch.py`：盘前输入与盘中观察。
- `session.py`、`auto_watch.py`、`mock_watch.py`：许可、状态、预检与 custody 交接。
- `daily_list.py`、`daily_k.py`、`p3.py`：会话仍引用的名单、日线、量基准和计算函数；A4 原研究规则仍标为 `P5_FAILED`。
- 冻结预登记仍引用的 `notes/FAILED_TRIALS.md` 与 `reports/P5_PARITY_CN.md` 只保留指向归档的符号链接，正文只维护一份。
- `notes/DENOMINATORS.md`、股票池 JSON 与 P2/P3 冻结预登记：上述共享代码的输入和校验依据，保留原路径与指纹。

数据使用状态见 [TEST_SETS](notes/TEST_SETS.md)。SV1/SV2 会话验证已于 2026-10-16 放弃，见 [archive](../archive/README.md)。

## 已结束研究

P1–P5、OH3、TS/FD、R27–R30 的结论与证据入口见 [研究归档](../archive/us_0dte_picks/README.md)。R27–R30 的隔离引擎、一次性评测脚本、研究测试和逐 case 输出已归档到固定 Git 提交，不再混在当前会话目录。注册策略与 `reports/` 下的资格报告保留原位。

测试：`PYTHONUTF8=1 python3 -m unittest discover -s studies/us_0dte_picks/tests`。
