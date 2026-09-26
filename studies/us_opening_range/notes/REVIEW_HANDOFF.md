# 研究收敛与提交 Review 入口

2026-09-26。此次提交收录此前工作区中的研究实现、冻结结果、归档迁移及清理；**没有新一轮收益搜索，也没有把未通过的研究改判成功**。当前唯一推荐的观察入口为`daily_scan`，其输出仍是`UNVALIDATED`，不注册到custody、不下单。

## 路径与做法

1. [旧研究审计](SIGNAL_SCOPE_AUDIT.md)区分“波动候选池”“方向提示”“期权收益”，保留S22有限证据；S1–S29现存材料归档至`studies/archive/us_preopen_bias/`，原路径只留跳转说明。89个旧tracked文件全部有对应：87个字节不变，README更新路径，`daily_top.py`保留用户原`--dump`改动。S11–S20缺档是既有问题，未伪造补齐。
2. OR1–OR4先检验端到端交易组合，全部失败；用户澄清目标后转为DS1／DS2上游观察，见[旧执行附录](OR_EXECUTION_REFERENCE.md)。`daily_signals.py`和`event_signals.py`只处理当时可知的日K／已完成5m；固定未来窗口只作质量标签，不规定用户持有期。
3. 每轮先冻结登记、至多5候选、保留所有结果，不网格搜索。回放按标的／日期有界处理，研究峰值约113–133 MiB；本次收敛不重跑收益。PERSISTENCE只审计原提示的多个期限；AH1及RG1明示提出时点，不能把新标签／新资产说成全新独立时间。
4. `option_bridge.py`将原DS1提示映射到已有真实0DTE合约，使用精确、有成交量的分钟端点，缺失不补价。`signal_cards.py`／`option_cards.py`只重绘冻结事件，因果图与事后标签分离；不挑赢家。
5. `daily_scan.py`为1–10标的的单次OpenD只读入口：盘前不猜方向，09:45／09:50／10:00完成格确认；真实当日到期链与流动性分开，缺格／过时明示、历史提示保留。Markdown说明2R仅为正股测量线，越出20日范围时外侧空间未知。
6. 行情仅OpenD／Yahoo／腾讯；原始数据、事件与图卡留`data/`及[Release登记](../../../docs/DATA.md)，不加入Git。研究报告和源码进入此次提交。采集／打包入口不是自动服务，不能把本次取数授权理解为未来新增额度或长期采集授权。

## 已知问题的最终状态

| 问题 | 本次处理／当前结论 | 仍未解决的边界 |
|---|---|---|
| 旧方向研究是否应全扔 | 保留原失败；[S22审计](../reports/S22_AUDIT_CN.md)复现原显示值 | 只能支持原热门池的归一化波动筛选，不能外推ETF方向／0DTE净收益 |
| 日K关键位能否改善方向 | [DS1](../reports/DS1_RESULTS_CN.md)、[DS2](../reports/DS2_RESULTS_CN.md)、[AH1](../reports/AH1_RESULTS_CN.md)未晋级 | 没有可靠购买信号认证，不继续用同批结果调近邻参数 |
| RG1胜率／盈亏比看似较好 | [118事件复核](../reports/RG1_RESULTS_CN.md)保留55.93%／1.90原值 | paired覆盖／差值下限失败，两日贡献净标签和80.49%；历史0DTE身份未知 |
| 正股提示能否对应期权盈利 | [OM1](../reports/OM1_RESULTS_CN.md)7独立事件：期权4涨2跌1缺失 | 仅6个毛标价结果，无双边盘口／净成本；缺失META是零成交量端点，不能补邻价 |
| 实时与回放来源 | 有限旧日／近期价格核对及指纹保存 | 三ETF20日OHLC一致而volume全不同，整体来源等价性仍未验证 |
| 扫描是否已实盘窗口验收 | 19项mock覆盖时点、缺格、清理、资格与展示 | 真实早盘缓存发布延迟、跨标的时差、当日0DTE流动性仍未验收 |
| 数据是否被重新当作留出 | RG1三ETF截至09/24已用，09/25与其余九ETF分钟仍未评测 | 同市场日期有相关性；09/25链为盘后查询，不能反推完整开盘时点挂牌池 |
| 历史授权台账可否精确复原 | 实际范围、请求、额度、源文件与取数实现指纹均保留 | ETF manifest的`authorization_sha256`指向采集时动态`ALPHA_PLAN.md`；当前台账已更新，本次未找到与旧SHA一致的完整台账快照，不能用当前文档验证该旧SHA。各固定研究PREREG指纹另行核对一致 |
| 过期期权试验脚本仅在临时目录 | [原脚本](../../archive/opend_probes/option_history_pilot_20260918.py)与[原预登记](../../archive/opend_probes/OPTION_HISTORY_PILOT_PREREG.md)原字节归档，均匹配原manifest | 仅审计证据，不是重跑许可；未新增真实调用或研究标签 |

30交易日长期采集仍未获单独批准，因此未启动。普通历史额度只消耗此前批准的12个新ETF；独立期权历史试验只请求此前批准的SPY同一链。此次整理不访问行情接口。

## 清理与恢复边界

- 用户明确确认后撤下`or-signal-research-20260926-v1` Release、两个附件及同名远端数据tag，回读均不存在；纯数据v2及其他Release不动。旧v1完整ZIP、sidecar、31成员源目录仍在本地，SHA见[处置记录](SIGNAL_RESEARCH_RELEASE.md)。可恢复包内容，不承诺恢复远端对象ID／下载计数，不自动重发旧tag。
- 仅删除13个已核定临时目标，逻辑文件大小共67,795,252字节：两个OM1截图用浏览器profile、已验证与`data/`原件一致的Release重复下载包／sidecar、一次性试验的Python字节码。未泛清`/tmp`、数据目录或用户缓存。
- 原始行情、派生事件、失败／初版目录、PNG／浏览器日志、两份`verification.json`及原临时取数脚本均保留。验证记录位于`/tmp/research-release-verify.m4XhuT/verification.json`和`/tmp/om1-cards-release-verify.KNbLMD/verification.json`；Git报告亦保留验证结论，原包可以重新验签。仓库未跟踪缓存不作为待提交文件。
- Release的数据tag仍锚定发布时的旧提交，不重指向本次代码提交；复现需按manifest选择匹配源码和原输入。用户此前删除的旧分钟Release没有擅自恢复，异机复现仍受本地原数据可用性限制。

## Reviewer 建议顺序与离线验证

先看本页和README，再检查`daily_signals.py → daily_replay.py → daily_scan.py`的因果边界；随后检查`event_signals.py`、`reverse_replay.py`、`option_bridge.py`及对应PREREG／JSON。图卡与采集／打包为独立辅助层，旧OR代码保留作复现。12份机器报告的代码／来源／原报告等129个指纹引用与所列固定预登记均经独立核对；不要为方便阅读重写冻结JSON或原预登记。

以下是离线单元测试，不调用行情接口、不消耗留出或重跑真实收益。本次提交前共531项复验通过（304＋149＋23＋26＋19＋10）；异常分支测试打印的拒覆盖usage信息是预期输出，不是测试失败。

```bash
python3 -m unittest discover -s studies/us_opening_range/tests
python3 -m unittest discover -s custody/tests
python3 -m unittest discover -s studies/archive/us_preopen_bias/tests
python3 watch/test_watch.py
python3 -m unittest discover -s studies/auction_strength/tests
python3 -m unittest discover -s studies/hk_open_scan/tests
git diff --check
```

保留生产`custody`、`watch`及策略注册表原样；此提交不是实盘启用，也没有push。提交说明用英文记录目录路径、研究转向、方法、失败边界、清理和测试，供另一个agent继续审查。
