 — systematic micro/nanocap intraday short

### Source and boundaries

B, TraderLion episode description dated 2026-02-28 [distribution page](https://getpodcast.com/podcast/the-traderlion-podcast/382-return-in-1-year-why-most-traders-fail-at-shorting-from-a-trading-_2f20d63a88), checked 2026-10-17. Describes systematic short-only championship style, overextension, dilution, volume/liquidity transitions, Excel research, compounding and serious halt/overnight risks. Chapters locate statistics 23:07, sizing 27:43, locates 48:21, entry context 1:05:53, wide stops 1:11:32, halts 1:20:09. 238 trades and 66% winning is published description, not audited trades. The same episode covers SPX options; do not assert he never trades options or merge options into the stock sample. [Original video](https://www.youtube.com/watch?v=bRXO6F_vGjM) fetch failed here; chapter headings are not a full transcript.

### Study interfaces and data

build_overextension_events; attach_sec_filings_asof (original accepted timestamp and public availability, form type, offering status, no future completed-offering label); measure_liquidity_transition (spread/depth/turnover separately); attach_borrow_asof; generate_candidate_signal; simulate_short_orders; stress_halt_recall; attribute_costs.

Borrow record must carry broker, timestamp, shares available, locate reservation/expiry, locate fee, annualized borrow rate and accrual convention, short-sale restriction status, rejection/recall/buy-in events. Live availability today cannot replace history. Execution needs bid/ask, quote depth or bounded impact model, trade prints, LULD/T12 and reopening data, corporate actions, dividend liability, and overnight inventory. Missing borrow => E1 event study only, not reported realizable short returns.

H-TR-EVENT-01 (non-trading): enumerate first completed 5m close >=30% above prior close with cumulative dollar volume >=$2m; retain all historical eligible symbols; at that time freeze event. Report subsequent 5/15/60-minute and next-session distributions, maximum adverse excursion, halt and missing-price rates. Threshold is H, not Ty's. Compare event-only vs events with already-public financing evidence. Borrow strata: confirmed available / unavailable / unknown. Do not impute unknown as borrowable.

Do not force a VWAP-break strategy into his name. No authenticated entry threshold, stop width, partial schedule, final close rule or account-risk formula was obtained. A trading simulator stays blocked until those are either sourced or separately approved as explicitly independent hypotheses. A wide historical adverse-move quantile is a stress statistic, never a guaranteed maximum loss. Stop fills cannot cap an unbounded squeeze or long halt.

