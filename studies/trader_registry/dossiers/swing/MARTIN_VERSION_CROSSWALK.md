# Martin Luk：ADR／R、减仓比例与现有代码来源对照

访问日期：2026-10-18。仅检查来源及代码，未修改策略、未回测。

## 已确认的本人表述

- 作者：Martin Luk；日期2025-02-06，页面标记Edited
- [直接评论](https://tradingresourcehub.substack.com/p/martin-luk-283-usic-2024-key-lessons/comment/91396123)
- [完整评论列表备用入口](https://tradingresourcehub.substack.com/p/martin-luk-283-usic-2024-key-lessons/comments)
- 原句（16词）： “The first partial is sold when the stock goes up for >3*ADR.”
- 同一回复表示每批约10%，9或23EMA跟踪；SMCI案例2024-01-09把止损提高至2024-01-08低点293.5（拆股前）。这是止损参考，不是买入价
- [2025-02-17回复](https://tradingresourcehub.substack.com/p/martin-luk-283-usic-2024-key-lessons/comment/94073578)确认当时方法未变；不能证明之后没有演进
- ADR回看长度、上涨的参照点、10%按初始还是剩余仓位计算均未明示；不能自行填补

## 来源与代码逐项映射

| 对象 | 实际内容 | 证据判断 |
|---|---|---|
| 本人2025-02-06评论 | 首次>3×ADR；约10%；9或23EMA | 日期明确的原始披露 |
| 2025-04-06访谈候选视频 lS9zbnLi1Gg | 本轮未核验原声 | 不能断言视频说3R或3ADR |
| youtubesummary.com/summary/lS9zbnLi1Gg | AI摘要写3R；分批与均线叙述 | 机器转述，待回听；不是独立原始证据 |
| studies/martin_luk/notes/SOURCES.md 第3行 | 引上述AI摘要，归纳+3R减10–15%、9/21/50EMA等 | 现有研究并非直接引2月本人评论；归因链可靠性不足 |
| studies/martin_luk/luk.py:41–42 | trims=(3,6,9,12)，trim_frac=.15；注释按初始股数 | 固定后续R梯级和分母是研究机械化选择，不由2月评论支持 |
| luk.py:282、285及292附近 | q.fill+k*R；卖cfg.trim_frac*q.shares0 | R以实际入场及策略风险构成；与ADR度量不同 |
| studies/martin_luk/intraday.py:102–103、304–312、326–334 | 同样3/6/9/12R、初始股数15%，含多空实现 | 多空对称性亦须独立原始证据，不能由多头评论推导 |

检查基线：QSothoth/s-alpha，research/individual-trader-studies；当时读取树commit 9bc6a6b29c577d4ad6d6d13312beaf15ae7ab1f2，并检查恢复的对应工作副本。

## 为什么这不是小的数值替换

R衡量入场至初始止损的交易风险；ADR衡量标的日常波动。举例：假设止损距离2%、ADR5%，3R对应6%价格变化，3ADR对应15%，并不相等。此例仅说明量纲差异，不是本人参数，也不假定评论的涨幅基准已经明确。

2月本人评论与4月访谈候选之间可能存在策略变化、不同setup、摘要错误或不同用词。现有证据只能确认“该2月版本不支持直接写成3R”，不能确认“后来所有3R均错误”。也不能把23EMA悄悄修成21EMA。

## 应如何处理旧研究结果

1. 旧回测仍可作为研究者定义的3R梯级系统结果，标签应与本人原始复现区分
2. 不要只将3改成ADR就宣布修复；还需确定ADR长度、价格参照、分批分母、后续批次、23/21EMA以及不同setup的适用性
3. 优先取得4月视频中退出规则的原声和时间戳，保留前后文与发表日期
4. 原AI摘要还有104胜319负与23%胜率不一致（前者计算24.59%）及5%账户风险可疑等问题，提示应逐项回查，不能批量接受

本次为资料增补与规则对照，未修改策略代码、开展新回测或推送更新。
