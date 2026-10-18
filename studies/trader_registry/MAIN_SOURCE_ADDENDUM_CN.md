# 2026-10-18：main 来源版本补充

本次整合核对 main `5bd4c16d73a9ca7b2b2d2c94b145b4949e2eb339`，不修改冻结个人档案或既有策略。本页记录旧资料包与当前 main 之间新发现的证据差异。

## Martin：自动字幕整理已存在，但不等于本轮亲听核验

main 的 [RULES_CN.md（固定版本）](https://github.com/QSothoth/s-alpha/blob/5bd4c16d73a9ca7b2b2d2c94b145b4949e2eb339/studies/martin_luk/notes/RULES_CN.md) 明确声明：2026-10-17 从两场 TraderLion 长访谈的英文自动字幕整理，中文为意译。

- `lS9zbnLi1Gg`：该文件记载2025-04发布、讨论2024年；[视频入口](https://www.youtube.com/watch?v=lS9zbnLi1Gg)，离场对应00:45:25、01:17:10
- `VKNEJA5r8zw`：该文件记载2026-01发布、讨论2025年；[离场段02:27:27](https://www.youtube.com/watch?v=VKNEJA5r8zw&t=8847)，延续至02:29:01，另见02:53:46
- 该整理将分批退出与初始风险倍数（3R或5R）、小时线延伸及约15%的减仓联系起来，同时记录均线退出和市场环境变化。它为该版本提供了有时间戳的字幕衍生证据，不能仍概括成“完全没有来源支持”
- 本次仅核对仓库中的整理和台账，没有重新播放音频、下载原始字幕或逐词核听。自动字幕识别和中文意译可能有误，多个时间戳合并在一行，不能把每个数字无条件归于每个视频或每个年度

[逐笔台账（固定版本）](https://github.com/QSothoth/s-alpha/blob/5bd4c16d73a9ca7b2b2d2c94b145b4949e2eb339/studies/martin_luk/notes/trades.csv) 进一步按视频ID/时间戳、日期精度和交易方向记录案例。这是研究者摘录的交易台账，不是券商完整成交与资金流水审计。

## ADR/R冲突仍须按日期区分

[旧资料包版本对照](dossiers/swing/MARTIN_VERSION_CROSSWALK.md) 对应此前研究分支 `9bc6a6b`；它保留2025-02-06本人评论中的 >3×ADR、约10%等口径，以及当时“未核原声”的阅读状态。当前 main 的字幕整理是额外证据，既不抹去早期评论，也不能证明全年规则恒定。

旧基线的3/6/9/12R阶梯、新字幕整理的3R或5R约15%、以及 main R74研究选择的10R减仓30%应分开：后者是研究者同段择优配置，不能写成已证实的本人原版。当前研究结论见 [REPLICATION_CN](../martin_luk/reports/REPLICATION_CN.md)。

下一步只需针对上述时间戳核对原字幕/原声、明确减仓分母与适用设置，并建立日期化规则映射；无需先改任何策略参数。

## Mark：使用反馈与当前代码可定位性分开

当前 main 逐文件检索专用目录、共享 `trader_replication` 模块、配置、测试与文档，未找到可明确归属于 Mark Minervini 的专用实现。Martin 台账中一次 VCP-like 描述不是 Mark 策略注册。

[历史研究分支的Mark实现](https://github.com/QSothoth/s-alpha/tree/9bc6a6b29c577d4ad6d6d13312beaf15ae7ab1f2/studies/mark_minervini) 确实存在；其局部假设实验与用户“使用起来感觉可以”的反馈都保留，不等于当前 main 已包含该实现或获得独立样本外验证。本次没有合并旧策略，也没有改动现有策略文件。
