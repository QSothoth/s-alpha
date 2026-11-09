最终遗漏按实际成交窗口对应的前晚条件归因；更早成交是实际路径证据，不是换顺序必然成交的反事实。

| ID | 股票 | 信号 | 遗漏处 | 具体条件 | 报价和实际更早成交 |
| --- | --- | --- | --- | --- | --- |
| I03 | US.GME | True | 被别的信号抢先 | 同日更早顺序开仓占用容量，见逐日明细 | [{"day": "2024-05-09", "rank": 42, "signals": 89, "morning": 7, "earlier": ["US.MARA", "US.RIVN", "US.SKYD", "US.CELH"], "same_held": false, "actual_same_day": false}, {"day": "2024-05-14", "rank": 43, "signals": 84, "morning": 8, "earlier": ["US.VRT", "US.RIVN", "US.NIO"], "same_held": false, "actual_same_day": false}] |
| I04 | US.AMC | True | 被别的信号抢先 | 同日更早顺序开仓占用容量，见逐日明细 | [{"day": "2024-05-14", "rank": 45, "signals": 84, "morning": 8, "earlier": ["US.VRT", "US.RIVN", "US.NIO"], "same_held": false, "actual_same_day": false}] |
| I05 | US.AMC | True | 被别的信号抢先 | 同日更早顺序开仓占用容量，见逐日明细 | [{"day": "2024-05-14", "rank": 45, "signals": 84, "morning": 8, "earlier": ["US.VRT", "US.RIVN", "US.NIO"], "same_held": false, "actual_same_day": false}] |
| I06 | US.SOFI | False | 买点 | 买点 | [] |
| I07 | US.COIN | True | 被别的信号抢先 | 同日更早顺序开仓占用容量，见逐日明细 | [{"day": "2024-11-07", "rank": 42, "signals": 93, "morning": 3, "earlier": ["US.VST", "US.OKLO", "US.FUTU", "US.CLSK", "US.TAL", "US.SMR", "US.XPEV", "US.LUNR"], "same_held": false, "actual_same_day": false}] |
| I08 | US.LMND | True | 市况 | 前晚市况未放行 | [] |
| I10 | US.QUBT | True | 被别的信号抢先 | 同日更早顺序开仓占用容量，见逐日明细 | [{"day": "2024-12-17", "rank": 34, "signals": 72, "morning": 5, "earlier": ["US.MARA", "US.RKLB", "US.HIMS", "US.ANF", "US.AI", "US.GME"], "same_held": false, "actual_same_day": false}, {"day": "2024-12-18", "rank": 42, "signals": 68, "morning": 7, "earlier": ["US.AFRM", "US.UPST", "US.LUNR", "US.ASTS"], "same_held": false, "actual_same_day": false}] |
| I11 | US.QUBT | True | 被别的信号抢先 | 同日更早顺序开仓占用容量，见逐日明细 | [{"day": "2024-12-17", "rank": 34, "signals": 72, "morning": 5, "earlier": ["US.MARA", "US.RKLB", "US.HIMS", "US.ANF", "US.AI", "US.GME"], "same_held": false, "actual_same_day": false}, {"day": "2024-12-18", "rank": 42, "signals": 68, "morning": 7, "earlier": ["US.AFRM", "US.UPST", "US.LUNR", "US.ASTS"], "same_held": false, "actual_same_day": false}] |
| I12 | US.SMTC | False | 领涨状态 | 领涨状态 | [] |
| I26 | US.CSIQ | True | 被别的信号抢先 | 同日更早顺序开仓占用容量，见逐日明细 | [{"day": "2025-11-28", "rank": 18, "signals": 304, "morning": 11, "earlier": [], "same_held": false, "actual_same_day": false}, {"day": "2025-12-01", "rank": 15, "signals": 164, "morning": 10, "earlier": ["US.APP"], "same_held": false, "actual_same_day": false}] |
| I27 | US.BBAI | True | 被别的信号抢先 | 同日更早顺序开仓占用容量，见逐日明细 | [{"day": "2025-01-31", "rank": 8, "signals": 98, "morning": 8, "earlier": ["US.CEG", "US.LUNR", "US.TLN"], "same_held": false, "actual_same_day": false}, {"day": "2025-02-06", "rank": 69, "signals": 123, "morning": 7, "earlier": ["US.RGTI", "US.APP", "US.IONQ", "US.SMCI"], "same_held": false, "actual_same_day": false}] |
| I28 | US.TQQQ | False | 股票池 | 缺缓存，保留分母 | [] |
| I30 | US.OKLO | True | 被别的信号抢先 | 同日更早顺序开仓占用容量，见逐日明细 | [{"day": "2025-04-28", "rank": 46, "signals": 738, "morning": 11, "earlier": [], "same_held": false, "actual_same_day": false}, {"day": "2025-05-01", "rank": 79, "signals": 669, "morning": 8, "earlier": ["US.META", "US.AVGO", "US.NVDA"], "same_held": false, "actual_same_day": false}, {"day": "2025-05-06", "rank": 10, "signals": 126, "morning": 11, "earlier": [], "same_held": false, "actual_same_day": false}] |
| I31 | US.FUTU | False | 股票池 | 股票池 | [] |
| I33 | US.PL | True | 触发 | 窗口内没有可成交报价或独立尝试不足 | [] |
| I38 | US.TSLA | False | 股票池 | 股票池 | [] |
| I39 | US.AMPX | True | 被别的信号抢先 | 同日更早顺序开仓占用容量，见逐日明细 | [{"day": "2025-09-10", "rank": 32, "signals": 122, "morning": 9, "earlier": ["US.OKLO", "US.CRWV"], "same_held": false, "actual_same_day": false}, {"day": "2025-09-15", "rank": 17, "signals": 117, "morning": 8, "earlier": ["US.SOUN", "US.RIOT", "US.NIO"], "same_held": false, "actual_same_day": false}] |
| I40 | US.ACHR | True | 被别的信号抢先 | 同日更早顺序开仓占用容量，见逐日明细 | [{"day": "2025-10-01", "rank": 7, "signals": 132, "morning": 6, "earlier": ["US.MARA", "US.JOBY", "US.CIFR", "US.ASTS", "US.QS"], "same_held": false, "actual_same_day": false}, {"day": "2025-10-02", "rank": 14, "signals": 153, "morning": 4, "earlier": ["US.CRWV", "US.CLS", "US.HIMS", "US.RGTI", "US.SOUN", "US.QBTS", "US.OKLO"], "same_held": false, "actual_same_day": false}] |
| I41 | US.AMD | False | 股票池 | 股票池 | [] |
| O01 | US.RCAT | True | 被别的信号抢先 | 同日更早顺序开仓占用容量，见逐日明细 | [{"day": "2025-10-02", "rank": 23, "signals": 153, "morning": 4, "earlier": ["US.CRWV", "US.CLS", "US.HIMS", "US.RGTI", "US.SOUN", "US.QBTS", "US.OKLO"], "same_held": false, "actual_same_day": false}, {"day": "2025-10-03", "rank": 22, "signals": 160, "morning": 9, "earlier": ["US.BMNR", "US.IONQ"], "same_held": false, "actual_same_day": false}] |
| S02 | US.TSLA | False | 股票池 | 股票池 | [] |
| S03 | US.LMND | True | 被别的信号抢先 | 同日更早顺序开仓占用容量，见逐日明细 | [{"day": "2025-11-26", "rank": 25, "signals": 362, "morning": 6, "earlier": ["US.SHOP", "US.WDC", "US.STX", "US.MU", "US.SOFI"], "same_held": false, "actual_same_day": false}] |
| S04 | US.ONDS | True | 被别的信号抢先 | 同日更早顺序开仓占用容量，见逐日明细 | [{"day": "2025-12-03", "rank": 4, "signals": 190, "morning": 10, "earlier": ["US.HOOD"], "same_held": false, "actual_same_day": false}] |
| S07 | US.QBTS | True | 市况 | 前晚市况未放行 | [] |
| S08 | US.AEVA | True | 触发 | 窗口内没有可成交报价或独立尝试不足 | [] |
| S09 | US.AEVA | True | 触发 | 窗口内没有可成交报价或独立尝试不足 | [] |
| S10 | US.HUT | True | 市况 | 前晚市况未放行 | [] |
| S11 | US.RKLB | True | 被别的信号抢先 | 同日更早顺序开仓占用容量，见逐日明细 | [{"day": "2026-01-06", "rank": 35, "signals": 106, "morning": 2, "earlier": ["US.IONQ", "US.OKLO", "US.SMR", "US.AG", "US.CDE", "US.CLSK", "US.UPST", "US.HL", "US.EOSE"], "same_held": false, "actual_same_day": false}, {"day": "2026-01-08", "rank": 37, "signals": 93, "morning": 6, "earlier": ["US.IREN", "US.RIVN", "US.CLS", "US.CDE", "US.ECHO"], "same_held": false, "actual_same_day": false}] |
| S12 | US.GLXY | True | 被别的信号抢先 | 同日更早顺序开仓占用容量，见逐日明细 | [{"day": "2026-01-09", "rank": 19, "signals": 127, "morning": 4, "earlier": ["US.ASTS", "US.IREN", "US.QBTS", "US.OKLO", "US.IONQ", "US.RGTI", "US.BBAI"], "same_held": false, "actual_same_day": false}, {"day": "2026-01-13", "rank": 25, "signals": 150, "morning": 5, "earlier": ["US.OKLO", "US.QBTS", "US.IONQ", "US.RGTI", "US.CRDO", "US.ALAB"], "same_held": false, "actual_same_day": false}] |
| S14 | US.SERV | False | 股票池 | 股票池 | [] |
| S15 | US.RR | True | 触发 | 窗口内没有可成交报价或独立尝试不足 | [] |
| S19 | US.PLTR | False | 股票池 | 股票池 | [] |
| V01 | US.GLXY | True | 被别的信号抢先 | 同日更早顺序开仓占用容量，见逐日明细 | [{"day": "2026-04-09", "rank": 58, "signals": 98, "morning": 10, "earlier": ["US.SNDK"], "same_held": false, "actual_same_day": false}, {"day": "2026-04-10", "rank": 21, "signals": 211, "morning": 10, "earlier": ["US.ARM"], "same_held": false, "actual_same_day": false}] |
| V03 | US.COIN | False | 买点 | 买点 | [] |
| V04 | US.NET | True | 没仓位 | 既有持仓、敞口或单票限制，见逐日明细 | [{"day": "2026-04-20", "rank": 4, "signals": 139, "morning": 11, "earlier": [], "same_held": false, "actual_same_day": false}, {"day": "2026-04-21", "rank": 7, "signals": 223, "morning": 11, "earlier": [], "same_held": false, "actual_same_day": false}, {"day": "2026-04-22", "rank": 4, "signals": 124, "morning": 11, "earlier": [], "same_held": false, "actual_same_day": false}] |
| V06 | US.MRVL | True | 没仓位 | 已持同票或一次成交已配给另一笔台账 | [{"day": "2026-04-29", "rank": 42, "signals": 83, "morning": 6, "earlier": ["US.BE", "US.CVNA", "US.DOCN", "US.TTMI", "US.TTD"], "same_held": true, "actual_same_day": false}, {"day": "2026-04-30", "rank": 48, "signals": 125, "morning": 6, "earlier": ["US.LITE", "US.CRWV", "US.AAOI", "US.CRDO", "US.CVNA"], "same_held": true, "actual_same_day": false}] |
| V09 | US.QBTS | True | 被别的信号抢先 | 同日更早顺序开仓占用容量，见逐日明细 | [{"day": "2026-05-01", "rank": 11, "signals": 276, "morning": 5, "earlier": ["US.RKLB", "US.AAOI", "US.IONQ", "US.LITE", "US.CIEN", "US.MSTR"], "same_held": false, "actual_same_day": false}] |
| V12 | US.QBTS | True | 被别的信号抢先 | 同日更早顺序开仓占用容量，见逐日明细 | [{"day": "2026-05-22", "rank": 202, "signals": 435, "morning": 7, "earlier": ["US.IREN", "US.INTC", "US.WDC", "US.STX"], "same_held": false, "actual_same_day": false}] |
| V13 | US.AMD | False | 股票池 | 股票池 | [] |
| V16 | US.INTC | False | 买点 | 独立信号尝试不足 | [] |
| V17 | US.ENPH | False | 领涨状态 | 领涨状态 | [] |
| V20 | US.TEL | False | 股票池 | 股票池 | [] |
| V21 | US.ENPH | False | 领涨状态 | 领涨状态 | [] |
| V22 | US.NET | True | 被别的信号抢先 | 同日更早顺序开仓占用容量，见逐日明细 | [{"day": "2026-06-29", "rank": 10, "signals": 290, "morning": 3, "earlier": ["US.ALAB", "US.TER", "US.SOFI", "US.LRCX", "US.KLAC", "US.CRWD", "US.HOOD", "US.SNOW"], "same_held": false, "actual_same_day": false}] |
| V23 | US.QBTS | True | 被别的信号抢先 | 同日更早顺序开仓占用容量，见逐日明细 | [{"day": "2026-06-30", "rank": 85, "signals": 258, "morning": 7, "earlier": ["US.WDC", "US.MU", "US.INTC", "US.AMD"], "same_held": false, "actual_same_day": false}] |
| V25 | US.NET | True | 触发 | 窗口内没有可成交报价或独立尝试不足 | [] |
| V27 | US.BMNR | True | 没仓位 | 已持同票或一次成交已配给另一笔台账 | [{"day": "2026-07-22", "rank": 9, "signals": 242, "morning": 2, "earlier": ["US.AMD", "US.STX", "US.NBIS", "US.MPWR", "US.CBRS", "US.RIVN", "US.CIFR", "US.HPE"], "same_held": false, "actual_same_day": true}] |
| V31 | US.FTNT | False | 股票池 | 股票池 | [] |
| V32 | US.FTNT | False | 股票池 | 股票池 | [] |
| V33 | US.BMNR | True | 触发 | 窗口内没有可成交报价或独立尝试不足 | [] |
| V35 | US.AAOI | True | 被别的信号抢先 | 同日更早顺序开仓占用容量，见逐日明细 | [{"day": "2026-08-12", "rank": 12, "signals": 270, "morning": 6, "earlier": ["US.MRVL", "US.LITE", "US.GLW", "US.GEV", "US.DELL"], "same_held": false, "actual_same_day": false}] |
| V44 | US.MSTR | True | 没仓位 | 已持同票或一次成交已配给另一笔台账 | [{"day": "2026-09-18", "rank": 2, "signals": 92, "morning": 3, "earlier": ["US.SNDK"], "same_held": false, "actual_same_day": true}] |
| V45 | US.BMNR | True | 市况 | 前晚市况未放行 | [] |
| V46 | US.PLTR | False | 股票池 | 股票池 | [] |
| V47 | US.PLTR | False | 股票池 | 股票池 | [] |
| V48 | US.TSLA | False | 股票池 | 股票池 | [] |
| V49 | US.TSLA | False | 股票池 | 股票池 | [] |
| V55 | US.USO | False | 股票池 | 缺缓存，保留分母 | [] |
| J01 | US.IONQ | True | 被别的信号抢先 | 同日更早顺序开仓占用容量，见逐日明细 | [{"day": "2025-05-08", "rank": 10, "signals": 244, "morning": 11, "earlier": [], "same_held": false, "actual_same_day": false}, {"day": "2025-05-12", "rank": 2, "signals": 163, "morning": 10, "earlier": ["US.PLTR"], "same_held": false, "actual_same_day": false}] |
