# 张棋：真实行业ETF反转机制

最新阶段使用12个真实行业ETF，执行原先冻结的三组技术机制；成熟度E1，价格经济账簿与严格不可执行账簿分离。不是张棋完整方法、比赛收益复刻或净总回报。原“无ETF语料”E0审计作为历史保留，新增数据阶段另行报告。

实际回放：`python -m studies.zhang_qi.replay --data-root data/trader-data/china-etf --output studies/zhang_qi/reports/etf_run_20261017`。

账簿校验：`python -m studies.zhang_qi.checks studies/zhang_qi/reports/etf_run_20261017`。测试：`python -m unittest discover -s studies/zhang_qi/tests -v`。

见[原预登记](notes/PREREGISTRATION.md)、[结果前执行解释](notes/EXECUTION_INTERPRETATION_20261017.md)、[结果](reports/RESULTS.md)、[数据与未知](reports/DATA_READINESS.md)。冻结名单、输入/源码指纹和所有逐日库存/订单/成交/行动账簿均保留。
