# Sam Miesse R12 预登记（2026-10-26 晚，抛物线 / 过度延伸）

- 主线 R11 G25S5R4（trader-data-v2，风险 4%）：2024 +41.2%（他约 +100%，对数差 0.35）、2025 +29.0%、回撤 39%、每年 344 笔。
- 依据：“short selling moves that you might consider parabolic … looking for hyperextensions”（00:27）。我们只看当天跳空，没看跳空前已经涨了多少；R6 在 v1 上见过只有极端延伸（跳空 ≥ 50% 且前一日 ≥ +20%）为正，但笔数太少。
- 候选（≤ 5）：RUN30 / RUN50（跳空前 5 个交易日已涨 ≥ 30% / 50%）、D220（前一日 ≥ +20%）、PRUN（每天名额按前 5 日涨幅 + 跳空排序，不减笔数）、PRUNMX3（PRUN 且每天 ≤ 3 笔）。
- 选择规则同 R6 起（`goal`；placebo / years / behav 门），50 次同池随机。
