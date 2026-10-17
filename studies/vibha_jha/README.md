# vibha_jha 独立研究切片

先读 [阶段报告](reports/STAGE_CN.md)、[最终限制与结果](reports/FINAL_CN.md)、[来源映射](source_rule_map.csv) 和 [预登记](notes/PREREG_CN.md)。这是来源启发的逐日收盘机械假设研究，不是本人比赛账户复刻。

运行：`python -m studies.vibha_jha.run --data data/trader-data/public-daily`

仅标准库；不调用券商、不取新行情额度、不下单。价格和原始行情留在研究数据目录，不提交git。输出保留数据指纹、源码指纹、实际命令、净成本单位账本、权益和事件日志。共用的是 `studies/sean_ryan/daily_engine.py` 会计/执行组件，三人的信号并不共享同一条突破模板。

测试：`python -m unittest discover -s studies/sean_ryan/tests -v`；各自测试目录含本人机制补充测试。
