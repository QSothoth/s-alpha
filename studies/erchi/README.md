# 二池：三日修复与回踩价格机制

成熟度 E1。真实A股日线/沪深300的四组冻结事件研究，含完整事件与严格拒单账簿。行业论据缺失，不能称二池完整策略；缺历史ST/涨跌停、手续费，不能称可成交组合回测或净收益。

运行：在仓库根目录执行 `python -m studies.erchi.replay --data-root data/salpha-champion-replication/data --output studies/erchi/reports/run_20261017`。

测试：`python -m unittest discover -s studies/erchi/tests -v`。数据只读；无联网、无订单接口。

先读 [预登记](notes/PREREGISTRATION.md)、[结果](reports/RESULTS.md)、[数据](reports/DATA_READINESS.md)、[映射](reports/RULE_MAPPING.md) 与 [未知](reports/UNKNOWN.md)。真实价格毛事件与0成交严格会计账簿分开，禁止把事件均值当成组合收益。
