# 固定提示路径审计：首次运行记录

2026-09-26，首次读取新增60分钟／收盘标签之前冻结：

- 登记 `PERSISTENCE_PREREG.md` SHA256：`b297fb6d5876e57a9e291990a5ac79fedd4b3115db6a7299efa3889b798c4f29`。
- 实现 `persistence.py` SHA256：`90fdffebbd6a476f6f2a939a0fd70761b6208631bbece167b666af7f1821688b`。
- DS1事件SHA256：`a56fb5d964daf9954ef7fbd1f1af457fcbb8b0065289bbc1d6ae873bf8ec1004`。
- DS2首次事件SHA256：`6d9c4b5b7bdb97627d02f921ea01d0a9bf6c67e7dcafd4e1371de15549f5b2ec`，对应报告SHA256：`458314927ad18ca9645a72799a1050d4c183f2463c171905c13a77d9a0535e0e`。

12项合成测试已通过；运行前可用内存2508 MiB。只读取原开发数据和固定事件，不运行新detect，不打开新ETF／09-25期权标签。全部4类×3期限并排报告，无选择／晋级。新输出为 `reports/persistence_development.json` 和 `data/persistence-development-labels-20260926.jsonl`，不可覆写。全套测试与运行结果完成后另记。

完成：63.23秒、峰值RSS130,396 KiB，3228条固定事件，原30分钟标签与固定peer逐项复核通过。JSON报告SHA256 `e521355a7d4a5fddfed4e35566266b146b2dcd87d42d10d161f79579a525fb61`，新标签SHA256 `786f01cb13e28e2d2e19383b6027c049b84100a3090221e8273e8229becd4c58`。研究204项与custody149项测试通过。原候选状态不变，没有晋级逻辑。
