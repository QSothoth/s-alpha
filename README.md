# s-alpha

多市场交易执行与只读研究仓库。当前研究聚焦有当天到期期权的标的：日 K 找关键位置，盘前观察，开盘 15 / 20 / 30 分钟确认突破提示。只提供上游观察信号，不负责从找信号到购买、持有、退出的全过程；与现有交易执行分开管理。

| 入口 | 内容 |
|---|---|
| [每日 0DTE 选标的](studies/us_0dte_picks/README.md) | 周一三五个股研究：财报／放量宽幅次日的大动信号保留；A4 方向规则在 P5 新截面失败，尚无稳定方向能力；名单工具仅作研究观察，见 `notes/FAILED_TRIALS.md` |
| [日 K／早盘信号研究](studies/us_opening_range/README.md) | 日线位置与早盘突破观察（DS / OR 各轮未晋级） |
| [custody](custody/AGENTS.md) | 既有美股 0DTE 单笔执行：上游给定标的、方向和合约，按当日正股 1m K 线择时，按期权成交价计盈亏 |
| [watch](watch/README.md) | A / H 股实时盯盘，只读行情与标注 |
| [其他研究](studies/AGENTS.md) | 竞价、港股开盘与期权异动等研究切片 |
| [历史归档](studies/archive/README.md) | S1–S29 现存代码、预登记与失败结果，停止作为当前方向推荐入口 |

`custody` 是唯一会下单的部分。默认策略仍为 `zero_dte_timing_v6.6`（`candidate`）；现有注册表中 `zero_dte_timing_v6.5` 与 `open_hold_v3` 为 `accepted`。`run --mode live` 只接受 `accepted`，因此默认策略不能直接用于实盘；状态以 [注册表](custody/strategies/index.json) 为准。注册状态不等于研究通过，已提交报告没有评测结论 ACCEPT。历史策略与报告保留原位，供运行依赖、对照及审计使用。

数据尽量沿用 OpenD、Yahoo 与腾讯；真实到期日、期权合约及期权成交资料以可核验的行情源为准。只用真实行情，数据不进 Git，已发布数据按 tag 与 SHA256 固定；不因新研究自动启动长期采集或消耗新标的历史 K 线额度。4GB VPS 上按标的 / 日期分块处理，避免无界加载。

项目规范见 [AGENTS.md](AGENTS.md)。数据与 Release 见 [DATA](docs/DATA.md)，执行命令见 [RUNTIME](docs/RUNTIME.md)，评测口径见 [STANDARD](docs/STANDARD.md)，历史策略研究见 [STRATEGY](docs/STRATEGY.md)，OpenD 环境见 [OPEND_SETUP](docs/OPEND_SETUP.md)。

```bash
# 查看现有策略；不连接交易账户
python3 -m custody strategies

# 检查已下载的真实期权数据
python3 -m custody check --dataset data/custody-0dte-v6.1

# 修改哪里测哪里；custody 测试每次都跑
python3 -m unittest discover -s custody/tests
python3 watch/test_watch.py
python3 -m unittest discover -s studies/auction_strength/tests
python3 -m unittest discover -s studies/hk_open_scan/tests
python3 -m unittest discover -s studies/archive/us_preopen_bias/tests
python3 -m unittest discover -s studies/us_opening_range/tests
python3 -m unittest discover -s studies/us_0dte_picks/tests
```

行情与策略研究入口不下单；只有 `custody/broker.py` 可使用 OpenD 交易接口。密码、令牌、运行数据库不提交。

代码采用 MIT 许可；Release 行情小样本用于个人研究和离线复现。
