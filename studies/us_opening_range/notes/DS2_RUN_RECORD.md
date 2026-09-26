# DS2 首次开发运行记录

首次真实标签读取前，2026-09-26 04:18 UTC：固定 SPY 2024-05-30 抽查已完成，旧 5m 和延长时段数据与 OpenD 同时刻重取完全相同；Yahoo／腾讯日线的差异符合复权基准差异。没有发现足以中止本轮同源 5m 聚合研究的时间或来源错误。质量审计并不覆盖全部历史，更不证明 Alpha。

质量原始目录 CHECKSUMS SHA256：`0abc2178327c1b0c4db7281cb03e261e31b0fc273758c78434976771b4b12ee3`，已另发 [固定日期质量 Release](https://github.com/QSothoth/s-alpha/releases/tag/or-source-recheck-spy-20240530-v1)。复核仍发现跨周期成交量不一致、个别日线高低与 5m 聚合不同及零量平价条目，所以本轮仅用同源分钟历史与同钟点成交量；零量条目不事后删除，输出质量标记。

冻结登记 SHA256：`1ebb0641738f688cba538e6b35b69a25e6da9379121423cbf9414385956cb19b`。
引擎 `event_signals.py`：`c891d118a5fa8995f8ac77825d33c286ee3c5d9686f373b6a672037880c81d44`。
回放 `event_replay.py`：`ac7e99c5779b297f52d27267303339031416e72f8f0acdeeb0a732226bee33ac`。

预标签操作口径：paired 覆盖分母为**全部提示**（含 raw 标签缺失），不是只算有效 raw；所有日历日期含最初热身零日参与抽样。见 [方法审查](DS2_METHOD_REVIEW.md)。引擎 17 项及回放 12 项合成测试已经通过；最终测试汇总另记，不把待执行事项写成已完成。

最近内存检查：总 3927 MiB，可用 2504 MiB。回放按日期流式处理，每标的仅当日及前 20 日摘要／前六根。将写新输出 `reports/ds2_development.json` 和 `data/ds2-development-signals-20260926.jsonl`；不覆写旧结果，不打开 valid 或新 ETF 价格。

## 首次完成

正式运行前再次检查内存可用2523 MiB。运行成功，155.37秒，峰值RSS125,664 KiB；输出1520条提示，晋级为空。报告SHA256 `458314927ad18ca9645a72799a1050d4c183f2463c171905c13a77d9a0535e0e`，事件SHA256 `6d9c4b5b7bdb97627d02f921ea01d0a9bf6c67e7dcafd4e1371de15549f5b2ec`。最终事件测试17项、回放测试13项、研究全套192项和custody149项通过。该事件指纹也固定为PERSISTENCE审计输入，不使用另一次重跑输出。
