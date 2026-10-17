# 进度（中断后从这里恢复）

目标：用户 2026-10-16 晚要求在现有数据上复刻 Martin Luk 的超额收益（/goal）。

- [x] 资料调研：规则汇总在 PREREG_R1.md，出处在 SOURCES.md；他 2025 月度路径：3 月 +46%、4 月 +70%、5 月 +178%、6 月 +184%、7 月 +245%、8 月 +260%、9 月 +581%、10 月 +842%、11 月 +1358%、12 月 +970%
- [x] R1 日 K 近似：未通过（reports/R1_RESULTS_CN.md）
- [x] R2 5 分钟盘中规则：I3 验证未通过（reports/R2_RESULTS_CN.md）
- [x] R3 预登记（PREREG_R3.md）+ 实现（intraday.py 的 J1–J5、confirm_close 因果入场）
  - 全区间 2024-01 → 2026-09：J4 +350%（年化 74%）；因果入场 J4 +207%（年化 51%），胜率 17.6%、平均赚 +13.3% / 亏 −2.0%、盈亏比 6.7、304 笔/年（他 22%、+14.1% / −2.1%、6.8、930 笔/年）
  - 顶部交易 IREN/RGTI/BE/SNDK/ASTS（2025-09～10）、RKLB（2024-11）等，时点与价格已人工核对
- [x] R4（PREREG_R4.md）：港股 5 分钟 J4 −27%/−25%（持有 +25.6%）；日 K 收盘确认 D4 美 −40.6%、港 +38.1%、A +52.0%，均低于持有 → 未通过（reports/R4_RESULTS_CN.md）
- [x] 敏感性（只报告）：J4 风险 1% + 280% 曝险 +439%；J4 2025 月度形状与他相似（5–7 月、9–10 月涨，11–12 月回吐），幅度 +81% vs +970%
- [x] R5 空头（PREREG_R5.md）：空头期望 −0.19～−0.42R，加入后拖累多头 → 未通过（reports/R5_RESULTS_CN.md；名单事后挑选对空头不利）
- [x] 对照他公开的交易：抓到 SMCI 2024-01 EP、COIN 2024-11 EP、GME 2024-05 底；漏 GME 2024-05-13（ADR 止损上限）、SOFI（ADR<5%）
- [x] R6 预登记（PREREG_R6.md）：EP 止损上限 5%、ADR 门槛 4%；全区间 L3 +455%（年化 88%）、L4 因果 +183%、L5（1% 风险 280%）+704%（2024 +146%、2025 +133%）（reports/r6_full.json）
- [x] R6 区间内检验：L3 5/5 通过（+455%）；L4 收盘确认 4/5（+183%，去掉前 10 笔转负）（reports/R6_RESULTS_CN.md）
- 注意：2026-10-16 12:39 EDT 机器被外部强制关机（日志无 OOM / 内核错误、无关机流程），之前两核满载近 2 小时；之后重计算一律单进程 + nice，不同时跑两个重任务
- [x] R3 区间内检验：J4（越过即买）5/5 通过；J4 因果版 4/5（去掉前 10 笔转负）；1 分钟重建 82 笔显示 5 分钟模型几乎无乐观偏差（reports/R3_RESULTS_CN.md）
- [x] 最终报告 reports/FINAL_CN.md；研究完成，未提交 git（等用户决定）
- 单测：`/opt/futu-opend/venv/bin/python -m unittest studies.martin_luk.tests.test_luk studies.martin_luk.tests.test_intraday`
- [x] 量级对账（scale.py）：L5 单笔优势 × 930 笔 → 2024 +1043%、2025 +914%（他 +970%）、两年 +5121%（他 +3998%）；计入容量拖累约 +225%/年；2026 对不上
- [x] 2026 缺口诊断：他 2026-07 约 +86% 而 QQQ −6.6%、L3 −3.9% → 主要来自空头；我们的空头按大盘状态拆开都为负（−0.48R/−0.34R），名单偏差使现有数据无法检验。要跑他真实的量级和空头，需要全市场（含后来冷掉/退市股）5 分钟数据，属于新数据，等用户决定
- [x] R7（PREREG_R7.md）：108 只新股票 30 分钟 2026-06 → 09，多头 −20%/−21%、空头 −11%（7 月 +17%）→ 未通过（reports/R7_RESULTS_CN.md）。现有本地数据已用尽
- [ ] R8（用户 2026-10-17 同意拉数据，注意磁盘）：PREREG_R8.md；fetch_r8.py 三步
  1. `nice -n 19 ... -m studies.martin_luk.fetch_r8 daily` → data/martin-luk-universe-us/us（免费日 K，可续传）
  2. `... fetch_r8 sample` → data/martin-luk-k5-r8/sample.json（种子 20261017 随机 200 只）
  3. `... fetch_r8 k5` → data/martin-luk-k5-r8/*.csv.gz（扣额度，可续传，留 80 给 custody）
  4. 之后：intraday 加载新名单，按 PREREG_R8 跑 A（新 200 只）与 B（284 只）
