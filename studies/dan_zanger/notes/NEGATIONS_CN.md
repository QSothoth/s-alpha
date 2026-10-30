# Dan Zanger 否定登记表

每个没被带入的候选一行（自动写入）；“当时的配置”一列是那一轮的基础配置报告。下游大改后，用 `negations` 动作列出依赖旧配置的行，在新配置上重测。

| 轮次 | 环节 | 候选 | 改了什么 | 当时的配置 | 带入 | 否定依据 | 状态 |
|---|---|---|---|---|---|---|---|
| R1 | end-to-end draft: stop / volume / exit / leaders / market | FAILPASS | `{"rule_opts": {"feedback": 3, "risk_low": 0.004}}` | :base | LEAD | gates: placebo；全区间 -9%（带入 +5%） | open |
| R1 | end-to-end draft: stop / volume / exit / leaders / market | NOSLEEP | `{"rule_opts": {"exit_signal": "zexit0"}}` | :base | LEAD | gates: placebo；全区间 -37%（带入 +5%） | open |
| R1 | end-to-end draft: stop / volume / exit / leaders / market | PIVOT3 | `{"stop": "pivot", "stop_pct": 0.03}` | :base | LEAD | gates: placebo；全区间 -16%（带入 +5%） | open |
| R1 | end-to-end draft: stop / volume / exit / leaders / market | VOL15 | `{"base": {"vol": 1.5}}` | :base | LEAD | gates: placebo；全区间 -45%（带入 +5%） | open |
| R2 | stock selection | BASE15 | `{"base": {"days": 15}}` | r1.json:chosen | BASE25 | gates: placebo；全区间 -15%（带入 +17%） | open |
| R2 | stock selection | NEARHI | `{"near_high": 0.15}` | r1.json:chosen | BASE25 | objective below BASE25；全区间 +9%（带入 +17%） | open |
| R2 | stock selection | PRICE50 | `{"pool": {"price": 50.0}}` | r1.json:chosen | BASE25 | gates: placebo；全区间 -13%（带入 +17%） | open |
| R2 | stock selection | RS90 | `{"strength": "rs90"}` | r1.json:chosen | BASE25 | objective below BASE25；全区间 -1%（带入 +17%） | open |
| R3 | holding: exits, trims, adds | NFT0 | `{"rule_opts": {"nft_days": 0}}` | r2.json:chosen | ADD2 | gates: placebo；全区间 -5%（带入 +22%） | open |
| R3 | holding: exits, trims, adds | REV | `{"rule_opts": {"exit_signal": "zrev5"}}` | r2.json:chosen | ADD2 | objective below ADD2；全区间 +20%（带入 +22%） | open |
| R3 | holding: exits, trims, adds | SLEEP10 | `{"rule_opts": {"exit_signal": "zexit10"}}` | r2.json:chosen | ADD2 | gates: placebo；全区间 -12%（带入 +22%） | open |
| R3 | holding: exits, trims, adds | TRIM20 | `{"rule_opts": {"trims": [4], "trim_frac": 0.3}}` | r2.json:chosen | ADD2 | objective below ADD2；全区间 +18%（带入 +22%） | open |
| R4 | entry / stop / setups (directions from earlier traders) | ADDSIG | `{"rule_opts": {"add_signal": "sig_all", "add_signal_frac": 0.5, "add_signal_profit": true}}` | r3.json:chosen | EP | objective below EP；全区间 +20%（带入 -6%） | open |
| R4 | entry / stop / setups (directions from earlier traders) | ADR3 | `{"pool": {"adr": 3.0}}` | r3.json:chosen | EP | objective below EP；全区间 +9%（带入 -6%） | open |
| R4 | entry / stop / setups (directions from earlier traders) | IDX50 | `{"filter": "IDX50"}` | r3.json:chosen | EP | objective below EP；全区间 +26%（带入 -6%） | open |
| R4 | entry / stop / setups (directions from earlier traders) | STOPLOW | `{"stop": "low", "stop_cap": 0.05}` | r3.json:chosen | EP | objective below EP；全区间 +14%（带入 -6%） | open |
| R5 | holding: trendline, trims, EP slot (directions from earlier traders) | EMA21 | `{"rule_opts": {"trail": "ema21", "arm_trail_on_entry": true, "exit_signal": "zsleep5"}}` | r3.json:chosen | EMA10 | objective below EMA10；全区间 +26%（带入 +27%） | open |
| R5 | holding: trendline, trims, EP slot (directions from earlier traders) | EPSLOT | `{"setups": ["zbase", "ep"], "ep": {"rvol": 3.0}, "rule_opts": {"max_open_by_kind": {"ep": 1}}}` | r3.json:chosen | EMA10 | gates: total, dd+0.05；全区间 +10%（带入 +27%） | open |
| R5 | holding: trendline, trims, EP slot (directions from earlier traders) | REV | `{"rule_opts": {"exit_signal": "zrev5"}}` | r3.json:chosen | EMA10 | objective below EMA10；全区间 +27%（带入 +27%） | open |
| R5 | holding: trendline, trims, EP slot (directions from earlier traders) | TRIM2 | `{"rule_opts": {"trims": [3, 6], "trim_frac": 0.25}}` | r3.json:chosen | EMA10 | objective below EMA10；全区间 +27%（带入 +27%） | open |
| R6 | holding: the 5-day asleep exit (binding in R5) | NOSLEEP | `{"rule_opts": {"exit_signal": ""}}` | r5.json:chosen | EMA10 | gates: total, dd+0.05；全区间 +1%（带入 +27%） | open |
| R6 | holding: the 5-day asleep exit (binding in R5) | SLEEP10 | `{"rule_opts": {"exit_signal": "zsleep10"}}` | r5.json:chosen | EMA10 | gates: total, dd+0.05；全区间 +8%（带入 +27%） | open |
| R6 | holding: the 5-day asleep exit (binding in R5) | SLEEP10EP | `{"rule_opts": {"exit_signal": "zsleep10", "max_open_by_kind": {"ep": 1}}, "setups": ["zbase", "ep"], "ep": {"rvol": 3.0}}` | r5.json:chosen | EMA10 | gates: total, dd+0.05；全区间 -4%（带入 +27%） | open |
| R7 | paired: tight stop x slow exit (payoff structure) | LOW_EMA21 | `{"stop": "low", "stop_cap": 0.05, "rule_opts": {"trail": "ema21", "exit_signal": ""}}` | r5.json:chosen | EMA10 | gates: placebo, total, dd+0.05；全区间 -14%（带入 +27%） | open |
| R7 | paired: tight stop x slow exit (payoff structure) | LOW_SLEEP20 | `{"stop": "low", "stop_cap": 0.05, "rule_opts": {"trail": "ema21", "exit_signal": "zsleep20"}}` | r5.json:chosen | EMA10 | gates: placebo, total, dd+0.05；全区间 -14%（带入 +27%） | open |
| R7 | paired: tight stop x slow exit (payoff structure) | LOW_SMA50 | `{"stop": "low", "stop_cap": 0.05, "rule_opts": {"trail": "sma50", "exit_signal": ""}}` | r5.json:chosen | EMA10 | gates: dd+0.05；全区间 +78%（带入 +27%） | open |
| R7 | paired: tight stop x slow exit (payoff structure) | SMA50 | `{"rule_opts": {"trail": "sma50", "exit_signal": ""}}` | r5.json:chosen | EMA10 | gates: dd+0.05；全区间 +83%（带入 +27%） | open |
| R8 | payoff structure on SMA50: tight stop, breakeven, trims, split exit, pyramiding | ADDTWO | `{"rule_opts": {"add_levels": [2, 4], "add_frac": 0.5}}` | r7.json:SMA50 | NOTRIM | objective below NOTRIM；全区间 +93%（带入 +99%） | open |
| R8 | payoff structure on SMA50: tight stop, breakeven, trims, split exit, pyramiding | BE2 | `{"rule_opts": {"breakeven_r": 2.0}}` | r7.json:SMA50 | NOTRIM | objective below NOTRIM；全区间 +84%（带入 +99%） | open |
| R8 | payoff structure on SMA50: tight stop, breakeven, trims, split exit, pyramiding | LOW3 | `{"stop": "low", "stop_cap": 0.03}` | r7.json:SMA50 | NOTRIM | objective below NOTRIM；全区间 +93%（带入 +99%） | open |
| R8 | payoff structure on SMA50: tight stop, breakeven, trims, split exit, pyramiding | SPLIT | `{"rule_opts": {"trail": "ema10", "trail_after_trim": "sma50"}}` | r7.json:SMA50 | NOTRIM | gates: total；全区间 +21%（带入 +99%） | open |
| R9 | pairs of R8 changes | N_ADDTWO | `{"rule_opts": {"add_levels": [2, 4], "add_frac": 0.5}}` | r8.json:chosen | NOTRIM | gates: total；全区间 +95%（带入 +99%） | open |
| R9 | pairs of R8 changes | N_LOW3 | `{"stop": "low", "stop_cap": 0.03}` | r8.json:chosen | NOTRIM | objective below NOTRIM；全区间 +112%（带入 +99%） | open |
| R9 | pairs of R8 changes | N_LOW3_ADDTWO | `{"stop": "low", "stop_cap": 0.03, "rule_opts": {"add_levels": [2, 4], "add_frac": 0.5}}` | r8.json:chosen | NOTRIM | objective below NOTRIM；全区间 +112%（带入 +99%） | open |
| R9 | pairs of R8 changes | N_LOW5 | `{"stop": "low", "stop_cap": 0.05}` | r8.json:chosen | NOTRIM | objective below NOTRIM；全区间 +103%（带入 +99%） | open |
