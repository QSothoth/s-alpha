# OM1：全部七个提示的因果图卡与冻结记录

2026-09-26，已发布[or-om1-cards-20260926-v1](https://github.com/QSothoth/s-alpha/releases/tag/or-om1-cards-20260926-v1)。本地打包与独立远端回下载的精确成员、逐文件SHA及CRC均通过；远端恰有ZIP和sidecar，ZIP与本地原件一致。解压后打开`or-om1-cards-20260926-readable-work/index.html`，无需服务端或外部资源。

本包保存[OM1诊断](../reports/OM1_RESULTS_CN.md)的全部7个独立事件：META、SPY、AAPL、SPY、MSFT、IWM、MU，按原日期排列。NR7／内包仅列重叠成员，不将7个事件放大成11个机会。图中左侧为此前20个完整日K，右侧为提示时已完成的早盘5m；没有未来行情或收益。原始231候选记录、机器报告及独立事后表含已有标签，不属于当时可知信息。

期权有6条有效标价、1条缺合格端点；全部保留，不挑赢家。价格是同分钟成交K线毛标价，不是可成交bid／ask或净收益，也没有接管购买、持仓或退出。图卡及研究继续标`UNVALIDATED`，不是晋级或新验证。

## 内容与指纹

- 14成员：7张SVG、`index.html`、`contexts.jsonl`、原字节`records.jsonl`、`om1_diagnostic.json`、`OM1_PREREG.md`、`manifest.json`、`CHECKSUMS.sha256`。
- ZIP：40997字节；SHA256 `807107c5fdda318764a8ddad13ede873ff7e96883324503e90a0f28eee29d729`。
- CHECKSUMS：`b548a56a6356a770edd8ea7c750a355f5d612530a22e849acd54580c8af9966e`。
- manifest：`58da13f0a5b48e797635fe558a8aabbcd74b6721c0eb1ad501c2b0a2eddd612b`。
- ZIP sidecar：`52dab7059bd898b60598ca90b8de627888781cdbbcfe2b4aa32a9fa4059f1a6b`。

原记录SHA为`3896a22dd3d31317e3ab6838db2fab69374dd5f53195c1d6c49c0227e5c6141d`，机器报告SHA为`559db24b93f1006130c050fd819e0ddc96c72b131888090e670666206fb426c4`；预登记、输入源与实现SHA同时保存在manifest。没有源码或原始全量行情；发布时实现仍在工作区，之后由独立Git提交保存。tag仍锚定既有远端提交`45d0b620c6c05729adbe19daecb8cffe0fb218e3`，不代表该提交已包含本地新实现，不重指向新代码提交。重绘需要匹配源码／原输入，直接看图及复核冻结记录不需重新取行情。

## 展示检查与保留过程

初次导出保存在`data/or-om1-cards-20260926-work`，未发布、未覆盖。浏览器检查发现部分文字被蜡烛实体遮挡、邻近价位标签重叠，因此仅在OM1启用文字置顶、白描边及17像素避让，再导出至新目录`data/or-om1-cards-20260926-readable-work`。

新旧7张全部水平线／蜡烛几何、全部价格文本一致；contexts、231记录、机器报告、预登记及index逐字节相同。当前共享渲染器的默认RG1路径仍与已保存118张SVG逐字节相同，旧Release不变。主控用本机浏览器复查全部7张新版，中文、日期、价格与图例可读；未来标签仍独立列在index末尾。

图卡专项15项、全部研究303项及custody149项测试通过，独立只读审查无阻断；未计算新标签、调用行情、消耗额度或启动后台采集。发布后不替换附件，变化另发tag。

```bash
# 使用已冻结OM1输入重新导出；新目录必须不存在
python3 -m studies.us_opening_range.option_cards --out data/om1-new-cards
```
