# 35位交易员风格与实现状态索引

截至 2026-10-20。由 registry.json 生成；33位原对象与2位追加方法参考分组。风格是证据摘要，不是推荐或收益评级。

实现列只描述当前 main；历史研究分支代码链接见每人的详细记录。未知保持未知，未实现不等于方法无效，已有局部代码也不等于本人完整系统已复现。

[使用说明与查询方法](README.md) · [来源覆盖与限制](dossiers/AUDIT_CN.md) · [机器可读注册表](registry.json)

## 原研究33人

| 人物 / ID | 市场 | 风格 | 周期 | 多空方法 | 证据 | main 实现状态 |
|---|---|---|---|---|---|---|
| [Martin Luk](dossiers/swing/martin_luk.md) / `martin_luk` | 美国股票 | 高波动强势股趋势突破；趋势回撤与AVWAP（main有后期访谈自动字幕整理，适用版本仍需核对）；低胜率、尾部赢家与分批退出 | 日线趋势背景；开盘早段1分钟、之后5分钟触发（main的访谈自动字幕整理；需保留版本）；波段持有；完整持仓分布unknown | long: 强势股突破与趋势回撤；short: 下降均线/高点AVWAP阻力、前一小时低点破位或VWAP回测失败；属于分日期研究披露 | primary_rules_partial | MAIN_EXECUTED_LIMITED_HYPOTHESES |
| [Mark Minervini](dossiers/swing/mark_minervini.md) / `mark_minervini` | 美国股票 | SEPA成长股趋势；相对强度与VCP收缩突破；渐进风险和环境适应 | 日/周线选股与结构；波段，历史上亦有较长持有；统一天数unknown；精确盘中触发频率unknown | long: 强势成长股低风险枢轴/收缩突破；short: unknown（未取得可重建独立空头系统的原始资料） | primary_rules_partial | EXECUTED_DAILY_LIMITED_HYPOTHESES |
| [Ryan Pierpont](dossiers/swing/ryan_pierpont.md) / `ryan_pierpont` | 美国股票 | 成长股中期底部突破；少量集中持仓；兼顾本职工作的观察表流程 | 日/周线研究；3–6个月底部是经验范围；数周至数月持有；精确订单频率unknown | long: 成长强股整理后突破；short: unknown（无足够原始规则） | interview_framework_partial | HISTORICAL_RESEARCH_BRANCH_ONLY |
| [Afzal Lokhandwala](dossiers/remaining/afzal_lokhandwala.md) / `afzal_lokhandwala` | 美国股票（本人网站自述）；印度股票（本人网站自述）；其他市场（具体范围unknown） | 量价趋势；市场适应：顺境交易、逆境休息 | 数周至数月波段（2023问答）；具体信号频率unknown | long: 寻找上升或即将上升的量价结构；short: unknown；衍生品方法: unknown（增强增长组与股票组分开） | interview_framework_partial | SOURCE_INSUFFICIENT_NO_FAKE_IMPLEMENTATION |
| [Gemy Zhou](dossiers/active/gemy_zhou.md) / `gemy_zhou` | 美国股票（报道案例）；完整时点股票池unknown | Python机器学习驱动；自动订单与人工隔夜覆盖 | 盘中多笔，报道案例约十几至二十分钟；完整持有期分布unknown；可能隔夜，非已证每日强制平仓 | long: 模型驱动买入，精确信号unknown；short: 模型驱动卖空，精确信号及借券规则unknown | interview_framework_partial | HISTORICAL_RESEARCH_BRANCH_ONLY |
| [Sean Ryan](dossiers/swing/sean_ryan.md) / `sean_ryan` | 美国股票；美国ETF（含NUGT等杠杆产品） | 第一波后整理的第二波；图表与相对强弱；RSI背离辅助退出和风险管理 | 日线结构与波段；原始触发粒度和统一持仓天数unknown | long: 第一波后整理再启动；short: 已有弱市/房地产做空讨论，完整触发和止损unknown | interview_framework_partial | EXECUTED_DAILY_LIMITED_HYPOTHESES |
| [Goverdhan Gajjala](dossiers/active/goverdhan_gajjala.md) / `goverdhan_gajjala` | 美国低流通小盘股票 | 日内多头动量；自然回调与牛旗；EMA Kiss and Fly、Intraday VCP等教学结构分开 | 5分钟为主，少量15分钟（本人问答）；日内；完整隔夜例外unknown | long: 动量推进后自然回调/枢轴突破；short: unknown（已核方法以多头为主） | primary_framework_partial | HISTORICAL_RESEARCH_BRANCH_ONLY |
| [Christian Flanders](dossiers/active/christian_flanders.md) / `christian_flanders` | 美国股票 | 强势股突破与VCP；EP事件驱动；少数长赢家及成功后加仓 | 日线结构与波段；赢单通常较输单持有更久（年度自报统计）；具体盘中频率与统一持仓期unknown | long: 趋势/高点突破及EP；short: unknown（未取得完整原始空头系统） | primary_rules_partial | EXECUTED_DAILY_LIMITED_HYPOTHESES |
| [J Law](dossiers/active/j_law.md) / `j_law` | 美国股票；ETF（含杠杆/反向产品；时期和账户分开）；香港股票（早年经历，不代表现方法专属港股） | 强行业强股与基本面/主题结合；swing与position分流；多空随环境切换及递减加仓 | 数日至数月；熊市亦转日内减少隔夜；原始统一触发频率unknown | long: 强牛市强行业强股回撤；基本面决定短波段或长持；short: 熊市反弹做空弱行业弱股；借券及精确规则unknown | primary_framework_partial | HISTORICAL_RESEARCH_BRANCH_ONLY |
| [Vibha Jha](dossiers/swing/vibha_jha.md) / `vibha_jha` | 美国成长股；美国杠杆指数ETF（TQQQ） | 成长股较长期持有；TQQQ市场恢复阶段波段；盈利后向个股轮换的自述流程 | 成长股可超过一年；ETF日/周线恢复阶段波段；全年频率与平均持有期unknown | long: 成长股及TQQQ恢复阶段；short: unknown（TQQQ多头不是做空） | secondary_framework_only | HISTORICAL_RESEARCH_BRANCH_ONLY |
| [Ty Rajnus](dossiers/active/ty_rajnus.md) / `ty_rajnus` | 美国微小盘股票；SPX 0DTE期权（个人交易线索，非2025股票比赛账簿） | 系统化过热微小盘日内做空；融资稀释/流动性研究；2026做多微盘变化仅本人帖镜像线索 | 日内为2025股票方法主线；全平时间及隔夜例外unknown | short: 2025股票比赛据其介绍为全做空；精确触发unknown；long: 2026本人帖镜像提到微盘做多，规则unknown；不能扩写为终身只做空或从不做期权 | interview_framework_partial | HISTORICAL_RESEARCH_BRANCH_ONLY |
| [Clement Ang](dossiers/active/clement_ang.md) / `clement_ang` | 美国股票；杠杆ETF（历史案例） | 动量波段与趋势收缩；model book人工识别；2026向position trading探索 | 日/周线结构；2026常观察开盘30分钟，部分例外观察首15分钟；波段向较长持有探索；固定天数unknown | long: 强势股收缩/回调，2026两层ADR筛选；short: 观察表有空头线索及早年尝试，完整成熟系统unknown | primary_rules_partial | EXECUTED_DAILY_LIMITED_HYPOTHESES |
| [Deepak Uppal](dossiers/active/deepak_uppal.md) / `deepak_uppal` | 美国成长股；美国杠杆ETF | 强势成长股短波段；杯柄、旗形与支撑回踩；顺风反馈下渐进风险 | 通常数日波段，亦有同日结束案例；具体原始信号频率unknown | long: 强势股技术支撑入场与约3R/情境提前退出；short: unknown（多资产经历不等于公开空头系统） | secondary_framework_only | HISTORICAL_RESEARCH_BRANCH_ONLY |
| [Roy Mattox](dossiers/remaining/roy_mattox.md) / `roy_mattox` | 美国股票 | 集中成长股；回调企稳转强；顺境加风险及浮盈保护 | 波段框架；具体触发频率和平均持有天数unknown | long: 强势成长股回调企稳后参与；short: unknown | secondary_framework_only | SOURCE_INSUFFICIENT_NO_FAKE_IMPLEMENTATION |
| [Tanmay Khandelwal](dossiers/remaining/tanmay_khandelwal.md) / `tanmay_khandelwal` | 印度股票 | BEST成长投资；基本面、盈利、相对强度与管理层研究 | 通常持有超过五个月（原节目说明）；信号频率unknown | long: 印度成长股框架；short: unknown | secondary_framework_only | SOURCE_INSUFFICIENT_NO_FAKE_IMPLEMENTATION |
| [Judy Lai](dossiers/remaining/judy_lai.md) / `judy_lai` | 股票（比赛组别已核，具体市场unknown） | unknown（关联方声称执行MYT计划，未取得本人完整方法） | unknown（触发频率及持仓期未核） | long: unknown；short: unknown | identity_and_results_only | SOURCE_INSUFFICIENT_NO_FAKE_IMPLEMENTATION |
| [Leos Mikulka](dossiers/remaining/leos_mikulka.md) / `leos_mikulka` | 美国股票（ARM/SMR等二手访谈案例） | 成长主题波段；底部突破与集中持仓（事后采访整理，待原声核验） | 波段；赢家/输家持有差异为二手统计，原始频率unknown | long: 成长主题突破线索；short: unknown | secondary_framework_only | SOURCE_INSUFFICIENT_NO_FAKE_IMPLEMENTATION |
| [Adrian Law](dossiers/remaining/adrian_law.md) / `adrian_law` | 股票（比赛组别已核，具体市场unknown） | unknown（未交叉认证访谈提供动量/市场状态线索） | unknown（日内或波段均未可靠确认） | long: unknown；short: unknown | candidate_framework_unverified | SOURCE_INSUFFICIENT_NO_FAKE_IMPLEMENTATION |
| [Pavel P. Sterba](dossiers/remaining/pavel_sterba.md) / `pavel_sterba` | 股票（主办方披露，具体交易市场unknown） | unknown（课程销售者有价格行为学习归因，未获本人确认） | unknown | long: unknown；short: unknown | identity_and_results_only | SOURCE_INSUFFICIENT_NO_FAKE_IMPLEMENTATION |
| [Hsiu-Ping Peng](dossiers/remaining/hsiu_ping_peng.md) / `hsiu_ping_peng` | unknown（具体市场未核，不因姓名推断地区） | unknown | unknown | long: unknown；short: unknown | identity_and_results_only | SOURCE_INSUFFICIENT_NO_FAKE_IMPLEMENTATION |
| [Sam Bhatia](dossiers/remaining/sam_bhatia.md) / `sam_bhatia` | unknown（实际交易所与股票池未核） | unknown | unknown | long: unknown；short: unknown | identity_and_results_only | SOURCE_INSUFFICIENT_NO_FAKE_IMPLEMENTATION |
| [Sean Goodsell](dossiers/remaining/sean_goodsell.md) / `sean_goodsell` | unknown（完整资产及交易市场未核） | unknown（后期公司研究兴趣不能回填2022比赛方法） | unknown | long: unknown；short: unknown | identity_and_results_only | SOURCE_INSUFFICIENT_NO_FAKE_IMPLEMENTATION |
| [Moritz Reinhart](dossiers/remaining/moritz_reinhart.md) / `moritz_reinhart` | unknown（个人比赛的实际市场未核） | unknown（机构趋势跟踪/战术配置文章仅待连接线索） | unknown | long: unknown；short: unknown（文章摘要提及做空，不证明比赛采用） | candidate_framework_unverified | SOURCE_INSUFFICIENT_NO_FAKE_IMPLEMENTATION |
| [Luis Carlos Tarin](dossiers/remaining/luis_carlos_tarin.md) / `luis_carlos_tarin` | unknown | unknown | unknown | long: unknown；short: unknown | identity_and_results_only | SOURCE_INSUFFICIENT_NO_FAKE_IMPLEMENTATION |
| [Miguel Zambrano Sánchez](dossiers/remaining/miguel_zambrano_sanchez.md) / `miguel_zambrano_sanchez` | 股票（具体交易市场/交易所unknown） | 裁量短线技术交易；波段技术与基本面结合 | 日内分钟/小时，含盘前盘后；波段1–3周；67%/33%分配分母与平均持有说法未闭合 | long: unknown（方向未充分披露）；short: unknown | interview_framework_partial | SOURCE_INSUFFICIENT_NO_FAKE_IMPLEMENTATION |
| [张棋](dossiers/china/zhang_qi.md) / `zhang_qi` | 境内场内ETF；跨境指数敞口ETF | 技术超跌反转；产业/宏观困境反转；资金迁移与轮动 | 隔日反弹至较长产业修复；统一持有天数及信号频率unknown | long: ETF反转/轮动与风险时空仓；short: unknown | interview_framework_partial | HISTORICAL_RESEARCH_BRANCH_ONLY |
| [叙市](dossiers/china/xushi.md) / `xushi` | 境内ETF；香港股票（明源云案例）；个股（范围未完整披露） | ETF波段V2/V3专有指标；分钟与日线共振；支撑阻力、产业/宏观研究与人工裁量 | 5分钟辅助触发；日线支撑阻力；波段；平均持有期unknown | long: ETF/股票波段及已有底仓做T；short: unknown | primary_framework_partial | HISTORICAL_RESEARCH_BRANCH_ONLY |
| [Li666](dossiers/china/li666.md) / `li666` | 中国A股（偏好300开头） | 企业研究与政策/商品背景；提前买入、低频持有 | 低频持有；平均天数与买入触发周期unknown | long: 研究后较早持有；short: unknown | interview_framework_partial | HISTORICAL_RESEARCH_BRANCH_ONLY |
| [二池](dossiers/china/erchi.md) / `erchi` | 中国A股 | 产业预期与市场反馈；主线反复交易/修复回踩；10/20日均线退出描述按日期分开 | 日线框架；主线可反复跟踪半年以上；单笔平均持有期及完整频率unknown | long: 主线股修复/回踩及趋势跟随；short: unknown | primary_framework_partial | HISTORICAL_RESEARCH_BRANCH_ONLY |
| [这股有毒](dossiers/china/zhegu_youdu.md) / `zhegu_youdu` | 中国股票；中国可转债/转股；逆回购 | 情绪与竞价预期；板块回流；商品/业绩逻辑；转债负溢价转股与风险回避 | 竞价/盘中/尾盘观察；波段与较长个股持有并存；固定持仓期unknown | long: 股票、转债转股及板块轮动；short: unknown；风险回避: 空仓或逆回购 | primary_framework_partial | HISTORICAL_RESEARCH_BRANCH_ONLY |
| [归因](dossiers/china/guiyin.md) / `guiyin` | 中国A股（小盘题材案例） | unknown（第三方产业/事件预判与低吸等仅工作假说） | unknown（平均持有与实际频率未核） | long: 第三方案例为多头交易，完整方法unknown；short: unknown | secondary_framework_only | HISTORICAL_RESEARCH_BRANCH_ONLY |
| [低调科科员](dossiers/china/didiao_kekeyuan.md) / `didiao_kekeyuan` | 中国A股（赛事/点评范围） | 热点板块分仓波动（主办点评分类，非闭合规则） | 波段分类线索；具体周期/平均持有与频率unknown | long: 热点股票交易线索，完整规则unknown；short: unknown | secondary_framework_only | HISTORICAL_RESEARCH_BRANCH_ONLY |
| [投资如人生](dossiers/china/touzi_ru_rensheng.md) / `touzi_ru_rensheng` | 中国A股；融资股票账户（本人自述，账本待核） | 左侧潜伏；重组/产业预期；下行趋势减仓与融资风险控制 | 日/周线及60/120分钟为第三方转述线索；实际平均持有期与信号频率unknown | long: 左侧布局、反复交易与下跌减仓；short: unknown | primary_framework_partial | HISTORICAL_RESEARCH_BRANCH_ONLY |

## 追加2位方法参考

| 人物 / ID | 市场 | 风格 | 周期 | 多空方法 | 证据 | main 实现状态 |
|---|---|---|---|---|---|---|
| [Qullamaggie](dossiers/qullamaggie/dossier.zh.md) / `qullamaggie` | 美国股票；极端ETF/波动产品（历史个例） | 强动量收缩突破；Episodic Pivot；Parabolic short及极端下跌反向多头；低胜率、少数大赢家与紧风险 | 日线选股/整理，1/3/6月强度；盘中开盘区间执行（1/5/60分钟需按版本定义）；波段数日至数周或更长，统一频率unknown | long: Breakout与EP；另有极端下跌parabolic long；short: 加速上涨后ORL破位、转弱或VWAP反抽失败；借券必需 | primary_rules_partial | EXECUTED_DAILY_LIMITED_HYPOTHESES |
| [Oliver Kell](dossiers/swing/oliver_kell.md) / `oliver_kell` | 美国股票 | 价格循环；Wedge Pop与EMA Crossback；底部/趋势线突破；Wedge Drop与Downside EMA Crossback | 日线10/20EMA背景；65分钟执行/加仓（访谈文字）；数周至数月，非固定持有期 | long: Wedge Pop、首次EMA回踩和底部突破；short: Wedge Drop及下降EMA阻力回抽；完整借券规则unknown | primary_rules_partial | EXECUTED_DAILY_LIMITED_HYPOTHESES |

## 逐人来源、代码与下一步

### Martin Luk（martin_luk）

- 别名：无另列别名
- 实现边界：2026-10-20 main：在统一数据层 trader-data-v1 上按本人原话逐环节复刻（日 K、收盘或前一日决定的限价 / 开盘入场），R74 + S7（多空一体） 经用户同意登记冻结在 studies/trader_replication/systems.py，比对表与交易员看板运行同一版本；空头为前领涨股反抽到下行 21 EMA 的限价空单（只在指数 < 50 EMA，最多 5 天）；全部是样本内（2024-01-02 → 2026-10-16 逐轮选择），冻结后的前向记录才是样本外；是有限假设的日线翻译，不是本人完整系统，盘中入场、锚定 VWAP、反向 / 指数 ETF 等不在其中。
- 来源账本：[studies/trader_registry/dossiers/swing/sources.json](../../studies/trader_registry/dossiers/swing/sources.json)；[studies/trader_registry/dossiers/swing/sources.csv](../../studies/trader_registry/dossiers/swing/sources.csv)
- main代码：[studies/martin_luk/replicate.py](../../studies/martin_luk/replicate.py)；[studies/trader_replication/martin.py](../../studies/trader_replication/martin.py)；[studies/trader_replication/system.py](../../studies/trader_replication/system.py)；[studies/trader_replication/shorts.py](../../studies/trader_replication/shorts.py)；[studies/trader_replication/systems.py](../../studies/trader_replication/systems.py)
- main报告：[studies/martin_luk/reports/SHORTS_CN.md](../../studies/martin_luk/reports/SHORTS_CN.md)；[studies/martin_luk/reports/final_system_r74.json](../../studies/martin_luk/reports/final_system_r74.json)；[studies/martin_luk/reports/FINAL_CN.md](../../studies/martin_luk/reports/FINAL_CN.md)
- 原始来源入口：[来源1](https://financial-competitions.com/previousstandings/2020/10/13/december-2019-final)；[来源2](https://financial-competitions.com/previousstandings/2021/1/13/december-2020-standings)；[来源3](https://financial-competitions.com/previousstandings/2022/1/18/december-31-standings)；[来源4](https://financial-competitions.com/previousstandings/2023/2/21/december-2022-standings)；[来源5](https://financial-competitions.com/previousstandings/2024/1/23/december-standings-2023)；[来源6](https://financial-competitions.com/previousstandings/2025/2/12/december-final-standings-2024)；[来源7](https://financial-competitions.com/previousstandings/2026/1/24/december-standings-2025)；[来源8](https://financial-competitions.com)；[来源9](https://financial-competitions.com/previousstandings/)；[来源10](https://tradingresourcehub.substack.com/p/martin-luk-283-usic-2024-key-lessons)；[来源11](https://tradingresourcehub.substack.com/p/martin-luk-283-usic-2024-key-lessons/comment/91396123)；[来源12](https://tradingresourcehub.substack.com/p/martin-luk-283-usic-2024-key-lessons/comment/94073578)；[来源13](https://tradingresourcehub.substack.com/p/martin-luk-283-usic-2024-key-lessons/comment/90457733)；[来源14](https://tradingresourcehub.substack.com/p/martin-luk-study-process)；[来源15](https://www.youtube.com/watch?v=lS9zbnLi1Gg)；[来源16](https://youtubesummary.com/summary/lS9zbnLi1Gg)；[来源17](https://www.youtube.com/watch?v=VKNEJA5r8zw)；[来源18](https://share.snipd.com/episode/2ecc451e-3f05-4f2b-8ccd-83d2d741e3ad)；[来源19](https://www.youtube.com/watch?v=O1LZJYaMqnQ&t=820)；[来源20](https://github.com/QSothoth/s-alpha/blob/5bd4c16d73a9ca7b2b2d2c94b145b4949e2eb339/studies/martin_luk/notes/RULES_CN.md)；[来源21](https://github.com/QSothoth/s-alpha/blob/5bd4c16d73a9ca7b2b2d2c94b145b4949e2eb339/studies/martin_luk/notes/trades.csv)
- 缺失规则：版本待对照：2025-02-06本人评论为首次>3×ADR、约10%、9或23EMA；历史9bc6a6b29c577d4ad6d6d13312beaf15ae7ab1f2的luk.py/intraday.py基线为3/6/9/12R、初始股数15%。main较新R19–R74另有自动字幕规则及不同轮次配置，不由旧基线代表；需核原句/日期/setup，不能将不同版本合并或判所有R规则错误；ADR回看期、涨幅参照、10%分母、后续批次及不同setup适用性unknown；完整券商成交、资金流、真实容量及年度规则映射仍缺；main已有137笔公开材料台账，不等于全账户订单
- 下一步：对照main已有自动字幕时间戳与原音，厘清2025-02评论及2025/2026访谈的版本/setup；明确ADR/R、10%/15%、23/21EMA和后续批次差异，不直接改参数宣布修复；在已有公开交易台账基础上核对券商订单/资金流，保持同段择优与独立样本外资格分离

### Mark Minervini（mark_minervini）

- 别名：无另列别名
- 实现边界：2026-10-20 main：在统一数据层 trader-data-v1 上按本人原话逐环节复刻（日 K、收盘或前一日决定的限价 / 开盘入场），R0b（B 级基线，只做多） 经用户同意登记冻结在 studies/trader_replication/systems.py，比对表与交易员看板运行同一版本；空头基线两轮都没通过（他的空头主要是指数 ETF 对冲，不在范围内）；全部是样本内（2024-01-02 → 2026-10-16 逐轮选择），冻结后的前向记录才是样本外；是有限假设的日线翻译，不是本人完整系统，盘中入场、锚定 VWAP、反向 / 指数 ETF 等不在其中。
- 来源账本：[studies/trader_registry/dossiers/swing/sources.json](../../studies/trader_registry/dossiers/swing/sources.json)；[studies/trader_registry/dossiers/swing/sources.csv](../../studies/trader_registry/dossiers/swing/sources.csv)
- main代码：[studies/mark_minervini/replicate.py](../../studies/mark_minervini/replicate.py)；[studies/trader_replication/system.py](../../studies/trader_replication/system.py)；[studies/trader_replication/shorts.py](../../studies/trader_replication/shorts.py)；[studies/trader_replication/systems.py](../../studies/trader_replication/systems.py)
- main报告：[studies/mark_minervini/reports/SHORTS_CN.md](../../studies/mark_minervini/reports/SHORTS_CN.md)
- 原始来源入口：[来源1](https://financial-competitions.com/previousstandings/2022/1/18/december-31-standings)；[来源2](https://financial-competitions.com)；[来源3](https://minerviniselect.com/strategy.php)；[来源4](https://michaelsincere.com/articles/my-marketwatch-interview-with-stock-market-wizard-mark-minervini)；[来源5](https://cdn.minervini.com/static/dist/mtp-review.1f8e8633.pdf)；[来源6](https://traderlion.com/investing-champions/mark-minervinis-risk-management/)；[来源7](https://playthetrade.com/screens/how-mark-minervini-uses-his-trend-templates/)；[来源8](https://github.com/obzva/trend-template-screener)；[来源9](https://github.com/phuazz/vcp-screener)；[来源10](https://www.reddit.com/r/swingtrading/comments/om09wm/mark_minervinis_performance_and_experience_with/)；[来源11](https://canslim.blog/2026/09/01/ai-trader-minervini-26-sepa-setups-senea-best-at-3-131/)
- 缺失规则：不同趋势模板与cheat/power play等结构的完整可执行定义；逐年风险切换、加仓、退出优先级和真实触发频率；同口径完整订单及容量/费用
- 下一步：合法核对原书及同期讲义，标明版本；把源规则扫描与冻结代理形态分开；补足失败案例、完整账本与风险变化记录

### Ryan Pierpont（ryan_pierpont）

- 别名：无另列别名
- 实现边界：main 5bd4c16d73a9ca7b2b2d2c94b145b4949e2eb339无可识别的该人专属实现；不迁入历史策略代码。历史research/individual-trader-studies分支 9bc6a6b29c577d4ad6d6d13312beaf15ae7ab1f2：已执行独立日线底部/成长性代理；共享会计引擎不等于共享信号。使用限定存续名单与复权因子单位账本，不是比赛账户或实际股数净收益。 历史代码：https://github.com/QSothoth/s-alpha/blob/9bc6a6b29c577d4ad6d6d13312beaf15ae7ab1f2/studies/ryan_pierpont/fundamentals.py；历史报告：https://github.com/QSothoth/s-alpha/blob/9bc6a6b29c577d4ad6d6d13312beaf15ae7ab1f2/studies/ryan_pierpont/reports/FINAL_CN.md
- 来源账本：[studies/trader_registry/dossiers/swing/sources.json](../../studies/trader_registry/dossiers/swing/sources.json)；[studies/trader_registry/dossiers/swing/sources.csv](../../studies/trader_registry/dossiers/swing/sources.csv)
- main代码：无可归属的当前文件
- main报告：无可归属的当前文件
- 原始来源入口：[来源1](https://financial-competitions.com/previousstandings/2021/1/13/december-2020-standings)；[来源2](https://financial-competitions.com/previousstandings/2022/1/18/december-31-standings)；[来源3](https://financial-competitions.com)；[来源4](https://www.businessinsider.com/trading-strategy-us-investing-championship-contender-outperformance-alpha-ryan-pierpoint-2021-8)；[来源5](https://podcasts.apple.com/us/podcast/10-steps-to-profitable-trading-in-2024-ryan-pierpont/id1586336923?i=1000640742389)；[来源6](https://youtu.be/KQRuUWSZvLE)；[来源7](https://traderlion.com/profile/clement-ang/influences-on-my-trading-clement-ang/)
- 缺失规则：突破容差、下单时段、跳空和单据类型；初始/追踪止损、分批比例、总风险与相关性规则；63/126日、8–35%深度等既有代理不是本人已证参数
- 下一步：核听2023-06-03大会完整原声并分清2024发行日期；补事前候选与排除记录及原始交易日志；核对资金连续性与后续亏损期

### Afzal Lokhandwala（afzal_lokhandwala）

- 别名：无另列别名
- 实现边界：以main 5bd4c16d73a9ca7b2b2d2c94b145b4949e2eb339为准：未发现专属策略目录或运行结果；仅覆盖/证据审查。新档案已补足持有期框架，不代表原版算法已闭合，不能用通用VCP冒名。
- 来源账本：[studies/trader_registry/dossiers/remaining/afzal_lokhandwala.sources.json](../../studies/trader_registry/dossiers/remaining/afzal_lokhandwala.sources.json)；[studies/trader_registry/dossiers/remaining/source_ledger.json](../../studies/trader_registry/dossiers/remaining/source_ledger.json)
- main代码：无可归属的当前文件
- main报告：无可归属的当前文件
- 原始来源入口：[来源1](https://financial-competitions.com/previousstandings/2023/2/21/december-2022-standings)；[来源2](https://financial-competitions.com/previousstandings/2024/1/23/december-standings-2023)；[来源3](https://www.businesswire.com/news/home/20230125005300/en/)；[来源4](https://news.abplive.com/brand-wire/mastering-the-market-a-conversation-with-afzal-lokhandwala-the-first-indian-winner-of-the-united-states-investing-championship-1613491)；[来源5](https://www.moneycontrol.com/news/trends/features/stock-trading-simplified-by-afzal-lokhandwala-5560871.html/amp)；[来源6](https://afzallokhandwala.com/intl/)；[来源7](https://afzallokhandwala.com/success-stories/)；[来源8](https://www.reddit.com/r/IndianStockMarket/comments/1ap03be/anyone_who_took_course_of_ca_afzal_lokhandwala/)
- 缺失规则：突破确认、止损、仓位预算、加仓和退出优先级；具体比赛交易市场与各账户工具映射；完整净值、费用和订单
- 下一步：取得不同组别账户清单、月结及现金流；收集至少一胜一负的赛前计划与实际交易；冻结公开教学版本与赛时版本的对应关系

### Gemy Zhou（gemy_zhou）

- 别名：无另列别名
- 实现边界：main 5bd4c16d73a9ca7b2b2d2c94b145b4949e2eb339无可识别的该人专属实现；不迁入历史策略代码。历史research/individual-trader-studies分支 9bc6a6b29c577d4ad6d6d13312beaf15ae7ab1f2：仅输入可得时点、缺模型拒绝、父子单数量/去重/部分成交及人工隔夜状态的工程实现和合成测试；没有交易模型或金融回测结论。 历史代码：https://github.com/QSothoth/s-alpha/blob/9bc6a6b29c577d4ad6d6d13312beaf15ae7ab1f2/studies/gemy_zhou/architecture.py；历史报告：https://github.com/QSothoth/s-alpha/blob/9bc6a6b29c577d4ad6d6d13312beaf15ae7ab1f2/studies/gemy_zhou/reports/FINAL_CN.md
- 来源账本：[studies/trader_registry/dossiers/active/quant_short_ledger.json](../../studies/trader_registry/dossiers/active/quant_short_ledger.json)
- main代码：无可归属的当前文件
- main报告：无可归属的当前文件
- 原始来源入口：[来源1](https://financial-competitions.com/previousstandings/2022/12/19/november-2022-standings)；[来源2](https://financial-competitions.com/previousstandings/2023/2/21/december-2022-standings)；[来源3](https://financial-competitions.com/previousstandings/2023/7/21/june-2023-standings)；[来源4](https://financial-competitions.com/previousstandings/2023/10/23/september-2023-standings)；[来源5](https://financial-competitions.com/previousstandings/2023/11/24/ten-month-standings-2023)；[来源6](https://financial-competitions.com/previousstandings/2023/12/28/november-standings-2023)；[来源7](https://financial-competitions.com/previousstandings/2024/1/23/december-standings-2023)；[来源8](https://www.tmcnet.com/usubmit/-united-states-investing-championship-ten-month-results-/2022/11/28/9720006.htm)；[来源9](https://www.financialcontent.com/article/bizwire-2023-7-24-united-states-investing-championship-first-half-results)；[来源10](https://www.businessinsider.es/economia/trader-gano-440-2022-explica-como-diseno-programa-1195890)；[来源11](https://en.bulios.com/status/86509)；[来源12](https://x.com/GemyZhou)；[来源13](https://www.sotwe.com/GemyZhou?lang=en)；[来源14](https://m.hk.investing.com/news/stock-market-news/article-276192?ampMode=1)；[来源15](https://test.elitetrader.com/et/threads/what-style-of-trading-would-you-teach-your-son.375171/)
- 缺失规则：原始特征、标签、训练切分、模型权重和版本；证券池、报价事件、目标/止损公式、重训与人工覆盖政策；AFI日期冲突、逐笔订单和借券资料
- 下一步：取得合法原模型/源码/哈希及特征时间映射；先核AFI原始日期、十月设置问题原帖与模型版本；继续以缺模型即拒绝的工程契约保持阻塞

### Sean Ryan（sean_ryan）

- 别名：无另列别名
- 实现边界：2026-10-20 main：按本人 TraderLion 2024-01 访谈原话在 trader-data-v1 上逐环节复刻（第二波 / 洗盘、收盘买、当日低点止损 ≤ 6%、1R 保本、2R 卖三分之二、新买点加三分之一、前 5 日低点或反转日离场），B 级（台账 6 行、全在 2023），R0–R8 在选择段 2024–2025 逐轮选出 W2（+207%），2026 验证段只评一次 −43.6%、排位 0.00，未通过；空头 S1–S2 未带入（他的主要空头是反向 ETF，数据缺口）；未在 systems.py 登记。历史分支 9bc6a6b 的日线第二波研究只作线索，不迁入。
- 来源账本：[studies/trader_registry/dossiers/swing/sources.json](../../studies/trader_registry/dossiers/swing/sources.json)；[studies/trader_registry/dossiers/swing/sources.csv](../../studies/trader_registry/dossiers/swing/sources.csv)
- main代码：[studies/sean_ryan/replicate.py](../../studies/sean_ryan/replicate.py)；[studies/sean_ryan/shorts_round.py](../../studies/sean_ryan/shorts_round.py)；[studies/trader_replication/system.py](../../studies/trader_replication/system.py)；[studies/trader_replication/shorts.py](../../studies/trader_replication/shorts.py)
- main报告：[studies/sean_ryan/reports/FINAL_CN.md](../../studies/sean_ryan/reports/FINAL_CN.md)；[studies/sean_ryan/reports/SHORTS_CN.md](../../studies/sean_ryan/reports/SHORTS_CN.md)
- 原始来源入口：[来源1](https://financial-competitions.com/previousstandings/2020/10/13/december-2019-final)；[来源2](https://financial-competitions.com/previousstandings/2021/1/13/december-2020-standings)；[来源3](https://financial-competitions.com/previousstandings/2022/1/18/december-31-standings)；[来源4](https://financial-competitions.com/previousstandings/2023/2/21/december-2022-standings)；[来源5](https://financial-competitions.com/previousstandings/2024/1/23/december-standings-2023)；[来源6](https://financial-competitions.com/previousstandings/2026/1/24/december-standings-2025)；[来源7](https://financial-competitions.com)；[来源8](https://www.businessinsider.com/stock-market-investor-indicators-profitable-trader-huge-returns-2023-2)；[来源9](https://podcasts.apple.com/us/podcast/multiple-100-years-after-blowing-out-an-account-sean-ryan/id1586336923?i=1000642129705)；[来源10](https://completetradersedge.com/sean-ryan-usic-consistency-record/)；[来源11](https://github.com/mrseanryan)；[来源12](https://financial-competitions.com/previousstandings/2025/2/12/december-final-standings-2024)
- 缺失规则：第二波机械边界、RSI周期/配对/容差；加仓比例、退出优先级、总杠杆及借券/强平规则；全量账本与爆仓/重启原声
- 下一步：核听原访谈风险、失败及空头章节；保留RSI14等研究假设标签，分别审查第二波、保本和背离退出；补全借券、杠杆与容量记录

### Goverdhan Gajjala（goverdhan_gajjala）

- 别名：GG、Gon
- 实现边界：main 5bd4c16d73a9ca7b2b2d2c94b145b4949e2eb339无可识别的该人专属实现；不迁入历史策略代码。历史research/individual-trader-studies分支 9bc6a6b29c577d4ad6d6d13312beaf15ae7ab1f2：已执行5分钟机制与域外诊断、小盘不完整子集及成本压力。strict因历史float缺失关闭；域外和极少样本不能验证本人小盘策略或可部署收益。 历史代码：https://github.com/QSothoth/s-alpha/blob/9bc6a6b29c577d4ad6d6d13312beaf15ae7ab1f2/studies/goverdhan_gajjala/replay.py；历史报告：https://github.com/QSothoth/s-alpha/blob/9bc6a6b29c577d4ad6d6d13312beaf15ae7ab1f2/studies/goverdhan_gajjala/reports/RESULTS.md
- 来源账本：[studies/trader_registry/dossiers/active/active_source_ledger.json](../../studies/trader_registry/dossiers/active/active_source_ledger.json)；[studies/trader_registry/dossiers/active/active_claim_ledger.json](../../studies/trader_registry/dossiers/active/active_claim_ledger.json)
- main代码：无可归属的当前文件
- main报告：无可归属的当前文件
- 原始来源入口：[来源1](https://www.businesswire.com/news/home/20240126217806/en/United-States-Investing-Championship-2023-Final-Results/)；[来源2](https://kagels-trading.com/blog/us-investing-championship/)；[来源3](https://traderlion.com/investing-champions/2023-us-investing-champion/)；[来源4](https://retailtradersrepository.substack.com/p/goverdhan-gajjala-question-and-answer)；[来源5](https://retailtradersrepository.substack.com/p/goverdhan-gajjala-a-deep-dive-into)；[来源6](https://retailtradersrepository.substack.com/p/bull-flag-breakout-pullback-setup)；[来源7](https://www.youtube.com/watch?v=10pHBNVi4Jc)；[来源8](https://www.momentumaccess.com/)；[来源9](https://tickerguard.com/articles/gajjala-daytrading-backtest-study)；[来源10](https://www.reddit.com/r/swingtrading/comments/1czhhns/paid_courses_are_not_wroth_it/)
- 缺失规则：历史时点float、真实盘口/停牌/重开与全部候选及跳过记录；A+、自然回调、周期切换、风险轨迹和加仓规则；精确形态细节主要为二手课程笔记，未认证为比赛全年参数
- 下一步：先补历史float和分钟/报价数据门禁；获取带日期的胜败样本、观察表和全年订单；将本人Q&A、二手形态与第三方代理反证分层

### Christian Flanders（christian_flanders）

- 别名：无另列别名
- 实现边界：2026-10-20 main：在统一数据层 trader-data-v1 上按本人原话逐环节复刻（日 K、收盘或前一日决定的限价 / 开盘入场），R15 C4 + C1C + S4（2026-10-20 加当天 EP 先买）（多空一体） 经用户同意登记冻结在 studies/trader_replication/systems.py，比对表与交易员看板运行同一版本；空头为已压回过反抽的下行 200 日线限价空单（指数 < 50 EMA，有利润马上了结）；合计改善偏弱；全部是样本内（2024-01-02 → 2026-10-16 逐轮选择），冻结后的前向记录才是样本外；是有限假设的日线翻译，不是本人完整系统，盘中入场、锚定 VWAP、反向 / 指数 ETF 等不在其中。
- 来源账本：[studies/trader_registry/dossiers/active/active_source_ledger.json](../../studies/trader_registry/dossiers/active/active_source_ledger.json)；[studies/trader_registry/dossiers/active/active_claim_ledger.json](../../studies/trader_registry/dossiers/active/active_claim_ledger.json)
- main代码：[studies/christian_flanders/replicate.py](../../studies/christian_flanders/replicate.py)；[studies/trader_replication/system.py](../../studies/trader_replication/system.py)；[studies/trader_replication/shorts.py](../../studies/trader_replication/shorts.py)；[studies/trader_replication/systems.py](../../studies/trader_replication/systems.py)
- main报告：[studies/christian_flanders/reports/SHORTS_CN.md](../../studies/christian_flanders/reports/SHORTS_CN.md)；[studies/christian_flanders/reports/FINAL_CN.md](../../studies/christian_flanders/reports/FINAL_CN.md)
- 原始来源入口：[来源1](https://www.businesswire.com/news/home/20250127956815/en/2024-United-States-Investing-Championship-Final-Results)；[来源2](https://financial-competitions.com/previousstandings/2026/1/24/december-standings-2025)；[来源3](https://kagels-trading.com/blog/us-investing-championship/)；[来源4](https://tradingresourcehub.substack.com/p/christian-flanders-usic-2024-outperformance)；[来源5](https://tradingresourcehub.substack.com/p/christian-flanders-2025-review)；[来源6](https://www.marawealth.com/christian-flanders/)；[来源7](https://smartstocksnewsletter.substack.com/p/interview-with-christian-flanders)；[来源8](https://www.linkedin.com/posts/businessinsider_a-poker-player-turned-trader-up-253-this-activity-7246633371529842688-erkv)
- 缺失规则：A+与EP的完整选股、事件和入口定义；10DMA、少量20DMA计划与2026更小初始仓必须分版本；逐次加仓、保证金、成交滑点与订单取消确认
- 下一步：按2024/2025复盘和2026计划分别建规则卡；补NVDA/CRWV/USAR/CSIQ订单与失败样本；审查尾部赢家、退出与订单幂等性

### J Law（j_law）

- 别名：Law Wai-Sum、@JLawStock
- 实现边界：main 5bd4c16d73a9ca7b2b2d2c94b145b4949e2eb339无可识别的该人专属实现；不迁入历史策略代码。历史research/individual-trader-studies分支 9bc6a6b29c577d4ad6d6d13312beaf15ae7ab1f2：已执行20日阻力/同时间量与SEC时点财务分流的分钟局部假设，NI替EPS明确另立。QFQ单位账本不是实盘净美元。身份独立于Adrian Law及Judy Lai。 历史代码：https://github.com/QSothoth/s-alpha/blob/9bc6a6b29c577d4ad6d6d13312beaf15ae7ab1f2/studies/j_law/signals.py；历史报告：https://github.com/QSothoth/s-alpha/blob/9bc6a6b29c577d4ad6d6d13312beaf15ae7ab1f2/studies/j_law/reports/FINAL_CN.md
- 来源账本：[studies/trader_registry/dossiers/active/active_source_ledger.json](../../studies/trader_registry/dossiers/active/active_source_ledger.json)；[studies/trader_registry/dossiers/active/active_claim_ledger.json](../../studies/trader_registry/dossiers/active/active_claim_ledger.json)
- main代码：无可归属的当前文件
- main报告：无可归属的当前文件
- 原始来源入口：[来源1](https://www.businesswire.com/news/home/20250127956815/en/2024-United-States-Investing-Championship-Final-Results)；[来源2](https://financial-competitions.com/previousstandings/2026/1/24/december-standings-2025)；[来源3](https://financial-competitions.com/rules)；[来源4](https://kagels-trading.com/blog/us-investing-championship/)；[来源5](https://traderlion.com/profile/j-law/11-lessons-from-j-law/)；[来源6](https://www.jlawstock.com/blog/20250905)；[来源7](https://www.prnewswire.com/apac/news-releases/j-law-sets-two-year-record-with-1-499-return-in-us-investing-championship-302698517.html)；[来源8](https://w.twstalker.com/JLawStock)
- 缺失规则：日常约0.3%风险不等于比赛账户风险；比赛风险上限unknown；行业/题材、财务质量、多空切换、退出优先级及加仓阈值；空头库存/费用、所有账户映射与完整订单
- 下一步：补带日期的完整入场—加仓—退出胜败链；取得赛时与日常账户规则及现金流分离记录；独立核查空头执行，禁止多头信号机械反转

### Vibha Jha（vibha_jha）

- 别名：无另列别名
- 实现边界：main 5bd4c16d73a9ca7b2b2d2c94b145b4949e2eb339无可识别的该人专属实现；不迁入历史策略代码。历史research/individual-trader-studies分支 9bc6a6b29c577d4ad6d6d13312beaf15ae7ab1f2：已执行ETF、成长性及轮换审计的独立日线假设；两条线未形成同窗口完整统一资金轮换。使用真实产品价格而非指数收益乘三；部分因子单位账本非实际股数净收益。 历史代码：https://github.com/QSothoth/s-alpha/blob/9bc6a6b29c577d4ad6d6d13312beaf15ae7ab1f2/studies/vibha_jha/exposure_control.py；历史报告：https://github.com/QSothoth/s-alpha/blob/9bc6a6b29c577d4ad6d6d13312beaf15ae7ab1f2/studies/vibha_jha/reports/FINAL_CN.md
- 来源账本：[studies/trader_registry/dossiers/swing/sources.json](../../studies/trader_registry/dossiers/swing/sources.json)；[studies/trader_registry/dossiers/swing/sources.csv](../../studies/trader_registry/dossiers/swing/sources.csv)
- main代码：无可归属的当前文件
- main报告：无可归属的当前文件
- 原始来源入口：[来源1](https://financial-competitions.com/previousstandings/2021/1/13/december-2020-standings)；[来源2](https://financial-competitions.com/previousstandings/2022/1/18/december-31-standings)；[来源3](https://financial-competitions.com/previousstandings/2024/1/23/december-standings-2023)；[来源4](https://financial-competitions.com/previousstandings/2025/2/12/december-final-standings-2024)；[来源5](https://financial-competitions.com)；[来源6](https://traderlion.com/investing-champions/vibha-jha-tqqq/)；[来源7](https://www.listennotes.com/podcasts/the-traderlion/1000000-tqqq-swing-trading-DHrK81nG_4R/)；[来源8](https://www.youtube.com/watch?v=aDRYV4mjlHA)；[来源9](https://podcasts.apple.com/ca/podcast/ep-309-how-to-achieve-huge-returns-with-these-buy-and/id1454868999?i=1000696389182)；[来源10](https://podcasts.apple.com/ch/podcast/from-corporate-exec-to-champion-trader-vibha-jha-on/id1812778005?i=1000733858533&l=fr-FR)；[来源11](https://www.linkedin.com/posts/vibha-jha-0748845_it-was-my-pleasure-dave-thank-you-for-everything-activity-7387877706379657217-ATFJ)；[来源12](https://www.reddit.com/r/TradersEdgeLabs/comments/1x3920w/vibha_jha_learning_to_trade_while_working_full/)
- 缺失规则：更高低点、分布日、阻力失败的精确定义；两套系统的统一资金、风险和轮换账本；原始访谈音频、实际ETF订单及完整亏损期
- 下一步：先核原访谈并分开成长股与ETF规则；补真实TQQQ产品路径、公司行动和同窗资金轮换；不将50日/10周或固定分布日代理写成本人全部条件

### Ty Rajnus（ty_rajnus）

- 别名：Rajnus Capital LLC、@RajnusCapital
- 实现边界：main 5bd4c16d73a9ca7b2b2d2c94b145b4949e2eb339无可识别的该人专属实现；不迁入历史策略代码。历史research/individual-trader-studies分支 9bc6a6b29c577d4ad6d6d13312beaf15ae7ab1f2：仅真实5分钟过热事件价格路径，未模拟卖空成交或净利润；borrow未知，融资披露关联未完成。原模型与可实现净收益保持阻塞。 历史代码：https://github.com/QSothoth/s-alpha/blob/9bc6a6b29c577d4ad6d6d13312beaf15ae7ab1f2/studies/ty_rajnus/events.py；历史报告：https://github.com/QSothoth/s-alpha/blob/9bc6a6b29c577d4ad6d6d13312beaf15ae7ab1f2/studies/ty_rajnus/reports/FINAL_CN.md
- 来源账本：[studies/trader_registry/dossiers/active/quant_short_ledger.json](../../studies/trader_registry/dossiers/active/quant_short_ledger.json)
- main代码：无可归属的当前文件
- main报告：无可归属的当前文件
- 原始来源入口：[来源1](https://financial-competitions.com/previousstandings/2025/3/23/january-standings-2025)；[来源2](https://financial-competitions.com/previousstandings/2025/4/20/february-standings-2025)；[来源3](https://financial-competitions.com/previousstandings/2025/5/23/march-standings-2025)；[来源4](https://financial-competitions.com/previousstandings/2025/6/4/april-standings-2025)；[来源5](https://financial-competitions.com/previousstandings/2025/7/15/may-standings-2025)；[来源6](https://financial-competitions.com/previousstandings/2025/8/4/june-standings-2025)；[来源7](https://financial-competitions.com/previousstandings/2025/8/24/july-standings-2025)；[来源8](https://financial-competitions.com/previousstandings/2025/10/11/august-standings-2025)；[来源9](https://financial-competitions.com/previousstandings/2025/10/29/september-standings-2025)；[来源10](https://financial-competitions.com/previousstandings/2025/12/8/october-standings-2025)；[来源11](https://financial-competitions.com/previousstandings/2026/1/24/november-2025-standings)；[来源12](https://financial-competitions.com/previousstandings/2026/1/24/december-standings-2025)；[来源13](https://www.streetinsider.com/Business%2BWire/Multiple%2BWorld%2BRecords%2BSet%2Bin%2BInternational%2BInvesting%2BCompetition/25927718.html)；[来源14](https://getpodcast.com/podcast/the-traderlion-podcast/382-return-in-1-year-why-most-traders-fail-at-shorting-from-a-trading-_2f20d63a88)；[来源15](https://www.youtube.com/watch?v=bRXO6F_vGjM)；[来源16](https://traderlion.com/profile/ty-rajnus/ty-rajnus-returned-382/)；[来源17](https://share.snipd.com/episode/76030b42-ffd8-4aea-ab03-f23afcfc9ee5)；[来源18](https://share.snipd.com/chapter/935f45a1-ea6c-46ce-b580-42cc75bfc7b4)；[来源19](https://share.snipd.com/chapter/10a94276-9cbd-469a-aa45-ccc7d6744b6e)；[来源20](https://x.com/RajnusCapital)；[来源21](https://mobile.twstalker.com/RajnusCapital)；[来源22](https://mobile.twstalker.com/RajnusCapital/status/1909342663322800408)；[来源23](https://mobile.twstalker.com/RajnusCapital/status/1922812116794474881)；[来源24](https://mobile.twstalker.com/RajnusCapital/status/2064816179013906648)；[来源25](https://mobile.twstalker.com/RajnusCapital/status/1916269729205129588)；[来源26](https://mobile.twstalker.com/RajnusCapital/status/1911925563377524930)；[来源27](https://mobile.twstalker.com/RajnusCapital/status/1927065512644653145)；[来源28](https://mobile.twstalker.com/RajnusCapital/status/1908248716353679495)；[来源29](https://arxiv.org/abs/1903.11804)
- 缺失规则：价格/流动性/摊薄概率的精确阈值与因果发布时间；locate数量/费用/有效期、召回、停牌、强平与保证金；入出场、宽止损、仓位、模型版本及账户映射
- 下一步：核听原节目并核对CWD与亏损例的订单；补历史借券和融资事件时点后再研究可执行卖空；分开2025股票、期权及2026方法变化

### Clement Ang（clement_ang）

- 别名：无另列别名
- 实现边界：2026-10-20 main：在统一数据层 trader-data-v1 上按本人原话逐环节复刻（日 K、收盘或前一日决定的限价 / 开盘入场），R15 AA3 + C4A + S5（2026-10-20 加 EP 另计每天 1 笔）（多空一体） 经用户同意登记冻结在 studies/trader_replication/systems.py，比对表与交易员看板运行同一版本；空头为大型前领涨股的晚期失败底部（市况连续转负后，最多 5 天）；他主要的反向 ETF 空头不在其中；全部是样本内（2024-01-02 → 2026-10-16 逐轮选择），冻结后的前向记录才是样本外；是有限假设的日线翻译，不是本人完整系统，盘中入场、锚定 VWAP、反向 / 指数 ETF 等不在其中。
- 来源账本：[studies/trader_registry/dossiers/active/active_source_ledger.json](../../studies/trader_registry/dossiers/active/active_source_ledger.json)；[studies/trader_registry/dossiers/active/active_claim_ledger.json](../../studies/trader_registry/dossiers/active/active_claim_ledger.json)
- main代码：[studies/clement_ang/replicate.py](../../studies/clement_ang/replicate.py)；[studies/trader_replication/system.py](../../studies/trader_replication/system.py)；[studies/trader_replication/shorts.py](../../studies/trader_replication/shorts.py)；[studies/trader_replication/systems.py](../../studies/trader_replication/systems.py)
- main报告：[studies/clement_ang/reports/SHORTS_CN.md](../../studies/clement_ang/reports/SHORTS_CN.md)；[studies/clement_ang/reports/FINAL_CN.md](../../studies/clement_ang/reports/FINAL_CN.md)
- 原始来源入口：[来源1](https://financial-competitions.com/previousstandings/2026/1/24/december-standings-2025)；[来源2](https://kagels-trading.com/blog/us-investing-championship/)；[来源3](https://traderlion.com/profile/clement-ang/clement-ang-qa/)；[来源4](https://tradingresourcehub.substack.com/p/6-lessons-from-competing-usic-2024-clement-ang)；[来源5](https://tradingresourcehub.substack.com/p/routine-of-part-time-trader-clement-ang)；[来源6](https://tradingresourcehub.substack.com/p/model-books-clement-ang)；[来源7](https://podcasts.apple.com/us/podcast/us-trading-champion-he-made-520-competing-against-the/id1780241706?i=1000793080369)；[来源8](https://hk.linkedin.com/in/clementang-17)；[来源9](https://github.com/traderwillhu/market_dashboard)；[来源10](https://www.moeasymmetry.com/articles/clement-ang-from-1m-to-zero-and-back)；[来源11](https://financial-competitions.com/previousstandings/2025/2/12/december-final-standings-2024)
- 缺失规则：ADR/ATR算法、RS基准、主题/形态成熟及突破/回调切换；2024/2025比赛与2026AMA规则版本映射；初始止损、条件性撤止损例外、风险升降及完整账户对应
- 下一步：分别冻结2024流程、2025模型书、2026AMA内容；核对宣传与官方参赛账户映射，不拼接收益；补失败订单及条件性风险例外的实际执行

### Deepak Uppal（deepak_uppal）

- 别名：@duppal75
- 实现边界：main 5bd4c16d73a9ca7b2b2d2c94b145b4949e2eb339无可识别的该人专属实现；不迁入历史策略代码。历史research/individual-trader-studies分支 9bc6a6b29c577d4ad6d6d13312beaf15ae7ab1f2：已执行数值筛选、NI正盈利分钟代理、最新已披露单季EPS-sign分钟代理；两种分钟版本样本极少。QFQ单位非真实股数/净美元，完整原版未闭合。 历史代码：https://github.com/QSothoth/s-alpha/blob/9bc6a6b29c577d4ad6d6d13312beaf15ae7ab1f2/studies/deepak_uppal/signals.py；历史报告：https://github.com/QSothoth/s-alpha/blob/9bc6a6b29c577d4ad6d6d13312beaf15ae7ab1f2/studies/deepak_uppal/reports/FINAL_CN.md
- 来源账本：[studies/trader_registry/dossiers/active/active_source_ledger.json](../../studies/trader_registry/dossiers/active/active_source_ledger.json)；[studies/trader_registry/dossiers/active/active_claim_ledger.json](../../studies/trader_registry/dossiers/active/active_claim_ledger.json)
- main代码：无可归属的当前文件
- main报告：无可归属的当前文件
- 原始来源入口：[来源1](https://www.businesswire.com/news/home/20240126217806/en/United-States-Investing-Championship-2023-Final-Results/)；[来源2](https://www.businesswire.com/news/home/20250127956815/en/2024-United-States-Investing-Championship-Final-Results)；[来源3](https://kagels-trading.com/blog/us-investing-championship/)；[来源4](https://traderlion.com/investing-champions/deepak-uppals-trading-strategy/)；[来源5](https://www.youtube.com/watch?v=q43pkYBo1hU)；[来源6](https://trading-tournaments.com/traders/deepak-uppal)；[来源7](https://www.ainvest.com/news/champion-259-return-priced-reality-asymmetric-payoffs-2602/)
- 缺失规则：ATR周期/分母、EPS会计口径、RS期限及市场状态门槛；全/分批退出比例、总风险、保证金和加仓顺序；文章最高1%与未核视频1–1.5%风险差异
- 下一步：先核访谈风险原句和年度统计口径；对齐NTES/NFLX/AVGO原始成交与拆股前报价；区分3R目标与实际均盈均亏

### Roy Mattox（roy_mattox）

- 别名：无另列别名
- 实现边界：以main 5bd4c16d73a9ca7b2b2d2c94b145b4949e2eb339为准：无专属策略代码或运行结果；现为来源/覆盖审查。公开框架可研究，尚不能构造本人精确策略或收益曲线。
- 来源账本：[studies/trader_registry/dossiers/remaining/roy_mattox.sources.json](../../studies/trader_registry/dossiers/remaining/roy_mattox.sources.json)；[studies/trader_registry/dossiers/remaining/source_ledger.json](../../studies/trader_registry/dossiers/remaining/source_ledger.json)
- main代码：无可归属的当前文件
- main报告：无可归属的当前文件
- 原始来源入口：[来源1](https://www.businesswire.com/news/home/20220124005241/en/)；[来源2](https://financial-competitions.com/previousstandings/2023/2/21/december-2022-standings)；[来源3](https://tradingengineered.substack.com/p/10-keys-to-achieving-super-performance)；[来源4](https://metacast.app/podcast/the-traderlion-podcast/rXxhcWFL/how-to-identify-the-best-market-windows-for-maximum-returns-roy-and-wesley-mattox/0600Go81)；[来源5](https://www.linkedin.com/in/roy-mattox-13069312)
- 缺失规则：入场细则、减仓/保护浮盈执行价格和时点；单笔账户风险、加仓/亏损串复位及组合相关性；全量订单、费用、资本和容量
- 下一步：核听原演讲并获取同期胜败订单；将5%–8%股价止损与账户风险分开；分别研究分批止盈和浮盈保护，不用教学胜率作实测值

### Tanmay Khandelwal（tanmay_khandelwal）

- 别名：TwoX Capital Management
- 实现边界：以main 5bd4c16d73a9ca7b2b2d2c94b145b4949e2eb339为准：无专属策略代码或运行结果；仅研究框架。不可与Aryan Khandelwal混同，不能把2023印度股票成绩写成美股方法验证。
- 来源账本：[studies/trader_registry/dossiers/remaining/tanmay_khandelwal.sources.json](../../studies/trader_registry/dossiers/remaining/tanmay_khandelwal.sources.json)；[studies/trader_registry/dossiers/remaining/source_ledger.json](../../studies/trader_registry/dossiers/remaining/source_ledger.json)
- main代码：无可归属的当前文件
- main报告：无可归属的当前文件
- 原始来源入口：[来源1](https://financial-competitions.com/previousstandings/2024/1/23/december-standings-2023)；[来源2](https://twoxcapital.com/)；[来源3](https://getpodcast.com/podcast/the-traderlion-podcast/24-year-old-trading-champion-shares-million-dollar-strategy-129_2e4229b904)；[来源4](https://www.youtube.com/watch?v=eney0dClrpI)；[来源5](https://www.elearnmarkets.com/face2face/details/investing-championship-trading-strategies-revealed)
- 缺失规则：Big/Trustworthy Management的时点研究定义；仓位、初始止损、卖出比例、杠杆与频率；2023比赛账户与后续基金边界
- 下一步：核听成功/失败案例及卖出章节；冻结2023身份、规则和印度时点财报/管理层证据；迁移美股/A股/港股必须另立假设

### Judy Lai（judy_lai）

- 别名：无另列别名
- 实现边界：以main 5bd4c16d73a9ca7b2b2d2c94b145b4949e2eb339为准：无专属策略实现或运行结果；只有身份/成绩及关联方方法归因。不得复制J Law代码冠名Judy；MYT @JLawStock是赛事品牌标签，不是同一人证明。
- 来源账本：[studies/trader_registry/dossiers/remaining/judy_lai.sources.json](../../studies/trader_registry/dossiers/remaining/judy_lai.sources.json)；[studies/trader_registry/dossiers/remaining/source_ledger.json](../../studies/trader_registry/dossiers/remaining/source_ledger.json)
- main代码：无可归属的当前文件
- main报告：无可归属的当前文件
- 原始来源入口：[来源1](https://financial-competitions.com/previousstandings/2025/2/12/december-final-standings-2024)；[来源2](https://www.jlawstock.com/myt)
- 缺失规则：本人选股范围、入出场、初始止损、仓位及加减仓；多空、财报、频率、净值和费用；两个参赛账户与MYT计划的逐时对应
- 下一步：取得本人授权的2024规则版本与赛前计划；分别核对两个账户的现金流与胜败订单；保持Judy、J Law与Adrian三份独立身份

### Leos Mikulka（leos_mikulka）

- 别名：无另列别名
- 实现边界：以main 5bd4c16d73a9ca7b2b2d2c94b145b4949e2eb339为准：无专属策略代码或运行结果；风险轨迹可研究。高曝光个例不是固定配置，二手参数不能冒充已认证原版。
- 来源账本：[studies/trader_registry/dossiers/remaining/leos_mikulka.sources.json](../../studies/trader_registry/dossiers/remaining/leos_mikulka.sources.json)；[studies/trader_registry/dossiers/remaining/source_ledger.json](../../studies/trader_registry/dossiers/remaining/source_ledger.json)
- main代码：无可归属的当前文件
- main报告：无可归属的当前文件
- 原始来源入口：[来源1](https://financial-competitions.com/previousstandings/2025/2/12/december-final-standings-2024)；[来源2](https://financial-competitions.com/previousstandings/2025/1/18/november-standings-2024)；[来源3](https://podcasts.apple.com/us/podcast/300-return-in-the-us-investing-championship-leos/id1586336923?i=1000660792211)；[来源4](https://traderlion.com/profile/leos-mikulka/how-leos-mikulka-returned-409-in-the-2024/)
- 缺失规则：具体入场、加仓顺序、分段止损与逐日杠杆；二手回顾465/960.4/46.6/52不同口径冲突；完整交易和连续资金记录
- 下一步：核原始12月复盘及官方月度结单；对齐ARM/SMR订单与风险轨迹；先做集中度/回撤口径审查，再考虑规则研究

### Adrian Law（adrian_law）

- 别名：WhiteBear.trading
- 实现边界：以main 5bd4c16d73a9ca7b2b2d2c94b145b4949e2eb339为准：无专属策略代码或运行结果。官方姓名/品牌已核，方法仍阻塞；不能把来源编辑错误或TTP/个人挑战口径当比赛原版。
- 来源账本：[studies/trader_registry/dossiers/remaining/adrian_law.sources.json](../../studies/trader_registry/dossiers/remaining/adrian_law.sources.json)；[studies/trader_registry/dossiers/remaining/source_ledger.json](../../studies/trader_registry/dossiers/remaining/source_ledger.json)
- main代码：无可归属的当前文件
- main报告：无可归属的当前文件
- 原始来源入口：[来源1](https://financial-competitions.com/previousstandings/2026/1/24/december-standings-2025)；[来源2](https://trading-tournaments.com/traders/adrian-law)；[来源3](https://www.instagram.com/whitebear.trading/)
- 缺失规则：访谈日期、本人确认和账户映射；工具、频率、持仓、止损、仓位、加仓及借券；具体执行规则和容量
- 下一步：先取得本人原帖对访谈的确认；核比赛开始结单和带事前计划的一笔完整交易；保持与Law Wai-Sum/J Law及Judy Lai的身份区分

### Pavel P. Sterba（pavel_sterba）

- 别名：Pavel Sterba
- 实现边界：以main 5bd4c16d73a9ca7b2b2d2c94b145b4949e2eb339为准：无专属策略代码或运行结果。官方成绩和部分资金/职业锚点不能导出可执行策略。
- 来源账本：[studies/trader_registry/dossiers/remaining/pavel_sterba.sources.json](../../studies/trader_registry/dossiers/remaining/pavel_sterba.sources.json)；[studies/trader_registry/dossiers/remaining/source_ledger.json](../../studies/trader_registry/dossiers/remaining/source_ledger.json)
- main代码：无可归属的当前文件
- main报告：无可归属的当前文件
- 原始来源入口：[来源1](https://www.businesswire.com/news/home/20220124005241/en/)；[来源2](https://course.zangertradingu.com/courses/priceaction)
- 缺失规则：本人方法来源与赛时版本；股票池、触发、退出、风险、频率、做空和杠杆；起始金额/盈利精度差异、现金流和月结
- 下一步：先找本人访谈确认方法而非移植Ryan Pierpont规则；取得连续券商月结及赛时计划；未公开时保留证据审查，不声称策略复刻

### Hsiu-Ping Peng（hsiu_ping_peng）

- 别名：无另列别名
- 实现边界：以main 5bd4c16d73a9ca7b2b2d2c94b145b4949e2eb339为准：无专属策略代码或运行结果。现有可靠证据为参赛身份/结果；同名短期指标目录仅候选线索。
- 来源账本：[studies/trader_registry/dossiers/remaining/hsiu_ping_peng.sources.json](../../studies/trader_registry/dossiers/remaining/hsiu_ping_peng.sources.json)；[studies/trader_registry/dossiers/remaining/source_ledger.json](../../studies/trader_registry/dossiers/remaining/source_ledger.json)
- main代码：无可归属的当前文件
- main报告：无可归属的当前文件
- 原始来源入口：[来源1](https://www.businesswire.com/news/home/20220124005241/en/)；[来源2](https://financial-competitions.com/previousstandings/2020/10/13/december-2019-final)；[来源3](https://stockcharts.com/public?asc=true&category=Cycle+Analysis&sort=)
- 缺失规则：同名StockCharts作者与参赛者身份桥接；全部选股/入出场/仓位/风险和执行规则；2019 H.P.Peng与完整姓名/账户的对应
- 下一步：先确认StockCharts作者身份；再取得赛前图表及订单；不用同名职业资料或栏目标题推导策略

### Sam Bhatia（sam_bhatia）

- 别名：无另列别名
- 实现边界：以main 5bd4c16d73a9ca7b2b2d2c94b145b4949e2eb339为准：无专属策略代码或运行结果；主办披露职业背景与方法规则分开，规则仍阻塞。
- 来源账本：[studies/trader_registry/dossiers/remaining/sam_bhatia.sources.json](../../studies/trader_registry/dossiers/remaining/sam_bhatia.sources.json)；[studies/trader_registry/dossiers/remaining/source_ledger.json](../../studies/trader_registry/dossiers/remaining/source_ledger.json)
- main代码：无可归属的当前文件
- main报告：无可归属的当前文件
- 原始来源入口：[来源1](https://financial-competitions.com/previousstandings/2023/2/21/december-2022-standings)；[来源2](https://www.businesswire.com/news/home/20230125005300/en/)
- 缺失规则：选股因子、触发/持仓周期、仓位和退出；止损/加减仓、杠杆、费用、净值路径与容量；赛事身份对应的本人方法材料
- 下一步：先取得能绑定赛事身份的长访谈或机构资料；补账户月结、交易市场和代表订单；不从熊市正收益或投行背景推导对冲/量化风格

### Sean Goodsell（sean_goodsell）

- 别名：无另列别名
- 实现边界：以main 5bd4c16d73a9ca7b2b2d2c94b145b4949e2eb339为准：无专属策略代码或运行结果；搜索索引中的职业/研究入口不构成完整方法，两个参赛账户不得拼接。
- 来源账本：[studies/trader_registry/dossiers/remaining/sean_goodsell.sources.json](../../studies/trader_registry/dossiers/remaining/sean_goodsell.sources.json)；[studies/trader_registry/dossiers/remaining/source_ledger.json](../../studies/trader_registry/dossiers/remaining/source_ledger.json)
- main代码：无可归属的当前文件
- main报告：无可归属的当前文件
- 原始来源入口：[来源1](https://financial-competitions.com/previousstandings/2023/2/21/december-2022-standings)；[来源2](https://financial-competitions.com/previousstandings/2020/10/13/december-2019-final)；[来源3](https://www.linkedin.com/in/sean-goodsell-aa0145133)
- 缺失规则：两个比赛账户的映射与各自策略；入出场、持仓、频率、杠杆、止损及组合约束；全部订单、现金流与容量
- 下一步：先取得本人确认账户映射及2022交易例；阅读日期化研究正文，区分观点与成交；排除同名创意工作者/房产人士

### Moritz Reinhart（moritz_reinhart）

- 别名：AQS（机构关联）
- 实现边界：以main 5bd4c16d73a9ca7b2b2d2c94b145b4949e2eb339为准：无专属策略代码或运行结果；机构身份关联增强，但文章与比赛策略未连接，不能由机构奖项推断已验证规则。
- 来源账本：[studies/trader_registry/dossiers/remaining/moritz_reinhart.sources.json](../../studies/trader_registry/dossiers/remaining/moritz_reinhart.sources.json)；[studies/trader_registry/dossiers/remaining/source_ledger.json](../../studies/trader_registry/dossiers/remaining/source_ledger.json)
- main代码：无可归属的当前文件
- main报告：无可归属的当前文件
- 原始来源入口：[来源1](https://financial-competitions.com/previousstandings/2023/2/21/december-2022-standings)；[来源2](https://financial-competitions.com/previousstandings/2024/1/23/december-standings-2023)；[来源3](https://aqsinvestments.com/about)；[来源4](https://aqsinvestments.com/)；[来源5](https://aqsinvestments.com/author/moritz-reinhart/)
- 缺失规则：趋势跟踪文章正文、作者/日期及是否赛时执行；市场/周期、组合、多空/衍生品边界、再平衡和风险；个人比赛与现行机构组合的账户及版本连接
- 下一步：取得文章正文与实际执行参数；用2022订单确认方法关联；现行AQS组合另建时期与资产范围

### Luis Carlos Tarin（luis_carlos_tarin）

- 别名：无另列别名
- 实现边界：以main 5bd4c16d73a9ca7b2b2d2c94b145b4949e2eb339为准：无专属策略代码或运行结果；不把Louis Carlos Tarin列为已确认别名，不拼接跨年收益或同名人物资料。
- 来源账本：[studies/trader_registry/dossiers/remaining/luis_carlos_tarin.sources.json](../../studies/trader_registry/dossiers/remaining/luis_carlos_tarin.sources.json)；[studies/trader_registry/dossiers/remaining/source_ledger.json](../../studies/trader_registry/dossiers/remaining/source_ledger.json)
- main代码：无可归属的当前文件
- main报告：无可归属的当前文件
- 原始来源入口：[来源1](https://financial-competitions.com/previousstandings/2024/1/23/december-standings-2023)；[来源2](https://financial-competitions.com/previousstandings/2025/2/12/december-final-standings-2024)；[来源3](https://www.idcrawl.com/luis-tarin)
- 缺失规则：Luis与2024 Louis拼写是否同一人/账户尚未确认；@LuisTarin4与参赛者身份桥接；全部市场、选股、频率、仓位、退出、止损和账本
- 下一步：先核主办方/本人的拼写及社交身份说明；再补市场、账户起始日和连续结单；不与David Tarin或同名公职/商业人士混同

### Miguel Zambrano Sánchez（miguel_zambrano_sanchez）

- 别名：Miguel Zambrano、Miguel Zambrano Sanchez、@ZambranoSMiguel
- 实现边界：以main 5bd4c16d73a9ca7b2b2d2c94b145b4949e2eb339为准：无专属策略代码或运行结果。新档案已取得本人短期/波段框架，不能继续称完全无方法；完整触发仍不足以实施，不能拿日线替代盘前盘后执行。
- 来源账本：[studies/trader_registry/dossiers/remaining/miguel_zambrano_sanchez.sources.json](../../studies/trader_registry/dossiers/remaining/miguel_zambrano_sanchez.sources.json)；[studies/trader_registry/dossiers/remaining/source_ledger.json](../../studies/trader_registry/dossiers/remaining/source_ledger.json)
- main代码：无可归属的当前文件
- main报告：无可归属的当前文件
- 原始来源入口：[来源1](https://financial-competitions.com/previousstandings/2024/1/23/december-standings-2023)；[来源2](https://www.businesswire.com/news/home/20220124005241/en/)；[来源3](https://www.escuelatraders.com/post/entrevista-a-miguel-zambrano-3er-puesto-united-states-investing-championship-2023)
- 缺失规则：日内/波段精确触发与止损/止盈算法；67%/33%按资本或次数等分母、100%杠杆语义；各模式账户/时段/股票/成交和费用映射
- 下一步：把盘前盘后日内与1–3周波段分开；两模式各补一胜一负的赛前计划和订单；核实杠杆、资金分配及市场范围

### 张棋（zhang_qi）

- 别名：Zhang Qi
- 实现边界：main 5bd4c16d73a9ca7b2b2d2c94b145b4949e2eb339无可识别的该人专属实现；不迁入历史策略代码。历史research/individual-trader-studies分支 9bc6a6b29c577d4ad6d6d13312beaf15ae7ab1f2：现已完成E1真实行业ETF三分支价格机制及固定成本敏感性，E0仅历史。strict撮合未认证，现金分红不完整，不是本人完整策略、净总回报或独立样本外。与叙市身份暂独立，不计为两个独立成功样本。 历史代码：https://github.com/QSothoth/s-alpha/blob/9bc6a6b29c577d4ad6d6d13312beaf15ae7ab1f2/studies/zhang_qi/checks.py；历史报告：https://github.com/QSothoth/s-alpha/blob/9bc6a6b29c577d4ad6d6d13312beaf15ae7ab1f2/studies/zhang_qi/reports/RESULTS.md
- 来源账本：[studies/trader_registry/dossiers/china/source_ledger.json](../../studies/trader_registry/dossiers/china/source_ledger.json)；[studies/trader_registry/dossiers/china/source_ledger.md](../../studies/trader_registry/dossiers/china/source_ledger.md)
- main代码：无可归属的当前文件
- main报告：无可归属的当前文件
- 原始来源入口：[来源1](https://www.cls.cn/detail/1683118)；[来源2](https://www.cls.cn/detail/1406483)
- 缺失规则：技术/基本面/资金流排序及入出场和风险预算；原比赛具体场次、账户和案例ETF代码；与叙市的实名绑定、全账本、现金流及真实执行
- 下一步：补原始最终分场榜、结单及三个案例事前记录；分开技术价格机制与产业判断；核ETF可卖制度、分红、容量和真实撮合

### 叙市（xushi）

- 别名：叙市XushiETF、XushiETF
- 实现边界：main 5bd4c16d73a9ca7b2b2d2c94b145b4949e2eb339无可识别的该人专属实现；不迁入历史策略代码。历史research/individual-trader-studies分支 9bc6a6b29c577d4ad6d6d13312beaf15ae7ab1f2：仅E0证据门禁；有evidence.py不代表信号策略实现。未取得专有公式/版本，不用60日突破替代；与张棋实名关系未闭合。 历史代码：https://github.com/QSothoth/s-alpha/blob/9bc6a6b29c577d4ad6d6d13312beaf15ae7ab1f2/studies/xushi/evidence.py；历史报告：https://github.com/QSothoth/s-alpha/blob/9bc6a6b29c577d4ad6d6d13312beaf15ae7ab1f2/studies/xushi/reports/RESULTS.md
- 来源账本：[studies/trader_registry/dossiers/china/source_ledger.json](../../studies/trader_registry/dossiers/china/source_ledger.json)；[studies/trader_registry/dossiers/china/source_ledger.md](../../studies/trader_registry/dossiers/china/source_ledger.md)
- main代码：无可归属的当前文件
- main报告：无可归属的当前文件
- 原始来源入口：[来源1](https://www.caiwennews.com/article/857353.shtml)；[来源2](https://caifuhao.eastmoney.com/news/20230605114141071686610)；[来源3](https://caifuhao.eastmoney.com/news/20230727153733250432530)；[来源4](https://poi.10jqka.com.cn/store/formula/detail/indexid/318635)；[来源5](https://xueqiu.com/1993371359/250594652)；[来源6](https://www.yinsfinance.com/article/832510.shtml)
- 缺失规则：V2/V3公式、参数版本、重绘情况及全部历史信号；可卖库存、仓位、隔夜和退出规则；跨平台身份与实名/赛时版本绑定
- 下一步：先取得合法原公式或日期化历史信号；核跨平台身份及获奖账户对应；保留人工覆盖与已有底仓/当日新买的执行区别

### Li666（li666）

- 别名：无另列别名
- 实现边界：main 5bd4c16d73a9ca7b2b2d2c94b145b4949e2eb339无可识别的该人专属实现；不迁入历史策略代码。历史research/individual-trader-studies分支 9bc6a6b29c577d4ad6d6d13312beaf15ae7ab1f2：仅E1-screen真实名义价格/300前缀筛选；覆盖极窄且有当前存续池偏差。没有买入持有模拟或该交易者策略收益。 历史代码：https://github.com/QSothoth/s-alpha/blob/9bc6a6b29c577d4ad6d6d13312beaf15ae7ab1f2/studies/li666/screen.py；历史报告：https://github.com/QSothoth/s-alpha/blob/9bc6a6b29c577d4ad6d6d13312beaf15ae7ab1f2/studies/li666/reports/RESULTS.md
- 来源账本：[studies/trader_registry/dossiers/china/source_ledger.json](../../studies/trader_registry/dossiers/china/source_ledger.json)；[studies/trader_registry/dossiers/china/source_ledger.md](../../studies/trader_registry/dossiers/china/source_ledger.md)
- main代码：无可归属的当前文件
- main报告：无可归属的当前文件
- 原始来源入口：[来源1](https://app.dahecube.com/nweb/news/20211103/111301nca063cc1a56.htm)；[来源2](https://spds.ccnew.com.cn/introduce.shtml)
- 缺失规则：企业研究标准、预期差和入场触发；集中度、融资、仓位调整、退出/止损及空仓；2021计分规则、IPO贡献和资金流
- 下一步：补2021原榜和赛段规则及IPO剔除明细；获取本人愿意公开的股票代码、事前研究及全部胜败订单；不反向猜测约3元买入的大赢家

### 二池（erchi）

- 别名：无另列别名
- 实现边界：main 5bd4c16d73a9ca7b2b2d2c94b145b4949e2eb339无可识别的该人专属实现；不迁入历史策略代码。历史research/individual-trader-studies分支 9bc6a6b29c577d4ad6d6d13312beaf15ae7ab1f2：已执行E1四组真实A股价格事件及严格拒单账簿；严格账簿无成交。缺产业论据、历史ST/限价与费用，非完整策略、可成交组合或净收益。 历史代码：https://github.com/QSothoth/s-alpha/blob/9bc6a6b29c577d4ad6d6d13312beaf15ae7ab1f2/studies/erchi/checks.py；历史报告：https://github.com/QSothoth/s-alpha/blob/9bc6a6b29c577d4ad6d6d13312beaf15ae7ab1f2/studies/erchi/reports/RESULTS.md
- 来源账本：[studies/trader_registry/dossiers/china/source_ledger.json](../../studies/trader_registry/dossiers/china/source_ledger.json)；[studies/trader_registry/dossiers/china/source_ledger.md](../../studies/trader_registry/dossiers/china/source_ledger.md)
- main代码：无可归属的当前文件
- main报告：无可归属的当前文件
- 原始来源入口：[来源1](https://m.tgb.cn/a/2dVOWdW2Lpm?type=hot)；[来源2](https://m.tgb.cn/a/2err4uoNmhQ?type=hot)；[来源3](https://tgb.cn/user/blog/myspmath?userID=9435281)；[来源4](https://www.9db.com/user/7c156618-9ee7-4da6-af62-54a41a95dce3)；[来源5](https://www.tgb.cn/dialog/2eYbNKW3IVz_83172956_1)；[来源6](https://kdocs.cn/l/cntVsLnAM9Kn)
- 缺失规则：事前产业池、修复/均线定义与仓位；三日修复原回复待逐句重核，不作为本轮新增确认；融资/现金流、真实订单、涨跌停/停牌及原始交割单
- 下一步：合法取得已公开交割单并统一各赛事映射；将事前产业观点、失效日期与全部交易配对；核10/20日不同语境，不事后挑成功产业

### 这股有毒（zhegu_youdu）

- 别名：无另列别名
- 实现边界：main 5bd4c16d73a9ca7b2b2d2c94b145b4949e2eb339无可识别的该人专属实现；不迁入历史策略代码。历史research/individual-trader-studies分支 9bc6a6b29c577d4ad6d6d13312beaf15ae7ab1f2：仅E0-accounting资金流与工具边界实现；没有策略信号收益。入金不可计作回报，转股不是瞬时无风险套利。 历史代码：https://github.com/QSothoth/s-alpha/blob/9bc6a6b29c577d4ad6d6d13312beaf15ae7ab1f2/studies/zhegu_youdu/accounting.py；历史报告：https://github.com/QSothoth/s-alpha/blob/9bc6a6b29c577d4ad6d6d13312beaf15ae7ab1f2/studies/zhegu_youdu/reports/RESULTS.md
- 来源账本：[studies/trader_registry/dossiers/china/source_ledger.json](../../studies/trader_registry/dossiers/china/source_ledger.json)；[studies/trader_registry/dossiers/china/source_ledger.md](../../studies/trader_registry/dossiers/china/source_ledger.md)
- main代码：无可归属的当前文件
- main报告：无可归属的当前文件
- 原始来源入口：[来源1](https://m.tgb.cn/a/25sBhQzDWpM?type=hot)；[来源2](https://www.tgb.cn/user/blog/myspmath?userID=1301470)；[来源3](https://www.tgb.cn/a/29WhTgXRnHh)；[来源4](https://www.bilibili.com/video/BV11S421R7ii/)；[来源5](https://www.youtube.com/watch?v=vGXywJUCUAY)
- 缺失规则：竞价事前预期、入出场、分支归因和风险上限；转股资格/到账/可卖时间、费用与实际成交；全部现金流，特别是2024-04-18额外入金
- 下一步：先核各赛事账户及完整入出金表；各模式分别收集订单与失败案例；取得转债和竞价执行证据后再定规则

### 归因（guiyin）

- 别名：无另列别名
- 实现边界：main 5bd4c16d73a9ca7b2b2d2c94b145b4949e2eb339无可识别的该人专属实现；不迁入历史策略代码。历史research/individual-trader-studies分支 9bc6a6b29c577d4ad6d6d13312beaf15ae7ab1f2：仅E0-accounting，原账本未读、审计未完成。没有低吸策略或净收益实现；本人核验声明与本研究核验状态分开。 历史代码：https://github.com/QSothoth/s-alpha/blob/9bc6a6b29c577d4ad6d6d13312beaf15ae7ab1f2/studies/guiyin/accounting.py；历史报告：https://github.com/QSothoth/s-alpha/blob/9bc6a6b29c577d4ad6d6d13312beaf15ae7ab1f2/studies/guiyin/reports/RESULTS.md
- 来源账本：[studies/trader_registry/dossiers/china/source_ledger.json](../../studies/trader_registry/dossiers/china/source_ledger.json)；[studies/trader_registry/dossiers/china/source_ledger.md](../../studies/trader_registry/dossiers/china/source_ledger.md)
- main代码：无可归属的当前文件
- main报告：无可归属的当前文件
- 原始来源入口：[来源1](https://www.tgb.cn/dialog/2eYbNKW3IVz_83172956_1)；[来源2](https://www.tgb.cn/a/2eB2qhDdRJg)；[来源3](https://www.tgb.cn/user/blog/myspmath?userID=8950857)；[来源4](https://www.9db.com/info/detail/A6FC95A7-BAF0-4F26-A3D2-4C81A947181D)；[来源5](https://www.9db.com/user/faa62429-9845-4158-8e44-032872dca4ab?type=blog)；[来源6](https://www.bilibili.com/video/BV1eDrpYaEJc/)；[来源7](https://kdocs.cn/l/cm5xnCnUZCIZ)
- 缺失规则：本人完整方法、入场/加仓/退出和风险预算；第三方不打板说法与首板案例冲突；赛事/第三方口径、融资净资产、资金流及交割单
- 下一步：优先合法读取原始公开交割单并映射赛事；核听完整原访谈并校对全部订单；不把单股三分之一等二次总结当固定规则

### 低调科科员（didiao_kekeyuan）

- 别名：无另列别名
- 实现边界：main 5bd4c16d73a9ca7b2b2d2c94b145b4949e2eb339无可识别的该人专属实现；不迁入历史策略代码。历史research/individual-trader-studies分支 9bc6a6b29c577d4ad6d6d13312beaf15ae7ab1f2：仅E0证据对象和不变量测试；无可执行热点轮动策略。半年度冠军不能写全年冠军，分仓不自动证明低风险。 历史代码：https://github.com/QSothoth/s-alpha/blob/9bc6a6b29c577d4ad6d6d13312beaf15ae7ab1f2/studies/didiao_kekeyuan/evidence.py；历史报告：https://github.com/QSothoth/s-alpha/blob/9bc6a6b29c577d4ad6d6d13312beaf15ae7ab1f2/studies/didiao_kekeyuan/reports/RESULTS.md
- 来源账本：[studies/trader_registry/dossiers/china/source_ledger.json](../../studies/trader_registry/dossiers/china/source_ledger.json)；[studies/trader_registry/dossiers/china/source_ledger.md](../../studies/trader_registry/dossiers/china/source_ledger.md)
- main代码：无可归属的当前文件
- main报告：无可归属的当前文件
- 原始来源入口：[来源1](https://www.tgb.cn/user/blog/myspmath?userID=2167007)；[来源2](https://m.tgb.cn/a/1Uztryjrjrg?type=hot)；[来源3](https://k.sina.com.cn/article_5952915720_162d2490806704ihrc.html)；[来源4](https://m.tgb.cn/a/2iAfrtwEaD6)；[来源5](https://www.bilibili.com/video/BV1EFpNeZEeu/)
- 缺失规则：本人完整原访谈及精确买卖/仓位规则；入出金、融资、资金规模与逐笔胜败；页面50%仓位/0股票等字段含义
- 下一步：先核完整访谈和核验账本；查明期末/中途报单字段，不移植邻近作者交易；保留半年度与全年赛事区别

### 投资如人生（touzi_ru_rensheng）

- 别名：无另列别名
- 实现边界：main 5bd4c16d73a9ca7b2b2d2c94b145b4949e2eb339无可识别的该人专属实现；不迁入历史策略代码。历史research/individual-trader-studies分支 9bc6a6b29c577d4ad6d6d13312beaf15ae7ab1f2：仅E0-risk风险/融资压力工具与不变量测试；没有均值回归alpha。特定日期不足30%仓位不是固定择时阈值，完整策略仍阻塞。 历史代码：https://github.com/QSothoth/s-alpha/blob/9bc6a6b29c577d4ad6d6d13312beaf15ae7ab1f2/studies/touzi_ru_rensheng/risk.py；历史报告：https://github.com/QSothoth/s-alpha/blob/9bc6a6b29c577d4ad6d6d13312beaf15ae7ab1f2/studies/touzi_ru_rensheng/reports/RESULTS.md
- 来源账本：[studies/trader_registry/dossiers/china/source_ledger.json](../../studies/trader_registry/dossiers/china/source_ledger.json)；[studies/trader_registry/dossiers/china/source_ledger.md](../../studies/trader_registry/dossiers/china/source_ledger.md)
- main代码：无可归属的当前文件
- main报告：无可归属的当前文件
- 原始来源入口：[来源1](https://m.tgb.cn/a/2eDSCQ6c6tL?type=hot)；[来源2](https://m.tgb.cn/a/2eDSCQ6c6tL-2?type=hot)；[来源3](https://www.tgb.cn/user/blog/myspmath?userID=856449)；[来源4](https://m.tgb.cn/a/2fF8HogWPXN)；[来源5](https://kdocs.cn/l/ch6JpoRINMOp)；[来源6](https://kdocs.cn/l/ctytoHFuRBps)；[来源7](https://m.tgb.cn/a/2rcSbfzmFSy-3?type=hot)
- 缺失规则：精确入出场、加减仓、风险预算和模式版本；提款后本金、融资负债/利息、担保比例和强平线；全部订单、资金流与后续亏损段
- 下一步：补合法可读月度交割单与资金流；核原访谈及真实融资尾部风险；将低点起算自述与比赛赛段保持分离

### Qullamaggie（qullamaggie）

- 别名：Kristjan Kullamägi、Kristjan Kullamagi、@Qullamaggie
- 实现边界：2026-10-20 main：在统一数据层 trader-data-v1 上按本人原话逐环节复刻（日 K、收盘或前一日决定的限价 / 开盘入场），R11 N3 + S7（多空一体） 经用户同意登记冻结在 studies/trader_replication/systems.py，比对表与交易员看板运行同一版本；多头 R11 把“卖后立刻保本”改为“+2R 才保本”（偏离原话，为胜率门禁）；空头为小盘抛物线收红后开盘 / 反弹卖空；全部是样本内（2024-01-02 → 2026-10-16 逐轮选择），冻结后的前向记录才是样本外；是有限假设的日线翻译，不是本人完整系统，盘中入场、锚定 VWAP、反向 / 指数 ETF 等不在其中。
- 来源账本：[studies/trader_registry/dossiers/qullamaggie/source-ledger.md](../../studies/trader_registry/dossiers/qullamaggie/source-ledger.md)
- main代码：[studies/qullamaggie/replicate.py](../../studies/qullamaggie/replicate.py)；[studies/trader_replication/system.py](../../studies/trader_replication/system.py)；[studies/trader_replication/shorts.py](../../studies/trader_replication/shorts.py)；[studies/trader_replication/systems.py](../../studies/trader_replication/systems.py)
- main报告：[studies/qullamaggie/reports/SHORTS_CN.md](../../studies/qullamaggie/reports/SHORTS_CN.md)；[studies/qullamaggie/reports/FINAL_CN.md](../../studies/qullamaggie/reports/FINAL_CN.md)
- 原始来源入口：[来源1](https://qullamaggie.com/my-3-timeless-setups-that-have-made-me-tens-of-millions/)；[来源2](https://qullamaggie.com/about/)；[来源3](https://qullamaggie.com/faq/)；[来源4](https://qullamaggie.com/how-to-master-a-setup-episodic-pivots/)；[来源5](https://qullamaggie.com/some-good-tweetstorms/)；[来源6](https://twitter.com/Qullamaggie/status/1344675459934662657)；[来源7](https://twitter.com/Qullamaggie/status/1344626907573342208)；[来源8](https://chatwithtraders.com/episode/212-kristjan-kullamagi-breakouts-home-runs-exponential-returns)；[来源9](https://www.maoxian.com/thoughts/notes-for-chat-with-traders-episode-212)；[来源10](https://tradingresourcehub.substack.com/p/interview-qullamaggie-chat-with-traders-part1?open=false)；[来源11](https://podme.com/no/episode/935561/)；[来源12](https://www.daytrading.se/svenske-tradern-kristjan-kullamagi-i-chat-with-traders/)；[来源13](https://www.wsj.com/articles/short-selling-stocks-proves-costly-for-some-investors-11599645600)；[来源14](https://omni.se/borshaj-fran-arboga-drog-in-305-miljoner-pa-ett-ar/a/lVLKnk)；[来源15](https://nyheter205.rssing.com/chan-4974127/article43172.html)；[来源16](https://www.reddit.com/r/qullamaggie/comments/1buvei7/qullamaggie_tax_returns_since_2013_capital/)；[来源17](https://www.reddit.com/r/qullamaggie/comments/1o5tgpy/qullamaggie_tax_returns_2024/)；[来源18](https://www.panmacmillan.com/authors/jack-d-schwager/market-wizards-the-next-generation/9781804093641)；[来源19](https://completetradersedge.com/kristjan-kullamagi-qullamaggie/)；[来源20](https://www.reddit.com/r/qullamaggie/comments/13hjo2l)；[来源21](https://www.elitetrader.com/et/threads/how-do-famous-swing-traders-like-dan-zanger-size-up-so-fast.377082/page-22)；[来源22](https://qullamaggie.com/)；[来源23](https://www.youtube.com/qullamaggie)；[来源24](https://www.youtube.com/watch?v=K0F73Sq90j0)；[来源25](https://www.youtube.com/watch?v=KciAjkEFA6s)；[来源26](https://www.youtube.com/playlist?list=PLV4rgdMPi5CgtRwngmf79U2G5LA066LNa)；[来源27](https://youtu.be/VtBYmOR83oU?t=3755)；[来源28](https://stockbee.blogspot.com/2021/05/learn-to-make-money.html)；[来源29](https://stockbee.blogspot.com/2022/01/always-use-stops.html)；[来源30](https://github.com/axidzz/Qullamaggie-Setups/blob/main/Qullamaggie_Setups.pine)；[来源31](https://github.com/ycchew/CQ_breakout_strategy)；[来源32](https://github.com/udaydivvela/qullamaggie-strategies)；[来源33](https://github.com/VladPetrariu/Qullamaggie-breakout-scanner)；[来源34](https://github.com/HodlHook/momentum-breakout-postmortem)；[来源35](https://findasset.de/strategie/qullamaggie)；[来源36](https://www.kqscan.com/)；[来源37](https://www.reddit.com/r/Daytrading/comments/1bzze12)；[来源38](https://www.reddit.com/r/qullamaggie/comments/1ibzkm3)；[来源39](https://www.reddit.com/r/qullamaggie/comments/1gcqtzd)；[来源40](https://www.kristjankullamagi.com/)；[来源41](https://www.reddit.com/r/qullamaggie/comments/1vj2dh3/my_notes_on_qullamaggie_from_the_market_wizards/)；[来源42](https://uu.diva-portal.org/smash/get/diva2%3A1687559/FULLTEXT01.pdf)；[来源43](https://setupalpha.com/products/parabolic-short-realtest-qullamaggie-strategy)；[来源44](https://excessreturnspod.substack.com/p/full-transcript-jack-schwager-on)；[来源45](https://www.toptradersunplugged.com/podcast/inside-the-next-generation-market-wizards-ft-jack-schwager-george-coyle/)
- 缺失规则：有序/紧凑形态、市场过滤、事件意外程度和候选拒绝定义；2021早期设置与11月EP风险范围、入口和退出版本；全账户净值/现金流/订单、容量、借券及后续规则变化
- 下一步：合法核对原书章与作者核验范围；对官方视频建立逐段可验证索引；未来只选一个日期版本/setup/股票池先冻结定义，再决定研究

### Oliver Kell（oliver_kell）

- 别名：无另列别名
- 实现边界：2026-10-20 main：在统一数据层 trader-data-v1 上按本人原话逐环节复刻（日 K、收盘或前一日决定的限价 / 开盘入场），R6 A5 + S5（多空一体） 经用户同意登记冻结在 studies/trader_replication/systems.py，比对表与交易员看板运行同一版本；空头为 Wedge Drop 后反抽到下行 10 / 20 EMA 的限价空单（指数 < 50 EMA，最多 10 天）；全部是样本内（2024-01-02 → 2026-10-16 逐轮选择），冻结后的前向记录才是样本外；是有限假设的日线翻译，不是本人完整系统，盘中入场、锚定 VWAP、反向 / 指数 ETF 等不在其中。
- 来源账本：[studies/trader_registry/dossiers/swing/sources.json](../../studies/trader_registry/dossiers/swing/sources.json)；[studies/trader_registry/dossiers/swing/sources.csv](../../studies/trader_registry/dossiers/swing/sources.csv)
- main代码：[studies/oliver_kell/replicate.py](../../studies/oliver_kell/replicate.py)；[studies/trader_replication/system.py](../../studies/trader_replication/system.py)；[studies/trader_replication/shorts.py](../../studies/trader_replication/shorts.py)；[studies/trader_replication/systems.py](../../studies/trader_replication/systems.py)
- main报告：[studies/oliver_kell/reports/SHORTS_CN.md](../../studies/oliver_kell/reports/SHORTS_CN.md)；[studies/oliver_kell/reports/FINAL_CN.md](../../studies/oliver_kell/reports/FINAL_CN.md)
- 原始来源入口：[来源1](https://financial-competitions.com/previousstandings/2021/1/13/december-2020-standings)；[来源2](https://financial-competitions.com)；[来源3](https://www.tradingwithrayner.com/the-stock-trader-who-made-941-1-in-a-year-with-oliver-kell/)；[来源4](https://stockbsessed.substack.com/p/oliver-kell-interview-the-mind-and)；[来源5](https://www.global-bolsa.com/2021/05/grabacion-y-chat-conversatorio-con.html)；[来源6](https://traderlion.com/technical-analysis/chart-patterns/wedge-pop-the-money-pattern/)；[来源7](https://traderlion.com/technical-analysis/chart-patterns/ema-crossback/)；[来源8](https://traderlion.com/technical-analysis/chart-patterns/downside-ema-crossback-sell-short-into-resistance/)；[来源9](https://traderlion.com/technical-analysis/chart-patterns/wedge-drop-how-to-sell-short/)；[来源10](https://traderlion.com/profile/oliver-kell/mu-wedge-pop/)；[来源11](https://traderlion.com/profile/oliver-kell/amd-wedge-pop/)；[来源12](https://traderlion.com/profile/oliver-kell/cava-breakout/)；[来源13](https://traderlion.com/profile/oliver-kell/arm-reversal-extension/)；[来源14](https://github.com/passiontrader/oliver-kell-price-action-rulebook/blob/main/Oliver_Kell_Price_Action_Rulebook.md)；[来源15](https://github.com/wubo1992/signal-system-oliver/blob/main/docs/PRD_v_oliver_kell_2026-05-15.md)；[来源16](https://www.buzzsprout.com/1745226/episodes/11598278-2020-u-s-investing-champion-oliver-kell-tells-his-story)
- 缺失规则：setup图形边界、10/20EMA选择、分批及加仓；1–3%风险说法分母未明确；MU/ARM/AMD回顾日期异常、完整成交与容量
- 下一步：按setup和发布日期保留规则；对照原图/订单核日期及分批加权收益；合法核原书与原音，第三方规则书不作本人算法
