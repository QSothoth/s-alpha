# 近到期期权研究归档

当前任务入口：[near-expiry-session](../../../skills/near-expiry-session/SKILL.md)；共享实现：[us_0dte_picks](../../us_0dte_picks/README.md)。先读 [失败经验](FAILED_TRIALS.md)，不要换名字重复失败机制。

| 已结束研究 | 结论与证据 |
|---|---|
| P1–P5 | 方向名单没有形成稳定有效规则；财报反应日与放量宽幅次日的大波动证据不提供方向。保留 [P1](P1_RESULTS_CN.md)、[P2](P2_RESULTS_CN.md)、[P3](P3_RESULTS_CN.md)、[P4](P4_RESULTS_CN.md)、[P5](P5_RESULTS_CN.md) |
| OH3 | 退出与模型口径审计，见 [报告](OH3_EXIT_AUDIT_CN.md) |
| TS / FD | 已移出的历史实验，结论见 [失败经验](FAILED_TRIALS.md) |
| R27 | 连续信号确认四版均 REJECT，见 [报告](R27_RESULTS_CN.md) |
| R28 | H3 在开发段为 PROVISIONAL，未达到晋级条件；见 [报告](R28_RESULTS_CN.md) |
| R29 | 两种 mode 的基线审计，未改变策略资格；见 [报告](R29_BASELINES_CN.md) |
| R30 | 持仓确认组合的开发段实验，完整原始结果见下面快照；不把已运行评测表述为独立验证通过 |

2026-10-15 将 R27–R30 的脚本、隔离引擎、测试、预登记和逐 case 输出归档到固定提交 [63ab1aa](https://github.com/QSothoth/s-alpha/tree/63ab1aa27ae9a56b423ce2b57ac06729c5f96edc/studies/us_0dte_picks)。[R30 原始结果](https://github.com/QSothoth/s-alpha/tree/63ab1aa27ae9a56b423ce2b57ac06729c5f96edc/studies/us_0dte_picks/reports/R30)与各轮参数、源码指纹都按原样保存。复现应恢复完整快照，方法见 [归档索引](../README.md)，不在当前运行目录复活旧实验。

P2/P3 的计算函数仍被当前会话调用，其冻结预登记和输入文件留在共享代码目录。SV1/SV2 尚未完成验证，也保留在该目录。归档不消耗或重新定义验证数据，不修改已发布 Release。
