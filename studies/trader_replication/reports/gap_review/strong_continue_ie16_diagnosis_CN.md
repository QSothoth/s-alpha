最终遗漏逐笔诊断，按实际成交窗口对应的前晚条件归因。报价中的更早成交只是实际路径，不是换顺序反事实。

| ID | 股票 | 信号 | 遗漏处 | 具体条件 | 窗口内报价及实际更早成交 |
| --- | --- | --- | --- | --- | --- |
| I04 | US.AMC | True | 被别的信号抢先 | 同日更早顺序开仓占用容量，见逐日明细 | [{"day": "2024-05-14", "rank": 7, "signals": 84, "morning": 8, "earlier": ["US.VRT", "US.GME", "US.MSTR"], "same_held": false, "actual_same_day": false}] |
| I05 | US.AMC | True | 被别的信号抢先 | 同日更早顺序开仓占用容量，见逐日明细 | [{"day": "2024-05-14", "rank": 7, "signals": 84, "morning": 8, "earlier": ["US.VRT", "US.GME", "US.MSTR"], "same_held": false, "actual_same_day": false}] |
| I06 | US.SOFI | False | 买点 | 买点 | [] |
| I08 | US.LMND | True | 市况 | 前晚市况未放行 | [] |
| I11 | US.QUBT | True | 被别的信号抢先 | 同日更早顺序开仓占用容量，见逐日明细 | [{"day": "2024-12-17", "rank": 7, "signals": 72, "morning": 6, "earlier": ["US.MARA", "US.IONQ", "US.RKLB", "US.HIMS", "US.AI"], "same_held": false, "actual_same_day": false}, {"day": "2024-12-18", "rank": 6, "signals": 68, "morning": 6, "earlier": ["US.SOUN", "US.AFRM", "US.UPST"], "same_held": false, "actual_same_day": true}] |
| I12 | US.SMTC | False | 领涨状态 | 领涨状态 | [] |
| I22 | US.OKLO | True | 被别的信号抢先 | 同日更早顺序开仓占用容量，见逐日明细 | [{"day": "2025-12-04", "rank": 11, "signals": 368, "morning": 9, "earlier": ["US.MSTR", "US.COIN"], "same_held": false, "actual_same_day": false}, {"day": "2025-12-08", "rank": 6, "signals": 172, "morning": 7, "earlier": ["US.SNDK", "US.AMD", "US.COIN", "US.MU"], "same_held": false, "actual_same_day": false}] |
| I23 | US.OPEN | True | 被别的信号抢先 | 同日更早顺序开仓占用容量，见逐日明细 | [{"day": "2025-11-28", "rank": 13, "signals": 304, "morning": 11, "earlier": [], "same_held": false, "actual_same_day": false}, {"day": "2025-12-10", "rank": 4, "signals": 188, "morning": 8, "earlier": ["US.SNDK", "US.BMNR", "US.WDC"], "same_held": false, "actual_same_day": false}] |
| I26 | US.CSIQ | True | 被别的信号抢先 | 同日更早顺序开仓占用容量，见逐日明细 | [{"day": "2025-11-28", "rank": 42, "signals": 304, "morning": 11, "earlier": [], "same_held": false, "actual_same_day": false}, {"day": "2025-12-01", "rank": 22, "signals": 164, "morning": 10, "earlier": ["US.PLTR"], "same_held": false, "actual_same_day": false}] |
| I27 | US.BBAI | True | 被别的信号抢先 | 同日更早顺序开仓占用容量，见逐日明细 | [{"day": "2025-01-31", "rank": 8, "signals": 98, "morning": 7, "earlier": ["US.CEG", "US.LUNR", "US.TLN", "US.SMR"], "same_held": false, "actual_same_day": false}, {"day": "2025-02-06", "rank": 13, "signals": 123, "morning": 7, "earlier": ["US.RGTI", "US.APP", "US.IONQ", "US.VRT"], "same_held": false, "actual_same_day": false}] |
| I28 | US.TQQQ | False | 股票池 | 缺缓存，保留分母 | [] |
| I30 | US.OKLO | True | 被别的信号抢先 | 同日更早顺序开仓占用容量，见逐日明细 | [{"day": "2025-04-28", "rank": 71, "signals": 738, "morning": 11, "earlier": [], "same_held": false, "actual_same_day": false}, {"day": "2025-05-01", "rank": 93, "signals": 669, "morning": 8, "earlier": ["US.META", "US.AMZN", "US.AVGO"], "same_held": false, "actual_same_day": false}, {"day": "2025-05-06", "rank": 11, "signals": 126, "morning": 10, "earlier": ["US.HOOD"], "same_held": false, "actual_same_day": false}] |
| I31 | US.FUTU | False | 股票池 | 股票池 | [] |
| I33 | US.PL | True | 触发 | 窗口内没有可成交报价或独立尝试不足 | [] |
| I38 | US.TSLA | False | 股票池 | 股票池 | [] |
| I39 | US.AMPX | True | 被别的信号抢先 | 同日更早顺序开仓占用容量，见逐日明细 | [{"day": "2025-09-10", "rank": 50, "signals": 122, "morning": 8, "earlier": ["US.NBIS", "US.OKLO", "US.CRWV"], "same_held": false, "actual_same_day": false}, {"day": "2025-09-15", "rank": 31, "signals": 117, "morning": 7, "earlier": ["US.OPEN", "US.CRCL", "US.ALAB", "US.SOUN"], "same_held": false, "actual_same_day": false}] |
| I40 | US.ACHR | True | 被别的信号抢先 | 同日更早顺序开仓占用容量，见逐日明细 | [{"day": "2025-10-01", "rank": 12, "signals": 132, "morning": 9, "earlier": ["US.RGTI", "US.MARA"], "same_held": false, "actual_same_day": false}, {"day": "2025-10-02", "rank": 17, "signals": 153, "morning": 5, "earlier": ["US.CRWV", "US.HIMS", "US.RGTI", "US.SOUN", "US.QBTS", "US.OKLO"], "same_held": false, "actual_same_day": false}] |
| I41 | US.AMD | False | 股票池 | 股票池 | [] |
| I42 | US.ASTS | True | 被别的信号抢先 | 同日更早顺序开仓占用容量，见逐日明细 | [{"day": "2025-09-29", "rank": 7, "signals": 145, "morning": 6, "earlier": ["US.JOBY", "US.LYFT", "US.IREN", "US.SNDK", "US.RIOT"], "same_held": false, "actual_same_day": false}, {"day": "2025-10-01", "rank": 7, "signals": 132, "morning": 9, "earlier": ["US.RGTI", "US.MARA"], "same_held": false, "actual_same_day": false}] |
| O01 | US.RCAT | True | 被别的信号抢先 | 同日更早顺序开仓占用容量，见逐日明细 | [{"day": "2025-10-02", "rank": 26, "signals": 153, "morning": 5, "earlier": ["US.CRWV", "US.HIMS", "US.RGTI", "US.SOUN", "US.QBTS", "US.OKLO"], "same_held": false, "actual_same_day": false}, {"day": "2025-10-03", "rank": 27, "signals": 160, "morning": 10, "earlier": ["US.BMNR"], "same_held": false, "actual_same_day": false}] |
| S02 | US.TSLA | False | 股票池 | 股票池 | [] |
| S03 | US.LMND | True | 被别的信号抢先 | 同日更早顺序开仓占用容量，见逐日明细 | [{"day": "2025-11-26", "rank": 42, "signals": 362, "morning": 4, "earlier": ["US.SHOP", "US.GEV", "US.WDC", "US.MU", "US.SOFI", "US.MRVL", "US.APP"], "same_held": false, "actual_same_day": false}] |
| S04 | US.ONDS | True | 被别的信号抢先 | 同日更早顺序开仓占用容量，见逐日明细 | [{"day": "2025-12-03", "rank": 5, "signals": 190, "morning": 10, "earlier": ["US.BMNR"], "same_held": false, "actual_same_day": false}] |
| S07 | US.QBTS | True | 市况 | 前晚市况未放行 | [] |
| S08 | US.AEVA | True | 触发 | 窗口内没有可成交报价或独立尝试不足 | [] |
| S09 | US.AEVA | True | 触发 | 窗口内没有可成交报价或独立尝试不足 | [] |
| S10 | US.HUT | True | 市况 | 前晚市况未放行 | [] |
| S12 | US.GLXY | True | 被别的信号抢先 | 同日更早顺序开仓占用容量，见逐日明细 | [{"day": "2026-01-09", "rank": 24, "signals": 127, "morning": 2, "earlier": ["US.CRWV", "US.BMNR", "US.ASTS", "US.IREN", "US.QBTS", "US.OKLO", "US.IONQ", "US.RGTI", "US.BBAI"], "same_held": false, "actual_same_day": false}, {"day": "2026-01-13", "rank": 37, "signals": 150, "morning": 5, "earlier": ["US.OKLO", "US.QBTS", "US.IONQ", "US.BMNR", "US.MSTR", "US.WDC"], "same_held": false, "actual_same_day": false}] |
| S14 | US.SERV | False | 股票池 | 股票池 | [] |
| S15 | US.RR | True | 触发 | 窗口内没有可成交报价或独立尝试不足 | [] |
| S19 | US.PLTR | False | 股票池 | 股票池 | [] |
| V01 | US.GLXY | True | 被别的信号抢先 | 同日更早顺序开仓占用容量，见逐日明细 | [{"day": "2026-04-09", "rank": 19, "signals": 98, "morning": 9, "earlier": ["US.AXTI", "US.SNDK"], "same_held": false, "actual_same_day": false}, {"day": "2026-04-10", "rank": 37, "signals": 211, "morning": 10, "earlier": ["US.MSTR"], "same_held": false, "actual_same_day": false}] |
| V02 | US.ARM | True | 被别的信号抢先 | 同日更早顺序开仓占用容量，见逐日明细 | [{"day": "2026-04-10", "rank": 4, "signals": 211, "morning": 10, "earlier": ["US.MSTR"], "same_held": false, "actual_same_day": false}, {"day": "2026-04-14", "rank": 9, "signals": 417, "morning": 10, "earlier": ["US.MSTR"], "same_held": false, "actual_same_day": false}] |
| V03 | US.COIN | False | 买点 | 买点 | [] |
| V04 | US.NET | True | 没仓位 | 既有持仓、敞口或单票限制，见逐日明细 | [{"day": "2026-04-20", "rank": 8, "signals": 139, "morning": 11, "earlier": [], "same_held": false, "actual_same_day": false}, {"day": "2026-04-21", "rank": 8, "signals": 223, "morning": 11, "earlier": [], "same_held": false, "actual_same_day": false}, {"day": "2026-04-22", "rank": 6, "signals": 124, "morning": 11, "earlier": [], "same_held": false, "actual_same_day": false}] |
| V06 | US.MRVL | True | 没仓位 | 已持同票或一次成交已配给另一笔台账 | [{"day": "2026-04-29", "rank": 1, "signals": 83, "morning": 7, "earlier": [], "same_held": true, "actual_same_day": false}, {"day": "2026-04-30", "rank": 2, "signals": 125, "morning": 7, "earlier": ["US.LITE"], "same_held": true, "actual_same_day": false}] |
| V09 | US.QBTS | True | 被别的信号抢先 | 同日更早顺序开仓占用容量，见逐日明细 | [{"day": "2026-05-01", "rank": 15, "signals": 276, "morning": 6, "earlier": ["US.RKLB", "US.AAOI", "US.IONQ", "US.LITE", "US.MSTR"], "same_held": false, "actual_same_day": false}] |
| V12 | US.QBTS | True | 被别的信号抢先 | 同日更早顺序开仓占用容量，见逐日明细 | [{"day": "2026-05-22", "rank": 23, "signals": 435, "morning": 7, "earlier": ["US.MRVL", "US.INTC", "US.WDC", "US.STX"], "same_held": false, "actual_same_day": false}] |
| V13 | US.AMD | False | 股票池 | 股票池 | [] |
| V16 | US.INTC | False | 买点 | 独立信号尝试不足 | [] |
| V17 | US.ENPH | False | 领涨状态 | 领涨状态 | [] |
| V20 | US.TEL | False | 股票池 | 股票池 | [] |
| V21 | US.ENPH | False | 领涨状态 | 领涨状态 | [] |
| V22 | US.NET | True | 被别的信号抢先 | 同日更早顺序开仓占用容量，见逐日明细 | [{"day": "2026-06-29", "rank": 12, "signals": 290, "morning": 2, "earlier": ["US.AMAT", "US.ALAB", "US.TER", "US.NOW", "US.LRCX", "US.KLAC", "US.CRWD", "US.HOOD", "US.SNOW"], "same_held": false, "actual_same_day": false}] |
| V23 | US.QBTS | True | 被别的信号抢先 | 同日更早顺序开仓占用容量，见逐日明细 | [{"day": "2026-06-30", "rank": 22, "signals": 258, "morning": 6, "earlier": ["US.WDC", "US.NBIS", "US.MU", "US.INTC", "US.AMD"], "same_held": false, "actual_same_day": false}] |
| V25 | US.NET | True | 触发 | 窗口内没有可成交报价或独立尝试不足 | [] |
| V26 | US.BMNR | True | 被别的信号抢先 | 同日更早顺序开仓占用容量，见逐日明细 | [{"day": "2026-07-22", "rank": 19, "signals": 242, "morning": 2, "earlier": ["US.SNDK", "US.AMD", "US.INTC", "US.WDC", "US.STX", "US.NBIS", "US.IREN", "US.MPWR", "US.CRWV"], "same_held": false, "actual_same_day": false}] |
| V27 | US.BMNR | True | 被别的信号抢先 | 同日更早顺序开仓占用容量，见逐日明细 | [{"day": "2026-07-22", "rank": 19, "signals": 242, "morning": 2, "earlier": ["US.SNDK", "US.AMD", "US.INTC", "US.WDC", "US.STX", "US.NBIS", "US.IREN", "US.MPWR", "US.CRWV"], "same_held": false, "actual_same_day": false}] |
| V29 | US.NET | True | 被别的信号抢先 | 同日更早顺序开仓占用容量，见逐日明细 | [{"day": "2026-07-31", "rank": 15, "signals": 227, "morning": 1, "earlier": ["US.ORCL", "US.STX", "US.NBIS", "US.WDC", "US.BE", "US.CRWV", "US.IREN", "US.ALAB", "US.TER", "US.ANET"], "same_held": false, "actual_same_day": false}] |
| V31 | US.FTNT | False | 股票池 | 股票池 | [] |
| V32 | US.FTNT | False | 股票池 | 股票池 | [] |
| V33 | US.BMNR | True | 触发 | 窗口内没有可成交报价或独立尝试不足 | [] |
| V35 | US.AAOI | True | 被别的信号抢先 | 同日更早顺序开仓占用容量，见逐日明细 | [{"day": "2026-08-12", "rank": 17, "signals": 270, "morning": 6, "earlier": ["US.MRVL", "US.LITE", "US.INTC", "US.GEV", "US.LRCX"], "same_held": false, "actual_same_day": false}] |
| V44 | US.MSTR | True | 没仓位 | 已持同票或一次成交已配给另一笔台账 | [{"day": "2026-09-18", "rank": 2, "signals": 92, "morning": 2, "earlier": ["US.SNDK"], "same_held": false, "actual_same_day": true}] |
| V45 | US.BMNR | True | 市况 | 前晚市况未放行 | [] |
| V46 | US.PLTR | False | 股票池 | 股票池 | [] |
| V47 | US.PLTR | False | 股票池 | 股票池 | [] |
| V48 | US.TSLA | False | 股票池 | 股票池 | [] |
| V49 | US.TSLA | False | 股票池 | 股票池 | [] |
| V55 | US.USO | False | 股票池 | 缺缓存，保留分母 | [] |
| J01 | US.IONQ | True | 被别的信号抢先 | 同日更早顺序开仓占用容量，见逐日明细 | [{"day": "2025-05-08", "rank": 11, "signals": 244, "morning": 11, "earlier": [], "same_held": false, "actual_same_day": false}, {"day": "2025-05-12", "rank": 3, "signals": 163, "morning": 10, "earlier": ["US.PLTR"], "same_held": false, "actual_same_day": false}] |
