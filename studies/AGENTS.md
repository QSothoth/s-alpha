# studies：研究切片（未达生产）

> 全仓库规则见 [../AGENTS.md](../AGENTS.md)。这里都是原子能力或研究结论，不当生产能力用、不对外承诺效果。

## 在用 / 进行中

| 目录 | 内容 | 状态 |
|---|---|---|
| [daily_technical/](daily_technical/README.md) | 独立 `daily-technical-review` 技能：沪深 / 美 / 港日 K 的 Cycle、SMC、CMF/MFI 参考 | 按需只读，辅助模型和人审视介入条件，不做策略收益认证或交易 |
| [option_horizon/](option_horizon/README.md) | 独立 `option-horizon-match` 技能：按机会兑现时间匹配期权/涡轮 DTE；非收益认证、不下单 | 协作约定档，辅助选期限，不替代机会研究或日 K 买点 |
| [us_0dte_picks/](us_0dte_picks/README.md) | 近到期个股名单研究与盘中人工会话流程（v6.6 择时，只做 mock） | 方向规则全部未过（A4 在 P5 失败，TS1–TS67 失败，教训见 notes/FAILED_TRIALS.md）；只有大波动名单成立；SV1 待评测 |
| [watch_signal/](watch_signal/README.md) | 盯盘信号研究 W1–W19 | 通过的结论已进 `watch/` |
| [us_opening_range/](us_opening_range/README.md) | 仅剩 SV1 收盘采集工具 `capture.py` | 研究已结束；模块路径被定时任务引用，勿移动 |
| [auction_strength/](auction_strength/README.md) | 竞价最后一分钟强弱打分（港股 09:19、A 股 09:24） | 只有 3 天样本，门槛未校准 |

## 已结束

us_preopen_bias、us_opening_range（采集工具除外）、agent_card_eval、hk_open_scan、hk_near_expiry_flow、calendar_weekly、TS 系列：结论为负或未晋级，代码已移出仓库，结论见 [archive/README.md](archive/README.md)。

[trend_breakout/](trend_breakout/README.md)（2026-10-13 结束）：日 K 突破 / 动量 / 反投机 / 指数趋势跟随 / 节前效应共 TF1–TF14 约 40 个候选，样本外全部不成立；代码、预登记和报告保留在目录里，数据在 Release（见 [DATA](../docs/DATA.md)）。可复用的是点时股票池工具 `pit.py` 和多市场统一取数 `sources.py`。

- 每个切片自带 README（结论、数据、复现），预登记放 `notes/`，结果放 `reports/`。
- 新研究前先查 [archive](archive/README.md) 与 [FAILED_TRIALS](us_0dte_picks/notes/FAILED_TRIALS.md)，不重开已失败的机制。
- 切片升级为核心能力由用户决定：改根规范的能力地图，补该目录的 `AGENTS.md`。
