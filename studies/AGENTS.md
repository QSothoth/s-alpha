# studies：研究切片（未达生产）

> 全仓库规则见 [../AGENTS.md](../AGENTS.md)。这里都是原子能力或研究结论，不当生产能力用、不对外承诺效果。

| 目录 | 内容 | 状态 |
|---|---|---|
| [us_0dte_picks/](us_0dte_picks/README.md) | 近到期个股名单研究与盘中人工会话流程（v6.6 择时，只做 mock） | 方向规则全部未过（A4 在 P5 失败，TS1–TS67 失败，教训见 notes/FAILED_TRIALS.md）；只有大波动名单成立；SV1 待评测 |
| [us_opening_range/](us_opening_range/README.md) | 当前美股 0DTE 上游研究：日K位置、盘前观察／早盘突破提示；旧OR交易回放保留 | DS1/DS2/AH1未晋级；RG1局部raw正但整体未过；OM1仅7次真实0DTE桥接提示，不认证期权净收益；扫描仅观察，九ETF分钟及09/25仍未评测 |
| [agent_card_eval/](agent_card_eval/README.md) | agent 审择时卡片（接受/拒绝）是否提高收益 | A1、A2 均未通过：Codex 不知收益结构时砍掉赢单，知道后几乎全接受，打分无信息；审卡暂不应否决信号 |
| [auction_strength/](auction_strength/README.md) | 竞价最后一分钟强弱打分（港股 09:19、A 股 09:24） | 只有 3 天样本，门槛未校准 |
| [hk_open_scan/](hk_open_scan/README.md) | 港股通全市场竞价时点 / 09:45 排序 | 结论为负（追涨负期望） |
| [hk_near_expiry_flow/](hk_near_expiry_flow/README.md) | 港股正股期权近月异动扫描 | 结论为负（R1–R3 全部不达标） |
| [watch_signal/](watch_signal/README.md) | 盯盘信号研究 W1–W19 | 通过的结论已进 `watch/` |
| [archive/](archive/README.md) | 已停止的研究：us_preopen_bias S1–S29、calendar_weekly 易学预测 | 只留结论 |
| [archive/us_preopen_bias/](archive/us_preopen_bias/README.md) | 美股日内选股：每日多空名单（给日内期权策略选标的） | S22原验证段ATR标准化幅度比1.25–1.32x，旧口径审计复现一致；非方向或0DTE净收益证据。S24–S27多空篮子扣成本未成立；S28开盘15m版失败 |

- 每个切片自带 README（结论、数据、复现），预登记放 `notes/`，结果放 `reports/`。
- 切片升级为核心能力由用户决定：改根规范的能力地图，补该目录的 `AGENTS.md`。
