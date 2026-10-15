# R28：间隔信号与较大周期确认

2026-10-14。按用户澄清，固定测试允许间隔、独立重复事件、3m／5m方向确认五种机制。**H3在开发集上通过全部G2–G13，结论PROVISIONAL；其余四版REJECT。没有候选达到事先设定的「优于V6.6」晋级条件，因此不登记V6.7、不更改默认或live资格。**

预登记：[R28_PREREG.md](https://github.com/QSothoth/s-alpha/blob/63ab1aa27ae9a56b423ce2b57ac06729c5f96edc/studies/us_0dte_picks/notes/R28_PREREG.md)。研究引擎：[confirmation.py](https://github.com/QSothoth/s-alpha/blob/63ab1aa27ae9a56b423ce2b57ac06729c5f96edc/studies/us_0dte_picks/confirmation.py)。没有改变R27的参数或历史结果，也没有打开旧09-18／SV1留出数据、取新行情或启动采集。

## 完整比较

同一已登记开发集 `custody-0dte-v6.1`：146个真实0DTE case、21日、73组同价CALL/PUT，真实期权成交模型、25%区间滑点和每张每边0.65美元费用全部不变。下表平均净收益按方向对称加权，未入场记0，不是账户收益率。

| 版本 | 完成笔数 | 每case平均净收益 | 盈亏比 | 利润因子 | 综合分50%／60% | 结论 |
|---|---:|---:|---:|---:|---:|---|
| V6.6 | 96 | +4.19% | 4.55 | 1.35 | 74.69／76.58 | PROVISIONAL |
| W2：5分钟内2次信号 | 56 | +1.70% | 3.79 | 1.26 | 66.12／69.73 | REJECT |
| W3：10分钟内3次信号 | 21 | +1.27% | 4.22 | 1.69 | 65.45／67.17 | REJECT |
| E2：15分钟内两次独立事件 | 30 | +1.49% | 3.63 | 1.56 | 63.66／67.58 | REJECT |
| H3：两根完整3m方向确认 | 29 | +2.96% | 5.62 | 2.14 | 69.20／69.20 | PROVISIONAL |
| H5：两根完整5m方向确认 | 17 | −1.15% | 1.51 | 0.32 | 27.74／29.44 | REJECT |

W2／W3允许普通停顿，窗口过期、VWAP／EMA方向失效或缺分钟则清空。E2要求完整信号true→false→true，连续true只算一次。

H3／H5使用按开盘对齐、不重叠、已完成的3m／5m块。最近两块都顺方向（块收盘相对开盘有利，且块完成时收盘在VWAP有利侧、EMA排列顺向），后一块收盘还要优于前一块；当前1m完整V6.6信号负责精确触发。未完成块不参与；退出、ATR和权利金模型仍用1m原规则。这里没有要求每根3m K线都重复完整V6.6突破。

## 通过和未通过的部分

| 候选 | 未通过门槛 | G13期望p值 | 解释 |
|---|---|---:|---|
| W2 | G13 | 0.104478 | 高于固定0.10，不能四舍五入通过，也未追加抽样救回 |
| W3 | G10、G13 | 0.114428 | 确认次数3→4的邻域失败 |
| E2 | G10 | 0.084577 | ATR周期14→10、VWAP距离上限2→1.5的邻域失败 |
| H3 | 无 | 0.009950 | G2及全部G3–G13通过；没有独立前向20日证据，最高PROVISIONAL |
| H5 | G4、G6、G9、G10、G11、G12、G13 | 0.388060 | 盈亏比不足2、整体负收益等，多项失败 |

H3已成交交易的平均净收益 **+14.90%**，原版 **+6.38%**；已成交胜率27.59%对22.92%，平均亏损18.03%对23.50%，中位持仓26分钟对18分钟。它在这份开发数据上提高了所选交易的质量，但少做67笔，计入未交易机会后平均收益仍为+2.96%对+4.19%。收益子分81.53高于76.92，而原标准含20%完成分，综合分69.20低于74.69。两种口径都保留，不能看完结果后换选择标准。

H3相对原版综合分差的按日配对重抽样95%区间为 **[−21.61, +7.79]**，未证明优越性。其余区间：W2 [−30.99, −0.61]，W3 [−45.80, −1.23]，E2 [−53.61, −0.71]，H5 [−62.93, −22.91]。预登记的简化留一天交叉选择21折全部保留V6.6；这不是每折完整门槛嵌套验证，更不是独立样本外。

本轮说明：允许间隔的两种窗口版本比R27对应相邻分钟版本好；更大周期中3m与5m的结果明显不同。不能由R27推断所有连续性机制都无效，也不能由H3推断所有较大周期都会有效。H3只冻结为研究配置，未经独立验证，不接入交易会话。

## 复现与检查

```bash
# 输出目录必须不存在，依次调用六次原 custody evaluate CLI。
python3 -m studies.us_0dte_picks.r28 --out /tmp/r28-reproduction
python3 -m unittest discover -s custody/tests
python3 -m unittest discover -s studies/us_0dte_picks/tests
```

研究引擎仅在临时隔离副本注册，原custody引擎代码和注册表本轮未修改。复用R27选择代码后，原R27的选择JSON计算结果逐项一致。V6.6完整官方报告与原报告JSON一致；研究源文件在运行前后哈希一致。

custody **191项**、研究切片 **113项**测试通过（共304项），新增测试覆盖间隔、失效、过期、去重、完整块、未完成块、缺分钟、反向块、多空对称及随机入场准确分钟。候选逐个运行，未并发大回测或增加依赖。

机器结果：[selection.json](https://github.com/QSothoth/s-alpha/blob/63ab1aa27ae9a56b423ce2b57ac06729c5f96edc/studies/us_0dte_picks/reports/R28/selection.json)。完整官方报告：[V6.6](https://github.com/QSothoth/s-alpha/blob/63ab1aa27ae9a56b423ce2b57ac06729c5f96edc/studies/us_0dte_picks/reports/R28/V6.6/REPORT.md)、[W2](https://github.com/QSothoth/s-alpha/blob/63ab1aa27ae9a56b423ce2b57ac06729c5f96edc/studies/us_0dte_picks/reports/R28/W2/REPORT.md)、[W3](https://github.com/QSothoth/s-alpha/blob/63ab1aa27ae9a56b423ce2b57ac06729c5f96edc/studies/us_0dte_picks/reports/R28/W3/REPORT.md)、[E2](https://github.com/QSothoth/s-alpha/blob/63ab1aa27ae9a56b423ce2b57ac06729c5f96edc/studies/us_0dte_picks/reports/R28/E2/REPORT.md)、[H3](https://github.com/QSothoth/s-alpha/blob/63ab1aa27ae9a56b423ce2b57ac06729c5f96edc/studies/us_0dte_picks/reports/R28/H3/REPORT.md)、[H5](https://github.com/QSothoth/s-alpha/blob/63ab1aa27ae9a56b423ce2b57ac06729c5f96edc/studies/us_0dte_picks/reports/R28/H5/REPORT.md)。H3冻结参数：[H3_config.json](https://github.com/QSothoth/s-alpha/blob/63ab1aa27ae9a56b423ce2b57ac06729c5f96edc/studies/us_0dte_picks/reports/R28/H3_config.json)。每个子目录包含逐笔、完整邻域、压力测试和随机对照结果。

本轮五个固定机制到此完成。下一次改规则或比较标准须事前登记；当前反复使用的21日开发集不足以认证新版本，未用过的验证数据仍是晋级所需证据。
