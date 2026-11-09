# WF03 判定

判定为 **branch**（`completion.json` 的 decision，由 `pipeline.accept('trading')` 算出、核对步骤重算一致，见 `VERIFY.json`）。交易冻结版本仍为 C062，v1 不变，没有待合并的版本。

- 放行：Q1、Q2 通过全账本单票回放；Q3、Q4 未通过，T4、T5 删除。
- 测试台选择年峰前持有：C062 15；B0 16；T1 16（+1，未达 +3，且对照护栏不过）；T2 14；T3 12。无人合格，未跑留出与消融，未建冻结缓存。
- 机制：收盘判止损单票明显更好，但在 11 只名额下让没走出来的对照票占住名额，他的票进不来，净丢段。

交易线留出年按规则只报告，本轮没有最终版，`holdout_loss=false`。详见 [报告](REPORT_CN.md)、[预登记](PREREG_CN.md)、[核对](VERIFY.json)。
