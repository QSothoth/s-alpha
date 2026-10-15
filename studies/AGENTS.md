# studies：研究切片（未达生产）

> 全仓库规则见 [../AGENTS.md](../AGENTS.md)。这里都是原子能力或研究结论，不当生产能力用、不对外承诺效果。

用户任务从顶层 [skill 入口](../README.md) 进入。使用说明和操作流程随 skill 放在 `skills/<名称>/references/`；这里保留实现、预登记、结果与失败经验，不再嵌套维护 `skills/`。

## 在用 / 进行中

| 目录 | 内容 | 状态 |
|---|---|---|
| [daily_technical/](daily_technical/README.md) | `daily-technical-review` 实现：沪深 / 美 / 港日 K 的 Cycle、SMC、CMF/MFI 参考 | 按需只读，辅助模型和人审视介入条件，不做策略收益认证或交易 |
| [us_0dte_picks/](us_0dte_picks/README.md) | 近到期个股名单研究与盘中人工会话流程（v6.6 择时，只做 mock） | 方向规则全部未过（A4 在 P5 失败，TS1–TS67 失败，教训见 notes/FAILED_TRIALS.md）；只有大波动名单成立；SV1 待评测 |
| [watch_signal/](watch_signal/README.md) | 盯盘信号研究 W1–W33 | 通过的结论已进 `watch/`（价位闸、`D±`、余下振幅 `left`、强度档）；1m 方向与收益始终不稳定（W22–W24、W28、W29、W32 失败）；2024H1 是最后一段未用分钟数据 |
| [us_opening_range/](us_opening_range/README.md) | 仅剩 SV1 收盘采集工具 `capture.py` | 研究已结束；模块路径被定时任务引用，勿移动 |
| [auction_strength/](auction_strength/README.md) | 竞价最后一分钟强弱打分（港股 09:19、A 股 09:24） | 只有 3 天样本，门槛未校准 |
| [trend_breakout/](trend_breakout/README.md) | 日 K / 周 K 趋势研究（2026-10-12～15，已收敛） | 三个市场各有最终方案（A 股、美股长持，港股波段），区间内检验通过，但均为同一段历史上的择优、非样本外；不用于实盘。结论与经验见 reports/CONCLUSIONS_CN.md，历史文件已移出仓库；`trend-market-scan` 技能按最终方案做全市场周扫描（只列规则状态） |

## 已结束

us_preopen_bias、us_opening_range（采集工具除外）、agent_card_eval、hk_open_scan、hk_near_expiry_flow、calendar_weekly、TS 系列：结论为负或未晋级，代码已移出仓库，结论见 [archive/README.md](archive/README.md)。

[trend_breakout/](trend_breakout/README.md) 的历史各轮（TF1–TF14、PB1–PB31）已于 2026-10-15 收敛：结论与经验保留在 `trend_breakout/reports/CONCLUSIONS_CN.md`，原文件移到仓库外 `/root/opend-us-options-archive-20261015/`。数据在 Release（见 [DATA](../docs/DATA.md)）。

- 每个切片自带 README（结论、数据、复现），预登记放 `notes/`，结果放 `reports/`。
- 新研究前先查 [archive](archive/README.md) 与 [FAILED_TRIALS](us_0dte_picks/notes/FAILED_TRIALS.md)，不重开已失败的机制。
- 切片升级为核心能力由用户决定：更新根规范的 skill 入口与实现归属，补该目录的 `AGENTS.md`。
