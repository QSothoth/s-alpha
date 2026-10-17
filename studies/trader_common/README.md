# 33对象逐人研究总索引

本次不是33套比赛账户复刻。原Martin研究完整保留；新代码区分实际运行的局部假设、非交易事件/筛选、工程契约与来源阻塞。结果有真实输入和时序审计，仍无独立样本外或收益保证。

## 覆盖清单

- Martin Luk：EXISTING_BASELINE_IMMUTABLE；[研究入口](../martin_luk/README.md)。主要边界：局部可执行；现研究只作为深度基准和待审查结果，不能把代理或外推称本人复现
- Mark Minervini：EXECUTED_DAILY_LIMITED_HYPOTHESES；[研究入口](../mark_minervini/reports/FINAL_CN.md)。主要边界：局部可执行：源规则扫描与冻结代理分开；先检验形态和风险自适应各自贡献
- Ryan Pierpont：EXECUTED_DAILY_LIMITED_HYPOTHESES；[研究入口](../ryan_pierpont/reports/FINAL_CN.md)。主要边界：框架可研究：候选层及人工标签先行；不能默认所有扫描通过者都被本人买入
- Afzal Lokhandwala：SOURCE_INSUFFICIENT_NO_FAKE_IMPLEMENTATION；[研究入口](notes/COVERAGE_AND_ACCEPTANCE_CN.md)。主要边界：原版阻塞；先补本人案例和交易周期，不能用通用VCP冒名
- Gemy Zhou：MODEL_BLOCKED_ARCHITECTURE_TESTED；[研究入口](../gemy_zhou/reports/FINAL_CN.md)。主要边界：原版阻塞；可做独立ML研究，但必须另名；日线替代无效
- Sean Ryan：EXECUTED_DAILY_LIMITED_HYPOTHESES；[研究入口](../sean_ryan/reports/FINAL_CN.md)。主要边界：局部可执行：第二波、背离退出、加仓分离测试；不得默认RSI14为原规则
- Goverdhan Gajjala：EXECUTED_MINUTE_DOMAIN_DIAGNOSTIC；[研究入口](../goverdhan_gajjala/reports/RESULTS.md)。主要边界：框架可研究且需分钟数据；禁止转为日线波段，禁止用日均成交量代替紧急退出深度
- Christian Flanders：EXECUTED_DAILY_LIMITED_HYPOTHESES；[研究入口](../christian_flanders/reports/FINAL_CN.md)。主要边界：局部可执行：尾部赢家/退出/风险实验；不把220%单票曝光当固定配置
- J Law / Law Wai-Sum：EXECUTED_MINUTE_LIMITED_HYPOTHESES；[研究入口](../j_law/reports/r2_minute/FINAL_CN.md)。主要边界：框架可研究：相同入场检验差异退出；不能归成香港股票策略
- Vibha Jha：EXECUTED_DAILY_LIMITED_HYPOTHESES；[研究入口](../vibha_jha/reports/FINAL_CN.md)。主要边界：局部可执行；优先ETF简单市场状态对照，禁止指数多日收益乘三或把长期个股强制短波段化
- Ty Rajnus / Rajnus Capital LLC：EXECUTED_NONTRADING_EVENT_OR_SCREEN；[研究入口](../ty_rajnus/reports/FINAL_CN.md)。主要边界：原版与可实现净收益阻塞；无借券只能价格事件研究，不能假设永远可借
- Clement Ang：EXECUTED_MINUTE_LIMITED_HYPOTHESES；[研究入口](../clement_ang/reports/r2_minute/FINAL_CN.md)。主要边界：局部可执行，优先源参数筛选；不能回填为2024/2025原版规则
- Deepak Uppal：EXECUTED_MINUTE_LIMITED_HYPOTHESES；[研究入口](../deepak_uppal/reports/FINAL_CN.md)。主要边界：局部可执行：筛选和风险预算先行；3R目标不等于实际平均盈亏比
- Roy Mattox：SOURCE_INSUFFICIENT_NO_FAKE_IMPLEMENTATION；[研究入口](notes/COVERAGE_AND_ACCEPTANCE_CN.md)。主要边界：框架可研究；教学60%–70%不能当实测胜率，价格止损不能当账户风险
- Tanmay Khandelwal：SOURCE_INSUFFICIENT_NO_FAKE_IMPLEMENTATION；[研究入口](notes/COVERAGE_AND_ACCEPTANCE_CN.md)。主要边界：框架可研究且印度范围；美国/A股/港股迁移须另设假设；不可与Aryan混同
- Judy Lai：SOURCE_INSUFFICIENT_NO_FAKE_IMPLEMENTATION；[研究入口](notes/COVERAGE_AND_ACCEPTANCE_CN.md)。主要边界：原版阻塞；单独研究身份与来源，不能复制J Law规则后冠名Judy
- Leos Mikulka：SOURCE_INSUFFICIENT_NO_FAKE_IMPLEMENTATION；[研究入口](notes/COVERAGE_AND_ACCEPTANCE_CN.md)。主要边界：框架可研究：风险轨迹/集中度研究优先；缺完整触发不得硬造策略
- Adrian Law / WhiteBear.trading：SOURCE_INSUFFICIENT_NO_FAKE_IMPLEMENTATION；[研究入口](notes/COVERAGE_AND_ACCEPTANCE_CN.md)。主要边界：原版阻塞；不得与J Law因姓名相似合并
- Pavel P. Sterba：SOURCE_INSUFFICIENT_NO_FAKE_IMPLEMENTATION；[研究入口](notes/COVERAGE_AND_ACCEPTANCE_CN.md)。主要边界：原版阻塞；不从冠军收益反推模型
- Hsiu-Ping Peng：SOURCE_INSUFFICIENT_NO_FAKE_IMPLEMENTATION；[研究入口](notes/COVERAGE_AND_ACCEPTANCE_CN.md)。主要边界：原版阻塞
- Sam Bhatia：SOURCE_INSUFFICIENT_NO_FAKE_IMPLEMENTATION；[研究入口](notes/COVERAGE_AND_ACCEPTANCE_CN.md)。主要边界：原版阻塞
- Sean Goodsell：SOURCE_INSUFFICIENT_NO_FAKE_IMPLEMENTATION；[研究入口](notes/COVERAGE_AND_ACCEPTANCE_CN.md)。主要边界：原版阻塞
- Moritz Reinhart：SOURCE_INSUFFICIENT_NO_FAKE_IMPLEMENTATION；[研究入口](notes/COVERAGE_AND_ACCEPTANCE_CN.md)。主要边界：原版阻塞
- Luis Carlos Tarin：SOURCE_INSUFFICIENT_NO_FAKE_IMPLEMENTATION；[研究入口](notes/COVERAGE_AND_ACCEPTANCE_CN.md)。主要边界：原版阻塞
- Miguel Zambrano Sánchez：SOURCE_INSUFFICIENT_NO_FAKE_IMPLEMENTATION；[研究入口](notes/COVERAGE_AND_ACCEPTANCE_CN.md)。主要边界：原版阻塞
- 张棋：EVIDENCE_OR_ACCOUNTING_ONLY；[研究入口](../zhang_qi/README.md)。主要边界：框架可研究：技术价格反转与主题判断分开；不能假设所有ETF同一市场制度
- 叙市：EVIDENCE_OR_ACCOUNTING_ONLY；[研究入口](../xushi/README.md)。主要边界：原版阻塞；保留独立身份记录但不计算为两个独立成功样本
- Li666：EXECUTED_NONTRADING_EVENT_OR_SCREEN；[研究入口](../li666/reports/RESULTS.md)。主要边界：框架可研究：案例事件表先行；不得用“低价买入”替代原研究过程
- 二池：EXECUTED_NONTRADING_EVENT_OR_SCREEN；[研究入口](../erchi/reports/RESULTS.md)。主要边界：局部可执行的代理研究；禁止简化为连板打板，禁止事后挑产业主线
- 这股有毒：EVIDENCE_OR_ACCOUNTING_ONLY；[研究入口](../zhegu_youdu/README.md)。主要边界：框架可研究且必须拆模式；不得把总收益归给纯股票趋势策略或称转股无风险套利
- 归因：EVIDENCE_OR_ACCOUNTING_ONLY；[研究入口](../guiyin/README.md)。主要边界：原版阻塞；不能把网络“低吸”归纳当本人规则
- 低调科科员：EVIDENCE_OR_ACCOUNTING_ONLY；[研究入口](../didiao_kekeyuan/README.md)。主要边界：原版阻塞；半年度冠军不可改全年冠军
- 投资如人生：EVIDENCE_OR_ACCOUNTING_ONLY；[研究入口](../touzi_ru_rensheng/README.md)。主要边界：框架可研究：杠杆压力与退出研究先行；不得把自述十个月与半年赛事混算

## 关键解释

1. 日线FD/MD用原始价格、全窗口无登记公司行为的回顾性样本；该事后筛选与当前存续名单造成选择偏差，不能部署外推
2. CM/JL/DN用真实1分钟/已完成5分钟及SEC时点数据，但QFQ是调整单位账本，不是真实历史股数/执行收益。目标3R不是实际平均盈亏比
3. Vibha/Sean/Pierpont含独立数据/技术/PIT分层，复权因子单位和可部署原始账本须区别；Vibha长仓与ETF未形成同窗口统一资金轮换
4. Gajjala小盘/低流通完整筛选仍缺PIT流通盘与报价；大盘域测试、15名5分钟样本不能叫原小盘策略验证
5. Ty只有真实事件价格路径，borrow未知不计算可实现卖空利润；Gemy只有工程契约，不造原模型
6. 中国方法按T+1/涨跌停/资金流/ETF制度分层，无法确认可卖条件不生成成交。新的可用ETF数据可能另开明确预登记轮次
7. 来源公开胜率/收益只作来源事实；本文不以冠军收益校准参数，未取得同口径流水就不做虚假对齐
8. 所有正、负和零信号结果完整保存；superseded目录为审计前废弃结果，不能引用作当前结论

## 复现

见REPRODUCE_CN.md、DATA_INPUTS.json和每人运行清单；原始输入不进Git，仅公开Release/公开来源或单独本地研究数据包。没有访问Mac/VPS/SSH/券商，没有付费额度或远程推送。
