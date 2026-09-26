# RG1全部因果图卡

`or-rg1-cards-20260926-v1`保存固定RG1的全部118次提示，按时点和标的排序，不筛赢家。解压后用浏览器打开`or-rg1-cards-20260926-work/index.html`：左图是提示前20个完整日K，右图是截至提示时的已完成早盘5m。纵轴独立，标出当时20日边界和参考价；**图中不放未来K线或未来收益**。

原事件文件按字节保留；已有30分钟标签只在index末尾的事后审计表展示。`contexts.jsonl`保留所有绘图输入，manifest记录原始源文件及脚本SHA，便于重新制图。原研究状态仍UNVALIDATED，RG1联合门槛未过；图形不是交易推荐或历史0DTE资格证明。

- 123个成员：118张SVG、index、contexts、原events、manifest和CHECKSUMS。三个ETF仅至09/24，未解析09/25行情。
- 全118张通过XML解析；按事先固定的第1／59／118张用本机浏览器检查，中文、时间／价格坐标与图例可读，无需外部字体服务或CDN。
- 导出器8项合成测试覆盖118事件全量导出、来源验签、截止日期、历史缺失、转义、因果／标签分离及拒覆盖。没有重算新收益。
- ZIP为349349字节，SHA256 `337f11771d1aadfb30f68a12c022351f1da6cba0db1d23442a50d332ee60c739`。
- CHECKSUMS SHA256 `ac50dd50fe0b354149c629e29d6af9629d81154ddccec2e2941f7b2e41776d21`。
- manifest SHA256 `905e8bcb42b8411b7d90eebd0b1d0128a6ab84ddad59a874f571df1b26c41d45`。

数据不进Git；tag锚定远端已有`45d0b620c6c05729adbe19daecb8cffe0fb218e3`，实际本地导出实现另按manifest指纹识别，不宣称该提交包含导出器。发布后不替换附件，变更另发tag；没有订单或长期采集。
