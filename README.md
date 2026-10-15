# s-alpha

美股期权日内执行（custody）、港股 / A 股 / 美股盯盘（watch）与只读研究（studies）。

| 入口 | 内容 |
|---|---|
| [custody](custody/AGENTS.md) | 美股近到期期权单笔执行：上游给定标的、方向和合约，按当日正股 1m K 线择时，按期权成交价计盈亏；唯一会下单的部分 |
| [watch](watch/README.md) | A / H 股实时盯盘，只读行情与标注 |
| [近到期选标的与盘中会话](studies/us_0dte_picks/README.md) | 当前在用的上游：人工选候选 + v6.6 择时，只做 mock。方向规则全部失败，只有大波动名单成立；教训见 `notes/FAILED_TRIALS.md` |
| [其他研究](studies/AGENTS.md) | 竞价、盯盘信号，以及已失败、只供查阅的切片 |

`custody` 是唯一会下单的部分。默认策略仍为 `zero_dte_timing_v6.6`（`candidate`）；现有注册表中 `zero_dte_timing_v6.5` 与 `open_hold_v3` 为 `accepted`。`run --mode live` 只接受 `accepted`，因此默认策略不能直接用于实盘；状态以 [注册表](custody/strategies/index.json) 为准。注册状态不等于研究通过，已提交报告没有评测结论 ACCEPT。历史策略与报告保留原位，供运行依赖、对照及审计使用。

数据尽量沿用 OpenD、Yahoo 与腾讯；真实到期日、期权合约及期权成交资料以可核验的行情源为准。只用真实行情，数据不进 Git，已发布数据按 tag 与 SHA256 固定；不因新研究自动启动长期采集或消耗新标的历史 K 线额度。4GB VPS 上按标的 / 日期分块处理，避免无界加载。

项目规范见 [AGENTS.md](AGENTS.md)。数据与 Release 见 [DATA](docs/DATA.md)，执行命令见 [RUNTIME](docs/RUNTIME.md)，评测口径见 [STANDARD](docs/STANDARD.md)，历史策略研究见 [STRATEGY](docs/STRATEGY.md)，OpenD 环境见 [OPEND_SETUP](docs/OPEND_SETUP.md)。

```bash
# 查看现有策略；不连接交易账户
python3 -m custody strategies

# 检查已下载的真实期权数据
python3 -m custody check --dataset data/custody-0dte-v6.1
```

测试命令以 [AGENTS.md](AGENTS.md)「修改与验证」为准。

行情与策略研究入口不下单；只有 `custody/broker.py` 可使用 OpenD 交易接口。密码、令牌、运行数据库不提交。

代码采用 MIT 许可；Release 行情小样本用于个人研究和离线复现。
