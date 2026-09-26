# AH1 首次开发运行记录

2026-09-26 04:54 UTC，首次真实标签计算前冻结。主控与另一实现agent交叉只读审查通过；两个候选、历史21日百分比ATR、原AH端点、共同09:45参考价、固定peer及双窗口均按登记，不增加筛选器。

- 预登记SHA256：`9893cd96bc4f465cfde339c9ba8d16d7ff495ddda70591113677828f7c4d900c`。
- `ah_replay.py`：`d173f71a72389a0b8056f602fc967557a919195e388fd9481f874b846cd243cb`。
- `tests/test_ah_replay.py`：`2f190236b25848d69c0d83e818e1fc80b12596eee5020ab65f108b6adeafd9fb`。
- AH1合成测试16项、研究全套234项与custody149项通过（研究总数包含并行完成的RG1）。

最近内存检查总3927MiB，可用2518MiB。按日流式处理，每股只保留21日日线、前一AH与当日有界K5。原55个CSV及对应清单/manifest/日历全部重新验签，先完成Decimal去重冲突检查才计算候选或标签。

计划新输出 `reports/ah1_development.json` 与 `data/ah1-development-signals-20260926.jsonl`，拒绝覆盖。范围仅旧11股2020-01-02至2024-05-31，所有收益均为已暴露开发诊断；不读取新ETF价格或09/25期权。

## 首次完成

04:54 UTC启动前内存可用2543MiB。一次运行完成，28.89秒，峰值115688KiB（约113MiB）。BASE169条、DOWN108条（全部与BASE重叠），均无晋级；主标签没有缺失，BASE的8条paired缺失保留。结果报告SHA256 `3228710a553ad47bfd91113ea7de48a7425d9e86034301403b42928ba0fc3890`，277行事件SHA256 `a8358ef73a1ca1fbc0f332580b2c3128dc037edbd450d3d0407d70e91a5966cf`。规则、输入与冻结实现未修改。
