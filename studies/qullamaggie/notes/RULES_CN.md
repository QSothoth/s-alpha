# Qullamaggie（Kristjan Kullamägi）的做法按环节整理（原话出处）

2026-10-18 整理。来源：一手网页 S01（三形态指南）、S03（FAQ）、S04（EP 进阶），文本存 `data/qullamaggie-subs/web/`；本人频道 2023 年直播的自动字幕（`en-orig`，存 `data/qullamaggie-subs/`，不进 Git），出处写成 `视频id@时间戳`（30 秒一段）。档案见 [dossier.zh.md](../../trader_registry/dossiers/qullamaggie/dossier.zh.md)，交易台账见 [trades.csv](trades.csv)。英文是字幕原文短引文，中文是转述；字幕听错的票名在台账里标了“ticker 存疑”。

| 直播 id | 日期 | 标题 |
|---|---|---|
| 1AJIzXSkfyM | 2023-05-18 | Episodic Pivots galore |
| _y9Wo0eBP4A | 2023-05-19 | Episodic Pivots, Kenny boy and old times |
| 2UgJ5CvVVK4 | 2023-05-23 | EPs good follow through |
| 1HFPeLD2zwc | 2023-06-01 | AI and the shittier the stock, the bigger the move |
| C7ZZhSxYYLk | 2023-06-05 | Zzzlow |
| SLhbpNuHegw | 2023-06-08 | EPs, AI and quantum computing stocks |
| VdQSDGZBLQE | 2023-06-09 | Market mechanics, setups and more |
| TZnX1qEiOkM | 2023-12-01 | EP party! |
| JNVA5cd_m7M | 2023-12-15 | Speculation money is back! |

## 看板初版取值 → 他的原话

| 初版（研究者取值） | 他的原话 | 处理 |
|---|---|---|
| 突破 + EP 两种都做 | 2023 年“几乎只做 EP，突破从 2021-11 后就不灵了”（1AJIzXSkfyM@00:02:30；2UgJ5CvVVK4@00:23:30） | 逐轮比较只做 EP |
| EP：跳空 ≥ 10% 且全天量 ≥ 20 日均量 3 倍 | 跳空 10%+（直播放宽到 8–10%），开盘 15–20 分钟就成交日均量（S04；1AJIzXSkfyM@00:20:00）；最好的 EP 之前横盘 3–6 个月以上（S04） | 先保留，横盘条件逐轮比较 |
| 每笔风险 0.5% | 多数 0.3–0.5%，很少超过 1%（S03） | 保留 |
| 第 3 天盈利卖 1/3，余仓 10 日线 | 3–5 天卖 1/3–1/2 再把止损移到成本，余仓 10 / 20 日线（S01）；他自己多用 20 日线，大盘股 20、小盘股 10（SLhbpNuHegw@00:25:30；_y9Wo0eBP4A@00:24:30） | 逐轮比较保本、20 日线 |
| 无市况过滤 | QQQ 的 10 日线在 20 日线上方且都向上才是绿灯，不好时少做或减仓（1AJIzXSkfyM@00:35:30；VdQSDGZBLQE@00:55:30） | 逐轮比较 |
| 同时 10 只、每天 3 笔 | “不会再同时持 30 只”（2UgJ5CvVVK4@00:23:00）；2023-05 持仓约 8–12 只，全是 EP | 保留 |
| 成交额 ≥ 2000 万、ADR ≥ 4 | ADR 4–5 以上、最好两位数（_y9Wo0eBP4A@00:48:30）；仓位不超过日均量 1%（1AJIzXSkfyM@00:29:00）；小盘低流动性的放在免税小账户 | 保留 |

## 0. 2023 年的重点变化（先读这一节）

- **2023 年几乎只做 EP，不做突破。** 1AJIzXSkfyM@00:02:30 "I pretty much switched to almost only EPs nowadays I don't even bother with breakouts"；1AJIzXSkfyM@00:02:00 "I have only EPs in my portfolio right now"；2UgJ5CvVVK4@00:23:30 "breakouts they haven't really been working since like November 2021 … EPs have been working fine but breakouts I don't trust"；TZnX1qEiOkM@00:23:00 "I haven't really traded breakouts since 2021 EPs have worked way better … 50 times better"；JNVA5cd_m7M@00:14:00 同样的说法。
- **为什么突破失效：** 突破要靠趋势市；2022–2023 是区间市，小盘股也没动。2UgJ5CvVVK4@00:25:30–00:27:00 "you need a trending market for breakouts to work … breakouts work the best on small cap small and mid caps in an uptrending Market"；VdQSDGZBLQE@01:27:00 "breakouts are best to buy when the market is just coming out of a correction"。
- **他说自己最大的毛病是过度交易。** JNVA5cd_m7M@00:16:30 "I over trade every year … I'll take half size but you do a half size in a market that's bad and you do it 10 times it kind of adds up … usually my biggest detractor every year"。

## 1. 股票池

- **只做美股和美国 ETF**（S03 "I also trade the U.S. ETFs"）。
- **ADR 下限：** _y9Wo0eBP4A@01:10:30 "you shouldn't really trade stocks below ADR 4 … most of its stocks I have you know ADR five seven eight ten twelve thirteen"；_y9Wo0eBP4A@00:48:30 "focus on stocks at ADR four or five plus and even better in the double digits"（ORCL ADR 1.4 被他嘲笑）；SLhbpNuHegw@00:54:00 BA "ADR 2.3 … very slow"；SLhbpNuHegw@01:03:30 "4.9 is okay"；TZnX1qEiOkM@00:25:00 1.9 ADR 不看。ADR 的定义是 20 日 (H/L) 的平均值减 1（S03 有公式）。
- **流动性和容量：** 1AJIzXSkfyM@00:29:00 "you don't want to be more than one percent of the average daily volume of a stock because otherwise the slippage is gonna be crazy bad"。练习用的扫描条件是 5 日平均成交额 ≥ 100 万美元（1AJIzXSkfyM@00:24:30），这是给小账户用的门槛。他自己大账户的票要够流动，太薄就放弃，例如 SLhbpNuHegw@00:17:30 "too thin for me"、TZnX1qEiOkM@00:21:00 DRCT。SLhbpNuHegw@00:31:30 举例说 PLTR "you can do like a million shares 2 million"。档案 S07 转述：成交额门槛从约 2000 万美元提到 1.5 亿美元。
- **“小账户优势”与分账户：** 他把免税 ISK 小账户专门用来放小盘、低流动性的“多倍股”（QBTS、RGTI、APLD、ARQQ）。VdQSDGZBLQE@01:18:00–01:18:30 "that's how you build small accounts … small account edge"；1AJIzXSkfyM@00:23:30 "best way to grow a small account is to buy small caps"。
- **按股性排除：** 历史走势来回震荡、回归均值的票不做，例如 TTWO、ESTC、NVO、ORCL、WDAY。TZnX1qEiOkM@00:25:00 "some stocks are just incredibly choppy they shouldn't be traded"；SLhbpNuHegw@00:53:00 "I always go back and look like how does it trade"。纽交所股票动量比纳斯达克弱（TZnX1qEiOkM@00:26:00）。
- **不碰的事件：** 有收购传闻、指数纳入的不做（SLhbpNuHegw@00:26:00 "I never trade things with buyout rumors or index additions"）；生物科技股临床数据公布前几天不买（VdQSDGZBLQE@01:07:00 "I'm not gonna buy a few days before a data release"）；不太信任中概股的 EP（VdQSDGZBLQE@00:57:00）。
- **越烂的票涨得越多：** 1HFPeLD2zwc@00:47:00 "pieces of [*] … make the biggest moves"；SLhbpNuHegw@00:44:30。股价 0.5 美元以上他也能接受（1HFPeLD2zwc@00:46:30 "am I comfortable trading 50 cent stocks yeah"），但 WDSCP 那只 0.8 美元，他嫌太便宜（VdQSDGZBLQE@00:54:00）。
- **不做期权：** S03 "It's like poison"；JNVA5cd_m7M@00:24:00 只考虑用 LEAPS 买大盘股。

## 2. 什么算强

- **S01：** 选 1、3、6 个月涨幅排前 1–2% 的股票。
- **相对强度：** 大盘回调时比指数抗跌，例如 2022-10 的 NVDA、AMD（_y9Wo0eBP4A@00:46:30–00:47:30），2023 年中概下跌时的 PDD、LI（TZnX1qEiOkM@00:18:00，1HFPeLD2zwc@00:55:00）。
- **成交量第一：** 2UgJ5CvVVK4@00:14:30 "volume always trumps numbers"；1HFPeLD2zwc@00:35:30 他判断板块轮动只看一句 "price and volume is it going up on big volume"。持续放量比一次性放量重要，见 SLhbpNuHegw@00:33:00 讲 QBTS、RGTI 天天放量。
- **主题和板块：** 例如 2023 年 1 月他提前做好 AI 和量子计算名单（约 120 只），2023 年底在跟减肥药 GLP-1（2UgJ5CvVVK4@00:25:00，TZnX1qEiOkM@00:36:30–00:37:30）。EP 往往先出现，板块随后才变热（TZnX1qEiOkM@00:47:00）。
- **故事比基本面重要：** 1HFPeLD2zwc@00:48:00 "stories are way more powerful than fundamentals"。前瞻预期比当期数字重要（VdQSDGZBLQE@00:41:30），他用 MarketSmith 和 Koyfin 看过去 8 个季度和未来两年的预期（_y9Wo0eBP4A@00:25:30–00:26:30）。

## 3. 观察名单与每日流程

- 开盘前 20–30 分钟查跳空股、新闻，开盘后看成交量，前 30 分钟完成入场，"takes one hour every day"（2UgJ5CvVVK4@00:36:00）。
- 1AJIzXSkfyM@00:25:30："30 minutes before the Market opens until 30 minutes after"。
- 2UgJ5CvVVK4@00:38:30："most of my trading happens in the first say 30 45 minutes probably like 70 80 percent"。
- VdQSDGZBLQE@01:04:00：开盘前 30 分钟看跳空股和新闻，开盘后看谁有量。
- 他每天建当日名单，名单上标财报和预期（1HFPeLD2zwc@00:50:00）。S01 要求开盘前名单、警报和股数都备好。
- **练习用扫描（教学用，不是他的选股条件）：**
  - 14 个交易日内涨 50%，回看 150 个交易日，5 日平均成交额 ≥ 100 万美元，结果约 444 只（1AJIzXSkfyM@00:21:00–00:24:30）；
  - 22 个交易日内涨 50%，回看约 5 个月，成交量 ≥ 100 万，结果约 205 只（SLhbpNuHegw@00:20:00–00:21:30）。
- 观察名单上出现的是“基础形态”（base），不等于他会买，他会说"I'm just looking for an entry point but they're not there yet"（1AJIzXSkfyM@00:33:00）。

## 4. 形态

### 4.1 EP（2023 年的主力形态）

- **定义：** S04 "a gap up of 10% or more. There has to be massive volume near the open, ideally the stock should trade the average daily volume the first 15-20 minutes"。S01 写的是 "Gap up 10%+"，并且开盘后 15–30 分钟内成交量要达到日均量。2023 年直播里他放宽到 "gap up 8 10 percent plus sometimes 50 percent or even 100"（1AJIzXSkfyM@00:20:00），扫描时看 "gapping up 10 15 percent"（_y9Wo0eBP4A@01:12:00）。
- **基本面：** S01 和 S04 要求 EPS、收入增速达到两位数中高段甚至三位数，最好大幅超预期并上调指引。2023 年他补充：没有利润、只有收入高增长的也行；数字差但成交量大照样能涨，例如 ACVA "numbers were [*] but it worked"（2UgJ5CvVVK4@00:14:00）、APP 收入增速只有 14%（_y9Wo0eBP4A@00:08:30）。漏掉 SMCI 是因为他嫌增速在放缓（VdQSDGZBLQE@01:22:30）。
- **最好的 EP 前面横盘很久：** S04 "best EPs are on stocks that have gone sideways for 3-6 months or more"；S01 "best if the stock has not rallied over the past 3-6 months"。直播里的说法："broke a multi-year range and huge volume"（_y9Wo0eBP4A@01:07:30）；DRCT "going sideways for years"（TZnX1qEiOkM@00:05:30）；CELH "two-year base, higher lows for a year"（1AJIzXSkfyM@00:40:30）。二次 EP 失败率更高（S04），他举了 VKTX 的例子，并说自己因此错过（_y9Wo0eBP4A@00:38:30）。
- **星级：** 五星的例子是 YEXT，"biggest volume ever … had a base … higher lows"（SLhbpNuHegw@00:38:00），还有 DRCT（三位数增长、大幅上调指引、巨量、多年底部）。四星的例子是 IOT（SLhbpNuHegw@00:31:00）。成交量只有日均 4 倍的 PWR 算一般（1AJIzXSkfyM@00:41:30）。
- **种类：** 财报（最主要）、FDA/生物科技、合同或合作、板块 EP（例如 QBTS "there is no news it's a sector move it's a sector EP"，2UgJ5CvVVK4@00:24:30）、政治或监管（S04）。
- **会让 EP 失败的情况：** 股价当天在下跌（2UgJ5CvVVK4@00:21:30 "stock that's going down is never a good EP"）；属于最后一批补涨的落后股（VdQSDGZBLQE@00:46:30 PTON）；行动慢、喜欢回归均值的股票（SLhbpNuHegw@00:53:00）。

### 4.2 突破（Breakout）

- S01 的三步：过去 1–3 个月有一段 30–100%+ 的上涨；之后有序回调，低点抬高、振幅收窄，整理 2 周到 2 个月，期间沿 10、20 日线（有时 50 日线）走；最后放量突破。
- 直播补充：“好看的旗形”要沿 10、20、50 日线走（JNVA5cd_m7M@00:10:30）；BBBY 是 60 分钟图上的 high tight flag，"higher lows … really tight so you had great risk reward"（_y9Wo0eBP4A@00:56:30）。
- 突破在大盘刚走出调整时最好用，大盘已经连涨一个月后很难做（VdQSDGZBLQE@01:05:30、01:27:00）。

### 4.3 抛物线做空（以及“meaner version”）

- S01 的条件：大盘股几天到几周涨 50–100%+，小盘股涨 300–1000%+，并且连涨 3–5 天以上。
- 入场有三种：跌破开盘区间低点；第一根红色 5 分钟 K；先跌一次，反弹到 VWAP 失败时进场。止损放在当日高点，或价格重新站上 VWAP。目标是 10、20 日线，盈亏比 5–10 倍。
- 直播强调必须真的“延伸”：UEC 3 天涨 21%、RMTI 5 天涨 50% 都不算（C7ZZhSxYYLk@00:14:30–00:15:30）。CCCC 的第 3 天"five star short day three"（JNVA5cd_m7M@00:04:00）。
- 2023 年他做空减少：VdQSDGZBLQE@01:19:00 "probably do less shorting going forward"，并说做空的单笔幅度有限，"if you're gonna get a 70 on a short that's a really great job"（VdQSDGZBLQE@01:20:30）。
- 做多抛物线（暴跌之后抄底）很少做，太可怕，"I only trade parabolics on the short side"（_y9Wo0eBP4A@01:03:30–01:04:30）。

## 5. 入场

- **开盘区间高点（ORH）** 可以用 1 分钟、5 分钟或 60 分钟 K（60 分钟图第一根只有 9:30–10:00）（S01、S04）。
  - S04："if I bought the 1-minute highs I may add on the 5-minute highs also"；"Often I miss the 1-minute opening range and I will buy the 5-minute highs or 60-minute highs. No need to be first in"。
  - 直播：1AJIzXSkfyM@00:26:30–00:27:00 "just wait for the first say five minute candle … five minute highs keep it simple"。
- **入场时间窗口：** SLhbpNuHegw@00:39:00 "most EPs you will have to enter in the first say three to ten minutes … some you can enter after a half an hour or two hours"。GTLB 是开盘约 1 小时后进的，APLD 是 1 小时后才突破 5 分钟高点（先破了日低）。VVOS 是开盘后 1–1.5 小时突破开盘区间高点。
- **成交量确认：** 第一根 1 分钟 K 的量放到日均量的很大比例就算确认，例如 SLhbpNuHegw@00:40:30 讲 CVNA："300 almost 400,000 one minute volume bar … average daily volume … 1 million"。CXAI "traded like 10 million shares in the first minute"（JNVA5cd_m7M@00:04:30）。
- **EP 必须第一天买：** JNVA5cd_m7M@00:05:00 "you always buy day one"。他很少在盘前盘后交易（S04）。
- **重新入场和加仓：** CVNA 被止损两次后第三次再买（_y9Wo0eBP4A@00:32:30）；FTCH（存疑）EP 当天被止损，次日又买；ALT 第一天在跳空回落时买，两天后量价守住再加，之后又加一次（JNVA5cd_m7M@00:11:00）。
- **建仓节奏和杠杆：** TZnX1qEiOkM@00:46:00 "you go from 0% to 20 30 and then a few days later you up it again … after a few weeks … fully invested … then you slowly start going on margin"。

## 6. 止损

- **当日低点止损，宽度不超过 ADR/ATR：** S01 "Stop is always lows of the day and stop should not be wider than the ATR or ADR"；S04 写的是 "no more than 1x, or maximum 1.5x the average daily range"。
  - 直播：APLD "the stop will be lows of the day"（1AJIzXSkfyM@00:27:00）；IMGN 差几美分就被打止损（1AJIzXSkfyM@00:34:00）。
- **硬止损和心理止损都用，一律市价止损**（S03）。他很少不执行止损，并说"If you made less than a few million … never"（S03）。
- **止损上移：** 突破后的规则是 3–5 天减仓再把止损移到成本价（S01）；EP 是在价格越过初始止损后改用 10 或 20 日线（S01）。CVNA 跳空高开后他"moved up my stop"（SLhbpNuHegw@00:03:00）。

## 7. 离场

- **3–5 天减仓 1/3 到 1/2，余仓用 10 或 20 日线跟踪，等第一个收盘跌破**（S01）。新手用 10 日线。
- **直播里的实际做法：**
  - 他自己多用 20 日线（SLhbpNuHegw@00:25:30 "I'm mostly using the 20 day for myself in my Trading"），而且是 EMA（VdQSDGZBLQE@01:12:00 "I've been using the 10 EMA"，_y9Wo0eBP4A@00:25:00 "I use the 10 EMA"，两处说法不一致）。
  - 大盘股用 20 日线，小盘和微盘股用 10 日线（_y9Wo0eBP4A@00:24:30，JNVA5cd_m7M@00:17:30 "with large caps it's always the 20 day"）。
  - PDD 收盘跌破 20 日线就走（TZnX1qEiOkM@00:05:00）。W 收盘跌破 10 或 20 日线就走（_y9Wo0eBP4A@00:54:30）。
- **快速大涨时在强势中卖：** 小盘股前 3–5 天涨幅大就减仓，MDGL 进场 3 个交易日后涨 50% 就必须减（_y9Wo0eBP4A@00:23:00–00:24:00）。
  - 几天涨 200–300% 的股票不能用日线均线，要在强势中卖。CCCC 从 2 美元涨到 3.5–3.8，VVOS 当天从 13 涨到 49（JNVA5cd_m7M@00:18:00–00:19:00）。
  - 但他在 TZnX1qEiOkM@00:42:00 又说，微盘股“强势卖出”不如用 60 分钟图的 10、20 EMA 跟踪："if you bought the EP on INDO and sold the next day when it was 130% you missed out"。这两处说法有冲突，都照录。
- **减仓比例示例：** PLTR 先卖 1/10，余仓用 20 日线跟踪（_y9Wo0eBP4A@00:39:30）；AI 留约 1/3 过财报（C7ZZhSxYYLk@00:19:00）。他说 "trim and trail trim and trail"（SLhbpNuHegw@00:57:30）。
- **不按规则离场的情况：** 价格走势不好就主动卖，例如 FSLR、MNDY（_y9Wo0eBP4A@00:07:00）；Z 是因为不信任市场而在强势时卖（_y9Wo0eBP4A@00:06:00）。
- **怎么定离场方法：** 自己研究 500 个以上的形态再决定，"is it best to sell into strength after three to five days or … trade the rest with the 10 or the 20"（SLhbpNuHegw@00:22:30–00:23:30）。S04 也说 EP 的卖出规则要自己定，可以用 20 或 50 日线跟踪。

## 8. 仓位与风险

| 数字 | 出处 |
|---|---|
| 单只股票隔夜不超过账户的 30%（日内可以更多） | S01 |
| 大多数仓位占账户 10–20% | S01 |
| 仓位一般 5–25%，多数在 10–15% | S03 |
| 每笔风险通常 0.25–1%，很少超过 1% | S01 |
| 每笔风险多数时候 0.3–0.5%，很少超过 1% | S03 |
| 账户较小（几百万美元以下）时每笔风险 0.5–1.5% | S01 |
| 2019 年胜率 25% | S03 |
| 2013–2019 年 CAGR 268% | S03 |
| 最大回撤 50%（2014 年）；目标是把回撤控制在 15–20%，一年会发生几次 | S03 |
| 只要 25–30% 的胜率就能大幅盈利，目标是赚到初始风险的 5–20 倍以上；突破和 EP 有时能做到 30–50 倍，抛物线做空约 5–10 倍 | S01 |
| 牛市里赚到初始风险 10–20 倍以上的单子很常见 | S01 |
| 有史以来最大的单只仓位：UCO，约 2500–3000 万美元（2022 年 5 月底突破） | SLhbpNuHegw@01:16:30 |
| 按流动性和信心调整仓位；小盘高波动股放小仓位 | JNVA5cd_m7M@00:15:30（GME、ALT 小仓位，PDD 大仓位）；SLhbpNuHegw@00:35:00 "you don't need to do like big positions" |
| 2022 年 BBBY 前几个月亏，所以下注偏小；2022 年 3 月小盘石油股只用了半仓 | _y9Wo0eBP4A@00:56:30、01:01:00 |
| 不想以后再同时持有 30 只股票："I'm never gonna have 30 positions again" | 2UgJ5CvVVK4@00:23:00 |

## 9. 市况过滤

- **基础过滤：** 1AJIzXSkfyM@00:35:30–00:36:30 "I mostly use QQQs … 10 and the 20-day … the 10 is above the 20 that's good the 10 is going up … the 20 is going up … green light yellow light red light"。女友用 Russell 指数。
- **用法：** 市况不好时少做或减小仓位，"you either do fewer trades or you do smaller size"（1AJIzXSkfyM@00:36:30）。
- **具体判断规则**（VdQSDGZBLQE@00:55:30–00:56:00）：
  - 10 日线在 20 日线之上，并且两条都向上，好；
  - 一条转头向下，谨慎；
  - 两条都向下，更谨慎；
  - 10 日线跌破 20 日线，不好。
- **指标：** 他用 TradingView 上 "Chillax moving averages" 的配色，绿色区域开新仓，黑色区域不交易。他的说法是 "keep you in eighty percent of the good times … out of the market 80 percent of the bad times"（SLhbpNuHegw@00:58:00–01:00:30，VdQSDGZBLQE@00:51:00）。他也在试 MACD 柱状图做红绿灯，觉得它更灵敏（1HFPeLD2zwc@00:42:30，VdQSDGZBLQE@00:51:30）。
- **额外过滤：** 用 100 日线的斜率判断是不是熊市反弹的末段（TZnX1qEiOkM@00:39:00）；"if the 50 is rising too that's nice"（JNVA5cd_m7M@00:03:00）。
- **理想市况：** 低波动的上升趋势，"those are best markets for swing trader … these are the type of markets you can be on margin"（TZnX1qEiOkM@00:46:00）。"you can trade like 20 30% of a year"（TZnX1qEiOkM@00:35:00）；"you get a few of those periods per year"（TZnX1qEiOkM@00:30:30）。
- **适用范围：** 过滤主要管做多的波段交易（突破和 EP）。他说 EP 在任何时候都可能有效，但市况好时更好（VdQSDGZBLQE@00:52:00）。做空和日内交易可以不看这个过滤（SLhbpNuHegw@01:00:30）。
- **成长股要等小盘跟上：** 2023 年 5–6 月他特别看小盘股有没有跟上大盘，"Russell wake up … more stocks participating"（SLhbpNuHegw@00:30:30）；JNVA5cd_m7M@00:09:30 提到罗素指数突破两年下降趋势线。

## 10. 每天笔数、持仓数与频率

- EP 是最少出现的形态，每季集中在财报季的 3–4 周（S04 "mostly occur during a concentrated period of 3-4 weeks every quarter"）；S04 还说要 4–8 个财报季才能学会 EP。
- 每天的交易大多发生在开盘后 30–45 分钟内（2UgJ5CvVVK4@00:38:30）。
- 没有好形态时什么也不做："it's never a good sign when I'm frantically looking for trades … I have a solid portfolio … no need to do anything"（C7ZZhSxYYLk@00:12:30–00:13:00）。
- 持仓数：
  - 2023-05-23 他说 "last time my positions list was this long probably in January"（2UgJ5CvVVK4@00:02:30），以后不会再有 30 只；
  - 2023-05-18 他的持仓全是 EP（PLTR、SHOP、AI、IMGN、MNDY、LI、APLD 等，按我们的台账推算约 8–12 只）。
- 一个财报季内的 EP 单子：2023 年 4–5 月财报季，他在 05-19 回顾时提到的 EP 和近期交易有 PLTR、SHOP、AI、Z、APLD、IMGN、SRPT、FSLR、MNDY、DKNG、CVNA，约 10 只左右（_y9Wo0eBP4A@00:05:00–00:08:30）。其中 SRPT、FSLR、DKNG、CVNA（2 次）被止损，MNDY 主动卖出。
- "you can take vacation most of the time"；"many people … feel like they have to do things all the time"（TZnX1qEiOkM@00:35:00）。

## 11. 其他可用于复刻的细节

- **EP 当天只看分钟图：** 平时只看日线，偶尔看周线和月线；只在开盘时看 1、5、60 分钟图（2UgJ5CvVVK4@00:37:30，VdQSDGZBLQE@01:08:00）。
- **EP 后增发不是坏事：** 生物科技股出好消息后常有增发，而且常常在增发后继续上涨（_y9Wo0eBP4A@00:37:30–00:39:00）。
- **学习方法：** 回看 5 年的 EP，覆盖牛市、熊市和横盘（1AJIzXSkfyM@00:31:00）。
- **2022 年的教训：** 他说 2022 年是亏损年；如果 3 月小盘石油股做了全仓，"I would have had at least a break even year instead of a losing year"（_y9Wo0eBP4A@01:01:30）。这和档案里 2022 年约 -2.29 亿瑞典克朗的线索方向一致。
