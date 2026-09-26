# S22旧口径审计复现计划

2026-09-26，重新计算标签前登记。这不是新策略预登记、第二次样本外验证或新Alpha候选。主控和审查者已经看过S21／S22原报告；本轮仅问：固定原文件、原规则与原统计，能否复现已公布的数字，并保存可复核的派生事件。全部输入早已暴露，不恢复留出身份。

## 固定对象与指纹

只用本地 `data/preopen-s21-select-v1` 和 `data/preopen-s21-valid-v1`。先验全部CHECKSUMS及各文件，失败则不计算标签；不补数据、不联网、不读新12ETF或09/25，不改归档代码与数据。

| 数据包 | CHECKSUMS.sha256的SHA256 | manifest.json的SHA256 |
|---|---|---|
| preopen-s21-select-v1 | `9fd9ece38757cfe115512b7c94d78ee7da2930ef3cdbf1448072484587e7f1a0` | `1f4f324dca3958a5d71e3ae568811ea65fc65ae1148072b3fd8c0433ceee7486` |
| preopen-s21-valid-v1 | `42b8a0b53c69cac1152696de25e61660ff79f036b4e1534b343ec2b88c55e677` | `9f6ed130d7033db039f82d60cd31bedba0f42b601c3b44dffa369e286cd0b44f` |

固定34只池（不是历史逐日可知池）：AA、AAOI、ABVX、ACAD、AG、ALB、APLD、CDE、CLF、CRML、FSLY、HIMS、HL、IBRX、IONQ、IOVA、IREN、KGC、LQDA、MP、QBTS、RARE、RGTI、RIOT、SLS、SMCI、SVRA、TEM、TTD、U、UEC、USAR、UUUU、VKTX。来自2026-09-24热门名单36只剔除KOD／AVTX，保留事后选池偏差。

归档路径均在 `studies/archive/us_preopen_bias/`：

| 文件 | SHA256 |
|---|---|
| code/preopen.py | `f95b01702c5a5c3ce699706cab0437dce5ca93b8274a6fa6871c900fd6425f95` |
| code/picks.py | `b3fefbc63dfa2799e3667a9cf33f20c4bbdb6971d90bd80384d3c8bea5c75850` |
| notes/S21_PREREG.md | `5c5112e875323e9ed59f1bfddde4463d3bd756029c7cc0ddcdbaadd97169bb26` |
| notes/S22_PREREG.md | `37f647981b5dd25980b7fe630cd22c355e7aa14ad365e24c5a8ee5dea655d769` |
| notes/universe_smallmid.json | `891277ab17f755938b33eb3251fb700bc42b7a3670124f885f34e8477ac572d0` |
| reports/s22_select_raw.txt | `6cf014b7ec1393040cd8b720058834f4322db3168cb98c7ea2ea958eea1d81e7` |
| reports/s22_validation_raw.txt | `ecb969c245c27e8975d8a8f4443c0264626a7ebd7302cd614ed97c89b883c893` |

这些是本次冻结的现存归档版本，不声称原文字报告已经记录了当时执行代码的完整指纹。新增薄包装、测试和本计划的运行前指纹另写 `S22_AUDIT_RUN_RECORD.md`。

## 不改变的规则、缺失与统计

- 选择段请求2023-08-01→2024-12-31，只加载选择包；验证段请求2025-01-02→2026-09-24，按顺序加载选择包、验证包作热身。元数据审计已知验证daily与option_stats实际止于09/23，共432日期；09/24仅有部分辅助表，不能写成完整评测日。输出同时记请求边界、实际daily边界和准入日期范围。
- 复用归档 `preopen.load/build`、`picks.eligible_days/pools/p1_gap_go/p3_pm_volume_go/pick_items/score_magnitude/range_ratio/score`，不使用 `evaluate.py/run_round.py` 的其他规则。每次只加载一个symbol，保留S22需要的紧凑字段，按日组合固定池，不保留全池宽特征或分钟矩阵。
- 名义close≥5、ATR14≥0.5、过去20日均成交额≥1000万及精确前一日记录期权量≥5000沿原实现。T−1是各股票之前的日线记录，不新增交易日历修补。缺期权记录不回退；当日C/H/L可用性门禁保留并披露，不能为改进因果表述而悄悄改变队列。
- M1：gap/ATR20向上≥0.5、向下≤−0.5，各取前三；M2：pm_ratio≥2、按gap正负各取前三。保留原symbol并列排序。ATR20为前20记录的 `mean(TR_j / C_{j−1})`，不是名义ATR。M2过去20记录中仅取有正盘前成交额的记录，至少15个即允许；不新增完整盘前网格条件，零量与缺失沿原语义。
- 幅度是 `abs(C/O−1)/ATR20`，振幅是 `(H−L)/O/ATR20`。分母为同日全准入池、包含入选自身；每个入选条目重复带入该日池均值，最终取两个均值的比，不改成留一peer、每日等权或逐日比值均值。
- 仅有入选的日期参加日期聚类bootstrap，2000次，seed=20260925。95%区间用排序后的第50及1949项（零起算），原“90%下限”用第100项；不改成线性插值，不加入零信号日期。方向命中仅复核原报告的描述项，不测试新方向规则。
- 原判定仍是幅度倍数≥1.2、振幅倍数≥1.2、幅度90%下限>1.0。本次只记录原判定是否复现，不授予新的验证身份。

## 执行与差异处理

先用合成数据验证统计等价、含自身且按事件加权的分母、缺精确前日期权记录及PM至少15个正观测的语义，再跑研究测试和custody测试。真实运行前查内存，记录时间／峰值RSS；选择与验证各只计算一次，不运行旧payoff模式或新期限。

新输出固定为 `reports/s22_audit.json`、`data/s22-audit-20260926.jsonl`，拒绝覆盖。保存每条入选事件的原特征、标签、池分母及segment，两个名单重叠不计成独立样本。原报告只有显示精度的数字，故逐行比较原CLI可显示字段，另保存本次未四舍五入值；不能声称知道原报告未保存的全精度值。

若选择段不一致，保存差异并停止，不运行验证段；若验证段不一致，保存差异并停止。不得改算法、门槛、输入或删样本来凑原数字。成功或失败都写中文审计报告，保留全部差异与实际覆盖；没有新行情或历史额度请求。
