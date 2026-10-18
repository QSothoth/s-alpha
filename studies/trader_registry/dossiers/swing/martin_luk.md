# Martin Luk｜原始披露、版本冲突与交易证据

## 核心判断
适合研究高波动美股趋势交易及低胜率下的风险控制。最重要纠正是：2025-02-06本人评论写首次减仓阈值为 **>3×ADR**，不是3R；现有研究代码来自较晚访谈的AI摘要，现阶段应标记版本冲突待回听，不能宣判所有3R用法错误。

## 生涯、亏损与风格演变
ML1是经编辑协作发表的本人来稿。晚2020开始，2021遭约50%回撤，随后受Qullamaggie影响；2023起改善；2024经历约30%回撤和18连亏，仍坦承尚未稳定。这些是个人叙述，没有全期间净值账本。2024官方283.1%，2025官方969.8%分别为普通股票组第六和第一（C24/C25）。2025年11月累计1358.2%到年底969.8%，同口径月末权益推算约下降26.64%；不是把收益百分点相减当回撤，也不是完整最大回撤（CN25）。

## 按日期保留原始系统
- **2025-02文章版**：高波动趋势股，9/21/50EMA关系和板块表现；ADR>5%是偏好。账户计划风险通常.5–1%；价格止损多1–5%，不超过半ADR。均线出场、低胜率与大盈利单并存，不代表固定盈亏比可稳定兑现（ML1）
- **2025-02-02扫描器评论版**：Potent市值>100M、周波动>3.5%、价>21EMA、Vol×Price>50M；盘前另有10日均量>500K；leader以周Vol×Price>300M并按过去1个月表现排序。不要把不同扫描器拼成一个AND条件（ML4）
- **2025-02-06退出评论版**：首次涨幅>3×ADR减约10%，用9或23EMA跟踪；ADR期数、收益参照点、10%分母未明。2月17日回复确认当时未变（ML2/3）
- **2025-04访谈候选版**：原视频未听，AI摘要说3R、9/21/50EMA。不能覆盖2月本人陈述，也不能断言原声说了3R（ML6/7）
- **2025-04草稿、2026-01发表的做空研究版**：下降21/50EMA与摆动高点AVWAP阻力；破前一小时低点或VWAP/高点AVWAP回测失败进空。图形研究明确仍有裁量；QQQ/IWM均线过滤的研究愿望不能追认为既定规则（ML5）
- **2026-01长访谈**：提及从突破向回调、AVWAP等新主题，仅核验节目章节；待原声核验后才能追加数值版（ML8/9）

## 具体交易与不能推导的内容
ML1列有2024 GME约54R、SMCI约22R等精选标注，缺成交导出。ML2对SMCI说明2024-01-09把止损抬至01-08低点293.5（拆股前），不是293.5的入场证明。分批、费用、滑点和R分母均影响实际收益；不能用教学图倒推出逐笔权益。

仓位上限35%、平均盈利持有5天、104胜319负等目前来自AI摘要，不升级为可靠原始参数。104/(104+319)=24.59%，与同页23%不同，可能统计口径或摘要误差。2026节目3:19容量、46:10十二月回撤有明确章节入口，但未听，不编造容量上限。更少交易、风险缩放和市场条件之间的关系仍缺完整数据。

## 代码、论文和旧研究对照
现有repo属于研究者实现；未发现经身份确认由Martin发布的完整可执行系统或学术论文。另见 MARTIN_VERSION_CROSSWALK.md。关键问题不是选更好看的回测参数，而是先修正来源层级和版本标注。本轮未改代码、未回测。

## 下一步证据缺口
优先听ML6的减仓原声，核对日期、3R/3ADR和10%/15%；取得本人ADR定义、持仓容量、全部成交及资金流；保留2月评论的edited状态。X传播内容若不能直达原帖和日期，不补写为本人证据。

## 证据边界与阅读状态
访问日期：2026-10-18。文中来源编号对应文末链接和 sources.json / sources.csv 的逐项断言账本。read 表示读取网页正文或提取文字；read_excerpt 表示仅片段；discovery_metadata_only 只作待读入口。视频章节文字、节目简介和完整听看是不同证据层级，本轮没有把未听视频声称为已核验原声。

比赛名次可由主办方确认，但不是公开全量券商审计。自述、教学图、主办方榜单、记者有限报表核查、匿名论坛反馈分别使用，转载和镜像不重复计算独立来源。收益为特定年份/参赛账户，不能代表可复制的长期预期收益。未找到不等于不存在。本资料为历史研究，不构成交易建议。

## 已读来源与待核入口
- **C19** [USIC 19 year final standings](https://financial-competitions.com/previousstandings/2020/10/13/december-2019-final)｜2020-01-01｜organizer_results｜read；限制：主办方比赛结果；不等于全职业生涯、全账户逐笔审计；组别不可混比
- **C20** [USIC 20 year final standings](https://financial-competitions.com/previousstandings/2021/1/13/december-2020-standings)｜2021-01-13｜organizer_results｜read；限制：主办方比赛结果；不等于全职业生涯、全账户逐笔审计；组别不可混比
- **C21** [USIC 21 year final standings](https://financial-competitions.com/previousstandings/2022/1/18/december-31-standings)｜2022-01-18｜organizer_results｜read；限制：主办方比赛结果；不等于全职业生涯、全账户逐笔审计；组别不可混比
- **C22** [USIC 22 year final standings](https://financial-competitions.com/previousstandings/2023/2/21/december-2022-standings)｜2023-02-21｜organizer_results｜read；限制：主办方比赛结果；不等于全职业生涯、全账户逐笔审计；组别不可混比
- **C23** [USIC 23 year final standings](https://financial-competitions.com/previousstandings/2024/1/23/december-standings-2023)｜2024-01-23｜organizer_results｜read；限制：主办方比赛结果；不等于全职业生涯、全账户逐笔审计；组别不可混比
- **C24** [USIC 24 year final standings](https://financial-competitions.com/previousstandings/2025/2/12/december-final-standings-2024)｜2025-02-12｜organizer_results｜read；限制：主办方比赛结果；不等于全职业生涯、全账户逐笔审计；组别不可混比
- **C25** [USIC 25 year final standings](https://financial-competitions.com/previousstandings/2026/1/24/december-standings-2025)｜2026-01-24｜organizer_results｜read；限制：主办方比赛结果；不等于全职业生涯、全账户逐笔审计；组别不可混比
- **CR** [USIC home and current standings](https://financial-competitions.com)｜日期未确认｜organizer_rules_summary｜read；限制：完整规则为图片，未完成逐项图像核验；2026进行中结果不作全年结果
- **CN25** [Previous standings archive](https://financial-competitions.com/previousstandings/)｜2026-01-24｜organizer_results｜read；限制：月端推算不等于真实最大回撤；需假设同一可比较资金调整口径
- **ML1** [The 22-Year-Old Who Returned 283% in USIC 2024](https://tradingresourcehub.substack.com/p/martin-luk-283-usic-2024-key-lessons)｜2025-02-01｜first_person_guest_article｜read；限制：Kyna编辑，明确Martin来稿；个人回顾和精选图不等于成交账本
- **ML2** [Martin Luk reply: SMCI and partials](https://tradingresourcehub.substack.com/p/martin-luk-283-usic-2024-key-lessons/comment/91396123)｜2025-02-06 (edited)｜first_person_comment｜read；限制：未定义ADR回看期、涨幅参照价、10%分母；编辑前版本未知
- **ML3** [Martin Luk follow-up](https://tradingresourcehub.substack.com/p/martin-luk-283-usic-2024-key-lessons/comment/94073578)｜2025-02-17｜first_person_comment｜read；限制：不能自动推断之后所有版本也不变
- **ML4** [Martin Luk screener settings](https://tradingresourcehub.substack.com/p/martin-luk-283-usic-2024-key-lessons/comment/90457733)｜2025-02-02 (edited)｜first_person_comment｜read；限制：TradingView字段；Vol×Price周期不能自行统一，货币单位原文隐含美股美元
- **ML5** [Low-Friction Study Process](https://tradingresourcehub.substack.com/p/martin-luk-study-process)｜2026-01-10; draft 2025-04｜first_person_guest_article｜read；限制：回顾性图形研究非验证；未来研究想法不当作已执行硬规则
- **ML6** [283% Gain: Martin Luk interview](https://www.youtube.com/watch?v=lS9zbnLi1Gg)｜2025-04-06 (podcast mirror)｜firsthand_interview_video｜discovery_metadata_only；限制：仅打开页面，未取得音频/逐字稿，不认定任何原声时间戳
- **ML7** [AI summary of Martin interview](https://youtubesummary.com/summary/lS9zbnLi1Gg)｜日期未确认｜machine_summary｜read；限制：机器摘要非原声；104/423=24.59%；5%portfolio risk等可疑，不能用于定案
- **ML8** [+969% Return: Martin Luk](https://www.youtube.com/watch?v=VKNEJA5r8zw)｜2026-01-31｜firsthand_interview_video｜discovery_metadata_only；限制：原视频未观看；章节来自镜像说明，不是核验原声
- **ML9** [Martin Luk 2026 episode chapters](https://share.snipd.com/episode/2ecc451e-3f05-4f2b-8ccd-83d2d741e3ad)｜2026-01-31｜podcast_mirror｜read；限制：只核验章节文字，不核验音频内容
- **ML10** [Martin Luk EP10 livestream](https://www.youtube.com/watch?v=O1LZJYaMqnQ&t=820)｜2025-12-15｜own_video_link｜discovery_metadata_only；限制：出处给出的深链；未观看音频，不可称已核验原声
