# 35位交易员：经历、方法与证据档案

研究截至：2026-10-18。用途：把交易员的经历、方法演变、交易案例和可核实证据整理成可追溯的资料库，供后续策略研究使用。本次没有开展新的回测。

## 先读结论

这次覆盖原研究名单33人，另加Qullamaggie与Oliver Kell两份方法参考档案。这里的“35人”是档案覆盖人数，不等于35套已实现策略、35个独立Alpha或35份完整审计记录。各人的公开资料深度不一，稀疏者保留具体缺口，不能用别人相似的策略替代其本人方法。

优先阅读：Qullamaggie、Martin Luk、Mark Minervini、Oliver Kell、Ryan Pierpont、Sean Ryan、J Law、Goverdhan Gajjala。这是资料与方法研究优先级，不是资金分配或预期收益排名。

## 如何使用证据

- 本人文章、回答和采访：可以支持“本人如此描述”，不能单独证明收益真实、完整或可复制
- 主办方成绩：支持特定账户、组别与期间名次；不等于全职业生涯或完整策略审计
- 记者/作者查看账单：比无凭据自述更强，但需说明查看哪些期间、账户、现金流，不能自动称会计师独立审计
- 第三方独立报道：用于交叉核查特定事实；多篇转载同一个采访并不增加独立性
- 社区批评、第三方代码与回测：帮助发现反例和实现差异；匿名金额、未跑代码和改造策略不能被升级为本人业绩事实
- 未读、不可访问、只定位到视频或付费内容的资料均不能当作已完整核验

每个人的档案尽量涵盖经历与失败、学习过程、方法演变、具体设置、风险/仓位/容量、实际案例、来源冲突和缺口。未披露的胜率、平均盈亏比、持仓天数或空头规则，不按常识填数。

## 阅读目录

### 动量体系与方法参考
- [Qullamaggie / Kristjan Kullamägi](qullamaggie/dossier.zh.md)：完整独立资料档案；此前仅零散引用，未纳入原33人的独立Study
- [Qullamaggie逐项来源账本](qullamaggie/source-ledger.md)
- [Martin Luk](swing/martin_luk.md)
- [Mark Minervini](swing/mark_minervini.md)
- [Oliver Kell（追加方法参考）](swing/oliver_kell.md)
- [Ryan Pierpont](swing/ryan_pierpont.md)
- [Sean Ryan](swing/sean_ryan.md)
- [Vibha Jha](swing/vibha_jha.md)

### 活跃波段与日内交易
- [Clement Ang](active/clement_ang.md)
- [Deepak Uppal](active/deepak_uppal.md)
- [Christian Flanders](active/christian_flanders.md)
- [J Law / Law Wai-Sum](active/j_law.md)
- [Goverdhan Gajjala](active/goverdhan_gajjala.md)
- [Gemy Zhou](active/gemy_zhou.md)
- [Ty Rajnus / Rajnus Capital LLC](active/ty_rajnus.md)

### 中国市场八位人物/账号
- [张棋](china/zhang_qi.md)
- [叙市](china/xushi.md)
- [Li666](china/li666.md)
- [二池](china/erchi.md)
- [这股有毒](china/zhegu_youdu.md)
- [归因](china/guiyin.md)
- [低调科科员](china/didiao_kekeyuan.md)
- [投资如人生](china/touzi_ru_rensheng.md)
- [中国部分总览与平台历史展示限制](china/README.md)

### 其余13位具名对象
- [逐人索引](remaining/README.md)
- [资料深度与独立性](remaining/COVERAGE_DEPTH_CN.md)
- [原报告中另外出现的排名/观察名单](remaining/COVERAGE_ONLY_APPENDIX_CN.md)：仅名单附录，不计入35份档案数量，也不宣称全部逐人重新核验

## 与已发布代码研究的关系

原代码与实验报告：[独立研究分支](https://github.com/QSothoth/s-alpha/tree/research/individual-trader-studies)。本资料包补充和纠正证据归因，不会自动改变既有回测代码或结果，也不构成新增样本外证据。发现新规则或版本冲突后，应先定位日期、账户和设置，再另行预登记实验。

原Release：[trader-studies-20261017-v1](https://github.com/QSothoth/s-alpha/releases/tag/trader-studies-20261017-v1)。其中公开数据并非全部复现输入；许可受限或未明确的行情数据缺口仍然存在。

## 主要边界

1. 公开资料研究无法保证全网穷尽，特别是删除内容、付费课程、未公开交割单与无法完整播放的长视频
2. 不将冠军/高收益年份等同长期可靠性；同时保留亏损、回撤、爆仓风险和幸存者偏差
3. 规则随时间改变，ADR倍数、R倍数、仓位百分比和账户风险必须区分；不能拼成从未存在的“原版系统”
4. 本包以原创中文归纳、少量必要引文与链接为主，不附整本书、完整付费课程或大段原文转载
5. 文中涉及交易判断均为方法研究；公开资料不能保证未来收益，做空另有借券、逼空和无限损失风险


## 本轮最值得回查的规则问题

- [Martin减仓规则版本与现有代码对照](swing/MARTIN_VERSION_CROSSWALK.md)：本人2025年2月披露的3×ADR，不等于代码中按初始风险计算的3R。较晚访谈原声尚待核验，不能武断认定此后所有3R表述均错
- [Clement档案](active/clement_ang.md)：官方比赛收益与宣传收益账户/期间尚未对齐；AMA包含有条件容忍较大回撤及跳空时改变止损处理的裁量例外
- [Vibha档案](swing/vibha_jha.md)：核实2021/2023相应股票组为亚军，不能由营销标题改写为两届冠军
- [Qullamaggie档案](qullamaggie/dossier.zh.md)：作者查阅记录、节目中的其他人审计要求、匿名社区税务说法应分别处理
- [独立复核记录](AUDIT_CN.md)：列明抽查范围和未核验边界，不是35人每句话或全部交易的审计证明
