# 美股 0DTE：日 K 位置与早盘突破信号

当前目标是上游观察提示：日 K 找关键位置，盘前观察候选，开盘 15／20／30 分钟确认是否向上／向下离开该位置。允许没有信号。**不是高频交易，也不包办合约购买、持仓管理或退出；没有接入自动下单。**

此次提交的研究路径、已知问题、清理边界与核验顺序统一见[Review交接](notes/REVIEW_HANDOFF.md)；各轮冻结报告和预登记保留原判定，不用旧审计中“当时尚未试过”的表述覆盖后续结果。

新主线 [DS1 预登记](notes/DS1_PREREG.md) 比较昨日高低突破的共同触发对照、七日最窄区间（NR7）、内包日。信号输出方向、时点、价位、失效参考与空间；后续 30 分钟的胜率、平均盈亏比、PF、目标／失效先达与发生频率用于评价提示质量，**不是期权净收益，也不是给用户规定持有 30 分钟**。

[旧研究范围审计](notes/SIGNAL_SCOPE_AUDIT.md)已把可保留证据与失败边界分开：S22的波动候选池有有限证据，但不能直接给方向；[旧口径审计复现](reports/S22_AUDIT_CN.md)与原报全部显示值一致，实际原验证截至09/23，不是新增验证。S28/S29没有检验ETF或日K节点；W6的港股背景交互不能直接搬成美股突破规则。过去的失败全部保留，不把它们概括为“所有日K信号无效”。

行情继续只用 OpenD／Yahoo／腾讯。三份新采行情及一份固定旧日的来源复核已保存为可复用 Release，来源、zip SHA256 与逐文件指纹见 [DATA](../../docs/DATA.md)。RG1已一次性评测XLV／XLI／XLY截至09/24的分钟路径；另外九ETF分钟与全部09/25仍未评测。新分辨率、新研究目标不等于独立时间样本。

后续又发布三ETF的[分钟跨源复核](notes/RECENT_CROSSCHECK_20260924.md)、五轮[派生事件纯数据快照v2](notes/SIGNAL_RESEARCH_RELEASE.md)，以及[全部118次RG1图卡](https://github.com/QSothoth/s-alpha/releases/tag/or-rg1-cards-20260926-v1)。图卡解压打开index.html，只画提示当时已知的日K与早盘，事后标签另表展示，不挑漂亮案例。数据保存不是Alpha认证；含源码的旧v1已按用户确认撤下Release及同名数据tag，本地完整备份保留，其他Release不变。

[DS1首轮结果](reports/DS1_RESULTS_CN.md)：旧开发段1,091日期，NR7 318次、胜率52.52%／盈亏比0.93；内包204次、50.98%／1.01。两个结构都未稳定改善对照，未晋级。不要把实现了形态扫描等同于发现优质买入信号。

[DS2首轮结果](reports/DS2_RESULTS_CN.md)另检验活动日的20日边界突破、跳空守住、跳空收回，共1520条提示；三项均未通过，不据某个较好分组临时改选。实现按日处理，峰值约123MiB。[来源复核](notes/DATA_RECHECK_20260926.md)确认固定SPY旧日可复取，也发现跨周期量口径、零量平价条目（成因未确认）及合并旧盘前包的边界；[合约身份审计](notes/OPTION_IDENTITY_COVERAGE.md)区分真实0DTE、未知历史身份和盘后链时点，不能拿星期几代替合约查询。

## 当前信号工具

[RG1资产迁移结果](reports/RG1_RESULTS_CN.md)出现局部正向线索：三ETF的118条反向观察，30分钟胜率55.93%、平均盈亏比1.90。但对照覆盖与对照差值下限未通过，且约80%的净标签收益来自两个日期，不能晋级或宣称期权盈利。该反向假设是在看过DS2后提出，未消除多轮探索偏差。[AH1复核](reports/AH1_RESULTS_CN.md)的盘后背景及09:45卖压确认均未晋级。

[OM1真实0DTE桥接](reports/OM1_RESULTS_CN.md)固定原DS1规则，在已有真实合约的77标的日得到7次PD提示：正股5正2负；期权精确分钟标价4涨2跌1缺失。6条有效标价的幅度比2.239只是小样本毛标签，不是净盈亏比；NR7／内包仅为子集，不能把2/2上涨包装成100%胜率。该检查不改变DS1原判定、不接管购买或退出。

[全部7张OM1图卡与冻结记录](notes/OM1_CARDS_RELEASE.md)已发布，含失败与缺端点案例；下载解压后打开index.html，先看提示当时的20日日K与早盘，再到末尾查看独立的事后标签表。无需重新下载行情，不能用看过结果的图形重新挑选本批赢家。

```bash
# 旧开发数据的信号质量复现；输出必须不存在
python3 -m studies.us_opening_range.daily_replay \
  --out /tmp/ds1-report.json --signals-out data/ds1-signals.jsonl

# DS2固定开发规则复现，不会打开新ETF或自动晋级
python3 -m studies.us_opening_range.event_replay \
  --out /tmp/ds2-report.json --signals-out data/ds2-signals.jsonl

# 从冻结的118条RG1事件生成全部因果图卡，不计算新标签
python3 -m studies.us_opening_range.signal_cards --out data/rg1-new-cards

# 同样只重绘已冻结的全部7个OM1提示，含原231候选记录
python3 -m studies.us_opening_range.option_cards --out data/om1-new-cards

# 当天美东09:00–10:05，有限次只读扫描；目录必须不存在
/opt/futu-opend/venv/bin/python -m studies.us_opening_range.daily_scan \
  --symbols SPY,QQQ,META,NVDA --out data/ds1-new-observation --format markdown
```

扫描最多10标的，一次调用后结束；每次原始日K、5m、到期日／链、快照及请求时间都保存在新目录，带manifest和CHECKSUMS。`--format markdown`在终端给出中文摘要，默认JSON；两者使用同一份已保存结果，不改变提示或原始记录。无历史K请求、无下单、无定时任务；自己创建的订阅按服务端等待限制释放，单次调用至少约一分钟，十标的可能数分钟，必须留出扫描窗口。

盘前输出日K形态、双向触发区和可取得的已完成盘前5m事实，不给尚未确认的方向。开盘后只使用09:45／09:50／10:00已完成快照，首次提示保留，不因后来“应退出”而删除；最新可用已完成5m落后于最新应完成格时标 `STALE`。中间缺根也会记录错误并标数据缺失，不能把缺数据当成“没有信号”；较早已成立的提示仍保留。方向信号、当日真实标准到期链资格、流动性是不同字段：没有链不会抹去正股提示，挂牌也不代表盘口合格；期权流动性仍未验证，底层汇总期权量不等于0DTE成交量。

摘要分别列出结构失效参考、2R测量线和空间状态。`room_to_20d_boundary`只表示到已观测20日边界满足原规则的空间门槛；`beyond_observed_20d_range`表示越过历史范围、外侧空间未知，不能当成确定还有2R空间。正股2R测量线也不代表期权盈亏比或自动退出指令。

所有输出均为 `UNVALIDATED`。线上日K用OpenD K_DAY QFQ，开发回放用QFQ 5m聚合；[近期三ETF×20日来源检查](notes/DAILY_SOURCE_RELEASE.md)的240个OHLC及21项历史levels精确一致，但60个volume均不同，不能推广到全历史／全标的，仍标 `source_equivalence=unverified`。扫描入口已做mock/纯函数测试，尚未在真实盘前／开盘时段运行；有限来源检查不等于实盘窗口验收。不虚构买入概率，不选择或提交具体合约订单。

## 旧研究与复现

OR1–OR4的完整规则、成交／退出假设、旧扫描与采集命令已集中到 [执行研究复现附录](notes/OR_EXECUTION_REFERENCE.md)。代码、原报告和失败记录未删除；它们不是当前信号推荐入口。

[固定提示的跨期限审计](reports/PERSISTENCE_RESULTS_CN.md)并排保留30分钟、60分钟与收盘表现，不据此更改原判定。完整研究轨迹见 [计划](notes/ALPHA_PLAN.md) 与 [三小时继续探索记录](notes/EXPLORATION_3H_20260926.md)。

```bash
python3 -m unittest discover -s studies/us_opening_range/tests
```
